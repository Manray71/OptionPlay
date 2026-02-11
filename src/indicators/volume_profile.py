# OptionPlay - Volume Profile Indicators
# =======================================
# VWAP, Volume Profile POC, Market Context

import numpy as np
from typing import List, Optional, Dict
from dataclasses import dataclass

try:
    from ..constants.trading_rules import VIX_LOW_VOL_MAX, VIX_NORMAL_MAX, VIX_DANGER_ZONE_MAX
except ImportError:
    from constants.trading_rules import VIX_LOW_VOL_MAX, VIX_NORMAL_MAX, VIX_DANGER_ZONE_MAX


@dataclass
class VWAPResult:
    """VWAP calculation result."""
    vwap: float
    distance_pct: float  # Current price distance from VWAP in %
    position: str  # 'above', 'near', 'below'


@dataclass
class VolumeProfileResult:
    """Volume Profile calculation result."""
    poc: float  # Point of Control (price with highest volume)
    distance_pct: float  # Current price distance from POC in %
    value_area_high: float
    value_area_low: float


@dataclass
class MarketContextResult:
    """Market context (SPY trend) result."""
    spy_trend: str  # 'strong_uptrend', 'uptrend', 'sideways', 'downtrend', 'strong_downtrend'
    spy_sma20: float
    spy_sma50: float
    spy_current: float
    score_adjustment: float  # Score adjustment based on trend


def calculate_vwap(
    prices: List[float],
    volumes: List[int],
    period: int = 20
) -> Optional[VWAPResult]:
    """
    Calculate Volume Weighted Average Price (VWAP).

    VWAP = Sum(Price * Volume) / Sum(Volume)

    This is a key institutional indicator - prices above VWAP show strength,
    prices below show weakness.

    Args:
        prices: Close prices (oldest first)
        volumes: Trading volumes
        period: Lookback period for VWAP calculation

    Returns:
        VWAPResult with VWAP value and distance metrics
    """
    if len(prices) < period or len(volumes) < period:
        return None

    if len(prices) != len(volumes):
        return None

    prices_arr = np.array(prices[-period:], dtype=np.float64)
    volumes_arr = np.array(volumes[-period:], dtype=np.float64)

    total_volume = np.sum(volumes_arr)
    if total_volume == 0:
        return None

    vwap = np.sum(prices_arr * volumes_arr) / total_volume
    current_price = prices[-1]

    # Calculate distance from VWAP
    distance_pct = (current_price - vwap) / vwap * 100 if vwap > 0 else 0

    # Determine position
    if distance_pct > 1.0:
        position = 'above'
    elif distance_pct < -1.0:
        position = 'below'
    else:
        position = 'near'

    return VWAPResult(
        vwap=float(vwap),
        distance_pct=float(distance_pct),
        position=position
    )


def calculate_volume_profile_poc(
    prices: List[float],
    volumes: List[int],
    num_bins: int = 20,
    period: int = 50
) -> Optional[VolumeProfileResult]:
    """
    Calculate Volume Profile with Point of Control (POC).

    POC = Price level where most volume was traded.
    This is where institutional interest is concentrated.

    Args:
        prices: Close prices
        volumes: Trading volumes
        num_bins: Number of price bins for the profile
        period: Lookback period

    Returns:
        VolumeProfileResult with POC and value area
    """
    if len(prices) < period or len(volumes) < period:
        return None

    prices_arr = np.array(prices[-period:], dtype=np.float64)
    volumes_arr = np.array(volumes[-period:], dtype=np.float64)

    price_min, price_max = prices_arr.min(), prices_arr.max()
    if price_max == price_min:
        return None

    # Create price bins
    bins = np.linspace(price_min, price_max, num_bins + 1)
    bin_volumes = np.zeros(num_bins)

    # Assign volumes to bins
    for price, volume in zip(prices_arr, volumes_arr):
        bin_idx = min(
            int((price - price_min) / (price_max - price_min) * num_bins),
            num_bins - 1
        )
        bin_volumes[bin_idx] += volume

    # Find POC (bin with highest volume)
    poc_bin_idx = np.argmax(bin_volumes)
    poc_price = (bins[poc_bin_idx] + bins[poc_bin_idx + 1]) / 2

    # Calculate Value Area (70% of volume)
    total_volume = np.sum(bin_volumes)
    target_volume = total_volume * 0.7

    # Expand from POC until 70% volume is captured
    low_idx = poc_bin_idx
    high_idx = poc_bin_idx
    current_volume = bin_volumes[poc_bin_idx]

    while current_volume < target_volume and (low_idx > 0 or high_idx < num_bins - 1):
        # Check which direction adds more volume
        low_vol = bin_volumes[low_idx - 1] if low_idx > 0 else 0
        high_vol = bin_volumes[high_idx + 1] if high_idx < num_bins - 1 else 0

        if low_vol >= high_vol and low_idx > 0:
            low_idx -= 1
            current_volume += low_vol
        elif high_idx < num_bins - 1:
            high_idx += 1
            current_volume += high_vol
        else:
            break

    value_area_low = (bins[low_idx] + bins[low_idx + 1]) / 2
    value_area_high = (bins[high_idx] + bins[high_idx + 1]) / 2

    # Calculate distance from POC
    current_price = prices[-1]
    distance_pct = (current_price - poc_price) / poc_price * 100 if poc_price > 0 else 0

    return VolumeProfileResult(
        poc=float(poc_price),
        distance_pct=float(distance_pct),
        value_area_high=float(value_area_high),
        value_area_low=float(value_area_low)
    )


