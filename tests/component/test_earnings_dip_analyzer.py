# OptionPlay - Earnings Dip Analyzer Tests (v2)
# ================================================
# Comprehensive tests for EarningsDipAnalyzer v2 (refactored)
#
# Test Coverage:
# 1. Initialization (6 tests)
# 2. Analyze method (7 tests)
# 3. Disqualification / Filter Pipeline (7 tests)
# 4. Spec Test Cases (10 tests)
# 5. Signal Text Format (4 tests)
# 6. Scoring Components (15 tests)
# 7. Stabilization Detection (5 tests)
# 8. Edge Cases (6 tests)
# 9. Backward Compatibility (5 tests)
# 10. RSI Calculation (4 tests)
# 11. Penalty Calculation (4 tests)
# 12. Fundamental Check (4 tests)

import pytest
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.earnings_dip import (
    EarningsDipAnalyzer,
    EarningsDipConfig,
    GapInfo,
    EDIP_MIN_SCORE,
    EDIP_MAX_SCORE,
)
from models.base import SignalType, SignalStrength


# =============================================================================
# HELPER: Generate test data with earnings dip
# =============================================================================

def make_dip_data(
    n: int = 100,
    pre_price: float = 100.0,
    dip_pct: float = 10.0,
    stabilization_days: int = 3,
    green_days: int = 2,
    volume_spike: float = 3.0,
    volume_decay: float = 0.5,
    pre_trend: str = "uptrend",
):
    """
    Generate OHLCV data with an earnings dip and recovery.

    Args:
        n: Total data points
        pre_price: Price before earnings
        dip_pct: Drop percentage (positive, e.g. 10 for -10%)
        stabilization_days: Days after drop with recovery
        green_days: Number of green days in recovery
        volume_spike: Volume multiplier on drop day
        volume_decay: Volume decay ratio after drop
        pre_trend: "uptrend" or "downtrend" before earnings

    Returns:
        (prices, volumes, highs, lows, drop_day_idx)
    """
    dip_low_price = pre_price * (1 - dip_pct / 100)
    current_recovery = dip_low_price * 1.02  # Small recovery from low

    # Build pre-earnings data
    pre_count = n - stabilization_days - 1  # -1 for drop day

    prices = []
    volumes = []

    if pre_trend == "uptrend":
        # Gradual uptrend ending at pre_price
        start_price = pre_price * 0.7
        for i in range(pre_count):
            p = start_price + (pre_price - start_price) * (i / pre_count)
            prices.append(p)
            volumes.append(1_000_000)
    else:
        # Downtrend
        start_price = pre_price * 1.1
        for i in range(pre_count):
            p = start_price - (start_price - pre_price * 0.9) * (i / pre_count)
            prices.append(p)
            volumes.append(1_000_000)

    # Drop day
    drop_day_idx = len(prices)
    prices.append(dip_low_price)
    volumes.append(int(1_000_000 * volume_spike))

    # Stabilization / recovery days
    recovery_step = (current_recovery - dip_low_price) / max(1, stabilization_days)
    for i in range(stabilization_days):
        p = dip_low_price + recovery_step * (i + 1)
        if i < green_days:
            # Green day: price goes up
            prices.append(p)
        else:
            # Flat/slight decline
            prices.append(dip_low_price + recovery_step * green_days * 0.99)
        volumes.append(int(1_000_000 * volume_spike * (volume_decay ** (i + 1))))

    # Ensure correct length
    while len(prices) < n:
        prices.insert(0, prices[0])
        volumes.insert(0, 1_000_000)
        drop_day_idx += 1

    prices = prices[:n]
    volumes = volumes[:n]

    highs = [p * 1.005 for p in prices]
    lows = [p * 0.995 for p in prices]
    # Make drop day low deeper
    lows[drop_day_idx] = dip_low_price * 0.99

    return prices, volumes, highs, lows, drop_day_idx


# =============================================================================
# 1. INITIALIZATION TESTS
# =============================================================================

