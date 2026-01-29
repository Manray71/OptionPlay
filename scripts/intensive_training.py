#!/usr/bin/env python3
"""
OptionPlay - Intensive Full-Day Training (8+ Hours)
====================================================

Comprehensive training analyzing EVERY trading day (no sampling):
- Full backtest on every single trading day
- Per-symbol strategy optimization with all data points
- Deep component correlation analysis
- Multi-timeframe regime analysis
- Exhaustive parameter grid search

Progress logged to ~/.optionplay/intensive_training.log
"""

import json
import sys
import warnings
import time
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
LOG_FILE = LOG_DIR / 'intensive_training.log'
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
MIN_SCORES = [4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]
HOLDING_PERIODS = [21, 30, 45, 60]


@dataclass
class DetailedTradeResult:
    """Detailed trade result for analysis"""
    symbol: str
    strategy: str
    entry_date: date
    entry_price: float
    score: float
    vix: float
    regime: str
    holding_days: int
    outcome: int
    pnl: float
    exit_reason: str
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class IntensiveProgress:
    """Track intensive training progress"""
    start_time: datetime = field(default_factory=datetime.now)
    phase: str = "initializing"
    current_strategy: str = ""
    current_symbol: str = ""
    symbols_processed: int = 0
    total_symbols: int = 0
    trades_analyzed: int = 0
    current_phase_progress: float = 0.0

    def elapsed_hours(self) -> float:
        return (datetime.now() - self.start_time).total_seconds() / 3600

    def save(self):
        progress_file = OUTPUT_DIR / 'intensive_progress.json'
        with open(progress_file, 'w') as f:
            json.dump({
                'start_time': self.start_time.isoformat(),
                'elapsed_hours': round(self.elapsed_hours(), 2),
                'phase': self.phase,
                'current_strategy': self.current_strategy,
                'current_symbol': self.current_symbol,
                'symbols_processed': self.symbols_processed,
                'total_symbols': self.total_symbols,
                'trades_analyzed': self.trades_analyzed,
                'phase_progress': f"{self.current_phase_progress:.1f}%"
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


def simulate_spread_trade(
    entry_price: float,
    future_bars: List[Dict],
    holding_days: int = 45,
    short_strike_pct: float = 0.92,
    spread_width_pct: float = 0.05
) -> Tuple[int, float, str]:
    """
    Detailed Bull-Put-Spread simulation
    Returns: (outcome, pnl, exit_reason)
    """
    if len(future_bars) < 10:
        return 0, 0.0, "insufficient_data"

    short_strike = entry_price * short_strike_pct
    long_strike = short_strike - (entry_price * spread_width_pct)
    spread_width = short_strike - long_strike
    net_credit = spread_width * 0.20

    max_profit = net_credit * 100
    max_loss = (spread_width - net_credit) * 100

    # Track daily
    for day, bar in enumerate(future_bars[:holding_days]):
        current_price = bar['close']
        current_low = bar['low']

        # Max loss hit
        if current_low < long_strike:
            return 0, -max_loss, "max_loss"

        # 50% profit target after 14 days
        if day >= 14:
            if current_price >= entry_price * 1.01:
                return 1, max_profit * 0.5, "profit_target_50"

        # 75% profit target after 21 days
        if day >= 21:
            if current_price >= short_strike * 1.02:
                return 1, max_profit * 0.75, "profit_target_75"

    # At expiration
    final_price = future_bars[min(holding_days-1, len(future_bars)-1)]['close']

    if final_price >= short_strike:
        return 1, max_profit, "expiration_profit"
    elif final_price >= long_strike:
        intrinsic = short_strike - final_price
        pnl = (net_credit - intrinsic) * 100
        return (1 if pnl > 0 else 0), pnl, "expiration_partial"
    else:
        return 0, -max_loss, "expiration_loss"


def analyze_symbol_intensive(
    symbol: str,
    symbol_data: List[Dict],
    vix_data: Dict[date, float],
    strategy: str,
    analyzer,
    progress: IntensiveProgress
) -> List[DetailedTradeResult]:
    """Analyze every single trading day for a symbol"""

    results = []

    if len(symbol_data) < 300:
        return results

    # Sort and prepare
    sorted_data = sorted(
        symbol_data,
        key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
    )

    for bar in sorted_data:
        if isinstance(bar['date'], str):
            bar['date'] = date.fromisoformat(bar['date'])

    # Analyze EVERY trading day (no sampling)
    for idx in range(250, len(sorted_data) - 60):
        history = sorted_data[max(0, idx-259):idx]
        future = sorted_data[idx:idx+60]

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

        if signal.signal_type != SignalType.LONG:
            continue

        # Test multiple holding periods
        for holding_days in HOLDING_PERIODS:
            if len(future) < holding_days:
                continue

            entry_price = prices[-1]
            vix = vix_data.get(current_date, 20.0)
            regime = get_regime(vix)

            outcome, pnl, exit_reason = simulate_spread_trade(
                entry_price, future, holding_days
            )

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

            results.append(DetailedTradeResult(
                symbol=symbol,
                strategy=strategy,
                entry_date=current_date,
                entry_price=entry_price,
                score=signal.score,
                vix=vix,
                regime=regime,
                holding_days=holding_days,
                outcome=outcome,
                pnl=pnl,
                exit_reason=exit_reason,
                score_breakdown=score_breakdown
            ))

            progress.trades_analyzed += 1

    return results


def aggregate_results(all_results: List[DetailedTradeResult]) -> Dict[str, Any]:
    """Aggregate all results into comprehensive statistics"""

    aggregation = {
        'total_trades': len(all_results),
        'total_wins': sum(1 for r in all_results if r.outcome == 1),
        'total_pnl': sum(r.pnl for r in all_results),

        'by_strategy': defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'pnl': 0.0,
            'by_regime': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0}),
            'by_score': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0}),
            'by_holding': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0}),
            'by_exit_reason': defaultdict(int)
        }),

        'by_symbol': defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'pnl': 0.0,
            'best_strategy': '', 'best_strategy_wr': 0.0,
            'strategies': defaultdict(lambda: {'trades': 0, 'wins': 0})
        }),

        'by_regime': defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0}),

        'component_analysis': defaultdict(lambda: {
            'win_values': [], 'loss_values': []
        })
    }

    for r in all_results:
        # Strategy level
        strat = aggregation['by_strategy'][r.strategy]
        strat['trades'] += 1
        strat['wins'] += r.outcome
        strat['pnl'] += r.pnl
        strat['by_regime'][r.regime]['trades'] += 1
        strat['by_regime'][r.regime]['wins'] += r.outcome
        strat['by_regime'][r.regime]['pnl'] += r.pnl

        # Score bucket
        score_bucket = int(r.score)
        strat['by_score'][score_bucket]['trades'] += 1
        strat['by_score'][score_bucket]['wins'] += r.outcome
        strat['by_score'][score_bucket]['pnl'] += r.pnl

        # Holding period
        strat['by_holding'][r.holding_days]['trades'] += 1
        strat['by_holding'][r.holding_days]['wins'] += r.outcome
        strat['by_holding'][r.holding_days]['pnl'] += r.pnl

        # Exit reason
        strat['by_exit_reason'][r.exit_reason] += 1

        # Symbol level
        sym = aggregation['by_symbol'][r.symbol]
        sym['trades'] += 1
        sym['wins'] += r.outcome
        sym['pnl'] += r.pnl
        sym['strategies'][r.strategy]['trades'] += 1
        sym['strategies'][r.strategy]['wins'] += r.outcome

        # Regime level
        aggregation['by_regime'][r.regime]['trades'] += 1
        aggregation['by_regime'][r.regime]['wins'] += r.outcome
        aggregation['by_regime'][r.regime]['pnl'] += r.pnl

        # Component analysis
        for comp, value in r.score_breakdown.items():
            key = f"{r.strategy}_{comp}"
            if r.outcome == 1:
                aggregation['component_analysis'][key]['win_values'].append(value)
            else:
                aggregation['component_analysis'][key]['loss_values'].append(value)

    # Calculate win rates and best strategies per symbol
    for sym, data in aggregation['by_symbol'].items():
        if data['trades'] > 0:
            best_wr = 0
            best_strat = ''
            for strat, strat_data in data['strategies'].items():
                if strat_data['trades'] >= 10:
                    wr = strat_data['wins'] / strat_data['trades'] * 100
                    if wr > best_wr:
                        best_wr = wr
                        best_strat = strat
            data['best_strategy'] = best_strat
            data['best_strategy_wr'] = best_wr

    return aggregation


