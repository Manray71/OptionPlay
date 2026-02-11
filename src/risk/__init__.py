# OptionPlay - Risk Management Package
# =====================================
"""
Risk Management Module für OptionPlay.

Enthält:
- Position Sizing mit Kelly Criterion
- VIX-basierte Adjustments
- Stop Loss Management
- Portfolio-Level Risk Controls
"""

from .position_sizing import (
    KellyMode,
    PositionSizer,
    PositionSizerConfig,
    PositionSizeResult,
    VIXRegime,
    calculate_optimal_position,
    get_recommended_stop_loss,
)

__all__ = [
    "PositionSizer",
    "PositionSizerConfig",
    "PositionSizeResult",
    "KellyMode",
    "VIXRegime",
    "calculate_optimal_position",
    "get_recommended_stop_loss",
]
