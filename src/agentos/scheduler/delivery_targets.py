"""What a cron job's delivery recipient is allowed to look like.

A ``channelId`` reaches the adapter untouched — Telegram, for instance, puts it
straight into ``sendMessage``'s ``chat_id``. A wrong value is therefore not
caught until the job next fires, ten minutes or a day later, and all the
operator sees then is "delivery failed". These checks move that discovery to the
moment the job is saved.
"""

from __future__ import annotations

import re

#: Prefixes of AgentOS *session* keys. A session key names a conversation
#: inside AgentOS; a channel id names a chat on the provider's side. They are
#: routinely confused because both are visible in the UI, and the session key is
#: the one that happens to be selectable text.
#:
#: Matched as prefixes rather than by counting colons on purpose: a genuine MS
#: Teams conversation id looks like ``19:meeting_NGY3@thread.v2``.
_SESSION_KEY_PREFIXES = ("agent:", "cron:", "webchat:", "session:")

_TELEGRAM_CHAT_ID = re.compile(r"^-?\d+$")
_TELEGRAM_USERNAME = re.compile(r"^@[A-Za-z0-9_]{3,}$")


def _suggest_from_session_key(value: str) -> str:
    """The trailing segment of a session key — usually the id that was meant."""
    return value.rsplit(":", 1)[-1].strip()


def validate_channel_target(channel_name: str, channel_id: str) -> None:
    """Raise ``ValueError`` when *channel_id* cannot be a *channel_name* recipient.

    An empty target is legal: delivery falls back to the channel's configured
    default chat.
    """
    target = (channel_id or "").strip()
    if not target:
        return

    if target.startswith(_SESSION_KEY_PREFIXES):
        suggestion = _suggest_from_session_key(target)
        hint = f" — use {suggestion}" if suggestion and suggestion != target else ""
        raise ValueError(
            f'delivery target "{target}" is a session key, not a '
            f"{channel_name or 'channel'} chat id{hint}"
        )

    if (channel_name or "").strip().lower() == "telegram":
        if not (_TELEGRAM_CHAT_ID.match(target) or _TELEGRAM_USERNAME.match(target)):
            raise ValueError(
                f'delivery target "{target}" is not a telegram chat id — '
                "pass the numeric chat id (negative for groups) or @username"
            )
