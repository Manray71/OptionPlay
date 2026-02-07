#!/usr/bin/env python3
"""
OptionPlay - Full Strategy Backtesting & Training System
=========================================================

Vollständiges Backtesting-System für alle Strategien mit:
- Echte Analyzer-Signale (keine simulierten Scores)
- VIX-Regime-Analyse für jede Periode
- Walk-Forward Training mit Out-of-Sample Validation
- Komponenten-Gewichts-Optimierung pro Strategie
- Per-Regime Performance-Analyse

Strategien:
- pullback: Mean-Reversion bei Rücksetzern in Aufwärtstrend
- bounce: Support-Bounce-Strategie
- ath_breakout: Momentum bei Allzeithochs
- earnings_dip: Konträre Strategie nach Earnings-Überreaktion

Usage:
    # Vollständiges Backtesting aller Strategien
    python scripts/full_strategy_backtest.py

    # Einzelne Strategie mit Training
    python scripts/full_strategy_backtest.py --strategy pullback --train

    # Mit VIX-Regime-Analyse
    python scripts/full_strategy_backtest.py --regime-analysis

    # Schneller Test-Modus
    python scripts/full_strategy_backtest.py --quick

    # Export der trainierten Modelle
    python scripts/full_strategy_backtest.py --train --export
"""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any, NamedTuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import statistics
import logging
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.backtesting import TradeTracker, TradeOutcome, ExitReason
from src.config.models import PullbackScoringConfig
from src.analyzers.pullback import PullbackAnalyzer
from src.analyzers.bounce import BounceAnalyzer, BounceConfig
from src.analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from src.analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
from src.analyzers.base import BaseAnalyzer
from src.models.base import TradeSignal, SignalType

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================

class VIXRegime(Enum):
    """VIX-Regime Klassifikation"""
    LOW = "low"           # VIX < 15
    NORMAL = "normal"     # 15 <= VIX < 20
    ELEVATED = "elevated" # 20 <= VIX < 30
    HIGH = "high"         # VIX >= 30

    @classmethod
    def from_vix(cls, vix: float) -> "VIXRegime":
        if vix < 15:
            return cls.LOW
        elif vix < 20:
            return cls.NORMAL
        elif vix < 30:
            return cls.ELEVATED
        else:
            return cls.HIGH


STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class BacktestConfig:
    """
    Konfiguration für vollständiges Backtesting.

    Basisstrategie (gemäß strategies.yaml):
    - Short Put: Delta -0.20 (Range: -0.25 bis -0.15)
    - Long Put: Delta -0.05 (Range: -0.08 bis -0.03)
    - DTE: 60-90 Tage
    - Earnings-Buffer: 60 Tage
    """
    # Kapital
    initial_capital: float = 100000.0
    max_position_pct: float = 5.0
    max_total_risk_pct: float = 25.0

    # Entry-Kriterien
    min_score: float = 5.0
    min_otm_pct: float = 8.0  # Fallback wenn kein Delta verwendet

    # DTE-Parameter (Basisstrategie: 60-90 Tage)
    dte_min: int = 60
    dte_max: int = 90

    # Delta-basierte Strike-Auswahl (Basisstrategie)
    use_delta_based_strikes: bool = True
    short_delta_target: float = -0.20
    short_delta_min: float = -0.25
    short_delta_max: float = -0.15
    long_delta_target: float = -0.05
    long_delta_min: float = -0.08
    long_delta_max: float = -0.03

    # Exit-Kriterien
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 100.0
    dte_exit_threshold: int = 14

    # Spread-Parameter (Fallback)
    spread_width_pct: float = 5.0
    min_credit_pct: float = 20.0

    # Simulation
    slippage_pct: float = 1.0
    commission_per_contract: float = 1.30

    # Training
    train_months: int = 12
    test_months: int = 3
    step_months: int = 3
    min_trades_per_epoch: int = 20


@dataclass
class TradeRecord:
    """Vollständiger Trade-Record mit allen Details"""
    symbol: str
    strategy: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    signal_score: float
    realized_pnl: float
    outcome: TradeOutcome
    exit_reason: ExitReason
    hold_days: int
    vix_at_entry: Optional[float] = None
    regime_at_entry: Optional[VIXRegime] = None
    score_breakdown: Optional[Dict[str, float]] = None

    # Position Details
    short_strike: float = 0.0
    long_strike: float = 0.0
    spread_width: float = 0.0
    contracts: int = 1
    max_profit: float = 0.0
    max_loss: float = 0.0


@dataclass
class RegimePerformance:
    """Performance-Metriken für ein VIX-Regime"""
    regime: VIXRegime
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    profit_factor: float = 0.0
    avg_score: float = 0.0
    avg_hold_days: float = 0.0


@dataclass
class ComponentPerformance:
    """Performance einer Score-Komponente"""
    component: str
    correlation_with_win: float = 0.0
    avg_when_win: float = 0.0
    avg_when_loss: float = 0.0
    weight_suggestion: float = 1.0


@dataclass
class EpochResult:
    """Ergebnis einer Walk-Forward Epoche"""
    epoch_id: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    # In-Sample Metriken
    is_trades: int = 0
    is_win_rate: float = 0.0
    is_pnl: float = 0.0
    is_sharpe: float = 0.0

    # Out-of-Sample Metriken
    oos_trades: int = 0
    oos_win_rate: float = 0.0
    oos_pnl: float = 0.0
    oos_sharpe: float = 0.0

    # Degradation
    win_rate_degradation: float = 0.0
    is_valid: bool = True
    skip_reason: str = ""

    # Optimierte Parameter
    optimal_min_score: float = 5.0
    regime_adjustments: Dict[str, float] = field(default_factory=dict)


