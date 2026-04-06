#!/usr/bin/env python3
"""
OptionPlay - Daily Data Fetcher
================================

Automated daily data fetcher for end-of-day (EOD) data persistence.
Designed to run as a cronjob after market close.

Features:
- VIX closing prices from Yahoo Finance
- Gap detection and automatic backfill
- Weekly fundamentals update (Sundays)
- Comprehensive logging

Usage:
    # Normal run (fetch missing VIX data)
    python scripts/daily_data_fetcher.py

    # Backfill mode (fetch last N days)
    python scripts/daily_data_fetcher.py --backfill 30

    # Force fundamentals update (normally runs on Sundays)
    python scripts/daily_data_fetcher.py --update-fundamentals

    # Dry run (show what would be fetched)
    python scripts/daily_data_fetcher.py --dry-run

    # Verbose output
    python scripts/daily_data_fetcher.py -v

Cronjob Setup:
    # Run at 18:00 ET (23:00 UTC in winter, 22:00 in summer)
    0 23 * * 1-5 /path/to/daily_data_fetcher.py >> ~/.optionplay/logs/daily_fetcher.log 2>&1

Author: OptionPlay Team
Created: 2026-02-01
"""

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Database path
DB_PATH = Path.home() / ".optionplay" / "trades.db"
LOG_DIR = Path.home() / ".optionplay" / "logs"


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging with file and console handlers."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "daily_fetcher.log"

    level = logging.DEBUG if verbose else logging.INFO

    # Create logger
    logger = logging.getLogger("daily_fetcher")
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)

    return logger


def get_last_vix_date(conn: sqlite3.Connection) -> Optional[date]:
    """Get the most recent VIX date in the database."""
    cursor = conn.execute("SELECT MAX(date) FROM vix_data")
    row = cursor.fetchone()

    if row[0]:
        return date.fromisoformat(row[0])
    return None


def get_vix_gaps(conn: sqlite3.Connection, days_back: int = 30) -> List[date]:
    """
    Find missing trading days in VIX data.

    Returns list of dates that should have VIX data but don't.
    """
    # Get existing dates
    start = (date.today() - timedelta(days=days_back)).isoformat()
    cursor = conn.execute("SELECT date FROM vix_data WHERE date >= ? ORDER BY date", (start,))
    existing = {date.fromisoformat(row[0]) for row in cursor.fetchall()}

    # Generate expected trading days (Mon-Fri, excluding holidays)
    # Simple approach: just Mon-Fri
    gaps = []
    current = date.today() - timedelta(days=days_back)
    end = date.today()

    while current <= end:
        # Skip weekends
        if current.weekday() < 5:  # Mon=0, Fri=4
            if current not in existing and current < date.today():
                gaps.append(current)
        current += timedelta(days=1)

    return gaps


def fetch_vix_from_yahoo(
    start_date: date, end_date: date, logger: logging.Logger
) -> List[Tuple[date, float]]:
    """
    Fetch VIX closing prices from Yahoo Finance.

    Returns list of (date, value) tuples.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return []

    logger.info(f"Fetching VIX from Yahoo Finance: {start_date} to {end_date}")

    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(start=start_date, end=end_date + timedelta(days=1))  # end is exclusive

        if hist.empty:
            logger.warning("No VIX data received from Yahoo Finance")
            return []

        results = []
        for idx, row in hist.iterrows():
            bar_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
            vix_close = round(row["Close"], 2)
            results.append((bar_date, vix_close))

        logger.info(f"Received {len(results)} VIX data points")
        return results

    except Exception as e:
        logger.error(f"Error fetching VIX from Yahoo: {e}")
        return []


def store_vix_data(
    conn: sqlite3.Connection, data: List[Tuple[date, float]], logger: logging.Logger
) -> int:
    """
    Store VIX data in database.

    Returns number of new records inserted.
    """
    if not data:
        return 0

    now = datetime.now().isoformat()
    inserted = 0

    for vix_date, value in data:
        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO vix_data (date, value, created_at)
                VALUES (?, ?, ?)
                """,
                (vix_date.isoformat(), value, now),
            )
            if cursor.rowcount > 0:
                inserted += 1
                logger.debug(f"  Stored VIX {vix_date}: {value}")
            else:
                logger.debug(f"  VIX {vix_date} already exists, skipped")
        except sqlite3.Error as e:
            logger.error(f"Error storing VIX for {vix_date}: {e}")

    conn.commit()
    return inserted


