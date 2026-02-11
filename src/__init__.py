# OptionPlay - Options Trading Analysis System
# =============================================
#
# Refactored Package Structure (v4.0.0):
#
#   src/
#   ├── models/          # Dataclasses (TradeSignal, Indicators, etc.)
#   ├── analyzers/       # Strategy Analyzers (Pullback, Breakout, etc.)
#   ├── indicators/      # Technical Indicators (RSI, MACD, etc.)
#   ├── options/         # Options-specific tools (Max Pain, VIX)
#   ├── providers/       # Data Providers (Tradier)
#   ├── cache/           # Caching (Earnings, IV)
#   ├── config/          # Configuration
#   └── scanner/         # Multi-Strategy Scanner
#
# For backwards compatibility, all public symbols are re-exported here.

__version__ = "4.0.0"

# =============================================================================
# ANALYZERS
# =============================================================================
from .analyzers import (
    BaseAnalyzer,
    PullbackAnalyzer,
)

# =============================================================================
# CACHE
# =============================================================================
from .cache import (
    EarningsCache,
    EarningsFetcher,
    HistoricalIVFetcher,
    IVCache,
    IVFetcher,
    calculate_iv_percentile,
    calculate_iv_rank,
    fetch_iv_history,
    get_earnings,
    get_earnings_cache,
    get_earnings_fetcher,
    get_historical_iv_fetcher,
    get_iv_cache,
    get_iv_fetcher,
    get_iv_rank,
    is_earnings_safe,
    is_iv_elevated,
    update_iv_cache,
)

# =============================================================================
# CONFIG (backwards compatible imports)
# =============================================================================
from .config import (
    ConfigLoader,
    FilterConfig,
    OptionsConfig,
    PullbackScoringConfig,
    Settings,
    WatchlistLoader,
    get_config,
    get_watchlist_loader,
)

# =============================================================================
# PROVIDERS
# =============================================================================
from .data_providers import (
    DataProvider,
    TradierConfig,
    TradierProvider,
)

# =============================================================================
# INDICATORS (new standalone functions)
# =============================================================================
from .indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_fibonacci,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    calculate_stochastic,
    find_resistance_levels,
    find_support_levels,
)

# =============================================================================
# MODELS
# =============================================================================
from .models import (  # Base; Indicators; Candidates; Options; Market Data
    EarningsInfo,
    EarningsSource,
    IVData,
    IVSource,
    MACDResult,
    MaxPainResult,
    PullbackCandidate,
    ScoreBreakdown,
    SignalStrength,
    SignalType,
    StochasticResult,
    StrikePainData,
    StrikeQuality,
    StrikeRecommendation,
    SupportLevel,
    TechnicalIndicators,
    TradeSignal,
)

# =============================================================================
# OPTIONS
# =============================================================================
from .options import (
    MarketRegime,
    MaxPainCalculator,
    StrategyRecommendation,
    StrikeRecommender,
    VIXStrategySelector,
    VIXThresholds,
    calculate_max_pain,
    calculate_strike_recommendation,
    format_max_pain_report,
    format_recommendation,
    get_strategy_for_vix,
)

# =============================================================================
# SCANNER
# =============================================================================
from .scanner import (
    MarketScanner,
    SignalAggregator,
)

# =============================================================================
# ALL EXPORTS
# =============================================================================
__all__ = [
    # Version
    "__version__",
    # Models - Base
    "TradeSignal",
    "SignalType",
    "SignalStrength",
    # Models - Indicators
    "MACDResult",
    "StochasticResult",
    "TechnicalIndicators",
    # Models - Candidates
    "PullbackCandidate",
    "ScoreBreakdown",
    "SupportLevel",
    # Models - Options
    "MaxPainResult",
    "StrikePainData",
    "StrikeRecommendation",
    "StrikeQuality",
    # Models - Market Data
    "EarningsInfo",
    "EarningsSource",
    "IVData",
    "IVSource",
    # Config
    "ConfigLoader",
    "get_config",
    "Settings",
    "PullbackScoringConfig",
    "FilterConfig",
    "OptionsConfig",
    "WatchlistLoader",
    "get_watchlist_loader",
    # Analyzers
    "BaseAnalyzer",
    "PullbackAnalyzer",
    # Options
    "MaxPainCalculator",
    "calculate_max_pain",
    "format_max_pain_report",
    "StrikeRecommender",
    "calculate_strike_recommendation",
    "VIXStrategySelector",
    "MarketRegime",
    "VIXThresholds",
    "StrategyRecommendation",
    "get_strategy_for_vix",
    "format_recommendation",
    # Cache
    "EarningsCache",
    "EarningsFetcher",
    "get_earnings_cache",
    "get_earnings_fetcher",
    "get_earnings",
    "is_earnings_safe",
    "IVCache",
    "IVFetcher",
    "calculate_iv_rank",
    "calculate_iv_percentile",
    "get_iv_cache",
    "get_iv_fetcher",
    "get_iv_rank",
    "is_iv_elevated",
    "HistoricalIVFetcher",
    "get_historical_iv_fetcher",
    "fetch_iv_history",
    "update_iv_cache",
    # Providers
    "DataProvider",
    "TradierProvider",
    "TradierConfig",
    # Scanner
    "MarketScanner",
    "SignalAggregator",
    # Indicators
    "calculate_rsi",
    "calculate_macd",
    "calculate_stochastic",
    "calculate_sma",
    "calculate_ema",
    "calculate_atr",
    "calculate_bollinger_bands",
    "find_support_levels",
    "find_resistance_levels",
    "calculate_fibonacci",
    # Dependency Injection
    "ServiceContainer",
    "get_container",
    "set_container",
    "reset_container",
]

# =============================================================================
# DEPENDENCY INJECTION CONTAINER
# =============================================================================
from .container import (
    ServiceContainer,
    get_container,
    reset_container,
    set_container,
)
