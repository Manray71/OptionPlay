# OptionPlay - Scanner Config Loader
# ====================================
"""
Centralizes loading of scanner configuration from YAML files.
Replaces hardcoded RSI thresholds, earnings buffer, and support bounce
parameters with config-driven adaptive values.

Config files:
  - config/rsi_thresholds.yaml   — Stability-adaptive RSI thresholds
  - config/scanner_config.yaml   — Earnings buffer, support bounce settings

Usage:
    from src.utils.scanner_config_loader import get_scanner_config

    cfg = get_scanner_config()
    threshold = cfg.get_rsi_neutral_threshold(stability_score=85)  # → 42
    buffer = cfg.get_earnings_buffer_days()                        # → 30
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_RSI_CONFIG_PATH = _CONFIG_DIR / "rsi_thresholds.yaml"
_SCANNER_CONFIG_PATH = _CONFIG_DIR / "scanner_config.yaml"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RSITier:
    """A single RSI threshold tier."""

    name: str
    min_stability: float
    neutral_threshold: int


# ---------------------------------------------------------------------------
# ScannerConfig
# ---------------------------------------------------------------------------


class ScannerConfig:
    """
    Thread-safe config loader for scanner parameters.

    Loads RSI thresholds and scanner settings from YAML config files.
    Falls back to sensible defaults if config files are missing.
    """

    def __init__(
        self,
        rsi_config_path: Optional[Path] = None,
        scanner_config_path: Optional[Path] = None,
    ) -> None:
        self._rsi_data: Dict[str, Any] = {}
        self._scanner_data: Dict[str, Any] = {}
        self._rsi_tiers: List[RSITier] = []

        # Load RSI thresholds
        rsi_path = rsi_config_path or _RSI_CONFIG_PATH
        if rsi_path.exists():
            with open(rsi_path) as f:
                self._rsi_data = yaml.safe_load(f) or {}
            self._parse_rsi_tiers()
            logger.info("RSI thresholds config loaded from %s", rsi_path)
        else:
            logger.warning("RSI config not found at %s, using defaults", rsi_path)
            self._set_default_rsi_tiers()

        # Load scanner config
        scanner_path = scanner_config_path or _SCANNER_CONFIG_PATH
        if scanner_path.exists():
            with open(scanner_path) as f:
                self._scanner_data = yaml.safe_load(f) or {}
            logger.info("Scanner config loaded from %s", scanner_path)
        else:
            logger.warning("Scanner config not found at %s, using defaults", scanner_path)

    # -- RSI thresholds -------------------------------------------------------

    def _parse_rsi_tiers(self) -> None:
        """Parse RSI tiers from loaded YAML data."""
        tiers_data = self._rsi_data.get("rsi_thresholds", {}).get("tiers", [])
        self._rsi_tiers = []
        for tier in tiers_data:
            self._rsi_tiers.append(
                RSITier(
                    name=tier["name"],
                    min_stability=float(tier["min_stability"]),
                    neutral_threshold=int(tier["neutral_threshold"]),
                )
            )
        # Sort descending by min_stability so we check highest first
        self._rsi_tiers.sort(key=lambda t: t.min_stability, reverse=True)

        if not self._rsi_tiers:
            self._set_default_rsi_tiers()

    def _set_default_rsi_tiers(self) -> None:
        """Fallback defaults matching original hardcoded behavior."""
        self._rsi_tiers = [
            RSITier("high_stability", 85, 42),
            RSITier("medium_stability", 70, 40),
            RSITier("low_stability", 60, 38),
            RSITier("very_low_stability", 0, 35),
        ]

    def get_rsi_neutral_threshold(self, stability_score: float) -> int:
        """
        Get adaptive RSI neutral threshold based on stability score.

        Higher stability → higher threshold (more permissive for pullbacks).

        Args:
            stability_score: Stock stability score (0-100)

        Returns:
            RSI neutral threshold (e.g. 42 for high stability)
        """
        for tier in self._rsi_tiers:
            if stability_score >= tier.min_stability:
                return tier.neutral_threshold
        # Fallback: lowest tier
        return self._rsi_tiers[-1].neutral_threshold if self._rsi_tiers else 50

    def get_rsi_scoring_config(self) -> Dict[str, Any]:
        """Get RSI scoring adjustments (severe_oversold, overbought penalties)."""
        return self._rsi_data.get("rsi_thresholds", {}).get("scoring", {})

    # -- Earnings buffer ------------------------------------------------------

    def get_earnings_buffer_days(self, mode: Optional[str] = None) -> int:
        """
        Get earnings buffer in days.

        Args:
            mode: 'conservative' (45), 'standard' (30), 'aggressive' (20).
                  If None, uses current_mode from config.

        Returns:
            Number of days before earnings to exclude.
        """
        earnings_cfg = self._scanner_data.get("scanner", {}).get("earnings_buffer", {})
        if not earnings_cfg:
            return 30  # Default: standard mode

        mode = mode or earnings_cfg.get("current_mode", "standard")
        return int(earnings_cfg.get(mode, 30))

    # -- Support bounce -------------------------------------------------------

    def get_support_min_touches(self) -> int:
        """Get minimum support touches required for bounce signal."""
        bounce_cfg = self._scanner_data.get("scanner", {}).get("support_bounce", {})
        return int(bounce_cfg.get("min_touches", 3))

    def get_support_strong_touches(self) -> int:
        """Get touch count for 'strong' support classification."""
        bounce_cfg = self._scanner_data.get("scanner", {}).get("support_bounce", {})
        return int(bounce_cfg.get("strong_touches", 5))

    def get_support_moderate_touches(self) -> int:
        """Get touch count for 'moderate' support classification."""
        bounce_cfg = self._scanner_data.get("scanner", {}).get("support_bounce", {})
        return int(bounce_cfg.get("moderate_touches", 4))

    # -- Stability tiers ------------------------------------------------------

    def get_stability_tiers(self) -> Dict[str, Any]:
        """Get stability-first filtering tier thresholds and min scores."""
        return self._scanner_data.get("scanner", {}).get(
            "stability_tiers",
            {
                "qualified": {"threshold": 60.0, "min_score": 3.5},
            },
        )

    def get_stability_boost(self) -> Dict[str, Any]:
        """Get legacy stability boost parameters."""
        return self._scanner_data.get("scanner", {}).get(
            "stability_boost",
            {
                "threshold": 70.0,
                "amount": 1.0,
                "premium_multiplier": 0.5,
                "good_multiplier": 0.25,
                "premium_score": 80,
            },
        )

    # -- Win rate integration -------------------------------------------------

    def get_win_rate_config(self) -> Dict[str, float]:
        """Get win rate integration parameters."""
        return self._scanner_data.get("scanner", {}).get(
            "win_rate",
            {
                "base_multiplier": 0.7,
                "divisor": 300.0,
            },
        )

    # -- Drawdown penalty -----------------------------------------------------

    def get_drawdown_config(self) -> Dict[str, float]:
        """Get drawdown penalty parameters."""
        return self._scanner_data.get("scanner", {}).get(
            "drawdown",
            {
                "penalty_threshold": 10.0,
                "penalty_per_pct": 0.02,
                "max_penalty_pct": 0.3,
            },
        )

    # -- Fundamentals pre-filter ----------------------------------------------

    def get_fundamentals_prefilter(self) -> Dict[str, float]:
        """Get fundamentals pre-filter thresholds."""
        return self._scanner_data.get("scanner", {}).get(
            "fundamentals_prefilter",
            {
                "min_stability": 50.0,
                "min_win_rate": 65.0,
                "max_volatility": 70.0,
                "max_beta": 2.0,
                "iv_rank_min": 20.0,
            },
        )

    # -- Adjustment labels ----------------------------------------------------

    def get_adjustment_labels(self) -> Dict[str, Any]:
        """Get thresholds for human-readable adjustment reason labels."""
        return self._scanner_data.get("scanner", {}).get(
            "adjustment_labels",
            {
                "win_rate": {"excellent": 90, "very_good": 85, "low": 75},
                "drawdown": {"high": 15, "low": 5},
                "stability": {"very_stable": 80},
            },
        )

    # -- Output limits --------------------------------------------------------

    def get_output_config(self) -> Dict[str, int]:
        """Get scanner output limit parameters."""
        return self._scanner_data.get("scanner", {}).get(
            "output",
            {
                "max_results_per_symbol": 3,
                "max_total_results": 50,
                "max_symbol_appearances": 2,
                "min_data_points": 60,
                "pool_size_per_strategy": 5,
            },
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_instance: Optional[ScannerConfig] = None


def get_scanner_config(
    rsi_config_path: Optional[Path] = None,
    scanner_config_path: Optional[Path] = None,
) -> ScannerConfig:
    """Return (or create) the singleton ScannerConfig instance.

    Prefers the global ServiceContainer if available.
    """
    # Prefer container if available
    try:
        from ..container import _default_container

        if _default_container is not None and _default_container.scanner_config is not None:
            return _default_container.scanner_config
    except ImportError:
        pass

    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ScannerConfig(rsi_config_path, scanner_config_path)
    return _instance


def reset_scanner_config() -> None:
    """Reset singleton (for testing)."""
    global _instance
    _instance = None
    try:
        from ..container import _default_container

        if _default_container is not None:
            _default_container.scanner_config = None
    except ImportError:
        pass
