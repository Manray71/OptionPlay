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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
