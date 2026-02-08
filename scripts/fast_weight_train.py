#!/usr/bin/env python3
"""
OptionPlay - Fast Component Weight Training
============================================

Optimized version of weight training for quick execution.
Uses parallel processing and simplified P&L calculations.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import statistics
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

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

logger = logging.getLogger(__name__)

STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'trend_continuation']


@dataclass
class TradeResult:
    """Simplified trade result for weight training"""
    symbol: str
    signal_date: date
    score: float
    outcome: int  # 1=win, 0=loss
    pnl: float
    vix: Optional[float]
    component_scores: Dict[str, float]


@dataclass
class ComponentWeight:
    """Component weight and statistics"""
    name: str
    samples: int = 0
    correlation: float = 0.0
    predictive_power: float = 0.0
    avg_when_win: float = 0.0
    avg_when_loss: float = 0.0
    optimal_weight: float = 1.0


def analyze_single_symbol(
    symbol: str,
    symbol_data: List[Dict],
    strategy: str,
    analyzer,
    vix_data: Dict[date, float],
    start_date: date,
    end_date: date,
) -> List[TradeResult]:
    """Analyze a single symbol for trades - optimized for speed"""
    results = []

    # Sort data by date
    sorted_data = sorted(symbol_data, key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date']))

    if len(sorted_data) < 200:
        return results

    # Build date index for O(1) lookups
    date_to_idx = {}
    for i, bar in enumerate(sorted_data):
        d = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
        date_to_idx[d] = i
        sorted_data[i] = {**bar, 'date': d}

    # Sample every 5th trading day for speed
    trading_days = [d for d in sorted(date_to_idx.keys()) if start_date <= d <= end_date]
    sampled_days = trading_days[::5]  # Every 5th day

    for current_date in sampled_days:
        idx = date_to_idx.get(current_date)
        if idx is None or idx < 200:
            continue

        # Get history up to this point
        history = sorted_data[max(0, idx-259):idx]
        if len(history) < 200:
            continue

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

        if signal.signal_type != SignalType.LONG or signal.score < 3.0:
            continue

        # Extract component scores
        component_scores = {}
        if signal.details:
            breakdown = signal.details.get('score_breakdown') or signal.details.get('breakdown')
            if breakdown:
                if isinstance(breakdown, dict):
                    for k, v in breakdown.items():
                        if isinstance(v, (int, float)):
                            component_scores[k] = float(v)
                elif hasattr(breakdown, '__dict__'):
                    for k, v in breakdown.__dict__.items():
                        if isinstance(v, (int, float)) and not k.startswith('_'):
                            component_scores[k] = float(v)

        # Simplified outcome calculation
        entry_price = prices[-1]

        # Look ahead 30 days for outcome
        future_bars = sorted_data[idx:idx+30]
        if len(future_bars) < 10:
            continue

        short_strike = entry_price * 0.92
        max_price = max(b['high'] for b in future_bars[:15])
        min_price = min(b['low'] for b in future_bars)
        final_price = future_bars[-1]['close']

        # Win if stock stayed above short strike
        if min_price >= short_strike:
            outcome = 1
            pnl = entry_price * 0.01 * 100  # Approximate credit
        elif max_price >= entry_price * 1.02 and final_price >= short_strike:
            outcome = 1
            pnl = entry_price * 0.005 * 100  # Partial credit
        else:
            outcome = 0
            pnl = -(entry_price * 0.03 * 100)  # Approximate loss

        results.append(TradeResult(
            symbol=symbol,
            signal_date=current_date,
            score=signal.score,
            outcome=outcome,
            pnl=pnl,
            vix=vix_data.get(current_date),
            component_scores=component_scores
        ))

    return results


def train_strategy_fast(
    strategy: str,
    historical_data: Dict[str, List[Dict]],
    vix_data: Dict[date, float],
    train_months: int = 12,
    test_months: int = 3,
) -> Dict[str, Any]:
    """Fast training for a single strategy"""

    # Initialize analyzer
    if strategy == 'pullback':
        analyzer = PullbackAnalyzer(PullbackScoringConfig())
    elif strategy == 'bounce':
        analyzer = BounceAnalyzer(BounceConfig())
    elif strategy == 'ath_breakout':
        analyzer = ATHBreakoutAnalyzer(ATHBreakoutConfig())
    elif strategy == 'earnings_dip':
        analyzer = EarningsDipAnalyzer(EarningsDipConfig())
    elif strategy == 'trend_continuation':
        from src.analyzers.trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig
        analyzer = TrendContinuationAnalyzer(TrendContinuationConfig())
    else:
        return {}

    # Find date range
    all_dates = set()
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
            all_dates.add(d)

    if not all_dates:
        return {}

    min_date = min(all_dates)
    max_date = max(all_dates)

    # Split into train/test
    train_end = max_date - timedelta(days=test_months * 30)
    train_start = train_end - timedelta(days=train_months * 30)
    test_start = train_end + timedelta(days=1)
    test_end = max_date

    print(f"    Train: {train_start} to {train_end}")
    print(f"    Test:  {test_start} to {test_end}")

    # Collect trades in parallel
    train_trades = []
    test_trades = []
    symbols = list(historical_data.keys())

    print(f"    Analyzing {len(symbols)} symbols...")

    with ThreadPoolExecutor(max_workers=8) as executor:
        # Submit all train tasks
        train_futures = {
            executor.submit(
                analyze_single_symbol,
                symbol, historical_data[symbol], strategy, analyzer,
                vix_data, train_start, train_end
            ): symbol
            for symbol in symbols
        }

        # Collect results
        for future in as_completed(train_futures):
            try:
                results = future.result()
                train_trades.extend(results)
            except Exception as e:
                pass

        # Submit test tasks
        test_futures = {
            executor.submit(
                analyze_single_symbol,
                symbol, historical_data[symbol], strategy, analyzer,
                vix_data, test_start, test_end
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(test_futures):
            try:
                results = future.result()
                test_trades.extend(results)
            except Exception:
                pass

    print(f"    Trades: {len(train_trades)} train, {len(test_trades)} test")

    if len(train_trades) < 20:
        return {
            'strategy': strategy,
            'status': 'insufficient_data',
            'train_trades': len(train_trades),
        }

    # Analyze components
    component_weights = {}
    all_components = set()

    for t in train_trades:
        for k in t.component_scores.keys():
            all_components.add(k)

    for component in all_components:
        relevant = [t for t in train_trades if component in t.component_scores]

        if len(relevant) < 10:
            continue

        winners = [t for t in relevant if t.outcome == 1]
        losers = [t for t in relevant if t.outcome == 0]

        cw = ComponentWeight(name=component)
        cw.samples = len(relevant)

        if winners:
            cw.avg_when_win = statistics.mean(t.component_scores[component] for t in winners)
        if losers:
            cw.avg_when_loss = statistics.mean(t.component_scores[component] for t in losers)

        # Calculate correlation
        try:
            outcomes = np.array([t.outcome for t in relevant])
            values = np.array([t.component_scores[component] for t in relevant])

            if np.std(values) > 0 and np.std(outcomes) > 0:
                cw.correlation = float(np.corrcoef(outcomes, values)[0, 1])

            # Predictive power (t-stat approximation)
            if winners and losers and len(winners) >= 2 and len(losers) >= 2:
                win_vals = np.array([t.component_scores[component] for t in winners])
                loss_vals = np.array([t.component_scores[component] for t in losers])

                mean_diff = np.mean(win_vals) - np.mean(loss_vals)
                pooled_std = np.sqrt((np.var(win_vals) + np.var(loss_vals)) / 2)

                if pooled_std > 0:
                    cw.predictive_power = float(mean_diff / pooled_std)
        except Exception:
            pass

        # Calculate optimal weight
        if cw.correlation > 0.1:
            cw.optimal_weight = 1.0 + (cw.correlation * 0.5)
        elif cw.correlation < -0.1:
            cw.optimal_weight = 1.0 + (cw.correlation * 0.3)
        else:
            cw.optimal_weight = 1.0

        cw.optimal_weight = max(0.5, min(2.0, cw.optimal_weight))

        component_weights[component] = cw

    # Calculate win rates
    train_wins = sum(1 for t in train_trades if t.outcome == 1)
    test_wins = sum(1 for t in test_trades if t.outcome == 1)

    train_wr = (train_wins / len(train_trades) * 100) if train_trades else 0
    test_wr = (test_wins / len(test_trades) * 100) if test_trades else 0

    return {
        'strategy': strategy,
        'status': 'success',
        'train_trades': len(train_trades),
        'test_trades': len(test_trades),
        'train_win_rate': train_wr,
        'test_win_rate': test_wr,
        'degradation': train_wr - test_wr,
        'components': {
            k: {
                'samples': v.samples,
                'correlation': v.correlation,
                'predictive_power': v.predictive_power,
                'avg_when_win': v.avg_when_win,
                'avg_when_loss': v.avg_when_loss,
                'optimal_weight': v.optimal_weight,
            }
            for k, v in sorted(
                component_weights.items(),
                key=lambda x: abs(x[1].correlation),
                reverse=True
            )
        }
    }


def main():
    parser = argparse.ArgumentParser(description='Fast component weight training')
    parser.add_argument('--strategy', choices=STRATEGIES + ['all'], default='all')
    parser.add_argument('--train-months', type=int, default=12)
    parser.add_argument('--test-months', type=int, default=3)
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    print("=" * 70)
    print("  OPTIONPLAY FAST COMPONENT WEIGHT TRAINING")
    print("=" * 70)

    # Load data
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    print(f"\n  Database Stats:")
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

    print(f"  Loaded: {len(historical_data)} symbols")

    # Train each strategy
    strategies = [args.strategy] if args.strategy != 'all' else STRATEGIES
    all_results = {}

    for strategy in strategies:
        print(f"\n{'='*70}")
        print(f"  TRAINING: {strategy.upper()}")
        print("=" * 70)

        result = train_strategy_fast(
            strategy=strategy,
            historical_data=historical_data,
            vix_data=vix_data,
            train_months=args.train_months,
            test_months=args.test_months,
        )

        all_results[strategy] = result

        if result.get('status') == 'success':
            print(f"\n    Results:")
            print(f"      Train Win Rate: {result['train_win_rate']:.1f}%")
            print(f"      Test Win Rate:  {result['test_win_rate']:.1f}%")
            print(f"      Degradation:    {result['degradation']:+.1f}%")

            if result.get('components'):
                print(f"\n    Top Components by Correlation:")
                print(f"    {'Component':<25} {'Corr':>8} {'Pred':>8} {'Weight':>8}")
                print("    " + "-" * 53)

                for i, (name, comp) in enumerate(result['components'].items()):
                    if i >= 8:  # Top 8
                        break
                    print(f"    {name:<25} {comp['correlation']:>+7.3f} "
                          f"{comp['predictive_power']:>+7.3f} {comp['optimal_weight']:>7.2f}")

    # Summary
    print(f"\n{'='*70}")
    print("  SUMMARY")
    print("=" * 70)

    print(f"\n  {'Strategy':<15} {'Train%':>10} {'Test%':>10} {'Degrad':>10} {'Status':<15}")
    print("  " + "-" * 60)

    for strategy, result in all_results.items():
        if result.get('status') == 'success':
            print(f"  {strategy:<15} "
                  f"{result['train_win_rate']:>9.1f}% "
                  f"{result['test_win_rate']:>9.1f}% "
                  f"{result['degradation']:>+9.1f}% "
                  f"{'OK' if result['degradation'] < 10 else 'OVERFIT':<15}")
        else:
            print(f"  {strategy:<15} {'N/A':>10} {'N/A':>10} {'N/A':>10} {result.get('status', 'unknown'):<15}")

    # Save results
    output_dir = Path.home() / '.optionplay' / 'models'
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save component weights
    weights_data = {
        'version': '1.0.0',
        'created_at': datetime.now().isoformat(),
        'strategies': {}
    }

    for strategy, result in all_results.items():
        if result.get('status') == 'success':
            weights_data['strategies'][strategy] = {
                'component_weights': {
                    k: v['optimal_weight']
                    for k, v in result.get('components', {}).items()
                },
                'validation': {
                    'train_trades': result['train_trades'],
                    'test_trades': result['test_trades'],
                    'train_win_rate': result['train_win_rate'],
                    'test_win_rate': result['test_win_rate'],
                    'degradation': result['degradation'],
                },
                'component_stats': result.get('components', {})
            }

    weights_path = output_dir / 'component_weights.json'
    with open(weights_path, 'w') as f:
        json.dump(weights_data, f, indent=2)

    print(f"\n  Weights saved to: {weights_path}")

    # Export for production
    if args.export:
        export_path = output_dir / 'production_weights.json'
        prod_data = {
            'version': '1.0.0',
            'created_at': datetime.now().isoformat(),
            'strategies': {
                s: {
                    'component_weights': {
                        k: v['optimal_weight']
                        for k, v in r.get('components', {}).items()
                    }
                }
                for s, r in all_results.items()
                if r.get('status') == 'success'
            }
        }
        with open(export_path, 'w') as f:
            json.dump(prod_data, f, indent=2)
        print(f"  Production export: {export_path}")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    main()
