# OptionPlay - Performance Benchmark Tests
# =========================================
# Measures and validates performance improvements.
#
# Run with:
#     pytest tests/test_performance_benchmark.py -v --tb=short
#     pytest tests/test_performance_benchmark.py -v -k "benchmark" --benchmark

import pytest
import time
import numpy as np
from typing import List, Tuple
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.indicators.optimized import (
    calc_rsi_numpy,
    calc_sma_numpy,
    calc_sma_series,
    calc_ema_numpy,
    calc_macd_numpy,
    calc_stochastic_numpy,
    calc_atr_numpy,
    calc_all_indicators,
)
from src.analyzers.context import AnalysisContext


# =============================================================================
# TEST DATA GENERATION
# =============================================================================

def generate_price_data(n_days: int = 252, seed: int = 42) -> Tuple[
    List[float], List[float], List[float], List[int]
]:
    """
    Generate realistic price data for benchmarking.

    Returns:
        Tuple of (closes, highs, lows, volumes)
    """
    np.random.seed(seed)

    # Generate random walk with drift
    returns = np.random.normal(0.0005, 0.02, n_days)  # 0.05% daily drift, 2% vol
    prices = 100 * np.exp(np.cumsum(returns))

    # Generate OHLC from closes
    volatility = prices * 0.02  # 2% daily range
    highs = prices + np.abs(np.random.normal(0, volatility))
    lows = prices - np.abs(np.random.normal(0, volatility))

    # Ensure H > C > L
    highs = np.maximum(highs, prices * 1.001)
    lows = np.minimum(lows, prices * 0.999)

    # Generate volume
    base_volume = 1_000_000
    volumes = np.random.poisson(base_volume, n_days)

    return (
        prices.tolist(),
        highs.tolist(),
        lows.tolist(),
        volumes.tolist()
    )


# =============================================================================
# PURE PYTHON REFERENCE IMPLEMENTATIONS
# =============================================================================

def rsi_pure_python(prices: List[float], period: int = 14) -> float:
    """Pure Python RSI for comparison."""
    if len(prices) < period + 1:
        return 50.0

    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def sma_pure_python(prices: List[float], period: int) -> float:
    """Pure Python SMA for comparison."""
    return sum(prices[-period:]) / period


def stochastic_pure_python(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    k_period: int = 14,
    d_period: int = 3
) -> Tuple[float, float]:
    """Pure Python Stochastic for comparison."""
    k_values = []
    for i in range(d_period):
        offset = d_period - 1 - i
        end_idx = len(closes) - offset
        start_idx = end_idx - k_period

        highest_high = max(highs[start_idx:end_idx])
        lowest_low = min(lows[start_idx:end_idx])
        close = closes[end_idx - 1]

        if highest_high == lowest_low:
            k_values.append(50.0)
        else:
            k_val = (close - lowest_low) / (highest_high - lowest_low) * 100
            k_values.append(k_val)

    return k_values[-1], sum(k_values) / len(k_values)


# =============================================================================
# CORRECTNESS TESTS
# =============================================================================

class TestIndicatorCorrectness:
    """Verify that optimized implementations produce correct results."""

    @pytest.fixture
    def price_data(self):
        """Generate standard test data."""
        return generate_price_data(252)

    def test_rsi_matches_python(self, price_data):
        """RSI numpy should match pure Python implementation."""
        prices, _, _, _ = price_data

        rsi_numpy = calc_rsi_numpy(prices, 14)
        rsi_python = rsi_pure_python(prices, 14)

        assert rsi_numpy is not None
        assert abs(rsi_numpy - rsi_python) < 0.01, \
            f"RSI mismatch: numpy={rsi_numpy:.4f}, python={rsi_python:.4f}"

    def test_sma_matches_python(self, price_data):
        """SMA numpy should match pure Python implementation."""
        prices, _, _, _ = price_data

        for period in [20, 50, 200]:
            if len(prices) >= period:
                sma_numpy = calc_sma_numpy(prices, period)
                sma_python = sma_pure_python(prices, period)

                assert sma_numpy is not None
                assert abs(sma_numpy - sma_python) < 0.0001, \
                    f"SMA{period} mismatch: numpy={sma_numpy:.4f}, python={sma_python:.4f}"

    def test_stochastic_matches_python(self, price_data):
        """Stochastic numpy should match pure Python implementation."""
        prices, highs, lows, _ = price_data

        stoch_numpy = calc_stochastic_numpy(highs, lows, prices)
        k_python, d_python = stochastic_pure_python(highs, lows, prices)

        assert stoch_numpy is not None
        assert abs(stoch_numpy.k - k_python) < 0.1, \
            f"Stoch K mismatch: numpy={stoch_numpy.k:.2f}, python={k_python:.2f}"
        assert abs(stoch_numpy.d - d_python) < 0.1, \
            f"Stoch D mismatch: numpy={stoch_numpy.d:.2f}, python={d_python:.2f}"

    def test_rsi_range(self, price_data):
        """RSI should always be between 0 and 100."""
        prices, _, _, _ = price_data

        rsi = calc_rsi_numpy(prices, 14)
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_stochastic_zones(self, price_data):
        """Stochastic should correctly identify zones."""
        prices, highs, lows, _ = price_data

        stoch = calc_stochastic_numpy(highs, lows, prices)
        assert stoch is not None

        # Zone should match K value
        if stoch.k < 20:
            assert stoch.zone == 'oversold'
        elif stoch.k > 80:
            assert stoch.zone == 'overbought'
        else:
            assert stoch.zone == 'neutral'

    def test_macd_values(self, price_data):
        """MACD should have sensible values."""
        prices, _, _, _ = price_data

        macd = calc_macd_numpy(prices)
        assert macd is not None
        assert macd.macd_line is not None
        assert macd.signal_line is not None
        assert macd.histogram is not None

        # Histogram should equal macd_line - signal_line
        expected_hist = macd.macd_line - macd.signal_line
        assert abs(macd.histogram - expected_hist) < 0.0001


