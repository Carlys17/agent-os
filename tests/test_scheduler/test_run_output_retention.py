"""A run record keeps the whole output; only what goes *out* stays short.

One 500-character cap used to serve two unrelated jobs: trimming the WS/webhook
payload, and writing the run record. The second use destroyed the output at write
time, so the run-history drawer could never show more than half a screen of a
script's stdout no matter how it scrolled.

They are separate now:

* ``preview_summary`` — WS broadcast, webhook POST, ``cron.runs`` list rows;
* ``clamp_run_output`` — the stored record, capped only as a runaway backstop.

``cron.runOutput`` then fetches the full text for the single run someone opens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentos.gateway.rpc_cron import _handle_cron_run_output, _handle_cron_runs
from agentos.scheduler.handlers import make_script_run_handler
from agentos.scheduler.jobs import execute_with_timeout
from agentos.scheduler.payloads import make_script_payload
from agentos.scheduler.persistence import JobStore
from agentos.scheduler.types import (
    CRON_RUN_OUTPUT_MAX_CHARS,
    CRON_SUMMARY_PREVIEW_CHARS,
    CronJob,
    DeliveryConfig,
    DeliveryMode,
    HandlerResult,
    JobExecution,
    SessionTarget,
    clamp_run_output,
    preview_summary,
)

LONG_OUTPUT = "line of json output\n" * 400  # ~8 KB, well past the old cap


def _script_job() -> CronJob:
    return CronJob(
        id="job-1",
        name="ratchet-tick",
        handler_key="script_run",
        payload=make_script_payload("ratchet.py"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(mode=DeliveryMode.NONE),
    )


class _RecordingChain:
    """Captures what the delivery chain was handed, which must stay small."""

    def __init__(self) -> None:
        self.delivered: list[dict[str, Any]] = []

    async def notify_start(self, job: CronJob, text: str) -> None:
        return None

    async def deliver(self, job: CronJob, **kwargs: Any) -> Any:
        self.delivered.append(kwargs)
        from agentos.scheduler.delivery import DeliveryReport

        return DeliveryReport(
            channel_status="skipped",
            ws_status="skipped",
            session_status="skipped",
        )


class _FakeScheduler:
    def __init__(self, runs: list[JobExecution]) -> None:
        self.runs = runs

    async def get_runs(self, job_id: str, limit: int = 20) -> list[JobExecution]:
        return self.runs[:limit]

    async def get_run(self, job_id: str, run_id: str | None = None) -> JobExecution | None:
        if run_id is None:
            return self.runs[0] if self.runs else None
        return next((r for r in self.runs if r.id == run_id), None)


def _ctx(scheduler: Any) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(cron_scheduler=scheduler)


# ── the helpers themselves ──────────────────────────────────────────────────


def test_preview_is_short_and_stored_output_is_not() -> None:
    assert len(preview_summary(LONG_OUTPUT) or "") == CRON_SUMMARY_PREVIEW_CHARS
    assert clamp_run_output(LONG_OUTPUT) == LONG_OUTPUT


def test_stored_output_still_has_a_runaway_backstop() -> None:
    runaway = "x" * (CRON_RUN_OUTPUT_MAX_CHARS + 5_000)
    assert len(clamp_run_output(runaway) or "") == CRON_RUN_OUTPUT_MAX_CHARS


@pytest.mark.parametrize("empty", ["", None])
def test_helpers_pass_empty_values_through(empty: str | None) -> None:
    assert preview_summary(empty) == empty
    assert clamp_run_output(empty) == empty


# ── the handler: full text on the record, preview on the wire ───────────────


async def test_script_handler_keeps_full_output_but_delivers_a_preview(monkeypatch) -> None:
    chain = _RecordingChain()
    monkeypatch.setattr(
        "agentos.scheduler.handlers.run_job_script",
        _fake_run_script(True, LONG_OUTPUT),
    )

    result = await make_script_run_handler(chain)(_script_job())

    assert result.summary == LONG_OUTPUT
    assert len(chain.delivered) == 1
    delivered = chain.delivered[0]["summary"]
    assert len(delivered) == CRON_SUMMARY_PREVIEW_CHARS
    # The WS broadcast and webhook POST both carry this value — it must not grow.
    assert LONG_OUTPUT.startswith(delivered)


async def test_execute_with_timeout_no_longer_trims_the_record() -> None:
    async def handler(job: CronJob) -> HandlerResult:
        return HandlerResult(summary=LONG_OUTPUT, session_key="s", delivery_status="skipped")

    execution = await execute_with_timeout(_script_job(), handler)

    assert execution.summary == LONG_OUTPUT


def _fake_run_script(ok: bool, output: str):
    async def _run(script: str, **kwargs: Any) -> tuple[bool, str]:
        return ok, output

    return _run


# ── persistence: one run at a time ──────────────────────────────────────────


async def test_get_execution_reads_back_the_full_output(tmp_path: Path) -> None:
    store = JobStore(str(tmp_path / "cron.db"))
    await store.open()
    try:
        run = JobExecution(job_id="job-1", success=True, summary=LONG_OUTPUT)
        await store.save_execution(run)

        by_id = await store.get_execution("job-1", run.id)
        assert by_id is not None
        assert by_id.summary == LONG_OUTPUT

        latest = await store.get_execution("job-1")
        assert latest is not None and latest.id == run.id

        # Scoped to the job, so a run id alone cannot reach another job's output.
        assert await store.get_execution("other-job", run.id) is None
        assert await store.get_execution("job-1", "no-such-run") is None
    finally:
        await store.close()


async def test_get_execution_returns_none_for_a_job_that_never_ran(tmp_path: Path) -> None:
    store = JobStore(str(tmp_path / "cron.db"))
    await store.open()
    try:
        assert await store.get_execution("job-1") is None
    finally:
        await store.close()


# ── RPC surface ─────────────────────────────────────────────────────────────


async def test_cron_runs_rows_carry_a_preview_and_say_it_is_one() -> None:
    scheduler = _FakeScheduler([JobExecution(id="r1", job_id="job-1", summary=LONG_OUTPUT)])

    rows = await _handle_cron_runs({"id": "job-1"}, _ctx(scheduler))

    assert len(rows[0]["summary"]) == CRON_SUMMARY_PREVIEW_CHARS
    assert rows[0]["summaryTruncated"] is True
    assert rows[0]["id"] == "r1"


async def test_a_short_run_is_not_marked_truncated() -> None:
    scheduler = _FakeScheduler([JobExecution(id="r1", job_id="job-1", summary="all quiet")])

    rows = await _handle_cron_runs({"id": "job-1"}, _ctx(scheduler))

    assert rows[0]["summary"] == "all quiet"
    assert rows[0]["summaryTruncated"] is False


async def test_cron_run_output_returns_the_whole_thing() -> None:
    scheduler = _FakeScheduler([JobExecution(id="r1", job_id="job-1", summary=LONG_OUTPUT)])

    payload = await _handle_cron_run_output({"id": "job-1", "runId": "r1"}, _ctx(scheduler))

    assert payload["output"] == LONG_OUTPUT
    assert payload["runId"] == "r1"


async def test_cron_run_output_defaults_to_the_latest_run() -> None:
    scheduler = _FakeScheduler(
        [
            JobExecution(id="r2", job_id="job-1", summary="newest"),
            JobExecution(id="r1", job_id="job-1", summary="older"),
        ]
    )

    payload = await _handle_cron_run_output({"id": "job-1"}, _ctx(scheduler))

    assert payload["output"] == "newest"


async def test_cron_run_output_rejects_an_unknown_run() -> None:
    scheduler = _FakeScheduler([])

    with pytest.raises(KeyError):
        await _handle_cron_run_output({"id": "job-1", "runId": "nope"}, _ctx(scheduler))


async def test_cron_run_output_requires_a_job_id() -> None:
    with pytest.raises(ValueError):
        await _handle_cron_run_output({}, _ctx(_FakeScheduler([])))
