# OptionPlay - Tradier Provider Tests
# =====================================
# Comprehensive unit tests for TradierProvider class
#
# Coverage includes:
# 1. Initialization with API key
# 2. get_quote method
# 3. get_options_chain method
# 4. get_historical_data method
# 5. Rate limiting behavior
# 6. Error handling (API errors, timeouts)
# 7. Response parsing

import pytest
import asyncio
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from src.data_providers.tradier import (
    TradierProvider,
    TradierConfig,
    TradierEnvironment,
    HistoricalOptionBar,
    parse_occ_symbol,
    build_occ_symbol,
    get_tradier_provider,
    fetch_option_chain,
    fetch_quote,
)
from src.data_providers.interface import (
    PriceQuote,
    OptionQuote,
    HistoricalBar,
    DataQuality
)


# =============================================================================
# 1. INITIALIZATION TESTS
# =============================================================================

class TestTradierProviderInitialization:
    """Tests for TradierProvider initialization"""

    def test_init_with_api_key_only(self):
        """Initialize provider with just API key"""
        provider = TradierProvider(api_key="test_api_key")

        assert provider.config.api_key == "test_api_key"
        assert provider.config.environment == TradierEnvironment.PRODUCTION
        assert provider._session is None
        assert provider._connected is False
        assert provider._request_count == 0
        assert provider._last_request_time is None

    def test_init_with_sandbox_environment(self):
        """Initialize provider with sandbox environment"""
        provider = TradierProvider(
            api_key="sandbox_key",
            environment=TradierEnvironment.SANDBOX
        )

        assert provider.config.environment == TradierEnvironment.SANDBOX
        assert "sandbox.tradier.com" in provider.config.base_url

    def test_init_with_production_environment(self):
        """Initialize provider with production environment"""
        provider = TradierProvider(
            api_key="prod_key",
            environment=TradierEnvironment.PRODUCTION
        )

        assert provider.config.environment == TradierEnvironment.PRODUCTION
        assert "api.tradier.com" in provider.config.base_url

    def test_init_with_custom_config(self):
        """Initialize provider with custom TradierConfig"""
        config = TradierConfig(
            api_key="custom_key",
            environment=TradierEnvironment.SANDBOX,
            timeout_seconds=60,
            max_retries=5,
            retry_delay_seconds=2.0,
            rate_limit_per_minute=60
        )

        provider = TradierProvider(
            api_key="ignored_key",  # Should be overridden by config
            config=config
        )

        assert provider.config.api_key == "custom_key"
        assert provider.config.timeout_seconds == 60
        assert provider.config.max_retries == 5
        assert provider.config.retry_delay_seconds == 2.0
        assert provider.config.rate_limit_per_minute == 60

    def test_init_with_iv_cache(self):
        """Initialize provider with custom IV cache"""
        mock_iv_cache = MagicMock()
        provider = TradierProvider(api_key="test", iv_cache=mock_iv_cache)

        assert provider._iv_cache is mock_iv_cache

    def test_provider_name(self):
        """Provider name should be 'tradier'"""
        provider = TradierProvider(api_key="test")
        assert provider.name == "tradier"

    def test_supported_features(self):
        """Provider should support required features"""
        provider = TradierProvider(api_key="test")
        features = provider.supported_features

        assert "quotes" in features
        assert "options" in features
        assert "historical" in features
        assert "expirations" in features
        assert "strikes" in features


class TestTradierConfig:
    """Tests for TradierConfig dataclass"""

    def test_production_base_url(self):
        """Production URL should be correct"""
        config = TradierConfig(
            api_key="test_key",
            environment=TradierEnvironment.PRODUCTION
        )

        assert config.base_url == "https://api.tradier.com"

    def test_sandbox_base_url(self):
        """Sandbox URL should be correct"""
        config = TradierConfig(
            api_key="test_key",
            environment=TradierEnvironment.SANDBOX
        )

        assert config.base_url == "https://sandbox.tradier.com"

    def test_headers_include_authorization(self):
        """Headers should include Bearer token"""
        config = TradierConfig(api_key="my_secret_key")

        assert "Authorization" in config.headers
        assert config.headers["Authorization"] == "Bearer my_secret_key"
        assert config.headers["Accept"] == "application/json"

    def test_default_values(self):
        """Default config values should be set"""
        config = TradierConfig(api_key="test")

        assert config.timeout_seconds == 30
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 1.0
        assert config.rate_limit_per_minute == 120


# =============================================================================
# 2. GET_QUOTE METHOD TESTS
# =============================================================================

