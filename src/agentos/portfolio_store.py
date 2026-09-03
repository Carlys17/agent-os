"""Persistent portfolio store for AgentOS.

Tracks token positions, cost basis, and realized PnL across sessions,
persisted in SQLite alongside the existing memory and scheduler stores.

Lifecycle:
    Use ``get_portfolio_store()`` — never construct directly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from agentos.compat import aiosqlite
from agentos.paths import state_dir

if TYPE_CHECKING:
    pass

SCHEMA_VERSION = 1
DDL_PORTFOLIO: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS portfolio_positions (
        id TEXT PRIMARY KEY,
        wallet TEXT NOT NULL,
        chain TEXT NOT NULL,
        token_address TEXT NOT NULL,
        token_symbol TEXT NOT NULL,
        amount REAL NOT NULL,
        entry_price REAL NOT NULL,
        entry_at REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        exit_price REAL,
        exit_at REAL,
        realized_pnl REAL,
        metadata TEXT,
        schema_version INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_portfolio_wallet
        ON portfolio_positions(wallet, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_portfolio_token
        ON portfolio_positions(token_address)
    """,
]

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class PortfolioStoreError(Exception):
    """Base exception for all portfolio store errors."""

    pass


class PortfolioStoreValidationError(PortfolioStoreError, ValueError):
    """Raised when input validation fails."""

    pass


class PortfolioStoreNotFoundError(PortfolioStoreError):
    """Raised when a position does not exist."""

    pass