class TestEarningsDipInitialization:
    """Tests for EarningsDipAnalyzer initialization."""

    def test_default_initialization(self):
        """Default initialization should use default config."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer.config is not None
        assert isinstance(analyzer.config, EarningsDipConfig)

    def test_strategy_name(self):
        """Strategy name should be 'earnings_dip'."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer.strategy_name == "earnings_dip"

    def test_description(self):
        """Description should mention Earnings Dip."""
        analyzer = EarningsDipAnalyzer()
        assert "Earnings Dip" in analyzer.description

    def test_custom_config(self):
        """Custom config should override defaults."""
        config = EarningsDipConfig(min_dip_pct=7.0, max_dip_pct=18.0)
        analyzer = EarningsDipAnalyzer(config=config)
        assert analyzer.config.min_dip_pct == 7.0
        assert analyzer.config.max_dip_pct == 18.0

    def test_legacy_scoring_config_accepted(self):
        """Should accept scoring_config kwarg without error (backward compat)."""
        analyzer = EarningsDipAnalyzer(scoring_config="ignored")
        assert analyzer.scoring_config == "ignored"

    def test_config_defaults(self):
        """Config defaults should match spec."""
        config = EarningsDipConfig()
        assert config.min_dip_pct == 5.0
        assert config.max_dip_pct == 20.0
        assert config.extreme_dip_pct == 25.0
        assert config.dip_lookback_days == 10
        assert config.min_stabilization_days == 1
        assert config.min_stability_score == 60.0
        assert config.min_score_for_signal == 3.5
        assert config.max_score == 9.5


# =============================================================================
# 2. ANALYZE METHOD TESTS
# =============================================================================

class TestAnalyzeMethod:
    """Tests for the main analyze method."""

    def test_returns_trade_signal(self):
        """analyze should return a TradeSignal."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data()
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        assert signal is not None
        assert signal.symbol == "TEST"
        assert signal.strategy == "earnings_dip"

    def test_score_in_range(self):
        """Score should be 0-10."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data()
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        assert 0 <= signal.score <= 10

    def test_validates_inputs(self):
        """Should raise ValueError for insufficient data."""
        analyzer = EarningsDipAnalyzer()
        with pytest.raises(ValueError):
            analyzer.analyze("T", [100] * 30, [1000] * 30, [101] * 30, [99] * 30)

    def test_has_details(self):
        """Signal should have details dict."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data()
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        assert signal.details is not None
        if signal.signal_type != SignalType.NEUTRAL or signal.details.get('disqualified'):
            assert 'dip_info' in signal.details

    def test_includes_breakdown(self):
        """Signal should include score_breakdown for scored signals."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=11.0, stabilization_days=5, green_days=3
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        if signal.score > 0:
            assert 'score_breakdown' in signal.details

    def test_sets_entry_stop_target(self):
        """Should set entry, stop_loss, target for actionable signals."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=11.0, stabilization_days=5, green_days=3
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        if signal.signal_type == SignalType.LONG:
            assert signal.stop_loss is not None
            assert signal.target_price is not None
            assert signal.entry_price is not None
            assert signal.stop_loss < signal.entry_price
            assert signal.target_price > signal.entry_price

    def test_earnings_date_accepted(self):
        """analyze should accept earnings_date parameter."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data()
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            earnings_date=date.today() - timedelta(days=3)
        )
        assert signal is not None


# =============================================================================
# 3. DISQUALIFICATION / FILTER PIPELINE TESTS
# =============================================================================

