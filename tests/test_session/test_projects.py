"""Tests for project CRUD, session membership, and project-scoped search."""

from __future__ import annotations

import pytest
import pytest_asyncio

from agentos.session.manager import ProjectUpdateConflictError, SessionManager
from agentos.session.storage import SessionStorage


@pytest_asyncio.fixture
async def storage():
    store = SessionStorage(":memory:")
    await store.connect()
    yield store
    await store.close()


@pytest_asyncio.fixture
async def manager(storage):
    return SessionManager(storage, inject_time_prefix=False)


@pytest.mark.asyncio
async def test_create_project_and_list_with_session_counts(manager):
    project = await manager.create_project("main", "Research", knowledge="Use Vietnamese.")
    assert project["name"] == "Research"
    assert project["knowledge"] == "Use Vietnamese."
    assert project["agent_id"] == "main"

    await manager.create(
        "agent:main:webchat:aaaa0001", agent_id="main", project_id=project["project_id"]
    )
    rows = await manager.list_projects("main")
    assert [(row["name"], row["session_count"]) for row in rows] == [("Research", 1)]


@pytest.mark.asyncio
async def test_create_project_rejects_duplicate_name_case_insensitive(manager):
    await manager.create_project("main", "Research")
    with pytest.raises(ValueError, match="already exists"):
        await manager.create_project("main", "research")
    # Names are unique globally, not per agent.
    with pytest.raises(ValueError, match="already exists"):
        await manager.create_project("other", "RESEARCH")


@pytest.mark.asyncio
async def test_create_project_rejects_empty_name_and_oversized_knowledge(manager):
    with pytest.raises(ValueError, match="empty"):
        await manager.create_project("main", "   ")
    with pytest.raises(ValueError, match="knowledge exceeds"):
        await manager.create_project(
            "main", "Big", knowledge="x" * (SessionManager.PROJECT_KNOWLEDGE_MAX_CHARS + 1)
        )


@pytest.mark.asyncio
async def test_session_create_with_unknown_project_raises(manager):
    with pytest.raises(KeyError, match="Project not found"):
        await manager.create("agent:main:webchat:aaaa0002", agent_id="main", project_id="missing")


@pytest.mark.asyncio
async def test_move_session_between_projects_and_detach(manager):
    project = await manager.create_project("main", "Research")
    await manager.create("agent:main:webchat:aaaa0003", agent_id="main")

    node = await manager.move_session_to_project(
        "agent:main:webchat:aaaa0003", project["project_id"]
    )
    assert node.project_id == project["project_id"]

    node = await manager.move_session_to_project("agent:main:webchat:aaaa0003", None)
    assert node.project_id is None


@pytest.mark.asyncio
async def test_move_session_across_agents_is_allowed(manager):
    # Projects are cross-agent: a session of any agent may join any project.
    project = await manager.create_project("other", "OtherProj")
    await manager.create("agent:main:webchat:aaaa0004", agent_id="main")
    node = await manager.move_session_to_project(
        "agent:main:webchat:aaaa0004", project["project_id"]
    )
    assert node.project_id == project["project_id"]
    rows = await manager.list_projects()
    assert [(row["name"], row["session_count"]) for row in rows] == [("OtherProj", 1)]


@pytest.mark.asyncio
async def test_update_project_name_and_knowledge(manager):
    project = await manager.create_project("main", "Research", knowledge="v1")
    updated = await manager.update_project(project["project_id"], name="Research 2", knowledge="v2")
    assert updated["name"] == "Research 2"
    assert updated["knowledge"] == "v2"
    assert updated["updated_at"] >= project["updated_at"]


@pytest.mark.asyncio
async def test_update_project_rejects_name_collision(manager):
    await manager.create_project("main", "One")
    other = await manager.create_project("main", "Two")
    with pytest.raises(ValueError, match="already exists"):
        await manager.update_project(other["project_id"], name="one")


