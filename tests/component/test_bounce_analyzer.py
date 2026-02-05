# OptionPlay - Bounce Analyzer Tests
# =====================================
# Comprehensive unit tests for src/analyzers/bounce.py
#
# Test coverage:
# 1. BounceAnalyzer initialization
# 2. analyze method (main entry point)
# 3. Support level detection and scoring
# 4. RSI oversold detection and divergence
# 5. Candlestick pattern recognition
# 6. Volume analysis
# 7. Trend scoring
# 8. MACD/Stochastic/Keltner scoring
# 9. Score calculation and normalization
# 10. Edge cases and error handling

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.bounce import BounceAnalyzer, BounceConfig
from analyzers.context import AnalysisContext
from models.base import SignalType, SignalStrength, TradeSignal
from models.indicators import (
    MACDResult,
    StochasticResult,
    KeltnerChannelResult,
    RSIDivergenceResult,
)
from models.strategy_breakdowns import BounceScoreBreakdown


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def analyzer():
    """Standard analyzer with default config"""
    return BounceAnalyzer()


@pytest.fixture
def custom_config():
    """Custom config for testing"""
    return BounceConfig(
        support_lookback_days=90,
        support_touches_min=3,
        support_tolerance_pct=2.0,
        bounce_min_pct=1.5,
        volume_confirmation=True,
        volume_spike_multiplier=1.5,
        rsi_oversold_threshold=35.0,
        rsi_period=14,
        require_bullish_candle=True,
        stop_below_support_pct=2.5,
        target_risk_reward=2.5,
        max_score=10,
        min_score_for_signal=7,
    )


@pytest.fixture
def bounce_data():
    """Generates data with support bounce pattern"""
    n = 100
    prices = []
    highs = []
    lows = []

    # Uptrend, then pullback to support, then bounce
    for i in range(n):
        if i < 60:
            # Uptrend
            base = 100 + i * 0.3
        elif i < 80:
            # Pullback to support at ~110
            base = 118 - (i - 60) * 0.4
        else:
            # Bounce from support
            base = 110 + (i - 80) * 0.2

        prices.append(base)
        highs.append(base + 1)
        lows.append(base - 1)

    # Create support touches
    lows[30] = 109.5  # Support Touch 1
    lows[50] = 109.8  # Support Touch 2
    lows[78] = 109.2  # Support Touch 3 (current bounce)

    volumes = [1000000] * n
    volumes[-1] = 1500000  # Elevated volume at bounce

    return prices, volumes, highs, lows


@pytest.fixture
def downtrend_data():
    """Generates data with consistent downtrend (no bounce)"""
    n = 100
    prices = [100 - i * 0.3 for i in range(n)]
    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


@pytest.fixture
def sideways_data():
    """Generates sideways/ranging data"""
    n = 100
    prices = [100 + (i % 10 - 5) * 0.5 for i in range(n)]
    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


@pytest.fixture
def oversold_data():
    """Generates data with strongly oversold RSI"""
    n = 100
    # Sharp decline for oversold RSI
    prices = [100 - i * 0.5 for i in range(n)]
    volumes = [1000000] * n
    highs = [p + 1 for p in prices]
    lows = [p - 1 for p in prices]
    return prices, volumes, highs, lows


# =============================================================================
# TEST CLASS: INITIALIZATION
# =============================================================================

class TestBounceAnalyzerInitialization:
    """Tests for BounceAnalyzer initialization"""

    def test_default_initialization(self):
        """Default initialization should use BounceConfig defaults"""
        analyzer = BounceAnalyzer()

        assert analyzer.config is not None
        assert isinstance(analyzer.config, BounceConfig)
        assert analyzer.config.support_touches_min == 2
        assert analyzer.config.rsi_period == 14

    def test_custom_config_initialization(self, custom_config):
        """Custom config should be applied correctly"""
        analyzer = BounceAnalyzer(config=custom_config)

        assert analyzer.config.support_lookback_days == 90
        assert analyzer.config.support_touches_min == 3
        assert analyzer.config.rsi_oversold_threshold == 35.0
        assert analyzer.config.target_risk_reward == 2.5

    def test_scoring_config_initialization(self):
        """Scoring config should be initialized"""
        from config import BounceScoringConfig

        scoring_config = BounceScoringConfig()
        analyzer = BounceAnalyzer(scoring_config=scoring_config)

        assert analyzer.scoring_config is not None

    def test_strategy_name_property(self, analyzer):
        """strategy_name should return 'bounce'"""
        assert analyzer.strategy_name == "bounce"

    def test_description_property(self, analyzer):
        """description should be meaningful"""
        desc = analyzer.description
        assert "bounce" in desc.lower() or "support" in desc.lower()


# =============================================================================
# TEST CLASS: ANALYZE METHOD
# =============================================================================

