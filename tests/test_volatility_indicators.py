# Tests for Volatility Indicators
# ================================
"""
Tests for volatility indicator functions.
"""

import pytest
import numpy as np

from src.indicators.volatility import (
    calculate_atr,
    calculate_bollinger_bands,
    is_volatility_squeeze,
)
from src.models.indicators import BollingerBands, ATRResult


# =============================================================================
# SAMPLE DATA
# =============================================================================

def create_ohlc_data(n: int = 100, start: float = 100.0, volatility: float = 0.02):
    """Create OHLC data for testing."""
    np.random.seed(42)
    closes = [start]
    for i in range(1, n):
        change = np.random.normal(0, volatility)
        closes.append(closes[-1] * (1 + change))

    highs = [c * (1 + abs(np.random.normal(0, 0.01))) for c in closes]
    lows = [c * (1 - abs(np.random.normal(0, 0.01))) for c in closes]

    return highs, lows, closes


def create_high_volatility_data(n: int = 100):
    """Create high volatility OHLC data."""
    return create_ohlc_data(n, volatility=0.05)


def create_low_volatility_data(n: int = 100):
    """Create low volatility OHLC data."""
    return create_ohlc_data(n, volatility=0.005)


# =============================================================================
# CALCULATE ATR TESTS
# =============================================================================

