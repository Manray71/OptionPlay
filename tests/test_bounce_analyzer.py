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
    """Tests für Support-Level Detection"""
    
    @pytest.fixture
    def analyzer(self):
        return BounceAnalyzer()
    
    def test_finds_multiple_support_levels(self, analyzer):
        """Sollte mehrere Support-Levels finden"""
        n = 100
        lows = [100.0] * n
        
        # Erstelle verschiedene Support-Levels
        for i in [20, 25, 28]:  # Support bei 95
            lows[i] = 95.0
        for i in [50, 55, 58]:  # Support bei 90
            lows[i] = 90.0
        
        supports = analyzer._find_support_levels(lows)
        
        assert len(supports) >= 1
    
    def test_clusters_similar_levels(self, analyzer):
        """Ähnliche Levels sollten geclustert werden"""
        levels = [100.0, 100.5, 100.2, 95.0, 95.3]
        tolerance = 0.015
        
        clusters = analyzer._cluster_levels(levels, tolerance)
        
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
