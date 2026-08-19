"""Plan-mode enforcement in the gateway tool-context builder + RPC surface."""

from __future__ import annotations

import pytest

from agentos.channels.types import IncomingMessage
from agentos.gateway.access import CONTROL_AND_CHANNEL, CONTROL_ONLY
from agentos.gateway.config import GatewayConfig
from agentos.gateway.routing import (
    build_channel_route_envelope,
    build_cron_route_envelope,
    build_web_route_envelope,
    tool_context_from_envelope,
)
from agentos.gateway.rpc import RpcContext, get_dispatcher
from agentos.plan_mode import (
    PLAN_MODE_TOOL_ALLOW,
    get_plan_mode_store,
    reset_plan_mode_store,
)


@pytest.fixture(autouse=True)
def _fresh_store() -> None:
    reset_plan_mode_store()
    yield
    reset_plan_mode_store()


class TestRoutingEnforcement:
    def test_web_turn_gets_the_plan_allowlist_when_mode_is_on(self) -> None:
        key = "agent:main:web-plan"
        get_plan_mode_store().enable(key)
        ctx = tool_context_from_envelope(build_web_route_envelope(session_key=key))
        assert ctx.allowed_tools == set(PLAN_MODE_TOOL_ALLOW)
        assert "write_file" not in ctx.allowed_tools
        assert "exit_plan_mode" in ctx.allowed_tools

    def test_web_turn_is_unrestricted_when_mode_is_off(self) -> None:
        ctx = tool_context_from_envelope(
            build_web_route_envelope(session_key="agent:main:web-noplan")
        )
        assert ctx.allowed_tools is None

    def test_channel_turn_gets_the_allowlist_despite_unattended_mark(self) -> None:
        key = "telegram:dm:u1"
        get_plan_mode_store().enable(key)
        msg = IncomingMessage(sender_id="u1", channel_id="c1", content="hi")
        ctx = tool_context_from_envelope(
            build_channel_route_envelope(msg, session_key=key, session_prefix="telegram")
        )
        assert ctx.allowed_tools == set(PLAN_MODE_TOOL_ALLOW)

    def test_cron_surface_is_never_narrowed_by_plan_mode(self) -> None:
        from types import SimpleNamespace

        key = "cron:job-1"
        get_plan_mode_store().enable(key)
        job = SimpleNamespace(id="job-1", name="demo")
        ctx = tool_context_from_envelope(build_cron_route_envelope(job, session_key=key))
        # Cron keeps its own allowlist; plan mode must not intersect it.
        assert "exit_plan_mode" not in (ctx.allowed_tools or set())


class TestPlanRpc:
    def test_audiences(self) -> None:
        set_entry = get_dispatcher().get_entry("plan.mode.set")
        get_entry = get_dispatcher().get_entry("plan.mode.get")
        assert set_entry is not None and set_entry.audiences == CONTROL_AND_CHANNEL
        assert get_entry is not None and get_entry.audiences == CONTROL_ONLY

    @pytest.mark.asyncio
    async def test_set_and_get_roundtrip(self) -> None:
        ctx = RpcContext(conn_id="test", config=GatewayConfig())
        key = "agent:main:rpc-plan"

        on = await get_dispatcher().dispatch("r1", "plan.mode.set", {"key": key, "mode": "on"}, ctx)
        assert on.ok is True and on.payload["planMode"] is True
        assert get_plan_mode_store().is_enabled(key) is True

        got = await get_dispatcher().dispatch("r2", "plan.mode.get", {"key": key}, ctx)
        assert got.ok is True and got.payload["planMode"] is True

        off = await get_dispatcher().dispatch(
            "r3", "plan.mode.set", {"key": key, "mode": "off"}, ctx
        )
        assert off.ok is True and off.payload["planMode"] is False
        assert get_plan_mode_store().is_enabled(key) is False

    @pytest.mark.asyncio
    async def test_set_rejects_bad_params(self) -> None:
        ctx = RpcContext(conn_id="test", config=GatewayConfig())
        bad_mode = await get_dispatcher().dispatch(
            "r4", "plan.mode.set", {"key": "agent:main:x", "mode": "maybe"}, ctx
        )
        assert bad_mode.ok is False
        no_key = await get_dispatcher().dispatch("r5", "plan.mode.set", {"mode": "on"}, ctx)
        assert no_key.ok is False
