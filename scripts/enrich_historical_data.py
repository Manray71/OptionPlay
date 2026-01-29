#!/usr/bin/env python3
"""
Enrich Historical Data from Tradier and Marketdata.app

This script extends historical price data in the database using multiple data providers.
Primary: Tradier API (better historical coverage)
Fallback: Marketdata.app API

Usage:
    python scripts/enrich_historical_data.py --min-bars 750  # Enrich symbols with < 3 years
    python scripts/enrich_historical_data.py --symbols AAPL,MSFT  # Specific symbols
    python scripts/enrich_historical_data.py --all  # All symbols
    python scripts/enrich_historical_data.py --dry-run  # Preview without changes
    python scripts/enrich_historical_data.py --provider tradier  # Use Tradier only
"""

import argparse
import asyncio
import aiohttp
import gzip
import json
import logging
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from data_providers.marketdata import MarketDataProvider, HistoricalBar

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DB_PATH = Path.home() / ".optionplay" / "trades.db"
MARKETDATA_API_KEY = os.environ.get("MARKETDATA_API_KEY", "***REMOVED_MARKETDATA_KEY***")
TRADIER_API_KEY = os.environ.get("TRADIER_API_KEY", "***REMOVED_TRADIER_KEY***")
MAX_DAYS = 1260  # ~5 years
RATE_LIMIT_DELAY = 0.15  # 150ms between requests


# =============================================================================
# TRADIER PROVIDER (Primary - better historical coverage)
# =============================================================================

