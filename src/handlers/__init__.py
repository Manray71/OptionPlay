"""
OptionPlay Handler Modules
==========================

Modular handler organization for the MCP server.

Architecture:
  Composition-Based Handlers (active):
  - HandlerContainer, ServerContext, BaseHandler
  - Used by OptionPlayServer via server.handlers property
  - Cleaner architecture without MRO complexity

  Legacy Mixins (deprecated, kept for test compatibility):
  - VixHandlerMixin, ScanHandlerMixin, etc.
  - No longer inherited by OptionPlayServer

Modules:
- handler_container: Composition-based handler system
- vix_composed: VIX, strategy, and regime handlers
- scan_composed: All scan operations
- quote_composed: Quote, options chain, historical data
- analysis_composed: Symbol analysis, ensemble recommendations
- portfolio_composed: Portfolio management operations
- ibkr_composed: IBKR Bridge features
- report_composed: PDF report generation
- risk_composed: Position sizing and stop loss
- validate_composed: Trade validation against PLAYBOOK rules
- monitor_composed: Position monitoring for exit signals
"""

# Composition-based handler system (active)
from .handler_container import (
    HandlerContainer,
    ServerContext,
    BaseHandler,
    create_handler_container_from_server,
)

# Composed handlers (active)
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

# Legacy Mixins (deprecated — kept for test compatibility)
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

__all__ = [
    # Composition-based infrastructure
    "HandlerContainer",
    "ServerContext",
    "BaseHandler",
    "create_handler_container_from_server",
    # Composed handlers (active)
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
    # Legacy Mixins (deprecated)
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
]
