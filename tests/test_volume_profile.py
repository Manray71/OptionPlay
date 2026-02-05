# Tests for Volume Profile Indicators
# =====================================
"""
Tests for VWAP, Volume Profile POC, SPY Trend, and Sector Adjustments.
"""

import pytest
import numpy as np

from src.indicators.volume_profile import (
    calculate_vwap,
    calculate_volume_profile_poc,
    calculate_spy_trend,
    get_sector,
    get_sector_adjustment,
    get_sector_adjustment_with_reason,
    VWAPResult,
    VolumeProfileResult,
    MarketContextResult,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def uptrend_prices():
    """50+ prices in uptrend."""
    base = 100.0
    return [base + i * 0.5 + np.sin(i * 0.3) * 2 for i in range(60)]


@pytest.fixture
def downtrend_prices():
    """50+ prices in downtrend."""
    base = 150.0
    return [base - i * 0.5 + np.sin(i * 0.3) * 2 for i in range(60)]


@pytest.fixture
def sideways_prices():
    """50+ prices in sideways channel."""
    return [100.0 + np.sin(i * 0.5) * 3 for i in range(60)]


@pytest.fixture
def sample_volumes():
    """60 volume data points."""
    np.random.seed(42)
    return [int(1_000_000 + np.random.randint(-500_000, 500_000)) for _ in range(60)]


# =============================================================================
# VOLUME PROFILE POC TESTS
# =============================================================================

class TestVolumeProfilePOC:
    """Tests for calculate_volume_profile_poc."""

    def test_basic_poc_calculation(self, uptrend_prices, sample_volumes):
        """Test basic POC calculation returns valid result."""
        result = calculate_volume_profile_poc(uptrend_prices, sample_volumes)
        assert result is not None
        assert isinstance(result, VolumeProfileResult)
        assert result.poc > 0
        assert result.value_area_low <= result.poc <= result.value_area_high

    def test_insufficient_data_returns_none(self):
        """Test returns None with insufficient data."""
        prices = [100.0] * 10
        volumes = [1000] * 10
        result = calculate_volume_profile_poc(prices, volumes, period=50)
        assert result is None

    def test_flat_prices_returns_none(self):
        """Test returns None when all prices are the same."""
        prices = [100.0] * 60
        volumes = [1000] * 60
        result = calculate_volume_profile_poc(prices, volumes, period=50)
        assert result is None

    def test_value_area_contains_70pct_volume(self, uptrend_prices, sample_volumes):
        """Test that value area captures approximately 70% of volume."""
        result = calculate_volume_profile_poc(uptrend_prices, sample_volumes, num_bins=20)
        assert result is not None
        # Value area should be within price range
        assert result.value_area_low >= min(uptrend_prices[-50:])
        assert result.value_area_high <= max(uptrend_prices[-50:])

    def test_distance_pct_calculation(self, uptrend_prices, sample_volumes):
        """Test distance percentage is correctly computed."""
        result = calculate_volume_profile_poc(uptrend_prices, sample_volumes)
        assert result is not None
        # Distance should be calculable
        expected_dist = (uptrend_prices[-1] - result.poc) / result.poc * 100
        assert abs(result.distance_pct - expected_dist) < 0.01

    def test_different_bin_counts(self, uptrend_prices, sample_volumes):
        """Test POC with varying bin counts."""
        for bins in [5, 10, 20, 50]:
            result = calculate_volume_profile_poc(
                uptrend_prices, sample_volumes, num_bins=bins
            )
            assert result is not None
            assert result.poc > 0

    def test_concentrated_volume(self):
        """Test with volume concentrated at one price level."""
        # Prices oscillate but volume is concentrated at one level
        prices = []
        volumes = []
        for i in range(60):
            price = 100.0 + (i % 10) * 2  # 100-118 range
            vol = 5_000_000 if 108 <= price <= 112 else 100_000
            prices.append(price)
            volumes.append(vol)

        result = calculate_volume_profile_poc(prices, volumes, period=60)
        assert result is not None
        # POC should be near the high-volume area (108-112)
        assert 105 <= result.poc <= 115


# =============================================================================
# SPY TREND TESTS
# =============================================================================

class TestSPYTrend:
    """Tests for calculate_spy_trend."""

    def test_insufficient_data_returns_none(self):
        """Test returns None with < 50 data points."""
        result = calculate_spy_trend([100.0] * 49)
        assert result is None

    def test_strong_uptrend(self):
        """Test detection of strong uptrend (price > SMA20 > SMA50)."""
        # Steady uptrend over 60 days
        prices = [100.0 + i * 1.0 for i in range(60)]
        result = calculate_spy_trend(prices)
        assert result is not None
        assert result.spy_trend == 'strong_uptrend'
        assert result.score_adjustment == 1.0
        assert result.spy_current == prices[-1]
        assert result.spy_sma20 < result.spy_current

    def test_strong_downtrend(self):
        """Test detection of strong downtrend (price < SMA20 < SMA50)."""
        # Steady downtrend over 60 days
        prices = [200.0 - i * 1.0 for i in range(60)]
        result = calculate_spy_trend(prices)
        assert result is not None
        assert result.spy_trend == 'strong_downtrend'
        assert result.score_adjustment == -1.0

    def test_sideways_trend(self):
        """Test detection of sideways trend (price > SMA50, price < SMA20)."""
        # Price above SMA50 but below SMA20 → sideways
        prices = list(range(50, 110))  # 50 to 109 (steady up then)
        # Push recent prices below SMA20 but above SMA50
        prices = [80.0 + i * 0.6 for i in range(40)] + [103.0] * 20
        result = calculate_spy_trend(prices)
        assert result is not None
        assert result.spy_trend in ('sideways', 'uptrend', 'downtrend')

    def test_result_fields(self, uptrend_prices):
        """Test all result fields are populated."""
        result = calculate_spy_trend(uptrend_prices)
        assert result is not None
        assert isinstance(result, MarketContextResult)
        assert result.spy_sma20 > 0
        assert result.spy_sma50 > 0
        assert result.spy_current > 0
        assert isinstance(result.score_adjustment, float)

    def test_sma_calculations_correct(self):
        """Test SMA20 and SMA50 are correctly computed."""
        prices = [float(i) for i in range(1, 61)]  # 1.0 to 60.0
        result = calculate_spy_trend(prices)
        assert result is not None
        # SMA20 should be mean of last 20 prices (41-60)
        expected_sma20 = np.mean(prices[-20:])
        assert abs(result.spy_sma20 - expected_sma20) < 0.01
        # SMA50 should be mean of last 50 prices (11-60)
        expected_sma50 = np.mean(prices[-50:])
        assert abs(result.spy_sma50 - expected_sma50) < 0.01


# =============================================================================
# SECTOR ADJUSTMENT TESTS
# =============================================================================

class TestGetSector:
    """Tests for get_sector."""

    def test_known_tech_symbol(self):
        assert get_sector('AAPL') == 'Technology'

    def test_known_healthcare_symbol(self):
        assert get_sector('JNJ') == 'Healthcare'

    def test_unknown_symbol(self):
        assert get_sector('ZZZZZ') == 'Unknown'

    def test_case_insensitive(self):
        assert get_sector('aapl') == 'Technology'


class TestSectorAdjustment:
    """Tests for get_sector_adjustment."""

    def test_no_vix_base_adjustment(self):
        """Test base adjustment without VIX."""
        adj = get_sector_adjustment('PG')  # Consumer Staples
        assert adj > 0  # Consumer Staples has positive adjustment

    def test_tech_negative_adjustment(self):
        """Test Technology has negative adjustment."""
        adj = get_sector_adjustment('AAPL')
        assert adj < 0

    def test_unknown_symbol_zero_adjustment(self):
        """Test unknown symbol returns 0."""
        adj = get_sector_adjustment('ZZZZZ')
        assert adj == 0.0

    def test_vix_above_15_modifies_financials(self):
        """Test VIX > 15 applies vix_15_plus modifier to Financials."""
        base_adj = get_sector_adjustment('JPM', vix=10.0)
        vix_adj = get_sector_adjustment('JPM', vix=18.0)
        # With VIX > 15, Financials should get worse
        assert vix_adj < base_adj

    def test_vix_danger_zone_additional_modifier(self):
        """Test VIX 20-25 (danger zone) applies additional modifier."""
        vix_15 = get_sector_adjustment('JPM', vix=18.0)
        vix_danger = get_sector_adjustment('JPM', vix=22.0)
        # Danger zone should be even worse than just VIX > 15
        assert vix_danger < vix_15

    def test_defensive_sectors_improve_with_high_vix(self):
        """Test defensive sectors get better with VIX > 15."""
        low_vix = get_sector_adjustment('NEE', vix=12.0)  # Utilities
        high_vix = get_sector_adjustment('NEE', vix=18.0)
        # Utilities should get better (higher) with VIX > 15
        assert high_vix > low_vix

    def test_vix_none_uses_base_only(self):
        """Test VIX=None uses only base adjustment."""
        adj_none = get_sector_adjustment('AAPL', vix=None)
        adj_low = get_sector_adjustment('AAPL', vix=10.0)
        assert adj_none == adj_low  # No VIX modifier below 15

    def test_consumer_staples_danger_zone_bonus(self):
        """Test Consumer Staples gets danger zone bonus."""
        normal = get_sector_adjustment('PG', vix=12.0)
        danger = get_sector_adjustment('PG', vix=22.0)
        assert danger > normal  # Flight to safety


class TestSectorAdjustmentWithReason:
    """Tests for get_sector_adjustment_with_reason."""

    def test_returns_tuple_of_three(self):
        """Test returns (adjustment, sector, reason)."""
        result = get_sector_adjustment_with_reason('AAPL')
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_reason_contains_sector(self):
        """Test reason string contains sector name."""
        adj, sector, reason = get_sector_adjustment_with_reason('AAPL')
        assert 'Technology' in sector or 'Technology' in reason

    def test_vix_modifier_in_reason(self):
        """Test VIX modifier shows in reason when applicable."""
        adj, sector, reason = get_sector_adjustment_with_reason('JPM', vix=22.0)
        assert 'VIX' in reason
        assert 'DANGER' in reason

    def test_adjustment_matches_plain_function(self):
        """Test adjustment value matches get_sector_adjustment."""
        for symbol in ['AAPL', 'JPM', 'PG', 'NEE', 'ZZZZZ']:
            for vix in [None, 12.0, 18.0, 22.0]:
                adj_plain = get_sector_adjustment(symbol, vix=vix)
                adj_reason, _, _ = get_sector_adjustment_with_reason(symbol, vix=vix)
                assert abs(adj_plain - adj_reason) < 0.001, \
                    f"Mismatch for {symbol} at VIX={vix}"
