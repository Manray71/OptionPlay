# OptionPlay - Volatility Indicators
# ====================================
# ATR, Bollinger Bands, Keltner Channel

import numpy as np
from typing import List, Optional

try:
    from ..models.indicators import BollingerBands, ATRResult, KeltnerChannelResult
except ImportError:
    from models.indicators import BollingerBands, ATRResult, KeltnerChannelResult


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


def calculate_atr_simple(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> Optional[float]:
    """
    Berechnet ATR mit einfachem SMA (kein Wilder's Smoothing).

    Diese Variante wird von den Analyzern fuer Keltner Channel verwendet.
    Fuer standalone ATR-Analyse ist calculate_atr() (mit Wilder's) vorzuziehen.

    Args:
        highs: Tageshochs
        lows: Tagestiefs
        closes: Schlusskurse
        period: ATR-Periode

    Returns:
        ATR-Wert als float oder None
    """
    if len(highs) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    return float(np.mean(true_ranges[-period:]))


def calculate_keltner_channel(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    ema_period: int = 20,
    atr_period: int = 10,
    atr_multiplier: float = 2.0
) -> Optional[KeltnerChannelResult]:
    """
    Berechnet Keltner Channel.

    Keltner Channel = EMA +/- (ATR x Multiplier)
    - Middle: EMA(ema_period)
    - Upper: EMA + ATR(atr_period) x multiplier
    - Lower: EMA - ATR(atr_period) x multiplier

    Args:
        prices: Schlusskurse
        highs: Tageshochs
        lows: Tagestiefs
        ema_period: Periode fuer EMA (Middle Line)
        atr_period: Periode fuer ATR
        atr_multiplier: Multiplikator fuer Bandbreite

    Returns:
        KeltnerChannelResult oder None
    """
    from .trend import calculate_ema

    min_required = max(ema_period, atr_period) + 1

    if len(prices) < min_required:
        return None

    # Calculate EMA (middle line)
    ema_values = calculate_ema(prices, ema_period)
    if not ema_values:
        return None
    current_ema = ema_values[-1]

    # Calculate ATR (SMA-based, matching analyzer behavior)
    atr = calculate_atr_simple(highs, lows, prices, atr_period)
    if atr is None or atr <= 0:
        return None

    # Calculate bands
    band_width = atr * atr_multiplier
    upper = current_ema + band_width
    lower = current_ema - band_width

    # Determine current price position
    current_price = prices[-1]
    channel_range = upper - lower

    if channel_range <= 0:
        return None

    # Percent Position: -1 = lower, 0 = middle, +1 = upper
    percent_position = (current_price - current_ema) / band_width if band_width > 0 else 0

    # Position Label
    if current_price > upper:
        price_position = 'above_upper'
    elif current_price < lower:
        price_position = 'below_lower'
    elif percent_position < -0.5:
        price_position = 'near_lower'
    elif percent_position > 0.5:
        price_position = 'near_upper'
    else:
        price_position = 'in_channel'

    # Channel width as % of price (volatility indicator)
    channel_width_pct = (channel_range / current_price) * 100 if current_price > 0 else 0

    return KeltnerChannelResult(
        upper=upper,
        middle=current_ema,
        lower=lower,
        atr=atr,
        price_position=price_position,
        percent_position=percent_position,
        channel_width_pct=channel_width_pct
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
