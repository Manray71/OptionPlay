# OptionPlay - Indicators Package
# =================================
# Wiederverwendbare technische Indikatoren

from .divergence import (
    DivergenceSignal,
    check_cmf_and_macd_falling,
    check_cmf_early_warning,
    check_distribution_pattern,
    check_momentum_divergence,
    check_price_mfi_divergence,
    check_price_obv_divergence,
    check_price_rsi_divergence,
)
from .gap_analysis import (
    analyze_gap,
    calculate_gap_series,
    calculate_gap_statistics,
    detect_gap,
    gap_type_to_score_factor,
    get_gap_description,
    is_significant_gap,
)
from .momentum import (
    calculate_cmf_series,
    calculate_macd,
    calculate_macd_series,
    calculate_mfi_series,
    calculate_obv_series,
    calculate_rsi,
    calculate_rsi_divergence,
    calculate_rsi_series,
    calculate_stochastic,
    find_swing_highs,
    find_swing_lows,
)
from .support_resistance import calculate_fibonacci, find_resistance_levels, find_support_levels
from .trend import calculate_adx, calculate_ema, calculate_sma
from .volatility import (
    calculate_atr,
    calculate_atr_simple,
    calculate_bollinger_bands,
    calculate_keltner_channel,
)
from .volume_profile import (
    MarketContextResult,
    VolumeProfileResult,
    VWAPResult,
    calculate_spy_trend,
    calculate_volume_profile_poc,
    calculate_vwap,
    get_sector,
    get_sector_adjustment,
)

__all__ = [
    # Divergence checks
    "DivergenceSignal",
    "check_price_rsi_divergence",
    "check_price_obv_divergence",
    "check_price_mfi_divergence",
    "check_cmf_and_macd_falling",
    "check_momentum_divergence",
    "check_distribution_pattern",
    "check_cmf_early_warning",
    # Momentum
    "calculate_rsi",
    "calculate_rsi_series",
    "calculate_macd",
    "calculate_macd_series",
    "calculate_stochastic",
    "calculate_rsi_divergence",
    "find_swing_lows",
    "find_swing_highs",
    # Volume indicators
    "calculate_obv_series",
    "calculate_mfi_series",
    "calculate_cmf_series",
    # Trend
    "calculate_sma",
    "calculate_ema",
    "calculate_adx",
    # Volatility
    "calculate_atr",
    "calculate_atr_simple",
    "calculate_bollinger_bands",
    "calculate_keltner_channel",
    # Support/Resistance
    "find_support_levels",
    "find_resistance_levels",
    "calculate_fibonacci",
    # Volume Profile (NEW from Feature Engineering)
    "calculate_vwap",
    "calculate_volume_profile_poc",
    "calculate_spy_trend",
    "get_sector",
    "get_sector_adjustment",
    "VWAPResult",
    "VolumeProfileResult",
    "MarketContextResult",
    # Gap Analysis
    "detect_gap",
    "analyze_gap",
    "calculate_gap_statistics",
    "calculate_gap_series",
    "gap_type_to_score_factor",
    "is_significant_gap",
    "get_gap_description",
]
