#!/usr/bin/env python3
"""
OptionPlay - Stability Threshold Optimizer
==========================================

Uses Walk-Forward trade data to find optimal stability_score cutoffs
per strategy × VIX regime.

Runs only at the trained optimal score thresholds (35 jobs instead of 280).
Cross-references each trade's symbol with stability_score from symbol_fundamentals.

Output: Updates stability_thresholds section in config/scoring_weights.yaml

Usage:
    python scripts/train_stability_thresholds.py
    python scripts/train_stability_thresholds.py --workers 4
    python scripts/train_stability_thresholds.py --dry-run
"""

import json
import logging
import multiprocessing as mp
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# Project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

# Reuse WF training infrastructure
from scripts.full_walkforward_train import (
    STRATEGIES, VIX_REGIMES, MODELS_DIR, DB_PATH,
    WFConfig, generate_epochs,
    _init_analyzer, _run_backtest_period, _get_regime,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("stability_train")

SCORING_WEIGHTS_PATH = project_root / "config" / "scoring_weights.yaml"

# Optimal thresholds from WF training
TRAINED_THRESHOLDS = {
    "pullback": 4.5,
    "bounce": 6.0,
    "ath_breakout": 6.0,
    "earnings_dip": 5.0,
    "trend_continuation": 5.5,
}

# Stability buckets to test
STABILITY_BUCKETS = [0, 40, 50, 55, 60, 65, 70, 75, 80, 85, 90]

# Minimum trades per bucket to be statistically meaningful
MIN_TRADES_PER_BUCKET = 10

# Target win rate — cutoff where win rate drops below this
TARGET_WIN_RATE = 82.0


def load_stability_scores() -> Dict[str, float]:
    """Load stability_score per symbol from symbol_fundamentals."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute(
        "SELECT symbol, stability_score FROM symbol_fundamentals WHERE stability_score IS NOT NULL"
    )
    scores = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    logger.info(f"  Loaded stability scores for {len(scores)} symbols")
    return scores


def load_sector_map() -> Dict[str, str]:
    """Load sector per symbol."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute(
        "SELECT symbol, sector FROM symbol_fundamentals WHERE sector IS NOT NULL"
    )
    sectors = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return sectors


def worker_stability_epoch(args):
    """Worker: run one epoch for one strategy at optimal threshold, return per-trade stability data."""
    (
        epoch_id, strategy, min_score,
        train_start_str, train_end_str, test_start_str, test_end_str,
        historical_data, vix_by_date, config_dict, sector_map, stability_scores,
    ) = args

    config = WFConfig(**config_dict)
    test_start = date.fromisoformat(test_start_str)
    test_end = date.fromisoformat(test_end_str)

    try:
        analyzer = _init_analyzer(strategy)

        # Create per-worker DB connection for real option chains
        spread_finder = None
        if config.pricing_mode == "real":
            from src.backtesting.core.database import OptionsDatabase
            from src.backtesting.core.spread_engine import SpreadFinder
            db = OptionsDatabase(DB_PATH)
            spread_finder = SpreadFinder(db)

        # OOS backtest only (that's what we care about)
        oos_trades, _, _ = _run_backtest_period(
            analyzer, strategy, historical_data, vix_by_date,
            test_start, test_end, min_score, config,
            spread_finder=spread_finder, sector_map=sector_map,
        )

        if spread_finder:
            spread_finder.db.close()

        # Enrich trades with stability scores
        enriched = []
        for t in oos_trades:
            symbol = t["symbol"]
            stability = stability_scores.get(symbol)
            if stability is not None:
                enriched.append({
                    "symbol": symbol,
                    "strategy": strategy,
                    "regime": t.get("vix_regime", "normal"),
                    "sector": t.get("sector", "Unknown"),
                    "stability": stability,
                    "is_win": t["is_win"],
                    "pnl": t["pnl"],
                })

        return {
            "epoch_id": epoch_id,
            "strategy": strategy,
            "total_trades": len(oos_trades),
            "enriched_trades": enriched,
            "error": None,
        }

    except Exception as e:
        return {
            "epoch_id": epoch_id,
            "strategy": strategy,
            "total_trades": 0,
            "enriched_trades": [],
            "error": str(e),
        }


def find_optimal_cutoff(trades: List[Dict], target_wr: float = TARGET_WIN_RATE) -> int:
    """Find minimum stability where win rate >= target.
    Returns the cutoff value (trades with stability < cutoff are filtered)."""
    if not trades:
        return 70  # default

    # Sort trades by stability
    trades_sorted = sorted(trades, key=lambda t: t["stability"])

    # Test each bucket: what's the win rate if we only keep stability >= cutoff?
    best_cutoff = 0
    for cutoff in STABILITY_BUCKETS:
        above = [t for t in trades_sorted if t["stability"] >= cutoff]
        if len(above) < MIN_TRADES_PER_BUCKET:
            continue
        wr = sum(1 for t in above if t["is_win"]) / len(above) * 100
        if wr >= target_wr:
            best_cutoff = cutoff
            break

    return best_cutoff


