# OptionPlay - MarketData Provider Tests
# ========================================

import pytest
import asyncio
import sys
from pathlib import Path
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.data_providers.marketdata import (
    MarketDataProvider,
    MarketDataConfig,
    get_marketdata_provider
)
from src.data_providers.interface import DataQuality


# =============================================================================
# Mock Response Data
# =============================================================================

MOCK_QUOTE_RESPONSE = {
    "s": "ok",
    "symbol": ["AAPL"],
    "last": [175.50],
    "bid": [175.40],
    "ask": [175.60],
    "volume": [45000000]
}

MOCK_CANDLES_RESPONSE = {
    "s": "ok",
    "o": [170.0, 172.0, 174.0],
    "h": [172.0, 175.0, 176.0],
    "l": [169.0, 171.0, 173.0],
    "c": [171.0, 174.0, 175.0],
    "v": [1000000, 1200000, 1100000],
    "t": [1704067200, 1704153600, 1704240000]  # Jan 1-3, 2024
}

MOCK_OPTIONS_CHAIN_RESPONSE = {
    "s": "ok",
    "optionSymbol": ["AAPL250321P00170000", "AAPL250321P00175000"],
    "strike": [170.0, 175.0],
    "expiration": [1742515200, 1742515200],  # March 21, 2025
    "side": ["put", "put"],
    "bid": [2.50, 4.20],
    "ask": [2.70, 4.40],
    "last": [2.60, 4.30],
    "volume": [1500, 2000],
    "openInterest": [5000, 8000],
    "iv": [0.32, 0.30],
    "delta": [-0.28, -0.45],
    "gamma": [0.015, 0.020],
    "theta": [-0.05, -0.07],
    "vega": [0.25, 0.30]
}

MOCK_EXPIRATIONS_RESPONSE = {
    "s": "ok",
    "expirations": [1742515200, 1745020800, 1747612800]  # March, April, May 2025
}

MOCK_STATUS_RESPONSE = {
    "s": "ok",
    "service": ["/v1/stocks/quotes/"],
    "status": ["online"]
}


# =============================================================================
# Configuration Tests
# =============================================================================

class TestMarketDataConfig:
    """Tests für MarketDataConfig"""
    
    def test_default_config(self):
        """Default Config sollte korrekte Werte haben"""
        config = MarketDataConfig(api_key="test_key")
        
        assert config.api_key == "test_key"
        assert config.base_url == "https://api.marketdata.app"
        assert config.timeout_seconds == 30
        assert config.max_retries == 3
    
    def test_headers_include_auth(self):
        """Headers sollten Bearer Token enthalten"""
        config = MarketDataConfig(api_key="my_api_key")
        
        headers = config.headers
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer my_api_key"


# =============================================================================
# Provider Initialization Tests
# =============================================================================

class TestProviderInitialization:
    """Tests für Provider-Initialisierung"""
    
    def test_provider_name(self):
        """Provider Name sollte korrekt sein"""
        provider = MarketDataProvider(api_key="test")
        assert provider.name == "marketdata"
    
    def test_supported_features(self):
        """Supported Features sollten korrekt sein"""
        provider = MarketDataProvider(api_key="test")
        features = provider.supported_features
        
        assert "quotes" in features
        assert "historical" in features
        assert "options" in features
        assert "earnings" in features


# =============================================================================
# Quote Parsing Tests
# =============================================================================

class TestQuoteParsing:
    """Tests für Quote-Parsing"""
    
    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test")
    
    def test_parse_quote(self, provider):
        """Quote sollte korrekt geparst werden"""
        quote = provider._parse_quote("AAPL", MOCK_QUOTE_RESPONSE)
        
        assert quote.symbol == "AAPL"
        assert quote.last == 175.50
        assert quote.bid == 175.40
        assert quote.ask == 175.60
        assert quote.volume == 45000000
        assert quote.source == "marketdata"
        assert quote.data_quality == DataQuality.REALTIME


# =============================================================================
# Candle Parsing Tests
# =============================================================================

class TestCandleParsing:
    """Tests für Candle-Parsing"""
    
    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test")
    
    def test_parse_candles(self, provider):
        """Candles sollten korrekt geparst werden"""
        bars = provider._parse_candles("AAPL", MOCK_CANDLES_RESPONSE, 100)
        
        assert len(bars) == 3
        
        # Erste Bar prüfen
        bar = bars[0]
        assert bar.symbol == "AAPL"
        assert bar.open == 170.0
        assert bar.high == 172.0
        assert bar.low == 169.0
        assert bar.close == 171.0
        assert bar.volume == 1000000
        assert bar.source == "marketdata"
    
    def test_candles_sorted_by_date(self, provider):
        """Candles sollten nach Datum sortiert sein"""
        bars = provider._parse_candles("AAPL", MOCK_CANDLES_RESPONSE, 100)
        
        dates = [bar.date for bar in bars]
        assert dates == sorted(dates)


# =============================================================================
# Options Chain Parsing Tests
# =============================================================================