@dataclass
class StrategyResult:
    """Vollständiges Ergebnis für eine Strategie"""
    strategy: str
    trades: List[TradeRecord]
    config: BacktestConfig

    # Aggregate Metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    avg_hold_days: float = 0.0

    # Per-Regime Performance
    regime_performance: Dict[str, RegimePerformance] = field(default_factory=dict)

    # Component Analysis
    component_analysis: Dict[str, ComponentPerformance] = field(default_factory=dict)

    # Walk-Forward Results
    epochs: List[EpochResult] = field(default_factory=list)
    overfit_severity: str = "unknown"

    # Optimized Parameters
    optimal_params: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.trades:
            self._calculate_all_metrics()

    def _calculate_all_metrics(self):
        """Berechnet alle Metriken"""
        self._calculate_base_metrics()
        self._calculate_regime_metrics()
        self._calculate_component_metrics()

    def _calculate_base_metrics(self):
        """Berechnet Basis-Metriken"""
        self.total_trades = len(self.trades)
        winners = [t for t in self.trades if t.realized_pnl > 0]
        losers = [t for t in self.trades if t.realized_pnl < 0]

        self.winning_trades = len(winners)
        self.losing_trades = len(losers)

        total_profit = sum(t.realized_pnl for t in winners)
        total_loss = abs(sum(t.realized_pnl for t in losers))
        self.total_pnl = total_profit - total_loss

        if self.total_trades > 0:
            self.win_rate = (self.winning_trades / self.total_trades) * 100
            self.avg_hold_days = statistics.mean(t.hold_days for t in self.trades)

        if winners:
            self.avg_win = total_profit / len(winners)
        if losers:
            self.avg_loss = total_loss / len(losers)

        if total_loss > 0:
            self.profit_factor = total_profit / total_loss

        # Equity Curve und Drawdown
        equity = [self.config.initial_capital]
        for t in sorted(self.trades, key=lambda x: x.exit_date):
            equity.append(equity[-1] + t.realized_pnl)

        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = peak - e
            if dd > max_dd:
                max_dd = dd
        self.max_drawdown = max_dd

        # Sharpe Ratio
        if len(self.trades) >= 2:
            returns = [t.realized_pnl / self.config.initial_capital for t in self.trades]
            avg_ret = statistics.mean(returns)
            std_ret = statistics.stdev(returns) if len(returns) > 1 else 0
            if std_ret > 0:
                self.sharpe_ratio = (avg_ret * 12) / (std_ret * (12 ** 0.5))

    def _calculate_regime_metrics(self):
        """Berechnet Performance pro VIX-Regime"""
        regime_trades: Dict[VIXRegime, List[TradeRecord]] = defaultdict(list)

        for trade in self.trades:
            if trade.regime_at_entry:
                regime_trades[trade.regime_at_entry].append(trade)

        for regime, trades in regime_trades.items():
            winners = [t for t in trades if t.realized_pnl > 0]
            losers = [t for t in trades if t.realized_pnl < 0]

            total_profit = sum(t.realized_pnl for t in winners)
            total_loss = abs(sum(t.realized_pnl for t in losers))

            perf = RegimePerformance(
                regime=regime,
                trades=len(trades),
                wins=len(winners),
                losses=len(losers),
                total_pnl=total_profit - total_loss,
            )

            if trades:
                perf.win_rate = (len(winners) / len(trades)) * 100
                perf.avg_pnl = perf.total_pnl / len(trades)
                perf.avg_score = statistics.mean(t.signal_score for t in trades)
                perf.avg_hold_days = statistics.mean(t.hold_days for t in trades)

            if total_loss > 0:
                perf.profit_factor = total_profit / total_loss

            self.regime_performance[regime.value] = perf

    def _calculate_component_metrics(self):
        """Analysiert Score-Komponenten für Gewichts-Optimierung"""
        # Sammle alle Breakdowns
        trades_with_breakdown = [t for t in self.trades if t.score_breakdown]

        if not trades_with_breakdown:
            return

        # Identifiziere alle Komponenten (nur numerische Werte)
        all_components = set()
        for trade in trades_with_breakdown:
            for k, v in trade.score_breakdown.items():
                if isinstance(v, (int, float)):
                    all_components.add(k)

        for component in all_components:
            # Filter to trades where this component exists and is numeric
            winners = [t for t in trades_with_breakdown
                      if t.realized_pnl > 0
                      and component in t.score_breakdown
                      and isinstance(t.score_breakdown[component], (int, float))]
            losers = [t for t in trades_with_breakdown
                     if t.realized_pnl < 0
                     and component in t.score_breakdown
                     and isinstance(t.score_breakdown[component], (int, float))]

            comp_perf = ComponentPerformance(component=component)

            if winners:
                comp_perf.avg_when_win = statistics.mean(
                    t.score_breakdown[component] for t in winners
                )

            if losers:
                comp_perf.avg_when_loss = statistics.mean(
                    t.score_breakdown[component] for t in losers
                )

            # Korrelation mit Win (vereinfacht)
            if winners and losers:
                # Höhere Werte bei Gewinnern = positive Korrelation
                diff = comp_perf.avg_when_win - comp_perf.avg_when_loss
                comp_perf.correlation_with_win = diff

                # Weight Suggestion: Erhöhe Gewicht wenn Komponente Gewinne vorhersagt
                if diff > 0.5:
                    comp_perf.weight_suggestion = 1.2
                elif diff > 0:
                    comp_perf.weight_suggestion = 1.1
                elif diff < -0.5:
                    comp_perf.weight_suggestion = 0.8
                elif diff < 0:
                    comp_perf.weight_suggestion = 0.9

            self.component_analysis[component] = comp_perf


