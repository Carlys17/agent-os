"""V013 — portfolio_positions table for persistent token-position tracking.

For a fresh database this is a near no-op (PortfolioStore._ensure_schema
creates the table with its indexes on first write).  For an existing database
carried over from a pre-portfolio release this step is also a no-op because
``CREATE TABLE IF NOT EXISTS`` and ``CREATE INDEX IF NOT EXISTS`` are
idempotent.

Rollback is a no-op — the table and indexes are dropped with
``IF EXISTS`` so a failed migration never corrupts existing data.
"""

from __future__ import annotations

__depends__: set[str] = {"V012__projects_name_unique"}


def _table_exists(conn, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def apply_step(conn) -> None:
    """Ensure the portfolio_positions table and its indexes exist.

    Safe to call on both fresh and pre-existing databases.
    """
    if not _table_exists(conn, "portfolio_positions"):
        conn.execute(
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
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_portfolio_wallet "
            "ON portfolio_positions(wallet, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_portfolio_token "
            "ON portfolio_positions(token_address)"
        )


def rollback_step(conn) -> None:
    """Drop the portfolio positions table if it exists.

    Uses ``IF EXISTS`` so a failed apply still allows rollback.
    """
    conn.execute("DROP TABLE IF EXISTS portfolio_positions")
