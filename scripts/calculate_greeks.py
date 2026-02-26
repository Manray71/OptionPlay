#!/usr/bin/env python3
"""
OptionPlay - Greeks Calculator for Historical Options
======================================================

Berechnet Greeks für bereits gesammelte Options-Preise in der Datenbank.
Nutzt das kalibrierte Black-Scholes Modell mit Symbol-spezifischen Korrekturfaktoren.

Strategie:
1. Liest options_prices Tabelle (nur Preisdaten)
2. Berechnet IV aus Mid-Price (Newton-Raphson)
3. Falls IV nicht konvergiert: Nutzt kalibrierte IV-Schätzung
4. Berechnet Delta, Gamma, Theta, Vega
5. Speichert in options_greeks Tabelle

Usage:
    # Berechne für alle Datensätze
    python scripts/calculate_greeks.py --all

    # Nur für bestimmte Symbole
    python scripts/calculate_greeks.py --symbols AAPL,MSFT,SPY

    # Mit mehr Workers
    python scripts/calculate_greeks.py --all --workers 8

    # Status prüfen
    python scripts/calculate_greeks.py --status
"""

import argparse
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.pricing.black_scholes import (
    black_scholes_greeks,
    implied_volatility,
    estimate_iv_calibrated,
    get_symbol_iv_multiplier,
)

# Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE
# =============================================================================


def get_db_path() -> str:
    return str(Path.home() / ".optionplay" / "trades.db")


def ensure_greeks_table(db_path: str):
    """Erstellt die options_greeks Tabelle"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS options_greeks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            options_price_id INTEGER NOT NULL,
            occ_symbol TEXT NOT NULL,
            quote_date TEXT NOT NULL,
            iv_calculated REAL,
            iv_method TEXT,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(options_price_id),
            FOREIGN KEY (options_price_id) REFERENCES options_prices(id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_options_greeks_occ
        ON options_greeks(occ_symbol)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_options_greeks_date
        ON options_greeks(quote_date)
    """)

    conn.commit()
    conn.close()
    logger.info("Greeks table schema verified/created")


def get_options_without_greeks(
    db_path: str, symbols: List[str] = None, limit: int = None
) -> List[Tuple]:
    """Holt Options-Preise ohne berechnete Greeks"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
        SELECT p.id, p.occ_symbol, p.underlying, p.strike, p.option_type,
               p.quote_date, p.expiration, p.mid, p.underlying_price, p.dte
        FROM options_prices p
        LEFT JOIN options_greeks g ON p.id = g.options_price_id
        WHERE g.id IS NULL
    """

    params = []
    if symbols:
        placeholders = ",".join("?" * len(symbols))
        query += f" AND p.underlying IN ({placeholders})"
        params.extend(symbols)

    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return rows


def store_greeks_batch(db_path: str, greeks_data: List[Dict]) -> int:
    """Speichert berechnete Greeks"""
    if not greeks_data:
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    inserted = 0
    for g in greeks_data:
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO options_greeks (
                    options_price_id, occ_symbol, quote_date,
                    iv_calculated, iv_method, delta, gamma, theta, vega
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    g["price_id"],
                    g["occ_symbol"],
                    g["quote_date"],
                    g["iv"],
                    g["iv_method"],
                    g["delta"],
                    g["gamma"],
                    g["theta"],
                    g["vega"],
                ),
            )
            inserted += 1
        except Exception as e:
            pass

    conn.commit()
    conn.close()
    return inserted


# =============================================================================
# GREEKS CALCULATOR
# =============================================================================


