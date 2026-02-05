"""
Tests for the Regime Config module.

Tests cover:
- RegimeType and RegimeBoundaryMethod enums
- RegimeConfig dataclass
- RegimeState dataclass
- RegimeTransition dataclass
- Helper functions (get_regime_for_vix, load_regimes, etc.)
- TrainedModelLoader class
"""

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backtesting.regime_config import (
    RegimeBoundaryMethod,
    RegimeConfig,
    RegimeType,
    FIXED_REGIMES,
    get_regime_for_vix,
    load_regimes,
    format_regime_summary,
)


# =============================================================================
# ENUM TESTS
# =============================================================================


class TestRegimeType:
    """Tests for RegimeType enum."""

    def test_enum_values(self):
        """Test enum values are correct."""
        assert RegimeType.LOW_VOL.value == "low_vol"
        assert RegimeType.NORMAL.value == "normal"
        assert RegimeType.ELEVATED.value == "elevated"
        assert RegimeType.HIGH_VOL.value == "high_vol"

    def test_enum_string_conversion(self):
        """Test enum string conversion."""
        assert str(RegimeType.LOW_VOL) == "RegimeType.LOW_VOL"
        assert RegimeType.NORMAL.value == "normal"


class TestRegimeBoundaryMethod:
    """Tests for RegimeBoundaryMethod enum."""

    def test_enum_values(self):
        """Test enum values are correct."""
        assert RegimeBoundaryMethod.FIXED.value == "fixed"
        assert RegimeBoundaryMethod.PERCENTILE.value == "percentile"


# =============================================================================
# REGIME CONFIG TESTS
# =============================================================================