def calculate_optimal_parameters(aggregation: Dict) -> Dict[str, Any]:
    """Calculate optimal parameters for each strategy"""

    optimal = {}

    for strategy, data in aggregation['by_strategy'].items():
        if data['trades'] < 100:
            continue

        strategy_optimal = {
            'overall_win_rate': data['wins'] / data['trades'] * 100 if data['trades'] > 0 else 0,
            'total_trades': data['trades'],
            'total_pnl': data['pnl'],
            'optimal_min_score': 5.0,
            'optimal_holding_days': 45,
            'regime_adjustments': {},
            'score_analysis': {},
            'holding_analysis': {}
        }

        # Find optimal min score
        best_score_wr = 0
        for score, score_data in data['by_score'].items():
            if score_data['trades'] >= 50:
                wr = score_data['wins'] / score_data['trades'] * 100
                strategy_optimal['score_analysis'][score] = {
                    'trades': score_data['trades'],
                    'win_rate': wr,
                    'pnl': score_data['pnl']
                }
                if wr > best_score_wr:
                    best_score_wr = wr
                    strategy_optimal['optimal_min_score'] = float(score)

        # Find optimal holding period
        best_holding_wr = 0
        for holding, holding_data in data['by_holding'].items():
            if holding_data['trades'] >= 50:
                wr = holding_data['wins'] / holding_data['trades'] * 100
                strategy_optimal['holding_analysis'][holding] = {
                    'trades': holding_data['trades'],
                    'win_rate': wr,
                    'pnl': holding_data['pnl']
                }
                if wr > best_holding_wr:
                    best_holding_wr = wr
                    strategy_optimal['optimal_holding_days'] = holding

        # Regime adjustments
        base_wr = strategy_optimal['overall_win_rate']
        for regime, regime_data in data['by_regime'].items():
            if regime_data['trades'] >= 20:
                regime_wr = regime_data['wins'] / regime_data['trades'] * 100
                diff = regime_wr - base_wr

                if diff > 5:
                    adjustment = 1.0
                elif diff > 2:
                    adjustment = 0.5
                elif diff < -5:
                    adjustment = -1.0
                elif diff < -2:
                    adjustment = -0.5
                else:
                    adjustment = 0.0

                strategy_optimal['regime_adjustments'][regime] = {
                    'adjustment': adjustment,
                    'win_rate': regime_wr,
                    'trades': regime_data['trades'],
                    'pnl': regime_data['pnl']
                }

        optimal[strategy] = strategy_optimal

    return optimal


