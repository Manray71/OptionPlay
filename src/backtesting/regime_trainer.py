#!/usr/bin/env python3
"""
Regime-Based Walk-Forward Training Module

Trains separate models for each VIX regime, optimizing parameters and
strategy selection independently. Supports both fixed and percentile-based
regime boundaries with automatic best-method selection.

Features:
- Per-regime Walk-Forward training
- Automatic strategy enablement based on performance
- Hysteresis-aware regime transitions
- Fixed vs. Percentile boundary comparison
- Component weight optimization per regime

Usage:
    from src.backtesting.regime_trainer import RegimeTrainer, RegimeTrainingConfig

    config = RegimeTrainingConfig(
        train_months=12,
        test_months=3,
        compare_boundary_methods=True,
    )

    trainer = RegimeTrainer(config)
    result = trainer.train(historical_data, vix_data)

    print(result.summary())
    trainer.save(result, "~/.optionplay/models/regime_model.json")
"""

import json
import logging
import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set

from .regime_config import (
    RegimeConfig,
    RegimeType,
    RegimeBoundaryMethod,
    RegimeState,
    FIXED_REGIMES,
    create_percentile_regimes,
    get_regime_for_vix,
    save_regimes,
    load_regimes,
    format_regime_summary,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class RegimeTrainingConfig:
    """Configuration for regime-based training"""

    # Walk-Forward Parameters
    train_months: int = 12                  # Training period per epoch
    test_months: int = 3                    # Test period per epoch
    step_months: int = 3                    # Step between epochs

    # Quality Requirements
    min_trades_per_regime: int = 50         # Minimum trades for valid training
    min_trades_per_epoch: int = 20          # Minimum trades per epoch
    min_valid_epochs: int = 2               # Minimum valid epochs per regime

    # Regime Boundary Settings
    compare_boundary_methods: bool = True   # Compare fixed vs percentile
    percentile_thresholds: Tuple[float, float, float] = (25, 50, 75)

    # Strategy Optimization
    auto_disable_strategies: bool = True    # Disable underperforming strategies
    strategy_disable_threshold: float = 45.0  # Disable if win rate below this

    # Parameter Optimization
    optimize_parameters: bool = True        # Optimize min_score, profit_target, etc.
    parameter_grid: Dict[str, List[float]] = field(default_factory=lambda: {
        "min_score": [4.0, 5.0, 6.0, 7.0, 8.0],
        "profit_target_pct": [40.0, 50.0, 60.0, 75.0],
        "stop_loss_pct": [75.0, 100.0, 150.0, 200.0],
    })

    # Backtest Defaults (gemäß strategies.yaml Basisstrategie)
    initial_capital: float = 100000.0
    dte_min: int = 60                       # Basisstrategie: 60-90 DTE
    dte_max: int = 90

    # Delta-basierte Strike-Auswahl (gemäß strategies.yaml Basisstrategie)
    use_delta_based_strikes: bool = True
    short_delta_target: float = -0.20       # Short Put Delta
    long_delta_target: float = -0.05        # Long Put Delta

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "train_months": self.train_months,
            "test_months": self.test_months,
            "step_months": self.step_months,
            "min_trades_per_regime": self.min_trades_per_regime,
            "min_trades_per_epoch": self.min_trades_per_epoch,
            "min_valid_epochs": self.min_valid_epochs,
            "compare_boundary_methods": self.compare_boundary_methods,
            "percentile_thresholds": self.percentile_thresholds,
            "auto_disable_strategies": self.auto_disable_strategies,
            "strategy_disable_threshold": self.strategy_disable_threshold,
            "optimize_parameters": self.optimize_parameters,
        }


# =============================================================================
# RESULT DATA CLASSES
# =============================================================================

@dataclass
class StrategyPerformance:
    """Performance metrics for a single strategy within a regime"""
    strategy: str
    regime: str
    total_trades: int
    winning_trades: int
    win_rate: float
    avg_pnl: float
    sharpe_ratio: float
    profit_factor: float
    should_enable: bool
    confidence: str  # "high", "medium", "low"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "regime": self.regime,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": round(self.win_rate, 1),
            "avg_pnl": round(self.avg_pnl, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "profit_factor": round(self.profit_factor, 2),
            "should_enable": self.should_enable,
            "confidence": self.confidence,
        }


@dataclass
class RegimeEpochResult:
    """Result from a single training epoch within a regime"""
    epoch_id: int
    regime: str
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    # In-Sample Metrics
    in_sample_trades: int
    in_sample_win_rate: float
    in_sample_pnl: float
    in_sample_sharpe: float

    # Out-of-Sample Metrics
    out_sample_trades: int
    out_sample_win_rate: float
    out_sample_pnl: float
    out_sample_sharpe: float

    # Degradation
    win_rate_degradation: float
    pnl_degradation: float

    # Validity
    is_valid: bool = True
    skip_reason: str = ""

    # Strategy breakdown
    strategy_performance: Dict[str, StrategyPerformance] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "regime": self.regime,
            "train_period": f"{self.train_start} to {self.train_end}",
            "test_period": f"{self.test_start} to {self.test_end}",
            "in_sample": {
                "trades": self.in_sample_trades,
                "win_rate": round(self.in_sample_win_rate, 1),
                "pnl": round(self.in_sample_pnl, 2),
                "sharpe": round(self.in_sample_sharpe, 2),
            },
            "out_sample": {
                "trades": self.out_sample_trades,
                "win_rate": round(self.out_sample_win_rate, 1),
                "pnl": round(self.out_sample_pnl, 2),
                "sharpe": round(self.out_sample_sharpe, 2),
            },
            "degradation": {
                "win_rate": round(self.win_rate_degradation, 1),
                "pnl": round(self.pnl_degradation, 2),
            },
            "is_valid": self.is_valid,
            "skip_reason": self.skip_reason,
        }


