# OptionPlay - Rate Limiter Tests
# =================================
# Tests für src/utils/rate_limiter.py

import pytest
import asyncio
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    AdaptiveRateLimiter,
    retry_with_backoff,
    get_limiter,
    get_marketdata_limiter,
    get_tradier_limiter,
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
    """Tests für RateLimitConfig dataclass."""

    def test_default_config(self):
        """Test: Default Config Werte."""
        config = RateLimitConfig()

        assert config.calls_per_minute == 100
        assert config.calls_per_second == 10
        assert config.burst_limit == 5
        assert config.backoff_base == 1.0

    def test_custom_config(self):
        """Test: Custom Config."""
        config = RateLimitConfig(
            calls_per_minute=200,
            calls_per_second=20,
            burst_limit=10
        )

        assert config.calls_per_minute == 200
        assert config.calls_per_second == 20


# =============================================================================
# RateLimiter Basic Tests
# =============================================================================

class TestRateLimiterBasic:
    """Basic Tests für RateLimiter."""

    def test_create_limiter(self, limiter):
        """Test: Limiter erstellen."""
        assert limiter.name == "test"
        assert limiter.calls_per_minute == 600
        assert limiter.burst_limit == 10

    def test_initial_tokens(self, limiter):
        """Test: Initiale Tokens verfügbar."""
        assert limiter.available_tokens == 10

    def test_acquire_sync_reduces_tokens(self, limiter):
        """Test: acquire_sync reduziert Tokens."""
        initial = limiter.available_tokens
        limiter.acquire_sync()
        assert limiter.available_tokens < initial

    def test_try_acquire_success(self, limiter):
        """Test: try_acquire erfolgreich."""
        result = limiter.try_acquire()
        assert result == True

    def test_try_acquire_exhausted(self, limiter):
        """Test: try_acquire wenn Tokens erschöpft."""
        # Exhaust all tokens
        for _ in range(limiter.burst_limit):
            limiter.try_acquire()

        # Next should fail
        result = limiter.try_acquire()
        assert result == False


# =============================================================================
# RateLimiter Async Tests
# =============================================================================

class TestRateLimiterAsync:
    """Async Tests für RateLimiter."""

    @pytest.mark.asyncio
    async def test_acquire_async(self, limiter):
        """Test: Async acquire."""
        wait_time = await limiter.acquire()

        assert isinstance(wait_time, float)

    @pytest.mark.asyncio
    async def test_multiple_async_acquires(self, limiter):
        """Test: Mehrere async acquires."""
        for _ in range(5):
            await limiter.acquire()

        # Still has tokens
        assert limiter.available_tokens > 0


# =============================================================================
# RateLimiter Stats Tests
# =============================================================================

class TestRateLimiterStats:
    """Tests für RateLimiter Statistiken."""

    def test_stats_initial(self, limiter):
        """Test: Initiale Statistiken."""
        stats = limiter.stats()

        assert stats['name'] == "test"
        assert stats['total_requests'] == 0
        assert stats['total_waits'] == 0

    def test_stats_after_requests(self, limiter):
        """Test: Statistiken nach Requests."""
        limiter.acquire_sync()
        limiter.acquire_sync()

        stats = limiter.stats()

        assert stats['total_requests'] == 2

    def test_reset(self, limiter):
        """Test: Reset setzt Statistiken zurück."""
        limiter.acquire_sync()
        limiter.acquire_sync()

        limiter.reset()

        stats = limiter.stats()
        assert stats['total_requests'] == 0


# =============================================================================
# RateLimiter Decorator Tests
# =============================================================================

class TestRateLimiterDecorator:
    """Tests für Rate Limiter Decorator."""

    def test_sync_decorator(self, limiter):
        """Test: Sync Decorator."""
        call_count = 0

        @limiter.limit
        def my_func():
            nonlocal call_count
            call_count += 1
            return "result"

        result = my_func()

        assert result == "result"
        assert call_count == 1
        assert limiter.stats()['total_requests'] == 1

    @pytest.mark.asyncio
    async def test_async_decorator(self, limiter):
        """Test: Async Decorator."""
        call_count = 0

        @limiter.limit
        async def my_async_func():
            nonlocal call_count
            call_count += 1
            return "async_result"

        result = await my_async_func()

        assert result == "async_result"
        assert call_count == 1


# =============================================================================
# AdaptiveRateLimiter Tests
# =============================================================================

