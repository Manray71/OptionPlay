# OptionPlay - Configuration Core
# ================================
# Singleton und Convenience-Funktionen für Config-Zugriff
#
# Extrahiert aus config_loader.py im Rahmen des Recursive Logic Refactorings (Phase 2.2)

import logging
import os
import threading
from typing import TYPE_CHECKING, Optional

from .loader import ConfigLoader, find_config_dir
from .validation import ConfigValidationError

if TYPE_CHECKING:
    from ..scanner.multi_strategy_scanner import ScanConfig

logger = logging.getLogger(__name__)


# =============================================================================
# SINGLETON & A/B TEST MANAGEMENT
# =============================================================================

_config: Optional[ConfigLoader] = None
_config_lock = threading.Lock()

# A/B Test Weight Selection
# Set via environment variable or config
_ab_test_variant: str = os.environ.get(
    "OPTIONPLAY_AB_VARIANT", "A"
)  # "A" = feature-based, "B" = outcome-based


def set_ab_test_variant(variant: str) -> None:
    """
    Set the A/B test variant for weight selection.

    Args:
        variant: "A" for feature-based v3.7, "B" for outcome-based v3.8
    """
    global _ab_test_variant
    if variant not in ("A", "B"):
        raise ValueError(f"Invalid variant '{variant}'. Must be 'A' or 'B'.")
    _ab_test_variant = variant
    logger.info(f"A/B Test variant set to: {variant}")


def get_ab_test_variant() -> str:
    """Get current A/B test variant."""
    return _ab_test_variant


# =============================================================================
# SINGLETON ACCESS
# =============================================================================


def get_config(config_dir: Optional[str] = None) -> ConfigLoader:
    """
    Globaler Config-Zugriff (Singleton).

    .. deprecated:: 3.5.0
        Use ``ServiceContainer.config`` or pass config explicitly.
        Will be removed in v4.0.
    """
    from ..utils.deprecation import warn_singleton_usage

    warn_singleton_usage("get_config", "container.config")

    global _config
    with _config_lock:
        if _config is None:
            _config = ConfigLoader(config_dir)
            _config.set_ab_test_variant(_ab_test_variant)
            _config.load_all()
        return _config


def reset_config() -> None:
    """Setzt den Singleton zurück."""
    global _config
    with _config_lock:
        _config = None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def get_scan_config(
    config_dir: Optional[str] = None,
    override_min_score: Optional[float] = None,
    override_earnings_days: Optional[int] = None,
    override_iv_rank_min: Optional[float] = None,
    override_iv_rank_max: Optional[float] = None,
    enable_iv_filter: Optional[bool] = None,
    enable_fundamentals_filter: Optional[bool] = None,
) -> "ScanConfig":
    """
    Erstellt ScanConfig aus YAML-Konfiguration.

    Importiert ScanConfig aus multi_strategy_scanner, um circular imports zu vermeiden.

    Args:
        config_dir: Optionaler Pfad zum Config-Verzeichnis
        override_min_score: Überschreibt min_score aus Config
        override_earnings_days: Überschreibt exclude_earnings_within_days aus Config
        override_iv_rank_min: Überschreibt iv_rank_minimum aus Config
        override_iv_rank_max: Überschreibt iv_rank_maximum aus Config
        enable_iv_filter: Überschreibt enable_iv_filter aus Config
        enable_fundamentals_filter: Überschreibt enable_fundamentals_filter aus Config

    Returns:
        ScanConfig Instanz für MultiStrategyScanner

    Usage:
        from src.config import get_scan_config
        from src.scanner import MultiStrategyScanner

        scan_config = get_scan_config()
        scanner = MultiStrategyScanner(scan_config)
    """
    # Import hier, um circular imports zu vermeiden
    from ..scanner.multi_strategy_scanner import ScanConfig

    cfg = get_config(config_dir)
    scanner_cfg = cfg.settings.scanner
    filters_cfg = cfg.settings.filters
    fundamentals_cfg = filters_cfg.fundamentals

    return ScanConfig(
        min_score=override_min_score if override_min_score is not None else scanner_cfg.min_score,
        min_actionable_score=scanner_cfg.min_actionable_score,
        exclude_earnings_within_days=(
            override_earnings_days
            if override_earnings_days is not None
            else scanner_cfg.exclude_earnings_within_days
        ),
        iv_rank_minimum=(
            override_iv_rank_min
            if override_iv_rank_min is not None
            else scanner_cfg.iv_rank_minimum
        ),
        iv_rank_maximum=(
            override_iv_rank_max
            if override_iv_rank_max is not None
            else scanner_cfg.iv_rank_maximum
        ),
        enable_iv_filter=(
            enable_iv_filter if enable_iv_filter is not None else scanner_cfg.enable_iv_filter
        ),
        max_results_per_symbol=scanner_cfg.max_results_per_symbol,
        max_total_results=scanner_cfg.max_total_results,
        max_concurrent=scanner_cfg.max_concurrent,
        min_data_points=scanner_cfg.min_data_points,
        enable_pullback=scanner_cfg.enable_pullback,
        enable_ath_breakout=scanner_cfg.enable_ath_breakout,
        enable_bounce=scanner_cfg.enable_bounce,
        enable_earnings_dip=scanner_cfg.enable_earnings_dip,
        # Fundamentals Filter (aus filters.fundamentals)
        enable_fundamentals_filter=(
            enable_fundamentals_filter
            if enable_fundamentals_filter is not None
            else fundamentals_cfg.enabled
        ),
        fundamentals_min_stability=fundamentals_cfg.min_stability_score,
        fundamentals_min_win_rate=fundamentals_cfg.min_historical_win_rate,
        fundamentals_max_volatility=fundamentals_cfg.max_historical_volatility,
        fundamentals_max_beta=fundamentals_cfg.max_beta,
        fundamentals_iv_rank_min=fundamentals_cfg.iv_rank_min,
        fundamentals_iv_rank_max=fundamentals_cfg.iv_rank_max,
        fundamentals_max_spy_correlation=fundamentals_cfg.max_spy_correlation,
        fundamentals_min_spy_correlation=fundamentals_cfg.min_spy_correlation,
        fundamentals_exclude_sectors=fundamentals_cfg.exclude_sectors,
        fundamentals_include_sectors=fundamentals_cfg.include_sectors,
        fundamentals_exclude_market_caps=fundamentals_cfg.exclude_market_caps,
        fundamentals_include_market_caps=fundamentals_cfg.include_market_caps,
        fundamentals_blacklist=fundamentals_cfg.blacklist_symbols,
        fundamentals_whitelist=fundamentals_cfg.whitelist_symbols,
        # Stability-First-Filter (Phase 6)
        enable_stability_first=scanner_cfg.enable_stability_first,
        stability_premium_threshold=scanner_cfg.stability_premium_threshold,
        stability_premium_min_score=scanner_cfg.stability_premium_min_score,
        stability_good_threshold=scanner_cfg.stability_good_threshold,
        stability_good_min_score=scanner_cfg.stability_good_min_score,
        stability_ok_threshold=scanner_cfg.stability_ok_threshold,
        stability_ok_min_score=scanner_cfg.stability_ok_min_score,
    )
