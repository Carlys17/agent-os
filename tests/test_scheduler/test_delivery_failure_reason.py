"""A failed delivery has to say *why* on the run record.

The run that prompted this failed with exactly one line — "Cron job '<name>'
delivery failed" — while the reason (Telegram's `chat not found`) existed only
as a log line in the gateway's stdout. Whoever reads `agentos cron runs` next
gets the reason too.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.scheduler.delivery import DeliveryChain
from agentos.scheduler.handlers import _required_delivery_error
from agentos.scheduler.payloads import make_script_payload
from agentos.scheduler.types import CronJob, DeliveryConfig, DeliveryMode, SessionTarget


class _FailingAdapter:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def send(self, message: Any) -> None:
        raise self._error


class _FakeChannelManager:
    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def get(self, name: str) -> Any:
        return self._adapter


def _telegram_job() -> CronJob:
    return CronJob(
        id="job-1",
        name="watch-memory",
        handler_key="script_run",
        payload=make_script_payload("watch-memory.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="telegram",
            channel_id="1245463966",
        ),
    )


async def _deliver_with(adapter: Any) -> Any:
    chain = DeliveryChain(channel_manager_ref=lambda: _FakeChannelManager(adapter))
    return await chain.deliver(
        _telegram_job(),
        result_text="3 alerts pending",
        success=True,
        summary="3 alerts pending",
        session_key="cron:job-1:run:deadbeef",
    )


@pytest.mark.asyncio
async def test_the_adapters_error_is_carried_on_the_report() -> None:
    report = await _deliver_with(_FailingAdapter(RuntimeError("Bad Request: chat not found")))

    assert report.channel_status == "delivery_failed"
    assert "chat not found" in report.channel_detail


@pytest.mark.asyncio
async def test_the_run_error_names_the_reason_not_just_the_job() -> None:
    report = await _deliver_with(_FailingAdapter(RuntimeError("Bad Request: chat not found")))

    error = _required_delivery_error(_telegram_job(), report)

    assert error is not None
    assert "watch-memory" in error
    assert "telegram" in error
    assert "chat not found" in error


@pytest.mark.asyncio
async def test_a_missing_adapter_says_so() -> None:
    chain = DeliveryChain(channel_manager_ref=lambda: _FakeChannelManager(None))
    report = await chain.deliver(
        _telegram_job(),
        result_text="3 alerts pending",
        success=True,
        summary="3 alerts pending",
        session_key="cron:job-1:run:deadbeef",
    )

    assert report.channel_status == "delivery_failed"
    assert "no adapter" in report.channel_detail
    assert "no adapter" in str(_required_delivery_error(_telegram_job(), report))


@pytest.mark.asyncio
async def test_a_successful_delivery_carries_no_reason() -> None:
    class _OkAdapter:
        async def send(self, message: Any) -> None:
            return None

    report = await _deliver_with(_OkAdapter())

    assert report.channel_status == "delivered"
    assert report.channel_detail == ""
    assert _required_delivery_error(_telegram_job(), report) is None
