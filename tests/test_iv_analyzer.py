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

    def test_singleton_accepts_custom_params(self):
        """First call sets parameters, second call ignores them."""
        fetcher = _make_fetcher()
        a1 = get_iv_analyzer(iv_fetcher=fetcher)
        a2 = get_iv_analyzer()  # ignores default params
        assert a1 is a2
        assert a1._fetcher is fetcher


# =============================================================================
# TESTS: IVMetrics Boundary Values
# =============================================================================

class TestIVMetricsBoundary:
    """Test IVMetrics boundary values for iv_status."""

    @pytest.mark.parametrize("iv_rank,expected_status", [
        (0.0, "low"),
        (29.9, "low"),
        (30.0, "normal"),
        (49.9, "normal"),
        (50.0, "elevated"),
        (69.9, "elevated"),
        (70.0, "very_high"),
        (100.0, "very_high"),
    ])
    def test_iv_status_boundaries(self, iv_rank, expected_status):
        """Test exact boundary values for iv_status classification."""
        m = IVMetrics(
            symbol="TEST", iv_rank=iv_rank, iv_percentile=None,
            current_iv=None, current_iv_pct=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source="cache",
        )
        assert m.iv_status == expected_status

    @pytest.mark.parametrize("iv_rank,expected", [
        (49.9, False),
        (50.0, True),
        (50.1, True),
    ])
    def test_is_elevated_boundary(self, iv_rank, expected):
        """Test exact boundary for is_elevated (50.0 threshold)."""
        m = IVMetrics(
            symbol="TEST", iv_rank=iv_rank, iv_percentile=None,
            current_iv=None, current_iv_pct=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source="cache",
        )
        assert m.is_elevated is expected


# =============================================================================
# TESTS: IVAnalyzer Cache Details
# =============================================================================

class TestIVAnalyzerCacheDetails:
    """Test detailed cache behavior: rounding, field transfer."""

    @pytest.mark.asyncio
    async def test_cache_rounds_iv_rank(self):
        """IV rank is rounded to 1 decimal place."""
        iv_data = _make_iv_data(iv_rank=55.456, iv_percentile=68.789)
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.iv_rank == 55.5  # rounded to 1 decimal
        assert metrics.iv_percentile == 68.8

    @pytest.mark.asyncio
    async def test_cache_transfers_high_low(self):
        """iv_high_52w and iv_low_52w are transferred from cache."""
        iv_data = _make_iv_data()
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.iv_high_52w == 0.45
        assert metrics.iv_low_52w == 0.18

    @pytest.mark.asyncio
    async def test_cache_current_iv_pct_computed(self):
        """current_iv_pct is computed from current_iv * 100."""
        iv_data = _make_iv_data(current_iv=0.3456)
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.current_iv == 0.3456
        assert metrics.current_iv_pct == 34.6  # rounded to 1 decimal

    @pytest.mark.asyncio
    async def test_cache_none_iv_percentile_stays_none(self):
        """If cache has None iv_percentile, result stays None."""
        iv_data = IVData(
            symbol="AAPL", current_iv=0.28,
            iv_rank=55.0, iv_percentile=None,
            iv_high_52w=0.45, iv_low_52w=0.18,
            data_points=200, source=IVSource.TRADIER,
            updated_at="2026-02-04T12:00:00",
        )
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.iv_rank == 55.0
        assert metrics.iv_percentile is None
        assert metrics.source == "cache"

    @pytest.mark.asyncio
    async def test_cache_zero_current_iv_pct_is_none(self):
        """current_iv=0.0 produces current_iv_pct=None (falsy check)."""
        iv_data = IVData(
            symbol="AAPL", current_iv=0.0,
            iv_rank=55.0, iv_percentile=68.0,
            iv_high_52w=0.45, iv_low_52w=0.18,
            data_points=200, source=IVSource.TRADIER,
            updated_at="2026-02-04T12:00:00",
        )
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.current_iv_pct is None

    @pytest.mark.asyncio
    async def test_cache_exactly_20_data_points_accepted(self):
        """Exactly 20 data points is accepted (>= 20)."""
        iv_data = _make_iv_data(data_points=20)
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.source == "cache"
        assert metrics.data_points == 20

    @pytest.mark.asyncio
    async def test_cache_19_data_points_rejected(self):
        """19 data points is rejected (< 20)."""
        iv_data = _make_iv_data(data_points=19)
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )
        # Use a mock that returns None to prevent lazy-load fallback
        mock_fundamentals = MagicMock()
        mock_fundamentals.get_fundamentals = MagicMock(return_value=None)
        analyzer._fundamentals = mock_fundamentals

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.source == "none"

    @pytest.mark.asyncio
    async def test_fetcher_called_with_current_iv_or_zero(self):
        """Fetcher receives current_iv or 0.0 as default."""
        fetcher = _make_fetcher(_make_iv_data())
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        # With current_iv
        await analyzer.get_iv_metrics("AAPL", current_iv=0.35)
        fetcher.get_iv_rank.assert_called_with("AAPL", 0.35)

        # Without current_iv → 0.0
        fetcher.get_iv_rank.reset_mock()
        fetcher.get_iv_rank.return_value = _make_iv_data()
        await analyzer.get_iv_metrics("AAPL")
        fetcher.get_iv_rank.assert_called_with("AAPL", 0.0)


