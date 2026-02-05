# Tests for Analysis Context
# ===========================
"""
Tests for analyzers/context.py module including:
- AnalysisContext dataclass
- from_data factory method
- Indicator calculations (RSI, SMA, EMA, MACD, Stochastic, ATR)
- Support/Resistance levels
- Fibonacci levels
- Gap analysis
- Trend determination
- to_dict method
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch

from src.analyzers.context import AnalysisContext


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_prices():
    """Generate 90 days of simulated price data."""
    base = 100.0
    # Create trending price data
    prices = []
    for i in range(90):
        trend = i * 0.1  # Upward trend
        noise = (i % 7 - 3) * 0.2  # Some noise
        prices.append(base + trend + noise)
    return prices


@pytest.fixture
def sample_volumes():
    """Generate 90 days of volume data."""
    return [1000000 + i * 10000 for i in range(90)]


@pytest.fixture
def sample_highs(sample_prices):
    """Generate highs from prices."""
    return [p + 1.5 for p in sample_prices]


@pytest.fixture
def sample_lows(sample_prices):
    """Generate lows from prices."""
    return [p - 1.5 for p in sample_prices]


@pytest.fixture
def sample_opens(sample_prices):
    """Generate opens from prices."""
    return [sample_prices[0]] + sample_prices[:-1]


# =============================================================================
# BASIC CREATION TESTS
# =============================================================================

class TestAnalysisContextCreation:
    """Tests for AnalysisContext creation."""

    def test_create_empty_context(self):
        """Test creating an empty context."""
        ctx = AnalysisContext()

        assert ctx.symbol == ""
        assert ctx.current_price == 0.0
        assert ctx.rsi_14 is None
        assert ctx.support_levels == []
        assert ctx.resistance_levels == []
        assert ctx.fib_levels == {}
        assert ctx.trend == "unknown"

    def test_create_with_symbol(self):
        """Test creating context with symbol."""
        ctx = AnalysisContext(symbol="AAPL")

        assert ctx.symbol == "AAPL"

    def test_create_with_values(self):
        """Test creating context with values."""
        ctx = AnalysisContext(
            symbol="AAPL",
            current_price=150.0,
            rsi_14=55.0,
            sma_20=148.0,
            trend="uptrend",
        )

        assert ctx.current_price == 150.0
        assert ctx.rsi_14 == 55.0
        assert ctx.sma_20 == 148.0
        assert ctx.trend == "uptrend"


# =============================================================================
# FROM DATA FACTORY TESTS
# =============================================================================

class TestFromData:
    """Tests for from_data factory method."""

    def test_from_data_basic(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test basic from_data creation."""
        ctx = AnalysisContext.from_data(
            symbol="AAPL",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.symbol == "AAPL"
        assert ctx.current_price == sample_prices[-1]
        assert ctx.current_volume == sample_volumes[-1]

    def test_from_data_insufficient_data(self):
        """Test from_data with insufficient data."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=[100.0] * 10,  # Only 10 data points
            volumes=[1000] * 10,
            highs=[101.0] * 10,
            lows=[99.0] * 10,
        )

        # Should return basic context without calculations
        assert ctx.symbol == "TEST"
        # Indicators should be None due to insufficient data
        assert ctx.sma_50 is None

    def test_from_data_without_calculation(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test from_data without calculating indicators."""
        ctx = AnalysisContext.from_data(
            symbol="AAPL",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
            calculate_all=False,
        )

        assert ctx.symbol == "AAPL"
        assert ctx.current_price == sample_prices[-1]
        # Indicators should not be calculated
        assert ctx.rsi_14 is None
        assert ctx.sma_20 is None

    def test_from_data_with_opens(self, sample_prices, sample_volumes, sample_highs, sample_lows, sample_opens):
        """Test from_data with open prices."""
        ctx = AnalysisContext.from_data(
            symbol="AAPL",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
            opens=sample_opens,
        )

        assert ctx.symbol == "AAPL"
        # Gap analysis should have been performed
        # (gap_score will be 0.0 if no significant gap)


# =============================================================================
# RSI CALCULATION TESTS
# =============================================================================

class TestRSICalculation:
    """Tests for RSI calculation."""

    def test_rsi_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test that RSI is calculated."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.rsi_14 is not None
        assert 0 <= ctx.rsi_14 <= 100

    def test_rsi_in_uptrend(self):
        """Test RSI in uptrend is elevated."""
        # Strong uptrend prices
        prices = [100.0 + i * 0.5 for i in range(90)]
        volumes = [1000000] * 90
        highs = [p + 1 for p in prices]
        lows = [p - 0.5 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # In strong uptrend, RSI should be elevated
        assert ctx.rsi_14 is not None
        assert ctx.rsi_14 > 50


# =============================================================================
# MOVING AVERAGE TESTS
# =============================================================================

class TestMovingAverages:
    """Tests for moving average calculations."""

    def test_sma_20_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test SMA 20 calculation."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.sma_20 is not None
        # SMA should be close to average of last 20 prices
        expected = sum(sample_prices[-20:]) / 20
        assert abs(ctx.sma_20 - expected) < 0.01

    def test_sma_50_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test SMA 50 calculation."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.sma_50 is not None

    def test_sma_200_requires_more_data(self):
        """Test SMA 200 requires 200+ data points."""
        # Only 100 data points
        prices = [100.0 + i * 0.1 for i in range(100)]
        volumes = [1000000] * 100
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.sma_200 is None

    def test_ema_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test EMA calculation."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.ema_12 is not None
        assert ctx.ema_26 is not None


# =============================================================================
# MACD TESTS
# =============================================================================

class TestMACD:
    """Tests for MACD calculation."""

    def test_macd_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test MACD calculation."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.macd_line is not None
        assert ctx.macd_signal is not None
        assert ctx.macd_histogram is not None

    def test_macd_histogram_relationship(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test MACD histogram = macd_line - signal."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        if ctx.macd_line and ctx.macd_signal and ctx.macd_histogram:
            expected = ctx.macd_line - ctx.macd_signal
            assert abs(ctx.macd_histogram - expected) < 0.01


# =============================================================================
# STOCHASTIC TESTS
# =============================================================================

class TestStochastic:
    """Tests for Stochastic calculation."""

    def test_stochastic_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test Stochastic calculation."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.stoch_k is not None
        assert ctx.stoch_d is not None

    def test_stochastic_range(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test Stochastic is in 0-100 range."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        if ctx.stoch_k is not None:
            assert 0 <= ctx.stoch_k <= 100
        if ctx.stoch_d is not None:
            assert 0 <= ctx.stoch_d <= 100


# =============================================================================
# SUPPORT/RESISTANCE TESTS
# =============================================================================

class TestSupportResistance:
    """Tests for Support/Resistance calculation."""

    def test_support_levels_found(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test support levels are found."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        # Support levels should be a list
        assert isinstance(ctx.support_levels, list)

    def test_resistance_levels_found(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test resistance levels are found."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        # Resistance levels should be a list
        assert isinstance(ctx.resistance_levels, list)


# =============================================================================
# FIBONACCI TESTS
# =============================================================================

class TestFibonacci:
    """Tests for Fibonacci level calculation."""

    def test_fibonacci_levels_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test Fibonacci levels are calculated."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert isinstance(ctx.fib_levels, dict)
        assert len(ctx.fib_levels) > 0

    def test_fibonacci_standard_levels(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test standard Fibonacci levels are present."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        # Should have standard levels
        expected_keys = ['0.0', '0.236', '0.382', '0.5', '0.618', '0.786', '1.0']
        for key in expected_keys:
            assert key in ctx.fib_levels


# =============================================================================
# ATR TESTS
# =============================================================================

class TestATR:
    """Tests for ATR calculation."""

    def test_atr_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test ATR is calculated."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.atr_14 is not None
        assert ctx.atr_14 > 0  # ATR should be positive


# =============================================================================
# VOLUME TESTS
# =============================================================================

class TestVolume:
    """Tests for volume calculations."""

    def test_avg_volume_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test average volume is calculated."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.avg_volume_20 is not None
        expected = sum(sample_volumes[-20:]) / 20
        assert abs(ctx.avg_volume_20 - expected) < 1

    def test_volume_ratio_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test volume ratio is calculated."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.volume_ratio is not None
        assert ctx.volume_ratio > 0


# =============================================================================
# ATH TESTS
# =============================================================================

class TestATH:
    """Tests for All-Time High tracking."""

    def test_ath_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test ATH is calculated."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.all_time_high is not None
        assert ctx.all_time_high == max(sample_highs)

    def test_pct_from_ath_calculated(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test percent from ATH is calculated."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.pct_from_ath is not None


# =============================================================================
# TREND TESTS
# =============================================================================

class TestTrend:
    """Tests for trend determination."""

    def test_trend_determined(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test trend is determined."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.trend in ['uptrend', 'downtrend', 'sideways']

    def test_above_sma_flags(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test above SMA flags are set."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        # Should have boolean values for SMA comparisons
        assert ctx.above_sma20 is not None
        assert ctx.above_sma50 is not None


# =============================================================================
# TO_DICT TESTS
# =============================================================================

class TestToDict:
    """Tests for to_dict method."""

    def test_to_dict_basic(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test to_dict returns dictionary."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        result = ctx.to_dict()

        assert isinstance(result, dict)
        assert result['symbol'] == "TEST"
        assert 'current_price' in result
        assert 'rsi_14' in result
        assert 'trend' in result

    def test_to_dict_contains_key_fields(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test to_dict contains all key fields."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        result = ctx.to_dict()

        expected_keys = [
            'symbol', 'current_price', 'rsi_14', 'sma_20', 'sma_50', 'sma_200',
            'macd_line', 'macd_signal', 'stoch_k', 'support_levels',
            'resistance_levels', 'trend', 'volume_ratio', 'pct_from_ath',
            'gap_score', 'gap_type'
        ]
        for key in expected_keys:
            assert key in result


# =============================================================================
# PYTHON FALLBACK CALCULATION TESTS
# =============================================================================

class TestPythonFallback:
    """Tests for pure Python calculation fallback."""

    def test_calc_rsi_pure_python(self):
        """Test RSI calculation via canonical calculate_rsi."""
        from src.indicators.momentum import calculate_rsi

        # Generate prices with uptrend
        prices = [100.0 + i * 0.5 for i in range(30)]

        rsi = calculate_rsi(prices, 14)

        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_calc_rsi_insufficient_data(self):
        """Test RSI with insufficient data returns 50.0 (neutral)."""
        from src.indicators.momentum import calculate_rsi

        prices = [100.0, 101.0, 102.0]  # Too few

        # calculate_rsi returns 50.0 for insufficient data
        rsi = calculate_rsi(prices, 14)

        assert rsi == 50.0

    def test_calc_sma_pure_python(self):
        """Test pure Python SMA calculation."""
        ctx = AnalysisContext(symbol="TEST")

        prices = [100.0 + i for i in range(30)]

        sma = ctx._calc_sma(prices, 20)

        expected = sum(prices[-20:]) / 20
        assert abs(sma - expected) < 0.01

    def test_calc_sma_insufficient_data(self):
        """Test SMA with insufficient data."""
        ctx = AnalysisContext(symbol="TEST")

        prices = [100.0, 101.0]

        sma = ctx._calc_sma(prices, 20)

        assert sma is None

    def test_calc_ema_pure_python(self):
        """Test pure Python EMA calculation."""
        ctx = AnalysisContext(symbol="TEST")

        prices = [100.0 + i * 0.1 for i in range(30)]

        ema = ctx._calc_ema(prices, 12)

        assert ema is not None
        assert len(ema) > 0

    def test_calc_fibonacci_pure_python(self):
        """Test pure Python Fibonacci calculation."""
        ctx = AnalysisContext(symbol="TEST")

        fib = ctx._calc_fibonacci(high=110.0, low=100.0)

        assert '0.0' in fib
        assert fib['0.0'] == 110.0
        assert '1.0' in fib
        assert fib['1.0'] == 100.0
        assert '0.5' in fib
        assert fib['0.5'] == 105.0

    def test_calc_atr_pure_python(self):
        """Test pure Python ATR calculation."""
        ctx = AnalysisContext(symbol="TEST")

        prices = [100.0 + i * 0.1 for i in range(30)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        atr = ctx._calc_atr(highs, lows, prices, 14)

        assert atr is not None
        assert atr > 0

    def test_calc_stochastic_pure_python(self):
        """Test pure Python Stochastic calculation."""
        ctx = AnalysisContext(symbol="TEST")

        prices = [100.0 + i * 0.1 for i in range(30)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        ctx._calc_stochastic(highs, lows, prices)

        assert ctx.stoch_k is not None
        assert ctx.stoch_d is not None


# =============================================================================
# GAP ANALYSIS TESTS
# =============================================================================

class TestGapAnalysis:
    """Tests for gap analysis."""

    def test_gap_score_initialized(self, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test gap score is initialized."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        # gap_score should be a number
        assert isinstance(ctx.gap_score, (int, float))


# =============================================================================
# EDGE CASES TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_volumes(self, sample_prices, sample_highs, sample_lows):
        """Test handling of empty volumes."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=sample_prices,
            volumes=[],  # Empty volumes
            highs=sample_highs,
            lows=sample_lows,
        )

        assert ctx.symbol == "TEST"
        assert ctx.current_volume == 0

    def test_constant_prices(self):
        """Test handling of constant prices."""
        prices = [100.0] * 90
        volumes = [1000000] * 90
        highs = [101.0] * 90
        lows = [99.0] * 90

        ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        assert ctx.symbol == "TEST"
        # RSI should handle constant prices
        assert ctx.rsi_14 is not None

    def test_single_data_point(self):
        """Test handling of single data point."""
        ctx = AnalysisContext.from_data(
            symbol="TEST",
            prices=[100.0],
            volumes=[1000000],
            highs=[101.0],
            lows=[99.0],
        )

        # Should handle gracefully
        assert ctx.symbol == "TEST"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
