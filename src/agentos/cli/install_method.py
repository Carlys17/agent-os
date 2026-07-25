"""Detect how the running ``agentos`` was installed and how to upgrade it.

Two independent hazards from the OpenClaw / Hermes case studies drive this
module:

* **Wrong upgrade channel** — running ``pip install -U`` against a uv-tool
  install silently no-ops (or corrupts the tool venv). We inspect where the
  running executable / package actually lives and pick the matching upgrade
  command, and for plain-pip / editable installs we refuse to fake it.

* **PATH gaps on macOS** (Hermes's #1 incident cluster) — the upgrade
  subprocess hangs or fails because ``uv`` / ``pipx`` is not on the ``PATH``
  the daemon inherited. We resolve the delegated tool to an ABSOLUTE path
  against an environment augmented with the standard login locations before
  spawning anything.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DIST_NAME = "use-agent-os"

# Standard login-shell locations that a GUI-launched or daemon-inherited
# environment frequently drops. Appended (not prepended) so an operator's own
# PATH ordering still wins.
_LOGIN_PATH_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
)


class InstallMethod(StrEnum):
    UV_TOOL = "uv-tool"
    PIPX = "pipx"
    PIP = "pip"
    EDITABLE = "editable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class UpgradePlan:
    """How to upgrade the running install.

    ``delegated`` is True when AgentOS can run the upgrade itself (uv-tool /
    pipx). When False, ``command`` is the exact command the operator must run
    by hand and the ``upgrade`` command exits 3 rather than pretending.
    """

    method: InstallMethod
    delegated: bool
    tool: str | None
    command: list[str]
    manual_hint: str


def _package_location() -> Path:
    """Absolute path to the installed ``agentos`` package directory."""

    import agentos

    return Path(agentos.__file__).resolve().parent


def _looks_editable(pkg_dir: Path) -> bool:
    """True when the package is imported from a source checkout (editable/-e).

    An editable install lives in the project tree (``src/agentos``) rather than
    under a ``site-packages`` directory.
    """

    parts = pkg_dir.parts
    if "site-packages" in parts or "dist-packages" in parts:
        return False
    # ``src/agentos`` layout is the tell-tale of this repo's editable install.
    return pkg_dir.parent.name == "src" or (pkg_dir.parent / "pyproject.toml").exists()


def _under(path: Path, *needles: str) -> bool:
    lowered = [part.lower() for part in path.parts]
    return any(needle in lowered for needle in needles)


def _uv_tools_roots(env: dict[str, str]) -> list[Path]:
    """Resolved uv-tools root directories to prefix-match against.

    ``UV_TOOL_DIR`` overrides the default ``~/.local/share/uv/tools`` location
    entirely (uv honours it), so a custom value must be treated as a first-class
    tools root — otherwise a uv-tool install under it is misclassified and we
    hand back the actively-wrong ``pip`` suggestion (a uv tool venv has no pip).
    """

    roots: list[Path] = []
    override = env.get("UV_TOOL_DIR", "").strip()
    if override:
        try:
            roots.append(Path(override).resolve())
        except OSError:
            pass
    return roots


def _is_within(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or lives beneath it (both resolved)."""

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def detect_install_method(
    *,
    executable: str | None = None,
    package_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> InstallMethod:
    """Classify the running install.

    ``executable`` / ``package_dir`` / ``env`` are injectable for tests; they
    default to ``sys.executable``, the real ``agentos`` package location, and
    ``os.environ``.
    """

    environ = env if env is not None else dict(os.environ)
    raw_exe = Path(executable or sys.executable)
    exe = raw_exe.resolve()
    pkg_dir = package_dir if package_dir is not None else _package_location()

    # Editable / source checkout first: it can otherwise masquerade as pip.
    if _looks_editable(pkg_dir):
        return InstallMethod.EDITABLE

    # A custom UV_TOOL_DIR relocates the whole tools tree; the executable may
    # even be a symlink from a bin dir INTO that tree, so check both the raw path
    # and its symlink-resolved target against the override root.
    uv_roots = _uv_tools_roots(environ)
    if uv_roots:
        candidates: list[Path] = []
        for candidate in (raw_exe, exe, pkg_dir):
            candidates.append(candidate)
            try:
                candidates.append(candidate.resolve())
            except OSError:
                pass
        if any(_is_within(c, root) for c in candidates for root in uv_roots):
            return InstallMethod.UV_TOOL

    # uv tool installs live under the uv tools root, e.g.
    #   ~/.local/share/uv/tools/use-agent-os/...
    #   $XDG_DATA_HOME/uv/tools/...
    for candidate in (exe, pkg_dir):
        parts = [p.lower() for p in candidate.parts]
        if "uv" in parts and "tools" in parts:
            return InstallMethod.UV_TOOL

    # pipx venvs: ~/.local/share/pipx/venvs/<name>/ or $PIPX_HOME/venvs/...
    for candidate in (exe, pkg_dir):
        if _under(candidate, "pipx"):
            return InstallMethod.PIPX

    if "site-packages" in [p.lower() for p in pkg_dir.parts] or "dist-packages" in [
        p.lower() for p in pkg_dir.parts
    ]:
        return InstallMethod.PIP

    return InstallMethod.UNKNOWN


def hardened_path_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an env copy whose ``PATH`` includes the standard login dirs.

    The augmented directories are *appended* so an operator's own ordering is
    preserved; only genuinely-missing login locations are added.
    """

    env = dict(base_env if base_env is not None else os.environ)
    current = env.get("PATH", "")
    entries = [p for p in current.split(os.pathsep) if p]
    seen = set(entries)
    home = env.get("HOME") or str(Path.home())
    login_dirs = list(_LOGIN_PATH_DIRS) + [str(Path(home) / ".local" / "bin")]
    for extra in login_dirs:
        if extra not in seen:
            entries.append(extra)
            seen.add(extra)
    env["PATH"] = os.pathsep.join(entries)
    return env


def resolve_tool(tool: str, env: dict[str, str] | None = None) -> str | None:
    """Resolve ``tool`` (``uv`` / ``pipx``) to an ABSOLUTE path.

    Uses a PATH-hardened environment so a daemon-inherited PATH missing
    ``/opt/homebrew/bin`` etc. still finds the tool. Returns ``None`` when the
    tool genuinely cannot be found.
    """

    hardened = hardened_path_env(env)
    resolved = shutil.which(tool, path=hardened.get("PATH"))
    if resolved:
        return str(Path(resolved).resolve())
    return None


def build_upgrade_plan(
    *,
    method: InstallMethod | None = None,
    env: dict[str, str] | None = None,
    dist: str = DIST_NAME,
) -> UpgradePlan:
    """Build the :class:`UpgradePlan` for the running install."""

    resolved_method = method if method is not None else detect_install_method()

    if resolved_method is InstallMethod.UV_TOOL:
        # ``--reinstall`` (which implies ``--refresh``) is what makes ``upgrade``
        # a safe, self-healing operation rather than a fragile in-place bump. A
        # plain ``uv tool upgrade`` no-ops or fails when the tool venv is in a
        # broken state — a stale PyPI cache, or an orphaned interpreter after the
        # base Python moved (e.g. a Homebrew bump). Both leave operators forced
        # to hand-run ``uv tool install … --force``. ``--reinstall`` rebuilds the
        # venv from scratch and bypasses the cache, matching install.sh's
        # ``--force`` posture, while ``upgrade`` (not ``install``) preserves the
        # extras recorded in uv's tool receipt — ``uv tool upgrade`` takes only a
        # bare tool NAME and rejects a ``dist[extra]`` spec.
        uv = resolve_tool("uv", env)
        if uv is not None:
            return UpgradePlan(
                method=resolved_method,
                delegated=True,
                tool=uv,
                command=[uv, "tool", "upgrade", dist, "--reinstall"],
                manual_hint=f"uv tool upgrade {dist} --reinstall",
            )
        return UpgradePlan(
            method=resolved_method,
            delegated=False,
            tool=None,
            command=["uv", "tool", "upgrade", dist, "--reinstall"],
            manual_hint=f"uv tool upgrade {dist} --reinstall",
        )

    if resolved_method is InstallMethod.PIPX:
        # ``--force`` is pipx's counterpart to uv's ``--reinstall``: it rebuilds
        # the managed venv instead of no-op'ing or failing when it is in a broken
        # state (stale wheel, orphaned interpreter after the base Python moved).
        # ``pipx upgrade`` (not ``pipx reinstall``) is the right verb — ``upgrade
        # --force`` still moves to the newest version, whereas ``reinstall`` only
        # re-lays-down the currently pinned version. Extras are preserved by pipx
        # across the forced upgrade.
        pipx = resolve_tool("pipx", env)
        if pipx is not None:
            return UpgradePlan(
                method=resolved_method,
                delegated=True,
                tool=pipx,
                command=[pipx, "upgrade", dist, "--force"],
                manual_hint=f"pipx upgrade {dist} --force",
            )
        return UpgradePlan(
            method=resolved_method,
            delegated=False,
            tool=None,
            command=["pipx", "upgrade", dist, "--force"],
            manual_hint=f"pipx upgrade {dist} --force",
        )

    if resolved_method is InstallMethod.EDITABLE:
        return UpgradePlan(
            method=resolved_method,
            delegated=False,
            tool=None,
            command=["git", "pull"],
            manual_hint=(
                "editable / source checkout — pull the repo and reinstall: git pull && uv sync"
            ),
        )

    if resolved_method is InstallMethod.PIP:
        # A genuine site-packages install: pip is the right upgrade tool.
        pip_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", dist]
        return UpgradePlan(
            method=resolved_method,
            delegated=False,
            tool=None,
            command=pip_cmd,
            manual_hint=f"{sys.executable} -m pip install --upgrade {dist}",
        )

    # UNKNOWN: we could not classify the install, so a blind ``python -m pip``
    # may be actively wrong (e.g. a uv/pipx venv has no pip). List all three
    # installers and let the operator pick the one they originally used.
    return UpgradePlan(
        method=resolved_method,
        delegated=False,
        tool=None,
        command=[sys.executable, "-m", "pip", "install", "--upgrade", dist],
        manual_hint=(
            "could not detect the install method — reinstall/upgrade with your "
            f"original installer, e.g.:\n    uv tool install {dist}\n    "
            f"pipx install {dist}\n    {sys.executable} -m pip install --upgrade {dist}"
        ),
    )