# =============================================================================
# TESTS: IVAnalyzer Local DB
# =============================================================================

class TestIVAnalyzerLocalDB:
    """Test IVAnalyzer local database path."""

    @pytest.mark.asyncio
    async def test_db_path_not_exists_skips(self):
        """If DB path doesn't exist, _try_local_db returns None."""
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
        analyzer._fundamentals = None

        result = await analyzer._try_local_db("AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_db_insufficient_rows_returns_none(self):
        """DB returns < 30 rows → returns None."""
        iv_data_empty = IVData(
            symbol="AAPL", current_iv=0.0,
            iv_rank=None, iv_percentile=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source=IVSource.UNKNOWN,
            updated_at="",
        )
        fetcher = _make_fetcher(iv_data_empty)

        db_path = MagicMock(spec=Path)
        db_path.exists = MagicMock(return_value=True)
        analyzer = IVAnalyzer(iv_fetcher=fetcher, db_path=db_path)

        # Return only 10 rows (< 30)
        rows = [(0.25 + i * 0.001, f"2026-01-{i+1:02d}") for i in range(10)]

        with patch.object(analyzer, '_query_iv_from_db', return_value=rows):
            with patch('src.services.iv_analyzer.asyncio.to_thread',
                       new_callable=AsyncMock, return_value=rows):
                result = await analyzer._try_local_db("AAPL")

        assert result is None

    @pytest.mark.asyncio
    async def test_db_sufficient_rows_returns_metrics(self):
        """DB returns >= 30 daily IVs → returns IVMetrics with source=db."""
        db_path = MagicMock(spec=Path)
        db_path.exists = MagicMock(return_value=True)

        fetcher = _make_fetcher()
        analyzer = IVAnalyzer(iv_fetcher=fetcher, db_path=db_path)

        # Create 50 unique days of IV data
        rows = [(0.20 + i * 0.005, f"2025-{(i // 28) + 10:02d}-{(i % 28) + 1:02d}")
                for i in range(50)]

        with patch('src.services.iv_analyzer.asyncio.to_thread',
                   new_callable=AsyncMock, return_value=rows):
            result = await analyzer._try_local_db("AAPL")

        assert result is not None
        assert result.source == "db"
        assert result.data_points == 50
        assert result.iv_rank is not None
        assert result.current_iv is not None
        assert result.iv_high_52w is not None
        assert result.iv_low_52w is not None

    @pytest.mark.asyncio
    async def test_db_daily_averaging(self):
        """Multiple rows per day are averaged."""
        db_path = MagicMock(spec=Path)
        db_path.exists = MagicMock(return_value=True)

        fetcher = _make_fetcher()
        analyzer = IVAnalyzer(iv_fetcher=fetcher, db_path=db_path)

        # 30 days, 3 rows per day (different strikes)
        rows = []
        for day in range(30):
            date = f"2025-12-{day + 1:02d}"
            base_iv = 0.20 + day * 0.005
            rows.append((base_iv, date))
            rows.append((base_iv + 0.01, date))
            rows.append((base_iv - 0.01, date))

        with patch('src.services.iv_analyzer.asyncio.to_thread',
                   new_callable=AsyncMock, return_value=rows):
            result = await analyzer._try_local_db("AAPL")

        assert result is not None
        assert result.data_points == 30  # 30 days, not 90 rows

    @pytest.mark.asyncio
    async def test_db_exception_returns_none(self):
        """DB query exception → returns None gracefully."""
        db_path = MagicMock(spec=Path)
        db_path.exists = MagicMock(return_value=True)

        fetcher = _make_fetcher()
        analyzer = IVAnalyzer(iv_fetcher=fetcher, db_path=db_path)

        with patch('src.services.iv_analyzer.asyncio.to_thread',
                   new_callable=AsyncMock, side_effect=Exception("DB error")):
            result = await analyzer._try_local_db("AAPL")

        assert result is None

    @pytest.mark.asyncio
    async def test_db_empty_rows_returns_none(self):
        """DB returns empty list → returns None."""
        db_path = MagicMock(spec=Path)
        db_path.exists = MagicMock(return_value=True)

        fetcher = _make_fetcher()
        analyzer = IVAnalyzer(iv_fetcher=fetcher, db_path=db_path)

        with patch('src.services.iv_analyzer.asyncio.to_thread',
                   new_callable=AsyncMock, return_value=[]):
            result = await analyzer._try_local_db("AAPL")

        assert result is None

    @pytest.mark.asyncio
    async def test_db_rounding(self):
        """DB results are properly rounded."""
        db_path = MagicMock(spec=Path)
        db_path.exists = MagicMock(return_value=True)

        fetcher = _make_fetcher()
        analyzer = IVAnalyzer(iv_fetcher=fetcher, db_path=db_path)

        # 30 days of data with precise values
        rows = [(0.234567, f"2025-12-{i + 1:02d}") for i in range(30)]

        with patch('src.services.iv_analyzer.asyncio.to_thread',
                   new_callable=AsyncMock, return_value=rows):
            result = await analyzer._try_local_db("AAPL")

        assert result is not None
        # current_iv rounded to 4 decimals
        assert result.current_iv == round(0.234567, 4)
        # current_iv_pct rounded to 1 decimal
        assert result.current_iv_pct == round(0.234567 * 100, 1)


# =============================================================================
# TESTS: IVAnalyzer Fundamentals Details
# =============================================================================

class TestIVAnalyzerFundamentalsDetails:
    """Test fundamentals fallback edge cases."""

    @pytest.mark.asyncio
    async def test_fundamentals_with_current_iv(self):
        """Fundamentals includes current_iv when provided."""
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

        mock_fundamentals = MagicMock()
        mock_f = MagicMock()
        mock_f.iv_rank_252d = 45.0
        mock_f.iv_percentile_252d = 52.0
        mock_fundamentals.get_fundamentals = MagicMock(return_value=mock_f)
        analyzer._fundamentals = mock_fundamentals

        metrics = await analyzer.get_iv_metrics("AAPL", current_iv=0.30)

        assert metrics.current_iv == 0.30
        assert metrics.current_iv_pct == 30.0
        assert metrics.source == "fundamentals"

    @pytest.mark.asyncio
    async def test_fundamentals_no_iv_rank_returns_none(self):
        """If fundamentals has no iv_rank_252d, returns None."""
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

        mock_fundamentals = MagicMock()
        mock_f = MagicMock()
        mock_f.iv_rank_252d = None
        mock_f.iv_percentile_252d = None
        mock_fundamentals.get_fundamentals = MagicMock(return_value=mock_f)
        analyzer._fundamentals = mock_fundamentals

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.source == "none"

    @pytest.mark.asyncio
    async def test_fundamentals_exception_handled(self):
        """Fundamentals exception → falls through to none."""
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

        mock_fundamentals = MagicMock()
        mock_fundamentals.get_fundamentals = MagicMock(
            side_effect=Exception("DB connection failed")
        )
        analyzer._fundamentals = mock_fundamentals

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.source == "none"

    @pytest.mark.asyncio
    async def test_fundamentals_none_iv_percentile(self):
        """Fundamentals with iv_rank but no percentile."""
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

        mock_fundamentals = MagicMock()
        mock_f = MagicMock()
        mock_f.iv_rank_252d = 55.0
        mock_f.iv_percentile_252d = None
        mock_fundamentals.get_fundamentals = MagicMock(return_value=mock_f)
        analyzer._fundamentals = mock_fundamentals

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.iv_rank == 55.0
        assert metrics.iv_percentile is None
        assert metrics.source == "fundamentals"

    def test_fundamentals_lazy_load_exception(self):
        """Fundamentals manager init failure handled gracefully."""
        analyzer = IVAnalyzer(
            iv_fetcher=_make_fetcher(),
            db_path=Path("/nonexistent/path/trades.db"),
        )

        with patch(
            'src.services.iv_analyzer.get_fundamentals_manager',
            side_effect=Exception("No DB"),
        ):
            result = analyzer.fundamentals

        assert result is None


# =============================================================================
# TESTS: IVAnalyzer Lazy Properties
# =============================================================================

class TestIVAnalyzerLazyProperties:
    """Test lazy-loading behavior of fetcher and fundamentals."""

    def test_fetcher_lazy_load(self):
        """Fetcher is lazy-loaded from global singleton."""
        analyzer = IVAnalyzer()

        mock_fetcher = MagicMock()
        with patch(
            'src.services.iv_analyzer.get_iv_fetcher',
            return_value=mock_fetcher,
        ):
            f = analyzer.fetcher

        assert f is mock_fetcher

    def test_fetcher_cached_after_first_access(self):
        """Fetcher is created once and cached."""
        mock_fetcher = MagicMock()
        analyzer = IVAnalyzer(iv_fetcher=mock_fetcher)

        assert analyzer.fetcher is mock_fetcher
        assert analyzer.fetcher is mock_fetcher  # same reference

    def test_default_db_path(self):
        """Default DB path is ~/.optionplay/trades.db."""
        analyzer = IVAnalyzer(iv_fetcher=_make_fetcher())

        assert analyzer._db_path == Path.home() / ".optionplay" / "trades.db"

    def test_custom_db_path(self):
        """Custom DB path is used."""
        custom = Path("/tmp/custom.db")
        analyzer = IVAnalyzer(iv_fetcher=_make_fetcher(), db_path=custom)

        assert analyzer._db_path == custom


# =============================================================================
# TESTS: IVAnalyzer Source Priority
# =============================================================================

class TestIVAnalyzerSourcePriority:
    """Test that sources are tried in correct order."""

    @pytest.mark.asyncio
    async def test_cache_takes_priority_over_db(self):
        """When cache has valid data, DB is not queried."""
        iv_data = _make_iv_data(iv_rank=55.0)
        fetcher = _make_fetcher(iv_data)

        db_path = MagicMock(spec=Path)
        db_path.exists = MagicMock(return_value=True)

        analyzer = IVAnalyzer(iv_fetcher=fetcher, db_path=db_path)

        metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.source == "cache"
        # DB path.exists should not be called when cache succeeds
        db_path.exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_takes_priority_over_fundamentals(self):
        """When cache fails but DB works, fundamentals is not queried."""
        iv_data_empty = IVData(
            symbol="AAPL", current_iv=0.0,
            iv_rank=None, iv_percentile=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source=IVSource.UNKNOWN,
            updated_at="",
        )
        fetcher = _make_fetcher(iv_data_empty)

        db_path = MagicMock(spec=Path)
        db_path.exists = MagicMock(return_value=True)

        analyzer = IVAnalyzer(iv_fetcher=fetcher, db_path=db_path)

        # Mock DB to return valid data
        rows = [(0.25 + i * 0.002, f"2025-12-{i + 1:02d}") for i in range(30)]

        mock_fundamentals = MagicMock()
        analyzer._fundamentals = mock_fundamentals

        with patch('src.services.iv_analyzer.asyncio.to_thread',
                   new_callable=AsyncMock, return_value=rows):
            metrics = await analyzer.get_iv_metrics("AAPL")

        assert metrics.source == "db"
        # Fundamentals should not be queried
        mock_fundamentals.get_fundamentals.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_chain_cache_fail_db_fail_fundamentals_success(self):
        """Full fallback: cache fails → DB fails → fundamentals succeeds."""
        # Cache: no data
        iv_data_empty = IVData(
            symbol="TSLA", current_iv=0.0,
            iv_rank=None, iv_percentile=None,
            iv_high_52w=None, iv_low_52w=None,
            data_points=0, source=IVSource.UNKNOWN,
            updated_at="",
        )
        fetcher = _make_fetcher(iv_data_empty)

        # DB: doesn't exist
        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )

        # Fundamentals: has data
        mock_fundamentals = MagicMock()
        mock_f = MagicMock()
        mock_f.iv_rank_252d = 72.3
        mock_f.iv_percentile_252d = 80.0
        mock_fundamentals.get_fundamentals = MagicMock(return_value=mock_f)
        analyzer._fundamentals = mock_fundamentals

        metrics = await analyzer.get_iv_metrics("TSLA")

        assert metrics.source == "fundamentals"
        assert metrics.iv_rank == 72.3
        assert metrics.symbol == "TSLA"


