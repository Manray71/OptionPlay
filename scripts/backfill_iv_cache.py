#!/usr/bin/env python3
"""
Backfill IV Cache for all watchlist symbols.

Uses Historical Volatility (via yfinance) as IV proxy, adjusted by VIX.
Populates ~252 data points per symbol (1 year of trading days).

Usage:
    python scripts/backfill_iv_cache.py [--force] [--symbols AAPL,MSFT]
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cache.iv_cache_impl import IVCache, HistoricalIVFetcher, IVSource
from src.config.watchlist_loader import get_watchlist_loader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_all_watchlist_symbols() -> list[str]:
    """Load all unique symbols from the default watchlist."""
    try:
        loader = get_watchlist_loader()
        symbols = loader.get_all_symbols()
        if symbols:
            return sorted(set(s.upper() for s in symbols))
    except Exception as e:
        logger.warning(f"Could not load watchlist: {e}")

    # Fallback: load from YAML directly
    import yaml
    config_path = Path(__file__).resolve().parent.parent / "config" / "watchlists.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)

    symbols = set()
    wl = data.get("watchlists", {}).get("default_275", {})
    sectors = wl.get("sectors", {})
    for sector_data in sectors.values():
        if isinstance(sector_data, dict):
            for s in sector_data.get("symbols", []):
                symbols.add(s.upper())

    return sorted(symbols)


def main():
    parser = argparse.ArgumentParser(description="Backfill IV cache from historical data")
    parser.add_argument("--force", action="store_true", help="Force update even if cache is fresh")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols (default: full watchlist)")
    parser.add_argument("--days", type=int, default=252, help="Days of history (default: 252)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between API calls in seconds")
    args = parser.parse_args()

    cache = IVCache()
    fetcher = HistoricalIVFetcher(cache)

    # Determine symbols
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        symbols = get_all_watchlist_symbols()

    # Show current cache state
    stats = cache.stats()
    logger.info(f"Current cache: {stats['total_symbols']} symbols, {stats['with_sufficient_data']} with ≥20 points")

    # Filter to only symbols needing update (unless --force)
    if not args.force:
        need_update = [s for s in symbols if s not in cache or cache.get_history(s) == [] or len(cache.get_history(s)) < 50]
        logger.info(f"Symbols needing update: {len(need_update)} of {len(symbols)}")
        symbols = need_update

    if not symbols:
        logger.info("All symbols already have sufficient IV data. Use --force to re-fetch.")
        return

    logger.info(f"Backfilling IV cache for {len(symbols)} symbols ({args.days} days each)...")
    logger.info(f"Estimated time: ~{len(symbols) * (args.delay + 1.5):.0f}s")
    print()

    success = 0
    failed = []
    start = time.time()

    for i, symbol in enumerate(symbols):
        try:
            logger.info(f"[{i+1}/{len(symbols)}] {symbol}...")
            iv_history = fetcher.fetch_iv_history(symbol, days=args.days)

            if iv_history and len(iv_history) >= 20:
                cache.update_history(symbol, iv_history, IVSource.YAHOO)
                logger.info(f"  → {len(iv_history)} data points saved")
                success += 1
            else:
                logger.warning(f"  → Only {len(iv_history) if iv_history else 0} points, skipping")
                failed.append(symbol)

        except Exception as e:
            logger.error(f"  → Failed: {e}")
            failed.append(symbol)

        # Rate limiting
        if i < len(symbols) - 1:
            time.sleep(args.delay)

    elapsed = time.time() - start

    # Final summary
    print()
    logger.info("=" * 60)
    logger.info(f"Backfill complete in {elapsed:.0f}s")
    logger.info(f"Success: {success}/{len(symbols)}")
    if failed:
        logger.info(f"Failed: {', '.join(failed)}")

    stats = cache.stats()
    logger.info(f"Cache now: {stats['total_symbols']} symbols, {stats['with_sufficient_data']} with ≥20 points")


if __name__ == "__main__":
    main()
