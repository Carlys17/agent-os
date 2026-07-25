from __future__ import annotations

from types import SimpleNamespace

from agentos.channels.types import IncomingMessage
from agentos.gateway.routing import (
    build_channel_route_envelope,
    build_cli_route_envelope,
    build_cron_route_envelope,
    build_subagent_route_envelope,
    build_web_route_envelope,
    tool_context_from_envelope,
)
from agentos.scheduler.handlers import _build_cron_tool_context
from agentos.scheduler.types import CronJob, SessionTarget
from agentos.tools.policy import ToolSurfaceCapabilities, resolve_runtime_tool_surface
from agentos.tools.types import CallerKind, InteractionMode


def test_route_envelopes_assign_expected_interaction_modes() -> None:
    channel_msg = IncomingMessage(sender_id="u1", channel_id="c1", content="hi")
    cron_job = SimpleNamespace(id="job-1", name="demo")

    cases = [
        (
            build_cli_route_envelope(session_key="agent:main:cli"),
            CallerKind.CLI,
            InteractionMode.INTERACTIVE,
        ),
        (
            build_cli_route_envelope(
                session_key="agent:main:auto",
                interaction_mode=InteractionMode.UNATTENDED,
            ),
            CallerKind.CLI,
            InteractionMode.UNATTENDED,
        ),
        (
            build_web_route_envelope(session_key="agent:main:web"),
            CallerKind.WEB,
            InteractionMode.INTERACTIVE,
        ),
        (
            build_channel_route_envelope(
                channel_msg,
                session_key="telegram:dm:u1",
                session_prefix="telegram",
            ),
            CallerKind.CHANNEL,
            InteractionMode.UNATTENDED,
        ),
        (
            build_cron_route_envelope(cron_job, session_key="cron:job-1"),
            CallerKind.CRON,
            InteractionMode.UNATTENDED,
        ),
        (
            build_subagent_route_envelope(
                session_key="subagent:parent:child",
                parent_session_key="agent:main:parent",
            ),
            CallerKind.SUBAGENT,
            InteractionMode.UNATTENDED,
        ),
    ]

    for envelope, expected_kind, expected_mode in cases:
        ctx = tool_context_from_envelope(envelope)
        assert ctx.caller_kind is expected_kind
        assert ctx.interaction_mode is expected_mode


def test_unattended_cli_denies_runtime_dependent_tools_but_keeps_session_reads() -> None:
    envelope = build_cli_route_envelope(
        session_key="agent:main:auto",
        interaction_mode=InteractionMode.UNATTENDED,
    )

    ctx = resolve_runtime_tool_surface(
        tool_context_from_envelope(envelope),
        capabilities=ToolSurfaceCapabilities(session_manager=True),
    )

    assert "sessions_spawn" in ctx.denied_tools
    assert "gateway" in ctx.denied_tools
    assert "sessions_list" not in ctx.denied_tools
    assert "sessions_history" not in ctx.denied_tools
    assert "session_status" not in ctx.denied_tools


def test_default_elevated_mode_applies_only_to_interactive_control_context() -> None:
    interactive = build_cli_route_envelope(session_key="agent:main:cli")
    unattended = build_cli_route_envelope(
        session_key="agent:main:auto",
        interaction_mode=InteractionMode.UNATTENDED,
    )
    channel = build_channel_route_envelope(
        IncomingMessage(sender_id="u1", channel_id="c1", content="hi"),
        session_key="agent:main:telegram:dm:u1",
        session_prefix="telegram",
    )

    control_ctx = tool_context_from_envelope(
        interactive,
        default_elevated="bypass",
    )
    unattended_ctx = tool_context_from_envelope(
        unattended,
        default_elevated="bypass",
    )
    channel_ctx = tool_context_from_envelope(channel, default_elevated="bypass")

    assert control_ctx.elevated == "bypass"
    assert unattended_ctx.elevated is None
    assert channel_ctx.elevated is None


def test_cron_never_inherits_default_elevated_mode() -> None:
    job = CronJob(
        id="job",
        name="job",
        session_target=SessionTarget.ISOLATED,
    )
    ctx = _build_cron_tool_context(
        "agent",
        job,
        default_elevated="full",
    )

    assert ctx.elevated is None


def test_cron_route_always_keeps_restricted_tool_boundary() -> None:
    cron_job = SimpleNamespace(id="job", name="job")
    envelope = build_cron_route_envelope(cron_job, session_key="cron:job")

    ctx = tool_context_from_envelope(envelope)

    assert ctx.caller_kind is CallerKind.CRON
    assert ctx.allowed_tools is not None
    assert "exec_command" not in ctx.allowed_tools
    assert "exec_command" in ctx.denied_tools
