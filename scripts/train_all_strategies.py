#!/usr/bin/env python3
"""
OptionPlay - Complete Strategy Training Pipeline
=================================================

Trains all strategies with:
1. Full Bull-Put-Spread P&L simulation
2. VIX regime analysis
3. Walk-forward validation
4. Ensemble model training
5. Production export

Usage:
    python scripts/train_all_strategies.py
"""

import json
import sys
import warnings
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import statistics
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

# Suppress warnings for cleaner output
warnings.filterwarnings('ignore')
logging.getLogger('optionplay').setLevel(logging.ERROR)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.backtesting import TradeTracker
from src.config.config_loader import PullbackScoringConfig
from src.analyzers.pullback import PullbackAnalyzer
from src.analyzers.bounce import BounceAnalyzer, BounceConfig
from src.analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from src.analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
from src.models.base import SignalType

# Constants
STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']

VIX_REGIMES = {
    'low': (0, 15),
    'normal': (15, 20),
    'elevated': (20, 30),
    'high': (30, 100)
}


@dataclass
class TradeRecord:
    symbol: str
    entry_date: date
    exit_date: Optional[date]
    entry_price: float
    score: float
    vix: float
    regime: str
    outcome: int  # 1=win, 0=loss
    pnl: float
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class StrategyResult:
    strategy: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    regime_performance: Dict[str, Dict] = field(default_factory=dict)
    score_threshold_analysis: Dict[float, Dict] = field(default_factory=dict)
    train_validation: Dict[str, float] = field(default_factory=dict)


def get_regime(vix: float) -> str:
    """Classify VIX into regime"""
    for regime, (low, high) in VIX_REGIMES.items():
        if low <= vix < high:
            return regime
    return 'high'


def create_analyzer(strategy: str):
    """Create analyzer for strategy"""
    if strategy == 'pullback':
        return PullbackAnalyzer(PullbackScoringConfig())
    elif strategy == 'bounce':
        return BounceAnalyzer(BounceConfig())
    elif strategy == 'ath_breakout':
        return ATHBreakoutAnalyzer(ATHBreakoutConfig())
    elif strategy == 'earnings_dip':
        return EarningsDipAnalyzer(EarningsDipConfig())
    raise ValueError(f"Unknown strategy: {strategy}")


def simulate_trade_outcome(
    entry_price: float,
    future_prices: List[Dict],
    holding_days: int = 45
) -> tuple[int, float]:
    """
    Simulate Bull-Put-Spread outcome

    Returns: (outcome, pnl)
    - outcome: 1=win, 0=loss
    - pnl: realized P&L in dollars
    """
    if len(future_prices) < 10:
        return 0, 0

    # Bull-Put-Spread parameters
    short_strike = entry_price * 0.92  # 8% OTM
    long_strike = short_strike - (entry_price * 0.05)  # $5 wide spread
    spread_width = short_strike - long_strike
    net_credit = spread_width * 0.20  # 20% of width as credit

    max_profit = net_credit * 100
    max_loss = (spread_width - net_credit) * 100

    # Track through holding period
    min_price = float('inf')

    for i, bar in enumerate(future_prices[:holding_days]):
        current_low = bar['low']
        current_close = bar['close']
        min_price = min(min_price, current_low)

        # Check for max loss (price drops below long strike)
        if current_low < long_strike:
            return 0, -max_loss

        # Check for early exit at 50% profit (price stays well above short strike)
        days_held = i + 1
        if days_held >= 14:  # After 2 weeks
            if current_close >= entry_price:  # Stock recovered/stayed strong
                return 1, max_profit * 0.5  # 50% profit target

    # At expiration
    final_price = future_prices[min(holding_days-1, len(future_prices)-1)]['close']

    if final_price >= short_strike:
        return 1, max_profit  # Full profit
    elif final_price >= long_strike:
        intrinsic = short_strike - final_price
        return 0, (net_credit - intrinsic) * 100  # Partial loss
    else:
        return 0, -max_loss  # Max loss


