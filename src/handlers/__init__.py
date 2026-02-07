"""
OptionPlay Handler Modules
==========================

Modular handler organization for the MCP server.

Architecture:
1. Legacy Mixins (for backwards compatibility):
   - VixHandlerMixin, ScanHandlerMixin, etc.
   - Used by OptionPlayServer via multiple inheritance

2. Composition-Based Handlers (preferred for new code):
   - HandlerContainer, ServerContext, BaseHandler
   - Cleaner architecture without MRO complexity
   - Better testability and maintainability

Modules:
- base: Base handler mixin with shared utilities
- vix: VIX, strategy, and regime handlers
- scan: All scan operations (pullback, bounce, breakout, etc.)
- quote: Quote, options chain, historical data
- analysis: Symbol analysis, ensemble recommendations
- portfolio: Portfolio management operations
- ibkr: IBKR Bridge features
- report: PDF report generation
- risk: Position sizing and stop loss
- validate: Trade validation against PLAYBOOK rules
- monitor: Position monitoring for exit signals
- handler_container: Composition-based handler system
"""

# Legacy Mixins (backwards compatibility)
from .base import BaseHandlerMixin
from .vix import VixHandlerMixin
from .scan import ScanHandlerMixin
from .quote import QuoteHandlerMixin
from .analysis import AnalysisHandlerMixin
from .portfolio import PortfolioHandlerMixin
from .ibkr import IbkrHandlerMixin
from .report import ReportHandlerMixin
from .risk import RiskHandlerMixin
from .validate import ValidateHandlerMixin
from .monitor import MonitorHandlerMixin

# Composition-based handler system (new, preferred)
from .handler_container import (
    HandlerContainer,
    ServerContext,
    BaseHandler,
    create_handler_container_from_server,
)

# Composed handlers (new, preferred for new code)
from .vix_composed import VixHandler
from .scan_composed import ScanHandler
from .quote_composed import QuoteHandler
from .analysis_composed import AnalysisHandler
from .portfolio_composed import PortfolioHandler
from .ibkr_composed import IbkrHandler
from .report_composed import ReportHandler
from .risk_composed import RiskHandler
from .validate_composed import ValidateHandler
from .monitor_composed import MonitorHandler

__all__ = [
    # Legacy Mixins (for backwards compatibility)
    "BaseHandlerMixin",
    "VixHandlerMixin",
    "ScanHandlerMixin",
    "QuoteHandlerMixin",
    "AnalysisHandlerMixin",
    "PortfolioHandlerMixin",
    "IbkrHandlerMixin",
    "ReportHandlerMixin",
    "RiskHandlerMixin",
    "ValidateHandlerMixin",
    "MonitorHandlerMixin",
    # Composition-based infrastructure
    "HandlerContainer",
    "ServerContext",
    "BaseHandler",
    "create_handler_container_from_server",
    # Composed handlers (preferred for new code)
    "VixHandler",
    "ScanHandler",
    "QuoteHandler",
    "AnalysisHandler",
    "PortfolioHandler",
    "IbkrHandler",
    "ReportHandler",
    "RiskHandler",
    "ValidateHandler",
    "MonitorHandler",
]
