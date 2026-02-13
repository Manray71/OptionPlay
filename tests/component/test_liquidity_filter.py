"""Tests for Options Liquidity Filter."""

import pytest

from src.options.liquidity import LiquidityAssessor, LiquidityInfo, SpreadLiquidity


@pytest.fixture
def assessor():
    return LiquidityAssessor()


def _make_option(strike, bid, ask, oi=0, volume=0):
    """Helper to create option data dict."""
    return {
        "strike": strike,
        "right": "P",
        "bid": bid,
        "ask": ask,
        "open_interest": oi,
        "volume": volume,
        "delta": -0.20,
        "iv": 0.30,
        "dte": 75,
    }


# =============================================================================
# assess_strike tests
# =============================================================================


class TestAssessStrike:
    def test_excellent(self, assessor):
        # Thresholds: OI>=5000, spread<5%, volume>=200
        opt = _make_option(100, 2.00, 2.05, oi=6000, volume=300)
        result = assessor.assess_strike(opt)
        assert result.quality == "excellent"
        assert result.open_interest == 6000
        assert result.daily_volume == 300
        assert result.spread_pct < 5.0

    def test_good(self, assessor):
        # Thresholds: OI>=700, spread<10%, volume>=50
        opt = _make_option(100, 1.00, 1.08, oi=800, volume=60)
        result = assessor.assess_strike(opt)
        assert result.quality == "good"

    def test_fair(self, assessor):
        # Thresholds: OI>=100, spread<15%
        opt = _make_option(100, 1.00, 1.12, oi=150, volume=5)
        result = assessor.assess_strike(opt)
        assert result.quality == "fair"

    def test_poor_low_oi(self, assessor):
        opt = _make_option(100, 1.00, 1.05, oi=10, volume=5)
        result = assessor.assess_strike(opt)
        assert result.quality == "poor"

    def test_poor_wide_spread(self, assessor):
        opt = _make_option(100, 0.50, 1.00, oi=800, volume=100)
        result = assessor.assess_strike(opt)
        # spread_pct = (1.00 - 0.50) / 0.75 * 100 = 66.7%
        assert result.quality == "poor"

    def test_boundary_oi_700(self, assessor):
        """OI=700 with acceptable spread and volume should be 'good'."""
        opt = _make_option(100, 2.00, 2.15, oi=700, volume=50)
        result = assessor.assess_strike(opt)
        assert result.quality == "good"

    def test_boundary_oi_699(self, assessor):
        """OI=699 should NOT be 'good'."""
        opt = _make_option(100, 2.00, 2.15, oi=699, volume=50)
        result = assessor.assess_strike(opt)
        assert result.quality in ("fair", "poor")

    def test_zero_mid_price(self, assessor):
        """Zero bid and ask should not crash."""
        opt = _make_option(100, 0, 0, oi=500, volume=100)
        result = assessor.assess_strike(opt)
        assert result.spread_pct == 999.0
        assert result.quality == "poor"

    def test_none_values(self, assessor):
        """None values for bid/ask/oi/volume handled gracefully."""
        opt = {
            "strike": 100,
            "bid": None,
            "ask": None,
            "open_interest": None,
            "volume": None,
        }
        result = assessor.assess_strike(opt)
        assert result.quality == "poor"
        assert result.open_interest == 0
        assert result.daily_volume == 0


# =============================================================================
# assess_spread tests
# =============================================================================


class TestAssessSpread:
    def test_both_excellent(self, assessor):
        options_data = [
            _make_option(95, 3.00, 3.10, oi=6000, volume=400),
            _make_option(90, 1.00, 1.03, oi=5500, volume=250),
        ]
        result = assessor.assess_spread(95, 90, options_data)
        assert result is not None
        assert result.overall_quality == "excellent"
        assert result.is_tradeable is True
        assert len(result.warnings) == 0

    def test_mixed_quality_uses_worst(self, assessor):
        """Overall quality is min(short, long)."""
        options_data = [
            _make_option(95, 3.00, 3.10, oi=6000, volume=400),  # excellent
            _make_option(90, 1.00, 1.12, oi=150, volume=5),  # fair
        ]
        result = assessor.assess_spread(95, 90, options_data)
        assert result is not None
        assert result.overall_quality == "fair"
        assert result.is_tradeable is True  # fair is now tradeable (min_quality=fair)

    def test_both_poor(self, assessor):
        options_data = [
            _make_option(95, 0.50, 1.50, oi=5, volume=0),
            _make_option(90, 0.10, 0.80, oi=2, volume=0),
        ]
        result = assessor.assess_spread(95, 90, options_data)
        assert result is not None
        assert result.overall_quality == "poor"
        assert result.is_tradeable is False

    def test_missing_short_strike(self, assessor):
        """Returns None when short strike not in chain."""
        options_data = [
            _make_option(90, 1.00, 1.03, oi=600, volume=250),
        ]
        result = assessor.assess_spread(95, 90, options_data)
        assert result is None

    def test_missing_long_strike(self, assessor):
        """Returns None when long strike not in chain."""
        options_data = [
            _make_option(95, 3.00, 3.10, oi=800, volume=400),
        ]
        result = assessor.assess_spread(95, 90, options_data)
        assert result is None

    def test_missing_both_strikes(self, assessor):
        result = assessor.assess_spread(95, 90, [])
        assert result is None

    def test_warnings_generated(self, assessor):
        """Warnings for low OI and wide spreads."""
        options_data = [
            _make_option(95, 3.00, 3.50, oi=30, volume=10),  # low OI, wide spread
            _make_option(90, 1.00, 1.03, oi=600, volume=250),
        ]
        result = assessor.assess_spread(95, 90, options_data)
        assert result is not None
        assert len(result.warnings) > 0
        assert any("Low OI" in w for w in result.warnings)
        assert any("Wide bid-ask" in w for w in result.warnings)

    def test_tradeable_good_quality(self, assessor):
        """Good quality should be tradeable."""
        options_data = [
            _make_option(95, 3.00, 3.25, oi=800, volume=60),
            _make_option(90, 1.00, 1.08, oi=750, volume=55),
        ]
        result = assessor.assess_spread(95, 90, options_data)
        assert result is not None
        assert result.overall_quality == "good"
        assert result.is_tradeable is True


# =============================================================================
# LiquidityInfo tests
# =============================================================================


class TestLiquidityInfo:
    def test_spread_pct_calculation(self, assessor):
        opt = _make_option(100, 2.00, 2.20, oi=500, volume=200)
        result = assessor.assess_strike(opt)
        # mid = 2.10, spread = 0.20, spread_pct = 0.20/2.10 * 100 = 9.52%
        assert abs(result.spread_pct - 9.52) < 0.1
        assert result.mid == pytest.approx(2.10)

    def test_strike_preserved(self, assessor):
        opt = _make_option(175.50, 2.00, 2.10, oi=500, volume=200)
        result = assessor.assess_strike(opt)
        assert result.strike == 175.50


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    def test_strike_tolerance(self, assessor):
        """Strikes with tiny floating point differences should match."""
        options_data = [
            _make_option(95.0000001, 3.00, 3.10, oi=800, volume=400),
            _make_option(90.0, 1.00, 1.03, oi=600, volume=250),
        ]
        result = assessor.assess_spread(95.0, 90.0, options_data)
        assert result is not None

    def test_large_options_chain(self, assessor):
        """Should handle large chains efficiently."""
        options_data = [_make_option(50 + i, 1.00, 1.05, oi=800, volume=100) for i in range(200)]
        result = assessor.assess_spread(100, 95, options_data)
        assert result is not None
        assert result.overall_quality == "good"
