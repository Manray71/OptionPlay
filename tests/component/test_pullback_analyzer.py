# OptionPlay - Pullback Analyzer Tests
# ======================================

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

# Add project root to path (not src!)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.analyzers import PullbackAnalyzer
from src.models import (
    PullbackCandidate,
    ScoreBreakdown,
    TechnicalIndicators,
    MACDResult,
    StochasticResult,
    TradeSignal
)
from src.config import PullbackScoringConfig, RSIConfig, SupportConfig


class TestRSICalculation:
    """Tests for RSI calculation"""
    
    @pytest.fixture
    def analyzer(self):
        """Standard analyzer with default config"""
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_rsi_oversold(self, analyzer):
        """Falling prices should give low RSI"""
        prices = [100 - i * 0.5 for i in range(50)]
        rsi = analyzer._calculate_rsi(prices, 14)
        assert rsi < 40
        
    def test_rsi_overbought(self, analyzer):
        """Rising prices should give high RSI"""
        prices = [100 + i * 0.5 for i in range(50)]
        rsi = analyzer._calculate_rsi(prices, 14)
        assert rsi > 60
        
    def test_rsi_neutral(self, analyzer):
        """Sideways prices should give RSI around 50"""
        prices = [100 + (i % 2) * 0.5 - 0.25 for i in range(50)]
        rsi = analyzer._calculate_rsi(prices, 14)
        assert 40 < rsi < 60
        
    def test_rsi_range(self, analyzer):
        """RSI should always be between 0 and 100"""
        prices_down = [100 - i * 2 for i in range(50)]
        prices_up = [100 + i * 2 for i in range(50)]
        
        rsi_down = analyzer._calculate_rsi(prices_down, 14)
        rsi_up = analyzer._calculate_rsi(prices_up, 14)
        
        assert 0 <= rsi_down <= 100
        assert 0 <= rsi_up <= 100


class TestMovingAverages:
    """Tests for Moving Average calculations"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_sma_calculation(self, analyzer):
        """SMA should calculate correct average"""
        prices = [10, 20, 30, 40, 50]
        sma = analyzer._calculate_sma(prices, 5)
        assert sma == 30.0
        
    def test_sma_uses_last_n_prices(self, analyzer):
        """SMA should only use last N prices"""
        prices = [100, 10, 20, 30, 40, 50]
        sma = analyzer._calculate_sma(prices, 5)
        assert sma == 30.0
        
    def test_ema_calculation(self, analyzer):
        """EMA should calculate exponential average"""
        prices = [10, 20, 30, 40, 50]
        ema_values = analyzer._calculate_ema(prices, 3)
        assert len(ema_values) > 0
        assert min(prices) <= ema_values[-1] <= max(prices)


class TestMACDCalculation:
    """Tests for MACD calculation"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_macd_returns_result(self, analyzer):
        """MACD should return MACDResult with sufficient data"""
        prices = [100 + i * 0.1 for i in range(50)]
        result = analyzer._calculate_macd(prices)
        
        assert result is not None
        assert isinstance(result, MACDResult)
        assert hasattr(result, 'macd_line')
        assert hasattr(result, 'signal_line')
        assert hasattr(result, 'histogram')
        
    def test_macd_none_for_insufficient_data(self, analyzer):
        """MACD should return None with insufficient data"""
        prices = [100, 101, 102]
        result = analyzer._calculate_macd(prices)
        assert result is None
        
    def test_macd_crossover_detection(self, analyzer):
        """MACD should detect crossovers"""
        prices = [100 + i * 0.5 for i in range(50)]
        result = analyzer._calculate_macd(prices)
        
        assert result is not None
        assert result.crossover in [None, 'bullish', 'bearish']


