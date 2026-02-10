# OptionPlay - Earnings Cache Tests
# ===================================

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS
from src.cache.earnings_cache import (
    EarningsInfo,
    EarningsSource,
    EarningsCache
)


class TestEarningsInfo:
    """Tests für EarningsInfo Dataclass"""
    
    def test_is_safe_sufficient_days(self):
        """is_safe sollte True sein bei genug Tagen"""
        info = EarningsInfo(
            symbol="AAPL",
            earnings_date="2025-04-25",
            days_to_earnings=90,
            source=EarningsSource.YFINANCE,
            updated_at="2025-01-24T10:00:00",
            confirmed=False
        )
        
        assert info.is_safe(min_days=ENTRY_EARNINGS_MIN_DAYS) == True
        assert info.is_safe(min_days=90) == True
        
    def test_is_safe_insufficient_days(self):
        """is_safe sollte False sein bei zu wenig Tagen"""
        info = EarningsInfo(
            symbol="AAPL",
            earnings_date="2025-02-15",
            days_to_earnings=22,
            source=EarningsSource.YFINANCE,
            updated_at="2025-01-24T10:00:00",
            confirmed=False
        )
        
        assert info.is_safe(min_days=ENTRY_EARNINGS_MIN_DAYS) == False
        assert info.is_safe(min_days=30) == False
        assert info.is_safe(min_days=20) == True
        
    def test_is_safe_none_days(self):
        """is_safe sollte True sein wenn days unbekannt"""
        info = EarningsInfo(
            symbol="AAPL",
            earnings_date=None,
            days_to_earnings=None,
            source=EarningsSource.UNKNOWN,
            updated_at="2025-01-24T10:00:00",
            confirmed=False
        )

        # Unbekannt mit unknown_is_safe=False (default) = False
        assert info.is_safe(min_days=ENTRY_EARNINGS_MIN_DAYS) == False
        # Unbekannt mit unknown_is_safe=True = True (permissiv)
        assert info.is_safe(min_days=60, unknown_is_safe=True) == True

    def test_is_safe_past_earnings(self):
        """is_safe sollte True sein bei vergangenen Earnings (negative days)"""
        info = EarningsInfo(
            symbol="QCOM",
            earnings_date="2025-01-01",
            days_to_earnings=-30,
            source=EarningsSource.YFINANCE,
            updated_at="2025-01-24T10:00:00",
            confirmed=False
        )

        # Vergangene Earnings = safe (nächste Earnings ~90d entfernt)
        assert info.is_safe(min_days=ENTRY_EARNINGS_MIN_DAYS) == True
        assert info.is_safe(min_days=90) == True


class TestEarningsSourceEnum:
    """Tests für EarningsSource Enum"""
    
    def test_earnings_source_values(self):
        """EarningsSource sollte alle Werte haben"""
        assert EarningsSource.YFINANCE.value == "yfinance"
        assert EarningsSource.TRADIER.value == "tradier"
        assert EarningsSource.MANUAL.value == "manual"
        assert EarningsSource.UNKNOWN.value == "unknown"


class TestCalculateDaysToEarnings:
    """Tests für _calculate_days_to_earnings"""

    @pytest.fixture
    def cache(self, tmp_path):
        cache_file = tmp_path / "test_calc.json"
        return EarningsCache(cache_file=cache_file)

    def test_future_date_returns_positive(self, cache):
        future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        result = cache._calculate_days_to_earnings(future)
        assert result is not None
        assert result >= 29  # allow for day boundary

    def test_past_date_returns_negative(self, cache):
        past = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        result = cache._calculate_days_to_earnings(past)
        assert result is not None
        assert result <= -10

    def test_none_returns_none(self, cache):
        assert cache._calculate_days_to_earnings(None) is None

    def test_invalid_date_returns_none(self, cache):
        assert cache._calculate_days_to_earnings("not-a-date") is None


