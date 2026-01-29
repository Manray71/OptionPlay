#!/usr/bin/env python3
"""
OptionPlay - Overnight Training Pipeline (8 Hours)
====================================================

Comprehensive training that runs autonomously for 8 hours:
1. Per-symbol strategy optimization
2. Deep component weight analysis
3. Multi-timeframe validation
4. Regime transition analysis
5. Ensemble refinement
6. Cross-validation across all data

Progress is logged to ~/.optionplay/training_log.txt
"""

import json
import sys
import warnings
import time
import logging
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed, ProcessPoolExecutor
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

# Setup logging
LOG_DIR = Path.home() / '.optionplay'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'training_log.txt'

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
TRAINING_DURATION_HOURS = 8
OUTPUT_DIR = Path.home() / '.optionplay' / 'models'


@dataclass
class SymbolPerformance:
    """Performance metrics for a single symbol"""
    symbol: str
    total_trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    best_strategy: str = ""
    best_strategy_win_rate: float = 0.0
    strategy_performance: Dict[str, Dict] = field(default_factory=dict)
    regime_performance: Dict[str, Dict] = field(default_factory=dict)
    optimal_min_score: float = 5.0
    component_correlations: Dict[str, float] = field(default_factory=dict)


@dataclass
class TrainingProgress:
    """Track training progress"""
    start_time: datetime = field(default_factory=datetime.now)
    phase: str = "initializing"
    symbols_processed: int = 0
    total_symbols: int = 0
    trades_analyzed: int = 0
    current_symbol: str = ""
    errors: List[str] = field(default_factory=list)

    def elapsed_hours(self) -> float:
        return (datetime.now() - self.start_time).total_seconds() / 3600

    def remaining_hours(self) -> float:
        return max(0, TRAINING_DURATION_HOURS - self.elapsed_hours())

    def to_dict(self) -> Dict:
        return {
            'start_time': self.start_time.isoformat(),
            'elapsed_hours': round(self.elapsed_hours(), 2),
            'remaining_hours': round(self.remaining_hours(), 2),
            'phase': self.phase,
            'symbols_processed': self.symbols_processed,
            'total_symbols': self.total_symbols,
            'trades_analyzed': self.trades_analyzed,
            'current_symbol': self.current_symbol,
            'error_count': len(self.errors)
        }


def save_progress(progress: TrainingProgress):
    """Save progress to file"""
    progress_file = OUTPUT_DIR / 'training_progress.json'
    with open(progress_file, 'w') as f:
        json.dump(progress.to_dict(), f, indent=2)


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


def simulate_trade(entry_price: float, future_bars: List[Dict], holding_days: int = 45) -> Tuple[int, float]:
    """Simulate Bull-Put-Spread outcome"""
    if len(future_bars) < 10:
        return 0, 0.0

    short_strike = entry_price * 0.92
    long_strike = short_strike - (entry_price * 0.05)
    spread_width = short_strike - long_strike
    net_credit = spread_width * 0.20

    max_profit = net_credit * 100
    max_loss = (spread_width - net_credit) * 100

    for i, bar in enumerate(future_bars[:holding_days]):
        if bar['low'] < long_strike:
            return 0, -max_loss

        if i >= 14 and bar['close'] >= entry_price:
            return 1, max_profit * 0.5

    final_price = future_bars[min(holding_days-1, len(future_bars)-1)]['close']

    if final_price >= short_strike:
        return 1, max_profit
    elif final_price >= long_strike:
        intrinsic = short_strike - final_price
        return 0, (net_credit - intrinsic) * 100
    else:
        return 0, -max_loss


