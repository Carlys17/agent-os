"""Acquisition is derived from the lockfile, and never promises a broken action."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentos.skills.availability import REASON_PROMPT_BUDGET, REASON_TOOL_GATE
from agentos.skills.hub.installer import SkillInstaller
from agentos.skills.hub.lockfile import LockEntry, Lockfile
from agentos.skills.hub.source import SkillBundle, SkillMeta
from agentos.skills.inventory import SkillRow, build_skill_inventory
from agentos.skills.loader import SkillLoader
from agentos.skills.publishers import RECOGNIZED_PUBLISHERS
from agentos.skills.types import AcquisitionKind, SkillPublisher

BANKR = RECOGNIZED_PUBLISHERS["bankr"]
ROBINHOOD = RECOGNIZED_PUBLISHERS["robinhood"]


def _write_skill(root: Path, name: str, extra_frontmatter: str = "") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Synthetic skill.\n{extra_frontmatter}---\n\n# body\n",
        encoding="utf-8",
    )
    return skill_dir


def _loader(tmp_path: Path, **kwargs: Path | None) -> SkillLoader:
    """Build a loader with no snapshot cache, so every call re-reads disk."""
    return SkillLoader(snapshot_path=tmp_path / "cache" / "snapshot.json", **kwargs)


def _lockfile(lock_path: Path, name: str, **fields: str) -> Path:
    lockfile = Lockfile()
    lockfile.add(name, LockEntry(source=fields.pop("source", "bankr"), **fields))
    lockfile.save(lock_path)
    return lock_path


def _row(rows: list[SkillRow], name: str) -> SkillRow:
    return next(row for row in rows if row.spec.name == name)


# ── Acquisition kinds ────────────────────────────────────────────────────────


def test_a_bundled_skill_is_shipped(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    _write_skill(bundled, "shipped-one")

    rows = build_skill_inventory(
        _loader(tmp_path, bundled_dir=bundled),
        lockfile_path=tmp_path / "lock.json",
    )

    assert [row.spec.name for row in rows] == ["shipped-one"]
    assert rows[0].acquisition.kind is AcquisitionKind.SHIPPED
    assert rows[0].acquisition.removable is False
    assert rows[0].acquisition.updatable is False


def test_a_directory_with_no_lockfile_entry_is_local(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_skill(workspace, "hand-written")

    rows = build_skill_inventory(
        _loader(tmp_path, workspace_dir=workspace),
        lockfile_path=tmp_path / "lock.json",
    )

    assert rows[0].acquisition.kind is AcquisitionKind.LOCAL
    assert rows[0].acquisition.removable is False


def test_a_lockfile_entry_makes_it_a_hub_install(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    install_dir = _write_skill(managed, "from-a-hub")
    lock = _lockfile(
        tmp_path / "lock.json",
        "from-a-hub",
        source="bankr",
        identifier="https://example.com/skills/from-a-hub",
        installed_at="2026-01-01T00:00:00Z",
        path=str(install_dir),
        source_trust="community",
        scan_verdict="clean",
    )

    rows = build_skill_inventory(_loader(tmp_path, managed_dir=managed), lockfile_path=lock)

    acquisition = rows[0].acquisition
    assert acquisition.kind is AcquisitionKind.HUB
    assert acquisition.source_id == "bankr"
    assert acquisition.identifier == "https://example.com/skills/from-a-hub"
    assert acquisition.installed_at == "2026-01-01T00:00:00Z"
    assert acquisition.source_trust == "community"
    assert acquisition.scan_verdict == "clean"
    assert acquisition.removable is True
    assert acquisition.updatable is True
    assert acquisition.detail == ""


def test_a_hub_install_stays_hub_even_when_it_loads_from_another_layer(tmp_path: Path) -> None:
    """The lockfile, not the layer, decides whether an operator installed it."""
    workspace = tmp_path / "workspace"
    install_dir = _write_skill(workspace, "relocated")
    lock = _lockfile(tmp_path / "lock.json", "relocated", identifier="id", path=str(install_dir))

    rows = build_skill_inventory(_loader(tmp_path, workspace_dir=workspace), lockfile_path=lock)

    assert rows[0].acquisition.kind is AcquisitionKind.HUB


# ── Guards: never offer an action that would half-succeed ────────────────────


def test_a_custom_managed_dir_withholds_uninstall_and_says_why(tmp_path: Path) -> None:
    """The lockfile path comes from the state root; the managed dir is
    config-overridable. When they disagree, Uninstall would drop the lockfile
    entry and leave the files behind."""
    elsewhere = tmp_path / "elsewhere"
    install_dir = _write_skill(elsewhere, "diverged")
    configured = tmp_path / "configured"
    _write_skill(configured, "diverged")
    lock = _lockfile(tmp_path / "lock.json", "diverged", identifier="id", path=str(install_dir))

    rows = build_skill_inventory(_loader(tmp_path, managed_dir=configured), lockfile_path=lock)

    acquisition = rows[0].acquisition
    assert acquisition.kind is AcquisitionKind.HUB
    assert acquisition.removable is False
    assert str(install_dir) in acquisition.detail
    assert str(configured) in acquisition.detail
    # Re-fetching by identifier still works, so the update affordance stays.
    assert acquisition.updatable is True


def test_an_orphaned_entry_does_not_claim_to_be_removable(tmp_path: Path) -> None:
    """Someone deleted the managed copy by hand; the entry outlived its files.

    The skill still loads — from a workspace copy — so it still gets a row, and
    that row must not offer to uninstall a directory that is already gone.
    """
    managed = tmp_path / "managed"
    managed.mkdir()
    workspace = tmp_path / "workspace"
    _write_skill(workspace, "survivor")
    lock = _lockfile(
        tmp_path / "lock.json",
        "survivor",
        identifier="id",
        path=str(managed / "survivor"),
    )

    rows = build_skill_inventory(
        _loader(tmp_path, managed_dir=managed, workspace_dir=workspace),
        lockfile_path=lock,
    )

    acquisition = _row(rows, "survivor").acquisition
    assert acquisition.kind is AcquisitionKind.HUB
    assert acquisition.removable is False
    assert str(managed / "survivor") in acquisition.detail


def test_no_managed_dir_at_all_withholds_uninstall(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_skill(workspace, "orphan")
    lock = _lockfile(tmp_path / "lock.json", "orphan", identifier="id")

    rows = build_skill_inventory(
        SkillLoader(workspace_dir=workspace, snapshot_path=tmp_path / "snap.json"),
        lockfile_path=lock,
    )

    assert rows[0].acquisition.removable is False
    assert rows[0].acquisition.detail


# ── Publisher carried through a hub install ─────────────────────────────────


def test_a_hub_entry_supplies_the_brand_a_manifest_never_declared(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    install_dir = _write_skill(managed, "branded")
    lock = _lockfile(
        tmp_path / "lock.json",
        "branded",
        identifier="id",
        path=str(install_dir),
        publisher_id="bankr",
        publisher_name="Bankr",
    )

    rows = build_skill_inventory(_loader(tmp_path, managed_dir=managed), lockfile_path=lock)

    assert rows[0].spec.publisher == SkillPublisher()
    assert rows[0].publisher == BANKR


def test_a_hub_cannot_mint_a_brand_either(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    install_dir = _write_skill(managed, "impostor")
    lock = _lockfile(
        tmp_path / "lock.json",
        "impostor",
        identifier="id",
        path=str(install_dir),
        publisher_id="acme-capital",
        publisher_name="Robinhood",
    )

    rows = build_skill_inventory(_loader(tmp_path, managed_dir=managed), lockfile_path=lock)

    assert rows[0].publisher == SkillPublisher()


def test_a_partner_installed_before_publisher_ids_existed_keeps_its_brand(tmp_path: Path) -> None:
    """An upgrading machine must not silently lose the Partners grouping.

    Every lockfile written before ``publisher_id`` existed has an empty one, so
    a Bankr skill installed on the previous release would fall out of Partners
    and into "Installed from a hub" until it was reinstalled — the exact split
    heading this issue set out to remove. The source is the same selector
    install time falls back to, so it resolves to the same allowlisted record.
    """
    managed = tmp_path / "managed"
    install_dir = _write_skill(managed, "legacy-install")
    lock = _lockfile(
        tmp_path / "lock.json",
        "legacy-install",
        source="bankr",
        identifier="id",
        path=str(install_dir),
    )

    rows = build_skill_inventory(_loader(tmp_path, managed_dir=managed), lockfile_path=lock)

    assert rows[0].publisher == BANKR


def test_an_unrecognized_source_still_grants_no_brand(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    install_dir = _write_skill(managed, "community-install")
    lock = _lockfile(
        tmp_path / "lock.json",
        "community-install",
        source="clawhub",
        identifier="id",
        path=str(install_dir),
    )

    rows = build_skill_inventory(_loader(tmp_path, managed_dir=managed), lockfile_path=lock)

    assert rows[0].publisher == SkillPublisher()


def test_an_installed_skill_cannot_rebrand_itself_over_the_lockfile(tmp_path: Path) -> None:
    """The catalog row that installed it is the trusted source, not its own text."""

    managed = tmp_path / "managed"
    install_dir = _write_skill(managed, "declared", "publisher:\n  id: robinhood\n")
    lock = _lockfile(
        tmp_path / "lock.json",
        "declared",
        identifier="id",
        path=str(install_dir),
        publisher_id="bankr",
    )

    rows = build_skill_inventory(_loader(tmp_path, managed_dir=managed), lockfile_path=lock)

    assert rows[0].spec.publisher == SkillPublisher()
    assert rows[0].publisher == BANKR


def test_a_bundled_skill_keeps_the_brand_it_declares(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    _write_skill(bundled, "shipped-partner", "publisher:\n  id: robinhood\n")

    rows = build_skill_inventory(
        _loader(tmp_path, bundled_dir=bundled),
        lockfile_path=tmp_path / "lock.json",
    )

    assert rows[0].publisher == ROBINHOOD


# ── LockEntry schema ────────────────────────────────────────────────────────


def test_lock_entry_round_trips_the_publisher_fields(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"
    lockfile = Lockfile()
    lockfile.add(
        "demo",
        LockEntry(
            source="bankr",
            identifier="id",
            publisher_id="bankr",
            publisher_name="Bankr",
        ),
    )
    lockfile.save(path)

    entry = Lockfile.load(path).get("demo")
    assert entry is not None
    assert entry.publisher_id == "bankr"
    assert entry.publisher_name == "Bankr"


def test_an_entry_written_before_publisher_fields_existed_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "installed": {"demo": {"source": "clawhub", "identifier": "demo", "sha256": "abc"}},
            }
        ),
        encoding="utf-8",
    )

    entry = Lockfile.load(path).get("demo")
    assert entry is not None
    assert entry.identifier == "demo"
    assert entry.publisher_id == ""
    assert entry.publisher_name == ""


# ── Install writes the publisher ────────────────────────────────────────────


class _StubRouter:
    """Router returning one fixed bundle, so install() can be driven offline."""

    def __init__(self, meta: SkillMeta | None) -> None:
        self._meta = meta

    async def fetch(self, identifier: str, source_id: str) -> SkillBundle:
        body = "---\nname: demo\ndescription: Use when testing.\n---\n\n# Demo\n"
        return SkillBundle(name="demo", files={"SKILL.md": body}, meta=self._meta)

    async def inspect(self, identifier: str, source_id: str) -> SkillMeta | None:
        return self._meta


def _stub_installer(tmp_path: Path, meta: SkillMeta | None) -> SkillInstaller:
    return SkillInstaller(
        router=_StubRouter(meta),  # type: ignore[arg-type]
        managed_dir=tmp_path / "managed",
        quarantine_dir=tmp_path / "quarantine",
        lockfile_path=tmp_path / "lock.json",
    )


@pytest.mark.asyncio
async def test_install_records_the_catalog_provider_as_the_publisher(tmp_path: Path) -> None:
    meta = SkillMeta(name="demo", source_id="bankr", provider="Bankr")
    result = await _stub_installer(tmp_path, meta).install("demo", "bankr")

    assert result.success
    entry = Lockfile.load(tmp_path / "lock.json").get("demo")
    assert entry is not None
    assert entry.publisher_id == "bankr"
    assert entry.publisher_name == "Bankr"


@pytest.mark.asyncio
async def test_install_falls_back_to_the_source_when_no_provider_is_declared(
    tmp_path: Path,
) -> None:
    meta = SkillMeta(name="demo", source_id="bankr", provider="")
    await _stub_installer(tmp_path, meta).install("demo", "bankr")

    entry = Lockfile.load(tmp_path / "lock.json").get("demo")
    assert entry is not None
    assert entry.publisher_id == "bankr"


@pytest.mark.asyncio
async def test_install_records_the_version_the_row_advertises(tmp_path: Path) -> None:
    """``acquisition.version`` is on the wire, so it has to be written."""
    meta = SkillMeta(name="demo", source_id="clawhub", version="2.1.0")
    await _stub_installer(tmp_path, meta).install("demo", "clawhub")

    entry = Lockfile.load(tmp_path / "lock.json").get("demo")
    assert entry is not None
    assert entry.version == "2.1.0"

    rows = build_skill_inventory(
        _loader(tmp_path, managed_dir=tmp_path / "managed"),
        lockfile_path=tmp_path / "lock.json",
    )
    assert rows[0].acquisition.version == "2.1.0"


@pytest.mark.asyncio
async def test_an_unrecognized_provider_installs_unbranded(tmp_path: Path) -> None:
    meta = SkillMeta(name="demo", source_id="github", provider="Acme Capital")
    await _stub_installer(tmp_path, meta).install("demo", "github")

    entry = Lockfile.load(tmp_path / "lock.json").get("demo")
    assert entry is not None
    # The raw claim is kept for diagnostics, but it resolves to nothing.
    assert entry.publisher_id == "acme-capital"
    assert entry.publisher_name == "Acme Capital"

    rows = build_skill_inventory(
        _loader(tmp_path, managed_dir=tmp_path / "managed"),
        lockfile_path=tmp_path / "lock.json",
    )
    assert rows[0].publisher == SkillPublisher()


# ── The builder itself ──────────────────────────────────────────────────────


def test_one_row_per_loaded_skill_with_every_derived_fact(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    _write_skill(bundled, "shipped-one")
    _write_skill(bundled, "shipped-two")
    managed = tmp_path / "managed"
    install_dir = _write_skill(managed, "hub-one")
    lock = _lockfile(
        tmp_path / "lock.json",
        "hub-one",
        identifier="id",
        path=str(install_dir),
        publisher_id="bankr",
    )

    rows = build_skill_inventory(
        _loader(tmp_path, bundled_dir=bundled, managed_dir=managed),
        lockfile_path=lock,
        available_tools=set(),
    )

    assert {row.spec.name for row in rows} == {"shipped-one", "shipped-two", "hub-one"}
    assert all(row.eligibility.eligible for row in rows)
    assert all(row.availability is not None and row.availability.offered for row in rows)
    assert all(row.acquisition.kind for row in rows)
    assert _row(rows, "shipped-one").acquisition.kind is AcquisitionKind.SHIPPED
    assert _row(rows, "hub-one").acquisition.kind is AcquisitionKind.HUB
    assert _row(rows, "hub-one").publisher == BANKR


def test_availability_is_answered_only_when_a_tool_set_is_supplied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_skill(
        workspace,
        "needs-tools",
        "metadata:\n  agentos:\n    requires_tools: [web_search]\n",
    )
    loader = _loader(tmp_path, workspace_dir=workspace)
    lock = tmp_path / "lock.json"

    assert loader.load_all()[0].requires_tools == ["web_search"]
    # No tool set supplied → no claim either way, rather than a guess that would
    # report every tool-gated skill as unavailable.
    assert build_skill_inventory(loader, lockfile_path=lock)[0].availability is None

    rows = build_skill_inventory(loader, lockfile_path=lock, available_tools=set())
    availability = rows[0].availability
    assert availability is not None
    assert availability.offered is False
    assert availability.reason == REASON_TOOL_GATE

    rows = build_skill_inventory(loader, lockfile_path=lock, available_tools={"web_search"})
    availability = rows[0].availability
    assert availability is not None
    assert availability.offered is True


def test_managed_dir_falls_back_to_config_when_the_loader_has_none(tmp_path: Path) -> None:
    """CLI paths build a loader without a managed dir; the guard still needs one."""
    managed = tmp_path / "managed"
    install_dir = _write_skill(managed, "configured-only")
    lock = _lockfile(
        tmp_path / "lock.json", "configured-only", identifier="id", path=str(install_dir)
    )

    class _Skills:
        managed_dir = str(managed)

    class _Config:
        skills = _Skills()

    rows = build_skill_inventory(
        SkillLoader(workspace_dir=managed, snapshot_path=tmp_path / "snap.json"),
        config=_Config(),
        lockfile_path=lock,
    )

    assert rows[0].acquisition.removable is True


def test_a_stale_lockfile_entry_cannot_make_a_shipped_skill_look_installed(
    tmp_path: Path,
) -> None:
    """A bundled skill is never a hub install, whatever the lockfile says.

    The bundled directory lives inside the installed package and is not
    configurable, so nothing can be installed into it. An entry whose name
    collides with a shipped skill is a leftover from a different, since-removed
    install; honoring it would render a shipped skill with a source label and a
    Remove button that cannot apply.
    """
    bundled = tmp_path / "bundled"
    _write_skill(bundled, "collides")
    lock = _lockfile(
        tmp_path / "lock.json",
        "collides",
        identifier="id",
        path=str(tmp_path / "managed" / "collides"),
        publisher_id="bankr",
    )

    rows = build_skill_inventory(
        _loader(tmp_path, bundled_dir=bundled, managed_dir=tmp_path / "managed"),
        lockfile_path=lock,
        available_tools=set(),
    )

    acquisition = _row(rows, "collides").acquisition
    assert acquisition.kind is AcquisitionKind.SHIPPED
    assert acquisition.removable is False
    assert acquisition.source_id == ""
    # And the stale entry must not lend it a partner's brand either.
    assert _row(rows, "collides").publisher == SkillPublisher()


def test_a_row_reports_the_budget_that_will_drop_it(tmp_path: Path) -> None:
    """`prompt_budget` has to be answerable without a turn.

    It depends only on the installed set and the configured budget, both known
    here — so the Skills page can say "installed, ready, but the block is full"
    instead of implying the agent has a skill it is never offered.
    """
    workspace = tmp_path / "workspace"
    for i in range(6):
        _write_skill(workspace, f"skill-{i:02d}")
    loader = _loader(tmp_path, workspace_dir=workspace)
    lock = tmp_path / "lock.json"

    class _Skills:
        max_skills_prompt_chars = 120
        injection_mode = "system"

    class _Config:
        skills = _Skills()

    rows = build_skill_inventory(
        loader, config=_Config(), lockfile_path=lock, available_tools=set()
    )

    dropped = [r for r in rows if r.availability and r.availability.reason == REASON_PROMPT_BUDGET]
    assert dropped, "a 120-char budget cannot fit six skills"
    assert all(r.eligibility.eligible for r in dropped), "dropped for budget, not for eligibility"
    assert all("120" in (r.availability.detail if r.availability else "") for r in dropped)

    # A budget with room reports every skill as offered.
    class _RoomySkills:
        max_skills_prompt_chars = 30_000
        injection_mode = "system"

    class _RoomyConfig:
        skills = _RoomySkills()

    rows = build_skill_inventory(
        loader, config=_RoomyConfig(), lockfile_path=lock, available_tools=set()
    )
    assert all(r.availability is not None and r.availability.offered for r in rows)
