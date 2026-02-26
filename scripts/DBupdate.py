#!/usr/bin/env python3
"""
OptionPlay - Daily DB Update (All-in-One)
==========================================

Prüft den letzten Datenstand und füllt nur die Lücke seit dem
letzten vorhandenen Datum bis gestern auf. Historische Lücken
werden NICHT angefasst.

Schritte:
  1. VIX via Yahoo Finance
  2. Options-Chain + Greeks via Tradier (ORATS)
  3. OHLCV daily prices via Tradier
  4. IV Cache backfill via yfinance (HV→IV estimation)

Usage:
    python scripts/DBupdate.py              # Komplettes Update
    python scripts/DBupdate.py --status     # Nur Status zeigen
    python scripts/DBupdate.py --dry-run    # Zeigt was passieren würde
    python scripts/DBupdate.py --steps vix  # Nur VIX
    python scripts/DBupdate.py --steps options ohlcv  # Options + OHLCV
    python scripts/DBupdate.py --steps iv             # Nur IV Cache
    python scripts/DBupdate.py -v           # Verbose
"""

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path.home() / ".optionplay" / "trades.db"
LOG_DIR = Path.home() / ".optionplay" / "logs"
ALL_STEPS = ["vix", "options", "ohlcv", "iv", "liquidity"]


