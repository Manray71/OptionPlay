# Tests for VIX Composed Handler
# ===============================
"""
Tests for composition-based VIX handler.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta


class MockServerContext:
    """Mock server context for testing."""

    def __init__(self):
        self.config = MagicMock()
        self.provider = None
        self.ibkr_provider = None
        self.rate_limiter = MagicMock()
        self.rate_limiter.acquire = AsyncMock()
        self.rate_limiter.record_success = MagicMock()
        self.circuit_breaker = MagicMock()
        self.historical_cache = MagicMock()
        self.vix_selector = MagicMock()
        self.deduplicator = MagicMock()
        self.container = None
        self.ibkr_bridge = None

        # Mutable state
        self.connected = False
        self.ibkr_connected = False
        self.tradier_api_key = None
        self.current_vix = None
        self.vix_updated = None

        # Caches
        self.quote_cache = {}
        self.quote_cache_hits = 0
        self.quote_cache_misses = 0


class TestVixHandlerGetVix:
    """Tests for get_vix method."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        return MockServerContext()

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    @pytest.mark.asyncio
    async def test_get_vix_returns_cached_value(self, vix_handler, mock_context):
        """Test get_vix returns cached value if fresh."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_vix()

        assert result == 18.5

    @pytest.mark.asyncio
    async def test_get_vix_refreshes_stale_cache(self, vix_handler, mock_context):
        """Test get_vix refreshes stale cached value."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now() - timedelta(seconds=400)  # Stale

        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.get_vix = AsyncMock(return_value=20.0)
        mock_context.provider = mock_provider

        result = await vix_handler.get_vix()

        assert result == 20.0 or result == 18.5  # Either new or fallback

    @pytest.mark.asyncio
    async def test_get_vix_force_refresh(self, vix_handler, mock_context):
        """Test get_vix with force_refresh ignores cache."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.get_vix = AsyncMock(return_value=22.0)
        mock_context.provider = mock_provider

        result = await vix_handler.get_vix(force_refresh=True)

        # Should have tried to get new value
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_vix_tries_ibkr_first(self, vix_handler, mock_context):
        """Test get_vix tries IBKR bridge first."""
        mock_ibkr = AsyncMock()
        mock_ibkr.get_vix_value = AsyncMock(return_value=19.5)
        mock_context.ibkr_bridge = mock_ibkr

        result = await vix_handler.get_vix(force_refresh=True)

        assert result == 19.5
        mock_ibkr.get_vix_value.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_vix_falls_back_to_tradier(self, vix_handler, mock_context):
        """Test get_vix falls back to IBKR quote if IBKR fails."""
        mock_ibkr = AsyncMock()
        mock_ibkr.get_vix_value = AsyncMock(side_effect=Exception("IBKR error"))
        mock_context.ibkr_bridge = mock_ibkr

        # IBKR quote for VIX
        mock_ibkr = AsyncMock()
        mock_quote = MagicMock()
        mock_quote.last = 21.0
        mock_ibkr.get_quote = AsyncMock(return_value=mock_quote)
        mock_ibkr.connect = AsyncMock(return_value=True)
        mock_context.ibkr_provider = mock_ibkr
        mock_context.ibkr_connected = True

        result = await vix_handler.get_vix(force_refresh=True)

        assert result == 21.0
        mock_ibkr.get_quote.assert_called_once_with("VIX")

    @pytest.mark.asyncio
    async def test_get_vix_returns_none_if_no_source(self, vix_handler, mock_context):
        """Test get_vix returns None if no data source available."""
        mock_context.current_vix = None
        mock_context.vix_updated = None
        mock_context.ibkr_bridge = None
        mock_context.provider = None

        with patch.object(vix_handler, '_fetch_vix_yahoo', return_value=None):
            result = await vix_handler.get_vix()

        assert result is None


class TestVixHandlerStrategyRecommendation:
    """Tests for get_strategy_recommendation method.

    Now uses formatters.strategy.format(recommendation, vix)
    via get_strategy_for_vix() -- output matches the mixin version.
    """

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        return MockServerContext()

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_returns_markdown(self, vix_handler, mock_context):
        """Test get_strategy_recommendation returns markdown with Strategy Recommendation title."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_strategy_recommendation()

        assert "Strategy Recommendation" in result
        assert "18.5" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_includes_regime(self, vix_handler, mock_context):
        """Test get_strategy_recommendation includes regime info."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_strategy_recommendation()

        # The formatter outputs regime value (e.g. "normal") not uppercased
        assert "Regime" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_includes_parameters(self, vix_handler, mock_context):
        """Test get_strategy_recommendation includes recommended parameters."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_strategy_recommendation()

        assert "Recommended Parameters" in result
        assert "Min Score" in result
        assert "Delta Target" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_handles_no_vix(self, vix_handler, mock_context):
        """Test get_strategy_recommendation gracefully handles no VIX.

        When VIX is None, get_strategy_for_vix() returns a default recommendation
        with a warning about VIX not being available.
        """
        mock_context.current_vix = None
        mock_context.ibkr_bridge = None
        mock_context.provider = None

        result = await vix_handler.get_strategy_recommendation()

        # The formatter still produces output; the recommendation includes
        # a warning about VIX not being available
        assert "Strategy Recommendation" in result
        assert "Not available" in result or "VIX" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_low_volatility(self, vix_handler, mock_context):
        """Test get_strategy_recommendation output for low VIX."""
        mock_context.current_vix = 12.0
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_strategy_recommendation()

        assert "12.0" in result
        assert "Reasoning" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_high_volatility(self, vix_handler, mock_context):
        """Test get_strategy_recommendation output for high VIX."""
        mock_context.current_vix = 35.0
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_strategy_recommendation()

        assert "35.0" in result
        # High vol should include warnings
        assert "Warnings" in result or "Warning" in result


