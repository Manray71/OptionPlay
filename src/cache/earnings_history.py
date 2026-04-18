# OptionPlay - Earnings History Manager
# ======================================
# SQLite-based storage for historical earnings data
#
# Usage:
#     from src.cache.earnings_history import EarningsHistoryManager, get_earnings_history_manager
#
#     manager = get_earnings_history_manager()
#     manager.save_earnings("AAPL", earnings_list)
#     earnings = manager.get_all_earnings("AAPL")
#     had_recent = manager.had_earnings_recently("AAPL", date(2024, 1, 15), days=5)

import asyncio
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ..constants.trading_rules import EARNINGS_QUARTERLY_MAX_GAP_DAYS, ENTRY_EARNINGS_MIN_DAYS
except ImportError:
    from constants.trading_rules import EARNINGS_QUARTERLY_MAX_GAP_DAYS, ENTRY_EARNINGS_MIN_DAYS

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_DB_PATH = Path.home() / ".optionplay" / "trades.db"


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class EarningsRecord:
    """Single historical earnings record"""

    symbol: str
    earnings_date: date
    fiscal_year: Optional[int] = None
    fiscal_quarter: Optional[str] = None  # Q1, Q2, Q3, Q4
    eps_actual: Optional[float] = None
    eps_estimate: Optional[float] = None
    eps_surprise: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    time_of_day: Optional[str] = None  # 'bmo', 'amc', 'dmh'
    source: str = "ibkr"

    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary"""
        return {
            "symbol": self.symbol,
            "earnings_date": (
                self.earnings_date.isoformat()
                if isinstance(self.earnings_date, date)
                else self.earnings_date
            ),
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
            "eps_actual": self.eps_actual,
            "eps_estimate": self.eps_estimate,
            "eps_surprise": self.eps_surprise,
            "eps_surprise_pct": self.eps_surprise_pct,
            "time_of_day": self.time_of_day,
            "source": self.source,
        }


# =============================================================================
# EARNINGS HISTORY MANAGER
# =============================================================================


class EarningsHistoryManager:
    """
    Manager for historical earnings data in SQLite.

    Features:
    - Thread-safe SQLite operations
    - Bulk insert for efficient storage
    - Queries by symbol, date, time period
    - Check if earnings were near a specific date
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._lock = threading.RLock()
        self._ensure_db_exists()
        self._create_table()

    def _ensure_db_exists(self) -> None:
        """Ensures that the DB directory exists"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self):
        """Context Manager for thread-safe DB connection"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _create_table(self) -> None:
        """Creates the earnings_history table if it does not exist"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS earnings_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        earnings_date DATE NOT NULL,
                        fiscal_year INTEGER,
                        fiscal_quarter TEXT,
                        eps_actual REAL,
                        eps_estimate REAL,
                        eps_surprise REAL,
                        eps_surprise_pct REAL,
                        time_of_day TEXT,
                        source TEXT DEFAULT 'ibkr',
                        collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, earnings_date)
                    )
                """)

                # Indices for fast queries
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_eh_symbol
                    ON earnings_history(symbol)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_eh_date
                    ON earnings_history(earnings_date)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_eh_symbol_date
                    ON earnings_history(symbol, earnings_date)
                """)

                conn.commit()
                logger.debug("earnings_history table initialized")

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def save_earnings(
        self, symbol: str, earnings_list: List[Dict[str, Any]], source: str = "ibkr"
    ) -> int:
        """
        Saves multiple earnings entries for a symbol.

        Args:
            symbol: Ticker symbol
            earnings_list: List of earnings dicts
            source: Data source

        Returns:
            Number of inserted/updated entries
        """
        if not earnings_list:
            return 0

        symbol = symbol.upper()
        inserted = 0

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                for earnings in earnings_list:
                    try:
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO earnings_history (
                                symbol, earnings_date, fiscal_year, fiscal_quarter,
                                eps_actual, eps_estimate, eps_surprise, eps_surprise_pct,
                                time_of_day, source, collected_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                symbol,
                                earnings.get("earnings_date"),
                                earnings.get("fiscal_year"),
                                earnings.get("fiscal_quarter"),
                                earnings.get("eps_actual"),
                                earnings.get("eps_estimate"),
                                earnings.get("eps_surprise"),
                                earnings.get("eps_surprise_pct"),
                                earnings.get("time_of_day"),
                                source,
                                datetime.now().isoformat(),
                            ),
                        )
                        inserted += 1

                    except sqlite3.Error as e:
                        logger.warning(f"Error saving {symbol} earnings: {e}")

                conn.commit()

        logger.debug(f"{symbol}: {inserted} earnings entries saved")
        return inserted

    def get_all_earnings(self, symbol: str) -> List[EarningsRecord]:
        """
        Gets all historical earnings for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            List of EarningsRecord, sorted by date (newest first)
        """
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT symbol, earnings_date, fiscal_year, fiscal_quarter,
                           eps_actual, eps_estimate, eps_surprise, eps_surprise_pct,
                           time_of_day, source
                    FROM earnings_history
                    WHERE symbol = ?
                    ORDER BY earnings_date DESC
                """,
                    (symbol,),
                )

                rows = cursor.fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_earnings_in_range(
        self, symbol: str, from_date: date, to_date: date
    ) -> List[EarningsRecord]:
        """
        Gets earnings within a date range.

        Args:
            symbol: Ticker symbol
            from_date: Start date
            to_date: End date

        Returns:
            List of EarningsRecord
        """
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT symbol, earnings_date, fiscal_year, fiscal_quarter,
                           eps_actual, eps_estimate, eps_surprise, eps_surprise_pct,
                           time_of_day, source
                    FROM earnings_history
                    WHERE symbol = ? AND earnings_date BETWEEN ? AND ?
                    ORDER BY earnings_date DESC
                """,
                    (symbol, from_date.isoformat(), to_date.isoformat()),
                )

                rows = cursor.fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_earnings_around_date(
        self, symbol: str, target_date: date, days_window: int = 7
    ) -> List[EarningsRecord]:
        """
        Gets earnings around a specific date.

        Args:
            symbol: Ticker symbol
            target_date: Target date
            days_window: Days before and after the date

        Returns:
            List of EarningsRecord within the time window
        """
        from_date = target_date - timedelta(days=days_window)
        to_date = target_date + timedelta(days=days_window)
        return self.get_earnings_in_range(symbol, from_date, to_date)

    def had_earnings_recently(self, symbol: str, target_date: date, days: int = 5) -> bool:
        """
        Checks if earnings occurred in the last X days before target_date.

        Args:
            symbol: Ticker symbol
            target_date: Check date
            days: Number of days to look back

        Returns:
            True if earnings occurred within the period
        """
        from_date = target_date - timedelta(days=days)
        earnings = self.get_earnings_in_range(symbol, from_date, target_date)
        return len(earnings) > 0

    def will_have_earnings_soon(self, symbol: str, target_date: date, days: int = 5) -> bool:
        """
        Checks if earnings are scheduled in the next X days after target_date.

        Args:
            symbol: Ticker symbol
            target_date: Check date
            days: Number of days to look ahead

        Returns:
            True if earnings will occur within the period
        """
        to_date = target_date + timedelta(days=days)
        earnings = self.get_earnings_in_range(symbol, target_date, to_date)
        return len(earnings) > 0

    def is_near_earnings(
        self, symbol: str, target_date: date, days_before: int = 5, days_after: int = 2
    ) -> bool:
        """
        Checks if the date is near earnings.

        Useful for signal filtering: Avoid trades shortly before or after earnings.

        Args:
            symbol: Ticker symbol
            target_date: Check date
            days_before: Days before earnings to avoid
            days_after: Days after earnings to avoid

        Returns:
            True if near earnings
        """
        from_date = target_date - timedelta(days=days_after)  # Earnings that are X days in the past
        to_date = target_date + timedelta(days=days_before)  # Earnings that are X days ahead
        earnings = self.get_earnings_in_range(symbol, from_date, to_date)
        return len(earnings) > 0

    def get_nearest_earnings(
        self, symbol: str, target_date: date, search_days: int = 90
    ) -> Optional[EarningsRecord]:
        """
        Finds the nearest earnings date (before or after target_date).

        Args:
            symbol: Ticker symbol
            target_date: Reference date
            search_days: Maximum search days in both directions

        Returns:
            Nearest EarningsRecord or None
        """
        earnings = self.get_earnings_around_date(symbol, target_date, search_days)

        if not earnings:
            return None

        # Find the nearest earnings
        nearest = min(earnings, key=lambda e: abs((e.earnings_date - target_date).days))
        return nearest

    def get_next_future_earnings(
        self, symbol: str, from_date: Optional[date] = None, search_days: int = 90
    ) -> Optional[EarningsRecord]:
        """
        Finds the next future earnings date.

        Args:
            symbol: Ticker symbol
            from_date: Start date (default: today)
            search_days: Maximum search days ahead

        Returns:
            Next future EarningsRecord or None (incl. time_of_day)
        """
        if from_date is None:
            from_date = date.today()

        to_date = from_date + timedelta(days=search_days)
        earnings = self.get_earnings_in_range(symbol, from_date, to_date)

        if not earnings:
            return None

        # Earnings are sorted by date DESC, so the last element is the next
        # But we want the earliest future one
        future_earnings = [e for e in earnings if e.earnings_date >= from_date]

        if not future_earnings:
            return None

        # The earliest future earnings
        return min(future_earnings, key=lambda e: e.earnings_date)

    def is_earnings_day_safe(
        self,
        symbol: str,
        target_date: date,
        min_days: int = ENTRY_EARNINGS_MIN_DAYS,
        allow_bmo_same_day: bool = False,
    ) -> tuple:
        """
        Checks if a symbol is safe for trading regarding earnings.

        IMPORTANT: BMO/AMC handling:
        - AMC (After Market Close): Do NOT trade on earnings day, reaction comes tomorrow
        - BMO (Before Market Open): Can trade the day AFTER earnings,
          as reaction is already priced in

        Args:
            symbol: Ticker symbol
            target_date: Check date (today)
            min_days: Minimum distance to earnings
            allow_bmo_same_day: Allow trading on BMO day itself? (conservative: False)

        Returns:
            Tuple (is_safe: bool, days_to_earnings: Optional[int], reason: str)
        """
        next_earnings = self.get_next_future_earnings(symbol, target_date)
        if next_earnings:
            return self._evaluate_earnings_safety(
                next_earnings, target_date, min_days, allow_bmo_same_day
            )

        # No future earnings found — check if recently reported
        symbol = symbol.upper()
        all_earnings = self.get_all_earnings(symbol)
        if all_earnings:
            last_date = all_earnings[0].earnings_date
            days_since = (target_date - last_date).days
            if days_since <= EARNINGS_QUARTERLY_MAX_GAP_DAYS:
                return (True, None, "recently_reported")

        return (False, None, "no_earnings_data")

    def _evaluate_earnings_safety(
        self,
        next_earnings: Optional[EarningsRecord],
        target_date: date,
        min_days: int,
        allow_bmo_same_day: bool,
    ) -> tuple:
        """
        Evaluates earnings safety for a single symbol.

        Internal helper used by both is_earnings_day_safe() and batch methods.
        """
        if not next_earnings:
            return (False, None, "no_earnings_data")

        days_to = (next_earnings.earnings_date - target_date).days
        time_of_day = next_earnings.time_of_day or "unknown"

        # Normalize time_of_day
        time_of_day_lower = time_of_day.lower() if time_of_day else "unknown"
        is_bmo = time_of_day_lower in ("before open", "bmo", "before market open")
        is_amc = time_of_day_lower in ("after close", "amc", "after market close")

        # Special case: Earnings today
        if days_to == 0:
            if is_amc:
                return (False, 0, "earnings_amc_today")
            elif is_bmo:
                if allow_bmo_same_day:
                    return (True, 0, "earnings_bmo_today_allowed")
                else:
                    return (False, 0, "earnings_bmo_today_conservative")
            else:
                return (False, 0, "earnings_today_unknown_time")

        # Standard case: Check minimum distance
        if days_to >= min_days:
            return (True, days_to, "safe")
        else:
            return (False, days_to, f"too_close_{days_to}d")

    def is_earnings_day_safe_batch(
        self,
        symbols: List[str],
        target_date: date,
        min_days: int = ENTRY_EARNINGS_MIN_DAYS,
        allow_bmo_same_day: bool = False,
    ) -> Dict[str, tuple]:
        """
        Batch version of is_earnings_day_safe() for multiple symbols.

        Loads all earnings data in a SINGLE SQL query for efficiency.
        This avoids N+1 query patterns when checking many symbols.

        Args:
            symbols: List of ticker symbols
            target_date: Reference date (usually today)
            min_days: Minimum days to earnings required
            allow_bmo_same_day: Allow trading on BMO day?

        Returns:
            Dict mapping symbol -> (is_safe, days_to_earnings, reason)
        """
        if not symbols:
            return {}

        symbols_upper = [s.upper() for s in symbols]
        search_days = 365

        # Calculate date range for query
        to_date = target_date + timedelta(days=search_days)

        # Single query for all symbols' future earnings
        # Also fetch the most recent PAST earnings for fallback
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(symbols_upper))

                # Future earnings
                cursor.execute(
                    f"""
                    SELECT symbol, earnings_date, time_of_day
                    FROM earnings_history
                    WHERE symbol IN ({placeholders})
                      AND earnings_date >= ?
                      AND earnings_date <= ?
                    ORDER BY symbol, earnings_date ASC
                """,
                    (*symbols_upper, target_date.isoformat(), to_date.isoformat()),
                )

                future_rows = cursor.fetchall()

                # Most recent past earnings per symbol (for fallback)
                cursor.execute(
                    f"""
                    SELECT symbol, MAX(earnings_date) as last_earnings
                    FROM earnings_history
                    WHERE symbol IN ({placeholders})
                      AND earnings_date < ?
                    GROUP BY symbol
                """,
                    (*symbols_upper, target_date.isoformat()),
                )

                past_rows = cursor.fetchall()

        # Map of most recent past earnings per symbol
        last_earnings_by_symbol: Dict[str, date] = {}
        for row in past_rows:
            last_date = row["last_earnings"]
            if isinstance(last_date, str):
                last_date = date.fromisoformat(last_date)
            last_earnings_by_symbol[row["symbol"]] = last_date

        # Group future earnings by symbol, keep only the nearest one
        next_earnings_by_symbol: Dict[str, Optional[EarningsRecord]] = {
            s: None for s in symbols_upper
        }

        for row in future_rows:
            symbol = row["symbol"]
            # Only keep the first (nearest) future earnings per symbol
            if next_earnings_by_symbol[symbol] is None:
                earnings_date = row["earnings_date"]
                if isinstance(earnings_date, str):
                    earnings_date = date.fromisoformat(earnings_date)

                next_earnings_by_symbol[symbol] = EarningsRecord(
                    symbol=symbol, earnings_date=earnings_date, time_of_day=row["time_of_day"]
                )

        # Evaluate safety for each symbol
        results: Dict[str, tuple] = {}
        for symbol in symbols_upper:
            next_earnings = next_earnings_by_symbol.get(symbol)

            if next_earnings:
                # Have future earnings date — use standard evaluation
                results[symbol] = self._evaluate_earnings_safety(
                    next_earnings, target_date, min_days, allow_bmo_same_day
                )
            else:
                # No future earnings in DB — check if recently reported
                last_date = last_earnings_by_symbol.get(symbol)
                if last_date:
                    days_since = (target_date - last_date).days
                    if days_since <= EARNINGS_QUARTERLY_MAX_GAP_DAYS:
                        # Recently reported — quarterly earnings are ~90 days
                        # apart, so next is likely far enough away
                        results[symbol] = (True, None, "recently_reported")
                    else:
                        # Has earnings history but no future date
                        results[symbol] = (False, None, "no_earnings_data")
                else:
                    # No earnings data at all
                    results[symbol] = (False, None, "no_earnings_data")

        return results

    def get_next_earnings_dates_batch(self, symbols: List[str]) -> Dict[str, Optional[date]]:
        """Return the next future earnings date per symbol via a single SQL query.

        Used by the scanner to pre-populate _earnings_cache before the scan loop.

        Args:
            symbols: List of ticker symbols

        Returns:
            Dict mapping symbol (upper-case) -> next earnings date, or None if not found
        """
        if not symbols:
            return {}

        symbols_upper = [s.upper() for s in symbols]
        today = date.today().isoformat()
        placeholders = ",".join("?" * len(symbols_upper))

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    SELECT symbol, MIN(earnings_date) AS next_earnings
                    FROM earnings_history
                    WHERE symbol IN ({placeholders})
                      AND earnings_date >= ?
                    GROUP BY symbol
                    """,
                    (*symbols_upper, today),
                )
                rows = cursor.fetchall()

        result: Dict[str, Optional[date]] = {s: None for s in symbols_upper}
        for row in rows:
            d = row["next_earnings"]
            if d is not None:
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                result[row["symbol"]] = d

        return result

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_symbol_count(self) -> int:
        """Number of symbols with earnings data"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(DISTINCT symbol) FROM earnings_history")
                return cursor.fetchone()[0]

    def get_total_earnings_count(self) -> int:
        """Total number of earnings entries"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM earnings_history")
                return cursor.fetchone()[0]

    def get_symbols_with_earnings(self) -> List[str]:
        """List of all symbols with earnings data"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT symbol FROM earnings_history ORDER BY symbol")
                return [row[0] for row in cursor.fetchall()]

    def get_date_range(self) -> Optional[tuple]:
        """Returns the date range of stored earnings"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MIN(earnings_date), MAX(earnings_date)
                    FROM earnings_history
                """)
                row = cursor.fetchone()
                if row and row[0]:
                    return (row[0], row[1])
                return None

    def get_statistics(self) -> Dict[str, Any]:
        """Returns statistics about the earnings history"""
        date_range = self.get_date_range()
        return {
            "total_symbols": self.get_symbol_count(),
            "total_earnings": self.get_total_earnings_count(),
            "date_range": {
                "from": date_range[0] if date_range else None,
                "to": date_range[1] if date_range else None,
            },
        }

    # =========================================================================
    # Helpers
    # =========================================================================

    def _row_to_record(self, row: sqlite3.Row) -> EarningsRecord:
        """Converts SQLite Row to EarningsRecord"""
        earnings_date = row["earnings_date"]
        if isinstance(earnings_date, str):
            earnings_date = date.fromisoformat(earnings_date)

        return EarningsRecord(
            symbol=row["symbol"],
            earnings_date=earnings_date,
            fiscal_year=row["fiscal_year"],
            fiscal_quarter=row["fiscal_quarter"],
            eps_actual=row["eps_actual"],
            eps_estimate=row["eps_estimate"],
            eps_surprise=row["eps_surprise"],
            eps_surprise_pct=row["eps_surprise_pct"],
            time_of_day=row["time_of_day"],
            source=row["source"],
        )

    def delete_symbol(self, symbol: str) -> int:
        """Deletes all earnings for a symbol"""
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM earnings_history WHERE symbol = ?", (symbol,))
                deleted = cursor.rowcount
                conn.commit()

        logger.info(f"{symbol}: {deleted} earnings entries deleted")
        return deleted

    def clear_all(self) -> int:
        """Deletes all earnings data (use with caution!)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM earnings_history")
                deleted = cursor.rowcount
                conn.commit()

        logger.warning(f"All {deleted} earnings entries deleted")
        return deleted

    # =========================================================================
    # ASYNC WRAPPERS (for non-blocking I/O in async contexts)
    # =========================================================================

    async def get_all_earnings_async(
        self, symbol: str, executor: Optional[ThreadPoolExecutor] = None
    ) -> List[EarningsRecord]:
        """
        Async wrapper for get_all_earnings().

        Args:
            symbol: Ticker symbol
            executor: Optional ThreadPoolExecutor

        Returns:
            List of all earnings entries
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, partial(self.get_all_earnings, symbol))

    async def is_near_earnings_async(
        self,
        symbol: str,
        target_date: date,
        days_before: int = 5,
        days_after: int = 2,
        executor: Optional[ThreadPoolExecutor] = None,
    ) -> bool:
        """
        Async wrapper for is_near_earnings().

        Args:
            symbol: Ticker symbol
            target_date: Target date
            days_before: Days before earnings
            days_after: Days after earnings
            executor: Optional ThreadPoolExecutor

        Returns:
            True if near earnings
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor, partial(self.is_near_earnings, symbol, target_date, days_before, days_after)
        )

    async def had_earnings_recently_async(
        self,
        symbol: str,
        target_date: date,
        days: int = 5,
        executor: Optional[ThreadPoolExecutor] = None,
    ) -> bool:
        """
        Async wrapper for had_earnings_recently().

        Args:
            symbol: Ticker symbol
            target_date: Target date
            days: Days back
            executor: Optional ThreadPoolExecutor

        Returns:
            True if there were recent earnings
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor, partial(self.had_earnings_recently, symbol, target_date, days)
        )

    async def is_earnings_day_safe_batch_async(
        self,
        symbols: List[str],
        target_date: date,
        min_days: int = ENTRY_EARNINGS_MIN_DAYS,
        allow_bmo_same_day: bool = False,
        executor: Optional[ThreadPoolExecutor] = None,
    ) -> Dict[str, tuple]:
        """
        Async wrapper for is_earnings_day_safe_batch().

        Runs the batch query in a thread pool to avoid blocking the event loop.

        Args:
            symbols: List of ticker symbols
            target_date: Reference date
            min_days: Minimum days to earnings
            allow_bmo_same_day: Allow trading on BMO day?
            executor: Optional ThreadPoolExecutor

        Returns:
            Dict mapping symbol -> (is_safe, days_to_earnings, reason)
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor,
            partial(
                self.is_earnings_day_safe_batch, symbols, target_date, min_days, allow_bmo_same_day
            ),
        )


# =============================================================================
# SINGLETON & CONVENIENCE FUNCTIONS
# =============================================================================

_default_manager: Optional[EarningsHistoryManager] = None
_manager_lock = threading.Lock()


def get_earnings_history_manager(db_path: Optional[Path] = None) -> EarningsHistoryManager:
    """
    Returns global EarningsHistoryManager instance.

    Prefers the global ServiceContainer if available, otherwise
    falls back to the module-level singleton.
    """
    # Prefer container if available
    try:
        from ..container import _default_container

        if (
            _default_container is not None
            and _default_container.earnings_history_manager is not None
        ):
            return _default_container.earnings_history_manager
    except ImportError:
        pass

    global _default_manager

    with _manager_lock:
        if _default_manager is None:
            _default_manager = EarningsHistoryManager(db_path)
        return _default_manager


def reset_earnings_history_manager() -> None:
    """Resets the global manager (for tests)"""
    global _default_manager
    with _manager_lock:
        _default_manager = None
    try:
        from ..container import _default_container

        if _default_container is not None:
            _default_container.earnings_history_manager = None
    except ImportError:
        pass
