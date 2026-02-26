#!/usr/bin/env python3
"""
OptionPlay - Scheduled Data Collection
======================================

Plant und führt die Datensammlung in Batches aus,
um API-Kontingente optimal zu nutzen.

Features:
- Intelligente Batch-Aufteilung
- Automatisches Resume bei Unterbrechung
- Quota-Schätzung vor Start
- Detaillierte Fortschrittsberichte

Usage:
    # Zeige geplante Batches
    python scripts/scheduled_collection.py --plan

    # Starte Batch 1
    python scripts/scheduled_collection.py --batch 1

    # Alle Batches nacheinander (mit Pausen)
    python scripts/scheduled_collection.py --run-all

    # Nächsten unvollständigen Batch ausführen
    python scripts/scheduled_collection.py --next
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.collect_historical_data import (
    HistoricalDataCollector,
    QuotaConfig,
    get_api_key,
    get_all_symbols,
    print_progress,
    setup_logging,
)
from src.backtesting import TradeTracker

# =============================================================================
# Batch Planning
# =============================================================================


@dataclass
class BatchPlan:
    """Plan für Batch-Sammlung"""

    batch_id: int
    symbols: List[str]
    estimated_requests: int
    estimated_minutes: float
    status: str = "pending"  # pending, in_progress, completed, partial

    def to_dict(self) -> Dict:
        return {
            "batch_id": self.batch_id,
            "symbols": self.symbols,
            "estimated_requests": self.estimated_requests,
            "estimated_minutes": self.estimated_minutes,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "BatchPlan":
        return cls(**data)


@dataclass
class CollectionSchedule:
    """Gesamtplan für die Datensammlung"""

    created_at: str
    total_symbols: int
    batches: List[BatchPlan]
    lookback_days: int = 260
    requests_per_symbol: int = 2  # historical + potential retry
    requests_per_minute: int = 80

    SCHEDULE_FILE = Path.home() / ".optionplay" / "collection_schedule.json"

    def to_dict(self) -> Dict:
        return {
            "created_at": self.created_at,
            "total_symbols": self.total_symbols,
            "batches": [b.to_dict() for b in self.batches],
            "lookback_days": self.lookback_days,
            "requests_per_symbol": self.requests_per_symbol,
            "requests_per_minute": self.requests_per_minute,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CollectionSchedule":
        batches = [BatchPlan.from_dict(b) for b in data["batches"]]
        return cls(
            created_at=data["created_at"],
            total_symbols=data["total_symbols"],
            batches=batches,
            lookback_days=data.get("lookback_days", 260),
            requests_per_symbol=data.get("requests_per_symbol", 2),
            requests_per_minute=data.get("requests_per_minute", 80),
        )

    def save(self):
        """Speichert den Schedule"""
        self.SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.SCHEDULE_FILE, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls) -> Optional["CollectionSchedule"]:
        """Lädt existierenden Schedule"""
        if cls.SCHEDULE_FILE.exists():
            with open(cls.SCHEDULE_FILE) as f:
                return cls.from_dict(json.load(f))
        return None

    @property
    def completed_batches(self) -> List[BatchPlan]:
        return [b for b in self.batches if b.status == "completed"]

    @property
    def pending_batches(self) -> List[BatchPlan]:
        return [b for b in self.batches if b.status in ("pending", "partial")]

    @property
    def next_batch(self) -> Optional[BatchPlan]:
        """Nächster ausstehender Batch"""
        pending = self.pending_batches
        return pending[0] if pending else None

    @property
    def progress_percent(self) -> float:
        if not self.batches:
            return 0.0
        completed = len(self.completed_batches)
        return (completed / len(self.batches)) * 100

    def update_batch_status(self, batch_id: int, status: str):
        """Aktualisiert Batch-Status"""
        for batch in self.batches:
            if batch.batch_id == batch_id:
                batch.status = status
                break
        self.save()


def create_schedule(
    symbols: List[str],
    batch_size: int = 50,
    daily_quota: int = 9000,
    lookback_days: int = 260,
) -> CollectionSchedule:
    """
    Erstellt einen optimierten Sammlungs-Schedule.

    Args:
        symbols: Alle zu sammelnden Symbole
        batch_size: Symbole pro Batch
        daily_quota: API-Requests pro Tag
        lookback_days: Tage Lookback

    Returns:
        CollectionSchedule
    """
    # Requests pro Symbol: 1 historical + 1 VIX (einmalig) + Retry-Buffer
    requests_per_symbol = 2

    # Batches erstellen
    batches = []
    for i in range(0, len(symbols), batch_size):
        batch_symbols = symbols[i : i + batch_size]
        batch_id = len(batches) + 1

        estimated_requests = len(batch_symbols) * requests_per_symbol
        # Erster Batch hat +1 für VIX
        if batch_id == 1:
            estimated_requests += 1

        # Zeit schätzen bei 80 req/min
        estimated_minutes = estimated_requests / 80

        batches.append(
            BatchPlan(
                batch_id=batch_id,
                symbols=batch_symbols,
                estimated_requests=estimated_requests,
                estimated_minutes=round(estimated_minutes, 1),
            )
        )

    return CollectionSchedule(
        created_at=datetime.now().isoformat(),
        total_symbols=len(symbols),
        batches=batches,
        lookback_days=lookback_days,
    )


def print_schedule(schedule: CollectionSchedule):
    """Zeigt den Schedule an"""
    print("\n" + "=" * 70)
    print("DATA COLLECTION SCHEDULE")
    print("=" * 70)

    print(f"\nCreated: {schedule.created_at[:19]}")
    print(f"Total Symbols: {schedule.total_symbols}")
    print(f"Total Batches: {len(schedule.batches)}")
    print(f"Lookback Days: {schedule.lookback_days}")

    total_requests = sum(b.estimated_requests for b in schedule.batches)
    total_minutes = sum(b.estimated_minutes for b in schedule.batches)

    print(f"\nEstimated Total:")
    print(f"  Requests: {total_requests:,}")
    print(f"  Time: {total_minutes:.0f} minutes ({total_minutes/60:.1f} hours)")

    print(f"\nProgress: {schedule.progress_percent:.1f}%")
    print(f"Completed Batches: {len(schedule.completed_batches)}/{len(schedule.batches)}")

    print("\n" + "-" * 70)
    print(f"{'Batch':<8} {'Symbols':<10} {'Requests':<12} {'Time':<10} {'Status':<12}")
    print("-" * 70)

    for batch in schedule.batches:
        status_color = {
            "completed": "✓",
            "in_progress": "►",
            "partial": "◐",
            "pending": "○",
        }.get(batch.status, "?")

        print(
            f"{batch.batch_id:<8} "
            f"{len(batch.symbols):<10} "
            f"{batch.estimated_requests:<12} "
            f"{batch.estimated_minutes:.1f} min{'':<4} "
            f"{status_color} {batch.status}"
        )

    next_batch = schedule.next_batch
    if next_batch:
        print(f"\nNext: Batch {next_batch.batch_id} ({len(next_batch.symbols)} symbols)")
        print(
            f"      Run with: python scripts/scheduled_collection.py --batch {next_batch.batch_id}"
        )


# =============================================================================
# Batch Execution
# =============================================================================


async def run_batch(
    schedule: CollectionSchedule,
    batch_id: int,
    api_key: str,
    delay: float = 0.75,
) -> bool:
    """
    Führt einen einzelnen Batch aus.

    Returns:
        True wenn erfolgreich
    """
    logger = logging.getLogger(__name__)

    # Batch finden
    batch = None
    for b in schedule.batches:
        if b.batch_id == batch_id:
            batch = b
            break

    if not batch:
        logger.error(f"Batch {batch_id} not found!")
        return False

    if batch.status == "completed":
        logger.info(f"Batch {batch_id} already completed")
        return True

    print(f"\n{'='*60}")
    print(f"BATCH {batch_id}: {len(batch.symbols)} symbols")
    print(f"Estimated: {batch.estimated_requests} requests, {batch.estimated_minutes} minutes")
    print(f"{'='*60}\n")

    # Status aktualisieren
    schedule.update_batch_status(batch_id, "in_progress")

    # Collector
    quota_config = QuotaConfig(
        min_delay_seconds=delay,
        requests_per_minute=int(60 / delay) - 5,  # Buffer
    )

    collector = HistoricalDataCollector(
        api_key=api_key,
        quota_config=quota_config,
    )

    try:
        await collector.connect()

        result = await collector.collect(
            symbols=batch.symbols,
            lookback_days=schedule.lookback_days,
            resume=False,  # Jeder Batch ist eigenständig
            progress_callback=print_progress,
        )

        print(f"\n\n{result}")

        # Status basierend auf Ergebnis
        if result.success_rate >= 95:
            schedule.update_batch_status(batch_id, "completed")
            return True
        else:
            schedule.update_batch_status(batch_id, "partial")
            logger.warning(f"Batch {batch_id} partial: {result.success_rate:.1f}% success")
            return False

    except KeyboardInterrupt:
        schedule.update_batch_status(batch_id, "partial")
        print("\n\nInterrupted! Batch marked as partial.")
        raise

    except Exception as e:
        schedule.update_batch_status(batch_id, "partial")
        logger.error(f"Batch {batch_id} failed: {e}")
        return False

    finally:
        await collector.disconnect()


async def run_all_batches(
    schedule: CollectionSchedule,
    api_key: str,
    delay: float = 0.75,
    pause_between_batches: int = 5,
):
    """
    Führt alle ausstehenden Batches nacheinander aus.
    """
    logger = logging.getLogger(__name__)

    pending = schedule.pending_batches

    if not pending:
        print("All batches completed!")
        return

    print(f"\nRunning {len(pending)} batches...")
    print(f"Pause between batches: {pause_between_batches} seconds")

    for i, batch in enumerate(pending, 1):
        print(f"\n\n{'#'*60}")
        print(f"# BATCH {batch.batch_id} of {len(schedule.batches)}")
        print(f"# Progress: {schedule.progress_percent:.1f}%")
        print(f"{'#'*60}")

        try:
            success = await run_batch(schedule, batch.batch_id, api_key, delay)

            if success and i < len(pending):
                print(f"\nPausing {pause_between_batches}s before next batch...")
                await asyncio.sleep(pause_between_batches)

        except KeyboardInterrupt:
            print(f"\n\nStopped after batch {batch.batch_id}")
            print(f"Resume with: --batch {batch.batch_id} or --next")
            return

    # Final Status
    print_schedule(schedule)


# =============================================================================
# CLI
# =============================================================================


async def main():
    parser = argparse.ArgumentParser(
        description="Scheduled batch data collection for OptionPlay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Actions
    parser.add_argument("--plan", action="store_true", help="Show/create collection plan")
    parser.add_argument("--batch", type=int, help="Run specific batch number")
    parser.add_argument("--next", action="store_true", help="Run next pending batch")
    parser.add_argument("--run-all", action="store_true", help="Run all pending batches")
    parser.add_argument("--reset", action="store_true", help="Reset schedule (mark all as pending)")

    # Options
    parser.add_argument(
        "--batch-size", type=int, default=50, help="Symbols per batch (default: 50)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.75, help="Delay between requests (default: 0.75s)"
    )
    parser.add_argument(
        "--pause", type=int, default=5, help="Pause between batches in seconds (default: 5)"
    )
    parser.add_argument("--days", type=int, default=260, help="Days of history (default: 260)")

    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Schedule laden oder erstellen
    schedule = CollectionSchedule.load()

    if schedule is None or args.plan:
        print("Creating new collection schedule...")
        symbols = get_all_symbols()
        schedule = create_schedule(
            symbols=symbols,
            batch_size=args.batch_size,
            lookback_days=args.days,
        )
        schedule.save()
        print_schedule(schedule)

        if not args.batch and not args.next and not args.run_all:
            return

    # Reset
    if args.reset:
        for batch in schedule.batches:
            batch.status = "pending"
        schedule.save()
        print("Schedule reset. All batches marked as pending.")
        print_schedule(schedule)
        return

    # Plan anzeigen
    if args.plan:
        print_schedule(schedule)
        return

    # API Key
    api_key = get_api_key()

    # Batch ausführen
    if args.batch:
        await run_batch(schedule, args.batch, api_key, args.delay)

    elif args.next:
        next_batch = schedule.next_batch
        if next_batch:
            await run_batch(schedule, next_batch.batch_id, api_key, args.delay)
        else:
            print("No pending batches!")

    elif args.run_all:
        await run_all_batches(schedule, api_key, args.delay, args.pause)

    else:
        print_schedule(schedule)
        print("\nUse --batch N, --next, or --run-all to start collection")


if __name__ == "__main__":
    asyncio.run(main())