class TradierHistoricalProvider:
    """Simple Tradier client for historical data only."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.tradier.com"
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json"
                }
            )

    async def disconnect(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_historical(self, symbol: str, days: int = 1260) -> List[HistoricalBar]:
        """Fetch historical data from Tradier."""
        if not self._session:
            await self.connect()

        start = (date.today() - timedelta(days=int(days * 1.5))).isoformat()
        end = date.today().isoformat()

        params = {
            "symbol": symbol.upper(),
            "interval": "daily",
            "start": start,
            "end": end
        }

        try:
            async with self._session.get(
                f"{self.base_url}/v1/markets/history",
                params=params
            ) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()

                if "history" not in data or not data["history"]:
                    return []

                days_data = data["history"].get("day", [])
                if not days_data:
                    return []

                # Handle single day response (not a list)
                if isinstance(days_data, dict):
                    days_data = [days_data]

                bars = []
                for day in days_data:
                    try:
                        bar = HistoricalBar(
                            symbol=symbol.upper(),
                            date=datetime.strptime(day["date"], "%Y-%m-%d").date(),
                            open=float(day.get("open", 0)),
                            high=float(day.get("high", 0)),
                            low=float(day.get("low", 0)),
                            close=float(day.get("close", 0)),
                            volume=int(day.get("volume", 0)),
                            source="tradier"
                        )
                        bars.append(bar)
                    except (KeyError, ValueError) as e:
                        continue

                # Sort by date and limit
                bars.sort(key=lambda x: x.date)
                if len(bars) > days:
                    bars = bars[-days:]

                return bars

        except Exception as e:
            logger.warning(f"Tradier error for {symbol}: {e}")
            return []


def get_db_connection() -> sqlite3.Connection:
    """Get database connection."""
    return sqlite3.connect(str(DB_PATH))


def get_symbols_needing_enrichment(conn: sqlite3.Connection, min_bars: int = 750) -> List[Tuple[str, int, str, str]]:
    """Get symbols with less than min_bars of data."""
    cursor = conn.execute("""
        SELECT symbol, bar_count, start_date, end_date
        FROM price_data
        WHERE bar_count < ?
        ORDER BY bar_count ASC
    """, (min_bars,))
    return cursor.fetchall()


def get_all_symbols(conn: sqlite3.Connection) -> List[Tuple[str, int, str, str]]:
    """Get all symbols."""
    cursor = conn.execute("""
        SELECT symbol, bar_count, start_date, end_date
        FROM price_data
        ORDER BY symbol
    """)
    return cursor.fetchall()


def get_symbol_data(conn: sqlite3.Connection, symbol: str) -> Optional[Tuple[int, str, str, bytes]]:
    """Get existing data for a symbol."""
    cursor = conn.execute("""
        SELECT bar_count, start_date, end_date, data_compressed
        FROM price_data
        WHERE symbol = ?
    """, (symbol,))
    return cursor.fetchone()


def decompress_bars(data_compressed: bytes) -> List[Dict]:
    """Decompress stored bar data."""
    if not data_compressed:
        return []
    try:
        # Try gzip first
        decompressed = gzip.decompress(data_compressed)
        return json.loads(decompressed.decode('utf-8'))
    except gzip.BadGzipFile:
        # Fall back to zlib (older format)
        try:
            import zlib
            decompressed = zlib.decompress(data_compressed)
            return json.loads(decompressed.decode('utf-8'))
        except Exception as e:
            logger.warning(f"Failed to decompress with zlib: {e}")
            return []
    except Exception as e:
        logger.warning(f"Failed to decompress data: {e}")
        return []


def compress_bars(bars: List[Dict]) -> bytes:
    """Compress bar data for storage."""
    json_data = json.dumps(bars).encode('utf-8')
    return gzip.compress(json_data, compresslevel=9)


def bars_to_dict_list(bars: List[HistoricalBar]) -> List[Dict]:
    """Convert HistoricalBar objects to dicts for storage."""
    result = []
    for bar in bars:
        result.append({
            'date': bar.date.isoformat() if isinstance(bar.date, date) else bar.date,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume
        })
    return result


def merge_bar_data(existing: List[Dict], new_bars: List[HistoricalBar]) -> List[Dict]:
    """Merge existing and new bar data, removing duplicates."""
    # Convert existing to dict by date
    by_date = {}
    for bar in existing:
        bar_date = bar.get('date', bar.get('d'))
        if bar_date:
            by_date[bar_date] = bar

    # Add new bars
    for bar in new_bars:
        bar_date = bar.date.isoformat() if isinstance(bar.date, date) else bar.date
        # Only add if not already present (prefer existing data)
        if bar_date not in by_date:
            by_date[bar_date] = {
                'date': bar_date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            }

    # Sort by date
    sorted_bars = sorted(by_date.values(), key=lambda x: x.get('date', x.get('d', '')))
    return sorted_bars


def update_symbol_data(conn: sqlite3.Connection, symbol: str, bars: List[Dict]):
    """Update symbol data in database."""
    if not bars:
        return

    # Get date range
    dates = [b.get('date', b.get('d', '')) for b in bars]
    dates = [d for d in dates if d]
    if not dates:
        return

    start_date = min(dates)
    end_date = max(dates)
    bar_count = len(bars)

    # Compress data
    data_compressed = compress_bars(bars)

    # Update or insert
    conn.execute("""
        INSERT OR REPLACE INTO price_data
        (symbol, start_date, end_date, bar_count, data_compressed, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?,
                COALESCE((SELECT created_at FROM price_data WHERE symbol = ?), ?),
                ?)
    """, (symbol, start_date, end_date, bar_count, data_compressed,
          symbol, datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit()


async def enrich_symbol(
    tradier: TradierHistoricalProvider,
    marketdata: MarketDataProvider,
    conn: sqlite3.Connection,
    symbol: str,
    current_bars: int,
    current_start: str,
    dry_run: bool = False,
    provider_preference: str = "tradier"
) -> Tuple[str, int, int, str]:
    """
    Enrich a single symbol with more historical data.

    Returns: (symbol, old_bars, new_bars, status)
    """
    try:
        # Try primary provider first
        if provider_preference == "tradier":
            new_bars = await tradier.get_historical(symbol, days=MAX_DAYS)
            if not new_bars or len(new_bars) < 100:
                # Fallback to marketdata
                new_bars = await marketdata.get_historical(symbol, days=MAX_DAYS)
        else:
            new_bars = await marketdata.get_historical(symbol, days=MAX_DAYS)
            if not new_bars or len(new_bars) < 100:
                # Fallback to tradier
                new_bars = await tradier.get_historical(symbol, days=MAX_DAYS)

        if not new_bars:
            return (symbol, current_bars, current_bars, "no_data")

        # Get existing data
        existing_data = get_symbol_data(conn, symbol)
        existing_bars = []
        if existing_data and existing_data[3]:
            existing_bars = decompress_bars(existing_data[3])

        # Merge data
        merged = merge_bar_data(existing_bars, new_bars)
        new_count = len(merged)

        if new_count <= current_bars:
            return (symbol, current_bars, new_count, "no_improvement")

        if dry_run:
            return (symbol, current_bars, new_count, "dry_run")

        # Save merged data
        update_symbol_data(conn, symbol, merged)

        # Get new date range
        dates = [b.get('date', b.get('d', '')) for b in merged if b.get('date') or b.get('d')]
        new_start = min(dates) if dates else current_start

        return (symbol, current_bars, new_count, f"enriched: {current_start} -> {new_start}")

    except Exception as e:
        logger.error(f"Error enriching {symbol}: {e}")
        return (symbol, current_bars, current_bars, f"error: {str(e)[:50]}")


async def enrich_all(
    symbols_data: List[Tuple[str, int, str, str]],
    dry_run: bool = False,
    workers: int = 1,
    provider_preference: str = "tradier"
) -> Dict[str, Tuple[int, int, str]]:
    """Enrich all specified symbols."""

    # Initialize providers
    tradier = TradierHistoricalProvider(api_key=TRADIER_API_KEY)
    await tradier.connect()

    marketdata = MarketDataProvider(api_key=MARKETDATA_API_KEY)
    await marketdata.connect()

    conn = get_db_connection()
    results = {}

    total = len(symbols_data)
    enriched = 0
    failed = 0
    no_change = 0

    print(f"\nEnriching {total} symbols (primary: {provider_preference})...")
    print(f"{'='*60}")

    for i, (symbol, bar_count, start_date, end_date) in enumerate(symbols_data):
        result = await enrich_symbol(
            tradier, marketdata, conn, symbol, bar_count, start_date, dry_run, provider_preference
        )

        symbol, old_bars, new_bars, status = result
        results[symbol] = (old_bars, new_bars, status)

        if "enriched" in status:
            enriched += 1
            improvement = new_bars - old_bars
            print(f"[{i+1}/{total}] {symbol}: {old_bars} -> {new_bars} bars (+{improvement}) ✓")
        elif status == "no_improvement" or status == "no_data":
            no_change += 1
            if i % 20 == 0:  # Only print every 20th
                print(f"[{i+1}/{total}] {symbol}: {old_bars} bars (no change)")
        elif status == "dry_run":
            enriched += 1
            improvement = new_bars - old_bars
            print(f"[{i+1}/{total}] {symbol}: {old_bars} -> {new_bars} bars (+{improvement}) [DRY RUN]")
        else:
            failed += 1
            print(f"[{i+1}/{total}] {symbol}: {status}")

        # Rate limiting
        if i < total - 1:
            await asyncio.sleep(RATE_LIMIT_DELAY)

    await tradier.disconnect()
    await marketdata.disconnect()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  Enriched: {enriched}")
    print(f"  No change: {no_change}")
    print(f"  Failed: {failed}")
    print(f"  Total: {total}")

    return results


def print_summary(conn: sqlite3.Connection):
    """Print database summary."""
    cursor = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(bar_count) as total_bars,
            MIN(start_date) as earliest,
            MAX(end_date) as latest,
            AVG(bar_count) as avg_bars
        FROM price_data
    """)
    row = cursor.fetchone()

    print(f"\nDatabase Summary:")
    print(f"  Symbols: {row[0]}")
    print(f"  Total Bars: {row[1]:,}")
    print(f"  Date Range: {row[2]} to {row[3]}")
    print(f"  Avg Bars/Symbol: {row[4]:.0f}")

    # Distribution
    cursor = conn.execute("""
        SELECT
            CASE
                WHEN bar_count < 252 THEN '< 1 year'
                WHEN bar_count < 504 THEN '1-2 years'
                WHEN bar_count < 756 THEN '2-3 years'
                WHEN bar_count < 1008 THEN '3-4 years'
                ELSE '4+ years'
            END as range,
            COUNT(*) as count
        FROM price_data
        GROUP BY 1
        ORDER BY MIN(bar_count)
    """)

    print(f"\n  Data Coverage:")
    for range_name, count in cursor.fetchall():
        print(f"    {range_name}: {count} symbols")


