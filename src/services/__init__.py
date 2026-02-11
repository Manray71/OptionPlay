# OptionPlay - Services Package
# ==============================
"""
Service-Layer für OptionPlay.

Aufgeteilte Business-Logik aus dem ursprünglichen OptionPlayServer "God Object".
Jeder Service hat eine klar definierte Verantwortlichkeit.

Services:
    - VIXService: VIX-Daten und Strategie-Empfehlungen
    - ScannerService: Multi-Strategy Scanning
    - QuoteService: Stock Quotes und Historical Data
    - OptionsService: Options Chain und Strike-Empfehlungen
    - EarningsService: Earnings-Daten und Pre-Filter
    - PortfolioService: Portfolio-Management

Verwendung:
    from src.services import VIXService, ScannerService

    vix_service = VIXService(api_key="...")
    vix = await vix_service.get_vix()

    scanner = ScannerService(api_key="...")
    result = await scanner.scan_pullback(symbols=["AAPL", "MSFT"])
"""

from ..models.result import ServiceResult
from .base import BaseService, ServiceContext
from .options_service import OptionsService
from .portfolio_constraints import (
    ConstraintResult,
    PortfolioConstraintChecker,
    PortfolioConstraints,
    get_constraint_checker,
    reset_constraint_checker,
)
from .position_monitor import (
    MonitorResult,
    PositionMonitor,
    PositionSignal,
    PositionSnapshot,
    estimate_pnl_from_theta,
    get_position_monitor,
    reset_position_monitor,
    snapshot_from_ibkr,
    snapshot_from_internal,
)
from .quote_service import QuoteService
from .recommendation_engine import (
    DailyPick,
    DailyRecommendationEngine,
    DailyRecommendationResult,
    SuggestedStrikes,
    create_recommendation_engine,
    get_quick_picks,
)
from .scanner_service import ScannerService
from .sector_cycle_service import (
    SectorCycleService,
    SectorRegime,
    SectorStatus,
)
from .server_core import ServerCore
from .trade_validator import (
    TradeValidationRequest,
    TradeValidationResult,
    TradeValidator,
    ValidationCheck,
    get_trade_validator,
    reset_trade_validator,
)
from .vix_service import VIXService

__all__ = [
    "BaseService",
    "ServiceContext",
    "ServiceResult",
    "VIXService",
    "ScannerService",
    "QuoteService",
    "OptionsService",
    "ServerCore",
    # Portfolio Constraints
    "PortfolioConstraints",
    "PortfolioConstraintChecker",
    "ConstraintResult",
    "get_constraint_checker",
    "reset_constraint_checker",
    # Trade Validator
    "TradeValidator",
    "TradeValidationRequest",
    "TradeValidationResult",
    "ValidationCheck",
    "get_trade_validator",
    "reset_trade_validator",
    # Position Monitor
    "PositionMonitor",
    "PositionSnapshot",
    "PositionSignal",
    "MonitorResult",
    "get_position_monitor",
    "reset_position_monitor",
    "snapshot_from_internal",
    "snapshot_from_ibkr",
    "estimate_pnl_from_theta",
    # Sector Cycle Service
    "SectorCycleService",
    "SectorRegime",
    "SectorStatus",
    # Recommendation Engine
    "DailyRecommendationEngine",
    "DailyPick",
    "DailyRecommendationResult",
    "SuggestedStrikes",
    "create_recommendation_engine",
    "get_quick_picks",
]
