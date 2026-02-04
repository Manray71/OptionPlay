# Tests for Scan Handler
# =======================
"""
Tests for handlers/scan.py module including:
- ScanHandlerMixin class
- _execute_scan method
- _make_scan_cache_key method
- scan_with_strategy method
- scan_bounce method
- scan_ath_breakout method
- scan_earnings_dip method
- scan_multi_strategy method
- daily_picks method
- _format_daily_picks_output method
"""

import pytest
from datetime import datetime, date
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import dataclass
from typing import Optional, List, Any

from src.handlers.scan import ScanHandlerMixin
from src.scanner.multi_strategy_scanner import ScanMode


# =============================================================================
# FIXTURES
# =============================================================================

@dataclass
class MockSignal:
    """Mock signal for testing."""
    symbol: str
    score: float
    current_price: Optional[float]
    strategy: str
    reason: Optional[str] = None


@dataclass
class MockScanResult:
    """Mock scan result."""
    signals: List[MockSignal]
    symbols_with_signals: int


class MockScanner:
    """Mock scanner config."""
    auto_earnings_prefilter = True
    earnings_prefilter_min_days = 45


class MockPerformance:
    """Mock performance config."""
    historical_days = 90
    prefetch_batch_size = 20


class MockSettings:
    """Mock settings."""
    scanner = MockScanner()
    performance = MockPerformance()


class MockConfig:
    """Mock config object."""
    settings = MockSettings()


@dataclass
class MockStrikeRecommendation:
    """Mock strike recommendation."""
    short_strike: float = 180.0
    long_strike: float = 170.0
    spread_width: float = 10.0
    estimated_credit: Optional[float] = 1.50
    prob_profit: Optional[float] = 80.0
    liquidity_quality: Optional[str] = None
    short_oi: Optional[int] = None
    long_oi: Optional[int] = None
    short_spread_pct: Optional[float] = None
    long_spread_pct: Optional[float] = None
    expiry: Optional[str] = None
    dte: Optional[int] = None
    dte_warning: Optional[str] = None
    tradeable_status: str = "unknown"


@dataclass
class MockDailyPick:
    """Mock daily pick."""
    rank: int
    symbol: str
    score: float
    stability_score: Optional[float]
    strategy: str
    current_price: Optional[float]
    sector: Optional[str]
    reliability_grade: Optional[str]
    historical_win_rate: Optional[float] = None
    speed_score: float = 3.5
    suggested_strikes: Optional[MockStrikeRecommendation] = None
    reason: Optional[str] = None
    warnings: Optional[List[str]] = None
    spread_validation: Optional[Any] = None
    entry_quality: Optional[Any] = None
    ranking_score: Optional[float] = None


class MockVixRegime:
    """Mock VIX regime enum."""
    value = "normal"


@dataclass
class MockDailyRecommendationResult:
    """Mock daily recommendation result."""
    picks: List[MockDailyPick]
    vix_level: Optional[float]
    market_regime: MockVixRegime
    symbols_scanned: int
    signals_found: int
    after_stability_filter: int
    after_liquidity_filter: int = 0
    warnings: Optional[List[str]] = None


class MockScanHandler(ScanHandlerMixin):
    """Mock scan handler for testing."""

    def __init__(self):
        self._config = MockConfig()
        self._scan_cache = {}
        self._scan_cache_ttl = 1800  # 30 minutes
        self._scan_cache_hits = 0
        self._scan_cache_misses = 0
        self._earnings_fetcher = None

    async def _ensure_connected(self):
        pass

    async def _apply_earnings_prefilter(self, symbols, min_days, for_earnings_dip=False):
        # Return symbols unchanged with mock stats
        return symbols, 0, 0

    async def _fetch_historical_cached(self, symbol, days=90):
        return {"symbol": symbol, "prices": [100.0] * days}

    async def _get_vix_data(self):
        return {"current": 18.5}

    def _get_multi_scanner(self, **kwargs):
        scanner = MagicMock()
        scanner.config = MagicMock()
        scanner.config.max_total_results = 10
        scanner.set_earnings_date = MagicMock()
        return scanner


@pytest.fixture
def handler():
    """Create mock scan handler."""
    return MockScanHandler()


@pytest.fixture
def mock_signals():
    """Create mock signals."""
    return [
        MockSignal("AAPL", 8.5, 185.50, "pullback", "Strong support bounce"),
        MockSignal("MSFT", 7.5, 410.0, "pullback", "Oversold RSI"),
        MockSignal("GOOGL", 6.5, 175.0, "pullback", "Fib retracement"),
    ]