def main():
    parser = argparse.ArgumentParser(description='Enrich historical data from Marketdata.app')
    parser.add_argument('--symbols', '-s', help='Comma-separated symbols')
    parser.add_argument('--min-bars', type=int, default=750, help='Enrich symbols with fewer bars (default: 750 = ~3 years)')
    parser.add_argument('--all', '-a', action='store_true', help='Enrich all symbols')
    parser.add_argument('--dry-run', '-n', action='store_true', help='Preview without making changes')
    parser.add_argument('--workers', type=int, default=1, help='Number of workers (currently unused)')
    parser.add_argument('--provider', choices=['tradier', 'marketdata'], default='tradier',
                        help='Primary data provider (default: tradier)')
    parser.add_argument('--summary', action='store_true', help='Just show database summary')

    args = parser.parse_args()

    conn = get_db_connection()

    if args.summary:
        print_summary(conn)
        conn.close()
        return

    # Determine which symbols to process
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
        symbols_data = []
        for sym in symbols:
            data = get_symbol_data(conn, sym)
            if data:
                symbols_data.append((sym, data[0], data[1], data[2]))
            else:
                symbols_data.append((sym, 0, '', ''))
    elif args.all:
        symbols_data = get_all_symbols(conn)
    else:
        symbols_data = get_symbols_needing_enrichment(conn, args.min_bars)

    if not symbols_data:
        print("No symbols to process.")
        conn.close()
        return

    print(f"\nHistorical Data Enrichment")
    print(f"{'='*60}")
    print(f"Symbols to process: {len(symbols_data)}")
    print(f"Min bars threshold: {args.min_bars}")
    print(f"Max historical days: {MAX_DAYS} (~5 years)")
    print(f"Primary provider: {args.provider}")
    print(f"Dry run: {args.dry_run}")

    # Show current summary
    print_summary(conn)
    conn.close()

    # Run enrichment
    asyncio.run(enrich_all(symbols_data, dry_run=args.dry_run, workers=args.workers, provider_preference=args.provider))

    # Show updated summary
    if not args.dry_run:
        conn = get_db_connection()
        print("\n" + "="*60)
        print("AFTER ENRICHMENT:")
        print_summary(conn)
        conn.close()


if __name__ == "__main__":
    main()
