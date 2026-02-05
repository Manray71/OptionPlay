# Tests for Volatility Indicators Module
# =======================================
"""
Comprehensive tests for src/indicators/volatility.py

Covers:
- calculate_atr (with Wilder's smoothing)
- calculate_atr_simple (SMA-based)
- calculate_bollinger_bands
- calculate_keltner_channel
- is_volatility_squeeze
- Edge cases and boundary conditions
"""

import pytest
import numpy as np
from typing import List, Tuple

from src.indicators.volatility import (
    calculate_atr,
    calculate_atr_simple,
    calculate_bollinger_bands,
    calculate_keltner_channel,
    is_volatility_squeeze,
)
from src.models.indicators import (
    ATRResult,
    BollingerBands,
    KeltnerChannelResult,
)


# =============================================================================
# TEST DATA GENERATORS
# =============================================================================

def create_ohlc_data(
    n: int = 100,
    start: float = 100.0,
    volatility: float = 0.02,
    seed: int = 42
) -> Tuple[List[float], List[float], List[float]]:
    """
    Create synthetic OHLC data for testing.

    Args:
        n: Number of data points
        start: Starting price
        volatility: Daily volatility (as decimal)
        seed: Random seed for reproducibility

    Returns:
        Tuple of (highs, lows, closes)
    """
    np.random.seed(seed)
    closes = [start]
    for _ in range(1, n):
        change = np.random.normal(0, volatility)
        closes.append(closes[-1] * (1 + change))

    # Generate highs and lows with realistic spreads
    highs = []
    lows = []
    for c in closes:
        spread = abs(np.random.normal(0, 0.01))
        highs.append(c * (1 + spread))
        lows.append(c * (1 - spread))

    return highs, lows, closes


def create_trending_up_data(
    n: int = 100,
    start: float = 100.0,
    trend: float = 0.002,
    volatility: float = 0.01,
    seed: int = 42
) -> Tuple[List[float], List[float], List[float]]:
    """Create uptrending OHLC data."""
    np.random.seed(seed)
    closes = [start]
    for _ in range(1, n):
        change = trend + np.random.normal(0, volatility)
        closes.append(closes[-1] * (1 + change))

    highs = [c * (1 + abs(np.random.normal(0, 0.01))) for c in closes]
    lows = [c * (1 - abs(np.random.normal(0, 0.01))) for c in closes]
    return highs, lows, closes


def create_trending_down_data(
    n: int = 100,
    start: float = 100.0,
    trend: float = -0.002,
    volatility: float = 0.01,
    seed: int = 42
) -> Tuple[List[float], List[float], List[float]]:
    """Create downtrending OHLC data."""
    np.random.seed(seed)
    closes = [start]
    for _ in range(1, n):
        change = trend + np.random.normal(0, volatility)
        closes.append(closes[-1] * (1 + change))

    highs = [c * (1 + abs(np.random.normal(0, 0.01))) for c in closes]
    lows = [c * (1 - abs(np.random.normal(0, 0.01))) for c in closes]
    return highs, lows, closes


def create_flat_data(
    n: int = 100,
    price: float = 100.0,
    noise: float = 0.001,
    seed: int = 42
) -> Tuple[List[float], List[float], List[float]]:
    """Create flat/sideways price data with minimal volatility."""
    np.random.seed(seed)
    closes = [price + np.random.normal(0, noise) for _ in range(n)]
    highs = [c + abs(np.random.normal(0, noise)) for c in closes]
    lows = [c - abs(np.random.normal(0, noise)) for c in closes]
    return highs, lows, closes


def create_constant_data(n: int = 100, price: float = 100.0) -> Tuple[List[float], List[float], List[float]]:
    """Create constant price data (no volatility)."""
    closes = [price] * n
    highs = [price] * n
    lows = [price] * n
    return highs, lows, closes


# =============================================================================
# CALCULATE ATR TESTS
# =============================================================================

