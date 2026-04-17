# OptionPlay - IBKR Connection Management
# ==========================================
"""
Handles IBKR/TWS connection lifecycle and symbol mapping.

Provides:
- Symbol mapping between standard tickers and IBKR-compatible names
- Connection management (connect, disconnect, availability check)
- Shared connection instance for portfolio and market data modules
"""

import asyncio
import logging
import socket

# ib_insync needs nest_asyncio for compatibility with already running event loops
# (e.g., when the MCP server already uses asyncio.run())
import nest_asyncio

nest_asyncio.apply()

from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# IBKR SYMBOL MAPPING
# =============================================================================
# Some symbols have different names at IBKR than at other brokers/data providers.
# This mapping converts standard symbols to IBKR-compatible symbols.

IBKR_SYMBOL_MAP = {
    # Berkshire Hathaway - space instead of period
    "BRK.B": "BRK B",
    "BRK.A": "BRK A",
    # Brown-Forman - space instead of period
    "BF.B": "BF B",
    "BF.A": "BF A",
    # Symbols not available at IBKR (delisted, merged, ticker change)
    # Set to None to skip them
    "MMC": None,  # Marsh McLennan - possibly ticker change
    "IPG": None,  # Interpublic Group - possibly delisted
    "PARA": None,  # Paramount - delisted/merged
    "K": None,  # Kellanova - possibly ticker change after spin-off
    "PXD": None,  # Pioneer Natural Resources - acquired by Exxon
    "HES": None,  # Hess - acquired by Chevron
    "MRO": None,  # Marathon Oil - possibly ticker change
    # Additional known issues can be added here
}

# Reverse mapping for back-conversion
IBKR_REVERSE_MAP = {v: k for k, v in IBKR_SYMBOL_MAP.items() if v is not None}


def to_ibkr_symbol(symbol: str) -> Optional[str]:
    """
    Converts a standard symbol to an IBKR-compatible symbol.

    Args:
        symbol: Standard ticker symbol

    Returns:
        IBKR symbol or None if the symbol should be skipped
    """
    symbol = symbol.upper().strip()

    # Check if mapping exists
    if symbol in IBKR_SYMBOL_MAP:
        mapped = IBKR_SYMBOL_MAP[symbol]
        if mapped is None:
            logger.debug(f"Symbol {symbol} is being skipped (no IBKR equivalent)")
        return mapped

    return symbol


def from_ibkr_symbol(ibkr_symbol: str) -> str:
    """
    Converts an IBKR symbol back to the standard symbol.

    Args:
        ibkr_symbol: IBKR ticker symbol

    Returns:
        Standard symbol
    """
    if ibkr_symbol in IBKR_REVERSE_MAP:
        return IBKR_REVERSE_MAP[ibkr_symbol]
    return ibkr_symbol


class IBKRConnection:
    """
    Manages the IBKR/TWS connection lifecycle.

    Provides connect/disconnect, availability checking,
    and access to the underlying ib_insync IB instance.

    Usage:
        conn = IBKRConnection()
        if await conn.is_available():
            await conn._ensure_connected()
            # Use conn.ib for API calls
    """

    # TWS Default Ports
    TWS_PAPER_PORT = 7497
    TWS_LIVE_PORT = 7496
    GATEWAY_PORT = 4001

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 98) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self._ib = None
        self._connected = False
        self._last_check: Optional[datetime] = None
        self._check_interval = 60  # seconds

    @property
    def ib(self) -> Any:
        """Access to the underlying ib_insync IB instance."""
        return self._ib

    @property
    def connected(self) -> bool:
        """Whether the connection is currently active."""
        return self._connected

    async def is_available(self, force_check: bool = False) -> bool:
        """
        Checks if TWS/Gateway is reachable.

        Caches the result for 60 seconds.
        """
        if not force_check and self._last_check:
            age = (datetime.now() - self._last_check).total_seconds()
            if age < self._check_interval:
                return self._connected

        self._last_check = datetime.now()

        # Quick Socket Check
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((self.host, self.port))
            sock.close()
            self._connected = result == 0

            if self._connected:
                logger.debug(f"TWS reachable at {self.host}:{self.port}")
            else:
                logger.debug(f"TWS not reachable at {self.host}:{self.port}")

            return self._connected

        except Exception as e:
            logger.debug(f"TWS check failed: {e}")
            self._connected = False
            return False

    async def _ensure_connected(self) -> bool:
        """Establishes connection to IBKR."""
        # Check if existing connection is still active
        if self._ib is not None and self._connected:
            if self._ib.isConnected():
                return True
            else:
                logger.warning("IBKR connection lost, reconnecting...")
                self._connected = False
                self._ib = None

        if not await self.is_available():
            return False

        try:
            from ib_insync import IB

            self._ib = IB()
            await self._ib.connectAsync(
                self.host,
                self.port,
                clientId=self.client_id,
                timeout=10,
                readonly=True,
            )

            if self._ib.isConnected():
                self._connected = True
                # Use delayed data (type 3) to avoid subscription errors
                self._ib.reqMarketDataType(3)
                logger.info(f"IBKR Bridge verbunden (clientId={self.client_id}, port={self.port})")
                return True
            else:
                logger.warning("IBKR connectAsync returned but isConnected=False")
                self._connected = False
                return False

        except ImportError:
            logger.warning("ib_insync not installed - IBKR Bridge not available")
            return False
        except Exception as e:
            logger.warning(f"IBKR Bridge connection failed: {type(e).__name__}: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnects."""
        if self._ib:
            self._ib.disconnect()
            self._ib = None
        self._connected = False

    async def get_status(self) -> Dict[str, any]:
        """Returns connection status."""
        available = await self.is_available(force_check=True)

        return {
            "available": available,
            "host": self.host,
            "port": self.port,
            "connected": self._connected,
            "features": ["news", "vix", "max_pain", "portfolio", "positions"] if available else [],
        }
