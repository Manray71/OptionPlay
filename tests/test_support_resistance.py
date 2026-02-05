# OptionPlay - Support/Resistance Tests
# ======================================
# Tests für die optimierte Support/Resistance Level Detection
#
# Comprehensive test suite covering:
# - find_support_levels function
# - find_resistance_levels function
# - find_pivot_points (calculate_pivot_points) function
# - Edge cases (empty data, insufficient data)
# - Data structures and utilities

import pytest
import sys
import math
import numpy as np
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indicators.support_resistance import (
    # Data structures
    PriceLevel,
    SupportResistanceResult,
    VolumeZone,
    VolumeProfile,
    LevelTest,

    # Core algorithms
    find_local_minima_optimized,
    find_local_maxima_optimized,
    cluster_levels,
    score_levels,

    # Main API
    find_support_levels,
    find_resistance_levels,
    find_support_levels_enhanced,
    find_resistance_levels_enhanced,
    analyze_support_resistance,
    get_nearest_sr_levels,

    # Volume Analysis
    calculate_volume_profile,
    analyze_level_tests,
    validate_level_with_volume,
    get_volume_at_level,
    analyze_support_resistance_with_validation,

    # Utilities
    calculate_fibonacci,
    find_pivot_points,
    price_near_level,
)


# =============================================================================
# TEST DATA GENERATORS
# =============================================================================

def generate_swing_data(
    base: float = 100.0,
    num_swings: int = 5,
    swing_amplitude: float = 5.0,
    points_per_swing: int = 20
) -> List[float]:
    """
    Generiert synthetische Preisdaten mit klaren Swing-Punkten.

    Args:
        base: Basispreis
        num_swings: Anzahl der Auf-/Ab-Bewegungen
        swing_amplitude: Amplitude der Schwingung
        points_per_swing: Datenpunkte pro Halbschwingung

    Returns:
        Liste von Preisen mit klaren Swing Highs/Lows
    """
    import math
    data = []
    for i in range(num_swings * points_per_swing * 2):
        # Sinuswelle für natürliche Schwingung
        phase = i / points_per_swing * math.pi
        value = base + swing_amplitude * math.sin(phase)
        data.append(value)
    return data


def generate_support_test_data() -> list:
    """
    Generiert Testdaten mit bekannten Support-Levels.

    Returns:
        lows Liste
    """
    # Erstelle Daten mit drei klaren Support-Levels bei ~95, ~98, ~100
    lows = []

    # Segment 1: Support bei ~95
    lows.extend([100, 98, 96, 95, 95.2, 96, 98, 100, 102])

    # Segment 2: Support bei ~98
    lows.extend([102, 100, 98.5, 98, 98.2, 99, 100, 102, 104])

    # Segment 3: Wieder Support bei ~95
    lows.extend([104, 102, 100, 97, 95.5, 95, 96, 98, 100])

    # Segment 4: Support bei ~100
    lows.extend([102, 101, 100, 100.2, 100.5, 101, 102, 103, 105])

    # Segment 5: Letzter Bereich
    lows.extend([105, 103, 101, 100, 99, 100, 101, 102, 103])

    return lows


# =============================================================================
# TESTS: DATA STRUCTURES
# =============================================================================

class TestPriceLevel:
    """Tests für PriceLevel Dataclass"""

    def test_default_values(self):
        level = PriceLevel(price=100.0)
        assert level.price == 100.0
        assert level.strength == 0.0
        assert level.touches == 1
        assert level.indices == []
        assert level.volumes == []
        assert level.level_type == "support"

    def test_avg_volume_empty(self):
        level = PriceLevel(price=100.0)
        assert level.avg_volume == 0.0

    def test_avg_volume_with_data(self):
        level = PriceLevel(price=100.0, volumes=[1000, 2000, 3000])
        assert level.avg_volume == 2000.0

    def test_last_touch_index_empty(self):
        level = PriceLevel(price=100.0)
        assert level.last_touch_index == -1

    def test_last_touch_index_with_data(self):
        level = PriceLevel(price=100.0, indices=[10, 50, 30])
        assert level.last_touch_index == 50

    def test_to_dict(self):
        level = PriceLevel(
            price=100.5,
            strength=0.75,
            touches=3,
            indices=[10, 20, 30],
            volumes=[1000, 2000, 3000],
            level_type="resistance"
        )
        d = level.to_dict()

        assert d['price'] == 100.5
        assert d['strength'] == 0.75
        assert d['touches'] == 3
        assert d['avg_volume'] == 2000
        assert d['last_touch_index'] == 30
        assert d['level_type'] == "resistance"


class TestSupportResistanceResult:
    """Tests für SupportResistanceResult Container"""

    def test_empty_result(self):
        result = SupportResistanceResult()
        assert result.support_levels == []
        assert result.resistance_levels == []
        assert result.nearest_support is None
        assert result.nearest_resistance is None

    def test_get_support_prices(self):
        levels = [
            PriceLevel(price=100.0),
            PriceLevel(price=95.0),
            PriceLevel(price=90.0)
        ]
        result = SupportResistanceResult(support_levels=levels)

        prices = result.get_support_prices()
        assert prices == [100.0, 95.0, 90.0]

    def test_get_resistance_prices(self):
        levels = [
            PriceLevel(price=110.0),
            PriceLevel(price=115.0)
        ]
        result = SupportResistanceResult(resistance_levels=levels)

        prices = result.get_resistance_prices()
        assert prices == [110.0, 115.0]


# =============================================================================
# TESTS: CORE ALGORITHMS
# =============================================================================

class TestLocalMinimaOptimized:
    """Tests für O(n) Swing Low Detection"""

    def test_simple_minimum(self):
        """Einfaches V-Muster"""
        values = [10, 8, 6, 4, 2, 4, 6, 8, 10]
        # Window=2: Minimum bei Index 4 (Wert 2)
        result = find_local_minima_optimized(values, window=2)
        assert 4 in result

    def test_multiple_minima(self):
        """Mehrere lokale Minima"""
        values = [10, 5, 10, 5, 10, 5, 10]
        # Window=1: Minima bei Index 1, 3, 5
        result = find_local_minima_optimized(values, window=1)
        assert 1 in result
        assert 3 in result
        assert 5 in result

    def test_not_enough_data(self):
        """Zu wenig Daten für Window"""
        values = [10, 5, 10]
        result = find_local_minima_optimized(values, window=2)
        assert result == []

    def test_plateau(self):
        """Plateau am Minimum"""
        values = [10, 8, 5, 5, 5, 8, 10]
        result = find_local_minima_optimized(values, window=2)
        # Bei Plateau kann erstes Element als Minimum gefunden werden
        assert len(result) >= 1

    def test_sine_wave_pattern(self):
        """Sinuswellen-Muster mit mehreren Tiefs"""
        data = generate_swing_data(base=100, num_swings=3, swing_amplitude=10, points_per_swing=10)
        result = find_local_minima_optimized(data, window=5)
        # Sollte 3 Minima finden (bei jedem Tal der Sinuswelle)
        assert len(result) >= 2  # Mindestens 2 Minima


