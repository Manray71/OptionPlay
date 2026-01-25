# OptionPlay - Configuration Loader (Backwards Compatibility)
# =============================================================
# This module re-exports from the new package structure for backwards compatibility.
# New code should import directly from src.config
#
# Migration:
#   Old: from config_loader import get_config
#   New: from src.config import get_config

import warnings

# Try relative import first (when used as package), then absolute (when used standalone)
try:
    from .config import (
        ConfigLoader,
        get_config,
        get_scan_config,
        reset_config,
        Settings,
        PullbackScoringConfig,
        FilterConfig,
        OptionsConfig,
        RSIConfig,
        SupportConfig,
        FibonacciConfig,
        FibonacciLevel,
        MovingAverageConfig,
        VolumeConfig,
        PerformanceConfig,
        ApiConnectionConfig,
        CircuitBreakerConfig,
        ScannerConfig,
        find_config_dir,
    )
except ImportError:
    # Standalone mode - use absolute import
    from config import (
        ConfigLoader,
        get_config,
        get_scan_config,
        reset_config,
        Settings,
        PullbackScoringConfig,
        FilterConfig,
        OptionsConfig,
        RSIConfig,
        SupportConfig,
        FibonacciConfig,
        FibonacciLevel,
        MovingAverageConfig,
        VolumeConfig,
        PerformanceConfig,
        ApiConnectionConfig,
        CircuitBreakerConfig,
        ScannerConfig,
        find_config_dir,
    )

__all__ = [
    'ConfigLoader',
    'get_config',
    'get_scan_config',
    'reset_config',
    'Settings',
    'PullbackScoringConfig',
    'FilterConfig',
    'OptionsConfig',
    'RSIConfig',
    'SupportConfig',
    'FibonacciConfig',
    'FibonacciLevel',
    'MovingAverageConfig',
    'VolumeConfig',
    'PerformanceConfig',
    'ApiConnectionConfig',
    'CircuitBreakerConfig',
    'ScannerConfig',
    'find_config_dir',
]


def __getattr__(name):
    """Issue deprecation warning for direct imports from this module."""
    if name in __all__:
        warnings.warn(
            f"Importing '{name}' from 'config_loader' is deprecated. "
            f"Please import from 'src.config' instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return globals().get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