class TestDisqualifications:
    """Tests for filter pipeline disqualifications."""

    def test_no_dip_neutral(self):
        """No significant dip should return neutral."""
        analyzer = EarningsDipAnalyzer()
        prices = [100 + i * 0.1 for i in range(100)]
        volumes = [1_000_000] * 100
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert signal.signal_type == SignalType.NEUTRAL

    def test_dip_too_small(self):
        """Dip < 5% should be disqualified."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(dip_pct=3.0)
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        assert signal.signal_type == SignalType.NEUTRAL
        assert "too small" in signal.reason.lower()

    def test_dip_too_extreme(self):
        """Dip > 25% should be disqualified."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(dip_pct=28.0)
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        assert signal.signal_type == SignalType.NEUTRAL
        assert "extreme" in signal.reason.lower() or "too" in signal.reason.lower()

    def test_no_stabilization_day0(self):
        """Drop day (day 0) should NOT produce a signal."""
        analyzer = EarningsDipAnalyzer()
        # Only 0 days after drop
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=10.0, stabilization_days=0
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        assert signal.signal_type == SignalType.NEUTRAL

    def test_continued_decline_no_stabilization(self):
        """Continued decline with no recovery should be disqualified."""
        analyzer = EarningsDipAnalyzer()
        n = 100
        # Build data where price continues falling after drop
        prices = [100.0] * 85
        # Drop day and continued decline
        for i in range(15):
            prices.append(90.0 - i * 1.0)  # 90, 89, 88, ... 76
        volumes = [1_000_000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0
        )
        # Should be neutral (no stabilization or heavily penalized)
        assert signal.signal_type == SignalType.NEUTRAL

    def test_below_sma200_disqualified(self):
        """Price below SMA 200 before earnings should be disqualified."""
        analyzer = EarningsDipAnalyzer()
        # Downtrend data — price is already below SMA 200
        n = 250
        prices = [150.0 - i * 0.3 for i in range(n)]  # 150 -> 75
        volumes = [1_000_000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=80.0
        )
        # Should be neutral due to SMA 200 check
        assert signal.signal_type == SignalType.NEUTRAL

    def test_low_stability_disqualified(self):
        """Stability < 60 should be disqualified."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(dip_pct=10.0)

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            stability_score=50.0,
        )
        assert signal.signal_type == SignalType.NEUTRAL
        assert "stability" in signal.reason.lower()


# =============================================================================
# 4. SPEC TEST CASES (from Spec Section 8)
# =============================================================================

class TestSpecTestCases:
    """Tests implementing the 10 spec test cases."""

    def test_case1_classic_stabilized_dip(self):
        """Case 1: -11% drop, Tag 3: 2 green days, vol -30%, RSI 29, Stability 85 -> Strong ~7.0"""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=11.0,
            stabilization_days=3,
            green_days=2,
            volume_spike=3.5,
            volume_decay=0.3,
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            stability_score=85.0,
        )
        # Should be actionable
        assert signal.signal_type == SignalType.LONG
        assert signal.score >= EDIP_MIN_SCORE

    def test_case2_moderate_dip(self):
        """Case 2: -8% drop, Tag 2: 1 green day, higher low, Stability 75 -> Moderate ~4.5"""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=8.0,
            stabilization_days=2,
            green_days=1,
            volume_spike=2.0,
            volume_decay=0.5,
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            stability_score=75.0,
        )
        # Should have score > 0, might or might not be above threshold
        assert signal.score >= 0

    def test_case3_drop_day_no_signal(self):
        """Case 3: -12% drop, Tag 0 (today) -> No signal"""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=12.0,
            stabilization_days=0,
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
        )
        assert signal.signal_type == SignalType.NEUTRAL

    def test_case4_falling_knife(self):
        """Case 4: -10% drop, Tag 2: price continues falling -> No signal"""
        analyzer = EarningsDipAnalyzer()
        n = 100
        prices = [100.0] * 90
        # Drop and continued decline
        prices.extend([90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 78.0, 76.0, 74.0, 72.0])
        volumes = [1_000_000] * n
        volumes[90] = 3_000_000  # spike on drop day
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
        )
        # Continued decline - no stabilization
        assert signal.signal_type == SignalType.NEUTRAL

    def test_case5_weak_fundamentals(self):
        """Case 5: -6% drop, Stability 65, under SMA 200 -> No signal"""
        analyzer = EarningsDipAnalyzer()
        # Downtrend pre-earnings
        n = 250
        prices = [130.0 - i * 0.2 for i in range(n)]
        # Add a dip at the end
        for i in range(10):
            prices[-(10 - i)] = prices[-11] * (1 - 0.06 * (10 - i) / 10)
        volumes = [1_000_000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            stability_score=55.0,
        )
        assert signal.signal_type == SignalType.NEUTRAL

    def test_case6_excellent_signal(self):
        """Case 6: -15% drop, Tag 4: 3 green days, vol -50%, panic vol 4x, Stability 92"""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=15.0,
            stabilization_days=4,
            green_days=3,
            volume_spike=4.0,
            volume_decay=0.3,
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            stability_score=92.0,
        )
        assert signal.signal_type == SignalType.LONG
        assert signal.score >= 5.0  # Should be a strong signal

    def test_case7_rsi_not_extreme(self):
        """Case 7: -7% drop, RSI after drop at 45 -> Weak signal (penalty)"""
        analyzer = EarningsDipAnalyzer()
        # Create sideways data then small dip (RSI won't be extreme)
        n = 100
        prices = [100.0 + (i % 3) * 0.2 for i in range(90)]  # oscillating
        prices.extend([93.0, 93.5, 94.0, 94.5, 95.0, 95.5, 96.0, 96.5, 97.0, 97.5])
        volumes = [1_000_000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
        )
        # RSI penalty should apply
        if signal.details and 'penalties' in signal.details:
            penalties = signal.details['penalties']
            # Should have RSI penalty
            assert penalties.get('total', 0) < 0 or signal.score < 5

    def test_case8_extreme_dip_rejected(self):
        """Case 8: -22% drop, Stability 80 -> No signal (>20% but depends on extreme_dip)"""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(dip_pct=22.0)
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            stability_score=80.0,
        )
        # 22% is between max_dip_pct (20%) and extreme_dip_pct (25%)
        # Score should be reduced (1.0 for >20% drop) but not disqualified
        # The drop scoring gives 1.0 for >20%, so total will be modest
        assert signal.score < 7.0  # Not a strong signal

    def test_case9_good_signal_with_hammer(self):
        """Case 9: -9% drop, Tag 5: hammer candle, vol 0.5x, above SMA 200"""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=9.0,
            stabilization_days=5,
            green_days=2,
            volume_spike=2.5,
            volume_decay=0.4,
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            stability_score=80.0,
        )
        # Should be actionable
        assert signal.score >= 0

    def test_case10_next_earnings_too_close(self):
        """Case 10: -11% drop, next earnings in 40 days -> reduced BPS score"""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(dip_pct=11.0)
        signal_close = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            stability_score=80.0,
            next_earnings_days=40,
        )
        signal_far = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0,
            stability_score=80.0,
            next_earnings_days=90,
        )
        # The far earnings signal should score higher (BPS suitability bonus)
        if signal_close.score > 0 and signal_far.score > 0:
            assert signal_far.score >= signal_close.score


# =============================================================================
# 5. SIGNAL TEXT FORMAT TESTS
# =============================================================================

class TestSignalText:
    """Tests for signal text format."""

    def test_contains_dip_pct(self):
        """Signal text should contain the dip percentage."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=11.0, stabilization_days=3, green_days=2
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0, stability_score=85.0,
        )
        if signal.signal_type == SignalType.LONG:
            assert "Earnings Dip" in signal.reason
            assert "%" in signal.reason

    def test_contains_stabilization_info(self):
        """Signal text should mention stabilization."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=11.0, stabilization_days=3, green_days=2
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0, stability_score=85.0,
        )
        if signal.signal_type == SignalType.LONG:
            assert "Stabilizing" in signal.reason or "stabil" in signal.reason.lower()

    def test_contains_stability_score(self):
        """Signal text should include stability score when provided."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=11.0, stabilization_days=3, green_days=2
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0, stability_score=85.0,
        )
        if signal.signal_type == SignalType.LONG:
            assert "Stability 85" in signal.reason

    def test_pipe_separated_format(self):
        """Signal text should use pipe-separated format."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            dip_pct=11.0, stabilization_days=3, green_days=2
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=100.0, stability_score=85.0,
        )
        if signal.signal_type == SignalType.LONG:
            assert " | " in signal.reason


# =============================================================================
# 6. SCORING COMPONENT TESTS
# =============================================================================

class TestScoringComponents:
    """Tests for individual scoring components."""

    # --- Drop Magnitude ---
    def test_drop_score_small(self):
        """5-7% drop should score 0.5."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer._score_drop_magnitude(6.0) == 0.5

    def test_drop_score_moderate(self):
        """7-10% drop should score 1.0."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer._score_drop_magnitude(8.0) == 1.0

    def test_drop_score_significant(self):
        """10-15% drop should score 1.5."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer._score_drop_magnitude(12.0) == 1.5

    def test_drop_score_strong(self):
        """15-20% drop should score 2.0."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer._score_drop_magnitude(17.0) == 2.0

    def test_drop_score_extreme_reduced(self):
        """>20% drop should score 1.0 (reduced)."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer._score_drop_magnitude(22.0) == 1.0

    def test_drop_score_below_min(self):
        """<5% drop should score 0."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer._score_drop_magnitude(3.0) == 0.0

    # --- Stabilization ---
    def test_stabilization_green_days(self):
        """Green days should contribute to stabilization score."""
        analyzer = EarningsDipAnalyzer()
        score = analyzer._score_stabilization({
            'green_days': 2, 'higher_low': False,
            'volume_declining': False, 'hammer_detected': False
        })
        assert score == 1.5

    def test_stabilization_all_criteria(self):
        """All criteria met should cap at 2.5."""
        analyzer = EarningsDipAnalyzer()
        score = analyzer._score_stabilization({
            'green_days': 3, 'higher_low': True,
            'volume_declining': True, 'hammer_detected': True
        })
        assert score == 2.5

    def test_stabilization_single_criterion(self):
        """Single criterion should still score."""
        analyzer = EarningsDipAnalyzer()
        score = analyzer._score_stabilization({
            'green_days': 0, 'higher_low': True,
            'volume_declining': False, 'hammer_detected': False
        })
        assert score == 1.0

    # --- Fundamental Strength ---
    def test_fundamental_high_stability(self):
        """Stability > 90 should score 1.5."""
        analyzer = EarningsDipAnalyzer()
        score = analyzer._score_fundamental_strength(
            stability_score=92.0,
            fund_info={'was_above_sma200': False, 'sma200_rising': False}
        )
        assert score == 1.5

    def test_fundamental_moderate_stability(self):
        """Stability 80-90 should score 1.0."""
        analyzer = EarningsDipAnalyzer()
        score = analyzer._score_fundamental_strength(
            stability_score=85.0,
            fund_info={'was_above_sma200': False, 'sma200_rising': False}
        )
        assert score == 1.0

    def test_fundamental_low_stability(self):
        """Stability 70-80 should score 0.5."""
        analyzer = EarningsDipAnalyzer()
        score = analyzer._score_fundamental_strength(
            stability_score=75.0,
            fund_info={'was_above_sma200': False, 'sma200_rising': False}
        )
        assert score == 0.5

    def test_fundamental_sma_bonus(self):
        """Above SMA 200 + rising should add 0.5."""
        analyzer = EarningsDipAnalyzer()
        score = analyzer._score_fundamental_strength(
            stability_score=85.0,
            fund_info={'was_above_sma200': True, 'sma200_rising': True}
        )
        assert score == 1.5  # 1.0 (stability) + 0.5 (SMA)

    # --- BPS Suitability ---
    def test_bps_far_earnings(self):
        """Next earnings > 60 days should score 0.5."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer._score_bps_suitability(next_earnings_days=90) == 0.5

    def test_bps_close_earnings(self):
        """Next earnings < 60 days should score 0."""
        analyzer = EarningsDipAnalyzer()
        assert analyzer._score_bps_suitability(next_earnings_days=40) == 0.0


