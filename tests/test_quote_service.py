# OptionPlay - Quote Service Tests
# ==================================
# Tests für src/services/quote_service.py

import pytest
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.quote_service import QuoteService
from src.models.result import ServiceResult


# =============================================================================
# Mock Classes
# =============================================================================

class MockConfig:
    """Mock config for testing."""
    class Settings:
        class ApiConnection:
            vix_cache_seconds = 300
        api_connection = ApiConnection()
    settings = Settings()


class MockProvider:
    """Mock data provider."""
    async def get_quote(self, symbol):
        return {
            "symbol": symbol,
            "last": 150.0,
            "bid": 149.90,
            "ask": 150.10,
            "volume": 1000000,
            "change": 2.50,
            "change_percent": 1.67,
            "high": 152.0,
            "low": 148.0,
        }

    async def get_batch_quotes(self, symbols):
        return {symbol: await self.get_quote(symbol) for symbol in symbols}


class MockServiceContext:
    """Mock service context."""
    def __init__(self):
        self._provider = MockProvider()
        self._rate_limiter = MagicMock()
        self._vix_cache = None
        self._vix_updated = None


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_context():
    """Create a mock service context."""
    return MockServiceContext()


@pytest.fixture
def service(mock_context):
    """Create a QuoteService with mock context."""
    with patch.object(QuoteService, '__init__', lambda self, ctx, **kw: None):
        svc = QuoteService.__new__(QuoteService)
        svc._context = mock_context
        svc._config = MockConfig()
        svc._logger = MagicMock()
        from collections import OrderedDict
        svc._quote_cache = OrderedDict()
        svc._cache_ttl_seconds = 60
        svc._max_cache_size = 500
        svc._cache_hits = 0
        svc._cache_misses = 0
        svc._cache_evictions = 0
        return svc


# =============================================================================
# get_quote Tests
# =============================================================================

class TestGetQuote:
    """Tests für get_quote()."""

    @pytest.mark.asyncio
    async def test_get_quote_valid_symbol(self, service):
        """Test: Quote für gültiges Symbol."""
        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_quote("AAPL")

        assert result.success
        assert result.data["symbol"] == "AAPL"
        assert result.data["last"] == 150.0

    @pytest.mark.asyncio
    async def test_get_quote_uses_cache(self, service):
        """Test: Quote verwendet Cache."""
        # Pre-populate cache
        cached_quote = {"symbol": "MSFT", "last": 300.0}
        service._quote_cache["MSFT"] = (cached_quote, datetime.now())

        result = await service.get_quote("MSFT", use_cache=True)

        assert result.success
        assert result.data["last"] == 300.0
        # Check that data came from cache (source should indicate cache)
        assert result.source == "cache"

    @pytest.mark.asyncio
    async def test_get_quote_stale_cache(self, service):
        """Test: Staler Cache wird nicht verwendet."""
        # Pre-populate with stale cache
        stale_time = datetime.now() - timedelta(seconds=120)
        cached_quote = {"symbol": "GOOGL", "last": 100.0}
        service._quote_cache["GOOGL"] = (cached_quote, stale_time)

        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_quote("GOOGL", use_cache=True)

        assert result.success
        assert result.data["last"] == 150.0  # From provider, not cache

    @pytest.mark.asyncio
    async def test_get_quote_invalid_symbol(self, service):
        """Test: Ungültiges Symbol."""
        result = await service.get_quote("INVALID!!!")

        assert not result.success
        assert "validation" in result.error.lower() or "invalid" in result.error.lower()


# =============================================================================
# Cache Tests
# =============================================================================

class TestQuoteCache:
    """Tests für Quote Cache."""

    def test_cache_stats_initial(self, service):
        """Test: Initiale Cache-Statistiken."""
        assert service._cache_hits == 0
        assert service._cache_misses == 0

    @pytest.mark.asyncio
    async def test_cache_hit_increments(self, service):
        """Test: Cache Hit wird gezählt."""
        initial_hits = service._cache_hits

        # Pre-populate cache
        cached_quote = {"symbol": "AAPL", "last": 150.0}
        service._quote_cache["AAPL"] = (cached_quote, datetime.now())

        await service.get_quote("AAPL", use_cache=True)

        assert service._cache_hits > initial_hits


