#!/usr/bin/env python3
"""
Iteration 3: Regime × Strategie Weight-Training.

Trainiert separate Gewichtsvektoren für jede Kombination
von VIX-Regime × Strategie.

Fallback-Kaskade:
  1. Strategy × Regime spezifisch  (wenn >= MIN_TRADES)
  2. Strategy global               (aus Iter 2)
  3. Global default

Output: trained_weights_v3_regime_<strategy>.json + trained_weights_v3_regime_summary.json
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
OUTPUT_DIR = Path(__file__).parent.parent / "data_inventory"

STRATEGIES = ["pullback", "bounce", "ath_breakout"]
REGIMES = ["low", "medium", "high", "extreme"]

# Minimum trades required for regime-specific training
# Below this → fall back to strategy-global weights
MIN_TRADES_PER_REGIME = {
    "pullback": {"low": 80, "medium": 80, "high": 60, "extreme": 40},
    "bounce": {"low": 80, "medium": 80, "high": 60, "extreme": 40},
    "ath_breakout": {"low": 80, "medium": 80, "high": 60, "extreme": 40},
}


def load_trades_df():
    """Load all trades from outcomes.db as a DataFrame."""
    conn = sqlite3.connect(OUTCOMES_DB)

    cols = [
        "symbol", "entry_date", "was_profitable", "pnl_pct",
        "vix_regime", "max_drawdown_pct",
        "pullback_score", "bounce_score", "ath_breakout_score", "earnings_dip_score",
        # Component scores
        "rsi_score", "support_score", "fibonacci_score", "ma_score",
        "volume_score", "macd_score", "stoch_score", "keltner_score",
        "trend_strength_score", "momentum_score", "rs_score",
        "candlestick_score", "vwap_score", "market_context_score",
        "sector_score", "gap_score",
    ]

    query = f"SELECT {', '.join(cols)} FROM trade_outcomes WHERE pullback_score IS NOT NULL ORDER BY entry_date"
    df = pd.read_sql_query(query, conn)
    conn.close()

    score_cols = [c for c in df.columns if c.endswith("_score")]
    df[score_cols] = df[score_cols].fillna(0)

    print(f"Loaded {len(df)} trades from outcomes.db")
    return df


def load_global_weights(strategy):
    """Load strategy-global weights from Iter 2 output."""
    path = OUTPUT_DIR / f"trained_weights_v3_{strategy}.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return data.get("weights", {})
    return {}


def get_regime_trade_counts(df, strategy):
    """Get trade counts per regime for a strategy."""
    score_col = f"{strategy}_score"
    other_cols = [f"{s}_score" for s in STRATEGIES if s != strategy]

    mask = (df[score_col].notna()) & (df[score_col] > 0)
    for oc in other_cols:
        mask = mask & (df[score_col] >= df[oc].fillna(0))

    strategy_df = df[mask]
    counts = strategy_df["vix_regime"].value_counts().to_dict()
    return counts


def train_regime(strategy, df, regime, global_weights):
    """Train weights for a single strategy × regime combination."""
    # Reset singleton
    RecursiveConfigResolver.reset()

    trainer = StrategyWeightTrainer(strategy)

    # Override min_trades for regime-specific training (lower than global)
    min_trades = MIN_TRADES_PER_REGIME.get(strategy, {}).get(regime, 50)
    trainer.config.min_trades = min_trades

    result = trainer.train(df, regime=regime)

    if result.converged:
        return {
            "source": "trained",
            "regime": regime,
            "weights": {k: round(v, 4) for k, v in result.weights.items()},
            "metrics": {
                "objective": round(result.metrics.get("objective_value", 0), 4),
                "val_objective": round(result.metrics.get("val_objective", 0), 4),
                "val_win_rate": round(result.metrics.get("val_win_rate", 0), 4),
                "n_trades": result.n_trades,
                "n_train": result.n_train,
                "n_val": result.n_validation,
            },
        }
    else:
        # Fallback to global weights
        return {
            "source": "fallback_global",
            "regime": regime,
            "weights": {k: round(v, 4) for k, v in global_weights.items()},
            "metrics": {
                "reason": result.metrics.get("reason", "not_converged"),
                "n_trades": result.n_trades,
            },
        }


def evaluate_regime_improvement(strategy, df, regime_weights, global_weights):
    """Compare regime-specific vs global weights per regime."""
    components = STRATEGY_COMPONENTS.get(strategy, [])
    score_col = f"{strategy}_score"
    other_cols = [f"{s}_score" for s in STRATEGIES if s != strategy]

    mask = (df[score_col].notna()) & (df[score_col] > 0)
    for oc in other_cols:
        mask = mask & (df[score_col] >= df[oc].fillna(0))

    strategy_df = df[mask].copy()
    available = [c for c in components if c in strategy_df.columns]

    results = {}
    for regime in REGIMES:
        regime_df = strategy_df[strategy_df["vix_regime"] == regime]
        if len(regime_df) < 20:
            continue

        X = regime_df[available].values.astype(np.float64)
        outcomes = regime_df["was_profitable"].values
        pnl = regime_df["pnl_pct"].values

        # Global weights scoring
        gw = np.array([global_weights.get(c, 1.0) for c in available])
        g_scores = X @ gw
        g_median = np.median(g_scores) if len(g_scores) > 0 else 0
        g_high = g_scores >= g_median
        g_wr = outcomes[g_high].mean() * 100 if g_high.sum() > 0 else 0
        g_pnl = pnl[g_high].mean() if g_high.sum() > 0 else 0

        # Regime weights scoring
        rw_dict = regime_weights.get(regime, {}).get("weights", global_weights)
        rw = np.array([rw_dict.get(c, 1.0) for c in available])
        r_scores = X @ rw
        r_median = np.median(r_scores) if len(r_scores) > 0 else 0
        r_high = r_scores >= r_median
        r_wr = outcomes[r_high].mean() * 100 if r_high.sum() > 0 else 0
        r_pnl = pnl[r_high].mean() if r_high.sum() > 0 else 0

        results[regime] = {
            "n_trades": len(regime_df),
            "global_top50_wr": round(float(g_wr), 1),
            "regime_top50_wr": round(float(r_wr), 1),
            "wr_delta": round(float(r_wr - g_wr), 1),
            "global_top50_pnl": round(float(g_pnl), 2),
            "regime_top50_pnl": round(float(r_pnl), 2),
            "pnl_delta": round(float(r_pnl - g_pnl), 2),
        }

    return results


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    df = load_trades_df()
    summary = {}

    for strategy in STRATEGIES:
        print(f"\n{'='*60}")
        print(f"  {strategy.upper()} — Regime × Strategy Training")
        print(f"{'='*60}")

        # Load global weights from Iter 2
        global_weights = load_global_weights(strategy)
        if not global_weights:
            print(f"  WARNING: No Iter 2 weights found for {strategy}, using defaults")

        # Show trade distribution
        counts = get_regime_trade_counts(df, strategy)
        print(f"  Trade counts per regime:")
        for regime in REGIMES:
            cnt = counts.get(regime, 0)
            min_req = MIN_TRADES_PER_REGIME.get(strategy, {}).get(regime, 50)
            status = "✓ TRAIN" if cnt >= min_req else "✗ FALLBACK"
            print(f"    {regime:>8s}: {cnt:>5} trades (min={min_req}) → {status}")

        # Train per regime
        regime_results = {}
        for regime in REGIMES:
            cnt = counts.get(regime, 0)
            min_req = MIN_TRADES_PER_REGIME.get(strategy, {}).get(regime, 50)

            if cnt < min_req:
                print(f"\n  {regime}: FALLBACK → global weights ({cnt} < {min_req} trades)")
                regime_results[regime] = {
                    "source": "fallback_global",
                    "regime": regime,
                    "weights": {k: round(v, 4) for k, v in global_weights.items()},
                    "metrics": {"reason": "insufficient_data", "n_trades": cnt},
                }
                continue

            print(f"\n  {regime}: Training ({cnt} trades)...")
            result = train_regime(strategy, df, regime, global_weights)
            regime_results[regime] = result

            if result["source"] == "trained":
                print(f"    Converged! Val WR={result['metrics']['val_win_rate']*100:.1f}%")
                # Show top 3 weight differences
                sorted_diffs = sorted(
                    [
                        (c, result["weights"].get(c, 0) - global_weights.get(c, 0))
                        for c in result["weights"]
                    ],
                    key=lambda x: abs(x[1]),
                    reverse=True,
                )
                for comp, diff in sorted_diffs[:3]:
                    print(f"    {comp}: {global_weights.get(comp, 0):.3f} → {result['weights'].get(comp, 0):.3f} ({diff:+.3f})")
            else:
                print(f"    FALLBACK: {result['metrics'].get('reason', 'unknown')}")

        # Evaluate improvement
        improvement = evaluate_regime_improvement(strategy, df, regime_results, global_weights)
        print(f"\n  Improvement vs Global Weights (top-50% by score):")
        for regime, imp in improvement.items():
            print(f"    {regime:>8s}: n={imp['n_trades']:>5}, "
                  f"WR: {imp['global_top50_wr']:.1f}% → {imp['regime_top50_wr']:.1f}% ({imp['wr_delta']:+.1f}), "
                  f"PnL: {imp['global_top50_pnl']:.2f} → {imp['regime_top50_pnl']:.2f} ({imp['pnl_delta']:+.2f})")

        # Save per-strategy regime results
        output = {
            "strategy": strategy,
            "regimes": regime_results,
            "improvement": improvement,
        }

        output_path = OUTPUT_DIR / f"trained_weights_v3_regime_{strategy}.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n  Saved: {output_path}")

        summary[strategy] = {
            "regimes_trained": sum(1 for r in regime_results.values() if r["source"] == "trained"),
            "regimes_fallback": sum(1 for r in regime_results.values() if r["source"] == "fallback_global"),
            "improvement": improvement,
        }

    # Save summary
    summary_path = OUTPUT_DIR / "trained_weights_v3_regime_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  REGIME TRAINING COMPLETE")
    print(f"{'='*60}")
    for strategy, stats in summary.items():
        print(f"  {strategy:>15s}: trained={stats['regimes_trained']}/4, fallback={stats['regimes_fallback']}/4")
        for regime, imp in stats.get("improvement", {}).items():
            wr_d = imp.get("wr_delta", "N/A")
            pnl_d = imp.get("pnl_delta", "N/A")
            print(f"    {regime:>8s}: WR Δ={wr_d:+.1f}%, PnL Δ={pnl_d:+.2f}%")


if __name__ == "__main__":
    main()
