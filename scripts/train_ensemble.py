#!/usr/bin/env python3
"""
OptionPlay - Ensemble Strategy Selection Training

Trains the ensemble strategy selector using historical trade data:
- MetaLearner for symbol/regime-specific strategy selection
- Performance tracking and rotation calibration
- Cross-validation of selection methods

Usage:
    # Standard training
    python scripts/train_ensemble.py

    # With verbose output
    python scripts/train_ensemble.py -v

    # Use synthetic data for testing
    python scripts/train_ensemble.py --use-synthetic

    # Custom output path
    python scripts/train_ensemble.py --output ~/models/ensemble.json

Examples:
    # Full training from trade history
    python scripts/train_ensemble.py -v

    # Quick test with synthetic data
    python scripts/train_ensemble.py --use-synthetic --synthetic-size 300
"""

import argparse
import logging
import random
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.backtesting import TradeTracker
from src.backtesting.ensemble_selector import (
    EnsembleSelector,
    MetaLearner,
    StrategyRotationEngine,
    StrategyScore,
    SelectionMethod,
    STRATEGIES,
    create_strategy_score,
)
from src.backtesting.ml_weight_optimizer import STRATEGY_COMPONENTS

logger = logging.getLogger(__name__)


# =============================================================================
# DATA LOADING
# =============================================================================

