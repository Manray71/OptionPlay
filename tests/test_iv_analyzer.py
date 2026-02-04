"""
Tests for IVAnalyzer service.

Tests IV Rank and IV Percentile calculation from multiple sources:
- IVCache
- Local DB
- symbol_fundamentals
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pathlib import Path

from src.services.iv_analyzer import (
    IVAnalyzer,
    IVMetrics,
    get_iv_analyzer,
    reset_iv_analyzer,
)
from src.cache.iv_cache_impl import IVData, IVSource


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before each test."""
    reset_iv_analyzer()
    yield
    reset_iv_analyzer()


def _make_iv_data(
    symbol: str = "AAPL",
    iv_rank: float = 55.0,
    iv_percentile: float = 68.0,
    current_iv: float = 0.28,
    data_points: int = 200,
) -> IVData:
    """Create a mock IVData."""
    return IVData(
        symbol=symbol,
        current_iv=current_iv,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        iv_high_52w=0.45,
        iv_low_52w=0.18,
        data_points=data_points,
        source=IVSource.TRADIER,
        updated_at="2026-02-04T12:00:00",
    )


def _make_fetcher(iv_data: IVData = None):
    """Create a mock IVFetcher."""
    fetcher = MagicMock()
    if iv_data is None:
        iv_data = _make_iv_data()
    fetcher.get_iv_rank = MagicMock(return_value=iv_data)
    return fetcher


# =============================================================================
# TESTS: IVMetrics
# =============================================================================

class TestIVMetrics:
    """Test IVMetrics dataclass."""

    def test_is_elevated_true(self):
        m = IVMetrics(
            symbol="AAPL", iv_rank=55.0, iv_percentile=68.0,
            current_iv=0.28, current_iv_pct=28.0,
            iv_high_52w=0.45, iv_low_52w=0.18,
            data_points=200, source="cache",
        )
        assert m.is_elevated is True

    def test_is_elevated_false(self):
        m = IVMetrics(
            symbol="AAPL", iv_rank=30.0, iv_percentile=40.0,
            current_iv=0.22, current_iv_pct=22.0,
            iv_high_52w=0.45, iv_low_52w=0.18,
            data_points=200, source="cache",
        )
        assert m.is_elevated is False

    def test_is_elevated_none(self):
        m = IVMetrics(
            symbol="AAPL", iv_rank=None, iv_percentile=None,
            current_iv=None, current_iv_pct=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source="none",
        )
        assert m.is_elevated is False

    def test_iv_status_very_high(self):
        m = IVMetrics(
            symbol="AAPL", iv_rank=75.0, iv_percentile=None,
            current_iv=None, current_iv_pct=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source="cache",
        )
        assert m.iv_status == "very_high"

    def test_iv_status_normal(self):
        m = IVMetrics(
            symbol="AAPL", iv_rank=40.0, iv_percentile=None,
            current_iv=None, current_iv_pct=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source="cache",
        )
        assert m.iv_status == "normal"

    def test_iv_status_low(self):
        m = IVMetrics(
            symbol="AAPL", iv_rank=15.0, iv_percentile=None,
            current_iv=None, current_iv_pct=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source="cache",
        )
        assert m.iv_status == "low"

    def test_iv_status_unknown(self):
        m = IVMetrics(
            symbol="AAPL", iv_rank=None, iv_percentile=None,
            current_iv=None, current_iv_pct=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source="none",
        )
        assert m.iv_status == "unknown"


# =============================================================================
# TESTS: IVAnalyzer from Cache
# =============================================================================

