from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentos.channels.telegram import TelegramChannel, TelegramChannelConfig
from agentos.channels.types import Attachment, IncomingMessage, OutgoingMessage
from agentos.gateway.channel_dispatch import _ingest_channel_message_attachments


def test_telegram_voice_and_video_note_parsing() -> None:
    # 1. Test voice parsing with duration
    channel = TelegramChannel(TelegramChannelConfig(token="test-token"))
    msg = channel.parse_incoming({
        "message": {
            "message_id": 101,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 456, "first_name": "Alice"},
            "voice": {
                "file_id": "voice-file-id",
                "file_unique_id": "voice-unique",
                "duration": 45,
                "mime_type": "audio/ogg",
                "file_size": 2048,
            }
        }
    })
    assert msg.content == "[voice]"
    assert len(msg.attachments) == 1
    assert msg.attachments[0].metadata["telegram_media_kind"] == "voice"
    assert msg.attachments[0].metadata["duration"] == 45
    assert msg.attachments[0].metadata["telegram_file_id"] == "voice-file-id"

    # 2. Test video_note parsing with duration
    msg_vn = channel.parse_incoming({
        "message": {
            "message_id": 102,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 456, "first_name": "Alice"},
            "video_note": {
                "file_id": "vn-file-id",
                "file_unique_id": "vn-unique",
                "duration": 12,
                "file_size": 4096,
            }
        }
    })
    assert msg_vn.content == "[video_note]"
    assert len(msg_vn.attachments) == 1
    assert msg_vn.attachments[0].metadata["telegram_media_kind"] == "video_note"
    assert msg_vn.attachments[0].metadata["duration"] == 12
    assert msg_vn.attachments[0].metadata["telegram_file_id"] == "vn-file-id"

    # 3. Test reply metadata parsing
    msg_reply = channel.parse_incoming({
        "message": {
            "message_id": 103,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 456, "first_name": "Alice"},
            "text": "Hello",
            "reply_to_message": {
                "message_id": 99,
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 789, "username": "bot_user"},
                "text": "Prior message",
            }
        }
    })
    assert msg_reply.metadata["reply_to_message_id"] == "99"
    assert msg_reply.metadata["reply_to_message_from_id"] == "789"
    assert msg_reply.metadata["reply_to_message_from_username"] == "bot_user"


def test_telegram_is_group_mentioned_on_reply() -> None:
    channel = TelegramChannel(TelegramChannelConfig(token="test-token"))
    channel.bot_user_id = "789"
    channel.bot_username = "my_bot"

    # Reply to bot by ID
    msg_reply_id = IncomingMessage(
        sender_id="456",
        channel_id="123",
        content="[voice]",
        metadata={
            "is_group": True,
            "reply_to_message_from_id": "789",
        }
    )
    assert channel.is_group_mentioned(msg_reply_id) is True

    # Reply to bot by username
    msg_reply_username = IncomingMessage(
        sender_id="456",
        channel_id="123",
        content="[voice]",
        metadata={
            "is_group": True,
            "reply_to_message_from_username": "my_bot",
        }
    )
    assert channel.is_group_mentioned(msg_reply_username) is True

    # Unrelated message - no mention
    msg_no_mention = IncomingMessage(
        sender_id="456",
        channel_id="123",
        content="[voice]",
        metadata={
            "is_group": True,
        }
    )
    assert channel.is_group_mentioned(msg_no_mention) is False


@pytest.mark.asyncio
async def test_channel_dispatch_transcription_success() -> None:
    channel = MagicMock()
    channel.config = TelegramChannelConfig(token="test-token", transcribe_voice=True)
    channel.resolve_inbound_attachment = AsyncMock(
        side_effect=lambda att: att.model_copy(update={"data": b"fake-ogg-bytes"})
    )

    msg = IncomingMessage(
        sender_id="456",
        channel_id="123",
        content="[voice]",
        attachments=[
            Attachment(
                name="voice.ogg",
                mime_type="audio/ogg",
                size=120,
                metadata={
                    "telegram_media_kind": "voice",
                    "telegram_file_id": "voice-id",
                    "duration": 10,
                }
            )
        ]
    )

    config = MagicMock()
    config.audio.enabled = True
    route_envelope = MagicMock()
    route_envelope.channel_id = "123"

    with patch(
        "agentos.gateway.audio_transcription.transcribe_audio_bytes",
        new_callable=AsyncMock,
    ) as mock_stt:
        mock_stt.return_value = MagicMock(
            text="hello from voice note",
            provider="elevenlabs",
            model="scribe_v2",
            language_code="en",
        )

        await _ingest_channel_message_attachments(
            channel=channel,
            msg=msg,
            config=config,
            route_envelope=route_envelope,
        )

        # Assert voice attachment transcribed and removed from attachments list
        assert msg.content == "hello from voice note"
        assert len(msg.attachments) == 0
        assert msg.metadata["transcribed_from"] == "voice"
        assert msg.metadata["duration"] == 10
        assert msg.metadata["telegram_file_id"] == "voice-id"
        assert msg.metadata["language_code"] == "en"


