"""Regression tests for role-free dispatch surface hardening.

Two boundaries are exercised here:

1. Channel callers (and anonymous callers with no
   :class:`ToolContext`) must not be able to enumerate the registry by
   probing tool names. The registry-miss envelope they see must be opaque,
   while the structured log retains the actual tool name for diagnostics.

2. A channel tool explicitly admitted by agent configuration is not
   subjected to a second role gate.
"""

from __future__ import annotations

import json

import pytest
import structlog.testing

from agentos.engine.types import ToolCall
from agentos.tools.dispatch import build_tool_handler
from agentos.tools.registry import ToolRegistry
from agentos.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    ToolSpec,
    current_tool_context,
)


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def some_tool() -> str:
        return "ok"

    registry.register(
        ToolSpec(name="some_real_tool", description="real", parameters={}),
        some_tool,
    )
    return registry


_PROBE_TOOL_NAME = "definitely_not_a_real_tool_xyz"


@pytest.mark.asyncio
async def test_registry_miss_for_channel_caller_is_opaque() -> None:
    handler = build_tool_handler(_build_registry())
    ctx = ToolContext(
                caller_kind=CallerKind.CHANNEL,
        interaction_mode=InteractionMode.UNATTENDED,
        agent_id="main",
        session_key="agent:main:hardening",
    )
    token = current_tool_context.set(ctx)
    try:
        with structlog.testing.capture_logs() as captured:
            result = await handler(
                ToolCall(
                    tool_use_id="tc-opaque-1",
                    tool_name=_PROBE_TOOL_NAME,
                    arguments={},
                )
            )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["error_class"] == "PolicyDenied"
    assert payload["status"] == "error"
    assert payload["user_message"] == "Tool unavailable for this surface."
    # The tool name must NOT appear in any user-visible field.
    assert _PROBE_TOOL_NAME not in payload["user_message"]

    # Operators must still be able to debug the miss via structured logs.
    miss_events = [e for e in captured if e["event"] == "dispatch.registry_miss"]
    assert miss_events, "dispatch.registry_miss must be logged"
    event = miss_events[0]
    assert event["tool"] == _PROBE_TOOL_NAME
    assert event["untrusted_caller"] is True
    assert event["is_skill"] is False
    assert event["session_key"] == "agent:main:hardening"


@pytest.mark.asyncio
async def test_registry_miss_for_anonymous_caller_is_opaque() -> None:
    """No ``ToolContext`` at all is treated as untrusted for the same reason."""
    handler = build_tool_handler(_build_registry())

    with structlog.testing.capture_logs() as captured:
        result = await handler(
            ToolCall(
                tool_use_id="tc-opaque-2",
                tool_name=_PROBE_TOOL_NAME,
                arguments={},
            )
        )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["error_class"] == "PolicyDenied"
    assert _PROBE_TOOL_NAME not in payload["user_message"]
    miss_events = [e for e in captured if e["event"] == "dispatch.registry_miss"]
    assert miss_events and miss_events[0]["tool"] == _PROBE_TOOL_NAME


@pytest.mark.asyncio
async def test_registry_miss_for_channel_skill_collision_is_opaque() -> None:
    """Even the skill-collision branch must not echo the probed name."""
    handler = build_tool_handler(
        _build_registry(),
        known_skill_names={"my_skill"},
    )
    ctx = ToolContext(
                caller_kind=CallerKind.CHANNEL,
        interaction_mode=InteractionMode.UNATTENDED,
        agent_id="main",
        session_key="agent:main:hardening",
    )
    token = current_tool_context.set(ctx)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-opaque-3",
                tool_name="my_skill",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result.content)
    assert payload["error_class"] == "PolicyDenied"
    assert "my_skill" not in payload["user_message"]


@pytest.mark.asyncio
async def test_registry_miss_for_cli_caller_preserves_descriptive_envelope() -> None:
    """Trusted CLI callers must keep the actionable ToolNotFound message."""
    handler = build_tool_handler(_build_registry())
    ctx = ToolContext(
                caller_kind=CallerKind.CLI,
        agent_id="main",
        session_key="cli:main:hardening",
    )
    token = current_tool_context.set(ctx)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-cli-miss",
                tool_name=_PROBE_TOOL_NAME,
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result.content)
    assert payload["error_class"] == "ToolNotFound"
    assert _PROBE_TOOL_NAME in payload["user_message"]


@pytest.mark.asyncio
async def test_channel_registry_miss_cannot_be_promoted_to_verbose_envelope() -> None:
    handler = build_tool_handler(_build_registry())
    ctx = ToolContext(
                caller_kind=CallerKind.CHANNEL,
        interaction_mode=InteractionMode.UNATTENDED,
        agent_id="main",
        session_key="agent:main:hardening",
    )
    token = current_tool_context.set(ctx)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-channel-miss",
                tool_name=_PROBE_TOOL_NAME,
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    payload = json.loads(result.content)
    assert payload["error_class"] == "PolicyDenied"
    assert _PROBE_TOOL_NAME not in payload["user_message"]


def _registry_with(name: str) -> ToolRegistry:
    registry = ToolRegistry()

    async def handler() -> str:
        return "ok"

    registry.register(ToolSpec(name=name, description=name, parameters={}), handler)
    return registry


@pytest.mark.asyncio
async def test_configured_channel_tool_has_no_second_role_gate() -> None:
    handler = build_tool_handler(_registry_with("git_push"))
    ctx = ToolContext(
        caller_kind=CallerKind.CHANNEL,
        interaction_mode=InteractionMode.UNATTENDED,
        agent_id="main",
        session_key="agent:main:hardening",
        allowed_tools={"git_push"},
    )
    token = current_tool_context.set(ctx)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-configured-channel",
                tool_name="git_push",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is False
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_webui_source_can_execute_configured_tools() -> None:
    handler = build_tool_handler(_registry_with("write_file"))
    ctx = ToolContext(
                caller_kind=CallerKind.CHANNEL,
        interaction_mode=InteractionMode.INTERACTIVE,
        agent_id="main",
        session_key="agent:main:webchat:hardening",
        channel_kind="webchat",
        source_kind="webui",
    )
    token = current_tool_context.set(ctx)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-webui-write",
                tool_name="write_file",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is False
    assert result.content == "ok"
