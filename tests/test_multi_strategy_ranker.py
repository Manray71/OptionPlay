# Tests for Multi-Strategy Ranker
# ================================
"""
Tests for score normalization and ranking across strategies.
"""

import pytest
from src.scanner.multi_strategy_ranker import (
    MultiStrategyRanker,
    NormalizedScore,
    MultiStrategyRanking,
    STRATEGY_METRICS,
    get_ranker,
    compare_strategies,
)


class TestStrategyMetrics:
    """Tests for strategy metrics constants."""

    def test_all_strategies_have_metrics(self):
        """Test all strategies have defined metrics."""
        expected_strategies = ["pullback", "bounce", "ath_breakout", "earnings_dip"]
        for strategy in expected_strategies:
            assert strategy in STRATEGY_METRICS

    def test_metrics_have_required_fields(self):
        """Test each strategy has required metric fields."""
        for strategy, metrics in STRATEGY_METRICS.items():
            assert "win_rate" in metrics
            assert "avg_pnl" in metrics
            assert "sharpe" in metrics
            assert "score_percentiles" in metrics

    def test_percentiles_have_required_keys(self):
        """Test score percentiles have all required keys."""
        for strategy, metrics in STRATEGY_METRICS.items():
            percentiles = metrics["score_percentiles"]
            assert "p10" in percentiles
            assert "p25" in percentiles
            assert "p50" in percentiles
            assert "p75" in percentiles
            assert "p90" in percentiles
            assert "p95" in percentiles

    def test_win_rates_are_valid(self):
        """Test win rates are between 0 and 1."""
        for strategy, metrics in STRATEGY_METRICS.items():
            assert 0 < metrics["win_rate"] <= 1

    def test_avg_pnl_is_positive(self):
        """Test average P&L is positive."""
        for strategy, metrics in STRATEGY_METRICS.items():
            assert metrics["avg_pnl"] > 0


class TestNormalizedScore:
    """Tests for NormalizedScore dataclass."""

    def test_normalized_score_creation(self):
        """Test NormalizedScore can be created."""
        score = NormalizedScore(
            strategy="pullback",
            raw_score=7.5,
            normalized_score=75.0,
            percentile=75.0,
            expected_value=150.0,
            win_rate=0.86,
            avg_pnl=158.0,
        )

        assert score.strategy == "pullback"
        assert score.raw_score == 7.5
        assert score.normalized_score == 75.0

    def test_normalized_score_comparison(self):
        """Test NormalizedScore comparison by expected value."""
        score1 = NormalizedScore(
            strategy="pullback",
            raw_score=7.5,
            normalized_score=75.0,
            percentile=75.0,
            expected_value=150.0,
            win_rate=0.86,
            avg_pnl=158.0,
        )
        score2 = NormalizedScore(
            strategy="bounce",
            raw_score=6.0,
            normalized_score=60.0,
            percentile=60.0,
            expected_value=120.0,
            win_rate=0.85,
            avg_pnl=157.0,
        )

        assert score2 < score1  # score2 has lower expected value


class TestMultiStrategyRanking:
    """Tests for MultiStrategyRanking dataclass."""

    def test_ranking_to_dict(self):
        """Test ranking to_dict method."""
        score = NormalizedScore(
            strategy="pullback",
            raw_score=7.5,
            normalized_score=75.0,
            percentile=75.0,
            expected_value=150.0,
            win_rate=0.86,
            avg_pnl=158.0,
        )

        ranking = MultiStrategyRanking(
            symbol="AAPL",
            current_price=185.0,
            scores=[score],
            best_strategy="pullback",
            best_expected_value=150.0,
            strategy_count=1,
        )

        result = ranking.to_dict()

        assert result["symbol"] == "AAPL"
        assert result["current_price"] == 185.0
        assert result["best_strategy"] == "pullback"
        assert len(result["scores"]) == 1


