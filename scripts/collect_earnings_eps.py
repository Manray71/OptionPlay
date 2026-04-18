#!/usr/bin/env python3
"""
OptionPlay - Collect Earnings EPS Data from yfinance
=====================================================

Aktualisiert die earnings_history Tabelle mit EPS-Daten von yfinance:
- eps_actual (Reported EPS)
- eps_estimate (EPS Estimate)
- eps_surprise (Differenz)
- eps_surprise_pct (Differenz in %)

Usage:
    # Alle Symbole aus der earnings_history Tabelle
    python scripts/collect_earnings_eps.py

    # Spezifische Symbole
    python scripts/collect_earnings_eps.py --symbols AAPL MSFT GOOGL

    # Nur Symbole ohne EPS-Daten
    python scripts/collect_earnings_eps.py --missing-only
"""

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".optionplay" / "trades.db"


def get_symbols_from_earnings_history() -> List[str]:
    """Holt alle Symbole aus earnings_history"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT symbol FROM earnings_history ORDER BY symbol")
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    logger.info(f"earnings_history: {len(symbols)} Symbole gefunden")
    return symbols


def get_symbols_missing_eps() -> List[str]:
    """Holt Symbole die keine EPS-Daten haben"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT symbol FROM earnings_history
        WHERE eps_actual IS NULL AND eps_estimate IS NULL
        ORDER BY symbol
    """)
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    logger.info(f"Symbole ohne EPS-Daten: {len(symbols)}")
    return symbols


def fetch_earnings_from_yfinance(symbol: str) -> List[Dict[str, Any]]:
    """
    Holt historische Earnings-Daten von yfinance.

    Returns:
        Liste von Dicts mit earnings_date, eps_actual, eps_estimate, etc.
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        logger.error("yfinance nicht installiert. Run: pip install yfinance")
        return []

    max_retries = 3
    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(symbol)
            earnings_dates = ticker.earnings_dates

            if earnings_dates is None or earnings_dates.empty:
                return []
            break
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "too many" in err_str or "429" in err_str:
                wait = 30 * (attempt + 1)
                logger.warning(f"Rate limited on {symbol}, waiting {wait}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                if attempt == max_retries - 1:
                    logger.error(f"Rate limited on {symbol} after {max_retries} retries, skipping")
                    return []
            else:
                logger.warning(f"Fehler beim Abrufen von yfinance Earnings für {symbol}: {e}")
                return []

    try:

        results = []
        now = pd.Timestamp.now(tz="UTC")

        # Konvertiere Index zu UTC wenn nötig
        if earnings_dates.index.tz is None:
            earnings_dates.index = earnings_dates.index.tz_localize("UTC")

        for idx, row in earnings_dates.iterrows():
            try:
                # Nur vergangene Earnings mit EPS-Daten
                if idx >= now:
                    continue

                eps_actual = row.get("Reported EPS")
                eps_estimate = row.get("EPS Estimate")

                # Skip wenn keine Daten
                if pd.isna(eps_actual) and pd.isna(eps_estimate):
                    continue

                # Konvertiere zu float
                eps_actual = float(eps_actual) if pd.notna(eps_actual) else None
                eps_estimate = float(eps_estimate) if pd.notna(eps_estimate) else None

                # Surprise berechnen
                eps_surprise = None
                eps_surprise_pct = None
                if eps_actual is not None and eps_estimate is not None:
                    eps_surprise = round(eps_actual - eps_estimate, 4)
                    if eps_estimate != 0:
                        eps_surprise_pct = round(
                            (eps_actual - eps_estimate) / abs(eps_estimate) * 100, 2
                        )

                result = {
                    "earnings_date": idx.strftime("%Y-%m-%d"),
                    "eps_actual": eps_actual,
                    "eps_estimate": eps_estimate,
                    "eps_surprise": eps_surprise,
                    "eps_surprise_pct": eps_surprise_pct,
                }
                results.append(result)

            except Exception as e:
                logger.debug(f"Fehler beim Parsen von {symbol} Earnings: {e}")
                continue

        return results

    except Exception as e:
        logger.warning(f"Fehler beim Parsen von {symbol} Earnings-Daten: {e}")
        return []


def update_earnings_eps(symbol: str, earnings_data: List[Dict[str, Any]]) -> int:
    """
    Aktualisiert die EPS-Daten in earnings_history.

    Returns:
        Anzahl der aktualisierten Einträge
    """
    if not earnings_data:
        return 0

    updated = 0
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    for data in earnings_data:
        try:
            # Update nur wenn Daten vorhanden
            cursor.execute(
                """
                UPDATE earnings_history
                SET eps_actual = COALESCE(?, eps_actual),
                    eps_estimate = COALESCE(?, eps_estimate),
                    eps_surprise = COALESCE(?, eps_surprise),
                    eps_surprise_pct = COALESCE(?, eps_surprise_pct),
                    source = 'yfinance'
                WHERE symbol = ? AND earnings_date = ?
            """,
                (
                    data.get("eps_actual"),
                    data.get("eps_estimate"),
                    data.get("eps_surprise"),
                    data.get("eps_surprise_pct"),
                    symbol.upper(),
                    data.get("earnings_date"),
                ),
            )

            if cursor.rowcount > 0:
                updated += 1

        except sqlite3.Error as e:
            logger.warning(f"Fehler beim Update von {symbol}: {e}")

    conn.commit()
    conn.close()

    return updated


def insert_missing_earnings(symbol: str, earnings_data: List[Dict[str, Any]]) -> int:
    """
    Fügt neue Earnings-Einträge ein, die nicht in der DB sind.

    Returns:
        Anzahl der eingefügten Einträge
    """
    if not earnings_data:
        return 0

    inserted = 0
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    for data in earnings_data:
        try:
            # Check ob Eintrag existiert
            cursor.execute(
                """
                SELECT 1 FROM earnings_history
                WHERE symbol = ? AND earnings_date = ?
            """,
                (symbol.upper(), data.get("earnings_date")),
            )

            if cursor.fetchone() is None:
                # Insert neuer Eintrag
                cursor.execute(
                    """
                    INSERT INTO earnings_history (
                        symbol, earnings_date, eps_actual, eps_estimate,
                        eps_surprise, eps_surprise_pct, source, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'yfinance', ?)
                """,
                    (
                        symbol.upper(),
                        data.get("earnings_date"),
                        data.get("eps_actual"),
                        data.get("eps_estimate"),
                        data.get("eps_surprise"),
                        data.get("eps_surprise_pct"),
                        datetime.now().isoformat(),
                    ),
                )
                inserted += 1

        except sqlite3.Error as e:
            logger.warning(f"Fehler beim Insert von {symbol}: {e}")

    conn.commit()
    conn.close()

    return inserted


def get_watchlist_symbols() -> List[str]:
    """Holt alle Symbole aus der default_275 Watchlist."""
    try:
        from src.config.watchlist_loader import WatchlistLoader

        loader = WatchlistLoader()
        symbols = loader.get_symbols_from_watchlist("default_275")
        logger.info(f"Watchlist: {len(symbols)} Symbole geladen")
        return symbols
    except Exception as e:
        logger.warning(f"Watchlist konnte nicht geladen werden: {e}. Fallback auf earnings_history.")
        return get_symbols_from_earnings_history()


def backfill_future_earnings_dates(symbols: List[str], delay: float = 1.0) -> Dict[str, int]:
    """
    Holt zukünftige Earnings-Termine von yfinance.Ticker.calendar und
    fügt fehlende Einträge in earnings_history ein.

    Returns:
        Dict mit {inserted: n, skipped: n, errors: n}
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        logger.error("yfinance nicht installiert. Run: pip install yfinance")
        return {"inserted": 0, "skipped": 0, "errors": 0}

    today = date.today().isoformat()
    inserted = 0
    skipped = 0
    errors = 0

    conn = sqlite3.connect(str(DB_PATH))

    for i, sym in enumerate(symbols, 1):
        try:
            ticker = yf.Ticker(sym)
            cal = ticker.calendar

            if cal is None:
                skipped += 1
                continue

            # 'Earnings Date' kann eine Liste oder ein einzelner Timestamp sein
            raw_dates = cal.get("Earnings Date")
            if raw_dates is None:
                skipped += 1
                continue

            if not isinstance(raw_dates, list):
                raw_dates = [raw_dates]

            eps_estimate = cal.get("Earnings Average")
            if eps_estimate is not None:
                try:
                    eps_estimate = float(eps_estimate)
                except (TypeError, ValueError):
                    eps_estimate = None

            for ed in raw_dates:
                try:
                    if hasattr(ed, "date"):
                        ed_date = ed.date()
                    else:
                        ed_date = pd.Timestamp(ed).date()

                    ed_str = ed_date.isoformat()

                    # Nur zukünftige oder heutige Termine
                    if ed_str < today:
                        continue

                    existing = conn.execute(
                        "SELECT 1 FROM earnings_history WHERE symbol = ? AND earnings_date = ?",
                        (sym.upper(), ed_str),
                    ).fetchone()

                    if existing:
                        skipped += 1
                        continue

                    conn.execute(
                        """INSERT INTO earnings_history
                           (symbol, earnings_date, eps_estimate, source)
                           VALUES (?, ?, ?, 'yfinance_calendar')""",
                        (sym.upper(), ed_str, eps_estimate),
                    )
                    inserted += 1
                    logger.debug(f"  {sym}: inserted future earnings {ed_str}")

                except Exception as e:
                    logger.debug(f"  {sym}: Fehler bei Datum {ed}: {e}")
                    errors += 1

        except Exception as e:
            logger.warning(f"  {sym}: calendar-Fehler - {e}")
            errors += 1

        if i < len(symbols) and delay > 0:
            time.sleep(delay)

    conn.commit()
    conn.close()
    logger.info(
        f"Future earnings backfill: {inserted} inserted, {skipped} already existed / no date, {errors} errors"
    )
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


def process_symbol(symbol: str) -> Dict[str, int]:
    """
    Verarbeitet ein Symbol: Holt Daten und aktualisiert DB.

    Returns:
        Dict mit {updated: n, inserted: n, fetched: n}
    """
    earnings_data = fetch_earnings_from_yfinance(symbol)

    if not earnings_data:
        return {"fetched": 0, "updated": 0, "inserted": 0}

    updated = update_earnings_eps(symbol, earnings_data)
    inserted = insert_missing_earnings(symbol, earnings_data)

    return {"fetched": len(earnings_data), "updated": updated, "inserted": inserted}


def get_eps_statistics() -> Dict[str, Any]:
    """Holt Statistiken über EPS-Daten"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM earnings_history")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM earnings_history WHERE eps_actual IS NOT NULL")
    with_eps_actual = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM earnings_history WHERE eps_estimate IS NOT NULL")
    with_eps_estimate = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM earnings_history
        WHERE eps_actual IS NOT NULL AND eps_estimate IS NOT NULL
    """)
    with_both = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(DISTINCT symbol) FROM earnings_history WHERE eps_actual IS NOT NULL"
    )
    symbols_with_eps = cursor.fetchone()[0]

    conn.close()

    return {
        "total_earnings": total,
        "with_eps_actual": with_eps_actual,
        "with_eps_estimate": with_eps_estimate,
        "with_both": with_both,
        "symbols_with_eps": symbols_with_eps,
        "coverage_pct": round(with_both / total * 100, 1) if total > 0 else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Collect Earnings EPS Data from yfinance")

    parser.add_argument(
        "--symbols",
        "-s",
        nargs="+",
        help="Spezifische Symbole (default: alle aus earnings_history)",
    )
    parser.add_argument(
        "--missing-only", action="store_true", help="Nur Symbole ohne EPS-Daten verarbeiten"
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=1.5,
        help="Delay zwischen API-Aufrufen in Sekunden (default: 1.5)",
    )
    parser.add_argument("--stats", action="store_true", help="Nur Statistiken anzeigen")

    args = parser.parse_args()

    # Nur Statistiken
    if args.stats:
        stats = get_eps_statistics()
        logger.info(f"\n{'='*60}")
        logger.info("EPS-DATEN STATISTIKEN")
        logger.info(f"{'='*60}")
        logger.info(f"Gesamt Earnings-Einträge: {stats['total_earnings']}")
        logger.info(f"Mit EPS Actual: {stats['with_eps_actual']}")
        logger.info(f"Mit EPS Estimate: {stats['with_eps_estimate']}")
        logger.info(f"Mit beiden: {stats['with_both']} ({stats['coverage_pct']}%)")
        logger.info(f"Symbole mit EPS-Daten: {stats['symbols_with_eps']}")
        return

    # Schritt 1: Zukünftige Earnings-Termine aus yfinance.calendar backfillen
    logger.info(f"\n{'='*60}")
    logger.info("SCHRITT 1: Zukünftige Earnings-Termine backfillen")
    logger.info(f"{'='*60}")
    watchlist_symbols = get_watchlist_symbols()
    backfill_future_earnings_dates(watchlist_symbols, delay=args.delay)

    # Schritt 2: EPS-Daten für historische Einträge aktualisieren
    logger.info(f"\n{'='*60}")
    logger.info("SCHRITT 2: EPS-Daten aktualisieren")
    logger.info(f"{'='*60}")

    # Symbole bestimmen
    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
        logger.info(f"Verarbeite {len(symbols)} spezifizierte Symbole")
    elif args.missing_only:
        symbols = get_symbols_missing_eps()
    else:
        symbols = get_symbols_from_earnings_history()

    if not symbols:
        logger.error("Keine Symbole gefunden!")
        sys.exit(1)

    logger.info(f"\n{'='*60}")
    logger.info(f"Sammle EPS-Daten für {len(symbols)} Symbole")
    logger.info(f"{'='*60}")

    start_time = time.time()
    total_fetched = 0
    total_updated = 0
    total_inserted = 0
    successful = 0

    for i, symbol in enumerate(symbols, 1):
        result = process_symbol(symbol)

        if result["fetched"] > 0:
            successful += 1
            total_fetched += result["fetched"]
            total_updated += result["updated"]
            total_inserted += result["inserted"]
            logger.info(
                f"[{i}/{len(symbols)}] {symbol}: {result['fetched']} Earnings, {result['updated']} updated, {result['inserted']} inserted"
            )
        else:
            logger.debug(f"[{i}/{len(symbols)}] {symbol}: keine Daten")

        if i < len(symbols) and args.delay > 0:
            time.sleep(args.delay)

    elapsed = time.time() - start_time

    # Finale Statistiken
    stats = get_eps_statistics()

    logger.info(f"\n{'='*60}")
    logger.info("ERGEBNIS")
    logger.info(f"{'='*60}")
    logger.info(f"Symbole verarbeitet: {successful}/{len(symbols)}")
    logger.info(f"Earnings-Datensätze geholt: {total_fetched}")
    logger.info(f"Einträge aktualisiert: {total_updated}")
    logger.info(f"Einträge eingefügt: {total_inserted}")
    logger.info(
        f"\nEPS-Coverage: {stats['coverage_pct']}% ({stats['with_both']}/{stats['total_earnings']})"
    )
    logger.info(f"Dauer: {elapsed:.1f} Sekunden")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
