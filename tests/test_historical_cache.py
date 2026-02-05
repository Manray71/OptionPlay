# Tests for Historical Cache (src/utils/historical_cache.py)
# ==========================================================
"""
Comprehensive unit tests for HistoricalDataCache class.

Tests cover:
1. HistoricalCache initialization
2. get/set methods
3. Cache expiration
4. File-based persistence (N/A - this is an in-memory cache)
5. Thread safety

Note: This cache implementation is purely in-memory and does not
have file-based persistence. Tests verify in-memory behavior only.
"""

import pytest
import time
import threading
import concurrent.futures
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.utils.historical_cache import (
    HistoricalDataCache,
    CacheEntry,
    get_historical_cache,
    reset_historical_cache,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before and after each test."""
    reset_historical_cache()
    yield
    reset_historical_cache()


@pytest.fixture
def cache():
    """Create fresh cache for each test."""
    return HistoricalDataCache(ttl_seconds=300, max_entries=100)


@pytest.fixture
def small_cache():
    """Create cache with small max_entries for eviction tests."""
    return HistoricalDataCache(ttl_seconds=300, max_entries=5)


@pytest.fixture
def short_ttl_cache():
    """Create cache with short TTL for expiration tests."""
    return HistoricalDataCache(ttl_seconds=1, max_entries=100)


@pytest.fixture
def sample_data():
    """Sample historical data for testing."""
    return {
        "prices": [100.0 + i * 0.5 for i in range(260)],
        "volumes": [1000000 + i * 1000 for i in range(260)],
        "highs": [101.0 + i * 0.5 for i in range(260)],
        "lows": [99.0 + i * 0.5 for i in range(260)],
    }


# =============================================================================
# CACHE ENTRY DATACLASS TESTS
# =============================================================================

class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_create_entry_with_required_fields(self):
        """Test creating cache entry with required fields."""
        now = datetime.now()
        entry = CacheEntry(
            data={"prices": [100, 101, 102]},
            created_at=now,
            expires_at=now + timedelta(seconds=300),
            days=30
        )

        assert entry.data == {"prices": [100, 101, 102]}
        assert entry.days == 30
        assert entry.created_at == now
        assert entry.access_count == 0

    def test_entry_default_values(self):
        """Test entry has correct default values."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300),
            days=30
        )

        assert entry.access_count == 0
        assert entry.last_accessed is not None

    def test_is_expired_returns_false_for_valid_entry(self):
        """Test is_expired returns False when entry has not expired."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300),
            days=30
        )

        assert entry.is_expired() is False

    def test_is_expired_returns_true_for_expired_entry(self):
        """Test is_expired returns True when entry has expired."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now - timedelta(seconds=400),
            expires_at=now - timedelta(seconds=100),
            days=30
        )

        assert entry.is_expired() is True

    def test_is_expired_boundary_case(self):
        """Test is_expired at exact expiration time."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now - timedelta(seconds=1),
            expires_at=now - timedelta(microseconds=1),
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
        entry.touch()
        assert entry.access_count == 3

    def test_touch_updates_last_accessed(self):
        """Test touch updates last_accessed timestamp."""
        now = datetime.now()
        entry = CacheEntry(
            data="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300),
            days=30
        )

        old_accessed = entry.last_accessed
        time.sleep(0.02)  # Small delay to ensure time difference
        entry.touch()

        assert entry.last_accessed > old_accessed

    def test_entry_stores_any_data_type(self):
        """Test entry can store any data type."""
        now = datetime.now()

        # Test with list
        entry1 = CacheEntry(data=[1, 2, 3], created_at=now, expires_at=now + timedelta(seconds=300), days=30)
        assert entry1.data == [1, 2, 3]

        # Test with dict
        entry2 = CacheEntry(data={"key": "value"}, created_at=now, expires_at=now + timedelta(seconds=300), days=30)
        assert entry2.data == {"key": "value"}

        # Test with tuple
        entry3 = CacheEntry(data=(1, 2, 3), created_at=now, expires_at=now + timedelta(seconds=300), days=30)
        assert entry3.data == (1, 2, 3)

        # Test with None
        entry4 = CacheEntry(data=None, created_at=now, expires_at=now + timedelta(seconds=300), days=30)
        assert entry4.data is None


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestHistoricalDataCacheInit:
    """Tests for HistoricalDataCache initialization."""

    def test_init_with_default_values(self):
        """Test initialization with default values."""
        cache = HistoricalDataCache()

        assert cache._ttl_seconds == HistoricalDataCache.DEFAULT_TTL_SECONDS
        assert cache._max_entries == HistoricalDataCache.DEFAULT_MAX_ENTRIES
        assert cache._ttl_seconds == 300
        assert cache._max_entries == 500

    def test_init_with_custom_ttl(self):
        """Test initialization with custom TTL."""
        cache = HistoricalDataCache(ttl_seconds=60)

        assert cache._ttl_seconds == 60
        assert cache._max_entries == 500

    def test_init_with_custom_max_entries(self):
        """Test initialization with custom max_entries."""
        cache = HistoricalDataCache(max_entries=100)

        assert cache._ttl_seconds == 300
        assert cache._max_entries == 100

    def test_init_with_all_custom_values(self):
        """Test initialization with all custom values."""
        cache = HistoricalDataCache(ttl_seconds=60, max_entries=100)

        assert cache._ttl_seconds == 60
        assert cache._max_entries == 100

    def test_init_creates_empty_cache(self):
        """Test initialization creates empty internal cache."""
        cache = HistoricalDataCache()

        assert len(cache._cache) == 0

    def test_init_zeroes_statistics(self):
        """Test initialization zeroes all statistics."""
        cache = HistoricalDataCache()

        assert cache._hits == 0
        assert cache._misses == 0
        assert cache._evictions == 0

    def test_init_creates_lock(self):
        """Test initialization creates threading lock."""
        cache = HistoricalDataCache()

        assert hasattr(cache, "_lock")
        assert isinstance(cache._lock, type(threading.RLock()))

    def test_class_constants(self):
        """Test class constants are defined correctly."""
        assert HistoricalDataCache.DEFAULT_TTL_SECONDS == 300
        assert HistoricalDataCache.DEFAULT_MAX_ENTRIES == 500


# =============================================================================
# SET METHOD TESTS
# =============================================================================

class TestSetMethod:
    """Tests for set method."""

    def test_set_stores_data(self, cache, sample_data):
        """Test set stores data in cache."""
        cache.set("AAPL", sample_data, days=260)

        assert cache.has("AAPL", 260)

    def test_set_returns_none(self, cache):
        """Test set returns None (no return value)."""
        result = cache.set("AAPL", "test", days=30)

        assert result is None

    def test_set_creates_correct_entry(self, cache):
        """Test set creates entry with correct attributes."""
        cache.set("AAPL", "test_data", days=60)

        key = "AAPL:60"
        entry = cache._cache[key]

        assert entry.data == "test_data"
        assert entry.days == 60
        assert entry.access_count == 0

    def test_set_with_custom_ttl(self, cache):
        """Test set with custom TTL overrides default."""
        cache.set("AAPL", "test", days=30, ttl_seconds=600)

        key = "AAPL:30"
        entry = cache._cache[key]

        expected_expires = entry.created_at + timedelta(seconds=600)
        assert abs((entry.expires_at - expected_expires).total_seconds()) < 1

    def test_set_normalizes_symbol_to_uppercase(self, cache):
        """Test set normalizes symbol to uppercase."""
        cache.set("aapl", "test", days=30)

        assert cache.has("AAPL", 30)
        assert "AAPL:30" in cache._cache

    def test_set_overwrites_existing_entry(self, cache):
        """Test set overwrites existing entry for same key."""
        cache.set("AAPL", "old_data", days=30)
        cache.set("AAPL", "new_data", days=30)

        result = cache.get("AAPL", days=30)
        assert result == "new_data"

    def test_set_different_days_creates_different_entries(self, cache):
        """Test set with different days creates separate entries."""
        cache.set("AAPL", "data_30", days=30)
        cache.set("AAPL", "data_60", days=60)

        assert cache.get("AAPL", days=30) == "data_30"
        assert cache.get("AAPL", days=60) == "data_60"

    def test_set_triggers_cleanup_when_full(self, small_cache):
        """Test set triggers cleanup when cache reaches max_entries."""
        # Fill cache
        for i in range(5):
            small_cache.set(f"SYM{i}", f"data{i}", days=30)

        assert len(small_cache._cache) == 5

        # Add one more - should trigger cleanup
        small_cache.set("NEW", "new_data", days=30)

        assert len(small_cache._cache) <= 5

    def test_set_stores_complex_data_structures(self, cache):
        """Test set can store complex nested data."""
        complex_data = {
            "prices": [100.0, 101.0, 102.0],
            "metadata": {
                "symbol": "AAPL",
                "dates": ["2024-01-01", "2024-01-02"],
            },
            "nested": [[1, 2], [3, 4]],
        }

        cache.set("AAPL", complex_data, days=30)
        result = cache.get("AAPL", days=30)

        assert result == complex_data


# =============================================================================
# GET METHOD TESTS
# =============================================================================

class TestGetMethod:
    """Tests for get method."""

    def test_get_returns_cached_data(self, cache, sample_data):
        """Test get returns cached data."""
        cache.set("AAPL", sample_data, days=260)

        result = cache.get("AAPL", days=260)

        assert result == sample_data

    def test_get_returns_none_for_missing_key(self, cache):
        """Test get returns None for non-existent key."""
        result = cache.get("AAPL", days=30)

        assert result is None

    def test_get_returns_none_for_missing_symbol(self, cache):
        """Test get returns None for symbol not in cache."""
        cache.set("AAPL", "data", days=30)

        result = cache.get("MSFT", days=30)

        assert result is None

    def test_get_returns_none_for_missing_days(self, cache):
        """Test get returns None for days not in cache."""
        cache.set("AAPL", "data", days=30)

        result = cache.get("AAPL", days=60)

        assert result is None

    def test_get_returns_none_for_expired_entry(self, short_ttl_cache):
        """Test get returns None for expired entry."""
        short_ttl_cache.set("AAPL", "test", days=30)

        time.sleep(1.5)  # Wait for expiration

        result = short_ttl_cache.get("AAPL", days=30)
        assert result is None

    def test_get_normalizes_symbol_to_uppercase(self, cache):
        """Test get normalizes symbol to uppercase."""
        cache.set("AAPL", "test", days=30)

        result = cache.get("aapl", days=30)

        assert result == "test"

    def test_get_increments_hits_counter(self, cache):
        """Test get increments hits counter on cache hit."""
        cache.set("AAPL", "test", days=30)

        cache.get("AAPL", days=30)
        cache.get("AAPL", days=30)
        cache.get("AAPL", days=30)

        assert cache._hits == 3

    def test_get_increments_misses_counter(self, cache):
        """Test get increments misses counter on cache miss."""
        cache.get("AAPL", days=30)
        cache.get("MSFT", days=30)
        cache.get("GOOGL", days=30)

        assert cache._misses == 3

    def test_get_touches_entry_on_hit(self, cache):
        """Test get calls touch() on cache hit."""
        cache.set("AAPL", "test", days=30)
        key = "AAPL:30"

        initial_count = cache._cache[key].access_count
        cache.get("AAPL", days=30)

        assert cache._cache[key].access_count == initial_count + 1

    def test_get_with_min_days_finds_larger_cache(self, cache):
        """Test get with min_days finds larger cached entry."""
        cache.set("AAPL", "large_data_260", days=260)

        result = cache.get("AAPL", days=60, min_days=60)

        assert result == "large_data_260"

    def test_get_with_min_days_searches_common_days(self, cache):
        """Test get with min_days searches common day values."""
        # Cache 365 days
        cache.set("AAPL", "data_365", days=365)

        # Request 90 days with min_days - should find 365
        result = cache.get("AAPL", days=90, min_days=90)

        assert result == "data_365"

    def test_get_with_min_days_returns_none_if_no_match(self, cache):
        """Test get with min_days returns None if no suitable cache."""
        cache.set("AAPL", "data_30", days=30)

        # Request 60 days with min_days of 60 - 30 day cache is too small
        result = cache.get("AAPL", days=60, min_days=60)

        # Should still return data_30 if min_days search finds it
        # The implementation searches [260, 365, 180, 120, 90, 60, 30]
        # 30 < 60 so it won't match
        assert result is None

    def test_get_direct_match_preferred_over_min_days(self, cache):
        """Test direct match is preferred over min_days search."""
        cache.set("AAPL", "exact_60", days=60)
        cache.set("AAPL", "large_260", days=260)

        result = cache.get("AAPL", days=60)

        assert result == "exact_60"


# =============================================================================
# HAS METHOD TESTS
# =============================================================================

class TestHasMethod:
    """Tests for has method."""

    def test_has_returns_true_for_cached_entry(self, cache):
        """Test has returns True for cached entry."""
        cache.set("AAPL", "test", days=30)

        assert cache.has("AAPL", 30) is True

    def test_has_returns_false_for_missing_entry(self, cache):
        """Test has returns False for missing entry."""
        assert cache.has("AAPL", 30) is False

    def test_has_returns_false_for_expired_entry(self, short_ttl_cache):
        """Test has returns False for expired entry."""
        short_ttl_cache.set("AAPL", "test", days=30)

        time.sleep(1.5)

        assert short_ttl_cache.has("AAPL", 30) is False

    def test_has_normalizes_symbol_to_uppercase(self, cache):
        """Test has normalizes symbol to uppercase."""
        cache.set("AAPL", "test", days=30)

        assert cache.has("aapl", 30) is True

    def test_has_different_days_returns_false(self, cache):
        """Test has with different days returns False."""
        cache.set("AAPL", "test", days=30)

        assert cache.has("AAPL", 60) is False


# =============================================================================
# INVALIDATE METHOD TESTS
# =============================================================================

class TestInvalidateMethod:
    """Tests for invalidate method."""

    def test_invalidate_specific_days(self, cache):
        """Test invalidate removes specific days entry."""
        cache.set("AAPL", "data1", days=30)
        cache.set("AAPL", "data2", days=60)
        cache.set("AAPL", "data3", days=260)

        count = cache.invalidate("AAPL", days=60)

        assert count == 1
        assert cache.has("AAPL", 30) is True
        assert cache.has("AAPL", 60) is False
        assert cache.has("AAPL", 260) is True

    def test_invalidate_all_for_symbol(self, cache):
        """Test invalidate without days removes all entries for symbol."""
        cache.set("AAPL", "data1", days=30)
        cache.set("AAPL", "data2", days=60)
        cache.set("AAPL", "data3", days=260)
        cache.set("MSFT", "data4", days=30)

        count = cache.invalidate("AAPL")

        assert count == 3
        assert cache.has("AAPL", 30) is False
        assert cache.has("AAPL", 60) is False
        assert cache.has("AAPL", 260) is False
        assert cache.has("MSFT", 30) is True

    def test_invalidate_returns_zero_for_missing(self, cache):
        """Test invalidate returns 0 for non-existent symbol."""
        count = cache.invalidate("AAPL", days=30)

        assert count == 0

    def test_invalidate_normalizes_symbol_to_uppercase(self, cache):
        """Test invalidate normalizes symbol to uppercase."""
        cache.set("AAPL", "test", days=30)

        count = cache.invalidate("aapl", days=30)

        assert count == 1
        assert cache.has("AAPL", 30) is False

    def test_invalidate_returns_correct_count(self, cache):
        """Test invalidate returns correct removal count."""
        cache.set("AAPL", "data1", days=30)
        cache.set("AAPL", "data2", days=60)
        cache.set("AAPL", "data3", days=90)
        cache.set("AAPL", "data4", days=120)

        count = cache.invalidate("AAPL")

        assert count == 4


# =============================================================================
# CLEAR METHOD TESTS
# =============================================================================

class TestClearMethod:
    """Tests for clear method."""

    def test_clear_removes_all_entries(self, cache):
        """Test clear removes all entries."""
        cache.set("AAPL", "data1", days=30)
        cache.set("MSFT", "data2", days=60)
        cache.set("GOOGL", "data3", days=90)

        count = cache.clear()

        assert count == 3
        assert len(cache._cache) == 0

    def test_clear_returns_zero_for_empty_cache(self, cache):
        """Test clear returns 0 for empty cache."""
        count = cache.clear()

        assert count == 0

    def test_clear_resets_internal_cache(self, cache):
        """Test clear completely empties internal cache dict."""
        cache.set("AAPL", "test", days=30)
        cache.clear()

        assert cache._cache == {}

    def test_clear_preserves_statistics(self, cache):
        """Test clear does not reset statistics."""
        cache.set("AAPL", "test", days=30)
        cache.get("AAPL", days=30)  # Hit
        cache.get("MSFT", days=30)  # Miss

        cache.clear()

        assert cache._hits == 1
        assert cache._misses == 1


# =============================================================================
# STATS METHOD TESTS
# =============================================================================

class TestStatsMethod:
    """Tests for stats method."""

    def test_stats_returns_dict(self, cache):
        """Test stats returns dictionary."""
        stats = cache.stats()

        assert isinstance(stats, dict)

    def test_stats_has_all_expected_keys(self, cache):
        """Test stats has all expected keys."""
        stats = cache.stats()

        expected_keys = [
            "entries",
            "max_entries",
            "hits",
            "misses",
            "hit_rate_percent",
            "evictions",
            "ttl_seconds",
            "avg_entry_age_seconds",
        ]

        for key in expected_keys:
            assert key in stats, f"Missing key: {key}"

    def test_stats_entries_count(self, cache):
        """Test stats reports correct entries count."""
        cache.set("AAPL", "test1", days=30)
        cache.set("MSFT", "test2", days=30)

        stats = cache.stats()

        assert stats["entries"] == 2

    def test_stats_max_entries(self, cache):
        """Test stats reports configured max_entries."""
        stats = cache.stats()

        assert stats["max_entries"] == 100

    def test_stats_tracks_hits(self, cache):
        """Test stats tracks hits correctly."""
        cache.set("AAPL", "test", days=30)
        cache.get("AAPL", days=30)
        cache.get("AAPL", days=30)

        stats = cache.stats()

        assert stats["hits"] == 2

    def test_stats_tracks_misses(self, cache):
        """Test stats tracks misses correctly."""
        cache.get("AAPL", days=30)
        cache.get("MSFT", days=30)

        stats = cache.stats()

        assert stats["misses"] == 2

    def test_stats_calculates_hit_rate(self, cache):
        """Test stats calculates hit rate percentage."""
        cache.set("AAPL", "test", days=30)
        cache.get("AAPL", days=30)  # Hit
        cache.get("MSFT", days=30)  # Miss

        stats = cache.stats()

        assert stats["hit_rate_percent"] == 50.0

    def test_stats_hit_rate_zero_when_no_requests(self, cache):
        """Test stats shows 0 hit rate when no requests made."""
        stats = cache.stats()

        assert stats["hit_rate_percent"] == 0

    def test_stats_tracks_evictions(self, small_cache):
        """Test stats tracks evictions."""
        # Fill cache and trigger eviction
        for i in range(6):
            small_cache.set(f"SYM{i}", f"data{i}", days=30)

        stats = small_cache.stats()

        assert stats["evictions"] > 0

    def test_stats_reports_ttl(self):
        """Test stats reports configured TTL."""
        cache = HistoricalDataCache(ttl_seconds=600)

        stats = cache.stats()

        assert stats["ttl_seconds"] == 600

    def test_stats_calculates_avg_age(self, cache):
        """Test stats calculates average entry age."""
        cache.set("AAPL", "test", days=30)
        time.sleep(0.1)

        stats = cache.stats()

        assert stats["avg_entry_age_seconds"] >= 0


# =============================================================================
# GET CACHED SYMBOLS TESTS
# =============================================================================

class TestGetCachedSymbols:
    """Tests for get_cached_symbols method."""

    def test_returns_list(self, cache):
        """Test returns list type."""
        result = cache.get_cached_symbols()
        assert isinstance(result, list)

    def test_returns_empty_list_for_empty_cache(self, cache):
        """Test returns empty list when cache is empty."""
        result = cache.get_cached_symbols()
        assert result == []

    def test_returns_unique_symbols(self, cache):
        """Test returns unique symbols only."""
        cache.set("AAPL", "data1", days=30)
        cache.set("AAPL", "data2", days=60)
        cache.set("AAPL", "data3", days=260)
        cache.set("MSFT", "data4", days=30)

        result = cache.get_cached_symbols()

        assert sorted(result) == ["AAPL", "MSFT"]

    def test_returns_sorted_list(self, cache):
        """Test returns sorted list."""
        cache.set("MSFT", "data1", days=30)
        cache.set("AAPL", "data2", days=30)
        cache.set("GOOGL", "data3", days=30)

        result = cache.get_cached_symbols()

        assert result == ["AAPL", "GOOGL", "MSFT"]


# =============================================================================
# CACHE EXPIRATION TESTS
# =============================================================================

class TestCacheExpiration:
    """Tests for cache expiration behavior."""

    def test_entry_expires_after_ttl(self, short_ttl_cache):
        """Test entry expires after TTL seconds."""
        short_ttl_cache.set("AAPL", "test", days=30)

        assert short_ttl_cache.has("AAPL", 30) is True

        time.sleep(1.5)

        assert short_ttl_cache.has("AAPL", 30) is False

    def test_get_returns_none_for_expired(self, short_ttl_cache):
        """Test get returns None for expired entries."""
        short_ttl_cache.set("AAPL", "test", days=30)

        time.sleep(1.5)

        result = short_ttl_cache.get("AAPL", days=30)
        assert result is None

    def test_custom_ttl_overrides_default(self):
        """Test custom TTL per-entry overrides default."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=100)

        # Set with short custom TTL
        cache.set("AAPL", "test", days=30, ttl_seconds=1)

        time.sleep(1.5)

        assert cache.has("AAPL", 30) is False

    def test_expired_entries_cleaned_on_set(self, short_ttl_cache):
        """Test expired entries are cleaned during set when cache is full."""
        # Fill cache
        for i in range(short_ttl_cache._max_entries):
            short_ttl_cache.set(f"SYM{i}", f"data{i}", days=30)

        time.sleep(1.5)  # Let all entries expire

        # Add new entry - should trigger cleanup of expired entries
        short_ttl_cache.set("NEW", "new_data", days=30)

        assert short_ttl_cache.has("NEW", 30) is True

    def test_cleanup_expired_removes_old_entries(self, short_ttl_cache):
        """Test _cleanup_expired removes expired entries."""
        short_ttl_cache.set("AAPL", "test", days=30)

        time.sleep(1.5)

        removed = short_ttl_cache._cleanup_expired()

        assert removed == 1
        assert "AAPL:30" not in short_ttl_cache._cache


