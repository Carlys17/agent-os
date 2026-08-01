from __future__ import annotations

from agentos.gateway.config import AgentEntryConfig, GatewayConfig
from agentos.gateway.routing import build_cron_route_envelope, tool_context_from_envelope
from agentos.scheduler.types import CronJob
from agentos.tools.policy import apply_tool_policy_from_config
from agentos.tools.types import (
    CRON_AGENT_ALLOW,
    CRON_AGENT_DENY,
    SUBAGENT_TOOL_DENY,
    CallerKind,
    InteractionMode,
    ToolContext,
)


def _cron_ctx(tool_policy: dict | None = None, **kwargs):
    job = CronJob(id="elev", name="Elevated", tool_policy=tool_policy or {})
    envelope = build_cron_route_envelope(
        job,
        session_key="cron:elev:run:1",
        agent_id="main",
    )
    return tool_context_from_envelope(envelope, **kwargs)


def test_tool_policy_reads_direct_gateway_agents_list() -> None:
    cfg = GatewayConfig(
        agents=[
            AgentEntryConfig(
                id="ops",
                tools={"profile": "minimal", "also_allow": ["memory_search"]},
            )
        ]
    )
    ctx = ToolContext(agent_id="ops")

    result = apply_tool_policy_from_config(
        ctx,
        available_tools=["session_status", "memory_search", "exec_command"],
        config=cfg,
    )

    assert result.allowed_tools == {"session_status", "memory_search"}


def test_cron_route_tool_policy_can_only_narrow_or_extend_cron_baseline() -> None:
    job = CronJob(
        id="policy",
        name="Policy",
        tool_policy={
            "profile": "minimal",
            "also_allow": ["memory_search", "exec_command"],
            "deny": ["web_fetch"],
        },
    )

    envelope = build_cron_route_envelope(
        job,
        session_key="cron:policy:run:1",
        agent_id="main",
    )
    result = tool_context_from_envelope(envelope)

    assert envelope.metadata["tool_policy"] == job.tool_policy
    assert result.caller_kind is CallerKind.CRON
    assert result.allowed_tools == {"session_status"}
    assert "web_fetch" in result.denied_tools
    assert "exec_command" in result.denied_tools


def test_cron_route_has_no_role_override() -> None:
    job = CronJob(
        id="role-free-policy",
        name="Role-free Policy",
        tool_policy={
            "profile": "minimal",
            "also_allow": ["memory_search", "exec_command"],
            "deny": ["web_fetch"],
        },
    )

    envelope = build_cron_route_envelope(
        job,
        session_key="cron:role-free-policy:run:1",
        agent_id="main",
    )
    result = tool_context_from_envelope(envelope)

    assert result.caller_kind is CallerKind.CRON
    assert result.allowed_tools == {"session_status"}
    assert result.tool_policy == job.tool_policy
    assert "exec_command" in result.denied_tools


def test_cron_route_elevated_job_gains_exec_and_write_tools() -> None:
    result = _cron_ctx({"elevated": "bypass"})

    assert result.elevated == "bypass"
    assert {"exec_command", "write_file", "edit_file"} <= (result.allowed_tools or set())
    # Elevation widens the tool surface; it does not make the turn interactive.
    assert result.interaction_mode is InteractionMode.UNATTENDED
    assert result.caller_kind is CallerKind.CRON


def test_cron_route_elevated_keeps_the_hard_deny_floor() -> None:
    result = _cron_ctx({"elevated": "bypass"})

    floor = {
        "cron",
        "message",
        "agents_list",
        "subagents",
        "background_process",
        "execute_code",
        "apply_patch",
        "git_commit",
    }
    assert floor <= result.denied_tools
    assert not (floor & (result.allowed_tools or set()))


def test_cron_route_elevated_policy_can_still_only_narrow() -> None:
    result = _cron_ctx({"elevated": "bypass", "deny": ["write_file"]})

    assert "write_file" in result.denied_tools
    assert "write_file" not in (result.allowed_tools or set())
    assert "exec_command" in (result.allowed_tools or set())


def test_cron_route_elevated_full_is_honoured_verbatim() -> None:
    assert _cron_ctx({"elevated": "full"}).elevated == "full"


def test_cron_route_ignores_an_unparseable_persisted_elevation() -> None:
    """A hand-edited or pre-feature row must not be able to break routing."""

    result = _cron_ctx({"elevated": "sudo-please"})

    assert result.elevated is None
    assert result.allowed_tools == set(CRON_AGENT_ALLOW)


