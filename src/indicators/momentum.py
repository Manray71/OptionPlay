# OptionPlay - Momentum Indicators
# ==================================
# RSI, MACD, Stochastic

import numpy as np
from typing import List, Optional, Tuple

try:
    from ..models.indicators import MACDResult, StochasticResult
except ImportError:
    from models.indicators import MACDResult, StochasticResult


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """
    Berechnet RSI (Relative Strength Index) mit Wilder's Smoothing.
    
    Args:
        prices: Schlusskurse (älteste zuerst)
        period: RSI-Periode (default: 14)
        
    Returns:
        RSI-Wert zwischen 0 und 100
    """
    if len(prices) < period + 1:
        return 50.0
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(
    prices: List[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Optional[MACDResult]:
    """
    Berechnet MACD (Moving Average Convergence Divergence).
    
    Args:
        prices: Schlusskurse
        fast_period: Schnelle EMA-Periode
        slow_period: Langsame EMA-Periode
        signal_period: Signal-Linie Periode
        
    Returns:
        MACDResult oder None bei unzureichenden Daten
    """
    min_required = slow_period + signal_period
    if len(prices) < min_required:
        return None
    
    def ema(data: List[float], period: int) -> List[float]:
        multiplier = 2 / (period + 1)
        ema_values = [np.mean(data[:period])]
        for price in data[period:]:
            ema_values.append((price * multiplier) + (ema_values[-1] * (1 - multiplier)))
        return ema_values
    
    ema_fast = ema(prices, fast_period)
    ema_slow = ema(prices, slow_period)
    
    offset = slow_period - fast_period
    macd_line = []
    for i in range(len(ema_slow)):
        fast_idx = i + offset
        if fast_idx < len(ema_fast):
            macd_line.append(ema_fast[fast_idx] - ema_slow[i])
    
    if len(macd_line) < signal_period:
        return None
    
    signal_line = ema(macd_line, signal_period)
    
    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    histogram = current_macd - current_signal
    
    crossover = None
    if len(signal_line) >= 2:
        prev_diff = macd_line[-2] - signal_line[-2]
        curr_diff = current_macd - current_signal
        
        if prev_diff < 0 and curr_diff > 0:
            crossover = 'bullish'
        elif prev_diff > 0 and curr_diff < 0:
            crossover = 'bearish'
    
    return MACDResult(
        macd_line=current_macd,
        signal_line=current_signal,
        histogram=histogram,
        crossover=crossover
    )


def calculate_stochastic(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    k_period: int = 14,
    d_period: int = 3,
    smooth: int = 3,
    oversold: float = 20,
    overbought: float = 80
) -> Optional[StochasticResult]:
    """
    Berechnet Stochastik-Oszillator.
    
    Args:
        highs: Tageshochs
        lows: Tagestiefs
        closes: Schlusskurse
        k_period: %K Periode
        d_period: %D Periode
        smooth: Glättung für %K
        oversold: Oversold-Schwelle
        overbought: Overbought-Schwelle
        
    Returns:
        StochasticResult oder None
    """
    if len(highs) != len(lows) or len(lows) != len(closes):
        return None
    
    min_required = k_period + d_period + smooth
    if len(closes) < min_required:
        return None
    
    raw_k = []
    for i in range(k_period - 1, len(closes)):
        period_high = max(highs[i - k_period + 1:i + 1])
        period_low = min(lows[i - k_period + 1:i + 1])
        
        if period_high == period_low:
            raw_k.append(50.0)
        else:
            k = 100 * (closes[i] - period_low) / (period_high - period_low)
            raw_k.append(k)
    
    smooth_k = []
    for i in range(smooth - 1, len(raw_k)):
        smooth_k.append(np.mean(raw_k[i - smooth + 1:i + 1]))
    
    d_values = []
    for i in range(d_period - 1, len(smooth_k)):
        d_values.append(np.mean(smooth_k[i - d_period + 1:i + 1]))
    
    if not smooth_k or not d_values:
        return None
    
    current_k = smooth_k[-1]
    current_d = d_values[-1]
    
    crossover = None
    if len(smooth_k) >= 2 and len(d_values) >= 2:
        prev_diff = smooth_k[-2] - d_values[-2]
        curr_diff = smooth_k[-1] - d_values[-1]
        
        if prev_diff < 0 and curr_diff > 0:
            crossover = 'bullish'
        elif prev_diff > 0 and curr_diff < 0:
            crossover = 'bearish'
    
    if current_k < oversold:
        zone = 'oversold'
    elif current_k > overbought:
        zone = 'overbought'
    else:
        zone = 'neutral'
    
    return StochasticResult(
        k=current_k,
        d=current_d,
        crossover=crossover,
        zone=zone
    )
