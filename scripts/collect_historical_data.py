#!/usr/bin/env python3
"""
OptionPlay - Historical Data Collection Script
==============================================

Sammelt historische Daten für Training und Validierung mit
kontrolliertem Rate-Limiting und Quota-Management.

Usage:
    # Kleiner Test (10 Symbole)
    python scripts/collect_historical_data.py --test

    # Einzelner Sektor
    python scripts/collect_historical_data.py --sector tech

    # Alle Sektoren, aber in Batches
    python scripts/collect_historical_data.py --batch-size 50 --delay 1.0

    # Status prüfen
    python scripts/collect_historical_data.py --status

    # Resume nach Unterbrechung
    python scripts/collect_historical_data.py --resume

    # Spezifische Symbole
    python scripts/collect_historical_data.py --symbols AAPL,MSFT,GOOGL

API Limits (Marketdata.app):
    - Starter: 100 req/min
    - Trader: 10,000 req/day, 100 req/min
    - Professional: Higher limits
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field, asdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting import (
    DataCollector,
    CollectionConfig,
    CollectionResult,
    format_collection_status,
    TradeTracker,
)
from src.data_providers.marketdata import MarketDataProvider
from src.config.watchlist_loader import WatchlistLoader, get_watchlist_loader

# =============================================================================
# Configuration
# =============================================================================

@dataclass
class QuotaConfig:
    """API Quota Konfiguration"""
    requests_per_minute: int = 90  # Unter 100 bleiben für Sicherheit
    requests_per_day: int = 9000   # Unter 10000 bleiben für Sicherheit
    min_delay_seconds: float = 0.7  # ~85 req/min
    max_delay_seconds: float = 2.0
    pause_on_rate_limit_seconds: float = 60.0

    # Adaptive Rate Limiting
    increase_delay_on_error: float = 0.5
    decrease_delay_on_success: float = 0.05
    min_consecutive_success: int = 10


@dataclass
class SessionState:
    """Zustand einer Sammlungssession für Resume"""
    session_id: str
    started_at: str
    last_updated: str
    symbols_requested: List[str] = field(default_factory=list)
    symbols_completed: Set[str] = field(default_factory=set)
    symbols_failed: Set[str] = field(default_factory=set)
    total_requests: int = 0
    total_bars: int = 0
    vix_collected: bool = False
    current_delay: float = 0.7

    def to_dict(self) -> Dict:
        return {
            'session_id': self.session_id,
            'started_at': self.started_at,
            'last_updated': self.last_updated,
            'symbols_requested': self.symbols_requested,
            'symbols_completed': list(self.symbols_completed),
            'symbols_failed': list(self.symbols_failed),
            'total_requests': self.total_requests,
            'total_bars': self.total_bars,
            'vix_collected': self.vix_collected,
            'current_delay': self.current_delay,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'SessionState':
        return cls(
            session_id=data['session_id'],
            started_at=data['started_at'],
            last_updated=data['last_updated'],
            symbols_requested=data['symbols_requested'],
            symbols_completed=set(data['symbols_completed']),
            symbols_failed=set(data['symbols_failed']),
            total_requests=data['total_requests'],
            total_bars=data['total_bars'],
            vix_collected=data.get('vix_collected', False),
            current_delay=data.get('current_delay', 0.7),
        )

    @property
    def remaining_symbols(self) -> List[str]:
        completed = self.symbols_completed | self.symbols_failed
        return [s for s in self.symbols_requested if s not in completed]

    @property
    def progress_percent(self) -> float:
        if not self.symbols_requested:
            return 0.0
        completed = len(self.symbols_completed) + len(self.symbols_failed)
        return (completed / len(self.symbols_requested)) * 100


# =============================================================================
# Adaptive Rate Limiter
# =============================================================================

class AdaptiveRateLimiter:
    """
    Adaptiver Rate Limiter der sich an API-Antworten anpasst.

    - Erhöht Delay bei Fehlern
    - Verringert Delay bei Erfolg
    - Pausiert bei Rate-Limit-Fehlern
    """

    def __init__(self, config: QuotaConfig):
        self.config = config
        self.current_delay = config.min_delay_seconds
        self.consecutive_success = 0
        self.requests_this_minute = 0
        self.requests_today = 0
        self.minute_start = datetime.now()
        self.day_start = date.today()
        self.logger = logging.getLogger(__name__)

    async def wait(self):
        """Wartet gemäß aktuellem Rate-Limit"""
        now = datetime.now()

        # Reset Minute Counter
        if (now - self.minute_start).seconds >= 60:
            self.minute_start = now
            self.requests_this_minute = 0

        # Reset Day Counter
        if date.today() > self.day_start:
            self.day_start = date.today()
            self.requests_today = 0

        # Check Minute Limit
        if self.requests_this_minute >= self.config.requests_per_minute:
            wait_time = 60 - (now - self.minute_start).seconds
            self.logger.warning(f"Minute limit reached, waiting {wait_time}s...")
            await asyncio.sleep(wait_time + 1)
            self.minute_start = datetime.now()
            self.requests_this_minute = 0

        # Check Day Limit
        if self.requests_today >= self.config.requests_per_day:
            self.logger.error("Daily limit reached! Resume tomorrow.")
            raise QuotaExhaustedError("Daily API quota exhausted")

        # Normal Delay
        await asyncio.sleep(self.current_delay)

    def record_success(self):
        """Aufzeichnen eines erfolgreichen Requests"""
        self.requests_this_minute += 1
        self.requests_today += 1
        self.consecutive_success += 1

        # Delay verringern nach mehreren Erfolgen
        if self.consecutive_success >= self.config.min_consecutive_success:
            self.current_delay = max(
                self.config.min_delay_seconds,
                self.current_delay - self.config.decrease_delay_on_success
            )

    def record_error(self, is_rate_limit: bool = False):
        """Aufzeichnen eines fehlerhaften Requests"""
        self.consecutive_success = 0

        if is_rate_limit:
            self.current_delay = self.config.pause_on_rate_limit_seconds
        else:
            self.current_delay = min(
                self.config.max_delay_seconds,
                self.current_delay + self.config.increase_delay_on_error
            )

    def get_status(self) -> Dict:
        return {
            'current_delay': round(self.current_delay, 2),
            'requests_this_minute': self.requests_this_minute,
            'requests_today': self.requests_today,
            'consecutive_success': self.consecutive_success,
        }


class QuotaExhaustedError(Exception):
    """Quota erschöpft"""
    pass


# =============================================================================
# Historical Data Collector
# =============================================================================

class HistoricalDataCollector:
    """
    Erweiterter Data Collector mit:
    - Adaptivem Rate Limiting
    - Session Resume
    - Progress Tracking
    - Quota Management
    """

    STATE_FILE = Path.home() / ".optionplay" / "collection_state.json"

    def __init__(
        self,
        api_key: str,
        quota_config: Optional[QuotaConfig] = None,
        db_path: Optional[str] = None,
    ):
        self.api_key = api_key
        self.quota_config = quota_config or QuotaConfig()
        self.db_path = db_path
        self.rate_limiter = AdaptiveRateLimiter(self.quota_config)
        self.logger = logging.getLogger(__name__)
        self.state: Optional[SessionState] = None
        self._provider: Optional[MarketDataProvider] = None

    async def connect(self):
        """Verbindung zum Provider herstellen"""
        self._provider = MarketDataProvider(self.api_key)
        connected = await self._provider.connect()
        if not connected:
            raise ConnectionError("Could not connect to Marketdata.app")
        self.logger.info("Connected to Marketdata.app")

    async def disconnect(self):
        """Verbindung trennen"""
        if self._provider:
            await self._provider.disconnect()

    def _load_state(self) -> Optional[SessionState]:
        """Lädt gespeicherten Session-State"""
        if self.STATE_FILE.exists():
            try:
                with open(self.STATE_FILE, 'r') as f:
                    data = json.load(f)
                return SessionState.from_dict(data)
            except Exception as e:
                self.logger.warning(f"Could not load state: {e}")
        return None

    def _save_state(self):
        """Speichert aktuellen Session-State"""
        if self.state:
            self.state.last_updated = datetime.now().isoformat()
            self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.STATE_FILE, 'w') as f:
                json.dump(self.state.to_dict(), f, indent=2)

    def _clear_state(self):
        """Löscht gespeicherten State"""
        if self.STATE_FILE.exists():
            self.STATE_FILE.unlink()
        self.state = None

    async def collect(
        self,
        symbols: List[str],
        lookback_days: int = 260,
        resume: bool = False,
        progress_callback=None,
    ) -> CollectionResult:
        """
        Sammelt historische Daten für alle Symbole.

        Args:
            symbols: Liste der Symbole
            lookback_days: Tage Lookback
            resume: True = vorherige Session fortsetzen
            progress_callback: Optional (symbol, current, total, status)

        Returns:
            CollectionResult
        """
        start_time = datetime.now()

        # Resume oder neue Session
        if resume:
            self.state = self._load_state()
            if self.state:
                self.logger.info(
                    f"Resuming session from {self.state.started_at}, "
                    f"{self.state.progress_percent:.1f}% complete"
                )
                symbols = self.state.remaining_symbols
                self.rate_limiter.current_delay = self.state.current_delay
            else:
                self.logger.warning("No previous session found, starting fresh")
                resume = False

        if not resume:
            self.state = SessionState(
                session_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
                started_at=datetime.now().isoformat(),
                last_updated=datetime.now().isoformat(),
                symbols_requested=list(symbols),
            )

        # Tracker für Persistenz
        tracker = TradeTracker(db_path=self.db_path)

        total = len(symbols)
        self.logger.info(f"Collecting data for {total} symbols...")

        try:
            # VIX zuerst (wenn noch nicht)
            if not self.state.vix_collected:
                await self._collect_vix(tracker, lookback_days)
                self.state.vix_collected = True
                self._save_state()

            # Symbole einzeln
            for i, symbol in enumerate(symbols, 1):
                if symbol in self.state.symbols_completed:
                    continue

                try:
                    await self.rate_limiter.wait()

                    if progress_callback:
                        progress_callback(symbol, i, total, "collecting")

                    bars_count = await self._collect_symbol(
                        tracker, symbol, lookback_days
                    )

                    self.rate_limiter.record_success()
                    self.state.symbols_completed.add(symbol)
                    self.state.total_bars += bars_count
                    self.state.total_requests += 1

                    if progress_callback:
                        progress_callback(symbol, i, total, f"done ({bars_count} bars)")

                except QuotaExhaustedError:
                    self._save_state()
                    raise

                except Exception as e:
                    is_rate_limit = "429" in str(e) or "rate" in str(e).lower()
                    self.rate_limiter.record_error(is_rate_limit)
                    self.state.symbols_failed.add(symbol)
                    self.state.total_requests += 1

                    if progress_callback:
                        progress_callback(symbol, i, total, f"FAILED: {e}")

                    self.logger.warning(f"Failed to collect {symbol}: {e}")

                # Regelmäßig speichern
                if i % 10 == 0:
                    self.state.current_delay = self.rate_limiter.current_delay
                    self._save_state()

        except KeyboardInterrupt:
            self.logger.info("Interrupted! Saving state for resume...")
            self._save_state()
            raise

        except QuotaExhaustedError:
            self.logger.error("Quota exhausted! Use --resume to continue later.")
            raise

        duration = (datetime.now() - start_time).total_seconds()

        # Ergebnis erstellen bevor State gelöscht wird
        result = CollectionResult(
            timestamp=start_time,
            symbols_requested=len(self.state.symbols_requested),
            symbols_collected=len(self.state.symbols_completed),
            symbols_failed=list(self.state.symbols_failed),
            total_bars_collected=self.state.total_bars,
            vix_points_collected=lookback_days if self.state.vix_collected else 0,
            duration_seconds=duration,
            errors=[f"{s}: failed" for s in self.state.symbols_failed][:20],
        )

        # Erfolgreiche Session - State löschen
        self._clear_state()

        return result

    async def _collect_symbol(
        self,
        tracker: TradeTracker,
        symbol: str,
        days: int,
    ) -> int:
        """Sammelt Daten für ein einzelnes Symbol"""
        from src.backtesting.trade_tracker import PriceBar

        bars = await self._provider.get_historical(symbol, days=days)

        if not bars:
            return 0

        price_bars = []
        for bar in bars:
            bar_date = bar.date if isinstance(bar.date, date) else date.fromisoformat(str(bar.date)[:10])
            price_bars.append(PriceBar(
                date=bar_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            ))

        count = tracker.store_price_data(symbol, price_bars, merge=True)
        return count

    async def _collect_vix(
        self,
        tracker: TradeTracker,
        days: int,
    ) -> int:
        """Sammelt VIX-Daten"""
        from src.backtesting.trade_tracker import VixDataPoint

        self.logger.info("Collecting VIX data...")

        await self.rate_limiter.wait()
        bars = await self._provider.get_index_candles("VIX", days=days)

        if not bars:
            self.logger.warning("Could not fetch VIX data")
            return 0

        vix_points = []
        for bar in bars:
            bar_date = bar.date if isinstance(bar.date, date) else date.fromisoformat(str(bar.date)[:10])
            vix_points.append(VixDataPoint(date=bar_date, value=bar.close))

        count = tracker.store_vix_data(vix_points)
        self.rate_limiter.record_success()
        self.logger.info(f"Collected {count} VIX data points")
        return count


# =============================================================================
# CLI
# =============================================================================

def setup_logging(verbose: bool = False):
    """Logging konfigurieren"""
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


def get_symbols_by_sector(sector: str) -> List[str]:
    """Lädt Symbole für einen Sektor"""
    sector_map = {
        'tech': 'information_technology',
        'health': 'health_care',
        'finance': 'financials',
        'consumer': 'consumer_discretionary',
        'communication': 'communication_services',
        'industrial': 'industrials',
        'staples': 'consumer_staples',
        'energy': 'energy',
        'utilities': 'utilities',
        'materials': 'materials',
        'realestate': 'real_estate',
    }

    full_sector = sector_map.get(sector.lower(), sector)

    try:
        loader = get_watchlist_loader()
        symbols = loader.get_sector(full_sector)

        if symbols:
            return symbols

        print(f"Unknown sector: {sector}")
        print(f"Available: {', '.join(sector_map.keys())}")
        sys.exit(1)

    except Exception as e:
        print(f"Error loading watchlist: {e}")
        sys.exit(1)


def get_all_symbols() -> List[str]:
    """Lädt alle Symbole aus der Watchlist"""
    loader = get_watchlist_loader()
    return sorted(set(loader.get_all_symbols()))


class ProgressTracker:
    """Verfolgt und zeigt Fortschritt mit Metriken"""

    def __init__(self):
        self.start_time = datetime.now()
        self.total_bars = 0
        self.successful = 0
        self.failed = 0
        self.last_print_time = datetime.now()

    def update(self, symbol: str, current: int, total: int, status: str):
        """Update und Anzeige des Fortschritts"""
        now = datetime.now()
        elapsed = (now - self.start_time).total_seconds()

        # Bars aus Status extrahieren
        if "bars" in status and "done" in status:
            try:
                bars = int(status.split("(")[1].split(" ")[0])
                self.total_bars += bars
                self.successful += 1
            except (IndexError, ValueError):
                pass
        elif "FAILED" in status:
            self.failed += 1

        # Fortschrittsberechnung
        pct = (current / total) * 100
        bar_width = 25
        filled = int(bar_width * current / total)
        bar = '█' * filled + '░' * (bar_width - filled)

        # ETA berechnen
        if current > 0 and elapsed > 0:
            rate = current / elapsed  # Symbole pro Sekunde
            remaining = total - current
            eta_seconds = remaining / rate if rate > 0 else 0
            eta_str = self._format_time(eta_seconds)
        else:
            eta_str = "--:--"

        # Elapsed time
        elapsed_str = self._format_time(elapsed)

        # Success rate
        completed = self.successful + self.failed
        success_rate = (self.successful / completed * 100) if completed > 0 else 100

        # Metriken-Zeile
        metrics = f"✓{self.successful} ✗{self.failed} | {self.total_bars:,} bars | {elapsed_str} / ETA {eta_str}"

        # Status kürzen wenn zu lang
        status_short = status[:20] if len(status) > 20 else status

        # Ausgabe
        print(f"\r[{bar}] {pct:5.1f}% | {symbol:6s} | {status_short:20s} | {metrics}", end='', flush=True)

        # Summary nur am Ende und nur bei "done" Status (nicht bei "collecting")
        if current == total and "done" in status:
            print()  # Neue Zeile am Ende
            self._print_summary(total, elapsed)

    def _format_time(self, seconds: float) -> str:
        """Formatiert Sekunden als MM:SS oder HH:MM:SS"""
        if seconds < 0:
            return "--:--"
        if seconds < 3600:
            return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}:{minutes:02d}:{int(seconds % 60):02d}"

    def _print_summary(self, total: int, elapsed: float):
        """Druckt Zusammenfassung am Ende"""
        print()
        print("─" * 70)
        print(f"  Completed: {self.successful}/{total} symbols ({self.successful/total*100:.1f}%)")
        print(f"  Failed:    {self.failed} symbols")
        print(f"  Total:     {self.total_bars:,} price bars collected")
        print(f"  Duration:  {self._format_time(elapsed)}")
        if elapsed > 0:
            print(f"  Rate:      {self.successful / elapsed * 60:.1f} symbols/min")
        print("─" * 70)


# Global progress tracker für Callback
_progress_tracker: Optional[ProgressTracker] = None


def print_progress(symbol: str, current: int, total: int, status: str):
    """Progress-Callback für den Collector"""
    global _progress_tracker
    if _progress_tracker is None:
        _progress_tracker = ProgressTracker()
    _progress_tracker.update(symbol, current, total, status)


def reset_progress_tracker():
    """Setzt den Progress-Tracker zurück"""
    global _progress_tracker
    _progress_tracker = ProgressTracker()


def show_status():
    """Zeigt Status der gesammelten Daten"""
    tracker = TradeTracker()

    # Storage Stats
    stats = tracker.get_storage_stats()
    symbols = tracker.list_symbols_with_price_data()
    vix_range = tracker.get_vix_range()

    print("\n" + "=" * 60)
    print("HISTORICAL DATA COLLECTION STATUS")
    print("=" * 60)

    print(f"\nDatabase: ~/.optionplay/trades.db")
    print(f"Size: {stats['database_size_mb']:.2f} MB")

    print(f"\nSymbols with Price Data: {stats['symbols_with_price_data']}")
    print(f"Total Price Bars: {stats['total_price_bars']:,}")
    print(f"Compressed Size: {stats['price_data_compressed_kb']:.1f} KB")

    if vix_range:
        print(f"\nVIX Data: {vix_range[0]} to {vix_range[1]}")
        print(f"VIX Points: {stats['vix_data_points']}")
    else:
        print(f"\nVIX Data: None")

    # Resume State
    state_file = Path.home() / ".optionplay" / "collection_state.json"
    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
        print(f"\nPending Session:")
        print(f"  Started: {state['started_at']}")
        print(f"  Progress: {len(state['symbols_completed'])}/{len(state['symbols_requested'])}")
        print(f"  Remaining: {len(state['symbols_requested']) - len(state['symbols_completed']) - len(state['symbols_failed'])}")
        print(f"\n  Use --resume to continue")

    # Sample von Symbolen
    if symbols:
        print(f"\nSample Symbols:")
        for s in symbols[:10]:
            print(f"  {s['symbol']:6s}: {s['start_date']} to {s['end_date']} ({s['bar_count']} bars)")
        if len(symbols) > 10:
            print(f"  ... and {len(symbols) - 10} more")

    print()


async def main():
    parser = argparse.ArgumentParser(
        description='Collect historical market data for OptionPlay training',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Modes
    parser.add_argument('--status', action='store_true',
                        help='Show collection status')
    parser.add_argument('--resume', action='store_true',
                        help='Resume previous collection session')
    parser.add_argument('--test', action='store_true',
                        help='Test mode with 10 symbols')

    # Symbol Selection
    parser.add_argument('--symbols', type=str,
                        help='Comma-separated list of symbols')
    parser.add_argument('--sector', type=str,
                        help='Collect single sector (tech, health, finance, etc.)')
    parser.add_argument('--all', action='store_true',
                        help='Collect all 275 symbols')

    # Rate Limiting
    parser.add_argument('--delay', type=float, default=0.7,
                        help='Delay between requests (default: 0.7s)')
    parser.add_argument('--rpm', type=int, default=90,
                        help='Requests per minute limit (default: 90)')

    # Data Options
    parser.add_argument('--days', type=int, default=260,
                        help='Days of history to collect (default: 260)')

    # Output
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Status anzeigen
    if args.status:
        show_status()
        return

    # Symbole bestimmen
    if args.test:
        symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA',
                   'META', 'TSLA', 'JPM', 'V', 'JNJ']
        logger.info("Test mode: 10 symbols")
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
        logger.info(f"Custom symbols: {len(symbols)}")
    elif args.sector:
        symbols = get_symbols_by_sector(args.sector)
        logger.info(f"Sector {args.sector}: {len(symbols)} symbols")
    elif args.all:
        symbols = get_all_symbols()
        logger.info(f"All symbols: {len(symbols)}")
    elif args.resume:
        symbols = []  # Wird aus State geladen
    else:
        parser.print_help()
        print("\n\nExamples:")
        print("  python scripts/collect_historical_data.py --test")
        print("  python scripts/collect_historical_data.py --sector tech")
        print("  python scripts/collect_historical_data.py --all --delay 1.0")
        print("  python scripts/collect_historical_data.py --status")
        return

    # API Key
    api_key = get_api_key()

    # Quota Config
    quota_config = QuotaConfig(
        requests_per_minute=args.rpm,
        min_delay_seconds=args.delay,
    )

    # Collector
    collector = HistoricalDataCollector(
        api_key=api_key,
        quota_config=quota_config,
    )

    try:
        await collector.connect()

        print(f"\n{'═'*70}")
        print(f"  HISTORICAL DATA COLLECTION")
        print(f"{'═'*70}")
        print(f"  Symbols:  {len(symbols) if symbols else 'from resume'}")
        print(f"  Lookback: {args.days} days (~1 year)")
        print(f"  Rate:     ~{int(60/args.delay)} req/min (delay: {args.delay}s)")
        print(f"{'═'*70}\n")

        # Progress Tracker zurücksetzen
        reset_progress_tracker()

        result = await collector.collect(
            symbols=symbols,
            lookback_days=args.days,
            resume=args.resume,
            progress_callback=print_progress,
        )

        print(f"\n{result}")

        if result.symbols_failed:
            print(f"\nFailed symbols: {', '.join(result.symbols_failed[:20])}")
            if len(result.symbols_failed) > 20:
                print(f"  ... and {len(result.symbols_failed) - 20} more")

        # Rate Limiter Status
        limiter_status = collector.rate_limiter.get_status()
        print(f"\nRate Limiter: {limiter_status['requests_today']} requests today")

    except KeyboardInterrupt:
        print("\n\nInterrupted! Progress saved. Use --resume to continue.")

    except QuotaExhaustedError:
        print("\n\nQuota exhausted! Use --resume to continue tomorrow.")

    finally:
        await collector.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