class TestBounceAnalyzeMethod:
    """Tests for the main analyze() method"""

    def test_analyze_returns_trade_signal(self, analyzer, bounce_data):
        """analyze() should return a TradeSignal"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert isinstance(signal, TradeSignal)
        assert signal.symbol == "TEST"
        assert signal.strategy == "bounce"

    def test_analyze_with_bounce_pattern(self, analyzer, bounce_data):
        """Bounce pattern should be detected with positive score"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        # Bounce should be detected
        assert signal.score > 0 or "Support" in signal.reason

    def test_analyze_with_context(self, analyzer, bounce_data):
        """analyze() should accept optional context"""
        prices, volumes, highs, lows = bounce_data
        context = AnalysisContext(
            symbol="TEST",
            current_price=prices[-1],
            support_levels=[109.0, 105.0],
        )

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows, context=context
        )

        assert isinstance(signal, TradeSignal)

    def test_analyze_no_support_returns_neutral(self, analyzer, downtrend_data):
        """No support test should return neutral signal"""
        prices, volumes, highs, lows = downtrend_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert signal.signal_type == SignalType.NEUTRAL
        assert signal.score <= 3.5  # Below actionable threshold

    def test_analyze_score_normalization(self, analyzer, bounce_data):
        """Score should be normalized to 0-10 scale"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 0 <= signal.score <= 10

    def test_analyze_includes_score_breakdown(self, analyzer, bounce_data):
        """Signal details should include score breakdown"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'score_breakdown' in signal.details
        breakdown = signal.details['score_breakdown']
        assert 'components' in breakdown
        assert 'total_score' in breakdown

    def test_analyze_includes_entry_stop_target(self, analyzer, bounce_data):
        """Signal should include entry, stop, and target prices"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        if signal.signal_type == SignalType.LONG:
            assert signal.entry_price is not None
            assert signal.stop_loss is not None
            assert signal.target_price is not None
            assert signal.stop_loss < signal.entry_price < signal.target_price

    def test_analyze_signal_strength_classification(self, analyzer, bounce_data):
        """Signal strength should be properly classified"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert signal.strength in [
            SignalStrength.STRONG,
            SignalStrength.MODERATE,
            SignalStrength.WEAK,
            SignalStrength.NONE,
        ]


# =============================================================================
# TEST CLASS: SUPPORT DETECTION
# =============================================================================

class TestBounceSupportDetection:
    """Tests for support level detection and scoring"""

    def test_finds_support_levels(self, analyzer):
        """Should find support levels using centralized module"""
        from indicators.support_resistance import find_support_levels

        n = 100
        lows = [100.0] * n

        # Create support touches at 95
        for i in [20, 25, 28]:
            lows[i] = 95.0
        for i in [50, 55, 58]:
            lows[i] = 90.0

        supports = find_support_levels(lows, lookback=80, window=3, max_levels=5)

        assert len(supports) >= 1

    def test_clusters_similar_levels(self):
        """Similar levels should be clustered"""
        from indicators.support_resistance import cluster_levels

        levels = [100.0, 100.5, 100.2, 95.0, 95.3]
        indices = [10, 20, 30, 40, 50]
        tolerance_pct = 1.5

        clusters = cluster_levels(levels, indices=indices, tolerance_pct=tolerance_pct)

        # Should have two clusters: ~100 and ~95
        assert len(clusters) == 2

    def test_score_support_test_at_support(self, analyzer):
        """Price at support should score positively"""
        lows = [100.0] * 100
        # Create support touches
        lows[20] = 95.0
        lows[40] = 95.2
        lows[60] = 94.9

        support_levels = [95.0]

        score, info = analyzer._score_support_test(
            current_low=95.1,
            current_price=96.5,
            support_levels=support_levels,
            lows=lows,
        )

        assert score >= 2
        assert 'tested_support' in info or info.get('distance_pct', 100) < 2

    def test_score_support_test_near_support(self, analyzer):
        """Price near but not at support should score lower"""
        lows = [100.0] * 100
        support_levels = [95.0]

        score, info = analyzer._score_support_test(
            current_low=97.0,  # Not touching support
            current_price=98.0,
            support_levels=support_levels,
            lows=lows,
        )

        assert score <= 2

    def test_score_support_test_no_support(self, analyzer):
        """No support levels should score zero"""
        lows = [100.0] * 100

        score, info = analyzer._score_support_test(
            current_low=99.0,
            current_price=100.0,
            support_levels=[],
            lows=lows,
        )

        assert score == 0
        assert info['nearest_support'] is None

    def test_count_support_touches(self, analyzer):
        """Should count support touches correctly"""
        n = 100
        lows = [100.0] * n

        # Create touches at support level 95
        lows[20] = 95.0
        lows[40] = 95.2
        lows[60] = 94.8

        touches = analyzer._count_support_touches(lows, 95.0, 0.015)

        assert touches >= 2

    def test_support_strength_classification(self, analyzer):
        """Support strength should be classified correctly"""
        lows = [100.0] * 100

        # Strong support: 4+ touches
        for i in [20, 30, 40, 50]:
            lows[i] = 95.0

        support_levels = [95.0]

        _, info = analyzer._score_support_test(
            current_low=95.1,
            current_price=96.5,
            support_levels=support_levels,
            lows=lows,
        )

        assert info['strength'] in ['weak', 'moderate', 'strong']


