# OptionPlay - Analyzers Package
# ================================
# Strategy analyzers for various trading setups

from .base import BaseAnalyzer
from .bounce import BounceAnalyzer, BounceConfig
from .context import AnalysisContext
from .pool import (
    AnalyzerPool,
    PoolConfig,
    PoolStats,
    configure_default_pool,
    get_analyzer_pool,
    reset_analyzer_pool,
)
from .pullback import PullbackAnalyzer

from .batch_scorer import BatchScorer
from .score_normalization import (
    STRATEGY_SCORE_CONFIGS,
    ScoreNormalizer,
    StrategyScoreConfig,
    clamp_score,
    compare_scores,
    denormalize_score,
    get_max_possible,
    get_signal_strength,
    normalize_score,
)

__all__ = [
    # Base
    "BaseAnalyzer",
    "AnalysisContext",
    # Analyzers
    "PullbackAnalyzer",
    "BounceAnalyzer",
    # Configs
    "BounceConfig",
    # Pool
    "AnalyzerPool",
    "PoolConfig",
    "PoolStats",
    "get_analyzer_pool",
    "reset_analyzer_pool",
    "configure_default_pool",
    # Score Normalization
    "normalize_score",
    "denormalize_score",
    "get_signal_strength",
    "get_max_possible",
    "compare_scores",
    "ScoreNormalizer",
    "StrategyScoreConfig",
    "STRATEGY_SCORE_CONFIGS",
    # BatchScorer
    "BatchScorer",
]