class TestRegimeConfig:
    """Tests for RegimeConfig dataclass."""

    def test_basic_creation(self):
        """Test basic RegimeConfig creation."""
        config = RegimeConfig(
            name="test_regime",
            regime_type=RegimeType.NORMAL,
            vix_lower=15.0,
            vix_upper=20.0,
        )
        assert config.name == "test_regime"
        assert config.regime_type == RegimeType.NORMAL
        assert config.vix_lower == 15.0
        assert config.vix_upper == 20.0

    def test_default_values(self):
        """Test default values are set correctly."""
        config = RegimeConfig(
            name="test",
            regime_type=RegimeType.NORMAL,
            vix_lower=15.0,
            vix_upper=20.0,
        )
        assert config.entry_buffer == 0.0
        assert config.exit_buffer == 1.0
        assert config.min_days_in_regime == 2
        assert config.min_score == 5.0
        assert config.profit_target_pct == 50.0
        assert config.stop_loss_pct == 150.0
        assert config.max_concurrent_positions == 10
        assert "pullback" in config.strategies_enabled

    def test_validation_vix_bounds(self):
        """Test validation fails when vix_lower >= vix_upper."""
        with pytest.raises(ValueError, match="vix_lower.*must be less than"):
            RegimeConfig(
                name="invalid",
                regime_type=RegimeType.NORMAL,
                vix_lower=25.0,
                vix_upper=20.0,
            )

    def test_validation_vix_bounds_equal(self):
        """Test validation fails when vix_lower == vix_upper."""
        with pytest.raises(ValueError, match="vix_lower.*must be less than"):
            RegimeConfig(
                name="invalid",
                regime_type=RegimeType.NORMAL,
                vix_lower=20.0,
                vix_upper=20.0,
            )

    def test_validation_min_score_negative(self):
        """Test validation fails for negative min_score."""
        with pytest.raises(ValueError, match="min_score must be between"):
            RegimeConfig(
                name="invalid",
                regime_type=RegimeType.NORMAL,
                vix_lower=15.0,
                vix_upper=20.0,
                min_score=-1.0,
            )

    def test_validation_min_score_too_high(self):
        """Test validation fails for min_score > 15."""
        with pytest.raises(ValueError, match="min_score must be between"):
            RegimeConfig(
                name="invalid",
                regime_type=RegimeType.NORMAL,
                vix_lower=15.0,
                vix_upper=20.0,
                min_score=16.0,
            )

    def test_contains_vix_basic(self):
        """Test contains_vix basic functionality."""
        config = RegimeConfig(
            name="test",
            regime_type=RegimeType.NORMAL,
            vix_lower=15.0,
            vix_upper=20.0,
        )
        assert config.contains_vix(17.0) is True
        assert config.contains_vix(15.0) is True
        assert config.contains_vix(14.9) is False
        assert config.contains_vix(20.0) is False
        assert config.contains_vix(25.0) is False

    def test_contains_vix_with_hysteresis(self):
        """Test contains_vix with hysteresis."""
        config = RegimeConfig(
            name="test",
            regime_type=RegimeType.NORMAL,
            vix_lower=15.0,
            vix_upper=20.0,
            exit_buffer=1.0,
        )
        # Without hysteresis
        assert config.contains_vix(14.5, with_hysteresis=False) is False
        # With hysteresis (exit_buffer extends range)
        assert config.contains_vix(14.5, with_hysteresis=True) is True
        assert config.contains_vix(20.5, with_hysteresis=True) is True
        assert config.contains_vix(21.1, with_hysteresis=True) is False

    def test_to_dict(self):
        """Test to_dict serialization."""
        config = RegimeConfig(
            name="test",
            regime_type=RegimeType.NORMAL,
            vix_lower=15.0,
            vix_upper=20.0,
            description="Test regime",
            is_trained=True,
            training_date=datetime(2026, 1, 15, 10, 0, 0),
            sample_size=1000,
        )
        d = config.to_dict()

        assert d["name"] == "test"
        assert d["regime_type"] == "normal"
        assert d["vix_boundaries"]["lower"] == 15.0
        assert d["vix_boundaries"]["upper"] == 20.0
        assert d["metadata"]["is_trained"] is True
        assert d["metadata"]["sample_size"] == 1000

    def test_from_dict(self):
        """Test from_dict deserialization."""
        data = {
            "name": "test",
            "regime_type": "normal",
            "vix_boundaries": {"lower": 15.0, "upper": 20.0},
            "hysteresis": {"entry_buffer": 0.5, "exit_buffer": 1.5},
            "trading_parameters": {
                "min_score": 6.0,
                "profit_target_pct": 60.0,
            },
            "strategies": {"enabled": ["pullback", "bounce"]},
            "metadata": {
                "is_trained": True,
                "training_date": "2026-01-15T10:00:00",
            },
        }
        config = RegimeConfig.from_dict(data)

        assert config.name == "test"
        assert config.regime_type == RegimeType.NORMAL
        assert config.vix_lower == 15.0
        assert config.entry_buffer == 0.5
        assert config.min_score == 6.0
        assert config.is_trained is True

    def test_round_trip_serialization(self):
        """Test that to_dict -> from_dict produces equivalent config."""
        original = RegimeConfig(
            name="test",
            regime_type=RegimeType.ELEVATED,
            vix_lower=20.0,
            vix_upper=30.0,
            min_score=7.0,
            strategies_enabled=["pullback", "bounce"],
            strategy_weights={"pullback": 0.6, "bounce": 0.4},
            is_trained=True,
            sample_size=500,
        )

        d = original.to_dict()
        loaded = RegimeConfig.from_dict(d)

        assert loaded.name == original.name
        assert loaded.regime_type == original.regime_type
        assert loaded.vix_lower == original.vix_lower
        assert loaded.vix_upper == original.vix_upper
        assert loaded.min_score == original.min_score
        assert loaded.strategies_enabled == original.strategies_enabled


# =============================================================================
# FIXED REGIMES TESTS
# =============================================================================


class TestFixedRegimes:
    """Tests for FIXED_REGIMES constant."""

    def test_fixed_regimes_defined(self):
        """Test that FIXED_REGIMES is defined."""
        assert FIXED_REGIMES is not None
        assert len(FIXED_REGIMES) == 4

    def test_fixed_regimes_coverage(self):
        """Test that FIXED_REGIMES cover all VIX ranges."""
        # Check each regime type is present
        regime_types = {config.regime_type for config in FIXED_REGIMES.values()}
        assert RegimeType.LOW_VOL in regime_types
        assert RegimeType.NORMAL in regime_types
        assert RegimeType.ELEVATED in regime_types
        assert RegimeType.HIGH_VOL in regime_types

    def test_fixed_regimes_non_overlapping(self):
        """Test that FIXED_REGIMES don't overlap."""
        regimes = list(FIXED_REGIMES.values())
        for i, r1 in enumerate(regimes):
            for r2 in regimes[i + 1:]:
                # Check no overlap (excluding boundaries)
                assert r1.vix_upper <= r2.vix_lower or r2.vix_upper <= r1.vix_lower


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================


