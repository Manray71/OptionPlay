#!/usr/bin/env python3
"""
A/B Test Comparison for Weight Variants
========================================

Compares v3.7 feature-based weights (A) vs v3.8 outcome-based weights (B)
using historical trade outcomes.

Usage:
    python scripts/compare_ab_variants.py
    python scripts/compare_ab_variants.py --strategy pullback
    python scripts/compare_ab_variants.py --symbols AAPL,MSFT,NVDA
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import yaml

import numpy as np


@dataclass
class VariantResult:
    """Results for one A/B variant."""

    variant: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_score: float
    high_score_wins: int  # Wins with score >= 7
    high_score_total: int
    high_score_win_rate: float
    score_correlation: float  # Correlation between score and win


def load_weights(config_dir: Path, variant: str) -> Dict[str, Dict[str, float]]:
    """Load weights for a specific variant."""
    if variant == "A":
        weights_file = config_dir / "trained_weights.yaml"
    else:
        weights_file = config_dir / "trained_weights_outcome_based.yaml"

    if not weights_file.exists():
        raise FileNotFoundError(f"Weights file not found: {weights_file}")

    with open(weights_file) as f:
        data = yaml.safe_load(f)

    weights = {}
    for strategy in ["pullback", "bounce", "ath_breakout", "earnings_dip"]:
        if strategy in data:
            weights[strategy] = data[strategy].get("weights", {})

    return weights


def calculate_weighted_score(
    component_scores: Dict[str, float], weights: Dict[str, float]
) -> float:
    """Calculate weighted score from component scores."""
    total = 0.0
    weight_sum = 0.0

    for component, weight in weights.items():
        # Map component names to score column names
        score_col = f"{component}_score"
        if component == "trend":
            score_col = "trend_strength_score"
        elif component == "stochastic":
            score_col = "stoch_score"
        elif component == "moving_average":
            score_col = "ma_score"

        if score_col in component_scores and component_scores[score_col] is not None:
            total += component_scores[score_col] * weight
            weight_sum += weight

    if weight_sum > 0:
        return total / weight_sum * 10  # Normalize to 0-10 scale
    return 0.0


def load_trades_with_scores(
    db_path: Path, strategy: Optional[str] = None, symbols: Optional[List[str]] = None
) -> List[Dict]:
    """Load trades that have component scores."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Note: This table doesn't have a 'strategy' column - all trades are Bull-Put-Spreads
    # The 'outcome' column uses: max_profit, partial_profit, partial_loss, max_loss
    query = """
        SELECT
            id, symbol, entry_date, outcome, pnl as pnl_dollars, was_profitable,
            rsi_score, support_score, fibonacci_score, ma_score,
            macd_score, stoch_score, trend_strength_score,
            market_context_score, momentum_score, volume_score,
            candlestick_score, keltner_score, rs_score as relative_strength_score
        FROM trade_outcomes
        WHERE rsi_score IS NOT NULL
    """

    params = []
    # Strategy filter not applicable (no strategy column in this schema)

    if symbols:
        placeholders = ",".join("?" * len(symbols))
        query += f" AND symbol IN ({placeholders})"
        params.extend(symbols)

    cursor = conn.execute(query, params)
    trades = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return trades


def evaluate_variant(trades: List[Dict], weights: Dict[str, float], variant: str) -> VariantResult:
    """Evaluate a weight variant on historical trades."""
    scores = []
    outcomes = []

    for trade in trades:
        # Get component scores
        comp_scores = {
            "rsi_score": trade.get("rsi_score"),
            "support_score": trade.get("support_score"),
            "fibonacci_score": trade.get("fibonacci_score"),
            "ma_score": trade.get("ma_score"),
            "macd_score": trade.get("macd_score"),
            "stoch_score": trade.get("stoch_score"),
            "trend_strength_score": trade.get("trend_strength_score"),
            "market_context_score": trade.get("market_context_score"),
            "momentum_score": trade.get("momentum_score"),
            "volume_score": trade.get("volume_score"),
            "candlestick_score": trade.get("candlestick_score"),
            "keltner_score": trade.get("keltner_score"),
            "relative_strength_score": trade.get("relative_strength_score"),
        }

        score = calculate_weighted_score(comp_scores, weights)
        scores.append(score)
        # was_profitable is 1 for WIN, 0 for LOSS
        # Or check outcome: max_profit, partial_profit = WIN; partial_loss, max_loss = LOSS
        is_win = trade.get("was_profitable", 0) == 1 or trade["outcome"] in (
            "max_profit",
            "partial_profit",
        )
        outcomes.append(1 if is_win else 0)

    scores = np.array(scores)
    outcomes = np.array(outcomes)

    # Basic stats
    total_trades = len(trades)
    wins = int(outcomes.sum())
    losses = total_trades - wins
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0

    # High score analysis (score >= 7)
    high_score_mask = scores >= 7.0
    high_score_total = int(high_score_mask.sum())
    high_score_wins = int((high_score_mask & (outcomes == 1)).sum())
    high_score_win_rate = high_score_wins / high_score_total * 100 if high_score_total > 0 else 0

    # Score-Outcome correlation
    if len(scores) > 1:
        correlation = np.corrcoef(scores, outcomes)[0, 1]
    else:
        correlation = 0.0

    return VariantResult(
        variant=variant,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        avg_score=float(scores.mean()),
        high_score_wins=high_score_wins,
        high_score_total=high_score_total,
        high_score_win_rate=high_score_win_rate,
        score_correlation=correlation,
    )


