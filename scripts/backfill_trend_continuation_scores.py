#!/usr/bin/env python3
"""
Backfill trend_continuation_score + 5 component scores for existing trades.

Uses the TrendContinuationAnalyzer to calculate scores for all trades.
Since trades.db only has closing prices (underlying_price), we approximate
highs/lows with a small offset from closes.

Writes to outcomes.db:
  - trend_continuation_score (strategy total)
  - tc_sma_alignment_score
  - tc_stability_score
  - tc_buffer_score
  - tc_momentum_score
  - tc_volatility_score

Usage:
    python scripts/backfill_trend_continuation_scores.py
    python scripts/backfill_trend_continuation_scores.py --limit 100
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv()

from src.analyzers.trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TRADES_DB = Path.home() / ".optionplay" / "trades.db"
OUTCOMES_DB = Path.home() / ".optionplay" / "outcomes.db"
MIN_BARS = 220  # SMA 200 + slope days


def main():
    parser = argparse.ArgumentParser(description="Backfill trend_continuation scores + components")
    parser.add_argument("--limit", type=int, help="Limit trades to process")
    args = parser.parse_args()

    analyzer = TrendContinuationAnalyzer(TrendContinuationConfig())

    # Load all trades
    conn = sqlite3.connect(str(OUTCOMES_DB))
    cursor = conn.cursor()
    query = (
        "SELECT id, symbol, entry_date, entry_price FROM trade_outcomes ORDER BY symbol, entry_date"
    )
    if args.limit:
        query += f" LIMIT {args.limit}"
    cursor.execute(query)
    trades = cursor.fetchall()
    conn.close()
    logger.info(f"Total trades: {len(trades)}")

    # Group by symbol
    symbol_trades: Dict[str, List[Tuple[int, str, float]]] = {}
    for trade_id, symbol, entry_date, entry_price in trades:
        symbol_trades.setdefault(symbol, []).append((trade_id, entry_date, entry_price))
    logger.info(f"Unique symbols: {len(symbol_trades)}")

    # Load VIX data
    tconn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
    tcursor = tconn.cursor()
    tcursor.execute("SELECT date, value FROM vix_data ORDER BY date")
    vix_list = tcursor.fetchall()
    tconn.close()
    vix_dates = [r[0] for r in vix_list]
    vix_values = [r[1] for r in vix_list]
    logger.info(f"VIX data: {len(vix_list)} points")

    def get_vix(entry_date: str) -> Optional[float]:
        lo, hi = 0, len(vix_dates) - 1
        result = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if vix_dates[mid] <= entry_date:
                result = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return vix_values[result] if result is not None else None

    updates = []
    processed = 0
    scored = 0
    skipped_data = 0
    errors = 0

    for sym_idx, (symbol, sym_trades_list) in enumerate(sorted(symbol_trades.items())):
        if sym_idx % 50 == 0:
            logger.info(
                f"  [{sym_idx}/{len(symbol_trades)}] {symbol} ({len(sym_trades_list)} trades)"
            )

        # Load ALL price history for this symbol
        tconn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
        tcursor = tconn.cursor()
        tcursor.execute(
            """
            SELECT quote_date, underlying_price
            FROM (
                SELECT DISTINCT quote_date, underlying_price
                FROM options_prices
                WHERE underlying = ?
                ORDER BY quote_date
            )
        """,
            (symbol,),
        )
        price_rows = tcursor.fetchall()
        tconn.close()

        if len(price_rows) < MIN_BARS:
            skipped_data += len(sym_trades_list)
            processed += len(sym_trades_list)
            continue

        price_dates = [r[0] for r in price_rows]
        price_values = [r[1] for r in price_rows]
        date_to_idx = {d: i for i, d in enumerate(price_dates)}

        for trade_id, entry_date, entry_price in sym_trades_list:
            processed += 1

            try:
                idx = date_to_idx.get(entry_date)
                if idx is None:
                    candidates = [i for i, d in enumerate(price_dates) if d <= entry_date]
                    if not candidates:
                        continue
                    idx = candidates[-1]

                if idx < MIN_BARS - 1:
                    skipped_data += 1
                    continue

                closes = price_values[: idx + 1]
                highs = [p * 1.005 for p in closes]
                lows = [p * 0.995 for p in closes]
                volumes = [1_000_000] * len(closes)

                vix = get_vix(entry_date)

                signal = analyzer.analyze(
                    symbol=symbol,
                    prices=closes,
                    volumes=volumes,
                    highs=highs,
                    lows=lows,
                    vix=vix,
                )

                tc_score = signal.score if signal.score is not None else 0.0

                # Extract component scores from signal.details
                components = {}
                if hasattr(signal, "details") and signal.details:
                    comp_dict = signal.details.get("components", {})
                    components = {
                        "tc_sma_alignment_score": comp_dict.get("sma_alignment", 0.0),
                        "tc_stability_score": comp_dict.get("trend_stability", 0.0),
                        "tc_buffer_score": comp_dict.get("trend_buffer", 0.0),
                        "tc_momentum_score": comp_dict.get("momentum_health", 0.0),
                        "tc_volatility_score": comp_dict.get("volatility", 0.0),
                    }

                updates.append(
                    (
                        tc_score,
                        components.get("tc_sma_alignment_score", 0.0),
                        components.get("tc_stability_score", 0.0),
                        components.get("tc_buffer_score", 0.0),
                        components.get("tc_momentum_score", 0.0),
                        components.get("tc_volatility_score", 0.0),
                        trade_id,
                    )
                )
                scored += 1

            except Exception as e:
                errors += 1
                if errors <= 10:
                    logger.warning(f"  Error {symbol} {entry_date}: {e}")

    logger.info(f"\n{'='*60}")
    logger.info(f"Processed: {processed}")
    logger.info(f"Scored:    {scored}")
    logger.info(f"Skipped (insufficient data): {skipped_data}")
    logger.info(f"Errors:    {errors}")
    logger.info(f"Scores > 0:   {sum(1 for u in updates if u[0] > 0)}")
    logger.info(f"Scores >= 5.0: {sum(1 for u in updates if u[0] >= 5.0)}")

    # Score distribution
    if updates:
        scores = [u[0] for u in updates]
        non_zero = [s for s in scores if s > 0]
        logger.info(f"\nScore distribution (non-zero):")
        if non_zero:
            import statistics

            logger.info(f"  Count:  {len(non_zero)}")
            logger.info(f"  Mean:   {statistics.mean(non_zero):.2f}")
            logger.info(f"  Median: {statistics.median(non_zero):.2f}")
            logger.info(f"  Min:    {min(non_zero):.2f}")
            logger.info(f"  Max:    {max(non_zero):.2f}")

    # Write to DB
    if updates:
        conn = sqlite3.connect(str(OUTCOMES_DB))
        cursor = conn.cursor()
        cursor.executemany(
            """UPDATE trade_outcomes SET
                trend_continuation_score = ?,
                tc_sma_alignment_score = ?,
                tc_stability_score = ?,
                tc_buffer_score = ?,
                tc_momentum_score = ?,
                tc_volatility_score = ?
            WHERE id = ?""",
            updates,
        )
        conn.commit()
        conn.close()
        logger.info(f"\nUpdated {len(updates)} trades in outcomes.db (score + 5 components)")
    else:
        logger.warning("No updates to write!")


if __name__ == "__main__":
    main()
