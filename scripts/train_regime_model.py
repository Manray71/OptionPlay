#!/usr/bin/env python3
"""
OptionPlay - Regime-Based Model Training Script
===============================================

Trains VIX regime-specific models using Walk-Forward methodology.
Optimizes parameters and strategy selection per regime.

Features:
- Walk-Forward training per regime
- Fixed vs Percentile boundary comparison
- Automatic strategy enablement based on performance
- Hysteresis-aware regime transitions
- JSON model export for production use

Usage:
    # Full training with all features
    python scripts/train_regime_model.py

    # Quick training (shorter periods)
    python scripts/train_regime_model.py --quick

    # Specify training periods
    python scripts/train_regime_model.py --train-months 18 --test-months 6

    # Skip boundary comparison (faster)
    python scripts/train_regime_model.py --no-compare-boundaries

    # Custom output path
    python scripts/train_regime_model.py --output ~/my_models/regime.json

    # Verbose output with epoch details
    python scripts/train_regime_model.py -v

Examples:
    # Standard training
    python scripts/train_regime_model.py

    # Production training with longer history
    python scripts/train_regime_model.py --train-months 24 --test-months 6 -v

    # Quick test run
    python scripts/train_regime_model.py --quick --no-compare-boundaries
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.backtesting import TradeTracker
from src.backtesting.regime_trainer import (
    RegimeTrainer,
    RegimeTrainingConfig,
    FullRegimeTrainingResult,
)
from src.backtesting.regime_model import RegimeModel
from src.backtesting.regime_config import format_regime_summary

logger = logging.getLogger(__name__)


# =============================================================================
# DATA LOADING
# =============================================================================

def load_historical_data(tracker: TradeTracker, symbols: List[str]) -> Dict[str, List[Dict]]:
    """Load historical price data from database"""
    data = {}

    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            data[symbol] = [
                {
                    "date": bar.date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in price_data.bars
            ]

    return data


def load_vix_data(tracker: TradeTracker) -> List[Dict]:
    """Load VIX historical data from database"""
    vix_points = tracker.get_vix_data()

    if not vix_points:
        return []

    return [
        {"date": p.date, "close": p.value}
        for p in vix_points
    ]


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def print_header():
    """Print script header"""
    print()
    print("=" * 70)
    print("  OPTIONPLAY REGIME-BASED MODEL TRAINING")
    print("=" * 70)
    print()


def print_config(config: RegimeTrainingConfig):
    """Print training configuration"""
    print("  Training Configuration:")
    print(f"    Train Period:           {config.train_months} months")
    print(f"    Test Period:            {config.test_months} months")
    print(f"    Step:                   {config.step_months} months")
    print(f"    Min Trades/Regime:      {config.min_trades_per_regime}")
    print(f"    Compare Boundaries:     {config.compare_boundary_methods}")
    print(f"    Auto-Disable Strategies: {config.auto_disable_strategies}")
    print(f"    Optimize Parameters:    {config.optimize_parameters}")
    print()


def print_data_stats(historical_data: Dict, vix_data: List):
    """Print data statistics"""
    total_bars = sum(len(bars) for bars in historical_data.values())

    print("  Data Statistics:")
    print(f"    Symbols:       {len(historical_data)}")
    print(f"    Total Bars:    {total_bars:,}")
    print(f"    VIX Points:    {len(vix_data):,}")

    if vix_data:
        vix_values = [v["close"] for v in vix_data]
        print(f"    VIX Range:     {min(vix_values):.1f} - {max(vix_values):.1f}")

    print()


def print_regime_results(result: FullRegimeTrainingResult, verbose: bool = False):
    """Print training results"""
    print()
    print("=" * 80)
    print("  TRAINING RESULTS")
    print("=" * 80)
    print()

    # Boundary comparison
    print("  Boundary Method Comparison:")
    print(f"    Fixed Score:      {result.fixed_boundaries_score:.4f}")
    print(f"    Percentile Score: {result.percentile_boundaries_score:.4f}")
    print(f"    Selected Method:  {result.boundary_method_used.value.upper()}")
    print()

    # Per-regime summary
    print("-" * 80)
    print("  PER-REGIME RESULTS")
    print("-" * 80)
    print()
    print(f"{'Regime':<12} {'Epochs':>8} {'Trades':>8} {'IS Win%':>10} {'OOS Win%':>10} {'Degrad':>10} {'Overfit':<10}")
    print("-" * 80)

    for regime_name in ["low_vol", "normal", "elevated", "high_vol"]:
        if regime_name not in result.regime_results:
            continue

        r = result.regime_results[regime_name]

        severity_icon = {
            "none": "",
            "mild": "*",
            "moderate": "**",
            "severe": "***",
            "unknown": "?",
        }.get(r.overfit_severity, "")

        print(
            f"{regime_name:<12} "
            f"{r.valid_epochs:>8} "
            f"{r.total_trades:>8} "
            f"{r.avg_in_sample_win_rate:>9.1f}% "
            f"{r.avg_out_sample_win_rate:>9.1f}% "
            f"{r.avg_win_rate_degradation:>+9.1f}% "
            f"{r.overfit_severity:<8} {severity_icon}"
        )

    print()

    # Strategy recommendations
    print("-" * 80)
    print("  STRATEGY RECOMMENDATIONS")
    print("-" * 80)
    print()
    print(f"{'Regime':<12} {'Enabled Strategies':<40} {'Disabled':<20}")
    print("-" * 80)

    for regime_name in ["low_vol", "normal", "elevated", "high_vol"]:
        if regime_name not in result.regime_results:
            continue

        r = result.regime_results[regime_name]
        enabled = ", ".join(r.enabled_strategies) or "none"
        disabled = ", ".join(r.disabled_strategies) or "-"

        print(f"{regime_name:<12} {enabled:<40} {disabled:<20}")

    print()

    # Optimized parameters
    print("-" * 80)
    print("  OPTIMIZED PARAMETERS")
    print("-" * 80)
    print()
    print(f"{'Regime':<12} {'Min Score':>10} {'Profit %':>10} {'Stop %':>10} {'Pos Size %':>12} {'Max Pos':>10}")
    print("-" * 80)

    for regime_name in ["low_vol", "normal", "elevated", "high_vol"]:
        if regime_name not in result.trained_regimes:
            continue

        config = result.trained_regimes[regime_name]

        print(
            f"{regime_name:<12} "
            f"{config.min_score:>10.1f} "
            f"{config.profit_target_pct:>10.0f} "
            f"{config.stop_loss_pct:>10.0f} "
            f"{config.position_size_pct:>12.1f} "
            f"{config.max_concurrent_positions:>10}"
        )

    print()

    # Verbose epoch details
    if verbose:
        for regime_name, r in result.regime_results.items():
            if not r.epochs:
                continue

            print("-" * 80)
            print(f"  EPOCH DETAILS: {regime_name.upper()}")
            print("-" * 80)
            print()
            print(f"{'Epoch':>6} {'Train Period':<22} {'Test Period':<22} {'IS Win%':>10} {'OOS Win%':>10} {'Degrad':>10}")
            print("-" * 80)

            for epoch in r.epochs:
                if not epoch.is_valid:
                    print(f"{epoch.epoch_id:>6} SKIPPED: {epoch.skip_reason}")
                    continue

                train_period = f"{epoch.train_start} to {epoch.train_end}"
                test_period = f"{epoch.test_start} to {epoch.test_end}"

                print(
                    f"{epoch.epoch_id:>6} "
                    f"{train_period:<22} "
                    f"{test_period:<22} "
                    f"{epoch.in_sample_win_rate:>9.1f}% "
                    f"{epoch.out_sample_win_rate:>9.1f}% "
                    f"{epoch.win_rate_degradation:>+9.1f}%"
                )

            print()

    # Warnings
    if result.warnings:
        print("-" * 80)
        print("  WARNINGS")
        print("-" * 80)
        for warning in result.warnings:
            print(f"  ! {warning}")
        print()

    # Summary
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  Training ID:          {result.training_id}")
    print(f"  Total Trades:         {result.total_trades_analyzed:,}")
    print(f"  Avg OOS Win Rate:     {result.avg_out_sample_win_rate:.1f}%")
    print(f"  Overall Confidence:   {result.overall_confidence.upper()}")
    print("=" * 80)
    print()


def print_final_model(result: FullRegimeTrainingResult, model_path: str):
    """Print final model summary"""
    print()
    print("=" * 70)
    print("  TRAINED MODEL SAVED")
    print("=" * 70)
    print(f"  Path: {model_path}")
    print()
    print(format_regime_summary(result.trained_regimes))
    print()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Train regime-based VIX models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Training parameters
    parser.add_argument(
        "--train-months", type=int, default=12,
        help="Training period in months (default: 12)"
    )
    parser.add_argument(
        "--test-months", type=int, default=3,
        help="Test period in months (default: 3)"
    )
    parser.add_argument(
        "--step-months", type=int, default=3,
        help="Step between epochs in months (default: 3)"
    )

    # Quality settings
    parser.add_argument(
        "--min-trades-per-regime", type=int, default=50,
        help="Minimum trades per regime (default: 50)"
    )
    parser.add_argument(
        "--min-trades-per-epoch", type=int, default=20,
        help="Minimum trades per epoch (default: 20)"
    )

    # Feature flags
    parser.add_argument(
        "--no-compare-boundaries", action="store_true",
        help="Skip comparison of fixed vs percentile boundaries"
    )
    parser.add_argument(
        "--no-auto-disable", action="store_true",
        help="Don't auto-disable underperforming strategies"
    )
    parser.add_argument(
        "--no-optimize", action="store_true",
        help="Don't optimize parameters"
    )

    # Quick mode
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick mode with shorter training periods"
    )

    # Output
    parser.add_argument(
        "--output", "-o", type=str,
        help="Output file path (default: ~/.optionplay/models/)"
    )

    # Verbosity
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output with epoch details"
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

    # Quick mode adjustments
    if args.quick:
        args.train_months = 6
        args.test_months = 2
        args.step_months = 2
        args.min_trades_per_regime = 30
        args.min_trades_per_epoch = 10
        print("  Mode: QUICK (shortened training periods)")
        print()

    # Load data
    print("  Loading data...")
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    if stats["symbols_with_price_data"] == 0:
        print()
        print("  ERROR: No historical data found!")
        print("  Run first: python scripts/collect_historical_data.py --all")
        sys.exit(1)

    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s["symbol"] for s in symbol_info]

    historical_data = load_historical_data(tracker, symbols)
    vix_data = load_vix_data(tracker)

    if not vix_data:
        print()
        print("  ERROR: No VIX data found!")
        print("  Run first: python scripts/collect_historical_data.py --all")
        sys.exit(1)

    print_data_stats(historical_data, vix_data)

    # Create training config
    config = RegimeTrainingConfig(
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        min_trades_per_regime=args.min_trades_per_regime,
        min_trades_per_epoch=args.min_trades_per_epoch,
        compare_boundary_methods=not args.no_compare_boundaries,
        auto_disable_strategies=not args.no_auto_disable,
        optimize_parameters=not args.no_optimize,
    )

    print_config(config)

    # Train
    print("-" * 70)
    print("  TRAINING IN PROGRESS...")
    print("-" * 70)
    print()

    trainer = RegimeTrainer(config)

    try:
        result = trainer.train(
            historical_data=historical_data,
            vix_data=vix_data,
        )
    except Exception as e:
        print(f"  ERROR: Training failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    # Print results
    print_regime_results(result, verbose=args.verbose)

    # Save model
    if args.output:
        model_path = args.output
    else:
        models_dir = Path.home() / ".optionplay" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        model_path = str(models_dir / f"{result.training_id}.json")

    saved_path = trainer.save(result, model_path)
    print_final_model(result, saved_path)

    # Create production model
    model = RegimeModel(
        regimes=result.trained_regimes,
        model_id=result.training_id,
    )

    production_path = str(Path(saved_path).parent / "regime_model_latest.json")
    model.save(production_path)
    print(f"  Production model: {production_path}")

    # Test the model
    print()
    print("-" * 70)
    print("  MODEL TEST")
    print("-" * 70)

    # Test with different VIX values
    test_cases = [
        (12.0, 8.5, "pullback"),
        (18.0, 6.0, "bounce"),
        (25.0, 7.5, "ath_breakout"),
        (35.0, 9.0, "pullback"),
    ]

    for vix, score, strategy in test_cases:
        model.initialize(vix)
        decision = model.should_trade(score, strategy, vix)

        status = "TRADE" if decision.should_trade else "SKIP"
        print(f"  VIX={vix:5.1f}, Score={score:.1f}, Strategy={strategy:12s} -> {status:5s} ({decision.reason})")

    print()
    print("=" * 70)
    print("  TRAINING COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
