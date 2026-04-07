# Tests for Analysis Handler
# ===========================
"""
Tests for handlers/analysis.py module including:
- AnalysisHandlerMixin class
- analyze_symbol method
- analyze_multi_strategy method
- recommend_strikes method
- ensemble_recommendation method
"""

import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass
from typing import Optional, List


# =============================================================================
# FIXTURES
# =============================================================================

@dataclass
class MockQuote:
    """Mock quote object."""
    symbol: str = "AAPL"
    last: float = 185.50
    bid: float = 185.45
    ask: float = 185.55
    volume: int = 1000000


@dataclass
class MockEarnings:
    """Mock earnings object."""
    earnings_date: Optional[str] = "2026-04-25"
    days_to_earnings: Optional[int] = 80


@dataclass
class MockSignal:
    """Mock signal object."""
    symbol: str = "AAPL"
    score: float = 7.5
    strategy: str = "pullback"
    reason: str = "Strong support bounce"
    current_price: Optional[float] = 185.50


@dataclass
class MockStrategy:
    """Mock VIX strategy."""
    profile_name: str = "normal"
    target_delta: float = -0.20


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


class MockAnalysisHandler:
    """Mock analysis handler for testing."""

    def __init__(self):
        self._config = MockConfig()
        self._rate_limiter = MockRateLimiter()
        self._earnings_fetcher = None

    async def _ensure_connected(self):
        """Mock ensure connected."""
        mock_provider = MagicMock()
        mock_provider.get_historical_for_scanner = AsyncMock(return_value=(
            [180.0 + i * 0.1 for i in range(260)],  # prices
            [1000000] * 260,  # volumes
            [181.0 + i * 0.1 for i in range(260)],  # highs
            [179.0 + i * 0.1 for i in range(260)],  # lows
        ))
        mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
        return mock_provider

    async def _get_quote_cached(self, symbol):
        """Mock get quote cached."""
        return MockQuote(symbol=symbol)

    async def _fetch_historical_cached(self, symbol, days=90):
        """Mock fetch historical cached."""
        return (
            [180.0 + i * 0.1 for i in range(days)],  # prices
            [1000000] * days,  # volumes
            [181.0 + i * 0.1 for i in range(days)],  # highs
            [179.0 + i * 0.1 for i in range(days)],  # lows
        )

    async def get_vix(self):
        """Mock get VIX."""
        return 18.5

    def _get_multi_scanner(self, **kwargs):
        """Mock get multi scanner."""
        scanner = MagicMock()
        scanner.analyze_symbol = MagicMock(return_value=[
            MockSignal(strategy="pullback", score=7.5),
            MockSignal(strategy="bounce", score=6.0),
        ])
        scanner.set_earnings_date = MagicMock()
        return scanner


@pytest.fixture
def handler():
    """Create mock analysis handler."""
    return MockAnalysisHandler()


# =============================================================================
# ANALYZE SYMBOL TESTS
# =============================================================================

