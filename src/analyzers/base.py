# OptionPlay - Base Analyzer
# ===========================
# Abstraktes Interface für alle Strategie-Analyzer

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength


class BaseAnalyzer(ABC):
    """
    Basis-Interface für alle Strategie-Analyzer.
    
    Jeder Analyzer implementiert eine spezifische Trading-Strategie
    und liefert ein einheitliches TradeSignal zurück.
    
    Verwendung:
        class MyAnalyzer(BaseAnalyzer):
            @property
            def strategy_name(self) -> str:
                return "my_strategy"
            
            def analyze(self, symbol, prices, volumes, highs, lows, **kwargs):
                # Analyse-Logik
                return TradeSignal(...)
    """
    
    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """
        Eindeutiger Name der Strategie.
        
        Beispiele: "pullback", "breakout", "bounce", "earnings_dip"
        """
        pass
    
    @property
    def description(self) -> str:
        """Optionale Beschreibung der Strategie"""
        return ""
    
    @abstractmethod
    def analyze(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        **kwargs
    ) -> TradeSignal:
        """
        Analysiert ein Symbol und gibt ein TradeSignal zurück.
        
        Args:
            symbol: Ticker-Symbol
            prices: Schlusskurse (älteste zuerst)
            volumes: Tagesvolumen
            highs: Tageshochs
            lows: Tagestiefs
            **kwargs: Strategie-spezifische Parameter
            
        Returns:
            TradeSignal mit Score, Entry/Exit-Levels und Begründung
        """
        pass
    
    def validate_inputs(
        self,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        min_length: int = 50
    ) -> None:
        """
        Validiert Input-Arrays.
        
        Raises:
            ValueError: Bei ungültigen Inputs
        """
        arrays = {'prices': prices, 'volumes': volumes, 'highs': highs, 'lows': lows}
        lengths = {name: len(arr) for name, arr in arrays.items()}
        unique_lengths = set(lengths.values())
        
        if len(unique_lengths) != 1:
            raise ValueError(
                f"All input arrays must have same length. Got: "
                f"{', '.join(f'{k}={v}' for k, v in lengths.items())}"
            )
        
        if len(prices) == 0:
            raise ValueError("Input arrays cannot be empty")
        
        if len(prices) < min_length:
            raise ValueError(
                f"Need at least {min_length} data points, got {len(prices)}"
            )
        
        # Preise müssen positiv sein
        if any(p <= 0 for p in prices if p is not None):
            raise ValueError("All prices must be positive")
        
        # High >= Low prüfen
        for i, (h, l) in enumerate(zip(highs, lows)):
            if h < l:
                raise ValueError(
                    f"High must be >= Low. Violation at index {i}: "
                    f"high={h}, low={l}"
                )
    
    def create_neutral_signal(self, symbol: str, price: float, reason: str = "") -> TradeSignal:
        """Erstellt ein neutrales Signal (kein Trade)"""
        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.NEUTRAL,
            strength=SignalStrength.NONE,
            score=0.0,
            current_price=price,
            reason=reason or "No actionable signal"
        )
    
    def get_config(self) -> Dict[str, Any]:
        """Gibt die aktuelle Konfiguration zurück"""
        return getattr(self, 'config', {})