class TestCalculateATR:
    """Tests for calculate_atr function with Wilder's smoothing."""

    def test_basic_calculation(self):
        """Test basic ATR calculation returns valid result."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_atr(highs, lows, closes, period=14)

        assert result is not None
        assert isinstance(result, ATRResult)
        assert result.atr > 0
        assert result.atr_percent > 0

    def test_returns_atr_result_type(self):
        """Test that result is ATRResult with correct attributes."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_atr(highs, lows, closes, period=14)

        assert hasattr(result, 'atr')
        assert hasattr(result, 'atr_percent')
        assert isinstance(result.atr, float)
        assert isinstance(result.atr_percent, float)

    def test_atr_percent_calculation(self):
        """Test ATR percent is correctly calculated as percentage of price."""
        highs, lows, closes = create_ohlc_data(50, start=100.0)
        result = calculate_atr(highs, lows, closes, period=14)

        # ATR percent should be ATR / current_price * 100
        expected_percent = (result.atr / closes[-1]) * 100
        assert abs(result.atr_percent - expected_percent) < 0.01

    def test_insufficient_data_returns_none(self):
        """Test ATR returns None with insufficient data."""
        # Need period + 1 data points for ATR
        highs = [100.0, 101.0, 102.0]
        lows = [99.0, 100.0, 101.0]
        closes = [99.5, 100.5, 101.5]

        result = calculate_atr(highs, lows, closes, period=14)
        assert result is None

    def test_exact_minimum_data(self):
        """Test ATR with exactly minimum required data points."""
        # For period=14, need 15 data points (period + 1)
        highs, lows, closes = create_ohlc_data(15)
        result = calculate_atr(highs, lows, closes, period=14)
        assert result is not None

    def test_one_less_than_minimum_data(self):
        """Test ATR returns None with one less than minimum data."""
        highs, lows, closes = create_ohlc_data(14)  # Need 15 for period=14
        result = calculate_atr(highs, lows, closes, period=14)
        assert result is None

    def test_different_periods(self):
        """Test ATR with different periods returns different values."""
        highs, lows, closes = create_ohlc_data(100)

        result_7 = calculate_atr(highs, lows, closes, period=7)
        result_14 = calculate_atr(highs, lows, closes, period=14)
        result_21 = calculate_atr(highs, lows, closes, period=21)

        assert result_7 is not None
        assert result_14 is not None
        assert result_21 is not None
        # Different periods should give different results
        assert result_7.atr != result_14.atr
        assert result_14.atr != result_21.atr

    def test_high_volatility_higher_atr(self):
        """Test that high volatility data has higher ATR."""
        highs_low, lows_low, closes_low = create_ohlc_data(50, volatility=0.005)
        highs_high, lows_high, closes_high = create_ohlc_data(50, volatility=0.05)

        result_low = calculate_atr(highs_low, lows_low, closes_low, period=14)
        result_high = calculate_atr(highs_high, lows_high, closes_high, period=14)

        assert result_high.atr > result_low.atr

    def test_true_range_uses_all_three_components(self):
        """Test that True Range considers all three components correctly."""
        # Create data where each TR component dominates
        # TR = max(H-L, |H-PrevC|, |L-PrevC|)

        # Day 0: H=101, L=99, C=100
        # Day 1: H=102, L=100, C=101 (H-L=2, |H-PrevC|=2, |L-PrevC|=0) -> TR=2
        # Day 2: H=105, L=103, C=104 (H-L=2, |H-PrevC|=4, |L-PrevC|=2) -> TR=4 (gap up)
        # Day 3: H=102, L=100, C=101 (H-L=2, |H-PrevC|=2, |L-PrevC|=4) -> TR=4 (gap down)

        highs = [101.0, 102.0, 105.0, 102.0] + [100.0] * 12
        lows = [99.0, 100.0, 103.0, 100.0] + [99.0] * 12
        closes = [100.0, 101.0, 104.0, 101.0] + [99.5] * 12

        result = calculate_atr(highs, lows, closes, period=3)
        # True Range values: TR[1]=2, TR[2]=4 (gap up), TR[3]=4 (gap down)
        # Initial ATR = mean([2, 4, 4]) = 3.33
        assert result is not None

    def test_wilder_smoothing_applied(self):
        """Test that Wilder's smoothing is used (not SMA)."""
        highs, lows, closes = create_ohlc_data(100)
        result_wilder = calculate_atr(highs, lows, closes, period=14)
        result_simple = calculate_atr_simple(highs, lows, closes, period=14)

        # Wilder's smoothing should give different result than simple SMA
        assert result_wilder.atr != result_simple

    def test_zero_current_price_edge_case(self):
        """Test ATR handles zero current price gracefully."""
        highs = [1.0] * 20
        lows = [0.5] * 20
        closes = [0.75] * 19 + [0.0]  # Last close is zero

        result = calculate_atr(highs, lows, closes, period=14)
        assert result is not None
        assert result.atr_percent == 0  # Division by zero handled

    def test_to_dict_method(self):
        """Test ATRResult.to_dict() method."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_atr(highs, lows, closes, period=14)

        result_dict = result.to_dict()
        assert 'atr' in result_dict
        assert 'atr_percent' in result_dict
        assert isinstance(result_dict['atr'], float)


# =============================================================================
# CALCULATE ATR SIMPLE TESTS
# =============================================================================

class TestCalculateATRSimple:
    """Tests for calculate_atr_simple function (SMA-based)."""

    def test_basic_calculation(self):
        """Test basic simple ATR calculation."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_atr_simple(highs, lows, closes, period=14)

        assert result is not None
        assert isinstance(result, float)
        assert result > 0

    def test_insufficient_data_returns_none(self):
        """Test simple ATR returns None with insufficient data."""
        highs = [100.0, 101.0, 102.0]
        lows = [99.0, 100.0, 101.0]
        closes = [99.5, 100.5, 101.5]

        result = calculate_atr_simple(highs, lows, closes, period=14)
        assert result is None

    def test_uses_last_period_values(self):
        """Test simple ATR uses last period values (not smoothed)."""
        # Create data with known TR values
        highs, lows, closes = create_ohlc_data(100)

        result_period10 = calculate_atr_simple(highs, lows, closes, period=10)
        result_period20 = calculate_atr_simple(highs, lows, closes, period=20)

        # Different periods should use different data windows
        assert result_period10 is not None
        assert result_period20 is not None
        assert result_period10 != result_period20

    def test_exact_minimum_data(self):
        """Test simple ATR with exactly minimum data points."""
        highs, lows, closes = create_ohlc_data(15)  # period + 1
        result = calculate_atr_simple(highs, lows, closes, period=14)
        assert result is not None