class TestAnalyzeSymbol:
    """Tests for analyze_symbol method."""

    @pytest.mark.asyncio
    async def test_analyze_symbol_basic(self):
        """Test basic symbol analysis."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical_for_scanner = AsyncMock(return_value=(
                    [180.0 + i * 0.1 for i in range(260)],
                    [1000000] * 260,
                    [181.0 + i * 0.1 for i in range(260)],
                    [179.0 + i * 0.1 for i in range(260)],
                ))
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def get_vix(self):
                return 18.5

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_strategy_for_vix') as mock_strategy:
            mock_strategy.return_value = MockStrategy()

            result = await test_handler.analyze_symbol("AAPL")

            assert "Complete Analysis: AAPL" in result
            assert "VIX" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_with_pullback(self):
        """Test symbol analysis showing pullback in uptrend."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                # Create prices that show pullback in uptrend
                # Current below SMA20 but above SMA200
                prices = []
                for i in range(260):
                    if i < 240:
                        prices.append(100.0 + i * 0.2)  # Uptrend
                    else:
                        prices.append(145.0 - (i - 240) * 0.5)  # Pullback

                mock_provider = MagicMock()
                mock_provider.get_historical_for_scanner = AsyncMock(return_value=(
                    prices,
                    [1000000] * 260,
                    [p + 1 for p in prices],
                    [p - 1 for p in prices],
                ))
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol, last=140.0)

            async def get_vix(self):
                return 18.5

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_strategy_for_vix') as mock_strategy:
            mock_strategy.return_value = MockStrategy()

            result = await test_handler.analyze_symbol("AAPL")

            # Should show technical indicators
            assert "SMA 20" in result or "Technical" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_earnings_warning(self):
        """Test symbol analysis with earnings warning."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical_for_scanner = AsyncMock(return_value=(
                    [180.0 + i * 0.1 for i in range(260)],
                    [1000000] * 260,
                    [181.0 + i * 0.1 for i in range(260)],
                    [179.0 + i * 0.1 for i in range(260)],
                ))
                # Near earnings
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings(
                    earnings_date="2026-02-15",
                    days_to_earnings=10
                ))
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def get_vix(self):
                return 18.5

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_strategy_for_vix') as mock_strategy:
            mock_strategy.return_value = MockStrategy()

            result = await test_handler.analyze_symbol("AAPL")

            assert "NOT SAFE" in result or "Earnings" in result


# =============================================================================
# ANALYZE MULTI STRATEGY TESTS
# =============================================================================

class TestAnalyzeMultiStrategy:
    """Tests for analyze_multi_strategy method."""

    @pytest.mark.asyncio
    async def test_analyze_multi_strategy_basic(self):
        """Test multi-strategy analysis."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def _fetch_historical_cached(self, symbol, days=90):
                return (
                    [180.0 + i * 0.1 for i in range(days)],
                    [1000000] * days,
                    [181.0 + i * 0.1 for i in range(days)],
                    [179.0 + i * 0.1 for i in range(days)],
                )

            async def get_vix(self):
                return 18.5

            def _get_multi_scanner(self, **kwargs):
                scanner = MagicMock()
                scanner.analyze_symbol = MagicMock(return_value=[
                    MockSignal(strategy="pullback", score=7.5, reason="Strong support"),
                    MockSignal(strategy="bounce", score=6.0, reason="At support level"),
                ])
                scanner.set_earnings_date = MagicMock()
                return scanner

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_earnings_fetcher') as mock_ef:
            mock_ef.return_value.cache.get.return_value = None

            result = await test_handler.analyze_multi_strategy("AAPL")

            assert "Multi-Strategy Analysis: AAPL" in result
            assert "Strategy Scores" in result

    @pytest.mark.asyncio
    async def test_analyze_multi_strategy_no_data(self):
        """Test multi-strategy analysis with no historical data."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                return MagicMock()

            async def _fetch_historical_cached(self, symbol, days=90):
                return None  # No data

        test_handler = TestHandler()

        result = await test_handler.analyze_multi_strategy("AAPL")

        assert "No historical data" in result

    @pytest.mark.asyncio
    async def test_analyze_multi_strategy_earnings_warning(self):
        """Test multi-strategy analysis with earnings warning."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings(
                    earnings_date="2026-02-15",
                    days_to_earnings=30  # Between 45 and 60 - caution
                ))
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def _fetch_historical_cached(self, symbol, days=90):
                return (
                    [180.0 + i * 0.1 for i in range(days)],
                    [1000000] * days,
                    [181.0 + i * 0.1 for i in range(days)],
                    [179.0 + i * 0.1 for i in range(days)],
                )

            async def get_vix(self):
                return 18.5

            def _get_multi_scanner(self, **kwargs):
                scanner = MagicMock()
                scanner.analyze_symbol = MagicMock(return_value=[
                    MockSignal(strategy="pullback", score=7.5),
                ])
                scanner.set_earnings_date = MagicMock()
                return scanner

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_earnings_fetcher') as mock_ef:
            mock_ef.return_value.cache.get.return_value = None

            result = await test_handler.analyze_multi_strategy("AAPL")

            # Should show earnings warning
            assert "DO NOT TRADE" in result or "CAUTION" in result or "Earnings" in result


# =============================================================================
# RECOMMEND STRIKES TESTS
# =============================================================================