def backtest_strategy(
    strategy: str,
    historical_data: Dict[str, List[Dict]],
    vix_data: Dict[date, float],
    start_date: date,
    end_date: date,
    min_score: float = 5.0,
    sample_rate: int = 3  # Check every N days for speed
) -> List[TradeRecord]:
    """Backtest a strategy over a period"""

    analyzer = create_analyzer(strategy)
    trades = []

    # Build date index
    all_dates = set()
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
            if start_date <= d <= end_date:
                all_dates.add(d)

    trading_days = sorted(all_dates)[::sample_rate]  # Sample for speed
    symbols = list(historical_data.keys())

    # Track open positions to avoid duplicates
    position_cooldown = {}  # symbol -> last_entry_date

    for current_date in trading_days:
        # Get VIX for this date
        vix = vix_data.get(current_date, 20.0)
        regime = get_regime(vix)

        for symbol in symbols:
            # Cooldown: no new entry within 30 days of previous
            if symbol in position_cooldown:
                if (current_date - position_cooldown[symbol]).days < 30:
                    continue

            symbol_data = historical_data.get(symbol, [])

            # Get history up to current date
            history = []
            future = []
            for bar in symbol_data:
                d = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
                bar_copy = {**bar, 'date': d}
                if d < current_date:
                    history.append(bar_copy)
                elif d >= current_date:
                    future.append(bar_copy)

            history.sort(key=lambda x: x['date'])
            future.sort(key=lambda x: x['date'])

            if len(history) < 200:
                continue

            history = history[-260:]  # Last 260 days

            prices = [bar['close'] for bar in history]
            volumes = [bar['volume'] for bar in history]
            highs = [bar['high'] for bar in history]
            lows = [bar['low'] for bar in history]

            try:
                signal = analyzer.analyze(
                    symbol=symbol,
                    prices=prices,
                    volumes=volumes,
                    highs=highs,
                    lows=lows
                )
            except Exception:
                continue

            if signal.signal_type != SignalType.LONG:
                continue
            if signal.score < min_score:
                continue

            # Entry signal found
            entry_price = prices[-1]

            # Simulate trade
            outcome, pnl = simulate_trade_outcome(entry_price, future)

            # Extract score breakdown
            score_breakdown = {}
            if signal.details:
                bd = signal.details.get('score_breakdown') or signal.details.get('breakdown')
                if bd:
                    if isinstance(bd, dict):
                        for k, v in bd.items():
                            if isinstance(v, (int, float)):
                                score_breakdown[k] = float(v)
                    elif hasattr(bd, '__dict__'):
                        for k, v in bd.__dict__.items():
                            if isinstance(v, (int, float)) and not k.startswith('_'):
                                score_breakdown[k] = float(v)

            trades.append(TradeRecord(
                symbol=symbol,
                entry_date=current_date,
                exit_date=current_date + timedelta(days=45),
                entry_price=entry_price,
                score=signal.score,
                vix=vix,
                regime=regime,
                outcome=outcome,
                pnl=pnl,
                score_breakdown=score_breakdown
            ))

            position_cooldown[symbol] = current_date

    return trades


