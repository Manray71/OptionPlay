"""
Tests for liquidity tier classification system.

Tests:
- Tier assignment logic
- DB column migration
- Median OI calculation
- WatchlistLoader.get_symbols_by_tier()
- DailyPick.liquidity_tier field
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Tier Assignment Tests
# =============================================================================


class TestAssignTier:
    """Test the assign_tier() function."""

    def test_tier_1_high_oi(self):
        from scripts.classify_liquidity import assign_tier

        assert assign_tier(1000) == 1
        assert assign_tier(501) == 1
        assert assign_tier(5000) == 1

    def test_tier_1_boundary(self):
        from scripts.classify_liquidity import assign_tier

        # > 500 is Tier 1
        assert assign_tier(500.1) == 1
        # == 500 is NOT Tier 1 (threshold is > 500)
        assert assign_tier(500) == 2

    def test_tier_2_medium_oi(self):
        from scripts.classify_liquidity import assign_tier

        assert assign_tier(200) == 2
        assert assign_tier(100) == 2
        assert assign_tier(300) == 2

    def test_tier_3_low_oi(self):
        from scripts.classify_liquidity import assign_tier

        assert assign_tier(99) == 3
        assert assign_tier(50) == 3
        assert assign_tier(10) == 3
        assert assign_tier(0) == 3

    def test_tier_3_zero(self):
        from scripts.classify_liquidity import assign_tier

        assert assign_tier(0) == 3
        assert assign_tier(0.0) == 3


# =============================================================================
# DB Column Migration Tests
# =============================================================================


class TestEnsureColumns:
    """Test ensure_columns() adds missing columns."""

    def test_adds_missing_columns(self):
        from scripts.classify_liquidity import ensure_columns

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE symbol_fundamentals (symbol TEXT PRIMARY KEY)")
        conn.commit()

        ensure_columns(conn)

        # Verify columns exist
        cursor = conn.execute("SELECT liquidity_tier, avg_put_oi FROM symbol_fundamentals LIMIT 1")
        assert cursor.description[0][0] == "liquidity_tier"
        assert cursor.description[1][0] == "avg_put_oi"
        conn.close()

    def test_idempotent(self):
        from scripts.classify_liquidity import ensure_columns

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE symbol_fundamentals ("
            "symbol TEXT PRIMARY KEY, liquidity_tier INTEGER, avg_put_oi REAL)"
        )
        conn.commit()

        # Should not raise
        ensure_columns(conn)
        conn.close()


# =============================================================================
# Update Symbol Tier Tests
# =============================================================================


class TestUpdateSymbolTier:
    """Test update_symbol_tier() writes to DB correctly."""

    def test_updates_existing_symbol(self):
        from scripts.classify_liquidity import ensure_columns, update_symbol_tier

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE symbol_fundamentals (" "symbol TEXT PRIMARY KEY, updated_at TEXT)"
        )
        conn.execute("INSERT INTO symbol_fundamentals (symbol) VALUES ('AAPL')")
        conn.commit()
        ensure_columns(conn)

        result = update_symbol_tier(conn, "AAPL", 1, 1500.0)
        assert result is True

        row = conn.execute(
            "SELECT liquidity_tier, avg_put_oi FROM symbol_fundamentals WHERE symbol = 'AAPL'"
        ).fetchone()
        assert row[0] == 1
        assert row[1] == 1500.0
        conn.close()

    def test_nonexistent_symbol_returns_false(self):
        from scripts.classify_liquidity import ensure_columns, update_symbol_tier

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE symbol_fundamentals (" "symbol TEXT PRIMARY KEY, updated_at TEXT)"
        )
        conn.commit()
        ensure_columns(conn)

        result = update_symbol_tier(conn, "FAKE", 3, 0.0)
        assert result is False
        conn.close()


# =============================================================================
# Median OI Calculation Tests
# =============================================================================


class TestCalculateMedianPutOI:
    """Test calculate_median_put_oi() with in-memory DB."""

    def _create_test_db(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE options_prices (
                id INTEGER PRIMARY KEY,
                underlying TEXT,
                quote_date TEXT,
                option_type TEXT,
                dte INTEGER,
                open_interest INTEGER,
                strike REAL,
                bid REAL,
                ask REAL,
                underlying_price REAL
            )
        """)
        return conn

    def test_returns_median_oi(self):
        from scripts.classify_liquidity import calculate_median_put_oi

        conn = self._create_test_db()
        # Insert 10 days of data with varying OI
        for i in range(10):
            day = f"2026-01-{10+i:02d}"
            conn.execute(
                "INSERT INTO options_prices (underlying, quote_date, option_type, dte, open_interest, strike) "
                "VALUES (?, ?, 'P', 75, ?, 100.0)",
                ("AAPL", day, (i + 1) * 100),
            )
        conn.commit()

        result = calculate_median_put_oi(conn, "AAPL")
        assert result is not None
        # Median of [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000] = 550
        assert result == 550.0
        conn.close()

    def test_returns_none_insufficient_data(self):
        from scripts.classify_liquidity import calculate_median_put_oi

        conn = self._create_test_db()
        # Insert only 2 days (< 5 minimum)
        for i in range(2):
            day = f"2026-01-{10+i:02d}"
            conn.execute(
                "INSERT INTO options_prices (underlying, quote_date, option_type, dte, open_interest, strike) "
                "VALUES (?, ?, 'P', 75, 100, 100.0)",
                ("AAPL", day),
            )
        conn.commit()

        result = calculate_median_put_oi(conn, "AAPL")
        assert result is None
        conn.close()

    def test_ignores_calls(self):
        from scripts.classify_liquidity import calculate_median_put_oi

        conn = self._create_test_db()
        for i in range(10):
            day = f"2026-01-{10+i:02d}"
            # Put with OI=100
            conn.execute(
                "INSERT INTO options_prices (underlying, quote_date, option_type, dte, open_interest, strike) "
                "VALUES (?, ?, 'P', 75, 100, 100.0)",
                ("AAPL", day),
            )
            # Call with OI=9999 (should be ignored)
            conn.execute(
                "INSERT INTO options_prices (underlying, quote_date, option_type, dte, open_interest, strike) "
                "VALUES (?, ?, 'C', 75, 9999, 100.0)",
                ("AAPL", day),
            )
        conn.commit()

        result = calculate_median_put_oi(conn, "AAPL")
        assert result is not None
        assert result == 100.0  # Only puts counted
        conn.close()

    def test_filters_dte_range(self):
        from scripts.classify_liquidity import calculate_median_put_oi

        conn = self._create_test_db()
        for i in range(10):
            day = f"2026-01-{10+i:02d}"
            # In range (DTE=75)
            conn.execute(
                "INSERT INTO options_prices (underlying, quote_date, option_type, dte, open_interest, strike) "
                "VALUES (?, ?, 'P', 75, 500, 100.0)",
                ("AAPL", day),
            )
            # Out of range (DTE=30)
            conn.execute(
                "INSERT INTO options_prices (underlying, quote_date, option_type, dte, open_interest, strike) "
                "VALUES (?, ?, 'put', 30, 9999, 100.0)",
                ("AAPL", day),
            )
        conn.commit()

        result = calculate_median_put_oi(conn, "AAPL")
        assert result is not None
        assert result == 500.0  # Only 60-90 DTE puts counted
        conn.close()


