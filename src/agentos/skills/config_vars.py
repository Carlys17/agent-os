"""Skill settings that are configuration rather than credentials.

A skill needs two different kinds of value from its operator, and conflating
them makes both worse:

* **Credentials** — an API key, a bot token. They belong in
  ``~/.agentos/.env``, where :mod:`agentos.env_store` masks them in listings,
  gates who may write them, and audits reads.
* **Settings** — a wiki directory, an output format, a default region. There
  is nothing to hide; hiding them just makes the setup harder to inspect,
  diff, and share. They belong in the TOML config under ``skills.config.*``,
  alongside everything else about how this install is set up.

This module handles the second kind: discovering what enabled skills declare,
and resolving the values currently in effect.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import structlog

from agentos.skills.types import SkillConfigVar

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agentos.skills.loader import SkillLoader

log = structlog.get_logger(__name__)

#: Where a skill's declared settings live in the TOML config.
SKILL_CONFIG_PREFIX = "skills.config"


def discover_skill_config_vars(loader: SkillLoader | None) -> list[tuple[str, SkillConfigVar]]:
    """Return ``(skill_name, declaration)`` for every declared setting.

    Duplicate keys across skills collapse to the first declaration — two skills
    naming the same key are asking for the same setting, and prompting twice
    for one value would be worse than picking one description.
    """
    if loader is None:
        return []
    try:
        skills = loader.load_all()
    except Exception:  # pragma: no cover - a broken loader must not break setup
        log.debug("skill_config.scan_failed", exc_info=True)
        return []

    found: list[tuple[str, SkillConfigVar]] = []
    seen: set[str] = set()
    for skill in skills:
        meta = getattr(skill, "metadata", None)
        for declared in getattr(meta, "config_vars", []) or []:
            if declared.key in seen:
                continue
            seen.add(declared.key)
            found.append((skill.name, declared))
    return found


def _value_at(config: Any, dotted_key: str) -> Any:
    """Walk ``skills.config.<dotted_key>`` on a config object or mapping."""
    current: Any = config
    for part in f"{SKILL_CONFIG_PREFIX}.{dotted_key}".split("."):
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        else:
            current = getattr(current, part, None)
            if current is None:
                return None
    return current


def resolve_skill_config_values(
    declarations: list[SkillConfigVar],
    config: Any,
) -> dict[str, Any]:
    """Return the value in effect for each declaration, falling back to its default.

    ``~`` and ``$VAR`` are expanded in string values, because these settings are
    overwhelmingly paths and an unexpanded ``~/wiki`` is a directory literally
    named ``~``.
    """
    resolved: dict[str, Any] = {}
    for declared in declarations:
        value = _value_at(config, declared.key)
        if value is None or (isinstance(value, str) and not value.strip()):
            value = declared.default
        if isinstance(value, str) and ("~" in value or "$" in value):
            value = os.path.expanduser(os.path.expandvars(value))
        resolved[declared.key] = value
    return resolved


def missing_skill_config_vars(
    loader: SkillLoader | None,
    config: Any,
) -> list[dict[str, Any]]:
    """Return declarations that have neither a configured value nor a default.

    A declaration with a usable default is not missing — the skill works out
    of the box and the operator only needs to know about it if they want
    something else.
    """
    missing: list[dict[str, Any]] = []
    for skill_name, declared in discover_skill_config_vars(loader):
        value = _value_at(config, declared.key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if declared.default not in (None, ""):
                continue
            missing.append({**declared.to_dict(), "skill": skill_name})
    return missing


def render_skill_config_block(skill: Any, config: Any, config_path: str = "") -> str:
    """Return a ``[Skill config: …]`` block for *skill*, or ``""`` when it declares none.

    Appended to what ``skill_view`` returns so the agent starts with the values
    already in effect instead of guessing, asking the user, or going to read
    the config file itself. Skills that declare nothing cost nothing.
    """
    meta = getattr(skill, "metadata", None)
    declarations = list(getattr(meta, "config_vars", []) or [])
    if not declarations:
        return ""

    values = resolve_skill_config_values(declarations, config)
    where = f" (from {config_path})" if config_path else ""
    lines = [f"\n\n[Skill config{where}:"]
    for declared in declarations:
        value = values.get(declared.key)
        shown = str(value) if value not in (None, "") else "(not set)"
        lines.append(f"  {declared.key} = {shown}")
    lines.append("]")
    return "\n".join(lines)
