"""
IBKR Handler (Composition-Based)
==================================

Handles Interactive Brokers (IBKR) Bridge operations.

This is the composition-based version of IbkrHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# IBKR availability flag
try:
    from ..ibkr_bridge import IBKRBridge, get_ibkr_bridge
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    IBKRBridge = None
    get_ibkr_bridge = None


class IbkrHandler(BaseHandler):
    """
    Handler for IBKR Bridge operations.

    Methods:
    - get_ibkr_status(): Check IBKR Bridge status
    - get_news(): Get news headlines from IBKR
    - get_max_pain(): Calculate Max Pain for symbols
    - get_ibkr_portfolio(): Get portfolio positions from IBKR
    - get_ibkr_spreads(): Get identified spread positions
    - get_ibkr_vix(): Get live VIX from IBKR
    - get_ibkr_quotes(): Get batch quotes from IBKR
    """

    async def get_ibkr_status(self) -> str:
        """Check IBKR Bridge status."""
        from ..utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        b.h1("IBKR Bridge Status").blank()

        if not IBKR_AVAILABLE or not self._ctx.ibkr_bridge:
            b.status_error("**Not available** - ib_insync not installed.")
            return b.build()

        is_available = await self._ctx.ibkr_bridge.is_available(force_check=True)
        b.kv("Status", "[OK] Available" if is_available else "[X] Not available")
        b.kv("Host", f"{self._ctx.ibkr_bridge.host}:{self._ctx.ibkr_bridge.port}")

        return b.build()

    async def get_news(self, symbols: List[str], days: int = 5) -> str:
        """
        Get news headlines from IBKR for symbols.

        Args:
            symbols: List of ticker symbols
            days: Number of days to look back

        Returns:
            Formatted news headlines
        """
        from ..utils.validation import validate_symbols

        symbols = validate_symbols(symbols, skip_invalid=True)

        if not IBKR_AVAILABLE or not self._ctx.ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ctx.ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        return await self._ctx.ibkr_bridge.get_news_formatted(symbols, days)

    async def get_max_pain(self, symbols: List[str]) -> str:
        """
        Calculate Max Pain for symbols via IBKR.

        Args:
            symbols: List of ticker symbols

        Returns:
            Formatted max pain levels
        """
        from ..utils.validation import validate_symbols

        symbols = validate_symbols(symbols, skip_invalid=True)

        if not IBKR_AVAILABLE or not self._ctx.ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ctx.ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        return await self._ctx.ibkr_bridge.get_max_pain_formatted(symbols)

    async def get_ibkr_portfolio(self) -> str:
        """Get portfolio positions from IBKR/TWS."""
        if not IBKR_AVAILABLE or not self._ctx.ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ctx.ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        return await self._ctx.ibkr_bridge.get_portfolio_formatted()

    async def get_ibkr_spreads(self) -> str:
        """Get identified spread positions from IBKR/TWS."""
        if not IBKR_AVAILABLE or not self._ctx.ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ctx.ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        return await self._ctx.ibkr_bridge.get_spreads_formatted()

    async def get_ibkr_vix(self) -> str:
        """Get live VIX from IBKR with fallback."""
        from ..utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()

        if not IBKR_AVAILABLE or not self._ctx.ibkr_bridge:
            vix = await self._get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata (IBKR not available)")
            return b.build()

        if not await self._ctx.ibkr_bridge.is_available():
            vix = await self._get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata (TWS not connected)")
            return b.build()

        vix_data = await self._ctx.ibkr_bridge.get_vix()

        if vix_data:
            b.h1("VIX").blank()
            b.kv("VIX", vix_data["value"], fmt=".2f")
            b.kv("Source", f"IBKR ({vix_data['source']})")
        else:
            vix = await self._get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata")

        return b.build()

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
        from ..utils.validation import validate_symbols
        from ..config import get_watchlist_loader

        if not IBKR_AVAILABLE or not self._ctx.ibkr_bridge:
            return "IBKR Bridge not available."

        if not await self._ctx.ibkr_bridge.is_available():
            return "TWS/Gateway not reachable."

        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)

        return await self._ctx.ibkr_bridge.get_quotes_batch_formatted(symbols, batch_size, pause_seconds)

    # --- Shared helper methods ---

    async def _get_vix(self) -> Optional[float]:
        """Get current VIX value from context cache or provider."""
        if self._ctx.current_vix is not None:
            return self._ctx.current_vix
        if self._ctx.provider:
            try:
                quote = await self._ctx.provider.get_quote("VIX")
                if quote and hasattr(quote, 'last') and quote.last:
                    self._ctx.current_vix = quote.last
                    self._ctx.vix_updated = datetime.now()
                    return quote.last
            except (ConnectionError, AttributeError, TimeoutError) as e:
                logger.debug("VIX fetch failed: %s", e)
        return None