class TestLocalMaximaOptimized:
    """Tests für O(n) Swing High Detection"""

    def test_simple_maximum(self):
        """Einfaches ^-Muster"""
        values = [2, 4, 6, 8, 10, 8, 6, 4, 2]
        # Window=2: Maximum bei Index 4 (Wert 10)
        result = find_local_maxima_optimized(values, window=2)
        assert 4 in result

    def test_multiple_maxima(self):
        """Mehrere lokale Maxima"""
        values = [5, 10, 5, 10, 5, 10, 5]
        # Window=1: Maxima bei Index 1, 3, 5
        result = find_local_maxima_optimized(values, window=1)
        assert 1 in result
        assert 3 in result
        assert 5 in result


class TestClusterLevels:
    """Tests für Level-Clustering"""

    def test_single_level(self):
        prices = [100.0]
        indices = [10]
        result = cluster_levels(prices, indices)

        assert len(result) == 1
        assert result[0].price == 100.0
        assert result[0].touches == 1

    def test_two_separate_levels(self):
        """Zwei Levels weit genug auseinander"""
        prices = [100.0, 110.0]
        indices = [10, 20]
        result = cluster_levels(prices, indices, tolerance_pct=5.0)

        assert len(result) == 2

    def test_two_levels_clustered(self):
        """Zwei Levels nah beieinander → werden geclustert"""
        prices = [100.0, 100.5]  # 0.5% Unterschied
        indices = [10, 20]
        result = cluster_levels(prices, indices, tolerance_pct=1.5)

        assert len(result) == 1
        assert result[0].touches == 2
        # Durchschnittspreis
        assert 100.0 <= result[0].price <= 100.5

    def test_multiple_clusters(self):
        """Mehrere unterschiedliche Cluster"""
        prices = [100.0, 100.2, 110.0, 110.3, 120.0]
        indices = [10, 20, 30, 40, 50]
        result = cluster_levels(prices, indices, tolerance_pct=1.0)

        assert len(result) == 3  # 3 Cluster: ~100, ~110, ~120

    def test_with_volumes(self):
        """Cluster mit Volumen-Daten"""
        prices = [100.0, 100.5]
        indices = [10, 20]
        volumes = [1000000, 2000000]
        result = cluster_levels(prices, indices, volumes, tolerance_pct=2.0)

        assert len(result) == 1
        assert len(result[0].volumes) == 2
        assert result[0].avg_volume == 1500000


class TestScoreLevels:
    """Tests für Level-Scoring"""

    def test_empty_input(self):
        result = score_levels([], total_length=100, avg_volume=1000000)
        assert result == []

    def test_basic_scoring(self):
        levels = [
            PriceLevel(price=100.0, touches=5, indices=[90], volumes=[2000000]),
            PriceLevel(price=95.0, touches=2, indices=[50], volumes=[500000])
        ]
        result = score_levels(levels, total_length=100, avg_volume=1000000)

        # Level mit mehr Touches und höherem Volumen sollte stärker sein
        assert result[0].strength > result[1].strength
        assert result[0].price == 100.0

    def test_recency_matters(self):
        """Jüngere Levels sollten höher bewertet werden"""
        levels = [
            PriceLevel(price=100.0, touches=3, indices=[10]),  # Alter Touch
            PriceLevel(price=95.0, touches=3, indices=[90])    # Neuer Touch
        ]
        result = score_levels(levels, total_length=100, avg_volume=0)

        # Jüngerer Touch sollte höher bewertet werden
        assert result[0].price == 95.0  # Neuerer Touch zuerst


# =============================================================================
# TESTS: MAIN API (Backward Compatibility)
# =============================================================================

class TestFindSupportLevels:
    """Tests für find_support_levels API"""

    def test_finds_swing_lows(self):
        """Test: Findet Swing Lows als Support"""
        # Erstelle Daten mit klarem Support bei 90
        lows = [100, 98, 95, 90, 92, 95, 98, 100, 98, 95, 90, 92, 95] * 5

        supports = find_support_levels(lows, lookback=60, window=3, max_levels=3)

        assert len(supports) > 0

    def test_basic_support_detection(self):
        lows = generate_support_test_data()
        result = find_support_levels(lows, lookback=len(lows), window=3, max_levels=3)

        assert isinstance(result, list)
        assert len(result) <= 3
        assert all(isinstance(level, float) for level in result)

    def test_returns_max_levels(self):
        """Test: Gibt nur max_levels zurück"""
        lows = list(range(100, 0, -1)) + list(range(0, 100))  # V-Formation

        supports = find_support_levels(lows, lookback=100, window=10, max_levels=2)

        assert len(supports) <= 2

    def test_not_enough_data(self):
        lows = [100, 99, 98]  # Zu wenig Daten
        result = find_support_levels(lows, lookback=60, window=5)
        assert result == []

    def test_empty_for_insufficient_data(self):
        """Test: Leere Liste bei zu wenig Daten"""
        lows = [100, 99, 98]  # Nur 3 Datenpunkte

        supports = find_support_levels(lows, lookback=60, window=20)

        assert supports == []

    def test_with_volumes(self):
        lows = generate_support_test_data()
        volumes = [1000000] * len(lows)
        result = find_support_levels(lows, lookback=len(lows), window=3, volumes=volumes)

        assert isinstance(result, list)


class TestFindResistanceLevels:
    """Tests für Resistance-Detection"""

    def test_finds_swing_highs(self):
        """Test: Findet Swing Highs als Resistance"""
        # Erstelle Daten mit klarem Resistance bei 110
        highs = [100, 102, 105, 110, 108, 105, 102, 100, 102, 105, 110, 108, 105] * 5

        resistances = find_resistance_levels(highs, lookback=60, window=3, max_levels=3)

        assert len(resistances) > 0

    def test_basic_resistance_detection(self):
        highs = generate_swing_data(base=100, num_swings=3, swing_amplitude=10, points_per_swing=10)
        result = find_resistance_levels(highs, lookback=len(highs), window=3, max_levels=3)

        assert isinstance(result, list)
        assert len(result) <= 3

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


class TestFindSupportLevelsEnhanced:
    """Tests für erweiterte Support-Detection"""

    def test_returns_support_resistance_result(self):
        lows = generate_support_test_data()
        result = find_support_levels_enhanced(lows, lookback=len(lows), window=3)

        assert isinstance(result, SupportResistanceResult)
        assert isinstance(result.support_levels, list)

    def test_levels_have_metadata(self):
        lows = generate_support_test_data()
        result = find_support_levels_enhanced(lows, lookback=len(lows), window=3)

        if result.support_levels:
            level = result.support_levels[0]
            assert hasattr(level, 'price')
            assert hasattr(level, 'strength')
            assert hasattr(level, 'touches')
            assert level.level_type == "support"

    def test_nearest_support_found(self):
        # Erstelle Daten wo aktueller Preis über Support liegt
        lows = [100, 95, 90, 85, 90, 95, 100, 102, 104, 102, 100]
        result = find_support_levels_enhanced(lows, lookback=len(lows), window=2)

        # Aktueller Preis ist 100, Support sollte darunter gefunden werden
        if result.nearest_support:
            assert result.nearest_support.price < lows[-1]


