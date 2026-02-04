# OptionPlay - VIX Service Tests
# ================================
# Tests für src/services/vix_service.py

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.vix_service import VIXService
from src.models.result import ServiceResult


# =============================================================================
# Mock Classes
# =============================================================================

class MockConfig:
    """Mock config for testing."""
    class Settings:
        class ApiConnection:
            yahoo_timeout = 5
            vix_cache_seconds = 300
        api_connection = ApiConnection()
    settings = Settings()


class MockProvider:
    """Mock data provider."""
    async def get_vix(self):
        return 18.5


class MockServiceContext:
    """Mock service context."""
    def __init__(self):
        self._vix_cache = None
        self._vix_updated = None
        self._provider = MockProvider()
        self._rate_limiter = MagicMock()


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_context():
    """Create a mock service context."""
    return MockServiceContext()


@pytest.fixture
def service(mock_context):
    """Create a VIX service with mock context."""
    # Patch the config and setup
    with patch.object(VIXService, '__init__', lambda self, ctx: None):
        svc = VIXService.__new__(VIXService)
        svc._context = mock_context
        svc._config = MockConfig()
        svc._logger = MagicMock()
        svc._vix_selector = MagicMock()
        return svc


# =============================================================================
# get_vix Tests
# =============================================================================

class TestGetVix:
    """Tests für get_vix()."""

    @pytest.mark.asyncio
    async def test_get_vix_returns_service_result(self, service):
        """Test: get_vix gibt ServiceResult zurück."""
        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock(return_value=AsyncMock().__aenter__())

        result = await service.get_vix()

        assert isinstance(result, ServiceResult)

    @pytest.mark.asyncio
    async def test_get_vix_uses_cache(self, service):
        """Test: Cache wird verwendet."""
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now()

        result = await service.get_vix()

        assert result.success
        assert result.data == 20.0
        assert result.cached == True
        assert result.source == "cache"

    @pytest.mark.asyncio
    async def test_get_vix_force_refresh(self, service):
        """Test: Force Refresh ignoriert Cache."""
        service._context._vix_cache = 20.0
        service._context._vix_updated = datetime.now()
        service._get_provider = AsyncMock(return_value=MockProvider())
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_vix(force_refresh=True)

        assert result.success
        assert result.data == 18.5  # From mock provider
        assert result.cached == False

    @pytest.mark.asyncio
    async def test_get_vix_stale_cache(self, service):
        """Test: Stale Cache wird verwendet wenn fetch fehlschlägt."""
        service._context._vix_cache = 22.0
        service._context._vix_updated = datetime.now() - timedelta(hours=1)  # Stale

        # Both fetches fail
        service._get_provider = AsyncMock(side_effect=Exception("Provider error"))
        service._fetch_vix_yahoo = MagicMock(return_value=None)

        result = await service.get_vix(force_refresh=True)

        assert result.success
        assert result.data == 22.0
        assert result.source == "stale_cache"

    @pytest.mark.asyncio
    async def test_get_vix_yahoo_fallback(self, service):
        """Test: Yahoo Fallback wenn Marketdata fehlschlägt."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        # Marketdata fails
        service._get_provider = AsyncMock(side_effect=Exception("Marketdata error"))

        # Yahoo succeeds (mock directly on the service)
        with patch.object(service, '_fetch_vix_yahoo', return_value=17.5):
            result = await service.get_vix()

        assert result.success
        assert result.data == 17.5
        assert result.source == "yahoo"

    @pytest.mark.asyncio
    async def test_get_vix_all_fail_no_cache(self, service):
        """Test: Fehler wenn alle Quellen fehlschlagen ohne Cache."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        service._get_provider = AsyncMock(side_effect=Exception("Provider error"))
        with patch.object(service, '_fetch_vix_yahoo', return_value=None):
            result = await service.get_vix()

        assert not result.success
        assert "Could not fetch VIX" in result.error

    @pytest.mark.asyncio
    async def test_get_vix_updates_cache(self, service):
        """Test: VIX wird gecached nach erfolgreichem Abruf."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        mock_provider = AsyncMock()
        mock_provider.get_vix = AsyncMock(return_value=16.5)
        service._get_provider = AsyncMock(return_value=mock_provider)
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_vix()

        assert result.success
        assert service._context._vix_cache == 16.5
        assert service._context._vix_updated is not None


# =============================================================================
# _fetch_vix_yahoo Tests
# =============================================================================

class TestFetchVixYahoo:
    """Tests für _fetch_vix_yahoo()."""

    def test_fetch_yahoo_success(self, service):
        """Test: Yahoo VIX erfolgreich abrufen."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"chart":{"result":[{"meta":{"regularMarketPrice":17.5}}]}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            vix = service._fetch_vix_yahoo()

        assert vix == 17.5

    def test_fetch_yahoo_fallback_to_closes(self, service):
        """Test: Fallback zu closes wenn regularMarketPrice fehlt."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"chart":{"result":[{"meta":{},"indicators":{"quote":[{"close":[16.0, 17.0, 18.0]}]}}]}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            vix = service._fetch_vix_yahoo()

        assert vix == 18.0  # Last close

    def test_fetch_yahoo_error(self, service):
        """Test: Fehler wird behandelt."""
        with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
            vix = service._fetch_vix_yahoo()

        assert vix is None


# =============================================================================
# get_vix_concurrent Tests
# =============================================================================

class TestGetVixConcurrent:
    """Tests für get_vix_concurrent()."""

    @pytest.mark.asyncio
    async def test_concurrent_uses_cache(self, service):
        """Test: Concurrent verwendet Cache."""
        service._context._vix_cache = 21.0
        service._context._vix_updated = datetime.now()

        result = await service.get_vix_concurrent()

        assert result.success
        assert result.data == 21.0
        assert result.cached == True

    @pytest.mark.asyncio
    async def test_concurrent_fetches_from_provider(self, service):
        """Test: Concurrent fetches from provider when no cache."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        mock_provider = AsyncMock()
        mock_provider.get_vix = AsyncMock(return_value=19.5)

        service._get_provider = AsyncMock(return_value=mock_provider)
        service._rate_limited = MagicMock()
        service._rate_limited.return_value.__aenter__ = AsyncMock()
        service._rate_limited.return_value.__aexit__ = AsyncMock()

        result = await service.get_vix_concurrent()

        assert result.success
        assert result.data == 19.5
        assert result.cached == False

    @pytest.mark.asyncio
    async def test_concurrent_stale_cache_fallback(self, service):
        """Test: Concurrent falls back to stale cache when both sources fail."""
        service._context._vix_cache = 23.0
        service._context._vix_updated = datetime.now() - timedelta(hours=1)

        # Both sources fail
        service._get_provider = AsyncMock(side_effect=Exception("Provider error"))
        service._fetch_vix_yahoo = MagicMock(return_value=None)

        result = await service.get_vix_concurrent()

        assert result.success
        assert result.data == 23.0
        assert result.source == "stale_cache"

    @pytest.mark.asyncio
    async def test_concurrent_all_fail_no_cache(self, service):
        """Test: Concurrent fails when all sources fail and no cache."""
        service._context._vix_cache = None
        service._context._vix_updated = None

        service._get_provider = AsyncMock(side_effect=Exception("Provider error"))
        service._fetch_vix_yahoo = MagicMock(return_value=None)

        result = await service.get_vix_concurrent()

        assert not result.success
        assert "Could not fetch VIX" in result.error


