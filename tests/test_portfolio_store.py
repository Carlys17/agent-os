"""Tests for the portfolio store."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.portfolio_store import (
    PortfolioStore,
    PortfolioStoreNotFoundError,
    PortfolioStoreStateError,
    PortfolioStoreValidationError,
    get_portfolio_store,
    reset_portfolio_store,
)


@pytest.fixture(autouse=True)
def clean_global() -> None:
    """Reset the global store singleton before and after every test."""
    reset_portfolio_store()
    yield
    reset_portfolio_store()


@pytest.fixture
def store(tmp_path: Path) -> PortfolioStore:
    """Return a fresh per-test portfolio store.

    Uses pytest's ``tmp_path`` so each test gets a unique directory
    and the store is destroyed on test teardown.
    """
    return PortfolioStore(tmp_path / "portfolio.db")


# -------------------------------------------------------------------
# Open position
# -------------------------------------------------------------------


class TestOpenPosition:
    async def test_returns_stable_id(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xABCDEF1234567890",
            chain="ethereum",
            token_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            token_symbol="WETH",
            amount=10.0,
            entry_price=3500.0,
        )
        assert pid.startswith("pos-0xABCDEF")
        assert len(pid.split("-")) == 3

    async def test_stores_correct_values(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET",
            chain="solana",
            token_address="MEMEcoin",
            token_symbol="MEME",
            amount=1000.0,
            entry_price=0.001,
            metadata={"source": "pumpfun"},
        )
        pos = await store.get_position(pid)
        assert pos.wallet == "0xWALLET"
        assert pos.chain == "solana"
        assert pos.token_symbol == "MEME"
        assert pos.amount == 1000.0
        assert pos.entry_price == 0.001
        assert pos.status == "open"
        assert pos.metadata["source"] == "pumpfun"

    async def test_symbol_normalized_to_uppercase(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET",
            chain="ethereum",
            token_address="0xABC",
            token_symbol="weth",
            amount=1.0,
            entry_price=100.0,
        )
        pos = await store.get_position(pid)
        assert pos.token_symbol == "WETH"

    @pytest.mark.parametrize(
        "amount,entry_price",
        [(0.0, 1.0), (-1.0, 1.0), (1.0, 0.0), (1.0, -0.001)],
    )
    async def test_rejects_non_positive_values(
        self, store: PortfolioStore, amount: float, entry_price: float
    ) -> None:
        with pytest.raises(PortfolioStoreValidationError):
            await store.open_position(
                wallet="0xWALLET",
                chain="ethereum",
                token_address="0xABC",
                token_symbol="T",
                amount=amount,
                entry_price=entry_price,
            )

    async def test_rejects_empty_wallet(self, store: PortfolioStore) -> None:
        with pytest.raises(PortfolioStoreValidationError):
            await store.open_position(
                wallet="   ",
                chain="ethereum",
                token_address="0xABC",
                token_symbol="T",
                amount=1.0,
                entry_price=1.0,
            )


# -------------------------------------------------------------------
# Close position
# -------------------------------------------------------------------


class TestClosePosition:
    async def test_computes_realized_pnl(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET",
            chain="ethereum",
            token_address="0xUNI",
            token_symbol="UNI",
            amount=5.0,
            entry_price=10.0,
        )
        realized = await store.close_position(position_id=pid, exit_price=12.0)
        # (12 - 10) * 5 = 10
        assert realized == 10.0

    async def test_marks_status_closed(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET",
            chain="ethereum",
            token_address="0xUNI",
            token_symbol="UNI",
            amount=5.0,
            entry_price=10.0,
        )
        await store.close_position(position_id=pid, exit_price=12.0)
        pos = await store.get_position(pid)
        assert pos.status == "closed"
        assert pos.exit_price == 12.0
        assert pos.realized_pnl == 10.0

    async def test_rejects_double_close(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET",
            chain="ethereum",
            token_address="0xUNI",
            token_symbol="UNI",
            amount=1.0,
            entry_price=1.0,
        )
        await store.close_position(position_id=pid, exit_price=2.0)
        with pytest.raises(PortfolioStoreStateError):
            await store.close_position(position_id=pid, exit_price=3.0)

    async def test_raises_for_unknown_id(self, store: PortfolioStore) -> None:
        with pytest.raises(PortfolioStoreNotFoundError):
            await store.close_position(position_id="pos-nonexistent-123", exit_price=1.0)

    async def test_metadata_merged_on_close(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET",
            chain="ethereum",
            token_address="0xUNI",
            token_symbol="UNI",
            amount=1.0,
            entry_price=1.0,
            metadata={"source": "uniswap_v2"},
        )
        await store.close_position(
            position_id=pid, exit_price=2.0, metadata={"exit_route": "sushiswap"}
        )
        pos = await store.get_position(pid)
        assert pos.metadata["source"] == "uniswap_v2"
        assert pos.metadata["exit_route"] == "sushiswap"


# -------------------------------------------------------------------
# Position queries
# -------------------------------------------------------------------


class TestPositionQueries:
    async def test_list_open_excludes_closed(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET", chain="ethereum", token_address="0xA", token_symbol="A",
            amount=1.0, entry_price=1.0,
        )
        await store.open_position(
            wallet="0xWALLET", chain="ethereum", token_address="0xB", token_symbol="B",
            amount=1.0, entry_price=1.0,
        )
        await store.close_position(position_id=pid, exit_price=2.0)
        open_pos = await store.list_open("0xWALLET")
        assert len(open_pos) == 1
        assert open_pos[0].token_symbol == "B"

    async def test_list_all_includes_closed(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET", chain="ethereum", token_address="0xA", token_symbol="A",
            amount=1.0, entry_price=1.0,
        )
        await store.close_position(position_id=pid, exit_price=2.0)
        all_pos = await store.list_all("0xWALLET")
        assert len(all_pos) == 1
        assert all_pos[0].status == "closed"


# -------------------------------------------------------------------
# Position calculations
# -------------------------------------------------------------------


class TestPositionCalculations:
    async def test_unrealized_pnl_on_open(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET", chain="ethereum", token_address="0xETH", token_symbol="ETH",
            amount=2.0, entry_price=3000.0,
        )
        pos = await store.get_position(pid)
        # (3500 - 3000) * 2 = 1000
        assert pos.unrealized_pnl(3500.0) == 1000.0
        assert pos.unrealized_pnl_pct(3500.0) == pytest.approx(16.666, rel=1e-3)

    async def test_unrealized_is_zero_on_closed(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET", chain="ethereum", token_address="0xETH", token_symbol="ETH",
            amount=1.0, entry_price=1000.0,
        )
        await store.close_position(position_id=pid, exit_price=1500.0)
        pos = await store.get_position(pid)
        assert pos.unrealized_pnl(2000.0) == 0.0

    async def test_total_cost_and_value(self, store: PortfolioStore) -> None:
        pid = await store.open_position(
            wallet="0xWALLET", chain="ethereum", token_address="0xETH", token_symbol="ETH",
            amount=3.0, entry_price=2000.0,
        )
        pos = await store.get_position(pid)
        assert pos.total_cost() == 6000.0
        assert pos.total_value(4000.0) == 12000.0


# -------------------------------------------------------------------
# Portfolio summary
# -------------------------------------------------------------------


class TestPortfolioSummary:
    async def test_empty_wallet(self, store: PortfolioStore) -> None:
        summary = await store.portfolio_summary("0xEMPTY")
        assert summary["total_positions"] == 0
        assert summary["open_positions"] == 0
        assert summary["total_realized_pnl"] == 0.0

    async def test_aggregates_by_token(self, store: PortfolioStore) -> None:
        p1 = await store.open_position(
            wallet="0xWALLET", chain="ethereum", token_address="0xETH", token_symbol="ETH",
            amount=1.0, entry_price=1000.0,
        )
        await store.open_position(
            wallet="0xWALLET", chain="ethereum", token_address="0xETH", token_symbol="ETH",
            amount=2.0, entry_price=2000.0,
        )
        await store.close_position(position_id=p1, exit_price=1500.0)
        summary = await store.portfolio_summary("0xWALLET")
        assert summary["total_positions"] == 2
        assert summary["open_positions"] == 1
        eth_summary = next(t for t in summary["by_token"] if t["token_symbol"] == "ETH")
        assert eth_summary["position_count"] == 2
        assert eth_summary["realized_pnl"] == 500.0  # (1500-1000)*1


# -------------------------------------------------------------------
# Singleton
# -------------------------------------------------------------------


class TestSingleton:
    async def test_same_instance_returned(self) -> None:
        reset_portfolio_store()
        s1 = get_portfolio_store()
        s2 = get_portfolio_store()
        assert s1 is s2

    async def test_reset_clears_instance(self) -> None:
        s1 = get_portfolio_store()
        reset_portfolio_store()
        s2 = get_portfolio_store()
        assert s1 is not s2
