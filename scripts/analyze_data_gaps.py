#!/usr/bin/env python3
"""
OptionPlay - Datenlücken-Analyse und -Schließung
=================================================

Analysiert fehlende Daten in der options_prices Tabelle und
ermöglicht gezieltes Nachladen.

Usage:
    # Analyse der Lücken
    python scripts/analyze_data_gaps.py --analyze

    # Lücken schließen
    python scripts/analyze_data_gaps.py --fill --workers 20

    # Nur bestimmte Symbole nachladen
    python scripts/analyze_data_gaps.py --fill --symbols AAPL,MSFT
"""

import asyncio
import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Set, Tuple
from collections import defaultdict

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
)
from src.config.watchlist_loader import get_watchlist_loader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_all_symbols() -> List[str]:
    """Lädt alle Watchlist-Symbole."""
    loader = get_watchlist_loader()
    return loader.get_all_symbols()


def get_trading_days(start_date: date, end_date: date) -> List[date]:
    """Gibt alle Handelstage (Mo-Fr) zwischen zwei Daten zurück."""
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Mo-Fr
            days.append(current)
        current += timedelta(days=1)
    return days


def analyze_gaps(db_path: str) -> Dict:
    """
    Analysiert Datenlücken in der options_prices Tabelle.

    Returns:
        Dict mit Analyse-Ergebnissen
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Alle Symbole in der DB
    cursor.execute("SELECT DISTINCT underlying FROM options_prices")
    db_symbols = {row[0] for row in cursor.fetchall()}

    # Alle erwarteten Symbole
    expected_symbols = set(get_all_symbols())

    # Fehlende Symbole
    missing_symbols = expected_symbols - db_symbols

    # Datumsbereich
    cursor.execute("SELECT MIN(quote_date), MAX(quote_date) FROM options_prices")
    date_range = cursor.fetchone()
    min_date = date.fromisoformat(date_range[0]) if date_range[0] else None
    max_date = date.fromisoformat(date_range[1]) if date_range[1] else None

    # Handelstage pro Monat analysieren
    cursor.execute("""
        SELECT
            strftime('%Y-%m', quote_date) as month,
            COUNT(DISTINCT quote_date) as trading_days,
            COUNT(DISTINCT underlying) as symbols,
            COUNT(*) as records
        FROM options_prices
        GROUP BY month
        ORDER BY month
    """)
    monthly_stats = cursor.fetchall()

    # Erwartete Handelstage pro Monat (ca. 20-22)
    monthly_gaps = []
    for month, days, symbols, records in monthly_stats:
        year, mon = map(int, month.split('-'))
        # Typischerweise 20-22 Handelstage pro Monat
        if days < 18:
            monthly_gaps.append({
                'month': month,
                'trading_days': days,
                'symbols': symbols,
                'records': records,
                'missing_days_estimate': 20 - days,
            })

    # Symbole mit wenig Daten
    cursor.execute("""
        SELECT
            underlying,
            COUNT(DISTINCT quote_date) as trading_days,
            COUNT(*) as records,
            MIN(quote_date) as first_date,
            MAX(quote_date) as last_date
        FROM options_prices
        GROUP BY underlying
        ORDER BY trading_days ASC
        LIMIT 50
    """)
    symbols_with_few_days = cursor.fetchall()

    # Lücken pro Symbol-Monat finden
    cursor.execute("""
        SELECT
            underlying,
            strftime('%Y-%m', quote_date) as month,
            COUNT(DISTINCT quote_date) as days
        FROM options_prices
        GROUP BY underlying, month
        HAVING days < 15
        ORDER BY underlying, month
    """)
    symbol_month_gaps = cursor.fetchall()

    conn.close()

    return {
        'date_range': (min_date, max_date),
        'db_symbols': len(db_symbols),
        'expected_symbols': len(expected_symbols),
        'missing_symbols': list(missing_symbols)[:20],  # Top 20
        'missing_symbols_count': len(missing_symbols),
        'monthly_stats': monthly_stats,
        'monthly_gaps': monthly_gaps,
        'symbols_with_few_days': symbols_with_few_days[:20],
        'symbol_month_gaps': symbol_month_gaps[:50],
    }


def print_analysis(analysis: Dict):
    """Gibt die Analyse-Ergebnisse aus."""
    print("\n" + "=" * 70)
    print("DATENLÜCKEN-ANALYSE")
    print("=" * 70)

    # Übersicht
    print(f"\n--- ÜBERSICHT ---")
    print(f"Datumsbereich: {analysis['date_range'][0]} bis {analysis['date_range'][1]}")
    print(f"Symbole in DB: {analysis['db_symbols']}")
    print(f"Erwartete Symbole: {analysis['expected_symbols']}")
    print(f"Fehlende Symbole: {analysis['missing_symbols_count']}")

    if analysis['missing_symbols']:
        print(f"\nFehlende Symbole (Top 20): {', '.join(analysis['missing_symbols'][:20])}")

    # Monatliche Übersicht
    print(f"\n--- MONATLICHE DATEN ---")
    print(f"{'Monat':<10} {'Tage':>8} {'Symbole':>10} {'Records':>12}")
    print("-" * 45)
    for month, days, symbols, records in analysis['monthly_stats']:
        flag = " ⚠️" if days < 18 else ""
        print(f"{month:<10} {days:>8} {symbols:>10} {records:>12,}{flag}")

    # Monate mit Lücken
    if analysis['monthly_gaps']:
        print(f"\n--- MONATE MIT LÜCKEN ---")
        for gap in analysis['monthly_gaps']:
            print(f"  {gap['month']}: nur {gap['trading_days']} Tage (ca. {gap['missing_days_estimate']} fehlen)")

    # Symbole mit wenig Daten
    print(f"\n--- SYMBOLE MIT WENIG DATEN (Top 20) ---")
    print(f"{'Symbol':<10} {'Tage':>8} {'Records':>10} {'Erster':>12} {'Letzter':>12}")
    print("-" * 55)
    for symbol, days, records, first, last in analysis['symbols_with_few_days']:
        print(f"{symbol:<10} {days:>8} {records:>10,} {first:>12} {last:>12}")

    # Symbol-Monat Lücken
    if analysis['symbol_month_gaps']:
        print(f"\n--- SYMBOL-MONAT LÜCKEN (Top 50) ---")
        gaps_by_month = defaultdict(list)
        for symbol, month, days in analysis['symbol_month_gaps']:
            gaps_by_month[month].append((symbol, days))

        for month in sorted(gaps_by_month.keys()):
            symbols_info = gaps_by_month[month]
            print(f"  {month}: {len(symbols_info)} Symbole mit <15 Tagen")


def get_gaps_to_fill(db_path: str) -> List[Tuple[str, str, int]]:
    """
    Findet Symbol-Monat Kombinationen, die nachgeladen werden sollten.

    Returns:
        Liste von (symbol, month, missing_days_estimate)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Finde Symbol-Monat Kombinationen mit wenig Daten
    cursor.execute("""
        SELECT
            underlying,
            strftime('%Y-%m', quote_date) as month,
            COUNT(DISTINCT quote_date) as days
        FROM options_prices
        WHERE quote_date < '2025-12-01'  -- Nur historische
        GROUP BY underlying, month
        HAVING days < 15
        ORDER BY month, underlying
    """)
    gaps = cursor.fetchall()

    conn.close()

    # Konvertiere zu Liste mit geschätzten fehlenden Tagen
    return [(symbol, month, 20 - days) for symbol, month, days in gaps]


