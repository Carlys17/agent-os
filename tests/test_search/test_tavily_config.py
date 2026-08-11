from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentos.gateway.config import GatewayConfig
from agentos.search.providers.tavily import TavilySearchProvider
from agentos.search.types import SearchProviderError
from agentos.tools.builtin import web


def test_gateway_config_accepts_search_api_key() -> None:
    config = GatewayConfig(search_api_key="tavily-test-key")
    assert config.search_api_key == "tavily-test-key"


def test_tavily_provider_prefers_explicit_api_key(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    provider = TavilySearchProvider(api_key="tavily-test-key")
    assert provider._api_key == "tavily-test-key"


def test_tavily_provider_strips_trailing_paste_punctuation(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    provider = TavilySearchProvider(api_key="tavily-test-key、")
    assert provider._api_key == "tavily-test-key"


def test_web_search_kwargs_pass_tavily_api_key() -> None:
    web.configure_search("tavily", api_key="tavily-test-key")
    assert web._search_provider_kwargs("tavily")["api_key"] == "tavily-test-key"


@pytest.mark.asyncio
async def test_tavily_search_success(monkeypatch) -> None:
    provider = TavilySearchProvider(api_key="tavily-test-key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {
                "title": "Tavily Title",
                "url": "https://tavily.com",
                "content": "Tavily Content",
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    monkeypatch.setattr("httpx.AsyncClient.__aenter__", AsyncMock(return_value=mock_client))

    results = await provider.search("hello", max_results=1)

    assert len(results) == 1
    assert results[0].title == "Tavily Title"
    assert results[0].url == "https://tavily.com"
    assert results[0].snippet == "Tavily Content"


@pytest.mark.asyncio
async def test_tavily_search_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    provider = TavilySearchProvider(api_key="")

    with pytest.raises(SearchProviderError) as exc_info:
        await provider.search("hello")
    assert exc_info.value.kind == "auth"
