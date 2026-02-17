# Tests for IBKR Bridge Module
# =============================

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# nest_asyncio is required by ibkr_bridge at import time
pytest.importorskip("nest_asyncio", reason="nest_asyncio not installed")


class TestSymbolMapping:
    """Tests for IBKR symbol mapping functions."""

    def test_to_ibkr_symbol_standard(self):
        """Test standard symbols pass through unchanged."""
        from src.ibkr.bridge import to_ibkr_symbol

        assert to_ibkr_symbol("AAPL") == "AAPL"
        assert to_ibkr_symbol("MSFT") == "MSFT"
        assert to_ibkr_symbol("GOOGL") == "GOOGL"

    def test_to_ibkr_symbol_berkshire(self):
        """Test Berkshire Hathaway symbol mapping."""
        from src.ibkr.bridge import to_ibkr_symbol

        assert to_ibkr_symbol("BRK.B") == "BRK B"
        assert to_ibkr_symbol("BRK.A") == "BRK A"

    def test_to_ibkr_symbol_delisted(self):
        """Test delisted symbols return None."""
        from src.ibkr.bridge import to_ibkr_symbol

        assert to_ibkr_symbol("PARA") is None
        assert to_ibkr_symbol("PXD") is None

    def test_to_ibkr_symbol_case_insensitive(self):
        """Test symbol mapping is case insensitive."""
        from src.ibkr.bridge import to_ibkr_symbol

        assert to_ibkr_symbol("aapl") == "AAPL"
        assert to_ibkr_symbol("Aapl") == "AAPL"
        assert to_ibkr_symbol("brk.b") == "BRK B"

    def test_from_ibkr_symbol_reverse(self):
        """Test reverse symbol mapping."""
        from src.ibkr.bridge import from_ibkr_symbol

        assert from_ibkr_symbol("BRK B") == "BRK.B"
        assert from_ibkr_symbol("BRK A") == "BRK.A"

    def test_from_ibkr_symbol_unchanged(self):
        """Test unmapped symbols pass through."""
        from src.ibkr.bridge import from_ibkr_symbol

        assert from_ibkr_symbol("AAPL") == "AAPL"
        assert from_ibkr_symbol("MSFT") == "MSFT"


class TestIBKRSymbolMap:
    """Tests for symbol mapping constants."""

    def test_symbol_map_contains_berkshire(self):
        """Test IBKR_SYMBOL_MAP contains Berkshire."""
        from src.ibkr.bridge import IBKR_SYMBOL_MAP

        assert "BRK.B" in IBKR_SYMBOL_MAP
        assert "BRK.A" in IBKR_SYMBOL_MAP

    def test_reverse_map_exists(self):
        """Test reverse mapping is created."""
        from src.ibkr.bridge import IBKR_REVERSE_MAP

        assert "BRK B" in IBKR_REVERSE_MAP
        assert IBKR_REVERSE_MAP["BRK B"] == "BRK.B"


class TestIBKRBridgeInit:
    """Tests for IBKRBridge initialization."""

    def test_bridge_can_be_instantiated(self):
        """Test IBKRBridge can be created."""
        from src.ibkr.bridge import IBKRBridge

        bridge = IBKRBridge()
        assert bridge is not None
        assert bridge._connected == False

    def test_bridge_has_required_attributes(self):
        """Test IBKRBridge has required attributes."""
        from src.ibkr.bridge import IBKRBridge

        bridge = IBKRBridge()

        assert hasattr(bridge, '_ib')
        assert hasattr(bridge, '_connected')
        assert hasattr(bridge, '_last_check')

    def test_bridge_default_state(self):
        """Test IBKRBridge default state."""
        from src.ibkr.bridge import IBKRBridge

        bridge = IBKRBridge()

        assert bridge._connected == False
        assert bridge._ib is None


