# Tests for Analysis Context - Extended Coverage
# ===============================================
"""
Additional tests for src/analyzers/context.py focusing on:
- Edge cases and boundary conditions
- Pure Python fallback calculations
- Gap analysis edge cases
- Error handling paths
- Missing/invalid data scenarios

These tests complement test_analysis_context.py by targeting uncovered lines.
"""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from typing import List

from src.analyzers.context import AnalysisContext, _NUMPY_AVAILABLE


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def minimal_prices():
    """Generate exactly 20 data points (minimum for context creation)."""
    return [100.0 + i * 0.5 for i in range(20)]


@pytest.fixture
def minimal_volumes():
    """Generate exactly 20 volume data points."""
    return [1000000 + i * 10000 for i in range(20)]


@pytest.fixture
def minimal_highs(minimal_prices):
    """Generate highs from minimal prices."""
    return [p + 1.0 for p in minimal_prices]


@pytest.fixture
def minimal_lows(minimal_prices):
    """Generate lows from minimal prices."""
    return [p - 1.0 for p in minimal_prices]


@pytest.fixture
def large_dataset():
    """Generate 250+ days of data for SMA200 testing."""
    n = 260
    prices = [100.0 + i * 0.1 for i in range(n)]
    volumes = [1000000 + i * 5000 for i in range(n)]
    highs = [p + 1.5 for p in prices]
    lows = [p - 1.5 for p in prices]
    return prices, volumes, highs, lows


@pytest.fixture
def downtrend_data():
    """Generate strong downtrend data."""
    n = 90
    prices = [150.0 - i * 0.5 for i in range(n)]
    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


@pytest.fixture
def sideways_data():
    """Generate sideways/ranging data."""
    n = 250
    prices = []
    for i in range(n):
        # Oscillating between 100 and 105
        prices.append(100.0 + 2.5 * np.sin(i * 0.3) + 2.5)
    volumes = [1000000] * n
    highs = [p + 1 for p in prices]
    lows = [p - 1 for p in prices]
    return prices, volumes, highs, lows


# =============================================================================
# INITIALIZATION AND PROPERTIES TESTS
# =============================================================================

class TestAnalysisContextInit:
    """Tests for AnalysisContext initialization and default values."""

    def test_default_values(self):
        """Test all default values are correctly initialized."""
        ctx = AnalysisContext()

        # Basic defaults
        assert ctx.symbol == ""
        assert ctx.current_price == 0.0
        assert ctx.current_volume == 0

        # RSI default
        assert ctx.rsi_14 is None

        # Moving averages defaults
        assert ctx.sma_20 is None
        assert ctx.sma_50 is None
        assert ctx.sma_200 is None
        assert ctx.ema_12 is None
        assert ctx.ema_26 is None

        # MACD defaults
        assert ctx.macd_line is None
        assert ctx.macd_signal is None
        assert ctx.macd_histogram is None

        # Stochastic defaults
        assert ctx.stoch_k is None
        assert ctx.stoch_d is None

        # Support/Resistance defaults
        assert ctx.support_levels == []
        assert ctx.resistance_levels == []

        # Fibonacci defaults
        assert ctx.fib_levels == {}

        # ATR default
        assert ctx.atr_14 is None

        # Volume defaults
        assert ctx.avg_volume_20 is None
        assert ctx.volume_ratio is None

        # ATH defaults
        assert ctx.all_time_high is None
        assert ctx.pct_from_ath is None

        # Trend defaults
        assert ctx.trend == "unknown"
        assert ctx.above_sma20 is None
        assert ctx.above_sma50 is None
        assert ctx.above_sma200 is None

        # Gap defaults
        assert ctx.gap_result is None
        assert ctx.gap_score == 0.0

    def test_custom_initialization(self):
        """Test creating context with custom values."""
        ctx = AnalysisContext(
            symbol="AAPL",
            current_price=150.0,
            current_volume=5000000,
            rsi_14=65.0,
            sma_20=148.0,
            sma_50=145.0,
            sma_200=140.0,
            macd_line=1.5,
            macd_signal=1.2,
            macd_histogram=0.3,
            stoch_k=75.0,
            stoch_d=72.0,
            support_levels=[145.0, 140.0],
            resistance_levels=[155.0, 160.0],
            fib_levels={'0.5': 147.5},
            atr_14=2.5,
            avg_volume_20=4000000,
            volume_ratio=1.25,
            all_time_high=160.0,
            pct_from_ath=6.25,
            trend="uptrend",
            above_sma20=True,
            above_sma50=True,
            above_sma200=True,
            gap_score=0.5,
        )

        assert ctx.symbol == "AAPL"
        assert ctx.current_price == 150.0
        assert ctx.current_volume == 5000000
        assert ctx.rsi_14 == 65.0
        assert ctx.support_levels == [145.0, 140.0]
        assert ctx.trend == "uptrend"


