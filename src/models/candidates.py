# OptionPlay - Candidate Models
# ==============================
# Dataclasses für Analyse-Kandidaten

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .indicators import TechnicalIndicators


@dataclass
class SupportLevel:
    """Support-Level mit Metadaten"""

    price: float
    touches: int = 1
    strength: str = "moderate"  # weak, moderate, strong
    confirmed_by_fib: bool = False
    distance_pct: float = 0.0  # Abstand zum aktuellen Preis in %


@dataclass
class ScoreBreakdown:
    """Detaillierte Aufschlüsselung des Pullback-Scores"""

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

    support_score: float = 0
    support_level: Optional[float] = None
    support_distance_pct: float = 0
    support_strength: str = ""  # NEW: weak, moderate, strong
    support_touches: int = 0  # NEW: Anzahl der Berührungen
    support_reason: str = ""

    fibonacci_score: float = 0
    fib_level: Optional[str] = None
    fib_reason: str = ""

    ma_score: float = 0
    price_vs_sma20: str = ""
    price_vs_sma200: str = ""
    ma_reason: str = ""

    # NEW: Trend-Stärke Score
    trend_strength_score: float = 0
    trend_alignment: str = ""  # "strong", "moderate", "weak", "none"
    sma20_slope: float = 0  # Steigung des SMA20
    trend_reason: str = ""

    volume_score: float = 0
    volume_ratio: float = 0
    volume_trend: str = ""  # NEW: "decreasing" (gut), "increasing", "stable"
    volume_reason: str = ""

    # MACD Score (NEW - jetzt mit Scoring)
    macd_score: float = 0
    macd_signal: Optional[str] = None  # 'bullish_cross', 'bullish', 'bearish', 'neutral'
    macd_histogram: float = 0
    macd_reason: str = ""

    # Stochastik Score (NEW - jetzt mit Scoring)
    stoch_score: float = 0
    stoch_signal: Optional[str] = None  # 'oversold_bullish_cross', 'oversold', etc.
    stoch_k: float = 0
    stoch_d: float = 0
    stoch_reason: str = ""

    # Keltner Channel Score (NEW)
    keltner_score: float = 0
    keltner_position: str = (
        ""  # 'below_lower', 'near_lower', 'in_channel', 'near_upper', 'above_upper'
    )
    keltner_percent: float = 0  # -1 = lower, 0 = middle, +1 = upper
    keltner_reason: str = ""

    # VWAP Score (NEW from Feature Engineering)
    # Based on training: entries above VWAP have 91.9% win rate vs 51.7% below
    vwap_score: float = 0
    vwap_value: float = 0
    vwap_distance_pct: float = 0  # Positive = above VWAP
    vwap_position: str = ""  # 'above', 'near', 'below'
    vwap_reason: str = ""

    # Market Context Score (SPY Trend Filter)
    # Strong uptrend: 76.1% WR, Strong downtrend: 59.3% WR
    market_context_score: float = 0
    spy_trend: str = ""  # 'strong_uptrend', 'uptrend', 'sideways', 'downtrend', 'strong_downtrend'
    market_context_reason: str = ""

    # Sector Score (NEW from Feature Engineering)
    # Consumer Staples: +9%, Utilities: +6.8%, Technology: -10%
    sector_score: float = 0
    sector: str = ""
    sector_reason: str = ""

    # Candlestick Reversal Score (NEW - literature alignment)
    # Hammer, Bullish Engulfing, Doji at support/fibonacci levels
    candlestick_score: float = 0
    candlestick_pattern: str = ""  # 'hammer', 'bullish_engulfing', 'doji', 'none'
    candlestick_reason: str = ""

    # Gap Score (NEW - validated with 174k+ events)
    # Down-gaps: +0.43% better 30d returns, +1.9pp win rate
    # Large down-gaps (>3%): +1.21% outperformance
    gap_score: float = 0
    gap_type: str = ""  # 'up', 'down', 'partial_up', 'partial_down', 'none'
    gap_size_pct: float = 0
    gap_filled: bool = False
    gap_reason: str = ""

    total_score: float = 0
    max_possible: int = 26  # Erhöht: +1 Gap Score (0-1 für down-gaps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "max_possible": self.max_possible,
            "qualified": self.total_score >= 5,
            "components": {
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
                "support": {
                    "score": self.support_score,
                    "level": self.support_level,
                    "distance_pct": round(self.support_distance_pct, 2),
                    "strength": self.support_strength,
                    "touches": self.support_touches,
                    "reason": self.support_reason,
                },
                "fibonacci": {
                    "score": self.fibonacci_score,
                    "level": self.fib_level,
                    "reason": self.fib_reason,
                },
                "moving_averages": {
                    "score": self.ma_score,
                    "vs_sma20": self.price_vs_sma20,
                    "vs_sma200": self.price_vs_sma200,
                    "reason": self.ma_reason,
                },
                "trend_strength": {
                    "score": self.trend_strength_score,
                    "alignment": self.trend_alignment,
                    "sma20_slope": round(self.sma20_slope, 4),
                    "reason": self.trend_reason,
                },
                "volume": {
                    "score": self.volume_score,
                    "ratio": round(self.volume_ratio, 2),
                    "trend": self.volume_trend,
                    "reason": self.volume_reason,
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
                "candlestick": {
                    "score": self.candlestick_score,
                    "pattern": self.candlestick_pattern,
                    "reason": self.candlestick_reason,
                },
                "gap": {
                    "score": self.gap_score,
                    "type": self.gap_type,
                    "size_pct": round(self.gap_size_pct, 2),
                    "filled": self.gap_filled,
                    "reason": self.gap_reason,
                },
            },
        }


@dataclass
class PullbackCandidate:
    """Vollständige Pullback-Analyse eines Symbols"""

    symbol: str
    current_price: float
    score: float
    score_breakdown: ScoreBreakdown

    # Technische Indikatoren
    technicals: TechnicalIndicators

    # Support/Resistance
    support_levels: list[float]
    resistance_levels: list[float]
    fib_levels: dict[str, float]

    # Volume
    avg_volume: int
    current_volume: int

    # Meta
    timestamp: datetime = field(default_factory=datetime.now)
    data_source: str = "calculated"
    warnings: list[str] = field(default_factory=list)  # E.5: runtime warnings

    # Für Rückwärtskompatibilität
    @property
    def rsi_14(self) -> float:
        return self.technicals.rsi_14

    @property
    def sma_20(self) -> float:
        return self.technicals.sma_20

    @property
    def sma_200(self) -> float:
        return self.technicals.sma_200

    def is_qualified(self, min_score: int = 5) -> bool:
        return self.score >= min_score

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": round(self.current_price, 2),
            "score": self.score,
            "qualified": self.is_qualified(),
            "technicals": self.technicals.to_dict(),
            "support_levels": [round(s, 2) for s in self.support_levels],
            "resistance_levels": [round(r, 2) for r in self.resistance_levels],
            "fib_levels": {k: round(v, 2) for k, v in self.fib_levels.items()},
            "volume": {
                "current": self.current_volume,
                "average": self.avg_volume,
                "ratio": (
                    round(self.current_volume / self.avg_volume, 2) if self.avg_volume > 0 else 0
                ),
            },
            "score_breakdown": self.score_breakdown.to_dict(),
            "timestamp": self.timestamp.isoformat(),
        }
