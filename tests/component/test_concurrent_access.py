#!/usr/bin/env python3
"""
F.2: Concurrent Access Tests

Tests for thread safety of singletons, caches, and shared state:
- Singleton initialization races
- Concurrent cache reads/writes
- DividendHistoryManager concurrent operations
- EarningsHistoryManager concurrent operations
- SymbolFundamentalsManager concurrent operations

Usage:
    pytest tests/component/test_concurrent_access.py -v
"""

import threading
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pytest


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_db():
    """Creates temporary DB for tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
    Path(f.name).unlink(missing_ok=True)


# =============================================================================
# DIVIDEND HISTORY THREAD SAFETY
# =============================================================================

class TestDividendHistoryConcurrent:
    """Thread safety tests for DividendHistoryManager."""

    def test_concurrent_writes_no_corruption(self, temp_db):
        """Multiple threads writing dividends should not corrupt DB."""
        from src.cache.dividend_history import DividendHistoryManager

        manager = DividendHistoryManager(db_path=temp_db)
        errors = []

        def write_dividends(thread_id):
            try:
                symbol = f"SYM{thread_id:03d}"
                divs = [
                    {"ex_date": f"2025-{m:02d}-15", "amount": 0.25 + thread_id * 0.01}
                    for m in range(1, 5)
                ]
                manager.save_dividends(symbol, divs)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_dividends, i) for i in range(20)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors during concurrent writes: {errors}"
        assert manager.get_symbol_count() == 20

    def test_concurrent_reads_no_crash(self, temp_db):
        """Multiple threads reading dividends should not crash."""
        from src.cache.dividend_history import DividendHistoryManager

        manager = DividendHistoryManager(db_path=temp_db)
        # Pre-populate data
        for i in range(10):
            manager.save_dividends(f"SYM{i:03d}", [
                {"ex_date": "2025-02-15", "amount": 0.25}
            ])

        errors = []

        def read_dividends(thread_id):
            try:
                for _ in range(50):
                    symbol = f"SYM{thread_id % 10:03d}"
                    manager.get_dividends(symbol)
                    manager.is_near_ex_dividend(symbol, date(2025, 2, 15))
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_dividends, i) for i in range(20)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors during concurrent reads: {errors}"

    def test_concurrent_read_write_mix(self, temp_db):
        """Mixed reads and writes should not corrupt data."""
        from src.cache.dividend_history import DividendHistoryManager

        manager = DividendHistoryManager(db_path=temp_db)
        errors = []

        def mixed_task(thread_id):
            try:
                symbol = f"MIX{thread_id % 5:03d}"
                for i in range(30):
                    if i % 3 == 0:
                        manager.save_dividends(symbol, [
                            {"ex_date": f"2025-{(i % 12) + 1:02d}-15", "amount": 0.25}
                        ])
                    else:
                        manager.get_dividends(symbol)
                        manager.is_near_ex_dividend(symbol, date(2025, 2, 15))
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(mixed_task, i) for i in range(15)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors during mixed R/W: {errors}"

    def test_concurrent_batch_query(self, temp_db):
        """Concurrent batch near-ex-dividend queries should not crash."""
        from src.cache.dividend_history import DividendHistoryManager

        manager = DividendHistoryManager(db_path=temp_db)
        symbols = [f"SYM{i:03d}" for i in range(20)]
        for sym in symbols:
            manager.save_dividends(sym, [{"ex_date": "2025-02-15", "amount": 0.30}])

        errors = []

        def batch_query(thread_id):
            try:
                for _ in range(20):
                    result = manager.is_near_ex_dividend_batch(symbols, date(2025, 2, 15))
                    assert isinstance(result, dict)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(batch_query, i) for i in range(5)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors during batch queries: {errors}"


# =============================================================================
# SINGLETON INITIALIZATION RACES
# =============================================================================

class TestSingletonRaces:
    """Tests for concurrent singleton initialization."""

    def test_dividend_singleton_concurrent_init(self, temp_db):
        """Concurrent get_dividend_history_manager calls should return same instance."""
        from src.cache.dividend_history import (
            get_dividend_history_manager,
            reset_dividend_history_manager,
        )

        reset_dividend_history_manager()
        instances = []
        errors = []

        def get_instance(thread_id):
            try:
                mgr = get_dividend_history_manager(temp_db)
                instances.append(id(mgr))
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=get_instance, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors: {errors}"
        # All instances should be the same object
        unique_ids = set(instances)
        assert len(unique_ids) == 1, f"Got {len(unique_ids)} different instances"
        reset_dividend_history_manager()

    def test_earnings_singleton_concurrent_init(self, temp_db):
        """Concurrent get_earnings_history_manager calls should return same instance."""
        from src.cache.earnings_history import (
            get_earnings_history_manager,
            reset_earnings_history_manager,
        )

        reset_earnings_history_manager()
        instances = []
        errors = []

        def get_instance(thread_id):
            try:
                mgr = get_earnings_history_manager(temp_db)
                instances.append(id(mgr))
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=get_instance, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors: {errors}"
        unique_ids = set(instances)
        assert len(unique_ids) == 1, f"Got {len(unique_ids)} different instances"
        reset_earnings_history_manager()


# =============================================================================
# EARNINGS HISTORY THREAD SAFETY
# =============================================================================

class TestEarningsHistoryConcurrent:
    """Thread safety tests for EarningsHistoryManager."""

    def test_concurrent_writes(self, temp_db):
        """Multiple threads saving earnings should not corrupt DB."""
        from src.cache.earnings_history import EarningsHistoryManager

        manager = EarningsHistoryManager(db_path=temp_db)
        errors = []

        def write_earnings(thread_id):
            try:
                symbol = f"EARN{thread_id:03d}"
                earnings = [
                    {
                        "earnings_date": f"2025-{q:02d}-15",
                        "fiscal_year": 2025,
                        "fiscal_quarter": f"Q{q // 3 + 1}",
                        "eps_actual": 1.50 + thread_id * 0.1,
                        "eps_estimate": 1.45,
                        "time_of_day": "bmo",
                    }
                    for q in [2, 5, 8, 11]
                ]
                manager.save_earnings(symbol, earnings)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_earnings, i) for i in range(15)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors during concurrent writes: {errors}"

    def test_concurrent_reads(self, temp_db):
        """Multiple threads reading earnings should not crash."""
        from src.cache.earnings_history import EarningsHistoryManager

        manager = EarningsHistoryManager(db_path=temp_db)
        # Pre-populate
        for i in range(5):
            manager.save_earnings(f"EARN{i:03d}", [
                {"earnings_date": "2025-02-15", "fiscal_year": 2025,
                 "fiscal_quarter": "Q1", "eps_actual": 1.50, "time_of_day": "bmo"}
            ])

        errors = []

        def read_earnings(thread_id):
            try:
                for _ in range(50):
                    symbol = f"EARN{thread_id % 5:03d}"
                    manager.get_all_earnings(symbol)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_earnings, i) for i in range(10)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors during concurrent reads: {errors}"


# =============================================================================
# SCORE NORMALIZATION THREAD SAFETY
# =============================================================================

class TestScoreNormalizationConcurrent:
    """Thread safety tests for score normalization (stateless, should be safe)."""

    def test_concurrent_normalize_calls(self):
        """Concurrent normalize_score calls should produce correct results."""
        from src.analyzers.score_normalization import normalize_score

        errors = []

        def normalize_many(thread_id):
            try:
                for i in range(100):
                    raw = (thread_id * 100 + i) % 14
                    result = normalize_score(raw, "pullback")
                    expected = (raw / 14.0) * 10.0
                    expected = max(0.0, min(10.0, expected))
                    assert abs(result - expected) < 1e-10, \
                        f"Expected {expected}, got {result}"
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(normalize_many, i) for i in range(10)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors: {errors}"


# =============================================================================
# POSITION SIZER THREAD SAFETY
# =============================================================================

class TestPositionSizerConcurrent:
    """Thread safety tests for position sizing calculations."""

    def test_concurrent_kelly_calculations(self):
        """Concurrent Kelly calculations should produce consistent results."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        errors = []

        def calculate_kelly(thread_id):
            try:
                for i in range(100):
                    win_rate = 0.5 + (thread_id % 4) * 0.05
                    result = sizer.calculate_kelly_fraction(
                        win_rate=win_rate,
                        avg_win=150.0,
                        avg_loss=100.0,
                    )
                    assert 0.0 <= result <= 0.25, f"Kelly out of bounds: {result}"
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(calculate_kelly, i) for i in range(8)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors: {errors}"

    def test_concurrent_position_size_calculations(self):
        """Concurrent position size calculations should not interfere."""
        from src.risk.position_sizing import PositionSizer

        sizer = PositionSizer(account_size=100000)
        errors = []

        def calc_size(thread_id):
            try:
                for _ in range(50):
                    result = sizer.calculate_position_size(
                        max_loss_per_contract=500,
                        win_rate=0.65,
                        avg_win=150.0,
                        avg_loss=100.0,
                        signal_score=7.0 + thread_id * 0.1,
                        vix_level=20.0 + thread_id,
                    )
                    assert result.contracts >= 0
                    assert result.capital_at_risk >= 0
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(calc_size, i) for i in range(8)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errors: {errors}"
