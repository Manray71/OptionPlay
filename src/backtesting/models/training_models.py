"""
Regime Training Data Models
============================

Extracted from regime_trainer.py (Phase 6a).

Contains:
- RegimeTrainingConfig: Configuration for regime-based training
- StrategyPerformance: Performance metrics for a single strategy within a regime
- RegimeEpochResult: Result from a single training epoch
- RegimeTrainingResult: Complete training result for a single regime
- FullRegimeTrainingResult: Complete training result across all regimes
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .regime_config import (
    RegimeConfig,
    RegimeBoundaryMethod,
)


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
