# OptionPlay - Strategy Score Breakdowns
# =======================================
# Dataclasses für detaillierte Score-Aufschlüsselung aller Strategien

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class BounceScoreBreakdown:
    """Detaillierte Aufschlüsselung des Bounce-Scores"""

    # Support-Test Score (0-3)
    support_score: float = 0
    support_level: Optional[float] = None
    support_distance_pct: float = 0
    support_strength: str = ""  # weak, moderate, strong
    support_touches: int = 0
    support_reason: str = ""

    # RSI Score (0-2)
    rsi_score: float = 0
    rsi_value: float = 0
    rsi_reason: str = ""

    # RSI Divergenz Score (0-3) - NEU
    # Bullische Divergenz: Kurs tieferes Tief, RSI höheres Tief → Verkaufsdruck lässt nach
    # Bärische Divergenz: Kurs höheres Hoch, RSI tieferes Hoch → Kaufdruck lässt nach
    rsi_divergence_score: float = 0
    rsi_divergence_type: Optional[str] = None  # 'bullish', 'bearish', or None
    rsi_divergence_strength: float = 0
    rsi_divergence_formation_days: int = 0
    rsi_divergence_reason: str = ""

    # Candlestick Pattern Score (0-2)
    candlestick_score: float = 0
    candlestick_pattern: Optional[str] = None
    candlestick_bullish: bool = False
    candlestick_reason: str = ""

    # Volume Score (0-2) - erweitert
    volume_score: float = 0
    volume_ratio: float = 0
    volume_trend: str = ""  # decreasing, stable, increasing
    volume_reason: str = ""

    # Trend Score (0-2)
    trend_score: float = 0
    trend_status: str = ""  # uptrend, pullback_in_uptrend, downtrend
    trend_reason: str = ""

    # MACD Score (0-2) - NEU
    macd_score: float = 0
    macd_signal: Optional[str] = None
    macd_histogram: float = 0
    macd_reason: str = ""

    # Stochastik Score (0-2) - NEU
    stoch_score: float = 0
    stoch_signal: Optional[str] = None
    stoch_k: float = 0
    stoch_d: float = 0
    stoch_reason: str = ""

    # Keltner Channel Score (0-2) - NEU
    keltner_score: float = 0
    keltner_position: str = ""
    keltner_percent: float = 0
    keltner_reason: str = ""

    # VWAP Score (0-3) - NEW from Feature Engineering
    vwap_score: float = 0
    vwap_value: float = 0
    vwap_distance_pct: float = 0
    vwap_position: str = ""
    vwap_reason: str = ""

    # Market Context Score (-1 to +2) - NEW from Feature Engineering
    market_context_score: float = 0
    spy_trend: str = ""
    market_context_reason: str = ""

    # Sector Score (-1 to +1) - NEW from Feature Engineering
    sector_score: float = 0
    sector: str = ""
    sector_reason: str = ""

    # Gap Score (0-1) - from Feature Engineering
    gap_score: float = 0
    gap_reason: str = ""

    total_score: float = 0
    max_possible: float = 10.0  # v2: 5-component scoring, max 10.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "max_possible": self.max_possible,
            "qualified": self.total_score >= 3.5,
            "components": {
                "support": {
                    "score": self.support_score,
                    "level": self.support_level,
                    "distance_pct": round(self.support_distance_pct, 2),
                    "strength": self.support_strength,
                    "touches": self.support_touches,
                    "reason": self.support_reason,
                },
                "rsi": {
                    "score": self.rsi_score,
                    "value": round(self.rsi_value, 2),
                    "reason": self.rsi_reason,
                },
                "rsi_divergence": {
                    "score": self.rsi_divergence_score,
                    "type": self.rsi_divergence_type,
                    "strength": round(self.rsi_divergence_strength, 3),
                    "formation_days": self.rsi_divergence_formation_days,
                    "reason": self.rsi_divergence_reason,
                },
                "candlestick": {
                    "score": self.candlestick_score,
                    "pattern": self.candlestick_pattern,
                    "bullish": self.candlestick_bullish,
                    "reason": self.candlestick_reason,
                },
                "volume": {
                    "score": self.volume_score,
                    "ratio": round(self.volume_ratio, 2),
                    "trend": self.volume_trend,
                    "reason": self.volume_reason,
                },
                "trend": {
                    "score": self.trend_score,
                    "status": self.trend_status,
                    "reason": self.trend_reason,
                },
                "macd": {
                    "score": self.macd_score,
                    "signal": self.macd_signal,
                    "histogram": round(self.macd_histogram, 4),
                    "reason": self.macd_reason,
                },
                "stochastic": {
                    "score": self.stoch_score,
                    "signal": self.stoch_signal,
                    "k": round(self.stoch_k, 2),
                    "d": round(self.stoch_d, 2),
                    "reason": self.stoch_reason,
                },
                "keltner": {
                    "score": self.keltner_score,
                    "position": self.keltner_position,
                    "percent": round(self.keltner_percent, 3),
                    "reason": self.keltner_reason,
                },
                "vwap": {
                    "score": self.vwap_score,
                    "value": round(self.vwap_value, 2),
                    "distance_pct": round(self.vwap_distance_pct, 2),
                    "position": self.vwap_position,
                    "reason": self.vwap_reason,
                },
                "market_context": {
                    "score": self.market_context_score,
                    "spy_trend": self.spy_trend,
                    "reason": self.market_context_reason,
                },
                "sector": {
                    "score": self.sector_score,
                    "name": self.sector,
                    "reason": self.sector_reason,
                },
            },
        }


