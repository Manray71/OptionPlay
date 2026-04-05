# Tests for IBKRDataProvider
# ===========================
"""
Unit tests for src/data_providers/ibkr_provider.py

All IBKR calls are mocked — no live connection required.
"""

import asyncio
import math
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# nest_asyncio is required by ibkr connection at import time
pytest.importorskip("nest_asyncio", reason="nest_asyncio not installed")

from src.data_providers.ibkr_provider import IBKRDataProvider, _valid_float, get_ibkr_provider
from src.data_providers.interface import DataProvider, DataQuality, HistoricalBar, OptionQuote, PriceQuote


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_connection():
    """Create a mocked IBKRConnection."""
    conn = MagicMock()
    conn.host = "127.0.0.1"
    conn.port = 7497
    conn.client_id = 10
    conn._connected = True
    conn.is_available = AsyncMock(return_value=True)
    conn._ensure_connected = AsyncMock(return_value=True)
    conn.disconnect = AsyncMock()

    # Mock the IB instance
    ib = MagicMock()
    ib.isConnected.return_value = True
    conn.ib = ib
    conn._ib = ib

    return conn


@pytest.fixture
def mock_market_data():
    """Create a mocked IBKRMarketData."""
    md = MagicMock()
    md.get_vix_value = AsyncMock(return_value=18.5)
    md.get_quotes_batch = AsyncMock(return_value=[])
    md.get_option_chain = AsyncMock(return_value=[])
    return md


@pytest.fixture
def provider(mock_connection, mock_market_data):
    """Create an IBKRDataProvider with mocked components."""
    p = IBKRDataProvider(host="127.0.0.1", port=7497, client_id=10)
    p._connection = mock_connection
    p._market_data = mock_market_data
    return p


# =============================================================================
# ABC Conformance
# =============================================================================


class TestABCConformance:
    """Test that IBKRDataProvider implements the DataProvider ABC."""

    def test_is_data_provider_subclass(self):
        assert issubclass(IBKRDataProvider, DataProvider)

    def test_can_instantiate(self):
        p = IBKRDataProvider()
        assert isinstance(p, DataProvider)

    def test_name_property(self, provider):
        assert provider.name == "ibkr"

    def test_supported_features(self, provider):
        features = provider.supported_features
        assert "quotes" in features
        assert "options" in features
        assert "historical" in features
        assert "iv" in features
        assert "vix" in features

    def test_all_abc_methods_exist(self, provider):
        """Verify all abstract methods are implemented."""
        assert hasattr(provider, "connect")
        assert hasattr(provider, "disconnect")
        assert hasattr(provider, "is_connected")
        assert hasattr(provider, "get_quote")
        assert hasattr(provider, "get_quotes")
        assert hasattr(provider, "get_historical")
        assert hasattr(provider, "get_option_chain")
        assert hasattr(provider, "get_expirations")
        assert hasattr(provider, "get_iv_data")
        assert hasattr(provider, "get_earnings_date")


# =============================================================================
# Connection
# =============================================================================


class TestConnection:
    """Test connection lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection via mocked components."""
        mock_conn = MagicMock()
        mock_conn._ensure_connected = AsyncMock(return_value=True)
        mock_conn.is_available = AsyncMock(return_value=True)
        mock_conn.ib = MagicMock()
        mock_conn.ib.isConnected.return_value = True

        p = IBKRDataProvider()
        p._connection = mock_conn
        p._market_data = MagicMock()

        result = await p._connection._ensure_connected()
        assert result is True
        assert await p._ensure_ready() is True

    @pytest.mark.asyncio
    async def test_disconnect(self, provider, mock_connection):
        """Test disconnect cleans up."""
        await provider.disconnect()
        mock_connection.disconnect.assert_called_once()
        assert provider._connection is None
        assert provider._market_data is None

    @pytest.mark.asyncio
    async def test_is_connected_true(self, provider, mock_connection):
        """Test is_connected when connected."""
        result = await provider.is_connected()
        assert result is True

    @pytest.mark.asyncio
    async def test_is_connected_false_no_connection(self):
        """Test is_connected when no connection object."""
        p = IBKRDataProvider()
        result = await p.is_connected()
        assert result is False

    @pytest.mark.asyncio
    async def test_is_connected_false_unavailable(self, provider, mock_connection):
        """Test is_connected when IBKR unavailable."""
        mock_connection.is_available = AsyncMock(return_value=False)
        result = await provider.is_connected()
        assert result is False


# =============================================================================
# Quotes
# =============================================================================