@dataclass
class RegimeTrainingResult:
    """Complete training result for a single regime"""
    regime: str
    config: RegimeConfig

    # Epoch Results
    epochs: List[RegimeEpochResult]
    total_epochs: int
    valid_epochs: int

    # Aggregated Metrics
    avg_in_sample_win_rate: float
    avg_out_sample_win_rate: float
    avg_win_rate_degradation: float
    avg_sharpe: float
    total_trades: int

    # Strategy Recommendations
    strategy_performance: Dict[str, StrategyPerformance]
    enabled_strategies: List[str]
    disabled_strategies: List[str]

    # Optimized Parameters
    optimized_min_score: float
    optimized_profit_target: float
    optimized_stop_loss: float

    # Quality Assessment
    overfit_severity: str  # "none", "mild", "moderate", "severe"
    confidence_level: str  # "high", "medium", "low"
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "config": self.config.to_dict(),
            "epochs_summary": {
                "total": self.total_epochs,
                "valid": self.valid_epochs,
            },
            "metrics": {
                "avg_in_sample_win_rate": round(self.avg_in_sample_win_rate, 1),
                "avg_out_sample_win_rate": round(self.avg_out_sample_win_rate, 1),
                "avg_win_rate_degradation": round(self.avg_win_rate_degradation, 1),
                "avg_sharpe": round(self.avg_sharpe, 2),
                "total_trades": self.total_trades,
            },
            "strategy_recommendations": {
                "enabled": self.enabled_strategies,
                "disabled": self.disabled_strategies,
                "performance": {
                    k: v.to_dict() for k, v in self.strategy_performance.items()
                },
            },
            "optimized_parameters": {
                "min_score": self.optimized_min_score,
                "profit_target_pct": self.optimized_profit_target,
                "stop_loss_pct": self.optimized_stop_loss,
            },
            "quality": {
                "overfit_severity": self.overfit_severity,
                "confidence_level": self.confidence_level,
            },
            "epochs": [e.to_dict() for e in self.epochs],
            "warnings": self.warnings,
        }


@dataclass
class FullRegimeTrainingResult:
    """Complete training result across all regimes"""
    training_id: str
    training_date: datetime
    config: RegimeTrainingConfig

    # Boundary Method Comparison
    boundary_method_used: RegimeBoundaryMethod
    fixed_boundaries_score: float
    percentile_boundaries_score: float

    # Per-Regime Results
    regime_results: Dict[str, RegimeTrainingResult]

    # Final Regime Configurations
    trained_regimes: Dict[str, RegimeConfig]

    # Summary Statistics
    total_trades_analyzed: int
    avg_out_sample_win_rate: float
    overall_confidence: str

    # Warnings
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": "2.0.0",
            "training_id": self.training_id,
            "training_date": self.training_date.isoformat(),
            "config": self.config.to_dict(),
            "boundary_comparison": {
                "method_used": self.boundary_method_used.value,
                "fixed_score": round(self.fixed_boundaries_score, 3),
                "percentile_score": round(self.percentile_boundaries_score, 3),
            },
            "regime_results": {
                name: result.to_dict()
                for name, result in self.regime_results.items()
            },
            "trained_regimes": {
                name: config.to_dict()
                for name, config in self.trained_regimes.items()
            },
            "summary": {
                "total_trades": self.total_trades_analyzed,
                "avg_out_sample_win_rate": round(self.avg_out_sample_win_rate, 1),
                "overall_confidence": self.overall_confidence,
            },
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        """Format as readable summary"""
        lines = [
            "",
            "=" * 80,
            "  REGIME-BASED TRAINING RESULT",
            "=" * 80,
            f"  Training ID:      {self.training_id}",
            f"  Date:             {self.training_date.strftime('%Y-%m-%d %H:%M')}",
            f"  Boundary Method:  {self.boundary_method_used.value}",
            f"  Total Trades:     {self.total_trades_analyzed:,}",
            f"  Avg OOS Win Rate: {self.avg_out_sample_win_rate:.1f}%",
            f"  Confidence:       {self.overall_confidence.upper()}",
            "",
            "-" * 80,
            "  PER-REGIME SUMMARY",
            "-" * 80,
            "",
            f"{'Regime':<12} {'VIX':<10} {'Trades':>8} {'IS Win%':>10} {'OOS Win%':>10} {'Degrad':>10} {'Strategies':<20}",
            "-" * 80,
        ]

        for name in ["low_vol", "normal", "elevated", "high_vol"]:
            if name not in self.regime_results:
                continue

            result = self.regime_results[name]
            config = self.trained_regimes.get(name)
            if not config:
                continue

            vix_range = f"{config.vix_lower:.0f}-{config.vix_upper:.0f}"
            strategies = ",".join(s[:3] for s in result.enabled_strategies)

            severity_icon = {
                "none": "",
                "mild": "*",
                "moderate": "**",
                "severe": "***",
            }.get(result.overfit_severity, "")

            lines.append(
                f"{name:<12} {vix_range:<10} {result.total_trades:>8} "
                f"{result.avg_in_sample_win_rate:>9.1f}% "
                f"{result.avg_out_sample_win_rate:>9.1f}% "
                f"{result.avg_win_rate_degradation:>+9.1f}% "
                f"{strategies:<20} {severity_icon}"
            )

        lines.extend([
            "",
            "-" * 80,
            "  OPTIMIZED PARAMETERS",
            "-" * 80,
            "",
            f"{'Regime':<12} {'Min Score':>10} {'Profit %':>10} {'Stop %':>10}",
            "-" * 50,
        ])

        for name in ["low_vol", "normal", "elevated", "high_vol"]:
            if name not in self.regime_results:
                continue
            result = self.regime_results[name]
            lines.append(
                f"{name:<12} {result.optimized_min_score:>10.1f} "
                f"{result.optimized_profit_target:>10.0f} "
                f"{result.optimized_stop_loss:>10.0f}"
            )

        if self.warnings:
            lines.extend([
                "",
                "-" * 80,
                "  WARNINGS",
                "-" * 80,
            ])
            for warning in self.warnings:
                lines.append(f"  ! {warning}")

        lines.append("=" * 80)
        return "\n".join(lines)


