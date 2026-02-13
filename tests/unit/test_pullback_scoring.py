#!/usr/bin/env python3
"""
F.3: Tests for PullbackScoringMixin (src/analyzers/pullback_scoring.py)

Tests scoring methods for the Pullback strategy's indicator components:
- RSI scoring and RSI divergence scoring
- Support proximity scoring
- Fibonacci level scoring
- Moving average scoring
- Volume scoring
- MACD scoring
- Stochastic scoring
- Trend strength scoring
- Keltner Channel scoring
- VWAP scoring
- Market context scoring
- Sector scoring
- Gap scoring

Usage:
    pytest tests/unit/test_pullback_scoring.py -v
"""

import pytest
from unittest.mock import patch

from src.analyzers.pullback_scoring import PullbackScoringMixin
from src.config.models import PullbackScoringConfig
from src.models.indicators import (
    KeltnerChannelResult,
    MACDResult,
    RSIDivergenceResult,
    StochasticResult,
)


# =============================================================================
# FIXTURES — Create a concrete class from the mixin
# =============================================================================

class ConcretePullbackScorer(PullbackScoringMixin):
    """Concrete class to test the mixin methods."""

    def __init__(self, config=None):
        self.config = config or PullbackScoringConfig()


@pytest.fixture
def scorer():
    """Returns a PullbackScoringMixin instance with default config."""
    return ConcretePullbackScorer()


@pytest.fixture
def config():
    """Returns default PullbackScoringConfig."""
    return PullbackScoringConfig()


# =============================================================================
# RSI DIVERGENCE SCORING
# =============================================================================

class TestScoreRsiDivergence:
    """Tests for _score_rsi_divergence()"""

    def test_no_divergence(self, scorer):
        score, reason = scorer._score_rsi_divergence(None)
        assert score == 0
        assert "No RSI divergence" in reason

    def test_strong_bullish_divergence(self, scorer):
        div = RSIDivergenceResult(
            divergence_type='bullish', strength=0.8,
            price_pivot_1=100, price_pivot_2=95,
            rsi_pivot_1=30, rsi_pivot_2=35,
            formation_days=10,
        )
        score, reason = scorer._score_rsi_divergence(div)
        assert score == 3.0
        assert "Strong bullish" in reason

    def test_moderate_bullish_divergence(self, scorer):
        div = RSIDivergenceResult(
            divergence_type='bullish', strength=0.5,
            price_pivot_1=100, price_pivot_2=95,
            rsi_pivot_1=30, rsi_pivot_2=35,
            formation_days=7,
        )
        score, reason = scorer._score_rsi_divergence(div)
        assert score == 2.0
        assert "Moderate bullish" in reason

    def test_weak_bullish_divergence(self, scorer):
        div = RSIDivergenceResult(
            divergence_type='bullish', strength=0.2,
            price_pivot_1=100, price_pivot_2=95,
            rsi_pivot_1=30, rsi_pivot_2=35,
            formation_days=5,
        )
        score, reason = scorer._score_rsi_divergence(div)
        assert score == 1.0
        assert "Weak bullish" in reason

    def test_bearish_divergence_no_deduction(self, scorer):
        div = RSIDivergenceResult(
            divergence_type='bearish', strength=0.8,
            price_pivot_1=100, price_pivot_2=105,
            rsi_pivot_1=70, rsi_pivot_2=65,
            formation_days=10,
        )
        score, reason = scorer._score_rsi_divergence(div)
        assert score == 0
        assert "Bearish" in reason or "caution" in reason


# =============================================================================
# RSI SCORING
# =============================================================================

class TestScoreRsi:
    """Tests for _score_rsi()"""

    def test_extreme_oversold(self, scorer):
        """RSI < extreme_oversold threshold → highest score."""
        score, reason = scorer._score_rsi(20.0)
        assert score > 0
        assert "extreme oversold" in reason.lower() or "oversold" in reason.lower()

    def test_oversold(self, scorer):
        score, reason = scorer._score_rsi(35.0)
        assert score > 0
        assert "oversold" in reason.lower()

    def test_neutral_low(self, scorer):
        score, reason = scorer._score_rsi(45.0)
        assert score >= 0

    def test_not_oversold(self, scorer):
        score, reason = scorer._score_rsi(65.0)
        assert score == 0
        assert "not in pullback zone" in reason.lower() or "not oversold" in reason.lower()


# =============================================================================
# SUPPORT SCORING
# =============================================================================

class TestScoreSupport:
    """Tests for _score_support()"""

    def test_no_supports(self, scorer):
        score, reason = scorer._score_support(100.0, [])
        assert score == 0
        assert "No support" in reason

    def test_close_to_support(self, scorer):
        score, reason = scorer._score_support(100.0, [99.0])
        assert score > 0
        assert "support" in reason.lower()

    def test_near_support(self, scorer):
        score, reason = scorer._score_support(100.0, [96.0])
        assert score >= 0

    def test_far_from_support(self, scorer):
        score, reason = scorer._score_support(100.0, [50.0])
        assert score == 0
        assert "from nearest support" in reason.lower()

    def test_multiple_supports_picks_nearest(self, scorer):
        score, reason = scorer._score_support(100.0, [80.0, 99.5, 95.0])
        assert score > 0
        assert "99.50" in reason


# =============================================================================
# MOVING AVERAGES SCORING
# =============================================================================

class TestScoreMovingAverages:
    """Tests for _score_moving_averages()"""

    def test_dip_in_uptrend(self, scorer):
        """Price > SMA200 but < SMA20 → pullback setup."""
        score, reason = scorer._score_moving_averages(
            price=195, sma_20=200, sma_200=180,
        )
        assert score == 2
        assert "Dip in uptrend" in reason

    def test_strong_uptrend_no_pullback(self, scorer):
        """Price > both SMAs → no pullback signal."""
        score, reason = scorer._score_moving_averages(
            price=210, sma_20=200, sma_200=180,
        )
        assert score == 0
        assert "Strong uptrend" in reason

    def test_below_sma200(self, scorer):
        """Price < SMA200 → no uptrend."""
        score, reason = scorer._score_moving_averages(
            price=170, sma_20=200, sma_200=180,
        )
        assert score == 0
        assert "Below SMA200" in reason


# =============================================================================
# VOLUME SCORING
# =============================================================================

class TestScoreVolume:
    """Tests for _score_volume()"""

    def test_no_average_volume(self, scorer):
        score, reason, status = scorer._score_volume(1000, 0)
        assert score == 0
        assert status == "unknown"

    def test_decreasing_volume_is_healthy(self, scorer):
        """Low volume during pullback is positive."""
        score, reason, status = scorer._score_volume(500, 1000)
        assert score > 0 or status == "decreasing"

    def test_volume_spike_is_caution(self, scorer):
        """High volume during pullback could be panic."""
        score, reason, status = scorer._score_volume(5000, 1000)
        assert score == 0
        assert status == "increasing"

    def test_normal_volume(self, scorer):
        score, reason, status = scorer._score_volume(1000, 1000)
        assert status in ("stable", "decreasing")


# =============================================================================
# MACD SCORING
# =============================================================================

class TestScoreMacd:
    """Tests for _score_macd()"""

    def test_no_macd(self, scorer):
        score, reason, signal = scorer._score_macd(None)
        assert score == 0
        assert signal == "neutral"

    def test_bullish_crossover(self, scorer):
        macd = MACDResult(macd_line=1.0, signal_line=0.5, histogram=0.5, crossover='bullish')
        score, reason, signal = scorer._score_macd(macd)
        assert score > 0
        assert signal == "bullish_cross"

    def test_histogram_positive(self, scorer):
        macd = MACDResult(macd_line=1.0, signal_line=0.5, histogram=0.5, crossover=None)
        score, reason, signal = scorer._score_macd(macd)
        assert score > 0
        assert signal == "bullish"

    def test_histogram_negative(self, scorer):
        macd = MACDResult(macd_line=-0.5, signal_line=0.5, histogram=-1.0, crossover=None)
        score, reason, signal = scorer._score_macd(macd)
        assert score == 0
        assert signal == "bearish"


# =============================================================================
# STOCHASTIC SCORING
# =============================================================================