def fetch_missing_vix(
    conn: sqlite3.Connection, logger: logging.Logger, dry_run: bool = False
) -> int:
    """
    Fetch and store missing VIX data since last stored date.

    Returns number of new records stored.
    """
    last_date = get_last_vix_date(conn)
    today = date.today()

    if not last_date:
        logger.warning("No existing VIX data found. Use --backfill to initialize.")
        return 0

    logger.info(f"Last VIX date in DB: {last_date}")

    # Check if we need to fetch
    if last_date >= today - timedelta(days=1):
        logger.info("VIX data is up to date")
        return 0

    # Fetch from day after last_date to yesterday
    start = last_date + timedelta(days=1)
    end = today - timedelta(days=1)  # Today's data may not be final

    if start > end:
        logger.info("No new trading days to fetch")
        return 0

    logger.info(f"Fetching VIX for {start} to {end}")

    if dry_run:
        logger.info("[DRY RUN] Would fetch VIX data")
        return 0

    data = fetch_vix_from_yahoo(start, end, logger)
    return store_vix_data(conn, data, logger)


def backfill_vix(
    conn: sqlite3.Connection, days: int, logger: logging.Logger, dry_run: bool = False
) -> int:
    """
    Backfill VIX data for the last N days.

    Returns number of records stored.
    """
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)

    logger.info(f"Backfilling VIX data: {start} to {end} ({days} days)")

    if dry_run:
        logger.info("[DRY RUN] Would backfill VIX data")
        return 0

    data = fetch_vix_from_yahoo(start, end, logger)
    return store_vix_data(conn, data, logger)


def update_fundamentals(logger: logging.Logger, dry_run: bool = False) -> int:
    """
    Update symbol fundamentals (normally runs weekly on Sundays).

    Returns number of symbols updated.
    """
    logger.info("Updating symbol fundamentals...")

    if dry_run:
        logger.info("[DRY RUN] Would update fundamentals")
        return 0

    try:
        from src.cache.symbol_fundamentals import get_fundamentals_manager
        from src.config.watchlist_loader import WatchlistLoader

        # Get symbols from watchlist
        loader = WatchlistLoader()
        symbols = loader.get_all_symbols()

        if not symbols:
            logger.warning("No symbols in watchlist")
            return 0

        logger.info(f"Updating fundamentals for {len(symbols)} symbols")

        manager = get_fundamentals_manager()
        results = manager.update_all_from_yfinance(symbols, delay_seconds=0.5)

        successful = sum(1 for v in results.values() if v)
        failed = [s for s, v in results.items() if not v]

        logger.info(f"Fundamentals updated: {successful}/{len(symbols)} successful")

        if failed and len(failed) <= 10:
            logger.warning(f"Failed symbols: {', '.join(failed)}")

        return successful

    except ImportError as e:
        logger.error(f"Import error updating fundamentals: {e}")
        return 0
    except Exception as e:
        logger.error(f"Error updating fundamentals: {e}")
        return 0


def fetch_future_earnings(logger: logging.Logger, dry_run: bool = False) -> int:
    """
    Fetch future earnings dates for all watchlist symbols and store in DB.

    Uses Yahoo Finance API to find next earnings dates (up to 90 days ahead).
    Results are stored in earnings_history for use by TradeValidator.

    Returns number of symbols with earnings data stored.
    """
    logger.info("Fetching future earnings dates...")

    if dry_run:
        logger.info("[DRY RUN] Would fetch future earnings")
        return 0

    try:
        from src.cache.earnings_history import get_earnings_history_manager
        from src.config.watchlist_loader import WatchlistLoader

        loader = WatchlistLoader()
        symbols = loader.get_all_symbols()

        if not symbols:
            logger.warning("No symbols in watchlist")
            return 0

        logger.info(f"Checking future earnings for {len(symbols)} symbols")

        manager = get_earnings_history_manager()
        stored = 0
        errors = 0

        for i, symbol in enumerate(symbols, 1):
            try:
                earnings_date = _fetch_yahoo_earnings_date(symbol)

                if earnings_date:
                    days_to = (earnings_date - date.today()).days

                    if days_to >= 0:  # Only future earnings
                        manager.save_earnings(
                            symbol,
                            [
                                {
                                    "earnings_date": earnings_date.isoformat(),
                                    "source": "yahoo_daily_fetch",
                                }
                            ],
                        )
                        stored += 1
                        logger.debug(
                            f"  [{i}/{len(symbols)}] {symbol}: "
                            f"Earnings {earnings_date} ({days_to}d)"
                        )
                    else:
                        logger.debug(
                            f"  [{i}/{len(symbols)}] {symbol}: "
                            f"Past earnings {earnings_date}, skipped"
                        )
                else:
                    logger.debug(f"  [{i}/{len(symbols)}] {symbol}: No earnings date found")

                # Rate limit: ~2 requests per second
                if i < len(symbols):
                    import time

                    time.sleep(0.5)

            except Exception as e:
                errors += 1
                logger.debug(f"  [{i}/{len(symbols)}] {symbol}: Error - {e}")

        logger.info(
            f"Future earnings: {stored} stored, " f"{errors} errors, {len(symbols)} checked"
        )
        return stored

    except ImportError as e:
        logger.error(f"Import error fetching earnings: {e}")
        return 0
    except Exception as e:
        logger.error(f"Error fetching future earnings: {e}")
        return 0