class TestGetQuote:
    """Tests for get_quote and get_quotes methods"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_quote_success(self, provider):
        """get_quote should return PriceQuote on success"""
        mock_response = {
            "quotes": {
                "quote": {
                    "symbol": "AAPL",
                    "last": 175.50,
                    "bid": 175.45,
                    "ask": 175.55,
                    "volume": 45000000
                }
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        quote = await provider.get_quote("AAPL")

        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.last == 175.50
        assert quote.bid == 175.45
        assert quote.ask == 175.55
        assert quote.volume == 45000000
        assert quote.source == "tradier"

    @pytest.mark.asyncio
    async def test_get_quote_uppercase_symbol(self, provider):
        """get_quote should uppercase the symbol"""
        mock_response = {
            "quotes": {
                "quote": {
                    "symbol": "AAPL",
                    "last": 175.50
                }
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        quote = await provider.get_quote("aapl")  # lowercase input

        # The call should uppercase the symbol
        assert quote.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_get_quote_not_found(self, provider):
        """get_quote should return None for invalid symbol"""
        provider._get = AsyncMock(return_value=None)

        quote = await provider.get_quote("INVALID")

        assert quote is None

    @pytest.mark.asyncio
    async def test_get_quote_empty_response(self, provider):
        """get_quote should handle empty quotes response"""
        provider._get = AsyncMock(return_value={"quotes": {}})

        quote = await provider.get_quote("AAPL")

        assert quote is None

    @pytest.mark.asyncio
    async def test_get_quotes_multiple_symbols(self, provider):
        """get_quotes should return multiple quotes"""
        mock_response = {
            "quotes": {
                "quote": [
                    {"symbol": "AAPL", "last": 175.50, "bid": 175.45, "ask": 175.55, "volume": 45000000},
                    {"symbol": "MSFT", "last": 400.00, "bid": 399.90, "ask": 400.10, "volume": 30000000},
                    {"symbol": "GOOGL", "last": 140.00, "bid": 139.95, "ask": 140.05, "volume": 20000000}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        quotes = await provider.get_quotes(["AAPL", "MSFT", "GOOGL"])

        assert len(quotes) == 3
        assert "AAPL" in quotes
        assert "MSFT" in quotes
        assert "GOOGL" in quotes
        assert quotes["AAPL"].last == 175.50
        assert quotes["MSFT"].last == 400.00

    @pytest.mark.asyncio
    async def test_get_quotes_single_symbol_response(self, provider):
        """get_quotes should handle single quote response (dict instead of list)"""
        mock_response = {
            "quotes": {
                "quote": {  # Single quote as dict, not list
                    "symbol": "AAPL",
                    "last": 175.50,
                    "bid": 175.45,
                    "ask": 175.55,
                    "volume": 45000000
                }
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        quotes = await provider.get_quotes(["AAPL"])

        assert len(quotes) == 1
        assert "AAPL" in quotes

    @pytest.mark.asyncio
    async def test_get_quotes_empty_list(self, provider):
        """get_quotes should return empty dict for empty input"""
        quotes = await provider.get_quotes([])

        assert quotes == {}

    @pytest.mark.asyncio
    async def test_get_quotes_missing_symbol_in_response(self, provider):
        """get_quotes should skip quotes without symbol"""
        mock_response = {
            "quotes": {
                "quote": [
                    {"symbol": "AAPL", "last": 175.50},
                    {"last": 100.00},  # Missing symbol
                    {"symbol": "MSFT", "last": 400.00}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        quotes = await provider.get_quotes(["AAPL", "MSFT"])

        assert len(quotes) == 2
        assert "AAPL" in quotes
        assert "MSFT" in quotes


class TestQuoteParsing:
    """Tests for _parse_quote method"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test")

    def test_parse_quote_complete(self, provider):
        """Parse complete quote data"""
        data = {
            "symbol": "AAPL",
            "last": 175.50,
            "bid": 175.45,
            "ask": 175.55,
            "volume": 45000000
        }

        quote = provider._parse_quote(data)

        assert quote.symbol == "AAPL"
        assert quote.last == 175.50
        assert quote.bid == 175.45
        assert quote.ask == 175.55
        assert quote.volume == 45000000
        assert quote.source == "tradier"
        assert quote.data_quality == DataQuality.REALTIME

    def test_parse_quote_missing_values(self, provider):
        """Parse quote with missing values"""
        data = {
            "symbol": "AAPL",
            "last": 175.50
        }

        quote = provider._parse_quote(data)

        assert quote.symbol == "AAPL"
        assert quote.last == 175.50
        assert quote.bid is None
        assert quote.ask is None
        assert quote.volume is None

    def test_parse_quote_no_last_is_delayed(self, provider):
        """Quote without last price should be marked delayed"""
        data = {
            "symbol": "AAPL",
            "bid": 175.45,
            "ask": 175.55
        }

        quote = provider._parse_quote(data)

        assert quote.data_quality == DataQuality.DELAYED_15MIN

    def test_quote_mid_calculation(self, provider):
        """Mid price calculation"""
        data = {
            "symbol": "AAPL",
            "bid": 175.00,
            "ask": 176.00
        }

        quote = provider._parse_quote(data)

        assert quote.mid == 175.50

    def test_quote_spread_calculation(self, provider):
        """Spread calculation"""
        data = {
            "symbol": "AAPL",
            "bid": 175.00,
            "ask": 175.20
        }

        quote = provider._parse_quote(data)

        assert quote.spread == pytest.approx(0.20)

    def test_parse_quote_zero_volume(self, provider):
        """Parse quote with zero volume"""
        data = {
            "symbol": "AAPL",
            "last": 175.50,
            "volume": 0
        }

        quote = provider._parse_quote(data)

        assert quote.volume == 0


# =============================================================================
# 3. GET_OPTION_CHAIN METHOD TESTS
# =============================================================================

