# Tests for Historical Cache (utils version)
# ==========================================
"""
Tests for HistoricalDataCache class in utils/historical_cache.py.
"""

import pytest
import time
import threading
from datetime import datetime, timedelta

from src.utils.historical_cache import (
    HistoricalDataCache,
    CacheEntry,
    get_historical_cache,
    reset_historical_cache,
)


# =============================================================================
# CACHE ENTRY TESTS
# =============================================================================

class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_create_entry(self):
        """Test creating cache entry."""
        now = datetime.now()
        entry = CacheEntry(
            data={"prices": [100, 101, 102]},
            created_at=now,
            expires_at=now + timedelta(seconds=300),
            days=30
        )

        assert entry.data == {"prices": [100, 101, 102]}
        assert entry.days == 30
        assert entry.access_count == 0

    def test_is_expired_false(self):
        """Test is_expired returns False for valid entry."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300),
            days=30
        )

        assert entry.is_expired() is False

    def test_is_expired_true(self):
        """Test is_expired returns True for expired entry."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now - timedelta(seconds=400),
            expires_at=now - timedelta(seconds=100),
            days=30
        )

        assert entry.is_expired() is True

    def test_touch_increments_access_count(self):
        """Test touch increments access count."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300),
            days=30
        )

        assert entry.access_count == 0
        entry.touch()
        assert entry.access_count == 1
        entry.touch()
        assert entry.access_count == 2

    def test_touch_updates_last_accessed(self):
        """Test touch updates last_accessed time."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300),
            days=30
        )

        old_accessed = entry.last_accessed
        time.sleep(0.01)  # Small delay
        entry.touch()

        assert entry.last_accessed >= old_accessed


# =============================================================================
# HISTORICAL DATA CACHE INIT TESTS
# =============================================================================

class TestHistoricalDataCacheInit:
    """Tests for HistoricalDataCache initialization."""

    def test_init_default_values(self):
        """Test initialization with default values."""
        cache = HistoricalDataCache()

        assert cache._ttl_seconds == 300
        assert cache._max_entries == 500

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        cache = HistoricalDataCache(ttl_seconds=60, max_entries=100)

        assert cache._ttl_seconds == 60
        assert cache._max_entries == 100

    def test_init_empty_cache(self):
        """Test initialization creates empty cache."""
        cache = HistoricalDataCache()

        assert len(cache._cache) == 0
        assert cache._hits == 0
        assert cache._misses == 0


# =============================================================================
# SET METHOD TESTS
# =============================================================================

class TestSetMethod:
    """Tests for set method."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test."""
        return HistoricalDataCache(ttl_seconds=300, max_entries=100)

    def test_set_stores_data(self, cache):
        """Test set stores data in cache."""
        data = {"prices": [100, 101, 102], "volumes": [1000, 1100, 1200]}
        cache.set("AAPL", data, days=30)

        assert cache.has("AAPL", 30)

    def test_set_with_custom_ttl(self, cache):
        """Test set with custom TTL."""
        cache.set("AAPL", "test", days=30, ttl_seconds=60)

        assert cache.has("AAPL", 30)

    def test_set_uppercase_symbol(self, cache):
        """Test set normalizes symbol to uppercase."""
        cache.set("aapl", "test", days=30)

        assert cache.has("AAPL", 30)

    def test_set_triggers_cleanup_when_full(self):
        """Test set triggers cleanup when cache is full."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=5)

        # Fill cache
        for i in range(5):
            cache.set(f"SYM{i}", "data", days=30)

        # Add one more - should trigger cleanup
        cache.set("NEW", "data", days=30)

        assert len(cache._cache) <= 5


# =============================================================================
# GET METHOD TESTS
# =============================================================================

class TestGetMethod:
    """Tests for get method."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test."""
        return HistoricalDataCache(ttl_seconds=300, max_entries=100)

    def test_get_returns_cached_data(self, cache):
        """Test get returns cached data."""
        data = {"prices": [100, 101, 102]}
        cache.set("AAPL", data, days=30)

        result = cache.get("AAPL", days=30)

        assert result == data

    def test_get_returns_none_for_missing(self, cache):
        """Test get returns None for missing entry."""
        result = cache.get("AAPL", days=30)

        assert result is None

    def test_get_returns_none_for_expired(self):
        """Test get returns None for expired entry."""
        cache = HistoricalDataCache(ttl_seconds=1, max_entries=100)
        cache.set("AAPL", "test", days=30)

        time.sleep(1.5)  # Wait for expiration

        result = cache.get("AAPL", days=30)
        assert result is None

    def test_get_increments_hits(self, cache):
        """Test get increments hits counter."""
        cache.set("AAPL", "test", days=30)
        cache.get("AAPL", days=30)
        cache.get("AAPL", days=30)

        assert cache._hits == 2

    def test_get_increments_misses(self, cache):
        """Test get increments misses counter."""
        cache.get("AAPL", days=30)
        cache.get("MSFT", days=30)

        assert cache._misses == 2

    def test_get_with_min_days_finds_larger_cache(self, cache):
        """Test get with min_days finds larger cached entry."""
        cache.set("AAPL", "large_data", days=260)

        result = cache.get("AAPL", days=60, min_days=60)

        assert result == "large_data"


