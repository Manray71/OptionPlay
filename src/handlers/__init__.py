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
    # New Composition-based (preferred for new code)
    "HandlerContainer",
    "ServerContext",
    "BaseHandler",
    "create_handler_container_from_server",
]
