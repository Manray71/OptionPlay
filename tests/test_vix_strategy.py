# OptionPlay - VIX Strategy Tests
# =================================

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vix_strategy import (
    VIXStrategySelector,
    MarketRegime,
    VIXThresholds,
    StrategyRecommendation,
    VixTrend,
    VixTrendInfo,
    get_strategy_for_vix,
    get_strategy_for_stock,
    format_recommendation
)


class TestMarketRegime:
    """Tests für MarketRegime-Bestimmung (5-Stufen-System)"""

    def test_low_vol_regime(self):
        """VIX < 15 sollte LOW_VOL sein"""
        selector = VIXStrategySelector()

        # use_trend=False um statisches Regime zu testen
        assert selector.get_regime(10.0, use_trend=False) == MarketRegime.LOW_VOL
        assert selector.get_regime(14.9, use_trend=False) == MarketRegime.LOW_VOL

    def test_normal_regime(self):
        """VIX 15-20 sollte NORMAL sein"""
        selector = VIXStrategySelector()

        assert selector.get_regime(15.0, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(17.5, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(19.9, use_trend=False) == MarketRegime.NORMAL

    def test_danger_zone_regime(self):
        """VIX 20-25 sollte DANGER_ZONE sein"""
        selector = VIXStrategySelector()

        assert selector.get_regime(20.0, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(22.5, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(24.9, use_trend=False) == MarketRegime.DANGER_ZONE

    def test_elevated_regime(self):
        """VIX 25-30 sollte ELEVATED sein"""
        selector = VIXStrategySelector()

        assert selector.get_regime(25.0, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(27.5, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(29.9, use_trend=False) == MarketRegime.ELEVATED

    def test_high_vol_regime(self):
        """VIX > 30 sollte HIGH_VOL sein"""
        selector = VIXStrategySelector()

        assert selector.get_regime(30.0, use_trend=False) == MarketRegime.HIGH_VOL
        assert selector.get_regime(50.0, use_trend=False) == MarketRegime.HIGH_VOL

    def test_unknown_regime_for_none(self):
        """None VIX sollte UNKNOWN sein"""
        selector = VIXStrategySelector()

        assert selector.get_regime(None) == MarketRegime.UNKNOWN

    def test_negative_vix_is_unknown(self):
        """Negativer VIX sollte UNKNOWN sein"""
        selector = VIXStrategySelector()

        assert selector.get_regime(-5.0) == MarketRegime.UNKNOWN


class TestVixTrend:
    """Tests für VIX-Trend-Analyse"""

    def test_trend_calculation_with_history(self):
        """Trend sollte korrekt aus Historie berechnet werden"""
        selector = VIXStrategySelector()

        # Mock VIX-History: stabile Werte um 16
        with patch.object(selector, '_get_vix_history', return_value=[15.5, 16.0, 16.2, 15.8, 16.1]):
            trend = selector.get_vix_trend(16.0)

            assert trend.history_available is True
            assert trend.mean_5d == pytest.approx(15.92, rel=0.1)
            assert abs(trend.z_score) < 1.0  # Stabil

    def test_rising_fast_trend(self):
        """Stark steigender Trend bei hohem Z-Score"""
        selector = VIXStrategySelector()

        # Mock: VIX steigt von 15 auf 20
        with patch.object(selector, '_get_vix_history', return_value=[15.0, 15.2, 15.5, 15.8, 16.0]):
            trend = selector.get_vix_trend(20.0)

            assert trend.trend == VixTrend.RISING_FAST
            assert trend.z_score > 1.5

    def test_falling_fast_trend(self):
        """Stark fallender Trend bei niedrigem Z-Score"""
        selector = VIXStrategySelector()

        # Mock: VIX fällt von 25 auf 18
        with patch.object(selector, '_get_vix_history', return_value=[25.0, 24.5, 24.0, 23.5, 23.0]):
            trend = selector.get_vix_trend(18.0)

            assert trend.trend == VixTrend.FALLING_FAST
            assert trend.z_score < -1.5

    def test_stable_trend(self):
        """Stabiler Trend bei Z-Score nahe 0"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[17.0, 17.2, 16.8, 17.1, 17.0]):
            trend = selector.get_vix_trend(17.0)

            assert trend.trend == VixTrend.STABLE
            assert abs(trend.z_score) < 0.75

    def test_no_history_available(self):
        """Ohne History sollte Trend STABLE sein"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[]):
            trend = selector.get_vix_trend(18.0)

            assert trend.history_available is False
            assert trend.trend == VixTrend.STABLE


class TestTrendAdjustment:
    """Tests für Trend-basierte Regime-Anpassung"""

    def test_rising_fast_increases_regime(self):
        """RISING_FAST sollte Regime um 1 Stufe erhöhen"""
        selector = VIXStrategySelector()

        trend_info = VixTrendInfo(
            trend=VixTrend.RISING_FAST,
            z_score=2.0,
            current_vix=19.0,
            mean_5d=16.0,
            std_5d=1.5,
            history_available=True
        )

        adjusted = selector._adjust_regime_for_trend(MarketRegime.NORMAL, trend_info)
        assert adjusted == MarketRegime.DANGER_ZONE

    def test_falling_fast_decreases_regime(self):
        """FALLING_FAST sollte Regime um 1 Stufe senken"""
        selector = VIXStrategySelector()

        trend_info = VixTrendInfo(
            trend=VixTrend.FALLING_FAST,
            z_score=-2.0,
            current_vix=21.0,
            mean_5d=26.0,
            std_5d=2.0,
            history_available=True
        )

        adjusted = selector._adjust_regime_for_trend(MarketRegime.DANGER_ZONE, trend_info)
        assert adjusted == MarketRegime.NORMAL

    def test_stable_no_change(self):
        """STABLE sollte Regime nicht ändern"""
        selector = VIXStrategySelector()

        trend_info = VixTrendInfo(
            trend=VixTrend.STABLE,
            z_score=0.1,
            current_vix=18.0,
            mean_5d=17.5,
            std_5d=1.0,
            history_available=True
        )

        adjusted = selector._adjust_regime_for_trend(MarketRegime.NORMAL, trend_info)
        assert adjusted == MarketRegime.NORMAL

    def test_cannot_exceed_high_vol(self):
        """Regime kann nicht über HIGH_VOL hinaus gehen"""
        selector = VIXStrategySelector()

        trend_info = VixTrendInfo(
            trend=VixTrend.RISING_FAST,
            z_score=3.0,
            current_vix=35.0,
            mean_5d=28.0,
            std_5d=2.0,
            history_available=True
        )

        adjusted = selector._adjust_regime_for_trend(MarketRegime.HIGH_VOL, trend_info)
        assert adjusted == MarketRegime.HIGH_VOL  # Bleibt gleich

    def test_cannot_go_below_low_vol(self):
        """Regime kann nicht unter LOW_VOL gehen"""
        selector = VIXStrategySelector()

        trend_info = VixTrendInfo(
            trend=VixTrend.FALLING_FAST,
            z_score=-3.0,
            current_vix=12.0,
            mean_5d=16.0,
            std_5d=1.5,
            history_available=True
        )

        adjusted = selector._adjust_regime_for_trend(MarketRegime.LOW_VOL, trend_info)
        assert adjusted == MarketRegime.LOW_VOL  # Bleibt gleich


class TestProfileSelection:
    """Tests für Profil-Auswahl (5-Stufen-System)"""

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

    def test_danger_zone_profile(self):
        """VIX 20-25 sollte danger_zone Profil wählen"""
        selector = VIXStrategySelector()

        assert selector.select_profile(20.0) == "danger_zone"
        assert selector.select_profile(24.9) == "danger_zone"

    def test_elevated_profile(self):
        """VIX 25-30 sollte elevated Profil wählen"""
        selector = VIXStrategySelector()

        assert selector.select_profile(25.0) == "elevated"
        assert selector.select_profile(29.9) == "elevated"

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
        # spread_width is now None (dynamic, delta-based)
        assert rec.min_score is not None
        assert rec.earnings_buffer_days is not None

    def test_conservative_values(self):
        """Conservative-Profil sollte Basis-Werte haben"""
        rec = get_strategy_for_vix(12.0)

        assert rec.profile_name == "conservative"
        assert rec.delta_target == -0.20
        assert rec.spread_width is None  # Dynamic (delta-based)
        assert rec.min_score >= 5
        assert rec.dte_min == 60
        assert rec.dte_max == 90
        assert rec.earnings_buffer_days == 60

    def test_danger_zone_has_warnings(self):
        """Danger Zone sollte Warnungen enthalten"""
        rec = get_strategy_for_vix(22.0)

        assert rec.profile_name == "danger_zone"
        assert len(rec.warnings) > 0
        assert any("DANGER" in w for w in rec.warnings)

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

        # 5-Stufen-Grenzen: 15, 20, 25, 30
        assert selector.get_regime(15.0, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(20.0, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(25.0, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(30.0, use_trend=False) == MarketRegime.HIGH_VOL

    def test_zero_vix(self):
        """VIX = 0 sollte LOW_VOL sein"""
        selector = VIXStrategySelector()
        assert selector.get_regime(0.0, use_trend=False) == MarketRegime.LOW_VOL

    def test_extreme_vix(self):
        """Extrem hoher VIX sollte HIGH_VOL sein mit Warning"""
        selector = VIXStrategySelector()
        assert selector.get_regime(100.0, use_trend=False) == MarketRegime.HIGH_VOL


class TestCustomThresholds:
    """Tests für angepasste Schwellenwerte"""

    def test_custom_thresholds(self):
        """Benutzerdefinierte Schwellen sollten funktionieren"""
        custom = VIXThresholds(
            low_vol_max=12.0,
            normal_max=18.0,
            danger_zone_max=22.0,
            elevated_max=28.0
        )
        selector = VIXStrategySelector(thresholds=custom)

        assert selector.get_regime(11.0, use_trend=False) == MarketRegime.LOW_VOL
        assert selector.get_regime(15.0, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(20.0, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(25.0, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(30.0, use_trend=False) == MarketRegime.HIGH_VOL


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


class TestGetStrategyForStock:
    """Tests für get_strategy_for_stock — spread_width ist jetzt dynamic (None)"""

    def test_returns_recommendation(self):
        """Sollte StrategyRecommendation zurückgeben"""
        rec = get_strategy_for_stock(18.0, 150.0)
        assert rec is not None
        assert rec.regime is not None

    def test_spread_width_is_none(self):
        """Spread width sollte None sein (delta-basiert)"""
        rec = get_strategy_for_stock(18.0, 150.0)
        assert rec.spread_width is None

    def test_delta_target_is_set(self):
        """Delta target sollte -0.20 sein"""
        rec = get_strategy_for_stock(18.0, 150.0)
        assert rec.delta_target == -0.20

    def test_regime_correct_for_vix(self):
        """Regime sollte korrekt für VIX-Wert sein"""
        rec = get_strategy_for_stock(18.0, 150.0)
        assert rec.regime == MarketRegime.NORMAL

        rec = get_strategy_for_stock(27.0, 150.0)
        assert rec.regime == MarketRegime.ELEVATED


class TestGetRegimeWithTrend:
    """Tests für get_regime_with_trend"""

    def test_returns_tuple(self):
        """Sollte Tuple von (Regime, TrendInfo) zurückgeben"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[16.0, 16.5, 17.0, 17.2, 17.5]):
            regime, trend_info = selector.get_regime_with_trend(18.0)

            assert isinstance(regime, MarketRegime)
            assert isinstance(trend_info, VixTrendInfo)

    def test_none_vix_returns_unknown(self):
        """None VIX sollte UNKNOWN und None zurückgeben"""
        selector = VIXStrategySelector()

        regime, trend_info = selector.get_regime_with_trend(None)

        assert regime == MarketRegime.UNKNOWN
        assert trend_info is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