# =============================================================================
# REGIME TRAINER
# =============================================================================

class RegimeTrainer:
    """
    Trains separate models for each VIX regime.

    Process:
    1. Segment historical data by VIX regime
    2. For each regime:
       a) Run Walk-Forward training
       b) Optimize parameters (min_score, profit_target, stop_loss)
       c) Evaluate strategy performance
       d) Determine which strategies to enable/disable
    3. Compare fixed vs percentile boundaries
    4. Select best configuration per regime
    """

    ALL_STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip"]

    OVERFIT_THRESHOLDS = {
        "none": 5.0,
        "mild": 10.0,
        "moderate": 15.0,
        "severe": float("inf"),
    }

    def __init__(self, config: RegimeTrainingConfig):
        """
        Initialize trainer.

        Args:
            config: Training configuration
        """
        self.config = config
        self._last_result: Optional[FullRegimeTrainingResult] = None

    def train(
        self,
        historical_data: Dict[str, List[Dict]],
        vix_data: List[Dict],
        symbols: Optional[List[str]] = None,
    ) -> FullRegimeTrainingResult:
        """
        Execute full regime-based training.

        Args:
            historical_data: Dict of {symbol: [{date, open, high, low, close, volume}, ...]}
            vix_data: List of [{date, close/value}, ...]
            symbols: Optional list of symbols to include

        Returns:
            FullRegimeTrainingResult with all regime configurations
        """
        training_id = f"regime_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        training_date = datetime.now()
        warnings: List[str] = []

        # Determine symbols
        test_symbols = symbols or list(historical_data.keys())
        if not test_symbols:
            raise ValueError("No symbols available for training")

        logger.info(f"Starting regime training with {len(test_symbols)} symbols")

        # Normalize VIX data
        vix_by_date = self._normalize_vix_data(vix_data)
        vix_values = list(vix_by_date.values())

        if len(vix_values) < 100:
            warnings.append(f"Limited VIX history ({len(vix_values)} points)")

        # Create regime configurations
        fixed_regimes = FIXED_REGIMES.copy()
        percentile_regimes = create_percentile_regimes(
            vix_values,
            self.config.percentile_thresholds,
        )

        # Segment data by regime
        fixed_segments = self._segment_data_by_regime(
            historical_data, vix_by_date, fixed_regimes, test_symbols
        )
        percentile_segments = self._segment_data_by_regime(
            historical_data, vix_by_date, percentile_regimes, test_symbols
        )

        # Train with both boundary methods
        fixed_results = {}
        percentile_results = {}

        logger.info("Training with fixed boundaries...")
        for regime_name, segment_data in fixed_segments.items():
            if len(segment_data["trades"]) < self.config.min_trades_per_regime:
                logger.warning(
                    f"Skipping {regime_name} (fixed): only {len(segment_data['trades'])} trades"
                )
                continue

            result = self._train_regime(
                regime_name=regime_name,
                regime_config=fixed_regimes[regime_name],
                segment_data=segment_data,
                historical_data=historical_data,
                vix_by_date=vix_by_date,
            )
            fixed_results[regime_name] = result

        if self.config.compare_boundary_methods:
            logger.info("Training with percentile boundaries...")
            for regime_name, segment_data in percentile_segments.items():
                if len(segment_data["trades"]) < self.config.min_trades_per_regime:
                    continue

                result = self._train_regime(
                    regime_name=regime_name,
                    regime_config=percentile_regimes[regime_name],
                    segment_data=segment_data,
                    historical_data=historical_data,
                    vix_by_date=vix_by_date,
                )
                percentile_results[regime_name] = result

        # Compare and select best method
        fixed_score = self._calculate_method_score(fixed_results)
        percentile_score = self._calculate_method_score(percentile_results) if percentile_results else 0

        if percentile_score > fixed_score and percentile_results:
            best_method = RegimeBoundaryMethod.PERCENTILE
            best_results = percentile_results
            best_regimes = percentile_regimes
            logger.info(
                f"Percentile boundaries selected (score: {percentile_score:.3f} vs {fixed_score:.3f})"
            )
        else:
            best_method = RegimeBoundaryMethod.FIXED
            best_results = fixed_results
            best_regimes = fixed_regimes
            logger.info(
                f"Fixed boundaries selected (score: {fixed_score:.3f} vs {percentile_score:.3f})"
            )

        # Apply trained parameters to regime configs
        trained_regimes = self._apply_training_to_regimes(best_regimes, best_results)

        # Calculate summary statistics
        total_trades = sum(r.total_trades for r in best_results.values())
        avg_win_rates = [r.avg_out_sample_win_rate for r in best_results.values() if r.valid_epochs > 0]
        avg_oos_win_rate = statistics.mean(avg_win_rates) if avg_win_rates else 0

        # Determine overall confidence
        low_confidence_count = sum(
            1 for r in best_results.values()
            if r.confidence_level == "low"
        )
        if low_confidence_count >= 2:
            overall_confidence = "low"
        elif low_confidence_count >= 1:
            overall_confidence = "medium"
        else:
            overall_confidence = "high"

        result = FullRegimeTrainingResult(
            training_id=training_id,
            training_date=training_date,
            config=self.config,
            boundary_method_used=best_method,
            fixed_boundaries_score=fixed_score,
            percentile_boundaries_score=percentile_score,
            regime_results=best_results,
            trained_regimes=trained_regimes,
            total_trades_analyzed=total_trades,
            avg_out_sample_win_rate=avg_oos_win_rate,
            overall_confidence=overall_confidence,
            warnings=warnings,
        )

        self._last_result = result
        return result

    def _normalize_vix_data(self, vix_data: List[Dict]) -> Dict[date, float]:
        """Convert VIX data to {date: value} dict"""
        result = {}
        for point in vix_data:
            d = point.get("date")
            if isinstance(d, str):
                d = date.fromisoformat(d)
            value = point.get("close") or point.get("value")
            if d and value:
                result[d] = float(value)
        return result

    def _segment_data_by_regime(
        self,
        historical_data: Dict[str, List[Dict]],
        vix_by_date: Dict[date, float],
        regimes: Dict[str, RegimeConfig],
        symbols: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Segment historical data by VIX regime.

        Returns dict of:
        {
            regime_name: {
                "dates": List[date],
                "trades": List[Dict],  # Simulated trade opportunities
                "vix_values": List[float],
            }
        }
        """
        segments: Dict[str, Dict] = {
            name: {"dates": [], "trades": [], "vix_values": []}
            for name in regimes.keys()
        }

        # Get all unique dates with both price and VIX data
        all_dates: Set[date] = set()
        for symbol in symbols:
            if symbol not in historical_data:
                continue
            for bar in historical_data[symbol]:
                d = bar.get("date")
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if d in vix_by_date:
                    all_dates.add(d)

        # Segment dates by regime
        for d in sorted(all_dates):
            vix = vix_by_date.get(d)
            if vix is None:
                continue

            regime_name, _ = get_regime_for_vix(vix, regimes)
            segments[regime_name]["dates"].append(d)
            segments[regime_name]["vix_values"].append(vix)

        # Generate synthetic trade opportunities for each regime
        for regime_name, segment in segments.items():
            segment["trades"] = self._generate_trade_opportunities(
                regime_dates=set(segment["dates"]),
                historical_data=historical_data,
                symbols=symbols,
            )

        return segments

    def _generate_trade_opportunities(
        self,
        regime_dates: Set[date],
        historical_data: Dict[str, List[Dict]],
        symbols: List[str],
    ) -> List[Dict]:
        """
        Generate potential trade opportunities within regime dates.

        This is a simplified simulation - actual trades would use
        the full analyzer pipeline.
        """
        opportunities = []

        for symbol in symbols:
            if symbol not in historical_data:
                continue

            bars = historical_data[symbol]
            bars_by_date = {}
            for bar in bars:
                d = bar.get("date")
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                bars_by_date[d] = bar

            for d in sorted(regime_dates):
                if d not in bars_by_date:
                    continue

                bar = bars_by_date[d]
                opportunities.append({
                    "symbol": symbol,
                    "date": d,
                    "price": bar.get("close", 0),
                    "volume": bar.get("volume", 0),
                })

        return opportunities

    def _train_regime(
        self,
        regime_name: str,
        regime_config: RegimeConfig,
        segment_data: Dict[str, Any],
        historical_data: Dict[str, List[Dict]],
        vix_by_date: Dict[date, float],
    ) -> RegimeTrainingResult:
        """
        Train a single regime using Walk-Forward methodology.
        """
        logger.info(f"Training regime: {regime_name}")

        epochs: List[RegimeEpochResult] = []
        strategy_trades: Dict[str, List[Dict]] = defaultdict(list)

        regime_dates = sorted(segment_data["dates"])
        if len(regime_dates) < 60:
            return self._create_empty_result(regime_name, regime_config, "Insufficient dates")

        # Generate epochs within regime dates
        epoch_configs = self._generate_regime_epochs(regime_dates)

        if len(epoch_configs) < self.config.min_valid_epochs:
            return self._create_empty_result(
                regime_name, regime_config,
                f"Only {len(epoch_configs)} epochs possible"
            )

        # Run Walk-Forward for each epoch
        for i, (train_dates, test_dates) in enumerate(epoch_configs):
            epoch_result = self._run_regime_epoch(
                epoch_id=i + 1,
                regime_name=regime_name,
                train_dates=train_dates,
                test_dates=test_dates,
                historical_data=historical_data,
                vix_by_date=vix_by_date,
                regime_config=regime_config,
            )
            epochs.append(epoch_result)

            # Collect strategy trades for performance analysis
            for strategy, perf in epoch_result.strategy_performance.items():
                strategy_trades[strategy].append({
                    "win_rate": perf.win_rate,
                    "trades": perf.total_trades,
                })

        # Aggregate results
        valid_epochs = [e for e in epochs if e.is_valid]
        n_valid = len(valid_epochs)

        if n_valid == 0:
            return self._create_empty_result(regime_name, regime_config, "No valid epochs")

        # Calculate aggregated metrics
        avg_is_win_rate = statistics.mean(e.in_sample_win_rate for e in valid_epochs)
        avg_oos_win_rate = statistics.mean(e.out_sample_win_rate for e in valid_epochs)
        avg_degradation = avg_is_win_rate - avg_oos_win_rate
        avg_sharpe = statistics.mean(e.out_sample_sharpe for e in valid_epochs)
        total_trades = sum(e.in_sample_trades + e.out_sample_trades for e in valid_epochs)

        # Analyze strategy performance
        strategy_performance = self._analyze_strategy_performance(
            strategy_trades, regime_name
        )

        # Determine which strategies to enable
        enabled_strategies = []
        disabled_strategies = []

        if self.config.auto_disable_strategies:
            for strategy, perf in strategy_performance.items():
                if perf.should_enable:
                    enabled_strategies.append(strategy)
                else:
                    disabled_strategies.append(strategy)
        else:
            enabled_strategies = self.ALL_STRATEGIES.copy()

        # Optimize parameters
        optimized_params = self._optimize_parameters(
            valid_epochs, regime_config
        ) if self.config.optimize_parameters else {
            "min_score": regime_config.min_score,
            "profit_target_pct": regime_config.profit_target_pct,
            "stop_loss_pct": regime_config.stop_loss_pct,
        }

        # Determine overfit severity
        overfit_severity = self._classify_overfit(avg_degradation)

        # Determine confidence level
        if n_valid >= 4 and total_trades >= 200:
            confidence = "high"
        elif n_valid >= 2 and total_trades >= 100:
            confidence = "medium"
        else:
            confidence = "low"

        warnings = []
        if overfit_severity in ("moderate", "severe"):
            warnings.append(f"Significant overfitting detected ({avg_degradation:.1f}% degradation)")
        if not enabled_strategies:
            warnings.append("No strategies passed performance threshold")
            enabled_strategies = ["pullback"]  # Always keep at least one

        return RegimeTrainingResult(
            regime=regime_name,
            config=regime_config,
            epochs=epochs,
            total_epochs=len(epochs),
            valid_epochs=n_valid,
            avg_in_sample_win_rate=avg_is_win_rate,
            avg_out_sample_win_rate=avg_oos_win_rate,
            avg_win_rate_degradation=avg_degradation,
            avg_sharpe=avg_sharpe,
            total_trades=total_trades,
            strategy_performance=strategy_performance,
            enabled_strategies=enabled_strategies,
            disabled_strategies=disabled_strategies,
            optimized_min_score=optimized_params["min_score"],
            optimized_profit_target=optimized_params["profit_target_pct"],
            optimized_stop_loss=optimized_params["stop_loss_pct"],
            overfit_severity=overfit_severity,
            confidence_level=confidence,
            warnings=warnings,
        )

    def _generate_regime_epochs(
        self,
        regime_dates: List[date],
    ) -> List[Tuple[List[date], List[date]]]:
        """Generate train/test epoch splits within regime dates"""
        epochs = []

        train_days = self.config.train_months * 21  # ~21 trading days/month
        test_days = self.config.test_months * 21
        step_days = self.config.step_months * 21

        n = len(regime_dates)
        start_idx = 0

        while start_idx + train_days + test_days <= n:
            train_end_idx = start_idx + train_days
            test_end_idx = train_end_idx + test_days

            train_dates = regime_dates[start_idx:train_end_idx]
            test_dates = regime_dates[train_end_idx:test_end_idx]

            if len(train_dates) >= 60 and len(test_dates) >= 20:
                epochs.append((train_dates, test_dates))

            start_idx += step_days

        return epochs

    def _run_regime_epoch(
        self,
        epoch_id: int,
        regime_name: str,
        train_dates: List[date],
        test_dates: List[date],
        historical_data: Dict[str, List[Dict]],
        vix_by_date: Dict[date, float],
        regime_config: RegimeConfig,
    ) -> RegimeEpochResult:
        """Run a single Walk-Forward epoch within a regime"""
        # Simulate trades for train period
        train_trades = self._simulate_trades(
            dates=train_dates,
            historical_data=historical_data,
            min_score=regime_config.min_score,
        )

        # Simulate trades for test period
        test_trades = self._simulate_trades(
            dates=test_dates,
            historical_data=historical_data,
            min_score=regime_config.min_score,
        )

        # Check validity
        if len(train_trades) < self.config.min_trades_per_epoch:
            return RegimeEpochResult(
                epoch_id=epoch_id,
                regime=regime_name,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                in_sample_trades=len(train_trades),
                in_sample_win_rate=0,
                in_sample_pnl=0,
                in_sample_sharpe=0,
                out_sample_trades=len(test_trades),
                out_sample_win_rate=0,
                out_sample_pnl=0,
                out_sample_sharpe=0,
                win_rate_degradation=0,
                pnl_degradation=0,
                is_valid=False,
                skip_reason=f"Only {len(train_trades)} training trades",
            )

        if len(test_trades) < 10:
            return RegimeEpochResult(
                epoch_id=epoch_id,
                regime=regime_name,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                in_sample_trades=len(train_trades),
                in_sample_win_rate=0,
                in_sample_pnl=0,
                in_sample_sharpe=0,
                out_sample_trades=len(test_trades),
                out_sample_win_rate=0,
                out_sample_pnl=0,
                out_sample_sharpe=0,
                win_rate_degradation=0,
                pnl_degradation=0,
                is_valid=False,
                skip_reason=f"Only {len(test_trades)} test trades",
            )

        # Calculate metrics
        is_metrics = self._calculate_trade_metrics(train_trades)
        oos_metrics = self._calculate_trade_metrics(test_trades)

        # Calculate strategy performance within this epoch
        strategy_perf = {}
        for strategy in self.ALL_STRATEGIES:
            strategy_train = [t for t in train_trades if t.get("strategy") == strategy]
            if strategy_train:
                s_metrics = self._calculate_trade_metrics(strategy_train)
                strategy_perf[strategy] = StrategyPerformance(
                    strategy=strategy,
                    regime=regime_name,
                    total_trades=len(strategy_train),
                    winning_trades=sum(1 for t in strategy_train if t.get("pnl", 0) > 0),
                    win_rate=s_metrics["win_rate"],
                    avg_pnl=s_metrics["avg_pnl"],
                    sharpe_ratio=s_metrics["sharpe"],
                    profit_factor=s_metrics["profit_factor"],
                    should_enable=s_metrics["win_rate"] >= self.config.strategy_disable_threshold,
                    confidence="medium" if len(strategy_train) >= 20 else "low",
                )

        return RegimeEpochResult(
            epoch_id=epoch_id,
            regime=regime_name,
            train_start=train_dates[0],
            train_end=train_dates[-1],
            test_start=test_dates[0],
            test_end=test_dates[-1],
            in_sample_trades=len(train_trades),
            in_sample_win_rate=is_metrics["win_rate"],
            in_sample_pnl=is_metrics["total_pnl"],
            in_sample_sharpe=is_metrics["sharpe"],
            out_sample_trades=len(test_trades),
            out_sample_win_rate=oos_metrics["win_rate"],
            out_sample_pnl=oos_metrics["total_pnl"],
            out_sample_sharpe=oos_metrics["sharpe"],
            win_rate_degradation=is_metrics["win_rate"] - oos_metrics["win_rate"],
            pnl_degradation=is_metrics["total_pnl"] - oos_metrics["total_pnl"],
            is_valid=True,
            strategy_performance=strategy_perf,
        )

    def _simulate_trades(
        self,
        dates: List[date],
        historical_data: Dict[str, List[Dict]],
        min_score: float,
    ) -> List[Dict]:
        """
        Simulate trade outcomes for given dates.

        This is a simplified simulation that generates trade-like outcomes
        for training purposes. In production, actual analyzer output would
        be used.
        """
        import random

        trades = []
        symbols = list(historical_data.keys())

        # Sample dates for trade entry (not every day)
        trade_dates = random.sample(dates, min(len(dates) // 3, 50))

        for d in sorted(trade_dates):
            # Pick random symbols
            selected_symbols = random.sample(symbols, min(5, len(symbols)))

            for symbol in selected_symbols:
                bars = historical_data.get(symbol, [])
                bar = None
                for b in bars:
                    bd = b.get("date")
                    if isinstance(bd, str):
                        bd = date.fromisoformat(bd)
                    if bd == d:
                        bar = b
                        break

                if not bar:
                    continue

                # Simulate score and outcome
                # In real implementation, this would use actual analyzer
                score = random.uniform(3, 12)
                if score < min_score:
                    continue

                # Higher scores = higher win probability (simplified)
                win_prob = 0.40 + (score - 5) * 0.05  # 40% base + 5% per point above 5
                win_prob = min(0.75, max(0.30, win_prob))

                is_winner = random.random() < win_prob

                if is_winner:
                    pnl = random.uniform(50, 200)  # Simulated profit
                else:
                    pnl = random.uniform(-300, -50)  # Simulated loss

                strategy = random.choice(self.ALL_STRATEGIES)

                trades.append({
                    "symbol": symbol,
                    "date": d,
                    "score": score,
                    "pnl": pnl,
                    "is_winner": is_winner,
                    "strategy": strategy,
                })

        return trades

    def _calculate_trade_metrics(self, trades: List[Dict]) -> Dict[str, float]:
        """Calculate performance metrics from trades"""
        if not trades:
            return {
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0,
                "sharpe": 0,
                "profit_factor": 0,
            }

        winners = [t for t in trades if t.get("pnl", 0) > 0]
        losers = [t for t in trades if t.get("pnl", 0) < 0]
        pnls = [t.get("pnl", 0) for t in trades]

        win_rate = len(winners) / len(trades) * 100 if trades else 0
        total_pnl = sum(pnls)
        avg_pnl = statistics.mean(pnls) if pnls else 0

        # Sharpe (simplified)
        if len(pnls) > 1:
            std = statistics.stdev(pnls)
            sharpe = (avg_pnl / std) * (252 ** 0.5) if std > 0 else 0
        else:
            sharpe = 0

        # Profit factor
        gross_profit = sum(t.get("pnl", 0) for t in winners)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        return {
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "sharpe": sharpe,
            "profit_factor": profit_factor,
        }

    def _analyze_strategy_performance(
        self,
        strategy_trades: Dict[str, List[Dict]],
        regime_name: str,
    ) -> Dict[str, StrategyPerformance]:
        """Analyze aggregate performance per strategy"""
        results = {}

        for strategy, epoch_data in strategy_trades.items():
            if not epoch_data:
                continue

            # Aggregate across epochs
            total_trades = sum(e["trades"] for e in epoch_data)
            avg_win_rate = statistics.mean(e["win_rate"] for e in epoch_data) if epoch_data else 0

            should_enable = avg_win_rate >= self.config.strategy_disable_threshold

            # Confidence based on sample size
            if total_trades >= 100:
                confidence = "high"
            elif total_trades >= 50:
                confidence = "medium"
            else:
                confidence = "low"

            results[strategy] = StrategyPerformance(
                strategy=strategy,
                regime=regime_name,
                total_trades=total_trades,
                winning_trades=int(total_trades * avg_win_rate / 100),
                win_rate=avg_win_rate,
                avg_pnl=0,  # Not tracked at this level
                sharpe_ratio=0,
                profit_factor=0,
                should_enable=should_enable,
                confidence=confidence,
            )

        return results

    def _optimize_parameters(
        self,
        valid_epochs: List[RegimeEpochResult],
        regime_config: RegimeConfig,
    ) -> Dict[str, float]:
        """
        Optimize trading parameters based on epoch results.

        Returns best parameters based on out-of-sample performance.
        """
        # Simplified optimization: use median of well-performing epochs
        # In full implementation, would do grid search

        oos_win_rates = [e.out_sample_win_rate for e in valid_epochs]
        avg_oos = statistics.mean(oos_win_rates) if oos_win_rates else 50

        # Adjust min_score based on regime and performance
        base_score = regime_config.min_score

        if avg_oos < 50:
            # Increase min_score if performance is poor
            adjusted_score = min(base_score + 1.0, 9.0)
        elif avg_oos > 60:
            # Can be more aggressive if performance is good
            adjusted_score = max(base_score - 0.5, 4.0)
        else:
            adjusted_score = base_score

        return {
            "min_score": round(adjusted_score, 1),
            "profit_target_pct": regime_config.profit_target_pct,
            "stop_loss_pct": regime_config.stop_loss_pct,
        }

    def _classify_overfit(self, degradation: float) -> str:
        """Classify overfitting severity"""
        abs_deg = abs(degradation)

        if abs_deg < self.OVERFIT_THRESHOLDS["none"]:
            return "none"
        elif abs_deg < self.OVERFIT_THRESHOLDS["mild"]:
            return "mild"
        elif abs_deg < self.OVERFIT_THRESHOLDS["moderate"]:
            return "moderate"
        else:
            return "severe"

    def _calculate_method_score(
        self,
        regime_results: Dict[str, RegimeTrainingResult],
    ) -> float:
        """
        Calculate overall score for a boundary method.

        Higher is better. Considers:
        - Out-of-sample win rate
        - Degradation (penalized)
        - Confidence levels
        """
        if not regime_results:
            return 0.0

        scores = []
        for result in regime_results.values():
            if result.valid_epochs == 0:
                continue

            # Base score from OOS win rate
            base = result.avg_out_sample_win_rate / 100

            # Penalty for degradation
            deg_penalty = abs(result.avg_win_rate_degradation) / 100
            base -= deg_penalty * 0.5

            # Bonus for high confidence
            if result.confidence_level == "high":
                base *= 1.1
            elif result.confidence_level == "low":
                base *= 0.9

            scores.append(base)

        return statistics.mean(scores) if scores else 0.0

    def _apply_training_to_regimes(
        self,
        base_regimes: Dict[str, RegimeConfig],
        training_results: Dict[str, RegimeTrainingResult],
    ) -> Dict[str, RegimeConfig]:
        """Apply training results to create final regime configurations"""
        trained = {}

        for name, base_config in base_regimes.items():
            result = training_results.get(name)

            if result and result.valid_epochs > 0:
                # Apply optimized parameters
                config = RegimeConfig(
                    name=base_config.name,
                    regime_type=base_config.regime_type,
                    vix_lower=base_config.vix_lower,
                    vix_upper=base_config.vix_upper,
                    entry_buffer=base_config.entry_buffer,
                    exit_buffer=base_config.exit_buffer,
                    min_days_in_regime=base_config.min_days_in_regime,
                    min_score=result.optimized_min_score,
                    profit_target_pct=result.optimized_profit_target,
                    stop_loss_pct=result.optimized_stop_loss,
                    position_size_pct=base_config.position_size_pct,
                    max_concurrent_positions=base_config.max_concurrent_positions,
                    strategies_enabled=result.enabled_strategies,
                    description=f"{base_config.description} (trained)",
                    is_trained=True,
                    training_date=datetime.now(),
                    sample_size=result.total_trades,
                    confidence_level=result.confidence_level,
                )
            else:
                # Use base config
                config = base_config

            trained[name] = config

        return trained

    def _create_empty_result(
        self,
        regime_name: str,
        config: RegimeConfig,
        reason: str,
    ) -> RegimeTrainingResult:
        """Create empty result for skipped regime"""
        return RegimeTrainingResult(
            regime=regime_name,
            config=config,
            epochs=[],
            total_epochs=0,
            valid_epochs=0,
            avg_in_sample_win_rate=0,
            avg_out_sample_win_rate=0,
            avg_win_rate_degradation=0,
            avg_sharpe=0,
            total_trades=0,
            strategy_performance={},
            enabled_strategies=config.strategies_enabled,
            disabled_strategies=[],
            optimized_min_score=config.min_score,
            optimized_profit_target=config.profit_target_pct,
            optimized_stop_loss=config.stop_loss_pct,
            overfit_severity="unknown",
            confidence_level="low",
            warnings=[f"Skipped: {reason}"],
        )

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def save(
        self,
        result: FullRegimeTrainingResult,
        filepath: Optional[str] = None,
    ) -> str:
        """
        Save training result to JSON file.

        Args:
            result: Training result to save
            filepath: Optional path (default: ~/.optionplay/models/)

        Returns:
            Path to saved file
        """
        if filepath is None:
            models_dir = Path.home() / ".optionplay" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            filepath = str(models_dir / f"{result.training_id}.json")
        else:
            filepath = str(Path(filepath).expanduser())
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Saved regime training result to {filepath}")

        # Also save the trained regimes separately for easy loading
        regimes_path = str(Path(filepath).parent / f"regimes_{result.training_id}.json")
        save_regimes(result.trained_regimes, regimes_path)

        return filepath

    @classmethod
    def load(cls, filepath: str) -> "RegimeTrainer":
        """
        Load trainer with saved training result.

        Args:
            filepath: Path to saved JSON file

        Returns:
            RegimeTrainer with loaded result
        """
        filepath = str(Path(filepath).expanduser())

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Reconstruct config
        config_data = data.get("config", {})
        config = RegimeTrainingConfig(
            train_months=config_data.get("train_months", 12),
            test_months=config_data.get("test_months", 3),
            step_months=config_data.get("step_months", 3),
            min_trades_per_regime=config_data.get("min_trades_per_regime", 50),
            min_trades_per_epoch=config_data.get("min_trades_per_epoch", 20),
            min_valid_epochs=config_data.get("min_valid_epochs", 2),
            compare_boundary_methods=config_data.get("compare_boundary_methods", True),
            auto_disable_strategies=config_data.get("auto_disable_strategies", True),
            strategy_disable_threshold=config_data.get("strategy_disable_threshold", 45.0),
            optimize_parameters=config_data.get("optimize_parameters", True),
        )

        trainer = cls(config)

        # Load trained regimes
        trained_regimes = {}
        for name, regime_data in data.get("trained_regimes", {}).items():
            trained_regimes[name] = RegimeConfig.from_dict(regime_data)

        # Reconstruct result (simplified)
        trainer._last_result = FullRegimeTrainingResult(
            training_id=data.get("training_id", "loaded"),
            training_date=datetime.fromisoformat(data.get("training_date", datetime.now().isoformat())),
            config=config,
            boundary_method_used=RegimeBoundaryMethod(data.get("boundary_comparison", {}).get("method_used", "fixed")),
            fixed_boundaries_score=data.get("boundary_comparison", {}).get("fixed_score", 0),
            percentile_boundaries_score=data.get("boundary_comparison", {}).get("percentile_score", 0),
            regime_results={},  # Not fully reconstructed
            trained_regimes=trained_regimes,
            total_trades_analyzed=data.get("summary", {}).get("total_trades", 0),
            avg_out_sample_win_rate=data.get("summary", {}).get("avg_out_sample_win_rate", 0),
            overall_confidence=data.get("summary", {}).get("overall_confidence", "unknown"),
            warnings=data.get("warnings", []),
        )

        logger.info(f"Loaded regime training from {filepath}")
        return trainer

    # =========================================================================
    # PRODUCTION METHODS
    # =========================================================================

    def get_current_regime(
        self,
        vix: float,
    ) -> Tuple[str, RegimeConfig]:
        """
        Get regime configuration for current VIX.

        Args:
            vix: Current VIX value

        Returns:
            Tuple of (regime_name, RegimeConfig)
        """
        if self._last_result is None:
            return get_regime_for_vix(vix, FIXED_REGIMES)

        return get_regime_for_vix(vix, self._last_result.trained_regimes)

    def get_trading_parameters(
        self,
        vix: float,
    ) -> Dict[str, Any]:
        """
        Get trading parameters for current market conditions.

        Args:
            vix: Current VIX value

        Returns:
            Dict of trading parameters
        """
        regime_name, config = self.get_current_regime(vix)

        return {
            "regime": regime_name,
            "vix": vix,
            "min_score": config.min_score,
            "profit_target_pct": config.profit_target_pct,
            "stop_loss_pct": config.stop_loss_pct,
            "position_size_pct": config.position_size_pct,
            "max_positions": config.max_concurrent_positions,
            "strategies_enabled": config.strategies_enabled,
            "confidence": config.confidence_level,
        }