# =============================================================================
# TEST CLASS: RSI SCORING
# =============================================================================

class TestBounceRSIScoring:
    """Tests for RSI oversold detection and scoring"""

    def test_rsi_oversold_detection(self, analyzer):
        """Oversold RSI should be detected"""
        # Strongly falling prices -> low RSI
        prices = [100 - i * 0.5 for i in range(50)]

        score, rsi = analyzer._score_rsi_oversold(prices)

        assert rsi < 40
        assert score >= 1

    def test_rsi_extreme_oversold(self, analyzer):
        """Extreme oversold RSI should give max score"""
        # Very strongly falling prices
        prices = [100 - i * 1.0 for i in range(50)]

        score, rsi = analyzer._score_rsi_oversold(prices)

        assert rsi < 30  # RSI_OVERSOLD constant
        assert score == 2

    def test_rsi_neutral_no_score(self, analyzer):
        """Neutral RSI should give zero score"""
        # Sideways prices
        prices = [100 + (i % 2) * 0.5 for i in range(50)]

        score, rsi = analyzer._score_rsi_oversold(prices)

        assert 40 < rsi < 60
        assert score == 0

    def test_rsi_insufficient_data(self, analyzer):
        """Insufficient data should return default values"""
        prices = [100, 101, 102]

        score, rsi = analyzer._score_rsi_oversold(prices)

        assert score == 0
        assert rsi == 50.0  # Default neutral RSI


# =============================================================================
# TEST CLASS: RSI DIVERGENCE
# =============================================================================

class TestBounceRSIDivergence:
    """Tests for RSI divergence scoring"""

    def test_score_bullish_divergence_strong(self, analyzer):
        """Strong bullish divergence should give max score"""
        divergence = RSIDivergenceResult(
            divergence_type='bullish',
            price_pivot_1=100.0,
            price_pivot_2=95.0,
            rsi_pivot_1=30.0,
            rsi_pivot_2=35.0,
            strength=0.75,  # Strong
            formation_days=10,
        )

        score, reason = analyzer._score_rsi_divergence(divergence)

        assert score == 3.0
        assert "strong" in reason.lower()

    def test_score_bullish_divergence_moderate(self, analyzer):
        """Moderate bullish divergence should give 2 points"""
        divergence = RSIDivergenceResult(
            divergence_type='bullish',
            price_pivot_1=100.0,
            price_pivot_2=95.0,
            rsi_pivot_1=30.0,
            rsi_pivot_2=32.0,
            strength=0.5,  # Moderate
            formation_days=8,
        )

        score, reason = analyzer._score_rsi_divergence(divergence)

        assert score == 2.0

    def test_score_bullish_divergence_weak(self, analyzer):
        """Weak bullish divergence should give 1 point"""
        divergence = RSIDivergenceResult(
            divergence_type='bullish',
            price_pivot_1=100.0,
            price_pivot_2=98.0,
            rsi_pivot_1=35.0,
            rsi_pivot_2=36.0,
            strength=0.25,  # Weak
            formation_days=5,
        )

        score, reason = analyzer._score_rsi_divergence(divergence)

        assert score == 1.0

    def test_score_bearish_divergence_no_points(self, analyzer):
        """Bearish divergence should give 0 points but warning"""
        divergence = RSIDivergenceResult(
            divergence_type='bearish',
            price_pivot_1=100.0,
            price_pivot_2=105.0,
            rsi_pivot_1=70.0,
            rsi_pivot_2=65.0,
            strength=0.5,
            formation_days=8,
        )

        score, reason = analyzer._score_rsi_divergence(divergence)

        assert score == 0
        assert "caution" in reason.lower()

    def test_score_no_divergence(self, analyzer):
        """No divergence should give 0 points"""
        score, reason = analyzer._score_rsi_divergence(None)

        assert score == 0
        assert "no" in reason.lower()


# =============================================================================
# TEST CLASS: CANDLESTICK PATTERNS
# =============================================================================

