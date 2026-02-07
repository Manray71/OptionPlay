#!/usr/bin/env python3
"""
Weighted Scorer for Production Use

Extracted from ml_weight_optimizer.py for modularity.
Contains: WeightedScorer class
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class WeightedScorer:
    """
    Production scorer that applies optimized weights.

    Usage:
        scorer = WeightedScorer.load_latest()
        weighted_score = scorer.score(score_breakdown, strategy="pullback")
    """

    def __init__(self, optimization_result=None):
        """
        Initialize scorer.

        Args:
            optimization_result: OptimizationResult from MLWeightOptimizer
        """
        self._result = optimization_result
        from .ml_weight_optimizer import DEFAULT_WEIGHTS
        self._default_weights = DEFAULT_WEIGHTS.copy()

    def score(
        self,
        score_breakdown: Dict[str, float],
        strategy: str = "pullback",
        regime: Optional[str] = None,
        vix: Optional[float] = None,
    ) -> float:
        """
        Calculate weighted score.

        Args:
            score_breakdown: Dict of component scores
            strategy: Strategy name
            regime: Optional regime override
            vix: Optional VIX for auto-regime detection

        Returns:
            Weighted total score
        """
        # Determine regime from VIX if not specified
        if regime is None and vix is not None:
            if vix < 15:
                regime = "low_vol"
            elif vix < 20:
                regime = "normal"
            elif vix < 30:
                regime = "elevated"
            else:
                regime = "high_vol"

        if self._result is None:
            # No optimization loaded - use raw scores
            return sum(score_breakdown.values())

        # Get weight config
        config = self._result.get_weights(strategy, regime)
        return config.apply_weights(score_breakdown)

    def get_weight_info(
        self,
        strategy: str,
        regime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get information about weights being used"""
        if self._result is None:
            return {
                "status": "default",
                "message": "No optimization loaded - using equal weights",
            }

        config = self._result.get_weights(strategy, regime)
        return {
            "status": "optimized",
            "strategy": config.strategy,
            "regime": config.regime,
            "method": config.method.value,
            "confidence": config.confidence,
            "validation_score": config.validation_score,
            "top_weights": dict(sorted(
                config.weights.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]),
        }

    @classmethod
    def load_latest(cls) -> "WeightedScorer":
        """Load scorer with latest optimization"""
        from .ml_weight_optimizer import MLWeightOptimizer
        result = MLWeightOptimizer.load_latest()
        return cls(result)

    @classmethod
    def from_file(cls, filepath: str) -> "WeightedScorer":
        """Load scorer from specific file"""
        from .ml_weight_optimizer import MLWeightOptimizer
        result = MLWeightOptimizer.load(filepath)
        return cls(result)
