# OptionPlay - Strategy Parameter Constants
# =========================================
# Specific parameters for each trading strategy.
#
# These values define the behavior of individual analyzers.

from dataclasses import dataclass

# =============================================================================
# PULLBACK STRATEGY
# =============================================================================

# Trend Requirements
PULLBACK_MIN_UPTREND_DAYS = 20  # Minimum days in uptrend
PULLBACK_SMA_TREND_PERIOD = 50  # SMA for trend confirmation

# Pullback Detection
PULLBACK_MIN_PULLBACK_PCT = 3.0  # Minimum pullback (%)
PULLBACK_MAX_PULLBACK_PCT = 15.0  # Maximum pullback (%)
PULLBACK_LOOKBACK_DAYS = 20  # Lookback for swing high

# Score Bonuses
PULLBACK_VOLUME_CONFIRMATION_BONUS = 1.0
PULLBACK_RSI_OVERSOLD_BONUS = 1.5
PULLBACK_SUPPORT_CONFLUENCE_BONUS = 2.0


# =============================================================================
# ATH BREAKOUT STRATEGY
# =============================================================================

# ATH Detection
ATH_LOOKBACK_DAYS = 252  # 1 year for all-time high
ATH_CONSOLIDATION_DAYS = 20  # Consolidation before breakout

# Breakout Confirmation
ATH_BREAKOUT_THRESHOLD_PCT = 1.0  # Minimum above ATH (%)
ATH_CONFIRMATION_DAYS = 2  # Days for confirmation
ATH_CONFIRMATION_THRESHOLD = 0.5  # Min % above ATH for confirmation

# Additional Filters
ATH_VOLUME_SPIKE_MULTIPLIER = 1.5  # Volume spike at breakout
ATH_RSI_MAX = 80.0  # Max RSI (not overbought)
ATH_MIN_UPTREND_DAYS = 50  # Minimum uptrend before breakout

# Score Bonuses
ATH_VOLUME_CONFIRMATION_BONUS = 2.0
ATH_CLEAN_BREAKOUT_BONUS = 1.5


# =============================================================================
# BOUNCE STRATEGY
# =============================================================================

# Support Detection
BOUNCE_LOOKBACK_DAYS = 60  # Lookback for support levels
BOUNCE_MIN_TOUCHES = 3  # Minimum support touches (was 2, config-driven via scanner_config.yaml)
BOUNCE_PROXIMITY_PCT = 2.0  # Max distance to support (%)

# Bounce Confirmation
BOUNCE_REVERSAL_BARS = 3  # Bars for reversal confirmation
BOUNCE_MIN_BOUNCE_PCT = 1.0  # Minimum bounce (%)

# Score Bonuses
BOUNCE_STRONG_SUPPORT_BONUS = 2.0
BOUNCE_VOLUME_REVERSAL_BONUS = 1.5
BOUNCE_RSI_OVERSOLD_BONUS = 1.0


# =============================================================================
# EARNINGS DIP STRATEGY
# =============================================================================

# Dip Detection
EARNINGS_DIP_MIN_PCT = 5.0  # Minimum dip after earnings (%)
EARNINGS_DIP_MAX_PCT = 25.0  # Maximum dip (above = fundamentally broken)
EARNINGS_DIP_LOOKBACK_DAYS = 5  # Days after earnings for dip

# Entry Requirements
EARNINGS_RSI_OVERSOLD = 35.0  # RSI threshold for oversold

# Risk Management
EARNINGS_STOP_BELOW_LOW_PCT = 3.0  # Stop below dip low (%)
EARNINGS_TARGET_RECOVERY_PCT = 50.0  # Target: 50% recovery of dip

# Gap Analysis
EARNINGS_GAP_MIN_PCT = 2.0  # Minimum gap after earnings (%)
EARNINGS_GAP_FILL_THRESHOLD = 50.0  # Gap fill percentage

# Timing
EARNINGS_MAX_DAYS_SINCE = 10  # Max days since earnings for signal


# =============================================================================
# COMMON STRATEGY PARAMETERS
# =============================================================================

# Trend Confirmation
TREND_SMA_SHORT = 20
TREND_SMA_MEDIUM = 50
TREND_SMA_LONG = 200

# Price Action
MIN_PRICE_FOR_OPTIONS = 10.0  # Minimum price for options trading
MAX_PRICE_FOR_SPREAD = 500.0  # Maximum for standard spreads

# Sector Adjustments
SECTOR_TECH_VOLATILITY_FACTOR = 1.2
SECTOR_UTILITIES_VOLATILITY_FACTOR = 0.8
SECTOR_FINANCIALS_VOLATILITY_FACTOR = 1.1


# =============================================================================
# CONVENIENCE CLASS
# =============================================================================


@dataclass(frozen=True)
class StrategyParameters:
    """
    Grouped strategy parameters.

    Usage:
        from src.constants import StrategyParameters as SP
        if dip_pct >= SP.EARNINGS_DIP_MIN:
            ...
    """

    # Pullback
    PULLBACK_MIN_UPTREND: int = PULLBACK_MIN_UPTREND_DAYS
    PULLBACK_MIN_DIP: float = PULLBACK_MIN_PULLBACK_PCT
    PULLBACK_MAX_DIP: float = PULLBACK_MAX_PULLBACK_PCT

    # ATH Breakout
    ATH_LOOKBACK: int = ATH_LOOKBACK_DAYS
    ATH_THRESHOLD: float = ATH_BREAKOUT_THRESHOLD_PCT
    ATH_VOLUME_SPIKE: float = ATH_VOLUME_SPIKE_MULTIPLIER

    # Bounce
    BOUNCE_LOOKBACK: int = BOUNCE_LOOKBACK_DAYS
    BOUNCE_MIN_TOUCHES: int = BOUNCE_MIN_TOUCHES
    BOUNCE_PROXIMITY: float = BOUNCE_PROXIMITY_PCT

    # Earnings Dip
    EARNINGS_DIP_MIN: float = EARNINGS_DIP_MIN_PCT
    EARNINGS_DIP_MAX: float = EARNINGS_DIP_MAX_PCT
    EARNINGS_RSI: float = EARNINGS_RSI_OVERSOLD