def calculate_iv_from_price(
    mid_price: float,
    spot: float,
    strike: float,
    tte: float,
    option_type: str,
    risk_free_rate: float = 0.05,
) -> Tuple[Optional[float], str]:
    """
    Berechnet IV aus dem Marktpreis.

    Returns:
        (iv, method) - IV und die verwendete Methode
    """
    if mid_price <= 0 or spot <= 0 or tte <= 0:
        return None, "invalid_input"

    # Konvertiere option_type
    opt_type = option_type.upper() if option_type in ["c", "p", "C", "P"] else option_type

    # Versuche Newton-Raphson
    try:
        iv = implied_volatility(
            option_price=mid_price,
            S=spot,
            K=strike,
            T=tte,
            r=risk_free_rate,
            option_type=opt_type,
        )

        if iv is not None and 0.01 <= iv <= 5.0:
            return iv, "newton_raphson"

    except Exception:
        pass

    # Fallback: Einfache ATM-IV Schätzung basierend auf VIX-Level
    # VIX ~20 entspricht etwa 20% IV für ATM Optionen
    try:
        # Einfache Schätzung: 25% als Basis, angepasst nach Moneyness
        moneyness = strike / spot
        base_iv = 0.25

        # OTM Optionen haben höhere IV (Volatility Smile)
        if opt_type == "P":
            # Put: Moneyness < 1 ist OTM
            skew_adj = 1 + max(0, (1 - moneyness) * 0.5)
        else:
            # Call: Moneyness > 1 ist OTM
            skew_adj = 1 + max(0, (moneyness - 1) * 0.3)

        iv_est = base_iv * skew_adj

        if 0.05 <= iv_est <= 2.0:
            return iv_est, "estimated"

    except Exception:
        pass

    return None, "failed"


def calculate_greeks_for_option(
    price_id: int,
    occ_symbol: str,
    underlying: str,
    strike: float,
    option_type: str,
    quote_date: str,
    expiration: str,
    mid_price: float,
    underlying_price: float,
    dte: int,
) -> Optional[Dict]:
    """Berechnet Greeks für eine einzelne Option"""

    # Time to expiration in Jahren
    tte = dte / 365.0
    if tte <= 0:
        return None

    # IV berechnen
    iv, iv_method = calculate_iv_from_price(
        mid_price=mid_price,
        spot=underlying_price,
        strike=strike,
        tte=tte,
        option_type=option_type,
    )

    if iv is None:
        return None

    # Symbol-spezifische Korrektur anwenden
    iv_multiplier = get_symbol_iv_multiplier(underlying)
    iv_adjusted = iv * iv_multiplier

    # Greeks berechnen
    try:
        # option_type für black_scholes_greeks: 'C' oder 'P'
        opt_type = option_type.upper() if option_type in ["c", "p", "C", "P"] else option_type

        greeks = black_scholes_greeks(
            S=underlying_price,
            K=strike,
            T=tte,
            r=0.05,
            sigma=iv_adjusted,
            option_type=opt_type,
        )

        return {
            "price_id": price_id,
            "occ_symbol": occ_symbol,
            "quote_date": quote_date,
            "iv": iv_adjusted,
            "iv_method": iv_method,
            "delta": greeks.delta,
            "gamma": greeks.gamma,
            "theta": greeks.theta,
            "vega": greeks.vega,
        }

    except Exception as e:
        return None


def process_batch(batch: List[Tuple]) -> List[Dict]:
    """Verarbeitet einen Batch von Optionen (für Multiprocessing)"""
    results = []

    for row in batch:
        (
            price_id,
            occ_symbol,
            underlying,
            strike,
            option_type,
            quote_date,
            expiration,
            mid_price,
            underlying_price,
            dte,
        ) = row

        result = calculate_greeks_for_option(
            price_id=price_id,
            occ_symbol=occ_symbol,
            underlying=underlying,
            strike=strike,
            option_type=option_type,
            quote_date=quote_date,
            expiration=expiration,
            mid_price=mid_price or 0,
            underlying_price=underlying_price or 0,
            dte=dte or 0,
        )

        if result:
            results.append(result)

    return results


# =============================================================================
# MAIN CALCULATOR
# =============================================================================


