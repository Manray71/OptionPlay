#!/usr/bin/env python3
"""
Walk-Forward Result Aggregation

Extracted from walk_forward.py for modularity.
Contains: _aggregate_results, _aggregate_threshold, _aggregate_component_weights,
          _aggregate_predictors, _aggregate_regime_adjustments, _classify_overfit_severity
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class WFResultAggregatorMixin:
    """
    Mixin providing result aggregation logic for WalkForwardTrainer.

    Requires the host class to have:
    - self.config (TrainingConfig)
    - self.OVERFIT_THRESHOLDS (dict)
    """

    def _aggregate_results(
        self,
        training_id: str,
        training_date: datetime,
        epochs: List,  # List[EpochResult]
        warnings: List[str],
    ):
        """Aggregiert Ergebnisse aller Epochen"""
        from .walk_forward import TrainingResult

        valid_epochs = [e for e in epochs if e.is_valid]
        n_valid = len(valid_epochs)

        if n_valid == 0:
            warnings.append("Keine gültigen Epochen für Aggregation!")
            return TrainingResult(
                training_id=training_id,
                training_date=training_date,
                config=self.config,
                epochs=epochs,
                valid_epochs=0,
                total_epochs=len(epochs),
                avg_in_sample_win_rate=0,
                avg_in_sample_sharpe=0,
                avg_out_sample_win_rate=0,
                avg_out_sample_sharpe=0,
                avg_win_rate_degradation=0,
                max_win_rate_degradation=0,
                overfit_severity="severe",
                recommended_min_score=self.config.min_pullback_score,
                top_predictors=[],
                component_weights={},
                regime_adjustments={},
                warnings=warnings,
            )

        # In-Sample Durchschnitte
        avg_in_sample_win_rate = sum(e.in_sample_win_rate for e in valid_epochs) / n_valid
        avg_in_sample_sharpe = sum(e.in_sample_sharpe for e in valid_epochs) / n_valid

        # Out-of-Sample Durchschnitte
        avg_out_sample_win_rate = sum(e.out_sample_win_rate for e in valid_epochs) / n_valid
        avg_out_sample_sharpe = sum(e.out_sample_sharpe for e in valid_epochs) / n_valid

        # Degradation
        avg_win_rate_degradation = avg_in_sample_win_rate - avg_out_sample_win_rate
        max_win_rate_degradation = max(e.win_rate_degradation for e in valid_epochs)

        # Overfit-Severity
        overfit_severity = self._classify_overfit_severity(avg_win_rate_degradation)

        # Empfehlungen aggregieren
        recommended_min_score = self._aggregate_threshold(valid_epochs)
        top_predictors = self._aggregate_predictors(valid_epochs)
        component_weights = self._aggregate_component_weights(valid_epochs)
        regime_adjustments = self._aggregate_regime_adjustments(valid_epochs)

        # Warnungen für Overfit
        if overfit_severity == "moderate":
            warnings.append(
                f"Moderate Overfitting erkannt ({avg_win_rate_degradation:.1f}% Degradation). "
                "Empfehlung: Konservativere Parameter verwenden."
            )
        elif overfit_severity == "severe":
            warnings.append(
                f"Schweres Overfitting erkannt ({avg_win_rate_degradation:.1f}% Degradation). "
                "WARNUNG: Strategie ist möglicherweise nicht produktionsreif!"
            )

        return TrainingResult(
            training_id=training_id,
            training_date=training_date,
            config=self.config,
            epochs=epochs,
            valid_epochs=n_valid,
            total_epochs=len(epochs),
            avg_in_sample_win_rate=avg_in_sample_win_rate,
            avg_in_sample_sharpe=avg_in_sample_sharpe,
            avg_out_sample_win_rate=avg_out_sample_win_rate,
            avg_out_sample_sharpe=avg_out_sample_sharpe,
            avg_win_rate_degradation=avg_win_rate_degradation,
            max_win_rate_degradation=max_win_rate_degradation,
            overfit_severity=overfit_severity,
            recommended_min_score=recommended_min_score,
            top_predictors=top_predictors,
            component_weights=component_weights,
            regime_adjustments=regime_adjustments,
            warnings=warnings,
        )

    def _classify_overfit_severity(self, degradation: float) -> str:
        """Klassifiziert Overfit-Severity"""
        abs_deg = abs(degradation)

        if abs_deg < self.OVERFIT_THRESHOLDS["none"]:
            return "none"
        elif abs_deg < self.OVERFIT_THRESHOLDS["mild"]:
            return "mild"
        elif abs_deg < self.OVERFIT_THRESHOLDS["moderate"]:
            return "moderate"
        else:
            return "severe"

    def _aggregate_threshold(self, epochs: List) -> float:
        """Aggregiert optimalen Threshold aus allen Epochen"""
        if not epochs:
            return self.config.min_pullback_score

        thresholds = [e.optimal_threshold for e in epochs]

        # Konservativer Ansatz: 75. Perzentil
        sorted_thresholds = sorted(thresholds)
        idx = int(len(sorted_thresholds) * 0.75)
        return sorted_thresholds[min(idx, len(sorted_thresholds) - 1)]

    def _aggregate_predictors(self, epochs: List) -> List[str]:
        """Aggregiert Top-Predictors aus allen Epochen"""
        predictor_counts: Counter = Counter()

        for epoch in epochs:
            if epoch.validation_result and epoch.validation_result.top_predictors:
                for pred in epoch.validation_result.top_predictors[:3]:
                    predictor_counts[pred] += 1

        return [pred for pred, _ in predictor_counts.most_common(5)]

    def _aggregate_component_weights(
        self,
        epochs: List,
    ) -> Dict[str, float]:
        """Aggregiert Komponenten-Gewichte"""
        weights: Dict[str, List[float]] = defaultdict(list)

        for epoch in epochs:
            if epoch.validation_result:
                for corr in epoch.validation_result.component_correlations:
                    if corr.predictive_power in ("strong", "moderate"):
                        weights[corr.component_name].append(
                            abs(corr.win_rate_correlation)
                        )

        # Durchschnitt pro Komponente
        return {
            comp: sum(vals) / len(vals)
            for comp, vals in weights.items()
            if vals
        }

    def _aggregate_regime_adjustments(
        self,
        epochs: List,
    ) -> Dict[str, Dict[str, float]]:
        """Aggregiert Regime-Adjustments"""
        adjustments: Dict[str, List[float]] = defaultdict(list)

        for epoch in epochs:
            if epoch.validation_result:
                for regime, adj in epoch.validation_result.regime_sensitivity.items():
                    adjustments[regime].append(adj)

        return {
            regime: {"win_rate_adjustment": sum(vals) / len(vals)}
            for regime, vals in adjustments.items()
            if vals
        }
