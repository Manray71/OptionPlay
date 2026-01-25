# OptionPlay - Base Models
# =========================
# Gemeinsame Basis-Dataclasses für alle Analyzer

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Any


class SignalType(Enum):
    """Art des Trading-Signals"""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class SignalStrength(Enum):
    """Stärke des Signals"""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


@dataclass
class TradeSignal:
    """
    Universelles Trade-Signal von allen Analyzern.
    
    Ermöglicht einheitliches Ranking und Vergleich
    zwischen verschiedenen Strategien.
    """
    # Identifikation
    symbol: str
    strategy: str  # Name der Strategie (z.B. "pullback", "breakout")
    
    # Signal
    signal_type: SignalType
    strength: SignalStrength
    score: float  # 0-10 für Ranking
    
    # Preis-Informationen
    current_price: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    
    # Kontext
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    
    # Meta
    timestamp: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    
    @property
    def risk_reward_ratio(self) -> Optional[float]:
        """Berechnet Risk/Reward wenn Entry, Stop und Target gesetzt"""
        if not all([self.entry_price, self.stop_loss, self.target_price]):
            return None
        
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target_price - self.entry_price)
        
        if risk == 0:
            return None
        
        return round(reward / risk, 2)
    
    @property
    def is_actionable(self) -> bool:
        """Signal ist handelbar wenn Score >= 5 und LONG/SHORT"""
        return (
            self.score >= 5 and 
            self.signal_type in [SignalType.LONG, SignalType.SHORT]
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary für JSON-Output"""
        return {
            'symbol': self.symbol,
            'strategy': self.strategy,
            'signal_type': self.signal_type.value,
            'strength': self.strength.value,
            'score': self.score,
            'current_price': self.current_price,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'target_price': self.target_price,
            'risk_reward': self.risk_reward_ratio,
            'is_actionable': self.is_actionable,
            'reason': self.reason,
            'details': self.details,
            'warnings': self.warnings,
            'timestamp': self.timestamp.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }
