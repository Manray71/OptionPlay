#!/usr/bin/env python3
"""
Tests for DividendHistoryManager (E.5: Dividend-Gap-Handling)

Usage:
    pytest tests/component/test_dividend_history.py -v
"""

import pytest
import tempfile
from datetime import date, timedelta
from pathlib import Path

from src.cache.dividend_history import (
    DividendHistoryManager,
    DividendRecord,
    get_dividend_history_manager,
    reset_dividend_history_manager,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_db():
    """Creates temporary DB for tests"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def manager(temp_db):
    """Creates manager with temporary DB"""
    return DividendHistoryManager(db_path=temp_db)


@pytest.fixture
def sample_dividends():
    """Sample dividend data for AAPL"""
    return [
        {"ex_date": "2025-02-07", "amount": 0.25},
        {"ex_date": "2024-11-08", "amount": 0.25},
        {"ex_date": "2024-08-12", "amount": 0.25},
        {"ex_date": "2024-05-10", "amount": 0.25},
        {"ex_date": "2024-02-09", "amount": 0.24},
        {"ex_date": "2023-11-10", "amount": 0.24},
    ]


@pytest.fixture
def sample_dividends_msft():
    """Sample dividend data for MSFT"""
    return [
        {"ex_date": "2025-02-20", "amount": 0.83},
        {"ex_date": "2024-11-21", "amount": 0.83},
        {"ex_date": "2024-08-15", "amount": 0.75},
    ]


# =============================================================================
# CRUD TESTS
# =============================================================================

class TestDividendCRUD:
    """Tests for basic CRUD operations"""

    def test_save_dividends(self, manager, sample_dividends):
        """Should save dividend records"""
        count = manager.save_dividends("AAPL", sample_dividends)
        assert count == 6

    def test_save_empty_list(self, manager):
        """Should return 0 for empty list"""
        count = manager.save_dividends("AAPL", [])
        assert count == 0

    def test_save_upsert(self, manager, sample_dividends):
        """Should upsert on duplicate (symbol, ex_date)"""
        manager.save_dividends("AAPL", sample_dividends)
        # Save again with updated amount
        updated = [{"ex_date": "2025-02-07", "amount": 0.26}]
        count = manager.save_dividends("AAPL", updated)
        assert count == 1

        # Verify the updated amount
        divs = manager.get_dividends("AAPL")
        feb_div = next(d for d in divs if d.ex_date == date(2025, 2, 7))
        assert feb_div.amount == 0.26

    def test_get_dividends(self, manager, sample_dividends):
        """Should get all dividends sorted by date DESC"""
        manager.save_dividends("AAPL", sample_dividends)
        divs = manager.get_dividends("AAPL")
        assert len(divs) == 6
        # Newest first
        assert divs[0].ex_date == date(2025, 2, 7)
        assert divs[-1].ex_date == date(2023, 11, 10)

    def test_get_dividends_empty(self, manager):
        """Should return empty list for unknown symbol"""
        divs = manager.get_dividends("UNKNOWN")
        assert divs == []

    def test_get_dividends_case_insensitive(self, manager, sample_dividends):
        """Should normalize to uppercase"""
        manager.save_dividends("aapl", sample_dividends)
        divs = manager.get_dividends("AAPL")
        assert len(divs) == 6

    def test_get_dividends_in_range(self, manager, sample_dividends):
        """Should filter by date range"""
        manager.save_dividends("AAPL", sample_dividends)
        divs = manager.get_dividends_in_range(
            "AAPL",
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        assert len(divs) == 4  # Feb, May, Aug, Nov 2024

    def test_delete_symbol(self, manager, sample_dividends):
        """Should delete all dividends for a symbol"""
        manager.save_dividends("AAPL", sample_dividends)
        deleted = manager.delete_symbol("AAPL")
        assert deleted == 6
        assert manager.get_dividends("AAPL") == []


# =============================================================================
# IS_NEAR_EX_DIVIDEND TESTS
# =============================================================================

class TestIsNearExDividend:
    """Tests for ex-dividend proximity check"""

    def test_on_ex_date(self, manager, sample_dividends):
        """Should return True on ex-dividend date"""
        manager.save_dividends("AAPL", sample_dividends)
        assert manager.is_near_ex_dividend("AAPL", date(2025, 2, 7)) is True

    def test_day_after_ex_date(self, manager, sample_dividends):
        """Should return True one day after ex-date (days_after=1)"""
        manager.save_dividends("AAPL", sample_dividends)
        assert manager.is_near_ex_dividend("AAPL", date(2025, 2, 8)) is True

    def test_day_before_ex_date(self, manager, sample_dividends):
        """Should return True two days before ex-date (days_before=2)"""
        manager.save_dividends("AAPL", sample_dividends)
        assert manager.is_near_ex_dividend("AAPL", date(2025, 2, 5)) is True

    def test_far_from_ex_date(self, manager, sample_dividends):
        """Should return False when far from ex-date"""
        manager.save_dividends("AAPL", sample_dividends)
        assert manager.is_near_ex_dividend("AAPL", date(2025, 1, 15)) is False

    def test_custom_window(self, manager, sample_dividends):
        """Should respect custom days_before/days_after"""
        manager.save_dividends("AAPL", sample_dividends)
        # With wider window
        assert manager.is_near_ex_dividend(
            "AAPL", date(2025, 2, 3), days_before=5, days_after=1
        ) is True
        # With narrow window
        assert manager.is_near_ex_dividend(
            "AAPL", date(2025, 2, 3), days_before=1, days_after=0
        ) is False

    def test_no_dividend_data(self, manager):
        """Should return False when no dividend data exists"""
        assert manager.is_near_ex_dividend("UNKNOWN", date(2025, 2, 7)) is False


# =============================================================================
# BATCH QUERY TESTS
# =============================================================================

class TestBatchQuery:
    """Tests for batch operations"""

    def test_batch_near_ex_dividend(self, manager, sample_dividends, sample_dividends_msft):
        """Should correctly identify near-dividend symbols in batch"""
        manager.save_dividends("AAPL", sample_dividends)
        manager.save_dividends("MSFT", sample_dividends_msft)

        result = manager.is_near_ex_dividend_batch(
            ["AAPL", "MSFT", "GOOGL"],
            date(2025, 2, 7)
        )
        assert result["AAPL"] is True   # ex-date is 2025-02-07
        assert result["MSFT"] is False  # ex-date is 2025-02-20
        assert result["GOOGL"] is False  # no data

    def test_batch_empty_symbols(self, manager):
        """Should return empty dict for empty symbols list"""
        result = manager.is_near_ex_dividend_batch([], date(2025, 2, 7))
        assert result == {}

    def test_batch_all_near(self, manager, sample_dividends, sample_dividends_msft):
        """Should identify both symbols near ex-date"""
        manager.save_dividends("AAPL", sample_dividends)
        manager.save_dividends("MSFT", sample_dividends_msft)

        result = manager.is_near_ex_dividend_batch(
            ["AAPL", "MSFT"],
            date(2025, 2, 20)  # MSFT ex-date
        )
        assert result["AAPL"] is False
        assert result["MSFT"] is True


# =============================================================================
# GET_EX_DIVIDEND_AMOUNT TESTS
# =============================================================================

class TestGetExDividendAmount:
    """Tests for amount lookup"""

    def test_get_amount_on_date(self, manager, sample_dividends):
        """Should return amount for exact ex-date"""
        manager.save_dividends("AAPL", sample_dividends)
        amount = manager.get_ex_dividend_amount("AAPL", date(2025, 2, 7))
        assert amount == 0.25

    def test_get_amount_near_date(self, manager, sample_dividends):
        """Should return amount for nearby date"""
        manager.save_dividends("AAPL", sample_dividends)
        amount = manager.get_ex_dividend_amount("AAPL", date(2025, 2, 8))
        assert amount == 0.25

    def test_get_amount_no_data(self, manager):
        """Should return None when no dividend data"""
        amount = manager.get_ex_dividend_amount("UNKNOWN", date(2025, 2, 7))
        assert amount is None

    def test_get_amount_far_from_date(self, manager, sample_dividends):
        """Should return None when far from any ex-date"""
        manager.save_dividends("AAPL", sample_dividends)
        amount = manager.get_ex_dividend_amount("AAPL", date(2025, 1, 1))
        assert amount is None


# =============================================================================
# STATISTICS TESTS
# =============================================================================

class TestStatistics:
    """Tests for statistics methods"""

    def test_symbol_count(self, manager, sample_dividends, sample_dividends_msft):
        """Should count distinct symbols"""
        manager.save_dividends("AAPL", sample_dividends)
        manager.save_dividends("MSFT", sample_dividends_msft)
        assert manager.get_symbol_count() == 2

    def test_total_count(self, manager, sample_dividends):
        """Should count total records"""
        manager.save_dividends("AAPL", sample_dividends)
        assert manager.get_total_count() == 6

    def test_get_statistics(self, manager, sample_dividends):
        """Should return comprehensive statistics"""
        manager.save_dividends("AAPL", sample_dividends)
        stats = manager.get_statistics()
        assert stats["total_symbols"] == 1
        assert stats["total_records"] == 6
        assert stats["date_range"]["from"] is not None


# =============================================================================
# SINGLETON TESTS
# =============================================================================

class TestSingleton:
    """Tests for singleton pattern"""

    def test_singleton_returns_same_instance(self, temp_db):
        """Should return same manager instance"""
        reset_dividend_history_manager()
        m1 = get_dividend_history_manager(temp_db)
        m2 = get_dividend_history_manager()
        assert m1 is m2
        reset_dividend_history_manager()

    def test_reset_clears_singleton(self, temp_db):
        """Should create new instance after reset"""
        reset_dividend_history_manager()
        m1 = get_dividend_history_manager(temp_db)
        reset_dividend_history_manager()
        m2 = get_dividend_history_manager(temp_db)
        assert m1 is not m2
        reset_dividend_history_manager()


# =============================================================================
# DIVIDEND RECORD TESTS
# =============================================================================

class TestDividendRecord:
    """Tests for DividendRecord dataclass"""

    def test_to_dict(self):
        """Should convert to dictionary"""
        record = DividendRecord(
            symbol="AAPL",
            ex_date=date(2025, 2, 7),
            amount=0.25,
            source="yfinance"
        )
        d = record.to_dict()
        assert d["symbol"] == "AAPL"
        assert d["ex_date"] == "2025-02-07"
        assert d["amount"] == 0.25
        assert d["source"] == "yfinance"

    def test_default_source(self):
        """Should default source to yfinance"""
        record = DividendRecord(symbol="AAPL", ex_date=date(2025, 2, 7))
        assert record.source == "yfinance"


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases"""

    def test_future_dates(self, manager):
        """Should handle future ex-dates"""
        future = date.today() + timedelta(days=30)
        divs = [{"ex_date": future.isoformat(), "amount": 0.50}]
        manager.save_dividends("AAPL", divs)

        result = manager.is_near_ex_dividend("AAPL", future)
        assert result is True

    def test_very_old_dates(self, manager):
        """Should handle very old ex-dates"""
        divs = [{"ex_date": "2010-01-15", "amount": 0.10}]
        manager.save_dividends("AAPL", divs)

        result = manager.is_near_ex_dividend("AAPL", date(2010, 1, 15))
        assert result is True

    def test_none_amount(self, manager):
        """Should handle None amount gracefully"""
        divs = [{"ex_date": "2025-02-07", "amount": None}]
        count = manager.save_dividends("AAPL", divs)
        assert count == 1

        amount = manager.get_ex_dividend_amount("AAPL", date(2025, 2, 7))
        assert amount is None

    def test_clear_all(self, manager, sample_dividends):
        """Should clear all data"""
        manager.save_dividends("AAPL", sample_dividends)
        deleted = manager.clear_all()
        assert deleted == 6
        assert manager.get_total_count() == 0