def _fetch_yahoo_earnings_date(symbol: str) -> Optional[date]:
    """
    Fetch next earnings date for a symbol from Yahoo Finance API.

    Returns earnings date or None if not found.
    """
    import json
    import urllib.request

    # Handle special ticker formats (BRK.B -> BRK-B for Yahoo)
    yahoo_symbol = symbol.replace(".", "-")

    url = (
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
        f"{yahoo_symbol}?modules=calendarEvents"
    )

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")

    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode())

    calendar = data.get("quoteSummary", {}).get("result", [{}])[0].get("calendarEvents", {})
    earnings_dates = calendar.get("earnings", {}).get("earningsDate", [])

    if earnings_dates:
        timestamp = earnings_dates[0].get("raw")
        if timestamp:
            return datetime.fromtimestamp(timestamp).date()

    return None


async def fetch_daily_prices(
    logger: logging.Logger, dry_run: bool = False, backfill_days: int = 5
) -> int:
    """
    Fetch OHLCV daily prices for all watchlist symbols from Tradier.

    Stores data in the daily_prices table for use by LocalDBProvider.

    Args:
        logger: Logger instance
        dry_run: If True, only show what would be done
        backfill_days: Number of days to fetch

    Returns:
        Number of symbols with data saved
    """
    tradier_key = os.environ.get("TRADIER_API_KEY")
    if not tradier_key:
        logger.warning("No TRADIER_API_KEY — skipping OHLCV fetch")
        return 0

    logger.info(f"Fetching OHLCV daily prices (last {backfill_days} days)...")

    if dry_run:
        logger.info("[DRY RUN] Would fetch OHLCV daily prices")
        return 0

    try:
        from src.data_providers.tradier import TradierProvider
        from src.data_providers.local_db import LocalDBProvider
        from src.config.watchlist_loader import WatchlistLoader

        local_db = LocalDBProvider()
        loader = WatchlistLoader()
        symbols = loader.get_all_symbols()

        # Always include sector ETFs + SPY for SectorRSService (O-1)
        SECTOR_ETFS = [
            "SPY", "XLK", "XLV", "XLF", "XLY", "XLP",
            "XLE", "XLI", "XLB", "XLRE", "XLU", "XLC",
        ]
        for etf in SECTOR_ETFS:
            if etf not in symbols:
                symbols.append(etf)

        if not symbols:
            logger.warning("No symbols in watchlist")
            return 0

        logger.info(f"Fetching OHLCV for {len(symbols)} symbols")
        saved_count = 0
        errors = 0

        tradier = TradierProvider(api_key=tradier_key, environment="production")
        try:
            connected = await tradier.connect()
            if not connected:
                logger.error("Failed to connect to Tradier API")
                return 0

            for i, symbol in enumerate(symbols, 1):
                try:
                    bars = await tradier.get_historical(symbol, days=backfill_days)
                    if bars:
                        count = await local_db.save_daily_prices(symbol, bars)
                        if count > 0:
                            saved_count += 1
                            logger.debug(f"  [{i}/{len(symbols)}] {symbol}: " f"{count} bars saved")
                    else:
                        logger.debug(f"  [{i}/{len(symbols)}] {symbol}: No data from Tradier")

                    # Rate limit: ~2 requests per second
                    if i < len(symbols):
                        await asyncio.sleep(0.5)

                except Exception as e:
                    errors += 1
                    logger.debug(f"  [{i}/{len(symbols)}] {symbol}: Error - {e}")

        finally:
            await tradier.disconnect()

        logger.info(
            f"OHLCV fetch: {saved_count} symbols saved, " f"{errors} errors, {len(symbols)} checked"
        )
        return saved_count

    except ImportError as e:
        logger.error(f"Import error fetching daily prices: {e}")
        return 0
    except Exception as e:
        logger.error(f"Error fetching daily prices: {e}")
        return 0


