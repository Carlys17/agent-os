"""The skill directories are not exclusively ours.

``agentos skills install`` runs in its own process, and ``.agents/skills`` is a
cross-agent directory that Codex, Cursor, and others write into while an AgentOS
gateway is already running. Both used to leave a skill on disk and invisible
until the next restart, with no log and no user-visible signal.
"""

from __future__ import annotations

from pathlib import Path

from agentos.skills.loader import SkillLoader
from agentos.skills.paths import resolve_skill_layer_dirs
from agentos.skills.types import SkillLayer


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} does a thing.\n---\nBody.\n",
        encoding="utf-8",
    )


def test_a_skill_another_agent_writes_lands_without_an_invalidate(tmp_path: Path) -> None:
    personal = tmp_path / "agents-skills"
    _write_skill(personal, "already-here")
    loader = SkillLoader(personal_agents_dir=personal, snapshot_path=tmp_path / "snapshot.json")

    assert {s.name for s in loader.load_all()} == {"already-here"}

    # Another agent writes into the shared directory. Nothing calls
    # invalidate_cache() — that is only reached through AgentOS's own paths.
    _write_skill(personal, "written-by-someone-else")

    names = {s.name for s in loader.load_all()}
    assert "written-by-someone-else" in names, "a shared-directory write must not need a restart"
    assert names == {"already-here", "written-by-someone-else"}


def test_a_removed_skill_stops_being_reported(tmp_path: Path) -> None:
    personal = tmp_path / "agents-skills"
    _write_skill(personal, "here-then-gone")
    loader = SkillLoader(personal_agents_dir=personal, snapshot_path=tmp_path / "snapshot.json")
    assert loader.get_by_name("here-then-gone") is not None

    for path in sorted((personal / "here-then-gone").iterdir()):
        path.unlink()
    (personal / "here-then-gone").rmdir()

    assert loader.get_by_name("here-then-gone") is None


def test_an_edited_skill_is_re_read(tmp_path: Path) -> None:
    personal = tmp_path / "agents-skills"
    _write_skill(personal, "edited")
    loader = SkillLoader(personal_agents_dir=personal, snapshot_path=tmp_path / "snapshot.json")
    assert loader.load_all()[0].description == "edited does a thing."

    (personal / "edited" / "SKILL.md").write_text(
        "---\nname: edited\ndescription: rewritten by another agent.\n---\nBody.\n",
        encoding="utf-8",
    )

    assert loader.load_all()[0].description == "rewritten by another agent."


def test_agents_dirs_are_named_even_before_they_exist(tmp_path: Path, monkeypatch) -> None:
    """A directory created after boot must not need a restart to be seen.

    ``.agents/skills`` frequently does not exist yet — the first cross-agent
    install creates it. Resolving it to None at boot dropped the whole layer.
    """
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    dirs = resolve_skill_layer_dirs(allow_bundled=False, workspace_root=project)

    assert dirs.personal_agents_dir == home / ".agents" / "skills"
    assert dirs.project_agents_dir == project / ".agents" / "skills"
    assert not dirs.personal_agents_dir.exists()

    loader = SkillLoader(
        personal_agents_dir=dirs.personal_agents_dir,
        project_agents_dir=dirs.project_agents_dir,
        snapshot_path=tmp_path / "snapshot.json",
    )
    # Naming a directory that is not there costs nothing.
    assert loader.load_all() == []

    _write_skill(dirs.personal_agents_dir, "created-after-boot")

    loaded = loader.load_all()
    assert [s.name for s in loaded] == ["created-after-boot"]
    assert loaded[0].layer is SkillLayer.PERSONAL
