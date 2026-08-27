"""git tools must redact credentials in their output before it reaches the model.

``git diff`` / ``log -p`` / ``show`` surface committed and working-tree file
content, which routinely includes ``.env`` files and credentials. The other
output surfaces (read_file, execute_code) all route through the redaction
layer; git must too.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentos.tools.builtin import git

_ANTHROPIC_KEY = (
    "sk-ant-api03-A1b2C3d4E5f6G7h8A1b2C3d4E5f6G7h8A1b2C3d4E5f6G7h8"
)
_GITHUB_TOKEN = "ghp_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
_NAMED_SECRET = "supersecretvalue123"


def _write_env(repo: Path, extra: str = "") -> None:
    content = (
        f"ANTHROPIC_KEY={_ANTHROPIC_KEY}\n"
        f"GITHUB_TOKEN={_GITHUB_TOKEN}\n"
        f"MY_CUSTOM_SECRET={_NAMED_SECRET}\n"
        f"{extra}"
    )
    repo.joinpath(".env").write_text(content, encoding="utf-8")


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)


def _make_repo_with_secrets(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_env(repo)
    _init_repo(repo)
    subprocess.run(["git", "add", ".env"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add env"], cwd=repo, check=True)
    return repo


def _git_repo_with_history(tmp_path: Path) -> Path:
    """Real repo with the secret committed, then a second commit so `git log -p` shows it."""
    repo = _make_repo_with_secrets(tmp_path)
    _write_env(repo, extra="EXTRA_KEY=moresecretvalue456\n")
    subprocess.run(["git", "add", ".env"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "edit env"], cwd=repo, check=True)
    return repo


def test_run_git_redacts_committed_secret_in_log_p(tmp_path: Path) -> None:
    repo = _git_repo_with_history(tmp_path)
    out = subprocess.run(  # noqa: S603
        ["git", "log", "-p", "-3"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    # Precondition: the raw git output really contains the secrets.
    assert _NAMED_SECRET in out
    # _run_git must not hand them to the model raw.
    redacted = git._redact_git_output(out)
    assert _ANTHROPIC_KEY not in redacted
    assert _GITHUB_TOKEN not in redacted
    assert _NAMED_SECRET not in redacted
    # Structure is preserved, not dropped.
    assert "ANTHROPIC_KEY=" in redacted
    assert "GITHUB_TOKEN=" in redacted
    assert "MY_CUSTOM_SECRET=" in redacted


def test_run_git_redacts_working_tree_secret_in_diff(tmp_path: Path) -> None:
    repo = _make_repo_with_secrets(tmp_path)
    # Modify the working tree so `git diff` shows the added line only.
    _write_env(repo, extra="EXTRA_SECRET=moresecretvalue456\n")
    # Precondition: the raw diff shows an added line carrying a named secret.
    raw = subprocess.run(  # noqa: S603
        ["git", "diff"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert "+EXTRA_SECRET=moresecretvalue456" in raw
    # The unified-diff `+` marker must not let the named secret escape redaction.
    redacted = git._redact_git_output(raw)
    assert "moresecretvalue456" not in redacted
    # Diff marker and label are preserved so the agent still reads the change.
    assert "+EXTRA_SECRET=" in redacted


def test_git_diff_added_lines_do_not_leak_named_secret(tmp_path: Path) -> None:
    repo = _make_repo_with_secrets(tmp_path)
    # Every line is an added line (+...) via a no-index diff against /dev/null.
    raw = subprocess.run(  # noqa: S603
        [
            "git",
            "diff",
            "--no-index",
            "/dev/null",
            str(repo / ".env"),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout
    assert "+ANTHROPIC_KEY=" in raw
    redacted = git._redact_git_output(raw)
    assert _ANTHROPIC_KEY not in redacted
    assert _GITHUB_TOKEN not in redacted
    assert _NAMED_SECRET not in redacted
    # Assignment pass still masks non-vendor named secrets even with the + marker.
    assert "MY_CUSTOM_SECRET=" in redacted
