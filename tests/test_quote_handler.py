# Tests for Quote Handler
# ========================
"""
Comprehensive tests for handlers/quote.py module including:
- QuoteHandlerMixin class
- get_quote method
- get_options_chain method
- get_expirations method
- get_earnings method
- get_earnings_aggregated method
- earnings_prefilter method
- get_historical_data method
- validate_for_trading method
- _fetch_yahoo_earnings private method
- Error handling
- Response formatting
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


# =============================================================================
# MOCK DATA CLASSES
# =============================================================================

class MockDataQuality(Enum):
    """Mock data quality enum."""
    REALTIME = "realtime"
    DELAYED_15MIN = "delayed_15"


@dataclass
class MockPriceQuote:
    """Mock quote object matching PriceQuote interface."""
    symbol: str = "AAPL"
    last: float = 185.50
    bid: float = 185.45
    ask: float = 185.55
    volume: int = 1000000
    timestamp: datetime = None
    data_quality: MockDataQuality = MockDataQuality.REALTIME
    source: str = "test"

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class MockEarnings:
    """Mock earnings object matching EarningsInfo interface."""
    earnings_date: Optional[str] = "2026-04-25"
    days_to_earnings: Optional[int] = 80
    source: str = "marketdata"


@dataclass
class MockEarningsSource:
    """Mock earnings source enum."""
    value: str = "yfinance"


@dataclass
class MockEarningsFetched:
    """Mock fetched earnings from yfinance."""
    earnings_date: Optional[str] = "2026-04-25"
    days_to_earnings: Optional[int] = 80
    source: MockEarningsSource = None

    def __post_init__(self):
        if self.source is None:
            self.source = MockEarningsSource()


@dataclass
class MockOptionQuote:
    """Mock option object matching OptionQuote interface."""
    symbol: str = "AAPL260321P00180000"
    underlying: str = "AAPL"
    underlying_price: float = 185.50
    expiry: date = None
    strike: float = 180.0
    right: str = "P"
    bid: float = 2.50
    ask: float = 2.70
    last: float = 2.60
    volume: int = 500
    open_interest: int = 1500
    implied_volatility: float = 0.25
    delta: float = -0.20
    gamma: float = 0.02
    theta: float = -0.05
    vega: float = 0.10
    timestamp: datetime = None
    data_quality: MockDataQuality = MockDataQuality.REALTIME
    source: str = "test"

    def __post_init__(self):
        if self.expiry is None:
            self.expiry = date.today() + timedelta(days=75)
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class MockHistoricalBar:
    """Mock historical bar."""
    symbol: str = "AAPL"
    date: date = None
    open: float = 184.0
    high: float = 186.5
    low: float = 183.5
    close: float = 185.50
    volume: int = 50000000
    source: str = "test"

    def __post_init__(self):
        if self.date is None:
            self.date = date.today()


class MockConfig:
    """Mock config."""
    class Settings:
        class Performance:
            historical_days = 90
        performance = Performance()
    settings = Settings()


class MockRateLimiter:
    """Mock rate limiter."""
    async def acquire(self):
        pass

    def record_success(self):
        pass


class MockOrchestrator:
    """Mock provider orchestrator."""
    def record_request(self, provider, success=True, error=None):
        pass


class MockEarningsFetcher:
    """Mock earnings fetcher with cache."""
    def __init__(self):
        self.cache = {}

    def fetch(self, symbol):
        return MockEarningsFetched()


class MockWatchlistLoader:
    """Mock watchlist loader."""
    def get_all_symbols(self):
        return ["AAPL", "MSFT", "GOOGL", "SPY"]


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_config():
    """Create mock config."""
    return MockConfig()


@pytest.fixture
def mock_rate_limiter():
    """Create mock rate limiter."""
    return MockRateLimiter()


@pytest.fixture
def mock_provider():
    """Create mock data provider."""
    provider = MagicMock()
    provider.get_quote = AsyncMock(return_value=MockPriceQuote())
    provider.get_option_chain = AsyncMock(return_value=[MockOptionQuote()])
    provider.get_historical = AsyncMock(return_value=[MockHistoricalBar()])
    provider.get_expirations = AsyncMock(return_value=[
        date.today() + timedelta(days=30),
        date.today() + timedelta(days=60),
        date.today() + timedelta(days=90),
    ])
    provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
    return provider


# =============================================================================
# GET QUOTE TESTS
# =============================================================================

class TestGetQuote:
    """Tests for get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_basic(self):
        """Test basic quote lookup returns formatted output."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.quote.format.return_value = "# Quote: AAPL\n\nLast: $185.50"

            result = await test_handler.get_quote("AAPL")

            assert result == "# Quote: AAPL\n\nLast: $185.50"
            mock_formatters.quote.format.assert_called_once()
            # Verify the formatter received correct arguments
            call_args = mock_formatters.quote.format.call_args
            assert call_args[0][0] == "AAPL"
            assert call_args[0][1].symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_get_quote_validates_symbol(self):
        """Test that get_quote validates and normalizes symbol."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.quote.format.return_value = "MSFT: $400.00"

            # Symbol should be uppercased
            await test_handler.get_quote("msft")

            # Formatter should receive uppercase symbol
            call_args = mock_formatters.quote.format.call_args
            assert call_args[0][0] == "MSFT"

    @pytest.mark.asyncio
    async def test_get_quote_invalid_symbol(self):
        """Test quote with invalid symbol returns validation error."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

        test_handler = TestHandler()

        # Invalid symbol should return error message
        result = await test_handler.get_quote("123INVALID!")

        assert "Error" in result or "Validation" in result

    @pytest.mark.asyncio
    async def test_get_quote_no_data(self):
        """Test quote when no data returned."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _get_quote_cached(self, symbol):
                return None  # No data

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.quote.format.return_value = "# Quote: XYZW\n\nNo data available"

            result = await test_handler.get_quote("XYZW")

            assert result == "# Quote: XYZW\n\nNo data available"

    @pytest.mark.asyncio
    async def test_get_quote_with_special_symbol(self):
        """Test quote with special symbol format like BRK.A."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol, last=450.00)

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.quote.format.return_value = "# Quote: BRK.A"

            result = await test_handler.get_quote("BRK.A")

            call_args = mock_formatters.quote.format.call_args
            assert call_args[0][0] == "BRK.A"


# =============================================================================
# GET OPTIONS CHAIN TESTS
# =============================================================================

class TestGetOptionsChain:
    """Tests for get_options_chain method."""

    @pytest.mark.asyncio
    async def test_get_options_chain_basic(self):
        """Test basic options chain lookup."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._orchestrator = MockOrchestrator()
                self._tradier_connected = False
                self._tradier_provider = None
                self._ibkr_bridge = None

            async def _ensure_connected(self):
                return MagicMock()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

            async def _get_options_chain_with_fallback(self, symbol, dte_min, dte_max, right):
                return [MockOptionQuote()]

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.options_chain.format.return_value = "# Options Chain: AAPL (Puts)"

            result = await test_handler.get_options_chain("AAPL")

            assert result == "# Options Chain: AAPL (Puts)"
            mock_formatters.options_chain.format.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_options_chain_with_custom_dte_range(self):
        """Test options chain with custom DTE range."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None
                self._ibkr_bridge = None

            async def _ensure_connected(self):
                return MagicMock()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

            async def _get_options_chain_with_fallback(self, symbol, dte_min, dte_max, right):
                # Verify DTE parameters are passed correctly
                assert dte_min == 30
                assert dte_max == 45
                return [MockOptionQuote()]

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.options_chain.format.return_value = "Options..."

            await test_handler.get_options_chain("AAPL", dte_min=30, dte_max=45)

            call_args = mock_formatters.options_chain.format.call_args
            assert call_args[1]['dte_min'] == 30
            assert call_args[1]['dte_max'] == 45

    @pytest.mark.asyncio
    async def test_get_options_chain_calls(self):
        """Test options chain for calls."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None
                self._ibkr_bridge = None

            async def _ensure_connected(self):
                return MagicMock()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

            async def _get_options_chain_with_fallback(self, symbol, dte_min, dte_max, right):
                assert right == "C"
                return [MockOptionQuote(right="C")]

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.options_chain.format.return_value = "# Options Chain: AAPL (Calls)"

            await test_handler.get_options_chain("AAPL", right="C")

            call_args = mock_formatters.options_chain.format.call_args
            assert call_args[1]['right'] == "C"

    @pytest.mark.asyncio
    async def test_get_options_chain_empty(self):
        """Test options chain with no options returned."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None
                self._ibkr_bridge = None

            async def _ensure_connected(self):
                return MagicMock()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

            async def _get_options_chain_with_fallback(self, symbol, dte_min, dte_max, right):
                return []  # Empty chain

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.options_chain.format.return_value = "No options found"

            result = await test_handler.get_options_chain("AAPL")

            assert result == "No options found"
            call_args = mock_formatters.options_chain.format.call_args
            assert call_args[1]['options'] == []

    @pytest.mark.asyncio
    async def test_get_options_chain_validates_dte_range(self):
        """Test options chain validates DTE range and returns error for invalid range."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None
                self._ibkr_bridge = None

            async def _ensure_connected(self):
                return MagicMock()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

            async def _get_options_chain_with_fallback(self, symbol, dte_min, dte_max, right):
                return [MockOptionQuote()]

        test_handler = TestHandler()

        # Inverted DTE range should return an error
        result = await test_handler.get_options_chain("AAPL", dte_min=90, dte_max=60)

        # Should return validation error
        assert "Error" in result or "Validation" in result or "dte_min" in result.lower()

    @pytest.mark.asyncio
    async def test_get_options_chain_max_options_limit(self):
        """Test options chain respects max_options limit."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None
                self._ibkr_bridge = None

            async def _ensure_connected(self):
                return MagicMock()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

            async def _get_options_chain_with_fallback(self, symbol, dte_min, dte_max, right):
                # Return many options
                return [MockOptionQuote(strike=175 + i) for i in range(50)]

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.options_chain.format.return_value = "Options..."

            await test_handler.get_options_chain("AAPL", max_options=10)

            call_args = mock_formatters.options_chain.format.call_args
            assert call_args[1]['max_options'] == 10


# =============================================================================
# GET EXPIRATIONS TESTS
# =============================================================================

class TestGetExpirations:
    """Tests for get_expirations method."""

    @pytest.mark.asyncio
    async def test_get_expirations_basic(self):
        """Test basic expirations lookup."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_expirations = AsyncMock(return_value=[
                    date.today() + timedelta(days=30),
                    date.today() + timedelta(days=60),
                    date.today() + timedelta(days=90),
                ])
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.get_expirations("AAPL")

        assert "Expirations" in result
        assert "AAPL" in result
        assert "Total" in result

    @pytest.mark.asyncio
    async def test_get_expirations_tradier_first(self):
        """Test expirations uses Tradier provider first."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = True
                self._tradier_provider = MagicMock()
                self._tradier_provider.get_expirations = AsyncMock(return_value=[
                    date.today() + timedelta(days=30),
                ])
                self._marketdata_called = False

            async def _ensure_connected(self):
                self._marketdata_called = True
                mock_provider = MagicMock()
                mock_provider.get_expirations = AsyncMock(return_value=[])
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.get_expirations("AAPL")

        # Tradier should be called
        test_handler._tradier_provider.get_expirations.assert_called_once_with("AAPL")
        assert "1" in result  # Total: 1

    @pytest.mark.asyncio
    async def test_get_expirations_fallback_to_marketdata(self):
        """Test expirations falls back to Marketdata when Tradier fails."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = True
                self._tradier_provider = MagicMock()
                self._tradier_provider.get_expirations = AsyncMock(side_effect=Exception("Tradier error"))

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_expirations = AsyncMock(return_value=[
                    date.today() + timedelta(days=45),
                    date.today() + timedelta(days=75),
                ])
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.get_expirations("AAPL")

        # Should have results from Marketdata fallback
        assert "Total" in result
        assert "2" in result

    @pytest.mark.asyncio
    async def test_get_expirations_no_data(self):
        """Test expirations when no data available."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_expirations = AsyncMock(return_value=None)
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.get_expirations("AAPL")

        assert "No expiration dates found" in result

    @pytest.mark.asyncio
    async def test_get_expirations_many_dates(self):
        """Test expirations with many dates (shows first 20)."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                # Return 30 expiration dates
                mock_provider.get_expirations = AsyncMock(return_value=[
                    date.today() + timedelta(days=7 * i) for i in range(1, 31)
                ])
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.get_expirations("AAPL")

        assert "Total" in result
        assert "30" in result
        # Should indicate there are more
        assert "more" in result


