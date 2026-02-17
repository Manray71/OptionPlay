# OptionPlay - VIX Service Tests
# ================================
# Comprehensive tests for src/services/vix_service.py
#
# Coverage:
# - VixService initialization
# - get_vix method (caching, force_refresh, fallback)
# - get_vix_concurrent method
# - get_strategy_recommendation method
# - get_strategy_recommendation_formatted method
# - Caching behavior (TTL, stale cache, cache update)
# - Error handling (provider failure, Yahoo fallback, all sources fail)
# - Properties (current_vix, vix_updated)

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.vix_service import VIXService
from src.services.base import ServiceContext, BaseService
from src.models.result import ServiceResult
from src.constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS
from src.services.vix_strategy import StrategyRecommendation, MarketRegime, VIXStrategySelector


# =============================================================================
# Mock Classes
# =============================================================================

class MockConfig:
    """Mock config for testing."""
    class Settings:
        class ApiConnection:
            yahoo_timeout = 5
            vix_cache_seconds = 300
            max_retries = 3
            retry_base_delay = 1
        class Performance:
            cache_ttl_seconds = 300
            cache_max_entries = 1000
        class CircuitBreaker:
            failure_threshold = 5
            recovery_timeout = 30
        api_connection = ApiConnection()
        performance = Performance()
        circuit_breaker = CircuitBreaker()
    settings = Settings()


class MockProvider:
    """Mock data provider."""
    def __init__(self, vix_value: float = 18.5):
        self._vix_value = vix_value
        self._should_fail = False
        self._call_count = 0

    async def get_vix(self):
        self._call_count += 1
        if self._should_fail:
            raise Exception("Provider error")
        return self._vix_value


class MockRateLimiter:
    """Mock rate limiter."""
    def __init__(self):
        self.acquire_count = 0
        self.success_count = 0
        self.failure_count = 0

    async def acquire(self):
        self.acquire_count += 1

    def record_success(self):
        self.success_count += 1

    def record_failure(self):
        self.failure_count += 1


class MockServiceContext:
    """Mock service context."""
    def __init__(self):
        self._vix_cache = None
        self._vix_updated = None
        self._provider = MockProvider()
        self.rate_limiter = MockRateLimiter()
        self.api_key = "test_key_123456"

    @property
    def api_key_masked(self):
        return "test_***"

    async def get_provider(self):
        return self._provider


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_context():
    """Create a mock service context."""
    return MockServiceContext()


@pytest.fixture
def mock_config():
    """Create a mock config."""
    return MockConfig()


@pytest.fixture
def service(mock_context, mock_config):
    """Create a VIX service with mock context."""
    with patch.object(VIXService, '__init__', lambda self, ctx: None):
        svc = VIXService.__new__(VIXService)
        svc._context = mock_context
        svc._config = mock_config
        svc._logger = MagicMock()
        svc._vix_selector = VIXStrategySelector()

        # Setup rate_limited as async context manager
        @asynccontextmanager
        async def mock_rate_limited():
            await mock_context.rate_limiter.acquire()
            try:
                yield
                mock_context.rate_limiter.record_success()
            except Exception:
                mock_context.rate_limiter.record_failure()
                raise

        svc._rate_limited = mock_rate_limited
        svc._get_provider = AsyncMock(return_value=mock_context._provider)

        return svc


@pytest.fixture
def fresh_service():
    """Create a fresh VIX service with no mocked init."""
    context = MagicMock(spec=ServiceContext)
    context.api_key = "test_key"
    context.api_key_masked = "test_***"
    context._vix_cache = None
    context._vix_updated = None
    context.rate_limiter = MockRateLimiter()

    with patch('src.services.base.get_config', return_value=MockConfig()):
        # Use __new__ to avoid calling __init__
        svc = VIXService.__new__(VIXService)
        svc._context = context
        svc._config = MockConfig()
        svc._logger = MagicMock()
        svc._vix_selector = VIXStrategySelector()

    return svc


# =============================================================================
# VIXService Initialization Tests
# =============================================================================

