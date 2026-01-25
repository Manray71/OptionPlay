# OptionPlay - Models Package
# ============================
# Zentrale Dataclasses und Typdefinitionen

from .base import TradeSignal, SignalType, SignalStrength
from .strategy import (
    Strategy,
    STRATEGY_ICONS,
    STRATEGY_NAMES,
    get_strategy_icon,
    get_strategy_display_name,
)
from .result import (
    Result,
    ServiceResult,
    BatchResult,
    ResultStatus,
)
from .indicators import (
    MACDResult,
    StochasticResult,
    TechnicalIndicators
)
from .candidates import (
    PullbackCandidate,
    ScoreBreakdown,
    SupportLevel
)
from .options import (
    MaxPainResult,
    StrikePainData,
    StrikeRecommendation,
    StrikeQuality
)
from .market_data import (
    EarningsInfo,
    EarningsSource,
    IVData,
    IVSource
)

__all__ = [
    # Base
    'TradeSignal',
    'SignalType',
    'SignalStrength',
    
    # Strategy
    'Strategy',
    'STRATEGY_ICONS',
    'STRATEGY_NAMES',
    'get_strategy_icon',
    'get_strategy_display_name',
    
    # Result Types
    'Result',
    'ServiceResult',
    'BatchResult',
    'ResultStatus',
    
    # Indicators
    'MACDResult',
    'StochasticResult',
    'TechnicalIndicators',
    
    # Candidates
    'PullbackCandidate',
    'ScoreBreakdown',
    'SupportLevel',
    
    # Options
    'MaxPainResult',
    'StrikePainData',
    'StrikeRecommendation',
    'StrikeQuality',
    
    # Market Data
    'EarningsInfo',
    'EarningsSource',
    'IVData',
    'IVSource',
]