def compare_variants(
    strategy: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    db_path: Optional[Path] = None,
    config_dir: Optional[Path] = None,
) -> Tuple[VariantResult, VariantResult, Dict, Dict, List[Dict]]:
    """Compare A and B variants."""
    if db_path is None:
        db_path = Path.home() / "OptionPlay" / "data" / "outcomes.db"
    if config_dir is None:
        config_dir = Path.home() / "OptionPlay" / "config"

    # Load weights for both variants
    weights_a = load_weights(config_dir, "A")
    weights_b = load_weights(config_dir, "B")

    # Load trades
    trades = load_trades_with_scores(db_path, strategy, symbols)

    if not trades:
        raise ValueError("No trades with component scores found")

    # For comparison, use pullback weights as default (most trades)
    strategy_key = strategy or "pullback"
    w_a = weights_a.get(strategy_key, {})
    w_b = weights_b.get(strategy_key, {})

    result_a = evaluate_variant(trades, w_a, "A")
    result_b = evaluate_variant(trades, w_b, "B")

    # Score bucket analysis
    buckets_a = analyze_score_buckets(trades, w_a, "A")
    buckets_b = analyze_score_buckets(trades, w_b, "B")

    return result_a, result_b, buckets_a, buckets_b, trades


def analyze_score_buckets(
    trades: List[Dict], weights: Dict[str, float], variant: str
) -> Dict[str, Tuple[int, int, float]]:
    """Analyze win rate by score bucket."""
    buckets = {
        "0-4": (0, 0),
        "4-5": (0, 0),
        "5-6": (0, 0),
        "6-7": (0, 0),
        "7-8": (0, 0),
        "8-9": (0, 0),
        "9+": (0, 0),
    }

    for trade in trades:
        comp_scores = {
            "rsi_score": trade.get("rsi_score"),
            "support_score": trade.get("support_score"),
            "fibonacci_score": trade.get("fibonacci_score"),
            "ma_score": trade.get("ma_score"),
            "macd_score": trade.get("macd_score"),
            "stoch_score": trade.get("stoch_score"),
            "trend_strength_score": trade.get("trend_strength_score"),
            "market_context_score": trade.get("market_context_score"),
            "momentum_score": trade.get("momentum_score"),
            "volume_score": trade.get("volume_score"),
            "candlestick_score": trade.get("candlestick_score"),
            "keltner_score": trade.get("keltner_score"),
            "relative_strength_score": trade.get("relative_strength_score"),
        }

        score = calculate_weighted_score(comp_scores, weights)
        is_win = trade.get("was_profitable", 0) == 1 or trade["outcome"] in (
            "max_profit",
            "partial_profit",
        )

        # Find bucket
        if score < 4:
            key = "0-4"
        elif score < 5:
            key = "4-5"
        elif score < 6:
            key = "5-6"
        elif score < 7:
            key = "6-7"
        elif score < 8:
            key = "7-8"
        elif score < 9:
            key = "8-9"
        else:
            key = "9+"

        total, wins = buckets[key]
        buckets[key] = (total + 1, wins + (1 if is_win else 0))

    # Calculate win rates
    result = {}
    for key, (total, wins) in buckets.items():
        wr = wins / total * 100 if total > 0 else 0
        result[key] = (total, wins, wr)

    return result


