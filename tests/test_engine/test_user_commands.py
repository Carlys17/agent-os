"""Regression: agentos.engine.user_commands loader and render."""

import pytest
from pathlib import Path

from agentos.engine.user_commands import (
    UserCommand,
    load_user_commands,
    user_command_help_lines,
    _parse_frontmatter,
    _validate_name,
    _coerce_surfaces,
)


class TestValidateName:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("/review", "/review"),
            ("/code-review", "/code-review"),
            ("review", "/review"),
            ("/pr-123", "/pr-123"),
            # Invalid
            (None, None),
            ("", None),
            ("/", None),  # bare slash
            ("1abc", None),  # must start with letter
            ("_underscore", None),
            ("toolong" * 10, None),  # > 32 chars after slash
        ],
    )
    def test_validate_name(self, raw, expected) -> None:
        assert _validate_name(raw, Path("x")) == expected


class TestParseFrontmatter:
    def test_full_frontmatter(self) -> None:
        text = "---\nname: /review\ndescription: Review diff\nsurfaces:\n  - cli\n  - channel\n---\nBody here."
        meta, body = _parse_frontmatter(text)
        assert meta["name"] == "/review"
        assert meta["description"] == "Review diff"
        assert body == "Body here."

    def test_no_frontmatter(self) -> None:
        text = "Just a plain body."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == "Just a plain body."


class TestCoerceSurfaces:
    def test_valid_list(self) -> None:
        assert _coerce_surfaces(["channel", "web", "cli"]) == frozenset({"channel", "web", "cli"})

    def test_ignores_invalid(self) -> None:
        assert _coerce_surfaces(["cli", "twitter", "x"]) == frozenset({"cli"})

    def test_default_on_empty(self) -> None:
        assert _coerce_surfaces([]) == frozenset({"cli", "channel", "web"})
        assert _coerce_surfaces(None) == frozenset({"cli", "channel", "web"})


class TestUserCommandRender:
    @pytest.mark.parametrize(
        "body, args, expected",
        [
            ("Review {{ args }} changes.", "src/api", "Review src/api changes."),
            ("Review {{ args }} changes.", "", "Review  changes."),
            ("Review {{ args_or_default }} changes.", "src/api", "Review src/api changes."),
            ("Review {{ args_or_default }} changes.", "", "Review changes changes."),
            ("Simple body.", "ignored", "Simple body."),
            ("{{ args }}", "", ""),
            ("Prefix {{ args }}", "", "Prefix"),
        ],
    )
    def test_render(self, body: str, args: str, expected: str) -> None:
        cmd = UserCommand(
            name="/x",
            description="x",
            body=body,
            surfaces=frozenset({"cli"}),
            source_path=Path("x"),
        )
        assert cmd.render(args) == expected


class TestLoadUserCommands:
    def test_loads_valid_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "review.md").write_text(
            "---\nname: /review\ndescription: Review changes\nsurfaces: [cli]\nargument_hint: scope\n---\nReview the {{ args_or_default }} changes."
        )
        cmds = load_user_commands(cmd_dir)
        assert len(cmds) == 1
        assert cmds[0].name == "/review"
        assert cmds[0].argument_hint == "scope"
        assert cmds[0].surfaces == frozenset({"cli"})
        assert "Review the " in cmds[0].body

    def test_skips_invalid_name(self, tmp_path: Path) -> None:
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "bad.md").write_text("---\nname: 123bad\ndescription: x\n---\nbody")
        cmds = load_user_commands(cmd_dir)
        assert len(cmds) == 0

    def test_skips_empty_body(self, tmp_path: Path) -> None:
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "empty.md").write_text("---\nname: /empty\ndescription: x\n---\n   \n")
        cmds = load_user_commands(cmd_dir)
        assert len(cmds) == 0

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert load_user_commands(tmp_path / "nonexistent") == ()
        assert load_user_commands(tmp_path / "notadir") == ()

    def test_sorted_order(self, tmp_path: Path) -> None:
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "zulu.md").write_text("---\nname: /zulu\n---\nz")
        (cmd_dir / "alpha.md").write_text("---\nname: /alpha\n---\na")
        (cmd_dir / "mike.md").write_text("---\nname: /mike\n---\nm")
        cmds = load_user_commands(cmd_dir)
        names = [c.name for c in cmds]
        assert names == ["/alpha", "/mike", "/zulu"]

    def test_help_lines(self, tmp_path: Path) -> None:
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "review.md").write_text("---\nname: /review\ndescription: Review diffs\n---\nReview.")
        (cmd_dir / "deploy.md").write_text("---\nname: /deploy\ndescription: Deploy\n---\nDeploy.")
        cmds = load_user_commands(cmd_dir)
        lines = user_command_help_lines(cmds)
        assert "/deploy" in lines[0]
        assert "/review" in lines[1]
