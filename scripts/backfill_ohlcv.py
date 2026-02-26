#!/usr/bin/env python3
"""
OptionPlay - OHLCV Backfill Script
====================================

Fetches full historical OHLCV data from Tradier for all symbols in the local DB
and writes them to the daily_prices table.

Features:
- Backfills 2021-01-04 to today for all 356 symbols
- Respects Tradier rate limits (120 req/min) with configurable batching
- Skips dates that already have real OHLCV data (volume > 0)
- Continues on per-symbol errors, shows summary at end
- Resumable: re-running only fetches missing data

Usage:
    # Full backfill (all symbols, 2021-01-04 to today)
    python3 scripts/backfill_ohlcv.py

    # Specific symbols only
    python3 scripts/backfill_ohlcv.py --symbols AAPL MSFT GOOG

    # Custom date range
    python3 scripts/backfill_ohlcv.py --start 2023-01-01

    # Dry run (show what would be done)
    python3 scripts/backfill_ohlcv.py --dry-run

    # Adjust batch size and delay
    python3 scripts/backfill_ohlcv.py --batch-size 20 --delay 1.5

Requirements:
    TRADIER_API_KEY environment variable must be set.
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

# Database path
DB_PATH = Path.home() / ".optionplay" / "trades.db"
LOG_DIR = Path.home() / ".optionplay" / "logs"

# Tradier API
TRADIER_BASE_URL = "https://api.tradier.com"
BACKFILL_START = date(2021, 1, 4)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging with file and console handlers."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "backfill_ohlcv.log"

    level = logging.DEBUG if verbose else logging.INFO

    logger = logging.getLogger("backfill_ohlcv")
    logger.setLevel(level)
    logger.handlers.clear()

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(console)

    # File handler (always debug)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)

    return logger


def get_all_symbols(conn: sqlite3.Connection) -> List[str]:
    """Get all distinct symbols from options_prices table."""
    cursor = conn.execute("""
        SELECT DISTINCT underlying
        FROM options_prices
        ORDER BY underlying
    """)
    return [row[0] for row in cursor.fetchall()]


def get_existing_ohlcv_dates(conn: sqlite3.Connection, symbol: str) -> set:
    """Get dates that already have real OHLCV data (volume > 0) for a symbol."""
    cursor = conn.execute(
        """
        SELECT quote_date FROM daily_prices
        WHERE symbol = ? AND volume > 0
    """,
        (symbol,),
    )
    return {row[0] for row in cursor.fetchall()}


def fetch_tradier_history(
    api_key: str,
    symbol: str,
    start_date: date,
    end_date: date,
    logger: logging.Logger,
    max_retries: int = 3,
) -> List[Dict]:
    """
    Fetch historical OHLCV bars from Tradier API (synchronous).

    Returns list of dicts with keys: date, open, high, low, close, volume.
    """
    url = (
        f"{TRADIER_BASE_URL}/v1/markets/history"
        f"?symbol={symbol.upper()}"
        f"&interval=daily"
        f"&start={start_date.isoformat()}"
        f"&end={end_date.isoformat()}"
    )

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {api_key}")
            req.add_header("Accept", "application/json")

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

            if not data or "history" not in data:
                return []

            history = data["history"]
            if not history or "day" not in history:
                return []

            days_data = history["day"]
            if isinstance(days_data, dict):
                days_data = [days_data]

            return days_data

        except urllib.error.HTTPError as e:
            if e.code == 401:
                logger.error(f"Tradier: Unauthorized (401) — check TRADIER_API_KEY")
                return []
            elif e.code == 429:
                wait = 2.0 * (attempt + 1)
                logger.warning(f"  Rate limited for {symbol}, waiting {wait}s...")
                time.sleep(wait)
                continue
            else:
                logger.warning(f"  HTTP {e.code} for {symbol}: {e.reason}")
        except urllib.error.URLError as e:
            logger.warning(f"  Network error for {symbol} (attempt {attempt + 1}): {e}")
        except Exception as e:
            logger.warning(f"  Unexpected error for {symbol} (attempt {attempt + 1}): {e}")

        if attempt < max_retries - 1:
            time.sleep(1.0 * (attempt + 1))

    return []


def store_bars(
    conn: sqlite3.Connection,
    symbol: str,
    bars: List[Dict],
    existing_dates: set,
    logger: logging.Logger,
) -> Tuple[int, int]:
    """
    Store OHLCV bars in daily_prices table.

    Skips dates that already have real data (in existing_dates set).

    Returns (inserted_count, skipped_count).
    """
    inserted = 0
    skipped = 0

    cursor = conn.cursor()

    for bar in bars:
        try:
            bar_date = bar["date"]  # Already YYYY-MM-DD string from Tradier

            # Skip if we already have real OHLCV for this date
            if bar_date in existing_dates:
                skipped += 1
                continue

            cursor.execute(
                """
                INSERT OR REPLACE INTO daily_prices
                    (symbol, quote_date, open, high, low, close, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    symbol.upper(),
                    bar_date,
                    float(bar["open"]),
                    float(bar["high"]),
                    float(bar["low"]),
                    float(bar["close"]),
                    int(bar.get("volume", 0)),
                    "tradier_backfill",
                ),
            )
            inserted += 1

        except (KeyError, ValueError, sqlite3.Error) as e:
            logger.debug(f"  Error storing bar for {symbol} {bar.get('date', '?')}: {e}")

    conn.commit()
    return inserted, skipped


