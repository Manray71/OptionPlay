# OptionPlay - Trading Rules (Single Source of Truth)
# ====================================================
# ALL trading rules from PLAYBOOK.md centralized here.
# Other modules MUST import from here instead of using hardcoded values.
#
# If a value here differs from PLAYBOOK.md, this file is WRONG.
# PLAYBOOK.md is the authoritative document.
#
# Last synced with PLAYBOOK.md: 2026-02-04

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

# =============================================================================
# ENUMS
# =============================================================================


class TradeDecision(Enum):
    """Result of a trade validation check."""

    GO = "GO"
    NO_GO = "NO_GO"
    WARNING = "WARNING"


class VIXRegime(Enum):
    """VIX regime classification (5 tiers from PLAYBOOK §3)."""

    LOW_VOL = "LOW_VOL"  # VIX < 15
    NORMAL = "NORMAL"  # VIX 15-20
    DANGER_ZONE = "DANGER_ZONE"  # VIX 20-25
    ELEVATED = "ELEVATED"  # VIX 25-30
    HIGH_VOL = "HIGH_VOL"  # VIX > 30
    NO_TRADING = "NO_TRADING"  # VIX > 35


class ExitAction(Enum):
    """Position exit actions (PLAYBOOK §4)."""

    HOLD = "HOLD"
    CLOSE = "CLOSE"
    ROLL = "ROLL"
    ALERT = "ALERT"


# =============================================================================
# ENTRY RULES (PLAYBOOK §1)
# =============================================================================

# Hard filters - NO exceptions
ENTRY_STABILITY_MIN = 65.0  # Stability Score minimum (lowered from 70: 65-70 = WARNING)
ENTRY_EARNINGS_MIN_DAYS = 30  # Minimum days to earnings (was 45, now config-driven via scanner_config.yaml)
EARNINGS_QUARTERLY_MAX_GAP_DAYS = 100  # Max days since last earnings to assume "recently reported"
ENTRY_VIX_MAX_NEW_TRADES = 30.0  # No new trades above this VIX
ENTRY_VIX_NO_TRADING = 35.0  # No trading at all above this
ENTRY_PRICE_MIN = 20.0  # Minimum stock price
ENTRY_PRICE_MAX = 1500.0  # Maximum stock price (PLAYBOOK §1)
ENTRY_VOLUME_MIN = 500_000  # Minimum daily volume

# Soft filters - WARNING only
ENTRY_IV_RANK_MIN = 30.0  # IV Rank minimum (warning)
ENTRY_IV_RANK_MAX = 80.0  # IV Rank maximum (warning)


# Liquidity thresholds (loaded from config/scoring_weights.yaml)
def _load_liquidity_config() -> dict:
    """Load liquidity thresholds from scoring_weights.yaml."""
    try:
        from ..config.scoring_config import get_scoring_resolver

        resolver = get_scoring_resolver()
        return resolver.get_liquidity_config()
    except Exception:
        return {}


_liq = _load_liquidity_config()
_entry = _liq.get("entry", {})
_quality = _liq.get("quality", {})

ENTRY_OPEN_INTEREST_MIN = _entry.get("open_interest_min", 100)
ENTRY_BID_ASK_SPREAD_MAX = _entry.get("bid_ask_spread_max", 0.20)

# Options Liquidity Quality Thresholds (per strike)
_oi = _quality.get("open_interest", {})
LIQUIDITY_OI_EXCELLENT = _oi.get("excellent", 5000)
LIQUIDITY_OI_GOOD = _oi.get("good", 700)
LIQUIDITY_OI_FAIR = _oi.get("fair", 100)

_spread = _quality.get("spread_pct", {})
LIQUIDITY_SPREAD_PCT_EXCELLENT = _spread.get("excellent", 5.0)
LIQUIDITY_SPREAD_PCT_GOOD = _spread.get("good", 10.0)
LIQUIDITY_SPREAD_PCT_FAIR = _spread.get("fair", 15.0)

_vol = _quality.get("volume", {})
LIQUIDITY_VOLUME_EXCELLENT = _vol.get("excellent", 200)
LIQUIDITY_VOLUME_GOOD = _vol.get("good", 50)
LIQUIDITY_VOLUME_FAIR = _vol.get("fair", 10)

LIQUIDITY_MIN_QUALITY_DAILY_PICKS = _liq.get("min_quality_daily_picks", "good")

