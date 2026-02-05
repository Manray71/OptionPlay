# OptionPlay - Trade Tracking Subpackage
# =======================================
# SQLite-basiertes Trade-Tracking für kontinuierliches Training
#
# Refactored in Phase 2.3 (Recursive Logic):
# - models.py: Dataclasses und Enums
# - tracker.py: TradeTracker Klasse
# - analytics.py: Formatierung und Factory-Funktionen
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
    # Tracker
    'TradeTracker',
    # Analytics
    'format_trade_stats',
    'create_tracker',
]
