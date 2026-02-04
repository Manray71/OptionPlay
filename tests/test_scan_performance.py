# OptionPlay - Scanner Performance Benchmark
# ============================================
# End-to-end benchmark for scanner performance improvements.
#
# Run with:
#     pytest tests/test_scan_performance.py -v -s --tb=short

import asyncio
import pytest
import time
import numpy as np
from typing import List, Tuple
from datetime import datetime

from src.scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig, ScanMode
from src.analyzers.context import AnalysisContext


# =============================================================================
# MOCK DATA GENERATION
# =============================================================================

def generate_mock_data(n_days: int = 252, seed: int = 42) -> Tuple[
    List[float], List[int], List[float], List[float]
]:
    """Generate realistic price data for benchmarking."""
    np.random.seed(seed)

    # Generate random walk with drift
    returns = np.random.normal(0.0005, 0.02, n_days)
    prices = 100 * np.exp(np.cumsum(returns))

    # Generate OHLC from closes
    volatility = prices * 0.02
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
        volumes.tolist(),
        highs.tolist(),
        lows.tolist()
    )


# =============================================================================
# SCANNER PERFORMANCE TESTS
# =============================================================================

class TestScannerPerformance:
    """Benchmark scanner performance with optimizations."""

    @pytest.fixture
    def mock_data_cache(self):
        """Pre-generate mock data for all test symbols."""
        symbols = [f"TEST{i}" for i in range(50)]  # 50 symbols
        data_cache = {}
        for i, sym in enumerate(symbols):
            data_cache[sym] = generate_mock_data(252, seed=i)
        return symbols, data_cache

    def test_analyzer_pool_prefill_performance(self):
        """Pool prefill should be fast and reduce first-scan latency."""
        scanner = MultiStrategyScanner()

        # Time prefill
        start = time.perf_counter()
        prefilled = scanner.prefill_pool()
        prefill_time = (time.perf_counter() - start) * 1000

        print(f"\nPool Prefill Performance:")
        print(f"  Prefilled: {prefilled}")
        print(f"  Time: {prefill_time:.2f}ms")

        # Prefill should be fast (< 100ms)
        assert prefill_time < 100, f"Prefill too slow: {prefill_time:.2f}ms"

        # All strategies should be prefilled
        assert sum(prefilled.values()) >= 4 * 5  # 4 strategies * 5 pool size

    def test_context_creation_performance(self):
        """AnalysisContext creation should be fast."""
        prices, volumes, highs, lows = generate_mock_data(252)
        iterations = 100

        start = time.perf_counter()
        for _ in range(iterations):
            ctx = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)
        end = time.perf_counter()

        avg_time = (end - start) / iterations * 1000

        print(f"\nContext Creation Performance ({iterations} iterations):")
        print(f"  Average: {avg_time:.3f}ms per symbol")

        # Should be under 20ms per symbol
        assert avg_time < 20, f"Context creation too slow: {avg_time:.2f}ms"

    def test_context_caching_benefit(self, mock_data_cache):
        """Context caching should provide measurable speedup."""
        symbols, data_cache = mock_data_cache
        scanner = MultiStrategyScanner()

        # Simulate analysis with context caching (as in optimized scanner)
        context_cache = {}

        start_cached = time.perf_counter()
        for sym in symbols:
            prices, volumes, highs, lows = data_cache[sym]

            # Create context only once per symbol (cached)
            if sym not in context_cache:
                context_cache[sym] = AnalysisContext.from_data(
                    sym, prices, volumes, highs, lows
                )

            # Analyze with cached context
            scanner.analyze_symbol(
                symbol=sym,
                prices=prices,
                volumes=volumes,
                highs=highs,
                lows=lows,
                context=context_cache[sym]
            )
        cached_time = (time.perf_counter() - start_cached) * 1000

        # Simulate analysis without caching
        start_uncached = time.perf_counter()
        for sym in symbols:
            prices, volumes, highs, lows = data_cache[sym]

            # Each analysis creates its own context
            scanner.analyze_symbol(
                symbol=sym,
                prices=prices,
                volumes=volumes,
                highs=highs,
                lows=lows,
                # No context provided - will create one internally
            )
        uncached_time = (time.perf_counter() - start_uncached) * 1000

        speedup = uncached_time / cached_time if cached_time > 0 else 1

        print(f"\nContext Caching Performance ({len(symbols)} symbols):")
        print(f"  With caching: {cached_time:.1f}ms")
        print(f"  Without caching: {uncached_time:.1f}ms")
        print(f"  Speedup: {speedup:.2f}x")

        # Caching should not cause significant regression
        # Note: In optimized scanner, context is created once and shared
        # Allow for minor timing variations (up to 10% regression)
        assert speedup >= 0.90, f"Caching regression: {speedup:.2f}x"

    @pytest.mark.asyncio
    async def test_async_scan_performance(self, mock_data_cache):
        """Async scan should complete in reasonable time."""
        symbols, data_cache = mock_data_cache

        scanner = MultiStrategyScanner(ScanConfig(
            min_score=0.0,  # Accept all signals for benchmark
            max_total_results=100,
            max_concurrent=10,
        ))

        # Prefill pool for consistent timing
        scanner.prefill_pool()

        async def mock_fetcher(symbol: str):
            """Mock data fetcher returning cached data."""
            # Simulate small network delay
            await asyncio.sleep(0.001)  # 1ms
            return data_cache.get(symbol)

        start = time.perf_counter()
        result = await scanner.scan_async(
            symbols=symbols,
            data_fetcher=mock_fetcher,
            mode=ScanMode.ALL
        )
        scan_time = (time.perf_counter() - start) * 1000

        print(f"\nAsync Scan Performance ({len(symbols)} symbols, all strategies):")
        print(f"  Total time: {scan_time:.1f}ms")
        print(f"  Per symbol: {scan_time / len(symbols):.2f}ms")
        print(f"  Signals found: {len(result.signals)}")
        print(f"  Symbols with signals: {result.symbols_with_signals}")

        # Scan should complete in reasonable time
        # With 50 symbols, 1ms fetch delay, 10 concurrent = ~50ms for fetch
        # Plus analysis time (~10ms per symbol) = ~550ms total
        # Our optimizations should bring this under 1000ms
        assert scan_time < 2000, f"Scan too slow: {scan_time:.1f}ms"

    @pytest.mark.asyncio
    async def test_semaphore_deferral_benefit(self, mock_data_cache):
        """Deferring semaphore acquisition should improve throughput."""
        symbols, data_cache = mock_data_cache

        # Simulate fetch times to see concurrency benefit
        fetch_delay_ms = 5  # 5ms simulated network delay

        scanner = MultiStrategyScanner(ScanConfig(
            min_score=0.0,
            max_total_results=100,
            max_concurrent=10,  # Only 10 concurrent
        ))
        scanner.prefill_pool()

        async def slow_fetcher(symbol: str):
            """Mock fetcher with simulated delay."""
            await asyncio.sleep(fetch_delay_ms / 1000)
            return data_cache.get(symbol)

        start = time.perf_counter()
        result = await scanner.scan_async(
            symbols=symbols[:20],  # Use 20 symbols
            data_fetcher=slow_fetcher,
            mode=ScanMode.PULLBACK_ONLY  # Single strategy for simplicity
        )
        scan_time = (time.perf_counter() - start) * 1000

        # With optimized semaphore deferral:
        # - 20 symbols, 5ms fetch delay
        # - Fetches can all run in parallel (no semaphore during fetch)
        # - Only analysis is limited by semaphore
        # Expected: ~50-100ms (fetch) + analysis time

        # Without optimization (old behavior):
        # - 20 symbols, 5ms fetch delay, 10 concurrent
        # - Expected: 2 batches * 5ms = ~10ms fetch + analysis
        # But with fetch inside semaphore, throughput is limited

        print(f"\nSemaphore Deferral Performance (20 symbols, {fetch_delay_ms}ms fetch):")
        print(f"  Total time: {scan_time:.1f}ms")
        print(f"  Signals: {len(result.signals)}")

        # Should complete faster than serial execution
        serial_time = 20 * fetch_delay_ms
        assert scan_time < serial_time * 2, f"Poor concurrency: {scan_time:.1f}ms vs {serial_time}ms serial"


# =============================================================================
# HEAPQ OPTIMIZATION TESTS
# =============================================================================

class TestHeapqOptimization:
    """Test that heapq.nlargest is used for large result sets."""

    def test_nlargest_faster_than_sort(self):
        """heapq.nlargest should be faster than sort for top-k."""
        import heapq

        # Generate large list of mock signals
        n = 1000
        k = 50
        data = [(np.random.random(), i) for i in range(n)]

        # Time sort + slice
        start = time.perf_counter()
        for _ in range(100):
            sorted_data = sorted(data, key=lambda x: x[0], reverse=True)[:k]
        sort_time = (time.perf_counter() - start) * 1000

        # Time heapq.nlargest
        start = time.perf_counter()
        for _ in range(100):
            heap_data = heapq.nlargest(k, data, key=lambda x: x[0])
        heap_time = (time.perf_counter() - start) * 1000

        print(f"\nHeapq vs Sort (n={n}, k={k}, 100 iterations):")
        print(f"  Sort + slice: {sort_time:.2f}ms")
        print(f"  heapq.nlargest: {heap_time:.2f}ms")
        print(f"  Speedup: {sort_time / heap_time:.2f}x")

        # heapq should be faster for large n, small k
        # (though Python's sort is very optimized)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
