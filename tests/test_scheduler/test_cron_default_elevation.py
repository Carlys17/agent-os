from __future__ import annotations

from pathlib import Path

from agentos.gateway.config import PermissionsConfig
from agentos.gateway.routing import build_cron_route_envelope, tool_context_from_envelope
from agentos.gateway.rpc_cron import _job_to_wire
from agentos.scheduler.ops import SchedulerOps
from agentos.scheduler.payloads import make_agent_turn_payload
from agentos.scheduler.persistence import JobStore
from agentos.scheduler.types import CronJob, ScheduleKind, SessionTarget


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


def test_permissions_config_round_trip() -> None:
    config = PermissionsConfig(cron_default_mode="off")
    data = config.model_dump()
    assert data["cron_default_mode"] == "off"
    loaded = PermissionsConfig(**data)
    assert loaded.cron_default_mode == "off"


async def test_cron_write_path_explicit_off_override(tmp_path: Path) -> None:
    store = JobStore(str(tmp_path / "cron.db"))
    await store.open()
    ops = SchedulerOps(store)
    try:
        # Create a job with elevated=False on the real write path
        job = await ops.add(
            name="optout-job",
            handler_key="agent_run",
            payload=make_agent_turn_payload("ping"),
            session_target=SessionTarget.ISOLATED,
            schedule_kind=ScheduleKind.CRON,
            schedule_value="*/5 * * * *",
            tool_policy={"elevated": False},
        )
        assert job.tool_policy == {"elevated": "off"}

        # Loaded job still carries elevated="off"
        loaded = await store.get(job.id)
        assert loaded is not None
        assert loaded.tool_policy == {"elevated": "off"}

        # Routing with bypass default still keeps the explicit override off
        envelope = build_cron_route_envelope(loaded, session_key="cron:run:1", agent_id="main")
        result = tool_context_from_envelope(envelope, cron_default_elevated="bypass")
        assert result.elevated is None
    finally:
        await store.close()


async def test_cron_list_wire_surfacing(tmp_path: Path) -> None:
    store = JobStore(str(tmp_path / "cron.db"))
    await store.open()
    ops = SchedulerOps(store)
    try:
        # Create one default job and one explicit opt-out job
        job_default = await ops.add(
            name="default-job",
            handler_key="agent_run",
            payload=make_agent_turn_payload("ping"),
            session_target=SessionTarget.ISOLATED,
            schedule_kind=ScheduleKind.CRON,
            schedule_value="*/5 * * * *",
        )
        job_off = await ops.add(
            name="off-job",
            handler_key="agent_run",
            payload=make_agent_turn_payload("ping"),
            session_target=SessionTarget.ISOLATED,
            schedule_kind=ScheduleKind.CRON,
            schedule_value="*/5 * * * *",
            tool_policy={"elevated": "off"},
        )

        from types import SimpleNamespace

        fake_config = SimpleNamespace(permissions=SimpleNamespace(cron_default_mode="bypass"))

        # Wire mapping surfaces effectiveElevated properly
        wire_default = _job_to_wire(job_default, config=fake_config)
        assert wire_default["effectiveElevated"] == "bypass"

        wire_off = _job_to_wire(job_off, config=fake_config)
        assert wire_off["effectiveElevated"] is None
    finally:
        await store.close()
