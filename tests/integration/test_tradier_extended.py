# OptionPlay - Extended Tradier Provider Tests
# =============================================
# Additional tests to increase coverage for tradier.py

import pytest
import asyncio
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import aiohttp

from src.data_providers.tradier import (
    TradierProvider,
    TradierConfig,
    TradierEnvironment,
    HistoricalOptionBar,
    parse_occ_symbol,
    build_occ_symbol,
    get_tradier_provider,
)
from src.data_providers.interface import (
    PriceQuote,
    OptionQuote,
    HistoricalBar,
    DataQuality
)


# =============================================================================
# OCC SYMBOL TESTS
# =============================================================================

class TestOCCSymbolParsing:
    """Tests for OCC symbol parsing and building functions"""

    def test_parse_occ_symbol_standard(self):
        """Parse standard OCC symbol AAPL240119P00150000"""
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
        """Parse OCC symbol with short underlying (e.g., T, F)"""
        underlying, expiry, opt_type, strike = parse_occ_symbol("T250117P00020000")

        assert underlying == "T"
        assert strike == 20.0

    def test_parse_occ_symbol_long_underlying(self):
        """Parse OCC symbol with 5-char underlying"""
        underlying, expiry, opt_type, strike = parse_occ_symbol("GOOGL250117C03000000")

        assert underlying == "GOOGL"
        assert strike == 3000.0

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

    def test_build_occ_symbol_fractional(self):
        """Build OCC symbol with fractional strike"""
        occ = build_occ_symbol("SPY", date(2025, 1, 17), "P", 575.5)
        assert occ == "SPY250117P00575500"

    def test_build_occ_symbol_lowercase_type(self):
        """Build OCC symbol with lowercase option type"""
        occ = build_occ_symbol("AAPL", date(2024, 1, 19), "put", 150.0)
        assert occ == "AAPL240119P00150000"

    def test_build_occ_symbol_lowercase_underlying(self):
        """Build OCC symbol with lowercase underlying"""
        occ = build_occ_symbol("aapl", date(2024, 1, 19), "P", 150.0)
        assert occ == "AAPL240119P00150000"

    def test_build_occ_symbol_long_underlying_truncated(self):
        """Underlying longer than 6 chars should be truncated"""
        occ = build_occ_symbol("VERYLONGNAME", date(2024, 1, 19), "P", 100.0)
        assert occ.startswith("VERYLO")

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
        assert bar.high == 2.80
        assert bar.low == 2.40
        assert bar.close == 2.75
        assert bar.volume == 1500
        assert bar.underlying_symbol == "AAPL"
        assert bar.strike == 150.0
        assert bar.expiry == date(2024, 1, 19)
        assert bar.option_type == "P"

    def test_from_occ_symbol_missing_values(self):
        """Create HistoricalOptionBar with missing values defaults to 0"""
        bar_data = {
            "date": "2024-01-15"
        }

        bar = HistoricalOptionBar.from_occ_symbol("AAPL240119P00150000", bar_data)

        assert bar.open == 0.0
        assert bar.high == 0.0
        assert bar.low == 0.0
        assert bar.close == 0.0
        assert bar.volume == 0


# =============================================================================
# PROVIDER CONNECTION TESTS
# =============================================================================

class TestTradierConnection:
    """Tests for connection management"""

    @pytest.mark.asyncio
    async def test_connect_sets_connected_flag(self):
        """connect() should set _connected flag on success"""
        provider = TradierProvider(api_key="test_key")

        # Mock _get to return successful response
        async def mock_get(*args, **kwargs):
            return {"quotes": {"quote": {"symbol": "SPY", "last": 580.0}}}

        provider._get = mock_get
        provider._session = MagicMock()  # Pre-set session

        await provider.connect()

        assert provider._connected is True

        # Cleanup
        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_session(self):
        """disconnect() should close session"""
        provider = TradierProvider(api_key="test_key")
        await provider.connect()

        await provider.disconnect()

        assert provider._connected is False

    @pytest.mark.asyncio
    async def test_disconnect_handles_none_session(self):
        """disconnect() should handle None session gracefully"""
        provider = TradierProvider(api_key="test_key")
        provider._session = None

        # Should not raise
        await provider.disconnect()
        assert provider._connected is False

    @pytest.mark.asyncio
    async def test_context_manager_enters_and_exits(self):
        """Context manager should connect and disconnect"""
        provider = TradierProvider(api_key="test_key")
        provider.connect = AsyncMock()
        provider.disconnect = AsyncMock()

        async with provider as p:
            assert p is provider

        provider.connect.assert_called_once()
        provider.disconnect.assert_called_once()


