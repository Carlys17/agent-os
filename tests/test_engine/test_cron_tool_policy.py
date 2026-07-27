from __future__ import annotations

from agentos.engine.runtime import TurnRunner
from agentos.tools.registry import ToolRegistry
from agentos.tools.types import (
    CRON_AGENT_ALLOW,
    CRON_AGENT_DENY,
    CallerKind,
    InteractionMode,
    ToolContext,
    ToolSpec,
)


async def _handler() -> str:
    return "ok"


def _spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description=f"{name} tool", parameters={})


def test_cron_tool_policy_uses_runtime_registry_names_and_respects_hard_denies() -> None:
    registry = ToolRegistry()
    for name in ("session_status", "read_file", "exec_command", "web_fetch"):
        registry.register(_spec(name), _handler)
    runner = TurnRunner(
        provider_selector=None,
        tool_registry=registry,
        session_manager=object(),
        config=object(),
    )
    ctx = ToolContext(
        caller_kind=CallerKind.CRON,
        interaction_mode=InteractionMode.UNATTENDED,
        session_key="cron:job:run:1",
        allowed_tools=set(CRON_AGENT_ALLOW),
        denied_tools=set(CRON_AGENT_DENY),
        tool_policy={
            "profile": "minimal",
            "also_allow": ["read_file", "exec_command"],
            "deny": ["web_fetch"],
        },
    )

    tool_defs, _handler_fn = runner._build_tools(ctx)
    names = {tool.name for tool in tool_defs}

    assert "session_status" in names
    assert "read_file" in names
    assert "exec_command" not in names
    assert "web_fetch" not in names