@pytest.fixture
def mock_scan_result(mock_signals):
    """Create mock scan result."""
    return MockScanResult(signals=mock_signals, symbols_with_signals=3)


# =============================================================================
# CACHE KEY TESTS
# =============================================================================

class TestMakeScanCacheKey:
    """Tests for _make_scan_cache_key method."""

    def test_make_cache_key_basic(self, handler):
        """Test basic cache key generation."""
        key = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["AAPL", "MSFT"],
            3.5,
            10
        )
        assert "scan:" in key
        assert "pullback" in key
        assert ":3.5:10" in key

    def test_make_cache_key_different_modes(self, handler):
        """Test different modes produce different keys."""
        key1 = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["AAPL"],
            3.5,
            10
        )
        key2 = handler._make_scan_cache_key(
            ScanMode.BOUNCE_ONLY,
            ["AAPL"],
            3.5,
            10
        )
        assert key1 != key2

    def test_make_cache_key_same_symbols_different_order(self, handler):
        """Test same symbols in different order produce same key."""
        key1 = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["AAPL", "MSFT", "GOOGL"],
            3.5,
            10
        )
        key2 = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["GOOGL", "AAPL", "MSFT"],
            3.5,
            10
        )
        # Should be same because symbols are sorted
        assert key1 == key2

    def test_make_cache_key_different_params(self, handler):
        """Test different parameters produce different keys."""
        base_key = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["AAPL"],
            3.5,
            10
        )

        # Different min_score
        key_score = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["AAPL"],
            5.0,
            10
        )
        assert base_key != key_score

        # Different max_results
        key_results = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["AAPL"],
            3.5,
            20
        )
        assert base_key != key_results


# =============================================================================
# EXECUTE SCAN TESTS
# =============================================================================

class TestExecuteScan:
    """Tests for _execute_scan method."""

    @pytest.mark.asyncio
    async def test_execute_scan_with_cache_hit(self, handler, mock_scan_result):
        """Test execute_scan returns cached result."""
        # Pre-populate cache
        cache_key = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["AAPL", "MSFT"],
            3.5,
            10
        )
        handler._scan_cache[cache_key] = (mock_scan_result, datetime.now())

        with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
            mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL", "MSFT"]
            mock_loader.return_value.stability_split_enabled = False

            result = await handler._execute_scan(
                mode=ScanMode.PULLBACK_ONLY,
                title="Test Scan",
                emoji="[TEST]",
                symbols=["AAPL", "MSFT"],
                max_results=10,
                min_score=3.5,
            )

        assert "[TEST]" in result
        assert "Test Scan" in result
        assert "AAPL" in result
        assert handler._scan_cache_hits == 1

    @pytest.mark.asyncio
    async def test_execute_scan_cache_miss(self, handler, mock_scan_result):
        """Test execute_scan on cache miss."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL", "MSFT"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler._execute_scan(
                        mode=ScanMode.PULLBACK_ONLY,
                        title="Test Scan",
                        emoji="[TEST]",
                        symbols=["AAPL", "MSFT"],
                        max_results=10,
                        min_score=3.5,
                    )

        assert handler._scan_cache_misses == 1
        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_execute_scan_no_results(self, handler):
        """Test execute_scan with no results."""
        empty_result = MockScanResult(signals=[], symbols_with_signals=0)
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=empty_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler._execute_scan(
                        mode=ScanMode.PULLBACK_ONLY,
                        title="Test Scan",
                        emoji="[TEST]",
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                        no_results_msg="Custom no results message",
                    )

        assert "Custom no results message" in result

    @pytest.mark.asyncio
    async def test_execute_scan_with_custom_formatter(self, handler, mock_scan_result):
        """Test execute_scan with custom row formatter."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        def custom_formatter(signal):
            return [signal.symbol, f"CUSTOM-{signal.score}"]

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler._execute_scan(
                        mode=ScanMode.PULLBACK_ONLY,
                        title="Test Scan",
                        emoji="[TEST]",
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                        table_columns=["Symbol", "Custom"],
                        row_formatter=custom_formatter,
                    )

        assert "CUSTOM-8.5" in result

    @pytest.mark.asyncio
    async def test_execute_scan_with_stability_split(self, handler, mock_scan_result):
        """Test execute_scan shows list type when stability split enabled."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = True

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler._execute_scan(
                        mode=ScanMode.PULLBACK_ONLY,
                        title="Test Scan",
                        emoji="[TEST]",
                        symbols=None,  # Use default list
                        max_results=10,
                        min_score=3.5,
                        list_type="stable",
                    )

        assert "Stable List" in result


# =============================================================================
# SCAN METHOD TESTS
# =============================================================================

class TestScanWithStrategy:
    """Tests for scan_with_strategy method."""

    @pytest.mark.asyncio
    async def test_scan_with_strategy(self, handler, mock_scan_result):
        """Test scan_with_strategy."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_with_strategy(
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                    )

        assert "[PULLBACK]" in result
        assert "Pullback Candidates" in result


