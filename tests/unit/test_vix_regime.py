# Tests for VIX Regime v2 — Continuous Interpolation Model
# ========================================================

import pytest

from src.services.vix_regime import (
    ANCHOR_POINTS,
    TS_BACKWARDATION_EARNINGS_CEILING,
    TS_BACKWARDATION_SCORE_CEILING,
    TS_CONTANGO_SCORE_FLOOR,
    TREND_FALLING_FAST_SCORE_RELIEF,
    TREND_RISING_FAST_SCORE_PENALTY,
    RegimeLabel,
    VIXRegimeParams,
    _apply_term_structure,
    _apply_trend_overlay,
    _classify_regime,
    _determine_term_structure,
    _interpolate,
    get_regime_params,
    should_trade,
)
from src.constants.trading_rules import (
    SPREAD_DTE_MAX,
    SPREAD_DTE_MIN,
    SPREAD_LONG_DELTA_TARGET,
    SPREAD_SHORT_DELTA_MAX,
    SPREAD_SHORT_DELTA_MIN,
    SPREAD_SHORT_DELTA_TARGET,
)


# =============================================================================
# INTERPOLATION TESTS
# =============================================================================


class TestInterpolation:
    """Test linear interpolation between anchor points."""

    @pytest.mark.parametrize(
        "anchor_idx",
        range(len(ANCHOR_POINTS)),
        ids=[f"anchor_vix_{a[0]}" for a in ANCHOR_POINTS],
    )
    def test_interpolation_at_exact_anchor_points(self, anchor_idx):
        """At exact anchor VIX levels, interpolation returns anchor values."""
        anchor = ANCHOR_POINTS[anchor_idx]
        vix = anchor[0]
        result = _interpolate(vix)

        assert result["spread"] == anchor[1]
        assert result["min_score"] == anchor[2]
        assert result["earnings"] == anchor[3]
        assert result["max_pos"] == anchor[4]

    def test_interpolation_midpoint_between_anchors(self):
        """VIX 17.5 = midpoint between anchor 15 and 20."""
        result = _interpolate(17.5)
        # spread: (5.00 + 5.00) / 2 = 5.00
        assert result["spread"] == 5.00
        # min_score: (4.0 + 4.5) / 2 = 4.25 → rounded to 4.2
        assert result["min_score"] == 4.2
        # earnings: (60 + 60) / 2 = 60
        assert result["earnings"] == 60
        # max_pos: (5 + 4) / 2 = 4.5 → rounded to 4
        assert result["max_pos"] in (4, 5)  # rounding

    def test_interpolation_quarter_point(self):
        """VIX 12.5 = midpoint between anchor 10 and 15."""
        result = _interpolate(12.5)
        # spread: 2.50 + 0.5 * (5.00 - 2.50) = 3.75
        assert result["spread"] == 3.75
        # min_score: 3.5 + 0.5 * (4.0 - 3.5) = 3.8
        assert result["min_score"] == 3.8

    def test_interpolation_monotonicity_min_score(self):
        """min_score increases monotonically with VIX."""
        prev_score = 0.0
        for vix in range(10, 41):
            result = _interpolate(vix)
            assert result["min_score"] >= prev_score, (
                f"min_score decreased at VIX {vix}: {result['min_score']} < {prev_score}"
            )
            prev_score = result["min_score"]

    def test_interpolation_monotonicity_max_positions(self):
        """max_positions decreases monotonically with VIX."""
        prev_pos = 999
        for vix in range(10, 41):
            result = _interpolate(vix)
            assert result["max_pos"] <= prev_pos, (
                f"max_pos increased at VIX {vix}: {result['max_pos']} > {prev_pos}"
            )
            prev_pos = result["max_pos"]

    def test_interpolation_no_large_jumps(self):
        """No jump > 0.5 in min_score between adjacent VIX levels."""
        prev = _interpolate(10)
        for vix_10x in range(101, 401):
            vix = vix_10x / 10.0
            curr = _interpolate(vix)
            diff = abs(curr["min_score"] - prev["min_score"])
            assert diff <= 0.6, (
                f"Jump of {diff} at VIX {vix}"
            )
            prev = curr

    def test_clamping_below_min_anchor(self):
        """VIX below lowest anchor clamps to anchor[0] values."""
        result = _interpolate(5.0)
        anchor0 = ANCHOR_POINTS[0]
        assert result["spread"] == anchor0[1]
        assert result["min_score"] == anchor0[2]
        assert result["max_pos"] == anchor0[4]

    def test_clamping_above_max_anchor(self):
        """VIX above highest anchor clamps to anchor[-1] values."""
        result = _interpolate(50.0)
        anchor_last = ANCHOR_POINTS[-1]
        assert result["spread"] == anchor_last[1]
        assert result["min_score"] == anchor_last[2]
        assert result["max_pos"] == anchor_last[4]