# =============================================================================
# LRU EVICTION TESTS
# =============================================================================

class TestLRUEviction:
    """Tests for LRU eviction behavior."""

    def test_evicts_least_recently_used(self, small_cache):
        """Test LRU eviction removes oldest accessed entries."""
        # Add entries with small delays
        small_cache.set("A", "data_a", days=30)
        time.sleep(0.02)
        small_cache.set("B", "data_b", days=30)
        time.sleep(0.02)
        small_cache.set("C", "data_c", days=30)
        time.sleep(0.02)
        small_cache.set("D", "data_d", days=30)
        time.sleep(0.02)
        small_cache.set("E", "data_e", days=30)

        # Access A to make it recently used
        small_cache.get("A", days=30)
        time.sleep(0.02)

        # Add new entry - should evict B (oldest not recently accessed)
        small_cache.set("NEW", "data_new", days=30)

        # A should still be there (recently accessed)
        assert small_cache.has("A", 30)
        # NEW should be there (just added)
        assert small_cache.has("NEW", 30)

    def test_eviction_increments_counter(self, small_cache):
        """Test eviction increments evictions counter."""
        # Fill cache
        for i in range(5):
            small_cache.set(f"SYM{i}", f"data{i}", days=30)

        initial_evictions = small_cache._evictions

        # Add more entries to trigger eviction
        small_cache.set("NEW", "data_new", days=30)

        assert small_cache._evictions > initial_evictions

    def test_evict_lru_with_empty_cache(self, cache):
        """Test _evict_lru handles empty cache."""
        removed = cache._evict_lru(count=5)

        assert removed == 0

    def test_evict_lru_removes_specified_count(self, cache):
        """Test _evict_lru removes specified number of entries."""
        for i in range(10):
            cache.set(f"SYM{i}", f"data{i}", days=30)

        removed = cache._evict_lru(count=3)

        assert removed == 3
        assert len(cache._cache) == 7