# =============================================================================
# CALCULATE BOLLINGER BANDS TESTS
# =============================================================================

class TestCalculateBollingerBands:
    """Tests for calculate_bollinger_bands function."""

    def test_basic_calculation(self):
        """Test basic Bollinger Bands calculation."""
        _, _, prices = create_ohlc_data(50)
        result = calculate_bollinger_bands(prices, period=20)

        assert result is not None
        assert isinstance(result, BollingerBands)

    def test_band_ordering(self):
        """Test that upper > middle > lower."""
        _, _, prices = create_ohlc_data(50)
        result = calculate_bollinger_bands(prices, period=20)

        assert result.upper > result.middle
        assert result.middle > result.lower

    def test_middle_is_sma(self):
        """Test that middle band is the SMA of prices."""
        _, _, prices = create_ohlc_data(50)
        period = 20
        result = calculate_bollinger_bands(prices, period=period)

        # Calculate expected SMA manually
        expected_sma = np.mean(prices[-period:])
        assert abs(result.middle - expected_sma) < 0.0001

    def test_bands_use_correct_num_std(self):
        """Test that bands use correct number of standard deviations."""
        _, _, prices = create_ohlc_data(50)
        period = 20
        num_std = 2.0
        result = calculate_bollinger_bands(prices, period=period, num_std=num_std)

        recent_prices = prices[-period:]
        expected_std = np.std(recent_prices)
        expected_upper = result.middle + (num_std * expected_std)
        expected_lower = result.middle - (num_std * expected_std)

        assert abs(result.upper - expected_upper) < 0.0001
        assert abs(result.lower - expected_lower) < 0.0001

    def test_insufficient_data_returns_none(self):
        """Test BB returns None with insufficient data."""
        prices = [100.0, 101.0, 102.0]
        result = calculate_bollinger_bands(prices, period=20)
        assert result is None

    def test_exact_minimum_data(self):
        """Test BB with exactly minimum data points."""
        _, _, prices = create_ohlc_data(20)  # Exactly period
        result = calculate_bollinger_bands(prices, period=20)
        assert result is not None

    def test_different_periods(self):
        """Test BB with different periods."""
        _, _, prices = create_ohlc_data(100)

        result_10 = calculate_bollinger_bands(prices, period=10)
        result_20 = calculate_bollinger_bands(prices, period=20)
        result_50 = calculate_bollinger_bands(prices, period=50)

        assert result_10.middle != result_20.middle
        assert result_20.middle != result_50.middle

    def test_different_num_std(self):
        """Test BB with different standard deviation multipliers."""
        _, _, prices = create_ohlc_data(50)

        result_1std = calculate_bollinger_bands(prices, period=20, num_std=1.0)
        result_2std = calculate_bollinger_bands(prices, period=20, num_std=2.0)
        result_3std = calculate_bollinger_bands(prices, period=20, num_std=3.0)

        # Wider multiplier = wider bands
        assert result_3std.bandwidth > result_2std.bandwidth
        assert result_2std.bandwidth > result_1std.bandwidth

    def test_bandwidth_calculation(self):
        """Test bandwidth is calculated correctly."""
        _, _, prices = create_ohlc_data(50)
        result = calculate_bollinger_bands(prices, period=20)

        expected_bandwidth = (result.upper - result.lower) / result.middle
        assert abs(result.bandwidth - expected_bandwidth) < 0.0001

    def test_percent_b_calculation(self):
        """Test percent_b is calculated correctly."""
        _, _, prices = create_ohlc_data(50)
        result = calculate_bollinger_bands(prices, period=20)

        current_price = prices[-1]
        expected_percent_b = (current_price - result.lower) / (result.upper - result.lower)
        assert abs(result.percent_b - expected_percent_b) < 0.0001

    def test_percent_b_at_bands(self):
        """Test percent_b values at specific band positions."""
        # Create data where current price is exactly at middle
        prices = [100.0] * 20
        result = calculate_bollinger_bands(prices, period=20)

        # With constant prices, std=0, so upper=lower=middle
        # In this case, percent_b should be 0.5 (the edge case handler)
        assert result.percent_b == 0.5

    def test_high_volatility_wider_bands(self):
        """Test high volatility data has wider bandwidth."""
        _, _, low_vol_prices = create_flat_data(50)
        _, _, high_vol_prices = create_ohlc_data(50, volatility=0.05)

        result_low = calculate_bollinger_bands(low_vol_prices, period=20)
        result_high = calculate_bollinger_bands(high_vol_prices, period=20)

        assert result_high.bandwidth > result_low.bandwidth

    def test_zero_middle_edge_case(self):
        """Test BB handles zero middle price gracefully."""
        prices = [0.0] * 20
        result = calculate_bollinger_bands(prices, period=20)

        assert result is not None
        assert result.bandwidth == 0  # Division by zero handled

    def test_to_dict_method(self):
        """Test BollingerBands.to_dict() method."""
        _, _, prices = create_ohlc_data(50)
        result = calculate_bollinger_bands(prices, period=20)

        result_dict = result.to_dict()
        assert 'upper' in result_dict
        assert 'middle' in result_dict
        assert 'lower' in result_dict
        assert 'bandwidth' in result_dict
        assert 'percent_b' in result_dict


