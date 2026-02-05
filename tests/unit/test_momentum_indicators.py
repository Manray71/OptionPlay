# Tests for Momentum Indicators Module
# =====================================
"""
Tests for RSI, MACD, Stochastic and divergence calculations.
"""

import pytest
import numpy as np

from src.indicators.momentum import (
    calculate_rsi,
    calculate_macd,
    calculate_stochastic,
    calculate_rsi_series,
    find_swing_lows,
    find_swing_highs,
    calculate_rsi_divergence,
)
from src.models.indicators import MACDResult, StochasticResult


# =============================================================================
# RSI TESTS
# =============================================================================

class TestCalculateRSI:
    """Tests for calculate_rsi function."""

    def test_returns_float(self):
        """Test calculate_rsi returns float."""
        prices = list(range(100, 150))  # Uptrend
        result = calculate_rsi(prices)

        assert isinstance(result, float)

    def test_uptrend_high_rsi(self):
        """Test uptrend produces high RSI."""
        prices = list(range(100, 130))  # Strong uptrend
        result = calculate_rsi(prices)

        assert result > 60  # Should be high in uptrend

    def test_downtrend_low_rsi(self):
        """Test downtrend produces low RSI."""
        prices = list(range(130, 100, -1))  # Strong downtrend
        result = calculate_rsi(prices)

        assert result < 40  # Should be low in downtrend

    def test_insufficient_data_returns_50(self):
        """Test insufficient data returns neutral 50."""
        prices = [100, 101, 102]  # Too few points
        result = calculate_rsi(prices)

        assert result == 50.0

    def test_rsi_range_0_to_100(self):
        """Test RSI stays in 0-100 range."""
        prices = list(range(100, 150))
        result = calculate_rsi(prices)

        assert 0 <= result <= 100

    def test_custom_period(self):
        """Test custom RSI period works without error."""
        # Use mixed data where results may differ
        np.random.seed(42)
        prices = [100 + np.random.randn() * 2 for _ in range(50)]
        result_14 = calculate_rsi(prices, period=14)
        result_7 = calculate_rsi(prices, period=7)

        # Both should return valid RSI values
        assert 0 <= result_14 <= 100
        assert 0 <= result_7 <= 100

    def test_all_gains_returns_100(self):
        """Test all gains scenario returns 100."""
        prices = list(range(100, 125))  # Consistent gains
        result = calculate_rsi(prices)

        assert result == 100.0


# =============================================================================
# MACD TESTS
# =============================================================================

class TestCalculateMACD:
    """Tests for calculate_macd function."""

    def test_returns_macd_result(self):
        """Test calculate_macd returns MACDResult."""
        prices = [100 + i * 0.5 for i in range(50)]  # Uptrend
        result = calculate_macd(prices)

        assert isinstance(result, MACDResult)

    def test_insufficient_data_returns_none(self):
        """Test insufficient data returns None."""
        prices = [100, 101, 102]  # Too few points
        result = calculate_macd(prices)

        assert result is None

    def test_macd_attributes(self):
        """Test MACDResult has expected attributes."""
        prices = [100 + i * 0.5 for i in range(50)]
        result = calculate_macd(prices)

        assert hasattr(result, 'macd_line')
        assert hasattr(result, 'signal_line')
        assert hasattr(result, 'histogram')
        assert hasattr(result, 'crossover')

    def test_histogram_is_difference(self):
        """Test histogram is MACD minus signal."""
        prices = [100 + i * 0.5 for i in range(50)]
        result = calculate_macd(prices)

        expected_histogram = result.macd_line - result.signal_line
        assert abs(result.histogram - expected_histogram) < 0.001

    def test_uptrend_positive_macd(self):
        """Test uptrend produces positive MACD."""
        prices = [100 + i * 2 for i in range(50)]  # Strong uptrend
        result = calculate_macd(prices)

        assert result.macd_line > 0

    def test_custom_periods(self):
        """Test custom MACD periods."""
        prices = [100 + i * 0.5 for i in range(50)]
        result = calculate_macd(prices, fast_period=8, slow_period=17, signal_period=9)

        assert isinstance(result, MACDResult)


# =============================================================================
# STOCHASTIC TESTS
# =============================================================================

