"""`skills.uninstall` addresses the lockfile key, not the name it is called with.

Every surface names a skill the way its ``SKILL.md`` does; the installer names
it the way the lockfile does, which is the directory the bundle was written
into. Those differ for published skills whose manifest renames them — hub
``ytdlp-transcript`` ships a manifest named ``youtube-transcript`` — and the
Remove button reported "not found" for an install sitting on disk.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentos.gateway import rpc_skills
from agentos.gateway.rpc import RpcContext
from agentos.skills.hub.installer import InstallResult
from agentos.skills.hub.lockfile import LockEntry, Lockfile
from agentos.skills.loader import SkillLoader


class _RecordingInstaller:
    """Stands in for :class:`~agentos.skills.hub.installer.SkillInstaller`.

    Mirrors only the two coroutines the handlers call, with the same signatures
    and return type, so a drift in either is a test failure rather than a fake
    that quietly keeps passing.
    """

    def __init__(self) -> None:
        self.uninstalled: list[str] = []
        self.updated: list[str | None] = []

    async def uninstall(self, name: str) -> InstallResult:
        self.uninstalled.append(name)
        return InstallResult(success=True, name=name, message=f"Uninstalled '{name}'")

    async def update(self, name: str | None = None) -> list[InstallResult]:
        self.updated.append(name)
        return [InstallResult(success=True, name=name or "", message="updated")]


def _install(managed_dir: Path, directory: str, manifest_name: str) -> Path:
    skill_dir = managed_dir / directory
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {manifest_name}\ndescription: Renamed by its manifest.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return skill_dir


def _lockfile(tmp_path: Path, key: str, install_dir: Path) -> Path:
    lock_path = tmp_path / "skills-lock.json"
    lockfile = Lockfile()
    lockfile.add(key, LockEntry(source="clawhub", identifier="id", path=str(install_dir)))
    lockfile.save(lock_path)
    return lock_path


@pytest.fixture
def wired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RpcContext, _RecordingInstaller]:
    managed_dir = tmp_path / "managed"
    install_dir = _install(managed_dir, "ytdlp-transcript", "youtube-transcript")
    lock_path = _lockfile(tmp_path, "ytdlp-transcript", install_dir)
    monkeypatch.setattr(rpc_skills, "default_lockfile_path", lambda: lock_path)

    installer = _RecordingInstaller()
    monkeypatch.setattr(
        rpc_skills,
        "build_default_skill_installer",
        lambda *, managed_dir=None: installer,
    )
    loader = SkillLoader(managed_dir=managed_dir, snapshot_path=tmp_path / "snapshot.json")
    return RpcContext(conn_id="test", skill_loader=loader), installer


def test_uninstall_translates_a_manifest_name_into_its_lockfile_key(
    wired: tuple[RpcContext, _RecordingInstaller],
) -> None:
    ctx, installer = wired

    result = asyncio.run(rpc_skills._handle_skills_uninstall({"name": "youtube-transcript"}, ctx))

    assert installer.uninstalled == ["ytdlp-transcript"]
    assert result["success"] is True


def test_update_translates_the_same_way(
    wired: tuple[RpcContext, _RecordingInstaller],
) -> None:
    ctx, installer = wired

    asyncio.run(rpc_skills._handle_skills_update({"name": "youtube-transcript"}, ctx))

    assert installer.updated == ["ytdlp-transcript"]


def test_update_with_no_name_still_means_every_skill(
    wired: tuple[RpcContext, _RecordingInstaller],
) -> None:
    """A bare `skills.update` updates everything; translation must not invent a target."""
    ctx, installer = wired

    asyncio.run(rpc_skills._handle_skills_update({}, ctx))

    assert installer.updated == [None]


def test_a_name_no_skill_loads_under_is_passed_through(
    wired: tuple[RpcContext, _RecordingInstaller],
) -> None:
    """Clearing a stale lockfile entry by its own key has to keep working."""
    ctx, installer = wired

    asyncio.run(rpc_skills._handle_skills_uninstall({"name": "long-gone"}, ctx))

    assert installer.uninstalled == ["long-gone"]
