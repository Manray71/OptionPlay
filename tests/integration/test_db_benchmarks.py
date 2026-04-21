# OptionPlay - DB Performance Benchmarks
# ========================================
# Measures query performance for critical database operations.
#
# Run with:
#     pytest tests/integration/test_db_benchmarks.py -v -s --tb=short
#
# These benchmarks establish baselines for DB hotspots identified
# during Phase 4.5 of the stabilization roadmap.

import os
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

from src.constants.trading_rules import ENTRY_STABILITY_MIN
from typing import Any, Optional
from unittest.mock import patch

import pytest

# =============================================================================
# CONFIG
# =============================================================================

DB_PATH = Path.home() / ".optionplay" / "trades.db"
OUTCOMES_DB_PATH = Path.home() / ".optionplay" / "outcomes.db"

_REQUIRED_TABLES = ("symbol_fundamentals", "earnings_history", "vix_data", "options_prices")


def _db_has_required_tables() -> bool:
    if not DB_PATH.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        return all(t in existing for t in _REQUIRED_TABLES)
    except Exception:
        return False


# Skip all benchmarks if DB or required tables are missing
pytestmark = pytest.mark.skipif(
    not _db_has_required_tables(),
    reason=f"Database at {DB_PATH} missing one or more required tables: {_REQUIRED_TABLES}"
)


def get_db_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Create a read-only connection to the database."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def time_query(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> tuple[float, list[Any]]:
    """Execute a query and return (time_ms, results)."""
    start = time.perf_counter()
    cursor = conn.execute(sql, params)
    results = cursor.fetchall()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, results


# =============================================================================
# BENCHMARK: Symbol Fundamentals
# =============================================================================

class TestFundamentalsBenchmarks:
    """Benchmarks for symbol_fundamentals queries."""

    @pytest.fixture
    def conn(self) -> sqlite3.Connection:
        conn = get_db_connection()
        yield conn
        conn.close()

    def test_get_all_fundamentals(self, conn: sqlite3.Connection) -> None:
        """Baseline: fetch all fundamentals rows."""
        elapsed_ms, rows = time_query(
            conn,
            "SELECT * FROM symbol_fundamentals"
        )
        print(f"\n  All fundamentals: {len(rows)} rows in {elapsed_ms:.2f}ms")
        assert elapsed_ms < 50, f"Full table fetch too slow: {elapsed_ms:.2f}ms"

    def test_get_stable_symbols(self, conn: sqlite3.Connection) -> None:
        """Benchmark: filter by stability_score >= ENTRY_STABILITY_MIN."""
        elapsed_ms, rows = time_query(
            conn,
            "SELECT symbol, stability_score, historical_win_rate "
            "FROM symbol_fundamentals "
            "WHERE stability_score >= ? "
            "ORDER BY stability_score DESC",
            (ENTRY_STABILITY_MIN,)
        )
        print(f"\n  Stable symbols (>= {ENTRY_STABILITY_MIN}): {len(rows)} rows in {elapsed_ms:.2f}ms")
        assert elapsed_ms < 20, f"Stability filter too slow: {elapsed_ms:.2f}ms"

    def test_batch_lookup(self, conn: sqlite3.Connection) -> None:
        """Benchmark: batch IN lookup for 50 symbols."""
        # Get 50 random symbols
        _, all_rows = time_query(conn, "SELECT symbol FROM symbol_fundamentals LIMIT 50")
        symbols = [row["symbol"] for row in all_rows]

        if len(symbols) < 10:
            pytest.skip("Not enough symbols in DB")

        placeholders = ",".join("?" * len(symbols))
        elapsed_ms, rows = time_query(
            conn,
            f"SELECT * FROM symbol_fundamentals WHERE symbol IN ({placeholders})",
            tuple(symbols)
        )
        print(f"\n  Batch lookup ({len(symbols)} symbols): {len(rows)} rows in {elapsed_ms:.2f}ms")
        assert elapsed_ms < 20, f"Batch lookup too slow: {elapsed_ms:.2f}ms"

    def test_statistics_aggregation(self, conn: sqlite3.Connection) -> None:
        """Benchmark: aggregation queries for statistics."""
        start = time.perf_counter()

        conn.execute("SELECT COUNT(*) FROM symbol_fundamentals").fetchone()
        conn.execute(
            "SELECT sector, COUNT(*) FROM symbol_fundamentals "
            "WHERE sector IS NOT NULL GROUP BY sector"
        ).fetchall()
        conn.execute(
            "SELECT market_cap_category, COUNT(*) FROM symbol_fundamentals "
            "WHERE market_cap_category IS NOT NULL GROUP BY market_cap_category"
        ).fetchall()
        conn.execute(
            "SELECT COUNT(*) FROM symbol_fundamentals WHERE stability_score IS NOT NULL"
        ).fetchone()

        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"\n  Statistics (4 queries): {elapsed_ms:.2f}ms")
        assert elapsed_ms < 30, f"Statistics aggregation too slow: {elapsed_ms:.2f}ms"

    def test_explain_query_plan(self, conn: sqlite3.Connection) -> None:
        """Verify index usage for key queries."""
        # Check if symbol_fundamentals has a proper index
        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM symbol_fundamentals WHERE symbol = 'AAPL'"
        ).fetchall()
        plan_str = " | ".join(str(dict(row)) for row in plan)
        print(f"\n  Query plan (single lookup): {plan_str}")

        # Check stability filter
        plan2 = conn.execute(
            "EXPLAIN QUERY PLAN "
            f"SELECT * FROM symbol_fundamentals WHERE stability_score >= {ENTRY_STABILITY_MIN} "
            "ORDER BY stability_score DESC"
        ).fetchall()
        plan2_str = " | ".join(str(dict(row)) for row in plan2)
        print(f"  Query plan (stability filter): {plan2_str}")