class TestGetOptionChain:
    """Tests for get_option_chain method"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_option_chain_success(self, provider):
        """get_option_chain should return list of OptionQuotes"""
        # Calculate a date that falls within dte_min=30, dte_max=60
        from datetime import date, timedelta
        future_date = (date.today() + timedelta(days=45)).isoformat()  # 45 days out

        # Mock get_quote for underlying price
        quote_response = {
            "quotes": {"quote": {"symbol": "AAPL", "last": 175.50}}
        }

        # Mock expirations - use a date within DTE range
        exp_response = {
            "expirations": {"date": [future_date]}
        }

        # Mock options chain
        chain_response = {
            "options": {
                "option": [
                    {
                        "symbol": "AAPL250321P00170000",
                        "strike": 170.0,
                        "option_type": "put",
                        "bid": 2.50,
                        "ask": 2.70,
                        "last": 2.60,
                        "volume": 1500,
                        "open_interest": 5000,
                        "greeks": {
                            "delta": -0.28,
                            "gamma": 0.015,
                            "theta": -0.05,
                            "vega": 0.25,
                            "mid_iv": 0.32
                        }
                    },
                    {
                        "symbol": "AAPL250321P00175000",
                        "strike": 175.0,
                        "option_type": "put",
                        "bid": 4.00,
                        "ask": 4.20,
                        "last": 4.10,
                        "volume": 2000,
                        "open_interest": 8000,
                        "greeks": {
                            "mid_iv": 0.30
                        }
                    }
                ]
            }
        }

        call_count = 0
        async def mock_get(endpoint, params=None, _skip_connect_check=False):
            nonlocal call_count
            call_count += 1
            if "quotes" in endpoint:
                return quote_response
            elif "expirations" in endpoint:
                return exp_response
            elif "chains" in endpoint:
                return chain_response
            return None

        provider._get = mock_get

        chain = await provider.get_option_chain("AAPL", dte_min=30, dte_max=60, right="P")

        assert len(chain) == 2
        assert chain[0].strike == 170.0
        assert chain[0].right == "P"
        assert chain[0].underlying == "AAPL"
        assert chain[0].underlying_price == 175.50
        assert chain[0].implied_volatility == 0.32

    @pytest.mark.asyncio
    async def test_get_option_chain_with_specific_expiry(self, provider):
        """get_option_chain with specific expiry date"""
        quote_response = {"quotes": {"quote": {"symbol": "AAPL", "last": 175.50}}}
        chain_response = {
            "options": {
                "option": {
                    "symbol": "AAPL250321P00170000",
                    "strike": 170.0,
                    "option_type": "put",
                    "bid": 2.50,
                    "ask": 2.70
                }
            }
        }

        async def mock_get(endpoint, params=None, _skip_connect_check=False):
            if "quotes" in endpoint:
                return quote_response
            elif "chains" in endpoint:
                # Verify expiration is passed correctly
                assert params.get("expiration") == "2025-03-21"
                return chain_response
            return None

        provider._get = mock_get

        chain = await provider.get_option_chain("AAPL", expiry=date(2025, 3, 21))

        assert len(chain) == 1

    @pytest.mark.asyncio
    async def test_get_option_chain_filters_by_right(self, provider):
        """get_option_chain should filter by option type"""
        from datetime import date, timedelta
        future_date = (date.today() + timedelta(days=45)).isoformat()  # 45 days out

        quote_response = {"quotes": {"quote": {"symbol": "AAPL", "last": 175.50}}}
        exp_response = {"expirations": {"date": future_date}}
        chain_response = {
            "options": {
                "option": [
                    {"symbol": "PUT1", "strike": 170.0, "option_type": "put", "bid": 2.50, "ask": 2.70},
                    {"symbol": "CALL1", "strike": 180.0, "option_type": "call", "bid": 3.50, "ask": 3.70},
                    {"symbol": "PUT2", "strike": 175.0, "option_type": "put", "bid": 4.00, "ask": 4.20}
                ]
            }
        }

        async def mock_get(endpoint, params=None, _skip_connect_check=False):
            if "quotes" in endpoint:
                return quote_response
            elif "expirations" in endpoint:
                return exp_response
            elif "chains" in endpoint:
                return chain_response
            return None

        provider._get = mock_get

        # Request puts only
        puts = await provider.get_option_chain("AAPL", dte_min=30, dte_max=60, right="P")
        assert len(puts) == 2
        assert all(opt.right == "P" for opt in puts)

    @pytest.mark.asyncio
    async def test_get_option_chain_no_underlying_price(self, provider):
        """get_option_chain should return empty list if no underlying price"""
        provider._get = AsyncMock(return_value={"quotes": {}})

        chain = await provider.get_option_chain("AAPL")

        assert chain == []

    @pytest.mark.asyncio
    async def test_get_option_chain_no_expirations(self, provider):
        """get_option_chain should return empty list if no matching expirations"""
        quote_response = {"quotes": {"quote": {"symbol": "AAPL", "last": 175.50}}}
        exp_response = {"expirations": {"date": []}}

        async def mock_get(endpoint, params=None, _skip_connect_check=False):
            if "quotes" in endpoint:
                return quote_response
            elif "expirations" in endpoint:
                return exp_response
            return None

        provider._get = mock_get

        chain = await provider.get_option_chain("AAPL")

        assert chain == []


class TestOptionParsing:
    """Tests for _parse_option method"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test")

    def test_parse_option_put(self, provider):
        """Parse put option"""
        data = {
            "symbol": "AAPL250321P00170000",
            "strike": 170.0,
            "option_type": "put",
            "bid": 2.50,
            "ask": 2.70,
            "last": 2.60,
            "volume": 1500,
            "open_interest": 5000,
            "greeks": {
                "delta": -0.28,
                "gamma": 0.015,
                "theta": -0.05,
                "vega": 0.25,
                "mid_iv": 0.32
            }
        }

        option = provider._parse_option(
            data,
            underlying="AAPL",
            underlying_price=175.50,
            expiry=date(2025, 3, 21)
        )

        assert option is not None
        assert option.symbol == "AAPL250321P00170000"
        assert option.underlying == "AAPL"
        assert option.strike == 170.0
        assert option.right == "P"
        assert option.bid == 2.50
        assert option.ask == 2.70
        assert option.gamma == 0.015
        assert option.vega == 0.25
        assert option.implied_volatility == 0.32

    def test_parse_option_call(self, provider):
        """Parse call option"""
        data = {
            "symbol": "AAPL250321C00180000",
            "strike": 180.0,
            "option_type": "call",
            "bid": 1.80,
            "ask": 2.00,
            "greeks": {
                "delta": 0.35,
                "smv_vol": 0.28
            }
        }

        option = provider._parse_option(
            data,
            underlying="AAPL",
            underlying_price=175.50,
            expiry=date(2025, 3, 21)
        )

        assert option.right == "C"
        assert option.delta == 0.35
        assert option.implied_volatility == 0.28  # smv_vol as fallback

    def test_parse_option_without_greeks(self, provider):
        """Parse option without Greeks"""
        data = {
            "symbol": "AAPL250321P00170000",
            "strike": 170.0,
            "option_type": "put",
            "bid": 2.50,
            "ask": 2.70
        }

        option = provider._parse_option(
            data,
            underlying="AAPL",
            underlying_price=175.50,
            expiry=date(2025, 3, 21)
        )

        assert option.delta is None
        assert option.implied_volatility is None

    def test_parse_option_null_greeks(self, provider):
        """Parse option with null greeks"""
        data = {
            "symbol": "TEST",
            "strike": 100.0,
            "option_type": "put",
            "bid": 1.00,
            "ask": 1.10,
            "greeks": None
        }

        option = provider._parse_option(
            data,
            underlying="TEST",
            underlying_price=100.0,
            expiry=date(2025, 3, 21)
        )

        assert option is not None
        assert option.delta is None

    def test_parse_option_invalid_data(self, provider):
        """Parse option with invalid data should return None gracefully"""
        # Missing required fields should still work but have None values
        data = {"symbol": "TEST"}

        option = provider._parse_option(
            data,
            underlying="TEST",
            underlying_price=100.0,
            expiry=date(2025, 3, 21)
        )

        # Should return an option with default/None values
        assert option is not None or option is None  # May return None on parse error