# =============================================================================
# HAS METHOD TESTS
# =============================================================================

class TestHasMethod:
    """Tests for has method."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test."""
        return HistoricalDataCache(ttl_seconds=300, max_entries=100)

    def test_has_returns_true_for_cached(self, cache):
        """Test has returns True for cached entry."""
        cache.set("AAPL", "test", days=30)

        assert cache.has("AAPL", 30) is True

    def test_has_returns_false_for_missing(self, cache):
        """Test has returns False for missing entry."""
        assert cache.has("AAPL", 30) is False

    def test_has_returns_false_for_expired(self):
        """Test has returns False for expired entry."""
        cache = HistoricalDataCache(ttl_seconds=1, max_entries=100)
        cache.set("AAPL", "test", days=30)

        time.sleep(1.5)

        assert cache.has("AAPL", 30) is False


# =============================================================================
# INVALIDATE METHOD TESTS
# =============================================================================

class TestInvalidateMethod:
    """Tests for invalidate method."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test."""
        return HistoricalDataCache(ttl_seconds=300, max_entries=100)

    def test_invalidate_specific_days(self, cache):
        """Test invalidate removes specific days entry."""
        cache.set("AAPL", "data1", days=30)
        cache.set("AAPL", "data2", days=60)

        count = cache.invalidate("AAPL", days=30)

        assert count == 1
        assert cache.has("AAPL", 30) is False
        assert cache.has("AAPL", 60) is True

    def test_invalidate_all_for_symbol(self, cache):
        """Test invalidate removes all entries for symbol."""
        cache.set("AAPL", "data1", days=30)
        cache.set("AAPL", "data2", days=60)
        cache.set("MSFT", "data3", days=30)

        count = cache.invalidate("AAPL")

        assert count == 2
        assert cache.has("AAPL", 30) is False
        assert cache.has("AAPL", 60) is False
        assert cache.has("MSFT", 30) is True

    def test_invalidate_returns_zero_for_missing(self, cache):
        """Test invalidate returns 0 for missing symbol."""
        count = cache.invalidate("AAPL", days=30)

        assert count == 0


# =============================================================================
# CLEAR METHOD TESTS
# =============================================================================

class TestClearMethod:
    """Tests for clear method."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test."""
        return HistoricalDataCache(ttl_seconds=300, max_entries=100)

    def test_clear_removes_all_entries(self, cache):
        """Test clear removes all entries."""
        cache.set("AAPL", "data1", days=30)
        cache.set("MSFT", "data2", days=30)
        cache.set("GOOGL", "data3", days=30)

        count = cache.clear()

        assert count == 3
        assert len(cache._cache) == 0


# =============================================================================
# STATS METHOD TESTS
# =============================================================================

