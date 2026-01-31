# OptionPlay - Earnings History Manager
# ======================================
# SQLite-basierte Speicherung historischer Earnings-Daten
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
class EarningsRecord:
    """Einzelner historischer Earnings-Eintrag"""
    symbol: str
    earnings_date: date
    fiscal_year: Optional[int] = None
    fiscal_quarter: Optional[str] = None  # Q1, Q2, Q3, Q4
    eps_actual: Optional[float] = None
    eps_estimate: Optional[float] = None
    eps_surprise: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    time_of_day: Optional[str] = None  # 'bmo', 'amc', 'dmh'
    source: str = "marketdata"

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            "symbol": self.symbol,
            "earnings_date": self.earnings_date.isoformat() if isinstance(self.earnings_date, date) else self.earnings_date,
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
            "eps_actual": self.eps_actual,
            "eps_estimate": self.eps_estimate,
            "eps_surprise": self.eps_surprise,
            "eps_surprise_pct": self.eps_surprise_pct,
            "time_of_day": self.time_of_day,
            "source": self.source
        }


# =============================================================================
# EARNINGS HISTORY MANAGER
# =============================================================================

class EarningsHistoryManager:
    """
    Manager für historische Earnings-Daten in SQLite.

    Features:
    - Thread-safe SQLite Operationen
    - Bulk Insert für effiziente Speicherung
    - Abfragen nach Symbol, Datum, Zeitraum
    - Prüfung ob Earnings in der Nähe eines Datums waren
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._lock = threading.RLock()
        self._ensure_db_exists()
        self._create_table()

    def _ensure_db_exists(self) -> None:
        """Stellt sicher, dass das DB-Verzeichnis existiert"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self):
        """Context Manager für Thread-safe DB-Verbindung"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _create_table(self) -> None:
        """Erstellt die earnings_history Tabelle falls nicht vorhanden"""
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
                        source TEXT DEFAULT 'marketdata',
                        collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, earnings_date)
                    )
                """)

                # Indices für schnelle Abfragen
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
                logger.debug("earnings_history Tabelle initialisiert")

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def save_earnings(
        self,
        symbol: str,
        earnings_list: List[Dict[str, Any]],
        source: str = "marketdata"
    ) -> int:
        """
        Speichert mehrere Earnings-Einträge für ein Symbol.

        Args:
            symbol: Ticker-Symbol
            earnings_list: Liste von Earnings-Dicts (aus MarketDataProvider)
            source: Datenquelle

        Returns:
            Anzahl der eingefügten/aktualisierten Einträge
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
                        cursor.execute("""
                            INSERT OR REPLACE INTO earnings_history (
                                symbol, earnings_date, fiscal_year, fiscal_quarter,
                                eps_actual, eps_estimate, eps_surprise, eps_surprise_pct,
                                time_of_day, source, collected_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
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
                            datetime.now().isoformat()
                        ))
                        inserted += 1

                    except sqlite3.Error as e:
                        logger.warning(f"Fehler beim Speichern von {symbol} Earnings: {e}")

                conn.commit()

        logger.debug(f"{symbol}: {inserted} Earnings-Einträge gespeichert")
        return inserted

    def get_all_earnings(self, symbol: str) -> List[EarningsRecord]:
        """
        Holt alle historischen Earnings für ein Symbol.

        Args:
            symbol: Ticker-Symbol

        Returns:
            Liste von EarningsRecord, sortiert nach Datum (neueste zuerst)
        """
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol, earnings_date, fiscal_year, fiscal_quarter,
                           eps_actual, eps_estimate, eps_surprise, eps_surprise_pct,
                           time_of_day, source
                    FROM earnings_history
                    WHERE symbol = ?
                    ORDER BY earnings_date DESC
                """, (symbol,))

                rows = cursor.fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_earnings_in_range(
        self,
        symbol: str,
        from_date: date,
        to_date: date
    ) -> List[EarningsRecord]:
        """
        Holt Earnings in einem Datumsbereich.

        Args:
            symbol: Ticker-Symbol
            from_date: Start-Datum
            to_date: End-Datum

        Returns:
            Liste von EarningsRecord
        """
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol, earnings_date, fiscal_year, fiscal_quarter,
                           eps_actual, eps_estimate, eps_surprise, eps_surprise_pct,
                           time_of_day, source
                    FROM earnings_history
                    WHERE symbol = ? AND earnings_date BETWEEN ? AND ?
                    ORDER BY earnings_date DESC
                """, (symbol, from_date.isoformat(), to_date.isoformat()))

                rows = cursor.fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_earnings_around_date(
        self,
        symbol: str,
        target_date: date,
        days_window: int = 7
    ) -> List[EarningsRecord]:
        """
        Holt Earnings um ein bestimmtes Datum herum.

        Args:
            symbol: Ticker-Symbol
            target_date: Ziel-Datum
            days_window: Tage vor und nach dem Datum

        Returns:
            Liste von EarningsRecord im Zeitfenster
        """
        from_date = target_date - timedelta(days=days_window)
        to_date = target_date + timedelta(days=days_window)
        return self.get_earnings_in_range(symbol, from_date, to_date)

    def had_earnings_recently(
        self,
        symbol: str,
        target_date: date,
        days: int = 5
    ) -> bool:
        """
        Prüft ob in den letzten X Tagen vor target_date Earnings waren.

        Args:
            symbol: Ticker-Symbol
            target_date: Prüf-Datum
            days: Anzahl Tage zurückblicken

        Returns:
            True wenn Earnings im Zeitraum stattfanden
        """
        from_date = target_date - timedelta(days=days)
        earnings = self.get_earnings_in_range(symbol, from_date, target_date)
        return len(earnings) > 0

    def will_have_earnings_soon(
        self,
        symbol: str,
        target_date: date,
        days: int = 5
    ) -> bool:
        """
        Prüft ob in den nächsten X Tagen nach target_date Earnings sind.

        Args:
            symbol: Ticker-Symbol
            target_date: Prüf-Datum
            days: Anzahl Tage vorausschauen

        Returns:
            True wenn Earnings im Zeitraum stattfinden werden
        """
        to_date = target_date + timedelta(days=days)
        earnings = self.get_earnings_in_range(symbol, target_date, to_date)
        return len(earnings) > 0

    def is_near_earnings(
        self,
        symbol: str,
        target_date: date,
        days_before: int = 5,
        days_after: int = 2
    ) -> bool:
        """
        Prüft ob das Datum in der Nähe von Earnings liegt.

        Nützlich für Signal-Filterung: Vermeide Trades kurz vor oder nach Earnings.

        Args:
            symbol: Ticker-Symbol
            target_date: Prüf-Datum
            days_before: Tage vor Earnings zu vermeiden
            days_after: Tage nach Earnings zu vermeiden

        Returns:
            True wenn in der Nähe von Earnings
        """
        from_date = target_date - timedelta(days=days_after)  # Earnings die X Tage zurückliegen
        to_date = target_date + timedelta(days=days_before)   # Earnings die X Tage bevorstehen
        earnings = self.get_earnings_in_range(symbol, from_date, to_date)
        return len(earnings) > 0

    def get_nearest_earnings(
        self,
        symbol: str,
        target_date: date,
        search_days: int = 90
    ) -> Optional[EarningsRecord]:
        """
        Findet das nächste Earnings-Datum (vor oder nach target_date).

        Args:
            symbol: Ticker-Symbol
            target_date: Referenz-Datum
            search_days: Maximale Suchtage in beide Richtungen

        Returns:
            Nächstes EarningsRecord oder None
        """
        earnings = self.get_earnings_around_date(symbol, target_date, search_days)

        if not earnings:
            return None

        # Finde das nächste Earnings
        nearest = min(
            earnings,
            key=lambda e: abs((e.earnings_date - target_date).days)
        )
        return nearest

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_symbol_count(self) -> int:
        """Anzahl der Symbole mit Earnings-Daten"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(DISTINCT symbol) FROM earnings_history")
                return cursor.fetchone()[0]

    def get_total_earnings_count(self) -> int:
        """Gesamtanzahl der Earnings-Einträge"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM earnings_history")
                return cursor.fetchone()[0]

    def get_symbols_with_earnings(self) -> List[str]:
        """Liste aller Symbole mit Earnings-Daten"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT symbol FROM earnings_history ORDER BY symbol")
                return [row[0] for row in cursor.fetchall()]

    def get_date_range(self) -> Optional[tuple]:
        """Gibt den Datumsbereich der gespeicherten Earnings zurück"""
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
        """Gibt Statistiken über die Earnings-History zurück"""
        date_range = self.get_date_range()
        return {
            "total_symbols": self.get_symbol_count(),
            "total_earnings": self.get_total_earnings_count(),
            "date_range": {
                "from": date_range[0] if date_range else None,
                "to": date_range[1] if date_range else None
            }
        }

    # =========================================================================
    # Helpers
    # =========================================================================

    def _row_to_record(self, row: sqlite3.Row) -> EarningsRecord:
        """Konvertiert SQLite Row zu EarningsRecord"""
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
            source=row["source"]
        )

    def delete_symbol(self, symbol: str) -> int:
        """Löscht alle Earnings für ein Symbol"""
        symbol = symbol.upper()

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM earnings_history WHERE symbol = ?", (symbol,))
                deleted = cursor.rowcount
                conn.commit()

        logger.info(f"{symbol}: {deleted} Earnings-Einträge gelöscht")
        return deleted

    def clear_all(self) -> int:
        """Löscht alle Earnings-Daten (Vorsicht!)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM earnings_history")
                deleted = cursor.rowcount
                conn.commit()

        logger.warning(f"Alle {deleted} Earnings-Einträge gelöscht")
        return deleted

    # =========================================================================
    # ASYNC WRAPPERS (für non-blocking I/O in async contexts)
    # =========================================================================

    async def get_all_earnings_async(
        self,
        symbol: str,
        executor: Optional[ThreadPoolExecutor] = None
    ) -> List[EarningsRecord]:
        """
        Async wrapper für get_all_earnings().

        Args:
            symbol: Ticker-Symbol
            executor: Optional ThreadPoolExecutor

        Returns:
            Liste aller Earnings-Einträge
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor,
            partial(self.get_all_earnings, symbol)
        )

    async def is_near_earnings_async(
        self,
        symbol: str,
        target_date: date,
        days_before: int = 5,
        days_after: int = 2,
        executor: Optional[ThreadPoolExecutor] = None
    ) -> bool:
        """
        Async wrapper für is_near_earnings().

        Args:
            symbol: Ticker-Symbol
            target_date: Zieldatum
            days_before: Tage vor Earnings
            days_after: Tage nach Earnings
            executor: Optional ThreadPoolExecutor

        Returns:
            True wenn nahe an Earnings
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor,
            partial(self.is_near_earnings, symbol, target_date, days_before, days_after)
        )

    async def had_earnings_recently_async(
        self,
        symbol: str,
        target_date: date,
        days: int = 5,
        executor: Optional[ThreadPoolExecutor] = None
    ) -> bool:
        """
        Async wrapper für had_earnings_recently().

        Args:
            symbol: Ticker-Symbol
            target_date: Zieldatum
            days: Tage zurück
            executor: Optional ThreadPoolExecutor

        Returns:
            True wenn kürzlich Earnings waren
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor,
            partial(self.had_earnings_recently, symbol, target_date, days)
        )


# =============================================================================
# SINGLETON & CONVENIENCE FUNCTIONS
# =============================================================================

_default_manager: Optional[EarningsHistoryManager] = None
_manager_lock = threading.Lock()


def get_earnings_history_manager(db_path: Optional[Path] = None) -> EarningsHistoryManager:
    """
    Gibt globale EarningsHistoryManager Instanz zurück.

    Thread-safe Singleton-Pattern.
    """
    global _default_manager

    with _manager_lock:
        if _default_manager is None:
            _default_manager = EarningsHistoryManager(db_path)
        return _default_manager


def reset_earnings_history_manager() -> None:
    """Setzt den globalen Manager zurück (für Tests)"""
    global _default_manager
    with _manager_lock:
        _default_manager = None
