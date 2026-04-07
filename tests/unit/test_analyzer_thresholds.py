# Tests for Analyzer Thresholds Config Loader
# =============================================
"""
Tests for the centralized analyzer thresholds configuration.
Validates that pullback and bounce strategy analyzers load scoring parameters
from config/analyzer_thresholds.yaml correctly.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.config.analyzer_thresholds import (
    AnalyzerThresholdsConfig,
    get_analyzer_thresholds,
    reset_analyzer_thresholds,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset singleton before each test."""
    reset_analyzer_thresholds()
    yield
    reset_analyzer_thresholds()


@pytest.fixture
def config_path(tmp_path):
    """Create a temporary analyzer thresholds config."""
    config = {
        "pullback": {
            "signal": {"strong": 8.0, "moderate": 6.0, "min_normalized_score": 4.0},
            "divergence": {"strong_threshold": 0.8, "moderate_threshold": 0.5},
            "divergence_scoring": {"strong_pts": 4.0, "moderate_pts": 2.5, "weak_pts": 1.5},
            "vwap": {"strong_above_pts": 3.5, "above_pts": 2.5, "near_pts": 1.5},
        },
        "bounce": {
            "general": {"min_score": 4.0, "max_score": 11.0},
            "signal": {"strong": 7.5, "moderate": 5.5},
            "support_quality": {"touches_strong": 6, "score_strong": 2.5},
            "proximity": {"tier1_pct": 1.5, "score_at": 2.5},
        },
    }
    path = tmp_path / "scoring.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


@pytest.fixture
def cfg(config_path):
    """Create config from test YAML."""
    return AnalyzerThresholdsConfig(config_path)


# ---------------------------------------------------------------------------
# Basic Loader Tests
# ---------------------------------------------------------------------------


class TestBasicLoading:
    """Test basic config loading functionality."""

    def test_loads_from_file(self, cfg):
        """Config loads values from YAML file."""
        assert cfg.get("bounce.general.min_score") == 4.0

    def test_missing_file_uses_defaults(self):
        """Missing config file falls back to defaults."""
        cfg = AnalyzerThresholdsConfig(Path("/nonexistent/config.yaml"))
        # All values should return their defaults
        assert cfg.get("bounce.signal.strong", 7.0) == 7.0

    def test_dot_path_access(self, cfg):
        """Dot-path access navigates nested YAML."""
        assert cfg.get("pullback.signal.strong") == 8.0
        assert cfg.get("pullback.divergence.strong_threshold") == 0.8

    def test_default_on_missing_key(self, cfg):
        """Missing key returns provided default."""
        assert cfg.get("pullback.nonexistent.key", 42.0) == 42.0
        assert cfg.get("nonexistent_strategy.key", "default") == "default"

    def test_default_on_none_value(self, cfg):
        """None value returns provided default."""
        assert cfg.get("pullback.nonexistent", 5.0) == 5.0

    def test_get_section(self, cfg):
        """get_section returns full dict."""
        section = cfg.get_section("pullback.signal")
        assert isinstance(section, dict)
        assert section["strong"] == 8.0
        assert section["moderate"] == 6.0

    def test_get_section_missing(self, cfg):
        """get_section returns empty dict for missing path."""
        assert cfg.get_section("nonexistent.section") == {}


# ---------------------------------------------------------------------------
# Pullback Strategy Tests
# ---------------------------------------------------------------------------


class TestPullbackConfig:
    """Test pullback-specific config values."""

    def test_signal_thresholds(self, cfg):
        assert cfg.get("pullback.signal.strong") == 8.0
        assert cfg.get("pullback.signal.moderate") == 6.0
        assert cfg.get("pullback.signal.min_normalized_score") == 4.0

    def test_divergence(self, cfg):
        assert cfg.get("pullback.divergence.strong_threshold") == 0.8
        assert cfg.get("pullback.divergence_scoring.strong_pts") == 4.0

    def test_vwap(self, cfg):
        assert cfg.get("pullback.vwap.strong_above_pts") == 3.5


# ---------------------------------------------------------------------------
# Bounce Strategy Tests
# ---------------------------------------------------------------------------


