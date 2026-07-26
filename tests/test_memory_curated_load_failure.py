"""Curated memory must not go silently blind when its files cannot be read.

The write paths already refuse on an unreadable file (see
test_memory_curated_durability). The *read* path had no equivalent: a
transient lock or permission blip during load produced an empty snapshot,
which the runtime then froze for the whole session. The agent ran with no
memory at all, the file still holding every entry on disk, and nothing
anywhere said why.
"""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from agentos.memory.curated import ENTRY_DELIMITER, CuratedMemoryStore


def _seed(tmp_path: Path) -> None:
    (tmp_path / "MEMORY.md").write_text(
        ENTRY_DELIMITER.join(["fact one", "fact two", "fact three"]), encoding="utf-8"
    )
    (tmp_path / "USER.md").write_text("Name: Example User", encoding="utf-8")


def _blocking_read(target_name: str, exc: Exception):
    real = Path.read_text

    def patched(self: Path, *a, **k):
        if self.name == target_name:
            raise exc
        return real(self, *a, **k)

    return patched


def test_load_records_the_failure_instead_of_reporting_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _seed(tmp_path)
    monkeypatch.setattr(
        Path, "read_text", _blocking_read("MEMORY.md", OSError(errno.EACCES, "locked"))
    )

    store = CuratedMemoryStore(memory_dir=tmp_path)
    store.load_from_disk()

    assert store.load_failed == {"memory": True}


def test_successful_load_records_no_failure(tmp_path: Path):
    _seed(tmp_path)
    store = CuratedMemoryStore(memory_dir=tmp_path)
    store.load_from_disk()

    assert store.load_failed == {}
    assert len(store.entries_for("memory")) == 3


def test_a_genuinely_empty_store_is_not_a_failure(tmp_path: Path):
    """Absent files are a known state, not an unreadable one."""
    store = CuratedMemoryStore(memory_dir=tmp_path)
    store.load_from_disk()

    assert store.load_failed == {}
    assert store.entries_for("memory") == []


def test_each_target_is_tracked_separately(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A readable MEMORY.md must not be penalised for an unreadable USER.md."""
    _seed(tmp_path)
    monkeypatch.setattr(
        Path, "read_text", _blocking_read("USER.md", OSError(errno.EACCES, "locked"))
    )

    store = CuratedMemoryStore(memory_dir=tmp_path)
    store.load_from_disk()

    assert store.load_failed == {"user": True}
    assert len(store.entries_for("memory")) == 3


def test_corrupt_utf8_counts_as_unreadable(tmp_path: Path):
    _seed(tmp_path)
    (tmp_path / "MEMORY.md").write_bytes(b"\xff\xfe not utf-8 \xff")

    store = CuratedMemoryStore(memory_dir=tmp_path)
    store.load_from_disk()

    assert store.load_failed == {"memory": True}


def test_a_failed_load_never_flushes_emptiness_over_real_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The decisive case: load fails, the file recovers, then a write lands.

    The store holds [] in memory while disk holds real entries. `add` skips
    the drift check, so only the re-read inside the write path stands between
    the user and losing everything.
    """
    _seed(tmp_path)
    before = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    monkeypatch.setattr(
        Path, "read_text", _blocking_read("MEMORY.md", OSError(errno.EACCES, "locked"))
    )
    store = CuratedMemoryStore(memory_dir=tmp_path)
    store.load_from_disk()
    monkeypatch.undo()  # the transient condition clears

    result = store.add("memory", "fact four")

    assert result["success"] is True
    text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    for entry in before.split(ENTRY_DELIMITER):
        assert entry in text, "a pre-existing entry was lost"
    assert "fact four" in text


def test_runtime_refuses_to_freeze_a_snapshot_it_could_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`_load_memory_md` must raise, not return None.

    None is indistinguishable from "no memory yet", and the caller freezes
    that for the whole session -- so returning it would blind the agent until
    the session ends over a momentary read failure.
    """
    from agentos.engine.runtime import MemorySourceUnreadableError, TurnRunner

    _seed(tmp_path)
    runner = object.__new__(TurnRunner)
    runner._config = type("C", (), {"memory": None})()

    monkeypatch.setattr(
        Path, "read_text", _blocking_read("MEMORY.md", OSError(errno.EACCES, "locked"))
    )
    with pytest.raises(MemorySourceUnreadableError):
        runner._load_memory_md(tmp_path)


def test_runtime_returns_none_when_memory_is_merely_absent(tmp_path: Path):
    """An empty workspace is not an error -- only an unreadable one is."""
    from agentos.engine.runtime import TurnRunner

    runner = object.__new__(TurnRunner)
    runner._config = type("C", (), {"memory": None})()

    assert runner._load_memory_md(tmp_path) is None
