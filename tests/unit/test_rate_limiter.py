# OptionPlay - Rate Limiter Tests
# =================================
# Comprehensive tests for src/utils/rate_limiter.py
#
# Covers:
# - RateLimiter initialization
# - acquire method (sync and async)
# - wait_if_needed mechanics
# - Burst handling
# - Token bucket algorithm

import pytest
import asyncio
import time
import threading
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    AdaptiveRateLimiter,
    retry_with_backoff,
    get_limiter,
    get_marketdata_limiter,
    get_yahoo_limiter,
    _limiters,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def limiter():
    """Create a basic rate limiter."""
    return RateLimiter(calls_per_minute=600, burst_limit=10, name="test")


@pytest.fixture
def slow_limiter():
    """Create a slow rate limiter for testing wait behavior."""
    return RateLimiter(calls_per_minute=60, burst_limit=2, name="slow")


@pytest.fixture
def fast_limiter():
    """Create a fast rate limiter for quick refill tests."""
    return RateLimiter(calls_per_minute=6000, burst_limit=5, name="fast")


@pytest.fixture
def adaptive_limiter():
    """Create an adaptive rate limiter."""
    return AdaptiveRateLimiter(
        calls_per_minute=100,
        min_rate=10,
        backoff_factor=0.5,
        recovery_factor=1.1,
        name="adaptive_test"
    )


@pytest.fixture(autouse=True)
def clear_global_limiters():
    """Clear global limiter cache before each test."""
    _limiters.clear()
    yield
    _limiters.clear()


# =============================================================================
# RateLimitConfig Tests
# =============================================================================

class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_config(self):
        """Test default config values."""
        config = RateLimitConfig()

        assert config.calls_per_minute == 100
        assert config.calls_per_second == 10
        assert config.burst_limit == 5
        assert config.backoff_base == 1.0
        assert config.backoff_max == 60.0
        assert config.backoff_factor == 2.0

    def test_custom_config(self):
        """Test custom config values."""
        config = RateLimitConfig(
            calls_per_minute=200,
            calls_per_second=20,
            burst_limit=10,
            backoff_base=2.0,
            backoff_max=120.0,
            backoff_factor=3.0
        )

        assert config.calls_per_minute == 200
        assert config.calls_per_second == 20
        assert config.burst_limit == 10
        assert config.backoff_base == 2.0
        assert config.backoff_max == 120.0
        assert config.backoff_factor == 3.0


# =============================================================================
# RateLimiter Initialization Tests
# =============================================================================

class TestRateLimiterInitialization:
    """Tests for RateLimiter initialization."""

    def test_create_with_default_burst_limit(self):
        """Test creating limiter calculates default burst limit."""
        limiter = RateLimiter(calls_per_minute=100, name="test")

        # Default burst = min(10, calls_per_minute // 10)
        assert limiter.burst_limit == 10

    def test_create_with_low_rate_default_burst(self):
        """Test default burst limit with low rate."""
        limiter = RateLimiter(calls_per_minute=30, name="test")

        # burst = min(10, 30 // 10) = min(10, 3) = 3
        assert limiter.burst_limit == 3

    def test_create_with_custom_burst_limit(self):
        """Test creating limiter with custom burst limit."""
        limiter = RateLimiter(calls_per_minute=100, burst_limit=20, name="test")

        assert limiter.burst_limit == 20

    def test_calls_per_second_calculation(self):
        """Test calls_per_second is correctly calculated."""
        limiter = RateLimiter(calls_per_minute=120, name="test")

        assert limiter.calls_per_second == 2.0  # 120 / 60

    def test_initial_tokens_equal_burst_limit(self):
        """Test initial tokens equal burst limit."""
        limiter = RateLimiter(calls_per_minute=100, burst_limit=15, name="test")

        assert limiter._tokens == 15.0
        assert limiter.available_tokens == 15.0

    def test_initial_statistics(self):
        """Test initial statistics are zero."""
        limiter = RateLimiter(calls_per_minute=100, name="test")

        assert limiter._total_requests == 0
        assert limiter._total_waits == 0
        assert limiter._total_wait_time == 0.0

    def test_name_is_stored(self):
        """Test limiter name is stored correctly."""
        limiter = RateLimiter(calls_per_minute=100, name="my_limiter")

        assert limiter.name == "my_limiter"

    def test_async_lock_not_created_initially(self):
        """Test async lock is not created until needed."""
        limiter = RateLimiter(calls_per_minute=100, name="test")

        assert limiter._async_lock is None

    def test_thread_lock_created_on_init(self):
        """Test thread lock is created on initialization."""
        limiter = RateLimiter(calls_per_minute=100, name="test")

        assert limiter._lock is not None
        assert isinstance(limiter._lock, type(threading.Lock()))