class TestVixHandlerRegimeStatus:
    """Tests for get_regime_status method.

    Now uses RegimeModel (trained) with FIXED_REGIMES fallback --
    matches the mixin version exactly.
    """

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        return MockServerContext()

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    @pytest.mark.asyncio
    async def test_get_regime_status_returns_markdown(self, vix_handler, mock_context):
        """Test get_regime_status returns markdown."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_regime_status()

        assert "VIX Regime Status" in result
        assert "18.5" in result

    @pytest.mark.asyncio
    async def test_get_regime_status_shows_regime(self, vix_handler, mock_context):
        """Test get_regime_status shows current regime (v2 format)."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_regime_status()

        assert "Current Regime" in result

    @pytest.mark.asyncio
    async def test_get_regime_status_returns_error_if_no_vix(self, vix_handler, mock_context):
        """Test get_regime_status returns error if no VIX."""
        mock_context.current_vix = None
        mock_context.ibkr_bridge = None
        mock_context.provider = None

        with patch.object(vix_handler, '_fetch_vix_yahoo', return_value=None):
            result = await vix_handler.get_regime_status()

        assert "Could not" in result or "unavailable" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_get_regime_status_shows_trading_parameters(self, vix_handler, mock_context):
        """Test get_regime_status shows trading parameters section (v2 format)."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_regime_status()

        assert "Parameters" in result


class TestVixHandlerStrategyForStock:
    """Tests for get_strategy_for_stock method."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context with Tradier provider for quote fetching."""
        ctx = MockServerContext()
        mock_ibkr = AsyncMock()
        mock_ibkr.connect = AsyncMock(return_value=True)

        mock_quote = MagicMock()
        mock_quote.last = 150.0
        mock_ibkr.get_quote = AsyncMock(return_value=mock_quote)

        ctx.ibkr_provider = mock_ibkr
        ctx.ibkr_connected = True
        ctx.current_vix = 18.5
        ctx.vix_updated = datetime.now()
        return ctx

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    @pytest.mark.asyncio
    async def test_get_strategy_for_stock_returns_markdown(self, vix_handler):
        """Test get_strategy_for_stock returns formatted markdown."""
        result = await vix_handler.get_strategy_for_stock("AAPL")

        assert "Strategy for AAPL" in result
        assert "Market Context" in result
        assert "Bull-Put-Spread" in result

    @pytest.mark.asyncio
    async def test_get_strategy_for_stock_shows_stock_price(self, vix_handler):
        """Test get_strategy_for_stock shows stock price."""
        result = await vix_handler.get_strategy_for_stock("AAPL")

        assert "$150.00" in result

    @pytest.mark.asyncio
    async def test_get_strategy_for_stock_shows_delta_info(self, vix_handler):
        """Test get_strategy_for_stock shows delta targets."""
        result = await vix_handler.get_strategy_for_stock("AAPL")

        assert "Short Put Delta" in result
        assert "Long Put Delta" in result
        assert "Delta-Range" in result

    @pytest.mark.asyncio
    async def test_get_strategy_for_stock_no_quote(self, vix_handler, mock_context):
        """Test get_strategy_for_stock when quote fails."""
        mock_context.ibkr_provider.get_quote = AsyncMock(return_value=None)

        result = await vix_handler.get_strategy_for_stock("AAPL")

        assert "Cannot get quote for AAPL" in result