# Blacklist - symbols that must NEVER be traded
BLACKLIST_SYMBOLS: List[str] = [
    "ROKU",
    "SNAP",
    "UPST",
    "AFRM",
    "MRNA",
    "RUN",
    "MSTR",
    "TSLA",
    "COIN",
    "SQ",
    "IONQ",
    "QBTS",
    "RGTI",
    "DAVE",
]

# Blacklist criteria
BLACKLIST_STABILITY_THRESHOLD = 40.0  # Below this = blacklist
BLACKLIST_WIN_RATE_THRESHOLD = 70.0  # Below this = blacklist
BLACKLIST_VOLATILITY_THRESHOLD = 100.0  # Above this (annualized %) = blacklist


# =============================================================================
# SPREAD PARAMETERS (PLAYBOOK §2)
# =============================================================================

# DTE
SPREAD_DTE_MIN = 60  # Minimum DTE
SPREAD_DTE_MAX = 90  # Maximum DTE
SPREAD_DTE_TARGET = 75  # Optimal DTE

# Delta - DO NOT CHANGE (PLAYBOOK: "Delta ist heilig")
SPREAD_SHORT_DELTA_TARGET = -0.20  # Short put delta target
SPREAD_SHORT_DELTA_MIN = -0.17  # Short put delta minimum (±0.03)
SPREAD_SHORT_DELTA_MAX = -0.23  # Short put delta maximum (±0.03)

SPREAD_LONG_DELTA_TARGET = -0.05  # Long put delta target
SPREAD_LONG_DELTA_MIN = -0.03  # Long put delta minimum (±0.02)
SPREAD_LONG_DELTA_MAX = -0.07  # Long put delta maximum (±0.02)

# Credit
SPREAD_MIN_CREDIT_PCT = 10.0  # Min credit as % of spread width (PLAYBOOK §2)
SPREAD_MIN_CREDIT_ABSOLUTE = 20.0  # Min absolute credit per contract (USD)
SPREAD_FEE_WARNING_THRESHOLD = 40.0  # Warn when credit < this (fee erosion)
SPREAD_IBKR_ROUND_TRIP_FEE = 2.60  # IBKR fee per spread round-trip (USD)


# =============================================================================
# VIX REGIME RULES (PLAYBOOK §3)
# =============================================================================

# Regime boundaries
VIX_LOW_VOL_MAX = 15.0
VIX_NORMAL_MAX = 20.0
VIX_DANGER_ZONE_MAX = 25.0
VIX_ELEVATED_MAX = 30.0
VIX_NO_TRADING_THRESHOLD = 35.0


# Per-regime rules
@dataclass(frozen=True)
class VIXRegimeRules:
    """Rules that change based on VIX regime."""

    regime: VIXRegime
    stability_min: float
    new_trades_allowed: bool
    max_positions: int
    max_per_sector: int
    risk_per_trade_pct: float
    profit_exit_pct: float  # Close at this % of credit
    notes: str


VIX_REGIME_RULES: Dict[VIXRegime, VIXRegimeRules] = {
    VIXRegime.LOW_VOL: VIXRegimeRules(
        regime=VIXRegime.LOW_VOL,
        stability_min=65.0,
        new_trades_allowed=True,
        max_positions=10,
        max_per_sector=2,
        risk_per_trade_pct=2.0,
        profit_exit_pct=50.0,
        notes="Niedrigere Prämien akzeptieren",
    ),
    VIXRegime.NORMAL: VIXRegimeRules(
        regime=VIXRegime.NORMAL,
        stability_min=65.0,
        new_trades_allowed=True,
        max_positions=10,
        max_per_sector=2,
        risk_per_trade_pct=2.0,
        profit_exit_pct=50.0,
        notes="Standard-Parameter",
    ),
    VIXRegime.DANGER_ZONE: VIXRegimeRules(
        regime=VIXRegime.DANGER_ZONE,
        stability_min=80.0,
        new_trades_allowed=True,
        max_positions=5,
        max_per_sector=1,
        risk_per_trade_pct=1.5,
        profit_exit_pct=30.0,
        notes="Nur Premium-Symbole, schneller raus",
    ),
    VIXRegime.ELEVATED: VIXRegimeRules(
        regime=VIXRegime.ELEVATED,
        stability_min=80.0,
        new_trades_allowed=True,
        max_positions=3,
        max_per_sector=1,
        risk_per_trade_pct=1.0,
        profit_exit_pct=30.0,
        notes="Nur Top-10 Symbole, keine neuen Sektoren",
    ),
    VIXRegime.HIGH_VOL: VIXRegimeRules(
        regime=VIXRegime.HIGH_VOL,
        stability_min=100.0,  # effectively no new trades
        new_trades_allowed=False,
        max_positions=0,
        max_per_sector=0,
        risk_per_trade_pct=0.0,
        profit_exit_pct=0.0,  # close all winners immediately
        notes="KEINE neuen Trades, nur Bestand managen",
    ),
    VIXRegime.NO_TRADING: VIXRegimeRules(
        regime=VIXRegime.NO_TRADING,
        stability_min=100.0,
        new_trades_allowed=False,
        max_positions=0,
        max_per_sector=0,
        risk_per_trade_pct=0.0,
        profit_exit_pct=0.0,
        notes="KEIN TRADING - alles mit Verlust-Limit schließen",
    ),
}


