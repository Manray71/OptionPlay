# OptionPlay - Price Data Storage
# ================================
# Extracted from tracker.py (Phase 6b)
#
# Contains: store, get, list, delete price data (compressed JSON blobs)

import json
import logging
import zlib
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    PriceBar,
    SymbolPriceData,
)

logger = logging.getLogger(__name__)


class PriceStorage:
    """
    Historical price data storage using compressed JSON blobs.

    Receives _get_connection from the parent TradeTracker facade.
    """

    def __init__(self, get_connection) -> None:
        """
        Args:
            get_connection: Context manager yielding a sqlite3.Connection
        """
        self._get_connection = get_connection

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
        data_compressed = zlib.compress(data_json.encode("utf-8"), level=6)

        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Lösche alte Einträge für dieses Symbol
            cursor.execute("DELETE FROM price_data WHERE symbol = ?", (symbol,))

            # Speichere neue Daten
            cursor.execute(
                """
                INSERT INTO price_data (
                    symbol, start_date, end_date, bar_count,
                    data_compressed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    symbol,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    len(bars),
                    data_compressed,
                    now,
                    now,
                ),
            )

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
            cursor.execute(
                """
                SELECT data_compressed FROM price_data
                WHERE symbol = ?
            """,
                (symbol,),
            )
            row = cursor.fetchone()

            if row is None:
                return None

            # Dekomprimiere
            data_json = zlib.decompress(row["data_compressed"]).decode("utf-8")
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
            cursor.execute(
                """
                SELECT start_date, end_date FROM price_data
                WHERE symbol = ?
            """,
                (symbol,),
            )
            row = cursor.fetchone()

            if row is None:
                return None

            return (
                date.fromisoformat(row["start_date"]),
                date.fromisoformat(row["end_date"]),
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
                    "symbol": row["symbol"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "bar_count": row["bar_count"],
                    "updated_at": row["updated_at"],
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
