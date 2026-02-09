# Re-export stub: module moved to src/services/vix_strategy.py
# This file maintains backward compatibility for existing imports.
from .services.vix_strategy import *  # noqa: F401,F403
from .services.vix_strategy import (  # noqa: F401
    MarketRegime,
    StrategyRecommendation,
    VIXStrategySelector,
    get_strategy_for_vix,
)