@pytest.mark.asyncio
async def test_delete_project_detaches_sessions_but_keeps_them(manager):
    project = await manager.create_project("main", "Research")
    await manager.create(
        "agent:main:webchat:aaaa0005", agent_id="main", project_id=project["project_id"]
    )

    detached = await manager.delete_project(project["project_id"])
    assert detached == 1
    node = await manager.get_session("agent:main:webchat:aaaa0005")
    assert node is not None
    assert node.project_id is None
    assert await manager.get_project(project["project_id"]) is None


@pytest.mark.asyncio
async def test_delete_missing_project_raises(manager):
    with pytest.raises(KeyError, match="Project not found"):
        await manager.delete_project("missing")


@pytest.mark.asyncio
async def test_list_sessions_filters_by_project(manager):
    project = await manager.create_project("main", "Research")
    await manager.create(
        "agent:main:webchat:aaaa0006", agent_id="main", project_id=project["project_id"]
    )
    await manager.create("agent:main:webchat:aaaa0007", agent_id="main")

    rows = await manager.list_sessions(project_id=project["project_id"])
    assert [row["session_key"] for row in rows] == ["agent:main:webchat:aaaa0006"]


@pytest.mark.asyncio
async def test_get_project_knowledge_for_session(manager):
    project = await manager.create_project("main", "Research", knowledge="Shared facts.")
    await manager.create(
        "agent:main:webchat:aaaa0008", agent_id="main", project_id=project["project_id"]
    )
    await manager.create("agent:main:webchat:aaaa0009", agent_id="main")

    assert (
        await manager.get_project_knowledge_for_session("agent:main:webchat:aaaa0008")
        == "Shared facts."
    )
    assert await manager.get_project_knowledge_for_session("agent:main:webchat:aaaa0009") is None
    # Blank knowledge injects nothing.
    await manager.update_project(project["project_id"], knowledge="   ")
    assert await manager.get_project_knowledge_for_session("agent:main:webchat:aaaa0008") is None


@pytest.mark.asyncio
async def test_search_transcript_scoped_to_project(manager, storage):
    project = await manager.create_project("main", "Research")
    inside = await manager.create(
        "agent:main:webchat:aaaa000a", agent_id="main", project_id=project["project_id"]
    )
    outside = await manager.create("agent:main:webchat:aaaa000b", agent_id="main")
    await manager.append_message(inside.session_key, role="user", content="quantum widget alpha")
    await manager.append_message(outside.session_key, role="user", content="quantum widget beta")

    all_hits = await storage.search_transcript("quantum widget")
    assert len(all_hits) == 2

    scoped = await storage.search_transcript("quantum widget", project_id=project["project_id"])
    assert [hit["session_key"] for hit in scoped] == [inside.session_key]


@pytest.mark.asyncio
async def test_update_project_rename_does_not_clobber_concurrent_knowledge(manager):
    """A rename holding a stale row must not revert another writer's knowledge."""
    project = await manager.create_project("main", "Research", knowledge="v1")
    pid = project["project_id"]

    # Writer B saves new knowledge after writer A read the row; A then
    # renames without a precondition. Partial UPDATE keeps B's knowledge.
    await manager.update_project(pid, knowledge="v2")
    renamed = await manager.update_project(pid, name="Renamed")
    assert renamed["name"] == "Renamed"
    assert renamed["knowledge"] == "v2"


@pytest.mark.asyncio
async def test_update_project_cas_conflict_on_stale_read(manager):
    project = await manager.create_project("main", "Research", knowledge="v1")
    pid = project["project_id"]
    stale = project["updated_at"]

    fresh = await manager.update_project(pid, knowledge="v2")
    assert fresh["updated_at"] != stale
    with pytest.raises(ProjectUpdateConflictError):
        await manager.update_project(pid, knowledge="v3", expected_updated_at=stale)
    # Nothing was written by the losing update.
    row = await manager.get_project(pid)
    assert row["knowledge"] == "v2"

    # A matching precondition succeeds.
    winner = await manager.update_project(
        pid, knowledge="v3", expected_updated_at=fresh["updated_at"]
    )
    assert winner["knowledge"] == "v3"


