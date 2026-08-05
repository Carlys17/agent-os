"""A script job's stdout is its only trace, so the delivery chain must not drop it.

Several skips in :class:`DeliveryChain` encode "the run already wrote this into
the session, so mirroring it would duplicate it". That holds for an agent turn,
which appends its own reply to the transcript it ran in. A script job has no
turn: nothing writes its stdout anywhere unless the chain does, so the very same
skips silently discard the output instead of deduplicating it.

Two shapes reached that dead end:

* ``sessionTarget=current`` from webchat — ``_deliver_channel`` recognised the
  run's session as the destination session and returned ``"delivered"`` without
  writing, so a run reported success with nothing to show for it;
* a job bound to a chat whose run *is* that chat — ``_forward_to_session``
  skipped on ``origin == session_key``.

A third shape genuinely has nowhere to write (``agentos cron add --script``
with no ``--session-key``). That one is reported as ``no_session_target`` rather
than ``skipped``, so an empty chat is legible in ``agentos cron runs``.
"""

from __future__ import annotations

from typing import Any

from agentos.scheduler.delivery import (
    NO_SESSION_TARGET,
    ORIGIN_SESSION_GONE,
    DeliveryChain,
)
from agentos.scheduler.handlers import _required_delivery_error
from agentos.scheduler.payloads import make_script_payload
from agentos.scheduler.types import CronJob, DeliveryConfig, DeliveryMode, SessionTarget

WEBCHAT_SESSION = "agent:main:webchat:live-chat"
ISOLATED_RUN_KEY = "cron:job-1:run:deadbeef"


class _RecordingForwarder:
    """Stands in for the gateway forwarder, recording where output landed."""

    def __init__(self, result: bool | None = True) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> bool | None:
        self.calls.append(kwargs)
        return self.result


def _script_job(
    *,
    session_target: SessionTarget,
    session_key: str = "",
    origin_session_key: str = "",
    delivery: DeliveryConfig | None = None,
) -> CronJob:
    return CronJob(
        id="job-1",
        name="watch-memory",
        handler_key="script_run",
        payload=make_script_payload("watch-memory.sh"),
        session_target=session_target,
        session_key=session_key,
        origin_session_key=origin_session_key,
        delivery=delivery or DeliveryConfig(mode=DeliveryMode.NONE),
    )


def _agent_turn_job(**kwargs: Any) -> CronJob:
    job = _script_job(**kwargs)
    job.handler_key = "agent_run"
    job.payload = {"kind": "agent_turn", "task": "summarise", "agent_id": "main"}
    return job


async def test_current_target_webchat_script_output_reaches_the_chat() -> None:
    """The regression: run's session == destination session, so nothing wrote it."""
    forwarder = _RecordingForwarder()
    job = _script_job(
        session_target=SessionTarget.CURRENT,
        session_key=WEBCHAT_SESSION,
        origin_session_key=WEBCHAT_SESSION,
        delivery=DeliveryConfig(
            mode=DeliveryMode.ORIGIN,
            channel_name="webchat",
            channel_id=f"webchat:{WEBCHAT_SESSION}",
        ),
    )
    chain = DeliveryChain(session_forwarder=forwarder)

    report = await chain.deliver(
        job,
        result_text="3 alerts pending",
        success=True,
        summary="3 alerts pending",
        session_key=WEBCHAT_SESSION,
    )

    assert report.channel_status == "delivered"
    assert [c["origin_session_key"] for c in forwarder.calls] == [WEBCHAT_SESSION]
    assert forwarder.calls[0]["text"] == "3 alerts pending"
    assert _required_delivery_error(job, report) is None


async def test_current_target_webchat_agent_turn_is_still_not_mirrored() -> None:
    """The turn wrote its own reply there; mirroring would double it."""
    forwarder = _RecordingForwarder()
    job = _agent_turn_job(
        session_target=SessionTarget.CURRENT,
        session_key=WEBCHAT_SESSION,
        origin_session_key=WEBCHAT_SESSION,
        delivery=DeliveryConfig(
            mode=DeliveryMode.ORIGIN,
            channel_name="webchat",
            channel_id=f"webchat:{WEBCHAT_SESSION}",
        ),
    )
    chain = DeliveryChain(session_forwarder=forwarder)

    report = await chain.deliver(
        job,
        result_text="here is your summary",
        success=True,
        summary="here is your summary",
        session_key=WEBCHAT_SESSION,
    )

    assert report.channel_status == "delivered"
    assert forwarder.calls == []