# =============================================================================
# Token Bucket Algorithm Tests
# =============================================================================

class TestTokenBucketAlgorithm:
    """Tests for the token bucket algorithm implementation."""

    def test_tokens_consumed_on_acquire_sync(self, limiter):
        """Test tokens are consumed on acquire_sync."""
        initial_tokens = limiter.available_tokens
        limiter.acquire_sync()

        # One token should be consumed
        assert limiter.available_tokens < initial_tokens

    def test_tokens_consumed_sequentially(self, limiter):
        """Test tokens are consumed correctly for multiple acquires."""
        initial_tokens = limiter.available_tokens

        for i in range(5):
            limiter.acquire_sync()

        # 5 tokens consumed (minus any refill during test)
        assert limiter.available_tokens < initial_tokens - 4

    def test_tokens_refill_based_on_time(self, fast_limiter):
        """Test tokens refill based on elapsed time."""
        # Exhaust all tokens
        for _ in range(fast_limiter.burst_limit):
            fast_limiter.try_acquire()

        tokens_after_exhaust = fast_limiter.available_tokens
        assert tokens_after_exhaust < 1

        # Wait for refill (6000/min = 100/sec)
        time.sleep(0.05)

        tokens_after_wait = fast_limiter.available_tokens
        assert tokens_after_wait > tokens_after_exhaust

    def test_tokens_capped_at_burst_limit(self, fast_limiter):
        """Test tokens do not exceed burst limit."""
        # Start with full tokens
        initial_tokens = fast_limiter.available_tokens
        assert initial_tokens == fast_limiter.burst_limit

        # Wait some time - tokens should stay at burst limit
        time.sleep(0.1)

        # Tokens should not exceed burst limit
        assert fast_limiter.available_tokens <= fast_limiter.burst_limit

    def test_refill_rate_matches_calls_per_second(self):
        """Test refill rate matches configured calls_per_second."""
        # 600 calls/min = 10 calls/sec
        limiter = RateLimiter(calls_per_minute=600, burst_limit=5, name="test")

        # Exhaust tokens
        for _ in range(5):
            limiter.try_acquire()

        assert limiter.available_tokens < 1

        # Wait 0.1 seconds, should refill ~1 token (10/sec * 0.1 = 1)
        time.sleep(0.1)

        tokens = limiter.available_tokens
        assert 0.5 < tokens < 2  # Allow some variance for timing

    def test_wait_time_calculation_when_tokens_available(self, limiter):
        """Test wait time is zero when tokens are available."""
        # Force a refill check
        limiter._refill_tokens()
        wait_time = limiter._wait_time()

        assert wait_time == 0.0

    def test_wait_time_calculation_when_tokens_exhausted(self):
        """Test wait time calculation when tokens are exhausted."""
        limiter = RateLimiter(calls_per_minute=60, burst_limit=1, name="test")

        # Exhaust the only token
        limiter.try_acquire()

        # Calculate wait time (60/min = 1/sec, so need 1 second for 1 token)
        wait_time = limiter._wait_time()

        assert wait_time > 0
        # Should be close to 1 second (allowing for fractional token refill)
        assert wait_time <= 1.0


# =============================================================================
# Acquire Method Tests
# =============================================================================

