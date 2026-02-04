#!/usr/bin/env python3
"""
Phase 2+3: Berechne days_to_exit für alle Trades in outcomes.db.

Berechnet pro Trade:
- days_to_50pct: Tage bis Spread-Wert <= 50% des Entry-Credits
- days_to_30pct: Tage bis Spread-Wert <= 30% des Entry-Credits
- days_to_playbook_exit: VIX-abhängig (50% wenn VIX<20, 30% wenn VIX>=20)

Batch-Approach: Pro Symbol alle Trades gleichzeitig verarbeiten.
"""

import sqlite3
import time
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

OUTCOMES_DB = Path.home() / ".optionplay" / "outcomes.db"
TRADES_DB = Path.home() / ".optionplay" / "trades.db"


def backup_outcomes_db():
    """Backup outcomes.db vor ALTER TABLE."""
    backup_path = OUTCOMES_DB.with_suffix(".db.bak_speed")
    if not backup_path.exists():
        print(f"Backup: {OUTCOMES_DB} -> {backup_path}")
        shutil.copy2(OUTCOMES_DB, backup_path)
    else:
        print(f"Backup existiert bereits: {backup_path}")


def add_columns(conn_out):
    """Neue Spalten hinzufügen falls nicht vorhanden."""
    cursor = conn_out.cursor()
    columns = {
        "days_to_50pct": "INTEGER",
        "days_to_30pct": "INTEGER",
        "days_to_playbook_exit": "INTEGER",
    }
    cursor.execute("PRAGMA table_info(trade_outcomes)")
    existing = {row[1] for row in cursor.fetchall()}

    for col, dtype in columns.items():
        if col not in existing:
            print(f"  ALTER TABLE: +{col} {dtype}")
            cursor.execute(
                f"ALTER TABLE trade_outcomes ADD COLUMN {col} {dtype}"
            )
        else:
            print(f"  Spalte {col} existiert bereits")
    conn_out.commit()


def load_trades(conn_out):
    """Alle Trades laden, gruppiert nach Symbol."""
    cursor = conn_out.cursor()
    cursor.execute("""
        SELECT id, symbol, entry_date, short_strike, long_strike,
               expiration, net_credit, vix_at_entry
        FROM trade_outcomes
    """)
    trades_by_symbol = defaultdict(list)
    for row in cursor.fetchall():
        trade = {
            "id": row[0],
            "symbol": row[1],
            "entry_date": row[2],
            "short_strike": row[3],
            "long_strike": row[4],
            "expiration": row[5],
            "net_credit": row[6],
            "vix_at_entry": row[7],
        }
        trades_by_symbol[trade["symbol"]].append(trade)
    return trades_by_symbol


def load_put_prices(conn_trades, symbol):
    """Alle Put-Preise für ein Symbol laden als dict[expiration][quote_date][(strike)] = mid."""
    cursor = conn_trades.cursor()
    cursor.execute(
        """
        SELECT quote_date, strike, expiration, mid
        FROM options_prices
        WHERE underlying = ? AND option_type = 'P'
        ORDER BY quote_date
    """,
        (symbol,),
    )
    # Struktur: prices[expiration][quote_date][strike] = mid
    prices = defaultdict(lambda: defaultdict(dict))
    row_count = 0
    for qd, strike, exp, mid in cursor:
        prices[exp][qd][strike] = mid
        row_count += 1
    return prices, row_count


def calculate_for_trade(trade, prices):
    """Days-to-exit für einen einzelnen Trade berechnen."""
    exp = trade["expiration"]
    short_strike = trade["short_strike"]
    long_strike = trade["long_strike"]
    net_credit = trade["net_credit"]
    entry_date = trade["entry_date"]
    vix = trade["vix_at_entry"]

    if net_credit is None or net_credit <= 0:
        return None, None, None

    target_50 = net_credit * 0.50
    target_30 = net_credit * 0.30
    playbook_target = target_30 if (vix is not None and vix >= 20) else target_50

    days_to_50 = None
    days_to_30 = None
    days_to_playbook = None

    exp_prices = prices.get(exp, {})
    entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")

    for qd in sorted(exp_prices.keys()):
        if qd <= entry_date:
            continue

        day_prices = exp_prices[qd]
        if short_strike not in day_prices or long_strike not in day_prices:
            continue

        spread_value = day_prices[short_strike] - day_prices[long_strike]
        qd_dt = datetime.strptime(qd, "%Y-%m-%d")
        days_elapsed = (qd_dt - entry_dt).days

        if days_to_50 is None and spread_value <= target_50:
            days_to_50 = days_elapsed

        if days_to_30 is None and spread_value <= target_30:
            days_to_30 = days_elapsed

        if days_to_playbook is None and spread_value <= playbook_target:
            days_to_playbook = days_elapsed

        if days_to_50 is not None and days_to_30 is not None and days_to_playbook is not None:
            break

    return days_to_50, days_to_30, days_to_playbook