def walk_forward_train(
    strategy: str,
    historical_data: Dict[str, List[Dict]],
    vix_data: Dict[date, float],
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
) -> StrategyResult:
    """Walk-forward training with out-of-sample validation"""

    result = StrategyResult(strategy=strategy)

    # Find date range
    all_dates = set()
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
            all_dates.add(d)

    min_date = min(all_dates)
    max_date = max(all_dates)

    print(f"    Data range: {min_date} to {max_date}")

    train_days = train_months * 30
    test_days = test_months * 30
    step_days = step_months * 30

    all_train_trades = []
    all_test_trades = []

    current_start = min_date + timedelta(days=200)  # Need 200 days of history
    epoch = 0

    while True:
        train_end = current_start + timedelta(days=train_days)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_days)

        if test_end > max_date:
            break

        epoch += 1
        print(f"    Epoch {epoch}: Train {current_start.strftime('%Y-%m')} to {train_end.strftime('%Y-%m')}, "
              f"Test {test_start.strftime('%Y-%m')} to {test_end.strftime('%Y-%m')}")

        # Training period
        train_trades = backtest_strategy(
            strategy, historical_data, vix_data,
            current_start, train_end,
            min_score=5.0,
            sample_rate=5  # Faster sampling for training
        )

        # Test period
        test_trades = backtest_strategy(
            strategy, historical_data, vix_data,
            test_start, test_end,
            min_score=5.0,
            sample_rate=3
        )

        all_train_trades.extend(train_trades)
        all_test_trades.extend(test_trades)

        current_start += timedelta(days=step_days)

    print(f"    Collected: {len(all_train_trades)} train, {len(all_test_trades)} test trades")

    # Calculate metrics
    all_trades = all_train_trades + all_test_trades
    result.total_trades = len(all_trades)
    result.wins = sum(1 for t in all_trades if t.outcome == 1)
    result.losses = sum(1 for t in all_trades if t.outcome == 0)
    result.total_pnl = sum(t.pnl for t in all_trades)

    # Regime analysis
    for regime in VIX_REGIMES.keys():
        regime_trades = [t for t in all_trades if t.regime == regime]
        if regime_trades:
            wins = sum(1 for t in regime_trades if t.outcome == 1)
            result.regime_performance[regime] = {
                'trades': len(regime_trades),
                'wins': wins,
                'win_rate': wins / len(regime_trades) * 100,
                'pnl': sum(t.pnl for t in regime_trades),
                'avg_score': statistics.mean(t.score for t in regime_trades)
            }

    # Score threshold analysis
    for threshold in [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]:
        threshold_trades = [t for t in all_trades if t.score >= threshold]
        if threshold_trades:
            wins = sum(1 for t in threshold_trades if t.outcome == 1)
            result.score_threshold_analysis[threshold] = {
                'trades': len(threshold_trades),
                'wins': wins,
                'win_rate': wins / len(threshold_trades) * 100,
                'pnl': sum(t.pnl for t in threshold_trades)
            }

    # Train/Test validation
    if all_train_trades:
        train_wins = sum(1 for t in all_train_trades if t.outcome == 1)
        result.train_validation['train_win_rate'] = train_wins / len(all_train_trades) * 100

    if all_test_trades:
        test_wins = sum(1 for t in all_test_trades if t.outcome == 1)
        result.train_validation['test_win_rate'] = test_wins / len(all_test_trades) * 100
        result.train_validation['degradation'] = (
            result.train_validation.get('train_win_rate', 0) -
            result.train_validation['test_win_rate']
        )

    return result


def print_results(results: Dict[str, StrategyResult]):
    """Print formatted results"""

    print("\n" + "=" * 80)
    print("  TRAINING RESULTS SUMMARY")
    print("=" * 80)

    # Overview table
    print(f"\n  {'Strategy':<15} {'Trades':>8} {'Win%':>8} {'Test%':>8} {'Degrad':>8} {'P&L':>12}")
    print("  " + "-" * 63)

    for strategy, result in results.items():
        win_rate = result.wins / result.total_trades * 100 if result.total_trades > 0 else 0
        test_wr = result.train_validation.get('test_win_rate', 0)
        degrad = result.train_validation.get('degradation', 0)

        status = "OK" if degrad < 15 else "OVERFIT"

        print(f"  {strategy:<15} {result.total_trades:>8} {win_rate:>7.1f}% {test_wr:>7.1f}% "
              f"{degrad:>+7.1f}% ${result.total_pnl:>10,.0f}")

    # Regime performance
    print(f"\n  VIX REGIME PERFORMANCE")
    print("  " + "-" * 70)
    print(f"  {'Strategy':<15} {'Low':>10} {'Normal':>10} {'Elevated':>10} {'High':>10}")
    print("  " + "-" * 70)

    for strategy, result in results.items():
        row = f"  {strategy:<15}"
        for regime in ['low', 'normal', 'elevated', 'high']:
            perf = result.regime_performance.get(regime, {})
            wr = perf.get('win_rate', 0)
            row += f" {wr:>9.1f}%"
        print(row)

    # Best score thresholds
    print(f"\n  OPTIMAL SCORE THRESHOLDS")
    print("  " + "-" * 60)

    for strategy, result in results.items():
        best_threshold = 5.0
        best_win_rate = 0

        for threshold, data in result.score_threshold_analysis.items():
            if data['trades'] >= 20 and data['win_rate'] > best_win_rate:
                best_win_rate = data['win_rate']
                best_threshold = threshold

        print(f"  {strategy:<15}: Score >= {best_threshold:.1f} -> {best_win_rate:.1f}% win rate")


