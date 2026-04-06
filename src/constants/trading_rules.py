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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# =============================================================================
# CONFIG LOADER
# =============================================================================


def _load_trading_rules_config() -> Dict[str, Any]:
    """Load tunable trading rules from config/trading_rules.yaml."""
    try:
        config_path = Path(__file__).resolve().parents[2] / "config" / "trading_rules.yaml"
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def get_trading_rules_config() -> Dict[str, Any]:
    """Return the cached parsed trading_rules.yaml config.

    Other modules that need sections from trading_rules.yaml should call this
    instead of re-parsing the file independently.
    """
    return _tr_cfg


_tr_cfg = _load_trading_rules_config()
_entry_cfg = _tr_cfg.get("entry", {})
_spread_cfg = _tr_cfg.get("spread", {})
_exit_cfg = _tr_cfg.get("exit", {})
_roll_cfg = _tr_cfg.get("roll", {})
_sizing_cfg = _tr_cfg.get("sizing", {})
_discipline_cfg = _tr_cfg.get("discipline", {})
_bl_cfg = _tr_cfg.get("blacklist_criteria", {})
_wl_cfg = _tr_cfg.get("watchlist", {})
_vix_cfg = _tr_cfg.get("vix_regimes", {})
_vix_bounds = _vix_cfg.get("boundaries", {})
_vix_rules = _vix_cfg.get("rules", {})


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
ENTRY_STABILITY_MIN = _entry_cfg.get("stability_min", 65.0)
ENTRY_EARNINGS_MIN_DAYS = _entry_cfg.get("earnings_min_days", 30)
EARNINGS_QUARTERLY_MAX_GAP_DAYS = _entry_cfg.get("earnings_quarterly_max_gap", 100)
ENTRY_VIX_MAX_NEW_TRADES = _entry_cfg.get("vix_max_new_trades", 30.0)
ENTRY_VIX_NO_TRADING = _entry_cfg.get("vix_no_trading", 35.0)
ENTRY_PRICE_MIN = _entry_cfg.get("price_min", 20.0)
ENTRY_PRICE_MAX = _entry_cfg.get("price_max", 1500.0)
ENTRY_VOLUME_MIN = _entry_cfg.get("volume_min", 500_000)

# Soft filters - WARNING only
ENTRY_IV_RANK_MIN = _entry_cfg.get("iv_rank_min", 30.0)
ENTRY_IV_RANK_MAX = _entry_cfg.get("iv_rank_max", 80.0)


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
BLACKLIST_STABILITY_THRESHOLD = _bl_cfg.get("stability_threshold", 40.0)
BLACKLIST_WIN_RATE_THRESHOLD = _bl_cfg.get("win_rate_threshold", 70.0)
BLACKLIST_VOLATILITY_THRESHOLD = _bl_cfg.get("volatility_threshold", 100.0)


# =============================================================================
# SPREAD PARAMETERS (PLAYBOOK §2)
# =============================================================================

# DTE
SPREAD_DTE_MIN = _spread_cfg.get("dte_min", 60)
SPREAD_DTE_MAX = _spread_cfg.get("dte_max", 90)
SPREAD_DTE_TARGET = _spread_cfg.get("dte_target", 75)

# Delta - DO NOT CHANGE (PLAYBOOK: "Delta ist heilig")
SPREAD_SHORT_DELTA_TARGET = -0.20  # Short put delta target
SPREAD_SHORT_DELTA_MIN = -0.17  # Short put delta minimum (±0.03)
SPREAD_SHORT_DELTA_MAX = -0.23  # Short put delta maximum (±0.03)

SPREAD_LONG_DELTA_TARGET = -0.05  # Long put delta target
SPREAD_LONG_DELTA_MIN = -0.03  # Long put delta minimum (±0.02)
SPREAD_LONG_DELTA_MAX = -0.07  # Long put delta maximum (±0.02)

# Credit
SPREAD_MIN_CREDIT_PCT = _spread_cfg.get("min_credit_pct", 10.0)
SPREAD_MIN_CREDIT_ABSOLUTE = _spread_cfg.get("min_credit_absolute", 20.0)
SPREAD_FEE_WARNING_THRESHOLD = _spread_cfg.get("fee_warning_threshold", 40.0)
SPREAD_IBKR_ROUND_TRIP_FEE = _spread_cfg.get("ibkr_round_trip_fee", 2.60)


