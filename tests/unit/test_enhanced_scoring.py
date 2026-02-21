# Tests for Enhanced Scoring (Daily Picks re-ranking)
# ====================================================
"""
Tests cover:
  - Config loading and singleton
  - Additive: Liquidity, Credit, Pullback, Stability bonus functions
  - Multiplicative: Liquidity, Credit, Pullback, Stability mult functions
  - Orchestrator (calculate_enhanced_score) — both modes
  - EnhancedScoreResult properties and formatting
  - Edge cases (None, 0, negative values)
  - Key property: strong signal without bonus > weak signal with max bonus (mult mode)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from src.services.enhanced_scoring import (
    EnhancedScoreResult,
    EnhancedScoringConfig,
    calculate_credit_bonus,
    calculate_credit_mult,
    calculate_enhanced_score,
    calculate_liquidity_bonus,
    calculate_liquidity_mult,
    calculate_pullback_bonus,
    calculate_pullback_mult,
    calculate_stability_bonus,
    calculate_stability_mult,
    get_enhanced_scoring_config,
    reset_enhanced_scoring_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_config():
    """Ensure clean config state between tests."""
    reset_enhanced_scoring_config()
    yield
    reset_enhanced_scoring_config()


@pytest.fixture
def config():
    """Return a fresh config loaded from the real YAML."""
    return EnhancedScoringConfig()


def _make_pick(
    score: float = 6.0,
    stability_score: float = 80.0,
    liquidity_quality: Optional[str] = "good",
    estimated_credit: Optional[float] = 0.45,
    spread_width: Optional[float] = 5.0,
):
    """Create a minimal mock DailyPick."""
    strikes = MagicMock()
    strikes.liquidity_quality = liquidity_quality
    strikes.estimated_credit = estimated_credit
    strikes.spread_width = spread_width

    pick = MagicMock()
    pick.score = score
    pick.stability_score = stability_score
    pick.suggested_strikes = strikes if liquidity_quality is not None else None
    return pick


def _make_signal(vs_sma20: str = "above", vs_sma200: str = "above"):
    """Create a minimal mock TradeSignal with score_breakdown."""
    signal = MagicMock()
    signal.details = {
        "score_breakdown": {
            "components": {
                "moving_averages": {
                    "vs_sma20": vs_sma20,
                    "vs_sma200": vs_sma200,
                }
            }
        }
    }
    return signal


# ===========================================================================
# Config Tests
# ===========================================================================


class TestEnhancedScoringConfig:
    def test_loads_from_yaml(self, config):
        assert config.liquidity_bonus["excellent"] == 2.0
        assert config.liquidity_bonus["poor"] == 0.0

    def test_credit_brackets_ordered(self, config):
        brackets = config.credit_bonus["brackets"]
        assert len(brackets) == 3
        assert brackets[0]["min_pct"] > brackets[1]["min_pct"]

    def test_overfetch_factor(self, config):
        assert config.overfetch_factor == 5

    def test_singleton(self):
        c1 = get_enhanced_scoring_config()
        c2 = get_enhanced_scoring_config()
        assert c1 is c2

    def test_reset_clears_singleton(self):
        c1 = get_enhanced_scoring_config()
        reset_enhanced_scoring_config()
        c2 = get_enhanced_scoring_config()
        assert c1 is not c2

    def test_mode_default_multiplicative(self, config):
        assert config.mode == "multiplicative"

    def test_multiplicative_section_exists(self, config):
        mult = config.multiplicative
        assert "liquidity" in mult
        assert "credit" in mult
        assert "pullback" in mult
        assert "stability" in mult

    def test_multiplicative_liquidity_values(self, config):
        liq = config.multiplicative["liquidity"]
        assert liq["excellent"] == 0.10
        assert liq["good"] == 0.07
        assert liq["fair"] == 0.03
        assert liq["poor"] == 0.0

    def test_multiplicative_credit_brackets(self, config):
        brackets = config.multiplicative["credit"]["brackets"]
        assert len(brackets) == 3
        assert brackets[0]["mult"] == 0.08
        assert brackets[1]["mult"] == 0.05
        assert brackets[2]["mult"] == 0.02


# ===========================================================================
# Additive Liquidity Bonus Tests
# ===========================================================================


class TestLiquidityBonus:
    def test_excellent(self, config):
        assert calculate_liquidity_bonus("excellent", config) == 2.0

    def test_good(self, config):
        assert calculate_liquidity_bonus("good", config) == 2.0

    def test_fair(self, config):
        assert calculate_liquidity_bonus("fair", config) == 1.0

    def test_poor(self, config):
        assert calculate_liquidity_bonus("poor", config) == 0.0

    def test_none(self, config):
        assert calculate_liquidity_bonus(None, config) == 0.0

    def test_case_insensitive(self, config):
        assert calculate_liquidity_bonus("GOOD", config) == 2.0
        assert calculate_liquidity_bonus("Fair", config) == 1.0

    def test_unknown_quality(self, config):
        assert calculate_liquidity_bonus("unknown", config) == 0.0


# ===========================================================================
# Additive Credit Bonus Tests
# ===========================================================================


class TestCreditBonus:
    def test_high_return(self, config):
        # 1.0 / 5.0 = 20% → >= 10% → 1.5
        assert calculate_credit_bonus(1.0, 5.0, config) == 1.5

    def test_medium_return(self, config):
        # 0.40 / 5.0 = 8% → >= 7% → 1.0
        assert calculate_credit_bonus(0.40, 5.0, config) == 1.0

    def test_low_return(self, config):
        # 0.25 / 5.0 = 5% → >= 4% → 0.5
        assert calculate_credit_bonus(0.25, 5.0, config) == 0.5

    def test_very_low_return(self, config):
        # 0.10 / 5.0 = 2% → below all brackets → 0.0
        assert calculate_credit_bonus(0.10, 5.0, config) == 0.0

    def test_none_credit(self, config):
        assert calculate_credit_bonus(None, 5.0, config) == 0.0

    def test_none_width(self, config):
        assert calculate_credit_bonus(0.50, None, config) == 0.0

    def test_zero_width(self, config):
        assert calculate_credit_bonus(0.50, 0.0, config) == 0.0

    def test_negative_width(self, config):
        assert calculate_credit_bonus(0.50, -5.0, config) == 0.0


# ===========================================================================
# Additive Pullback Bonus Tests
# ===========================================================================


class TestPullbackBonus:
    def test_both_above(self, config):
        signal = _make_signal("above", "above")
        assert calculate_pullback_bonus(signal.details, config) == 1.0

    def test_sma200_only(self, config):
        signal = _make_signal("below", "above")
        assert calculate_pullback_bonus(signal.details, config) == 0.5

    def test_neither_above(self, config):
        signal = _make_signal("below", "below")
        assert calculate_pullback_bonus(signal.details, config) == 0.0

    def test_sma20_only(self, config):
        # Above SMA20 but below SMA200 — no bonus
        signal = _make_signal("above", "below")
        assert calculate_pullback_bonus(signal.details, config) == 0.0

    def test_none_details(self, config):
        assert calculate_pullback_bonus(None, config) == 0.0

    def test_no_score_breakdown(self, config):
        assert calculate_pullback_bonus({"foo": "bar"}, config) == 0.0

    def test_no_components(self, config):
        details = {"score_breakdown": {"total_score": 5}}
        assert calculate_pullback_bonus(details, config) == 0.0

    def test_no_moving_averages(self, config):
        details = {"score_breakdown": {"components": {"rsi": {}}}}
        assert calculate_pullback_bonus(details, config) == 0.0


# ===========================================================================
# Additive Stability Bonus Tests
# ===========================================================================


class TestStabilityBonus:
    def test_very_high(self, config):
        assert calculate_stability_bonus(90.0, config) == 1.0

    def test_high(self, config):
        assert calculate_stability_bonus(85.0, config) == 1.0

    def test_medium_high(self, config):
        assert calculate_stability_bonus(80.0, config) == 0.5

    def test_at_threshold(self, config):
        assert calculate_stability_bonus(75.0, config) == 0.5

    def test_below_threshold(self, config):
        assert calculate_stability_bonus(70.0, config) == 0.0

    def test_zero(self, config):
        assert calculate_stability_bonus(0.0, config) == 0.0

    def test_none(self, config):
        assert calculate_stability_bonus(None, config) == 0.0


# ===========================================================================
# EnhancedScoreResult Tests (Additive)
# ===========================================================================


class TestEnhancedScoreResult:
    def test_total_bonus(self):
        r = EnhancedScoreResult(
            base_score=6.0,
            liquidity_bonus=2.0,
            credit_bonus=1.0,
            pullback_bonus=0.5,
            stability_bonus=1.0,
            mode="additive",
        )
        assert r.total_bonus == 4.5
        assert r.enhanced_score == 10.5

    def test_no_bonus(self):
        r = EnhancedScoreResult(base_score=6.0, mode="additive")
        assert r.total_bonus == 0.0
        assert r.enhanced_score == 6.0

    def test_breakdown_str_full(self):
        r = EnhancedScoreResult(
            base_score=6.0,
            liquidity_bonus=2.0,
            credit_bonus=1.0,
            pullback_bonus=0.5,
            stability_bonus=1.0,
            mode="additive",
        )
        s = r.bonus_breakdown_str()
        assert "Liq+2.0" in s
        assert "Cred+1.0" in s
        assert "Pull+0.5" in s
        assert "Stab+1.0" in s
        assert "= +4.5" in s

    def test_breakdown_str_empty(self):
        r = EnhancedScoreResult(base_score=6.0, mode="additive")
        assert r.bonus_breakdown_str() == "no bonus"

    def test_breakdown_str_partial(self):
        r = EnhancedScoreResult(base_score=6.0, liquidity_bonus=2.0, mode="additive")
        s = r.bonus_breakdown_str()
        assert "Liq+2.0" in s
        assert "Cred" not in s
        assert "= +2.0" in s


# ===========================================================================
# EnhancedScoreResult Tests (Multiplicative)
# ===========================================================================


class TestEnhancedScoreResultMultiplicative:
    def test_bonus_factor(self):
        r = EnhancedScoreResult(
            base_score=7.0,
            liquidity_bonus=0.10,
            credit_bonus=0.08,
            pullback_bonus=0.05,
            stability_bonus=0.05,
            mode="multiplicative",
        )
        assert r.bonus_factor == pytest.approx(1.28)
        assert r.enhanced_score == pytest.approx(7.0 * 1.28)

    def test_no_bonus_factor_is_one(self):
        r = EnhancedScoreResult(base_score=7.0, mode="multiplicative")
        assert r.bonus_factor == 1.0
        assert r.enhanced_score == 7.0

    def test_breakdown_str_multiplicative(self):
        r = EnhancedScoreResult(
            base_score=7.0,
            liquidity_bonus=0.10,
            credit_bonus=0.08,
            stability_bonus=0.05,
            mode="multiplicative",
        )
        s = r.bonus_breakdown_str()
        assert "\u00d71.23" in s
        assert "Liq+10%" in s
        assert "Cred+8%" in s
        assert "Stab+5%" in s
        assert "Pull" not in s

    def test_breakdown_str_empty_multiplicative(self):
        r = EnhancedScoreResult(base_score=7.0, mode="multiplicative")
        assert r.bonus_breakdown_str() == "no bonus"

    def test_enhanced_score_preserves_ordering(self):
        """Strong signal (8.0) without bonuses > weak signal (4.0) with max bonuses."""
        strong = EnhancedScoreResult(base_score=8.0, mode="multiplicative")
        weak = EnhancedScoreResult(
            base_score=4.0,
            liquidity_bonus=0.10,
            credit_bonus=0.08,
            pullback_bonus=0.05,
            stability_bonus=0.05,
            mode="multiplicative",
        )
        # weak: 4.0 × 1.28 = 5.12
        assert weak.enhanced_score == pytest.approx(5.12)
        # strong: 8.0 × 1.0 = 8.0
        assert strong.enhanced_score == 8.0
        assert strong.enhanced_score > weak.enhanced_score


# ===========================================================================
# Multiplicative Scoring Function Tests
# ===========================================================================


class TestLiquidityMult:
    def test_excellent(self, config):
        assert calculate_liquidity_mult("excellent", config) == 0.10

    def test_good(self, config):
        assert calculate_liquidity_mult("good", config) == 0.07

    def test_fair(self, config):
        assert calculate_liquidity_mult("fair", config) == 0.03

    def test_poor(self, config):
        assert calculate_liquidity_mult("poor", config) == 0.0

    def test_none(self, config):
        assert calculate_liquidity_mult(None, config) == 0.0

    def test_case_insensitive(self, config):
        assert calculate_liquidity_mult("EXCELLENT", config) == 0.10
        assert calculate_liquidity_mult("Good", config) == 0.07

    def test_unknown_quality(self, config):
        assert calculate_liquidity_mult("unknown", config) == 0.0


class TestCreditMult:
    def test_high_return(self, config):
        # 1.0 / 5.0 = 20% → >= 10% → 0.08
        assert calculate_credit_mult(1.0, 5.0, config) == 0.08

    def test_medium_return(self, config):
        # 0.40 / 5.0 = 8% → >= 7% → 0.05
        assert calculate_credit_mult(0.40, 5.0, config) == 0.05

    def test_low_return(self, config):
        # 0.25 / 5.0 = 5% → >= 4% → 0.02
        assert calculate_credit_mult(0.25, 5.0, config) == 0.02

    def test_very_low_return(self, config):
        # 0.10 / 5.0 = 2% → below all → 0.0
        assert calculate_credit_mult(0.10, 5.0, config) == 0.0

    def test_none_credit(self, config):
        assert calculate_credit_mult(None, 5.0, config) == 0.0

    def test_none_width(self, config):
        assert calculate_credit_mult(0.50, None, config) == 0.0

    def test_zero_width(self, config):
        assert calculate_credit_mult(0.50, 0.0, config) == 0.0


class TestPullbackMult:
    def test_both_above(self, config):
        signal = _make_signal("above", "above")
        assert calculate_pullback_mult(signal.details, config) == 0.05

    def test_sma200_only(self, config):
        signal = _make_signal("below", "above")
        assert calculate_pullback_mult(signal.details, config) == 0.025

    def test_neither_above(self, config):
        signal = _make_signal("below", "below")
        assert calculate_pullback_mult(signal.details, config) == 0.0

    def test_sma20_only(self, config):
        signal = _make_signal("above", "below")
        assert calculate_pullback_mult(signal.details, config) == 0.0

    def test_none_details(self, config):
        assert calculate_pullback_mult(None, config) == 0.0

    def test_no_score_breakdown(self, config):
        assert calculate_pullback_mult({"foo": "bar"}, config) == 0.0

    def test_no_components(self, config):
        details = {"score_breakdown": {"total_score": 5}}
        assert calculate_pullback_mult(details, config) == 0.0

    def test_no_moving_averages(self, config):
        details = {"score_breakdown": {"components": {"rsi": {}}}}
        assert calculate_pullback_mult(details, config) == 0.0


class TestStabilityMult:
    def test_very_high(self, config):
        assert calculate_stability_mult(90.0, config) == 0.05

    def test_high(self, config):
        assert calculate_stability_mult(85.0, config) == 0.05

    def test_medium_high(self, config):
        assert calculate_stability_mult(80.0, config) == 0.025

    def test_at_threshold(self, config):
        assert calculate_stability_mult(75.0, config) == 0.025

    def test_below_threshold(self, config):
        assert calculate_stability_mult(70.0, config) == 0.0

    def test_zero(self, config):
        assert calculate_stability_mult(0.0, config) == 0.0

    def test_none(self, config):
        assert calculate_stability_mult(None, config) == 0.0


# ===========================================================================
# Orchestrator Tests (Additive — legacy)
# ===========================================================================


class TestCalculateEnhancedScoreAdditive:
    """Tests for additive mode — verifies backward compatibility."""

    @pytest.fixture(autouse=True)
    def _force_additive(self, config):
        """Force additive mode for these tests."""
        config._data["mode"] = "additive"
        self._config = config

    def test_aapl_scenario(self):
        """AAPL: score 6.3, GOOD liquidity, ~8.7% return, above both SMAs, stability 88."""
        pick = _make_pick(
            score=6.3,
            stability_score=88.0,
            liquidity_quality="good",
            estimated_credit=0.435,
            spread_width=5.0,
        )
        signal = _make_signal("above", "above")
        result = calculate_enhanced_score(pick, signal, self._config)

        assert result.mode == "additive"
        assert result.base_score == 6.3
        assert result.liquidity_bonus == 2.0
        assert result.credit_bonus == 1.0  # 8.7% >= 7%
        assert result.pullback_bonus == 1.0
        assert result.stability_bonus == 1.0  # 88 >= 85
        assert result.enhanced_score == pytest.approx(11.3)

    def test_mrk_scenario(self):
        """MRK: score 9.2, POOR liquidity, no credit, below SMA20, stability 72."""
        pick = _make_pick(
            score=9.2,
            stability_score=72.0,
            liquidity_quality="poor",
            estimated_credit=None,
            spread_width=5.0,
        )
        signal = _make_signal("below", "above")
        result = calculate_enhanced_score(pick, signal, self._config)

        assert result.mode == "additive"
        assert result.base_score == 9.2
        assert result.liquidity_bonus == 0.0
        assert result.credit_bonus == 0.0
        assert result.pullback_bonus == 0.5  # SMA200 only
        assert result.stability_bonus == 0.0  # 72 < 75
        assert result.enhanced_score == pytest.approx(9.7)

    def test_aapl_beats_mrk_additive(self):
        """In additive mode, AAPL enhanced (11.3) > MRK enhanced (9.7)."""
        aapl_pick = _make_pick(
            score=6.3,
            stability_score=88.0,
            liquidity_quality="good",
            estimated_credit=0.435,
            spread_width=5.0,
        )
        aapl_signal = _make_signal("above", "above")
        aapl = calculate_enhanced_score(aapl_pick, aapl_signal, self._config)

        mrk_pick = _make_pick(
            score=9.2,
            stability_score=72.0,
            liquidity_quality="poor",
            estimated_credit=None,
            spread_width=5.0,
        )
        mrk_signal = _make_signal("below", "above")
        mrk = calculate_enhanced_score(mrk_pick, mrk_signal, self._config)

        assert aapl.enhanced_score > mrk.enhanced_score

    def test_no_strikes(self):
        """Pick without strikes — only stability bonus possible."""
        pick = _make_pick(score=7.0, stability_score=90.0, liquidity_quality=None)
        signal = _make_signal("above", "above")
        result = calculate_enhanced_score(pick, signal, self._config)

        assert result.liquidity_bonus == 0.0
        assert result.credit_bonus == 0.0
        assert result.pullback_bonus == 1.0
        assert result.stability_bonus == 1.0
        assert result.enhanced_score == 9.0

    def test_no_signal(self):
        """Signal is None — pullback bonus defaults to 0."""
        pick = _make_pick(score=7.0, stability_score=85.0)
        result = calculate_enhanced_score(pick, None, self._config)

        assert result.pullback_bonus == 0.0
        assert result.stability_bonus == 1.0

    def test_signal_no_details(self):
        """Signal with details=None."""
        pick = _make_pick(score=7.0, stability_score=60.0)
        signal = MagicMock()
        signal.details = None
        result = calculate_enhanced_score(pick, signal, self._config)

        assert result.pullback_bonus == 0.0
        assert result.stability_bonus == 0.0
        assert result.enhanced_score == pytest.approx(7.0 + 2.0 + 1.0)  # liq + cred


# ===========================================================================
# Orchestrator Tests (Multiplicative — default)
# ===========================================================================


class TestCalculateEnhancedScoreMultiplicative:
    """Tests for multiplicative mode (default)."""

    def test_aapl_scenario(self, config):
        """AAPL: score 6.3, GOOD liquidity, ~8.7% return, above both SMAs, stability 88."""
        pick = _make_pick(
            score=6.3,
            stability_score=88.0,
            liquidity_quality="good",
            estimated_credit=0.435,
            spread_width=5.0,
        )
        signal = _make_signal("above", "above")
        result = calculate_enhanced_score(pick, signal, config)

        assert result.mode == "multiplicative"
        assert result.base_score == 6.3
        assert result.liquidity_bonus == 0.07  # good
        assert result.credit_bonus == 0.05  # 8.7% >= 7%
        assert result.pullback_bonus == 0.05  # both above
        assert result.stability_bonus == 0.05  # 88 >= 85
        # factor = 1.0 + 0.07 + 0.05 + 0.05 + 0.05 = 1.22
        assert result.bonus_factor == pytest.approx(1.22)
        assert result.enhanced_score == pytest.approx(6.3 * 1.22)

    def test_mrk_scenario(self, config):
        """MRK: score 9.2, POOR liquidity, no credit, below SMA20, stability 72."""
        pick = _make_pick(
            score=9.2,
            stability_score=72.0,
            liquidity_quality="poor",
            estimated_credit=None,
            spread_width=5.0,
        )
        signal = _make_signal("below", "above")
        result = calculate_enhanced_score(pick, signal, config)

        assert result.mode == "multiplicative"
        assert result.liquidity_bonus == 0.0  # poor
        assert result.credit_bonus == 0.0
        assert result.pullback_bonus == 0.025  # SMA200 only
        assert result.stability_bonus == 0.0  # 72 < 75
        assert result.bonus_factor == pytest.approx(1.025)
        assert result.enhanced_score == pytest.approx(9.2 * 1.025)

    def test_mrk_beats_aapl_multiplicative(self, config):
        """In multiplicative mode, MRK (9.2×1.025=9.43) > AAPL (6.3×1.22=7.69)."""
        aapl_pick = _make_pick(
            score=6.3,
            stability_score=88.0,
            liquidity_quality="good",
            estimated_credit=0.435,
            spread_width=5.0,
        )
        aapl = calculate_enhanced_score(aapl_pick, _make_signal("above", "above"), config)

        mrk_pick = _make_pick(
            score=9.2,
            stability_score=72.0,
            liquidity_quality="poor",
            estimated_credit=None,
            spread_width=5.0,
        )
        mrk = calculate_enhanced_score(mrk_pick, _make_signal("below", "above"), config)

        # Key: In multiplicative mode, higher base signal wins
        assert mrk.enhanced_score > aapl.enhanced_score

    def test_strong_signal_beats_weak_with_max_bonuses(self, config):
        """Key property: 8.0 base without bonuses > 4.0 base with max bonuses."""
        strong_pick = _make_pick(
            score=8.0,
            stability_score=60.0,
            liquidity_quality="poor",
            estimated_credit=None,
            spread_width=None,
        )
        strong = calculate_enhanced_score(strong_pick, None, config)

        weak_pick = _make_pick(
            score=4.0,
            stability_score=90.0,
            liquidity_quality="excellent",
            estimated_credit=1.0,
            spread_width=5.0,  # 20% return
        )
        weak = calculate_enhanced_score(weak_pick, _make_signal("above", "above"), config)

        # weak: 4.0 × (1 + 0.10 + 0.08 + 0.05 + 0.05) = 4.0 × 1.28 = 5.12
        assert weak.enhanced_score == pytest.approx(5.12)
        # strong: 8.0 × 1.0 = 8.0
        assert strong.enhanced_score == 8.0
        assert strong.enhanced_score > weak.enhanced_score

    def test_no_strikes(self, config):
        """Pick without strikes — only pullback + stability mult possible."""
        pick = _make_pick(score=7.0, stability_score=90.0, liquidity_quality=None)
        signal = _make_signal("above", "above")
        result = calculate_enhanced_score(pick, signal, config)

        assert result.liquidity_bonus == 0.0
        assert result.credit_bonus == 0.0
        assert result.pullback_bonus == 0.05
        assert result.stability_bonus == 0.05
        # 7.0 × 1.10 = 7.7
        assert result.enhanced_score == pytest.approx(7.0 * 1.10)

    def test_no_signal(self, config):
        """Signal is None — pullback mult defaults to 0."""
        pick = _make_pick(score=7.0, stability_score=85.0)
        result = calculate_enhanced_score(pick, None, config)

        assert result.pullback_bonus == 0.0
        assert result.stability_bonus == 0.05

    def test_max_factor(self, config):
        """All bonuses at max → factor = 1.28."""
        pick = _make_pick(
            score=10.0,
            stability_score=90.0,
            liquidity_quality="excellent",
            estimated_credit=1.0,
            spread_width=5.0,  # 20%
        )
        signal = _make_signal("above", "above")
        result = calculate_enhanced_score(pick, signal, config)

        assert result.bonus_factor == pytest.approx(1.28)
        assert result.enhanced_score == pytest.approx(12.8)


# ===========================================================================
# Mode Switch Tests
# ===========================================================================


class TestModeSwitch:
    def test_mode_switch_changes_behavior(self, config):
        """Switching mode changes which scoring functions are used."""
        pick = _make_pick(score=7.0, stability_score=90.0)
        signal = _make_signal("above", "above")

        # Default: multiplicative
        result_mult = calculate_enhanced_score(pick, signal, config)
        assert result_mult.mode == "multiplicative"

        # Switch to additive
        config._data["mode"] = "additive"
        result_add = calculate_enhanced_score(pick, signal, config)
        assert result_add.mode == "additive"

        # Additive gives much larger bonus values
        assert result_add.liquidity_bonus > result_mult.liquidity_bonus
        # But multiplicative applies them proportionally
        assert result_mult.enhanced_score < result_add.enhanced_score
