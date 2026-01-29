#!/usr/bin/env python3
"""
OptionPlay - Intelligent Historical Data Update Script
======================================================

Aktualisiert historische Daten intelligent:
- Analysiert bestehende Daten in der Datenbank
- Holt nur fehlende Tage für existierende Symbole
- Holt vollständige Historie für neue Symbole
- Optimiert API-Calls durch intelligentes Batching

Usage:
    # Status anzeigen (keine Daten abrufen)
    python scripts/update_historical_data.py --status

    # Dryrun - zeigt was abgerufen würde
    python scripts/update_historical_data.py --dryrun

    # Update ausführen
    python scripts/update_historical_data.py --update

    # Nur neue Symbole abrufen
    python scripts/update_historical_data.py --new-only

    # Nur Updates für existierende Symbole
    python scripts/update_historical_data.py --update-only
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting.trade_tracker import TradeTracker, PriceBar, VixDataPoint
from src.data_providers.marketdata import MarketDataProvider
from src.config.watchlist_loader import get_watchlist_loader


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class UpdateConfig:
    """Konfiguration für das Update"""
    requests_per_minute: int = 85  # Unter 100 für Sicherheit
    min_delay_seconds: float = 0.75
    max_history_days: int = 780  # ~3 Jahre für neue Symbole
    min_data_points: int = 60  # Minimum für sinnvolle Analyse
    stale_threshold_days: int = 3  # Daten älter als X Tage = veraltet


@dataclass
class SymbolUpdateInfo:
    """Info über benötigte Updates für ein Symbol"""
    symbol: str
    status: str  # 'new', 'update', 'current', 'delisted'
    db_start: Optional[date] = None
    db_end: Optional[date] = None
    db_bars: int = 0
    days_missing: int = 0
    fetch_from: Optional[date] = None
    fetch_to: Optional[date] = None


# =============================================================================
# Data Analysis
# =============================================================================

def analyze_database(
    tracker: TradeTracker,
    watchlist_symbols: Set[str],
    config: UpdateConfig
) -> Tuple[List[SymbolUpdateInfo], Dict]:
    """
    Analysiert die Datenbank und bestimmt benötigte Updates.

    Returns:
        Tuple von (Liste der SymbolUpdateInfo, Summary-Dict)
    """
    today = date.today()
    cutoff = today - timedelta(days=config.stale_threshold_days)

    # Daten aus DB laden
    db_symbols = tracker.list_symbols_with_price_data()
    db_symbol_map = {s['symbol']: s for s in db_symbols}
    db_symbol_set = set(db_symbol_map.keys())

    results = []

    # Kategorien
    new_symbols = watchlist_symbols - db_symbol_set
    existing_symbols = watchlist_symbols & db_symbol_set
    removed_symbols = db_symbol_set - watchlist_symbols

    # Neue Symbole - brauchen vollständige Historie
    for symbol in sorted(new_symbols):
        results.append(SymbolUpdateInfo(
            symbol=symbol,
            status='new',
            days_missing=config.max_history_days,
            fetch_from=today - timedelta(days=config.max_history_days),
            fetch_to=today
        ))

    # Existierende Symbole - prüfen ob Update nötig
    current_count = 0
    update_count = 0

    for symbol in sorted(existing_symbols):
        info = db_symbol_map[symbol]
        db_start = date.fromisoformat(info['start_date'])
        db_end = date.fromisoformat(info['end_date'])
        db_bars = info['bar_count']

        # Tage seit letztem Datenpunkt (nur Werktage zählen approximiert)
        calendar_days = (today - db_end).days

        if db_end >= cutoff:
            # Daten sind aktuell genug
            results.append(SymbolUpdateInfo(
                symbol=symbol,
                status='current',
                db_start=db_start,
                db_end=db_end,
                db_bars=db_bars,
                days_missing=0
            ))
            current_count += 1
        else:
            # Daten sind veraltet - Update nötig
            # Fetch ab dem Tag nach dem letzten vorhandenen
            fetch_from = db_end + timedelta(days=1)
            days_missing = (today - db_end).days

            results.append(SymbolUpdateInfo(
                symbol=symbol,
                status='update',
                db_start=db_start,
                db_end=db_end,
                db_bars=db_bars,
                days_missing=days_missing,
                fetch_from=fetch_from,
                fetch_to=today
            ))
            update_count += 1

    # Entfernte Symbole (in DB aber nicht mehr in Watchlist)
    for symbol in sorted(removed_symbols):
        info = db_symbol_map[symbol]
        results.append(SymbolUpdateInfo(
            symbol=symbol,
            status='delisted',
            db_start=date.fromisoformat(info['start_date']),
            db_end=date.fromisoformat(info['end_date']),
            db_bars=info['bar_count']
        ))

    summary = {
        'total_watchlist': len(watchlist_symbols),
        'total_in_db': len(db_symbol_set),
        'new_symbols': len(new_symbols),
        'update_needed': update_count,
        'current': current_count,
        'delisted': len(removed_symbols),
        'today': today.isoformat(),
        'cutoff': cutoff.isoformat(),
    }

    return results, summary


def analyze_vix(tracker: TradeTracker) -> Dict:
    """Analysiert VIX-Daten Status"""
    today = date.today()
    vix_range = tracker.get_vix_range()
    vix_count = tracker.count_vix_data()

    if vix_range:
        days_missing = (today - vix_range[1]).days
        needs_update = days_missing > 1
    else:
        days_missing = 0
        needs_update = True

    return {
        'has_data': vix_range is not None,
        'start': vix_range[0].isoformat() if vix_range else None,
        'end': vix_range[1].isoformat() if vix_range else None,
        'count': vix_count,
        'days_missing': days_missing,
        'needs_update': needs_update,
    }


# =============================================================================
# Data Collection
# =============================================================================

class IncrementalDataCollector:
    """Sammelt nur fehlende Daten"""

    def __init__(self, api_key: str, config: UpdateConfig):
        self.api_key = api_key
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._provider: Optional[MarketDataProvider] = None

    async def connect(self):
        self._provider = MarketDataProvider(self.api_key)
        connected = await self._provider.connect()
        if not connected:
            raise ConnectionError("Could not connect to Marketdata.app")
        self.logger.info("Connected to Marketdata.app")

    async def disconnect(self):
        if self._provider:
            await self._provider.disconnect()

    async def update_symbol(
        self,
        tracker: TradeTracker,
        info: SymbolUpdateInfo,
    ) -> Tuple[bool, int, str]:
        """
        Aktualisiert ein einzelnes Symbol.

        Returns:
            Tuple von (success, bars_added, message)
        """
        if info.status == 'current':
            return True, 0, "already current"

        if info.status == 'delisted':
            return True, 0, "skipped (delisted)"

        try:
            if info.status == 'new':
                # Neue Symbole: Volle Historie
                bars = await self._provider.get_historical(
                    info.symbol,
                    days=self.config.max_history_days
                )
            else:
                # Update: Nur fehlende Tage
                # Wir holen etwas mehr Tage als nötig für Überlappung
                days_to_fetch = info.days_missing + 5
                bars = await self._provider.get_historical(
                    info.symbol,
                    days=days_to_fetch
                )

            if not bars:
                return False, 0, "no data returned"

            # Konvertiere zu PriceBar
            price_bars = []
            for bar in bars:
                bar_date = bar.date if isinstance(bar.date, date) else date.fromisoformat(str(bar.date)[:10])

                # Bei Updates: Nur Bars nach dem letzten vorhandenen
                if info.status == 'update' and info.db_end:
                    if bar_date <= info.db_end:
                        continue

                price_bars.append(PriceBar(
                    date=bar_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                ))

            if not price_bars:
                return True, 0, "no new bars"

            # Speichern mit merge=True
            count = tracker.store_price_data(info.symbol, price_bars, merge=True)

            return True, count, f"added {count} bars"

        except Exception as e:
            self.logger.error(f"Error updating {info.symbol}: {e}")
            return False, 0, str(e)

    async def update_vix(self, tracker: TradeTracker, vix_info: Dict) -> Tuple[bool, int]:
        """Aktualisiert VIX-Daten"""
        try:
            if not vix_info['needs_update']:
                return True, 0

            # Hole VIX-Daten
            if vix_info['has_data']:
                # Nur fehlende Tage
                days = vix_info['days_missing'] + 5
            else:
                # Volle Historie
                days = self.config.max_history_days

            bars = await self._provider.get_index_candles("VIX", days=days)

            if not bars:
                return False, 0

            # Konvertiere zu VixDataPoint
            vix_points = []
            cutoff_date = date.fromisoformat(vix_info['end']) if vix_info['end'] else None

            for bar in bars:
                bar_date = bar.date if isinstance(bar.date, date) else date.fromisoformat(str(bar.date)[:10])

                # Bei Update: Nur neue Daten
                if cutoff_date and bar_date <= cutoff_date:
                    continue

                vix_points.append(VixDataPoint(date=bar_date, value=bar.close))

            if not vix_points:
                return True, 0

            count = tracker.store_vix_data(vix_points)
            return True, count

        except Exception as e:
            self.logger.error(f"Error updating VIX: {e}")
            return False, 0


# =============================================================================
# Progress Display
# =============================================================================

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


# =============================================================================
# CLI
# =============================================================================

def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
    )


def get_api_key() -> str:
    """API Key aus Environment oder Config laden"""
    api_key = os.environ.get('MARKETDATA_API_KEY')

    if not api_key:
        config_file = Path.home() / ".optionplay" / "config.json"
        if config_file.exists():
            with open(config_file) as f:
                config = json.load(f)
                api_key = config.get('marketdata_api_key')

    if not api_key:
        print("ERROR: No API key found!")
        print("Set MARKETDATA_API_KEY environment variable or add to ~/.optionplay/config.json")
        sys.exit(1)

    return api_key


def print_status(results: List[SymbolUpdateInfo], summary: Dict, vix_info: Dict):
    """Druckt Status-Übersicht"""
    print()
    print("=" * 70)
    print("  HISTORICAL DATA STATUS")
    print("=" * 70)
    print()
    print(f"  Today: {summary['today']}")
    print(f"  Stale cutoff: {summary['cutoff']}")
    print()
    print(f"  Watchlist symbols: {summary['total_watchlist']}")
    print(f"  In database: {summary['total_in_db']}")
    print()
    print(f"  ┌─ NEW (need full history): {summary['new_symbols']}")
    print(f"  ├─ UPDATE needed: {summary['update_needed']}")
    print(f"  ├─ CURRENT (up to date): {summary['current']}")
    print(f"  └─ DELISTED (in DB, not in watchlist): {summary['delisted']}")
    print()

    # VIX Status
    print("  VIX Data:")
    if vix_info['has_data']:
        print(f"    Range: {vix_info['start']} to {vix_info['end']}")
        print(f"    Points: {vix_info['count']}")
        print(f"    Days missing: {vix_info['days_missing']}")
        print(f"    Needs update: {'Yes' if vix_info['needs_update'] else 'No'}")
    else:
        print("    No VIX data in database")

    print()

    # Neue Symbole auflisten
    new_symbols = [r for r in results if r.status == 'new']
    if new_symbols:
        print("  NEW SYMBOLS (need full history):")
        for r in new_symbols[:20]:
            print(f"    {r.symbol}")
        if len(new_symbols) > 20:
            print(f"    ... and {len(new_symbols) - 20} more")
        print()

    # Symbole mit Updates auflisten
    update_symbols = [r for r in results if r.status == 'update']
    if update_symbols:
        print("  SYMBOLS NEEDING UPDATE:")
        for r in update_symbols[:10]:
            print(f"    {r.symbol:6s}: {r.db_end} → {r.fetch_to} ({r.days_missing} days)")
        if len(update_symbols) > 10:
            print(f"    ... and {len(update_symbols) - 10} more")
        print()

    # Geschätzte API Calls
    new_calls = len(new_symbols)
    update_calls = len(update_symbols)
    vix_calls = 1 if vix_info['needs_update'] else 0
    total_calls = new_calls + update_calls + vix_calls

    print(f"  ESTIMATED API CALLS:")
    print(f"    New symbols: {new_calls}")
    print(f"    Updates: {update_calls}")
    print(f"    VIX: {vix_calls}")
    print(f"    Total: {total_calls}")
    print()


async def run_update(
    results: List[SymbolUpdateInfo],
    vix_info: Dict,
    config: UpdateConfig,
    new_only: bool = False,
    update_only: bool = False,
    dryrun: bool = False
):
    """Führt das Update aus"""
    api_key = get_api_key()
    tracker = TradeTracker()
    collector = IncrementalDataCollector(api_key, config)

    # Filter basierend auf Modus
    to_process = []

    if new_only:
        to_process = [r for r in results if r.status == 'new']
        print(f"\nProcessing {len(to_process)} NEW symbols only...")
    elif update_only:
        to_process = [r for r in results if r.status == 'update']
        print(f"\nProcessing {len(to_process)} symbols needing UPDATE only...")
    else:
        to_process = [r for r in results if r.status in ('new', 'update')]
        print(f"\nProcessing {len(to_process)} symbols (new + update)...")

    if dryrun:
        print("\nDRYRUN MODE - No data will be fetched")
        print("\nWould process:")
        for r in to_process[:20]:
            if r.status == 'new':
                print(f"  {r.symbol:6s}: FETCH {config.max_history_days} days history")
            else:
                print(f"  {r.symbol:6s}: UPDATE {r.db_end} → {r.fetch_to} ({r.days_missing} days)")
        if len(to_process) > 20:
            print(f"  ... and {len(to_process) - 20} more")
        if vix_info['needs_update']:
            print(f"  VIX: UPDATE")
        return

    if not to_process and not vix_info['needs_update']:
        print("\nNothing to update - all data is current!")
        return

    try:
        await collector.connect()

        # VIX zuerst
        if vix_info['needs_update']:
            print("\nUpdating VIX data...")
            success, count = await collector.update_vix(tracker, vix_info)
            if success:
                print(f"  VIX: +{count} points")
            else:
                print("  VIX: FAILED")
            await asyncio.sleep(config.min_delay_seconds)

        if not to_process:
            print("\nNo symbol updates needed.")
            return

        # Symbole updaten
        print()
        progress = ProgressDisplay(len(to_process))

        for info in to_process:
            success, bars, message = await collector.update_symbol(tracker, info)
            progress.update(info.symbol, success, bars, message)

            # Rate limiting
            await asyncio.sleep(config.min_delay_seconds)

        progress.finish()

    finally:
        await collector.disconnect()


async def main():
    parser = argparse.ArgumentParser(
        description='Intelligent historical data updater for OptionPlay',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Modes
    parser.add_argument('--status', action='store_true',
                        help='Show status only (no data fetch)')
    parser.add_argument('--dryrun', action='store_true',
                        help='Show what would be fetched without actually fetching')
    parser.add_argument('--update', action='store_true',
                        help='Perform the update')
    parser.add_argument('--new-only', action='store_true',
                        help='Only fetch new symbols (full history)')
    parser.add_argument('--update-only', action='store_true',
                        help='Only update existing symbols (incremental)')

    # Options
    parser.add_argument('--delay', type=float, default=0.75,
                        help='Delay between requests in seconds (default: 0.75)')
    parser.add_argument('--max-days', type=int, default=780,
                        help='Max history days for new symbols (default: 780)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Config
    config = UpdateConfig(
        min_delay_seconds=args.delay,
        max_history_days=args.max_days,
    )

    # Daten analysieren
    tracker = TradeTracker()
    loader = get_watchlist_loader()
    watchlist_symbols = set(loader.get_all_symbols())

    print("Analyzing database...")
    results, summary = analyze_database(tracker, watchlist_symbols, config)
    vix_info = analyze_vix(tracker)

    # Status immer anzeigen
    print_status(results, summary, vix_info)

    # Je nach Modus handeln
    if args.status:
        return

    if args.dryrun:
        await run_update(results, vix_info, config,
                         new_only=args.new_only,
                         update_only=args.update_only,
                         dryrun=True)
        return

    if args.update or args.new_only or args.update_only:
        await run_update(results, vix_info, config,
                         new_only=args.new_only,
                         update_only=args.update_only,
                         dryrun=False)
        return

    # Wenn kein Modus angegeben, Hilfe zeigen
    print("\nUsage:")
    print("  --status      Show status only")
    print("  --dryrun      Show what would be fetched")
    print("  --update      Perform the full update")
    print("  --new-only    Only fetch new symbols")
    print("  --update-only Only update existing symbols")
    print()


if __name__ == '__main__':
    asyncio.run(main())
