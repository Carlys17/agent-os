"""One inventory builder for every "what skills does this install have" surface.

``skills.list``, ``skills.status``, ``skills.get``, the ``skill_list`` tool, and
``agentos skills list`` each used to assemble their own answer, which is why they
disagreed: only one of them read the lockfile, so a hub-installed skill looked
like an ordinary local directory everywhere else. This module derives the whole
row once — eligibility, acquisition, publisher — and every surface renders the
same facts.

Nothing here is cached. Acquisition depends on the lockfile, which changes
without any ``SKILL.md`` mtime changing, so the skill snapshot deliberately does
not carry it; see :class:`~agentos.skills.types.SkillAcquisition`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentos.skills.availability import SkillAvailability, gate_skills, plan_injection
from agentos.skills.eligibility import (
    EligibilityContext,
    EligibilityReport,
    diagnose_eligibility,
)
from agentos.skills.hub.lockfile import LockEntry, Lockfile, default_lockfile_path
from agentos.skills.injector import DEFAULT_MAX_SKILLS_PROMPT_CHARS
from agentos.skills.loader import SkillLoader
from agentos.skills.publishers import resolve_publisher
from agentos.skills.types import (
    AcquisitionKind,
    SkillAcquisition,
    SkillLayer,
    SkillPublisher,
    SkillSpec,
)

__all__ = [
    "SkillRow",
    "acquisition_payload",
    "availability_payload",
    "build_skill_inventory",
    "publisher_payload",
]


@dataclass(frozen=True)
class SkillRow:
    """A loaded skill plus everything a surface needs to render it."""

    spec: SkillSpec
    eligibility: EligibilityReport
    acquisition: SkillAcquisition
    publisher: SkillPublisher
    #: Whether the agent would be offered this skill, from
    #: :func:`~agentos.skills.availability.gate_skills`. ``None`` when the
    #: caller supplied no tool set: two of the gates read one, and guessing an
    #: empty set would report every tool-gated skill as unavailable.
    availability: SkillAvailability | None = None


def build_skill_inventory(
    loader: SkillLoader,
    *,
    config: Any | None = None,
    lockfile_path: Path | None = None,
    available_tools: set[str] | None = None,
) -> list[SkillRow]:
    """Return one row per loaded skill, in loader precedence order.

    Args:
        loader: Supplies the skills and the managed directory the acquisition
            guard checks recorded install paths against.
        config: Optional gateway config, consulted for ``skills.managed_dir``
            when the loader carries no managed directory, and for the prompt
            budget the availability answer is measured against.
        lockfile_path: Override for the shared lockfile; defaults to
            :func:`~agentos.skills.hub.lockfile.default_lockfile_path`.
        available_tools: Tool names this session can offer. Supplying it fills
            :attr:`SkillRow.availability`; omitting it leaves that ``None``,
            because the tool-gate and fallback gates cannot be answered
            without one.
    """
    skills = loader.load_all()
    lock_path = lockfile_path if lockfile_path is not None else default_lockfile_path()
    lockfile = Lockfile.load(lock_path)
    managed_dir = _managed_dir(loader, config)
    # One context for the whole sweep — it caches binary lookups across skills —
    # but built here rather than at import time, so a credential added since the
    # process started is seen on the next call.
    elig_ctx = EligibilityContext.auto()
    # The turn pipeline runs the same gates, so a row and the prompt agree on
    # which skills the agent is being offered.
    availability: dict[str, SkillAvailability] = {}
    if available_tools is not None:
        gated, availability = gate_skills(skills, available_tools, elig_ctx)
        # The budget gate is *not* turn-specific: it depends only on the gated
        # set and the configured budget, both of which are known here. Running
        # it is what lets a row say "installed and ready, but the skills block
        # is full" instead of claiming the agent has a skill it is never
        # offered — the half of the answer a Skills page could not give before.
        # Retrieval is the one genuinely per-turn gate and stays out: it ranks
        # against the user's message, so there is no query to answer it with.
        skills_cfg = getattr(config, "skills", None) if config is not None else None
        plan = plan_injection(
            gated,
            getattr(skills_cfg, "max_skills_prompt_chars", DEFAULT_MAX_SKILLS_PROMPT_CHARS),
            getattr(skills_cfg, "injection_mode", "system"),
            # Derived from the same tool set the gate just used. Guessing it
            # would change the block's header length, which moves the point a
            # tight budget truncates at — and then a row here and the prompt the
            # engine builds would disagree about which skills are offered.
            skill_list_tool="skill_list" in available_tools,
        )
        availability = {**availability, **plan.availability}

    rows: list[SkillRow] = []
    for spec in skills:
        entry = lockfile.get(spec.name)
        rows.append(
            SkillRow(
                spec=spec,
                eligibility=diagnose_eligibility(spec, elig_ctx),
                acquisition=_derive_acquisition(spec, entry, managed_dir),
                publisher=_derive_publisher(spec, entry),
                availability=availability.get(spec.name),
            )
        )
    return rows


def publisher_payload(publisher: SkillPublisher | None) -> dict[str, Any]:
    """Serialize an allowlisted publisher; all-empty when a skill has none.

    Lives here rather than beside any one surface: the gateway, the CLI, and the
    agent's own ``skill_list`` all emit these three blocks, and a second copy of
    the key names is exactly how they drifted apart before. Always present, so a
    consumer reads ``row["publisher"]["id"]`` without a guard and tests one
    thing — an empty ``id`` means unbranded.
    """
    p = publisher or SkillPublisher()
    return {"id": p.id, "name": p.name, "url": p.url, "logo": p.logo}


def acquisition_payload(acquisition: SkillAcquisition | None) -> dict[str, Any]:
    """Serialize how a skill was acquired and what an operator may do to it.

    :attr:`SkillAcquisition.detail` is deliberately left off the wire: it names
    filesystem paths, and this payload reaches the agent's ``skill_list`` as
    well as the Web UI. A surface that wants to explain a withheld affordance
    reads it off the row.
    """
    a = acquisition or SkillAcquisition()
    return {
        "kind": str(a.kind),
        "source_id": a.source_id,
        "identifier": a.identifier,
        "version": a.version,
        "installed_at": a.installed_at,
        "source_trust": a.source_trust,
        "scan_verdict": a.scan_verdict,
        "removable": a.removable,
        "updatable": a.updatable,
    }


def availability_payload(availability: SkillAvailability) -> dict[str, Any]:
    """Serialize whether the agent is being offered a skill, and why not."""
    return {
        "offered": availability.offered,
        "reason": availability.reason,
        "detail": availability.detail,
    }


def _managed_dir(loader: SkillLoader, config: Any | None) -> Path | None:
    """Return the directory ``skills.uninstall`` would actually delete from."""
    if loader.managed_dir is not None:
        return loader.managed_dir
    configured = getattr(getattr(config, "skills", None), "managed_dir", None)
    return Path(configured).expanduser() if configured else None


def _derive_publisher(spec: SkillSpec, entry: LockEntry | None) -> SkillPublisher:
    """Return the brand for a row: declared by a bundled manifest, else the hub's.

    Only a bundled ``SKILL.md`` may name its own publisher (see
    :mod:`agentos.skills.publishers`), so ``spec.publisher`` is already empty for
    anything an operator or a hub put on disk. A hub install gets its brand from
    the catalog row that installed it, which the lockfile carries forward. Either
    way the declaration is only a selector: the allowlist supplies every displayed
    field, so neither a manifest nor a hub can invent a brand.

    ``entry.source`` is the fallback selector because that is exactly what
    install time falls back to (``installer._publisher_slug``). Without it every
    lockfile written before ``publisher_id`` existed — i.e. every partner skill
    already installed on an upgrading machine — would lose its brand and drop
    out of the Partners group until it was reinstalled.

    A shipped skill never consults the lockfile: nothing can be installed into
    the packaged bundled directory, so an entry under that name belongs to a
    different, since-removed install and must not lend its brand across the
    collision. See :func:`_derive_acquisition`, which drops the same entry.
    """
    if spec.publisher.id:
        return spec.publisher
    if entry is not None and spec.layer != SkillLayer.BUNDLED:
        return resolve_publisher(entry.publisher_id or entry.source)
    return SkillPublisher()


def _derive_acquisition(
    spec: SkillSpec,
    entry: LockEntry | None,
    managed_dir: Path | None,
) -> SkillAcquisition:
    """Classify how a skill got here, and what an operator may do to it.

    The lockfile wins over the layer: a hub install stays a hub install even
    when an operator has pointed ``skills.managed_dir`` somewhere else and the
    loader now reads it from a different layer.

    The one exception is ``BUNDLED``. That directory is ``skills/bundled`` inside
    the installed package (:func:`~agentos.skills.paths.default_bundled_skills_dir`)
    and is not configurable, so nothing can ever be installed into it. A lockfile
    entry whose name matches a shipped skill is therefore a collision with some
    *other*, since-removed install — honoring it would show a shipped skill as
    hub-acquired, with a source label and a Remove button that cannot apply.
    """
    if entry is None or spec.layer == SkillLayer.BUNDLED:
        shipped = spec.layer == SkillLayer.BUNDLED
        return SkillAcquisition(kind=AcquisitionKind.SHIPPED if shipped else AcquisitionKind.LOCAL)

    removable, detail = _removability(spec.name, entry, managed_dir)
    return SkillAcquisition(
        kind=AcquisitionKind.HUB,
        source_id=entry.source,
        identifier=entry.identifier,
        version=entry.version,
        installed_at=entry.installed_at,
        source_trust=entry.source_trust,
        scan_verdict=entry.scan_verdict,
        removable=removable,
        # An update re-fetches by identifier and writes into the *current*
        # managed dir, so it still works when the recorded path has diverged.
        updatable=bool(entry.identifier),
        detail=detail,
    )


def _removability(name: str, entry: LockEntry, managed_dir: Path | None) -> tuple[bool, str]:
    """Return whether ``skills.uninstall`` can act, and why not when it cannot.

    ``SkillInstaller.uninstall`` deletes ``<managed_dir>/<name>`` and nothing
    else. The lockfile path, however, is resolved from the state root while the
    managed directory is config-overridable, so the two can point at different
    places — and then an Uninstall button removes the lockfile entry while
    leaving the files on disk. Report the mismatch instead of offering an
    action that will half-succeed.
    """
    if managed_dir is None:
        return False, "No managed skills directory is configured, so this cannot be uninstalled."

    target = managed_dir / name
    recorded = Path(entry.path).expanduser() if entry.path else target
    if not _same_path(recorded, target):
        return False, (
            f"Recorded at {recorded}, which is outside the configured managed "
            f"skills directory ({managed_dir}). Uninstalling would drop the lockfile "
            "entry without removing those files."
        )
    if not target.exists():
        return False, (
            f"Nothing left at {target} — the directory was removed outside AgentOS. "
            "The lockfile entry is stale."
        )
    return True, ""


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:  # pragma: no cover - resolve() only raises on exotic filesystems
        return False
