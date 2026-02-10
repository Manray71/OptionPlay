#!/usr/bin/env python3
"""
OptionPlay - Future Earnings Date Collector (Tradier Beta API)
==============================================================

Holt zukünftige Earnings-Termine von Tradier's Beta Fundamentals API
(/beta/markets/fundamentals/calendars) und speichert sie in der
earnings_history-Tabelle.

Ersetzt collect_earnings_marketdata.py — nutzt den bereits vorhandenen
Tradier API-Key statt Marketdata.app.

Usage:
    # Test mit 5 Symbolen
    python scripts/collect_earnings_tradier.py --test

    # Alle Watchlist-Symbole
    python scripts/collect_earnings_tradier.py --all

    # Spezifische Symbole
    python scripts/collect_earnings_tradier.py --symbols AAPL,MSFT,GOOGL

    # Nur Status anzeigen
    python scripts/collect_earnings_tradier.py --status
"""

import argparse
import logging
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

import requests

from src.cache.earnings_history import EarningsHistoryManager
from src.config.watchlist_loader import get_watchlist_loader

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Tradier Beta API
TRADIER_BASE_URL = "https://api.tradier.com/beta"
BATCH_SIZE = 50  # Symbols per request (tested: 50 in ~1.6s)

# Event types for earnings (Tradier corporate_calendars)
# Results: 7=Q1, 8=Q2, 9=Q3, 10=Q4
# Conference Calls: 12=Q1, 13=Q2, 14=Q3, 15=Q4
EARNINGS_RESULT_TYPES = {7, 8, 9, 10}
EARNINGS_CALL_TYPES = {12, 13, 14, 15}
EARNINGS_EVENT_TYPES = EARNINGS_RESULT_TYPES | EARNINGS_CALL_TYPES

# Map event_type to fiscal quarter
EVENT_TYPE_TO_QUARTER = {
    7: "Q1", 8: "Q2", 9: "Q3", 10: "Q4",
    12: "Q1", 13: "Q2", 14: "Q3", 15: "Q4",
}

# ETFs (keine Earnings)
ETFS = {
    'SPY', 'QQQ', 'IWM', 'DIA', 'XLK', 'XLF', 'XLE', 'XLV',
    'XLI', 'XLY', 'XLP', 'XLU', 'XLRE', 'XLB', 'XLC', 'ARKK',
}


def _parse_time_of_day(event_text: str) -> str:
    """Parse time_of_day from event description."""
    text_lower = event_text.lower()
    if "before" in text_lower or "bmo" in text_lower:
        return "bmo"
    if "after" in text_lower or "amc" in text_lower:
        return "amc"
    return "during market hours"


def _deduplicate_earnings(events: List[Dict]) -> List[Dict]:
    """
    Deduplicate earnings events by date.

    When both Results and Conference Call exist for the same date,
    prefer the Results event (types 7-10) as it's the actual release.
    """
    by_date: Dict[str, Dict] = {}

    for ev in events:
        dt = ev["begin_date_time"]
        et = ev["event_type"]

        if dt not in by_date:
            by_date[dt] = ev
        elif et in EARNINGS_RESULT_TYPES and by_date[dt]["event_type"] in EARNINGS_CALL_TYPES:
            # Prefer results over conference call
            by_date[dt] = ev

    return list(by_date.values())