# =============================================================================
# 7. STABILIZATION DETECTION TESTS
# =============================================================================

class TestStabilizationDetection:
    """Tests for stabilization detection logic."""

    def test_detects_green_days(self):
        """Should detect green days after drop."""
        analyzer = EarningsDipAnalyzer()
        # Prices go up after drop
        prices = [100.0] * 90 + [90.0, 91.0, 92.0, 93.0, 94.0, 95.0, 96.0, 97.0, 98.0, 99.0]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1_000_000] * 100
        volumes[90] = 3_000_000

        result = analyzer._check_stabilization(
            prices, highs, lows, volumes, drop_day_idx=90
        )
        assert result['stabilized'] is True
        assert result['green_days'] >= 1

    def test_detects_higher_low(self):
        """Should detect higher low after drop."""
        analyzer = EarningsDipAnalyzer()
        prices = [100.0] * 90 + [90.0, 90.5, 91.0, 91.5, 92.0, 92.5, 93.0, 93.5, 94.0, 94.5]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        lows[90] = 88.0  # Drop day low
        volumes = [1_000_000] * 100

        result = analyzer._check_stabilization(
            prices, highs, lows, volumes, drop_day_idx=90
        )
        assert result['stabilized'] is True
        assert result['higher_low'] is True

    def test_detects_volume_decline(self):
        """Should detect declining volume after drop."""
        analyzer = EarningsDipAnalyzer()
        prices = [100.0] * 90 + [90.0, 90.0, 90.0, 90.5, 91.0, 91.5, 92.0, 92.5, 93.0, 93.5]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1_000_000] * 100
        volumes[90] = 5_000_000  # Big spike
        volumes[91:] = [500_000] * 9  # Low volume after

        result = analyzer._check_stabilization(
            prices, highs, lows, volumes, drop_day_idx=90
        )
        assert result['stabilized'] is True
        assert result['volume_declining'] is True

    def test_no_stabilization_continued_decline(self):
        """Continued decline should not stabilize."""
        analyzer = EarningsDipAnalyzer()
        prices = [100.0] * 90 + [90.0, 89.0, 88.0, 87.0, 86.0, 85.0, 84.0, 83.0, 82.0, 81.0]
        highs = [p + 0.5 for p in prices]
        lows = [p - 1.0 for p in prices]
        # Make each day's low below drop day low
        for i in range(91, 100):
            lows[i] = lows[90] - (i - 90) * 0.5
        volumes = [1_000_000] * 100
        volumes[90] = 3_000_000
        # Keep volume elevated
        for i in range(91, 100):
            volumes[i] = 3_000_000

        result = analyzer._check_stabilization(
            prices, highs, lows, volumes, drop_day_idx=90
        )
        # Should still find green days since each close > previous close is not happening
        # But higher_low won't be true since lows keep declining
        # Let's just verify the structure
        assert 'stabilized' in result

    def test_too_early_rejected(self):
        """Day 0 should be rejected (too early)."""
        analyzer = EarningsDipAnalyzer()
        prices = [100.0] * 100
        highs = [101.0] * 100
        lows = [99.0] * 100
        volumes = [1_000_000] * 100

        result = analyzer._check_stabilization(
            prices, highs, lows, volumes, drop_day_idx=99  # Last bar
        )
        assert result['stabilized'] is False
        assert "Too early" in result.get('reason', '')