@pytest.mark.asyncio
async def test_storage_unique_name_index_backstops_python_check(manager, storage):
    """Writing a duplicate name straight to storage (bypassing the advisory
    Python check, as a concurrent create would) hits the unique index."""
    from agentos.compat import aiosqlite
    from agentos.session.models import ProjectNode

    await manager.create_project("main", "Research")
    with pytest.raises(aiosqlite.IntegrityError):
        await storage.upsert_project(ProjectNode(agent_id="main", name="research"))


def test_write_cap_matches_injection_cap():
    """Anything that saves must inject in full — the caps may never diverge
    again (a larger write cap silently truncated every turn)."""
    from agentos.engine.runtime import TurnRunner

    assert (
        SessionManager.PROJECT_KNOWLEDGE_MAX_CHARS == TurnRunner.PROJECT_KNOWLEDGE_INJECT_MAX_CHARS
    )


# ── sanitize_fts_query regression tests ─────────────────────────────────


def test_sanitize_fts_query_preserves_unicode():
    """Unicode letters (Latin-1 accents, CJK, Cyrillic, Arabic, etc.) must be
    preserved in FTS tokens so searches actually find non-ASCII transcript
    content. Previously the ASCII-only regex stripped all non-ASCII chars,
    turning 'résumé' into partial tokens and '中文' into nothing."""
    # Latin accents — before fix: "café" → '"caf"' (accent stripped, wrong stem)
    assert SessionStorage.sanitize_fts_query("café") == '"café"'
    # Multi-word Latin-1
    assert SessionStorage.sanitize_fts_query("déploiement résumé") == '"déploiement" "résumé"'
    # CJK — before fix: empty → '""', zero results
    assert SessionStorage.sanitize_fts_query("中文 报告") == '"中文" "报告"'
    assert SessionStorage.sanitize_fts_query("部署 pipeline") == '"部署" "pipeline"'
    # Cyrillic
    assert SessionStorage.sanitize_fts_query("Привет мир") == '"Привет" "мир"'
    assert SessionStorage.sanitize_fts_query("отчёт готов") == '"отчёт" "готов"'
    # Vietnamese diacritics — before fix: "triển khai" → '"tri" "n" "khai"'
    assert SessionStorage.sanitize_fts_query("triển khai hệ thống") == '"triển" "khai" "hệ" "thống"'
    # Mixed scripts
    assert SessionStorage.sanitize_fts_query('café "quoted" 部署') == '"café" "quoted" "部署"'


def test_sanitize_fts_query_blocks_injection():
    """FTS5 operators, quotes, and other syntax-breaking chars must be stripped
    so a malicious query cannot expand the scope of a FTS MATCH."""
    # Quoted-string injection: "test" OR 1=1 --
    assert SessionStorage.sanitize_fts_query('test" OR 1=1 --') == '"test" "OR" "1=1"'
    # Star wildcard at end of term
    assert SessionStorage.sanitize_fts_query("star*") == '"star"'
    # NEAR operator
    assert SessionStorage.sanitize_fts_query("a NEAR b") == '"a" "NEAR" "b"'
    # Caret prefix
    assert SessionStorage.sanitize_fts_query("^prefix") == '"prefix"'
    # Parentheses group
    assert SessionStorage.sanitize_fts_query("(grouped)") == '"grouped"'
    # Column selector
    assert SessionStorage.sanitize_fts_query("col:term") == '"col" "term"'
    # Backtick command injection
    assert SessionStorage.sanitize_fts_query("a`whoami`b") == '"a" "whoami" "b"'
    # NUL / control chars stripped
    assert SessionStorage.sanitize_fts_query("a\x00b\x07c") == '"a" "b" "c"'


def test_sanitize_fts_query_token_cap():
    """Queries with more than 20 tokens are silently truncated to prevent
    oversized MATCH expressions."""
    many = " ".join([f"word{i}" for i in range(30)])
    result = SessionStorage.sanitize_fts_query(many)
    assert result.count('"') == 40  # 20 tokens × 2 quotes each
    assert "word29" not in result
    assert "word0" in result


def test_sanitize_fts_query_empty_and_blank():
    """Empty or whitespace-only queries return the empty-string literal."""
    assert SessionStorage.sanitize_fts_query("") == '""'
    assert SessionStorage.sanitize_fts_query("   ") == '""'
    assert SessionStorage.sanitize_fts_query("\t\n") == '""'


