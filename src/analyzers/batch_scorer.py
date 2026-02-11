# OptionPlay - BatchScorer for Vectorized Scoring
# =================================================
# Replaces per-symbol loop with NumPy matrix multiplication.
#
# Instead of:
#   for symbol in 275_symbols:
#       score = sum(weight_i * component_i)
#
# Does:
#   scores = component_matrix @ weight_vector  # single matmul
#   normalized = (scores / max_possible) * 10   # vectorized

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from ..config.scoring_config import RecursiveConfigResolver, ResolvedWeights
except ImportError:
    from config.scoring_config import RecursiveConfigResolver, ResolvedWeights

logger = logging.getLogger(__name__)


class BatchScorer:
    """
    Vectorized batch scorer for scoring many symbols simultaneously.

    Groups symbols by sector (different weight vectors per sector),
    performs matrix multiplication per group, and assembles results.
    """

    def __init__(self, resolver: Optional[RecursiveConfigResolver] = None) -> None:
        if resolver is None:
            from ..config.scoring_config import get_scoring_resolver

            resolver = get_scoring_resolver()
        self._resolver = resolver

    def score_batch(
        self,
        strategy: str,
        regime: str,
        sectors: List[Optional[str]],
        component_matrix: np.ndarray,
        component_names: List[str],
    ) -> np.ndarray:
        """
        Score a batch of symbols using vectorized matrix multiplication.

        Args:
            strategy: Strategy name (e.g., 'pullback')
            regime: Current VIX regime (e.g., 'normal', 'danger')
            sectors: List of sector names, one per symbol (None for unknown)
            component_matrix: Shape (N, C) - N symbols × C components
            component_names: List of C component names matching matrix columns

        Returns:
            np.ndarray of shape (N,) with normalized scores (0-10 scale)
        """
        n_symbols = component_matrix.shape[0]

        if n_symbols == 0:
            return np.array([], dtype=np.float64)

        # Group symbols by sector for batch processing
        sector_groups: Dict[Optional[str], List[int]] = {}
        for i, sector in enumerate(sectors):
            sector_groups.setdefault(sector, []).append(i)

        scores = np.zeros(n_symbols, dtype=np.float64)

        for sector, indices in sector_groups.items():
            resolved = self._resolver.resolve(strategy, regime, sector)
            weight_vector = resolved.as_numpy_array(component_names)
            max_possible = resolved.max_possible

            # Extract sub-matrix for this sector group
            idx = np.array(indices)
            sub_matrix = component_matrix[idx]

            # Matrix multiplication: (G, C) @ (C,) → (G,)
            raw_scores = sub_matrix @ weight_vector

            # Normalize to 0-10 scale
            if max_possible > 0:
                normalized = (raw_scores / max_possible) * 10.0
            else:
                normalized = raw_scores

            # Clamp to [0, 10]
            normalized = np.clip(normalized, 0.0, 10.0)

            scores[idx] = normalized

        return scores

    def score_single(
        self,
        strategy: str,
        regime: str,
        sector: Optional[str],
        components: Dict[str, float],
    ) -> float:
        """
        Score a single symbol (convenience wrapper).

        Args:
            strategy: Strategy name
            regime: VIX regime
            sector: Sector name (or None)
            components: Dict of {component_name: score}

        Returns:
            Normalized score (0-10 scale)
        """
        resolved = self._resolver.resolve(strategy, regime, sector)

        raw_score = sum(
            resolved.weights.get(comp, 0.0) * value for comp, value in components.items()
        )

        if resolved.max_possible > 0:
            normalized = (raw_score / resolved.max_possible) * 10.0
        else:
            normalized = raw_score

        return max(0.0, min(10.0, normalized))