class TestAcquireSync:
    """Tests for synchronous acquire method."""

    def test_acquire_sync_returns_wait_time(self, limiter):
        """Test acquire_sync returns wait time."""
        wait_time = limiter.acquire_sync()

        assert isinstance(wait_time, float)
        assert wait_time >= 0

    def test_acquire_sync_no_wait_with_tokens(self, limiter):
        """Test acquire_sync doesn't wait when tokens are available."""
        wait_time = limiter.acquire_sync()

        assert wait_time == 0.0

    def test_acquire_sync_increments_request_count(self, limiter):
        """Test acquire_sync increments request count."""
        initial_requests = limiter._total_requests

        limiter.acquire_sync()

        assert limiter._total_requests == initial_requests + 1

    def test_acquire_sync_waits_when_exhausted(self, slow_limiter):
        """Test acquire_sync waits when tokens exhausted."""
        # Exhaust tokens
        for _ in range(slow_limiter.burst_limit):
            slow_limiter.acquire_sync()

        start_time = time.monotonic()
        slow_limiter.acquire_sync()
        elapsed = time.monotonic() - start_time

        # Should have waited (60/min = 1/sec, so ~1 second per token)
        assert elapsed > 0.5

    def test_acquire_sync_tracks_wait_statistics(self, slow_limiter):
        """Test acquire_sync tracks wait statistics."""
        # Exhaust tokens
        for _ in range(slow_limiter.burst_limit):
            slow_limiter.acquire_sync()

        # This should wait
        slow_limiter.acquire_sync()

        assert slow_limiter._total_waits > 0
        assert slow_limiter._total_wait_time > 0


