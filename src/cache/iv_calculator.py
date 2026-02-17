# OptionPlay - IV Calculator
# ==========================
"""
Pure math functions for IV calculations.

Extracted from iv_cache_impl.py (Phase D.3).

Functions:
- calculate_iv_rank: IV-Rank = (Current - Low) / (High - Low) * 100
- calculate_iv_percentile: Percentile of days with lower IV
- calculate_historical_volatility: HV from price series
- estimate_iv_from_hv: IV estimation from HV with VIX adjustment
"""

import logging
import math
from typing import List, Optional

try:
    from ..constants.trading_rules import VIX_DANGER_ZONE_MAX, VIX_NO_TRADING_THRESHOLD
except ImportError:
    from constants.trading_rules import VIX_DANGER_ZONE_MAX, VIX_NO_TRADING_THRESHOLD

logger = logging.getLogger(__name__)


def calculate_iv_rank(current_iv: float, iv_history: List[float]) -> Optional[float]:
    """
    Berechnet IV-Rank.

    IV-Rank = (Current IV - 52w Low) / (52w High - 52w Low) * 100

    Args:
        current_iv: Aktuelle IV (dezimal)
        iv_history: Liste historischer IV-Werte (dezimal)

    Returns:
        IV-Rank (0-100) oder None
    """
    if not iv_history or len(iv_history) < 20:
        return None
    if current_iv is None or current_iv <= 0:
        return None

    iv_high = max(iv_history)
    iv_low = min(iv_history)

    if iv_high == iv_low:
        return 50.0

    iv_rank = (current_iv - iv_low) / (iv_high - iv_low) * 100
    return max(0.0, min(100.0, iv_rank))


def calculate_iv_percentile(current_iv: float, iv_history: List[float]) -> Optional[float]:
    """
    Berechnet IV-Perzentil.

    Zeigt an welchem Prozentsatz der historischen Tage die IV niedriger war.

    Args:
        current_iv: Aktuelle IV (dezimal)
        iv_history: Liste historischer IV-Werte (dezimal)

    Returns:
        IV-Perzentil (0-100) oder None
    """
    if not iv_history or len(iv_history) < 20:
        return None
    if current_iv is None or current_iv <= 0:
        return None

    days_below = sum(1 for iv in iv_history if iv < current_iv)
    percentile = days_below / len(iv_history) * 100
    return round(percentile, 1)


def calculate_historical_volatility(
    prices: List[float],
    window: int = 20,
) -> List[float]:
    """
    Berechnet historische Volatilität (HV) aus Preisen.

    HV = StdDev(log returns) * sqrt(252)

    Args:
        prices: Liste von Schlusskursen (älteste zuerst)
        window: Rolling Window für Berechnung (default: 20 Tage)

    Returns:
        Liste von HV-Werten (annualisiert, dezimal)
    """
    if len(prices) < window + 1:
        return []

    log_returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            log_returns.append(math.log(prices[i] / prices[i - 1]))
        else:
            log_returns.append(0)

    hv_values = []
    for i in range(window - 1, len(log_returns)):
        window_returns = log_returns[i - window + 1 : i + 1]

        mean = sum(window_returns) / len(window_returns)
        variance = sum((r - mean) ** 2 for r in window_returns) / len(window_returns)
        std_dev = math.sqrt(variance)

        annualized_vol = std_dev * math.sqrt(252)
        hv_values.append(annualized_vol)

    return hv_values


def estimate_iv_from_hv(
    hv_values: List[float],
    vix_history: Optional[List[float]] = None,
    iv_premium: float = 1.15,
) -> List[float]:
    """
    Schätzt IV aus historischer Volatilität.

    IV ist typischerweise 10-20% höher als HV (Volatility Risk Premium).

    Args:
        hv_values: Liste von HV-Werten (dezimal)
        vix_history: Optional VIX-History für Markt-Adjustment
        iv_premium: Multiplikator für IV (default: 1.15 = 15% Premium)

    Returns:
        Liste von geschätzten IV-Werten (dezimal)
    """
    if not hv_values:
        return []

    estimated_iv = []
    for i, hv in enumerate(hv_values):
        iv = hv * iv_premium

        if vix_history and i < len(vix_history):
            vix = vix_history[i]
            if vix > VIX_NO_TRADING_THRESHOLD:
                iv *= 1.2
            elif vix > VIX_DANGER_ZONE_MAX:
                iv *= 1.1

        estimated_iv.append(round(iv, 4))

    return estimated_iv
