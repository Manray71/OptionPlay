# OptionPlay - VIX Strategy Tests
# =================================

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vix_strategy import (
    VIXStrategySelector,
    MarketRegime,
    VIXThresholds,
    StrategyRecommendation,
    get_strategy_for_vix,
    format_recommendation
)


class TestMarketRegime:
    """Tests für MarketRegime-Bestimmung"""
    
    def test_low_vol_regime(self):
        """VIX < 15 sollte LOW_VOL sein"""
        selector = VIXStrategySelector()
        
        assert selector.get_regime(10.0) == MarketRegime.LOW_VOL
        assert selector.get_regime(14.9) == MarketRegime.LOW_VOL
        
    def test_normal_regime(self):
        """VIX 15-20 sollte NORMAL sein"""
        selector = VIXStrategySelector()
        
        assert selector.get_regime(15.0) == MarketRegime.NORMAL
        assert selector.get_regime(17.5) == MarketRegime.NORMAL
        assert selector.get_regime(19.9) == MarketRegime.NORMAL
        
    def test_elevated_regime(self):
        """VIX 20-30 sollte ELEVATED sein"""
        selector = VIXStrategySelector()
        
        assert selector.get_regime(20.0) == MarketRegime.ELEVATED
        assert selector.get_regime(25.0) == MarketRegime.ELEVATED
        assert selector.get_regime(29.9) == MarketRegime.ELEVATED
        
    def test_high_vol_regime(self):
        """VIX > 30 sollte HIGH_VOL sein"""
        selector = VIXStrategySelector()
        
        assert selector.get_regime(30.0) == MarketRegime.HIGH_VOL
        assert selector.get_regime(50.0) == MarketRegime.HIGH_VOL
        
    def test_unknown_regime_for_none(self):
        """None VIX sollte UNKNOWN sein"""
        selector = VIXStrategySelector()
        
        assert selector.get_regime(None) == MarketRegime.UNKNOWN


class TestProfileSelection:
    """Tests für Profil-Auswahl"""
    
    def test_conservative_profile(self):
        """VIX < 15 sollte conservative Profil wählen"""
        selector = VIXStrategySelector()
        
        assert selector.select_profile(10.0) == "conservative"
        assert selector.select_profile(14.9) == "conservative"
        
    def test_standard_profile(self):
        """VIX 15-20 sollte standard Profil wählen"""
        selector = VIXStrategySelector()
        
        assert selector.select_profile(15.0) == "standard"
        assert selector.select_profile(19.9) == "standard"
        
    def test_aggressive_profile(self):
        """VIX 20-30 sollte aggressive Profil wählen"""
        selector = VIXStrategySelector()
        
        assert selector.select_profile(20.0) == "aggressive"
        assert selector.select_profile(29.9) == "aggressive"
        
    def test_high_volatility_profile(self):
        """VIX > 30 sollte high_volatility Profil wählen"""
        selector = VIXStrategySelector()
        
        assert selector.select_profile(30.0) == "high_volatility"
        assert selector.select_profile(50.0) == "high_volatility"
        
    def test_fallback_for_none(self):
        """None VIX sollte standard als Fallback wählen"""
        selector = VIXStrategySelector()
        
        assert selector.select_profile(None) == "standard"


class TestStrategyRecommendation:
    """Tests für vollständige Strategie-Empfehlungen"""
    
    def test_recommendation_structure(self):
        """Empfehlung sollte alle Felder haben"""
        rec = get_strategy_for_vix(22.5)
        
        assert rec.profile_name is not None
        assert rec.regime is not None
        assert rec.vix_level == 22.5
        assert rec.delta_target is not None
        assert rec.spread_width is not None
        assert rec.min_score is not None
        assert rec.earnings_buffer_days is not None
        
    def test_conservative_values(self):
        """Conservative-Profil sollte konservative Werte haben"""
        rec = get_strategy_for_vix(12.0)
        
        assert rec.profile_name == "conservative"
        assert rec.delta_target == -0.20
        assert rec.spread_width == 2.5
        assert rec.min_score >= 6
        
    def test_aggressive_values(self):
        """Aggressive-Profil sollte aggressivere Werte haben"""
        rec = get_strategy_for_vix(25.0)
        
        assert rec.profile_name == "aggressive"
        assert rec.delta_target == -0.35
        assert rec.min_score <= 4
        
    def test_high_vol_has_warnings(self):
        """High-Vol sollte Warnungen enthalten"""
        rec = get_strategy_for_vix(35.0)
        
        assert rec.profile_name == "high_volatility"
        assert len(rec.warnings) > 0


class TestBoundaryValues:
    """Tests für Grenzwerte"""
    
    def test_exact_boundaries(self):
        """Exakte Grenzen sollten korrekt zugeordnet werden"""
        selector = VIXStrategySelector()
        
        # Grenzen: 15, 20, 30
        assert selector.get_regime(15.0) == MarketRegime.NORMAL
        assert selector.get_regime(20.0) == MarketRegime.ELEVATED
        assert selector.get_regime(30.0) == MarketRegime.HIGH_VOL
        
    def test_zero_vix(self):
        """VIX = 0 sollte LOW_VOL sein"""
        selector = VIXStrategySelector()
        assert selector.get_regime(0.0) == MarketRegime.LOW_VOL
        
    def test_extreme_vix(self):
        """Extrem hoher VIX sollte HIGH_VOL sein"""
        selector = VIXStrategySelector()
        assert selector.get_regime(100.0) == MarketRegime.HIGH_VOL


class TestCustomThresholds:
    """Tests für angepasste Schwellenwerte"""
    
    def test_custom_thresholds(self):
        """Benutzerdefinierte Schwellen sollten funktionieren"""
        custom = VIXThresholds(
            low_vol_max=12.0,
            normal_max=18.0,
            elevated_max=25.0
        )
        selector = VIXStrategySelector(thresholds=custom)
        
        assert selector.get_regime(11.0) == MarketRegime.LOW_VOL
        assert selector.get_regime(13.0) == MarketRegime.NORMAL
        assert selector.get_regime(20.0) == MarketRegime.ELEVATED
        assert selector.get_regime(26.0) == MarketRegime.HIGH_VOL


class TestFormatRecommendation:
    """Tests für formatierte Ausgabe"""
    
    def test_format_is_string(self):
        """format_recommendation sollte String zurückgeben"""
        rec = get_strategy_for_vix(18.0)
        output = format_recommendation(rec)
        
        assert isinstance(output, str)
        assert len(output) > 50
        
    def test_format_contains_key_info(self):
        """Formatierte Ausgabe sollte wichtige Infos enthalten"""
        rec = get_strategy_for_vix(22.5)
        output = format_recommendation(rec)
        
        assert "22.5" in output or "22" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