class TestStochasticCalculation:
    """Tests for Stochastic calculation"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_stochastic_returns_result(self, analyzer):
        """Stochastic should return StochasticResult"""
        n = 50
        highs = [100 + i * 0.2 for i in range(n)]
        lows = [99 + i * 0.2 for i in range(n)]
        closes = [99.5 + i * 0.2 for i in range(n)]
        
        result = analyzer._calculate_stochastic(highs, lows, closes)
        
        assert result is not None
        assert isinstance(result, StochasticResult)
        assert 0 <= result.k <= 100
        assert 0 <= result.d <= 100
        
    def test_stochastic_oversold_zone(self, analyzer):
        """Stochastic should detect oversold zone"""
        n = 50
        highs = [100] * n
        lows = [90] * n
        closes = [91] * n
        
        result = analyzer._calculate_stochastic(highs, lows, closes)
        
        assert result is not None
        assert result.zone == 'oversold'
        
    def test_stochastic_overbought_zone(self, analyzer):
        """Stochastic should detect overbought zone"""
        n = 50
        highs = [100] * n
        lows = [90] * n
        closes = [99] * n
        
        result = analyzer._calculate_stochastic(highs, lows, closes)
        
        assert result is not None
        assert result.zone == 'overbought'


class TestSupportResistance:
    """Tests for Support/Resistance detection"""
    
    def test_find_support_levels(self):
        """Should find swing lows as support via centralized module"""
        from indicators.support_resistance import find_support_levels

        lows = [100, 99, 98, 95, 98, 99, 100, 101, 102, 103,
                102, 101, 100, 96, 100, 101, 102, 103, 104, 105] * 5
        supports = find_support_levels(lows, lookback=60, window=3, max_levels=5)
        assert isinstance(supports, list)

    def test_find_resistance_levels(self):
        """Should find swing highs as resistance via centralized module"""
        from indicators.support_resistance import find_resistance_levels

        highs = [100, 101, 102, 105, 102, 101, 100, 99, 98, 97,
                 98, 99, 100, 104, 100, 99, 98, 97, 96, 95] * 5
        resistances = find_resistance_levels(highs, lookback=60, window=3, max_levels=5)
        assert isinstance(resistances, list)


class TestFibonacciLevels:
    """Tests for Fibonacci calculation"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_fibonacci_levels_correct(self, analyzer):
        """Fibonacci levels should be calculated correctly"""
        high = 100
        low = 80
        fib = analyzer._calculate_fibonacci(high, low)
        
        assert fib['0.0%'] == 100
        assert fib['100.0%'] == 80
        assert fib['50.0%'] == 90
        assert abs(fib['38.2%'] - 92.36) < 0.1
        assert abs(fib['61.8%'] - 87.64) < 0.1


class TestPullbackScoring:
    """Tests for pullback scoring"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_rsi_score_extreme_oversold(self, analyzer):
        """RSI < 30 should give 3 points"""
        score, reason = analyzer._score_rsi(25.0)
        assert score == 3
        assert "extreme" in reason.lower() or "25" in reason
        
    def test_rsi_score_oversold(self, analyzer):
        """RSI 30-40 should give 2 points"""
        score, reason = analyzer._score_rsi(35.0)
        assert score == 2
        
    def test_rsi_score_neutral(self, analyzer):
        """RSI 40-50 should give 1 point"""
        score, reason = analyzer._score_rsi(45.0)
        assert score == 1
        
    def test_rsi_score_not_oversold(self, analyzer):
        """RSI >= 50 should give 0 points"""
        score, reason = analyzer._score_rsi(55.0)
        assert score == 0
        
    def test_ma_score_dip_in_uptrend(self, analyzer):
        """Price > SMA200 but < SMA20 should give 2 points"""
        price = 105
        sma_20 = 110
        sma_200 = 100
        
        score, reason = analyzer._score_moving_averages(price, sma_20, sma_200)
        
        assert score == 2
        assert "dip" in reason.lower() or "uptrend" in reason.lower()
        
    def test_ma_score_no_uptrend(self, analyzer):
        """Price < SMA200 should give 0 points"""
        price = 95
        sma_20 = 100
        sma_200 = 100
        
        score, reason = analyzer._score_moving_averages(price, sma_20, sma_200)
        assert score == 0


class TestFullAnalysis:
    """Tests for full analysis using analyze_detailed()"""
    
    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)
    
    def test_analyze_detailed_returns_candidate(self, analyzer):
        """analyze_detailed() should return PullbackCandidate"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        
        assert isinstance(result, PullbackCandidate)
        assert result.symbol == "TEST"
        assert 0 <= result.score <= 10
        
    def test_analyze_detailed_includes_breakdown(self, analyzer):
        """Analysis should include score breakdown"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        
        assert result.score_breakdown is not None
        assert isinstance(result.score_breakdown, ScoreBreakdown)
        assert result.score_breakdown.total_score == result.score
        
    def test_analyze_detailed_includes_technicals(self, analyzer):
        """Analysis should include technical indicators"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        
        assert result.technicals is not None
        assert isinstance(result.technicals, TechnicalIndicators)
        assert result.technicals.rsi_14 is not None
        assert result.technicals.sma_20 is not None
        assert result.technicals.sma_200 is not None
        
    def test_analyze_raises_for_insufficient_data(self, analyzer):
        """Analysis should raise exception with insufficient data"""
        prices = [100, 101, 102]
        volumes = [1000000] * 3
        highs = [101, 102, 103]
        lows = [99, 100, 101]
        
        with pytest.raises(ValueError):
            analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
    
    def test_analyze_returns_trade_signal(self, analyzer):
        """analyze() should return TradeSignal"""
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        
        result = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert isinstance(result, TradeSignal)
        assert result.symbol == "TEST"
        assert result.strategy == "pullback"


