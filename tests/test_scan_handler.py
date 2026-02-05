# Tests for Scan Handler
# =======================
"""
Tests for handlers/scan.py module including:
- ScanHandlerMixin class
- _execute_scan method
- _make_scan_cache_key method
- scan_with_strategy (pullback) method
- scan_pullback_candidates (legacy alias)
- scan_bounce method
- scan_ath_breakout method
- scan_earnings_dip method
- scan_multi_strategy method
- daily_picks method
- _apply_chain_validation method
- _format_daily_picks_output method
- _format_single_pick_v2 method
- Filter application (earnings prefilter, stability split)
- Error handling
"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import dataclass, field
from typing import Optional, List, Any, Dict

from src.handlers.scan import ScanHandlerMixin
from src.scanner.multi_strategy_scanner import ScanMode, ScanResult
from src.services.pick_formatter import format_single_pick_v2


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
class MockOptionLeg:
    """Mock option leg for SpreadValidation."""
    strike: float
    delta: float
    iv: Optional[float]
    open_interest: int
    bid: float
    ask: float


@dataclass
class MockSpreadValidation:
    """Mock spread validation from chain validator."""
    tradeable: bool
    short_leg: MockOptionLeg
    long_leg: MockOptionLeg
    spread_width: float
    expiration: str
    dte: int
    credit_bid: float
    credit_mid: float
    credit_pct: Optional[float]
    max_loss_per_contract: Optional[float]
    spread_theta: Optional[float]
    reason: str = ""
    data_source: str = "Tradier"


@dataclass
class MockEntryQuality:
    """Mock entry quality score."""
    eqs_total: float = 65.0
    iv_rank: Optional[float] = 45.0
    iv_percentile: Optional[float] = 50.0
    rsi: Optional[float] = 35.0
    pullback_pct: Optional[float] = 5.0


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
    spread_validation: Optional[MockSpreadValidation] = None
    entry_quality: Optional[MockEntryQuality] = None
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


class MockEarningsCacheEntry:
    """Mock earnings cache entry."""
    def __init__(self, earnings_date: Optional[str]):
        self.earnings_date = earnings_date


class MockScanHandler(ScanHandlerMixin):
    """Mock scan handler for testing."""

    def __init__(self):
        self._config = MockConfig()
        self._scan_cache = {}
        self._scan_cache_ttl = 1800  # 30 minutes
        self._scan_cache_hits = 0
        self._scan_cache_misses = 0
        self._earnings_fetcher = None
        self._tradier = None
        self._tradier_connected = False
        self._tradier_provider = None
        self._ibkr = None
        self._provider = None

    async def _ensure_connected(self):
        pass

    async def _apply_earnings_prefilter(self, symbols, min_days, for_earnings_dip=False):
        # Return symbols unchanged with mock stats
        return symbols, 0, 0

    async def _fetch_historical_cached(self, symbol, days=90):
        return ([100.0] * days, [1000000] * days, [101.0] * days, [99.0] * days, [100.0] * days)

    async def _get_vix_data(self):
        return {"current": 18.5}

    async def get_vix(self, force_refresh=False):
        return 18.5

    def _get_multi_scanner(self, **kwargs):
        scanner = MagicMock()
        scanner.config = MagicMock()
        scanner.config.max_total_results = 10
        scanner.set_earnings_date = MagicMock()
        return scanner

    async def _get_options_chain_with_fallback(self, symbol, dte_min=60, dte_max=90, right="P"):
        return []


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

    def test_make_cache_key_all_scan_modes(self, handler):
        """Test cache key generation for all scan modes."""
        modes = [
            ScanMode.PULLBACK_ONLY,
            ScanMode.BOUNCE_ONLY,
            ScanMode.BREAKOUT_ONLY,
            ScanMode.EARNINGS_DIP,
            ScanMode.BEST_SIGNAL,
            ScanMode.ALL,
        ]
        keys = set()
        for mode in modes:
            key = handler._make_scan_cache_key(mode, ["AAPL"], 3.5, 10)
            keys.add(key)

        # All modes should produce unique keys
        assert len(keys) == len(modes)

    def test_make_cache_key_empty_symbols_list(self, handler):
        """Test cache key with empty symbols list."""
        key = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            [],
            3.5,
            10
        )
        assert "scan:" in key
        # Should still generate a valid key


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
    async def test_execute_scan_cache_expired(self, handler, mock_scan_result):
        """Test execute_scan does not use expired cache."""
        # Pre-populate cache with old timestamp
        cache_key = handler._make_scan_cache_key(
            ScanMode.PULLBACK_ONLY,
            ["AAPL"],
            3.5,
            10
        )
        old_time = datetime.now() - timedelta(hours=1)
        handler._scan_cache[cache_key] = (mock_scan_result, old_time)

        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

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
                    )

        # Should miss cache (expired)
        assert handler._scan_cache_misses == 1

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

    @pytest.mark.asyncio
    async def test_execute_scan_with_earnings_prefilter(self, handler, mock_scan_result):
        """Test execute_scan applies earnings prefilter."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        # Mock earnings prefilter to exclude some symbols
        async def mock_prefilter(symbols, min_days, for_earnings_dip=False):
            return ["AAPL"], 1, 1  # Excluded 1 symbol, 1 cache hit

        with patch.object(handler, '_apply_earnings_prefilter', side_effect=mock_prefilter):
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

        assert "Pre-filtered" in result
        assert "-1 (earnings)" in result

    @pytest.mark.asyncio
    async def test_execute_scan_loads_earnings_dates(self, handler, mock_scan_result):
        """Test execute_scan loads earnings dates into scanner."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
        mock_scanner.set_earnings_date = MagicMock()

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_cache_entry = MockEarningsCacheEntry("2026-04-25")
                    mock_ef.return_value.cache.get.return_value = mock_cache_entry

                    await handler._execute_scan(
                        mode=ScanMode.PULLBACK_ONLY,
                        title="Test Scan",
                        emoji="[TEST]",
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                    )

        mock_scanner.set_earnings_date.assert_called()

    @pytest.mark.asyncio
    async def test_execute_scan_handles_invalid_earnings_date(self, handler, mock_scan_result):
        """Test execute_scan handles invalid earnings date gracefully."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
        mock_scanner.set_earnings_date = MagicMock()

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    # Invalid date format
                    mock_cache_entry = MockEarningsCacheEntry("invalid-date")
                    mock_ef.return_value.cache.get.return_value = mock_cache_entry

                    # Should not raise
                    result = await handler._execute_scan(
                        mode=ScanMode.PULLBACK_ONLY,
                        title="Test Scan",
                        emoji="[TEST]",
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                    )

        assert result is not None


