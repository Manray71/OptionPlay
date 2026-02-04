#!/usr/bin/env python3
"""
OptionPlay - 5-Year Historical Options Collector
=================================================

Sammelt historische Options-Daten für 5 Jahre von Marketdata.app.

Filter:
- Strikes: ±20% vom Spot
- Expirations: Nur 4 monatliche Verfallsdaten (3. Freitag)

Usage:
    python scripts/collect_options_5years.py --start
    python scripts/collect_options_5years.py --status
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional
from calendar import monthcalendar, FRIDAY

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.collect_options_prices import (
    OptionsCollector,
    MarketdataClient,
    ensure_schema,
    store_options,
    get_api_key,
    get_db_path,
    show_status,
)
from src.config.watchlist_loader import get_watchlist_loader

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_available_months() -> List[date]:
    """
    Gibt die Monate zurück, für die Marketdata.app Daten hat.
    Basiert auf dem Scan-Ergebnis: ~70% der Monate haben Daten.
    """
    # Bekannte verfügbare Monate (aus dem Scan)
    available = [
        # 2021
        (2021, 1), (2021, 3), (2021, 4), (2021, 6), (2021, 7),
        (2021, 9), (2021, 10), (2021, 11), (2021, 12),
        # 2022
        (2022, 2), (2022, 3), (2022, 6), (2022, 7), (2022, 8),
        (2022, 9), (2022, 11), (2022, 12),
        # 2023
        (2023, 2), (2023, 3), (2023, 5), (2023, 6), (2023, 8),
        (2023, 9), (2023, 11), (2023, 12),
        # 2024
        (2024, 2), (2024, 3), (2024, 4), (2024, 5), (2024, 7),
        (2024, 8), (2024, 10), (2024, 11),
        # 2025
        (2025, 1), (2025, 4), (2025, 5), (2025, 7), (2025, 8),
        (2025, 9), (2025, 10), (2025, 12),
        # 2026
        (2026, 1),
    ]

    return [date(y, m, 15) for y, m in available]


def get_collected_months(db_path: str) -> set:
    """Gibt bereits gesammelte Monate zurück."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT strftime('%Y-%m', quote_date) as month
        FROM options_prices
        WHERE quote_date < '2025-12-01'  -- Nur historische Monate
    """)
    months = {row[0] for row in cursor.fetchall()}
    conn.close()
    return months


def get_trading_days_for_month(year: int, month: int) -> List[date]:
    """Gibt alle Handelstage (Mo-Fr) für einen Monat zurück."""
    from calendar import monthrange

    _, last_day = monthrange(year, month)
    days = []

    for day in range(1, last_day + 1):
        d = date(year, month, day)
        if d.weekday() < 5:  # Mo-Fr
            days.append(d)

    return days


async def collect_month(
    collector: OptionsCollector,
    client: MarketdataClient,
    symbols: List[str],
    year: int,
    month: int,
    semaphore: asyncio.Semaphore,
) -> int:
    """Sammelt Daten für einen Monat."""

    trading_days = get_trading_days_for_month(year, month)
    total_collected = 0

    for trade_date in trading_days:
        # Skip Zukunft
        if trade_date >= date.today():
            continue

        tasks = []
        for symbol in symbols:
            task = collector._process_symbol_date(client, symbol, trade_date, semaphore)
            tasks.append(task)

        # Parallel ausführen
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Sammle erfolgreiche Ergebnisse
        batch_options = []
        for result in results:
            if isinstance(result, list) and result:
                batch_options.extend(result)

        # In DB speichern
        if batch_options:
            stored = store_options(collector.db_path, batch_options)
            total_collected += stored

    return total_collected


async def main_collect(symbols: List[str], workers: int = 20, rpm: int = 6000):
    """Hauptfunktion für 5-Jahres-Sammlung."""

    api_key = get_api_key()
    db_path = get_db_path()

    ensure_schema(db_path)

    collector = OptionsCollector(
        api_key=api_key,
        db_path=db_path,
        requests_per_minute=rpm,
        concurrent_workers=workers,
    )

    available_months = get_available_months()

    # Bereits gesammelte Monate überspringen
    collected = get_collected_months(db_path)
    remaining_months = [
        m for m in available_months
        if f"{m.year}-{m.month:02d}" not in collected
    ]

    total_months = len(remaining_months)
    skipped = len(available_months) - total_months

    logger.info(f"Starting 5-year collection")
    logger.info(f"Symbols: {len(symbols)}")
    logger.info(f"Available months: {len(available_months)}, Already collected: {skipped}, Remaining: {total_months}")
    logger.info(f"Workers: {workers}, RPM: {rpm}")

    semaphore = asyncio.Semaphore(workers)
    total_collected = 0

    async with MarketdataClient(api_key, rpm) as client:
        for i, month_date in enumerate(remaining_months):
            year = month_date.year
            month = month_date.month

            logger.info(f"[{i+1}/{total_months}] Processing {year}-{month:02d}...")

            month_collected = await collect_month(
                collector, client, symbols, year, month, semaphore
            )

            total_collected += month_collected

            progress = (i + 1) / total_months * 100
            logger.info(
                f"[{progress:5.1f}%] {year}-{month:02d}: {month_collected:,} options | "
                f"Total: {total_collected:,}"
            )

    logger.info(f"\n{'='*60}")
    logger.info(f"COLLECTION COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Total options collected: {total_collected:,}")

    return total_collected


def main():
    parser = argparse.ArgumentParser(description='Collect 5 years of historical options')
    parser.add_argument('--start', action='store_true', help='Start collection')
    parser.add_argument('--status', action='store_true', help='Show status')
    parser.add_argument('--workers', type=int, default=50, help='Concurrent workers')
    parser.add_argument('--rpm', type=int, default=8000, help='Requests per minute')
    parser.add_argument('--symbols', type=str, help='Comma-separated symbols (default: all)')

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if not args.start:
        parser.print_help()
        return

    # Symbole laden
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    else:
        loader = get_watchlist_loader()
        symbols = loader.get_all_symbols()

    logger.info(f"Loaded {len(symbols)} symbols")

    # Collection starten
    asyncio.run(main_collect(symbols, args.workers, args.rpm))

    # Status anzeigen
    show_status()


if __name__ == '__main__':
    main()