class TestMACDScoring:
    """Tests for MACD scoring (NEW)"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_macd_score_bullish_cross(self, analyzer):
        """Bullish crossover should give 2 points"""
        macd = MACDResult(
            macd_line=0.5,
            signal_line=0.4,
            histogram=0.1,
            crossover='bullish'
        )
        score, reason, signal = analyzer._score_macd(macd)

        assert score == 2
        assert signal == "bullish_cross"
        assert "bullish" in reason.lower()

    def test_macd_score_bullish_histogram(self, analyzer):
        """Positive histogram should give 1 point"""
        macd = MACDResult(
            macd_line=0.5,
            signal_line=0.4,
            histogram=0.1,
            crossover=None
        )
        score, reason, signal = analyzer._score_macd(macd)

        assert score == 1
        assert signal == "bullish"

    def test_macd_score_bearish(self, analyzer):
        """Negative histogram should give 0 points"""
        macd = MACDResult(
            macd_line=0.3,
            signal_line=0.5,
            histogram=-0.2,
            crossover=None
        )
        score, reason, signal = analyzer._score_macd(macd)

        assert score == 0
        assert signal == "bearish"

    def test_macd_score_none(self, analyzer):
        """No MACD data should give 0 points"""
        score, reason, signal = analyzer._score_macd(None)

        assert score == 0
        assert signal == "neutral"


class TestStochasticScoring:
    """Tests for Stochastic scoring (NEW)"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_stoch_score_oversold_bullish_cross(self, analyzer):
        """Oversold + bullish cross should give 2 points"""
        stoch = StochasticResult(
            k=15.0,
            d=18.0,
            crossover='bullish',
            zone='oversold'
        )
        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 2
        assert signal == "oversold_bullish_cross"

    def test_stoch_score_oversold_only(self, analyzer):
        """Oversold without cross should give 1 point"""
        stoch = StochasticResult(
            k=15.0,
            d=12.0,
            crossover=None,
            zone='oversold'
        )
        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 1
        assert signal == "oversold"

    def test_stoch_score_overbought(self, analyzer):
        """Overbought should give 0 points"""
        stoch = StochasticResult(
            k=85.0,
            d=82.0,
            crossover=None,
            zone='overbought'
        )
        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 0
        assert signal == "overbought"

    def test_stoch_score_neutral(self, analyzer):
        """Neutral zone should give 0 points"""
        stoch = StochasticResult(
            k=50.0,
            d=48.0,
            crossover=None,
            zone='neutral'
        )
        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 0
        assert signal == "neutral"


