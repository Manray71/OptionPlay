# OptionPlay - VIX Handler Tests
# ================================
# Tests für src/handlers/vix.py

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.handlers.vix import VixHandlerMixin
from src.services.vix_strategy import MarketRegime


# =============================================================================
# Mock Classes
# =============================================================================

class MockConfig:
    """Mock config for testing."""
    class Settings:
        class ApiConnection:
            yahoo_timeout = 5
            vix_cache_seconds = 300
        api_connection = ApiConnection()
    settings = Settings()


class MockVixSelector:
    """Mock VIX selector."""
    def get_regime(self, vix):
        if vix is None:
            return MarketRegime.UNKNOWN
        if vix < 15:
            return MarketRegime.LOW_VOL
        elif vix < 20:
            return MarketRegime.NORMAL
        elif vix < 25:
            return MarketRegime.DANGER_ZONE
        elif vix < 30:
            return MarketRegime.ELEVATED
        else:
            return MarketRegime.HIGH_VOL


class MockQuote:
    """Mock quote object."""
    def __init__(self, price=150.0):
        self.last = price
        self.symbol = "AAPL"


class MockVixHandler(VixHandlerMixin):
    """Concrete implementation of VixHandlerMixin for testing."""

    def __init__(self):
        self._config = MockConfig()
        self._vix_selector = MockVixSelector()
        self._current_vix = None
        self._vix_updated = None
        self._rate_limiter = MagicMock()
        self._rate_limiter.acquire = AsyncMock()
        self._rate_limiter.record_success = MagicMock()

    async def _ensure_connected(self):
        """Mock connection."""
        provider = MagicMock()
        provider.get_vix = AsyncMock(return_value=18.5)
        return provider

    async def _get_quote_cached(self, symbol):
        """Mock quote cache."""
        return MockQuote(150.0)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def handler():
    """Create a mock VIX handler."""
    return MockVixHandler()


# =============================================================================
# VIX Fetch Tests
# =============================================================================

class TestGetVix:
    """Tests für get_vix()."""

    @pytest.mark.asyncio
    async def test_get_vix_from_provider(self, handler):
        """Test: VIX vom Provider abrufen."""
        vix = await handler.get_vix()

        assert vix == 18.5
        assert handler._current_vix == 18.5

    @pytest.mark.asyncio
    async def test_get_vix_uses_cache(self, handler):
        """Test: VIX Cache wird verwendet."""
        handler._current_vix = 20.0
        handler._vix_updated = datetime.now()

        vix = await handler.get_vix()

        assert vix == 20.0  # Cached value

    @pytest.mark.asyncio
    async def test_get_vix_force_refresh(self, handler):
        """Test: Force Refresh ignoriert Cache."""
        handler._current_vix = 20.0
        handler._vix_updated = datetime.now()

        vix = await handler.get_vix(force_refresh=True)

        assert vix == 18.5  # Fresh value from provider

    @pytest.mark.asyncio
    async def test_get_vix_fallback_to_yahoo(self, handler):
        """Test: Fallback zu Yahoo bei Provider-Fehler."""
        # Mock provider failure
        async def failing_connect():
            provider = MagicMock()
            provider.get_vix = AsyncMock(return_value=None)
            return provider

        handler._ensure_connected = failing_connect

        with patch.object(handler, '_fetch_vix_yahoo', return_value=19.5):
            vix = await handler.get_vix()

        assert vix == 19.5


# =============================================================================
# Yahoo Fetch Tests
# =============================================================================

