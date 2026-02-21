# OptionPlay - Enhanced Scoring for Daily Picks
# ===============================================
"""
Adds bonus components to the base signal score,
then re-ranks daily picks by enhanced score.

Only used by daily_picks() — regular scans are unaffected.

Modes:
  - "additive" (legacy): enhanced = base + sum(bonuses)
  - "multiplicative" (default): enhanced = base × (1 + sum(multipliers))
    Max factor 1.28 → a 7.0 becomes max 8.96, a 4.0 becomes max 5.12
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "enhanced_scoring.yaml"

# ---------------------------------------------------------------------------
# Config singleton
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_instance: Optional[EnhancedScoringConfig] = None


class EnhancedScoringConfig:
    """Thread-safe singleton that loads enhanced_scoring.yaml."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        path = config_path or _CONFIG_PATH
        with open(path) as f:
            self._data: Dict[str, Any] = yaml.safe_load(f)

    # -- accessors ----------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._data.get("mode", "additive")

    @property
    def liquidity_bonus(self) -> Dict[str, float]:
        return self._data.get("liquidity_bonus", {})

    @property
    def credit_bonus(self) -> Dict[str, Any]:
        return self._data.get("credit_bonus", {})

    @property
    def pullback_bonus(self) -> Dict[str, Any]:
        return self._data.get("pullback_bonus", {})

    @property
    def stability_bonus(self) -> Dict[str, Any]:
        return self._data.get("stability_bonus", {})

    @property
    def multiplicative(self) -> Dict[str, Any]:
        return self._data.get("multiplicative", {})

    @property
    def quality_filter(self) -> Dict[str, Any]:
        return self._data.get("quality_filter", {})

    @property
    def overfetch_factor(self) -> int:
        return int(self._data.get("overfetch_factor", 5))


