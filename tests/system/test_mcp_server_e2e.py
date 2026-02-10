# End-to-End Tests for MCP Server
# =================================

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, datetime

# Import server
from src.mcp_server import OptionPlayServer


class MockQuote:
    """Mock quote object."""
    def __init__(self, symbol="AAPL"):
        self.symbol = symbol
        self.last = 185.50
        self.bid = 185.45
        self.ask = 185.55
        self.volume = 50000000


class MockBar:
    """Mock historical bar."""
    def __init__(self, d, o, h, l, c, v):
        self.date = d
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v


class MockOption:
    """Mock option object."""
    def __init__(self, strike, expiry, bid, ask, delta, iv, oi, volume=100):
        self.strike = strike
        self.expiry = expiry
        self.bid = bid
        self.ask = ask
        self.delta = delta
        self.iv = iv
        self.implied_volatility = iv
        self.open_interest = oi
        self.volume = volume
        self.dte = 30  # Default DTE for tests


class MockEarnings:
    """Mock earnings info."""
    def __init__(self, symbol="AAPL"):
        self.symbol = symbol
        self.earnings_date = "2025-04-25"
        self.days_to_earnings = 90


@pytest.fixture
def mock_api_key():
    """Mock API key for tests."""
    with patch.dict('os.environ', {'MARKETDATA_API_KEY': 'test_api_key_12345'}):
        yield


@pytest.fixture
def mock_provider():
    """Create mock data provider."""
    provider = AsyncMock()
    
    # Mock connect
    provider.connect = AsyncMock(return_value=True)
    provider.disconnect = AsyncMock()
    
    # Mock quote
    provider.get_quote = AsyncMock(return_value=MockQuote())
    
    # Mock VIX
    provider.get_vix = AsyncMock(return_value=18.5)
    
    # Mock historical data
    bars = [
        MockBar("2025-01-01", 180.0, 182.0, 179.0, 181.0, 40000000),
        MockBar("2025-01-02", 181.0, 183.0, 180.0, 182.5, 42000000),
        MockBar("2025-01-03", 182.5, 185.0, 182.0, 184.0, 45000000),
    ]
    provider.get_historical = AsyncMock(return_value=bars)
    provider.get_historical_for_scanner = AsyncMock(return_value=(
        [180.0, 181.0, 182.5, 184.0, 185.5],  # prices
        [40000000, 42000000, 45000000, 48000000, 50000000],  # volumes
        [182.0, 183.0, 185.0, 186.0, 186.5],  # highs
        [179.0, 180.0, 182.0, 183.5, 184.0],  # lows
    ))
    
    # Mock options chain
    options = [
        MockOption(180.0, date(2025, 2, 21), 2.50, 2.60, -0.30, 0.25, 5000),
        MockOption(175.0, date(2025, 2, 21), 1.20, 1.30, -0.20, 0.24, 3000),
        MockOption(185.0, date(2025, 2, 21), 4.50, 4.60, -0.42, 0.26, 4000),
    ]
    provider.get_option_chain = AsyncMock(return_value=options)
    
    # Mock expirations
    expirations = [
        date(2025, 2, 21),
        date(2025, 3, 21),
        date(2025, 4, 17),
    ]
    provider.get_expirations = AsyncMock(return_value=expirations)
    
    # Mock earnings
    provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
    
    return provider


@pytest.fixture
def server(mock_api_key, mock_provider):
    """Create server instance with mocked Tradier provider."""
    with patch('src.mcp_server.get_marketdata_limiter') as mock_limiter:
        mock_limiter.return_value = MagicMock(
            acquire=AsyncMock(),
            record_success=MagicMock(),
            stats=MagicMock(return_value={
                'total_requests': 10,
                'total_waits': 2,
                'avg_wait_time': 0.05,
                'available_tokens': 8.5
            })
        )
        server = OptionPlayServer(api_key="test_key")
        server._tradier_provider = mock_provider
        server._tradier_connected = True
        server._connected = True
        yield server


class TestServerInitialization:
    """Test server initialization."""
    
    def test_init_with_api_key(self, mock_api_key):
        """Test initialization with API key."""
        with patch('src.mcp_server.get_marketdata_limiter'):
            server = OptionPlayServer(api_key="explicit_key")
            assert server._tradier_api_key is not None or server._provider is None

    def test_version(self, server):
        """Test server version."""
        assert server.VERSION == "4.0.0"

    def test_api_key_masked(self, server):
        """Test API key masking."""
        masked = server.api_key_masked
        assert masked is not None


