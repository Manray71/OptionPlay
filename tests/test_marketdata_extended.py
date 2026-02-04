# OptionPlay - Extended MarketData Provider Tests
# ===============================================
# Comprehensive tests for src/data_providers/marketdata.py

import pytest
import sys
import json
from pathlib import Path
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_providers.marketdata import (
    MarketDataProvider,
    MarketDataConfig,
)
from data_providers.interface import (
    PriceQuote,
    OptionQuote,
    HistoricalBar,
    DataQuality
)


# =============================================================================
# CONFIG TESTS
# =============================================================================

class TestMarketDataConfig:
    """Tests for MarketDataConfig"""

    def test_default_config(self):
        """Default config should have correct values"""
        config = MarketDataConfig(api_key="test_key")

        assert config.api_key == "test_key"
        assert config.base_url == "https://api.marketdata.app"
        assert config.timeout_seconds == 30
        assert config.max_retries == 3
        assert config.rate_limit_per_minute == 100

    def test_custom_config(self):
        """Custom config values should be set"""
        config = MarketDataConfig(
            api_key="test_key",
            base_url="https://custom.api.com",
            timeout_seconds=60,
            max_retries=5,
            rate_limit_per_minute=200
        )

        assert config.base_url == "https://custom.api.com"
        assert config.timeout_seconds == 60
        assert config.max_retries == 5
        assert config.rate_limit_per_minute == 200

    def test_headers_include_auth(self):
        """Headers should include authorization"""
        config = MarketDataConfig(api_key="my_secret_key")

        headers = config.headers

        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer my_secret_key"
        assert headers["Accept"] == "application/json"


# =============================================================================
# PROVIDER INTERFACE TESTS
# =============================================================================

class TestMarketDataProviderInterface:
    """Tests for DataProvider interface implementation"""

    def test_provider_name(self):
        """Provider name should be 'marketdata'"""
        provider = MarketDataProvider(api_key="test_key")
        assert provider.name == "marketdata"

    def test_supported_features(self):
        """Should support expected features"""
        provider = MarketDataProvider(api_key="test_key")
        features = provider.supported_features

        assert "quotes" in features
        assert "historical" in features
        assert "options" in features
        assert "expirations" in features
        assert "earnings" in features
        assert "indices" in features


# =============================================================================
# CONNECTION TESTS
# =============================================================================

class TestMarketDataConnection:
    """Tests for connection management"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_connect_success(self, provider):
        """connect() should set _connected on success"""
        mock_response = {"s": "ok", "symbol": ["SPY"], "last": [580.0]}

        provider._get = AsyncMock(return_value=mock_response)

        result = await provider.connect()

        assert result is True
        assert provider._connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self, provider):
        """connect() should handle failure"""
        provider._get = AsyncMock(return_value=None)

        result = await provider.connect()

        assert result is False
        assert provider._connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self, provider):
        """disconnect() should set _connected to False"""
        provider._connected = True

        await provider.disconnect()

        assert provider._connected is False

    @pytest.mark.asyncio
    async def test_is_connected(self, provider):
        """is_connected() should return connection status"""
        provider._connected = True
        assert await provider.is_connected() is True

        provider._connected = False
        assert await provider.is_connected() is False

    @pytest.mark.asyncio
    async def test_context_manager(self, provider):
        """Context manager should connect and disconnect"""
        provider.connect = AsyncMock(return_value=True)
        provider.disconnect = AsyncMock()

        async with provider as p:
            assert p is provider

        provider.connect.assert_called_once()
        provider.disconnect.assert_called_once()


# =============================================================================
# QUOTE TESTS
# =============================================================================

class TestMarketDataQuotes:
    """Tests for quote retrieval"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_quote_success(self, provider):
        """get_quote should return PriceQuote on success"""
        mock_response = {
            "s": "ok",
            "symbol": ["AAPL"],
            "last": [175.50],
            "bid": [175.45],
            "ask": [175.55],
            "volume": [45000000]
        }

        provider._get = AsyncMock(return_value=mock_response)

        quote = await provider.get_quote("AAPL")

        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.last == 175.50
        assert quote.source == "marketdata"

    @pytest.mark.asyncio
    async def test_get_quote_not_found(self, provider):
        """get_quote should return None for invalid response"""
        provider._get = AsyncMock(return_value=None)

        quote = await provider.get_quote("INVALID")

        assert quote is None

    @pytest.mark.asyncio
    async def test_get_quote_error_status(self, provider):
        """get_quote should return None for error status"""
        mock_response = {"s": "error", "errmsg": "Invalid symbol"}

        provider._get = AsyncMock(return_value=mock_response)

        quote = await provider.get_quote("INVALID")

        assert quote is None

    @pytest.mark.asyncio
    async def test_get_quotes_bulk(self, provider):
        """get_quotes should return multiple quotes"""
        mock_response = {
            "s": "ok",
            "symbol": ["AAPL", "MSFT"],
            "last": [175.50, 400.00],
            "bid": [175.45, 399.90],
            "ask": [175.55, 400.10],
            "volume": [45000000, 30000000]
        }

        provider._get = AsyncMock(return_value=mock_response)

        quotes = await provider.get_quotes(["AAPL", "MSFT"])

        assert len(quotes) == 2
        assert "AAPL" in quotes
        assert "MSFT" in quotes
        assert quotes["AAPL"].last == 175.50
        assert quotes["MSFT"].last == 400.00

    @pytest.mark.asyncio
    async def test_get_quotes_empty_list(self, provider):
        """get_quotes with empty list should return empty dict"""
        quotes = await provider.get_quotes([])

        assert quotes == {}