def load_trades_from_tracker(tracker: TradeTracker) -> List[Dict[str, Any]]:
    """Load all closed trades from TradeTracker"""
    trades = []

    exported = tracker.export_for_training()
    if exported:
        for trade in exported:
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
    Generate synthetic trades for testing.

    Creates realistic trade data with:
    - Multiple strategies with varying performance
    - Symbol-specific patterns
    - Regime-dependent outcomes
    """
    trades = []
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "CRM", "ORCL",
               "JPM", "V", "MA", "BAC", "GS", "UNH", "JNJ", "PFE", "ABBV", "MRK"]

    # Symbol-specific strategy preferences (for realistic patterns)
    symbol_preferences = {}
    for sym in symbols:
        prefs = {s: random.uniform(0.4, 0.6) for s in STRATEGIES}
        # Give each symbol a "best" strategy
        best = random.choice(STRATEGIES)
        prefs[best] = random.uniform(0.55, 0.70)
        symbol_preferences[sym] = prefs

    base_date = date.today() - timedelta(days=365 * 2)

    for i in range(n_trades):
        symbol = random.choice(symbols)
        strategy = random.choice(STRATEGIES)

        # Get win probability based on symbol preference
        base_win_prob = symbol_preferences[symbol].get(strategy, 0.5)

        # VIX affects win probability
        vix = random.gauss(18, 6)
        vix = max(10, min(45, vix))

        # Regime adjustment
        if vix < 15:
            regime = "low_vol"
            if strategy == "ath_breakout":
                base_win_prob += 0.05
        elif vix < 20:
            regime = "normal"
        elif vix < 30:
            regime = "elevated"
            if strategy in ["pullback", "bounce"]:
                base_win_prob += 0.05
            else:
                base_win_prob -= 0.05
        else:
            regime = "high_vol"
            if strategy == "pullback":
                base_win_prob += 0.05
            else:
                base_win_prob -= 0.10

        # Score affects outcome
        components = STRATEGY_COMPONENTS.get(strategy, STRATEGY_COMPONENTS["pullback"])
        breakdown = {}
        total_score = 0

        for comp in components:
            score = random.uniform(0, 2)
            breakdown[comp] = score
            total_score += score

        # Higher score = better chance
        score_bonus = (total_score - 5) * 0.02
        win_prob = min(0.75, max(0.25, base_win_prob + score_bonus))

        is_winner = random.random() < win_prob

        if is_winner:
            pnl_pct = random.uniform(10, 60)
        else:
            pnl_pct = random.uniform(-100, -15)

        trade_date = base_date + timedelta(days=random.randint(0, 700))

        trades.append({
            "id": i,
            "symbol": symbol,
            "strategy": strategy,
            "signal_date": trade_date,
            "signal_score": total_score,
            "score_breakdown": breakdown,
            "outcome": "WIN" if is_winner else "LOSS",
            "pnl_percent": pnl_pct,
            "pnl_amount": pnl_pct * 10,
            "holding_days": random.randint(5, 45),
            "vix_at_signal": vix,
            "regime": regime,
        })

    return trades


# =============================================================================
# TRAINING
# =============================================================================

def train_ensemble(
    trades: List[Dict[str, Any]],
    method: SelectionMethod = SelectionMethod.META_LEARNER,
    verbose: bool = False,
) -> Tuple[EnsembleSelector, Dict[str, Any]]:
    """
    Train ensemble selector from historical trades.

    Args:
        trades: List of historical trades
        method: Selection method to use
        verbose: Print detailed output

    Returns:
        Tuple of (trained EnsembleSelector, training stats)
    """
    selector = EnsembleSelector(
        method=method,
        enable_rotation=True,
        min_score_threshold=4.0,
    )

    stats = {
        "total_trades": len(trades),
        "by_strategy": defaultdict(int),
        "by_symbol": defaultdict(int),
        "by_regime": defaultdict(int),
        "win_rates": defaultdict(lambda: {"wins": 0, "total": 0}),
    }

    # Sort by date for proper temporal learning
    sorted_trades = sorted(trades, key=lambda t: t.get("signal_date") or date.today())

    for trade in sorted_trades:
        strategy = trade.get("strategy", "pullback")
        symbol = trade.get("symbol", "UNKNOWN")
        outcome = trade.get("outcome", "") == "WIN"
        pnl = trade.get("pnl_percent", 0)
        signal_date = trade.get("signal_date")

        if isinstance(signal_date, str):
            try:
                signal_date = date.fromisoformat(signal_date[:10])
            except ValueError:
                signal_date = date.today()
        elif not isinstance(signal_date, date):
            signal_date = date.today()

        # Get regime from VIX
        vix = trade.get("vix_at_signal")
        regime = trade.get("regime")
        if not regime and vix:
            if vix < 15:
                regime = "low_vol"
            elif vix < 20:
                regime = "normal"
            elif vix < 30:
                regime = "elevated"
            else:
                regime = "high_vol"

        # Update selector with this trade result
        selector.update_with_result(
            symbol=symbol,
            strategy=strategy,
            outcome=outcome,
            pnl_percent=pnl,
            signal_date=signal_date,
            regime=regime,
        )

        # Track stats
        stats["by_strategy"][strategy] += 1
        stats["by_symbol"][symbol] += 1
        stats["by_regime"][regime or "unknown"] += 1
        stats["win_rates"][strategy]["total"] += 1
        if outcome:
            stats["win_rates"][strategy]["wins"] += 1

    # Calculate final win rates
    for strat in stats["win_rates"]:
        total = stats["win_rates"][strat]["total"]
        wins = stats["win_rates"][strat]["wins"]
        stats["win_rates"][strat]["rate"] = wins / total if total > 0 else 0

    return selector, stats


def evaluate_selector(
    selector: EnsembleSelector,
    test_trades: List[Dict[str, Any]],
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate selector on test data.

    Simulates what would have happened if we used the selector's
    recommendations on the test trades.
    """
    results = {
        "total": 0,
        "correct_selections": 0,
        "by_method": defaultdict(lambda: {"correct": 0, "total": 0}),
        "by_regime": defaultdict(lambda: {"correct": 0, "total": 0}),
    }

    # Group test trades by symbol and date
    trade_groups = defaultdict(list)
    for t in test_trades:
        key = (t.get("symbol"), str(t.get("signal_date")))
        trade_groups[key].append(t)

    for (symbol, signal_date), trades in trade_groups.items():
        if len(trades) < 2:
            continue  # Need multiple strategies to compare

        # Create strategy scores from trades
        strategy_scores = {}
        for t in trades:
            strat = t.get("strategy")
            if not strat:
                continue

            breakdown = t.get("score_breakdown", {})
            if isinstance(breakdown, str):
                import json
                try:
                    breakdown = json.loads(breakdown)
                except:
                    breakdown = {}

            score = create_strategy_score(
                strategy=strat,
                raw_score=t.get("signal_score", 0),
                breakdown=breakdown,
            )
            strategy_scores[strat] = score

        if not strategy_scores:
            continue

        # Get recommendation
        vix = trades[0].get("vix_at_signal")
        rec = selector.get_recommendation(symbol, strategy_scores, vix=vix)

        # Check if recommended strategy had best outcome
        best_actual = max(trades, key=lambda t: t.get("pnl_percent", -1000))
        selected_trade = next((t for t in trades if t.get("strategy") == rec.recommended_strategy), None)

        results["total"] += 1

        if selected_trade:
            # Did we pick a winner?
            if selected_trade.get("outcome") == "WIN":
                results["correct_selections"] += 1
                results["by_method"][rec.selection_method.value]["correct"] += 1

        results["by_method"][rec.selection_method.value]["total"] += 1

        regime = rec.regime or "unknown"
        results["by_regime"][regime]["total"] += 1
        if selected_trade and selected_trade.get("outcome") == "WIN":
            results["by_regime"][regime]["correct"] += 1

    # Calculate accuracy
    if results["total"] > 0:
        results["accuracy"] = results["correct_selections"] / results["total"]
    else:
        results["accuracy"] = 0

    return results