# =============================================================================
# BENCHMARK: Earnings History
# =============================================================================

class TestEarningsBenchmarks:
    """Benchmarks for earnings_history queries."""

    @pytest.fixture
    def conn(self) -> sqlite3.Connection:
        conn = get_db_connection()
        yield conn
        conn.close()

    def test_earnings_safety_check_single(self, conn: sqlite3.Connection) -> None:
        """Benchmark: check earnings safety for a single symbol."""
        today = date.today()
        window_start = today - timedelta(days=5)
        window_end = today + timedelta(days=45)

        elapsed_ms, rows = time_query(
            conn,
            "SELECT symbol, earnings_date, time_of_day "
            "FROM earnings_history "
            "WHERE symbol = ? "
            "AND earnings_date >= ? AND earnings_date <= ? "
            "ORDER BY earnings_date ASC",
            ("AAPL", window_start.isoformat(), window_end.isoformat())
        )
        print(f"\n  Earnings check (AAPL): {len(rows)} rows in {elapsed_ms:.2f}ms")
        assert elapsed_ms < 10, f"Single earnings check too slow: {elapsed_ms:.2f}ms"

    def test_earnings_safety_check_batch(self, conn: sqlite3.Connection) -> None:
        """Benchmark: batch earnings safety check for 100 symbols."""
        _, all_rows = time_query(
            conn, "SELECT DISTINCT symbol FROM earnings_history LIMIT 100"
        )
        symbols = [row["symbol"] for row in all_rows]

        if len(symbols) < 20:
            pytest.skip("Not enough symbols with earnings data")

        today = date.today()
        window_start = today - timedelta(days=5)
        window_end = today + timedelta(days=45)

        placeholders = ",".join("?" * len(symbols))
        elapsed_ms, rows = time_query(
            conn,
            f"SELECT symbol, earnings_date, time_of_day "
            f"FROM earnings_history "
            f"WHERE symbol IN ({placeholders}) "
            f"AND earnings_date >= ? AND earnings_date <= ? "
            f"ORDER BY symbol, earnings_date ASC",
            tuple(symbols) + (window_start.isoformat(), window_end.isoformat())
        )
        print(f"\n  Batch earnings ({len(symbols)} symbols): {len(rows)} rows in {elapsed_ms:.2f}ms")
        assert elapsed_ms < 50, f"Batch earnings check too slow: {elapsed_ms:.2f}ms"

    def test_explain_earnings_query_plan(self, conn: sqlite3.Connection) -> None:
        """Verify index usage for earnings queries."""
        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT symbol, earnings_date FROM earnings_history "
            "WHERE symbol = 'AAPL' AND earnings_date >= '2026-01-01' "
            "ORDER BY earnings_date ASC"
        ).fetchall()
        plan_str = " | ".join(str(dict(row)) for row in plan)
        print(f"\n  Earnings query plan: {plan_str}")