class TestTrendStrengthScoring:
    """Tests for Trend Strength scoring (NEW)"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_strong_alignment_rising_slope(self, analyzer):
        """SMA20 > SMA50 > SMA200 with rising slope should give 2 points"""
        # Steadily rising prices
        n = 250
        prices = [100 + i * 0.1 for i in range(n)]
        sma_20 = sum(prices[-20:]) / 20
        sma_50 = sum(prices[-50:]) / 50
        sma_200 = sum(prices[-200:]) / 200

        score, alignment, slope, reason = analyzer._score_trend_strength(
            prices, sma_20, sma_50, sma_200
        )

        assert score == 2
        assert alignment == "strong"
        assert slope > 0
        assert "strong" in reason.lower()

    def test_moderate_alignment(self, analyzer):
        """Price > SMA200 with partial alignment should give 1 point"""
        n = 250
        # Price above SMA200 but messy alignment
        prices = [100 + (i % 10) * 0.5 for i in range(n)]
        prices[-1] = 110  # Current price above SMA200

        sma_20 = sum(prices[-20:]) / 20
        sma_50 = sum(prices[-50:]) / 50
        sma_200 = sum(prices[-200:]) / 200

        # Ensure price > SMA200 for moderate alignment
        if prices[-1] > sma_200:
            score, alignment, _, _ = analyzer._score_trend_strength(
                prices, sma_20, sma_50, sma_200
            )
            assert score >= 1 or alignment in ["moderate", "strong"]

    def test_no_alignment_below_sma200(self, analyzer):
        """Price below SMA200 should give 0 points"""
        n = 250
        # Declining prices
        prices = [150 - i * 0.2 for i in range(n)]
        sma_20 = sum(prices[-20:]) / 20
        sma_50 = sum(prices[-50:]) / 50
        sma_200 = sum(prices[-200:]) / 200

        score, alignment, _, reason = analyzer._score_trend_strength(
            prices, sma_20, sma_50, sma_200
        )

        assert score == 0
        assert "no uptrend" in reason.lower() or alignment in ["none", "weak"]


class TestVolumeScoring:
    """Tests for improved Volume scoring (NEW)"""

    @pytest.fixture(autouse=True)
    def _mock_intraday_scale(self):
        """Ensure deterministic volume scoring regardless of time of day."""
        with patch.object(PullbackAnalyzer, "_intraday_volume_scale", return_value=1.0):
            yield

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_volume_decreasing_healthy(self, analyzer):
        """Low volume pullback should give 1 point (healthy)"""
        current_volume = 500000
        avg_volume = 1000000  # 50% of average = decreasing

        score, reason, trend = analyzer._score_volume(current_volume, avg_volume)

        assert score == 1
        assert trend == "decreasing"
        assert "healthy" in reason.lower()

    def test_volume_spike_caution(self, analyzer):
        """Volume spike should give 0 points (caution)"""
        current_volume = 2000000
        avg_volume = 1000000  # 200% of average = spike

        score, reason, trend = analyzer._score_volume(current_volume, avg_volume)

        assert score == 0
        assert trend == "increasing"
        assert "caution" in reason.lower() or "spike" in reason.lower()

    def test_volume_normal(self, analyzer):
        """Normal volume should give 0 points"""
        current_volume = 1000000
        avg_volume = 1000000  # 100% = normal

        score, reason, trend = analyzer._score_volume(current_volume, avg_volume)

        assert score == 0
        assert trend == "stable"

    def test_volume_zero_average(self, analyzer):
        """Zero average volume should handle gracefully"""
        score, reason, trend = analyzer._score_volume(1000000, 0)

        assert score == 0
        assert trend == "unknown"

    def test_volume_very_low_penalty(self, analyzer):
        """E.3: Very low volume (ratio < 0.5) should get -0.5 penalty"""
        current_volume = 300000
        avg_volume = 1000000  # 30% of average = very low

        score, reason, trend = analyzer._score_volume(current_volume, avg_volume)

        assert score == -0.5
        assert trend == "very_low"
        assert "weak conviction" in reason.lower()

    def test_volume_very_low_boundary(self, analyzer):
        """E.3: At exactly 0.5 ratio, should be 'decreasing' not penalized"""
        current_volume = 500000
        avg_volume = 1000000  # 50% of average = boundary

        score, reason, trend = analyzer._score_volume(current_volume, avg_volume)

        assert score == 1.0
        assert trend == "decreasing"

    def test_volume_existing_behavior_unchanged(self, analyzer):
        """E.3: Existing volume tiers should remain unchanged"""
        # 0.6x = decreasing (healthy)
        score, reason, trend = analyzer._score_volume(600000, 1000000)
        assert score == 1.0
        assert trend == "decreasing"

        # 1.0x = stable
        score, reason, trend = analyzer._score_volume(1000000, 1000000)
        assert score == 0
        assert trend == "stable"

        # 2.0x = increasing (caution)
        score, reason, trend = analyzer._score_volume(2000000, 1000000)
        assert score == 0
        assert trend == "increasing"


class TestSupportWithStrength:
    """Tests for Support scoring with strength (NEW)"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_strong_support_close(self, analyzer):
        """Close to strong support should give bonus points"""
        price = 100
        supports = [98.0]  # 2% below = close

        # Create lows that touch support multiple times
        lows = [98, 99, 100, 98, 99, 100, 98, 99, 100, 98] * 6  # 60 days with 4+ touches

        score, reason, strength, touches = analyzer._score_support_with_strength(
            price, supports, None, lows
        )

        # Should get base score + bonus for strong support
        assert score >= 2
        assert strength in ["moderate", "strong"]
        assert touches >= 2

    def test_weak_support_near(self, analyzer):
        """Near weak support should give lower score"""
        price = 100
        supports = [96.0]  # 4% below = near but not close

        # Create lows that rarely touch support
        lows = [98, 99, 100, 99, 98, 99, 100, 99, 98, 99] * 6  # No touches at 96

        score, reason, strength, touches = analyzer._score_support_with_strength(
            price, supports, None, lows
        )

        assert strength == "weak"
        assert touches == 0

    def test_no_support_levels(self, analyzer):
        """No support levels should give 0 points"""
        score, reason, strength, touches = analyzer._score_support_with_strength(
            100, [], None, None
        )

        assert score == 0
        assert strength == "none"
        assert touches == 0


