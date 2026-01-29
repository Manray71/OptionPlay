#!/usr/bin/env python3
"""
OptionPlay - Walk-Forward + Per-Symbol Training
================================================

Comprehensive training combining:
1. Walk-Forward Validation (prevents overfitting)
   - Multiple train/test periods
   - Rolling windows
   - Out-of-sample validation

2. Per-Symbol Specialization
   - Individual optimal parameters per symbol
   - Symbol-strategy affinity scoring
   - Sector-based patterns

Progress logged to ~/.optionplay/walkforward_training.log
"""

import json
import sys
import warnings
import logging
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import statistics
import traceback
import numpy as np

warnings.filterwarnings('ignore')

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

# Setup
LOG_DIR = Path.home() / '.optionplay'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'walkforward_training.log'
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

STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']
VIX_REGIMES = {'low': (0, 15), 'normal': (15, 20), 'elevated': (20, 30), 'high': (30, 100)}
MIN_SCORES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]


@dataclass
class WalkForwardEpoch:
    """Single walk-forward epoch results"""
    epoch_id: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    # Training results
    train_trades: int = 0
    train_wins: int = 0
    train_pnl: float = 0.0
    best_params: Dict[str, Any] = field(default_factory=dict)

    # Test results (out-of-sample)
    test_trades: int = 0
    test_wins: int = 0
    test_pnl: float = 0.0

    def train_win_rate(self) -> float:
        return self.train_wins / self.train_trades * 100 if self.train_trades > 0 else 0

    def test_win_rate(self) -> float:
        return self.test_wins / self.test_trades * 100 if self.test_trades > 0 else 0

    def degradation(self) -> float:
        return self.train_win_rate() - self.test_win_rate()


@dataclass
class SymbolProfile:
    """Per-symbol trading profile"""
    symbol: str
    total_trades: int = 0
    total_wins: int = 0
    total_pnl: float = 0.0

    best_strategy: str = ""
    best_strategy_trades: int = 0
    best_strategy_win_rate: float = 0.0

    optimal_min_score: float = 6.0
    optimal_holding_days: int = 30

    strategy_performance: Dict[str, Dict] = field(default_factory=dict)
    regime_performance: Dict[str, Dict] = field(default_factory=dict)

    # Walk-forward validation
    wf_train_wr: float = 0.0
    wf_test_wr: float = 0.0
    wf_degradation: float = 0.0
    wf_stable: bool = False  # True if degradation < 10%


@dataclass
class TrainingProgress:
    """Track training progress"""
    start_time: datetime = field(default_factory=datetime.now)
    phase: str = "initializing"
    current_task: str = ""
    epochs_completed: int = 0
    total_epochs: int = 0
    symbols_processed: int = 0
    total_symbols: int = 0
    trades_analyzed: int = 0

    def elapsed_hours(self) -> float:
        return (datetime.now() - self.start_time).total_seconds() / 3600

    def save(self):
        with open(OUTPUT_DIR / 'walkforward_progress.json', 'w') as f:
            json.dump({
                'start_time': self.start_time.isoformat(),
                'elapsed_hours': round(self.elapsed_hours(), 2),
                'phase': self.phase,
                'current_task': self.current_task,
                'epochs_completed': self.epochs_completed,
                'total_epochs': self.total_epochs,
                'symbols_processed': self.symbols_processed,
                'total_symbols': self.total_symbols,
                'trades_analyzed': self.trades_analyzed
            }, f, indent=2)


def get_regime(vix: float) -> str:
    for regime, (low, high) in VIX_REGIMES.items():
        if low <= vix < high:
            return regime
    return 'high'


def create_analyzer(strategy: str):
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