class TestMultiStrategyRankerInit:
    """Tests for MultiStrategyRanker initialization."""

    def test_default_metrics(self):
        """Test ranker uses default metrics."""
        ranker = MultiStrategyRanker()
        assert ranker.metrics == STRATEGY_METRICS

    def test_custom_metrics(self):
        """Test ranker accepts custom metrics."""
        custom_metrics = {
            "pullback": {
                "win_rate": 0.80,
                "avg_pnl": 100.0,
                "sharpe": 10.0,
                "score_percentiles": {
                    "p10": 3.0, "p25": 4.0, "p50": 5.0,
                    "p75": 6.0, "p90": 7.0, "p95": 8.0,
                }
            }
        }
        ranker = MultiStrategyRanker(metrics=custom_metrics)
        assert ranker.metrics == custom_metrics


class TestNormalizeScore:
    """Tests for normalize_score method."""

    @pytest.fixture
    def ranker(self):
        """Create ranker instance."""
        return MultiStrategyRanker()

    def test_normalize_score_pullback(self, ranker):
        """Test score normalization for pullback strategy."""
        result = ranker.normalize_score("pullback", 6.0)

        assert result.strategy == "pullback"
        assert result.raw_score == 6.0
        assert 0 <= result.normalized_score <= 100
        assert 0 <= result.percentile <= 100
        assert result.expected_value > 0

    def test_normalize_score_bounce(self, ranker):
        """Test score normalization for bounce strategy."""
        result = ranker.normalize_score("bounce", 5.8)

        assert result.strategy == "bounce"
        assert 0 <= result.percentile <= 100

    def test_normalize_score_ath_breakout(self, ranker):
        """Test score normalization for ATH breakout strategy."""
        result = ranker.normalize_score("ath_breakout", 7.0)

        assert result.strategy == "ath_breakout"
        assert 0 <= result.percentile <= 100

    def test_normalize_score_earnings_dip(self, ranker):
        """Test score normalization for earnings dip strategy."""
        result = ranker.normalize_score("earnings_dip", 7.0)

        assert result.strategy == "earnings_dip"
        assert 0 <= result.percentile <= 100

    def test_normalize_low_score(self, ranker):
        """Test normalization of low score."""
        result = ranker.normalize_score("pullback", 2.0)

        assert result.percentile < 25  # Should be low percentile

    def test_normalize_high_score(self, ranker):
        """Test normalization of high score."""
        result = ranker.normalize_score("pullback", 9.5)

        assert result.percentile > 90  # Should be high percentile

    def test_normalize_very_high_score(self, ranker):
        """Test normalization of score above 95th percentile."""
        result = ranker.normalize_score("pullback", 10.0)

        assert result.percentile >= 95
        assert result.percentile <= 100

    def test_normalize_unknown_strategy_raises(self, ranker):
        """Test unknown strategy raises ValueError."""
        with pytest.raises(ValueError) as exc:
            ranker.normalize_score("unknown_strategy", 5.0)

        assert "Unknown strategy" in str(exc.value)

    def test_expected_value_increases_with_percentile(self, ranker):
        """Test expected value increases with percentile."""
        low_score = ranker.normalize_score("pullback", 4.0)
        high_score = ranker.normalize_score("pullback", 9.0)

        assert high_score.expected_value > low_score.expected_value


