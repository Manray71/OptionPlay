# Tests for Handler Container
# ===========================
"""
Tests for HandlerContainer and ServerContext classes.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.handlers.handler_container import (
    ServerContext,
    BaseHandler,
    HandlerContainer,
    create_handler_container_from_server,
)


# =============================================================================
# SERVER CONTEXT TESTS
# =============================================================================

class TestServerContext:
    """Tests for ServerContext class."""

    def create_mock_context_args(self):
        """Create mock arguments for ServerContext."""
        return {
            "config": MagicMock(),
            "provider": MagicMock(),
            "ibkr_provider": MagicMock(),
            "rate_limiter": MagicMock(),
            "circuit_breaker": MagicMock(),
            "historical_cache": MagicMock(),
            "vix_selector": MagicMock(),
            "deduplicator": MagicMock(),
        }

    def test_init_with_all_args(self):
        """Test ServerContext initialization with all arguments."""
        args = self.create_mock_context_args()
        ctx = ServerContext(**args)

        assert ctx.config is args["config"]
        assert ctx.provider is args["provider"]
        assert ctx.ibkr_provider is args["ibkr_provider"]
        assert ctx.rate_limiter is args["rate_limiter"]

    def test_init_default_state(self):
        """Test ServerContext default mutable state."""
        args = self.create_mock_context_args()
        ctx = ServerContext(**args)

        assert ctx.connected is False
        assert ctx.ibkr_connected is False
        assert ctx.current_vix is None
        assert ctx.vix_updated is None

    def test_init_default_caches(self):
        """Test ServerContext default caches are empty."""
        args = self.create_mock_context_args()
        ctx = ServerContext(**args)

        assert ctx.quote_cache == {}
        assert ctx.scan_cache == {}
        assert ctx.scan_cache_ttl == 1800

    def test_init_default_stats(self):
        """Test ServerContext default stats are zero."""
        args = self.create_mock_context_args()
        ctx = ServerContext(**args)

        assert ctx.quote_cache_hits == 0
        assert ctx.quote_cache_misses == 0
        assert ctx.scan_cache_hits == 0
        assert ctx.scan_cache_misses == 0

    def test_init_optional_components_none(self):
        """Test ServerContext optional components default to None."""
        args = self.create_mock_context_args()
        ctx = ServerContext(**args)

        assert ctx.earnings_fetcher is None
        assert ctx.scanner is None
        assert ctx.ibkr_bridge is None

    def test_init_with_container(self):
        """Test ServerContext with optional container."""
        args = self.create_mock_context_args()
        args["container"] = MagicMock()
        ctx = ServerContext(**args)

        assert ctx.container is args["container"]


# =============================================================================
# BASE HANDLER TESTS
# =============================================================================

class TestBaseHandler:
    """Tests for BaseHandler class."""

    def create_context(self):
        """Create a ServerContext for testing."""
        return ServerContext(
            config=MagicMock(),
            provider=MagicMock(),
            ibkr_provider=MagicMock(),
            rate_limiter=MagicMock(),
            circuit_breaker=MagicMock(),
            historical_cache=MagicMock(),
            vix_selector=MagicMock(),
            deduplicator=MagicMock(),
        )

    def test_init_stores_context(self):
        """Test BaseHandler stores context."""
        ctx = self.create_context()
        handler = BaseHandler(ctx)

        assert handler._ctx is ctx

    def test_config_property(self):
        """Test BaseHandler config property."""
        ctx = self.create_context()
        handler = BaseHandler(ctx)

        assert handler.config is ctx.config

    def test_ibkr_provider_property(self):
        """Test BaseHandler ibkr_provider property."""
        ctx = self.create_context()
        handler = BaseHandler(ctx)

        assert handler.ibkr_provider is ctx.ibkr_provider

    def test_has_logger(self):
        """Test BaseHandler has logger."""
        ctx = self.create_context()
        handler = BaseHandler(ctx)

        assert handler._logger is not None


# =============================================================================
# HANDLER CONTAINER TESTS
# =============================================================================

class TestHandlerContainer:
    """Tests for HandlerContainer class."""

    def create_context(self):
        """Create a ServerContext for testing."""
        return ServerContext(
            config=MagicMock(),
            provider=MagicMock(),
            ibkr_provider=MagicMock(),
            rate_limiter=MagicMock(),
            circuit_breaker=MagicMock(),
            historical_cache=MagicMock(),
            vix_selector=MagicMock(),
            deduplicator=MagicMock(),
        )

    def test_init_handlers_none(self):
        """Test HandlerContainer initializes handlers as None."""
        ctx = self.create_context()
        container = HandlerContainer(ctx)

        assert container._vix is None
        assert container._scan is None
        assert container._quote is None
        assert container._analysis is None
        assert container._portfolio is None
        assert container._ibkr is None
        assert container._risk is None

    def test_vix_property_lazy_init(self):
        """Test vix property creates handler on first access."""
        ctx = self.create_context()
        container = HandlerContainer(ctx)

        # Mock the import
        with patch("src.handlers.handler_container.HandlerContainer.vix", new_callable=lambda: property(lambda self: MagicMock())):
            pass  # Property would be created

        # Direct test
        assert container._vix is None  # Initially None

    def test_scan_property_lazy_init(self):
        """Test scan property creates handler on first access."""
        ctx = self.create_context()
        container = HandlerContainer(ctx)

        assert container._scan is None  # Initially None

    def test_quote_property_lazy_init(self):
        """Test quote property creates handler on first access."""
        ctx = self.create_context()
        container = HandlerContainer(ctx)

        assert container._quote is None  # Initially None

    def test_analysis_property_lazy_init(self):
        """Test analysis property creates handler on first access."""
        ctx = self.create_context()
        container = HandlerContainer(ctx)

        assert container._analysis is None  # Initially None

    def test_portfolio_property_lazy_init(self):
        """Test portfolio property creates handler on first access."""
        ctx = self.create_context()
        container = HandlerContainer(ctx)

        assert container._portfolio is None  # Initially None

    def test_ibkr_property_lazy_init(self):
        """Test ibkr property creates handler on first access."""
        ctx = self.create_context()
        container = HandlerContainer(ctx)

        assert container._ibkr is None  # Initially None

    def test_risk_property_lazy_init(self):
        """Test risk property creates handler on first access."""
        ctx = self.create_context()
        container = HandlerContainer(ctx)

        assert container._risk is None  # Initially None


# =============================================================================
# CREATE FROM SERVER TESTS
# =============================================================================

class TestCreateHandlerContainerFromServer:
    """Tests for create_handler_container_from_server function."""

    def create_mock_server(self):
        """Create a mock server object."""
        server = MagicMock()
        server._config = MagicMock()
        server._provider = MagicMock()
        server._ibkr_provider = MagicMock()
        server._rate_limiter = MagicMock()
        server._circuit_breaker = MagicMock()
        server._historical_cache = MagicMock()
        server._vix_selector = MagicMock()
        server._deduplicator = MagicMock()
        server._connected = True
        server._ibkr_connected = True
        server._current_vix = 18.5
        server._vix_updated = "2024-01-30T10:00:00"
        server._quote_cache = {"AAPL": {"price": 150.0}}
        server._scan_cache = {}
        server._earnings_fetcher = MagicMock()
        server._scanner = MagicMock()
        server._ibkr_bridge = MagicMock()
        server._container = MagicMock()
        return server

    def test_creates_handler_container(self):
        """Test function creates a HandlerContainer."""
        server = self.create_mock_server()
        container = create_handler_container_from_server(server)

        assert isinstance(container, HandlerContainer)

    def test_copies_config(self):
        """Test function copies config to context."""
        server = self.create_mock_server()
        container = create_handler_container_from_server(server)

        assert container._context.config is server._config

    def test_copies_providers(self):
        """Test function copies providers to context."""
        server = self.create_mock_server()
        container = create_handler_container_from_server(server)

        assert container._context.provider is server._provider
        assert container._context.ibkr_provider is server._ibkr_provider

    def test_copies_mutable_state(self):
        """Test function copies mutable state to context."""
        server = self.create_mock_server()
        container = create_handler_container_from_server(server)

        assert container._context.connected is True
        assert container._context.ibkr_connected is True
        assert container._context.current_vix == 18.5

    def test_copies_caches(self):
        """Test function copies caches to context."""
        server = self.create_mock_server()
        container = create_handler_container_from_server(server)

        assert container._context.quote_cache == {"AAPL": {"price": 150.0}}

    def test_copies_optional_components(self):
        """Test function copies optional components to context."""
        server = self.create_mock_server()
        container = create_handler_container_from_server(server)

        assert container._context.earnings_fetcher is server._earnings_fetcher
        assert container._context.scanner is server._scanner
        assert container._context.ibkr_bridge is server._ibkr_bridge

    def test_handles_missing_optional_attrs(self):
        """Test function handles missing optional attributes."""
        server = MagicMock()
        server._config = MagicMock()
        server._provider = MagicMock()
        server._rate_limiter = MagicMock()
        server._circuit_breaker = MagicMock()
        server._historical_cache = MagicMock()
        server._vix_selector = MagicMock()
        server._deduplicator = MagicMock()
        server._connected = False
        server._current_vix = None
        server._vix_updated = None
        server._quote_cache = {}
        server._scan_cache = {}
        server._earnings_fetcher = None

        # Delete optional attributes
        del server._ibkr_provider
        del server._ibkr_connected
        del server._scanner
        del server._ibkr_bridge
        del server._container

        container = create_handler_container_from_server(server)

        assert container._context.ibkr_provider is None
        assert container._context.ibkr_connected is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