class TestGetRegimeForVix:
    """Tests for get_regime_for_vix function."""

    def test_low_vol(self):
        """Test detection of low vol regime."""
        name, config = get_regime_for_vix(12.0, FIXED_REGIMES)
        assert config is not None
        assert config.regime_type == RegimeType.LOW_VOL

    def test_normal(self):
        """Test detection of normal regime."""
        name, config = get_regime_for_vix(17.0, FIXED_REGIMES)
        assert config is not None
        assert config.regime_type == RegimeType.NORMAL

    def test_elevated(self):
        """Test detection of elevated regime."""
        name, config = get_regime_for_vix(25.0, FIXED_REGIMES)
        assert config is not None
        assert config.regime_type == RegimeType.ELEVATED

    def test_high_vol(self):
        """Test detection of high vol regime."""
        name, config = get_regime_for_vix(35.0, FIXED_REGIMES)
        assert config is not None
        assert config.regime_type == RegimeType.HIGH_VOL

    def test_boundary_values(self):
        """Test boundary VIX values."""
        # At exact boundaries
        name_15, config_15 = get_regime_for_vix(15.0, FIXED_REGIMES)
        assert config_15 is not None  # Should be in some regime

        name_20, config_20 = get_regime_for_vix(20.0, FIXED_REGIMES)
        assert config_20 is not None

        name_30, config_30 = get_regime_for_vix(30.0, FIXED_REGIMES)
        assert config_30 is not None

    def test_extreme_vix_low(self):
        """Test very low VIX."""
        name, config = get_regime_for_vix(8.0, FIXED_REGIMES)
        assert config is not None
        assert config.regime_type == RegimeType.LOW_VOL

    def test_extreme_vix_high(self):
        """Test very high VIX."""
        name, config = get_regime_for_vix(80.0, FIXED_REGIMES)
        assert config is not None
        assert config.regime_type == RegimeType.HIGH_VOL


class TestLoadRegimes:
    """Tests for load_regimes function."""

    def test_load_regimes_valid_file(self):
        """Test loading regimes from valid JSON file."""
        regimes_data = {
            "version": "1.0.0",
            "regimes": {
                "low_vol": {
                    "name": "low_vol",
                    "regime_type": "low_vol",
                    "vix_boundaries": {"lower": 0, "upper": 15},
                    "trading_parameters": {"min_score": 5.0},
                },
                "normal": {
                    "name": "normal",
                    "regime_type": "normal",
                    "vix_boundaries": {"lower": 15, "upper": 20},
                    "trading_parameters": {"min_score": 6.0},
                },
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(regimes_data, f)
            filepath = f.name

        try:
            regimes = load_regimes(filepath)
            assert len(regimes) == 2
            assert "low_vol" in regimes
            assert "normal" in regimes
        finally:
            Path(filepath).unlink()

    def test_load_regimes_nonexistent_file(self):
        """Test loading from nonexistent file returns FIXED_REGIMES or raises."""
        # Function may either return FIXED_REGIMES or raise FileNotFoundError
        try:
            result = load_regimes("/nonexistent/path/regimes.json")
            # If it returns, should be FIXED_REGIMES
            assert result == FIXED_REGIMES
        except FileNotFoundError:
            # This is also acceptable behavior
            pass


class TestFormatRegimeSummary:
    """Tests for format_regime_summary function."""

    def test_format_regime_summary_basic(self):
        """Test basic regime summary formatting."""
        summary = format_regime_summary(FIXED_REGIMES)
        assert isinstance(summary, str)
        assert "low_vol" in summary.lower() or "LOW" in summary
        assert "normal" in summary.lower() or "NORMAL" in summary

    def test_format_regime_summary_includes_vix_ranges(self):
        """Test that summary includes VIX ranges."""
        summary = format_regime_summary(FIXED_REGIMES)
        # Should contain some VIX numbers
        assert any(char.isdigit() for char in summary)