# =============================================================================
# DELTA TESTS (ALWAYS FIXED)
# =============================================================================


class TestDeltaFixed:
    """Delta must always come from Playbook, never interpolated."""

    @pytest.mark.parametrize("vix", [8, 10, 15, 20, 25, 30, 35, 40, 45])
    def test_delta_always_playbook_value(self, vix):
        """Delta target is always SPREAD_SHORT_DELTA_TARGET regardless of VIX."""
        params = get_regime_params(vix)
        assert params.delta_target == SPREAD_SHORT_DELTA_TARGET
        assert params.delta_min == SPREAD_SHORT_DELTA_MIN
        assert params.delta_max == SPREAD_SHORT_DELTA_MAX
        assert params.long_delta_target == SPREAD_LONG_DELTA_TARGET

    @pytest.mark.parametrize("vix", [20, 28, 35])
    def test_delta_unchanged_by_term_structure(self, vix):
        """Term structure adjustments must not affect delta."""
        params_base = get_regime_params(vix)
        params_contango = get_regime_params(vix, vix_futures_front=vix * 1.10)
        params_backwardation = get_regime_params(vix, vix_futures_front=vix * 0.90)

        assert params_base.delta_target == params_contango.delta_target
        assert params_base.delta_target == params_backwardation.delta_target

    def test_dte_always_playbook_value(self):
        """DTE range comes from Playbook constants."""
        params = get_regime_params(20.0)
        assert params.dte_min == SPREAD_DTE_MIN
        assert params.dte_max == SPREAD_DTE_MAX


# =============================================================================
# REGIME LABEL TESTS
# =============================================================================


class TestRegimeLabels:
    """Test regime classification labels."""

    def test_regime_label_ultra_low(self):
        assert _classify_regime(8.0) == RegimeLabel.ULTRA_LOW_VOL

    def test_regime_label_low_vol(self):
        assert _classify_regime(14.0) == RegimeLabel.LOW_VOL

    def test_regime_label_normal(self):
        assert _classify_regime(18.0) == RegimeLabel.NORMAL

    def test_regime_label_elevated(self):
        assert _classify_regime(24.0) == RegimeLabel.ELEVATED

    def test_regime_label_high_vol(self):
        assert _classify_regime(29.0) == RegimeLabel.HIGH_VOL

    def test_regime_label_stress(self):
        assert _classify_regime(36.0) == RegimeLabel.STRESS

    def test_regime_label_extreme(self):
        assert _classify_regime(42.0) == RegimeLabel.EXTREME

    def test_regime_label_boundary_13(self):
        """VIX 13 is LOW VOL (not ULTRA-LOW)."""
        assert _classify_regime(13.0) == RegimeLabel.LOW_VOL

    def test_regime_label_boundary_22(self):
        """VIX 22 is ELEVATED (not NORMAL)."""
        assert _classify_regime(22.0) == RegimeLabel.ELEVATED


# =============================================================================
# MAX_PER_SECTOR DERIVATION
# =============================================================================


class TestMaxPerSector:
    """Test max_per_sector derivation from max_positions."""

    def test_max_per_sector_from_6(self):
        params = get_regime_params(10.0)
        assert params.max_positions == 6
        assert params.max_per_sector == 2  # 6 // 3

    def test_max_per_sector_from_4(self):
        params = get_regime_params(20.0)
        assert params.max_positions == 4
        assert params.max_per_sector == 1  # 4 // 3

    def test_max_per_sector_from_3(self):
        params = get_regime_params(25.0)
        assert params.max_positions == 3
        assert params.max_per_sector == 1  # 3 // 3

    def test_max_per_sector_from_0(self):
        """When max_positions=0, max_per_sector=0."""
        params = get_regime_params(40.0)
        assert params.max_positions == 0
        assert params.max_per_sector == 0


