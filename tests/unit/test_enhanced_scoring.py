# Tests for Enhanced Scoring (Daily Picks re-ranking)
# ====================================================
"""
Tests cover:
  - Config loading and singleton
  - Liquidity bonus function
  - Credit bonus function
  - Pullback bonus function
  - Stability bonus function
  - Orchestrator (calculate_enhanced_score)
  - EnhancedScoreResult properties and formatting
  - Edge cases (None, 0, negative values)
  - AAPL/MRK/STLD validation scenarios
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
    calculate_enhanced_score,
    calculate_liquidity_bonus,
    calculate_pullback_bonus,
    calculate_stability_bonus,
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


# ===========================================================================
# Liquidity Bonus Tests
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
# Credit Bonus Tests
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
# Pullback Bonus Tests
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
# Stability Bonus Tests
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
# EnhancedScoreResult Tests
# ===========================================================================


class TestEnhancedScoreResult:
    def test_total_bonus(self):
        r = EnhancedScoreResult(
            base_score=6.0,
            liquidity_bonus=2.0,
            credit_bonus=1.0,
            pullback_bonus=0.5,
            stability_bonus=1.0,
        )
        assert r.total_bonus == 4.5
        assert r.enhanced_score == 10.5

    def test_no_bonus(self):
        r = EnhancedScoreResult(base_score=6.0)
        assert r.total_bonus == 0.0
        assert r.enhanced_score == 6.0

    def test_breakdown_str_full(self):
        r = EnhancedScoreResult(
            base_score=6.0,
            liquidity_bonus=2.0,
            credit_bonus=1.0,
            pullback_bonus=0.5,
            stability_bonus=1.0,
        )
        s = r.bonus_breakdown_str()
        assert "Liq+2.0" in s
        assert "Cred+1.0" in s
        assert "Pull+0.5" in s
        assert "Stab+1.0" in s
        assert "= +4.5" in s

    def test_breakdown_str_empty(self):
        r = EnhancedScoreResult(base_score=6.0)
        assert r.bonus_breakdown_str() == "no bonus"

    def test_breakdown_str_partial(self):
        r = EnhancedScoreResult(base_score=6.0, liquidity_bonus=2.0)
        s = r.bonus_breakdown_str()
        assert "Liq+2.0" in s
        assert "Cred" not in s
        assert "= +2.0" in s


# ===========================================================================
# Orchestrator Tests
# ===========================================================================


class TestCalculateEnhancedScore:
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

        assert result.base_score == 6.3
        assert result.liquidity_bonus == 2.0
        assert result.credit_bonus == 1.0  # 8.7% >= 7%
        assert result.pullback_bonus == 1.0
        assert result.stability_bonus == 1.0  # 88 >= 85
        assert result.enhanced_score == pytest.approx(11.3)

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

        assert result.base_score == 9.2
        assert result.liquidity_bonus == 0.0
        assert result.credit_bonus == 0.0
        assert result.pullback_bonus == 0.5  # SMA200 only
        assert result.stability_bonus == 0.0  # 72 < 75
        assert result.enhanced_score == pytest.approx(9.7)

    def test_aapl_beats_mrk(self, config):
        """AAPL enhanced (11.3) should rank above MRK enhanced (9.7)."""
        aapl_pick = _make_pick(
            score=6.3,
            stability_score=88.0,
            liquidity_quality="good",
            estimated_credit=0.435,
            spread_width=5.0,
        )
        aapl_signal = _make_signal("above", "above")
        aapl = calculate_enhanced_score(aapl_pick, aapl_signal, config)

        mrk_pick = _make_pick(
            score=9.2,
            stability_score=72.0,
            liquidity_quality="poor",
            estimated_credit=None,
            spread_width=5.0,
        )
        mrk_signal = _make_signal("below", "above")
        mrk = calculate_enhanced_score(mrk_pick, mrk_signal, config)

        assert aapl.enhanced_score > mrk.enhanced_score

    def test_no_strikes(self, config):
        """Pick without strikes — only stability bonus possible."""
        pick = _make_pick(score=7.0, stability_score=90.0, liquidity_quality=None)
        signal = _make_signal("above", "above")
        result = calculate_enhanced_score(pick, signal, config)

        assert result.liquidity_bonus == 0.0
        assert result.credit_bonus == 0.0
        assert result.pullback_bonus == 1.0
        assert result.stability_bonus == 1.0
        assert result.enhanced_score == 9.0

    def test_no_signal(self, config):
        """Signal is None — pullback bonus defaults to 0."""
        pick = _make_pick(score=7.0, stability_score=85.0)
        result = calculate_enhanced_score(pick, None, config)

        assert result.pullback_bonus == 0.0
        assert result.stability_bonus == 1.0

    def test_signal_no_details(self, config):
        """Signal with details=None."""
        pick = _make_pick(score=7.0, stability_score=60.0)
        signal = MagicMock()
        signal.details = None
        result = calculate_enhanced_score(pick, signal, config)

        assert result.pullback_bonus == 0.0
        assert result.stability_bonus == 0.0
        assert result.enhanced_score == pytest.approx(7.0 + 2.0 + 1.0)  # liq + cred