class TestGetQuote:
    """Test single quote retrieval."""

    @pytest.mark.asyncio
    async def test_get_quote_success(self, provider, mock_connection):
        """Test successful quote retrieval."""
        # Mock ticker
        ticker = MagicMock()
        ticker.last = 175.50
        ticker.bid = 175.40
        ticker.ask = 175.60
        ticker.close = 174.00
        ticker.volume = 50000000.0
        ticker.markPrice = float("nan")

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqMktData = MagicMock()
        mock_connection.ib.cancelMktData = MagicMock()
        mock_connection.ib.ticker.return_value = ticker

        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock):
            quote = await provider.get_quote("AAPL")

        assert quote is not None
        assert isinstance(quote, PriceQuote)
        assert quote.symbol == "AAPL"
        assert quote.last == 175.50
        assert quote.bid == 175.40
        assert quote.ask == 175.60
        assert quote.volume == 50000000
        assert quote.source == "ibkr"
        assert quote.data_quality == DataQuality.REALTIME

    @pytest.mark.asyncio
    async def test_get_quote_closed_market_fallback(self, provider, mock_connection):
        """Test quote fallback to close price when market closed."""
        ticker = MagicMock()
        ticker.last = float("nan")
        ticker.bid = float("nan")
        ticker.ask = float("nan")
        ticker.close = 174.00
        ticker.volume = float("nan")
        ticker.markPrice = float("nan")

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqMktData = MagicMock()
        mock_connection.ib.cancelMktData = MagicMock()
        mock_connection.ib.ticker.return_value = ticker

        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock):
            quote = await provider.get_quote("AAPL")

        assert quote is not None
        assert quote.last == 174.00
        assert quote.data_quality == DataQuality.DELAYED_15MIN

    @pytest.mark.asyncio
    async def test_get_quote_symbol_mapping(self, provider, mock_connection):
        """Test BRK.B maps to 'BRK B' for IBKR."""
        ticker = MagicMock()
        ticker.last = 450.00
        ticker.bid = 449.50
        ticker.ask = 450.50
        ticker.close = 448.00
        ticker.volume = 1000000.0
        ticker.markPrice = float("nan")

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqMktData = MagicMock()
        mock_connection.ib.cancelMktData = MagicMock()
        mock_connection.ib.ticker.return_value = ticker

        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock):
            quote = await provider.get_quote("BRK.B")

        assert quote is not None
        assert quote.symbol == "BRK.B"  # Original symbol preserved in output

    @pytest.mark.asyncio
    async def test_get_quote_delisted_symbol(self, provider):
        """Test delisted symbol returns None."""
        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock):
            quote = await provider.get_quote("PARA")
        assert quote is None

    @pytest.mark.asyncio
    async def test_get_quote_no_connection(self):
        """Test get_quote when not connected."""
        p = IBKRDataProvider()
        quote = await p.get_quote("AAPL")
        assert quote is None

    @pytest.mark.asyncio
    async def test_get_quote_no_ticker(self, provider, mock_connection):
        """Test get_quote when ticker returns None."""
        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqMktData = MagicMock()
        mock_connection.ib.cancelMktData = MagicMock()
        mock_connection.ib.ticker.return_value = None

        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock):
            quote = await provider.get_quote("AAPL")
        assert quote is None


class TestGetQuotes:
    """Test batch quote retrieval."""

    @pytest.mark.asyncio
    async def test_get_quotes_batch(self, provider, mock_market_data):
        """Test batch quotes converts results."""
        mock_market_data.get_quotes_batch.return_value = [
            {"symbol": "AAPL", "last": 175.0, "bid": 174.9, "ask": 175.1, "volume": 50000000},
            {"symbol": "MSFT", "last": 400.0, "bid": 399.5, "ask": 400.5, "volume": 30000000},
            {"symbol": "PARA", "error": "No IBKR equivalent (skipped)"},
        ]

        quotes = await provider.get_quotes(["AAPL", "MSFT", "PARA"])

        assert len(quotes) == 2
        assert "AAPL" in quotes
        assert "MSFT" in quotes
        assert "PARA" not in quotes
        assert isinstance(quotes["AAPL"], PriceQuote)

    @pytest.mark.asyncio
    async def test_get_quotes_empty(self, provider, mock_market_data):
        """Test empty batch."""
        mock_market_data.get_quotes_batch.return_value = []
        quotes = await provider.get_quotes([])
        assert quotes == {}


# =============================================================================
# Historical
# =============================================================================