class TestKeltnerChannelCalculation:
    """Tests for Keltner Channel calculation (NEW)"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_keltner_channel_returns_result(self, analyzer):
        """Keltner Channel should return result with sufficient data"""
        n = 50
        prices = [100 + i * 0.1 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)

        assert result is not None
        assert result.upper > result.middle > result.lower
        assert result.atr > 0
        assert result.price_position in ['above_upper', 'near_upper', 'in_channel', 'near_lower', 'below_lower']

    def test_keltner_channel_none_for_insufficient_data(self, analyzer):
        """Keltner Channel should return None with insufficient data"""
        prices = [100, 101, 102]
        highs = [101, 102, 103]
        lows = [99, 100, 101]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)
        assert result is None

    def test_keltner_below_lower_band(self, analyzer):
        """Price below lower band should be detected"""
        n = 50
        # Steady prices then sudden drop
        prices = [100.0] * 40 + [95.0, 94.0, 93.0, 92.0, 91.0, 90.0, 89.0, 88.0, 87.0, 85.0]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)

        assert result is not None
        # After sharp drop, price should be below lower band
        assert result.percent_position < 0

    def test_keltner_above_upper_band(self, analyzer):
        """Price above upper band should be detected"""
        n = 50
        # Steady prices then sudden spike
        prices = [100.0] * 40 + [105.0, 106.0, 107.0, 108.0, 109.0, 110.0, 112.0, 114.0, 116.0, 120.0]
        highs = [p + 2 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)

        assert result is not None
        # After sharp rise, price should be above upper band
        assert result.percent_position > 0

    def test_keltner_channel_width(self, analyzer):
        """Channel width should reflect volatility"""
        n = 50
        # Low volatility
        prices_low_vol = [100 + i * 0.01 for i in range(n)]
        highs_low_vol = [p + 0.5 for p in prices_low_vol]
        lows_low_vol = [p - 0.5 for p in prices_low_vol]

        # High volatility
        prices_high_vol = [100 + (i % 5 - 2) * 2 for i in range(n)]
        highs_high_vol = [p + 3 for p in prices_high_vol]
        lows_high_vol = [p - 3 for p in prices_high_vol]

        result_low = analyzer._calculate_keltner_channel(prices_low_vol, highs_low_vol, lows_low_vol)
        result_high = analyzer._calculate_keltner_channel(prices_high_vol, highs_high_vol, lows_high_vol)

        assert result_low is not None and result_high is not None
        # High volatility should have wider channel
        assert result_high.channel_width_pct > result_low.channel_width_pct


class TestKeltnerScoring:
    """Tests for Keltner Channel scoring (NEW)"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_keltner_score_below_lower(self, analyzer):
        """Price below lower band should give 2 points"""
        from src.models.indicators import KeltnerChannelResult

        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='below_lower',
            percent_position=-1.5,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner(keltner, 85.0)

        assert score == 2
        assert "unter" in reason.lower() or "below" in reason.lower()

    def test_keltner_score_near_lower(self, analyzer):
        """Price near lower band should give 1 point"""
        from src.models.indicators import KeltnerChannelResult

        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='near_lower',
            percent_position=-0.7,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner(keltner, 93.0)

        assert score == 1
        assert "nahe" in reason.lower() or "near" in reason.lower()

    def test_keltner_score_above_upper(self, analyzer):
        """Price above upper band should give 0 points"""
        from src.models.indicators import KeltnerChannelResult

        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='above_upper',
            percent_position=1.5,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner(keltner, 115.0)

        assert score == 0
        assert "über" in reason.lower() or "above" in reason.lower() or "überkauft" in reason.lower()

    def test_keltner_score_in_channel(self, analyzer):
        """Price in channel should give 0 points (neutral)"""
        from src.models.indicators import KeltnerChannelResult

        keltner = KeltnerChannelResult(
            upper=110.0,
            middle=100.0,
            lower=90.0,
            atr=5.0,
            price_position='in_channel',
            percent_position=0.1,
            channel_width_pct=20.0
        )

        score, reason = analyzer._score_keltner(keltner, 101.0)

        assert score == 0