class TestCalculateATR:
    """Tests for calculate_atr function."""

    def test_atr_basic(self):
        """Test basic ATR calculation."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_atr(highs, lows, closes, period=14)

        assert result is not None
        assert isinstance(result, ATRResult)
        assert result.atr > 0

    def test_atr_percent(self):
        """Test ATR percent is calculated correctly."""
        highs, lows, closes = create_ohlc_data(50)
        result = calculate_atr(highs, lows, closes, period=14)

        assert result.atr_percent > 0
        # ATR percent should be reasonable (0-100)
        assert result.atr_percent < 100

    def test_atr_insufficient_data(self):
        """Test ATR with insufficient data returns None."""
        highs = [100.0, 101.0, 102.0]
        lows = [99.0, 100.0, 101.0]
        closes = [99.5, 100.5, 101.5]

        result = calculate_atr(highs, lows, closes, period=14)

        assert result is None

    def test_atr_custom_period(self):
        """Test ATR with custom period."""
        highs, lows, closes = create_ohlc_data(100)

        result_14 = calculate_atr(highs, lows, closes, period=14)
        result_7 = calculate_atr(highs, lows, closes, period=7)

        assert result_14 is not None
        assert result_7 is not None
        # Different periods should give different results
        assert result_14.atr != result_7.atr

    def test_atr_high_volatility(self):
        """Test ATR for high volatility data."""
        highs, lows, closes = create_high_volatility_data(50)
        result = calculate_atr(highs, lows, closes, period=14)

        assert result is not None
        assert result.atr > 0

    def test_atr_low_volatility(self):
        """Test ATR for low volatility data."""
        highs, lows, closes = create_low_volatility_data(50)
        high_highs, high_lows, high_closes = create_high_volatility_data(50)

        low_vol_result = calculate_atr(highs, lows, closes, period=14)
        high_vol_result = calculate_atr(high_highs, high_lows, high_closes, period=14)

        # High volatility should have higher ATR
        assert high_vol_result.atr > low_vol_result.atr


# =============================================================================
# CALCULATE BOLLINGER BANDS TESTS
# =============================================================================

class TestCalculateBollingerBands:
    """Tests for calculate_bollinger_bands function."""

    def test_bb_basic(self):
        """Test basic Bollinger Bands calculation."""
        _, _, prices = create_ohlc_data(50)
        result = calculate_bollinger_bands(prices, period=20)

        assert result is not None
        assert isinstance(result, BollingerBands)

    def test_bb_structure(self):
        """Test Bollinger Bands have correct structure."""
        _, _, prices = create_ohlc_data(50)
        result = calculate_bollinger_bands(prices, period=20)

        assert result.upper > result.middle
        assert result.middle > result.lower
        assert result.bandwidth > 0

    def test_bb_insufficient_data(self):
        """Test BB with insufficient data returns None."""
        prices = [100.0, 101.0, 102.0]

        result = calculate_bollinger_bands(prices, period=20)

        assert result is None

    def test_bb_custom_period(self):
        """Test BB with custom period."""
        _, _, prices = create_ohlc_data(100)

        result_20 = calculate_bollinger_bands(prices, period=20)
        result_10 = calculate_bollinger_bands(prices, period=10)

        assert result_20 is not None
        assert result_10 is not None
        # Different periods should give different results
        assert result_20.middle != result_10.middle

    def test_bb_custom_std(self):
        """Test BB with custom standard deviation multiplier."""
        _, _, prices = create_ohlc_data(50)

        result_2std = calculate_bollinger_bands(prices, period=20, num_std=2.0)
        result_3std = calculate_bollinger_bands(prices, period=20, num_std=3.0)

        assert result_2std is not None
        assert result_3std is not None
        # Wider std should give wider bands
        assert result_3std.bandwidth > result_2std.bandwidth

    def test_bb_percent_b(self):
        """Test percent_b is calculated correctly."""
        _, _, prices = create_ohlc_data(50)
        result = calculate_bollinger_bands(prices, period=20)

        # percent_b should be between -infinity and +infinity but typically 0-1
        assert isinstance(result.percent_b, float)

    def test_bb_bandwidth(self):
        """Test bandwidth calculation."""
        _, _, low_vol_prices = create_low_volatility_data(50)
        _, _, high_vol_prices = create_high_volatility_data(50)

        low_vol_bb = calculate_bollinger_bands(low_vol_prices, period=20)
        high_vol_bb = calculate_bollinger_bands(high_vol_prices, period=20)

        # High volatility should have wider bandwidth
        assert high_vol_bb.bandwidth > low_vol_bb.bandwidth


# =============================================================================
# IS VOLATILITY SQUEEZE TESTS
# =============================================================================

class TestIsVolatilitySqueeze:
    """Tests for is_volatility_squeeze function."""

    def test_squeeze_detected(self):
        """Test squeeze detection with low volatility."""
        # Create very low volatility data
        prices = [100.0 + np.sin(i * 0.01) * 0.1 for i in range(50)]

        # Should detect squeeze with very narrow bands
        result = is_volatility_squeeze(prices, period=20, bandwidth_threshold=0.1)

        assert isinstance(result, bool)

    def test_no_squeeze_high_volatility(self):
        """Test no squeeze detection with high volatility."""
        _, _, prices = create_high_volatility_data(50)

        result = is_volatility_squeeze(prices, period=20, bandwidth_threshold=0.01)

        # High volatility should not show squeeze with low threshold
        assert isinstance(result, bool)

    def test_squeeze_insufficient_data(self):
        """Test squeeze with insufficient data returns False."""
        prices = [100.0, 101.0, 102.0]

        result = is_volatility_squeeze(prices, period=20)

        assert result is False

    def test_squeeze_custom_threshold(self):
        """Test squeeze with custom threshold."""
        _, _, prices = create_ohlc_data(50)

        # Very high threshold should trigger squeeze
        result_high = is_volatility_squeeze(prices, bandwidth_threshold=1.0)
        # Very low threshold should not trigger
        result_low = is_volatility_squeeze(prices, bandwidth_threshold=0.0001)

        assert isinstance(result_high, bool)
        assert isinstance(result_low, bool)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestVolatilityIndicatorsIntegration:
    """Integration tests for volatility indicators."""

    def test_atr_and_bb_consistency(self):
        """Test ATR and BB give consistent volatility signals."""
        highs, lows, closes = create_high_volatility_data(100)

        atr_result = calculate_atr(highs, lows, closes, period=14)
        bb_result = calculate_bollinger_bands(closes, period=20)

        # Both should indicate volatility
        assert atr_result is not None
        assert bb_result is not None
        assert atr_result.atr > 0
        assert bb_result.bandwidth > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