class TestVIXOperations:
    """Test VIX-related operations."""
    
    @pytest.mark.asyncio
    async def test_get_vix(self, server, mock_provider):
        """Test VIX retrieval via Tradier quote."""
        # Tradier's get_quote("VIX") returns MockQuote with last=185.50
        vix = await server.handlers.vix.get_vix()
        assert vix == 185.50  # MockQuote.last

    @pytest.mark.asyncio
    async def test_get_vix_cached(self, server, mock_provider):
        """Test VIX caching."""
        # First call
        vix1 = await server.handlers.vix.get_vix()
        # Second call should use cache
        vix2 = await server.handlers.vix.get_vix()

        assert vix1 == vix2
    
    @pytest.mark.asyncio
    async def test_get_strategy_recommendation(self, server):
        """Test strategy recommendation."""
        result = await server.handlers.vix.get_strategy_recommendation()
        
        assert "Strategy Recommendation" in result
        assert "VIX" in result
        assert "Regime" in result
        assert "Delta" in result


class TestQuoteOperations:
    """Test quote operations."""
    
    @pytest.mark.asyncio
    async def test_get_quote_success(self, server):
        """Test successful quote retrieval."""
        result = await server.handlers.quote.get_quote("AAPL")
        
        assert "Quote: AAPL" in result
        assert "Last:" in result
        assert "185.50" in result
    
    @pytest.mark.asyncio
    async def test_get_quote_invalid_symbol(self, server):
        """Test quote with invalid symbol."""
        result = await server.handlers.quote.get_quote("123INVALID")
        
        assert "Validation Error" in result
    
    @pytest.mark.asyncio
    async def test_get_quote_no_data(self, server, mock_provider):
        """Test quote when no data available."""
        mock_provider.get_quote = AsyncMock(return_value=None)
        
        result = await server.handlers.quote.get_quote("AAPL")
        assert "No quote data available" in result


class TestOptionsOperations:
    """Test options operations."""
    
    @pytest.mark.asyncio
    async def test_get_options_chain(self, server):
        """Test options chain retrieval."""
        result = await server.handlers.quote.get_options_chain("AAPL")
        
        assert "Options Chain: AAPL" in result
        assert "Strike" in result
        assert "Delta" in result
    
    @pytest.mark.asyncio
    async def test_get_options_chain_puts(self, server):
        """Test puts options chain."""
        result = await server.handlers.quote.get_options_chain("AAPL", right="P")
        
        assert "Put" in result
    
    @pytest.mark.asyncio
    async def test_get_options_chain_calls(self, server):
        """Test calls options chain."""
        result = await server.handlers.quote.get_options_chain("AAPL", right="C")
        
        assert "Call" in result
    
    @pytest.mark.asyncio
    async def test_get_expirations(self, server):
        """Test expiration dates retrieval."""
        result = await server.handlers.quote.get_expirations("AAPL")

        assert "Option Expirations: AAPL" in result
        assert "DTE" in result


class TestEarningsOperations:
    """Test earnings operations."""
    
    @pytest.mark.asyncio
    async def test_get_earnings_safe(self, server):
        """Test earnings check with safe distance."""
        from src.constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS
        result = await server.handlers.quote.get_earnings("AAPL", min_days=ENTRY_EARNINGS_MIN_DAYS)

        assert "Earnings: AAPL" in result
        assert "SAFE" in result

    @pytest.mark.asyncio
    async def test_get_earnings_too_close(self, server, mock_provider):
        """Test earnings check with insufficient distance."""
        mock_earnings = MockEarnings()
        mock_earnings.days_to_earnings = 30
        mock_provider.get_earnings_date = AsyncMock(return_value=mock_earnings)

        from src.constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS
        result = await server.handlers.quote.get_earnings("AAPL", min_days=ENTRY_EARNINGS_MIN_DAYS)
        
        assert "TOO CLOSE" in result
    
    @pytest.mark.asyncio
    async def test_earnings_prefilter_basic(self, server):
        """Test earnings prefilter with default settings."""
        result = await server.handlers.quote.earnings_prefilter(
            min_days=45,
            symbols=["AAPL", "MSFT"]
        )
        
        assert "Earnings Pre-Filter" in result
        assert "Summary" in result
        assert "Safe" in result or "safe" in result.lower()
    
    @pytest.mark.asyncio
    async def test_earnings_prefilter_with_show_excluded(self, server):
        """Test earnings prefilter showing excluded symbols."""
        result = await server.handlers.quote.earnings_prefilter(
            min_days=45,
            symbols=["AAPL", "MSFT"],
            show_excluded=True
        )
        
        assert "Earnings Pre-Filter" in result
        assert "Summary" in result
    
    @pytest.mark.asyncio
    async def test_earnings_prefilter_cache_stats(self, server):
        """Test that prefilter includes cache statistics."""
        result = await server.handlers.quote.earnings_prefilter(
            symbols=["AAPL"]
        )
        
        assert "Cache" in result


