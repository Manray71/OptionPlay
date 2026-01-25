# OptionPlay - Support/Resistance Indicator Tests
# =================================================
# Tests für src/indicators/support_resistance.py

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indicators.support_resistance import (
    find_support_levels,
    find_resistance_levels,
    calculate_fibonacci,
    find_pivot_points,
    price_near_level
)


class TestFindSupportLevels:
    """Tests für Support-Level-Erkennung"""
    
    def test_finds_swing_lows(self):
        """Test: Findet Swing Lows als Support"""
        # Erstelle Daten mit klarem Support bei 90
        lows = [100, 98, 95, 90, 92, 95, 98, 100, 98, 95, 90, 92, 95] * 5
        
        supports = find_support_levels(lows, lookback=60, window=3, max_levels=3)
        
        assert len(supports) > 0
        assert 90 in supports
    
    def test_returns_max_levels(self):
        """Test: Gibt nur max_levels zurück"""
        lows = list(range(100, 0, -1)) + list(range(0, 100))  # V-Formation
        
        supports = find_support_levels(lows, lookback=100, window=10, max_levels=2)
        
        assert len(supports) <= 2
    
    def test_empty_for_insufficient_data(self):
        """Test: Leere Liste bei zu wenig Daten"""
        lows = [100, 99, 98]  # Nur 3 Datenpunkte
        
        supports = find_support_levels(lows, lookback=60, window=20)
        
        assert supports == []
    
    def test_sorted_ascending(self):
        """Test: Supports sind aufsteigend sortiert"""
        lows = [100] * 20 + [90] * 20 + [95] * 20 + [85] * 20 + [92] * 20
        
        supports = find_support_levels(lows, lookback=90, window=5, max_levels=5)
        
        if len(supports) > 1:
            assert supports == sorted(supports)


class TestFindResistanceLevels:
    """Tests für Resistance-Level-Erkennung"""
    
    def test_finds_swing_highs(self):
        """Test: Findet Swing Highs als Resistance"""
        # Erstelle Daten mit klarem Resistance bei 110
        highs = [100, 102, 105, 110, 108, 105, 102, 100, 102, 105, 110, 108, 105] * 5
        
        resistances = find_resistance_levels(highs, lookback=60, window=3, max_levels=3)
        
        assert len(resistances) > 0
        assert 110 in resistances
    
    def test_returns_max_levels(self):
        """Test: Gibt nur max_levels zurück"""
        highs = list(range(0, 100)) + list(range(100, 0, -1))  # Umgekehrte V-Formation
        
        resistances = find_resistance_levels(highs, lookback=100, window=10, max_levels=2)
        
        assert len(resistances) <= 2
    
    def test_empty_for_insufficient_data(self):
        """Test: Leere Liste bei zu wenig Daten"""
        highs = [100, 101, 102]  # Nur 3 Datenpunkte
        
        resistances = find_resistance_levels(highs, lookback=60, window=20)
        
        assert resistances == []


class TestCalculateFibonacci:
    """Tests für Fibonacci-Berechnung"""
    
    def test_fibonacci_levels(self):
        """Test: Berechnet korrekte Fibonacci-Levels"""
        high = 200.0
        low = 100.0
        
        fibs = calculate_fibonacci(high, low)
        
        # Überprüfe alle Standard-Levels
        assert fibs['0.0%'] == 200.0  # High
        assert fibs['100.0%'] == 100.0  # Low
        assert abs(fibs['50.0%'] - 150.0) < 0.01
        assert abs(fibs['38.2%'] - 161.8) < 0.01
        assert abs(fibs['61.8%'] - 138.2) < 0.01
    
    def test_fibonacci_with_different_range(self):
        """Test: Fibonacci mit anderem Bereich"""
        high = 150.0
        low = 100.0
        diff = 50.0
        
        fibs = calculate_fibonacci(high, low)
        
        # 23.6% Level
        expected_236 = 150.0 - (diff * 0.236)
        assert abs(fibs['23.6%'] - expected_236) < 0.01
        
        # 78.6% Level
        expected_786 = 150.0 - (diff * 0.786)
        assert abs(fibs['78.6%'] - expected_786) < 0.01
    
    def test_fibonacci_returns_all_levels(self):
        """Test: Gibt alle erwarteten Levels zurück"""
        fibs = calculate_fibonacci(100.0, 50.0)
        
        expected_keys = ['0.0%', '23.6%', '38.2%', '50.0%', '61.8%', '78.6%', '100.0%']
        
        for key in expected_keys:
            assert key in fibs


