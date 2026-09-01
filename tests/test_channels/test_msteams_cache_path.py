"""Regression: MSTeamsChannel._cache_path resolves workspace_dir to prevent traversal."""

from pathlib import Path

from agentos.channels.msteams import MSTeamsChannel, MSTeamsChannelConfig


class TestMSTeamsCachePath:
    """Guard _cache_path() against path-traversal via malicious workspace_dir."""

    def test_cache_path_resolves_traversal_segments(self, tmp_path: Path) -> None:
        """
        Supplying a workspace_dir with ../ segments must result in a canonical
        cache path without any .. components.

        Before the fix: Path("/a/b/../../../etc") joined with "state/msteams/file"
        produces /a/b/../../../etc/state/msteams/file — raw .. segments that an
        attacker could use to write to an unintended location.
        After the fix: Path("/a/b/../../../etc").resolve() normalizes before join,
        so /a/b/../../../etc becomes /etc and cache_path = /etc/state/msteams/file.
        The cache is always under the resolved workspace.
        """
        # Build a path that has real .. segments in it
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        # /tmp/pytest-X/a/b/../../../Z → resolves to /tmp/pytest-X/Z
        crafted = str(nested / ".." / ".." / ".." / "Z")
        assert ".." in crafted, "precondition: crafted path must contain .."

        cfg = MSTeamsChannelConfig(workspace_dir=crafted)
        ch = MSTeamsChannel(cfg)

        cache_path = ch._cache_path()

        # The fix: .resolve() on workspace normalizes away all .. segments
        assert ".." not in str(cache_path), (
            f"cache_path contains traversal segments after fix: {cache_path}"
        )
        # Cache path must be under the resolved workspace (no .. in workspace either)
        resolved_workspace = cache_path.parent.parent.parent  # strip state/msteams/file
        assert ".." not in str(resolved_workspace), (
            f"resolved workspace contains ..: {resolved_workspace}"
        )

    def test_cache_path_normal_path(self, tmp_path: Path) -> None:
        """Normal absolute workspace_dir should produce a clean cache path."""
        cfg = MSTeamsChannelConfig(workspace_dir=str(tmp_path))
        ch = MSTeamsChannel(cfg)

        cache_path = ch._cache_path()
        assert ".." not in str(cache_path)
        assert cache_path == (tmp_path.resolve() / "state" / "msteams" / "conversations.json")

    def test_cache_path_default_workspace(self) -> None:
        """Default workspace (home/.agentos) must not contain .. segments."""
        cfg = MSTeamsChannelConfig()
        ch = MSTeamsChannel(cfg)

        cache_path = ch._cache_path()
        assert ".." not in str(cache_path)
        assert cache_path.name == "conversations.json"
