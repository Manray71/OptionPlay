# OptionPlay - Bounce Analyzer Tests
# =====================================

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.bounce import BounceAnalyzer, BounceConfig
from models.base import SignalType, SignalStrength


class TestBounceBasics:
    """Grundlegende Tests für Bounce Analyzer"""
    
    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()
    
    @pytest.fixture
    def bounce_data(self):
        """Generiert Daten mit Support-Bounce"""
        n = 100
        prices = []
        highs = []
        lows = []
        
        # Aufwärtstrend, dann Pullback zum Support, dann Bounce
        for i in range(n):
            if i < 60:
                # Aufwärtstrend
                base = 100 + i * 0.3
            elif i < 80:
                # Pullback zum Support bei ~110
                base = 118 - (i - 60) * 0.4
            else:
                # Bounce vom Support
                base = 110 + (i - 80) * 0.2
            
            prices.append(base)
            highs.append(base + 1)
            lows.append(base - 1)
        
        # Erstelle Support-Touches
        lows[30] = 109.5  # Support Touch 1
        lows[50] = 109.8  # Support Touch 2
        lows[78] = 109.2  # Support Touch 3 (aktueller Bounce)
        
        volumes = [1000000] * n
        volumes[-1] = 1500000  # Erhöhtes Volumen beim Bounce
        
        return prices, volumes, highs, lows
    
    def test_strategy_name(self, analyzer):
        """Strategy Name sollte korrekt sein"""
        assert analyzer.strategy_name == "bounce"
    
    def test_bounce_detected(self, analyzer, bounce_data):
        """Support Bounce sollte erkannt werden"""
        prices, volumes, highs, lows = bounce_data
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        # Bounce sollte erkannt werden
        assert "Support" in signal.reason or signal.score > 0
    
    def test_no_bounce_without_support(self, analyzer):
        """Kein Signal ohne etablierten Support"""
        n = 100
        # Konstant fallende Preise (kein Support)
        prices = [100 - i * 0.2 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL


class TestBounceConfig:
    """Tests für Bounce Konfiguration"""
    
    def test_custom_config(self):
        """Custom Config sollte angewendet werden"""
        config = BounceConfig(
            support_touches_min=3,
            rsi_oversold_threshold=35.0,
            min_score_for_signal=7
        )
        
        analyzer = BounceAnalyzer(config)
        
        assert analyzer.config.support_touches_min == 3
        assert analyzer.config.rsi_oversold_threshold == 35.0


class TestBounceSupportDetection:
    """Tests für Support-Level Detection via centralized module"""

    def test_finds_multiple_support_levels(self):
        """Sollte mehrere Support-Levels finden über zentrales Modul"""
        # This test now validates the integration with the optimized module
        from indicators.support_resistance import find_support_levels

        n = 100
        lows = [100.0] * n

        # Erstelle verschiedene Support-Levels
        for i in [20, 25, 28]:  # Support bei 95
            lows[i] = 95.0
        for i in [50, 55, 58]:  # Support bei 90
            lows[i] = 90.0

        supports = find_support_levels(lows, lookback=80, window=3, max_levels=5)

        assert len(supports) >= 1

    def test_clusters_similar_levels(self):
        """Ähnliche Levels sollten geclustert werden via zentrales Modul"""
        from indicators.support_resistance import cluster_levels

        levels = [100.0, 100.5, 100.2, 95.0, 95.3]
        indices = [10, 20, 30, 40, 50]  # Dummy indices für Test
        tolerance_pct = 1.5

        clusters = cluster_levels(levels, indices=indices, tolerance_pct=tolerance_pct)

        # Sollte zwei Cluster haben: ~100 und ~95
        assert len(clusters) == 2


class TestBounceCandlestickPatterns:
    """Tests für Candlestick Pattern Recognition"""
    
    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()
    
    def test_detects_hammer(self, analyzer):
        """Hammer Pattern sollte erkannt werden"""
        # Hammer: kleiner Body oben, langer unterer Docht
        prices = [100, 99, 100.5]  # Close nahe High
        highs = [101, 100, 101]
        lows = [99, 98, 96]  # Langer unterer Docht
        
        score, info = analyzer._score_candlestick_pattern(prices, highs, lows)
        
        # Könnte Hammer oder Bullish Candle sein
        assert info['pattern'] is not None
    
    def test_detects_bullish_candle(self, analyzer):
        """Bullish Candle sollte erkannt werden"""
        prices = [100, 99, 102]  # Grüne Kerze
        highs = [101, 100, 103]
        lows = [99, 98, 101]
        
        score, info = analyzer._score_candlestick_pattern(prices, highs, lows)
        
        assert info['bullish'] == True


class TestBounceRSI:
    """Tests für RSI Oversold Detection"""
    
    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()
    
    def test_rsi_oversold_detection(self, analyzer):
        """Oversold RSI sollte erkannt werden"""
        # Stark fallende Preise -> niedriger RSI
        prices = [100 - i * 0.5 for i in range(50)]
        
        score, rsi = analyzer._score_rsi_oversold(prices)
        
        assert rsi < 40
        assert score >= 1
    
    def test_rsi_neutral_no_bonus(self, analyzer):
        """Neutraler RSI sollte keinen Bonus geben"""
        # Seitwärts-Preise
        prices = [100 + (i % 2) * 0.5 for i in range(50)]
        
        score, rsi = analyzer._score_rsi_oversold(prices)
        
        assert 40 < rsi < 60
        assert score == 0


class TestBounceEdgeCases:
    """Edge Cases für Bounce Analyzer"""
    
    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()
    
    def test_insufficient_data(self, analyzer):
        """Zu wenig Daten sollte Exception werfen"""
        prices = [100] * 30
        volumes = [1000000] * 30
        highs = [101] * 30
        lows = [99] * 30
        
        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)
    
    def test_downtrend_warning(self, analyzer):
        """Downtrend sollte Warnung generieren"""
        n = 100
        prices = [100 - i * 0.3 for i in range(n)]  # Abwärtstrend
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        # Entweder Warnung oder niedriger Score
        has_warning = any("trend" in w.lower() or "risiko" in w.lower() 
                         for w in signal.warnings)
        assert has_warning or signal.score < 5