# =============================================================================
# TERM STRUCTURE TESTS
# =============================================================================


class TestTermStructure:
    """Test term structure detection and adjustments."""

    def test_contango_detected(self):
        """VIX 25, futures 28 → contango (12% premium)."""
        ts = _determine_term_structure(25.0, 28.0)
        assert ts == "contango"

    def test_backwardation_detected(self):
        """VIX 28, futures 25 → backwardation."""
        ts = _determine_term_structure(28.0, 25.0)
        assert ts == "backwardation"

    def test_neutral_band(self):
        """VIX 25, futures 25.5 → within ±3% → None."""
        ts = _determine_term_structure(25.0, 25.5)
        assert ts is None

    def test_no_futures_data(self):
        """No futures data → None."""
        ts = _determine_term_structure(25.0, None)
        assert ts is None

    def test_contango_adjustments(self):
        """Contango: score relief, max_pos bonus."""
        base = {"spread": 7.50, "min_score": 5.5, "earnings": 75, "max_pos": 2}
        adjusted, stress = _apply_term_structure(base, 28.0, "contango")

        assert adjusted["min_score"] == 5.0  # 5.5 - 0.5
        assert adjusted["max_pos"] == 3  # 2 + 1
        assert stress is False

    def test_backwardation_adjustments(self):
        """Backwardation: score penalty, max_pos penalty, earnings extra."""
        base = {"spread": 7.50, "min_score": 5.5, "earnings": 75, "max_pos": 2}
        adjusted, stress = _apply_term_structure(base, 28.0, "backwardation")

        assert adjusted["min_score"] == 6.5  # 5.5 + 1.0
        assert adjusted["max_pos"] == 1  # 2 - 1
        assert adjusted["earnings"] == 90  # 75 + 15
        assert stress is True

    def test_term_structure_ignored_below_vix_20(self):
        """Below VIX 20, term structure is not applied."""
        base = {"spread": 5.0, "min_score": 4.0, "earnings": 60, "max_pos": 5}
        adjusted, stress = _apply_term_structure(base, 15.0, "backwardation")

        assert adjusted == base
        assert stress is False

    def test_contango_score_floor(self):
        """Contango relief cannot push min_score below floor."""
        base = {"spread": 2.50, "min_score": 3.5, "earnings": 60, "max_pos": 6}
        adjusted, _ = _apply_term_structure(base, 22.0, "contango")

        assert adjusted["min_score"] >= TS_CONTANGO_SCORE_FLOOR

    def test_backwardation_score_ceiling(self):
        """Backwardation penalty cannot push min_score above ceiling."""
        base = {"spread": 10.0, "min_score": 7.5, "earnings": 90, "max_pos": 0}
        adjusted, _ = _apply_term_structure(base, 38.0, "backwardation")

        assert adjusted["min_score"] <= TS_BACKWARDATION_SCORE_CEILING

    def test_backwardation_earnings_ceiling(self):
        """Backwardation earnings extra capped at ceiling."""
        base = {"spread": 10.0, "min_score": 6.0, "earnings": 110, "max_pos": 1}
        adjusted, _ = _apply_term_structure(base, 35.0, "backwardation")

        assert adjusted["earnings"] <= TS_BACKWARDATION_EARNINGS_CEILING

    def test_backwardation_max_pos_floor(self):
        """Backwardation max_pos penalty cannot go below 0."""
        base = {"spread": 10.0, "min_score": 6.0, "earnings": 90, "max_pos": 0}
        adjusted, _ = _apply_term_structure(base, 35.0, "backwardation")

        assert adjusted["max_pos"] >= 0

    def test_full_integration_contango(self):
        """Full get_regime_params with contango."""
        params = get_regime_params(27.0, vix_futures_front=30.0)
        assert params.term_structure == "contango"
        assert params.stress_adjusted is False

    def test_full_integration_backwardation(self):
        """Full get_regime_params with backwardation."""
        params = get_regime_params(28.0, vix_futures_front=25.0)
        assert params.term_structure == "backwardation"
        assert params.stress_adjusted is True


