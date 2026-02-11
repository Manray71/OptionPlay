# OptionPlay - IBKR Package
# ==========================
"""
IBKR integration package split into focused modules:

- connection.py: Symbol mapping, connect/disconnect, availability
- portfolio.py:  Portfolio positions, option positions, spread identification
- market_data.py: VIX, quotes, options chain, news, max pain

All public names are re-exported here for backward compatibility.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Data classes (shared across modules)
# ---------------------------------------------------------------------------


@dataclass
class IBKRNews:
    """News headline from IBKR"""

    symbol: str
    headline: str
    time: Optional[str] = None
    provider: Optional[str] = None


@dataclass
class MaxPainData:
    """Max Pain data"""

    symbol: str
    current_price: float
    max_pain_strike: float
    distance_pct: float
    put_wall: Dict[str, Any]
    call_wall: Dict[str, Any]
    put_call_ratio: float
    expiry: str


@dataclass
class StrikeRecommendation:
    """Strike recommendation from IBKR"""

    symbol: str
    current_price: float
    short_strike: float
    long_strike: float
    spread_width: float
    reason: str
    delta: Optional[float] = None
    credit: Optional[float] = None
    quality: str = "good"
    confidence: float = 50.0
    vix: Optional[float] = None
    vix_regime: Optional[str] = None
    warnings: List[str] = None


# ---------------------------------------------------------------------------
# Sub-module classes
# ---------------------------------------------------------------------------

from .connection import (
    IBKR_REVERSE_MAP,
    IBKR_SYMBOL_MAP,
    IBKRConnection,
    from_ibkr_symbol,
    to_ibkr_symbol,
)
from .market_data import IBKRMarketData
from .portfolio import IBKRPortfolio

__all__ = [
    # Data classes
    "IBKRNews",
    "MaxPainData",
    "StrikeRecommendation",
    # Connection
    "IBKRConnection",
    "IBKR_SYMBOL_MAP",
    "IBKR_REVERSE_MAP",
    "to_ibkr_symbol",
    "from_ibkr_symbol",
    # Sub-modules
    "IBKRPortfolio",
    "IBKRMarketData",
]
