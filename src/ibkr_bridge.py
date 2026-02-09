# OptionPlay - IBKR Bridge (Facade)
# ====================================
"""
Backward-compatible facade for IBKR integration.

The actual implementation is split across:
- src/ibkr/connection.py   -> IBKRConnection (symbol mapping, connect/disconnect)
- src/ibkr/portfolio.py    -> IBKRPortfolio  (positions, spreads)
- src/ibkr/market_data.py  -> IBKRMarketData (VIX, quotes, options, news, max pain)

This module re-exports everything so existing imports continue to work:
    from src.ibkr_bridge import IBKRBridge, get_ibkr_bridge
    from src.ibkr_bridge import to_ibkr_symbol, IBKR_SYMBOL_MAP, ...
"""

from dataclasses import dataclass
from typing import Optional, Dict, List, Any

# Re-export all public names from the ibkr package
from .ibkr import (
    # Data classes
    IBKRNews,
    MaxPainData,
    StrikeRecommendation,
    # Connection utilities
    IBKRConnection,
    IBKR_SYMBOL_MAP,
    IBKR_REVERSE_MAP,
    to_ibkr_symbol,
    from_ibkr_symbol,
    # Sub-module classes
    IBKRPortfolio,
    IBKRMarketData,
)


class IBKRBridge:
    """
    Facade that composes IBKRConnection, IBKRPortfolio, and IBKRMarketData.

    Maintains the exact same public API as the original monolithic class.

    Usage:
        bridge = IBKRBridge()

        if await bridge.is_available():
            news = await bridge.get_news(["AAPL", "MSFT"])
            max_pain = await bridge.get_max_pain(["AAPL"])
    """

    # TWS Default Ports (kept for backward compatibility)
    TWS_PAPER_PORT = 7497
    TWS_LIVE_PORT = 7496
    GATEWAY_PORT = 4001

    @dataclass
    class QuoteData:
        """Quote data for a symbol."""
        symbol: str
        last: Optional[float] = None
        bid: Optional[float] = None
        ask: Optional[float] = None
        volume: Optional[int] = None
        change: Optional[float] = None
        change_pct: Optional[float] = None
        high: Optional[float] = None
        low: Optional[float] = None
        close: Optional[float] = None
        error: Optional[str] = None

    def __init__(self, host: str = "127.0.0.1", port: int = 7497) -> None:
        # Shared connection instance
        self._connection = IBKRConnection(host=host, port=port)
        # Composed sub-modules
        self._portfolio = IBKRPortfolio(self._connection)
        self._market_data = IBKRMarketData(self._connection)

    # ------------------------------------------------------------------
    # Expose connection attributes for backward compatibility
    # ------------------------------------------------------------------

    @property
    def host(self) -> str:
        return self._connection.host

    @property
    def port(self) -> int:
        return self._connection.port

    @property
    def _ib(self):
        return self._connection._ib

    @_ib.setter
    def _ib(self, value):
        self._connection._ib = value

    @property
    def _connected(self):
        return self._connection._connected

    @_connected.setter
    def _connected(self, value):
        self._connection._connected = value

    @property
    def _last_check(self):
        return self._connection._last_check

    @_last_check.setter
    def _last_check(self, value):
        self._connection._last_check = value

    @property
    def _check_interval(self):
        return self._connection._check_interval

    # ------------------------------------------------------------------
    # Connection management (delegate to IBKRConnection)
    # ------------------------------------------------------------------

    async def is_available(self, force_check: bool = False) -> bool:
        return await self._connection.is_available(force_check=force_check)

    async def _ensure_connected(self) -> bool:
        return await self._connection._ensure_connected()

    async def disconnect(self) -> None:
        return await self._connection.disconnect()

    async def get_status(self) -> Dict[str, Any]:
        return await self._connection.get_status()

    async def get_status_formatted(self) -> str:
        return await self._market_data.get_status_formatted()

    # ------------------------------------------------------------------
    # News (delegate to IBKRMarketData)
    # ------------------------------------------------------------------

    async def get_news(
        self,
        symbols: List[str],
        days: int = 5,
        max_per_symbol: int = 5
    ) -> List[IBKRNews]:
        return await self._market_data.get_news(symbols, days, max_per_symbol)

    async def get_news_formatted(
        self,
        symbols: List[str],
        days: int = 5
    ) -> str:
        return await self._market_data.get_news_formatted(symbols, days)

    # ------------------------------------------------------------------
    # VIX (delegate to IBKRMarketData)
    # ------------------------------------------------------------------

    async def get_vix(self) -> Optional[Dict[str, Any]]:
        return await self._market_data.get_vix()

    async def get_vix_value(self) -> Optional[float]:
        return await self._market_data.get_vix_value()

    # ------------------------------------------------------------------
    # Max Pain (delegate to IBKRMarketData)
    # ------------------------------------------------------------------

    async def get_max_pain(
        self,
        symbols: List[str],
        expiry: Optional[str] = None
    ) -> List[MaxPainData]:
        return await self._market_data.get_max_pain(symbols, expiry)

    async def get_max_pain_formatted(self, symbols: List[str]) -> str:
        return await self._market_data.get_max_pain_formatted(symbols)

    # ------------------------------------------------------------------
    # Portfolio & Positions (delegate to IBKRPortfolio)
    # ------------------------------------------------------------------

    async def get_portfolio(self) -> List[Dict[str, Any]]:
        return await self._portfolio.get_portfolio()

    async def get_portfolio_formatted(self) -> str:
        return await self._portfolio.get_portfolio_formatted()

    async def get_option_positions(self) -> List[Dict[str, Any]]:
        return await self._portfolio.get_option_positions()

    async def get_spreads(self) -> List[Dict[str, Any]]:
        return await self._portfolio.get_spreads()

    async def get_spreads_formatted(self) -> str:
        return await self._portfolio.get_spreads_formatted()

    # ------------------------------------------------------------------
    # Batch Quotes (delegate to IBKRMarketData)
    # ------------------------------------------------------------------

    async def get_quotes_batch(
        self,
        symbols: List[str],
        batch_size: int = 50,
        pause_seconds: int = 60,
        callback: Optional[callable] = None,
        include_outside_rth: bool = True
    ) -> List[Dict[str, Any]]:
        return await self._market_data.get_quotes_batch(
            symbols, batch_size, pause_seconds, callback, include_outside_rth
        )

    async def get_quotes_batch_formatted(
        self,
        symbols: List[str],
        batch_size: int = 50,
        pause_seconds: int = 60
    ) -> str:
        return await self._market_data.get_quotes_batch_formatted(
            symbols, batch_size, pause_seconds
        )

    # ------------------------------------------------------------------
    # Options Chain (delegate to IBKRMarketData)
    # ------------------------------------------------------------------

    async def get_option_chain(
        self,
        symbol: str,
        dte_min: int = 60,
        dte_max: int = 90,
        right: str = "P",
    ) -> list:
        return await self._market_data.get_option_chain(
            symbol, dte_min, dte_max, right
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_bridge: Optional[IBKRBridge] = None


def get_ibkr_bridge() -> IBKRBridge:
    """Returns global bridge instance."""
    global _default_bridge
    if _default_bridge is None:
        _default_bridge = IBKRBridge()
    return _default_bridge


async def check_ibkr_available() -> bool:
    """Quick check if IBKR is available."""
    bridge = get_ibkr_bridge()
    return await bridge.is_available()
