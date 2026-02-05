#!/usr/bin/env python3
"""
OptionPlay - VIX Historical Data Collection from Yahoo Finance
==============================================================

Holt historische VIX-Daten von Yahoo Finance (kostenlos, kein API-Key)
und speichert sie in der Backtesting-Datenbank.

Usage:
    python scripts/collect_vix_yahoo.py
    python scripts/collect_vix_yahoo.py --days 500
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, date, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting.tracking import TradeTracker, VixDataPoint


def collect_vix(days: int = 260) -> int:
    """
    Holt historische VIX-Daten von Yahoo Finance.

    Args:
        days: Anzahl Tage Historie

    Returns:
        Anzahl gespeicherter VIX-Datenpunkte
    """
    try:
        import yfinance as yf
    except ImportError:
        print("ERROR: yfinance nicht installiert")
        print("Run: pip install yfinance")
        return 0

    print(f"Hole VIX-Daten von Yahoo Finance ({days} Tage)...")

    try:
        # VIX Ticker
        vix = yf.Ticker("^VIX")

        # Historische Daten holen
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days + 10)  # Etwas mehr für Wochenenden

        hist = vix.history(start=start_date, end=end_date)

        if hist.empty:
            print("✗ Keine VIX-Daten erhalten")
            return 0

        print(f"✓ {len(hist)} VIX-Bars erhalten")
        print(f"  Von: {hist.index[0].date()}")
        print(f"  Bis: {hist.index[-1].date()}")

        # In VixDataPoints konvertieren
        vix_points = []
        for idx, row in hist.iterrows():
            bar_date = idx.date() if hasattr(idx, 'date') else date.fromisoformat(str(idx)[:10])
            vix_points.append(VixDataPoint(
                date=bar_date,
                value=round(row['Close'], 2)
            ))

        # In Datenbank speichern
        tracker = TradeTracker()
        count = tracker.store_vix_data(vix_points)

        print(f"✓ {count} VIX-Datenpunkte gespeichert")

        # Verifizieren
        vix_range = tracker.get_vix_range()
        if vix_range:
            print(f"  Gespeicherter Bereich: {vix_range[0]} bis {vix_range[1]}")

        return count

    except Exception as e:
        print(f"✗ Fehler: {e}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    parser = argparse.ArgumentParser(
        description='Collect historical VIX data from Yahoo Finance'
    )
    parser.add_argument('--days', type=int, default=260,
                        help='Days of history (default: 260)')

    args = parser.parse_args()

    print("=" * 60)
    print("VIX HISTORICAL DATA COLLECTION (Yahoo Finance)")
    print("=" * 60)
    print()

    count = collect_vix(args.days)

    if count > 0:
        print()
        print("=" * 60)
        print(f"SUCCESS: {count} VIX data points collected")
        print("=" * 60)
    else:
        print()
        print("=" * 60)
        print("FAILED: No VIX data collected")
        print("=" * 60)
        sys.exit(1)


if __name__ == '__main__':
    main()