# =============================================================================
# THREAD SAFETY TESTS
# =============================================================================

class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_set_operations(self):
        """Test concurrent set operations are thread-safe."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=1000)
        errors = []

        def writer(thread_id):
            try:
                for i in range(100):
                    cache.set(f"SYM_{thread_id}_{i}", f"data_{thread_id}_{i}", days=30)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_get_operations(self):
        """Test concurrent get operations are thread-safe."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=1000)
        errors = []

        # Pre-populate cache
        for i in range(100):
            cache.set(f"SYM{i}", f"data{i}", days=30)

        def reader():
            try:
                for i in range(100):
                    cache.get(f"SYM{i}", days=30)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_mixed_operations(self):
        """Test concurrent mixed read/write operations are thread-safe."""
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

        def clearer():
            try:
                for _ in range(10):
                    cache.invalidate("SYM50")
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=clearer),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_stats_access(self):
        """Test concurrent stats access is thread-safe."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=1000)
        results = []
        errors = []

        def stat_reader():
            try:
                for _ in range(50):
                    stats = cache.stats()
                    results.append(stats)
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(50):
                    cache.set(f"SYM{i}", f"data{i}", days=30)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=stat_reader),
            threading.Thread(target=writer),
            threading.Thread(target=stat_reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 100

    def test_concurrent_eviction(self, small_cache):
        """Test concurrent operations that trigger eviction."""
        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    small_cache.set(f"T{thread_id}_SYM{i}", f"data", days=30)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(small_cache._cache) <= small_cache._max_entries

    def test_with_thread_pool_executor(self):
        """Test with ThreadPoolExecutor for more realistic concurrency."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=1000)
        errors = []

        def task(i):
            try:
                cache.set(f"SYM{i}", f"data{i}", days=30)
                cache.get(f"SYM{i}", days=30)
                cache.has(f"SYM{i}", 30)
                return True
            except Exception as e:
                errors.append(e)
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(task, range(200)))

        assert len(errors) == 0
        assert all(results)


