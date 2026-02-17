# OptionPlay - Risk Management Constants
# =======================================
# All parameters for risk management and position sizing.
#
# IMPORTANT: Delta is a strategy parameter and must NOT be changed!
# See CLAUDE.md for details.

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

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
    get_trading_rules_config,
)

# =============================================================================
# CONFIG LOADER
# =============================================================================


def _load_rm_config() -> Dict[str, Any]:
    """Load risk management section from shared trading_rules config."""
    return get_trading_rules_config().get("risk_management", {})


_rm_cfg = _load_rm_config()


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
OTM_TARGET_PCT = _rm_cfg.get("otm_target_pct", 10.0)


# =============================================================================
# RISK/REWARD RATIOS
# =============================================================================

# Minimum acceptable risk/reward
RISK_REWARD_MIN = _rm_cfg.get("risk_reward_min", 0.25)

# Targets
RISK_REWARD_TARGET = _rm_cfg.get("risk_reward_target", 0.35)
RISK_REWARD_OPTIMAL = _rm_cfg.get("risk_reward_optimal", 0.40)

# Stop Loss / Target Price Multipliers
STOP_LOSS_MULTIPLIER = EXIT_STOP_LOSS_MULTIPLIER  # Delegiert an trading_rules (PLAYBOOK: 2x credit)
TARGET_MULTIPLIER = (
    EXIT_PROFIT_PCT_NORMAL / 100
)  # Delegiert an trading_rules (PLAYBOOK: 50% credit)


# =============================================================================
# EARNINGS SAFETY
# =============================================================================

# Minimum distance to earnings
# PLAYBOOK §1: Earnings buffer (was 45d, now 30d via scanner_config.yaml)
EARNINGS_MIN_DAYS = ENTRY_EARNINGS_MIN_DAYS  # Minimum days until earnings
EARNINGS_MIN_DAYS_STRICT = ENTRY_EARNINGS_MIN_DAYS  # Strict variant (same as default)
EARNINGS_SAFE_DAYS = _rm_cfg.get("earnings_safe_days", 90)

# Post-Earnings Buffer
EARNINGS_POST_BUFFER_DAYS = _rm_cfg.get("earnings_post_buffer_days", 2)


# =============================================================================
# POSITION SIZING
# =============================================================================

# Maximum Exposure
MAX_POSITION_SIZE_PCT = _rm_cfg.get("max_position_size_pct", 5.0)
MAX_SECTOR_EXPOSURE_PCT = _rm_cfg.get("max_sector_exposure_pct", 20.0)
MAX_TOTAL_RISK_PCT = _rm_cfg.get("max_total_risk_pct", 10.0)

# Trade Limits
# PLAYBOOK §5+§6: Max 2 neue Trades pro Tag, Max 10 Positionen
MAX_DAILY_TRADES = 2  # Delegated to trading_rules.py SIZING_MAX_NEW_TRADES_PER_DAY
MAX_OPEN_POSITIONS = 10  # Delegated to trading_rules.py SIZING_MAX_OPEN_POSITIONS
MAX_POSITIONS_PER_SYMBOL = _rm_cfg.get("max_positions_per_symbol", 2)


# =============================================================================
# KELLY CRITERION PARAMETERS
# =============================================================================

# Kelly Fraction Scaling
KELLY_FRACTION = _rm_cfg.get("kelly_fraction", 0.25)
KELLY_MAX_BET_PCT = _rm_cfg.get("kelly_max_bet_pct", 5.0)

# Win Rate Scaling
WIN_RATE_BASE_MULTIPLIER = _rm_cfg.get("win_rate_base_multiplier", 0.7)
WIN_RATE_DIVISOR = _rm_cfg.get("win_rate_divisor", 300.0)


# =============================================================================
# STOP LOSS LEVELS
# =============================================================================

# Standard Stop Loss (% of max loss)
STOP_LOSS_PCT_OF_WIDTH = _rm_cfg.get("stop_loss_pct_of_width", 150.0)

# VIX-based adjustment
STOP_LOSS_VIX_LOW_MULT = _rm_cfg.get("stop_loss_vix_low_mult", 1.0)
STOP_LOSS_VIX_NORMAL_MULT = _rm_cfg.get("stop_loss_vix_normal_mult", 1.2)
STOP_LOSS_VIX_HIGH_MULT = _rm_cfg.get("stop_loss_vix_high_mult", 1.5)


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
