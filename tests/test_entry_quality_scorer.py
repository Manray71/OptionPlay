"""
Tests for EntryQualityScorer.

Tests the 7-factor EQS calculation with known inputs.
"""

import pytest
from src.services.entry_quality_scorer import (
    EntryQualityScorer,
    EntryQuality,
    get_entry_scorer,
    reset_entry_scorer,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before each test."""
    reset_entry_scorer()
    yield
    reset_entry_scorer()


@pytest.fixture
def scorer():
    return EntryQualityScorer()


# =============================================================================
# TESTS: Full Score Calculation
# =============================================================================

class TestFullScore:
    """Test full EQS calculation with known inputs."""

    def test_ideal_entry_high_score(self, scorer):
        """Ideal entry conditions → high EQS."""
        eq = scorer.score(
            iv_rank=55,          # Sweet spot (40-65)
            iv_percentile=68,    # Good (50-80)
            credit_pct=18.5,     # Well above 10% min
            spread_theta=0.042,
            credit_bid=1.85,
            pullback_pct=-4.2,   # Sweet spot (3-8%)
            rsi=32,              # Oversold
            trend_bullish=True,
        )
        assert 0 <= eq.eqs_total <= 100
        assert eq.eqs_total >= 65  # Should be a good score
        assert eq.eqs_normalized >= 0.65

    def test_poor_entry_low_score(self, scorer):
        """Poor entry conditions → low EQS."""
        eq = scorer.score(
            iv_rank=10,          # Too low — minimal premium
            iv_percentile=15,    # Low — IV usually higher
            credit_pct=8,        # Below 10% minimum
            spread_theta=0.005,
            credit_bid=0.40,
            pullback_pct=-0.5,   # No real pullback
            rsi=75,              # Overbought
            trend_bullish=False,
        )
        assert eq.eqs_total < 40
        assert eq.eqs_normalized < 0.40

    def test_all_none_returns_neutral(self, scorer):
        """All None inputs → neutral score (~50)."""
        eq = scorer.score()
        # iv_rank=None→50, iv_pctl=None→50, credit=None→0,
        # theta=None→50, pullback=None→50, rsi=None→50, trend=False→30
        # 50*0.20 + 50*0.15 + 0*0.20 + 50*0.15 + 50*0.15 + 50*0.10 + 30*0.05
        # = 10 + 7.5 + 0 + 7.5 + 7.5 + 5.0 + 1.5 = 39.0
        assert 35 <= eq.eqs_total <= 45
        assert eq.eqs_normalized == eq.eqs_total / 100

    def test_score_range_0_100(self, scorer):
        """EQS should always be between 0 and 100."""
        # Test with extreme values
        eq = scorer.score(
            iv_rank=100, iv_percentile=100, credit_pct=50,
            spread_theta=1.0, credit_bid=0.5,
            pullback_pct=-20, rsi=5, trend_bullish=True,
        )
        assert 0 <= eq.eqs_total <= 100

    def test_normalized_matches_total(self, scorer):
        """eqs_normalized should be eqs_total / 100."""
        eq = scorer.score(iv_rank=50, iv_percentile=60, credit_pct=20)
        assert abs(eq.eqs_normalized - eq.eqs_total / 100) < 0.01

    def test_weights_sum_to_one(self, scorer):
        """Factor weights must sum to 1.0."""
        total = sum(scorer.WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_to_dict_structure(self, scorer):
        """to_dict returns proper structure."""
        eq = scorer.score(iv_rank=55, credit_pct=18.5)
        d = eq.to_dict()
        assert 'eqs_total' in d
        assert 'eqs_normalized' in d
        assert 'factors' in d
        assert 'raw' in d
        assert 'iv_rank' in d['factors']
        assert 'credit_ratio' in d['factors']
        assert len(d['factors']) == 7


# =============================================================================
# TESTS: Individual Factors — IV Rank
# =============================================================================

class TestIVRankScore:
    """Test IV Rank scoring function."""

    def test_none_returns_50(self, scorer):
        assert scorer._score_iv_rank(None) == 50.0

    def test_zero_returns_zero(self, scorer):
        assert scorer._score_iv_rank(0) == 0.0

    def test_low_iv_rank_low_score(self, scorer):
        """IV Rank 10% → low score (25)."""
        score = scorer._score_iv_rank(10)
        assert score == 25.0

    def test_sweet_spot_40(self, scorer):
        """IV Rank 40% → start of sweet spot (80)."""
        score = scorer._score_iv_rank(40)
        assert score == 80.0

    def test_sweet_spot_65(self, scorer):
        """IV Rank 65% → end of sweet spot (100)."""
        score = scorer._score_iv_rank(65)
        assert score == 100.0

    def test_high_iv_rank_decreasing(self, scorer):
        """IV Rank 80% → lower than sweet spot."""
        score = scorer._score_iv_rank(80)
        assert score < 100  # Should decrease from sweet spot
        assert score >= 75

    def test_very_high_iv_rank_warning(self, scorer):
        """IV Rank 95% → event risk warning, lower score."""
        score = scorer._score_iv_rank(95)
        assert score < 70
        assert score >= 30  # Min is 30


# =============================================================================
# TESTS: Individual Factors — IV Percentile
# =============================================================================

class TestIVPercentileScore:
    """Test IV Percentile scoring function."""

    def test_none_returns_50(self, scorer):
        assert scorer._score_iv_percentile(None) == 50.0

    def test_low_percentile_low_score(self, scorer):
        """Percentile 10% → low score."""
        score = scorer._score_iv_percentile(10)
        assert score == 10.0

    def test_ideal_percentile_70(self, scorer):
        """Percentile 70% → high score (in sweet spot)."""
        score = scorer._score_iv_percentile(70)
        assert score >= 85

    def test_percentile_80_is_max(self, scorer):
        """Percentile 80% → peak score (100)."""
        score = scorer._score_iv_percentile(80)
        assert score == 100.0

    def test_very_high_percentile_decreases(self, scorer):
        """Percentile 95% → decreases from peak."""
        score = scorer._score_iv_percentile(95)
        assert score < 100
        assert score >= 50  # Min is 50


# =============================================================================
# TESTS: Individual Factors — Credit Ratio
# =============================================================================

class TestCreditRatioScore:
    """Test Credit Ratio scoring function."""

    def test_none_returns_zero(self, scorer):
        assert scorer._score_credit_ratio(None) == 0.0

    def test_below_minimum_returns_zero(self, scorer):
        """Credit < 10% → 0 (below PLAYBOOK minimum)."""
        assert scorer._score_credit_ratio(8.0) == 0.0
        assert scorer._score_credit_ratio(5.0) == 0.0

    def test_at_minimum_returns_zero(self, scorer):
        """Credit exactly 10% → just at threshold."""
        score = scorer._score_credit_ratio(10.0)
        assert score == 0.0

    def test_15_percent_returns_60(self, scorer):
        """Credit 15% → 60."""
        score = scorer._score_credit_ratio(15.0)
        assert score == 60.0

    def test_25_percent_capped(self, scorer):
        """Credit 25% → 100 (capped)."""
        score = scorer._score_credit_ratio(25.0)
        assert score == 100.0

    def test_above_25_stays_capped(self, scorer):
        """Credit 35% → still 100."""
        score = scorer._score_credit_ratio(35.0)
        assert score == 100.0

    def test_18_5_percent(self, scorer):
        """Credit 18.5% → between 60 and 100."""
        score = scorer._score_credit_ratio(18.5)
        assert 60 < score < 100


# =============================================================================
# TESTS: Individual Factors — Theta Efficiency
# =============================================================================

class TestThetaEfficiencyScore:
    """Test Theta Efficiency scoring function."""

    def test_none_theta_returns_neutral(self, scorer):
        assert scorer._score_theta_efficiency(None, 1.85) == 50.0

    def test_none_credit_returns_neutral(self, scorer):
        assert scorer._score_theta_efficiency(0.042, None) == 50.0

    def test_zero_credit_returns_neutral(self, scorer):
        assert scorer._score_theta_efficiency(0.042, 0.0) == 50.0

    def test_typical_ratio(self, scorer):
        """Typical theta/credit ratio (~2-3%)."""
        score = scorer._score_theta_efficiency(0.042, 1.85)
        # 0.042 / 1.85 * 100 = 2.27%
        # 2.27 * 25 = 56.75
        assert 50 < score < 70

    def test_high_ratio_capped(self, scorer):
        """Very high theta/credit ratio → capped at 100."""
        score = scorer._score_theta_efficiency(0.50, 1.00)
        # 50% ratio → 50 * 25 = 1250 → capped at 100
        assert score == 100.0


# =============================================================================
# TESTS: Individual Factors — Pullback
# =============================================================================

class TestPullbackScore:
    """Test Pullback scoring function."""

    def test_none_returns_neutral(self, scorer):
        assert scorer._score_pullback(None) == 50.0

    def test_no_pullback_low_score(self, scorer):
        """< 1% pullback → low score (20)."""
        assert scorer._score_pullback(-0.5) == 20.0

    def test_small_pullback(self, scorer):
        """2% pullback → moderate score."""
        score = scorer._score_pullback(-2.0)
        assert 30 < score < 60

    def test_sweet_spot_5_percent(self, scorer):
        """5% pullback → sweet spot (high score)."""
        score = scorer._score_pullback(-5.0)
        assert score >= 70

    def test_sweet_spot_8_percent(self, scorer):
        """8% pullback → peak of sweet spot (100)."""
        score = scorer._score_pullback(-8.0)
        assert score == 100.0

    def test_deep_pullback_10_percent(self, scorer):
        """10% pullback → decreasing score."""
        score = scorer._score_pullback(-10.0)
        assert score < 100
        assert score >= 60

    def test_too_deep_pullback(self, scorer):
        """15% pullback → warning (low score)."""
        score = scorer._score_pullback(-15.0)
        assert score == 30.0


# =============================================================================
# TESTS: Individual Factors — RSI
# =============================================================================

class TestRSIScore:
    """Test RSI scoring function."""

    def test_none_returns_neutral(self, scorer):
        assert scorer._score_rsi(None) == 50.0

    def test_strongly_oversold(self, scorer):
        """RSI 20 → max score (100)."""
        assert scorer._score_rsi(20) == 100.0

    def test_oversold(self, scorer):
        """RSI 30 → good score (> 70)."""
        score = scorer._score_rsi(30)
        assert score > 70

    def test_neutral(self, scorer):
        """RSI 45 → moderate score."""
        score = scorer._score_rsi(45)
        assert 40 <= score <= 60

    def test_neutral_range(self, scorer):
        """RSI 55 → neutral (40)."""
        score = scorer._score_rsi(55)
        assert score == 40.0

    def test_overbought(self, scorer):
        """RSI 75 → low score (20)."""
        score = scorer._score_rsi(75)
        assert score == 20.0


# =============================================================================
# TESTS: Individual Factors — Trend
# =============================================================================

class TestTrendScore:
    """Test Trend scoring function."""

    def test_bullish_100(self, scorer):
        eq = scorer.score(trend_bullish=True)
        assert eq.trend_score == 100.0

    def test_bearish_30(self, scorer):
        eq = scorer.score(trend_bullish=False)
        assert eq.trend_score == 30.0


# =============================================================================
# TESTS: EQS Bonus
# =============================================================================

class TestEQSBonus:
    """Test apply_eqs_bonus method."""

    def test_bonus_increases_score(self, scorer):
        """EQS bonus should increase the signal score."""
        eq = scorer.score(
            iv_rank=55, iv_percentile=68, credit_pct=18.5,
            spread_theta=0.042, credit_bid=1.85,
            pullback_pct=-4.2, rsi=32, trend_bullish=True,
        )
        signal_score = 7.5
        ranking_score = scorer.apply_eqs_bonus(signal_score, eq)

        assert ranking_score > signal_score
        assert ranking_score <= signal_score * 1.3  # Max 30% bonus

    def test_bonus_max_30_percent(self, scorer):
        """Even with perfect EQS, bonus is capped at 30%."""
        eq = EntryQuality(
            eqs_total=100, eqs_normalized=1.0,
            iv_rank_score=100, iv_percentile_score=100,
            credit_ratio_score=100, theta_efficiency_score=100,
            pullback_score=100, rsi_score=100, trend_score=100,
            iv_rank=55, iv_percentile=70, credit_pct=25,
            theta_per_day=0.1, pullback_pct=-5, rsi=25,
        )
        ranking = scorer.apply_eqs_bonus(10.0, eq, max_bonus_pct=0.3)
        assert ranking == 13.0

    def test_bonus_zero_with_zero_eqs(self, scorer):
        """Zero EQS → no bonus."""
        eq = EntryQuality(
            eqs_total=0, eqs_normalized=0.0,
            iv_rank_score=0, iv_percentile_score=0,
            credit_ratio_score=0, theta_efficiency_score=0,
            pullback_score=0, rsi_score=0, trend_score=0,
            iv_rank=None, iv_percentile=None, credit_pct=None,
            theta_per_day=None, pullback_pct=None, rsi=None,
        )
        ranking = scorer.apply_eqs_bonus(8.0, eq)
        assert ranking == 8.0

    def test_custom_max_bonus(self, scorer):
        """Custom max bonus percentage."""
        eq = EntryQuality(
            eqs_total=100, eqs_normalized=1.0,
            iv_rank_score=100, iv_percentile_score=100,
            credit_ratio_score=100, theta_efficiency_score=100,
            pullback_score=100, rsi_score=100, trend_score=100,
            iv_rank=55, iv_percentile=70, credit_pct=25,
            theta_per_day=0.1, pullback_pct=-5, rsi=25,
        )
        ranking = scorer.apply_eqs_bonus(10.0, eq, max_bonus_pct=0.5)
        assert ranking == 15.0


# =============================================================================
# TESTS: Acceptance Criteria from TASKS
# =============================================================================

class TestAcceptanceCriteria:
    """
    Test acceptance criteria from TASKS_DAILY_PICKS_V2.md.

    scorer.score(
        iv_rank=55, iv_percentile=68,
        credit_pct=18.5, spread_theta=0.042, credit_bid=1.85,
        pullback_pct=-4.2, rsi=32, trend_bullish=True
    )
    assert 0 <= eq.eqs_total <= 100
    assert eq.iv_percentile_score > 50   # Percentile 68% is good
    assert eq.rsi_score > 70             # RSI 32 is oversold → good
    assert eq.credit_ratio_score > 60    # 18.5% is well above 10%
    """

    def test_acceptance_criteria(self, scorer):
        eq = scorer.score(
            iv_rank=55, iv_percentile=68,
            credit_pct=18.5, spread_theta=0.042, credit_bid=1.85,
            pullback_pct=-4.2, rsi=32, trend_bullish=True,
        )
        assert 0 <= eq.eqs_total <= 100
        assert eq.iv_percentile_score > 50    # Percentile 68% is good
        assert eq.rsi_score > 70               # RSI 32 is oversold → good
        assert eq.credit_ratio_score > 60      # 18.5% is well above 10%


# =============================================================================
# TESTS: Singleton
# =============================================================================

class TestSingleton:
    """Test singleton pattern."""

    def test_get_entry_scorer_same_instance(self):
        s1 = get_entry_scorer()
        s2 = get_entry_scorer()
        assert s1 is s2

    def test_reset_clears_singleton(self):
        s1 = get_entry_scorer()
        reset_entry_scorer()
        s2 = get_entry_scorer()
        assert s1 is not s2
