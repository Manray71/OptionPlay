# Tests for SectorCycleService (Schritt 6)
import asyncio
import pytest
import yaml
from unittest.mock import AsyncMock, MagicMock, patch

from src.config.scoring_config import RecursiveConfigResolver
from src.services.sector_cycle_service import (
    SectorCycleService,
    SectorRegime,
    SectorStatus,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    RecursiveConfigResolver.reset()
    yield
    RecursiveConfigResolver.reset()


@pytest.fixture
def sample_yaml(tmp_path):
    config = {
        "version": "1.0.0",
        "defaults": {"min_stability": 70},
        "strategies": {},
        "sector_momentum": {
            "enabled": True,
            "cache_ttl_hours": 4,
            "etf_mapping": {
                "Technology": "XLK",
                "Healthcare": "XLV",
                "Financials": "XLF",
            },
            "factor_range": {"min": 0.6, "max": 1.2},
            "lookback_days": {"short": 30, "long": 60},
            "component_weights": {
                "relative_strength_30d": 0.40,
                "relative_strength_60d": 0.30,
                "breadth": 0.20,
                "vol_premium": 0.10,
            },
        },
    }
    yaml_path = tmp_path / "scoring_weights.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    RecursiveConfigResolver(str(yaml_path))
    return str(yaml_path)


def _make_prices(base: float, daily_return: float, n: int = 70) -> list:
    """Generate synthetic price series."""
    prices = [base]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + daily_return))
    return prices


def _make_flat_prices(base: float, n: int = 70) -> list:
    """Generate flat price series."""
    return [base] * n


class TestNeutralMarket:
    @pytest.mark.asyncio
    async def test_neutral_market_factor_near_one(self, sample_yaml):
        """In a neutral market (flat ETF and SPY), factor ≈ 1.0."""
        mock_provider = AsyncMock()

        # Both SPY and ETF are flat
        flat = _make_flat_prices(100.0)
        mock_provider.get_historical = AsyncMock(return_value=flat)

        service = SectorCycleService(provider=mock_provider)
        statuses = await service.get_all_sector_statuses()

        for status in statuses:
            assert 0.85 <= status.momentum_factor <= 1.15, (
                f"{status.sector}: factor={status.momentum_factor}"
            )


class TestWeakSector:
    @pytest.mark.asyncio
    async def test_weak_sector_factor_below_one(self, sample_yaml):
        """A sector underperforming SPY should have factor < 0.90."""
        spy_prices = _make_prices(100.0, 0.003, 70)  # SPY rising
        weak_prices = _make_prices(100.0, -0.005, 70)  # ETF falling

        service = SectorCycleService(provider=MagicMock())

        # Directly mock the internal fetch method
        async def mock_fetch(symbol, days):
            if symbol == "SPY":
                return spy_prices
            return weak_prices

        service._fetch_historical = mock_fetch
        statuses = await service.get_all_sector_statuses()

        for status in statuses:
            assert status.momentum_factor < 0.90, (
                f"{status.sector}: factor={status.momentum_factor} should be < 0.90"
            )


class TestStrongSector:
    @pytest.mark.asyncio
    async def test_strong_sector_factor_above_one(self, sample_yaml):
        """A sector outperforming SPY should have factor > 1.05."""
        spy_prices = _make_prices(100.0, 0.001, 70)   # SPY slow
        strong_prices = _make_prices(100.0, 0.008, 70)  # ETF fast

        service = SectorCycleService(provider=MagicMock())

        async def mock_fetch(symbol, days):
            if symbol == "SPY":
                return spy_prices
            return strong_prices

        service._fetch_historical = mock_fetch
        statuses = await service.get_all_sector_statuses()

        for status in statuses:
            assert status.momentum_factor > 1.05, (
                f"{status.sector}: factor={status.momentum_factor} should be > 1.05"
            )


