# OptionPlay - Support/Resistance Indicators (Facade)
# ====================================================
# Backward-compatible facade that re-exports everything from
# sr_core (data structures, core algorithms, main API, utilities)
# and sr_advanced (volume profile, level tests, event analysis).
#
# All existing imports from this module continue to work unchanged.
#
# Implementation split:
#   sr_core.py     - Data structures + Core algorithms + Main API + Utilities
#   sr_advanced.py - Advanced analysis (volume profile, level tests, events)

from __future__ import annotations

# Re-export everything from sr_advanced
from .sr_advanced import (  # Advanced S/R with context; Volume Profile; Touch Quality & Volume Confirmation; Enhanced Analysis with Validation; Event-Aware Analysis
    analyze_level_tests,
    analyze_sr_with_events,
    analyze_support_resistance_with_validation,
    calculate_volume_profile,
    get_nearest_sr_levels,
    get_volume_at_level,
    validate_level_with_volume,
)

# Re-export everything from sr_core
from .sr_core import (  # Data structures; Core algorithms; Main API; Utilities
    LevelTest,
    PriceLevel,
    SupportResistanceResult,
    VolumeProfile,
    VolumeZone,
    analyze_support_resistance,
    calculate_fibonacci,
    cluster_levels,
    find_local_maxima_optimized,
    find_local_minima_optimized,
    find_pivot_points,
    find_resistance_levels,
    find_resistance_levels_enhanced,
    find_support_levels,
    find_support_levels_enhanced,
    price_near_level,
    score_levels,
)

# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Data structures
    "PriceLevel",
    "VolumeZone",
    "VolumeProfile",
    "LevelTest",
    "SupportResistanceResult",
    # Core algorithms
    "find_local_minima_optimized",
    "find_local_maxima_optimized",
    "cluster_levels",
    "score_levels",
    # Main API
    "find_support_levels",
    "find_resistance_levels",
    "find_support_levels_enhanced",
    "find_resistance_levels_enhanced",
    "analyze_support_resistance",
    # Volume Analysis
    "calculate_volume_profile",
    "analyze_level_tests",
    "validate_level_with_volume",
    "get_volume_at_level",
    "analyze_support_resistance_with_validation",
    # Event-Aware Analysis
    "analyze_sr_with_events",
    # Advanced
    "get_nearest_sr_levels",
    # Utilities
    "calculate_fibonacci",
    "find_pivot_points",
    "price_near_level",
]
