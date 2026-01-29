#!/usr/bin/env python3
"""
OptionPlay - Fast Strategy Training
====================================

Optimiertes Training für alle Strategien mit:
- Parallelisierung pro Symbol
- Effizientes Caching
- Reduzierte Epochen für schnelleres Feedback

Usage:
    python scripts/fast_strategy_train.py
    python scripts/fast_strategy_train.py --strategy pullback
    python scripts/fast_strategy_train.py --epochs 3
"""

import argparse
import json
import sys
import logging
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
import statistics
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

# Suppress warnings
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']

VIX_THRESHOLDS = {
    'low': (0, 15),
    'normal': (15, 20),
    'elevated': (20, 30),
    'high': (30, 100),
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TrainConfig:
    """Training configuration"""
    train_months: int = 9
    test_months: int = 3
    step_months: int = 3
    max_epochs: int = 5
    min_score: float = 5.0
    min_trades_per_epoch: int = 15


@dataclass
class EpochMetrics:
    """Metrics for one training epoch"""
    epoch: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    # In-Sample
    is_trades: int = 0
    is_wins: int = 0
    is_pnl: float = 0.0

    # Out-of-Sample
    oos_trades: int = 0
    oos_wins: int = 0
    oos_pnl: float = 0.0

    # Optimal parameters found
    optimal_score: float = 5.0

    @property
    def is_win_rate(self) -> float:
        return (self.is_wins / self.is_trades * 100) if self.is_trades > 0 else 0

    @property
    def oos_win_rate(self) -> float:
        return (self.oos_wins / self.oos_trades * 100) if self.oos_trades > 0 else 0

    @property
    def degradation(self) -> float:
        return self.is_win_rate - self.oos_win_rate


@dataclass
class StrategyTrainResult:
    """Training result for one strategy"""
    strategy: str
    epochs: List[EpochMetrics] = field(default_factory=list)

    # Aggregated metrics
    total_oos_trades: int = 0
    total_oos_pnl: float = 0.0
    avg_is_win_rate: float = 0.0
    avg_oos_win_rate: float = 0.0
    avg_degradation: float = 0.0

    # Per-regime performance
    regime_metrics: Dict[str, Dict] = field(default_factory=dict)

    # Recommended parameters
    recommended_min_score: float = 5.0
    regime_adjustments: Dict[str, float] = field(default_factory=dict)

    def calculate_aggregates(self):
        """Calculate aggregate metrics from epochs"""
        valid_epochs = [e for e in self.epochs if e.oos_trades >= 5]

        if not valid_epochs:
            return

        self.total_oos_trades = sum(e.oos_trades for e in valid_epochs)
        self.total_oos_pnl = sum(e.oos_pnl for e in valid_epochs)
        self.avg_is_win_rate = statistics.mean(e.is_win_rate for e in valid_epochs)
        self.avg_oos_win_rate = statistics.mean(e.oos_win_rate for e in valid_epochs)
        self.avg_degradation = statistics.mean(e.degradation for e in valid_epochs)

        # Best performing score threshold
        best_epoch = max(valid_epochs, key=lambda e: e.oos_pnl)
        self.recommended_min_score = best_epoch.optimal_score


# =============================================================================
# SIMPLIFIED BACKTESTER (for fast training)
# =============================================================================

class FastBacktester:
    """
    Simplified backtester for fast training iterations.
    Uses simplified P&L calculation without full spread simulation.
    """

    def __init__(self, min_score: float = 5.0):
        self.min_score = min_score
        self._analyzers = {}
        self._init_analyzers()

    def _init_analyzers(self):
        """Initialize analyzers"""
        from src.config.config_loader import PullbackScoringConfig
        from src.analyzers.pullback import PullbackAnalyzer
        from src.analyzers.bounce import BounceAnalyzer, BounceConfig
        from src.analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
        from src.analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig

        self._analyzers['pullback'] = PullbackAnalyzer(PullbackScoringConfig())
        self._analyzers['bounce'] = BounceAnalyzer(BounceConfig())
        self._analyzers['ath_breakout'] = ATHBreakoutAnalyzer(ATHBreakoutConfig())
        self._analyzers['earnings_dip'] = EarningsDipAnalyzer(EarningsDipConfig())

    def run_period(
        self,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        vix_data: Dict[date, float],
        start_date: date,
        end_date: date,
    ) -> Tuple[int, int, float, Dict[str, List]]:
        """
        Run backtest for a period.

        Returns: (total_trades, wins, pnl, regime_trades)
        """
        from src.models.base import SignalType

        analyzer = self._analyzers[strategy]

        trades = 0
        wins = 0
        pnl = 0.0
        regime_trades: Dict[str, List] = defaultdict(list)

        # Collect trading days
        all_dates = set()
        for sym_data in historical_data.values():
            for bar in sym_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if start_date <= d <= end_date:
                    all_dates.add(d)

        trading_days = sorted(all_dates)

        # Simplified: check signals once per week to speed up
        check_dates = trading_days[::5]  # Every 5th day

        for current_date in check_dates:
            for symbol, sym_data in historical_data.items():
                # Get history
                history = []
                for bar in sym_data:
                    d = bar['date']
                    if isinstance(d, str):
                        d = date.fromisoformat(d)
                    if d < current_date:
                        history.append({**bar, 'date': d})

                history.sort(key=lambda x: x['date'])
                history = history[-250:] if len(history) > 250 else history

                if len(history) < 200:
                    continue

                # Analyze
                try:
                    prices = [bar['close'] for bar in history]
                    volumes = [bar['volume'] for bar in history]
                    highs = [bar['high'] for bar in history]
                    lows = [bar['low'] for bar in history]

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
                if signal.score < self.min_score:
                    continue

                # Simulate trade outcome (simplified)
                entry_price = prices[-1]

                # Look forward 30 days for outcome
                future_prices = []
                for bar in sym_data:
                    d = bar['date']
                    if isinstance(d, str):
                        d = date.fromisoformat(d)
                    if current_date < d <= current_date + timedelta(days=45):
                        future_prices.append(bar['close'])

                if not future_prices:
                    continue

                # Calculate outcome
                max_future = max(future_prices) if future_prices else entry_price
                min_future = min(future_prices) if future_prices else entry_price

                short_strike = entry_price * 0.92  # 8% OTM

                # Win if price stayed above short strike
                is_win = min_future > short_strike * 0.98

                # Simplified P&L
                if is_win:
                    trade_pnl = entry_price * 0.01 * 100  # ~1% gain
                else:
                    trade_pnl = -entry_price * 0.04 * 100  # ~4% loss

                trades += 1
                if is_win:
                    wins += 1
                pnl += trade_pnl

                # Track by regime
                vix = vix_data.get(current_date, 18.0)
                regime = self._get_regime(vix)
                regime_trades[regime].append({
                    'win': is_win,
                    'pnl': trade_pnl,
                    'score': signal.score,
                })

        return trades, wins, pnl, dict(regime_trades)

    def _get_regime(self, vix: float) -> str:
        for regime, (low, high) in VIX_THRESHOLDS.items():
            if low <= vix < high:
                return regime
        return 'normal'


# =============================================================================
# TRAINER
# =============================================================================

class FastTrainer:
    """Fast strategy trainer"""

    def __init__(self, config: TrainConfig):
        self.config = config

    def train_strategy(
        self,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        vix_data: Dict[date, float],
    ) -> StrategyTrainResult:
        """Train one strategy with walk-forward validation"""

        result = StrategyTrainResult(strategy=strategy)

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

        # Generate epochs
        train_days = self.config.train_months * 30
        test_days = self.config.test_months * 30
        step_days = self.config.step_months * 30

        epochs = []
        current_start = min_date

        while len(epochs) < self.config.max_epochs:
            train_end = current_start + timedelta(days=train_days)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=test_days)

            if test_end > max_date:
                break

            epochs.append((current_start, train_end, test_start, test_end))
            current_start += timedelta(days=step_days)

        logger.info(f"  Training {strategy}: {len(epochs)} epochs")

        all_regime_trades: Dict[str, List] = defaultdict(list)

        for i, (train_start, train_end, test_start, test_end) in enumerate(epochs):
            # Find optimal score threshold on training data
            best_score = self.config.min_score
            best_metric = -999

            for score_thresh in [4.0, 5.0, 6.0, 7.0]:
                backtester = FastBacktester(min_score=score_thresh)
                trades, wins, pnl, _ = backtester.run_period(
                    strategy, historical_data, vix_data,
                    train_start, train_end
                )

                if trades >= self.config.min_trades_per_epoch:
                    win_rate = wins / trades if trades > 0 else 0
                    # Metric: balance win rate and trade count
                    metric = win_rate * 0.7 + (min(trades, 100) / 100) * 0.3

                    if metric > best_metric:
                        best_metric = metric
                        best_score = score_thresh

            # Test with optimal score
            backtester = FastBacktester(min_score=best_score)

            is_trades, is_wins, is_pnl, _ = backtester.run_period(
                strategy, historical_data, vix_data,
                train_start, train_end
            )

            oos_trades, oos_wins, oos_pnl, oos_regime = backtester.run_period(
                strategy, historical_data, vix_data,
                test_start, test_end
            )

            epoch_metrics = EpochMetrics(
                epoch=i + 1,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                is_trades=is_trades,
                is_wins=is_wins,
                is_pnl=is_pnl,
                oos_trades=oos_trades,
                oos_wins=oos_wins,
                oos_pnl=oos_pnl,
                optimal_score=best_score,
            )

            result.epochs.append(epoch_metrics)

            # Collect regime trades
            for regime, trades_list in oos_regime.items():
                all_regime_trades[regime].extend(trades_list)

            logger.info(
                f"    Epoch {i+1}: IS {is_trades} trades ({epoch_metrics.is_win_rate:.0f}%), "
                f"OOS {oos_trades} trades ({epoch_metrics.oos_win_rate:.0f}%), "
                f"Score: {best_score}"
            )

        # Calculate regime-specific metrics
        for regime, trades_list in all_regime_trades.items():
            if trades_list:
                wins = sum(1 for t in trades_list if t['win'])
                total_pnl = sum(t['pnl'] for t in trades_list)
                result.regime_metrics[regime] = {
                    'trades': len(trades_list),
                    'wins': wins,
                    'win_rate': wins / len(trades_list) * 100,
                    'pnl': total_pnl,
                    'avg_score': statistics.mean(t['score'] for t in trades_list),
                }

                # Regime adjustments
                win_rate = wins / len(trades_list) * 100
                if win_rate >= 70:
                    result.regime_adjustments[regime] = -0.5  # Lower score OK
                elif win_rate < 50:
                    result.regime_adjustments[regime] = +1.0  # Higher score needed
                else:
                    result.regime_adjustments[regime] = 0.0

        result.calculate_aggregates()

        return result


