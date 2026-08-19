"""ask_user tool: dispatch behavior, end-turn contract, and surface gating."""

from __future__ import annotations

import json

import pytest

from agentos.tool_boundary import ToolCall
from agentos.tools import get_default_registry
from agentos.tools.dispatch import build_tool_handler
from agentos.tools.types import CallerKind, InteractionMode, ToolContext
from agentos.tools.visibility import effective_tool_context, is_tool_visible


def _call(arguments: dict | None = None) -> ToolCall:
    return ToolCall(
        tool_use_id="ask-1",
        tool_name="ask_user",
        arguments=arguments
        if arguments is not None
        else {
            "questions": [
                {
                    "question": "Deploy now?",
                    "options": [{"label": "Yes"}, {"label": "No"}],
                }
            ]
        },
    )


@pytest.mark.asyncio
async def test_ask_user_presents_and_terminates_turn() -> None:
    ctx = ToolContext(caller_kind=CallerKind.AGENT, session_key="agent:main:t-ask")
    handler = build_tool_handler(get_default_registry(), ctx)

    result = await handler(_call())

    assert result.is_error is False
    # The end-turn-and-resume contract: presenting the question ends the turn.
    assert result.terminates_turn is True
    payload = json.loads(result.content)
    assert payload["status"] == "question_presented"
    assert payload["questions"][0]["question"] == "Deploy now?"
    assert [o["label"] for o in payload["questions"][0]["options"]] == ["Yes", "No"]


@pytest.mark.asyncio
async def test_ask_user_rejects_invalid_questions_without_ending_turn() -> None:
    ctx = ToolContext(caller_kind=CallerKind.AGENT, session_key="agent:main:t-ask-bad")
    handler = build_tool_handler(get_default_registry(), ctx)

    result = await handler(
        _call({"questions": [{"question": "x?", "options": [{"label": "only one"}]}]})
    )

    assert result.is_error is True
    assert result.terminates_turn is False
    assert "between 2 and 4" in result.content


@pytest.mark.asyncio
async def test_ask_user_refuses_unattended_surfaces() -> None:
    ctx = ToolContext(
        caller_kind=CallerKind.AGENT,
        interaction_mode=InteractionMode.UNATTENDED,
        session_key="agent:main:t-ask-unattended",
    )
    handler = build_tool_handler(get_default_registry(), ctx)

    result = await handler(_call())

    assert result.is_error is True
    assert result.terminates_turn is False
    assert "unattended" in result.content


def _registered_ask_user():
    rt = get_default_registry().get("ask_user")
    assert rt is not None
    return rt


def test_ask_user_hidden_from_cron_and_subagent_surfaces() -> None:
    rt = _registered_ask_user()
    cron_ctx = effective_tool_context(session_key="cron:job-1", caller_kind=CallerKind.CRON)
    subagent_ctx = effective_tool_context(
        session_key="subagent:main:x", caller_kind=CallerKind.SUBAGENT
    )
    assert is_tool_visible(rt, cron_ctx) is False
    assert is_tool_visible(rt, subagent_ctx) is False


def test_ask_user_hidden_when_interactive_surface_is_unattended() -> None:
    rt = _registered_ask_user()
    ctx = effective_tool_context(
        session_key="agent:main:t-ask-vis",
        caller_kind=CallerKind.AGENT,
        interaction_mode=InteractionMode.UNATTENDED,
    )
    assert is_tool_visible(rt, ctx) is False


def test_ask_user_visible_on_interactive_agent_surface() -> None:
    rt = _registered_ask_user()
    ctx = effective_tool_context(
        session_key="agent:main:t-ask-vis2",
        caller_kind=CallerKind.AGENT,
        interaction_mode=InteractionMode.INTERACTIVE,
    )
    assert is_tool_visible(rt, ctx) is True