def export_models(results: Dict[str, StrategyResult], output_dir: Path):
    """Export trained models for production"""

    output_dir.mkdir(parents=True, exist_ok=True)

    # Main config
    config = {
        'version': '2.0.0',
        'created_at': datetime.now().isoformat(),
        'training_method': 'walk_forward_validation',
        'strategies': {}
    }

    for strategy, result in results.items():
        # Find best regime
        best_regime = 'normal'
        best_wr = 0
        for regime, perf in result.regime_performance.items():
            if perf.get('win_rate', 0) > best_wr:
                best_wr = perf['win_rate']
                best_regime = regime

        # Find optimal score threshold
        best_threshold = 6.0
        for threshold, data in result.score_threshold_analysis.items():
            if data['trades'] >= 20 and data['win_rate'] > 60:
                best_threshold = threshold
                break

        # Calculate regime adjustments
        regime_adjustments = {}
        base_wr = result.train_validation.get('test_win_rate', 50)

        for regime, perf in result.regime_performance.items():
            regime_wr = perf.get('win_rate', 50)
            diff = regime_wr - base_wr

            if diff > 10:
                regime_adjustments[regime] = 1.0  # Favor this regime
            elif diff > 5:
                regime_adjustments[regime] = 0.5
            elif diff < -10:
                regime_adjustments[regime] = -1.0  # Avoid this regime
            elif diff < -5:
                regime_adjustments[regime] = -0.5
            else:
                regime_adjustments[regime] = 0.0

        config['strategies'][strategy] = {
            'enabled': True,
            'recommended_min_score': best_threshold,
            'regime_adjustments': regime_adjustments,
            'best_regime': best_regime,
            'validation': {
                'total_trades': result.total_trades,
                'train_win_rate': result.train_validation.get('train_win_rate', 0),
                'test_win_rate': result.train_validation.get('test_win_rate', 0),
                'degradation': result.train_validation.get('degradation', 0),
            },
            'regime_performance': result.regime_performance,
            'score_analysis': {
                str(k): v for k, v in result.score_threshold_analysis.items()
            }
        }

    # Save main config
    main_path = output_dir / 'trained_strategies.json'
    with open(main_path, 'w') as f:
        json.dump(config, f, indent=2, default=str)

    print(f"\n  Saved: {main_path}")

    # Also update production config
    prod_config = {
        'version': '2.0.0',
        'created_at': datetime.now().isoformat(),
        'strategies': {
            s: {
                'enabled': True,
                'min_score': c['recommended_min_score'],
                'regime_adjustments': c['regime_adjustments'],
            }
            for s, c in config['strategies'].items()
        }
    }

    prod_path = output_dir / 'production_config.json'
    with open(prod_path, 'w') as f:
        json.dump(prod_config, f, indent=2)

    print(f"  Saved: {prod_path}")


def main():
    print("=" * 80)
    print("  OPTIONPLAY - COMPLETE STRATEGY TRAINING PIPELINE")
    print("=" * 80)

    # Load data
    print("\n  Loading data...")
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    print(f"    Symbols: {stats['symbols_with_price_data']}")
    print(f"    Price Bars: {stats['total_price_bars']:,}")
    print(f"    VIX Points: {stats['vix_data_points']:,}")

    # Load historical data
    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_info]

    print(f"\n  Loading {len(symbols)} symbols...")

    historical_data = {}
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            historical_data[symbol] = [
                {
                    'date': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume,
                }
                for bar in price_data.bars
            ]

    # Load VIX
    vix_data = {}
    for p in tracker.get_vix_data():
        vix_data[p.date] = p.value

    print(f"  Loaded: {len(historical_data)} symbols, {len(vix_data)} VIX points")

    # Train each strategy
    results = {}

    for strategy in STRATEGIES:
        print(f"\n{'='*80}")
        print(f"  TRAINING: {strategy.upper()}")
        print("=" * 80)

        try:
            result = walk_forward_train(
                strategy=strategy,
                historical_data=historical_data,
                vix_data=vix_data,
                train_months=12,
                test_months=3,
                step_months=3
            )
            results[strategy] = result

            win_rate = result.wins / result.total_trades * 100 if result.total_trades > 0 else 0
            print(f"    Result: {result.total_trades} trades, {win_rate:.1f}% win rate, ${result.total_pnl:,.0f} P&L")

        except Exception as e:
            print(f"    ERROR: {e}")
            import traceback
            traceback.print_exc()

    # Print results
    print_results(results)

    # Export models
    output_dir = Path.home() / '.optionplay' / 'models'
    export_models(results, output_dir)

    print("\n" + "=" * 80)
    print("  TRAINING COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    main()