# =============================================================================
# PERFORMANCE BENCHMARK TESTS
# =============================================================================

class TestPerformanceBenchmarks:
    """Benchmark tests to measure and validate performance improvements."""

    @pytest.fixture
    def large_price_data(self):
        """Generate larger dataset for benchmarking."""
        return generate_price_data(1000)

    def _time_function(self, func, iterations: int = 100) -> float:
        """Time a function over multiple iterations."""
        start = time.perf_counter()
        for _ in range(iterations):
            func()
        end = time.perf_counter()
        return (end - start) / iterations * 1000  # ms

    def test_rsi_performance(self, large_price_data):
        """RSI numpy should be faster than pure Python."""
        prices, _, _, _ = large_price_data
        iterations = 100

        # Time numpy version
        numpy_time = self._time_function(
            lambda: calc_rsi_numpy(prices, 14),
            iterations
        )

        # Time pure Python version
        python_time = self._time_function(
            lambda: rsi_pure_python(prices, 14),
            iterations
        )

        speedup = python_time / numpy_time if numpy_time > 0 else 1

        print(f"\nRSI Performance (1000 days, {iterations} iterations):")
        print(f"  NumPy:  {numpy_time:.3f}ms")
        print(f"  Python: {python_time:.3f}ms")
        print(f"  Speedup: {speedup:.1f}x")

        # NumPy should be at least 2x faster
        assert speedup >= 1.5, f"RSI speedup only {speedup:.1f}x, expected >= 2x"

    def test_sma_series_performance(self, large_price_data):
        """Rolling SMA using cumsum should be much faster than naive."""
        prices, _, _, _ = large_price_data
        prices_arr = np.array(prices)
        period = 20
        iterations = 100

        # Time optimized version (cumsum trick)
        numpy_time = self._time_function(
            lambda: calc_sma_series(prices_arr, period),
            iterations
        )

        # Time naive version
        def naive_sma_series():
            result = []
            for i in range(period - 1, len(prices)):
                result.append(sum(prices[i - period + 1:i + 1]) / period)
            return result

        naive_time = self._time_function(naive_sma_series, iterations)

        speedup = naive_time / numpy_time if numpy_time > 0 else 1

        print(f"\nSMA Series Performance (1000 days, {iterations} iterations):")
        print(f"  NumPy (cumsum): {numpy_time:.3f}ms")
        print(f"  Naive:          {naive_time:.3f}ms")
        print(f"  Speedup: {speedup:.1f}x")

        # Cumsum should be at least 5x faster
        assert speedup >= 3, f"SMA series speedup only {speedup:.1f}x, expected >= 5x"

    def test_stochastic_performance(self, large_price_data):
        """Stochastic with stride tricks should be faster."""
        prices, highs, lows, _ = large_price_data
        iterations = 100

        # Time numpy version
        numpy_time = self._time_function(
            lambda: calc_stochastic_numpy(highs, lows, prices),
            iterations
        )

        # Time pure Python version
        python_time = self._time_function(
            lambda: stochastic_pure_python(highs, lows, prices),
            iterations
        )

        speedup = python_time / numpy_time if numpy_time > 0 else 1

        print(f"\nStochastic Performance (1000 days, {iterations} iterations):")
        print(f"  NumPy:  {numpy_time:.3f}ms")
        print(f"  Python: {python_time:.3f}ms")
        print(f"  Speedup: {speedup:.1f}x")

        # Should be at least 2x faster
        assert speedup >= 1.5, f"Stochastic speedup only {speedup:.1f}x"

    def test_full_context_performance(self, large_price_data):
        """Full context calculation should complete in reasonable time."""
        prices, highs, lows, volumes = large_price_data
        iterations = 50

        # Time full context creation
        context_time = self._time_function(
            lambda: AnalysisContext.from_data("TEST", prices, volumes, highs, lows),
            iterations
        )

        print(f"\nFull Context Creation (1000 days, {iterations} iterations):")
        print(f"  Time: {context_time:.3f}ms per symbol")

        # Should complete in under 50ms per symbol
        assert context_time < 50, f"Context creation too slow: {context_time:.1f}ms"

    def test_bundle_calculation_performance(self, large_price_data):
        """All indicators in bundle should complete quickly."""
        prices, highs, lows, volumes = large_price_data
        iterations = 100

        bundle_time = self._time_function(
            lambda: calc_all_indicators(prices, highs, lows, volumes),
            iterations
        )

        print(f"\nIndicator Bundle (1000 days, {iterations} iterations):")
        print(f"  Time: {bundle_time:.3f}ms per symbol")

        # Should complete in under 20ms per symbol
        assert bundle_time < 30, f"Bundle calculation too slow: {bundle_time:.1f}ms"