def print_status(conn: sqlite3.Connection, logger: logging.Logger):
    """Print current data status."""
    # VIX status
    cursor = conn.execute("""
        SELECT
            MIN(date) as first_date,
            MAX(date) as last_date,
            COUNT(*) as count
        FROM vix_data
    """)
    row = cursor.fetchone()

    logger.info("=" * 60)
    logger.info("DATA STATUS")
    logger.info("=" * 60)

    if row[0]:
        logger.info(f"VIX Data:")
        logger.info(f"  Range: {row[0]} to {row[1]}")
        logger.info(f"  Records: {row[2]:,}")

        # Check for gaps
        gaps = get_vix_gaps(conn, days_back=30)
        if gaps:
            logger.warning(f"  Gaps (last 30 days): {len(gaps)} days")
            if len(gaps) <= 5:
                logger.warning(f"    {', '.join(str(g) for g in gaps)}")
        else:
            logger.info("  Gaps (last 30 days): None")
    else:
        logger.warning("VIX Data: No data found")


def main():
    parser = argparse.ArgumentParser(
        description="Daily Data Fetcher for OptionPlay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                    # Fetch missing VIX data
    %(prog)s --backfill 30      # Backfill last 30 days
    %(prog)s --update-fundamentals  # Force fundamentals update
    %(prog)s --dry-run          # Show what would be done
        """,
    )

    parser.add_argument(
        "--backfill", "-b", type=int, metavar="DAYS", help="Backfill VIX data for the last N days"
    )
    parser.add_argument(
        "--update-fundamentals",
        "-f",
        action="store_true",
        help="Update symbol fundamentals (normally runs on Sundays)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "--status", "-s", action="store_true", help="Show current data status and exit"
    )
    parser.add_argument(
        "--vix-only",
        action="store_true",
        help="Only fetch VIX data (skip automatic Sunday fundamentals update)",
    )
    parser.add_argument(
        "--update-earnings",
        "-e",
        action="store_true",
        help="Fetch future earnings dates for all watchlist symbols",
    )
    parser.add_argument(
        "--update-prices",
        "-p",
        action="store_true",
        help="Fetch OHLCV daily prices for all watchlist symbols",
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.verbose)

    logger.info("=" * 60)
    logger.info("OPTIONPLAY - DAILY DATA FETCHER")
    logger.info(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Check database exists
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        logger.error("Please run the initial data collection scripts first.")
        sys.exit(1)

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        # Status only
        if args.status:
            print_status(conn, logger)
            return

        total_updates = 0

        # Backfill mode
        if args.backfill:
            count = backfill_vix(conn, args.backfill, logger, args.dry_run)
            total_updates += count
            logger.info(f"VIX backfill: {count} records stored")

        # Normal mode: fetch missing VIX
        else:
            count = fetch_missing_vix(conn, logger, args.dry_run)
            total_updates += count
            logger.info(f"VIX update: {count} new records")

        # Daily OHLCV update
        if args.update_prices or (not args.vix_only and not args.backfill):
            count = asyncio.run(fetch_daily_prices(logger, args.dry_run))
            total_updates += count

        # Future earnings update (daily or forced)
        if args.update_earnings:
            count = fetch_future_earnings(logger, args.dry_run)
            total_updates += count
        elif not args.vix_only and not args.backfill:
            # Run earnings update daily as part of normal flow
            count = fetch_future_earnings(logger, args.dry_run)
            total_updates += count

        # Fundamentals update (Sundays or forced, unless --vix-only)
        if args.update_fundamentals:
            count = update_fundamentals(logger, args.dry_run)
            total_updates += count
        elif datetime.today().weekday() == 6 and not args.vix_only:  # Sunday
            logger.info("Sunday - running weekly fundamentals update")
            count = update_fundamentals(logger, args.dry_run)
            total_updates += count

        # Print final status
        print_status(conn, logger)

        logger.info("")
        logger.info("=" * 60)
        if args.dry_run:
            logger.info("[DRY RUN] No changes made")
        else:
            logger.info(f"COMPLETED - {total_updates} total updates")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