def get_enhanced_scoring_config(
    config_path: Optional[Path] = None,
) -> EnhancedScoringConfig:
    """Return (or create) the singleton config instance."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = EnhancedScoringConfig(config_path)
    return _instance


def reset_enhanced_scoring_config() -> None:
    """Reset the singleton — primarily for tests."""
    global _instance
    with _lock:
        _instance = None


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnhancedScoreResult:
    """Holds the enhanced score and its breakdown."""

    base_score: float
    liquidity_bonus: float = 0.0
    credit_bonus: float = 0.0
    pullback_bonus: float = 0.0
    stability_bonus: float = 0.0
    mode: str = "additive"

    @property
    def total_bonus(self) -> float:
        return self.liquidity_bonus + self.credit_bonus + self.pullback_bonus + self.stability_bonus

    @property
    def bonus_factor(self) -> float:
        """Multiplicative factor: 1.0 + sum of multipliers."""
        return 1.0 + self.total_bonus

    @property
    def enhanced_score(self) -> float:
        if self.mode == "multiplicative":
            return self.base_score * self.bonus_factor
        return self.base_score + self.total_bonus

    def bonus_breakdown_str(self) -> str:
        """Human-readable breakdown."""
        if self.mode == "multiplicative":
            return self._mult_breakdown_str()
        return self._additive_breakdown_str()

    def _additive_breakdown_str(self) -> str:
        """e.g. 'Liq+2.0 Cred+1.0 Pull+0.5 Stab+1.0 = +4.5'"""
        parts: list[str] = []
        if self.liquidity_bonus > 0:
            parts.append(f"Liq+{self.liquidity_bonus:.1f}")
        if self.credit_bonus > 0:
            parts.append(f"Cred+{self.credit_bonus:.1f}")
        if self.pullback_bonus > 0:
            parts.append(f"Pull+{self.pullback_bonus:.1f}")
        if self.stability_bonus > 0:
            parts.append(f"Stab+{self.stability_bonus:.1f}")
        if not parts:
            return "no bonus"
        return f"{' '.join(parts)} = +{self.total_bonus:.1f}"

    def _mult_breakdown_str(self) -> str:
        """e.g. '×1.23 (Liq+10% Cred+8% Stab+5%)'"""
        parts: list[str] = []
        if self.liquidity_bonus > 0:
            parts.append(f"Liq+{self.liquidity_bonus * 100:.0f}%")
        if self.credit_bonus > 0:
            parts.append(f"Cred+{self.credit_bonus * 100:.0f}%")
        if self.pullback_bonus > 0:
            parts.append(f"Pull+{self.pullback_bonus * 100:.0f}%")
        if self.stability_bonus > 0:
            parts.append(f"Stab+{self.stability_bonus * 100:.0f}%")
        if not parts:
            return "no bonus"
        return f"\u00d7{self.bonus_factor:.2f} ({' '.join(parts)})"


# ---------------------------------------------------------------------------
# Additive scoring functions (legacy)
# ---------------------------------------------------------------------------


def calculate_liquidity_bonus(
    liquidity_quality: Optional[str],
    config: Optional[EnhancedScoringConfig] = None,
) -> float:
    """Map liquidity_quality string to bonus points."""
    if not liquidity_quality:
        return 0.0
    cfg = config or get_enhanced_scoring_config()
    return float(cfg.liquidity_bonus.get(liquidity_quality.lower(), 0.0))


def calculate_credit_bonus(
    credit: Optional[float],
    spread_width: Optional[float],
    config: Optional[EnhancedScoringConfig] = None,
) -> float:
    """Bonus based on return_pct = (credit / spread_width) * 100."""
    if not credit or not spread_width or spread_width <= 0:
        return 0.0
    cfg = config or get_enhanced_scoring_config()
    return_pct = (credit / spread_width) * 100

    for bracket in cfg.credit_bonus.get("brackets", []):
        if return_pct >= bracket["min_pct"]:
            return float(bracket["bonus"])

    return float(cfg.credit_bonus.get("default", 0.0))


def calculate_pullback_bonus(
    signal_details: Optional[Dict[str, Any]],
    config: Optional[EnhancedScoringConfig] = None,
) -> float:
    """Bonus when price is above key SMAs (healthy trend pullback)."""
    if not signal_details:
        return 0.0
    cfg = config or get_enhanced_scoring_config()
    pb = cfg.pullback_bonus

    # Navigate: details["score_breakdown"]["components"]["moving_averages"]
    breakdown = signal_details.get("score_breakdown")
    if not isinstance(breakdown, dict):
        return float(pb.get("default", 0.0))

    components = breakdown.get("components")
    if not isinstance(components, dict):
        return float(pb.get("default", 0.0))

    ma = components.get("moving_averages")
    if not isinstance(ma, dict):
        return float(pb.get("default", 0.0))

    vs_sma20 = ma.get("vs_sma20", "")
    vs_sma200 = ma.get("vs_sma200", "")

    above_sma20 = vs_sma20 == "above"
    above_sma200 = vs_sma200 == "above"

    if above_sma20 and above_sma200:
        return float(pb.get("both_above", 1.0))
    if above_sma200:
        return float(pb.get("sma200_above_only", 0.5))
    return float(pb.get("default", 0.0))


def calculate_stability_bonus(
    stability_score: Optional[float],
    config: Optional[EnhancedScoringConfig] = None,
) -> float:
    """Bonus for high-stability symbols."""
    if stability_score is None:
        return 0.0
    cfg = config or get_enhanced_scoring_config()
    sb = cfg.stability_bonus

    for bracket in sb.get("brackets", []):
        if stability_score >= bracket["min_score"]:
            return float(bracket["bonus"])

    return float(sb.get("default", 0.0))


# ---------------------------------------------------------------------------
# Multiplicative scoring functions
# ---------------------------------------------------------------------------


def calculate_liquidity_mult(
    liquidity_quality: Optional[str],
    config: Optional[EnhancedScoringConfig] = None,
) -> float:
    """Map liquidity_quality string to multiplier bonus."""
    if not liquidity_quality:
        return 0.0
    cfg = config or get_enhanced_scoring_config()
    liq = cfg.multiplicative.get("liquidity", {})
    return float(liq.get(liquidity_quality.lower(), 0.0))


def calculate_credit_mult(
    credit: Optional[float],
    spread_width: Optional[float],
    config: Optional[EnhancedScoringConfig] = None,
) -> float:
    """Multiplier based on return_pct = (credit / spread_width) * 100."""
    if not credit or not spread_width or spread_width <= 0:
        return 0.0
    cfg = config or get_enhanced_scoring_config()
    cred = cfg.multiplicative.get("credit", {})
    return_pct = (credit / spread_width) * 100

    for bracket in cred.get("brackets", []):
        if return_pct >= bracket["min_pct"]:
            return float(bracket["mult"])

    return float(cred.get("default", 0.0))


def calculate_pullback_mult(
    signal_details: Optional[Dict[str, Any]],
    config: Optional[EnhancedScoringConfig] = None,
) -> float:
    """Multiplier when price is above key SMAs."""
    if not signal_details:
        return 0.0
    cfg = config or get_enhanced_scoring_config()
    pb = cfg.multiplicative.get("pullback", {})

    breakdown = signal_details.get("score_breakdown")
    if not isinstance(breakdown, dict):
        return float(pb.get("default", 0.0))

    components = breakdown.get("components")
    if not isinstance(components, dict):
        return float(pb.get("default", 0.0))

    ma = components.get("moving_averages")
    if not isinstance(ma, dict):
        return float(pb.get("default", 0.0))

    vs_sma20 = ma.get("vs_sma20", "")
    vs_sma200 = ma.get("vs_sma200", "")

    above_sma20 = vs_sma20 == "above"
    above_sma200 = vs_sma200 == "above"

    if above_sma20 and above_sma200:
        return float(pb.get("both_above", 0.05))
    if above_sma200:
        return float(pb.get("sma200_above_only", 0.025))
    return float(pb.get("default", 0.0))


def calculate_stability_mult(
    stability_score: Optional[float],
    config: Optional[EnhancedScoringConfig] = None,
) -> float:
    """Multiplier for high-stability symbols."""
    if stability_score is None:
        return 0.0
    cfg = config or get_enhanced_scoring_config()
    sb = cfg.multiplicative.get("stability", {})

    for bracket in sb.get("brackets", []):
        if stability_score >= bracket["min_score"]:
            return float(bracket["mult"])

    return float(sb.get("default", 0.0))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def calculate_enhanced_score(
    pick: Any,
    signal: Any,
    config: Optional[EnhancedScoringConfig] = None,
) -> EnhancedScoreResult:
    """
    Compute enhanced score for a DailyPick that already has strikes.

    Args:
        pick: DailyPick with suggested_strikes populated
        signal: Original TradeSignal (for score_breakdown access)
        config: Optional config override (for tests)

    Returns:
        EnhancedScoreResult with bonus breakdown
    """
    cfg = config or get_enhanced_scoring_config()
    base = pick.score
    signal_details = signal.details if signal else None

    # Extract common inputs
    liq_quality = None
    credit = None
    spread_width = None
    if pick.suggested_strikes:
        liq_quality = pick.suggested_strikes.liquidity_quality
        credit = pick.suggested_strikes.estimated_credit
        spread_width = pick.suggested_strikes.spread_width

    if cfg.mode == "multiplicative":
        return EnhancedScoreResult(
            base_score=base,
            liquidity_bonus=calculate_liquidity_mult(liq_quality, cfg),
            credit_bonus=calculate_credit_mult(credit, spread_width, cfg),
            pullback_bonus=calculate_pullback_mult(signal_details, cfg),
            stability_bonus=calculate_stability_mult(pick.stability_score, cfg),
            mode="multiplicative",
        )

    # Additive (legacy)
    return EnhancedScoreResult(
        base_score=base,
        liquidity_bonus=calculate_liquidity_bonus(liq_quality, cfg),
        credit_bonus=calculate_credit_bonus(credit, spread_width, cfg),
        pullback_bonus=calculate_pullback_bonus(signal_details, cfg),
        stability_bonus=calculate_stability_bonus(pick.stability_score, cfg),
        mode="additive",
    )