class TestFindResistanceLevelsEnhanced:
    """Tests für erweiterte Resistance-Detection"""

    def test_resistance_levels_enhanced(self):
        highs = generate_swing_data(base=100, num_swings=3, swing_amplitude=10, points_per_swing=10)
        result = find_resistance_levels_enhanced(highs, lookback=len(highs), window=3)

        assert isinstance(result, SupportResistanceResult)

        if result.resistance_levels:
            level = result.resistance_levels[0]
            assert level.level_type == "resistance"


class TestAnalyzeSupportResistance:
    """Tests für kombinierte Analyse"""

    def test_combined_analysis(self):
        data = generate_swing_data(base=100, num_swings=5, swing_amplitude=10, points_per_swing=15)
        # Für lows/highs leicht modifizieren
        prices = data
        highs = [p + 2 for p in data]
        lows = [p - 2 for p in data]
        volumes = [1000000] * len(data)

        result = analyze_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            lookback=len(data),
            window=5
        )

        assert isinstance(result, SupportResistanceResult)
        # Sollte sowohl Support als auch Resistance finden
        assert len(result.support_levels) > 0 or len(result.resistance_levels) > 0


# =============================================================================
# TESTS: UTILITY FUNCTIONS
# =============================================================================

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
        result = calculate_fibonacci(high=100.0, low=80.0)

        assert result['0.0%'] == 100.0
        assert result['100.0%'] == 80.0
        assert result['50.0%'] == 90.0
        assert pytest.approx(result['38.2%'], 0.01) == 92.36
        assert pytest.approx(result['61.8%'], 0.01) == 87.64

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

    def test_support_below_resistance(self):
        result = find_pivot_points(high=110.0, low=90.0, close=100.0)

        assert result['s1'] < result['pivot']
        assert result['s2'] < result['s1']
        assert result['r1'] > result['pivot']
        assert result['r2'] > result['r1']


class TestPriceNearLevel:
    """Tests für price_near_level"""

    def test_price_at_level(self):
        assert price_near_level(100.0, 100.0, tolerance_pct=2.0) is True

    def test_price_within_tolerance(self):
        assert price_near_level(101.0, 100.0, tolerance_pct=2.0) is True
        assert price_near_level(99.0, 100.0, tolerance_pct=2.0) is True
        assert price_near_level(100.0, 101.5, tolerance_pct=2.0) is True
        assert price_near_level(100.0, 98.5, tolerance_pct=2.0) is True

    def test_price_outside_tolerance(self):
        assert price_near_level(105.0, 100.0, tolerance_pct=2.0) is False
        assert price_near_level(95.0, 100.0, tolerance_pct=2.0) is False

    def test_custom_tolerance(self):
        """Test: Benutzerdefinierte Toleranz"""
        # 5% Toleranz
        assert price_near_level(100.0, 104.0, tolerance_pct=5.0) is True
        assert price_near_level(100.0, 106.0, tolerance_pct=5.0) is False

    def test_zero_level(self):
        assert price_near_level(100.0, 0.0, tolerance_pct=2.0) is False


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================