def calculate_spy_trend(
    spy_prices: List[float]
) -> Optional[MarketContextResult]:
    """
    Determine SPY (market) trend for context filtering.

    Trading is much more successful when aligned with market trend.

    Args:
        spy_prices: SPY close prices (oldest first)

    Returns:
        MarketContextResult with trend and score adjustment
    """
    if len(spy_prices) < 50:
        return None

    current = spy_prices[-1]
    sma20 = float(np.mean(spy_prices[-20:]))
    sma50 = float(np.mean(spy_prices[-50:]))

    # Determine trend based on price vs SMAs
    if current > sma20 > sma50:
        # Strong uptrend: price > SMA20 > SMA50
        trend = 'strong_uptrend'
        score_adjustment = 1.0
    elif current > sma50 and current > sma20:
        # Uptrend: price above both SMAs
        trend = 'uptrend'
        score_adjustment = 0.5
    elif current > sma50:
        # Neutral/consolidation
        trend = 'sideways'
        score_adjustment = 0.0
    elif current < sma20 < sma50:
        # Strong downtrend: price < SMA20 < SMA50
        trend = 'strong_downtrend'
        score_adjustment = -1.0
    else:
        # Downtrend
        trend = 'downtrend'
        score_adjustment = -0.5

    return MarketContextResult(
        spy_trend=trend,
        spy_sma20=sma20,
        spy_sma50=sma50,
        spy_current=current,
        score_adjustment=score_adjustment
    )


