# OptionPlay - Parameter Optimization & Result Processing
# =======================================================
# Extracted from training/regime_trainer.py (Phase 6e)
#
# Optimizes trading parameters, scores boundary methods,
# applies training results to regime configurations, and
# handles persistence (save/load).

import json
import logging
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import (
    RegimeConfig,
    RegimeBoundaryMethod,
    save_regimes,
)
from ..models.training_models import (
    RegimeTrainingConfig,
    RegimeTrainingResult,
    RegimeEpochResult,
    FullRegimeTrainingResult,
)

logger = logging.getLogger(__name__)


class ParameterOptimizer:
    """Optimizes trading parameters and processes training results."""

    def optimize_parameters(
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

    def calculate_method_score(
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

    def apply_training_to_regimes(
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


class ResultProcessor:
    """Handles saving and loading of training results."""

    @staticmethod
    def save(
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

    @staticmethod
    def load(filepath: str) -> Dict[str, Any]:
        """
        Load training data from JSON file.

        Args:
            filepath: Path to saved JSON file

        Returns:
            Dict with loaded data
        """
        filepath = str(Path(filepath).expanduser())

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data
