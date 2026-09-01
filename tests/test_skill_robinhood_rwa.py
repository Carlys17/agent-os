"""Offline regression tests for the robinhood-rwa-addresses lookup script.

The skill's entrypoint defaults ``--query`` to the raw user message, so the
matcher must resolve tokens from full sentences ("what is Apple's ticker?",
"mã cổ phiếu Apple là gì") as well as bare names/tickers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src/agentos/skills/bundled/robinhood-rwa-addresses/scripts/rwa_lookup.py"
)

_spec = importlib.util.spec_from_file_location("rwa_lookup", _SCRIPT)
assert _spec is not None and _spec.loader is not None
rwa_lookup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rwa_lookup)

_TOKENS = [
    {
        "chainId": 4663,
        "address": "0xaf3d76f1834a1d425780943c99ea8a608f8a93f9",
        "name": "Apple • Robinhood Token",
        "symbol": "AAPL",
        "decimals": 18,
        "logoURI": "https://assets.example/aapl.png",
    },
    {
        "chainId": 4663,
        "address": "0x322f0929c4625ed5bad873c95208d54e1c003b2d",
        "name": "Tesla • Robinhood Token",
        "symbol": "TSLA",
        "decimals": 18,
        "logoURI": "",
    },
    {
        "chainId": 4663,
        "address": "0x39ec44bee4f6a116c6f9b8de566848a985c53c60",
        "name": "e.l.f. Beauty • Robinhood Token",
        "symbol": "ELF",
        "decimals": 18,
        "logoURI": "",
    },
    {
        "chainId": 4663,
        "address": "0x1b0e319c6a659f002271b69db8a7df2f911c153e",
        "name": "GameStop • Robinhood Token",
        "symbol": "GME",
        "decimals": 18,
        "logoURI": "",
    },
    # Robinhood Chain is permissionless: this community token reuses GameStop's
    # name and ticker, and only the missing suffix tells the two apart.
    {
        "chainId": 4663,
        "address": "0x7e86381a763f0ecca2bdf27c54eac403ddd48123",
        "name": "GameStop",
        "symbol": "GME",
        "decimals": 18,
        "logoURI": "",
    },
]

_REAL_GME = "0x1b0e319c6a659f002271b69db8a7df2f911c153e"
_FAKE_GME = "0x7e86381a763f0ecca2bdf27c54eac403ddd48123"


def _symbols(query: str) -> list[str]:
    return [m["symbol"] for m in rwa_lookup.lookup(query, _TOKENS, limit=3)]


def test_bare_name_and_ticker_resolve() -> None:
    assert _symbols("Apple") == ["AAPL"]
    assert _symbols("AAPL") == ["AAPL"]
    assert _symbols("tesla") == ["TSLA"]


def test_full_sentence_queries_resolve() -> None:
    # The entrypoint feeds the raw user message by default.
    assert _symbols("What is Apple's ticker?")[:1] == ["AAPL"]
    assert _symbols("mã cổ phiếu apple là gì")[:1] == ["AAPL"]
    assert _symbols("Robinhood contract address for Tesla")[:1] == ["TSLA"]


def test_ticker_inside_sentence_resolves() -> None:
    assert _symbols("gia AAPL bao nhieu")[:1] == ["AAPL"]


def test_no_match_returns_empty() -> None:
    assert _symbols("zzz-not-a-company") == []


def test_robinhood_suffix_stripped_from_names() -> None:
    matches = rwa_lookup.lookup("Apple", _TOKENS, limit=1)
    assert matches[0]["name"] == "Apple"
    assert matches[0]["address"] == "0xaf3d76f1834a1d425780943c99ea8a608f8a93f9"


def test_community_token_impersonating_a_listing_is_excluded() -> None:
    """A lookalike must never be offered as the answer to a company question.

    Both entries clean up to the display name "GameStop" with symbol GME, so
    without the suffix filter the caller cannot tell which address is the equity.
    """
    for query in ("GME", "GameStop", "mã cổ phiếu GME là gì"):
        matches = rwa_lookup.lookup(query, _TOKENS, limit=5)
        assert [m["address"] for m in matches] == [_REAL_GME], query


def test_include_community_widens_the_search_but_keeps_stock_tokens_first() -> None:
    matches = rwa_lookup.lookup("GME", _TOKENS, limit=5, include_community=True)
    assert [m["address"] for m in matches] == [_REAL_GME, _FAKE_GME]
    assert [m["isStockToken"] for m in matches] == [True, False]


def test_matches_are_tagged_with_stock_token_status() -> None:
    assert rwa_lookup.lookup("Apple", _TOKENS, limit=1)[0]["isStockToken"] is True


def test_is_stock_token_keys_off_the_suffix() -> None:
    assert rwa_lookup.is_stock_token({"name": "Apple • Robinhood Token"}) is True
    assert rwa_lookup.is_stock_token({"name": "GameStop"}) is False
    assert rwa_lookup.is_stock_token({}) is False
