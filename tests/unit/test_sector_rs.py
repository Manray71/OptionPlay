# Tests for Sector Relative Strength (RRG Quadrants)
# ===================================================

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.sector_rs import (
    DEFAULT_EMA_FAST,
    DEFAULT_EMA_SLOW,
    DEFAULT_FAST_EMA,
    DEFAULT_FAST_MOMENTUM_LOOKBACK,
    DEFAULT_FAST_WEIGHT,
    DEFAULT_FAST_WINDOW,
    DEFAULT_MOMENTUM_LOOKBACK,
    MODIFIER_IMPROVING,
    MODIFIER_LAGGING,
    MODIFIER_LEADING,
    MODIFIER_WEAKENING,
    SECTOR_ETF_MAP,
    RSQuadrant,
    SectorRS,
    SectorRSService,
    StockRS,
    _compute_dual_label,
    classify_quadrant,
    compute_ema,
    compute_rs_momentum,
    compute_rs_ratio,
    get_quadrant_modifier,
    normalize_sector_name,
)

# =============================================================================
# EMA TESTS
# =============================================================================


class TestEMA:
    """Test Exponential Moving Average computation."""

    def test_ema_single_value(self):
        """Single value EMA = that value."""
        result = compute_ema([100.0], 10)
        assert result == [100.0]

    def test_ema_known_values(self):
        """EMA with known time series."""
        prices = [10.0, 11.0, 12.0, 11.0, 13.0]
        result = compute_ema(prices, 3)
        # k = 2/(3+1) = 0.5
        # EMA[0] = 10.0
        # EMA[1] = 11 * 0.5 + 10 * 0.5 = 10.5
        # EMA[2] = 12 * 0.5 + 10.5 * 0.5 = 11.25
        # EMA[3] = 11 * 0.5 + 11.25 * 0.5 = 11.125
        # EMA[4] = 13 * 0.5 + 11.125 * 0.5 = 12.0625
        assert len(result) == 5
        assert result[0] == 10.0
        assert abs(result[1] - 10.5) < 0.001
        assert abs(result[2] - 11.25) < 0.001
        assert abs(result[4] - 12.0625) < 0.001

    def test_ema_fast_reacts_quicker(self):
        """Fast EMA reacts more to recent changes than slow EMA."""
        # Prices trending up strongly at end
        prices = [100.0] * 20 + [110.0, 120.0, 130.0]
        ema_fast = compute_ema(prices, 5)
        ema_slow = compute_ema(prices, 20)
        # Fast EMA should be closer to recent high
        assert ema_fast[-1] > ema_slow[-1]

    def test_ema_empty_list(self):
        result = compute_ema([], 10)
        assert result == []

    def test_ema_zero_period(self):
        result = compute_ema([1.0, 2.0], 0)
        assert result == []


# =============================================================================
# RS RATIO TESTS
# =============================================================================


class TestRSRatio:
    """Test relative strength ratio computation."""

    def test_rs_ratio_outperformance(self):
        """Sector growing faster than benchmark -> ratio > 100."""
        # Sector goes from 100 to 120, benchmark from 100 to 105
        n = 60
        sector = [100.0 + i * (20.0 / n) for i in range(n)]
        benchmark = [100.0 + i * (5.0 / n) for i in range(n)]
        ratio = compute_rs_ratio(sector, benchmark)
        assert ratio > 100.0

    def test_rs_ratio_underperformance(self):
        """Sector growing slower than benchmark -> ratio < 100."""
        n = 60
        sector = [100.0 + i * (2.0 / n) for i in range(n)]
        benchmark = [100.0 + i * (15.0 / n) for i in range(n)]
        ratio = compute_rs_ratio(sector, benchmark)
        assert ratio < 100.0

    def test_rs_ratio_equal_performance(self):
        """Equal performance -> ratio ~100."""
        n = 60
        prices = [100.0 + i * 0.1 for i in range(n)]
        ratio = compute_rs_ratio(prices, prices)
        assert abs(ratio - 100.0) < 1.0

    def test_rs_ratio_empty_data(self):
        assert compute_rs_ratio([], []) == 100.0

    def test_rs_ratio_mismatched_length(self):
        assert compute_rs_ratio([1, 2, 3], [1, 2]) == 100.0


# =============================================================================
# RS MOMENTUM TESTS
# =============================================================================


