# OptionPlay - IBKR Data Provider
# ==================================
"""
Vollwertiger IBKR DataProvider via ib_insync.

Implementiert das DataProvider ABC und wrapped die bestehenden
IBKRConnection + IBKRMarketData Module.

Usage:
    provider = IBKRDataProvider(host="127.0.0.1", port=7497)
    await provider.connect()
    quote = await provider.get_quote("AAPL")
"""

import asyncio
import logging
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .interface import (
    DataProvider,
    DataQuality,
    HistoricalBar,
    OptionQuote,
    PriceQuote,
)

logger = logging.getLogger(__name__)

# Lazy imports for cache types (avoid circular)
try:
    from ..cache import EarningsInfo, EarningsSource, IVData, IVSource
except ImportError:
    try:
        from cache import EarningsInfo, EarningsSource, IVData, IVSource
    except ImportError:
        from src.cache import EarningsInfo, EarningsSource, IVData, IVSource


def _load_ibkr_config() -> Dict[str, Any]:
    """Load IBKR connection settings from config/settings.yaml."""
    from pathlib import Path

    try:
        import yaml

        config_path = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("connection", {}).get("ibkr", {})
    except Exception:
        return {}


_ibkr_cfg = _load_ibkr_config()
_DEFAULT_HOST = _ibkr_cfg.get("host", "127.0.0.1")
_DEFAULT_PORT = _ibkr_cfg.get("port", 7497)
_DEFAULT_CLIENT_ID = _ibkr_cfg.get("client_id", 10)
_DEFAULT_TIMEOUT = _ibkr_cfg.get("timeout_seconds", 30)


