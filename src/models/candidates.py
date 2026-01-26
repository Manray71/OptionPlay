# OptionPlay - Candidate Models
# ==============================
# Dataclasses für Analyse-Kandidaten

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

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
    keltner_position: str = ""  # 'below_lower', 'near_lower', 'in_channel', 'near_upper', 'above_upper'
    keltner_percent: float = 0  # -1 = lower, 0 = middle, +1 = upper
    keltner_reason: str = ""

    total_score: float = 0
    max_possible: int = 16  # Erhöht von 14 auf 16 (Keltner = 0-2)
    
    def to_dict(self) -> Dict:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 5,
            'components': {
                'rsi': {
                    'score': self.rsi_score,
                    'value': round(self.rsi_value, 2),
                    'reason': self.rsi_reason
                },
                'support': {
                    'score': self.support_score,
                    'level': self.support_level,
                    'distance_pct': round(self.support_distance_pct, 2),
                    'strength': self.support_strength,
                    'touches': self.support_touches,
                    'reason': self.support_reason
                },
                'fibonacci': {
                    'score': self.fibonacci_score,
                    'level': self.fib_level,
                    'reason': self.fib_reason
                },
                'moving_averages': {
                    'score': self.ma_score,
                    'vs_sma20': self.price_vs_sma20,
                    'vs_sma200': self.price_vs_sma200,
                    'reason': self.ma_reason
                },
                'trend_strength': {
                    'score': self.trend_strength_score,
                    'alignment': self.trend_alignment,
                    'sma20_slope': round(self.sma20_slope, 4),
                    'reason': self.trend_reason
                },
                'volume': {
                    'score': self.volume_score,
                    'ratio': round(self.volume_ratio, 2),
                    'trend': self.volume_trend,
                    'reason': self.volume_reason
                },
                'macd': {
                    'score': self.macd_score,
                    'signal': self.macd_signal,
                    'histogram': round(self.macd_histogram, 4),
                    'reason': self.macd_reason
                },
                'stochastic': {
                    'score': self.stoch_score,
                    'signal': self.stoch_signal,
                    'k': round(self.stoch_k, 2),
                    'd': round(self.stoch_d, 2),
                    'reason': self.stoch_reason
                },
                'keltner': {
                    'score': self.keltner_score,
                    'position': self.keltner_position,
                    'percent': round(self.keltner_percent, 3),
                    'reason': self.keltner_reason
                }
            }
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
    support_levels: List[float]
    resistance_levels: List[float]
    fib_levels: Dict[str, float]
    
    # Volume
    avg_volume: int
    current_volume: int
    
    # Meta
    timestamp: datetime = field(default_factory=datetime.now)
    data_source: str = "calculated"
    
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
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'price': round(self.current_price, 2),
            'score': self.score,
            'qualified': self.is_qualified(),
            'technicals': self.technicals.to_dict(),
            'support_levels': [round(s, 2) for s in self.support_levels],
            'resistance_levels': [round(r, 2) for r in self.resistance_levels],
            'fib_levels': {k: round(v, 2) for k, v in self.fib_levels.items()},
            'volume': {
                'current': self.current_volume,
                'average': self.avg_volume,
                'ratio': round(self.current_volume / self.avg_volume, 2) if self.avg_volume > 0 else 0
            },
            'score_breakdown': self.score_breakdown.to_dict(),
            'timestamp': self.timestamp.isoformat()
        }