class TestIVAnalyzerFromCache:
    """Test IVAnalyzer using IVCache source."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_metrics(self):
        """Valid cache data → returns IVMetrics with cache source."""
        iv_data = _make_iv_data(iv_rank=55.0, iv_percentile=68.0)
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        metrics = await analyzer.get_iv_metrics("AAPL", current_iv=0.28)

        assert metrics.iv_rank == 55.0
        assert metrics.iv_percentile == 68.0
        assert metrics.source == "cache"
        assert metrics.data_points == 200

    @pytest.mark.asyncio
    async def test_cache_miss_tries_next_source(self):
        """Cache returns None iv_rank → falls through to next source."""
        iv_data_no_rank = IVData(
            symbol="AAPL", current_iv=0.28,
            iv_rank=None, iv_percentile=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=5, source=IVSource.UNKNOWN,
            updated_at="2026-02-04T12:00:00",
        )
        fetcher = _make_fetcher(iv_data_no_rank)
        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )
        # Explicitly disable fundamentals fallback
        analyzer._fundamentals = MagicMock()
        analyzer._fundamentals.get_fundamentals = MagicMock(return_value=None)

        metrics = await analyzer.get_iv_metrics("AAPL")

        # Should fall through to "none" since DB doesn't exist and fundamentals returns None
        assert metrics.source == "none"
        assert metrics.iv_rank is None

    @pytest.mark.asyncio
    async def test_insufficient_data_points_skips_cache(self):
        """Cache with < 20 data points → skip to next source."""
        iv_data = IVData(
            symbol="AAPL", current_iv=0.28,
            iv_rank=55.0, iv_percentile=68.0,
            iv_high_52w=0.45, iv_low_52w=0.18,
            data_points=10,  # < 20
            source=IVSource.TRADIER,
            updated_at="2026-02-04T12:00:00",
        )
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )
        # Explicitly disable fundamentals fallback
        analyzer._fundamentals = MagicMock()
        analyzer._fundamentals.get_fundamentals = MagicMock(return_value=None)

        metrics = await analyzer.get_iv_metrics("AAPL")

        # Should skip cache (data_points < 20) and fall through
        assert metrics.source == "none"


# =============================================================================
# TESTS: IVAnalyzer from Fundamentals
# =============================================================================

class TestIVAnalyzerFromFundamentals:
    """Test IVAnalyzer using symbol_fundamentals fallback."""

    @pytest.mark.asyncio
    async def test_fundamentals_fallback(self):
        """When cache fails, uses fundamentals as fallback."""
        # Cache returns no data
        iv_data_empty = IVData(
            symbol="AAPL", current_iv=0.0,
            iv_rank=None, iv_percentile=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source=IVSource.UNKNOWN,
            updated_at="",
        )
        fetcher = _make_fetcher(iv_data_empty)
        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )

        # Mock fundamentals
        mock_fundamentals = MagicMock()
        mock_f = MagicMock()
        mock_f.iv_rank_252d = 62.5
        mock_f.iv_percentile_252d = 74.0
        mock_fundamentals.get_fundamentals = MagicMock(return_value=mock_f)
        analyzer._fundamentals = mock_fundamentals

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.iv_rank == 62.5
        assert metrics.iv_percentile == 74.0
        assert metrics.source == "fundamentals"


# =============================================================================
# TESTS: IVAnalyzer Edge Cases
# =============================================================================

class TestIVAnalyzerEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_no_sources_available(self):
        """No cache, no DB, no fundamentals → returns empty metrics."""
        iv_data_empty = IVData(
            symbol="UNKNOWN", current_iv=0.0,
            iv_rank=None, iv_percentile=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source=IVSource.UNKNOWN,
            updated_at="",
        )
        fetcher = _make_fetcher(iv_data_empty)
        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )
        analyzer._fundamentals = None

        metrics = await analyzer.get_iv_metrics("UNKNOWN")

        assert metrics.iv_rank is None
        assert metrics.iv_percentile is None
        assert metrics.source == "none"
        assert metrics.data_points == 0

    @pytest.mark.asyncio
    async def test_cache_exception_handled(self):
        """Cache throws exception → gracefully falls through."""
        fetcher = MagicMock()
        fetcher.get_iv_rank = MagicMock(side_effect=Exception("Cache corrupted"))
        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )
        # Explicitly disable fundamentals fallback
        analyzer._fundamentals = MagicMock()
        analyzer._fundamentals.get_fundamentals = MagicMock(return_value=None)

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.source == "none"
        assert metrics.iv_rank is None

    @pytest.mark.asyncio
    async def test_symbol_uppercase(self):
        """Symbol is always uppercased."""
        iv_data = _make_iv_data(symbol="AAPL")
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        metrics = await analyzer.get_iv_metrics("aapl")

        assert metrics.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_get_iv_metrics_many(self):
        """Batch processing returns dict of metrics."""
        iv_data = _make_iv_data()
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        results = await analyzer.get_iv_metrics_many(["AAPL", "MSFT"])

        assert "AAPL" in results
        assert "MSFT" in results
        assert results["AAPL"].iv_rank == 55.0

    @pytest.mark.asyncio
    async def test_current_iv_passed_to_fallback(self):
        """When current_iv provided, it's passed to fallback."""
        iv_data_empty = IVData(
            symbol="AAPL", current_iv=0.0,
            iv_rank=None, iv_percentile=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source=IVSource.UNKNOWN,
            updated_at="",
        )
        fetcher = _make_fetcher(iv_data_empty)
        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )

        metrics = await analyzer.get_iv_metrics("AAPL", current_iv=0.35)

        assert metrics.current_iv == 0.35
        assert metrics.current_iv_pct == 35.0


# =============================================================================
# TESTS: Singleton
# =============================================================================

class TestSingleton:
    """Test singleton pattern."""

    def test_get_iv_analyzer_returns_same_instance(self):
        a1 = get_iv_analyzer()
        a2 = get_iv_analyzer()
        assert a1 is a2

    def test_reset_clears_singleton(self):
        a1 = get_iv_analyzer()
        reset_iv_analyzer()
        a2 = get_iv_analyzer()
        assert a1 is not a2
