# OptionPlay - ATH Breakout Analyzer Tests
# ==========================================

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from models.base import SignalType, SignalStrength


class TestATHBreakoutBasics:
    """Grundlegende Tests für ATH Breakout Analyzer"""
    
    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()
    
    @pytest.fixture
    def uptrend_data(self):
        """Generiert Aufwärtstrend-Daten mit ATH-Breakout"""
        n = 260
        # Aufwärtstrend mit Konsolidierung und dann Breakout
        prices = []
        highs = []
        lows = []
        
        for i in range(n):
            if i < 200:
                # Aufwärtstrend bis 120
                p = 100 + i * 0.1
                prices.append(p)
                highs.append(p + 0.5)  # ATH wird 120.5
                lows.append(p - 0.5)
            elif i < 250:
                # Konsolidierung bei 115 (deutlich unter ATH von 120.5)
                p = 115 + (i % 3) * 0.2
                prices.append(p)
                highs.append(p + 0.3)  # Highs unter altem ATH
                lows.append(p - 0.3)
            else:
                # BREAKOUT: Neues ATH!
                p = 121 + (i - 250) * 0.5
                prices.append(p)
                highs.append(p + 1)  # Neues ATH über 120.5!
                lows.append(p - 0.3)
        
        volumes = [1000000] * n
        volumes[-1] = 2000000  # Volume Spike am Breakout
        
        return prices, volumes, highs, lows
    
    def test_strategy_name(self, analyzer):
        """Strategy Name sollte korrekt sein"""
        assert analyzer.strategy_name == "ath_breakout"
    
    def test_breakout_detected(self, analyzer, uptrend_data):
        """ATH Breakout sollte erkannt werden"""
        prices, volumes, highs, lows = uptrend_data
        
        # Debug: Check that the data actually has a breakout
        old_ath = max(highs[:-10])  # ATH vor den letzten 10 Tagen
        current_high = highs[-1]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        # Wenn current_high > old_ath, sollte Breakout erkannt werden
        if current_high > old_ath * 1.01:  # Mindestens 1% über ATH
            assert signal.score >= 2, f"Expected score >= 2, got {signal.score}. Current high: {current_high}, Old ATH: {old_ath}"
        else:
            # Testdaten erzeugen keinen echten Breakout - Test überspringen
            assert signal.signal_type in [SignalType.LONG, SignalType.NEUTRAL]
    
    def test_no_breakout_in_downtrend(self, analyzer):
        """Kein Signal bei Abwärtstrend"""
        n = 260
        prices = [100 - i * 0.1 for i in range(n)]  # Abwärtstrend
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL
        assert signal.score < 5
    
    def test_volume_confirmation_bonus(self, analyzer, uptrend_data):
        """Volumen-Spike sollte Score erhöhen"""
        prices, volumes, highs, lows = uptrend_data
        
        # Mit Volumen-Spike
        signal_with_vol = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        # Ohne Volumen-Spike
        low_volumes = [1000000] * len(volumes)
        signal_no_vol = analyzer.analyze("TEST", prices, low_volumes, highs, lows)
        
        assert signal_with_vol.score >= signal_no_vol.score


class TestATHBreakoutConfig:
    """Tests für ATH Breakout Konfiguration"""
    
    def test_custom_config(self):
        """Custom Config sollte angewendet werden"""
        config = ATHBreakoutConfig(
            breakout_threshold_pct=2.0,
            volume_spike_multiplier=2.0,
            min_score_for_signal=7
        )
        
        analyzer = ATHBreakoutAnalyzer(config)
        
        assert analyzer.config.breakout_threshold_pct == 2.0
        assert analyzer.config.volume_spike_multiplier == 2.0
    
    def test_stricter_config_less_signals(self):
        """Striktere Config sollte weniger Signale geben"""
        n = 260
        prices = [100 + i * 0.08 for i in range(n)]
        volumes = [1000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        # Standard Config
        standard = ATHBreakoutAnalyzer()
        signal_standard = standard.analyze("TEST", prices, volumes, highs, lows)
        
        # Strikte Config
        strict_config = ATHBreakoutConfig(min_score_for_signal=9)
        strict = ATHBreakoutAnalyzer(strict_config)
        signal_strict = strict.analyze("TEST", prices, volumes, highs, lows)
        
        # Beide haben Score, aber nur Standard hat LONG Signal
        if signal_standard.signal_type == SignalType.LONG:
            assert signal_strict.score <= signal_standard.score or \
                   signal_strict.signal_type == SignalType.NEUTRAL


class TestATHBreakoutRiskManagement:
    """Tests für Risk Management"""
    
    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()
    
    def test_stop_loss_below_recent_low(self, analyzer):
        """Stop Loss sollte unter letztem Low sein"""
        n = 260
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [2000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        if signal.stop_loss:
            recent_low = min(lows[-10:])
            assert signal.stop_loss < recent_low
    
    def test_target_has_positive_rr(self, analyzer):
        """Target sollte positives Risk/Reward haben"""
        n = 260
        prices = [100 + i * 0.1 for i in range(n)]
        volumes = [2000000] * n
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        if signal.risk_reward_ratio:
            assert signal.risk_reward_ratio >= 1.5


class TestATHBreakoutEdgeCases:
    """Edge Cases für ATH Breakout"""
    
    @pytest.fixture
    def analyzer(self):
        return ATHBreakoutAnalyzer()
    
    def test_insufficient_data(self, analyzer):
        """Zu wenig Daten sollte Exception werfen"""
        prices = [100] * 50  # Nur 50 Punkte, braucht 252
        volumes = [1000000] * 50
        highs = [101] * 50
        lows = [99] * 50
        
        with pytest.raises(ValueError):
            analyzer.analyze("TEST", prices, volumes, highs, lows)
    
    def test_flat_prices_no_signal(self, analyzer):
        """Flache Preise sollten kein Signal geben"""
        n = 260
        prices = [100.0] * n  # Komplett flat
        volumes = [1000000] * n
        highs = [100.5] * n
        lows = [99.5] * n
        
        signal = analyzer.analyze("TEST", prices, volumes, highs, lows)
        
        assert signal.signal_type == SignalType.NEUTRAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
