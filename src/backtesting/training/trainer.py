# OptionPlay - Regime Trainer (Facade)
# =====================================
# Extracted from training/regime_trainer.py (Phase 6e)
#
# Orchestrates regime-based training by delegating to:
#   - DataPrep (data normalization, segmentation)
#   - EpochRunner (epoch generation, execution, simulation)
#   - PerformanceAnalyzer (metrics, strategy analysis, overfit)
#   - ParameterOptimizer (parameter optimization, method scoring)
#   - ResultProcessor (save/load persistence)

import logging
import statistics
import uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import (
    RegimeConfig,
    RegimeType,
    RegimeBoundaryMethod,
    FIXED_REGIMES,
    create_percentile_regimes,
    get_regime_for_vix,
)
from ..models.training_models import (
    RegimeTrainingConfig,
    StrategyPerformance,
    RegimeEpochResult,
    RegimeTrainingResult,
    FullRegimeTrainingResult,
)
from .data_prep import DataPrep
from .epoch_runner import EpochRunner
from .performance import PerformanceAnalyzer
from .optimizer import ParameterOptimizer, ResultProcessor

logger = logging.getLogger(__name__)


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

    ALL_STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip", "trend_continuation"]

    def __init__(self, config: RegimeTrainingConfig) -> None:
        """
        Initialize trainer.

        Args:
            config: Training configuration
        """
        self.config = config
        self._last_result: Optional[FullRegimeTrainingResult] = None

        # Sub-modules
        self._data_prep = DataPrep()
        self._epoch_runner = EpochRunner(config)
        self._performance = PerformanceAnalyzer()
        self._optimizer = ParameterOptimizer()
        self._result_processor = ResultProcessor()

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
        vix_by_date = self._data_prep.normalize_vix_data(vix_data)
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
        fixed_segments = self._data_prep.segment_data_by_regime(
            historical_data, vix_by_date, fixed_regimes, test_symbols
        )
        percentile_segments = self._data_prep.segment_data_by_regime(
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
        fixed_score = self._optimizer.calculate_method_score(fixed_results)
        percentile_score = self._optimizer.calculate_method_score(percentile_results) if percentile_results else 0

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
        trained_regimes = self._optimizer.apply_training_to_regimes(best_regimes, best_results)

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
        epoch_configs = self._epoch_runner.generate_regime_epochs(regime_dates)

        if len(epoch_configs) < self.config.min_valid_epochs:
            return self._create_empty_result(
                regime_name, regime_config,
                f"Only {len(epoch_configs)} epochs possible"
            )

        # Run Walk-Forward for each epoch
        for i, (train_dates, test_dates) in enumerate(epoch_configs):
            epoch_result = self._epoch_runner.run_regime_epoch(
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
        strategy_performance = self._performance.analyze_strategy_performance(
            strategy_trades, regime_name, self.config
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
        optimized_params = self._optimizer.optimize_parameters(
            valid_epochs, regime_config
        ) if self.config.optimize_parameters else {
            "min_score": regime_config.min_score,
            "profit_target_pct": regime_config.profit_target_pct,
            "stop_loss_pct": regime_config.stop_loss_pct,
        }

        # Determine overfit severity
        overfit_severity = self._performance.classify_overfit(avg_degradation)

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
    # PERSISTENCE (delegates to ResultProcessor)
    # =========================================================================

    def save(
        self,
        result: FullRegimeTrainingResult,
        filepath: Optional[str] = None,
    ) -> str:
        """Save training result to JSON file."""
        return self._result_processor.save(result, filepath)

    @classmethod
    def load(cls, filepath: str) -> "RegimeTrainer":
        """
        Load trainer with saved training result.

        Args:
            filepath: Path to saved JSON file

        Returns:
            RegimeTrainer with loaded result
        """
        data = ResultProcessor.load(filepath)

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

    # =========================================================================
    # BACKWARD COMPATIBILITY: Private methods delegate to sub-modules
    # =========================================================================

    def _normalize_vix_data(self, vix_data: List[Dict]) -> Dict[date, float]:
        return self._data_prep.normalize_vix_data(vix_data)

    def _segment_data_by_regime(self, *args, **kwargs):
        return self._data_prep.segment_data_by_regime(*args, **kwargs)

    def _generate_trade_opportunities(self, *args, **kwargs):
        return self._data_prep.generate_trade_opportunities(*args, **kwargs)

    def _generate_regime_epochs(self, regime_dates):
        return self._epoch_runner.generate_regime_epochs(regime_dates)

    def _run_regime_epoch(self, *args, **kwargs):
        return self._epoch_runner.run_regime_epoch(*args, **kwargs)

    def _simulate_trades(self, *args, **kwargs):
        return self._epoch_runner.simulate_trades(*args, **kwargs)

    def _calculate_trade_metrics(self, trades):
        return self._performance.calculate_trade_metrics(trades)

    def _analyze_strategy_performance(self, strategy_trades, regime_name):
        return self._performance.analyze_strategy_performance(
            strategy_trades, regime_name, self.config
        )

    def _classify_overfit(self, degradation):
        return self._performance.classify_overfit(degradation)

    def _optimize_parameters(self, valid_epochs, regime_config):
        return self._optimizer.optimize_parameters(valid_epochs, regime_config)

    def _calculate_method_score(self, regime_results):
        return self._optimizer.calculate_method_score(regime_results)

    def _apply_training_to_regimes(self, base_regimes, training_results):
        return self._optimizer.apply_training_to_regimes(base_regimes, training_results)
