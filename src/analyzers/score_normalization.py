# OptionPlay - Score Normalization
# ==================================
# Central normalization for all strategy scores
#
# Problem: Different strategies have different max scores
# - Pullback: max 26 points
# - Bounce: max 27 points
# - ATH Breakout: max 23 points
# - Earnings Dip: max 21 points
#
# Solution: Normalize all scores to 0-10 scale for direct comparability

from dataclasses import dataclass
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class StrategyScoreConfig:
    """Configuration for a strategy's scoring system."""
    max_possible: float
    # Thresholds for signal strength (on normalized 0-10 scale)
    strong_threshold: float = 7.0
    moderate_threshold: float = 5.0
    weak_threshold: float = 3.0


# =============================================================================
# STRATEGY SCORE CONFIGURATIONS
# =============================================================================

STRATEGY_SCORE_CONFIGS: Dict[str, StrategyScoreConfig] = {
    'pullback': StrategyScoreConfig(
        max_possible=26.0,
        # Component breakdown:
        # RSI: 3, RSI Divergence: 3, Support: 2.5, Fibonacci: 2,
        # MA: 2, Trend: 2, Volume: 2, MACD: 2, Stoch: 2, Keltner: 2,
        # VWAP: 3, Market Context: 2, Sector: 1, Gap: 1
        strong_threshold=7.0,
        moderate_threshold=5.0,
        weak_threshold=3.0,
    ),
    'bounce': StrategyScoreConfig(
        max_possible=27.0,
        # Component breakdown:
        # Support: 3, RSI: 3, RSI Divergence: 3, Candlestick: 3,
        # Volume: 2, Trend: 2, MACD: 2, Stoch: 2, Keltner: 2,
        # VWAP: 3, Market Context: 2, Sector: 1, Gap: 1
        strong_threshold=7.0,
        moderate_threshold=5.0,
        weak_threshold=3.0,
    ),
    'ath_breakout': StrategyScoreConfig(
        max_possible=23.0,
        # Component breakdown:
        # ATH Score: 4, Volume: 3, Trend: 2, RS: 2, Momentum: 3,
        # Candlestick: 2, VWAP: 3, Market Context: 2, Sector: 1, Gap: 1
        strong_threshold=7.0,
        moderate_threshold=5.0,
        weak_threshold=3.0,
    ),
    'earnings_dip': StrategyScoreConfig(
        max_possible=21.0,
        # Component breakdown:
        # Dip Magnitude: 3, Quality: 3, Stabilization: 3, Support: 2,
        # Volume: 2, RSI: 2, VWAP: 3, Market Context: 2, Sector: 1
        strong_threshold=7.0,
        moderate_threshold=5.0,
        weak_threshold=3.0,
    ),
}


def normalize_score(raw_score: float, strategy: str) -> float:
    """
    Normalize a raw strategy score to a 0-10 scale.

    Args:
        raw_score: The raw score from the strategy analyzer
        strategy: Strategy name ('pullback', 'bounce', 'ath_breakout', 'earnings_dip')

    Returns:
        Normalized score on 0-10 scale
    """
    config = STRATEGY_SCORE_CONFIGS.get(strategy)
    if not config:
        logger.warning(f"Unknown strategy '{strategy}', using raw score")
        return raw_score

    if config.max_possible <= 0:
        return 0.0

    # Normalize to 0-10 scale
    normalized = (raw_score / config.max_possible) * 10.0

    # Clamp to 0-10 range
    return max(0.0, min(10.0, normalized))


def denormalize_score(normalized_score: float, strategy: str) -> float:
    """
    Convert a normalized 0-10 score back to the strategy's raw scale.

    Args:
        normalized_score: Score on 0-10 scale
        strategy: Strategy name

    Returns:
        Raw score in strategy's native scale
    """
    config = STRATEGY_SCORE_CONFIGS.get(strategy)
    if not config:
        return normalized_score

    return (normalized_score / 10.0) * config.max_possible


def get_signal_strength(
    normalized_score: float,
    strategy: str = 'pullback'
) -> str:
    """
    Determine signal strength based on normalized score.

    Args:
        normalized_score: Score on 0-10 scale
        strategy: Strategy name (for custom thresholds)

    Returns:
        'STRONG', 'MODERATE', 'WEAK', or 'NONE'
    """
    config = STRATEGY_SCORE_CONFIGS.get(strategy, STRATEGY_SCORE_CONFIGS['pullback'])

    if normalized_score >= config.strong_threshold:
        return 'STRONG'
    elif normalized_score >= config.moderate_threshold:
        return 'MODERATE'
    elif normalized_score >= config.weak_threshold:
        return 'WEAK'
    else:
        return 'NONE'


def get_max_possible(strategy: str) -> float:
    """
    Get the maximum possible raw score for a strategy.

    Args:
        strategy: Strategy name

    Returns:
        Maximum possible raw score
    """
    config = STRATEGY_SCORE_CONFIGS.get(strategy)
    if config:
        return config.max_possible
    return 10.0  # Default fallback


def compare_scores(
    scores: Dict[str, float],
    normalize: bool = True
) -> Dict[str, float]:
    """
    Compare scores across different strategies.

    Args:
        scores: Dict of {strategy: raw_score}
        normalize: If True, normalize all scores to 0-10 scale

    Returns:
        Dict of {strategy: comparable_score}
    """
    if not normalize:
        return scores

    return {
        strategy: normalize_score(score, strategy)
        for strategy, score in scores.items()
    }


class ScoreNormalizer:
    """
    Utility class for score normalization.

    Provides instance-based access to normalization functions
    with optional custom configurations.
    """

    def __init__(self, custom_configs: Optional[Dict[str, StrategyScoreConfig]] = None):
        """
        Initialize with optional custom configurations.

        Args:
            custom_configs: Override default strategy configurations
        """
        self.configs = {**STRATEGY_SCORE_CONFIGS}
        if custom_configs:
            self.configs.update(custom_configs)

    def normalize(self, raw_score: float, strategy: str) -> float:
        """Normalize a score to 0-10 scale."""
        config = self.configs.get(strategy)
        if not config:
            return raw_score

        normalized = (raw_score / config.max_possible) * 10.0
        return max(0.0, min(10.0, normalized))

    def get_strength(self, normalized_score: float, strategy: str) -> str:
        """Get signal strength for a normalized score."""
        config = self.configs.get(strategy, self.configs.get('pullback'))
        if not config:
            return 'NONE'

        if normalized_score >= config.strong_threshold:
            return 'STRONG'
        elif normalized_score >= config.moderate_threshold:
            return 'MODERATE'
        elif normalized_score >= config.weak_threshold:
            return 'WEAK'
        return 'NONE'

    def rank_candidates(
        self,
        candidates: list,
        score_attr: str = 'score'
    ) -> list:
        """
        Rank candidates by normalized score for cross-strategy comparison.

        Args:
            candidates: List of candidate objects with score and strategy attributes
            score_attr: Name of the score attribute

        Returns:
            Sorted list with normalized_score added to each candidate
        """
        ranked = []
        for c in candidates:
            raw_score = getattr(c, score_attr, 0)
            strategy = getattr(c, 'strategy', 'pullback')
            normalized = self.normalize(raw_score, strategy)
            ranked.append((normalized, c))

        ranked.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked]
