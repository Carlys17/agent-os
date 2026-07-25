"""Role-free risk classification for tool execution."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class RiskTier(StrEnum):
    SAFE = "safe"
    CONFIRM = "confirm"


# Host-mutating tools can never be downgraded to automatic execution.
HARDCODED_CONFIRM: Final[frozenset[str]] = frozenset(
    {
        "shell_exec",
        "exec_command",
        "background_process",
        "file_write",
        "write_file",
        "edit_file",
        "apply_patch",
        "git_push",
        "channel_send",
    }
)

_DECLARATIONS: dict[str, RiskTier] = {}


def declare_tier(tool_name: str, tier: RiskTier) -> None:
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("tool_name must be a non-empty str")
    if not isinstance(tier, RiskTier):
        raise TypeError("tier must be a RiskTier member")
    _DECLARATIONS[tool_name] = tier


def get_tier(tool_name: str, default: RiskTier = RiskTier.CONFIRM) -> RiskTier:
    if tool_name in HARDCODED_CONFIRM:
        return RiskTier.CONFIRM
    return _DECLARATIONS.get(tool_name, default)


def reset_declarations() -> None:
    _DECLARATIONS.clear()


__all__ = [
    "HARDCODED_CONFIRM",
    "RiskTier",
    "declare_tier",
    "get_tier",
    "reset_declarations",
]