class TestScanBounce:
    """Tests for scan_bounce method."""

    @pytest.mark.asyncio
    async def test_scan_bounce(self, handler, mock_scan_result):
        """Test scan_bounce."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_bounce(
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                    )

        assert "[BOUNCE]" in result
        assert "Support Bounce Candidates" in result


class TestScanAthBreakout:
    """Tests for scan_ath_breakout method."""

    @pytest.mark.asyncio
    async def test_scan_ath_breakout(self, handler, mock_scan_result):
        """Test scan_ath_breakout."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_ath_breakout(
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                    )

        assert "[BREAKOUT]" in result
        assert "ATH Breakout Candidates" in result


class TestScanEarningsDip:
    """Tests for scan_earnings_dip method."""

    @pytest.mark.asyncio
    async def test_scan_earnings_dip(self, handler, mock_scan_result):
        """Test scan_earnings_dip."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_earnings_dip(
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                    )

        assert "[EARN_DIP]" in result
        assert "Earnings Dip Candidates" in result


class TestScanMultiStrategy:
    """Tests for scan_multi_strategy method."""

    @pytest.mark.asyncio
    async def test_scan_multi_strategy(self, handler, mock_scan_result):
        """Test scan_multi_strategy."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_multi_strategy(
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                    )

        assert "[MULTI]" in result
        assert "Multi-Strategy Scan" in result

    @pytest.mark.asyncio
    async def test_scan_multi_strategy_risk_list(self, handler, mock_scan_result):
        """Test scan_multi_strategy with risk list."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["TSLA"]
                mock_loader.return_value.stability_split_enabled = True

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_multi_strategy(
                        symbols=None,
                        max_results=10,
                        min_score=3.5,
                        list_type="risk",
                    )

        assert "Risk List" in result


# =============================================================================
# DAILY PICKS TESTS
# =============================================================================

class TestDailyPicks:
    """Tests for daily_picks method."""

    @pytest.mark.asyncio
    async def test_daily_picks_basic(self, handler):
        """Test daily_picks basic functionality."""
        mock_pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
        )

        mock_result = MockDailyRecommendationResult(
            picks=[mock_pick],
            vix_level=18.5,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        mock_engine = MagicMock()
        mock_engine.get_daily_picks = AsyncMock(return_value=mock_result)
        mock_engine.set_vix = MagicMock()

        with patch('src.handlers.scan.DailyRecommendationEngine', return_value=mock_engine):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]

                result = await handler.daily_picks(
                    symbols=["AAPL"],
                    max_picks=20,
                    min_score=5.0,
                )

        assert "Daily Picks" in result
        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_daily_picks_with_strikes(self, handler):
        """Test daily_picks with strike recommendations."""
        mock_strikes = MockStrikeRecommendation()
        mock_pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
            suggested_strikes=mock_strikes,
        )

        mock_result = MockDailyRecommendationResult(
            picks=[mock_pick],
            vix_level=18.5,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        mock_engine = MagicMock()
        mock_engine.get_daily_picks = AsyncMock(return_value=mock_result)
        mock_engine.set_vix = MagicMock()

        with patch('src.handlers.scan.DailyRecommendationEngine', return_value=mock_engine):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]

                result = await handler.daily_picks(
                    symbols=["AAPL"],
                    max_picks=20,
                    min_score=5.0,
                    include_strikes=True,
                )

        assert "Short $180" in result  # v2 format for strike recommendations
        assert "Long $170" in result


# =============================================================================
# FORMAT OUTPUT TESTS
# =============================================================================

class TestFormatDailyPicksOutput:
    """Tests for _format_daily_picks_output method."""

    def test_format_empty_picks(self, handler):
        """Test formatting with no picks."""
        result = MockDailyRecommendationResult(
            picks=[],
            vix_level=18.5,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=0,
            after_stability_filter=0,
        )

        output = handler._format_daily_picks_output(result, 5.0)

        assert "No candidates found" in output

    def test_format_with_warnings(self, handler):
        """Test formatting with warnings."""
        mock_pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
        )

        result = MockDailyRecommendationResult(
            picks=[mock_pick],
            vix_level=25.0,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
            warnings=["High VIX environment - reduce position sizes"],
        )

        output = handler._format_daily_picks_output(result, 5.0)

        assert "High VIX" in output

    def test_format_different_regimes(self, handler):
        """Test formatting with different VIX regimes."""
        mock_pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
        )

        # Test low vol regime
        class LowVolRegime:
            value = "low_vol"

        result = MockDailyRecommendationResult(
            picks=[mock_pick],
            vix_level=12.0,
            market_regime=LowVolRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        output = handler._format_daily_picks_output(result, 5.0)

        assert "Normal" in output  # low_vol maps to "Normal" in v2 format

    def test_format_multiple_strategies(self, handler):
        """Test formatting with multiple strategies."""
        picks = [
            MockDailyPick(
                rank=1, symbol="AAPL", score=8.5, stability_score=85.0,
                strategy="pullback", current_price=185.50, sector="Technology",
                reliability_grade="A"
            ),
            MockDailyPick(
                rank=2, symbol="JPM", score=7.5, stability_score=80.0,
                strategy="bounce", current_price=200.0, sector="Financials",
                reliability_grade="B"
            ),
            MockDailyPick(
                rank=3, symbol="NVDA", score=7.0, stability_score=75.0,
                strategy="ath_breakout", current_price=500.0, sector="Technology",
                reliability_grade="B"
            ),
        ]

        result = MockDailyRecommendationResult(
            picks=picks,
            vix_level=18.5,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        output = handler._format_daily_picks_output(result, 5.0)

        assert "Pullback" in output
        assert "Bounce" in output
        assert "ATH Breakout" in output

    def test_format_pick_with_all_details(self, handler):
        """Test formatting pick with all details."""
        mock_strikes = MockStrikeRecommendation()
        mock_pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
            historical_win_rate=92.0,
            suggested_strikes=mock_strikes,
            reason="Strong support bounce with RSI oversold",
            warnings=["Near sector concentration limit"],
        )

        result = MockDailyRecommendationResult(
            picks=[mock_pick],
            vix_level=18.5,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        output = handler._format_daily_picks_output(result, 5.0)

        assert "AAPL" in output
        assert "Technology" in output
        assert "Strong support bounce" in output


class TestFormatSinglePickDetail:
    """Tests for _format_single_pick_detail method."""

    def test_format_basic_pick(self, handler):
        """Test formatting basic pick detail."""
        from src.utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
        )

        handler._format_single_pick_detail(b, pick)
        output = b.build()

        assert "AAPL" in output
        assert "Pullback" in output
        assert "Stab(85)" in output  # Stability check in v2 format
        assert "8.5" in output

    def test_format_pick_with_strikes(self, handler):
        """Test formatting pick with strike recommendations."""
        from src.utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        mock_strikes = MockStrikeRecommendation()
        pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
            suggested_strikes=mock_strikes,
        )

        handler._format_single_pick_detail(b, pick)
        output = b.build()

        assert "Short $180" in output  # v2 format: "Strikes: Short $180 / Long $170"
        assert "Long $170" in output
        assert "Width $10" in output

    def test_format_pick_with_warnings(self, handler):
        """Test formatting pick with warnings."""
        from src.utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
            warnings=["Near earnings", "High IV"],
        )

        handler._format_single_pick_detail(b, pick)
        output = b.build()

        assert "Warning: Near earnings" in output  # v2 format uses "Warning:" prefix
        assert "Warning: High IV" in output


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_scan_with_empty_symbols(self, handler, mock_scan_result):
        """Test scan with empty symbols list uses watchlist."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL", "MSFT"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler._execute_scan(
                        mode=ScanMode.PULLBACK_ONLY,
                        title="Test Scan",
                        emoji="[TEST]",
                        symbols=None,  # Empty - should use watchlist
                        max_results=10,
                        min_score=3.5,
                    )

        mock_loader.return_value.get_symbols_by_list_type.assert_called_once()

    def test_format_pick_no_price(self, handler):
        """Test formatting pick without price."""
        from src.utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        pick = MockDailyPick(
            rank=1,
            symbol="TEST",
            score=5.0,
            stability_score=None,
            strategy="pullback",
            current_price=None,  # No price
            sector=None,
            reliability_grade=None,
        )

        handler._format_single_pick_detail(b, pick)
        output = b.build()

        assert "TEST" in output  # v2 format: symbol present, no crash
        assert "Pullback" in output  # Strategy still shown


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