# =============================================================================
# SINGLETON PATTERN TESTS
# =============================================================================

class TestSingletonPattern:
    """Tests for singleton pattern implementation."""

    def test_get_historical_cache_returns_instance(self):
        """Test get_historical_cache returns HistoricalDataCache instance."""
        cache = get_historical_cache()
        assert isinstance(cache, HistoricalDataCache)

    def test_get_historical_cache_returns_same_instance(self):
        """Test get_historical_cache returns same instance on multiple calls."""
        cache1 = get_historical_cache()
        cache2 = get_historical_cache()

        assert cache1 is cache2

    def test_singleton_uses_provided_params_on_first_call(self):
        """Test singleton uses parameters from first call."""
        cache = get_historical_cache(ttl_seconds=600, max_entries=200)

        assert cache._ttl_seconds == 600
        assert cache._max_entries == 200

    def test_singleton_ignores_params_on_subsequent_calls(self):
        """Test singleton ignores parameters on subsequent calls."""
        cache1 = get_historical_cache(ttl_seconds=600, max_entries=200)
        cache2 = get_historical_cache(ttl_seconds=100, max_entries=50)

        # Should still have first call's values
        assert cache2._ttl_seconds == 600
        assert cache2._max_entries == 200

    def test_reset_clears_singleton(self):
        """Test reset_historical_cache clears singleton."""
        cache1 = get_historical_cache()
        cache1.set("AAPL", "test", days=30)

        reset_historical_cache()

        cache2 = get_historical_cache()

        assert cache1 is not cache2
        assert not cache2.has("AAPL", 30)

    def test_reset_clears_cache_data(self):
        """Test reset_historical_cache clears cache data."""
        cache = get_historical_cache()
        cache.set("AAPL", "test", days=30)
        cache.set("MSFT", "test", days=30)

        reset_historical_cache()
        new_cache = get_historical_cache()

        assert len(new_cache._cache) == 0


