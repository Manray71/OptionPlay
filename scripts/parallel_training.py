#!/usr/bin/env python3
"""
OptionPlay - Parallel Training (M2 Optimized)
==============================================

Utilizes all 12 CPU cores for maximum performance:
- Parallel symbol processing
- Parallel strategy evaluation
- Parallel epoch processing

Optimized for M2 with 32GB RAM
"""

import json
import sys
import warnings
import logging
import multiprocessing as mp
from multiprocessing import Pool, Manager
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import statistics
import traceback
import os

# Set multiprocessing start method for macOS
if sys.platform == 'darwin':
    mp.set_start_method('fork', force=True)

warnings.filterwarnings('ignore')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

# Setup
LOG_DIR = Path.home() / '.optionplay'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'parallel_training.log'
OUTPUT_DIR = LOG_DIR / 'models'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']
VIX_REGIMES = {'low': (0, 15), 'normal': (15, 20), 'elevated': (20, 30), 'high': (30, 100)}
MIN_SCORES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]
NUM_WORKERS = 10  # Leave 2 cores for system


def get_regime(vix: float) -> str:
    for regime, (low, high) in VIX_REGIMES.items():
        if low <= vix < high:
            return regime
    return 'high'


def create_analyzer(strategy: str):
    """Create analyzer - must be called within worker process"""
    from src.config.config_loader import PullbackScoringConfig
    from src.analyzers.pullback import PullbackAnalyzer
    from src.analyzers.bounce import BounceAnalyzer, BounceConfig
    from src.analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
    from src.analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig

    if strategy == 'pullback':
        return PullbackAnalyzer(PullbackScoringConfig())
    elif strategy == 'bounce':
        return BounceAnalyzer(BounceConfig())
    elif strategy == 'ath_breakout':
        return ATHBreakoutAnalyzer(ATHBreakoutConfig())
    elif strategy == 'earnings_dip':
        return EarningsDipAnalyzer(EarningsDipConfig())
    raise ValueError(f"Unknown strategy: {strategy}")


def simulate_trade(entry_price: float, future_bars: List[Dict], holding_days: int = 30) -> Tuple[int, float]:
    """Simulate Bull-Put-Spread"""
    if len(future_bars) < 15:
        return 0, 0.0

    short_strike = entry_price * 0.92
    long_strike = short_strike - (entry_price * 0.05)
    spread_width = short_strike - long_strike
    net_credit = spread_width * 0.20

    max_profit = net_credit * 100
    max_loss = (spread_width - net_credit) * 100

    for day, bar in enumerate(future_bars[:holding_days]):
        if bar['low'] < long_strike:
            return 0, -max_loss
        if day >= 14 and bar['close'] >= entry_price:
            return 1, max_profit * 0.5

    final_price = future_bars[min(holding_days-1, len(future_bars)-1)]['close']

    if final_price >= short_strike:
        return 1, max_profit
    elif final_price >= long_strike:
        intrinsic = short_strike - final_price
        return (1 if net_credit > intrinsic else 0), (net_credit - intrinsic) * 100
    else:
        return 0, -max_loss