# ── FTS5 end-to-end regression tests (issue #903) ─────────────────────
# The sanitizer output is an implementation detail; the hit count against a
# real in-memory FTS5 index is the contract. These tests seed a real
# transcript_fts via append_transcript_entry and search through
# search_transcript, covering the four script families from the issue table
# (Latin-1 accents, CJK, Cyrillic, Vietnamese diacritics) plus the
# punctuation-only empty-guard path.


@pytest.mark.asyncio
async def test_search_transcript_finds_unicode_content_end_to_end(storage):
    """A Unicode query must find rows a real FTS5 index actually matched.

    Before the fix the ASCII-only whitelist stripped every non-ASCII char,
    so '部署' became the empty MATCH literal and search_transcript returned
    [] even though the row was indexed.
    """
    from agentos.session.models import SessionNode, TranscriptEntry

    t0 = 1_700_000_000_000
    await storage.upsert_session(
        SessionNode(session_key="sk:fts", session_id="sess-fts", created_at=t0, updated_at=t0)
    )
    seed_rows = [
        ("user", "部署 pipeline 完成", t0),
        ("assistant", "报告: 中文 content here", t0 + 1),
        ("user", "café déjeuner was great", t0 + 2),
        ("assistant", "Привет мир из Москвы", t0 + 3),
        ("user", "triển khai hệ thống xong", t0 + 4),
        ("assistant", "plain ascii note", t0 + 5),
    ]
    for role, content, created_at in seed_rows:
        await storage.append_transcript_entry(
            TranscriptEntry(
                session_id="sess-fts",
                session_key="sk:fts",
                role=role,
                content=content,
                created_at=created_at,
            )
        )

    # Each Unicode query must return its row — hit count is the contract.
    expected = {
        "部署": "部署 pipeline 完成",
        "中文": "报告: 中文 content here",
        "café": "café déjeuner was great",
        "Привет": "Привет мир из Москвы",
        "triển": "triển khai hệ thống xong",
    }
    # Strip snippet() highlight markers (">>>term<<<") before comparing.
    for query, content in expected.items():
        hits = await storage.search_transcript(query, session_id="sess-fts")
        assert len(hits) == 1, f"query {query!r} returned {len(hits)} hits, expected 1"
        snippet = (hits[0].get("snippet") or "").replace(">>>", "").replace("<<<", "")
        assert content in snippet, f"query {query!r} hit wrong row: {snippet!r}"

    # Partial-token regression: the old sanitizer turned 'café' into '"caf"',
    # which can match UNRELATED ascii rows. Exact 'café' must not match the
    # plain-ascii row either.
    ascii_only = await storage.search_transcript("plain ascii", session_id="sess-fts")
    assert len(ascii_only) == 1
    plain_snippet = (ascii_only[0].get("snippet") or "").replace(">>>", "").replace("<<<", "")
    assert "plain ascii note" in plain_snippet


@pytest.mark.asyncio
async def test_search_transcript_punctuation_only_query_returns_empty(storage):
    """A query made only of punctuation must exercise the empty-guard path.

    All FTS5 syntax chars are stripped, so the sanitized query is the empty
    MATCH literal and search_transcript must return [] (no rows, no crash).
    """
    from agentos.session.models import SessionNode, TranscriptEntry

    t0 = 1_700_000_000_000
    await storage.upsert_session(
        SessionNode(session_key="sk:punct", session_id="sess-punct", created_at=t0, updated_at=t0)
    )
    await storage.append_transcript_entry(
        TranscriptEntry(
            session_id="sess-punct",
            session_key="sk:punct",
            role="user",
            content="hello world",
            created_at=t0,
        )
    )
    for query in ("!!!", "???", '""', "(())", "***", "--", "  .,;  "):
        assert storage.sanitize_fts_query(query) == '""', f"sanitizer leaked {query!r}"
        hits = await storage.search_transcript(query, session_id="sess-punct")
        assert hits == [], f"punctuation-only query {query!r} returned {hits}"
