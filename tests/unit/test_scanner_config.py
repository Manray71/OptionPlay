# Tests for Scanner Config Loader
# ================================
"""
Tests for adaptive RSI thresholds, earnings buffer, and support bounce
configuration loaded from YAML files.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.utils.scanner_config_loader import (
    RSITier,
    ScannerConfig,
    get_scanner_config,
    reset_scanner_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset singleton before each test."""
    reset_scanner_config()
    yield
    reset_scanner_config()


@pytest.fixture
def rsi_config_path(tmp_path):
    """Create a temporary RSI thresholds config."""
    config = {
        "rsi_thresholds": {
            "description": "Test RSI thresholds",
            "tiers": [
                {"name": "high_stability", "min_stability": 85, "neutral_threshold": 42},
                {"name": "medium_stability", "min_stability": 70, "neutral_threshold": 40},
                {"name": "low_stability", "min_stability": 60, "neutral_threshold": 38},
                {"name": "very_low_stability", "min_stability": 0, "neutral_threshold": 35},
            ],
            "scoring": {
                "severe_oversold": {"max_rsi": 30, "penalty": -1.5},
                "overbought": {"min_rsi": 70, "penalty": -0.5},
            },
        }
    }
    path = tmp_path / "rsi_thresholds.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


@pytest.fixture
def scanner_config_path(tmp_path):
    """Create a temporary scanner config."""
    config = {
        "scanner": {
            "earnings_buffer": {
                "conservative": 45,
                "standard": 30,
                "aggressive": 20,
                "current_mode": "standard",
            },
            "support_bounce": {
                "min_touches": 3,
                "strong_touches": 5,
                "moderate_touches": 4,
            },
        }
    }
    path = tmp_path / "scanner_config.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


@pytest.fixture
def config(rsi_config_path, scanner_config_path):
    """Create a ScannerConfig with test config files."""
    return ScannerConfig(
        rsi_config_path=rsi_config_path,
        scanner_config_path=scanner_config_path,
    )


# ---------------------------------------------------------------------------
# RSI Threshold Tests
# ---------------------------------------------------------------------------


class TestRSIThresholds:
    """Test adaptive RSI thresholds based on stability score."""

    def test_high_stability_threshold(self, config):
        """Stability 85+ → neutral threshold 42."""
        assert config.get_rsi_neutral_threshold(92) == 42
        assert config.get_rsi_neutral_threshold(85) == 42
        assert config.get_rsi_neutral_threshold(100) == 42

    def test_medium_stability_threshold(self, config):
        """Stability 70-84 → neutral threshold 40."""
        assert config.get_rsi_neutral_threshold(84) == 40
        assert config.get_rsi_neutral_threshold(75) == 40
        assert config.get_rsi_neutral_threshold(70) == 40

    def test_low_stability_threshold(self, config):
        """Stability 60-69 → neutral threshold 38."""
        assert config.get_rsi_neutral_threshold(69) == 38
        assert config.get_rsi_neutral_threshold(65) == 38
        assert config.get_rsi_neutral_threshold(60) == 38

    def test_very_low_stability_threshold(self, config):
        """Stability <60 → neutral threshold 35."""
        assert config.get_rsi_neutral_threshold(59) == 35
        assert config.get_rsi_neutral_threshold(50) == 35
        assert config.get_rsi_neutral_threshold(0) == 35

    def test_boundary_values(self, config):
        """Test exact boundary values."""
        assert config.get_rsi_neutral_threshold(85) == 42  # high
        assert config.get_rsi_neutral_threshold(84.9) == 40  # medium
        assert config.get_rsi_neutral_threshold(70) == 40  # medium
        assert config.get_rsi_neutral_threshold(69.9) == 38  # low
        assert config.get_rsi_neutral_threshold(60) == 38  # low
        assert config.get_rsi_neutral_threshold(59.9) == 35  # very low

    def test_scoring_config(self, config):
        """Get RSI scoring adjustments."""
        scoring = config.get_rsi_scoring_config()
        assert scoring["severe_oversold"]["max_rsi"] == 30
        assert scoring["severe_oversold"]["penalty"] == -1.5
        assert scoring["overbought"]["min_rsi"] == 70


class TestRSIThresholdsFallback:
    """Test fallback behavior when config files are missing."""

    def test_missing_rsi_config_uses_defaults(self, scanner_config_path):
        """Missing RSI config falls back to hardcoded defaults."""
        missing = Path("/nonexistent/rsi_thresholds.yaml")
        cfg = ScannerConfig(
            rsi_config_path=missing,
            scanner_config_path=scanner_config_path,
        )
        # Defaults should match the YAML values
        assert cfg.get_rsi_neutral_threshold(90) == 42
        assert cfg.get_rsi_neutral_threshold(75) == 40
        assert cfg.get_rsi_neutral_threshold(65) == 38
        assert cfg.get_rsi_neutral_threshold(50) == 35

    def test_empty_tiers_uses_defaults(self, tmp_path, scanner_config_path):
        """Empty tiers list falls back to defaults."""
        config = {"rsi_thresholds": {"tiers": []}}
        path = tmp_path / "empty_rsi.yaml"
        with open(path, "w") as f:
            yaml.dump(config, f)

        cfg = ScannerConfig(rsi_config_path=path, scanner_config_path=scanner_config_path)
        assert cfg.get_rsi_neutral_threshold(90) == 42


