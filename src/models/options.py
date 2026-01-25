# OptionPlay - Options Models
# ============================
# Dataclasses für Options-spezifische Daten

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class StrikeQuality(Enum):
    """Bewertung der Strike-Empfehlung"""
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"


@dataclass
class MaxPainResult:
    """Ergebnis der Max Pain Berechnung"""
    symbol: str
    expiry: str
    current_price: float
    
    # Max Pain
    max_pain: float
    distance_pct: float  # Abstand zum aktuellen Preis in %
    
    # Walls (höchstes Open Interest)
    put_wall: Optional[float]
    put_wall_oi: int
    call_wall: Optional[float]
    call_wall_oi: int
    
    # Totals
    total_put_oi: int
    total_call_oi: int
    pcr: float  # Put/Call Ratio
    
    def price_vs_max_pain(self) -> str:
        """Zeigt ob Preis über oder unter Max Pain liegt"""
        if self.current_price > self.max_pain:
            return "above"
        elif self.current_price < self.max_pain:
            return "below"
        return "at"
    
    def sentiment(self) -> str:
        """
        Interpretation des PCR.
        
        Returns:
            'bearish' wenn PCR > 1.2 (mehr Puts)
            'bullish' wenn PCR < 0.8 (mehr Calls)
            'neutral' sonst
            'extreme_bearish' wenn PCR ist unendlich (keine Calls)
        """
        if math.isinf(self.pcr):
            return "extreme_bearish"
        elif self.pcr > 1.2:
            return "bearish"
        elif self.pcr < 0.8:
            return "bullish"
        return "neutral"
    
    def gravity_direction(self) -> str:
        """
        Zeigt erwartete Preisbewegung Richtung Max Pain.
        
        Max Pain Theorie: Preis tendiert zum Verfall hin zu Max Pain.
        """
        if self.distance_pct > 3:
            return "down" if self.current_price > self.max_pain else "up"
        return "neutral"
    
    def to_dict(self) -> Dict:
        # PCR kann unendlich sein wenn keine Calls vorhanden
        if math.isinf(self.pcr):
            pcr_value = "inf"
        else:
            pcr_value = round(self.pcr, 2)
        
        return {
            'symbol': self.symbol,
            'expiry': self.expiry,
            'current_price': round(self.current_price, 2),
            'max_pain': round(self.max_pain, 2),
            'distance_pct': round(self.distance_pct, 2),
            'price_vs_max_pain': self.price_vs_max_pain(),
            'gravity_direction': self.gravity_direction(),
            'put_wall': round(self.put_wall, 2) if self.put_wall else None,
            'put_wall_oi': self.put_wall_oi,
            'call_wall': round(self.call_wall, 2) if self.call_wall else None,
            'call_wall_oi': self.call_wall_oi,
            'total_put_oi': self.total_put_oi,
            'total_call_oi': self.total_call_oi,
            'pcr': pcr_value,
            'sentiment': self.sentiment()
        }


@dataclass
class StrikePainData:
    """Pain-Daten für einen einzelnen Strike"""
    strike: float
    call_oi: int
    put_oi: int
    total_pain: float  # Gesamtverlust der Options-Käufer bei diesem Settlement


@dataclass
class StrikeRecommendation:
    """Empfohlene Strike-Kombination für Bull-Put-Spread"""
    symbol: str
    current_price: float
    
    # Strike-Preise
    short_strike: float
    long_strike: float
    spread_width: float
    
    # Basis für die Empfehlung
    short_strike_reason: str
    support_level_used: Optional[Any] = None  # SupportLevel
    
    # Options-Metriken (falls verfügbar)
    estimated_delta: Optional[float] = None
    estimated_credit: Optional[float] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None
    break_even: Optional[float] = None
    
    # Probabilitäten
    prob_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    
    # Bewertung
    quality: StrikeQuality = StrikeQuality.GOOD
    confidence_score: float = 0.0
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary für JSON-Output"""
        support_dict = None
        if self.support_level_used:
            support_dict = {
                'price': self.support_level_used.price,
                'strength': self.support_level_used.strength,
                'touches': self.support_level_used.touches,
                'confirmed_by_fib': self.support_level_used.confirmed_by_fib
            }
        
        return {
            'symbol': self.symbol,
            'current_price': self.current_price,
            'short_strike': self.short_strike,
            'long_strike': self.long_strike,
            'spread_width': self.spread_width,
            'short_strike_reason': self.short_strike_reason,
            'estimated_delta': self.estimated_delta,
            'estimated_credit': self.estimated_credit,
            'max_loss': self.max_loss,
            'max_profit': self.max_profit,
            'break_even': self.break_even,
            'prob_profit': self.prob_profit,
            'risk_reward_ratio': self.risk_reward_ratio,
            'quality': self.quality.value,
            'confidence_score': self.confidence_score,
            'warnings': self.warnings,
            'support_level': support_dict
        }