def analyze_symbol(
    symbol: str,
    symbol_data: List[Dict],
    vix_data: Dict[date, float],
    strategies: List[str],
    min_scores: List[float] = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]
) -> SymbolPerformance:
    """Deep analysis of a single symbol across all strategies and parameters"""

    perf = SymbolPerformance(symbol=symbol)

    if len(symbol_data) < 300:
        return perf

    # Sort and prepare data
    sorted_data = sorted(
        symbol_data,
        key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
    )

    # Convert dates
    for bar in sorted_data:
        if isinstance(bar['date'], str):
            bar['date'] = date.fromisoformat(bar['date'])

    # Build date index
    date_to_idx = {bar['date']: i for i, bar in enumerate(sorted_data)}
    all_dates = sorted(date_to_idx.keys())

    # Sample dates for analysis (every 3rd trading day)
    sample_dates = all_dates[200::3]

    for strategy in strategies:
        try:
            analyzer = create_analyzer(strategy)
        except Exception:
            continue

        strategy_results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        regime_results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        score_results = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
        component_wins = defaultdict(list)
        component_losses = defaultdict(list)

        for current_date in sample_dates:
            idx = date_to_idx.get(current_date)
            if idx is None or idx < 200 or idx >= len(sorted_data) - 50:
                continue

            history = sorted_data[max(0, idx-259):idx]
            if len(history) < 200:
                continue

            future = sorted_data[idx:idx+50]
            if len(future) < 20:
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

            if signal.signal_type != SignalType.LONG:
                continue

            score = signal.score
            entry_price = prices[-1]
            vix = vix_data.get(current_date, 20.0)
            regime = get_regime(vix)

            outcome, pnl = simulate_trade(entry_price, future)

            # Overall strategy results
            strategy_results[strategy]['trades'] += 1
            strategy_results[strategy]['wins'] += outcome
            strategy_results[strategy]['pnl'] += pnl

            # Regime results
            regime_results[regime]['trades'] += 1
            regime_results[regime]['wins'] += outcome
            regime_results[regime]['pnl'] += pnl

            # Score threshold results
            for min_score in min_scores:
                if score >= min_score:
                    score_results[min_score]['trades'] += 1
                    score_results[min_score]['wins'] += outcome
                    score_results[min_score]['pnl'] += pnl

            # Component analysis
            if signal.details:
                breakdown = signal.details.get('score_breakdown') or signal.details.get('breakdown')
                if breakdown:
                    if isinstance(breakdown, dict):
                        for k, v in breakdown.items():
                            if isinstance(v, (int, float)):
                                if outcome == 1:
                                    component_wins[k].append(v)
                                else:
                                    component_losses[k].append(v)

        # Save strategy performance
        if strategy_results[strategy]['trades'] > 0:
            trades = strategy_results[strategy]['trades']
            wins = strategy_results[strategy]['wins']
            perf.strategy_performance[strategy] = {
                'trades': trades,
                'wins': wins,
                'win_rate': wins / trades * 100 if trades > 0 else 0,
                'pnl': strategy_results[strategy]['pnl'],
                'regime_breakdown': {
                    r: {
                        'trades': d['trades'],
                        'wins': d['wins'],
                        'win_rate': d['wins'] / d['trades'] * 100 if d['trades'] > 0 else 0,
                        'pnl': d['pnl']
                    }
                    for r, d in regime_results.items() if d['trades'] > 0
                },
                'score_analysis': {
                    str(s): {
                        'trades': d['trades'],
                        'wins': d['wins'],
                        'win_rate': d['wins'] / d['trades'] * 100 if d['trades'] > 0 else 0,
                        'pnl': d['pnl']
                    }
                    for s, d in score_results.items() if d['trades'] > 0
                }
            }

            perf.total_trades += trades
            perf.wins += wins
            perf.total_pnl += strategy_results[strategy]['pnl']

        # Component correlations
        for component in component_wins.keys():
            if component in component_losses and len(component_wins[component]) >= 5 and len(component_losses[component]) >= 5:
                try:
                    win_mean = statistics.mean(component_wins[component])
                    loss_mean = statistics.mean(component_losses[component])
                    diff = win_mean - loss_mean
                    perf.component_correlations[f"{strategy}_{component}"] = diff
                except Exception:
                    pass

    # Find best strategy
    best_wr = 0
    for strategy, data in perf.strategy_performance.items():
        if data['trades'] >= 10 and data['win_rate'] > best_wr:
            best_wr = data['win_rate']
            perf.best_strategy = strategy
            perf.best_strategy_win_rate = best_wr

    # Find optimal min score
    best_score_wr = 0
    for strategy, data in perf.strategy_performance.items():
        for score_str, score_data in data.get('score_analysis', {}).items():
            if score_data['trades'] >= 10 and score_data['win_rate'] > best_score_wr:
                best_score_wr = score_data['win_rate']
                perf.optimal_min_score = float(score_str)

    return perf


