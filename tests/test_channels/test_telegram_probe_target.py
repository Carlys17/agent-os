"""``probe_target`` lets a caller check a chat id before committing to it.

Cron uses it at save time: a recipient Telegram cannot reach is worth knowing
about while the operator is still looking at the form.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.channels.telegram import TelegramApiError, TelegramChannel, TelegramChannelConfig


def _channel() -> TelegramChannel:
    return TelegramChannel(TelegramChannelConfig(token="token"))


@pytest.mark.asyncio
async def test_probe_confirms_a_chat_the_bot_can_see() -> None:
    channel = _channel()
    calls: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_api(method: str, payload: dict[str, Any] | None = None) -> Any:
        calls.append((method, payload))
        return {"id": 1245463966, "type": "private"}

    channel._api = fake_api  # type: ignore[method-assign]  # noqa: SLF001

    ok, reason = await channel.probe_target("1245463966")

    assert (ok, reason) == (True, "")
    assert calls == [("getChat", {"chat_id": "1245463966"})]


@pytest.mark.asyncio
async def test_probe_reports_the_reason_telegram_gave() -> None:
    channel = _channel()

    async def fake_api(method: str, payload: dict[str, Any] | None = None) -> Any:
        raise TelegramApiError("Telegram getChat failed: Bad Request: chat not found")

    channel._api = fake_api  # type: ignore[method-assign]  # noqa: SLF001

    ok, reason = await channel.probe_target("agent:main:telegram:direct:1245463966")

    assert ok is False
    assert "chat not found" in reason


@pytest.mark.asyncio
async def test_a_transport_failure_is_not_a_verdict_on_the_chat() -> None:
    # The bot being unable to reach Telegram says nothing about the chat id, so
    # the probe raises rather than answering "no" — the caller decides.
    channel = _channel()

    async def fake_api(method: str, payload: dict[str, Any] | None = None) -> Any:
        raise TelegramApiError("Telegram getChat connection failed")

    channel._api = fake_api  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(TelegramApiError):
        await channel.probe_target("1245463966")


@pytest.mark.asyncio
async def test_probe_without_a_target_is_not_an_answer() -> None:
    channel = _channel()
    calls: list[str] = []

    async def fake_api(method: str, payload: dict[str, Any] | None = None) -> Any:
        calls.append(method)
        return {}

    channel._api = fake_api  # type: ignore[method-assign]  # noqa: SLF001

    ok, reason = await channel.probe_target("   ")

    assert (ok, reason) == (True, "")
    assert calls == []