def analyze_symbol_worker(args: Tuple) -> Dict[str, Any]:
    """Worker function to analyze a single symbol - runs in parallel"""
    symbol, symbol_data, vix_data, strategies = args

    from src.models.base import SignalType

    results = {
        'symbol': symbol,
        'total_trades': 0,
        'total_wins': 0,
        'total_pnl': 0.0,
        'strategies': {},
        'best_strategy': '',
        'best_strategy_wr': 0.0
    }

    if len(symbol_data) < 300:
        return results

    # Sort data
    sorted_data = sorted(
        symbol_data,
        key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
    )

    for bar in sorted_data:
        if isinstance(bar['date'], str):
            bar['date'] = date.fromisoformat(bar['date'])

    # Split train/test
    split_idx = int(len(sorted_data) * 0.8)

    for strategy in strategies:
        try:
            analyzer = create_analyzer(strategy)
        except Exception:
            continue

        strat_results = {
            'train_trades': 0, 'train_wins': 0, 'train_pnl': 0.0,
            'test_trades': 0, 'test_wins': 0, 'test_pnl': 0.0,
            'by_score': defaultdict(lambda: {'trades': 0, 'wins': 0}),
            'by_regime': defaultdict(lambda: {'trades': 0, 'wins': 0})
        }

        # Analyze every 2nd day for speed
        for idx in range(250, len(sorted_data) - 40, 2):
            history = sorted_data[max(0, idx-259):idx]
            future = sorted_data[idx:idx+40]

            if len(history) < 200 or len(future) < 30:
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

            if signal.signal_type != SignalType.LONG or signal.score < 5.0:
                continue

            current_date = sorted_data[idx]['date']
            vix = vix_data.get(current_date, 20.0)
            regime = get_regime(vix)

            outcome, pnl = simulate_trade(prices[-1], future, 30)

            is_train = idx < split_idx

            if is_train:
                strat_results['train_trades'] += 1
                strat_results['train_wins'] += outcome
                strat_results['train_pnl'] += pnl
            else:
                strat_results['test_trades'] += 1
                strat_results['test_wins'] += outcome
                strat_results['test_pnl'] += pnl

            score_bucket = int(signal.score)
            strat_results['by_score'][score_bucket]['trades'] += 1
            strat_results['by_score'][score_bucket]['wins'] += outcome

            strat_results['by_regime'][regime]['trades'] += 1
            strat_results['by_regime'][regime]['wins'] += outcome

        # Calculate totals
        total = strat_results['train_trades'] + strat_results['test_trades']
        wins = strat_results['train_wins'] + strat_results['test_wins']

        if total >= 10:
            wr = wins / total * 100
            train_wr = strat_results['train_wins'] / strat_results['train_trades'] * 100 if strat_results['train_trades'] > 0 else 0
            test_wr = strat_results['test_wins'] / strat_results['test_trades'] * 100 if strat_results['test_trades'] > 0 else 0

            results['strategies'][strategy] = {
                'trades': total,
                'wins': wins,
                'win_rate': wr,
                'pnl': strat_results['train_pnl'] + strat_results['test_pnl'],
                'train_wr': train_wr,
                'test_wr': test_wr,
                'degradation': train_wr - test_wr,
                'by_score': dict(strat_results['by_score']),
                'by_regime': dict(strat_results['by_regime'])
            }

            results['total_trades'] += total
            results['total_wins'] += wins
            results['total_pnl'] += strat_results['train_pnl'] + strat_results['test_pnl']

            if wr > results['best_strategy_wr'] and total >= 20:
                results['best_strategy'] = strategy
                results['best_strategy_wr'] = wr

    return results