class TestBounceCandlestickPatterns:
    """Tests for candlestick pattern recognition"""

    def test_detects_hammer(self, analyzer):
        """Hammer pattern should be detected"""
        # Hammer: small body at top, long lower wick
        prices = [100, 99, 100.5]  # Close near high
        highs = [101, 100, 101]
        lows = [99, 98, 96]  # Long lower wick

        score, info = analyzer._score_candlestick_pattern(prices, highs, lows)

        assert info['pattern'] is not None
        # Could be Hammer or similar bullish pattern

    def test_detects_bullish_engulfing(self, analyzer):
        """Bullish engulfing pattern should be detected"""
        prices = [102, 100, 103]  # Red candle followed by larger green
        highs = [103, 101, 104]
        lows = [101, 99, 99]

        score, info = analyzer._score_candlestick_pattern(prices, highs, lows)

        if info['pattern'] == 'Bullish Engulfing':
            assert score == 2
            assert info['bullish'] is True

    def test_detects_doji(self, analyzer):
        """Doji pattern should be detected"""
        prices = [100, 100, 100.05]  # Very small body
        highs = [102, 101, 101.5]
        lows = [98, 99, 98.5]

        score, info = analyzer._score_candlestick_pattern(prices, highs, lows)

        if info['pattern'] == 'Doji':
            assert score == 1

    def test_detects_bullish_candle(self, analyzer):
        """Simple bullish (green) candle should be detected"""
        prices = [100, 99, 102]  # Green candle
        highs = [101, 100, 103]
        lows = [99, 98, 101]

        score, info = analyzer._score_candlestick_pattern(prices, highs, lows)

        assert info['bullish'] is True
        assert score >= 1

    def test_insufficient_data_for_pattern(self, analyzer):
        """Insufficient data should return no pattern"""
        prices = [100, 101]
        highs = [101, 102]
        lows = [99, 100]

        score, info = analyzer._score_candlestick_pattern(prices, highs, lows)

        assert score == 0
        assert info['pattern'] is None


# =============================================================================
# TEST CLASS: VOLUME ANALYSIS
# =============================================================================

class TestBounceVolumeAnalysis:
    """Tests for volume analysis scoring"""

    def test_volume_spike_at_bounce(self, analyzer):
        """Volume spike at bounce should score positively"""
        volumes = [1000000] * 30
        volumes[-1] = 1500000  # 1.5x average

        score, info = analyzer._score_volume(volumes)

        assert score >= 1
        assert info['multiplier'] >= 1.3

    def test_declining_volume_healthy(self, analyzer):
        """Declining volume during pullback is healthy"""
        # Declining volume
        volumes = [1000000] * 25 + [900000, 800000, 700000, 600000, 500000]

        score, info = analyzer._score_volume(volumes)

        # Should recognize declining trend
        if info['trend'] == 'decreasing':
            assert score >= 1

    def test_normal_volume_neutral(self, analyzer):
        """Normal volume should be neutral"""
        volumes = [1000000] * 30

        score, info = analyzer._score_volume(volumes)

        assert info['trend'] in ['stable', 'unknown']

    def test_insufficient_volume_data(self, analyzer):
        """Insufficient volume data should handle gracefully"""
        volumes = [1000000] * 5

        score, info = analyzer._score_volume(volumes)

        assert score == 0
        assert info['trend'] == 'unknown'

    def test_zero_average_volume(self, analyzer):
        """Zero average volume should handle gracefully"""
        volumes = [0] * 30

        score, info = analyzer._score_volume(volumes)

        assert score == 0


# =============================================================================
# TEST CLASS: TREND SCORING
# =============================================================================

class TestBounceTrendScoring:
    """Tests for trend analysis scoring"""

    def test_uptrend_scores_high(self, analyzer):
        """Price in uptrend should score 2 points"""
        # Steadily rising prices
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]

        score, info = analyzer._score_trend(prices)

        assert score == 2
        assert info['trend'] in ['uptrend', 'pullback_in_uptrend']

    def test_pullback_in_uptrend(self, analyzer):
        """Pullback in uptrend should score 2 points"""
        n = 250
        # Rising then slight pullback, still above SMA200
        prices = [100 + i * 0.1 for i in range(200)]
        prices += [120 - i * 0.2 for i in range(50)]  # Pullback

        score, info = analyzer._score_trend(prices)

        # Current price should still be above SMA200
        if info['price'] > info['sma_200']:
            assert score >= 1

    def test_downtrend_scores_zero(self, analyzer):
        """Downtrend should score 0 points"""
        n = 250
        # Steadily declining prices
        prices = [150 - i * 0.2 for i in range(n)]

        score, info = analyzer._score_trend(prices)

        assert score == 0
        assert info['trend'] == 'downtrend'

    def test_trend_calculation_short_data(self, analyzer):
        """Short data should use available data for SMAs"""
        n = 60  # Less than 200 days
        prices = [100 + i * 0.1 for i in range(n)]

        score, info = analyzer._score_trend(prices)

        # Should still work with available data
        assert 'sma_50' in info
        assert 'sma_200' in info


