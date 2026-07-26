"""USER.md is a curated memory store, not just a bootstrap file.

``CuratedMemoryStore`` loads, sanitizes, and injects USER.md alongside
MEMORY.md, and the periodic memory review writes user-profile facts there by
preference. But the filesystem tools only classified it as a bootstrap file,
so editing it never refreshed the frozen memory snapshot -- the change stayed
invisible to the model for the rest of the session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.tools.builtin import filesystem


def _rel(path: Path) -> str | None:
    return filesystem._memory_source_rel_path(path)


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(filesystem, "_memory_roots", lambda: [tmp_path.resolve()])
    return tmp_path


def test_user_md_is_a_memory_source(workspace: Path):
    """The regression this file exists for."""
    assert _rel(workspace / "USER.md") == "USER.md"


def test_memory_md_still_is(workspace: Path):
    assert _rel(workspace / "MEMORY.md") == "MEMORY.md"


def test_legacy_lowercase_memory_md_still_is(workspace: Path):
    """Kept deliberately: runtime.py still falls back to reading memory.md."""
    assert _rel(workspace / "memory.md") == "memory.md"


def test_daily_notes_still_are(workspace: Path):
    assert _rel(workspace / "memory" / "2026-07-26.md") == "memory/2026-07-26.md"


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("SOUL.md", id="soul"),
        pytest.param("IDENTITY.md", id="identity"),
        pytest.param("AGENTS.md", id="agents"),
        pytest.param("notes.md", id="stray_markdown"),
        pytest.param("USER.txt", id="wrong_extension"),
    ],
)
def test_other_root_files_are_not_memory_sources(workspace: Path, name: str):
    """Widening for USER.md must not sweep in every root-level file."""
    assert _rel(workspace / name) is None


def test_paths_outside_the_workspace_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(filesystem, "_memory_roots", lambda: [(tmp_path / "ws").resolve()])
    assert _rel(tmp_path / "elsewhere" / "USER.md") is None


@pytest.mark.asyncio
async def test_writing_user_md_notifies_the_memory_path(tmp_path: Path):
    """End to end through write_file: the memory callback must fire.

    Without it the snapshot keeps serving the stale USER block, so a profile
    fact the agent just saved is absent from the very next prompt.
    """
    from agentos.tools.types import ToolContext, current_tool_context

    memory_calls: list[tuple[str, str]] = []
    bootstrap_calls: list[tuple[str, str]] = []
    token = current_tool_context.set(
        ToolContext(
            agent_id="main",
            workspace_dir=str(tmp_path),
            memory_source_dir=str(tmp_path),
            on_memory_source_write=lambda a, p: memory_calls.append((a, p)),
            on_bootstrap_source_write=lambda a, p: bootstrap_calls.append((a, p)),
        )
    )
    write_file = filesystem.write_file.__wrapped__.__wrapped__  # type: ignore[attr-defined]
    try:
        await write_file("USER.md", "Name: Example User\n")
    finally:
        current_tool_context.reset(token)

    assert ("main", "USER.md") in memory_calls
    # Still a bootstrap file too -- both snapshots must be invalidated.
    assert ("main", "USER.md") in bootstrap_calls
