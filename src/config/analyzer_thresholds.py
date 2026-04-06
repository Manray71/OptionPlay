# OptionPlay - Analyzer Thresholds Config Loader
# ================================================
"""
Loads scoring parameters for all 5 strategy analyzers from YAML.
Replaces ~100 hardcoded module-level constants with config-driven values.

Config file: config/analyzer_thresholds.yaml

Usage:
    from src.config.analyzer_thresholds import get_analyzer_thresholds

    cfg = get_analyzer_thresholds()
    score = cfg.get("bounce.proximity.tier1_pct", 1.0)
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_DEFAULT_PATH = _CONFIG_DIR / "analyzer_thresholds.yaml"


class AnalyzerThresholdsConfig:
    """
    Thread-safe config loader for analyzer scoring parameters.

    Provides dot-path access to nested YAML values with fallback defaults.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._data: dict = {}
        path = config_path or _DEFAULT_PATH
        if path.exists():
            with open(path) as f:
                self._data = yaml.safe_load(f) or {}
            logger.info("Analyzer thresholds loaded from %s", path)
        else:
            logger.warning("Analyzer thresholds config not found at %s, using defaults", path)

    def get(self, dotpath: str, default: Any = None) -> Any:
        """
        Get a config value by dot-separated path.

        Example:
            cfg.get("bounce.proximity.tier1_pct", 1.0)
            → data["bounce"]["proximity"]["tier1_pct"]

        Falls back to *default* if any key is missing.
        """
        keys = dotpath.split(".")
        node = self._data
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key)
                if node is None:
                    return default
            else:
                return default
        return node if node is not None else default

    def get_section(self, dotpath: str) -> dict:
        """
        Get a full section as a dict.

        Example:
            cfg.get_section("bounce.proximity")
            → {"tier1_pct": 1.0, "tier2_pct": 2.0, ...}
        """
        keys = dotpath.split(".")
        node = self._data
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key, {})
            else:
                return {}
        return node if isinstance(node, dict) else {}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_instance: Optional[AnalyzerThresholdsConfig] = None


def get_analyzer_thresholds(
    config_path: Optional[Path] = None,
) -> AnalyzerThresholdsConfig:
    """Return (or create) the singleton AnalyzerThresholdsConfig instance.

    Prefers the global ServiceContainer if available.
    """
    # Prefer container if available
    try:
        from ..container import _default_container

        if _default_container is not None and _default_container.analyzer_thresholds is not None:
            return _default_container.analyzer_thresholds
    except ImportError:
        pass

    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AnalyzerThresholdsConfig(config_path)
    return _instance


def reset_analyzer_thresholds() -> None:
    """Reset singleton (for testing)."""
    global _instance
    _instance = None
    # Also clear container slot so getter creates fresh instance
    try:
        from ..container import _default_container

        if _default_container is not None:
            _default_container.analyzer_thresholds = None
    except ImportError:
        pass
