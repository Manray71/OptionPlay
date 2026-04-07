# OptionPlay - Models Package
# ============================
# Zentrale Dataclasses und Typdefinitionen

from .base import SignalStrength, SignalType, TradeSignal
from .candidates import PullbackCandidate, ScoreBreakdown, SupportLevel
from .indicators import MACDResult, StochasticResult, TechnicalIndicators
from .market_data import EarningsInfo, EarningsSource, IVData, IVSource
from .options import MaxPainResult, StrikePainData, StrikeQuality, StrikeRecommendation
from .result import (
    BatchResult,
    Result,
    ResultStatus,
    ServiceResult,
)
from .strategy import (
    STRATEGY_ICONS,
    STRATEGY_NAMES,
    Strategy,
    get_strategy_display_name,
    get_strategy_icon,
)
from .strategy_breakdowns import (
    BounceScoreBreakdown,
)

__all__ = [
    # Base
    "TradeSignal",
    "SignalType",
    "SignalStrength",
    # Strategy
    "Strategy",
    "STRATEGY_ICONS",
    "STRATEGY_NAMES",
    "get_strategy_icon",
    "get_strategy_display_name",
    # Result Types
    "Result",
    "ServiceResult",
    "BatchResult",
    "ResultStatus",
    # Indicators
    "MACDResult",
    "StochasticResult",
    "TechnicalIndicators",
    # Candidates
    "PullbackCandidate",
    "ScoreBreakdown",
    "SupportLevel",
    # Strategy Breakdowns
    "BounceScoreBreakdown",
    # Options
    "MaxPainResult",
    "StrikePainData",
    "StrikeRecommendation",
    "StrikeQuality",
    # Market Data
    "EarningsInfo",
    "EarningsSource",
    "IVData",
    "IVSource",
]
