#!/usr/bin/env python3
"""
Import Backtest Trades for ML Training

Imports backtest results into the TradeTracker database for use in:
- ML Weight Optimization
- Ensemble Strategy Training
- Regime Model Training

This script re-runs the backtest but saves full trade details including
score breakdowns, VIX at signal time, and all metadata needed for training.

Usage:
    python scripts/import_backtest_trades.py
    python scripts/import_backtest_trades.py --strategies pullback bounce
    python scripts/import_backtest_trades.py --max-trades 1000
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv()

from src.backtesting import TradeTracker
from src.backtesting.engine import TradeOutcome, ExitReason
from src.config.config_loader import PullbackScoringConfig
from src.analyzers.pullback import PullbackAnalyzer
from src.analyzers.bounce import BounceAnalyzer, BounceConfig
from src.analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from src.analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
from src.analyzers.trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig
from src.models.base import SignalType

logger = logging.getLogger(__name__)

STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip", "trend_continuation"]


def create_analyzers():
    """Create all strategy analyzers"""
    return {
        "pullback": PullbackAnalyzer(PullbackScoringConfig()),
        "bounce": BounceAnalyzer(BounceConfig()),
        "ath_breakout": ATHBreakoutAnalyzer(ATHBreakoutConfig()),
        "earnings_dip": EarningsDipAnalyzer(EarningsDipConfig()),
        "trend_continuation": TrendContinuationAnalyzer(TrendContinuationConfig()),
    }


def load_historical_data(tracker: TradeTracker, symbols: List[str]) -> Dict[str, List[Dict]]:
    """Load historical data from database"""
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


def load_vix_data(tracker: TradeTracker) -> Dict[date, float]:
    """Load VIX data as date -> value dict"""
    vix_points = tracker.get_vix_data()
    if not vix_points:
        return {}
    return {p.date: p.value for p in vix_points}


def get_history_up_to(
    symbol_data: List[Dict], target_date: date, lookback: int = 260
) -> List[Dict]:
    """Get historical bars up to target date"""
    bars_before = []
    for bar in symbol_data:
        d = bar["date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        if d < target_date:
            bars_before.append({**bar, "date": d})

    bars_before.sort(key=lambda x: x["date"])
    return bars_before[-lookback:] if len(bars_before) > lookback else bars_before


def simulate_trade_outcome(
    entry_price: float,
    entry_date: date,
    symbol_data: List[Dict],
    profit_target_pct: float = 50.0,
    stop_loss_pct: float = 100.0,
    max_days: int = 60,
) -> tuple:
    """
    Simulate trade outcome based on price movement.

    Returns:
        (outcome, exit_date, exit_price, pnl_percent, holding_days)
    """
    # Calculate strikes for Bull Put Spread
    short_strike = entry_price * 0.92  # ~8% OTM
    long_strike = short_strike * 0.95  # $5 width approx
    spread_width = short_strike - long_strike

    # Estimate credit (simplified)
    credit_per_spread = spread_width * 0.3  # ~30% of width
    max_profit = credit_per_spread * 100  # Per contract
    max_loss = (spread_width - credit_per_spread) * 100

    exit_date = entry_date
    exit_price = entry_price

    # Get future bars
    future_bars = []
    for bar in symbol_data:
        d = bar["date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        if d > entry_date:
            future_bars.append({**bar, "date": d})

    future_bars.sort(key=lambda x: x["date"])

    for i, bar in enumerate(future_bars[:max_days]):
        bar_date = bar["date"]
        bar_close = bar["close"]

        # Check for profit target (price stayed above short strike)
        if bar_close >= short_strike:
            # Calculate days held
            days_held = (bar_date - entry_date).days
            if days_held >= 21:  # DTE exit threshold
                return ("WIN", bar_date, bar_close, profit_target_pct, days_held)

        # Check for stop loss (price fell below long strike)
        if bar_close <= long_strike:
            days_held = (bar_date - entry_date).days
            return ("LOSS", bar_date, bar_close, -stop_loss_pct, days_held)

        # Partial loss - between strikes
        if bar_close < short_strike:
            intrinsic = short_strike - bar_close
            loss_pct = (intrinsic / credit_per_spread) * 100 if credit_per_spread > 0 else 0
            if loss_pct >= stop_loss_pct:
                days_held = (bar_date - entry_date).days
                return ("LOSS", bar_date, bar_close, -loss_pct, days_held)

        exit_date = bar_date
        exit_price = bar_close

    # Expired at max profit if we got here
    days_held = (exit_date - entry_date).days
    if exit_price >= short_strike:
        return ("WIN", exit_date, exit_price, profit_target_pct, max(days_held, 1))
    else:
        # Partial outcome
        intrinsic = max(0, short_strike - exit_price)
        pnl_pct = (
            ((credit_per_spread - intrinsic) / credit_per_spread) * 100
            if credit_per_spread > 0
            else 0
        )
        outcome = "WIN" if pnl_pct > 0 else "LOSS"
        return (outcome, exit_date, exit_price, pnl_pct, max(days_held, 1))


def run_backtest_with_details(
    strategy: str,
    analyzer,
    historical_data: Dict[str, List[Dict]],
    vix_data: Dict[date, float],
    min_score: float = 5.0,
    max_trades: int = 1000,
) -> List[Dict[str, Any]]:
    """
    Run backtest for a strategy and return detailed trade records.
    """
    trades = []

    # Get all trading days
    all_dates = set()
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar["date"]
            if isinstance(d, str):
                d = date.fromisoformat(d)
            all_dates.add(d)

    trading_days = sorted(all_dates)

    # Skip first 60 days for warmup
    if len(trading_days) > 60:
        trading_days = trading_days[60:]

    symbols = list(historical_data.keys())
    signals_per_day = {}  # Track to limit signals per day

    for current_date in trading_days:
        if len(trades) >= max_trades:
            break

        # Limit signals per day to avoid oversampling
        day_count = signals_per_day.get(current_date, 0)
        if day_count >= 5:
            continue

        for symbol in symbols:
            if len(trades) >= max_trades:
                break

            symbol_data = historical_data.get(symbol, [])
            history = get_history_up_to(symbol_data, current_date, lookback=260)

            if len(history) < 60:
                continue

            # Prepare arrays for analyzer
            prices = [bar["close"] for bar in history]
            volumes = [bar["volume"] for bar in history]
            highs = [bar["high"] for bar in history]
            lows = [bar["low"] for bar in history]

            try:
                signal = analyzer.analyze(
                    symbol=symbol, prices=prices, volumes=volumes, highs=highs, lows=lows
                )
            except Exception as e:
                continue

            # Check if signal qualifies
            if signal.signal_type != SignalType.LONG:
                continue
            if signal.score < min_score:
                continue

            # Get VIX at signal time
            vix_at_signal = vix_data.get(current_date)
            if not vix_at_signal:
                # Find nearest VIX
                for delta in range(1, 5):
                    check_date = current_date - timedelta(days=delta)
                    if check_date in vix_data:
                        vix_at_signal = vix_data[check_date]
                        break

            # Simulate trade outcome
            entry_price = prices[-1]
            outcome, exit_date, exit_price, pnl_pct, holding_days = simulate_trade_outcome(
                entry_price, current_date, symbol_data
            )

            # Extract score breakdown - flatten the nested structure
            score_breakdown = {}
            if signal.details and "score_breakdown" in signal.details:
                breakdown = signal.details["score_breakdown"]

                # Check if it's a ScoreBreakdown object or dict
                if hasattr(breakdown, "to_dict"):
                    breakdown = breakdown.to_dict()

                # Handle nested 'components' structure
                if isinstance(breakdown, dict) and "components" in breakdown:
                    for comp, data in breakdown["components"].items():
                        if isinstance(data, dict):
                            score_breakdown[f"{comp}_score"] = data.get(
                                "score", data.get("value", 0)
                            )
                        else:
                            score_breakdown[f"{comp}_score"] = data
                elif isinstance(breakdown, dict):
                    # Flat structure
                    for comp, data in breakdown.items():
                        if comp in ["total_score", "max_possible", "qualified", "components"]:
                            continue  # Skip metadata
                        if isinstance(data, dict):
                            key = comp if comp.endswith("_score") else f"{comp}_score"
                            score_breakdown[key] = data.get("score", data.get("value", 0))
                        elif isinstance(data, (int, float)):
                            key = comp if comp.endswith("_score") else f"{comp}_score"
                            score_breakdown[key] = data

            trades.append(
                {
                    "symbol": symbol,
                    "strategy": strategy,
                    "signal_date": current_date,
                    "exit_date": exit_date,
                    "signal_score": signal.score,
                    "score_breakdown": score_breakdown,
                    "outcome": outcome,
                    "pnl_percent": pnl_pct,
                    "pnl_amount": pnl_pct * 10,  # Simplified
                    "holding_days": holding_days,
                    "vix_at_signal": vix_at_signal,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                }
            )

            signals_per_day[current_date] = day_count + 1

    return trades


def save_trades_for_training(trades: List[Dict[str, Any]], output_path: str):
    """Save trades to JSON for training scripts"""
    with open(output_path, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "total_trades": len(trades),
                "trades": [
                    {
                        **t,
                        "signal_date": (
                            t["signal_date"].isoformat()
                            if isinstance(t["signal_date"], date)
                            else t["signal_date"]
                        ),
                        "exit_date": (
                            t["exit_date"].isoformat()
                            if isinstance(t["exit_date"], date)
                            else t["exit_date"]
                        ),
                    }
                    for t in trades
                ],
            },
            f,
            indent=2,
            default=str,
        )

    print(f"  Saved {len(trades)} trades to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Import backtest trades for ML training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=STRATEGIES + ["all"],
        default=["all"],
        help="Strategies to backtest (default: all)",
    )
    parser.add_argument(
        "--max-trades", type=int, default=2000, help="Max trades per strategy (default: 2000)"
    )
    parser.add_argument(
        "--min-score", type=float, default=5.0, help="Minimum signal score (default: 5.0)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(Path.home() / ".optionplay" / "training_trades.json"),
        help="Output JSON path",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    print()
    print("=" * 70)
    print("  OPTIONPLAY - IMPORT BACKTEST TRADES FOR TRAINING")
    print("=" * 70)
    print()

    # Load data
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    if stats["symbols_with_price_data"] == 0:
        print("❌ No historical data found!")
        sys.exit(1)

    print(f"  Database: {stats['symbols_with_price_data']} symbols")

    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s["symbol"] for s in symbol_info]

    print(f"  Loading historical data...")
    historical_data = load_historical_data(tracker, symbols)
    vix_data = load_vix_data(tracker)

    print(f"  Loaded {len(historical_data)} symbols, {len(vix_data)} VIX points")
    print()

    # Determine strategies
    if "all" in args.strategies:
        strategies = STRATEGIES
    else:
        strategies = args.strategies

    # Create analyzers
    analyzers = create_analyzers()

    # Run backtests
    all_trades = []

    for strategy in strategies:
        print(f"  Backtesting {strategy}...")

        analyzer = analyzers[strategy]
        trades = run_backtest_with_details(
            strategy=strategy,
            analyzer=analyzer,
            historical_data=historical_data,
            vix_data=vix_data,
            min_score=args.min_score,
            max_trades=args.max_trades,
        )

        wins = sum(1 for t in trades if t["outcome"] == "WIN")
        win_rate = wins / len(trades) * 100 if trades else 0

        print(f"    ✓ {len(trades)} trades, Win Rate: {win_rate:.1f}%")
        all_trades.extend(trades)

    print()
    print("-" * 70)
    print(f"  TOTAL: {len(all_trades)} trades across {len(strategies)} strategies")
    print("-" * 70)

    # Summary by strategy
    by_strategy = defaultdict(list)
    for t in all_trades:
        by_strategy[t["strategy"]].append(t)

    print()
    print(f"  {'Strategy':<15} {'Trades':>8} {'Win%':>8} {'Avg Score':>10}")
    print("  " + "-" * 45)
    for strat, trades in sorted(by_strategy.items()):
        wins = sum(1 for t in trades if t["outcome"] == "WIN")
        win_rate = wins / len(trades) * 100 if trades else 0
        avg_score = sum(t["signal_score"] for t in trades) / len(trades) if trades else 0
        print(f"  {strat:<15} {len(trades):>8} {win_rate:>7.1f}% {avg_score:>10.1f}")

    # Save
    print()
    save_trades_for_training(all_trades, args.output)

    print()
    print("=" * 70)
    print("  COMPLETE - Run training scripts now:")
    print("    python3 scripts/train_ml_weights.py")
    print("    python3 scripts/train_ensemble.py")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