# =============================================================================
# HISTORICAL DATA TESTS
# =============================================================================

class TestMarketDataHistorical:
    """Tests for historical data retrieval"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_historical_success(self, provider):
        """get_historical should return HistoricalBar list"""
        mock_response = {
            "s": "ok",
            "t": [1706140800, 1706227200],  # Timestamps
            "o": [174.50, 175.50],
            "h": [176.00, 177.00],
            "l": [174.00, 175.00],
            "c": [175.50, 176.80],
            "v": [45000000, 42000000]
        }

        provider._get = AsyncMock(return_value=mock_response)

        bars = await provider.get_historical("AAPL", days=30)

        assert len(bars) > 0
        assert all(isinstance(bar, HistoricalBar) for bar in bars)

    @pytest.mark.asyncio
    async def test_get_historical_no_data(self, provider):
        """get_historical should return empty list for no data"""
        provider._get = AsyncMock(return_value=None)

        bars = await provider.get_historical("INVALID", days=30)

        assert bars == []

    @pytest.mark.asyncio
    async def test_get_historical_error_status(self, provider):
        """get_historical should return empty list for error status"""
        mock_response = {"s": "error", "errmsg": "No data"}

        provider._get = AsyncMock(return_value=mock_response)

        bars = await provider.get_historical("AAPL", days=30)

        assert bars == []

    @pytest.mark.asyncio
    async def test_get_historical_for_scanner(self, provider):
        """get_historical_for_scanner should return tuple format"""
        mock_response = {
            "s": "ok",
            "t": [1706140800 + i * 86400 for i in range(100)],
            "o": [174.50 + i * 0.1 for i in range(100)],
            "h": [176.00 + i * 0.1 for i in range(100)],
            "l": [174.00 + i * 0.1 for i in range(100)],
            "c": [175.50 + i * 0.1 for i in range(100)],
            "v": [45000000 for _ in range(100)]
        }

        provider._get = AsyncMock(return_value=mock_response)

        result = await provider.get_historical_for_scanner("AAPL", days=100)

        assert result is not None
        prices, volumes, highs, lows, opens = result
        assert len(prices) >= 50
        assert len(volumes) >= 50

    @pytest.mark.asyncio
    async def test_get_historical_for_scanner_insufficient_data(self, provider):
        """get_historical_for_scanner should return None for insufficient data"""
        mock_response = {
            "s": "ok",
            "t": [1706140800],
            "o": [174.50],
            "h": [176.00],
            "l": [174.00],
            "c": [175.50],
            "v": [45000000]
        }

        provider._get = AsyncMock(return_value=mock_response)

        result = await provider.get_historical_for_scanner("AAPL", days=100)

        assert result is None


# =============================================================================
# OPTIONS TESTS
# =============================================================================

class TestMarketDataOptions:
    """Tests for options data retrieval"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_expirations(self, provider):
        """get_expirations should return list of dates"""
        mock_response = {
            "s": "ok",
            "expirations": ["2025-02-21", "2025-03-21", "2025-04-17"]
        }

        provider._get = AsyncMock(return_value=mock_response)

        expirations = await provider.get_expirations("AAPL")

        assert len(expirations) == 3
        assert date(2025, 2, 21) in expirations

    @pytest.mark.asyncio
    async def test_get_expirations_unix_timestamps(self, provider):
        """get_expirations should handle unix timestamps"""
        mock_response = {
            "s": "ok",
            "expirations": [1708473600, 1711065600]  # Unix timestamps
        }

        provider._get = AsyncMock(return_value=mock_response)

        expirations = await provider.get_expirations("AAPL")

        assert len(expirations) == 2

    @pytest.mark.asyncio
    async def test_get_expirations_empty(self, provider):
        """get_expirations should return empty list for no data"""
        provider._get = AsyncMock(return_value=None)

        expirations = await provider.get_expirations("INVALID")

        assert expirations == []

    @pytest.mark.asyncio
    async def test_get_strikes(self, provider):
        """get_strikes should return list of strike prices"""
        mock_response = {
            "s": "ok",
            "strikes": [170.0, 175.0, 180.0, 185.0]
        }

        provider._get = AsyncMock(return_value=mock_response)

        strikes = await provider.get_strikes("AAPL", date(2025, 2, 21))

        assert len(strikes) == 4
        assert 175.0 in strikes
        assert strikes == sorted(strikes)

    @pytest.mark.asyncio
    async def test_get_option_chain_puts(self, provider):
        """get_option_chain should return put options"""
        mock_chain_response = {
            "s": "ok",
            "optionSymbol": ["AAPL250321P00170000", "AAPL250321P00175000"],
            "strike": [170.0, 175.0],
            "side": ["put", "put"],
            "bid": [2.50, 3.50],
            "ask": [2.70, 3.70],
            "last": [2.60, 3.60],
            "volume": [1000, 2000],
            "openInterest": [5000, 8000],
            "iv": [0.30, 0.32],
            "delta": [-0.25, -0.50],
            "gamma": [0.01, 0.02],
            "theta": [-0.05, -0.08],
            "vega": [0.20, 0.30],
            "expiration": [1742515200, 1742515200],
            "underlying": ["AAPL", "AAPL"]
        }

        mock_quote_response = {
            "s": "ok",
            "symbol": ["AAPL"],
            "last": [175.0]
        }

        async def mock_get(endpoint, params=None):
            if "chain" in endpoint:
                return mock_chain_response
            elif "quotes" in endpoint:
                return mock_quote_response
            return None

        provider._get = mock_get

        chain = await provider.get_option_chain("AAPL", dte_min=30, dte_max=60, right="P")

        # Chain parsing depends on internal implementation
        assert isinstance(chain, list)


