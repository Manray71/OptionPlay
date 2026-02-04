# Tests for Trend Indicators
# ==========================
"""
Tests for trend indicator functions.
"""

import pytest
import numpy as np

from src.indicators.trend import (
    calculate_sma,
    calculate_ema,
    calculate_adx,
    get_trend_direction,
)


# =============================================================================
# SAMPLE DATA
# =============================================================================

def create_uptrend_prices(n: int = 100, start: float = 100.0):
    """Create uptrending price data."""
    return [start + i * 0.5 for i in range(n)]


def create_downtrend_prices(n: int = 100, start: float = 100.0):
    """Create downtrending price data."""
    return [start - i * 0.5 for i in range(n)]


def create_sideways_prices(n: int = 100, center: float = 100.0):
    """Create sideways price data."""
    np.random.seed(42)
    return [center + np.sin(i * 0.1) * 2 for i in range(n)]


def create_ohlc_data(n: int = 100):
    """Create OHLC data for ADX testing."""
    np.random.seed(42)
    closes = [100.0]
    for i in range(1, n):
        change = np.random.normal(0, 0.02)
        closes.append(closes[-1] * (1 + change))

    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]

    return highs, lows, closes


# =============================================================================
# CALCULATE SMA TESTS
# =============================================================================

class TestCalculateSMA:
    """Tests for calculate_sma function."""

    def test_sma_basic(self):
        """Test basic SMA calculation."""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = calculate_sma(prices, period=3)

        expected = (30.0 + 40.0 + 50.0) / 3
        assert result == pytest.approx(expected)

    def test_sma_full_period(self):
        """Test SMA with full period."""
        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = calculate_sma(prices, period=5)

        expected = (1.0 + 2.0 + 3.0 + 4.0 + 5.0) / 5
        assert result == pytest.approx(expected)

    def test_sma_insufficient_data(self):
        """Test SMA with insufficient data returns last price."""
        prices = [10.0, 20.0]
        result = calculate_sma(prices, period=10)

        assert result == 20.0

    def test_sma_empty_list(self):
        """Test SMA with empty list returns 0."""
        result = calculate_sma([], period=5)
        assert result == 0.0

    def test_sma_single_price(self):
        """Test SMA with single price."""
        result = calculate_sma([100.0], period=20)
        assert result == 100.0


# =============================================================================
# CALCULATE EMA TESTS
# =============================================================================

class TestCalculateEMA:
    """Tests for calculate_ema function."""

    def test_ema_basic(self):
        """Test basic EMA calculation."""
        prices = create_uptrend_prices(20)
        result = calculate_ema(prices, period=10)

        assert isinstance(result, list)
        assert len(result) > 0

    def test_ema_insufficient_data(self):
        """Test EMA with insufficient data returns prices."""
        prices = [10.0, 20.0]
        result = calculate_ema(prices, period=10)

        assert result == prices

    def test_ema_length(self):
        """Test EMA returns correct length."""
        prices = [i * 1.0 for i in range(50)]
        result = calculate_ema(prices, period=10)

        # First period is SMA, then EMA for remaining
        assert len(result) == len(prices) - 10 + 1

    def test_ema_follows_trend(self):
        """Test EMA follows uptrend."""
        prices = create_uptrend_prices(50)
        result = calculate_ema(prices, period=10)

        # EMA should be increasing in uptrend
        assert result[-1] > result[0]


# =============================================================================
# CALCULATE ADX TESTS
# =============================================================================

class TestCalculateADX:
    """Tests for calculate_adx function."""

    def test_adx_basic(self):
        """Test basic ADX calculation."""
        highs, lows, closes = create_ohlc_data(100)
        result = calculate_adx(highs, lows, closes, period=14)

        assert result is not None
        assert 0 <= result <= 100

    def test_adx_insufficient_data(self):
        """Test ADX with insufficient data returns None."""
        highs = [100.0, 101.0, 102.0]
        lows = [99.0, 100.0, 101.0]
        closes = [99.5, 100.5, 101.5]

        result = calculate_adx(highs, lows, closes, period=14)

        assert result is None

    def test_adx_strong_trend(self):
        """Test ADX for strong trending market."""
        # Strong uptrend
        n = 100
        closes = [100.0 + i * 2.0 for i in range(n)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 0.5 for c in closes]

        result = calculate_adx(highs, lows, closes, period=14)

        # Strong trend should have higher ADX
        assert result is not None
        assert result > 0

    def test_adx_custom_period(self):
        """Test ADX with custom period."""
        highs, lows, closes = create_ohlc_data(100)

        result_14 = calculate_adx(highs, lows, closes, period=14)
        result_7 = calculate_adx(highs, lows, closes, period=7)

        # Both should return valid results
        assert result_14 is not None
        assert result_7 is not None


# =============================================================================
# GET TREND DIRECTION TESTS
# =============================================================================

class TestGetTrendDirection:
    """Tests for get_trend_direction function."""

    def test_uptrend(self):
        """Test uptrend detection."""
        result = get_trend_direction(
            price=110.0,
            sma_short=105.0,
            sma_long=100.0
        )
        assert result == 'uptrend'

    def test_downtrend(self):
        """Test downtrend detection."""
        result = get_trend_direction(
            price=90.0,
            sma_short=95.0,
            sma_long=100.0
        )
        assert result == 'downtrend'

    def test_sideways_above_long(self):
        """Test sideways when above long but below short."""
        result = get_trend_direction(
            price=102.0,
            sma_short=105.0,
            sma_long=100.0
        )
        assert result == 'sideways'

    def test_sideways_below_long(self):
        """Test sideways when below long but above short."""
        result = get_trend_direction(
            price=98.0,
            sma_short=95.0,
            sma_long=100.0
        )
        assert result == 'sideways'

    def test_at_exact_short_ma(self):
        """Test when price equals short MA."""
        result = get_trend_direction(
            price=100.0,
            sma_short=100.0,  # Equal
            sma_long=95.0
        )
        # Not above short, so sideways
        assert result == 'sideways'


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestTrendIndicatorsIntegration:
    """Integration tests for trend indicators."""

    def test_sma_in_trend_detection(self):
        """Test SMA used in trend direction."""
        prices = create_uptrend_prices(100)

        sma_20 = calculate_sma(prices, 20)
        sma_50 = calculate_sma(prices, 50)
        current_price = prices[-1]

        direction = get_trend_direction(current_price, sma_20, sma_50)

        # Uptrend prices should show uptrend
        assert direction == 'uptrend'

    def test_downtrend_sma_detection(self):
        """Test downtrend detection with SMA."""
        prices = create_downtrend_prices(100)

        sma_20 = calculate_sma(prices, 20)
        sma_50 = calculate_sma(prices, 50)
        current_price = prices[-1]

        direction = get_trend_direction(current_price, sma_20, sma_50)

        # Downtrend prices should show downtrend
        assert direction == 'downtrend'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
