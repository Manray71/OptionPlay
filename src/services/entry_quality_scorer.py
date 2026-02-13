# OptionPlay - Entry Quality Score (EQS)
# ========================================
"""
Entry Quality Score (EQS) -- bewertet wie guenstig der Einstiegszeitpunkt ist.

Der EQS ersetzt den Signal Score NICHT. Er gibt einen Bonus von bis zu 30%:
  Ranking Score = Signal Score * (1 + EQS_normalized * 0.3)

7 gewichtete Faktoren:
  1. IV Rank (20%)         - IV Range-Position, Sweet Spot 40-65%
  2. IV Percentile (15%)   - IV Haeufigkeitsverteilung
  3. Credit Ratio (20%)    - Credit / Spread-Breite
  4. Theta Efficiency (15%) - Theta / Credit Verhaeltnis
  5. Pullback (15%)        - Pullback-Tiefe (Mean Reversion)
  6. RSI (10%)             - RSI(14) Niveau
  7. Trend (5%)            - Trend-Alignment (SMA20 > SMA50 > SMA200)

Optimiert auf Capital Efficiency, NICHT auf Speed-to-50%.
(Speed Score wurde getestet und verworfen -- arbeitet gegen Profit.)

Verwendung:
    from src.services.entry_quality_scorer import EntryQualityScorer, get_entry_scorer

    scorer = get_entry_scorer()
    eq = scorer.score(
        iv_rank=55, iv_percentile=68,
        credit_pct=18.5, spread_theta=0.042, credit_bid=1.85,
        pullback_pct=-4.2, rsi=32, trend_bullish=True
    )
    print(f"EQS: {eq.eqs_total}/100")

Author: OptionPlay Team
Created: 2026-02-04
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..config.scoring_config import get_scoring_resolver as _get_resolver
from ..constants.trading_rules import SPREAD_MIN_CREDIT_PCT

logger = logging.getLogger(__name__)


# =============================================================================
# SCORING CONSTANTS (loaded from config/scoring_weights.yaml → entry_quality)
# =============================================================================

_eqs_cfg = _get_resolver().get_entry_quality_config()
_eqs_iv = _eqs_cfg.get("iv_rank", {})
_eqs_ivp = _eqs_cfg.get("iv_percentile", {})
_eqs_cr = _eqs_cfg.get("credit", {})
_eqs_th = _eqs_cfg.get("theta", {})
_eqs_pb = _eqs_cfg.get("pullback", {})
_eqs_rsi = _eqs_cfg.get("rsi", {})
_eqs_trend = _eqs_cfg.get("trend", {})

# General scoring limits
EQS_SCORE_MAX = _eqs_cfg.get("score_max", 100.0)
EQS_SCORE_NEUTRAL = _eqs_cfg.get("score_neutral", 50.0)

# Default bonus max percentage applied via apply_eqs_bonus
EQS_DEFAULT_BONUS_MAX_PCT = _eqs_cfg.get("bonus_max_pct", 0.3)

# --- IV Rank scoring (_score_iv_rank) ---
EQS_IV_RANK_ZONE_LOW = _eqs_iv.get("zone_low", 20)
EQS_IV_RANK_ZONE_MID_LOW = _eqs_iv.get("zone_mid_low", 40)
EQS_IV_RANK_ZONE_MID_HIGH = _eqs_iv.get("zone_mid_high", 65)
EQS_IV_RANK_ZONE_HIGH = _eqs_iv.get("zone_high", 80)
EQS_IV_RANK_MULT_LOW = _eqs_iv.get("mult_low", 2.5)
EQS_IV_RANK_MULT_MID_LOW = _eqs_iv.get("mult_mid_low", 1.5)
EQS_IV_RANK_MULT_MID_HIGH = _eqs_iv.get("mult_mid_high", 0.8)
EQS_IV_RANK_MULT_HIGH = _eqs_iv.get("mult_high", 1.333)
EQS_IV_RANK_FLOOR = _eqs_iv.get("floor", 30.0)

# --- IV Percentile scoring (_score_iv_percentile) ---
EQS_IV_PCT_ZONE_LOW = _eqs_ivp.get("zone_low", 30)
EQS_IV_PCT_ZONE_MID = _eqs_ivp.get("zone_mid", 50)
EQS_IV_PCT_ZONE_HIGH = _eqs_ivp.get("zone_high", 80)
EQS_IV_PCT_SCORE_LOW = _eqs_ivp.get("score_low", 30)
EQS_IV_PCT_SCORE_MID = _eqs_ivp.get("score_mid", 70)
EQS_IV_PCT_MULT_LOW = _eqs_ivp.get("mult_low", 1.0)
EQS_IV_PCT_MULT_MID = _eqs_ivp.get("mult_mid", 2.0)
EQS_IV_PCT_MULT_HIGH = _eqs_ivp.get("mult_high", 1.0)
EQS_IV_PCT_DECAY_MULT = _eqs_ivp.get("decay_mult", 1.5)
EQS_IV_PCT_FLOOR = _eqs_ivp.get("floor", 50.0)

# --- Credit Ratio scoring (_score_credit_ratio) ---
# EQS_CREDIT_MIN_PCT uses SPREAD_MIN_CREDIT_PCT from trading_rules (10%)
EQS_CREDIT_MID_PCT = _eqs_cr.get("mid_pct", 15)
EQS_CREDIT_HIGH_PCT = _eqs_cr.get("high_pct", 25)
EQS_CREDIT_MULT_LOW = _eqs_cr.get("mult_low", 12)
EQS_CREDIT_SCORE_MID = _eqs_cr.get("score_mid", 60)
EQS_CREDIT_MULT_HIGH = _eqs_cr.get("mult_high", 4)

# --- Theta Efficiency scoring (_score_theta_efficiency) ---
EQS_THETA_PCT_CONVERSION = _eqs_th.get("pct_conversion", 100)
EQS_THETA_MULTIPLIER = _eqs_th.get("multiplier", 25)

# --- Pullback scoring (_score_pullback_pct) ---
EQS_PULLBACK_ZONE_MINIMAL = _eqs_pb.get("zone_minimal", 1)
EQS_PULLBACK_ZONE_SHALLOW = _eqs_pb.get("zone_shallow", 3)
EQS_PULLBACK_ZONE_SWEET = _eqs_pb.get("zone_sweet", 8)
EQS_PULLBACK_ZONE_DEEP = _eqs_pb.get("zone_deep", 12)
EQS_PULLBACK_SCORE_MINIMAL = _eqs_pb.get("score_minimal", 20)
EQS_PULLBACK_MULT_SHALLOW = _eqs_pb.get("mult_shallow", 20)
EQS_PULLBACK_MULT_SWEET = _eqs_pb.get("mult_sweet", 8)
EQS_PULLBACK_MULT_DEEP = _eqs_pb.get("mult_deep", 10)
EQS_PULLBACK_FLOOR = _eqs_pb.get("floor", 30.0)

# --- RSI scoring (_score_rsi) ---
EQS_RSI_ZONE_VERY_LOW = _eqs_rsi.get("zone_very_low", 25)
EQS_RSI_ZONE_OVERSOLD = _eqs_rsi.get("zone_oversold", 35)
EQS_RSI_ZONE_NEUTRAL = _eqs_rsi.get("zone_neutral", 50)
EQS_RSI_ZONE_OVERBOUGHT = _eqs_rsi.get("zone_overbought", 70)
EQS_RSI_SCORE_OVERSOLD = _eqs_rsi.get("score_oversold", 70)
EQS_RSI_SCORE_NEUTRAL = _eqs_rsi.get("score_neutral", 40)
EQS_RSI_SCORE_OVERBOUGHT = _eqs_rsi.get("score_overbought", 20)
EQS_RSI_MULT_OVERSOLD = _eqs_rsi.get("mult_oversold", 3)
EQS_RSI_MULT_NEUTRAL = _eqs_rsi.get("mult_neutral", 2)

# --- Trend scoring ---
EQS_TREND_BULLISH = _eqs_trend.get("bullish", 100.0)
EQS_TREND_BEARISH = _eqs_trend.get("bearish", 30.0)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class EntryQuality:
    """Bewertung der Entry-Qualitaet."""

    eqs_total: float  # 0-100
    eqs_normalized: float  # 0.0-1.0

    # Einzelfaktoren (0-100 jeweils)
    iv_rank_score: float
    iv_percentile_score: float
    credit_ratio_score: float
    theta_efficiency_score: float
    pullback_score: float
    rsi_score: float
    trend_score: float

    # Rohdaten
    iv_rank: Optional[float]
    iv_percentile: Optional[float]
    credit_pct: Optional[float]
    theta_per_day: Optional[float]
    pullback_pct: Optional[float]
    rsi: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        """Gibt Entry Quality als Dict zurueck."""
        return {
            "eqs_total": self.eqs_total,
            "eqs_normalized": self.eqs_normalized,
            "factors": {
                "iv_rank": self.iv_rank_score,
                "iv_percentile": self.iv_percentile_score,
                "credit_ratio": self.credit_ratio_score,
                "theta_efficiency": self.theta_efficiency_score,
                "pullback": self.pullback_score,
                "rsi": self.rsi_score,
                "trend": self.trend_score,
            },
            "raw": {
                "iv_rank": self.iv_rank,
                "iv_percentile": self.iv_percentile,
                "credit_pct": self.credit_pct,
                "theta_per_day": self.theta_per_day,
                "pullback_pct": self.pullback_pct,
                "rsi": self.rsi,
            },
        }


# =============================================================================
# ENTRY QUALITY SCORER
# =============================================================================


class EntryQualityScorer:
    """
    Bewertet Entry-Timing-Qualitaet basierend auf IV, Momentum, Technicals.

    Gewichtung der 7 Faktoren summiert sich zu 1.0.
    Jeder Faktor wird auf 0-100 skaliert.
    EQS = gewichtete Summe aller Faktoren.
    """

    # Gewichtung der Faktoren (Summe = 1.0), loaded from config
    _DEFAULT_WEIGHTS: dict[str, float] = {
        "iv_rank": 0.20,
        "iv_percentile": 0.15,
        "credit_ratio": 0.20,
        "theta_efficiency": 0.15,
        "pullback": 0.15,
        "rsi": 0.10,
        "trend": 0.05,
    }
    WEIGHTS: dict[str, float] = {
        **_DEFAULT_WEIGHTS,
        **_eqs_cfg.get("weights", {}),
    }

    def score(
        self,
        iv_rank: Optional[float] = None,
        iv_percentile: Optional[float] = None,
        credit_pct: Optional[float] = None,
        spread_theta: Optional[float] = None,
        credit_bid: Optional[float] = None,
        pullback_pct: Optional[float] = None,
        rsi: Optional[float] = None,
        trend_bullish: bool = False,
    ) -> EntryQuality:
        """
        Berechnet den Entry Quality Score.

        Args:
            iv_rank: IV Rank 0-100 (None wenn nicht verfuegbar)
            iv_percentile: IV Percentile 0-100 (None wenn nicht verfuegbar)
            credit_pct: Credit als % der Spread-Breite (z.B. 18.5)
            spread_theta: Taeglicher Theta des Spreads in $ (z.B. 0.042)
            credit_bid: Absolute Credit in $ (Bid, z.B. 1.85)
            pullback_pct: Abstand zum 52w-High in % (negativ, z.B. -4.2)
            rsi: RSI(14) Wert (0-100)
            trend_bullish: True wenn SMA20 > SMA50 > SMA200

        Returns:
            EntryQuality mit gewichtetem Score und Einzelfaktoren
        """
        scores: dict[str, float] = {}

        # --- IV Rank Score ---
        # Sweet Spot: 40-65% -> hoechstes IV-Crush-Potenzial
        # Unter 20%: Zu wenig Premium
        # Ueber 80%: Warnung (Event-Risiko?)
        scores["iv_rank"] = self._score_iv_rank(iv_rank)

        # --- IV Percentile Score ---
        # Hohes Percentile (>50%) = IV ist haeufiger niedriger = guter Entry
        # Percentile 60-80% ist ideal
        scores["iv_percentile"] = self._score_iv_percentile(iv_percentile)

        # --- Credit Ratio Score ---
        # Minimum 10% (PLAYBOOK). Mehr ist besser, aber mit abnehmendem Grenznutzen
        scores["credit_ratio"] = self._score_credit_ratio(credit_pct)

        # --- Theta Efficiency Score ---
        # Theta pro Tag / Credit -> wie schnell decayed der Spread relativ zum Credit?
        scores["theta_efficiency"] = self._score_theta_efficiency(spread_theta, credit_bid)

        # --- Pullback Score ---
        # Tiefer Dip = besserer Entry (Mean Reversion)
        scores["pullback"] = self._score_pullback(pullback_pct)

        # --- RSI Score ---
        # Ueberverkauft (<35) ist gut fuer Bull-Put (Bounce wahrscheinlich)
        scores["rsi"] = self._score_rsi(rsi)

        # --- Trend Score ---
        scores["trend"] = EQS_TREND_BULLISH if trend_bullish else EQS_TREND_BEARISH

        # --- Gewichteter Gesamtscore ---
        eqs_total = sum(scores[factor] * weight for factor, weight in self.WEIGHTS.items())
        eqs_normalized = eqs_total / EQS_SCORE_MAX  # 0.0-1.0

        return EntryQuality(
            eqs_total=round(eqs_total, 1),
            eqs_normalized=round(eqs_normalized, 3),
            iv_rank_score=round(scores["iv_rank"], 1),
            iv_percentile_score=round(scores["iv_percentile"], 1),
            credit_ratio_score=round(scores["credit_ratio"], 1),
            theta_efficiency_score=round(scores["theta_efficiency"], 1),
            pullback_score=round(scores["pullback"], 1),
            rsi_score=round(scores["rsi"], 1),
            trend_score=round(scores["trend"], 1),
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            credit_pct=credit_pct,
            theta_per_day=spread_theta,
            pullback_pct=pullback_pct,
            rsi=rsi,
        )

    # =========================================================================
    # SCORING FUNCTIONS (jeweils 0-100)
    # =========================================================================

    @staticmethod
    def _score_iv_rank(iv_rank: Optional[float]) -> float:
        """
        IV Rank Score.

        Sweet Spot: 40-65% (hoechstes IV-Crush-Potenzial).
        < 20%: zu wenig Premium.
        > 80%: Event-Risiko-Warnung.
        """
        if iv_rank is None:
            return EQS_SCORE_NEUTRAL  # Neutral wenn nicht verfuegbar

        if iv_rank < EQS_IV_RANK_ZONE_LOW:
            return iv_rank * EQS_IV_RANK_MULT_LOW  # 0 -> 0, 20 -> 50
        elif iv_rank < EQS_IV_RANK_ZONE_MID_LOW:
            return (
                50 + (iv_rank - EQS_IV_RANK_ZONE_LOW) * EQS_IV_RANK_MULT_MID_LOW
            )  # 20 -> 50, 40 -> 80
        elif iv_rank <= EQS_IV_RANK_ZONE_MID_HIGH:
            return (
                80 + (iv_rank - EQS_IV_RANK_ZONE_MID_LOW) * EQS_IV_RANK_MULT_MID_HIGH
            )  # 40 -> 80, 65 -> 100
        elif iv_rank <= EQS_IV_RANK_ZONE_HIGH:
            return (
                EQS_SCORE_MAX - (iv_rank - EQS_IV_RANK_ZONE_MID_HIGH) * EQS_IV_RANK_MULT_HIGH
            )  # 65 -> 100, 80 -> 80
        else:
            return max(
                EQS_IV_RANK_FLOOR, 80 - (iv_rank - EQS_IV_RANK_ZONE_HIGH)
            )  # 80 -> 80, 100 -> 60, min 30

    @staticmethod
    def _score_iv_percentile(iv_percentile: Optional[float]) -> float:
        """
        IV Percentile Score.

        Hohes Percentile (>50%) = IV ist haeufiger niedriger = guter Entry.
        60-80% ist ideal.
        """
        if iv_percentile is None:
            return EQS_SCORE_NEUTRAL  # Neutral

        if iv_percentile < EQS_IV_PCT_ZONE_LOW:
            return iv_percentile * EQS_IV_PCT_MULT_LOW  # 0 -> 0, 30 -> 30
        elif iv_percentile < EQS_IV_PCT_ZONE_MID:
            return (
                EQS_IV_PCT_SCORE_LOW + (iv_percentile - EQS_IV_PCT_ZONE_LOW) * EQS_IV_PCT_MULT_MID
            )  # 30 -> 30, 50 -> 70
        elif iv_percentile <= EQS_IV_PCT_ZONE_HIGH:
            return (
                EQS_IV_PCT_SCORE_MID + (iv_percentile - EQS_IV_PCT_ZONE_MID) * EQS_IV_PCT_MULT_HIGH
            )  # 50 -> 70, 80 -> 100
        else:
            return max(
                EQS_IV_PCT_FLOOR,
                EQS_SCORE_MAX - (iv_percentile - EQS_IV_PCT_ZONE_HIGH) * EQS_IV_PCT_DECAY_MULT,
            )  # 80 -> 100, 100 -> 70, min 50

    @staticmethod
    def _score_credit_ratio(credit_pct: Optional[float]) -> float:
        """
        Credit Ratio Score.

        Minimum 10% (PLAYBOOK). Mehr ist besser, mit abnehmendem Grenznutzen.
        """
        if credit_pct is None:
            return 0.0  # Kein Credit -> Score 0

        if credit_pct < SPREAD_MIN_CREDIT_PCT:
            return 0.0  # Unter Minimum
        elif credit_pct < EQS_CREDIT_MID_PCT:
            return (credit_pct - SPREAD_MIN_CREDIT_PCT) * EQS_CREDIT_MULT_LOW  # 10 -> 0, 15 -> 60
        elif credit_pct < EQS_CREDIT_HIGH_PCT:
            return (
                EQS_CREDIT_SCORE_MID + (credit_pct - EQS_CREDIT_MID_PCT) * EQS_CREDIT_MULT_HIGH
            )  # 15 -> 60, 25 -> 100
        else:
            return EQS_SCORE_MAX  # Cap

    @staticmethod
    def _score_theta_efficiency(
        spread_theta: Optional[float],
        credit_bid: Optional[float],
    ) -> float:
        """
        Theta Efficiency Score.

        Theta pro Tag / Credit -> wie schnell decayed der Spread relativ zum Credit?
        ~2-5% pro Tag ist typisch.
        """
        if not spread_theta or not credit_bid or credit_bid <= 0:
            return EQS_SCORE_NEUTRAL  # Neutral

        theta_ratio = abs(spread_theta) / credit_bid * EQS_THETA_PCT_CONVERSION  # In %
        return min(EQS_SCORE_MAX, theta_ratio * EQS_THETA_MULTIPLIER)

    @staticmethod
    def _score_pullback(pullback_pct: Optional[float]) -> float:
        """
        Pullback Score.

        Tiefer Dip = besserer Entry (Mean Reversion).
        -2% bis -8% ist Sweet Spot, tiefer als -10% ist Warnung.
        """
        if pullback_pct is None:
            return EQS_SCORE_NEUTRAL  # Neutral

        depth = abs(pullback_pct)

        if depth < EQS_PULLBACK_ZONE_MINIMAL:
            return float(EQS_PULLBACK_SCORE_MINIMAL)  # Kaum Pullback
        elif depth < EQS_PULLBACK_ZONE_SHALLOW:
            return (
                EQS_PULLBACK_SCORE_MINIMAL
                + (depth - EQS_PULLBACK_ZONE_MINIMAL) * EQS_PULLBACK_MULT_SHALLOW
            )  # 1% -> 20, 3% -> 60
        elif depth <= EQS_PULLBACK_ZONE_SWEET:
            return (
                60 + (depth - EQS_PULLBACK_ZONE_SHALLOW) * EQS_PULLBACK_MULT_SWEET
            )  # 3% -> 60, 8% -> 100
        elif depth <= EQS_PULLBACK_ZONE_DEEP:
            return (
                EQS_SCORE_MAX - (depth - EQS_PULLBACK_ZONE_SWEET) * EQS_PULLBACK_MULT_DEEP
            )  # 8% -> 100, 12% -> 60
        else:
            return EQS_PULLBACK_FLOOR  # Zu tief, Warnung

    @staticmethod
    def _score_rsi(rsi: Optional[float]) -> float:
        """
        RSI Score.

        Ueberverkauft (<35) ist gut fuer Bull-Put (Bounce wahrscheinlich).
        """
        if rsi is None:
            return EQS_SCORE_NEUTRAL  # Neutral

        if rsi < EQS_RSI_ZONE_VERY_LOW:
            return EQS_SCORE_MAX  # Stark ueberverkauft
        elif rsi < EQS_RSI_ZONE_OVERSOLD:
            return (
                EQS_RSI_SCORE_OVERSOLD + (EQS_RSI_ZONE_OVERSOLD - rsi) * EQS_RSI_MULT_OVERSOLD
            )  # 25 -> 100, 35 -> 70
        elif rsi < EQS_RSI_ZONE_NEUTRAL:
            return (
                EQS_RSI_SCORE_NEUTRAL + (EQS_RSI_ZONE_NEUTRAL - rsi) * EQS_RSI_MULT_NEUTRAL
            )  # 35 -> 70, 50 -> 40
        elif rsi < EQS_RSI_ZONE_OVERBOUGHT:
            return float(EQS_RSI_SCORE_NEUTRAL)  # Neutral
        else:
            return float(EQS_RSI_SCORE_OVERBOUGHT)  # Ueberkauft -- weniger ideal

    def apply_eqs_bonus(
        self,
        signal_score: float,
        entry_quality: EntryQuality,
        max_bonus_pct: float = EQS_DEFAULT_BONUS_MAX_PCT,
    ) -> float:
        """
        Wendet EQS-Bonus auf Signal Score an.

        Ranking Score = Signal Score * (1 + EQS_normalized * max_bonus_pct)

        Args:
            signal_score: Urspruenglicher Signal Score (0-10)
            entry_quality: EntryQuality Objekt
            max_bonus_pct: Maximaler Bonus (Default: 30%)

        Returns:
            Angepasster Ranking Score
        """
        bonus = entry_quality.eqs_normalized * max_bonus_pct
        return round(signal_score * (1 + bonus), 2)


# =============================================================================
# SINGLETON
# =============================================================================

_entry_scorer: Optional[EntryQualityScorer] = None


def get_entry_scorer() -> EntryQualityScorer:
    """Gibt Singleton EntryQualityScorer-Instanz zurueck."""
    global _entry_scorer
    if _entry_scorer is None:
        _entry_scorer = EntryQualityScorer()
    return _entry_scorer


def reset_entry_scorer() -> None:
    """Setzt Singleton zurueck (fuer Tests)."""
    global _entry_scorer
    _entry_scorer = None