# =============================================================================
# TESTS: get_iv_metrics_many
# =============================================================================

class TestGetIVMetricsMany:
    """Test batch processing."""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Empty symbol list returns empty dict."""
        analyzer = IVAnalyzer(iv_fetcher=_make_fetcher())

        results = await analyzer.get_iv_metrics_many([])

        assert results == {}

    @pytest.mark.asyncio
    async def test_uppercases_symbols(self):
        """Symbols are uppercased in result keys."""
        iv_data = _make_iv_data()
        fetcher = _make_fetcher(iv_data)
        analyzer = IVAnalyzer(iv_fetcher=fetcher)

        results = await analyzer.get_iv_metrics_many(["aapl", "msft"])

        assert "AAPL" in results
        assert "MSFT" in results
        assert "aapl" not in results

    @pytest.mark.asyncio
    async def test_mixed_success_failure(self):
        """Some symbols succeed, some fail — all returned."""
        fetcher = MagicMock()

        # AAPL succeeds, FAKE fails
        def side_effect(symbol, current_iv):
            if symbol == "AAPL":
                return _make_iv_data(symbol="AAPL", iv_rank=55.0)
            return IVData(
                symbol=symbol, current_iv=0.0,
                iv_rank=None, iv_percentile=None,
                iv_high_52w=None, iv_low_52w=None,
                data_points=0, source=IVSource.UNKNOWN,
                updated_at="",
            )

        fetcher.get_iv_rank = MagicMock(side_effect=side_effect)

        analyzer = IVAnalyzer(
            iv_fetcher=fetcher,
            db_path=Path("/nonexistent/path/trades.db"),
        )
        analyzer._fundamentals = None

        results = await analyzer.get_iv_metrics_many(["AAPL", "FAKE"])

        assert results["AAPL"].source == "cache"
        assert results["AAPL"].iv_rank == 55.0
        assert results["FAKE"].source == "none"
        assert results["FAKE"].iv_rank is None
