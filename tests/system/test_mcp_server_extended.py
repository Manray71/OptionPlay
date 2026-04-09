# Extended Tests for MCP Server
# ==============================
"""
Extended tests for src/mcp_server.py covering:
- Container-based initialization
- IBKR provider integration
- Local database provider
- Connection retry logic
- Cache management
- Earnings prefilter logic
- Health check branches
"""

import pytest
import asyncio
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from collections import OrderedDict

from src.constants.trading_rules import ENTRY_STABILITY_MIN
from src.mcp_server import OptionPlayServer


# =============================================================================
# MOCK CLASSES
# =============================================================================

class MockConfig:
    """Mock configuration object."""
    class Settings:
        class Performance:
            cache_ttl_seconds = 300
            cache_max_entries = 1000
            historical_days = 90
            cache_ttl_intraday = 60

        class CircuitBreaker:
            failure_threshold = 5
            recovery_timeout = 30

        class ApiConnection:
            max_retries = 3
            retry_base_delay = 1
            vix_cache_seconds = 300

        class Scanner:
            enable_iv_filter = False
            earnings_allow_bmo_same_day = False
            min_score = 5.0
            min_stability = ENTRY_STABILITY_MIN
            max_candidates = 20

        class IBKRSettings:
            is_production = False
            environment = "sandbox"

        class DataSources:
            class LocalDatabase:
                enabled = True
                max_data_age_days = 1
            local_database = LocalDatabase()

        performance = Performance()
        circuit_breaker = CircuitBreaker()
        api_connection = ApiConnection()
        scanner = Scanner()
        ibkr = IBKRSettings()
        data_sources = DataSources()

    settings = Settings()


class MockServiceContainer:
    """Mock service container for DI."""
    def __init__(self):
        self.config = MockConfig()
        self.rate_limiter = MagicMock()
        self.rate_limiter.acquire = AsyncMock()
        self.rate_limiter.record_success = MagicMock()
        self.rate_limiter.stats = MagicMock(return_value={
            "requests": 0,
            "available_tokens": 10,
            "max_tokens": 10
        })
        self.circuit_breaker = MagicMock()
        self.circuit_breaker.can_execute = MagicMock(return_value=True)
        self.circuit_breaker.record_success = MagicMock()
        self.circuit_breaker.record_failure = MagicMock()
        self.circuit_breaker.stats = MagicMock(return_value={
            "state": "closed",
            "failure_count": 0,
            "failure_threshold": 5,
            "recovery_timeout": 30,
            "failures": 0,
            "successes": 0
        })
        self.circuit_breaker.name = "test_breaker"
        self.circuit_breaker.get_retry_after = MagicMock(return_value=10)
        self.historical_cache = MagicMock()
        self.historical_cache.get = MagicMock(return_value=MagicMock(status='MISS', data=None))
        self.historical_cache.set = MagicMock()
        self.historical_cache.stats = MagicMock(return_value={
            "entries": 0,
            "max_entries": 1000,
            "hits": 0,
            "misses": 0,
            "hit_rate_percent": 0.0,
            "ttl_seconds": 300
        })
        self.provider = AsyncMock()


class MockQuote:
    """Mock quote object."""
    def __init__(self, symbol="AAPL", last=185.50):
        self.symbol = symbol
        self.last = last
        self.bid = 185.45
        self.ask = 185.55
        self.volume = 50000000


class MockLocalDBProvider:
    """Mock local database provider."""
    def __init__(self, available=True):
        self._available = available
        self.db_path = "/mock/path/trades.db"

    def is_available(self):
        return self._available

    async def get_historical_for_scanner(self, symbol, days=90):
        return ([100.0] * days, [1000000] * days, [101.0] * days, [99.0] * days, [99.5] * days)

    def is_data_fresh(self, symbol, max_age_days):
        return True

    def stats(self):
        return {"available": True, "symbols": 100}


class MockCacheStatus:
    """Mock cache status enum."""
    HIT = "HIT"
    MISS = "MISS"


class MockCacheResult:
    """Mock cache result."""
    def __init__(self, status, data=None):
        self.status = status
        self.data = data