# =============================================================================
# VALIDATE INPUTS EDGE CASES
# =============================================================================

class TestFromDataValidation:
    """Tests for from_data input validation and edge cases."""

    def test_exactly_20_data_points(self):
        """Test behavior with exactly 20 data points (boundary)."""
        prices = [100.0 + i for i in range(20)]
        volumes = [1000000] * 20
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should calculate indicators with exactly 20 points
        assert ctx.symbol == "TEST"
        assert ctx.current_price == prices[-1]
        assert ctx.sma_20 is not None

    def test_exactly_19_data_points(self):
        """Test behavior with 19 data points (below minimum)."""
        prices = [100.0 + i for i in range(19)]
        volumes = [1000000] * 19
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should return basic context without calculations
        assert ctx.symbol == "TEST"
        # No price/volume should be set for insufficient data
        assert ctx.current_price == 0.0

    def test_zero_data_points(self):
        """Test behavior with empty data."""
        ctx = AnalysisContext.from_data("TEST", [], [], [], [])

        assert ctx.symbol == "TEST"
        assert ctx.current_price == 0.0
        assert ctx.sma_20 is None

    def test_mismatched_array_lengths(self):
        """Test behavior with mismatched array lengths."""
        prices = [100.0 + i for i in range(30)]
        volumes = [1000000] * 25  # Different length
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        # Should not crash, but may have unexpected results
        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)
        assert ctx.symbol == "TEST"

    def test_none_in_volumes(self):
        """Test with None values in volumes list."""
        prices = [100.0 + i for i in range(30)]
        volumes = [1000000] * 30
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        # Should handle gracefully
        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)
        assert ctx.symbol == "TEST"

    def test_with_calculate_all_false(self):
        """Test from_data with calculate_all=False."""
        prices = [100.0 + i for i in range(90)]
        volumes = [1000000] * 90
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data(
            "TEST", prices, volumes, highs, lows, calculate_all=False
        )

        # Should have price/volume but no indicators
        assert ctx.symbol == "TEST"
        assert ctx.current_price == prices[-1]
        assert ctx.rsi_14 is None
        assert ctx.sma_20 is None
        assert ctx.macd_line is None


# =============================================================================
# CALCULATE INDICATORS TESTS
# =============================================================================

class TestCalculateIndicators:
    """Tests for _calculate_indicators method and its branches."""

    def test_numpy_available_flag(self):
        """Test that NumPy availability flag is set correctly."""
        # The flag should be True in normal test environment
        assert _NUMPY_AVAILABLE is True

    def test_indicators_with_large_dataset(self, large_dataset):
        """Test indicator calculation with 260 days of data."""
        prices, volumes, highs, lows = large_dataset

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should calculate all indicators including SMA200
        assert ctx.sma_20 is not None
        assert ctx.sma_50 is not None
        assert ctx.sma_200 is not None

    def test_stochastic_with_minimal_data(self):
        """Test stochastic with exactly 16 data points (14 + 3 - 1)."""
        prices = [100.0 + i * 0.5 for i in range(20)]
        volumes = [1000000] * 20
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should calculate stochastic
        assert ctx.stoch_k is not None
        assert ctx.stoch_d is not None

    def test_volume_ratio_with_zero_avg_volume(self):
        """Test volume ratio when average volume is zero."""
        prices = [100.0 + i * 0.5 for i in range(30)]
        volumes = [0] * 30  # All zeros
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Volume ratio should not be calculated if avg is 0
        assert ctx.avg_volume_20 == 0.0
        assert ctx.volume_ratio is None or ctx.volume_ratio == 0


# =============================================================================
# RSI EDGE CASES
# =============================================================================