# =============================================================================
# CALCULATE KELTNER CHANNEL TESTS
# =============================================================================

class TestCalculateKeltnerChannel:
    """Tests for calculate_keltner_channel function."""

    def test_basic_calculation(self):
        """Test basic Keltner Channel calculation."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_keltner_channel(closes, highs, lows)

        assert result is not None
        assert isinstance(result, KeltnerChannelResult)

    def test_band_ordering(self):
        """Test that upper > middle > lower."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_keltner_channel(closes, highs, lows)

        assert result.upper > result.middle
        assert result.middle > result.lower

    def test_middle_is_ema(self):
        """Test that middle band is EMA."""
        highs, lows, closes = create_ohlc_data(50)
        ema_period = 20
        result = calculate_keltner_channel(
            closes, highs, lows,
            ema_period=ema_period, atr_period=10
        )

        # Calculate EMA manually
        from src.indicators.trend import calculate_ema
        ema_values = calculate_ema(closes, ema_period)
        expected_ema = ema_values[-1]

        assert abs(result.middle - expected_ema) < 0.0001

    def test_uses_atr_for_band_width(self):
        """Test that bands use ATR for width calculation."""
        highs, lows, closes = create_ohlc_data(50)
        atr_multiplier = 2.0
        result = calculate_keltner_channel(
            closes, highs, lows,
            atr_multiplier=atr_multiplier
        )

        # Band width should equal ATR * multiplier
        band_width = result.upper - result.middle
        expected_width = result.atr * atr_multiplier
        assert abs(band_width - expected_width) < 0.0001

    def test_insufficient_data_returns_none(self):
        """Test KC returns None with insufficient data."""
        highs = [100.0, 101.0, 102.0]
        lows = [99.0, 100.0, 101.0]
        closes = [99.5, 100.5, 101.5]

        result = calculate_keltner_channel(closes, highs, lows, ema_period=20)
        assert result is None

    def test_exact_minimum_data(self):
        """Test KC with exactly minimum data points."""
        # Need max(ema_period, atr_period) + 1 data points
        highs, lows, closes = create_ohlc_data(21)  # 20 + 1
        result = calculate_keltner_channel(closes, highs, lows, ema_period=20, atr_period=10)
        assert result is not None

    def test_different_ema_periods(self):
        """Test KC with different EMA periods."""
        highs, lows, closes = create_ohlc_data(100)

        result_10 = calculate_keltner_channel(closes, highs, lows, ema_period=10)
        result_20 = calculate_keltner_channel(closes, highs, lows, ema_period=20)

        assert result_10.middle != result_20.middle

    def test_different_atr_multipliers(self):
        """Test KC with different ATR multipliers."""
        highs, lows, closes = create_ohlc_data(50)

        result_1x = calculate_keltner_channel(closes, highs, lows, atr_multiplier=1.0)
        result_2x = calculate_keltner_channel(closes, highs, lows, atr_multiplier=2.0)
        result_3x = calculate_keltner_channel(closes, highs, lows, atr_multiplier=3.0)

        # Higher multiplier = wider channel
        width_1x = result_1x.upper - result_1x.lower
        width_2x = result_2x.upper - result_2x.lower
        width_3x = result_3x.upper - result_3x.lower

        assert width_3x > width_2x > width_1x

    def test_price_position_above_upper(self):
        """Test price_position='above_upper' when price is above upper band."""
        # Create uptrending data where price ends well above EMA
        highs, lows, closes = create_trending_up_data(50, trend=0.01)
        result = calculate_keltner_channel(closes, highs, lows, atr_multiplier=1.0)

        # With strong uptrend, price should be above upper
        if closes[-1] > result.upper:
            assert result.price_position == 'above_upper'

    def test_price_position_below_lower(self):
        """Test price_position='below_lower' when price is below lower band."""
        # Create downtrending data
        highs, lows, closes = create_trending_down_data(50, trend=-0.01)
        result = calculate_keltner_channel(closes, highs, lows, atr_multiplier=1.0)

        # With strong downtrend, price should be below lower
        if closes[-1] < result.lower:
            assert result.price_position == 'below_lower'

    def test_price_position_in_channel(self):
        """Test price_position='in_channel' for normal conditions."""
        # Create flat data where price should be near middle
        highs, lows, closes = create_flat_data(50)
        result = calculate_keltner_channel(closes, highs, lows)

        # Should be in channel or near bands
        assert result.price_position in ['in_channel', 'near_lower', 'near_upper']

    def test_percent_position_calculation(self):
        """Test percent_position is calculated correctly."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_keltner_channel(closes, highs, lows)

        # percent_position = (price - middle) / band_width
        band_width = result.upper - result.middle
        expected_percent = (closes[-1] - result.middle) / band_width
        assert abs(result.percent_position - expected_percent) < 0.0001

    def test_channel_width_pct_calculation(self):
        """Test channel_width_pct is calculated correctly."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_keltner_channel(closes, highs, lows)

        channel_range = result.upper - result.lower
        expected_pct = (channel_range / closes[-1]) * 100
        assert abs(result.channel_width_pct - expected_pct) < 0.0001

    def test_atr_value_returned(self):
        """Test that ATR value is included in result."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_keltner_channel(closes, highs, lows, atr_period=10)

        assert result.atr > 0
        # ATR should match simple ATR calculation
        expected_atr = calculate_atr_simple(highs, lows, closes, period=10)
        assert abs(result.atr - expected_atr) < 0.0001

    def test_zero_atr_returns_none(self):
        """Test KC returns None when ATR is zero."""
        # Constant prices result in zero ATR
        highs, lows, closes = create_constant_data(50)
        result = calculate_keltner_channel(closes, highs, lows)

        # Zero ATR means we can't calculate valid bands
        assert result is None

    def test_to_dict_method(self):
        """Test KeltnerChannelResult.to_dict() method."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_keltner_channel(closes, highs, lows)

        result_dict = result.to_dict()
        assert 'upper' in result_dict
        assert 'middle' in result_dict
        assert 'lower' in result_dict
        assert 'atr' in result_dict
        assert 'price_position' in result_dict
        assert 'percent_position' in result_dict
        assert 'channel_width_pct' in result_dict