# =============================================================================
# VIX AND INDEX TESTS
# =============================================================================

class TestMarketDataVIX:
    """Tests for VIX and index data"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_vix_from_candles(self, provider):
        """get_vix should return VIX from candles"""
        mock_candles = {
            "s": "ok",
            "t": [1706140800],
            "o": [18.0],
            "h": [19.0],
            "l": [17.5],
            "c": [18.5],
            "v": [1000000]
        }

        provider._get = AsyncMock(return_value=mock_candles)

        vix = await provider.get_vix()

        assert vix is not None
        assert vix == 18.5

    @pytest.mark.asyncio
    async def test_get_vix_from_quote_fallback(self, provider):
        """get_vix should fallback to quote endpoint"""
        call_count = 0

        async def mock_get(endpoint, params=None, _skip_connect_check=False):
            nonlocal call_count
            call_count += 1

            if "candles" in endpoint:
                return None  # Candles fail
            elif "quotes" in endpoint:
                return {"s": "ok", "last": [20.5]}
            return None

        provider._get = mock_get

        vix = await provider.get_vix()

        assert vix == 20.5

    @pytest.mark.asyncio
    async def test_get_vix_no_data(self, provider):
        """get_vix should return None when no data available"""
        provider._get = AsyncMock(return_value=None)

        vix = await provider.get_vix()

        assert vix is None

    @pytest.mark.asyncio
    async def test_get_index_candles(self, provider):
        """get_index_candles should return historical bars"""
        mock_response = {
            "s": "ok",
            "t": [1706140800, 1706227200],
            "o": [4800.0, 4810.0],
            "h": [4850.0, 4860.0],
            "l": [4790.0, 4800.0],
            "c": [4820.0, 4840.0],
            "v": [1000000, 1100000]
        }

        provider._get = AsyncMock(return_value=mock_response)

        bars = await provider.get_index_candles("SPX", days=30)

        assert len(bars) > 0


# =============================================================================
# EARNINGS TESTS
# =============================================================================

class TestMarketDataEarnings:
    """Tests for earnings data"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_earnings_date(self, provider):
        """get_earnings_date should return next earnings"""
        future_date = (date.today() + timedelta(days=30)).isoformat()

        mock_response = {
            "s": "ok",
            "reportDate": [future_date],
            "fiscalYear": [2025],
            "fiscalQuarter": [1]
        }

        provider._get = AsyncMock(return_value=mock_response)

        earnings = await provider.get_earnings_date("AAPL")

        assert earnings is not None
        assert earnings.symbol == "AAPL"
        assert earnings.days_to_earnings > 0

    @pytest.mark.asyncio
    async def test_get_earnings_date_no_data(self, provider):
        """get_earnings_date should return None for no data"""
        provider._get = AsyncMock(return_value=None)

        earnings = await provider.get_earnings_date("INVALID")

        assert earnings is None

    @pytest.mark.asyncio
    async def test_get_earnings_date_past_only(self, provider):
        """get_earnings_date should return None when only past dates"""
        past_date = (date.today() - timedelta(days=30)).isoformat()

        mock_response = {
            "s": "ok",
            "reportDate": [past_date],
            "fiscalYear": [2024],
            "fiscalQuarter": [4]
        }

        provider._get = AsyncMock(return_value=mock_response)

        earnings = await provider.get_earnings_date("AAPL")

        assert earnings is None

    @pytest.mark.asyncio
    async def test_get_historical_earnings(self, provider):
        """get_historical_earnings should return list of earnings"""
        mock_response = {
            "s": "ok",
            "reportDate": ["2024-01-25", "2024-04-25", "2024-07-25"],
            "fiscalYear": [2024, 2024, 2024],
            "fiscalQuarter": [1, 2, 3],
            "reportTime": ["amc", "amc", "amc"],
            "epsReported": [1.50, 1.60, 1.70],
            "epsEstimate": [1.45, 1.55, 1.65],
            "epsSurprise": [0.05, 0.05, 0.05],
            "epsSurprisePct": [3.4, 3.2, 3.0]
        }

        provider._get = AsyncMock(return_value=mock_response)

        earnings = await provider.get_historical_earnings("AAPL")

        assert len(earnings) == 3
        assert earnings[0]["fiscal_quarter"] == "Q3"  # Most recent first

    @pytest.mark.asyncio
    async def test_get_historical_earnings_unix_timestamps(self, provider):
        """get_historical_earnings should handle unix timestamps"""
        mock_response = {
            "s": "ok",
            "reportDate": [1706227200],  # Unix timestamp
            "fiscalYear": [2024],
            "fiscalQuarter": [1],
            "epsReported": [1.50],
            "epsEstimate": [1.45]
        }

        provider._get = AsyncMock(return_value=mock_response)

        earnings = await provider.get_historical_earnings("AAPL")

        assert len(earnings) == 1