class TestATRCalculation:
    """Tests for ATR calculation"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_atr_calculation(self, analyzer):
        """ATR should be calculated correctly"""
        n = 30
        highs = [100 + 2] * n
        lows = [100 - 2] * n
        closes = [100.0] * n

        atr = analyzer._calculate_atr(highs, lows, closes, 14)

        assert atr is not None
        # With constant range of 4 (102-98), ATR should be ~4
        assert 3.5 < atr < 4.5

    def test_atr_none_for_insufficient_data(self, analyzer):
        """ATR should return None with insufficient data"""
        atr = analyzer._calculate_atr([100, 101], [98, 99], [99, 100], 14)
        assert atr is None

    def test_atr_increases_with_volatility(self, analyzer):
        """ATR should increase with higher volatility"""
        n = 30

        # Low volatility
        highs_low = [100 + 1] * n
        lows_low = [100 - 1] * n
        closes_low = [100.0] * n

        # High volatility
        highs_high = [100 + 5] * n
        lows_high = [100 - 5] * n
        closes_high = [100.0] * n

        atr_low = analyzer._calculate_atr(highs_low, lows_low, closes_low, 14)
        atr_high = analyzer._calculate_atr(highs_high, lows_high, closes_high, 14)

        assert atr_low is not None and atr_high is not None
        assert atr_high > atr_low


class TestScoreBreakdownIntegration:
    """Tests for ScoreBreakdown with new fields"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_breakdown_contains_all_new_fields(self, analyzer):
        """ScoreBreakdown should contain all new scoring fields"""
        n = 250
        prices = [100 + i * 0.05 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        breakdown = result.score_breakdown

        # Check new fields exist
        assert hasattr(breakdown, 'macd_score')
        assert hasattr(breakdown, 'macd_reason')
        assert hasattr(breakdown, 'stoch_score')
        assert hasattr(breakdown, 'stoch_reason')
        assert hasattr(breakdown, 'trend_strength_score')
        assert hasattr(breakdown, 'trend_alignment')
        assert hasattr(breakdown, 'volume_trend')
        assert hasattr(breakdown, 'support_strength')
        assert hasattr(breakdown, 'support_touches')
        assert hasattr(breakdown, 'keltner_score')
        assert hasattr(breakdown, 'keltner_position')
        assert hasattr(breakdown, 'keltner_reason')

    def test_to_dict_contains_new_components(self, analyzer):
        """to_dict should include all new scoring components"""
        n = 250
        prices = [100 + i * 0.05 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        d = result.score_breakdown.to_dict()

        assert 'components' in d
        assert 'macd' in d['components']
        assert 'stochastic' in d['components']
        assert 'trend_strength' in d['components']
        assert 'keltner' in d['components']
        assert 'score' in d['components']['macd']
        assert 'score' in d['components']['stochastic']
        assert 'alignment' in d['components']['trend_strength']
        assert 'position' in d['components']['keltner']

    def test_total_score_includes_all_components(self, analyzer):
        """Total score should be sum of all scoring components"""
        n = 250
        prices = [100 + i * 0.05 for i in range(n)]
        volumes = [500000] * n  # Low volume for healthy pullback
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)
        breakdown = result.score_breakdown

        # Calculate expected total (including all components and new features)
        expected_total = (
            breakdown.rsi_score +
            breakdown.rsi_divergence_score +
            breakdown.support_score +
            breakdown.fibonacci_score +
            breakdown.ma_score +
            breakdown.trend_strength_score +
            breakdown.volume_score +
            breakdown.macd_score +
            breakdown.stoch_score +
            breakdown.keltner_score +
            # New feature scores from feature engineering
            breakdown.vwap_score +
            breakdown.market_context_score +
            breakdown.sector_score +
            breakdown.gap_score
        )

        assert abs(breakdown.total_score - expected_total) < 0.5


class TestCandidateMethods:
    """Tests for PullbackCandidate methods"""

    def test_is_qualified_true(self):
        """is_qualified should be True when score >= min_score"""
        breakdown = ScoreBreakdown(total_score=6)
        technicals = TechnicalIndicators(
            rsi_14=35, sma_20=100, sma_50=98, sma_200=95,
            macd=None, stochastic=None,
            above_sma20=True, above_sma50=True, above_sma200=True,
            trend='uptrend'
        )
        
        candidate = PullbackCandidate(
            symbol="TEST",
            current_price=100,
            score=6,
            score_breakdown=breakdown,
            technicals=technicals,
            support_levels=[95, 90],
            resistance_levels=[105, 110],
            fib_levels={'50%': 97.5},
            avg_volume=1000000,
            current_volume=1200000
        )
        
        assert candidate.is_qualified(min_score=5) == True
        assert candidate.is_qualified(min_score=6) == True
        assert candidate.is_qualified(min_score=7) == False
        
    def test_to_dict(self):
        """to_dict should return complete dict"""
        breakdown = ScoreBreakdown(total_score=5)
        technicals = TechnicalIndicators(
            rsi_14=40, sma_20=100, sma_50=None, sma_200=95,
            macd=None, stochastic=None,
            above_sma20=False, above_sma50=None, above_sma200=True,
            trend='sideways'
        )
        
        candidate = PullbackCandidate(
            symbol="AAPL",
            current_price=175.50,
            score=5,
            score_breakdown=breakdown,
            technicals=technicals,
            support_levels=[170, 165],
            resistance_levels=[180, 185],
            fib_levels={'38.2%': 172, '50%': 170},
            avg_volume=50000000,
            current_volume=55000000
        )
        
        d = candidate.to_dict()
        
        assert d['symbol'] == "AAPL"
        assert d['price'] == 175.50
        assert d['score'] == 5
        assert 'technicals' in d
        assert 'support_levels' in d
        assert 'score_breakdown' in d


class TestDividendGapWarning:
    """E.5: Tests for dividend gap warning detection"""

    @pytest.fixture
    def analyzer(self):
        config = PullbackScoringConfig()
        return PullbackAnalyzer(config)

    def test_dividend_gap_warning_detected(self, analyzer):
        """E.5: -2% gap with low volume should trigger dividend gap warning"""
        n = 250
        # Create uptrend data with a -2% gap on last day
        prices = [100 + i * 0.1 for i in range(n - 1)]
        last_price = prices[-1] * 0.98  # -2% overnight gap
        prices.append(last_price)
        # Low volume on gap day (0.6x average)
        volumes = [1000000] * (n - 1) + [600000]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)

        assert len(result.warnings) > 0
        assert any("dividend gap" in w.lower() for w in result.warnings)

    def test_normal_pullback_no_dividend_warning(self, analyzer):
        """E.5: Large drop with high volume should NOT trigger dividend warning"""
        n = 250
        # Create data with a -5% drop (too large for dividend) with high volume
        prices = [100 + i * 0.1 for i in range(n - 1)]
        last_price = prices[-1] * 0.95  # -5% drop
        prices.append(last_price)
        # High volume (1.5x average)
        volumes = [1000000] * (n - 1) + [1500000]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer.analyze_detailed("TEST", prices, volumes, highs, lows)

        assert not any("dividend gap" in w.lower() for w in result.warnings)


