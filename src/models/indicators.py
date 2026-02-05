# OptionPlay - Indicator Models
# ==============================
# Dataclasses für technische Indikatoren

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class MACDResult:
    """MACD Indicator Result"""
    macd_line: float
    signal_line: float
    histogram: float
    crossover: Optional[str] = None  # 'bullish', 'bearish', or None
    
    def to_dict(self) -> dict[str, Any]:
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
    
    def to_dict(self) -> dict[str, Any]:
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

    # Gap Analysis (optional, für mittelfristige Strategien)
    gap: Optional['GapResult'] = None

    def to_dict(self) -> dict[str, Any]:
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
            'trend': self.trend,
            'gap': self.gap.to_dict() if self.gap else None,
        }


@dataclass
class BollingerBands:
    """Bollinger Bands Result"""
    upper: float
    middle: float  # SMA
    lower: float
    bandwidth: float  # (upper - lower) / middle
    percent_b: float  # (price - lower) / (upper - lower)
    
    def to_dict(self) -> dict[str, Any]:
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

    def to_dict(self) -> dict[str, Any]:
        return {
            'atr': round(self.atr, 2),
            'atr_percent': round(self.atr_percent, 2)
        }


@dataclass
class RSIDivergenceResult:
    """
    RSI Divergenz Ergebnis

    RSI-Divergenzen sind starke Signale der technischen Analyse:
    - Bullische Divergenz: Kurs macht tieferes Tief, RSI macht höheres Tief
      → Verkaufsdruck lässt nach, Bodenbildung wahrscheinlich
    - Bärische Divergenz: Kurs macht höheres Hoch, RSI macht tieferes Hoch
      → Kaufdruck lässt nach, Top-Bildung wahrscheinlich
    """
    divergence_type: str  # 'bullish', 'bearish', or 'none'

    # Pivot-Punkte für Kurs
    price_pivot_1: float  # Erster Pivot (älter)
    price_pivot_2: float  # Zweiter Pivot (aktueller)

    # Pivot-Punkte für RSI
    rsi_pivot_1: float  # RSI beim ersten Pivot
    rsi_pivot_2: float  # RSI beim zweiten Pivot

    # Stärke der Divergenz (0-1)
    strength: float

    # Anzahl Tage zwischen den Pivots
    formation_days: int

    # Zusätzliche Infos
    pivot_1_idx: int = 0  # Index des ersten Pivots
    pivot_2_idx: int = 0  # Index des zweiten Pivots

    def to_dict(self) -> dict[str, Any]:
        return {
            'type': self.divergence_type,
            'price_pivot_1': round(self.price_pivot_1, 2),
            'price_pivot_2': round(self.price_pivot_2, 2),
            'rsi_pivot_1': round(self.rsi_pivot_1, 2),
            'rsi_pivot_2': round(self.rsi_pivot_2, 2),
            'strength': round(self.strength, 3),
            'formation_days': self.formation_days
        }


@dataclass
class GapResult:
    """
    Gap Analysis Result - Erkennt und bewertet Price Gaps.

    Gap-Typen:
    - Up-Gap: Open > Previous High (bullish gap, aber oft Überkauft-Signal)
    - Down-Gap: Open < Previous Low (bearish gap, aber oft Einstiegschance)
    - Partial Up-Gap: Open > Previous Close, but <= Previous High
    - Partial Down-Gap: Open < Previous Close, but >= Previous Low

    These für Bull-Put-Spreads:
    - Down-Gaps können gute Einstiegspunkte sein (Überreaktion)
    - Up-Gaps signalisieren oft Euphorie (Vorsicht)
    """
    gap_type: str  # 'up', 'down', 'partial_up', 'partial_down', 'none'
    gap_size_pct: float  # Gap-Größe in % vom Previous Close
    gap_size_abs: float  # Gap-Größe in Dollar

    # Gap-Fill Status
    is_filled: bool  # Wurde der Gap intraday gefüllt?
    fill_percentage: float  # Wie viel % des Gaps wurden gefüllt (0-100+)

    # Historische Gap-Statistiken
    gaps_last_20_days: int  # Anzahl Gaps in den letzten 20 Tagen
    avg_gap_size_20d: float  # Durchschnittliche Gap-Größe
    gap_fill_rate_20d: float  # Wie oft werden Gaps gefüllt (0-1)

    # Aktueller Gap-Kontext
    previous_close: float
    current_open: float
    current_high: float
    current_low: float

    # Qualitäts-Score für Strategie
    quality_score: float  # -1 (bearish/schlecht) bis +1 (bullish/gut für Entry)

    def to_dict(self) -> dict[str, Any]:
        return {
            'gap_type': self.gap_type,
            'gap_size_pct': round(self.gap_size_pct, 3),
            'gap_size_abs': round(self.gap_size_abs, 2),
            'is_filled': self.is_filled,
            'fill_percentage': round(self.fill_percentage, 1),
            'gaps_last_20_days': self.gaps_last_20_days,
            'avg_gap_size_20d': round(self.avg_gap_size_20d, 3),
            'gap_fill_rate_20d': round(self.gap_fill_rate_20d, 3),
            'previous_close': round(self.previous_close, 2),
            'current_open': round(self.current_open, 2),
            'quality_score': round(self.quality_score, 3),
        }


