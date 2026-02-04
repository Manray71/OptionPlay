# Tests for ServiceContainer
# ===========================

import pytest
from unittest.mock import Mock, AsyncMock, patch

from src.container import (
    ServiceContainer,
    get_container,
    set_container,
    reset_container,
)


class TestServiceContainerCreation:
    """Tests for container creation methods."""

    def test_create_minimal(self):
        """Test minimal container has config."""
        container = ServiceContainer.create_minimal()

        assert container.config is not None
        assert container.provider is None
        assert container.rate_limiter is None

    def test_create_default(self):
        """Test default container has all services."""
        container = ServiceContainer.create_default()

        assert container.config is not None
        assert container.rate_limiter is not None
        assert container.circuit_breaker is not None
        assert container.historical_cache is not None
        assert container.earnings_fetcher is not None

    def test_create_for_testing_with_mocks(self):
        """Test container accepts mock services."""
        mock_provider = Mock()
        mock_rate_limiter = Mock()

        container = ServiceContainer.create_for_testing(
            provider=mock_provider,
            rate_limiter=mock_rate_limiter,
        )

        assert container.provider is mock_provider
        assert container.rate_limiter is mock_rate_limiter

    def test_create_for_testing_with_overrides(self):
        """Test container accepts arbitrary overrides."""
        mock_cache = Mock()

        container = ServiceContainer.create_for_testing(
            historical_cache=mock_cache,
        )

        assert container.historical_cache is mock_cache


class TestServiceContainerProvider:
    """Tests for provider management."""

    @pytest.mark.asyncio
    async def test_ensure_provider_creates_provider(self):
        """Test ensure_provider creates provider if None."""
        container = ServiceContainer.create_minimal()

        with patch('src.data_providers.marketdata.MarketDataProvider') as MockProvider:
            mock_instance = AsyncMock()
            mock_instance.is_connected = AsyncMock(return_value=False)
            mock_instance.connect = AsyncMock()
            MockProvider.return_value = mock_instance

            with patch('src.utils.secure_config.get_api_key', return_value='test_key'):
                provider = await container.ensure_provider()

            assert provider is mock_instance
            mock_instance.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_provider_reuses_existing(self):
        """Test ensure_provider reuses existing provider."""
        mock_provider = AsyncMock()
        mock_provider.connected = True

        container = ServiceContainer.create_for_testing(provider=mock_provider)

        provider = await container.ensure_provider()

        assert provider is mock_provider
        mock_provider.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnect calls provider disconnect."""
        mock_provider = AsyncMock()
        mock_provider.disconnect = AsyncMock()

        container = ServiceContainer.create_for_testing(provider=mock_provider)

        await container.disconnect()

        mock_provider.disconnect.assert_called_once()


class TestServiceContainerStats:
    """Tests for stats collection."""

    def test_get_stats_with_rate_limiter(self):
        """Test stats includes rate limiter stats."""
        mock_limiter = Mock()
        mock_limiter.stats.return_value = {'calls': 100}

        container = ServiceContainer.create_for_testing(rate_limiter=mock_limiter)

        stats = container.get_stats()

        assert 'rate_limiter' in stats
        assert stats['rate_limiter']['calls'] == 100

    def test_get_stats_with_circuit_breaker(self):
        """Test stats includes circuit breaker stats."""
        mock_breaker = Mock()
        mock_breaker.stats.return_value = {'state': 'closed'}

        container = ServiceContainer.create_for_testing(circuit_breaker=mock_breaker)

        stats = container.get_stats()

        assert 'circuit_breaker' in stats
        assert stats['circuit_breaker']['state'] == 'closed'

    def test_get_stats_empty_container(self):
        """Test stats with empty container."""
        container = ServiceContainer()

        stats = container.get_stats()

        assert stats == {}


class TestServiceContainerReset:
    """Tests for reset functionality."""

    def test_reset_calls_service_resets(self):
        """Test reset calls reset on all services."""
        mock_limiter = Mock()
        mock_breaker = Mock()
        mock_cache = Mock()

        container = ServiceContainer.create_for_testing(
            rate_limiter=mock_limiter,
            circuit_breaker=mock_breaker,
            historical_cache=mock_cache,
        )

        container.reset()

        mock_limiter.reset.assert_called_once()
        mock_breaker.reset.assert_called_once()
        mock_cache.clear.assert_called_once()


class TestGlobalContainer:
    """Tests for global container management."""

    def teardown_method(self):
        """Reset global container after each test."""
        reset_container()

    def test_get_container_creates_default(self):
        """Test get_container creates default container."""
        container = get_container()

        assert container is not None
        assert container.config is not None

    def test_get_container_returns_same_instance(self):
        """Test get_container returns same instance."""
        container1 = get_container()
        container2 = get_container()

        assert container1 is container2

    def test_set_container_replaces_global(self):
        """Test set_container replaces global container."""
        mock_container = ServiceContainer()
        set_container(mock_container)

        retrieved = get_container()

        assert retrieved is mock_container

    def test_reset_container_clears_global(self):
        """Test reset_container clears global container."""
        _ = get_container()  # Create default
        reset_container()

        # Next call should create new container
        with patch.object(ServiceContainer, 'create_default') as mock_create:
            mock_create.return_value = ServiceContainer()
            _ = get_container()
            mock_create.assert_called_once()


class TestContainerIntegration:
    """Integration tests for container with real services."""

    def test_default_container_services_work_together(self):
        """Test services in default container are properly wired."""
        container = ServiceContainer.create_default()

        # Rate limiter should have correct config
        assert container.rate_limiter.calls_per_minute > 0

        # Circuit breaker should be configured
        assert container.circuit_breaker.failure_threshold > 0

        # Caches should be initialized
        assert container.historical_cache is not None
        assert container.earnings_cache is not None

    def test_container_config_propagates(self):
        """Test container config values are used by services."""
        container = ServiceContainer.create_default()

        # Circuit breaker should use config values
        config_threshold = container.config.settings.circuit_breaker.failure_threshold
        assert container.circuit_breaker.failure_threshold == config_threshold
