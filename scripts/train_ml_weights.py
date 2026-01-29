#!/usr/bin/env python3
"""
OptionPlay - ML-Based Component Weight Training
================================================

Trains optimized component weights using machine learning:
- Correlation analysis for baseline
- Feature importance from ensemble methods
- Cross-validation across market phases
- Per-strategy and per-regime optimization

Usage:
    # Standard training
    python scripts/train_ml_weights.py

    # With regime-specific weights
    python scripts/train_ml_weights.py --enable-regime-weights

    # Verbose output
    python scripts/train_ml_weights.py -v

    # Custom output path
    python scripts/train_ml_weights.py --output ~/models/weights.json

Examples:
    # Full training with all features
    python scripts/train_ml_weights.py --enable-regime-weights -v

    # Quick analysis without regime segmentation
    python scripts/train_ml_weights.py --no-regime-weights
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.backtesting import TradeTracker
from src.backtesting.ml_weight_optimizer import (
    MLWeightOptimizer,
    OptimizationMethod,
    OptimizationResult,
    WeightedScorer,
    STRATEGY_COMPONENTS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA LOADING
# =============================================================================

def load_trades_from_tracker(tracker: TradeTracker) -> List[Dict[str, Any]]:
    """Load all closed trades from TradeTracker"""
    trades = []

    # Try export_for_training first (includes backtested trades)
    exported = tracker.export_for_training()
    if exported:
        for trade in exported:
            # Handle both dict and object formats
            if isinstance(trade, dict):
                trade_dict = trade.copy()
            else:
                trade_dict = {
                    "id": getattr(trade, 'id', len(trades)),
                    "symbol": getattr(trade, 'symbol', 'UNKNOWN'),
                    "strategy": getattr(trade, 'strategy', 'pullback'),
                    "signal_date": getattr(trade, 'signal_date', None),
                    "signal_score": getattr(trade, 'signal_score', 0),
                    "score_breakdown": getattr(trade, 'score_breakdown', {}),
                    "outcome": getattr(trade, 'outcome', ''),
                    "pnl_percent": getattr(trade, 'pnl_percent', 0),
                    "pnl_amount": getattr(trade, 'pnl_amount', 0),
                    "holding_days": getattr(trade, 'holding_days', 0),
                    "vix_at_signal": getattr(trade, 'vix_at_signal', None),
                    "entry_price": getattr(trade, 'entry_price', 0),
                    "exit_price": getattr(trade, 'exit_price', 0),
                }

            # Normalize outcome
            outcome = trade_dict.get("outcome", "")
            if hasattr(outcome, 'value'):
                outcome = outcome.value
            trade_dict["outcome"] = str(outcome).upper()

            trades.append(trade_dict)

    return trades


def load_trades_from_json(filepath: str) -> List[Dict[str, Any]]:
    """Load trades from JSON file (from backtest import)"""
    import json

    with open(filepath, 'r') as f:
        data = json.load(f)

    trades = data.get("trades", [])

    # Normalize outcome field
    for t in trades:
        outcome = t.get("outcome", "")
        t["outcome"] = str(outcome).upper()

    return trades


def generate_synthetic_trades(n_trades: int = 500) -> List[Dict[str, Any]]:
    """
    Generate synthetic trades for testing when no real data available.

    This creates realistic-looking trade data with score breakdowns
    that have some predictive signal built in.
    """
    import random
    from datetime import date, timedelta

    trades = []
    strategies = ["pullback", "bounce", "ath_breakout", "earnings_dip"]

    base_date = date.today() - timedelta(days=365 * 2)

    for i in range(n_trades):
        strategy = random.choice(strategies)
        components = STRATEGY_COMPONENTS.get(strategy, [])

        # Generate score breakdown with some signal
        # Higher scores = slightly higher win probability
        breakdown = {}
        total_score = 0

        for comp in components:
            # Random score 0-2 for each component
            score = random.uniform(0, 2)
            breakdown[comp] = score
            total_score += score

        # Win probability increases with score
        base_win_prob = 0.45
        score_bonus = (total_score - 5) * 0.03  # +3% win rate per point above 5
        win_prob = min(0.70, max(0.30, base_win_prob + score_bonus))

        is_winner = random.random() < win_prob

        if is_winner:
            pnl_pct = random.uniform(5, 50)
        else:
            pnl_pct = random.uniform(-100, -10)

        # Random VIX
        vix = random.gauss(18, 5)
        vix = max(10, min(40, vix))

        trade_date = base_date + timedelta(days=random.randint(0, 700))

        trades.append({
            "id": i,
            "symbol": f"SYM{i % 50}",
            "strategy": strategy,
            "signal_date": trade_date,
            "signal_score": total_score,
            "score_breakdown": breakdown,
            "outcome": "WIN" if is_winner else "LOSS",
            "pnl_percent": pnl_pct,
            "pnl_amount": pnl_pct * 10,  # Simplified
            "holding_days": random.randint(5, 45),
            "vix_at_signal": vix,
            "entry_price": random.uniform(50, 200),
            "exit_price": random.uniform(50, 200),
        })

    return trades


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def print_header():
    """Print script header"""
    print()
    print("=" * 70)
    print("  OPTIONPLAY ML WEIGHT OPTIMIZATION")
    print("=" * 70)
    print()


def print_data_stats(trades: List[Dict], real_data: bool):
    """Print data statistics"""
    print("  Data Statistics:")
    print(f"    Total Trades:    {len(trades):,}")
    print(f"    Data Source:     {'Real trades' if real_data else 'Synthetic (demo)'}")

    # Count by strategy
    by_strategy: Dict[str, int] = {}
    by_outcome: Dict[str, int] = {"WIN": 0, "LOSS": 0}

    for t in trades:
        strat = t.get("strategy", "unknown")
        by_strategy[strat] = by_strategy.get(strat, 0) + 1
        outcome = t.get("outcome", "")
        if outcome in by_outcome:
            by_outcome[outcome] += 1

    print()
    print("    By Strategy:")
    for strat, count in sorted(by_strategy.items()):
        print(f"      {strat:<15} {count:>5}")

    print()
    win_rate = by_outcome["WIN"] / len(trades) * 100 if trades else 0
    print(f"    Win Rate:        {win_rate:.1f}%")
    print()


def print_component_analysis(result: OptimizationResult, top_n: int = 15):
    """Print component analysis"""
    print("-" * 70)
    print("  COMPONENT IMPORTANCE ANALYSIS")
    print("-" * 70)
    print()
    print(f"  {'Component':<28} {'Importance':>12} {'Win Corr':>10} {'Weight':>10} {'Power':<10}")
    print("  " + "-" * 68)

    sorted_stats = sorted(
        result.component_stats.values(),
        key=lambda x: x.ensemble_importance,
        reverse=True
    )

    for stat in sorted_stats[:top_n]:
        power_icon = {
            "strong": "+++",
            "moderate": "++",
            "weak": "+",
            "none": "-",
        }.get(stat.predictive_power, "?")

        name_short = stat.name.replace("_score", "")[:25]
        print(
            f"  {name_short:<28} "
            f"{stat.ensemble_importance:>12.4f} "
            f"{stat.win_rate_correlation:>+10.3f} "
            f"{stat.recommended_weight:>10.2f} "
            f"{power_icon:<10}"
        )

    print()


def print_strategy_weights(result: OptimizationResult):
    """Print optimized weights per strategy"""
    print("-" * 70)
    print("  OPTIMIZED WEIGHTS BY STRATEGY")
    print("-" * 70)
    print()

    for strategy, config in result.strategy_weights.items():
        confidence_icon = {"high": "***", "medium": "**", "low": "*"}.get(
            config.confidence, ""
        )

        print(f"  {strategy.upper()} {confidence_icon}")
        print(f"    Samples: {config.sample_size} | Validation: {config.validation_score:.3f}")
        print()

        # Top 5 weights
        sorted_weights = sorted(
            config.weights.items(),
            key=lambda x: x[1],
            reverse=True
        )

        print(f"    {'Component':<25} {'Weight':>10} {'Normalized':>12}")
        print("    " + "-" * 48)

        for comp, weight in sorted_weights[:7]:
            norm = config.normalized_weights.get(comp, 0)
            name_short = comp.replace("_score", "")[:22]
            print(f"    {name_short:<25} {weight:>10.3f} {norm:>12.4f}")

        print()


def print_regime_weights(result: OptimizationResult):
    """Print regime-specific weights"""
    if not result.regime_weights:
        return

    print("-" * 70)
    print("  REGIME-SPECIFIC ADJUSTMENTS")
    print("-" * 70)
    print()

    for regime, strat_weights in result.regime_weights.items():
        regime_upper = regime.upper().replace("_", " ")
        print(f"  {regime_upper}:")

        for strategy, config in strat_weights.items():
            top_3 = sorted(config.weights.items(), key=lambda x: x[1], reverse=True)[:3]
            weights_str = ", ".join(
                f"{k.replace('_score', '')}={v:.2f}" for k, v in top_3
            )
            print(f"    {strategy:<12} -> {weights_str}")

        print()


def print_summary(result: OptimizationResult, filepath: str):
    """Print final summary"""
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  Optimization ID:     {result.optimization_id}")
    print(f"  Trades Analyzed:     {result.total_trades_analyzed:,}")
    print(f"  Validation Score:    {result.overall_validation_score:.4f}")
    print(f"  Improvement:         {result.improvement_vs_baseline:+.1f}% vs baseline")
    print()
    print(f"  Saved to: {filepath}")
    print("=" * 70)
    print()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Train ML-based component weights",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Training options
    parser.add_argument(
        "--method", type=str,
        choices=["correlation", "random_forest", "gradient_boosting", "ensemble"],
        default="ensemble",
        help="Optimization method (default: ensemble)"
    )
    parser.add_argument(
        "--cv-folds", type=int, default=5,
        help="Number of cross-validation folds (default: 5)"
    )
    parser.add_argument(
        "--min-samples", type=int, default=50,
        help="Minimum samples per strategy (default: 50)"
    )

    # Regime options
    parser.add_argument(
        "--enable-regime-weights", action="store_true", default=True,
        help="Train separate weights per VIX regime (default: enabled)"
    )
    parser.add_argument(
        "--no-regime-weights", action="store_true",
        help="Disable regime-specific weights"
    )

    # Data options
    parser.add_argument(
        "--use-synthetic", action="store_true",
        help="Use synthetic data for testing"
    )
    parser.add_argument(
        "--synthetic-size", type=int, default=500,
        help="Number of synthetic trades to generate (default: 500)"
    )

    # Output
    parser.add_argument(
        "--output", "-o", type=str,
        help="Output file path (default: ~/.optionplay/models/)"
    )

    # Verbosity
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Debug logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else (logging.INFO if args.verbose else logging.WARNING)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    print_header()

    # Load data
    print("  Loading trade data...")
    real_data = False

    if args.use_synthetic:
        trades = generate_synthetic_trades(args.synthetic_size)
        print(f"    Generated {len(trades)} synthetic trades")
    else:
        # First try to load from backtest JSON
        training_file = Path.home() / ".optionplay" / "training_trades.json"
        if training_file.exists():
            trades = load_trades_from_json(str(training_file))
            real_data = True
            print(f"    Loaded {len(trades)} trades from backtest results")
        else:
            tracker = TradeTracker()
            trades = load_trades_from_tracker(tracker)

        if len(trades) < args.min_samples:
            print(f"    Only {len(trades)} real trades found")
            print("    Generating synthetic data for demonstration...")
            trades = generate_synthetic_trades(args.synthetic_size)
        else:
            real_data = True

    print_data_stats(trades, real_data)

    # Determine method
    method_map = {
        "correlation": OptimizationMethod.CORRELATION,
        "random_forest": OptimizationMethod.RANDOM_FOREST,
        "gradient_boosting": OptimizationMethod.GRADIENT_BOOSTING,
        "ensemble": OptimizationMethod.ENSEMBLE,
    }
    method = method_map.get(args.method, OptimizationMethod.ENSEMBLE)

    # Enable regime weights
    enable_regime = args.enable_regime_weights and not args.no_regime_weights

    # Create optimizer
    optimizer = MLWeightOptimizer(
        method=method,
        cv_folds=args.cv_folds,
        min_samples_per_strategy=args.min_samples,
        enable_regime_weights=enable_regime,
    )

    print("-" * 70)
    print("  TRAINING IN PROGRESS...")
    print("-" * 70)
    print()
    print(f"    Method:           {method.value}")
    print(f"    CV Folds:         {args.cv_folds}")
    print(f"    Min Samples:      {args.min_samples}")
    print(f"    Regime Weights:   {'Enabled' if enable_regime else 'Disabled'}")
    print()

    # Train
    try:
        result = optimizer.train(trades)
    except Exception as e:
        print(f"  ERROR: Training failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    # Print results
    if args.verbose:
        print_component_analysis(result)

    print_strategy_weights(result)

    if args.verbose and result.regime_weights:
        print_regime_weights(result)

    # Warnings
    if result.warnings:
        print("-" * 70)
        print("  WARNINGS")
        print("-" * 70)
        for w in result.warnings:
            print(f"  ! {w}")
        print()

    # Save
    if args.output:
        filepath = args.output
    else:
        models_dir = Path.home() / ".optionplay" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        filepath = str(models_dir / f"{result.optimization_id}.json")

    saved_path = optimizer.save(result, filepath)

    # Also save as latest
    latest_path = str(Path(saved_path).parent / "weights_latest.json")
    optimizer.save(result, latest_path)

    print_summary(result, saved_path)

    # Test the scorer
    print("-" * 70)
    print("  SCORER TEST")
    print("-" * 70)
    print()

    scorer = WeightedScorer(result)

    # Test with sample score breakdowns
    test_cases = [
        {
            "strategy": "pullback",
            "breakdown": {
                "rsi_score": 2.5, "support_score": 2.0, "fibonacci_score": 1.5,
                "ma_score": 1.0, "volume_score": 0.5, "macd_score": 1.5,
            },
        },
        {
            "strategy": "bounce",
            "breakdown": {
                "rsi_score": 2.0, "support_score": 2.5, "volume_score": 1.5,
                "candlestick_score": 2.0, "macd_score": 1.0,
            },
        },
    ]

    for tc in test_cases:
        raw_score = sum(tc["breakdown"].values())
        weighted = scorer.score(tc["breakdown"], tc["strategy"])

        print(f"  {tc['strategy']:<12} Raw: {raw_score:.1f} -> Weighted: {weighted:.1f}")

    print()
    print("=" * 70)
    print("  TRAINING COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