class IBKRDataProvider(DataProvider):
    """
    Vollwertiger IBKR Data Provider.

    Wraps IBKRConnection + IBKRMarketData to implement the DataProvider ABC.
    Also provides extra methods for VIX and VIX Futures (not part of ABC).
    """

    def __init__(
        self,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        client_id: int = _DEFAULT_CLIENT_ID,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout

        # IBKR components (lazy-initialized on connect)
        self._connection = None
        self._market_data = None

        # Rate limiting
        self._historical_semaphore = asyncio.Semaphore(6)  # max 6 concurrent historical
        self._mktdata_semaphore = asyncio.Semaphore(50)  # max 50 market data lines

    # =========================================================================
    # DataProvider ABC — Properties
    # =========================================================================

    @property
    def name(self) -> str:
        return "ibkr"

    @property
    def supported_features(self) -> List[str]:
        return ["quotes", "options", "historical", "iv", "vix"]

    # =========================================================================
    # DataProvider ABC — Connection
    # =========================================================================

    async def connect(self) -> bool:
        """Establish connection to IB Gateway/TWS."""
        try:
            from ..ibkr.connection import IBKRConnection
            from ..ibkr.market_data import IBKRMarketData

            self._connection = IBKRConnection(
                host=self._host,
                port=self._port,
                client_id=self._client_id,
            )

            connected = await self._connection._ensure_connected()
            if connected:
                self._market_data = IBKRMarketData(self._connection)
                logger.info(
                    f"IBKRDataProvider connected ({self._host}:{self._port}, "
                    f"clientId={self._client_id})"
                )
            return connected

        except ImportError:
            logger.warning("ib_insync not installed — IBKRDataProvider unavailable")
            return False
        except Exception as e:
            logger.warning(f"IBKRDataProvider connect failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from IB Gateway/TWS."""
        if self._connection:
            await self._connection.disconnect()
            self._connection = None
            self._market_data = None

    async def is_connected(self) -> bool:
        """Check connection status."""
        if self._connection is None:
            return False
        return await self._connection.is_available()

    # =========================================================================
    # DataProvider ABC — Quotes
    # =========================================================================

    async def get_quote(self, symbol: str) -> Optional[PriceQuote]:
        """Get a single stock quote."""
        if not await self._ensure_ready():
            return None

        from ..ibkr.connection import to_ibkr_symbol

        try:
            from ib_insync import Stock

            ibkr_sym = to_ibkr_symbol(symbol)
            if ibkr_sym is None:
                logger.debug(f"Symbol {symbol} has no IBKR equivalent")
                return None

            async with self._mktdata_semaphore:
                stock = Stock(ibkr_sym, "SMART", "USD")
                self._connection.ib.qualifyContracts(stock)

                self._connection.ib.reqMktData(stock, "221", False, False)
                await asyncio.sleep(2)

                ticker = self._connection.ib.ticker(stock)
                self._connection.ib.cancelMktData(stock)

                if not ticker:
                    return None

                last = _valid_float(ticker.last)
                bid = _valid_float(ticker.bid)
                ask = _valid_float(ticker.ask)
                close = _valid_float(ticker.close)
                mark = _valid_float(getattr(ticker, "markPrice", None))

                # Price fallback chain
                price = last or mark or close
                if price is None and bid and ask:
                    price = (bid + ask) / 2

                volume = None
                if ticker.volume and not math.isnan(ticker.volume) and ticker.volume > 0:
                    volume = int(ticker.volume)

                return PriceQuote(
                    symbol=symbol,
                    last=price,
                    bid=bid,
                    ask=ask,
                    volume=volume,
                    timestamp=datetime.now(),
                    data_quality=DataQuality.REALTIME if last else DataQuality.DELAYED_15MIN,
                    source="ibkr",
                )

        except Exception as e:
            logger.warning(f"IBKRDataProvider get_quote({symbol}) error: {e}")
            return None

    async def get_quotes(self, symbols: List[str]) -> Dict[str, PriceQuote]:
        """Get quotes for multiple symbols."""
        if not await self._ensure_ready():
            return {}

        # Use existing batch method and convert results
        raw_results = await self._market_data.get_quotes_batch(
            symbols, batch_size=50, pause_seconds=0
        )

        quotes = {}
        for r in raw_results:
            sym = r.get("symbol", "")
            if "error" in r:
                continue

            last = r.get("last") or r.get("close")
            bid = r.get("bid")
            ask = r.get("ask")

            if last is None and bid is None and ask is None:
                continue

            quotes[sym] = PriceQuote(
                symbol=sym,
                last=last,
                bid=bid,
                ask=ask,
                volume=r.get("volume"),
                timestamp=datetime.now(),
                data_quality=DataQuality.REALTIME if r.get("last") else DataQuality.END_OF_DAY,
                source="ibkr",
            )

        return quotes

    # =========================================================================
    # DataProvider ABC — Historical
    # =========================================================================

    async def get_historical(self, symbol: str, days: int = 90) -> List[HistoricalBar]:
        """Get historical OHLCV data from IBKR."""
        if not await self._ensure_ready():
            return []

        from ..ibkr.connection import to_ibkr_symbol

        try:
            from ib_insync import Stock

            ibkr_sym = to_ibkr_symbol(symbol)
            if ibkr_sym is None:
                return []

            async with self._historical_semaphore:
                stock = Stock(ibkr_sym, "SMART", "USD")
                self._connection.ib.qualifyContracts(stock)

                # Duration string: IBKR expects "X D" for days, "X M" for months, "X Y" for years
                if days <= 365:
                    duration = f"{days} D"
                else:
                    years = max(1, days // 365)
                    duration = f"{years} Y"

                bars = await asyncio.wait_for(
                    self._connection.ib.reqHistoricalDataAsync(
                        stock,
                        endDateTime="",
                        durationStr=duration,
                        barSizeSetting="1 day",
                        whatToShow="TRADES",
                        useRTH=True,
                        formatDate=1,
                    ),
                    timeout=self._timeout,
                )

                if not bars:
                    return []

                result = []
                for bar in bars:
                    try:
                        bar_date = bar.date
                        if isinstance(bar_date, str):
                            bar_date = datetime.strptime(bar_date, "%Y-%m-%d").date()
                        elif isinstance(bar_date, datetime):
                            bar_date = bar_date.date()

                        result.append(
                            HistoricalBar(
                                symbol=symbol,
                                date=bar_date,
                                open=float(bar.open),
                                high=float(bar.high),
                                low=float(bar.low),
                                close=float(bar.close),
                                volume=int(bar.volume) if bar.volume else 0,
                                source="ibkr",
                            )
                        )
                    except (ValueError, TypeError, AttributeError) as e:
                        logger.debug(f"Skipping invalid bar for {symbol}: {e}")

                return result

        except asyncio.TimeoutError:
            logger.warning(f"IBKRDataProvider get_historical({symbol}) timeout")
            return []
        except Exception as e:
            logger.warning(f"IBKRDataProvider get_historical({symbol}) error: {e}")
            return []

    # =========================================================================
    # DataProvider ABC — Options
    # =========================================================================

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
        dte_min: int = 30,
        dte_max: int = 60,
        right: str = "P",
    ) -> List[OptionQuote]:
        """Get options chain with Greeks from IBKR."""
        if not await self._ensure_ready():
            return []

        # Delegate to existing IBKRMarketData.get_option_chain()
        # which already returns List[OptionQuote]
        return await self._market_data.get_option_chain(
            symbol=symbol,
            dte_min=dte_min,
            dte_max=dte_max,
            right=right,
        )

    async def get_expirations(self, symbol: str) -> List[date]:
        """Get available option expiration dates."""
        if not await self._ensure_ready():
            return []

        from ..ibkr.connection import to_ibkr_symbol

        try:
            from ib_insync import Stock

            ibkr_sym = to_ibkr_symbol(symbol)
            if ibkr_sym is None:
                return []

            stock = Stock(ibkr_sym, "SMART", "USD")
            self._connection.ib.qualifyContracts(stock)

            chains = await asyncio.wait_for(
                self._connection.ib.reqSecDefOptParamsAsync(
                    stock.symbol, "", stock.secType, stock.conId
                ),
                timeout=15,
            )

            if not chains:
                return []

            chain = next((c for c in chains if c.exchange == "SMART"), chains[0])

            result = []
            for exp_str in sorted(chain.expirations):
                try:
                    exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
                    result.append(exp_date)
                except (ValueError, TypeError):
                    continue

            return result

        except asyncio.TimeoutError:
            logger.warning(f"IBKRDataProvider get_expirations({symbol}) timeout")
            return []
        except Exception as e:
            logger.warning(f"IBKRDataProvider get_expirations({symbol}) error: {e}")
            return []

    # =========================================================================
    # DataProvider ABC — IV Data
    # =========================================================================

    async def get_iv_data(self, symbol: str) -> Optional[IVData]:
        """
        Get IV data. Current IV from IBKR tick, IV rank from local DB.
        """
        if not await self._ensure_ready():
            return None

        from ..ibkr.connection import to_ibkr_symbol

        try:
            from ib_insync import Stock

            ibkr_sym = to_ibkr_symbol(symbol)
            if ibkr_sym is None:
                return None

            async with self._mktdata_semaphore:
                stock = Stock(ibkr_sym, "SMART", "USD")
                self._connection.ib.qualifyContracts(stock)

                # Tick 106 = impliedVolatility (historical volatility from IBKR)
                self._connection.ib.reqMktData(stock, "106", False, False)
                await asyncio.sleep(2)

                ticker = self._connection.ib.ticker(stock)
                self._connection.ib.cancelMktData(stock)

                current_iv = None
                if ticker and hasattr(ticker, "impliedVolatility"):
                    iv_raw = ticker.impliedVolatility
                    if iv_raw and not math.isnan(iv_raw) and iv_raw > 0:
                        current_iv = iv_raw

                # Try to get IV rank from local DB fundamentals
                iv_rank = None
                iv_percentile = None
                iv_high = None
                iv_low = None
                data_points = 0

                try:
                    from ..cache import get_fundamentals_manager

                    fm = get_fundamentals_manager()
                    f = fm.get_fundamentals(symbol)
                    if f:
                        iv_rank = getattr(f, "iv_rank_252d", None)
                        data_points = 252 if iv_rank is not None else 0
                except Exception:
                    pass

                if current_iv is None and iv_rank is None:
                    return None

                return IVData(
                    symbol=symbol,
                    current_iv=current_iv,
                    iv_rank=iv_rank,
                    iv_percentile=iv_percentile,
                    iv_high_52w=iv_high,
                    iv_low_52w=iv_low,
                    data_points=data_points,
                    source=IVSource.IBKR,
                    updated_at=datetime.now().isoformat(),
                )

        except Exception as e:
            logger.warning(f"IBKRDataProvider get_iv_data({symbol}) error: {e}")
            return None

    # =========================================================================
    # DataProvider ABC — Earnings
    # =========================================================================

    async def get_earnings_date(self, symbol: str) -> Optional[EarningsInfo]:
        """
        Get next earnings date. Falls back to Yahoo Finance.

        IBKR requires WSH subscription for earnings — not available in most setups.
        """
        try:
            # Use existing earnings cache/fetcher
            from ..cache import get_earnings_history_manager

            manager = get_earnings_history_manager()
            next_date = manager.get_next_earnings_date(symbol)

            if next_date:
                days_to = (next_date - date.today()).days
                return EarningsInfo(
                    symbol=symbol,
                    earnings_date=next_date.isoformat(),
                    days_to_earnings=days_to,
                    source=EarningsSource.YFINANCE,
                    updated_at=datetime.now().isoformat(),
                    confirmed=False,
                )
        except Exception as e:
            logger.debug(f"Earnings lookup for {symbol} failed: {e}")

        return None

    # =========================================================================
    # EXTRA — VIX (nicht im ABC)
    # =========================================================================

    async def get_vix(self) -> Optional[float]:
        """Get live VIX spot value from IBKR."""
        if not await self._ensure_ready():
            return None

        return await self._market_data.get_vix_value()

    async def get_vix_futures_front(self) -> Optional[float]:
        """
        Get front-month VIX future price from IBKR.

        Used for VIX Term Structure analysis (Phase 2).
        Requires CFE data subscription.
        """
        if not await self._ensure_ready():
            return None

        try:
            from ib_insync import Future

            # VX is the VIX Futures symbol at CFE
            vx = Future("VX", exchange="CFE")

            # Get the next available contract
            chains = self._connection.ib.qualifyContracts(vx)
            if not chains:
                # Try getting contract details to find front month
                details = await asyncio.wait_for(
                    self._connection.ib.reqContractDetailsAsync(vx),
                    timeout=10,
                )
                if details:
                    # Sort by expiry, take the closest
                    details.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
                    vx = details[0].contract
                    self._connection.ib.qualifyContracts(vx)
                else:
                    return None

            async with self._mktdata_semaphore:
                self._connection.ib.reqMktData(vx, "", False, False)
                await asyncio.sleep(2)

                ticker = self._connection.ib.ticker(vx)
                self._connection.ib.cancelMktData(vx)

                if ticker:
                    price = _valid_float(ticker.last) or _valid_float(ticker.close)
                    return round(price, 2) if price else None

        except asyncio.TimeoutError:
            logger.debug("VIX Futures timeout")
        except Exception as e:
            logger.debug(f"VIX Futures error: {e}")

        return None

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _ensure_ready(self) -> bool:
        """Ensure connection is active, attempt reconnect if needed."""
        if self._connection is None:
            return False

        if await self._connection.is_available():
            # Check if ib instance is still connected
            if self._connection.ib and self._connection.ib.isConnected():
                return True
            # Try reconnect
            return await self._connection._ensure_connected()

        return False


# =============================================================================
# Module-level helpers
# =============================================================================


def _valid_float(val: Any) -> Optional[float]:
    """Extract a valid float, filtering NaN and non-positive values."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or f <= 0:
            return None
        return f
    except (ValueError, TypeError):
        return None


def get_ibkr_provider(
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    client_id: int = _DEFAULT_CLIENT_ID,
) -> IBKRDataProvider:
    """Factory function for IBKRDataProvider."""
    return IBKRDataProvider(host=host, port=port, client_id=client_id)
