"""Shape checks for a cron job's delivery recipient.

The bug behind these: a session key (``agent:main:telegram:direct:1245463966``)
was accepted as a Telegram ``channelId``. Telegram answers "chat not found" for
it, so the job only failed ten minutes later, at delivery time.
"""

import pytest

from agentos.scheduler.delivery_targets import validate_channel_target

SESSION_KEY = "agent:main:telegram:direct:1245463966"


@pytest.mark.parametrize(
    "channel",
    ["telegram", "slack", "discord", "msteams", "unknown-channel"],
)
def test_session_keys_are_rejected_for_every_channel(channel: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_channel_target(channel, SESSION_KEY)
    assert "session key" in str(excinfo.value)


@pytest.mark.parametrize(
    "key",
    [
        "agent:main:telegram:direct:1245463966",
        "cron:6b23bfa7:run:deadbeef",
        "webchat:abc123",
        "session:main",
    ],
)
def test_every_session_key_prefix_is_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        validate_channel_target("slack", key)


def test_rejection_suggests_the_id_that_would_have_worked() -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_channel_target("telegram", SESSION_KEY)
    assert "1245463966" in str(excinfo.value)


@pytest.mark.parametrize("target", ["1245463966", "-1001234567890", "@andreapn", "  42  "])
def test_telegram_accepts_chat_ids_and_usernames(target: str) -> None:
    validate_channel_target("telegram", target)


@pytest.mark.parametrize("target", ["C-team-alerts", "not a chat", "12ab", "@", "+1245463966"])
def test_telegram_rejects_anything_that_is_not_a_chat_id(target: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_channel_target("telegram", target)
    assert "chat id" in str(excinfo.value)


def test_other_channels_keep_their_own_id_shapes() -> None:
    # Slack channel ids, a Discord snowflake, and an MS Teams conversation id —
    # the last one has colons, which is why the guard is a prefix whitelist and
    # not a colon count.
    validate_channel_target("slack", "C0123ABCDEF")
    validate_channel_target("slack", "#team-alerts")
    validate_channel_target("discord", "1103283746372617")
    validate_channel_target("msteams", "19:meeting_NGY3@thread.v2")


def test_empty_target_is_left_alone() -> None:
    # Delivery falls back to the channel's configured default chat.
    validate_channel_target("telegram", "")
    validate_channel_target("slack", "   ")