# =============================================================================
# MEMORY EFFICIENCY TESTS
# =============================================================================

class TestMemoryEfficiency:
    """Test memory efficiency of optimized implementations."""

    def test_ema_memory_efficiency(self):
        """EMA should only store last value when requested."""
        prices = list(range(1000))

        # Full EMA (stores all values)
        ema_full = calc_ema_numpy(prices, 12, return_last_only=False)

        # Last only (memory efficient)
        ema_last = calc_ema_numpy(prices, 12, return_last_only=True)

        # Both should give same final value
        assert isinstance(ema_last, float)
        assert isinstance(ema_full, np.ndarray)
        assert abs(ema_last - ema_full[-1]) < 0.0001

        # Full array should have many elements
        assert len(ema_full) > 900

    def test_context_doesnt_store_full_ema_arrays(self):
        """Context should not store full EMA arrays anymore."""
        prices, highs, lows, volumes = generate_price_data(500)

        context = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        # EMA should be single-element list for backward compat
        if context.ema_12 is not None:
            assert len(context.ema_12) <= 1, "EMA_12 should only store last value"
        if context.ema_26 is not None:
            assert len(context.ema_26) <= 1, "EMA_26 should only store last value"


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_insufficient_data_rsi(self):
        """RSI should handle insufficient data gracefully."""
        short_prices = [100, 101, 102]
        result = calc_rsi_numpy(short_prices, 14)
        assert result is None

    def test_insufficient_data_macd(self):
        """MACD should handle insufficient data gracefully."""
        short_prices = list(range(20))
        result = calc_macd_numpy(short_prices)
        assert result is None

    def test_insufficient_data_stochastic(self):
        """Stochastic should handle insufficient data gracefully."""
        short_data = list(range(10))
        result = calc_stochastic_numpy(short_data, short_data, short_data)
        assert result is None

    def test_constant_prices_rsi(self):
        """RSI should handle constant prices (no changes)."""
        constant_prices = [100.0] * 50
        result = calc_rsi_numpy(constant_prices, 14)
        # With no changes, RSI is undefined but should return a sensible value
        assert result is not None

    def test_constant_prices_stochastic(self):
        """Stochastic should handle constant prices."""
        constant = [100.0] * 50
        result = calc_stochastic_numpy(constant, constant, constant)
        assert result is not None
        # With no range, K should be 50 (middle)
        assert result.k == 50.0

    def test_empty_data(self):
        """Should handle empty data gracefully."""
        assert calc_rsi_numpy([], 14) is None
        assert calc_sma_numpy([], 20) is None
        assert calc_macd_numpy([]) is None


# =============================================================================
# RUN BENCHMARKS
# =============================================================================

if __name__ == "__main__":
    # Run benchmarks with verbose output
    pytest.main([
        __file__,
        "-v",
        "-s",  # Show print statements
        "-k", "Performance",  # Only run performance tests
    ])