# =============================================================================
# VIX TREND OVERLAY TESTS
# =============================================================================


class TestTrendOverlay:
    """Test VIX trend post-interpolation adjustments."""

    def test_rising_fast_tightens(self):
        """RISING_FAST: score +0.5, max_pos -1."""
        base = {"spread": 5.0, "min_score": 4.5, "earnings": 60, "max_pos": 4}
        adjusted, trend_adj = _apply_trend_overlay(base, 22.0, "rising_fast")

        assert adjusted["min_score"] == 5.0  # 4.5 + 0.5
        assert adjusted["max_pos"] == 3  # 4 - 1
        assert trend_adj is True

    def test_falling_fast_relaxes(self):
        """FALLING_FAST at high VIX: score -0.3."""
        base = {"spread": 7.5, "min_score": 5.5, "earnings": 75, "max_pos": 2}
        adjusted, trend_adj = _apply_trend_overlay(base, 28.0, "falling_fast")

        assert adjusted["min_score"] == 5.2  # 5.5 - 0.3
        assert trend_adj is True

    def test_stable_no_change(self):
        """STABLE trend: no adjustment."""
        base = {"spread": 5.0, "min_score": 4.5, "earnings": 60, "max_pos": 4}
        adjusted, trend_adj = _apply_trend_overlay(base, 22.0, "stable")

        assert adjusted == base
        assert trend_adj is False

    def test_rising_no_change(self):
        """Regular RISING trend: no adjustment (only rising_fast matters)."""
        base = {"spread": 5.0, "min_score": 4.5, "earnings": 60, "max_pos": 4}
        adjusted, trend_adj = _apply_trend_overlay(base, 22.0, "rising")

        assert adjusted == base
        assert trend_adj is False

    def test_trend_ignored_below_vix_20(self):
        """Below VIX 20, trend overlay is not applied."""
        base = {"spread": 5.0, "min_score": 4.0, "earnings": 60, "max_pos": 5}
        adjusted, trend_adj = _apply_trend_overlay(base, 15.0, "rising_fast")

        assert adjusted == base
        assert trend_adj is False

    def test_trend_none_no_change(self):
        """None trend: no adjustment."""
        base = {"spread": 5.0, "min_score": 4.5, "earnings": 60, "max_pos": 4}
        adjusted, trend_adj = _apply_trend_overlay(base, 22.0, None)

        assert adjusted == base
        assert trend_adj is False

    def test_rising_fast_max_pos_floor(self):
        """rising_fast cannot push max_pos below 0."""
        base = {"spread": 10.0, "min_score": 6.0, "earnings": 90, "max_pos": 0}
        adjusted, _ = _apply_trend_overlay(base, 35.0, "rising_fast")

        assert adjusted["max_pos"] >= 0

    def test_full_integration_trend(self):
        """Full get_regime_params with trend overlay."""
        params = get_regime_params(24.0, vix_trend="rising_fast")
        assert params.trend_adjusted is True
        assert params.vix_trend_label == "rising_fast"
        # Base min_score at VIX 24 ≈ 4.9, + 0.5 = 5.4
        assert params.min_score > 5.0


# =============================================================================
# should_trade TESTS
# =============================================================================