# =============================================================================
# VIX REGIME RULES (PLAYBOOK §3)
# =============================================================================

# Regime boundaries
VIX_LOW_VOL_MAX = _vix_bounds.get("low_vol_max", 15.0)
VIX_NORMAL_MAX = _vix_bounds.get("normal_max", 20.0)
VIX_DANGER_ZONE_MAX = _vix_bounds.get("danger_zone_max", 25.0)
VIX_ELEVATED_MAX = _vix_bounds.get("elevated_max", 30.0)
VIX_NO_TRADING_THRESHOLD = _vix_bounds.get("no_trading", 35.0)


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


def _build_regime_rules() -> Dict["VIXRegime", VIXRegimeRules]:
    """Build VIX regime rules from config (with hardcoded defaults)."""
    _DEFAULTS = {
        "low_vol": {
            "stability_min": 65.0,
            "new_trades_allowed": True,
            "max_positions": 10,
            "max_per_sector": 2,
            "risk_per_trade_pct": 2.0,
            "profit_exit_pct": 50.0,
            "notes": "Niedrigere Prämien akzeptieren",
        },
        "normal": {
            "stability_min": 65.0,
            "new_trades_allowed": True,
            "max_positions": 10,
            "max_per_sector": 2,
            "risk_per_trade_pct": 2.0,
            "profit_exit_pct": 50.0,
            "notes": "Standard-Parameter",
        },
        "danger_zone": {
            "stability_min": 80.0,
            "new_trades_allowed": True,
            "max_positions": 5,
            "max_per_sector": 1,
            "risk_per_trade_pct": 1.5,
            "profit_exit_pct": 30.0,
            "notes": "Nur Premium-Symbole, schneller raus",
        },
        "elevated": {
            "stability_min": 80.0,
            "new_trades_allowed": True,
            "max_positions": 3,
            "max_per_sector": 1,
            "risk_per_trade_pct": 1.0,
            "profit_exit_pct": 30.0,
            "notes": "Nur Top-10 Symbole, keine neuen Sektoren",
        },
        "high_vol": {
            "stability_min": 100.0,
            "new_trades_allowed": False,
            "max_positions": 0,
            "max_per_sector": 0,
            "risk_per_trade_pct": 0.0,
            "profit_exit_pct": 0.0,
            "notes": "KEINE neuen Trades, nur Bestand managen",
        },
        "no_trading": {
            "stability_min": 100.0,
            "new_trades_allowed": False,
            "max_positions": 0,
            "max_per_sector": 0,
            "risk_per_trade_pct": 0.0,
            "profit_exit_pct": 0.0,
            "notes": "KEIN TRADING - alles mit Verlust-Limit schließen",
        },
    }
    _REGIME_MAP = {
        "low_vol": VIXRegime.LOW_VOL,
        "normal": VIXRegime.NORMAL,
        "danger_zone": VIXRegime.DANGER_ZONE,
        "elevated": VIXRegime.ELEVATED,
        "high_vol": VIXRegime.HIGH_VOL,
        "no_trading": VIXRegime.NO_TRADING,
    }
    rules = {}
    for key, regime in _REGIME_MAP.items():
        defaults = _DEFAULTS[key]
        cfg = _vix_rules.get(key, {})
        rules[regime] = VIXRegimeRules(
            regime=regime,
            stability_min=cfg.get("stability_min", defaults["stability_min"]),
            new_trades_allowed=cfg.get("new_trades_allowed", defaults["new_trades_allowed"]),
            max_positions=cfg.get("max_positions", defaults["max_positions"]),
            max_per_sector=cfg.get("max_per_sector", defaults["max_per_sector"]),
            risk_per_trade_pct=cfg.get("risk_per_trade_pct", defaults["risk_per_trade_pct"]),
            profit_exit_pct=cfg.get("profit_exit_pct", defaults["profit_exit_pct"]),
            notes=defaults["notes"],
        )
    return rules


VIX_REGIME_RULES: Dict[VIXRegime, VIXRegimeRules] = _build_regime_rules()


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