class TestEarningsCacheBasics:
    """Grundlegende Cache-Tests"""

    @pytest.fixture
    def temp_cache(self, tmp_path):
        """Temporärer Cache"""
        cache_file = tmp_path / "test_cache.json"
        return EarningsCache(cache_file=cache_file, max_age_hours=24)
    
    def test_set_and_get(self, temp_cache):
        """set und get sollten funktionieren"""
        temp_cache.set(
            symbol="AAPL",
            earnings_date="2025-04-25",
            days_to_earnings=90,
            source=EarningsSource.YFINANCE
        )
        
        result = temp_cache.get("AAPL")
        
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.earnings_date == "2025-04-25"
        
    def test_get_nonexistent(self, temp_cache):
        """get sollte None für nicht-existierendes Symbol zurückgeben"""
        result = temp_cache.get("NONEXISTENT")
        assert result is None
        
    def test_case_insensitive(self, temp_cache):
        """Cache sollte case-insensitive sein"""
        temp_cache.set("aapl", "2025-04-25", 90, EarningsSource.YFINANCE)
        
        result = temp_cache.get("AAPL")
        assert result is not None
        
    def test_invalidate(self, temp_cache):
        """invalidate sollte Symbol entfernen"""
        temp_cache.set("AAPL", "2025-04-25", 90, EarningsSource.YFINANCE)
        temp_cache.invalidate("AAPL")
        
        assert temp_cache.get("AAPL") is None
        
    def test_invalidate_all(self, temp_cache):
        """invalidate_all sollte Cache leeren"""
        temp_cache.set("AAPL", "2025-04-25", 90, EarningsSource.YFINANCE)
        temp_cache.set("MSFT", "2025-04-20", 85, EarningsSource.YFINANCE)
        
        temp_cache.invalidate_all()
        
        assert len(temp_cache) == 0


class TestEarningsCacheBulkOps:
    """Tests für Bulk-Operationen"""
    
    @pytest.fixture
    def temp_cache(self, tmp_path):
        cache_file = tmp_path / "test_cache.json"
        return EarningsCache(cache_file=cache_file)
    
    def test_get_many(self, temp_cache):
        """get_many sollte Dict zurückgeben"""
        temp_cache.set("AAPL", "2025-04-25", 90, EarningsSource.YFINANCE)
        temp_cache.set("MSFT", "2025-04-20", 85, EarningsSource.YFINANCE)
        
        results = temp_cache.get_many(["AAPL", "MSFT", "GOOGL"])
        
        assert results["AAPL"] is not None
        assert results["MSFT"] is not None
        assert results["GOOGL"] is None
        
    def test_get_missing_symbols(self, temp_cache):
        """get_missing_symbols sollte fehlende identifizieren"""
        temp_cache.set("AAPL", "2025-04-25", 90, EarningsSource.YFINANCE)
        
        missing = temp_cache.get_missing_symbols(["AAPL", "MSFT"])
        
        assert "AAPL" not in missing
        assert "MSFT" in missing


class TestEarningsCacheStats:
    """Tests für Cache-Statistiken"""
    
    @pytest.fixture
    def temp_cache(self, tmp_path):
        cache_file = tmp_path / "test_cache.json"
        return EarningsCache(cache_file=cache_file)
    
    def test_len(self, temp_cache):
        """len() sollte Anzahl zurückgeben"""
        assert len(temp_cache) == 0
        
        temp_cache.set("AAPL", "2025-04-25", 90, EarningsSource.YFINANCE)
        assert len(temp_cache) == 1
        
    def test_contains(self, temp_cache):
        """in-Operator sollte funktionieren"""
        temp_cache.set("AAPL", "2025-04-25", 90, EarningsSource.YFINANCE)
        
        assert "AAPL" in temp_cache
        assert "MSFT" not in temp_cache


class TestEarningsCachePersistence:
    """Tests für Persistenz"""
    
    def test_persistence(self, tmp_path):
        """Cache sollte persistiert werden"""
        cache_file = tmp_path / "test_persistence.json"
        
        # Erste Instanz
        cache1 = EarningsCache(cache_file=cache_file)
        cache1.set("AAPL", "2025-04-25", 90, EarningsSource.YFINANCE)
        
        # Zweite Instanz
        cache2 = EarningsCache(cache_file=cache_file)
        result = cache2.get("AAPL")
        
        assert result is not None
        assert result.symbol == "AAPL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