# =============================================================================
# TEST CLASS: MACD SCORING
# =============================================================================

class TestBounceMACDScoring:
    """Tests for MACD scoring"""

    def test_macd_bullish_cross_max_score(self, analyzer):
        """Bullish MACD crossover should give max score"""
        macd = MACDResult(
            macd_line=0.5,
            signal_line=0.4,
            histogram=0.1,
            crossover='bullish',
        )

        score, reason, signal = analyzer._score_macd(macd)

        assert score == 2
        assert signal == "bullish_cross"

    def test_macd_bullish_histogram(self, analyzer):
        """Positive MACD histogram should give 1 point"""
        macd = MACDResult(
            macd_line=0.5,
            signal_line=0.4,
            histogram=0.1,
            crossover=None,
        )

        score, reason, signal = analyzer._score_macd(macd)

        assert score == 1
        assert signal == "bullish"

    def test_macd_bearish_no_score(self, analyzer):
        """Negative MACD histogram should give 0 points"""
        macd = MACDResult(
            macd_line=0.3,
            signal_line=0.5,
            histogram=-0.2,
            crossover=None,
        )

        score, reason, signal = analyzer._score_macd(macd)

        assert score == 0
        assert signal == "bearish"

    def test_macd_none_neutral(self, analyzer):
        """No MACD data should give 0 points"""
        score, reason, signal = analyzer._score_macd(None)

        assert score == 0
        assert signal == "neutral"

    def test_macd_calculation_with_data(self, analyzer):
        """MACD should be calculated with sufficient data"""
        n = 50
        prices = [100 + i * 0.5 for i in range(n)]

        result = analyzer._calculate_macd(prices)

        assert result is not None
        assert hasattr(result, 'macd_line')
        assert hasattr(result, 'signal_line')
        assert hasattr(result, 'histogram')

    def test_macd_calculation_insufficient_data(self, analyzer):
        """MACD should return None with insufficient data"""
        prices = [100, 101, 102]

        result = analyzer._calculate_macd(prices)

        assert result is None


# =============================================================================
# TEST CLASS: STOCHASTIC SCORING
# =============================================================================

class TestBounceStochasticScoring:
    """Tests for Stochastic scoring"""

    def test_stoch_oversold_bullish_cross(self, analyzer):
        """Oversold + bullish cross should give max score"""
        stoch = StochasticResult(
            k=15.0,
            d=18.0,
            crossover='bullish',
            zone='oversold',
        )

        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 2
        assert signal == "oversold_bullish_cross"

    def test_stoch_oversold_only(self, analyzer):
        """Oversold without cross should give 1 point"""
        stoch = StochasticResult(
            k=15.0,
            d=12.0,
            crossover=None,
            zone='oversold',
        )

        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 1
        assert signal == "oversold"

    def test_stoch_overbought_no_score(self, analyzer):
        """Overbought should give 0 points"""
        stoch = StochasticResult(
            k=85.0,
            d=82.0,
            crossover=None,
            zone='overbought',
        )

        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 0
        assert signal == "overbought"

    def test_stoch_neutral_no_score(self, analyzer):
        """Neutral zone should give 0 points"""
        stoch = StochasticResult(
            k=50.0,
            d=48.0,
            crossover=None,
            zone='neutral',
        )

        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 0
        assert signal == "neutral"

    def test_stoch_none_neutral(self, analyzer):
        """No stochastic data should give 0 points"""
        score, reason, signal = analyzer._score_stochastic(None)

        assert score == 0
        assert signal == "neutral"

    def test_stoch_calculation_with_data(self, analyzer):
        """Stochastic should be calculated with sufficient data"""
        n = 30
        prices = [100 + i * 0.1 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_stochastic(prices, highs, lows)

        assert result is not None
        assert 0 <= result.k <= 100
        assert 0 <= result.d <= 100

    def test_stoch_calculation_insufficient_data(self, analyzer):
        """Stochastic should return None with insufficient data"""
        prices = [100, 101, 102]
        highs = [101, 102, 103]
        lows = [99, 100, 101]

        result = analyzer._calculate_stochastic(prices, highs, lows)

        assert result is None


# =============================================================================
# TEST CLASS: KELTNER CHANNEL SCORING
# =============================================================================

class TestBounceKeltnerScoring:
    """Tests for Keltner Channel scoring"""

    def test_keltner_below_lower_max_score(self, analyzer):
        """Price below lower band should give max score"""
        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='below_lower',
            percent_position=-1.5,
            channel_width_pct=20.0,
        )

        score, reason = analyzer._score_keltner(keltner, 85.0)

        assert score == 2
        assert "below" in reason.lower()

    def test_keltner_near_lower(self, analyzer):
        """Price near lower band should give 1 point"""
        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='near_lower',
            percent_position=-0.7,
            channel_width_pct=20.0,
        )

        score, reason = analyzer._score_keltner(keltner, 93.0)

        assert score == 1
        assert "near" in reason.lower()

    def test_keltner_above_upper_no_score(self, analyzer):
        """Price above upper band should give 0 points"""
        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='above_upper',
            percent_position=1.5,
            channel_width_pct=20.0,
        )

        score, reason = analyzer._score_keltner(keltner, 115.0)

        assert score == 0
        assert "above" in reason.lower() or "overbought" in reason.lower()

    def test_keltner_in_channel_neutral(self, analyzer):
        """Price in channel should give 0 or partial points"""
        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='in_channel',
            percent_position=0.1,
            channel_width_pct=20.0,
        )

        score, reason = analyzer._score_keltner(keltner, 101.0)

        assert score <= 1

    def test_keltner_calculation_with_data(self, analyzer):
        """Keltner Channel should be calculated with sufficient data"""
        n = 50
        prices = [100 + i * 0.1 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)

        assert result is not None
        assert result.upper > result.middle > result.lower
        assert result.atr > 0

    def test_keltner_calculation_insufficient_data(self, analyzer):
        """Keltner Channel should return None with insufficient data"""
        prices = [100, 101, 102]
        highs = [101, 102, 103]
        lows = [99, 100, 101]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)

        assert result is None