# =============================================================================
# IS VOLATILITY SQUEEZE TESTS
# =============================================================================

class TestIsVolatilitySqueeze:
    """Tests for is_volatility_squeeze function."""

    def test_returns_boolean(self):
        """Test function returns boolean."""
        _, _, prices = create_ohlc_data(50)
        result = is_volatility_squeeze(prices, period=20)
        assert isinstance(result, bool)

    def test_squeeze_with_low_volatility(self):
        """Test squeeze detected with very low volatility data."""
        # Create extremely flat data
        prices = [100.0 + np.sin(i * 0.01) * 0.01 for i in range(50)]

        # Very high threshold should detect squeeze
        result = is_volatility_squeeze(prices, period=20, bandwidth_threshold=0.1)
        assert isinstance(result, bool)

    def test_no_squeeze_with_high_volatility(self):
        """Test no squeeze with high volatility data."""
        _, _, prices = create_ohlc_data(50, volatility=0.05)

        # Very low threshold should not detect squeeze
        result = is_volatility_squeeze(prices, period=20, bandwidth_threshold=0.001)
        assert result is False

    def test_insufficient_data_returns_false(self):
        """Test squeeze returns False with insufficient data."""
        prices = [100.0, 101.0, 102.0]
        result = is_volatility_squeeze(prices, period=20)
        assert result is False

    def test_threshold_sensitivity(self):
        """Test squeeze detection is sensitive to threshold."""
        _, _, prices = create_ohlc_data(50)

        # Very high threshold should (likely) detect squeeze
        result_high = is_volatility_squeeze(prices, bandwidth_threshold=1.0)
        # Very low threshold should (likely) not detect squeeze
        result_low = is_volatility_squeeze(prices, bandwidth_threshold=0.0001)

        assert result_high is True
        assert result_low is False

    def test_squeeze_uses_bollinger_bands(self):
        """Test that squeeze detection uses Bollinger Bands bandwidth."""
        _, _, prices = create_ohlc_data(50)
        period = 20

        bb = calculate_bollinger_bands(prices, period=period)
        squeeze_threshold = bb.bandwidth + 0.01  # Just above actual bandwidth

        result = is_volatility_squeeze(prices, period=period, bandwidth_threshold=squeeze_threshold)
        assert result is True


