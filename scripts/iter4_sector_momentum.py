#!/usr/bin/env python3
"""
Iteration 4: Sektor-Momentum pro Strategie.

Analysiert historische Performance pro Strategy × Sector und optimiert:
1. Sector performance score per strategy (welche Sektoren performen gut/schlecht)
2. Optimal sector factor ranges per strategy
3. Sector-specific weight adjustments

Output: trained_weights_v3_sector_<strategy>.json + trained_weights_v3_sector_summary.json
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.scoring_config import RecursiveConfigResolver

# ─── Config ────────────────────────────────────────────
OUTCOMES_DB = os.path.expanduser("~/.optionplay/outcomes.db")
TRADES_DB = os.path.expanduser("~/.optionplay/trades.db")
OUTPUT_DIR = Path(__file__).parent.parent / "data_inventory"

STRATEGIES = ["pullback", "bounce", "ath_breakout"]
MIN_SECTOR_TRADES = 30  # Minimum trades per sector × strategy


def load_sector_map():
    """Load symbol → sector mapping."""
    conn = sqlite3.connect(TRADES_DB)
    rows = conn.execute("SELECT symbol, sector FROM symbol_fundamentals").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows if r[1]}


def load_strategy_trades(strategy):
    """Load trades for a strategy from outcomes.db."""
    conn = sqlite3.connect(OUTCOMES_DB)

    score_col = f"{strategy}_score"
    other_scores = [f"{s}_score" for s in STRATEGIES if s != strategy]

    where = [f"{score_col} IS NOT NULL", f"{score_col} > 0"]
    for oc in other_scores:
        where.append(f"{score_col} >= COALESCE({oc}, 0)")

    cols = [
        "symbol", "was_profitable", "pnl_pct", "vix_regime",
        "max_drawdown_pct", score_col,
        "rsi_score", "support_score", "fibonacci_score", "ma_score",
        "volume_score", "macd_score", "stoch_score", "keltner_score",
        "trend_strength_score", "momentum_score",
        "candlestick_score", "vwap_score", "market_context_score",
    ]

    query = f"SELECT {', '.join(cols)} FROM trade_outcomes WHERE {' AND '.join(where)} ORDER BY entry_date"
    rows = conn.execute(query).fetchall()
    conn.close()

    return [dict(zip(cols, row)) for row in rows]


def analyze_sector_performance(trades, sector_map, strategy):
    """Compute sector performance metrics per strategy."""
    sector_stats = defaultdict(lambda: {
        "n": 0, "wins": 0, "pnl_sum": 0.0, "pnl_list": [],
        "drawdowns": [], "regimes": defaultdict(int),
    })

    for t in trades:
        sector = sector_map.get(t["symbol"], "Unknown")
        stats = sector_stats[sector]
        stats["n"] += 1
        stats["wins"] += t["was_profitable"] or 0
        stats["pnl_sum"] += t["pnl_pct"] or 0
        stats["pnl_list"].append(t["pnl_pct"] or 0)
        if t["max_drawdown_pct"]:
            stats["drawdowns"].append(t["max_drawdown_pct"])
        stats["regimes"][t["vix_regime"] or "unknown"] += 1

    results = {}
    for sector, stats in sorted(sector_stats.items(), key=lambda x: -x[1]["n"]):
        if stats["n"] < MIN_SECTOR_TRADES:
            continue

        pnl_arr = np.array(stats["pnl_list"])
        wr = stats["wins"] / stats["n"] * 100
        avg_pnl = stats["pnl_sum"] / stats["n"]

        # Risk-adjusted metrics
        pnl_std = pnl_arr.std() if len(pnl_arr) > 1 else 0
        sharpe_like = avg_pnl / (pnl_std + 1e-6) if pnl_std > 0 else 0
        avg_dd = np.mean(stats["drawdowns"]) if stats["drawdowns"] else 0

        # Tail risk: average of worst 10% of PnLs
        n_tail = max(1, int(len(pnl_arr) * 0.1))
        sorted_pnl = np.sort(pnl_arr)
        tail_loss = sorted_pnl[:n_tail].mean()

        results[sector] = {
            "n": stats["n"],
            "win_rate": round(wr, 1),
            "avg_pnl": round(avg_pnl, 2),
            "pnl_std": round(pnl_std, 2),
            "sharpe_like": round(sharpe_like, 3),
            "avg_drawdown": round(avg_dd, 2),
            "tail_loss_10pct": round(tail_loss, 2),
            "regime_distribution": dict(stats["regimes"]),
        }

    return results


def compute_sector_scores(sector_perf, strategy):
    """
    Compute a momentum factor for each sector based on historical performance.

    Score range: [0.5, 1.5] where:
    - 1.0 = average sector
    - > 1.0 = outperforming (boost)
    - < 1.0 = underperforming (penalize)
    """
    if not sector_perf:
        return {}

    # Compute composite score from multiple metrics
    sectors = list(sector_perf.keys())
    metrics = {}
    for sector in sectors:
        p = sector_perf[sector]
        # Normalize each metric
        metrics[sector] = {
            "wr": p["win_rate"],
            "pnl": p["avg_pnl"],
            "sharpe": p["sharpe_like"],
            "tail": p["tail_loss_10pct"],
        }

    # Strategy-specific weighting of metrics
    weights = {
        "pullback": {"wr": 0.30, "pnl": 0.25, "sharpe": 0.30, "tail": 0.15},
        "bounce": {"wr": 0.25, "pnl": 0.30, "sharpe": 0.25, "tail": 0.20},
        "ath_breakout": {"wr": 0.20, "pnl": 0.20, "sharpe": 0.25, "tail": 0.35},
    }
    w = weights.get(strategy, {"wr": 0.25, "pnl": 0.25, "sharpe": 0.25, "tail": 0.25})

    # Z-score normalize each metric across sectors
    raw_scores = {}
    for metric_name in ["wr", "pnl", "sharpe", "tail"]:
        values = [metrics[s][metric_name] for s in sectors]
        mean_v = np.mean(values)
        std_v = np.std(values) + 1e-8
        for sector in sectors:
            z = (metrics[sector][metric_name] - mean_v) / std_v
            # Invert tail (lower = better)
            if metric_name == "tail":
                z = -z
            raw_scores.setdefault(sector, 0)
            raw_scores[sector] += w[metric_name] * z

    # Convert z-scores to factor range
    # Strategy-specific factor ranges from YAML config
    factor_ranges = {
        "pullback": (0.60, 1.20),
        "bounce": (0.75, 1.15),
        "ath_breakout": (0.50, 1.25),
    }
    f_min, f_max = factor_ranges.get(strategy, (0.60, 1.20))

    # Sigmoid mapping: z-score → factor
    sector_factors = {}
    for sector in sectors:
        z = raw_scores[sector]
        # Sigmoid to [0, 1]
        sigmoid = 1.0 / (1.0 + np.exp(-1.5 * z))
        # Map to [f_min, f_max]
        factor = f_min + sigmoid * (f_max - f_min)
        sector_factors[sector] = round(factor, 3)

    return sector_factors


def compute_regime_sector_factors(trades, sector_map, strategy):
    """Compute sector factors per regime."""
    regimes = ["low", "medium", "high", "extreme"]
    regime_factors = {}

    for regime in regimes:
        regime_trades = [t for t in trades if t["vix_regime"] == regime]
        if len(regime_trades) < 50:
            regime_factors[regime] = {}
            continue

        perf = analyze_sector_performance(regime_trades, sector_map, strategy)
        factors = compute_sector_scores(perf, strategy)
        regime_factors[regime] = factors

    return regime_factors


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    sector_map = load_sector_map()
    summary = {}

    for strategy in STRATEGIES:
        print(f"\n{'='*60}")
        print(f"  {strategy.upper()} — Sector Momentum Analysis")
        print(f"{'='*60}")

        trades = load_strategy_trades(strategy)
        print(f"  Total trades: {len(trades)}")

        # 1. Sector Performance
        sector_perf = analyze_sector_performance(trades, sector_map, strategy)
        print(f"\n  Sector Performance ({len(sector_perf)} sectors):")
        for sector, p in sorted(sector_perf.items(), key=lambda x: -x[1]["avg_pnl"]):
            print(f"    {sector:>25s}: n={p['n']:>5}, WR={p['win_rate']:>5.1f}%, "
                  f"PnL={p['avg_pnl']:>8.2f}%, Sharpe={p['sharpe_like']:>6.3f}, "
                  f"Tail10={p['tail_loss_10pct']:>8.2f}%")

        # 2. Sector Factors
        sector_factors = compute_sector_scores(sector_perf, strategy)
        print(f"\n  Sector Factors (momentum multiplier):")
        for sector, factor in sorted(sector_factors.items(), key=lambda x: -x[1]):
            emoji = "+" if factor > 1.05 else ("-" if factor < 0.95 else "=")
            print(f"    {sector:>25s}: {factor:.3f} [{emoji}]")

        # 3. Regime × Sector Factors
        regime_factors = compute_regime_sector_factors(trades, sector_map, strategy)
        print(f"\n  Regime-Specific Sector Factors:")
        for regime in ["low", "medium", "high", "extreme"]:
            factors = regime_factors.get(regime, {})
            if factors:
                # Show most extreme factors
                extremes = sorted(factors.items(), key=lambda x: abs(x[1] - 1.0), reverse=True)[:3]
                parts = [f"{s}: {f:.2f}" for s, f in extremes]
                print(f"    {regime:>8s}: {', '.join(parts)}")
            else:
                print(f"    {regime:>8s}: insufficient data")

        # Save per-strategy
        output = {
            "strategy": strategy,
            "n_trades": len(trades),
            "sector_performance": sector_perf,
            "sector_factors": sector_factors,
            "regime_sector_factors": regime_factors,
        }

        output_path = OUTPUT_DIR / f"trained_weights_v3_sector_{strategy}.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n  Saved: {output_path}")

        # Summary stats
        factors_arr = np.array(list(sector_factors.values()))
        summary[strategy] = {
            "n_sectors": len(sector_factors),
            "factor_mean": round(float(factors_arr.mean()), 3),
            "factor_std": round(float(factors_arr.std()), 3),
            "best_sector": max(sector_factors.items(), key=lambda x: x[1])[0] if sector_factors else None,
            "worst_sector": min(sector_factors.items(), key=lambda x: x[1])[0] if sector_factors else None,
            "n_boosted": sum(1 for f in sector_factors.values() if f > 1.05),
            "n_penalized": sum(1 for f in sector_factors.values() if f < 0.95),
        }

    # Save summary
    summary_path = OUTPUT_DIR / "trained_weights_v3_sector_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  SECTOR MOMENTUM ANALYSIS COMPLETE")
    print(f"{'='*60}")
    for strategy, stats in summary.items():
        print(f"  {strategy:>15s}: {stats['n_sectors']} sectors, "
              f"boosted={stats['n_boosted']}, penalized={stats['n_penalized']}, "
              f"best={stats['best_sector']}, worst={stats['worst_sector']}")


if __name__ == "__main__":
    main()
