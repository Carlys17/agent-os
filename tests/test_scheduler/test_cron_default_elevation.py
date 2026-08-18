from __future__ import annotations

from agentos.gateway.routing import build_cron_route_envelope, tool_context_from_envelope
from agentos.scheduler.types import CronJob


def _cron_ctx(handler_key: str, tool_policy: dict | None = None, **kwargs):
    job = CronJob(
        id="elev",
        name="Elevated",
        handler_key=handler_key,
        tool_policy=tool_policy if tool_policy is not None else {},
    )
    envelope = build_cron_route_envelope(
        job,
        session_key="cron:elev:run:1",
        agent_id="main",
    )
    return tool_context_from_envelope(envelope, **kwargs)


def test_cron_agent_run_elevated_by_default() -> None:
    # 1. agent_run job with no explicit tool_policy.elevated runs elevated by default (bypass)
    result = _cron_ctx("agent_run", cron_default_elevated="bypass")
    assert result.elevated == "bypass"
    assert "exec_command" in (result.allowed_tools or set())


def test_cron_other_jobs_not_elevated_by_default() -> None:
    # 2. reminder, system_event and script_run jobs are unaffected and still reject elevation
    for handler in ("system_event", "static_message", "script_run"):
        result = _cron_ctx(handler, cron_default_elevated="bypass")
        assert result.elevated is None
        assert "exec_command" not in (result.allowed_tools or set())


def test_cron_explicit_off_override() -> None:
    # 3. Explicitly setting elevated: "off" on an agent_run job overrides
    # the default and does not run elevated
    result = _cron_ctx("agent_run", {"elevated": "off"}, cron_default_elevated="bypass")
    assert result.elevated is None


def test_cron_explicit_full_override() -> None:
    # 4. Explicitly setting elevated: "full" overrides the bypass default
    result = _cron_ctx("agent_run", {"elevated": "full"}, cron_default_elevated="bypass")
    assert result.elevated == "full"


def test_cron_default_mode_off() -> None:
    # 5. Setting cron_default_mode: "off" globally restores the previous
    # behavior exactly (unelevated by default)
    result = _cron_ctx("agent_run", cron_default_elevated=None)
    assert result.elevated is None


def test_cron_default_mode_on_does_not_leak_into_cron() -> None:
    # 6. Interactive setting default_mode: "on" does not leak into a cron turn
    result = _cron_ctx("agent_run", default_elevated="on", cron_default_elevated=None)
    assert result.elevated is None
