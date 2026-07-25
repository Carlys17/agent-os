"""Surface-neutral tool confirmation policy.

Authentication and pairing happen before tool dispatch. Once admitted, every
human surface follows the same SAFE/CONFIRM classification; configured agent
policy, sandboxing, and approval decisions provide the remaining boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from agentos.safety.tool_tiers import RiskTier, get_tier

CHANNEL_WEBUI: Final[str] = "webui"
CHANNEL_DM: Final[str] = "dm"
CHANNEL_GROUP: Final[str] = "group"


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str


def is_tool_allowed(tool_name: str, channel_kind: str) -> PermissionDecision:
    del channel_kind
    tier = get_tier(tool_name)
    if tier is RiskTier.SAFE:
        return PermissionDecision(True, "safe")
    return PermissionDecision(True, "confirmation_required")


def clear_channel_overrides() -> None:
    """Compatibility no-op: per-channel privilege overrides no longer exist."""


__all__ = [
    "CHANNEL_DM",
    "CHANNEL_GROUP",
    "CHANNEL_WEBUI",
    "PermissionDecision",
    "clear_channel_overrides",
    "is_tool_allowed",
]
