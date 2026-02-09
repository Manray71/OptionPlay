# OptionPlay - Options Database Access
# =====================================
# Extracted from simulation/real_options_backtester.py (Phase 6c)
#
# Provides access to historical options data for backtesting.

import sqlite3
import logging
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional

from ..models.outcomes import OptionQuote

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".optionplay" / "trades.db"


class OptionsDatabase:
    """Zugriff auf die historischen Options-Daten"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._conn = None

    def connect(self) -> sqlite3.Connection:
        """Verbindung zur Datenbank herstellen"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        """Verbindung schließen"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_puts_for_date(
        self,
        symbol: str,
        quote_date: date,
        dte_min: int = 30,
        dte_max: int = 60,
        moneyness_min: float = 0.80,
        moneyness_max: float = 1.0,
    ) -> List[OptionQuote]:
        """
        Hole alle Put-Optionen für ein Symbol an einem bestimmten Datum.

        Args:
            symbol: Ticker Symbol
            quote_date: Datum der Quotes
            dte_min/max: Days-to-Expiration Range
            moneyness_min/max: Strike/Underlying Range (< 1 = OTM Put)

        Returns:
            Liste von OptionQuote Objekten
        """
        conn = self.connect()
        cursor = conn.cursor()

        query = """
        SELECT
            occ_symbol, underlying, expiration, strike, option_type,
            quote_date, bid, ask, mid, last, volume, open_interest,
            underlying_price, dte, moneyness
        FROM options_prices
        WHERE underlying = ?
          AND quote_date = ?
          AND option_type = 'P'
          AND dte BETWEEN ? AND ?
          AND moneyness BETWEEN ? AND ?
        ORDER BY expiration, strike DESC
        """

        cursor.execute(query, (
            symbol,
            quote_date.isoformat(),
            dte_min,
            dte_max,
            moneyness_min,
            moneyness_max,
        ))

        return [OptionQuote(
                occ_symbol=row['occ_symbol'],
                underlying=row['underlying'],
                expiration=date.fromisoformat(row['expiration']),
                strike=row['strike'],
                option_type=row['option_type'],
                quote_date=date.fromisoformat(row['quote_date']),
                bid=row['bid'] or 0,
                ask=row['ask'] or 0,
                mid=row['mid'] or 0,
                last=row['last'],
                volume=row['volume'] or 0,
                open_interest=row['open_interest'] or 0,
                underlying_price=row['underlying_price'],
                dte=row['dte'],
                moneyness=row['moneyness'],
            ) for row in cursor]

    def get_underlying_prices(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> Dict[date, float]:
        """
        Hole Underlying-Preise aus der options_prices Tabelle.
        (Die price_data Tabelle hat komprimierte Daten, also nutzen wir
        die underlying_price aus den Optionsdaten.)

        Returns:
            Dict von date -> close_price
        """
        conn = self.connect()
        cursor = conn.cursor()

        # Nutze die underlying_price aus options_prices (distinct per date)
        query = """
        SELECT DISTINCT quote_date, underlying_price
        FROM options_prices
        WHERE underlying = ?
          AND quote_date BETWEEN ? AND ?
        ORDER BY quote_date
        """

        cursor.execute(query, (symbol, start_date.isoformat(), end_date.isoformat()))

        return {
            date.fromisoformat(row['quote_date']): row['underlying_price']
            for row in cursor
        }

    def get_available_dates(
        self,
        symbol: str,
        start_date: date = None,
        end_date: date = None,
    ) -> List[date]:
        """Hole alle verfügbaren Quote-Dates für ein Symbol"""
        conn = self.connect()
        cursor = conn.cursor()

        query = """
        SELECT DISTINCT quote_date
        FROM options_prices
        WHERE underlying = ?
        """
        params = [symbol]

        if start_date:
            query += " AND quote_date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND quote_date <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY quote_date"

        cursor.execute(query, params)
        return [date.fromisoformat(row[0]) for row in cursor.fetchall()]

    def get_vix_data(
        self,
        start_date: date,
        end_date: date,
    ) -> Dict[date, float]:
        """Hole VIX-Daten"""
        conn = self.connect()
        cursor = conn.cursor()

        query = """
        SELECT date, value
        FROM vix_data
        WHERE date BETWEEN ? AND ?
        ORDER BY date
        """

        cursor.execute(query, (start_date.isoformat(), end_date.isoformat()))

        return {
            date.fromisoformat(row['date']): row['value']
            for row in cursor.fetchall()
        }
