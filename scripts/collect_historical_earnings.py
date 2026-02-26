#!/usr/bin/env python3
"""
Collect Historical Earnings Data
=================================
Sammelt historische Earnings-Daten für alle Watchlist-Symbole
und speichert sie in der SQLite-Datenbank.

Verwendet die Marketdata.app API (bereits integriert).

Usage:
    # Erste Ausführung
    python scripts/collect_historical_earnings.py

    # Resume nach Unterbrechung
    python scripts/collect_historical_earnings.py --resume

    # Nur bestimmte Symbole
    python scripts/collect_historical_earnings.py --symbols AAPL,MSFT,GOOGL

    # Dry-run (keine DB-Schreibung)
    python scripts/collect_historical_earnings.py --dry-run

    # Status anzeigen
    python scripts/collect_historical_earnings.py --status

    # Alle Daten löschen und neu sammeln
    python scripts/collect_historical_earnings.py --reset
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Optional, Set

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import WatchlistLoader
from src.cache.earnings_history import EarningsHistoryManager, get_earnings_history_manager
from src.data_providers.marketdata import MarketDataProvider

# =============================================================================
# CONFIGURATION
# =============================================================================

STATE_FILE = Path.home() / ".optionplay" / "earnings_collection_state.json"
DEFAULT_FROM_DATE = "2020-01-01"
DEFAULT_TO_DATE = None  # None = heute
REQUEST_DELAY = 0.7  # Sekunden zwischen Requests (100 req/min = 0.6s, mit Buffer)
BATCH_SIZE = 50  # Symbole pro Batch
BATCH_PAUSE = 5  # Sekunden Pause zwischen Batches

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(project_root / "logs" / "earnings_collection.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================================
# STATE MANAGEMENT
# =============================================================================


class CollectionState:
    """Verwaltet den Fortschritt der Sammlung"""

    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self.state: Dict = self._load()

    def _load(self) -> Dict:
        """Lädt State aus Datei"""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Konnte State nicht laden: {e}")

        return self._default_state()

    def _default_state(self) -> Dict:
        """Erstellt leeren State"""
        return {
            "started_at": None,
            "last_updated": None,
            "completed_symbols": [],
            "failed_symbols": {},
            "total_symbols": 0,
            "total_earnings_collected": 0,
            "requests_made": 0,
        }

    def save(self) -> None:
        """Speichert State in Datei"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state["last_updated"] = datetime.now().isoformat()

        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def reset(self) -> None:
        """Setzt State zurück"""
        self.state = self._default_state()
        if self.state_file.exists():
            self.state_file.unlink()
        logger.info("State zurückgesetzt")

    def mark_started(self, total_symbols: int) -> None:
        """Markiert Start der Collection"""
        if not self.state["started_at"]:
            self.state["started_at"] = datetime.now().isoformat()
        self.state["total_symbols"] = total_symbols
        self.save()

    def mark_completed(self, symbol: str, earnings_count: int) -> None:
        """Markiert Symbol als abgeschlossen"""
        if symbol not in self.state["completed_symbols"]:
            self.state["completed_symbols"].append(symbol)
        self.state["total_earnings_collected"] += earnings_count
        self.state["requests_made"] += 1
        self.save()

    def mark_failed(self, symbol: str, error: str) -> None:
        """Markiert Symbol als fehlgeschlagen"""
        self.state["failed_symbols"][symbol] = error
        self.state["requests_made"] += 1
        self.save()

    def get_remaining_symbols(self, all_symbols: List[str]) -> List[str]:
        """Gibt noch nicht verarbeitete Symbole zurück"""
        completed = set(self.state["completed_symbols"])
        failed = set(self.state["failed_symbols"].keys())
        processed = completed | failed
        return [s for s in all_symbols if s not in processed]

    def print_status(self) -> None:
        """Gibt Status auf Console aus"""
        print("\n" + "=" * 60)
        print("EARNINGS COLLECTION STATUS")
        print("=" * 60)
        print(f"Gestartet:            {self.state['started_at'] or 'Noch nicht'}")
        print(f"Letztes Update:       {self.state['last_updated'] or 'N/A'}")
        print(f"Symbole gesamt:       {self.state['total_symbols']}")
        print(f"Symbole abgeschlossen: {len(self.state['completed_symbols'])}")
        print(f"Symbole fehlgeschlagen: {len(self.state['failed_symbols'])}")
        print(f"Earnings gesammelt:   {self.state['total_earnings_collected']}")
        print(f"API Requests:         {self.state['requests_made']}")

        if self.state["failed_symbols"]:
            print(f"\nFehlgeschlagene Symbole:")
            for sym, err in list(self.state["failed_symbols"].items())[:10]:
                print(f"  - {sym}: {err}")
            if len(self.state["failed_symbols"]) > 10:
                print(f"  ... und {len(self.state['failed_symbols']) - 10} weitere")

        print("=" * 60 + "\n")


