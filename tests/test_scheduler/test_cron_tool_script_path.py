"""What the ``cron`` tool reports back about a script job's path.

The caller writes the script *after* the job exists — that is the whole point of
``{job_id}`` — so the add result has to say where. It reports the path the job
actually carries, not the argument it was handed, and spells it out in full:
``script`` is relative to a directory the tool never names.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import pytest

import agentos.tools.builtin.control as control_mod
from agentos.scheduler.ops import _resolve_script_placeholder
from agentos.scheduler.types import CronJob, DeliveryConfig
from agentos.tools.builtin.control import cron as cron_tool
from agentos.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    current_tool_context,
)


@contextmanager
def _with_ctx(ctx: ToolContext):
    token = current_tool_context.set(ctx)
    try:
        yield
    finally:
        current_tool_context.reset(token)


class _FakeScheduler:
    """Stands in for the engine, but resolves the placeholder the way ops does.

    The substitution itself belongs to ``SchedulerOps`` and is covered against a
    real store in ``test_script_job_id_placeholder``. Calling the same helper
    here keeps this stub from quietly diverging from it — a fake that skipped
    the step would let the tool look correct while reporting a path holding an
    unresolved placeholder.
    """

    def __init__(self) -> None:
        self.jobs: list[CronJob] = []

    async def list_jobs(self) -> list[CronJob]:
        return list(self.jobs)

    async def add_job(self, **kwargs: Any) -> CronJob:
        job = CronJob(
            id="1f3c9d2a-0000-4000-8000-00000000abcd",
            name=kwargs["name"],
            cron_expr=kwargs.get("schedule_value", ""),
            schedule_raw=kwargs.get("schedule_value", ""),
            handler_key=kwargs["handler_key"],
            payload=kwargs["payload"],
            session_target=kwargs["session_target"],
            session_key=kwargs["session_key"],
            delivery=kwargs.get("delivery") or DeliveryConfig(),
        )
        _resolve_script_placeholder(job)
        self.jobs.append(job)
        return job

    async def update_job(self, job_id: str, **patch: Any) -> CronJob | None:
        for job in self.jobs:
            if job.id == job_id:
                for key, value in patch.items():
                    setattr(job, key, value)
                return job
        return None

    async def get_job(self, job_id: str) -> CronJob | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    async def remove_job(self, job_id: str) -> bool:
        return False

    async def get_runs(self, job_id: str, limit: int = 20) -> list[Any]:
        return []


@pytest.fixture
def scheduler(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTOS_STATE_DIR", str(tmp_path))
    sched = _FakeScheduler()
    control_mod.set_scheduler(sched)

    from agentos.tools.builtin import sessions as sessions_mod

    class _Storage:
        async def get_session(self, session_key: str) -> None:
            return None

    class _Manager:
        _storage = _Storage()

    monkeypatch.setattr(sessions_mod, "_get_session_manager", lambda: _Manager())
    yield sched
    control_mod.set_scheduler(None)  # type: ignore[arg-type]


def _web_ctx() -> ToolContext:
    return ToolContext(
        caller_kind=CallerKind.WEB,
        interaction_mode=InteractionMode.INTERACTIVE,
        session_key="agent:main:webchat:u1",
        agent_id="main",
    )


async def _add(script: str) -> dict[str, Any]:
    with _with_ctx(_web_ctx()):
        raw = await cron_tool(
            action="add",
            name="monitor",
            schedule={"kind": "every", "every_seconds": 600},
            job_kind="script",
            script=script,
            session_target="isolated",
        )
    return json.loads(raw)


async def test_add_reports_the_resolved_script_and_its_full_path(scheduler) -> None:
    result = await _add("unilp/{job_id}/tick.sh")

    job_id = result["job_id"]
    assert result["script"] == f"unilp/{job_id}/tick.sh"
    assert result["script_path"].endswith(f"scripts/unilp/{job_id}/tick.sh")
    assert "{job_id}" not in result["script"]
    assert "{job_id}" not in result["script_path"]


async def test_a_plain_script_still_reports_where_it_lives(scheduler) -> None:
    result = await _add("watch.sh")

    assert result["script"] == "watch.sh"
    assert result["script_path"].endswith("scripts/watch.sh")


async def test_a_job_with_no_script_reports_no_path(scheduler) -> None:
    with _with_ctx(_web_ctx()):
        raw = await cron_tool(
            action="add",
            name="ping",
            schedule={"kind": "every", "every_seconds": 600},
            job_kind="agent_turn",
            task="say hi",
            session_target="isolated",
        )

    assert "script_path" not in json.loads(raw)
