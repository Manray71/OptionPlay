"""
Tests for the IBKR Handler module.

Tests cover:
- IbkrHandlerMixin class methods
- IBKR availability handling
- News, max pain, portfolio, spreads, VIX, and quotes endpoints
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.handlers.ibkr import IbkrHandlerMixin, IBKR_AVAILABLE


# =============================================================================
# FIXTURES
# =============================================================================


class MockIBKRHandler(IbkrHandlerMixin):
    """Mock handler class for testing."""

    def __init__(self):
        self._ibkr_bridge = None
        self._vix_service = MagicMock()


@pytest.fixture
def handler():
    """Create mock handler."""
    return MockIBKRHandler()


@pytest.fixture
def mock_ibkr_bridge():
    """Create mock IBKR bridge."""
    bridge = AsyncMock()
    bridge.host = "127.0.0.1"
    bridge.port = 7497
    bridge.is_available = AsyncMock(return_value=True)
    bridge.get_news_formatted = AsyncMock(return_value="# News\n- AAPL: Test headline")
    bridge.get_max_pain_formatted = AsyncMock(return_value="# Max Pain\nAAPL: $150")
    bridge.get_portfolio_formatted = AsyncMock(return_value="# Portfolio\n- 100 AAPL")
    bridge.get_spreads_formatted = AsyncMock(return_value="# Spreads\n- AAPL put spread")
    bridge.get_vix = AsyncMock(return_value={"value": 18.5, "source": "live"})
    bridge.get_quotes_batch_formatted = AsyncMock(return_value="# Quotes\nAAPL: $150")
    return bridge


# =============================================================================
# IBKR STATUS TESTS
# =============================================================================


class TestGetIbkrStatus:
    """Tests for get_ibkr_status method."""

    @pytest.mark.asyncio
    async def test_status_no_bridge(self, handler):
        """Test status when IBKR bridge not available."""
        handler._ibkr_bridge = None
        result = await handler.get_ibkr_status()
        assert "Not available" in result or "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_status_with_bridge_connected(self, handler, mock_ibkr_bridge):
        """Test status with connected IBKR bridge."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_status()
            assert "OK" in result or "Available" in result

    @pytest.mark.asyncio
    async def test_status_with_bridge_disconnected(self, handler, mock_ibkr_bridge):
        """Test status with disconnected IBKR bridge."""
        mock_ibkr_bridge.is_available = AsyncMock(return_value=False)
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_status()
            assert "Not available" in result or "not available" in result.lower()


# =============================================================================
# NEWS TESTS
# =============================================================================


class TestGetNews:
    """Tests for get_news method."""

    @pytest.mark.asyncio
    async def test_news_no_bridge(self, handler):
        """Test news when IBKR bridge not available."""
        result = await handler.get_news(["AAPL"])
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_news_bridge_unavailable(self, handler, mock_ibkr_bridge):
        """Test news when TWS not reachable."""
        mock_ibkr_bridge.is_available = AsyncMock(return_value=False)
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_news(["AAPL"])
            assert "not reachable" in result.lower()

    @pytest.mark.asyncio
    async def test_news_success(self, handler, mock_ibkr_bridge):
        """Test successful news fetch."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_news(["AAPL"], days=5)
            assert "AAPL" in result
            mock_ibkr_bridge.get_news_formatted.assert_called_once()

    @pytest.mark.asyncio
    async def test_news_validates_symbols(self, handler, mock_ibkr_bridge):
        """Test that symbols are validated."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            # Invalid symbols should be skipped
            result = await handler.get_news(["AAPL", "INVALID123!@#"], days=3)
            # Should still work with valid symbols
            mock_ibkr_bridge.get_news_formatted.assert_called()


# =============================================================================
# MAX PAIN TESTS
# =============================================================================


class TestGetMaxPain:
    """Tests for get_max_pain method."""

    @pytest.mark.asyncio
    async def test_max_pain_no_bridge(self, handler):
        """Test max pain when IBKR bridge not available."""
        result = await handler.get_max_pain(["AAPL"])
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_max_pain_bridge_unavailable(self, handler, mock_ibkr_bridge):
        """Test max pain when TWS not reachable."""
        mock_ibkr_bridge.is_available = AsyncMock(return_value=False)
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_max_pain(["AAPL"])
            assert "not reachable" in result.lower()

    @pytest.mark.asyncio
    async def test_max_pain_success(self, handler, mock_ibkr_bridge):
        """Test successful max pain calculation."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_max_pain(["AAPL", "MSFT"])
            mock_ibkr_bridge.get_max_pain_formatted.assert_called_once()


# =============================================================================
# PORTFOLIO TESTS
# =============================================================================


class TestGetIbkrPortfolio:
    """Tests for get_ibkr_portfolio method."""

    @pytest.mark.asyncio
    async def test_portfolio_no_bridge(self, handler):
        """Test portfolio when IBKR bridge not available."""
        result = await handler.get_ibkr_portfolio()
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_portfolio_bridge_unavailable(self, handler, mock_ibkr_bridge):
        """Test portfolio when TWS not reachable."""
        mock_ibkr_bridge.is_available = AsyncMock(return_value=False)
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_portfolio()
            assert "not reachable" in result.lower()

    @pytest.mark.asyncio
    async def test_portfolio_success(self, handler, mock_ibkr_bridge):
        """Test successful portfolio fetch."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_portfolio()
            mock_ibkr_bridge.get_portfolio_formatted.assert_called_once()