def ensure_daily_prices_table(conn: sqlite3.Connection):
    """Create daily_prices table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            symbol TEXT NOT NULL,
            quote_date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL DEFAULT 0,
            source TEXT DEFAULT 'tradier',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, quote_date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol
        ON daily_prices(symbol)
    """)
    conn.commit()


def print_summary(
    logger: logging.Logger,
    results: Dict[str, Tuple[int, int, str]],
    elapsed: float,
):
    """Print final summary of backfill results."""
    total_symbols = len(results)
    successful = sum(1 for _, _, status in results.values() if status == "ok")
    failed = {s: info for s, info in results.items() if info[2] == "error"}
    no_data = sum(1 for _, _, status in results.values() if status == "no_data")
    skipped = sum(1 for _, _, status in results.values() if status == "up_to_date")
    total_inserted = sum(ins for ins, _, _ in results.values())
    total_skipped = sum(sk for _, sk, _ in results.values())

    logger.info("")
    logger.info("=" * 65)
    logger.info("BACKFILL SUMMARY")
    logger.info("=" * 65)
    logger.info(f"  Symbols processed:  {total_symbols}")
    logger.info(f"  Successful:         {successful}")
    logger.info(f"  Already up-to-date: {skipped}")
    logger.info(f"  No data from API:   {no_data}")
    logger.info(f"  Errors:             {len(failed)}")
    logger.info(f"  Bars inserted:      {total_inserted:,}")
    logger.info(f"  Bars skipped (existing): {total_skipped:,}")
    logger.info(f"  Duration:           {elapsed:.1f}s ({elapsed/60:.1f}min)")

    if failed:
        logger.info("")
        logger.info("Failed symbols:")
        for sym, (ins, sk, status) in sorted(failed.items()):
            logger.info(f"  {sym}")

    logger.info("=" * 65)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill OHLCV data from Tradier into daily_prices table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                          # Full backfill, all symbols
    %(prog)s --symbols AAPL MSFT      # Specific symbols only
    %(prog)s --start 2023-01-01       # Custom start date
    %(prog)s --dry-run                # Preview without writing
    %(prog)s --batch-size 10 --delay 2  # Slower, safer batching
        """,
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        metavar="SYM",
        help="Only backfill these symbols (default: all in DB)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2021-01-04",
        help="Start date YYYY-MM-DD (default: 2021-01-04)",
    )
    parser.add_argument(
        "--end", type=str, default=None, help="End date YYYY-MM-DD (default: yesterday)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=10, help="Symbols per batch before pausing (default: 10)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.6, help="Delay in seconds between API calls (default: 0.6)"
    )
    parser.add_argument(
        "--batch-pause",
        type=float,
        default=5.0,
        help="Pause in seconds between batches (default: 5.0)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing OHLCV data (default: skip existing)",
    )

    args = parser.parse_args()

    logger = setup_logging(args.verbose)

    # Validate API key
    api_key = os.environ.get("TRADIER_API_KEY")
    if not api_key:
        logger.error("TRADIER_API_KEY environment variable not set.")
        logger.error("Export it first: export TRADIER_API_KEY=your_key_here")
        sys.exit(1)

    # Parse dates
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)

    if start_date >= end_date:
        logger.error(f"Start date {start_date} must be before end date {end_date}")
        sys.exit(1)

    logger.info("=" * 65)
    logger.info("OPTIONPLAY - OHLCV BACKFILL")
    logger.info(f"  Date range: {start_date} to {end_date}")
    logger.info(
        f"  Batch size: {args.batch_size} symbols, "
        f"{args.delay}s between calls, "
        f"{args.batch_pause}s between batches"
    )
    if args.dry_run:
        logger.info("  MODE: DRY RUN (no changes)")
    if args.force:
        logger.info("  MODE: FORCE (overwriting existing data)")
    logger.info("=" * 65)

    # Check database
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        # Ensure table exists
        ensure_daily_prices_table(conn)

        # Get symbols
        if args.symbols:
            symbols = [s.upper() for s in args.symbols]
            logger.info(f"Symbols: {len(symbols)} (user-specified)")
        else:
            symbols = get_all_symbols(conn)
            logger.info(f"Symbols: {len(symbols)} (from options_prices)")

        if not symbols:
            logger.warning("No symbols to process")
            return

        # Process symbols
        results: Dict[str, Tuple[int, int, str]] = {}
        t_start = time.time()

        for i, symbol in enumerate(symbols, 1):
            # Batch pause
            if i > 1 and (i - 1) % args.batch_size == 0:
                logger.info(f"  --- Batch pause ({args.batch_pause}s) ---")
                if not args.dry_run:
                    time.sleep(args.batch_pause)

            # Check existing data
            if args.force:
                existing_dates = set()
            else:
                existing_dates = get_existing_ohlcv_dates(conn, symbol)

            if args.dry_run:
                logger.info(
                    f"  [{i}/{len(symbols)}] {symbol}: "
                    f"Would fetch {start_date} to {end_date}, "
                    f"{len(existing_dates)} dates already cached"
                )
                results[symbol] = (0, len(existing_dates), "ok")
                continue

            # Fetch from Tradier
            bars = fetch_tradier_history(api_key, symbol, start_date, end_date, logger)

            if not bars:
                logger.info(f"  [{i}/{len(symbols)}] {symbol}: " f"No data from Tradier")
                results[symbol] = (0, 0, "no_data")
            else:
                # Check if all dates already exist
                bar_dates = {b["date"] for b in bars}
                new_dates = bar_dates - existing_dates

                if not new_dates and not args.force:
                    logger.info(
                        f"  [{i}/{len(symbols)}] {symbol}: "
                        f"Up to date ({len(bars)} bars, all cached)"
                    )
                    results[symbol] = (0, len(bars), "up_to_date")
                else:
                    # Store new bars
                    inserted, skipped = store_bars(conn, symbol, bars, existing_dates, logger)
                    logger.info(
                        f"  [{i}/{len(symbols)}] {symbol}: "
                        f"{inserted} bars inserted, {skipped} skipped "
                        f"(of {len(bars)} total)"
                    )
                    results[symbol] = (inserted, skipped, "ok")

            # Rate limit delay between symbols
            if i < len(symbols) and not args.dry_run:
                time.sleep(args.delay)

        elapsed = time.time() - t_start
        print_summary(logger, results, elapsed)

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user. Progress has been saved.")
        logger.info("Re-run to continue from where you left off.")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
