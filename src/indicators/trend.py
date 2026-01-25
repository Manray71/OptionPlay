# OptionPlay - Trend Indicators
# ===============================
# SMA, EMA, ADX

import numpy as np
from typing import List, Optional


def calculate_sma(prices: List[float], period: int) -> float:
    """
    Berechnet Simple Moving Average.
    
    Args:
        prices: Schlusskurse
        period: Periode
        
    Returns:
        SMA-Wert
    """
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return float(np.mean(prices[-period:]))


def calculate_ema(prices: List[float], period: int) -> List[float]:
    """
    Berechnet Exponential Moving Average.
    
    Args:
        prices: Schlusskurse
        period: Periode
        
    Returns:
        Liste der EMA-Werte
    """
    if len(prices) < period:
        return prices
    
    multiplier = 2 / (period + 1)
    ema_values = [np.mean(prices[:period])]
    
    for price in prices[period:]:
        ema = (price * multiplier) + (ema_values[-1] * (1 - multiplier))
        ema_values.append(ema)
    
    return ema_values


def calculate_adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> Optional[float]:
    """
    Berechnet Average Directional Index (ADX).
    
    Misst die Stärke eines Trends (nicht die Richtung).
    - ADX > 25: Starker Trend
    - ADX < 20: Schwacher/kein Trend
    
    Args:
        highs: Tageshochs
        lows: Tagestiefs
        closes: Schlusskurse
        period: ADX-Periode
        
    Returns:
        ADX-Wert oder None
    """
    if len(highs) < period + 1:
        return None
    
    # True Range
    tr = []
    for i in range(1, len(highs)):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        ))
    
    # +DM und -DM
    plus_dm = []
    minus_dm = []
    for i in range(1, len(highs)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0)
        
        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0)
    
    if len(tr) < period:
        return None
    
    # Smoothed TR, +DM, -DM
    atr = np.mean(tr[:period])
    plus_dm_smooth = np.mean(plus_dm[:period])
    minus_dm_smooth = np.mean(minus_dm[:period])
    
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
        plus_dm_smooth = (plus_dm_smooth * (period - 1) + plus_dm[i]) / period
        minus_dm_smooth = (minus_dm_smooth * (period - 1) + minus_dm[i]) / period
    
    if atr == 0:
        return None
    
    # +DI und -DI
    plus_di = 100 * plus_dm_smooth / atr
    minus_di = 100 * minus_dm_smooth / atr
    
    # DX
    if plus_di + minus_di == 0:
        return None
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    
    # ADX ist geglätteter DX (vereinfacht: nur aktueller Wert)
    return dx


def get_trend_direction(
    price: float,
    sma_short: float,
    sma_long: float
) -> str:
    """
    Bestimmt Trend-Richtung basierend auf MAs.
    
    Args:
        price: Aktueller Preis
        sma_short: Kurzfristiger MA (z.B. 20)
        sma_long: Langfristiger MA (z.B. 200)
        
    Returns:
        'uptrend', 'downtrend', oder 'sideways'
    """
    above_short = price > sma_short
    above_long = price > sma_long
    
    if above_long and above_short:
        return 'uptrend'
    elif not above_long and not above_short:
        return 'downtrend'
    else:
        return 'sideways'