def main():
    t_start = time.time()

    # Backup
    backup_outcomes_db()

    # Connections
    conn_out = sqlite3.connect(str(OUTCOMES_DB))
    conn_trades = sqlite3.connect(str(TRADES_DB))

    # Spalten anlegen
    print("\nSpalten prüfen/anlegen...")
    add_columns(conn_out)

    # Trades laden
    print("\nTrades laden...")
    trades_by_symbol = load_trades(conn_out)
    total_trades = sum(len(t) for t in trades_by_symbol.values())
    total_symbols = len(trades_by_symbol)
    print(f"  {total_trades} Trades in {total_symbols} Symbolen")

    # Berechnung
    print("\nBerechnung läuft...")
    cursor_out = conn_out.cursor()
    processed = 0
    results_summary = {"found_50": 0, "found_30": 0, "found_pb": 0, "no_data": 0}

    for i, (symbol, trades) in enumerate(sorted(trades_by_symbol.items())):
        # Put-Preise für dieses Symbol laden
        prices, row_count = load_put_prices(conn_trades, symbol)

        if row_count == 0:
            results_summary["no_data"] += len(trades)
            processed += len(trades)
            continue

        for trade in trades:
            d50, d30, dpb = calculate_for_trade(trade, prices)

            cursor_out.execute(
                """
                UPDATE trade_outcomes
                SET days_to_50pct = ?, days_to_30pct = ?, days_to_playbook_exit = ?
                WHERE id = ?
            """,
                (d50, d30, dpb, trade["id"]),
            )

            if d50 is not None:
                results_summary["found_50"] += 1
            if d30 is not None:
                results_summary["found_30"] += 1
            if dpb is not None:
                results_summary["found_pb"] += 1

            processed += 1

        # Fortschritt alle 50 Symbole
        if (i + 1) % 50 == 0 or (i + 1) == total_symbols:
            conn_out.commit()
            elapsed = time.time() - t_start
            pct = processed / total_trades * 100
            print(
                f"  [{i+1}/{total_symbols}] {processed}/{total_trades} Trades "
                f"({pct:.0f}%) in {elapsed:.1f}s"
            )

    conn_out.commit()
    elapsed = time.time() - t_start

    # Zusammenfassung
    print(f"\n{'='*50}")
    print(f"Fertig in {elapsed:.1f}s")
    print(f"  Total Trades:          {total_trades}")
    print(f"  days_to_50pct gefunden: {results_summary['found_50']} ({results_summary['found_50']/total_trades*100:.1f}%)")
    print(f"  days_to_30pct gefunden: {results_summary['found_30']} ({results_summary['found_30']/total_trades*100:.1f}%)")
    print(f"  days_to_playbook_exit:  {results_summary['found_pb']} ({results_summary['found_pb']/total_trades*100:.1f}%)")
    print(f"  Keine Preisdaten:       {results_summary['no_data']}")

    # Schnelle Statistik
    cursor_out = conn_out.cursor()
    cursor_out.execute("""
        SELECT
            AVG(days_to_playbook_exit),
            MIN(days_to_playbook_exit),
            MAX(days_to_playbook_exit),
            AVG(CASE WHEN vix_at_entry < 20 THEN days_to_playbook_exit END) as avg_low_vix,
            AVG(CASE WHEN vix_at_entry >= 20 THEN days_to_playbook_exit END) as avg_high_vix
        FROM trade_outcomes
        WHERE days_to_playbook_exit IS NOT NULL
    """)
    row = cursor_out.fetchone()
    print(f"\n  Avg days_to_playbook_exit: {row[0]:.1f}")
    print(f"  Min: {row[1]}, Max: {row[2]}")
    print(f"  Avg bei VIX<20 (50% target):  {row[3]:.1f} Tage" if row[3] else "  Avg bei VIX<20: n/a")
    print(f"  Avg bei VIX>=20 (30% target): {row[4]:.1f} Tage" if row[4] else "  Avg bei VIX>=20: n/a")

    conn_out.close()
    conn_trades.close()


if __name__ == "__main__":
    main()