# =============================================================================
# STRATEGY BACKTESTER
# =============================================================================

class FullStrategyBacktester:
    """
    Vollständiger Strategy-Backtester mit VIX-Regime-Analyse
    und Walk-Forward Training
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self._analyzers: Dict[str, BaseAnalyzer] = {}
        self._vix_data: Dict[date, float] = {}
        self._init_analyzers()

    def _init_analyzers(self):
        """Initialisiert alle Strategy-Analyzer"""
        # Pullback
        pullback_config = PullbackScoringConfig()
        self._analyzers['pullback'] = PullbackAnalyzer(pullback_config)

        # Bounce
        bounce_config = BounceConfig()
        self._analyzers['bounce'] = BounceAnalyzer(bounce_config)

        # ATH Breakout
        breakout_config = ATHBreakoutConfig()
        self._analyzers['ath_breakout'] = ATHBreakoutAnalyzer(breakout_config)

        # Earnings Dip
        dip_config = EarningsDipConfig()
        self._analyzers['earnings_dip'] = EarningsDipAnalyzer(dip_config)

    def set_vix_data(self, vix_data: List[Dict]):
        """Setzt VIX-Daten für Regime-Analyse"""
        for point in vix_data:
            d = point['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            self._vix_data[d] = point.get('close') or point.get('value', 18.0)

    def get_vix_at_date(self, target_date: date) -> Optional[float]:
        """Holt VIX für ein Datum (mit Fallback auf vorherigen Tag)"""
        if target_date in self._vix_data:
            return self._vix_data[target_date]

        # Suche vorherigen verfügbaren Tag
        for i in range(1, 8):
            prev_date = target_date - timedelta(days=i)
            if prev_date in self._vix_data:
                return self._vix_data[prev_date]

        return None

    def run_backtest(
        self,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_score_override: Optional[float] = None,
    ) -> StrategyResult:
        """
        Führt vollständiges Backtesting für eine Strategie durch.

        Args:
            strategy: Name der Strategie
            historical_data: {symbol: [{date, open, high, low, close, volume}, ...]}
            start_date: Optional Start-Datum
            end_date: Optional End-Datum
            min_score_override: Optional Score-Override für Optimierung

        Returns:
            StrategyResult mit allen Metriken
        """
        if strategy not in self._analyzers:
            raise ValueError(f"Unknown strategy: {strategy}. Available: {STRATEGIES}")

        analyzer = self._analyzers[strategy]
        trades: List[TradeRecord] = []

        min_score = min_score_override if min_score_override is not None else self.config.min_score

        # Determine date range
        all_dates = set()
        for sym_data in historical_data.values():
            for bar in sym_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                all_dates.add(d)

        if not all_dates:
            return StrategyResult(strategy=strategy, trades=[], config=self.config)

        min_date = start_date or min(all_dates)
        max_date = end_date or max(all_dates)

        trading_days = sorted([d for d in all_dates if min_date <= d <= max_date])

        # Track positions
        open_positions: Dict[str, Dict] = {}
        current_risk = 0.0

        symbols = list(historical_data.keys())

        for current_date in trading_days:
            # Check exits
            positions_to_close = []
            for symbol, pos in list(open_positions.items()):
                exit_signal = self._check_exit(
                    pos, current_date, historical_data.get(symbol, [])
                )
                if exit_signal:
                    positions_to_close.append((symbol, pos, exit_signal))

            # Close positions
            for symbol, pos, (reason, exit_price) in positions_to_close:
                trade = self._close_position(pos, current_date, reason, exit_price, strategy)
                trades.append(trade)
                current_risk -= pos.get('max_loss', 0)
                del open_positions[symbol]

            # Check entries
            for symbol in symbols:
                if symbol in open_positions:
                    continue

                if current_risk >= self.config.initial_capital * (self.config.max_total_risk_pct / 100):
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
                except Exception as e:
                    logger.debug(f"Error analyzing {symbol}: {e}")
                    continue

                if signal.signal_type != SignalType.LONG:
                    continue
                if signal.score < min_score:
                    continue

                # Get VIX and regime
                vix = self.get_vix_at_date(current_date)
                regime = VIXRegime.from_vix(vix) if vix else None

                # Extract score breakdown
                score_breakdown = None
                if signal.details and 'score_breakdown' in signal.details:
                    score_breakdown = signal.details['score_breakdown']
                elif hasattr(signal, 'details') and signal.details:
                    # Try to extract from breakdown field
                    if 'breakdown' in signal.details:
                        bd = signal.details['breakdown']
                        if hasattr(bd, '__dict__'):
                            score_breakdown = {k: v for k, v in bd.__dict__.items()
                                             if isinstance(v, (int, float))}

                # Open position
                current_price = prices[-1]
                max_position_risk = self.config.initial_capital * (self.config.max_position_pct / 100)
                available_risk = (self.config.initial_capital * (self.config.max_total_risk_pct / 100)) - current_risk

                position = self._open_position(
                    symbol=symbol,
                    entry_date=current_date,
                    current_price=current_price,
                    score=signal.score,
                    max_risk=min(max_position_risk, available_risk),
                    vix=vix,
                    regime=regime,
                    score_breakdown=score_breakdown
                )

                if position:
                    open_positions[symbol] = position
                    current_risk += position.get('max_loss', 0)

        # Close remaining positions
        for symbol, pos in open_positions.items():
            symbol_data = historical_data.get(symbol, [])
            last_price = pos['entry_price']
            for bar in symbol_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if d == max_date:
                    last_price = bar['close']
                    break

            trade = self._close_position(
                pos, max_date, ExitReason.MANUAL, last_price, strategy
            )
            trades.append(trade)

        return StrategyResult(strategy=strategy, trades=trades, config=self.config)

    def run_walk_forward(
        self,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        optimize_score: bool = True,
    ) -> StrategyResult:
        """
        Führt Walk-Forward Training für eine Strategie durch.

        Teilt die Daten in Train/Test-Epochen und optimiert Parameter.
        """
        # Bestimme Datumsbereich
        all_dates = set()
        for sym_data in historical_data.values():
            for bar in sym_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                all_dates.add(d)

        if not all_dates:
            return StrategyResult(strategy=strategy, trades=[], config=self.config)

        min_date = min(all_dates)
        max_date = max(all_dates)

        # Generiere Epochen
        epochs_config = self._generate_epochs(min_date, max_date)

        all_trades: List[TradeRecord] = []
        epoch_results: List[EpochResult] = []

        for i, (train_start, train_end, test_start, test_end) in enumerate(epochs_config):
            logger.info(f"  Epoch {i+1}: Train {train_start} - {train_end}, Test {test_start} - {test_end}")

            # Training Phase
            optimal_score = self.config.min_score

            if optimize_score:
                # Grid-Search für optimalen Score
                best_score_threshold = self.config.min_score
                best_sharpe = -999

                for score_threshold in [4.0, 5.0, 6.0, 7.0, 8.0]:
                    train_result = self.run_backtest(
                        strategy=strategy,
                        historical_data=historical_data,
                        start_date=train_start,
                        end_date=train_end,
                        min_score_override=score_threshold
                    )

                    if train_result.total_trades >= self.config.min_trades_per_epoch:
                        if train_result.sharpe_ratio > best_sharpe:
                            best_sharpe = train_result.sharpe_ratio
                            best_score_threshold = score_threshold

                optimal_score = best_score_threshold

            # Test Phase mit optimierten Parametern
            train_result = self.run_backtest(
                strategy=strategy,
                historical_data=historical_data,
                start_date=train_start,
                end_date=train_end,
                min_score_override=optimal_score
            )

            test_result = self.run_backtest(
                strategy=strategy,
                historical_data=historical_data,
                start_date=test_start,
                end_date=test_end,
                min_score_override=optimal_score
            )

            # Epoch Result erstellen
            epoch = EpochResult(
                epoch_id=i + 1,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                is_trades=train_result.total_trades,
                is_win_rate=train_result.win_rate,
                is_pnl=train_result.total_pnl,
                is_sharpe=train_result.sharpe_ratio,
                oos_trades=test_result.total_trades,
                oos_win_rate=test_result.win_rate,
                oos_pnl=test_result.total_pnl,
                oos_sharpe=test_result.sharpe_ratio,
                optimal_min_score=optimal_score,
            )

            # Validierung
            if train_result.total_trades < self.config.min_trades_per_epoch:
                epoch.is_valid = False
                epoch.skip_reason = f"Not enough training trades ({train_result.total_trades})"
            elif test_result.total_trades < 5:
                epoch.is_valid = False
                epoch.skip_reason = f"Not enough test trades ({test_result.total_trades})"
            else:
                epoch.win_rate_degradation = train_result.win_rate - test_result.win_rate

            epoch_results.append(epoch)

            # Sammle OOS Trades für finale Metriken
            all_trades.extend(test_result.trades)

        # Erstelle Gesamtergebnis
        result = StrategyResult(
            strategy=strategy,
            trades=all_trades,
            config=self.config,
            epochs=epoch_results
        )

        # Berechne Overfit Severity
        valid_epochs = [e for e in epoch_results if e.is_valid]
        if valid_epochs:
            avg_degradation = statistics.mean(e.win_rate_degradation for e in valid_epochs)
            if avg_degradation < 5:
                result.overfit_severity = "none"
            elif avg_degradation < 10:
                result.overfit_severity = "mild"
            elif avg_degradation < 15:
                result.overfit_severity = "moderate"
            else:
                result.overfit_severity = "severe"

            # Optimale Parameter aus bester Epoche
            best_epoch = max(valid_epochs, key=lambda e: e.oos_sharpe)
            result.optimal_params = {
                'min_score': best_epoch.optimal_min_score,
                'regime_adjustments': best_epoch.regime_adjustments,
            }

        return result

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

    def _open_position(
        self,
        symbol: str,
        entry_date: date,
        current_price: float,
        score: float,
        max_risk: float,
        vix: Optional[float] = None,
        regime: Optional[VIXRegime] = None,
        score_breakdown: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Opens a new position"""
        otm_pct = self.config.min_otm_pct / 100
        short_strike = round(current_price * (1 - otm_pct), 0)

        spread_width_pct = self.config.spread_width_pct / 100
        spread_width = max(5.0, round(current_price * spread_width_pct / 5) * 5)
        long_strike = short_strike - spread_width

        credit_pct = self.config.min_credit_pct / 100
        net_credit = spread_width * credit_pct
        net_credit *= (1 - self.config.slippage_pct / 100)

        max_loss_per_contract = (spread_width - net_credit) * 100
        contracts = max(1, int(max_risk / max_loss_per_contract))

        total_max_profit = net_credit * 100 * contracts
        total_max_loss = max_loss_per_contract * contracts
        commission = self.config.commission_per_contract * contracts * 2

        return {
            'symbol': symbol,
            'entry_date': entry_date,
            'entry_price': current_price,
            'short_strike': short_strike,
            'long_strike': long_strike,
            'spread_width': spread_width,
            'net_credit': net_credit,
            'contracts': contracts,
            'max_profit': total_max_profit - commission,
            'max_loss': total_max_loss + commission,
            'score': score,
            'score_breakdown': score_breakdown,
            'vix': vix,
            'regime': regime,
            'dte_at_entry': self.config.dte_max,
            'expiry_date': entry_date + timedelta(days=self.config.dte_max),
        }

    def _check_exit(
        self,
        position: Dict,
        current_date: date,
        symbol_data: List[Dict]
    ) -> Optional[Tuple[ExitReason, float]]:
        """Checks if position should exit"""
        price_data = self._get_price_on_date(symbol_data, current_date)
        current_price = price_data['close'] if price_data else position['entry_price']

        short_strike = position['short_strike']
        net_credit = position['net_credit']
        expiry = position['expiry_date']
        dte = (expiry - current_date).days

        # Expiration
        if current_date >= expiry:
            return (ExitReason.EXPIRATION, current_price)

        # Short strike breached
        if current_price < short_strike:
            spread_value = short_strike - current_price
            if spread_value >= position['spread_width'] * 0.8:
                return (ExitReason.BREACH_SHORT_STRIKE, current_price)

        # Profit target
        days_held = (current_date - position['entry_date']).days
        if days_held > 0 and dte > 0:
            time_decay_factor = days_held / position['dte_at_entry']
            price_buffer_pct = ((current_price - short_strike) / short_strike) * 100 if short_strike > 0 else 0
            estimated_profit_pct = min((time_decay_factor * 50) + (price_buffer_pct * 5), 100)

            if estimated_profit_pct >= self.config.profit_target_pct:
                return (ExitReason.PROFIT_TARGET_HIT, current_price)

        # DTE threshold
        if dte <= self.config.dte_exit_threshold and dte > 0:
            return (ExitReason.DTE_THRESHOLD, current_price)

        # Stop loss
        if current_price < short_strike:
            loss_pct = ((short_strike - current_price) / net_credit) * 100 if net_credit > 0 else 0
            if loss_pct >= self.config.stop_loss_pct:
                return (ExitReason.STOP_LOSS_HIT, current_price)

        return None

    def _close_position(
        self,
        position: Dict,
        exit_date: date,
        exit_reason: ExitReason,
        exit_price: float,
        strategy: str
    ) -> TradeRecord:
        """Closes position and calculates P&L"""
        short_strike = position['short_strike']
        long_strike = position['long_strike']
        net_credit = position['net_credit']
        contracts = position['contracts']

        if exit_price >= short_strike:
            realized_pnl = position['max_profit']
            outcome = TradeOutcome.MAX_PROFIT
        elif exit_price <= long_strike:
            realized_pnl = -position['max_loss']
            outcome = TradeOutcome.MAX_LOSS
        else:
            intrinsic_value = short_strike - exit_price
            spread_cost = intrinsic_value * 100 * contracts
            commission = self.config.commission_per_contract * contracts * 2
            realized_pnl = (net_credit * 100 * contracts) - spread_cost - commission

            if realized_pnl > 0:
                outcome = TradeOutcome.PROFIT_TARGET if exit_reason == ExitReason.PROFIT_TARGET_HIT else TradeOutcome.PARTIAL_PROFIT
            elif realized_pnl < 0:
                outcome = TradeOutcome.STOP_LOSS if exit_reason == ExitReason.STOP_LOSS_HIT else TradeOutcome.PARTIAL_LOSS
            else:
                outcome = TradeOutcome.PARTIAL_PROFIT

        hold_days = (exit_date - position['entry_date']).days

        return TradeRecord(
            symbol=position['symbol'],
            strategy=strategy,
            entry_date=position['entry_date'],
            exit_date=exit_date,
            entry_price=position['entry_price'],
            exit_price=exit_price,
            signal_score=position['score'],
            realized_pnl=realized_pnl,
            outcome=outcome,
            exit_reason=exit_reason,
            hold_days=max(1, hold_days),
            vix_at_entry=position.get('vix'),
            regime_at_entry=position.get('regime'),
            score_breakdown=position.get('score_breakdown'),
            short_strike=short_strike,
            long_strike=long_strike,
            spread_width=position['spread_width'],
            contracts=contracts,
            max_profit=position['max_profit'],
            max_loss=position['max_loss'],
        )


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
    return [{'date': p.date, 'value': p.value} for p in vix_points]


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def print_header(title: str, width: int = 80):
    """Prints a formatted header"""
    print()
    print("═" * width)
    print(f"  {title}")
    print("═" * width)