# =============================================================================
# BENCHMARK: VIX Data
# =============================================================================

class TestVIXBenchmarks:
    """Benchmarks for vix_data queries."""

    @pytest.fixture
    def conn(self) -> sqlite3.Connection:
        conn = get_db_connection()
        yield conn
        conn.close()

    def test_vix_exact_date(self, conn: sqlite3.Connection) -> None:
        """Benchmark: exact VIX date lookup."""
        # Get a known date
        _, rows = time_query(conn, "SELECT date FROM vix_data LIMIT 1")
        if not rows:
            pytest.skip("No VIX data")

        target = rows[0]["date"]

        elapsed_ms, result = time_query(
            conn,
            "SELECT value FROM vix_data WHERE date = ?",
            (target,)
        )
        print(f"\n  VIX exact lookup: {elapsed_ms:.3f}ms")
        assert elapsed_ms < 5, f"VIX lookup too slow: {elapsed_ms:.3f}ms"

    def test_vix_fallback_lookup(self, conn: sqlite3.Connection) -> None:
        """Benchmark: VIX fallback to closest previous date."""
        elapsed_ms, rows = time_query(
            conn,
            "SELECT value FROM vix_data "
            "WHERE date < ? ORDER BY date DESC LIMIT 1",
            ("2025-12-25",)  # Christmas - market closed
        )
        print(f"\n  VIX fallback lookup: {elapsed_ms:.3f}ms")
        assert elapsed_ms < 5, f"VIX fallback too slow: {elapsed_ms:.3f}ms"

    def test_vix_statistics_query(self, conn: sqlite3.Connection) -> None:
        """Benchmark: VIX statistics aggregation in SQL vs Python."""
        # Current approach: fetch all, calculate in Python
        start = time.perf_counter()
        cursor = conn.execute(
            "SELECT value FROM vix_data ORDER BY date DESC LIMIT 252"
        )
        values = [row["value"] for row in cursor.fetchall()]
        if values:
            mean_val = sum(values) / len(values)
            min_val = min(values)
            max_val = max(values)
        python_ms = (time.perf_counter() - start) * 1000

        # Alternative: do aggregation in SQL
        sql_ms, sql_rows = time_query(
            conn,
            "SELECT AVG(value) as mean_val, MIN(value) as min_val, "
            "MAX(value) as max_val, COUNT(*) as cnt "
            "FROM (SELECT value FROM vix_data ORDER BY date DESC LIMIT 252)"
        )

        print(f"\n  VIX stats (252 days):")
        print(f"    Python-side: {python_ms:.2f}ms ({len(values)} rows)")
        print(f"    SQL-side:    {sql_ms:.2f}ms")
        if sql_ms > 0:
            print(f"    Speedup:     {python_ms / sql_ms:.1f}x")


# =============================================================================
# BENCHMARK: Options Prices (largest table)
# =============================================================================

