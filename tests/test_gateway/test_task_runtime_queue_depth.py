"""Regression: agentos_queue_depth gauge is updated when tasks leave the pending queue."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog
import structlog.testing

from agentos.gateway.task_runtime import AgentTaskRecord, TaskRuntime
from agentos.gateway.routing import RouteEnvelope, SourceKind


@contextmanager
def _capture_metric_logs():
    old_config = structlog.get_config()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET))
    try:
        with structlog.testing.capture_logs() as captured:
            yield captured
    finally:
        structlog.configure(**old_config)


def _make_storage() -> Any:
    storage = MagicMock()
    task_db: dict[str, AgentTaskRecord] = {}

    async def create(record: AgentTaskRecord) -> None:
        task_db[record.task_id] = record

    async def update(task_id: str, **kwargs: Any) -> None:
        rec = task_db.get(task_id)
        if rec is None:
            return
        for k, v in kwargs.items():
            if hasattr(rec, k):
                object.__setattr__(rec, k, v)

    async def get(task_id: str) -> AgentTaskRecord | None:
        return task_db.get(task_id)

    async def list_tasks(**_: Any) -> list[AgentTaskRecord]:
        return list(task_db.values())

    storage.create_agent_task = create
    storage.update_agent_task = update
    storage.get_agent_task = get
    storage.list_agent_tasks = list_tasks
    return storage


def _make_runtime(
    turn_handler: Callable[..., Awaitable[Any]] | None = None,
    max_concurrency: int = 1,
) -> TaskRuntime:
    async def _default_handler(_run: Any) -> None:
        pass

    return TaskRuntime(
        storage=_make_storage(),
        turn_handler=turn_handler or _default_handler,
        max_concurrency=max_concurrency,
    )


def _env(session: str) -> RouteEnvelope:
    return RouteEnvelope(
        source_kind=SourceKind.WEB,
        source_name="test",
        agent_id="agent-1",
        session_key=f"agent-1::{session}",
        input_provenance={"kind": "test"},
    )


def _queue_depth_values(logs: list[Any]) -> list[int]:
    """Extract agentos_queue_depth metric values in order from captured logs."""
    return [
        int(log["value"])
        for log in logs
        if log.get("metric") == "agentos_queue_depth"
    ]


@pytest.mark.asyncio
async def test_queue_depth_decrements_when_task_leaves_pending() -> None:
    """When a task transitions QUEUED -> RUNNING, the gauge value drops."""
    runtime = _make_runtime()

    with _capture_metric_logs() as logs:
        h1 = await runtime.enqueue(_env("s1"), "task 1")
        h2 = await runtime.enqueue(_env("s1"), "task 2")
        await runtime.wait(h1.task_id)
        await runtime.wait(h2.task_id)

    values = _queue_depth_values(logs)
    # Verify depth rises then falls to zero
    assert max(values) >= 2, f"expected depth >= 2, got {values}"
    assert values[-1] == 0, f"expected last value 0, got {values}"


@pytest.mark.asyncio
async def test_queue_depth_reaches_zero_after_all_complete() -> None:
    """Gauge ends at 0 after all enqueued tasks complete."""
    runtime = _make_runtime()

    with _capture_metric_logs() as logs:
        h1 = await runtime.enqueue(_env("s2"), "task A")
        h2 = await runtime.enqueue(_env("s2"), "task B")
        await runtime.wait(h1.task_id)
        await runtime.wait(h2.task_id)

    values = _queue_depth_values(logs)
    assert values[-1] == 0, f"expected last value 0, got {values}"
