from __future__ import annotations

import json
from typing import Any

import pytest

from agentos.skills.hub.capminal import CapminalSource

_FIXTURE_SLUGS = ("capminal", "contract-interaction", "morse-launch-b20", "broken")


def _meta(
    slug: str,
    *,
    owner: str = "AndreaPN",
    display_name: str | None = None,
    version: str = "0.37.0",
) -> bytes:
    return json.dumps(
        {
            "owner": owner,
            "package": slug,
            "displayName": display_name or slug.capitalize(),
            "latestRelease": {
                "version": version,
                "publishedAt": 1748822400000,
            },
        }
    ).encode("utf-8")


class _Response:
    def __init__(
        self,
        *,
        json_data: dict[str, Any] | None = None,
        content: bytes = b"",
        status_code: int = 200,
    ) -> None:
        self._json_data = json_data or {}
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _AsyncClient:
    """Mocks the per-skill Capminal/agent-skills _meta.json + SKILL.md fetches."""

    metas = {
        "capminal": _meta("capminal"),
        "contract-interaction": _meta("contract-interaction"),
        "morse-launch-b20": _meta("morse-launch-b20"),
        "broken": b"{ not json",
    }
    skill_mds = {
        "capminal": (
            b"---\nname: capminal\ndescription: Cap World interaction\n"
            b"tags: [capminal, crypto, wallet]\n---\n# Capminal\n"
        ),
        "contract-interaction": (
            b"---\nname: contract-interaction\ndescription: Smart contract interaction\n"
            b"tags: [contract, crypto]\n---\n# Contract\n"
        ),
        "morse-launch-b20": (
            b"---\nname: morse-launch-b20\ndescription: Morse launch B20 skill\n"
            b"tags: [morse, launch]\n---\n# Morse\n"
        ),
    }
    meta_calls = 0
    skill_md_calls = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _AsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> _Response:
        if "/git/trees/" in url:
            raise AssertionError(f"tree API must not be called: {url}")
        marker = "raw.githubusercontent.com/Capminal/agent-skills/main/"
        if marker in url:
            slug = url.split(marker, 1)[1].split("/", 1)[0]
            if url.endswith("/SKILL.md"):
                type(self).skill_md_calls += 1
                content = self.skill_mds.get(slug)
                if content is None:
                    return _Response(status_code=404)
                return _Response(content=content)
            type(self).meta_calls += 1
            content = self.metas.get(slug)
            if content is None or content == b"{ not json":
                return _Response(content=content or b"")
            return _Response(content=content)
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture(autouse=True)
def _reset_client_counters() -> None:
    _AsyncClient.meta_calls = 0
    _AsyncClient.skill_md_calls = 0


def _source() -> CapminalSource:
    return CapminalSource(allowlist=_FIXTURE_SLUGS)


@pytest.mark.asyncio
async def test_search_empty_query_lists_all_capminal_skills(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    results = await _source().search("")

    names = {r.name for r in results}
    # capminal, contract-interaction, morse-launch-b20 kept; broken JSON skipped.
    assert names == {"capminal", "contract-interaction", "morse-launch-b20"}
    assert all(r.source_id == "capminal" for r in results)
    assert all(r.trust_level == "community" for r in results)
    assert all(r.category == "crypto" for r in results)


@pytest.mark.asyncio
async def test_search_builds_provider_and_identifier(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    results = await _source().search("")
    by_name = {r.name: r for r in results}

    capminal = by_name["capminal"]
    assert capminal.provider == "Capminal"
    assert capminal.logo == ""
    assert capminal.identifier == "https://github.com/Capminal/agent-skills/tree/main/capminal"
    assert capminal.emoji == "🤖"
    assert capminal.tags == ["capminal", "crypto", "wallet"]


@pytest.mark.asyncio
async def test_inspect_and_fetch_enforce_allowlist(monkeypatch) -> None:
    src = _source()
    inspected_id = None
    fetched_id = None

    async def mock_inspect(self_source, identifier):
        nonlocal inspected_id
        inspected_id = identifier
        return None

    async def mock_fetch(self_source, identifier):
        nonlocal fetched_id
        fetched_id = identifier
        return None

    from agentos.skills.hub.github import GitHubSource

    monkeypatch.setattr(GitHubSource, "inspect", mock_inspect)
    monkeypatch.setattr(GitHubSource, "fetch", mock_fetch)

    # Allowed identifier delegates successfully
    allowed_id = "https://github.com/Capminal/agent-skills/tree/main/capminal"
    await src.inspect(allowed_id)
    assert inspected_id == allowed_id

    await src.fetch(allowed_id)
    assert fetched_id == allowed_id

    # Disallowed repo is rejected without delegating
    inspected_id = None
    fetched_id = None
    disallowed_repo = "https://github.com/attacker/malicious/tree/main/capminal"
    assert await src.inspect(disallowed_repo) is None
    assert inspected_id is None

    assert await src.fetch(disallowed_repo) is None
    assert fetched_id is None

    # Disallowed slug in Capminal repo is rejected without delegating
    disallowed_slug = "https://github.com/Capminal/agent-skills/tree/main/unapproved"
    assert await src.inspect(disallowed_slug) is None
    assert inspected_id is None

    assert await src.fetch(disallowed_slug) is None
    assert fetched_id is None

