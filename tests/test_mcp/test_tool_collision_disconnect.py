"""Regression tests for issue #801: MCP same-name tool collision on disconnect.

When two MCP servers expose a tool with the same name, disconnecting either
server must not remove the tool still owned by the other active server.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from agentos.mcp.client import MCPClient
from agentos.mcp.types import MCPServerConfig, MCPToolDef, MCPToolResult
from agentos.tools.registry import ToolRegistry


class _StaticClient(MCPClient):
    """FakeMCPClient that returns the same tool list for every config."""

    def __init__(self, config: MCPServerConfig) -> None:
        super().__init__(config)
        self.closed = False

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def list_tools(self) -> list[MCPToolDef]:
        return [
            MCPToolDef(
                name="lookup",
                description=f"Lookup from {self.config.name}",
                input_schema={"properties": {}, "required": []},
            )
        ]

    async def call_tool(self, name: str, arguments: dict) -> MCPToolResult:
        return MCPToolResult(content=f"{self.config.name}:{name}:{arguments}")


@pytest_asyncio.fixture(autouse=True)
async def _reset_mcp_state():
    from agentos.mcp import discovery
    from agentos.mcp.discovery import close_active_clients

    await close_active_clients()
    discovery._tool_owners.clear()
    yield
    await close_active_clients()
    discovery._tool_owners.clear()


@pytest.mark.asyncio
async def test_disconnect_older_server_preserves_newer_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disconnecting the older server must not remove a tool now owned by B."""
    from agentos.mcp import discovery

    config_a = MCPServerConfig(name="server_A", transport="stdio", command="mock-mcp")
    config_b = MCPServerConfig(name="server_B", transport="stdio", command="mock-mcp")
    client_a = _StaticClient(config_a)
    client_b = _StaticClient(config_b)
    clients = {config_a.name: client_a, config_b.name: client_b}

    monkeypatch.setattr(discovery, "create_client", lambda cfg: clients[cfg.name])

    registry = ToolRegistry()
    await discovery.discover_and_register(config_a, registry, owner="server_A")
    await discovery.discover_and_register(config_b, registry, owner="server_B")

    # Both servers active, but only ONE registration exists (B's wins).
    assert "mcp_lookup" in registry.list_names()
    assert discovery._tool_owners["lookup"] == "server_B"

    await discovery.disconnect_and_unregister("server_A", registry)

    # Acceptance: B's tool must survive A's disconnect.
    assert "mcp_lookup" in registry.list_names(), (
        "Disconnecting older server A must NOT remove a tool now owned by B"
    )
    assert client_a.closed is True
    assert client_b.closed is False
    assert discovery._tool_owners["lookup"] == "server_B"


@pytest.mark.asyncio
async def test_disconnect_newer_server_restores_older_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disconnecting the newer owner restores the older still-active handler."""
    from agentos.mcp import discovery

    config_a = MCPServerConfig(name="server_A", transport="stdio", command="mock-mcp")
    config_b = MCPServerConfig(name="server_B", transport="stdio", command="mock-mcp")
    client_a = _StaticClient(config_a)
    client_b = _StaticClient(config_b)
    clients = {config_a.name: client_a, config_b.name: client_b}

    monkeypatch.setattr(discovery, "create_client", lambda cfg: clients[cfg.name])

    registry = ToolRegistry()
    await discovery.discover_and_register(config_a, registry, owner="server_A")
    await discovery.discover_and_register(config_b, registry, owner="server_B")

    await discovery.disconnect_and_unregister("server_B", registry)

    # B was the current owner, so its disconnect removes B's handler — but A is
    # still active and registered the same name first, so A's handler returns.
    assert "mcp_lookup" in registry.list_names(), (
        "Disconnecting the newer owner must restore the older server's handler"
    )
    assert client_b.closed is True
    assert client_a.closed is False
    assert discovery._tool_owners["lookup"] == "server_A"

    # The restored handler must route to A, not to the disconnected B.
    registered = registry.get("mcp_lookup")
    assert registered is not None
    result = await registered.handler()
    assert "server_A" in result, (
        f"restored handler should call A, got: {result!r}"
    )


@pytest.mark.asyncio
async def test_disconnect_only_owner_removes_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a single server owns a unique tool, disconnect removes it."""
    from agentos.mcp import discovery

    config = MCPServerConfig(name="solo", transport="stdio", command="mock-mcp")
    client = _StaticClient(config)
    monkeypatch.setattr(discovery, "create_client", lambda _: client)

    registry = ToolRegistry()
    await discovery.discover_and_register(config, registry, owner="solo")
    assert "mcp_lookup" in registry.list_names()

    await discovery.disconnect_and_unregister("solo", registry)
    assert "mcp_lookup" not in registry.list_names()
    assert client.closed is True
    assert discovery._tool_owners == {}


@pytest.mark.asyncio
async def test_non_colliding_tools_remain_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A's unique tools must not be touched when B is disconnected, and vice versa."""

    from agentos.mcp import discovery

    class _MultiClient(MCPClient):
        def __init__(self, config: MCPServerConfig) -> None:
            super().__init__(config)
            self.closed = False

        async def connect(self) -> None:
            pass

        async def close(self) -> None:
            self.closed = True

        async def list_tools(self) -> list[MCPToolDef]:
            return [
                MCPToolDef(
                    name="shared",
                    description="shared",
                    input_schema={"properties": {}, "required": []},
                ),
                MCPToolDef(
                    name=f"only_{self.config.name}",
                    description=f"only {self.config.name}",
                    input_schema={"properties": {}, "required": []},
                ),
            ]

        async def call_tool(self, name: str, arguments: dict) -> MCPToolResult:
            return MCPToolResult(content=f"{self.config.name}:{name}:{arguments}")

    config_a = MCPServerConfig(name="server_A", transport="stdio", command="mock-mcp")
    config_b = MCPServerConfig(name="server_B", transport="stdio", command="mock-mcp")
    client_a = _MultiClient(config_a)
    client_b = _MultiClient(config_b)
    clients = {config_a.name: client_a, config_b.name: client_b}
    monkeypatch.setattr(discovery, "create_client", lambda cfg: clients[cfg.name])

    registry = ToolRegistry()
    await discovery.discover_and_register(config_a, registry, owner="server_A")
    await discovery.discover_and_register(config_b, registry, owner="server_B")

    # Both shared and unique tools registered.
    names = set(registry.list_names())
    assert "mcp_shared" in names
    assert "mcp_only_server_A" in names
    assert "mcp_only_server_B" in names

    # Disconnect A: B's "shared" must survive, A's unique must be removed.
    await discovery.disconnect_and_unregister("server_A", registry)
    names = set(registry.list_names())
    assert "mcp_shared" in names, "B's shared tool must survive A's disconnect"
    assert "mcp_only_server_A" not in names, "A's unique tool must be removed"
    assert "mcp_only_server_B" in names, "B's unique tool must remain"
