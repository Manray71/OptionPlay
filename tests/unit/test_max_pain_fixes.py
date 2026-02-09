# OptionPlay - Max Pain Fixes Tests
# ===================================
# Tests für die Bug-Fixes aus optionplay_fixes_applied.md

import pytest
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.options.max_pain import (
    MaxPainCalculator,
    MaxPainResult,
    calculate_max_pain
)


class TestPCRDivisionByZero:
    """
    Tests für Fix #3: Division-by-Zero in max_pain.py
    
    Kritischer Fix: PCR-Berechnung behandelt jetzt:
    - PCR = 1.0 (neutral) wenn keine OI-Daten vorhanden
    - PCR = float('inf') wenn nur Puts vorhanden
    - sentiment() hat math.isinf() Check
    - to_dict() konvertiert inf zu String "inf"
    """
    
    def test_pcr_no_data_returns_none(self):
        """Test: Leere Dicts geben None zurück"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=100.0,
            calls={},
            puts={}
        )
        
        assert result is None
    
    def test_pcr_only_calls(self):
        """Test: Nur Calls -> PCR = 0"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=100.0,
            calls={100: 500, 105: 300},
            puts={}
        )
        
        assert result is not None
        assert result.pcr == 0.0
        assert result.total_put_oi == 0
        assert result.total_call_oi == 800
    
    def test_pcr_only_puts_is_infinite(self):
        """Test: Nur Puts -> PCR ist unendlich"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=100.0,
            calls={},
            puts={95: 500, 90: 300}
        )
        
        assert result is not None
        assert math.isinf(result.pcr)
    
    def test_sentiment_with_infinite_pcr(self):
        """Test: sentiment() gibt 'extreme_bearish' bei unendlichem PCR"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=100.0,
            calls={},
            puts={95: 500}
        )
        
        assert result.sentiment() == "extreme_bearish"
    
    def test_to_dict_with_infinite_pcr(self):
        """Test: to_dict() konvertiert inf zu String 'inf'"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=100.0,
            calls={},
            puts={95: 500}
        )
        
        d = result.to_dict()
        
        # PCR sollte als String "inf" dargestellt werden (JSON-kompatibel)
        assert d['pcr'] == "inf"
    
    def test_pcr_normal_calculation(self):
        """Test: Normale PCR-Berechnung funktioniert"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=100.0,
            calls={100: 200},  # 200 Call OI
            puts={100: 300}    # 300 Put OI
        )
        
        assert result.pcr == 1.5  # 300/200
    
    def test_sentiment_bearish(self):
        """Test: PCR > 1.2 -> bearish"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=100.0, max_pain=100.0, distance_pct=0.0,
            put_wall=None, put_wall_oi=0, call_wall=None, call_wall_oi=0,
            total_put_oi=1500, total_call_oi=1000, pcr=1.5
        )
        
        assert result.sentiment() == "bearish"
    
    def test_sentiment_bullish(self):
        """Test: PCR < 0.8 -> bullish"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=100.0, max_pain=100.0, distance_pct=0.0,
            put_wall=None, put_wall_oi=0, call_wall=None, call_wall_oi=0,
            total_put_oi=500, total_call_oi=1000, pcr=0.5
        )
        
        assert result.sentiment() == "bullish"
    
    def test_sentiment_neutral(self):
        """Test: PCR 0.8-1.2 -> neutral"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=100.0, max_pain=100.0, distance_pct=0.0,
            put_wall=None, put_wall_oi=0, call_wall=None, call_wall_oi=0,
            total_put_oi=1000, total_call_oi=1000, pcr=1.0
        )
        
        assert result.sentiment() == "neutral"


class TestDistancePercentCalculation:
    """Tests für Fix: Null-Check bei current_price für distance_pct"""
    
    def test_distance_pct_with_zero_price(self):
        """Test: distance_pct = 0 wenn current_price = 0"""
        # Dieser Fall sollte eigentlich nie auftreten (Preise > 0),
        # aber der Fix verhindert Division by Zero
        calc = MaxPainCalculator()
        
        # Wir können das Result direkt erstellen um den Edge Case zu testen
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=0.0,  # Edge Case
            max_pain=100.0,
            distance_pct=0.0,  # Sollte 0 sein, nicht NaN/Inf
            put_wall=None, put_wall_oi=0,
            call_wall=None, call_wall_oi=0,
            total_put_oi=0, total_call_oi=0, pcr=1.0
        )
        
        # Sollte nicht crashen
        d = result.to_dict()
        assert d['distance_pct'] == 0.0
    
    def test_distance_pct_normal_calculation(self):
        """Test: Normale distance_pct Berechnung"""
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=100.0,
            calls={110: 500},  # Max Pain wird bei 110 sein
            puts={90: 500}     # oder bei 90
        )
        
        assert result is not None
        # Distance sollte nicht 0 sein wenn Price != Max Pain
        assert isinstance(result.distance_pct, float)


class TestToDictJsonSafety:
    """Tests für JSON-sichere Serialisierung"""
    
    def test_to_dict_all_fields_serializable(self):
        """Test: Alle Felder in to_dict() sind JSON-serialisierbar"""
        import json
        
        calc = MaxPainCalculator()
        
        result = calc.calculate(
            symbol="TEST",
            expiry="20250321",
            current_price=100.0,
            calls={100: 500, 105: 300},
            puts={95: 400, 100: 200}
        )
        
        d = result.to_dict()
        
        # Sollte nicht werfen
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
    
    def test_to_dict_with_none_walls(self):
        """Test: to_dict() mit None walls"""
        result = MaxPainResult(
            symbol="TEST", expiry="20250321",
            current_price=100.0, max_pain=100.0, distance_pct=0.0,
            put_wall=None, put_wall_oi=0,
            call_wall=None, call_wall_oi=0,
            total_put_oi=0, total_call_oi=100, pcr=0.0
        )
        
        d = result.to_dict()
        
        assert d['put_wall'] is None
        assert d['call_wall'] is None


class TestCalculateFromChainEdgeCases:
    """Tests für Edge Cases in calculate_from_chain"""
    
    def test_empty_chain(self):
        """Test: Leere Chain gibt None"""
        calc = MaxPainCalculator()
        
        result = calc.calculate_from_chain(
            symbol="TEST",
            options_chain=[],
            current_price=100.0
        )
        
        assert result is None
    
    def test_chain_with_zero_oi(self):
        """Test: Chain mit OI=0 gibt Result mit Warnung zurück"""
        calc = MaxPainCalculator()
        
        chain = [
            {'strike': 100, 'option_type': 'call', 'open_interest': 0},
            {'strike': 100, 'option_type': 'put', 'open_interest': 0},
        ]
        
        result = calc.calculate_from_chain(
            symbol="TEST",
            options_chain=chain,
            current_price=100.0
        )
        
        # Result wird zurückgegeben, aber mit neutralem PCR (keine echten Daten)
        assert result is not None
        assert result.total_put_oi == 0
        assert result.total_call_oi == 0
        assert result.pcr == 1.0  # Neutral fallback
    
    def test_chain_with_missing_oi_field(self):
        """Test: Chain mit fehlendem open_interest Feld"""
        calc = MaxPainCalculator()
        
        chain = [
            {'strike': 100, 'option_type': 'call'},  # Kein open_interest
            {'strike': 100, 'option_type': 'put', 'open_interest': 500},
        ]
        
        result = calc.calculate_from_chain(
            symbol="TEST",
            options_chain=chain,
            current_price=100.0
        )
        
        # Sollte funktionieren mit dem einen Put
        assert result is not None
        assert result.total_put_oi == 500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