def get_vix_regime(vix: float) -> VIXRegime:
    """Classify VIX into regime (PLAYBOOK §3).

    Boundaries: <15 LOW_VOL | 15-20 NORMAL | 20-25 DANGER | 25-30 ELEVATED | >30 HIGH | >35 NONE
    """
    if vix >= VIX_NO_TRADING_THRESHOLD:
        return VIXRegime.NO_TRADING
    elif vix >= VIX_ELEVATED_MAX:
        return VIXRegime.HIGH_VOL
    elif vix >= VIX_DANGER_ZONE_MAX:
        return VIXRegime.ELEVATED
    elif vix >= VIX_NORMAL_MAX:
        return VIXRegime.DANGER_ZONE
    elif vix >= VIX_LOW_VOL_MAX:
        return VIXRegime.NORMAL
    else:
        return VIXRegime.LOW_VOL


def get_regime_rules(vix: float) -> VIXRegimeRules:
    """Get regime-specific rules for a given VIX level."""
    regime = get_vix_regime(vix)
    return VIX_REGIME_RULES[regime]


def is_blacklisted(symbol: str) -> bool:
    """Check if symbol is on the blacklist (PLAYBOOK §1, Check 1)."""
    return symbol.upper() in {s.upper() for s in BLACKLIST_SYMBOLS}


def get_adjusted_stability_min(vix: Optional[float] = None) -> float:
    """Get VIX-adjusted stability minimum threshold (PLAYBOOK §1 + §3).

    Default: ENTRY_STABILITY_MIN.
    Under elevated VIX: Regime may require higher stability.
    """
    min_stability = ENTRY_STABILITY_MIN
    if vix is not None:
        regime_rules = get_regime_rules(vix)
        min_stability = max(min_stability, regime_rules.stability_min)
    return min_stability


# =============================================================================
# EXIT RULES (PLAYBOOK §4)
# =============================================================================

# Profit exits
EXIT_PROFIT_PCT_NORMAL = 50.0  # Close at 50% profit (VIX < 20)
EXIT_PROFIT_PCT_HIGH_VIX = 30.0  # Close at 30% profit (VIX >= 20)

# Loss exits
EXIT_STOP_LOSS_MULTIPLIER = 2.0  # 200% of credit = stop loss

# Time exits
EXIT_ROLL_DTE = 21  # Decision point: roll or close
EXIT_FORCE_CLOSE_DTE = 7  # Force close, no exceptions

# Event exits
# Support broken -> CLOSE (within session)
# Earnings announced -> CLOSE IMMEDIATELY (regardless of P&L)


# =============================================================================
# ROLL RULES (PLAYBOOK §4, Roll-Regeln)
# =============================================================================

ROLL_ALLOWED_MAX_LOSS_PCT = 0.0  # Max: break-even (0% loss)
ROLL_NEW_DTE_MIN = 60  # New expiration: 60-90 DTE
ROLL_NEW_DTE_MAX = 90
ROLL_MIN_CREDIT_PCT = 10.0  # New credit must be >= 10% spread (PLAYBOOK §4)


# =============================================================================
# POSITION SIZING (PLAYBOOK §5)
# =============================================================================

SIZING_MAX_RISK_PER_TRADE_PCT = 2.0  # Max 2% portfolio risk per trade
SIZING_MAX_OPEN_POSITIONS = 10  # Max open positions (VIX < 20)
SIZING_MAX_PER_SECTOR = 2  # Max positions per sector (PLAYBOOK §5: "Max 2 bei Normal VIX")
SIZING_MAX_NEW_TRADES_PER_DAY = 2  # Max new trades per day


# =============================================================================
# DISCIPLINE RULES (PLAYBOOK §6)
# =============================================================================

DISCIPLINE_MAX_TRADES_PER_MONTH = 25
DISCIPLINE_MAX_TRADES_PER_DAY = 2
DISCIPLINE_MAX_TRADES_PER_WEEK = 8

