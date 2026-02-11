# OptionPlay - Scoring & Threshold Constants
# ==========================================
# Thresholds for scoring, filtering and classification.
#
# NOTE: Technical indicator parameters are in technical_indicators.py
# NOTE: Risk management parameters (DTE, Delta, Spread) are in risk_management.py
#
# Stability and win-rate values are based on training from 2026-01-31.

from dataclasses import dataclass

from .trading_rules import (
    BLACKLIST_STABILITY_THRESHOLD,
    ENTRY_IV_RANK_MAX,
    ENTRY_IV_RANK_MIN,
    SPREAD_MIN_CREDIT_PCT,
    VIX_DANGER_ZONE_MAX,
    VIX_ELEVATED_MAX,
    VIX_LOW_VOL_MAX,
    VIX_NO_TRADING_THRESHOLD,
    VIX_NORMAL_MAX,
)

# =============================================================================
# SCORE THRESHOLDS
# =============================================================================

# Signal Strength Classification (normalized 0-10 scale)
SCORE_STRONG_THRESHOLD = 7.0  # Strong signal
SCORE_MODERATE_THRESHOLD = 5.0  # Moderate signal
SCORE_WEAK_THRESHOLD = 3.0  # Weak signal

# Minimum Scores for filtering
MIN_SCORE_DEFAULT = 3.5  # Standard minimum for candidates
MIN_ACTIONABLE_SCORE = 5.0  # Minimum for immediate action


# =============================================================================
# CREDIT REQUIREMENTS (for spread evaluation)
# =============================================================================

MIN_CREDIT_PCT = SPREAD_MIN_CREDIT_PCT  # Delegiert an trading_rules (PLAYBOOK §2: 10%)
TARGET_CREDIT_PCT = 30.0  # Target credit percentage

# OTM Extensions (beyond risk_management.py targets)
OTM_IDEAL_PCT = 12.0  # Ideal OTM percentage
OTM_MAX_PCT = 25.0  # Maximum OTM percentage


# =============================================================================
# VIX TREND Z-SCORE THRESHOLDS
# =============================================================================

VIX_ZSCORE_RISING_FAST = 1.5  # Z-score for rapidly rising VIX
VIX_ZSCORE_RISING = 0.75  # Z-score for rising VIX
VIX_ZSCORE_FALLING = -0.75  # Z-score for falling VIX
VIX_ZSCORE_FALLING_FAST = -1.5  # Z-score for rapidly falling VIX


# =============================================================================
# POSITION SIZING MODIFIERS
# =============================================================================

POSITION_SIZE_DANGER_ZONE = 0.75  # Position size factor in danger zone


# =============================================================================
# STABILITY THRESHOLDS (from backtest data)
# =============================================================================

# Symbol Stability Scores (0-100)
STABILITY_PREMIUM = 80.0  # Premium symbols (highest reliability)
STABILITY_GOOD = 70.0  # Good symbols
STABILITY_OK = 50.0  # Acceptable symbols
STABILITY_BLACKLIST = BLACKLIST_STABILITY_THRESHOLD  # Delegiert an trading_rules (PLAYBOOK §7: 40)

# Corresponding score thresholds for stability-first filter
STABILITY_PREMIUM_MIN_SCORE = 4.0  # Premium can have lower score
STABILITY_GOOD_MIN_SCORE = 5.0  # Good needs standard score
STABILITY_OK_MIN_SCORE = 6.0  # OK needs higher score


# =============================================================================
# WIN RATE THRESHOLDS (from training 2026-01-31)
# =============================================================================

# Historical win rates based on stability
WIN_RATE_PREMIUM = 94.5  # Stability >= 80
WIN_RATE_GOOD = 86.1  # Stability 70-80
WIN_RATE_OK = 75.0  # Stability 50-70
WIN_RATE_BLACKLIST = 66.0  # Stability < 50


# =============================================================================
# VIX REGIME THRESHOLDS
# =============================================================================