class TestStatsMethod:
    """Tests for stats method."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test."""
        return HistoricalDataCache(ttl_seconds=300, max_entries=100)

    def test_stats_returns_dict(self, cache):
        """Test stats returns dictionary."""
        stats = cache.stats()

        assert isinstance(stats, dict)

    def test_stats_has_expected_keys(self, cache):
        """Test stats has expected keys."""
        stats = cache.stats()

        assert "entries" in stats
        assert "max_entries" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate_percent" in stats
        assert "evictions" in stats
        assert "ttl_seconds" in stats

    def test_stats_tracks_hit_rate(self, cache):
        """Test stats calculates hit rate."""
        cache.set("AAPL", "test", days=30)
        cache.get("AAPL", days=30)  # Hit
        cache.get("MSFT", days=30)  # Miss

        stats = cache.stats()
        assert stats["hit_rate_percent"] == 50.0


# =============================================================================
# GET CACHED SYMBOLS TESTS
# =============================================================================

class TestGetCachedSymbols:
    """Tests for get_cached_symbols method."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test."""
        return HistoricalDataCache(ttl_seconds=300, max_entries=100)

    def test_returns_list(self, cache):
        """Test returns list."""
        result = cache.get_cached_symbols()
        assert isinstance(result, list)

    def test_returns_unique_symbols(self, cache):
        """Test returns unique symbols."""
        cache.set("AAPL", "data1", days=30)
        cache.set("AAPL", "data2", days=60)
        cache.set("MSFT", "data3", days=30)

        result = cache.get_cached_symbols()
        assert sorted(result) == ["AAPL", "MSFT"]


# =============================================================================
# LRU EVICTION TESTS
# =============================================================================

class TestLRUEviction:
    """Tests for LRU eviction."""

    def test_evicts_least_recently_used(self):
        """Test LRU eviction removes oldest accessed entries."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=3)

        cache.set("AAPL", "data1", days=30)
        time.sleep(0.01)
        cache.set("MSFT", "data2", days=30)
        time.sleep(0.01)
        cache.set("GOOGL", "data3", days=30)

        # Access AAPL to make it recent
        cache.get("AAPL", days=30)

        # Add new entry - should evict MSFT (oldest accessed)
        cache.set("TSLA", "data4", days=30)

        # Check eviction happened
        stats = cache.stats()
        assert stats["entries"] <= 3


# =============================================================================
# THREAD SAFETY TESTS
# =============================================================================

class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_access(self):
        """Test concurrent access to cache."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=1000)
        errors = []

        def writer():
            try:
                for i in range(100):
                    cache.set(f"SYM{i}", f"data{i}", days=30)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    cache.get(f"SYM{i}", days=30)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =============================================================================
# SINGLETON TESTS
# =============================================================================

class TestSingleton:
    """Tests for singleton pattern."""

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_historical_cache()

    def test_get_historical_cache_returns_instance(self):
        """Test get_historical_cache returns instance."""
        cache = get_historical_cache()
        assert isinstance(cache, HistoricalDataCache)

    def test_get_historical_cache_returns_same_instance(self):
        """Test get_historical_cache returns same instance."""
        cache1 = get_historical_cache()
        cache2 = get_historical_cache()
        assert cache1 is cache2

    def test_reset_creates_new_instance(self):
        """Test reset_historical_cache creates new instance."""
        cache1 = get_historical_cache()
        cache1.set("AAPL", "test", days=30)

        reset_historical_cache()
        cache2 = get_historical_cache()

        assert cache1 is not cache2
        assert not cache2.has("AAPL", 30)


# =============================================================================
# MAKE KEY TESTS
# =============================================================================

class TestMakeKey:
    """Tests for _make_key method."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache for each test."""
        return HistoricalDataCache()

    def test_creates_key_format(self, cache):
        """Test key format is SYMBOL:DAYS."""
        key = cache._make_key("AAPL", 30)
        assert key == "AAPL:30"

    def test_uppercase_symbol(self, cache):
        """Test symbol is uppercased."""
        key = cache._make_key("aapl", 30)
        assert key == "AAPL:30"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
