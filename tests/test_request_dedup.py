# OptionPlay - Request Deduplication Tests
# =========================================

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.utils.request_dedup import RequestDeduplicator, get_request_deduplicator, reset_request_deduplicator


class TestRequestDeduplicator:
    """Tests for RequestDeduplicator class."""

    @pytest.fixture
    def dedup(self):
        """Create a fresh deduplicator for each test."""
        return RequestDeduplicator()

    @pytest.mark.asyncio
    async def test_single_request_executes(self, dedup):
        """Single request should execute normally."""
        mock_coro = AsyncMock(return_value="result")

        result = await dedup.deduplicated_call(
            key="test:1",
            coro_factory=mock_coro
        )

        assert result == "result"
        mock_coro.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_identical_requests_deduplicated(self, dedup):
        """Concurrent identical requests should be deduplicated."""
        call_count = 0

        async def slow_fetch():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate slow API call
            return f"result_{call_count}"

        # Start 5 concurrent requests for the same key
        tasks = [
            dedup.deduplicated_call(key="test:same", coro_factory=slow_fetch)
            for _ in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # All should get the same result
        assert all(r == "result_1" for r in results)

        # Only ONE actual call should have been made
        assert call_count == 1

        # Stats should reflect deduplication
        stats = dedup.stats()
        assert stats["total_requests"] == 5
        assert stats["actual_calls"] == 1
        assert stats["deduplicated"] == 4
        assert stats["dedup_rate_percent"] == 80.0

    @pytest.mark.asyncio
    async def test_different_keys_not_deduplicated(self, dedup):
        """Different keys should not be deduplicated."""
        call_count = 0

        def make_fetch(key_id):
            async def fetch():
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.05)
                return f"result_for_key{key_id}"
            return fetch

        # Start concurrent requests for DIFFERENT keys
        tasks = [
            dedup.deduplicated_call(key=f"test:key{i}", coro_factory=make_fetch(i))
            for i in range(3)
        ]

        results = await asyncio.gather(*tasks)

        # Each should get different result (identified by key)
        assert "result_for_key0" in results
        assert "result_for_key1" in results
        assert "result_for_key2" in results

        # Three actual calls
        assert call_count == 3

        stats = dedup.stats()
        assert stats["actual_calls"] == 3
        assert stats["deduplicated"] == 0

    @pytest.mark.asyncio
    async def test_sequential_requests_not_deduplicated(self, dedup):
        """Sequential (non-concurrent) requests should not be deduplicated."""
        call_count = 0

        async def fetch():
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        # Sequential requests (not concurrent)
        result1 = await dedup.deduplicated_call(key="test:seq", coro_factory=fetch)
        result2 = await dedup.deduplicated_call(key="test:seq", coro_factory=fetch)

        # Both should execute separately
        assert result1 == "result_1"
        assert result2 == "result_2"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_exception_propagates_to_all_waiters(self, dedup):
        """Exception should propagate to all waiting requests."""

        async def failing_fetch():
            await asyncio.sleep(0.1)
            raise ValueError("API Error")

        # Start concurrent requests
        tasks = [
            dedup.deduplicated_call(key="test:fail", coro_factory=failing_fetch)
            for _ in range(3)
        ]

        # All should raise the same exception
        with pytest.raises(ValueError, match="API Error"):
            await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_in_flight_cleared_after_completion(self, dedup):
        """In-flight request should be cleared after completion."""

        async def fetch():
            return "done"

        await dedup.deduplicated_call(key="test:clear", coro_factory=fetch)

        stats = dedup.stats()
        assert stats["in_flight"] == 0

    def test_stats_initial_values(self, dedup):
        """Initial stats should be zeros."""
        stats = dedup.stats()

        assert stats["total_requests"] == 0
        assert stats["actual_calls"] == 0
        assert stats["deduplicated"] == 0
        assert stats["dedup_rate_percent"] == 0
        assert stats["in_flight"] == 0

    def test_reset_stats(self, dedup):
        """Reset should clear statistics."""
        dedup._total_requests = 100
        dedup._deduplicated = 50
        dedup._actual_calls = 50

        dedup.reset_stats()

        stats = dedup.stats()
        assert stats["total_requests"] == 0
        assert stats["actual_calls"] == 0
        assert stats["deduplicated"] == 0


class TestSingleton:
    """Tests for singleton functionality."""

    def test_get_request_deduplicator_returns_same_instance(self):
        """get_request_deduplicator should return the same instance."""
        reset_request_deduplicator()

        dedup1 = get_request_deduplicator()
        dedup2 = get_request_deduplicator()

        assert dedup1 is dedup2

    def test_reset_creates_new_instance(self):
        """reset should allow creating a new instance."""
        dedup1 = get_request_deduplicator()
        reset_request_deduplicator()
        dedup2 = get_request_deduplicator()

        assert dedup1 is not dedup2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
