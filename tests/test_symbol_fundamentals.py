# OptionPlay - Symbol Fundamentals Manager Tests
# ===============================================
# Comprehensive tests for symbol_fundamentals.py

import pytest
import sys
import sqlite3
import tempfile
import threading
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cache.symbol_fundamentals import (
    SymbolFundamentals,
    SymbolFundamentalsManager,
    categorize_market_cap,
    get_fundamentals_manager,
    reset_fundamentals_manager,
    DEFAULT_DB_PATH,
)


# =============================================================================
# DATACLASS TESTS
# =============================================================================

class TestSymbolFundamentalsDataclass:
    """Tests for SymbolFundamentals dataclass"""

    def test_create_minimal(self):
        """Create SymbolFundamentals with minimal data"""
        f = SymbolFundamentals(symbol="AAPL")

        assert f.symbol == "AAPL"
        assert f.sector is None
        assert f.market_cap is None
        assert f.stability_score is None

    def test_create_full(self):
        """Create SymbolFundamentals with full data"""
        f = SymbolFundamentals(
            symbol="AAPL",
            sector="Technology",
            industry="Consumer Electronics",
            market_cap=3000000000000.0,
            market_cap_category="Mega",
            beta=1.25,
            week_52_high=200.0,
            week_52_low=150.0,
            current_price=175.0,
            price_to_52w_high_pct=-12.5,
            average_volume=50000000.0,
            institutional_ownership=0.65,
            analyst_rating="BULLISH",
            analyst_buy=30,
            analyst_hold=5,
            analyst_sell=2,
            stability_score=85.5,
            historical_win_rate=92.0,
            iv_rank_252d=45.0,
            spy_correlation_60d=0.75,
            earnings_beat_rate=87.5,
        )

        assert f.symbol == "AAPL"
        assert f.sector == "Technology"
        assert f.market_cap == 3000000000000.0
        assert f.stability_score == 85.5
        assert f.earnings_beat_rate == 87.5

    def test_to_dict(self):
        """to_dict should convert to dictionary"""
        f = SymbolFundamentals(
            symbol="AAPL",
            sector="Technology",
            market_cap=3000000000000.0
        )

        d = f.to_dict()

        assert isinstance(d, dict)
        assert d["symbol"] == "AAPL"
        assert d["sector"] == "Technology"
        assert d["market_cap"] == 3000000000000.0

    def test_from_dict(self):
        """from_dict should create instance from dictionary"""
        data = {
            "symbol": "MSFT",
            "sector": "Technology",
            "market_cap": 2500000000000.0,
            "beta": 0.95,
            "unknown_field": "ignored"  # Should be ignored
        }

        f = SymbolFundamentals.from_dict(data)

        assert f.symbol == "MSFT"
        assert f.sector == "Technology"
        assert f.market_cap == 2500000000000.0
        assert f.beta == 0.95

    def test_from_dict_filters_unknown_fields(self):
        """from_dict should ignore unknown fields"""
        data = {
            "symbol": "AAPL",
            "nonexistent_field": "value",
            "another_unknown": 123
        }

        # Should not raise
        f = SymbolFundamentals.from_dict(data)
        assert f.symbol == "AAPL"


# =============================================================================
# MARKET CAP CATEGORIZATION TESTS
# =============================================================================

class TestMarketCapCategorization:
    """Tests for market cap categorization"""

    def test_mega_cap(self):
        """Market cap >= $200B should be Mega"""
        assert categorize_market_cap(300_000_000_000) == "Mega"
        assert categorize_market_cap(200_000_000_000) == "Mega"

    def test_large_cap(self):
        """Market cap $10B-$200B should be Large"""
        assert categorize_market_cap(50_000_000_000) == "Large"
        assert categorize_market_cap(10_000_000_000) == "Large"

    def test_mid_cap(self):
        """Market cap $2B-$10B should be Mid"""
        assert categorize_market_cap(5_000_000_000) == "Mid"
        assert categorize_market_cap(2_000_000_000) == "Mid"

    def test_small_cap(self):
        """Market cap $300M-$2B should be Small"""
        assert categorize_market_cap(1_000_000_000) == "Small"
        assert categorize_market_cap(300_000_000) == "Small"

    def test_micro_cap(self):
        """Market cap < $300M should be Micro"""
        assert categorize_market_cap(100_000_000) == "Micro"
        assert categorize_market_cap(50_000_000) == "Micro"

    def test_none_market_cap(self):
        """None market cap should return None"""
        assert categorize_market_cap(None) is None

    def test_zero_market_cap(self):
        """Zero market cap should return Micro"""
        assert categorize_market_cap(0) == "Micro"


