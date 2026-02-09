# OptionPlay - Dividend History Manager
# ======================================
# SQLite-based storage for historical ex-dividend data
#
# E.5: Prevents ex-dividend gaps from being misinterpreted as pullbacks/dips.
#
# Usage:
#     from src.cache.dividend_history import DividendHistoryManager, get_dividend_history_manager
#
#     manager = get_dividend_history_manager()
#     manager.save_dividends("AAPL", [{"ex_date": "2025-02-07", "amount": 0.25}])
#     near = manager.is_near_ex_dividend("AAPL", date(2025, 2, 8))

import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_DB_PATH = Path.home() / ".optionplay" / "trades.db"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DividendRecord:
    """Single historical dividend record"""
    symbol: str
    ex_date: date
    amount: Optional[float] = None
    source: str = "yfinance"

    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary"""
        return {
            "symbol": self.symbol,
            "ex_date": self.ex_date.isoformat() if isinstance(self.ex_date, date) else self.ex_date,
            "amount": self.amount,
            "source": self.source,
        }


# =============================================================================
# DIVIDEND HISTORY MANAGER
# =============================================================================

class DividendHistoryManager:
    """
    Manager for historical ex-dividend data in SQLite.

    Features:
    - Thread-safe SQLite operations
    - Bulk insert for efficient storage
    - Query by symbol, date range
    - Check if near ex-dividend date (for gap filtering)
    - Batch query for scanner efficiency
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
        """Creates the dividend_history table if it does not exist"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dividend_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        ex_date DATE NOT NULL,
                        amount REAL,
                        source TEXT DEFAULT 'yfinance',
                        collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, ex_date)
                    )
                """)

                # Indices for fast queries
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_div_symbol_date
                    ON dividend_history(symbol, ex_date)
                """)

                conn.commit()
                logger.debug("dividend_history table initialized")

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def save_dividends(
        self,
        symbol: str,
        dividends: List[Dict[str, Any]],
        source: str = "yfinance"
    ) -> int:
        """
        Saves multiple dividend entries for a symbol.

        Args:
            symbol: Ticker symbol
            dividends: List of dicts with keys: ex_date, amount
            source: Data source

        Returns:
            Number of inserted/updated entries
        """
        if not dividends:
            return 0

        symbol = symbol.upper()
        inserted = 0

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                for div in dividends:
                    try:
                        cursor.execute("""
                            INSERT OR REPLACE INTO dividend_history (
                                symbol, ex_date, amount, source, collected_at
                            ) VALUES (?, ?, ?, ?, ?)
                        """, (
                            symbol,
                            div.get("ex_date"),
                            div.get("amount"),
                            source,
                            datetime.now().isoformat()
                        ))
                        inserted += 1

                    except sqlite3.Error as e:
                        logger.warning(f"Error saving {symbol} dividend: {e}")

                conn.commit()

        logger.debug(f"{symbol}: {inserted} dividend entries saved")
        return inserted

    def get_dividends(self, symbol: str) -> List[DividendRecord]:
        """
        Gets all historical dividends for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            List of DividendRecord, sorted by date (newest first)
        """
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol, ex_date, amount, source
                    FROM dividend_history
                    WHERE symbol = ?
                    ORDER BY ex_date DESC
                """, (symbol,))

                rows = cursor.fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_dividends_in_range(
        self,
        symbol: str,
        from_date: date,
        to_date: date
    ) -> List[DividendRecord]:
        """
        Gets dividends within a date range.

        Args:
            symbol: Ticker symbol
            from_date: Start date
            to_date: End date

        Returns:
            List of DividendRecord
        """
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol, ex_date, amount, source
                    FROM dividend_history
                    WHERE symbol = ? AND ex_date BETWEEN ? AND ?
                    ORDER BY ex_date DESC
                """, (symbol, from_date.isoformat(), to_date.isoformat()))

                rows = cursor.fetchall()

        return [self._row_to_record(row) for row in rows]

    def is_near_ex_dividend(
        self,
        symbol: str,
        target_date: date,
        days_before: int = 2,
        days_after: int = 1
    ) -> bool:
        """
        Checks if the target date is near an ex-dividend date.

        Ex-dividend day causes a price drop equal to the dividend amount.
        This can be misinterpreted as a pullback or dip signal.

        Args:
            symbol: Ticker symbol
            target_date: Date to check
            days_before: Days before ex-date to flag
            days_after: Days after ex-date to flag

        Returns:
            True if near an ex-dividend date
        """
        from_date = target_date - timedelta(days=days_after)
        to_date = target_date + timedelta(days=days_before)
        dividends = self.get_dividends_in_range(symbol, from_date, to_date)
        return len(dividends) > 0

    def is_near_ex_dividend_batch(
        self,
        symbols: List[str],
        target_date: date,
        days_before: int = 2,
        days_after: int = 1
    ) -> Dict[str, bool]:
        """
        Batch version of is_near_ex_dividend() for scanner efficiency.

        Single SQL query for all symbols.

        Args:
            symbols: List of ticker symbols
            target_date: Date to check
            days_before: Days before ex-date to flag
            days_after: Days after ex-date to flag

        Returns:
            Dict mapping symbol -> bool
        """
        if not symbols:
            return {}

        symbols_upper = [s.upper() for s in symbols]
        from_date = target_date - timedelta(days=days_after)
        to_date = target_date + timedelta(days=days_before)

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(symbols_upper))

                cursor.execute(f"""
                    SELECT DISTINCT symbol
                    FROM dividend_history
                    WHERE symbol IN ({placeholders})
                      AND ex_date BETWEEN ? AND ?
                """, (*symbols_upper, from_date.isoformat(), to_date.isoformat()))

                near_symbols = {row["symbol"] for row in cursor.fetchall()}

        return {s: s in near_symbols for s in symbols_upper}

    def get_ex_dividend_amount(
        self,
        symbol: str,
        target_date: date,
        days_window: int = 3
    ) -> Optional[float]:
        """
        Gets the dividend amount for the nearest ex-dividend date.

        Args:
            symbol: Ticker symbol
            target_date: Reference date
            days_window: Search window in days

        Returns:
            Dividend amount or None
        """
        from_date = target_date - timedelta(days=days_window)
        to_date = target_date + timedelta(days=days_window)
        dividends = self.get_dividends_in_range(symbol, from_date, to_date)

        if not dividends:
            return None

        # Return the nearest dividend's amount
        nearest = min(
            dividends,
            key=lambda d: abs((d.ex_date - target_date).days)
        )
        return nearest.amount

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_symbol_count(self) -> int:
        """Number of symbols with dividend data"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(DISTINCT symbol) FROM dividend_history")
                return cursor.fetchone()[0]

    def get_total_count(self) -> int:
        """Total number of dividend entries"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM dividend_history")
                return cursor.fetchone()[0]

    def get_statistics(self) -> Dict[str, Any]:
        """Returns statistics about the dividend history"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(DISTINCT symbol) FROM dividend_history")
                total_symbols = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM dividend_history")
                total_records = cursor.fetchone()[0]

                cursor.execute("SELECT MIN(ex_date), MAX(ex_date) FROM dividend_history")
                row = cursor.fetchone()
                date_range = (row[0], row[1]) if row and row[0] else (None, None)

        return {
            "total_symbols": total_symbols,
            "total_records": total_records,
            "date_range": {"from": date_range[0], "to": date_range[1]},
        }

    # =========================================================================
    # Helpers
    # =========================================================================

    def _row_to_record(self, row: sqlite3.Row) -> DividendRecord:
        """Converts SQLite Row to DividendRecord"""
        ex_date = row["ex_date"]
        if isinstance(ex_date, str):
            ex_date = date.fromisoformat(ex_date)

        return DividendRecord(
            symbol=row["symbol"],
            ex_date=ex_date,
            amount=row["amount"],
            source=row["source"],
        )

    def delete_symbol(self, symbol: str) -> int:
        """Deletes all dividends for a symbol"""
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM dividend_history WHERE symbol = ?", (symbol,))
                deleted = cursor.rowcount
                conn.commit()

        logger.info(f"{symbol}: {deleted} dividend entries deleted")
        return deleted

    def clear_all(self) -> int:
        """Deletes all dividend data (use with caution!)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM dividend_history")
                deleted = cursor.rowcount
                conn.commit()

        logger.warning(f"All {deleted} dividend entries deleted")
        return deleted


# =============================================================================
# SINGLETON & CONVENIENCE FUNCTIONS
# =============================================================================

_default_manager: Optional[DividendHistoryManager] = None
_manager_lock = threading.Lock()


def get_dividend_history_manager(db_path: Optional[Path] = None) -> DividendHistoryManager:
    """
    Returns global DividendHistoryManager instance.

    Thread-safe singleton pattern.
    """
    global _default_manager

    with _manager_lock:
        if _default_manager is None:
            _default_manager = DividendHistoryManager(db_path)
        return _default_manager


def reset_dividend_history_manager() -> None:
    """Resets the global manager (for tests)"""
    global _default_manager
    with _manager_lock:
        _default_manager = None
