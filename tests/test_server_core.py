# OptionPlay - Server Core Tests
# ================================
"""
Tests für ServerCore Service-Koordinator.

Testet:
- Factory Methods
- Service Lazy Loading
- Connection Lifecycle
- State Integration
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.services.server_core import ServerCore
from src.state import ServerState, ConnectionStatus


class TestServerCoreFactory:
    """Tests für ServerCore Factory Methods."""

    def test_create_for_testing(self):
        """create_for_testing should create minimal instance."""
        core = ServerCore.create_for_testing()

        assert core._api_key == "test_key"
        assert isinstance(core.state, ServerState)
        assert not core.is_connected

    def test_create_for_testing_with_state(self):
        """create_for_testing should accept custom state."""
        custom_state = ServerState()
        custom_state.request_count = 42

        core = ServerCore.create_for_testing(state=custom_state)

        assert core.state.request_count == 42

    def test_create_for_testing_with_container(self):
        """create_for_testing should accept mock container."""
        mock_container = Mock()

        core = ServerCore.create_for_testing(container=mock_container)

        assert core.container == mock_container


class TestServerCoreServices:
    """Tests für Service Lazy Loading."""

    def test_quotes_service_lazy_loaded(self):
        """quotes property should lazy-load QuoteService."""
        core = ServerCore.create_for_testing()

        assert core._quote_service is None

        # Access should trigger creation
        quotes = core.quotes

        assert quotes is not None
        assert core._quote_service is not None

    def test_options_service_lazy_loaded(self):
        """options property should lazy-load OptionsService."""
        core = ServerCore.create_for_testing()

        options = core.options

        assert options is not None
        assert core._options_service is not None

    def test_vix_service_lazy_loaded(self):
        """vix property should lazy-load VIXService."""
        core = ServerCore.create_for_testing()

        vix = core.vix

        assert vix is not None
        assert core._vix_service is not None

    def test_scanner_service_lazy_loaded(self):
        """scanner property should lazy-load ScannerService."""
        core = ServerCore.create_for_testing()

        scanner = core.scanner

        assert scanner is not None
        assert core._scanner_service is not None

    def test_services_cached(self):
        """Services should be cached after first access."""
        core = ServerCore.create_for_testing()

        quotes1 = core.quotes
        quotes2 = core.quotes

        assert quotes1 is quotes2


class TestServerCoreConnection:
    """Tests für Connection Lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_updates_state(self):
        """connect should update connection state."""
        core = ServerCore.create_for_testing()

        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.connect = AsyncMock(return_value=True)

        with patch.object(core, '_provider', mock_provider):
            # Skip actual provider creation
            core._provider = mock_provider
            result = await core.connect()

        assert result is True
        assert core.state.connection.is_connected

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """connect should return early if already connected."""
        core = ServerCore.create_for_testing()
        core.state.connection.mark_connected()

        result = await core.connect()

        assert result is True

    @pytest.mark.asyncio
    async def test_disconnect_updates_state(self):
        """disconnect should update connection state."""
        core = ServerCore.create_for_testing()
        core.state.connection.mark_connected()

        mock_provider = AsyncMock()
        mock_provider.disconnect = AsyncMock()
        core._provider = mock_provider

        await core.disconnect()

        assert core.state.connection.status == ConnectionStatus.DISCONNECTED

    def test_is_connected_property(self):
        """is_connected should reflect state."""
        core = ServerCore.create_for_testing()

        assert not core.is_connected

        core.state.connection.mark_connected()
        assert core.is_connected


class TestServerCoreContextManager:
    """Tests für Async Context Manager."""

    @pytest.mark.asyncio
    async def test_context_manager_connects(self):
        """__aenter__ should connect."""
        core = ServerCore.create_for_testing()

        # Mock connect
        core.connect = AsyncMock(return_value=True)
        core.disconnect = AsyncMock()

        async with core as ctx:
            assert ctx is core
            core.connect.assert_called_once()

        core.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_disconnects_on_exception(self):
        """__aexit__ should disconnect even on exception."""
        core = ServerCore.create_for_testing()
        core.connect = AsyncMock(return_value=True)
        core.disconnect = AsyncMock()

        try:
            async with core:
                raise ValueError("test error")
        except ValueError:
            pass

        core.disconnect.assert_called_once()