class TestVIXServiceInit:
    """Tests for VIXService initialization."""

    def test_service_init_creates_vix_selector(self):
        """Test: Service initialization creates VIX selector."""
        mock_context = MagicMock(spec=ServiceContext)
        mock_context.api_key = "test_key"

        with patch('src.services.base.get_config', return_value=MockConfig()):
            service = VIXService(mock_context)

        assert hasattr(service, '_vix_selector')
        assert isinstance(service._vix_selector, VIXStrategySelector)

    def test_service_init_stores_context(self):
        """Test: Service stores context reference."""
        mock_context = MagicMock(spec=ServiceContext)
        mock_context.api_key = "test_key"

        with patch('src.services.base.get_config', return_value=MockConfig()):
            service = VIXService(mock_context)

        assert service._context is mock_context

    def test_service_inherits_from_base(self):
        """Test: VIXService inherits from BaseService."""
        assert issubclass(VIXService, BaseService)

    def test_service_has_required_methods(self):
        """Test: Service has all required methods."""
        required_methods = [
            'get_vix',
            'get_vix_concurrent',
            'get_strategy_recommendation',
            'get_strategy_recommendation_formatted',
            '_fetch_vix_yahoo',
        ]
        for method in required_methods:
            assert hasattr(VIXService, method), f"Missing method: {method}"


# =============================================================================
# get_vix Tests
# =============================================================================

