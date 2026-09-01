from __future__ import annotations

from pathlib import Path

from agentos.sandbox.sensitive_paths import (
    is_sensitive_path,
    sensitive_path_in_text,
    sensitive_path_marker,
    sensitive_target_in_command,
)


def test_sensitive_path_matches_nested_home_prefixes_with_native_separators() -> None:
    assert is_sensitive_path(str(Path.home() / ".ssh" / "id_rsa")) == "~/.ssh"
    assert is_sensitive_path(str(Path.home() / ".aws" / "credentials")) == "~/.aws"


def test_sensitive_path_in_text_matches_native_separator_paths() -> None:
    key_path = Path.home() / ".ssh" / "id_rsa"

    assert sensitive_path_in_text(f"type {key_path}") == "~/.ssh"


def test_active_workspace_under_root_is_not_blocked_by_root_prefix() -> None:
    workspace = Path("/root/.agentos/workspace")

    assert (
        sensitive_path_marker(
            str(workspace / "notes" / "plan.md"),
            workspace=workspace,
        )
        is None
    )
    assert (
        sensitive_path_in_text(
            f"cat {workspace / 'notes' / 'plan.md'}",
            workspace=workspace,
        )
        is None
    )


def test_active_workspace_exception_keeps_leaf_secret_blocks() -> None:
    workspace = Path("/root/.agentos/workspace")

    assert sensitive_path_marker(str(workspace / ".env"), workspace=workspace) in {
        "/.env",
        "/.env*",
    }
    assert sensitive_path_marker(str(workspace / "id_rsa"), workspace=workspace) == "/id_rsa"
    assert (
        sensitive_path_in_text(
            f"cat {workspace / '.env.local'}",
            workspace=workspace,
        )
        in {"/.env.local", "/.env*"}
    )


def test_sensitive_command_targets_honor_active_workspace_exception() -> None:
    workspace = Path("/root/.agentos/workspace")

    assert (
        sensitive_target_in_command(
            f"rm {workspace / 'scratch.txt'}",
            workspace=workspace,
        )
        is None
    )
    assert (
        sensitive_target_in_command(
            f"rm {workspace / '.env'}",
            workspace=workspace,
        )
        in {"/.env", "/.env*"}
    )


def test_windows_rooted_workspace_targets_keep_leaf_secret_blocks() -> None:
    workspace = Path("/root/.agentos/workspace")

    assert (
        sensitive_target_in_command(
            r"rm \root\.agentos\workspace\scratch.txt",
            workspace=workspace,
        )
        is None
    )
    assert (
        sensitive_target_in_command(
            r"rm \root\.agentos\workspace\.env",
            workspace=workspace,
        )
        in {"/.env", "/.env*"}
    )


def test_posix_sensitive_paths_stay_blocked_on_windows_runners() -> None:
    workspace = Path("/root/.agentos/workspace")

    assert sensitive_path_in_text("cat /dev/sda 2>/dev/null") == "/dev"
    assert (
        sensitive_path_in_text("cat /root/.ssh/id_rsa", workspace=workspace)
        == "~/.ssh"
    )

def test_bare_root_is_sensitive() -> None:
    # Issue #563: `rm -rf /` must hit the hard block.
    assert is_sensitive_path("/") == "/ (filesystem root)"
    assert is_sensitive_path("/.") == "/ (filesystem root)"
    assert is_sensitive_path("///") == "/ (filesystem root)"
    assert is_sensitive_path("/*") == "/ (filesystem root)"


def test_root_wipe_in_compound_command_is_blocked() -> None:
    # Issue #563: a benign leading target must not smuggle a root wipe past
    # the hard block; every rm segment of a compound command is scanned.
    assert sensitive_target_in_command("rm /tmp/safe; rm -rf /") == "/ (filesystem root)"
    assert (
        sensitive_target_in_command("rm /tmp/safe && rm -rf /*") == "/ (filesystem root)"
    )
    assert sensitive_target_in_command("rm -rf /") == "/ (filesystem root)"


def test_non_root_compound_targets_still_block() -> None:
    # The trailing-target scan (upstream #512 parser) still catches sensitive
    # paths in later rm segments; bare-root handling must not shadow it.
    assert sensitive_target_in_command("rm /tmp/safe; rm /root/.ssh/id_rsa") is not None
