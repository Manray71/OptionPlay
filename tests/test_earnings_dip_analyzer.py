# OptionPlay - Earnings Dip Analyzer Tests
# ==========================================

import pytest
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
from models.base import SignalType, SignalStrength


class TestEarningsDipBasics:
    """Grundlegende Tests für Earnings Dip Analyzer"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    @pytest.fixture
    def earnings_dip_data(self):
        """Generiert Daten mit Earnings-Dip und Recovery"""
        n = 100
        prices = []
        
        # Vor Earnings: Stabiler Aufwärtstrend
        for i in range(90):
            prices.append(100 + i * 0.1)  # Steigt bis 109
        
        # Earnings Dip: -10%
        prices.append(99)   # Gap down Day 1
        prices.append(98.5) # Continued selling Day 2
        prices.append(98)   # Low reached Day 3
        
        # Stabilisierung
        prices.append(98.5) # Day 4
        prices.append(99)   # Day 5
        prices.append(99.5) # Day 6 (aktuell)
        prices.append(100)  # Day 7
        prices.append(100.5) # Day 8
        prices.append(101)  # Day 9
        prices.append(101.5) # Day 10
        
        volumes = [1000000] * n
        volumes[90:93] = [3000000, 2500000, 2000000]  # Erhöhtes Volumen beim Dip
        volumes[93:] = [1200000] * (n - 93)  # Normalisiert
        
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        # Tieferes Low am Dip-Tag
        lows[92] = 97.0
        
        return prices, volumes, highs, lows
    
    def test_strategy_name(self, analyzer):
        """Strategy Name sollte korrekt sein"""
        assert analyzer.strategy_name == "earnings_dip"
    
    def test_dip_detected(self, analyzer, earnings_dip_data):
        """Earnings Dip sollte erkannt werden"""
        prices, volumes, highs, lows = earnings_dip_data
        
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=109.0
        )
        
        assert "Dip" in signal.reason or signal.score > 0
    
    def test_no_signal_without_dip(self, analyzer):
        """Kein Signal ohne Dip"""
        n = 100
        # Kontinuierlicher Aufwärtstrend, kein Dip
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL
        assert "Dip zu klein" in signal.reason or signal.score < 5


class TestEarningsDipConfig:
    """Tests für Earnings Dip Konfiguration"""
    
    def test_custom_config(self):
        """Custom Config sollte angewendet werden"""
        config = EarningsDipConfig(
            min_dip_pct=7.0,
            max_dip_pct=20.0,
            rsi_oversold_threshold=30.0
        )
        
        analyzer = EarningsDipAnalyzer(config)
        
        assert analyzer.config.min_dip_pct == 7.0
        assert analyzer.config.max_dip_pct == 20.0
    
    def test_larger_min_dip_fewer_signals(self):
        """Größerer min_dip sollte weniger Signale geben"""
        n = 100
        # Moderater Dip von ~2.5% - explizit kontrolliert
        prices = [100.0] * 90  # Stabiler Preis vor Dip
        prices += [97, 95, 94, 94.5, 95, 95.5, 96, 96.5, 97, 97.5]  # Dip auf 94, dann Recovery
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        lows[92] = 93.5  # Klares Dip-Low
        
        # Strikt (min 10%) - sollte KEIN Signal geben weil Dip nur ~2.5%
        strict = EarningsDipAnalyzer(EarningsDipConfig(min_dip_pct=10.0))
        signal_strict = strict.analyze("TEST", prices, volumes, highs, lows)
        
        # Der Dip ist < 10%, also sollte NEUTRAL sein
        assert signal_strict.signal_type == SignalType.NEUTRAL


class TestEarningsDipDetection:
    """Tests für Dip-Erkennung"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    def test_detects_moderate_dip(self, analyzer):
        """Moderater Dip (5-10%) sollte erkannt werden"""
        n = 100
        prices = [100.0] * 90
        prices += [93, 92, 91, 91.5, 92, 92.5, 93, 93.5, 94, 94.5]  # ~8% Dip, Recovery
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.details.get('dip_info', {}).get('dip_pct', 0) > 5
    
    def test_rejects_too_large_dip(self, analyzer):
        """Zu großer Dip (>25%) sollte abgelehnt werden"""
        n = 100
        prices = [100.0] * 90
        prices += [70, 68, 65, 66, 67, 68, 69, 70, 71, 72]  # ~30% Dip
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL
        assert "zu groß" in signal.reason.lower() or "riskant" in signal.reason.lower()


class TestEarningsDipStabilization:
    """Tests für Stabilisierungs-Erkennung"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    def test_detects_stabilization(self, analyzer):
        """Stabilisierung sollte erkannt werden"""
        lows = [100] * 90
        lows += [92, 91, 90, 91, 92, 93, 94, 95, 96, 97]  # Low bei 90, dann höher
        
        score, info = analyzer._score_stabilization(lows)
        
        assert info['days_without_new_low'] >= 2
        assert score >= 1
    
    def test_no_stabilization_new_lows(self, analyzer):
        """Keine Stabilisierung bei neuen Lows"""
        lows = [100] * 90
        lows += [95, 94, 93, 92, 91, 90, 89, 88, 87, 86]  # Kontinuierlich neue Lows
        
        score, info = analyzer._score_stabilization(lows)
        
        assert score == 0 or info['days_without_new_low'] < 2


class TestEarningsDipRiskManagement:
    """Tests für Risk Management"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    def test_stop_below_dip_low(self, analyzer):
        """Stop Loss sollte unter Dip-Low sein"""
        n = 100
        prices = [100.0] * 90
        prices += [92, 90, 88, 89, 90, 91, 92, 93, 94, 95]
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 1 for p in prices]
        lows[92] = 86  # Klares Dip-Low
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        if signal.stop_loss:
            # Stop sollte unter dem Dip-Low aus dip_info sein
            dip_low = signal.details.get('dip_info', {}).get('dip_low', min(lows[-10:]))
            assert signal.stop_loss < dip_low
    
    def test_target_is_partial_recovery(self, analyzer):
        """Target sollte teilweise Recovery sein"""
        n = 100
        pre_price = 100.0
        current = 92.0
        
        prices = [pre_price] * 90
        prices += [93, 91, 90, 91, 92, 92, 92, 92, 92, current]
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze(
            "TEST", prices, volumes, highs, lows,
            pre_earnings_price=pre_price
        )
        
        if signal.target_price:
            # Target sollte zwischen current und pre_price sein
            assert current < signal.target_price < pre_price


class TestEarningsDipEdgeCases:
    """Edge Cases für Earnings Dip Analyzer"""
    
    @pytest.fixture
    def analyzer(self):
        return EarningsDipAnalyzer()
    
    def test_insufficient_data(self, analyzer):
        """Zu wenig Daten sollte Exception werfen"""
        prices = [100] * 30
        volumes = [1000000] * 30
        highs = [101] * 30
        lows = [99] * 30
        
        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)
    
    def test_warning_for_large_dip(self, analyzer):
        """Großer Dip sollte Warnung generieren"""
        n = 100
        prices = [100.0] * 90
        prices += [82, 80, 78, 79, 80, 81, 82, 83, 84, 85]  # ~18% Dip
        
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        # Entweder Warnung oder niedriger Score
        has_warning = any("risiko" in w.lower() or "groß" in w.lower() 
                         for w in signal.warnings)
        assert has_warning or signal.signal_type == SignalType.NEUTRAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
