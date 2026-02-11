# OptionPlay - Trade Analysis & Export
# =====================================
# Extracted from tracker.py (Phase 6b)
#
# Contains: get_stats, export_for_training, export_for_backtesting, get_storage_stats

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    TrackedTrade,
    TradeOutcome,
    TradeStats,
    TradeStatus,
)

logger = logging.getLogger(__name__)


class TradeAnalysis:
    """
    Trade statistics, export, and analysis operations.

    Receives _get_connection and a reference to TradeCRUD for query_trades.
    """

    def __init__(self, get_connection, trade_crud) -> None:
        """
        Args:
            get_connection: Context manager yielding a sqlite3.Connection
            trade_crud: TradeCRUD instance for query_trades access
        """
        self._get_connection = get_connection
        self._trade_crud = trade_crud

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
        trades = self._trade_crud.query_trades(
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
                stats.total_pnl = sum(
                    t.pnl_amount for t in closed_trades if t.pnl_amount is not None
                )

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
                    "count": len(bucket_trades),
                    "wins": wins,
                    "win_rate": (wins / len(bucket_trades)) * 100,
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
                "count": len(strategy_trades),
                "wins": wins,
                "win_rate": (wins / len(strategy_trades)) * 100,
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
                trades = self._trade_crud.query_trades(
                    strategy=strategy,
                    status=TradeStatus.CLOSED,
                    min_date=min_date,
                    max_date=max_date,
                    limit=10000,
                )
                all_trades.extend(trades)
        else:
            all_trades = self._trade_crud.query_trades(
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
            training_data.append(
                {
                    "symbol": trade.symbol,
                    "strategy": trade.strategy,
                    "signal_date": trade.signal_date.isoformat() if trade.signal_date else None,
                    "score": trade.signal_score,
                    "score_breakdown": trade.score_breakdown,
                    "vix": trade.vix_at_signal,
                    "outcome": 1 if trade.outcome == TradeOutcome.WIN else 0,
                    "pnl_percent": trade.pnl_percent,
                    "holding_days": trade.holding_days,
                }
            )

        return {
            "version": "1.0.0",
            "export_date": datetime.now().isoformat(),
            "total_trades": len(all_trades),
            "date_range": {
                "min": (
                    min(t.signal_date for t in all_trades if t.signal_date).isoformat()
                    if all_trades
                    else None
                ),
                "max": (
                    max(t.signal_date for t in all_trades if t.signal_date).isoformat()
                    if all_trades
                    else None
                ),
            },
            "strategies": list(set(t.strategy for t in all_trades)),
            "trades": training_data,
        }

    def export_for_backtesting(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        price_storage=None,
        vix_storage=None,
    ) -> Dict[str, Any]:
        """
        Exportiert alle Daten für Backtesting/Training.

        Args:
            symbols: Optional Liste von Symbolen (default: alle)
            start_date: Optional Start-Datum
            end_date: Optional End-Datum
            price_storage: PriceStorage instance
            vix_storage: VixStorage instance

        Returns:
            Dictionary mit price_data, vix_data und trades
        """
        # Sammle Preisdaten
        price_data = {}
        symbol_list = symbols or [s["symbol"] for s in price_storage.list_symbols_with_price_data()]

        for symbol in symbol_list:
            data = price_storage.get_price_data(symbol, start_date, end_date)
            if data and data.bars:
                price_data[symbol] = [b.to_dict() for b in data.bars]

        # VIX-Daten
        vix_data = [p.to_dict() for p in vix_storage.get_vix_data(start_date, end_date)]

        # Trades
        trades = self._trade_crud.query_trades(
            status=TradeStatus.CLOSED,
            min_date=start_date,
            max_date=end_date,
        )

        return {
            "version": "2.0.0",
            "export_date": datetime.now().isoformat(),
            "date_range": {
                "start": start_date.isoformat() if start_date else None,
                "end": end_date.isoformat() if end_date else None,
            },
            "symbols": list(price_data.keys()),
            "price_data": price_data,
            "vix_data": vix_data,
            "trades": [t.to_dict() for t in trades],
            "summary": {
                "symbols_count": len(price_data),
                "total_bars": sum(len(bars) for bars in price_data.values()),
                "vix_points": len(vix_data),
                "trades_count": len(trades),
            },
        }

    def get_storage_stats(self, db_path: str) -> Dict[str, Any]:
        """
        Gibt Statistiken über den Speicherverbrauch zurück.

        Args:
            db_path: Path to the database file

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
            db_size = Path(db_path).stat().st_size if Path(db_path).exists() else 0

            return {
                "trades_count": trades_count,
                "symbols_with_price_data": symbols_count,
                "total_price_bars": total_bars,
                "price_data_compressed_kb": compressed_bytes / 1024,
                "vix_data_points": vix_count,
                "database_size_mb": db_size / (1024 * 1024),
            }
