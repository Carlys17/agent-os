from __future__ import annotations

import pytest

from agentos.gateway import rpc_skills
from agentos.skills.hub.lockfile import LockEntry
from agentos.skills.hub.source import SkillMeta


class _StubRouter:
    def __init__(self, results: list[SkillMeta]) -> None:
        self._results = results
        self.calls: list[dict] = []

    async def search(self, query: str, limit: int = 20, source_id: str | None = None):
        self.calls.append({"query": query, "limit": limit, "source_id": source_id})
        return self._results[:limit]


class _Ctx:
    def __init__(self, router: _StubRouter, skill_loader=None) -> None:
        self._skill_router = router
        self.skill_loader = skill_loader


def _no_lockfile(monkeypatch) -> None:
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: set())
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: set())
    monkeypatch.setattr(rpc_skills, "_installed_lock_entries", dict)


@pytest.mark.asyncio
async def test_skills_search_payload_carries_catalog_fields(monkeypatch) -> None:
    """The browse UI reads provider/logo/category/setup/demo/homepage off every
    result row — dropping any of them silently breaks the registry cards and
    the detail dialog."""
    _no_lockfile(monkeypatch)
    meta = SkillMeta(
        name="alchemy",
        source_id="bankr",
        identifier="https://github.com/BankrBot/skills/tree/main/alchemy",
        homepage="https://alchemy.com",
        provider="Alchemy",
        logo="https://raw.githubusercontent.com/BankrBot/skills/main/alchemy/alchemy.svg",
        category="data",
        setup=["Install SDK"],
        demo={"title": "demo.sh", "language": "bash", "code": "alchemy run"},
    )
    router = _StubRouter([meta])

    res = await rpc_skills._handle_skills_search(
        {"query": "", "source": "bankr", "limit": 200}, _Ctx(router)
    )

    row = res["results"][0]
    assert row["provider"] == "Alchemy"
    assert row["logo"].endswith("alchemy.svg")
    assert row["category"] == "data"
    assert row["setup"] == ["Install SDK"]
    assert row["demo"]["code"] == "alchemy run"
    assert row["homepage"] == "https://alchemy.com"
    assert row["installed"] is False


@pytest.mark.asyncio
async def test_skills_search_marks_installed_by_identifier(monkeypatch) -> None:
    """A skill whose lockfile name differs from its catalog slug must still show
    as installed. Bankr's ``bankr-token-scam-analysis`` slug installs under the
    name ``token-scam-analysis``, so name-only matching misses it — the source
    identifier is the reliable join key across a page reload."""
    # Lockfile records only the installed *name*, which does not match the
    # browse card's name; the identifier is what lines up.
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: {"token-scam-analysis"})
    identifier = "https://github.com/BankrBot/skills/tree/main/bankr-token-scam-analysis"
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: {identifier})
    monkeypatch.setattr(
        rpc_skills,
        "_installed_lock_entries",
        lambda: {"token-scam-analysis": LockEntry(source="bankr", identifier=identifier)},
    )
    meta = SkillMeta(
        name="bankr-token-scam-analysis",
        source_id="bankr",
        identifier="https://github.com/BankrBot/skills/tree/main/bankr-token-scam-analysis",
    )
    router = _StubRouter([meta])

    res = await rpc_skills._handle_skills_search({"query": "", "source": "bankr"}, _Ctx(router))

    assert res["results"][0]["installed"] is True


@pytest.mark.asyncio
async def test_skills_search_limit_accommodates_full_catalog_browse(monkeypatch) -> None:
    """Browse requests whole catalogs (Bankr is ~100 skills); a cap sized for
    paged search results would silently truncate them."""
    _no_lockfile(monkeypatch)
    metas = [SkillMeta(name=f"skill-{i:03d}", source_id="bankr") for i in range(150)]
    router = _StubRouter(metas)

    res = await rpc_skills._handle_skills_search({"query": "", "limit": 200}, _Ctx(router))

    assert router.calls[0]["limit"] == 200
    assert len(res["results"]) == 150


# ── Installed skills the catalog does not return ────────────────────────────


class _StubLoader:
    """Just enough loader for the synthesized-row description lookup."""

    def __init__(self, specs: dict) -> None:
        self._specs = specs

    def get_by_name(self, name: str):
        return self._specs.get(name)


class _StubSpec:
    def __init__(self, description: str, emoji: str = "") -> None:
        self.description = description
        self.metadata = type("_Meta", (), {"emoji": emoji})()