# =============================================================================
# get_strategy_recommendation Tests
# =============================================================================

class TestGetStrategyRecommendation:
    """Tests für get_strategy_recommendation()."""

    @pytest.mark.asyncio
    async def test_recommendation_with_vix(self, service):
        """Test: Recommendation mit VIX."""
        service._context._vix_cache = 18.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation()

        assert result.success
        assert result.data is not None
        # Check that recommendation has expected attributes
        assert hasattr(result.data, 'regime')
        assert hasattr(result.data, 'delta_target')

    @pytest.mark.asyncio
    async def test_recommendation_fallback(self, service):
        """Test: Recommendation mit Fallback VIX."""
        # No cache, fetch fails
        service._context._vix_cache = None
        service._context._vix_updated = None
        service._get_provider = AsyncMock(side_effect=Exception("Error"))
        service._fetch_vix_yahoo = MagicMock(return_value=None)

        result = await service.get_strategy_recommendation()

        assert result.success
        # Should have warning about using default
        assert len(result.warnings) > 0


# =============================================================================
# get_strategy_recommendation_formatted Tests
# =============================================================================

class TestGetStrategyRecommendationFormatted:
    """Tests für get_strategy_recommendation_formatted()."""

    @pytest.mark.asyncio
    async def test_formatted_recommendation(self, service):
        """Test: Formatierte Recommendation."""
        service._context._vix_cache = 19.0
        service._context._vix_updated = datetime.now()

        result = await service.get_strategy_recommendation_formatted()

        assert isinstance(result, str)
        # Should contain VIX information
        assert "VIX" in result or "Strategy" in result


# =============================================================================
# Properties Tests
# =============================================================================

class TestProperties:
    """Tests für Service Properties."""

    def test_current_vix(self, service):
        """Test: current_vix Property."""
        service._context._vix_cache = 25.0

        assert service.current_vix == 25.0

    def test_current_vix_none(self, service):
        """Test: current_vix Property None."""
        service._context._vix_cache = None

        assert service.current_vix is None

    def test_vix_updated(self, service):
        """Test: vix_updated Property."""
        now = datetime.now()
        service._context._vix_updated = now

        assert service.vix_updated == now


# =============================================================================
# Integration Tests
# =============================================================================

class TestVixServiceIntegration:
    """Integration Tests für VIX Service."""

    @pytest.mark.asyncio
    async def test_cache_update_flow(self, service):
        """Test: Cache Update Flow."""
        # Initial state - no cache
        assert service.current_vix is None

        # Set cache
        service._context._vix_cache = 18.5
        service._context._vix_updated = datetime.now()

        # Get from cache
        result = await service.get_vix()
        assert result.success
        assert result.data == 18.5
        assert result.cached == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