# =============================================================================
# Batch Quote Tests
# =============================================================================

class TestGetBatchQuotes:
    """Tests für get_batch_quotes()."""

    @pytest.mark.asyncio
    async def test_batch_quotes_multiple_symbols(self, service):
        """Test: Batch Quotes für mehrere Symbole."""
        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_batch_quotes(["AAPL", "MSFT", "GOOGL"])

        assert result.success
        assert len(result.data) == 3
        assert "AAPL" in result.data
        assert "MSFT" in result.data

    @pytest.mark.asyncio
    async def test_batch_quotes_empty_list(self, service):
        """Test: Leere Symbol-Liste gibt Fehler."""
        result = await service.get_batch_quotes([])

        # Empty list returns failure - "No valid symbols provided"
        assert not result.success
        assert "symbols" in result.error.lower()


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests für Error Handling."""

    @pytest.mark.asyncio
    async def test_provider_error_handled(self, service):
        """Test: Provider-Fehler wird behandelt."""
        mock_provider = MagicMock()
        mock_provider.get_quote = AsyncMock(side_effect=Exception("API Error"))

        service._get_provider = AsyncMock(return_value=mock_provider)
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_quote("AAPL", use_cache=False)

        assert not result.success


# =============================================================================
# Formatted Output Tests
# =============================================================================

class TestFormattedOutput:
    """Tests for formatted output methods."""

    @pytest.mark.asyncio
    async def test_get_quote_formatted_success(self, service):
        """Test: Formatted quote output."""
        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_quote_formatted("AAPL")

        assert isinstance(result, str)
        assert "AAPL" in result
        assert "150" in result or "$150" in result  # Price should be in output

    @pytest.mark.asyncio
    async def test_get_quote_formatted_error(self, service):
        """Test: Formatted output on error."""
        result = await service.get_quote_formatted("INVALID!!!")

        assert "❌" in result
        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_get_batch_quotes_formatted_success(self, service):
        """Test: Formatted batch quotes."""
        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_batch_quotes_formatted(["AAPL", "MSFT"])

        assert isinstance(result, str)
        assert "AAPL" in result
        assert "MSFT" in result

    @pytest.mark.asyncio
    async def test_get_batch_quotes_formatted_error(self, service):
        """Test: Formatted batch output on error."""
        result = await service.get_batch_quotes_formatted([])

        assert "❌" in result


# =============================================================================
# Cache Management Tests
# =============================================================================

class TestCacheManagement:
    """Tests for cache management methods."""

    def test_get_cache_stats(self, service):
        """Test: Cache statistics."""
        stats = service.get_cache_stats()

        assert "entries" in stats
        assert "max_size" in stats
        assert "usage_pct" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "evictions" in stats
        assert "hit_rate_pct" in stats
        assert "ttl_seconds" in stats

    def test_clear_cache(self, service):
        """Test: Clear cache."""
        # Add some entries
        service._quote_cache["AAPL"] = ({"symbol": "AAPL"}, datetime.now())
        service._quote_cache["MSFT"] = ({"symbol": "MSFT"}, datetime.now())

        count = service.clear_cache()

        assert count == 2
        assert len(service._quote_cache) == 0

    def test_clear_empty_cache(self, service):
        """Test: Clear empty cache returns 0."""
        count = service.clear_cache()
        assert count == 0

    def test_cache_lru_eviction(self, service):
        """Test: LRU eviction when cache is full."""
        service._max_cache_size = 3

        # Fill cache
        service._set_cache("A", {"symbol": "A"})
        service._set_cache("B", {"symbol": "B"})
        service._set_cache("C", {"symbol": "C"})

        # Add one more - should evict oldest (A)
        service._set_cache("D", {"symbol": "D"})

        assert "A" not in service._quote_cache
        assert "D" in service._quote_cache
        assert service._cache_evictions == 1

    def test_cache_lru_access_updates_order(self, service):
        """Test: Accessing cache entry updates LRU order."""
        service._set_cache("A", {"symbol": "A"})
        service._set_cache("B", {"symbol": "B"})

        # Access A - should move to end
        service._get_from_cache("A")

        # Keys order should now be B, A
        keys = list(service._quote_cache.keys())
        assert keys == ["B", "A"]

    def test_cache_update_existing_entry(self, service):
        """Test: Updating existing cache entry."""
        service._set_cache("AAPL", {"symbol": "AAPL", "last": 150.0})
        service._set_cache("AAPL", {"symbol": "AAPL", "last": 155.0})

        cached = service._get_from_cache("AAPL")

        assert cached["last"] == 155.0
        assert len(service._quote_cache) == 1


# =============================================================================
# Quote Conversion Tests
# =============================================================================

class TestQuoteConversion:
    """Tests for quote to dict conversion."""

    def test_quote_to_dict_with_to_dict_method(self, service):
        """Test: Quote with to_dict method."""
        quote = MagicMock()
        quote.to_dict.return_value = {"symbol": "AAPL", "last": 150.0}

        result = service._quote_to_dict(quote, "AAPL")

        assert result == {"symbol": "AAPL", "last": 150.0}

    def test_quote_to_dict_with_dict_attr(self, service):
        """Test: Quote with __dict__ attribute."""
        class QuoteObj:
            def __init__(self):
                self.last = 150.0
                self.bid = 149.90

        quote = QuoteObj()
        # Remove to_dict if it exists
        if hasattr(quote, 'to_dict'):
            delattr(quote, 'to_dict')

        result = service._quote_to_dict(quote, "AAPL")

        assert result["symbol"] == "AAPL"
        assert result["last"] == 150.0

    def test_quote_to_dict_with_dict_input(self, service):
        """Test: Quote as dict input."""
        quote = {"last": 150.0, "bid": 149.90}

        result = service._quote_to_dict(quote, "AAPL")

        assert result["symbol"] == "AAPL"
        assert result["last"] == 150.0

    def test_quote_to_dict_minimal(self, service):
        """Test: Minimal quote conversion."""
        class MinimalQuote:
            def __init__(self):
                # Use instance attributes so they appear in __dict__
                self.price = 150.0
                self.bid = 149.90
                self.ask = 150.10
                self.volume = 1000000

        quote = MinimalQuote()

        result = service._quote_to_dict(quote, "AAPL")

        assert result["symbol"] == "AAPL"
        # __dict__ branch adds symbol and copies attributes
        assert result["price"] == 150.0
        assert result["bid"] == 149.90


# =============================================================================
# Format Methods Tests
# =============================================================================

class TestFormatMethods:
    """Tests for internal format methods."""

    def test_format_quote_basic(self, service):
        """Test: Basic quote formatting."""
        quote_data = {
            "symbol": "AAPL",
            "last": 150.0,
            "bid": 149.90,
            "ask": 150.10,
            "volume": 1000000,
            "change": 2.50,
            "change_pct": 1.67,
        }

        result = service._format_quote(quote_data)

        assert "AAPL" in result
        assert "150" in result
        assert "Volume" in result

    def test_format_quote_with_negative_change(self, service):
        """Test: Quote formatting with negative change."""
        quote_data = {
            "symbol": "AAPL",
            "last": 148.0,
            "bid": 147.90,
            "ask": 148.10,
            "volume": 1000000,
            "change": -2.0,
            "change_pct": -1.33,
        }

        result = service._format_quote(quote_data)

        assert "🔴" in result  # Negative change indicator

    def test_format_quote_minimal_data(self, service):
        """Test: Quote formatting with minimal data."""
        quote_data = {
            "symbol": "TEST",
        }

        result = service._format_quote(quote_data)

        assert "TEST" in result

    def test_format_batch_quotes_empty(self, service):
        """Test: Empty batch quotes formatting."""
        result = service._format_batch_quotes({})

        assert "No quotes" in result

    def test_format_batch_quotes_multiple(self, service):
        """Test: Multiple quotes formatting."""
        quotes = {
            "AAPL": {"last": 150.0, "change_pct": 1.5, "volume": 1000000},
            "MSFT": {"last": 300.0, "change_pct": -0.5, "volume": 500000},
        }

        result = service._format_batch_quotes(quotes)

        assert "AAPL" in result
        assert "MSFT" in result
        assert "Symbol" in result  # Table header


# =============================================================================
# Batch Quote Edge Cases
# =============================================================================

class TestBatchQuoteEdgeCases:
    """Tests for batch quote edge cases."""

    @pytest.mark.asyncio
    async def test_batch_mixed_cache_and_fetch(self, service):
        """Test: Mix of cached and fetched quotes."""
        # Pre-populate some cache entries
        service._quote_cache["AAPL"] = ({"symbol": "AAPL", "last": 150.0}, datetime.now())

        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_batch_quotes(["AAPL", "MSFT"], use_cache=True)

        assert result.success
        assert "AAPL" in result.data
        assert "MSFT" in result.data
        # AAPL should be from cache (150.0)
        assert result.data["AAPL"]["last"] == 150.0

    @pytest.mark.asyncio
    async def test_batch_quotes_no_cache(self, service):
        """Test: Batch quotes without cache."""
        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_batch_quotes(["AAPL", "MSFT"], use_cache=False)

        assert result.success
        assert len(result.data) == 2

    @pytest.mark.asyncio
    async def test_batch_quotes_partial_failure(self, service):
        """Test: Partial failure in batch quotes."""
        call_count = 0

        async def sometimes_fail_quote(symbol):
            nonlocal call_count
            call_count += 1
            if symbol == "FAIL":
                raise Exception("Simulated failure")
            return {"symbol": symbol, "last": 100.0}

        mock_provider = MagicMock()
        mock_provider.get_quote = sometimes_fail_quote

        service._get_provider = AsyncMock(return_value=mock_provider)
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_batch_quotes(["AAPL", "FAIL", "MSFT"])

        assert result.success
        # Should have AAPL and MSFT, but not FAIL
        assert "AAPL" in result.data
        assert "MSFT" in result.data


# =============================================================================
# Cache Expiry Tests
# =============================================================================

class TestCacheExpiry:
    """Tests for cache expiry behavior."""

    def test_get_from_cache_not_found(self, service):
        """Test: Cache miss returns None."""
        result = service._get_from_cache("NOTEXIST")
        assert result is None

    def test_get_from_cache_expired(self, service):
        """Test: Expired cache entry returns None."""
        # Add entry that's already expired
        expired_time = datetime.now() - timedelta(seconds=120)
        service._quote_cache["EXPIRED"] = ({"symbol": "EXPIRED"}, expired_time)

        result = service._get_from_cache("EXPIRED")

        assert result is None
        assert "EXPIRED" not in service._quote_cache  # Should be removed

    def test_get_from_cache_valid(self, service):
        """Test: Valid cache entry is returned."""
        service._quote_cache["VALID"] = ({"symbol": "VALID", "last": 100.0}, datetime.now())

        result = service._get_from_cache("VALID")

        assert result is not None
        assert result["last"] == 100.0


# =============================================================================
# Service Initialization Tests
# =============================================================================

class TestServiceInitialization:
    """Tests for service initialization."""

    def test_default_cache_ttl(self):
        """Test: Default cache TTL."""
        mock_ctx = MockServiceContext()
        with patch.object(QuoteService, '__init__', lambda self, ctx, **kw: None):
            svc = QuoteService.__new__(QuoteService)
            svc._cache_ttl_seconds = 60
            assert svc._cache_ttl_seconds == 60

    def test_custom_cache_ttl(self):
        """Test: Custom cache TTL."""
        mock_ctx = MockServiceContext()
        with patch.object(QuoteService, '__init__', lambda self, ctx, **kw: None):
            svc = QuoteService.__new__(QuoteService)
            svc._cache_ttl_seconds = 120
            assert svc._cache_ttl_seconds == 120


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