# Sector mapping and adjustments based on training results
SECTOR_MAP: Dict[str, str] = {
    # Technology
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'AVGO': 'Technology',
    'CSCO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology', 'ORCL': 'Technology',
    'ACN': 'Technology', 'IBM': 'Technology', 'INTC': 'Technology', 'AMD': 'Technology',
    'QCOM': 'Technology', 'TXN': 'Technology', 'AMAT': 'Technology', 'ADI': 'Technology',
    'MU': 'Technology', 'LRCX': 'Technology', 'KLAC': 'Technology', 'SNPS': 'Technology',
    'CDNS': 'Technology', 'MCHP': 'Technology', 'HPQ': 'Technology', 'HPE': 'Technology',

    # Communication Services
    'GOOGL': 'Communication', 'GOOG': 'Communication', 'META': 'Communication',
    'NFLX': 'Communication', 'DIS': 'Communication', 'CMCSA': 'Communication',
    'VZ': 'Communication', 'T': 'Communication', 'TMUS': 'Communication',

    # Consumer Discretionary
    'AMZN': 'Consumer_Disc', 'TSLA': 'Consumer_Disc', 'HD': 'Consumer_Disc',
    'NKE': 'Consumer_Disc', 'MCD': 'Consumer_Disc', 'SBUX': 'Consumer_Disc',
    'LOW': 'Consumer_Disc', 'TJX': 'Consumer_Disc', 'BKNG': 'Consumer_Disc',

    # Consumer Staples
    'PG': 'Consumer_Staples', 'KO': 'Consumer_Staples', 'PEP': 'Consumer_Staples',
    'COST': 'Consumer_Staples', 'WMT': 'Consumer_Staples', 'PM': 'Consumer_Staples',
    'MO': 'Consumer_Staples', 'CL': 'Consumer_Staples', 'KMB': 'Consumer_Staples',
    'GIS': 'Consumer_Staples', 'K': 'Consumer_Staples', 'KR': 'Consumer_Staples',

    # Healthcare
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'PFE': 'Healthcare',
    'ABBV': 'Healthcare', 'MRK': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'BMY': 'Healthcare', 'AMGN': 'Healthcare', 'MDT': 'Healthcare',
    'GILD': 'Healthcare', 'CVS': 'Healthcare', 'BSX': 'Healthcare',

    # Financials
    'BRK.B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'BLK': 'Financials', 'C': 'Financials', 'AXP': 'Financials', 'SCHW': 'Financials',
    'CB': 'Financials', 'MMC': 'Financials', 'PGR': 'Financials', 'MET': 'Financials',
    'AIG': 'Financials', 'AFL': 'Financials', 'TRV': 'Financials', 'CME': 'Financials',

    # Industrials
    'GE': 'Industrials', 'CAT': 'Industrials', 'HON': 'Industrials', 'UNP': 'Industrials',
    'BA': 'Industrials', 'RTX': 'Industrials', 'DE': 'Industrials', 'LMT': 'Industrials',
    'UPS': 'Industrials', 'ADP': 'Industrials', 'MMM': 'Industrials', 'GD': 'Industrials',
    'ITW': 'Industrials', 'EMR': 'Industrials', 'ETN': 'Industrials', 'WM': 'Industrials',

    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'EOG': 'Energy',
    'SLB': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'OXY': 'Energy', 'KMI': 'Energy', 'WMB': 'Energy', 'HAL': 'Energy',

    # Materials
    'LIN': 'Materials', 'APD': 'Materials', 'SHW': 'Materials', 'ECL': 'Materials',
    'DD': 'Materials', 'NEM': 'Materials', 'FCX': 'Materials', 'NUE': 'Materials',

    # Real Estate
    'AMT': 'Real_Estate', 'PLD': 'Real_Estate', 'CCI': 'Real_Estate', 'EQIX': 'Real_Estate',
    'PSA': 'Real_Estate', 'O': 'Real_Estate', 'SPG': 'Real_Estate', 'AVB': 'Real_Estate',
    'EQR': 'Real_Estate', 'DLR': 'Real_Estate', 'WELL': 'Real_Estate', 'VTR': 'Real_Estate',
    'MAA': 'Real_Estate', 'CPT': 'Real_Estate', 'KIM': 'Real_Estate', 'INVH': 'Real_Estate',

    # Utilities
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities',
    'AEP': 'Utilities', 'EXC': 'Utilities', 'SRE': 'Utilities', 'XEL': 'Utilities',
    'ED': 'Utilities', 'WEC': 'Utilities', 'ES': 'Utilities', 'AWK': 'Utilities',
    'DTE': 'Utilities', 'AEE': 'Utilities', 'CMS': 'Utilities', 'ETR': 'Utilities',
    'FE': 'Utilities', 'EIX': 'Utilities', 'EVRG': 'Utilities', 'LNT': 'Utilities',
    'ATO': 'Utilities',
}

# Sector score adjustments based on training (vs 80% baseline)
# Diese Werte gelten bei normalem VIX (<15)
SECTOR_ADJUSTMENTS: Dict[str, float] = {
    'Consumer_Staples': 0.9,   # +9% win rate
    'Utilities': 0.68,         # +6.8% win rate
    'Financials': 0.64,        # +6.4% win rate
    'Energy': -0.1,            # -1% win rate
    'Industrials': -0.1,       # -1% win rate
    'Communication': -0.29,    # -2.9% win rate
    'Real_Estate': -0.39,      # -3.9% win rate
    'Healthcare': -0.42,       # -4.2% win rate
    'Consumer_Disc': -0.69,    # -6.9% win rate
    'Materials': -0.75,        # -7.5% win rate
    'Technology': -1.0,        # -10% win rate
}

