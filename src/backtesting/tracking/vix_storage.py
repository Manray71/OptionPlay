# OptionPlay - VIX Data Storage
# ==============================
# Extracted from tracker.py (Phase 6b)
#
# Contains: store, get, count VIX data

import logging
from datetime import datetime, date
from typing import List, Optional, Tuple

from .models import VixDataPoint

logger = logging.getLogger(__name__)


class VixStorage:
    """
    VIX historical data storage operations.

    Receives _get_connection from the parent TradeTracker facade.
    """

    def __init__(self, get_connection) -> None:
        """
        Args:
            get_connection: Context manager yielding a sqlite3.Connection
        """
        self._get_connection = get_connection

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
