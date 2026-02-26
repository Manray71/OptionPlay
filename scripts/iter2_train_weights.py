#!/usr/bin/env python3
"""
Iteration 2: Weight-Training pro Strategie.

Lädt Trades aus outcomes.db, trainiert pro Strategie optimale Gewichte
mit dem StrategyWeightTrainer, und speichert die Ergebnisse.

Output: trained_weights_v3_<strategy>.json + trained_weights_v3_summary.json
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.training.strategy_weight_trainer import (
    StrategyWeightTrainer,
    StrategyTrainingConfig,
)
from src.backtesting.training.ml_weight_optimizer import STRATEGY_COMPONENTS
from src.config.scoring_config import RecursiveConfigResolver

# ─── Config ────────────────────────────────────────────
OUTCOMES_DB = os.path.expanduser("~/.optionplay/outcomes.db")
TRADES_DB = os.path.expanduser("~/.optionplay/trades.db")
OUTPUT_DIR = Path(__file__).parent.parent / "data_inventory"

STRATEGIES = ["pullback", "bounce", "ath_breakout"]
# earnings_dip has NO data → skip


def load_trades_df():
    """Load all trades from outcomes.db as a DataFrame."""
    conn = sqlite3.connect(OUTCOMES_DB)

    # Columns we need
    cols = [
        "symbol",
        "entry_date",
        "was_profitable",
        "pnl_pct",
        "vix_regime",
        "max_drawdown_pct",
        "pullback_score",
        "bounce_score",
        "ath_breakout_score",
        "earnings_dip_score",
        # Component scores
        "rsi_score",
        "support_score",
        "fibonacci_score",
        "ma_score",
        "volume_score",
        "macd_score",
        "stoch_score",
        "keltner_score",
        "trend_strength_score",
        "momentum_score",
        "rs_score",
        "candlestick_score",
        "vwap_score",
        "market_context_score",
        "sector_score",
        "gap_score",
    ]

    query = f"SELECT {', '.join(cols)} FROM trade_outcomes WHERE pullback_score IS NOT NULL ORDER BY entry_date"
    df = pd.read_sql_query(query, conn)
    conn.close()

    # Fill NaN scores with 0
    score_cols = [c for c in df.columns if c.endswith("_score")]
    df[score_cols] = df[score_cols].fillna(0)

    print(f"Loaded {len(df)} trades from outcomes.db")
    return df


def load_sector_map():
    """Load symbol → sector mapping."""
    conn = sqlite3.connect(TRADES_DB)
    rows = conn.execute("SELECT symbol, sector FROM symbol_fundamentals").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows if r[1]}


def train_strategy(strategy, df):
    """Train weights for a single strategy."""
    print(f"\n{'='*60}")
    print(f"  Training: {strategy.upper()}")
    print(f"{'='*60}")

    # Reset singleton to use project config
    RecursiveConfigResolver.reset()

    trainer = StrategyWeightTrainer(strategy)
    print(
        f"  Config: L2={trainer.config.l2_lambda}, "
        f"max_change={trainer.config.max_weight_change}, "
        f"bounds={trainer.config.weight_bounds}"
    )
    print(f"  Components: {len(trainer.components)}")

    result = trainer.train(df)

    print(f"\n  Results:")
    print(f"    Trades used: {result.n_trades} (train={result.n_train}, val={result.n_validation})")
    print(f"    Converged: {result.converged}")

    if result.converged:
        print(f"    Objective: {result.metrics.get('objective_value', 'N/A'):.4f}")
        print(f"    Val Objective: {result.metrics.get('val_objective', 'N/A'):.4f}")
        print(f"    Val Win-Rate: {result.metrics.get('val_win_rate', 0)*100:.1f}%")

        print(f"\n  Trained Weights:")
        # Sort by weight value
        sorted_weights = sorted(result.weights.items(), key=lambda x: -x[1])
        for comp, w in sorted_weights:
            print(f"    {comp:>30s}: {w:.3f}")
    else:
        print(f"    Reason: {result.metrics.get('reason', 'unknown')}")

    return result


def evaluate_improvement(strategy, df, old_weights, new_weights):
    """Compare old vs new weights on the full dataset."""
    # Get strategy trades
    score_col = f"{strategy}_score"
    other_cols = [f"{s}_score" for s in STRATEGIES if s != strategy]

    mask = df[score_col] > 0
    for oc in other_cols:
        mask = mask & (df[score_col] >= df[oc])

    strategy_df = df[mask].copy()
    if len(strategy_df) == 0:
        return {}

    components = STRATEGY_COMPONENTS.get(strategy, [])
    available = [c for c in components if c in strategy_df.columns]

    X = strategy_df[available].values.astype(np.float64)
    outcomes = strategy_df["was_profitable"].values
    pnl = strategy_df["pnl_pct"].values

    # Old scores
    old_w = np.array([old_weights.get(c, 1.0) for c in available])
    old_scores = X @ old_w
    old_median = np.median(old_scores)
    old_high_mask = old_scores >= old_median

    old_high_wr = outcomes[old_high_mask].mean() * 100 if old_high_mask.sum() > 0 else 0
    old_high_pnl = pnl[old_high_mask].mean() if old_high_mask.sum() > 0 else 0

    # New scores
    new_w = np.array([new_weights.get(c, 1.0) for c in available])
    new_scores = X @ new_w
    new_median = np.median(new_scores)
    new_high_mask = new_scores >= new_median

    new_high_wr = outcomes[new_high_mask].mean() * 100 if new_high_mask.sum() > 0 else 0
    new_high_pnl = pnl[new_high_mask].mean() if new_high_mask.sum() > 0 else 0

    result = {
        "old_top50_wr": round(float(old_high_wr), 1),
        "new_top50_wr": round(float(new_high_wr), 1),
        "wr_delta": round(float(new_high_wr - old_high_wr), 1),
        "old_top50_pnl": round(float(old_high_pnl), 2),
        "new_top50_pnl": round(float(new_high_pnl), 2),
        "pnl_delta": round(float(new_high_pnl - old_high_pnl), 2),
    }

    print(f"\n  Improvement (top 50% by score):")
    print(f"    WR: {old_high_wr:.1f}% → {new_high_wr:.1f}% ({result['wr_delta']:+.1f}%)")
    print(f"    PnL: {old_high_pnl:.2f}% → {new_high_pnl:.2f}% ({result['pnl_delta']:+.2f}%)")

    return result


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    df = load_trades_df()
    sector_map = load_sector_map()

    summary = {}

    for strategy in STRATEGIES:
        result = train_strategy(strategy, df)

        # Get old weights for comparison
        RecursiveConfigResolver.reset()
        resolver = RecursiveConfigResolver()
        resolved = resolver.resolve(strategy, "normal")
        old_weights = {}
        for comp in STRATEGY_COMPONENTS.get(strategy, []):
            config_key = comp.replace("_score", "")
            old_weights[comp] = resolved.weights.get(config_key, 1.0)

        # Evaluate improvement
        improvement = evaluate_improvement(strategy, df, old_weights, result.weights)

        # Save per-strategy results
        output = {
            "strategy": strategy,
            "config": {
                "l2_lambda": result.metrics.get("l2_lambda"),
                "n_trades": result.n_trades,
                "n_train": result.n_train,
                "n_validation": result.n_validation,
                "converged": result.converged,
            },
            "weights": {k: round(v, 4) for k, v in result.weights.items()},
            "old_weights": {k: round(v, 4) for k, v in old_weights.items()},
            "metrics": {
                k: round(v, 4) if isinstance(v, float) else v for k, v in result.metrics.items()
            },
            "improvement": improvement,
        }

        output_path = OUTPUT_DIR / f"trained_weights_v3_{strategy}.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n  Saved: {output_path}")

        summary[strategy] = {
            "converged": result.converged,
            "n_trades": result.n_trades,
            "val_wr": result.metrics.get("val_win_rate", 0),
            "improvement": improvement,
        }

    # Save summary
    summary_path = OUTPUT_DIR / "trained_weights_v3_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  TRAINING COMPLETE")
    print(f"{'='*60}")
    for strategy, stats in summary.items():
        imp = stats.get("improvement", {})
        print(
            f"  {strategy:>15s}: converged={stats['converged']}, "
            f"WR delta={imp.get('wr_delta', 'N/A')}, "
            f"PnL delta={imp.get('pnl_delta', 'N/A')}"
        )


if __name__ == "__main__":
    main()
