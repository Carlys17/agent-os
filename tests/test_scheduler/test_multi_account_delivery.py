from __future__ import annotations

import pytest

from agentos.channels.manager import ChannelManager
from agentos.channels.types import OutgoingMessage
from agentos.scheduler.delivery import DeliveryChain
from agentos.scheduler.payloads import make_script_payload
from agentos.scheduler.types import CronJob, DeliveryConfig, DeliveryMode, SessionTarget


class _FakeAdapter:
    def __init__(self, name: str) -> None:
        self.name = name
        self.messages: list[OutgoingMessage] = []

    async def send(self, message: OutgoingMessage) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_cron_delivery_resolves_and_honors_account_id() -> None:
    # Setup two Slack adapters
    adapter1 = _FakeAdapter("slack-bot-1")
    adapter2 = _FakeAdapter("slack-bot-2")
    channels = {"slack-bot-1": adapter1, "slack-bot-2": adapter2}
    channel_types = {"slack-bot-1": "slack", "slack-bot-2": "slack"}

    # Use a real ChannelManager configured with two adapters of the same type
    manager = ChannelManager(
        _channels=channels,  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types=channel_types,
    )
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    job = CronJob(
        id="job-1",
        name="multi-acc-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C0123ABCDEF",
            account_id="slack-bot-1",
        ),
    )

    report = await chain.deliver(
        job,
        result_text="hello world",
        success=True,
        summary="hello world",
        session_key="cron:job-1:run:deadbeef",
    )

    assert report.channel_status == "delivered"
    # Ensure message went to adapter 1 and not adapter 2
    assert len(adapter1.messages) == 1
    assert adapter1.messages[0].content == "hello world"
    assert len(adapter2.messages) == 0


@pytest.mark.asyncio
async def test_cron_delivery_resolution_failure_reports_failed() -> None:
    # Setup one Slack adapter
    adapter = _FakeAdapter("slack-bot-1")
    channels = {"slack-bot-1": adapter}
    channel_types = {"slack-bot-1": "slack"}

    # Use a real ChannelManager
    manager = ChannelManager(
        _channels=channels,  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types=channel_types,
    )
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    # Use a non-existent account_id
    job = CronJob(
        id="job-1",
        name="multi-acc-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C0123ABCDEF",
            account_id="slack-bot-nonexistent",
        ),
    )

    report = await chain.deliver(
        job,
        result_text="hello world",
        success=True,
        summary="hello world",
        session_key="cron:job-1:run:deadbeef",
    )

    assert report.channel_status == "delivery_failed"
    assert "delivery target resolution failed: unsupported_account" in report.channel_detail
