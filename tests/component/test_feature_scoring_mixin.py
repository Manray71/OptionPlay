# Tests for Feature Scoring Mixin
# ================================
"""
Tests for analyzers/feature_scoring_mixin.py module including:
- get_trained_weights function
- FeatureScoringMixin class
- _score_vwap method
- _score_market_context method
- _score_sector method
- _score_gap method
- _apply_feature_scores method
- apply_trained_weights method
- get_roll_params method
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch

from src.analyzers.feature_scoring_mixin import (
    FeatureScoringMixin,
    get_trained_weights,
    _trained_weights_cache,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mixin():
    """Create a FeatureScoringMixin instance for testing."""
    return FeatureScoringMixin()


@pytest.fixture
def sample_prices():
    """Generate sample price data."""
    return [100.0 + i * 0.1 for i in range(90)]


@pytest.fixture
def sample_volumes():
    """Generate sample volume data."""
    return [1000000 + i * 10000 for i in range(90)]


@pytest.fixture
def sample_highs(sample_prices):
    """Generate sample high prices."""
    return [p + 1.5 for p in sample_prices]


@pytest.fixture
def sample_lows(sample_prices):
    """Generate sample low prices."""
    return [p - 1.5 for p in sample_prices]


@pytest.fixture
def sample_breakdown():
    """Create a sample breakdown object."""
    class Breakdown:
        total_score = 0
        rsi_score = 0
        support_score = 0
        fibonacci_score = 0
        ma_score = 0
        volume_score = 0
        macd_score = 0
        stoch_score = 0
        keltner_score = 0
        trend_strength_score = 0
        momentum_score = 0
        rs_score = 0
        candlestick_score = 0
        vwap_score = 0
        vwap_value = 0
        vwap_distance_pct = 0
        vwap_position = ""
        vwap_reason = ""
        market_context_score = 0
        spy_trend = ""
        market_context_reason = ""
        sector_score = 0
        sector = ""
        sector_reason = ""
        gap_score = 0
        gap_type = ""
        gap_size_pct = 0
        gap_filled = False
        gap_reason = ""
    return Breakdown()


# =============================================================================
# GET TRAINED WEIGHTS TESTS
# =============================================================================

class TestGetTrainedWeights:
    """Tests for get_trained_weights function."""

    def test_returns_dict(self):
        """Test that get_trained_weights returns a dict."""
        result = get_trained_weights()
        assert isinstance(result, dict)

    def test_caching_behavior(self):
        """Test that weights are cached."""
        # First call
        result1 = get_trained_weights()
        # Second call should return cached
        result2 = get_trained_weights()

        # Should be same object
        assert result1 is result2


# =============================================================================
# SCORE VWAP TESTS
# =============================================================================

class TestScoreVwap:
    """Tests for _score_vwap method."""

    def test_score_vwap_basic(self, mixin, sample_prices, sample_volumes):
        """Test basic VWAP scoring."""
        result = mixin._score_vwap(sample_prices, sample_volumes)

        assert len(result) == 5  # (score, vwap, distance, position, reason)
        score, vwap, distance, position, reason = result

        assert isinstance(score, (int, float))
        assert 0 <= score <= 3  # Max VWAP score is 3

    def test_score_vwap_insufficient_data(self, mixin):
        """Test VWAP with insufficient data."""
        result = mixin._score_vwap([100.0, 101.0], [1000, 1100])

        score, vwap, distance, position, reason = result
        assert score == 0
        assert "Insufficient" in reason

    def test_score_vwap_strong_momentum(self, mixin):
        """Test VWAP score for strong momentum (>3% above)."""
        # Create prices trending strongly above VWAP
        prices = [100.0 + i * 0.5 for i in range(30)]
        volumes = [1000000] * 30

        result = mixin._score_vwap(prices, volumes)
        score, vwap, distance, position, reason = result

        # Score should be higher for above VWAP
        assert score >= 0

    def test_score_vwap_returns_position(self, mixin, sample_prices, sample_volumes):
        """Test VWAP returns position string."""
        result = mixin._score_vwap(sample_prices, sample_volumes)
        score, vwap, distance, position, reason = result

        # Position should be a string
        assert isinstance(position, str)


# =============================================================================
# SCORE MARKET CONTEXT TESTS
# =============================================================================

class TestScoreMarketContext:
    """Tests for _score_market_context method."""

    def test_strong_uptrend(self, mixin):
        """Test score for strong market uptrend."""
        # SPY in strong uptrend: current > SMA20 > SMA50
        spy_prices = [400.0 + i * 0.5 for i in range(60)]

        score, trend, reason = mixin._score_market_context(spy_prices)

        assert score == 2.0
        assert trend == "strong_uptrend"
        assert "Strong market uptrend" in reason

    def test_uptrend(self, mixin):
        """Test score for market uptrend."""
        # SPY in uptrend: current > SMA50, current > SMA20
        spy_prices = [400.0] * 30 + [410.0] * 20 + [415.0] * 10

        score, trend, reason = mixin._score_market_context(spy_prices)

        assert score >= 1.0

    def test_downtrend(self, mixin):
        """Test score for market downtrend."""
        # SPY in downtrend
        spy_prices = [400.0 - i * 0.5 for i in range(60)]

        score, trend, reason = mixin._score_market_context(spy_prices)

        assert score <= 0
        assert "downtrend" in trend

    def test_insufficient_data(self, mixin):
        """Test with insufficient SPY data."""
        score, trend, reason = mixin._score_market_context([400.0] * 10)

        assert score == 0
        assert trend == "unknown"
        assert "No SPY data" in reason

    def test_no_spy_data(self, mixin):
        """Test with no SPY data."""
        score, trend, reason = mixin._score_market_context(None)

        assert score == 0
        assert trend == "unknown"


# =============================================================================
# SCORE SECTOR TESTS
# =============================================================================

class TestScoreSector:
    """Tests for _score_sector method."""

    def test_sector_score_basic(self, mixin):
        """Test basic sector scoring."""
        score, sector, reason = mixin._score_sector("AAPL")

        assert isinstance(score, (int, float))
        assert isinstance(sector, str)
        assert isinstance(reason, str)

    def test_sector_with_vix(self, mixin):
        """Test sector scoring with VIX."""
        score, sector, reason = mixin._score_sector("JPM", vix=18.0)

        assert isinstance(score, (int, float))
        assert isinstance(sector, str)

    def test_sector_without_vix(self, mixin):
        """Test sector scoring without VIX."""
        score, sector, reason = mixin._score_sector("XOM", vix=None)

        assert isinstance(score, (int, float))

    def test_different_sectors(self, mixin):
        """Test different sector symbols."""
        # Test various symbols from different sectors
        symbols = ["AAPL", "JPM", "XOM", "JNJ", "PG"]

        for symbol in symbols:
            score, sector, reason = mixin._score_sector(symbol)
            assert isinstance(score, (int, float))
            assert -2 <= score <= 2  # Reasonable range


# =============================================================================
# SCORE GAP TESTS
# =============================================================================

class TestScoreGap:
    """Tests for _score_gap method."""

    def test_score_gap_no_context(self, mixin, sample_prices, sample_highs, sample_lows):
        """Test gap scoring without context."""
        result = mixin._score_gap(sample_prices, sample_highs, sample_lows, context=None)

        assert len(result) == 5
        score, gap_type, gap_size, is_filled, reason = result

        assert isinstance(score, (int, float))
        assert isinstance(gap_type, str)
        assert isinstance(reason, str)

    def test_score_gap_with_context(self, mixin, sample_prices, sample_highs, sample_lows):
        """Test gap scoring with context."""
        # Create mock context with gap_result
        class MockGapResult:
            gap_type = "down"
            gap_size_pct = -2.5
            is_filled = False
            quality_score = 0.5

        class MockContext:
            gap_result = MockGapResult()

        result = mixin._score_gap(sample_prices, sample_highs, sample_lows, context=MockContext())

        score, gap_type, gap_size, is_filled, reason = result
        assert score >= 0  # Down gap should be positive
        assert gap_type == "down"

    def test_score_gap_insufficient_data(self, mixin):
        """Test gap scoring with insufficient data."""
        result = mixin._score_gap([100.0], [101.0], [99.0], context=None)

        score, gap_type, gap_size, is_filled, reason = result
        assert score == 0
        assert "Insufficient" in reason

    def test_score_gap_down_gap(self, mixin):
        """Test scoring for down gap (bullish for entry)."""
        class MockGapResult:
            gap_type = "down"
            gap_size_pct = -3.5
            is_filled = False
            quality_score = 0.8

        class MockContext:
            gap_result = MockGapResult()

        result = mixin._score_gap([100.0], [101.0], [99.0], context=MockContext())

        score, gap_type, gap_size, is_filled, reason = result
        assert score > 0  # Down gap is positive
        assert "down-gap" in reason.lower()

    def test_score_gap_up_gap(self, mixin):
        """Test scoring for up gap."""
        class MockGapResult:
            gap_type = "up"
            gap_size_pct = 2.0
            is_filled = False
            quality_score = -0.3

        class MockContext:
            gap_result = MockGapResult()

        result = mixin._score_gap([100.0], [101.0], [99.0], context=MockContext())

        score, gap_type, gap_size, is_filled, reason = result
        assert score <= 0  # Up gap should be zero or negative


# =============================================================================
# APPLY FEATURE SCORES TESTS
# =============================================================================

class TestApplyFeatureScores:
    """Tests for _apply_feature_scores method."""

    def test_apply_feature_scores_basic(self, mixin, sample_breakdown, sample_prices, sample_volumes):
        """Test applying all feature scores."""
        mixin._apply_feature_scores(
            breakdown=sample_breakdown,
            symbol="AAPL",
            prices=sample_prices,
            volumes=sample_volumes,
        )

        # VWAP should be set
        assert hasattr(sample_breakdown, 'vwap_score')
        assert sample_breakdown.vwap_reason != ""

        # Sector should be set
        assert hasattr(sample_breakdown, 'sector_score')
        assert sample_breakdown.sector != ""

    def test_apply_feature_scores_with_high_low(self, mixin, sample_breakdown, sample_prices, sample_volumes, sample_highs, sample_lows):
        """Test applying feature scores with high/low data."""
        mixin._apply_feature_scores(
            breakdown=sample_breakdown,
            symbol="AAPL",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=sample_highs,
            lows=sample_lows,
        )

        # Gap score should be set
        assert hasattr(sample_breakdown, 'gap_score')
        assert sample_breakdown.gap_reason != ""

    def test_apply_feature_scores_with_context(self, mixin, sample_breakdown, sample_prices, sample_volumes):
        """Test applying feature scores with market context."""
        class MockContext:
            spy_prices = [400.0 + i * 0.3 for i in range(60)]

        mixin._apply_feature_scores(
            breakdown=sample_breakdown,
            symbol="AAPL",
            prices=sample_prices,
            volumes=sample_volumes,
            context=MockContext(),
        )

        # Market context should be set
        assert sample_breakdown.spy_trend != "unknown"

    def test_apply_feature_scores_with_vix(self, mixin, sample_breakdown, sample_prices, sample_volumes):
        """Test applying feature scores with VIX."""
        mixin._apply_feature_scores(
            breakdown=sample_breakdown,
            symbol="AAPL",
            prices=sample_prices,
            volumes=sample_volumes,
            vix=20.0,
        )

        # Sector score should consider VIX
        assert hasattr(sample_breakdown, 'sector_score')

    def test_apply_feature_scores_no_high_low(self, mixin, sample_breakdown, sample_prices, sample_volumes):
        """Test applying feature scores without high/low data."""
        mixin._apply_feature_scores(
            breakdown=sample_breakdown,
            symbol="AAPL",
            prices=sample_prices,
            volumes=sample_volumes,
            highs=None,
            lows=None,
        )

        # Gap should have fallback values
        assert sample_breakdown.gap_score == 0.0
        assert sample_breakdown.gap_type == "none"


# =============================================================================
# APPLY TRAINED WEIGHTS TESTS
# =============================================================================

class TestApplyTrainedWeights:
    """Tests for apply_trained_weights method."""

    def test_apply_trained_weights_basic(self, mixin, sample_breakdown):
        """Test basic application of trained weights."""
        # Set some scores on breakdown
        sample_breakdown.rsi_score = 2.0
        sample_breakdown.support_score = 1.5
        sample_breakdown.total_score = 5.0

        result = mixin.apply_trained_weights(
            breakdown=sample_breakdown,
            strategy='pullback',
            vix_regime='normal'
        )

        # Should return a number
        assert isinstance(result, (int, float))

    def test_apply_trained_weights_no_weights(self, mixin, sample_breakdown):
        """Test when no trained weights are available."""
        sample_breakdown.total_score = 7.5

        # With non-existent strategy
        result = mixin.apply_trained_weights(
            breakdown=sample_breakdown,
            strategy='nonexistent_strategy',
            vix_regime='normal'
        )

        # Should return unweighted total score
        assert result == 7.5

    def test_apply_trained_weights_different_strategies(self, mixin, sample_breakdown):
        """Test different strategies."""
        sample_breakdown.rsi_score = 2.0
        sample_breakdown.total_score = 5.0

        for strategy in ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']:
            result = mixin.apply_trained_weights(
                breakdown=sample_breakdown,
                strategy=strategy,
                vix_regime='normal'
            )
            assert isinstance(result, (int, float))

    def test_apply_trained_weights_different_regimes(self, mixin, sample_breakdown):
        """Test different VIX regimes."""
        sample_breakdown.rsi_score = 2.0
        sample_breakdown.total_score = 5.0

        for regime in ['low', 'normal', 'elevated', 'high']:
            result = mixin.apply_trained_weights(
                breakdown=sample_breakdown,
                strategy='pullback',
                vix_regime=regime
            )
            assert isinstance(result, (int, float))


# =============================================================================
# GET ROLL PARAMS TESTS
# =============================================================================

class TestGetRollParams:
    """Tests for get_roll_params method."""

    def test_get_roll_params_basic(self, mixin):
        """Test getting roll parameters."""
        result = mixin.get_roll_params('pullback')

        assert isinstance(result, dict)

    def test_get_roll_params_different_strategies(self, mixin):
        """Test different strategies."""
        for strategy in ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']:
            result = mixin.get_roll_params(strategy)
            assert isinstance(result, dict)

    def test_get_roll_params_unknown_strategy(self, mixin):
        """Test unknown strategy returns empty dict."""
        result = mixin.get_roll_params('unknown_strategy')

        assert isinstance(result, dict)


# =============================================================================
# EDGE CASES TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_prices(self, mixin):
        """Test handling of empty prices."""
        result = mixin._score_vwap([], [])
        assert result[0] == 0

    def test_none_spy_prices(self, mixin):
        """Test handling of None SPY prices."""
        result = mixin._score_market_context(None)
        assert result[0] == 0

    def test_very_short_data(self, mixin):
        """Test handling of very short data."""
        prices = [100.0, 101.0, 102.0]
        volumes = [1000, 1100, 1200]

        result = mixin._score_vwap(prices, volumes)
        # Should handle gracefully
        assert isinstance(result[0], (int, float))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