# ---------------------------------------------------------------------------
# Earnings Buffer Tests
# ---------------------------------------------------------------------------


class TestEarningsBuffer:
    """Test configurable earnings buffer."""

    def test_standard_mode(self, config):
        """Standard mode → 30 days."""
        assert config.get_earnings_buffer_days() == 30

    def test_conservative_mode(self, config):
        """Conservative mode → 45 days."""
        assert config.get_earnings_buffer_days("conservative") == 45

    def test_aggressive_mode(self, config):
        """Aggressive mode → 20 days."""
        assert config.get_earnings_buffer_days("aggressive") == 20

    def test_explicit_standard_mode(self, config):
        """Explicit standard mode → 30 days."""
        assert config.get_earnings_buffer_days("standard") == 30

    def test_missing_config_defaults_to_30(self):
        """Missing scanner config defaults to 30 days."""
        cfg = ScannerConfig(
            rsi_config_path=Path("/nonexistent/rsi.yaml"),
            scanner_config_path=Path("/nonexistent/scanner.yaml"),
        )
        assert cfg.get_earnings_buffer_days() == 30


# ---------------------------------------------------------------------------
# Support Bounce Tests
# ---------------------------------------------------------------------------


class TestSupportBounce:
    """Test configurable support bounce settings."""

    def test_min_touches(self, config):
        """Minimum touches → 3."""
        assert config.get_support_min_touches() == 3

    def test_strong_touches(self, config):
        """Strong classification → 5."""
        assert config.get_support_strong_touches() == 5

    def test_moderate_touches(self, config):
        """Moderate classification → 4."""
        assert config.get_support_moderate_touches() == 4

    def test_missing_config_defaults(self):
        """Missing config uses hardcoded defaults."""
        cfg = ScannerConfig(
            rsi_config_path=Path("/nonexistent/rsi.yaml"),
            scanner_config_path=Path("/nonexistent/scanner.yaml"),
        )
        assert cfg.get_support_min_touches() == 3
        assert cfg.get_support_strong_touches() == 5
        assert cfg.get_support_moderate_touches() == 4


# ---------------------------------------------------------------------------
# Singleton Tests
# ---------------------------------------------------------------------------


class TestSingleton:
    """Test singleton pattern."""

    def test_singleton_returns_same_instance(self):
        """get_scanner_config() returns the same instance."""
        cfg1 = get_scanner_config()
        cfg2 = get_scanner_config()
        assert cfg1 is cfg2

    def test_reset_clears_singleton(self):
        """reset_scanner_config() clears the singleton."""
        cfg1 = get_scanner_config()
        reset_scanner_config()
        cfg2 = get_scanner_config()
        assert cfg1 is not cfg2


# ---------------------------------------------------------------------------
# Integration: RSI Tier parsing
# ---------------------------------------------------------------------------


class TestRSITierParsing:
    """Test RSI tier data class and sorting."""

    def test_tiers_sorted_descending(self, config):
        """Tiers should be sorted by min_stability descending."""
        tiers = config._rsi_tiers
        assert len(tiers) == 4
        assert tiers[0].min_stability >= tiers[1].min_stability
        assert tiers[1].min_stability >= tiers[2].min_stability
        assert tiers[2].min_stability >= tiers[3].min_stability

    def test_tier_names(self, config):
        """All tiers should have names."""
        names = [t.name for t in config._rsi_tiers]
        assert "high_stability" in names
        assert "very_low_stability" in names


# ---------------------------------------------------------------------------
# Production config validation
# ---------------------------------------------------------------------------


class TestProductionConfig:
    """Validate the actual production config files."""

    def test_production_rsi_config_loads(self):
        """Production rsi_thresholds.yaml loads correctly."""
        prod_path = Path(__file__).resolve().parents[2] / "config" / "rsi_thresholds.yaml"
        if not prod_path.exists():
            pytest.skip("Production config not found")

        cfg = ScannerConfig(rsi_config_path=prod_path)
        # Should have 4 tiers
        assert len(cfg._rsi_tiers) == 4
        # High stability threshold should be 50 (adaptive thresholds)
        assert cfg.get_rsi_neutral_threshold(90) == 50

    def test_production_scanner_config_loads(self):
        """Production scanner_config.yaml loads correctly."""
        prod_path = Path(__file__).resolve().parents[2] / "config" / "scanner_config.yaml"
        if not prod_path.exists():
            pytest.skip("Production config not found")

        cfg = ScannerConfig(scanner_config_path=prod_path)
        assert cfg.get_earnings_buffer_days() == 30
        assert cfg.get_support_min_touches() == 2

    def test_production_rsi_thresholds_are_descending(self):
        """Production RSI thresholds must be descending with stability."""
        prod_path = Path(__file__).resolve().parents[2] / "config" / "rsi_thresholds.yaml"
        if not prod_path.exists():
            pytest.skip("Production config not found")

        cfg = ScannerConfig(rsi_config_path=prod_path)
        thresholds = [cfg.get_rsi_neutral_threshold(s) for s in [90, 75, 65, 50]]
        # Higher stability should have higher (or equal) threshold
        for i in range(len(thresholds) - 1):
            assert thresholds[i] >= thresholds[i + 1], (
                f"Threshold for higher stability ({thresholds[i]}) "
                f"should be >= lower stability ({thresholds[i + 1]})"
            )
