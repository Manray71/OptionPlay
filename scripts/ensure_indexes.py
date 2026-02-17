#!/usr/bin/env python3
"""
Ensure all required database indexes exist on trades.db.

Indexes are created with IF NOT EXISTS, so this script is idempotent.
Run after DB creation or any time indexes may have been dropped.

Usage:
    python scripts/ensure_indexes.py
"""

import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path.home() / ".optionplay" / "trades.db"

# All required indexes, grouped by table.
# Format: (index_name, table, columns_sql)
INDEXES = [
    # options_prices (20M+ rows) — most queried table
    (
        "idx_options_prices_underlying",
        "options_prices",
        "(underlying)",
    ),
    (
        "idx_options_prices_quote_date",
        "options_prices",
        "(quote_date)",
    ),
    (
        "idx_options_prices_dte",
        "options_prices",
        "(dte)",
    ),
    (
        "idx_options_prices_composite",
        "options_prices",
        "(underlying, quote_date, dte)",
    ),
    (
        "idx_opt_underlying_date_type_dte",
        "options_prices",
        "(underlying, quote_date, option_type, dte)",
    ),
    # options_greeks (20M+ rows)
    (
        "idx_greeks_price_id",
        "options_greeks",
        "(options_price_id)",
    ),
    (
        "idx_options_greeks_occ",
        "options_greeks",
        "(occ_symbol)",
    ),
    (
        "idx_options_greeks_date",
        "options_greeks",
        "(quote_date)",
    ),
    # daily_prices (444k rows)
    (
        "idx_daily_prices_symbol",
        "daily_prices",
        "(symbol)",
    ),
    (
        "idx_daily_symbol_date",
        "daily_prices",
        "(symbol, quote_date)",
    ),
]


def main():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Show existing indexes
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")
    existing = {row[0] for row in cursor.fetchall()}
    print(f"Existing indexes: {len(existing)}")

    created = 0
    skipped = 0
    for idx_name, table, columns in INDEXES:
        if idx_name in existing:
            print(f"  [skip] {idx_name} (exists)")
            skipped += 1
            continue

        sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}{columns}"
        print(f"  [create] {idx_name} on {table}{columns} ...", end=" ", flush=True)
        t0 = time.time()
        conn.execute(sql)
        conn.commit()
        elapsed = time.time() - t0
        print(f"({elapsed:.1f}s)")
        created += 1

    # Run ANALYZE to update query planner statistics
    print("\nRunning ANALYZE for query planner statistics...", end=" ", flush=True)
    t0 = time.time()
    conn.execute("ANALYZE")
    conn.commit()
    elapsed = time.time() - t0
    print(f"({elapsed:.1f}s)")

    conn.close()
    print(f"\nDone: {created} created, {skipped} skipped")


if __name__ == "__main__":
    main()