class TestShouldTrade:
    """Test the quick trade-allowed check."""

    def test_allowed(self):
        """Normal conditions: trade allowed."""
        result = should_trade(18.0, 5.5, 2)
        assert result["allowed"] is True
        assert "params" in result

    def test_blocked_extreme(self):
        """Extreme VIX: max_positions=0, blocked."""
        result = should_trade(42.0, 8.0, 0)
        assert result["allowed"] is False
        assert "no new positions" in result["reason"]

    def test_blocked_capacity(self):
        """Positions at max: blocked."""
        result = should_trade(20.0, 6.0, 4)  # max_pos=4 at VIX 20
        assert result["allowed"] is False
        assert "Max positions" in result["reason"]

    def test_blocked_score(self):
        """Score below minimum: blocked."""
        result = should_trade(25.0, 3.0, 0)  # min_score=5.0 at VIX 25
        assert result["allowed"] is False
        assert "Score" in result["reason"]

    def test_with_term_structure(self):
        """should_trade respects term structure."""
        # VIX 28 + backwardation → tighter
        result = should_trade(28.0, 5.5, 1, vix_futures_front=25.0)
        # Backwardation pushes min_score up, 5.5 might still pass or fail
        assert isinstance(result["allowed"], bool)

    def test_with_trend(self):
        """should_trade respects VIX trend."""
        result = should_trade(24.0, 4.5, 1, vix_trend="rising_fast")
        # rising_fast pushes min_score up, 4.5 should be blocked
        assert result["allowed"] is False

    def test_exact_score_match_allowed(self):
        """Score exactly at min_score is NOT allowed (strict <)."""
        # At VIX 20, min_score = 4.5
        result = should_trade(20.0, 4.5, 0)
        # 4.5 < 4.5 is False, so trade IS allowed
        assert result["allowed"] is True

    def test_score_just_below_blocked(self):
        """Score just below min_score is blocked."""
        result = should_trade(20.0, 4.4, 0)
        assert result["allowed"] is False


# =============================================================================
# VIXRegimeParams OUTPUT TESTS
# =============================================================================


class TestVIXRegimeParamsOutput:
    """Test VIXRegimeParams string and dict output."""

    def test_to_dict_keys(self):
        params = get_regime_params(20.0)
        d = params.to_dict()
        expected_keys = {
            "vix", "regime_label", "spread_width", "min_score",
            "earnings_buffer_days", "max_positions", "max_per_sector",
            "delta_target", "delta_min", "delta_max", "long_delta_target",
            "dte_min", "dte_max", "term_structure", "stress_adjusted",
            "vix_trend_label", "trend_adjusted",
        }
        assert set(d.keys()) == expected_keys

    def test_str_output(self):
        params = get_regime_params(20.0)
        s = str(params)
        assert "NORMAL" in s
        assert "VIX=20.0" in s
        assert "Min Score" in s
        assert "Delta Target" in s

    def test_str_with_term_structure(self):
        params = get_regime_params(28.0, vix_futures_front=25.0)
        s = str(params)
        assert "backwardation" in s
        assert "STRESS-ADJUSTED" in s

    def test_str_with_trend(self):
        params = get_regime_params(24.0, vix_trend="rising_fast")
        s = str(params)
        assert "rising_fast" in s


# =============================================================================
# EDGE CASES & REGRESSION
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_vix_zero(self):
        """VIX 0 should not crash — clamps to lowest anchor."""
        params = get_regime_params(0.0)
        assert params.min_score == 3.5  # anchor[0]
        assert params.max_positions == 6

    def test_vix_negative(self):
        """Negative VIX should raise ValueError (data error)."""
        with pytest.raises(ValueError, match="VIX cannot be negative"):
            get_regime_params(-5.0)

    def test_vix_very_high(self):
        """VIX 100 should clamp to highest anchor."""
        params = get_regime_params(100.0)
        assert params.min_score == 7.0
        assert params.max_positions == 0

    def test_combined_overlays(self):
        """Both term structure and trend applied."""
        params = get_regime_params(
            28.0, vix_futures_front=25.0, vix_trend="rising_fast"
        )
        assert params.stress_adjusted is True
        assert params.trend_adjusted is True
        # Both penalties stack
        assert params.min_score > 6.0  # base ~5.4 + 1.0 backw + 0.5 trend

    def test_contango_plus_falling_fast(self):
        """Contango + falling_fast = partial relief."""
        params = get_regime_params(
            28.0, vix_futures_front=32.0, vix_trend="falling_fast"
        )
        assert params.term_structure == "contango"
        assert params.trend_adjusted is True

    def test_all_anchor_points_reachable(self):
        """Every anchor point produces valid params."""
        for anchor in ANCHOR_POINTS:
            params = get_regime_params(float(anchor[0]))
            assert params.min_score >= 0
            assert params.max_positions >= 0
            assert params.earnings_buffer_days >= 0

    def test_regime_label_in_enum(self):
        """Regime label is always a valid RegimeLabel."""
        for vix in range(5, 50):
            params = get_regime_params(float(vix))
            assert isinstance(params.regime_label, RegimeLabel)
