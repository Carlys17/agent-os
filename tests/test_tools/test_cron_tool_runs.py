"""Cron tool: ``action=runs`` — what a scheduled job actually did.

Without this action the model can list a job but not see a single thing any run
produced, so "what did the watcher report last night?" had no answer it could
look up — only one it could invent. For a ``script`` job the run record is the
*only* place stdout is kept unless the job was bound to a chat, which makes this
the difference between the model reading the output and guessing at it.

The bounds matter as much as the data: a watcher's stdout is unbounded and the
answer has to fit in a context window, so the limit is clamped and long output
is truncated with a flag saying so rather than silently cut.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

import agentos.tools.builtin.control as control_mod
from agentos.scheduler.payloads import make_script_payload
from agentos.tools.builtin.control import cron as cron_tool
from agentos.tools.types import ToolError

RUN_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _run(
    *,
    summary: str = "pool alpha: ok",
    success: bool = True,
    delivery: str = "skipped|ws:no_subscribers|fwd:delivered",
    error: str | None = None,
) -> Any:
    return SimpleNamespace(
        started_at=RUN_AT,
        success=success,
        summary=summary,
        delivery_status=delivery,
        error=error,
    )


class _FakeScheduler:
    def __init__(self, runs: list[Any], *, agent_id: str = "main") -> None:
        self._runs = runs
        self._job = SimpleNamespace(
            id="job-1",
            name="memory-watchdog",
            payload=make_script_payload("watch-memory.sh", agent_id),
        )
        self.get_runs_calls: list[tuple[str, int]] = []

    async def get_job(self, job_id: str) -> Any | None:
        return self._job if job_id == "job-1" else None

    async def get_runs(self, job_id: str, limit: int = 20) -> list[Any]:
        self.get_runs_calls.append((job_id, limit))
        return self._runs[:limit]


async def _runs(fake: _FakeScheduler, **kwargs: Any) -> dict[str, Any]:
    control_mod.set_scheduler(fake)
    try:
        raw = await cron_tool(action="runs", job_id="job-1", **kwargs)
    finally:
        control_mod.set_scheduler(None)  # type: ignore[arg-type]
    return json.loads(raw)


@pytest.mark.asyncio
async def test_runs_returns_the_output_each_run_produced() -> None:
    fake = _FakeScheduler([_run(summary="pool beta: BELOW FLOOR")])

    payload = await _runs(fake)

    assert payload["action"] == "runs"
    assert payload["job_id"] == "job-1"
    assert payload["name"] == "memory-watchdog"
    assert payload["runs"] == [
        {
            "started_at": "2026-01-02T03:04:05+00:00",
            "success": True,
            # Named "output", not "summary": for a script job this is literal
            # stdout, and the name should invite quoting rather than rewording.
            "output": "pool beta: BELOW FLOOR",
            "delivery": "skipped|ws:no_subscribers|fwd:delivered",
        }
    ]


@pytest.mark.asyncio
async def test_runs_surfaces_delivery_so_a_silent_job_is_distinguishable() -> None:
    """"It ran and told you" and "it ran and told no one" look identical
    from the job alone — only the run's delivery status separates them."""
    fake = _FakeScheduler(
        [_run(delivery="skipped|ws:no_subscribers|fwd:no_session_target")]
    )

    payload = await _runs(fake)

    assert payload["runs"][0]["delivery"].endswith("fwd:no_session_target")


@pytest.mark.asyncio
async def test_runs_reports_failures_with_their_error() -> None:
    fake = _FakeScheduler(
        [_run(summary="", success=False, error="exit status 1: no such file")]
    )

    payload = await _runs(fake)

    assert payload["runs"][0]["success"] is False
    assert payload["runs"][0]["error"] == "exit status 1: no such file"


@pytest.mark.asyncio
async def test_runs_omits_error_when_there_was_none() -> None:
    fake = _FakeScheduler([_run()])

    payload = await _runs(fake)

    assert "error" not in payload["runs"][0]
    assert "output_truncated" not in payload["runs"][0]


@pytest.mark.asyncio
async def test_long_output_is_truncated_and_says_so() -> None:
    fake = _FakeScheduler([_run(summary="x" * 5000)])

    payload = await _runs(fake)

    run = payload["runs"][0]
    assert len(run["output"]) == control_mod._CRON_RUN_OUTPUT_MAX_CHARS
    assert run["output_truncated"] is True


@pytest.mark.asyncio
async def test_limit_defaults_and_is_clamped_to_the_maximum() -> None:
    fake = _FakeScheduler([_run() for _ in range(50)])

    await _runs(fake)
    assert fake.get_runs_calls[-1] == ("job-1", control_mod._CRON_RUNS_DEFAULT_LIMIT)

    await _runs(fake, limit=500)
    assert fake.get_runs_calls[-1] == ("job-1", control_mod._CRON_RUNS_MAX_LIMIT)

    await _runs(fake, limit=0)
    assert fake.get_runs_calls[-1] == ("job-1", 1)

    # A model that fills the field with a string should not crash the call.
    await _runs(fake, limit="three")  # type: ignore[arg-type]
    assert fake.get_runs_calls[-1] == ("job-1", control_mod._CRON_RUNS_DEFAULT_LIMIT)


@pytest.mark.asyncio
async def test_runs_requires_a_job_id() -> None:
    control_mod.set_scheduler(_FakeScheduler([]))
    try:
        with pytest.raises(ToolError, match="'job_id' required for runs"):
            await cron_tool(action="runs")
    finally:
        control_mod.set_scheduler(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_runs_rejects_an_unknown_job() -> None:
    fake = _FakeScheduler([])
    control_mod.set_scheduler(fake)
    try:
        with pytest.raises(ToolError, match="Job not found"):
            await cron_tool(action="runs", job_id="nope")
    finally:
        control_mod.set_scheduler(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_runs_refuses_a_job_owned_by_another_profile() -> None:
    """Same ownership boundary remove and run already enforce."""
    fake = _FakeScheduler([_run()], agent_id="research")
    control_mod.set_scheduler(fake)
    try:
        with pytest.raises(ToolError, match="different profile"):
            await cron_tool(action="runs", job_id="job-1")
    finally:
        control_mod.set_scheduler(None)  # type: ignore[arg-type]
