#!/usr/bin/env python3
"""
OptionPlay - Historical Data Collection via Yahoo Finance
=========================================================

Sammelt historische Preisdaten von Yahoo Finance für längere Zeiträume.
Yahoo bietet kostenlos bis zu 10+ Jahre Historie.

Usage:
    python scripts/collect_historical_yahoo.py --days 780
    python scripts/collect_historical_yahoo.py --years 3
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance nicht installiert")
    print("Run: pip3 install --break-system-packages yfinance")
    sys.exit(1)

from src.backtesting.tracking import TradeTracker, PriceBar
from src.config.watchlist_loader import get_watchlist_loader


def collect_symbol(symbol: str, days: int, tracker: TradeTracker) -> int:
    """Sammelt Daten für ein Symbol von Yahoo Finance"""
    try:
        ticker = yf.Ticker(symbol)

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days + 30)  # Extra Buffer

        hist = ticker.history(start=start_date, end=end_date)

        if hist.empty:
            return 0

        bars = []
        for idx, row in hist.iterrows():
            bar_date = idx.date() if hasattr(idx, "date") else idx
            bars.append(
                PriceBar(
                    date=bar_date,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
            )

        if bars:
            tracker.store_price_data(symbol, bars)
            return len(bars)

        return 0

    except Exception as e:
        print(f"  Error {symbol}: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Collect historical data from Yahoo Finance")
    parser.add_argument(
        "--days", type=int, default=780, help="Days of history (default: 780 = ~3 years)"
    )
    parser.add_argument("--years", type=int, help="Years of history (overrides --days)")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols (default: watchlist)")

    args = parser.parse_args()

    days = args.years * 365 if args.years else args.days

    print("=" * 70)
    print("HISTORICAL DATA COLLECTION (Yahoo Finance)")
    print("=" * 70)
    print(f"\n  Lookback: {days} days (~{days/365:.1f} years)")

    # Symbole laden
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        loader = get_watchlist_loader()
        symbols = sorted(set(loader.get_all_symbols()))

    print(f"  Symbols: {len(symbols)}")
    print()

    tracker = TradeTracker()

    total_bars = 0
    successful = 0
    failed = 0

    for i, symbol in enumerate(symbols, 1):
        pct = (i / len(symbols)) * 100
        bar_width = 25
        filled = int(bar_width * i / len(symbols))
        bar = "█" * filled + "░" * (bar_width - filled)

        print(f"\r[{bar}] {pct:5.1f}% | {symbol:<6} | ", end="", flush=True)

        count = collect_symbol(symbol, days, tracker)

        if count > 0:
            total_bars += count
            successful += 1
            print(f"✓ {count} bars", end="", flush=True)
        else:
            failed += 1
            print(f"✗ failed", end="", flush=True)

    print()
    print()
    print("-" * 70)
    print(f"  Completed: {successful}/{len(symbols)} symbols")
    print(f"  Failed:    {failed}")
    print(f"  Total:     {total_bars:,} price bars")
    print("-" * 70)

    # Status anzeigen
    stats = tracker.get_storage_stats()
    print(
        f"\n  Database: {stats['symbols_with_price_data']} symbols, {stats['total_price_bars']:,} bars"
    )


if __name__ == "__main__":
    main()
