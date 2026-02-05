# Tests for Report Handler Module
# ================================
"""
Tests for ReportHandlerMixin class.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import date


# =============================================================================
# MOCK CLASSES
# =============================================================================

class MockReportHandler:
    """Mock handler for testing ReportHandlerMixin."""

    def __init__(self):
        self._vix_selector = MagicMock()
        self._earnings_fetcher = None
        self._provider = MagicMock()
        self._rate_limiter = MagicMock()
        self._ibkr_bridge = None

    async def get_vix(self):
        return 18.5

    async def _ensure_connected(self):
        return self._provider

    async def _fetch_historical_cached(self, symbol, days):
        return ([100.0] * days, [1000000] * days, [101.0] * days, [99.0] * days)

    def _get_multi_scanner(self, min_score):
        mock_scanner = MagicMock()
        mock_scanner.set_earnings_date = MagicMock()
        mock_scanner.analyze_symbol = MagicMock(return_value=[])
        return mock_scanner


# =============================================================================
# REPORT HANDLER TESTS
# =============================================================================

class TestReportHandlerMixin:
    """Tests for ReportHandlerMixin class."""

    def test_format_market_cap_trillion(self):
        """Test _format_market_cap with trillion value."""
        from src.handlers.report import ReportHandlerMixin

        # Create minimal mock
        handler = MagicMock(spec=ReportHandlerMixin)

        # Call the actual method
        result = ReportHandlerMixin._format_market_cap(handler, 2.5e12)

        assert "T" in result
        assert "$2.50T" == result

    def test_format_market_cap_billion(self):
        """Test _format_market_cap with billion value."""
        from src.handlers.report import ReportHandlerMixin

        handler = MagicMock(spec=ReportHandlerMixin)
        result = ReportHandlerMixin._format_market_cap(handler, 150e9)

        assert "B" in result

    def test_format_market_cap_million(self):
        """Test _format_market_cap with million value."""
        from src.handlers.report import ReportHandlerMixin

        handler = MagicMock(spec=ReportHandlerMixin)
        result = ReportHandlerMixin._format_market_cap(handler, 500e6)

        assert "M" in result

    def test_format_market_cap_none(self):
        """Test _format_market_cap with None value."""
        from src.handlers.report import ReportHandlerMixin

        handler = MagicMock(spec=ReportHandlerMixin)
        result = ReportHandlerMixin._format_market_cap(handler, None)

        assert result == "N/A"

    def test_format_market_cap_small(self):
        """Test _format_market_cap with small value."""
        from src.handlers.report import ReportHandlerMixin

        handler = MagicMock(spec=ReportHandlerMixin)
        result = ReportHandlerMixin._format_market_cap(handler, 500000)

        assert "$" in result

    def test_format_market_cap_zero(self):
        """Test _format_market_cap with zero value."""
        from src.handlers.report import ReportHandlerMixin

        handler = MagicMock(spec=ReportHandlerMixin)
        result = ReportHandlerMixin._format_market_cap(handler, 0)

        assert result == "N/A"


# =============================================================================
# GENERATE REPORT METHOD TESTS
# =============================================================================

class TestGenerateReport:
    """Tests for generate_report method."""

    def test_method_exists(self):
        """Test generate_report method exists."""
        from src.handlers.report import ReportHandlerMixin

        assert hasattr(ReportHandlerMixin, 'generate_report')
        assert callable(getattr(ReportHandlerMixin, 'generate_report'))

    @pytest.mark.asyncio
    async def test_generate_report_returns_string(self):
        """Test generate_report returns a string."""
        from src.handlers.report import ReportHandlerMixin

        class MockHandler(ReportHandlerMixin):
            def __init__(self):
                self._ibkr_bridge = None

        handler = MockHandler()
        result = await handler.generate_report("AAPL")
        assert isinstance(result, str)
        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_generate_report_with_options(self):
        """Test generate_report with options flag."""
        from src.handlers.report import ReportHandlerMixin

        class MockHandler(ReportHandlerMixin):
            def __init__(self):
                self._ibkr_bridge = None

        handler = MockHandler()
        result = await handler.generate_report("AAPL", include_options=True)
        assert "Yes" in result or "Options" in result

    @pytest.mark.asyncio
    async def test_generate_report_with_news(self):
        """Test generate_report with news flag."""
        from src.handlers.report import ReportHandlerMixin

        class MockHandler(ReportHandlerMixin):
            def __init__(self):
                self._ibkr_bridge = None

        handler = MockHandler()
        result = await handler.generate_report("AAPL", include_news=True)
        assert "Yes" in result or "News" in result

    @pytest.mark.asyncio
    async def test_generate_report_different_strategies(self):
        """Test generate_report with different strategies."""
        from src.handlers.report import ReportHandlerMixin

        class MockHandler(ReportHandlerMixin):
            def __init__(self):
                self._ibkr_bridge = None

        handler = MockHandler()

        for strategy in ["pullback", "bounce", "breakout", "earnings_dip"]:
            result = await handler.generate_report("AAPL", strategy=strategy)
            assert strategy.lower() in result.lower() or "Strategy" in result


# =============================================================================
# GENERATE SCAN REPORT TESTS
# =============================================================================

class TestGenerateScanReport:
    """Tests for generate_scan_report method."""

    def test_method_exists(self):
        """Test generate_scan_report method exists."""
        from src.handlers.report import ReportHandlerMixin

        assert hasattr(ReportHandlerMixin, 'generate_scan_report')
        assert callable(getattr(ReportHandlerMixin, 'generate_scan_report'))


# =============================================================================
# CHECK EARNINGS ASYNC TESTS
# =============================================================================

class TestCheckEarningsAsync:
    """Tests for _check_earnings_async method."""

    def test_method_exists(self):
        """Test _check_earnings_async method exists."""
        from src.handlers.report import ReportHandlerMixin

        assert hasattr(ReportHandlerMixin, '_check_earnings_async')

    @pytest.mark.asyncio
    async def test_check_earnings_cached_data(self):
        """Test _check_earnings_async with cached data."""
        from src.handlers.report import ReportHandlerMixin

        class MockHandler(ReportHandlerMixin):
            def __init__(self):
                self._earnings_fetcher = MagicMock()
                cached = MagicMock()
                cached.earnings_date = "2026-03-15"
                self._earnings_fetcher.cache.get.return_value = cached

        handler = MockHandler()
        result = await handler._check_earnings_async("AAPL")
        assert "days_to_earnings" in result
        assert result.get("next_date") == "2026-03-15"

    @pytest.mark.asyncio
    async def test_check_earnings_no_cached_data(self):
        """Test _check_earnings_async without cached data."""
        from src.handlers.report import ReportHandlerMixin

        class MockHandler(ReportHandlerMixin):
            def __init__(self):
                self._earnings_fetcher = MagicMock()
                self._earnings_fetcher.cache.get.return_value = None
                self._earnings_fetcher.fetch.return_value = None

        handler = MockHandler()
        with patch('src.handlers.report.get_earnings_fetcher', return_value=handler._earnings_fetcher):
            result = await handler._check_earnings_async("AAPL")
            assert result.get("days_to_earnings") is None

    @pytest.mark.asyncio
    async def test_check_earnings_handles_exception(self):
        """Test _check_earnings_async handles exceptions."""
        from src.handlers.report import ReportHandlerMixin

        class MockHandler(ReportHandlerMixin):
            def __init__(self):
                self._earnings_fetcher = MagicMock()
                self._earnings_fetcher.cache.get.side_effect = Exception("Test error")

        handler = MockHandler()
        result = await handler._check_earnings_async("AAPL")
        assert result.get("days_to_earnings") is None

    @pytest.mark.asyncio
    async def test_check_earnings_invalid_date_format(self):
        """Test _check_earnings_async with invalid date format."""
        from src.handlers.report import ReportHandlerMixin

        class MockHandler(ReportHandlerMixin):
            def __init__(self):
                self._earnings_fetcher = MagicMock()
                cached = MagicMock()
                cached.earnings_date = "invalid-date"
                self._earnings_fetcher.cache.get.return_value = cached

        handler = MockHandler()
        result = await handler._check_earnings_async("AAPL")
        # Should handle invalid date gracefully
        assert "days_to_earnings" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