# VIX-dynamische Sektor-Modifikatoren (Training 2026-01-31)
# Diese Werte werden bei erhöhtem VIX auf SECTOR_ADJUSTMENTS angewendet
VIX_SECTOR_MODIFIERS: Dict[str, Dict[str, float]] = {
    # Financial Services: 6.5% Win Rate Drop wenn VIX über 15
    # Bei VIX 20-25 (Danger Zone) besonders schlecht
    'Financials': {
        'vix_15_plus': -0.65,       # -6.5% WR bei VIX > 15
        'vix_danger_zone': -1.0,    # Zusätzlich -10% bei VIX 20-25
    },
    # Technology leidet auch bei erhöhtem VIX
    'Technology': {
        'vix_15_plus': -0.30,       # Zusätzlich -3% bei VIX > 15
        'vix_danger_zone': -0.50,   # Zusätzlich -5% bei VIX 20-25
    },
    # Communication Services - ähnlich wie Tech
    'Communication': {
        'vix_15_plus': -0.25,
        'vix_danger_zone': -0.40,
    },
    # Defensive Sektoren werden bei hohem VIX BESSER
    'Consumer_Staples': {
        'vix_15_plus': 0.20,        # +2% bei VIX > 15 (Flight to Safety)
        'vix_danger_zone': 0.30,    # +3% bei VIX 20-25
    },
    'Utilities': {
        'vix_15_plus': 0.25,        # +2.5% bei VIX > 15
        'vix_danger_zone': 0.35,    # +3.5% bei VIX 20-25
    },
}


def get_sector(symbol: str) -> str:
    """Get sector for a symbol."""
    return SECTOR_MAP.get(symbol.upper(), 'Unknown')


def get_sector_adjustment(symbol: str, vix: float = None) -> float:
    """
    Get VIX-dynamic score adjustment for a symbol's sector.

    Based on training results (2026-01-31):
    - Consumer Staples, Utilities, Financials: positive adjustment
    - Technology, Materials, Consumer Disc: negative adjustment
    - Financial Services: 6.5% WR Drop bei VIX > 15!
    - Defensive Sektoren werden bei hohem VIX BESSER

    Args:
        symbol: Stock ticker
        vix: Current VIX level (optional, for dynamic adjustment)

    Returns:
        Score adjustment value (can be < -1.0 or > +1.0 with VIX modifiers)
    """
    sector = get_sector(symbol)
    base_adjustment = SECTOR_ADJUSTMENTS.get(sector, 0.0)

    # VIX-dynamische Anpassung
    if vix is not None and sector in VIX_SECTOR_MODIFIERS:
        modifiers = VIX_SECTOR_MODIFIERS[sector]

        if vix >= VIX_LOW_VOL_MAX:
            # Basis-Modifier bei VIX > 15
            vix_mod = modifiers.get('vix_15_plus', 0.0)
            base_adjustment += vix_mod

        if VIX_NORMAL_MAX <= vix < VIX_DANGER_ZONE_MAX:
            # Zusätzlicher Modifier in der Danger Zone (VIX 20-25)
            danger_mod = modifiers.get('vix_danger_zone', 0.0)
            base_adjustment += danger_mod

    return base_adjustment


def get_sector_adjustment_with_reason(symbol: str, vix: float = None) -> tuple:
    """
    Get VIX-dynamic sector adjustment with explanation.

    Returns:
        (adjustment, sector, reason_string)
    """
    sector = get_sector(symbol)
    base_adjustment = SECTOR_ADJUSTMENTS.get(sector, 0.0)
    reasons = []

    if base_adjustment > 0:
        reasons.append(f"{sector}: +{base_adjustment*10:.0f}% base WR")
    elif base_adjustment < 0:
        reasons.append(f"{sector}: {base_adjustment*10:.0f}% base WR")
    else:
        reasons.append(f"{sector}: neutral base")

    total_adjustment = base_adjustment

    # VIX-dynamische Anpassung
    if vix is not None and sector in VIX_SECTOR_MODIFIERS:
        modifiers = VIX_SECTOR_MODIFIERS[sector]

        if vix >= VIX_LOW_VOL_MAX:
            vix_mod = modifiers.get('vix_15_plus', 0.0)
            if vix_mod != 0:
                total_adjustment += vix_mod
                direction = "+" if vix_mod > 0 else ""
                reasons.append(f"VIX>{VIX_LOW_VOL_MAX:.0f}: {direction}{vix_mod*10:.0f}%")

        if VIX_NORMAL_MAX <= vix < VIX_DANGER_ZONE_MAX:
            danger_mod = modifiers.get('vix_danger_zone', 0.0)
            if danger_mod != 0:
                total_adjustment += danger_mod
                direction = "+" if danger_mod > 0 else ""
                reasons.append(f"DANGER ZONE: {direction}{danger_mod*10:.0f}%")

    reason_str = ", ".join(reasons)
    return total_adjustment, sector, reason_str
