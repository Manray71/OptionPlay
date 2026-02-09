# OptionPlay - Analyzers Package
# ================================
# Strategy analyzers for various trading setups

from .base import BaseAnalyzer
from .context import AnalysisContext
from .pullback import PullbackAnalyzer
from .ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from .bounce import BounceAnalyzer, BounceConfig
from .earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
from .trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig
from .pool import (
    AnalyzerPool,
    PoolConfig,
    PoolStats,
    get_analyzer_pool,
    reset_analyzer_pool,
    configure_default_pool,
)
try:
    from .batch_scorer import BatchScorer
except ImportError:
    BatchScorer = None  # type: ignore[assignment,misc]  # optional dependency; None sentinel for availability check
from .score_normalization import (
    normalize_score,
    denormalize_score,
    get_signal_strength,
    get_max_possible,
    compare_scores,
    ScoreNormalizer,
    StrategyScoreConfig,
    STRATEGY_SCORE_CONFIGS,
)

__all__ = [
    # Base
    'BaseAnalyzer',
    'AnalysisContext',

    # Analyzers
    'PullbackAnalyzer',
    'ATHBreakoutAnalyzer',
    'BounceAnalyzer',
    'EarningsDipAnalyzer',
    'TrendContinuationAnalyzer',

    # Configs
    'ATHBreakoutConfig',
    'BounceConfig',
    'EarningsDipConfig',
    'TrendContinuationConfig',

    # Pool
    'AnalyzerPool',
    'PoolConfig',
    'PoolStats',
    'get_analyzer_pool',
    'reset_analyzer_pool',
    'configure_default_pool',

    # Score Normalization
    'normalize_score',
    'denormalize_score',
    'get_signal_strength',
    'get_max_possible',
    'compare_scores',
    'ScoreNormalizer',
    'StrategyScoreConfig',
    'STRATEGY_SCORE_CONFIGS',

    # BatchScorer
    'BatchScorer',
]
