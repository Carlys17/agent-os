from __future__ import annotations

import json
from typing import Any

import pytest

from agentos.skills.hub.capminal import CapminalSource

_FIXTURE_SLUGS = ("capminal", "contract-interaction", "neuron-branch-stats", "broken")


def _meta(slug: str, *, version: str = "0.1.0", github_url: str | None = None) -> bytes:
    if github_url is None:
        github_url = f"https://github.com/capminal-skills/{slug}"
    return json.dumps(
        {
            "name": slug,
            "package": slug,
            "description": f"Capminal description for {slug}",
            "installSource": {
                "version": version,
                "githubUrl": github_url,
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
    """Mocks the per-skill capminal-skills/skills _meta.json + SKILL.md fetches."""

    metas = {
        "capminal": _meta("capminal"),
        "contract-interaction": _meta("contract-interaction"),
        "neuron-branch-stats": _meta("neuron-branch-stats"),
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
        "neuron-branch-stats": (
            b"---\nname: neuron-branch-stats\ndescription: Stats for neuron branch\n"
            b"tags: [stats, branch]\n---\n# Stats\n"
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
        marker = "raw.githubusercontent.com/capminal-skills/skills/main/"
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
    # capminal, contract-interaction, neuron-branch-stats kept; broken JSON skipped.
    assert names == {"capminal", "contract-interaction", "neuron-branch-stats"}
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
    assert capminal.identifier == "https://github.com/capminal-skills/capminal"
    assert capminal.emoji == "🤖"
    assert capminal.tags == ["capminal", "crypto", "wallet"]


@pytest.mark.asyncio
async def test_search_delegates_inspect_and_fetch(monkeypatch) -> None:
    # Verify that inspect and fetch calls on CapminalSource are delegated to GitHubSource
    src = _source()
    called_inspect = False
    called_fetch = False

    async def mock_inspect(self_source, identifier):
        nonlocal called_inspect
        called_inspect = True
        return None

    async def mock_fetch(self_source, identifier):
        nonlocal called_fetch
        called_fetch = True
        return None

    from agentos.skills.hub.github import GitHubSource
    monkeypatch.setattr(GitHubSource, "inspect", mock_inspect)
    monkeypatch.setattr(GitHubSource, "fetch", mock_fetch)

    await src.inspect("https://github.com/capminal-skills/capminal")
    assert called_inspect

    await src.fetch("https://github.com/capminal-skills/capminal")
    assert called_fetch