async def fill_gaps(
    gaps: List[Tuple[str, str, int]],
    workers: int = 20,
    rpm: int = 5000,
):
    """
    Füllt die identifizierten Lücken.
    """
    if not gaps:
        logger.info("Keine Lücken zu füllen!")
        return

    api_key = get_api_key()
    db_path = get_db_path()

    collector = OptionsCollector(
        api_key=api_key,
        db_path=db_path,
        requests_per_minute=rpm,
        concurrent_workers=workers,
    )

    # Gruppiere nach Monat
    gaps_by_month = defaultdict(list)
    for symbol, month, missing in gaps:
        gaps_by_month[month].append(symbol)

    logger.info(f"Fülle Lücken für {len(gaps)} Symbol-Monat Kombinationen")
    logger.info(f"Betroffene Monate: {len(gaps_by_month)}")

    semaphore = asyncio.Semaphore(workers)
    total_filled = 0

    async with MarketdataClient(api_key, rpm) as client:
        for month, symbols in sorted(gaps_by_month.items()):
            year, mon = map(int, month.split('-'))

            logger.info(f"Processing {month} ({len(symbols)} symbols)...")

            # Alle Handelstage des Monats
            from calendar import monthrange
            _, last_day = monthrange(year, mon)

            for day in range(1, last_day + 1):
                trade_date = date(year, mon, day)
                if trade_date.weekday() >= 5:  # Skip Wochenende
                    continue
                if trade_date >= date.today():  # Skip Zukunft
                    continue

                tasks = []
                for symbol in symbols:
                    task = collector._process_symbol_date(client, symbol, trade_date, semaphore)
                    tasks.append(task)

                results = await asyncio.gather(*tasks, return_exceptions=True)

                batch_options = []
                for result in results:
                    if isinstance(result, list) and result:
                        batch_options.extend(result)

                if batch_options:
                    stored = store_options(db_path, batch_options)
                    total_filled += stored

            logger.info(f"  {month}: +{total_filled:,} options")

    logger.info(f"\nTotal filled: {total_filled:,} options")


def main():
    parser = argparse.ArgumentParser(description='Analyze and fill data gaps')
    parser.add_argument('--analyze', action='store_true', help='Analyze gaps')
    parser.add_argument('--fill', action='store_true', help='Fill gaps')
    parser.add_argument('--workers', type=int, default=20, help='Workers')
    parser.add_argument('--rpm', type=int, default=5000, help='Requests per minute')
    parser.add_argument('--symbols', type=str, help='Specific symbols to fill')

    args = parser.parse_args()
    db_path = get_db_path()

    if args.analyze or (not args.analyze and not args.fill):
        analysis = analyze_gaps(db_path)
        print_analysis(analysis)

    if args.fill:
        gaps = get_gaps_to_fill(db_path)

        if args.symbols:
            target_symbols = set(s.strip().upper() for s in args.symbols.split(','))
            gaps = [(s, m, d) for s, m, d in gaps if s in target_symbols]

        logger.info(f"Found {len(gaps)} gaps to fill")
        asyncio.run(fill_gaps(gaps, args.workers, args.rpm))


if __name__ == '__main__':
    main()