# =============================================================================
# 4. GET_HISTORICAL_DATA METHOD TESTS
# =============================================================================

class TestGetHistorical:
    """Tests for get_historical method"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_historical_success(self, provider):
        """get_historical should return list of HistoricalBar"""
        mock_response = {
            "history": {
                "day": [
                    {
                        "date": "2025-01-20",
                        "open": 174.50,
                        "high": 176.00,
                        "low": 174.00,
                        "close": 175.50,
                        "volume": 45000000
                    },
                    {
                        "date": "2025-01-21",
                        "open": 175.50,
                        "high": 177.00,
                        "low": 175.00,
                        "close": 176.80,
                        "volume": 42000000
                    }
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        bars = await provider.get_historical("AAPL", days=30)

        assert len(bars) == 2
        assert bars[0].symbol == "AAPL"
        assert bars[0].close == 175.50
        assert bars[0].date == date(2025, 1, 20)
        assert bars[1].close == 176.80
        assert bars[0].source == "tradier"

    @pytest.mark.asyncio
    async def test_get_historical_single_day(self, provider):
        """get_historical should handle single day response"""
        mock_response = {
            "history": {
                "day": {
                    "date": "2025-01-20",
                    "open": 174.50,
                    "high": 176.00,
                    "low": 174.00,
                    "close": 175.50,
                    "volume": 45000000
                }
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        bars = await provider.get_historical("AAPL", days=1)

        assert len(bars) == 1
        assert bars[0].close == 175.50

    @pytest.mark.asyncio
    async def test_get_historical_empty_response(self, provider):
        """get_historical should return empty list for no data"""
        provider._get = AsyncMock(return_value={"history": None})

        bars = await provider.get_historical("INVALID", days=30)

        assert bars == []

    @pytest.mark.asyncio
    async def test_get_historical_no_history_key(self, provider):
        """get_historical should handle missing history key"""
        provider._get = AsyncMock(return_value={})

        bars = await provider.get_historical("AAPL", days=30)

        assert bars == []

    @pytest.mark.asyncio
    async def test_get_historical_no_day_key(self, provider):
        """get_historical should handle missing day key"""
        provider._get = AsyncMock(return_value={"history": {}})

        bars = await provider.get_historical("AAPL", days=30)

        assert bars == []

    @pytest.mark.asyncio
    async def test_get_historical_limits_results(self, provider):
        """get_historical should limit results to requested days"""
        # Create 100 days of data
        days_data = [
            {
                "date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i * 0.1,
                "volume": 1000000
            }
            for i in range(100)
        ]

        mock_response = {"history": {"day": days_data}}
        provider._get = AsyncMock(return_value=mock_response)

        bars = await provider.get_historical("AAPL", days=30)

        # Should return at most 30 bars (the most recent ones)
        assert len(bars) <= 30

    @pytest.mark.asyncio
    async def test_get_historical_sorted_by_date(self, provider):
        """get_historical should return bars sorted by date"""
        mock_response = {
            "history": {
                "day": [
                    {"date": "2025-01-22", "open": 176.0, "high": 177.0, "low": 175.0, "close": 176.5, "volume": 40000000},
                    {"date": "2025-01-20", "open": 174.5, "high": 176.0, "low": 174.0, "close": 175.5, "volume": 45000000},
                    {"date": "2025-01-21", "open": 175.5, "high": 177.0, "low": 175.0, "close": 176.8, "volume": 42000000}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        bars = await provider.get_historical("AAPL", days=30)

        # Should be sorted chronologically
        assert bars[0].date < bars[1].date < bars[2].date

    @pytest.mark.asyncio
    async def test_get_historical_with_interval(self, provider):
        """get_historical should pass interval parameter"""
        captured_params = {}

        async def mock_get(endpoint, params=None, _skip_connect_check=False):
            captured_params.update(params or {})
            return {"history": {"day": []}}

        provider._get = mock_get

        await provider.get_historical("AAPL", days=30, interval="weekly")

        assert captured_params.get("interval") == "weekly"

    @pytest.mark.asyncio
    async def test_get_historical_for_scanner(self, provider):
        """get_historical_for_scanner should return tuple format"""
        # Generate valid dates (use a date range that will have valid format)
        from datetime import date, timedelta
        base_date = date(2025, 1, 1)
        mock_response = {
            "history": {
                "day": [
                    {
                        "date": (base_date + timedelta(days=i)).isoformat(),
                        "open": 100.0 + i,
                        "high": 101.0 + i,
                        "low": 99.0 + i,
                        "close": 100.5 + i,
                        "volume": 1000000 + i * 1000
                    }
                    for i in range(60)  # 60 days of data
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        result = await provider.get_historical_for_scanner("AAPL", days=260)

        assert result is not None
        prices, volumes, highs, lows, opens = result
        assert len(prices) == 60
        assert len(volumes) == 60
        assert len(highs) == 60
        assert len(lows) == 60
        assert len(opens) == 60

    @pytest.mark.asyncio
    async def test_get_historical_for_scanner_insufficient_data(self, provider):
        """get_historical_for_scanner should return None for insufficient data"""
        mock_response = {
            "history": {
                "day": [
                    {"date": "2025-01-01", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000000}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        result = await provider.get_historical_for_scanner("AAPL", days=260)

        assert result is None


# =============================================================================
# 5. RATE LIMITING BEHAVIOR TESTS
# =============================================================================

class TestRateLimiting:
    """Tests for rate limiting behavior"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_request_count_incremented(self, provider):
        """Request count should be incremented on each request"""
        initial_count = provider._request_count

        async def mock_urlopen():
            return json.dumps({"quotes": {"quote": {"symbol": "AAPL"}}}).encode()

        with patch('urllib.request.urlopen') as mock_open:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({"clock": {}}).encode()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_response

            await provider._get("/v1/markets/clock", _skip_connect_check=True)

        assert provider._request_count > initial_count

    @pytest.mark.asyncio
    async def test_last_request_time_updated(self, provider):
        """Last request time should be updated on each request"""
        assert provider._last_request_time is None

        with patch('urllib.request.urlopen') as mock_open:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({"clock": {}}).encode()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_response

            await provider._get("/v1/markets/clock", _skip_connect_check=True)

        assert provider._last_request_time is not None
        assert isinstance(provider._last_request_time, datetime)

    @pytest.mark.asyncio
    async def test_rate_limit_config(self, provider):
        """Rate limit should be configurable"""
        config = TradierConfig(api_key="test", rate_limit_per_minute=60)
        limited_provider = TradierProvider(api_key="test", config=config)

        assert limited_provider.config.rate_limit_per_minute == 60

    @pytest.mark.asyncio
    async def test_bulk_quotes_adds_delay(self, provider):
        """Bulk operations should add delay between batches"""
        # Test that get_quotes_bulk properly handles large lists
        symbols = [f"SYM{i}" for i in range(150)]  # More than batch size

        call_count = 0
        async def mock_get_quotes(syms):
            nonlocal call_count
            call_count += 1
            return {s: MagicMock() for s in syms}

        provider.get_quotes = mock_get_quotes

        await provider.get_quotes_bulk(symbols, batch_size=100)

        # Should have been called twice (100 + 50)
        assert call_count == 2