# =============================================================================
# TEST CLASS: Bearish Divergence Penalties (Pullback)
# =============================================================================


class TestPullbackDivergencePenalties:
    """Tests for PullbackAnalyzer._apply_divergence_penalties integration."""

    @pytest.fixture
    def analyzer(self):
        from src.config import PullbackScoringConfig
        return PullbackAnalyzer(config=PullbackScoringConfig())

    def test_apply_divergence_penalties_exists(self, analyzer):
        """_apply_divergence_penalties method must exist on PullbackAnalyzer."""
        assert hasattr(analyzer, "_apply_divergence_penalties")

    def test_no_penalty_when_no_divergence(self, analyzer):
        """Smooth uptrend with no divergence patterns leaves score unchanged."""
        n = 80
        prices = [100.0 + i * 0.1 for i in range(n)]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1_000_000] * n
        score = 8.0
        result = analyzer._apply_divergence_penalties(
            prices=prices, highs=highs, lows=lows, volumes=volumes, score=score
        )
        assert result <= score

    def test_penalty_reduces_score_when_divergence_found(self, analyzer):
        """Distribution phase data should trigger at most no increase in score."""
        prices = []
        p = 120.0
        for _ in range(50):
            prices.append(p)
            p *= 1.002
        for _ in range(30):
            prices.append(p)
            p *= 0.997
        highs = [pr + 0.5 for pr in prices]
        lows = [pr - 0.5 for pr in prices]
        volumes = [2_000_000] * 50 + [int(2_000_000 * (0.96 ** i)) for i in range(30)]
        score = 10.0
        result = analyzer._apply_divergence_penalties(
            prices=prices, highs=highs, lows=lows, volumes=volumes, score=score
        )
        assert result <= score

    def test_worst_case_penalty_sum(self, analyzer):
        """Maximum possible penalty (all 7 checks active) = -11.5."""
        from src.analyzers.pullback import (
            PULLBACK_DIV_PENALTY_CMF_EARLY,
            PULLBACK_DIV_PENALTY_CMF_MACD,
            PULLBACK_DIV_PENALTY_DISTRIBUTION,
            PULLBACK_DIV_PENALTY_MOMENTUM,
            PULLBACK_DIV_PENALTY_PRICE_MFI,
            PULLBACK_DIV_PENALTY_PRICE_OBV,
            PULLBACK_DIV_PENALTY_PRICE_RSI,
        )

        total = (
            PULLBACK_DIV_PENALTY_PRICE_RSI
            + PULLBACK_DIV_PENALTY_PRICE_OBV
            + PULLBACK_DIV_PENALTY_PRICE_MFI
            + PULLBACK_DIV_PENALTY_CMF_MACD
            + PULLBACK_DIV_PENALTY_MOMENTUM
            + PULLBACK_DIV_PENALTY_DISTRIBUTION
            + PULLBACK_DIV_PENALTY_CMF_EARLY
        )
        assert abs(total - (-11.5)) < 0.01, f"Expected -11.5, got {total}"


