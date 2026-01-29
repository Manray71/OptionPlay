#!/usr/bin/env python3
"""
OptionPlay - Tradier Historical Data Backfill Script
=====================================================

Erweitert historische Daten rückwärts für Symbole mit kurzer Historie.
Verwendet Tradier API (unterstützt 5+ Jahre historische Daten).

Usage:
    # Status anzeigen
    python scripts/backfill_tradier.py --status

    # Dryrun
    python scripts/backfill_tradier.py --dryrun

    # Backfill ausführen (Standard: 3 Jahre zurück)
    python scripts/backfill_tradier.py --backfill

    # Mit spezifischer Zieltiefe
    python scripts/backfill_tradier.py --backfill --target-years 5
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.backtesting.trade_tracker import TradeTracker, PriceBar
from src.data_providers.tradier import TradierProvider
from src.config.watchlist_loader import get_watchlist_loader


@dataclass
class BackfillConfig:
    """Konfiguration für Backfill"""
    target_years: int = 3  # Ziel: X Jahre Historie
    min_delay_seconds: float = 0.5  # Tradier erlaubt mehr Requests
    min_bars_threshold: int = 500  # Symbole mit weniger als X bars werden erweitert


@dataclass
class BackfillInfo:
    """Info über benötigtes Backfill für ein Symbol"""
    symbol: str
    current_start: date
    current_end: date
    current_bars: int
    target_start: date
    days_to_backfill: int
    needs_backfill: bool


def analyze_backfill_needs(
    tracker: TradeTracker,
    watchlist_symbols: set,
    config: BackfillConfig
) -> Tuple[List[BackfillInfo], Dict]:
    """Analysiert welche Symbole Backfill benötigen."""

    today = date.today()
    target_start = today - timedelta(days=config.target_years * 365)

    db_symbols = tracker.list_symbols_with_price_data()
    db_symbol_map = {s['symbol']: s for s in db_symbols}

    results = []
    needs_backfill_count = 0
    total_days_to_fetch = 0

    for symbol in sorted(watchlist_symbols):
        if symbol not in db_symbol_map:
            continue

        info = db_symbol_map[symbol]
        current_start = date.fromisoformat(info['start_date'])
        current_end = date.fromisoformat(info['end_date'])
        current_bars = info['bar_count']

        # Prüfe ob Backfill nötig
        needs_backfill = current_bars < config.min_bars_threshold and current_start > target_start
        days_to_backfill = (current_start - target_start).days if needs_backfill else 0

        results.append(BackfillInfo(
            symbol=symbol,
            current_start=current_start,
            current_end=current_end,
            current_bars=current_bars,
            target_start=target_start,
            days_to_backfill=days_to_backfill,
            needs_backfill=needs_backfill
        ))

        if needs_backfill:
            needs_backfill_count += 1
            total_days_to_fetch += days_to_backfill

    summary = {
        'total_symbols': len(results),
        'needs_backfill': needs_backfill_count,
        'already_complete': len(results) - needs_backfill_count,
        'target_start': target_start.isoformat(),
        'target_years': config.target_years,
        'min_bars_threshold': config.min_bars_threshold,
        'total_days_to_fetch': total_days_to_fetch,
    }

    return results, summary


class TradierBackfillCollector:
    """Sammelt historische Daten rückwärts via Tradier"""

    def __init__(self, api_key: str, config: BackfillConfig):
        self.api_key = api_key
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._provider: Optional[TradierProvider] = None

    async def connect(self):
        self._provider = TradierProvider(self.api_key)
        connected = await self._provider.connect()
        if not connected:
            raise ConnectionError("Could not connect to Tradier API")
        self.logger.info("Connected to Tradier API")

    async def disconnect(self):
        if self._provider:
            await self._provider.disconnect()

    async def backfill_symbol(
        self,
        tracker: TradeTracker,
        info: BackfillInfo,
    ) -> Tuple[bool, int, str]:
        """
        Holt ältere Daten für ein Symbol.

        Returns:
            Tuple von (success, bars_added, message)
        """
        if not info.needs_backfill:
            return True, 0, "no backfill needed"

        try:
            # Berechne wie viele Tage wir ab heute zurück brauchen
            today = date.today()
            days_from_today = (today - info.target_start).days + 100  # Puffer

            # Tradier unterstützt bis zu 5+ Jahre
            days_to_fetch = min(days_from_today, 2000)

            bars = await self._provider.get_historical(
                info.symbol,
                days=days_to_fetch
            )

            if not bars:
                return False, 0, "no data returned"

            # Filtere nur Bars VOR dem aktuellen Start-Datum
            price_bars = []
            for bar in bars:
                bar_date = bar.date if isinstance(bar.date, date) else date.fromisoformat(str(bar.date)[:10])

                # Nur Bars vor dem aktuellen Start
                if bar_date < info.current_start:
                    price_bars.append(PriceBar(
                        date=bar_date,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                    ))

            if not price_bars:
                return True, 0, "no older bars available"

            # Speichern mit merge=True (fügt zu bestehenden Daten hinzu)
            count = tracker.store_price_data(info.symbol, price_bars, merge=True)

            return True, count, f"added {count} historical bars"

        except Exception as e:
            self.logger.error(f"Error backfilling {info.symbol}: {e}")
            return False, 0, str(e)


class ProgressDisplay:
    """Zeigt Fortschritt an"""

    def __init__(self, total: int):
        self.total = total
        self.current = 0
        self.success = 0
        self.failed = 0
        self.bars_added = 0
        self.start_time = datetime.now()

    def update(self, symbol: str, success: bool, bars: int, message: str):
        self.current += 1
        if success:
            self.success += 1
            self.bars_added += bars
        else:
            self.failed += 1

        elapsed = (datetime.now() - self.start_time).total_seconds()
        rate = self.current / elapsed if elapsed > 0 else 0
        eta = (self.total - self.current) / rate if rate > 0 else 0

        pct = (self.current / self.total) * 100
        bar_width = 30
        filled = int(bar_width * self.current / self.total)
        bar = '█' * filled + '░' * (bar_width - filled)

        status_icon = '✓' if success else '✗'

        print(
            f"\r[{bar}] {pct:5.1f}% | "
            f"{symbol:6s} {status_icon} | "
            f"+{self.bars_added:,} bars | "
            f"ETA {int(eta//60)}:{int(eta%60):02d}",
            end='', flush=True
        )

    def finish(self):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        print()
        print()
        print("=" * 60)
        print(f"  Completed: {self.success}/{self.total} symbols")
        print(f"  Failed: {self.failed}")
        print(f"  Bars added: {self.bars_added:,}")
        print(f"  Duration: {int(elapsed//60)}:{int(elapsed%60):02d}")
        print("=" * 60)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
    )


def get_api_key() -> str:
    """API Key aus Environment laden"""
    api_key = os.environ.get('TRADIER_API_KEY')

    if not api_key:
        print("ERROR: No TRADIER_API_KEY found!")
        print("Please set it in .env file or as environment variable")
        sys.exit(1)

    return api_key


def print_status(results: List[BackfillInfo], summary: Dict):
    """Druckt Status-Übersicht"""
    print()
    print("=" * 70)
    print("  HISTORICAL DATA BACKFILL STATUS (Tradier)")
    print("=" * 70)
    print()
    print(f"  Target: {summary['target_years']} Jahre Historie (Start: {summary['target_start']})")
    print(f"  Threshold: Symbole mit < {summary['min_bars_threshold']} bars werden erweitert")
    print()
    print(f"  Total Symbole: {summary['total_symbols']}")
    print(f"  ┌─ Brauchen Backfill: {summary['needs_backfill']}")
    print(f"  └─ Bereits komplett: {summary['already_complete']}")
    print()

    # Symbole die Backfill brauchen
    needs_backfill = [r for r in results if r.needs_backfill]
    if needs_backfill:
        print("  SYMBOLE DIE BACKFILL BRAUCHEN:")
        for r in sorted(needs_backfill, key=lambda x: x.current_bars)[:30]:
            print(f"    {r.symbol:6s}: {r.current_start} ({r.current_bars:3d} bars) → {r.target_start}")
        if len(needs_backfill) > 30:
            print(f"    ... und {len(needs_backfill) - 30} weitere")
        print()

    print(f"  GESCHÄTZTE API CALLS: {summary['needs_backfill']}")
    print()


async def run_backfill(
    results: List[BackfillInfo],
    config: BackfillConfig,
    dryrun: bool = False
):
    """Führt das Backfill aus"""
    api_key = get_api_key()
    tracker = TradeTracker()
    collector = TradierBackfillCollector(api_key, config)

    to_process = [r for r in results if r.needs_backfill]

    if not to_process:
        print("\nAlle Symbole haben bereits ausreichend Historie!")
        return

    print(f"\nProcessing {len(to_process)} symbols for backfill via Tradier...")

    if dryrun:
        print("\nDRYRUN MODE - No data will be fetched")
        print("\nWould backfill:")
        for r in to_process[:20]:
            print(f"  {r.symbol:6s}: {r.target_start} → {r.current_start} ({r.days_to_backfill} days)")
        if len(to_process) > 20:
            print(f"  ... and {len(to_process) - 20} more")
        return

    try:
        await collector.connect()

        progress = ProgressDisplay(len(to_process))

        for info in to_process:
            success, bars, message = await collector.backfill_symbol(tracker, info)
            progress.update(info.symbol, success, bars, message)

            await asyncio.sleep(config.min_delay_seconds)

        progress.finish()

    finally:
        await collector.disconnect()


async def main():
    parser = argparse.ArgumentParser(
        description='Backfill historical data using Tradier API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('--status', action='store_true',
                        help='Show status only')
    parser.add_argument('--dryrun', action='store_true',
                        help='Show what would be fetched')
    parser.add_argument('--backfill', action='store_true',
                        help='Perform the backfill')
    parser.add_argument('--target-years', type=int, default=3,
                        help='Target years of history (default: 3)')
    parser.add_argument('--min-bars', type=int, default=500,
                        help='Min bars threshold (default: 500)')
    parser.add_argument('--delay', type=float, default=0.5,
                        help='Delay between requests (default: 0.5)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    setup_logging(args.verbose)

    config = BackfillConfig(
        target_years=args.target_years,
        min_delay_seconds=args.delay,
        min_bars_threshold=args.min_bars,
    )

    tracker = TradeTracker()
    loader = get_watchlist_loader()
    watchlist_symbols = set(loader.get_all_symbols())

    print("Analyzing database...")
    results, summary = analyze_backfill_needs(tracker, watchlist_symbols, config)

    print_status(results, summary)

    if args.status:
        return

    if args.dryrun:
        await run_backfill(results, config, dryrun=True)
        return

    if args.backfill:
        await run_backfill(results, config, dryrun=False)
        return

    print("Usage:")
    print("  --status      Show status only")
    print("  --dryrun      Show what would be fetched")
    print("  --backfill    Perform the backfill")
    print()


if __name__ == '__main__':
    asyncio.run(main())
