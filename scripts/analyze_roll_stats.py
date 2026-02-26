#!/usr/bin/env python3
"""
OptionPlay - Roll Statistics Analyzer
=====================================
Analyzes roll maneuver effectiveness from backtest database.

Usage:
    python scripts/analyze_roll_stats.py
    python scripts/analyze_roll_stats.py --run-id 1
"""

import argparse
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

DB_PATH = Path.home() / ".optionplay" / "backtest_rolls.db"


def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def analyze_roll_effectiveness(run_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Comprehensive analysis of roll maneuver effectiveness.

    Returns detailed statistics on:
    - When rolls help vs hurt
    - Optimal roll timing
    - Roll cost efficiency
    - Recovery rates by roll type
    """
    conn = get_connection()
    cursor = conn.cursor()

    run_filter = "WHERE t.run_id = ?" if run_id else "WHERE t.roll_count > 0"
    params = (run_id,) if run_id else ()

    results = {}

    # 1. Overall comparison: Rolled vs Non-Rolled
    print("\n" + "=" * 70)
    print("ROLL EFFECTIVENESS ANALYSIS")
    print("=" * 70)

    cursor.execute(
        f"""
        SELECT
            CASE WHEN roll_count > 0 THEN 'Rolled' ELSE 'Not Rolled' END as category,
            COUNT(*) as trades,
            SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'max_loss' THEN 1 ELSE 0 END) as max_losses,
            AVG(final_pnl) as avg_pnl,
            SUM(final_pnl) as total_pnl,
            AVG(initial_credit) as avg_credit,
            AVG(total_roll_cost) as avg_roll_cost
        FROM trades t
        {run_filter.replace('WHERE t.roll_count > 0', '')}
        GROUP BY category
    """,
        params,
    )

    print("\n1. OVERALL PERFORMANCE BY ROLL STATUS")
    print("-" * 70)
    print(
        f"{'Category':<15} {'Trades':>8} {'Win Rate':>10} {'Max Loss':>10} {'Avg P&L':>12} {'Total P&L':>14}"
    )
    print("-" * 70)

    for row in cursor.fetchall():
        win_rate = (row["wins"] / row["trades"] * 100) if row["trades"] > 0 else 0
        ml_rate = (row["max_losses"] / row["trades"] * 100) if row["trades"] > 0 else 0
        print(
            f"{row['category']:<15} {row['trades']:>8,} {win_rate:>9.1f}% {ml_rate:>9.1f}% ${row['avg_pnl']:>10.2f} ${row['total_pnl']:>12,.2f}"
        )

    # 2. Roll Type Analysis
    if run_id:
        cursor.execute(
            """
            SELECT
                r.roll_type,
                COUNT(*) as roll_count,
                AVG(r.roll_cost) as avg_cost,
                SUM(r.roll_cost) as total_cost,
                AVG(r.dte_at_roll) as avg_dte
            FROM roll_events r
            JOIN trades t ON r.trade_id = t.id
            WHERE t.run_id = ?
            GROUP BY r.roll_type
        """,
            (run_id,),
        )
    else:
        cursor.execute("""
            SELECT
                roll_type,
                COUNT(*) as roll_count,
                AVG(roll_cost) as avg_cost,
                SUM(roll_cost) as total_cost,
                AVG(dte_at_roll) as avg_dte
            FROM roll_events
            GROUP BY roll_type
        """)

    print("\n2. ROLL TYPE BREAKDOWN")
    print("-" * 70)
    print(f"{'Roll Type':<20} {'Count':>8} {'Avg Cost':>12} {'Total Cost':>14} {'Avg DTE':>10}")
    print("-" * 70)

    for row in cursor.fetchall():
        print(
            f"{row['roll_type']:<20} {row['roll_count']:>8,} ${row['avg_cost']:>10.2f} ${row['total_cost']:>12,.2f} {row['avg_dte']:>9.1f}"
        )

    # 3. Roll Timing Analysis
    if run_id:
        cursor.execute(
            """
            SELECT
                CASE
                    WHEN r.dte_at_roll >= 40 THEN '40+ DTE'
                    WHEN r.dte_at_roll >= 30 THEN '30-39 DTE'
                    WHEN r.dte_at_roll >= 20 THEN '20-29 DTE'
                    ELSE '<20 DTE'
                END as dte_bucket,
                COUNT(*) as rolls,
                AVG(r.roll_cost) as avg_cost,
                COUNT(DISTINCT r.trade_id) as trades_affected
            FROM roll_events r
            JOIN trades t ON r.trade_id = t.id
            WHERE t.run_id = ?
            GROUP BY dte_bucket
            ORDER BY r.dte_at_roll DESC
        """,
            (run_id,),
        )
    else:
        cursor.execute("""
            SELECT
                CASE
                    WHEN dte_at_roll >= 40 THEN '40+ DTE'
                    WHEN dte_at_roll >= 30 THEN '30-39 DTE'
                    WHEN dte_at_roll >= 20 THEN '20-29 DTE'
                    ELSE '<20 DTE'
                END as dte_bucket,
                COUNT(*) as rolls,
                AVG(roll_cost) as avg_cost,
                COUNT(DISTINCT trade_id) as trades_affected
            FROM roll_events
            GROUP BY dte_bucket
        """)

    print("\n3. ROLL TIMING ANALYSIS (by DTE at Roll)")
    print("-" * 70)
    print(f"{'DTE Bucket':<15} {'Rolls':>8} {'Trades':>8} {'Avg Cost':>12}")
    print("-" * 70)

    for row in cursor.fetchall():
        print(
            f"{row['dte_bucket']:<15} {row['rolls']:>8,} {row['trades_affected']:>8,} ${row['avg_cost']:>10.2f}"
        )

    # 4. Outcome after rolls
    if run_id:
        cursor.execute(
            """
            SELECT
                t.outcome,
                t.roll_count,
                COUNT(*) as count,
                AVG(t.final_pnl) as avg_pnl,
                AVG(t.total_roll_cost) as avg_roll_cost
            FROM trades t
            WHERE t.run_id = ? AND t.roll_count > 0
            GROUP BY t.outcome, t.roll_count
            ORDER BY t.roll_count, t.outcome
        """,
            (run_id,),
        )
    else:
        cursor.execute("""
            SELECT
                t.outcome,
                t.roll_count,
                COUNT(*) as count,
                AVG(t.final_pnl) as avg_pnl,
                AVG(t.total_roll_cost) as avg_roll_cost
            FROM trades t
            WHERE t.roll_count > 0
            GROUP BY t.outcome, t.roll_count
            ORDER BY t.roll_count, t.outcome
        """)

    print("\n4. OUTCOMES FOR ROLLED TRADES")
    print("-" * 70)
    print(f"{'Outcome':<12} {'Rolls':>6} {'Count':>8} {'Avg P&L':>12} {'Avg Roll Cost':>14}")
    print("-" * 70)

    for row in cursor.fetchall():
        print(
            f"{row['outcome']:<12} {row['roll_count']:>6} {row['count']:>8,} ${row['avg_pnl']:>10.2f} ${row['avg_roll_cost']:>12.2f}"
        )

    # 5. Recovery Analysis - Did rolls save the trade?
    print("\n5. ROLL RECOVERY ANALYSIS")
    print("-" * 70)

    if run_id:
        # Calculate how many trades that were rolled ended up as wins vs max_loss
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as partial_loss,
                SUM(CASE WHEN outcome = 'max_loss' THEN 1 ELSE 0 END) as max_loss,
                COUNT(*) as total
            FROM trades
            WHERE run_id = ? AND roll_count > 0
        """,
            (run_id,),
        )
    else:
        cursor.execute("""
            SELECT
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as partial_loss,
                SUM(CASE WHEN outcome = 'max_loss' THEN 1 ELSE 0 END) as max_loss,
                COUNT(*) as total
            FROM trades
            WHERE roll_count > 0
        """)

    row = cursor.fetchone()
    if row and row["total"] > 0:
        total = row["total"]
        print(f"Total Rolled Trades: {total:,}")
        print(f"  - Recovered to Win: {row['wins']:,} ({row['wins']/total*100:.1f}%)")
        print(
            f"  - Partial Loss:     {row['partial_loss']:,} ({row['partial_loss']/total*100:.1f}%)"
        )
        print(f"  - Max Loss:         {row['max_loss']:,} ({row['max_loss']/total*100:.1f}%)")

        # Calculate if rolls were "worth it"
        # A roll is worth it if the win rate after roll > expected without roll
        # and/or if the avg P&L after roll > expected without roll

        print(f"\nRecovery Rate (Wins from Rolled Trades): {row['wins']/total*100:.1f}%")

    # 6. Symbol-level Analysis
    print("\n6. TOP SYMBOLS WITH MOST ROLLS")
    print("-" * 70)

    if run_id:
        cursor.execute(
            """
            SELECT
                t.symbol,
                COUNT(*) as trades,
                SUM(CASE WHEN t.roll_count > 0 THEN 1 ELSE 0 END) as rolled_trades,
                SUM(t.roll_count) as total_rolls,
                AVG(CASE WHEN t.roll_count > 0 THEN t.final_pnl ELSE NULL END) as avg_rolled_pnl,
                AVG(CASE WHEN t.roll_count = 0 THEN t.final_pnl ELSE NULL END) as avg_unrolled_pnl
            FROM trades t
            WHERE t.run_id = ?
            GROUP BY t.symbol
            HAVING rolled_trades > 5
            ORDER BY total_rolls DESC
            LIMIT 15
        """,
            (run_id,),
        )
    else:
        cursor.execute("""
            SELECT
                symbol,
                COUNT(*) as trades,
                SUM(CASE WHEN roll_count > 0 THEN 1 ELSE 0 END) as rolled_trades,
                SUM(roll_count) as total_rolls,
                AVG(CASE WHEN roll_count > 0 THEN final_pnl ELSE NULL END) as avg_rolled_pnl,
                AVG(CASE WHEN roll_count = 0 THEN final_pnl ELSE NULL END) as avg_unrolled_pnl
            FROM trades
            GROUP BY symbol
            HAVING rolled_trades > 5
            ORDER BY total_rolls DESC
            LIMIT 15
        """)

    print(
        f"{'Symbol':<8} {'Trades':>8} {'Rolled':>8} {'Rolls':>8} {'Avg Rolled P&L':>15} {'Avg Normal P&L':>15}"
    )
    print("-" * 70)

    for row in cursor.fetchall():
        rolled_pnl = row["avg_rolled_pnl"] or 0
        normal_pnl = row["avg_unrolled_pnl"] or 0
        print(
            f"{row['symbol']:<8} {row['trades']:>8,} {row['rolled_trades']:>8,} {row['total_rolls']:>8,} ${rolled_pnl:>13.2f} ${normal_pnl:>13.2f}"
        )

    # 7. IV Analysis - Do high IV trades need more rolls?
    print("\n7. IV ANALYSIS (IV at Entry)")
    print("-" * 70)

    if run_id:
        cursor.execute(
            """
            SELECT
                CASE
                    WHEN iv_at_entry * 100 < 30 THEN 'Low (<30%)'
                    WHEN iv_at_entry * 100 < 50 THEN 'Medium (30-50%)'
                    WHEN iv_at_entry * 100 < 70 THEN 'High (50-70%)'
                    ELSE 'Very High (>70%)'
                END as iv_bucket,
                COUNT(*) as trades,
                SUM(CASE WHEN roll_count > 0 THEN 1 ELSE 0 END) as rolled,
                AVG(roll_count) as avg_rolls,
                AVG(final_pnl) as avg_pnl
            FROM trades
            WHERE run_id = ?
            GROUP BY iv_bucket
        """,
            (run_id,),
        )
    else:
        cursor.execute("""
            SELECT
                CASE
                    WHEN iv_at_entry * 100 < 30 THEN 'Low (<30%)'
                    WHEN iv_at_entry * 100 < 50 THEN 'Medium (30-50%)'
                    WHEN iv_at_entry * 100 < 70 THEN 'High (50-70%)'
                    ELSE 'Very High (>70%)'
                END as iv_bucket,
                COUNT(*) as trades,
                SUM(CASE WHEN roll_count > 0 THEN 1 ELSE 0 END) as rolled,
                AVG(roll_count) as avg_rolls,
                AVG(final_pnl) as avg_pnl
            FROM trades
            GROUP BY iv_bucket
        """)

    print(
        f"{'IV Bucket':<20} {'Trades':>8} {'Rolled':>8} {'Roll %':>8} {'Avg Rolls':>10} {'Avg P&L':>12}"
    )
    print("-" * 70)

    for row in cursor.fetchall():
        roll_pct = (row["rolled"] / row["trades"] * 100) if row["trades"] > 0 else 0
        print(
            f"{row['iv_bucket']:<20} {row['trades']:>8,} {row['rolled']:>8,} {roll_pct:>7.1f}% {row['avg_rolls']:>9.2f} ${row['avg_pnl']:>10.2f}"
        )

    # 8. Summary Statistics
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if run_id:
        cursor.execute(
            """
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN roll_count > 0 THEN 1 ELSE 0 END) as rolled_trades,
                SUM(roll_count) as total_rolls,
                SUM(total_roll_cost) as total_roll_cost,
                SUM(final_pnl) as total_pnl,
                AVG(final_pnl) as avg_pnl
            FROM trades
            WHERE run_id = ?
        """,
            (run_id,),
        )
    else:
        cursor.execute("""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN roll_count > 0 THEN 1 ELSE 0 END) as rolled_trades,
                SUM(roll_count) as total_rolls,
                SUM(total_roll_cost) as total_roll_cost,
                SUM(final_pnl) as total_pnl,
                AVG(final_pnl) as avg_pnl
            FROM trades
        """)

    row = cursor.fetchone()
    print(f"\nTotal Trades:        {row['total_trades']:,}")
    print(
        f"Rolled Trades:       {row['rolled_trades']:,} ({row['rolled_trades']/row['total_trades']*100:.1f}%)"
    )
    print(f"Total Rolls:         {row['total_rolls']:,}")
    print(f"Total Roll Cost:     ${row['total_roll_cost']:,.2f}")
    print(f"Total P&L:           ${row['total_pnl']:,.2f}")
    print(f"Avg P&L per Trade:   ${row['avg_pnl']:.2f}")

    # Calculate net impact
    if run_id:
        cursor.execute(
            """
            SELECT SUM(final_pnl) as rolled_pnl
            FROM trades WHERE run_id = ? AND roll_count > 0
        """,
            (run_id,),
        )
    else:
        cursor.execute("""
            SELECT SUM(final_pnl) as rolled_pnl
            FROM trades WHERE roll_count > 0
        """)
    rolled_pnl = cursor.fetchone()["rolled_pnl"] or 0

    print(f"\nP&L from Rolled Trades:  ${rolled_pnl:,.2f}")
    print(
        f"Roll Cost as % of P&L:   {abs(row['total_roll_cost']/row['total_pnl']*100):.1f}%"
        if row["total_pnl"] != 0
        else "N/A"
    )

    conn.close()

    print("\n" + "=" * 70)
    return results


def main():
    parser = argparse.ArgumentParser(description="Analyze Roll Statistics from Backtest Database")
    parser.add_argument("--run-id", type=int, help="Specific run ID to analyze")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run the backtest first: python scripts/backtest_with_rolls.py --all")
        return

    analyze_roll_effectiveness(args.run_id)


if __name__ == "__main__":
    main()
