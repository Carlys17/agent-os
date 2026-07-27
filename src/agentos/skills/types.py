"""Type definitions for the skills system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class SkillLayer(StrEnum):
    """Where a skill is loaded from (6-layer precedence, low→high)."""

    EXTRA = "extra"
    BUNDLED = "bundled"
    MANAGED = "managed"
    PERSONAL = "personal"
    PROJECT = "project"
    WORKSPACE = "workspace"


@dataclass
class SkillEnvVar:
    """One environment variable a skill needs, with enough context to fix it.

    A bare name tells an operator that something is missing but not what it is
    or where to get it. Skills may therefore declare the richer form::

        requires:
          env:
            - name: BASE_RPC_URL
              description: Base L2 RPC endpoint
              url: https://docs.base.org/
              secret: false

    The plain ``env: [BASE_RPC_URL]`` list keeps working — :meth:`coerce`
    upgrades it — so no existing skill manifest needs touching.
    """

    name: str
    description: str = ""
    url: str = ""
    #: ``None`` means "decide from the name"; skills override when the
    #: heuristic would be wrong (an endpoint URL ending in ``_KEY``, say).
    secret: bool | None = None
    required: bool = True

    @classmethod
    def coerce(cls, raw: Any) -> SkillEnvVar | None:
        """Return a :class:`SkillEnvVar` from a string, mapping, or instance.

        Returns ``None`` for anything unusable so one malformed manifest entry
        cannot make a whole skill fail to load.
        """
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, str):
            name = raw.strip()
            return cls(name=name) if name else None
        if isinstance(raw, dict):
            name = str(raw.get("name", "")).strip()
            if not name:
                return None
            secret = raw.get("secret")
            return cls(
                name=name,
                description=str(raw.get("description", "") or ""),
                url=str(raw.get("url", "") or ""),
                secret=secret if isinstance(secret, bool) else None,
                required=bool(raw.get("required", True)),
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-safe form used by the skill cache and RPC payloads."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "secret": self.secret,
            "required": self.required,
        }


@dataclass
class SkillConfigVar:
    """A non-secret setting a skill needs — a path, a mode, a default.

    Deliberately separate from :class:`SkillEnvVar`. Credentials belong in
    ``~/.agentos/.env`` where they can be masked and audited; a wiki directory
    or an output format is ordinary configuration and belongs in the TOML
    config under ``skills.config.<key>``, where it is visible, diffable, and
    safe to commit alongside the rest of a setup.

    Declared as::

        metadata:
          agentos:
            config:
              - key: wiki.path
                description: Path to the knowledge base directory
                default: "~/wiki"
    """

    key: str
    description: str = ""
    default: Any = None
    prompt: str = ""

    @classmethod
    def coerce(cls, raw: Any) -> SkillConfigVar | None:
        """Return a :class:`SkillConfigVar` from a mapping, or ``None``.

        An entry without a key or a description is skipped rather than
        raising — a malformed manifest should cost its own setting, not the
        whole skill.
        """
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, dict):
            return None
        key = str(raw.get("key", "")).strip()
        description = str(raw.get("description", "") or "").strip()
        if not key or not description:
            return None
        prompt = str(raw.get("prompt", "") or "").strip()
        return cls(
            key=key,
            description=description,
            default=raw.get("default"),
            prompt=prompt or description,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-safe form used by the skill cache and RPC payloads."""
        return {
            "key": self.key,
            "description": self.description,
            "default": self.default,
            "prompt": self.prompt,
        }


@dataclass
class SkillRequires:
    """Binary/env/config requirements for a skill."""

    bins: list[str] = field(default_factory=list)
    any_bins: list[str] = field(default_factory=list)
    env: list[SkillEnvVar] = field(default_factory=list)
    config: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Coerce here rather than at each construction site: manifests, the
        # on-disk skill cache, and tests all build this from raw data, and one
        # of them forgetting would silently produce strings where callers
        # expect structured entries.
        self.env = [entry for entry in map(SkillEnvVar.coerce, self.env) if entry is not None]

    @property
    def env_names(self) -> list[str]:
        """Return just the variable names, for callers that only check presence."""
        return [entry.name for entry in self.env]


@dataclass
class SkillInstallSpec:
    """How to install a skill's dependencies."""

    kind: str = ""  # brew | node | go | uv | download
    id: str = ""
    label: str = ""
    bins: list[str] = field(default_factory=list)
    os: list[str] = field(default_factory=list)
    formula: str = ""
    package: str = ""
    module: str = ""
    url: str = ""


@dataclass
class SkillPlatformMeta:
    """Platform requirements and metadata for a skill (OS, binaries, env, install)."""

    emoji: str = ""
    skill_key: str = ""
    primary_env: str = ""
    homepage: str = ""
    always: bool | None = None
    os: list[str] = field(default_factory=list)
    requires: SkillRequires | None = None
    install: list[SkillInstallSpec] = field(default_factory=list)
    # Advisory risk metadata. These are manifest fields, not runtime permissions.
    risk_level: str = ""
    capabilities: list[str] = field(default_factory=list)
    #: Non-secret settings the skill reads from ``skills.config.*``.
    config_vars: list[SkillConfigVar] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.config_vars = [
            entry for entry in map(SkillConfigVar.coerce, self.config_vars) if entry is not None
        ]


@dataclass(frozen=True)
class SkillProvenance:
    """Origin and stewardship metadata for release-facing skill surfaces."""

    origin: str = "unknown"
    license: str = "unknown"
    upstream_url: str = ""
    maintained_by: str = "AgentOS"


@dataclass
class SkillSpec:
    """Parsed skill metadata and content."""

    name: str
    description: str
    layer: SkillLayer
    always: bool
    triggers: list[str]
    content: str
    path: Path | None = None

    # Platform metadata
    metadata: SkillPlatformMeta | None = None
    provenance: SkillProvenance = field(default_factory=SkillProvenance)
    user_invocable: bool = True
    disable_model_invocation: bool = False
    homepage: str = ""
    file_path: str = ""
    base_dir: str = ""
    # Conditional activation metadata
    requires_tools: list[str] = field(default_factory=list)
    fallback_for_toolsets: list[str] = field(default_factory=list)
