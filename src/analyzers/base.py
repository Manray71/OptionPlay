# OptionPlay - Base Analyzer
# ===========================
# Abstract interface for all strategy analyzers

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength


class BaseAnalyzer(ABC):
    """
    Base interface for all strategy analyzers.

    Each analyzer implements a specific trading strategy
    and returns a unified TradeSignal.

    Usage:
        class MyAnalyzer(BaseAnalyzer):
            @property
            def strategy_name(self) -> str:
                return "my_strategy"

            def analyze(self, symbol, prices, volumes, highs, lows, **kwargs):
                # Analysis logic
                return TradeSignal(...)
    """
    
    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """
        Unique name of the strategy.

        Examples: "pullback", "breakout", "bounce", "earnings_dip"
        """
        pass
    
    @property
    def description(self) -> str:
        """Optional description of the strategy"""
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
        Analyzes a symbol and returns a TradeSignal.

        Args:
            symbol: Ticker symbol
            prices: Closing prices (oldest first)
            volumes: Daily volume
            highs: Daily highs
            lows: Daily lows
            **kwargs: Strategy-specific parameters

        Returns:
            TradeSignal with score, entry/exit levels, and reasoning
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
        Validates input arrays.

        Raises:
            ValueError: For invalid inputs
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
        
        # Prices must be positive
        if any(p <= 0 for p in prices if p is not None):
            raise ValueError("All prices must be positive")
        
        # Check High >= Low
        for i, (h, l) in enumerate(zip(highs, lows)):
            if h < l:
                raise ValueError(
                    f"High must be >= Low. Violation at index {i}: "
                    f"high={h}, low={l}"
                )
    
    def create_neutral_signal(self, symbol: str, price: float, reason: str = "") -> TradeSignal:
        """Creates a neutral signal (no trade)"""
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
        """Returns the current configuration"""
        return getattr(self, 'config', {})
