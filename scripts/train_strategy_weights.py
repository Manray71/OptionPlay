#!/usr/bin/env python3
"""
OptionPlay - Strategy Component Weight Training
================================================

Trainiert optimale Komponenten-Gewichte für jede Strategie basierend auf
historischen Trade-Ergebnissen.

Das Script analysiert welche Score-Komponenten tatsächlich Gewinne vorhersagen
und passt die Gewichte entsprechend an.

Features:
- Walk-Forward Cross-Validation
- Per-Regime Weight Optimization
- Component Correlation Analysis
- Exportiert trainierte Gewichte für Produktion

Usage:
    # Alle Strategien trainieren
    python scripts/train_strategy_weights.py

    # Einzelne Strategie
    python scripts/train_strategy_weights.py --strategy pullback

    # Mit detaillierter Ausgabe
    python scripts/train_strategy_weights.py --verbose

    # Export für Produktion
    python scripts/train_strategy_weights.py --export
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
import statistics
import logging
import numpy as np

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
from src.models.base import SignalType

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']

# Komponenten pro Strategie
STRATEGY_COMPONENTS = {
    'pullback': [
        'rsi_score', 'rsi_divergence_score', 'support_score', 'fib_score',
        'ma_score', 'trend_strength_score', 'volume_score', 'macd_score',
        'stoch_score', 'keltner_score'
    ],
    'bounce': [
        'support_test_score', 'rsi_score', 'rsi_divergence_score',
        'candlestick_score', 'volume_score', 'trend_score', 'macd_score',
        'stoch_score', 'keltner_score'
    ],
    'ath_breakout': [
        'ath_score', 'volume_score', 'trend_score', 'rsi_score',
        'relative_strength_score', 'macd_score', 'momentum_score',
        'keltner_score'
    ],
    'earnings_dip': [
        'dip_score', 'gap_score', 'rsi_score', 'stabilization_score',
        'volume_score', 'trend_score', 'macd_score', 'stoch_score',
        'keltner_score'
    ]
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TrainingConfig:
    """Konfiguration für Weight-Training"""
    train_months: int = 12
    test_months: int = 3
    step_months: int = 3
    min_trades_per_component: int = 30
    min_samples_for_weight: int = 20
    learning_rate: float = 0.1
    regularization: float = 0.01  # L2 regularization


@dataclass
class ComponentStats:
    """Statistiken für eine Score-Komponente"""
    component: str
    total_samples: int = 0
    win_samples: int = 0
    loss_samples: int = 0

    avg_value: float = 0.0
    avg_when_win: float = 0.0
    avg_when_loss: float = 0.0

    correlation_with_outcome: float = 0.0
    predictive_power: float = 0.0  # t-statistic or similar

    current_weight: float = 1.0
    optimal_weight: float = 1.0
    weight_change: float = 0.0


@dataclass
class StrategyWeights:
    """Optimierte Gewichte für eine Strategie"""
    strategy: str
    base_weights: Dict[str, float] = field(default_factory=dict)
    regime_adjustments: Dict[str, Dict[str, float]] = field(default_factory=dict)
    component_stats: Dict[str, ComponentStats] = field(default_factory=dict)

    # Validation Metrics
    in_sample_win_rate: float = 0.0
    out_sample_win_rate: float = 0.0
    improvement_pct: float = 0.0


@dataclass
class TradeForTraining:
    """Trade-Record für Training"""
    symbol: str
    signal_date: date
    signal_score: float
    outcome: int  # 1 = win, 0 = loss
    pnl: float
    vix: Optional[float] = None
    component_scores: Dict[str, float] = field(default_factory=dict)


# =============================================================================
# WEIGHT TRAINER
# =============================================================================

class StrategyWeightTrainer:
    """
    Trainiert optimale Komponenten-Gewichte für jede Strategie.

    Verwendet Walk-Forward Validation um Overfitting zu vermeiden.
    """

    def __init__(self, config: TrainingConfig):
        self.config = config
        self._analyzers = {}
        self._init_analyzers()

    def _init_analyzers(self):
        """Initialisiert Analyzer für Signal-Generierung"""
        self._analyzers['pullback'] = PullbackAnalyzer(PullbackScoringConfig())
        self._analyzers['bounce'] = BounceAnalyzer(BounceConfig())
        self._analyzers['ath_breakout'] = ATHBreakoutAnalyzer(ATHBreakoutConfig())
        self._analyzers['earnings_dip'] = EarningsDipAnalyzer(EarningsDipConfig())

    def collect_training_data(
        self,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        vix_data: Dict[date, float],
        start_date: date,
        end_date: date,
        min_score: float = 3.0,  # Niedrigerer Score für mehr Samples
    ) -> List[TradeForTraining]:
        """
        Sammelt Training-Daten durch Backtesting.

        Simuliert Trades und extrahiert Component-Scores für jeden.
        """
        analyzer = self._analyzers[strategy]
        trades: List[TradeForTraining] = []

        # Collect all trading days
        all_dates = set()
        for sym_data in historical_data.values():
            for bar in sym_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if start_date <= d <= end_date:
                    all_dates.add(d)

        trading_days = sorted(all_dates)
        symbols = list(historical_data.keys())

        # Track positions
        open_positions: Dict[str, Dict] = {}

        for current_date in trading_days:
            # Check exits
            for symbol in list(open_positions.keys()):
                pos = open_positions[symbol]
                exit_result = self._check_trade_outcome(
                    pos, current_date, historical_data.get(symbol, [])
                )
                if exit_result:
                    outcome, pnl = exit_result

                    trades.append(TradeForTraining(
                        symbol=symbol,
                        signal_date=pos['entry_date'],
                        signal_score=pos['score'],
                        outcome=1 if pnl > 0 else 0,
                        pnl=pnl,
                        vix=vix_data.get(pos['entry_date']),
                        component_scores=pos.get('component_scores', {})
                    ))
                    del open_positions[symbol]

            # Check entries
            for symbol in symbols:
                if symbol in open_positions:
                    continue

                symbol_data = historical_data.get(symbol, [])
                history = self._get_history_up_to(symbol_data, current_date, lookback=260)

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

                if signal.signal_type != SignalType.LONG:
                    continue
                if signal.score < min_score:
                    continue

                # Extract component scores
                component_scores = self._extract_component_scores(signal, strategy)

                open_positions[symbol] = {
                    'entry_date': current_date,
                    'entry_price': prices[-1],
                    'score': signal.score,
                    'component_scores': component_scores,
                    'expiry_date': current_date + timedelta(days=60),
                }

        return trades

    def _extract_component_scores(
        self,
        signal,
        strategy: str
    ) -> Dict[str, float]:
        """Extrahiert individuelle Komponenten-Scores aus Signal"""
        component_scores = {}

        if not signal.details:
            return component_scores

        # Try different possible locations for breakdown
        breakdown = None

        if 'score_breakdown' in signal.details:
            breakdown = signal.details['score_breakdown']
        elif 'breakdown' in signal.details:
            breakdown = signal.details['breakdown']

        if breakdown:
            if isinstance(breakdown, dict):
                component_scores = breakdown
            elif hasattr(breakdown, '__dict__'):
                component_scores = {
                    k: v for k, v in breakdown.__dict__.items()
                    if isinstance(v, (int, float)) and not k.startswith('_')
                }

        return component_scores

    def _get_history_up_to(
        self,
        symbol_data: List[Dict],
        target_date: date,
        lookback: int = 260
    ) -> List[Dict]:
        """Gets historical bars up to target_date"""
        bars_before = []
        for bar in symbol_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if d < target_date:
                bars_before.append({**bar, 'date': d})

        bars_before.sort(key=lambda x: x['date'])
        return bars_before[-lookback:] if len(bars_before) > lookback else bars_before

    def _get_price_on_date(
        self,
        symbol_data: List[Dict],
        target_date: date
    ) -> Optional[Dict]:
        """Gets price for specific date"""
        for bar in symbol_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if d == target_date:
                return bar
        return None

    def _check_trade_outcome(
        self,
        position: Dict,
        current_date: date,
        symbol_data: List[Dict]
    ) -> Optional[Tuple[str, float]]:
        """Checks if trade should be closed and returns outcome"""
        price_data = self._get_price_on_date(symbol_data, current_date)
        if not price_data:
            return None

        current_price = price_data['close']
        entry_price = position['entry_price']
        expiry = position['expiry_date']

        # Simplified exit logic
        short_strike = entry_price * 0.92
        long_strike = short_strike - (entry_price * 0.05)
        spread_width = short_strike - long_strike
        net_credit = spread_width * 0.20

        days_held = (current_date - position['entry_date']).days

        # Exit conditions
        if current_date >= expiry:
            if current_price >= short_strike:
                return ('max_profit', net_credit * 100)
            else:
                intrinsic = short_strike - current_price
                return ('expiration', (net_credit - intrinsic) * 100)

        if days_held >= 14:  # DTE threshold
            if current_price >= short_strike:
                return ('profit_target', net_credit * 100 * 0.5)  # 50% profit

        if current_price < long_strike:
            return ('max_loss', -(spread_width - net_credit) * 100)

        return None

    def calculate_component_stats(
        self,
        trades: List[TradeForTraining],
        strategy: str
    ) -> Dict[str, ComponentStats]:
        """Berechnet Statistiken für jede Komponente"""
        components = STRATEGY_COMPONENTS.get(strategy, [])
        stats: Dict[str, ComponentStats] = {}

        for component in components:
            # Filter trades that have this component
            relevant_trades = [
                t for t in trades
                if component in t.component_scores
            ]

            if len(relevant_trades) < self.config.min_samples_for_weight:
                continue

            winners = [t for t in relevant_trades if t.outcome == 1]
            losers = [t for t in relevant_trades if t.outcome == 0]

            cs = ComponentStats(
                component=component,
                total_samples=len(relevant_trades),
                win_samples=len(winners),
                loss_samples=len(losers),
            )

            all_values = [t.component_scores[component] for t in relevant_trades]
            cs.avg_value = statistics.mean(all_values) if all_values else 0

            if winners:
                cs.avg_when_win = statistics.mean(
                    t.component_scores[component] for t in winners
                )
            if losers:
                cs.avg_when_loss = statistics.mean(
                    t.component_scores[component] for t in losers
                )

            # Calculate correlation with outcome
            if len(relevant_trades) >= 10:
                try:
                    outcomes = np.array([t.outcome for t in relevant_trades])
                    values = np.array([t.component_scores[component] for t in relevant_trades])

                    # Pearson correlation
                    if np.std(values) > 0 and np.std(outcomes) > 0:
                        cs.correlation_with_outcome = float(
                            np.corrcoef(outcomes, values)[0, 1]
                        )

                    # T-test for predictive power
                    if winners and losers:
                        win_vals = np.array([t.component_scores[component] for t in winners])
                        loss_vals = np.array([t.component_scores[component] for t in losers])

                        if len(win_vals) >= 2 and len(loss_vals) >= 2:
                            mean_diff = np.mean(win_vals) - np.mean(loss_vals)
                            pooled_std = np.sqrt(
                                (np.var(win_vals) + np.var(loss_vals)) / 2
                            )
                            if pooled_std > 0:
                                cs.predictive_power = float(mean_diff / pooled_std)
                except Exception as e:
                    logger.warning(f"Error calculating stats for {component}: {e}")

            stats[component] = cs

        return stats

    def optimize_weights(
        self,
        component_stats: Dict[str, ComponentStats],
        strategy: str
    ) -> Dict[str, float]:
        """
        Optimiert Gewichte basierend auf Komponenten-Statistiken.

        Verwendet einen simplen aber robusten Ansatz:
        - Komponenten mit positiver Korrelation bekommen höhere Gewichte
        - Komponenten mit negativer Korrelation bekommen niedrigere Gewichte
        - Regularisierung verhindert extreme Gewichte
        """
        weights = {}

        for component, stats in component_stats.items():
            # Base weight adjustment based on correlation
            if stats.correlation_with_outcome > 0.1:
                # Positive correlation - increase weight
                adjustment = 1.0 + (stats.correlation_with_outcome * 0.5)
            elif stats.correlation_with_outcome < -0.1:
                # Negative correlation - decrease weight
                adjustment = 1.0 + (stats.correlation_with_outcome * 0.3)
            else:
                # No significant correlation
                adjustment = 1.0

            # Additional adjustment based on predictive power (t-stat)
            if stats.predictive_power > 0.5:
                adjustment *= 1.1
            elif stats.predictive_power < -0.5:
                adjustment *= 0.9

            # Regularization - prevent extreme weights
            adjustment = max(0.5, min(2.0, adjustment))

            # Apply learning rate
            current_weight = stats.current_weight
            optimal_weight = current_weight * (
                1.0 + self.config.learning_rate * (adjustment - 1.0)
            )

            # Update stats
            stats.optimal_weight = optimal_weight
            stats.weight_change = optimal_weight - current_weight

            weights[component] = optimal_weight

        return weights

    def train_strategy(
        self,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        vix_data: Dict[date, float],
    ) -> StrategyWeights:
        """
        Führt vollständiges Training für eine Strategie durch.

        Verwendet Walk-Forward Validation.
        """
        # Determine date range
        all_dates = set()
        for sym_data in historical_data.values():
            for bar in sym_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                all_dates.add(d)

        min_date = min(all_dates)
        max_date = max(all_dates)

        logger.info(f"Training {strategy} from {min_date} to {max_date}")

        # Generate epochs
        train_days = self.config.train_months * 30
        test_days = self.config.test_months * 30
        step_days = self.config.step_months * 30

        all_train_trades = []
        all_test_trades = []

        current_start = min_date
        epoch = 0

        while True:
            train_end = current_start + timedelta(days=train_days)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=test_days)

            if test_end > max_date:
                break

            epoch += 1
            logger.info(f"  Epoch {epoch}: {current_start} - {train_end} / {test_start} - {test_end}")

            # Collect training data
            train_trades = self.collect_training_data(
                strategy, historical_data, vix_data,
                current_start, train_end
            )

            test_trades = self.collect_training_data(
                strategy, historical_data, vix_data,
                test_start, test_end
            )

            all_train_trades.extend(train_trades)
            all_test_trades.extend(test_trades)

            current_start += timedelta(days=step_days)

        logger.info(f"  Collected {len(all_train_trades)} train, {len(all_test_trades)} test trades")

        # Calculate component statistics
        component_stats = self.calculate_component_stats(all_train_trades, strategy)

        if not component_stats:
            logger.warning(f"  No component data available for {strategy}")
            return StrategyWeights(strategy=strategy)

        # Optimize weights
        optimized_weights = self.optimize_weights(component_stats, strategy)

        # Calculate validation metrics
        in_sample_wins = sum(1 for t in all_train_trades if t.outcome == 1)
        in_sample_wr = (in_sample_wins / len(all_train_trades) * 100) if all_train_trades else 0

        out_sample_wins = sum(1 for t in all_test_trades if t.outcome == 1)
        out_sample_wr = (out_sample_wins / len(all_test_trades) * 100) if all_test_trades else 0

        result = StrategyWeights(
            strategy=strategy,
            base_weights=optimized_weights,
            component_stats=component_stats,
            in_sample_win_rate=in_sample_wr,
            out_sample_win_rate=out_sample_wr,
            improvement_pct=0.0,  # Would need simulation with new weights
        )

        return result


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def print_header(title: str, width: int = 80):
    """Prints a formatted header"""
    print()
    print("═" * width)
    print(f"  {title}")
    print("═" * width)


def print_strategy_weights(weights: StrategyWeights, verbose: bool = False):
    """Prints training results for a strategy"""
    print_header(f"STRATEGY: {weights.strategy.upper()}")

    print(f"\n  Training Results:")
    print(f"    In-Sample Win Rate:   {weights.in_sample_win_rate:.1f}%")
    print(f"    Out-Sample Win Rate:  {weights.out_sample_win_rate:.1f}%")
    print(f"    Degradation:          {weights.in_sample_win_rate - weights.out_sample_win_rate:+.1f}%")

    if weights.base_weights:
        print(f"\n  Optimized Component Weights:")
        print(f"  {'Component':<25} {'Weight':>10} {'Corr':>10} {'Pred':>10}")
        print("  " + "-" * 57)

        for component, weight in sorted(
            weights.base_weights.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            stats = weights.component_stats.get(component)
            if stats:
                weight_emoji = "⬆️" if weight > 1.1 else "⬇️" if weight < 0.9 else "➡️"
                print(
                    f"  {component:<25} "
                    f"{weight_emoji} {weight:>8.2f} "
                    f"{stats.correlation_with_outcome:>+9.3f} "
                    f"{stats.predictive_power:>+9.3f}"
                )

    if verbose and weights.component_stats:
        print(f"\n  Component Details:")
        print(f"  {'Component':<20} {'N':>6} {'Win Avg':>10} {'Loss Avg':>10} {'Diff':>10}")
        print("  " + "-" * 60)

        for component, stats in sorted(
            weights.component_stats.items(),
            key=lambda x: x[1].correlation_with_outcome,
            reverse=True
        ):
            diff = stats.avg_when_win - stats.avg_when_loss
            diff_emoji = "🟢" if diff > 0.3 else "🔴" if diff < -0.3 else "🟡"
            print(
                f"  {component:<20} "
                f"{stats.total_samples:>6} "
                f"{stats.avg_when_win:>10.2f} "
                f"{stats.avg_when_loss:>10.2f} "
                f"{diff_emoji} {diff:>+8.2f}"
            )


def save_weights(
    all_weights: List[StrategyWeights],
    output_path: Path
):
    """Saves trained weights to JSON"""
    data = {
        'version': '1.0.0',
        'created_at': datetime.now().isoformat(),
        'strategies': {}
    }

    for w in all_weights:
        data['strategies'][w.strategy] = {
            'base_weights': w.base_weights,
            'regime_adjustments': w.regime_adjustments,
            'validation': {
                'in_sample_win_rate': w.in_sample_win_rate,
                'out_sample_win_rate': w.out_sample_win_rate,
            },
            'component_stats': {
                k: {
                    'samples': v.total_samples,
                    'correlation': v.correlation_with_outcome,
                    'predictive_power': v.predictive_power,
                    'avg_when_win': v.avg_when_win,
                    'avg_when_loss': v.avg_when_loss,
                }
                for k, v in w.component_stats.items()
            }
        }

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\n  Weights saved to: {output_path}")


def export_for_production(
    all_weights: List[StrategyWeights],
    output_dir: Path
):
    """Exports weights in production-ready format"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Separate file per strategy
    for w in all_weights:
        strategy_config = {
            'strategy': w.strategy,
            'version': '1.0.0',
            'created_at': datetime.now().isoformat(),
            'component_weights': w.base_weights,
            'regime_adjustments': w.regime_adjustments,
        }

        path = output_dir / f'{w.strategy}_weights.json'
        with open(path, 'w') as f:
            json.dump(strategy_config, f, indent=2)

        print(f"  Exported: {path}")

    # Combined file
    combined = {
        'version': '1.0.0',
        'created_at': datetime.now().isoformat(),
        'strategies': {
            w.strategy: {
                'component_weights': w.base_weights,
                'regime_adjustments': w.regime_adjustments,
            }
            for w in all_weights
        }
    }

    combined_path = output_dir / 'all_strategy_weights.json'
    with open(combined_path, 'w') as f:
        json.dump(combined, f, indent=2)

    print(f"  Combined: {combined_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Train strategy component weights',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--strategy', type=str,
                        choices=['pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'all'],
                        default='all', help='Strategy to train (default: all)')
    parser.add_argument('--train-months', type=int, default=12,
                        help='Training period months (default: 12)')
    parser.add_argument('--test-months', type=int, default=3,
                        help='Test period months (default: 3)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output with component details')
    parser.add_argument('--output', type=str,
                        help='Save weights to JSON file')
    parser.add_argument('--export', action='store_true',
                        help='Export for production use')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
    )

    print_header("OPTIONPLAY STRATEGY WEIGHT TRAINING")

    # Load data
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    if stats['symbols_with_price_data'] == 0:
        print("\n  ❌ No historical data found!")
        print("     Run first: python scripts/backfill_tradier.py")
        sys.exit(1)

    print(f"\n  Database: {stats['symbols_with_price_data']} symbols")
    print(f"  Price Bars: {stats['total_price_bars']:,}")
    print(f"  VIX Data: {stats['vix_data_points']:,} points")

    # Load historical data
    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_info]

    print(f"\n  Loading data for {len(symbols)} symbols...")

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

    # Load VIX data
    vix_data = {}
    vix_points = tracker.get_vix_data()
    for p in vix_points:
        vix_data[p.date] = p.value

    print(f"  Loaded: {len(historical_data)} symbols")

    # Configure training
    config = TrainingConfig(
        train_months=args.train_months,
        test_months=args.test_months,
    )

    print(f"\n  Config:")
    print(f"    Train Period: {config.train_months} months")
    print(f"    Test Period:  {config.test_months} months")

    # Train
    trainer = StrategyWeightTrainer(config)
    all_weights: List[StrategyWeights] = []

    strategies = [args.strategy] if args.strategy != 'all' else STRATEGIES

    print_header("TRAINING WEIGHTS...")

    for strategy in strategies:
        print(f"\n  Training {strategy}...")

        try:
            weights = trainer.train_strategy(
                strategy=strategy,
                historical_data=historical_data,
                vix_data=vix_data,
            )
            all_weights.append(weights)

            n_components = len(weights.base_weights)
            print(f"    ✓ {n_components} components, IS: {weights.in_sample_win_rate:.1f}%, OOS: {weights.out_sample_win_rate:.1f}%")

        except Exception as e:
            print(f"    ❌ Error: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Print results
    for weights in all_weights:
        print_strategy_weights(weights, verbose=args.verbose)

    # Save
    if args.output:
        save_weights(all_weights, Path(args.output))
    else:
        output_dir = Path.home() / '.optionplay' / 'models'
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f'weights_{timestamp}.json'
        save_weights(all_weights, output_path)

    # Export
    if args.export:
        output_dir = Path.home() / '.optionplay' / 'models'
        export_for_production(all_weights, output_dir)

    # Summary
    print_header("SUMMARY")

    if all_weights:
        print(f"\n  {'Strategy':<20} {'Components':>12} {'IS Win%':>10} {'OOS Win%':>10} {'Degrad':>10}")
        print("  " + "-" * 65)

        for w in all_weights:
            deg = w.in_sample_win_rate - w.out_sample_win_rate
            deg_emoji = "🟢" if deg < 5 else "🟡" if deg < 10 else "🔴"
            print(
                f"  {w.strategy:<20} "
                f"{len(w.base_weights):>12} "
                f"{w.in_sample_win_rate:>9.1f}% "
                f"{w.out_sample_win_rate:>9.1f}% "
                f"{deg_emoji} {deg:>+8.1f}%"
            )

    print("\n" + "═" * 80)


if __name__ == '__main__':
    main()
