"""The one-time MEMORY.md migration must not be able to destroy the file.

The migration is the single moment MEMORY.md is restructured, and the kept
entries -- the ~80% the user retains -- exist nowhere else at that point: the
overflow archive holds only the discarded remainder. It is also one-time and
content-idempotent, so a failure that truncates the file has no retry that
brings it back.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from agentos.memory.curated import ENTRY_DELIMITER
from agentos.memory.curated_migration import migrate_freeform_memory_md

_FREEFORM = """# Notes

- prefers concise answers
- uses uv and ruff

Some longer paragraph worth keeping across sessions.
"""


def test_migration_still_works(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(_FREEFORM, encoding="utf-8")

    assert migrate_freeform_memory_md(tmp_path, 4000, today="2026-07-26") is True

    text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert ENTRY_DELIMITER in text
    assert "prefers concise answers" in text


def test_a_failed_write_leaves_the_original_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The decisive case: crash-equivalent failure must not truncate MEMORY.md.

    A plain write_text would already have emptied it before failing.
    """
    path = tmp_path / "MEMORY.md"
    path.write_text(_FREEFORM, encoding="utf-8")

    monkeypatch.setattr(
        os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError(errno.EIO, "io"))
    )
    with pytest.raises(OSError):
        migrate_freeform_memory_md(tmp_path, 4000, today="2026-07-26")
    monkeypatch.undo()

    assert path.read_text(encoding="utf-8") == _FREEFORM


def test_a_failed_write_leaves_no_temp_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "MEMORY.md"
    path.write_text(_FREEFORM, encoding="utf-8")

    monkeypatch.setattr(
        os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError(errno.EIO, "io"))
    )
    with pytest.raises(OSError):
        migrate_freeform_memory_md(tmp_path, 4000, today="2026-07-26")
    monkeypatch.undo()

    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["MEMORY.md"]


# -- overflow archive ------------------------------------------------------


def _overflow_workspace(tmp_path: Path) -> Path:
    """A file large enough that migration must archive part of it."""
    entries = "\n\n".join(f"- durable fact number {i} worth keeping" for i in range(60))
    (tmp_path / "MEMORY.md").write_text(f"# Notes\n\n{entries}\n", encoding="utf-8")
    return tmp_path / "memory" / "archive" / "memory-overflow.md"


def test_overflow_is_archived(tmp_path: Path):
    archive = _overflow_workspace(tmp_path)
    assert migrate_freeform_memory_md(tmp_path, 500, today="2026-07-26") is True
    assert archive.is_file()
    assert "durable fact number" in archive.read_text(encoding="utf-8")


def test_an_unreadable_archive_aborts_rather_than_overwriting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Unreadable is not empty.

    Falling back to "" would rewrite the archive with only this batch,
    discarding every overflow entry migrated previously.
    """
    archive = _overflow_workspace(tmp_path)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text("## Migrated earlier\n\nan older overflow entry\n", encoding="utf-8")
    before = archive.read_text(encoding="utf-8")
    memory_before = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    real_read = Path.read_text

    def blocked(self: Path, *a, **k):
        if self.name == "memory-overflow.md":
            raise OSError(errno.EACCES, "locked")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", blocked)
    with pytest.raises(OSError):
        migrate_freeform_memory_md(tmp_path, 500, today="2026-07-26")
    monkeypatch.undo()

    assert archive.read_text(encoding="utf-8") == before
    # MEMORY.md is written after the archive, so aborting costs nothing.
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == memory_before


def test_a_readable_archive_is_appended_to_not_replaced(tmp_path: Path):
    archive = _overflow_workspace(tmp_path)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text("## Migrated earlier\n\nan older overflow entry\n", encoding="utf-8")

    assert migrate_freeform_memory_md(tmp_path, 500, today="2026-07-26") is True

    text = archive.read_text(encoding="utf-8")
    assert "an older overflow entry" in text
    assert "durable fact number" in text