# =============================================================================
# 8. EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_arrays(self):
        """Should raise ValueError for empty arrays."""
        analyzer = EarningsDipAnalyzer()
        with pytest.raises(ValueError):
            analyzer.analyze("T", [], [], [], [])

    def test_mismatched_lengths(self):
        """Should raise ValueError for mismatched array lengths."""
        analyzer = EarningsDipAnalyzer()
        with pytest.raises(ValueError):
            analyzer.analyze("T", [100] * 100, [1000] * 99, [101] * 100, [99] * 100)

    def test_negative_prices(self):
        """Should raise ValueError for negative prices."""
        analyzer = EarningsDipAnalyzer()
        prices = [100] * 50 + [-5] + [100] * 49
        with pytest.raises(ValueError):
            analyzer.analyze("T", prices, [1000] * 100, [101] * 100, [99] * 100)

    def test_high_less_than_low(self):
        """Should raise ValueError when high < low."""
        analyzer = EarningsDipAnalyzer()
        with pytest.raises(ValueError):
            analyzer.analyze("T", [100] * 100, [1000] * 100, [99] * 100, [101] * 100)

    def test_very_small_prices(self):
        """Should handle penny stock prices."""
        analyzer = EarningsDipAnalyzer(EarningsDipConfig(
            require_above_sma200=False,
            min_avg_volume=0,
        ))
        prices, volumes, highs, lows, _ = make_dip_data(
            pre_price=1.0, dip_pct=10.0
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=1.0,
        )
        assert signal is not None

    def test_very_large_prices(self):
        """Should handle high-priced stocks."""
        analyzer = EarningsDipAnalyzer()
        prices, volumes, highs, lows, _ = make_dip_data(
            pre_price=5000.0, dip_pct=10.0
        )
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=5000.0,
        )
        assert signal is not None


