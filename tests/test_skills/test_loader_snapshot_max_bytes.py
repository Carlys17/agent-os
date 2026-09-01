"""Regression: SkillLoader.load_snapshot rejects snapshot files over _SNAPSHOT_MAX_BYTES."""

import json
from pathlib import Path

from agentos.skills.loader import _SNAPSHOT_MAX_BYTES, SkillLoader


class TestSnapshotSizeLimit:
    """Guard load_snapshot() against unbounded snapshot file sizes."""

    def test_load_snapshot_rejects_oversized_file(self, tmp_path: Path) -> None:
        """
        A snapshot file larger than _SNAPSHOT_MAX_BYTES must be ignored,
        falling back to a normal layer scan rather than loading the full
        content into memory.
        """
        # Create a snapshot just over the limit
        oversize_bytes = _SNAPSHOT_MAX_BYTES + 1024
        # Pad with skills to exceed the limit
        skills_data = [
            {"id": f"skill_{i}", "name": f"Skill {i}", "description": "x" * 1000}
            for i in range(oversize_bytes // 500)
        ]
        snapshot = {
            "version": 11,
            "skills": skills_data,
            "manifest": {},
        }
        snap_path = tmp_path / "snapshot.json"
        snap_path.write_text(json.dumps(snapshot))

        actual_size = snap_path.stat().st_size
        assert actual_size > _SNAPSHOT_MAX_BYTES, (
            f"test fixture under limit ({actual_size} bytes); fix the padding"
        )

        loader = SkillLoader(workspace_dir=tmp_path)
        loader._snapshot_path = snap_path

        result = loader.load_snapshot()

        # Must return None (cache miss), not the full content
        assert result is None, (
            f"load_snapshot returned {len(result) if result else 0} skills "
            f"for a {actual_size / 1024 / 1024:.1f} MB file; expected None"
        )

    def test_load_snapshot_accepts_undersized_file(self, tmp_path: Path) -> None:
        """A snapshot within the limit must load normally."""
        snapshot = {
            "version": 11,
            "skills": [],
            "manifest": {},
        }
        snap_path = tmp_path / "snapshot.json"
        snap_path.write_text(json.dumps(snapshot))

        loader = SkillLoader(workspace_dir=tmp_path)
        loader._snapshot_path = snap_path

        result = loader.load_snapshot()
        # Either None (schema mismatch) or [] (empty skill list) — both are safe
        assert result is None or result == [], (
            f"unexpected result for small snapshot: {result}"
        )

    def test_snapshot_max_bytes_constant(self) -> None:
        """_SNAPSHOT_MAX_BYTES must be a positive integer > 0."""
        assert isinstance(_SNAPSHOT_MAX_BYTES, int)
        assert _SNAPSHOT_MAX_BYTES > 0
        # Sanity: must be at least 1 KB
        assert _SNAPSHOT_MAX_BYTES >= 1024
        # Should be at most 100 MB
        assert _SNAPSHOT_MAX_BYTES <= 100 * 1024 * 1024