# =============================================================================
# WatchlistLoader.get_symbols_by_tier() Tests
# =============================================================================


class TestGetSymbolsByTier:
    """Test WatchlistLoader.get_symbols_by_tier()."""

    def _make_loader(self):
        """Create a WatchlistLoader with known symbols."""
        from src.config.watchlist_loader import WatchlistLoader

        loader = WatchlistLoader.__new__(WatchlistLoader)
        loader._all_symbols = ["AAPL", "MSFT", "TINY", "UNKNOWN"]
        loader._sectors = {}
        loader._watchlists = {}
        loader._stability_split_enabled = False
        loader._stable_min_score = 60.0
        loader._include_unknown_in_risk = True
        loader._stable_symbols = None
        loader._risk_symbols = None
        loader._default_list = "default_275"
        loader.config_path = None
        return loader

    @patch("src.cache.get_fundamentals_manager")
    def test_tier_1_only(self, mock_get_manager):
        from src.cache.symbol_fundamentals import SymbolFundamentals

        loader = self._make_loader()
        manager = MagicMock()
        mock_get_manager.return_value = manager

        manager.get_fundamentals_batch.return_value = {
            "AAPL": SymbolFundamentals(symbol="AAPL", liquidity_tier=1),
            "MSFT": SymbolFundamentals(symbol="MSFT", liquidity_tier=2),
            "TINY": SymbolFundamentals(symbol="TINY", liquidity_tier=3),
        }

        result = loader.get_symbols_by_tier(max_tier=1)
        assert result == ["AAPL"]

    @patch("src.cache.get_fundamentals_manager")
    def test_tier_1_and_2(self, mock_get_manager):
        from src.cache.symbol_fundamentals import SymbolFundamentals

        loader = self._make_loader()
        manager = MagicMock()
        mock_get_manager.return_value = manager

        manager.get_fundamentals_batch.return_value = {
            "AAPL": SymbolFundamentals(symbol="AAPL", liquidity_tier=1),
            "MSFT": SymbolFundamentals(symbol="MSFT", liquidity_tier=2),
            "TINY": SymbolFundamentals(symbol="TINY", liquidity_tier=3),
        }

        result = loader.get_symbols_by_tier(max_tier=2)
        assert "AAPL" in result
        assert "MSFT" in result
        assert "TINY" not in result
        # UNKNOWN has no tier data, included at max_tier >= 2
        assert "UNKNOWN" in result

    @patch("src.cache.get_fundamentals_manager")
    def test_no_tier_data_returns_all(self, mock_get_manager):
        from src.cache.symbol_fundamentals import SymbolFundamentals

        loader = self._make_loader()
        manager = MagicMock()
        mock_get_manager.return_value = manager

        # No symbols have tier data
        manager.get_fundamentals_batch.return_value = {
            "AAPL": SymbolFundamentals(symbol="AAPL"),
            "MSFT": SymbolFundamentals(symbol="MSFT"),
        }

        result = loader.get_symbols_by_tier(max_tier=1)
        assert result == ["AAPL", "MSFT", "TINY", "UNKNOWN"]


