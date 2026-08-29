"""The git tools must mask credentials the way every sibling surface does.

``git diff``/``git log -p`` return committed and working-tree file content, so
a ``.env`` that was committed once keeps reaching the model on every diff. These
tests pin both halves: the redaction call on ``_run_git`` itself, and the
unified-diff ``+``/``-`` marker that used to defeat the assignment pass.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentos.redact import redact_sensitive_text
from agentos.tools.builtin import git

VENDOR_KEY = "sk-ant-api03-" + "A" * 40
NAMED_SECRET = "supersecretvalue123abc"
ROTATED_SECRET = "rotatedsecretvalue456def"
OTHER_SECRET = "othersecretvalue789ghi"


def _git(repo: Path, *args: str) -> None:
    """Run git with the ambient user/system config neutralised.

    A maintainer's global ``commit.gpgsign`` or commit template would otherwise
    decide whether this test can make a commit, and the env is copied rather
    than replaced because git on Windows needs the ambient ``SYSTEMROOT``.
    """
    missing = str(repo.parent / "no-such-gitconfig")
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": missing,
            "GIT_CONFIG_SYSTEM": missing,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".env").write_text(
        f"ANTHROPIC_KEY={VENDOR_KEY}\nMY_CUSTOM_SECRET={NAMED_SECRET}\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add env")
    return repo


async def test_git_log_patch_masks_committed_credentials(repo: Path) -> None:
    out = await git._run_git("log", "-p", "-1", cwd=str(repo))

    assert VENDOR_KEY not in out
    assert NAMED_SECRET not in out
    assert "add env" in out


async def test_git_diff_masks_working_tree_credentials(repo: Path) -> None:
    """Rotating the value puts the old and new secret on real ``-``/``+`` lines."""
    (repo / ".env").write_text(
        f"ANTHROPIC_KEY={VENDOR_KEY}\nMY_CUSTOM_SECRET={ROTATED_SECRET}\nEXTRA=1\n",
        encoding="utf-8",
        newline="\n",
    )

    out = await git._run_git("diff", cwd=str(repo))

    assert VENDOR_KEY not in out
    assert NAMED_SECRET not in out
    assert ROTATED_SECRET not in out
    assert "EXTRA=1" in out
    assert "--- a/.env" in out and "+++ b/.env" in out


async def test_git_diff_masks_secrets_in_a_conflicted_merge(repo: Path) -> None:
    """A conflicted tree makes ``git diff`` emit combined (``--cc``) output.

    Resolving a merge is exactly when an agent reaches for ``git_diff``, and the
    combined form carries two marker columns instead of one.
    """
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / ".env").write_text(
        f"MY_CUSTOM_SECRET={ROTATED_SECRET}\n", encoding="utf-8", newline="\n"
    )
    _git(repo, "commit", "-qam", "side")
    _git(repo, "checkout", "-q", "main")
    (repo / ".env").write_text(f"MY_CUSTOM_SECRET={OTHER_SECRET}\n", encoding="utf-8", newline="\n")
    _git(repo, "commit", "-qam", "main")
    subprocess.run(["git", "merge", "side"], cwd=repo, check=False, capture_output=True)

    out = await git._run_git("diff", cwd=str(repo))

    assert "diff --cc" in out
    assert ROTATED_SECRET not in out
    assert OTHER_SECRET not in out


async def test_masked_value_cannot_pass_for_a_truncated_key(repo: Path) -> None:
    """A diff is file content: an agent may ``git apply`` it, so use the sentinel."""
    out = await git._run_git("show", "HEAD", cwd=str(repo))

    assert "«redacted:" in out


async def test_git_failure_message_masks_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error path carries output too — it must not be the raw hole."""

    class _Proc:
        returncode = 1

        async def communicate(self) -> tuple[bytes, None]:
            body = f"error: could not apply\nMY_CUSTOM_SECRET={NAMED_SECRET}\n"
            return (body.encode(), None)

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(RuntimeError) as excinfo:
        await git._run_git("status", cwd=str(tmp_path))

    assert NAMED_SECRET not in str(excinfo.value)
    assert "could not apply" in str(excinfo.value)


async def test_sandboxed_backend_output_is_redacted_too(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sandboxed path returns its own string and needs its own masking."""
    runtime = SimpleNamespace(
        effective=SimpleNamespace(
            sandbox_enabled=True,
            grading_enabled=False,
            default_level="standard",
        ),
        settings=SimpleNamespace(),
        workspace=tmp_path,
    )

    async def fake_run_under_backend(request: object, *, runtime: object) -> SimpleNamespace:
        return SimpleNamespace(
            stdout=f"+MY_CUSTOM_SECRET={NAMED_SECRET}\n+KEY={VENDOR_KEY}\n",
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(git, "get_runtime", lambda: runtime)
    monkeypatch.setattr(git, "build_policy", lambda *a, **k: None)
    monkeypatch.setattr(git, "build_request_for_git", lambda *a, **k: None)
    monkeypatch.setattr(git, "run_under_backend", fake_run_under_backend)

    out = await git._run_git("diff", cwd=str(tmp_path))

    assert NAMED_SECRET not in out
    assert VENDOR_KEY not in out


@pytest.mark.parametrize("marker", ["+", "-", "++", "--", " ", ""])
def test_assignment_pass_survives_the_diff_marker(marker: str) -> None:
    line = f"{marker}MY_CUSTOM_SECRET={NAMED_SECRET}"

    out = redact_sensitive_text(line, force=True, code_file=False)

    assert out is not None
    assert NAMED_SECRET not in out
    assert out.startswith(marker)


@pytest.mark.parametrize(
    "line",
    [
        "+++ b/.env",
        "--- a/.env",
        "@@ -1,2 +1,3 @@",
        "diff --git a/.env b/.env",
        "@@@ -1,2 -1,2 +1,3 @@@",
        "index 703ae62..b82a5d0 100644",
        "-rw-r--r-- 1 user staff 42 .env",
        "+total = base+count=2",
        "++timeout=30",
        "--count=5",
        "+MAX_TOKENS=4096",
    ],
)
def test_diff_marker_does_not_create_false_positives(line: str) -> None:
    assert redact_sensitive_text(line, force=True, code_file=False) == line
