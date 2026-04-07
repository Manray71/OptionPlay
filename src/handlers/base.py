"""
Base Handler Mixin
==================

Shared utilities and type hints for all handler modules.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional

from ..constants.trading_rules import SPREAD_DTE_MAX, SPREAD_DTE_MIN

if TYPE_CHECKING:
    from ..cache import EarningsFetcher, HistoricalCache
    from ..config import ConfigLoader
    from ..data_providers.ibkr_provider import IBKRDataProvider
    from ..scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig
    from ..services.vix_strategy import VIXStrategySelector
    from ..utils.circuit_breaker import CircuitBreaker
    from ..utils.rate_limiter import AdaptiveRateLimiter
    from ..utils.request_dedup import RequestDeduplicator

logger = logging.getLogger(__name__)


class BaseHandlerMixin:
    """
    Base mixin providing shared utilities for all handlers.

    This mixin defines the interface that the main OptionPlayServer provides,
    allowing handler modules to access shared state and utilities.

    Attributes expected on self (provided by OptionPlayServer):
        _config: Config instance
        _provider: Optional provider instance
        _ibkr_provider: Optional IBKRDataProvider instance
        _rate_limiter: AdaptiveRateLimiter instance
        _circuit_breaker: CircuitBreaker instance
        _historical_cache: HistoricalCache instance
        _earnings_fetcher: Optional EarningsFetcher instance
        _vix_selector: VIXStrategySelector instance
        _deduplicator: RequestDeduplicator instance
        _connected: bool
        _ibkr_connected: bool
        _current_vix: Optional[float]
        _vix_updated: Optional[datetime]
        _quote_cache: Dict[str, tuple]
        _scan_cache: Dict[str, tuple]
    """

    # Type hints for attributes provided by OptionPlayServer
    _config: "ConfigLoader"
    _provider: Optional[Any]
    _ibkr_provider: Optional["IBKRDataProvider"]
    _rate_limiter: "AdaptiveRateLimiter"
    _circuit_breaker: "CircuitBreaker"
    _historical_cache: "HistoricalCache"
    _earnings_fetcher: Optional["EarningsFetcher"]
    _vix_selector: "VIXStrategySelector"
    _deduplicator: "RequestDeduplicator"
    _connected: bool
    _ibkr_connected: bool
    _current_vix: Optional[float]
    _vix_updated: Optional[datetime]
    _quote_cache: dict[str, tuple[Any, ...]]
    _scan_cache: dict[str, tuple[Any, ...]]
    _scan_cache_ttl: int
    _quote_cache_hits: int
    _quote_cache_misses: int
    _scan_cache_hits: int
    _scan_cache_misses: int
    _ibkr_bridge: Any

    # Methods expected from OptionPlayServer (defined elsewhere)
    async def _ensure_connected(self) -> Optional[Any]:
        """Ensure connection to data provider."""
        raise NotImplementedError

    async def _ensure_ibkr_connected(self) -> Optional["IBKRDataProvider"]:
        """Ensure connection to IBKR."""
        raise NotImplementedError

    # Legacy alias
    async def _ensure_tradier_connected(self) -> Optional[Any]:
        """Legacy alias for _ensure_ibkr_connected."""
        return await self._ensure_ibkr_connected()

    async def _fetch_historical_cached(
        self, symbol: str, days: Optional[int] = None
    ) -> Optional[tuple[Any, ...]]:
        """Fetch historical data with caching."""
        raise NotImplementedError

    async def _get_quote_cached(self, symbol: str) -> Optional[Any]:
        """Get quote with caching."""
        raise NotImplementedError

    def _get_scanner(
        self, min_score: Optional[float] = None, earnings_days: Optional[int] = None
    ) -> "MultiStrategyScanner":
        """Get scanner instance."""
        raise NotImplementedError

    def _get_multi_scanner(
        self,
        min_score: float = 3.5,
        enable_pullback: bool = True,
        enable_bounce: bool = True,
    ) -> "MultiStrategyScanner":
        """Get multi-strategy scanner instance."""
        raise NotImplementedError

    async def _apply_earnings_prefilter(
        self,
        symbols: list[str],
        min_days: int,
    ) -> tuple[list[str], int, int]:
        """Apply earnings pre-filter to symbols."""
        raise NotImplementedError

    async def get_vix(self, force_refresh: bool = False) -> Optional[float]:
        """Get current VIX value."""
        raise NotImplementedError

    async def _get_options_chain_with_fallback(
        self,
        symbol: str,
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
        right: str = "P",
    ) -> list[Any]:
        """
        Fetch options chain with IBKR provider as primary source.

        Provider priority:
            1. IBKR DataProvider — full chains with Greeks
            2. IBKR Bridge (legacy fallback)

        Args:
            symbol: Ticker symbol
            dte_min: Minimum days to expiration
            dte_max: Maximum days to expiration
            right: Option type - "P" for puts, "C" for calls

        Returns:
            List of OptionQuote objects, or empty list if no data available
        """
        options = None
        right_upper = right.upper()

        # 1. Try IBKR DataProvider (primary)
        if self._ibkr_connected and self._ibkr_provider:
            try:
                options = await self._ibkr_provider.get_option_chain(
                    symbol,
                    dte_min=dte_min,
                    dte_max=dte_max,
                    right=right_upper,
                )
                if options:
                    logger.debug(f"Options chain from IBKR: {len(options)} options for {symbol}")
            except Exception as e:
                logger.debug(f"IBKR options chain failed for {symbol}: {e}")

        # 2. Fallback to IBKR Bridge (legacy)
        if not options and hasattr(self, "_ibkr_bridge") and self._ibkr_bridge:
            try:
                if await self._ibkr_bridge.is_available():
                    options = await self._ibkr_bridge.get_option_chain(
                        symbol,
                        dte_min=dte_min,
                        dte_max=dte_max,
                        right=right_upper,
                    )
                    if options:
                        logger.debug(
                            f"Options chain from IBKR bridge: {len(options)} options for {symbol}"
                        )
            except Exception as e:
                logger.debug(f"IBKR bridge options chain failed for {symbol}: {e}")

        if not options:
            logger.warning(
                f"No options chain available for {symbol} "
                f"(IBKR: {'connected' if self._ibkr_connected else 'not connected'}, "
                f"Bridge: {'available' if hasattr(self, '_ibkr_bridge') and self._ibkr_bridge else 'not available'})"
            )

        return options or []