def print_comparison(
    result_a: VariantResult, result_b: VariantResult, buckets_a: Dict = None, buckets_b: Dict = None
) -> None:
    """Print comparison table."""
    print("\n" + "=" * 70)
    print("A/B TEST COMPARISON: Feature-Based (A) vs Outcome-Based (B)")
    print("=" * 70)

    headers = ["Metric", "Variant A (v3.7)", "Variant B (v3.8)", "Difference"]
    print(f"\n{headers[0]:<30} {headers[1]:>15} {headers[2]:>15} {headers[3]:>12}")
    print("-" * 75)

    def row(label: str, a: float, b: float, fmt: str = ".1f", suffix: str = ""):
        diff = b - a
        sign = "+" if diff >= 0 else ""
        print(
            f"{label:<30} {a:>14{fmt}}{suffix} {b:>14{fmt}}{suffix} {sign}{diff:>10{fmt}}{suffix}"
        )

    row("Total Trades", result_a.total_trades, result_b.total_trades, "d")
    row("Win Rate", result_a.win_rate, result_b.win_rate, ".1f", "%")
    row("Average Score", result_a.avg_score, result_b.avg_score, ".2f")
    row("Score-Win Correlation", result_a.score_correlation, result_b.score_correlation, ".3f")
    print("-" * 75)
    row("High-Score Trades (>=7)", result_a.high_score_total, result_b.high_score_total, "d")
    row(
        "High-Score Win Rate",
        result_a.high_score_win_rate,
        result_b.high_score_win_rate,
        ".1f",
        "%",
    )

    # Score bucket analysis
    if buckets_a and buckets_b:
        print("\n" + "-" * 75)
        print("SCORE BUCKET ANALYSIS:")
        print(
            f"{'Bucket':<10} {'A: Trades':>10} {'A: WR%':>8} {'B: Trades':>10} {'B: WR%':>8} {'WR Diff':>8}"
        )
        print("-" * 60)
        for bucket in ["0-4", "4-5", "5-6", "6-7", "7-8", "8-9", "9+"]:
            a_total, a_wins, a_wr = buckets_a.get(bucket, (0, 0, 0))
            b_total, b_wins, b_wr = buckets_b.get(bucket, (0, 0, 0))
            diff = b_wr - a_wr
            sign = "+" if diff >= 0 else ""
            print(
                f"{bucket:<10} {a_total:>10} {a_wr:>7.1f}% {b_total:>10} {b_wr:>7.1f}% {sign}{diff:>6.1f}%"
            )

    print("\n" + "=" * 70)

    # Recommendation
    print("\nRECOMMENDATION:")
    if result_b.score_correlation > result_a.score_correlation:
        corr_diff = result_b.score_correlation - result_a.score_correlation
        print(f"  Variant B shows {corr_diff:.3f} higher score-outcome correlation")

    if result_b.high_score_win_rate > result_a.high_score_win_rate:
        wr_diff = result_b.high_score_win_rate - result_a.high_score_win_rate
        print(f"  Variant B shows {wr_diff:.1f}% higher win rate for high-score trades")

    # Winner
    b_wins = 0
    if result_b.score_correlation > result_a.score_correlation:
        b_wins += 1
    if result_b.high_score_win_rate > result_a.high_score_win_rate:
        b_wins += 1

    if b_wins >= 2:
        print("\n  --> Recommend switching to Variant B (outcome-based weights)")
    elif b_wins == 1:
        print("\n  --> Results mixed, suggest more testing before switching")
    else:
        print("\n  --> Keep Variant A (feature-based weights)")


def main():
    parser = argparse.ArgumentParser(description="Compare A/B test variants")
    parser.add_argument("--strategy", type=str, help="Filter by strategy")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    parser.add_argument("--db", type=str, help="Path to outcomes.db")
    parser.add_argument("--config", type=str, help="Path to config directory")

    args = parser.parse_args()

    symbols = args.symbols.split(",") if args.symbols else None
    db_path = Path(args.db) if args.db else None
    config_dir = Path(args.config) if args.config else None

    try:
        result_a, result_b, buckets_a, buckets_b, trades = compare_variants(
            strategy=args.strategy,
            symbols=symbols,
            db_path=db_path,
            config_dir=config_dir,
        )
        print_comparison(result_a, result_b, buckets_a, buckets_b)
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
