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
- risk_composed: Position sizing and stop loss
- validate_composed: Trade validation against PLAYBOOK rules
- monitor_composed: Position monitoring for exit signals
"""

from .analysis_composed import AnalysisHandler

# Legacy Mixins (deprecated — kept for test compatibility)
from .base import BaseHandlerMixin

# Composition-based handler system (active)
from .handler_container import (
    BaseHandler,
    HandlerContainer,
    ServerContext,
    create_handler_container_from_server,
)
from .ibkr_composed import IbkrHandler
from .monitor_composed import MonitorHandler
from .portfolio_composed import PortfolioHandler
from .quote_composed import QuoteHandler
from .risk_composed import RiskHandler
from .scan import ScanHandlerMixin
from .scan_composed import ScanHandler
from .validate_composed import ValidateHandler
from .vix import VixHandlerMixin

# Composed handlers (active)
from .vix_composed import VixHandler

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
    "RiskHandler",
    "ValidateHandler",
    "MonitorHandler",
    # Legacy Mixins (deprecated)
    "BaseHandlerMixin",
    "VixHandlerMixin",
    "ScanHandlerMixin",
]