class TestRankSymbol:
    """Tests for rank_symbol method."""

    @pytest.fixture
    def ranker(self):
        """Create ranker instance."""
        return MultiStrategyRanker()

    def test_rank_symbol_single_strategy(self, ranker):
        """Test ranking with single strategy."""
        scores = {"pullback": 7.0}
        ranking = ranker.rank_symbol("AAPL", 185.0, scores)

        assert ranking.symbol == "AAPL"
        assert ranking.current_price == 185.0
        assert ranking.best_strategy == "pullback"
        assert ranking.strategy_count == 1

    def test_rank_symbol_multiple_strategies(self, ranker):
        """Test ranking with multiple strategies."""
        scores = {
            "pullback": 7.5,
            "bounce": 6.0,
            "ath_breakout": 8.0,
        }
        ranking = ranker.rank_symbol("AAPL", 185.0, scores)

        assert ranking.strategy_count == 3
        assert len(ranking.scores) == 3

    def test_rank_symbol_filters_none_scores(self, ranker):
        """Test ranking filters out None scores."""
        scores = {
            "pullback": 7.5,
            "bounce": None,
            "ath_breakout": 6.5,
        }
        ranking = ranker.rank_symbol("AAPL", 185.0, scores)

        assert ranking.strategy_count == 2

    def test_rank_symbol_filters_low_scores(self, ranker):
        """Test ranking filters out scores below min_score."""
        scores = {
            "pullback": 7.5,
            "bounce": 3.0,  # Below default min_score of 5.0
        }
        ranking = ranker.rank_symbol("AAPL", 185.0, scores)

        assert ranking.strategy_count == 1

    def test_rank_symbol_custom_min_score(self, ranker):
        """Test ranking with custom min_score."""
        scores = {
            "pullback": 6.0,
            "bounce": 5.0,
        }
        ranking = ranker.rank_symbol("AAPL", 185.0, scores, min_score=5.5)

        assert ranking.strategy_count == 1

    def test_rank_symbol_selects_best_strategy(self, ranker):
        """Test ranking selects strategy with highest expected value."""
        scores = {
            "pullback": 6.0,
            "ath_breakout": 8.5,  # Higher score
        }
        ranking = ranker.rank_symbol("AAPL", 185.0, scores)

        assert ranking.best_strategy == "ath_breakout"

    def test_rank_symbol_no_qualifying_strategies(self, ranker):
        """Test ranking when no strategies qualify."""
        scores = {
            "pullback": 2.0,  # Too low
            "bounce": None,
        }
        ranking = ranker.rank_symbol("AAPL", 185.0, scores)

        assert ranking.strategy_count == 0
        assert ranking.best_strategy == "none"


class TestRankMultiple:
    """Tests for rank_multiple method."""

    @pytest.fixture
    def ranker(self):
        """Create ranker instance."""
        return MultiStrategyRanker()

    def test_rank_multiple_symbols(self, ranker):
        """Test ranking multiple symbols."""
        symbols_data = [
            {"symbol": "AAPL", "price": 185.0, "scores": {"pullback": 7.0}},
            {"symbol": "MSFT", "price": 400.0, "scores": {"pullback": 8.0}},
            {"symbol": "GOOGL", "price": 150.0, "scores": {"pullback": 6.0}},
        ]

        rankings = ranker.rank_multiple(symbols_data)

        assert len(rankings) == 3
        # Should be sorted by expected value
        assert rankings[0].symbol == "MSFT"  # Highest score

    def test_rank_multiple_filters_by_min_strategies(self, ranker):
        """Test rank_multiple filters by min_strategies."""
        symbols_data = [
            {"symbol": "AAPL", "price": 185.0, "scores": {"pullback": 7.0, "bounce": 6.0}},
            {"symbol": "MSFT", "price": 400.0, "scores": {"pullback": 8.0}},  # Only 1 strategy
        ]

        rankings = ranker.rank_multiple(symbols_data, min_strategies=2)

        assert len(rankings) == 1
        assert rankings[0].symbol == "AAPL"

    def test_rank_multiple_empty_input(self, ranker):
        """Test rank_multiple with empty input."""
        rankings = ranker.rank_multiple([])

        assert rankings == []


class TestFormatRanking:
    """Tests for format_ranking method."""

    @pytest.fixture
    def ranker(self):
        """Create ranker instance."""
        return MultiStrategyRanker()

    def test_format_ranking_basic(self, ranker):
        """Test basic formatting."""
        scores = {"pullback": 7.5}
        ranking = ranker.rank_symbol("AAPL", 185.0, scores)

        formatted = ranker.format_ranking(ranking)

        assert "AAPL" in formatted
        assert "185.0" in formatted
        assert "pullback" in formatted.lower()


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_get_ranker(self):
        """Test get_ranker returns MultiStrategyRanker."""
        ranker = get_ranker()
        assert isinstance(ranker, MultiStrategyRanker)

    def test_compare_strategies_basic(self):
        """Test compare_strategies function."""
        ranking = compare_strategies(
            "AAPL", 185.0,
            pullback_score=7.5,
            bounce_score=6.0,
        )

        assert ranking.symbol == "AAPL"
        assert ranking.strategy_count == 2

    def test_compare_strategies_with_none(self):
        """Test compare_strategies with None scores."""
        ranking = compare_strategies(
            "AAPL", 185.0,
            pullback_score=7.5,
            bounce_score=None,
            ath_breakout_score=8.0,
        )

        assert ranking.strategy_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