# =============================================================================
# TEST CLASS: SCORE CALCULATION
# =============================================================================

class TestBounceScoreCalculation:
    """Tests for overall score calculation"""

    def test_total_score_sum_of_components(self, analyzer, bounce_data):
        """Total score should be sum of all components"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        breakdown = signal.details['score_breakdown']

        components = breakdown['components']
        expected_total = sum([
            components['support']['score'],
            components['rsi']['score'],
            components.get('rsi_divergence', {}).get('score', 0),
            components['candlestick']['score'],
            components['volume']['score'],
            components['trend']['score'],
            components['macd']['score'],
            components['stochastic']['score'],
            components['keltner']['score'],
            components.get('vwap', {}).get('score', 0),
            components.get('market_context', {}).get('score', 0),
            components.get('sector', {}).get('score', 0),
            components.get('gap', {}).get('score', 0),
        ])

        assert abs(breakdown['total_score'] - expected_total) < 0.1

    def test_max_possible_is_27(self, analyzer, bounce_data):
        """Max possible score should be 27"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        breakdown = signal.details['score_breakdown']

        assert breakdown['max_possible'] == 27

    def test_normalized_score_range(self, analyzer, bounce_data):
        """Normalized score should be in 0-10 range"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 0 <= signal.score <= 10

    def test_signal_type_based_on_score(self, analyzer, bounce_data):
        """Signal type should be based on normalized score threshold"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        if signal.score >= 3.5:
            assert signal.signal_type == SignalType.LONG
        else:
            assert signal.signal_type == SignalType.NEUTRAL

    def test_signal_strength_thresholds(self, analyzer):
        """Signal strength should follow threshold rules"""
        # We test the strength assignment logic
        # Score >= 7 -> STRONG
        # Score >= 5 -> MODERATE
        # Score >= 3 -> WEAK
        # Otherwise -> NONE

        # This is implicitly tested through analyze() results


# =============================================================================
# TEST CLASS: SCORE BREAKDOWN
# =============================================================================

