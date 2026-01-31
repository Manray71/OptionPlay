"""
Base Handler Mixin
==================

Shared utilities and type hints for all handler modules.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from ..data_providers.marketdata import MarketDataProvider
    from ..data_providers.tradier import TradierProvider
    from ..scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig
    from ..cache import EarningsFetcher, HistoricalCache
    from ..utils.rate_limiter import AdaptiveRateLimiter
    from ..utils.circuit_breaker import CircuitBreaker
    from ..utils.request_dedup import RequestDeduplicator
    from ..vix_strategy import VIXStrategySelector
    from ..config import Config

logger = logging.getLogger(__name__)


class BaseHandlerMixin:
    """
    Base mixin providing shared utilities for all handlers.

    This mixin defines the interface that the main OptionPlayServer provides,
    allowing handler modules to access shared state and utilities.

    Attributes expected on self (provided by OptionPlayServer):
        _config: Config instance
        _provider: MarketDataProvider instance
        _tradier_provider: Optional TradierProvider instance
        _rate_limiter: AdaptiveRateLimiter instance
        _circuit_breaker: CircuitBreaker instance
        _historical_cache: HistoricalCache instance
        _earnings_fetcher: Optional EarningsFetcher instance
        _vix_selector: VIXStrategySelector instance
        _deduplicator: RequestDeduplicator instance
        _connected: bool
        _tradier_connected: bool
        _current_vix: Optional[float]
        _vix_updated: Optional[datetime]
        _quote_cache: Dict[str, tuple]
        _scan_cache: Dict[str, tuple]
    """

    # Type hints for attributes provided by OptionPlayServer
    _config: "Config"
    _provider: Optional["MarketDataProvider"]
    _tradier_provider: Optional["TradierProvider"]
    _rate_limiter: "AdaptiveRateLimiter"
    _circuit_breaker: "CircuitBreaker"
    _historical_cache: "HistoricalCache"
    _earnings_fetcher: Optional["EarningsFetcher"]
    _vix_selector: "VIXStrategySelector"
    _deduplicator: "RequestDeduplicator"
    _connected: bool
    _tradier_connected: bool
    _current_vix: Optional[float]
    _vix_updated: Optional[datetime]
    _quote_cache: Dict[str, tuple]
    _scan_cache: Dict[str, tuple]
    _scan_cache_ttl: int
    _quote_cache_hits: int
    _quote_cache_misses: int
    _scan_cache_hits: int
    _scan_cache_misses: int

    # Methods expected from OptionPlayServer (defined elsewhere)
    async def _ensure_connected(self) -> "MarketDataProvider":
        """Ensure connection to data provider."""
        raise NotImplementedError

    async def _ensure_tradier_connected(self) -> Optional["TradierProvider"]:
        """Ensure connection to Tradier."""
        raise NotImplementedError

    async def _fetch_historical_cached(
        self,
        symbol: str,
        days: Optional[int] = None
    ) -> Optional[Tuple]:
        """Fetch historical data with caching."""
        raise NotImplementedError

    async def _get_quote_cached(self, symbol: str) -> Optional[Any]:
        """Get quote with caching."""
        raise NotImplementedError

    def _get_scanner(
        self,
        min_score: Optional[float] = None,
        earnings_days: Optional[int] = None
    ) -> "MultiStrategyScanner":
        """Get scanner instance."""
        raise NotImplementedError

    def _get_multi_scanner(
        self,
        min_score: float = 3.5,
        enable_pullback: bool = True,
        enable_bounce: bool = True,
        enable_breakout: bool = True,
        enable_earnings_dip: bool = True,
    ) -> "MultiStrategyScanner":
        """Get multi-strategy scanner instance."""
        raise NotImplementedError

    async def _apply_earnings_prefilter(
        self,
        symbols: List[str],
        min_days: int,
        for_earnings_dip: bool = False
    ) -> Tuple[List[str], int, int]:
        """Apply earnings pre-filter to symbols."""
        raise NotImplementedError

    async def get_vix(self, force_refresh: bool = False) -> Optional[float]:
        """Get current VIX value."""
        raise NotImplementedError
