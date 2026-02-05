# OptionPlay - Request Deduplication
# ====================================
"""
Deduplicates concurrent identical requests to reduce API calls.

When multiple callers request the same data simultaneously, only one
actual API call is made and all callers receive the same result.

Usage:
    dedup = RequestDeduplicator()

    # Multiple concurrent calls to fetch AAPL quote
    # Only ONE actual API call is made
    result = await dedup.deduplicated_call(
        key="quote:AAPL",
        coro_factory=lambda: provider.get_quote("AAPL")
    )
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RequestDeduplicator:
    """
    Deduplicates concurrent identical async requests.

    When multiple callers request the same key simultaneously:
    1. First caller starts the actual request
    2. Subsequent callers wait for the first request to complete
    3. All callers receive the same result

    This prevents redundant API calls when the same data is requested
    multiple times in parallel (e.g., during batch operations).
    """

    def __init__(self):
        # Maps key -> (Future, timestamp)
        self._in_flight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

        # Statistics
        self._total_requests = 0
        self._deduplicated = 0
        self._actual_calls = 0

    async def deduplicated_call(
        self,
        key: str,
        coro_factory: Callable[[], Coroutine[Any, Any, T]],
    ) -> T:
        """
        Execute a request with deduplication.

        If a request with the same key is already in flight, wait for
        its result instead of making a new request.

        Args:
            key: Unique identifier for this request (e.g., "quote:AAPL")
            coro_factory: Factory function that creates the coroutine to execute
                         (must be a factory, not a coroutine, to avoid starting it prematurely)

        Returns:
            Result of the request

        Raises:
            Exception: If the underlying request fails
        """
        self._total_requests += 1

        async with self._lock:
            # Check if request is already in flight
            if key in self._in_flight:
                future = self._in_flight[key]
                self._deduplicated += 1
                logger.debug(f"Dedup HIT: {key} (waiting for in-flight request)")
            else:
                # Create new future and start request
                future = asyncio.get_running_loop().create_future()
                self._in_flight[key] = future
                self._actual_calls += 1

                # Start the actual request (outside the lock)
                asyncio.create_task(self._execute_request(key, coro_factory, future))
                logger.debug(f"Dedup MISS: {key} (starting new request)")

        # Wait for result (whether we started it or someone else did)
        try:
            return await future
        except Exception:
            # Re-raise the exception
            raise

    async def _execute_request(
        self,
        key: str,
        coro_factory: Callable[[], Coroutine[Any, Any, T]],
        future: asyncio.Future,
    ) -> None:
        """Execute the actual request and set the result on the future."""
        try:
            result = await coro_factory()
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)
        finally:
            # Remove from in-flight map
            async with self._lock:
                if key in self._in_flight:
                    del self._in_flight[key]

    def stats(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        dedup_rate = (
            (self._deduplicated / self._total_requests * 100)
            if self._total_requests > 0 else 0
        )
        return {
            "total_requests": self._total_requests,
            "actual_calls": self._actual_calls,
            "deduplicated": self._deduplicated,
            "dedup_rate_percent": round(dedup_rate, 1),
            "in_flight": len(self._in_flight),
        }

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._total_requests = 0
        self._deduplicated = 0
        self._actual_calls = 0


# Singleton instance
_deduplicator: Optional[RequestDeduplicator] = None


def get_request_deduplicator() -> RequestDeduplicator:
    """
    Get the global request deduplicator instance.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.
    """
    try:
        from .deprecation import warn_singleton_usage
        warn_singleton_usage("get_request_deduplicator", "ServiceContainer.request_deduplicator")
    except ImportError:
        pass

    global _deduplicator
    if _deduplicator is None:
        _deduplicator = RequestDeduplicator()
        logger.info("Request deduplicator initialized")
    return _deduplicator


def reset_request_deduplicator() -> None:
    """Reset the global deduplicator (for testing)."""
    global _deduplicator
    _deduplicator = None
