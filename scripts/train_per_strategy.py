#!/usr/bin/env python3
"""
OptionPlay - Strategy-Specific Walk-Forward Training
=====================================================

Führt Walk-Forward Training individuell für jede Strategie durch.
Trainiert optimale Parameter und erkennt Overfitting.

Strategien:
- pullback
- bounce
- ath_breakout
- earnings_dip

Usage:
    # Alle Strategien trainieren
    python scripts/train_per_strategy.py

    # Einzelne Strategie
    python scripts/train_per_strategy.py --strategy pullback

    # Mit Parameter-Optimierung
    python scripts/train_per_strategy.py --optimize

    # Quick Mode
    python scripts/train_per_strategy.py --quick
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
import statistics
import logging

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
from src.analyzers.base import BaseAnalyzer
from src.models.base import TradeSignal, SignalType

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TrainingConfig:
    """Konfiguration für Walk-Forward Training"""
    train_months: int = 12
    test_months: int = 3
    step_months: int = 3
    min_trades_per_epoch: int = 30
    min_valid_epochs: int = 3
    initial_capital: float = 100000.0
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 100.0
    min_score: float = 5.0
    dte_max: int = 60


@dataclass
class EpochResult:
    """Ergebnis einer Training-Epoche"""
    epoch_id: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    in_sample_trades: int
    in_sample_win_rate: float
    in_sample_pnl: float
    out_sample_trades: int
    out_sample_win_rate: float
    out_sample_pnl: float
    win_rate_degradation: float
    is_valid: bool
    skip_reason: str = ""


@dataclass
class StrategyTrainingResult:
    """Training-Ergebnis für eine Strategie"""
    strategy: str
    epochs: List[EpochResult]
    total_epochs: int = 0
    valid_epochs: int = 0
    avg_in_sample_win_rate: float = 0.0
    avg_out_sample_win_rate: float = 0.0
    avg_win_rate_degradation: float = 0.0
    avg_in_sample_pnl: float = 0.0
    avg_out_sample_pnl: float = 0.0
    overfit_severity: str = "unknown"
    recommended_min_score: float = 5.0

    def __post_init__(self):
        if self.epochs:
            self._calculate_metrics()

    def _calculate_metrics(self):
        valid = [e for e in self.epochs if e.is_valid]
        self.total_epochs = len(self.epochs)
        self.valid_epochs = len(valid)

        if valid:
            self.avg_in_sample_win_rate = statistics.mean(e.in_sample_win_rate for e in valid)
            self.avg_out_sample_win_rate = statistics.mean(e.out_sample_win_rate for e in valid)
            self.avg_win_rate_degradation = statistics.mean(e.win_rate_degradation for e in valid)
            self.avg_in_sample_pnl = statistics.mean(e.in_sample_pnl for e in valid)
            self.avg_out_sample_pnl = statistics.mean(e.out_sample_pnl for e in valid)

            # Determine overfit severity
            deg = self.avg_win_rate_degradation
            if deg < 5:
                self.overfit_severity = "none"
            elif deg < 10:
                self.overfit_severity = "mild"
            elif deg < 15:
                self.overfit_severity = "moderate"
            else:
                self.overfit_severity = "severe"


# =============================================================================
# STRATEGY TRAINER
# =============================================================================

class StrategyTrainer:
    """Walk-Forward Trainer für einzelne Strategien"""

    STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']

    def __init__(self, config: TrainingConfig):
        self.config = config
        self._analyzers: Dict[str, BaseAnalyzer] = {}
        self._init_analyzers()

    def _init_analyzers(self):
        """Initialisiert alle Strategy-Analyzer"""
        pullback_config = PullbackScoringConfig()
        self._analyzers['pullback'] = PullbackAnalyzer(pullback_config)

        bounce_config = BounceConfig()
        self._analyzers['bounce'] = BounceAnalyzer(bounce_config)

        breakout_config = ATHBreakoutConfig()
        self._analyzers['ath_breakout'] = ATHBreakoutAnalyzer(breakout_config)

        dip_config = EarningsDipConfig()
        self._analyzers['earnings_dip'] = EarningsDipAnalyzer(dip_config)

    def train(
        self,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        vix_data: Optional[List[Dict]] = None,
    ) -> StrategyTrainingResult:
        """
        Führt Walk-Forward Training für eine Strategie durch.

        Args:
            strategy: Name der Strategie
            historical_data: {symbol: [{date, open, high, low, close, volume}, ...]}
            vix_data: Optional VIX data

        Returns:
            StrategyTrainingResult mit allen Epochen und Metriken
        """
        if strategy not in self._analyzers:
            raise ValueError(f"Unknown strategy: {strategy}. Available: {self.STRATEGIES}")

        # Determine date range
        all_dates = set()
        for sym_data in historical_data.values():
            for bar in sym_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                all_dates.add(d)

        if not all_dates:
            return StrategyTrainingResult(strategy=strategy, epochs=[])

        min_date = min(all_dates)
        max_date = max(all_dates)

        # Generate epochs
        epochs = self._generate_epochs(min_date, max_date)

        if not epochs:
            return StrategyTrainingResult(strategy=strategy, epochs=[])

        results: List[EpochResult] = []

        for i, (train_start, train_end, test_start, test_end) in enumerate(epochs):
            epoch_result = self._run_epoch(
                epoch_id=i + 1,
                strategy=strategy,
                historical_data=historical_data,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
            results.append(epoch_result)

        return StrategyTrainingResult(strategy=strategy, epochs=results)

    def _generate_epochs(
        self,
        min_date: date,
        max_date: date
    ) -> List[Tuple[date, date, date, date]]:
        """Generiert Training/Test-Epochen"""
        epochs = []

        train_days = self.config.train_months * 30
        test_days = self.config.test_months * 30
        step_days = self.config.step_months * 30

        current_train_start = min_date

        while True:
            train_end = current_train_start + timedelta(days=train_days)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=test_days)

            if test_end > max_date:
                break

            epochs.append((current_train_start, train_end, test_start, test_end))
            current_train_start += timedelta(days=step_days)

        return epochs

    def _run_epoch(
        self,
        epoch_id: int,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
    ) -> EpochResult:
        """Führt eine einzelne Epoche durch"""
        analyzer = self._analyzers[strategy]

        # Run on training period
        train_trades = self._run_period(
            analyzer, strategy, historical_data, train_start, train_end
        )

        # Run on test period
        test_trades = self._run_period(
            analyzer, strategy, historical_data, test_start, test_end
        )

        # Calculate metrics
        in_sample_trades = len(train_trades)
        in_sample_winners = sum(1 for t in train_trades if t['pnl'] > 0)
        in_sample_win_rate = (in_sample_winners / in_sample_trades * 100) if in_sample_trades > 0 else 0
        in_sample_pnl = sum(t['pnl'] for t in train_trades)

        out_sample_trades = len(test_trades)
        out_sample_winners = sum(1 for t in test_trades if t['pnl'] > 0)
        out_sample_win_rate = (out_sample_winners / out_sample_trades * 100) if out_sample_trades > 0 else 0
        out_sample_pnl = sum(t['pnl'] for t in test_trades)

        win_rate_degradation = in_sample_win_rate - out_sample_win_rate

        # Check validity
        is_valid = (
            in_sample_trades >= self.config.min_trades_per_epoch and
            out_sample_trades >= 10
        )
        skip_reason = ""
        if in_sample_trades < self.config.min_trades_per_epoch:
            skip_reason = f"Not enough training trades ({in_sample_trades})"
        elif out_sample_trades < 10:
            skip_reason = f"Not enough test trades ({out_sample_trades})"

        return EpochResult(
            epoch_id=epoch_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            in_sample_trades=in_sample_trades,
            in_sample_win_rate=in_sample_win_rate,
            in_sample_pnl=in_sample_pnl,
            out_sample_trades=out_sample_trades,
            out_sample_win_rate=out_sample_win_rate,
            out_sample_pnl=out_sample_pnl,
            win_rate_degradation=win_rate_degradation,
            is_valid=is_valid,
            skip_reason=skip_reason,
        )

    def _run_period(
        self,
        analyzer: BaseAnalyzer,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        start_date: date,
        end_date: date,
    ) -> List[Dict]:
        """Führt Backtest für einen Zeitraum durch"""
        trades = []

        # Collect all trading days in period
        all_dates = set()
        for sym_data in historical_data.values():
            for bar in sym_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if start_date <= d <= end_date:
                    all_dates.add(d)

        trading_days = sorted(all_dates)
        open_positions: Dict[str, Dict] = {}
        symbols = list(historical_data.keys())

        for current_date in trading_days:
            # Check exits
            for symbol in list(open_positions.keys()):
                pos = open_positions[symbol]
                price_data = self._get_price_on_date(historical_data.get(symbol, []), current_date)
                if price_data:
                    pos['last_price'] = price_data['close']

                exit_signal = self._check_exit(pos, current_date)
                if exit_signal:
                    reason, exit_price = exit_signal
                    pnl = self._calculate_pnl(pos, exit_price)
                    trades.append({
                        'symbol': symbol,
                        'entry_date': pos['entry_date'],
                        'exit_date': current_date,
                        'pnl': pnl,
                        'score': pos['score'],
                    })
                    del open_positions[symbol]

            # Check entries
            for symbol in symbols:
                if symbol in open_positions:
                    continue

                symbol_data = historical_data.get(symbol, [])
                history = self._get_history_up_to(symbol_data, current_date, lookback=260)

                if len(history) < 60:
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
                if signal.score < self.config.min_score:
                    continue

                current_price = prices[-1]
                open_positions[symbol] = {
                    'entry_date': current_date,
                    'entry_price': current_price,
                    'score': signal.score,
                    'last_price': current_price,
                    'expiry_date': current_date + timedelta(days=self.config.dte_max),
                }

        # Close remaining positions
        for symbol, pos in open_positions.items():
            pnl = self._calculate_pnl(pos, pos['last_price'])
            trades.append({
                'symbol': symbol,
                'entry_date': pos['entry_date'],
                'exit_date': end_date,
                'pnl': pnl,
                'score': pos['score'],
            })

        return trades

    def _get_history_up_to(
        self,
        symbol_data: List[Dict],
        target_date: date,
        lookback: int = 260
    ) -> List[Dict]:
        """Gets historical bars up to (not including) target_date"""
        bars_before = []
        for bar in symbol_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if d < target_date:
                bars_before.append({**bar, 'date': d})

        bars_before.sort(key=lambda x: x['date'])
        return bars_before[-lookback:] if len(bars_before) > lookback else bars_before

    def _get_price_on_date(self, symbol_data: List[Dict], target_date: date) -> Optional[Dict]:
        """Gets price data for specific date"""
        for bar in symbol_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if d == target_date:
                return bar
        return None

    def _check_exit(self, position: Dict, current_date: date) -> Optional[Tuple[str, float]]:
        """Checks if position should exit"""
        current_price = position['last_price']
        entry_price = position['entry_price']
        expiry = position['expiry_date']
        dte = (expiry - current_date).days

        # Simplified exit logic
        short_strike = entry_price * 0.92  # 8% OTM

        if current_date >= expiry:
            return ('expiration', current_price)

        if dte <= 14 and dte > 0:
            return ('dte_threshold', current_price)

        days_held = (current_date - position['entry_date']).days
        if days_held > 0:
            time_decay_factor = days_held / 60
            price_buffer = (current_price - short_strike) / short_strike * 100 if short_strike > 0 else 0
            estimated_profit = min((time_decay_factor * 50) + (price_buffer * 5), 100)

            if estimated_profit >= 50:
                return ('profit_target', current_price)

        if current_price < short_strike * 0.95:
            return ('stop_loss', current_price)

        return None

    def _calculate_pnl(self, position: Dict, exit_price: float) -> float:
        """Calculates P&L for a position"""
        entry_price = position['entry_price']
        short_strike = entry_price * 0.92
        long_strike = short_strike - (entry_price * 0.05)
        spread_width = short_strike - long_strike
        net_credit = spread_width * 0.20

        if exit_price >= short_strike:
            return net_credit * 100 * 0.95  # Max profit minus commission
        elif exit_price <= long_strike:
            return -(spread_width - net_credit) * 100 * 1.05  # Max loss
        else:
            intrinsic = short_strike - exit_price
            return (net_credit - intrinsic) * 100 - 5


# =============================================================================
# DATA LOADING
# =============================================================================

def load_historical_data(tracker: TradeTracker, symbols: List[str]) -> Dict[str, List[Dict]]:
    """Loads historical data from database"""
    data = {}
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            data[symbol] = [
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
    return data


def load_vix_data(tracker: TradeTracker) -> List[Dict]:
    """Loads VIX data from database"""
    vix_points = tracker.get_vix_data()
    if not vix_points:
        return []
    return [{'date': p.date, 'close': p.value} for p in vix_points]


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def print_epoch_details(result: StrategyTrainingResult, verbose: bool = False):
    """Prints epoch details"""
    if not verbose or not result.epochs:
        return

    print("\n" + "─" * 100)
    print("  EPOCH DETAILS")
    print("─" * 100)

    print(f"{'Epoch':<8} {'Train Period':<24} {'Test Period':<24} {'IS Win%':>10} {'OOS Win%':>10} {'Degrad':>10}")
    print("-" * 100)

    for epoch in result.epochs:
        if not epoch.is_valid:
            print(f"{epoch.epoch_id:<8} SKIPPED: {epoch.skip_reason}")
            continue

        train_period = f"{epoch.train_start} - {epoch.train_end}"
        test_period = f"{epoch.test_start} - {epoch.test_end}"

        degrad_color = "🟢" if epoch.win_rate_degradation < 5 else "🟡" if epoch.win_rate_degradation < 10 else "🔴"

        print(
            f"{epoch.epoch_id:<8} "
            f"{train_period:<24} "
            f"{test_period:<24} "
            f"{epoch.in_sample_win_rate:>9.1f}% "
            f"{epoch.out_sample_win_rate:>9.1f}% "
            f"{degrad_color} {epoch.win_rate_degradation:>+6.1f}%"
        )


def print_strategy_result(result: StrategyTrainingResult):
    """Prints formatted training result for one strategy"""
    print()
    print("═" * 70)
    print(f"  STRATEGY: {result.strategy.upper()}")
    print("═" * 70)
    print()
    print(f"  Total Epochs:         {result.total_epochs}")
    print(f"  Valid Epochs:         {result.valid_epochs}")
    print()
    print(f"  In-Sample Win Rate:   {result.avg_in_sample_win_rate:.1f}%")
    print(f"  Out-Sample Win Rate:  {result.avg_out_sample_win_rate:.1f}%")
    print(f"  Win Rate Degradation: {result.avg_win_rate_degradation:+.1f}%")
    print()
    print(f"  In-Sample P&L:        ${result.avg_in_sample_pnl:+,.0f}")
    print(f"  Out-Sample P&L:       ${result.avg_out_sample_pnl:+,.0f}")
    print()

    severity_emoji = {
        "none": "🟢 NONE",
        "mild": "🟡 MILD",
        "moderate": "🟠 MODERATE",
        "severe": "🔴 SEVERE",
        "unknown": "⚪ UNKNOWN",
    }
    print(f"  Overfitting:          {severity_emoji.get(result.overfit_severity, '⚪')}")
    print("═" * 70)


def print_comparison_table(results: List[StrategyTrainingResult]):
    """Prints comparison table for all strategies"""
    print()
    print("═" * 100)
    print("  TRAINING COMPARISON")
    print("═" * 100)
    print()
    print(f"{'Strategy':<15} {'Epochs':>8} {'IS Win%':>10} {'OOS Win%':>10} {'Degrad':>10} {'IS P&L':>12} {'OOS P&L':>12} {'Overfit':<12}")
    print("─" * 100)

    for r in sorted(results, key=lambda x: x.avg_out_sample_win_rate, reverse=True):
        severity_emoji = {"none": "🟢", "mild": "🟡", "moderate": "🟠", "severe": "🔴", "unknown": "⚪"}
        emoji = severity_emoji.get(r.overfit_severity, "⚪")

        print(
            f"{r.strategy:<15} "
            f"{r.valid_epochs:>8} "
            f"{r.avg_in_sample_win_rate:>9.1f}% "
            f"{r.avg_out_sample_win_rate:>9.1f}% "
            f"{r.avg_win_rate_degradation:>+9.1f}% "
            f"${r.avg_in_sample_pnl:>+10,.0f} "
            f"${r.avg_out_sample_pnl:>+10,.0f} "
            f"{emoji} {r.overfit_severity:<10}"
        )

    print("═" * 100)


def save_results(results: List[StrategyTrainingResult], output_path: Path):
    """Saves training results to JSON"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'strategies': {}
    }

    for r in results:
        data['strategies'][r.strategy] = {
            'total_epochs': r.total_epochs,
            'valid_epochs': r.valid_epochs,
            'avg_in_sample_win_rate': r.avg_in_sample_win_rate,
            'avg_out_sample_win_rate': r.avg_out_sample_win_rate,
            'avg_win_rate_degradation': r.avg_win_rate_degradation,
            'avg_in_sample_pnl': r.avg_in_sample_pnl,
            'avg_out_sample_pnl': r.avg_out_sample_pnl,
            'overfit_severity': r.overfit_severity,
            'epochs': [
                {
                    'epoch_id': e.epoch_id,
                    'train_start': str(e.train_start),
                    'train_end': str(e.train_end),
                    'test_start': str(e.test_start),
                    'test_end': str(e.test_end),
                    'in_sample_trades': e.in_sample_trades,
                    'in_sample_win_rate': e.in_sample_win_rate,
                    'out_sample_trades': e.out_sample_trades,
                    'out_sample_win_rate': e.out_sample_win_rate,
                    'win_rate_degradation': e.win_rate_degradation,
                    'is_valid': e.is_valid,
                }
                for e in r.epochs
            ]
        }

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\nResults saved to: {output_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Strategy-specific walk-forward training',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--strategy', type=str, choices=['pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'all'],
                        default='all', help='Strategy to train (default: all)')
    parser.add_argument('--train-months', type=int, default=12,
                        help='Training period in months (default: 12)')
    parser.add_argument('--test-months', type=int, default=3,
                        help='Test period in months (default: 3)')
    parser.add_argument('--step-months', type=int, default=3,
                        help='Step between epochs in months (default: 3)')
    parser.add_argument('--min-score', type=float, default=5.0,
                        help='Minimum signal score (default: 5.0)')
    parser.add_argument('--quick', action='store_true',
                        help='Quick mode with shorter periods')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output with epoch details')
    parser.add_argument('--output', type=str,
                        help='Save results to JSON file')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
    )

    print("═" * 70)
    print("  OPTIONPLAY STRATEGY-SPECIFIC TRAINING")
    print("═" * 70)

    # Load data
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    if stats['symbols_with_price_data'] == 0:
        print("\n❌ No historical data found!")
        print("   Run first: python scripts/collect_historical_data.py --all")
        sys.exit(1)

    print(f"\n  Database: {stats['symbols_with_price_data']} symbols, {stats['total_price_bars']:,} bars")

    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_info]

    print(f"  Loading historical data for {len(symbols)} symbols...")
    historical_data = load_historical_data(tracker, symbols)
    vix_data = load_vix_data(tracker)

    print(f"  Loaded: {len(historical_data)} symbols with data")

    # Adjust for quick mode
    if args.quick:
        args.train_months = 6
        args.test_months = 2
        args.step_months = 2

    # Configure training
    config = TrainingConfig(
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        min_score=args.min_score,
    )

    print(f"\n  Training Config:")
    print(f"    Train Period: {config.train_months} months")
    print(f"    Test Period:  {config.test_months} months")
    print(f"    Step:         {config.step_months} months")
    print(f"    Min Score:    {config.min_score}")

    # Run training
    trainer = StrategyTrainer(config)
    results: List[StrategyTrainingResult] = []

    strategies = [args.strategy] if args.strategy != 'all' else StrategyTrainer.STRATEGIES

    print("\n" + "═" * 70)
    print("  RUNNING WALK-FORWARD TRAINING...")
    print("═" * 70)

    for strategy in strategies:
        print(f"\n  Training {strategy}...")

        try:
            result = trainer.train(
                strategy=strategy,
                historical_data=historical_data,
                vix_data=vix_data,
            )
            results.append(result)

            severity_emoji = {"none": "🟢", "mild": "🟡", "moderate": "🟠", "severe": "🔴", "unknown": "⚪"}
            emoji = severity_emoji.get(result.overfit_severity, "⚪")

            print(
                f"    ✓ {result.valid_epochs} epochs | "
                f"IS: {result.avg_in_sample_win_rate:.1f}% | "
                f"OOS: {result.avg_out_sample_win_rate:.1f}% | "
                f"Overfit: {emoji} {result.overfit_severity}"
            )
        except Exception as e:
            print(f"    ✗ Error: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Print results
    for result in results:
        if args.verbose:
            print_strategy_result(result)
            print_epoch_details(result, args.verbose)

    if len(results) > 1:
        print_comparison_table(results)
    elif results:
        print_strategy_result(results[0])

    # Save if requested
    if args.output:
        save_results(results, Path(args.output))
    else:
        # Default save location
        output_dir = Path.home() / '.optionplay' / 'models'
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f'training_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        save_results(results, output_path)

    # Summary
    print("\n" + "═" * 70)
    if results:
        best = min(results, key=lambda x: x.avg_win_rate_degradation if x.valid_epochs > 0 else 100)
        severity_emoji = {"none": "🟢", "mild": "🟡", "moderate": "🟠", "severe": "🔴", "unknown": "⚪"}
        print(f"  Most Stable Strategy: {best.strategy.upper()}")
        print(f"  OOS Win Rate: {best.avg_out_sample_win_rate:.1f}% | Degradation: {best.avg_win_rate_degradation:+.1f}% | Overfit: {severity_emoji.get(best.overfit_severity, '⚪')} {best.overfit_severity}")
    print("═" * 70)


if __name__ == '__main__':
    main()