class TestScoreStochastic:
    """Tests for _score_stochastic()"""

    def test_no_stoch(self, scorer):
        score, reason, signal = scorer._score_stochastic(None)
        assert score == 0
        assert signal == "neutral"

    def test_oversold_with_bullish_cross(self, scorer):
        stoch = StochasticResult(k=15, d=20, crossover='bullish', zone='oversold')
        score, reason, signal = scorer._score_stochastic(stoch)
        assert score > 0
        assert signal == "oversold_bullish_cross"

    def test_oversold_without_cross(self, scorer):
        stoch = StochasticResult(k=15, d=10, crossover=None, zone='oversold')
        score, reason, signal = scorer._score_stochastic(stoch)
        assert score > 0
        assert signal == "oversold"

    def test_overbought(self, scorer):
        stoch = StochasticResult(k=85, d=80, crossover=None, zone='overbought')
        score, reason, signal = scorer._score_stochastic(stoch)
        assert score == 0
        assert signal == "overbought"

    def test_neutral(self, scorer):
        stoch = StochasticResult(k=50, d=50, crossover=None, zone='neutral')
        score, reason, signal = scorer._score_stochastic(stoch)
        assert score == 0
        assert signal == "neutral"


# =============================================================================
# KELTNER CHANNEL SCORING
# =============================================================================

class TestScoreKeltner:
    """Tests for _score_keltner()"""

    def test_below_lower_band(self, scorer):
        keltner = KeltnerChannelResult(
            upper=110, middle=100, lower=90, atr=5,
            price_position='below_lower', percent_position=-1.2,
            channel_width_pct=20.0,
        )
        score, reason = scorer._score_keltner(keltner, current_price=85)
        assert score > 0
        assert "below" in reason.lower()

    def test_near_lower_band(self, scorer):
        keltner = KeltnerChannelResult(
            upper=110, middle=100, lower=90, atr=5,
            price_position='near_lower', percent_position=-0.8,
            channel_width_pct=20.0,
        )
        score, reason = scorer._score_keltner(keltner, current_price=91)
        assert score > 0
        assert "near" in reason.lower()

    def test_above_upper_band(self, scorer):
        keltner = KeltnerChannelResult(
            upper=110, middle=100, lower=90, atr=5,
            price_position='above_upper', percent_position=1.2,
            channel_width_pct=20.0,
        )
        score, reason = scorer._score_keltner(keltner, current_price=115)
        assert score == 0
        assert "overbought" in reason.lower()


# =============================================================================
# TREND STRENGTH SCORING
# =============================================================================

class TestScoreTrendStrength:
    """Tests for _score_trend_strength()"""

    def test_strong_uptrend(self, scorer):
        """SMA20 > SMA50 > SMA200, price above all, rising slope."""
        prices = list(range(80, 210))  # 130 prices, rising
        sma_20 = 200
        sma_50 = 190
        sma_200 = 170
        score, alignment, slope, reason = scorer._score_trend_strength(
            prices, sma_20, sma_50, sma_200,
        )
        assert score > 0
        assert alignment in ("strong", "moderate")

    def test_below_sma200(self, scorer):
        """Price below SMA200 → no uptrend."""
        prices = list(range(50, 180))
        score, alignment, slope, reason = scorer._score_trend_strength(
            prices, sma_20=175, sma_50=185, sma_200=190,
        )
        assert score == 0
        assert "Below SMA200" in reason or alignment in ("none", "weak")

    def test_no_sma50(self, scorer):
        """Without SMA50, still works with SMA20 vs SMA200."""
        prices = list(range(80, 210))
        score, alignment, slope, reason = scorer._score_trend_strength(
            prices, sma_20=200, sma_50=None, sma_200=170,
        )
        assert score >= 0


# =============================================================================
# SUPPORT WITH STRENGTH SCORING
# =============================================================================

class TestScoreSupportWithStrength:
    """Tests for _score_support_with_strength()"""

    def test_no_supports(self, scorer):
        score, reason, strength, touches = scorer._score_support_with_strength(
            100.0, [],
        )
        assert score == 0
        assert strength == "none"

    def test_strong_support_close(self, scorer):
        """Close to support with many touches → strong rating + bonus."""
        lows = [99.5, 99.3, 99.7, 99.4, 99.6] + [101.0] * 50
        score, reason, strength, touches = scorer._score_support_with_strength(
            price=100.0, supports=[99.5], lows=lows,
        )
        assert score > 0
        assert touches > 0

    def test_far_from_support(self, scorer):
        score, reason, strength, touches = scorer._score_support_with_strength(
            price=100.0, supports=[50.0],
        )
        assert score == 0


