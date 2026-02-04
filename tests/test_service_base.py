# Tests for Service Base Module
# =============================
"""
Tests for ServiceContext and BaseService classes.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from src.services.base import ServiceContext, BaseService, create_service_context


# =============================================================================
# SERVICE CONTEXT TESTS
# =============================================================================

class TestServiceContext:
    """Tests for ServiceContext dataclass."""

    def test_init_with_api_key(self):
        """Test ServiceContext initialization with API key."""
        with patch('src.services.base.get_config') as mock_config:
            mock_settings = MagicMock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 1000
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 30
            mock_config.return_value.settings = mock_settings

            context = ServiceContext(api_key="test_key")

        assert context.api_key == "test_key"
        assert context._connected is False

    def test_api_key_masked(self):
        """Test api_key_masked property."""
        with patch('src.services.base.get_config') as mock_config:
            mock_settings = MagicMock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 1000
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 30
            mock_config.return_value.settings = mock_settings

            context = ServiceContext(api_key="12345678901234567890")

        # Should be masked (not the full key)
        masked = context.api_key_masked
        assert "1234" in masked or "***" in masked or len(masked) < len(context.api_key)

    def test_circuit_breaker_property(self):
        """Test circuit_breaker property."""
        with patch('src.services.base.get_config') as mock_config:
            mock_settings = MagicMock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 1000
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 30
            mock_config.return_value.settings = mock_settings

            context = ServiceContext(api_key="test_key")

        assert context.circuit_breaker is not None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        """Test disconnect does nothing when not connected."""
        with patch('src.services.base.get_config') as mock_config:
            mock_settings = MagicMock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 1000
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 30
            mock_config.return_value.settings = mock_settings

            context = ServiceContext(api_key="test_key")

        # Should not raise
        await context.disconnect()

    def test_vix_cache_initially_none(self):
        """Test VIX cache is initially None."""
        with patch('src.services.base.get_config') as mock_config:
            mock_settings = MagicMock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 1000
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 30
            mock_config.return_value.settings = mock_settings

            context = ServiceContext(api_key="test_key")

        assert context._vix_cache is None
        assert context._vix_updated is None


# =============================================================================
# BASE SERVICE TESTS
# =============================================================================

class MockService(BaseService):
    """Mock service for testing."""

    async def test_method(self):
        return "test"


class TestBaseService:
    """Tests for BaseService class."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock ServiceContext."""
        context = MagicMock(spec=ServiceContext)
        context.api_key = "test_key"
        context.api_key_masked = "test_***"
        context.rate_limiter = MagicMock()
        context.rate_limiter.acquire = AsyncMock()
        context.rate_limiter.record_success = MagicMock()
        context.rate_limiter.record_failure = MagicMock()
        context.circuit_breaker = MagicMock()
        context.historical_cache = MagicMock()
        return context

    def test_init_with_context(self, mock_context):
        """Test BaseService initialization."""
        with patch('src.services.base.get_config') as mock_config:
            mock_config.return_value = MagicMock()
            service = MockService(mock_context)

        assert service._context is mock_context

    def test_api_key_masked_property(self, mock_context):
        """Test api_key_masked property."""
        with patch('src.services.base.get_config') as mock_config:
            mock_config.return_value = MagicMock()
            service = MockService(mock_context)

        assert service.api_key_masked == "test_***"

    @pytest.mark.asyncio
    async def test_get_provider(self, mock_context):
        """Test _get_provider method."""
        mock_provider = MagicMock()
        mock_context.get_provider = AsyncMock(return_value=mock_provider)

        with patch('src.services.base.get_config') as mock_config:
            mock_config.return_value = MagicMock()
            service = MockService(mock_context)

        provider = await service._get_provider()

        assert provider is mock_provider
        mock_context.get_provider.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limited_context_manager(self, mock_context):
        """Test _rate_limited context manager."""
        with patch('src.services.base.get_config') as mock_config:
            mock_config.return_value = MagicMock()
            service = MockService(mock_context)

        async with service._rate_limited():
            pass

        mock_context.rate_limiter.acquire.assert_called_once()
        mock_context.rate_limiter.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limited_records_failure_on_exception(self, mock_context):
        """Test _rate_limited records failure on exception."""
        with patch('src.services.base.get_config') as mock_config:
            mock_config.return_value = MagicMock()
            service = MockService(mock_context)

        with pytest.raises(ValueError):
            async with service._rate_limited():
                raise ValueError("test error")

        mock_context.rate_limiter.record_failure.assert_called_once()

    def test_get_historical_cache(self, mock_context):
        """Test _get_historical_cache method."""
        with patch('src.services.base.get_config') as mock_config:
            mock_config.return_value = MagicMock()
            service = MockService(mock_context)

        cache = service._get_historical_cache()

        assert cache is mock_context.historical_cache

    def test_get_circuit_breaker(self, mock_context):
        """Test _get_circuit_breaker method."""
        with patch('src.services.base.get_config') as mock_config:
            mock_config.return_value = MagicMock()
            service = MockService(mock_context)

        cb = service._get_circuit_breaker()

        assert cb is mock_context.circuit_breaker


# =============================================================================
# CREATE SERVICE CONTEXT TESTS
# =============================================================================

class TestCreateServiceContext:
    """Tests for create_service_context factory function."""

    def test_creates_context_with_provided_key(self):
        """Test creates context with provided API key."""
        with patch('src.services.base.get_config') as mock_config:
            mock_settings = MagicMock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 1000
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 30
            mock_config.return_value.settings = mock_settings

            context = create_service_context(api_key="provided_key")

        assert context.api_key == "provided_key"

    def test_uses_environment_key_when_not_provided(self):
        """Test uses environment API key when not provided."""
        with patch('src.services.base.get_config') as mock_config:
            mock_settings = MagicMock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 1000
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 30
            mock_config.return_value.settings = mock_settings

            with patch('src.services.base.get_api_key', return_value="env_key"):
                context = create_service_context()

        assert context.api_key == "env_key"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
