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
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class EntryQuality:
    """Bewertung der Entry-Qualitaet."""
    eqs_total: float          # 0-100
    eqs_normalized: float     # 0.0-1.0

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
            'eqs_total': self.eqs_total,
            'eqs_normalized': self.eqs_normalized,
            'factors': {
                'iv_rank': self.iv_rank_score,
                'iv_percentile': self.iv_percentile_score,
                'credit_ratio': self.credit_ratio_score,
                'theta_efficiency': self.theta_efficiency_score,
                'pullback': self.pullback_score,
                'rsi': self.rsi_score,
                'trend': self.trend_score,
            },
            'raw': {
                'iv_rank': self.iv_rank,
                'iv_percentile': self.iv_percentile,
                'credit_pct': self.credit_pct,
                'theta_per_day': self.theta_per_day,
                'pullback_pct': self.pullback_pct,
                'rsi': self.rsi,
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

    # Gewichtung der Faktoren (Summe = 1.0)
    WEIGHTS: dict[str, float] = {
        "iv_rank":          0.20,  # IV Range-Position
        "iv_percentile":    0.15,  # IV Haeufigkeitsverteilung
        "credit_ratio":     0.20,  # Credit / Spread-Breite
        "theta_efficiency": 0.15,  # Theta / Credit Verhaeltnis
        "pullback":         0.15,  # Pullback-Tiefe
        "rsi":              0.10,  # RSI(14) Niveau
        "trend":            0.05,  # Trend-Alignment
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
        scores["theta_efficiency"] = self._score_theta_efficiency(
            spread_theta, credit_bid
        )

        # --- Pullback Score ---
        # Tiefer Dip = besserer Entry (Mean Reversion)
        scores["pullback"] = self._score_pullback(pullback_pct)

        # --- RSI Score ---
        # Ueberverkauft (<35) ist gut fuer Bull-Put (Bounce wahrscheinlich)
        scores["rsi"] = self._score_rsi(rsi)

        # --- Trend Score ---
        scores["trend"] = 100.0 if trend_bullish else 30.0

        # --- Gewichteter Gesamtscore ---
        eqs_total = sum(
            scores[factor] * weight
            for factor, weight in self.WEIGHTS.items()
        )
        eqs_normalized = eqs_total / 100.0  # 0.0-1.0

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
            return 50.0  # Neutral wenn nicht verfuegbar

        if iv_rank < 20:
            return iv_rank * 2.5                      # 0 -> 0, 20 -> 50
        elif iv_rank < 40:
            return 50 + (iv_rank - 20) * 1.5          # 20 -> 50, 40 -> 80
        elif iv_rank <= 65:
            return 80 + (iv_rank - 40) * 0.8          # 40 -> 80, 65 -> 100
        elif iv_rank <= 80:
            return 100 - (iv_rank - 65) * 1.333       # 65 -> 100, 80 -> 80
        else:
            return max(30.0, 80 - (iv_rank - 80))     # 80 -> 80, 100 -> 60, min 30

    @staticmethod
    def _score_iv_percentile(iv_percentile: Optional[float]) -> float:
        """
        IV Percentile Score.

        Hohes Percentile (>50%) = IV ist haeufiger niedriger = guter Entry.
        60-80% ist ideal.
        """
        if iv_percentile is None:
            return 50.0  # Neutral

        if iv_percentile < 30:
            return iv_percentile * 1.0                  # 0 -> 0, 30 -> 30
        elif iv_percentile < 50:
            return 30 + (iv_percentile - 30) * 2.0      # 30 -> 30, 50 -> 70
        elif iv_percentile <= 80:
            return 70 + (iv_percentile - 50) * 1.0      # 50 -> 70, 80 -> 100
        else:
            return max(50.0, 100 - (iv_percentile - 80) * 1.5)  # 80 -> 100, 100 -> 70, min 50

    @staticmethod
    def _score_credit_ratio(credit_pct: Optional[float]) -> float:
        """
        Credit Ratio Score.

        Minimum 10% (PLAYBOOK). Mehr ist besser, mit abnehmendem Grenznutzen.
        """
        if credit_pct is None:
            return 0.0  # Kein Credit -> Score 0

        if credit_pct < 10:
            return 0.0                                  # Unter Minimum
        elif credit_pct < 15:
            return (credit_pct - 10) * 12               # 10 -> 0, 15 -> 60
        elif credit_pct < 25:
            return 60 + (credit_pct - 15) * 4           # 15 -> 60, 25 -> 100
        else:
            return 100.0                                # Cap

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
            return 50.0  # Neutral

        theta_ratio = abs(spread_theta) / credit_bid * 100  # In %
        return min(100.0, theta_ratio * 25)

    @staticmethod
    def _score_pullback(pullback_pct: Optional[float]) -> float:
        """
        Pullback Score.

        Tiefer Dip = besserer Entry (Mean Reversion).
        -2% bis -8% ist Sweet Spot, tiefer als -10% ist Warnung.
        """
        if pullback_pct is None:
            return 50.0  # Neutral

        depth = abs(pullback_pct)

        if depth < 1:
            return 20.0                                # Kaum Pullback
        elif depth < 3:
            return 20 + (depth - 1) * 20               # 1% -> 20, 3% -> 60
        elif depth <= 8:
            return 60 + (depth - 3) * 8                # 3% -> 60, 8% -> 100
        elif depth <= 12:
            return 100 - (depth - 8) * 10              # 8% -> 100, 12% -> 60
        else:
            return 30.0                                # Zu tief, Warnung

    @staticmethod
    def _score_rsi(rsi: Optional[float]) -> float:
        """
        RSI Score.

        Ueberverkauft (<35) ist gut fuer Bull-Put (Bounce wahrscheinlich).
        """
        if rsi is None:
            return 50.0  # Neutral

        if rsi < 25:
            return 100.0                               # Stark ueberverkauft
        elif rsi < 35:
            return 70 + (35 - rsi) * 3                 # 25 -> 100, 35 -> 70
        elif rsi < 50:
            return 40 + (50 - rsi) * 2                 # 35 -> 70, 50 -> 40
        elif rsi < 70:
            return 40.0                                # Neutral
        else:
            return 20.0                                # Ueberkauft -- weniger ideal

    def apply_eqs_bonus(
        self,
        signal_score: float,
        entry_quality: EntryQuality,
        max_bonus_pct: float = 0.3,
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
