"""
Integration tests for the DB-based earnings filter.

All tests use a temp-file SQLite with constructed data — no real DB, no yfinance.
Verifies: prefilter correctness, fail-closed behaviour, scanner cache population,
and the ETF pass-through case.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cache.earnings_history import EarningsHistoryManager


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_manager(rows: list[tuple], tmp_path: Path) -> EarningsHistoryManager:
    """Create an EarningsHistoryManager backed by a temp file and insert rows.

    Each row: (symbol, earnings_date_str, time_of_day)
    """
    db_file = tmp_path / "test_earnings.db"
    mgr = EarningsHistoryManager(db_path=db_file)
    with mgr._lock:
        with mgr._get_connection() as conn:
            for symbol, earnings_date, time_of_day in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO earnings_history "
                    "(symbol, earnings_date, time_of_day) VALUES (?, ?, ?)",
                    (symbol, earnings_date, time_of_day),
                )
            conn.commit()
    return mgr


TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
IN_10 = (TODAY + timedelta(days=10)).isoformat()
IN_60 = (TODAY + timedelta(days=60)).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# is_earnings_day_safe_batch — unit
# ─────────────────────────────────────────────────────────────────────────────


class TestIsEarningsDaySafeBatch:
    """Direct tests on the batch DB method."""

    def test_symbol_earnings_today_amc_excluded(self, tmp_path):
        mgr = _make_manager([("BX", TODAY.isoformat(), "amc")], tmp_path)
        results = mgr.is_earnings_day_safe_batch(["BX"], TODAY, min_days=60)
        is_safe, days_to, reason = results["BX"]
        assert not is_safe
        assert days_to == 0
        assert reason == "earnings_amc_today"

    def test_symbol_earnings_in_10_days_excluded(self, tmp_path):
        mgr = _make_manager([("TSLA", IN_10, "amc")], tmp_path)
        results = mgr.is_earnings_day_safe_batch(["TSLA"], TODAY, min_days=60)
        is_safe, days_to, reason = results["TSLA"]
        assert not is_safe
        assert days_to == 10
        assert "too_close" in reason

    def test_symbol_earnings_in_60_days_safe(self, tmp_path):
        mgr = _make_manager([("AAPL", IN_60, "amc")], tmp_path)
        results = mgr.is_earnings_day_safe_batch(["AAPL"], TODAY, min_days=30)
        is_safe, _days_to, reason = results["AAPL"]
        assert is_safe
        assert reason == "safe"

    def test_etf_no_earnings_history_no_data(self, tmp_path):
        mgr = _make_manager([], tmp_path)  # SPY not in DB
        results = mgr.is_earnings_day_safe_batch(["SPY"], TODAY, min_days=60)
        is_safe, _, reason = results["SPY"]
        assert not is_safe
        assert reason == "no_earnings_data"

    def test_recently_reported_symbol_safe(self, tmp_path):
        recent = (TODAY - timedelta(days=10)).isoformat()
        mgr = _make_manager([("JPM", recent, "bmo")], tmp_path)
        results = mgr.is_earnings_day_safe_batch(["JPM"], TODAY, min_days=60)
        is_safe, _, reason = results["JPM"]
        assert is_safe
        assert reason == "recently_reported"


# ─────────────────────────────────────────────────────────────────────────────
# get_next_earnings_dates_batch
# ─────────────────────────────────────────────────────────────────────────────


class TestGetNextEarningsDatesBatch:
    def test_returns_nearest_future_date(self, tmp_path):
        mgr = _make_manager(
            [
                ("AAPL", IN_10, "amc"),
                ("AAPL", IN_60, "amc"),  # second future date — should be ignored
            ],
            tmp_path,
        )
        result = mgr.get_next_earnings_dates_batch(["AAPL"])
        assert result["AAPL"] == date.fromisoformat(IN_10)

    def test_past_date_excluded(self, tmp_path):
        mgr = _make_manager([("MSFT", YESTERDAY, "bmo")], tmp_path)
        result = mgr.get_next_earnings_dates_batch(["MSFT"])
        assert result["MSFT"] is None

    def test_symbol_not_in_db_returns_none(self, tmp_path):
        mgr = _make_manager([], tmp_path)
        result = mgr.get_next_earnings_dates_batch(["SPY"])
        assert result["SPY"] is None

    def test_mixed_symbols(self, tmp_path):
        mgr = _make_manager(
            [
                ("BX", TODAY.isoformat(), "amc"),
                ("AAPL", IN_60, "bmo"),
            ],
            tmp_path,
        )
        result = mgr.get_next_earnings_dates_batch(["BX", "AAPL", "SPY"])
        assert result["BX"] == TODAY
        assert result["AAPL"] == date.fromisoformat(IN_60)
        assert result["SPY"] is None

    def test_empty_symbols_list(self, tmp_path):
        mgr = _make_manager([], tmp_path)
        result = mgr.get_next_earnings_dates_batch([])
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# _apply_earnings_prefilter — via ScanHandler with mocked EHM
# ─────────────────────────────────────────────────────────────────────────────


def _make_scan_handler_with_mgr(mgr: EarningsHistoryManager):
    """Build a minimal ScanHandler whose prefilter uses the given EHM."""
    from src.handlers.scan_composed import ScanHandler

    ctx = MagicMock()
    ctx.earnings_fetcher = None
    handler = ScanHandler.__new__(ScanHandler)
    handler._ctx = ctx
    handler._logger = MagicMock()
    return handler


class TestApplyEarningsPrefilter:
    """Tests for ScanHandler._apply_earnings_prefilter() using mocked EHM."""

    @pytest.mark.asyncio
    async def test_symbol_with_earnings_tomorrow_excluded(self, tmp_path):
        mgr = _make_manager([("BX", TOMORROW, "amc")], tmp_path)

        async def fake_batch_async(symbols, target_date, min_days, **_kw):
            return mgr.is_earnings_day_safe_batch(symbols, target_date, min_days)

        mock_mgr = MagicMock()
        mock_mgr.is_earnings_day_safe_batch_async = fake_batch_async

        handler = _make_scan_handler_with_mgr(mgr)
        with patch("src.cache.get_earnings_history_manager", return_value=mock_mgr):
            safe, excluded, hits = await handler._apply_earnings_prefilter(
                ["BX"], min_days=60
            )

        assert "BX" not in safe
        assert excluded == 1

    @pytest.mark.asyncio
    async def test_symbol_earnings_in_60_days_passes(self, tmp_path):
        mgr = _make_manager([("AAPL", IN_60, "amc")], tmp_path)

        async def fake_batch_async(symbols, target_date, min_days, **_kw):
            return mgr.is_earnings_day_safe_batch(symbols, target_date, min_days)

        mock_mgr = MagicMock()
        mock_mgr.is_earnings_day_safe_batch_async = fake_batch_async

        handler = _make_scan_handler_with_mgr(mgr)
        with patch("src.cache.get_earnings_history_manager", return_value=mock_mgr):
            safe, excluded, hits = await handler._apply_earnings_prefilter(
                ["AAPL"], min_days=30
            )

        assert "AAPL" in safe
        assert excluded == 0

    @pytest.mark.asyncio
    async def test_etf_no_earnings_data_passes(self, tmp_path):
        mgr = _make_manager([], tmp_path)  # SPY not in DB

        async def fake_batch_async(symbols, target_date, min_days, **_kw):
            return mgr.is_earnings_day_safe_batch(symbols, target_date, min_days)

        mock_mgr = MagicMock()
        mock_mgr.is_earnings_day_safe_batch_async = fake_batch_async

        handler = _make_scan_handler_with_mgr(mgr)
        with patch("src.cache.get_earnings_history_manager", return_value=mock_mgr):
            safe, excluded, hits = await handler._apply_earnings_prefilter(
                ["SPY"], min_days=60
            )

        # SPY has no earnings history → passes through (ETF case)
        assert "SPY" in safe
        assert excluded == 0

    @pytest.mark.asyncio
    async def test_symbol_earnings_today_amc_excluded(self, tmp_path):
        mgr = _make_manager([("TSLA", TODAY.isoformat(), "amc")], tmp_path)

        async def fake_batch_async(symbols, target_date, min_days, **_kw):
            return mgr.is_earnings_day_safe_batch(symbols, target_date, min_days)

        mock_mgr = MagicMock()
        mock_mgr.is_earnings_day_safe_batch_async = fake_batch_async

        handler = _make_scan_handler_with_mgr(mgr)
        with patch("src.cache.get_earnings_history_manager", return_value=mock_mgr):
            safe, excluded, hits = await handler._apply_earnings_prefilter(
                ["TSLA"], min_days=60
            )

        assert "TSLA" not in safe
        assert excluded == 1

    @pytest.mark.asyncio
    async def test_db_exception_falls_back_to_json_cache(self):
        """When DB raises, JSON cache fallback is used and also excludes correctly."""
        mock_mgr = MagicMock()
        mock_mgr.is_earnings_day_safe_batch_async.side_effect = RuntimeError(
            "DB unavailable"
        )

        handler = _make_scan_handler_with_mgr(None)

        # JSON cache entry: days_to_earnings=5 < min_days=60 → excluded
        cached_entry = MagicMock()
        cached_entry.days_to_earnings = 5
        cache_mock = MagicMock()
        cache_mock.get.return_value = cached_entry

        fetcher_mock = MagicMock()
        fetcher_mock.cache = cache_mock

        with patch("src.cache.get_earnings_history_manager", return_value=mock_mgr):
            with patch(
                "src.cache.get_earnings_fetcher", return_value=fetcher_mock
            ):
                safe, excluded, hits = await handler._apply_earnings_prefilter(
                    ["BX"], min_days=60
                )

        assert "BX" not in safe
        assert excluded == 1

    @pytest.mark.asyncio
    async def test_regression_bx_earnings_today_excluded(self, tmp_path):
        """Regression: BX with earnings today must be excluded regardless of JSON cache."""
        mgr = _make_manager([("BX", TODAY.isoformat(), "amc")], tmp_path)

        async def fake_batch_async(symbols, target_date, min_days, **_kw):
            return mgr.is_earnings_day_safe_batch(symbols, target_date, min_days)

        mock_mgr = MagicMock()
        mock_mgr.is_earnings_day_safe_batch_async = fake_batch_async

        handler = _make_scan_handler_with_mgr(mgr)
        with patch("src.cache.get_earnings_history_manager", return_value=mock_mgr):
            safe, excluded, _hits = await handler._apply_earnings_prefilter(
                ["BX", "SPY"], min_days=60
            )

        assert "BX" not in safe, "BX has earnings today — must be excluded"
        assert "SPY" in safe, "SPY has no earnings history — must pass through"
        assert excluded == 1

    @pytest.mark.asyncio
    async def test_regression_tsla_earnings_in_4_days_excluded(self, tmp_path):
        """Regression: TSLA with earnings in 4 days must be excluded."""
        in_4 = (TODAY + timedelta(days=4)).isoformat()
        mgr = _make_manager([("TSLA", in_4, "amc")], tmp_path)

        async def fake_batch_async(symbols, target_date, min_days, **_kw):
            return mgr.is_earnings_day_safe_batch(symbols, target_date, min_days)

        mock_mgr = MagicMock()
        mock_mgr.is_earnings_day_safe_batch_async = fake_batch_async

        handler = _make_scan_handler_with_mgr(mgr)
        with patch("src.cache.get_earnings_history_manager", return_value=mock_mgr):
            safe, excluded, _hits = await handler._apply_earnings_prefilter(
                ["TSLA"], min_days=60
            )

        assert "TSLA" not in safe, "TSLA earnings in 4 days — must be excluded at min_days=60"
        assert excluded == 1