def print_strategy_result(result: StrategyResult, verbose: bool = False):
    """Prints formatted strategy result"""
    print_header(f"STRATEGY: {result.strategy.upper()}")

    print(f"\n  {'Metric':<25} {'Value':>15}")
    print("  " + "─" * 42)
    print(f"  {'Total Trades':<25} {result.total_trades:>15}")
    print(f"  {'Winning Trades':<25} {result.winning_trades:>15} ({result.win_rate:.1f}%)")
    print(f"  {'Losing Trades':<25} {result.losing_trades:>15}")
    print(f"  {'Avg Hold Days':<25} {result.avg_hold_days:>15.1f}")
    print()
    print(f"  {'Total P&L':<25} ${result.total_pnl:>+14,.2f}")
    print(f"  {'Avg Win':<25} ${result.avg_win:>14,.2f}")
    print(f"  {'Avg Loss':<25} ${result.avg_loss:>14,.2f}")
    print(f"  {'Profit Factor':<25} {result.profit_factor:>15.2f}")
    print()
    print(f"  {'Max Drawdown':<25} ${result.max_drawdown:>14,.2f}")
    print(f"  {'Sharpe Ratio':<25} {result.sharpe_ratio:>15.2f}")

    # Regime Performance
    if result.regime_performance:
        print("\n  " + "─" * 50)
        print("  VIX REGIME PERFORMANCE")
        print("  " + "─" * 50)
        print(f"  {'Regime':<12} {'Trades':>8} {'Win%':>8} {'P&L':>12} {'PF':>8}")
        print("  " + "-" * 50)

        for regime_name, perf in sorted(result.regime_performance.items()):
            emoji = "🟢" if perf.win_rate >= 60 else "🟡" if perf.win_rate >= 50 else "🔴"
            print(
                f"  {regime_name:<12} "
                f"{perf.trades:>8} "
                f"{emoji} {perf.win_rate:>5.1f}% "
                f"${perf.total_pnl:>+10,.0f} "
                f"{perf.profit_factor:>8.2f}"
            )

    # Component Analysis
    if verbose and result.component_analysis:
        print("\n  " + "─" * 60)
        print("  COMPONENT ANALYSIS")
        print("  " + "─" * 60)
        print(f"  {'Component':<20} {'Win Avg':>10} {'Loss Avg':>10} {'Diff':>10} {'Weight':>10}")
        print("  " + "-" * 60)

        for comp_name, comp in sorted(
            result.component_analysis.items(),
            key=lambda x: x[1].correlation_with_win,
            reverse=True
        ):
            diff_emoji = "+" if comp.correlation_with_win > 0 else "-"
            print(
                f"  {comp_name:<20} "
                f"{comp.avg_when_win:>10.2f} "
                f"{comp.avg_when_loss:>10.2f} "
                f"{diff_emoji}{abs(comp.correlation_with_win):>9.2f} "
                f"x{comp.weight_suggestion:>8.2f}"
            )

    # Walk-Forward Results
    if result.epochs:
        print("\n  " + "─" * 70)
        print("  WALK-FORWARD TRAINING RESULTS")
        print("  " + "─" * 70)

        valid_epochs = [e for e in result.epochs if e.is_valid]
        if valid_epochs:
            avg_is_wr = statistics.mean(e.is_win_rate for e in valid_epochs)
            avg_oos_wr = statistics.mean(e.oos_win_rate for e in valid_epochs)
            avg_degradation = statistics.mean(e.win_rate_degradation for e in valid_epochs)

            print(f"  Valid Epochs:           {len(valid_epochs)}/{len(result.epochs)}")
            print(f"  Avg In-Sample Win%:     {avg_is_wr:.1f}%")
            print(f"  Avg Out-of-Sample Win%: {avg_oos_wr:.1f}%")
            print(f"  Avg Degradation:        {avg_degradation:+.1f}%")

            severity_emoji = {
                "none": "🟢 NONE",
                "mild": "🟡 MILD",
                "moderate": "🟠 MODERATE",
                "severe": "🔴 SEVERE",
            }
            print(f"  Overfit Severity:       {severity_emoji.get(result.overfit_severity, '⚪')}")

            if result.optimal_params:
                print(f"\n  Optimal Parameters:")
                print(f"    Min Score: {result.optimal_params.get('min_score', 5.0):.1f}")


