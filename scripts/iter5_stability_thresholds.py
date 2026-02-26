#!/usr/bin/env python3
"""
Iteration 5: Stability-Threshold-Optimierung.

Findet optimale Stability-Schwellen pro Strategy × Regime × Sector.
Ziel: Stability-Schwelle die Win-Rate >= 65% sicherstellt.

Fallback-Kaskade:
  1. Strategy × Regime × Sector   (wenn >= 30 Trades)
  2. Strategy × Regime            (wenn >= 50 Trades)
  3. Strategy global              (wenn >= 100 Trades)
  4. Default = 70

Output: trained_weights_v3_stability_<strategy>.json + summary
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─── Config ────────────────────────────────────────────
OUTCOMES_DB = os.path.expanduser("~/.optionplay/outcomes.db")
TRADES_DB = os.path.expanduser("~/.optionplay/trades.db")
OUTPUT_DIR = Path(__file__).parent.parent / "data_inventory"

STRATEGIES = ["pullback", "bounce", "ath_breakout"]
REGIMES = ["low", "medium", "high", "extreme"]

# Target minimum win rate for threshold selection
TARGET_MIN_WR = 0.65
# Default stability threshold
DEFAULT_THRESHOLD = 70


def load_sector_map():
    """Load symbol → sector mapping."""
    conn = sqlite3.connect(TRADES_DB)
    rows = conn.execute("SELECT symbol, sector FROM symbol_fundamentals").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows if r[1]}


def load_stability_scores():
    """Load symbol → stability_score mapping."""
    conn = sqlite3.connect(TRADES_DB)
    rows = conn.execute(
        "SELECT symbol, stability_score FROM symbol_fundamentals WHERE stability_score IS NOT NULL"
    ).fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def load_trades():
    """Load all trades with strategy assignment."""
    conn = sqlite3.connect(OUTCOMES_DB)
    cols = [
        "symbol",
        "was_profitable",
        "pnl_pct",
        "vix_regime",
        "pullback_score",
        "bounce_score",
        "ath_breakout_score",
    ]
    query = f"SELECT {', '.join(cols)} FROM trade_outcomes WHERE pullback_score IS NOT NULL ORDER BY entry_date"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def assign_strategy(trade):
    """Determine which strategy a trade belongs to."""
    scores = {
        "pullback": trade.get("pullback_score") or 0,
        "bounce": trade.get("bounce_score") or 0,
        "ath_breakout": trade.get("ath_breakout_score") or 0,
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def find_optimal_threshold(trades, stability_scores, min_target_wr=TARGET_MIN_WR):
    """
    Binary search for the optimal stability threshold.

    Finds the lowest threshold where:
    - Win rate of trades with stability >= threshold is >= target
    - OR all trades are above threshold (use lowest that gives best WR)

    Returns: (threshold, win_rate, n_trades_above)
    """
    # Enrich trades with stability
    enriched = []
    for t in trades:
        stab = stability_scores.get(t["symbol"])
        if stab is not None:
            enriched.append(
                {
                    "stable": stab,
                    "won": t["was_profitable"] or 0,
                    "pnl": t["pnl_pct"] or 0,
                }
            )

    if len(enriched) < 20:
        return DEFAULT_THRESHOLD, 0, 0

    # Test thresholds from 40 to 95 in steps of 5
    thresholds = list(range(40, 96, 5))
    best_threshold = DEFAULT_THRESHOLD
    best_score = -999

    for thresh in thresholds:
        above = [t for t in enriched if t["stable"] >= thresh]
        if len(above) < 10:
            continue

        wr = sum(t["won"] for t in above) / len(above)
        avg_pnl = np.mean([t["pnl"] for t in above])
        n_above = len(above)
        coverage = n_above / len(enriched)

        # Score: balance win rate, PnL, and coverage
        # We want high WR and reasonable coverage (not too restrictive)
        score = (
            0.40 * wr  # Maximize win rate
            + 0.30 * (avg_pnl / 100.0)  # Maximize PnL (normalized)
            + 0.20 * coverage  # Don't be too restrictive
            + 0.10 * (1.0 if wr >= min_target_wr else -0.5)  # Bonus for meeting target
        )

        if score > best_score:
            best_score = score
            best_threshold = thresh

    # Get metrics at best threshold
    above = [t for t in enriched if t["stable"] >= best_threshold]
    if above:
        final_wr = sum(t["won"] for t in above) / len(above)
        return best_threshold, round(final_wr * 100, 1), len(above)

    return DEFAULT_THRESHOLD, 0, 0


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    sector_map = load_sector_map()
    stability_scores = load_stability_scores()
    all_trades = load_trades()

    # Assign strategy to each trade
    for t in all_trades:
        t["strategy"] = assign_strategy(t)
        t["sector"] = sector_map.get(t["symbol"], "Unknown")

    print(f"Loaded {len(all_trades)} trades, {len(stability_scores)} stability scores")

    summary = {}

    for strategy in STRATEGIES:
        print(f"\n{'='*60}")
        print(f"  {strategy.upper()} — Stability Threshold Optimization")
        print(f"{'='*60}")

        strategy_trades = [t for t in all_trades if t["strategy"] == strategy]
        print(f"  Total trades: {len(strategy_trades)}")

        # Level 1: Strategy global threshold
        global_thresh, global_wr, global_n = find_optimal_threshold(
            strategy_trades, stability_scores
        )
        print(f"\n  Global threshold: {global_thresh} (WR={global_wr}%, n={global_n})")

        # Level 2: Strategy × Regime thresholds
        regime_thresholds = {}
        print(f"\n  Regime thresholds:")
        for regime in REGIMES:
            regime_trades = [t for t in strategy_trades if t["vix_regime"] == regime]
            if len(regime_trades) >= 50:
                thresh, wr, n = find_optimal_threshold(regime_trades, stability_scores)
                regime_thresholds[regime] = {"threshold": thresh, "win_rate": wr, "n_trades": n}
                print(f"    {regime:>8s}: thresh={thresh:>3}, WR={wr:>5.1f}%, n={n:>5}")
            else:
                regime_thresholds[regime] = {
                    "threshold": global_thresh,
                    "win_rate": global_wr,
                    "n_trades": len(regime_trades),
                    "source": "fallback_global",
                }
                print(f"    {regime:>8s}: FALLBACK → global ({len(regime_trades)} < 50 trades)")

        # Level 3: Strategy × Regime × Sector thresholds
        sector_thresholds = {}
        print(f"\n  Sector × Regime thresholds (significant deviations):")
        sectors = sorted(set(t["sector"] for t in strategy_trades))

        for sector in sectors:
            sector_thresholds[sector] = {}
            sector_trades = [t for t in strategy_trades if t["sector"] == sector]

            if len(sector_trades) < 30:
                continue

            for regime in REGIMES:
                regime_sector_trades = [t for t in sector_trades if t["vix_regime"] == regime]
                if len(regime_sector_trades) >= 30:
                    thresh, wr, n = find_optimal_threshold(regime_sector_trades, stability_scores)
                    # Only report if different from regime default
                    regime_default = regime_thresholds.get(regime, {}).get(
                        "threshold", global_thresh
                    )
                    if abs(thresh - regime_default) >= 5:
                        sector_thresholds[sector][regime] = {
                            "threshold": thresh,
                            "win_rate": wr,
                            "n_trades": n,
                        }
                        delta = thresh - regime_default
                        print(
                            f"    {sector:>25s}/{regime:<8s}: {thresh:>3} "
                            f"(vs regime {regime_default}, Δ={delta:+d}), WR={wr:.1f}%, n={n}"
                        )

        # Save
        output = {
            "strategy": strategy,
            "n_trades": len(strategy_trades),
            "global_threshold": global_thresh,
            "global_win_rate": global_wr,
            "regime_thresholds": regime_thresholds,
            "sector_regime_thresholds": {k: v for k, v in sector_thresholds.items() if v},
        }

        output_path = OUTPUT_DIR / f"trained_weights_v3_stability_{strategy}.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n  Saved: {output_path}")

        summary[strategy] = {
            "global_threshold": global_thresh,
            "regime_thresholds": {r: d["threshold"] for r, d in regime_thresholds.items()},
            "n_sector_overrides": sum(len(v) for v in sector_thresholds.values()),
        }

    # Save summary
    summary_path = OUTPUT_DIR / "trained_weights_v3_stability_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  STABILITY THRESHOLD OPTIMIZATION COMPLETE")
    print(f"{'='*60}")
    for strategy, stats in summary.items():
        rt = stats["regime_thresholds"]
        print(
            f"  {strategy:>15s}: global={stats['global_threshold']}, "
            f"regime=[{rt.get('low','?')}/{rt.get('medium','?')}/{rt.get('high','?')}/{rt.get('extreme','?')}], "
            f"sector_overrides={stats['n_sector_overrides']}"
        )


if __name__ == "__main__":
    main()