def test_default_cron_route_is_unchanged_by_the_elevation_feature() -> None:
    result = _cron_ctx()

    assert result.allowed_tools == set(CRON_AGENT_ALLOW)
    assert result.denied_tools == set(CRON_AGENT_DENY)
    assert result.elevated is None


def test_global_default_elevated_still_cannot_reach_cron() -> None:
    """permissions.default_mode must never elevate a cron turn on its own."""

    result = _cron_ctx(default_elevated="full")

    assert result.elevated is None
    assert result.allowed_tools == set(CRON_AGENT_ALLOW)
    assert "exec_command" in result.denied_tools


def test_policy_deny_lists_do_not_reference_removed_agent_wrapper_tools() -> None:
    assert "spawn_subagent" not in SUBAGENT_TOOL_DENY
    assert "send_message" not in SUBAGENT_TOOL_DENY
    assert "spawn_subagent" not in CRON_AGENT_DENY
    assert "send_message" not in CRON_AGENT_DENY


def test_messaging_group_does_not_revive_removed_agent_send_wrapper() -> None:
    cfg = GatewayConfig(tools={"profile": "messaging"})
    ctx = ToolContext(agent_id="main")

    result = apply_tool_policy_from_config(
        ctx,
        available_tools=["message", "send_message", "sessions_send", "session_status"],
        config=cfg,
    )

    assert result.allowed_tools is not None
    assert "message" in result.allowed_tools
    assert "sessions_send" in result.allowed_tools
    assert "send_message" not in result.allowed_tools


def test_channel_media_group_expands_safe_file_authoring_tools() -> None:
    cfg = {
        "channels": {
            "feishu": {
                "groups": {
                    "oc_demo": {
                        "tools": {"profile": "minimal", "also_allow": ["channel:media"]}
                    }
                }
            }
        }
    }
    ctx = ToolContext(
                caller_kind=CallerKind.CHANNEL,
        channel_kind="feishu",
        channel_id="oc_demo",
        sender_id="ou_user",
    )

    result = apply_tool_policy_from_config(
        ctx,
        available_tools=[
            "session_status",
            "create_csv",
            "create_xlsx",
            "create_pptx",
            "create_pdf_report",
            "execute_code",
        ],
        config=cfg,
    )

    assert result.allowed_tools == {
        "session_status",
        "create_csv",
        "create_xlsx",
        "create_pptx",
        "create_pdf_report",
    }


def test_channel_perm_group_is_empty_until_explicit_tools_exist() -> None:
    cfg = {
        "channels": {
            "feishu": {
                "groups": {
                    "oc_demo": {
                        "tools": {"profile": "minimal", "also_allow": ["channel:perm"]}
                    }
                }
            }
        }
    }
    ctx = ToolContext(
                caller_kind=CallerKind.CHANNEL,
        channel_kind="feishu",
        channel_id="oc_demo",
        sender_id="ou_user",
    )

    result = apply_tool_policy_from_config(
        ctx,
        available_tools=["session_status", "feishu_permission_grant"],
        config=cfg,
    )

    assert result.allowed_tools == {"session_status"}


def test_channel_sender_policy_can_enable_drive_for_one_sender() -> None:
    cfg = {
        "channels": {
            "slack": {
                "groups": {
                    "oc_demo": {
                        "tools": {
                            "profile": "minimal",
                            "toolsBySender": {
                                "id:ou_allowed": {"also_allow": ["channel:drive"]}
                            },
                        }
                    }
                }
            }
        }
    }
    available = ["session_status", "create_pptx", "create_csv"]

    allowed = apply_tool_policy_from_config(
        ToolContext(
                        caller_kind=CallerKind.CHANNEL,
            channel_kind="slack",
            channel_id="oc_demo",
            sender_id="ou_allowed",
        ),
        available_tools=available,
        config=cfg,
    )
    other = apply_tool_policy_from_config(
        ToolContext(
                        caller_kind=CallerKind.CHANNEL,
            channel_kind="slack",
            channel_id="oc_demo",
            sender_id="ou_other",
        ),
        available_tools=available,
        config=cfg,
    )

    assert allowed.allowed_tools == {
        "session_status",
        "create_pptx",
        "create_csv",
    }
    assert other.allowed_tools == {"session_status"}