class TestAdaptiveRateLimiter:
    """Tests für AdaptiveRateLimiter."""

    def test_create_adaptive(self, adaptive_limiter):
        """Test: Adaptive Limiter erstellen."""
        assert adaptive_limiter.original_rate == 100
        assert adaptive_limiter.min_rate == 10

    def test_record_success(self, adaptive_limiter):
        """Test: Success Recording."""
        adaptive_limiter.record_success()

        assert adaptive_limiter._consecutive_successes == 1
        assert adaptive_limiter._consecutive_rate_limits == 0

    def test_record_rate_limit_decreases_rate(self, adaptive_limiter):
        """Test: Rate Limit reduziert Rate."""
        original = adaptive_limiter.calls_per_minute

        adaptive_limiter.record_rate_limit()

        # Rate should be reduced by backoff_factor (0.5)
        expected = int(original * 0.5)
        assert adaptive_limiter.calls_per_minute == expected

    def test_rate_not_below_minimum(self, adaptive_limiter):
        """Test: Rate nicht unter Minimum."""
        # Multiple rate limits
        for _ in range(10):
            adaptive_limiter.record_rate_limit()

        assert adaptive_limiter.calls_per_minute >= adaptive_limiter.min_rate

    def test_rate_recovery(self, adaptive_limiter):
        """Test: Rate Recovery nach Erfolgen."""
        # First reduce rate
        adaptive_limiter.record_rate_limit()
        reduced_rate = adaptive_limiter.calls_per_minute

        # Many successes
        for _ in range(adaptive_limiter._recovery_threshold):
            adaptive_limiter.record_success()

        # Rate should increase
        assert adaptive_limiter.calls_per_minute > reduced_rate

    def test_reset_to_original(self, adaptive_limiter):
        """Test: Reset auf Original-Rate."""
        adaptive_limiter.record_rate_limit()
        adaptive_limiter.reset_to_original()

        assert adaptive_limiter.calls_per_minute == adaptive_limiter.original_rate


# =============================================================================
# retry_with_backoff Tests
# =============================================================================

class TestRetryWithBackoff:
    """Tests für retry_with_backoff Decorator."""

    @pytest.mark.asyncio
    async def test_retry_success_first_try(self):
        """Test: Erfolg beim ersten Versuch."""
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
    async def test_retry_after_failure(self):
        """Test: Retry nach Fehler."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        async def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "success"

        result = await failing_then_success()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_max_retries_exceeded(self):
        """Test: Max Retries überschritten."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fail")

        with pytest.raises(ValueError):
            await always_fails()

        assert call_count == 3

    def test_retry_sync_function(self):
        """Test: Retry mit sync Funktion."""
        call_count = 0

        @retry_with_backoff(max_retries=2, base_delay=0.01, exceptions=(ValueError,))
        def sync_failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "sync_success"

        result = sync_failing_then_success()

        assert result == "sync_success"
        assert call_count == 2


# =============================================================================
# Global Limiter Factory Tests
# =============================================================================

class TestGlobalLimiterFactory:
    """Tests für globale Limiter-Factory Funktionen."""

    def test_get_limiter_creates_new(self):
        """Test: get_limiter erstellt neuen Limiter."""
        limiter = get_limiter("test_provider", calls_per_minute=50)

        assert limiter is not None
        assert limiter.name == "test_provider"
        assert limiter.calls_per_minute == 50

    def test_get_limiter_reuses_existing(self):
        """Test: get_limiter wiederverwendet existierenden."""
        limiter1 = get_limiter("test_provider")
        limiter2 = get_limiter("test_provider")

        assert limiter1 is limiter2

    def test_get_limiter_adaptive_flag(self):
        """Test: Adaptive Flag."""
        adaptive = get_limiter("adaptive_provider", adaptive=True)
        non_adaptive = get_limiter("non_adaptive", adaptive=False)

        assert isinstance(adaptive, AdaptiveRateLimiter)
        assert isinstance(non_adaptive, RateLimiter)
        assert not isinstance(non_adaptive, AdaptiveRateLimiter)

    def test_get_marketdata_limiter(self):
        """Test: Marketdata Limiter."""
        limiter = get_marketdata_limiter()

        assert limiter.name == "marketdata"
        assert limiter.calls_per_minute == 100
        assert isinstance(limiter, AdaptiveRateLimiter)

    def test_get_tradier_limiter(self):
        """Test: Tradier Limiter."""
        limiter = get_tradier_limiter()

        assert limiter.name == "tradier"
        assert limiter.calls_per_minute == 120

    def test_get_yahoo_limiter(self):
        """Test: Yahoo Limiter."""
        limiter = get_yahoo_limiter()

        assert limiter.name == "yahoo"
        assert not isinstance(limiter, AdaptiveRateLimiter)


# =============================================================================
# Token Refill Tests
# =============================================================================

class TestTokenRefill:
    """Tests für Token Refill Mechanismus."""

    def test_tokens_refill_over_time(self):
        """Test: Tokens werden über Zeit aufgefüllt."""
        # High rate limiter for fast refill
        limiter = RateLimiter(calls_per_minute=6000, burst_limit=5, name="fast")

        # Exhaust tokens
        for _ in range(5):
            limiter.try_acquire()

        assert limiter.available_tokens < 1

        # Wait a bit for refill
        time.sleep(0.1)

        # Tokens should have refilled
        assert limiter.available_tokens > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