# =============================================================================
# SPREADS TESTS
# =============================================================================


class TestGetIbkrSpreads:
    """Tests for get_ibkr_spreads method."""

    @pytest.mark.asyncio
    async def test_spreads_no_bridge(self, handler):
        """Test spreads when IBKR bridge not available."""
        result = await handler.get_ibkr_spreads()
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_spreads_bridge_unavailable(self, handler, mock_ibkr_bridge):
        """Test spreads when TWS not reachable."""
        mock_ibkr_bridge.is_available = AsyncMock(return_value=False)
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_spreads()
            assert "not reachable" in result.lower()

    @pytest.mark.asyncio
    async def test_spreads_success(self, handler, mock_ibkr_bridge):
        """Test successful spreads fetch."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_spreads()
            mock_ibkr_bridge.get_spreads_formatted.assert_called_once()


# =============================================================================
# VIX TESTS
# =============================================================================


class TestGetIbkrVix:
    """Tests for get_ibkr_vix method."""

    @pytest.mark.asyncio
    async def test_vix_no_bridge(self, handler):
        """Test VIX when IBKR bridge not available (falls back to other source)."""
        handler.get_vix = AsyncMock(return_value=19.5)
        result = await handler.get_ibkr_vix()
        assert "VIX" in result
        assert "not available" in result.lower() or "Yahoo" in result or "Marketdata" in result

    @pytest.mark.asyncio
    async def test_vix_bridge_unavailable(self, handler, mock_ibkr_bridge):
        """Test VIX when TWS not reachable (falls back)."""
        mock_ibkr_bridge.is_available = AsyncMock(return_value=False)
        handler._ibkr_bridge = mock_ibkr_bridge
        handler.get_vix = AsyncMock(return_value=20.0)
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_vix()
            assert "VIX" in result

    @pytest.mark.asyncio
    async def test_vix_success(self, handler, mock_ibkr_bridge):
        """Test successful VIX fetch from IBKR."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_vix()
            assert "VIX" in result
            assert "IBKR" in result

    @pytest.mark.asyncio
    async def test_vix_ibkr_returns_none(self, handler, mock_ibkr_bridge):
        """Test VIX fallback when IBKR returns None."""
        mock_ibkr_bridge.get_vix = AsyncMock(return_value=None)
        handler._ibkr_bridge = mock_ibkr_bridge
        handler.get_vix = AsyncMock(return_value=21.0)
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_vix()
            assert "VIX" in result
            handler.get_vix.assert_called_once()


# =============================================================================
# QUOTES TESTS
# =============================================================================


class TestGetIbkrQuotes:
    """Tests for get_ibkr_quotes method."""

    @pytest.mark.asyncio
    async def test_quotes_no_bridge(self, handler):
        """Test quotes when IBKR bridge not available."""
        result = await handler.get_ibkr_quotes()
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_quotes_bridge_unavailable(self, handler, mock_ibkr_bridge):
        """Test quotes when TWS not reachable."""
        mock_ibkr_bridge.is_available = AsyncMock(return_value=False)
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_quotes()
            assert "not reachable" in result.lower()

    @pytest.mark.asyncio
    async def test_quotes_with_symbols(self, handler, mock_ibkr_bridge):
        """Test quotes with explicit symbols."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_quotes(symbols=["AAPL", "MSFT"])
            mock_ibkr_bridge.get_quotes_batch_formatted.assert_called_once()

    @pytest.mark.asyncio
    async def test_quotes_default_watchlist(self, handler, mock_ibkr_bridge):
        """Test quotes uses watchlist when no symbols provided."""
        handler._ibkr_bridge = mock_ibkr_bridge

        mock_loader = MagicMock()
        mock_loader.get_all_symbols.return_value = ["AAPL", "MSFT", "GOOGL"]

        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            with patch('src.handlers.ibkr.get_watchlist_loader', return_value=mock_loader):
                result = await handler.get_ibkr_quotes()
                mock_loader.get_all_symbols.assert_called_once()
                mock_ibkr_bridge.get_quotes_batch_formatted.assert_called_once()

    @pytest.mark.asyncio
    async def test_quotes_custom_batch_size(self, handler, mock_ibkr_bridge):
        """Test quotes with custom batch size."""
        handler._ibkr_bridge = mock_ibkr_bridge
        with patch('src.handlers.ibkr.IBKR_AVAILABLE', True):
            result = await handler.get_ibkr_quotes(
                symbols=["AAPL"],
                batch_size=25,
                pause_seconds=30
            )
            mock_ibkr_bridge.get_quotes_batch_formatted.assert_called_with(
                ["AAPL"], 25, 30
            )