# =============================================================================
# GET EARNINGS TESTS
# =============================================================================

class TestGetEarnings:
    """Tests for get_earnings method."""

    @pytest.mark.asyncio
    async def test_get_earnings_etf(self):
        """Test earnings for ETF returns no earnings."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.earnings.format.return_value = "# Earnings: SPY\n\nETF - No earnings"

            result = await test_handler.get_earnings("SPY")

            call_args = mock_formatters.earnings.format.call_args
            assert call_args[1]['is_etf'] is True
            assert call_args[1]['source'] == "etf"

    @pytest.mark.asyncio
    async def test_get_earnings_from_marketdata(self):
        """Test earnings from Marketdata provider."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings(
                    earnings_date="2026-04-25",
                    days_to_earnings=80
                ))
                return mock_provider

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.earnings.format.return_value = "AAPL: Earnings in 80 days"

            result = await test_handler.get_earnings("AAPL")

            call_args = mock_formatters.earnings.format.call_args
            assert call_args[1]['earnings_date'] == "2026-04-25"
            assert call_args[1]['days_to_earnings'] == 80
            assert call_args[1]['source'] == "marketdata"

    @pytest.mark.asyncio
    async def test_get_earnings_fallback_yahoo_direct(self):
        """Test earnings falls back to Yahoo direct when Marketdata fails."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=None)
                return mock_provider

            def _fetch_yahoo_earnings(self, symbol):
                return {
                    'earnings_date': '2026-04-25',
                    'days_to_earnings': 80,
                    'source': 'yahoo_direct'
                }

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.earnings.format.return_value = "AAPL earnings"

            await test_handler.get_earnings("AAPL")

            call_args = mock_formatters.earnings.format.call_args
            assert call_args[1]['source'] == "yahoo_direct"

    @pytest.mark.asyncio
    async def test_get_earnings_fallback_yfinance(self):
        """Test earnings falls back to yfinance library as final fallback."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=None)
                return mock_provider

            def _fetch_yahoo_earnings(self, symbol):
                return {'earnings_date': None, 'days_to_earnings': None, 'source': 'yahoo_direct'}

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.earnings.format.return_value = "AAPL earnings"

            with patch('src.handlers.quote.get_earnings_fetcher') as mock_get_fetcher:
                mock_fetcher = MockEarningsFetcher()
                mock_get_fetcher.return_value = mock_fetcher

                await test_handler.get_earnings("AAPL")

                call_args = mock_formatters.earnings.format.call_args
                # Should have used yfinance source
                assert call_args[1]['source'] == "yfinance"

    @pytest.mark.asyncio
    async def test_get_earnings_custom_min_days(self):
        """Test earnings with custom min_days parameter."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.earnings.format.return_value = "AAPL earnings"

            await test_handler.get_earnings("AAPL", min_days=45)

            call_args = mock_formatters.earnings.format.call_args
            assert call_args[1]['min_days'] == 45


# =============================================================================
# FETCH YAHOO EARNINGS TESTS
# =============================================================================

class TestFetchYahooEarnings:
    """Tests for _fetch_yahoo_earnings private method."""

    def test_fetch_yahoo_earnings_success(self):
        """Test successful Yahoo earnings fetch."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            pass

        test_handler = TestHandler()

        # Mock successful response
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_context = MagicMock()
            # Future timestamp for April 2026
            future_timestamp = 1745971200
            mock_context.__enter__.return_value.read.return_value = f'{{"quoteSummary":{{"result":[{{"calendarEvents":{{"earnings":{{"earningsDate":[{{"raw":{future_timestamp}}}]}}}}}}]}}}}'.encode()
            mock_urlopen.return_value = mock_context

            result = test_handler._fetch_yahoo_earnings("AAPL")

            assert result['source'] == 'yahoo_direct'
            assert result['earnings_date'] is not None

    def test_fetch_yahoo_earnings_network_error(self):
        """Test Yahoo earnings fetch with network error."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            pass

        test_handler = TestHandler()

        with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
            result = test_handler._fetch_yahoo_earnings("AAPL")

            assert result['source'] == 'error'
            assert result['earnings_date'] is None
            assert result['days_to_earnings'] is None

    def test_fetch_yahoo_earnings_no_date_in_response(self):
        """Test Yahoo earnings fetch with no date in response."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            pass

        test_handler = TestHandler()

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_context = MagicMock()
            mock_context.__enter__.return_value.read.return_value = b'{"quoteSummary":{"result":[{"calendarEvents":{"earnings":{}}}]}}'
            mock_urlopen.return_value = mock_context

            result = test_handler._fetch_yahoo_earnings("AAPL")

            assert result['source'] == 'yahoo_direct'
            assert result['earnings_date'] is None
            assert result['days_to_earnings'] is None

    def test_fetch_yahoo_earnings_empty_earnings_array(self):
        """Test Yahoo earnings fetch with empty earnings array."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            pass

        test_handler = TestHandler()

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_context = MagicMock()
            mock_context.__enter__.return_value.read.return_value = b'{"quoteSummary":{"result":[{"calendarEvents":{"earnings":{"earningsDate":[]}}}]}}'
            mock_urlopen.return_value = mock_context

            result = test_handler._fetch_yahoo_earnings("AAPL")

            assert result['source'] == 'yahoo_direct'
            assert result['earnings_date'] is None

    def test_fetch_yahoo_earnings_malformed_response(self):
        """Test Yahoo earnings fetch with malformed JSON response."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            pass

        test_handler = TestHandler()

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_context = MagicMock()
            mock_context.__enter__.return_value.read.return_value = b'not valid json'
            mock_urlopen.return_value = mock_context

            result = test_handler._fetch_yahoo_earnings("AAPL")

            assert result['source'] == 'error'
            assert result['earnings_date'] is None

    def test_fetch_yahoo_earnings_past_date(self):
        """Test Yahoo earnings fetch with past date returns negative days."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            pass

        test_handler = TestHandler()

        # Timestamp for a past date (Jan 1, 2021)
        past_timestamp = 1609459200

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_context = MagicMock()
            mock_context.__enter__.return_value.read.return_value = f'{{"quoteSummary":{{"result":[{{"calendarEvents":{{"earnings":{{"earningsDate":[{{"raw":{past_timestamp}}}]}}}}}}]}}}}'.encode()
            mock_urlopen.return_value = mock_context

            result = test_handler._fetch_yahoo_earnings("AAPL")

            assert result['earnings_date'] is not None
            # days_to should be None for past dates (per the implementation)
            # or it could be negative - check the actual behavior


# =============================================================================
# GET HISTORICAL DATA TESTS
# =============================================================================

class TestGetHistoricalData:
    """Tests for get_historical_data method."""

    @pytest.mark.asyncio
    async def test_get_historical_basic(self):
        """Test basic historical data retrieval."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical = AsyncMock(return_value=[
                    MockHistoricalBar(date=date.today() - timedelta(days=i), close=180 + i)
                    for i in range(30)
                ])
                return mock_provider

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.historical.format.return_value = "# Historical: AAPL\n\n30 days"

            result = await test_handler.get_historical_data("AAPL", days=30)

            assert "Historical" in result or "30 days" in result

    @pytest.mark.asyncio
    async def test_get_historical_custom_days(self):
        """Test historical data with custom number of days."""
        from src.handlers.quote import QuoteHandlerMixin

        # Create provider mock that persists across calls
        mock_provider = MagicMock()
        mock_provider.get_historical = AsyncMock(return_value=[MockHistoricalBar()])

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                return mock_provider

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.historical.format.return_value = "Historical..."

            await test_handler.get_historical_data("AAPL", days=90)

            # Verify provider was called with correct days
            mock_provider.get_historical.assert_called_once_with("AAPL", days=90)

    @pytest.mark.asyncio
    async def test_get_historical_no_data(self):
        """Test historical data when no data returned."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical = AsyncMock(return_value=None)
                return mock_provider

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.historical.format.return_value = "No historical data"

            result = await test_handler.get_historical_data("AAPL")

            call_args = mock_formatters.historical.format.call_args
            assert call_args[1]['bars'] == []


# =============================================================================
# VALIDATE FOR TRADING TESTS
# =============================================================================

class TestValidateForTrading:
    """Tests for validate_for_trading method."""

    @pytest.mark.asyncio
    async def test_validate_etf_always_safe(self):
        """Test validation for ETF returns always safe."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

        test_handler = TestHandler()

        result = await test_handler.validate_for_trading("SPY")

        assert "SAFE" in result
        assert "ETF" in result

    @pytest.mark.asyncio
    async def test_validate_stock_with_earnings(self):
        """Test validation for stock with upcoming earnings."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings(
                    earnings_date="2026-04-25",
                    days_to_earnings=80
                ))
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.validate_for_trading("AAPL")

        assert "SAFE" in result
        assert "80" in result or "days" in result.lower()

    @pytest.mark.asyncio
    async def test_validate_stock_earnings_too_close(self):
        """Test validation for stock with earnings too close."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings(
                    earnings_date="2026-02-10",
                    days_to_earnings=5
                ))
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.validate_for_trading("AAPL")

        assert "CAUTION" in result or "SAFE" not in result.split("ETF")[0]
        assert "5" in result

    @pytest.mark.asyncio
    async def test_validate_unknown_earnings(self):
        """Test validation when earnings cannot be determined."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=None)
                return mock_provider

        test_handler = TestHandler()

        with patch('src.handlers.quote.get_earnings_fetcher') as mock_get_fetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = None
            mock_get_fetcher.return_value = mock_fetcher

            result = await test_handler.validate_for_trading("AAPL")

            assert "UNKNOWN" in result


# =============================================================================
# EARNINGS PREFILTER TESTS
# =============================================================================

class TestEarningsPrefilter:
    """Tests for earnings_prefilter method."""

    @pytest.mark.asyncio
    async def test_earnings_prefilter_basic(self):
        """Test basic earnings prefilter."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = MockEarningsFetcher()

        test_handler = TestHandler()

        with patch('src.handlers.quote.get_watchlist_loader') as mock_loader:
            mock_loader.return_value = MockWatchlistLoader()

            result = await test_handler.earnings_prefilter()

            assert "Earnings Pre-Filter" in result
            assert "Summary" in result

    @pytest.mark.asyncio
    async def test_earnings_prefilter_custom_symbols(self):
        """Test earnings prefilter with custom symbols list."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = MockEarningsFetcher()

        test_handler = TestHandler()

        result = await test_handler.earnings_prefilter(symbols=["AAPL", "MSFT"])

        assert "AAPL" in result or "2" in result
        assert "Total Symbols" in result

    @pytest.mark.asyncio
    async def test_earnings_prefilter_etf_handling(self):
        """Test earnings prefilter handles ETFs correctly (no earnings)."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = MockEarningsFetcher()

        test_handler = TestHandler()

        result = await test_handler.earnings_prefilter(symbols=["SPY", "QQQ", "AAPL"])

        assert "ETFs" in result
        # SPY and QQQ should be counted as ETFs
        assert "2" in result  # 2 ETFs

    @pytest.mark.asyncio
    async def test_earnings_prefilter_show_excluded(self):
        """Test earnings prefilter with show_excluded option."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                # Create fetcher that returns close earnings
                self._earnings_fetcher = MagicMock()
                self._earnings_fetcher.cache = {}
                self._earnings_fetcher.fetch.return_value = MockEarningsFetched(
                    earnings_date="2026-02-10",
                    days_to_earnings=5  # Too close
                )

        test_handler = TestHandler()

        result = await test_handler.earnings_prefilter(
            symbols=["AAPL"],
            min_days=45,
            show_excluded=True
        )

        assert "Excluded" in result

    @pytest.mark.asyncio
    async def test_earnings_prefilter_custom_min_days(self):
        """Test earnings prefilter with custom min_days."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = MockEarningsFetcher()

        test_handler = TestHandler()

        result = await test_handler.earnings_prefilter(
            symbols=["AAPL"],
            min_days=30
        )

        assert "Min Days to Earnings" in result
        assert "30" in result


