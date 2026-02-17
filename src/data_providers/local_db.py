# OptionPlay - Local Database Data Provider
# ==========================================
# Provides historical price data from the local SQLite database.
# Uses underlying_price from options_prices table for fast scanner access.
#
# This provider is MUCH faster than API calls since data is local.
# Coverage: 356 symbols, 2021-01-04 to present
#
# Usage:
#     from src.data_providers.local_db import LocalDBProvider, get_local_db_provider
#
#     provider = get_local_db_provider()
#     if provider.is_available():
#         data = provider.get_historical_for_scanner("AAPL", days=260)

import asyncio
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

T = TypeVar("T")

from .interface import DataProvider, DataQuality, HistoricalBar, PriceQuote

logger = logging.getLogger(__name__)


# Default database path
DEFAULT_DB_PATH = Path.home() / ".optionplay" / "trades.db"


class LocalDBProvider(DataProvider):
    """
    Local database provider for historical price data.

    Extracts daily closing prices from the options_prices table
    where underlying_price is stored for each quote_date.

    This is significantly faster than API calls:
    - API: ~30s timeout per symbol, rate limited
    - Local: <1ms per symbol, no rate limits

    Note: Only provides closing prices, not full OHLCV data.
    For scanner purposes (RSI, SMA, etc.), close prices are sufficient.

    Implements the DataProvider interface for seamless integration.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """
        Initialize the local database provider.

        Args:
            db_path: Path to trades.db (default: ~/.optionplay/trades.db)
        """
        self.db_path = Path(db_path).expanduser() if db_path else DEFAULT_DB_PATH
        self._available_symbols: Optional[List[str]] = None
        self._symbol_date_ranges: Dict[str, Tuple[date, date]] = {}
        self._connected = False

        if not self.db_path.exists():
            logger.warning(f"Database not found: {self.db_path}")
        else:
            self._ensure_daily_prices_table()

    # =========================================================================
    # DataProvider Interface Implementation
    # =========================================================================

    @property
    def name(self) -> str:
        return "local_db"

    @property
    def supported_features(self) -> List[str]:
        return ["historical", "quotes"]

    def _connect_sync(self) -> bool:
        """Sync connect logic. Runs in thread pool."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(DISTINCT underlying) FROM options_prices")
                count = cursor.fetchone()[0]
                self._connected = count > 0
                if self._connected:
                    logger.info(f"LocalDBProvider connected: {count} symbols available")
                return self._connected
        except Exception as e:
            logger.error(f"LocalDBProvider connection failed: {e}")
            self._connected = False
            return False

    async def connect(self) -> bool:
        """Connect to the database (verify it exists and has data)."""
        if not self.db_path.exists():
            logger.warning(f"Database not found: {self.db_path}")
            self._connected = False
            return False
        return await self._run_sync(self._connect_sync)

    async def disconnect(self) -> None:
        """Disconnect from the database."""
        self._connected = False
        self._available_symbols = None
        self._symbol_date_ranges.clear()

    async def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected

    def _get_quote_sync(self, symbol: str) -> Optional[PriceQuote]:
        """Sync quote logic. Runs in thread pool."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT underlying_price, quote_date
                    FROM options_prices
                    WHERE underlying = ?
                      AND underlying_price IS NOT NULL
                    ORDER BY quote_date DESC
                    LIMIT 1
                """,
                    (symbol,),
                )
                row = cursor.fetchone()

                if row:
                    return PriceQuote(
                        symbol=symbol,
                        last=float(row[0]),
                        bid=None,
                        ask=None,
                        volume=None,
                        timestamp=datetime.fromisoformat(row[1] + "T16:00:00"),
                        data_quality=DataQuality.END_OF_DAY,
                        source="local_db",
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to get quote for {symbol}: {e}")
            return None

    async def get_quote(self, symbol: str) -> Optional[PriceQuote]:
        """
        Get the latest quote for a symbol.

        Returns the most recent underlying_price from options_prices.
        Note: This is end-of-day data, not real-time.
        """
        return await self._run_sync(self._get_quote_sync, symbol.upper())

    def _get_quotes_batch_sync(self, symbols: List[str]) -> Dict[str, PriceQuote]:
        """Batch quote retrieval using a single SQL query per batch."""
        if not symbols:
            return {}

        results = {}
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Use a single query with GROUP BY to get latest quote per symbol
                placeholders = ",".join("?" for _ in symbols)
                cursor.execute(
                    f"""
                    SELECT underlying, underlying_price, MAX(quote_date) as quote_date
                    FROM options_prices
                    WHERE underlying IN ({placeholders})
                      AND underlying_price IS NOT NULL
                    GROUP BY underlying
                    """,
                    [s.upper() for s in symbols],
                )
                for row in cursor.fetchall():
                    symbol = row[0]
                    results[symbol] = PriceQuote(
                        symbol=symbol,
                        last=float(row[1]),
                        bid=None,
                        ask=None,
                        volume=None,
                        timestamp=datetime.fromisoformat(row[2] + "T16:00:00"),
                        data_quality=DataQuality.END_OF_DAY,
                        source="local_db",
                    )
        except Exception as e:
            logger.error(f"Failed to get batch quotes: {e}")
        return results

    async def get_quotes(self, symbols: List[str]) -> Dict[str, PriceQuote]:
        """
        Get quotes for multiple symbols.

        Returns the most recent underlying_price from options_prices for each symbol.
        Uses a single batch SQL query instead of one query per symbol.
        """
        return await self._run_sync(self._get_quotes_batch_sync, symbols)

    async def get_option_chain(
        self,
        symbol: str,
        expiration: Optional[date] = None,
        strikes: Optional[List[float]] = None,
        option_type: Optional[str] = None,
    ) -> List[Any]:
        """
        Get option chain - NOT SUPPORTED by local DB.

        Local DB has options_prices but not in real-time format.
        Use Tradier or Marketdata.app for option chains.
        """
        logger.debug(f"get_option_chain not supported by local DB for {symbol}")
        return []

    async def get_expirations(self, symbol: str) -> List[date]:
        """
        Get available expirations - NOT SUPPORTED by local DB.

        Use Tradier or Marketdata.app for expirations.
        """
        logger.debug(f"get_expirations not supported by local DB for {symbol}")
        return []

    async def get_iv_data(self, symbol: str) -> Optional[Any]:
        """
        Get IV data - NOT SUPPORTED by local DB.

        IV data should come from options_greeks table but that requires
        additional implementation. Use Tradier for real-time IV.
        """
        logger.debug(f"get_iv_data not supported by local DB for {symbol}")
        return None

    def _get_earnings_date_sync(self, symbol: str) -> Optional[Any]:
        """Sync earnings date query. Runs in thread pool."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT earnings_date, time_of_day
                    FROM earnings_history
                    WHERE symbol = ?
                      AND earnings_date >= date('now')
                    ORDER BY earnings_date ASC
                    LIMIT 1
                """,
                    (symbol,),
                )
                row = cursor.fetchone()

                if row:
                    from ..cache import EarningsInfo, EarningsSource

                    return EarningsInfo(
                        symbol=symbol,
                        earnings_date=row[0],
                        source=EarningsSource.DATABASE,
                        time_of_day=row[1],
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to get earnings for {symbol}: {e}")
            return None

    async def get_earnings_date(self, symbol: str) -> Optional[Any]:
        """
        Get earnings date from earnings_history table.

        Returns the next upcoming or most recent earnings date.
        """
        return await self._run_sync(self._get_earnings_date_sync, symbol.upper())

    def _get_historical_sync(self, symbol: str, days: int) -> List[HistoricalBar]:
        """Sync historical query. Runs in thread pool."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT quote_date, underlying_price
                    FROM options_prices
                    WHERE underlying = ?
                      AND underlying_price IS NOT NULL
                    GROUP BY quote_date
                    ORDER BY quote_date DESC
                    LIMIT ?
                """,
                    (symbol, days),
                )

                rows = cursor.fetchall()
                if not rows:
                    return []

                rows = list(reversed(rows))

                bars = []
                for row in rows:
                    price = float(row[1])
                    bars.append(
                        HistoricalBar(
                            symbol=symbol,
                            date=date.fromisoformat(row[0]),
                            open=price,
                            high=price,
                            low=price,
                            close=price,
                            volume=0,
                            source="local_db",
                        )
                    )

                return bars

        except Exception as e:
            logger.error(f"Failed to get historical for {symbol}: {e}")
            return []

    async def get_historical(
        self, symbol: str, days: int = 90, interval: str = "daily"
    ) -> List[HistoricalBar]:
        """
        Get historical price bars.

        Note: Only daily interval is supported from local DB.
        Only close prices are available (OHLC are all set to close).
        """
        return await self._run_sync(self._get_historical_sync, symbol.upper(), days)

    def _get_historical_for_scanner_sync(
        self, symbol: str, days: int
    ) -> Optional[Tuple[List[float], List[int], List[float], List[float], List[float]]]:
        """Sync scanner data query. Runs in thread pool.

        Priority:
        1. daily_prices table (real OHLCV from API)
        2. options_prices table (close only, fake OHLCV fallback)
        """
        # 1. Try daily_prices first (has real OHLCV data)
        daily_data = self._query_daily_prices_sync(symbol, days)
        if daily_data and len(daily_data[0]) >= 50:
            logger.debug(f"LocalDB: Loaded {len(daily_data[0])} real OHLCV bars for {symbol}")
            return daily_data

        # 2. Fallback: options_prices (close only)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT quote_date, underlying_price
                    FROM options_prices
                    WHERE underlying = ?
                      AND underlying_price IS NOT NULL
                    GROUP BY quote_date
                    ORDER BY quote_date DESC
                    LIMIT ?
                """,
                    (symbol, days),
                )

                rows = cursor.fetchall()

                if not rows:
                    logger.debug(f"No price data for {symbol} in local DB")
                    return None

                rows = list(reversed(rows))
                prices = [float(row[1]) for row in rows]

                if len(prices) < 50:
                    logger.debug(f"Insufficient data for {symbol}: {len(prices)} < 50")
                    return None

                volumes = [0] * len(prices)
                highs = prices.copy()
                lows = prices.copy()
                opens = prices.copy()

                logger.debug(
                    f"LocalDB: Loaded {len(prices)} close-only prices for {symbol} (no OHLCV)"
                )
                return prices, volumes, highs, lows, opens

        except Exception as e:
            logger.error(f"Failed to get scanner data for {symbol}: {e}")
            return None

    async def get_historical_for_scanner(
        self, symbol: str, days: int = 260
    ) -> Optional[Tuple[List[float], List[int], List[float], List[float], List[float]]]:
        """
        Get historical data in scanner format.

        The scanner expects: (prices, volumes, highs, lows, opens)

        Since we only have closing prices from options_prices,
        we use close for all OHLC values and 0 for volume.

        This is acceptable for most technical indicators:
        - RSI: uses close only
        - SMA/EMA: uses close only
        - Support/Resistance: works with close
        - Fibonacci: uses high/low but close approximation works

        Args:
            symbol: Stock ticker
            days: Number of trading days

        Returns:
            Tuple of (prices, volumes, highs, lows, opens) or None
        """
        return await self._run_sync(self._get_historical_for_scanner_sync, symbol.upper(), days)

    # =========================================================================
    # Daily Prices Table (OHLCV enrichment)
    # =========================================================================

    def _ensure_daily_prices_table(self):
        """Create daily_prices table if it doesn't exist."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS daily_prices (
                        symbol TEXT NOT NULL,
                        quote_date TEXT NOT NULL,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        volume INTEGER NOT NULL DEFAULT 0,
                        source TEXT DEFAULT 'tradier',
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (symbol, quote_date)
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol
                    ON daily_prices(symbol)
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to create daily_prices table: {e}")

    def _save_daily_prices_sync(self, symbol: str, bars: List[HistoricalBar]) -> int:
        """Save OHLCV bars to daily_prices table. Returns count of saved rows."""
        if not bars:
            return 0

        symbol = symbol.upper()
        saved = 0

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for bar in bars:
                    try:
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO daily_prices
                                (symbol, quote_date, open, high, low, close, volume, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                symbol,
                                (
                                    bar.date.isoformat()
                                    if isinstance(bar.date, date)
                                    else str(bar.date)
                                ),
                                bar.open,
                                bar.high,
                                bar.low,
                                bar.close,
                                bar.volume,
                                bar.source or "tradier",
                            ),
                        )
                        saved += 1
                    except sqlite3.Error as e:
                        logger.warning(f"Error saving daily price for {symbol} {bar.date}: {e}")
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save daily prices for {symbol}: {e}")

        logger.debug(f"Saved {saved} daily prices for {symbol}")
        return saved

    async def save_daily_prices(self, symbol: str, bars: List[HistoricalBar]) -> int:
        """Save OHLCV bars to daily_prices table (async)."""
        return await self._run_sync(self._save_daily_prices_sync, symbol, bars)

    def _save_daily_prices_from_tuple_sync(
        self,
        symbol: str,
        data: Tuple[List[float], List[int], List[float], List[float], List[float]],
    ) -> int:
        """Save scanner-format tuple data to daily_prices. Returns count of saved rows."""
        prices, volumes, highs, lows, opens = data
        if not prices:
            return 0

        symbol = symbol.upper()
        saved = 0

        # We need dates — estimate from today backwards (trading days)
        today = date.today()
        num_bars = len(prices)

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Try to get actual dates from options_prices for this symbol
                cursor.execute(
                    """
                    SELECT DISTINCT quote_date
                    FROM options_prices
                    WHERE underlying = ?
                      AND underlying_price IS NOT NULL
                    ORDER BY quote_date DESC
                    LIMIT ?
                """,
                    (symbol, num_bars),
                )
                date_rows = cursor.fetchall()

                if date_rows and len(date_rows) >= num_bars:
                    # Use actual dates from options_prices (reversed to oldest-first)
                    dates = [row[0] for row in reversed(date_rows)][:num_bars]
                else:
                    # Fallback: estimate trading dates backwards from today
                    dates = []
                    current = today
                    while len(dates) < num_bars:
                        if current.weekday() < 5:  # Mon-Fri
                            dates.append(current.isoformat())
                        current -= timedelta(days=1)
                    dates.reverse()

                for i in range(num_bars):
                    try:
                        quote_date = dates[i] if isinstance(dates[i], str) else dates[i]
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO daily_prices
                                (symbol, quote_date, open, high, low, close, volume, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                symbol,
                                quote_date,
                                opens[i],
                                highs[i],
                                lows[i],
                                prices[i],
                                volumes[i],
                                "api",
                            ),
                        )
                        saved += 1
                    except (sqlite3.Error, IndexError) as e:
                        logger.warning(f"Error saving daily price tuple for {symbol} idx {i}: {e}")

                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save daily prices from tuple for {symbol}: {e}")

        logger.debug(f"Saved {saved} daily prices (from tuple) for {symbol}")
        return saved

    async def save_daily_prices_from_tuple(
        self,
        symbol: str,
        data: Tuple[List[float], List[int], List[float], List[float], List[float]],
    ) -> int:
        """Save scanner-format tuple data to daily_prices table (async)."""
        return await self._run_sync(self._save_daily_prices_from_tuple_sync, symbol, data)

    def _query_daily_prices_sync(
        self, symbol: str, days: int
    ) -> Optional[Tuple[List[float], List[int], List[float], List[float], List[float]]]:
        """Query daily_prices table for OHLCV data in scanner format."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT quote_date, open, high, low, close, volume
                    FROM daily_prices
                    WHERE symbol = ?
                    ORDER BY quote_date DESC
                    LIMIT ?
                """,
                    (symbol.upper(), days),
                )

                rows = cursor.fetchall()
                if not rows:
                    return None

                # Reverse to oldest-first
                rows = list(reversed(rows))

                prices = [float(row[4]) for row in rows]  # close
                volumes = [int(row[5]) for row in rows]
                highs = [float(row[2]) for row in rows]
                lows = [float(row[3]) for row in rows]
                opens = [float(row[1]) for row in rows]

                return prices, volumes, highs, lows, opens

        except Exception as e:
            logger.debug(f"daily_prices query failed for {symbol}: {e}")
            return None

    # =========================================================================
    # Local DB Specific Methods
    # =========================================================================

    @contextmanager
    def _get_connection(self):
        """Context manager for database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    async def _run_sync(self, func: Callable[..., T], *args: Any) -> T:
        """Run a sync function in a thread pool to avoid blocking the event loop."""
        return await asyncio.to_thread(func, *args)

    def is_available(self) -> bool:
        """Check if the database is available and has data."""
        if not self.db_path.exists():
            return False

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM options_prices LIMIT 1")
                count = cursor.fetchone()[0]
                return count > 0
        except Exception as e:
            logger.error(f"Database check failed: {e}")
            return False

    def get_available_symbols(self) -> List[str]:
        """Get list of symbols with price data in the database."""
        if self._available_symbols is not None:
            return self._available_symbols

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT underlying
                    FROM options_prices
                    ORDER BY underlying
                """)
                self._available_symbols = [row[0] for row in cursor.fetchall()]
                logger.debug(f"Found {len(self._available_symbols)} symbols in database")
                return self._available_symbols
        except Exception as e:
            logger.error(f"Failed to get symbols: {e}")
            return []

    def has_symbol(self, symbol: str) -> bool:
        """Check if symbol exists in local database."""
        symbols = self.get_available_symbols()
        return symbol.upper() in symbols

    def get_data_range(self, symbol: str) -> Optional[Tuple[date, date]]:
        """
        Get the date range of available data for a symbol.

        Args:
            symbol: Stock ticker

        Returns:
            Tuple of (min_date, max_date) or None if no data
        """
        symbol = symbol.upper()

        # Check cache
        if symbol in self._symbol_date_ranges:
            return self._symbol_date_ranges[symbol]

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT MIN(quote_date), MAX(quote_date)
                    FROM options_prices
                    WHERE underlying = ?
                """,
                    (symbol,),
                )
                row = cursor.fetchone()

                if row and row[0] and row[1]:
                    result = (date.fromisoformat(row[0]), date.fromisoformat(row[1]))
                    self._symbol_date_ranges[symbol] = result
                    return result
                return None
        except Exception as e:
            logger.error(f"Failed to get date range for {symbol}: {e}")
            return None

    def is_data_fresh(self, symbol: str, max_age_days: int = 7) -> bool:
        """
        Check if the data for a symbol is fresh enough.

        Args:
            symbol: Stock ticker
            max_age_days: Maximum allowed age of data in days

        Returns:
            True if data is fresh enough, False otherwise
        """
        date_range = self.get_data_range(symbol)
        if not date_range:
            return False

        _, max_date = date_range
        age = (date.today() - max_date).days
        return age <= max_age_days

    def get_vix_history(self, days: int = 260) -> Optional[List[Tuple[str, float]]]:
        """
        Get VIX history from vix_data table.

        Args:
            days: Number of trading days

        Returns:
            List of (date, value) tuples or None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT date, value
                    FROM vix_data
                    ORDER BY date DESC
                    LIMIT ?
                """,
                    (days,),
                )

                rows = cursor.fetchall()
                if not rows:
                    return None

                # Reverse to oldest-first
                return [(row[0], float(row[1])) for row in reversed(rows)]

        except Exception as e:
            logger.error(f"Failed to get VIX history: {e}")
            return None

    def get_latest_vix(self) -> Optional[float]:
        """Get the most recent VIX value from the database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT value FROM vix_data
                    ORDER BY date DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()
                return float(row[0]) if row else None
        except Exception as e:
            logger.error(f"Failed to get latest VIX: {e}")
            return None

    def stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Symbol count
                cursor.execute("SELECT COUNT(DISTINCT underlying) FROM options_prices")
                symbol_count = cursor.fetchone()[0]

                # Date range
                cursor.execute("SELECT MIN(quote_date), MAX(quote_date) FROM options_prices")
                row = cursor.fetchone()
                min_date = row[0]
                max_date = row[1]

                # VIX count
                cursor.execute("SELECT COUNT(*) FROM vix_data")
                vix_count = cursor.fetchone()[0]

                return {
                    "symbols": symbol_count,
                    "min_date": min_date,
                    "max_date": max_date,
                    "vix_points": vix_count,
                    "db_path": str(self.db_path),
                    "connected": self._connected,
                }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_default_provider: Optional[LocalDBProvider] = None


def get_local_db_provider(db_path: Optional[Path] = None) -> LocalDBProvider:
    """
    Get the default LocalDBProvider instance.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.

    Args:
        db_path: Optional custom database path

    Returns:
        LocalDBProvider instance
    """
    try:
        from ..utils.deprecation import warn_singleton_usage

        warn_singleton_usage("get_local_db_provider", "ServiceContainer.local_db_provider")
    except ImportError:
        pass

    global _default_provider

    if _default_provider is None or (db_path and _default_provider.db_path != db_path):
        _default_provider = LocalDBProvider(db_path)

    return _default_provider


def reset_local_db_provider() -> None:
    """Reset the singleton (for testing)."""
    global _default_provider
    _default_provider = None