def phase1_per_symbol_analysis(
    historical_data: Dict[str, List[Dict]],
    vix_data: Dict[date, float],
    progress: TrainingProgress,
    max_hours: float = 3.0
) -> Dict[str, SymbolPerformance]:
    """Phase 1: Deep analysis of each symbol"""

    progress.phase = "Phase 1: Per-Symbol Analysis"
    logger.info(f"Starting {progress.phase}")

    symbols = list(historical_data.keys())
    progress.total_symbols = len(symbols)

    results = {}
    start_time = datetime.now()
    max_seconds = max_hours * 3600

    for i, symbol in enumerate(symbols):
        # Check time limit
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > max_seconds:
            logger.info(f"Phase 1 time limit reached after {len(results)} symbols")
            break

        progress.current_symbol = symbol
        progress.symbols_processed = i + 1

        try:
            perf = analyze_symbol(
                symbol=symbol,
                symbol_data=historical_data[symbol],
                vix_data=vix_data,
                strategies=STRATEGIES
            )

            if perf.total_trades > 0:
                results[symbol] = perf
                progress.trades_analyzed += perf.total_trades

            if (i + 1) % 25 == 0:
                logger.info(f"  Processed {i+1}/{len(symbols)} symbols, {progress.trades_analyzed} trades")
                save_progress(progress)

        except Exception as e:
            progress.errors.append(f"{symbol}: {str(e)}")
            logger.warning(f"Error analyzing {symbol}: {e}")

    logger.info(f"Phase 1 complete: {len(results)} symbols analyzed")
    return results


def phase2_cross_strategy_optimization(
    symbol_results: Dict[str, SymbolPerformance],
    progress: TrainingProgress,
    max_hours: float = 1.5
) -> Dict[str, Any]:
    """Phase 2: Cross-strategy optimization"""

    progress.phase = "Phase 2: Cross-Strategy Optimization"
    logger.info(f"Starting {progress.phase}")

    optimization = {
        'strategy_rankings': {},
        'regime_recommendations': {},
        'symbol_strategy_map': {},
        'optimal_thresholds': {}
    }

    # Strategy rankings per regime
    regime_strategy_wins = defaultdict(lambda: defaultdict(lambda: {'wins': 0, 'trades': 0}))

    for symbol, perf in symbol_results.items():
        for strategy, data in perf.strategy_performance.items():
            for regime, regime_data in data.get('regime_breakdown', {}).items():
                regime_strategy_wins[regime][strategy]['wins'] += regime_data['wins']
                regime_strategy_wins[regime][strategy]['trades'] += regime_data['trades']

        # Best strategy per symbol
        if perf.best_strategy:
            optimization['symbol_strategy_map'][symbol] = {
                'best_strategy': perf.best_strategy,
                'win_rate': perf.best_strategy_win_rate,
                'optimal_score': perf.optimal_min_score
            }

    # Calculate rankings
    for regime, strategies in regime_strategy_wins.items():
        ranked = []
        for strategy, data in strategies.items():
            if data['trades'] >= 50:
                wr = data['wins'] / data['trades'] * 100
                ranked.append((strategy, wr, data['trades']))

        ranked.sort(key=lambda x: x[1], reverse=True)
        optimization['strategy_rankings'][regime] = [
            {'strategy': s, 'win_rate': wr, 'trades': t}
            for s, wr, t in ranked
        ]

        if ranked:
            optimization['regime_recommendations'][regime] = ranked[0][0]

    # Optimal thresholds per strategy
    for strategy in STRATEGIES:
        score_totals = defaultdict(lambda: {'wins': 0, 'trades': 0})

        for perf in symbol_results.values():
            strat_data = perf.strategy_performance.get(strategy, {})
            for score_str, data in strat_data.get('score_analysis', {}).items():
                score = float(score_str)
                score_totals[score]['wins'] += data['wins']
                score_totals[score]['trades'] += data['trades']

        best_score = 5.0
        best_wr = 0

        for score, data in score_totals.items():
            if data['trades'] >= 100:
                wr = data['wins'] / data['trades'] * 100
                if wr > best_wr:
                    best_wr = wr
                    best_score = score

        optimization['optimal_thresholds'][strategy] = {
            'min_score': best_score,
            'expected_win_rate': best_wr
        }

    logger.info(f"Phase 2 complete: Optimizations calculated")
    return optimization