class TestGetHistorical:
    """Test historical data retrieval."""

    @pytest.mark.asyncio
    async def test_get_historical_success(self, provider, mock_connection):
        """Test successful historical data fetch."""
        # Mock IBKR bar objects
        bar1 = MagicMock()
        bar1.date = date(2026, 4, 1)
        bar1.open = 170.0
        bar1.high = 176.0
        bar1.low = 169.0
        bar1.close = 175.0
        bar1.volume = 50000000

        bar2 = MagicMock()
        bar2.date = date(2026, 4, 2)
        bar2.open = 175.0
        bar2.high = 178.0
        bar2.low = 174.0
        bar2.close = 177.0
        bar2.volume = 45000000

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqHistoricalDataAsync = AsyncMock(return_value=[bar1, bar2])

        bars = await provider.get_historical("AAPL", days=90)

        assert len(bars) == 2
        assert isinstance(bars[0], HistoricalBar)
        assert bars[0].symbol == "AAPL"
        assert bars[0].date == date(2026, 4, 1)
        assert bars[0].open == 170.0
        assert bars[0].close == 175.0
        assert bars[0].volume == 50000000
        assert bars[0].source == "ibkr"

    @pytest.mark.asyncio
    async def test_get_historical_string_dates(self, provider, mock_connection):
        """Test handling of string date format from IBKR."""
        bar = MagicMock()
        bar.date = "2026-04-01"
        bar.open = 170.0
        bar.high = 176.0
        bar.low = 169.0
        bar.close = 175.0
        bar.volume = 50000000

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqHistoricalDataAsync = AsyncMock(return_value=[bar])

        bars = await provider.get_historical("AAPL", days=30)

        assert len(bars) == 1
        assert bars[0].date == date(2026, 4, 1)

    @pytest.mark.asyncio
    async def test_get_historical_duration_string(self, provider, mock_connection):
        """Test correct duration string for different day counts."""
        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqHistoricalDataAsync = AsyncMock(return_value=[])

        # 90 days → "90 D"
        await provider.get_historical("AAPL", days=90)
        call_args = mock_connection.ib.reqHistoricalDataAsync.call_args
        assert call_args.kwargs.get("durationStr") == "90 D" or \
               (call_args.args and "90 D" in str(call_args))

    @pytest.mark.asyncio
    async def test_get_historical_empty(self, provider, mock_connection):
        """Test handling of empty result."""
        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqHistoricalDataAsync = AsyncMock(return_value=[])

        bars = await provider.get_historical("AAPL", days=30)
        assert bars == []

    @pytest.mark.asyncio
    async def test_get_historical_timeout(self, provider, mock_connection):
        """Test timeout handling."""
        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqHistoricalDataAsync = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        bars = await provider.get_historical("AAPL", days=30)
        assert bars == []

    @pytest.mark.asyncio
    async def test_get_historical_delisted_symbol(self, provider):
        """Test delisted symbol returns empty."""
        bars = await provider.get_historical("PARA", days=30)
        assert bars == []


# =============================================================================
# Options Chain
# =============================================================================


class TestGetOptionChain:
    """Test options chain retrieval."""

    @pytest.mark.asyncio
    async def test_get_option_chain_delegates(self, provider, mock_market_data):
        """Test that get_option_chain delegates to IBKRMarketData."""
        mock_options = [
            OptionQuote(
                symbol="AAPL20260620P170",
                underlying="AAPL",
                underlying_price=175.0,
                expiry=date(2026, 6, 20),
                strike=170.0,
                right="P",
                bid=2.50,
                ask=2.70,
                last=2.60,
                volume=100,
                open_interest=5000,
                implied_volatility=0.25,
                delta=-0.20,
                gamma=0.03,
                theta=-0.05,
                vega=0.15,
                timestamp=datetime.now(),
                data_quality=DataQuality.DELAYED_15MIN,
                source="ibkr",
            )
        ]
        mock_market_data.get_option_chain.return_value = mock_options

        result = await provider.get_option_chain("AAPL", dte_min=60, dte_max=90)

        assert len(result) == 1
        assert result[0].underlying == "AAPL"
        assert result[0].delta == -0.20
        mock_market_data.get_option_chain.assert_called_once_with(
            symbol="AAPL", dte_min=60, dte_max=90, right="P"
        )

    @pytest.mark.asyncio
    async def test_get_option_chain_empty(self, provider, mock_market_data):
        """Test empty chain."""
        mock_market_data.get_option_chain.return_value = []
        result = await provider.get_option_chain("XYZ")
        assert result == []