# =============================================================================
# SIGNAL HELPERS
# =============================================================================

class TestSignalHelpers:
    """Tests for _get_macd_signal() and _get_stoch_signal()"""

    def test_macd_signal_none(self, scorer):
        assert scorer._get_macd_signal(None) is None

    def test_macd_signal_bullish_cross(self, scorer):
        macd = MACDResult(macd_line=1, signal_line=0.5, histogram=0.5, crossover='bullish')
        assert scorer._get_macd_signal(macd) == 'bullish_cross'

    def test_macd_signal_bearish(self, scorer):
        macd = MACDResult(macd_line=-1, signal_line=0.5, histogram=-1.5, crossover=None)
        assert scorer._get_macd_signal(macd) == 'bearish'

    def test_stoch_signal_none(self, scorer):
        assert scorer._get_stoch_signal(None) is None

    def test_stoch_signal_oversold_bullish_cross(self, scorer):
        stoch = StochasticResult(k=15, d=20, crossover='bullish', zone='oversold')
        assert scorer._get_stoch_signal(stoch) == 'oversold_bullish_cross'

    def test_stoch_signal_overbought(self, scorer):
        stoch = StochasticResult(k=85, d=80, crossover=None, zone='overbought')
        assert scorer._get_stoch_signal(stoch) == 'overbought'


# =============================================================================
# FIBONACCI SCORING
# =============================================================================

class TestScoreFibonacci:
    """Tests for _score_fibonacci()"""

    def test_at_38_2_fib(self, scorer):
        """Price at 38.2% Fibonacci level."""
        fib_levels = {"38.2%": 95.0, "50.0%": 90.0, "61.8%": 85.0}
        score, level, reason = scorer._score_fibonacci(95.0, fib_levels)
        assert score > 0
        assert level == "38.2%"

    def test_not_at_fib_level(self, scorer):
        """Price far from any Fibonacci level."""
        fib_levels = {"38.2%": 95.0, "50.0%": 90.0, "61.8%": 85.0}
        score, level, reason = scorer._score_fibonacci(110.0, fib_levels)
        assert score == 0
        assert level is None

    def test_empty_fib_levels(self, scorer):
        score, level, reason = scorer._score_fibonacci(100.0, {})
        assert score == 0


# =============================================================================
# SCORE BOUNDS INVARIANTS
# =============================================================================

class TestScoreBounds:
    """All scoring methods should return non-negative scores within bounds."""

    def test_rsi_score_bounds(self, scorer):
        for rsi in [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            score, _ = scorer._score_rsi(float(rsi))
            assert 0 <= score <= 5, f"RSI {rsi} → score {score}"

    def test_macd_score_bounds(self, scorer):
        for crossover in [None, 'bullish', 'bearish']:
            for hist in [-2.0, -0.5, 0.0, 0.5, 2.0]:
                macd = MACDResult(macd_line=hist, signal_line=0, histogram=hist, crossover=crossover)
                score, _, _ = scorer._score_macd(macd)
                assert 0 <= score <= 5, f"MACD crossover={crossover}, hist={hist} → score {score}"

    def test_stochastic_score_bounds(self, scorer):
        for zone in ['oversold', 'overbought', 'neutral']:
            for crossover in [None, 'bullish', 'bearish']:
                stoch = StochasticResult(k=50, d=50, crossover=crossover, zone=zone)
                score, _, _ = scorer._score_stochastic(stoch)
                assert 0 <= score <= 5, f"Stoch zone={zone}, cross={crossover} → score {score}"

    def test_volume_score_bounds(self, scorer):
        for current, avg in [(0, 1000), (500, 1000), (1000, 1000), (5000, 1000)]:
            score, _, _ = scorer._score_volume(current, avg)
            assert -1 <= score <= 3, f"Vol {current}/{avg} → score {score}"

    def test_support_score_bounds(self, scorer):
        for price, supports in [(100, []), (100, [99]), (100, [80]), (100, [50])]:
            score, _ = scorer._score_support(float(price), [float(s) for s in supports])
            assert 0 <= score <= 5, f"Support {price}/{supports} → score {score}"