class TestFindPivotPoints:
    """Tests für Pivot-Point-Berechnung"""
    
    def test_pivot_calculation(self):
        """Test: Berechnet korrekten Pivot-Punkt"""
        high = 105.0
        low = 95.0
        close = 100.0
        
        pivots = find_pivot_points(high, low, close)
        
        # Pivot = (H + L + C) / 3
        expected_pivot = (105.0 + 95.0 + 100.0) / 3
        assert abs(pivots['pivot'] - expected_pivot) < 0.01
    
    def test_support_resistance_levels(self):
        """Test: Berechnet S1-S3 und R1-R3"""
        pivots = find_pivot_points(105.0, 95.0, 100.0)
        
        required_keys = ['pivot', 'r1', 'r2', 'r3', 's1', 's2', 's3']
        
        for key in required_keys:
            assert key in pivots
    
    def test_r1_above_pivot(self):
        """Test: R1 ist über Pivot"""
        pivots = find_pivot_points(105.0, 95.0, 100.0)
        
        assert pivots['r1'] > pivots['pivot']
    
    def test_s1_below_pivot(self):
        """Test: S1 ist unter Pivot"""
        pivots = find_pivot_points(105.0, 95.0, 100.0)
        
        assert pivots['s1'] < pivots['pivot']
    
    def test_levels_ordered(self):
        """Test: Levels sind korrekt geordnet"""
        pivots = find_pivot_points(105.0, 95.0, 100.0)
        
        # R3 > R2 > R1 > Pivot > S1 > S2 > S3
        assert pivots['r3'] > pivots['r2'] > pivots['r1'] > pivots['pivot']
        assert pivots['pivot'] > pivots['s1'] > pivots['s2'] > pivots['s3']


class TestPriceNearLevel:
    """Tests für Preis-Nähe-Prüfung"""
    
    def test_price_at_level(self):
        """Test: Preis direkt am Level"""
        assert price_near_level(100.0, 100.0) is True
    
    def test_price_within_tolerance(self):
        """Test: Preis innerhalb Toleranz"""
        # 2% Toleranz als Default
        assert price_near_level(100.0, 101.5, tolerance_pct=2.0) is True
        assert price_near_level(100.0, 98.5, tolerance_pct=2.0) is True
    
    def test_price_outside_tolerance(self):
        """Test: Preis außerhalb Toleranz"""
        assert price_near_level(100.0, 105.0, tolerance_pct=2.0) is False
        assert price_near_level(100.0, 95.0, tolerance_pct=2.0) is False
    
    def test_custom_tolerance(self):
        """Test: Benutzerdefinierte Toleranz"""
        # 5% Toleranz
        assert price_near_level(100.0, 104.0, tolerance_pct=5.0) is True
        assert price_near_level(100.0, 106.0, tolerance_pct=5.0) is False


class TestIntegration:
    """Integrationstests für Support/Resistance"""
    
    def test_support_below_current_price(self):
        """Test: Support-Levels unter aktuellem Preis sind relevant"""
        current_price = 100.0
        
        # Generiere historische Lows
        lows = [95, 90, 92, 88, 91, 89, 93, 90, 94, 91] * 6
        
        supports = find_support_levels(lows, lookback=50, window=3, max_levels=3)
        
        # Alle Supports sollten unter dem aktuellen Preis liegen
        relevant_supports = [s for s in supports if s < current_price]
        assert len(relevant_supports) > 0
    
    def test_fibonacci_for_bull_put_spread(self):
        """Test: Fibonacci-Levels für Bull-Put-Spread-Analyse"""
        # Simuliere 60-Tage Range
        high_60d = 185.0
        low_60d = 165.0
        current_price = 180.0
        
        fibs = calculate_fibonacci(high_60d, low_60d)
        
        # Für Bull-Put-Spread sind 38.2%, 50%, 61.8% relevant
        # Diese sollten unter dem aktuellen Preis liegen
        relevant_fibs = [
            v for k, v in fibs.items() 
            if v < current_price and k in ['38.2%', '50.0%', '61.8%']
        ]
        
        assert len(relevant_fibs) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