def fetch_calendars_batch(
    symbols: List[str],
    api_key: str,
) -> Dict[str, List[Dict]]:
    """
    Fetch corporate calendars for a batch of symbols from Tradier Beta API.

    Returns:
        Dict mapping symbol -> list of earnings dicts ready for save_earnings()
    """
    resp = requests.get(
        f"{TRADIER_BASE_URL}/markets/fundamentals/calendars",
        params={"symbols": ",".join(symbols)},
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    today_str = date.today().isoformat()
    result: Dict[str, List[Dict]] = {}

    for item in data:
        symbol = item.get("request", "")
        results_list = item.get("results", [])

        earnings_events = []
        for r in results_list:
            cals = r.get("tables", {}).get("corporate_calendars") or []
            for cal in cals:
                if cal.get("event_type") not in EARNINGS_EVENT_TYPES:
                    continue
                earnings_events.append(cal)

        if not earnings_events:
            result[symbol] = []
            continue

        # Deduplicate (Results + Conference Call on same date)
        unique_events = _deduplicate_earnings(earnings_events)

        # Convert to save_earnings() format
        earnings_list = []
        for ev in unique_events:
            earnings_date = ev["begin_date_time"]
            quarter = EVENT_TYPE_TO_QUARTER.get(ev["event_type"], "")
            fiscal_year = ev.get("event_fiscal_year")
            event_text = ev.get("event", "")
            is_future = earnings_date >= today_str

            earnings_list.append({
                "earnings_date": earnings_date,
                "fiscal_year": fiscal_year,
                "fiscal_quarter": quarter,
                "eps_actual": None,  # Future: no EPS yet
                "eps_estimate": None,
                "eps_surprise": None,
                "eps_surprise_pct": None,
                "time_of_day": _parse_time_of_day(event_text),
            })

        result[symbol] = earnings_list

    return result


def collect_earnings(
    symbols: List[str],
    api_key: str,
    future_only: bool = False,
) -> Dict:
    """
    Collect earnings from Tradier for all symbols and save to DB.

    Args:
        symbols: List of ticker symbols
        api_key: Tradier API key
        future_only: If True, only save future earnings dates

    Returns:
        Stats dict
    """
    manager = EarningsHistoryManager()
    today_str = date.today().isoformat()

    stats = {
        "total": len(symbols),
        "with_data": 0,
        "no_data": 0,
        "errors": 0,
        "records_saved": 0,
        "future_found": 0,
        "error_symbols": [],
    }

    # Process in batches
    batches = [symbols[i:i + BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]

    for batch_idx, batch in enumerate(batches):
        pct = (batch_idx + 1) / len(batches) * 100

        try:
            results = fetch_calendars_batch(batch, api_key)

            for symbol, earnings_list in results.items():
                if future_only:
                    earnings_list = [e for e in earnings_list if e["earnings_date"] >= today_str]

                if earnings_list:
                    saved = manager.save_earnings(symbol, earnings_list, source="tradier")
                    stats["records_saved"] += saved
                    stats["with_data"] += 1

                    future = [e for e in earnings_list if e["earnings_date"] >= today_str]
                    if future:
                        stats["future_found"] += 1
                else:
                    stats["no_data"] += 1

            logger.info(
                f"[{pct:5.1f}%] Batch {batch_idx + 1}/{len(batches)} "
                f"({len(batch)} symbols) | "
                f"Total: {stats['records_saved']:,} saved, "
                f"{stats['future_found']} with future dates"
            )

            # Small delay between batches
            if batch_idx < len(batches) - 1:
                time.sleep(0.2)

        except Exception as e:
            stats["errors"] += len(batch)
            for s in batch:
                stats["error_symbols"].append(f"{s}: {e}")
            logger.error(f"Batch {batch_idx + 1} error: {e}")

    return stats


def show_status():
    """Show earnings data status."""
    import sqlite3
    db_path = str(Path.home() / ".optionplay" / "trades.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Total stats
    cursor.execute("SELECT COUNT(*), COUNT(DISTINCT symbol) FROM earnings_history")
    total_records, total_symbols = cursor.fetchone()

    cursor.execute("SELECT MIN(earnings_date), MAX(earnings_date) FROM earnings_history")
    min_date, max_date = cursor.fetchone()

    # Future earnings
    today_str = date.today().isoformat()
    cursor.execute("""
        SELECT COUNT(DISTINCT symbol), COUNT(*)
        FROM earnings_history
        WHERE earnings_date >= ?
    """, (today_str,))
    future_symbols, future_records = cursor.fetchone()

    # Symbols without future earnings
    cursor.execute("""
        SELECT symbol, MAX(earnings_date) as last_date
        FROM earnings_history
        GROUP BY symbol
        HAVING MAX(earnings_date) < ?
        ORDER BY last_date DESC
    """, (today_str,))
    missing_future = cursor.fetchall()

    # Next 30 days
    next_30 = (date.today() + timedelta(days=30)).isoformat()
    cursor.execute("""
        SELECT symbol, earnings_date, time_of_day
        FROM earnings_history
        WHERE earnings_date >= ? AND earnings_date <= ?
        ORDER BY earnings_date
    """, (today_str, next_30))
    upcoming = cursor.fetchall()

    # Source breakdown
    cursor.execute("""
        SELECT source, COUNT(*), COUNT(DISTINCT symbol)
        FROM earnings_history
        GROUP BY source
    """)
    sources = cursor.fetchall()

    conn.close()

    # Watchlist
    loader = get_watchlist_loader()
    watchlist = set(loader.get_all_symbols()) - ETFS

    print()
    print("=" * 70)
    print("EARNINGS DATA STATUS")
    print("=" * 70)
    print(f"  Total Records:       {total_records:,}")
    print(f"  Symbols with data:   {total_symbols}")
    print(f"  Date Range:          {min_date} to {max_date}")
    print()
    print(f"  Future Earnings:     {future_records} records for {future_symbols} symbols")
    print(f"  Missing Future:      {len(missing_future)} symbols")
    print(f"  Watchlist Stocks:    {len(watchlist)}")
    print()
    print("  BY SOURCE:")
    for src, cnt, syms in sources:
        print(f"    {src:15s}: {cnt:,} records ({syms} symbols)")
    print()

    if upcoming:
        print(f"  UPCOMING EARNINGS (next 30 days, {len(upcoming)} total):")
        for sym, dt, tod in upcoming[:25]:
            tod_str = f" ({tod})" if tod else ""
            print(f"    {dt} {sym:6s}{tod_str}")
        if len(upcoming) > 25:
            print(f"    ... and {len(upcoming) - 25} more")
        print()

    if missing_future:
        print(f"  SYMBOLS WITHOUT FUTURE EARNINGS ({len(missing_future)}):")
        for sym, last_dt in missing_future[:30]:
            print(f"    {sym:6s}  last: {last_dt}")
        if len(missing_future) > 30:
            print(f"    ... and {len(missing_future) - 30} more")
        print()


def get_api_key() -> str:
    """Get Tradier API key from environment."""
    api_key = os.environ.get('TRADIER_API_KEY')

    if not api_key:
        env_file = project_root / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith('TRADIER_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
                        break

    if not api_key:
        print("ERROR: No TRADIER_API_KEY found!")
        print("Set it in .env or as environment variable")
        sys.exit(1)

    return api_key


def main():
    parser = argparse.ArgumentParser(
        description='Collect earnings dates from Tradier Beta Fundamentals API',
    )
    parser.add_argument('--test', action='store_true',
                        help='Test with 5 symbols')
    parser.add_argument('--symbols', type=str,
                        help='Comma-separated symbols')
    parser.add_argument('--all', action='store_true',
                        help='All watchlist symbols')
    parser.add_argument('--status', action='store_true',
                        help='Show earnings data status')
    parser.add_argument('--future-only', action='store_true',
                        help='Only save future earnings (skip historical)')

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # Determine symbols
    if args.test:
        symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META']
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    elif args.all:
        loader = get_watchlist_loader()
        all_symbols = loader.get_all_symbols()
        symbols = [s for s in all_symbols if s not in ETFS]
    else:
        parser.print_help()
        return

    api_key = get_api_key()

    print("=" * 70)
    print("OPTIONPLAY - EARNINGS COLLECTOR (Tradier Beta API)")
    print("=" * 70)
    print(f"  Symbols:     {len(symbols)}")
    print(f"  Date:        {date.today()}")
    print(f"  Batch Size:  {BATCH_SIZE}")
    print(f"  Future Only: {args.future_only}")
    print("=" * 70)
    print()

    t0 = time.time()
    stats = collect_earnings(symbols, api_key, future_only=args.future_only)
    elapsed = time.time() - t0

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
    print(f"  Time:               {elapsed:.1f}s")
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
    main()