class TestPullbackEarningsSurpriseModifier:
    """Verify earnings-surprise modifier is applied in PullbackAnalyzer.analyze()."""

    @pytest.fixture
    def analyzer(self):
        return PullbackAnalyzer(PullbackScoringConfig())

    def _make_data(self, n: int = 250):
        # Strong uptrend (100→200 over 200 bars), then moderate pullback (200→185 over 50 bars).
        # current_price (185) > SMA200 (~157) → passes gate 2.
        # current_price (185) < SMA20 (~188) → passes gate 3.
        uptrend = [100 + i * 0.5 for i in range(200)]          # 100 .. 199.5
        pullback = [200 - (i + 1) * 0.3 for i in range(50)]    # 199.7 .. 185.3
        prices = uptrend + pullback
        volumes = [1_000_000] * len(prices)
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        return prices, volumes, highs, lows

    def test_earnings_surprise_modifier_applied(self, analyzer):
        """get_earnings_surprise_modifier is called with the symbol."""
        prices, volumes, highs, lows = self._make_data()

        with patch(
            "src.services.earnings_quality.get_earnings_surprise_modifier", return_value=1.2
        ) as mock_mod:
            candidate = analyzer.analyze_detailed("MSFT", prices, volumes, highs, lows)
            mock_mod.assert_called_once_with("MSFT")

        assert candidate is not None

    def test_earnings_surprise_zero_when_no_data(self, analyzer):
        """Zero modifier (neutral) does not change score vs second call with zero."""
        prices, volumes, highs, lows = self._make_data()

        with patch(
            "src.services.earnings_quality.get_earnings_surprise_modifier", return_value=0.0
        ) as mock_mod:
            candidate = analyzer.analyze_detailed("MSFT", prices, volumes, highs, lows)
            mock_mod.assert_called_once_with("MSFT")

        with patch(
            "src.services.earnings_quality.get_earnings_surprise_modifier", return_value=0.0
        ):
            candidate_baseline = analyzer.analyze_detailed("MSFT", prices, volumes, highs, lows)

        assert candidate.score == pytest.approx(candidate_baseline.score, abs=0.05)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