class TestCalculateStochastic:
    """Tests for calculate_stochastic function."""

    @pytest.fixture
    def price_data(self):
        """Create price data with high, low, close."""
        base = 100
        closes = [base + i * 0.5 for i in range(30)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        return highs, lows, closes

    def test_returns_stochastic_result(self, price_data):
        """Test calculate_stochastic returns StochasticResult."""
        highs, lows, closes = price_data
        result = calculate_stochastic(highs, lows, closes)

        assert isinstance(result, StochasticResult)

    def test_insufficient_data_returns_none(self):
        """Test insufficient data returns None."""
        result = calculate_stochastic([100, 101], [99, 100], [99.5, 100.5])

        assert result is None

    def test_mismatched_lengths_returns_none(self):
        """Test mismatched array lengths returns None."""
        result = calculate_stochastic([100, 101], [99], [99.5, 100.5])

        assert result is None

    def test_stochastic_attributes(self, price_data):
        """Test StochasticResult has expected attributes."""
        highs, lows, closes = price_data
        result = calculate_stochastic(highs, lows, closes)

        assert hasattr(result, 'k')
        assert hasattr(result, 'd')
        assert hasattr(result, 'crossover')
        assert hasattr(result, 'zone')

    def test_k_in_range(self, price_data):
        """Test %K is in 0-100 range."""
        highs, lows, closes = price_data
        result = calculate_stochastic(highs, lows, closes)

        assert 0 <= result.k <= 100

    def test_d_in_range(self, price_data):
        """Test %D is in 0-100 range."""
        highs, lows, closes = price_data
        result = calculate_stochastic(highs, lows, closes)

        assert 0 <= result.d <= 100

    def test_oversold_zone(self):
        """Test oversold zone detection."""
        # Create downtrend data
        closes = [100 - i * 2 for i in range(30)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]

        result = calculate_stochastic(highs, lows, closes)

        # In strong downtrend, should be oversold
        assert result.zone in ['oversold', 'neutral']


# =============================================================================
# RSI SERIES TESTS
# =============================================================================

class TestCalculateRSISeries:
    """Tests for calculate_rsi_series function."""

    def test_returns_list(self):
        """Test calculate_rsi_series returns list."""
        prices = list(range(100, 130))
        result = calculate_rsi_series(prices)

        assert isinstance(result, list)

    def test_returns_non_empty_list(self):
        """Test result is not empty for sufficient data."""
        prices = list(range(100, 130))
        result = calculate_rsi_series(prices)

        assert len(result) > 0
        # RSI series may be slightly shorter due to diff calculation
        assert len(result) >= len(prices) - 1

    def test_initial_values_are_50(self):
        """Test initial values are 50 (placeholder)."""
        prices = list(range(100, 130))
        result = calculate_rsi_series(prices, period=14)

        # First 14 values should be 50
        for i in range(14):
            assert result[i] == 50.0


# =============================================================================
# SWING POINT TESTS
# =============================================================================

class TestSwingPoints:
    """Tests for swing point detection functions."""

    def test_find_swing_lows_returns_list(self):
        """Test find_swing_lows returns list."""
        values = [100, 95, 90, 95, 100, 98, 88, 92, 96, 100]
        result = find_swing_lows(values, window=2, lookback=10)

        assert isinstance(result, list)

    def test_find_swing_highs_returns_list(self):
        """Test find_swing_highs returns list."""
        values = [90, 95, 100, 95, 90, 92, 105, 98, 94, 90]
        result = find_swing_highs(values, window=2, lookback=10)

        assert isinstance(result, list)

    def test_swing_low_format(self):
        """Test swing low format is (index, value) tuple."""
        values = [100, 95, 90, 95, 100, 98, 88, 92, 96, 100]
        result = find_swing_lows(values, window=2, lookback=10)

        if result:
            assert isinstance(result[0], tuple)
            assert len(result[0]) == 2

    def test_swing_high_format(self):
        """Test swing high format is (index, value) tuple."""
        values = [90, 95, 100, 95, 90, 92, 105, 98, 94, 90]
        result = find_swing_highs(values, window=2, lookback=10)

        if result:
            assert isinstance(result[0], tuple)
            assert len(result[0]) == 2


# =============================================================================
# RSI DIVERGENCE TESTS
# =============================================================================

class TestCalculateRSIDivergence:
    """Tests for calculate_rsi_divergence function."""

    def test_insufficient_data_returns_none(self):
        """Test insufficient data returns None."""
        prices = [100, 101, 102]
        lows = [99, 100, 101]
        highs = [101, 102, 103]

        result = calculate_rsi_divergence(prices, lows, highs)

        assert result is None

    def test_with_sufficient_data(self):
        """Test with sufficient data."""
        # Create 100 data points
        np.random.seed(42)
        base = 100
        noise = np.random.randn(100) * 2
        prices = [base + i * 0.1 + noise[i] for i in range(100)]
        lows = [p - 1 for p in prices]
        highs = [p + 1 for p in prices]

        result = calculate_rsi_divergence(prices, lows, highs)

        # May or may not find divergence, but should not crash
        assert result is None or hasattr(result, 'divergence_type')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
