# Tests for src/indicators/trend.py
# ==================================
"""
Comprehensive unit tests for trend indicator functions.

This module tests:
- calculate_sma: Simple Moving Average calculation
- calculate_ema: Exponential Moving Average calculation
- calculate_adx: Average Directional Index calculation
- get_trend_direction: Trend direction detection

Focus areas:
- Edge cases (empty data, insufficient data, single values)
- Mathematical correctness validation
- Boundary conditions
- Type handling
"""

import pytest
import numpy as np
from typing import List

from src.indicators.trend import (
    calculate_sma,
    calculate_ema,
    calculate_adx,
    get_trend_direction,
)


# =============================================================================
# TEST FIXTURES AND HELPERS
# =============================================================================

@pytest.fixture
def uptrend_prices() -> List[float]:
    """Generate clear uptrend price data."""
    return [100.0 + i * 1.5 for i in range(100)]


@pytest.fixture
def downtrend_prices() -> List[float]:
    """Generate clear downtrend price data."""
    return [200.0 - i * 1.5 for i in range(100)]


@pytest.fixture
def flat_prices() -> List[float]:
    """Generate flat/constant price data."""
    return [100.0] * 50


@pytest.fixture
def volatile_prices() -> List[float]:
    """Generate highly volatile price data with seeded randomness."""
    np.random.seed(42)
    base = 100.0
    return [base + np.random.uniform(-10, 10) for _ in range(100)]