def walk_forward_epoch_worker(args: Tuple) -> Dict[str, Any]:
    """Worker for single walk-forward epoch"""
    strategy, symbols_data, vix_data, train_start, train_end, test_start, test_end, epoch_id = args

    from src.models.base import SignalType

    result = {
        'epoch_id': epoch_id,
        'strategy': strategy,
        'train_start': str(train_start),
        'train_end': str(train_end),
        'test_start': str(test_start),
        'test_end': str(test_end),
        'best_score': 5.0,
        'train_trades': 0,
        'train_wins': 0,
        'test_trades': 0,
        'test_wins': 0
    }

    try:
        analyzer = create_analyzer(strategy)
    except Exception as e:
        return result

    # Find best score on training data
    best_score = 5.0
    best_train_wr = 0

    for min_score in MIN_SCORES:
        train_trades = 0
        train_wins = 0

        for symbol, symbol_data in symbols_data.items():
            if len(symbol_data) < 300:
                continue

            sorted_data = sorted(
                symbol_data,
                key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
            )

            for bar in sorted_data:
                if isinstance(bar['date'], str):
                    bar['date'] = date.fromisoformat(bar['date'])

            for idx in range(250, len(sorted_data) - 40, 3):  # Every 3rd day
                current_date = sorted_data[idx]['date']

                if current_date < train_start or current_date > train_end:
                    continue

                history = sorted_data[max(0, idx-259):idx]
                future = sorted_data[idx:idx+40]

                if len(history) < 200 or len(future) < 30:
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

                if signal.signal_type != SignalType.LONG or signal.score < min_score:
                    continue

                outcome, _ = simulate_trade(prices[-1], future, 30)
                train_trades += 1
                train_wins += outcome

        if train_trades >= 30:
            wr = train_wins / train_trades * 100
            if wr > best_train_wr:
                best_train_wr = wr
                best_score = min_score
                result['train_trades'] = train_trades
                result['train_wins'] = train_wins

    result['best_score'] = best_score

    # Test with best score
    test_trades = 0
    test_wins = 0

    for symbol, symbol_data in symbols_data.items():
        if len(symbol_data) < 300:
            continue

        sorted_data = sorted(
            symbol_data,
            key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
        )

        for bar in sorted_data:
            if isinstance(bar['date'], str):
                bar['date'] = date.fromisoformat(bar['date'])

        for idx in range(250, len(sorted_data) - 40, 2):
            current_date = sorted_data[idx]['date']

            if current_date < test_start or current_date > test_end:
                continue

            history = sorted_data[max(0, idx-259):idx]
            future = sorted_data[idx:idx+40]

            if len(history) < 200 or len(future) < 30:
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

            if signal.signal_type != SignalType.LONG or signal.score < best_score:
                continue

            outcome, _ = simulate_trade(prices[-1], future, 30)
            test_trades += 1
            test_wins += outcome

    result['test_trades'] = test_trades
    result['test_wins'] = test_wins

    return result


def save_progress(phase: str, detail: str, stats: Dict):
    """Save progress to file"""
    progress = {
        'timestamp': datetime.now().isoformat(),
        'phase': phase,
        'detail': detail,
        'workers': NUM_WORKERS,
        **stats
    }
    with open(OUTPUT_DIR / 'parallel_progress.json', 'w') as f:
        json.dump(progress, f, indent=2)