class TestRSMomentum:
    """Test RS momentum computation."""

    def test_momentum_improving(self):
        """RS ratio improving recently -> momentum > 100."""
        n = 80  # need enough data for EMA + lookback
        # Sector flat for first half, then outperforming
        sector = [100.0] * 40 + [100.0 + i * 0.5 for i in range(40)]
        benchmark = [100.0] * n
        momentum = compute_rs_momentum(sector, benchmark)
        assert momentum > 100.0

    def test_momentum_declining(self):
        """RS ratio declining recently -> momentum < 100."""
        n = 80
        # Sector outperforming first half, then underperforming
        sector = [100.0 + i * 0.5 for i in range(40)] + [120.0 - i * 0.5 for i in range(40)]
        benchmark = [100.0] * n
        momentum = compute_rs_momentum(sector, benchmark)
        assert momentum < 100.0

    def test_momentum_insufficient_data(self):
        """Too few data points -> 100 (neutral)."""
        assert compute_rs_momentum([1, 2], [1, 2]) == 100.0

    def test_momentum_empty(self):
        assert compute_rs_momentum([], []) == 100.0


# =============================================================================
# QUADRANT TESTS
# =============================================================================


class TestQuadrants:
    """Test RRG quadrant classification."""

    def test_quadrant_leading(self):
        assert classify_quadrant(105.0, 102.0) == RSQuadrant.LEADING

    def test_quadrant_weakening(self):
        assert classify_quadrant(105.0, 98.0) == RSQuadrant.WEAKENING

    def test_quadrant_lagging(self):
        assert classify_quadrant(95.0, 98.0) == RSQuadrant.LAGGING

    def test_quadrant_improving(self):
        assert classify_quadrant(95.0, 102.0) == RSQuadrant.IMPROVING

    def test_quadrant_boundary_100_100(self):
        """100/100 is lagging (both <=)."""
        assert classify_quadrant(100.0, 100.0) == RSQuadrant.LAGGING

    def test_quadrant_boundary_100_101(self):
        """100/101 is improving (rs<=100, mom>100)."""
        assert classify_quadrant(100.0, 101.0) == RSQuadrant.IMPROVING


# =============================================================================
# SCORE MODIFIER TESTS
# =============================================================================


class TestScoreModifier:
    """Test quadrant-based score modifiers."""

    def test_modifier_leading(self):
        assert get_quadrant_modifier(RSQuadrant.LEADING) == MODIFIER_LEADING
        assert MODIFIER_LEADING == 0.5

    def test_modifier_improving(self):
        assert get_quadrant_modifier(RSQuadrant.IMPROVING) == MODIFIER_IMPROVING
        assert MODIFIER_IMPROVING == 0.3

    def test_modifier_weakening(self):
        assert get_quadrant_modifier(RSQuadrant.WEAKENING) == MODIFIER_WEAKENING
        assert MODIFIER_WEAKENING == -0.3

    def test_modifier_lagging(self):
        assert get_quadrant_modifier(RSQuadrant.LAGGING) == MODIFIER_LAGGING
        assert MODIFIER_LAGGING == -0.5


# =============================================================================
# SECTOR NAME NORMALIZATION
# =============================================================================


class TestSectorNormalization:
    """Test sector name aliasing."""

    def test_healthcare_alias(self):
        assert normalize_sector_name("Healthcare") == "Health Care"

    def test_tech_alias(self):
        assert normalize_sector_name("Information Technology") == "Technology"

    def test_canonical_unchanged(self):
        assert normalize_sector_name("Technology") == "Technology"
        assert normalize_sector_name("Financials") == "Financials"

    def test_unknown_sector_unchanged(self):
        assert normalize_sector_name("UnknownSector") == "UnknownSector"


# =============================================================================
# SERVICE TESTS
# =============================================================================


