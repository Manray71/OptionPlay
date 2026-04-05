# OptionPlay - VIX Regime v2
# ==========================
# Continuous interpolation model replacing discrete 4-profile system.
#
# Key changes from v1:
# - Linear interpolation between 7 anchor points instead of 4 hard buckets
# - Term Structure overlay (contango/backwardation) adjusts parameters
# - VIX Trend overlay (rising_fast/falling_fast) further adjusts
# - Delta remains FIXED per Playbook ("Delta ist heilig")
# - Spread width from anchors used as floor (not override)

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from ..constants.trading_rules import (
    SPREAD_DTE_MAX,
    SPREAD_DTE_MIN,
    SPREAD_LONG_DELTA_TARGET,
    SPREAD_SHORT_DELTA_MAX,
    SPREAD_SHORT_DELTA_MIN,
    SPREAD_SHORT_DELTA_TARGET,
)

logger = logging.getLogger(__name__)


# =============================================================================
# REGIME LABELS
# =============================================================================


class RegimeLabel(str, Enum):
    """Display labels for VIX regime — purely informational."""

    ULTRA_LOW_VOL = "ULTRA-LOW VOL"
    LOW_VOL = "LOW VOL"
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH_VOL = "HIGH VOL"
    STRESS = "STRESS"
    EXTREME = "EXTREME"


# =============================================================================
# ANCHOR POINTS — the interpolation control points
# =============================================================================
# Format: (vix_level, spread_width, min_score, earnings_buffer_days, max_positions)
# Delta is intentionally absent — it stays fixed per Playbook.
#
# Logic changes vs v1:
#   - VIX <15: min_score lower (4→3.5), more trades in calm markets
#   - VIX 15-20: similar, the sweet spot
#   - VIX 20-25: new intermediate step, more moderate than v1 "Aggressive"
#   - VIX 25-30: more cautious than v1, but no cliff
#   - VIX 35+: hard floor, but reachable (score 6 instead of 7)

ANCHOR_POINTS = [
    # (VIX,  spread_width, min_score, earnings_days, max_positions)
    (10, 2.50, 3.5, 60, 6),  # Ultra-Low Vol
    (15, 5.00, 4.0, 60, 5),  # Low Vol
    (20, 5.00, 4.5, 60, 4),  # Normal — Sweet Spot
    (25, 5.00, 5.0, 60, 3),  # Elevated
    (30, 7.50, 5.5, 75, 2),  # High Vol
    (35, 10.00, 6.0, 90, 1),  # Stress
    (40, 10.00, 7.0, 90, 0),  # Extreme — Pause
]


# =============================================================================
# TERM STRUCTURE CONSTANTS
# =============================================================================

TS_CONTANGO_THRESHOLD = 0.03  # >3% futures premium = contango
TS_BACKWARDATION_THRESHOLD = -0.03  # >3% futures discount = backwardation
TS_MIN_VIX_FOR_ADJUSTMENT = 20  # Below VIX 20, term structure less relevant

# Contango adjustments (stress is temporary)
TS_CONTANGO_SCORE_RELIEF = -0.5
TS_CONTANGO_MAX_POS_BONUS = 1
TS_CONTANGO_SCORE_FLOOR = 3.5
TS_CONTANGO_MAX_POS_CEILING = 6

# Backwardation adjustments (stress worsening)
TS_BACKWARDATION_SCORE_PENALTY = 1.0
TS_BACKWARDATION_MAX_POS_PENALTY = -1
TS_BACKWARDATION_EARNINGS_EXTRA = 15
TS_BACKWARDATION_SCORE_CEILING = 8.0
TS_BACKWARDATION_EARNINGS_CEILING = 120
TS_BACKWARDATION_MAX_POS_FLOOR = 0

# =============================================================================
# VIX TREND OVERLAY CONSTANTS
# =============================================================================

TREND_RISING_FAST_SCORE_PENALTY = 0.5
TREND_RISING_FAST_POS_PENALTY = 1
TREND_FALLING_FAST_SCORE_RELIEF = 0.3
TREND_MIN_VIX_FOR_ADJUSTMENT = 20