# =============================================================================
# Expirations
# =============================================================================


class TestGetExpirations:
    """Test expiration date retrieval."""

    @pytest.mark.asyncio
    async def test_get_expirations_success(self, provider, mock_connection):
        """Test successful expiration list."""
        chain_info = MagicMock()
        chain_info.exchange = "SMART"
        chain_info.expirations = ["20260620", "20260717", "20260821"]
        chain_info.strikes = [170.0, 175.0, 180.0]

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqSecDefOptParamsAsync = AsyncMock(return_value=[chain_info])

        result = await provider.get_expirations("AAPL")

        assert len(result) == 3
        assert result[0] == date(2026, 6, 20)
        assert result[1] == date(2026, 7, 17)
        assert result[2] == date(2026, 8, 21)

    @pytest.mark.asyncio
    async def test_get_expirations_empty(self, provider, mock_connection):
        """Test no chains available."""
        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqSecDefOptParamsAsync = AsyncMock(return_value=[])

        result = await provider.get_expirations("XYZ")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_expirations_timeout(self, provider, mock_connection):
        """Test timeout handling."""
        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqSecDefOptParamsAsync = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        result = await provider.get_expirations("AAPL")
        assert result == []


# =============================================================================
# VIX
# =============================================================================


class TestVIX:
    """Test VIX data retrieval."""

    @pytest.mark.asyncio
    async def test_get_vix(self, provider, mock_market_data):
        """Test VIX spot value."""
        mock_market_data.get_vix_value.return_value = 18.5
        result = await provider.get_vix()
        assert result == 18.5

    @pytest.mark.asyncio
    async def test_get_vix_none(self, provider, mock_market_data):
        """Test VIX when not available."""
        mock_market_data.get_vix_value.return_value = None
        result = await provider.get_vix()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_vix_not_connected(self):
        """Test VIX when not connected."""
        p = IBKRDataProvider()
        result = await p.get_vix()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_vix_futures_front(self, provider, mock_connection):
        """Test VIX futures front month."""
        ticker = MagicMock()
        ticker.last = 20.5
        ticker.close = 20.0

        mock_connection.ib.qualifyContracts = MagicMock(return_value=[MagicMock()])
        mock_connection.ib.reqMktData = MagicMock()
        mock_connection.ib.cancelMktData = MagicMock()
        mock_connection.ib.ticker.return_value = ticker

        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.get_vix_futures_front()

        assert result == 20.5


# =============================================================================
# IV Data
# =============================================================================


class TestIVData:
    """Test IV data retrieval."""

    @pytest.mark.asyncio
    async def test_get_iv_data_with_ticker(self, provider, mock_connection):
        """Test IV data from IBKR ticker."""
        ticker = MagicMock()
        ticker.impliedVolatility = 0.28

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqMktData = MagicMock()
        mock_connection.ib.cancelMktData = MagicMock()
        mock_connection.ib.ticker.return_value = ticker

        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock), \
             patch("src.cache.get_fundamentals_manager") as mock_fm:
            fm_instance = MagicMock()
            f = MagicMock()
            f.iv_rank_252d = 45.0
            fm_instance.get_fundamentals.return_value = f
            mock_fm.return_value = fm_instance

            result = await provider.get_iv_data("AAPL")

        assert result is not None
        assert result.symbol == "AAPL"
        assert result.current_iv == 0.28
        assert result.iv_rank == 45.0
        assert result.source.value == "ibkr"

    @pytest.mark.asyncio
    async def test_get_iv_data_no_iv(self, provider, mock_connection):
        """Test IV data when no IV available."""
        ticker = MagicMock()
        ticker.impliedVolatility = float("nan")

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqMktData = MagicMock()
        mock_connection.ib.cancelMktData = MagicMock()
        mock_connection.ib.ticker.return_value = ticker

        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock), \
             patch("src.cache.get_fundamentals_manager", side_effect=Exception("no db")):
            result = await provider.get_iv_data("AAPL")

        assert result is None


# =============================================================================
# Earnings
# =============================================================================


