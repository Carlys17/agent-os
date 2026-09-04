"""Regression tests for per-session lock eviction in TaskRuntime (gh-1040).

Acceptance criteria:

AC-C3-1 (bounded, revised for gh-1040): after a task reaches terminal state
and the session lock is quiescent, the ``_session_locks`` and
``_session_execution_locks`` entries are evicted so the registries do not
grow with session count on long-lived gateways.

AC-C3-1b (safe eviction): while another task of the same session is queued
behind the lock, the entry is retained and the lock object identity is
preserved, so the queued task cannot be handed a fresh lock by a concurrent
``setdefault`` (the split-brain window observed in #1041's unconditional
``pop``).

AC-C3-2 (unchanged from upstream): rapid enqueue -> terminal -> re-enqueue
for the same session_key never runs two of the session's turns concurrently.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentos.gateway.routing import RouteEnvelope, SourceKind
from agentos.gateway.task_runtime import TaskRuntime
from agentos.session.models import AgentTaskRecord


def _make_storage() -> Any:
    storage = MagicMock()
    db: dict[str, AgentTaskRecord] = {}

    async def create(record: AgentTaskRecord) -> None:
        db[record.task_id] = record

    async def update(task_id: str, **kw: Any) -> None:
        rec = db.get(task_id)
        if rec is None:
            return
        for k, v in kw.items():
            if hasattr(rec, k):
                object.__setattr__(rec, k, v)

    async def get(task_id: str) -> AgentTaskRecord | None:
        return db.get(task_id)

    async def list_tasks(**_: Any) -> list[AgentTaskRecord]:
        return list(db.values())

    storage.create_agent_task = create
    storage.update_agent_task = update
    storage.get_agent_task = get
    storage.list_agent_tasks = list_tasks
    return storage


def _make_envelope(session_key: str) -> RouteEnvelope:
    return RouteEnvelope(
        source_kind=SourceKind.WEB,
        source_name="test",
        agent_id="agent-1",
        session_key=session_key,
        input_provenance={"kind": "test"},
    )


# ---------------------------------------------------------------------------
# AC-C3-1: registries stay bounded after terminal (gh-1040 leak)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_locks_evicted_after_terminal() -> None:
    """After terminal, both per-session lock registries drop the entry."""
    session_key = "agent-1::sess-c3"
    env = _make_envelope(session_key)

    async def _instant(_run: Any) -> None:
        pass

    rt = TaskRuntime(
        storage=_make_storage(),
        turn_handler=_instant,
        max_concurrency=4,
    )
    handle = await rt.enqueue(env, "msg")
    await rt.wait(handle.task_id, timeout=5.0)

    assert session_key not in rt._session_locks, (
        "_session_locks should evict the entry after terminal (gh-1040)"
    )
    assert session_key not in rt._session_execution_locks, (
        "_session_execution_locks should evict the entry after terminal (gh-1040)"
    )


@pytest.mark.asyncio
async def test_session_locks_bounded_across_many_sessions() -> None:
    """500 sessions through the runtime must not leave 500 registry entries."""
    sessions = 200

    async def _instant(_run: Any) -> None:
        pass

    rt = TaskRuntime(
        storage=_make_storage(),
        turn_handler=_instant,
        max_concurrency=4,
    )
    for i in range(sessions):
        env = _make_envelope(f"agent-1::sess-{i}")
        handle = await rt.enqueue(env, "msg")
        await rt.wait(handle.task_id, timeout=5.0)

    assert len(rt._session_locks) < sessions / 10, (
        f"_session_locks grew to {len(rt._session_locks)} after {sessions} sessions"
    )


# ---------------------------------------------------------------------------
# AC-C3-1b: eviction must never create a split-brain window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_entry_retained_while_waiter_queued() -> None:
    """B queued behind A: the entry must survive A's terminal state.

    Fails against unconditional ``pop`` (#1041 head): there, C enqueued while
    B runs gets a brand-new lock via ``setdefault`` and runs concurrently.
    """
    session_key = "agent-1::sess-c3b"
    env = _make_envelope(session_key)
    mid_b = asyncio.Event()

    async def _handler(run: Any) -> None:
        if run.message == "B":
            mid_b.set()
            await asyncio.sleep(0.25)
        else:
            await asyncio.sleep(0.05)

    rt = TaskRuntime(
        storage=_make_storage(),
        turn_handler=_handler,
        max_concurrency=4,
        max_pending_per_session=64,
    )

    ha = await rt.enqueue(env, "A")
    await asyncio.sleep(0.02)  # A mid-turn; B queues behind the lock
    hb = await rt.enqueue(env, "B")
    await rt.wait(ha.task_id, timeout=5.0)

    # A terminal, B queued or running: entry retained, identity preserved.
    assert session_key in rt._session_locks
    assert session_key in rt._session_execution_locks
    assert not mid_b.is_set()

    await rt.wait(hb.task_id, timeout=5.0)
    await asyncio.sleep(0.02)  # let B's finally run

    # B done, registry quiescent again: entry evicted.
    assert session_key not in rt._session_locks
    assert session_key not in rt._session_execution_locks


@pytest.mark.asyncio
async def test_no_split_brain_when_message_arrives_mid_turn() -> None:
    """The #1041 failure mode as a test: C arriving mid-turn of B stays serial.

    Ordinary chat pattern: A runs, B queued behind A, C sent while B runs.
    With an unconditional pop, C mints a new lock and overlaps B.
    """
    session_key = "agent-1::sess-c3c"
    env = _make_envelope(session_key)

    running: set[str] = set()
    peak = 0
    b_running = asyncio.Event()

    async def _handler(run: Any) -> None:
        nonlocal peak
        label = run.message
        running.add(label)
        peak = max(peak, len(running))
        if label == "B":
            b_running.set()
            await asyncio.sleep(0.25)
        else:
            await asyncio.sleep(0.05)
        running.discard(label)

    rt = TaskRuntime(
        storage=_make_storage(),
        turn_handler=_handler,
        max_concurrency=4,
        max_pending_per_session=64,
    )

    ha = await rt.enqueue(env, "A")
    await asyncio.sleep(0.02)
    hb = await rt.enqueue(env, "B")  # queued behind A on the same lock
    await rt.wait(ha.task_id, timeout=5.0)
    async with asyncio.timeout(5.0):
        await b_running.wait()  # B now holds the pre-terminal lock object
    hc = await rt.enqueue(env, "C")  # must not mint a fresh lock and overlap B

    await asyncio.gather(
        rt.wait(hb.task_id, timeout=5.0),
        rt.wait(hc.task_id, timeout=5.0),
    )

    assert peak == 1, f"Split-brain: two turns of one session ran concurrently (max={peak})"


# ---------------------------------------------------------------------------
# AC-C3-2 (unchanged): rapid enqueue -> terminal -> re-enqueue stays serial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rapid_enqueue_after_terminal_no_split_brain() -> None:
    """Loop 100 times: enqueue -> wait for terminal -> immediately re-enqueue.

    At no point should two tasks for the same session run concurrently.
    max_concurrent_per_session must always be 1.
    """
    iterations = 100
    session_key = "agent-1::sess-c3-rapid"
    env = _make_envelope(session_key)

    concurrent_count = 0
    max_concurrent = 0
    count_lock = asyncio.Lock()

    async def _handler(_run: Any) -> None:
        nonlocal concurrent_count, max_concurrent
        async with count_lock:
            concurrent_count += 1
            if concurrent_count > max_concurrent:
                max_concurrent = concurrent_count
        # Small yield to allow other tasks to slip in if the lock is broken.
        await asyncio.sleep(0)
        async with count_lock:
            concurrent_count -= 1

    rt = TaskRuntime(
        storage=_make_storage(),
        turn_handler=_handler,
        max_concurrency=4,
        max_pending_per_session=None,
    )

    for _ in range(iterations):
        handle = await rt.enqueue(env, "msg")
        await rt.wait(handle.task_id, timeout=5.0)
        # Yield to event loop so any in-flight concurrent task could manifest.
        await asyncio.sleep(0)

    assert max_concurrent == 1, (
        f"Split-brain detected: max concurrent tasks for same session = {max_concurrent} "
        f"(expected 1)"
    )
