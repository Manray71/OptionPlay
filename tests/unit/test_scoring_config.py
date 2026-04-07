# Tests for RecursiveConfigResolver (Schritt 4)
import os
import threading
import pytest
import yaml

from src.config.scoring_config import (
    RecursiveConfigResolver,
    ResolvedWeights,
    _deep_merge,
    get_scoring_resolver,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before and after each test."""
    RecursiveConfigResolver.reset()
    yield
    RecursiveConfigResolver.reset()


@pytest.fixture
def sample_yaml(tmp_path):
    """Create a sample scoring_weights.yaml for testing."""
    config = {
        "version": "1.0.0",
        "defaults": {"min_stability": 70},
        "strategies": {
            "pullback": {
                "weights": {
                    "rsi": 3.0,
                    "support": 2.5,
                    "fibonacci": 2.0,
                    "macd": 2.0,
                    "vwap": 3.0,
                },
                "max_possible": 14.0,
                "regimes": {
                    "low": {},
                    "normal": {},
                    "danger": {
                        "min_stability": 80,
                        "weights": {"rsi": 4.0},
                    },
                    "elevated": {"min_stability": 80},
                },
                "sectors": {
                    "Technology": {
                        "weights": {"vwap": 2.0},
                    },
                    "danger:Technology": {
                        "weights": {"rsi": 5.0, "vwap": 1.5},
                        "min_stability": 90,
                    },
                },
            },
            "bounce": {
                "weights": {
                    "support_test": 3.0,
                    "rsi": 2.0,
                    "vwap": 3.0,
                },
                "max_possible": 14.0,
                "regimes": {
                    "danger": {"min_stability": 85},
                },
                "sectors": {},
            },
        },
        "stability_thresholds": {
            "by_regime": {
                "low": 70,
                "normal": 70,
                "danger": 80,
                "elevated": 80,
                "high": 999,
            },
            "by_sector": {
                "Technology": 5,
                "Healthcare": -5,
            },
        },
        "sector_momentum": {
            "enabled": True,
            "cache_ttl_hours": 4,
        },
        "parallelization": {
            "sector_batch_size": 11,
            "scan_concurrency": 50,
        },
    }
    yaml_path = tmp_path / "scoring_weights.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    return str(yaml_path)


# ======================================================================
# Basic Resolution Tests
# ======================================================================


class TestBasicResolution:
    def test_base_weights_loaded(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w = r.resolve("pullback", "normal")
        assert w.weights["rsi"] == 3.0
        assert w.weights["support"] == 2.5
        assert w.max_possible == 14.0

    def test_default_stability(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w = r.resolve("pullback", "normal")
        assert w.min_stability == 70

    def test_regime_override_merges_not_replaces(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w = r.resolve("pullback", "danger")
        # rsi overridden by danger regime
        assert w.weights["rsi"] == 4.0
        # support inherited from base
        assert w.weights["support"] == 2.5
        assert w.min_stability == 80

    def test_sector_override_merges(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w = r.resolve("pullback", "normal", "Technology")
        # vwap overridden by Technology sector
        assert w.weights["vwap"] == 2.0
        # rsi inherited from base
        assert w.weights["rsi"] == 3.0

    def test_4_layer_resolution_regime_x_sector(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w = r.resolve("pullback", "danger", "Technology")
        # rsi: base=3 → danger=4 → danger:Technology=5
        assert w.weights["rsi"] == 5.0
        # vwap: base=3 → Technology=2 → danger:Technology=1.5
        assert w.weights["vwap"] == 1.5
        # support: inherited from base
        assert w.weights["support"] == 2.5
        # stability: danger=80 → danger:Technology=90
        assert w.min_stability == 90

    def test_empty_regime_inherits_everything(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        base = r.resolve("pullback", "normal")
        low = r.resolve("pullback", "low")
        assert base.weights == low.weights
        assert base.min_stability == low.min_stability


# ======================================================================
# Stability Thresholds
# ======================================================================


class TestStabilityThresholds:
    def test_regime_stability(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        assert r.get_stability_threshold("normal") == 70
        assert r.get_stability_threshold("danger") == 80
        assert r.get_stability_threshold("high") == 999

    def test_sector_adjustment_additive(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        # danger(80) + Technology(+5) = 85
        assert r.get_stability_threshold("danger", "Technology") == 85
        # normal(70) + Healthcare(-5) = 65
        assert r.get_stability_threshold("normal", "Healthcare") == 65


# ======================================================================
# Caching
# ======================================================================


class TestCaching:
    def test_same_call_returns_same_id(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w1 = r.resolve("pullback", "normal")
        w2 = r.resolve("pullback", "normal")
        assert w1 is w2

    def test_different_calls_different_objects(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w1 = r.resolve("pullback", "normal")
        w2 = r.resolve("pullback", "danger")
        assert w1 is not w2

    def test_reload_clears_cache(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w1 = r.resolve("pullback", "normal")
        r.reload()
        w2 = r.resolve("pullback", "normal")
        assert w1 is not w2
        # But values are the same
        assert w1.weights == w2.weights


# ======================================================================
# Thread Safety
# ======================================================================


class TestThreadSafety:
    def test_concurrent_resolve(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        results = [None] * 10
        errors = []

        def worker(idx):
            try:
                w = r.resolve("pullback", "danger", "Technology")
                results[idx] = w
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All should resolve to the same cached object
        first = results[0]
        for w in results[1:]:
            assert w.weights == first.weights
            assert w.min_stability == first.min_stability


# ======================================================================
# NumPy Integration
# ======================================================================


class TestNumpyArray:
    def test_as_numpy_array_correct_order(self, sample_yaml):
        np = pytest.importorskip("numpy")
        r = RecursiveConfigResolver(sample_yaml)
        w = r.resolve("pullback", "normal")
        order = ["rsi", "support", "fibonacci", "macd", "vwap"]
        arr = w.as_numpy_array(order)
        assert arr.shape == (5,)
        assert arr[0] == 3.0  # rsi
        assert arr[1] == 2.5  # support
        assert arr[4] == 3.0  # vwap

    def test_missing_component_defaults_to_zero(self, sample_yaml):
        np = pytest.importorskip("numpy")
        r = RecursiveConfigResolver(sample_yaml)
        w = r.resolve("pullback", "normal")
        arr = w.as_numpy_array(["rsi", "nonexistent_component"])
        assert arr[0] == 3.0
        assert arr[1] == 0.0


# ======================================================================
# Deep Merge
# ======================================================================


class TestDeepMerge:
    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"weights": {"rsi": 3.0, "support": 2.5}, "max": 26}
        override = {"weights": {"rsi": 4.0}, "min_stability": 80}
        result = _deep_merge(base, override)
        assert result["weights"]["rsi"] == 4.0
        assert result["weights"]["support"] == 2.5
        assert result["max"] == 26
        assert result["min_stability"] == 80

    def test_deeply_nested_merge(self):
        base = {"a": {"b": {"c": 1, "d": 2}, "e": 3}}
        override = {"a": {"b": {"c": 10}}}
        result = _deep_merge(base, override)
        assert result["a"]["b"]["c"] == 10
        assert result["a"]["b"]["d"] == 2
        assert result["a"]["e"] == 3


# ======================================================================
# Missing YAML / Fallback
# ======================================================================


class TestFallback:
    def test_missing_yaml_uses_fallback(self, tmp_path):
        fake_path = str(tmp_path / "nonexistent.yaml")
        r = RecursiveConfigResolver(fake_path)
        w = r.resolve("pullback", "normal")
        # Should use hardcoded fallback
        assert w.weights["rsi"] == 3.0
        assert w.max_possible == 14.0

    def test_fallback_strategies_have_weights(self, tmp_path):
        fake_path = str(tmp_path / "nonexistent.yaml")
        r = RecursiveConfigResolver(fake_path)
        for strategy in r.list_strategies():
            w = r.resolve(strategy, "normal")
            assert len(w.weights) > 0, f"{strategy} has no weights"
            assert w.max_possible > 0, f"{strategy} has no max_possible"
            total = sum(w.weights.values())
            # Weights sum should be >= max_possible (some strategies have
            # components with negative min values, so max_possible can be
            # less than the theoretical positive sum)
            assert total >= w.max_possible * 0.8, (
                f"{strategy}: sum({total}) too low vs max_possible({w.max_possible})"
            )


# ======================================================================
# Other Config Accessors
# ======================================================================


class TestConfigAccessors:
    def test_sector_momentum_config(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        cfg = r.get_sector_momentum_config()
        assert cfg["enabled"] is True
        assert cfg["cache_ttl_hours"] == 4

    def test_parallelization_config(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        cfg = r.get_parallelization_config()
        assert cfg["sector_batch_size"] == 11
        assert cfg["scan_concurrency"] == 50

    def test_list_strategies(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        strats = r.list_strategies()
        assert "pullback" in strats
        assert "bounce" in strats
        # Fallbacks included even if not in YAML


# ======================================================================
# Singleton
# ======================================================================


class TestSingleton:
    def test_singleton_same_instance(self, sample_yaml):
        r1 = RecursiveConfigResolver(sample_yaml)
        r2 = RecursiveConfigResolver()
        assert r1 is r2

    def test_reset_creates_new_instance(self, sample_yaml):
        r1 = RecursiveConfigResolver(sample_yaml)
        RecursiveConfigResolver.reset()
        r2 = RecursiveConfigResolver(sample_yaml)
        assert r1 is not r2

    def test_get_scoring_resolver_convenience(self, sample_yaml):
        r = get_scoring_resolver(sample_yaml)
        assert isinstance(r, RecursiveConfigResolver)


# ======================================================================
# ResolvedWeights frozen
# ======================================================================


class TestResolvedWeightsFrozen:
    def test_frozen_dataclass(self, sample_yaml):
        r = RecursiveConfigResolver(sample_yaml)
        w = r.resolve("pullback", "normal")
        with pytest.raises(AttributeError):
            w.strategy = "changed"


# ======================================================================
# v3: Strategy-Specific Stability Thresholds
# ======================================================================


@pytest.fixture
def v3_yaml(tmp_path):
    """Create a v3 scoring_weights.yaml with strategy-specific thresholds."""
    config = {
        "version": "3.0.0",
        "defaults": {"min_stability": 70},
        "strategies": {
            "pullback": {
                "weights": {"rsi": 3.0, "support": 2.5},
                "max_possible": 14.0,
                "regimes": {},
                "sectors": {},
            },
        },
        "stability_thresholds": {
            "by_regime": {
                "low": 70, "normal": 70, "danger": 80,
                "elevated": 80, "high": 999,
            },
            "by_sector": {"Technology": 5, "Healthcare": -5},
            "by_strategy": {
                "pullback": {
                    "by_regime": {"low": 65, "normal": 70, "danger": 80, "elevated": 85, "high": 90},
                    "by_sector": {"Technology": 5, "Healthcare": -5},
                },
                "bounce": {
                    "by_regime": {"low": 60, "normal": 65, "danger": 75, "elevated": 80, "high": 85},
                    "by_sector": {"Technology": 3},
                },
            },
        },
        "sector_momentum": {
            "enabled": True,
            "cache_ttl_hours": 4,
            "factor_range": {"min": 0.6, "max": 1.2},
            "component_weights": {
                "relative_strength_30d": 0.40,
                "relative_strength_60d": 0.30,
                "breadth": 0.20,
                "vol_premium": 0.10,
            },
            "strategy_overrides": {
                "pullback": {
                    "factor_range": {"min": 0.60, "max": 1.20},
                    "component_weights": {
                        "relative_strength_30d": 0.45,
                        "relative_strength_60d": 0.25,
                        "breadth": 0.20,
                        "vol_premium": 0.10,
                    },
                },
            },
        },
        "training": {
            "strategy_configs": {
                "pullback": {
                    "walk_forward": {"train_months": 9, "validation_months": 2, "min_trades": 200},
                    "regularization": {"l2_lambda": 0.03, "max_weight_change": 0.25, "weight_bounds": [0.7, 4.0]},
                },
            },
        },
        "parallelization": {"sector_batch_size": 11, "strategy_parallel": True},
    }
    yaml_path = tmp_path / "scoring_weights_v3.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    return str(yaml_path)


class TestV3StrategyStability:
    """v3: Strategy-specific stability thresholds."""

    def test_strategy_specific_threshold(self, v3_yaml):
        r = RecursiveConfigResolver(v3_yaml)
        # Pullback normal = 70
        assert r.get_stability_threshold("normal", strategy="pullback") == 70
        # Bounce normal = 65 (lower than global 70)
        assert r.get_stability_threshold("normal", strategy="bounce") == 65

    def test_strategy_sector_adjustment(self, v3_yaml):
        r = RecursiveConfigResolver(v3_yaml)
        # Pullback danger(80) + Technology(+5) = 85
        assert r.get_stability_threshold("danger", "Technology", strategy="pullback") == 85
        # Bounce danger(75) + Technology(+3) = 78
        assert r.get_stability_threshold("danger", "Technology", strategy="bounce") == 78

    def test_fallback_to_global_when_no_strategy(self, v3_yaml):
        r = RecursiveConfigResolver(v3_yaml)
        # Without strategy → global fallback
        assert r.get_stability_threshold("normal") == 70
        assert r.get_stability_threshold("danger") == 80

    def test_fallback_to_global_for_unknown_strategy(self, v3_yaml):
        r = RecursiveConfigResolver(v3_yaml)
        # Unknown strategy → global fallback
        assert r.get_stability_threshold("normal", strategy="unknown_strategy") == 70


class TestV3SectorFactorConfig:
    """v3: Strategy-specific sector momentum configuration."""

    def test_global_fallback_without_strategy(self, v3_yaml):
        r = RecursiveConfigResolver(v3_yaml)
        fr, cw = r.get_sector_factor_config()
        assert fr["min"] == 0.6
        assert fr["max"] == 1.2

    def test_global_fallback_for_unknown_strategy(self, v3_yaml):
        r = RecursiveConfigResolver(v3_yaml)
        fr, _ = r.get_sector_factor_config("unknown_strategy")
        assert fr["min"] == 0.6
        assert fr["max"] == 1.2


class TestV3TrainingConfig:
    """v3: Per-strategy training configuration."""

    def test_get_training_config(self, v3_yaml):
        r = RecursiveConfigResolver(v3_yaml)
        cfg = r.get_training_config("pullback")
        assert cfg["walk_forward"]["train_months"] == 9
        assert cfg["regularization"]["l2_lambda"] == 0.03

    def test_missing_strategy_returns_empty(self, v3_yaml):
        r = RecursiveConfigResolver(v3_yaml)
        cfg = r.get_training_config("unknown_strategy")
        assert cfg == {}


# ======================================================================
# Sector Factor Integration (Iter 4)
# ======================================================================


@pytest.fixture
def sector_factor_yaml(tmp_path):
    """Create YAML with sector_factor values (Iter 4 trained)."""
    config = {
        "version": "3.1.0",
        "defaults": {"min_stability": 70},
        "strategies": {
            "pullback": {
                "weights": {"rsi": 3.0, "support": 2.5},
                "max_possible": 14.0,
                "regimes": {
                    "normal": {},
                    "danger": {"min_stability": 80},
                },
                "sectors": {
                    "Consumer Defensive": {"sector_factor": 1.126},
                    "Healthcare": {"sector_factor": 0.733},
                    "Technology": {
                        "sector_factor": 0.874,
                        "weights": {"rsi": 3.5},
                    },
                },
            },
        },
    }
    yaml_path = tmp_path / "scoring_weights_sf.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    return str(yaml_path)


class TestSectorFactor:
    """Tests for sector_factor extraction and application."""

    def test_sector_factor_extracted(self, sector_factor_yaml):
        r = RecursiveConfigResolver(sector_factor_yaml)
        w = r.resolve("pullback", "normal", "Consumer Defensive")
        assert w.sector_factor == 1.126

    def test_sector_factor_penalty(self, sector_factor_yaml):
        r = RecursiveConfigResolver(sector_factor_yaml)
        w = r.resolve("pullback", "normal", "Healthcare")
        assert w.sector_factor == 0.733

    def test_sector_factor_with_weights_override(self, sector_factor_yaml):
        """Sector with both sector_factor AND weights override."""
        r = RecursiveConfigResolver(sector_factor_yaml)
        w = r.resolve("pullback", "normal", "Technology")
        assert w.sector_factor == 0.874
        assert w.weights["rsi"] == 3.5  # Weight override applied
        assert w.weights["support"] == 2.5  # Inherited from base

    def test_sector_factor_default_no_sector(self, sector_factor_yaml):
        """No sector → sector_factor defaults to 1.0."""
        r = RecursiveConfigResolver(sector_factor_yaml)
        w = r.resolve("pullback", "normal")
        assert w.sector_factor == 1.0

    def test_sector_factor_default_unknown_sector(self, sector_factor_yaml):
        """Unknown sector → sector_factor defaults to 1.0."""
        r = RecursiveConfigResolver(sector_factor_yaml)
        w = r.resolve("pullback", "normal", "UnknownSector")
        assert w.sector_factor == 1.0

    def test_sector_factor_clamped_high(self, tmp_path):
        """sector_factor > 1.3 should be clamped."""
        config = {
            "strategies": {
                "pullback": {
                    "weights": {"rsi": 3.0},
                    "max_possible": 14.0,
                    "regimes": {},
                    "sectors": {"Extreme": {"sector_factor": 2.0}},
                }
            }
        }
        yaml_path = tmp_path / "test_clamp.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        r = RecursiveConfigResolver(str(yaml_path))
        w = r.resolve("pullback", "normal", "Extreme")
        assert w.sector_factor == 1.3

    def test_sector_factor_clamped_low(self, tmp_path):
        """sector_factor < 0.5 should be clamped."""
        config = {
            "strategies": {
                "pullback": {
                    "weights": {"rsi": 3.0},
                    "max_possible": 14.0,
                    "regimes": {},
                    "sectors": {"Terrible": {"sector_factor": 0.1}},
                }
            }
        }
        yaml_path = tmp_path / "test_clamp.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        r = RecursiveConfigResolver(str(yaml_path))
        w = r.resolve("pullback", "normal", "Terrible")
        assert w.sector_factor == 0.5

    def test_sector_factor_fallback_no_yaml(self, tmp_path):
        """Missing YAML → sector_factor defaults to 1.0."""
        fake_path = str(tmp_path / "nonexistent.yaml")
        r = RecursiveConfigResolver(fake_path)
        w = r.resolve("pullback", "normal", "Technology")
        assert w.sector_factor == 1.0


# ======================================================================
# Enabled + VIX Score Multiplier (Schritt 7)
# ======================================================================


@pytest.fixture
def vix_regime_yaml(tmp_path):
    """Create YAML with enabled and vix_score_multiplier fields."""
    config = {
        "version": "3.3.0",
        "defaults": {"min_stability": 70},
        "strategies": {
            "pullback": {
                "weights": {"rsi": 3.0, "support": 2.5},
                "max_possible": 14.0,
                "regimes": {
                    "low": {"vix_score_multiplier": 1.0},
                    "normal": {"vix_score_multiplier": 1.0},
                    "danger": {
                        "vix_score_multiplier": 0.95,
                        "min_stability": 80,
                    },
                    "elevated": {"vix_score_multiplier": 0.90},
                    "high": {"enabled": False},
                },
                "sectors": {},
            },
        },
    }
    yaml_path = tmp_path / "scoring_weights_vix.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)
    return str(yaml_path)


class TestVIXScoreMultiplier:
    """Tests for enabled and vix_score_multiplier fields on ResolvedWeights (Schritt 7)."""

    def test_enabled_default_true(self, vix_regime_yaml):
        """Without explicit enabled field, strategy is enabled."""
        r = RecursiveConfigResolver(vix_regime_yaml)
        w = r.resolve("pullback", "normal")
        assert w.enabled is True

    def test_enabled_false_high_regime(self, vix_regime_yaml):
        """enabled: false in high regime disables the strategy."""
        r = RecursiveConfigResolver(vix_regime_yaml)
        w = r.resolve("pullback", "high")
        assert w.enabled is False

    def test_vix_multiplier_default_1(self, vix_regime_yaml):
        """Without explicit multiplier, defaults to 1.0."""
        r = RecursiveConfigResolver(vix_regime_yaml)
        w = r.resolve("pullback", "low")
        assert w.vix_score_multiplier == 1.0

    def test_vix_multiplier_danger(self, vix_regime_yaml):
        r = RecursiveConfigResolver(vix_regime_yaml)
        w = r.resolve("pullback", "danger")
        assert w.vix_score_multiplier == 0.95

    def test_vix_multiplier_elevated(self, vix_regime_yaml):
        r = RecursiveConfigResolver(vix_regime_yaml)
        w = r.resolve("pullback", "elevated")
        assert w.vix_score_multiplier == 0.90

    def test_vix_multiplier_clamped_high(self, tmp_path):
        """vix_score_multiplier > 1.5 should be clamped."""
        config = {
            "strategies": {
                "pullback": {
                    "weights": {"rsi": 3.0},
                    "max_possible": 14.0,
                    "regimes": {"low": {"vix_score_multiplier": 2.5}},
                    "sectors": {},
                }
            }
        }
        yaml_path = tmp_path / "test_vix_clamp.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        r = RecursiveConfigResolver(str(yaml_path))
        w = r.resolve("pullback", "low")
        assert w.vix_score_multiplier == 1.5

    def test_vix_multiplier_clamped_low(self, tmp_path):
        """vix_score_multiplier < 0.0 should be clamped to 0.0."""
        config = {
            "strategies": {
                "pullback": {
                    "weights": {"rsi": 3.0},
                    "max_possible": 14.0,
                    "regimes": {"high": {"vix_score_multiplier": -0.5}},
                    "sectors": {},
                }
            }
        }
        yaml_path = tmp_path / "test_vix_clamp.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)
        r = RecursiveConfigResolver(str(yaml_path))
        w = r.resolve("pullback", "high")
        assert w.vix_score_multiplier == 0.0

    def test_enabled_and_multiplier_both_present(self, vix_regime_yaml):
        """Strategy can have both enabled: false and a multiplier."""
        r = RecursiveConfigResolver(vix_regime_yaml)
        w = r.resolve("pullback", "high")
        assert w.enabled is False
        # vix_score_multiplier defaults to 1.0 when not set
        assert w.vix_score_multiplier == 1.0

    def test_frozen_dataclass_new_fields(self, vix_regime_yaml):
        """New fields should be frozen like the rest."""
        r = RecursiveConfigResolver(vix_regime_yaml)
        w = r.resolve("pullback", "danger")
        with pytest.raises(AttributeError):
            w.enabled = False
        with pytest.raises(AttributeError):
            w.vix_score_multiplier = 0.5

    def test_fallback_no_yaml(self, tmp_path):
        """Missing YAML → enabled=True, vix_score_multiplier=1.0."""
        fake_path = str(tmp_path / "nonexistent.yaml")
        r = RecursiveConfigResolver(fake_path)
        w = r.resolve("pullback", "normal")
        assert w.enabled is True
        assert w.vix_score_multiplier == 1.0


class TestVIXMultiplierWithRealConfig:
    """Tests that verify the real scoring_weights.yaml has correct VIX config."""

    def test_all_strategies_have_high_disabled(self):
        """Pullback and bounce should have enabled: false in high regime."""
        r = RecursiveConfigResolver()
        for strategy in ["pullback", "bounce"]:
            w = r.resolve(strategy, "high")
            assert w.enabled is False, f"{strategy} should be disabled in high regime"
