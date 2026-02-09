#!/usr/bin/env python3
"""
E.6: Mark a symbol as delisted in symbol_fundamentals.

Usage:
    python scripts/mark_delisted.py SYMBOL YYYY-MM-DD

Example:
    python scripts/mark_delisted.py ATVI 2023-10-13

This adds two columns (if not present) and flags the symbol:
    - delisted INTEGER DEFAULT 0
    - delisted_date TEXT
"""

import sys
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".optionplay" / "trades.db"


def ensure_columns(conn: sqlite3.Connection) -> None:
    """Add delisted columns if they don't exist."""
    cursor = conn.execute("PRAGMA table_info(symbol_fundamentals)")
    columns = {row[1] for row in cursor.fetchall()}

    if "delisted" not in columns:
        conn.execute(
            "ALTER TABLE symbol_fundamentals ADD COLUMN delisted INTEGER DEFAULT 0"
        )
    if "delisted_date" not in columns:
        conn.execute(
            "ALTER TABLE symbol_fundamentals ADD COLUMN delisted_date TEXT"
        )
    conn.commit()


def mark_delisted(symbol: str, delisted_date: str) -> None:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        ensure_columns(conn)

        # Check symbol exists
        row = conn.execute(
            "SELECT symbol FROM symbol_fundamentals WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()

        if not row:
            print(f"Symbol {symbol.upper()} not found in symbol_fundamentals.")
            print("Insert it first or add with delisted flag:")
            conn.execute(
                "INSERT INTO symbol_fundamentals (symbol, delisted, delisted_date) VALUES (?, 1, ?)",
                (symbol.upper(), delisted_date),
            )
            conn.commit()
            print(f"Inserted {symbol.upper()} as delisted ({delisted_date}).")
        else:
            conn.execute(
                "UPDATE symbol_fundamentals SET delisted = 1, delisted_date = ? WHERE symbol = ?",
                (delisted_date, symbol.upper()),
            )
            conn.commit()
            print(f"Marked {symbol.upper()} as delisted ({delisted_date}).")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/mark_delisted.py SYMBOL YYYY-MM-DD")
        sys.exit(1)

    mark_delisted(sys.argv[1], sys.argv[2])