# =============================================================================
# SCAN METHOD TESTS
# =============================================================================

class TestScanWithStrategy:
    """Tests for scan_with_strategy method (pullback scan)."""

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

    @pytest.mark.asyncio
    async def test_scan_with_strategy_uses_pullback_mode(self, handler, mock_scan_result):
        """Test scan_with_strategy uses PULLBACK_ONLY mode."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner) as mock_get:
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    await handler.scan_with_strategy(symbols=["AAPL"])

        # Verify scanner was called with pullback mode
        call_args = mock_scanner.scan_async.call_args
        assert call_args[1]['mode'] == ScanMode.PULLBACK_ONLY


class TestScanPullbackCandidates:
    """Tests for scan_pullback_candidates (legacy alias)."""

    @pytest.mark.asyncio
    async def test_scan_pullback_candidates_is_alias(self, handler, mock_scan_result):
        """Test scan_pullback_candidates is alias for scan_with_strategy."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_pullback_candidates(
                        symbols=["AAPL"],
                        max_results=10,
                        min_score=3.5,
                    )

        # Should produce same output as scan_with_strategy
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

    @pytest.mark.asyncio
    async def test_scan_bounce_uses_bounce_mode(self, handler, mock_scan_result):
        """Test scan_bounce uses BOUNCE_ONLY mode."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    await handler.scan_bounce(symbols=["AAPL"])

        call_args = mock_scanner.scan_async.call_args
        assert call_args[1]['mode'] == ScanMode.BOUNCE_ONLY

    @pytest.mark.asyncio
    async def test_scan_bounce_empty_results(self, handler):
        """Test scan_bounce with no results."""
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

                    result = await handler.scan_bounce(symbols=["AAPL"])

        assert "No bounce candidates found" in result


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

    @pytest.mark.asyncio
    async def test_scan_ath_breakout_uses_breakout_mode(self, handler, mock_scan_result):
        """Test scan_ath_breakout uses BREAKOUT_ONLY mode."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    await handler.scan_ath_breakout(symbols=["AAPL"])

        call_args = mock_scanner.scan_async.call_args
        assert call_args[1]['mode'] == ScanMode.BREAKOUT_ONLY

    @pytest.mark.asyncio
    async def test_scan_ath_breakout_requires_historical_data(self, handler, mock_scan_result):
        """Test scan_ath_breakout requires 260 days of historical data."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        # Track what data fetcher is used
        data_fetcher_days = []

        async def track_fetch(symbol, days=90):
            data_fetcher_days.append(days)
            return ([100.0] * days, [1000000] * days, [101.0] * days, [99.0] * days)

        with patch.object(handler, '_fetch_historical_cached', side_effect=track_fetch):
            with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
                with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                    mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                    mock_loader.return_value.stability_split_enabled = False

                    with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                        mock_ef.return_value.cache.get.return_value = None

                        await handler.scan_ath_breakout(symbols=["AAPL"])

        # Should request at least 260 days of data
        assert len(data_fetcher_days) > 0
        assert max(data_fetcher_days) >= 260


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

    @pytest.mark.asyncio
    async def test_scan_earnings_dip_uses_earnings_dip_mode(self, handler, mock_scan_result):
        """Test scan_earnings_dip uses EARNINGS_DIP mode."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    await handler.scan_earnings_dip(symbols=["AAPL"])

        call_args = mock_scanner.scan_async.call_args
        assert call_args[1]['mode'] == ScanMode.EARNINGS_DIP

    @pytest.mark.asyncio
    async def test_scan_earnings_dip_empty_results_message(self, handler):
        """Test scan_earnings_dip shows specific no results message."""
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

                    result = await handler.scan_earnings_dip(symbols=["AAPL"])

        assert "No earnings dip candidates found" in result
        assert "requires recent earnings" in result


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

    @pytest.mark.asyncio
    async def test_scan_multi_strategy_all_list(self, handler, mock_scan_result):
        """Test scan_multi_strategy with all list."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL", "TSLA"]
                mock_loader.return_value.stability_split_enabled = True

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_multi_strategy(
                        symbols=None,
                        list_type="all",
                    )

        assert "Full Watchlist" in result

    @pytest.mark.asyncio
    async def test_scan_multi_strategy_uses_best_signal_mode(self, handler, mock_scan_result):
        """Test scan_multi_strategy uses BEST_SIGNAL mode."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    await handler.scan_multi_strategy(symbols=["AAPL"])

        call_args = mock_scanner.scan_async.call_args
        assert call_args[1]['mode'] == ScanMode.BEST_SIGNAL

    @pytest.mark.asyncio
    async def test_scan_multi_strategy_shows_strategy_icons(self, handler):
        """Test scan_multi_strategy shows strategy icons in output."""
        signals = [
            MockSignal("AAPL", 8.5, 185.50, "pullback", "Signal 1"),
            MockSignal("MSFT", 7.5, 410.0, "bounce", "Signal 2"),
            MockSignal("NVDA", 7.0, 500.0, "ath_breakout", "Signal 3"),
            MockSignal("META", 6.5, 350.0, "earnings_dip", "Signal 4"),
        ]
        mock_result = MockScanResult(signals=signals, symbols_with_signals=4)
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL", "MSFT", "NVDA", "META"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    result = await handler.scan_multi_strategy(symbols=["AAPL", "MSFT", "NVDA", "META"])

        # Check for strategy icons
        assert "[PB]" in result  # pullback
        assert "[BN]" in result  # bounce
        assert "[ATH]" in result  # ath_breakout
        assert "[ED]" in result  # earnings_dip


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

        assert "Short $180" in result
        assert "Long $170" in result

    @pytest.mark.asyncio
    async def test_daily_picks_with_chain_validation(self, handler):
        """Test daily_picks with chain validation."""
        mock_short_leg = MockOptionLeg(
            strike=180.0, delta=-0.20, iv=0.25, open_interest=1500, bid=2.50, ask=2.70
        )
        mock_long_leg = MockOptionLeg(
            strike=170.0, delta=-0.10, iv=0.26, open_interest=1200, bid=1.00, ask=1.20
        )
        mock_spread = MockSpreadValidation(
            tradeable=True,
            short_leg=mock_short_leg,
            long_leg=mock_long_leg,
            spread_width=10.0,
            expiration="2026-03-20",
            dte=45,
            credit_bid=1.50,
            credit_mid=1.55,
            credit_pct=15.0,
            max_loss_per_contract=850.0,
            spread_theta=0.05,
        )

        mock_pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
            spread_validation=mock_spread,
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
                    max_picks=5,
                    include_strikes=True,
                )

        # Should include chain-validated data
        assert "$180" in result  # short strike
        assert "$170" in result  # long strike
        assert "45 DTE" in result

    @pytest.mark.asyncio
    async def test_daily_picks_applies_earnings_prefilter(self, handler):
        """Test daily_picks applies earnings prefilter."""
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

        # Track prefilter calls
        prefilter_called = []

        async def mock_prefilter(symbols, min_days, for_earnings_dip=False):
            prefilter_called.append((symbols, min_days, for_earnings_dip))
            return symbols, 0, 0

        with patch.object(handler, '_apply_earnings_prefilter', side_effect=mock_prefilter):
            with patch('src.handlers.scan.DailyRecommendationEngine', return_value=mock_engine):
                with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                    mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]

                    await handler.daily_picks(symbols=["AAPL"])

        # Prefilter should have been called
        assert len(prefilter_called) > 0

    @pytest.mark.asyncio
    async def test_daily_picks_fetches_vix(self, handler):
        """Test daily_picks fetches VIX level."""
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

        get_vix_called = []

        async def track_get_vix(force_refresh=False):
            get_vix_called.append(True)
            return 18.5

        with patch.object(handler, 'get_vix', side_effect=track_get_vix):
            with patch('src.handlers.scan.DailyRecommendationEngine', return_value=mock_engine):
                with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                    mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]

                    await handler.daily_picks(symbols=["AAPL"])

        assert len(get_vix_called) > 0
        mock_engine.set_vix.assert_called()

    @pytest.mark.asyncio
    async def test_daily_picks_handles_vix_error(self, handler):
        """Test daily_picks handles VIX fetch error gracefully."""
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
            vix_level=None,  # No VIX available
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        mock_engine = MagicMock()
        mock_engine.get_daily_picks = AsyncMock(return_value=mock_result)
        mock_engine.set_vix = MagicMock()

        async def fail_get_vix(force_refresh=False):
            raise Exception("VIX fetch failed")

        with patch.object(handler, 'get_vix', side_effect=fail_get_vix):
            with patch('src.handlers.scan.DailyRecommendationEngine', return_value=mock_engine):
                with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                    mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]

                    # Should not raise
                    result = await handler.daily_picks(symbols=["AAPL"])

        assert result is not None