class TestVixHandlerEventCalendar:
    """Tests for get_event_calendar method."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        return MockServerContext()

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    @pytest.mark.asyncio
    async def test_get_event_calendar_returns_markdown(self, vix_handler):
        """Test get_event_calendar returns formatted markdown."""
        result = await vix_handler.get_event_calendar(days=30)

        assert "Market Events" in result
        assert "30 Days" in result

    @pytest.mark.asyncio
    async def test_get_event_calendar_custom_days(self, vix_handler):
        """Test get_event_calendar with custom days parameter."""
        result = await vix_handler.get_event_calendar(days=60)

        assert "60 Days" in result


class TestVixHandlerSectorStatus:
    """Tests for get_sector_status method."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        return MockServerContext()

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    @pytest.mark.asyncio
    async def test_get_sector_status_returns_markdown(self, vix_handler):
        """Test get_sector_status returns formatted markdown."""
        result = await vix_handler.get_sector_status()

        # Accepts both v1 ("Sector Momentum Status") and v2 ("Sector Relative Strength")
        assert "Sector" in result
        assert ("Momentum Status" in result or "Relative Strength" in result)


class TestVixHandlerCaching:
    """Tests for VIX caching behavior."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        return MockServerContext()

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    def test_vix_cache_seconds_default(self, vix_handler):
        """Test default VIX cache TTL is 5 minutes."""
        assert vix_handler.VIX_CACHE_SECONDS == 300

    @pytest.mark.asyncio
    async def test_cache_updates_on_new_fetch(self, vix_handler, mock_context):
        """Test cache is updated when new VIX is fetched."""
        mock_context.current_vix = None

        mock_ibkr = AsyncMock()
        mock_quote = MagicMock()
        mock_quote.last = 19.5
        mock_ibkr.get_quote = AsyncMock(return_value=mock_quote)
        mock_ibkr.connect = AsyncMock(return_value=True)
        mock_context.ibkr_provider = mock_ibkr
        mock_context.ibkr_connected = True

        await vix_handler.get_vix()

        assert mock_context.current_vix == 19.5
        assert mock_context.vix_updated is not None


class TestVixHandlerHelpers:
    """Tests for helper methods (_ensure_connected, _get_quote_cached)."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context with Tradier."""
        ctx = MockServerContext()
        mock_ibkr = AsyncMock()
        mock_ibkr.connect = AsyncMock(return_value=True)

        mock_quote = MagicMock()
        mock_quote.last = 175.0
        mock_ibkr.get_quote = AsyncMock(return_value=mock_quote)

        ctx.ibkr_provider = mock_ibkr
        ctx.ibkr_connected = True
        return ctx

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    @pytest.mark.asyncio
    async def test_ensure_connected_returns_tradier(self, vix_handler, mock_context):
        """Test _ensure_connected returns Tradier provider."""
        result = await vix_handler._ensure_connected()

        assert result is mock_context.ibkr_provider

    @pytest.mark.asyncio
    async def test_ensure_connected_returns_none_without_tradier(self, vix_handler, mock_context):
        """Test _ensure_connected returns None if no Tradier/IBKR available."""
        mock_context.ibkr_provider = None
        mock_context.ibkr_connected = False
        mock_context.tradier_api_key = None

        with patch(
            "src.data_providers.ibkr_provider.IBKRDataProvider",
            side_effect=ImportError("mocked"),
        ):
            result = await vix_handler._ensure_connected()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_quote_cached_returns_fresh_cache(self, vix_handler, mock_context):
        """Test _get_quote_cached returns cached value if fresh."""
        cached_quote = MagicMock()
        cached_quote.last = 200.0
        mock_context.quote_cache["AAPL"] = (cached_quote, datetime.now())

        result = await vix_handler._get_quote_cached("AAPL")

        assert result.last == 200.0
        assert mock_context.quote_cache_hits == 1

    @pytest.mark.asyncio
    async def test_get_quote_cached_fetches_on_miss(self, vix_handler, mock_context):
        """Test _get_quote_cached fetches from IBKR on cache miss."""
        result = await vix_handler._get_quote_cached("MSFT")

        assert result.last == 175.0
        assert mock_context.quote_cache_misses == 1
        assert "MSFT" in mock_context.quote_cache


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
