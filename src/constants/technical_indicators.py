# OptionPlay - Technical Indicator Constants
# ==========================================
# All parameters for technical indicators.
#
# These values have been extracted from the codebase and centralized here.
# Changes here affect all analyzers.

from dataclasses import dataclass
from typing import Tuple

# =============================================================================
# MOVING AVERAGES
# =============================================================================

# Simple Moving Averages (SMA)
SMA_SHORT = 20  # Short-term trend
SMA_MEDIUM = 50  # Medium-term trend
SMA_LONG = 200  # Long-term trend

# Exponential Moving Average
EMA_MULTIPLIER = 2  # Standard EMA multiplier: 2 / (period + 1)


# =============================================================================
# ATR (AVERAGE TRUE RANGE)
# =============================================================================

ATR_PERIOD = 14  # Standard ATR period


# =============================================================================
# RSI (RELATIVE STRENGTH INDEX)
# =============================================================================

RSI_PERIOD = 14  # Standard RSI period

# Threshold Levels
RSI_OVERSOLD = 30  # Oversold (buy signal)
RSI_OVERBOUGHT = 70  # Overbought (sell signal)
RSI_NEUTRAL_LOW = 40  # Neutral zone lower bound
RSI_NEUTRAL_HIGH = 60  # Neutral zone upper bound

# Strategy-specific RSI Thresholds
RSI_OVERSOLD_AGGRESSIVE = 35  # Less strict for pullbacks
RSI_OVERBOUGHT_FILTER = 80  # Maximum for ATH Breakout filter


# =============================================================================
# MACD (MOVING AVERAGE CONVERGENCE/DIVERGENCE)
# =============================================================================

MACD_FAST = 12  # Fast EMA period
MACD_SLOW = 26  # Slow EMA period
MACD_SIGNAL = 9  # Signal line period


# =============================================================================
# STOCHASTIC OSCILLATOR
# =============================================================================

STOCH_K_PERIOD = 14  # %K period
STOCH_D_PERIOD = 3  # %D period (smoothing of %K)
STOCH_SMOOTH = 3  # Additional smoothing

# Threshold Levels
STOCH_OVERSOLD = 20  # Oversold
STOCH_OVERBOUGHT = 80  # Overbought


# =============================================================================
# KELTNER CHANNELS
# =============================================================================

KELTNER_ATR_MULTIPLIER = 2.0  # ATR multiplier for channels

# Position within channels (-1 = lower band, +1 = upper band)
KELTNER_LOWER_THRESHOLD = -0.5  # Near lower band (bullish)
KELTNER_UPPER_THRESHOLD = 0.5  # Near upper band (bearish)
KELTNER_NEUTRAL_LOW = -0.3  # Slightly below center


# =============================================================================
# FIBONACCI RETRACEMENT
# =============================================================================

# Standard Fibonacci Levels
FIB_LEVELS: Tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 0.786)

# Lookback for Swing High/Low detection
FIB_LOOKBACK_DAYS = 20


# =============================================================================
# VOLUME ANALYSIS
# =============================================================================

VOLUME_AVG_PERIOD = 20  # Average over 20 days
VOLUME_RECENT_WINDOW = 5  # Last 5 days for trend

# Volume Trend Thresholds (ratio to average)
VOLUME_TREND_LOW = 0.7  # Below 70% = declining volume
VOLUME_TREND_HIGH = 1.3  # Above 130% = rising volume

# Volume Spike Detection
VOLUME_SPIKE_MULTIPLIER = 2.0  # 2x average = spike


# =============================================================================
# VWAP (VOLUME WEIGHTED AVERAGE PRICE)
# =============================================================================

VWAP_PERIOD = 20  # Standard VWAP period

# Distance Thresholds (in percent)
VWAP_STRONG_ABOVE = 3.0  # Strongly above VWAP
VWAP_ABOVE = 1.0  # Above VWAP
VWAP_BELOW = -1.0  # Below VWAP
VWAP_STRONG_BELOW = -3.0  # Strongly below VWAP


# =============================================================================
# SUPPORT / RESISTANCE
# =============================================================================

SUPPORT_LOOKBACK_DAYS = 60  # Lookback for support level detection
SUPPORT_WINDOW = 5  # Window for local minima
SUPPORT_MAX_LEVELS = 5  # Maximum number of support levels
SUPPORT_TOLERANCE_PCT = 1.5  # Tolerance for support clustering (%)

# Extended Lookback for long-term S/R
SR_LOOKBACK_DAYS_EXTENDED = 252  # 1 year for significant levels


# =============================================================================
# RSI DIVERGENCE DETECTION
# =============================================================================

DIVERGENCE_SWING_WINDOW = 3  # Window for swing detection
DIVERGENCE_MIN_BARS = 5  # Minimum bars between swings
DIVERGENCE_MAX_BARS = 50  # Maximum bars between swings

# Divergence Strength Thresholds
DIVERGENCE_STRENGTH_STRONG = 0.7  # Strong divergence
DIVERGENCE_STRENGTH_MODERATE = 0.4  # Moderate divergence


# =============================================================================
# GAP ANALYSIS
# =============================================================================

GAP_LOOKBACK_DAYS = 60  # Lookback for gap search
GAP_WINDOW = 3  # Window for gap confirmation
GAP_MIN_PCT = 2.0  # Minimum gap size (%)
GAP_FILL_THRESHOLD = 50.0  # Gap fill threshold (%)

# Gap Size Classification (%)
GAP_SIZE_LARGE = 3.0  # Large gap
GAP_SIZE_MEDIUM = 1.0  # Medium gap
GAP_SIZE_SMALL_NEG = -0.3  # Small negative gap
GAP_SIZE_LARGE_NEG = -3.0  # Large negative gap


# =============================================================================
# CONVENIENCE CLASS
# =============================================================================


@dataclass(frozen=True)
class TechnicalIndicators:
    """
    Grouped technical indicator constants.

    Usage:
        from src.constants import TechnicalIndicators as TI
        rsi = calculate_rsi(prices, TI.RSI_PERIOD)
    """

    # Moving Averages
    SMA_SHORT: int = SMA_SHORT
    SMA_MEDIUM: int = SMA_MEDIUM
    SMA_LONG: int = SMA_LONG

    # ATR
    ATR_PERIOD: int = ATR_PERIOD

    # RSI
    RSI_PERIOD: int = RSI_PERIOD
    RSI_OVERSOLD: int = RSI_OVERSOLD
    RSI_OVERBOUGHT: int = RSI_OVERBOUGHT

    # MACD
    MACD_FAST: int = MACD_FAST
    MACD_SLOW: int = MACD_SLOW
    MACD_SIGNAL: int = MACD_SIGNAL

    # Stochastic
    STOCH_K: int = STOCH_K_PERIOD
    STOCH_D: int = STOCH_D_PERIOD
    STOCH_OVERSOLD: int = STOCH_OVERSOLD
    STOCH_OVERBOUGHT: int = STOCH_OVERBOUGHT

    # Volume
    VOLUME_AVG_PERIOD: int = VOLUME_AVG_PERIOD
    VOLUME_SPIKE_MULTIPLIER: float = VOLUME_SPIKE_MULTIPLIER

    # Support/Resistance
    SUPPORT_LOOKBACK: int = SUPPORT_LOOKBACK_DAYS
    SUPPORT_TOLERANCE: float = SUPPORT_TOLERANCE_PCT