# =============================================================================
# OUTPUT
# =============================================================================

def print_result(result: StrategyTrainResult):
    """Print training result"""
    print()
    print("═" * 70)
    print(f"  STRATEGY: {result.strategy.upper()}")
    print("═" * 70)

    valid_epochs = [e for e in result.epochs if e.oos_trades >= 5]

    print(f"\n  Epochs Trained:        {len(result.epochs)}")
    print(f"  Valid Epochs:          {len(valid_epochs)}")
    print(f"  Total OOS Trades:      {result.total_oos_trades}")
    print(f"  Total OOS P&L:         ${result.total_oos_pnl:+,.0f}")
    print()
    print(f"  Avg In-Sample Win%:   {result.avg_is_win_rate:.1f}%")
    print(f"  Avg Out-Sample Win%:  {result.avg_oos_win_rate:.1f}%")
    print(f"  Avg Degradation:       {result.avg_degradation:+.1f}%")
    print()
    print(f"  Recommended Min Score: {result.recommended_min_score:.1f}")

    if result.regime_metrics:
        print("\n  VIX Regime Performance:")
        print(f"  {'Regime':<12} {'Trades':>8} {'Win%':>8} {'P&L':>12} {'Adj':>8}")
        print("  " + "-" * 50)

        for regime, metrics in sorted(result.regime_metrics.items()):
            adj = result.regime_adjustments.get(regime, 0)
            emoji = "🟢" if metrics['win_rate'] >= 60 else "🟡" if metrics['win_rate'] >= 50 else "🔴"
            print(
                f"  {regime:<12} "
                f"{metrics['trades']:>8} "
                f"{emoji} {metrics['win_rate']:>5.1f}% "
                f"${metrics['pnl']:>+10,.0f} "
                f"{adj:>+7.1f}"
            )

    # Overfitting assessment
    deg = result.avg_degradation
    if deg < 5:
        severity = "🟢 NONE"
    elif deg < 10:
        severity = "🟡 MILD"
    elif deg < 15:
        severity = "🟠 MODERATE"
    else:
        severity = "🔴 SEVERE"

    print(f"\n  Overfitting Severity:  {severity}")
    print("═" * 70)


