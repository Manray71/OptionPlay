#!/usr/bin/env python3
"""
OptionPlay - VIX Historical Data Collection from TWS
====================================================

Holt historische VIX-Daten von IBKR TWS und speichert sie
in der Backtesting-Datenbank.

Voraussetzungen:
- TWS oder IB Gateway muss laufen
- API muss aktiviert sein (Edit > Global Config > API > Settings)
- Port 7497 (Paper) oder 7496 (Live)

Usage:
    python scripts/collect_vix_from_tws.py
    python scripts/collect_vix_from_tws.py --days 500
    python scripts/collect_vix_from_tws.py --port 7496  # Live
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime, date

# Fix für nested event loops
import nest_asyncio
nest_asyncio.apply()

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtesting import TradeTracker
from src.backtesting.trade_tracker import VixDataPoint


def collect_vix(port: int = 7497, days: int = 260) -> int:
    """
    Holt historische VIX-Daten von TWS.

    Args:
        port: TWS Port (7497=Paper, 7496=Live)
        days: Anzahl Tage Historie

    Returns:
        Anzahl gespeicherter VIX-Datenpunkte
    """
    try:
        from ib_insync import IB, Index, util
    except ImportError:
        print("ERROR: ib_insync nicht installiert")
        print("Run: pip install ib_insync")
        return 0

    # Start event loop für ib_insync
    util.startLoop()

    ib = IB()

    print(f"Verbinde zu TWS auf Port {port}...")

    try:
        ib.connect('127.0.0.1', port, clientId=99, timeout=20)
        print("✓ TWS verbunden")
    except Exception as e:
        print(f"✗ TWS Verbindung fehlgeschlagen: {e}")
        print("\nStelle sicher dass:")
        print("  1. TWS oder IB Gateway läuft")
        print("  2. API aktiviert ist (Edit > Global Config > API > Settings)")
        print(f"  3. Port {port} korrekt ist (Paper=7497, Live=7496)")
        return 0

    try:
        # VIX Index Contract
        vix = Index('VIX', 'CBOE')
        ib.qualifyContracts(vix)
        print(f"✓ VIX Contract qualifiziert: {vix}")

        # Duration String berechnen
        if days <= 365:
            duration = f"{days} D"
        else:
            years = days // 365
            duration = f"{years} Y"

        print(f"Hole {duration} historische VIX-Daten...")

        # Historische Daten anfordern (synchron)
        bars = ib.reqHistoricalData(
            vix,
            endDateTime='',  # Bis jetzt
            durationStr=duration,
            barSizeSetting='1 day',
            whatToShow='TRADES',
            useRTH=True,
            formatDate=1
        )

        if not bars:
            print("✗ Keine VIX-Daten erhalten")
            return 0

        print(f"✓ {len(bars)} VIX-Bars erhalten")
        print(f"  Von: {bars[0].date}")
        print(f"  Bis: {bars[-1].date}")

        # In VixDataPoints konvertieren
        vix_points = []
        for bar in bars:
            # bar.date ist bereits ein date/datetime Objekt
            bar_date = bar.date if isinstance(bar.date, date) else date.fromisoformat(str(bar.date)[:10])
            vix_points.append(VixDataPoint(
                date=bar_date,
                value=bar.close
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

    finally:
        ib.disconnect()
        print("TWS getrennt")


def main():
    parser = argparse.ArgumentParser(
        description='Collect historical VIX data from IBKR TWS'
    )
    parser.add_argument('--port', type=int, default=7497,
                        help='TWS Port (7497=Paper, 7496=Live)')
    parser.add_argument('--days', type=int, default=260,
                        help='Days of history (default: 260)')

    args = parser.parse_args()

    print("=" * 60)
    print("VIX HISTORICAL DATA COLLECTION (TWS)")
    print("=" * 60)
    print()

    count = collect_vix(args.port, args.days)

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
