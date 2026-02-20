# Tests for Score Normalization
# ==============================
"""
Tests for score_normalization.py module including:
- StrategyScoreConfig dataclass
- normalize_score function
- denormalize_score function
- get_signal_strength function
- get_max_possible function
- compare_scores function
- ScoreNormalizer class
"""

import pytest
from unittest.mock import MagicMock

from src.analyzers.score_normalization import (
    StrategyScoreConfig,
    STRATEGY_SCORE_CONFIGS,
    normalize_score,
    denormalize_score,
    get_signal_strength,
    get_max_possible,
    compare_scores,
    ScoreNormalizer,
)


# =============================================================================
# STRATEGY SCORE CONFIG TESTS
# =============================================================================

class TestStrategyScoreConfig:
    """Tests for StrategyScoreConfig dataclass."""

    def test_create_config(self):
        """Test creating a StrategyScoreConfig."""
        config = StrategyScoreConfig(max_possible=25.0)

        assert config.max_possible == 25.0
        assert config.strong_threshold == 7.0
        assert config.moderate_threshold == 5.0
        assert config.weak_threshold == 3.0

    def test_custom_thresholds(self):
        """Test custom thresholds."""
        config = StrategyScoreConfig(
            max_possible=20.0,
            strong_threshold=8.0,
            moderate_threshold=6.0,
            weak_threshold=4.0,
        )

        assert config.strong_threshold == 8.0
        assert config.moderate_threshold == 6.0
        assert config.weak_threshold == 4.0


# =============================================================================
# STRATEGY CONFIGS DICT TESTS
# =============================================================================

class TestStrategyScoreConfigs:
    """Tests for STRATEGY_SCORE_CONFIGS dictionary."""

    def test_has_all_strategies(self):
        """Test that all expected strategies are present."""
        expected = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'trend_continuation']
        for strategy in expected:
            assert strategy in STRATEGY_SCORE_CONFIGS

    def test_pullback_config(self):
        """Test pullback configuration."""
        config = STRATEGY_SCORE_CONFIGS['pullback']
        assert config.max_possible == 27.0
        assert config.strong_threshold == 7.0

    def test_bounce_config(self):
        """Test bounce configuration."""
        config = STRATEGY_SCORE_CONFIGS['bounce']
        assert config.max_possible == 10.0

    def test_ath_breakout_config(self):
        """Test ATH breakout configuration."""
        config = STRATEGY_SCORE_CONFIGS['ath_breakout']
        assert config.max_possible == 10.0

    def test_earnings_dip_config(self):
        """Test earnings dip configuration."""
        config = STRATEGY_SCORE_CONFIGS['earnings_dip']
        assert config.max_possible == 9.5

    def test_trend_continuation_config(self):
        """Test trend continuation configuration."""
        config = STRATEGY_SCORE_CONFIGS['trend_continuation']
        assert config.max_possible == 10.5
        assert config.strong_threshold == 7.5
        assert config.moderate_threshold == 6.0
        assert config.weak_threshold == 5.0


# =============================================================================
# NORMALIZE SCORE TESTS
# =============================================================================

