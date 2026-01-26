# OptionPlay - Volatility Indicators
# ====================================
# ATR, Bollinger Bands

import numpy as np
from typing import List, Optional

try:
    from ..models.indicators import BollingerBands, ATRResult
except ImportError:
    from models.indicators import BollingerBands, ATRResult


def calculate_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> Optional[ATRResult]:
    """
    Berechnet Average True Range (ATR).
    
    ATR misst Volatilität unabhängig von der Preisrichtung.
    
    Args:
        highs: Tageshochs
        lows: Tagestiefs
        closes: Schlusskurse
        period: ATR-Periode
        
    Returns:
        ATRResult oder None
    """
    if len(highs) < period + 1:
        return None
    
    # True Range berechnen
    tr = []
    for i in range(1, len(highs)):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        ))
    
    if len(tr) < period:
        return None
    
    # ATR mit Wilder's Smoothing
    atr = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
    
    current_price = closes[-1]
    atr_percent = (atr / current_price * 100) if current_price > 0 else 0
    
    return ATRResult(
        atr=atr,
        atr_percent=atr_percent
    )


def calculate_bollinger_bands(
    prices: List[float],
    period: int = 20,
    num_std: float = 2.0
) -> Optional[BollingerBands]:
    """
    Berechnet Bollinger Bands.
    
    Args:
        prices: Schlusskurse
        period: Periode für SMA und Standardabweichung
        num_std: Anzahl Standardabweichungen für Bands
        
    Returns:
        BollingerBands oder None
    """
    if len(prices) < period:
        return None
    
    recent_prices = prices[-period:]
    middle = float(np.mean(recent_prices))
    std = float(np.std(recent_prices))
    
    upper = middle + (num_std * std)
    lower = middle - (num_std * std)
    
    bandwidth = (upper - lower) / middle if middle > 0 else 0
    
    current_price = prices[-1]
    if upper == lower:
        percent_b = 0.5
    else:
        percent_b = (current_price - lower) / (upper - lower)
    
    return BollingerBands(
        upper=upper,
        middle=middle,
        lower=lower,
        bandwidth=bandwidth,
        percent_b=percent_b
    )


def is_volatility_squeeze(
    prices: List[float],
    period: int = 20,
    bandwidth_threshold: float = 0.05
) -> bool:
    """
    Erkennt Volatility Squeeze (Bollinger Bands eng zusammen).
    
    Ein Squeeze deutet oft auf eine bevorstehende größere Bewegung hin.
    
    Args:
        prices: Schlusskurse
        period: Bollinger Band Periode
        bandwidth_threshold: Schwelle für Squeeze
        
    Returns:
        True wenn Squeeze erkannt
    """
    bb = calculate_bollinger_bands(prices, period)
    if not bb:
        return False
    
    return bb.bandwidth < bandwidth_threshold
