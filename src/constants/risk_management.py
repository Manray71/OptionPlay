# OptionPlay - Risk Management Constants
# =======================================
# All parameters for risk management and position sizing.
#
# IMPORTANT: Delta is a strategy parameter and must NOT be changed!
# See CLAUDE.md for details.

from dataclasses import dataclass

from .trading_rules import (
    ENTRY_EARNINGS_MIN_DAYS,
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_STOP_LOSS_MULTIPLIER,
    SPREAD_DTE_MAX,
    SPREAD_DTE_MIN,
    SPREAD_DTE_TARGET,
    SPREAD_LONG_DELTA_MAX,
    SPREAD_LONG_DELTA_MIN,
    SPREAD_LONG_DELTA_TARGET,
    SPREAD_SHORT_DELTA_MAX,
    SPREAD_SHORT_DELTA_MIN,
    SPREAD_SHORT_DELTA_TARGET,
)

# =============================================================================
# DTE (DAYS TO EXPIRATION)
# =============================================================================

# Standard DTE Range for Bull-Put-Spreads — delegiert an trading_rules
DTE_MIN = SPREAD_DTE_MIN  # PLAYBOOK §2: 60
DTE_MAX = SPREAD_DTE_MAX  # PLAYBOOK §2: 90
DTE_TARGET = SPREAD_DTE_TARGET  # PLAYBOOK §2: 75

# Strict Limits (for validation)
DTE_MIN_STRICT = SPREAD_DTE_MIN  # Gleich wie DTE_MIN (PLAYBOOK §2: 60)
DTE_MAX_STRICT = 120  # Absolute maximum


# =============================================================================
# DELTA TARGETS
# =============================================================================
# WARNING: These values are part of the strategy and were optimized based on
# historical win rates. Changes invalidate the strategy!

# Short Put Delta (sold) — delegiert an trading_rules
# PLAYBOOK §2: Delta -0.20 ±0.03 — "Delta ist heilig"
DELTA_TARGET = SPREAD_SHORT_DELTA_TARGET
DELTA_MIN = SPREAD_SHORT_DELTA_MIN
DELTA_MAX = SPREAD_SHORT_DELTA_MAX

# Alternatives for different market conditions
DELTA_CONSERVATIVE = SPREAD_SHORT_DELTA_MIN  # Lower risk
DELTA_AGGRESSIVE = SPREAD_SHORT_DELTA_MAX  # Higher risk

# Long Put Delta (bought) — delegiert an trading_rules
# PLAYBOOK §2: Delta -0.05 ±0.02
DELTA_LONG_TARGET = SPREAD_LONG_DELTA_TARGET
DELTA_LONG_MIN = SPREAD_LONG_DELTA_MIN
DELTA_LONG_MAX = SPREAD_LONG_DELTA_MAX


# =============================================================================
# SPREAD PARAMETERS
# =============================================================================

# Spread Width: NICHT konfigurierbar — ergibt sich aus Delta-Differenz (PLAYBOOK §2)
# Short Put Delta -0.20, Long Put Delta -0.05 → Width ist dynamisch

# OTM (Out of the Money) Target
OTM_TARGET_PCT = 10.0  # Short strike 10% below price


# =============================================================================
# RISK/REWARD RATIOS
# =============================================================================

# Minimum acceptable risk/reward
RISK_REWARD_MIN = 0.25  # Minimum 25% Return on Risk

# Targets
RISK_REWARD_TARGET = 0.35  # Target 35% RoR
RISK_REWARD_OPTIMAL = 0.40  # Optimal 40% RoR

# Stop Loss / Target Price Multipliers
STOP_LOSS_MULTIPLIER = EXIT_STOP_LOSS_MULTIPLIER  # Delegiert an trading_rules (PLAYBOOK: 2x credit)
TARGET_MULTIPLIER = (
    EXIT_PROFIT_PCT_NORMAL / 100
)  # Delegiert an trading_rules (PLAYBOOK: 50% credit)


# =============================================================================
# EARNINGS SAFETY
# =============================================================================

# Minimum distance to earnings
# PLAYBOOK §1: Earnings > 45 Tage (hart, keine Ausnahme)
EARNINGS_MIN_DAYS = ENTRY_EARNINGS_MIN_DAYS  # Minimum days until earnings (PLAYBOOK: 45)
EARNINGS_MIN_DAYS_STRICT = ENTRY_EARNINGS_MIN_DAYS  # Strict variant (same as default per PLAYBOOK)
EARNINGS_SAFE_DAYS = 90  # Classified as "safe"

# Post-Earnings Buffer
EARNINGS_POST_BUFFER_DAYS = 2  # Days after earnings before new trade


# =============================================================================
# POSITION SIZING
# =============================================================================

# Maximum Exposure
MAX_POSITION_SIZE_PCT = 5.0  # Max 5% per position
MAX_SECTOR_EXPOSURE_PCT = 20.0  # Max 20% per sector
MAX_TOTAL_RISK_PCT = 10.0  # Max 10% total risk

# Trade Limits
# PLAYBOOK §5+§6: Max 2 neue Trades pro Tag, Max 10 Positionen
MAX_DAILY_TRADES = 2  # Max new trades per day (PLAYBOOK: 2)
MAX_OPEN_POSITIONS = 10  # Max open positions (PLAYBOOK: 10 at VIX < 20)
MAX_POSITIONS_PER_SYMBOL = 2  # Max positions per symbol


# =============================================================================
# KELLY CRITERION PARAMETERS
# =============================================================================

# Kelly Fraction Scaling
KELLY_FRACTION = 0.25  # Use 25% of Kelly optimum (conservative)
KELLY_MAX_BET_PCT = 5.0  # Maximum bet even with high Kelly

# Win Rate Scaling
WIN_RATE_BASE_MULTIPLIER = 0.7  # Base multiplier
WIN_RATE_DIVISOR = 300.0  # Divisor for win rate integration


# =============================================================================
# STOP LOSS LEVELS
# =============================================================================

# Standard Stop Loss (% of max loss)
STOP_LOSS_PCT_OF_WIDTH = 150.0  # Stop at 150% of spread width risk

# VIX-based adjustment
STOP_LOSS_VIX_LOW_MULT = 1.0  # VIX < 15: Normal
STOP_LOSS_VIX_NORMAL_MULT = 1.2  # VIX 15-25: 20% wider
STOP_LOSS_VIX_HIGH_MULT = 1.5  # VIX > 25: 50% wider


# =============================================================================
# CONVENIENCE CLASS
# =============================================================================


@dataclass(frozen=True)
class RiskManagement:
    """
    Grouped risk management constants.

    Usage:
        from src.constants import RiskManagement as RM
        if dte < RM.DTE_MIN:
            ...
    """

    # DTE
    DTE_MIN: int = DTE_MIN
    DTE_MAX: int = DTE_MAX
    DTE_TARGET: int = DTE_TARGET

    # Delta
    DELTA_TARGET: float = DELTA_TARGET
    DELTA_MIN: float = DELTA_MIN
    DELTA_MAX: float = DELTA_MAX

    # Spread: width is delta-derived (PLAYBOOK §2), no configured constant
    OTM_TARGET_PCT: float = OTM_TARGET_PCT

    # Risk/Reward
    RISK_REWARD_MIN: float = RISK_REWARD_MIN

    # Earnings
    EARNINGS_MIN_DAYS: int = EARNINGS_MIN_DAYS

    # Position Sizing
    MAX_POSITION_PCT: float = MAX_POSITION_SIZE_PCT
    MAX_SECTOR_PCT: float = MAX_SECTOR_EXPOSURE_PCT