# =============================================================================
# COLLECTOR
# =============================================================================


class HistoricalEarningsCollector:
    """Sammelt historische Earnings für alle Symbole"""

    def __init__(
        self,
        api_key: str,
        from_date: str = DEFAULT_FROM_DATE,
        to_date: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.api_key = api_key
        self.from_date = from_date
        self.to_date = to_date or date.today().isoformat()
        self.dry_run = dry_run

        self.provider: Optional[MarketDataProvider] = None
        self.manager: Optional[EarningsHistoryManager] = None
        self.state = CollectionState()

    async def connect(self) -> bool:
        """Stellt Verbindungen her"""
        self.provider = MarketDataProvider(self.api_key)
        connected = await self.provider.connect()

        if not connected:
            logger.error("Konnte nicht mit Marketdata.app verbinden")
            return False

        if not self.dry_run:
            self.manager = get_earnings_history_manager()

        logger.info(f"Verbunden. Sammle Earnings von {self.from_date} bis {self.to_date}")
        return True

    async def disconnect(self) -> None:
        """Trennt Verbindungen"""
        if self.provider:
            await self.provider.disconnect()

    async def collect_symbol(self, symbol: str) -> int:
        """
        Sammelt Earnings für ein Symbol.

        Returns:
            Anzahl der gesammelten Earnings
        """
        try:
            earnings = await self.provider.get_historical_earnings(
                symbol, from_date=self.from_date, to_date=self.to_date
            )

            if not earnings:
                logger.debug(f"{symbol}: Keine Earnings gefunden")
                self.state.mark_completed(symbol, 0)
                return 0

            if not self.dry_run and self.manager:
                count = self.manager.save_earnings(symbol, earnings)
                logger.info(f"{symbol}: {count} Earnings gespeichert")
            else:
                count = len(earnings)
                logger.info(f"{symbol}: {count} Earnings gefunden (dry-run)")

            self.state.mark_completed(symbol, count)
            return count

        except Exception as e:
            logger.warning(f"{symbol}: Fehler - {e}")
            self.state.mark_failed(symbol, str(e))
            return 0

    async def collect_all(self, symbols: List[str], resume: bool = False) -> Dict[str, int]:
        """
        Sammelt Earnings für alle Symbole.

        Args:
            symbols: Liste der Symbole
            resume: True um bei letztem Symbol fortzufahren

        Returns:
            Dict mit Symbol -> Anzahl Earnings
        """
        # State initialisieren
        self.state.mark_started(len(symbols))

        # Bestimme zu verarbeitende Symbole
        if resume:
            remaining = self.state.get_remaining_symbols(symbols)
            logger.info(f"Resume: {len(remaining)} von {len(symbols)} Symbolen verbleiben")
            symbols = remaining
        else:
            logger.info(f"Starte neue Collection für {len(symbols)} Symbole")

        if not symbols:
            logger.info("Keine Symbole zu verarbeiten")
            return {}

        results = {}
        total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_idx in range(total_batches):
            start = batch_idx * BATCH_SIZE
            end = min(start + BATCH_SIZE, len(symbols))
            batch = symbols[start:end]

            logger.info(
                f"\nBatch {batch_idx + 1}/{total_batches} "
                f"({len(batch)} Symbole: {batch[0]}...{batch[-1]})"
            )

            for i, symbol in enumerate(batch):
                count = await self.collect_symbol(symbol)
                results[symbol] = count

                # Rate limiting
                if i < len(batch) - 1:
                    await asyncio.sleep(REQUEST_DELAY)

                # Progress
                total_done = len(self.state.state["completed_symbols"])
                total_all = self.state.state["total_symbols"]
                pct = (total_done / total_all) * 100 if total_all > 0 else 0
                print(f"\rProgress: {total_done}/{total_all} ({pct:.1f}%)", end="", flush=True)

            # Pause zwischen Batches
            if batch_idx < total_batches - 1:
                logger.info(f"\nPause {BATCH_PAUSE}s vor nächstem Batch...")
                await asyncio.sleep(BATCH_PAUSE)

        print()  # Newline nach Progress
        return results


# =============================================================================
# MAIN
# =============================================================================


async def main():
    parser = argparse.ArgumentParser(description="Sammelt historische Earnings-Daten")
    parser.add_argument("--resume", "-r", action="store_true", help="Setzt bei letztem Symbol fort")
    parser.add_argument(
        "--symbols",
        "-s",
        type=str,
        help="Komma-separierte Liste von Symbolen (z.B. AAPL,MSFT,GOOGL)",
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Keine DB-Schreibung, nur Test"
    )
    parser.add_argument("--status", action="store_true", help="Zeigt aktuellen Status")
    parser.add_argument("--reset", action="store_true", help="Löscht alle Daten und startet neu")
    parser.add_argument(
        "--from-date",
        type=str,
        default=DEFAULT_FROM_DATE,
        help=f"Start-Datum (default: {DEFAULT_FROM_DATE})",
    )
    parser.add_argument("--to-date", type=str, default=None, help="End-Datum (default: heute)")
    parser.add_argument(
        "--watchlist",
        type=str,
        default=None,
        help="Watchlist Name (z.B. default_275, sp500_complete)",
    )

    args = parser.parse_args()

    # Status anzeigen
    if args.status:
        state = CollectionState()
        state.print_status()

        # Auch DB-Stats anzeigen
        manager = get_earnings_history_manager()
        stats = manager.get_statistics()
        print("DATENBANK STATUS:")
        print(f"  Symbole mit Daten:  {stats['total_symbols']}")
        print(f"  Earnings gesamt:    {stats['total_earnings']}")
        print(
            f"  Datumsbereich:      {stats['date_range']['from']} bis {stats['date_range']['to']}"
        )
        return

    # Reset
    if args.reset:
        confirm = input("Alle Earnings-History-Daten löschen? (ja/nein): ")
        if confirm.lower() == "ja":
            state = CollectionState()
            state.reset()
            manager = get_earnings_history_manager()
            deleted = manager.clear_all()
            print(f"{deleted} Einträge gelöscht")
        else:
            print("Abgebrochen")
        return

    # API Key prüfen
    api_key = os.environ.get("MARKETDATA_API_KEY")
    if not api_key:
        logger.error("MARKETDATA_API_KEY nicht gesetzt!")
        logger.error("Setze: export MARKETDATA_API_KEY=your_key")
        sys.exit(1)

    # Symbole laden
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        logger.info(f"Verwende {len(symbols)} angegebene Symbole")
    else:
        loader = WatchlistLoader(default_list=args.watchlist)
        symbols = loader.get_all_symbols()
        logger.info(f"Watchlist geladen: {len(symbols)} Symbole")

    if not symbols:
        logger.error("Keine Symbole gefunden!")
        sys.exit(1)

    # Logs-Verzeichnis erstellen
    (project_root / "logs").mkdir(exist_ok=True)

    # Collector starten
    collector = HistoricalEarningsCollector(
        api_key=api_key, from_date=args.from_date, to_date=args.to_date, dry_run=args.dry_run
    )

    try:
        if not await collector.connect():
            sys.exit(1)

        start_time = datetime.now()
        results = await collector.collect_all(symbols, resume=args.resume)
        duration = datetime.now() - start_time

        # Zusammenfassung
        print("\n" + "=" * 60)
        print("SAMMLUNG ABGESCHLOSSEN")
        print("=" * 60)
        print(f"Dauer:            {duration}")
        print(f"Symbole:          {len(results)}")
        print(f"Earnings gesamt:  {sum(results.values())}")

        if args.dry_run:
            print("\n(Dry-Run: Keine Daten wurden gespeichert)")

        collector.state.print_status()

    finally:
        await collector.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