class MockEarningsManager:
    """Mock earnings history manager."""
    def is_earnings_day_safe(self, symbol, today, min_days, allow_bmo):
        if symbol == "SAFE":
            return (True, 30, "ok")
        elif symbol == "NEAR_EARNINGS":
            return (False, 3, "too_close")
        elif symbol == "UNKNOWN":
            return (False, None, "no_earnings_data")
        return (True, 30, "ok")

    async def is_earnings_day_safe_batch_async(self, symbols, today, min_days, allow_bmo):
        """Batch async wrapper matching real EarningsHistoryManager API."""
        return {
            s.upper(): self.is_earnings_day_safe(s, today, min_days, allow_bmo)
            for s in symbols
        }


class MockEarningsFetcher:
    """Mock earnings fetcher."""
    def __init__(self):
        self.cache = {}

    def fetch(self, symbol):
        class Info:
            days_to_earnings = 30
        return Info()


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_api_key():
    """Mock API key environment."""
    with patch.dict('os.environ', {'MARKETDATA_API_KEY': 'test_key_12345'}):
        yield


@pytest.fixture
def mock_container():
    """Create mock service container."""
    return MockServiceContainer()


@pytest.fixture
def mock_config():
    """Create mock config."""
    return MockConfig()


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestServerInitializationWithoutContainer:
    """Tests for initialization without container."""

    @patch('src.mcp_server.get_api_key')
    @patch('src.mcp_server.get_config')
    @patch('src.mcp_server.get_marketdata_limiter')
    @patch('src.mcp_server.get_historical_cache')
    @patch('src.mcp_server.get_circuit_breaker')
    def test_init_without_container_creates_components(
        self, mock_cb, mock_cache, mock_limiter, mock_config, mock_key
    ):
        """Test: Without container, creates all components."""
        mock_key.return_value = "test_key"
        mock_config.return_value = MockConfig()
        mock_limiter.return_value = MagicMock()
        mock_cache.return_value = MagicMock()
        mock_cb.return_value = MagicMock()

        server = OptionPlayServer()

        assert server._provider is None  # Created on connect
        mock_limiter.assert_called_once()
        mock_cache.assert_called_once()
        mock_cb.assert_called_once()


# =============================================================================
# CONNECTION TESTS
# =============================================================================

class TestIBKRConnection:
    """Tests for IBKR provider connection."""

    @pytest.mark.asyncio
    async def test_ensure_ibkr_connection_failure_logs_warning(self, mock_api_key):
        """Test: IBKR connection failure logs warning."""
        with patch('src.mcp_server.get_config', return_value=MockConfig()):
            with patch('src.mcp_server.IBKRDataProvider') as mock_ibkr:
                mock_provider = AsyncMock()
                mock_provider.connect = AsyncMock(return_value=False)
                mock_ibkr.return_value = mock_provider

                server = OptionPlayServer()

                result = await server._ensure_ibkr_connected()

                assert result is None
                assert server._ibkr_connected is False

    @pytest.mark.asyncio
    async def test_ensure_ibkr_connection_error_handled(self, mock_api_key):
        """Test: IBKR connection error is handled gracefully."""
        with patch('src.mcp_server.get_config', return_value=MockConfig()):
            with patch('src.mcp_server.IBKRDataProvider') as mock_ibkr:
                mock_provider = AsyncMock()
                mock_provider.connect = AsyncMock(side_effect=ConnectionError("Network error"))
                mock_ibkr.return_value = mock_provider

                server = OptionPlayServer()

                result = await server._ensure_ibkr_connected()

                assert result is None


# =============================================================================
# CACHE TESTS
# =============================================================================