# =============================================================================
# MAKE KEY METHOD TESTS
# =============================================================================

class TestMakeKey:
    """Tests for _make_key internal method."""

    def test_creates_correct_key_format(self, cache):
        """Test key format is SYMBOL:DAYS."""
        key = cache._make_key("AAPL", 30)
        assert key == "AAPL:30"

    def test_uppercases_symbol(self, cache):
        """Test symbol is uppercased in key."""
        key = cache._make_key("aapl", 30)
        assert key == "AAPL:30"

    def test_different_days_produce_different_keys(self, cache):
        """Test different days produce different keys."""
        key1 = cache._make_key("AAPL", 30)
        key2 = cache._make_key("AAPL", 60)

        assert key1 != key2

    def test_different_symbols_produce_different_keys(self, cache):
        """Test different symbols produce different keys."""
        key1 = cache._make_key("AAPL", 30)
        key2 = cache._make_key("MSFT", 30)

        assert key1 != key2


# =============================================================================
# EDGE CASES AND ERROR HANDLING
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_set_with_none_data(self, cache):
        """Test set with None data."""
        cache.set("AAPL", None, days=30)

        result = cache.get("AAPL", days=30)
        assert result is None  # This is ambiguous but valid

    def test_set_with_empty_dict(self, cache):
        """Test set with empty dict."""
        cache.set("AAPL", {}, days=30)

        result = cache.get("AAPL", days=30)
        assert result == {}

    def test_set_with_empty_list(self, cache):
        """Test set with empty list."""
        cache.set("AAPL", [], days=30)

        result = cache.get("AAPL", days=30)
        assert result == []

    def test_set_with_zero_days(self, cache):
        """Test set with zero days."""
        cache.set("AAPL", "test", days=0)

        assert cache.has("AAPL", 0)

    def test_set_with_negative_days(self, cache):
        """Test set with negative days (edge case)."""
        cache.set("AAPL", "test", days=-1)

        # Should still work, days is just a key component
        assert cache.has("AAPL", -1)

    def test_large_number_of_entries(self):
        """Test cache with large number of entries."""
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=10000)

        for i in range(1000):
            cache.set(f"SYM{i}", f"data{i}", days=30)

        assert len(cache._cache) == 1000

    def test_large_data_size(self, cache):
        """Test cache with large data objects."""
        large_data = {"prices": list(range(10000)), "volumes": list(range(10000))}

        cache.set("AAPL", large_data, days=30)

        result = cache.get("AAPL", days=30)
        assert result == large_data

    def test_special_characters_in_symbol(self, cache):
        """Test cache with special characters in symbol."""
        # Some exchanges use dots or dashes in symbols
        cache.set("BRK.A", "test", days=30)

        assert cache.has("BRK.A", 30)

    def test_very_short_ttl(self):
        """Test cache with very short TTL."""
        cache = HistoricalDataCache(ttl_seconds=0, max_entries=100)
        cache.set("AAPL", "test", days=30)

        # Entry should be immediately expired
        time.sleep(0.01)
        assert cache.has("AAPL", 30) is False

    def test_very_long_ttl(self):
        """Test cache with very long TTL."""
        cache = HistoricalDataCache(ttl_seconds=86400, max_entries=100)  # 24 hours
        cache.set("AAPL", "test", days=30)

        assert cache.has("AAPL", 30) is True


# =============================================================================
# FILE-BASED PERSISTENCE TESTS (N/A)
# =============================================================================

class TestFilePersistence:
    """Tests documenting that this cache does NOT have file-based persistence.

    Note: HistoricalDataCache is an in-memory cache implementation.
    It does not persist data to disk. These tests document this behavior.
    """

    def test_cache_is_memory_only(self, cache):
        """Test that cache does not persist to file."""
        cache.set("AAPL", "test", days=30)

        # Create a new cache instance - data should not persist
        new_cache = HistoricalDataCache()

        assert not new_cache.has("AAPL", 30)

    def test_singleton_data_lost_on_reset(self):
        """Test that singleton data is lost on reset."""
        cache = get_historical_cache()
        cache.set("AAPL", "test", days=30)

        reset_historical_cache()
        new_cache = get_historical_cache()

        assert not new_cache.has("AAPL", 30)

    def test_no_persistence_attributes(self, cache):
        """Test cache has no file persistence attributes."""
        # The cache should not have file-related attributes
        assert not hasattr(cache, "_file_path")
        assert not hasattr(cache, "_persist_path")
        assert not hasattr(cache, "save")
        assert not hasattr(cache, "load")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