def print_comparison_table(results: List[StrategyResult]):
    """Prints comparison table for all strategies"""
    print_header("STRATEGY COMPARISON")

    print(f"\n  {'Strategy':<15} {'Trades':>8} {'Win%':>8} {'P&L':>12} {'PF':>8} {'Sharpe':>8} {'MaxDD':>12}")
    print("  " + "─" * 75)

    for r in sorted(results, key=lambda x: x.total_pnl, reverse=True):
        win_indicator = "🟢" if r.win_rate >= 60 else "🟡" if r.win_rate >= 50 else "🔴"
        pnl_indicator = "🟢" if r.total_pnl > 0 else "🔴"

        print(
            f"  {r.strategy:<15} "
            f"{r.total_trades:>8} "
            f"{win_indicator} {r.win_rate:>5.1f}% "
            f"{pnl_indicator} ${r.total_pnl:>+9,.0f} "
            f"{r.profit_factor:>8.2f} "
            f"{r.sharpe_ratio:>8.2f} "
            f"${r.max_drawdown:>10,.0f}"
        )

    print("  " + "═" * 75)


def print_regime_comparison(results: List[StrategyResult]):
    """Prints regime-based comparison across strategies"""
    print_header("VIX REGIME COMPARISON")

    all_regimes = set()
    for r in results:
        all_regimes.update(r.regime_performance.keys())

    for regime in sorted(all_regimes):
        print(f"\n  Regime: {regime.upper()}")
        print(f"  {'Strategy':<15} {'Trades':>8} {'Win%':>8} {'P&L':>12} {'PF':>8}")
        print("  " + "-" * 55)

        for r in sorted(results, key=lambda x: x.regime_performance.get(regime, RegimePerformance(VIXRegime.NORMAL)).total_pnl, reverse=True):
            perf = r.regime_performance.get(regime)
            if perf:
                win_ind = "🟢" if perf.win_rate >= 60 else "🟡" if perf.win_rate >= 50 else "🔴"
                print(
                    f"  {r.strategy:<15} "
                    f"{perf.trades:>8} "
                    f"{win_ind} {perf.win_rate:>5.1f}% "
                    f"${perf.total_pnl:>+10,.0f} "
                    f"{perf.profit_factor:>8.2f}"
                )


