"""End-to-end: a reminder job survives the chat it was created from going away.

Unlike the unit tests next door, nothing here is a stand-in for the code under
test — this drives the real ``SessionManager`` over real SQLite, the real
``mirror_cron_result_to_session`` the gateway wires in, the real
``DeliveryChain``, and the real reminder handler
(``make_static_message_handler``), which is the thing that raises
``RuntimeError`` and marks the run failed.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from agentos.gateway.boot import mirror_cron_result_to_session
from agentos.scheduler.delivery import DeliveryChain
from agentos.scheduler.handlers import make_static_message_handler
from agentos.scheduler.payloads import make_reminder_payload
from agentos.scheduler.types import CronJob, DeliveryConfig, DeliveryMode, SessionTarget
from agentos.session.manager import SessionManager
from agentos.session.storage import SessionStorage

ORIGIN_KEY = "agent:main:webchat:the-chat-i-made-it-from"


@pytest_asyncio.fixture
async def session_stack():
    """``(manager, storage)`` — deletion lives on storage, as in rpc_sessions."""
    storage = SessionStorage(":memory:")
    await storage.connect()
    yield SessionManager(storage, inject_time_prefix=False), storage
    await storage.close()


def _reminder_job() -> CronJob:
    """Exactly what the web UI builds for a default reminder."""
    return CronJob(
        id="job-e2e",
        name="uống nước",
        session_target=SessionTarget.ISOLATED,
        origin_session_key=ORIGIN_KEY,
        payload=make_reminder_payload("Nhắc: uống nước"),
        delivery=DeliveryConfig(mode=DeliveryMode.NONE),
    )


def _chain_for(manager: SessionManager) -> DeliveryChain:
    """Wire the chain the way gateway boot does."""

    async def forwarder(*, origin_session_key: str, text: str, provenance: dict) -> bool:
        entry = await mirror_cron_result_to_session(
            manager, origin_session_key, text, provenance
        )
        return entry is not None

    return DeliveryChain(session_forwarder=forwarder)


@pytest.mark.asyncio
async def test_reminder_mirrors_into_the_origin_chat_while_it_exists(session_stack) -> None:
    manager, _ = session_stack
    await manager.create(ORIGIN_KEY)
    handler = make_static_message_handler(_chain_for(manager))

    result = await handler(_reminder_job())

    assert "fwd:delivered" in result.delivery_status
    transcript = await manager.get_transcript(ORIGIN_KEY)
    assert [e.content for e in transcript] == ["Nhắc: uống nước"]
    assert transcript[0].provenance_kind == "cron"


@pytest.mark.asyncio
async def test_reminder_survives_the_origin_chat_being_deleted(session_stack) -> None:
    """The regression: this used to raise RuntimeError and fail the run."""
    manager, storage = session_stack
    await manager.create(ORIGIN_KEY)
    await storage.delete_session(ORIGIN_KEY)
    handler = make_static_message_handler(_chain_for(manager))

    result = await handler(_reminder_job())

    assert "fwd:origin_gone" in result.delivery_status
    assert result.summary == "Nhắc: uống nước"


@pytest.mark.asyncio
async def test_reminder_survives_an_origin_chat_that_never_existed(session_stack) -> None:
    """A job restored from an older database whose session rows are long gone."""
    manager, _ = session_stack
    handler = make_static_message_handler(_chain_for(manager))

    result = await handler(_reminder_job())

    assert "fwd:origin_gone" in result.delivery_status


@pytest.mark.asyncio
async def test_the_pre_fix_wiring_really_did_fail_the_run(session_stack) -> None:
    """Pins the root cause, so a regression is recognisable rather than mysterious.

    This reconstructs the wiring as it shipped before the fix — appending
    straight to the transcript with no existence check — against the real
    SessionManager. The resulting ``KeyError: Session not found`` is what the
    delivery chain turned into ``forward_failed``, and the reminder handler
    into a failed run. If someone drops the lookup again, this documents the
    exact behaviour that returns.
    """
    manager, storage = session_stack
    await manager.create(ORIGIN_KEY)
    await storage.delete_session(ORIGIN_KEY)

    async def pre_fix_forwarder(*, origin_session_key: str, text: str, provenance: dict) -> None:
        await manager.append_message(
            origin_session_key, role="assistant", content=text, provenance=provenance
        )

    handler = make_static_message_handler(DeliveryChain(session_forwarder=pre_fix_forwarder))

    with pytest.raises(RuntimeError, match="session delivery failed"):
        await handler(_reminder_job())


@pytest.mark.asyncio
async def test_mirror_helper_appends_only_to_a_live_session(session_stack) -> None:
    manager, storage = session_stack
    await manager.create(ORIGIN_KEY)

    entry = await mirror_cron_result_to_session(manager, ORIGIN_KEY, "hi", {"kind": "cron"})
    assert entry is not None

    await storage.delete_session(ORIGIN_KEY)
    gone = await mirror_cron_result_to_session(manager, ORIGIN_KEY, "hi again", {"kind": "cron"})
    assert gone is None
