"""Issue #248: `/rename` labels the live session on both CLI surfaces.

Gateway mode delegates to ``sessions.rename`` and mirrors whatever the gateway
stored; standalone mode writes ``display_name`` through the session manager.
Both then refresh the toolbar chip so the new name is visible immediately.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.cli.chat.session_state import ChatSessionState
from agentos.cli.tui.adapters.slash_gateway import (
    GatewaySlashContext,
    handle_gateway_slash_command,
)
from agentos.cli.tui.adapters.slash_standalone import (
    StandaloneSlashContext,
    StandaloneSlashServices,
    handle_standalone_slash_command,
)


class _RenameClient:
    """Only the surface `/rename` touches; anything else is a test bug."""

    def __init__(self, stored: str | None = "normalized") -> None:
        self.calls: list[tuple[str, str | None]] = []
        self._stored = stored

    async def rename_session(self, key: str, name: str | None) -> dict[str, Any]:
        self.calls.append((key, name))
        return {"key": key, "name": self._stored, "displayName": self._stored}

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - guard rail
        raise AssertionError(f"{item} is not used by these tests")


def _gateway_context(client: _RenameClient) -> GatewaySlashContext:
    state = ChatSessionState(session_key="agent:main:cli:test", model="openai/test")
    return GatewaySlashContext(state=state, client=client, elevated_state={})


@pytest.mark.asyncio
async def test_gateway_rename_calls_the_rpc_and_mirrors_the_stored_name() -> None:
    client = _RenameClient(stored="api refactor")
    context = _gateway_context(client)

    handled = await handle_gateway_slash_command("/rename   api   refactor ", context)

    assert handled is True
    assert client.calls == [("agent:main:cli:test", "api   refactor")]
    # The gateway normalizes; the CLI shows what was actually stored.
    assert context.state.display_name == "api refactor"


@pytest.mark.asyncio
async def test_gateway_rename_with_no_argument_clears_the_name() -> None:
    client = _RenameClient(stored=None)
    context = _gateway_context(client)
    context.state.display_name = "old name"

    handled = await handle_gateway_slash_command("/rename", context)

    assert handled is True
    assert client.calls == [("agent:main:cli:test", "")]
    assert context.state.display_name is None


class _StandaloneManager:
    def __init__(self) -> None:
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def update(self, session_key: str, **fields: Any) -> None:
        self.updates.append((session_key, fields))


def _standalone_context(
    manager: _StandaloneManager | None,
) -> StandaloneSlashContext:
    state = ChatSessionState(session_key="agent:main:standalone:test", model="openai/test")
    return StandaloneSlashContext(
        state=state,
        session_key=state.session_key,
        model=state.model,
        tool_ctx=object(),
        slash_services=StandaloneSlashServices(
            update_session=manager.update if manager is not None else None,
        ),
        turn_runner=object(),
        build_tool_ctx=lambda _session_key: object(),
        replace_session=lambda **_updates: None,
    )


@pytest.mark.asyncio
async def test_standalone_rename_persists_a_normalized_display_name() -> None:
    manager = _StandaloneManager()
    context = _standalone_context(manager)

    handled = await handle_standalone_slash_command("/rename  bug   46 ", context)

    assert handled is True
    assert manager.updates == [
        ("agent:main:standalone:test", {"display_name": "bug 46"}),
    ]
    assert context.state.display_name == "bug 46"


@pytest.mark.asyncio
async def test_standalone_rename_with_no_argument_clears_the_name() -> None:
    manager = _StandaloneManager()
    context = _standalone_context(manager)
    context.state.display_name = "old name"

    handled = await handle_standalone_slash_command("/rename", context)

    assert handled is True
    assert manager.updates == [("agent:main:standalone:test", {"display_name": None})]
    assert context.state.display_name is None


@pytest.mark.asyncio
async def test_standalone_rename_without_a_session_manager_is_a_no_op() -> None:
    context = _standalone_context(None)
    context.state.display_name = "kept"

    handled = await handle_standalone_slash_command("/rename new", context)

    assert handled is True
    assert context.state.display_name == "kept"


@pytest.mark.asyncio
async def test_a_name_with_rich_markup_does_not_break_the_confirmation() -> None:
    """`console.print` parses markup, so an unbalanced "[/]" used to raise."""
    client = _RenameClient(stored="oops [/] [red]name")
    context = _gateway_context(client)

    handled = await handle_gateway_slash_command("/rename oops [/] [red]name", context)

    assert handled is True
    assert context.state.display_name == "oops [/] [red]name"

    # /status renders the same name through a second markup path.
    assert await handle_gateway_slash_command("/status", context) is True


@pytest.mark.asyncio
async def test_standalone_name_with_rich_markup_does_not_break_output() -> None:
    manager = _StandaloneManager()
    context = _standalone_context(manager)

    handled = await handle_standalone_slash_command("/rename oops [/] name", context)

    assert handled is True
    assert context.state.display_name == "oops [/] name"
    assert await handle_standalone_slash_command("/status", context) is True