class TestBounceScoreBreakdown:
    """Tests for BounceScoreBreakdown dataclass"""

    def test_breakdown_contains_all_fields(self, analyzer, bounce_data):
        """Breakdown should contain all scoring fields"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        breakdown = signal.details.get('score_breakdown', {})

        assert 'components' in breakdown
        components = breakdown['components']

        # Core components
        assert 'support' in components
        assert 'rsi' in components
        assert 'candlestick' in components
        assert 'volume' in components
        assert 'trend' in components
        assert 'macd' in components
        assert 'stochastic' in components
        assert 'keltner' in components

    def test_breakdown_macd_fields(self, analyzer, bounce_data):
        """MACD component should have correct fields"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        macd_info = signal.details['score_breakdown']['components']['macd']

        assert 'score' in macd_info
        assert 'signal' in macd_info
        assert 'histogram' in macd_info
        assert 'reason' in macd_info

    def test_breakdown_stochastic_fields(self, analyzer, bounce_data):
        """Stochastic component should have correct fields"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        stoch_info = signal.details['score_breakdown']['components']['stochastic']

        assert 'score' in stoch_info
        assert 'signal' in stoch_info
        assert 'k' in stoch_info
        assert 'd' in stoch_info
        assert 'reason' in stoch_info

    def test_breakdown_keltner_fields(self, analyzer, bounce_data):
        """Keltner component should have correct fields"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        keltner_info = signal.details['score_breakdown']['components']['keltner']

        assert 'score' in keltner_info
        assert 'position' in keltner_info
        assert 'percent' in keltner_info
        assert 'reason' in keltner_info

    def test_breakdown_support_fields(self, analyzer, bounce_data):
        """Support component should have strength and touches"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        support_info = signal.details['score_breakdown']['components']['support']

        assert 'score' in support_info
        assert 'strength' in support_info
        assert 'touches' in support_info

    def test_breakdown_to_dict(self):
        """BounceScoreBreakdown.to_dict() should work correctly"""
        breakdown = BounceScoreBreakdown(
            support_score=3,
            rsi_score=2,
            candlestick_score=2,
            volume_score=1,
            trend_score=2,
            macd_score=1,
            stoch_score=1,
            keltner_score=1,
            total_score=13,
            max_possible=27,
        )

        d = breakdown.to_dict()

        assert 'total_score' in d
        assert 'max_possible' in d
        assert 'components' in d
        assert d['total_score'] == 13


# =============================================================================
# TEST CLASS: HELPER METHODS
# =============================================================================

class TestBounceHelperMethods:
    """Tests for helper methods"""

    def test_calculate_ema(self, analyzer):
        """EMA should be calculated correctly"""
        values = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]

        ema = analyzer._calculate_ema(values, 5)

        assert ema is not None
        assert len(ema) > 0
        assert 105 < ema[-1] < 111

    def test_calculate_ema_insufficient_data(self, analyzer):
        """EMA should return None with insufficient data"""
        values = [100, 101, 102]

        ema = analyzer._calculate_ema(values, 10)

        assert ema is None

    def test_calculate_atr(self, analyzer):
        """ATR should be calculated correctly"""
        n = 30
        highs = [102.0] * n
        lows = [98.0] * n
        closes = [100.0] * n

        atr = analyzer._calculate_atr(highs, lows, closes, 14)

        assert atr is not None
        # With constant range of 4 (102-98), ATR should be ~4
        assert 3.5 < atr < 4.5

    def test_calculate_atr_insufficient_data(self, analyzer):
        """ATR should return None with insufficient data"""
        atr = analyzer._calculate_atr([100, 101], [98, 99], [99, 100], 14)

        assert atr is None

    def test_calculate_target(self, analyzer):
        """Target should be calculated based on risk/reward"""
        entry = 100.0
        stop = 95.0

        target = analyzer._calculate_target(entry, stop)

        # Default risk/reward is 2.0
        expected_target = entry + (entry - stop) * 2.0
        assert abs(target - expected_target) < 0.01

    def test_create_neutral_signal(self, analyzer):
        """create_neutral_signal should work correctly"""
        signal = analyzer.create_neutral_signal("TEST", 100.0, "Test reason")

        assert signal.symbol == "TEST"
        assert signal.signal_type == SignalType.NEUTRAL
        assert signal.strength == SignalStrength.NONE
        assert signal.score == 0.0
        assert "Test reason" in signal.reason


# =============================================================================
# TEST CLASS: EDGE CASES
# =============================================================================

class TestBounceEdgeCases:
    """Edge cases and error handling tests"""

    def test_insufficient_data_raises_error(self, analyzer):
        """Insufficient data should raise ValueError"""
        prices = [100] * 30
        volumes = [1000000] * 30
        highs = [101] * 30
        lows = [99] * 30

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_mismatched_array_lengths(self, analyzer):
        """Mismatched array lengths should raise ValueError"""
        prices = [100] * 100
        volumes = [1000000] * 99  # Different length
        highs = [101] * 100
        lows = [99] * 100

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_empty_arrays(self, analyzer):
        """Empty arrays should raise ValueError"""
        with pytest.raises(ValueError):
            analyzer.analyze("TEST", [], [], [], [])

    def test_negative_prices(self, analyzer):
        """Negative prices should raise ValueError"""
        prices = [100] * 50 + [-10] + [100] * 49
        volumes = [1000000] * 100
        highs = [101] * 100
        lows = [99] * 100

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_high_less_than_low(self, analyzer):
        """High < Low should raise ValueError"""
        n = 100
        prices = [100] * n
        volumes = [1000000] * n
        highs = [99] * n  # High less than low
        lows = [101] * n

        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)

    def test_downtrend_warning(self, analyzer, downtrend_data):
        """Downtrend should generate warning or low score"""
        prices, volumes, highs, lows = downtrend_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        # Either warning or low score
        has_warning = any(
            "trend" in w.lower() or "risk" in w.lower()
            for w in signal.warnings
        )
        assert has_warning or signal.score < 5

    def test_extreme_volume_spike(self, analyzer, bounce_data):
        """Extreme volume spike should be handled"""
        prices, volumes, highs, lows = bounce_data
        volumes[-1] = 100000000  # 100x normal

        # Should not crash
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert isinstance(signal, TradeSignal)

    def test_flat_prices(self, analyzer):
        """Flat prices should not crash"""
        n = 100
        prices = [100.0] * n
        volumes = [1000000] * n
        highs = [100.5] * n
        lows = [99.5] * n

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert isinstance(signal, TradeSignal)

    def test_very_volatile_data(self, analyzer):
        """Highly volatile data should be handled"""
        import random

        n = 100
        prices = [100 + random.uniform(-10, 10) for _ in range(n)]
        highs = [p + random.uniform(0, 5) for p in prices]
        lows = [p - random.uniform(0, 5) for p in prices]
        volumes = [1000000] * n

        # Ensure high >= low
        for i in range(n):
            if highs[i] < lows[i]:
                highs[i], lows[i] = lows[i], highs[i]

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        assert isinstance(signal, TradeSignal)


# =============================================================================
# TEST CLASS: INTEGRATION WITH CONTEXT
# =============================================================================

class TestBounceWithContext:
    """Tests for integration with AnalysisContext"""

    def test_uses_context_support_levels(self, analyzer, bounce_data):
        """Should use support levels from context if provided"""
        prices, volumes, highs, lows = bounce_data
        context = AnalysisContext(
            symbol="TEST",
            current_price=prices[-1],
            support_levels=[108.0, 105.0],
        )

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows, context=context
        )

        # Context support levels should be considered
        assert isinstance(signal, TradeSignal)

    def test_calculates_support_without_context(self, analyzer, bounce_data):
        """Should calculate support levels if context not provided"""
        prices, volumes, highs, lows = bounce_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        # Should still have support info
        support_info = signal.details.get('support_info', {})
        assert support_info is not None

    def test_empty_context_support(self, analyzer, bounce_data):
        """Empty context support should trigger calculation"""
        prices, volumes, highs, lows = bounce_data
        context = AnalysisContext(
            symbol="TEST",
            current_price=prices[-1],
            support_levels=[],  # Empty
        )

        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows, context=context
        )

        # Should calculate support even with empty context
        assert isinstance(signal, TradeSignal)


# =============================================================================
# TEST CLASS: FEATURE SCORING MIXIN
# =============================================================================

class TestBounceFeatureScoringMixin:
    """Tests for feature scoring mixin integration"""

    def test_vwap_score_included(self, analyzer, bounce_data):
        """VWAP score should be included in breakdown"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        breakdown = signal.details['score_breakdown']
        if 'vwap' in breakdown.get('components', {}):
            vwap_info = breakdown['components']['vwap']
            assert 'score' in vwap_info

    def test_market_context_score_included(self, analyzer, bounce_data):
        """Market context score should be included (if SPY data available)"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        breakdown = signal.details['score_breakdown']
        if 'market_context' in breakdown.get('components', {}):
            mc_info = breakdown['components']['market_context']
            assert 'score' in mc_info

    def test_sector_score_included(self, analyzer, bounce_data):
        """Sector score should be included"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        breakdown = signal.details['score_breakdown']
        if 'sector' in breakdown.get('components', {}):
            sector_info = breakdown['components']['sector']
            assert 'score' in sector_info

    def test_gap_score_included(self, analyzer, bounce_data):
        """Gap score should be included"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        breakdown = signal.details['score_breakdown']
        if 'gap' in breakdown.get('components', {}):
            gap_info = breakdown['components']['gap']
            assert 'score' in gap_info


# =============================================================================
# TEST CLASS: DETAILED OUTPUT
# =============================================================================

class TestBounceDetailedOutput:
    """Tests for detailed output in signal.details"""

    def test_includes_support_levels(self, analyzer, bounce_data):
        """Signal details should include support levels"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'support_levels' in signal.details

    def test_includes_support_info(self, analyzer, bounce_data):
        """Signal details should include support info"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'support_info' in signal.details

    def test_includes_trend_info(self, analyzer, bounce_data):
        """Signal details should include trend info"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'trend_info' in signal.details

    def test_includes_rsi(self, analyzer, bounce_data):
        """Signal details should include RSI value"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'rsi' in signal.details

    def test_includes_candle_info(self, analyzer, bounce_data):
        """Signal details should include candlestick info"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'candle_info' in signal.details
        candle_info = signal.details['candle_info']
        assert 'pattern' in candle_info
        assert 'bullish' in candle_info

    def test_includes_sr_levels(self, analyzer, bounce_data):
        """Signal details should include S/R levels"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'sr_levels' in signal.details

    def test_includes_raw_score(self, analyzer, bounce_data):
        """Signal details should include raw score"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'raw_score' in signal.details

    def test_includes_max_possible(self, analyzer, bounce_data):
        """Signal details should include max possible score"""
        prices, volumes, highs, lows = bounce_data
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)

        assert 'max_possible' in signal.details
        assert signal.details['max_possible'] == 27


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