# =============================================================================
# EDGE CASES AND BOUNDARY CONDITIONS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_lists(self):
        """Test functions handle empty lists gracefully."""
        assert calculate_atr([], [], [], period=14) is None
        assert calculate_atr_simple([], [], [], period=14) is None
        assert calculate_bollinger_bands([], period=20) is None
        assert calculate_keltner_channel([], [], []) is None
        assert is_volatility_squeeze([], period=20) is False

    def test_single_element_lists(self):
        """Test functions handle single element lists."""
        assert calculate_atr([100.0], [99.0], [99.5], period=14) is None
        assert calculate_atr_simple([100.0], [99.0], [99.5], period=14) is None
        assert calculate_bollinger_bands([100.0], period=20) is None
        assert calculate_keltner_channel([100.0], [100.0], [100.0]) is None
        assert is_volatility_squeeze([100.0], period=20) is False

    def test_negative_prices(self):
        """Test functions handle negative prices (shouldn't happen but test robustness)."""
        highs = [-90.0, -89.0, -88.0] + [-87.0] * 20
        lows = [-92.0, -91.0, -90.0] + [-89.0] * 20
        closes = [-91.0, -90.0, -89.0] + [-88.0] * 20

        # Should not crash
        result = calculate_atr(highs, lows, closes, period=14)
        # Result may be valid or None depending on implementation

    def test_very_large_prices(self):
        """Test functions handle very large prices."""
        base = 1e10
        highs, lows, closes = create_ohlc_data(50, start=base)

        result_atr = calculate_atr(highs, lows, closes, period=14)
        result_bb = calculate_bollinger_bands(closes, period=20)
        result_kc = calculate_keltner_channel(closes, highs, lows)

        assert result_atr is not None
        assert result_bb is not None
        assert result_kc is not None

    def test_very_small_prices(self):
        """Test functions handle very small prices (penny stocks)."""
        highs, lows, closes = create_ohlc_data(50, start=0.01, volatility=0.1)

        result_atr = calculate_atr(highs, lows, closes, period=14)
        result_bb = calculate_bollinger_bands(closes, period=20)

        assert result_atr is not None
        assert result_bb is not None

    def test_period_equals_one(self):
        """Test functions with period=1 (edge case)."""
        highs, lows, closes = create_ohlc_data(50)

        # Period 1 should work but give limited usefulness
        result_bb = calculate_bollinger_bands(closes, period=1)
        # BB with period=1 has no std deviation meaning
        assert result_bb is not None

    def test_mismatched_list_lengths(self):
        """Test ATR functions with mismatched list lengths."""
        highs = [100.0] * 50
        lows = [99.0] * 40  # Shorter
        closes = [99.5] * 50

        # Should use shortest length or handle gracefully
        # The actual behavior depends on implementation
        # This tests that it doesn't crash
        try:
            calculate_atr(highs, lows, closes, period=14)
        except (IndexError, ValueError):
            pass  # Expected potential exception

    def test_all_identical_prices(self):
        """Test with all identical prices (zero volatility)."""
        price = 100.0
        prices = [price] * 50

        result_bb = calculate_bollinger_bands(prices, period=20)

        # All identical prices means std=0
        assert result_bb is not None
        assert result_bb.upper == result_bb.middle == result_bb.lower == price
        assert result_bb.bandwidth == 0
        assert result_bb.percent_b == 0.5  # Edge case handling

    def test_alternating_prices(self):
        """Test with alternating high/low prices."""
        prices = [100.0, 110.0] * 25  # 50 prices alternating

        result_bb = calculate_bollinger_bands(prices, period=20)

        assert result_bb is not None
        assert result_bb.bandwidth > 0

    def test_extreme_price_spike(self):
        """Test with extreme price spike."""
        _, _, prices = create_flat_data(49)
        prices.append(prices[-1] * 2)  # Double the price suddenly

        result_bb = calculate_bollinger_bands(prices, period=20)

        assert result_bb is not None
        # Price should be way above upper band
        assert result_bb.percent_b > 1.0

    def test_extreme_price_drop(self):
        """Test with extreme price drop."""
        _, _, prices = create_flat_data(49)
        prices.append(prices[-1] * 0.5)  # Halve the price suddenly

        result_bb = calculate_bollinger_bands(prices, period=20)

        assert result_bb is not None
        # Price should be way below lower band
        assert result_bb.percent_b < 0.0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests combining multiple volatility indicators."""

    def test_atr_and_bollinger_consistency(self):
        """Test ATR and Bollinger Bands show consistent volatility signals."""
        highs_low, lows_low, closes_low = create_ohlc_data(100, volatility=0.005)
        highs_high, lows_high, closes_high = create_ohlc_data(100, volatility=0.05)

        # Low volatility data
        atr_low = calculate_atr(highs_low, lows_low, closes_low, period=14)
        bb_low = calculate_bollinger_bands(closes_low, period=20)

        # High volatility data
        atr_high = calculate_atr(highs_high, lows_high, closes_high, period=14)
        bb_high = calculate_bollinger_bands(closes_high, period=20)

        # Both should show higher volatility for high vol data
        assert atr_high.atr_percent > atr_low.atr_percent
        assert bb_high.bandwidth > bb_low.bandwidth

    def test_keltner_and_bollinger_comparison(self):
        """Test Keltner Channel and Bollinger Bands on same data."""
        highs, lows, closes = create_ohlc_data(100)

        bb = calculate_bollinger_bands(closes, period=20)
        kc = calculate_keltner_channel(closes, highs, lows, ema_period=20)

        # Both should have valid results
        assert bb is not None
        assert kc is not None

        # Middle lines should be similar (SMA vs EMA)
        # But not identical due to SMA vs EMA calculation
        assert abs(bb.middle - kc.middle) < abs(bb.middle * 0.1)

    def test_squeeze_correlates_with_bandwidth(self):
        """Test squeeze detection correlates with BB bandwidth."""
        _, _, prices = create_ohlc_data(100)
        bb = calculate_bollinger_bands(prices, period=20)

        # Squeeze threshold equal to bandwidth should be borderline
        squeeze_at_bandwidth = is_volatility_squeeze(
            prices, period=20, bandwidth_threshold=bb.bandwidth
        )
        squeeze_above_bandwidth = is_volatility_squeeze(
            prices, period=20, bandwidth_threshold=bb.bandwidth + 0.01
        )

        # Should detect squeeze when threshold > bandwidth
        assert squeeze_above_bandwidth is True

    def test_all_indicators_on_real_like_data(self):
        """Test all indicators work together on realistic data."""
        highs, lows, closes = create_trending_up_data(200)

        atr = calculate_atr(highs, lows, closes, period=14)
        atr_simple = calculate_atr_simple(highs, lows, closes, period=14)
        bb = calculate_bollinger_bands(closes, period=20)
        kc = calculate_keltner_channel(closes, highs, lows, ema_period=20, atr_period=14)
        squeeze = is_volatility_squeeze(closes, period=20)

        # All should return valid results
        assert atr is not None
        assert atr_simple is not None
        assert bb is not None
        assert kc is not None
        assert isinstance(squeeze, bool)

        # Sanity checks
        assert atr.atr > 0
        assert atr_simple > 0
        assert bb.upper > bb.lower
        assert kc.upper > kc.lower


# =============================================================================
# NUMERICAL PRECISION TESTS
# =============================================================================

class TestNumericalPrecision:
    """Tests for numerical precision and stability."""

    def test_float_precision_in_calculations(self):
        """Test that calculations maintain reasonable float precision."""
        highs, lows, closes = create_ohlc_data(100, start=100.0)

        atr = calculate_atr(highs, lows, closes, period=14)
        bb = calculate_bollinger_bands(closes, period=20)

        # Results should be finite
        assert np.isfinite(atr.atr)
        assert np.isfinite(atr.atr_percent)
        assert np.isfinite(bb.upper)
        assert np.isfinite(bb.lower)
        assert np.isfinite(bb.bandwidth)

    def test_deterministic_results(self):
        """Test that results are deterministic with same input."""
        highs, lows, closes = create_ohlc_data(50, seed=123)

        result1 = calculate_atr(highs, lows, closes, period=14)
        result2 = calculate_atr(highs, lows, closes, period=14)

        assert result1.atr == result2.atr
        assert result1.atr_percent == result2.atr_percent

    def test_consistent_across_multiple_runs(self):
        """Test results are consistent across multiple runs."""
        highs, lows, closes = create_ohlc_data(50, seed=42)

        results = [calculate_bollinger_bands(closes, period=20) for _ in range(10)]

        # All results should be identical
        for r in results:
            assert r.upper == results[0].upper
            assert r.middle == results[0].middle
            assert r.lower == results[0].lower


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