def save_results(results: List[StrategyResult], output_path: Path):
    """Saves results to JSON"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'strategies': {}
    }

    for r in results:
        strategy_data = {
            'total_trades': r.total_trades,
            'winning_trades': r.winning_trades,
            'losing_trades': r.losing_trades,
            'total_pnl': r.total_pnl,
            'win_rate': r.win_rate,
            'profit_factor': r.profit_factor,
            'max_drawdown': r.max_drawdown,
            'sharpe_ratio': r.sharpe_ratio,
            'avg_hold_days': r.avg_hold_days,
            'overfit_severity': r.overfit_severity,
            'optimal_params': r.optimal_params,
            'regime_performance': {
                k: {
                    'trades': v.trades,
                    'wins': v.wins,
                    'losses': v.losses,
                    'win_rate': v.win_rate,
                    'total_pnl': v.total_pnl,
                    'profit_factor': v.profit_factor,
                }
                for k, v in r.regime_performance.items()
            },
            'component_analysis': {
                k: {
                    'correlation_with_win': v.correlation_with_win,
                    'avg_when_win': v.avg_when_win,
                    'avg_when_loss': v.avg_when_loss,
                    'weight_suggestion': v.weight_suggestion,
                }
                for k, v in r.component_analysis.items()
            },
            'trades': [
                {
                    'symbol': t.symbol,
                    'entry_date': str(t.entry_date),
                    'exit_date': str(t.exit_date),
                    'realized_pnl': t.realized_pnl,
                    'outcome': t.outcome.value,
                    'signal_score': t.signal_score,
                    'regime': t.regime_at_entry.value if t.regime_at_entry else None,
                }
                for t in r.trades
            ]
        }

        if r.epochs:
            strategy_data['walk_forward'] = {
                'total_epochs': len(r.epochs),
                'valid_epochs': len([e for e in r.epochs if e.is_valid]),
                'epochs': [
                    {
                        'epoch_id': e.epoch_id,
                        'train_period': f"{e.train_start} - {e.train_end}",
                        'test_period': f"{e.test_start} - {e.test_end}",
                        'is_win_rate': e.is_win_rate,
                        'oos_win_rate': e.oos_win_rate,
                        'win_rate_degradation': e.win_rate_degradation,
                        'optimal_min_score': e.optimal_min_score,
                        'is_valid': e.is_valid,
                    }
                    for e in r.epochs
                ]
            }

        data['strategies'][r.strategy] = strategy_data

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\n  Results saved to: {output_path}")


def export_trained_models(results: List[StrategyResult], output_dir: Path):
    """Exports trained models for production use"""
    output_dir.mkdir(parents=True, exist_ok=True)

    model_data = {
        'version': '1.0.0',
        'created_at': datetime.now().isoformat(),
        'strategies': {}
    }

    for r in results:
        if r.optimal_params:
            strategy_model = {
                'min_score': r.optimal_params.get('min_score', 5.0),
                'performance': {
                    'win_rate': r.win_rate,
                    'profit_factor': r.profit_factor,
                    'sharpe_ratio': r.sharpe_ratio,
                },
                'regime_adjustments': {},
            }

            # Per-Regime Score-Anpassungen
            for regime_name, perf in r.regime_performance.items():
                if perf.win_rate >= 60:
                    strategy_model['regime_adjustments'][regime_name] = {
                        'score_modifier': -0.5,  # Erlaube niedrigere Scores
                        'position_size_modifier': 1.2,  # Größere Positionen
                    }
                elif perf.win_rate < 45:
                    strategy_model['regime_adjustments'][regime_name] = {
                        'score_modifier': +1.0,  # Erfordere höhere Scores
                        'position_size_modifier': 0.7,  # Kleinere Positionen
                    }
                else:
                    strategy_model['regime_adjustments'][regime_name] = {
                        'score_modifier': 0.0,
                        'position_size_modifier': 1.0,
                    }

            # Component Weights
            if r.component_analysis:
                strategy_model['component_weights'] = {
                    k: v.weight_suggestion
                    for k, v in r.component_analysis.items()
                }

            model_data['strategies'][r.strategy] = strategy_model

    model_path = output_dir / 'strategy_models.json'
    with open(model_path, 'w') as f:
        json.dump(model_data, f, indent=2)

    print(f"  Models exported to: {model_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Full strategy backtesting and training',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--strategy', type=str,
                        choices=['pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'all'],
                        default='all', help='Strategy to test (default: all)')
    parser.add_argument('--train', action='store_true',
                        help='Run walk-forward training with parameter optimization')
    parser.add_argument('--regime-analysis', action='store_true',
                        help='Include detailed VIX regime analysis')
    parser.add_argument('--min-score', type=float, default=5.0,
                        help='Minimum signal score (default: 5.0)')
    parser.add_argument('--profit-target', type=float, default=50.0,
                        help='Profit target %% (default: 50)')
    parser.add_argument('--stop-loss', type=float, default=100.0,
                        help='Stop loss %% (default: 100)')
    parser.add_argument('--capital', type=float, default=100000.0,
                        help='Initial capital (default: 100000)')
    parser.add_argument('--quick', action='store_true',
                        help='Quick mode with shorter periods')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output with component analysis')
    parser.add_argument('--output', type=str,
                        help='Save results to JSON file')
    parser.add_argument('--export', action='store_true',
                        help='Export trained models for production')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
    )

    print_header("OPTIONPLAY FULL STRATEGY BACKTEST & TRAINING")

    # Load data
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    if stats['symbols_with_price_data'] == 0:
        print("\n  ❌ No historical data found!")
        print("     Run first: python scripts/backfill_tradier.py")
        sys.exit(1)

    print(f"\n  Database: {stats['symbols_with_price_data']} symbols, {stats['total_price_bars']:,} bars")
    print(f"  VIX Data: {stats['vix_data_points']:,} points")

    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_info]

    print(f"  Loading historical data for {len(symbols)} symbols...")
    historical_data = load_historical_data(tracker, symbols)
    vix_data = load_vix_data(tracker)

    print(f"  Loaded: {len(historical_data)} symbols with data")

    # Determine date range
    all_dates = []
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            all_dates.append(d)

    start_date = min(all_dates)
    end_date = max(all_dates)
    print(f"  Date range: {start_date} to {end_date}")

    # Configure backtest
    config = BacktestConfig(
        initial_capital=args.capital,
        profit_target_pct=args.profit_target,
        stop_loss_pct=args.stop_loss,
        min_score=args.min_score,
    )

    if args.quick:
        config.train_months = 6
        config.test_months = 2
        config.step_months = 2
        config.min_trades_per_epoch = 10

    print(f"\n  Config:")
    print(f"    Capital:       ${config.initial_capital:,.0f}")
    print(f"    Profit Target: {config.profit_target_pct}%")
    print(f"    Stop Loss:     {config.stop_loss_pct}%")
    print(f"    Min Score:     {config.min_score}")
    if args.train:
        print(f"    Training:      {config.train_months}mo train / {config.test_months}mo test")

    # Setup backtester
    backtester = FullStrategyBacktester(config)
    backtester.set_vix_data(vix_data)

    results: List[StrategyResult] = []

    strategies = [args.strategy] if args.strategy != 'all' else STRATEGIES

    print_header("RUNNING BACKTESTS...")

    for strategy in strategies:
        print(f"\n  Testing {strategy}...")

        try:
            if args.train:
                result = backtester.run_walk_forward(
                    strategy=strategy,
                    historical_data=historical_data,
                    optimize_score=True
                )
            else:
                result = backtester.run_backtest(
                    strategy=strategy,
                    historical_data=historical_data,
                    start_date=start_date,
                    end_date=end_date
                )

            results.append(result)

            status = "🟢" if result.win_rate >= 55 else "🟡" if result.win_rate >= 45 else "🔴"
            print(f"    {status} {result.total_trades} trades, Win Rate: {result.win_rate:.1f}%, P&L: ${result.total_pnl:+,.0f}")

        except Exception as e:
            print(f"    ❌ Error: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Print results
    for result in results:
        print_strategy_result(result, verbose=args.verbose)

    if len(results) > 1:
        print_comparison_table(results)

        if args.regime_analysis:
            print_regime_comparison(results)

    # Save results
    if args.output:
        save_results(results, Path(args.output))
    else:
        output_dir = Path.home() / '.optionplay' / 'models'
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f'backtest_{timestamp}.json'
        save_results(results, output_path)

    # Export models
    if args.export and args.train:
        output_dir = Path.home() / '.optionplay' / 'models'
        export_trained_models(results, output_dir)

    # Summary
    print_header("SUMMARY")
    if results:
        best = max(results, key=lambda x: x.total_pnl)
        print(f"  Best Strategy:     {best.strategy.upper()}")
        print(f"  P&L:               ${best.total_pnl:+,.0f}")
        print(f"  Win Rate:          {best.win_rate:.1f}%")
        print(f"  Profit Factor:     {best.profit_factor:.2f}")

        if best.epochs:
            print(f"  Overfit Severity:  {best.overfit_severity.upper()}")

    print("═" * 80)


if __name__ == '__main__':
    main()