class TestNormalizeScore:
    """Tests for normalize_score function."""

    def test_normalize_pullback_half(self):
        """Test normalizing pullback score at 50%."""
        # Pullback max is 27, so 13.5 should be 5.0
        result = normalize_score(13.5, 'pullback')
        assert result == 5.0

    def test_normalize_pullback_full(self):
        """Test normalizing pullback at max."""
        # Pullback max is 27
        result = normalize_score(27.0, 'pullback')
        assert result == 10.0

    def test_normalize_bounce(self):
        """Test normalizing bounce score."""
        # Bounce max is 10.0, so 10.0 should be 10.0
        result = normalize_score(10.0, 'bounce')
        assert result == 10.0

        # 5.0 should be 5.0 (already normalized scale)
        result = normalize_score(5.0, 'bounce')
        assert result == 5.0

    def test_normalize_ath_breakout(self):
        """Test normalizing ATH breakout score."""
        # ATH max is 10.0 (v2: 4-component scoring)
        result = normalize_score(10.0, 'ath_breakout')
        assert result == 10.0

    def test_normalize_earnings_dip(self):
        """Test normalizing earnings dip score."""
        # Earnings dip max is 9.5 (v2: 5-component + penalties)
        result = normalize_score(9.5, 'earnings_dip')
        assert result == 10.0

    def test_normalize_trend_continuation(self):
        """Test normalizing trend continuation score."""
        # Trend continuation max is 10.5
        result = normalize_score(10.5, 'trend_continuation')
        assert result == 10.0

        # Half of max
        result = normalize_score(5.25, 'trend_continuation')
        assert result == 5.0

    def test_normalize_zero_score(self):
        """Test normalizing zero score."""
        result = normalize_score(0.0, 'pullback')
        assert result == 0.0

    def test_normalize_unknown_strategy(self):
        """Test normalizing unknown strategy returns raw score."""
        result = normalize_score(7.5, 'unknown_strategy')
        assert result == 7.5

    def test_normalize_clamps_above_max(self):
        """Test that scores above max are clamped to 10."""
        # More than max should cap at 10
        result = normalize_score(30.0, 'pullback')  # Max is 26
        assert result == 10.0

    def test_normalize_clamps_negative(self):
        """Test that negative scores are clamped to 0."""
        result = normalize_score(-5.0, 'pullback')
        assert result == 0.0


# =============================================================================
# DENORMALIZE SCORE TESTS
# =============================================================================

class TestDenormalizeScore:
    """Tests for denormalize_score function."""

    def test_denormalize_pullback(self):
        """Test denormalizing pullback score."""
        # 5.0 on 0-10 scale should be 13.5 raw (half of 27)
        result = denormalize_score(5.0, 'pullback')
        assert result == 13.5

    def test_denormalize_max(self):
        """Test denormalizing max score."""
        result = denormalize_score(10.0, 'pullback')
        assert result == 27.0

    def test_denormalize_zero(self):
        """Test denormalizing zero score."""
        result = denormalize_score(0.0, 'pullback')
        assert result == 0.0

    def test_denormalize_bounce(self):
        """Test denormalizing bounce score."""
        result = denormalize_score(10.0, 'bounce')
        assert result == 10.0

    def test_denormalize_unknown_strategy(self):
        """Test denormalizing unknown strategy returns input."""
        result = denormalize_score(7.5, 'unknown_strategy')
        assert result == 7.5


# =============================================================================
# GET SIGNAL STRENGTH TESTS
# =============================================================================

class TestGetSignalStrength:
    """Tests for get_signal_strength function."""

    def test_strong_signal(self):
        """Test strong signal detection."""
        result = get_signal_strength(8.0, 'pullback')
        assert result == 'STRONG'

    def test_strong_at_threshold(self):
        """Test strong exactly at threshold."""
        result = get_signal_strength(7.0, 'pullback')
        assert result == 'STRONG'

    def test_moderate_signal(self):
        """Test moderate signal detection."""
        result = get_signal_strength(6.0, 'pullback')
        assert result == 'MODERATE'

    def test_moderate_at_threshold(self):
        """Test moderate exactly at threshold."""
        result = get_signal_strength(5.0, 'pullback')
        assert result == 'MODERATE'

    def test_weak_signal(self):
        """Test weak signal detection."""
        result = get_signal_strength(4.0, 'pullback')
        assert result == 'WEAK'

    def test_weak_at_threshold(self):
        """Test weak exactly at threshold."""
        result = get_signal_strength(3.0, 'pullback')
        assert result == 'WEAK'

    def test_none_signal(self):
        """Test none signal for low scores."""
        result = get_signal_strength(2.0, 'pullback')
        assert result == 'NONE'

    def test_none_for_zero(self):
        """Test none signal for zero."""
        result = get_signal_strength(0.0, 'pullback')
        assert result == 'NONE'

    def test_unknown_strategy_uses_default(self):
        """Test unknown strategy uses default thresholds."""
        result = get_signal_strength(8.0, 'unknown')
        assert result == 'STRONG'