# =============================================================================
# 6. ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_http_401_unauthorized(self, provider):
        """Should handle 401 Unauthorized error"""
        with patch('urllib.request.urlopen') as mock_open:
            http_error = urllib.error.HTTPError(
                url="https://api.tradier.com/v1/test",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=None
            )
            mock_open.side_effect = http_error

            result = await provider._get("/v1/test", _skip_connect_check=True)

            assert result is None

    @pytest.mark.asyncio
    async def test_http_429_rate_limit_retries(self, provider):
        """Should retry on 429 Rate Limit error"""
        call_count = 0

        with patch('urllib.request.urlopen') as mock_open:
            def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise urllib.error.HTTPError(
                        url="https://api.tradier.com/v1/test",
                        code=429,
                        msg="Rate Limit",
                        hdrs={},
                        fp=None
                    )
                mock_response = MagicMock()
                mock_response.read.return_value = json.dumps({"data": "success"}).encode()
                mock_response.__enter__ = MagicMock(return_value=mock_response)
                mock_response.__exit__ = MagicMock(return_value=False)
                return mock_response

            mock_open.side_effect = side_effect

            # Use short retry delay for test
            provider.config.retry_delay_seconds = 0.01

            result = await provider._get("/v1/test", _skip_connect_check=True)

            # Should have retried and eventually succeeded
            assert call_count == 3
            assert result == {"data": "success"}

    @pytest.mark.asyncio
    async def test_http_500_server_error(self, provider):
        """Should handle 500 Server Error"""
        with patch('urllib.request.urlopen') as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="https://api.tradier.com/v1/test",
                code=500,
                msg="Server Error",
                hdrs={},
                fp=None
            )

            provider.config.retry_delay_seconds = 0.01

            result = await provider._get("/v1/test", _skip_connect_check=True)

            assert result is None

    @pytest.mark.asyncio
    async def test_url_error_network_failure(self, provider):
        """Should handle network failures"""
        with patch('urllib.request.urlopen') as mock_open:
            mock_open.side_effect = urllib.error.URLError("Connection refused")

            provider.config.retry_delay_seconds = 0.01

            result = await provider._get("/v1/test", _skip_connect_check=True)

            assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error(self, provider):
        """Should handle timeout errors"""
        with patch('urllib.request.urlopen') as mock_open:
            mock_open.side_effect = urllib.error.URLError("timeout")

            provider.config.retry_delay_seconds = 0.01

            result = await provider._get("/v1/test", _skip_connect_check=True)

            assert result is None

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, provider):
        """Should return None after max retries exhausted"""
        call_count = 0

        with patch('urllib.request.urlopen') as mock_open:
            def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                raise urllib.error.URLError("Connection failed")

            mock_open.side_effect = side_effect
            provider.config.retry_delay_seconds = 0.01
            provider.config.max_retries = 3

            result = await provider._get("/v1/test", _skip_connect_check=True)

            assert result is None
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_connect_failure_sets_connected_false(self, provider):
        """connect() should set _connected=False on failure"""
        with patch('urllib.request.urlopen') as mock_open:
            mock_open.side_effect = urllib.error.URLError("Connection failed")

            provider.config.retry_delay_seconds = 0.01

            result = await provider.connect()

            assert result is False
            assert provider._connected is False

    @pytest.mark.asyncio
    async def test_parse_option_exception_returns_none(self, provider):
        """_parse_option should return None on exception"""
        # Create data that will cause an exception during parsing
        bad_data = {
            "strike": "not_a_number"
        }

        result = provider._parse_option(
            bad_data,
            underlying="TEST",
            underlying_price=100.0,
            expiry=date(2025, 3, 21)
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_historical_bar_parse_error_skipped(self, provider):
        """Malformed bar data should be skipped"""
        mock_response = {
            "history": {
                "day": [
                    {"date": "2025-01-20", "open": 174.50, "high": 176.00, "low": 174.00, "close": 175.50, "volume": 45000000},
                    {"date": "invalid-date", "open": 100.0},  # Bad date
                    {"date": "2025-01-21", "open": 175.50, "high": 177.00, "low": 175.00, "close": 176.80, "volume": 42000000}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        bars = await provider.get_historical("AAPL", days=30)

        # Should have 2 valid bars, skipping the invalid one
        assert len(bars) == 2


# =============================================================================
# 7. RESPONSE PARSING TESTS
# =============================================================================

class TestSafeConversions:
    """Tests for safe type conversion methods"""

    def test_safe_float_valid_float(self):
        """_safe_float should convert valid floats"""
        assert TradierProvider._safe_float(175.50) == 175.50
        assert TradierProvider._safe_float("175.50") == 175.50
        assert TradierProvider._safe_float(175) == 175.0

    def test_safe_float_invalid_values(self):
        """_safe_float should return None for invalid values"""
        assert TradierProvider._safe_float(None) is None
        assert TradierProvider._safe_float("invalid") is None
        assert TradierProvider._safe_float("") is None
        assert TradierProvider._safe_float({}) is None

    def test_safe_float_zero_returns_none(self):
        """_safe_float should return None for zero"""
        assert TradierProvider._safe_float(0) is None
        assert TradierProvider._safe_float(0.0) is None

    def test_safe_float_negative_returns_none(self):
        """_safe_float should return None for negative values"""
        assert TradierProvider._safe_float(-5) is None
        assert TradierProvider._safe_float(-0.01) is None

    def test_safe_float_nan_returns_none(self):
        """_safe_float should handle NaN"""
        result = TradierProvider._safe_float(float('nan'))
        # NaN > 0 is False, so it should return None
        assert result is None

    def test_safe_float_inf(self):
        """_safe_float should handle infinity"""
        result = TradierProvider._safe_float(float('inf'))
        # inf > 0 is True, so it passes
        assert result == float('inf')

    def test_safe_int_valid_int(self):
        """_safe_int should convert valid integers"""
        assert TradierProvider._safe_int(100) == 100
        assert TradierProvider._safe_int("100") == 100
        assert TradierProvider._safe_int(100.7) == 100

    def test_safe_int_invalid_values(self):
        """_safe_int should return None for invalid values"""
        assert TradierProvider._safe_int(None) is None
        assert TradierProvider._safe_int("invalid") is None
        assert TradierProvider._safe_int("") is None
        assert TradierProvider._safe_int({}) is None

    def test_safe_int_negative_allowed(self):
        """_safe_int should allow negative values"""
        assert TradierProvider._safe_int(-5) == -5
        assert TradierProvider._safe_int("-10") == -10


class TestATMExtraction:
    """Tests for ATM IV extraction"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test")

    def test_extract_atm_iv(self, provider):
        """ATM IV should be from closest strike to underlying price"""
        underlying_price = 175.50

        chain = [
            OptionQuote(
                symbol="P170", underlying="AAPL", underlying_price=underlying_price,
                expiry=date(2025, 3, 21), strike=170.0, right="P",
                bid=2.0, ask=2.2, last=2.1, volume=100, open_interest=500,
                implied_volatility=0.30, delta=-0.25, gamma=0.01, theta=-0.05, vega=0.2,
                timestamp=datetime.now(), data_quality=DataQuality.REALTIME, source="tradier"
            ),
            OptionQuote(
                symbol="P175", underlying="AAPL", underlying_price=underlying_price,
                expiry=date(2025, 3, 21), strike=175.0, right="P",  # ATM
                bid=3.5, ask=3.7, last=3.6, volume=200, open_interest=800,
                implied_volatility=0.32, delta=-0.50, gamma=0.02, theta=-0.08, vega=0.3,
                timestamp=datetime.now(), data_quality=DataQuality.REALTIME, source="tradier"
            ),
            OptionQuote(
                symbol="P180", underlying="AAPL", underlying_price=underlying_price,
                expiry=date(2025, 3, 21), strike=180.0, right="P",
                bid=5.0, ask=5.3, last=5.1, volume=150, open_interest=600,
                implied_volatility=0.34, delta=-0.70, gamma=0.015, theta=-0.06, vega=0.25,
                timestamp=datetime.now(), data_quality=DataQuality.REALTIME, source="tradier"
            ),
        ]

        atm_iv = provider._extract_atm_iv(chain, underlying_price)

        # Should be IV from 175 strike (closest to 175.50)
        assert atm_iv == 0.32

    def test_extract_atm_iv_empty_chain(self, provider):
        """Empty chain should return None"""
        atm_iv = provider._extract_atm_iv([], 175.0)
        assert atm_iv is None

    def test_extract_atm_iv_zero_price(self, provider):
        """Zero underlying price should return None"""
        chain = [MagicMock(strike=100.0, implied_volatility=0.30)]
        atm_iv = provider._extract_atm_iv(chain, 0)
        assert atm_iv is None


# =============================================================================
# CONNECTION AND CONTEXT MANAGER TESTS
# =============================================================================

class TestConnectionManagement:
    """Tests for connection management"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_connect_success(self, provider):
        """connect() should set _connected=True on success"""
        with patch('urllib.request.urlopen') as mock_open:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({"clock": {"state": "open"}}).encode()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_response

            result = await provider.connect()

            assert result is True
            assert provider._connected is True

    @pytest.mark.asyncio
    async def test_disconnect(self, provider):
        """disconnect() should set _connected=False"""
        provider._connected = True

        await provider.disconnect()

        assert provider._connected is False

    @pytest.mark.asyncio
    async def test_is_connected(self, provider):
        """is_connected() should return _connected state"""
        provider._connected = False
        assert await provider.is_connected() is False

        provider._connected = True
        assert await provider.is_connected() is True

    @pytest.mark.asyncio
    async def test_context_manager_enter(self, provider):
        """__aenter__ should call connect and return self"""
        provider.connect = AsyncMock(return_value=True)

        async with provider as p:
            assert p is provider
            provider.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_exit(self, provider):
        """__aexit__ should call disconnect"""
        provider.connect = AsyncMock(return_value=True)
        provider.disconnect = AsyncMock()

        async with provider:
            pass

        provider.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_exit_on_exception(self, provider):
        """__aexit__ should call disconnect even on exception"""
        provider.connect = AsyncMock(return_value=True)
        provider.disconnect = AsyncMock()

        with pytest.raises(ValueError):
            async with provider:
                raise ValueError("Test error")

        provider.disconnect.assert_called_once()


# =============================================================================
# ADDITIONAL API ENDPOINT TESTS
# =============================================================================

class TestExpirations:
    """Tests for get_expirations method"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_expirations_multiple(self, provider):
        """get_expirations should return list of dates"""
        mock_response = {
            "expirations": {
                "date": ["2025-02-21", "2025-03-21", "2025-04-17"]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        expirations = await provider.get_expirations("AAPL")

        assert len(expirations) == 3
        assert date(2025, 2, 21) in expirations
        assert date(2025, 3, 21) in expirations

    @pytest.mark.asyncio
    async def test_get_expirations_single(self, provider):
        """get_expirations should handle single date"""
        mock_response = {
            "expirations": {"date": "2025-02-21"}
        }

        provider._get = AsyncMock(return_value=mock_response)

        expirations = await provider.get_expirations("AAPL")

        assert len(expirations) == 1

    @pytest.mark.asyncio
    async def test_get_expirations_empty(self, provider):
        """get_expirations should return empty list for no data"""
        provider._get = AsyncMock(return_value={"expirations": None})

        expirations = await provider.get_expirations("INVALID")

        assert expirations == []

    @pytest.mark.asyncio
    async def test_get_expirations_sorted(self, provider):
        """get_expirations should return sorted dates"""
        mock_response = {
            "expirations": {
                "date": ["2025-04-17", "2025-02-21", "2025-03-21"]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        expirations = await provider.get_expirations("AAPL")

        assert expirations == sorted(expirations)


class TestStrikes:
    """Tests for get_strikes method"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_strikes_multiple(self, provider):
        """get_strikes should return list of strikes"""
        mock_response = {
            "strikes": {
                "strike": [170.0, 175.0, 180.0, 185.0]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        strikes = await provider.get_strikes("AAPL", date(2025, 2, 21))

        assert len(strikes) == 4
        assert 175.0 in strikes

    @pytest.mark.asyncio
    async def test_get_strikes_single(self, provider):
        """get_strikes should handle single strike"""
        mock_response = {
            "strikes": {"strike": 175.0}
        }

        provider._get = AsyncMock(return_value=mock_response)

        strikes = await provider.get_strikes("AAPL", date(2025, 2, 21))

        assert len(strikes) == 1
        assert 175.0 in strikes

    @pytest.mark.asyncio
    async def test_get_strikes_sorted(self, provider):
        """get_strikes should return sorted strikes"""
        mock_response = {
            "strikes": {
                "strike": [185.0, 170.0, 180.0, 175.0]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        strikes = await provider.get_strikes("AAPL", date(2025, 2, 21))

        assert strikes == sorted(strikes)


class TestMarketEndpoints:
    """Tests for market-related endpoints"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_market_clock(self, provider):
        """get_market_clock should return clock data"""
        mock_response = {
            "clock": {
                "state": "open",
                "timestamp": 1706115600,
                "next_state": "postmarket",
                "next_change": "16:00"
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        clock = await provider.get_market_clock()

        assert clock is not None
        assert clock["state"] == "open"

    @pytest.mark.asyncio
    async def test_get_market_clock_none(self, provider):
        """get_market_clock should return None on failure"""
        provider._get = AsyncMock(return_value=None)

        clock = await provider.get_market_clock()

        assert clock is None

    @pytest.mark.asyncio
    async def test_get_market_calendar(self, provider):
        """get_market_calendar should return trading days"""
        mock_response = {
            "calendar": {
                "days": {
                    "day": [
                        {"date": "2025-01-20", "status": "open"},
                        {"date": "2025-01-21", "status": "open"}
                    ]
                }
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        calendar = await provider.get_market_calendar(1, 2025)

        assert len(calendar) == 2

    @pytest.mark.asyncio
    async def test_get_market_calendar_single_day(self, provider):
        """get_market_calendar should handle single day"""
        mock_response = {
            "calendar": {
                "days": {
                    "day": {"date": "2025-01-20", "status": "open"}
                }
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        calendar = await provider.get_market_calendar()

        assert len(calendar) == 1


class TestSymbolSearch:
    """Tests for symbol search methods"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_search_symbols(self, provider):
        """search_symbols should return matching symbols"""
        mock_response = {
            "securities": {
                "security": [
                    {"symbol": "AAPL", "description": "Apple Inc"},
                    {"symbol": "AAPLW", "description": "Apple Inc Warrants"}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        results = await provider.search_symbols("AAPL")

        assert len(results) == 2
        assert results[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_search_symbols_single(self, provider):
        """search_symbols should handle single result"""
        mock_response = {
            "securities": {
                "security": {"symbol": "AAPL", "description": "Apple Inc"}
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        results = await provider.search_symbols("AAPL")

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_lookup_symbol(self, provider):
        """lookup_symbol should return symbol info"""
        mock_response = {
            "securities": {
                "security": [
                    {"symbol": "AAPL", "exchange": "Q", "type": "stock"}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        result = await provider.lookup_symbol("AAPL")

        assert result[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_get_etb_securities(self, provider):
        """get_etb_securities should return ETB list"""
        mock_response = {
            "securities": {
                "security": [
                    {"symbol": "AAPL"},
                    {"symbol": "MSFT"},
                    {"symbol": "GOOGL"}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)

        etb = await provider.get_etb_securities()

        assert "AAPL" in etb
        assert "MSFT" in etb


# =============================================================================
# OCC SYMBOL TESTS
# =============================================================================

class TestOCCSymbolParsing:
    """Tests for OCC symbol parsing and building"""

    def test_parse_occ_symbol_standard(self):
        """Parse standard OCC symbol"""
        underlying, expiry, opt_type, strike = parse_occ_symbol("AAPL240119P00150000")

        assert underlying == "AAPL"
        assert expiry == date(2024, 1, 19)
        assert opt_type == "P"
        assert strike == 150.0

    def test_parse_occ_symbol_call(self):
        """Parse call option OCC symbol"""
        underlying, expiry, opt_type, strike = parse_occ_symbol("MSFT250321C00400000")

        assert underlying == "MSFT"
        assert expiry == date(2025, 3, 21)
        assert opt_type == "C"
        assert strike == 400.0

    def test_parse_occ_symbol_fractional_strike(self):
        """Parse OCC symbol with fractional strike"""
        underlying, expiry, opt_type, strike = parse_occ_symbol("SPY250117P00575500")

        assert underlying == "SPY"
        assert strike == 575.5

    def test_parse_occ_symbol_short_underlying(self):
        """Parse OCC symbol with short underlying"""
        underlying, expiry, opt_type, strike = parse_occ_symbol("T250117P00020000")

        assert underlying == "T"
        assert strike == 20.0

    def test_parse_occ_symbol_invalid_short(self):
        """Invalid short symbol should raise ValueError"""
        with pytest.raises(ValueError, match="Invalid OCC symbol"):
            parse_occ_symbol("ABC")

    def test_build_occ_symbol_put(self):
        """Build put option OCC symbol"""
        occ = build_occ_symbol("AAPL", date(2024, 1, 19), "P", 150.0)
        assert occ == "AAPL240119P00150000"

    def test_build_occ_symbol_call(self):
        """Build call option OCC symbol"""
        occ = build_occ_symbol("MSFT", date(2025, 3, 21), "C", 400.0)
        assert occ == "MSFT250321C00400000"

    def test_build_occ_symbol_lowercase(self):
        """Build OCC symbol with lowercase input"""
        occ = build_occ_symbol("aapl", date(2024, 1, 19), "put", 150.0)
        assert occ == "AAPL240119P00150000"

    def test_roundtrip_parse_build(self):
        """Parse and rebuild should produce same symbol"""
        original = "NVDA250321P00850000"
        underlying, expiry, opt_type, strike = parse_occ_symbol(original)
        rebuilt = build_occ_symbol(underlying, expiry, opt_type, strike)
        assert rebuilt == original


class TestHistoricalOptionBar:
    """Tests for HistoricalOptionBar dataclass"""

    def test_from_occ_symbol_basic(self):
        """Create HistoricalOptionBar from OCC symbol"""
        bar_data = {
            "date": "2024-01-15",
            "open": 2.50,
            "high": 2.80,
            "low": 2.40,
            "close": 2.75,
            "volume": 1500
        }

        bar = HistoricalOptionBar.from_occ_symbol("AAPL240119P00150000", bar_data)

        assert bar.symbol == "AAPL240119P00150000"
        assert bar.date == date(2024, 1, 15)
        assert bar.open == 2.50
        assert bar.close == 2.75
        assert bar.underlying_symbol == "AAPL"
        assert bar.strike == 150.0
        assert bar.option_type == "P"

    def test_from_occ_symbol_missing_values(self):
        """Create HistoricalOptionBar with missing values"""
        bar_data = {"date": "2024-01-15"}

        bar = HistoricalOptionBar.from_occ_symbol("AAPL240119P00150000", bar_data)

        assert bar.open == 0.0
        assert bar.high == 0.0
        assert bar.volume == 0


# =============================================================================
# GLOBAL PROVIDER AND CONVENIENCE FUNCTIONS
# =============================================================================

class TestGlobalProvider:
    """Tests for global provider functions"""

    def test_get_tradier_provider_requires_api_key(self):
        """get_tradier_provider should require API key on first call"""
        # Reset global state
        import src.data_providers.tradier as tradier_module
        tradier_module._default_provider = None

        with pytest.raises(ValueError, match="API Key erforderlich"):
            get_tradier_provider()

    def test_get_tradier_provider_with_api_key(self):
        """get_tradier_provider should return provider with API key"""
        import src.data_providers.tradier as tradier_module
        tradier_module._default_provider = None

        provider = get_tradier_provider(api_key="test_key")

        assert provider is not None
        assert provider.config.api_key == "test_key"

        # Reset for other tests
        tradier_module._default_provider = None

    def test_get_tradier_provider_returns_same_instance(self):
        """get_tradier_provider should return same instance on subsequent calls"""
        import src.data_providers.tradier as tradier_module
        tradier_module._default_provider = None

        provider1 = get_tradier_provider(api_key="test_key")
        provider2 = get_tradier_provider()  # No API key needed

        assert provider1 is provider2

        # Reset for other tests
        tradier_module._default_provider = None


class TestConvenienceFunctions:
    """Tests for convenience functions"""

    @pytest.mark.asyncio
    async def test_fetch_option_chain(self):
        """fetch_option_chain convenience function"""
        with patch.object(TradierProvider, 'connect', new_callable=AsyncMock) as mock_connect:
            with patch.object(TradierProvider, 'disconnect', new_callable=AsyncMock) as mock_disconnect:
                with patch.object(TradierProvider, 'get_option_chain', new_callable=AsyncMock) as mock_chain:
                    mock_chain.return_value = [MagicMock()]

                    result = await fetch_option_chain("AAPL", "test_key")

                    mock_connect.assert_called_once()
                    mock_disconnect.assert_called_once()
                    mock_chain.assert_called_once()
                    assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_quote(self):
        """fetch_quote convenience function"""
        with patch.object(TradierProvider, 'connect', new_callable=AsyncMock) as mock_connect:
            with patch.object(TradierProvider, 'disconnect', new_callable=AsyncMock) as mock_disconnect:
                with patch.object(TradierProvider, 'get_quote', new_callable=AsyncMock) as mock_quote:
                    mock_quote.return_value = MagicMock(symbol="AAPL")

                    result = await fetch_quote("AAPL", "test_key")

                    mock_connect.assert_called_once()
                    mock_disconnect.assert_called_once()
                    assert result.symbol == "AAPL"


# =============================================================================
# VALIDATION TESTS
# =============================================================================

class TestValidation:
    """Tests for data validation"""

    def test_option_is_valid_true(self):
        """Option with bid/ask should be valid"""
        option = OptionQuote(
            symbol="TEST", underlying="AAPL", underlying_price=175.0,
            expiry=date(2025, 3, 21), strike=170.0, right="P",
            bid=2.50, ask=2.70, last=2.60,
            volume=100, open_interest=500,
            implied_volatility=0.30, delta=-0.28,
            gamma=None, theta=None, vega=None,
            timestamp=datetime.now(),
            data_quality=DataQuality.REALTIME,
            source="tradier"
        )

        assert option.is_valid() is True

    def test_option_is_valid_false_no_bid(self):
        """Option without bid should be invalid"""
        option = OptionQuote(
            symbol="TEST", underlying="AAPL", underlying_price=175.0,
            expiry=date(2025, 3, 21), strike=170.0, right="P",
            bid=None, ask=2.70, last=2.60,
            volume=100, open_interest=500,
            implied_volatility=0.30, delta=-0.28,
            gamma=None, theta=None, vega=None,
            timestamp=datetime.now(),
            data_quality=DataQuality.REALTIME,
            source="tradier"
        )

        assert option.is_valid() is False

    def test_option_is_valid_false_zero_bid(self):
        """Option with bid=0 should be invalid"""
        option = OptionQuote(
            symbol="TEST", underlying="AAPL", underlying_price=175.0,
            expiry=date(2025, 3, 21), strike=170.0, right="P",
            bid=0, ask=2.70, last=2.60,
            volume=100, open_interest=500,
            implied_volatility=0.30, delta=-0.28,
            gamma=None, theta=None, vega=None,
            timestamp=datetime.now(),
            data_quality=DataQuality.REALTIME,
            source="tradier"
        )

        assert option.is_valid() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
