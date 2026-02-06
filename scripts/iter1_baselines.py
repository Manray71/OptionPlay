#!/usr/bin/env python3
"""
Iteration 1: Strategie-Baselines messen.

Analysiert outcomes.db und erzeugt pro Strategie:
1. Win-Rate per Score-Bucket (0-2, 2-4, 4-6, 6-8, 8-10)
2. Component-Importance (Korrelation jedes Score-Features mit Outcome)
3. Score-Calibration: Predicted vs. Actual Win-Rate
4. Sektor-Performance: Win-Rate per Sektor per Strategy
5. Regime-Performance: Win-Rate per Regime per Strategy

Output: baseline_<strategy>.json + baseline_summary.json
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

# ─── Config ────────────────────────────────────────────
OUTCOMES_DB = os.path.expanduser("~/.optionplay/outcomes.db")
TRADES_DB = os.path.expanduser("~/.optionplay/trades.db")
OUTPUT_DIR = Path(__file__).parent.parent / "data_inventory"

STRATEGY_SCORE_COLS = {
    "pullback": "pullback_score",
    "bounce": "bounce_score",
    "ath_breakout": "ath_breakout_score",
}

COMPONENT_COLS = [
    "rsi_score", "support_score", "fibonacci_score", "ma_score",
    "volume_score", "macd_score", "stoch_score", "keltner_score",
    "trend_strength_score", "momentum_score", "rs_score",
    "candlestick_score", "vwap_score", "market_context_score",
    "sector_score", "gap_score",
]

def _spearman_r(x, y):
    """Simple Spearman rank correlation (no scipy needed)."""
    n = len(x)
    if n < 3:
        return 0.0, 1.0
    rank_x = np.argsort(np.argsort(x)).astype(float)
    rank_y = np.argsort(np.argsort(y)).astype(float)
    d = rank_x - rank_y
    rho = 1 - (6 * np.sum(d**2)) / (n * (n**2 - 1))
    # Approximate p-value
    t_stat = rho * np.sqrt((n - 2) / (1 - rho**2 + 1e-10))
    return float(rho), 0.0  # p-value approximation omitted


def get_strategy_trades(conn, strategy, score_col):
    """Get trades where this strategy has the highest score."""
    other_cols = [c for s, c in STRATEGY_SCORE_COLS.items() if s != strategy]
    where_parts = [f"{score_col} IS NOT NULL", f"{score_col} > 0"]
    for oc in other_cols:
        where_parts.append(f"{score_col} >= COALESCE({oc}, 0)")

    cols = ", ".join(
        ["symbol", "was_profitable", "pnl_pct", "vix_regime",
         "max_drawdown_pct", score_col] + COMPONENT_COLS
    )
    query = f"SELECT {cols} FROM trade_outcomes WHERE {' AND '.join(where_parts)}"

    rows = conn.execute(query).fetchall()
    col_names = (
        ["symbol", "was_profitable", "pnl_pct", "vix_regime",
         "max_drawdown_pct", "strategy_score"] + COMPONENT_COLS
    )
    return [dict(zip(col_names, row)) for row in rows]


def get_sector_map(trades_db_path):
    """Load symbol → sector mapping from trades.db."""
    conn = sqlite3.connect(trades_db_path)
    rows = conn.execute("SELECT symbol, sector FROM symbol_fundamentals").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows if r[1]}


def analyze_win_rate_by_decile(trades, score_col="strategy_score"):
    """Win-Rate per Score-Decile (adaptive buckets)."""
    scored = [(t[score_col] or 0, t["was_profitable"] or 0, t["pnl_pct"] or 0) for t in trades]
    scored.sort(key=lambda x: x[0])

    n = len(scored)
    if n < 10:
        return {}

    decile_size = n // 10
    results = {}
    for i in range(10):
        start = i * decile_size
        end = (i + 1) * decile_size if i < 9 else n
        decile = scored[start:end]
        scores = [s[0] for s in decile]
        wins = [s[1] for s in decile]
        pnls = [s[2] for s in decile]

        results[f"D{i+1}"] = {
            "score_range": f"{min(scores):.3f}-{max(scores):.3f}",
            "count": len(decile),
            "win_rate": round(np.mean(wins) * 100, 1),
            "avg_pnl": round(float(np.mean(pnls)), 2),
        }
    return results


def analyze_component_importance(trades):
    """Pearson correlation of each component score with outcome."""
    results = {}
    outcomes = np.array([t["was_profitable"] or 0 for t in trades], dtype=float)

    if outcomes.std() == 0:
        return {c: 0.0 for c in COMPONENT_COLS}

    for comp in COMPONENT_COLS:
        values = np.array([t.get(comp) or 0 for t in trades], dtype=float)
        if values.std() == 0:
            results[comp] = 0.0
            continue
        corr = np.corrcoef(values, outcomes)[0, 1]
        results[comp] = round(float(corr), 4) if not np.isnan(corr) else 0.0

    # Sort by absolute correlation
    results = dict(sorted(results.items(), key=lambda x: abs(x[1]), reverse=True))
    return results


def analyze_score_calibration(trades, score_col="strategy_score"):
    """Predicted vs. Actual Win-Rate per score decile."""
    scores = [(t[score_col] or 0, t["was_profitable"] or 0) for t in trades]
    scores.sort(key=lambda x: x[0])

    n = len(scores)
    if n < 10:
        return {}

    decile_size = n // 10
    results = {}
    for i in range(10):
        start = i * decile_size
        end = (i + 1) * decile_size if i < 9 else n
        decile = scores[start:end]
        avg_score = np.mean([s[0] for s in decile])
        actual_wr = np.mean([s[1] for s in decile]) * 100
        results[f"D{i+1}"] = {
            "avg_score": round(float(avg_score), 2),
            "actual_win_rate": round(float(actual_wr), 1),
            "count": len(decile),
        }

    # Spearman rank correlation (monotonicity) — no scipy needed
    decile_scores = np.array([results[f"D{i+1}"]["avg_score"] for i in range(10)])
    decile_wr = np.array([results[f"D{i+1}"]["actual_win_rate"] for i in range(10)])
    rho, _ = _spearman_r(decile_scores, decile_wr)
    results["spearman_r"] = round(rho, 3)

    return results


def analyze_sector_performance(trades, sector_map):
    """Win-Rate per Sektor."""
    sector_stats = defaultdict(lambda: {"wins": 0, "total": 0, "pnl_sum": 0})

    for t in trades:
        sector = sector_map.get(t["symbol"], "Unknown")
        sector_stats[sector]["total"] += 1
        sector_stats[sector]["wins"] += t["was_profitable"] or 0
        sector_stats[sector]["pnl_sum"] += t["pnl_pct"] or 0

    results = {}
    for sector, stats in sorted(sector_stats.items(), key=lambda x: -x[1]["total"]):
        if stats["total"] < 10:
            continue
        results[sector] = {
            "count": stats["total"],
            "win_rate": round(stats["wins"] / stats["total"] * 100, 1),
            "avg_pnl": round(stats["pnl_sum"] / stats["total"], 2),
        }
    return results


def analyze_regime_performance(trades):
    """Win-Rate per VIX-Regime."""
    regime_stats = defaultdict(lambda: {"wins": 0, "total": 0, "pnl_sum": 0})

    for t in trades:
        regime = t["vix_regime"] or "unknown"
        regime_stats[regime]["total"] += 1
        regime_stats[regime]["wins"] += t["was_profitable"] or 0
        regime_stats[regime]["pnl_sum"] += t["pnl_pct"] or 0

    results = {}
    for regime, stats in sorted(regime_stats.items(), key=lambda x: -x[1]["total"]):
        results[regime] = {
            "count": stats["total"],
            "win_rate": round(stats["wins"] / stats["total"] * 100, 1),
            "avg_pnl": round(stats["pnl_sum"] / stats["total"], 2),
        }
    return results


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    conn = sqlite3.connect(OUTCOMES_DB)
    sector_map = get_sector_map(TRADES_DB)

    summary = {}

    for strategy, score_col in STRATEGY_SCORE_COLS.items():
        print(f"\n{'='*60}")
        print(f"  Analyzing: {strategy.upper()}")
        print(f"{'='*60}")

        trades = get_strategy_trades(conn, strategy, score_col)
        n = len(trades)
        print(f"  Trades: {n}")

        if n < 30:
            print(f"  SKIP: too few trades ({n})")
            summary[strategy] = {"count": n, "status": "SKIPPED"}
            continue

        # 1. Win-Rate by Score Decile
        deciles = analyze_win_rate_by_decile(trades)
        print(f"\n  Score Deciles:")
        for label, stats in deciles.items():
            print(f"    {label} [{stats['score_range']:>13s}]: n={stats['count']:>5}, WR={stats['win_rate']:>5.1f}%, PnL={stats['avg_pnl']:>7.2f}%")

        # 2. Component Importance
        importance = analyze_component_importance(trades)
        print(f"\n  Top 5 Components (by |correlation|):")
        for i, (comp, corr) in enumerate(importance.items()):
            if i >= 5:
                break
            direction = "+" if corr > 0 else "-"
            print(f"    {comp:>25s}: {direction}{abs(corr):.4f}")

        # 3. Score Calibration
        calibration = analyze_score_calibration(trades)
        spearman = calibration.get("spearman_r", 0)
        print(f"\n  Score Calibration (Spearman r): {spearman:.3f}")
        print(f"    D1 (worst scores):  WR={calibration.get('D1', {}).get('actual_win_rate', 'N/A')}%")
        print(f"    D10 (best scores):  WR={calibration.get('D10', {}).get('actual_win_rate', 'N/A')}%")

        # 4. Sector Performance
        sectors = analyze_sector_performance(trades, sector_map)
        print(f"\n  Sector Performance (top 5):")
        for i, (sector, stats) in enumerate(sectors.items()):
            if i >= 5:
                break
            print(f"    {sector:>25s}: n={stats['count']:>4}, WR={stats['win_rate']:>5.1f}%, PnL={stats['avg_pnl']:>7.2f}%")

        # 5. Regime Performance
        regimes = analyze_regime_performance(trades)
        print(f"\n  Regime Performance:")
        for regime, stats in regimes.items():
            print(f"    {regime:>10s}: n={stats['count']:>5}, WR={stats['win_rate']:>5.1f}%, PnL={stats['avg_pnl']:>7.2f}%")

        # Save per-strategy baseline
        baseline = {
            "strategy": strategy,
            "total_trades": n,
            "overall_win_rate": round(sum(1 for t in trades if t["was_profitable"]) / n * 100, 1),
            "overall_avg_pnl": round(float(np.mean([t["pnl_pct"] or 0 for t in trades])), 2),
            "score_deciles": deciles,
            "component_importance": importance,
            "score_calibration": calibration,
            "sector_performance": sectors,
            "regime_performance": regimes,
        }

        output_path = OUTPUT_DIR / f"baseline_{strategy}.json"
        with open(output_path, "w") as f:
            json.dump(baseline, f, indent=2)
        print(f"\n  Saved: {output_path}")

        summary[strategy] = {
            "count": n,
            "win_rate": baseline["overall_win_rate"],
            "avg_pnl": baseline["overall_avg_pnl"],
            "spearman_r": spearman,
            "top_component": list(importance.keys())[0] if importance else None,
            "best_regime": max(regimes.items(), key=lambda x: x[1]["win_rate"])[0] if regimes else None,
            "worst_regime": min(regimes.items(), key=lambda x: x[1]["win_rate"])[0] if regimes else None,
        }

    conn.close()

    # Save summary
    summary_path = OUTPUT_DIR / "baseline_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    for strategy, stats in summary.items():
        print(f"  {strategy:>15s}: n={stats.get('count', 0):>5}, "
              f"WR={stats.get('win_rate', 'N/A')}%, "
              f"Spearman={stats.get('spearman_r', 'N/A')}, "
              f"Top={stats.get('top_component', 'N/A')}")

    print(f"\nAll baselines saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
