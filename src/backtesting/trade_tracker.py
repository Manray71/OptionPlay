# OptionPlay - Trade Tracker
# ==========================
# SQLite-basiertes Trade-Tracking für kontinuierliches Training
# Inkl. historische Preisdaten für Re-Training

import json
import sqlite3
import logging
import zlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class TradeStatus(Enum):
    """Status eines Trades"""
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TradeOutcome(Enum):
    """Ergebnis eines geschlossenen Trades"""
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    PENDING = "pending"


@dataclass
class TrackedTrade:
    """
    Ein getrackter Trade mit allen relevanten Daten für Training.

    Enthält Signal-Informationen, Einstieg, Ausstieg und Outcome.
    """
    # Identifikation
    id: Optional[int] = None
    symbol: str = ""
    strategy: str = ""

    # Signal bei Einstieg
    signal_date: Optional[date] = None
    signal_score: float = 0.0
    signal_strength: str = ""
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    # Marktkontext
    vix_at_signal: Optional[float] = None
    iv_rank_at_signal: Optional[float] = None

    # Preise
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None

    # Trade-Status
    status: TradeStatus = TradeStatus.OPEN
    outcome: TradeOutcome = TradeOutcome.PENDING

    # Exit-Informationen
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""

    # P&L
    pnl_amount: Optional[float] = None
    pnl_percent: Optional[float] = None

    # Holding Period
    holding_days: Optional[int] = None

    # Reliability bei Signal (für Vergleich)
    signal_reliability_grade: Optional[str] = None
    signal_reliability_win_rate: Optional[float] = None

    # Meta
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    notes: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        result = {
            'id': self.id,
            'symbol': self.symbol,
            'strategy': self.strategy,
            'signal_date': self.signal_date.isoformat() if self.signal_date else None,
            'signal_score': self.signal_score,
            'signal_strength': self.signal_strength,
            'score_breakdown': self.score_breakdown,
            'vix_at_signal': self.vix_at_signal,
            'iv_rank_at_signal': self.iv_rank_at_signal,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'target_price': self.target_price,
            'status': self.status.value,
            'outcome': self.outcome.value,
            'exit_date': self.exit_date.isoformat() if self.exit_date else None,
            'exit_price': self.exit_price,
            'exit_reason': self.exit_reason,
            'pnl_amount': self.pnl_amount,
            'pnl_percent': self.pnl_percent,
            'holding_days': self.holding_days,
            'signal_reliability_grade': self.signal_reliability_grade,
            'signal_reliability_win_rate': self.signal_reliability_win_rate,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'notes': self.notes,
            'tags': self.tags,
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackedTrade":
        """Erstellt TrackedTrade aus Dictionary"""
        return cls(
            id=data.get('id'),
            symbol=data.get('symbol', ''),
            strategy=data.get('strategy', ''),
            signal_date=date.fromisoformat(data['signal_date']) if data.get('signal_date') else None,
            signal_score=data.get('signal_score', 0.0),
            signal_strength=data.get('signal_strength', ''),
            score_breakdown=data.get('score_breakdown', {}),
            vix_at_signal=data.get('vix_at_signal'),
            iv_rank_at_signal=data.get('iv_rank_at_signal'),
            entry_price=data.get('entry_price'),
            stop_loss=data.get('stop_loss'),
            target_price=data.get('target_price'),
            status=TradeStatus(data.get('status', 'open')),
            outcome=TradeOutcome(data.get('outcome', 'pending')),
            exit_date=date.fromisoformat(data['exit_date']) if data.get('exit_date') else None,
            exit_price=data.get('exit_price'),
            exit_reason=data.get('exit_reason', ''),
            pnl_amount=data.get('pnl_amount'),
            pnl_percent=data.get('pnl_percent'),
            holding_days=data.get('holding_days'),
            signal_reliability_grade=data.get('signal_reliability_grade'),
            signal_reliability_win_rate=data.get('signal_reliability_win_rate'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.now(),
            notes=data.get('notes', ''),
            tags=data.get('tags', []),
        )


@dataclass
class TradeStats:
    """Aggregierte Trade-Statistiken"""
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0

    wins: int = 0
    losses: int = 0
    breakeven: int = 0

    win_rate: float = 0.0
    avg_pnl_percent: float = 0.0
    total_pnl: float = 0.0

    avg_holding_days: float = 0.0
    avg_score: float = 0.0

    # By Score Bucket
    by_score_bucket: Dict[str, Dict] = field(default_factory=dict)

    # By Strategy
    by_strategy: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class PriceBar:
    """Eine einzelne Preis-Kerze (OHLCV)"""
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'date': self.date.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PriceBar":
        return cls(
            date=date.fromisoformat(data['date']),
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data['volume'],
        )


@dataclass
class SymbolPriceData:
    """Historische Preisdaten für ein Symbol"""
    symbol: str
    bars: List[PriceBar]
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    bar_count: int = 0

    def __post_init__(self):
        if self.bars:
            self.first_date = min(b.date for b in self.bars)
            self.last_date = max(b.date for b in self.bars)
            self.bar_count = len(self.bars)


@dataclass
class VixDataPoint:
    """Ein VIX-Datenpunkt"""
    date: date
    value: float

    def to_dict(self) -> Dict[str, Any]:
        return {'date': self.date.isoformat(), 'value': self.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VixDataPoint":
        return cls(
            date=date.fromisoformat(data['date']),
            value=data['value'],
        )


class TradeTracker:
    """
    SQLite-basierter Trade Tracker.

    Speichert alle Trades für:
    - Kontinuierliches Training
    - Performance-Analyse
    - Score-Validierung

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
    SCHEMA_VERSION = 2  # v2: Added price_data and vix_data tables

    def __init__(self, db_path: Optional[str] = None):
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
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context Manager für Datenbankverbindung"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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

            # Schema-Version setzen
            cursor.execute("""
                INSERT OR REPLACE INTO meta (key, value)
                VALUES ('schema_version', ?)
            """, (str(self.SCHEMA_VERSION),))

    def add_trade(self, trade: TrackedTrade) -> int:
        """
        Fügt einen neuen Trade hinzu.

        Args:
            trade: TrackedTrade-Objekt

        Returns:
            ID des eingefügten Trades
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            now = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO trades (
                    symbol, strategy,
                    signal_date, signal_score, signal_strength, score_breakdown,
                    vix_at_signal, iv_rank_at_signal,
                    entry_price, stop_loss, target_price,
                    status, outcome,
                    exit_date, exit_price, exit_reason,
                    pnl_amount, pnl_percent, holding_days,
                    signal_reliability_grade, signal_reliability_win_rate,
                    created_at, updated_at, notes, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.symbol,
                trade.strategy,
                trade.signal_date.isoformat() if trade.signal_date else None,
                trade.signal_score,
                trade.signal_strength,
                json.dumps(trade.score_breakdown),
                trade.vix_at_signal,
                trade.iv_rank_at_signal,
                trade.entry_price,
                trade.stop_loss,
                trade.target_price,
                trade.status.value,
                trade.outcome.value,
                trade.exit_date.isoformat() if trade.exit_date else None,
                trade.exit_price,
                trade.exit_reason,
                trade.pnl_amount,
                trade.pnl_percent,
                trade.holding_days,
                trade.signal_reliability_grade,
                trade.signal_reliability_win_rate,
                now,
                now,
                trade.notes,
                json.dumps(trade.tags),
            ))

            trade_id = cursor.lastrowid
            logger.info(f"Added trade {trade_id}: {trade.symbol} {trade.strategy}")
            return trade_id

    def get_trade(self, trade_id: int) -> Optional[TrackedTrade]:
        """
        Holt einen Trade nach ID.

        Args:
            trade_id: Trade-ID

        Returns:
            TrackedTrade oder None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
            row = cursor.fetchone()

            if row is None:
                return None

            return self._row_to_trade(row)

    def _row_to_trade(self, row: sqlite3.Row) -> TrackedTrade:
        """Konvertiert DB-Row zu TrackedTrade"""
        return TrackedTrade(
            id=row['id'],
            symbol=row['symbol'],
            strategy=row['strategy'],
            signal_date=date.fromisoformat(row['signal_date']) if row['signal_date'] else None,
            signal_score=row['signal_score'] or 0.0,
            signal_strength=row['signal_strength'] or '',
            score_breakdown=json.loads(row['score_breakdown']) if row['score_breakdown'] else {},
            vix_at_signal=row['vix_at_signal'],
            iv_rank_at_signal=row['iv_rank_at_signal'],
            entry_price=row['entry_price'],
            stop_loss=row['stop_loss'],
            target_price=row['target_price'],
            status=TradeStatus(row['status']),
            outcome=TradeOutcome(row['outcome']),
            exit_date=date.fromisoformat(row['exit_date']) if row['exit_date'] else None,
            exit_price=row['exit_price'],
            exit_reason=row['exit_reason'] or '',
            pnl_amount=row['pnl_amount'],
            pnl_percent=row['pnl_percent'],
            holding_days=row['holding_days'],
            signal_reliability_grade=row['signal_reliability_grade'],
            signal_reliability_win_rate=row['signal_reliability_win_rate'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else datetime.now(),
            notes=row['notes'] or '',
            tags=json.loads(row['tags']) if row['tags'] else [],
        )

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        outcome: TradeOutcome,
        exit_date: Optional[date] = None,
        exit_reason: str = "",
    ) -> bool:
        """
        Schließt einen Trade.

        Args:
            trade_id: Trade-ID
            exit_price: Ausstiegspreis
            outcome: WIN/LOSS/BREAKEVEN
            exit_date: Ausstiegsdatum (default: heute)
            exit_reason: Grund für Ausstieg

        Returns:
            True wenn erfolgreich
        """
        trade = self.get_trade(trade_id)
        if trade is None:
            logger.warning(f"Trade {trade_id} not found")
            return False

        if trade.status != TradeStatus.OPEN:
            logger.warning(f"Trade {trade_id} is not open (status: {trade.status})")
            return False

        exit_date = exit_date or date.today()

        # P&L berechnen
        pnl_amount = None
        pnl_percent = None
        if trade.entry_price and exit_price:
            pnl_amount = exit_price - trade.entry_price
            pnl_percent = (pnl_amount / trade.entry_price) * 100

        # Holding Days berechnen
        holding_days = None
        if trade.signal_date:
            holding_days = (exit_date - trade.signal_date).days

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trades SET
                    status = ?,
                    outcome = ?,
                    exit_date = ?,
                    exit_price = ?,
                    exit_reason = ?,
                    pnl_amount = ?,
                    pnl_percent = ?,
                    holding_days = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                TradeStatus.CLOSED.value,
                outcome.value,
                exit_date.isoformat(),
                exit_price,
                exit_reason,
                pnl_amount,
                pnl_percent,
                holding_days,
                datetime.now().isoformat(),
                trade_id,
            ))

            logger.info(f"Closed trade {trade_id}: {outcome.value}, P&L: {pnl_percent:.2f}%")
            return True

    def update_trade(self, trade_id: int, **updates) -> bool:
        """
        Aktualisiert Trade-Felder.

        Args:
            trade_id: Trade-ID
            **updates: Felder zum Aktualisieren

        Returns:
            True wenn erfolgreich
        """
        allowed_fields = {
            'notes', 'tags', 'stop_loss', 'target_price',
            'vix_at_signal', 'iv_rank_at_signal',
        }

        # Filter nur erlaubte Felder
        updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not updates:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # JSON-Felder konvertieren
            if 'tags' in updates:
                updates['tags'] = json.dumps(updates['tags'])

            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [datetime.now().isoformat(), trade_id]

            cursor.execute(f"""
                UPDATE trades SET {set_clause}, updated_at = ?
                WHERE id = ?
            """, values)

            return cursor.rowcount > 0

    def get_open_trades(self) -> List[TrackedTrade]:
        """Holt alle offenen Trades"""
        return self.query_trades(status=TradeStatus.OPEN)

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
        """
        Flexible Trade-Abfrage.

        Args:
            symbol: Filter nach Symbol
            strategy: Filter nach Strategie
            status: Filter nach Status
            outcome: Filter nach Outcome
            min_score: Minimaler Signal-Score
            max_score: Maximaler Signal-Score
            min_date: Minimales Signal-Datum
            max_date: Maximales Signal-Datum
            limit: Maximale Anzahl Ergebnisse

        Returns:
            Liste von TrackedTrades
        """
        conditions = []
        params = []

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())

        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)

        if status:
            conditions.append("status = ?")
            params.append(status.value)

        if outcome:
            conditions.append("outcome = ?")
            params.append(outcome.value)

        if min_score is not None:
            conditions.append("signal_score >= ?")
            params.append(min_score)

        if max_score is not None:
            conditions.append("signal_score <= ?")
            params.append(max_score)

        if min_date:
            conditions.append("signal_date >= ?")
            params.append(min_date.isoformat())

        if max_date:
            conditions.append("signal_date <= ?")
            params.append(max_date.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM trades
                WHERE {where_clause}
                ORDER BY signal_date DESC
                LIMIT ?
            """, params + [limit])

            return [self._row_to_trade(row) for row in cursor.fetchall()]

    def get_stats(
        self,
        strategy: Optional[str] = None,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
    ) -> TradeStats:
        """
        Berechnet aggregierte Statistiken.

        Args:
            strategy: Optional Strategy-Filter
            min_date: Minimales Datum
            max_date: Maximales Datum

        Returns:
            TradeStats mit aggregierten Metriken
        """
        trades = self.query_trades(
            strategy=strategy,
            min_date=min_date,
            max_date=max_date,
            limit=10000,
        )

        stats = TradeStats()
        stats.total_trades = len(trades)

        closed_trades = [t for t in trades if t.status == TradeStatus.CLOSED]
        open_trades = [t for t in trades if t.status == TradeStatus.OPEN]

        stats.open_trades = len(open_trades)
        stats.closed_trades = len(closed_trades)

        if closed_trades:
            stats.wins = sum(1 for t in closed_trades if t.outcome == TradeOutcome.WIN)
            stats.losses = sum(1 for t in closed_trades if t.outcome == TradeOutcome.LOSS)
            stats.breakeven = sum(1 for t in closed_trades if t.outcome == TradeOutcome.BREAKEVEN)

            stats.win_rate = (stats.wins / len(closed_trades)) * 100

            pnls = [t.pnl_percent for t in closed_trades if t.pnl_percent is not None]
            if pnls:
                stats.avg_pnl_percent = sum(pnls) / len(pnls)
                stats.total_pnl = sum(t.pnl_amount for t in closed_trades if t.pnl_amount is not None)

            holding_days = [t.holding_days for t in closed_trades if t.holding_days is not None]
            if holding_days:
                stats.avg_holding_days = sum(holding_days) / len(holding_days)

        if trades:
            stats.avg_score = sum(t.signal_score for t in trades) / len(trades)

        # Stats by Score Bucket
        stats.by_score_bucket = self._stats_by_score_bucket(closed_trades)

        # Stats by Strategy
        stats.by_strategy = self._stats_by_strategy(closed_trades)

        return stats

    def _stats_by_score_bucket(self, trades: List[TrackedTrade]) -> Dict[str, Dict]:
        """Statistiken pro Score-Bucket"""
        buckets = {
            "5.0-6.0": [],
            "6.0-7.0": [],
            "7.0-8.0": [],
            "8.0-9.0": [],
            "9.0-10.0": [],
        }

        for trade in trades:
            score = trade.signal_score
            if 5.0 <= score < 6.0:
                buckets["5.0-6.0"].append(trade)
            elif 6.0 <= score < 7.0:
                buckets["6.0-7.0"].append(trade)
            elif 7.0 <= score < 8.0:
                buckets["7.0-8.0"].append(trade)
            elif 8.0 <= score < 9.0:
                buckets["8.0-9.0"].append(trade)
            elif score >= 9.0:
                buckets["9.0-10.0"].append(trade)

        result = {}
        for bucket_name, bucket_trades in buckets.items():
            if bucket_trades:
                wins = sum(1 for t in bucket_trades if t.outcome == TradeOutcome.WIN)
                result[bucket_name] = {
                    'count': len(bucket_trades),
                    'wins': wins,
                    'win_rate': (wins / len(bucket_trades)) * 100,
                }

        return result

    def _stats_by_strategy(self, trades: List[TrackedTrade]) -> Dict[str, Dict]:
        """Statistiken pro Strategie"""
        by_strategy: Dict[str, List[TrackedTrade]] = {}

        for trade in trades:
            if trade.strategy not in by_strategy:
                by_strategy[trade.strategy] = []
            by_strategy[trade.strategy].append(trade)

        result = {}
        for strategy_name, strategy_trades in by_strategy.items():
            wins = sum(1 for t in strategy_trades if t.outcome == TradeOutcome.WIN)
            result[strategy_name] = {
                'count': len(strategy_trades),
                'wins': wins,
                'win_rate': (wins / len(strategy_trades)) * 100,
            }

        return result

    def export_for_training(
        self,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None,
        strategies: Optional[List[str]] = None,
        min_trades: int = 50,
    ) -> Dict[str, Any]:
        """
        Exportiert Trades im Format für Walk-Forward Training.

        Args:
            min_date: Minimales Datum
            max_date: Maximales Datum
            strategies: Optional Liste von Strategien
            min_trades: Minimum benötigte Trades

        Returns:
            Dictionary mit Trainings-Daten
        """
        # Nur geschlossene Trades
        all_trades = []

        if strategies:
            for strategy in strategies:
                trades = self.query_trades(
                    strategy=strategy,
                    status=TradeStatus.CLOSED,
                    min_date=min_date,
                    max_date=max_date,
                    limit=10000,
                )
                all_trades.extend(trades)
        else:
            all_trades = self.query_trades(
                status=TradeStatus.CLOSED,
                min_date=min_date,
                max_date=max_date,
                limit=10000,
            )

        if len(all_trades) < min_trades:
            logger.warning(f"Only {len(all_trades)} trades, minimum is {min_trades}")

        # Konvertiere zu Training-Format
        training_data = []
        for trade in all_trades:
            training_data.append({
                'symbol': trade.symbol,
                'strategy': trade.strategy,
                'signal_date': trade.signal_date.isoformat() if trade.signal_date else None,
                'score': trade.signal_score,
                'score_breakdown': trade.score_breakdown,
                'vix': trade.vix_at_signal,
                'outcome': 1 if trade.outcome == TradeOutcome.WIN else 0,
                'pnl_percent': trade.pnl_percent,
                'holding_days': trade.holding_days,
            })

        return {
            'version': '1.0.0',
            'export_date': datetime.now().isoformat(),
            'total_trades': len(all_trades),
            'date_range': {
                'min': min(t.signal_date for t in all_trades if t.signal_date).isoformat() if all_trades else None,
                'max': max(t.signal_date for t in all_trades if t.signal_date).isoformat() if all_trades else None,
            },
            'strategies': list(set(t.strategy for t in all_trades)),
            'trades': training_data,
        }

    def delete_trade(self, trade_id: int) -> bool:
        """
        Löscht einen Trade.

        Args:
            trade_id: Trade-ID

        Returns:
            True wenn erfolgreich
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trades WHERE id = ?", (trade_id,))

            if cursor.rowcount > 0:
                logger.info(f"Deleted trade {trade_id}")
                return True
            return False

    def count_trades(
        self,
        strategy: Optional[str] = None,
        status: Optional[TradeStatus] = None,
    ) -> int:
        """Zählt Trades mit optionalen Filtern"""
        conditions = []
        params = []

        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)

        if status:
            conditions.append("status = ?")
            params.append(status.value)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM trades WHERE {where_clause}", params)
            return cursor.fetchone()[0]

    # =========================================================================
    # Historische Preisdaten
    # =========================================================================

    def store_price_data(
        self,
        symbol: str,
        bars: List[PriceBar],
        merge: bool = True,
    ) -> int:
        """
        Speichert historische Preisdaten für ein Symbol.

        Die Daten werden als komprimiertes JSON gespeichert um
        Speicherplatz zu sparen (~70-80% Kompression).

        Args:
            symbol: Ticker-Symbol
            bars: Liste von PriceBar-Objekten
            merge: True = mit existierenden Daten zusammenführen

        Returns:
            Anzahl gespeicherter Bars
        """
        if not bars:
            return 0

        symbol = symbol.upper()

        # Sortiere nach Datum
        bars = sorted(bars, key=lambda b: b.date)

        # Wenn merge aktiv, lade existierende Daten
        if merge:
            existing = self.get_price_data(symbol)
            if existing:
                # Merge: existierende + neue, Duplikate entfernen
                all_bars = {b.date: b for b in existing.bars}
                for bar in bars:
                    all_bars[bar.date] = bar
                bars = sorted(all_bars.values(), key=lambda b: b.date)

        start_date = bars[0].date
        end_date = bars[-1].date

        # Komprimiere Daten
        data_json = json.dumps([b.to_dict() for b in bars])
        data_compressed = zlib.compress(data_json.encode('utf-8'), level=6)

        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Lösche alte Einträge für dieses Symbol
            cursor.execute("DELETE FROM price_data WHERE symbol = ?", (symbol,))

            # Speichere neue Daten
            cursor.execute("""
                INSERT INTO price_data (
                    symbol, start_date, end_date, bar_count,
                    data_compressed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                start_date.isoformat(),
                end_date.isoformat(),
                len(bars),
                data_compressed,
                now,
                now,
            ))

            logger.info(
                f"Stored {len(bars)} price bars for {symbol} "
                f"({start_date} to {end_date}, "
                f"{len(data_compressed)/1024:.1f}KB compressed)"
            )

            return len(bars)

    def get_price_data(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Optional[SymbolPriceData]:
        """
        Lädt historische Preisdaten für ein Symbol.

        Args:
            symbol: Ticker-Symbol
            start_date: Optional Start-Datum Filter
            end_date: Optional End-Datum Filter

        Returns:
            SymbolPriceData oder None
        """
        symbol = symbol.upper()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data_compressed FROM price_data
                WHERE symbol = ?
            """, (symbol,))
            row = cursor.fetchone()

            if row is None:
                return None

            # Dekomprimiere
            data_json = zlib.decompress(row['data_compressed']).decode('utf-8')
            bars_data = json.loads(data_json)
            bars = [PriceBar.from_dict(b) for b in bars_data]

            # Filter nach Datum wenn gewünscht
            if start_date:
                bars = [b for b in bars if b.date >= start_date]
            if end_date:
                bars = [b for b in bars if b.date <= end_date]

            return SymbolPriceData(symbol=symbol, bars=bars)

    def get_price_data_range(self, symbol: str) -> Optional[Tuple[date, date]]:
        """
        Gibt den Datumsbereich der gespeicherten Preisdaten zurück.

        Args:
            symbol: Ticker-Symbol

        Returns:
            Tuple (start_date, end_date) oder None
        """
        symbol = symbol.upper()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT start_date, end_date FROM price_data
                WHERE symbol = ?
            """, (symbol,))
            row = cursor.fetchone()

            if row is None:
                return None

            return (
                date.fromisoformat(row['start_date']),
                date.fromisoformat(row['end_date']),
            )

    def list_symbols_with_price_data(self) -> List[Dict[str, Any]]:
        """
        Listet alle Symbole mit gespeicherten Preisdaten.

        Returns:
            Liste von Dicts mit symbol, start_date, end_date, bar_count
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, start_date, end_date, bar_count, updated_at
                FROM price_data
                ORDER BY symbol
            """)

            return [
                {
                    'symbol': row['symbol'],
                    'start_date': row['start_date'],
                    'end_date': row['end_date'],
                    'bar_count': row['bar_count'],
                    'updated_at': row['updated_at'],
                }
                for row in cursor.fetchall()
            ]

    def delete_price_data(self, symbol: str) -> bool:
        """Löscht Preisdaten für ein Symbol"""
        symbol = symbol.upper()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM price_data WHERE symbol = ?", (symbol,))
            return cursor.rowcount > 0

    # =========================================================================
    # VIX-Daten
    # =========================================================================

    def store_vix_data(self, vix_points: List[VixDataPoint]) -> int:
        """
        Speichert VIX-Historie.

        Args:
            vix_points: Liste von VixDataPoint-Objekten

        Returns:
            Anzahl gespeicherter Punkte
        """
        if not vix_points:
            return 0

        now = datetime.now().isoformat()
        count = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()

            for point in vix_points:
                cursor.execute("""
                    INSERT OR REPLACE INTO vix_data (date, value, created_at)
                    VALUES (?, ?, ?)
                """, (point.date.isoformat(), point.value, now))
                count += 1

            logger.info(f"Stored {count} VIX data points")
            return count

    def get_vix_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[VixDataPoint]:
        """
        Lädt VIX-Historie.

        Args:
            start_date: Optional Start-Datum
            end_date: Optional End-Datum

        Returns:
            Liste von VixDataPoint-Objekten
        """
        conditions = []
        params = []

        if start_date:
            conditions.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT date, value FROM vix_data
                WHERE {where_clause}
                ORDER BY date
            """, params)

            return [
                VixDataPoint(
                    date=date.fromisoformat(row['date']),
                    value=row['value'],
                )
                for row in cursor.fetchall()
            ]

    def get_vix_at_date(self, target_date: date) -> Optional[float]:
        """
        Holt VIX-Wert für ein bestimmtes Datum.

        Wenn kein Wert für genau dieses Datum existiert,
        wird der nächste verfügbare Wert davor zurückgegeben.

        Args:
            target_date: Zieldatum

        Returns:
            VIX-Wert oder None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Exaktes Datum
            cursor.execute("""
                SELECT value FROM vix_data WHERE date = ?
            """, (target_date.isoformat(),))
            row = cursor.fetchone()

            if row:
                return row['value']

            # Nächster verfügbarer Wert davor
            cursor.execute("""
                SELECT value FROM vix_data
                WHERE date < ?
                ORDER BY date DESC
                LIMIT 1
            """, (target_date.isoformat(),))
            row = cursor.fetchone()

            return row['value'] if row else None

    def get_vix_range(self) -> Optional[Tuple[date, date]]:
        """
        Gibt den Datumsbereich der gespeicherten VIX-Daten zurück.

        Returns:
            Tuple (start_date, end_date) oder None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MIN(date) as min_date, MAX(date) as max_date
                FROM vix_data
            """)
            row = cursor.fetchone()

            if row['min_date'] is None:
                return None

            return (
                date.fromisoformat(row['min_date']),
                date.fromisoformat(row['max_date']),
            )

    def count_vix_data(self) -> int:
        """Zählt VIX-Datenpunkte"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM vix_data")
            return cursor.fetchone()[0]

    # =========================================================================
    # Bulk-Export für Training
    # =========================================================================

    def export_for_backtesting(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Exportiert alle Daten für Backtesting/Training.

        Args:
            symbols: Optional Liste von Symbolen (default: alle)
            start_date: Optional Start-Datum
            end_date: Optional End-Datum

        Returns:
            Dictionary mit price_data, vix_data und trades
        """
        # Sammle Preisdaten
        price_data = {}
        symbol_list = symbols or [
            s['symbol'] for s in self.list_symbols_with_price_data()
        ]

        for symbol in symbol_list:
            data = self.get_price_data(symbol, start_date, end_date)
            if data and data.bars:
                price_data[symbol] = [b.to_dict() for b in data.bars]

        # VIX-Daten
        vix_data = [p.to_dict() for p in self.get_vix_data(start_date, end_date)]

        # Trades
        trades = self.query_trades(
            status=TradeStatus.CLOSED,
            min_date=start_date,
            max_date=end_date,
        )

        return {
            'version': '2.0.0',
            'export_date': datetime.now().isoformat(),
            'date_range': {
                'start': start_date.isoformat() if start_date else None,
                'end': end_date.isoformat() if end_date else None,
            },
            'symbols': list(price_data.keys()),
            'price_data': price_data,
            'vix_data': vix_data,
            'trades': [t.to_dict() for t in trades],
            'summary': {
                'symbols_count': len(price_data),
                'total_bars': sum(len(bars) for bars in price_data.values()),
                'vix_points': len(vix_data),
                'trades_count': len(trades),
            },
        }

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Gibt Statistiken über den Speicherverbrauch zurück.

        Returns:
            Dictionary mit Speicher-Statistiken
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Trades
            cursor.execute("SELECT COUNT(*) FROM trades")
            trades_count = cursor.fetchone()[0]

            # Price Data
            cursor.execute("""
                SELECT COUNT(*), SUM(bar_count), SUM(LENGTH(data_compressed))
                FROM price_data
            """)
            row = cursor.fetchone()
            symbols_count = row[0] or 0
            total_bars = row[1] or 0
            compressed_bytes = row[2] or 0

            # VIX
            cursor.execute("SELECT COUNT(*) FROM vix_data")
            vix_count = cursor.fetchone()[0]

            # DB File Size
            db_size = Path(self.db_path).stat().st_size if Path(self.db_path).exists() else 0

            return {
                'trades_count': trades_count,
                'symbols_with_price_data': symbols_count,
                'total_price_bars': total_bars,
                'price_data_compressed_kb': compressed_bytes / 1024,
                'vix_data_points': vix_count,
                'database_size_mb': db_size / (1024 * 1024),
            }


