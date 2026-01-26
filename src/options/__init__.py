# OptionPlay - Options Package
# =============================
# Options-spezifische Analyse-Tools

from .max_pain import (
    MaxPainCalculator,
    calculate_max_pain,
    format_max_pain_report
)
from .strike_recommender import (
    StrikeRecommender,
    calculate_strike_recommendation
)
from .vix_strategy import (
    VIXStrategySelector,
    MarketRegime,
    VIXThresholds,
    StrategyRecommendation,
    get_strategy_for_vix,
    format_recommendation
)
from .black_scholes import (
    BlackScholes,
    BullPutSpread,
    OptionType,
    Greeks,
    SpreadGreeks,
    calculate_put_price,
    calculate_call_price,
    calculate_delta,
    calculate_implied_volatility,
    calculate_probability_otm,
)

__all__ = [
    # Max Pain
    'MaxPainCalculator',
    'calculate_max_pain',
    'format_max_pain_report',

    # Strike Recommender
    'StrikeRecommender',
    'calculate_strike_recommendation',

    # VIX Strategy
    'VIXStrategySelector',
    'MarketRegime',
    'VIXThresholds',
    'StrategyRecommendation',
    'get_strategy_for_vix',
    'format_recommendation',

    # Black-Scholes Pricing
    'BlackScholes',
    'BullPutSpread',
    'OptionType',
    'Greeks',
    'SpreadGreeks',
    'calculate_put_price',
    'calculate_call_price',
    'calculate_delta',
    'calculate_implied_volatility',
    'calculate_probability_otm',
]
