"""Tiny isolated PyPI client for the upgrade check + passive update notice.

Network access is quarantined here so every caller (``agentos upgrade
--check``, the passive update notice, the skew path) shares one code path that
is trivially mockable in tests. The client never raises on a network / offline
failure: it returns ``None`` so callers degrade to "could not check" instead of
crashing a command whose real job is something else.
"""

from __future__ import annotations

import json
from pathlib import Path

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

    Returns ``None`` on any failure (offline, timeout, HTTP error, malformed
    body). Yanked-only / pre-release-only edge cases fall back to the
    ``info.version`` field PyPI reports as canonical.
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
    if isinstance(info, dict):
        version = info.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    return None


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

        path.write_text(json.dumps(state), encoding="utf-8")
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