class TestIBKRBridgeMethods:
    """Tests for IBKRBridge method signatures."""

    def test_has_is_available_method(self):
        """Test has is_available method."""
        from src.ibkr.bridge import IBKRBridge

        assert hasattr(IBKRBridge, 'is_available')

    def test_has_disconnect_method(self):
        """Test has disconnect method."""
        from src.ibkr.bridge import IBKRBridge

        assert hasattr(IBKRBridge, 'disconnect')

    def test_has_get_news_method(self):
        """Test has get_news method."""
        from src.ibkr.bridge import IBKRBridge

        assert hasattr(IBKRBridge, 'get_news')

    def test_has_get_vix_method(self):
        """Test has get_vix method."""
        from src.ibkr.bridge import IBKRBridge

        assert hasattr(IBKRBridge, 'get_vix')

    def test_has_get_portfolio_method(self):
        """Test has get_portfolio method."""
        from src.ibkr.bridge import IBKRBridge

        assert hasattr(IBKRBridge, 'get_portfolio')

    def test_has_get_spreads_method(self):
        """Test has get_spreads method."""
        from src.ibkr.bridge import IBKRBridge

        assert hasattr(IBKRBridge, 'get_spreads')

    def test_has_get_status_method(self):
        """Test has get_status method."""
        from src.ibkr.bridge import IBKRBridge

        assert hasattr(IBKRBridge, 'get_status')


class TestIBKRBridgeFormatting:
    """Tests for IBKR Bridge formatting methods."""

    def test_has_formatted_methods(self):
        """Test has formatting methods."""
        from src.ibkr.bridge import IBKRBridge

        assert hasattr(IBKRBridge, 'get_status_formatted')
        assert hasattr(IBKRBridge, 'get_portfolio_formatted')
        assert hasattr(IBKRBridge, 'get_spreads_formatted')
        assert hasattr(IBKRBridge, 'get_news_formatted')


class TestIBKRBridgeAsync:
    """Tests for IBKRBridge async methods."""

    @pytest.mark.asyncio
    async def test_get_status_returns_dict(self):
        """Test get_status returns dict with expected keys."""
        from src.ibkr.bridge import IBKRBridge

        bridge = IBKRBridge()
        result = await bridge.get_status()

        assert isinstance(result, dict)
        assert "connected" in result
        assert isinstance(result["connected"], bool)

    @pytest.mark.asyncio
    async def test_get_status_formatted_when_disconnected(self):
        """Test get_status_formatted returns string when disconnected."""
        from src.ibkr.bridge import IBKRBridge

        bridge = IBKRBridge()
        result = await bridge.get_status_formatted()

        assert isinstance(result, str)
        assert "IBKR" in result or "Status" in result

    @pytest.mark.asyncio
    async def test_get_portfolio_formatted_when_disconnected(self):
        """Test get_portfolio_formatted returns string when disconnected."""
        from src.ibkr.bridge import IBKRBridge

        bridge = IBKRBridge()
        result = await bridge.get_portfolio_formatted()

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_get_spreads_formatted_when_disconnected(self):
        """Test get_spreads_formatted returns string when disconnected."""
        from src.ibkr.bridge import IBKRBridge

        bridge = IBKRBridge()
        result = await bridge.get_spreads_formatted()

        assert isinstance(result, str)


class TestGetIBKRBridge:
    """Tests for get_ibkr_bridge singleton function."""

    def test_get_ibkr_bridge_returns_instance(self):
        """Test get_ibkr_bridge returns IBKRBridge instance."""
        from src.ibkr.bridge import get_ibkr_bridge, IBKRBridge

        bridge = get_ibkr_bridge()

        assert isinstance(bridge, IBKRBridge)

    def test_get_ibkr_bridge_singleton(self):
        """Test get_ibkr_bridge returns same instance."""
        from src.ibkr.bridge import get_ibkr_bridge

        bridge1 = get_ibkr_bridge()
        bridge2 = get_ibkr_bridge()

        assert bridge1 is bridge2


class TestCheckIBKRAvailable:
    """Tests for check_ibkr_available function."""

    @pytest.mark.asyncio
    async def test_check_available_returns_bool(self):
        """Test check returns boolean."""
        from src.ibkr.bridge import check_ibkr_available

        result = await check_ibkr_available()

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_check_available_consistent_with_status(self):
        """Test check_ibkr_available is consistent with get_status."""
        from src.ibkr.bridge import check_ibkr_available, get_ibkr_bridge

        available = await check_ibkr_available()
        bridge = get_ibkr_bridge()
        status = await bridge.get_status()

        # Should be consistent
        assert available == status["connected"]