# VIX Level Classification (PLAYBOOK §3) — delegiert an trading_rules
VIX_LOW = VIX_LOW_VOL_MAX  # Low Vol boundary (PLAYBOOK: 15)
VIX_NORMAL = VIX_NORMAL_MAX  # Normal/Danger Zone boundary (PLAYBOOK: 20)
VIX_ELEVATED = VIX_DANGER_ZONE_MAX  # Danger Zone/Elevated boundary (PLAYBOOK: 25)
VIX_HIGH = VIX_ELEVATED_MAX  # Elevated/High Vol boundary (PLAYBOOK: 30)
VIX_NO_TRADING = VIX_NO_TRADING_THRESHOLD  # No trading above this (PLAYBOOK: 35)
VIX_EXTREME = 40.0  # Extreme volatility (defensive, no PLAYBOOK constant)


# =============================================================================
# IV RANK THRESHOLDS
# =============================================================================

# IV Rank for credit spreads (0-100)
# PLAYBOOK §1: IV Rank 30-80% (weicher Filter, WARNING)
IV_RANK_MIN = ENTRY_IV_RANK_MIN  # Delegiert an trading_rules (PLAYBOOK §1: 30)
IV_RANK_MAX = ENTRY_IV_RANK_MAX  # Delegiert an trading_rules (PLAYBOOK §1: 80)

# Optimal range
IV_RANK_OPTIMAL_LOW = ENTRY_IV_RANK_MIN  # Lower bound optimal (same as minimum)
IV_RANK_OPTIMAL_HIGH = 60.0  # Upper bound optimal


# =============================================================================
# RELIABILITY GRADES
# =============================================================================

# Minimum reliability grade for recommendations
RELIABILITY_MIN_GRADE = "D"  # D or better accepted

# Grade win rate ranges (for display)
RELIABILITY_GRADE_A_MIN_WR = 90.0
RELIABILITY_GRADE_B_MIN_WR = 80.0
RELIABILITY_GRADE_C_MIN_WR = 70.0
RELIABILITY_GRADE_D_MIN_WR = 60.0


# =============================================================================
# MARKET CONTEXT THRESHOLDS
# =============================================================================

# SPY Trend Detection
MARKET_UPTREND_SMA_RATIO = 1.0  # Price above SMA = uptrend
MARKET_DOWNTREND_SMA_RATIO = 1.0  # Price below SMA = downtrend

# Sector Correlation
SECTOR_CORRELATION_HIGH = 0.7  # High correlation with SPY
SECTOR_CORRELATION_LOW = 0.3  # Low correlation


# =============================================================================
# CONVENIENCE CLASS
# =============================================================================


@dataclass(frozen=True)
class Thresholds:
    """
    Grouped threshold constants for scoring and classification.

    NOTE: For technical indicators, use TechnicalIndicators from technical_indicators.py
    NOTE: For risk management (DTE, Delta), use RiskManagement from risk_management.py

    Usage:
        from src.constants import Thresholds
        if signal.score >= Thresholds.SCORE_STRONG:
            ...
    """

    # Scores
    SCORE_STRONG: float = SCORE_STRONG_THRESHOLD
    SCORE_MODERATE: float = SCORE_MODERATE_THRESHOLD
    SCORE_WEAK: float = SCORE_WEAK_THRESHOLD
    MIN_SCORE: float = MIN_SCORE_DEFAULT

    # Stability
    STABILITY_PREMIUM: float = STABILITY_PREMIUM
    STABILITY_GOOD: float = STABILITY_GOOD
    STABILITY_OK: float = STABILITY_OK

    # VIX Regimes
    VIX_LOW: float = VIX_LOW
    VIX_NORMAL: float = VIX_NORMAL
    VIX_ELEVATED: float = VIX_ELEVATED
    VIX_HIGH: float = VIX_HIGH

    # IV Rank
    IV_RANK_MIN: float = IV_RANK_MIN
    IV_RANK_MAX: float = IV_RANK_MAX

    # Credit Requirements
    MIN_CREDIT: float = MIN_CREDIT_PCT
    TARGET_CREDIT: float = TARGET_CREDIT_PCT
