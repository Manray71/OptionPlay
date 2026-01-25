# OptionPlay - Support/Resistance Indicators
# ============================================
# Support/Resistance Levels, Fibonacci

from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


def find_support_levels(
    lows: List[float],
    lookback: int = 60,
    window: int = 20,
    max_levels: int = 3
) -> List[float]:
    """
    Findet Support-Levels als Swing Lows.
    
    Ein Swing Low ist ein Tief, das niedriger ist als alle Tiefs
    in einem Fenster von 'window' Tagen auf beiden Seiten.
    
    Args:
        lows: Tagestiefs (älteste zuerst)
        lookback: Wie weit zurückschauen
        window: Fenstergröße für lokale Minima
        max_levels: Maximale Anzahl zurückgegebener Levels
        
    Returns:
        Liste der Support-Levels (sortiert aufsteigend)
    """
    lookback = min(lookback, len(lows))
    min_required = 2 * window + 1
    
    if lookback < min_required:
        logger.debug(f"Not enough data for support detection: {lookback} < {min_required}")
        return []
    
    supports = []
    start_idx = len(lows) - lookback
    
    for i in range(window, lookback - window):
        abs_idx = start_idx + i
        window_start = abs_idx - window
        window_end = abs_idx + window + 1
        
        local_min = min(lows[window_start:window_end])
        
        if lows[abs_idx] == local_min:
            supports.append(lows[abs_idx])
    
    unique_supports = sorted(set(supports))
    return unique_supports[-max_levels:] if unique_supports else []


def find_resistance_levels(
    highs: List[float],
    lookback: int = 60,
    window: int = 20,
    max_levels: int = 3
) -> List[float]:
    """
    Findet Resistance-Levels als Swing Highs.
    
    Ein Swing High ist ein Hoch, das höher ist als alle Hochs
    in einem Fenster von 'window' Tagen auf beiden Seiten.
    
    Args:
        highs: Tageshochs (älteste zuerst)
        lookback: Wie weit zurückschauen
        window: Fenstergröße für lokale Maxima
        max_levels: Maximale Anzahl zurückgegebener Levels
        
    Returns:
        Liste der Resistance-Levels (sortiert absteigend)
    """
    lookback = min(lookback, len(highs))
    min_required = 2 * window + 1
    
    if lookback < min_required:
        logger.debug(f"Not enough data for resistance detection: {lookback} < {min_required}")
        return []
    
    resistances = []
    start_idx = len(highs) - lookback
    
    for i in range(window, lookback - window):
        abs_idx = start_idx + i
        window_start = abs_idx - window
        window_end = abs_idx + window + 1
        
        local_max = max(highs[window_start:window_end])
        
        if highs[abs_idx] == local_max:
            resistances.append(highs[abs_idx])
    
    unique_resistances = sorted(set(resistances))
    return unique_resistances[:max_levels] if unique_resistances else []


def calculate_fibonacci(high: float, low: float) -> Dict[str, float]:
    """
    Berechnet Fibonacci Retracement Levels.
    
    Die Levels zeigen potenzielle Support/Resistance-Zonen
    basierend auf der Fibonacci-Sequenz.
    
    Args:
        high: Höchster Preis im Betrachtungszeitraum
        low: Niedrigster Preis im Betrachtungszeitraum
        
    Returns:
        Dict mit Fibonacci-Levels
    """
    diff = high - low
    return {
        '0.0%': high,
        '23.6%': high - diff * 0.236,
        '38.2%': high - diff * 0.382,
        '50.0%': high - diff * 0.5,
        '61.8%': high - diff * 0.618,
        '78.6%': high - diff * 0.786,
        '100.0%': low
    }


def find_pivot_points(
    high: float,
    low: float,
    close: float
) -> Dict[str, float]:
    """
    Berechnet klassische Pivot Points.
    
    Args:
        high: Tageshoch
        low: Tagestief
        close: Schlusskurs
        
    Returns:
        Dict mit Pivot, Support (S1-S3) und Resistance (R1-R3) Levels
    """
    pivot = (high + low + close) / 3
    
    return {
        'pivot': pivot,
        'r1': 2 * pivot - low,
        'r2': pivot + (high - low),
        'r3': high + 2 * (pivot - low),
        's1': 2 * pivot - high,
        's2': pivot - (high - low),
        's3': low - 2 * (high - pivot)
    }


def price_near_level(
    price: float,
    level: float,
    tolerance_pct: float = 2.0
) -> bool:
    """
    Prüft ob Preis nahe an einem Level ist.
    
    Args:
        price: Aktueller Preis
        level: Support/Resistance Level
        tolerance_pct: Toleranz in Prozent
        
    Returns:
        True wenn Preis innerhalb der Toleranz
    """
    distance_pct = abs(price - level) / price * 100
    return distance_pct <= tolerance_pct