# =============================================================================
# GET MAX POSSIBLE TESTS
# =============================================================================

class TestGetMaxPossible:
    """Tests for get_max_possible function."""

    def test_pullback_max(self):
        """Test pullback max."""
        result = get_max_possible('pullback')
        assert result == 27.0

    def test_bounce_max(self):
        """Test bounce max."""
        result = get_max_possible('bounce')
        assert result == 10.0

    def test_ath_breakout_max(self):
        """Test ATH breakout max."""
        result = get_max_possible('ath_breakout')
        assert result == 10.0

    def test_earnings_dip_max(self):
        """Test earnings dip max."""
        result = get_max_possible('earnings_dip')
        assert result == 9.5

    def test_trend_continuation_max(self):
        """Test trend continuation max."""
        result = get_max_possible('trend_continuation')
        assert result == 10.5

    def test_unknown_strategy_returns_default(self):
        """Test unknown strategy returns default of 10."""
        result = get_max_possible('unknown_strategy')
        assert result == 10.0


# =============================================================================
# COMPARE SCORES TESTS
# =============================================================================

class TestCompareScores:
    """Tests for compare_scores function."""

    def test_normalize_scores(self):
        """Test comparing and normalizing scores."""
        scores = {
            'pullback': 13.5,  # 50% of 27 = 5.0
            'bounce': 5.0,     # 50% of 10 = 5.0
        }

        result = compare_scores(scores, normalize=True)

        assert result['pullback'] == 5.0
        assert result['bounce'] == 5.0

    def test_no_normalize(self):
        """Test comparing without normalization."""
        scores = {
            'pullback': 13.0,
            'bounce': 7.0,
        }

        result = compare_scores(scores, normalize=False)

        assert result == scores

    def test_empty_scores(self):
        """Test comparing empty scores."""
        result = compare_scores({}, normalize=True)
        assert result == {}

    def test_mixed_strategies(self):
        """Test comparing multiple strategies."""
        scores = {
            'pullback': 27.0,    # Max = 10.0
            'bounce': 10.0,      # Max = 10.0
            'ath_breakout': 10.0,  # Max = 10.0 (v2)
            'earnings_dip': 9.5,  # Max = 10.0 (v2)
            'trend_continuation': 10.5,  # Max = 10.0
        }

        result = compare_scores(scores, normalize=True)

        # All max scores should normalize to 10.0
        for strategy in scores:
            assert result[strategy] == 10.0


# =============================================================================
# SCORE NORMALIZER CLASS TESTS
# =============================================================================

