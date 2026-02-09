# OptionPlay - Trade Tracker (Facade)
# ====================================
# SQLite-basiertes Trade-Tracking für kontinuierliches Training
# Inkl. historische Preisdaten für Re-Training
#
# Refactored in Phase 2.3: Models extrahiert nach models.py
# Refactored in Phase 6b: Facade-Pattern, delegiert an Sub-Module

import json
import sqlite3
import logging
import zlib
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from contextlib import contextmanager

from .models import (
    TradeStatus,
    TradeOutcome,
    TrackedTrade,
    TradeStats,
    PriceBar,
    SymbolPriceData,
    VixDataPoint,
    OptionBar,
)
from .trade_crud import TradeCRUD
from .trade_analysis import TradeAnalysis
from .price_storage import PriceStorage
from .vix_storage import VixStorage
from .options_storage import OptionsStorage

logger = logging.getLogger(__name__)


class TradeTracker:
    """
    SQLite-basierter Trade Tracker (Facade).

    Delegiert an spezialisierte Sub-Module:
    - TradeCRUD: Trade CRUD operations
    - TradeAnalysis: Statistics, export, storage stats
    - PriceStorage: Historical price data (compressed JSON)
    - VixStorage: VIX historical data
    - OptionsStorage: Historical options data

    Usage:
        tracker = TradeTracker()

        # Trade eröffnen
        trade = TrackedTrade(
            symbol="AAPL",
            strategy="pullback",
            signal_date=date.today(),
            signal_score=8.5,
            entry_price=175.00,
            stop_loss=170.00,
            target_price=185.00,
        )
        trade_id = tracker.add_trade(trade)

        # Trade schließen
        tracker.close_trade(
            trade_id,
            exit_price=182.50,
            outcome=TradeOutcome.WIN,
            exit_reason="target_reached"
        )

        # Statistiken
        stats = tracker.get_stats()
        print(f"Win Rate: {stats.win_rate:.1f}%")

        # Für Training exportieren
        training_data = tracker.export_for_training(
            min_date=date(2023, 1, 1),
            strategies=["pullback"]
        )
    """

    # Schema Version für Migrations
    SCHEMA_VERSION = 3  # v3: Added options_data table

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Initialisiert den Trade Tracker.

        Args:
            db_path: Pfad zur SQLite-Datenbank.
                     Default: ~/.optionplay/trades.db
        """
        if db_path is None:
            db_dir = Path.home() / ".optionplay"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "trades.db")

        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

        # Initialize sub-modules with shared connection factory
        self._trade_crud = TradeCRUD(self._get_connection)
        self._price_storage = PriceStorage(self._get_connection)
        self._vix_storage = VixStorage(self._get_connection)
        self._options_storage = OptionsStorage(self._get_connection)
        self._trade_analysis = TradeAnalysis(self._get_connection, self._trade_crud)

    def _ensure_connection(self) -> sqlite3.Connection:
        """Erstellt oder gibt bestehende Connection zurück (mit WAL-Mode)."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    @contextmanager
    def _get_connection(self):
        """Context Manager für Datenbankverbindung (wiederverwendet Connection)."""
        conn = self._ensure_connection()
        try:
            yield conn
            conn.commit()
        except (sqlite3.DatabaseError, OSError):
            conn.rollback()
            raise

    def close(self) -> None:
        """Schließt die DB-Connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _init_db(self):
        """Initialisiert die Datenbank mit Schema"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Trades-Tabelle
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,

                    signal_date TEXT,
                    signal_score REAL,
                    signal_strength TEXT,
                    score_breakdown TEXT,

                    vix_at_signal REAL,
                    iv_rank_at_signal REAL,

                    entry_price REAL,
                    stop_loss REAL,
                    target_price REAL,

                    status TEXT DEFAULT 'open',
                    outcome TEXT DEFAULT 'pending',

                    exit_date TEXT,
                    exit_price REAL,
                    exit_reason TEXT,

                    pnl_amount REAL,
                    pnl_percent REAL,
                    holding_days INTEGER,

                    signal_reliability_grade TEXT,
                    signal_reliability_win_rate REAL,

                    created_at TEXT,
                    updated_at TEXT,
                    notes TEXT,
                    tags TEXT
                )
            """)

            # Indices für schnelle Queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_symbol
                ON trades(symbol)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_strategy
                ON trades(strategy)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_status
                ON trades(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_signal_date
                ON trades(signal_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_signal_score
                ON trades(signal_score)
            """)

            # Meta-Tabelle für Schema-Version
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # ================================================
            # Historische Preisdaten (für Re-Training)
            # ================================================

            # Symbol-Preisdaten (komprimiert als JSON-Blobs)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    bar_count INTEGER,
                    data_compressed BLOB,
                    created_at TEXT,
                    updated_at TEXT,
                    UNIQUE(symbol, start_date, end_date)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_data_symbol
                ON price_data(symbol)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_data_dates
                ON price_data(start_date, end_date)
            """)

            # VIX-Historie
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vix_data (
                    date TEXT PRIMARY KEY,
                    value REAL NOT NULL,
                    created_at TEXT
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_vix_data_date
                ON vix_data(date)
            """)

            # ================================================
            # Historische Options-Daten
            # ================================================

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS options_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occ_symbol TEXT NOT NULL,
                    underlying TEXT NOT NULL,
                    strike REAL NOT NULL,
                    expiry TEXT NOT NULL,
                    option_type TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL NOT NULL,
                    volume INTEGER,
                    created_at TEXT,
                    UNIQUE(occ_symbol, trade_date)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_options_underlying
                ON options_data(underlying)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_options_expiry
                ON options_data(expiry)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_options_trade_date
                ON options_data(trade_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_options_occ_symbol
                ON options_data(occ_symbol)
            """)

            # Schema-Version setzen
            cursor.execute("""
                INSERT OR REPLACE INTO meta (key, value)
                VALUES ('schema_version', ?)
            """, (str(self.SCHEMA_VERSION),))

    # =========================================================================
    # Trade CRUD Operations (delegated to TradeCRUD)
    # =========================================================================

    def add_trade(self, trade: TrackedTrade) -> int:
        return self._trade_crud.add_trade(trade)

    def get_trade(self, trade_id: int) -> Optional[TrackedTrade]:
        return self._trade_crud.get_trade(trade_id)

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        outcome: TradeOutcome,
        exit_date: Optional[date] = None,
        exit_reason: str = "",
    ) -> bool:
        return self._trade_crud.close_trade(trade_id, exit_price, outcome, exit_date, exit_reason)

    def update_trade(self, trade_id: int, **updates) -> bool:
        return self._trade_crud.update_trade(trade_id, **updates)

    def get_open_trades(self) -> List[TrackedTrade]:
        return self._trade_crud.get_open_trades()

    def query_trades(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        status: Optional[TradeStatus] = None,
        outcome: Optional[TradeOutcome] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        limit: int = 1000,
    ) -> List[TrackedTrade]:
        return self._trade_crud.query_trades(
            symbol=symbol, strategy=strategy, status=status, outcome=outcome,
            min_score=min_score, max_score=max_score, min_date=min_date,
            max_date=max_date, limit=limit,
        )

    def delete_trade(self, trade_id: int) -> bool:
        return self._trade_crud.delete_trade(trade_id)

    def count_trades(
        self,
        strategy: Optional[str] = None,
        status: Optional[TradeStatus] = None,
    ) -> int:
        return self._trade_crud.count_trades(strategy=strategy, status=status)

    # =========================================================================
    # Statistics (delegated to TradeAnalysis)
    # =========================================================================

    def get_stats(
        self,
        strategy: Optional[str] = None,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
    ) -> TradeStats:
        return self._trade_analysis.get_stats(strategy=strategy, min_date=min_date, max_date=max_date)

    # =========================================================================
    # Export for Training (delegated to TradeAnalysis)
    # =========================================================================

    def export_for_training(
        self,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        strategies: Optional[List[str]] = None,
        min_trades: int = 50,
    ) -> Dict[str, Any]:
        return self._trade_analysis.export_for_training(
            min_date=min_date, max_date=max_date, strategies=strategies, min_trades=min_trades,
        )

    # =========================================================================
    # Historische Preisdaten (delegated to PriceStorage)
    # =========================================================================

    def store_price_data(
        self,
        symbol: str,
        bars: List[PriceBar],
        merge: bool = True,
    ) -> int:
        return self._price_storage.store_price_data(symbol, bars, merge)

    def get_price_data(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Optional[SymbolPriceData]:
        return self._price_storage.get_price_data(symbol, start_date, end_date)

    def get_price_data_range(self, symbol: str) -> Optional[Tuple[date, date]]:
        return self._price_storage.get_price_data_range(symbol)

    def list_symbols_with_price_data(self) -> List[Dict[str, Any]]:
        return self._price_storage.list_symbols_with_price_data()

    def delete_price_data(self, symbol: str) -> bool:
        return self._price_storage.delete_price_data(symbol)

    # =========================================================================
    # VIX-Daten (delegated to VixStorage)
    # =========================================================================

    def store_vix_data(self, vix_points: List[VixDataPoint]) -> int:
        return self._vix_storage.store_vix_data(vix_points)

    def get_vix_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[VixDataPoint]:
        return self._vix_storage.get_vix_data(start_date, end_date)

    def get_vix_at_date(self, target_date: date) -> Optional[float]:
        return self._vix_storage.get_vix_at_date(target_date)

    def get_vix_range(self) -> Optional[Tuple[date, date]]:
        return self._vix_storage.get_vix_range()

    def count_vix_data(self) -> int:
        return self._vix_storage.count_vix_data()

    # =========================================================================
    # Historische Options-Daten (delegated to OptionsStorage)
    # =========================================================================

    def store_option_bars(self, bars: List[OptionBar]) -> int:
        return self._options_storage.store_option_bars(bars)

    def get_option_history(
        self,
        occ_symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[OptionBar]:
        return self._options_storage.get_option_history(occ_symbol, start_date, end_date)

    def get_options_for_underlying(
        self,
        underlying: str,
        expiry: Optional[date] = None,
        option_type: Optional[str] = None,
        trade_date: Optional[date] = None,
    ) -> List[OptionBar]:
        return self._options_storage.get_options_for_underlying(
            underlying, expiry, option_type, trade_date,
        )

    def get_option_at_date(
        self,
        occ_symbol: str,
        trade_date: date,
    ) -> Optional[OptionBar]:
        return self._options_storage.get_option_at_date(occ_symbol, trade_date)

    def get_spread_history(
        self,
        short_occ: str,
        long_occ: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        return self._options_storage.get_spread_history(short_occ, long_occ, start_date, end_date)

    def list_options_underlyings(self) -> List[Dict[str, Any]]:
        return self._options_storage.list_options_underlyings()

    def count_option_bars(self, underlying: Optional[str] = None) -> int:
        return self._options_storage.count_option_bars(underlying)

    def delete_option_data(self, underlying: Optional[str] = None, occ_symbol: Optional[str] = None) -> int:
        return self._options_storage.delete_option_data(underlying, occ_symbol)

    # =========================================================================
    # Bulk-Export für Training (delegated to TradeAnalysis)
    # =========================================================================

    def export_for_backtesting(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        return self._trade_analysis.export_for_backtesting(
            symbols=symbols, start_date=start_date, end_date=end_date,
            price_storage=self._price_storage, vix_storage=self._vix_storage,
        )

    def get_storage_stats(self) -> Dict[str, Any]:
        return self._trade_analysis.get_storage_stats(self.db_path)