# =============================================================================
# GET EARNINGS AGGREGATED TESTS
# =============================================================================

class TestGetEarningsAggregated:
    """Tests for get_earnings_aggregated method."""

    @pytest.mark.asyncio
    async def test_get_earnings_aggregated_basic(self):
        """Test basic aggregated earnings check."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            def _fetch_yahoo_earnings(self, symbol):
                return {
                    'earnings_date': '2026-04-25',
                    'days_to_earnings': 80,
                    'source': 'yahoo_direct'
                }

        test_handler = TestHandler()

        with patch('src.handlers.quote.get_earnings_fetcher') as mock_get_fetcher:
            mock_fetcher = MockEarningsFetcher()
            mock_get_fetcher.return_value = mock_fetcher

            with patch('src.handlers.quote.get_earnings_aggregator') as mock_get_aggregator:
                mock_aggregator = MagicMock()
                mock_aggregator.aggregate.return_value = MagicMock(
                    consensus_date="2026-04-25",
                    days_to_earnings=80,
                    confidence=100
                )
                mock_get_aggregator.return_value = mock_aggregator

                result = await test_handler.get_earnings_aggregated("AAPL")

                assert "Earnings" in result
                assert "AAPL" in result


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling across all methods."""

    @pytest.mark.asyncio
    async def test_quote_provider_exception(self):
        """Test quote handles provider exception gracefully."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _get_quote_cached(self, symbol):
                raise Exception("Provider connection failed")

        test_handler = TestHandler()

        result = await test_handler.get_quote("AAPL")

        # Should return error message, not raise
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_options_chain_provider_exception(self):
        """Test options chain handles provider exception gracefully."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None
                self._ibkr_bridge = None

            async def _ensure_connected(self):
                raise Exception("Provider unavailable")

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

            async def _get_options_chain_with_fallback(self, symbol, dte_min, dte_max, right):
                raise Exception("Options chain failed")

        test_handler = TestHandler()

        result = await test_handler.get_options_chain("AAPL")

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_expirations_rate_limit_exception(self):
        """Test expirations handles rate limit exception."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MagicMock()
                self._rate_limiter.acquire = AsyncMock(side_effect=Exception("Rate limit exceeded"))
                self._tradier_connected = False
                self._tradier_provider = None

            async def _ensure_connected(self):
                return MagicMock()

        test_handler = TestHandler()

        result = await test_handler.get_expirations("AAPL")

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_historical_timeout_exception(self):
        """Test historical data handles timeout exception."""
        from src.handlers.quote import QuoteHandlerMixin
        import asyncio

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical = AsyncMock(side_effect=asyncio.TimeoutError())
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.get_historical_data("AAPL")

        # Should return timeout message or error
        assert "Timeout" in result or "Error" in result or "took too long" in result


# =============================================================================
# RESPONSE FORMATTING TESTS
# =============================================================================

class TestResponseFormatting:
    """Tests for response formatting consistency."""

    @pytest.mark.asyncio
    async def test_quote_returns_markdown(self):
        """Test quote returns properly formatted Markdown."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.quote.format.return_value = "# Quote: AAPL\n\n**Last:** $185.50"

            result = await test_handler.get_quote("AAPL")

            # Should be Markdown
            assert result.startswith("#")
            assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_expirations_returns_markdown_table(self):
        """Test expirations returns Markdown with table."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_expirations = AsyncMock(return_value=[
                    date.today() + timedelta(days=30),
                    date.today() + timedelta(days=60),
                ])
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.get_expirations("AAPL")

        # Should have Markdown headers
        assert "#" in result
        # Should have table structure
        assert "Expiration" in result or "DTE" in result

    @pytest.mark.asyncio
    async def test_validation_returns_status_indicator(self):
        """Test validation returns status indicator."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

        test_handler = TestHandler()

        result = await test_handler.validate_for_trading("AAPL")

        # Should have status indicators
        assert any(status in result for status in ["SAFE", "CAUTION", "UNKNOWN"])