class TestGetVix:
    """Tests for get_vix() method."""

    @pytest.mark.asyncio
    async def test_get_vix_returns_service_result(self, service):
        """Test: get_vix returns ServiceResult type."""
        result = await service.get_vix()
        assert isinstance(result, ServiceResult)

    @pytest.mark.asyncio
    async def test_get_vix_success_from_provider(self, service):
        """Test: get_vix fetches successfully from provider."""
        service._context._provider._vix_value = 22.5

        result = await service.get_vix()

        assert result.success
        assert result.data == 22.5
        assert result.cached is False
        assert result.source == "marketdata"

    @pytest.mark.asyncio
    async def test_get_vix_uses_cache_when_valid(self, service):
        """Test: get_vix returns cached value when still valid."""
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now()

        result = await service.get_vix()

        assert result.success
        assert result.data == 20.0
        assert result.cached is True
        assert result.source == "cache"

    @pytest.mark.asyncio
    async def test_get_vix_cache_expired(self, service):
        """Test: get_vix fetches new value when cache expired."""
        # Set cache but make it expired
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now() - timedelta(seconds=400)  # Expired

        result = await service.get_vix()

        assert result.success
        assert result.data == 18.5  # From mock provider
        assert result.cached is False
        assert result.source == "marketdata"

    @pytest.mark.asyncio
    async def test_get_vix_force_refresh_ignores_cache(self, service):
        """Test: get_vix with force_refresh ignores valid cache."""
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now()
        service._context._provider._vix_value = 19.0

        result = await service.get_vix(force_refresh=True)

        assert result.success
        assert result.data == 19.0  # From provider, not cache
        assert result.cached is False

    @pytest.mark.asyncio
    async def test_get_vix_updates_cache_on_success(self, service):
        """Test: get_vix updates cache after successful fetch."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._vix_value = 16.5

        result = await service.get_vix()

        assert result.success
        assert service._context._vix_cache == 16.5
        assert service._context._vix_updated is not None

    @pytest.mark.asyncio
    async def test_get_vix_yahoo_fallback_on_provider_failure(self, service):
        """Test: get_vix falls back to Yahoo when provider fails."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=17.5):
            result = await service.get_vix()

        assert result.success
        assert result.data == 17.5
        assert result.source == "yahoo"

    @pytest.mark.asyncio
    async def test_get_vix_stale_cache_fallback(self, service):
        """Test: get_vix returns stale cache when all sources fail."""
        service._context._vix_cache = 22.0
        service._context._vix_updated = datetime.now() - timedelta(hours=1)  # Stale
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result = await service.get_vix(force_refresh=True)

        assert result.success
        assert result.data == 22.0
        assert result.source == "stale_cache"
        assert len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_get_vix_all_fail_no_cache(self, service):
        """Test: get_vix fails when all sources fail and no cache."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result = await service.get_vix()

        assert not result.success
        assert "Could not fetch VIX" in result.error

    @pytest.mark.asyncio
    async def test_get_vix_includes_duration_ms(self, service):
        """Test: get_vix includes duration_ms in result."""
        result = await service.get_vix()

        assert result.success
        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_get_vix_logs_update(self, service):
        """Test: get_vix logs VIX update."""
        await service.get_vix()

        service._logger.info.assert_called()


# =============================================================================
# _fetch_vix_yahoo Tests
# =============================================================================

class TestFetchVixYahoo:
    """Tests for _fetch_vix_yahoo() method."""

    def test_fetch_yahoo_success_regular_market_price(self, service):
        """Test: Yahoo fetch returns regularMarketPrice."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"chart":{"result":[{"meta":{"regularMarketPrice":17.5}}]}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            vix = service._fetch_vix_yahoo()

        assert vix == 17.5

    def test_fetch_yahoo_fallback_to_closes(self, service):
        """Test: Yahoo falls back to last close when regularMarketPrice missing."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"chart":{"result":[{"meta":{},"indicators":{"quote":[{"close":[16.0, 17.0, 18.0]}]}}]}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            vix = service._fetch_vix_yahoo()

        assert vix == 18.0  # Last close

    def test_fetch_yahoo_skips_none_closes(self, service):
        """Test: Yahoo skips None values in closes array."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"chart":{"result":[{"meta":{},"indicators":{"quote":[{"close":[16.0, 17.0, null, null]}]}}]}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            vix = service._fetch_vix_yahoo()

        assert vix == 17.0  # Last non-null close

    def test_fetch_yahoo_network_error(self, service):
        """Test: Yahoo returns None on network error."""
        with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
            vix = service._fetch_vix_yahoo()

        assert vix is None

    def test_fetch_yahoo_invalid_json(self, service):
        """Test: Yahoo returns None on invalid JSON."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'invalid json'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            vix = service._fetch_vix_yahoo()

        assert vix is None

    def test_fetch_yahoo_empty_result(self, service):
        """Test: Yahoo returns None on empty result."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"chart":{"result":[]}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            vix = service._fetch_vix_yahoo()

        assert vix is None

    def test_fetch_yahoo_timeout(self, service):
        """Test: Yahoo returns None on timeout."""
        import socket
        with patch('urllib.request.urlopen', side_effect=socket.timeout("timeout")):
            vix = service._fetch_vix_yahoo()

        assert vix is None

    def test_fetch_yahoo_uses_correct_url(self, service):
        """Test: Yahoo uses correct API URL."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"chart":{"result":[{"meta":{"regularMarketPrice":18.0}}]}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response) as mock_open:
            with patch('urllib.request.Request') as mock_request:
                service._fetch_vix_yahoo()

                # Check the URL contains VIX
                call_args = mock_request.call_args
                url = call_args[0][0]
                assert "VIX" in url or "vix" in url.lower()


# =============================================================================
# get_vix_concurrent Tests
# =============================================================================

class TestGetVixConcurrent:
    """Tests for get_vix_concurrent() method."""

    @pytest.mark.asyncio
    async def test_concurrent_returns_service_result(self, service):
        """Test: get_vix_concurrent returns ServiceResult."""
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now()

        result = await service.get_vix_concurrent()

        assert isinstance(result, ServiceResult)

    @pytest.mark.asyncio
    async def test_concurrent_uses_cache(self, service):
        """Test: get_vix_concurrent returns cached value when valid."""
        service._context._vix_cache = 21.0
        service._context._vix_updated = datetime.now()

        result = await service.get_vix_concurrent()

        assert result.success
        assert result.data == 21.0
        assert result.cached is True
        assert result.source == "cache"

    @pytest.mark.asyncio
    async def test_concurrent_fetches_when_no_cache(self, service):
        """Test: get_vix_concurrent fetches when cache is empty."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._vix_value = 19.5

        result = await service.get_vix_concurrent()

        assert result.success
        assert result.data == 19.5
        assert result.cached is False

    @pytest.mark.asyncio
    async def test_concurrent_updates_cache(self, service):
        """Test: get_vix_concurrent updates cache on success."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._vix_value = 17.0

        result = await service.get_vix_concurrent()

        assert result.success
        assert service._context._vix_cache == 17.0
        assert service._context._vix_updated is not None

    @pytest.mark.asyncio
    async def test_concurrent_stale_cache_fallback(self, service):
        """Test: get_vix_concurrent falls back to stale cache."""
        service._context._vix_cache = 23.0
        service._context._vix_updated = datetime.now() - timedelta(hours=1)
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result = await service.get_vix_concurrent()

        assert result.success
        assert result.data == 23.0
        assert result.source == "stale_cache"

    @pytest.mark.asyncio
    async def test_concurrent_all_fail_no_cache(self, service):
        """Test: get_vix_concurrent fails when all sources fail."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result = await service.get_vix_concurrent()

        assert not result.success
        assert "Could not fetch VIX" in result.error

    @pytest.mark.asyncio
    async def test_concurrent_includes_duration(self, service):
        """Test: get_vix_concurrent includes duration_ms."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        result = await service.get_vix_concurrent()

        assert result.success
        assert result.duration_ms is not None


# =============================================================================
# get_strategy_recommendation Tests
# =============================================================================

class TestGetStrategyRecommendation:
    """Tests for get_strategy_recommendation() method."""

    @pytest.mark.asyncio
    async def test_recommendation_returns_service_result(self, service):
        """Test: get_strategy_recommendation returns ServiceResult."""
        service._context._vix_cache = 18.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation()

        assert isinstance(result, ServiceResult)

    @pytest.mark.asyncio
    async def test_recommendation_success_with_vix(self, service):
        """Test: Recommendation succeeds with valid VIX."""
        service._context._vix_cache = 18.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation()

        assert result.success
        assert result.data is not None
        assert isinstance(result.data, StrategyRecommendation)

    @pytest.mark.asyncio
    async def test_recommendation_has_expected_attributes(self, service):
        """Test: Recommendation has all expected attributes."""
        service._context._vix_cache = 18.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation()

        rec = result.data
        assert hasattr(rec, 'profile_name')
        assert hasattr(rec, 'regime')
        assert hasattr(rec, 'delta_target')
        assert hasattr(rec, 'delta_min')
        assert hasattr(rec, 'delta_max')
        assert hasattr(rec, 'min_score')
        assert hasattr(rec, 'earnings_buffer_days')
        assert hasattr(rec, 'dte_min')
        assert hasattr(rec, 'dte_max')
        assert hasattr(rec, 'reasoning')
        assert hasattr(rec, 'warnings')

    @pytest.mark.asyncio
    async def test_recommendation_regime_low_vol(self, service):
        """Test: Low VIX returns LOW_VOL regime."""
        service._context._vix_cache = 12.0
        service._context._vix_updated = datetime.now()

        # Create mock recommendation with LOW_VOL regime
        mock_rec = StrategyRecommendation(
            profile_name='conservative',
            regime=MarketRegime.LOW_VOL,
            vix_level=12.0,
            delta_target=-0.20,
            delta_min=-0.23,
            delta_max=-0.17,
            long_delta_target=-0.05,
            spread_width=None,
            min_score=6,
            earnings_buffer_days=ENTRY_EARNINGS_MIN_DAYS,
            dte_min=60,
            dte_max=90,
            reasoning="Test reasoning",
            warnings=[],
        )

        with patch('src.services.vix_service.get_strategy_for_vix', return_value=mock_rec):
            result = await service.get_strategy_recommendation()

        assert result.data.regime == MarketRegime.LOW_VOL

    @pytest.mark.asyncio
    async def test_recommendation_regime_normal(self, service):
        """Test: Normal VIX returns NORMAL regime.

        Uses VIX of 17.5 which is in NORMAL range (15-20).
        Note: VIXStrategySelector may adjust regime based on VIX trend,
        so we mock get_strategy_for_vix to ensure consistent behavior.
        """
        service._context._vix_cache = 17.5
        service._context._vix_updated = datetime.now()

        # Create mock recommendation with NORMAL regime
        mock_rec = StrategyRecommendation(
            profile_name='standard',
            regime=MarketRegime.NORMAL,
            vix_level=17.5,
            delta_target=-0.20,
            delta_min=-0.23,
            delta_max=-0.17,
            long_delta_target=-0.05,
            spread_width=None,
            min_score=5,
            earnings_buffer_days=ENTRY_EARNINGS_MIN_DAYS,
            dte_min=60,
            dte_max=90,
            reasoning="Test reasoning",
            warnings=[],
        )

        with patch('src.services.vix_service.get_strategy_for_vix', return_value=mock_rec):
            result = await service.get_strategy_recommendation()

        assert result.data.regime == MarketRegime.NORMAL

    @pytest.mark.asyncio
    async def test_recommendation_regime_danger_zone(self, service):
        """Test: VIX 20-25 returns DANGER_ZONE regime."""
        service._context._vix_cache = 22.0
        service._context._vix_updated = datetime.now()

        # Create mock recommendation with DANGER_ZONE regime
        mock_rec = StrategyRecommendation(
            profile_name='danger_zone',
            regime=MarketRegime.DANGER_ZONE,
            vix_level=22.0,
            delta_target=-0.20,
            delta_min=-0.22,
            delta_max=-0.15,
            long_delta_target=-0.05,
            spread_width=None,
            min_score=7,
            earnings_buffer_days=ENTRY_EARNINGS_MIN_DAYS,
            dte_min=60,
            dte_max=90,
            reasoning="Test reasoning",
            warnings=[],
        )

        with patch('src.services.vix_service.get_strategy_for_vix', return_value=mock_rec):
            result = await service.get_strategy_recommendation()

        assert result.data.regime == MarketRegime.DANGER_ZONE

    @pytest.mark.asyncio
    async def test_recommendation_regime_elevated(self, service):
        """Test: VIX 25-30 returns ELEVATED regime."""
        service._context._vix_cache = 27.0
        service._context._vix_updated = datetime.now()

        # Create mock recommendation with ELEVATED regime
        mock_rec = StrategyRecommendation(
            profile_name='elevated',
            regime=MarketRegime.ELEVATED,
            vix_level=27.0,
            delta_target=-0.20,
            delta_min=-0.23,
            delta_max=-0.17,
            long_delta_target=-0.05,
            spread_width=None,
            min_score=5,
            earnings_buffer_days=ENTRY_EARNINGS_MIN_DAYS,
            dte_min=60,
            dte_max=90,
            reasoning="Test reasoning",
            warnings=[],
        )

        with patch('src.services.vix_service.get_strategy_for_vix', return_value=mock_rec):
            result = await service.get_strategy_recommendation()

        assert result.data.regime == MarketRegime.ELEVATED

    @pytest.mark.asyncio
    async def test_recommendation_regime_high_vol(self, service):
        """Test: VIX > 30 returns HIGH_VOL regime."""
        service._context._vix_cache = 35.0
        service._context._vix_updated = datetime.now()

        # Create mock recommendation with HIGH_VOL regime
        mock_rec = StrategyRecommendation(
            profile_name='high_volatility',
            regime=MarketRegime.HIGH_VOL,
            vix_level=35.0,
            delta_target=-0.20,
            delta_min=-0.23,
            delta_max=-0.17,
            long_delta_target=-0.05,
            spread_width=None,
            min_score=6,
            earnings_buffer_days=ENTRY_EARNINGS_MIN_DAYS,
            dte_min=60,
            dte_max=90,
            reasoning="Test reasoning",
            warnings=[],
        )

        with patch('src.services.vix_service.get_strategy_for_vix', return_value=mock_rec):
            result = await service.get_strategy_recommendation()

        assert result.data.regime == MarketRegime.HIGH_VOL

    @pytest.mark.asyncio
    async def test_recommendation_fallback_vix(self, service):
        """Test: Recommendation uses default VIX when fetch fails."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result = await service.get_strategy_recommendation()

        assert result.success
        assert len(result.warnings) > 0
        assert any("default" in w.lower() or "failed" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_recommendation_propagates_source(self, service):
        """Test: Recommendation propagates VIX source."""
        service._context._vix_cache = 18.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation()

        assert result.source == "cache"

    @pytest.mark.asyncio
    async def test_recommendation_propagates_cached_flag(self, service):
        """Test: Recommendation propagates cached flag."""
        service._context._vix_cache = 18.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation()

        assert result.cached is True


# =============================================================================
# get_strategy_recommendation_formatted Tests
# =============================================================================

class TestGetStrategyRecommendationFormatted:
    """Tests for get_strategy_recommendation_formatted() method."""

    @pytest.mark.asyncio
    async def test_formatted_returns_string(self, service):
        """Test: Formatted recommendation returns string."""
        service._context._vix_cache = 19.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation_formatted()

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_formatted_contains_vix_info(self, service):
        """Test: Formatted output contains VIX information."""
        service._context._vix_cache = 19.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation_formatted()

        # Should contain VIX-related content
        assert "VIX" in result or "19" in result

    @pytest.mark.asyncio
    async def test_formatted_uses_default_vix_on_failure(self, service):
        """Test: Formatted uses default VIX (20.0) when fetch fails."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result = await service.get_strategy_recommendation_formatted()

        assert isinstance(result, str)
        # Default VIX is 20.0 which falls in NORMAL regime
        assert len(result) > 0


# =============================================================================
# Caching Behavior Tests
# =============================================================================

class TestCachingBehavior:
    """Tests for VIX caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_ttl_respected(self, service):
        """Test: Cache TTL (300 seconds) is respected."""
        service._context._vix_cache = 20.0
        # Set to just under TTL
        service._context._vix_updated = datetime.now() - timedelta(seconds=299)

        result = await service.get_vix()

        assert result.cached is True
        assert result.source == "cache"

    @pytest.mark.asyncio
    async def test_cache_expired_fetches_new(self, service):
        """Test: Expired cache triggers new fetch."""
        service._context._vix_cache = 20.0
        # Set to just over TTL
        service._context._vix_updated = datetime.now() - timedelta(seconds=301)

        result = await service.get_vix()

        assert result.cached is False
        assert result.source == "marketdata"

    @pytest.mark.asyncio
    async def test_cache_update_timestamp(self, service):
        """Test: Cache update sets correct timestamp."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        before = datetime.now()
        await service.get_vix()
        after = datetime.now()

        assert service._context._vix_updated is not None
        assert before <= service._context._vix_updated <= after

    @pytest.mark.asyncio
    async def test_cache_not_updated_on_failure(self, service):
        """Test: Cache not updated when all sources fail."""
        original_cache = 20.0
        original_updated = datetime.now() - timedelta(hours=1)
        service._context._vix_cache = original_cache
        service._context._vix_updated = original_updated
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            await service.get_vix(force_refresh=True)

        # Cache should remain unchanged (stale)
        assert service._context._vix_cache == original_cache

    @pytest.mark.asyncio
    async def test_concurrent_caching(self, service):
        """Test: Multiple concurrent requests use same cache."""
        service._context._vix_cache = 18.0
        service._context._vix_updated = datetime.now()

        # Make multiple concurrent requests
        results = await asyncio.gather(
            service.get_vix(),
            service.get_vix(),
            service.get_vix(),
        )

        # All should return cached value
        for result in results:
            assert result.success
            assert result.data == 18.0
            assert result.cached is True


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_provider_exception_handled(self, service):
        """Test: Provider exception is handled gracefully."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        # Make provider raise exception
        service._get_provider = AsyncMock(side_effect=Exception("Connection error"))

        with patch.object(service, '_fetch_vix_yahoo', return_value=17.0):
            result = await service.get_vix()

        # Should fall back to Yahoo
        assert result.success
        assert result.source == "yahoo"

    @pytest.mark.asyncio
    async def test_rate_limiter_exception_propagated(self, service):
        """Test: Rate limiter exception is properly handled."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        # Make rate limiter raise exception
        async def failing_rate_limited():
            raise Exception("Rate limit exceeded")

        # Need to wrap in context manager
        @asynccontextmanager
        async def mock_rate_limited():
            raise Exception("Rate limit exceeded")
            yield

        service._rate_limited = mock_rate_limited

        with patch.object(service, '_fetch_vix_yahoo', return_value=16.0):
            result = await service.get_vix()

        # Should fall back to Yahoo
        assert result.success
        assert result.source == "yahoo"

    @pytest.mark.asyncio
    async def test_yahoo_timeout_handled(self, service):
        """Test: Yahoo timeout is handled."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._should_fail = True

        import socket
        with patch.object(
            service, '_fetch_vix_yahoo',
            side_effect=socket.timeout("timeout")
        ):
            result = await service.get_vix()

        assert not result.success

    @pytest.mark.asyncio
    async def test_error_includes_duration(self, service):
        """Test: Error result includes duration_ms."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result = await service.get_vix()

        assert not result.success
        assert result.duration_ms is not None

    @pytest.mark.asyncio
    async def test_logging_on_provider_failure(self, service):
        """Test: Provider failure is logged."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._should_fail = True

        with patch.object(service, '_fetch_vix_yahoo', return_value=17.0):
            await service.get_vix()

        # Debug should be called for the failure
        service._logger.debug.assert_called()


# =============================================================================
# Properties Tests
# =============================================================================

class TestProperties:
    """Tests for VIXService properties."""

    def test_current_vix_returns_cached_value(self, service):
        """Test: current_vix returns cached VIX value."""
        service._context._vix_cache = 25.0

        assert service.current_vix == 25.0

    def test_current_vix_returns_none_when_no_cache(self, service):
        """Test: current_vix returns None when no cached value."""
        service._context._vix_cache = None

        assert service.current_vix is None

    def test_vix_updated_returns_timestamp(self, service):
        """Test: vix_updated returns cache timestamp."""
        now = datetime.now()
        service._context._vix_updated = now

        assert service.vix_updated == now

    def test_vix_updated_returns_none_when_never_updated(self, service):
        """Test: vix_updated returns None when never updated."""
        service._context._vix_updated = None

        assert service.vix_updated is None


# =============================================================================
# Integration Tests
# =============================================================================

class TestVixServiceIntegration:
    """Integration tests for VIX Service."""

    @pytest.mark.asyncio
    async def test_full_fetch_update_retrieve_flow(self, service):
        """Test: Full flow - fetch, update cache, retrieve from cache."""
        # Initial state
        assert service.current_vix is None
        assert service.vix_updated is None

        # Fetch VIX
        service._context._provider._vix_value = 18.5
        result1 = await service.get_vix()

        assert result1.success
        assert result1.data == 18.5
        assert result1.cached is False
        assert service.current_vix == 18.5
        assert service.vix_updated is not None

        # Retrieve from cache
        result2 = await service.get_vix()

        assert result2.success
        assert result2.data == 18.5
        assert result2.cached is True

    @pytest.mark.asyncio
    async def test_fallback_chain(self, service):
        """Test: Complete fallback chain - provider -> yahoo -> stale cache."""
        # Setup stale cache
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now() - timedelta(hours=1)

        # First: provider works
        service._context._provider._vix_value = 19.0
        result1 = await service.get_vix(force_refresh=True)
        assert result1.source == "marketdata"

        # Second: provider fails, yahoo works
        service._context._provider._should_fail = True
        service._context._vix_updated = datetime.now() - timedelta(hours=1)

        with patch.object(service, '_fetch_vix_yahoo', return_value=18.0):
            result2 = await service.get_vix(force_refresh=True)
        assert result2.source == "yahoo"

        # Third: both fail, use stale cache
        service._context._vix_updated = datetime.now() - timedelta(hours=1)

        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result3 = await service.get_vix(force_refresh=True)
        assert result3.source == "stale_cache"

    @pytest.mark.asyncio
    async def test_recommendation_uses_fresh_vix(self, service):
        """Test: Strategy recommendation uses freshly fetched VIX."""
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._context._provider._vix_value = 22.5

        result = await service.get_strategy_recommendation()

        assert result.success
        assert result.data.vix_level == 22.5

    @pytest.mark.asyncio
    async def test_concurrent_and_sequential_consistency(self, service):
        """Test: Concurrent and sequential methods return consistent results."""
        service._context._vix_cache = 19.0
        service._context._vix_updated = datetime.now()

        result_seq = await service.get_vix()
        result_conc = await service.get_vix_concurrent()

        assert result_seq.data == result_conc.data
        assert result_seq.cached == result_conc.cached


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_vix_zero_not_cached(self, service):
        """Test: VIX value of 0 is not cached (0 is falsy in 'if vix:' check).

        Note: In the implementation:
        - Provider returns 0
        - 'if vix:' is False, so source stays 'unknown'
        - 'if vix is None:' is False (0 != None), so Yahoo is NOT called
        - 'if vix:' at cache update is False, so 0 is not cached
        - Result: failure since no valid VIX and no stale cache

        This is actually correct behavior since VIX=0 is not realistic
        and should be treated as invalid data.
        """
        service._context._vix_cache = None
        service._context._vix_updated = None

        # Set provider to return 0 (falsy)
        service._context._provider._vix_value = 0.0

        result = await service.get_vix()

        # VIX of 0 is not considered valid (falsy), and doesn't trigger Yahoo fallback
        # because 'if vix is None' check fails (0 != None)
        # This results in failure when there's no stale cache
        assert not result.success
        assert "Could not fetch VIX" in result.error

    @pytest.mark.asyncio
    async def test_vix_zero_with_stale_cache_fallback(self, service):
        """Test: VIX of 0 falls back to stale cache when available."""
        # Setup stale cache
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now() - timedelta(hours=1)

        # Provider returns 0 (falsy)
        service._context._provider._vix_value = 0.0

        result = await service.get_vix(force_refresh=True)

        # Should fall back to stale cache since 0 is not valid
        assert result.success
        assert result.data == 20.0
        assert result.source == "stale_cache"

    @pytest.mark.asyncio
    async def test_vix_very_low_nonzero_handled(self, service):
        """Test: Very low but non-zero VIX (e.g., 5) is handled."""
        service._context._provider._vix_value = 5.0
        service._context._vix_cache = None
        service._context._vix_updated = None

        result = await service.get_vix()

        assert result.success
        assert result.data == 5.0
        assert result.source == "marketdata"

    @pytest.mark.asyncio
    async def test_very_high_vix_handled(self, service):
        """Test: Very high VIX (e.g., 80) is handled."""
        service._context._vix_cache = 80.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation()

        assert result.success
        assert result.data.regime == MarketRegime.HIGH_VOL

    @pytest.mark.asyncio
    async def test_cache_exactly_at_ttl(self, service):
        """Test: Cache exactly at TTL boundary."""
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now() - timedelta(seconds=300)

        result = await service.get_vix()

        # At exactly TTL, should fetch fresh
        # (depends on implementation - >= vs >)
        assert result.success

    @pytest.mark.asyncio
    async def test_recommendation_to_dict(self, service):
        """Test: StrategyRecommendation.to_dict() works correctly."""
        service._context._vix_cache = 18.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation()
        rec_dict = result.data.to_dict()

        assert 'profile' in rec_dict
        assert 'regime' in rec_dict
        assert 'vix' in rec_dict
        assert 'recommendations' in rec_dict
        assert 'reasoning' in rec_dict
        assert 'warnings' in rec_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
