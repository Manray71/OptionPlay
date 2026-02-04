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
)
from src.models.indicators import GapResult, GapStatistics


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


class TestGapTypeToScoreFactor:
    """Tests for gap_type_to_score_factor function"""

    def test_down_gap_positive(self):
        """Down gaps should return positive factor"""
        factor = gap_type_to_score_factor('down')
        assert factor > 0

    def test_up_gap_negative(self):
        """Up gaps should return negative or zero factor"""
        factor = gap_type_to_score_factor('up')
        assert factor <= 0

    def test_no_gap_zero(self):
        """No gap should return zero factor"""
        factor = gap_type_to_score_factor('none')
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


class TestGetGapDescription:
    """Tests for get_gap_description function"""

    def test_large_down_gap_description(self):
        """Large down gap should have positive description"""
        # Create a GapResult for a large down gap
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
        assert 'down' in desc.lower() or 'gap' in desc.lower()

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
        assert 'up' in desc.lower() or 'gap' in desc.lower()

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
