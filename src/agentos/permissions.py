"""Shared permission posture helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ELEVATED_PERMISSION_MODES = frozenset({"on", "bypass", "full"})
PERMISSION_MODES = frozenset({"off", *ELEVATED_PERMISSION_MODES})

# A cron turn has no human behind it, so only the two approval-free modes make
# sense. "on" is excluded deliberately rather than by omission: it skips the
# sandbox but has no branch in the exec approval path, so the first warned
# command would raise UnsupportedSurfaceError and kill the run.
CRON_ELEVATED_MODES = frozenset({"bypass", "full"})


def normalize_permission_mode(value: Any, *, default: str = "off") -> str:
    mode = str(value if value is not None else default).strip().lower()
    if mode == "restricted":
        return "off"
    if mode in PERMISSION_MODES:
        return mode
    allowed = ", ".join(sorted(PERMISSION_MODES | {"restricted"}))
    raise ValueError(f"permissions must be one of: {allowed}")


def normalize_cron_elevated(value: Any) -> str | None:
    """Validate a cron job's requested elevation. Write-side, strict.

    Returns the stored mode, or None when the job is not elevated. ``True`` is
    the ergonomic spelling every surface offers and means "bypass"; "full" has
    to be asked for by name because it also disables the sensitive-path block.
    """

    if value is None or value is False:
        return None
    if value is True:
        return "bypass"
    mode = str(value).strip().lower()
    if mode in ("", "off", "false", "none"):
        return None
    if mode == "on":
        raise ValueError(
            "cron elevation cannot use 'on': it requires a human approver and "
            "every cron run is unattended. Use 'bypass'."
        )
    if mode in CRON_ELEVATED_MODES:
        return mode
    allowed = ", ".join(sorted(CRON_ELEVATED_MODES))
    raise ValueError(f"cron elevation must be one of: {allowed} (or off)")


def cron_tool_policy_elevated(tool_policy: Any) -> str | None:
    """Read the elevation out of a persisted cron tool policy. Never raises.

    The write boundaries (rpc_cron, SchedulerOps) are what reject bad values;
    a row that predates them, or one hand-edited in the database, must not be
    able to break routing. Anything unrecognised reads as "not elevated".
    """

    if not isinstance(tool_policy, Mapping):
        return None
    try:
        return normalize_cron_elevated(tool_policy.get("elevated"))
    except ValueError:
        return None


def configured_default_elevated(config: Any) -> str | None:
    permissions = getattr(config, "permissions", None)
    mode = normalize_permission_mode(
        getattr(permissions, "default_mode", None),
        default="off",
    )
    return mode if mode in ELEVATED_PERMISSION_MODES else None


def configured_cron_default_elevated(config: Any) -> str | None:
    permissions = getattr(config, "permissions", None)
    if permissions is None:
        return "bypass"
    cron_default_mode = getattr(permissions, "cron_default_mode", "bypass")
    mode = normalize_permission_mode(cron_default_mode, default="bypass")
    return mode if mode in CRON_ELEVATED_MODES else None