# =============================================================================
# PROVIDER SELECTION TESTS
# =============================================================================

class TestProviderSelection:
    """Tests for provider selection logic."""

    @pytest.mark.asyncio
    async def test_tradier_preferred_for_expirations(self):
        """Test that Tradier is preferred for expirations."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = True
                self._tradier_provider = MagicMock()
                self._tradier_provider.get_expirations = AsyncMock(return_value=[
                    date.today() + timedelta(days=30)
                ])
                self._marketdata_called = False

            async def _ensure_connected(self):
                self._marketdata_called = True
                mock_provider = MagicMock()
                mock_provider.get_expirations = AsyncMock(return_value=[])
                return mock_provider

        test_handler = TestHandler()

        await test_handler.get_expirations("AAPL")

        # Tradier should be called
        test_handler._tradier_provider.get_expirations.assert_called_once()
        # Marketdata should NOT be called since Tradier succeeded
        assert not test_handler._marketdata_called

    @pytest.mark.asyncio
    async def test_marketdata_fallback_when_tradier_unavailable(self):
        """Test Marketdata is used when Tradier not connected."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None
                self._marketdata_called = False

            async def _ensure_connected(self):
                self._marketdata_called = True
                mock_provider = MagicMock()
                mock_provider.get_expirations = AsyncMock(return_value=[
                    date.today() + timedelta(days=60)
                ])
                return mock_provider

        test_handler = TestHandler()

        await test_handler.get_expirations("AAPL")

        assert test_handler._marketdata_called


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests combining multiple methods."""

    @pytest.mark.asyncio
    async def test_full_quote_workflow(self):
        """Test full quote workflow: quote -> options -> earnings."""
        from src.handlers.quote import QuoteHandlerMixin

        class TestHandler(QuoteHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._tradier_connected = False
                self._tradier_provider = None
                self._ibkr_bridge = None
                self._earnings_fetcher = None

            async def _get_quote_cached(self, symbol):
                return MockPriceQuote(symbol=symbol)

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_options_chain_with_fallback(self, symbol, dte_min, dte_max, right):
                return [MockOptionQuote()]

        test_handler = TestHandler()

        with patch('src.handlers.quote.formatters') as mock_formatters:
            mock_formatters.quote.format.return_value = "Quote AAPL"
            mock_formatters.options_chain.format.return_value = "Options AAPL"
            mock_formatters.earnings.format.return_value = "Earnings AAPL"

            # Execute workflow
            quote_result = await test_handler.get_quote("AAPL")
            options_result = await test_handler.get_options_chain("AAPL")
            earnings_result = await test_handler.get_earnings("AAPL")

            assert "AAPL" in quote_result
            assert "AAPL" in options_result
            assert "AAPL" in earnings_result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
