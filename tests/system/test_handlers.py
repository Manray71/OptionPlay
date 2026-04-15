# Tests for MCP Server Handler Modules
# =====================================

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, datetime


class TestVixHandler:
    """Tests for VIX handler methods."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock server with VIX handler methods."""
        from src.handlers.vix import VixHandlerMixin

        class MockServer(VixHandlerMixin):
            def __init__(self):
                self._current_vix = 18.5
                self._vix_updated = datetime.now()
                self._vix_source = "test"
                self._config = MagicMock()
                self._config.settings.api_connection.vix_cache_seconds = 60
                self._rate_limiter = MagicMock()
                self._rate_limiter.acquire = AsyncMock()
                self._rate_limiter.record_success = MagicMock()

            async def _ensure_connected(self):
                provider = MagicMock()
                provider.get_vix = AsyncMock(return_value=18.5)
                return provider

            async def _get_quote_cached(self, symbol):
                return None

        return MockServer()

    @pytest.mark.asyncio
    async def test_get_vix_returns_cached(self, mock_server):
        """Test VIX returns cached value when fresh."""
        result = await mock_server.get_vix()

        assert result == 18.5

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_format(self, mock_server):
        """Test strategy recommendation returns markdown."""
        with patch.object(mock_server, 'get_vix', AsyncMock(return_value=18.5)):
            result = await mock_server.get_strategy_recommendation()

        assert "Strategy Recommendation" in result
        assert "VIX" in result


class TestScanHandler:
    """Tests for scan handler methods."""

    @pytest.fixture
    def mock_scanner(self):
        """Create mock scanner."""
        scanner = MagicMock()
        scanner.scan_pullback_candidates = AsyncMock(return_value=[])
        return scanner

    @pytest.mark.asyncio
    async def test_scan_validates_symbols(self):
        """Test scan validates input symbols."""
        from src.handlers.scan import ScanHandlerMixin

        class MockServer(ScanHandlerMixin):
            async def get_vix(self):
                return 18.0

            async def _fetch_historical_cached(self, symbol, days):
                return None

        server = MockServer()

        # Invalid symbols should be handled gracefully
        result = await server.scan_with_strategy(
            symbols=["!!!INVALID"],
            max_results=5
        )

        # Should return result (possibly with errors) not raise
        assert isinstance(result, str)


class TestQuoteHandler:
    """Tests for quote handler methods."""

    @pytest.mark.asyncio
    async def test_get_quote_validates_symbol(self):
        """Test quote validates symbol format."""
        from src.handlers.quote import QuoteHandlerMixin

        class MockServer(QuoteHandlerMixin):
            async def _get_quote_cached(self, symbol):
                return MagicMock(last=100.0, bid=99.95, ask=100.05, volume=1000000)

        server = MockServer()

        # Invalid symbol should return error
        result = await server.get_quote("123INVALID")
        assert "Validation Error" in result or "Error" in result

    @pytest.mark.asyncio
    async def test_get_quote_formats_response(self):
        """Test quote formats response correctly."""
        from src.handlers.quote import QuoteHandlerMixin

        class MockServer(QuoteHandlerMixin):
            async def _get_quote_cached(self, symbol):
                quote = MagicMock()
                quote.last = 185.50
                quote.bid = 185.45
                quote.ask = 185.55
                quote.volume = 50000000
                quote.change = 2.5
                quote.change_pct = 1.37
                return quote

        server = MockServer()
        result = await server.get_quote("AAPL")

        assert "Quote: AAPL" in result
        assert "185.50" in result


class TestAnalysisHandler:
    """Tests for analysis handler methods."""

    @pytest.mark.asyncio
    async def test_analyze_symbol_validates_input(self):
        """Test symbol analysis validates input."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class MockServer(AnalysisHandlerMixin):
            pass

        server = MockServer()

        # Invalid symbol should return error
        result = await server.analyze_symbol("!!!INVALID")
        assert "Validation Error" in result or "Error" in result


class TestHandlerIntegration:
    """Integration tests for handler mixins."""

    def test_all_handlers_can_be_mixed(self):
        """Test all handlers can be combined into single class."""
        from src.handlers import (
            BaseHandlerMixin,
            VixHandlerMixin,
            ScanHandlerMixin,
            QuoteHandlerMixin,
            AnalysisHandlerMixin,
        )

        # This should not raise
        class CombinedServer(
            VixHandlerMixin,
            ScanHandlerMixin,
            QuoteHandlerMixin,
            AnalysisHandlerMixin,
            BaseHandlerMixin,
        ):
            pass

        server = CombinedServer()
        assert server is not None

    def test_handler_method_names_exist(self):
        """Test key handler methods exist."""
        from src.handlers import (
            VixHandlerMixin,
            QuoteHandlerMixin,
        )

        # Check VIX handler has key methods
        assert hasattr(VixHandlerMixin, 'get_vix')
        assert hasattr(VixHandlerMixin, 'get_strategy_recommendation')

        # Check Quote handler has key methods
        assert hasattr(QuoteHandlerMixin, 'get_quote')
        assert hasattr(QuoteHandlerMixin, 'get_options_chain')