class TestFetchVixYahoo:
    """Tests für _fetch_vix_yahoo()."""

    def test_fetch_yahoo_success(self, handler):
        """Test: Yahoo VIX erfolgreich abrufen."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"chart":{"result":[{"meta":{"regularMarketPrice":17.5}}]}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_response):
            vix = handler._fetch_vix_yahoo()

        assert vix == 17.5

    def test_fetch_yahoo_error(self, handler):
        """Test: Yahoo Fehler wird behandelt."""
        with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
            vix = handler._fetch_vix_yahoo()

        assert vix is None


# =============================================================================
# Strategy Recommendation Tests
# =============================================================================

class TestGetStrategyRecommendation:
    """Tests für get_strategy_recommendation()."""

    @pytest.mark.asyncio
    async def test_strategy_recommendation_format(self, handler):
        """Test: Strategy Recommendation wird formatiert."""
        result = await handler.get_strategy_recommendation()

        assert isinstance(result, str)
        # Should contain VIX-based recommendation elements
        # The exact format depends on the formatter


# =============================================================================
# Regime Status Tests
# =============================================================================

class TestGetRegimeStatus:
    """Tests für get_regime_status()."""

    @pytest.mark.asyncio
    async def test_regime_status_no_vix(self, handler):
        """Test: Regime Status ohne VIX."""
        async def no_vix():
            return None
        handler.get_vix = no_vix

        result = await handler.get_regime_status()

        assert "Could not fetch VIX" in result

    @pytest.mark.asyncio
    async def test_regime_status_default_fallback(self, handler):
        """Test: Fallback auf Default Regime wenn kein Model."""
        # This will trigger the default regime path since no trained model exists
        result = await handler.get_regime_status()

        assert isinstance(result, str)
        # Should contain regime information or default message


# =============================================================================
# Strategy for Stock Tests
# =============================================================================

class TestGetStrategyForStock:
    """Tests für get_strategy_for_stock()."""

    @pytest.mark.asyncio
    async def test_strategy_for_stock_basic(self, handler):
        """Test: Strategy für Stock."""
        result = await handler.get_strategy_for_stock("AAPL")

        assert "Strategy for AAPL" in result
        assert "Stock Price" in result
        assert "$150.00" in result

    @pytest.mark.asyncio
    async def test_strategy_for_stock_no_quote(self, handler):
        """Test: Keine Quote verfügbar."""
        handler._get_quote_cached = AsyncMock(return_value=None)

        result = await handler.get_strategy_for_stock("XYZ")

        assert "Cannot get quote" in result


# =============================================================================
# Spread Width Tests
# =============================================================================

# get_spread_width() was removed — spread width is delta-derived (PLAYBOOK §2)


# =============================================================================
# Event Calendar Tests
# =============================================================================

class TestGetEventCalendar:
    """Tests für get_event_calendar()."""

    @pytest.mark.asyncio
    async def test_event_calendar_default_days(self, handler):
        """Test: Event Calendar mit Default 30 Tagen."""
        # Mock EventCalendar to avoid attribute error
        with patch('src.handlers.vix.EventCalendar') as MockCal:
            mock_cal = MagicMock()
            mock_cal.events = []  # Empty events for now
            MockCal.return_value = mock_cal

            result = await handler.get_event_calendar()

            assert "Market Events" in result
            assert "Next 30 Days" in result

    @pytest.mark.asyncio
    async def test_event_calendar_custom_days(self, handler):
        """Test: Event Calendar mit Custom Tagen."""
        with patch('src.handlers.vix.EventCalendar') as MockCal:
            mock_cal = MagicMock()
            mock_cal.events = []
            MockCal.return_value = mock_cal

            result = await handler.get_event_calendar(days=7)

            assert "Next 7 Days" in result

    @pytest.mark.asyncio
    async def test_event_calendar_no_events(self, handler):
        """Test: Event Calendar ohne Events."""
        with patch('src.handlers.vix.EventCalendar') as MockCal:
            mock_cal = MagicMock()
            mock_cal.events = []
            MockCal.return_value = mock_cal

            result = await handler.get_event_calendar(days=60)

            assert "No major events" in result


# =============================================================================
# Integration Tests
# =============================================================================

class TestVixHandlerIntegration:
    """Integration Tests für VIX Handler."""

    @pytest.mark.asyncio
    async def test_vix_update_and_cache(self, handler):
        """Test: VIX wird aktualisiert und gecacht."""
        # First call - fetches from provider
        vix1 = await handler.get_vix()
        assert vix1 is not None

        # Second call - should use cache
        vix2 = await handler.get_vix()
        assert vix2 == vix1

    @pytest.mark.asyncio
    async def test_full_workflow(self, handler):
        """Test: Vollständiger Workflow."""
        # Get VIX
        vix = await handler.get_vix()
        assert vix is not None

        # Get strategy recommendation
        strategy = await handler.get_strategy_recommendation()
        assert isinstance(strategy, str)

        # Get strategy for stock
        stock_strategy = await handler.get_strategy_for_stock("AAPL")
        assert "AAPL" in stock_strategy


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
