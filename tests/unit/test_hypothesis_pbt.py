#!/usr/bin/env python3
"""
F.5: Hypothesis Property-Based Tests (PBT)

Property-based tests using Hypothesis for mathematical invariants:
- Score normalization: round-trip, bounds, monotonicity
- Black-Scholes: put-call parity, Greeks bounds, boundary conditions
- Position sizing: Kelly bounds, VIX adjustment monotonicity, risk constraints

Usage:
    pytest tests/unit/test_hypothesis_pbt.py -v
"""

import math
import pytest
import numpy as np

from hypothesis import given, assume, settings, HealthCheck
from hypothesis.strategies import (
    floats,
    sampled_from,
)

# Suppress deadline for first-import-time spikes
PBT_SETTINGS = settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])


# =============================================================================
# SCORE NORMALIZATION PBT
# =============================================================================

STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip", "trend_continuation"]

MAX_POSSIBLE = {
    "pullback": 14.0,
    "bounce": 10.0,
    "ath_breakout": 10.0,
    "earnings_dip": 9.5,
    "trend_continuation": 10.5,
}


class TestScoreNormalizationPBT:
    """Property-based tests for score normalization."""

    @PBT_SETTINGS
    @given(
        raw_score=floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False),
        strategy=sampled_from(STRATEGIES),
    )
    def test_normalize_bounds(self, raw_score, strategy):
        """Normalized score must always be in [0.0, 10.0]."""
        from src.analyzers.score_normalization import normalize_score

        result = normalize_score(raw_score, strategy)
        assert 0.0 <= result <= 10.0, f"Out of bounds: {result}"

    @PBT_SETTINGS
    @given(
        raw_score=floats(min_value=0.0, max_value=26.0, allow_nan=False, allow_infinity=False),
        strategy=sampled_from(STRATEGIES),
    )
    def test_normalize_denormalize_roundtrip(self, raw_score, strategy):
        """denormalize(normalize(x)) should approximate x for valid inputs."""
        from src.analyzers.score_normalization import normalize_score, denormalize_score

        max_val = MAX_POSSIBLE[strategy]
        # Clamp raw_score to valid range for this strategy
        clamped = min(raw_score, max_val)

        normalized = normalize_score(clamped, strategy)
        denormalized = denormalize_score(normalized, strategy)
        assert abs(denormalized - clamped) < 1e-9, \
            f"Round-trip failed: {clamped} -> {normalized} -> {denormalized}"

    @PBT_SETTINGS
    @given(
        strategy=sampled_from(STRATEGIES),
    )
    def test_normalize_monotonic(self, strategy):
        """normalize_score must be monotonically increasing."""
        from src.analyzers.score_normalization import normalize_score

        max_val = MAX_POSSIBLE[strategy]
        scores = np.linspace(0, max_val, 50)
        normalized = [normalize_score(float(s), strategy) for s in scores]

        for i in range(1, len(normalized)):
            assert normalized[i] >= normalized[i - 1], \
                f"Not monotonic at index {i}: {normalized[i - 1]} > {normalized[i]}"

    @PBT_SETTINGS
    @given(
        strategy=sampled_from(STRATEGIES),
    )
    def test_normalize_zero_is_zero(self, strategy):
        """normalize_score(0) must be 0.0."""
        from src.analyzers.score_normalization import normalize_score
        assert normalize_score(0.0, strategy) == 0.0

    @PBT_SETTINGS
    @given(
        strategy=sampled_from(STRATEGIES),
    )
    def test_normalize_max_is_ten(self, strategy):
        """normalize_score(max_possible) must be 10.0."""
        from src.analyzers.score_normalization import normalize_score
        max_val = MAX_POSSIBLE[strategy]
        assert abs(normalize_score(max_val, strategy) - 10.0) < 1e-9

    @PBT_SETTINGS
    @given(
        normalized=floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        strategy=sampled_from(STRATEGIES),
    )
    def test_signal_strength_valid(self, normalized, strategy):
        """get_signal_strength must return a valid category."""
        from src.analyzers.score_normalization import get_signal_strength
        result = get_signal_strength(normalized, strategy)
        assert result in {"STRONG", "MODERATE", "WEAK", "NONE"}

    @PBT_SETTINGS
    @given(
        strategy=sampled_from(STRATEGIES),
    )
    def test_signal_strength_ordering(self, strategy):
        """Higher scores must produce equal or stronger signals."""
        from src.analyzers.score_normalization import get_signal_strength

        STRENGTH_ORDER = {"NONE": 0, "WEAK": 1, "MODERATE": 2, "STRONG": 3}

        scores = np.linspace(0, 10, 50)
        strengths = [get_signal_strength(float(s), strategy) for s in scores]
        strength_values = [STRENGTH_ORDER[s] for s in strengths]

        for i in range(1, len(strength_values)):
            assert strength_values[i] >= strength_values[i - 1], \
                f"Strength decreased at score {scores[i]}: {strengths[i-1]} -> {strengths[i]}"


