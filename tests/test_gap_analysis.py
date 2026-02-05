"""
Tests for Gap Analysis Indicator

Validated with 174k+ gap events across 907 symbols, 5 years of data.
"""

import pytest
from dataclasses import dataclass
from typing import List, Tuple

from src.indicators.gap_analysis import (
    detect_gap,
    analyze_gap,
    calculate_gap_statistics,
    calculate_gap_series,
    gap_type_to_score_factor,
    is_significant_gap,
    get_gap_description,
    _calculate_gap_quality_score,
    _find_gap_fill_time,
    _calculate_forward_returns,
    MIN_GAP_THRESHOLD_PCT,
    GAP_FILL_THRESHOLD_PCT,
    DEFAULT_LOOKBACK_DAYS,
    STATS_LOOKBACK_DAYS,
    PERFORMANCE_FORWARD_DAYS,
)
from src.models.indicators import GapResult, GapStatistics


# =============================================================================
# DETECT_GAP FUNCTION TESTS
# =============================================================================


class TestDetectGap:
    """Tests for the detect_gap function"""

    def test_full_down_gap(self):
        """Full down-gap: open below previous low"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=95.0,  # Opens below prev_low (98.0)
            curr_high=97.0,
            curr_low=94.0,
            curr_close=96.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'down'
        assert gap_size_pct == pytest.approx(-5.0, rel=0.01)
        assert gap_size_abs == pytest.approx(-5.0, rel=0.01)

    def test_full_up_gap(self):
        """Full up-gap: open above previous high"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=104.0,  # Opens above prev_high (101.0)
            curr_high=106.0,
            curr_low=103.0,
            curr_close=105.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'up'
        assert gap_size_pct == pytest.approx(4.0, rel=0.01)

    def test_partial_down_gap(self):
        """Partial down-gap: open below close but above low"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=97.0,
            prev_close=100.0,
            curr_open=98.5,  # Opens below close (100) but above low (97)
            curr_high=99.0,
            curr_low=98.0,
            curr_close=98.5,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'partial_down'
        assert gap_size_pct == pytest.approx(-1.5, rel=0.01)

    def test_partial_up_gap(self):
        """Partial up-gap: open above close but below high"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=103.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=101.5,  # Opens above close (100) but below high (103)
            curr_high=102.0,
            curr_low=101.0,
            curr_close=101.5,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'partial_up'
        assert gap_size_pct == pytest.approx(1.5, rel=0.01)

    def test_no_gap(self):
        """No gap when open near previous close"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=100.2,  # Opens very near previous close
            curr_high=101.0,
            curr_low=99.5,
            curr_close=100.5,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'none'

    def test_gap_fill_detection(self):
        """Gap fill should be detected when price retraces"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=95.0,  # Down gap
            curr_high=100.5,  # Retraces above previous close (fills gap)
            curr_low=94.0,
            curr_close=99.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'down'
        assert is_filled == True
        assert fill_pct >= 90.0  # Gap considered filled

    def test_zero_previous_close_returns_none(self):
        """Zero previous close should return 'none' gap type"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=0.0,  # Zero close - edge case
            curr_open=100.0,
            curr_high=102.0,
            curr_low=99.0,
            curr_close=101.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'none'
        assert gap_size_pct == 0.0
        assert gap_size_abs == 0.0

    def test_negative_previous_close_returns_none(self):
        """Negative previous close should return 'none' gap type"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=-10.0,  # Negative close - edge case
            curr_open=100.0,
            curr_high=102.0,
            curr_low=99.0,
            curr_close=101.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'none'