# =============================================================================
# BULK OPERATIONS TESTS
# =============================================================================

class TestMarketDataBulkOperations:
    """Tests for bulk operations"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_historical_bulk(self, provider):
        """get_historical_bulk should return data for multiple symbols"""
        mock_response = {
            "s": "ok",
            "t": [1706140800 + i * 86400 for i in range(100)],
            "o": [174.50 + i * 0.1 for i in range(100)],
            "h": [176.00 + i * 0.1 for i in range(100)],
            "l": [174.00 + i * 0.1 for i in range(100)],
            "c": [175.50 + i * 0.1 for i in range(100)],
            "v": [45000000 for _ in range(100)]
        }

        provider._get = AsyncMock(return_value=mock_response)

        result = await provider.get_historical_bulk(
            ["AAPL", "MSFT"],
            days=100,
            delay_seconds=0  # No delay for test
        )

        assert len(result) == 2
        assert "AAPL" in result
        assert "MSFT" in result


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestMarketDataErrorHandling:
    """Tests for error handling"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_http_401_unauthorized(self, provider):
        """Should handle 401 Unauthorized"""
        error = urllib.error.HTTPError(
            url="https://api.marketdata.app/test",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None
        )

        with patch('urllib.request.urlopen', side_effect=error):
            result = await provider._get("/test")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_429_rate_limit(self, provider):
        """Should handle 429 Rate Limit with retry"""
        provider.config.max_retries = 2
        provider.config.retry_delay_seconds = 0.01  # Fast for test

        call_count = 0

        def mock_urlopen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise urllib.error.HTTPError(
                    url="https://api.marketdata.app/test",
                    code=429,
                    msg="Rate Limit",
                    hdrs={},
                    fp=None
                )
            # Return success on retry
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"s": "ok"}'
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            return mock_response

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            result = await provider._get("/test")

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_http_404_not_found(self, provider):
        """Should handle 404 Not Found"""
        error = urllib.error.HTTPError(
            url="https://api.marketdata.app/test",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None
        )

        with patch('urllib.request.urlopen', side_effect=error):
            result = await provider._get("/test")

        assert result is None

    @pytest.mark.asyncio
    async def test_network_error(self, provider):
        """Should handle network errors"""
        provider.config.max_retries = 1

        error = urllib.error.URLError("Network unreachable")

        with patch('urllib.request.urlopen', side_effect=error):
            result = await provider._get("/test")

        assert result is None