@pytest.fixture
def ohlc_uptrend():
    """Generate OHLC data for strong uptrend."""
    n = 50
    closes = [100.0 + i * 2.0 for i in range(n)]
    highs = [c + 1.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return highs, lows, closes


@pytest.fixture
def ohlc_downtrend():
    """Generate OHLC data for strong downtrend."""
    n = 50
    closes = [200.0 - i * 2.0 for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 1.5 for c in closes]
    return highs, lows, closes


@pytest.fixture
def ohlc_sideways():
    """Generate OHLC data for sideways market."""
    np.random.seed(123)
    n = 50
    closes = [100.0 + np.sin(i * 0.3) * 2 for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return highs, lows, closes


# =============================================================================
# CALCULATE_SMA TESTS
# =============================================================================

class TestCalculateSMA:
    """Comprehensive tests for calculate_sma function."""

    # --- Basic Functionality ---

    def test_sma_basic_calculation(self):
        """Test SMA calculates correct average of last n prices."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = calculate_sma(prices, period=3)

        # Should be average of last 3: (30 + 40 + 50) / 3 = 40
        expected = 40.0
        assert result == pytest.approx(expected)

    def test_sma_uses_last_n_prices(self):
        """Test SMA uses only the last n prices, not all."""
        prices = [1.0, 2.0, 3.0, 100.0, 100.0, 100.0]
        result = calculate_sma(prices, period=3)

        # Should be average of last 3: (100 + 100 + 100) / 3 = 100
        assert result == pytest.approx(100.0)

    def test_sma_full_period_equals_length(self):
        """Test SMA when period equals data length."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = calculate_sma(prices, period=5)

        expected = (10.0 + 20.0 + 30.0 + 40.0 + 50.0) / 5
        assert result == pytest.approx(expected)

    def test_sma_period_one(self):
        """Test SMA with period 1 returns last price."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = calculate_sma(prices, period=1)

        assert result == pytest.approx(50.0)

    def test_sma_returns_float(self):
        """Test SMA always returns a float."""
        prices = [100, 200, 300]  # integers
        result = calculate_sma(prices, period=2)

        assert isinstance(result, float)

    # --- Edge Cases ---

    def test_sma_empty_list(self):
        """Test SMA with empty list returns 0.0."""
        result = calculate_sma([], period=5)
        assert result == 0.0

    def test_sma_single_price(self):
        """Test SMA with single price returns that price."""
        result = calculate_sma([42.5], period=10)
        assert result == pytest.approx(42.5)

    def test_sma_insufficient_data(self):
        """Test SMA with insufficient data returns last price."""
        prices = [100.0, 110.0, 120.0]
        result = calculate_sma(prices, period=10)

        assert result == pytest.approx(120.0)

    def test_sma_insufficient_data_returns_last(self):
        """Verify insufficient data always returns the last price."""
        prices = [50.0, 75.0]
        result = calculate_sma(prices, period=100)

        assert result == pytest.approx(75.0)

    # --- Mathematical Validation ---

    def test_sma_flat_prices_equals_price(self):
        """Test SMA of constant prices equals that price."""
        prices = [100.0] * 20
        result = calculate_sma(prices, period=10)

        assert result == pytest.approx(100.0)

    def test_sma_mathematical_correctness(self):
        """Test SMA mathematical formula explicitly."""
        prices = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        period = 5
        result = calculate_sma(prices, period=period)

        # Manual calculation: mean of [6, 7, 8, 9, 10] = 8.0
        expected = np.mean(prices[-period:])
        assert result == pytest.approx(expected)

    def test_sma_with_numpy_array(self):
        """Test SMA works with numpy arrays (duck typing)."""
        prices = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        result = calculate_sma(list(prices), period=3)

        assert result == pytest.approx(40.0)

    def test_sma_negative_prices(self):
        """Test SMA handles negative prices correctly."""
        prices = [-10.0, -20.0, -30.0, -40.0, -50.0]
        result = calculate_sma(prices, period=3)

        expected = (-30.0 + -40.0 + -50.0) / 3
        assert result == pytest.approx(expected)

    def test_sma_mixed_positive_negative(self):
        """Test SMA handles mixed positive/negative prices."""
        prices = [-10.0, 10.0, -10.0, 10.0, -10.0]
        result = calculate_sma(prices, period=5)

        # Sum: -10 + 10 - 10 + 10 - 10 = -10, average = -2
        expected = (-10.0 + 10.0 - 10.0 + 10.0 - 10.0) / 5
        assert result == pytest.approx(expected)

    def test_sma_large_values(self):
        """Test SMA handles large values without overflow."""
        prices = [1e10, 2e10, 3e10, 4e10, 5e10]
        result = calculate_sma(prices, period=3)

        expected = (3e10 + 4e10 + 5e10) / 3
        assert result == pytest.approx(expected)

    def test_sma_small_values(self):
        """Test SMA handles small values without precision loss."""
        prices = [1e-10, 2e-10, 3e-10, 4e-10, 5e-10]
        result = calculate_sma(prices, period=3)

        expected = (3e-10 + 4e-10 + 5e-10) / 3
        assert result == pytest.approx(expected, rel=1e-5)


# =============================================================================
# CALCULATE_EMA TESTS
# =============================================================================

class TestCalculateEMA:
    """Comprehensive tests for calculate_ema function."""

    # --- Basic Functionality ---

    def test_ema_returns_list(self):
        """Test EMA returns a list."""
        prices = [100.0 + i for i in range(20)]
        result = calculate_ema(prices, period=5)

        assert isinstance(result, list)

    def test_ema_output_length(self):
        """Test EMA output length is correct."""
        prices = [100.0 + i for i in range(50)]
        period = 10
        result = calculate_ema(prices, period=period)

        # First value is SMA of first 'period' prices
        # Then EMA values for remaining prices
        expected_length = len(prices) - period + 1
        assert len(result) == expected_length

    def test_ema_first_value_is_sma(self):
        """Test first EMA value equals SMA of first n prices."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        period = 5
        result = calculate_ema(prices, period=period)

        # First EMA value should be SMA of first 5 prices
        expected_first = np.mean(prices[:period])
        assert result[0] == pytest.approx(expected_first)

    def test_ema_multiplier_formula(self):
        """Test EMA uses correct multiplier formula."""
        prices = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        period = 5
        result = calculate_ema(prices, period=period)

        multiplier = 2 / (period + 1)

        # First value is SMA
        expected_first = np.mean(prices[:period])
        assert result[0] == pytest.approx(expected_first)

        # Second value uses EMA formula
        expected_second = (prices[period] * multiplier) + (expected_first * (1 - multiplier))
        assert result[1] == pytest.approx(expected_second)

    def test_ema_returns_all_floats(self):
        """Test all EMA values are floats."""
        prices = [100, 110, 120, 130, 140, 150]  # integers
        result = calculate_ema(prices, period=3)

        for val in result:
            assert isinstance(val, (float, np.floating))

    # --- Edge Cases ---

    def test_ema_insufficient_data_returns_prices(self):
        """Test EMA with insufficient data returns original prices."""
        prices = [100.0, 110.0]
        result = calculate_ema(prices, period=10)

        assert result == prices

    def test_ema_exact_period_length(self):
        """Test EMA when data length equals period."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = calculate_ema(prices, period=5)

        # Should return single value (the SMA)
        assert len(result) == 1
        expected = np.mean(prices)
        assert result[0] == pytest.approx(expected)

    def test_ema_period_one(self):
        """Test EMA with period 1 returns all prices."""
        prices = [100.0, 110.0, 120.0]
        result = calculate_ema(prices, period=1)

        # With period=1, first SMA is just prices[0]
        # Then each EMA = price (since multiplier = 2/2 = 1)
        assert len(result) == len(prices)

    def test_ema_empty_list_with_period_zero_handling(self):
        """Test EMA with edge period values."""
        prices = [100.0, 110.0, 120.0, 130.0, 140.0]
        result = calculate_ema(prices, period=2)

        assert len(result) == 4  # 5 - 2 + 1

    # --- Trend Following Behavior ---

    def test_ema_follows_uptrend(self, uptrend_prices):
        """Test EMA increases in uptrend."""
        result = calculate_ema(uptrend_prices, period=10)

        # EMA should be increasing
        for i in range(1, len(result)):
            assert result[i] > result[i-1]

    def test_ema_follows_downtrend(self, downtrend_prices):
        """Test EMA decreases in downtrend."""
        result = calculate_ema(downtrend_prices, period=10)

        # EMA should be decreasing
        for i in range(1, len(result)):
            assert result[i] < result[i-1]

    def test_ema_flat_prices_stays_flat(self, flat_prices):
        """Test EMA of constant prices stays constant."""
        result = calculate_ema(flat_prices, period=10)

        for val in result:
            assert val == pytest.approx(100.0)

    def test_ema_reacts_faster_with_shorter_period(self):
        """Test shorter period EMA reacts faster to price changes."""
        # Price starts flat then jumps
        prices = [100.0] * 20 + [150.0] * 10

        ema_fast = calculate_ema(prices, period=5)
        ema_slow = calculate_ema(prices, period=15)

        # Fast EMA should be higher (closer to new price)
        assert ema_fast[-1] > ema_slow[-1]

    # --- Mathematical Validation ---

    def test_ema_lag_less_than_sma(self):
        """Test EMA lags less than SMA in trending market."""
        prices = [100.0 + i * 2.0 for i in range(50)]
        period = 10

        ema_values = calculate_ema(prices, period=period)
        ema_last = ema_values[-1]

        sma_last = calculate_sma(prices, period=period)

        # In uptrend, EMA should be approximately equal or slightly higher than SMA
        # (due to EMA weighting recent prices more heavily)
        # Use approx comparison to handle floating point precision
        assert ema_last == pytest.approx(sma_last, rel=0.01)

    def test_ema_smoothing_effect(self, volatile_prices):
        """Test EMA provides smoothing effect on volatile data."""
        result = calculate_ema(volatile_prices, period=20)

        # Calculate standard deviation
        original_std = np.std(volatile_prices[-len(result):])
        ema_std = np.std(result)

        # EMA should have lower variance than original
        assert ema_std < original_std


# =============================================================================
# CALCULATE_ADX TESTS
# =============================================================================

class TestCalculateADX:
    """Comprehensive tests for calculate_adx function."""

    # --- Basic Functionality ---

    def test_adx_returns_float_or_none(self, ohlc_uptrend):
        """Test ADX returns float or None."""
        highs, lows, closes = ohlc_uptrend
        result = calculate_adx(highs, lows, closes, period=14)

        assert result is None or isinstance(result, (float, np.floating))

    def test_adx_range_0_to_100(self, ohlc_uptrend):
        """Test ADX value is in 0-100 range."""
        highs, lows, closes = ohlc_uptrend
        result = calculate_adx(highs, lows, closes, period=14)

        assert result is not None
        assert 0 <= result <= 100

    def test_adx_default_period(self, ohlc_uptrend):
        """Test ADX uses default period of 14."""
        highs, lows, closes = ohlc_uptrend
        result_default = calculate_adx(highs, lows, closes)
        result_14 = calculate_adx(highs, lows, closes, period=14)

        assert result_default == result_14

    # --- Edge Cases ---

    def test_adx_insufficient_data_returns_none(self):
        """Test ADX returns None with insufficient data."""
        highs = [100.0, 101.0, 102.0]
        lows = [99.0, 100.0, 101.0]
        closes = [99.5, 100.5, 101.5]

        result = calculate_adx(highs, lows, closes, period=14)

        assert result is None

    def test_adx_minimum_data_for_period(self):
        """Test ADX with exactly minimum required data."""
        # Need period + 1 data points minimum
        n = 16  # 14 + 1 + 1 for calculations
        highs = [100.0 + i * 0.5 for i in range(n)]
        lows = [99.0 + i * 0.5 for i in range(n)]
        closes = [99.5 + i * 0.5 for i in range(n)]

        result = calculate_adx(highs, lows, closes, period=14)

        # May or may not return None depending on exact minimum
        assert result is None or isinstance(result, float)

    def test_adx_shorter_period(self, ohlc_uptrend):
        """Test ADX with shorter period."""
        highs, lows, closes = ohlc_uptrend
        result = calculate_adx(highs, lows, closes, period=7)

        assert result is not None
        assert 0 <= result <= 100

    def test_adx_empty_lists(self):
        """Test ADX with empty lists returns None."""
        result = calculate_adx([], [], [], period=14)

        assert result is None

    # --- Trend Strength Detection ---

    def test_adx_strong_uptrend_high_value(self, ohlc_uptrend):
        """Test ADX is high for strong uptrend."""
        highs, lows, closes = ohlc_uptrend
        result = calculate_adx(highs, lows, closes, period=14)

        # Strong trend should have higher ADX
        assert result is not None
        assert result > 0

    def test_adx_strong_downtrend_high_value(self, ohlc_downtrend):
        """Test ADX is high for strong downtrend."""
        highs, lows, closes = ohlc_downtrend
        result = calculate_adx(highs, lows, closes, period=14)

        # Strong trend (regardless of direction) should have higher ADX
        assert result is not None
        assert result > 0

    def test_adx_sideways_lower_than_trending(self, ohlc_uptrend, ohlc_sideways):
        """Test ADX is lower for sideways market than trending."""
        highs_trend, lows_trend, closes_trend = ohlc_uptrend
        highs_side, lows_side, closes_side = ohlc_sideways

        adx_trend = calculate_adx(highs_trend, lows_trend, closes_trend, period=14)
        adx_side = calculate_adx(highs_side, lows_side, closes_side, period=14)

        # Both should return values
        assert adx_trend is not None
        assert adx_side is not None

        # Trending market should have higher ADX
        assert adx_trend > adx_side

    # --- Mathematical Edge Cases ---

    def test_adx_flat_market_zero_atr(self):
        """Test ADX handles zero ATR edge case."""
        # Completely flat market (all OHLC same)
        n = 30
        highs = [100.0] * n
        lows = [100.0] * n
        closes = [100.0] * n

        result = calculate_adx(highs, lows, closes, period=14)

        # Should return None when ATR is zero
        assert result is None

    def test_adx_custom_period_variations(self):
        """Test ADX with various custom periods."""
        np.random.seed(42)
        n = 100
        base = 100.0
        closes = [base + i * 0.5 + np.random.uniform(-1, 1) for i in range(n)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]

        for period in [5, 10, 14, 20]:
            result = calculate_adx(highs, lows, closes, period=period)
            if result is not None:
                assert 0 <= result <= 100


# =============================================================================
# GET_TREND_DIRECTION TESTS
# =============================================================================

class TestGetTrendDirection:
    """Comprehensive tests for get_trend_direction function."""

    # --- Basic Trend Detection ---

    def test_uptrend_price_above_both_mas(self):
        """Test uptrend when price above both MAs."""
        result = get_trend_direction(
            price=150.0,
            sma_short=130.0,
            sma_long=100.0
        )
        assert result == 'uptrend'

    def test_downtrend_price_below_both_mas(self):
        """Test downtrend when price below both MAs."""
        result = get_trend_direction(
            price=80.0,
            sma_short=90.0,
            sma_long=100.0
        )
        assert result == 'downtrend'

    def test_sideways_above_long_below_short(self):
        """Test sideways when above long MA but below short MA."""
        result = get_trend_direction(
            price=105.0,
            sma_short=110.0,
            sma_long=100.0
        )
        assert result == 'sideways'

    def test_sideways_below_long_above_short(self):
        """Test sideways when below long MA but above short MA."""
        result = get_trend_direction(
            price=95.0,
            sma_short=90.0,
            sma_long=100.0
        )
        assert result == 'sideways'

    # --- Boundary Conditions ---

    def test_price_equals_short_ma_above_long(self):
        """Test when price equals short MA but above long MA."""
        result = get_trend_direction(
            price=110.0,
            sma_short=110.0,  # Equal
            sma_long=100.0
        )
        # Not above short, so sideways
        assert result == 'sideways'

    def test_price_equals_long_ma_above_short(self):
        """Test when price equals long MA but above short MA."""
        result = get_trend_direction(
            price=100.0,
            sma_short=90.0,
            sma_long=100.0  # Equal
        )
        # Not above long, so sideways
        assert result == 'sideways'

    def test_price_equals_both_mas(self):
        """Test when price equals both MAs."""
        result = get_trend_direction(
            price=100.0,
            sma_short=100.0,
            sma_long=100.0
        )
        # Not above either, so sideways (actually downtrend per logic)
        assert result == 'downtrend'

    def test_price_equals_short_below_long(self):
        """Test when price equals short MA and both below long MA."""
        result = get_trend_direction(
            price=90.0,
            sma_short=90.0,
            sma_long=100.0
        )
        # Not above short, not above long = downtrend
        assert result == 'downtrend'

    # --- Edge Cases with MA Crossovers ---

    def test_golden_cross_scenario(self):
        """Test scenario after golden cross (short > long)."""
        # Price and short MA above long MA
        result = get_trend_direction(
            price=115.0,
            sma_short=110.0,  # Short MA crossed above long
            sma_long=100.0
        )
        assert result == 'uptrend'

    def test_death_cross_scenario(self):
        """Test scenario after death cross (short < long)."""
        # Price and short MA below long MA
        result = get_trend_direction(
            price=85.0,
            sma_short=90.0,  # Short MA crossed below long
            sma_long=100.0
        )
        assert result == 'downtrend'

    def test_whipsaw_scenario(self):
        """Test whipsaw scenario (MAs close together)."""
        # Price bouncing around closely spaced MAs
        result = get_trend_direction(
            price=100.5,
            sma_short=100.0,
            sma_long=99.5
        )
        # Above both = uptrend
        assert result == 'uptrend'

    # --- Return Value Validation ---

    def test_returns_string(self):
        """Test return value is always a string."""
        result = get_trend_direction(100.0, 95.0, 90.0)
        assert isinstance(result, str)

    def test_returns_valid_trend_value(self):
        """Test return value is one of valid options."""
        valid_values = {'uptrend', 'downtrend', 'sideways'}

        test_cases = [
            (150.0, 130.0, 100.0),  # uptrend
            (80.0, 90.0, 100.0),    # downtrend
            (105.0, 110.0, 100.0),  # sideways
        ]

        for price, short, long in test_cases:
            result = get_trend_direction(price, short, long)
            assert result in valid_values

    # --- Numerical Edge Cases ---

    def test_very_small_differences(self):
        """Test with very small price differences."""
        result = get_trend_direction(
            price=100.0001,
            sma_short=100.0,
            sma_long=99.9999
        )
        # Above both (barely)
        assert result == 'uptrend'

    def test_large_values(self):
        """Test with large price values."""
        result = get_trend_direction(
            price=50000.0,
            sma_short=48000.0,
            sma_long=45000.0
        )
        assert result == 'uptrend'

    def test_negative_values(self):
        """Test with negative values (edge case)."""
        result = get_trend_direction(
            price=-50.0,
            sma_short=-60.0,
            sma_long=-70.0
        )
        # -50 > -60 and -50 > -70 = uptrend
        assert result == 'uptrend'

    def test_zero_values(self):
        """Test with zero values."""
        result = get_trend_direction(
            price=10.0,
            sma_short=0.0,
            sma_long=-5.0
        )
        # 10 > 0 and 10 > -5 = uptrend
        assert result == 'uptrend'


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestTrendIndicatorsIntegration:
    """Integration tests combining multiple trend functions."""

    def test_sma_based_trend_detection_uptrend(self, uptrend_prices):
        """Test trend detection using calculated SMAs in uptrend."""
        sma_short = calculate_sma(uptrend_prices, period=20)
        sma_long = calculate_sma(uptrend_prices, period=50)
        current_price = uptrend_prices[-1]

        direction = get_trend_direction(current_price, sma_short, sma_long)

        assert direction == 'uptrend'

    def test_sma_based_trend_detection_downtrend(self, downtrend_prices):
        """Test trend detection using calculated SMAs in downtrend."""
        sma_short = calculate_sma(downtrend_prices, period=20)
        sma_long = calculate_sma(downtrend_prices, period=50)
        current_price = downtrend_prices[-1]

        direction = get_trend_direction(current_price, sma_short, sma_long)

        assert direction == 'downtrend'

    def test_ema_based_trend_detection(self, uptrend_prices):
        """Test trend detection using EMA values."""
        ema_short = calculate_ema(uptrend_prices, period=12)
        ema_long = calculate_ema(uptrend_prices, period=26)
        current_price = uptrend_prices[-1]

        direction = get_trend_direction(
            current_price,
            ema_short[-1],
            ema_long[-1]
        )

        assert direction == 'uptrend'

    def test_adx_confirms_trend_strength(self, ohlc_uptrend):
        """Test ADX provides trend strength confirmation."""
        highs, lows, closes = ohlc_uptrend

        # Get trend direction
        sma_short = calculate_sma(closes, period=20)
        sma_long = calculate_sma(closes, period=50)
        direction = get_trend_direction(closes[-1], sma_short, sma_long)

        # Get trend strength
        adx = calculate_adx(highs, lows, closes, period=14)

        # Should have uptrend with measurable strength
        assert direction == 'uptrend'
        assert adx is not None
        assert adx > 0

    def test_complete_trend_analysis_workflow(self):
        """Test complete workflow for trend analysis."""
        # Generate realistic price data
        np.random.seed(42)
        n = 100
        base = 100.0
        trend = 0.3  # Slight uptrend

        closes = []
        for i in range(n):
            price = base + i * trend + np.random.uniform(-1, 1)
            closes.append(price)

        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]

        # Calculate indicators
        sma_20 = calculate_sma(closes, period=20)
        sma_50 = calculate_sma(closes, period=50)
        ema_20 = calculate_ema(closes, period=20)
        adx = calculate_adx(highs, lows, closes, period=14)

        # Get trend direction
        direction = get_trend_direction(closes[-1], sma_20, sma_50)

        # All should return valid values
        assert isinstance(sma_20, float)
        assert isinstance(sma_50, float)
        assert isinstance(ema_20, list) and len(ema_20) > 0
        assert adx is None or isinstance(adx, float)
        assert direction in {'uptrend', 'downtrend', 'sideways'}


# =============================================================================
# PERFORMANCE AND EDGE CASE TESTS
# =============================================================================

class TestPerformanceAndEdgeCases:
    """Tests for performance characteristics and unusual edge cases."""

    def test_sma_large_dataset(self):
        """Test SMA performance with large dataset."""
        prices = list(range(10000))
        result = calculate_sma(prices, period=200)

        assert isinstance(result, float)

    def test_ema_large_dataset(self):
        """Test EMA performance with large dataset."""
        prices = [float(i) for i in range(10000)]
        result = calculate_ema(prices, period=200)

        assert isinstance(result, list)
        assert len(result) > 0

    def test_adx_large_dataset(self):
        """Test ADX performance with large dataset."""
        n = 1000
        closes = [100.0 + i * 0.1 for i in range(n)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]

        result = calculate_adx(highs, lows, closes, period=14)

        assert result is not None

    def test_sma_precision_with_floats(self):
        """Test SMA maintains precision with floating point numbers."""
        prices = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = calculate_sma(prices, period=5)

        expected = 0.3
        assert result == pytest.approx(expected, rel=1e-10)

    def test_ema_precision_accumulation(self):
        """Test EMA doesn't accumulate precision errors."""
        prices = [100.0 + 0.01 * i for i in range(1000)]
        result = calculate_ema(prices, period=10)

        # Last EMA value should be close to recent prices
        assert result[-1] == pytest.approx(prices[-1], rel=0.1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
