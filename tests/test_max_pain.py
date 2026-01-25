# OptionPlay - Max Pain Tests
# =============================

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from max_pain import (
    MaxPainCalculator,
    MaxPainResult,
    calculate_max_pain
)


class TestMaxPainCalculation:
    """Tests für Max-Pain-Berechnung"""
    
    def test_max_pain_basic(self):
        """Grundlegende Max-Pain-Berechnung"""
        calc = MaxPainCalculator()
        
        calls = {100: 100, 105: 200, 110: 500}
        puts = {100: 500, 105: 200, 110: 100}
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=105.0,
            calls=calls,
            puts=puts
        )
        
        assert result is not None
        assert result.symbol == "TEST"
        assert result.max_pain in [100, 105, 110]
        
    def test_put_wall_detection(self):
        """Put Wall sollte höchstes Put OI sein"""
        calc = MaxPainCalculator()
        
        calls = {100: 100, 105: 100, 110: 100}
        puts = {100: 1000, 105: 200, 110: 100}
        
        result = calc.calculate(
            symbol="TEST", expiry="20250321",
            current_price=105.0, calls=calls, puts=puts
        )
        
        assert result.put_wall == 100
        assert result.put_wall_oi == 1000
        
    def test_call_wall_detection(self):
        """Call Wall sollte höchstes Call OI sein"""
        calc = MaxPainCalculator()
        
        calls = {100: 100, 105: 200, 110: 1000}
        puts = {100: 100, 105: 100, 110: 100}
        
        result = calc.calculate(
            symbol="TEST", expiry="20250321",
            current_price=105.0, calls=calls, puts=puts
        )
        
        assert result.call_wall == 110
        assert result.call_wall_oi == 1000
        
    def test_pcr_calculation(self):
        """Put/Call Ratio sollte korrekt sein"""
        calc = MaxPainCalculator()
        
        calls = {100: 100, 105: 100}  # Total: 200
        puts = {100: 150, 105: 150}   # Total: 300
        
        result = calc.calculate(
            symbol="TEST", expiry="20250321",
            current_price=102.0, calls=calls, puts=puts
        )
        
        assert result.pcr == 1.5
        assert result.total_put_oi == 300
        assert result.total_call_oi == 200


class TestMaxPainResult:
    """Tests für MaxPainResult Methoden"""
    
    def test_price_vs_max_pain_above(self):
        """Preis über Max Pain sollte 'above' sein"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=110.0, max_pain=100.0, distance_pct=10.0,
            put_wall=95.0, put_wall_oi=500,
            call_wall=115.0, call_wall_oi=500,
            total_put_oi=1000, total_call_oi=1000, pcr=1.0
        )
        
        assert result.price_vs_max_pain() == "above"
        
    def test_price_vs_max_pain_below(self):
        """Preis unter Max Pain sollte 'below' sein"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=90.0, max_pain=100.0, distance_pct=-10.0,
            put_wall=95.0, put_wall_oi=500,
            call_wall=115.0, call_wall_oi=500,
            total_put_oi=1000, total_call_oi=1000, pcr=1.0
        )
        
        assert result.price_vs_max_pain() == "below"
        
    def test_price_vs_max_pain_at(self):
        """Preis bei Max Pain sollte 'at' sein"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=100.0, max_pain=100.0, distance_pct=0.0,
            put_wall=95.0, put_wall_oi=500,
            call_wall=115.0, call_wall_oi=500,
            total_put_oi=1000, total_call_oi=1000, pcr=1.0
        )
        
        assert result.price_vs_max_pain() == "at"
        
    def test_sentiment_bearish(self):
        """PCR > 1.2 sollte bearish sein"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=100.0, max_pain=100.0, distance_pct=0.0,
            put_wall=None, put_wall_oi=0, call_wall=None, call_wall_oi=0,
            total_put_oi=1500, total_call_oi=1000, pcr=1.5
        )
        
        assert result.sentiment() == "bearish"
        
    def test_sentiment_bullish(self):
        """PCR < 0.8 sollte bullish sein"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=100.0, max_pain=100.0, distance_pct=0.0,
            put_wall=None, put_wall_oi=0, call_wall=None, call_wall_oi=0,
            total_put_oi=500, total_call_oi=1000, pcr=0.5
        )
        
        assert result.sentiment() == "bullish"
        
    def test_sentiment_neutral(self):
        """PCR 0.8-1.2 sollte neutral sein"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=100.0, max_pain=100.0, distance_pct=0.0,
            put_wall=None, put_wall_oi=0, call_wall=None, call_wall_oi=0,
            total_put_oi=1000, total_call_oi=1000, pcr=1.0
        )
        
        assert result.sentiment() == "neutral"
        
    def test_gravity_direction(self):
        """gravity_direction sollte Tendenz anzeigen"""
        result_above = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=110.0, max_pain=100.0, distance_pct=10.0,
            put_wall=None, put_wall_oi=0, call_wall=None, call_wall_oi=0,
            total_put_oi=1000, total_call_oi=1000, pcr=1.0
        )
        assert result_above.gravity_direction() == "down"
        
        result_below = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=90.0, max_pain=100.0, distance_pct=-10.0,
            put_wall=None, put_wall_oi=0, call_wall=None, call_wall_oi=0,
            total_put_oi=1000, total_call_oi=1000, pcr=1.0
        )
        assert result_below.gravity_direction() == "up"


class TestCalculateFromChain:
    """Tests für Berechnung aus Options-Chain"""
    
    def test_calculate_from_chain(self):
        """Berechnung aus Options-Chain Format"""
        calc = MaxPainCalculator()
        
        chain = [
            {'strike': 100, 'option_type': 'call', 'open_interest': 500},
            {'strike': 100, 'option_type': 'put', 'open_interest': 800},
            {'strike': 105, 'option_type': 'call', 'open_interest': 600},
            {'strike': 105, 'option_type': 'put', 'open_interest': 400},
        ]
        
        result = calc.calculate_from_chain(
            symbol="TEST",
            options_chain=chain,
            current_price=102.0
        )
        
        assert result is not None
        assert result.total_call_oi == 1100
        assert result.total_put_oi == 1200


class TestConvenienceFunction:
    """Tests für calculate_max_pain Funktion"""
    
    def test_calculate_max_pain_function(self):
        """calculate_max_pain sollte funktionieren"""
        chain = [
            {'strike': 100, 'option_type': 'call', 'open_interest': 500},
            {'strike': 100, 'option_type': 'put', 'open_interest': 500},
        ]
        
        result = calculate_max_pain("TEST", chain, 100.0)
        
        assert result is not None
        assert isinstance(result, MaxPainResult)


class TestEdgeCases:
    """Tests für Grenzfälle"""
    
    def test_empty_chain(self):
        """Leere Chain sollte None zurückgeben"""
        calc = MaxPainCalculator()
        
        result = calc.calculate_from_chain(
            symbol="TEST", options_chain=[], current_price=100.0
        )
        
        assert result is None
        
    def test_only_calls(self):
        """Nur Calls sollte funktionieren"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST", expiry="20250321",
            current_price=100.0,
            calls={100: 500}, puts={}
        )
        
        assert result is not None
        assert result.total_put_oi == 0
        
    def test_only_puts(self):
        """Nur Puts sollte funktionieren"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST", expiry="20250321",
            current_price=100.0,
            calls={}, puts={100: 500}
        )
        
        assert result is not None
        assert result.total_call_oi == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
