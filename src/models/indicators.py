# OptionPlay - Indicator Models
# ==============================
# Dataclasses für technische Indikatoren

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class MACDResult:
    """MACD Indicator Result"""
    macd_line: float
    signal_line: float
    histogram: float
    crossover: Optional[str] = None  # 'bullish', 'bearish', or None
    
    def to_dict(self) -> Dict:
        return {
            'macd': round(self.macd_line, 4),
            'signal': round(self.signal_line, 4),
            'histogram': round(self.histogram, 4),
            'crossover': self.crossover
        }


@dataclass
class StochasticResult:
    """Stochastic Oscillator Result"""
    k: float  # %K (fast)
    d: float  # %D (slow)
    crossover: Optional[str] = None  # 'bullish', 'bearish', or None
    zone: Optional[str] = None  # 'oversold', 'overbought', 'neutral'
    
    def to_dict(self) -> Dict:
        return {
            'k': round(self.k, 2),
            'd': round(self.d, 2),
            'crossover': self.crossover,
            'zone': self.zone
        }


@dataclass
class TechnicalIndicators:
    """Alle technischen Indikatoren für ein Symbol"""
    rsi_14: float
    sma_20: float
    sma_50: Optional[float]
    sma_200: float
    macd: Optional[MACDResult]
    stochastic: Optional[StochasticResult]
    
    # Trend-Status
    above_sma20: bool
    above_sma50: Optional[bool]
    above_sma200: bool
    trend: str  # 'uptrend', 'downtrend', 'sideways'
    
    def to_dict(self) -> Dict:
        return {
            'rsi_14': round(self.rsi_14, 2),
            'sma_20': round(self.sma_20, 2),
            'sma_50': round(self.sma_50, 2) if self.sma_50 else None,
            'sma_200': round(self.sma_200, 2),
            'macd': self.macd.to_dict() if self.macd else None,
            'stochastic': self.stochastic.to_dict() if self.stochastic else None,
            'above_sma20': self.above_sma20,
            'above_sma50': self.above_sma50,
            'above_sma200': self.above_sma200,
            'trend': self.trend
        }


@dataclass
class BollingerBands:
    """Bollinger Bands Result"""
    upper: float
    middle: float  # SMA
    lower: float
    bandwidth: float  # (upper - lower) / middle
    percent_b: float  # (price - lower) / (upper - lower)
    
    def to_dict(self) -> Dict:
        return {
            'upper': round(self.upper, 2),
            'middle': round(self.middle, 2),
            'lower': round(self.lower, 2),
            'bandwidth': round(self.bandwidth, 4),
            'percent_b': round(self.percent_b, 4)
        }


@dataclass
class ATRResult:
    """Average True Range Result"""
    atr: float
    atr_percent: float  # ATR als % des Preises
    
    def to_dict(self) -> Dict:
        return {
            'atr': round(self.atr, 2),
            'atr_percent': round(self.atr_percent, 2)
        }
