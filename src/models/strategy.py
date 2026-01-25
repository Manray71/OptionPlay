# OptionPlay - Strategy Enum
# ===========================
"""
Zentrale Definition aller Trading-Strategien.

Ersetzt Magic Strings wie 'pullback', 'bounce' durch typsichere Enums.
Enthält Metadaten wie Icons, Display-Namen und Eigenschaften.

Verwendung:
    from src.models.strategy import Strategy
    
    if signal.strategy == Strategy.PULLBACK:
        print(f"{Strategy.PULLBACK.icon} {Strategy.PULLBACK.display_name}")
    
    # Für Credit-Spread-geeignete Strategien
    for strat in Strategy.credit_spread_strategies():
        print(strat.name)
"""

from enum import Enum
from typing import List, Dict, Any


class Strategy(Enum):
    """
    Trading-Strategien mit Metadaten.
    
    Attributes:
        PULLBACK: Pullback im Aufwärtstrend - ideal für Bull-Put-Spreads
        BOUNCE: Support Bounce - Long-Entry bei Unterstützung
        ATH_BREAKOUT: All-Time-High Breakout - Momentum-Trade
        EARNINGS_DIP: Earnings Dip Buy - Contrarian nach Earnings-Drop
    """
    PULLBACK = "pullback"
    BOUNCE = "bounce"
    ATH_BREAKOUT = "ath_breakout"
    EARNINGS_DIP = "earnings_dip"
    
    @property
    def icon(self) -> str:
        """Emoji-Icon für die Strategie."""
        icons = {
            Strategy.PULLBACK: "📊",
            Strategy.BOUNCE: "🔄",
            Strategy.ATH_BREAKOUT: "🚀",
            Strategy.EARNINGS_DIP: "📉",
        }
        return icons.get(self, "•")
    
    @property
    def display_name(self) -> str:
        """Benutzerfreundlicher Anzeigename."""
        names = {
            Strategy.PULLBACK: "Bull-Put-Spread",
            Strategy.BOUNCE: "Support Bounce",
            Strategy.ATH_BREAKOUT: "ATH Breakout",
            Strategy.EARNINGS_DIP: "Earnings Dip",
        }
        return names.get(self, self.value)
    
    @property
    def description(self) -> str:
        """Kurze Beschreibung der Strategie."""
        descriptions = {
            Strategy.PULLBACK: "Pullback im Aufwärtstrend - ideal für Bull-Put-Spreads",
            Strategy.BOUNCE: "Bounce von etabliertem Support-Level - Long Entry",
            Strategy.ATH_BREAKOUT: "Ausbruch auf neues All-Time-High mit Volumen-Bestätigung",
            Strategy.EARNINGS_DIP: "Qualitätsaktie nach 5-15% Earnings-Drop - Contrarian Play",
        }
        return descriptions.get(self, "")
    
    @property
    def suitable_for_credit_spreads(self) -> bool:
        """
        Ist die Strategie für Credit Spreads (Bull-Put-Spreads) geeignet?
        
        Credit Spreads benötigen:
        - Ausreichend IV für Prämie
        - Keine nahen Earnings (außer Earnings-Dip)
        - Bullische oder neutrale Bias
        """
        return self in (Strategy.PULLBACK, Strategy.BOUNCE)
    
    @property
    def requires_earnings_filter(self) -> bool:
        """
        Soll die Strategie Earnings-Filter anwenden?
        
        Earnings-Dip braucht gerade kürzliche Earnings,
        andere Strategien meiden Earnings.
        """
        return self != Strategy.EARNINGS_DIP
    
    @property
    def min_historical_days(self) -> int:
        """Minimum historische Tage für die Analyse."""
        days = {
            Strategy.PULLBACK: 90,
            Strategy.BOUNCE: 90,
            Strategy.ATH_BREAKOUT: 260,  # 1 Jahr für ATH
            Strategy.EARNINGS_DIP: 60,
        }
        return days.get(self, 90)
    
    @property
    def default_min_score(self) -> float:
        """Default Mindest-Score für die Strategie."""
        scores = {
            Strategy.PULLBACK: 5.0,
            Strategy.BOUNCE: 5.0,
            Strategy.ATH_BREAKOUT: 6.0,  # Höher wegen Momentum-Risiko
            Strategy.EARNINGS_DIP: 5.0,
        }
        return scores.get(self, 5.0)
    
    @classmethod
    def credit_spread_strategies(cls) -> List["Strategy"]:
        """Gibt Strategien zurück, die für Credit Spreads geeignet sind."""
        return [s for s in cls if s.suitable_for_credit_spreads]
    
    @classmethod
    def from_string(cls, value: str) -> "Strategy":
        """
        Konvertiert String zu Strategy Enum.
        
        Args:
            value: Strategy-Name (case-insensitive)
            
        Returns:
            Strategy Enum
            
        Raises:
            ValueError: Wenn Strategy nicht existiert
        """
        value_lower = value.lower().strip()
        for strategy in cls:
            if strategy.value == value_lower:
                return strategy
        
        valid = ", ".join(s.value for s in cls)
        raise ValueError(f"Unknown strategy: '{value}'. Valid: {valid}")
    
    @classmethod
    def all_values(cls) -> List[str]:
        """Gibt alle Strategy-Values als Liste zurück."""
        return [s.value for s in cls]
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialisiert Strategy zu Dictionary."""
        return {
            "name": self.name,
            "value": self.value,
            "icon": self.icon,
            "display_name": self.display_name,
            "description": self.description,
            "suitable_for_credit_spreads": self.suitable_for_credit_spreads,
            "requires_earnings_filter": self.requires_earnings_filter,
            "min_historical_days": self.min_historical_days,
            "default_min_score": self.default_min_score,
        }


# Convenience-Mapping für Backwards-Compatibility
STRATEGY_ICONS = {s.value: s.icon for s in Strategy}
STRATEGY_NAMES = {s.value: s.display_name for s in Strategy}


def get_strategy_icon(strategy: str) -> str:
    """
    Gibt Icon für Strategy-String zurück.
    
    Für Backwards-Compatibility mit bestehendem Code.
    """
    try:
        return Strategy.from_string(strategy).icon
    except ValueError:
        return "•"


def get_strategy_display_name(strategy: str) -> str:
    """
    Gibt Display-Name für Strategy-String zurück.
    
    Für Backwards-Compatibility mit bestehendem Code.
    """
    try:
        return Strategy.from_string(strategy).display_name
    except ValueError:
        return strategy
