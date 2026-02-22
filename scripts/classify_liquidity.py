#!/usr/bin/env python3
"""
OptionPlay - Classify Liquidity Tiers
======================================

Classifies symbols into liquidity tiers based on put option Open Interest
at 60-90 DTE from the local options_prices database.

Tiers:
  - Tier 1 (median OI > 500): Always executable
  - Tier 2 (median OI 50-500): Usually executable
  - Tier 3 (median OI < 50): Limited

Updates symbol_fundamentals with:
  - liquidity_tier (INTEGER: 1, 2, 3)
  - avg_put_oi (REAL: Median OI of puts)

Usage:
    # All symbols
    python scripts/classify_liquidity.py

    # Specific symbols
    python scripts/classify_liquidity.py --symbols AAPL MSFT

    # Dry run (no DB writes)
    python scripts/classify_liquidity.py --dry-run
"""

import argparse
import logging
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".optionplay" / "trades.db"

# Tier thresholds
TIER_1_MIN_OI = 500
TIER_2_MIN_OI = 100


def assign_tier(median_oi: float) -> int:
    """Assign liquidity tier based on median put OI.

    Args:
        median_oi: Median open interest for puts at 60-90 DTE.

    Returns:
        1, 2, or 3.
    """
    if median_oi > TIER_1_MIN_OI:
        return 1
    elif median_oi >= TIER_2_MIN_OI:
        return 2
    else:
        return 3


def get_symbols_from_fundamentals(conn: sqlite3.Connection) -> List[str]:
    """Get all symbols from symbol_fundamentals."""
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT symbol FROM symbol_fundamentals ORDER BY symbol")
    return [row[0] for row in cursor.fetchall()]


def calculate_median_put_oi(conn: sqlite3.Connection, symbol: str) -> Optional[float]:
    """Calculate median per-strike put OI at 60-90 DTE for a symbol.

    Queries per-strike OI (not summed across strikes) from the most recent
    90 days of data. The median of individual strike OI values reflects what
    a trader actually sees when placing a spread order.

    Args:
        conn: SQLite connection to trades.db
        symbol: Ticker symbol

    Returns:
        Median per-strike put OI or None if insufficient data.
    """
    cursor = conn.cursor()

    # Get per-strike OI values (NOT summed across strikes)
    cursor.execute(
        """
        SELECT open_interest
        FROM options_prices
        WHERE underlying = ?
          AND option_type IN ('put', 'P')
          AND dte BETWEEN 60 AND 90
          AND open_interest IS NOT NULL
          AND open_interest > 0
          AND quote_date >= (
              SELECT date(MAX(quote_date), '-90 days')
              FROM options_prices
              WHERE underlying = ?
          )
        """,
        (symbol.upper(), symbol.upper()),
    )

    rows = cursor.fetchall()
    if len(rows) < 10:
        return None

    oi_values = [row[0] for row in rows]
    return statistics.median(oi_values)


def ensure_columns(conn: sqlite3.Connection) -> None:
    """Add liquidity_tier and avg_put_oi columns if missing."""
    cursor = conn.cursor()
    for col, col_type in (("liquidity_tier", "INTEGER"), ("avg_put_oi", "REAL")):
        try:
            cursor.execute(f"SELECT {col} FROM symbol_fundamentals LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE symbol_fundamentals ADD COLUMN {col} {col_type}")
            logger.info(f"Added column {col} to symbol_fundamentals")
    conn.commit()


def update_symbol_tier(conn: sqlite3.Connection, symbol: str, tier: int, median_oi: float) -> bool:
    """Update liquidity_tier and avg_put_oi for a symbol."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE symbol_fundamentals
            SET liquidity_tier = ?, avg_put_oi = ?, updated_at = datetime('now')
            WHERE symbol = ?
            """,
            (tier, round(median_oi, 1), symbol.upper()),
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Error updating {symbol}: {e}")
        return False


def classify_symbols(
    symbols: Optional[List[str]] = None, dry_run: bool = False
) -> Dict[int, List[str]]:
    """Classify symbols into liquidity tiers.

    Args:
        symbols: Optional list of symbols. If None, uses all from fundamentals.
        dry_run: If True, compute but don't write to DB.

    Returns:
        Dict mapping tier -> list of symbols.
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)

    if not dry_run:
        ensure_columns(conn)

    if symbols:
        symbols = [s.upper() for s in symbols]
    else:
        symbols = get_symbols_from_fundamentals(conn)

    logger.info(f"Classifying {len(symbols)} symbols")

    tiers: Dict[int, List[str]] = {1: [], 2: [], 3: []}
    no_data = []

    for i, symbol in enumerate(symbols, 1):
        median_oi = calculate_median_put_oi(conn, symbol)

        if median_oi is None:
            no_data.append(symbol)
            if not dry_run:
                # Set tier 3 for symbols without data
                update_symbol_tier(conn, symbol, 3, 0.0)
            logger.debug(f"[{i}/{len(symbols)}] {symbol}: no OI data -> Tier 3")
            tiers[3].append(symbol)
            continue

        tier = assign_tier(median_oi)
        tiers[tier].append(symbol)

        if not dry_run:
            update_symbol_tier(conn, symbol, tier, median_oi)

        logger.info(f"[{i}/{len(symbols)}] {symbol}: median OI={median_oi:.0f} -> Tier {tier}")

    conn.close()
    return tiers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify symbols into liquidity tiers based on put OI"
    )
    parser.add_argument(
        "--symbols",
        "-s",
        nargs="+",
        help="Specific symbols to classify",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute tiers without writing to DB",
    )

    args = parser.parse_args()

    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        sys.exit(1)

    tiers = classify_symbols(symbols=args.symbols, dry_run=args.dry_run)

    # Summary
    print(f"\n{'='*50}")
    print("LIQUIDITY TIER CLASSIFICATION")
    print(f"{'='*50}")
    for tier_num in (1, 2, 3):
        symbols = tiers[tier_num]
        label = {1: "High (OI > 500)", 2: "Medium (100-500)", 3: "Low (< 100)"}
        print(f"Tier {tier_num} ({label[tier_num]}): {len(symbols)} symbols")
    total = sum(len(v) for v in tiers.values())
    print(f"Total: {total} symbols")

    if args.dry_run:
        print("\n[DRY RUN - no changes saved]")


if __name__ == "__main__":
    main()