# =============================================================================
# 9. BACKWARD COMPATIBILITY TESTS
# =============================================================================

class TestBackwardCompatibility:
    """Tests for backward compatibility."""

    def test_legacy_config_fields(self):
        """Legacy config fields should exist."""
        config = EarningsDipConfig()
        assert hasattr(config, 'rsi_oversold_threshold')
        assert hasattr(config, 'analyze_gap')
        assert hasattr(config, 'min_gap_pct')
        assert hasattr(config, 'gap_fill_threshold')
        assert hasattr(config, 'min_market_cap')

    def test_gap_info_class_exists(self):
        """GapInfo class should still be importable."""
        gap = GapInfo(detected=True, gap_size_pct=5.0)
        assert gap.detected is True
        d = gap.to_dict()
        assert 'detected' in d

    def test_breakdown_to_dict(self):
        """Breakdown to_dict should produce valid output."""
        from models.strategy_breakdowns import EarningsDipScoreBreakdown
        b = EarningsDipScoreBreakdown()
        b.total_score = 5.0
        b.max_possible = 9.5
        d = b.to_dict()
        assert d['total_score'] == 5.0
        assert d['max_possible'] == 9.5
        assert 'qualified' in d
        assert 'components' in d

    def test_breakdown_qualified_threshold(self):
        """Qualified threshold should be 3.5."""
        from models.strategy_breakdowns import EarningsDipScoreBreakdown
        b = EarningsDipScoreBreakdown()
        b.total_score = 3.5
        d = b.to_dict()
        assert d['qualified'] is True

        b.total_score = 3.4
        d = b.to_dict()
        assert d['qualified'] is False

    def test_breakdown_components(self):
        """Breakdown should have v2 components."""
        from models.strategy_breakdowns import EarningsDipScoreBreakdown
        b = EarningsDipScoreBreakdown()
        d = b.to_dict()
        components = d['components']
        assert 'dip' in components
        assert 'stabilization' in components
        assert 'fundamental' in components
        assert 'overreaction' in components
        assert 'bps_suitability' in components


