"""Passive, gh-style "a new release is available" notice.

Emitted at most once per 24h on RPC-connected commands only (never on offline
paths). Every failure mode is silent — this is a courtesy line, never a reason
to slow down or break a command.

Suppression matrix (any one suppresses):
  * stderr is not a TTY            (piped / captured output)
  * a CI environment variable set  (CI / GITHUB_ACTIONS / …)
  * config ``updates.notify = false``
  * checked within the last 24h    (state file timestamp)
  * ``AGENTOS_NO_UPDATE_NOTICE=1`` escape hatch
"""

from __future__ import annotations

import os
import sys
import time

from agentos.compat.pypi_client import (
    config_notify_enabled,
    due_for_check,
    notice_state_path,
    write_state,
)

# Env vars that mark an automated / non-interactive context.
_CI_ENV_VARS = ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")


def _stderr_is_tty() -> bool:
    try:
        return bool(sys.stderr.isatty())
    except Exception:  # noqa: BLE001 - defensive; a broken stderr just suppresses
        return False


def _ci_active() -> bool:
    return any(os.environ.get(var, "").strip() for var in _CI_ENV_VARS)


def maybe_emit_update_notice(
    *,
    current_version: str,
    config: object | None = None,
    now: float | None = None,
    force: bool = False,
) -> str | None:
    """Emit the update notice to stderr if all suppression checks pass.

    Returns the message that was emitted (for tests), or ``None`` when
    suppressed. Network access is delegated to :mod:`pypi_client` and fully
    mockable; failures are silent.
    """

    if os.environ.get("AGENTOS_NO_UPDATE_NOTICE", "").strip() == "1":
        return None
    if not force:
        if not _stderr_is_tty():
            return None
        if _ci_active():
            return None
    if not config_notify_enabled(config):
        return None

    now = time.time() if now is None else now
    path = notice_state_path()
    if not force and not due_for_check(path, now, "cli"):
        return None

    from agentos.compat.pypi_client import latest_version
    from agentos.compat.version_utils import is_newer

    latest = latest_version(timeout=2.0)
    # Record the check regardless of outcome so an offline run still throttles.
    write_state(path, now, latest, "cli")
    if not latest or not is_newer(latest, current_version):
        return None

    message = (
        f"A new release of use-agent-os is available: "
        f"{current_version} → {latest}. Run 'agentos upgrade'."
    )
    print(message, file=sys.stderr)
    return message