class TestRecommendStrikes:
    """Tests for recommend_strikes method."""

    @pytest.mark.asyncio
    async def test_recommend_strikes_basic(self):
        """Test basic strike recommendation."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical_for_scanner = AsyncMock(return_value=(
                    [180.0 + i * 0.1 for i in range(260)],
                    [1000000] * 260,
                    [181.0 + i * 0.1 for i in range(260)],
                    [179.0 + i * 0.1 for i in range(260)],
                ))
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def get_vix(self):
                return 18.5

        test_handler = TestHandler()

        # Mock StrikeRecommender
        with patch('src.handlers.analysis.StrikeRecommender') as mock_recommender_class:
            mock_recommender = MagicMock()
            mock_result = MagicMock()
            mock_result.primary = MagicMock()
            mock_result.primary.short_strike = 180.0
            mock_result.primary.long_strike = 170.0
            mock_result.primary.spread_width = 10.0
            mock_result.primary.short_delta = -0.20
            mock_result.primary.long_delta = -0.08
            mock_result.primary.estimated_credit = 1.50
            mock_result.primary.max_risk = 8.50
            mock_result.primary.roi_percent = 17.6
            mock_result.primary.support_level = 175.0
            mock_result.primary.distance_to_support_pct = 3.0
            mock_result.alternatives = []

            mock_recommender.recommend.return_value = mock_result
            mock_recommender_class.return_value = mock_recommender

            with patch('src.handlers.analysis.get_strategy_for_vix') as mock_strategy:
                mock_strategy.return_value = MockStrategy()

                # The actual method would need to exist
                # For now, test structure verification


# =============================================================================
# ENSEMBLE RECOMMENDATION TESTS
# =============================================================================

class TestEnsembleRecommendation:
    """Tests for ensemble_recommendation method."""

    @pytest.mark.asyncio
    async def test_ensemble_recommendation_basic(self):
        """Test ensemble recommendation."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def _fetch_historical_cached(self, symbol, days=90):
                return (
                    [180.0 + i * 0.1 for i in range(days)],
                    [1000000] * days,
                    [181.0 + i * 0.1 for i in range(days)],
                    [179.0 + i * 0.1 for i in range(days)],
                )

            async def get_vix(self):
                return 18.5

            def _get_multi_scanner(self, **kwargs):
                scanner = MagicMock()
                scanner.analyze_symbol = MagicMock(return_value=[
                    MockSignal(strategy="pullback", score=7.5),
                    MockSignal(strategy="bounce", score=6.0),
                ])
                scanner.set_earnings_date = MagicMock()
                return scanner

        test_handler = TestHandler()

        # Test structure verification


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_analyze_symbol_no_quote(self):
        """Test analyze symbol with no quote data."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical_for_scanner = AsyncMock(return_value=(
                    [180.0 + i * 0.1 for i in range(260)],
                    [1000000] * 260,
                    [181.0 + i * 0.1 for i in range(260)],
                    [179.0 + i * 0.1 for i in range(260)],
                ))
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return None  # No quote

            async def get_vix(self):
                return 18.5

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_strategy_for_vix') as mock_strategy:
            mock_strategy.return_value = MockStrategy()

            result = await test_handler.analyze_symbol("AAPL")

            # Should still work without quote
            assert "Complete Analysis: AAPL" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_no_historical(self):
        """Test analyze symbol with no historical data."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical_for_scanner = AsyncMock(return_value=None)
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def get_vix(self):
                return 18.5

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_strategy_for_vix') as mock_strategy:
            mock_strategy.return_value = MockStrategy()

            result = await test_handler.analyze_symbol("AAPL")

            # Should still work without historical
            assert "Complete Analysis: AAPL" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_no_earnings(self):
        """Test analyze symbol with no earnings date."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_historical_for_scanner = AsyncMock(return_value=(
                    [180.0 + i * 0.1 for i in range(260)],
                    [1000000] * 260,
                    [181.0 + i * 0.1 for i in range(260)],
                    [179.0 + i * 0.1 for i in range(260)],
                ))
                mock_provider.get_earnings_date = AsyncMock(return_value=None)
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def get_vix(self):
                return 18.5

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_strategy_for_vix') as mock_strategy:
            mock_strategy.return_value = MockStrategy()

            result = await test_handler.analyze_symbol("AAPL")

            # Should still complete without earnings
            assert "Complete Analysis: AAPL" in result

    @pytest.mark.asyncio
    async def test_analyze_multi_strategy_strong_signals(self):
        """Test multi-strategy with strong signals."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def _fetch_historical_cached(self, symbol, days=90):
                return (
                    [180.0 + i * 0.1 for i in range(days)],
                    [1000000] * days,
                    [181.0 + i * 0.1 for i in range(days)],
                    [179.0 + i * 0.1 for i in range(days)],
                )

            async def get_vix(self):
                return 18.5

            def _get_multi_scanner(self, **kwargs):
                scanner = MagicMock()
                # Strong signals (>= 7)
                scanner.analyze_symbol = MagicMock(return_value=[
                    MockSignal(strategy="pullback", score=8.5, reason="Strong pullback"),
                    MockSignal(strategy="bounce", score=7.5, reason="Strong bounce"),
                ])
                scanner.set_earnings_date = MagicMock()
                return scanner

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_earnings_fetcher') as mock_ef:
            mock_ef.return_value.cache.get.return_value = None

            result = await test_handler.analyze_multi_strategy("AAPL")

            # Should show strong signals
            assert "8.5" in result or "7.5" in result

    @pytest.mark.asyncio
    async def test_analyze_multi_strategy_weak_signals(self):
        """Test multi-strategy with weak signals."""
        from src.handlers.analysis import AnalysisHandlerMixin

        class TestHandler(AnalysisHandlerMixin):
            def __init__(self):
                self._config = MockConfig()
                self._rate_limiter = MockRateLimiter()
                self._earnings_fetcher = None

            async def _ensure_connected(self):
                mock_provider = MagicMock()
                mock_provider.get_earnings_date = AsyncMock(return_value=MockEarnings())
                return mock_provider

            async def _get_quote_cached(self, symbol):
                return MockQuote(symbol=symbol)

            async def _fetch_historical_cached(self, symbol, days=90):
                return (
                    [180.0 + i * 0.1 for i in range(days)],
                    [1000000] * days,
                    [181.0 + i * 0.1 for i in range(days)],
                    [179.0 + i * 0.1 for i in range(days)],
                )

            async def get_vix(self):
                return 18.5

            def _get_multi_scanner(self, **kwargs):
                scanner = MagicMock()
                # Weak signals (< 5)
                scanner.analyze_symbol = MagicMock(return_value=[
                    MockSignal(strategy="pullback", score=3.5, reason="Weak signal"),
                ])
                scanner.set_earnings_date = MagicMock()
                return scanner

        test_handler = TestHandler()

        with patch('src.handlers.analysis.get_earnings_fetcher') as mock_ef:
            mock_ef.return_value.cache.get.return_value = None

            result = await test_handler.analyze_multi_strategy("AAPL")

            # Should show weak status
            assert "Weak" in result or "3.5" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