class TestOptionsPricesBenchmarks:
    """Benchmarks for options_prices queries (19.3M rows)."""

    @pytest.fixture
    def conn(self) -> sqlite3.Connection:
        conn = get_db_connection()
        yield conn
        conn.close()

    def test_historical_scanner_query(self, conn: sqlite3.Connection) -> None:
        """Benchmark: scanner historical price query."""
        elapsed_ms, rows = time_query(
            conn,
            "SELECT quote_date, underlying_price "
            "FROM options_prices "
            "WHERE underlying = ? "
            "AND underlying_price IS NOT NULL "
            "GROUP BY quote_date "
            "ORDER BY quote_date DESC "
            "LIMIT ?",
            ("AAPL", 252)
        )
        print(f"\n  Scanner history (AAPL, 252d): {len(rows)} rows in {elapsed_ms:.2f}ms")
        # This is the critical per-symbol query in scan loops
        assert elapsed_ms < 500, f"Scanner history too slow: {elapsed_ms:.2f}ms"

    def test_options_chain_query(self, conn: sqlite3.Connection) -> None:
        """Benchmark: options chain with Greeks join."""
        # Get most recent date
        _, date_rows = time_query(
            conn,
            "SELECT MAX(quote_date) as latest FROM options_prices "
            "WHERE underlying = 'AAPL'"
        )
        if not date_rows or not date_rows[0]["latest"]:
            pytest.skip("No AAPL options data")

        latest = date_rows[0]["latest"]

        elapsed_ms, rows = time_query(
            conn,
            "SELECT p.underlying, p.quote_date, p.strike, p.option_type, "
            "p.bid, p.ask, p.underlying_price, p.dte, "
            "g.delta, g.gamma, g.theta, g.vega, g.iv_calculated "
            "FROM options_prices p "
            "JOIN options_greeks g ON g.options_price_id = p.id "
            "WHERE p.underlying = ? "
            "AND p.quote_date = ? "
            "AND p.option_type = 'put' "
            "AND p.dte BETWEEN 30 AND 60",
            ("AAPL", latest)
        )
        print(f"\n  Options chain (AAPL, puts 30-60 DTE): {len(rows)} rows in {elapsed_ms:.2f}ms")
        assert elapsed_ms < 1000, f"Options chain too slow: {elapsed_ms:.2f}ms"

    def test_explain_scanner_query(self, conn: sqlite3.Connection) -> None:
        """Check query plan for scanner query."""
        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT quote_date, underlying_price "
            "FROM options_prices "
            "WHERE underlying = 'AAPL' "
            "AND underlying_price IS NOT NULL "
            "GROUP BY quote_date "
            "ORDER BY quote_date DESC "
            "LIMIT 252"
        ).fetchall()
        plan_str = " | ".join(str(dict(row)) for row in plan)
        print(f"\n  Scanner query plan: {plan_str}")


# =============================================================================
# BENCHMARK: Outcomes DB
# =============================================================================