class TestClamping:
    @pytest.mark.asyncio
    async def test_factor_clamped_to_range(self, sample_yaml):
        """Factor must be within [0.6, 1.2]."""
        mock_provider = AsyncMock()

        spy_prices = _make_prices(100.0, 0.001, 70)
        extreme_prices = _make_prices(100.0, 0.05, 70)  # Extreme outperformance

        async def mock_historical(symbol, days=70):
            if symbol == "SPY":
                return spy_prices
            return extreme_prices

        mock_provider.get_historical = AsyncMock(side_effect=mock_historical)

        service = SectorCycleService(provider=mock_provider)
        statuses = await service.get_all_sector_statuses()

        for status in statuses:
            assert 0.6 <= status.momentum_factor <= 1.2


class TestRegimeClassification:
    @pytest.mark.asyncio
    async def test_regimes(self, sample_yaml):
        """Test regime classification based on factor values."""
        service = SectorCycleService(provider=AsyncMock())

        assert service._classify_regime(1.10) == SectorRegime.STRONG
        assert service._classify_regime(1.00) == SectorRegime.NEUTRAL
        assert service._classify_regime(0.80) == SectorRegime.WEAK
        assert service._classify_regime(0.65) == SectorRegime.CRISIS


class TestCache:
    @pytest.mark.asyncio
    async def test_cache_prevents_refetch(self, sample_yaml):
        """Second call should use cache, not call provider again."""
        mock_provider = AsyncMock()
        flat = _make_flat_prices(100.0)
        mock_provider.get_historical = AsyncMock(return_value=flat)

        service = SectorCycleService(provider=mock_provider)

        await service.get_all_sector_statuses()
        call_count_1 = mock_provider.get_historical.call_count

        await service.get_all_sector_statuses()
        call_count_2 = mock_provider.get_historical.call_count

        # No additional calls on second invocation
        assert call_count_2 == call_count_1


class TestAPIError:
    @pytest.mark.asyncio
    async def test_api_error_returns_neutral(self, sample_yaml):
        """API errors should return factor 1.0 (neutral)."""
        mock_provider = AsyncMock()
        mock_provider.get_historical = AsyncMock(return_value=None)

        service = SectorCycleService(provider=mock_provider)
        statuses = await service.get_all_sector_statuses()

        for status in statuses:
            assert status.momentum_factor == 1.0

    @pytest.mark.asyncio
    async def test_get_sector_factor_error_returns_neutral(self, sample_yaml):
        """get_sector_factor should return 1.0 on error."""
        mock_provider = AsyncMock()
        mock_provider.get_historical = AsyncMock(return_value=None)

        service = SectorCycleService(provider=mock_provider)
        factor = await service.get_sector_factor("Technology")
        assert factor == 1.0


class TestMockCalculations:
    @pytest.mark.asyncio
    async def test_all_statuses_returned(self, sample_yaml):
        """Should return one status per configured sector."""
        mock_provider = AsyncMock()
        flat = _make_flat_prices(100.0)
        mock_provider.get_historical = AsyncMock(return_value=flat)

        service = SectorCycleService(provider=mock_provider)
        statuses = await service.get_all_sector_statuses()

        # 3 sectors in sample config
        assert len(statuses) == 3
        sectors = {s.sector for s in statuses}
        assert "Technology" in sectors
        assert "Healthcare" in sectors
        assert "Financials" in sectors


# ======================================================================
# v3: Strategy-Specific Sector Factor
# ======================================================================


