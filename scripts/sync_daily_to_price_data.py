#!/usr/bin/env python3
"""
Sync daily_prices → price_data (PriceStorage)

Reads real OHLCV data from daily_prices table and writes it
into the price_data table (compressed JSON) used by the training pipeline.

Usage:
    python3 scripts/sync_daily_to_price_data.py
"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting import TradeTracker
from src.backtesting.tracking.models import PriceBar

DB_PATH = Path.home() / ".optionplay" / "trades.db"


def main():
    print("=" * 60)
    print("  SYNC daily_prices → price_data")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    tracker = TradeTracker()

    # Get all symbols from daily_prices
    cursor = conn.execute("""
        SELECT DISTINCT symbol FROM daily_prices
        ORDER BY symbol
    """)
    symbols = [row["symbol"] for row in cursor.fetchall()]
    print(f"\n  Symbols in daily_prices: {len(symbols)}")

    synced = 0
    errors = 0
    total_bars = 0

    for i, symbol in enumerate(symbols, 1):
        try:
            rows = conn.execute(
                """
                SELECT quote_date, open, high, low, close, volume
                FROM daily_prices
                WHERE symbol = ?
                ORDER BY quote_date ASC
            """,
                (symbol,),
            ).fetchall()

            if not rows:
                continue

            bars = [
                PriceBar(
                    date=date.fromisoformat(row["quote_date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                )
                for row in rows
            ]

            count = tracker.store_price_data(symbol, bars, merge=True)
            total_bars += count
            synced += 1

            if i % 50 == 0 or i == len(symbols):
                print(f"  [{i}/{len(symbols)}] {symbol}: {count} bars synced")

        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(symbols)}] {symbol}: ERROR - {e}")

    conn.close()

    print(f"\n{'=' * 60}")
    print(f"  SYNC COMPLETE")
    print(f"  Symbols synced: {synced}")
    print(f"  Total bars:     {total_bars:,}")
    print(f"  Errors:         {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