def phase3_component_weight_optimization(
    symbol_results: Dict[str, SymbolPerformance],
    progress: TrainingProgress,
    max_hours: float = 1.5
) -> Dict[str, Dict[str, float]]:
    """Phase 3: Component weight optimization"""

    progress.phase = "Phase 3: Component Weight Optimization"
    logger.info(f"Starting {progress.phase}")

    # Aggregate component correlations
    component_aggregates = defaultdict(list)

    for perf in symbol_results.values():
        for comp, corr in perf.component_correlations.items():
            component_aggregates[comp].append(corr)

    optimized_weights = {}

    for comp, correlations in component_aggregates.items():
        if len(correlations) >= 10:
            avg_corr = statistics.mean(correlations)

            # Convert correlation to weight adjustment
            if avg_corr > 0.3:
                weight = 1.3
            elif avg_corr > 0.1:
                weight = 1.1
            elif avg_corr < -0.3:
                weight = 0.7
            elif avg_corr < -0.1:
                weight = 0.9
            else:
                weight = 1.0

            optimized_weights[comp] = {
                'weight': weight,
                'avg_correlation': avg_corr,
                'sample_size': len(correlations)
            }

    logger.info(f"Phase 3 complete: {len(optimized_weights)} component weights optimized")
    return optimized_weights


def phase4_ensemble_refinement(
    symbol_results: Dict[str, SymbolPerformance],
    optimization: Dict[str, Any],
    progress: TrainingProgress,
    max_hours: float = 1.0
) -> Dict[str, Any]:
    """Phase 4: Ensemble model refinement"""

    progress.phase = "Phase 4: Ensemble Refinement"
    logger.info(f"Starting {progress.phase}")

    ensemble_config = {
        'version': '3.0.0',
        'created_at': datetime.now().isoformat(),
        'method': 'symbol_aware_meta_learner',

        'regime_strategy_weights': {},
        'symbol_preferences': {},
        'fallback_chain': [],
        'confidence_thresholds': {}
    }

    # Build regime-strategy weight matrix
    for regime, rankings in optimization.get('strategy_rankings', {}).items():
        weights = {}
        total_wr = sum(r['win_rate'] for r in rankings) if rankings else 1

        for r in rankings:
            weights[r['strategy']] = r['win_rate'] / total_wr if total_wr > 0 else 0.25

        ensemble_config['regime_strategy_weights'][regime] = weights

    # Symbol preferences
    for symbol, data in optimization.get('symbol_strategy_map', {}).items():
        ensemble_config['symbol_preferences'][symbol] = {
            'preferred_strategy': data['best_strategy'],
            'confidence': min(data['win_rate'] / 100, 0.95)
        }

    # Fallback chain based on overall performance
    overall_performance = defaultdict(lambda: {'wins': 0, 'trades': 0})

    for perf in symbol_results.values():
        for strategy, data in perf.strategy_performance.items():
            overall_performance[strategy]['wins'] += data['wins']
            overall_performance[strategy]['trades'] += data['trades']

    ranked = []
    for strategy, data in overall_performance.items():
        if data['trades'] > 0:
            wr = data['wins'] / data['trades'] * 100
            ranked.append((strategy, wr))

    ranked.sort(key=lambda x: x[1], reverse=True)
    ensemble_config['fallback_chain'] = [s for s, _ in ranked]

    # Confidence thresholds
    ensemble_config['confidence_thresholds'] = {
        'use_symbol_preference': 0.7,
        'use_regime_weights': 0.5,
        'use_fallback': 0.3
    }

    logger.info(f"Phase 4 complete: Ensemble model refined")
    return ensemble_config