def backtest_period(
    symbols_data: Dict[str, List[Dict]],
    vix_data: Dict[date, float],
    strategy: str,
    analyzer,
    start_date: date,
    end_date: date,
    min_score: float = 5.0,
    holding_days: int = 30,
    sample_rate: int = 2
) -> Dict[str, Any]:
    """Backtest a strategy over a specific period"""

    results = {
        'trades': 0,
        'wins': 0,
        'pnl': 0.0,
        'by_symbol': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0}),
        'by_regime': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0}),
        'by_score': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
    }

    for symbol, symbol_data in symbols_data.items():
        if len(symbol_data) < 300:
            continue

        # Sort data
        sorted_data = sorted(
            symbol_data,
            key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
        )

        for bar in sorted_data:
            if isinstance(bar['date'], str):
                bar['date'] = date.fromisoformat(bar['date'])

        # Find indices within period
        for idx in range(250, len(sorted_data) - holding_days - 10, sample_rate):
            current_date = sorted_data[idx]['date']

            if current_date < start_date or current_date > end_date:
                continue

            history = sorted_data[max(0, idx-259):idx]
            future = sorted_data[idx:idx+holding_days+10]

            if len(history) < 200 or len(future) < holding_days:
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

            vix = vix_data.get(current_date, 20.0)
            regime = get_regime(vix)

            outcome, pnl = simulate_trade(prices[-1], future, holding_days)

            results['trades'] += 1
            results['wins'] += outcome
            results['pnl'] += pnl

            results['by_symbol'][symbol]['trades'] += 1
            results['by_symbol'][symbol]['wins'] += outcome
            results['by_symbol'][symbol]['pnl'] += pnl

            results['by_regime'][regime]['trades'] += 1
            results['by_regime'][regime]['wins'] += outcome
            results['by_regime'][regime]['pnl'] += pnl

            score_bucket = int(signal.score)
            results['by_score'][score_bucket]['trades'] += 1
            results['by_score'][score_bucket]['wins'] += outcome
            results['by_score'][score_bucket]['pnl'] += pnl

    return results


def run_walk_forward(
    symbols_data: Dict[str, List[Dict]],
    vix_data: Dict[date, float],
    strategy: str,
    progress: TrainingProgress,
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3
) -> List[WalkForwardEpoch]:
    """Run walk-forward validation for a strategy"""

    # Find date range
    all_dates = set()
    for sym_data in symbols_data.values():
        for bar in sym_data:
            d = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
            all_dates.add(d)

    if not all_dates:
        return []

    min_date = min(all_dates)
    max_date = max(all_dates)

    epochs = []
    analyzer = create_analyzer(strategy)

    current_start = min_date + timedelta(days=200)
    epoch_id = 0

    while True:
        train_end = current_start + timedelta(days=train_months * 30)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_months * 30)

        if test_end > max_date:
            break

        epoch_id += 1
        progress.current_task = f"{strategy} Epoch {epoch_id}"
        progress.save()

        epoch = WalkForwardEpoch(
            epoch_id=epoch_id,
            train_start=current_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end
        )

        # Find best parameters on training data
        best_score = 5.0
        best_train_wr = 0

        for min_score in MIN_SCORES:
            train_results = backtest_period(
                symbols_data, vix_data, strategy, analyzer,
                current_start, train_end,
                min_score=min_score,
                sample_rate=3  # Faster sampling for parameter search
            )

            if train_results['trades'] >= 50:
                wr = train_results['wins'] / train_results['trades'] * 100
                if wr > best_train_wr:
                    best_train_wr = wr
                    best_score = min_score
                    epoch.train_trades = train_results['trades']
                    epoch.train_wins = train_results['wins']
                    epoch.train_pnl = train_results['pnl']

        epoch.best_params = {'min_score': best_score}

        # Test on out-of-sample data with best parameters
        test_results = backtest_period(
            symbols_data, vix_data, strategy, analyzer,
            test_start, test_end,
            min_score=best_score,
            sample_rate=2
        )

        epoch.test_trades = test_results['trades']
        epoch.test_wins = test_results['wins']
        epoch.test_pnl = test_results['pnl']

        progress.trades_analyzed += epoch.train_trades + epoch.test_trades

        epochs.append(epoch)
        progress.epochs_completed += 1

        logger.info(f"    Epoch {epoch_id}: Train {epoch.train_win_rate():.1f}% -> Test {epoch.test_win_rate():.1f}% "
                   f"(deg: {epoch.degradation():+.1f}%, score>={best_score})")

        current_start += timedelta(days=step_months * 30)

    return epochs


