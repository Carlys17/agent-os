from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from agentos.gateway.config import GatewayConfig

# Real secret-shape detectors. Each pattern matches a shipped vendor key
# format so an accidentally-committed credential is caught at CI time
# before the public tree is published.
SECRET_PATTERNS = {
    "openrouter": re.compile(r"sk-or-v1-[A-Za-z0-9_-]{32,}"),
    "brave": re.compile(r"\bBSA[A-Za-z0-9_-]{20,}\b"),
    "github_pat": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
}

# Generic developer-machine path detectors. Matches any Windows
# ``C:\Users\<name>`` and any ``D:\<top-level>`` path so a hard-coded
# local checkout location cannot survive into the public tree, without
# embedding any specific contributor's username.
LOCAL_PATH_PATTERNS = {
    "windows_user_path": re.compile(r"C:\\Users\\[A-Za-z0-9_.-]+"),
    "windows_drive_d_repo": re.compile(r"\bD:\\[A-Za-z0-9_.-]+\\"),
    "linux_user_home_path": re.compile(r"/home/(?!node/)[A-Za-z0-9_.-]{2,}/"),
    "posix_user_home_path": re.compile(r"/Users/[A-Za-z0-9_.-]{2,}/"),
}

# A regional IANA zone locates a contributor as precisely as a home path does,
# and it arrives the same way: someone writes a fixture from the machine in
# front of them. A benchmark corpus did exactly that, and the value then
# propagated into recorded model output.
#
# Banning regional zones outright would be wrong -- the scheduler suite needs
# real zones to exercise DST, and the docs need example values. What is never
# legitimate is *this* machine's zone appearing in a tracked file, so that is
# what the check looks for. It fires on the machine where the mistake is being
# made and stays quiet in CI, which is the right trade for an authoring guard.
LOCAL_TZ_EXEMPT_FILES = frozenset({"tests/test_public_release_hygiene.py"})

# Generic placeholder names that the wheelhouse build script's release
# denylist must reference. These names are intentionally generic so the
# public denylist reads as a forward-looking forbidden-content policy
# rather than a confession of historical artifact names.
PUBLIC_RELEASE_MARKER_NAMES = (
    "INTERNAL_RELEASE_NOTE.md",
    ".internal/evidence",
    "LOCAL_AGENT_NOTES.md",
)

# These tests intentionally contain fake local paths to exercise path-policy
# behavior. They are public fixtures, not leaked developer-machine paths.
PATH_POLICY_FIXTURE_FILES = {
    "tests/test_artifacts.py",
    "tests/test_provider_image_generation.py",
    "tests/test_tools/test_apply_patch_gates.py",
    "tests/test_tools/test_filesystem_read_workspace.py",
    "tests/test_tools/test_git_workdir_policy.py",
    "tests/test_tools/test_path_policy.py",
    "tests/test_tools/test_shell_sensitive.py",
    "tests/test_tools/test_web_http_request.py",
    "tests/test_observability/test_decision_log_contract.py",
}


def _tracked_text_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files"], text=True)
    paths: list[Path] = []
    for rel in raw.splitlines():
        path = Path(rel)
        if path.suffix.lower() in {
            ".bin",
            ".onnx",
            ".pkl",
            ".joblib",
            ".woff2",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".ico",
        }:
            continue
        if not path.exists():
            continue
        paths.append(path)
    return paths


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_tracked_public_files_do_not_contain_real_secret_shapes_or_local_paths() -> None:
    violations: list[str] = []
    self_path = Path(__file__).relative_to(Path.cwd()).as_posix()
    for path in _tracked_text_files():
        # Skip this file so the regexes themselves do not trigger the test.
        if path.as_posix() == self_path:
            continue
        if path.as_posix() in PATH_POLICY_FIXTURE_FILES:
            continue
        text = _read_text(path)
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{path}: {name}")
        for name, pattern in LOCAL_PATH_PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{path}: {name}")

    assert violations == []


def _host_timezone_name() -> str | None:
    """Resolve the host's IANA zone name, or None if it cannot be determined.

    ``datetime.now().astimezone().tzinfo`` is not enough: on macOS it yields a
    fixed-offset ``timezone`` with no ``.key``, so the obvious one-liner reports
    nothing and the check would pass vacuously on the very machines it is meant
    to protect. ``/etc/localtime`` is a symlink into the zoneinfo tree on both
    macOS and Linux and carries the real name.
    """
    from datetime import datetime

    key = getattr(datetime.now().astimezone().tzinfo, "key", None)
    if key:
        return str(key)

    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        target = os.readlink(localtime)
        _, sep, zone = target.partition("zoneinfo/")
        if sep and zone:
            return zone

    env_zone = os.environ.get("TZ", "").strip()
    return env_zone or None


def test_tracked_public_files_do_not_carry_this_machines_timezone() -> None:
    """The running host's own zone must not appear in a tracked file.

    Regional zones in general are fine -- the scheduler suite needs them for
    DST and the docs need examples. A zone matching *this* machine is the
    signal that a value was copied out of the environment rather than chosen,
    which is how a contributor's location leaks into a public fixture.

    Use ``UTC`` or a fixed offset. Skips when the host is already UTC, so CI
    neither fails nor pretends to have checked anything.
    """
    local_zone = _host_timezone_name()
    if not local_zone or local_zone in {"UTC", "Etc/UTC"}:
        pytest.skip("host zone is UTC or undeterminable; nothing to leak")

    violations: list[str] = []
    for path in _tracked_text_files():
        if path.as_posix() in LOCAL_TZ_EXEMPT_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if local_zone in text:
            violations.append(path.as_posix())

    assert violations == [], (
        f"{local_zone} is this machine's timezone and must not be committed; "
        "use UTC or a fixed offset"
    )