def setup_logging(verbose=False):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("dbupdate")
    logger.setLevel(level)
    logger.handlers.clear()
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(ch)
    fh = logging.FileHandler(LOG_DIR / "dbupdate.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(fh)
    return logger


def get_status():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT MAX(date) FROM vix_data")
    vix_max = cur.fetchone()[0]
    cur = conn.execute(
        "SELECT MAX(quote_date), COUNT(*), COUNT(DISTINCT underlying) FROM options_prices"
    )
    r = cur.fetchone()
    opt_max, opt_count, opt_symbols = r
    cur = conn.execute(
        "SELECT COUNT(*) FROM options_prices p "
        "LEFT JOIN options_greeks g ON p.id = g.options_price_id "
        "WHERE g.id IS NULL"
    )
    greeks_pending = cur.fetchone()[0]
    cur = conn.execute("SELECT MAX(quote_date), COUNT(*), COUNT(DISTINCT symbol) FROM daily_prices")
    r = cur.fetchone()
    ohlcv_max, ohlcv_count, ohlcv_symbols = r
    conn.close()
    return {
        "vix_max": vix_max,
        "opt_max": opt_max,
        "opt_count": opt_count,
        "opt_symbols": opt_symbols,
        "greeks_pending": greeks_pending,
        "ohlcv_max": ohlcv_max,
        "ohlcv_count": ohlcv_count,
        "ohlcv_symbols": ohlcv_symbols,
    }


def print_status(s, logger):
    today = date.today()
    logger.info("DB STATUS:")
    if s["vix_max"]:
        d = (today - date.fromisoformat(s["vix_max"])).days
        logger.info(f"  VIX:     bis {s['vix_max']}  {'[aktuell]' if d <= 1 else f'[{d}d alt]'}")
    if s["opt_max"]:
        d = (today - date.fromisoformat(s["opt_max"])).days
        logger.info(
            f"  Options: bis {s['opt_max']}  {'[aktuell]' if d <= 1 else f'[{d}d alt]'}  ({s['opt_count']:,} Preise, {s['opt_symbols']} Symbole)"
        )
    logger.info(f"  Greeks:  {s['greeks_pending']:,} ausstehend")
    if s["ohlcv_max"]:
        d = (today - date.fromisoformat(s["ohlcv_max"])).days
        logger.info(
            f"  OHLCV:   bis {s['ohlcv_max']}  {'[aktuell]' if d <= 1 else f'[{d}d alt]'}  ({s['ohlcv_count']:,} Bars, {s['ohlcv_symbols']} Symbole)"
        )


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
            d = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
            cur = conn.execute(
                "INSERT OR IGNORE INTO vix_data (date, value, created_at) VALUES (?,?,?)",
                (d.isoformat(), round(row["Close"], 2), now),
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


# -- Step 2: Options + Greeks via Tradier --


async def step_options(logger, status, dry_run=False):
    logger.info("--- STEP 2: Options + Greeks (Tradier/ORATS) ---")
    last = status["opt_max"]
    if not last:
        logger.error("  Keine Options-Daten - manuell initialisieren")
        return False

    last_date = date.fromisoformat(last)
    today = date.today()

    # Wenn letzter Stand heute oder gestern (Wochenende/Feiertag beachten)
    days_since = (today - last_date).days
    if days_since <= 1 and today.weekday() < 5:
        logger.info(f"  Aktuell bis {last_date} - nichts zu tun")
        return True
    if days_since <= 3 and last_date.weekday() == 4 and today.weekday() == 0:
        # Freitag → Montag (Wochenende)
        logger.info(f"  Aktuell bis {last_date} (Wochenende) - hole heutige Daten")

    logger.info(f"  Letzter Stand: {last_date} ({days_since}d)")

    # Tradier liefert nur aktuelle Chains (kein historisches Backfill)
    # Daher sammeln wir die heutige Chain
    if today.weekday() >= 5:
        logger.info("  Wochenende - keine aktuellen Chains verfügbar")
        return True

    if dry_run:
        logger.info("  [DRY RUN] Würde heutige Options-Chain sammeln")
        return True

    api_key = os.environ.get("TRADIER_API_KEY")
    if not api_key:
        logger.error("  TRADIER_API_KEY nicht gesetzt!")
        return False

    try:
        from src.data_providers.tradier import TradierProvider
        from src.data_providers.interface import OptionQuote
        from src.config.watchlist_loader import get_watchlist_loader

        symbols = get_watchlist_loader().get_all_symbols()
        logger.info(f"  {len(symbols)} Symbole")

        provider = TradierProvider(api_key=api_key)
        try:
            connected = await provider.connect()
            if not connected:
                logger.error("  Tradier-Verbindung fehlgeschlagen")
                return False

            logger.info("  Tradier verbunden - sammle Options-Chains...")

            # Reuse store logic from collect_options_tradier
            from scripts.collect_options_tradier import store_options_with_greeks, ensure_schema

            db_path = str(DB_PATH)
            ensure_schema(db_path)

            quote_date = today
            total_prices = 0
            total_greeks = 0
            errors = 0
            semaphore = asyncio.Semaphore(3)  # Max 3 concurrent

            async def collect_one(symbol):
                nonlocal total_prices, total_greeks, errors
                async with semaphore:
                    try:
                        chain = await provider.get_option_chain(
                            symbol, dte_min=7, dte_max=130, right="PC"
                        )
                        if chain:
                            prices, greeks = store_options_with_greeks(db_path, chain, quote_date)
                            total_prices += prices
                            total_greeks += greeks
                    except Exception as e:
                        errors += 1
                        logger.debug(f"  {symbol}: {e}")

            # Process in batches of 15
            batch_size = 15
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i : i + batch_size]
                await asyncio.gather(*(collect_one(s) for s in batch))
                pct = min(100, (i + len(batch)) / len(symbols) * 100)
                logger.info(f"  [{pct:5.1f}%] {total_prices:,} Preise, " f"{total_greeks:,} Greeks")

            logger.info(f"  +{total_prices:,} Options-Preise, " f"+{total_greeks:,} Greeks")
            if errors:
                logger.warning(f"  {errors} Fehler")

            return True

        finally:
            await provider.disconnect()

    except Exception as e:
        logger.error(f"  Fehler: {e}")
        return False


# -- Step 3: OHLCV Daily Prices via Tradier --


async def step_ohlcv(logger, status, dry_run=False):
    logger.info("--- STEP 3: OHLCV Daily Prices (Tradier) ---")
    last = status.get("ohlcv_max")

    api_key = os.environ.get("TRADIER_API_KEY")
    if not api_key:
        logger.error("  TRADIER_API_KEY nicht gesetzt!")
        return False

    today = date.today()
    if last:
        last_date = date.fromisoformat(last)
        days_since = (today - last_date).days
        if days_since <= 1 and today.weekday() < 5:
            logger.info(f"  Aktuell bis {last_date} - nichts zu tun")
            return True
        backfill_days = min(days_since + 2, 10)  # Extra Puffer
        logger.info(f"  Letzter Stand: {last_date} ({days_since}d) - hole {backfill_days} Tage")
    else:
        backfill_days = 10
        logger.info("  Keine OHLCV-Daten - hole letzte 10 Tage")

    if dry_run:
        logger.info("  [DRY RUN]")
        return True

    try:
        from src.data_providers.tradier import TradierProvider
        from src.data_providers.local_db import LocalDBProvider
        from src.config.watchlist_loader import get_watchlist_loader

        symbols = get_watchlist_loader().get_all_symbols()
        logger.info(f"  {len(symbols)} Symbole x {backfill_days} Tage")

        local_db = LocalDBProvider()
        provider = TradierProvider(api_key=api_key)

        try:
            connected = await provider.connect()
            if not connected:
                logger.error("  Tradier-Verbindung fehlgeschlagen")
                return False

            saved_count = 0
            errors = 0

            for i, symbol in enumerate(symbols, 1):
                try:
                    bars = await provider.get_historical(symbol, days=backfill_days)
                    if bars:
                        count = await local_db.save_daily_prices(symbol, bars)
                        if count > 0:
                            saved_count += 1
                    if i % 50 == 0:
                        pct = i / len(symbols) * 100
                        logger.info(f"  [{pct:5.1f}%] {saved_count} Symbole gespeichert")
                    # Rate limit
                    await asyncio.sleep(0.3)
                except Exception as e:
                    errors += 1
                    logger.debug(f"  {symbol}: {e}")

            logger.info(f"  +{saved_count} Symbole mit neuen OHLCV-Daten")
            if errors:
                logger.warning(f"  {errors} Fehler")
            return True

        finally:
            await provider.disconnect()

    except Exception as e:
        logger.error(f"  Fehler: {e}")
        return False


# -- Step 4: IV Cache Backfill --


def step_iv(logger, dry_run=False):
    logger.info("--- STEP 4: IV Cache Backfill (yfinance HV→IV) ---")
    try:
        from src.cache.iv_cache_impl import IVCache, HistoricalIVFetcher, IVSource
        from src.config.watchlist_loader import get_watchlist_loader

        cache = IVCache()
        stats = cache.stats()
        logger.info(
            f"  Cache: {stats['total_symbols']} Symbole, {stats['with_sufficient_data']} mit ≥20 Punkten"
        )

        symbols = get_watchlist_loader().get_all_symbols()

        # Only update symbols with thin data (< 50 points) or stale cache
        need_update = [
            s
            for s in symbols
            if s not in cache or cache.get_history(s) == [] or len(cache.get_history(s)) < 50
        ]
        logger.info(f"  {len(need_update)} von {len(symbols)} brauchen Update")

        if not need_update:
            logger.info("  Alle Symbole haben ausreichend IV-Daten")
            return True

        if dry_run:
            logger.info(f"  [DRY RUN] Würde {len(need_update)} Symbole aktualisieren")
            return True

        fetcher = HistoricalIVFetcher(cache)
        success = 0
        errors = 0

        for i, symbol in enumerate(need_update, 1):
            try:
                iv_history = fetcher.fetch_iv_history(symbol, days=252)
                if iv_history and len(iv_history) >= 20:
                    cache.update_history(symbol, iv_history, IVSource.YAHOO)
                    success += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

            if i % 50 == 0:
                pct = i / len(need_update) * 100
                logger.info(f"  [{pct:5.1f}%] {success} OK, {errors} Fehler")

            time.sleep(0.3)

        logger.info(f"  +{success} Symbole mit IV-History, {errors} Fehler")
        stats = cache.stats()
        logger.info(
            f"  Cache jetzt: {stats['total_symbols']} Symbole, {stats['with_sufficient_data']} mit ≥20 Punkten"
        )
        return True

    except Exception as e:
        logger.error(f"  Fehler: {e}")
        return False


# -- Step 5: Liquidity Tier Classification --


def step_liquidity(logger, dry_run=False):
    logger.info("--- STEP 5: Liquidity Tier Classification ---")
    try:
        from scripts.classify_liquidity import classify_symbols

        if dry_run:
            tiers = classify_symbols(dry_run=True)
        else:
            tiers = classify_symbols()

        for tier_num in (1, 2, 3):
            count = len(tiers[tier_num])
            logger.info(f"  Tier {tier_num}: {count} Symbole")
        total = sum(len(v) for v in tiers.values())
        logger.info(f"  Gesamt: {total} Symbole klassifiziert")
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
        results["Options+Greeks"] = await step_options(logger, status, args.dry_run)
    if "ohlcv" in steps:
        results["OHLCV"] = await step_ohlcv(logger, status, args.dry_run)
    if "iv" in steps:
        results["IV Cache"] = step_iv(logger, args.dry_run)
    if "liquidity" in steps:
        results["Liquidity Tiers"] = step_liquidity(logger, args.dry_run)
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
    p = argparse.ArgumentParser(description="OptionPlay Daily DB Update")
    p.add_argument("--steps", nargs="+", choices=ALL_STEPS)
    p.add_argument("--dry-run", "-n", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