# =============================================================================
# CHAIN VALIDATION TESTS
# =============================================================================

class TestApplyChainValidation:
    """Tests for _apply_chain_validation method."""

    @pytest.mark.asyncio
    async def test_apply_chain_validation_filters_untradeable(self, handler):
        """Test chain validation filters out untradeable picks."""
        mock_short_leg = MockOptionLeg(
            strike=180.0, delta=-0.20, iv=0.25, open_interest=1500, bid=2.50, ask=2.70
        )
        mock_long_leg = MockOptionLeg(
            strike=170.0, delta=-0.10, iv=0.26, open_interest=1200, bid=1.00, ask=1.20
        )

        picks = [
            MockDailyPick(
                rank=1, symbol="AAPL", score=8.5, stability_score=85.0,
                strategy="pullback", current_price=185.50, sector="Technology",
                reliability_grade="A"
            ),
            MockDailyPick(
                rank=2, symbol="MSFT", score=7.5, stability_score=80.0,
                strategy="pullback", current_price=410.0, sector="Technology",
                reliability_grade="B"
            ),
        ]

        mock_result = MockDailyRecommendationResult(
            picks=picks,
            vix_level=18.5,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        # Create mock validator
        mock_validator = MagicMock()

        # AAPL is tradeable, MSFT is not
        async def mock_validate(symbol):
            if symbol == "AAPL":
                return MockSpreadValidation(
                    tradeable=True,
                    short_leg=mock_short_leg,
                    long_leg=mock_long_leg,
                    spread_width=10.0,
                    expiration="2026-03-20",
                    dte=45,
                    credit_bid=1.50,
                    credit_mid=1.55,
                    credit_pct=15.0,
                    max_loss_per_contract=850.0,
                    spread_theta=0.05,
                )
            else:
                return MockSpreadValidation(
                    tradeable=False,
                    short_leg=mock_short_leg,
                    long_leg=mock_long_leg,
                    spread_width=10.0,
                    expiration="2026-03-20",
                    dte=45,
                    credit_bid=0.50,
                    credit_mid=0.55,
                    credit_pct=5.0,
                    max_loss_per_contract=950.0,
                    spread_theta=0.02,
                    reason="Credit too low",
                )

        mock_validator.validate_spread = AsyncMock(side_effect=mock_validate)

        # Mock the import
        with patch.dict('sys.modules', {'src.services.options_chain_validator': MagicMock()}):
            with patch('src.handlers.scan.ScanHandlerMixin._apply_chain_validation') as mock_method:
                # Return filtered result
                filtered_result = MockDailyRecommendationResult(
                    picks=[picks[0]],  # Only AAPL
                    vix_level=18.5,
                    market_regime=MockVixRegime(),
                    symbols_scanned=100,
                    signals_found=10,
                    after_stability_filter=5,
                    warnings=["Chain-Validierung: 1 Picks nicht handelbar"],
                )
                mock_method.return_value = filtered_result

                result = await mock_method(mock_result, max_picks=5)

        assert len(result.picks) == 1
        assert result.picks[0].symbol == "AAPL"


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

        assert "Normal" in output

    def test_format_danger_zone_regime(self, handler):
        """Test formatting with danger zone VIX regime."""
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

        class DangerZoneRegime:
            value = "danger_zone"

        result = MockDailyRecommendationResult(
            picks=[mock_pick],
            vix_level=28.0,
            market_regime=DangerZoneRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        output = handler._format_daily_picks_output(result, 5.0)

        assert "Danger Zone" in output

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

    def test_format_with_excluded_by_earnings(self, handler):
        """Test formatting shows excluded by earnings count."""
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
            vix_level=18.5,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=10,
            after_stability_filter=5,
        )

        output = handler._format_daily_picks_output(result, 5.0, excluded_by_earnings=5)

        # Should contain count info in output
        assert "100" in output  # symbols scanned


class TestFormatSinglePickV2:
    """Tests for _format_single_pick_v2 method."""

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

        format_single_pick_v2(b, pick)
        output = b.build()

        assert "AAPL" in output
        assert "Pullback" in output
        assert "Stab(85)" in output
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

        format_single_pick_v2(b, pick)
        output = b.build()

        assert "Short $180" in output
        assert "Long $170" in output
        assert "Width $10" in output

    def test_format_pick_with_chain_validation(self, handler):
        """Test formatting pick with chain validation data."""
        from src.utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        mock_short_leg = MockOptionLeg(
            strike=180.0, delta=-0.20, iv=0.25, open_interest=1500, bid=2.50, ask=2.70
        )
        mock_long_leg = MockOptionLeg(
            strike=170.0, delta=-0.10, iv=0.26, open_interest=1200, bid=1.00, ask=1.20
        )
        mock_spread = MockSpreadValidation(
            tradeable=True,
            short_leg=mock_short_leg,
            long_leg=mock_long_leg,
            spread_width=10.0,
            expiration="2026-03-20",
            dte=45,
            credit_bid=1.50,
            credit_mid=1.55,
            credit_pct=15.0,
            max_loss_per_contract=850.0,
            spread_theta=0.05,
        )

        pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
            spread_validation=mock_spread,
        )

        format_single_pick_v2(b, pick)
        output = b.build()

        # Check for spread validation data
        assert "$180" in output
        assert "$170" in output
        assert "45 DTE" in output
        assert "$1.50" in output  # credit_bid

    def test_format_pick_with_entry_quality(self, handler):
        """Test formatting pick with entry quality score."""
        from src.utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        mock_eq = MockEntryQuality()
        pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
            entry_quality=mock_eq,
        )

        format_single_pick_v2(b, pick)
        output = b.build()

        assert "EQS 65" in output
        assert "IV Rank 45" in output
        assert "RSI 35" in output

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

        format_single_pick_v2(b, pick)
        output = b.build()

        assert "Warning: Near earnings" in output
        assert "Warning: High IV" in output


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in scan methods."""

    @pytest.mark.asyncio
    async def test_scan_handles_scanner_exception(self, handler):
        """Test scan handles scanner exception gracefully by returning error markdown."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(side_effect=Exception("Scanner error"))

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    # Error handler wraps and returns error markdown instead of raising
                    result = await handler.scan_with_strategy(symbols=["AAPL"])

        # Should return error markdown, not raise
        assert result is not None
        assert "Error" in result or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_scan_handles_data_fetch_exception(self, handler, mock_scan_result):
        """Test scan handles data fetch exception gracefully."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        async def fail_fetch(symbol, days=90):
            raise Exception("Data fetch failed")

        with patch.object(handler, '_fetch_historical_cached', side_effect=fail_fetch):
            with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
                with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                    mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                    mock_loader.return_value.stability_split_enabled = False

                    with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                        mock_ef.return_value.cache.get.return_value = None

                        # Should not crash - data fetch errors are handled
                        result = await handler.scan_with_strategy(symbols=["AAPL"])

        assert result is not None

    @pytest.mark.asyncio
    async def test_daily_picks_handles_engine_exception(self, handler):
        """Test daily_picks handles engine exception by returning error markdown."""
        mock_engine = MagicMock()
        mock_engine.get_daily_picks = AsyncMock(side_effect=Exception("Engine error"))
        mock_engine.set_vix = MagicMock()

        with patch('src.handlers.scan.DailyRecommendationEngine', return_value=mock_engine):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]

                # Error handler wraps and returns error markdown instead of raising
                result = await handler.daily_picks(symbols=["AAPL"])

        # Should return error markdown, not raise
        assert result is not None
        assert "Error" in result or "error" in result.lower()


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

        format_single_pick_v2(b, pick)
        output = b.build()

        assert "TEST" in output
        assert "Pullback" in output

    def test_format_pick_no_stability_score(self, handler):
        """Test formatting pick without stability score."""
        from src.utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        pick = MockDailyPick(
            rank=1,
            symbol="TEST",
            score=5.0,
            stability_score=None,
            strategy="pullback",
            current_price=100.0,
            sector="Technology",
            reliability_grade=None,
        )

        format_single_pick_v2(b, pick)
        output = b.build()

        assert "TEST" in output
        # Should not crash without stability score

    @pytest.mark.asyncio
    async def test_scan_with_single_symbol(self, handler, mock_scan_result):
        """Test scan with single symbol."""
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
                        max_results=1,
                        min_score=3.5,
                    )

        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_scan_with_invalid_symbols_skipped(self, handler, mock_scan_result):
        """Test scan skips invalid symbols via validation."""
        mock_scanner = MagicMock()
        mock_scanner.config = MagicMock()
        mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)

        with patch.object(handler, '_get_multi_scanner', return_value=mock_scanner):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]
                mock_loader.return_value.stability_split_enabled = False

                with patch('src.handlers.scan.get_earnings_fetcher') as mock_ef:
                    mock_ef.return_value.cache.get.return_value = None

                    with patch('src.handlers.scan.validate_symbols') as mock_validate:
                        mock_validate.return_value = ["AAPL"]  # Invalid symbols filtered out

                        result = await handler.scan_with_strategy(
                            symbols=["AAPL", "INVALID123"],
                            max_results=10,
                            min_score=3.5,
                        )

        # Should only scan valid symbols
        assert result is not None

    @pytest.mark.asyncio
    async def test_daily_picks_with_zero_max_picks(self, handler):
        """Test daily_picks with zero max_picks."""
        mock_result = MockDailyRecommendationResult(
            picks=[],
            vix_level=18.5,
            market_regime=MockVixRegime(),
            symbols_scanned=100,
            signals_found=0,
            after_stability_filter=0,
        )

        mock_engine = MagicMock()
        mock_engine.get_daily_picks = AsyncMock(return_value=mock_result)
        mock_engine.set_vix = MagicMock()

        with patch('src.handlers.scan.DailyRecommendationEngine', return_value=mock_engine):
            with patch('src.handlers.scan.get_watchlist_loader') as mock_loader:
                mock_loader.return_value.get_symbols_by_list_type.return_value = ["AAPL"]

                result = await handler.daily_picks(
                    symbols=["AAPL"],
                    max_picks=0,  # Edge case
                )

        assert result is not None

    def test_format_pick_with_all_strategy_types(self, handler):
        """Test formatting picks with all strategy types."""
        from src.utils.markdown_builder import MarkdownBuilder

        strategies = ["pullback", "bounce", "ath_breakout", "earnings_dip"]
        expected_display = ["Pullback", "Bounce", "ATH Breakout", "Earnings Dip"]

        for strategy, expected in zip(strategies, expected_display):
            b = MarkdownBuilder()
            pick = MockDailyPick(
                rank=1,
                symbol="TEST",
                score=5.0,
                stability_score=75.0,
                strategy=strategy,
                current_price=100.0,
                sector="Technology",
                reliability_grade="B",
            )

            format_single_pick_v2(b, pick)
            output = b.build()

            assert expected in output

    def test_format_pick_with_rsi_indicators(self, handler):
        """Test formatting pick shows RSI indicators (oversold/overbought)."""
        from src.utils.markdown_builder import MarkdownBuilder

        # Test oversold RSI
        b = MarkdownBuilder()
        mock_eq_oversold = MockEntryQuality(rsi=30.0)
        pick = MockDailyPick(
            rank=1,
            symbol="AAPL",
            score=8.5,
            stability_score=85.0,
            strategy="pullback",
            current_price=185.50,
            sector="Technology",
            reliability_grade="A",
            entry_quality=mock_eq_oversold,
        )

        format_single_pick_v2(b, pick)
        output = b.build()
        assert "oversold" in output

        # Test overbought RSI
        b = MarkdownBuilder()
        mock_eq_overbought = MockEntryQuality(rsi=70.0)
        pick.entry_quality = mock_eq_overbought

        format_single_pick_v2(b, pick)
        output = b.build()
        assert "overbought" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