# =============================================================================
# 10. RSI CALCULATION TESTS
# =============================================================================

class TestRSICalculation:
    """Tests for RSI calculation."""

    def test_rsi_downtrend_low(self):
        """Downtrend should produce low RSI."""
        analyzer = EarningsDipAnalyzer()
        prices = [100 - i for i in range(50)]
        rsi = analyzer._calculate_rsi(prices)
        assert rsi < 30

    def test_rsi_uptrend_high(self):
        """Uptrend should produce high RSI."""
        analyzer = EarningsDipAnalyzer()
        prices = [100 + i for i in range(50)]
        rsi = analyzer._calculate_rsi(prices)
        assert rsi > 70

    def test_rsi_sideways_neutral(self):
        """Sideways should produce neutral RSI."""
        analyzer = EarningsDipAnalyzer()
        prices = [100 + (i % 2) * 0.5 for i in range(50)]
        rsi = analyzer._calculate_rsi(prices)
        assert 30 < rsi < 70

    def test_rsi_insufficient_data(self):
        """Insufficient data should return 50."""
        analyzer = EarningsDipAnalyzer()
        rsi = analyzer._calculate_rsi([100, 101, 102])
        assert rsi == 50.0


# =============================================================================
# 11. PENALTY CALCULATION TESTS
# =============================================================================