def calculate_component_weights(aggregation: Dict) -> Dict[str, Dict]:
    """Calculate optimal component weights based on win correlation"""

    weights = {}

    for comp_key, data in aggregation['component_analysis'].items():
        win_vals = data['win_values']
        loss_vals = data['loss_values']

        if len(win_vals) < 20 or len(loss_vals) < 20:
            continue

        try:
            win_mean = statistics.mean(win_vals)
            loss_mean = statistics.mean(loss_vals)
            diff = win_mean - loss_mean

            # Calculate effect size (Cohen's d approximation)
            pooled_std = statistics.stdev(win_vals + loss_vals)
            effect_size = diff / pooled_std if pooled_std > 0 else 0

            # Convert to weight
            if effect_size > 0.5:
                weight = 1.5
            elif effect_size > 0.2:
                weight = 1.2
            elif effect_size < -0.5:
                weight = 0.5
            elif effect_size < -0.2:
                weight = 0.8
            else:
                weight = 1.0

            weights[comp_key] = {
                'weight': weight,
                'effect_size': effect_size,
                'win_mean': win_mean,
                'loss_mean': loss_mean,
                'sample_size': len(win_vals) + len(loss_vals)
            }
        except Exception:
            continue

    return weights


def save_intensive_results(
    aggregation: Dict,
    optimal_params: Dict,
    component_weights: Dict,
    progress: IntensiveProgress
):
    """Save all intensive training results"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Full aggregation
    agg_export = {
        'total_trades': aggregation['total_trades'],
        'total_wins': aggregation['total_wins'],
        'win_rate': aggregation['total_wins'] / aggregation['total_trades'] * 100 if aggregation['total_trades'] > 0 else 0,
        'total_pnl': aggregation['total_pnl'],
        'by_strategy': {
            s: {
                'trades': d['trades'],
                'wins': d['wins'],
                'win_rate': d['wins'] / d['trades'] * 100 if d['trades'] > 0 else 0,
                'pnl': d['pnl'],
                'by_regime': dict(d['by_regime']),
                'by_score': dict(d['by_score']),
                'by_holding': dict(d['by_holding']),
                'exit_reasons': dict(d['by_exit_reason'])
            }
            for s, d in aggregation['by_strategy'].items()
        },
        'by_regime': dict(aggregation['by_regime'])
    }

    with open(OUTPUT_DIR / f'intensive_aggregation_{timestamp}.json', 'w') as f:
        json.dump(agg_export, f, indent=2, default=str)

    # 2. Symbol performance
    symbol_export = {
        sym: {
            'trades': d['trades'],
            'wins': d['wins'],
            'win_rate': d['wins'] / d['trades'] * 100 if d['trades'] > 0 else 0,
            'pnl': d['pnl'],
            'best_strategy': d['best_strategy'],
            'best_strategy_wr': d['best_strategy_wr']
        }
        for sym, d in aggregation['by_symbol'].items()
        if d['trades'] >= 10
    }

    with open(OUTPUT_DIR / f'intensive_symbols_{timestamp}.json', 'w') as f:
        json.dump(symbol_export, f, indent=2)

    # 3. Optimal parameters
    with open(OUTPUT_DIR / f'intensive_optimal_{timestamp}.json', 'w') as f:
        json.dump(optimal_params, f, indent=2, default=str)

    # 4. Component weights
    with open(OUTPUT_DIR / f'intensive_weights_{timestamp}.json', 'w') as f:
        json.dump(component_weights, f, indent=2)

    # 5. Final production config
    final_config = {
        'version': '4.0.0',
        'created_at': datetime.now().isoformat(),
        'training_type': 'intensive_full_day',
        'training_duration_hours': progress.elapsed_hours(),
        'total_trades_analyzed': progress.trades_analyzed,
        'strategies': {}
    }

    for strategy, params in optimal_params.items():
        regime_adj = {
            r: d['adjustment']
            for r, d in params.get('regime_adjustments', {}).items()
        }

        final_config['strategies'][strategy] = {
            'enabled': True,
            'min_score': params.get('optimal_min_score', 6.0),
            'holding_days': params.get('optimal_holding_days', 45),
            'expected_win_rate': params.get('overall_win_rate', 0),
            'regime_adjustments': regime_adj,
            'score_analysis': params.get('score_analysis', {}),
            'holding_analysis': params.get('holding_analysis', {})
        }

    with open(OUTPUT_DIR / 'INTENSIVE_TRAINING_RESULT.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    with open(OUTPUT_DIR / 'intensive_latest.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    logger.info(f"All results saved to {OUTPUT_DIR}")


def main():
    """Main intensive training pipeline"""

    progress = IntensiveProgress()

    logger.info("=" * 70)
    logger.info("  OPTIONPLAY INTENSIVE FULL-DAY TRAINING")
    logger.info("  Analyzing EVERY trading day (no sampling)")
    logger.info(f"  Started: {progress.start_time}")
    logger.info("=" * 70)

    try:
        # Load data
        progress.phase = "Loading Data"
        progress.save()
        logger.info("Loading historical data...")

        tracker = TradeTracker()
        stats = tracker.get_storage_stats()

        logger.info(f"  Symbols: {stats['symbols_with_price_data']}")
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

        logger.info(f"  Loaded: {len(historical_data)} symbols")

        # Analyze each strategy
        all_results: List[DetailedTradeResult] = []

        for strategy in STRATEGIES:
            progress.phase = f"Analyzing {strategy}"
            progress.current_strategy = strategy
            progress.symbols_processed = 0
            progress.save()

            logger.info(f"\n{'='*70}")
            logger.info(f"  STRATEGY: {strategy.upper()}")
            logger.info("=" * 70)

            try:
                analyzer = create_analyzer(strategy)
            except Exception as e:
                logger.error(f"Failed to create analyzer for {strategy}: {e}")
                continue

            for i, symbol in enumerate(symbols):
                progress.current_symbol = symbol
                progress.symbols_processed = i + 1
                progress.current_phase_progress = (i + 1) / len(symbols) * 100

                try:
                    symbol_results = analyze_symbol_intensive(
                        symbol=symbol,
                        symbol_data=historical_data.get(symbol, []),
                        vix_data=vix_data,
                        strategy=strategy,
                        analyzer=analyzer,
                        progress=progress
                    )
                    all_results.extend(symbol_results)
                except Exception as e:
                    logger.warning(f"Error analyzing {symbol}/{strategy}: {e}")

                if (i + 1) % 50 == 0:
                    logger.info(f"  {strategy}: {i+1}/{len(symbols)} symbols, {progress.trades_analyzed:,} total trades")
                    progress.save()

            logger.info(f"  {strategy} complete: {len([r for r in all_results if r.strategy == strategy]):,} trades")

        # Aggregate results
        progress.phase = "Aggregating Results"
        progress.save()
        logger.info("\nAggregating results...")

        aggregation = aggregate_results(all_results)

        logger.info(f"  Total trades: {aggregation['total_trades']:,}")
        logger.info(f"  Total wins: {aggregation['total_wins']:,}")
        logger.info(f"  Win rate: {aggregation['total_wins']/aggregation['total_trades']*100:.1f}%")
        logger.info(f"  Total P&L: ${aggregation['total_pnl']:,.0f}")

        # Calculate optimal parameters
        progress.phase = "Calculating Optimal Parameters"
        progress.save()
        logger.info("\nCalculating optimal parameters...")

        optimal_params = calculate_optimal_parameters(aggregation)

        for strategy, params in optimal_params.items():
            logger.info(f"  {strategy}:")
            logger.info(f"    Win Rate: {params['overall_win_rate']:.1f}%")
            logger.info(f"    Optimal Min Score: {params['optimal_min_score']}")
            logger.info(f"    Optimal Holding: {params['optimal_holding_days']} days")

        # Calculate component weights
        progress.phase = "Calculating Component Weights"
        progress.save()
        logger.info("\nCalculating component weights...")

        component_weights = calculate_component_weights(aggregation)
        logger.info(f"  {len(component_weights)} component weights calculated")

        # Save results
        progress.phase = "Saving Results"
        progress.save()

        save_intensive_results(aggregation, optimal_params, component_weights, progress)

        # Final summary
        progress.phase = "Complete"
        progress.save()

        logger.info("\n" + "=" * 70)
        logger.info("  INTENSIVE TRAINING COMPLETE")
        logger.info("=" * 70)
        logger.info(f"  Duration: {progress.elapsed_hours():.2f} hours")
        logger.info(f"  Symbols: {progress.total_symbols}")
        logger.info(f"  Trades Analyzed: {progress.trades_analyzed:,}")
        logger.info(f"  Output: {OUTPUT_DIR}")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        progress.phase = f"Error: {str(e)}"
        progress.save()
        raise


if __name__ == '__main__':
    main()
