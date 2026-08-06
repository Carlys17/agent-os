"""``channels.deliveryTargets`` — the recipients we can name without guessing.

The cron form uses this to offer a dropdown instead of a free-text box. A
channel that is absent from the map is the signal that the caller has to ask
the operator to type the id.
"""

import asyncio
from types import SimpleNamespace

from agentos.gateway.rpc import RpcContext
from agentos.gateway.rpc_channels import _handle_channels_delivery_targets


class _FakeAdapter:
    def __init__(self, snapshot: dict) -> None:
        self._snapshot = snapshot

    def access_snapshot(self) -> dict:
        return self._snapshot


class _FakeChannelManager:
    def __init__(self, adapters: dict) -> None:
        self._adapters = adapters

    def get(self, name):
        return self._adapters.get(name)


def _ctx(channels: list[dict], adapters: dict) -> RpcContext:
    ctx = RpcContext(conn_id="test")
    ctx.config = SimpleNamespace(channels=SimpleNamespace(channels=list(channels)))
    ctx.channel_manager = _FakeChannelManager(adapters)
    return ctx


PAIRED = {
    "pending": [],
    "paired": [
        {
            "sender_id": "1245463966",
            "chat_id": "1245463966",
            "display_name": "AndreaPN | 404AI Labs",
            "username": "andreapn_dackielabs",
        }
    ],
    "locked_until": 0.0,
    "groups_enabled": True,
    "group_chat_ids": ["-1001234567890"],
    "group_mention_required": True,
}


def test_paired_users_become_dm_targets_labelled_for_a_human() -> None:
    ctx = _ctx(
        [{"name": "telegram", "type": "telegram", "enabled": True}],
        {"telegram": _FakeAdapter(PAIRED)},
    )
    result = asyncio.run(_handle_channels_delivery_targets(None, ctx))

    dms = [t for t in result["targets"]["telegram"] if t["kind"] == "dm"]
    assert dms == [
        {
            "id": "1245463966",
            "label": "AndreaPN | 404AI Labs (@andreapn_dackielabs)",
            "kind": "dm",
        }
    ]


def test_configured_group_chats_are_offered_too() -> None:
    ctx = _ctx(
        [{"name": "telegram", "type": "telegram", "enabled": True}],
        {"telegram": _FakeAdapter(PAIRED)},
    )
    result = asyncio.run(_handle_channels_delivery_targets(None, ctx))

    groups = [t for t in result["targets"]["telegram"] if t["kind"] == "group"]
    assert groups == [{"id": "-1001234567890", "label": "-1001234567890", "kind": "group"}]


def test_a_channel_we_know_nothing_about_is_absent() -> None:
    # Slack has no pairing store, so the caller must keep its free-text input.
    ctx = _ctx(
        [
            {"name": "telegram", "type": "telegram", "enabled": True},
            {"name": "slack", "type": "slack", "enabled": True},
        ],
        {"telegram": _FakeAdapter(PAIRED)},
    )
    result = asyncio.run(_handle_channels_delivery_targets(None, ctx))

    assert "slack" not in result["targets"]
    assert "telegram" in result["targets"]


def test_a_telegram_channel_with_nobody_paired_is_absent() -> None:
    empty = {**PAIRED, "paired": [], "group_chat_ids": []}
    ctx = _ctx(
        [{"name": "telegram", "type": "telegram", "enabled": True}],
        {"telegram": _FakeAdapter(empty)},
    )
    result = asyncio.run(_handle_channels_delivery_targets(None, ctx))

    assert result["targets"] == {}


def test_a_paired_user_without_a_username_falls_back_to_the_display_name() -> None:
    snapshot = {
        **PAIRED,
        "paired": [{"chat_id": "42", "display_name": "Someone", "username": ""}],
        "group_chat_ids": [],
    }
    ctx = _ctx(
        [{"name": "telegram", "type": "telegram", "enabled": True}],
        {"telegram": _FakeAdapter(snapshot)},
    )
    result = asyncio.run(_handle_channels_delivery_targets(None, ctx))

    assert result["targets"]["telegram"] == [{"id": "42", "label": "Someone", "kind": "dm"}]