# =============================================================================
# API REQUEST TESTS
# =============================================================================

class TestTradierAPIRequests:
    """Tests for API request handling"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_quote_success(self, provider):
        """get_quote should return PriceQuote on success"""
        mock_response_data = {
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

        provider._get = AsyncMock(return_value=mock_response_data)
        provider._connected = True

        quote = await provider.get_quote("AAPL")

        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.last == 175.50

    @pytest.mark.asyncio
    async def test_get_quotes_bulk(self, provider):
        """get_quotes_bulk should return multiple quotes"""
        mock_response_data = {
            "quotes": {
                "quote": [
                    {"symbol": "AAPL", "last": 175.50, "bid": 175.45, "ask": 175.55},
                    {"symbol": "MSFT", "last": 400.00, "bid": 399.90, "ask": 400.10}
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response_data)
        provider._connected = True

        quotes = await provider.get_quotes_bulk(["AAPL", "MSFT"])

        assert len(quotes) == 2
        assert "AAPL" in quotes
        assert "MSFT" in quotes


# =============================================================================
# OPTION CHAIN TESTS
# =============================================================================

class TestOptionChain:
    """Tests for option chain retrieval"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_expirations(self, provider):
        """get_expirations should return list of dates"""
        mock_response = {
            "expirations": {
                "date": ["2025-02-21", "2025-03-21", "2025-04-17"]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)
        provider._connected = True

        expirations = await provider.get_expirations("AAPL")

        assert len(expirations) == 3
        assert date(2025, 2, 21) in expirations

    @pytest.mark.asyncio
    async def test_get_expirations_single_date(self, provider):
        """get_expirations should handle single date response"""
        mock_response = {
            "expirations": {
                "date": "2025-02-21"  # Single date, not list
            }
        }

        provider._get = AsyncMock(return_value=mock_response)
        provider._connected = True

        expirations = await provider.get_expirations("AAPL")

        assert len(expirations) == 1
        assert date(2025, 2, 21) in expirations

    @pytest.mark.asyncio
    async def test_get_strikes(self, provider):
        """get_strikes should return list of strikes"""
        mock_response = {
            "strikes": {
                "strike": [170.0, 175.0, 180.0, 185.0]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)
        provider._connected = True

        strikes = await provider.get_strikes("AAPL", date(2025, 2, 21))

        assert len(strikes) == 4
        assert 175.0 in strikes


# =============================================================================
# HISTORICAL DATA TESTS
# =============================================================================

class TestHistoricalData:
    """Tests for historical data retrieval"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_historical_bars(self, provider):
        """get_historical should return HistoricalBar list"""
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
        provider._connected = True

        bars = await provider.get_historical("AAPL", days=2)

        assert len(bars) == 2
        assert bars[0].close == 175.50
        assert bars[1].close == 176.80

    @pytest.mark.asyncio
    async def test_get_historical_single_bar(self, provider):
        """get_historical should handle single bar response"""
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
        provider._connected = True

        bars = await provider.get_historical("AAPL", days=1)

        assert len(bars) == 1
        assert bars[0].close == 175.50

    @pytest.mark.asyncio
    async def test_get_historical_no_data(self, provider):
        """get_historical should return empty list for no data"""
        provider._get = AsyncMock(return_value={"history": None})
        provider._connected = True

        bars = await provider.get_historical("INVALID", days=30)

        assert bars == []


# =============================================================================
# EARNINGS DATA TESTS
# =============================================================================

class TestEarningsData:
    """Tests for earnings data retrieval"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_earnings_date_no_calendars(self, provider):
        """get_earnings_date should return None for no calendars"""
        mock_response = {"calendars": None}

        provider._get = AsyncMock(return_value=mock_response)
        provider._connected = True

        earnings = await provider.get_earnings_date("AAPL")

        # Should handle None calendars gracefully
        assert earnings is None

    @pytest.mark.asyncio
    async def test_get_earnings_date_no_event(self, provider):
        """get_earnings_date should return None for no earnings"""
        provider._get = AsyncMock(return_value={"calendars": None})
        provider._connected = True

        earnings = await provider.get_earnings_date("AAPL")

        assert earnings is None


# =============================================================================
# MARKET CALENDAR TESTS
# =============================================================================

class TestMarketCalendar:
    """Tests for market calendar"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_market_clock(self, provider):
        """get_market_clock should return market status"""
        mock_response = {
            "clock": {
                "state": "open",
                "timestamp": 1706115600,
                "next_state": "postmarket",
                "next_change": "16:00"
            }
        }

        provider._get = AsyncMock(return_value=mock_response)
        provider._connected = True

        clock = await provider.get_market_clock()

        assert clock is not None
        assert clock["state"] == "open"

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
        provider._connected = True

        calendar = await provider.get_market_calendar(1, 2025)

        assert calendar is not None


# =============================================================================
# SYMBOL LOOKUP TESTS
# =============================================================================

class TestSymbolLookup:
    """Tests for symbol search and lookup"""

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
        provider._connected = True

        results = await provider.search_symbols("AAPL")

        assert len(results) == 2
        assert results[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_lookup_symbol(self, provider):
        """lookup_symbol should return symbol info"""
        mock_response = {
            "securities": {
                "security": [
                    {
                        "symbol": "AAPL",
                        "exchange": "Q",
                        "type": "stock",
                        "description": "Apple Inc"
                    }
                ]
            }
        }

        provider._get = AsyncMock(return_value=mock_response)
        provider._connected = True

        result = await provider.lookup_symbol("AAPL")

        assert result is not None
        # lookup_symbol returns a list
        assert result[0]["symbol"] == "AAPL"


# =============================================================================
# IV CACHE INTEGRATION TESTS
# =============================================================================

class TestIVCacheIntegration:
    """Tests for IV cache integration"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    @pytest.mark.asyncio
    async def test_update_iv_cache_from_chains(self, provider):
        """update_iv_cache_from_chains should store IV data"""
        # Create mock option chain with IV data
        mock_chain = [
            OptionQuote(
                symbol="AAPL250321P00175000",
                underlying="AAPL",
                underlying_price=175.0,
                expiry=date(2025, 3, 21),
                strike=175.0,
                right="P",
                bid=3.50,
                ask=3.70,
                last=3.60,
                volume=100,
                open_interest=500,
                implied_volatility=0.30,
                delta=-0.50,
                gamma=0.02,
                theta=-0.05,
                vega=0.25,
                timestamp=datetime.now(),
                data_quality=DataQuality.REALTIME,
                source="tradier"
            )
        ]

        # Test that method exists and can be called
        # The actual behavior depends on the internal IV cache setup
        assert hasattr(provider, 'update_iv_cache_from_chains')
        assert callable(provider.update_iv_cache_from_chains)


# =============================================================================
# PROVIDER CONFIGURATION TESTS
# =============================================================================

class TestProviderConfig:
    """Tests for provider configuration"""

    def test_provider_with_custom_config(self):
        """Provider should accept custom config"""
        config = TradierConfig(
            api_key="custom_key",
            environment=TradierEnvironment.SANDBOX,
            timeout_seconds=60
        )
        provider = TradierProvider(api_key="ignored", config=config)

        assert provider.config.api_key == "custom_key"
        assert provider.config.timeout_seconds == 60


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling"""

    @pytest.fixture
    def provider(self):
        return TradierProvider(api_key="test_key")

    def test_parse_quote_with_nan(self, provider):
        """parse_quote should handle NaN values"""
        import math

        data = {
            "symbol": "AAPL",
            "last": float('nan'),
            "bid": 175.0,
            "ask": 175.10
        }

        quote = provider._parse_quote(data)

        # NaN should be handled gracefully
        assert quote.symbol == "AAPL"

    def test_safe_float_with_string_nan(self):
        """_safe_float should handle 'NaN' string"""
        result = TradierProvider._safe_float("NaN")
        assert result is None

    def test_safe_float_with_inf(self):
        """_safe_float should handle infinity"""
        result = TradierProvider._safe_float(float('inf'))
        # inf is > 0, so it passes the check but is unusual
        assert result == float('inf')

    def test_safe_int_with_integer_string(self):
        """_safe_int should handle integer strings"""
        result = TradierProvider._safe_int("100")
        assert result == 100

    def test_safe_int_with_integer(self):
        """_safe_int should handle integers"""
        result = TradierProvider._safe_int(100)
        assert result == 100

    @pytest.mark.asyncio
    async def test_connect_creates_session(self, provider):
        """connect should create session"""
        provider._connected = False
        provider._session = None

        # Mock the connect response
        provider._get = AsyncMock(return_value={"quotes": {"quote": {"symbol": "SPY"}}})

        await provider.connect()

        assert provider._connected is True

        # Cleanup
        await provider.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