def get_regime_rules_v2(
    vix: float, vix_futures_front: Optional[float] = None
) -> VIXRegimeRules:
    """Get interpolated regime rules from VIX Regime v2.

    Uses continuous interpolation instead of discrete tiers.
    Falls back to v1 lookup for fields not in v2 anchors
    (stability_min, risk_per_trade_pct, profit_exit_pct).

    Args:
        vix: Current VIX spot value
        vix_futures_front: Optional front-month VIX future for term structure

    Returns:
        VIXRegimeRules with interpolated max_positions/max_per_sector
        and v1-derived stability_min/risk_per_trade_pct/profit_exit_pct
    """
    from ..services.vix_regime import get_regime_params

    params = get_regime_params(vix, vix_futures_front)

    # v1 lookup for fields without v2 anchor points
    v1_rules = get_regime_rules(vix)

    return VIXRegimeRules(
        regime=get_vix_regime(vix),
        stability_min=v1_rules.stability_min,
        new_trades_allowed=params.max_positions > 0,
        max_positions=params.max_positions,
        max_per_sector=params.max_per_sector,
        risk_per_trade_pct=v1_rules.risk_per_trade_pct,
        profit_exit_pct=v1_rules.profit_exit_pct,
        notes=f"VIX Regime v2: {params.regime_label.value}",
    )


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
EXIT_PROFIT_PCT_NORMAL = _exit_cfg.get("profit_pct_normal", 50.0)
EXIT_PROFIT_PCT_HIGH_VIX = _exit_cfg.get("profit_pct_high_vix", 30.0)

# Loss exits
EXIT_STOP_LOSS_MULTIPLIER = _exit_cfg.get("stop_loss_multiplier", 2.0)

# Time exits
EXIT_ROLL_DTE = _exit_cfg.get("roll_dte", 21)
EXIT_FORCE_CLOSE_DTE = _exit_cfg.get("force_close_dte", 7)

# Event exits
# Support broken -> CLOSE (within session)
# Earnings announced -> CLOSE IMMEDIATELY (regardless of P&L)


# =============================================================================
# ROLL RULES (PLAYBOOK §4, Roll-Regeln)
# =============================================================================

ROLL_ALLOWED_MAX_LOSS_PCT = _roll_cfg.get("allowed_max_loss_pct", 0.0)
ROLL_NEW_DTE_MIN = _roll_cfg.get("new_dte_min", 60)
ROLL_NEW_DTE_MAX = _roll_cfg.get("new_dte_max", 90)
ROLL_MIN_CREDIT_PCT = _roll_cfg.get("min_credit_pct", 10.0)


# =============================================================================
# POSITION SIZING (PLAYBOOK §5)
# =============================================================================

SIZING_MAX_RISK_PER_TRADE_PCT = _sizing_cfg.get("max_risk_per_trade_pct", 2.0)
SIZING_MAX_OPEN_POSITIONS = _sizing_cfg.get("max_open_positions", 10)
SIZING_MAX_PER_SECTOR = _sizing_cfg.get("max_per_sector", 2)
SIZING_MAX_NEW_TRADES_PER_DAY = _sizing_cfg.get("max_new_trades_per_day", 2)


# =============================================================================
# DISCIPLINE RULES (PLAYBOOK §6)
# =============================================================================

DISCIPLINE_MAX_TRADES_PER_MONTH = _discipline_cfg.get("max_trades_per_month", 25)
DISCIPLINE_MAX_TRADES_PER_DAY = _discipline_cfg.get("max_trades_per_day", 2)
DISCIPLINE_MAX_TRADES_PER_WEEK = _discipline_cfg.get("max_trades_per_week", 8)

# Loss management
DISCIPLINE_CONSECUTIVE_LOSSES_PAUSE = _discipline_cfg.get("consecutive_losses_pause", 3)
DISCIPLINE_PAUSE_DAYS = _discipline_cfg.get("pause_days", 7)
DISCIPLINE_MONTHLY_LOSSES_PAUSE = _discipline_cfg.get("monthly_losses_pause", 5)
DISCIPLINE_MONTHLY_DRAWDOWN_PAUSE = _discipline_cfg.get("monthly_drawdown_pause", 5.0)


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
SECONDARY_WATCHLIST_STABILITY_MIN = _wl_cfg.get("secondary_stability_min", 70.0)


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
