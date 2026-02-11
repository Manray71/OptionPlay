# OptionPlay - Options Pricing Module
# ====================================
# Black-Scholes und andere Pricing-Modelle für Backtesting
# NumPy-vektorisierte Batch-Funktionen für schnelles Backtesting

from .black_scholes import find_strike_for_delta  # NEW: Delta-basierte Strike-Auswahl
from .black_scholes import (  # Scalar functions; NumPy-vektorisierte Funktionen; Batch-Funktionen für Backtesting; Classes; Convenience
    Greeks,
    OptionPricer,
    PricingResult,
    batch_estimate_iv,
    batch_historical_volatility,
    batch_spread_credit,
    batch_spread_pnl,
    black_scholes_call,
    black_scholes_call_np,
    black_scholes_greeks,
    black_scholes_price,
    black_scholes_put,
    black_scholes_put_np,
    create_pricer,
    implied_volatility,
    quick_put_price,
    quick_spread_credit,
)

__all__ = [
    # Scalar
    "black_scholes_price",
    "black_scholes_put",
    "black_scholes_call",
    "black_scholes_greeks",
    "implied_volatility",
    "find_strike_for_delta",  # NEW
    # NumPy vectorized
    "black_scholes_put_np",
    "black_scholes_call_np",
    # Batch functions
    "batch_spread_credit",
    "batch_spread_pnl",
    "batch_historical_volatility",
    "batch_estimate_iv",
    # Classes
    "OptionPricer",
    "PricingResult",
    "Greeks",
    # Convenience
    "create_pricer",
    "quick_put_price",
    "quick_spread_credit",
]