def find_sector_adjustments(
    trades: List[Dict], base_cutoff: int
) -> Dict[str, int]:
    """Find per-sector stability adjustments relative to base cutoff.
    Returns {sector: adjustment} where negative = lower threshold needed."""
    sector_groups = defaultdict(list)
    for t in trades:
        sector_groups[t["sector"]].append(t)

    adjustments = {}
    for sector, sector_trades in sector_groups.items():
        if sector == "Unknown" or len(sector_trades) < 15:
            continue

        # Find optimal cutoff for this sector
        sector_cutoff = find_optimal_cutoff(sector_trades)
        adj = sector_cutoff - base_cutoff

        # Only record significant adjustments (±5 or more)
        if abs(adj) >= 5:
            adjustments[sector] = int(round(adj / 5) * 5)  # round to nearest 5

    return adjustments


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=mp.cpu_count())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print("  STABILITY THRESHOLD OPTIMIZER")
    print("=" * 70)
    print()

    # Load data
    print("  Loading data...")
    stability_scores = load_stability_scores()
    sector_map = load_sector_map()

    from src.backtesting import TradeTracker
    tracker = TradeTracker()
    symbol_entries = tracker.list_symbols_with_price_data()
    all_symbols = sorted(set(e["symbol"] for e in symbol_entries))
    print(f"  Symbols in price_data: {len(all_symbols)}")

    # Load historical data
    historical_data = {}
    for sym in all_symbols:
        spd = tracker.get_price_data(sym)
        if spd and spd.bars and len(spd.bars) >= 60:
            historical_data[sym] = [
                {"date": b.date if isinstance(b.date, date) else date.fromisoformat(str(b.date)),
                 "close": b.close, "high": b.high, "low": b.low, "open": b.open, "volume": b.volume}
                for b in spd.bars
            ]
    print(f"  Loaded history for {len(historical_data)} symbols")

    # Load VIX
    conn = sqlite3.connect(str(DB_PATH))
    vix_rows = conn.execute("SELECT date, value FROM vix_data ORDER BY date").fetchall()
    conn.close()
    vix_by_date = {row[0]: row[1] for row in vix_rows}
    print(f"  VIX data: {len(vix_by_date)} days")

    # Determine epochs
    all_dates = set()
    for sym_data in historical_data.values():
        for bar in sym_data:
            all_dates.add(bar["date"])
    data_start = min(all_dates)
    data_end = max(all_dates)

    config = WFConfig(pricing_mode="real")
    epochs = generate_epochs(data_start, data_end, config)
    print(f"  Epochs: {len(epochs)}")
    print(f"  Strategies: {len(STRATEGIES)}")
    print(f"  Total jobs: {len(STRATEGIES) * len(epochs)}")
    print()

    if args.dry_run:
        for s in STRATEGIES:
            print(f"  {s}: threshold={TRAINED_THRESHOLDS[s]}, {len(epochs)} epochs")
        return

    # Build job list
    config_dict = {k: v for k, v in config.__dict__.items()}
    jobs = []
    for strategy in STRATEGIES:
        min_score = TRAINED_THRESHOLDS[strategy]
        for i, (ts, te, vs, ve) in enumerate(epochs):
            jobs.append((
                i, strategy, min_score,
                str(ts), str(te), str(vs), str(ve),
                historical_data, vix_by_date, config_dict, sector_map,
                stability_scores,
            ))

    print(f"  Running {len(jobs)} jobs on {args.workers} workers...")
    t0 = time.time()

    # Run parallel
    all_trades = []
    errors = 0
    with mp.Pool(args.workers) as pool:
        for result in pool.imap_unordered(worker_stability_epoch, jobs):
            if result["error"]:
                errors += 1
                if errors <= 3:
                    print(f"  ERROR [{result['strategy']} E{result['epoch_id']}]: {result['error']}")
            else:
                all_trades.extend(result["enriched_trades"])
                strat = result["strategy"]
                n = len(result["enriched_trades"])
                if n > 0:
                    print(f"  {strat} E{result['epoch_id']}: {n} trades with stability data")

    elapsed = time.time() - t0
    print(f"\n  Completed in {elapsed:.0f}s ({errors} errors)")
    print(f"  Total enriched trades: {len(all_trades)}")
    print()

    if not all_trades:
        print("  No trades found. Exiting.")
        return

    # =====================================================================
    # ANALYZE: Find optimal cutoffs per strategy × regime
    # =====================================================================
    print("=" * 70)
    print("  STABILITY ANALYSIS")
    print("=" * 70)
    print()

    # Group trades
    by_strategy = defaultdict(list)
    by_strategy_regime = defaultdict(list)
    for t in all_trades:
        by_strategy[t["strategy"]].append(t)
        by_strategy_regime[(t["strategy"], t["regime"])].append(t)

    # Results
    new_thresholds = {}

    for strategy in STRATEGIES:
        strat_trades = by_strategy[strategy]
        if not strat_trades:
            print(f"  {strategy}: no trades")
            continue

        total = len(strat_trades)
        wins = sum(1 for t in strat_trades if t["is_win"])
        overall_wr = wins / total * 100

        print(f"  {'=' * 60}")
        print(f"  STRATEGY: {strategy.upper()}")
        print(f"  {'=' * 60}")
        print(f"  Total OOS trades with stability data: {total}")
        print(f"  Overall WR: {overall_wr:.1f}%")
        print()

        # Stability bucket analysis
        print(f"  {'Stability':>12} {'Trades':>8} {'WR%':>8} {'Above WR%':>10} {'Above Trades':>13}")
        print(f"  {'-' * 55}")

        for bucket_min in STABILITY_BUCKETS:
            bucket_max = bucket_min + 10 if bucket_min < 90 else 200
            in_bucket = [t for t in strat_trades if bucket_min <= t["stability"] < bucket_max]
            above = [t for t in strat_trades if t["stability"] >= bucket_min]

            bucket_wr = (sum(1 for t in in_bucket if t["is_win"]) / len(in_bucket) * 100) if in_bucket else 0
            above_wr = (sum(1 for t in above if t["is_win"]) / len(above) * 100) if above else 0

            marker = " <--" if bucket_min > 0 and above_wr >= TARGET_WIN_RATE and len(above) >= MIN_TRADES_PER_BUCKET else ""
            print(f"  {bucket_min:>9}+ {len(in_bucket):>8} {bucket_wr:>7.1f}% {above_wr:>9.1f}% {len(above):>12}{marker}")

        print()

        # Per-regime analysis
        regime_cutoffs = {}
        print(f"  Per-regime cutoffs:")
        print(f"  {'Regime':>12} {'Trades':>8} {'WR%':>8} {'Cutoff':>8}")
        print(f"  {'-' * 40}")

        for regime in ["normal", "elevated", "high", "extreme"]:
            key = (strategy, regime)
            regime_trades = by_strategy_regime.get(key, [])
            if not regime_trades:
                regime_cutoffs[regime] = 70
                continue

            rwr = sum(1 for t in regime_trades if t["is_win"]) / len(regime_trades) * 100
            cutoff = find_optimal_cutoff(regime_trades)
            regime_cutoffs[regime] = cutoff
            print(f"  {regime:>12} {len(regime_trades):>8} {rwr:>7.1f}% {cutoff:>7}")

        print()

        # Per-sector adjustments (using all trades for the strategy)
        base_cutoff = find_optimal_cutoff(strat_trades)
        sector_adj = find_sector_adjustments(strat_trades, base_cutoff)

        if sector_adj:
            print(f"  Sector adjustments (vs base={base_cutoff}):")
            for sec, adj in sorted(sector_adj.items(), key=lambda x: x[1]):
                sign = "+" if adj > 0 else ""
                print(f"    {sec:>25}: {sign}{adj}")
            print()

        new_thresholds[strategy] = {
            "by_regime": regime_cutoffs,
            "by_sector": sector_adj,
        }

    # =====================================================================
    # UPDATE scoring_weights.yaml
    # =====================================================================
    print("=" * 70)
    print("  UPDATING scoring_weights.yaml")
    print("=" * 70)
    print()

    with open(SCORING_WEIGHTS_PATH, "r") as f:
        yaml_data = yaml.safe_load(f)

    old_thresholds = yaml_data.get("stability_thresholds", {}).get("by_strategy", {})

    # Update
    if "stability_thresholds" not in yaml_data:
        yaml_data["stability_thresholds"] = {}
    yaml_data["stability_thresholds"]["by_strategy"] = {}

    for strategy in STRATEGIES:
        if strategy not in new_thresholds:
            continue

        st = new_thresholds[strategy]
        yaml_data["stability_thresholds"]["by_strategy"][strategy] = {
            "by_regime": {k: int(v) for k, v in st["by_regime"].items()},
            "by_sector": {k: int(v) for k, v in st["by_sector"].items()},
        }

    # Show diff
    for strategy in STRATEGIES:
        if strategy not in new_thresholds:
            continue
        old = old_thresholds.get(strategy, {})
        new = new_thresholds[strategy]
        print(f"  {strategy}:")
        print(f"    Regime cutoffs: {old.get('by_regime', {})} → {new['by_regime']}")
        print(f"    Sector adj:     {old.get('by_sector', {})} → {new['by_sector']}")
        print()

    with open(SCORING_WEIGHTS_PATH, "w") as f:
        yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"  Saved: {SCORING_WEIGHTS_PATH}")

    # Also save detailed results
    results_path = MODELS_DIR / "stability_threshold_analysis.json"
    results = {
        "version": "1.0.0",
        "created_at": str(date.today()),
        "total_trades": len(all_trades),
        "target_win_rate": TARGET_WIN_RATE,
        "strategies": {},
    }
    for strategy in STRATEGIES:
        strat_trades = by_strategy.get(strategy, [])
        if not strat_trades:
            continue
        results["strategies"][strategy] = {
            "total_trades": len(strat_trades),
            "overall_wr": round(sum(1 for t in strat_trades if t["is_win"]) / len(strat_trades) * 100, 1),
            "thresholds": new_thresholds.get(strategy, {}),
        }

    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {results_path}")
    print()
    print("  Done!")


if __name__ == "__main__":
    main()