@dataclass
class GapStatistics:
    """
    Aggregierte Gap-Statistiken für ein Symbol.

    Wird für die Validierung der Gap-These verwendet:
    - Korrelation zwischen Gap-Typ und nachfolgender Performance
    """
    symbol: str
    analysis_period_days: int

    # Gap-Counts
    total_gaps: int
    up_gaps: int
    down_gaps: int
    partial_up_gaps: int
    partial_down_gaps: int

    # Fill-Statistiken
    up_gap_fill_rate: float  # Wie oft werden Up-Gaps gefüllt
    down_gap_fill_rate: float  # Wie oft werden Down-Gaps gefüllt
    avg_fill_time_days: float  # Durchschnittliche Zeit bis Gap gefüllt

    # Performance nach Gap (für Validierung)
    avg_return_after_up_gap_5d: float  # 5-Tages-Return nach Up-Gap
    avg_return_after_down_gap_5d: float  # 5-Tages-Return nach Down-Gap
    win_rate_after_up_gap: float  # % positive Returns nach Up-Gap
    win_rate_after_down_gap: float  # % positive Returns nach Down-Gap

    def to_dict(self) -> dict[str, Any]:
        return {
            'symbol': self.symbol,
            'period_days': self.analysis_period_days,
            'total_gaps': self.total_gaps,
            'up_gaps': self.up_gaps,
            'down_gaps': self.down_gaps,
            'up_gap_fill_rate': round(self.up_gap_fill_rate, 3),
            'down_gap_fill_rate': round(self.down_gap_fill_rate, 3),
            'avg_return_after_up_gap_5d': round(self.avg_return_after_up_gap_5d, 4),
            'avg_return_after_down_gap_5d': round(self.avg_return_after_down_gap_5d, 4),
            'win_rate_after_up_gap': round(self.win_rate_after_up_gap, 3),
            'win_rate_after_down_gap': round(self.win_rate_after_down_gap, 3),
        }


@dataclass
class KeltnerChannelResult:
    """
    Keltner Channel Result

    Keltner Channels sind volatilitätsbasierte Bänder:
    - Middle: EMA (typischerweise 20)
    - Upper: EMA + (ATR * Multiplier)
    - Lower: EMA - (ATR * Multiplier)

    Für Pullback-Analyse:
    - Preis berührt unteres Band = potenzielle Kaufgelegenheit
    - Preis innerhalb Channel bei Uptrend = gesunder Pullback
    """
    upper: float
    middle: float  # EMA
    lower: float
    atr: float

    # Position des aktuellen Preises
    price_position: str  # 'above_upper', 'in_channel', 'below_lower'
    percent_position: float  # -1 = lower band, 0 = middle, +1 = upper band

    # Band-Breite (Volatilitätsindikator)
    channel_width_pct: float  # Channel-Breite als % des Preises

    def to_dict(self) -> dict[str, Any]:
        return {
            'upper': round(self.upper, 2),
            'middle': round(self.middle, 2),
            'lower': round(self.lower, 2),
            'atr': round(self.atr, 2),
            'price_position': self.price_position,
            'percent_position': round(self.percent_position, 3),
            'channel_width_pct': round(self.channel_width_pct, 2)
        }
