"""A cron job must not fail because the chat it was created from is gone.

The web UI stamps ``originSessionKey`` onto every reminder job
(``frontend/src/views/cron/logic.ts:1009-1011``) while forcing the target to
ISOLATED (``logic.ts:820-827``), and reminder is the default payload kind for a
new job (``logic.ts:692``). The session mirror is therefore configured on jobs
the operator never asked to bind to a session — so when the originating chat is
replaced, the mirror must degrade to a no-op rather than fail the run.

``DeliveryChain`` learns the origin is gone from a ``False`` return on the
session forwarder (``gateway/boot.py`` looks the session up before appending).
Forwarders that return ``None`` keep the historic "delivered" contract.
"""

from __future__ import annotations

from typing import Any

from agentos.scheduler.delivery import ORIGIN_SESSION_GONE, DeliveryChain
from agentos.scheduler.handlers import _required_delivery_error
from agentos.scheduler.types import CronJob, DeliveryConfig, DeliveryMode, SessionTarget

STALE_ORIGIN = "agent:main:webchat:closed-chat"
RUN_SESSION_KEY = "cron:job-1:run:deadbeef"


def _isolated_reminder_job() -> CronJob:
    """The shape the web UI produces for a default reminder."""
    return CronJob(
        id="job-1",
        name="daily brief",
        session_target=SessionTarget.ISOLATED,
        session_key="",
        origin_session_key=STALE_ORIGIN,
        delivery=DeliveryConfig(mode=DeliveryMode.NONE),
    )


async def _forwarder_origin_gone(**_: Any) -> bool:
    return False


async def _forwarder_legacy_none(**_: Any) -> None:
    return None


async def _forwarder_raises(**_: Any) -> bool:
    raise KeyError(f"Session not found: {STALE_ORIGIN}")


async def test_missing_origin_session_does_not_fail_an_isolated_run() -> None:
    job = _isolated_reminder_job()
    chain = DeliveryChain(session_forwarder=_forwarder_origin_gone)

    report = await chain.deliver(
        job,
        result_text="Here is your daily brief.",
        success=True,
        summary="brief",
        session_key=RUN_SESSION_KEY,
    )

    assert report.session_status == ORIGIN_SESSION_GONE
    assert _required_delivery_error(job, report) is None


async def test_forwarder_returning_none_still_counts_as_delivered() -> None:
    """The historic contract: forwarders returned None on success."""
    job = _isolated_reminder_job()
    chain = DeliveryChain(session_forwarder=_forwarder_legacy_none)

    report = await chain.deliver(
        job,
        result_text="Here is your daily brief.",
        success=True,
        summary="brief",
        session_key=RUN_SESSION_KEY,
    )

    assert report.session_status == "delivered"
    assert _required_delivery_error(job, report) is None


async def test_unexpected_forwarder_error_is_still_a_failure() -> None:
    """Only a clean "origin is gone" signal is forgiven; real errors are not."""
    job = _isolated_reminder_job()
    chain = DeliveryChain(session_forwarder=_forwarder_raises)

    report = await chain.deliver(
        job,
        result_text="Here is your daily brief.",
        success=True,
        summary="brief",
        session_key=RUN_SESSION_KEY,
    )

    assert report.session_status == "forward_failed"
    assert _required_delivery_error(job, report) is not None


async def test_inferred_webchat_origin_delivery_is_also_forgiven() -> None:
    """The second webchat path: ``mode=ORIGIN`` synthesised by the cron tool.

    When the agent schedules something from a webchat turn, the cron tool builds
    ``mode=ORIGIN`` + ``channel=webchat`` from the live ToolContext
    (``tools/builtin/control.py:424-445``) — the operator never picked that
    destination. So it must degrade the same way the mode=NONE mirror does,
    rather than failing the run.
    """
    job = CronJob(
        id="job-2",
        name="agent-scheduled brief",
        session_target=SessionTarget.ISOLATED,
        session_key="",
        origin_session_key=STALE_ORIGIN,
        delivery=DeliveryConfig(
            mode=DeliveryMode.ORIGIN,
            channel_name="webchat",
            channel_id=f"webchat:{STALE_ORIGIN}",
        ),
    )
    chain = DeliveryChain(session_forwarder=_forwarder_origin_gone)

    report = await chain.deliver(
        job,
        result_text="Here is your daily brief.",
        success=True,
        summary="brief",
        session_key=RUN_SESSION_KEY,
    )

    assert report.channel_status == ORIGIN_SESSION_GONE
    assert _required_delivery_error(job, report) is None


async def test_a_real_channel_delivery_failure_still_fails_the_run() -> None:
    """The forgiveness must not leak into genuine channel delivery problems."""
    job = CronJob(
        id="job-3",
        name="telegram brief",
        session_target=SessionTarget.ISOLATED,
        session_key="",
        origin_session_key=STALE_ORIGIN,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="telegram",
            channel_id="-1001234567890",
        ),
    )
    # No channel manager wired -> the adapter cannot be reached.
    chain = DeliveryChain(session_forwarder=_forwarder_origin_gone)

    report = await chain.deliver(
        job,
        result_text="Here is your daily brief.",
        success=True,
        summary="brief",
        session_key=RUN_SESSION_KEY,
    )

    assert report.channel_status != ORIGIN_SESSION_GONE
    assert _required_delivery_error(job, report) is not None