# Loss management
DISCIPLINE_CONSECUTIVE_LOSSES_PAUSE = 3  # Pause after N consecutive losses
DISCIPLINE_PAUSE_DAYS = 7  # Duration of pause in days
DISCIPLINE_MONTHLY_LOSSES_PAUSE = 5  # Pause after N losses in a month
DISCIPLINE_MONTHLY_DRAWDOWN_PAUSE = 5.0  # Pause after N% portfolio drawdown


# =============================================================================
# WATCHLIST (PLAYBOOK §7)
# =============================================================================

# Primary Watchlist: Top 20 (Stability >= 80)
PRIMARY_WATCHLIST: List[str] = [
    "SPY",
    "TJX",
    "QQQ",
    "JNJ",
    "JPM",
    "IWM",
    "UNP",
    "ADI",
    "LOW",
    "GILD",
    "V",
    "WMT",
    "MSFT",
    "HLT",
    "WDAY",
    "GOOGL",
    "MRK",
    "AAPL",
    "MS",
    "XOM",
]

# Secondary Watchlist threshold
SECONDARY_WATCHLIST_STABILITY_MIN = 70.0


# =============================================================================
# FILTER ORDER (PLAYBOOK §1, Prüf-Reihenfolge)
# =============================================================================
# 1. Blacklist-Check     -> sofort raus wenn gelistet
# 2. Stability >= 65     -> sofort raus wenn < 65 (65-70 = WARNING)
# 3. Earnings > 45 Tage  -> sofort raus wenn zu nah
# 4. VIX < 30            -> sofort raus wenn >= 30
# 5. Preis $20-$1500      -> sofort raus wenn außerhalb
# 6. Volumen > 500k      -> sofort raus wenn zu dünn
# 7. IV Rank 30-80%      -> WARNING wenn außerhalb
# 8. Score-Ranking        -> sortieren, beste zuerst

FILTER_ORDER = [
    "blacklist",
    "stability",
    "earnings",
    "vix",
    "price",
    "volume",
    "iv_rank",
    "score_ranking",
]


# =============================================================================
# CONVENIENCE CLASS
# =============================================================================


@dataclass(frozen=True)
class TradingRules:
    """
    Convenience class for accessing all PLAYBOOK rules.

    Usage:
        from src.constants.trading_rules import TradingRules as TR
        if stability < TR.ENTRY_STABILITY_MIN:
            return "NO_GO"
    """

    # Entry
    ENTRY_STABILITY_MIN: float = ENTRY_STABILITY_MIN
    ENTRY_EARNINGS_MIN_DAYS: int = ENTRY_EARNINGS_MIN_DAYS
    ENTRY_VIX_MAX: float = ENTRY_VIX_MAX_NEW_TRADES
    ENTRY_PRICE_MIN: float = ENTRY_PRICE_MIN
    ENTRY_PRICE_MAX: float = ENTRY_PRICE_MAX
    ENTRY_VOLUME_MIN: int = ENTRY_VOLUME_MIN

    # Spread
    DTE_MIN: int = SPREAD_DTE_MIN
    DTE_MAX: int = SPREAD_DTE_MAX
    DTE_TARGET: int = SPREAD_DTE_TARGET
    SHORT_DELTA: float = SPREAD_SHORT_DELTA_TARGET
    LONG_DELTA: float = SPREAD_LONG_DELTA_TARGET
    MIN_CREDIT_PCT: float = SPREAD_MIN_CREDIT_PCT
    MIN_CREDIT_ABSOLUTE: float = SPREAD_MIN_CREDIT_ABSOLUTE

    # Exit
    PROFIT_EXIT_NORMAL: float = EXIT_PROFIT_PCT_NORMAL
    PROFIT_EXIT_HIGH_VIX: float = EXIT_PROFIT_PCT_HIGH_VIX
    STOP_LOSS_MULT: float = EXIT_STOP_LOSS_MULTIPLIER
    ROLL_DTE: int = EXIT_ROLL_DTE
    FORCE_CLOSE_DTE: int = EXIT_FORCE_CLOSE_DTE

    # Sizing
    MAX_RISK_PCT: float = SIZING_MAX_RISK_PER_TRADE_PCT
    MAX_POSITIONS: int = SIZING_MAX_OPEN_POSITIONS
    MAX_PER_SECTOR: int = SIZING_MAX_PER_SECTOR
    MAX_TRADES_DAY: int = SIZING_MAX_NEW_TRADES_PER_DAY
