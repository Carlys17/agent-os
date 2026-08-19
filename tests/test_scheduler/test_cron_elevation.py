"""Cron elevation is validated where it is written, not only on the wire.

The ``cron`` builtin tool hands its ``tool_policy`` argument straight to
``SchedulerOps.add``, so validating at the RPC boundary alone would leave that
path open. These pin the floor in ops, plus the persistence round trip that
lets the whole feature ship without a migration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.scheduler.ops import SchedulerOps
from agentos.scheduler.payloads import (
    make_agent_turn_payload,
    make_reminder_payload,
    make_system_event_payload,
)
from agentos.scheduler.persistence import JobStore
from agentos.scheduler.types import ScheduleKind, SessionTarget


async def _open_ops(tmp_path: Path) -> tuple[JobStore, SchedulerOps]:
    store = JobStore(str(tmp_path / "cron.db"))
    await store.open()
    return store, SchedulerOps(store)


async def _add(ops: SchedulerOps, **kwargs):
    defaults = {
        "name": "job",
        "handler_key": "agent_run",
        "payload": make_agent_turn_payload("ping"),
        "session_target": SessionTarget.ISOLATED,
        "schedule_kind": ScheduleKind.CRON,
        "schedule_value": "*/5 * * * *",
    }
    return await ops.add(**{**defaults, **kwargs})


async def test_ops_add_accepts_elevated_on_agent_run_job(tmp_path: Path) -> None:
    store, ops = await _open_ops(tmp_path)
    try:
        job = await _add(ops, tool_policy={"elevated": True})
        assert job.tool_policy == {"elevated": "bypass"}
    finally:
        await store.close()


async def test_ops_add_rejects_elevated_on_system_event_job(tmp_path: Path) -> None:
    """HeartbeatLoop builds its own read-only context and never reads the job's
    tool policy, so a system_event job would honour elevation on one path and
    silently drop it on the other."""
    store, ops = await _open_ops(tmp_path)
    try:
        with pytest.raises(ValueError, match="agent_turn"):
            await _add(
                ops,
                handler_key="system_event",
                payload=make_system_event_payload("wake"),
                session_target=SessionTarget.MAIN,
                tool_policy={"elevated": "bypass"},
            )
    finally:
        await store.close()


async def test_ops_add_rejects_elevated_on_reminder_job(tmp_path: Path) -> None:
    store, ops = await _open_ops(tmp_path)
    try:
        with pytest.raises(ValueError, match="agent_turn"):
            await _add(
                ops,
                handler_key="static_message",
                payload=make_reminder_payload("remember"),
                tool_policy={"elevated": "bypass"},
            )
    finally:
        await store.close()


async def test_ops_add_rejects_the_on_elevation_mode(tmp_path: Path) -> None:
    store, ops = await _open_ops(tmp_path)
    try:
        with pytest.raises(ValueError, match="bypass"):
            await _add(ops, tool_policy={"elevated": "on"})
    finally:
        await store.close()


async def test_ops_add_maps_a_falsy_elevation_key_to_off(tmp_path: Path) -> None:
    """An explicitly unelevated job stores the 'off' policy."""
    store, ops = await _open_ops(tmp_path)
    try:
        job = await _add(ops, tool_policy={"elevated": False})
        assert job.tool_policy == {"elevated": "off"}
    finally:
        await store.close()


async def test_ops_update_can_clear_elevation(tmp_path: Path) -> None:
    store, ops = await _open_ops(tmp_path)
    try:
        job = await _add(ops, tool_policy={"elevated": "bypass", "deny": ["web_fetch"]})
        updated = await ops.update(job.id, tool_policy={"deny": ["web_fetch"]})
        assert updated is not None
        assert updated.tool_policy == {"deny": ["web_fetch"]}
    finally:
        await store.close()


async def test_persisted_elevation_survives_a_store_round_trip(tmp_path: Path) -> None:
    """Elevation rides in the existing tool_policy_json column — no migration."""
    store, ops = await _open_ops(tmp_path)
    try:
        job = await _add(ops, tool_policy={"elevated": "full", "deny": ["web_fetch"]})
        loaded = await store.get(job.id)
    finally:
        await store.close()

    assert loaded is not None
    assert loaded.tool_policy == {"elevated": "full", "deny": ["web_fetch"]}