# =============================================================================
# VIX REGIME PARAMS (output dataclass)
# =============================================================================


@dataclass
class VIXRegimeParams:
    """Interpolated parameters for a given VIX level."""

    vix: float
    regime_label: RegimeLabel

    # Interpolated from anchor points
    spread_width: float
    min_score: float
    earnings_buffer_days: int
    max_positions: int
    max_per_sector: int

    # Fixed from Playbook (never interpolated)
    delta_target: float
    delta_min: float
    delta_max: float
    long_delta_target: float
    dte_min: int
    dte_max: int

    # Term Structure overlay
    term_structure: Optional[str] = None  # "contango" | "backwardation" | None
    stress_adjusted: bool = False

    # VIX Trend overlay
    vix_trend_label: Optional[str] = None
    trend_adjusted: bool = False

    def __str__(self) -> str:
        ts_info = ""
        if self.term_structure:
            ts_info = f"\n  Term Structure: {self.term_structure}"
        stress = " STRESS-ADJUSTED" if self.stress_adjusted else ""
        trend = ""
        if self.trend_adjusted:
            trend = f"\n  VIX Trend:      {self.vix_trend_label} (adjusted)"
        return (
            f"VIX Regime: {self.regime_label.value} (VIX={self.vix:.1f}){stress}\n"
            f"  Min Score:       {self.min_score:.1f}\n"
            f"  Spread Width:    ${self.spread_width:.2f}\n"
            f"  Earnings Buffer: {self.earnings_buffer_days}d\n"
            f"  Max Positions:   {self.max_positions}\n"
            f"  Max/Sector:      {self.max_per_sector}\n"
            f"  Delta Target:    {self.delta_target:.2f}"
            f"{ts_info}{trend}"
        )

    def to_dict(self) -> Dict:
        return {
            "vix": self.vix,
            "regime_label": self.regime_label.value,
            "spread_width": self.spread_width,
            "min_score": self.min_score,
            "earnings_buffer_days": self.earnings_buffer_days,
            "max_positions": self.max_positions,
            "max_per_sector": self.max_per_sector,
            "delta_target": self.delta_target,
            "delta_min": self.delta_min,
            "delta_max": self.delta_max,
            "long_delta_target": self.long_delta_target,
            "dte_min": self.dte_min,
            "dte_max": self.dte_max,
            "term_structure": self.term_structure,
            "stress_adjusted": self.stress_adjusted,
            "vix_trend_label": self.vix_trend_label,
            "trend_adjusted": self.trend_adjusted,
        }


# =============================================================================
# CORE FUNCTIONS
# =============================================================================


def _interpolate(vix: float, anchors: list = ANCHOR_POINTS) -> Dict:
    """
    Linear interpolation between anchor points.

    Args:
        vix: Current VIX spot level
        anchors: List of (vix, spread, min_score, earnings, max_pos) tuples

    Returns:
        Dict with interpolated values
    """
    vix_levels = [a[0] for a in anchors]

    # Clamp below minimum
    if vix <= vix_levels[0]:
        a = anchors[0]
        return dict(spread=a[1], min_score=a[2], earnings=a[3], max_pos=a[4])

    # Clamp above maximum
    if vix >= vix_levels[-1]:
        a = anchors[-1]
        return dict(spread=a[1], min_score=a[2], earnings=a[3], max_pos=a[4])

    # Find surrounding anchors and interpolate
    for i in range(len(anchors) - 1):
        if anchors[i][0] <= vix <= anchors[i + 1][0]:
            lo, hi = anchors[i], anchors[i + 1]
            t = (vix - lo[0]) / (hi[0] - lo[0])
            return {
                "spread": round(lo[1] + t * (hi[1] - lo[1]), 2),
                "min_score": round(lo[2] + t * (hi[2] - lo[2]), 1),
                "earnings": int(round(lo[3] + t * (hi[3] - lo[3]))),
                "max_pos": int(round(lo[4] + t * (hi[4] - lo[4]))),
            }

    # Should never reach here, but safety fallback
    a = anchors[-1]
    return dict(spread=a[1], min_score=a[2], earnings=a[3], max_pos=a[4])