class TestDetectGapEdgeCases:
    """Edge case tests for detect_gap function"""

    def test_gap_exactly_at_threshold(self):
        """Gap exactly at threshold should be detected"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=100.5,  # Exactly 0.5% gap
            curr_high=102.0,
            curr_low=100.0,
            curr_close=101.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'partial_up'
        assert gap_size_pct == pytest.approx(0.5, rel=0.01)

    def test_gap_just_below_threshold(self):
        """Gap just below threshold should not be detected"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=100.4,  # 0.4% - below 0.5% threshold
            curr_high=102.0,
            curr_low=100.0,
            curr_close=101.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'none'

    def test_up_gap_partial_fill(self):
        """Up gap with partial fill should report correct fill percentage"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=105.0,  # 5% up gap
            curr_high=106.0,
            curr_low=102.5,  # Filled half the gap (from 105 to 102.5, gap is 5)
            curr_close=104.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'up'
        assert gap_size_pct == pytest.approx(5.0, rel=0.01)
        assert is_filled == False
        assert fill_pct == pytest.approx(50.0, rel=0.01)  # 50% filled

    def test_down_gap_partial_fill(self):
        """Down gap with partial fill should report correct fill percentage"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=95.0,  # 5% down gap
            curr_high=97.5,  # Filled half the gap (from 95 to 97.5, gap is 5)
            curr_low=94.0,
            curr_close=96.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'down'
        assert gap_size_pct == pytest.approx(-5.0, rel=0.01)
        assert is_filled == False
        assert fill_pct == pytest.approx(50.0, rel=0.01)  # 50% filled

    def test_up_gap_exactly_at_threshold_fill(self):
        """Up gap that fills exactly at threshold should be marked as filled"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=110.0,  # 10% up gap
            curr_high=112.0,
            curr_low=101.0,  # Fills 90% of the gap (110-101 = 9, gap = 10)
            curr_close=108.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'up'
        assert is_filled == True
        assert fill_pct >= GAP_FILL_THRESHOLD_PCT

    def test_very_large_gap(self):
        """Very large gap should be detected correctly"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=80.0,  # 20% down gap
            curr_high=82.0,
            curr_low=78.0,
            curr_close=81.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'down'
        assert gap_size_pct == pytest.approx(-20.0, rel=0.01)
        assert gap_size_abs == pytest.approx(-20.0, rel=0.01)

    def test_custom_min_gap_threshold(self):
        """Custom min_gap_pct should be respected"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=102.0,  # 2% gap
            curr_high=104.0,
            curr_low=101.0,
            curr_close=103.0,
            min_gap_pct=3.0  # Higher threshold
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'none'  # 2% is below 3% threshold


class TestDetectGapGapSizeCategorization:
    """Tests for gap size categorization behavior"""

    def test_small_gap_detected(self):
        """Small gap (< 1%) should be detected if above threshold"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=97.0,
            prev_close=100.0,
            curr_open=99.3,  # -0.7% gap
            curr_high=100.0,
            curr_low=99.0,
            curr_close=99.5,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'partial_down'
        assert abs(gap_size_pct) < 1.0
        assert abs(gap_size_pct) >= 0.5

    def test_medium_gap_detected(self):
        """Medium gap (1-3%) should be detected"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=103.0,  # Higher prev_high so 102 open is below it
            prev_low=98.0,
            prev_close=100.0,
            curr_open=102.0,  # 2% gap, below prev_high so it's partial
            curr_high=104.0,
            curr_low=101.0,
            curr_close=103.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'partial_up'
        assert 1.0 <= gap_size_pct <= 3.0

    def test_large_gap_detected(self):
        """Large gap (> 3%) should be detected"""
        result = detect_gap(
            prev_open=99.0,
            prev_high=101.0,
            prev_low=98.0,
            prev_close=100.0,
            curr_open=104.0,  # 4% gap (above prev_high=101)
            curr_high=106.0,
            curr_low=103.0,
            curr_close=105.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'up'
        assert gap_size_pct > 3.0


# =============================================================================
# ANALYZE_GAP FUNCTION TESTS
# =============================================================================


class TestAnalyzeGap:
    """Tests for the analyze_gap function"""

    def test_analyze_gap_with_down_gap(self):
        """Analyze should detect down gap and return GapResult"""
        # Create data with a down-gap on the last day
        n = 25
        closes = [100.0 + i * 0.5 for i in range(n)]
        closes[-1] = closes[-2] * 0.95  # 5% drop

        opens = [c - 0.2 for c in closes]
        opens[-1] = closes[-2] * 0.94  # Gap open below previous low

        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        lows[-2] = closes[-2] - 0.3  # Previous low

        result = analyze_gap(
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=20,
            min_gap_pct=0.5
        )

        assert result is not None
        assert result.gap_type in ('down', 'partial_down')
        assert result.gap_size_pct < 0

    def test_analyze_gap_no_gap(self):
        """Analyze should return none type when no significant gap"""
        n = 25
        # Create smooth data with no gaps
        closes = [100.0 + i * 0.1 for i in range(n)]
        opens = [c - 0.05 for c in closes]  # Opens very close to previous close
        opens = [closes[0]] + closes[:-1]  # Open = previous close (no gap)
        highs = [c + 0.2 for c in closes]
        lows = [c - 0.2 for c in closes]

        result = analyze_gap(
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=20,
            min_gap_pct=0.5
        )

        assert result is not None
        assert result.gap_type == 'none'

    def test_analyze_gap_quality_score_down_gap(self):
        """Down gaps should have positive quality scores (good for entry)"""
        n = 25
        closes = [100.0] * n
        closes[-1] = 95.0  # 5% drop

        opens = [100.0] * n
        opens[-1] = 94.0  # Large gap open below

        highs = [101.0] * n
        highs[-1] = 96.0

        lows = [99.0] * n
        lows[-1] = 93.0

        result = analyze_gap(
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=20,
            min_gap_pct=0.5
        )

        assert result is not None
        assert result.gap_type in ('down', 'partial_down')
        assert result.quality_score > 0  # Positive = good for entry

    def test_analyze_gap_quality_score_up_gap(self):
        """Large up gaps should have negative quality scores (caution)"""
        n = 25
        closes = [100.0] * n
        closes[-1] = 106.0  # 6% rise

        opens = [100.0] * n
        opens[-1] = 105.0  # Large gap open above

        highs = [101.0] * n
        highs[-1] = 107.0

        lows = [99.0] * n
        lows[-1] = 104.0

        result = analyze_gap(
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=20,
            min_gap_pct=0.5
        )

        assert result is not None
        assert result.gap_type in ('up', 'partial_up')
        # Large up-gaps should have negative scores (caution for Bull-Put-Spreads)
        assert result.quality_score <= 0


class TestAnalyzeGapEdgeCases:
    """Edge case tests for analyze_gap function"""

    def test_analyze_gap_insufficient_data(self):
        """Analyze should return None with insufficient data"""
        opens = [100.0]
        highs = [101.0]
        lows = [99.0]
        closes = [100.0]

        result = analyze_gap(opens, highs, lows, closes)
        assert result is None

    def test_analyze_gap_unequal_array_lengths(self):
        """Analyze should return None with unequal array lengths"""
        opens = [100.0, 101.0, 102.0]
        highs = [101.0, 102.0]  # Different length
        lows = [99.0, 100.0, 101.0]
        closes = [100.0, 101.0, 102.0]

        result = analyze_gap(opens, highs, lows, closes)
        assert result is None

    def test_analyze_gap_minimum_data(self):
        """Analyze should work with exactly 2 data points"""
        opens = [100.0, 95.0]
        highs = [101.0, 96.0]
        lows = [99.0, 94.0]
        closes = [100.0, 95.0]

        result = analyze_gap(opens, highs, lows, closes)
        assert result is not None
        assert result.gap_type in ('down', 'partial_down', 'none')

    def test_analyze_gap_custom_lookback(self):
        """Analyze should respect custom lookback_days"""
        n = 50
        closes = [100.0 + i * 0.1 for i in range(n)]
        opens = [closes[0]] + closes[:-1]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]

        result = analyze_gap(
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=10,  # Short lookback
            min_gap_pct=0.5
        )

        assert result is not None

    def test_analyze_gap_returns_gap_statistics(self):
        """Analyze should return historical gap statistics"""
        n = 30
        closes = [100.0] * n
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n

        # Add some gaps in history
        opens[10] = 103.0
        closes[10] = 102.0
        opens[20] = 97.0
        closes[20] = 98.0

        result = analyze_gap(
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=20,
            min_gap_pct=0.5
        )

        assert result is not None
        assert hasattr(result, 'gaps_last_20_days')
        assert hasattr(result, 'avg_gap_size_20d')
        assert hasattr(result, 'gap_fill_rate_20d')

    def test_analyze_gap_previous_close_and_current_open(self):
        """Analyze should correctly set previous_close and current_open"""
        n = 10
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
        opens = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 115.0]  # Gap on last day
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]

        result = analyze_gap(opens, highs, lows, closes)

        assert result is not None
        assert result.previous_close == 108.0  # Second to last close
        assert result.current_open == 115.0  # Last open


# =============================================================================
# GAP QUALITY SCORE TESTS
# =============================================================================


class TestCalculateGapQualityScore:
    """Tests for _calculate_gap_quality_score function"""

    def test_no_gap_returns_zero_score(self):
        """No gap should return zero quality score"""
        score = _calculate_gap_quality_score(
            gap_type='none',
            gap_size_pct=0.0,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=1.0
        )
        assert score == 0.0

    def test_large_down_gap_positive_score(self):
        """Large down gap (>= 3%) should have high positive score"""
        score = _calculate_gap_quality_score(
            gap_type='down',
            gap_size_pct=-4.0,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=2.0
        )
        assert score >= 0.5
        assert score <= 1.0

    def test_medium_down_gap_moderate_score(self):
        """Medium down gap (2-3%) should have moderate positive score"""
        score = _calculate_gap_quality_score(
            gap_type='down',
            gap_size_pct=-2.5,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=2.0
        )
        assert 0.3 <= score <= 0.7

    def test_small_down_gap_low_score(self):
        """Small down gap (< 1%) should have low positive score"""
        score = _calculate_gap_quality_score(
            gap_type='down',
            gap_size_pct=-0.7,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=1.0
        )
        assert 0.0 < score < 0.3

    def test_small_up_gap_neutral_score(self):
        """Small up gap (< 1%) should have neutral score"""
        score = _calculate_gap_quality_score(
            gap_type='up',
            gap_size_pct=0.8,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=1.0
        )
        assert score == 0.0

    def test_large_up_gap_negative_score(self):
        """Large up gap (> 3%) should have negative score"""
        score = _calculate_gap_quality_score(
            gap_type='up',
            gap_size_pct=4.0,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=2.0
        )
        assert score < 0.0
        assert score >= -1.0

    def test_filled_down_gap_reduces_score(self):
        """Filled down gap should have reduced score"""
        score_unfilled = _calculate_gap_quality_score(
            gap_type='down',
            gap_size_pct=-3.5,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=2.0
        )
        score_filled = _calculate_gap_quality_score(
            gap_type='down',
            gap_size_pct=-3.5,
            is_filled=True,
            fill_percentage=95.0,
            avg_gap_size=2.0
        )
        assert score_filled < score_unfilled

    def test_partially_filled_down_gap_reduces_score(self):
        """Partially filled down gap should have somewhat reduced score"""
        score_unfilled = _calculate_gap_quality_score(
            gap_type='down',
            gap_size_pct=-3.5,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=2.0
        )
        score_partial = _calculate_gap_quality_score(
            gap_type='down',
            gap_size_pct=-3.5,
            is_filled=False,
            fill_percentage=60.0,
            avg_gap_size=2.0
        )
        assert score_partial < score_unfilled

    def test_partial_down_gap_lower_than_full(self):
        """Partial down gap should score lower than full down gap"""
        score_full = _calculate_gap_quality_score(
            gap_type='down',
            gap_size_pct=-2.0,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=2.0
        )
        score_partial = _calculate_gap_quality_score(
            gap_type='partial_down',
            gap_size_pct=-2.0,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=2.0
        )
        assert score_partial < score_full

    def test_filled_up_gap_reduces_negative_score(self):
        """Filled up gap should have less negative score (less bearish)"""
        score_unfilled = _calculate_gap_quality_score(
            gap_type='up',
            gap_size_pct=3.5,
            is_filled=False,
            fill_percentage=0.0,
            avg_gap_size=2.0
        )
        score_filled = _calculate_gap_quality_score(
            gap_type='up',
            gap_size_pct=3.5,
            is_filled=True,
            fill_percentage=95.0,
            avg_gap_size=2.0
        )
        # Filled means less negative (closer to zero)
        assert abs(score_filled) < abs(score_unfilled)

    def test_score_bounded_between_minus_one_and_one(self):
        """Quality score should always be between -1 and 1"""
        test_cases = [
            ('down', -10.0, False, 0.0),
            ('up', 10.0, False, 0.0),
            ('partial_down', -5.0, True, 100.0),
            ('partial_up', 5.0, True, 100.0),
        ]

        for gap_type, gap_size, is_filled, fill_pct in test_cases:
            score = _calculate_gap_quality_score(
                gap_type=gap_type,
                gap_size_pct=gap_size,
                is_filled=is_filled,
                fill_percentage=fill_pct,
                avg_gap_size=2.0
            )
            assert -1.0 <= score <= 1.0, f"Score {score} out of bounds for {gap_type}"


# =============================================================================
# GAP STATISTICS TESTS
# =============================================================================


class TestCalculateGapStatistics:
    """Tests for calculate_gap_statistics function"""

    def test_statistics_with_gaps(self):
        """Statistics should be calculated from gap data"""
        n = 300  # Need enough data for forward returns
        # Create data with some gaps
        closes = [100.0 + i * 0.2 for i in range(n)]
        opens = [closes[0]] + closes[:-1]

        # Add some gaps
        opens[50] = closes[49] * 1.03  # Up gap
        opens[100] = closes[99] * 0.97  # Down gap
        opens[150] = closes[149] * 1.02  # Up gap

        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]

        stats = calculate_gap_statistics(
            symbol='TEST',
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes
        )

        assert stats is not None
        assert stats.total_gaps >= 0
        assert stats.up_gaps >= 0
        assert stats.down_gaps >= 0

    def test_statistics_insufficient_data(self):
        """Statistics should return None with insufficient data"""
        n = 10  # Not enough for default lookback + forward days
        closes = [100.0 + i for i in range(n)]
        opens = [closes[0]] + closes[:-1]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]

        stats = calculate_gap_statistics(
            symbol='TEST',
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=252
        )

        assert stats is None

    def test_statistics_unequal_arrays(self):
        """Statistics should return None with unequal array lengths"""
        closes = [100.0] * 300
        opens = [100.0] * 299  # Different length
        highs = [101.0] * 300
        lows = [99.0] * 300

        stats = calculate_gap_statistics(
            symbol='TEST',
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes
        )

        assert stats is None

    def test_statistics_fill_rates(self):
        """Statistics should calculate fill rates correctly"""
        n = 300
        closes = [100.0] * n
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n

        # Create a down gap that fills
        opens[50] = 97.0
        closes[49] = 100.0
        lows[49] = 99.0
        highs[50] = 101.0  # Fills the gap

        stats = calculate_gap_statistics(
            symbol='TEST',
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=100
        )

        assert stats is not None
        assert hasattr(stats, 'down_gap_fill_rate')
        assert hasattr(stats, 'up_gap_fill_rate')

    def test_statistics_forward_returns(self):
        """Statistics should calculate forward returns"""
        n = 300
        closes = [100.0 + i * 0.1 for i in range(n)]
        opens = [closes[0]] + closes[:-1]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]

        # Create gaps
        opens[50] = closes[49] * 1.03
        opens[100] = closes[99] * 0.97

        stats = calculate_gap_statistics(
            symbol='TEST',
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            lookback_days=200,
            forward_days=5
        )

        assert stats is not None
        assert hasattr(stats, 'avg_return_after_up_gap_5d')
        assert hasattr(stats, 'avg_return_after_down_gap_5d')
        assert hasattr(stats, 'win_rate_after_up_gap')
        assert hasattr(stats, 'win_rate_after_down_gap')


# =============================================================================
# GAP SERIES TESTS
# =============================================================================


class TestCalculateGapSeries:
    """Tests for calculate_gap_series function"""

    def test_gap_series_length(self):
        """Gap series should have same length as input"""
        n = 50
        closes = [100.0 + i * 0.1 for i in range(n)]
        opens = [closes[0]] + closes[:-1]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]

        series = calculate_gap_series(opens, highs, lows, closes)

        assert len(series) == n

    def test_gap_series_first_element_none(self):
        """First element should be None (no gap for first day)"""
        n = 50
        closes = [100.0 + i * 0.1 for i in range(n)]
        opens = [closes[0]] + closes[:-1]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]

        series = calculate_gap_series(opens, highs, lows, closes)

        assert series[0] is None

    def test_gap_series_insufficient_data(self):
        """Series should return list of Nones for insufficient data"""
        closes = [100.0]
        opens = [100.0]
        highs = [101.0]
        lows = [99.0]

        series = calculate_gap_series(opens, highs, lows, closes)

        assert len(series) == 1
        assert series[0] is None

    def test_gap_series_detects_gaps(self):
        """Series should detect gaps at correct positions"""
        n = 20
        closes = [100.0] * n
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n

        # Create a gap on day 10
        opens[10] = 95.0  # Down gap
        closes[10] = 96.0
        lows[10] = 94.0
        lows[9] = 99.0  # Previous low

        series = calculate_gap_series(opens, highs, lows, closes)

        # Day 10 should have a gap detected
        assert series[10] is not None
        assert series[10].gap_type in ('down', 'partial_down')


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================


class TestGapTypeToScoreFactor:
    """Tests for gap_type_to_score_factor function"""

    def test_down_gap_positive(self):
        """Down gaps should return positive factor"""
        factor = gap_type_to_score_factor('down')
        assert factor > 0
        assert factor == 1.0

    def test_partial_down_gap_positive(self):
        """Partial down gaps should return positive factor"""
        factor = gap_type_to_score_factor('partial_down')
        assert factor > 0
        assert factor == 1.0

    def test_up_gap_negative(self):
        """Up gaps should return negative factor"""
        factor = gap_type_to_score_factor('up')
        assert factor < 0
        assert factor == -1.0

    def test_partial_up_gap_negative(self):
        """Partial up gaps should return negative factor"""
        factor = gap_type_to_score_factor('partial_up')
        assert factor < 0
        assert factor == -1.0

    def test_no_gap_zero(self):
        """No gap should return zero factor"""
        factor = gap_type_to_score_factor('none')
        assert factor == 0

    def test_invalid_gap_type_zero(self):
        """Invalid gap type should return zero factor"""
        factor = gap_type_to_score_factor('invalid')
        assert factor == 0


class TestIsSignificantGap:
    """Tests for is_significant_gap function"""

    def test_large_gap_is_significant(self):
        """Large gaps should be significant"""
        assert is_significant_gap(2.5, threshold=0.5) == True

    def test_small_gap_not_significant(self):
        """Gaps below threshold should not be significant"""
        assert is_significant_gap(0.3, threshold=0.5) == False

    def test_threshold_gap(self):
        """Gap exactly at threshold should be significant"""
        assert is_significant_gap(0.5, threshold=0.5) == True

    def test_negative_gap_is_significant(self):
        """Negative gaps should also be checked by absolute value"""
        assert is_significant_gap(-2.5, threshold=0.5) == True

    def test_default_threshold(self):
        """Default threshold should be MIN_GAP_THRESHOLD_PCT"""
        assert is_significant_gap(0.6) == True
        assert is_significant_gap(0.3) == False

    def test_zero_gap_not_significant(self):
        """Zero gap should not be significant"""
        assert is_significant_gap(0.0, threshold=0.5) == False


class TestGetGapDescription:
    """Tests for get_gap_description function"""

    def test_large_down_gap_description(self):
        """Large down gap should have positive description"""
        gap_result = GapResult(
            gap_type='down',
            gap_size_pct=-4.0,
            gap_size_abs=-4.0,
            is_filled=False,
            fill_percentage=0.0,
            gaps_last_20_days=1,
            avg_gap_size_20d=4.0,
            gap_fill_rate_20d=0.0,
            previous_close=100.0,
            current_open=96.0,
            current_high=98.0,
            current_low=95.0,
            quality_score=0.8
        )
        desc = get_gap_description(gap_result)
        assert 'down' in desc.lower() or 'gap' in desc.lower() or 'abwärts' in desc.lower()
        assert 'bullish' in desc.lower() or 'entry' in desc.lower()

    def test_large_up_gap_description(self):
        """Large up gap should have caution in description"""
        gap_result = GapResult(
            gap_type='up',
            gap_size_pct=4.0,
            gap_size_abs=4.0,
            is_filled=False,
            fill_percentage=0.0,
            gaps_last_20_days=1,
            avg_gap_size_20d=4.0,
            gap_fill_rate_20d=0.0,
            previous_close=100.0,
            current_open=104.0,
            current_high=106.0,
            current_low=103.0,
            quality_score=-0.3
        )
        desc = get_gap_description(gap_result)
        assert 'up' in desc.lower() or 'gap' in desc.lower() or 'aufwärts' in desc.lower()
        assert 'bearish' in desc.lower() or 'vorsicht' in desc.lower() or 'leicht' in desc.lower()

    def test_no_gap_description(self):
        """No gap should have neutral description"""
        gap_result = GapResult(
            gap_type='none',
            gap_size_pct=0.1,
            gap_size_abs=0.1,
            is_filled=False,
            fill_percentage=0.0,
            gaps_last_20_days=0,
            avg_gap_size_20d=0.0,
            gap_fill_rate_20d=0.0,
            previous_close=100.0,
            current_open=100.1,
            current_high=101.0,
            current_low=99.0,
            quality_score=0.0
        )
        desc = get_gap_description(gap_result)
        # German text: "Kein signifikanter Gap"
        assert 'kein' in desc.lower() or 'no' in desc.lower() or 'signifikant' in desc.lower()

    def test_filled_gap_description(self):
        """Filled gap should mention 'gefuellt' or 'filled'"""
        gap_result = GapResult(
            gap_type='down',
            gap_size_pct=-3.0,
            gap_size_abs=-3.0,
            is_filled=True,
            fill_percentage=95.0,
            gaps_last_20_days=1,
            avg_gap_size_20d=3.0,
            gap_fill_rate_20d=0.5,
            previous_close=100.0,
            current_open=97.0,
            current_high=101.0,
            current_low=96.0,
            quality_score=0.4
        )
        desc = get_gap_description(gap_result)
        assert 'gefüllt' in desc.lower() or 'filled' in desc.lower()

    def test_partial_gap_description(self):
        """Partial gap should mention 'Partial'"""
        gap_result = GapResult(
            gap_type='partial_down',
            gap_size_pct=-2.0,
            gap_size_abs=-2.0,
            is_filled=False,
            fill_percentage=30.0,
            gaps_last_20_days=1,
            avg_gap_size_20d=2.0,
            gap_fill_rate_20d=0.3,
            previous_close=100.0,
            current_open=98.0,
            current_high=99.0,
            current_low=97.0,
            quality_score=0.3
        )
        desc = get_gap_description(gap_result)
        assert 'partial' in desc.lower()


# =============================================================================
# PRIVATE HELPER FUNCTION TESTS
# =============================================================================


class TestFindGapFillTime:
    """Tests for _find_gap_fill_time function"""

    def test_down_gap_filled_next_day(self):
        """Down gap filled next day should return 1"""
        fill_time = _find_gap_fill_time(
            gap_type='down',
            gap_open=95.0,
            target_price=100.0,
            highs=[95.0, 101.0, 102.0],  # Fills on day 1
            lows=[94.0, 95.0, 96.0],
            max_days=5
        )
        assert fill_time == 1

    def test_up_gap_filled_on_day_3(self):
        """Up gap filled on day 3 should return 3"""
        fill_time = _find_gap_fill_time(
            gap_type='up',
            gap_open=105.0,
            target_price=100.0,
            highs=[106.0, 106.0, 106.0, 105.0],
            lows=[104.0, 103.0, 102.0, 99.0],  # Fills on day 3
            max_days=5
        )
        assert fill_time == 3

    def test_gap_not_filled(self):
        """Gap not filled within max_days should return None"""
        fill_time = _find_gap_fill_time(
            gap_type='down',
            gap_open=95.0,
            target_price=100.0,
            highs=[96.0, 97.0, 98.0, 99.0],  # Never reaches 100
            lows=[94.0, 95.0, 96.0, 97.0],
            max_days=5
        )
        assert fill_time is None

    def test_gap_filled_exactly_at_max_days(self):
        """Gap filled exactly at max_days boundary should be detected"""
        fill_time = _find_gap_fill_time(
            gap_type='down',
            gap_open=95.0,
            target_price=100.0,
            highs=[96.0, 97.0, 98.0, 101.0],  # Fills on day 3
            lows=[94.0, 95.0, 96.0, 97.0],
            max_days=4
        )
        assert fill_time == 3


class TestCalculateForwardReturns:
    """Tests for _calculate_forward_returns function"""

    def test_forward_returns_calculation(self):
        """Forward returns should be calculated correctly"""
        gaps = [(5, 2.0), (10, 3.0)]  # Gap indices and sizes
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0, 113.0, 114.0, 115.0]
        forward_days = 5

        returns = _calculate_forward_returns(gaps, closes, forward_days)

        assert len(returns) == 2
        # Return from day 5: (110 - 105) / 105 * 100 = 4.76%
        assert returns[0] == pytest.approx(4.7619, rel=0.01)
        # Return from day 10: (115 - 110) / 110 * 100 = 4.55%
        assert returns[1] == pytest.approx(4.5455, rel=0.01)

    def test_forward_returns_empty_gaps(self):
        """Empty gaps list should return empty returns"""
        gaps = []
        closes = [100.0] * 20
        forward_days = 5

        returns = _calculate_forward_returns(gaps, closes, forward_days)

        assert returns == []

    def test_forward_returns_gap_at_end(self):
        """Gap near end without enough forward days should be skipped"""
        gaps = [(15, 2.0)]  # Gap near end
        closes = [100.0] * 18
        forward_days = 5

        returns = _calculate_forward_returns(gaps, closes, forward_days)

        assert returns == []


# =============================================================================
# CONSTANTS TESTS
# =============================================================================


class TestConstants:
    """Tests for module constants"""

    def test_min_gap_threshold_pct(self):
        """MIN_GAP_THRESHOLD_PCT should be a reasonable value"""
        assert MIN_GAP_THRESHOLD_PCT > 0
        assert MIN_GAP_THRESHOLD_PCT < 5.0  # Less than 5%

    def test_gap_fill_threshold_pct(self):
        """GAP_FILL_THRESHOLD_PCT should be high (near 100)"""
        assert GAP_FILL_THRESHOLD_PCT > 80.0
        assert GAP_FILL_THRESHOLD_PCT <= 100.0

    def test_default_lookback_days(self):
        """DEFAULT_LOOKBACK_DAYS should be a reasonable value"""
        assert DEFAULT_LOOKBACK_DAYS >= 5
        assert DEFAULT_LOOKBACK_DAYS <= 60

    def test_stats_lookback_days(self):
        """STATS_LOOKBACK_DAYS should be roughly a year"""
        assert STATS_LOOKBACK_DAYS >= 200
        assert STATS_LOOKBACK_DAYS <= 260

    def test_performance_forward_days(self):
        """PERFORMANCE_FORWARD_DAYS should be a short period"""
        assert PERFORMANCE_FORWARD_DAYS >= 1
        assert PERFORMANCE_FORWARD_DAYS <= 20


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestIntegrationWithContext:
    """Integration tests with AnalysisContext"""

    def test_context_gap_analysis_with_opens(self):
        """AnalysisContext should use real opens for gap detection"""
        from src.analyzers.context import AnalysisContext

        # Create data with a clear down-gap
        n = 30
        closes = [100.0 + i * 0.3 for i in range(n)]
        closes[-1] = closes[-2] * 0.93  # 7% drop

        opens = [c - 0.1 for c in closes]
        opens[-1] = closes[-2] * 0.92  # Gap open

        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        lows[-2] = closes[-2] - 0.3

        volumes = [1000000] * n

        ctx = AnalysisContext.from_data(
            symbol='TEST',
            prices=closes,
            volumes=volumes,
            highs=highs,
            lows=lows,
            opens=opens  # Provide real opens
        )

        # Should detect the gap
        assert ctx.gap_result is not None
        assert ctx.gap_result.gap_type in ('down', 'partial_down')
        assert ctx.gap_score > 0  # Positive score for down-gap

    def test_context_gap_analysis_without_opens(self):
        """AnalysisContext should handle missing opens gracefully"""
        from src.analyzers.context import AnalysisContext

        n = 30
        closes = [100.0 + i * 0.1 for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [1000000] * n

        ctx = AnalysisContext.from_data(
            symbol='TEST',
            prices=closes,
            volumes=volumes,
            highs=highs,
            lows=lows,
            opens=None  # No opens provided
        )

        # Should still work, but use approximated opens
        assert ctx.gap_result is not None
        # With approximated opens (previous close), there should be no gap
        assert ctx.gap_result.gap_type == 'none'


class TestGapResultToDict:
    """Tests for GapResult.to_dict() method"""

    def test_gap_result_to_dict(self):
        """GapResult should convert to dict correctly"""
        gap_result = GapResult(
            gap_type='down',
            gap_size_pct=-3.1234,
            gap_size_abs=-3.12,
            is_filled=False,
            fill_percentage=45.678,
            gaps_last_20_days=5,
            avg_gap_size_20d=2.5678,
            gap_fill_rate_20d=0.6789,
            previous_close=100.0,
            current_open=96.88,
            current_high=98.0,
            current_low=95.0,
            quality_score=0.5678
        )

        d = gap_result.to_dict()

        assert d['gap_type'] == 'down'
        assert d['gap_size_pct'] == pytest.approx(-3.123, rel=0.01)
        assert d['is_filled'] == False
        assert d['fill_percentage'] == pytest.approx(45.7, rel=0.1)
        assert d['gaps_last_20_days'] == 5
        assert d['quality_score'] == pytest.approx(0.568, rel=0.01)


class TestGapStatisticsToDict:
    """Tests for GapStatistics.to_dict() method"""

    def test_gap_statistics_to_dict(self):
        """GapStatistics should convert to dict correctly"""
        stats = GapStatistics(
            symbol='AAPL',
            analysis_period_days=252,
            total_gaps=50,
            up_gaps=25,
            down_gaps=20,
            partial_up_gaps=3,
            partial_down_gaps=2,
            up_gap_fill_rate=0.6789,
            down_gap_fill_rate=0.7890,
            avg_fill_time_days=2.5,
            avg_return_after_up_gap_5d=0.1234,
            avg_return_after_down_gap_5d=0.2345,
            win_rate_after_up_gap=0.5678,
            win_rate_after_down_gap=0.6789
        )

        d = stats.to_dict()

        assert d['symbol'] == 'AAPL'
        assert d['period_days'] == 252
        assert d['total_gaps'] == 50
        assert d['up_gaps'] == 25
        assert d['down_gaps'] == 20
        assert d['up_gap_fill_rate'] == pytest.approx(0.679, rel=0.01)
        assert d['down_gap_fill_rate'] == pytest.approx(0.789, rel=0.01)


# =============================================================================
# EDGE CASE STRESS TESTS
# =============================================================================


class TestStressAndEdgeCases:
    """Stress tests and unusual edge cases"""

    def test_very_small_price_values(self):
        """Should handle very small price values (penny stocks)"""
        result = detect_gap(
            prev_open=0.10,
            prev_high=0.11,
            prev_low=0.09,
            prev_close=0.10,
            curr_open=0.08,  # 20% down gap
            curr_high=0.09,
            curr_low=0.07,
            curr_close=0.08,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'down'
        assert gap_size_pct == pytest.approx(-20.0, rel=0.01)

    def test_very_large_price_values(self):
        """Should handle very large price values"""
        result = detect_gap(
            prev_open=50000.0,
            prev_high=51000.0,
            prev_low=49000.0,
            prev_close=50000.0,
            curr_open=52000.0,  # 4% up gap
            curr_high=53000.0,
            curr_low=51500.0,
            curr_close=52500.0,
            min_gap_pct=0.5
        )

        gap_type, gap_size_pct, gap_size_abs, is_filled, fill_pct = result
        assert gap_type == 'up'
        assert gap_size_pct == pytest.approx(4.0, rel=0.01)

    def test_all_same_prices(self):
        """Should handle data where all prices are identical"""
        n = 30
        closes = [100.0] * n
        opens = [100.0] * n
        highs = [100.0] * n
        lows = [100.0] * n

        result = analyze_gap(opens, highs, lows, closes)

        assert result is not None
        assert result.gap_type == 'none'
        assert result.gap_size_pct == 0.0

    def test_alternating_gaps(self):
        """Should handle alternating up/down gaps"""
        n = 30
        closes = [100.0] * n
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n

        # Create alternating gaps
        for i in range(1, n):
            if i % 2 == 0:
                opens[i] = 103.0  # Up gap
            else:
                opens[i] = 97.0  # Down gap

        result = analyze_gap(opens, highs, lows, closes)

        assert result is not None
        assert result.gaps_last_20_days > 0

    def test_long_time_series(self):
        """Should handle very long time series efficiently"""
        n = 1000
        closes = [100.0 + i * 0.01 for i in range(n)]
        opens = [closes[0]] + closes[:-1]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]

        # Add some gaps
        for i in range(50, n, 100):
            opens[i] = closes[i-1] * 1.02

        result = analyze_gap(opens, highs, lows, closes)

        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
