#!/usr/bin/env python3
"""
OptionPlay - Populate Symbol Fundamentals
==========================================

Befüllt die symbol_fundamentals Tabelle mit Daten aus:
1. yfinance: Sector, Industry, Market Cap, Beta, Inst. Ownership, Analyst Ratings
2. outcomes.db: Stability Score, Historical Win Rate, Avg Drawdown
3. earnings_history: Earnings Beat Rate

Usage:
    # Alle Symbole aus der Watchlist
    python scripts/populate_fundamentals.py

    # Spezifische Symbole
    python scripts/populate_fundamentals.py --symbols AAPL MSFT GOOGL

    # Nur yfinance-Daten (schneller)
    python scripts/populate_fundamentals.py --yfinance-only

    # Nur Stability-Daten updaten
    python scripts/populate_fundamentals.py --stability-only

    # Nur Earnings Beat Rate updaten
    python scripts/populate_fundamentals.py --earnings-only
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.cache.symbol_fundamentals import (
    SymbolFundamentalsManager,
    get_fundamentals_manager
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_watchlist_symbols() -> list:
    """Holt alle Symbole aus der Watchlist"""
    try:
        from src.config.watchlist_loader import WatchlistLoader
        loader = WatchlistLoader()
        symbols = loader.get_all_symbols()
        logger.info(f"Watchlist: {len(symbols)} Symbole geladen")
        return symbols
    except Exception as e:
        logger.error(f"Fehler beim Laden der Watchlist: {e}")
        return []


def get_symbols_from_outcomes_db() -> list:
    """Holt alle Symbole aus outcomes.db"""
    import sqlite3
    outcomes_db = Path.home() / ".optionplay" / "outcomes.db"

    if not outcomes_db.exists():
        logger.warning(f"outcomes.db nicht gefunden: {outcomes_db}")
        return []

    try:
        conn = sqlite3.connect(str(outcomes_db))
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM trade_outcomes ORDER BY symbol")
        symbols = [row[0] for row in cursor.fetchall()]
        conn.close()
        logger.info(f"outcomes.db: {len(symbols)} Symbole gefunden")
        return symbols
    except Exception as e:
        logger.error(f"Fehler beim Lesen von outcomes.db: {e}")
        return []


def populate_yfinance(manager: SymbolFundamentalsManager, symbols: list, delay: float = 0.5):
    """Holt Fundamentaldaten von yfinance für alle Symbole"""
    logger.info(f"\n{'='*60}")
    logger.info("PHASE 1: yfinance Fundamentaldaten")
    logger.info(f"{'='*60}")

    results = manager.update_all_from_yfinance(symbols, delay_seconds=delay)

    successful = sum(1 for v in results.values() if v)
    failed = [s for s, v in results.items() if not v]

    logger.info(f"\nyfinance Ergebnis: {successful}/{len(symbols)} erfolgreich")

    if failed and len(failed) <= 20:
        logger.warning(f"Fehlgeschlagen: {', '.join(failed)}")

    return results


def populate_stability(manager: SymbolFundamentalsManager, symbols: list):
    """Berechnet Stability-Metriken aus outcomes.db"""
    logger.info(f"\n{'='*60}")
    logger.info("PHASE 2: Stability Score aus outcomes.db")
    logger.info(f"{'='*60}")

    successful = 0
    total = len(symbols)

    for i, symbol in enumerate(symbols, 1):
        success = manager.update_stability_from_outcomes(symbol)
        if success:
            successful += 1
            logger.debug(f"[{i}/{total}] {symbol}: ✓")
        else:
            logger.debug(f"[{i}/{total}] {symbol}: keine Daten")

    logger.info(f"\nStability Ergebnis: {successful}/{total} erfolgreich")

    return successful


def populate_earnings_beat_rate(manager: SymbolFundamentalsManager, symbols: list):
    """Berechnet Earnings Beat Rate aus earnings_history"""
    logger.info(f"\n{'='*60}")
    logger.info("PHASE 3: Earnings Beat Rate")
    logger.info(f"{'='*60}")

    successful = 0
    total = len(symbols)

    for i, symbol in enumerate(symbols, 1):
        success = manager.update_earnings_beat_rate(symbol)
        if success:
            successful += 1

    logger.info(f"\nEarnings Beat Rate: {successful}/{total} erfolgreich")

    return successful


def populate_proxy_stability(manager: SymbolFundamentalsManager):
    """
    Calculate proxy stability scores for symbols without backtest data.

    Uses Beta and Historical Volatility as proxies when outcomes.db
    has no trade data for a symbol.

    Formula: proxy_stability = 100 - (beta * 15) - (hv_30d * 0.5)
    Clamped to [40, 85] range and marked as proxy data.
    """
    logger.info(f"\n{'='*60}")
    logger.info("PHASE 4: Proxy Stability Scores")
    logger.info(f"{'='*60}")

    all_fundamentals = manager.get_all_fundamentals()
    missing = [f for f in all_fundamentals if f.stability_score is None]

    if not missing:
        logger.info("Alle Symbole haben Stability Scores - nichts zu tun")
        return 0

    logger.info(f"{len(missing)} Symbole ohne Stability Score gefunden")

    # Calculate sector averages for fallback
    sector_stability = {}
    for f in all_fundamentals:
        if f.stability_score is not None and f.sector:
            sector_stability.setdefault(f.sector, []).append(f.stability_score)

    sector_avg = {
        sector: sum(scores) / len(scores)
        for sector, scores in sector_stability.items()
    }
    overall_avg = sum(
        f.stability_score for f in all_fundamentals if f.stability_score is not None
    ) / max(1, len([f for f in all_fundamentals if f.stability_score is not None]))

    updated = 0
    for f in missing:
        beta = f.beta if f.beta is not None else 1.0
        hv = f.historical_volatility_30d if f.historical_volatility_30d is not None else 25.0

        # Calculate proxy score
        proxy = 100 - (beta * 15) - (hv * 0.5)

        # Use sector average as anchor if available
        if f.sector and f.sector in sector_avg:
            anchor = sector_avg[f.sector]
            # Blend: 60% formula, 40% sector average
            proxy = proxy * 0.6 + anchor * 0.4

        # Clamp to reasonable range (proxy scores should not reach extremes)
        proxy = max(40.0, min(85.0, proxy))

        f.stability_score = round(proxy, 1)
        f.data_source = "proxy"

        if manager.save_fundamentals(f):
            updated += 1
            logger.debug(
                f"  {f.symbol}: Proxy Stability = {f.stability_score:.1f} "
                f"(beta={beta:.2f}, hv={hv:.1f}%)"
            )

    logger.info(f"\nProxy Stability: {updated}/{len(missing)} berechnet")
    return updated


def print_statistics(manager: SymbolFundamentalsManager):
    """Zeigt Statistiken über die gespeicherten Daten"""
    stats = manager.get_statistics()

    logger.info(f"\n{'='*60}")
    logger.info("STATISTIKEN")
    logger.info(f"{'='*60}")

    logger.info(f"Gesamt Symbole: {stats['total_symbols']}")
    logger.info(f"Mit Stability Score: {stats['with_stability_score']} ({stats['stability_coverage_pct']}%)")

    logger.info("\nNach Sektor:")
    for sector, count in sorted(stats['by_sector'].items(), key=lambda x: -x[1]):
        logger.info(f"  {sector}: {count}")

    logger.info("\nNach Market Cap:")
    for cat, count in stats['by_market_cap'].items():
        logger.info(f"  {cat}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Populate Symbol Fundamentals Database")

    parser.add_argument(
        '--symbols', '-s',
        nargs='+',
        help='Spezifische Symbole (default: Watchlist)'
    )
    parser.add_argument(
        '--yfinance-only',
        action='store_true',
        help='Nur yfinance-Daten holen'
    )
    parser.add_argument(
        '--stability-only',
        action='store_true',
        help='Nur Stability-Scores updaten'
    )
    parser.add_argument(
        '--earnings-only',
        action='store_true',
        help='Nur Earnings Beat Rate updaten'
    )
    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=0.5,
        help='Delay zwischen API-Aufrufen in Sekunden (default: 0.5)'
    )
    parser.add_argument(
        '--proxy-stability',
        action='store_true',
        help='Nur Proxy-Stability Scores fuer Symbole ohne Backtest-Daten berechnen'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Nur Statistiken anzeigen'
    )

    args = parser.parse_args()

    # Manager initialisieren
    manager = get_fundamentals_manager()

    # Nur Statistiken
    if args.stats:
        print_statistics(manager)
        return

    # Symbole bestimmen
    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
        logger.info(f"Verarbeite {len(symbols)} spezifizierte Symbole")
    else:
        # Kombination aus Watchlist und outcomes.db
        watchlist = get_watchlist_symbols()
        outcomes = get_symbols_from_outcomes_db()
        symbols = list(set(watchlist + outcomes))
        symbols.sort()
        logger.info(f"Verarbeite {len(symbols)} Symbole (Watchlist + outcomes.db)")

    if not symbols:
        logger.error("Keine Symbole gefunden!")
        sys.exit(1)

    start_time = time.time()

    # Welche Phasen ausführen
    if args.yfinance_only:
        populate_yfinance(manager, symbols, args.delay)

    elif args.stability_only:
        populate_stability(manager, symbols)

    elif args.earnings_only:
        populate_earnings_beat_rate(manager, symbols)

    elif args.proxy_stability:
        populate_proxy_stability(manager)

    else:
        # Alle Phasen
        populate_yfinance(manager, symbols, args.delay)
        populate_stability(manager, symbols)
        populate_earnings_beat_rate(manager, symbols)
        populate_proxy_stability(manager)

    elapsed = time.time() - start_time

    # Finale Statistiken
    print_statistics(manager)

    logger.info(f"\n{'='*60}")
    logger.info(f"Fertig in {elapsed:.1f} Sekunden")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