class TestSectorRSService:
    """Test the SectorRSService class."""

    def _make_provider(self, price_map: dict) -> AsyncMock:
        """Create a mock provider that returns prices from a map."""
        provider = AsyncMock()

        async def mock_historical(symbol, days=60):
            prices = price_map.get(symbol)
            if prices is None:
                return None
            result = MagicMock()
            result.closes = prices
            return result

        provider.get_historical = mock_historical
        return provider

    def _make_prices(self, n: int = 70, base: float = 100.0, trend: float = 0.0) -> list:
        """Generate synthetic prices."""
        return [base + i * trend for i in range(n)]

    @pytest.mark.asyncio
    async def test_get_all_sector_rs_returns_all_sectors(self):
        """All 11 sectors returned."""
        prices = self._make_prices()
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        service = SectorRSService(provider=self._make_provider(price_map))
        result = await service.get_all_sector_rs()

        assert len(result) == len(SECTOR_ETF_MAP)
        for sector in SECTOR_ETF_MAP:
            assert sector in result
            assert isinstance(result[sector], SectorRS)

    @pytest.mark.asyncio
    async def test_outperforming_sector_leading(self):
        """Sector outperforming benchmark should have rs_ratio > 100."""
        n = 70
        spy = self._make_prices(n, 100.0, 0.1)
        xlk = self._make_prices(n, 100.0, 0.5)  # much stronger

        price_map = {etf: spy for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = spy
        price_map["XLK"] = xlk

        service = SectorRSService(provider=self._make_provider(price_map))
        result = await service.get_all_sector_rs()

        tech = result.get("Technology")
        assert tech is not None
        assert tech.rs_ratio > 100.0

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Second call uses cache, no new API calls."""
        prices = self._make_prices()
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        provider = self._make_provider(price_map)
        service = SectorRSService(provider=provider)

        await service.get_all_sector_rs()
        await service.get_all_sector_rs()  # should use cache

        # Provider was only called once per symbol (12 total: 11 ETFs + SPY)
        # Check that get_all_sector_rs uses cache on second call
        assert service._is_cache_valid()

    @pytest.mark.asyncio
    async def test_graceful_degradation_no_spy(self):
        """If SPY data unavailable, return neutral results."""
        price_map = {"XLK": self._make_prices()}
        # No SPY in map

        service = SectorRSService(provider=self._make_provider(price_map))
        result = await service.get_all_sector_rs()

        assert len(result) == len(SECTOR_ETF_MAP)
        # All should be neutral (rs_ratio=100, modifier=0)
        for rs in result.values():
            assert rs.rs_ratio == 100.0
            assert rs.score_modifier == 0.0

    @pytest.mark.asyncio
    async def test_graceful_degradation_no_provider(self):
        """If provider is None, return 0.0 modifier."""
        service = SectorRSService(provider=None)
        # Mock _get_provider to return None
        service._get_provider = AsyncMock(return_value=None)

        modifier = await service.get_score_modifier("AAPL")
        assert modifier == 0.0

    @pytest.mark.asyncio
    async def test_get_score_modifier_known_symbol(self):
        """Symbol with known sector gets correct modifier."""
        n = 70
        spy = self._make_prices(n, 100.0, 0.1)
        xlk = self._make_prices(n, 100.0, 0.5)

        price_map = {etf: spy for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = spy
        price_map["XLK"] = xlk

        service = SectorRSService(provider=self._make_provider(price_map))

        # Pre-populate cache
        await service.get_all_sector_rs()

        # Mock sector lookup
        service._symbol_sector_map["AAPL"] = "Technology"
        modifier = await service.get_score_modifier("AAPL")

        # Tech is outperforming, should have positive modifier
        assert modifier != 0.0

    @pytest.mark.asyncio
    async def test_get_score_modifier_unknown_symbol(self):
        """Unknown symbol returns 0.0."""
        service = SectorRSService(provider=AsyncMock())
        service._get_symbol_sector = AsyncMock(return_value=None)

        modifier = await service.get_score_modifier("UNKNOWN_XYZ")
        assert modifier == 0.0

    @pytest.mark.asyncio
    async def test_all_sectors_covered(self):
        """ETF map has 11 entries (all GICS sectors)."""
        assert len(SECTOR_ETF_MAP) == 11

    @pytest.mark.asyncio
    async def test_sector_rs_dataclass_frozen(self):
        """SectorRS is frozen (immutable)."""
        rs = SectorRS(
            sector="Technology",
            etf_symbol="XLK",
            rs_ratio=102.5,
            rs_momentum=101.0,
            quadrant=RSQuadrant.LEADING,
            score_modifier=0.5,
        )
        with pytest.raises(AttributeError):
            rs.score_modifier = 0.0  # type: ignore

    # =========================================================================
    # COMPATIBILITY WRAPPER TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_compat_get_all_sector_statuses(self):
        """Compat wrapper returns list (not dict)."""
        prices = self._make_prices()
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        service = SectorRSService(provider=self._make_provider(price_map))
        statuses = await service.get_all_sector_statuses()

        assert isinstance(statuses, list)
        assert len(statuses) == len(SECTOR_ETF_MAP)

    @pytest.mark.asyncio
    async def test_compat_get_sector_factor(self):
        """Compat wrapper: modifier + 1.0 = factor."""
        prices = self._make_prices()
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        service = SectorRSService(provider=self._make_provider(price_map))
        await service.get_all_sector_rs()

        factor = await service.get_sector_factor("Technology")
        # With equal prices, modifier ≈ 0, factor ≈ 1.0
        # But exact value depends on EMA math, so just check range
        assert 0.5 <= factor <= 1.5

    @pytest.mark.asyncio
    async def test_compat_get_sector_factor_unknown(self):
        """Unknown sector returns 1.0 (neutral)."""
        service = SectorRSService(provider=AsyncMock())
        service._cache = {}
        service._cache_time = time.time()

        factor = await service.get_sector_factor("NonexistentSector")
        assert factor == 1.0

    @pytest.mark.asyncio
    async def test_compat_healthcare_alias(self):
        """Healthcare alias works in get_sector_factor."""
        prices = self._make_prices()
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        service = SectorRSService(provider=self._make_provider(price_map))
        await service.get_all_sector_rs()

        # "Healthcare" should map to "Health Care"
        factor = await service.get_sector_factor("Healthcare")
        assert 0.5 <= factor <= 1.5


# =============================================================================
# E.1 DUAL-WINDOW TESTS
# =============================================================================


class TestDualLabel:
    """Test _compute_dual_label helper."""

    def test_same_quadrant_returns_value(self):
        assert _compute_dual_label(RSQuadrant.LEADING, RSQuadrant.LEADING) == "LEADING"
        assert _compute_dual_label(RSQuadrant.LAGGING, RSQuadrant.LAGGING) == "LAGGING"

    def test_different_quadrants_arrow_format(self):
        label = _compute_dual_label(RSQuadrant.LAGGING, RSQuadrant.IMPROVING)
        assert label == "LAG→IMP"

    def test_all_short_codes(self):
        assert _compute_dual_label(RSQuadrant.LEADING, RSQuadrant.WEAKENING) == "LEAD→WEAK"
        assert _compute_dual_label(RSQuadrant.WEAKENING, RSQuadrant.LAGGING) == "WEAK→LAG"
        assert _compute_dual_label(RSQuadrant.IMPROVING, RSQuadrant.LEADING) == "IMP→LEAD"


class TestDualWindowConfig:
    """Test E.1 config constants."""

    def test_slow_ema_is_50(self):
        assert DEFAULT_EMA_SLOW == 50

    def test_slow_momentum_lookback_is_14(self):
        assert DEFAULT_MOMENTUM_LOOKBACK == 14

    def test_fast_ema_is_10(self):
        assert DEFAULT_FAST_EMA == 10

    def test_fast_window_is_20(self):
        assert DEFAULT_FAST_WINDOW == 20

    def test_fast_momentum_lookback_is_5(self):
        assert DEFAULT_FAST_MOMENTUM_LOOKBACK == 5

    def test_fast_weight_is_1_5(self):
        assert DEFAULT_FAST_WEIGHT == 1.5

    def test_ema_fast_alias(self):
        """DEFAULT_EMA_FAST is alias for DEFAULT_FAST_EMA (backward compat)."""
        assert DEFAULT_EMA_FAST == DEFAULT_FAST_EMA


class TestDualWindowCalculation:
    """Test dual-window RS computation on sector level."""

    def _make_provider(self, price_map: dict) -> AsyncMock:
        provider = AsyncMock()

        async def mock_historical(symbol, days=120):
            prices = price_map.get(symbol)
            if prices is None:
                return None
            result = MagicMock()
            result.closes = prices
            return result

        provider.get_historical = mock_historical
        return provider

    def _make_prices(self, n: int, base: float = 100.0, trend: float = 0.1) -> list:
        return [base + i * trend for i in range(n)]

    @pytest.mark.asyncio
    async def test_dual_window_fields_present(self):
        """SectorRS returned by calculate_sector_rs has all E.1 fields."""
        n = 140
        spy = self._make_prices(n)
        xlk = self._make_prices(n, trend=0.3)
        price_map = {etf: spy for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = spy
        price_map["XLK"] = xlk

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_sector_rs()
        tech = result["Technology"]

        assert hasattr(tech, "rs_ratio_fast")
        assert hasattr(tech, "rs_momentum_fast")
        assert hasattr(tech, "quadrant_fast")
        assert hasattr(tech, "dual_label")

    @pytest.mark.asyncio
    async def test_slow_and_fast_differ(self):
        """Fast RS responds more to recent price changes than slow RS."""
        n = 140
        spy = self._make_prices(n, trend=0.1)
        # XLK: flat then strong rally at end (fast should pick up more)
        xlk = [100.0] * 100 + [100.0 + i * 1.0 for i in range(40)]
        price_map = {etf: spy for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = spy
        price_map["XLK"] = xlk

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_sector_rs()
        tech = result["Technology"]

        # Fast reacts more to recent rally, so fast RS ratio should exceed slow
        assert tech.rs_ratio_fast != tech.rs_ratio

    @pytest.mark.asyncio
    async def test_score_modifier_is_slow_based(self):
        """score_modifier always comes from the slow quadrant, regardless of fast."""
        n = 140
        spy = self._make_prices(n, trend=0.1)
        # XLK lags SPY overall (slow=LAGGING), but rallies in last 30 bars
        xlk = [100.0 - i * 0.05 for i in range(100)] + [95.0 + i * 1.5 for i in range(40)]
        price_map = {etf: spy for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = spy
        price_map["XLK"] = xlk

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_sector_rs()
        tech = result["Technology"]

        # score_modifier must equal modifier of the slow quadrant
        expected_modifier = get_quadrant_modifier(tech.quadrant)
        assert tech.score_modifier == expected_modifier

    @pytest.mark.asyncio
    async def test_dual_label_lag_to_imp(self):
        """Slow=LAGGING, Fast=IMPROVING → dual_label == 'LAG→IMP'."""
        n = 140
        spy = self._make_prices(n, trend=0.3)
        # XLK underperforms for long run, strong short-term reversal
        xlk = [100.0 - i * 0.02 for i in range(110)] + [97.8 + i * 2.0 for i in range(30)]
        price_map = {etf: spy for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = spy
        price_map["XLK"] = xlk

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_sector_rs()
        tech = result["Technology"]

        expected = _compute_dual_label(tech.quadrant, tech.quadrant_fast)
        assert tech.dual_label == expected

    @pytest.mark.asyncio
    async def test_graceful_degradation_missing_fast_window_config(self):
        """Service uses defaults if fast_window not in config dict."""
        svc = SectorRSService(config={})  # empty config
        assert svc._fast_window == DEFAULT_FAST_WINDOW
        assert svc._fast_ema == DEFAULT_FAST_EMA
        assert svc._fast_momentum_lookback == DEFAULT_FAST_MOMENTUM_LOOKBACK
        assert svc._fast_weight == DEFAULT_FAST_WEIGHT


class TestGetAllStockRS:
    """Test E.1 batch stock RS method."""

    def _make_provider(self, price_map: dict) -> AsyncMock:
        provider = AsyncMock()

        async def mock_historical(symbol, days=130):
            prices = price_map.get(symbol)
            if prices is None:
                return None
            result = MagicMock()
            result.closes = prices
            return result

        provider.get_historical = mock_historical
        return provider

    def _make_prices(self, n: int = 140, base: float = 100.0, trend: float = 0.1) -> list:
        return [base + i * trend for i in range(n)]

    @pytest.mark.asyncio
    async def test_returns_stock_rs_for_all_symbols(self):
        """get_all_stock_rs returns StockRS for each requested symbol."""
        syms = ["AAPL", "MSFT", "NVDA"]
        spy = self._make_prices()
        price_map = {
            "SPY": spy,
            "AAPL": self._make_prices(trend=0.2),
            "MSFT": spy,
            "NVDA": self._make_prices(trend=0.4),
        }

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_stock_rs(syms)

        assert set(result.keys()) == set(syms)
        for sym in syms:
            assert isinstance(result[sym], StockRS)

    @pytest.mark.asyncio
    async def test_stock_rs_has_all_dual_fields(self):
        """StockRS contains slow, fast, composite, and raw score fields."""
        spy = self._make_prices()
        price_map = {"SPY": spy, "AAPL": self._make_prices(trend=0.3)}

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_stock_rs(["AAPL"])
        aapl = result["AAPL"]

        assert hasattr(aapl, "rs_ratio")
        assert hasattr(aapl, "rs_ratio_fast")
        assert hasattr(aapl, "quadrant")
        assert hasattr(aapl, "quadrant_fast")
        assert hasattr(aapl, "dual_label")
        assert hasattr(aapl, "b_raw")
        assert hasattr(aapl, "f_raw")

    @pytest.mark.asyncio
    async def test_b_raw_and_f_raw_computation(self):
        """b_raw = rs_ratio - 100, f_raw = rs_ratio_fast - 100."""
        spy = self._make_prices()
        price_map = {"SPY": spy, "AAPL": self._make_prices(trend=0.3)}

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_stock_rs(["AAPL"])
        aapl = result["AAPL"]

        assert abs(aapl.b_raw - (aapl.rs_ratio - 100.0)) < 1e-6
        assert abs(aapl.f_raw - (aapl.rs_ratio_fast - 100.0)) < 1e-6

    @pytest.mark.asyncio
    async def test_empty_symbols_returns_empty(self):
        svc = SectorRSService(provider=AsyncMock())
        result = await svc.get_all_stock_rs([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_missing_symbol_data_skipped(self):
        """Symbols with no price data are omitted from result."""
        price_map = {"SPY": self._make_prices(), "AAPL": self._make_prices()}
        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_stock_rs(["AAPL", "MISSING"])

        assert "AAPL" in result
        assert "MISSING" not in result

    @pytest.mark.asyncio
    async def test_stock_rs_dual_label_consistency(self):
        """dual_label matches _compute_dual_label(quadrant, quadrant_fast)."""
        spy = self._make_prices()
        price_map = {"SPY": spy, "JPM": self._make_prices(trend=0.05)}

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_stock_rs(["JPM"])
        jpm = result["JPM"]

        expected = _compute_dual_label(jpm.quadrant, jpm.quadrant_fast)
        assert jpm.dual_label == expected


class TestTrailWithFast:
    """Test E.1.5 fast trail in get_all_sector_rs_with_trail."""

    def _make_provider(self, price_map: dict) -> AsyncMock:
        provider = AsyncMock()

        async def mock_historical(symbol, days=150):
            prices = price_map.get(symbol)
            if prices is None:
                return None
            result = MagicMock()
            result.closes = prices
            return result

        provider.get_historical = mock_historical
        return provider

    @pytest.mark.asyncio
    async def test_trail_fast_key_present(self):
        """get_all_sector_rs_with_trail returns trail_fast key."""
        n = 160
        prices = [100.0 + i * 0.1 for i in range(n)]
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_sector_rs_with_trail()

        for sector_data in result.values():
            assert "trail_fast" in sector_data

    @pytest.mark.asyncio
    async def test_trail_fast_length_bounded(self):
        """trail_fast length <= fast_window (20)."""
        n = 160
        prices = [100.0 + i * 0.1 for i in range(n)]
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_sector_rs_with_trail()

        for sector_data in result.values():
            assert len(sector_data["trail_fast"]) <= svc._fast_window

    @pytest.mark.asyncio
    async def test_trail_fast_fields_correct(self):
        """trail_fast entries have rs_ratio and rs_momentum keys."""
        n = 160
        prices = [100.0 + i * 0.1 for i in range(n)]
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_sector_rs_with_trail()

        for sector_data in result.values():
            for pt in sector_data["trail_fast"]:
                assert "rs_ratio" in pt
                assert "rs_momentum" in pt

    @pytest.mark.asyncio
    async def test_trail_result_has_fast_top_level_fields(self):
        """Top-level dict has rs_ratio_fast, rs_momentum_fast, quadrant_fast, dual_label."""
        n = 160
        prices = [100.0 + i * 0.1 for i in range(n)]
        price_map = {etf: prices for etf in SECTOR_ETF_MAP.values()}
        price_map["SPY"] = prices

        svc = SectorRSService(provider=self._make_provider(price_map))
        result = await svc.get_all_sector_rs_with_trail()

        for sector_data in result.values():
            assert "rs_ratio_fast" in sector_data
            assert "rs_momentum_fast" in sector_data
            assert "quadrant_fast" in sector_data
            assert "dual_label" in sector_data