# =============================================================================
# MANAGER TESTS
# =============================================================================

class TestSymbolFundamentalsManager:
    """Tests for SymbolFundamentalsManager"""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        # Cleanup
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def manager(self, temp_db):
        """Create manager with temp database"""
        return SymbolFundamentalsManager(db_path=temp_db)

    def test_init_creates_table(self, manager):
        """Manager should create table on init"""
        # Check table exists
        with manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='symbol_fundamentals'
            """)
            result = cursor.fetchone()

        assert result is not None

    def test_save_and_get_fundamentals(self, manager):
        """save_fundamentals and get_fundamentals should work"""
        f = SymbolFundamentals(
            symbol="AAPL",
            sector="Technology",
            market_cap=3000000000000.0,
            stability_score=85.5
        )

        result = manager.save_fundamentals(f)
        assert result is True

        retrieved = manager.get_fundamentals("AAPL")
        assert retrieved is not None
        assert retrieved.symbol == "AAPL"
        assert retrieved.sector == "Technology"
        assert retrieved.market_cap == 3000000000000.0
        assert retrieved.stability_score == 85.5

    def test_get_fundamentals_case_insensitive(self, manager):
        """get_fundamentals should be case insensitive"""
        f = SymbolFundamentals(symbol="AAPL", sector="Technology")
        manager.save_fundamentals(f)

        # Lowercase should work
        retrieved = manager.get_fundamentals("aapl")
        assert retrieved is not None
        assert retrieved.symbol == "AAPL"

    def test_get_fundamentals_not_found(self, manager):
        """get_fundamentals should return None for unknown symbol"""
        result = manager.get_fundamentals("UNKNOWN")
        assert result is None

    def test_save_fundamentals_updates_existing(self, manager):
        """save_fundamentals should update existing entry"""
        # First save
        f1 = SymbolFundamentals(symbol="AAPL", sector="Technology", stability_score=80.0)
        manager.save_fundamentals(f1)

        # Update
        f2 = SymbolFundamentals(symbol="AAPL", sector="Technology", stability_score=90.0)
        manager.save_fundamentals(f2)

        retrieved = manager.get_fundamentals("AAPL")
        assert retrieved.stability_score == 90.0

    def test_save_fundamentals_auto_categorizes_market_cap(self, manager):
        """save_fundamentals should auto-categorize market cap"""
        f = SymbolFundamentals(
            symbol="AAPL",
            market_cap=3000000000000.0
        )

        manager.save_fundamentals(f)
        retrieved = manager.get_fundamentals("AAPL")

        assert retrieved.market_cap_category == "Mega"

    def test_save_fundamentals_calculates_price_to_52w_high(self, manager):
        """save_fundamentals should calculate price_to_52w_high_pct"""
        f = SymbolFundamentals(
            symbol="AAPL",
            current_price=180.0,
            week_52_high=200.0
        )

        manager.save_fundamentals(f)
        retrieved = manager.get_fundamentals("AAPL")

        assert retrieved.price_to_52w_high_pct == -10.0  # (180/200 - 1) * 100

    def test_save_fundamentals_batch(self, manager):
        """save_fundamentals_batch should save multiple entries"""
        fundamentals = [
            SymbolFundamentals(symbol="AAPL", sector="Technology"),
            SymbolFundamentals(symbol="MSFT", sector="Technology"),
            SymbolFundamentals(symbol="JPM", sector="Financial Services"),
        ]

        saved = manager.save_fundamentals_batch(fundamentals)

        assert saved == 3
        assert manager.get_fundamentals("AAPL") is not None
        assert manager.get_fundamentals("MSFT") is not None
        assert manager.get_fundamentals("JPM") is not None

    def test_save_fundamentals_batch_empty_list(self, manager):
        """save_fundamentals_batch with empty list should return 0"""
        saved = manager.save_fundamentals_batch([])
        assert saved == 0

    def test_get_fundamentals_batch(self, manager):
        """get_fundamentals_batch should return multiple entries"""
        # Setup
        for symbol in ["AAPL", "MSFT", "GOOGL"]:
            manager.save_fundamentals(SymbolFundamentals(symbol=symbol, sector="Technology"))

        result = manager.get_fundamentals_batch(["AAPL", "MSFT"])

        assert len(result) == 2
        assert "AAPL" in result
        assert "MSFT" in result

    def test_get_fundamentals_batch_empty_list(self, manager):
        """get_fundamentals_batch with empty list should return empty dict"""
        result = manager.get_fundamentals_batch([])
        assert result == {}

    def test_get_all_fundamentals(self, manager):
        """get_all_fundamentals should return all entries"""
        for symbol in ["AAPL", "MSFT", "GOOGL"]:
            manager.save_fundamentals(SymbolFundamentals(symbol=symbol))

        all_fundamentals = manager.get_all_fundamentals()

        assert len(all_fundamentals) == 3

    def test_get_symbols_by_sector(self, manager):
        """get_symbols_by_sector should filter by sector"""
        manager.save_fundamentals(SymbolFundamentals(symbol="AAPL", sector="Technology"))
        manager.save_fundamentals(SymbolFundamentals(symbol="MSFT", sector="Technology"))
        manager.save_fundamentals(SymbolFundamentals(symbol="JPM", sector="Financial Services"))

        tech = manager.get_symbols_by_sector("Technology")

        assert len(tech) == 2
        symbols = [f.symbol for f in tech]
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_get_symbols_by_market_cap(self, manager):
        """get_symbols_by_market_cap should filter by category"""
        manager.save_fundamentals(SymbolFundamentals(
            symbol="AAPL", market_cap=3000000000000.0, market_cap_category="Mega"
        ))
        manager.save_fundamentals(SymbolFundamentals(
            symbol="SMALL", market_cap=500000000.0, market_cap_category="Small"
        ))

        mega = manager.get_symbols_by_market_cap("Mega")

        assert len(mega) == 1
        assert mega[0].symbol == "AAPL"

    def test_get_stable_symbols(self, manager):
        """get_stable_symbols should filter by stability score"""
        manager.save_fundamentals(SymbolFundamentals(symbol="AAPL", stability_score=85.0))
        manager.save_fundamentals(SymbolFundamentals(symbol="MSFT", stability_score=90.0))
        manager.save_fundamentals(SymbolFundamentals(symbol="TSLA", stability_score=50.0))

        stable = manager.get_stable_symbols(min_stability=70.0)

        assert len(stable) == 2
        symbols = [f.symbol for f in stable]
        assert "AAPL" in symbols
        assert "MSFT" in symbols
        assert "TSLA" not in symbols

    def test_get_symbol_count(self, manager):
        """get_symbol_count should return correct count"""
        assert manager.get_symbol_count() == 0

        for symbol in ["AAPL", "MSFT", "GOOGL"]:
            manager.save_fundamentals(SymbolFundamentals(symbol=symbol))

        assert manager.get_symbol_count() == 3

    def test_get_sectors(self, manager):
        """get_sectors should return unique sectors"""
        manager.save_fundamentals(SymbolFundamentals(symbol="AAPL", sector="Technology"))
        manager.save_fundamentals(SymbolFundamentals(symbol="MSFT", sector="Technology"))
        manager.save_fundamentals(SymbolFundamentals(symbol="JPM", sector="Financial Services"))

        sectors = manager.get_sectors()

        assert len(sectors) == 2
        assert "Technology" in sectors
        assert "Financial Services" in sectors

    def test_get_statistics(self, manager):
        """get_statistics should return comprehensive stats"""
        manager.save_fundamentals(SymbolFundamentals(
            symbol="AAPL", sector="Technology", market_cap=3000000000000.0, stability_score=85.0
        ))
        manager.save_fundamentals(SymbolFundamentals(
            symbol="JPM", sector="Financial Services", market_cap=500000000000.0
        ))

        stats = manager.get_statistics()

        assert stats["total_symbols"] == 2
        assert "Technology" in stats["by_sector"]
        assert stats["with_stability_score"] == 1

    def test_delete_symbol(self, manager):
        """delete_symbol should remove entry"""
        manager.save_fundamentals(SymbolFundamentals(symbol="AAPL"))

        deleted = manager.delete_symbol("AAPL")

        assert deleted is True
        assert manager.get_fundamentals("AAPL") is None

    def test_delete_symbol_not_found(self, manager):
        """delete_symbol should return False for unknown symbol"""
        deleted = manager.delete_symbol("UNKNOWN")
        assert deleted is False

    def test_clear_all(self, manager):
        """clear_all should remove all entries"""
        for symbol in ["AAPL", "MSFT", "GOOGL"]:
            manager.save_fundamentals(SymbolFundamentals(symbol=symbol))

        deleted = manager.clear_all()

        assert deleted == 3
        assert manager.get_symbol_count() == 0


# =============================================================================
# ASYNC WRAPPER TESTS
# =============================================================================

class TestAsyncWrappers:
    """Tests for async wrapper methods"""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def manager(self, temp_db):
        """Create manager with temp database"""
        return SymbolFundamentalsManager(db_path=temp_db)

    @pytest.mark.asyncio
    async def test_get_fundamentals_async(self, manager):
        """get_fundamentals_async should work"""
        manager.save_fundamentals(SymbolFundamentals(symbol="AAPL", sector="Technology"))

        result = await manager.get_fundamentals_async("AAPL")

        assert result is not None
        assert result.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_get_fundamentals_batch_async(self, manager):
        """get_fundamentals_batch_async should work"""
        manager.save_fundamentals(SymbolFundamentals(symbol="AAPL"))
        manager.save_fundamentals(SymbolFundamentals(symbol="MSFT"))

        result = await manager.get_fundamentals_batch_async(["AAPL", "MSFT"])

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_save_fundamentals_async(self, manager):
        """save_fundamentals_async should work"""
        f = SymbolFundamentals(symbol="AAPL", sector="Technology")

        result = await manager.save_fundamentals_async(f)

        assert result is True
        assert manager.get_fundamentals("AAPL") is not None

    @pytest.mark.asyncio
    async def test_save_fundamentals_batch_async(self, manager):
        """save_fundamentals_batch_async should work"""
        fundamentals = [
            SymbolFundamentals(symbol="AAPL"),
            SymbolFundamentals(symbol="MSFT"),
        ]

        result = await manager.save_fundamentals_batch_async(fundamentals)

        assert result == 2

    @pytest.mark.asyncio
    async def test_async_with_custom_executor(self, manager):
        """Async methods should work with custom executor"""
        executor = ThreadPoolExecutor(max_workers=2)

        manager.save_fundamentals(SymbolFundamentals(symbol="AAPL"))

        result = await manager.get_fundamentals_async("AAPL", executor=executor)

        assert result is not None
        executor.shutdown(wait=True)


# =============================================================================
# YFINANCE INTEGRATION TESTS
# =============================================================================

@pytest.mark.skipif(
    not all(
        __import__("importlib").util.find_spec(m) for m in ("yfinance", "pandas")
    ),
    reason="yfinance and/or pandas not installed",
)
class TestYFinanceIntegration:
    """Tests for yfinance integration"""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def manager(self, temp_db):
        """Create manager with temp database"""
        return SymbolFundamentalsManager(db_path=temp_db)

    def test_fetch_from_yfinance_success(self, manager):
        """fetch_from_yfinance should return SymbolFundamentals on success"""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "symbol": "AAPL",
            "regularMarketPrice": 175.0,
            "currentPrice": 175.0,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCap": 3000000000000,
            "beta": 1.25,
            "fiftyTwoWeekHigh": 200.0,
            "fiftyTwoWeekLow": 150.0,
            "averageVolume": 50000000,
            "heldPercentInstitutions": 0.65,
            "dividendYield": 0.005,
            "trailingPE": 28.5,
            "forwardPE": 25.0,
        }
        mock_ticker.recommendations_summary = None

        with patch('yfinance.Ticker', return_value=mock_ticker):
            result = manager.fetch_from_yfinance("AAPL")

        assert result is not None
        assert result.symbol == "AAPL"
        assert result.sector == "Technology"
        assert result.market_cap == 3000000000000
        assert result.market_cap_category == "Mega"

    def test_fetch_from_yfinance_no_data(self, manager):
        """fetch_from_yfinance should return None for no data"""
        mock_ticker = MagicMock()
        mock_ticker.info = {}

        with patch('yfinance.Ticker', return_value=mock_ticker):
            result = manager.fetch_from_yfinance("INVALID")

        assert result is None

    def test_fetch_from_yfinance_with_analyst_ratings(self, manager):
        """fetch_from_yfinance should parse analyst ratings"""
        import pandas as pd

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 175.0,
            "currentPrice": 175.0,
            "targetMeanPrice": 200.0,
        }

        # Mock recommendations_summary DataFrame
        mock_rec_summary = pd.DataFrame({
            "strongBuy": [10],
            "buy": [15],
            "hold": [5],
            "sell": [2],
            "strongSell": [1]
        })
        mock_ticker.recommendations_summary = mock_rec_summary

        with patch('yfinance.Ticker', return_value=mock_ticker):
            result = manager.fetch_from_yfinance("AAPL")

        assert result is not None
        # Buy includes strongBuy + buy (counting method may vary)
        assert result.analyst_buy >= 25
        assert result.analyst_rating == "BULLISH"

    def test_update_from_yfinance(self, manager):
        """update_from_yfinance should fetch and save"""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 175.0,
            "sector": "Technology"
        }
        mock_ticker.recommendations_summary = None

        with patch('yfinance.Ticker', return_value=mock_ticker):
            result = manager.update_from_yfinance("AAPL")

        assert result is True
        assert manager.get_fundamentals("AAPL") is not None


# =============================================================================
# STABILITY AND EARNINGS TESTS
# =============================================================================

class TestStabilityAndEarnings:
    """Tests for stability and earnings updates"""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def manager(self, temp_db):
        """Create manager with temp database"""
        return SymbolFundamentalsManager(db_path=temp_db)

    def test_update_stability_from_outcomes_no_db(self, manager, temp_db):
        """update_stability_from_outcomes should handle missing outcomes.db"""
        result = manager.update_stability_from_outcomes("AAPL")
        assert result is False

    def test_update_earnings_beat_rate(self, manager):
        """update_earnings_beat_rate should calculate from earnings_history"""
        # First, we need to create the earnings_history table
        with manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS earnings_history (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    earnings_date DATE NOT NULL,
                    eps_actual REAL,
                    eps_estimate REAL
                )
            """)
            # Insert test data: 3 beats out of 4
            cursor.execute("INSERT INTO earnings_history (symbol, earnings_date, eps_actual, eps_estimate) VALUES ('AAPL', '2024-01-01', 1.50, 1.40)")
            cursor.execute("INSERT INTO earnings_history (symbol, earnings_date, eps_actual, eps_estimate) VALUES ('AAPL', '2024-04-01', 1.60, 1.50)")
            cursor.execute("INSERT INTO earnings_history (symbol, earnings_date, eps_actual, eps_estimate) VALUES ('AAPL', '2024-07-01', 1.40, 1.45)")  # Miss
            cursor.execute("INSERT INTO earnings_history (symbol, earnings_date, eps_actual, eps_estimate) VALUES ('AAPL', '2024-10-01', 1.70, 1.55)")
            conn.commit()

        result = manager.update_earnings_beat_rate("AAPL")

        assert result is True
        fundamentals = manager.get_fundamentals("AAPL")
        assert fundamentals is not None
        assert fundamentals.earnings_beat_rate == 75.0  # 3/4 = 75%

    def test_update_earnings_beat_rate_no_data(self, manager):
        """update_earnings_beat_rate should return False for no data"""
        # Create empty earnings_history table
        with manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS earnings_history (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    earnings_date DATE NOT NULL,
                    eps_actual REAL,
                    eps_estimate REAL
                )
            """)
            conn.commit()

        result = manager.update_earnings_beat_rate("UNKNOWN")

        assert result is False


# =============================================================================
# SINGLETON TESTS
# =============================================================================

class TestSingleton:
    """Tests for singleton pattern"""

    def test_get_fundamentals_manager_returns_same_instance(self):
        """get_fundamentals_manager should return same instance"""
        reset_fundamentals_manager()

        manager1 = get_fundamentals_manager()
        manager2 = get_fundamentals_manager()

        assert manager1 is manager2

    def test_reset_fundamentals_manager(self):
        """reset_fundamentals_manager should clear singleton"""
        manager1 = get_fundamentals_manager()
        reset_fundamentals_manager()
        manager2 = get_fundamentals_manager()

        # After reset, should be different instance
        assert manager1 is not manager2


# =============================================================================
# THREAD SAFETY TESTS
# =============================================================================

class TestThreadSafety:
    """Tests for thread safety"""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        if db_path.exists():
            db_path.unlink()

    def test_concurrent_writes(self, temp_db):
        """Concurrent writes should not corrupt data"""
        manager = SymbolFundamentalsManager(db_path=temp_db)
        errors = []

        def write_symbol(symbol):
            try:
                for _ in range(10):
                    f = SymbolFundamentals(symbol=symbol, sector="Technology")
                    manager.save_fundamentals(f)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_symbol, args=(f"SYM{i}",))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert manager.get_symbol_count() == 5

    def test_concurrent_reads(self, temp_db):
        """Concurrent reads should work correctly"""
        manager = SymbolFundamentalsManager(db_path=temp_db)

        # Setup data
        for i in range(10):
            manager.save_fundamentals(SymbolFundamentals(symbol=f"SYM{i}"))

        results = []

        def read_symbols():
            for i in range(10):
                f = manager.get_fundamentals(f"SYM{i}")
                if f:
                    results.append(f.symbol)

        threads = [
            threading.Thread(target=read_symbols)
            for _ in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 50  # 5 threads * 10 symbols each


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