class TestBounceConfig:
    """Test bounce-specific config values."""

    def test_general(self, cfg):
        assert cfg.get("bounce.general.min_score") == 4.0
        assert cfg.get("bounce.general.max_score") == 11.0

    def test_support_quality(self, cfg):
        assert cfg.get("bounce.support_quality.touches_strong") == 6
        assert cfg.get("bounce.support_quality.score_strong") == 2.5

    def test_proximity(self, cfg):
        assert cfg.get("bounce.proximity.tier1_pct") == 1.5
        assert cfg.get("bounce.proximity.score_at") == 2.5


# ---------------------------------------------------------------------------
# Singleton Tests
# ---------------------------------------------------------------------------


class TestSingleton:
    """Test singleton pattern."""

    def test_returns_same_instance(self):
        cfg1 = get_analyzer_thresholds()
        cfg2 = get_analyzer_thresholds()
        assert cfg1 is cfg2

    def test_reset_clears_singleton(self):
        cfg1 = get_analyzer_thresholds()
        reset_analyzer_thresholds()
        cfg2 = get_analyzer_thresholds()
        assert cfg1 is not cfg2


# ---------------------------------------------------------------------------
# Production Config Validation
# ---------------------------------------------------------------------------


class TestProductionConfig:
    """Validate the actual production config file."""

    def test_production_config_loads(self):
        """Production analyzer_thresholds.yaml loads without errors."""
        prod_path = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"
        if not prod_path.exists():
            pytest.skip("Production config not found")

        cfg = AnalyzerThresholdsConfig(prod_path)
        # Spot-check values from each strategy
        assert cfg.get("bounce.signal.strong") == 7.0
        assert cfg.get("pullback.signal.strong") == 7.0

    def test_all_strategies_present(self):
        """Pullback and bounce strategies have sections in production config."""
        prod_path = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"
        if not prod_path.exists():
            pytest.skip("Production config not found")

        cfg = AnalyzerThresholdsConfig(prod_path)
        for strategy in ["pullback", "bounce"]:
            section = cfg.get_section(strategy)
            assert len(section) > 0, f"Strategy {strategy} missing from config"

    def test_production_bounce_has_all_sections(self):
        """Bounce strategy has all required scoring sections."""
        prod_path = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"
        if not prod_path.exists():
            pytest.skip("Production config not found")

        cfg = AnalyzerThresholdsConfig(prod_path)
        required_sections = [
            "bounce.general",
            "bounce.signal",
            "bounce.support_quality",
            "bounce.proximity",
            "bounce.volume",
            "bounce.trend",
            "bounce.confirmation",
            "bounce.candlestick",
        ]
        for section_path in required_sections:
            section = cfg.get_section(section_path)
            assert len(section) > 0, f"Section {section_path} missing or empty"

# ---------------------------------------------------------------------------
# Analyzer Integration Tests
# ---------------------------------------------------------------------------


class TestAnalyzerIntegration:
    """Test that analyzers correctly load from config."""

    def test_bounce_constants_match_config(self):
        """Bounce module-level constants match production YAML."""
        from src.analyzers.bounce import (
            BOUNCE_MIN_SCORE,
            BOUNCE_SIGNAL_STRONG,
            BOUNCE_SUPPORT_TOUCHES_STRONG,
        )

        assert BOUNCE_MIN_SCORE == 3.5
        assert BOUNCE_SIGNAL_STRONG == 7.0
        assert BOUNCE_SUPPORT_TOUCHES_STRONG == 5

    def test_pullback_constants_match_config(self):
        """Pullback module-level constants match production YAML."""
        from src.analyzers.pullback import PULLBACK_SIGNAL_STRONG
        from src.analyzers.pullback_scoring import (
            SCORE_DIVERGENCE_STRONG,
            SCORE_MARKET_STRONG_UPTREND,
        )

        assert PULLBACK_SIGNAL_STRONG == 7.0
        assert SCORE_DIVERGENCE_STRONG == 0.7
        assert SCORE_MARKET_STRONG_UPTREND == 2.0

