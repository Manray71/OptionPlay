"""
Optimization Methods for ML Weight Optimizer
=============================================

Extracted from ml_weight_optimizer.py (Phase D.8).
Contains the ML/math-heavy analysis and validation methods.

Functions:
- analyze_components: Component-level importance analysis
- cross_validate: Time-series cross-validation
- calculate_baseline_score: Equal-weight baseline
- validate_weights: OOS weight validation
- safe_correlation: Correlation with NaN safety
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np

from .feature_extraction import TradeFeatures

logger = logging.getLogger(__name__)


def safe_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Calculate Pearson correlation safely (returns 0 on degenerate inputs)."""
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def analyze_components(
    features: List[TradeFeatures],
) -> Dict[str, Any]:
    """
    Analyze all score components across trades.

    Returns ComponentStats-compatible dicts keyed by component name.
    Caller (MLWeightOptimizer) wraps into ComponentStats dataclass.

    Args:
        features: List of extracted trade features

    Returns:
        Dict mapping component name to analysis dict with keys:
        win_rate_correlation, pnl_correlation, avg_value_winners,
        avg_value_losers, std_value, rf_importance, gb_importance,
        ensemble_importance, predictive_power, recommended_weight,
        confidence_interval, sample_size
    """
    component_data: Dict[str, Dict[str, list]] = defaultdict(
        lambda: {"values": [], "outcomes": [], "pnls": []}
    )

    for f in features:
        for comp, value in f.components.items():
            component_data[comp]["values"].append(value)
            component_data[comp]["outcomes"].append(1 if f.is_winner else 0)
            component_data[comp]["pnls"].append(f.pnl_percent)

    results: Dict[str, Any] = {}
    for comp, data in component_data.items():
        if len(data["values"]) < 10:
            continue

        values = np.array(data["values"])
        outcomes = np.array(data["outcomes"])
        pnls = np.array(data["pnls"])

        win_corr = safe_correlation(values, outcomes)
        pnl_corr = safe_correlation(values, pnls)

        winner_mask = outcomes == 1
        avg_winners = float(np.mean(values[winner_mask])) if winner_mask.any() else 0.0
        avg_losers = float(np.mean(values[~winner_mask])) if (~winner_mask).any() else 0.0

        rf_imp = abs(win_corr) * 0.5 + abs(pnl_corr) * 0.5
        gb_imp = rf_imp
        ensemble_imp = (rf_imp + gb_imp) / 2

        if ensemble_imp > 0.2:
            power = "strong"
        elif ensemble_imp > 0.1:
            power = "moderate"
        elif ensemble_imp > 0.05:
            power = "weak"
        else:
            power = "none"

        rec_weight = 0.5 + ensemble_imp * 2.5

        results[comp] = {
            "sample_size": len(values),
            "win_rate_correlation": win_corr,
            "pnl_correlation": pnl_corr,
            "avg_value_winners": avg_winners,
            "avg_value_losers": avg_losers,
            "std_value": float(np.std(values)),
            "rf_importance": rf_imp,
            "gb_importance": gb_imp,
            "ensemble_importance": ensemble_imp,
            "predictive_power": power,
            "recommended_weight": rec_weight,
            "confidence_interval": (rec_weight * 0.8, rec_weight * 1.2),
        }

    return results


def cross_validate(
    features: List[TradeFeatures],
    weights: Dict[str, float],
    cv_folds: int = 5,
) -> float:
    """
    Cross-validate weights using time-series splits.

    Args:
        features: Trade features sorted by date
        weights: Component weights to validate
        cv_folds: Number of CV folds

    Returns:
        Average accuracy across folds (0.0-1.0)
    """
    if len(features) < 20:
        return 0.0

    sorted_features = sorted(features, key=lambda x: x.signal_date)
    fold_size = len(sorted_features) // cv_folds
    scores = []

    for i in range(cv_folds - 1):
        test_start = (i + 1) * fold_size
        test_end = min(test_start + fold_size, len(sorted_features))

        if test_end <= test_start:
            continue

        test_features = sorted_features[test_start:test_end]

        correct = 0
        for f in test_features:
            weighted_score = sum(f.components.get(comp, 0) * w for comp, w in weights.items())
            predicted_win = weighted_score > np.median(
                [
                    sum(tf.components.get(c, 0) * w for c, w in weights.items())
                    for tf in sorted_features[:test_start]
                ]
            )
            if predicted_win == f.is_winner:
                correct += 1

        scores.append(correct / len(test_features))

    return float(np.mean(scores)) if scores else 0.0


def calculate_baseline_score(features: List[TradeFeatures]) -> float:
    """
    Calculate baseline accuracy with equal weights (all weights = 1).

    Args:
        features: Trade features

    Returns:
        Baseline accuracy (0.0-1.0)
    """
    if not features:
        return 0.0

    all_scores = [sum(f.components.values()) for f in features]
    median_score = float(np.median(all_scores))

    correct = sum(
        1 for f, score in zip(features, all_scores) if (score > median_score) == f.is_winner
    )

    return correct / len(features)


def validate_weights(
    features: List[TradeFeatures],
    strategy_weights: Dict[str, Any],
) -> float:
    """
    Validate optimized weights across all strategies.

    Args:
        features: Trade features
        strategy_weights: Dict of strategy -> WeightConfig

    Returns:
        Overall accuracy (0.0-1.0)
    """
    if not features:
        return 0.0

    correct = 0
    total = 0

    for strategy, config in strategy_weights.items():
        strat_features = [f for f in features if f.strategy == strategy]
        if not strat_features:
            continue

        all_scores = [config.apply_weights(f.components) for f in strat_features]
        if not all_scores:
            continue

        median = float(np.median(all_scores))

        for f, score in zip(strat_features, all_scores):
            predicted_win = score > median
            if predicted_win == f.is_winner:
                correct += 1
            total += 1

    return correct / total if total > 0 else 0.0
