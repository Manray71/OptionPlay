# OptionPlay - Base Models
# =========================
# Gemeinsame Basis-Dataclasses für alle Analyzer
#
# WICHTIG: Alle Models implementieren __post_init__ Validierung
# für Domain-Constraints und Konsistenzprüfungen.

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Any, Literal


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


class ValidationError(ValueError):
    """Fehler bei der Validierung von Model-Daten"""
    pass


# Gültige Reliability Grades
VALID_RELIABILITY_GRADES = frozenset({"A", "B", "C", "D", "F"})


@dataclass
class TradeSignal:
    """
    Universelles Trade-Signal von allen Analyzern.

    Ermöglicht einheitliches Ranking und Vergleich
    zwischen verschiedenen Strategien.

    Validierung:
        - score: 0.0 - 16.0 (max theoretical score)
        - current_price: > 0
        - entry_price: > 0 wenn gesetzt
        - stop_loss/target_price: Konsistenz mit signal_type
        - reliability_grade: A, B, C, D, F
        - reliability_win_rate: 0-100
    """
    # Identifikation
    symbol: str
    strategy: str  # Name der Strategie (z.B. "pullback", "breakout")

    # Signal
    signal_type: SignalType
    strength: SignalStrength
    score: float  # 0-16 für Ranking (max theoretical)

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

    # Reliability (Phase 3 - Hochverlässlichkeits-Framework)
    reliability_grade: Optional[str] = None  # "A", "B", "C", "D", "F"
    reliability_win_rate: Optional[float] = None  # Historische Win Rate (0-100)
    reliability_ci: Optional[tuple] = None  # Confidence Interval (low, high)
    reliability_warnings: List[str] = field(default_factory=list)

    def __post_init__(self):
        """
        Validiert alle Felder nach Initialisierung.

        Raises:
            ValidationError: Bei ungültigen Werten oder inkonsistenten Daten
        """
        errors = []

        # Symbol Validierung
        if not self.symbol or not isinstance(self.symbol, str):
            errors.append("symbol must be a non-empty string")
        elif len(self.symbol) > 10:
            errors.append(f"symbol too long: {self.symbol}")

        # Strategy Validierung
        if not self.strategy or not isinstance(self.strategy, str):
            errors.append("strategy must be a non-empty string")

        # Score Validierung (0-16 max theoretical)
        if not isinstance(self.score, (int, float)):
            errors.append(f"score must be numeric, got {type(self.score)}")
        elif self.score < 0 or self.score > 20:
            errors.append(f"score must be 0-20, got {self.score}")

        # Price Validierung
        if self.current_price is not None:
            if not isinstance(self.current_price, (int, float)):
                errors.append(f"current_price must be numeric, got {type(self.current_price)}")
            elif self.current_price <= 0:
                errors.append(f"current_price must be positive, got {self.current_price}")

        if self.entry_price is not None:
            if not isinstance(self.entry_price, (int, float)):
                errors.append(f"entry_price must be numeric, got {type(self.entry_price)}")
            elif self.entry_price <= 0:
                errors.append(f"entry_price must be positive, got {self.entry_price}")

        if self.stop_loss is not None:
            if not isinstance(self.stop_loss, (int, float)):
                errors.append(f"stop_loss must be numeric, got {type(self.stop_loss)}")
            elif self.stop_loss <= 0:
                errors.append(f"stop_loss must be positive, got {self.stop_loss}")

        if self.target_price is not None:
            if not isinstance(self.target_price, (int, float)):
                errors.append(f"target_price must be numeric, got {type(self.target_price)}")
            elif self.target_price <= 0:
                errors.append(f"target_price must be positive, got {self.target_price}")

        # Entry/Stop/Target Konsistenz prüfen
        if all([self.entry_price, self.stop_loss, self.target_price]):
            self._validate_price_levels(errors)

        # Reliability Grade Validierung
        if self.reliability_grade is not None:
            if self.reliability_grade not in VALID_RELIABILITY_GRADES:
                errors.append(
                    f"reliability_grade must be one of {VALID_RELIABILITY_GRADES}, "
                    f"got '{self.reliability_grade}'"
                )

        # Reliability Win Rate Validierung
        if self.reliability_win_rate is not None:
            if not isinstance(self.reliability_win_rate, (int, float)):
                errors.append(f"reliability_win_rate must be numeric")
            elif self.reliability_win_rate < 0 or self.reliability_win_rate > 100:
                errors.append(
                    f"reliability_win_rate must be 0-100, got {self.reliability_win_rate}"
                )

        # Reliability CI Validierung
        if self.reliability_ci is not None:
            if not isinstance(self.reliability_ci, (tuple, list)) or len(self.reliability_ci) != 2:
                errors.append("reliability_ci must be a tuple of (low, high)")
            else:
                low, high = self.reliability_ci
                if not all(isinstance(x, (int, float)) for x in [low, high]):
                    errors.append("reliability_ci values must be numeric")
                elif low > high:
                    errors.append(f"reliability_ci low ({low}) must be <= high ({high})")

        # Timestamp Validierung
        if self.expires_at is not None and self.expires_at <= self.timestamp:
            # Warnung statt Fehler - kann in Edge Cases vorkommen
            if "expires_at <= timestamp" not in self.warnings:
                self.warnings.append("expires_at is before or equal to timestamp")

        # Raise ValidationError wenn Fehler gefunden
        if errors:
            raise ValidationError(
                f"TradeSignal validation failed for {self.symbol}: " +
                "; ".join(errors)
            )

    def _validate_price_levels(self, errors: List[str]) -> None:
        """
        Validiert Konsistenz von Entry, Stop Loss und Target basierend auf Signal-Type.

        Für LONG: stop_loss < entry_price < target_price
        Für SHORT: target_price < entry_price < stop_loss
        """
        entry = self.entry_price
        stop = self.stop_loss
        target = self.target_price

        if self.signal_type == SignalType.LONG:
            # Long: Stop unter Entry, Target über Entry
            if stop >= entry:
                errors.append(
                    f"LONG signal: stop_loss ({stop}) must be < entry_price ({entry})"
                )
            if target <= entry:
                errors.append(
                    f"LONG signal: target_price ({target}) must be > entry_price ({entry})"
                )

        elif self.signal_type == SignalType.SHORT:
            # Short: Stop über Entry, Target unter Entry
            if stop <= entry:
                errors.append(
                    f"SHORT signal: stop_loss ({stop}) must be > entry_price ({entry})"
                )
            if target >= entry:
                errors.append(
                    f"SHORT signal: target_price ({target}) must be < entry_price ({entry})"
                )

        # Entry darf nie gleich Stop sein (infinite risk)
        if entry == stop:
            errors.append(
                f"entry_price ({entry}) cannot equal stop_loss (would create infinite risk)"
            )
    
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
    
    @property
    def reliability_badge(self) -> str:
        """Kurzes Reliability-Badge für CLI-Output"""
        if not self.reliability_grade:
            return ""
        wr = self.reliability_win_rate or 0
        return f"[{self.reliability_grade}] {wr:.0f}%"

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary für JSON-Output"""
        result = {
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

        # Reliability-Daten hinzufügen wenn vorhanden
        if self.reliability_grade:
            result['reliability'] = {
                'grade': self.reliability_grade,
                'win_rate': self.reliability_win_rate,
                'confidence_interval': self.reliability_ci,
                'warnings': self.reliability_warnings,
            }

        return result