def _classify_regime(vix: float) -> RegimeLabel:
    """Classify VIX level into a regime label (display only)."""
    if vix < 13:
        return RegimeLabel.ULTRA_LOW_VOL
    elif vix < 17:
        return RegimeLabel.LOW_VOL
    elif vix < 22:
        return RegimeLabel.NORMAL
    elif vix < 27:
        return RegimeLabel.ELEVATED
    elif vix < 33:
        return RegimeLabel.HIGH_VOL
    elif vix < 40:
        return RegimeLabel.STRESS
    else:
        return RegimeLabel.EXTREME


def _determine_term_structure(
    vix: float, vix_futures_front: Optional[float]
) -> Optional[str]:
    """
    Determine term structure state from spot vs futures spread.

    Returns:
        "contango", "backwardation", or None (neutral/unknown)
    """
    if vix_futures_front is None or vix <= 0:
        return None

    spread_pct = (vix_futures_front - vix) / vix
    if spread_pct > TS_CONTANGO_THRESHOLD:
        return "contango"
    elif spread_pct < TS_BACKWARDATION_THRESHOLD:
        return "backwardation"
    return None


def _apply_term_structure(
    params: Dict, vix: float, term_structure: Optional[str]
) -> Tuple[Dict, bool]:
    """
    Adjust parameters based on VIX term structure.

    Contango (futures > spot): stress is temporary → slightly looser params
    Backwardation (spot > futures): stress worsening → tighter params

    Returns:
        (adjusted_params, stress_adjusted_flag)
    """
    if term_structure is None or vix < TS_MIN_VIX_FOR_ADJUSTMENT:
        return params, False

    if term_structure == "contango":
        return {
            **params,
            "min_score": max(
                TS_CONTANGO_SCORE_FLOOR,
                params["min_score"] + TS_CONTANGO_SCORE_RELIEF,
            ),
            "max_pos": min(
                TS_CONTANGO_MAX_POS_CEILING,
                params["max_pos"] + TS_CONTANGO_MAX_POS_BONUS,
            ),
        }, False

    elif term_structure == "backwardation":
        return {
            **params,
            "min_score": min(
                TS_BACKWARDATION_SCORE_CEILING,
                params["min_score"] + TS_BACKWARDATION_SCORE_PENALTY,
            ),
            "max_pos": max(
                TS_BACKWARDATION_MAX_POS_FLOOR,
                params["max_pos"] + TS_BACKWARDATION_MAX_POS_PENALTY,
            ),
            "earnings": min(
                TS_BACKWARDATION_EARNINGS_CEILING,
                params["earnings"] + TS_BACKWARDATION_EARNINGS_EXTRA,
            ),
        }, True

    return params, False


def _apply_trend_overlay(
    params: Dict, vix: float, vix_trend: Optional[str]
) -> Tuple[Dict, bool]:
    """
    Apply VIX trend overlay as post-interpolation adjustment.

    Args:
        params: Interpolated (and possibly term-structure-adjusted) params
        vix: Current VIX level
        vix_trend: One of "rising_fast", "rising", "stable", "falling", "falling_fast"

    Returns:
        (adjusted_params, trend_adjusted_flag)
    """
    if vix_trend is None or vix < TREND_MIN_VIX_FOR_ADJUSTMENT:
        return params, False

    if vix_trend == "rising_fast":
        return {
            **params,
            "min_score": params["min_score"] + TREND_RISING_FAST_SCORE_PENALTY,
            "max_pos": max(0, params["max_pos"] - TREND_RISING_FAST_POS_PENALTY),
        }, True

    elif vix_trend == "falling_fast":
        return {
            **params,
            "min_score": max(
                TS_CONTANGO_SCORE_FLOOR,
                params["min_score"] - TREND_FALLING_FAST_SCORE_RELIEF,
            ),
        }, True

    return params, False


# =============================================================================
# MAIN API
# =============================================================================


def get_regime_params(
    vix: float,
    vix_futures_front: Optional[float] = None,
    vix_trend: Optional[str] = None,
) -> VIXRegimeParams:
    """
    Compute interpolated regime parameters for a given VIX level.

    Args:
        vix: Current VIX spot value
        vix_futures_front: Front-month VIX future (for term structure).
                           None = no term structure overlay.
        vix_trend: VIX trend label from VixTrend enum value
                   ("rising_fast", "rising", "stable", "falling", "falling_fast")

    Returns:
        VIXRegimeParams with all interpolated and fixed values

    Example:
        >>> params = get_regime_params(vix=23.5)
        >>> params.min_score
        5.0
        >>> params.max_positions
        3

        >>> params = get_regime_params(vix=28.0, vix_futures_front=25.0)
        >>> params.stress_adjusted  # Backwardation detected
        True
    """
    # 1. Interpolate base parameters
    interp = _interpolate(vix)

    # 2. Determine and apply term structure
    term_structure = _determine_term_structure(vix, vix_futures_front)
    interp, stress_adjusted = _apply_term_structure(interp, vix, term_structure)

    # 3. Apply VIX trend overlay
    interp, trend_adjusted = _apply_trend_overlay(interp, vix, vix_trend)

    # 4. Derive max_per_sector
    max_pos = interp["max_pos"]
    max_per_sector = max(1, max_pos // 3) if max_pos > 0 else 0

    # 5. Build result with fixed Playbook values
    return VIXRegimeParams(
        vix=vix,
        regime_label=_classify_regime(vix),
        spread_width=interp["spread"],
        min_score=interp["min_score"],
        earnings_buffer_days=interp["earnings"],
        max_positions=max_pos,
        max_per_sector=max_per_sector,
        delta_target=SPREAD_SHORT_DELTA_TARGET,
        delta_min=SPREAD_SHORT_DELTA_MIN,
        delta_max=SPREAD_SHORT_DELTA_MAX,
        long_delta_target=SPREAD_LONG_DELTA_TARGET,
        dte_min=SPREAD_DTE_MIN,
        dte_max=SPREAD_DTE_MAX,
        term_structure=term_structure,
        stress_adjusted=stress_adjusted,
        vix_trend_label=vix_trend,
        trend_adjusted=trend_adjusted,
    )


def should_trade(
    vix: float,
    candidate_score: float,
    current_positions: int,
    vix_futures_front: Optional[float] = None,
    vix_trend: Optional[str] = None,
) -> Dict:
    """
    Quick check: is this trade allowed under current VIX regime?

    Args:
        vix: Current VIX spot
        candidate_score: Signal score of the candidate
        current_positions: Number of currently open positions
        vix_futures_front: Optional front-month VIX future
        vix_trend: Optional VIX trend label

    Returns:
        Dict with keys: allowed (bool), reason (str), params (VIXRegimeParams)
    """
    params = get_regime_params(vix, vix_futures_front, vix_trend)

    if params.max_positions == 0:
        return {
            "allowed": False,
            "reason": (
                f"VIX {vix:.1f} -> Regime {params.regime_label.value}: "
                f"no new positions allowed"
            ),
            "params": params,
        }

    if current_positions >= params.max_positions:
        return {
            "allowed": False,
            "reason": (
                f"Max positions reached ({current_positions}/{params.max_positions}) "
                f"at VIX {vix:.1f}"
            ),
            "params": params,
        }

    if candidate_score < params.min_score:
        return {
            "allowed": False,
            "reason": (
                f"Score {candidate_score:.1f} < Min {params.min_score:.1f} "
                f"at VIX {vix:.1f}"
            ),
            "params": params,
        }

    return {
        "allowed": True,
        "reason": (
            f"Score {candidate_score:.1f} >= {params.min_score:.1f}, "
            f"Pos {current_positions}/{params.max_positions}"
        ),
        "params": params,
    }