def test_release_text_marker_policy_uses_public_internal_fixture_names() -> None:
    script = Path("scripts/build_wheelhouse_zip.py").read_text(encoding="utf-8")

    for marker in PUBLIC_RELEASE_MARKER_NAMES:
        assert marker in script


def test_private_test_suites_are_not_tracked_in_public_repository() -> None:
    tracked = {path.as_posix() for path in _tracked_text_files()}

    assert not any(path.startswith("tests/_private/") for path in tracked)
    assert not any(path.startswith(".omx/private-golden/") for path in tracked)


def test_gitignore_keeps_private_live_artifacts_out_of_public_tree() -> None:
    ignore_text = Path(".gitignore").read_text(encoding="utf-8")

    assert "/tests/_private/" in ignore_text
    assert "tests/functional/reports/" in ignore_text
    assert ".omx/" in ignore_text


def test_pytest_default_collection_excludes_private_agent_artifacts() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = config["tool"]["pytest"]["ini_options"]
    excluded = set(pytest_options.get("norecursedirs", []))

    assert {"tests/_private", "tests/fixtures", ".omx", ".codex", ".claude"} <= excluded


def test_public_testing_guidance_documents_the_private_boundary() -> None:
    required_docs = [
        Path("CONTRIBUTING.md"),
        Path(".github/pull_request_template.md"),
    ]

    for path in required_docs:
        assert path.is_file(), f"missing testing guidance: {path}"

    combined = "\n".join(path.read_text(encoding="utf-8") for path in required_docs)
    required_phrases = [
        "offline",
        "credential-free",
        "tests/_private/",
        "must not be committed",
        "Live Release E2E",
    ]

    for phrase in required_phrases:
        assert phrase in combined


def test_pull_request_template_stays_minimal() -> None:
    text = Path(".github/pull_request_template.md").read_text(encoding="utf-8")

    assert "## Summary" in text
    assert "## Tests" in text


def test_public_docs_do_not_use_key_shaped_placeholders() -> None:
    violations: list[str] = []
    placeholder_pattern = re.compile(r"sk-or-v1-[A-Za-z0-9_-]+")
    for path in [Path("README.md"), Path("CONTRIBUTING.md")]:
        text = _read_text(path)
        if placeholder_pattern.search(text):
            violations.append(path.as_posix())

    assert violations == []


def test_security_policy_routes_vulnerability_reports_privately() -> None:
    text = Path("SECURITY.md").read_text(encoding="utf-8")

    assert "https://github.com/use-agent-os/agent-os/security/advisories/new" in text
    assert "Do not open a public issue with vulnerability details" in text
    assert "when it is available" not in text


def test_release_sop_documents_github_only_validation_boundary() -> None:
    text = Path("RELEASES.md").read_text(encoding="utf-8")

    required_phrases = [
        "GitHub-only release checks",
        "Preview releases publish only versioned assets",
        "Non-preview releases additionally publish a version-independent alias",
        "AgentOS-windows-x64-portable.zip",
        "filenames must remain versioned",
        "SHA256SUMS",
        "latest Windows portable",
        "post-publish latest URL check",
        "curl --fail --head --location",
        "wheelhouse zips, macOS portable zips, and Linux portable zips are intentionally",
        "Mark-of-the-Web",
        "SmartScreen",
        "Smart App Control",
    ]

    for phrase in required_phrases:
        assert phrase in text

    assert ".sha256" not in text


def test_readme_documents_quick_and_manual_terminal_install_commands() -> None:
    text = Path("README.md").read_text(encoding="utf-8")

    assert 'uv tool install --python 3.12 "use-agent-os[recommended]"' in text
    assert "curl -LsSf https://astral.sh/uv/install.sh | sh" in text
    assert '. "$HOME/.local/bin/env"' in text
    assert 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"' in text
    assert "$env:Path" in text
    assert "bash scripts/install_source.sh" in text
    assert "./scripts/install_source.ps1" in text


def test_readme_uses_gateway_default_port() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    expected_port = GatewayConfig.model_fields["port"].default

    assert f"127.0.0.1:{expected_port}" in text
    assert "18790" not in text


def test_tracked_sources_do_not_keep_agent_revision_markers() -> None:
    forbidden_markers = ("codex-revised", "claude-revised")
    violations: list[str] = []
    self_path = Path(__file__).relative_to(Path.cwd()).as_posix()
    for path in _tracked_text_files():
        if path.as_posix() == self_path:
            continue
        text = _read_text(path).lower()
        for marker in forbidden_markers:
            if marker in text:
                violations.append(f"{path}: {marker}")

    assert violations == []


def test_gitignore_does_not_hide_tracked_release_files() -> None:
    raw = subprocess.check_output(
        ["git", "ls-files", "-c", "-i", "--exclude-standard"],
        text=True,
    )
    # A pre-commit cleanup can leave an index entry for a file that has already
    # been deleted from the worktree. It is not a hidden release file and
    # disappears from the index with the deletion commit.
    ignored_tracked = [line for line in raw.splitlines() if line.strip() and Path(line).exists()]

    assert ignored_tracked == []