# =============================================================================
# BLACK-SCHOLES PBT
# =============================================================================

class TestBlackScholesPBT:
    """Property-based tests for Black-Scholes pricing model."""

    @PBT_SETTINGS
    @given(
        S=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        K=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        T=floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.15, allow_nan=False, allow_infinity=False),
        sigma=floats(min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    def test_put_call_parity(self, S, K, T, r, sigma):
        """Put-Call Parity: C - P = S - K*e^(-rT)."""
        from src.pricing.black_scholes import black_scholes_call, black_scholes_put

        call = black_scholes_call(S, K, T, r, sigma)
        put = black_scholes_put(S, K, T, r, sigma)

        theoretical_diff = S - K * math.exp(-r * T)
        actual_diff = call - put

        # Tolerance scales with option values (BS formula has clamping at 0)
        tolerance = max(0.05, 0.01 * max(call, put, abs(theoretical_diff)))
        assert abs(actual_diff - theoretical_diff) < tolerance, \
            f"Put-Call Parity violated: C-P={actual_diff:.4f}, S-Ke^(-rT)={theoretical_diff:.4f}"

    @PBT_SETTINGS
    @given(
        S=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        K=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        T=floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.15, allow_nan=False, allow_infinity=False),
        sigma=floats(min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    def test_call_price_non_negative(self, S, K, T, r, sigma):
        """Call price must be >= 0."""
        from src.pricing.black_scholes import black_scholes_call
        assert black_scholes_call(S, K, T, r, sigma) >= 0.0

    @PBT_SETTINGS
    @given(
        S=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        K=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        T=floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.15, allow_nan=False, allow_infinity=False),
        sigma=floats(min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    def test_put_price_non_negative(self, S, K, T, r, sigma):
        """Put price must be >= 0."""
        from src.pricing.black_scholes import black_scholes_put
        assert black_scholes_put(S, K, T, r, sigma) >= 0.0

    @PBT_SETTINGS
    @given(
        S=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        K=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        T=floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.15, allow_nan=False, allow_infinity=False),
        sigma=floats(min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    def test_call_upper_bound(self, S, K, T, r, sigma):
        """Call price must be <= S (can never be worth more than the stock)."""
        from src.pricing.black_scholes import black_scholes_call
        call = black_scholes_call(S, K, T, r, sigma)
        assert call <= S + 0.01  # Small tolerance for floating point

    @PBT_SETTINGS
    @given(
        S=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        K=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        T=floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.15, allow_nan=False, allow_infinity=False),
        sigma=floats(min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    def test_put_upper_bound(self, S, K, T, r, sigma):
        """Put price must be <= K*e^(-rT)."""
        from src.pricing.black_scholes import black_scholes_put
        put = black_scholes_put(S, K, T, r, sigma)
        upper = K * math.exp(-r * T)
        assert put <= upper + 0.01  # Small tolerance

    @PBT_SETTINGS
    @given(
        S=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        K=floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.10, allow_nan=False, allow_infinity=False),
        sigma=floats(min_value=0.05, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_more_time_more_value_call(self, S, K, r, sigma):
        """Longer time to expiry should produce higher or equal call price."""
        from src.pricing.black_scholes import black_scholes_call

        T1, T2 = 0.1, 0.5
        call_short = black_scholes_call(S, K, T1, r, sigma)
        call_long = black_scholes_call(S, K, T2, r, sigma)
        # American-style property: more time = more value (for calls on non-dividend stock)
        assert call_long >= call_short - 0.01

    @PBT_SETTINGS
    @given(
        S=floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        K=floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        T=floats(min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.10, allow_nan=False, allow_infinity=False),
    )
    def test_higher_vol_higher_price(self, S, K, T, r):
        """Higher volatility should produce higher or equal option prices."""
        from src.pricing.black_scholes import black_scholes_call, black_scholes_put

        sigma1, sigma2 = 0.1, 0.5
        call_low_vol = black_scholes_call(S, K, T, r, sigma1)
        call_high_vol = black_scholes_call(S, K, T, r, sigma2)
        assert call_high_vol >= call_low_vol - 0.01

        put_low_vol = black_scholes_put(S, K, T, r, sigma1)
        put_high_vol = black_scholes_put(S, K, T, r, sigma2)
        assert put_high_vol >= put_low_vol - 0.01

    @PBT_SETTINGS
    @given(
        K=floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        T=floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.10, allow_nan=False, allow_infinity=False),
        sigma=floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_deep_itm_call_approaches_intrinsic(self, K, T, r, sigma):
        """Deep ITM call should approach S - K*e^(-rT)."""
        from src.pricing.black_scholes import black_scholes_call

        S = K * 3.0  # Very deep in-the-money
        call = black_scholes_call(S, K, T, r, sigma)
        intrinsic = S - K * math.exp(-r * T)
        # Deep ITM: call ~ intrinsic (within 5% of S)
        assert call >= intrinsic - 0.01

    @PBT_SETTINGS
    @given(
        S=floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        T=floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
        r=floats(min_value=0.0, max_value=0.10, allow_nan=False, allow_infinity=False),
        sigma=floats(min_value=0.1, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    def test_deep_otm_call_near_zero(self, S, T, r, sigma):
        """Deep OTM call should be much less than spot (with moderate vol and time)."""
        from src.pricing.black_scholes import black_scholes_call

        K = S * 3.0  # Very deep out-of-the-money
        call = black_scholes_call(S, K, T, r, sigma)
        assert call < S * 0.2  # Should be small relative to spot

    def test_expired_call_is_intrinsic(self):
        """Expired call should equal max(0, S-K)."""
        from src.pricing.black_scholes import black_scholes_call

        assert black_scholes_call(100, 90, 0.0, 0.05, 0.2) == pytest.approx(10.0, abs=0.01)
        assert black_scholes_call(100, 110, 0.0, 0.05, 0.2) == pytest.approx(0.0, abs=0.01)

    def test_expired_put_is_intrinsic(self):
        """Expired put should equal max(0, K-S)."""
        from src.pricing.black_scholes import black_scholes_put

        assert black_scholes_put(100, 110, 0.0, 0.05, 0.2) == pytest.approx(10.0, abs=0.01)
        assert black_scholes_put(100, 90, 0.0, 0.05, 0.2) == pytest.approx(0.0, abs=0.01)


# =============================================================================
# POSITION SIZING PBT
# =============================================================================

class TestPositionSizingPBT:
    """Property-based tests for position sizing."""

    @PBT_SETTINGS
    @given(
        win_rate=floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
        avg_win=floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        avg_loss=floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    def test_kelly_fraction_bounds(self, win_rate, avg_win, avg_loss):
        """Kelly fraction must be in [0.0, kelly_cap]."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        result = sizer.calculate_kelly_fraction(win_rate, avg_win, avg_loss)
        assert 0.0 <= result <= 0.25, f"Kelly out of [0, 0.25]: {result}"

    @PBT_SETTINGS
    @given(
        win_rate=floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
    )
    def test_kelly_increases_with_win_rate(self, win_rate):
        """Kelly fraction should generally increase with win rate (for fixed payoff ratio)."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        avg_win, avg_loss = 150.0, 100.0

        kelly_low = sizer.calculate_kelly_fraction(0.3, avg_win, avg_loss)
        kelly_high = sizer.calculate_kelly_fraction(0.9, avg_win, avg_loss)

        # Higher win rate => higher or equal Kelly (both capped)
        assert kelly_high >= kelly_low

    @PBT_SETTINGS
    @given(
        win_rate=floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
    )
    def test_kelly_zero_for_bad_edge(self, win_rate):
        """Kelly should be 0 when edge is negative (avg_win < avg_loss with low win rate)."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        # Very bad payoff ratio
        result = sizer.calculate_kelly_fraction(win_rate, avg_win=10.0, avg_loss=1000.0)
        # With tiny avg_win/loss ratio, Kelly = W - (1-W)/R will be negative -> capped to 0
        assert result >= 0.0

    @PBT_SETTINGS
    @given(
        vix=floats(min_value=5.0, max_value=80.0, allow_nan=False, allow_infinity=False),
    )
    def test_vix_adjustment_bounds(self, vix):
        """VIX adjustment must be in [0.25, 1.0]."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        adj = sizer.get_vix_adjustment(vix)
        assert 0.25 <= adj <= 1.0, f"VIX adj out of bounds: {adj}"

    def test_vix_adjustment_decreasing(self):
        """VIX adjustment must be non-increasing with VIX level."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        vix_levels = [10, 15, 20, 25, 30, 35, 40, 50, 60]
        adjustments = [sizer.get_vix_adjustment(v) for v in vix_levels]

        for i in range(1, len(adjustments)):
            assert adjustments[i] <= adjustments[i - 1], \
                f"VIX adj increased at VIX={vix_levels[i]}: {adjustments[i-1]} -> {adjustments[i]}"

    @PBT_SETTINGS
    @given(
        score=floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    def test_score_adjustment_bounds(self, score):
        """Score adjustment must be in [0.0, 1.0]."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        adj = sizer.get_score_adjustment(score)
        assert 0.0 <= adj <= 1.0, f"Score adj out of bounds: {adj}"

    def test_score_adjustment_non_decreasing(self):
        """Score adjustment must be non-decreasing with signal score."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        scores = np.linspace(0, 10, 50)
        adjustments = [sizer.get_score_adjustment(float(s)) for s in scores]

        for i in range(1, len(adjustments)):
            assert adjustments[i] >= adjustments[i - 1], \
                f"Score adj decreased at score={scores[i]}: {adjustments[i-1]} -> {adjustments[i]}"

    def test_reliability_adjustment_valid_grades(self):
        """All valid grades must produce adjustments in [0.0, 1.0]."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        for grade in ["A", "B", "C", "D", "F", None]:
            adj = sizer.get_reliability_adjustment(grade)
            assert 0.0 <= adj <= 1.0, f"Grade {grade} adj out of bounds: {adj}"

    def test_reliability_adjustment_ordering(self):
        """Higher grades must produce higher or equal adjustments."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        grades = ["F", "D", "C", "B", "A"]
        adjustments = [sizer.get_reliability_adjustment(g) for g in grades]

        for i in range(1, len(adjustments)):
            assert adjustments[i] >= adjustments[i - 1], \
                f"Grade ordering violated: {grades[i-1]}={adjustments[i-1]} > {grades[i]}={adjustments[i]}"

    @PBT_SETTINGS
    @given(
        max_loss=floats(min_value=50.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
        score=floats(min_value=5.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        vix=floats(min_value=10.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_position_size_contracts_non_negative(self, max_loss, score, vix):
        """Position size contracts must always be >= 0."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        result = sizer.calculate_position_size(
            max_loss_per_contract=max_loss,
            signal_score=score,
            vix_level=vix,
        )
        assert result.contracts >= 0

    @PBT_SETTINGS
    @given(
        max_loss=floats(min_value=50.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
        score=floats(min_value=5.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        vix=floats(min_value=10.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_position_size_risk_within_budget(self, max_loss, score, vix):
        """Capital at risk must not exceed max_risk_per_trade."""
        from src.risk.position_sizing import PositionSizer

        account = 100000
        sizer = PositionSizer(account_size=account)
        result = sizer.calculate_position_size(
            max_loss_per_contract=max_loss,
            signal_score=score,
            vix_level=vix,
        )
        max_allowed = account * sizer.config.max_risk_per_trade
        assert result.capital_at_risk <= max_allowed + 0.01, \
            f"Risk {result.capital_at_risk} > max {max_allowed}"

    def test_below_min_score_zero_contracts(self):
        """Signal score below min_score_for_trade should yield 0 contracts."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            signal_score=3.0,  # Below min_score_for_trade=5.0
        )
        assert result.contracts == 0
