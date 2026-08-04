"""A cron job's tool profile is validated where it is written.

``profile`` used to be the one ``tool_policy`` key nothing checked: the wire
boundary stringified it, ops passed it through, and the store accepted it. The
name was resolved for the first time inside the *run*, where
``profile_allowlist`` raises on an unknown one — so a typo produced a job that
was created successfully and then failed every single firing, forever, with an
error the creator never saw.

``elevated`` already had the right shape and these pin the same one onto
``profile``: reject at both write boundaries, naming the valid values, and stay
tolerant on the read path so a row written before this validation existed can
still be listed and deleted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.gateway.rpc_cron import _tool_policy_from_params, _tool_policy_to_wire
from agentos.scheduler.ops import SchedulerOps
from agentos.scheduler.payloads import make_agent_turn_payload
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


async def test_ops_add_rejects_an_unknown_tool_profile(tmp_path: Path) -> None:
    """The exact value that produced a job failing every five minutes forever."""
    store, ops = await _open_ops(tmp_path)
    try:
        with pytest.raises(ValueError, match="unknown cron tool profile: 'default'"):
            await _add(ops, tool_policy={"profile": "default", "elevated": "bypass"})
    finally:
        await store.close()


async def test_the_rejection_names_the_profiles_that_do_exist(tmp_path: Path) -> None:
    """A caller that guessed a name cannot guess a second time from 'no'."""
    store, ops = await _open_ops(tmp_path)
    try:
        with pytest.raises(ValueError) as caught:
            await _add(ops, tool_policy={"profile": "readonly"})
        message = str(caught.value)
        for known in ("coding", "full", "memory_only", "messaging", "minimal"):
            assert known in message
    finally:
        await store.close()


async def test_ops_add_accepts_a_known_profile_and_canonicalises_it(tmp_path: Path) -> None:
    store, ops = await _open_ops(tmp_path)
    try:
        job = await _add(ops, tool_policy={"profile": "  Coding  "})
        assert job.tool_policy == {"profile": "coding"}
    finally:
        await store.close()


async def test_ops_add_keeps_an_empty_profile_meaning_no_profile(tmp_path: Path) -> None:
    """``None`` is how every other layer spells "inherit"; it must stay legal."""
    store, ops = await _open_ops(tmp_path)
    try:
        job = await _add(ops, tool_policy={"profile": None, "deny": ["web_fetch"]})
        assert job.tool_policy == {"profile": None, "deny": ["web_fetch"]}
    finally:
        await store.close()


async def test_ops_update_rejects_an_unknown_profile(tmp_path: Path) -> None:
    store, ops = await _open_ops(tmp_path)
    try:
        job = await _add(ops, tool_policy={"profile": "coding"})
        with pytest.raises(ValueError, match="unknown cron tool profile"):
            await ops.update(job.id, tool_policy={"profile": "default"})
    finally:
        await store.close()


def test_the_rpc_write_path_rejects_an_unknown_profile() -> None:
    with pytest.raises(ValueError, match="unknown cron tool profile: 'default'"):
        _tool_policy_from_params({"toolPolicy": {"profile": "default"}})


def test_the_rpc_write_path_accepts_a_known_profile() -> None:
    assert _tool_policy_from_params({"toolPolicy": {"profile": "minimal"}}) == {
        "profile": "minimal"
    }


def test_listing_a_job_stored_before_this_validation_does_not_raise() -> None:
    """The read path stays total.

    Rows carrying an unknown profile already exist — that is the whole reason
    this validation was added. If rendering one raised, ``cron list`` would die
    on the bad job and the operator could not even find the id to delete it.
    """
    wire = _tool_policy_to_wire({"profile": "default", "elevated": "bypass"})
    assert wire["profile"] == "default"
    assert wire["elevated"] == "bypass"