def _lock_entry(**kwargs) -> LockEntry:
    defaults = {
        "source": "bankr",
        "identifier": "https://github.com/BankrBot/skills/tree/main/ledger-watch",
        "version": "1.2.0",
        "installed_at": "2026-01-01T00:00:00Z",
        "upstream_url": "https://github.com/BankrBot/skills",
        "source_trust": "trusted",
        "publisher_id": "bankr",
    }
    defaults.update(kwargs)
    return LockEntry(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_browse_surfaces_an_install_the_catalog_did_not_return(monkeypatch) -> None:
    """Symptom 2: a skill installed minutes ago vanishes from Community.

    An empty-query browse asks a source for its catalog, and a catalog is free
    not to list something the user has installed — a GitHub install by URL is in
    no catalog at all. Without this join the row simply is not there after a
    reload, which reads as the install having been lost."""
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: {"ledger-watch"})
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: set())
    monkeypatch.setattr(
        rpc_skills, "_installed_lock_entries", lambda: {"ledger-watch": _lock_entry()}
    )
    router = _StubRouter([SkillMeta(name="alchemy", source_id="bankr", identifier="alchemy-id")])
    loader = _StubLoader({"ledger-watch": _StubSpec("Watch a ledger address.", emoji="👁")})

    res = await rpc_skills._handle_skills_search({"query": ""}, _Ctx(router, loader))

    names = [row["name"] for row in res["results"]]
    # Appended, not prepended: a synthesized row has no relevance score and no
    # catalog metadata, so it must not displace richer rows at the top.
    assert names == ["alchemy", "ledger-watch"]
    row = res["results"][1]
    assert row["installed"] is True
    assert row["source"] == "bankr"
    assert row["identifier"] == "https://github.com/BankrBot/skills/tree/main/ledger-watch"
    assert row["version"] == "1.2.0"
    assert row["trust_level"] == "trusted"
    assert row["homepage"] == "https://github.com/BankrBot/skills"
    assert row["description"] == "Watch a ledger address."
    assert row["emoji"] == "👁"
    # Only the allowlisted record supplies a brand.
    assert row["provider"] == "Bankr"
    # No catalog metadata means no category: the row joins the existing "other"
    # bucket rather than inventing a chip on catalogs that show none today.
    assert row["category"] == ""
    assert set(row) == set(res["results"][0])


@pytest.mark.asyncio
async def test_an_unrecognized_publisher_cannot_brand_a_synthesized_row(monkeypatch) -> None:
    """The lockfile is a writable file on disk; it is a selector, not a source
    of brand identity."""
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: {"ledger-watch"})
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: set())
    monkeypatch.setattr(
        rpc_skills,
        "_installed_lock_entries",
        lambda: {
            "ledger-watch": _lock_entry(publisher_id="acme-capital", publisher_name="Robinhood")
        },
    )
    router = _StubRouter([])

    res = await rpc_skills._handle_skills_search({"query": ""}, _Ctx(router))

    assert res["results"][0]["provider"] == ""
    assert res["results"][0]["logo"] == ""


@pytest.mark.asyncio
async def test_browsing_one_source_does_not_surface_another_sources_installs(monkeypatch) -> None:
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: {"ledger-watch"})
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: set())
    monkeypatch.setattr(
        rpc_skills, "_installed_lock_entries", lambda: {"ledger-watch": _lock_entry()}
    )
    router = _StubRouter([])

    clawhub = await rpc_skills._handle_skills_search(
        {"query": "", "source": "clawhub"}, _Ctx(router)
    )
    bankr = await rpc_skills._handle_skills_search({"query": "", "source": "bankr"}, _Ctx(router))

    assert clawhub["results"] == []
    assert [row["name"] for row in bankr["results"]] == ["ledger-watch"]


@pytest.mark.asyncio
async def test_a_keyword_search_only_synthesizes_installs_that_match(monkeypatch) -> None:
    """Browse must not hide installs; a keyword search must still be a search."""
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: {"ledger-watch"})
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: set())
    monkeypatch.setattr(
        rpc_skills, "_installed_lock_entries", lambda: {"ledger-watch": _lock_entry()}
    )
    router = _StubRouter([])
    loader = _StubLoader({"ledger-watch": _StubSpec("Watch a ledger address.")})

    miss = await rpc_skills._handle_skills_search({"query": "photo"}, _Ctx(router, loader))
    by_name = await rpc_skills._handle_skills_search({"query": "LEDGER"}, _Ctx(router, loader))
    by_description = await rpc_skills._handle_skills_search(
        {"query": "address"}, _Ctx(router, loader)
    )

    assert miss["results"] == []
    assert [row["name"] for row in by_name["results"]] == ["ledger-watch"]
    assert [row["name"] for row in by_description["results"]] == ["ledger-watch"]


@pytest.mark.asyncio
async def test_a_catalog_row_is_never_duplicated_by_a_synthesized_row(monkeypatch) -> None:
    """Dedupe on identifier, so a slug/name mismatch does not double the card."""
    identifier = "https://github.com/BankrBot/skills/tree/main/ledger-watch"
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: {"ledger-watch"})
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: {identifier})
    monkeypatch.setattr(
        rpc_skills, "_installed_lock_entries", lambda: {"ledger-watch": _lock_entry()}
    )
    router = _StubRouter(
        [SkillMeta(name="bankr-ledger-watch", source_id="bankr", identifier=identifier)]
    )

    res = await rpc_skills._handle_skills_search({"query": ""}, _Ctx(router))

    assert [row["name"] for row in res["results"]] == ["bankr-ledger-watch"]
    assert res["results"][0]["installed"] is True


@pytest.mark.asyncio
async def test_a_name_colliding_with_another_skills_identifier_is_not_installed(
    monkeypatch,
) -> None:
    """The installed chip joins names to names and identifiers to identifiers.

    Pooling both into one set makes a catalog row named ``x`` show as installed
    because some unrelated skill was installed from an identifier spelled ``x``."""
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: {"token-scam-analysis"})
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: {"alchemy"})
    monkeypatch.setattr(
        rpc_skills,
        "_installed_lock_entries",
        lambda: {"token-scam-analysis": _lock_entry(source="clawhub", identifier="alchemy")},
    )
    router = _StubRouter([SkillMeta(name="alchemy", source_id="bankr", identifier="alchemy-id")])

    res = await rpc_skills._handle_skills_search({"query": "", "source": "bankr"}, _Ctx(router))

    assert res["results"][0]["installed"] is False
