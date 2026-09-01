"""MCP tool discovery and registration into AgentOS ToolRegistry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

from agentos.mcp.client import MCPClient
from agentos.mcp.types import MCPServerConfig, MCPToolDef
from agentos.tools.registry import ToolRegistry
from agentos.tools.schema_sanitize import sanitize_input_schema
from agentos.tools.types import ToolHandler, ToolSpec

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ActiveMCPClient:
    """Tracked MCP client with the owner that controls its lifecycle."""

    owner: str
    server_name: str
    transport: str
    client: MCPClient
    registered_tools: tuple[str, ...] = ()
    # This server's own registrations: bare tool name -> (spec, handler).
    # Kept so a same-named tool registered by another server can be restored
    # when this server disconnects.
    tool_registrations: dict[str, tuple[ToolSpec, ToolHandler]] = field(
        default_factory=dict
    )

    async def close(self) -> None:
        await self.client.close()


# Module-level registry to keep clients alive for tool handlers.
_active_clients: list[ActiveMCPClient] = []

# Maps tool name (without mcp_ prefix) to the owner that last registered it.
# Used by disconnect_and_unregister to avoid removing a tool still owned by
# another active server that overwrote the registration.
_tool_owners: dict[str, str] = {}


def active_clients_snapshot() -> tuple[ActiveMCPClient, ...]:
    """Return active MCP clients without exposing mutable runtime state."""
    return tuple(_active_clients)


def _bare_name(name: str) -> str:
    """Strip the mcp_ prefix from a registered tool name."""
    return name[len("mcp_"):] if name.startswith("mcp_") else name


def _restore_survivor(
    name: str,
    remaining: list[ActiveMCPClient],
    registry: ToolRegistry,
) -> None:
    """Re-register the most recent surviving owner's handler for ``name``.

    When the current owner disconnects, the registry entry would otherwise be
    removed even though another active server still serves the same tool name.
    The survivor's stored (spec, handler) pair is re-registered verbatim so
    calls keep flowing to that server.
    """
    for entry in reversed(remaining):
        registration = entry.tool_registrations.get(_bare_name(name))
        if registration is not None:
            spec, handler = registration
            registry.register(spec, handler)
            _tool_owners[_bare_name(name)] = entry.owner
            return


async def close_active_clients(owner: str | None = None) -> int:
    """Close active MCP clients, optionally scoped to one owner/server name."""
    remaining: list[ActiveMCPClient] = []
    closing: list[ActiveMCPClient] = []
    for entry in _active_clients:
        if owner is None or entry.owner == owner or entry.server_name == owner:
            closing.append(entry)
        else:
            remaining.append(entry)
    _active_clients[:] = remaining

    # Drop tool-owner mappings for owners being closed.
    if owner is not None:
        for entry in closing:
            for name in entry.registered_tools:
                bare = _bare_name(name)
                # Only drop ownership if the disconnecting owner is still the
                # current owner — another active server may have taken over.
                if _tool_owners.get(bare) == entry.owner:
                    _tool_owners.pop(bare, None)
    else:
        _tool_owners.clear()

    closed = 0
    for entry in closing:
        try:
            await entry.close()
            closed += 1
        except Exception:
            pass
    return closed


async def disconnect_and_unregister(owner: str, registry: ToolRegistry) -> int:
    """Close one MCP server and remove the tools registered by that server.

    Only removes a tool from the registry if the disconnecting server is still
    its current owner. When it is, and another active server had registered the
    same tool name earlier, that survivor's handler is restored so the tool
    keeps working instead of disappearing.
    """
    snapshot = active_clients_snapshot()
    entries = [
        entry
        for entry in snapshot
        if entry.owner == owner or entry.server_name == owner
    ]
    remaining = [
        entry
        for entry in snapshot
        if not (entry.owner == owner or entry.server_name == owner)
    ]
    for entry in entries:
        for name in entry.registered_tools:
            bare = _bare_name(name)
            if _tool_owners.get(bare) != entry.owner:
                # A different owner took over — leave the tool registered.
                continue
            registry.unregister(name)
            _tool_owners.pop(bare, None)
            _restore_survivor(name, remaining, registry)
    return await close_active_clients(owner)


def create_client(config: MCPServerConfig) -> MCPClient:
    """Factory: create the appropriate MCPClient for the given transport."""
    if config.transport == "stdio":
        from agentos.mcp.stdio import MCPStdioClient

        return MCPStdioClient(config)
    elif config.transport == "sse":
        from agentos.mcp.sse import MCPSSEClient

        return MCPSSEClient(config)
    elif config.transport == "streamable_http":
        from agentos.mcp.streamable_http import MCPStreamableHTTPClient

        return MCPStreamableHTTPClient(config)
    else:
        raise ValueError(f"Unknown MCP transport: {config.transport!r}")


def _make_tool_handler(
    client: MCPClient,
    tool_name: str,
    tool_def: MCPToolDef,
    registry: ToolRegistry,
    timeout_seconds: float,
    owner: str,
) -> tuple[ToolSpec, ToolHandler]:
    """Register a single MCP tool into the registry with an mcp_ prefix.

    Returns the (spec, handler) pair so the caller can store it on the
    server's ActiveMCPClient entry for later restoration.
    """
    # The server's schema goes out verbatim in every provider request, so it is
    # normalized once here rather than per turn. A shape one backend tolerates
    # can make another reject the whole call, tools and all.
    schema, fixes = sanitize_input_schema(tool_def.input_schema)
    if fixes:
        log.info("mcp.schema_sanitized", tool=tool_name, fixes=fixes)
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    spec = ToolSpec(
        name=f"mcp_{tool_name}",
        description=tool_def.description,
        parameters=properties,
        required=required,
    )

    async def handler(**kwargs: Any) -> str:
        try:
            result = await asyncio.wait_for(
                client.call_tool(tool_name, kwargs),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return f"MCP tool '{tool_name}' timed out after {timeout_seconds}s"
        return result.content

    registry.register(spec, handler)
    # Track that this owner registered this tool name so disconnect knows
    # whether to remove it.
    _tool_owners[tool_name] = owner
    return spec, handler


async def discover_and_register(
    config: MCPServerConfig,
    registry: ToolRegistry,
    *,
    owner: str | None = None,
) -> list[str]:
    """Connect to MCP server, list tools, register each as a AgentOS tool.

    Returns list of registered tool names.
    The client is kept alive in module-level _active_clients so tool handlers can use it.
    """
    client = create_client(config)
    entry: ActiveMCPClient | None = None

    registered: list[str] = []
    registrations: dict[str, tuple[ToolSpec, ToolHandler]] = {}
    owner_id = owner or config.name
    try:
        await client.connect()
        tools = await client.list_tools()
        for t in tools:
            spec, handler = _make_tool_handler(
                client,
                t.name,
                t,
                registry,
                timeout_seconds=config.tool_timeout_seconds,
                owner=owner_id,
            )
            registered.append(f"mcp_{t.name}")
            registrations[t.name] = (spec, handler)
        entry = ActiveMCPClient(
            owner=owner_id,
            server_name=config.name,
            transport=config.transport,
            client=client,
            registered_tools=tuple(registered),
            tool_registrations=registrations,
        )
        _active_clients.append(entry)
    except BaseException:
        if entry is not None:
            try:
                _active_clients.remove(entry)
            except ValueError:
                pass
        await client.close()
        raise
    return registered
