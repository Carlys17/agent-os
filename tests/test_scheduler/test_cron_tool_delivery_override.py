"""A cron job created from chat can name where it announces.

Drives the contract of the tool's ``delivery`` parameter:
- Omitted, delivery is still inferred from the calling conversation — the
  behaviour every existing job depends on.
- ``mode='channel'`` pins the job to a named channel and recipient, so
  "every morning post the summary to the ops group" no longer requires opening
  the Web UI or moving to that chat first.
- ``mode='none'`` schedules a job that announces nowhere.
- A recipient the channel cannot use is rejected at save time, not at the next
  fire, and an AgentOS session key passed as a chat id says so.
- Redirecting delivery to another channel stays an operator action: a chat
  participant cannot aim scheduled output at a room they were never in.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import pytest

import agentos.tools.builtin.control as control_mod
from agentos.scheduler.types import CronJob, DeliveryConfig, ReplyTargetSnapshot
from agentos.tools.builtin.control import cron as cron_tool
from agentos.tools.types import (
    CallerKind,
    InteractionMode,
    SafeToolError,
    ToolContext,
    current_tool_context,
)


@contextmanager
def _with_ctx(ctx: ToolContext):
    token = current_tool_context.set(ctx)
    try:
        yield
    finally:
        current_tool_context.reset(token)


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[CronJob] = []
        self.add_calls: list[dict[str, Any]] = []

    async def list_jobs(self) -> list[CronJob]:
        return list(self.jobs)

    async def add_job(self, **kwargs: Any) -> CronJob:
        self.add_calls.append(kwargs)
        job = CronJob(
            id=f"job-{len(self.jobs) + 1}",
            name=kwargs["name"],
            cron_expr=kwargs.get("schedule_value", ""),
            schedule_raw=kwargs.get("schedule_value", ""),
            handler_key=kwargs["handler_key"],
            payload=kwargs["payload"],
            session_target=kwargs["session_target"],
            session_key=kwargs["session_key"],
            delivery=kwargs.get("delivery") or DeliveryConfig(),
        )
        self.jobs.append(job)
        return job

    async def update_job(self, job_id: str, **patch: Any) -> CronJob | None:
        for job in self.jobs:
            if job.id == job_id:
                for key, value in patch.items():
                    setattr(job, key, value)
                return job
        return None

    async def get_job(self, job_id: str) -> CronJob | None:
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    async def remove_job(self, job_id: str) -> bool:
        return False

    async def run_job_now(self, job_id: str) -> Any:  # pragma: no cover - unused
        raise NotImplementedError

    async def get_runs(self, job_id: str, limit: int = 20) -> list[Any]:
        return []


def _web_ctx(session_key: str = "agent:main:webchat:u1") -> ToolContext:
    return ToolContext(
        caller_kind=CallerKind.WEB,
        interaction_mode=InteractionMode.INTERACTIVE,
        session_key=session_key,
        agent_id="main",
    )


def _channel_ctx(session_key: str = "agent:main:telegram:direct:42") -> ToolContext:
    return ToolContext(
        caller_kind=CallerKind.CHANNEL,
        interaction_mode=InteractionMode.INTERACTIVE,
        session_key=session_key,
        agent_id="main",
        channel_kind="telegram",
        channel_id="42",
        sender_id="tg-user-1",
        source_kind="channel",
        source_name="telegram",
    )


@pytest.fixture
def fake_scheduler(monkeypatch):
    """Scheduler stub plus a session store that knows the caller's last channel.

    ``infer_delivery`` itself is left real: the override this suite exercises is
    its own first priority, and stubbing it out would test nothing.
    """
    sched = _FakeScheduler()
    control_mod.set_scheduler(sched)

    class _Node:
        last_channel = "webchat"
        last_to = "u1"
        last_account_id = ""
        last_thread_id = ""

    class _Storage:
        async def get_session(self, session_key: str) -> _Node:
            return _Node()

    from agentos.tools.builtin import sessions as sessions_mod

    class _Manager:
        _storage = _Storage()

    monkeypatch.setattr(sessions_mod, "_get_session_manager", lambda: _Manager())
    yield sched
    control_mod.set_scheduler(None)  # type: ignore[arg-type]


async def _add(**kwargs: Any) -> dict[str, Any]:
    raw = await cron_tool(
        action="add",
        schedule={"kind": "cron", "expr": "0 9 * * *"},
        task="Post the daily summary",
        job_kind="agent_turn",
        session_target="isolated",
        **kwargs,
    )
    return json.loads(raw)


# --- Default behaviour is untouched ---------------------------------------


async def test_delivery_omitted_still_infers_the_calling_conversation(fake_scheduler):
    with _with_ctx(_web_ctx()):
        resp = await _add()

    delivery = fake_scheduler.add_calls[-1]["delivery"]
    assert delivery.mode.value == "origin"
    assert delivery.channel_name == "webchat"
    assert resp["delivery"]["mode"] == "origin"


async def test_empty_delivery_object_is_treated_as_omitted(fake_scheduler):
    with _with_ctx(_web_ctx()):
        await _add(delivery={})

    assert fake_scheduler.add_calls[-1]["delivery"].mode.value == "origin"


async def test_mode_origin_is_the_inferred_destination(fake_scheduler):
    with _with_ctx(_web_ctx()):
        await _add(delivery={"mode": "origin"})

    delivery = fake_scheduler.add_calls[-1]["delivery"]
    assert delivery.mode.value == "origin"
    assert delivery.channel_name == "webchat"


# --- Naming a channel recipient -------------------------------------------


async def test_web_caller_can_target_a_telegram_group(fake_scheduler):
    """The reported case: created from webchat, delivered to a Telegram group."""
    with _with_ctx(_web_ctx()):
        resp = await _add(
            delivery={
                "mode": "channel",
                "channel_name": "telegram",
                "channel_id": "-1001234567890",
            }
        )

    delivery = fake_scheduler.add_calls[-1]["delivery"]
    assert delivery.mode.value == "channel"
    assert delivery.channel_name == "telegram"
    assert delivery.channel_id == "-1001234567890"
    assert resp["delivery"] == {
        "mode": "channel",
        "channel_name": "telegram",
        "channel_id": "-1001234567890",
    }


async def test_camel_case_delivery_fields_are_accepted(fake_scheduler):
    """The RPC wire spells these in camelCase; a model may copy that shape."""
    with _with_ctx(_web_ctx()):
        await _add(
            delivery={
                "mode": "channel",
                "channelName": "telegram",
                "channelId": "@ops_room",
                "accountId": "bot-2",
                "threadId": "7",
                "bestEffort": True,
            }
        )

    delivery = fake_scheduler.add_calls[-1]["delivery"]
    assert delivery.channel_name == "telegram"
    assert delivery.channel_id == "@ops_room"
    assert delivery.account_id == "bot-2"
    assert delivery.thread_id == "7"
    assert delivery.best_effort is True


async def test_channel_name_without_mode_still_targets_that_channel(fake_scheduler):
    with _with_ctx(_web_ctx()):
        await _add(delivery={"channel_name": "slack", "channel_id": "C0123ABCDEF"})

    delivery = fake_scheduler.add_calls[-1]["delivery"]
    assert delivery.mode.value == "channel"
    assert delivery.channel_id == "C0123ABCDEF"


async def test_empty_recipient_keeps_the_channel_default(fake_scheduler):
    """An empty target is legal — delivery falls back to the channel default."""
    with _with_ctx(_web_ctx()):
        await _add(delivery={"mode": "channel", "channel_name": "telegram"})

    delivery = fake_scheduler.add_calls[-1]["delivery"]
    assert delivery.mode.value == "channel"
    assert delivery.channel_id == ""


async def test_targeted_job_does_not_inherit_the_callers_reply_snapshot(fake_scheduler):
    """The override means "not here" — the calling chat must not be re-attached."""
    ctx = ToolContext(
        caller_kind=CallerKind.WEB,
        interaction_mode=InteractionMode.INTERACTIVE,
        session_key="agent:main:webchat:u1",
        agent_id="main",
        channel_kind="webchat",
        channel_id="u1",
    )
    with _with_ctx(ctx):
        await _add(
            delivery={
                "mode": "channel",
                "channel_name": "telegram",
                "channel_id": "-1001234567890",
            }
        )

    delivery = fake_scheduler.add_calls[-1]["delivery"]
    assert delivery.originating_reply_target is None


# --- Silencing a job -------------------------------------------------------


async def test_mode_none_schedules_a_silent_job(fake_scheduler):
    with _with_ctx(_web_ctx()):
        resp = await _add(delivery={"mode": "none"})

    assert fake_scheduler.add_calls[-1]["delivery"].mode.value == "none"
    assert resp["delivery"]["mode"] == "none"


async def test_channel_caller_may_silence_its_own_job(fake_scheduler):
    """Reducing delivery needs no operator gate; only redirecting it does."""
    with _with_ctx(_channel_ctx()):
        await _add(delivery={"mode": "none"})

    assert fake_scheduler.add_calls[-1]["delivery"].mode.value == "none"


# --- Rejections ------------------------------------------------------------


async def test_channel_caller_cannot_redirect_to_another_channel(fake_scheduler):
    with _with_ctx(_channel_ctx()), pytest.raises(SafeToolError) as exc:
        await _add(
            delivery={
                "mode": "channel",
                "channel_name": "telegram",
                "channel_id": "-1009999999999",
            }
        )

    assert "interactive CLI or Web caller" in str(exc.value)
    assert fake_scheduler.add_calls == []


async def test_session_key_as_recipient_is_rejected_at_save_time(fake_scheduler):
    with _with_ctx(_web_ctx()), pytest.raises(SafeToolError) as exc:
        await _add(
            delivery={
                "mode": "channel",
                "channel_name": "telegram",
                "channel_id": "agent:main:telegram:direct:1245463966",
            }
        )

    message = str(exc.value)
    assert "session key" in message
    assert "1245463966" in message
    assert fake_scheduler.add_calls == []


async def test_non_numeric_telegram_recipient_is_rejected(fake_scheduler):
    with _with_ctx(_web_ctx()), pytest.raises(SafeToolError) as exc:
        await _add(
            delivery={
                "mode": "channel",
                "channel_name": "telegram",
                "channel_id": "the ops group",
            }
        )

    assert "telegram chat id" in str(exc.value)


async def test_channel_mode_requires_a_channel_name(fake_scheduler):
    with _with_ctx(_web_ctx()), pytest.raises(SafeToolError) as exc:
        await _add(delivery={"mode": "channel", "channel_id": "-100123"})

    assert "channel_name" in str(exc.value)


async def test_unknown_delivery_mode_is_rejected(fake_scheduler):
    with _with_ctx(_web_ctx()), pytest.raises(SafeToolError) as exc:
        await _add(delivery={"mode": "webhook", "channel_name": "telegram"})

    assert "delivery.mode must be" in str(exc.value)


async def test_delivery_must_be_an_object(fake_scheduler):
    with _with_ctx(_web_ctx()), pytest.raises(SafeToolError) as exc:
        await _add(delivery="telegram")  # type: ignore[arg-type]

    assert "'delivery' must be an object" in str(exc.value)


async def test_channel_delivery_is_unavailable_for_main_session_target(fake_scheduler):
    with _with_ctx(_web_ctx()), pytest.raises(SafeToolError) as exc:
        await cron_tool(
            action="add",
            schedule={"kind": "cron", "expr": "0 9 * * *"},
            task="ping",
            job_kind="system_event",
            session_target="main",
            delivery={
                "mode": "channel",
                "channel_name": "telegram",
                "channel_id": "-1001234567890",
            },
        )

    assert "session_target=main" in str(exc.value)


# --- Sanity: the summary helper reads the saved job, not the request -------


def test_delivery_summary_of_an_unset_config_is_none() -> None:
    assert control_mod._cron_delivery_summary(None) == {"mode": "none"}


def test_delivery_summary_omits_empty_fields() -> None:
    summary = control_mod._cron_delivery_summary(
        DeliveryConfig(
            mode=control_mod.DeliveryMode.CHANNEL,
            channel_name="telegram",
            channel_id="-100123",
            originating_reply_target=ReplyTargetSnapshot(channel_name="webchat"),
        )
    )
    assert summary == {
        "mode": "channel",
        "channel_name": "telegram",
        "channel_id": "-100123",
    }