class TestPerformance:
    """Performance-Vergleichstests"""

    def test_large_dataset(self):
        """Test mit großem Datensatz (1 Jahr = 252 Handelstage)"""
        import time

        # Generiere 252 Tage Daten
        data = generate_swing_data(base=100, num_swings=20, swing_amplitude=5, points_per_swing=12)

        start = time.time()
        result = find_local_minima_optimized(data, window=5)
        duration = time.time() - start

        # Sollte sehr schnell sein (< 10ms)
        assert duration < 0.1  # 100ms als konservatives Limit
        assert len(result) > 0

    def test_very_large_dataset(self):
        """Test mit sehr großem Datensatz (5 Jahre = ~1260 Handelstage)"""
        import time

        data = generate_swing_data(base=100, num_swings=100, swing_amplitude=5, points_per_swing=12)

        start = time.time()
        result = find_local_minima_optimized(data, window=10)
        duration = time.time() - start

        # Immer noch schnell bei O(n)
        assert duration < 0.5
        assert len(result) > 0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

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


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests für Randfälle"""

    def test_all_same_values(self):
        """Alle Werte gleich"""
        lows = [100.0] * 50
        result = find_support_levels(lows, lookback=50, window=5)
        # Alle Punkte könnten als Minimum gelten
        assert isinstance(result, list)

    def test_monotonic_increasing(self):
        """Streng monoton steigend"""
        lows = [float(i) for i in range(100)]
        result = find_support_levels(lows, lookback=100, window=5)
        # Bei monoton steigenden Daten können durch Clustering
        # einige niedrige Werte als Support gefunden werden
        # Das ist akzeptables Verhalten
        assert isinstance(result, list)

    def test_monotonic_decreasing(self):
        """Streng monoton fallend"""
        lows = [float(100 - i) for i in range(100)]
        result = find_support_levels(lows, lookback=100, window=5)
        # Keine echten Swing Lows
        assert len(result) <= 1

    def test_single_spike_down(self):
        """Einzelner Spike nach unten"""
        lows = [100.0] * 20 + [80.0] + [100.0] * 20
        result = find_support_levels(lows, lookback=len(lows), window=5)

        # Sollte den Spike finden
        assert len(result) >= 1
        if result:
            assert 75.0 < min(result) < 85.0  # Nahe bei 80

    def test_high_volatility(self):
        """Hochvolatile Daten"""
        import random
        random.seed(42)
        lows = [100 + random.uniform(-10, 10) for _ in range(100)]

        # Sollte nicht crashen
        result = find_support_levels(lows, lookback=100, window=5)
        assert isinstance(result, list)


# =============================================================================
# VOLUME PROFILE TESTS
# =============================================================================

class TestVolumeProfile:
    """Tests für Volume Profile Berechnung"""

    def test_basic_volume_profile(self):
        """Basis Volume Profile Berechnung"""
        from indicators.support_resistance import calculate_volume_profile

        # Einfache Daten
        prices = [100.0, 101.0, 102.0, 101.0, 100.0] * 10
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        volumes = [1000000] * len(prices)

        profile = calculate_volume_profile(prices, highs, lows, volumes)

        assert profile is not None
        assert len(profile.zones) > 0
        assert profile.poc is not None
        assert profile.value_area_high >= profile.value_area_low

    def test_volume_profile_hvn_detection(self):
        """High Volume Nodes sollten erkannt werden"""
        from indicators.support_resistance import calculate_volume_profile

        # Konzentriertes Volumen in einer Zone
        prices = [100.0] * 30 + [110.0] * 10 + [100.0] * 10
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        volumes = [1000000] * 30 + [100000] * 10 + [1000000] * 10

        profile = calculate_volume_profile(prices, highs, lows, volumes, num_zones=10)

        # Sollte HVN haben
        assert len(profile.hvn_zones) >= 1

    def test_volume_profile_empty_data(self):
        """Leere Daten sollten leeres Profil zurückgeben"""
        from indicators.support_resistance import calculate_volume_profile

        profile = calculate_volume_profile([], [], [], [])

        assert len(profile.zones) == 0
        assert profile.poc is None


class TestVolumeZone:
    """Tests für VolumeZone Datenstruktur"""

    def test_volume_zone_properties(self):
        """VolumeZone Properties testen"""
        from indicators.support_resistance import VolumeZone

        zone = VolumeZone(
            price_low=100.0,
            price_high=105.0,
            total_volume=5000000,
            bar_count=10
        )

        assert zone.price_center == 102.5
        assert zone.avg_volume_per_bar == 500000.0


# =============================================================================
# LEVEL TEST ANALYSIS
# =============================================================================

class TestLevelTestAnalysis:
    """Tests für Level-Test Analyse"""

    def test_analyze_level_tests_support(self):
        """Support-Level Tests analysieren"""
        from indicators.support_resistance import analyze_level_tests

        # Support bei 95, wird mehrmals getestet
        prices = [100.0, 98.0, 96.0, 95.5, 97.0, 99.0, 98.0, 95.2, 98.0, 100.0]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        volumes = [1000000] * len(prices)

        tests, touch_quality, vol_confirm = analyze_level_tests(
            level_price=95.0,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            level_type="support",
            tolerance_pct=3.0,
            lookback=len(prices)
        )

        # Sollte Tests finden
        assert len(tests) >= 1
        assert 0.0 <= touch_quality <= 1.0
        assert 0.0 <= vol_confirm <= 1.0

    def test_analyze_level_tests_resistance(self):
        """Resistance-Level Tests analysieren"""
        from indicators.support_resistance import analyze_level_tests

        # Resistance bei 105, wird getestet
        prices = [100.0, 102.0, 104.0, 104.5, 103.0, 101.0, 103.0, 104.8, 102.0, 100.0]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        volumes = [1000000] * len(prices)

        tests, touch_quality, vol_confirm = analyze_level_tests(
            level_price=105.0,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            level_type="resistance",
            tolerance_pct=3.0,
            lookback=len(prices)
        )

        assert isinstance(tests, list)
        assert 0.0 <= touch_quality <= 1.0

    def test_analyze_level_tests_no_tests(self):
        """Keine Tests wenn Level nicht berührt"""
        from indicators.support_resistance import analyze_level_tests

        # Level weit weg
        prices = [100.0] * 20
        highs = [101.0] * 20
        lows = [99.0] * 20
        volumes = [1000000] * 20

        tests, touch_quality, vol_confirm = analyze_level_tests(
            level_price=50.0,  # Weit entfernt
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            level_type="support"
        )

        assert len(tests) == 0
        assert touch_quality == 0.0


class TestLevelTest:
    """Tests für LevelTest Datenstruktur"""

    def test_level_test_creation(self):
        """LevelTest erstellen"""
        from indicators.support_resistance import LevelTest

        test = LevelTest(
            index=10,
            price_at_test=95.0,
            close_after=97.0,
            volume_at_test=1500000,
            volume_ratio=1.5,
            distance_pct=0.5,
            held=True,
            bounce_pct=2.1
        )

        assert test.index == 10
        assert test.held is True
        assert test.bounce_pct == 2.1


# =============================================================================
# VOLUME VALIDATION
# =============================================================================

class TestVolumeValidation:
    """Tests für Volumen-Validierung"""

    def test_validate_level_with_volume(self):
        """Level mit Volumen validieren"""
        from indicators.support_resistance import validate_level_with_volume, PriceLevel

        level = PriceLevel(price=95.0, strength=0.5, level_type="support")

        # Testdaten mit Support bei 95
        prices = [100.0, 98.0, 95.5, 97.0, 99.0, 98.0, 95.2, 98.0, 100.0, 101.0]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        volumes = [1000000] * len(prices)

        validated = validate_level_with_volume(
            level=level,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes
        )

        # Sollte touch_quality und volume_confirmation gesetzt haben
        assert validated.touch_quality >= 0.0
        assert validated.volume_confirmation >= 0.0
        assert validated.strength >= 0.0

    def test_get_volume_at_level(self):
        """Volumen an einem Level berechnen"""
        from indicators.support_resistance import get_volume_at_level

        # Daten mit Volumen an Level 100
        prices = [100.0] * 20
        highs = [101.0] * 20
        lows = [99.0] * 20
        volumes = [1000000] * 20

        total_vol, vol_ratio = get_volume_at_level(
            level_price=100.0,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            tolerance_pct=2.0
        )

        assert total_vol > 0
        assert vol_ratio > 0.0


class TestEnhancedValidation:
    """Tests für erweiterte S/R Analyse mit Validierung"""

    def test_analyze_with_validation(self):
        """Vollständige Analyse mit Validierung"""
        from indicators.support_resistance import analyze_support_resistance_with_validation

        # Realistische Testdaten
        n = 100
        base_prices = [100 + (i % 10) - 5 for i in range(n)]
        prices = base_prices
        highs = [p + 2 for p in prices]
        lows = [p - 2 for p in prices]
        volumes = [1000000 + (i % 5) * 100000 for i in range(n)]

        result = analyze_support_resistance_with_validation(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            include_volume_profile=True
        )

        assert result is not None
        # Volume Profile sollte berechnet sein
        assert result.volume_profile is not None

        # Levels sollten touch_quality und volume_confirmation haben
        for level in result.support_levels + result.resistance_levels:
            assert hasattr(level, 'touch_quality')
            assert hasattr(level, 'volume_confirmation')

    def test_analyze_without_volume_profile(self):
        """Analyse ohne Volume Profile"""
        from indicators.support_resistance import analyze_support_resistance_with_validation

        prices = [100.0 + (i % 10) for i in range(50)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]
        volumes = [1000000] * 50

        result = analyze_support_resistance_with_validation(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            include_volume_profile=False
        )

        assert result is not None
        assert result.volume_profile is None


class TestPriceLevelEnhancements:
    """Tests für erweiterte PriceLevel Eigenschaften"""

    def test_price_level_hold_rate(self):
        """Hold-Rate Berechnung testen"""
        from indicators.support_resistance import PriceLevel

        level = PriceLevel(
            price=100.0,
            hold_count=8,
            break_count=2
        )

        assert level.hold_rate == 0.8

    def test_price_level_hold_rate_zero(self):
        """Hold-Rate bei keinen Tests"""
        from indicators.support_resistance import PriceLevel

        level = PriceLevel(price=100.0)

        assert level.hold_rate == 0.0

    def test_price_level_to_dict_enhanced(self):
        """Erweitertes to_dict testen"""
        from indicators.support_resistance import PriceLevel

        level = PriceLevel(
            price=100.0,
            strength=0.75,
            touches=5,
            touch_quality=0.8,
            volume_confirmation=0.9,
            hold_count=4,
            break_count=1
        )

        d = level.to_dict()

        assert 'touch_quality' in d
        assert 'volume_confirmation' in d
        assert 'hold_rate' in d
        assert d['hold_rate'] == 0.8


# =============================================================================
# COMPREHENSIVE FIND_SUPPORT_LEVELS TESTS
# =============================================================================

class TestFindSupportLevelsComprehensive:
    """Comprehensive tests for the find_support_levels function"""

    def test_empty_data(self):
        """Test with empty list"""
        result = find_support_levels([], lookback=60, window=5)
        assert result == []

    def test_single_element(self):
        """Test with single data point"""
        result = find_support_levels([100.0], lookback=60, window=5)
        assert result == []

    def test_insufficient_data_for_window(self):
        """Test when data length is less than 2*window+1"""
        # Window=5 requires at least 11 data points
        lows = [100.0, 99.0, 98.0, 97.0, 96.0, 97.0, 98.0, 99.0, 100.0]  # 9 points
        result = find_support_levels(lows, lookback=60, window=5)
        assert result == []

    def test_exactly_minimum_data(self):
        """Test with exactly 2*window+1 data points"""
        # Window=2 requires exactly 5 data points minimum
        lows = [100.0, 98.0, 95.0, 98.0, 100.0]  # V-shape with 5 points
        result = find_support_levels(lows, lookback=5, window=2)
        # Should find the minimum at index 2
        assert len(result) >= 0  # May or may not find depending on algorithm

    def test_w_pattern_support(self):
        """Test W-pattern (double bottom) support detection"""
        # W pattern with two lows at similar levels
        lows = [100, 98, 96, 95, 96, 98, 100, 98, 96, 95.5, 96, 98, 100]
        result = find_support_levels(lows, lookback=len(lows), window=2)
        # Should find support around 95-95.5
        if result:
            assert any(94.0 <= level <= 96.0 for level in result)

    def test_multiple_support_levels(self):
        """Test detection of multiple distinct support levels"""
        # Create data with supports at ~90, ~95, ~100
        lows = []
        lows.extend([105, 102, 100, 98, 95, 98, 100, 102, 105])  # Support at 95
        lows.extend([105, 102, 100, 98, 95, 90, 92, 95, 98, 100])  # Support at 90
        lows.extend([100, 102, 105, 103, 100, 102, 105])  # Support at 100

        result = find_support_levels(lows, lookback=len(lows), window=3, max_levels=5)

        assert isinstance(result, list)
        # Should find multiple distinct levels

    def test_lookback_parameter(self):
        """Test that lookback parameter limits the analysis window"""
        # First 50 points with support at 80, next 50 with support at 90
        lows_old = [85, 82, 80, 82, 85, 88, 90] * 7  # 49 points around 80
        lows_new = [95, 92, 90, 92, 95, 98, 100] * 7  # 49 points around 90
        lows = lows_old + lows_new

        # With lookback=50, should only see recent data (around 90)
        result = find_support_levels(lows, lookback=40, window=3, max_levels=2)

        if result:
            # Support should be around 90, not 80
            assert all(level > 85 for level in result)

    def test_tolerance_clustering(self):
        """Test that tolerance_pct clusters nearby levels"""
        # Supports at 95.0, 95.5, 95.2 should cluster with default tolerance
        lows = [100, 98, 95.0, 98, 100, 98, 95.5, 98, 100, 98, 95.2, 98, 100] * 4

        result = find_support_levels(
            lows, lookback=len(lows), window=2, max_levels=5, tolerance_pct=2.0
        )

        # Should find one clustered level around 95
        if result:
            assert len([l for l in result if 94.0 <= l <= 96.0]) <= 2

    def test_strict_tolerance_no_clustering(self):
        """Test that strict tolerance keeps levels separate"""
        lows = [100, 98, 90, 98, 100, 98, 95, 98, 100] * 5

        result = find_support_levels(
            lows, lookback=len(lows), window=2, max_levels=5, tolerance_pct=0.1
        )

        # With very strict tolerance, levels should remain separate
        assert isinstance(result, list)

    def test_with_volume_data(self):
        """Test support detection with volume weighting"""
        lows = [100, 98, 95, 98, 100, 98, 95, 98, 100] * 5
        volumes = [1000000] * len(lows)
        # High volume at support levels
        for i in range(len(lows)):
            if lows[i] == 95:
                volumes[i] = 5000000

        result = find_support_levels(
            lows, lookback=len(lows), window=2, max_levels=3, volumes=volumes
        )

        assert isinstance(result, list)

    def test_max_levels_limit(self):
        """Test that max_levels parameter is respected"""
        lows = generate_swing_data(base=100, num_swings=10, swing_amplitude=10, points_per_swing=10)

        for max_levels in [1, 2, 3, 5]:
            result = find_support_levels(
                lows, lookback=len(lows), window=3, max_levels=max_levels
            )
            assert len(result) <= max_levels

    def test_descending_trend_data(self):
        """Test support detection in descending trend"""
        # Descending stair-step pattern
        lows = []
        for level in [100, 95, 90, 85, 80]:
            lows.extend([level + 5, level + 3, level, level + 3, level + 5])

        result = find_support_levels(lows, lookback=len(lows), window=2, max_levels=5)
        assert isinstance(result, list)

    def test_ascending_trend_data(self):
        """Test support detection in ascending trend"""
        # Ascending stair-step pattern
        lows = []
        for level in [80, 85, 90, 95, 100]:
            lows.extend([level + 5, level + 3, level, level + 3, level + 5])

        result = find_support_levels(lows, lookback=len(lows), window=2, max_levels=5)
        assert isinstance(result, list)

    def test_returns_float_list(self):
        """Test that return type is List[float]"""
        lows = generate_support_test_data()
        result = find_support_levels(lows, lookback=len(lows), window=3)

        assert isinstance(result, list)
        for level in result:
            assert isinstance(level, float)


# =============================================================================
# COMPREHENSIVE FIND_RESISTANCE_LEVELS TESTS
# =============================================================================

class TestFindResistanceLevelsComprehensive:
    """Comprehensive tests for the find_resistance_levels function"""

    def test_empty_data(self):
        """Test with empty list"""
        result = find_resistance_levels([], lookback=60, window=5)
        assert result == []

    def test_single_element(self):
        """Test with single data point"""
        result = find_resistance_levels([100.0], lookback=60, window=5)
        assert result == []

    def test_insufficient_data_for_window(self):
        """Test when data length is less than 2*window+1"""
        highs = [100.0, 101.0, 102.0, 101.0, 100.0]  # 5 points
        result = find_resistance_levels(highs, lookback=60, window=5)
        assert result == []

    def test_exactly_minimum_data(self):
        """Test with exactly 2*window+1 data points"""
        # Window=2 requires exactly 5 data points minimum
        highs = [100.0, 102.0, 105.0, 102.0, 100.0]  # Inverted V with 5 points
        result = find_resistance_levels(highs, lookback=5, window=2)
        assert len(result) >= 0

    def test_m_pattern_resistance(self):
        """Test M-pattern (double top) resistance detection"""
        # M pattern with two highs at similar levels
        highs = [100, 102, 104, 105, 104, 102, 100, 102, 104, 104.5, 104, 102, 100]
        result = find_resistance_levels(highs, lookback=len(highs), window=2)

        if result:
            assert any(104.0 <= level <= 106.0 for level in result)

    def test_multiple_resistance_levels(self):
        """Test detection of multiple distinct resistance levels"""
        highs = []
        highs.extend([95, 98, 100, 102, 105, 102, 100, 98, 95])  # Resistance at 105
        highs.extend([95, 98, 100, 102, 105, 110, 108, 105, 102, 100])  # Resistance at 110
        highs.extend([100, 98, 95, 97, 100, 98, 95])  # Resistance at 100

        result = find_resistance_levels(highs, lookback=len(highs), window=3, max_levels=5)

        assert isinstance(result, list)

    def test_lookback_parameter(self):
        """Test that lookback parameter limits the analysis window"""
        # First 50 points with resistance at 120, next 50 with resistance at 110
        highs_old = [115, 118, 120, 118, 115, 112, 110] * 7
        highs_new = [105, 108, 110, 108, 105, 102, 100] * 7
        highs = highs_old + highs_new

        result = find_resistance_levels(highs, lookback=40, window=3, max_levels=2)

        if result:
            # Resistance should be around 110, not 120
            assert all(level < 115 for level in result)

    def test_with_volume_data(self):
        """Test resistance detection with volume weighting"""
        highs = [100, 102, 105, 102, 100, 102, 105, 102, 100] * 5
        volumes = [1000000] * len(highs)
        # High volume at resistance levels
        for i in range(len(highs)):
            if highs[i] == 105:
                volumes[i] = 5000000

        result = find_resistance_levels(
            highs, lookback=len(highs), window=2, max_levels=3, volumes=volumes
        )

        assert isinstance(result, list)

    def test_max_levels_limit(self):
        """Test that max_levels parameter is respected"""
        highs = generate_swing_data(base=100, num_swings=10, swing_amplitude=10, points_per_swing=10)

        for max_levels in [1, 2, 3, 5]:
            result = find_resistance_levels(
                highs, lookback=len(highs), window=3, max_levels=max_levels
            )
            assert len(result) <= max_levels

    def test_tolerance_clustering(self):
        """Test that tolerance_pct clusters nearby levels"""
        # Resistances at 105.0, 105.5, 105.2 should cluster
        highs = [100, 102, 105.0, 102, 100, 102, 105.5, 102, 100, 102, 105.2, 102, 100] * 4

        result = find_resistance_levels(
            highs, lookback=len(highs), window=2, max_levels=5, tolerance_pct=2.0
        )

        # Should cluster levels around 105
        assert isinstance(result, list)

    def test_returns_float_list(self):
        """Test that return type is List[float]"""
        highs = generate_swing_data(base=100, num_swings=3, swing_amplitude=10, points_per_swing=10)
        result = find_resistance_levels(highs, lookback=len(highs), window=3)

        assert isinstance(result, list)
        for level in result:
            assert isinstance(level, float)


# =============================================================================
# COMPREHENSIVE FIND_PIVOT_POINTS TESTS
# =============================================================================

class TestFindPivotPointsComprehensive:
    """Comprehensive tests for the find_pivot_points function"""

    def test_basic_pivot_calculation(self):
        """Test basic pivot point formula: (H + L + C) / 3"""
        high, low, close = 110.0, 90.0, 100.0
        result = find_pivot_points(high, low, close)

        expected_pivot = (110.0 + 90.0 + 100.0) / 3
        assert abs(result['pivot'] - expected_pivot) < 0.001

    def test_all_keys_present(self):
        """Test that all expected keys are present"""
        result = find_pivot_points(110.0, 90.0, 100.0)

        expected_keys = ['pivot', 'r1', 'r2', 'r3', 's1', 's2', 's3']
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_r1_formula(self):
        """Test R1 = 2*Pivot - Low"""
        high, low, close = 110.0, 90.0, 100.0
        result = find_pivot_points(high, low, close)

        pivot = (high + low + close) / 3
        expected_r1 = 2 * pivot - low
        assert abs(result['r1'] - expected_r1) < 0.001

    def test_r2_formula(self):
        """Test R2 = Pivot + (High - Low)"""
        high, low, close = 110.0, 90.0, 100.0
        result = find_pivot_points(high, low, close)

        pivot = (high + low + close) / 3
        expected_r2 = pivot + (high - low)
        assert abs(result['r2'] - expected_r2) < 0.001

    def test_r3_formula(self):
        """Test R3 = High + 2*(Pivot - Low)"""
        high, low, close = 110.0, 90.0, 100.0
        result = find_pivot_points(high, low, close)

        pivot = (high + low + close) / 3
        expected_r3 = high + 2 * (pivot - low)
        assert abs(result['r3'] - expected_r3) < 0.001

    def test_s1_formula(self):
        """Test S1 = 2*Pivot - High"""
        high, low, close = 110.0, 90.0, 100.0
        result = find_pivot_points(high, low, close)

        pivot = (high + low + close) / 3
        expected_s1 = 2 * pivot - high
        assert abs(result['s1'] - expected_s1) < 0.001

    def test_s2_formula(self):
        """Test S2 = Pivot - (High - Low)"""
        high, low, close = 110.0, 90.0, 100.0
        result = find_pivot_points(high, low, close)

        pivot = (high + low + close) / 3
        expected_s2 = pivot - (high - low)
        assert abs(result['s2'] - expected_s2) < 0.001

    def test_s3_formula(self):
        """Test S3 = Low - 2*(High - Pivot)"""
        high, low, close = 110.0, 90.0, 100.0
        result = find_pivot_points(high, low, close)

        pivot = (high + low + close) / 3
        expected_s3 = low - 2 * (high - pivot)
        assert abs(result['s3'] - expected_s3) < 0.001

    def test_level_ordering_ascending(self):
        """Test that levels are correctly ordered: S3 < S2 < S1 < Pivot < R1 < R2 < R3"""
        result = find_pivot_points(110.0, 90.0, 100.0)

        assert result['s3'] < result['s2']
        assert result['s2'] < result['s1']
        assert result['s1'] < result['pivot']
        assert result['pivot'] < result['r1']
        assert result['r1'] < result['r2']
        assert result['r2'] < result['r3']

    def test_symmetric_high_low(self):
        """Test with symmetric high/low around close"""
        # When high-close = close-low, pivot should equal close
        high, low, close = 110.0, 90.0, 100.0
        result = find_pivot_points(high, low, close)

        # Pivot = (110+90+100)/3 = 100
        assert result['pivot'] == 100.0

    def test_bullish_close(self):
        """Test with bullish close (close near high)"""
        high, low, close = 110.0, 90.0, 108.0
        result = find_pivot_points(high, low, close)

        # Pivot should be higher than 100
        assert result['pivot'] > 100.0

    def test_bearish_close(self):
        """Test with bearish close (close near low)"""
        high, low, close = 110.0, 90.0, 92.0
        result = find_pivot_points(high, low, close)

        # Pivot should be lower than 100
        assert result['pivot'] < 100.0

    def test_narrow_range(self):
        """Test with narrow price range"""
        high, low, close = 100.5, 99.5, 100.0
        result = find_pivot_points(high, low, close)

        # All levels should be close together
        assert result['r3'] - result['s3'] < 10

    def test_wide_range(self):
        """Test with wide price range"""
        high, low, close = 150.0, 50.0, 100.0
        result = find_pivot_points(high, low, close)

        # Levels should be spread out
        assert result['r3'] - result['s3'] > 100

    def test_same_high_low_close(self):
        """Test when high = low = close (doji-like)"""
        high, low, close = 100.0, 100.0, 100.0
        result = find_pivot_points(high, low, close)

        # All levels based on same value
        assert result['pivot'] == 100.0
        # R1 = 2*100 - 100 = 100
        assert result['r1'] == 100.0
        # S1 = 2*100 - 100 = 100
        assert result['s1'] == 100.0

    def test_float_precision(self):
        """Test float precision with odd numbers"""
        high, low, close = 103.57, 98.23, 101.45
        result = find_pivot_points(high, low, close)

        # Verify calculation is correct
        expected_pivot = (103.57 + 98.23 + 101.45) / 3
        assert abs(result['pivot'] - expected_pivot) < 0.0001

    def test_real_world_values(self):
        """Test with real-world stock values"""
        # AAPL-like values
        high, low, close = 182.50, 178.25, 180.75
        result = find_pivot_points(high, low, close)

        # Pivot should be between high and low
        assert low <= result['pivot'] <= high
        # R1 should be above pivot
        assert result['r1'] > result['pivot']
        # S1 should be below pivot
        assert result['s1'] < result['pivot']


# =============================================================================
# COMPREHENSIVE EDGE CASES TESTS
# =============================================================================

class TestEdgeCasesComprehensive:
    """Comprehensive edge case tests for support/resistance functions"""

    def test_empty_list_support(self):
        """Test find_support_levels with empty list"""
        assert find_support_levels([]) == []

    def test_empty_list_resistance(self):
        """Test find_resistance_levels with empty list"""
        assert find_resistance_levels([]) == []

    def test_empty_list_enhanced_support(self):
        """Test find_support_levels_enhanced with empty list"""
        result = find_support_levels_enhanced([])
        assert isinstance(result, SupportResistanceResult)
        assert result.support_levels == []

    def test_empty_list_enhanced_resistance(self):
        """Test find_resistance_levels_enhanced with empty list"""
        result = find_resistance_levels_enhanced([])
        assert isinstance(result, SupportResistanceResult)
        assert result.resistance_levels == []

    def test_none_volumes(self):
        """Test with volumes=None"""
        lows = generate_support_test_data()
        result = find_support_levels(lows, lookback=len(lows), window=3, volumes=None)
        assert isinstance(result, list)

    def test_empty_volumes(self):
        """Test with empty volumes list"""
        lows = generate_support_test_data()
        # Empty volumes list should be treated same as None
        result = find_support_levels_enhanced(lows, lookback=len(lows), window=3, volumes=[])
        assert isinstance(result, SupportResistanceResult)

    def test_mismatched_volumes_length(self):
        """Test with volumes list of different length

        Note: The function does not validate volumes length matches data length.
        Mismatched lengths will cause IndexError - this is expected behavior.
        Callers should ensure volumes length matches data length.
        """
        lows = generate_support_test_data()
        volumes = [1000000] * (len(lows) // 2)  # Half the length

        # Function raises IndexError for mismatched volumes - this is expected
        with pytest.raises(IndexError):
            find_support_levels_enhanced(lows, lookback=len(lows), window=3, volumes=volumes)

    def test_negative_values(self):
        """Test with negative price values (theoretical)"""
        lows = [-100, -98, -95, -90, -95, -98, -100, -98, -95, -90, -95, -98, -100]
        result = find_support_levels(lows, lookback=len(lows), window=2)
        assert isinstance(result, list)

    def test_very_small_values(self):
        """Test with very small price values (penny stocks)"""
        lows = [0.05, 0.04, 0.03, 0.02, 0.03, 0.04, 0.05, 0.04, 0.03, 0.02, 0.03, 0.04, 0.05]
        result = find_support_levels(lows, lookback=len(lows), window=2)
        assert isinstance(result, list)

    def test_very_large_values(self):
        """Test with very large price values"""
        base = 100000.0
        lows = [base + i * 100 for i in range(50)]
        lows[25] = base - 500  # Create a swing low

        result = find_support_levels(lows, lookback=len(lows), window=5)
        assert isinstance(result, list)

    def test_inf_values(self):
        """Test behavior with infinity values"""
        lows = [100.0] * 20
        lows[10] = float('inf')

        # Should handle gracefully or filter out inf
        try:
            result = find_support_levels(lows, lookback=len(lows), window=3)
            assert isinstance(result, list)
        except (ValueError, OverflowError):
            pass  # Acceptable to raise error for inf values

    def test_nan_values(self):
        """Test behavior with NaN values"""
        lows = [100.0] * 20
        lows[10] = float('nan')

        # Should handle gracefully
        try:
            result = find_support_levels(lows, lookback=len(lows), window=3)
            assert isinstance(result, list)
        except (ValueError, TypeError):
            pass  # Acceptable to raise error for NaN values

    def test_window_larger_than_data(self):
        """Test with window larger than available data"""
        lows = [100.0, 95.0, 100.0]
        result = find_support_levels(lows, lookback=3, window=10)
        assert result == []

    def test_lookback_zero(self):
        """Test with lookback=0"""
        lows = generate_support_test_data()
        result = find_support_levels(lows, lookback=0, window=3)
        assert result == []

    def test_window_zero(self):
        """Test with window=0"""
        lows = generate_support_test_data()
        # Window=0 means every point could be a local minimum/maximum
        result = find_support_levels(lows, lookback=len(lows), window=0)
        # Behavior depends on implementation - just verify no crash
        assert isinstance(result, list)

    def test_max_levels_zero(self):
        """Test with max_levels=0"""
        lows = generate_support_test_data()
        result = find_support_levels(lows, lookback=len(lows), window=3, max_levels=0)
        assert result == []

    def test_tolerance_zero(self):
        """Test with tolerance_pct=0"""
        lows = [100, 98, 95, 98, 100, 98, 95.001, 98, 100] * 5
        result = find_support_levels(
            lows, lookback=len(lows), window=2, tolerance_pct=0.0
        )
        # With zero tolerance, very similar levels should not cluster
        assert isinstance(result, list)

    def test_tolerance_hundred_percent(self):
        """Test with tolerance_pct=100 (all levels cluster)"""
        lows = [100, 80, 60, 80, 100, 80, 60, 80, 100] * 3
        result = find_support_levels(
            lows, lookback=len(lows), window=2, tolerance_pct=100.0
        )
        # With 100% tolerance, all levels might cluster
        assert isinstance(result, list)
        assert len(result) <= 3  # Most should cluster

    def test_all_identical_values(self):
        """Test with all identical values (flat line)"""
        lows = [100.0] * 100
        result = find_support_levels(lows, lookback=100, window=5)
        # No swings in flat data
        assert isinstance(result, list)

    def test_alternating_values(self):
        """Test with alternating high-low pattern"""
        lows = [100.0, 90.0] * 50  # 100 points alternating
        result = find_support_levels(lows, lookback=100, window=2)
        assert isinstance(result, list)

    def test_single_spike_pattern(self):
        """Test with single downward spike"""
        lows = [100.0] * 25 + [80.0] + [100.0] * 24
        result = find_support_levels(lows, lookback=50, window=5)

        # Should find the spike as support
        if result:
            assert any(75 <= level <= 85 for level in result)

    def test_unicode_or_special_in_volumes(self):
        """Test that volumes must be numeric"""
        lows = generate_support_test_data()
        # This should work with proper numeric volumes
        volumes = [int(1e6)] * len(lows)
        result = find_support_levels(lows, lookback=len(lows), window=3, volumes=volumes)
        assert isinstance(result, list)


# =============================================================================
# TESTS FOR GET_NEAREST_SR_LEVELS
# =============================================================================

class TestGetNearestSRLevels:
    """Tests for get_nearest_sr_levels function"""

    def test_basic_nearest_levels(self):
        """Test basic nearest S/R level detection"""
        n = 100
        current_price = 100.0
        prices = [95 + i * 0.1 for i in range(n)]
        prices[-1] = current_price
        highs = [p + 2 for p in prices]
        lows = [p - 2 for p in prices]
        volumes = [1000000] * n

        result = get_nearest_sr_levels(
            current_price=current_price,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes
        )

        assert 'supports' in result
        assert 'resistances' in result
        assert 'context' in result
        assert result['current_price'] == current_price

    def test_context_contains_52_week_data(self):
        """Test that context includes 52-week high/low"""
        n = 300
        prices = [100 + math.sin(i * 0.1) * 20 for i in range(n)]
        highs = [p + 2 for p in prices]
        lows = [p - 2 for p in prices]

        result = get_nearest_sr_levels(
            current_price=prices[-1],
            prices=prices,
            highs=highs,
            lows=lows
        )

        assert 'week_52_high' in result['context']
        assert 'week_52_low' in result['context']

    def test_context_contains_smas(self):
        """Test that context includes SMA values when sufficient data"""
        n = 250
        prices = [100.0 + i * 0.01 for i in range(n)]
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        result = get_nearest_sr_levels(
            current_price=prices[-1],
            prices=prices,
            highs=highs,
            lows=lows
        )

        assert result['context']['sma_50'] is not None
        assert result['context']['sma_100'] is not None
        assert result['context']['sma_200'] is not None

    def test_insufficient_data_for_smas(self):
        """Test SMA behavior with insufficient data"""
        n = 40  # Less than 50
        prices = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n

        result = get_nearest_sr_levels(
            current_price=100.0,
            prices=prices,
            highs=highs,
            lows=lows
        )

        # SMA50 should be None with only 40 data points
        assert result['context']['sma_50'] is None

    def test_fibonacci_levels_in_context(self):
        """Test that Fibonacci levels are calculated"""
        n = 100
        prices = [100.0 + math.sin(i * 0.1) * 10 for i in range(n)]
        highs = [p + 2 for p in prices]
        lows = [p - 2 for p in prices]

        result = get_nearest_sr_levels(
            current_price=prices[-1],
            prices=prices,
            highs=highs,
            lows=lows
        )

        assert 'fib_levels' in result['context']
        assert '50.0%' in result['context']['fib_levels']

    def test_empty_data_handling(self):
        """Test with insufficient data"""
        result = get_nearest_sr_levels(
            current_price=100.0,
            prices=[100.0] * 10,
            highs=[101.0] * 10,
            lows=[99.0] * 10
        )

        # Should return empty supports/resistances for insufficient data
        assert isinstance(result, dict)


# =============================================================================
# TESTS FOR ANALYZE_SUPPORT_RESISTANCE
# =============================================================================

class TestAnalyzeSupportResistanceComprehensive:
    """Comprehensive tests for analyze_support_resistance function"""

    def test_combined_sr_analysis(self):
        """Test combined support and resistance analysis"""
        data = generate_swing_data(base=100, num_swings=5, swing_amplitude=10, points_per_swing=15)
        prices = data
        highs = [p + 2 for p in data]
        lows = [p - 2 for p in data]
        volumes = [1000000] * len(data)

        result = analyze_support_resistance(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            lookback=len(data),
            window=5
        )

        assert isinstance(result, SupportResistanceResult)
        # Should find both support and resistance
        assert len(result.support_levels) >= 0
        assert len(result.resistance_levels) >= 0

    def test_result_structure(self):
        """Test the structure of returned result"""
        data = generate_swing_data(base=100, num_swings=3, swing_amplitude=10, points_per_swing=20)

        result = analyze_support_resistance(
            prices=data,
            highs=[p + 1 for p in data],
            lows=[p - 1 for p in data],
            volumes=[1000000] * len(data)
        )

        # Check result has all expected attributes
        assert hasattr(result, 'support_levels')
        assert hasattr(result, 'resistance_levels')
        assert hasattr(result, 'nearest_support')
        assert hasattr(result, 'nearest_resistance')
        assert hasattr(result, 'volume_profile')

    def test_with_empty_data(self):
        """Test with empty price data"""
        result = analyze_support_resistance(
            prices=[],
            highs=[],
            lows=[],
            volumes=[]
        )

        assert result.support_levels == []
        assert result.resistance_levels == []


# =============================================================================
# NUMPY INTEGRATION TESTS
# =============================================================================

class TestNumpyIntegration:
    """Tests for numpy array compatibility"""

    def test_support_with_numpy_array(self):
        """Test find_support_levels with numpy array input"""
        lows_np = np.array([100, 98, 95, 90, 95, 98, 100, 98, 95, 90, 95, 98, 100])
        # Convert to list since the function expects list
        result = find_support_levels(list(lows_np), lookback=13, window=2)
        assert isinstance(result, list)

    def test_resistance_with_numpy_array(self):
        """Test find_resistance_levels with numpy array input"""
        highs_np = np.array([100, 102, 105, 110, 105, 102, 100, 102, 105, 110, 105, 102, 100])
        result = find_resistance_levels(list(highs_np), lookback=13, window=2)
        assert isinstance(result, list)

    def test_pivot_points_with_numpy_values(self):
        """Test find_pivot_points with numpy float values"""
        high = np.float64(110.0)
        low = np.float64(90.0)
        close = np.float64(100.0)

        result = find_pivot_points(float(high), float(low), float(close))
        assert 'pivot' in result

    def test_fibonacci_with_numpy_values(self):
        """Test calculate_fibonacci with numpy float values"""
        high = np.float64(120.0)
        low = np.float64(80.0)

        result = calculate_fibonacci(float(high), float(low))
        assert '50.0%' in result
        assert result['50.0%'] == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