class TestScoreNormalizer:
    """Tests for ScoreNormalizer class."""

    def test_create_with_defaults(self):
        """Test creating with default configs."""
        normalizer = ScoreNormalizer()

        assert 'pullback' in normalizer.configs
        assert 'bounce' in normalizer.configs

    def test_create_with_custom_config(self):
        """Test creating with custom configs."""
        custom = {
            'custom_strategy': StrategyScoreConfig(max_possible=30.0),
        }

        normalizer = ScoreNormalizer(custom_configs=custom)

        assert 'custom_strategy' in normalizer.configs
        assert normalizer.configs['custom_strategy'].max_possible == 30.0

    def test_custom_config_overrides_default(self):
        """Test that custom config overrides default."""
        custom = {
            'pullback': StrategyScoreConfig(max_possible=100.0),
        }

        normalizer = ScoreNormalizer(custom_configs=custom)

        assert normalizer.configs['pullback'].max_possible == 100.0

    def test_normalize_method(self):
        """Test normalize method."""
        normalizer = ScoreNormalizer()

        result = normalizer.normalize(13.5, 'pullback')
        assert result == 5.0

    def test_normalize_unknown_strategy(self):
        """Test normalize with unknown strategy."""
        normalizer = ScoreNormalizer()

        result = normalizer.normalize(7.5, 'unknown')
        assert result == 7.5

    def test_normalize_clamps_values(self):
        """Test normalize clamps values to 0-10."""
        normalizer = ScoreNormalizer()

        # Above max
        result = normalizer.normalize(50.0, 'pullback')
        assert result == 10.0

        # Negative
        result = normalizer.normalize(-5.0, 'pullback')
        assert result == 0.0

    def test_get_strength_strong(self):
        """Test get_strength for strong signal."""
        normalizer = ScoreNormalizer()

        result = normalizer.get_strength(8.0, 'pullback')
        assert result == 'STRONG'

    def test_get_strength_moderate(self):
        """Test get_strength for moderate signal."""
        normalizer = ScoreNormalizer()

        result = normalizer.get_strength(6.0, 'pullback')
        assert result == 'MODERATE'

    def test_get_strength_weak(self):
        """Test get_strength for weak signal."""
        normalizer = ScoreNormalizer()

        result = normalizer.get_strength(4.0, 'pullback')
        assert result == 'WEAK'

    def test_get_strength_none(self):
        """Test get_strength for none signal."""
        normalizer = ScoreNormalizer()

        result = normalizer.get_strength(2.0, 'pullback')
        assert result == 'NONE'

    def test_get_strength_unknown_strategy(self):
        """Test get_strength with unknown strategy."""
        normalizer = ScoreNormalizer()

        # Should fall back to default config
        result = normalizer.get_strength(8.0, 'unknown')
        assert result == 'STRONG'

    def test_rank_candidates_empty(self):
        """Test ranking empty list."""
        normalizer = ScoreNormalizer()

        result = normalizer.rank_candidates([])
        assert result == []

    def test_rank_candidates_basic(self):
        """Test ranking candidates."""
        normalizer = ScoreNormalizer()

        # Create mock candidates
        class Candidate:
            def __init__(self, score, strategy):
                self.score = score
                self.strategy = strategy

        candidates = [
            Candidate(13.5, 'pullback'),   # 50% = 5.0
            Candidate(7.5, 'bounce'),      # 75% = 7.5
            Candidate(5.0, 'ath_breakout'),  # 50% = 5.0 (v2: max=10)
        ]

        result = normalizer.rank_candidates(candidates)

        # Bounce should be first (highest normalized score)
        assert result[0].strategy == 'bounce'

    def test_rank_candidates_custom_attr(self):
        """Test ranking with custom score attribute."""
        normalizer = ScoreNormalizer()

        class Candidate:
            def __init__(self, raw_score, strategy):
                self.raw_score = raw_score
                self.strategy = strategy

        candidates = [
            Candidate(13.5, 'pullback'),
            Candidate(10.0, 'bounce'),  # Max score
        ]

        result = normalizer.rank_candidates(candidates, score_attr='raw_score')

        # Bounce (10.0) should be first
        assert result[0].strategy == 'bounce'

    def test_rank_candidates_missing_attrs(self):
        """Test ranking candidates with missing attributes."""
        normalizer = ScoreNormalizer()

        class Candidate:
            pass

        candidates = [Candidate(), Candidate()]

        # Should handle missing attrs gracefully
        result = normalizer.rank_candidates(candidates)
        assert len(result) == 2


# =============================================================================
# EDGE CASES TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_very_small_score(self):
        """Test normalizing very small score."""
        result = normalize_score(0.001, 'pullback')
        assert result > 0
        assert result < 0.01

    def test_very_large_score(self):
        """Test normalizing very large score."""
        result = normalize_score(1000.0, 'pullback')
        assert result == 10.0  # Clamped

    def test_float_precision(self):
        """Test float precision in normalization."""
        # 20.25 / 27.0 * 10.0 = 7.5
        result = normalize_score(20.25, 'pullback')
        assert result == 7.5

    def test_denormalize_inverse(self):
        """Test that denormalize is inverse of normalize."""
        original = 15.0
        normalized = normalize_score(original, 'pullback')
        denormalized = denormalize_score(normalized, 'pullback')

        assert abs(denormalized - original) < 0.0001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
