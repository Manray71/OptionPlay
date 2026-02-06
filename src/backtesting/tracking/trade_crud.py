# OptionPlay - Trade CRUD Operations
# ====================================
# Extracted from tracker.py (Phase 6b)
#
# Contains: add, get, close, update, delete, query, count trades

import json
import sqlite3
import logging
from datetime import datetime, date
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

from .models import (
    TradeStatus,
    TradeOutcome,
    TrackedTrade,
)

logger = logging.getLogger(__name__)


class TradeCRUD:
    """
    Trade CRUD operations on the trades table.

    Receives _get_connection from the parent TradeTracker facade.
    """

    def __init__(self, get_connection):
        """
        Args:
            get_connection: Context manager yielding a sqlite3.Connection
        """
        self._get_connection = get_connection

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

            pnl_str = f"{pnl_percent:.2f}%" if pnl_percent is not None else "N/A"
            logger.info(f"Closed trade {trade_id}: {outcome.value}, P&L: {pnl_str}")
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