# =============================================================================
# OUTPUT
# =============================================================================

def print_header():
    print()
    print("=" * 70)
    print("  OPTIONPLAY ENSEMBLE STRATEGY SELECTOR TRAINING")
    print("=" * 70)
    print()


def print_data_stats(trades: List[Dict], real_data: bool):
    print("  Data Statistics:")
    print(f"    Total Trades:  {len(trades):,}")
    print(f"    Data Source:   {'Real trades' if real_data else 'Synthetic (demo)'}")

    # Count by strategy
    by_strategy = defaultdict(int)
    by_outcome = {"WIN": 0, "LOSS": 0}

    for t in trades:
        by_strategy[t.get("strategy", "unknown")] += 1
        outcome = t.get("outcome", "")
        if outcome in by_outcome:
            by_outcome[outcome] += 1

    print()
    print("    By Strategy:")
    for strat, count in sorted(by_strategy.items()):
        print(f"      {strat:<15} {count:>5}")

    total = len(trades)
    win_rate = by_outcome["WIN"] / total * 100 if total else 0
    print()
    print(f"    Win Rate:      {win_rate:.1f}%")
    print()


def print_training_results(stats: Dict[str, Any]):
    print("-" * 70)
    print("  TRAINING RESULTS")
    print("-" * 70)
    print()

    print("  Strategy Win Rates:")
    for strat in STRATEGIES:
        wr_data = stats["win_rates"].get(strat, {})
        rate = wr_data.get("rate", 0)
        total = wr_data.get("total", 0)
        print(f"    {strat:<15} {rate:>6.1%} ({total:>4} trades)")

    print()
    print("  Regime Distribution:")
    for regime, count in sorted(stats["by_regime"].items()):
        pct = count / stats["total_trades"] * 100 if stats["total_trades"] else 0
        print(f"    {regime:<15} {count:>5} ({pct:>5.1f}%)")

    print()


def print_evaluation_results(eval_results: Dict[str, Any]):
    print("-" * 70)
    print("  EVALUATION RESULTS")
    print("-" * 70)
    print()

    print(f"  Selection Accuracy: {eval_results.get('accuracy', 0):.1%}")
    print(f"  Total Selections:   {eval_results.get('total', 0)}")
    print()

    print("  By Regime:")
    for regime, data in sorted(eval_results.get("by_regime", {}).items()):
        total = data.get("total", 0)
        correct = data.get("correct", 0)
        rate = correct / total if total > 0 else 0
        print(f"    {regime:<15} {rate:>6.1%} ({correct}/{total})")

    print()


def print_symbol_insights(selector: EnsembleSelector, top_n: int = 10):
    print("-" * 70)
    print("  TOP SYMBOL INSIGHTS")
    print("-" * 70)
    print()

    # Get symbols with most data
    ml = selector._meta_learner
    symbols_by_samples = []

    for symbol, perf in ml._symbol_performance.items():
        total_samples = sum(perf.strategy_sample_sizes.values())
        if total_samples > 0:
            symbols_by_samples.append((symbol, total_samples, perf))

    symbols_by_samples.sort(key=lambda x: -x[1])

    print(f"  {'Symbol':<8} {'Best Strategy':<15} {'Confidence':>10} {'Samples':>8}")
    print("  " + "-" * 45)

    for symbol, samples, perf in symbols_by_samples[:top_n]:
        best = perf.best_strategy or "-"
        conf = perf.best_strategy_confidence
        print(f"  {symbol:<8} {best:<15} {conf:>10.0%} {samples:>8}")

    print()


def print_rotation_status(selector: EnsembleSelector):
    rotation = selector.get_rotation_status()
    if not rotation:
        return

    print("-" * 70)
    print("  ROTATION ENGINE STATUS")
    print("-" * 70)
    print()

    print(f"  Days Since Last Rotation: {rotation.get('days_since_rotation', 0)}")
    print(f"  Rotation Count:           {rotation.get('rotation_count', 0)}")
    print()

    print("  Current Strategy Preferences:")
    prefs = rotation.get("current_preferences", {})
    for strat, pref in sorted(prefs.items(), key=lambda x: -x[1]):
        bar = "█" * int(pref * 40)
        print(f"    {strat:<15} {pref:>5.1%} {bar}")

    print()

    print("  Recent Performance:")
    perf = rotation.get("recent_performance", {})
    for strat, rate in sorted(perf.items()):
        if rate is not None:
            print(f"    {strat:<15} {rate:>6.1%}")
        else:
            print(f"    {strat:<15} {'N/A':>6}")

    print()


