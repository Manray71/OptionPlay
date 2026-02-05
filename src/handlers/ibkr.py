"""
IBKR Handler Module
===================

Handles Interactive Brokers (IBKR) Bridge operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from ..utils.error_handler import endpoint
from ..utils.markdown_builder import MarkdownBuilder
from ..utils.validation import validate_symbols
from ..config import get_watchlist_loader
from .base import BaseHandlerMixin

if TYPE_CHECKING:
    from ..ibkr_bridge import IBKRBridge

logger = logging.getLogger(__name__)

# IBKR availability flag (set during import)
try:
    from ..ibkr_bridge import IBKRBridge, get_ibkr_bridge
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    IBKRBridge = None
    get_ibkr_bridge = None


class IbkrHandlerMixin(BaseHandlerMixin):
    """
    Mixin for IBKR Bridge handler methods.
    """

    # Type hints for attributes
    _ibkr_bridge: Optional["IBKRBridge"]

    @endpoint(operation="IBKR status check")
    async def get_ibkr_status(self) -> str:
        """Check IBKR Bridge status."""
        b = MarkdownBuilder()
        b.h1("IBKR Bridge Status").blank()

        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            b.status_error("**Not available** - ib_insync not installed.")
            return b.build()

        is_available = await self._ibkr_bridge.is_available(force_check=True)
        b.kv("Status", "[OK] Available" if is_available else "[X] Not available")
        b.kv("Host", f"{self._ibkr_bridge.host}:{self._ibkr_bridge.port}")

        return b.build()

    @endpoint(operation="news fetch")
    async def get_news(self, symbols: List[str], days: int = 5) -> str:
        """
        Get news headlines from IBKR for symbols.

        Args:
            symbols: List of ticker symbols
            days: Number of days to look back

        Returns:
            Formatted news headlines
        """
        symbols = validate_symbols(symbols, skip_invalid=True)

        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        return await self._ibkr_bridge.get_news_formatted(symbols, days)

    @endpoint(operation="max pain calculation")
    async def get_max_pain(self, symbols: List[str]) -> str:
        """
        Calculate Max Pain for symbols via IBKR.

        Args:
            symbols: List of ticker symbols

        Returns:
            Formatted max pain levels
        """
        symbols = validate_symbols(symbols, skip_invalid=True)

        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        return await self._ibkr_bridge.get_max_pain_formatted(symbols)

    @endpoint(operation="IBKR portfolio fetch")
    async def get_ibkr_portfolio(self) -> str:
        """Get portfolio positions from IBKR/TWS."""
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        return await self._ibkr_bridge.get_portfolio_formatted()

    @endpoint(operation="IBKR spreads fetch")
    async def get_ibkr_spreads(self) -> str:
        """Get identified spread positions from IBKR/TWS."""
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        return await self._ibkr_bridge.get_spreads_formatted()

    @endpoint(operation="IBKR VIX fetch")
    async def get_ibkr_vix(self) -> str:
        """Get live VIX from IBKR."""
        b = MarkdownBuilder()

        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            vix = await self.get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata (IBKR not available)")
            return b.build()

        if not await self._ibkr_bridge.is_available():
            vix = await self.get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata (TWS not connected)")
            return b.build()

        vix_data = await self._ibkr_bridge.get_vix()

        if vix_data:
            b.h1("VIX").blank()
            b.kv("VIX", vix_data["value"], fmt=".2f")
            b.kv("Source", f"IBKR ({vix_data['source']})")
        else:
            vix = await self.get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata")

        return b.build()

    @endpoint(operation="IBKR watchlist quotes")
    async def get_ibkr_quotes(
        self,
        symbols: Optional[List[str]] = None,
        batch_size: int = 50,
        pause_seconds: int = 60
    ) -> str:
        """
        Get quotes for watchlist symbols from IBKR in batches.

        Args:
            symbols: List of symbols (default: watchlist)
            batch_size: Symbols per batch
            pause_seconds: Pause between batches

        Returns:
            Formatted quotes
        """
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)

        return await self._ibkr_bridge.get_quotes_batch_formatted(symbols, batch_size, pause_seconds)
