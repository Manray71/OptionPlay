#!/usr/bin/env python3
"""
OptionPlay - Collect Dividend History from yfinance
====================================================

Populates the dividend_history table with ex-dividend dates and amounts.
Used by E.5 (Dividend-Gap-Handling) to prevent false pullback/dip signals.

Usage:
    # All symbols from symbol_fundamentals
    python scripts/collect_dividends.py

    # Specific symbols
    python scripts/collect_dividends.py --symbols AAPL MSFT GOOGL

    # Only dividend-paying symbols (dividend_yield > 0)
    python scripts/collect_dividends.py --payers-only
"""

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".optionplay" / "trades.db"


def get_all_symbols() -> List[str]:
    """Gets all symbols from symbol_fundamentals"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT symbol FROM symbol_fundamentals ORDER BY symbol")
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    logger.info(f"symbol_fundamentals: {len(symbols)} symbols found")
    return symbols


def get_dividend_payers() -> List[str]:
    """Gets symbols with dividend_yield > 0"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        SELECT symbol FROM symbol_fundamentals
        WHERE dividend_yield IS NOT NULL AND dividend_yield > 0
        ORDER BY symbol
    """)
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    logger.info(f"Dividend payers: {len(symbols)} symbols")
    return symbols


def fetch_dividends_from_yfinance(symbol: str) -> List[Dict[str, Any]]:
    """
    Fetches historical dividend data from yfinance.

    Returns:
        List of dicts with ex_date, amount
    """
    try:
        import yfinance as yf

        # yfinance uses "-" instead of "." for share classes (BRK.B -> BRK-B)
        yf_symbol = symbol.replace(".", "-")
        ticker = yf.Ticker(yf_symbol)

        dividends = ticker.dividends
        if dividends is None or dividends.empty:
            return []

        results = []
        for dt, amount in dividends.items():
            ex_date = dt.date() if hasattr(dt, "date") else dt
            results.append(
                {
                    "ex_date": ex_date.isoformat(),
                    "amount": round(float(amount), 4),
                }
            )

        return results

    except Exception as e:
        logger.warning(f"Error fetching dividends for {symbol}: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Collect dividend history from yfinance")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to collect")
    parser.add_argument("--payers-only", action="store_true", help="Only dividend-paying symbols")
    parser.add_argument(
        "--delay", type=float, default=0.3, help="Delay between API calls (seconds)"
    )
    args = parser.parse_args()

    # Determine symbols
    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    elif args.payers_only:
        symbols = get_dividend_payers()
    else:
        symbols = get_all_symbols()

    if not symbols:
        logger.error("No symbols found")
        return

    logger.info(f"Collecting dividends for {len(symbols)} symbols...")

    # Import manager
    from src.cache.dividend_history import get_dividend_history_manager

    manager = get_dividend_history_manager()

    total = len(symbols)
    success = 0
    total_records = 0

    for i, symbol in enumerate(symbols, 1):
        dividends = fetch_dividends_from_yfinance(symbol)

        if dividends:
            count = manager.save_dividends(symbol, dividends, source="yfinance")
            total_records += count
            success += 1
            logger.info(f"[{i}/{total}] {symbol}: {count} dividends saved")
        else:
            logger.debug(f"[{i}/{total}] {symbol}: no dividends")

        if i < total and args.delay > 0:
            time.sleep(args.delay)

    logger.info(f"Done: {success}/{total} symbols with dividends, {total_records} total records")

    # Print statistics
    stats = manager.get_statistics()
    logger.info(f"DB stats: {stats['total_symbols']} symbols, {stats['total_records']} records")
    if stats["date_range"]["from"]:
        logger.info(f"Date range: {stats['date_range']['from']} to {stats['date_range']['to']}")


if __name__ == "__main__":
    main()
