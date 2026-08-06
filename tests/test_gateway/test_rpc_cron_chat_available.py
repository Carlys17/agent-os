"""A run's session key does not mean a chat transcript exists.

``_resolve_session_key`` mints ``cron:<job>:run:<hex>`` for every run and writes it
onto the run record, but only ``agent_run`` ever creates the session — and even
those are reaped after 24h. Run history used to offer a "→ Chat" button for all of
them, which landed on "Could not load chat history."

``cron.runs`` now probes the session store so the caller can tell the difference.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.gateway.rpc import RpcContext
from agentos.gateway.rpc_cron import _handle_cron_runs
from agentos.scheduler.types import JobExecution

SCRIPT_RUN = "cron:job-1:run:deadbeef"  # script job — session never created
AGENT_RUN = "cron:job-1:run:cafe1234"  # agent turn — session exists


class _FakeScheduler:
    def __init__(self, runs: list[JobExecution]) -> None:
        self._runs = runs

    async def get_runs(self, job_id: str, limit: int = 20) -> list[JobExecution]:
        return self._runs[:limit]


class _FakeSessionManager:
    """Only ``AGENT_RUN`` resolves, mirroring a store where the rest were reaped."""

    def __init__(self, *, live: set[str], explode: bool = False) -> None:
        self._live = live
        self._explode = explode
        self.lookups: list[str] = []

    async def get_session(self, session_key: str) -> Any:
        self.lookups.append(session_key)
        if self._explode:
            raise RuntimeError("session store unavailable")
        return object() if session_key in self._live else None


def _ctx(scheduler: Any, session_manager: Any = None) -> RpcContext:
    ctx = RpcContext(conn_id="test", session_manager=session_manager)
    ctx.cron_scheduler = scheduler  # type: ignore[attr-defined]
    return ctx


def _runs() -> list[JobExecution]:
    return [
        JobExecution(id="r1", job_id="job-1", success=True, session_key=AGENT_RUN),
        JobExecution(id="r2", job_id="job-1", success=True, session_key=SCRIPT_RUN),
        JobExecution(id="r3", job_id="job-1", success=True, session_key=None),
    ]


@pytest.mark.asyncio
async def test_chat_available_only_where_the_session_exists() -> None:
    mgr = _FakeSessionManager(live={AGENT_RUN})

    rows = await _handle_cron_runs({"id": "job-1"}, _ctx(_FakeScheduler(_runs()), mgr))

    assert [r["chatAvailable"] for r in rows] == [True, False, False]
    # The key is still sent — the caller needs it to build the URL.
    assert rows[1]["sessionKey"] == SCRIPT_RUN


@pytest.mark.asyncio
async def test_repeated_session_keys_are_probed_once() -> None:
    shared = "cron:job-1"
    runs = [JobExecution(id=f"r{i}", job_id="job-1", session_key=shared) for i in range(5)]
    mgr = _FakeSessionManager(live={shared})

    rows = await _handle_cron_runs({"id": "job-1"}, _ctx(_FakeScheduler(runs), mgr))

    assert all(r["chatAvailable"] for r in rows)
    assert mgr.lookups == [shared]


@pytest.mark.asyncio
async def test_no_session_manager_means_nothing_is_offered() -> None:
    rows = await _handle_cron_runs({"id": "job-1"}, _ctx(_FakeScheduler(_runs()), None))

    assert [r["chatAvailable"] for r in rows] == [False, False, False]


@pytest.mark.asyncio
async def test_a_failing_lookup_does_not_take_down_run_history() -> None:
    mgr = _FakeSessionManager(live={AGENT_RUN}, explode=True)

    rows = await _handle_cron_runs({"id": "job-1"}, _ctx(_FakeScheduler(_runs()), mgr))

    assert len(rows) == 3
    assert [r["chatAvailable"] for r in rows] == [False, False, False]
