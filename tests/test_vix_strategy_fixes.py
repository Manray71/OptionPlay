# OptionPlay - VIX Strategy Fixes Tests
# =======================================
# Tests für die Bug-Fixes aus optionplay_fixes_applied.md

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vix_strategy import (
    VIXStrategySelector,
    MarketRegime,
    VIXThresholds,
    get_strategy_for_vix
)


class TestVIXValidation:
    """
    Tests für Fix #10: VIX-Validierung

    get_regime() prüft jetzt auf negative VIX-Werte und extrem hohe Werte.
    """

    def test_vix_negative_returns_unknown(self):
        """Test: Negative VIX gibt UNKNOWN"""
        selector = VIXStrategySelector()

        regime = selector.get_regime(-5.0, use_trend=False)

        assert regime == MarketRegime.UNKNOWN

    def test_vix_negative_minus_one(self):
        """Test: VIX = -1 gibt UNKNOWN"""
        selector = VIXStrategySelector()

        regime = selector.get_regime(-1.0, use_trend=False)

        assert regime == MarketRegime.UNKNOWN

    def test_vix_negative_small(self):
        """Test: VIX = -0.01 gibt UNKNOWN"""
        selector = VIXStrategySelector()

        regime = selector.get_regime(-0.01, use_trend=False)

        assert regime == MarketRegime.UNKNOWN

    def test_vix_zero_is_low_vol(self):
        """Test: VIX = 0 gibt LOW_VOL (gültig, wenn auch unwahrscheinlich)"""
        selector = VIXStrategySelector()

        regime = selector.get_regime(0.0, use_trend=False)

        assert regime == MarketRegime.LOW_VOL

    def test_vix_extreme_high_returns_high_vol(self):
        """Test: VIX > 100 gibt HIGH_VOL mit Warnung"""
        selector = VIXStrategySelector()

        regime = selector.get_regime(150.0, use_trend=False)

        assert regime == MarketRegime.HIGH_VOL

    def test_vix_exactly_100(self):
        """Test: VIX = 100 gibt HIGH_VOL"""
        selector = VIXStrategySelector()

        regime = selector.get_regime(100.0, use_trend=False)

        assert regime == MarketRegime.HIGH_VOL

    def test_vix_101_with_warning(self):
        """Test: VIX = 101 gibt HIGH_VOL (über 100 Grenze)"""
        selector = VIXStrategySelector()

        regime = selector.get_regime(101.0, use_trend=False)

        assert regime == MarketRegime.HIGH_VOL

    def test_vix_none_returns_unknown(self):
        """Test: VIX = None gibt UNKNOWN"""
        selector = VIXStrategySelector()

        regime = selector.get_regime(None, use_trend=False)

        assert regime == MarketRegime.UNKNOWN


class TestVIXNormalRanges:
    """Tests für normale VIX-Bereiche (5-Stufen-System)"""

    def test_vix_low_vol_range(self):
        """Test: VIX 0-14.99 ist LOW_VOL"""
        selector = VIXStrategySelector()

        for vix in [0.0, 5.0, 10.0, 14.0, 14.99]:
            assert selector.get_regime(vix, use_trend=False) == MarketRegime.LOW_VOL

    def test_vix_normal_range(self):
        """Test: VIX 15-19.99 ist NORMAL"""
        selector = VIXStrategySelector()

        for vix in [15.0, 16.0, 17.5, 19.0, 19.99]:
            assert selector.get_regime(vix, use_trend=False) == MarketRegime.NORMAL

    def test_vix_danger_zone_range(self):
        """Test: VIX 20-24.99 ist DANGER_ZONE (5-Stufen-System)"""
        selector = VIXStrategySelector()

        for vix in [20.0, 22.5, 24.0, 24.99]:
            assert selector.get_regime(vix, use_trend=False) == MarketRegime.DANGER_ZONE

    def test_vix_elevated_range(self):
        """Test: VIX 25-29.99 ist ELEVATED (5-Stufen-System)"""
        selector = VIXStrategySelector()

        for vix in [25.0, 27.0, 28.0, 29.99]:
            assert selector.get_regime(vix, use_trend=False) == MarketRegime.ELEVATED

    def test_vix_high_vol_range(self):
        """Test: VIX 30+ ist HIGH_VOL"""
        selector = VIXStrategySelector()

        for vix in [30.0, 35.0, 50.0, 80.0, 100.0]:
            assert selector.get_regime(vix, use_trend=False) == MarketRegime.HIGH_VOL


