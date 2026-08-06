"""The reaper has to walk the whole session store, not just its first page.

``SessionStorage.list_sessions`` defaults to ``limit=100, ORDER BY updated_at
DESC``. The reaper used to call it with no arguments, so it only ever saw the 100
*most recently updated* sessions — exactly the ones that are not expired. Past a
hundred sessions it silently stopped reaping anything.

These run against the real ``SessionStorage`` rather than a fake: a fake with a
permissive ``list_sessions(**kwargs)`` would have passed the whole time.
"""

from __future__ import annotations

import time

import pytest

from agentos.scheduler.reaper import SessionReaper
from agentos.session.models import SessionNode
from agentos.session.storage import SessionStorage

DAY_MS = 86_400_000


@pytest.fixture
async def storage():
    store = SessionStorage(":memory:")
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


def _node(key: str, updated_at: int) -> SessionNode:
    return SessionNode(
        session_key=key,
        session_id=key.replace(":", "-"),
        agent_id="main",
        created_at=updated_at,
        updated_at=updated_at,
    )


async def _keys(store: SessionStorage) -> set[str]:
    return {s.session_key for s in await store.list_sessions(limit=10_000)}


async def test_expired_cron_session_is_reaped_from_beyond_the_first_page(storage) -> None:
    now_ms = int(time.time() * 1000)

    # 150 fresh sessions, all newer than the expired one, so DESC ordering pushes
    # the stale cron session onto the second page.
    for i in range(150):
        await storage.upsert_session(_node(f"agent:main:webchat:s{i:03d}", now_ms - i))
    stale = "cron:job-1:run:deadbeef"
    await storage.upsert_session(_node(stale, now_ms - 3 * DAY_MS))

    assert len(await storage.list_sessions()) == 100, "guard: default page is still 100"

    await SessionReaper(storage)._do_reap()

    remaining = await _keys(storage)
    assert stale not in remaining
    assert len(remaining) == 150


async def test_reaper_leaves_fresh_and_non_cron_sessions_alone(storage) -> None:
    now_ms = int(time.time() * 1000)
    fresh_cron = "cron:job-1:run:aaaa1111"
    old_agent = "agent:main:webchat:ancient"
    # Three parts, so SessionTarget.SESSION keys are out of the reaper's reach.
    old_shared_cron = "cron:job-1"

    await storage.upsert_session(_node(fresh_cron, now_ms - 60_000))
    await storage.upsert_session(_node(old_agent, now_ms - 30 * DAY_MS))
    await storage.upsert_session(_node(old_shared_cron, now_ms - 30 * DAY_MS))

    await SessionReaper(storage)._do_reap()

    assert await _keys(storage) == {fresh_cron, old_agent, old_shared_cron}


async def test_reaper_sweeps_every_page(storage) -> None:
    now_ms = int(time.time() * 1000)
    # Force more than one page at the real PAGE_SIZE without inserting 500 rows.
    reaper = SessionReaper(storage)
    reaper.PAGE_SIZE = 10

    stale = [f"cron:job-1:run:{i:08x}" for i in range(25)]
    for i, key in enumerate(stale):
        await storage.upsert_session(_node(key, now_ms - 3 * DAY_MS - i))

    await reaper._do_reap()

    assert await _keys(storage) == set()
