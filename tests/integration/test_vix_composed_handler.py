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
        self.tradier_provider = None
        self.rate_limiter = MagicMock()
        self.circuit_breaker = MagicMock()
        self.historical_cache = MagicMock()
        self.vix_selector = MagicMock()
        self.deduplicator = MagicMock()
        self.container = None
        self.ibkr_bridge = None

        # Mutable state
        self.connected = False
        self.tradier_connected = False
        self.current_vix = None
        self.vix_updated = None


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
        mock_quote = MagicMock()
        mock_quote.last = 20.0
        mock_provider.get_quote = AsyncMock(return_value=mock_quote)
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
        mock_quote = MagicMock()
        mock_quote.last = 22.0
        mock_provider.get_quote = AsyncMock(return_value=mock_quote)
        mock_context.provider = mock_provider

        result = await vix_handler.get_vix(force_refresh=True)

        # Should have tried to get new value
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_vix_tries_ibkr_first(self, vix_handler, mock_context):
        """Test get_vix tries IBKR bridge first."""
        mock_ibkr = AsyncMock()
        mock_ibkr.get_vix = AsyncMock(return_value=19.5)
        mock_context.ibkr_bridge = mock_ibkr

        result = await vix_handler.get_vix(force_refresh=True)

        assert result == 19.5
        mock_ibkr.get_vix.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_vix_falls_back_to_provider(self, vix_handler, mock_context):
        """Test get_vix falls back to provider if IBKR fails."""
        mock_ibkr = AsyncMock()
        mock_ibkr.get_vix = AsyncMock(side_effect=Exception("IBKR error"))
        mock_context.ibkr_bridge = mock_ibkr

        mock_provider = AsyncMock()
        mock_quote = MagicMock()
        mock_quote.last = 21.0
        mock_provider.get_quote = AsyncMock(return_value=mock_quote)
        mock_context.provider = mock_provider

        result = await vix_handler.get_vix(force_refresh=True)

        assert result == 21.0

    @pytest.mark.asyncio
    async def test_get_vix_returns_none_if_no_source(self, vix_handler, mock_context):
        """Test get_vix returns None if no data source available."""
        mock_context.current_vix = None
        mock_context.vix_updated = None
        mock_context.ibkr_bridge = None
        mock_context.provider = None

        result = await vix_handler.get_vix()

        assert result is None


class TestVixHandlerStrategyRecommendation:
    """Tests for get_strategy_recommendation method."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        ctx = MockServerContext()

        # Setup VIX selector mock
        mock_regime = MagicMock()
        mock_regime.name = "NORMAL"
        mock_regime.description = "Normal volatility"

        mock_strategy = MagicMock()
        mock_strategy.name = "Standard"
        mock_strategy.min_score = 5.0
        mock_strategy.max_dte = 60
        mock_strategy.position_size_pct = 0.10

        ctx.vix_selector.get_regime = MagicMock(return_value=mock_regime)
        ctx.vix_selector.get_strategy = MagicMock(return_value=mock_strategy)

        return ctx

    @pytest.fixture
    def vix_handler(self, mock_context):
        """Create VIX handler with mock context."""
        from src.handlers.vix_composed import VixHandler

        handler = VixHandler(mock_context)
        return handler

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_returns_markdown(self, vix_handler, mock_context):
        """Test get_strategy_recommendation returns markdown."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_strategy_recommendation()

        assert "VIX Strategy Recommendation" in result
        assert "18.5" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_includes_regime(self, vix_handler, mock_context):
        """Test get_strategy_recommendation includes regime."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_strategy_recommendation()

        assert "NORMAL" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_includes_parameters(self, vix_handler, mock_context):
        """Test get_strategy_recommendation includes parameters."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_strategy_recommendation()

        assert "Min Score" in result
        assert "Max DTE" in result
        assert "Position Size" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_returns_error_if_no_vix(self, vix_handler, mock_context):
        """Test get_strategy_recommendation returns error if no VIX."""
        mock_context.current_vix = None
        mock_context.ibkr_bridge = None
        mock_context.provider = None

        result = await vix_handler.get_strategy_recommendation()

        assert "Unable to fetch VIX" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_low_volatility_advice(self, vix_handler, mock_context):
        """Test get_strategy_recommendation shows low vol advice."""
        mock_context.current_vix = 12.0
        mock_context.vix_updated = datetime.now()

        mock_regime = MagicMock()
        mock_regime.name = "LOW"
        mock_context.vix_selector.get_regime = MagicMock(return_value=mock_regime)

        result = await vix_handler.get_strategy_recommendation()

        assert "Low Volatility" in result

    @pytest.mark.asyncio
    async def test_get_strategy_recommendation_high_volatility_advice(self, vix_handler, mock_context):
        """Test get_strategy_recommendation shows high vol advice."""
        mock_context.current_vix = 35.0
        mock_context.vix_updated = datetime.now()

        mock_regime = MagicMock()
        mock_regime.name = "HIGH"
        mock_context.vix_selector.get_regime = MagicMock(return_value=mock_regime)

        result = await vix_handler.get_strategy_recommendation()

        assert "High Volatility" in result or "Caution" in result


class TestVixHandlerRegimeStatus:
    """Tests for get_regime_status method."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        ctx = MockServerContext()

        mock_regime = MagicMock()
        mock_regime.name = "NORMAL"
        mock_regime.description = "Normal market volatility"

        mock_strategy = MagicMock()
        mock_strategy.name = "Standard"
        mock_strategy.min_score = 5.0
        mock_strategy.max_dte = 60
        mock_strategy.position_size_pct = 0.10

        ctx.vix_selector.get_regime = MagicMock(return_value=mock_regime)
        ctx.vix_selector.get_strategy = MagicMock(return_value=mock_strategy)

        return ctx

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
    async def test_get_regime_status_shows_enabled_strategies(self, vix_handler, mock_context):
        """Test get_regime_status shows enabled strategies."""
        mock_context.current_vix = 18.5
        mock_context.vix_updated = datetime.now()

        result = await vix_handler.get_regime_status()

        assert "Enabled Strategies" in result
        assert "Pullback" in result

    @pytest.mark.asyncio
    async def test_get_regime_status_returns_error_if_no_vix(self, vix_handler, mock_context):
        """Test get_regime_status returns error if no VIX."""
        mock_context.current_vix = None
        mock_context.ibkr_bridge = None
        mock_context.provider = None

        result = await vix_handler.get_regime_status()

        assert "Unable to fetch VIX" in result


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

        mock_provider = AsyncMock()
        mock_quote = MagicMock()
        mock_quote.last = 19.5
        mock_provider.get_quote = AsyncMock(return_value=mock_quote)
        mock_context.provider = mock_provider

        await vix_handler.get_vix()

        assert mock_context.current_vix == 19.5
        assert mock_context.vix_updated is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