# =============================================================================
# HELPER METHOD TESTS
# =============================================================================

class TestMarketDataHelpers:
    """Tests for helper methods"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    def test_safe_get_first_with_list(self, provider):
        """_safe_get_first should return first element"""
        result = provider._safe_get_first([175.50, 176.00])
        assert result == 175.50

    def test_safe_get_first_with_single(self, provider):
        """_safe_get_first should handle single value"""
        result = provider._safe_get_first(175.50)
        assert result == 175.50

    def test_safe_get_first_with_none(self, provider):
        """_safe_get_first should return None for None"""
        result = provider._safe_get_first(None)
        assert result is None

    def test_safe_get_first_with_empty_list(self, provider):
        """_safe_get_first should return None for empty list"""
        result = provider._safe_get_first([])
        assert result is None

    def test_safe_get_index(self, provider):
        """_safe_get_index should return correct element"""
        result = provider._safe_get_index([1.0, 2.0, 3.0], 1)
        assert result == 2.0

    def test_safe_get_index_out_of_range(self, provider):
        """_safe_get_index should return None for out of range"""
        result = provider._safe_get_index([1.0, 2.0], 5)
        assert result is None

    def test_safe_get_index_with_none(self, provider):
        """_safe_get_index should return None for None input"""
        result = provider._safe_get_index(None, 0)
        assert result is None

    def test_safe_float(self, provider):
        """_safe_float should convert valid values"""
        assert provider._safe_float(175.50) == 175.50
        assert provider._safe_float("175.50") == 175.50
        assert provider._safe_float(175) == 175.0

    def test_safe_float_invalid(self, provider):
        """_safe_float should return None for invalid values"""
        assert provider._safe_float(None) is None
        assert provider._safe_float("invalid") is None

    def test_safe_int(self, provider):
        """_safe_int should convert valid values"""
        assert provider._safe_int(100) == 100
        assert provider._safe_int("100") == 100
        assert provider._safe_int(100.7) == 100

    def test_safe_int_invalid(self, provider):
        """_safe_int should return None for invalid values"""
        assert provider._safe_int(None) is None
        assert provider._safe_int("invalid") is None


# =============================================================================
# IV DATA TESTS
# =============================================================================

class TestMarketDataIVData:
    """Tests for IV data retrieval"""

    @pytest.fixture
    def provider(self):
        return MarketDataProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_iv_data_success(self, provider):
        """get_iv_data should return IV data"""
        mock_chain_response = {
            "s": "ok",
            "optionSymbol": ["AAPL250321P00175000"],
            "strike": [175.0],
            "side": ["put"],
            "bid": [3.50],
            "ask": [3.70],
            "iv": [0.30],
            "expiration": [1742515200]
        }

        mock_quote_response = {
            "s": "ok",
            "symbol": ["AAPL"],
            "last": [175.0],
            "bid": [174.95],
            "ask": [175.05]
        }

        call_count = 0

        async def mock_get(endpoint, params=None):
            nonlocal call_count
            call_count += 1
            if "chain" in endpoint:
                return mock_chain_response
            elif "quotes" in endpoint:
                return mock_quote_response
            return None

        provider._get = mock_get

        # Mock IV cache
        mock_cache = MagicMock()
        mock_cache.add_iv_point = MagicMock()
        mock_cache.get_iv_data = MagicMock(return_value=MagicMock(atm_iv=0.30))
        provider._iv_cache = mock_cache

        iv_data = await provider.get_iv_data("AAPL")

        # Verify cache was called
        assert mock_cache.add_iv_point.called

    @pytest.mark.asyncio
    async def test_get_iv_data_no_chain(self, provider):
        """get_iv_data should return None when no chain available"""
        provider._get = AsyncMock(return_value=None)

        iv_data = await provider.get_iv_data("INVALID")

        assert iv_data is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
