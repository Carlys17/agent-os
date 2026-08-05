"""Shared watermark store for cron watcher scripts.

A watcher runs every few minutes and must report only what is new since the
last run, so each one keeps a small JSON file of the ids it has already seen.
State lives under the AgentOS state root (``AGENTOS_STATE_DIR`` or
``~/.agentos``) in ``state/cron-watchers/<name>.json`` — never next to the
script, so the scripts directory stays read-only in practice.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

MAX_REMEMBERED_IDS = 500


def _state_root() -> Path:
    override = os.environ.get("AGENTOS_STATE_DIR", "").strip()
    if override:
        base = Path(override).expanduser()
    else:
        home = os.environ.get("HOME", "").strip()
        base = (Path(home) if home else Path.home()) / ".agentos"
    return base / "state" / "cron-watchers"


def watermark_path(name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name) or "watcher"
    return _state_root() / f"{safe}.json"


def load_seen(name: str) -> list[str]:
    """Return the ids this watcher has already reported, oldest first."""
    try:
        raw = json.loads(watermark_path(name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    seen = raw.get("seen") if isinstance(raw, dict) else None
    if not isinstance(seen, list):
        return []
    return [str(item) for item in seen]


def save_seen(name: str, ids: list[str]) -> None:
    """Persist the most recent ids, trimmed so the file cannot grow forever."""
    path = watermark_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = [str(item) for item in ids][-MAX_REMEMBERED_IDS:]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"seen": trimmed}), encoding="utf-8")
    tmp.replace(path)


def select_new(name: str, ids: list[str], *, first_run_reports: bool = False) -> list[str]:
    """Return the ids not seen before and record them.

    The first run reports nothing by default: a watcher that has never run has
    no idea which of the 50 items on the page are actually new, and dumping all
    of them into a chat is the wrong first impression.
    """
    seen = set(load_seen(name))
    is_first_run = not seen
    fresh = [item for item in ids if item not in seen]
    save_seen(name, [*load_seen(name), *fresh])
    if is_first_run and not first_run_reports:
        return []
    return fresh
