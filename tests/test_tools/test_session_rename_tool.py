"""Tests for the ``session_rename`` tool (prompt-driven session rename).

The fakes here expose ONLY the production ``SessionManager`` surface the tool
is allowed to touch (``get_session`` + ``update``) so a test can never pass
against a method the live gateway does not have — the failure mode that made
``session_status`` unusable in production (see
``test_sessions_status_regression.py``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from agentos.session.naming import MAX_SESSION_NAME_LENGTH
from agentos.tools.builtin import sessions as sessions_tool
from agentos.tools.types import ToolContext, ToolError, current_tool_context


@dataclass
class _StubSession:
    session_key: str = "agent:main:webchat:abc123"
    session_id: str = "sess-1"
    display_name: str | None = None


class _ProductionSurfaceManager:
    """Mirrors the real SessionManager: ``get_session`` + ``update``."""

    def __init__(self, sessions: dict[str, _StubSession]) -> None:
        self._sessions = sessions
        self.updates: list[tuple[str, dict[str, object]]] = []

    async def get_session(self, session_key: str) -> _StubSession | None:
        return self._sessions.get(session_key)

    async def update(self, session_key: str, **fields: object) -> _StubSession:
        node = self._sessions.get(session_key)
        if node is None:
            raise KeyError(f"Session not found: {session_key}")
        self.updates.append((session_key, dict(fields)))
        for key, value in fields.items():
            setattr(node, key, value)
        return node


@dataclass
class _NoUpdateManager:
    """A manager that can read sessions but cannot persist a rename."""

    sessions: dict[str, _StubSession] = field(default_factory=dict)

    async def get_session(self, session_key: str) -> _StubSession | None:
        return self.sessions.get(session_key)


@pytest.fixture
def _restore_manager():
    original = sessions_tool._session_manager
    yield
    sessions_tool.set_session_manager(original)


def _set_ctx(session_key: str | None) -> object:
    return current_tool_context.set(ToolContext(session_key=session_key))


async def _rename(name: str) -> dict:
    return json.loads(await sessions_tool.session_rename(name))


@pytest.mark.asyncio
async def test_rename_sets_the_calling_sessions_display_name(_restore_manager):
    session = _StubSession()
    mgr = _ProductionSurfaceManager({session.session_key: session})
    sessions_tool.set_session_manager(mgr)
    token = _set_ctx(session.session_key)
    try:
        data = await _rename("Speeding ticket report")
    finally:
        current_tool_context.reset(token)

    assert data["name"] == "Speeding ticket report"
    assert data["previous_name"] is None
    assert data["session_key"] == session.session_key
    assert data["cleared"] is False
    assert mgr.updates == [(session.session_key, {"display_name": "Speeding ticket report"})]
    assert session.display_name == "Speeding ticket report"


@pytest.mark.asyncio
async def test_rename_renames_only_the_calling_session(_restore_manager):
    mine = _StubSession(session_key="agent:main:webchat:mine")
    other = _StubSession(session_key="agent:main:webchat:other")
    mgr = _ProductionSurfaceManager({mine.session_key: mine, other.session_key: other})
    sessions_tool.set_session_manager(mgr)
    token = _set_ctx(mine.session_key)
    try:
        await _rename("Mine")
    finally:
        current_tool_context.reset(token)

    assert mine.display_name == "Mine"
    assert other.display_name is None


@pytest.mark.asyncio
async def test_empty_name_clears_the_session_name(_restore_manager):
    session = _StubSession(display_name="Old label")
    mgr = _ProductionSurfaceManager({session.session_key: session})
    sessions_tool.set_session_manager(mgr)
    token = _set_ctx(session.session_key)
    try:
        data = await _rename("   ")
    finally:
        current_tool_context.reset(token)

    assert data["name"] is None
    assert data["previous_name"] == "Old label"
    assert data["cleared"] is True
    assert mgr.updates == [(session.session_key, {"display_name": None})]
    assert session.display_name is None


@pytest.mark.asyncio
async def test_name_is_normalized_like_every_other_rename_surface(_restore_manager):
    """Same normalizer as ``sessions.rename``: one line, trimmed, capped."""
    session = _StubSession()
    mgr = _ProductionSurfaceManager({session.session_key: session})
    sessions_tool.set_session_manager(mgr)
    token = _set_ctx(session.session_key)
    try:
        data = await _rename("  Trading\n\tdesk   notes  ")
    finally:
        current_tool_context.reset(token)

    assert data["name"] == "Trading desk notes"


@pytest.mark.asyncio
async def test_overlong_name_is_truncated_not_rejected(_restore_manager):
    session = _StubSession()
    mgr = _ProductionSurfaceManager({session.session_key: session})
    sessions_tool.set_session_manager(mgr)
    token = _set_ctx(session.session_key)
    try:
        data = await _rename("x" * (MAX_SESSION_NAME_LENGTH + 40))
    finally:
        current_tool_context.reset(token)

    assert data["name"] == "x" * MAX_SESSION_NAME_LENGTH


@pytest.mark.asyncio
async def test_rename_without_an_active_session_is_an_error(_restore_manager):
    sessions_tool.set_session_manager(_ProductionSurfaceManager({}))
    token = _set_ctx(None)
    try:
        with pytest.raises(ToolError, match="No active session"):
            await _rename("Anything")
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_rename_of_a_vanished_session_is_an_error(_restore_manager):
    sessions_tool.set_session_manager(_ProductionSurfaceManager({}))
    token = _set_ctx("agent:main:webchat:vanished")
    try:
        with pytest.raises(ToolError, match="No active session"):
            await _rename("Anything")
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_session_deleted_between_read_and_write_is_a_tool_error(_restore_manager):
    """The real manager raises KeyError from ``update``; it must not escape."""
    session = _StubSession()
    mgr = _ProductionSurfaceManager({session.session_key: session})

    async def _vanish(session_key: str, **fields: object) -> _StubSession:
        raise KeyError(f"Session not found: {session_key}")

    mgr.update = _vanish  # type: ignore[method-assign]
    sessions_tool.set_session_manager(mgr)
    token = _set_ctx(session.session_key)
    try:
        with pytest.raises(ToolError, match="No active session"):
            await _rename("Anything")
    finally:
        current_tool_context.reset(token)


@pytest.mark.asyncio
async def test_rename_reports_when_storage_cannot_persist(_restore_manager):
    """Never return success the next list view would immediately contradict."""
    session = _StubSession()
    sessions_tool.set_session_manager(_NoUpdateManager({session.session_key: session}))
    token = _set_ctx(session.session_key)
    try:
        with pytest.raises(ToolError, match="cannot persist"):
            await _rename("Anything")
    finally:
        current_tool_context.reset(token)
