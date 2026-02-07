#!/usr/bin/env python3
"""
OptionPlay - Options Chain Collector (Tradier API)
===================================================

Sammelt aktuelle Options-Chains (Preise + Greeks) von Tradier und
speichert sie in options_prices + options_greeks.

Tradier liefert Greeks (ORATS) direkt mit — kein separater
calculate_greeks.py-Schritt nötig.

Usage:
    # Test mit 3 Symbolen
    python scripts/collect_options_tradier.py --test

    # Spezifische Symbole
    python scripts/collect_options_tradier.py --symbols AAPL,MSFT,SPY

    # Alle Watchlist-Symbole
    python scripts/collect_options_tradier.py --all

    # Status prüfen
    python scripts/collect_options_tradier.py --status
"""

import asyncio
import argparse
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.data_providers.tradier import TradierProvider
from src.data_providers.interface import OptionQuote
from src.config.watchlist_loader import get_watchlist_loader

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE
# =============================================================================

DB_PATH = str(Path.home() / ".optionplay" / "trades.db")


def ensure_schema(db_path: str):
    """Stellt sicher, dass beide Tabellen existieren."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS options_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occ_symbol TEXT NOT NULL,
            underlying TEXT NOT NULL,
            expiration TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            quote_date TEXT NOT NULL,
            bid REAL,
            ask REAL,
            mid REAL,
            last REAL,
            volume INTEGER,
            open_interest INTEGER,
            underlying_price REAL,
            dte INTEGER,
            moneyness REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(occ_symbol, quote_date)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_options_prices_underlying ON options_prices(underlying)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_options_prices_quote_date ON options_prices(quote_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_options_prices_dte ON options_prices(dte)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS options_greeks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            options_price_id INTEGER NOT NULL,
            occ_symbol TEXT NOT NULL,
            quote_date TEXT NOT NULL,
            iv_calculated REAL,
            iv_method TEXT,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(options_price_id),
            FOREIGN KEY (options_price_id) REFERENCES options_prices(id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_options_greeks_occ ON options_greeks(occ_symbol)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_options_greeks_date ON options_greeks(quote_date)")

    conn.commit()
    conn.close()


def store_options_with_greeks(
    db_path: str,
    options: List[OptionQuote],
    quote_date: date,
) -> Tuple[int, int]:
    """
    Speichert Options-Preise UND Greeks in einem Durchgang.

    Returns:
        Tuple von (prices_inserted, greeks_inserted)
    """
    if not options:
        return 0, 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    prices_inserted = 0
    greeks_inserted = 0
    quote_date_str = quote_date.isoformat()

    for opt in options:
        try:
            # Berechne abgeleitete Felder
            dte = (opt.expiry - quote_date).days
            mid = None
            if opt.bid is not None and opt.ask is not None:
                mid = (opt.bid + opt.ask) / 2
            elif opt.last is not None:
                mid = opt.last

            moneyness = None
            if opt.underlying_price and opt.underlying_price > 0:
                moneyness = round(opt.strike / opt.underlying_price, 4)

            # INSERT options_prices
            cursor.execute("""
                INSERT OR REPLACE INTO options_prices (
                    occ_symbol, underlying, expiration, strike, option_type,
                    quote_date, bid, ask, mid, last, volume, open_interest,
                    underlying_price, dte, moneyness
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                opt.symbol,
                opt.underlying,
                opt.expiry.isoformat(),
                opt.strike,
                opt.right,
                quote_date_str,
                opt.bid,
                opt.ask,
                mid,
                opt.last,
                opt.volume or 0,
                opt.open_interest or 0,
                opt.underlying_price,
                dte,
                moneyness,
            ))
            prices_inserted += 1

            # Greeks einfügen falls vorhanden
            has_greeks = any(v is not None for v in [
                opt.delta, opt.gamma, opt.theta, opt.vega, opt.implied_volatility
            ])
            if has_greeks:
                price_id = cursor.lastrowid
                cursor.execute("""
                    INSERT OR REPLACE INTO options_greeks (
                        options_price_id, occ_symbol, quote_date,
                        iv_calculated, iv_method, delta, gamma, theta, vega
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    price_id,
                    opt.symbol,
                    quote_date_str,
                    opt.implied_volatility,
                    "tradier_orats",
                    opt.delta,
                    opt.gamma,
                    opt.theta,
                    opt.vega,
                ))
                greeks_inserted += 1

        except Exception as e:
            logger.debug(f"Insert error for {opt.symbol}: {e}")

    conn.commit()
    conn.close()
    return prices_inserted, greeks_inserted


# =============================================================================
# COLLECTOR
# =============================================================================

@dataclass
class CollectionStats:
    symbols_requested: int = 0
    symbols_with_data: int = 0
    symbols_failed: int = 0
    options_collected: int = 0
    greeks_collected: int = 0
    api_calls: int = 0
    errors: List[str] = field(default_factory=list)


async def collect_symbol(
    provider: TradierProvider,
    symbol: str,
    db_path: str,
    quote_date: date,
    dte_min: int,
    dte_max: int,
) -> Tuple[int, int, Optional[str]]:
    """
    Sammelt Options-Chain für ein Symbol.

    Returns:
        Tuple von (prices_count, greeks_count, error_message)
    """
    try:
        # Hole Puts und Calls
        chain = await provider.get_option_chain(
            symbol,
            dte_min=dte_min,
            dte_max=dte_max,
            right="PC",
        )

        if not chain:
            return 0, 0, None

        prices, greeks = store_options_with_greeks(db_path, chain, quote_date)
        return prices, greeks, None

    except Exception as e:
        return 0, 0, str(e)


async def collect_batch(
    provider: TradierProvider,
    symbols: List[str],
    db_path: str,
    quote_date: date,
    dte_min: int,
    dte_max: int,
    max_workers: int,
) -> CollectionStats:
    """Sammelt Options-Daten für eine Liste von Symbolen."""
    stats = CollectionStats(symbols_requested=len(symbols))

    semaphore = asyncio.Semaphore(max_workers)

    async def worker(symbol: str):
        async with semaphore:
            prices, greeks, error = await collect_symbol(
                provider, symbol, db_path, quote_date, dte_min, dte_max
            )

            if error:
                stats.symbols_failed += 1
                stats.errors.append(f"{symbol}: {error}")
                logger.debug(f"{symbol}: ERROR - {error}")
            elif prices > 0:
                stats.symbols_with_data += 1
                stats.options_collected += prices
                stats.greeks_collected += greeks
            else:
                # Kein Fehler, aber auch keine Daten (normal bei kleinen Symbolen)
                pass

    # Batched processing mit Progress
    batch_size = max_workers * 3
    total_batches = (len(symbols) + batch_size - 1) // batch_size

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        batch_num = i // batch_size + 1

        tasks = [worker(s) for s in batch]
        await asyncio.gather(*tasks)

        pct = min(100, (i + len(batch)) / len(symbols) * 100)
        logger.info(
            f"[{pct:5.1f}%] Batch {batch_num}/{total_batches}: "
            f"{stats.options_collected:,} options, "
            f"{stats.greeks_collected:,} greeks | "
            f"{stats.symbols_with_data} symbols with data"
        )

    return stats


# =============================================================================
# CLI
# =============================================================================

def get_api_key() -> str:
    api_key = os.environ.get('TRADIER_API_KEY')

    if not api_key:
        config_file = Path.home() / ".optionplay" / "config.json"
        if config_file.exists():
            import json
            with open(config_file) as f:
                config = json.load(f)
                api_key = config.get('tradier_api_key')

    if not api_key:
        print("ERROR: No TRADIER_API_KEY found!")
        print("Set it in .env or ~/.optionplay/config.json")
        sys.exit(1)

    return api_key


def show_status():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*), MIN(quote_date), MAX(quote_date) FROM options_prices")
    total, min_date, max_date = cursor.fetchone()

    cursor.execute("SELECT COUNT(DISTINCT underlying) FROM options_prices")
    symbols = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT quote_date) FROM options_prices")
    days = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM options_greeks")
    greeks_total = cursor.fetchone()[0]

    # Letzte 5 Tage
    cursor.execute("""
        SELECT quote_date, COUNT(*) as cnt,
               COUNT(DISTINCT underlying) as syms
        FROM options_prices
        GROUP BY quote_date
        ORDER BY quote_date DESC
        LIMIT 5
    """)
    recent = cursor.fetchall()

    conn.close()

    print("=" * 70)
    print("OPTIONS DATA STATUS")
    print("=" * 70)
    print(f"  Total Records:  {total:,}")
    print(f"  Greeks Records: {greeks_total:,}")
    print(f"  Symbols:        {symbols}")
    print(f"  Trading Days:   {days}")
    print(f"  Date Range:     {min_date} to {max_date}")
    print()
    print("  RECENT DAYS:")
    for dt, cnt, syms in recent:
        print(f"    {dt}: {cnt:>8,} options from {syms:>3} symbols")
    print()


async def main():
    parser = argparse.ArgumentParser(
        description='Collect options chains via Tradier API',
    )
    parser.add_argument('--test', action='store_true',
                        help='Test with SPY, AAPL, MSFT')
    parser.add_argument('--symbols', type=str,
                        help='Comma-separated symbols (e.g. AAPL,MSFT)')
    parser.add_argument('--all', action='store_true',
                        help='All watchlist symbols')
    parser.add_argument('--status', action='store_true',
                        help='Show DB status')
    parser.add_argument('--workers', type=int, default=3,
                        help='Concurrent workers (default: 3, max: 5)')
    parser.add_argument('--dte-min', type=int, default=7,
                        help='Min DTE (default: 7)')
    parser.add_argument('--dte-max', type=int, default=130,
                        help='Max DTE (default: 130)')

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # Symbole bestimmen
    if args.test:
        symbols = ['SPY', 'AAPL', 'MSFT']
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    elif args.all:
        loader = get_watchlist_loader()
        symbols = loader.get_all_symbols()
    else:
        parser.print_help()
        return

    max_workers = min(args.workers, 5)
    quote_date = date.today()

    print("=" * 70)
    print("OPTIONPLAY - TRADIER OPTIONS COLLECTOR")
    print("=" * 70)
    print(f"  Symbols:    {len(symbols)}")
    print(f"  Quote Date: {quote_date}")
    print(f"  DTE Range:  {args.dte_min} - {args.dte_max}")
    print(f"  Workers:    {max_workers}")
    print("=" * 70)
    print()

    ensure_schema(DB_PATH)

    api_key = get_api_key()
    provider = TradierProvider(api_key)

    try:
        await provider.connect()
        logger.info("Connected to Tradier API")

        stats = await collect_batch(
            provider=provider,
            symbols=symbols,
            db_path=DB_PATH,
            quote_date=quote_date,
            dte_min=args.dte_min,
            dte_max=args.dte_max,
            max_workers=max_workers,
        )

    finally:
        await provider.disconnect()

    print()
    print("=" * 70)
    print("COLLECTION COMPLETE")
    print("=" * 70)
    print(f"  Symbols requested:  {stats.symbols_requested}")
    print(f"  Symbols with data:  {stats.symbols_with_data}")
    print(f"  Symbols failed:     {stats.symbols_failed}")
    print(f"  Options collected:  {stats.options_collected:,}")
    print(f"  Greeks collected:   {stats.greeks_collected:,}")
    print()

    if stats.errors:
        print(f"  ERRORS ({len(stats.errors)}):")
        for err in stats.errors[:10]:
            print(f"    {err}")
        if len(stats.errors) > 10:
            print(f"    ... and {len(stats.errors) - 10} more")
        print()

    show_status()


if __name__ == '__main__':
    asyncio.run(main())