def save_models(results: List[StrategyTrainResult], output_dir: Path):
    """Save trained models"""
    output_dir.mkdir(parents=True, exist_ok=True)

    models = {
        'version': '1.0.0',
        'created_at': datetime.now().isoformat(),
        'strategies': {}
    }

    for r in results:
        models['strategies'][r.strategy] = {
            'recommended_min_score': r.recommended_min_score,
            'regime_adjustments': r.regime_adjustments,
            'validation': {
                'total_oos_trades': r.total_oos_trades,
                'avg_oos_win_rate': r.avg_oos_win_rate,
                'avg_degradation': r.avg_degradation,
            },
            'regime_performance': r.regime_metrics,
        }

    path = output_dir / 'trained_models.json'
    with open(path, 'w') as f:
        json.dump(models, f, indent=2, default=str)

    print(f"\n  Models saved to: {path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Fast strategy training')
    parser.add_argument('--strategy', choices=STRATEGIES + ['all'], default='all')
    parser.add_argument('--epochs', type=int, default=5, help='Max epochs per strategy')
    parser.add_argument('--train-months', type=int, default=9)
    parser.add_argument('--test-months', type=int, default=3)

    args = parser.parse_args()

    print("═" * 70)
    print("  OPTIONPLAY FAST STRATEGY TRAINING")
    print("═" * 70)

    # Load data
    from src.backtesting import TradeTracker

    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    if stats['symbols_with_price_data'] == 0:
        print("\n  ❌ No historical data found!")
        sys.exit(1)

    print(f"\n  Database: {stats['symbols_with_price_data']} symbols")
    print(f"  Loading data...")

    # Load historical data
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

    # Load VIX
    vix_data = {}
    for p in tracker.get_vix_data():
        vix_data[p.date] = p.value

    print(f"  Loaded: {len(historical_data)} symbols, {len(vix_data)} VIX points")

    # Configure training
    config = TrainConfig(
        train_months=args.train_months,
        test_months=args.test_months,
        max_epochs=args.epochs,
    )

    print(f"\n  Config:")
    print(f"    Train: {config.train_months} months")
    print(f"    Test:  {config.test_months} months")
    print(f"    Epochs: {config.max_epochs}")

    # Train
    trainer = FastTrainer(config)
    results: List[StrategyTrainResult] = []

    strategies = [args.strategy] if args.strategy != 'all' else STRATEGIES

    print("\n" + "═" * 70)
    print("  TRAINING...")
    print("═" * 70)

    for strategy in strategies:
        try:
            result = trainer.train_strategy(strategy, historical_data, vix_data)
            results.append(result)
        except Exception as e:
            logger.error(f"  Error training {strategy}: {e}")
            import traceback
            traceback.print_exc()

    # Print results
    for result in results:
        print_result(result)

    # Comparison table
    if len(results) > 1:
        print("\n" + "═" * 80)
        print("  STRATEGY COMPARISON")
        print("═" * 80)
        print(f"\n  {'Strategy':<15} {'OOS Trades':>12} {'OOS Win%':>10} {'OOS P&L':>12} {'Degrad':>10} {'Score':>8}")
        print("  " + "-" * 70)

        for r in sorted(results, key=lambda x: x.total_oos_pnl, reverse=True):
            emoji = "🟢" if r.avg_degradation < 10 else "🟡" if r.avg_degradation < 15 else "🔴"
            print(
                f"  {r.strategy:<15} "
                f"{r.total_oos_trades:>12} "
                f"{r.avg_oos_win_rate:>9.1f}% "
                f"${r.total_oos_pnl:>+10,.0f} "
                f"{emoji} {r.avg_degradation:>+7.1f}% "
                f"{r.recommended_min_score:>7.1f}"
            )

    # Save models
    output_dir = Path.home() / '.optionplay' / 'models'
    save_models(results, output_dir)

    print("\n" + "═" * 70)
    print("  TRAINING COMPLETE")
    print("═" * 70)


if __name__ == '__main__':
    main()
