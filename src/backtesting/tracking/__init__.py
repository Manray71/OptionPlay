# OptionPlay - Trade Tracking Subpackage
# =======================================
# SQLite-basiertes Trade-Tracking für kontinuierliches Training
#
# Refactored in Phase 2.3 (Recursive Logic):
# - models.py: Dataclasses und Enums
# - tracker.py: TradeTracker Klasse (Facade)
# - analytics.py: Formatierung und Factory-Funktionen
#
# Refactored in Phase 6b (TradeTracker aufbrechen):
# - trade_crud.py: Trade CRUD operations
# - trade_analysis.py: Statistics, export, storage stats
# - price_storage.py: Historical price data (compressed JSON)
# - vix_storage.py: VIX historical data
# - options_storage.py: Historical options data
#
# Abwärtskompatibilität: Alle bisherigen Imports funktionieren weiterhin.

from .models import (
    TradeStatus,
    TradeOutcome,
    TrackedTrade,
    TradeStats,
    PriceBar,
    SymbolPriceData,
    VixDataPoint,
    OptionBar,
)

from .tracker import TradeTracker

from .analytics import (
    format_trade_stats,
    create_tracker,
)

# Sub-modules (for direct access if needed)
from .trade_crud import TradeCRUD
from .trade_analysis import TradeAnalysis
from .price_storage import PriceStorage
from .vix_storage import VixStorage
from .options_storage import OptionsStorage

__all__ = [
    # Enums
    'TradeStatus',
    'TradeOutcome',
    # Models
    'TrackedTrade',
    'TradeStats',
    'PriceBar',
    'SymbolPriceData',
    'VixDataPoint',
    'OptionBar',
    # Tracker (Facade)
    'TradeTracker',
    # Analytics
    'format_trade_stats',
    'create_tracker',
    # Sub-modules
    'TradeCRUD',
    'TradeAnalysis',
    'PriceStorage',
    'VixStorage',
    'OptionsStorage',
]