class TestProfileSelectionWithValidation:
    """Tests für Profil-Auswahl mit Validierung"""
    
    def test_profile_for_negative_vix(self):
        """Test: Negative VIX gibt Standard-Profil als Fallback"""
        selector = VIXStrategySelector()
        
        profile = selector.select_profile(-10.0)
        
        assert profile == "standard"  # Fallback für UNKNOWN
    
    def test_profile_for_none_vix(self):
        """Test: None VIX gibt Standard-Profil"""
        selector = VIXStrategySelector()
        
        profile = selector.select_profile(None)
        
        assert profile == "standard"
    
    def test_profile_for_extreme_vix(self):
        """Test: Extrem hoher VIX gibt high_volatility Profil"""
        selector = VIXStrategySelector()
        
        profile = selector.select_profile(200.0)
        
        assert profile == "high_volatility"


class TestRecommendationWithValidation:
    """Tests für vollständige Empfehlungen mit Validierung"""
    
    def test_recommendation_for_negative_vix(self):
        """Test: Negative VIX gibt Empfehlung mit Warnung"""
        rec = get_strategy_for_vix(-5.0)
        
        assert rec.regime == MarketRegime.UNKNOWN
        assert rec.profile_name == "standard"
        assert len(rec.warnings) > 0
    
    def test_recommendation_for_none_vix(self):
        """Test: None VIX gibt Empfehlung mit Warnung"""
        rec = get_strategy_for_vix(None)
        
        assert rec.regime == MarketRegime.UNKNOWN
        assert ("VIX nicht verfügbar" in rec.warnings[0]
                or "nicht verfügbar" in rec.reasoning
                or "not available" in rec.warnings[0]
                or "No VIX" in rec.reasoning)
    
    def test_recommendation_for_extreme_vix_has_warnings(self):
        """Test: Extrem hoher VIX hat Crash-Mode Warnungen"""
        rec = get_strategy_for_vix(150.0)

        assert rec.regime == MarketRegime.HIGH_VOL
        # Warnungen enthalten CRASH-MODUS oder Positionsgrößen
        assert any("CRASH" in w or "Positions" in w for w in rec.warnings)
    
    def test_recommendation_values_are_valid(self):
        """Test: Empfehlungswerte sind plausibel"""
        for vix in [10.0, 18.0, 25.0, 40.0]:
            rec = get_strategy_for_vix(vix)

            assert -1.0 < rec.delta_target < 0  # Delta ist negativ für Puts
            assert rec.spread_width is None  # Now dynamic (delta-based)
            assert 0 < rec.min_score <= 10
            assert rec.earnings_buffer_days > 0


class TestCustomThresholdsWithValidation:
    """Tests für benutzerdefinierte Schwellenwerte"""

    def test_custom_thresholds_validation_still_works(self):
        """Test: Validierung funktioniert auch mit Custom Thresholds"""
        custom = VIXThresholds(
            low_vol_max=12.0,
            normal_max=18.0,
            danger_zone_max=22.0,
            elevated_max=28.0
        )
        selector = VIXStrategySelector(thresholds=custom)

        # Negative VIX sollte immer noch UNKNOWN sein
        assert selector.get_regime(-5.0, use_trend=False) == MarketRegime.UNKNOWN

        # Normale Bereiche mit neuen Thresholds (5-Stufen-System)
        assert selector.get_regime(11.0, use_trend=False) == MarketRegime.LOW_VOL
        assert selector.get_regime(15.0, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(20.0, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(25.0, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(30.0, use_trend=False) == MarketRegime.HIGH_VOL


class TestBoundaryConditions:
    """Tests für Grenzwerte (5-Stufen-System)"""

    def test_exact_boundaries(self):
        """Test: Exakte Grenzen werden korrekt zugeordnet (5-Stufen-System)"""
        selector = VIXStrategySelector()

        # Bei exakt 15.0 -> NORMAL (nicht mehr LOW_VOL)
        assert selector.get_regime(14.99, use_trend=False) == MarketRegime.LOW_VOL
        assert selector.get_regime(15.0, use_trend=False) == MarketRegime.NORMAL

        # Bei exakt 20.0 -> DANGER_ZONE (NEU im 5-Stufen-System)
        assert selector.get_regime(19.99, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(20.0, use_trend=False) == MarketRegime.DANGER_ZONE

        # Bei exakt 25.0 -> ELEVATED
        assert selector.get_regime(24.99, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(25.0, use_trend=False) == MarketRegime.ELEVATED

        # Bei exakt 30.0 -> HIGH_VOL
        assert selector.get_regime(29.99, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(30.0, use_trend=False) == MarketRegime.HIGH_VOL

    def test_float_precision(self):
        """Test: Float-Präzision verursacht keine Probleme"""
        selector = VIXStrategySelector()

        # Diese Werte könnten Float-Präzisionsprobleme haben
        assert selector.get_regime(14.999999999, use_trend=False) == MarketRegime.LOW_VOL
        assert selector.get_regime(15.000000001, use_trend=False) == MarketRegime.NORMAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
