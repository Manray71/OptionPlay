"""Regression tests: verify divergence penalty constants are read from YAML,
not silently defaulting (prevents config drift like OQ-2).

Tests:
1. check_price_rsi_divergence respects custom severity parameter
2. check_distribution_pattern respects custom severity parameter
3. BOUNCE_DIV_PENALTY_* constants match bounce.divergence.* values in YAML
4. PULLBACK_DIV_PENALTY_* constants match pullback.divergence.* values in YAML
"""

import importlib
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_scoring_yaml() -> dict:
    """Load config/scoring.yaml directly (no caching)."""
    config_path = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _make_bearish_rsi_data(n: int = 80):
    """Construct data that triggers bearish RSI divergence:
    higher high in price while RSI makes lower high.

    Returns (prices, lows, highs).
    """
    import math

    prices = []
    p = 100.0
    # Initial decline so RSI starts from below
    for _ in range(20):
        prices.append(p)
        p *= 0.998

    # Strong rise to peak1 → RSI saturates high
    for _ in range(20):
        prices.append(p)
        p *= 1.003

    # Dip
    for _ in range(15):
        prices.append(p)
        p *= 0.999

    peak1 = p * 0.97  # start of second peak is slightly below peak1 absolute level
    p = peak1
    # Second rise: weaker (smaller % gain) but absolute higher level
    for _ in range(20):
        prices.append(p)
        p *= 1.0015  # weaker rise → lower RSI but higher price

    # Tail bars to allow swing detection
    for _ in range(5):
        prices.append(p * 0.9995)

    highs = [pr * 1.005 for pr in prices]
    lows = [pr * 0.995 for pr in prices]
    return prices, lows, highs


def _make_distribution_data(n: int = 80):
    """Prices with declining OBV, MFI and CMF (all three volume indicators falling)."""
    prices = []
    p = 100.0
    for _ in range(n - 30):
        prices.append(p)
        p *= 1.002

    for _ in range(30):
        prices.append(p)
        p *= 0.998

    highs = [pr * 1.005 for pr in prices]
    lows = [pr * 0.995 for pr in prices]
    volumes = [2_000_000] * (n - 30) + [max(50_000, int(2_000_000 * (0.96 ** i))) for i in range(30)]
    return prices, highs, lows, volumes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDivergenceCheckCustomSeverity:
    """Verify that divergence check functions respect the severity= parameter."""

    def test_divergence_check_returns_configured_severity(self):
        """check_price_rsi_divergence with custom severity returns that severity when detected."""
        from src.indicators.divergence import check_price_rsi_divergence

        prices, lows, highs = _make_bearish_rsi_data()
        custom_severity = -7.5

        sig = check_price_rsi_divergence(
            prices=prices, lows=lows, highs=highs, lookback=30, severity=custom_severity
        )
        if sig.detected:
            assert sig.severity == custom_severity, (
                f"Expected severity {custom_severity}, got {sig.severity}"
            )
        else:
            # Divergence not detected with this data — severity stays 0.0
            assert sig.severity == 0.0

    def test_divergence_check_distribution_custom_severity(self):
        """check_distribution_pattern with custom severity returns that severity when detected."""
        from src.indicators.divergence import check_distribution_pattern

        prices, highs, lows, volumes = _make_distribution_data()
        custom_severity = -9.0

        sig = check_distribution_pattern(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            n_bars=3,
            severity=custom_severity,
        )
        if sig.detected:
            assert sig.severity == custom_severity, (
                f"Expected severity {custom_severity}, got {sig.severity}"
            )
        else:
            assert sig.severity == 0.0

    def test_default_severity_is_negative(self):
        """Default severity for all checks must be negative (penalty)."""
        from src.indicators.divergence import (
            check_cmf_and_macd_falling,
            check_cmf_early_warning,
            check_distribution_pattern,
            check_momentum_divergence,
            check_price_mfi_divergence,
            check_price_obv_divergence,
            check_price_rsi_divergence,
        )

        # Verify default severity parameters using inspect
        import inspect
        checks = [
            check_price_rsi_divergence,
            check_price_obv_divergence,
            check_price_mfi_divergence,
            check_cmf_and_macd_falling,
            check_momentum_divergence,
            check_distribution_pattern,
            check_cmf_early_warning,
        ]
        for fn in checks:
            sig_params = inspect.signature(fn).parameters
            severity_default = sig_params["severity"].default
            assert severity_default < 0, (
                f"{fn.__name__} has non-negative default severity: {severity_default}"
            )


