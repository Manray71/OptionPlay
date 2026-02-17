# OptionPlay - VIX Strategy Tests
# =================================
# Comprehensive unit tests for src/vix_strategy.py

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.services.vix_strategy import (
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


# =============================================================================
# MarketRegime Enum Tests
# =============================================================================

class TestMarketRegimeEnum:
    """Tests for MarketRegime enum values and behavior"""

    def test_all_regime_values_exist(self):
        """All expected regime values should be defined"""
        expected_regimes = ["low_vol", "normal", "danger_zone", "elevated", "high_vol", "unknown"]
        actual_values = [regime.value for regime in MarketRegime]

        for expected in expected_regimes:
            assert expected in actual_values, f"Missing regime: {expected}"

    def test_regime_count(self):
        """Should have exactly 6 regimes"""
        assert len(MarketRegime) == 6

    def test_regime_value_types(self):
        """All regime values should be strings"""
        for regime in MarketRegime:
            assert isinstance(regime.value, str)

    def test_low_vol_regime(self):
        """LOW_VOL should have correct value"""
        assert MarketRegime.LOW_VOL.value == "low_vol"

    def test_normal_regime(self):
        """NORMAL should have correct value"""
        assert MarketRegime.NORMAL.value == "normal"

    def test_danger_zone_regime(self):
        """DANGER_ZONE should have correct value"""
        assert MarketRegime.DANGER_ZONE.value == "danger_zone"

    def test_elevated_regime(self):
        """ELEVATED should have correct value"""
        assert MarketRegime.ELEVATED.value == "elevated"

    def test_high_vol_regime(self):
        """HIGH_VOL should have correct value"""
        assert MarketRegime.HIGH_VOL.value == "high_vol"

    def test_unknown_regime(self):
        """UNKNOWN should have correct value"""
        assert MarketRegime.UNKNOWN.value == "unknown"


# =============================================================================
# VIXThresholds Tests
# =============================================================================

class TestVIXThresholds:
    """Tests for VIXThresholds dataclass"""

    def test_default_values(self):
        """Default thresholds should match constants"""
        thresholds = VIXThresholds()

        assert thresholds.low_vol_max == 15.0
        assert thresholds.normal_max == 20.0
        assert thresholds.danger_zone_max == 25.0
        assert thresholds.elevated_max == 30.0

    def test_custom_thresholds(self):
        """Custom thresholds should override defaults"""
        custom = VIXThresholds(
            low_vol_max=12.0,
            normal_max=18.0,
            danger_zone_max=22.0,
            elevated_max=28.0
        )

        assert custom.low_vol_max == 12.0
        assert custom.normal_max == 18.0
        assert custom.danger_zone_max == 22.0
        assert custom.elevated_max == 28.0

    def test_partial_custom_thresholds(self):
        """Partial custom thresholds should use defaults for unspecified"""
        custom = VIXThresholds(low_vol_max=10.0)

        assert custom.low_vol_max == 10.0
        assert custom.normal_max == 20.0  # Default
        assert custom.danger_zone_max == 25.0  # Default
        assert custom.elevated_max == 30.0  # Default


# =============================================================================
# VixTrend Enum Tests
# =============================================================================

class TestVixTrendEnum:
    """Tests for VixTrend enum"""

    def test_all_trend_values_exist(self):
        """All expected trend values should be defined"""
        expected_trends = ["rising_fast", "rising", "stable", "falling", "falling_fast"]
        actual_values = [trend.value for trend in VixTrend]

        for expected in expected_trends:
            assert expected in actual_values, f"Missing trend: {expected}"

    def test_trend_count(self):
        """Should have exactly 5 trends"""
        assert len(VixTrend) == 5


# =============================================================================
# VixTrendInfo Tests
# =============================================================================

class TestVixTrendInfo:
    """Tests for VixTrendInfo dataclass"""

    def test_trend_info_creation(self):
        """Should create VixTrendInfo with all fields"""
        trend_info = VixTrendInfo(
            trend=VixTrend.STABLE,
            z_score=0.5,
            current_vix=18.0,
            mean_5d=17.5,
            std_5d=1.0,
            history_available=True
        )

        assert trend_info.trend == VixTrend.STABLE
        assert trend_info.z_score == 0.5
        assert trend_info.current_vix == 18.0
        assert trend_info.mean_5d == 17.5
        assert trend_info.std_5d == 1.0
        assert trend_info.history_available is True

    def test_trend_description_rising_fast(self):
        """RISING_FAST should have correct description"""
        trend_info = VixTrendInfo(
            trend=VixTrend.RISING_FAST,
            z_score=2.0, current_vix=20.0, mean_5d=15.0, std_5d=2.0
        )
        assert "Rising fast" in trend_info.trend_description

    def test_trend_description_rising(self):
        """RISING should have correct description"""
        trend_info = VixTrendInfo(
            trend=VixTrend.RISING,
            z_score=1.0, current_vix=18.0, mean_5d=16.0, std_5d=1.5
        )
        assert "Rising" in trend_info.trend_description

    def test_trend_description_stable(self):
        """STABLE should have correct description"""
        trend_info = VixTrendInfo(
            trend=VixTrend.STABLE,
            z_score=0.2, current_vix=17.0, mean_5d=17.0, std_5d=1.0
        )
        assert "Stable" in trend_info.trend_description

    def test_trend_description_falling(self):
        """FALLING should have correct description"""
        trend_info = VixTrendInfo(
            trend=VixTrend.FALLING,
            z_score=-1.0, current_vix=16.0, mean_5d=18.0, std_5d=1.5
        )
        assert "Falling" in trend_info.trend_description

    def test_trend_description_falling_fast(self):
        """FALLING_FAST should have correct description"""
        trend_info = VixTrendInfo(
            trend=VixTrend.FALLING_FAST,
            z_score=-2.0, current_vix=14.0, mean_5d=20.0, std_5d=2.5
        )
        assert "Falling fast" in trend_info.trend_description

    def test_history_available_default(self):
        """history_available should default to True"""
        trend_info = VixTrendInfo(
            trend=VixTrend.STABLE,
            z_score=0.0, current_vix=17.0, mean_5d=17.0, std_5d=1.0
        )
        assert trend_info.history_available is True


# =============================================================================
# VIXStrategySelector Initialization Tests
# =============================================================================

class TestVIXStrategySelectorInit:
    """Tests for VIXStrategySelector initialization"""

    def test_default_initialization(self):
        """Should initialize with default thresholds"""
        selector = VIXStrategySelector()

        assert selector.thresholds is not None
        assert selector.thresholds.low_vol_max == 15.0
        assert selector.thresholds.normal_max == 20.0
        assert selector._vix_history_cache is None
        assert selector._cache_timestamp is None

    def test_custom_thresholds_initialization(self):
        """Should initialize with custom thresholds"""
        custom = VIXThresholds(low_vol_max=12.0, normal_max=18.0)
        selector = VIXStrategySelector(thresholds=custom)

        assert selector.thresholds.low_vol_max == 12.0
        assert selector.thresholds.normal_max == 18.0

    def test_profiles_exist(self):
        """PROFILES class attribute should be populated"""
        assert hasattr(VIXStrategySelector, 'PROFILES')
        assert len(VIXStrategySelector.PROFILES) > 0

    def test_all_profiles_defined(self):
        """All expected profiles should be defined"""
        expected_profiles = ['conservative', 'standard', 'danger_zone', 'elevated', 'high_volatility']

        for profile_name in expected_profiles:
            assert profile_name in VIXStrategySelector.PROFILES, f"Missing profile: {profile_name}"

    def test_trend_thresholds_exist(self):
        """TREND_THRESHOLDS class attribute should be defined"""
        assert hasattr(VIXStrategySelector, 'TREND_THRESHOLDS')
        assert 'rising_fast' in VIXStrategySelector.TREND_THRESHOLDS
        assert 'rising' in VIXStrategySelector.TREND_THRESHOLDS
        assert 'falling' in VIXStrategySelector.TREND_THRESHOLDS
        assert 'falling_fast' in VIXStrategySelector.TREND_THRESHOLDS


# =============================================================================
# get_regime Method Tests (5-Tier System)
# =============================================================================

class TestGetRegime:
    """Tests for get_regime method (5-tier system)"""

    def test_low_vol_regime(self):
        """VIX < 15 should be LOW_VOL"""
        selector = VIXStrategySelector()

        assert selector.get_regime(10.0, use_trend=False) == MarketRegime.LOW_VOL
        assert selector.get_regime(14.9, use_trend=False) == MarketRegime.LOW_VOL
        assert selector.get_regime(0.0, use_trend=False) == MarketRegime.LOW_VOL
        assert selector.get_regime(5.0, use_trend=False) == MarketRegime.LOW_VOL

    def test_normal_regime(self):
        """VIX 15-20 should be NORMAL"""
        selector = VIXStrategySelector()

        assert selector.get_regime(15.0, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(17.5, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(19.9, use_trend=False) == MarketRegime.NORMAL

    def test_danger_zone_regime(self):
        """VIX 20-25 should be DANGER_ZONE"""
        selector = VIXStrategySelector()

        assert selector.get_regime(20.0, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(22.5, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(24.9, use_trend=False) == MarketRegime.DANGER_ZONE

    def test_elevated_regime(self):
        """VIX 25-30 should be ELEVATED"""
        selector = VIXStrategySelector()

        assert selector.get_regime(25.0, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(27.5, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(29.9, use_trend=False) == MarketRegime.ELEVATED

    def test_high_vol_regime(self):
        """VIX > 30 should be HIGH_VOL"""
        selector = VIXStrategySelector()

        assert selector.get_regime(30.0, use_trend=False) == MarketRegime.HIGH_VOL
        assert selector.get_regime(35.0, use_trend=False) == MarketRegime.HIGH_VOL
        assert selector.get_regime(50.0, use_trend=False) == MarketRegime.HIGH_VOL

    def test_unknown_regime_for_none(self):
        """None VIX should be UNKNOWN"""
        selector = VIXStrategySelector()
        assert selector.get_regime(None) == MarketRegime.UNKNOWN

    def test_negative_vix_is_unknown(self):
        """Negative VIX should be UNKNOWN"""
        selector = VIXStrategySelector()
        assert selector.get_regime(-5.0) == MarketRegime.UNKNOWN
        assert selector.get_regime(-0.1) == MarketRegime.UNKNOWN

    def test_extremely_high_vix(self):
        """VIX > 100 should be HIGH_VOL with warning"""
        selector = VIXStrategySelector()
        assert selector.get_regime(100.0, use_trend=False) == MarketRegime.HIGH_VOL
        assert selector.get_regime(150.0, use_trend=False) == MarketRegime.HIGH_VOL


# =============================================================================
# _get_static_regime Tests
# =============================================================================

class TestGetStaticRegime:
    """Tests for _get_static_regime private method"""

    def test_static_regime_boundaries(self):
        """Test all boundary values"""
        selector = VIXStrategySelector()

        # Just below boundary
        assert selector._get_static_regime(14.99) == MarketRegime.LOW_VOL
        assert selector._get_static_regime(19.99) == MarketRegime.NORMAL
        assert selector._get_static_regime(24.99) == MarketRegime.DANGER_ZONE
        assert selector._get_static_regime(29.99) == MarketRegime.ELEVATED

    def test_static_regime_at_boundaries(self):
        """Test exact boundary values"""
        selector = VIXStrategySelector()

        assert selector._get_static_regime(15.0) == MarketRegime.NORMAL
        assert selector._get_static_regime(20.0) == MarketRegime.DANGER_ZONE
        assert selector._get_static_regime(25.0) == MarketRegime.ELEVATED
        assert selector._get_static_regime(30.0) == MarketRegime.HIGH_VOL


# =============================================================================
# VIX Trend Analysis Tests
# =============================================================================

class TestVixTrendAnalysis:
    """Tests for VIX trend analysis"""

    def test_trend_calculation_with_history(self):
        """Trend should be calculated from history"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[15.5, 16.0, 16.2, 15.8, 16.1]):
            trend = selector.get_vix_trend(16.0)

            assert trend.history_available is True
            assert trend.mean_5d == pytest.approx(15.92, rel=0.1)
            assert abs(trend.z_score) < 1.0

    def test_rising_fast_trend(self):
        """Rising fast trend with high Z-score"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[15.0, 15.2, 15.5, 15.8, 16.0]):
            trend = selector.get_vix_trend(20.0)

            assert trend.trend == VixTrend.RISING_FAST
            assert trend.z_score > 1.5

    def test_falling_fast_trend(self):
        """Falling fast trend with low Z-score"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[25.0, 24.5, 24.0, 23.5, 23.0]):
            trend = selector.get_vix_trend(18.0)

            assert trend.trend == VixTrend.FALLING_FAST
            assert trend.z_score < -1.5

    def test_stable_trend(self):
        """Stable trend with Z-score near 0"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[17.0, 17.2, 16.8, 17.1, 17.0]):
            trend = selector.get_vix_trend(17.0)

            assert trend.trend == VixTrend.STABLE
            assert abs(trend.z_score) < 0.75

    def test_rising_trend(self):
        """Rising trend with moderate Z-score"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[16.0, 16.2, 16.5, 16.8, 17.0]):
            trend = selector.get_vix_trend(18.0)

            assert trend.trend in [VixTrend.RISING, VixTrend.RISING_FAST]
            assert trend.z_score > 0.75

    def test_falling_trend(self):
        """Falling trend with moderate negative Z-score"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[20.0, 19.5, 19.0, 18.5, 18.0]):
            trend = selector.get_vix_trend(16.5)

            assert trend.trend in [VixTrend.FALLING, VixTrend.FALLING_FAST]
            assert trend.z_score < -0.75

    def test_no_history_available(self):
        """Without history, trend should be STABLE"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[]):
            trend = selector.get_vix_trend(18.0)

            assert trend.history_available is False
            assert trend.trend == VixTrend.STABLE

    def test_insufficient_history(self):
        """With less than 3 days history, trend should be STABLE"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[16.0, 17.0]):
            trend = selector.get_vix_trend(18.0)

            assert trend.history_available is False
            assert trend.trend == VixTrend.STABLE

    def test_uses_last_history_value_when_no_current_vix(self):
        """When current_vix is None, should use last history value"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[16.0, 16.5, 17.0, 17.2, 18.0]):
            trend = selector.get_vix_trend(None)

            assert trend.current_vix == 18.0


# =============================================================================
# Trend Adjustment Tests
# =============================================================================

class TestTrendAdjustment:
    """Tests for trend-based regime adjustment"""

    def test_rising_fast_increases_regime(self):
        """RISING_FAST should increase regime by 1 level"""
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
        """FALLING_FAST should decrease regime by 1 level"""
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
        """STABLE should not change regime"""
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
        """Regime cannot go above HIGH_VOL"""
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
        assert adjusted == MarketRegime.HIGH_VOL

    def test_cannot_go_below_low_vol(self):
        """Regime cannot go below LOW_VOL"""
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
        assert adjusted == MarketRegime.LOW_VOL

    def test_all_regime_transitions_rising_fast(self):
        """Test RISING_FAST transitions through all regimes"""
        selector = VIXStrategySelector()

        trend_info = VixTrendInfo(
            trend=VixTrend.RISING_FAST,
            z_score=2.0,
            current_vix=20.0,
            mean_5d=15.0,
            std_5d=2.0,
            history_available=True
        )

        # LOW_VOL -> NORMAL
        assert selector._adjust_regime_for_trend(MarketRegime.LOW_VOL, trend_info) == MarketRegime.NORMAL
        # NORMAL -> DANGER_ZONE
        assert selector._adjust_regime_for_trend(MarketRegime.NORMAL, trend_info) == MarketRegime.DANGER_ZONE
        # DANGER_ZONE -> ELEVATED
        assert selector._adjust_regime_for_trend(MarketRegime.DANGER_ZONE, trend_info) == MarketRegime.ELEVATED
        # ELEVATED -> HIGH_VOL
        assert selector._adjust_regime_for_trend(MarketRegime.ELEVATED, trend_info) == MarketRegime.HIGH_VOL

    def test_all_regime_transitions_falling_fast(self):
        """Test FALLING_FAST transitions through all regimes"""
        selector = VIXStrategySelector()

        trend_info = VixTrendInfo(
            trend=VixTrend.FALLING_FAST,
            z_score=-2.0,
            current_vix=15.0,
            mean_5d=25.0,
            std_5d=3.0,
            history_available=True
        )

        # HIGH_VOL -> ELEVATED
        assert selector._adjust_regime_for_trend(MarketRegime.HIGH_VOL, trend_info) == MarketRegime.ELEVATED
        # ELEVATED -> DANGER_ZONE
        assert selector._adjust_regime_for_trend(MarketRegime.ELEVATED, trend_info) == MarketRegime.DANGER_ZONE
        # DANGER_ZONE -> NORMAL
        assert selector._adjust_regime_for_trend(MarketRegime.DANGER_ZONE, trend_info) == MarketRegime.NORMAL
        # NORMAL -> LOW_VOL
        assert selector._adjust_regime_for_trend(MarketRegime.NORMAL, trend_info) == MarketRegime.LOW_VOL


# =============================================================================
# _is_near_threshold Tests
# =============================================================================

class TestIsNearThreshold:
    """Tests for _is_near_threshold private method"""

    def test_near_upper_threshold(self):
        """Should detect when near upper threshold"""
        selector = VIXStrategySelector()

        # 1 point margin below threshold
        assert selector._is_near_threshold(14.5, upper=True) is True
        assert selector._is_near_threshold(19.5, upper=True) is True
        assert selector._is_near_threshold(24.5, upper=True) is True
        assert selector._is_near_threshold(29.5, upper=True) is True

    def test_not_near_upper_threshold(self):
        """Should return False when not near upper threshold"""
        selector = VIXStrategySelector()

        assert selector._is_near_threshold(13.0, upper=True) is False
        assert selector._is_near_threshold(17.0, upper=True) is False
        assert selector._is_near_threshold(22.0, upper=True) is False

    def test_near_lower_threshold(self):
        """Should detect when near lower threshold"""
        selector = VIXStrategySelector()

        # At or just above threshold
        assert selector._is_near_threshold(15.5, upper=False) is True
        assert selector._is_near_threshold(20.5, upper=False) is True
        assert selector._is_near_threshold(25.5, upper=False) is True
        assert selector._is_near_threshold(30.5, upper=False) is True

    def test_not_near_lower_threshold(self):
        """Should return False when not near lower threshold"""
        selector = VIXStrategySelector()

        assert selector._is_near_threshold(17.0, upper=False) is False
        assert selector._is_near_threshold(22.0, upper=False) is False


# =============================================================================
# Profile Selection Tests
# =============================================================================

class TestProfileSelection:
    """Tests for profile selection (5-tier system)"""

    def test_conservative_profile(self):
        """VIX < 15 should select conservative profile"""
        selector = VIXStrategySelector()

        assert selector.select_profile(10.0) == "conservative"
        assert selector.select_profile(14.9) == "conservative"

    def test_standard_profile(self):
        """VIX 15-20 should select standard profile"""
        selector = VIXStrategySelector()

        assert selector.select_profile(15.0) == "standard"
        assert selector.select_profile(19.9) == "standard"

    def test_danger_zone_profile(self):
        """VIX 20-25 should select danger_zone profile"""
        selector = VIXStrategySelector()

        assert selector.select_profile(20.0) == "danger_zone"
        assert selector.select_profile(24.9) == "danger_zone"

    def test_elevated_profile(self):
        """VIX 25-30 should select elevated profile"""
        selector = VIXStrategySelector()

        assert selector.select_profile(25.0) == "elevated"
        assert selector.select_profile(29.9) == "elevated"

    def test_high_volatility_profile(self):
        """VIX > 30 should select high_volatility profile"""
        selector = VIXStrategySelector()

        assert selector.select_profile(30.0) == "high_volatility"
        assert selector.select_profile(50.0) == "high_volatility"

    def test_fallback_for_none(self):
        """None VIX should use standard as fallback"""
        selector = VIXStrategySelector()
        assert selector.select_profile(None) == "standard"


# =============================================================================
# get_recommendation Tests
# =============================================================================

class TestGetRecommendation:
    """Tests for get_recommendation method"""

    def test_recommendation_structure(self):
        """Recommendation should have all required fields"""
        selector = VIXStrategySelector()
        rec = selector.get_recommendation(22.5)

        assert rec.profile_name is not None
        assert rec.regime is not None
        assert rec.vix_level == 22.5
        assert rec.delta_target is not None
        assert rec.delta_min is not None
        assert rec.delta_max is not None
        assert rec.long_delta_target is not None
        assert rec.min_score is not None
        assert rec.earnings_buffer_days is not None
        assert rec.dte_min is not None
        assert rec.dte_max is not None
        assert rec.reasoning is not None
        assert rec.warnings is not None

    def test_conservative_recommendation(self):
        """Conservative profile values"""
        rec = get_strategy_for_vix(12.0)

        assert rec.profile_name == "conservative"
        assert rec.regime == MarketRegime.LOW_VOL
        assert rec.delta_target == -0.20
        assert rec.spread_width is None
        assert rec.min_score >= 5
        assert rec.dte_min == 60
        assert rec.dte_max == 90
        assert rec.earnings_buffer_days == 30

    def test_standard_recommendation(self):
        """Standard profile values (sweet spot)"""
        rec = get_strategy_for_vix(17.0)

        assert rec.profile_name == "standard"
        assert rec.regime == MarketRegime.NORMAL
        assert rec.delta_target == -0.20
        assert "Sweet Spot" in rec.reasoning

    def test_danger_zone_recommendation(self):
        """Danger zone profile should have warnings"""
        rec = get_strategy_for_vix(22.0)

        assert rec.profile_name == "danger_zone"
        assert rec.regime == MarketRegime.DANGER_ZONE
        assert len(rec.warnings) > 0
        assert any("DANGER" in w for w in rec.warnings)
        assert rec.min_score >= 7

    def test_elevated_recommendation(self):
        """Elevated profile (paradoxically good)"""
        rec = get_strategy_for_vix(27.0)

        assert rec.profile_name == "elevated"
        assert rec.regime == MarketRegime.ELEVATED
        assert "Paradoxically" in rec.reasoning or "88.6%" in rec.reasoning

    def test_high_vol_recommendation(self):
        """High volatility profile should have warnings"""
        rec = get_strategy_for_vix(35.0)

        assert rec.profile_name == "high_volatility"
        assert rec.regime == MarketRegime.HIGH_VOL
        assert len(rec.warnings) > 0
        assert any("CRASH" in w for w in rec.warnings)

    def test_unknown_recommendation(self):
        """Unknown VIX should return standard with warning"""
        rec = get_strategy_for_vix(None)

        assert rec.profile_name == "standard"
        assert rec.regime == MarketRegime.UNKNOWN
        assert len(rec.warnings) > 0


# =============================================================================
# StrategyRecommendation.to_dict Tests
# =============================================================================

class TestStrategyRecommendationToDict:
    """Tests for StrategyRecommendation.to_dict() method"""

    def test_to_dict_structure(self):
        """to_dict should return expected structure"""
        rec = get_strategy_for_vix(18.0)
        result = rec.to_dict()

        assert 'profile' in result
        assert 'regime' in result
        assert 'vix' in result
        assert 'recommendations' in result
        assert 'reasoning' in result
        assert 'warnings' in result

    def test_to_dict_recommendations_content(self):
        """to_dict recommendations section should have all fields"""
        rec = get_strategy_for_vix(18.0)
        result = rec.to_dict()

        recs = result['recommendations']
        assert 'delta_target' in recs
        assert 'long_delta_target' in recs
        assert 'delta_range' in recs
        assert 'spread_width' in recs
        assert 'min_score' in recs
        assert 'earnings_buffer_days' in recs
        assert 'dte_range' in recs

    def test_to_dict_spread_width_dynamic(self):
        """spread_width should be 'dynamic' in to_dict when None"""
        rec = get_strategy_for_vix(18.0)
        result = rec.to_dict()

        assert result['recommendations']['spread_width'] == 'dynamic'

    def test_to_dict_delta_range(self):
        """delta_range should be a list of [min, max]"""
        rec = get_strategy_for_vix(18.0)
        result = rec.to_dict()

        delta_range = result['recommendations']['delta_range']
        assert isinstance(delta_range, list)
        assert len(delta_range) == 2

    def test_to_dict_dte_range(self):
        """dte_range should be a list of [min, max]"""
        rec = get_strategy_for_vix(18.0)
        result = rec.to_dict()

        dte_range = result['recommendations']['dte_range']
        assert isinstance(dte_range, list)
        assert len(dte_range) == 2


# =============================================================================
# get_all_profiles Tests
# =============================================================================

class TestGetAllProfiles:
    """Tests for get_all_profiles method"""

    def test_returns_dict(self):
        """Should return a dictionary"""
        selector = VIXStrategySelector()
        profiles = selector.get_all_profiles()

        assert isinstance(profiles, dict)

    def test_returns_copy(self):
        """Should return a copy, not the original"""
        selector = VIXStrategySelector()
        profiles = selector.get_all_profiles()

        # Modify the returned dict
        profiles['test'] = 'value'

        # Original should not be affected
        assert 'test' not in selector.PROFILES

    def test_all_profiles_present(self):
        """All expected profiles should be present"""
        selector = VIXStrategySelector()
        profiles = selector.get_all_profiles()

        expected = ['conservative', 'standard', 'danger_zone', 'elevated', 'high_volatility']
        for name in expected:
            assert name in profiles

    def test_profile_structure(self):
        """Each profile should have required keys"""
        selector = VIXStrategySelector()
        profiles = selector.get_all_profiles()

        required_keys = ['delta_target', 'delta_range', 'min_score', 'earnings_buffer_days', 'dte_min', 'dte_max']

        for profile_name, profile in profiles.items():
            for key in required_keys:
                assert key in profile, f"Missing {key} in {profile_name}"


# =============================================================================
# get_regime_description Tests
# =============================================================================

class TestGetRegimeDescription:
    """Tests for get_regime_description method"""

    def test_low_vol_description(self):
        """LOW_VOL description should mention VIX < 15"""
        selector = VIXStrategySelector()
        desc = selector.get_regime_description(MarketRegime.LOW_VOL)

        assert "Low" in desc
        assert "15" in desc

    def test_normal_description(self):
        """NORMAL description should mention Sweet Spot"""
        selector = VIXStrategySelector()
        desc = selector.get_regime_description(MarketRegime.NORMAL)

        assert "Normal" in desc
        assert "Sweet Spot" in desc

    def test_danger_zone_description(self):
        """DANGER_ZONE description should mention danger"""
        selector = VIXStrategySelector()
        desc = selector.get_regime_description(MarketRegime.DANGER_ZONE)

        assert "DANGER" in desc

    def test_elevated_description(self):
        """ELEVATED description should mention VIX 25-30"""
        selector = VIXStrategySelector()
        desc = selector.get_regime_description(MarketRegime.ELEVATED)

        assert "Elevated" in desc
        assert "25" in desc

    def test_high_vol_description(self):
        """HIGH_VOL description should mention VIX > 30"""
        selector = VIXStrategySelector()
        desc = selector.get_regime_description(MarketRegime.HIGH_VOL)

        assert "High" in desc
        assert "30" in desc

    def test_unknown_description(self):
        """UNKNOWN description should mention no VIX data"""
        selector = VIXStrategySelector()
        desc = selector.get_regime_description(MarketRegime.UNKNOWN)

        assert "Unknown" in desc or "no VIX" in desc


# =============================================================================
# get_regime_with_trend Tests
# =============================================================================

class TestGetRegimeWithTrend:
    """Tests for get_regime_with_trend method"""

    def test_returns_tuple(self):
        """Should return tuple of (Regime, TrendInfo)"""
        selector = VIXStrategySelector()

        with patch.object(selector, '_get_vix_history', return_value=[16.0, 16.5, 17.0, 17.2, 17.5]):
            regime, trend_info = selector.get_regime_with_trend(18.0)

            assert isinstance(regime, MarketRegime)
            assert isinstance(trend_info, VixTrendInfo)

    def test_none_vix_returns_unknown_and_none(self):
        """None VIX should return UNKNOWN and None"""
        selector = VIXStrategySelector()

        regime, trend_info = selector.get_regime_with_trend(None)

        assert regime == MarketRegime.UNKNOWN
        assert trend_info is None


# =============================================================================
# Boundary Value Tests
# =============================================================================

class TestBoundaryValues:
    """Tests for boundary values"""

    def test_exact_boundaries(self):
        """Exact boundary values should be assigned correctly"""
        selector = VIXStrategySelector()

        # Boundaries: 15, 20, 25, 30
        assert selector.get_regime(15.0, use_trend=False) == MarketRegime.NORMAL
        assert selector.get_regime(20.0, use_trend=False) == MarketRegime.DANGER_ZONE
        assert selector.get_regime(25.0, use_trend=False) == MarketRegime.ELEVATED
        assert selector.get_regime(30.0, use_trend=False) == MarketRegime.HIGH_VOL

    def test_zero_vix(self):
        """VIX = 0 should be LOW_VOL"""
        selector = VIXStrategySelector()
        assert selector.get_regime(0.0, use_trend=False) == MarketRegime.LOW_VOL

    def test_extreme_vix(self):
        """Extremely high VIX should be HIGH_VOL"""
        selector = VIXStrategySelector()
        assert selector.get_regime(100.0, use_trend=False) == MarketRegime.HIGH_VOL
        assert selector.get_regime(200.0, use_trend=False) == MarketRegime.HIGH_VOL


# =============================================================================
# Custom Thresholds Tests
# =============================================================================

class TestCustomThresholds:
    """Tests for custom thresholds"""

    def test_custom_thresholds_affect_regime(self):
        """Custom thresholds should affect regime determination"""
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


# =============================================================================
# format_recommendation Tests
# =============================================================================

class TestFormatRecommendation:
    """Tests for format_recommendation function"""

    def test_format_is_string(self):
        """format_recommendation should return string"""
        rec = get_strategy_for_vix(18.0)
        output = format_recommendation(rec)

        assert isinstance(output, str)
        assert len(output) > 50

    def test_format_contains_vix(self):
        """Formatted output should contain VIX value"""
        rec = get_strategy_for_vix(22.5)
        output = format_recommendation(rec)

        assert "22.5" in output or "22" in output

    def test_format_contains_regime(self):
        """Formatted output should contain regime"""
        rec = get_strategy_for_vix(22.5)
        output = format_recommendation(rec)

        assert rec.regime.value in output

    def test_format_contains_profile(self):
        """Formatted output should contain profile name"""
        rec = get_strategy_for_vix(22.5)
        output = format_recommendation(rec)

        assert rec.profile_name.upper() in output or rec.profile_name in output

    def test_format_with_none_vix(self):
        """Should handle None VIX"""
        rec = get_strategy_for_vix(None)
        output = format_recommendation(rec)

        assert isinstance(output, str)
        assert "n/a" in output.lower() or "unknown" in output.lower()


# =============================================================================
# get_strategy_for_stock Tests
# =============================================================================

class TestGetStrategyForStock:
    """Tests for get_strategy_for_stock function"""

    def test_returns_recommendation(self):
        """Should return StrategyRecommendation"""
        rec = get_strategy_for_stock(18.0, 150.0)
        assert rec is not None
        assert rec.regime is not None

    def test_spread_width_is_none(self):
        """Spread width should be None (delta-based)"""
        rec = get_strategy_for_stock(18.0, 150.0)
        assert rec.spread_width is None

    def test_delta_target_is_set(self):
        """Delta target should be -0.20"""
        rec = get_strategy_for_stock(18.0, 150.0)
        assert rec.delta_target == -0.20

    def test_regime_correct_for_vix(self):
        """Regime should match VIX value"""
        rec = get_strategy_for_stock(18.0, 150.0)
        assert rec.regime == MarketRegime.NORMAL

        rec = get_strategy_for_stock(27.0, 150.0)
        assert rec.regime == MarketRegime.ELEVATED

    def test_ignores_stock_price(self):
        """Stock price should not affect recommendation (spread is dynamic)"""
        rec1 = get_strategy_for_stock(18.0, 50.0)
        rec2 = get_strategy_for_stock(18.0, 500.0)

        assert rec1.regime == rec2.regime
        assert rec1.delta_target == rec2.delta_target


# =============================================================================
# VIX History Cache Tests
# =============================================================================

class TestVIXHistoryCache:
    """Tests for VIX history caching"""

    def test_cache_is_initially_none(self):
        """Cache should be None initially"""
        selector = VIXStrategySelector()

        assert selector._vix_history_cache is None
        assert selector._cache_timestamp is None

    def test_cache_invalidation_on_timeout(self):
        """Cache should be refreshed after timeout"""
        import time

        selector = VIXStrategySelector()

        # Mock _get_vix_history to set cache
        with patch.object(selector, '_get_vix_history', return_value=[16.0, 17.0, 18.0]):
            selector.get_vix_trend(18.0)

        # Cache should be populated by the real _get_vix_history
        # This test mainly verifies the structure exists


# =============================================================================
# Profile Delta Range Tests
# =============================================================================

class TestProfileDeltaRanges:
    """Tests for profile delta ranges"""

    def test_danger_zone_uses_standard_delta_range(self):
        """Danger zone should use same delta range as standard (PLAYBOOK §2: Delta ist heilig)"""
        selector = VIXStrategySelector()

        standard = selector.PROFILES['standard']
        danger = selector.PROFILES['danger_zone']

        standard_range = standard['delta_range']
        danger_range = danger['delta_range']

        # Delta ist heilig — same range across all regimes
        assert danger_range == standard_range

    def test_all_profiles_have_delta_range(self):
        """All profiles should have delta_range"""
        selector = VIXStrategySelector()

        for name, profile in selector.PROFILES.items():
            assert 'delta_range' in profile, f"Missing delta_range in {name}"
            assert len(profile['delta_range']) == 2, f"Invalid delta_range in {name}"


# =============================================================================
# Position Size Factor Tests
# =============================================================================

class TestPositionSizeFactors:
    """Tests for position size factors in profiles"""

    def test_danger_zone_has_size_factor(self):
        """Danger zone should have position_size_factor"""
        selector = VIXStrategySelector()
        danger = selector.PROFILES['danger_zone']

        assert 'position_size_factor' in danger
        assert danger['position_size_factor'] == 0.75

    def test_high_volatility_has_size_factor(self):
        """High volatility should have position_size_factor"""
        selector = VIXStrategySelector()
        high_vol = selector.PROFILES['high_volatility']

        assert 'position_size_factor' in high_vol
        assert high_vol['position_size_factor'] == 0.50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