async def test_script_output_is_mirrored_into_the_session_it_ran_in() -> None:
    """mode=NONE twin of the above: ``origin == session_key`` skipped the write."""
    forwarder = _RecordingForwarder()
    job = _script_job(
        session_target=SessionTarget.SESSION,
        session_key=WEBCHAT_SESSION,
        origin_session_key=WEBCHAT_SESSION,
    )
    chain = DeliveryChain(session_forwarder=forwarder)

    report = await chain.deliver(
        job,
        result_text="disk at 91%",
        success=True,
        summary="disk at 91%",
        session_key=WEBCHAT_SESSION,
    )

    assert report.session_status == "delivered"
    assert [c["origin_session_key"] for c in forwarder.calls] == [WEBCHAT_SESSION]
    assert _required_delivery_error(job, report) is None


async def test_agent_turn_in_its_own_session_is_still_skipped() -> None:
    forwarder = _RecordingForwarder()
    job = _agent_turn_job(
        session_target=SessionTarget.SESSION,
        session_key=WEBCHAT_SESSION,
        origin_session_key=WEBCHAT_SESSION,
    )
    chain = DeliveryChain(session_forwarder=forwarder)

    report = await chain.deliver(
        job,
        result_text="summary",
        success=True,
        summary="summary",
        session_key=WEBCHAT_SESSION,
    )

    assert report.session_status == "skipped"
    assert forwarder.calls == []


async def test_isolated_script_job_mirrors_into_its_origin_chat() -> None:
    """The web-UI shape: isolated run, output mirrored back to the chat."""
    forwarder = _RecordingForwarder()
    job = _script_job(
        session_target=SessionTarget.ISOLATED,
        origin_session_key=WEBCHAT_SESSION,
    )
    chain = DeliveryChain(session_forwarder=forwarder)

    report = await chain.deliver(
        job,
        result_text="nothing unusual",
        success=True,
        summary="nothing unusual",
        session_key=ISOLATED_RUN_KEY,
    )

    assert report.session_status == "delivered"
    assert [c["origin_session_key"] for c in forwarder.calls] == [WEBCHAT_SESSION]


async def test_isolated_script_job_with_no_chat_reports_no_session_target() -> None:
    """``agentos cron add --script`` without ``--session-key``.

    Nothing is wrong with the run — the script ran and its stdout is on the run
    record — but the output reached no conversation, and the status has to say
    so rather than read as an ordinary skip.
    """
    forwarder = _RecordingForwarder()
    job = _script_job(session_target=SessionTarget.ISOLATED)
    chain = DeliveryChain(session_forwarder=forwarder)

    report = await chain.deliver(
        job,
        result_text="hello from a script cron job",
        success=True,
        summary="hello from a script cron job",
        session_key=ISOLATED_RUN_KEY,
    )

    assert report.session_status == NO_SESSION_TARGET
    assert forwarder.calls == []
    # Not a failure: the job did what it was asked to do.
    assert _required_delivery_error(job, report) is None


async def test_script_mirror_survives_a_vanished_chat() -> None:
    forwarder = _RecordingForwarder(result=False)
    job = _script_job(
        session_target=SessionTarget.ISOLATED,
        origin_session_key="agent:main:webchat:closed-chat",
    )
    chain = DeliveryChain(session_forwarder=forwarder)

    report = await chain.deliver(
        job,
        result_text="nothing unusual",
        success=True,
        summary="nothing unusual",
        session_key=ISOLATED_RUN_KEY,
    )

    assert report.session_status == ORIGIN_SESSION_GONE
    assert _required_delivery_error(job, report) is None


async def test_script_job_is_recognised_from_its_payload_alone() -> None:
    """Rows written before ``handler_key`` was normalized still carry the kind."""
    forwarder = _RecordingForwarder()
    job = _script_job(
        session_target=SessionTarget.SESSION,
        session_key=WEBCHAT_SESSION,
        origin_session_key=WEBCHAT_SESSION,
    )
    job.handler_key = ""
    chain = DeliveryChain(session_forwarder=forwarder)

    report = await chain.deliver(
        job,
        result_text="disk at 91%",
        success=True,
        summary="disk at 91%",
        session_key=WEBCHAT_SESSION,
    )

    assert report.session_status == "delivered"
    assert len(forwarder.calls) == 1