class TestAcquireAsync:
    """Tests for asynchronous acquire method."""

    @pytest.mark.asyncio
    async def test_acquire_async_returns_wait_time(self, limiter):
        """Test async acquire returns wait time."""
        wait_time = await limiter.acquire()

        assert isinstance(wait_time, float)
        assert wait_time >= 0

    @pytest.mark.asyncio
    async def test_acquire_async_no_wait_with_tokens(self, limiter):
        """Test async acquire doesn't wait when tokens available."""
        wait_time = await limiter.acquire()

        assert wait_time == 0.0

    @pytest.mark.asyncio
    async def test_acquire_async_increments_request_count(self, limiter):
        """Test async acquire increments request count."""
        initial_requests = limiter._total_requests

        await limiter.acquire()

        assert limiter._total_requests == initial_requests + 1

    @pytest.mark.asyncio
    async def test_acquire_async_creates_lock_on_first_use(self, limiter):
        """Test async lock is created on first async acquire."""
        assert limiter._async_lock is None

        await limiter.acquire()

        assert limiter._async_lock is not None
        assert isinstance(limiter._async_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_acquire_async_reuses_lock(self, limiter):
        """Test async acquire reuses the same lock."""
        await limiter.acquire()
        first_lock = limiter._async_lock

        await limiter.acquire()

        assert limiter._async_lock is first_lock

    @pytest.mark.asyncio
    async def test_acquire_async_concurrent(self, limiter):
        """Test concurrent async acquires."""
        results = []

        async def acquire_task(task_id):
            await limiter.acquire()
            results.append(task_id)

        # Run multiple concurrent acquires
        tasks = [acquire_task(i) for i in range(5)]
        await asyncio.gather(*tasks)

        assert len(results) == 5
        assert limiter._total_requests == 5

    @pytest.mark.asyncio
    async def test_acquire_async_waits_when_exhausted(self):
        """Test async acquire waits when tokens exhausted."""
        # Use slower limiter (60/min = 1/sec)
        limiter = RateLimiter(calls_per_minute=60, burst_limit=2, name="slow_async")

        # Exhaust tokens
        await limiter.acquire()
        await limiter.acquire()

        start_time = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start_time

        # Should have waited
        assert elapsed > 0.5


# =============================================================================
# Try Acquire Tests
# =============================================================================

class TestTryAcquire:
    """Tests for non-blocking try_acquire method."""

    def test_try_acquire_success_with_tokens(self, limiter):
        """Test try_acquire succeeds with available tokens."""
        result = limiter.try_acquire()

        assert result is True

    def test_try_acquire_fails_when_exhausted(self, limiter):
        """Test try_acquire fails when tokens exhausted."""
        # Exhaust all tokens
        for _ in range(limiter.burst_limit):
            limiter.try_acquire()

        result = limiter.try_acquire()

        assert result is False

    def test_try_acquire_does_not_wait(self):
        """Test try_acquire returns immediately without waiting."""
        limiter = RateLimiter(calls_per_minute=60, burst_limit=1, name="test")

        # Exhaust token
        limiter.try_acquire()

        start_time = time.monotonic()
        result = limiter.try_acquire()
        elapsed = time.monotonic() - start_time

        assert result is False
        assert elapsed < 0.01  # Should be nearly instant

    def test_try_acquire_increments_count_on_success(self, limiter):
        """Test try_acquire increments request count on success."""
        initial_requests = limiter._total_requests

        limiter.try_acquire()

        assert limiter._total_requests == initial_requests + 1

    def test_try_acquire_no_increment_on_failure(self, limiter):
        """Test try_acquire doesn't increment count on failure."""
        # Exhaust tokens
        for _ in range(limiter.burst_limit):
            limiter.try_acquire()

        count_after_exhaust = limiter._total_requests

        # This should fail
        limiter.try_acquire()

        assert limiter._total_requests == count_after_exhaust


# =============================================================================
# Burst Handling Tests
# =============================================================================

class TestBurstHandling:
    """Tests for burst handling behavior."""

    def test_burst_allows_rapid_requests(self):
        """Test burst limit allows rapid consecutive requests."""
        limiter = RateLimiter(calls_per_minute=60, burst_limit=10, name="test")

        # Should be able to make 10 rapid requests
        for _ in range(10):
            result = limiter.try_acquire()
            assert result is True

    def test_burst_exhausted_requires_wait(self):
        """Test waiting is required after burst exhausted."""
        limiter = RateLimiter(calls_per_minute=60, burst_limit=5, name="test")

        # Exhaust burst
        for _ in range(5):
            limiter.try_acquire()

        # Next should fail without waiting
        assert limiter.try_acquire() is False

    def test_burst_recovery_over_time(self, fast_limiter):
        """Test burst tokens recover over time."""
        # Exhaust all burst tokens
        for _ in range(fast_limiter.burst_limit):
            fast_limiter.try_acquire()

        assert fast_limiter.available_tokens < 1

        # Wait for some recovery
        time.sleep(0.1)

        # Should be able to acquire again
        assert fast_limiter.try_acquire() is True

    def test_burst_never_exceeds_limit(self, fast_limiter):
        """Test tokens never exceed burst limit even after long wait."""
        initial_tokens = fast_limiter.available_tokens
        assert initial_tokens == fast_limiter.burst_limit

        # Wait a long time
        time.sleep(0.2)

        # Tokens should still be capped at burst limit
        assert fast_limiter.available_tokens == fast_limiter.burst_limit

    def test_small_burst_with_high_rate(self):
        """Test small burst limit with high rate."""
        limiter = RateLimiter(calls_per_minute=6000, burst_limit=2, name="test")

        # Can only make 2 immediate requests
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False

        # But recovery is fast
        time.sleep(0.02)  # 6000/min = 100/sec, so ~2 tokens in 0.02 sec
        assert limiter.try_acquire() is True


# =============================================================================
# Statistics Tests
# =============================================================================

class TestStatistics:
    """Tests for rate limiter statistics."""

    def test_stats_initial_state(self, limiter):
        """Test initial statistics values."""
        stats = limiter.stats()

        assert stats['name'] == "test"
        assert stats['calls_per_minute'] == 600
        assert stats['burst_limit'] == 10
        assert stats['total_requests'] == 0
        assert stats['total_waits'] == 0
        assert stats['total_wait_time'] == 0
        assert stats['avg_wait_time'] == 0

    def test_stats_after_requests(self, limiter):
        """Test statistics after making requests."""
        limiter.acquire_sync()
        limiter.acquire_sync()
        limiter.acquire_sync()

        stats = limiter.stats()

        assert stats['total_requests'] == 3

    def test_stats_available_tokens(self, limiter):
        """Test available_tokens in stats."""
        stats = limiter.stats()

        assert stats['available_tokens'] == limiter.burst_limit

    def test_stats_average_wait_time(self, slow_limiter):
        """Test average wait time calculation."""
        # Exhaust tokens
        for _ in range(slow_limiter.burst_limit):
            slow_limiter.acquire_sync()

        # Force some waits
        slow_limiter.acquire_sync()

        stats = slow_limiter.stats()

        if stats['total_waits'] > 0:
            expected_avg = stats['total_wait_time'] / stats['total_waits']
            assert abs(stats['avg_wait_time'] - expected_avg) < 0.001


# =============================================================================
# Reset Tests
# =============================================================================

class TestReset:
    """Tests for rate limiter reset functionality."""

    def test_reset_restores_tokens(self, limiter):
        """Test reset restores tokens to burst limit."""
        # Exhaust tokens
        for _ in range(limiter.burst_limit):
            limiter.try_acquire()

        limiter.reset()

        assert limiter.available_tokens == limiter.burst_limit

    def test_reset_clears_statistics(self, limiter):
        """Test reset clears all statistics."""
        limiter.acquire_sync()
        limiter.acquire_sync()

        limiter.reset()

        assert limiter._total_requests == 0
        assert limiter._total_waits == 0
        assert limiter._total_wait_time == 0.0

    def test_reset_updates_timestamp(self, limiter):
        """Test reset updates last update timestamp."""
        old_timestamp = limiter._last_update

        time.sleep(0.01)
        limiter.reset()

        assert limiter._last_update > old_timestamp


# =============================================================================
# Decorator Tests
# =============================================================================

class TestLimitDecorator:
    """Tests for the limit decorator."""

    def test_sync_decorator_applies_rate_limit(self, limiter):
        """Test sync decorator applies rate limiting."""
        call_count = 0

        @limiter.limit
        def my_func():
            nonlocal call_count
            call_count += 1
            return "result"

        result = my_func()

        assert result == "result"
        assert call_count == 1
        assert limiter._total_requests == 1

    def test_sync_decorator_preserves_function_metadata(self, limiter):
        """Test decorator preserves function metadata."""
        @limiter.limit
        def documented_function():
            """This is a docstring."""
            pass

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a docstring."

    def test_sync_decorator_passes_arguments(self, limiter):
        """Test sync decorator passes arguments correctly."""
        @limiter.limit
        def func_with_args(a, b, c=None):
            return (a, b, c)

        result = func_with_args(1, 2, c=3)

        assert result == (1, 2, 3)

    @pytest.mark.asyncio
    async def test_async_decorator_applies_rate_limit(self, limiter):
        """Test async decorator applies rate limiting."""
        call_count = 0

        @limiter.limit
        async def my_async_func():
            nonlocal call_count
            call_count += 1
            return "async_result"

        result = await my_async_func()

        assert result == "async_result"
        assert call_count == 1
        assert limiter._total_requests == 1

    @pytest.mark.asyncio
    async def test_async_decorator_preserves_function_metadata(self, limiter):
        """Test async decorator preserves function metadata."""
        @limiter.limit
        async def documented_async():
            """Async docstring."""
            pass

        assert documented_async.__name__ == "documented_async"
        assert documented_async.__doc__ == "Async docstring."

    @pytest.mark.asyncio
    async def test_async_decorator_passes_arguments(self, limiter):
        """Test async decorator passes arguments correctly."""
        @limiter.limit
        async def async_with_args(x, y, z=None):
            return (x, y, z)

        result = await async_with_args("a", "b", z="c")

        assert result == ("a", "b", "c")


# =============================================================================
# AdaptiveRateLimiter Tests
# =============================================================================

class TestAdaptiveRateLimiter:
    """Tests for AdaptiveRateLimiter."""

    def test_create_adaptive_limiter(self, adaptive_limiter):
        """Test creating adaptive limiter."""
        assert adaptive_limiter.original_rate == 100
        assert adaptive_limiter.min_rate == 10
        assert adaptive_limiter.backoff_factor == 0.5
        assert adaptive_limiter.recovery_factor == 1.1

    def test_record_success_increments_counter(self, adaptive_limiter):
        """Test record_success increments success counter."""
        adaptive_limiter.record_success()

        assert adaptive_limiter._consecutive_successes == 1
        assert adaptive_limiter._consecutive_rate_limits == 0

    def test_record_success_resets_rate_limit_counter(self, adaptive_limiter):
        """Test record_success resets rate limit counter."""
        adaptive_limiter._consecutive_rate_limits = 5

        adaptive_limiter.record_success()

        assert adaptive_limiter._consecutive_rate_limits == 0

    def test_record_rate_limit_decreases_rate(self, adaptive_limiter):
        """Test record_rate_limit decreases rate."""
        original_rate = adaptive_limiter.calls_per_minute

        adaptive_limiter.record_rate_limit()

        expected_rate = int(original_rate * 0.5)
        assert adaptive_limiter.calls_per_minute == expected_rate

    def test_record_rate_limit_updates_calls_per_second(self, adaptive_limiter):
        """Test record_rate_limit updates calls_per_second."""
        adaptive_limiter.record_rate_limit()

        expected_cps = adaptive_limiter.calls_per_minute / 60.0
        assert adaptive_limiter.calls_per_second == expected_cps

    def test_rate_not_below_minimum(self, adaptive_limiter):
        """Test rate doesn't go below minimum."""
        # Multiple rate limits to drive rate down
        for _ in range(10):
            adaptive_limiter.record_rate_limit()

        assert adaptive_limiter.calls_per_minute >= adaptive_limiter.min_rate

    def test_rate_recovery_after_threshold_successes(self, adaptive_limiter):
        """Test rate increases after threshold successes."""
        # First reduce rate
        adaptive_limiter.record_rate_limit()
        reduced_rate = adaptive_limiter.calls_per_minute

        # Record enough successes to trigger recovery
        for _ in range(adaptive_limiter._recovery_threshold):
            adaptive_limiter.record_success()

        assert adaptive_limiter.calls_per_minute > reduced_rate

    def test_rate_recovery_capped_at_original(self, adaptive_limiter):
        """Test rate recovery doesn't exceed original rate."""
        original_rate = adaptive_limiter.original_rate

        # Many successes
        for _ in range(100):
            adaptive_limiter.record_success()

        assert adaptive_limiter.calls_per_minute <= original_rate

    def test_reset_to_original(self, adaptive_limiter):
        """Test reset_to_original restores original rate."""
        adaptive_limiter.record_rate_limit()
        adaptive_limiter.record_rate_limit()

        adaptive_limiter.reset_to_original()

        assert adaptive_limiter.calls_per_minute == adaptive_limiter.original_rate
        assert adaptive_limiter._consecutive_successes == 0
        assert adaptive_limiter._consecutive_rate_limits == 0


# =============================================================================
# retry_with_backoff Tests
# =============================================================================

class TestRetryWithBackoff:
    """Tests for retry_with_backoff decorator."""

    @pytest.mark.asyncio
    async def test_async_success_first_try(self):
        """Test async function succeeds on first try."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        async def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_func()

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_retries_on_failure(self):
        """Test async function retries on failure."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        async def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "success"

        result = await failing_then_success()

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_raises_after_max_retries(self):
        """Test async function raises after max retries."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fail")

        with pytest.raises(ValueError, match="always fail"):
            await always_fails()

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_only_catches_specified_exceptions(self):
        """Test only catches specified exception types."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        async def raises_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            await raises_type_error()

        # Should not retry for TypeError
        assert call_count == 1

    def test_sync_success_first_try(self):
        """Test sync function succeeds on first try."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()

        assert result == "success"
        assert call_count == 1

    def test_sync_retries_on_failure(self):
        """Test sync function retries on failure."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "sync_success"

        result = failing_then_success()

        assert result == "sync_success"
        assert call_count == 2

    def test_sync_raises_after_max_retries(self):
        """Test sync function raises after max retries."""
        call_count = 0

        @retry_with_backoff(max_retries=2, base_delay=0.01, exceptions=(RuntimeError,))
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("oops")

        with pytest.raises(RuntimeError, match="oops"):
            always_fails()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_backoff_respects_max_delay(self):
        """Test backoff delay is capped at max_delay."""
        call_count = 0
        wait_times = []

        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            wait_times.append(duration)
            await original_sleep(0.001)  # Minimal actual wait

        @retry_with_backoff(
            max_retries=5,
            base_delay=1.0,
            max_delay=2.0,
            backoff_factor=10.0,
            exceptions=(ValueError,)
        )
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with patch('asyncio.sleep', mock_sleep):
            with pytest.raises(ValueError):
                await always_fails()

        # All wait times should be <= max_delay
        for wait in wait_times:
            assert wait <= 2.0


# =============================================================================
# Global Limiter Factory Tests
# =============================================================================

class TestGlobalLimiterFactory:
    """Tests for global limiter factory functions."""

    def test_get_limiter_creates_new(self):
        """Test get_limiter creates new limiter."""
        limiter = get_limiter("test_provider", calls_per_minute=50)

        assert limiter is not None
        assert limiter.name == "test_provider"
        assert limiter.calls_per_minute == 50

    def test_get_limiter_reuses_existing(self):
        """Test get_limiter reuses existing limiter."""
        limiter1 = get_limiter("test_provider", calls_per_minute=100)
        limiter2 = get_limiter("test_provider", calls_per_minute=200)  # Different rate

        assert limiter1 is limiter2
        # First limiter's rate is preserved
        assert limiter2.calls_per_minute == 100

    def test_get_limiter_different_providers(self):
        """Test different providers get different limiters."""
        limiter1 = get_limiter("provider_a")
        limiter2 = get_limiter("provider_b")

        assert limiter1 is not limiter2

    def test_get_limiter_adaptive_true(self):
        """Test get_limiter with adaptive=True."""
        limiter = get_limiter("adaptive_provider", adaptive=True)

        assert isinstance(limiter, AdaptiveRateLimiter)

    def test_get_limiter_adaptive_false(self):
        """Test get_limiter with adaptive=False."""
        limiter = get_limiter("non_adaptive", adaptive=False)

        assert isinstance(limiter, RateLimiter)
        assert not isinstance(limiter, AdaptiveRateLimiter)

    def test_get_marketdata_limiter(self):
        """Test get_marketdata_limiter factory."""
        limiter = get_marketdata_limiter()

        assert limiter.name == "marketdata"
        assert limiter.calls_per_minute == 100
        assert isinstance(limiter, AdaptiveRateLimiter)

    def test_get_yahoo_limiter(self):
        """Test get_yahoo_limiter factory."""
        limiter = get_yahoo_limiter()

        assert limiter.name == "yahoo"
        assert limiter.calls_per_minute == 120
        assert not isinstance(limiter, AdaptiveRateLimiter)


# =============================================================================
# Thread Safety Tests
# =============================================================================

class TestThreadSafety:
    """Tests for thread safety of rate limiter."""

    def test_concurrent_sync_acquires(self, fast_limiter):
        """Test concurrent sync acquires from multiple threads."""
        results = []
        errors = []

        def acquire_task():
            try:
                for _ in range(10):
                    fast_limiter.acquire_sync()
                    results.append(True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=acquire_task) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 50

    def test_concurrent_try_acquires(self, limiter):
        """Test concurrent try_acquires from multiple threads."""
        results = []

        def try_acquire_task():
            for _ in range(5):
                result = limiter.try_acquire()
                results.append(result)

        threads = [threading.Thread(target=try_acquire_task) for _ in range(3)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly burst_limit successful acquires
        successful = sum(1 for r in results if r)
        assert successful == limiter.burst_limit

    def test_async_lock_creation_thread_safe(self):
        """Test async lock creation is thread-safe."""
        limiter = RateLimiter(calls_per_minute=100, name="test")
        locks_created = []

        def create_lock():
            lock = limiter._get_async_lock()
            locks_created.append(lock)

        threads = [threading.Thread(target=create_lock) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get the same lock
        assert all(lock is locks_created[0] for lock in locks_created)


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_burst_limit(self):
        """Test behavior with very low rate (effectively zero burst)."""
        limiter = RateLimiter(calls_per_minute=1, burst_limit=1, name="test")

        # Can make one request
        assert limiter.try_acquire() is True
        # Second should fail
        assert limiter.try_acquire() is False

    def test_very_high_rate(self):
        """Test behavior with very high rate."""
        limiter = RateLimiter(calls_per_minute=60000, burst_limit=100, name="test")

        # Should be able to make many rapid requests
        for _ in range(100):
            assert limiter.try_acquire() is True

    def test_available_tokens_thread_safe(self, limiter):
        """Test available_tokens property is thread-safe."""
        tokens_values = []

        def read_tokens():
            for _ in range(100):
                tokens_values.append(limiter.available_tokens)

        threads = [threading.Thread(target=read_tokens) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not have any errors
        assert len(tokens_values) == 500

    def test_stats_thread_safe(self, limiter):
        """Test stats() is thread-safe."""
        stats_results = []

        def read_stats():
            for _ in range(50):
                stats_results.append(limiter.stats())

        threads = [threading.Thread(target=read_stats) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(stats_results) == 250

    def test_reset_while_waiting(self, slow_limiter):
        """Test reset doesn't break waiting threads."""
        # This is a potential race condition test
        slow_limiter.try_acquire()
        slow_limiter.try_acquire()  # Exhaust

        def reset_after_delay():
            time.sleep(0.1)
            slow_limiter.reset()

        reset_thread = threading.Thread(target=reset_after_delay)
        reset_thread.start()

        # This should wait but not crash even with reset
        slow_limiter.acquire_sync()

        reset_thread.join()


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests combining multiple features."""

    @pytest.mark.asyncio
    async def test_mixed_sync_async_usage(self, limiter):
        """Test mixing sync and async acquires."""
        # Sync acquire
        limiter.acquire_sync()
        limiter.acquire_sync()

        # Async acquire
        await limiter.acquire()
        await limiter.acquire()

        assert limiter._total_requests == 4

    def test_adaptive_limiter_full_workflow(self):
        """Test full workflow with adaptive limiter."""
        limiter = AdaptiveRateLimiter(
            calls_per_minute=100,
            min_rate=10,
            backoff_factor=0.5,
            recovery_factor=1.5,
            name="workflow"
        )

        # Normal operation
        for _ in range(5):
            limiter.acquire_sync()
            limiter.record_success()

        # Simulate rate limiting
        limiter.record_rate_limit()
        reduced_rate = limiter.calls_per_minute
        assert reduced_rate < 100

        # Recover
        for _ in range(limiter._recovery_threshold):
            limiter.record_success()

        assert limiter.calls_per_minute > reduced_rate

        # Reset
        limiter.reset_to_original()
        assert limiter.calls_per_minute == 100

    @pytest.mark.asyncio
    async def test_decorator_with_rate_limit_exhaustion(self):
        """Test decorator behavior when rate limit is exhausted."""
        limiter = RateLimiter(calls_per_minute=60, burst_limit=2, name="test")

        call_times = []

        @limiter.limit
        async def tracked_call():
            call_times.append(time.monotonic())
            return "done"

        # These should all complete but with delays
        for _ in range(3):
            await tracked_call()

        assert len(call_times) == 3

        # Third call should have been delayed
        time_between_2_and_3 = call_times[2] - call_times[1]
        assert time_between_2_and_3 > 0.5  # Should have waited


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
