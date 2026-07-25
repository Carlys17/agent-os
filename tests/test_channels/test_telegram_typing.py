from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from agentos.channels.contract import ChannelCapabilities, ChannelSendStatus
from agentos.channels.stream_policy import resolve_channel_stream_policy
from agentos.channels.telegram import TelegramApiError, TelegramChannel, TelegramChannelConfig
from agentos.channels.types import IncomingMessage
from agentos.gateway import channel_dispatch


def _install_blocking_keepalive_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[float], asyncio.Event]:
    sleep_intervals: list[float] = []
    sleep_started = asyncio.Event()
    block_sleep = asyncio.Event()

    async def fake_sleep(interval: float) -> None:
        sleep_intervals.append(interval)
        sleep_started.set()
        await block_sleep.wait()

    monkeypatch.setattr(
        channel_dispatch,
        "asyncio",
        SimpleNamespace(create_task=asyncio.create_task, sleep=fake_sleep),
    )
    return sleep_intervals, sleep_started


@pytest.mark.asyncio
async def test_telegram_send_typing_posts_native_chat_action_for_topic() -> None:
    channel = TelegramChannel(TelegramChannelConfig(token="token"))
    calls: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_api(method: str, payload: dict[str, Any] | None = None) -> bool:
        calls.append((method, payload))
        return True

    channel._api = fake_api  # type: ignore[method-assign]  # noqa: SLF001

    result = await channel.send_typing(channel_id="-100123", thread_id="777")

    assert calls == [
        (
            "sendChatAction",
            {
                "chat_id": "-100123",
                "action": "typing",
                "message_thread_id": 777,
            },
        )
    ]
    assert result.status == ChannelSendStatus.SENT
    assert result.capability == ChannelCapabilities.TYPING_INDICATOR
    assert result.target_id == "-100123"


@pytest.mark.asyncio
async def test_telegram_send_typing_uses_default_target() -> None:
    channel = TelegramChannel(TelegramChannelConfig(token="token", default_chat_id="default-chat"))
    calls: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_api(method: str, payload: dict[str, Any] | None = None) -> bool:
        calls.append((method, payload))
        return True

    channel._api = fake_api  # type: ignore[method-assign]  # noqa: SLF001

    result = await channel.send_typing()

    assert calls == [("sendChatAction", {"chat_id": "default-chat", "action": "typing"})]
    assert result.status == ChannelSendStatus.SENT
    assert result.target_id == "default-chat"


@pytest.mark.asyncio
async def test_telegram_send_typing_without_target_is_unsupported() -> None:
    channel = TelegramChannel(TelegramChannelConfig(token="token"))

    async def unexpected_api(_method: str, _payload: dict[str, Any] | None = None) -> bool:
        raise AssertionError("sendChatAction must not run without a target")

    channel._api = unexpected_api  # type: ignore[method-assign]  # noqa: SLF001

    result = await channel.send_typing()

    assert result.status == ChannelSendStatus.UNSUPPORTED
    assert result.capability == ChannelCapabilities.TYPING_INDICATOR
    assert result.reason == "no chat target"


def test_telegram_typing_capability_selects_keepalive_policy() -> None:
    channel = TelegramChannel(TelegramChannelConfig())

    policy = resolve_channel_stream_policy(channel)

    assert channel.capability_profile.typing_indicator is True
    assert ChannelCapabilities.TYPING_INDICATOR in channel.capabilities
    assert policy.mode == "typing_final"
    assert policy.relay_stream is False
    assert policy.typing_keepalive is True
    assert 0 < channel.typing_keepalive_interval_s < 5


@pytest.mark.asyncio
async def test_telegram_keepalive_uses_inbound_chat_topic_and_adapter_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = TelegramChannel(TelegramChannelConfig(token="token"))
    api_calls: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_api(method: str, payload: dict[str, Any] | None = None) -> bool:
        api_calls.append((method, payload))
        return True

    channel._api = fake_api  # type: ignore[method-assign]  # noqa: SLF001
    sleep_intervals, sleep_started = _install_blocking_keepalive_sleep(monkeypatch)
    inbound = IncomingMessage(
        sender_id="user-1",
        channel_id="-100123",
        content="hello",
        metadata={"is_group": True, "thread_id": "777"},
    )

    task = channel_dispatch._start_typing_keepalive(channel, inbound)  # noqa: SLF001

    assert task is not None
    await asyncio.wait_for(sleep_started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert api_calls == [
        (
            "sendChatAction",
            {
                "chat_id": "-100123",
                "action": "typing",
                "message_thread_id": 777,
            },
        )
    ]
    assert sleep_intervals == [4.0]


@pytest.mark.asyncio
async def test_telegram_keepalive_treats_api_failure_as_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = TelegramChannel(TelegramChannelConfig(token="token"))
    attempts = 0

    async def failing_api(_method: str, _payload: dict[str, Any] | None = None) -> bool:
        nonlocal attempts
        attempts += 1
        raise TelegramApiError("rate limited")

    channel._api = failing_api  # type: ignore[method-assign]  # noqa: SLF001
    sleep_intervals, sleep_started = _install_blocking_keepalive_sleep(monkeypatch)
    inbound = IncomingMessage(
        sender_id="user-1",
        channel_id="chat-1",
        content="hello",
    )

    task = channel_dispatch._start_typing_keepalive(channel, inbound)  # noqa: SLF001

    assert task is not None
    await asyncio.wait_for(sleep_started.wait(), timeout=1)
    assert task.done() is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert attempts == 1
    assert sleep_intervals == [4.0]
