# OptionPlay - Analyzers Package
# ================================
# Strategie-Analyzer für verschiedene Trading-Setups

from .base import BaseAnalyzer
from .context import AnalysisContext
from .pullback import PullbackAnalyzer
from .ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from .bounce import BounceAnalyzer, BounceConfig
from .earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
from .pool import (
    AnalyzerPool,
    PoolConfig,
    PoolStats,
    get_analyzer_pool,
    reset_analyzer_pool,
    configure_default_pool,
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

    # Configs
    'ATHBreakoutConfig',
    'BounceConfig',
    'EarningsDipConfig',

    # Pool
    'AnalyzerPool',
    'PoolConfig',
    'PoolStats',
    'get_analyzer_pool',
    'reset_analyzer_pool',
    'configure_default_pool',
]