def print_summary(filepath: str, stats: Dict[str, Any]):
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()
    print(f"  Trades Processed: {stats['total_trades']:,}")
    print(f"  Unique Symbols:   {len(stats['by_symbol'])}")
    print(f"  Saved to:         {filepath}")
    print()
    print("=" * 70)
    print()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Train ensemble strategy selector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Data options
    parser.add_argument(
        "--use-synthetic", action="store_true",
        help="Use synthetic data for testing"
    )
    parser.add_argument(
        "--synthetic-size", type=int, default=500,
        help="Number of synthetic trades (default: 500)"
    )

    # Training options
    parser.add_argument(
        "--method", type=str,
        choices=["best_score", "weighted_best", "meta_learner", "confidence_weighted", "ensemble_vote"],
        default="meta_learner",
        help="Selection method (default: meta_learner)"
    )
    parser.add_argument(
        "--test-split", type=float, default=0.2,
        help="Fraction of data for testing (default: 0.2)"
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

        if len(trades) < 50:
            print(f"    Only {len(trades)} real trades found")
            print("    Generating synthetic data for demonstration...")
            trades = generate_synthetic_trades(args.synthetic_size)
        else:
            real_data = True

    print_data_stats(trades, real_data)

    # Split data for training and testing
    random.shuffle(trades)
    split_idx = int(len(trades) * (1 - args.test_split))
    train_trades = trades[:split_idx]
    test_trades = trades[split_idx:]

    print(f"  Train/Test Split: {len(train_trades)}/{len(test_trades)}")
    print()

    # Map method string to enum
    method_map = {
        "best_score": SelectionMethod.BEST_SCORE,
        "weighted_best": SelectionMethod.WEIGHTED_BEST,
        "meta_learner": SelectionMethod.META_LEARNER,
        "confidence_weighted": SelectionMethod.CONFIDENCE_WEIGHTED,
        "ensemble_vote": SelectionMethod.ENSEMBLE_VOTE,
    }
    method = method_map.get(args.method, SelectionMethod.META_LEARNER)

    # Train
    print("-" * 70)
    print("  TRAINING IN PROGRESS...")
    print("-" * 70)
    print()
    print(f"    Method:      {method.value}")
    print(f"    Train Size:  {len(train_trades)}")
    print()

    selector, stats = train_ensemble(train_trades, method=method, verbose=args.verbose)

    print_training_results(stats)

    # Evaluate
    if test_trades:
        eval_results = evaluate_selector(selector, test_trades, verbose=args.verbose)
        print_evaluation_results(eval_results)

    # Print insights
    if args.verbose:
        print_symbol_insights(selector)
        print_rotation_status(selector)

    # Save
    if args.output:
        filepath = args.output
    else:
        models_dir = Path.home() / ".optionplay" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = str(models_dir / f"ensemble_{timestamp}.json")

    selector.save(filepath)

    # Also save as latest
    latest_path = str(Path(filepath).parent / "ensemble_latest.json")
    selector.save(latest_path)

    print_summary(filepath, stats)

    # Test the selector
    print("-" * 70)
    print("  SELECTOR TEST")
    print("-" * 70)
    print()

    # Create sample scores
    test_scores = {
        "pullback": create_strategy_score(
            "pullback", 7.5,
            {"rsi_score": 1.5, "support_score": 2.0, "fibonacci_score": 1.5, "volume_score": 1.5, "ma_score": 1.0}
        ),
        "bounce": create_strategy_score(
            "bounce", 6.5,
            {"rsi_score": 1.5, "support_score": 2.5, "volume_score": 1.0, "candlestick_score": 1.5}
        ),
        "ath_breakout": create_strategy_score(
            "ath_breakout", 8.0,
            {"ath_breakout_score": 2.5, "volume_score": 2.0, "momentum_score": 2.0, "rsi_score": 1.5}
        ),
    }

    rec = selector.get_recommendation("AAPL", test_scores, vix=17.5)

    print(rec.summary())
    print()

    print("=" * 70)
    print("  TRAINING COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