class TestHistoricalCache:
    """Tests for historical data caching."""

    @pytest.mark.asyncio
    async def test_fetch_historical_cache_hit(self, mock_api_key, mock_container):
        """Test: Cache hit returns cached data."""
        cached_data = ([100.0] * 90, [1000000] * 90, [101.0] * 90, [99.0] * 90)
        cache_result = MockCacheResult("HIT", cached_data)
        mock_container.historical_cache.get = MagicMock(return_value=cache_result)

        server = OptionPlayServer(container=mock_container)

        # Patch CacheStatus
        with patch('src.mcp_server.CacheStatus', MockCacheStatus):
            result = await server._fetch_historical_cached("AAPL")

            assert result == cached_data

    @pytest.mark.asyncio
    async def test_fetch_historical_local_db_hit(self, mock_api_key, mock_container):
        """Test: Local DB hit after cache miss."""
        # Cache miss
        cache_result = MockCacheResult("MISS", None)
        mock_container.historical_cache.get = MagicMock(return_value=cache_result)

        server = OptionPlayServer(container=mock_container)

        # Local DB hit
        server._local_db_enabled = True
        server._local_db_provider = MockLocalDBProvider()

        with patch('src.mcp_server.CacheStatus', MockCacheStatus):
            result = await server._fetch_historical_cached("AAPL")

            assert result is not None
            assert len(result) == 5

class TestQuoteCache:
    """Tests for quote caching."""

    @pytest.mark.asyncio
    async def test_get_quote_cached_hit(self, mock_api_key, mock_container):
        """Test: Quote cache hit."""
        server = OptionPlayServer(container=mock_container)

        # Pre-populate cache
        cached_quote = MockQuote("AAPL", 185.50)
        server._quote_cache["AAPL"] = (cached_quote, datetime.now())

        result = await server._get_quote_cached("AAPL")

        assert result == cached_quote
        assert server._quote_cache_hits == 1

class TestCacheStats:
    """Tests for cache statistics."""

    def test_get_quote_cache_stats(self, mock_api_key, mock_container):
        """Test: Quote cache stats calculation."""
        server = OptionPlayServer(container=mock_container)
        server._quote_cache = {"AAPL": (None, datetime.now())}
        server._quote_cache_hits = 8
        server._quote_cache_misses = 2

        stats = server._get_quote_cache_stats()

        assert stats["entries"] == 1
        assert stats["hits"] == 8
        assert stats["misses"] == 2
        assert stats["hit_rate_percent"] == 80.0

    def test_get_scan_cache_stats(self, mock_api_key, mock_container):
        """Test: Scan cache stats calculation."""
        server = OptionPlayServer(container=mock_container)
        server._scan_cache = {"key1": None, "key2": None}
        server._scan_cache_hits = 5
        server._scan_cache_misses = 5

        stats = server._get_scan_cache_stats()

        assert stats["entries"] == 2
        assert stats["hit_rate_percent"] == 50.0
        assert stats["ttl_seconds"] == 1800


# =============================================================================
# EARNINGS PREFILTER TESTS
# =============================================================================

class TestEarningsPrefilter:
    """Tests for earnings prefilter logic."""

    @pytest.mark.asyncio
    async def test_prefilter_etf_always_safe(self, mock_api_key, mock_container):
        """Test: ETFs are always considered safe."""
        with patch('src.mcp_server.is_etf', return_value=True):
            with patch('src.cache.get_earnings_history_manager', return_value=MockEarningsManager()):
                server = OptionPlayServer(container=mock_container)
                server._earnings_fetcher = MockEarningsFetcher()

                safe, excluded, hits = await server._apply_earnings_prefilter(
                    ["SPY", "QQQ", "IWM"], min_days=7
                )

                assert len(safe) == 3
                assert excluded == 0

    @pytest.mark.asyncio
    async def test_prefilter_near_earnings_excluded(self, mock_api_key, mock_container):
        """Test: Symbols near earnings are excluded."""
        with patch('src.mcp_server.is_etf', return_value=False):
            with patch('src.cache.get_earnings_history_manager', return_value=MockEarningsManager()):
                server = OptionPlayServer(container=mock_container)
                server._earnings_fetcher = MockEarningsFetcher()

                safe, excluded, hits = await server._apply_earnings_prefilter(
                    ["NEAR_EARNINGS"], min_days=7
                )

                assert len(safe) == 0
                assert excluded == 1

    @pytest.mark.asyncio
    async def test_prefilter_safe_symbols_included(self, mock_api_key, mock_container):
        """Test: Safe symbols are included."""
        with patch('src.mcp_server.is_etf', return_value=False):
            with patch('src.cache.get_earnings_history_manager', return_value=MockEarningsManager()):
                server = OptionPlayServer(container=mock_container)
                server._earnings_fetcher = MockEarningsFetcher()

                safe, excluded, hits = await server._apply_earnings_prefilter(
                    ["SAFE"], min_days=7
                )

                assert len(safe) == 1
                assert "SAFE" in safe

    @pytest.mark.asyncio
    async def test_prefilter_unknown_excluded_conservatively(self, mock_api_key, mock_container):
        """Test: Unknown earnings dates are excluded conservatively."""
        mock_earnings_manager = MagicMock()
        mock_earnings_manager.is_earnings_day_safe.return_value = (False, None, "no_earnings_data")
        mock_earnings_manager.is_earnings_day_safe_batch_async = AsyncMock(
            return_value={"UNKNOWN_SYMBOL": (False, None, "no_earnings_data")}
        )

        with patch('src.mcp_server.is_etf', return_value=False):
            with patch('src.cache.get_earnings_history_manager', return_value=mock_earnings_manager):
                server = OptionPlayServer(container=mock_container)

                # Mock fetcher returns None for unknown symbol
                mock_fetcher = MagicMock()
                mock_fetcher.cache = {}
                mock_fetcher.fetch.return_value = None
                server._earnings_fetcher = mock_fetcher

                safe, excluded, hits = await server._apply_earnings_prefilter(
                    ["UNKNOWN_SYMBOL"], min_days=7
                )

                assert len(safe) == 0
                assert excluded == 1