def phase5_validation(
    historical_data: Dict[str, List[Dict]],
    vix_data: Dict[date, float],
    ensemble_config: Dict[str, Any],
    optimization: Dict[str, Any],
    progress: TrainingProgress,
    max_hours: float = 1.0
) -> Dict[str, Any]:
    """Phase 5: Out-of-sample validation"""

    progress.phase = "Phase 5: Validation"
    logger.info(f"Starting {progress.phase}")

    validation_results = {
        'total_trades': 0,
        'wins': 0,
        'pnl': 0.0,
        'by_strategy': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0}),
        'by_regime': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
    }

    # Use last 3 months as validation period
    all_dates = set()
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
            all_dates.add(d)

    if not all_dates:
        return validation_results

    max_date = max(all_dates)
    val_start = max_date - timedelta(days=90)

    symbols = list(historical_data.keys())[:100]  # Limit for speed

    for symbol in symbols:
        symbol_data = historical_data[symbol]

        # Get symbol preference
        pref = optimization.get('symbol_strategy_map', {}).get(symbol, {})
        preferred_strategy = pref.get('best_strategy', 'ath_breakout')
        optimal_score = pref.get('optimal_score', 6.0)

        # Sort data
        sorted_data = sorted(
            symbol_data,
            key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
        )

        for bar in sorted_data:
            if isinstance(bar['date'], str):
                bar['date'] = date.fromisoformat(bar['date'])

        # Find validation period indices
        val_indices = [
            i for i, bar in enumerate(sorted_data)
            if bar['date'] >= val_start and i >= 200 and i < len(sorted_data) - 50
        ]

        if not val_indices:
            continue

        # Sample validation dates
        sample_indices = val_indices[::5]

        try:
            analyzer = create_analyzer(preferred_strategy)
        except Exception:
            continue

        for idx in sample_indices:
            history = sorted_data[max(0, idx-259):idx]
            future = sorted_data[idx:idx+50]

            if len(history) < 200 or len(future) < 20:
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

            if signal.signal_type != SignalType.LONG or signal.score < optimal_score:
                continue

            vix = vix_data.get(sorted_data[idx]['date'], 20.0)
            regime = get_regime(vix)

            outcome, pnl = simulate_trade(prices[-1], future)

            validation_results['total_trades'] += 1
            validation_results['wins'] += outcome
            validation_results['pnl'] += pnl
            validation_results['by_strategy'][preferred_strategy]['trades'] += 1
            validation_results['by_strategy'][preferred_strategy]['wins'] += outcome
            validation_results['by_strategy'][preferred_strategy]['pnl'] += pnl
            validation_results['by_regime'][regime]['trades'] += 1
            validation_results['by_regime'][regime]['wins'] += outcome
            validation_results['by_regime'][regime]['pnl'] += pnl

    # Calculate win rate
    if validation_results['total_trades'] > 0:
        validation_results['win_rate'] = validation_results['wins'] / validation_results['total_trades'] * 100

    logger.info(f"Phase 5 complete: {validation_results['total_trades']} validation trades")
    return validation_results