# =============================================================================
# NEW TESTS: MACD, Stochastic, Keltner Channel Scoring
# =============================================================================

class TestBounceMACDScoring:
    """Tests for MACD scoring in Bounce Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()

    def test_macd_score_bullish_cross(self, analyzer):
        """Bullish crossover should give 2 points"""
        from models.indicators import MACDResult

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
        from models.indicators import MACDResult

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
        from models.indicators import MACDResult

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

    def test_macd_calculation(self, analyzer):
        """MACD should be calculated correctly with sufficient data"""
        n = 50
        # Rising prices should produce positive MACD
        prices = [100 + i * 0.5 for i in range(n)]

        result = analyzer._calculate_macd(prices)

        assert result is not None
        assert hasattr(result, 'macd_line')
        assert hasattr(result, 'signal_line')
        assert hasattr(result, 'histogram')

    def test_macd_insufficient_data(self, analyzer):
        """MACD should return None with insufficient data"""
        prices = [100, 101, 102]

        result = analyzer._calculate_macd(prices)
        assert result is None


class TestBounceStochasticScoring:
    """Tests for Stochastic scoring in Bounce Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()

    def test_stoch_score_oversold_bullish_cross(self, analyzer):
        """Oversold + bullish cross should give 2 points"""
        from models.indicators import StochasticResult

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
        from models.indicators import StochasticResult

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
        from models.indicators import StochasticResult

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
        from models.indicators import StochasticResult

        stoch = StochasticResult(
            k=50.0,
            d=48.0,
            crossover=None,
            zone='neutral'
        )
        score, reason, signal = analyzer._score_stochastic(stoch)

        assert score == 0
        assert signal == "neutral"

    def test_stoch_calculation(self, analyzer):
        """Stochastic should be calculated correctly"""
        n = 30
        prices = [100 + i * 0.1 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_stochastic(prices, highs, lows)

        assert result is not None
        assert hasattr(result, 'k')
        assert hasattr(result, 'd')
        assert hasattr(result, 'zone')
        assert 0 <= result.k <= 100
        assert 0 <= result.d <= 100

    def test_stoch_insufficient_data(self, analyzer):
        """Stochastic should return None with insufficient data"""
        prices = [100, 101, 102]
        highs = [101, 102, 103]
        lows = [99, 100, 101]

        result = analyzer._calculate_stochastic(prices, highs, lows)
        assert result is None


class TestBounceKeltnerScoring:
    """Tests for Keltner Channel scoring in Bounce Analyzer (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()

    def test_keltner_score_below_lower(self, analyzer):
        """Price below lower band should give 2 points"""
        from models.indicators import KeltnerChannelResult

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
        from models.indicators import KeltnerChannelResult

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
        from models.indicators import KeltnerChannelResult

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
        from models.indicators import KeltnerChannelResult

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

    def test_keltner_calculation(self, analyzer):
        """Keltner Channel should be calculated correctly"""
        n = 50
        prices = [100 + i * 0.1 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)

        assert result is not None
        assert result.upper > result.middle > result.lower
        assert result.atr > 0
        assert result.price_position in ['above_upper', 'near_upper', 'in_channel', 'near_lower', 'below_lower']

    def test_keltner_insufficient_data(self, analyzer):
        """Keltner should return None with insufficient data"""
        prices = [100, 101, 102]
        highs = [101, 102, 103]
        lows = [99, 100, 101]

        result = analyzer._calculate_keltner_channel(prices, highs, lows)
        assert result is None


class TestBounceScoreBreakdown:
    """Tests for BounceScoreBreakdown (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()

    @pytest.fixture
    def full_data(self):
        """Generiert vollständige Daten für Score-Tests"""
        n = 100
        prices = []
        highs = []
        lows = []

        # Aufwärtstrend mit Pullback zum Support
        for i in range(n):
            if i < 60:
                base = 100 + i * 0.3
            elif i < 80:
                base = 118 - (i - 60) * 0.4
            else:
                base = 110 + (i - 80) * 0.2

            prices.append(base)
            highs.append(base + 1)
            lows.append(base - 1)

        # Support touches
        lows[30] = 109.5
        lows[50] = 109.8
        lows[78] = 109.2

        volumes = [1000000] * n
        volumes[-1] = 1500000

        return prices, volumes, highs, lows

    def test_breakdown_contains_all_new_fields(self, analyzer, full_data):
        """BounceScoreBreakdown should contain all new scoring fields"""
        prices, volumes, highs, lows = full_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        breakdown = signal.details.get('score_breakdown', {})

        # Check that all components exist
        assert 'components' in breakdown
        components = breakdown['components']

        assert 'support' in components
        assert 'rsi' in components
        assert 'candlestick' in components
        assert 'volume' in components
        assert 'trend' in components
        assert 'macd' in components
        assert 'stochastic' in components
        assert 'keltner' in components

    def test_breakdown_macd_fields(self, analyzer, full_data):
        """MACD component should have correct fields"""
        prices, volumes, highs, lows = full_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        macd_info = signal.details['score_breakdown']['components']['macd']

        assert 'score' in macd_info
        assert 'signal' in macd_info
        assert 'histogram' in macd_info
        assert 'reason' in macd_info

    def test_breakdown_stochastic_fields(self, analyzer, full_data):
        """Stochastic component should have correct fields"""
        prices, volumes, highs, lows = full_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        stoch_info = signal.details['score_breakdown']['components']['stochastic']

        assert 'score' in stoch_info
        assert 'signal' in stoch_info
        assert 'k' in stoch_info
        assert 'd' in stoch_info
        assert 'reason' in stoch_info

    def test_breakdown_keltner_fields(self, analyzer, full_data):
        """Keltner component should have correct fields"""
        prices, volumes, highs, lows = full_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        keltner_info = signal.details['score_breakdown']['components']['keltner']

        assert 'score' in keltner_info
        assert 'position' in keltner_info
        assert 'percent' in keltner_info
        assert 'reason' in keltner_info

    def test_total_score_includes_all_components(self, analyzer, full_data):
        """Total score should include all component scores"""
        prices, volumes, highs, lows = full_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        breakdown = signal.details['score_breakdown']

        # Calculate expected total from components
        components = breakdown['components']
        expected_total = sum([
            components['support']['score'],
            components['rsi']['score'],
            components['candlestick']['score'],
            components['volume']['score'],
            components['trend']['score'],
            components['macd']['score'],
            components['stochastic']['score'],
            components['keltner']['score']
        ])

        assert abs(breakdown['total_score'] - expected_total) < 0.01

    def test_max_possible_is_17(self, analyzer, full_data):
        """Max possible score should be 17"""
        prices, volumes, highs, lows = full_data

        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        breakdown = signal.details['score_breakdown']

        assert breakdown['max_possible'] == 17


class TestBounceHelperMethods:
    """Tests for helper methods (NEW)"""

    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()

    def test_calculate_ema(self, analyzer):
        """EMA should be calculated correctly"""
        values = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]

        ema = analyzer._calculate_ema(values, 5)

        assert ema is not None
        assert len(ema) > 0
        # EMA should be close to recent values
        assert 105 < ema[-1] < 111

    def test_calculate_ema_insufficient_data(self, analyzer):
        """EMA should return None with insufficient data"""
        values = [100, 101, 102]

        ema = analyzer._calculate_ema(values, 10)
        assert ema is None

    def test_calculate_atr(self, analyzer):
        """ATR should be calculated correctly"""
        n = 30
        highs = [100 + 2] * n
        lows = [100 - 2] * n
        closes = [100.0] * n

        atr = analyzer._calculate_atr(highs, lows, closes, 14)

        assert atr is not None
        # With constant range of 4 (102-98), ATR should be ~4
        assert 3.5 < atr < 4.5

    def test_calculate_atr_insufficient_data(self, analyzer):
        """ATR should return None with insufficient data"""
        atr = analyzer._calculate_atr([100, 101], [98, 99], [99, 100], 14)
        assert atr is None

    def test_count_support_touches(self, analyzer):
        """Support touches should be counted correctly"""
        n = 100
        lows = [100.0] * n

        # Create touches at support level 95
        lows[20] = 95.0
        lows[40] = 95.2
        lows[60] = 94.8

        touches = analyzer._count_support_touches(lows, 95.0, 0.015)

        assert touches >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