class TestOptionsChainParsing:
    """Tests für Options-Chain-Parsing"""
    
    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test")
    
    def test_parse_option_chain(self, provider):
        """Options-Chain sollte korrekt geparst werden"""
        options = provider._parse_option_chain(
            "AAPL", 
            MOCK_OPTIONS_CHAIN_RESPONSE,
            175.50
        )
        
        assert len(options) == 2
        
        # Erste Option prüfen
        opt = options[0]
        assert opt.underlying == "AAPL"
        assert opt.strike == 170.0
        assert opt.right == "P"
        assert opt.bid == 2.50
        assert opt.ask == 2.70
        assert opt.implied_volatility == 0.32
        assert opt.delta == -0.28
        assert opt.source == "marketdata"


# =============================================================================
# Helper Method Tests
# =============================================================================

class TestHelperMethods:
    """Tests für Helper-Methoden"""
    
    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test")
    
    def test_safe_float_valid(self, provider):
        """safe_float sollte gültige Werte konvertieren"""
        assert provider._safe_float(3.14) == 3.14
        assert provider._safe_float("2.5") == 2.5
        assert provider._safe_float(0) == 0.0
    
    def test_safe_float_invalid(self, provider):
        """safe_float sollte None bei ungültigen Werten zurückgeben"""
        assert provider._safe_float(None) is None
        assert provider._safe_float("invalid") is None
    
    def test_safe_int_valid(self, provider):
        """safe_int sollte gültige Werte konvertieren"""
        assert provider._safe_int(42) == 42
        assert provider._safe_int("100") == 100
    
    def test_safe_int_invalid(self, provider):
        """safe_int sollte None bei ungültigen Werten zurückgeben"""
        assert provider._safe_int(None) is None
        assert provider._safe_int("invalid") is None
    
    def test_safe_get_first_array(self, provider):
        """safe_get_first sollte erstes Element aus Array holen"""
        assert provider._safe_get_first([1, 2, 3]) == 1
        assert provider._safe_get_first([]) is None
    
    def test_safe_get_first_scalar(self, provider):
        """safe_get_first sollte Skalar zurückgeben"""
        assert provider._safe_get_first(42) == 42
        assert provider._safe_get_first(None) is None


# =============================================================================
# Integration Tests (mit Mocks)
# =============================================================================

class TestIntegration:
    """Integration Tests mit gemockten HTTP-Calls"""
    
    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")
    
    @pytest.mark.asyncio
    async def test_connect_success(self, provider):
        """Connect sollte bei erfolgreicher Statusprüfung True zurückgeben"""
        with patch.object(provider, '_get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = MOCK_STATUS_RESPONSE
            
            result = await provider.connect()
            
            assert result == True
            assert provider._connected == True
    
    @pytest.mark.asyncio
    async def test_connect_failure(self, provider):
        """Connect sollte bei Fehler False zurückgeben"""
        with patch.object(provider, '_get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            
            result = await provider.connect()
            
            assert result == False
            assert provider._connected == False
    
    @pytest.mark.asyncio
    async def test_get_historical_for_scanner(self, provider):
        """get_historical_for_scanner sollte Tuple zurückgeben"""
        with patch.object(provider, 'get_historical', new_callable=AsyncMock) as mock:
            # Erstelle Mock-Bars
            from src.data_providers.interface import HistoricalBar
            from datetime import timedelta
            base_date = date(2024, 1, 1)
            mock_bars = [
                HistoricalBar(
                    symbol="AAPL",
                    date=base_date + timedelta(days=i),
                    open=170 + i,
                    high=172 + i,
                    low=169 + i,
                    close=171 + i,
                    volume=1000000,
                    source="marketdata"
                )
                for i in range(60)
            ]
            mock.return_value = mock_bars
            
            result = await provider.get_historical_for_scanner("AAPL")

            assert result is not None
            prices, volumes, highs, lows, opens = result
            assert len(prices) == 60
            assert len(volumes) == 60
            assert len(highs) == 60
            assert len(lows) == 60
            assert len(opens) == 60
    
    @pytest.mark.asyncio
    async def test_context_manager(self, provider):
        """Context Manager sollte connect/disconnect aufrufen"""
        with patch.object(provider, 'connect', new_callable=AsyncMock) as mock_connect:
            with patch.object(provider, 'disconnect', new_callable=AsyncMock) as mock_disconnect:
                mock_connect.return_value = True
                
                async with provider:
                    pass
                
                mock_connect.assert_called_once()
                mock_disconnect.assert_called_once()


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests für Factory-Funktionen"""
    
    def test_get_marketdata_provider_requires_key(self):
        """get_marketdata_provider sollte ohne Key Fehler werfen"""
        # Reset global provider
        import src.data_providers.marketdata as md
        md._default_provider = None
        
        with pytest.raises(ValueError):
            get_marketdata_provider()
    
    def test_get_marketdata_provider_with_key(self):
        """get_marketdata_provider sollte mit Key Provider zurückgeben"""
        import src.data_providers.marketdata as md
        md._default_provider = None
        
        provider = get_marketdata_provider(api_key="test_key")
        
        assert provider is not None
        assert provider.config.api_key == "test_key"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