class TestOutcomesBenchmarks:
    """Benchmarks for outcomes.db queries."""

    @pytest.fixture
    def conn(self) -> Optional[sqlite3.Connection]:
        if not OUTCOMES_DB_PATH.exists():
            pytest.skip(f"Outcomes DB not found at {OUTCOMES_DB_PATH}")
        conn = sqlite3.connect(f"file:{OUTCOMES_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    def test_trade_outcomes_per_symbol(self, conn: sqlite3.Connection) -> None:
        """Benchmark: outcome statistics per symbol."""
        elapsed_ms, rows = time_query(
            conn,
            "SELECT "
            "COUNT(*) as trades, "
            "AVG(CASE WHEN outcome = 'max_profit' THEN 1.0 ELSE 0.0 END) * 100 as win_rate, "
            "AVG(max_drawdown_pct) as avg_drawdown "
            "FROM trade_outcomes "
            "WHERE symbol = ?",
            ("AAPL",)
        )
        if rows:
            row = rows[0]
            print(f"\n  Outcomes AAPL: {row['trades']} trades, "
                  f"win_rate={row['win_rate']:.1f}%, "
                  f"drawdown={row['avg_drawdown']:.2f}%, "
                  f"time={elapsed_ms:.2f}ms")
        assert elapsed_ms < 100, f"Outcome stats too slow: {elapsed_ms:.2f}ms"

    def test_bulk_outcomes_aggregation(self, conn: sqlite3.Connection) -> None:
        """Benchmark: aggregate outcomes for all symbols."""
        elapsed_ms, rows = time_query(
            conn,
            "SELECT symbol, "
            "COUNT(*) as trades, "
            "AVG(CASE WHEN outcome = 'max_profit' THEN 1.0 ELSE 0.0 END) * 100 as win_rate "
            "FROM trade_outcomes "
            "GROUP BY symbol "
            "HAVING COUNT(*) >= 10 "
            "ORDER BY win_rate DESC"
        )
        print(f"\n  Bulk outcomes ({len(rows)} symbols with 10+ trades): {elapsed_ms:.2f}ms")
        assert elapsed_ms < 500, f"Bulk outcomes too slow: {elapsed_ms:.2f}ms"


# =============================================================================
# BENCHMARK: End-to-end Scan Scenario
# =============================================================================

class TestScanScenarioBenchmarks:
    """Simulate a realistic scan workflow measuring DB bottlenecks."""

    @pytest.fixture
    def conn(self) -> sqlite3.Connection:
        conn = get_db_connection()
        yield conn
        conn.close()

    def test_full_scan_db_overhead(self, conn: sqlite3.Connection) -> None:
        """Simulate DB queries for a typical 50-symbol scan."""
        # Step 1: Get stable symbols
        start_total = time.perf_counter()

        t1, stable_rows = time_query(
            conn,
            "SELECT symbol FROM symbol_fundamentals "
            f"WHERE stability_score >= {ENTRY_STABILITY_MIN} ORDER BY stability_score DESC"
        )
        symbols = [row["symbol"] for row in stable_rows[:50]]

        if len(symbols) < 10:
            pytest.skip("Not enough stable symbols for scan simulation")

        # Step 2: Batch earnings check
        today = date.today()
        placeholders = ",".join("?" * len(symbols))
        t2, _ = time_query(
            conn,
            f"SELECT symbol, earnings_date, time_of_day "
            f"FROM earnings_history "
            f"WHERE symbol IN ({placeholders}) "
            f"AND earnings_date >= ? AND earnings_date <= ?",
            tuple(symbols) + (
                (today - timedelta(days=5)).isoformat(),
                (today + timedelta(days=45)).isoformat()
            )
        )

        # Step 3: Batch fundamentals
        t3, _ = time_query(
            conn,
            f"SELECT * FROM symbol_fundamentals WHERE symbol IN ({placeholders})",
            tuple(symbols)
        )

        # Step 4: Per-symbol historical price query (the bottleneck)
        historical_times = []
        for sym in symbols[:20]:  # Sample 20 symbols
            t, rows = time_query(
                conn,
                "SELECT quote_date, underlying_price "
                "FROM options_prices "
                "WHERE underlying = ? "
                "AND underlying_price IS NOT NULL "
                "GROUP BY quote_date "
                "ORDER BY quote_date DESC "
                "LIMIT 252",
                (sym,)
            )
            historical_times.append(t)

        total_ms = (time.perf_counter() - start_total) * 1000
        avg_hist = sum(historical_times) / len(historical_times) if historical_times else 0

        print(f"\n  Scan Simulation ({len(symbols)} symbols):")
        print(f"    Step 1 - Stable symbols:    {t1:.2f}ms")
        print(f"    Step 2 - Earnings batch:     {t2:.2f}ms")
        print(f"    Step 3 - Fundamentals batch: {t3:.2f}ms")
        print(f"    Step 4 - Historical (avg):   {avg_hist:.2f}ms/symbol")
        print(f"    Step 4 - Historical (total): {sum(historical_times):.2f}ms (20 symbols)")
        print(f"    Total DB overhead:           {total_ms:.2f}ms")
        print(f"    Projected for 50 symbols:    {t1 + t2 + t3 + avg_hist * 50:.0f}ms")

        # Baseline: document current performance for regression tracking
        # Historical query is the bottleneck (~260ms/symbol on 19M row table)
        # Optimization target: add index on (underlying, quote_date) to reduce to <50ms/symbol
        projected = t1 + t2 + t3 + avg_hist * 50
        assert projected < 30000, f"Projected scan DB overhead regression: {projected:.0f}ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
