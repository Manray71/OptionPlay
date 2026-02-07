#!/usr/bin/env python3
"""
OptionPlay - Future Earnings Date Collector (Marketdata.app)
=============================================================

Holt zukünftige Earnings-Termine (inkl. EPS, time_of_day) von
Marketdata.app und speichert sie in der earnings_history-Tabelle.

Löst das Problem, dass der Earnings-Prefilter 70% der Symbole
ausschließt, weil keine Future-Earnings in der DB vorliegen.

Usage:
    # Test mit 5 Symbolen
    python scripts/collect_earnings_marketdata.py --test

    # Alle Watchlist-Symbole
    python scripts/collect_earnings_marketdata.py --all

    # Spezifische Symbole
    python scripts/collect_earnings_marketdata.py --symbols AAPL,MSFT,GOOGL

    # Status anzeigen
    python scripts/collect_earnings_marketdata.py --status
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.data_providers.marketdata import MarketDataProvider
from src.cache.earnings_history import EarningsHistoryManager
from src.config.watchlist_loader import get_watchlist_loader

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# =============================================================================
# COLLECTOR
# =============================================================================

async def collect_earnings(
    symbols: List[str],
    api_key: str,
    from_date: str = "2024-01-01",
    to_date: Optional[str] = None,
) -> dict:
    """
    Holt Earnings-Daten von Marketdata.app und speichert in DB.

    Holt historische + zukünftige Earnings inkl. EPS und time_of_day.
    """
    if to_date is None:
        # Bis Ende nächstes Jahr, um zukünftige Termine zu erfassen
        to_date = f"{date.today().year + 1}-12-31"

    manager = EarningsHistoryManager()

    stats = {
        "total": len(symbols),
        "with_data": 0,
        "no_data": 0,
        "errors": 0,
        "records_saved": 0,
        "future_found": 0,
        "error_symbols": [],
    }

    provider = MarketDataProvider(api_key)

    try:
        await provider.connect()
        logger.info(f"Connected to Marketdata.app")

        for i, symbol in enumerate(symbols):
            pct = (i + 1) / len(symbols) * 100

            try:
                earnings = await provider.get_historical_earnings(
                    symbol,
                    from_date=from_date,
                    to_date=to_date,
                )

                if earnings:
                    saved = manager.save_earnings(symbol, earnings, source="marketdata")
                    stats["records_saved"] += saved
                    stats["with_data"] += 1

                    # Zähle zukünftige Termine
                    today_str = date.today().isoformat()
                    future = [e for e in earnings if e["earnings_date"] >= today_str]
                    if future:
                        stats["future_found"] += 1

                    if (i + 1) % 25 == 0 or (i + 1) == len(symbols):
                        logger.info(
                            f"[{pct:5.1f}%] {i+1}/{len(symbols)} | "
                            f"{symbol}: {saved} records | "
                            f"Total: {stats['records_saved']:,} saved, "
                            f"{stats['future_found']} with future dates"
                        )
                else:
                    stats["no_data"] += 1
                    logger.debug(f"{symbol}: no earnings data")

                # Rate limiting (Marketdata.app: 6000 req/min)
                await asyncio.sleep(0.05)

            except Exception as e:
                stats["errors"] += 1
                stats["error_symbols"].append(f"{symbol}: {e}")
                logger.debug(f"{symbol}: ERROR - {e}")

    finally:
        await provider.disconnect()

    return stats


# =============================================================================
# STATUS
# =============================================================================

def show_status():
    """Zeigt Earnings-Daten-Status."""
    manager = EarningsHistoryManager()

    import sqlite3
    db_path = str(Path.home() / ".optionplay" / "trades.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Gesamtstatistik
    cursor.execute("SELECT COUNT(*), COUNT(DISTINCT symbol) FROM earnings_history")
    total_records, total_symbols = cursor.fetchone()

    cursor.execute("SELECT MIN(earnings_date), MAX(earnings_date) FROM earnings_history")
    min_date, max_date = cursor.fetchone()

    # Zukünftige Earnings
    today_str = date.today().isoformat()
    cursor.execute("""
        SELECT COUNT(DISTINCT symbol), COUNT(*)
        FROM earnings_history
        WHERE earnings_date >= ?
    """, (today_str,))
    future_symbols, future_records = cursor.fetchone()

    # Nächste 30 Tage
    from datetime import timedelta
    next_30 = (date.today() + timedelta(days=30)).isoformat()
    cursor.execute("""
        SELECT symbol, earnings_date, time_of_day
        FROM earnings_history
        WHERE earnings_date >= ? AND earnings_date <= ?
        ORDER BY earnings_date
    """, (today_str, next_30))
    upcoming = cursor.fetchall()

    # Symbole OHNE Earnings
    cursor.execute("""
        SELECT COUNT(DISTINCT symbol) FROM earnings_history
    """)
    db_symbols = cursor.fetchone()[0]

    conn.close()

    # Watchlist laden
    loader = get_watchlist_loader()
    watchlist = set(loader.get_all_symbols())
    # ETFs haben keine Earnings
    etfs = {'SPY', 'QQQ', 'IWM', 'DIA', 'XLK', 'XLF', 'XLE', 'XLV',
            'XLI', 'XLY', 'XLP', 'XLU', 'XLRE', 'XLB', 'XLC', 'ARKK'}
    stocks = watchlist - etfs
    symbols_with_data = set()

    import sqlite3 as sq
    conn2 = sq.connect(db_path)
    c2 = conn2.cursor()
    c2.execute("SELECT DISTINCT symbol FROM earnings_history")
    symbols_with_data = {row[0] for row in c2.fetchall()}
    conn2.close()

    missing = stocks - symbols_with_data

    print()
    print("=" * 70)
    print("EARNINGS DATA STATUS")
    print("=" * 70)
    print(f"  Total Records:       {total_records:,}")
    print(f"  Symbols with data:   {total_symbols}")
    print(f"  Date Range:          {min_date} to {max_date}")
    print()
    print(f"  Future Earnings:     {future_records} records for {future_symbols} symbols")
    print(f"  Watchlist Stocks:    {len(stocks)}")
    print(f"  Missing Earnings:    {len(missing)} symbols")
    print()

    if upcoming:
        print("  UPCOMING EARNINGS (next 30 days):")
        for sym, dt, tod in upcoming[:20]:
            tod_str = f" ({tod})" if tod else ""
            print(f"    {dt} {sym:6s}{tod_str}")
        if len(upcoming) > 20:
            print(f"    ... and {len(upcoming) - 20} more")
        print()

    if missing:
        print(f"  MISSING SYMBOLS ({len(missing)}):")
        for s in sorted(missing)[:30]:
            print(f"    {s}")
        if len(missing) > 30:
            print(f"    ... and {len(missing) - 30} more")
        print()


# =============================================================================
# CLI
# =============================================================================

def get_api_key() -> str:
    api_key = os.environ.get('MARKETDATA_API_KEY')

    if not api_key:
        config_file = Path.home() / ".optionplay" / "config.json"
        if config_file.exists():
            import json
            with open(config_file) as f:
                config = json.load(f)
                api_key = config.get('marketdata_api_key')

    if not api_key:
        env_file = project_root / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith('MARKETDATA_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
                        break

    if not api_key:
        print("ERROR: No MARKETDATA_API_KEY found!")
        print("Set it in .env or ~/.optionplay/config.json")
        sys.exit(1)

    return api_key


async def main():
    parser = argparse.ArgumentParser(
        description='Collect future earnings dates from Marketdata.app',
    )
    parser.add_argument('--test', action='store_true',
                        help='Test with 5 symbols')
    parser.add_argument('--symbols', type=str,
                        help='Comma-separated symbols')
    parser.add_argument('--all', action='store_true',
                        help='All watchlist symbols')
    parser.add_argument('--status', action='store_true',
                        help='Show earnings data status')

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # Symbole bestimmen
    if args.test:
        symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META']
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    elif args.all:
        loader = get_watchlist_loader()
        all_symbols = loader.get_all_symbols()
        # ETFs filtern (haben keine Earnings)
        etfs = {'SPY', 'QQQ', 'IWM', 'DIA', 'XLK', 'XLF', 'XLE', 'XLV',
                'XLI', 'XLY', 'XLP', 'XLU', 'XLRE', 'XLB', 'XLC', 'ARKK'}
        symbols = [s for s in all_symbols if s not in etfs]
    else:
        parser.print_help()
        return

    api_key = get_api_key()

    print("=" * 70)
    print("OPTIONPLAY - EARNINGS COLLECTOR (Marketdata.app)")
    print("=" * 70)
    print(f"  Symbols: {len(symbols)}")
    print(f"  Date:    {date.today()}")
    print("=" * 70)
    print()

    stats = await collect_earnings(symbols, api_key)

    print()
    print("=" * 70)
    print("COLLECTION COMPLETE")
    print("=" * 70)
    print(f"  Symbols processed:  {stats['total']}")
    print(f"  With earnings data: {stats['with_data']}")
    print(f"  No data available:  {stats['no_data']}")
    print(f"  Errors:             {stats['errors']}")
    print(f"  Records saved:      {stats['records_saved']:,}")
    print(f"  Future dates found: {stats['future_found']}")
    print()

    if stats["error_symbols"]:
        print(f"  ERRORS ({len(stats['error_symbols'])}):")
        for err in stats["error_symbols"][:10]:
            print(f"    {err}")
        if len(stats["error_symbols"]) > 10:
            print(f"    ... and {len(stats['error_symbols']) - 10} more")
        print()

    show_status()


if __name__ == '__main__':
    asyncio.run(main())
