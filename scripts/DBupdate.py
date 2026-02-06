#!/usr/bin/env python3
"""
OptionPlay - Daily DB Update (All-in-One)
==========================================

Prüft den letzten Datenstand und füllt nur die Lücke seit dem
letzten vorhandenen Datum bis gestern auf. Historische Lücken
werden NICHT angefasst.

Schritte:
  1. VIX via Yahoo Finance
  2. Options-Chain via Marketdata.app
  3. Greeks berechnen für neue Options ohne Greeks

Usage:
    python scripts/DBupdate.py              # Komplettes Update
    python scripts/DBupdate.py --status     # Nur Status zeigen
    python scripts/DBupdate.py --dry-run    # Zeigt was passieren würde
    python scripts/DBupdate.py --steps vix  # Nur VIX
    python scripts/DBupdate.py -v           # Verbose
"""

import argparse
import asyncio
import logging
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = Path.home() / ".optionplay" / "trades.db"
LOG_DIR = Path.home() / ".optionplay" / "logs"
ALL_STEPS = ["vix", "options", "greeks"]


def setup_logging(verbose=False):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("dbupdate")
    logger.setLevel(level)
    logger.handlers.clear()
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(ch)
    fh = logging.FileHandler(LOG_DIR / "dbupdate.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(fh)
    return logger


def get_status():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT MAX(date) FROM vix_data")
    vix_max = cur.fetchone()[0]
    cur = conn.execute("SELECT MAX(quote_date), COUNT(*), COUNT(DISTINCT underlying) FROM options_prices")
    r = cur.fetchone()
    opt_max, opt_count, opt_symbols = r
    cur = conn.execute(
        "SELECT COUNT(*) FROM options_prices p "
        "LEFT JOIN options_greeks g ON p.id = g.options_price_id "
        "WHERE g.id IS NULL"
    )
    greeks_pending = cur.fetchone()[0]
    conn.close()
    return {
        "vix_max": vix_max,
        "opt_max": opt_max, "opt_count": opt_count, "opt_symbols": opt_symbols,
        "greeks_pending": greeks_pending,
    }


def print_status(s, logger):
    today = date.today()
    logger.info("DB STATUS:")
    if s["vix_max"]:
        d = (today - date.fromisoformat(s["vix_max"])).days
        logger.info(f"  VIX:     bis {s['vix_max']}  {'[aktuell]' if d <= 1 else f'[{d}d alt]'}")
    if s["opt_max"]:
        d = (today - date.fromisoformat(s["opt_max"])).days
        logger.info(f"  Options: bis {s['opt_max']}  {'[aktuell]' if d <= 1 else f'[{d}d alt]'}  ({s['opt_count']:,} Preise, {s['opt_symbols']} Symbole)")
    logger.info(f"  Greeks:  {s['greeks_pending']:,} ausstehend")


# -- Step 1: VIX --

def step_vix(logger, status, dry_run=False):
    logger.info("--- STEP 1: VIX (Yahoo Finance) ---")
    last = status["vix_max"]
    if not last:
        logger.error("  Keine VIX-Daten - manuell initialisieren")
        return False
    last_date = date.fromisoformat(last)
    yesterday = date.today() - timedelta(days=1)
    if last_date >= yesterday:
        logger.info(f"  Aktuell bis {last_date} - nichts zu tun")
        return True
    fetch_start = last_date + timedelta(days=1)
    logger.info(f"  Hole: {fetch_start} bis {yesterday}")
    if dry_run:
        logger.info("  [DRY RUN]")
        return True
    try:
        import yfinance as yf
        hist = yf.Ticker("^VIX").history(start=fetch_start, end=date.today())
        if hist.empty:
            logger.warning("  Keine Daten von Yahoo")
            return False
        conn = sqlite3.connect(str(DB_PATH))
        now = datetime.now().isoformat()
        inserted = 0
        for idx, row in hist.iterrows():
            d = idx.date() if hasattr(idx, 'date') else date.fromisoformat(str(idx)[:10])
            cur = conn.execute(
                "INSERT OR IGNORE INTO vix_data (date, value, created_at) VALUES (?,?,?)",
                (d.isoformat(), round(row['Close'], 2), now)
            )
            if cur.rowcount > 0:
                inserted += 1
        conn.commit()
        conn.close()
        logger.info(f"  +{inserted} VIX-Punkte")
        return True
    except Exception as e:
        logger.error(f"  Fehler: {e}")
        return False


# -- Step 2: Options --

async def step_options(logger, status, dry_run=False):
    logger.info("--- STEP 2: Options-Chain (Marketdata.app) ---")
    last = status["opt_max"]
    if not last:
        logger.error("  Keine Options-Daten - manuell initialisieren")
        return False
    last_date = date.fromisoformat(last)
    yesterday = date.today() - timedelta(days=1)
    # Zähle fehlende Handelstage (Mo-Fr) zwischen last_date+1 und gestern
    days_missing = 0
    d = last_date + timedelta(days=1)
    while d <= yesterday:
        if d.weekday() < 5:
            days_missing += 1
        d += timedelta(days=1)
    if days_missing == 0:
        logger.info(f"  Aktuell bis {last_date} - nichts zu tun")
        return True
    logger.info(f"  Letzter Stand: {last_date}")
    logger.info(f"  Fehlend: {days_missing} Handelstag(e)")
    if dry_run:
        logger.info("  [DRY RUN]")
        return True
    try:
        from src.config.watchlist_loader import get_watchlist_loader
        from scripts.collect_options_prices import OptionsCollector, get_api_key, get_db_path
        symbols = get_watchlist_loader().get_all_symbols()
        logger.info(f"  {len(symbols)} Symbole x {days_missing} Tag(e)")
        collector = OptionsCollector(
            api_key=get_api_key(),
            db_path=get_db_path(),
            requests_per_minute=6000,
            concurrent_workers=30,
        )
        stats = await collector.collect(symbols, days_back=days_missing)
        logger.info(f"  +{stats.options_collected:,} Optionen ({stats.api_calls} API-Calls)")
        if stats.errors:
            logger.warning(f"  {len(stats.errors)} Fehler")
        return True
    except Exception as e:
        logger.error(f"  Fehler: {e}")
        return False


# -- Step 3: Greeks --

def step_greeks(logger, dry_run=False):
    logger.info("--- STEP 3: Greeks (IV + Delta) ---")
    try:
        from scripts.calculate_greeks import (
            calculate_all_greeks, get_db_path,
            get_options_without_greeks, ensure_greeks_table
        )
        db_path = get_db_path()
        ensure_greeks_table(db_path)
        pending = get_options_without_greeks(db_path)
        logger.info(f"  Ausstehend: {len(pending):,}")
        if not pending:
            logger.info("  Nichts zu tun")
            return True
        if dry_run:
            logger.info("  [DRY RUN]")
            return True
        import multiprocessing
        workers = min(multiprocessing.cpu_count(), 8)
        logger.info(f"  Berechne mit {workers} Workers...")
        calculate_all_greeks(db_path=db_path, workers=workers, batch_size=10000)
        logger.info("  Fertig")
        return True
    except Exception as e:
        logger.error(f"  Fehler: {e}")
        return False


# -- Main --

async def run(args):
    logger = setup_logging(args.verbose)
    logger.info("=" * 50)
    logger.info(f"DB UPDATE  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 50)
    if not DB_PATH.exists():
        logger.error(f"DB nicht gefunden: {DB_PATH}")
        sys.exit(1)
    status = get_status()
    print_status(status, logger)
    if args.status:
        return
    steps = args.steps or ALL_STEPS
    logger.info(f"Schritte: {' > '.join(steps)}")
    if args.dry_run:
        logger.info("Modus: DRY RUN")
    print()
    results = {}
    t0 = time.time()
    if "vix" in steps:
        results["VIX"] = step_vix(logger, status, args.dry_run)
    if "options" in steps:
        results["Options"] = await step_options(logger, status, args.dry_run)
    if "greeks" in steps:
        results["Greeks"] = step_greeks(logger, args.dry_run)
    elapsed = time.time() - t0
    print()
    logger.info("=" * 50)
    for name, ok in results.items():
        logger.info(f"  {name:15s} {'OK' if ok else 'FEHLER'}")
    logger.info(f"  Dauer: {int(elapsed//60)}m {int(elapsed%60)}s")
    logger.info("=" * 50)
    if not all(results.values()):
        sys.exit(1)


def main():
    p = argparse.ArgumentParser(description='OptionPlay Daily DB Update')
    p.add_argument('--steps', nargs='+', choices=ALL_STEPS)
    p.add_argument('--dry-run', '-n', action='store_true')
    p.add_argument('--status', action='store_true')
    p.add_argument('--verbose', '-v', action='store_true')
    asyncio.run(run(p.parse_args()))


if __name__ == '__main__':
    main()