# =============================================================================
# DailyPick.liquidity_tier Tests
# =============================================================================


class TestDailyPickLiquidityTier:
    """Test that DailyPick has liquidity_tier field."""

    def test_field_exists_default_none(self):
        from src.services.recommendation_engine import DailyPick

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
        )
        assert pick.liquidity_tier is None

    def test_field_can_be_set(self):
        from src.services.recommendation_engine import DailyPick

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            liquidity_tier=1,
        )
        assert pick.liquidity_tier == 1

    def test_to_dict_includes_tier(self):
        from src.services.recommendation_engine import DailyPick

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
            liquidity_tier=2,
        )
        d = pick.to_dict()
        assert d["liquidity_tier"] == 2

    def test_to_dict_omits_tier_when_none(self):
        from src.services.recommendation_engine import DailyPick

        pick = DailyPick(
            rank=1,
            symbol="AAPL",
            strategy="pullback",
            score=7.5,
            stability_score=85.0,
        )
        d = pick.to_dict()
        assert "liquidity_tier" not in d


# =============================================================================
# SymbolFundamentals Liquidity Fields Tests
# =============================================================================


class TestSymbolFundamentalsLiquidityFields:
    """Test that SymbolFundamentals has liquidity tier fields."""

    def test_fields_exist(self):
        from src.cache.symbol_fundamentals import SymbolFundamentals

        f = SymbolFundamentals(symbol="AAPL")
        assert f.liquidity_tier is None
        assert f.avg_put_oi is None

    def test_fields_in_to_dict(self):
        from src.cache.symbol_fundamentals import SymbolFundamentals

        f = SymbolFundamentals(symbol="AAPL", liquidity_tier=1, avg_put_oi=1500.0)
        d = f.to_dict()
        assert d["liquidity_tier"] == 1
        assert d["avg_put_oi"] == 1500.0

    def test_from_dict(self):
        from src.cache.symbol_fundamentals import SymbolFundamentals

        f = SymbolFundamentals.from_dict(
            {"symbol": "AAPL", "liquidity_tier": 2, "avg_put_oi": 300.0}
        )
        assert f.liquidity_tier == 2
        assert f.avg_put_oi == 300.0


# =============================================================================
# Classify Symbols Integration Test
# =============================================================================


class TestClassifySymbols:
    """Test the classify_symbols() function with mocked DB."""

    @patch("scripts.classify_liquidity.DB_PATH")
    def test_classify_with_mock_db(self, mock_db_path, tmp_path):
        from scripts.classify_liquidity import classify_symbols

        db_file = tmp_path / "test.db"
        mock_db_path.__str__ = lambda self: str(db_file)
        # Patch the actual Path object
        import scripts.classify_liquidity as cl_module

        original_path = cl_module.DB_PATH
        cl_module.DB_PATH = db_file

        try:
            conn = sqlite3.connect(str(db_file))
            conn.execute(
                "CREATE TABLE symbol_fundamentals (" "symbol TEXT PRIMARY KEY, updated_at TEXT)"
            )
            conn.execute("INSERT INTO symbol_fundamentals (symbol) VALUES ('AAPL')")
            conn.execute("INSERT INTO symbol_fundamentals (symbol) VALUES ('TINY')")

            conn.execute("""
                CREATE TABLE options_prices (
                    id INTEGER PRIMARY KEY,
                    underlying TEXT,
                    quote_date TEXT,
                    option_type TEXT,
                    dte INTEGER,
                    open_interest INTEGER,
                    strike REAL
                )
            """)

            # AAPL: high OI -> Tier 1
            for i in range(10):
                day = f"2026-01-{10+i:02d}"
                conn.execute(
                    "INSERT INTO options_prices (underlying, quote_date, option_type, dte, open_interest, strike) "
                    "VALUES ('AAPL', ?, 'P', 75, 2000, 150.0)",
                    (day,),
                )

            # TINY: low OI -> Tier 3
            for i in range(10):
                day = f"2026-01-{10+i:02d}"
                conn.execute(
                    "INSERT INTO options_prices (underlying, quote_date, option_type, dte, open_interest, strike) "
                    "VALUES ('TINY', ?, 'P', 75, 10, 20.0)",
                    (day,),
                )

            conn.commit()
            conn.close()

            tiers = classify_symbols(dry_run=False)

            assert "AAPL" in tiers[1]
            assert "TINY" in tiers[3]

            # Verify DB was updated
            conn = sqlite3.connect(str(db_file))
            row = conn.execute(
                "SELECT liquidity_tier, avg_put_oi FROM symbol_fundamentals WHERE symbol = 'AAPL'"
            ).fetchone()
            assert row[0] == 1
            assert row[1] == 2000.0

            row = conn.execute(
                "SELECT liquidity_tier FROM symbol_fundamentals WHERE symbol = 'TINY'"
            ).fetchone()
            assert row[0] == 3
            conn.close()
        finally:
            cl_module.DB_PATH = original_path
