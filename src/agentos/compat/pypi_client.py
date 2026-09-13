"""Tiny isolated PyPI client for the upgrade check + passive update notice.

Network access is quarantined here so every caller (``agentos upgrade
--check``, the passive update notice, the skew path) shares one code path that
is trivially mockable in tests. The client never raises on a network / offline
failure: it returns ``None`` so callers degrade to "could not check" instead of
crashing a command whose real job is something else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agentos.paths import state_dir

DIST_NAME = "use-agent-os"
_PYPI_JSON_URL = "https://pypi.org/pypi/{dist}/json"
_CHECK_INTERVAL_S = 24 * 60 * 60
_STATE_FILE = ("update_notice.json",)


def latest_version(
    dist: str = DIST_NAME,
    *,
    timeout: float = 5.0,
) -> str | None:
    """Return the latest released version string of ``dist`` on PyPI.

    Yanked releases and pre/dev releases (``rcN`` / ``aN`` / ``bN`` /
    ``.devN``) are skipped: stable users must never be pointed at a pulled
    build or a release candidate they did not opt into. Falls back to the
    ``info.version`` field PyPI reports as canonical when the release list
    cannot answer (or everything in it is filtered out). Returns ``None`` on
    any failure (offline, timeout, HTTP error, malformed body).
    """

    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a hard dependency
        return None

    url = _PYPI_JSON_URL.format(dist=dist)
    try:
        response = httpx.get(
            url,
            timeout=timeout,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
    except Exception:  # noqa: BLE001 - offline / DNS / TLS / timeout all degrade to None
        return None

    if response.status_code != 200:
        return None

    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - malformed body
        return None

    if not isinstance(body, dict):
        return None
    info = body.get("info")
    canonical: str | None = None
    if isinstance(info, dict):
        version = info.get("version")
        if isinstance(version, str) and version.strip():
            canonical = version.strip()

    from agentos.compat.version_utils import parse_version

    releases = body.get("releases")
    if isinstance(releases, dict):
        best: tuple[tuple[Any, ...], str] | None = None
        for raw_version, files in releases.items():
            if not isinstance(raw_version, str) or not raw_version.strip():
                continue
            # ``releases`` keys carry the full version list; the per-version
            # file list is what flags a yank, but a yanked upload also removes
            # its files, so treat "no files" the same as "yanked".
            if not isinstance(files, list) or not files:
                continue
            yanked = any(isinstance(f, dict) and f.get("yanked") is True for f in files)
            if yanked:
                continue
            parsed = parse_version(raw_version)
            # Pre/dev tails are opt-in channels; never recommend them to a
            # stable install. Unparsable strings sort below every real
            # release, so they lose the max() below naturally.
            if parsed.pre is not None or parsed.dev is not None or not parsed.parsed:
                continue
            key = parsed.sort_key(width=len(parsed.release))
            if best is None or key > best[0]:
                best = (key, raw_version.strip())
        if best is not None:
            return best[1]

    return canonical


def notice_state_path() -> Path:
    return state_dir(*_STATE_FILE)


def read_state(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(path: Path, last_checked: float, latest: str | None, surface: str = "cli") -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        state = read_state(path)
        if surface not in state or not isinstance(state[surface], dict):
            state[surface] = {}

        surface_dict = state[surface]
        if isinstance(surface_dict, dict):
            surface_dict["last_checked"] = last_checked

        if latest:
            state["latest"] = latest

        # Atomic replace: a concurrent read (Web UI updates.check vs a CLI
        # notice) must never observe a truncated / half-written file, and on
        # Windows a direct overwrite of a file another handle holds open
        # raises PermissionError. Write-then-replace in the same directory
        # keeps both readers safe.
        tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError:
        pass  # best-effort; a read-only home just means we re-check next time


def due_for_check(path: Path, now: float, surface: str = "cli") -> bool:
    state = read_state(path)
    surface_state = state.get(surface)
    if isinstance(surface_state, dict):
        last = surface_state.get("last_checked")
    else:
        last = state.get("last_checked")
    if not isinstance(last, int | float):
        return True
    return (now - float(last)) >= _CHECK_INTERVAL_S


def config_notify_enabled(config: object | None) -> bool:
    updates = getattr(config, "updates", None)
    if updates is None:
        return True
    return bool(getattr(updates, "notify", True))
