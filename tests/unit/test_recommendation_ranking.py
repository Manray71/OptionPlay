#!/usr/bin/env python3
"""
F.3: Tests for RecommendationRankingMixin (src/services/recommendation_ranking.py)

Tests the speed scoring and signal ranking logic:
- compute_speed_score: DTE, stability, sector, pullback, market context
- _rank_signals: combined scoring with speed multiplier

Usage:
    pytest tests/unit/test_recommendation_ranking.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from src.services.recommendation_ranking import (
    RecommendationRankingMixin,
    SPEED_DTE_OPTIMAL,
    SPEED_SCORE_MAX,
    RANKING_STABILITY_WEIGHT,
    _SIGNAL_TYPE_BONUS,
    _STRATEGY_CAPS,
    _STRATEGY_CAP_DEFAULT,
    _MIN_STRATEGIES_IN_PICKS,
)
from src.models.base import TradeSignal, SignalType, SignalStrength


# =============================================================================
# FIXTURES — Create a concrete class from the mixin
# =============================================================================

class ConcreteRanker(RecommendationRankingMixin):
    """Concrete class to test the mixin methods."""

    def __init__(self, config=None, sector_factors=None, fundamentals_manager=None):
        self.config = config or {
            'stability_weight': RANKING_STABILITY_WEIGHT,
            'speed_exponent': 0.3,
            'enable_strike_recommendations': False,
        }
        self._sector_factors = sector_factors or {}
        self._fundamentals_manager = fundamentals_manager
        self._strike_recommender = None


@pytest.fixture
def ranker():
    """Returns a RecommendationRankingMixin instance."""
    return ConcreteRanker()


def _make_signal(symbol, score, strategy="pullback", price=100.0, details=None):
    """Helper to create a TradeSignal for testing."""
    return TradeSignal(
        symbol=symbol,
        strategy=strategy,
        signal_type=SignalType.LONG,
        strength=SignalStrength.MODERATE,
        score=score,
        current_price=price,
        reason=f"Test signal for {symbol}",
        details=details or {},
    )


# =============================================================================
# SPEED SCORE
# =============================================================================

class TestComputeSpeedScore:
    """Tests for compute_speed_score()"""

    def test_optimal_dte(self, ranker):
        """DTE exactly at optimal (60) → max DTE component."""
        score = ranker.compute_speed_score(
            dte=SPEED_DTE_OPTIMAL, stability_score=70, sector=None,
        )
        assert score > 0

    def test_high_dte_lower_speed(self, ranker):
        """DTE far from optimal → lower speed score."""
        score_optimal = ranker.compute_speed_score(
            dte=60, stability_score=80, sector="Utilities",
        )
        score_high_dte = ranker.compute_speed_score(
            dte=120, stability_score=80, sector="Utilities",
        )
        assert score_optimal >= score_high_dte

    def test_stability_increases_speed(self, ranker):
        """Higher stability → higher speed score."""
        score_low = ranker.compute_speed_score(
            dte=60, stability_score=50, sector=None,
        )
        score_high = ranker.compute_speed_score(
            dte=60, stability_score=95, sector=None,
        )
        assert score_high > score_low

    def test_defensive_sector_faster(self, ranker):
        """Utilities (defensive) should score higher than Technology."""
        score_util = ranker.compute_speed_score(
            dte=60, stability_score=80, sector="Utilities",
        )
        score_tech = ranker.compute_speed_score(
            dte=60, stability_score=80, sector="Technology",
        )
        assert score_util > score_tech

    def test_pullback_score_bonus(self, ranker):
        """Higher pullback score → higher speed."""
        score_no_pb = ranker.compute_speed_score(
            dte=60, stability_score=80, sector=None,
        )
        score_pb = ranker.compute_speed_score(
            dte=60, stability_score=80, sector=None, pullback_score=8.0,
        )
        assert score_pb > score_no_pb

    def test_market_context_bonus(self, ranker):
        """Positive market context → higher speed."""
        score_no_mc = ranker.compute_speed_score(
            dte=60, stability_score=80, sector=None,
        )
        score_mc = ranker.compute_speed_score(
            dte=60, stability_score=80, sector=None, market_context_score=8.0,
        )
        assert score_mc > score_no_mc

    def test_max_speed_capped(self, ranker):
        """Speed score should not exceed SPEED_SCORE_MAX."""
        score = ranker.compute_speed_score(
            dte=60, stability_score=100, sector="Utilities",
            pullback_score=10.0, market_context_score=10.0,
        )
        assert score <= SPEED_SCORE_MAX

    def test_zero_minimum(self, ranker):
        """Speed score should be >= 0 even with bad inputs."""
        score = ranker.compute_speed_score(
            dte=200, stability_score=0, sector="Unknown",
        )
        assert score >= 0

    def test_unknown_sector_uses_default(self, ranker):
        """Unknown sector should use default speed (0.5)."""
        score = ranker.compute_speed_score(
            dte=60, stability_score=80, sector="Nonexistent",
        )
        assert score > 0

    def test_sector_factors_applied(self):
        """Sector cycle factors should modulate sector component."""
        ranker_with_factors = ConcreteRanker(sector_factors={"Utilities": 1.2})
        ranker_no_factors = ConcreteRanker(sector_factors={})

        score_with = ranker_with_factors.compute_speed_score(
            dte=60, stability_score=80, sector="Utilities",
        )
        score_without = ranker_no_factors.compute_speed_score(
            dte=60, stability_score=80, sector="Utilities",
        )
        assert score_with > score_without


# =============================================================================
# SIGNAL RANKING
# =============================================================================

class TestRankSignals:
    """Tests for _rank_signals()"""

    def test_higher_score_ranked_first(self, ranker):
        """Signal with higher score should rank higher."""
        signals = [
            _make_signal("LOW", 5.0),
            _make_signal("HIGH", 9.0),
        ]
        ranked = ranker._rank_signals(signals)
        assert ranked[0].symbol == "HIGH"
        assert ranked[1].symbol == "LOW"

    def test_stability_weight_in_ranking(self):
        """Stability should influence ranking via 30% weight."""
        ranker = ConcreteRanker()
        # Same signal score but different stability
        s1 = _make_signal("STABLE", 7.0, details={
            'stability': {'score': 90.0},
        })
        s2 = _make_signal("UNSTABLE", 7.0, details={
            'stability': {'score': 30.0},
        })
        ranked = ranker._rank_signals([s2, s1])
        assert ranked[0].symbol == "STABLE"

    def test_empty_signals(self, ranker):
        assert ranker._rank_signals([]) == []

    def test_single_signal(self, ranker):
        signals = [_make_signal("ONLY", 7.0)]
        ranked = ranker._rank_signals(signals)
        assert len(ranked) == 1
        assert ranked[0].symbol == "ONLY"

    def test_three_signals_ordering(self, ranker):
        """Three signals with clear score differences."""
        signals = [
            _make_signal("C", 3.0),
            _make_signal("A", 9.0),
            _make_signal("B", 6.0),
        ]
        ranked = ranker._rank_signals(signals)
        assert ranked[0].symbol == "A"
        assert ranked[1].symbol == "B"
        assert ranked[2].symbol == "C"

    def test_ranking_with_fundamentals(self):
        """Ranking should use fundamentals manager for stability + sector."""
        mock_fm = MagicMock()
        mock_fund = MagicMock()
        mock_fund.stability_score = 85.0
        mock_fund.sector = "Utilities"
        mock_fund.historical_win_rate = None
        mock_fund.market_cap_category = "Large"
        mock_fm.get_fundamentals.return_value = mock_fund

        ranker = ConcreteRanker(fundamentals_manager=mock_fm)
        signals = [
            _make_signal("AAPL", 7.0),
            _make_signal("MSFT", 7.0),
        ]
        ranked = ranker._rank_signals(signals)
        assert len(ranked) == 2
        # Both have same signal AND same fundamentals, so order is stable but both exist
        assert {s.symbol for s in ranked} == {"AAPL", "MSFT"}


# =============================================================================
# SECTOR SPEED MAP
# =============================================================================

class TestSectorSpeedMap:
    """Tests for SECTOR_SPEED class attribute."""

    def test_utilities_is_fastest(self):
        assert RecommendationRankingMixin.SECTOR_SPEED["Utilities"] == 1.0

    def test_basic_materials_is_slowest(self):
        assert RecommendationRankingMixin.SECTOR_SPEED["Basic Materials"] == 0.0

    def test_technology_low_speed(self):
        assert RecommendationRankingMixin.SECTOR_SPEED["Technology"] == 0.1

    def test_all_sectors_between_0_and_1(self):
        for sector, speed in RecommendationRankingMixin.SECTOR_SPEED.items():
            assert 0.0 <= speed <= 1.0, f"{sector} speed {speed} out of range"


# =============================================================================
# SPEED SCORE MONOTONICITY
# =============================================================================

class TestSpeedScoreMonotonicity:
    """Verify monotonicity properties of speed scoring."""

    def test_dte_monotonicity_towards_optimal(self):
        """Score should increase as DTE approaches 60."""
        ranker = ConcreteRanker()
        scores = []
        for dte in [120, 100, 80, 60]:
            s = ranker.compute_speed_score(dte=dte, stability_score=80, sector=None)
            scores.append(s)
        # Closer to 60 → higher score
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], f"DTE monotonicity violated at index {i}"

    def test_stability_monotonicity(self):
        """Higher stability → higher speed."""
        ranker = ConcreteRanker()
        scores = []
        for stab in [50, 60, 70, 80, 90, 100]:
            s = ranker.compute_speed_score(dte=60, stability_score=stab, sector=None)
            scores.append(s)
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], f"Stability monotonicity violated at index {i}"


# =============================================================================
# EVENT-PRIORITY-SYSTEM (Strategy Balance)
# =============================================================================

class TestEventPrioritySystem:
    """Tests for the Event-Priority-System (strategy balance)."""

    def test_event_bonus_applied(self, ranker):
        """Signal with event bonus (+0.5) ranks higher than TC at same base score."""
        tc_signal = _make_signal("TC_SYM", 7.0, strategy="trend_continuation")
        pb_signal = _make_signal("PB_SYM", 7.0, strategy="pullback")
        ranked = ranker._rank_signals([tc_signal, pb_signal])
        # Pullback gets +0.5 bonus, TC gets 0.0 → pullback should rank first
        assert ranked[0].symbol == "PB_SYM"
        assert ranked[1].symbol == "TC_SYM"

    def test_no_event_bonus_for_tc(self, ranker):
        """Trend continuation gets 0.0 bonus."""
        assert _SIGNAL_TYPE_BONUS.get("trend_continuation", 0.0) == 0.0

    def test_strategy_cap_enforced(self, ranker):
        """At >3 TC signals, only 3 should be kept."""
        tc_cap = _STRATEGY_CAPS.get("trend_continuation", _STRATEGY_CAP_DEFAULT)
        signals = [
            _make_signal(f"TC_{i}", 8.0 - i * 0.1, strategy="trend_continuation")
            for i in range(5)
        ]
        ranked = ranker._rank_signals(signals)
        tc_count = sum(1 for s in ranked if s.strategy == "trend_continuation")
        assert tc_count <= tc_cap

    def test_diversity_minimum(self, ranker):
        """With 5 TC and 1 pullback, pullback should appear in results."""
        signals = [
            _make_signal(f"TC_{i}", 8.0 - i * 0.1, strategy="trend_continuation")
            for i in range(5)
        ]
        # Add a weaker pullback signal
        signals.append(_make_signal("PB_1", 5.0, strategy="pullback"))
        ranked = ranker._rank_signals(signals)
        strategies_in_result = {s.strategy for s in ranked}
        assert len(strategies_in_result) >= _MIN_STRATEGIES_IN_PICKS
        assert "pullback" in strategies_in_result

    def test_strategy_balance_defaults(self):
        """Without YAML config, sensible defaults should apply."""
        # Defaults are loaded at module level — verify they exist
        assert isinstance(_SIGNAL_TYPE_BONUS, dict)
        assert isinstance(_STRATEGY_CAPS, dict)
        assert _STRATEGY_CAP_DEFAULT >= 1
        assert _MIN_STRATEGIES_IN_PICKS >= 1

    def test_event_bonus_values_for_all_event_strategies(self):
        """All event strategies should have positive bonus."""
        for strategy in ["pullback", "bounce", "ath_breakout", "earnings_dip"]:
            assert _SIGNAL_TYPE_BONUS.get(strategy, 0.0) > 0.0, (
                f"{strategy} should have positive event bonus"
            )

    def test_cap_does_not_affect_uncapped_strategies(self, ranker):
        """Strategies within their cap should all pass through."""
        signals = [
            _make_signal(f"PB_{i}", 7.0 - i * 0.5, strategy="pullback")
            for i in range(3)
        ]
        ranked = ranker._rank_signals(signals)
        assert len(ranked) == 3
