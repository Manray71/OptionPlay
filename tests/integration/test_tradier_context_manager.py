# OptionPlay - TradierProvider Context Manager Tests
# ====================================================
# Tests für Fix #6: TradierProvider Async Context Manager

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.data_providers.tradier import TradierProvider, TradierConfig


class TestTradierContextManager:
    """
    Tests für Fix #6: TradierProvider Async Context Manager
    
    Implementiert __aenter__ und __aexit__ damit Sessions
    automatisch geschlossen werden.
    """
    
    @pytest.fixture
    def mock_config(self):
        """Mock Tradier Config"""
        return TradierConfig(api_key="test_api_key")
    
    @pytest.mark.asyncio
    async def test_context_manager_exists(self):
        """Test: Context Manager Methoden existieren"""
        provider = TradierProvider(api_key="test_key")
        
        assert hasattr(provider, '__aenter__')
        assert hasattr(provider, '__aexit__')
    
    @pytest.mark.asyncio
    async def test_context_manager_returns_self(self):
        """Test: __aenter__ gibt self zurück"""
        provider = TradierProvider(api_key="test_key")
        
        # Mock connect
        provider.connect = AsyncMock()
        
        async with provider as p:
            assert p is provider
        
        # Cleanup
        if provider._session and not provider._session.closed:
            await provider._session.close()
    
    @pytest.mark.asyncio
    async def test_context_manager_calls_connect(self):
        """Test: Context Manager ruft connect() auf"""
        provider = TradierProvider(api_key="test_key")
        
        connect_called = False
        original_connect = provider.connect
        
        async def mock_connect():
            nonlocal connect_called
            connect_called = True
        
        provider.connect = mock_connect
        provider.disconnect = AsyncMock()
        
        async with provider:
            pass
        
        assert connect_called
    
    @pytest.mark.asyncio
    async def test_context_manager_calls_disconnect_on_exit(self):
        """Test: Context Manager ruft disconnect() beim Exit auf"""
        provider = TradierProvider(api_key="test_key")
        
        disconnect_called = False
        
        async def mock_disconnect():
            nonlocal disconnect_called
            disconnect_called = True
        
        provider.connect = AsyncMock()
        provider.disconnect = mock_disconnect
        
        async with provider:
            pass
        
        assert disconnect_called
    
    @pytest.mark.asyncio
    async def test_context_manager_closes_on_exception(self):
        """Test: Context Manager schließt auch bei Exception"""
        provider = TradierProvider(api_key="test_key")
        
        disconnect_called = False
        
        async def mock_disconnect():
            nonlocal disconnect_called
            disconnect_called = True
        
        provider.connect = AsyncMock()
        provider.disconnect = mock_disconnect
        
        with pytest.raises(ValueError):
            async with provider:
                raise ValueError("Test exception")
        
        assert disconnect_called
    
    @pytest.mark.asyncio
    async def test_double_disconnect_is_safe(self):
        """Test: Mehrfaches disconnect() ist sicher"""
        provider = TradierProvider(api_key="test_key")
        
        provider.connect = AsyncMock()
        
        # Manuelles disconnect, dann context manager exit
        async with provider:
            await provider.disconnect()
        
        # Sollte nicht crashen


class TestTradierConnectionManagement:
    """Tests für Connection Management"""
    
    @pytest.mark.asyncio
    async def test_disconnect_sets_connected_false(self):
        """Test: disconnect() setzt _connected auf False"""
        provider = TradierProvider(api_key="test_key")
        provider._connected = True

        await provider.disconnect()

        assert provider._connected is False
    
    @pytest.mark.asyncio
    async def test_disconnect_handles_none_session(self):
        """Test: disconnect() mit None Session crasht nicht"""
        provider = TradierProvider(api_key="test_key")
        provider._session = None
        
        # Sollte nicht crashen
        await provider.disconnect()
    
    @pytest.mark.asyncio
    async def test_disconnect_handles_already_closed_session(self):
        """Test: disconnect() mit bereits geschlossener Session"""
        provider = TradierProvider(api_key="test_key")
        
        mock_session = MagicMock()
        mock_session.closed = True
        provider._session = mock_session
        
        # Sollte nicht crashen
        await provider.disconnect()


class TestTradierUsagePatterns:
    """Tests für typische Verwendungsmuster"""
    
    @pytest.mark.asyncio
    async def test_recommended_usage_pattern(self):
        """Test: Empfohlenes Verwendungsmuster mit context manager"""
        
        # So sollte der Provider verwendet werden:
        # async with TradierProvider(api_key) as provider:
        #     chain = await provider.get_option_chain("AAPL")
        
        provider = TradierProvider(api_key="test_key")
        provider.connect = AsyncMock()
        provider.disconnect = AsyncMock()
        
        async with provider as p:
            # Simuliere API-Nutzung
            assert p is not None
        
        provider.connect.assert_called_once()
        provider.disconnect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_manual_usage_still_works(self):
        """Test: Manuelle Verwendung funktioniert noch"""
        provider = TradierProvider(api_key="test_key")
        provider.connect = AsyncMock()
        provider.disconnect = AsyncMock()
        
        # Alte Methode: manuelles connect/disconnect
        await provider.connect()
        # ... API calls ...
        await provider.disconnect()
        
        provider.connect.assert_called_once()
        provider.disconnect.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