@pytest.mark.asyncio
async def test_channel_dispatch_transcription_success_with_caption() -> None:
    channel = MagicMock()
    channel.config = TelegramChannelConfig(token="test-token", transcribe_voice=True)
    channel.resolve_inbound_attachment = AsyncMock(
        side_effect=lambda att: att.model_copy(update={"data": b"fake-ogg-bytes"})
    )

    msg = IncomingMessage(
        sender_id="456",
        channel_id="123",
        content="This is the caption",
        attachments=[
            Attachment(
                name="voice.ogg",
                mime_type="audio/ogg",
                size=120,
                metadata={
                    "telegram_media_kind": "voice",
                    "telegram_file_id": "voice-id",
                    "duration": 10,
                }
            )
        ]
    )

    config = MagicMock()
    config.audio.enabled = True
    route_envelope = MagicMock()

    with patch(
        "agentos.gateway.audio_transcription.transcribe_audio_bytes",
        new_callable=AsyncMock,
    ) as mock_stt:
        mock_stt.return_value = MagicMock(
            text="hello from voice note",
            provider="elevenlabs",
            model="scribe_v2",
            language_code="en",
        )

        await _ingest_channel_message_attachments(
            channel=channel,
            msg=msg,
            config=config,
            route_envelope=route_envelope,
        )

        # Caption and voice note combined
        assert msg.content == "This is the caption\n\nhello from voice note"
        assert len(msg.attachments) == 0


@pytest.mark.asyncio
async def test_channel_dispatch_transcription_provider_failure() -> None:
    channel = MagicMock()
    channel.config = TelegramChannelConfig(token="test-token", transcribe_voice=True)
    channel.resolve_inbound_attachment = AsyncMock(
        side_effect=lambda att: att.model_copy(update={"data": b"fake-ogg-bytes"})
    )
    channel.send = AsyncMock()

    msg = IncomingMessage(
        sender_id="456",
        channel_id="123",
        content="[voice]",
        attachments=[
            Attachment(
                name="voice.ogg",
                mime_type="audio/ogg",
                size=120,
                metadata={
                    "telegram_media_kind": "voice",
                    "telegram_file_id": "voice-id",
                    "duration": 10,
                }
            )
        ]
    )

    config = MagicMock()
    config.audio.enabled = True
    route_envelope = MagicMock()
    route_envelope.channel_id = "123"
    route_envelope.thread_id = None

    with patch(
        "agentos.gateway.audio_transcription.transcribe_audio_bytes",
        new_callable=AsyncMock,
    ) as mock_stt:
        mock_stt.side_effect = RuntimeError("STT provider is down")

        await _ingest_channel_message_attachments(
            channel=channel,
            msg=msg,
            config=config,
            route_envelope=route_envelope,
        )

        # Check content is unchanged (placeholder) and error message sent to user
        assert msg.content == "[voice]"
        channel.send.assert_called_once()
        sent_msg = channel.send.call_args[0][0]
        assert isinstance(sent_msg, OutgoingMessage)
        assert "provider error" in sent_msg.content


@pytest.mark.asyncio
async def test_channel_dispatch_transcription_oversized_duration() -> None:
    channel = MagicMock()
    # 5s max duration config
    channel.config = TelegramChannelConfig(
        token="test-token", transcribe_voice=True, max_voice_duration_s=5
    )
    channel.resolve_inbound_attachment = AsyncMock(
        side_effect=lambda att: att.model_copy(update={"data": b"fake-ogg-bytes"})
    )
    channel.send = AsyncMock()

    msg = IncomingMessage(
        sender_id="456",
        channel_id="123",
        content="[voice]",
        attachments=[
            Attachment(
                name="voice.ogg",
                mime_type="audio/ogg",
                size=120,
                metadata={
                    "telegram_media_kind": "voice",
                    "telegram_file_id": "voice-id",
                    "duration": 10,  # exceeds 5s max
                }
            )
        ]
    )

    config = MagicMock()
    config.audio.enabled = True
    route_envelope = MagicMock()
    route_envelope.channel_id = "123"
    route_envelope.thread_id = None

    with patch(
        "agentos.gateway.audio_transcription.transcribe_audio_bytes",
        new_callable=AsyncMock,
    ) as mock_stt:
        await _ingest_channel_message_attachments(
            channel=channel,
            msg=msg,
            config=config,
            route_envelope=route_envelope,
        )

        # No transcription should be called
        mock_stt.assert_not_called()
        assert msg.content == "[voice]"
        channel.send.assert_called_once()
        sent_msg = channel.send.call_args[0][0]
        assert "exceeds the maximum duration" in sent_msg.content


@pytest.mark.asyncio
async def test_channel_dispatch_transcription_disabled() -> None:
    channel = MagicMock()
    # transcribe_voice is False by default
    channel.config = TelegramChannelConfig(token="test-token")
    channel.resolve_inbound_attachment = AsyncMock(
        side_effect=lambda att: att.model_copy(update={"data": b"fake-ogg-bytes"})
    )

    msg = IncomingMessage(
        sender_id="456",
        channel_id="123",
        content="[voice]",
        attachments=[
            Attachment(
                name="voice.ogg",
                mime_type="audio/ogg",
                size=120,
                metadata={
                    "telegram_media_kind": "voice",
                    "telegram_file_id": "voice-id",
                    "duration": 10,
                }
            )
        ]
    )

    config = MagicMock()
    config.audio.enabled = True
    route_envelope = MagicMock()

    with patch(
        "agentos.gateway.audio_transcription.transcribe_audio_bytes",
        new_callable=AsyncMock,
    ) as mock_stt:
        await _ingest_channel_message_attachments(
            channel=channel,
            msg=msg,
            config=config,
            route_envelope=route_envelope,
        )

        mock_stt.assert_not_called()
        assert msg.content == "[voice]"