class TestServerCoreHealth:
    """Tests für Health & Stats."""

    def test_health_summary(self):
        """health_summary should return state summary."""
        core = ServerCore.create_for_testing()
        core.state.connection.mark_connected()
        core.state.vix.update(18.5)

        summary = core.health_summary()

        assert summary["status"] == "healthy"
        assert summary["connected"] is True
        assert summary["vix"] == 18.5

    def test_get_stats(self):
        """get_stats should return detailed statistics."""
        core = ServerCore.create_for_testing()
        core.state.record_request()

        stats = core.get_stats()

        assert "connection" in stats
        assert "vix" in stats
        assert "caches" in stats
        assert stats["request_count"] == 1

    def test_record_request(self):
        """record_request should increment state counter."""
        core = ServerCore.create_for_testing()

        core.record_request()
        core.record_request()

        assert core.state.request_count == 2


class TestServerCoreConvenience:
    """Tests für Convenience Methods."""

    @pytest.mark.asyncio
    async def test_get_vix_uses_cache(self):
        """get_vix should use cached value if not stale."""
        core = ServerCore.create_for_testing()
        core.state.vix.update(18.5)

        # Should return cached value without calling service
        vix = await core.get_vix()

        assert vix == 18.5

    @pytest.mark.asyncio
    async def test_get_vix_force_refresh(self):
        """get_vix with force_refresh should call service."""
        core = ServerCore.create_for_testing()
        core.state.vix.update(18.5)

        # Mock VIX service
        mock_result = Mock()
        mock_result.success = True
        mock_result.data = {"vix": 20.0}
        core._vix_service = Mock()
        core._vix_service.get_vix = AsyncMock(return_value=mock_result)

        vix = await core.get_vix(force_refresh=True)

        assert vix == 20.0
        assert core.state.vix.current_value == 20.0

    @pytest.mark.asyncio
    async def test_get_quote_tracks_cache(self):
        """get_quote should track cache metrics."""
        core = ServerCore.create_for_testing()

        # Mock quote service
        mock_result = Mock()
        mock_result.success = True
        mock_result.data = {"symbol": "AAPL", "price": 150.0}
        core._quote_service = Mock()
        core._quote_service.get_quote = AsyncMock(return_value=mock_result)

        result = await core.get_quote("AAPL")

        assert result is not None
        assert core.state.quote_cache.hits == 1

    @pytest.mark.asyncio
    async def test_get_quote_tracks_miss(self):
        """get_quote should track cache misses on failure."""
        core = ServerCore.create_for_testing()

        # Mock failed quote
        mock_result = Mock()
        mock_result.success = False
        mock_result.data = None
        core._quote_service = Mock()
        core._quote_service.get_quote = AsyncMock(return_value=mock_result)

        result = await core.get_quote("INVALID")

        assert result is None
        assert core.state.quote_cache.misses == 1


class TestServerCoreIntegration:
    """Integration tests für ServerCore."""

    def test_full_state_lifecycle(self):
        """Test complete state management through ServerCore."""
        core = ServerCore.create_for_testing()

        # Initial state
        assert not core.is_connected
        assert core.state.vix.is_stale
        assert core.state.request_count == 0

        # Simulate operations
        core.state.connection.mark_connected()
        core.state.vix.update(18.5)
        core.record_request()

        # Check state
        health = core.health_summary()
        assert health["status"] == "healthy"
        assert health["vix"] == 18.5

        stats = core.get_stats()
        assert stats["request_count"] == 1

    def test_provider_not_initialized(self):
        """provider property should be None initially."""
        core = ServerCore.create_for_testing()

        assert core.provider is None