def analyze_symbol_detailed(
    symbol: str,
    symbol_data: List[Dict],
    vix_data: Dict[date, float],
    progress: TrainingProgress
) -> SymbolProfile:
    """Detailed analysis for a single symbol across all strategies"""

    profile = SymbolProfile(symbol=symbol)

    if len(symbol_data) < 300:
        return profile

    # Sort data
    sorted_data = sorted(
        symbol_data,
        key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
    )

    for bar in sorted_data:
        if isinstance(bar['date'], str):
            bar['date'] = date.fromisoformat(bar['date'])

    # Split into train/test (80/20)
    split_idx = int(len(sorted_data) * 0.8)

    for strategy in STRATEGIES:
        try:
            analyzer = create_analyzer(strategy)
        except Exception:
            continue

        train_results = {'trades': 0, 'wins': 0, 'pnl': 0.0}
        test_results = {'trades': 0, 'wins': 0, 'pnl': 0.0}
        score_results = defaultdict(lambda: {'trades': 0, 'wins': 0})
        regime_results = defaultdict(lambda: {'trades': 0, 'wins': 0})

        for idx in range(250, len(sorted_data) - 40, 2):
            history = sorted_data[max(0, idx-259):idx]
            future = sorted_data[idx:idx+40]

            if len(history) < 200 or len(future) < 30:
                continue

            current_date = sorted_data[idx]['date']

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

            vix = vix_data.get(current_date, 20.0)
            regime = get_regime(vix)

            outcome, pnl = simulate_trade(prices[-1], future, 30)

            is_train = idx < split_idx

            if is_train:
                train_results['trades'] += 1
                train_results['wins'] += outcome
                train_results['pnl'] += pnl
            else:
                test_results['trades'] += 1
                test_results['wins'] += outcome
                test_results['pnl'] += pnl

            score_bucket = int(signal.score)
            score_results[score_bucket]['trades'] += 1
            score_results[score_bucket]['wins'] += outcome

            regime_results[regime]['trades'] += 1
            regime_results[regime]['wins'] += outcome

            profile.total_trades += 1
            profile.total_wins += outcome
            profile.total_pnl += pnl
            progress.trades_analyzed += 1

        # Store strategy performance
        total_trades = train_results['trades'] + test_results['trades']
        total_wins = train_results['wins'] + test_results['wins']

        if total_trades >= 10:
            profile.strategy_performance[strategy] = {
                'trades': total_trades,
                'wins': total_wins,
                'win_rate': total_wins / total_trades * 100,
                'pnl': train_results['pnl'] + test_results['pnl'],
                'train_wr': train_results['wins'] / train_results['trades'] * 100 if train_results['trades'] > 0 else 0,
                'test_wr': test_results['wins'] / test_results['trades'] * 100 if test_results['trades'] > 0 else 0
            }

            # Check if this is the best strategy
            wr = total_wins / total_trades * 100
            if wr > profile.best_strategy_win_rate and total_trades >= 20:
                profile.best_strategy = strategy
                profile.best_strategy_trades = total_trades
                profile.best_strategy_win_rate = wr

        # Find optimal min score
        best_score_wr = 0
        for score, data in score_results.items():
            if data['trades'] >= 10:
                wr = data['wins'] / data['trades'] * 100
                if wr > best_score_wr:
                    best_score_wr = wr
                    profile.optimal_min_score = float(score)

        # Regime performance
        for regime, data in regime_results.items():
            if data['trades'] >= 5:
                profile.regime_performance[regime] = {
                    'trades': data['trades'],
                    'wins': data['wins'],
                    'win_rate': data['wins'] / data['trades'] * 100
                }

    # Calculate walk-forward metrics
    if profile.strategy_performance:
        train_wrs = [d['train_wr'] for d in profile.strategy_performance.values() if d['trades'] >= 10]
        test_wrs = [d['test_wr'] for d in profile.strategy_performance.values() if d['trades'] >= 10]

        if train_wrs and test_wrs:
            profile.wf_train_wr = statistics.mean(train_wrs)
            profile.wf_test_wr = statistics.mean(test_wrs)
            profile.wf_degradation = profile.wf_train_wr - profile.wf_test_wr
            profile.wf_stable = abs(profile.wf_degradation) < 10

    return profile


def aggregate_walk_forward_results(
    wf_results: Dict[str, List[WalkForwardEpoch]]
) -> Dict[str, Any]:
    """Aggregate walk-forward results across strategies"""

    aggregation = {}

    for strategy, epochs in wf_results.items():
        if not epochs:
            continue

        total_train = sum(e.train_trades for e in epochs)
        total_train_wins = sum(e.train_wins for e in epochs)
        total_test = sum(e.test_trades for e in epochs)
        total_test_wins = sum(e.test_wins for e in epochs)

        train_wr = total_train_wins / total_train * 100 if total_train > 0 else 0
        test_wr = total_test_wins / total_test * 100 if total_test > 0 else 0

        # Find most common best params
        param_counts = defaultdict(int)
        for e in epochs:
            score = e.best_params.get('min_score', 5.0)
            param_counts[score] += 1

        best_score = max(param_counts.keys(), key=lambda x: param_counts[x]) if param_counts else 6.0

        aggregation[strategy] = {
            'epochs': len(epochs),
            'total_train_trades': total_train,
            'total_test_trades': total_test,
            'train_win_rate': train_wr,
            'test_win_rate': test_wr,
            'degradation': train_wr - test_wr,
            'stable': abs(train_wr - test_wr) < 10,
            'recommended_min_score': best_score,
            'epoch_details': [
                {
                    'id': e.epoch_id,
                    'train_period': f"{e.train_start} to {e.train_end}",
                    'test_period': f"{e.test_start} to {e.test_end}",
                    'train_wr': e.train_win_rate(),
                    'test_wr': e.test_win_rate(),
                    'degradation': e.degradation(),
                    'best_score': e.best_params.get('min_score', 5.0)
                }
                for e in epochs
            ]
        }

    return aggregation