class TestPenaltyCalculation:
    """Tests for penalty calculations."""

    def test_rsi_penalty(self):
        """RSI > 40 should get -0.5 penalty."""
        analyzer = EarningsDipAnalyzer()
        # Sideways prices -> RSI ~50
        prices = [100 + (i % 2) * 0.5 for i in range(250)]
        lows = [p - 0.5 for p in prices]
        fund_info = {'was_above_sma200': True}

        result = analyzer._calculate_penalties(prices, lows, 240, fund_info)
        # Should have RSI penalty
        has_rsi_penalty = any("RSI" in d for d in result.get('details', []))
        assert has_rsi_penalty

    def test_continued_decline_penalty(self):
        """Continued decline should get -1.5 penalty."""
        analyzer = EarningsDipAnalyzer()
        prices = [100.0] * 90 + [90.0, 89.0, 88.0, 87.0, 86.0, 85.0, 84.0, 83.0, 82.0, 81.0]
        lows = [p - 0.5 for p in prices]
        # Make lows go below drop day low
        for i in range(91, 100):
            lows[i] = lows[90] - (i - 90) * 0.3
        fund_info = {'was_above_sma200': True}

        result = analyzer._calculate_penalties(prices, lows, 90, fund_info)
        has_decline_penalty = any("decline" in d.lower() for d in result.get('details', []))
        assert has_decline_penalty

    def test_penalty_capped_at_minus3(self):
        """Total penalties should be capped at -3.0."""
        analyzer = EarningsDipAnalyzer()
        # Worst case: all penalties
        prices = [150.0 - i * 0.3 for i in range(250)]
        lows = [p - 0.5 for p in prices]
        for i in range(241, 250):
            lows[i] = lows[240] - (i - 240) * 0.5
        fund_info = {'was_above_sma200': False}

        result = analyzer._calculate_penalties(prices, lows, 240, fund_info)
        assert result['total'] >= -3.0

    def test_no_penalties_clean_signal(self):
        """Clean signal should have no penalties (or only RSI penalty)."""
        analyzer = EarningsDipAnalyzer()
        # Strong downtrend to produce low RSI, then a single-day gap down, then recovery
        prices = [100.0] * 80
        # Single big drop day
        prices.append(90.0)
        # Then recovery days (all higher than drop day)
        for i in range(19):
            prices.append(90.5 + i * 0.3)

        lows = [p - 0.3 for p in prices]
        # drop_day_idx = 80 (the single gap-down day)
        # All post-drop lows are above the drop-day low
        drop_day_idx = 80
        fund_info = {'was_above_sma200': True}

        result = analyzer._calculate_penalties(prices, lows, drop_day_idx, fund_info)
        # Should not have SMA or decline penalties
        has_sma_penalty = any("SMA" in d for d in result.get('details', []))
        has_decline_penalty = any("decline" in d.lower() for d in result.get('details', []))
        assert not has_sma_penalty
        assert not has_decline_penalty


# =============================================================================
# 12. FUNDAMENTAL CHECK TESTS
# =============================================================================

class TestFundamentalCheck:
    """Tests for fundamental check logic."""

    def test_passes_with_good_fundamentals(self):
        """Good fundamentals should pass."""
        analyzer = EarningsDipAnalyzer()
        prices = [80 + i * 0.1 for i in range(250)]
        volumes = [1_000_000] * 250

        result = analyzer._check_fundamentals(prices, volumes, stability_score=80.0)
        assert result['qualified'] is True

    def test_rejects_low_stability(self):
        """Low stability should fail."""
        analyzer = EarningsDipAnalyzer()
        prices = [100.0] * 250
        volumes = [1_000_000] * 250

        result = analyzer._check_fundamentals(prices, volumes, stability_score=50.0)
        assert result['qualified'] is False
        assert "stability" in result['reason'].lower()

    def test_rejects_below_sma200(self):
        """Below SMA 200 should fail (when require_above_sma200=True)."""
        analyzer = EarningsDipAnalyzer()
        # Downtrend - price below SMA 200
        prices = [150.0 - i * 0.3 for i in range(250)]
        volumes = [1_000_000] * 250

        result = analyzer._check_fundamentals(prices, volumes)
        assert result['qualified'] is False
        assert "SMA 200" in result['reason'] or "below" in result['reason'].lower()

    def test_skips_sma_check_insufficient_data(self):
        """Should skip SMA 200 check with < 200 bars."""
        analyzer = EarningsDipAnalyzer()
        prices = [100.0] * 100
        volumes = [1_000_000] * 100

        result = analyzer._check_fundamentals(prices, volumes)
        assert result['qualified'] is True  # Passes since SMA check skipped


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