def format_trade_stats(stats: TradeStats) -> str:
    """Formatiert TradeStats als lesbaren Text"""
    lines = [
        "=" * 50,
        "TRADE STATISTICS",
        "=" * 50,
        "",
        f"Total Trades:    {stats.total_trades}",
        f"Open Trades:     {stats.open_trades}",
        f"Closed Trades:   {stats.closed_trades}",
        "",
        f"Wins:            {stats.wins}",
        f"Losses:          {stats.losses}",
        f"Breakeven:       {stats.breakeven}",
        "",
        f"Win Rate:        {stats.win_rate:.1f}%",
        f"Avg P&L:         {stats.avg_pnl_percent:.2f}%",
        f"Total P&L:       ${stats.total_pnl:,.2f}",
        f"Avg Holding:     {stats.avg_holding_days:.1f} days",
        f"Avg Score:       {stats.avg_score:.1f}",
    ]

    if stats.by_score_bucket:
        lines.extend(["", "BY SCORE BUCKET:", "-" * 30])
        for bucket, data in sorted(stats.by_score_bucket.items()):
            lines.append(f"  {bucket}: {data['count']} trades, {data['win_rate']:.1f}% win rate")

    if stats.by_strategy:
        lines.extend(["", "BY STRATEGY:", "-" * 30])
        for strategy, data in sorted(stats.by_strategy.items()):
            lines.append(f"  {strategy}: {data['count']} trades, {data['win_rate']:.1f}% win rate")

    return "\n".join(lines)


def create_tracker(db_path: Optional[str] = None) -> TradeTracker:
    """Factory-Funktion für TradeTracker"""
    return TradeTracker(db_path)