class TestScanOperations:
    """Test scan operations."""
    
    @pytest.mark.asyncio
    async def test_scan_with_strategy(self, server):
        """Test VIX-aware scan."""
        result = await server.handlers.scan.scan_with_strategy(
            symbols=["AAPL", "MSFT"],
            max_results=5
        )

        assert "Pullback Candidates" in result
        assert "Scanned" in result
    
    @pytest.mark.asyncio
    async def test_scan_pullback_candidates(self, server):
        """Test legacy scan."""
        result = await server.handlers.scan.scan_pullback_candidates(
            symbols=["AAPL"],
            min_score=3.0,
            max_results=5
        )

        assert "Pullback Candidates" in result


class TestAnalysisOperations:
    """Test analysis operations."""
    
    @pytest.mark.asyncio
    async def test_analyze_symbol(self, server):
        """Test complete symbol analysis."""
        result = await server.handlers.analysis.analyze_symbol("AAPL")
        
        assert "Complete Analysis: AAPL" in result
        assert "VIX" in result
        assert "Technical Indicators" in result
        assert "Earnings Check" in result
        assert "Trend Assessment" in result
    
    @pytest.mark.asyncio
    async def test_get_historical_data(self, server):
        """Test historical data retrieval."""
        result = await server.handlers.quote.get_historical_data("AAPL", days=30)
        
        assert "Historical Data: AAPL" in result
        assert "Performance" in result


class TestStrikeRecommendation:
    """Test strike recommendation operations."""
    
    @pytest.mark.asyncio
    async def test_recommend_strikes_basic(self, server):
        """Test basic strike recommendation."""
        result = await server.handlers.analysis.recommend_strikes("AAPL")

        assert "Strike Recommendations: AAPL" in result
        assert "Short Strike" in result
        assert "Long Strike" in result
        assert "Spread Width" in result
    
    @pytest.mark.asyncio
    async def test_recommend_strikes_with_dte(self, server):
        """Test strike recommendation with custom DTE range."""
        result = await server.handlers.analysis.recommend_strikes(
            symbol="AAPL",
            dte_min=20,
            dte_max=45
        )

        assert "Strike Recommendations: AAPL" in result
        # The output format may vary based on recommendations found
    
    @pytest.mark.asyncio
    async def test_recommend_strikes_includes_quality(self, server):
        """Test that recommendation includes quality assessment."""
        result = await server.handlers.analysis.recommend_strikes("AAPL")

        assert "Quality" in result
        # Note: "Confidence" was removed from output format
    
    @pytest.mark.asyncio
    async def test_recommend_strikes_includes_metrics(self, server):
        """Test that recommendation includes metrics."""
        result = await server.handlers.analysis.recommend_strikes("AAPL")
        
        # Should include expected metrics section
        assert "Credit" in result or "Max Profit" in result
    
    @pytest.mark.asyncio
    async def test_recommend_strikes_invalid_symbol(self, server):
        """Test strike recommendation with invalid symbol."""
        result = await server.handlers.analysis.recommend_strikes("!!!INVALID")
        
        assert "Validation Error" in result or "Error" in result


class TestUtilityOperations:
    """Test utility operations."""
    
    def test_get_watchlist_info(self, server):
        """Test watchlist info."""
        result = server.get_watchlist_info()
        
        assert "Watchlist Overview" in result
        assert "Sectors" in result
    
    @pytest.mark.asyncio
    async def test_get_cache_stats(self, server):
        """Test cache stats."""
        result = await server.get_cache_stats()

        assert "Cache Statistics" in result
        assert "Hit Rate" in result
    
    @pytest.mark.asyncio
    async def test_health_check(self, server):
        """Test health check."""
        result = await server.health_check()

        assert "OptionPlay Server Health" in result
        assert "Version" in result
        assert "4.0.0" in result


class TestErrorHandling:
    """Test error handling."""
    
    @pytest.mark.asyncio
    async def test_invalid_symbol_handled(self, server):
        """Test that invalid symbols are handled gracefully."""
        result = await server.handlers.quote.get_quote("!!!INVALID!!!")
        
        # Should return error message, not raise exception
        assert "Validation Error" in result or "Error" in result
    
    @pytest.mark.asyncio
    async def test_connection_error_handled(self, server, mock_provider):
        """Test that connection errors are handled."""
        mock_provider.get_quote = AsyncMock(side_effect=ConnectionError("Network error"))
        
        result = await server.handlers.quote.get_quote("AAPL")
        
        # Should return error message, not crash
        assert "Error" in result


class TestDisconnect:
    """Test disconnect functionality."""
    
    @pytest.mark.asyncio
    async def test_disconnect(self, server, mock_provider):
        """Test server disconnect."""
        await server.disconnect()
        
        mock_provider.disconnect.assert_called_once()
        assert server._connected == False