class PortfolioStoreStateError(PortfolioStoreError):
    """Raised when an operation is illegal for the current position state."""

    pass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """A single token position tracked across sessions.

    Attributes:
        wallet: Owner's wallet address (checksummed).
        chain: Blockchain name (``ethereum``, ``solana``, ``base``, ...).
        token_address: Token contract address on the given chain.
        token_symbol: Human-readable symbol (``ETH``, ``USDC``).
        amount: Quantity of tokens held.
        entry_price: Cost per token at entry in chain's native token (e.g. ETH).
        entry_at: Unix timestamp of entry.
        status: ``open`` or ``closed``.
        exit_price: Price per token at exit, or ``None`` if still open.
        exit_at: Unix timestamp of exit, or ``None`` if still open.
        realized_pnl: Net PnL on this position, or ``None`` if still open.
        metadata: Arbitrary extra data stored as JSON.
    """

    wallet: str
    chain: str
    token_address: str
    token_symbol: str
    amount: float
    entry_price: float
    entry_at: float
    status: str = "open"
    exit_price: float | None = None
    exit_at: float | None = None
    realized_pnl: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def unrealized_pnl(self, current_price: float) -> float:
        """Unrealized PnL in chain-native token units.

        Returns 0 if the position is closed or has non-positive values.
        """
        if (
            self.status != "open"
            or self.amount <= 0
            or self.entry_price <= 0
            or current_price <= 0
        ):
            return 0.0
        return (current_price - self.entry_price) * self.amount

    def unrealized_pnl_pct(self, current_price: float) -> float:
        """Unrealized PnL as a percentage of total cost basis.

        Returns 0 if the position is closed or has non-positive values.
        """
        if (
            self.status != "open"
            or self.entry_price <= 0
            or self.amount <= 0
            or current_price <= 0
        ):
            return 0.0
        return ((current_price / self.entry_price) - 1.0) * 100.0

    def total_cost(self) -> float:
        """Total cost basis (entry_price * amount)."""
        return self.entry_price * self.amount

    def total_value(self, current_price: float) -> float:
        """Current market value (current_price * amount)."""
        return current_price * self.amount

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for API responses."""
        return {
            "id": getattr(self, "id", None),
            "wallet": self.wallet,
            "chain": self.chain,
            "token_address": self.token_address,
            "token_symbol": self.token_symbol,
            "amount": self.amount,
            "entry_price": self.entry_price,
            "entry_at": self.entry_at,
            "status": self.status,
            "exit_price": self.exit_price,
            "exit_at": self.exit_at,
            "realized_pnl": self.realized_pnl,
            "total_cost": self.total_cost(),
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class PortfolioStore:
    """SQLite-backed persistent portfolio store.

    Use :func:`get_portfolio_store` to obtain the process-global instance.

    The store respects ``AGENTOS_STATE_DIR`` via :func:`state_dir` so all
    AgentOS runtime state lives under a single directory tree.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        log_writes: bool = True,
    ) -> None:
        self._db_path_str = str(Path(db_path).resolve())
        self._log_writes = log_writes
        self._schema_initialized: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _ensure_schema(self, db: aiosqlite.Connection) -> None:
        """Run CREATE TABLE / INDEX statements idempotently.

        Uses a class-level flag so we only issue DDL once per process.
        """
        if self._schema_initialized:
            return
        for stmt in DDL_PORTFOLIO:
            stmt = stmt.strip()
            if stmt:
                await db.execute(stmt)
        await db.commit()
        self._schema_initialized = True
        log.info("portfolio_schema_initialized", db_path=self._db_path_str)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_wallet(wallet: str) -> str:
        """Validate and normalize a wallet address.

        Accepts any non-empty string up to 128 chars. Subclasses or
        chain-specific validators may impose stricter rules.
        """
        wallet = wallet.strip()
        if not wallet:
            raise PortfolioStoreValidationError("wallet must be non-empty")
        if len(wallet) > 128:
            raise PortfolioStoreValidationError(
                "wallet must be 128 characters or fewer"
            )
        return wallet

    @staticmethod
    def _validate_chain(chain: str) -> str:
        known = {"ethereum", "solana", "base", "arbitrum", "polygon", "avalanche", "optimism"}
        normalized = chain.strip().lower()
        if normalized not in known:
            log.debug("portfolio_unknown_chain", chain=chain, known=list(known))
        return normalized

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def open_position(
        self,
        *,
        wallet: str,
        chain: str,
        token_address: str,
        token_symbol: str,
        amount: float,
        entry_price: float,
        entry_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Open a new position and return its stable id.

        Args:
            wallet: Owner wallet address.
            chain: Blockchain name (``ethereum``, ``solana``, ...).
            token_address: Token contract address on ``chain``.
            token_symbol: Human-readable symbol (``ETH``, ``USDC``).
            amount: Quantity of tokens acquired. Must be > 0.
            entry_price: Cost per token at acquisition in chain-native token.
                Must be > 0.
            entry_at: Unix timestamp of entry. Defaults to current time.
            metadata: Optional extra key-value data stored as JSON.

        Returns:
            A stable position id (format: ``pos-{wallet_prefix}-{timestamp_ms}``).

        Raises:
            PortfolioStoreValidationError: ``amount`` or ``entry_price`` is not
                strictly positive.
        """
        if amount <= 0:
            raise PortfolioStoreValidationError(
                f"amount must be positive, got {amount!r}"
            )
        if entry_price <= 0:
            raise PortfolioStoreValidationError(
                f"entry_price must be positive, got {entry_price!r}"
            )

        wallet = self._validate_wallet(wallet)
        chain = self._validate_chain(chain)

        pos_id = f"pos-{wallet[:8]}-{int(time.time() * 1000)}"
        entry_ts = entry_at if entry_at is not None else time.time()

        async with aiosqlite.connect(self._db_path_str) as db:
            await self._ensure_schema(db)
            await db.execute(
                """
                INSERT INTO portfolio_positions
                    (id, wallet, chain, token_address, token_symbol,
                     amount, entry_price, entry_at, status, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    pos_id,
                    wallet,
                    chain,
                    token_address.strip(),
                    token_symbol.strip().upper(),
                    amount,
                    entry_price,
                    entry_ts,
                    json.dumps(metadata or {}),
                ),
            )
            await db.commit()

        if self._log_writes:
            log.info(
                "portfolio_position_opened",
                position_id=pos_id,
                wallet=wallet,
                chain=chain,
                token_symbol=token_symbol,
                amount=amount,
                entry_price=entry_price,
            )

        return pos_id

    async def close_position(
        self,
        *,
        position_id: str,
        exit_price: float,
        exit_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> float:
        """Close a position, compute realized PnL, and return it.

        Args:
            position_id: Id returned by :meth:`open_position`.
            exit_price: Price per token at exit. Must be > 0.
            exit_at: Unix timestamp of exit. Defaults to current time.
            metadata: Extra data merged into the position's existing metadata.

        Returns:
            Realized PnL in chain-native token units
            ``(exit_price - entry_price) * amount``.

        Raises:
            PortfolioStoreNotFoundError: No position with this id exists.
            PortfolioStoreStateError: The position is already closed.
            PortfolioStoreValidationError: ``exit_price`` is not strictly positive.
        """
        if exit_price <= 0:
            raise PortfolioStoreValidationError(
                f"exit_price must be positive, got {exit_price!r}"
            )

        async with aiosqlite.connect(self._db_path_str) as db:
            db.row_factory = aiosqlite.Row
            await self._ensure_schema(db)

            cur = await db.execute(
                """
                SELECT id, wallet, token_symbol, amount, entry_price, status
                FROM portfolio_positions
                WHERE id = ?
                """,
                (position_id,),
            )
            row = await cur.fetchone()

            if row is None:
                raise PortfolioStoreNotFoundError(
                    f"position not found: {position_id}"
                )
            if row["status"] != "open":
                raise PortfolioStoreStateError(
                    f"position already closed: {position_id}"
                )

            amount = float(row["amount"])
            entry_price = float(row["entry_price"])
            realized = (exit_price - entry_price) * amount
            exit_ts = exit_at if exit_at is not None else time.time()

            # Merge metadata if provided
            existing_meta = {}
            cur2 = await db.execute(
                "SELECT metadata FROM portfolio_positions WHERE id = ?",
                (position_id,),
            )
            row2 = await cur2.fetchone()
            if row2 and row2["metadata"]:
                try:
                    existing_meta = json.loads(row2["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass

            merged_meta = {**existing_meta, **(metadata or {})}

            await db.execute(
                """
                UPDATE portfolio_positions
                SET status = 'closed',
                    exit_price = ?,
                    exit_at = ?,
                    realized_pnl = ?,
                    metadata = ?
                WHERE id = ?
                """,
                (exit_price, exit_ts, realized, json.dumps(merged_meta), position_id),
            )
            await db.commit()

        if self._log_writes:
            log.info(
                "portfolio_position_closed",
                position_id=position_id,
                wallet=row["wallet"],
                token_symbol=row["token_symbol"],
                amount=amount,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized,
            )

        return realized

    async def update_position_amount(
        self,
        *,
        position_id: str,
        new_amount: float,
    ) -> None:
        """Adjust the token quantity of an open position.

        Useful when a position is partially filled or partially exited.

        Args:
            position_id: Id returned by :meth:`open_position`.
            new_amount: New total quantity. Must be > 0.

        Raises:
            PortfolioStoreNotFoundError: No position with this id exists.
            PortfolioStoreStateError: The position is already closed.
            PortfolioStoreValidationError: ``new_amount`` is not strictly positive.
        """
        if new_amount <= 0:
            raise PortfolioStoreValidationError(
                f"new_amount must be positive, got {new_amount!r}"
            )

        async with aiosqlite.connect(self._db_path_str) as db:
            db.row_factory = aiosqlite.Row
            await self._ensure_schema(db)

            cur = await db.execute(
                "SELECT id, status FROM portfolio_positions WHERE id = ?",
                (position_id,),
            )
            row = await cur.fetchone()

            if row is None:
                raise PortfolioStoreNotFoundError(
                    f"position not found: {position_id}"
                )
            if row["status"] != "open":
                raise PortfolioStoreStateError(
                    f"cannot update closed position: {position_id}"
                )

            await db.execute(
                "UPDATE portfolio_positions SET amount = ? WHERE id = ?",
                (new_amount, position_id),
            )
            await db.commit()

        log.info(
            "portfolio_position_amount_updated",
            position_id=position_id,
            new_amount=new_amount,
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_open(self, wallet: str) -> list[Position]:
        """Return all open positions for a wallet, newest first."""
        return await self._list(self._validate_wallet(wallet), status="open")

    async def list_closed(self, wallet: str) -> list[Position]:
        """Return all closed positions for a wallet, newest first."""
        return await self._list(self._validate_wallet(wallet), status="closed")

    async def list_all(self, wallet: str) -> list[Position]:
        """Return all positions (open + closed) for a wallet, newest first."""
        return await self._list(self._validate_wallet(wallet))

    async def get_position(self, position_id: str) -> Position:
        """Return a single position by id.

        Raises:
            PortfolioStoreNotFoundError: No position with this id exists.
        """
        async with aiosqlite.connect(self._db_path_str) as db:
            db.row_factory = aiosqlite.Row
            await self._ensure_schema(db)
            cur = await db.execute(
                "SELECT * FROM portfolio_positions WHERE id = ?",
                (position_id,),
            )
            row = await cur.fetchone()
        if row is None:
            raise PortfolioStoreNotFoundError(
                f"position not found: {position_id}"
            )
        return self._row_to_position(row)

    async def portfolio_summary(self, wallet: str) -> dict[str, Any]:
        """Return a performance summary for a wallet.

        Includes total positions, realized PnL, and a breakdown by token.
        """
        wallet = self._validate_wallet(wallet)
        async with aiosqlite.connect(self._db_path_str) as db:
            db.row_factory = aiosqlite.Row
            await self._ensure_schema(db)

            cur = await db.execute(
                """
                SELECT
                    COUNT(*) AS total_positions,
                    COUNT(CASE WHEN status = 'open' THEN 1 END) AS open_positions,
                    COUNT(CASE WHEN status = 'closed' THEN 1 END) AS closed_positions,
                    SUM(COALESCE(realized_pnl, 0)) AS total_realized_pnl
                FROM portfolio_positions
                WHERE wallet = ?
                """,
                (wallet,),
            )
            row = await cur.fetchone()

            cur2 = await db.execute(
                """
                SELECT
                    token_symbol,
                    COUNT(*) AS position_count,
                    SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
                    SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_count,
                    SUM(CASE WHEN status = 'closed' THEN COALESCE(realized_pnl, 0) ELSE 0 END)
                        AS realized_pnl
                FROM portfolio_positions
                WHERE wallet = ?
                GROUP BY token_symbol
                ORDER BY realized_pnl DESC
                """,
                (wallet,),
            )
            token_rows = await cur2.fetchall()

        return {
            "wallet": wallet,
            "total_positions": row["total_positions"],
            "open_positions": row["open_positions"],
            "closed_positions": row["closed_positions"],
            "total_realized_pnl": row["total_realized_pnl"] or 0.0,
            "by_token": [
                {
                    "token_symbol": tr["token_symbol"],
                    "position_count": tr["position_count"],
                    "open_count": tr["open_count"],
                    "closed_count": tr["closed_count"],
                    "realized_pnl": tr["realized_pnl"] or 0.0,
                }
                for tr in token_rows
            ],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _list(
        self,
        wallet: str,
        status: str | None = None,
    ) -> list[Position]:
        async with aiosqlite.connect(self._db_path_str) as db:
            db.row_factory = aiosqlite.Row
            await self._ensure_schema(db)

            if status:
                cur = await db.execute(
                    """
                    SELECT * FROM portfolio_positions
                    WHERE wallet = ? AND status = ?
                    ORDER BY entry_at DESC
                    """,
                    (wallet, status),
                )
            else:
                cur = await db.execute(
                    """
                    SELECT * FROM portfolio_positions
                    WHERE wallet = ?
                    ORDER BY entry_at DESC
                    """,
                    (wallet,),
                )
            rows = await cur.fetchall()
        return [self._row_to_position(row) for row in rows]

    def _row_to_position(self, row: aiosqlite.Row) -> Position:
        return Position(
            wallet=row["wallet"],
            chain=row["chain"],
            token_address=row["token_address"],
            token_symbol=row["token_symbol"],
            amount=float(row["amount"]),
            entry_price=float(row["entry_price"]),
            entry_at=float(row["entry_at"]),
            status=row["status"],
            exit_price=float(row["exit_price"])
            if row["exit_price"] is not None
            else None,
            exit_at=float(row["exit_at"]) if row["exit_at"] is not None else None,
            realized_pnl=float(row["realized_pnl"])
            if row["realized_pnl"] is not None
            else None,
            metadata=json.loads(row["metadata"] or "{}"),
        )


# ---------------------------------------------------------------------------
# Process-global singleton (same pattern as get_approval_queue)
# ---------------------------------------------------------------------------

_portfolio_store: PortfolioStore | None = None


def get_portfolio_store(
    *,
    log_writes: bool = True,
) -> PortfolioStore:
    """Return the process-global portfolio store instance.

    The store file lives under ``state_dir("portfolio.db")`` so it respects
    ``AGENTOS_STATE_DIR`` automatically.
    """
    global _portfolio_store  # noqa: PLW0603
    if _portfolio_store is None:
        db_path = state_dir("portfolio.db")
        _portfolio_store = PortfolioStore(db_path, log_writes=log_writes)
        log.debug("portfolio_store_initialized", db_path=str(db_path))
    return _portfolio_store


def reset_portfolio_store() -> None:
    """Reset the global store instance.

    Exists for tests and reconfiguration scenarios.
    """
    global _portfolio_store  # noqa: PLW0603
    _portfolio_store = None