@pytest.fixture
def v3_yaml(tmp_path):
    """Create v3 config with strategy_overrides for sector momentum."""
    config = {
        "version": "3.0.0",
        "defaults": {"min_stability": 70},
        "strategies": {},
        "sector_momentum": {
            "enabled": True,
            "cache_ttl_hours": 4,
            "etf_mapping": {
                "Technology": "XLK",
                "Healthcare": "XLV",
            },
            "factor_range": {"min": 0.6, "max": 1.2},
            "lookback_days": {"short": 30, "long": 60},
            "component_weights": {
                "relative_strength_30d": 0.40,
                "relative_strength_60d": 0.30,
                "breadth": 0.20,
                "vol_premium": 0.10,
            },
            "strategy_overrides": {
                "ath_breakout": {
                    "factor_range": {"min": 0.50, "max": 1.25},
                    "component_weights": {
                        "relative_strength_30d": 0.50,
                        "relative_strength_60d": 0.20,
                        "breadth": 0.15,
                        "vol_premium": 0.15,
                    },
                },
                "earnings_dip": {
                    "factor_range": {"min": 0.90, "max": 1.10},
                    "component_weights": {
                        "relative_strength_30d": 0.20,
                        "relative_strength_60d": 0.20,
                        "breadth": 0.30,
                        "vol_premium": 0.30,
                    },
                },
            },
        },
    }
    yaml_path = tmp_path / "scoring_weights_v3.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    RecursiveConfigResolver.reset()
    RecursiveConfigResolver(str(yaml_path))
    return str(yaml_path)


class TestV3StrategyFactor:
    """v3: get_sector_factor with strategy parameter."""

    @pytest.mark.asyncio
    async def test_without_strategy_returns_global(self, v3_yaml):
        """Without strategy, returns the globally calculated factor."""
        spy_prices = _make_prices(100.0, 0.003, 70)
        weak_prices = _make_prices(100.0, -0.005, 70)

        service = SectorCycleService(provider=MagicMock())

        async def mock_fetch(symbol, days):
            if symbol == "SPY":
                return spy_prices
            return weak_prices

        service._fetch_historical = mock_fetch
        await service.get_all_sector_statuses()

        global_factor = await service.get_sector_factor("Technology")
        assert 0.6 <= global_factor <= 1.2

    @pytest.mark.asyncio
    async def test_earnings_dip_has_narrower_range(self, v3_yaml):
        """Earnings dip factor should be clamped to [0.90, 1.10]."""
        spy_prices = _make_prices(100.0, 0.003, 70)
        weak_prices = _make_prices(100.0, -0.005, 70)

        service = SectorCycleService(provider=MagicMock())

        async def mock_fetch(symbol, days):
            if symbol == "SPY":
                return spy_prices
            return weak_prices

        service._fetch_historical = mock_fetch
        await service.get_all_sector_statuses()

        dip_factor = await service.get_sector_factor("Technology", strategy="earnings_dip")
        assert 0.90 <= dip_factor <= 1.10, (
            f"Earnings dip factor {dip_factor} should be in [0.90, 1.10]"
        )

    @pytest.mark.asyncio
    async def test_breakout_has_wider_range(self, v3_yaml):
        """ATH breakout should penalize weak sectors more (min=0.50)."""
        spy_prices = _make_prices(100.0, 0.003, 70)
        weak_prices = _make_prices(100.0, -0.005, 70)

        service = SectorCycleService(provider=MagicMock())

        async def mock_fetch(symbol, days):
            if symbol == "SPY":
                return spy_prices
            return weak_prices

        service._fetch_historical = mock_fetch
        await service.get_all_sector_statuses()

        breakout_factor = await service.get_sector_factor("Technology", strategy="ath_breakout")
        global_factor = await service.get_sector_factor("Technology")

        # Breakout should be <= global (wider penalty range)
        assert breakout_factor <= global_factor + 0.01, (
            f"Breakout {breakout_factor} should be <= global {global_factor}"
        )

    @pytest.mark.asyncio
    async def test_strategy_factor_for_unknown_sector(self, v3_yaml):
        """Unknown sector should return 1.0 even with strategy."""
        service = SectorCycleService(provider=MagicMock())

        # Empty cache → no data
        factor = await service.get_sector_factor("UnknownSector", strategy="pullback")
        assert factor == 1.0