def create_final_config(
    wf_aggregation: Dict[str, Any],
    symbol_profiles: Dict[str, SymbolProfile]
) -> Dict[str, Any]:
    """Create final production configuration"""

    config = {
        'version': '5.0.0',
        'created_at': datetime.now().isoformat(),
        'training_type': 'walk_forward_per_symbol',
        'strategies': {},
        'symbol_recommendations': {},
        'regime_adjustments': {}
    }

    # Strategy configs from walk-forward
    for strategy, wf_data in wf_aggregation.items():
        config['strategies'][strategy] = {
            'enabled': True,
            'min_score': wf_data['recommended_min_score'],
            'train_win_rate': wf_data['train_win_rate'],
            'test_win_rate': wf_data['test_win_rate'],
            'degradation': wf_data['degradation'],
            'stable': wf_data['stable'],
            'epochs_tested': wf_data['epochs']
        }

    # Symbol recommendations
    stable_symbols = []
    for symbol, profile in symbol_profiles.items():
        if profile.wf_stable and profile.total_trades >= 20:
            stable_symbols.append(symbol)

            config['symbol_recommendations'][symbol] = {
                'best_strategy': profile.best_strategy,
                'best_strategy_wr': profile.best_strategy_win_rate,
                'optimal_min_score': profile.optimal_min_score,
                'total_trades': profile.total_trades,
                'train_wr': profile.wf_train_wr,
                'test_wr': profile.wf_test_wr,
                'stable': profile.wf_stable
            }

    config['summary'] = {
        'total_symbols_analyzed': len(symbol_profiles),
        'stable_symbols': len(stable_symbols),
        'stable_symbol_list': stable_symbols[:50]  # Top 50
    }

    # Regime adjustments (aggregate across symbols)
    regime_stats = defaultdict(lambda: {'trades': 0, 'wins': 0})
    for profile in symbol_profiles.values():
        for regime, data in profile.regime_performance.items():
            regime_stats[regime]['trades'] += data['trades']
            regime_stats[regime]['wins'] += data['wins']

    base_wr = sum(p.total_wins for p in symbol_profiles.values()) / sum(p.total_trades for p in symbol_profiles.values()) * 100 if sum(p.total_trades for p in symbol_profiles.values()) > 0 else 50

    for regime, data in regime_stats.items():
        if data['trades'] > 0:
            regime_wr = data['wins'] / data['trades'] * 100
            diff = regime_wr - base_wr

            if diff > 5:
                adj = 1.0
            elif diff > 2:
                adj = 0.5
            elif diff < -5:
                adj = -1.0
            elif diff < -2:
                adj = -0.5
            else:
                adj = 0.0

            config['regime_adjustments'][regime] = {
                'adjustment': adj,
                'win_rate': regime_wr,
                'trades': data['trades']
            }

    return config


