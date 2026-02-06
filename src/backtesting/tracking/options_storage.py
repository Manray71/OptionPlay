# OptionPlay - Options Data Storage
# ==================================
# Extracted from tracker.py (Phase 6b)
#
# Contains: store, get, list, delete, count options data

import sqlite3
import logging
from datetime import date
from typing import List, Dict, Optional, Any

from .models import OptionBar

logger = logging.getLogger(__name__)


class OptionsStorage:
    """
    Historical options data storage operations.

    Receives _get_connection from the parent TradeTracker facade.
    """

    def __init__(self, get_connection):
        """
        Args:
            get_connection: Context manager yielding a sqlite3.Connection
        """
        self._get_connection = get_connection

    def store_option_bars(self, bars: List[OptionBar]) -> int:
        """
        Speichert historische Options-Daten.

        Args:
            bars: Liste von OptionBar-Objekten

        Returns:
            Anzahl gespeicherter Bars
        """
        if not bars:
            return 0

        from datetime import datetime
        now = datetime.now().isoformat()
        count = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()

            for bar in bars:
                try:
                    cursor.execute("""
                        INSERT OR REPLACE INTO options_data (
                            occ_symbol, underlying, strike, expiry, option_type,
                            trade_date, open, high, low, close, volume, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        bar.occ_symbol,
                        bar.underlying.upper(),
                        bar.strike,
                        bar.expiry.isoformat(),
                        bar.option_type,
                        bar.trade_date.isoformat(),
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        now,
                    ))
                    count += 1
                except sqlite3.Error as e:
                    logger.warning(f"Failed to store option bar {bar.occ_symbol}: {e}")

        logger.info(f"Stored {count} option bars")
        return count

    def get_option_history(
        self,
        occ_symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[OptionBar]:
        """
        Lädt historische Daten für eine Option.

        Args:
            occ_symbol: OCC Options-Symbol
            start_date: Optional Start-Datum
            end_date: Optional End-Datum

        Returns:
            Liste von OptionBar-Objekten
        """
        conditions = ["occ_symbol = ?"]
        params: List[Any] = [occ_symbol]

        if start_date:
            conditions.append("trade_date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("trade_date <= ?")
            params.append(end_date.isoformat())

        where_clause = " AND ".join(conditions)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM options_data
                WHERE {where_clause}
                ORDER BY trade_date
            """, params)

            return [self._row_to_option_bar(row) for row in cursor.fetchall()]

    def get_options_for_underlying(
        self,
        underlying: str,
        expiry: Optional[date] = None,
        option_type: Optional[str] = None,
        trade_date: Optional[date] = None,
    ) -> List[OptionBar]:
        """
        Lädt Options-Daten für ein Underlying.

        Args:
            underlying: Underlying Symbol
            expiry: Optional Verfall-Filter
            option_type: Optional 'P' oder 'C'
            trade_date: Optional Handelstag-Filter

        Returns:
            Liste von OptionBar-Objekten
        """
        conditions = ["underlying = ?"]
        params: List[Any] = [underlying.upper()]

        if expiry:
            conditions.append("expiry = ?")
            params.append(expiry.isoformat())
        if option_type:
            conditions.append("option_type = ?")
            params.append(option_type.upper())
        if trade_date:
            conditions.append("trade_date = ?")
            params.append(trade_date.isoformat())

        where_clause = " AND ".join(conditions)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM options_data
                WHERE {where_clause}
                ORDER BY trade_date, strike
            """, params)

            return [self._row_to_option_bar(row) for row in cursor.fetchall()]

    def get_option_at_date(
        self,
        occ_symbol: str,
        trade_date: date,
    ) -> Optional[OptionBar]:
        """
        Holt Options-Preis für ein bestimmtes Datum.

        Args:
            occ_symbol: OCC Options-Symbol
            trade_date: Handelstag

        Returns:
            OptionBar oder None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM options_data
                WHERE occ_symbol = ? AND trade_date = ?
            """, (occ_symbol, trade_date.isoformat()))

            row = cursor.fetchone()
            return self._row_to_option_bar(row) if row else None

    def get_spread_history(
        self,
        short_occ: str,
        long_occ: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lädt historische Daten für einen Bull-Put-Spread.

        Args:
            short_occ: OCC Symbol des Short Put
            long_occ: OCC Symbol des Long Put
            start_date: Optional Start-Datum
            end_date: Optional End-Datum

        Returns:
            Liste von Dicts mit trade_date, short_close, long_close, spread_value
        """
        short_bars = {b.trade_date: b for b in self.get_option_history(short_occ, start_date, end_date)}
        long_bars = {b.trade_date: b for b in self.get_option_history(long_occ, start_date, end_date)}

        # Nur Tage mit beiden Legs
        common_dates = sorted(set(short_bars.keys()) & set(long_bars.keys()))

        result = []
        for td in common_dates:
            short = short_bars[td]
            long = long_bars[td]
            spread_value = short.close - long.close

            result.append({
                'trade_date': td,
                'short_close': short.close,
                'long_close': long.close,
                'spread_value': spread_value,
                'short_volume': short.volume,
                'long_volume': long.volume,
            })

        return result

    def _row_to_option_bar(self, row: sqlite3.Row) -> OptionBar:
        """Konvertiert DB-Row zu OptionBar"""
        return OptionBar(
            occ_symbol=row['occ_symbol'],
            underlying=row['underlying'],
            strike=row['strike'],
            expiry=date.fromisoformat(row['expiry']),
            option_type=row['option_type'],
            trade_date=date.fromisoformat(row['trade_date']),
            open=row['open'] or 0.0,
            high=row['high'] or 0.0,
            low=row['low'] or 0.0,
            close=row['close'],
            volume=row['volume'] or 0,
        )

    def list_options_underlyings(self) -> List[Dict[str, Any]]:
        """
        Listet alle Underlyings mit Options-Daten.

        Returns:
            Liste von Dicts mit underlying, count, date_range
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    underlying,
                    COUNT(*) as bar_count,
                    COUNT(DISTINCT occ_symbol) as option_count,
                    MIN(trade_date) as first_date,
                    MAX(trade_date) as last_date
                FROM options_data
                GROUP BY underlying
                ORDER BY underlying
            """)

            return [
                {
                    'underlying': row['underlying'],
                    'bar_count': row['bar_count'],
                    'option_count': row['option_count'],
                    'first_date': row['first_date'],
                    'last_date': row['last_date'],
                }
                for row in cursor.fetchall()
            ]

    def count_option_bars(self, underlying: Optional[str] = None) -> int:
        """Zählt Options-Datenpunkte"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if underlying:
                cursor.execute(
                    "SELECT COUNT(*) FROM options_data WHERE underlying = ?",
                    (underlying.upper(),)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM options_data")
            return cursor.fetchone()[0]

    def delete_option_data(self, underlying: Optional[str] = None, occ_symbol: Optional[str] = None) -> int:
        """
        Löscht Options-Daten.

        Args:
            underlying: Löscht alle Daten für dieses Underlying
            occ_symbol: Löscht alle Daten für diese Option

        Returns:
            Anzahl gelöschter Zeilen
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if occ_symbol:
                cursor.execute("DELETE FROM options_data WHERE occ_symbol = ?", (occ_symbol,))
            elif underlying:
                cursor.execute("DELETE FROM options_data WHERE underlying = ?", (underlying.upper(),))
            else:
                cursor.execute("DELETE FROM options_data")

            count = cursor.rowcount
            logger.info(f"Deleted {count} option bars")
            return count