class TestEarningsDate:
    """Test earnings date retrieval."""

    @pytest.mark.asyncio
    async def test_get_earnings_date_from_cache(self, provider):
        """Test earnings date from local cache."""
        with patch("src.cache.get_earnings_history_manager") as mock_mgr:
            manager = MagicMock()
            manager.get_next_earnings_date.return_value = date(2026, 7, 30)
            mock_mgr.return_value = manager

            result = await provider.get_earnings_date("AAPL")

        assert result is not None
        assert result.symbol == "AAPL"
        assert result.earnings_date == "2026-07-30"
        assert result.days_to_earnings == (date(2026, 7, 30) - date.today()).days

    @pytest.mark.asyncio
    async def test_get_earnings_date_not_found(self, provider):
        """Test no earnings date available."""
        with patch("src.cache.get_earnings_history_manager") as mock_mgr:
            manager = MagicMock()
            manager.get_next_earnings_date.return_value = None
            mock_mgr.return_value = manager

            result = await provider.get_earnings_date("XYZ")

        assert result is None


# =============================================================================
# Helper Functions
# =============================================================================


class TestValidFloat:
    """Test _valid_float helper."""

    def test_valid_positive(self):
        assert _valid_float(175.50) == 175.50

    def test_none(self):
        assert _valid_float(None) is None

    def test_nan(self):
        assert _valid_float(float("nan")) is None

    def test_zero(self):
        assert _valid_float(0.0) is None

    def test_negative(self):
        assert _valid_float(-1.0) is None

    def test_string_number(self):
        assert _valid_float("175.50") == 175.50

    def test_invalid_string(self):
        assert _valid_float("abc") is None


class TestFactoryFunction:
    """Test get_ibkr_provider factory."""

    def test_creates_provider(self):
        p = get_ibkr_provider()
        assert isinstance(p, IBKRDataProvider)
        assert p.name == "ibkr"

    def test_custom_params(self):
        p = get_ibkr_provider(host="10.0.0.1", port=4001, client_id=99)
        assert p._host == "10.0.0.1"
        assert p._port == 4001
        assert p._client_id == 99


# =============================================================================
# Rate Limiting
# =============================================================================


class TestRateLimiting:
    """Test rate limiting via semaphores."""

    def test_historical_semaphore_exists(self, provider):
        """Test historical semaphore is configured."""
        assert isinstance(provider._historical_semaphore, asyncio.Semaphore)

    def test_mktdata_semaphore_exists(self, provider):
        """Test market data semaphore is configured."""
        assert isinstance(provider._mktdata_semaphore, asyncio.Semaphore)

    @pytest.mark.asyncio
    async def test_historical_semaphore_limits(self, provider, mock_connection):
        """Test that historical requests respect semaphore."""
        # Set semaphore to 1 to test limiting
        provider._historical_semaphore = asyncio.Semaphore(1)

        bar = MagicMock()
        bar.date = date(2026, 4, 1)
        bar.open = 170.0
        bar.high = 176.0
        bar.low = 169.0
        bar.close = 175.0
        bar.volume = 50000000

        mock_connection.ib.qualifyContracts = MagicMock()
        mock_connection.ib.reqHistoricalDataAsync = AsyncMock(return_value=[bar])

        # Should work with semaphore
        bars = await provider.get_historical("AAPL", days=30)
        assert len(bars) == 1


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_ensure_ready_reconnects(self, provider, mock_connection):
        """Test _ensure_ready reconnects if IB disconnected."""
        mock_connection.ib.isConnected.return_value = False
        mock_connection._ensure_connected.return_value = True

        result = await provider._ensure_ready()
        assert result is True
        mock_connection._ensure_connected.assert_called()

    @pytest.mark.asyncio
    async def test_ensure_ready_no_connection(self):
        """Test _ensure_ready with no connection."""
        p = IBKRDataProvider()
        result = await p._ensure_ready()
        assert result is False

    @pytest.mark.asyncio
    async def test_get_quote_exception(self, provider, mock_connection):
        """Test get_quote handles exceptions gracefully."""
        mock_connection.ib.qualifyContracts = MagicMock(side_effect=Exception("Connection lost"))

        with patch("src.data_providers.ibkr_provider.asyncio.sleep", new_callable=AsyncMock):
            quote = await provider.get_quote("AAPL")
        assert quote is None

    @pytest.mark.asyncio
    async def test_get_historical_exception(self, provider, mock_connection):
        """Test get_historical handles exceptions gracefully."""
        mock_connection.ib.qualifyContracts = MagicMock(side_effect=Exception("Network error"))

        bars = await provider.get_historical("AAPL")
        assert bars == []

    @pytest.mark.asyncio
    async def test_get_option_chain_not_connected(self):
        """Test option chain when not connected."""
        p = IBKRDataProvider()
        result = await p.get_option_chain("AAPL")
        assert result == []