def main():
    """Main parallel training pipeline"""

    start_time = datetime.now()

    logger.info("=" * 70)
    logger.info("  PARALLEL TRAINING (M2 OPTIMIZED)")
    logger.info(f"  Workers: {NUM_WORKERS} / 12 cores")
    logger.info(f"  Started: {start_time}")
    logger.info("=" * 70)

    # Load data
    logger.info("\nLoading data...")

    from src.backtesting import TradeTracker

    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    logger.info(f"  Symbols: {stats['symbols_with_price_data']}")
    logger.info(f"  Price Bars: {stats['total_price_bars']:,}")

    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_info]

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

    vix_data = {}
    for p in tracker.get_vix_data():
        vix_data[p.date] = p.value

    logger.info(f"  Loaded: {len(historical_data)} symbols")

    # =========================================================================
    # PHASE 1: PARALLEL WALK-FORWARD
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  PHASE 1: PARALLEL WALK-FORWARD VALIDATION")
    logger.info("=" * 70)

    # Find date range
    all_dates = set()
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
            all_dates.add(d)

    min_date = min(all_dates)
    max_date = max(all_dates)

    # Generate epochs
    epochs_args = []
    epoch_id = 0

    for strategy in STRATEGIES:
        current_start = min_date + timedelta(days=200)

        while True:
            train_end = current_start + timedelta(days=365)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=90)

            if test_end > max_date:
                break

            epoch_id += 1
            epochs_args.append((
                strategy, historical_data, vix_data,
                current_start, train_end, test_start, test_end, epoch_id
            ))

            current_start += timedelta(days=90)

    logger.info(f"  Total epochs to process: {len(epochs_args)}")
    save_progress("Walk-Forward", "Starting", {'total_epochs': len(epochs_args)})

    # Run in parallel
    wf_results = []
    with Pool(NUM_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(walk_forward_epoch_worker, epochs_args)):
            wf_results.append(result)

            if (i + 1) % 10 == 0:
                logger.info(f"  Completed {i+1}/{len(epochs_args)} epochs")
                save_progress("Walk-Forward", f"Epoch {i+1}/{len(epochs_args)}", {
                    'completed': i + 1,
                    'total': len(epochs_args)
                })

    # Aggregate walk-forward results
    wf_aggregation = defaultdict(lambda: {
        'epochs': [],
        'train_trades': 0, 'train_wins': 0,
        'test_trades': 0, 'test_wins': 0,
        'best_scores': []
    })

    for r in wf_results:
        strat = r['strategy']
        wf_aggregation[strat]['epochs'].append(r)
        wf_aggregation[strat]['train_trades'] += r['train_trades']
        wf_aggregation[strat]['train_wins'] += r['train_wins']
        wf_aggregation[strat]['test_trades'] += r['test_trades']
        wf_aggregation[strat]['test_wins'] += r['test_wins']
        wf_aggregation[strat]['best_scores'].append(r['best_score'])

    logger.info("\n  Walk-Forward Results:")
    for strategy, data in wf_aggregation.items():
        train_wr = data['train_wins'] / data['train_trades'] * 100 if data['train_trades'] > 0 else 0
        test_wr = data['test_wins'] / data['test_trades'] * 100 if data['test_trades'] > 0 else 0
        avg_score = statistics.mean(data['best_scores']) if data['best_scores'] else 6.0

        logger.info(f"    {strategy}:")
        logger.info(f"      Train: {train_wr:.1f}%, Test: {test_wr:.1f}%, Deg: {train_wr-test_wr:+.1f}%")
        logger.info(f"      Avg Best Score: {avg_score:.1f}")

    # =========================================================================
    # PHASE 2: PARALLEL PER-SYMBOL ANALYSIS
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  PHASE 2: PARALLEL PER-SYMBOL ANALYSIS")
    logger.info("=" * 70)

    # Prepare args for parallel processing
    symbol_args = [
        (symbol, historical_data[symbol], vix_data, STRATEGIES)
        for symbol in historical_data.keys()
    ]

    logger.info(f"  Analyzing {len(symbol_args)} symbols with {NUM_WORKERS} workers...")
    save_progress("Per-Symbol", "Starting", {'total_symbols': len(symbol_args)})

    # Run in parallel
    symbol_results = []
    with Pool(NUM_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(analyze_symbol_worker, symbol_args)):
            if result['total_trades'] >= 10:
                symbol_results.append(result)

            if (i + 1) % 50 == 0:
                logger.info(f"  Completed {i+1}/{len(symbol_args)} symbols")
                save_progress("Per-Symbol", f"Symbol {i+1}/{len(symbol_args)}", {
                    'completed': i + 1,
                    'total': len(symbol_args),
                    'valid_symbols': len(symbol_results)
                })

    logger.info(f"  Valid symbols with data: {len(symbol_results)}")

    # =========================================================================
    # PHASE 3: AGGREGATE AND SAVE
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  PHASE 3: AGGREGATION AND EXPORT")
    logger.info("=" * 70)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Calculate final statistics
    total_trades = sum(r['total_trades'] for r in symbol_results)
    total_wins = sum(r['total_wins'] for r in symbol_results)
    total_pnl = sum(r['total_pnl'] for r in symbol_results)

    # Strategy aggregation
    strategy_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
    for r in symbol_results:
        for strat, data in r['strategies'].items():
            strategy_stats[strat]['trades'] += data['trades']
            strategy_stats[strat]['wins'] += data['wins']
            strategy_stats[strat]['pnl'] += data['pnl']

    # Find stable symbols
    stable_symbols = [
        r for r in symbol_results
        if any(abs(s.get('degradation', 100)) < 10 for s in r['strategies'].values())
    ]

    # Create final config
    final_config = {
        'version': '6.0.0',
        'created_at': datetime.now().isoformat(),
        'training_type': 'parallel_walkforward_persymbol',
        'training_duration_minutes': (datetime.now() - start_time).total_seconds() / 60,
        'workers_used': NUM_WORKERS,

        'summary': {
            'total_trades': total_trades,
            'total_wins': total_wins,
            'win_rate': total_wins / total_trades * 100 if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'symbols_analyzed': len(symbol_results),
            'stable_symbols': len(stable_symbols)
        },

        'strategies': {},
        'symbol_recommendations': {}
    }

    # Strategy configs
    for strategy in STRATEGIES:
        wf_data = wf_aggregation.get(strategy, {})
        strat_stats = strategy_stats.get(strategy, {})

        train_wr = wf_data['train_wins'] / wf_data['train_trades'] * 100 if wf_data.get('train_trades', 0) > 0 else 0
        test_wr = wf_data['test_wins'] / wf_data['test_trades'] * 100 if wf_data.get('test_trades', 0) > 0 else 0
        overall_wr = strat_stats['wins'] / strat_stats['trades'] * 100 if strat_stats.get('trades', 0) > 0 else 0

        recommended_score = statistics.mode(wf_data.get('best_scores', [6.0])) if wf_data.get('best_scores') else 6.0

        final_config['strategies'][strategy] = {
            'enabled': True,
            'min_score': recommended_score,
            'train_win_rate': train_wr,
            'test_win_rate': test_wr,
            'overall_win_rate': overall_wr,
            'degradation': train_wr - test_wr,
            'stable': abs(train_wr - test_wr) < 10,
            'total_trades': strat_stats.get('trades', 0),
            'total_pnl': strat_stats.get('pnl', 0)
        }

    # Top symbol recommendations
    top_symbols = sorted(symbol_results, key=lambda x: x['best_strategy_wr'], reverse=True)[:50]
    for r in top_symbols:
        if r['best_strategy']:
            final_config['symbol_recommendations'][r['symbol']] = {
                'best_strategy': r['best_strategy'],
                'win_rate': r['best_strategy_wr'],
                'total_trades': r['total_trades']
            }

    # Save results
    with open(OUTPUT_DIR / f'parallel_results_{timestamp}.json', 'w') as f:
        json.dump({
            'wf_aggregation': {k: {**v, 'epochs': [dict(e) for e in v['epochs']]} for k, v in wf_aggregation.items()},
            'strategy_stats': dict(strategy_stats)
        }, f, indent=2, default=str)

    with open(OUTPUT_DIR / f'parallel_symbols_{timestamp}.json', 'w') as f:
        json.dump(symbol_results, f, indent=2, default=str)

    with open(OUTPUT_DIR / 'PARALLEL_FINAL_CONFIG.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    # Final summary
    duration = (datetime.now() - start_time).total_seconds() / 60

    logger.info(f"\n  Results saved to {OUTPUT_DIR}")

    logger.info("\n" + "=" * 70)
    logger.info("  PARALLEL TRAINING COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Duration: {duration:.1f} minutes")
    logger.info(f"  Workers: {NUM_WORKERS}")
    logger.info(f"  Total Trades: {total_trades:,}")
    logger.info(f"  Overall Win Rate: {total_wins/total_trades*100:.1f}%")
    logger.info(f"  Total P&L: ${total_pnl:,.0f}")

    logger.info("\n  Strategy Results:")
    for strategy, config in final_config['strategies'].items():
        logger.info(f"    {strategy}:")
        logger.info(f"      Min Score: {config['min_score']}")
        logger.info(f"      Train WR: {config['train_win_rate']:.1f}%")
        logger.info(f"      Test WR: {config['test_win_rate']:.1f}%")
        logger.info(f"      Stable: {'Yes' if config['stable'] else 'No'}")

    logger.info("\n" + "=" * 70)

    save_progress("Complete", "Done", {
        'duration_minutes': duration,
        'total_trades': total_trades,
        'win_rate': total_wins / total_trades * 100 if total_trades > 0 else 0
    })


if __name__ == '__main__':
    main()
