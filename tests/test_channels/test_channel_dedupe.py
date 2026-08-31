from __future__ import annotations

import json

import pytest

from agentos.channels.discord import DiscordChannel, DiscordChannelConfig
from agentos.channels.msteams import MSTeamsChannel, MSTeamsChannelConfig
from agentos.channels.slack import SlackChannel
from agentos.channels.types import IncomingMessage


class _BodyRequest:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()
        self.headers: dict[str, str] = {}

    async def body(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_slack_webhook_dedupes_retried_event_callback() -> None:
    channel = SlackChannel(
        token="xoxb-test",
        slack_channel_id="C1",
        signing_secret="test_secret",
    )
    payload = {
        "type": "event_callback",
        "event_id": "Ev123",
        "event": {
            "type": "message",
            "user": "U1",
            "channel": "C1",
            "text": "draw an image",
            "ts": "1710000000.000100",
            "channel_type": "im",
        },
    }

    import time

    # Bypass signature verification in test (auth tested separately)
    channel._verify_signature = lambda *a, **k: True  # type: ignore[method-assign]

    req = _BodyRequest(payload)
    req.headers["X-Slack-Signature"] = "v0=test"
    req.headers["X-Slack-Request-Timestamp"] = str(int(time.time()))
    await channel._handle_webhook(req)  # noqa: SLF001
    await channel._handle_webhook(req)  # noqa: SLF001

    assert channel._queue.qsize() == 1  # noqa: SLF001
    assert (await channel.receive()).content == "draw an image"


@pytest.mark.asyncio
async def test_slack_webhook_rejects_event_callback_when_signing_secret_unset() -> None:
    """event_callback must be rejected when signing_secret is not configured."""
    channel = SlackChannel(token="xoxb-test", slack_channel_id="C1")
    # signing_secret defaults to None
    assert channel.signing_secret is None
    payload = {
        "type": "event_callback",
        "event_id": "Ev999",
        "event": {"type": "message", "text": "injected"},
    }
    req = _BodyRequest(payload)
    import time
    req.headers["X-Slack-Request-Timestamp"] = str(int(time.time()))
    resp = await channel._handle_webhook(req)  # noqa: SLF001
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_msteams_enqueue_dedupes_retried_activity_id() -> None:
    channel = MSTeamsChannel(MSTeamsChannelConfig())
    msg = IncomingMessage(
        sender_id="u1",
        channel_id="conv1",
        content="make a deck",
        metadata={"activity_id": "activity-1"},
    )

    channel.enqueue(msg)
    channel.enqueue(msg)

    assert channel._queue.qsize() == 1  # noqa: SLF001
    assert (await channel.receive()).content == "make a deck"


@pytest.mark.asyncio
async def test_discord_gateway_dedupes_replayed_message_create() -> None:
    channel = DiscordChannel(DiscordChannelConfig(token="token"))
    payload = {
        "id": "message-1",
        "channel_id": "channel-1",
        "content": "hello",
        "author": {"id": "user-1"},
        "mentions": [],
        "attachments": [],
    }

    await channel._handle_dispatch("MESSAGE_CREATE", payload)  # noqa: SLF001
    await channel._handle_dispatch("MESSAGE_CREATE", payload)  # noqa: SLF001

    assert channel._queue.qsize() == 1  # noqa: SLF001
    assert (await channel.receive()).content == "hello"