def save_results(
    wf_aggregation: Dict[str, Any],
    symbol_profiles: Dict[str, SymbolProfile],
    final_config: Dict[str, Any],
    progress: TrainingProgress
):
    """Save all training results"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Walk-forward results
    with open(OUTPUT_DIR / f'walkforward_results_{timestamp}.json', 'w') as f:
        json.dump(wf_aggregation, f, indent=2, default=str)

    # Symbol profiles
    symbol_export = {
        symbol: {
            'total_trades': p.total_trades,
            'total_wins': p.total_wins,
            'win_rate': p.total_wins / p.total_trades * 100 if p.total_trades > 0 else 0,
            'best_strategy': p.best_strategy,
            'best_strategy_wr': p.best_strategy_win_rate,
            'optimal_min_score': p.optimal_min_score,
            'wf_stable': p.wf_stable,
            'wf_degradation': p.wf_degradation,
            'strategy_performance': p.strategy_performance
        }
        for symbol, p in symbol_profiles.items()
        if p.total_trades >= 10
    }

    with open(OUTPUT_DIR / f'symbol_profiles_{timestamp}.json', 'w') as f:
        json.dump(symbol_export, f, indent=2)

    # Final config
    with open(OUTPUT_DIR / f'walkforward_config_{timestamp}.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    with open(OUTPUT_DIR / 'WALKFORWARD_FINAL_CONFIG.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    logger.info(f"Results saved to {OUTPUT_DIR}")


def main():
    """Main training pipeline"""

    progress = TrainingProgress()

    logger.info("=" * 70)
    logger.info("  WALK-FORWARD + PER-SYMBOL TRAINING")
    logger.info(f"  Started: {progress.start_time}")
    logger.info("=" * 70)

    try:
        # Load data
        progress.phase = "Loading Data"
        progress.save()

        tracker = TradeTracker()
        stats = tracker.get_storage_stats()

        logger.info(f"\n  Symbols: {stats['symbols_with_price_data']}")
        logger.info(f"  Price Bars: {stats['total_price_bars']:,}")

        symbol_info = tracker.list_symbols_with_price_data()
        symbols = [s['symbol'] for s in symbol_info]
        progress.total_symbols = len(symbols)

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

        logger.info(f"  Loaded: {len(historical_data)} symbols\n")

        # Phase 1: Walk-Forward Validation
        progress.phase = "Walk-Forward Validation"
        progress.total_epochs = len(STRATEGIES) * 15  # Estimated
        progress.save()

        logger.info("=" * 70)
        logger.info("  PHASE 1: WALK-FORWARD VALIDATION")
        logger.info("=" * 70)

        wf_results = {}

        for strategy in STRATEGIES:
            logger.info(f"\n  Strategy: {strategy.upper()}")

            epochs = run_walk_forward(
                historical_data, vix_data, strategy, progress,
                train_months=12,
                test_months=3,
                step_months=3
            )

            wf_results[strategy] = epochs

            if epochs:
                avg_train = statistics.mean(e.train_win_rate() for e in epochs)
                avg_test = statistics.mean(e.test_win_rate() for e in epochs)
                logger.info(f"  -> Avg Train: {avg_train:.1f}%, Avg Test: {avg_test:.1f}%, "
                           f"Degradation: {avg_train - avg_test:+.1f}%")

        wf_aggregation = aggregate_walk_forward_results(wf_results)

        # Phase 2: Per-Symbol Analysis
        progress.phase = "Per-Symbol Analysis"
        progress.symbols_processed = 0
        progress.save()

        logger.info("\n" + "=" * 70)
        logger.info("  PHASE 2: PER-SYMBOL ANALYSIS")
        logger.info("=" * 70)

        symbol_profiles = {}

        for i, symbol in enumerate(symbols):
            progress.current_task = symbol
            progress.symbols_processed = i + 1

            profile = analyze_symbol_detailed(
                symbol, historical_data.get(symbol, []), vix_data, progress
            )

            if profile.total_trades >= 10:
                symbol_profiles[symbol] = profile

            if (i + 1) % 50 == 0:
                logger.info(f"  Processed {i+1}/{len(symbols)} symbols")
                progress.save()

        logger.info(f"\n  Analyzed {len(symbol_profiles)} symbols with sufficient data")

        # Stable symbols
        stable_count = sum(1 for p in symbol_profiles.values() if p.wf_stable)
        logger.info(f"  Stable symbols (degradation < 10%): {stable_count}")

        # Phase 3: Create Final Config
        progress.phase = "Creating Final Config"
        progress.save()

        final_config = create_final_config(wf_aggregation, symbol_profiles)

        # Save results
        save_results(wf_aggregation, symbol_profiles, final_config, progress)

        # Summary
        progress.phase = "Complete"
        progress.save()

        logger.info("\n" + "=" * 70)
        logger.info("  TRAINING COMPLETE")
        logger.info("=" * 70)
        logger.info(f"  Duration: {progress.elapsed_hours():.2f} hours")
        logger.info(f"  Trades Analyzed: {progress.trades_analyzed:,}")

        logger.info("\n  WALK-FORWARD RESULTS:")
        for strategy, data in wf_aggregation.items():
            logger.info(f"    {strategy}:")
            logger.info(f"      Train WR: {data['train_win_rate']:.1f}%")
            logger.info(f"      Test WR:  {data['test_win_rate']:.1f}%")
            logger.info(f"      Stable:   {'Yes' if data['stable'] else 'No'}")
            logger.info(f"      Min Score: {data['recommended_min_score']}")

        logger.info(f"\n  Output: {OUTPUT_DIR}")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        progress.phase = f"Error: {str(e)}"
        progress.save()
        raise


if __name__ == '__main__':
    main()
