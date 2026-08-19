"""Connection-surface authorization for gateway RPC calls.

AgentOS is a personal-agent runtime. Human callers do not form a privilege
hierarchy: a Control client is either connected or disconnected, and a channel
identity is either paired or unpaired. RPC authorization therefore depends on
the surface that admitted the request, not on user roles or implied scopes.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class ConnectionSurface(StrEnum):
    """Protocol surface that admitted a request."""

    CONTROL = "control"
    CHANNEL = "channel"
    NODE = "node"
    SYSTEM = "system"


CONTROL_ONLY: frozenset[ConnectionSurface] = frozenset({ConnectionSurface.CONTROL})
CONTROL_AND_CHANNEL: frozenset[ConnectionSurface] = frozenset(
    {ConnectionSurface.CONTROL, ConnectionSurface.CHANNEL}
)
CONTROL_AND_NODE: frozenset[ConnectionSurface] = frozenset(
    {ConnectionSurface.CONTROL, ConnectionSurface.NODE}
)

# Channel slash commands are projected from ``engine.commands`` and are the
# only channel traffic allowed to enter the RPC registry.
CHANNEL_RPC_METHODS: frozenset[str] = frozenset(
    {
        "chat.history",
        "commands.list_for_surface",
        "doctor.memory.status",
        "models.list",
        "plan.mode.set",
        "router.hold.clear",
        "router.hold.set",
        "sessions.abort",
        "sessions.contextCompact",
        "sessions.rename",
        "sessions.reset",
        "skills.list",
        "status",
        "usage.status",
    }
)

NODE_RPC_METHODS: frozenset[str] = frozenset({"skills.bins"})


def normalize_audiences(
    audiences: ConnectionSurface | Iterable[ConnectionSurface],
) -> frozenset[ConnectionSurface]:
    """Return an immutable, non-empty audience set."""

    if isinstance(audiences, ConnectionSurface):
        return frozenset({audiences})
    normalized = frozenset(ConnectionSurface(item) for item in audiences)
    if not normalized:
        raise ValueError("RPC audiences must not be empty")
    return normalized


def is_loopback_address(addr: str | None) -> bool:
    """Return whether ``addr`` is a literal loopback IPv4/IPv6 address."""

    if not addr:
        return False
    host = addr.split("%", 1)[0]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.startswith("::ffff:"):
        host = host[7:]
    if host in ("::1", "localhost"):
        return True
    if host.startswith("127."):
        parts = host.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) <= 255 for part in parts)
        except ValueError:
            return False
    return False


def is_loopback_bind(host: str | None) -> bool:
    """Return whether the gateway is bound to a loopback-only address."""

    if not host:
        return False
    return host == "localhost" or is_loopback_address(host)


__all__ = [
    "CHANNEL_RPC_METHODS",
    "CONTROL_AND_CHANNEL",
    "CONTROL_AND_NODE",
    "CONTROL_ONLY",
    "NODE_RPC_METHODS",
    "ConnectionSurface",
    "is_loopback_address",
    "is_loopback_bind",
    "normalize_audiences",
]