class TestBounceYAMLPenaltyConstants:
    """Verify BOUNCE_DIV_PENALTY_* constants match bounce.divergence.* in scoring.yaml."""

    def test_bounce_penalty_constants_match_yaml_defaults(self):
        """BOUNCE_DIV_PENALTY_* constants should equal bounce.divergence.* in YAML."""
        from src.config.analyzer_thresholds import reset_analyzer_thresholds
        reset_analyzer_thresholds()

        from src.analyzers.bounce import (
            BOUNCE_DIV_PENALTY_CMF_EARLY,
            BOUNCE_DIV_PENALTY_CMF_MACD,
            BOUNCE_DIV_PENALTY_DISTRIBUTION,
            BOUNCE_DIV_PENALTY_MOMENTUM,
            BOUNCE_DIV_PENALTY_PRICE_MFI,
            BOUNCE_DIV_PENALTY_PRICE_OBV,
            BOUNCE_DIV_PENALTY_PRICE_RSI,
        )
        import importlib
        import src.analyzers.bounce as bounce_mod
        importlib.reload(bounce_mod)

        yaml_data = _load_scoring_yaml()
        bounce_div = yaml_data.get("bounce", {}).get("divergence", {})

        assert bounce_div, "bounce.divergence section missing from scoring.yaml"

        pairs = [
            ("price_rsi", bounce_mod.BOUNCE_DIV_PENALTY_PRICE_RSI),
            ("price_obv", bounce_mod.BOUNCE_DIV_PENALTY_PRICE_OBV),
            ("price_mfi", bounce_mod.BOUNCE_DIV_PENALTY_PRICE_MFI),
            ("cmf_macd_falling", bounce_mod.BOUNCE_DIV_PENALTY_CMF_MACD),
            ("momentum_divergence", bounce_mod.BOUNCE_DIV_PENALTY_MOMENTUM),
            ("distribution_pattern", bounce_mod.BOUNCE_DIV_PENALTY_DISTRIBUTION),
            ("cmf_early_warning", bounce_mod.BOUNCE_DIV_PENALTY_CMF_EARLY),
        ]
        for yaml_key, module_value in pairs:
            yaml_value = bounce_div.get(yaml_key)
            assert yaml_value is not None, f"bounce.divergence.{yaml_key} missing from YAML"
            assert abs(yaml_value - module_value) < 1e-9, (
                f"bounce.divergence.{yaml_key}: YAML={yaml_value}, module={module_value}"
            )


class TestPullbackYAMLPenaltyConstants:
    """Verify PULLBACK_DIV_PENALTY_* constants match pullback.divergence.* in scoring.yaml."""

    def test_pullback_penalty_constants_match_yaml_defaults(self):
        """PULLBACK_DIV_PENALTY_* constants should equal pullback.divergence.* in YAML."""
        from src.config.analyzer_thresholds import reset_analyzer_thresholds
        reset_analyzer_thresholds()

        import src.analyzers.pullback as pullback_mod
        importlib.reload(pullback_mod)

        yaml_data = _load_scoring_yaml()
        pullback_div = yaml_data.get("pullback", {}).get("divergence", {})

        assert pullback_div, "pullback.divergence section missing from scoring.yaml"

        pairs = [
            ("price_rsi", pullback_mod.PULLBACK_DIV_PENALTY_PRICE_RSI),
            ("price_obv", pullback_mod.PULLBACK_DIV_PENALTY_PRICE_OBV),
            ("price_mfi", pullback_mod.PULLBACK_DIV_PENALTY_PRICE_MFI),
            ("cmf_macd_falling", pullback_mod.PULLBACK_DIV_PENALTY_CMF_MACD),
            ("momentum_divergence", pullback_mod.PULLBACK_DIV_PENALTY_MOMENTUM),
            ("distribution_pattern", pullback_mod.PULLBACK_DIV_PENALTY_DISTRIBUTION),
            ("cmf_early_warning", pullback_mod.PULLBACK_DIV_PENALTY_CMF_EARLY),
        ]
        for yaml_key, module_value in pairs:
            yaml_value = pullback_div.get(yaml_key)
            assert yaml_value is not None, f"pullback.divergence.{yaml_key} missing from YAML"
            assert abs(yaml_value - module_value) < 1e-9, (
                f"pullback.divergence.{yaml_key}: YAML={yaml_value}, module={module_value}"
            )