# =============================================================================
# SCANNER TESTS
# =============================================================================

class TestScannerMethods:
    """Tests for scanner creation methods."""

    def test_get_scanner_creates_pullback_only(self, mock_api_key, mock_container):
        """Test: _get_scanner creates pullback-only scanner."""
        with patch('src.mcp_server.get_scan_config') as mock_scan_config:
            mock_config = MagicMock()
            mock_scan_config.return_value = mock_config

            server = OptionPlayServer(container=mock_container)
            scanner = server._get_scanner(min_score=5.0)

            assert scanner is not None

    def test_get_multi_scanner_all_strategies(self, mock_api_key, mock_container):
        """Test: _get_multi_scanner enables all strategies."""
        server = OptionPlayServer(container=mock_container)

        scanner = server._get_multi_scanner(
            enable_pullback=True,
            enable_bounce=True,
        )

        assert scanner is not None

    def test_get_multi_scanner_iv_filter_disabled_without_ibkr(self, mock_api_key, mock_container):
        """Test: IV filter disabled when IBKR not connected."""
        server = OptionPlayServer(container=mock_container)
        server._ibkr_connected = False

        # Even if config has IV filter enabled
        server._config.settings.scanner.enable_iv_filter = True

        scanner = server._get_multi_scanner()

        # IV filter should be disabled (config attr is 'enable_iv_filter')
        assert scanner.config.enable_iv_filter is False


# =============================================================================
# HEALTH CHECK TESTS
# =============================================================================

class TestHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_returns_string(self, mock_api_key, mock_container):
        """Test: Health check returns formatted string."""
        with patch('src.mcp_server.formatters') as mock_formatters:
            mock_formatters.health_check.format.return_value = "Health: OK"

            server = OptionPlayServer(container=mock_container)
            server._ibkr_bridge = None
            server._local_db_enabled = False

            result = await server.health_check()

            assert result == "Health: OK"
            mock_formatters.health_check.format.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_with_ibkr_connected(self, mock_api_key, mock_container):
        """Test: Health check includes IBKR info when connected."""
        with patch('src.mcp_server.formatters') as mock_formatters:
            mock_formatters.health_check.format.return_value = "Health with IBKR: OK"

            server = OptionPlayServer(container=mock_container)
            server._ibkr_connected = True
            server._local_db_enabled = False

            result = await server.health_check()

            assert result == "Health with IBKR: OK"
            # Verify the HealthCheckData was passed with IBKR provider info
            call_args = mock_formatters.health_check.format.call_args
            health_data = call_args[0][0]
            assert health_data.ibkr_provider_available is True
            assert health_data.ibkr_provider_connected is True

    @pytest.mark.asyncio
    async def test_health_check_with_local_db_enabled(self, mock_api_key, mock_container):
        """Test: Health check includes local DB stats when enabled."""
        with patch('src.mcp_server.formatters') as mock_formatters:
            mock_formatters.health_check.format.return_value = "Health with LocalDB: OK"

            server = OptionPlayServer(container=mock_container)
            server._local_db_enabled = True
            server._local_db_provider = MockLocalDBProvider()

            result = await server.health_check()

            assert result == "Health with LocalDB: OK"
            # Verify local DB stats were included
            call_args = mock_formatters.health_check.format.call_args
            health_data = call_args[0][0]
            assert health_data.local_db_enabled is True
            assert health_data.local_db_stats is not None

    @pytest.mark.asyncio
    async def test_health_check_with_ibkr(self, mock_api_key, mock_container):
        """Test: Health check includes IBKR info when available."""
        mock_bridge = MagicMock()
        mock_bridge.host = "127.0.0.1"
        mock_bridge.port = 7497

        with patch('src.mcp_server.formatters') as mock_formatters:
            with patch('src.mcp_server.IBKR_AVAILABLE', True):
                with patch('src.mcp_server.get_ibkr_bridge', return_value=mock_bridge, create=True):
                    mock_formatters.health_check.format.return_value = "Health with IBKR: OK"

                    server = OptionPlayServer(container=mock_container)
                    server._local_db_enabled = False

                    result = await server.health_check()

                    # Verify IBKR info was included
                    call_args = mock_formatters.health_check.format.call_args
                    health_data = call_args[0][0]
                    assert health_data.ibkr_provider_available is True
                    assert health_data.ibkr_host == "127.0.0.1"
                    assert health_data.ibkr_port == 7497


# =============================================================================
# UTILITY TESTS
# =============================================================================

class TestUtilityMethods:
    """Tests for utility methods."""

    def test_get_active_provider_name_ibkr(self, mock_api_key, mock_container):
        """Test: Returns IBKR when connected."""
        server = OptionPlayServer(container=mock_container)
        server._ibkr_connected = True

        assert server._get_active_provider_name() == "IBKR"

    def test_get_watchlist_info(self, mock_api_key, mock_container):
        """Test: Watchlist info formatting."""
        server = OptionPlayServer(container=mock_container)

        result = server.get_watchlist_info()

        assert "Watchlist" in result
        assert "Symbols" in result or "Sectors" in result


# =============================================================================
# ASYNC CONTEXT MANAGER TESTS
# =============================================================================

class TestAsyncContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_aenter_connects(self, mock_api_key, mock_container):
        """Test: __aenter__ establishes connection."""
        server = OptionPlayServer(container=mock_container)
        server._ensure_connected = AsyncMock()

        result = await server.__aenter__()

        server._ensure_connected.assert_called_once()
        assert result is server

    @pytest.mark.asyncio
    async def test_aexit_disconnects(self, mock_api_key, mock_container):
        """Test: __aexit__ disconnects."""
        server = OptionPlayServer(container=mock_container)
        server.disconnect = AsyncMock()

        await server.__aexit__(None, None, None)

        server.disconnect.assert_called_once()


# =============================================================================
# CACHE STATS ENDPOINT TEST
# =============================================================================

class TestCacheStatsEndpoint:
    """Tests for get_cache_stats method."""

    @pytest.mark.asyncio
    async def test_get_cache_stats_formatting(self, mock_api_key, mock_container):
        """Test: Cache stats returns formatted string."""
        mock_container.historical_cache.stats = MagicMock(return_value={
            "entries": 10,
            "hits": 50,
            "misses": 10,
            "hit_rate_percent": 83.3
        })

        server = OptionPlayServer(container=mock_container)
        server._quote_cache = {}
        server._quote_cache_hits = 20
        server._quote_cache_misses = 5
        server._scan_cache = {}
        server._deduplicator.stats = MagicMock(return_value={
            "total_requests": 100,
            "actual_calls": 70,
            "deduplicated": 30,
            "dedup_rate_percent": 30.0
        })

        result = await server.get_cache_stats()

        assert "Cache" in result
        assert "Historical" in result or "Quote" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