def calculate_all_greeks(
    db_path: str,
    symbols: List[str] = None,
    workers: int = 4,
    batch_size: int = 10000,
):
    """Berechnet Greeks für alle Options-Preise"""

    ensure_greeks_table(db_path)

    # Hole Optionen ohne Greeks
    logger.info("Loading options without Greeks...")
    options = get_options_without_greeks(db_path, symbols)
    total = len(options)

    if total == 0:
        logger.info("All options already have Greeks calculated!")
        return

    logger.info(f"Found {total:,} options needing Greeks calculation")
    logger.info(f"Using {workers} worker processes")

    processed = 0
    stored = 0

    # Verarbeite in Batches
    for batch_start in range(0, total, batch_size):
        batch = options[batch_start : batch_start + batch_size]

        # Teile Batch für Worker auf
        chunk_size = max(1, len(batch) // workers)
        chunks = [batch[i : i + chunk_size] for i in range(0, len(batch), chunk_size)]

        results = []

        # Parallel verarbeiten
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_batch, chunk): i for i, chunk in enumerate(chunks)}

            for future in as_completed(futures):
                try:
                    chunk_results = future.result()
                    results.extend(chunk_results)
                except Exception as e:
                    logger.error(f"Worker error: {e}")

        # In DB speichern
        batch_stored = store_greeks_batch(db_path, results)
        stored += batch_stored
        processed += len(batch)

        progress = processed / total * 100
        success_rate = (stored / processed * 100) if processed > 0 else 0
        logger.info(
            f"[{progress:5.1f}%] Processed: {processed:,} | "
            f"Stored: {stored:,} | Success: {success_rate:.1f}%"
        )

    logger.info(f"\nCompleted: {stored:,} Greeks calculated from {total:,} options")


def show_status(db_path: str):
    """Zeigt Status der Greeks-Berechnung"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("GREEKS CALCULATION STATUS")
    print("=" * 70)

    # Prüfe ob Tabellen existieren
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN ('options_prices', 'options_greeks')
    """)
    tables = [r[0] for r in cursor.fetchall()]

    if "options_prices" not in tables:
        print("\nNo options_prices table found. Run collect_options_prices.py first.")
        conn.close()
        return

    # Total prices
    cursor.execute("SELECT COUNT(*) FROM options_prices")
    total_prices = cursor.fetchone()[0]

    # Greeks count
    if "options_greeks" in tables:
        cursor.execute("SELECT COUNT(*) FROM options_greeks")
        total_greeks = cursor.fetchone()[0]
    else:
        total_greeks = 0

    pending = total_prices - total_greeks
    coverage = (total_greeks / total_prices * 100) if total_prices > 0 else 0

    print(f"\nOptions Prices: {total_prices:,}")
    print(f"Greeks Calculated: {total_greeks:,}")
    print(f"Pending: {pending:,}")
    print(f"Coverage: {coverage:.1f}%")

    if total_greeks > 0:
        # IV method distribution
        print("\n" + "-" * 70)
        print("IV CALCULATION METHODS")
        print("-" * 70)

        cursor.execute("""
            SELECT iv_method, COUNT(*) as cnt
            FROM options_greeks
            GROUP BY iv_method
            ORDER BY cnt DESC
        """)
        for row in cursor.fetchall():
            print(f"  {row[0]}: {row[1]:,}")

        # Delta distribution
        print("\n" + "-" * 70)
        print("DELTA DISTRIBUTION (absolute)")
        print("-" * 70)

        cursor.execute("""
            SELECT
                CASE
                    WHEN ABS(delta) < 0.10 THEN '0.00-0.10'
                    WHEN ABS(delta) < 0.20 THEN '0.10-0.20'
                    WHEN ABS(delta) < 0.30 THEN '0.20-0.30'
                    WHEN ABS(delta) < 0.40 THEN '0.30-0.40'
                    ELSE '0.40+'
                END as delta_range,
                COUNT(*) as cnt
            FROM options_greeks
            WHERE delta IS NOT NULL
            GROUP BY delta_range
            ORDER BY delta_range
        """)
        for row in cursor.fetchall():
            print(f"  Delta {row[0]}: {row[1]:,}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Calculate Greeks for historical options")
    parser.add_argument("--all", action="store_true", help="Calculate for all options")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    parser.add_argument("--workers", type=int, default=4, help="Worker processes (default: 4)")
    parser.add_argument("--batch-size", type=int, default=10000, help="Batch size (default: 10000)")
    parser.add_argument("--status", action="store_true", help="Show calculation status")

    args = parser.parse_args()
    db_path = get_db_path()

    if args.status:
        show_status(db_path)
        return

    if not args.all and not args.symbols:
        parser.print_help()
        return

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]

    calculate_all_greeks(
        db_path=db_path,
        symbols=symbols,
        workers=args.workers,
        batch_size=args.batch_size,
    )

    show_status(db_path)


if __name__ == "__main__":
    main()