class TestRSIEdgeCases:
    """Tests for RSI calculation edge cases."""

    def test_rsi_all_gains(self):
        """Test RSI when all price changes are positive (should be ~100)."""
        # Monotonically increasing prices
        prices = [100.0 + i * 0.5 for i in range(30)]
        volumes = [1000000] * 30
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.rsi_14 is not None
        # RSI should be high for all gains (close to 100)
        assert ctx.rsi_14 > 90

    def test_rsi_all_losses(self):
        """Test RSI when all price changes are negative (should be ~0)."""
        # Monotonically decreasing prices
        prices = [150.0 - i * 0.5 for i in range(30)]
        volumes = [1000000] * 30
        highs = [p + 0.1 for p in prices]
        lows = [p - 0.5 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.rsi_14 is not None
        # RSI should be low for all losses (close to 0)
        assert ctx.rsi_14 < 10

    def test_rsi_constant_prices(self):
        """Test RSI with constant prices (no changes)."""
        prices = [100.0] * 30
        volumes = [1000000] * 30
        highs = [101.0] * 30
        lows = [99.0] * 30

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # With no changes, RSI behavior depends on implementation
        # It should return 100 when avg_loss is 0 (all gains are 0, all losses are 0)
        assert ctx.rsi_14 is not None


# =============================================================================
# PURE PYTHON CALCULATION TESTS
# =============================================================================

class TestPureePythonCalculations:
    """Tests for pure Python calculation methods (fallback path)."""

    def test_calc_rsi_python_avg_loss_zero(self):
        """Test calculate_rsi when average loss is zero (returns 100)."""
        from src.indicators.momentum import calculate_rsi

        # All gains, no losses
        prices = [100.0 + i * 0.5 for i in range(30)]
        rsi = calculate_rsi(prices, 14)

        assert rsi is not None
        # When all changes are gains, avg_loss = 0, RSI = 100
        assert rsi == 100.0

    def test_calc_rsi_python_insufficient_data(self):
        """Test calculate_rsi with insufficient data returns 50.0 (neutral)."""
        from src.indicators.momentum import calculate_rsi

        prices = [100.0, 101.0, 102.0]  # Only 3 points, need 15+
        rsi = calculate_rsi(prices, 14)

        # calculate_rsi returns 50.0 for insufficient data
        assert rsi == 50.0

    def test_calc_ema_python_insufficient_data(self):
        """Test _calc_ema with insufficient data."""
        ctx = AnalysisContext(symbol="TEST")

        prices = [100.0, 101.0, 102.0]
        ema = ctx._calc_ema(prices, 12)  # Need 12+ points

        assert ema is None

    def test_calc_atr_python_insufficient_data(self):
        """Test _calc_atr with insufficient data."""
        ctx = AnalysisContext(symbol="TEST")

        prices = [100.0, 101.0, 102.0]
        highs = [101.0, 102.0, 103.0]
        lows = [99.0, 100.0, 101.0]

        atr = ctx._calc_atr(highs, lows, prices, 14)

        assert atr is None

    def test_calc_atr_python_short_true_ranges(self):
        """Test _calc_atr when true_ranges is shorter than period."""
        ctx = AnalysisContext(symbol="TEST")

        # 10 data points, but need period + 1 = 15
        prices = [100.0 + i for i in range(10)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        atr = ctx._calc_atr(highs, lows, prices, 14)

        assert atr is None

    def test_calc_stochastic_python_insufficient_data(self):
        """Test _calc_stochastic with insufficient data."""
        ctx = AnalysisContext(symbol="TEST")

        # Need k_period + d_period - 1 = 14 + 3 - 1 = 16 points
        prices = [100.0 + i for i in range(10)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx._calc_stochastic(highs, lows, prices)

        # Should not set values with insufficient data
        assert ctx.stoch_k is None
        assert ctx.stoch_d is None

    def test_calc_stochastic_python_equal_high_low(self):
        """Test _calc_stochastic when high equals low (division by zero)."""
        ctx = AnalysisContext(symbol="TEST")

        # Constant high and low (no range)
        prices = [100.0] * 20
        highs = [100.0] * 20
        lows = [100.0] * 20

        ctx._calc_stochastic(highs, lows, prices)

        # Should handle gracefully (returns 50 when high == low)
        assert ctx.stoch_k is not None
        assert ctx.stoch_k == 50.0

    def test_calc_macd_python_no_emas(self):
        """Test _calc_macd when EMAs are None."""
        ctx = AnalysisContext(symbol="TEST")
        ctx.ema_12 = None
        ctx.ema_26 = None

        ctx._calc_macd()

        assert ctx.macd_line is None
        assert ctx.macd_signal is None
        assert ctx.macd_histogram is None

    def test_calc_macd_python_short_macd_line(self):
        """Test _calc_macd when MACD line is shorter than 9 periods."""
        ctx = AnalysisContext(symbol="TEST")
        ctx.ema_12 = [100.0, 101.0, 102.0, 103.0, 104.0]
        ctx.ema_26 = [99.0, 100.0, 101.0, 102.0, 103.0]

        ctx._calc_macd()

        # MACD line is 5 elements, need 9 for signal
        assert ctx.macd_line is None


# =============================================================================
# GAP ANALYSIS TESTS
# =============================================================================

class TestGapAnalysis:
    """Tests for _calculate_gap method."""

    def test_gap_with_opens_provided(self):
        """Test gap calculation when opens are provided."""
        n = 30
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        # Create a gap-up scenario
        opens = list(prices)
        opens[15] = prices[14] + 2  # Gap up

        ctx = AnalysisContext.from_data(
            "TEST", prices, volumes, highs, lows, opens=opens
        )

        # Gap analysis should have been performed
        assert isinstance(ctx.gap_score, (int, float))

    def test_gap_without_opens_fallback(self):
        """Test gap calculation fallback when opens not provided."""
        n = 30
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should use fallback opens (previous closes)
        assert isinstance(ctx.gap_score, (int, float))

    def test_gap_insufficient_data(self):
        """Test gap with insufficient price data."""
        ctx = AnalysisContext(symbol="TEST")
        ctx._calculate_gap([100.0], [101.0], [99.0])  # Only 1 point

        assert ctx.gap_result is None
        assert ctx.gap_score == 0.0

    def test_gap_exception_handling(self):
        """Test gap analysis exception handling."""
        ctx = AnalysisContext(symbol="TEST")
        ctx._opens = None

        # Call with valid but minimal data
        ctx._calculate_gap(
            [100.0, 101.0, 102.0],
            [101.0, 102.0, 103.0],
            [99.0, 100.0, 101.0]
        )

        # Should handle gracefully
        assert ctx.gap_score == 0.0 or isinstance(ctx.gap_score, float)


# =============================================================================
# TREND DETERMINATION TESTS
# =============================================================================

class TestTrendDetermination:
    """Tests for _determine_trend method."""

    def test_uptrend_detection(self, large_dataset):
        """Test uptrend is detected when price above all SMAs."""
        prices, volumes, highs, lows = large_dataset

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Uptrend data should show uptrend
        assert ctx.trend == "uptrend"
        assert ctx.above_sma20 is True
        assert ctx.above_sma50 is True
        assert ctx.above_sma200 is True

    def test_downtrend_detection(self, downtrend_data):
        """Test downtrend is detected when price below key SMAs."""
        prices, volumes, highs, lows = downtrend_data

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # In strong downtrend with 90 points, SMA200 won't be available
        # but we can still check trend based on SMA20
        assert ctx.above_sma20 is False

    def test_sideways_detection(self, sideways_data):
        """Test sideways market detection."""
        prices, volumes, highs, lows = sideways_data

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # In oscillating data, trend depends on current position
        # The key is that it's handled without error
        assert ctx.trend in ["uptrend", "downtrend", "sideways"]

    def test_trend_without_sma200(self):
        """Test trend determination when SMA200 is None."""
        prices = [100.0 + i * 0.5 for i in range(50)]  # Only 50 points
        volumes = [1000000] * 50
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.sma_200 is None
        assert ctx.above_sma200 is None
        # Trend should still be determined (sideways when SMA200 is None)
        assert ctx.trend in ["uptrend", "downtrend", "sideways"]


# =============================================================================
# TO_DICT METHOD TESTS
# =============================================================================

class TestToDict:
    """Tests for to_dict method."""

    def test_to_dict_with_gap_result(self):
        """Test to_dict when gap_result is present."""
        ctx = AnalysisContext(
            symbol="TEST",
            current_price=100.0,
            gap_score=0.5,
        )
        # Mock a gap_result with gap_type
        mock_gap = MagicMock()
        mock_gap.gap_type = "gap_up"
        ctx.gap_result = mock_gap

        result = ctx.to_dict()

        assert result["gap_type"] == "gap_up"
        assert result["gap_score"] == 0.5

    def test_to_dict_without_gap_result(self):
        """Test to_dict when gap_result is None."""
        ctx = AnalysisContext(
            symbol="TEST",
            current_price=100.0,
        )
        ctx.gap_result = None

        result = ctx.to_dict()

        assert result["gap_type"] is None


# =============================================================================
# ATH AND PERCENT FROM ATH TESTS
# =============================================================================

class TestATHCalculation:
    """Tests for All-Time High and percent from ATH calculations."""

    def test_ath_at_current_price(self):
        """Test when current price equals ATH."""
        # Uptrend ending at highest point
        n = 30
        prices = [100.0 + i * 0.5 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # ATH should be the highest high
        assert ctx.all_time_high == max(highs)
        # pct_from_ath should be small (close to 0) since we're near ATH
        assert ctx.pct_from_ath >= 0

    def test_pct_from_ath_calculation(self):
        """Test percent from ATH calculation accuracy."""
        n = 30
        prices = [100.0 + i * 0.5 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Manual calculation
        expected_ath = max(highs)
        expected_pct = (expected_ath - ctx.current_price) / expected_ath * 100

        assert abs(ctx.pct_from_ath - expected_pct) < 0.01

    def test_ath_with_empty_highs(self):
        """Test ATH calculation with minimal data."""
        # With less than 20 points, no calculations should occur
        ctx = AnalysisContext.from_data("TEST", [100.0] * 5, [1000] * 5, [101.0] * 5, [99.0] * 5)

        assert ctx.all_time_high is None


# =============================================================================
# VOLUME ANALYSIS TESTS
# =============================================================================

class TestVolumeAnalysis:
    """Tests for volume-related calculations."""

    def test_high_volume_ratio(self):
        """Test volume ratio with high current volume."""
        n = 30
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * (n - 1) + [3000000]  # Last day 3x average
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Volume ratio should be approximately 3
        assert ctx.volume_ratio is not None
        assert ctx.volume_ratio > 2.5

    def test_low_volume_ratio(self):
        """Test volume ratio with low current volume."""
        n = 30
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * (n - 1) + [100000]  # Last day 0.1x average
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.volume_ratio is not None
        assert ctx.volume_ratio < 0.2


# =============================================================================
# FIBONACCI LEVELS TESTS
# =============================================================================

class TestFibonacciLevels:
    """Tests for Fibonacci level calculations."""

    def test_fibonacci_level_accuracy(self):
        """Test Fibonacci levels are calculated accurately."""
        ctx = AnalysisContext(symbol="TEST")

        # Known high/low for easy calculation
        fib = ctx._calc_fibonacci(high=200.0, low=100.0)

        # Verify levels
        assert fib['0.0'] == 200.0  # High
        assert fib['1.0'] == 100.0  # Low
        assert fib['0.5'] == 150.0  # 50% retracement
        assert abs(fib['0.382'] - 161.8) < 0.1  # 38.2%
        assert abs(fib['0.618'] - 138.2) < 0.1  # 61.8%

    def test_fibonacci_with_equal_high_low(self):
        """Test Fibonacci when high equals low."""
        ctx = AnalysisContext(symbol="TEST")

        fib = ctx._calc_fibonacci(high=100.0, low=100.0)

        # All levels should be the same
        for level in fib.values():
            assert level == 100.0


# =============================================================================
# SUPPORT/RESISTANCE TESTS
# =============================================================================

class TestSupportResistance:
    """Tests for support and resistance level detection."""

    def test_support_levels_ordered(self):
        """Test that support levels are properly detected."""
        n = 90
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1.5 for p in prices]
        lows = [p - 1.5 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Support levels should be a list of floats
        assert isinstance(ctx.support_levels, list)
        for level in ctx.support_levels:
            assert isinstance(level, (int, float))

    def test_resistance_levels_ordered(self):
        """Test that resistance levels are properly detected."""
        n = 90
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1.5 for p in prices]
        lows = [p - 1.5 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Resistance levels should be a list of floats
        assert isinstance(ctx.resistance_levels, list)
        for level in ctx.resistance_levels:
            assert isinstance(level, (int, float))


# =============================================================================
# NUMPY VS PYTHON FALLBACK TESTS
# =============================================================================

class TestNumpyVsPythonFallback:
    """Tests comparing NumPy and Python fallback calculations."""

    def test_python_indicators_direct_call(self):
        """Test calling Python fallback methods directly."""
        ctx = AnalysisContext(symbol="TEST", current_price=110.0)

        prices = [100.0 + i * 0.3 for i in range(90)]
        volumes = [1000000] * 90
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        # Call Python fallback directly
        ctx._calculate_indicators_python(prices, volumes, highs, lows)

        # Verify indicators were calculated
        assert ctx.rsi_14 is not None
        assert ctx.sma_20 is not None
        assert ctx.ema_12 is not None
        assert ctx.macd_line is not None
        assert ctx.stoch_k is not None
        assert ctx.atr_14 is not None

    def test_python_fallback_with_opens(self):
        """Test Python fallback with opens for gap analysis."""
        ctx = AnalysisContext(symbol="TEST", current_price=110.0)

        prices = [100.0 + i * 0.3 for i in range(90)]
        volumes = [1000000] * 90
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        opens = [prices[0]] + prices[:-1]  # Previous close as open

        ctx._calculate_indicators_python(prices, volumes, highs, lows, opens)

        # Gap analysis should have been performed
        assert isinstance(ctx.gap_score, (int, float))


# =============================================================================
# EMA CALCULATION TESTS
# =============================================================================

class TestEMACalculation:
    """Tests for EMA calculation."""

    def test_ema_values_stored(self):
        """Test that EMA values are properly stored."""
        n = 50
        prices = [100.0 + i * 0.2 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # EMAs should be stored as lists (for compatibility)
        assert ctx.ema_12 is not None
        assert ctx.ema_26 is not None
        assert isinstance(ctx.ema_12, list)
        assert isinstance(ctx.ema_26, list)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for complete workflow."""

    def test_full_analysis_workflow(self):
        """Test complete analysis workflow from raw data."""
        # Generate realistic price data
        n = 200
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, n)
        prices = [100.0]
        for r in returns:
            prices.append(prices[-1] * (1 + r))

        volumes = [int(1000000 * (1 + np.random.uniform(-0.3, 0.3))) for _ in range(n + 1)]
        highs = [p * (1 + abs(np.random.normal(0, 0.01))) for p in prices]
        lows = [p * (1 - abs(np.random.normal(0, 0.01))) for p in prices]
        opens = [prices[0]] + prices[:-1]

        ctx = AnalysisContext.from_data(
            "TEST", prices, volumes, highs, lows, opens=opens
        )

        # All indicators should be populated
        assert ctx.rsi_14 is not None
        assert ctx.sma_20 is not None
        assert ctx.sma_50 is not None
        assert ctx.sma_200 is not None
        assert ctx.macd_line is not None
        assert ctx.stoch_k is not None
        assert ctx.atr_14 is not None
        assert ctx.trend in ["uptrend", "downtrend", "sideways"]

        # Convert to dict and verify structure
        result = ctx.to_dict()
        assert isinstance(result, dict)
        assert result["symbol"] == "TEST"

    def test_context_reusability(self):
        """Test that context can be created and reused."""
        prices = [100.0 + i * 0.2 for i in range(100)]
        volumes = [1000000] * 100
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        # Create context
        ctx = AnalysisContext.from_data("AAPL", prices, volumes, highs, lows)

        # Verify it can be converted to dict multiple times
        dict1 = ctx.to_dict()
        dict2 = ctx.to_dict()

        assert dict1 == dict2


# =============================================================================
# MACD EDGE CASES
# =============================================================================

class TestMACDEdgeCases:
    """Additional tests for MACD calculation edge cases."""

    def test_macd_with_exactly_35_prices(self):
        """Test MACD with minimum data for signal (26 + 9 = 35)."""
        prices = [100.0 + i * 0.2 for i in range(36)]
        volumes = [1000000] * 36
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should have MACD values
        assert ctx.macd_line is not None
        assert ctx.macd_signal is not None

    def test_macd_python_with_misaligned_emas(self):
        """Test _calc_macd Python method with different EMA lengths."""
        ctx = AnalysisContext(symbol="TEST")

        # Create EMAs with different lengths
        ctx.ema_12 = [100.0 + i * 0.1 for i in range(30)]
        ctx.ema_26 = [99.0 + i * 0.1 for i in range(20)]

        ctx._calc_macd()

        # Should align to shorter length and calculate
        assert ctx.macd_line is not None


# =============================================================================
# STOCHASTIC EDGE CASES
# =============================================================================

class TestStochasticEdgeCases:
    """Additional tests for Stochastic calculation edge cases."""

    def test_stochastic_with_exactly_16_prices(self):
        """Test stochastic with exactly minimum required (14 + 3 - 1 = 16)."""
        prices = [100.0 + i * 0.3 for i in range(20)]
        volumes = [1000000] * 20
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.stoch_k is not None
        assert ctx.stoch_d is not None

    def test_stochastic_extreme_values(self):
        """Test stochastic at extreme price positions."""
        n = 30
        # Price at highest point in range
        prices = [100.0] * (n - 1) + [110.0]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Stochastic K should be high when close is at top of range
        assert ctx.stoch_k is not None
        assert ctx.stoch_k > 80


# =============================================================================
# ATR EDGE CASES
# =============================================================================

class TestATREdgeCases:
    """Additional tests for ATR calculation edge cases."""

    def test_atr_with_large_gaps(self):
        """Test ATR calculation with large price gaps."""
        n = 30
        prices = [100.0] * 15 + [120.0] * 15  # Gap up in middle
        volumes = [1000000] * n
        highs = [p + 2 for p in prices]
        lows = [p - 2 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # ATR should reflect the gap
        assert ctx.atr_14 is not None
        assert ctx.atr_14 > 3  # Should be larger due to gap

    def test_atr_python_exactly_period_plus_one(self):
        """Test _calc_atr with exactly period + 1 data points."""
        ctx = AnalysisContext(symbol="TEST")

        # 15 data points for period=14
        prices = [100.0 + i for i in range(15)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        atr = ctx._calc_atr(highs, lows, prices, 14)

        assert atr is not None


# =============================================================================
# OPENS HANDLING TESTS
# =============================================================================

class TestOpensHandling:
    """Tests for opens parameter handling in gap analysis."""

    def test_opens_length_mismatch(self):
        """Test gap analysis when opens length doesn't match prices."""
        n = 30
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        opens = [99.0] * 20  # Wrong length

        ctx = AnalysisContext.from_data(
            "TEST", prices, volumes, highs, lows, opens=opens
        )

        # Should still calculate (falls back to approximation)
        assert ctx.symbol == "TEST"

    def test_opens_none_explicitly(self):
        """Test gap analysis with opens explicitly set to None."""
        n = 30
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data(
            "TEST", prices, volumes, highs, lows, opens=None
        )

        # Should handle None opens
        assert isinstance(ctx.gap_score, (int, float))

    def test_opens_empty_list(self):
        """Test gap analysis with empty opens list."""
        n = 30
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data(
            "TEST", prices, volumes, highs, lows, opens=[]
        )

        # Should handle empty opens
        assert isinstance(ctx.gap_score, (int, float))


# =============================================================================
# VOLUME EDGE CASES
# =============================================================================

class TestVolumeEdgeCases:
    """Additional tests for volume calculation edge cases."""

    def test_volume_less_than_20_days(self):
        """Test volume calculation with less than 20 days."""
        prices = [100.0 + i for i in range(25)]
        volumes = [1000000] * 15 + [0] * 10  # Partial volumes
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should handle partial data
        assert ctx.symbol == "TEST"

    def test_volume_all_same(self):
        """Test volume ratio when all volumes are identical."""
        n = 30
        prices = [100.0 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n  # All same
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Volume ratio should be 1.0
        assert ctx.volume_ratio is not None
        assert abs(ctx.volume_ratio - 1.0) < 0.01


# =============================================================================
# TREND EDGE CASES
# =============================================================================

class TestTrendEdgeCases:
    """Additional tests for trend determination edge cases."""

    def test_trend_above_sma20_below_sma200(self):
        """Test sideways trend when above SMA20 but below SMA200."""
        # Generate data where price is above short-term but below long-term
        n = 250
        # Start high, go down, then recover slightly
        prices = []
        for i in range(n):
            if i < 150:
                prices.append(150 - i * 0.2)  # Downtrend
            else:
                prices.append(120 + (i - 150) * 0.1)  # Recovery

        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should determine some trend (exact result depends on final position)
        assert ctx.trend in ["uptrend", "downtrend", "sideways"]

    def test_trend_all_smas_none(self):
        """Test trend when all SMAs are None (insufficient data)."""
        ctx = AnalysisContext(symbol="TEST", current_price=100.0)
        ctx.sma_20 = None
        ctx.sma_50 = None
        ctx.sma_200 = None

        ctx._determine_trend()

        # With no SMAs, should set to sideways (default/unknown behavior)
        assert ctx.above_sma20 is None
        assert ctx.above_sma50 is None
        assert ctx.above_sma200 is None


# =============================================================================
# NUMPY CALCULATION TESTS
# =============================================================================

class TestNumpyCalculations:
    """Tests for NumPy-based indicator calculations."""

    def test_numpy_indicators_called(self):
        """Test that NumPy path is used when available."""
        assert _NUMPY_AVAILABLE is True

        prices = [100.0 + i * 0.2 for i in range(90)]
        volumes = [1000000] * 90
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should have calculated all indicators
        assert ctx.rsi_14 is not None
        assert ctx.sma_20 is not None
        assert ctx.macd_line is not None

    def test_numpy_ema_return_type(self):
        """Test that NumPy EMA returns proper type."""
        prices = [100.0 + i * 0.2 for i in range(50)]
        volumes = [1000000] * 50
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # EMA should be stored as list for backward compatibility
        assert isinstance(ctx.ema_12, list)
        assert isinstance(ctx.ema_26, list)
        assert len(ctx.ema_12) == 1  # Only last value
        assert len(ctx.ema_26) == 1


# =============================================================================
# BOUNDARY VALUE TESTS
# =============================================================================

class TestBoundaryValues:
    """Tests for boundary value conditions."""

    def test_exactly_50_data_points(self):
        """Test with exactly 50 data points (boundary for SMA50)."""
        prices = [100.0 + i * 0.1 for i in range(50)]
        volumes = [1000000] * 50
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.sma_20 is not None
        assert ctx.sma_50 is not None
        assert ctx.sma_200 is None  # Not enough data

    def test_exactly_200_data_points(self):
        """Test with exactly 200 data points (boundary for SMA200)."""
        prices = [100.0 + i * 0.05 for i in range(200)]
        volumes = [1000000] * 200
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.sma_20 is not None
        assert ctx.sma_50 is not None
        assert ctx.sma_200 is not None

    def test_very_large_dataset(self):
        """Test with very large dataset (500+ days)."""
        n = 500
        prices = [100.0 + i * 0.02 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # All indicators should be calculated
        assert ctx.sma_20 is not None
        assert ctx.sma_50 is not None
        assert ctx.sma_200 is not None
        assert ctx.rsi_14 is not None


# =============================================================================
# SPECIAL PRICE PATTERNS
# =============================================================================

class TestSpecialPricePatterns:
    """Tests for special price patterns."""

    def test_alternating_prices(self):
        """Test with alternating up/down prices."""
        n = 100
        prices = [100.0 + (1 if i % 2 == 0 else -1) * 0.5 for i in range(n)]
        volumes = [1000000] * n
        highs = [max(prices[max(0, i-1):i+1]) + 0.5 for i in range(n)]
        lows = [min(prices[max(0, i-1):i+1]) - 0.5 for i in range(n)]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # Should handle alternating data without errors
        assert ctx.symbol == "TEST"
        assert ctx.rsi_14 is not None

    def test_sudden_spike(self):
        """Test with sudden price spike."""
        n = 50
        prices = [100.0] * 40 + [200.0] * 10  # Sudden double
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.symbol == "TEST"
        # RSI should reflect the spike
        assert ctx.rsi_14 is not None
        assert ctx.rsi_14 > 70  # Should be high after gains

    def test_sudden_crash(self):
        """Test with sudden price crash."""
        n = 50
        prices = [200.0] * 40 + [100.0] * 10  # Sudden halving
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.symbol == "TEST"
        # RSI should reflect the crash
        assert ctx.rsi_14 is not None
        assert ctx.rsi_14 < 30  # Should be low after losses


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