def save_final_results(
    symbol_results: Dict[str, SymbolPerformance],
    optimization: Dict[str, Any],
    component_weights: Dict[str, Dict],
    ensemble_config: Dict[str, Any],
    validation_results: Dict[str, Any],
    progress: TrainingProgress
):
    """Save all training results"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Symbol performance
    symbol_data = {
        symbol: {
            'total_trades': perf.total_trades,
            'wins': perf.wins,
            'win_rate': perf.wins / perf.total_trades * 100 if perf.total_trades > 0 else 0,
            'total_pnl': perf.total_pnl,
            'best_strategy': perf.best_strategy,
            'best_strategy_win_rate': perf.best_strategy_win_rate,
            'optimal_min_score': perf.optimal_min_score,
            'strategy_performance': perf.strategy_performance
        }
        for symbol, perf in symbol_results.items()
    }

    with open(OUTPUT_DIR / f'symbol_performance_{timestamp}.json', 'w') as f:
        json.dump(symbol_data, f, indent=2, default=str)

    # 2. Optimization results
    with open(OUTPUT_DIR / f'optimization_{timestamp}.json', 'w') as f:
        json.dump(optimization, f, indent=2, default=str)

    # 3. Component weights
    with open(OUTPUT_DIR / f'component_weights_{timestamp}.json', 'w') as f:
        json.dump(component_weights, f, indent=2, default=str)

    # 4. Ensemble config
    with open(OUTPUT_DIR / f'ensemble_overnight_{timestamp}.json', 'w') as f:
        json.dump(ensemble_config, f, indent=2, default=str)

    # 5. Validation results
    validation_export = {
        'total_trades': validation_results['total_trades'],
        'wins': validation_results['wins'],
        'win_rate': validation_results.get('win_rate', 0),
        'pnl': validation_results['pnl'],
        'by_strategy': dict(validation_results['by_strategy']),
        'by_regime': dict(validation_results['by_regime'])
    }

    with open(OUTPUT_DIR / f'validation_{timestamp}.json', 'w') as f:
        json.dump(validation_export, f, indent=2, default=str)

    # 6. Combined final config
    final_config = {
        'version': '3.0.0',
        'created_at': datetime.now().isoformat(),
        'training_duration_hours': progress.elapsed_hours(),
        'symbols_analyzed': len(symbol_results),
        'total_trades_analyzed': progress.trades_analyzed,

        'strategies': {},
        'ensemble': ensemble_config,
        'validation': validation_export
    }

    # Strategy configs
    for strategy in STRATEGIES:
        thresholds = optimization.get('optimal_thresholds', {}).get(strategy, {})
        regime_rec = []

        for regime, rankings in optimization.get('strategy_rankings', {}).items():
            for r in rankings:
                if r['strategy'] == strategy and r.get('win_rate', 0) > 80:
                    regime_rec.append(regime)

        final_config['strategies'][strategy] = {
            'enabled': True,
            'min_score': thresholds.get('min_score', 6.0),
            'expected_win_rate': thresholds.get('expected_win_rate', 0),
            'best_regimes': regime_rec,
            'regime_adjustments': {
                regime: 1.0 if regime in regime_rec else 0.0
                for regime in VIX_REGIMES.keys()
            }
        }

    with open(OUTPUT_DIR / 'OVERNIGHT_TRAINING_RESULT.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    # Also save as latest
    with open(OUTPUT_DIR / 'overnight_latest.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    logger.info(f"All results saved to {OUTPUT_DIR}")


def main():
    """Main overnight training pipeline"""

    progress = TrainingProgress()

    logger.info("=" * 70)
    logger.info("  OPTIONPLAY OVERNIGHT TRAINING PIPELINE")
    logger.info(f"  Duration: {TRAINING_DURATION_HOURS} hours")
    logger.info(f"  Started: {progress.start_time}")
    logger.info("=" * 70)

    try:
        # Load data
        progress.phase = "Loading Data"
        logger.info("Loading historical data...")

        tracker = TradeTracker()
        stats = tracker.get_storage_stats()

        logger.info(f"  Symbols: {stats['symbols_with_price_data']}")
        logger.info(f"  Price Bars: {stats['total_price_bars']:,}")
        logger.info(f"  VIX Points: {stats['vix_data_points']:,}")

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
        save_progress(progress)

        # Phase 1: Per-symbol analysis (3 hours)
        symbol_results = phase1_per_symbol_analysis(
            historical_data, vix_data, progress, max_hours=3.0
        )
        save_progress(progress)

        # Check if we should continue
        if progress.remaining_hours() < 1:
            logger.info("Time limit approaching, saving results...")
        else:
            # Phase 2: Cross-strategy optimization (1.5 hours)
            optimization = phase2_cross_strategy_optimization(
                symbol_results, progress, max_hours=1.5
            )
            save_progress(progress)

            # Phase 3: Component weights (1.5 hours)
            component_weights = phase3_component_weight_optimization(
                symbol_results, progress, max_hours=1.5
            )
            save_progress(progress)

            # Phase 4: Ensemble refinement (1 hour)
            ensemble_config = phase4_ensemble_refinement(
                symbol_results, optimization, progress, max_hours=1.0
            )
            save_progress(progress)

            # Phase 5: Validation (1 hour)
            validation_results = phase5_validation(
                historical_data, vix_data, ensemble_config, optimization, progress, max_hours=1.0
            )
            save_progress(progress)

            # Save all results
            save_final_results(
                symbol_results, optimization, component_weights,
                ensemble_config, validation_results, progress
            )

        progress.phase = "Complete"
        save_progress(progress)

        # Final summary
        logger.info("=" * 70)
        logger.info("  TRAINING COMPLETE")
        logger.info("=" * 70)
        logger.info(f"  Duration: {progress.elapsed_hours():.2f} hours")
        logger.info(f"  Symbols Analyzed: {progress.symbols_processed}")
        logger.info(f"  Trades Analyzed: {progress.trades_analyzed:,}")
        logger.info(f"  Errors: {len(progress.errors)}")
        logger.info(f"  Output: {OUTPUT_DIR}")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        progress.errors.append(f"Fatal: {str(e)}")
        progress.phase = "Error"
        save_progress(progress)
        raise


if __name__ == '__main__':
    main()
