# OptionPlay - Cache Manager Tests
# ==================================
"""
Comprehensive tests for the unified CacheManager.

Tests:
- CachePolicy and CacheEntry
- BaseCache core functions
- CacheManager coordination
- Cascading Invalidation
- Thread safety
- Async background refresh
- Stats and health methods
"""

import pytest
import asyncio
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.cache.cache_manager import (
    CacheManager,
    BaseCache,
    CachePolicy,
    CacheEntry,
    CachePriority,
    get_cache_manager,
    reset_cache_manager,
)


# =============================================================================
# CachePolicy Tests
# =============================================================================

class TestCachePolicy:
    """Tests for CachePolicy."""

    def test_required_values(self):
        """CachePolicy requires ttl_seconds and max_entries."""
        policy = CachePolicy(ttl_seconds=300, max_entries=1000)

        assert policy.ttl_seconds == 300
        assert policy.max_entries == 1000
        assert policy.priority == CachePriority.NORMAL  # default

    def test_custom_values(self):
        """Custom policy should use provided values."""
        policy = CachePolicy(
            ttl_seconds=600,
            max_entries=500,
            priority=CachePriority.HIGH
        )

        assert policy.ttl_seconds == 600
        assert policy.max_entries == 500
        assert policy.priority == CachePriority.HIGH

    def test_refresh_threshold(self):
        """refresh_threshold_seconds should be based on ttl and refresh_at_pct."""
        policy = CachePolicy(ttl_seconds=100, max_entries=100, refresh_at_pct=0.8)

        assert policy.refresh_threshold_seconds == 80.0

    def test_refresh_threshold_different_percentages(self):
        """refresh_threshold_seconds should work with different percentages."""
        policy_50 = CachePolicy(ttl_seconds=100, max_entries=100, refresh_at_pct=0.5)
        policy_90 = CachePolicy(ttl_seconds=100, max_entries=100, refresh_at_pct=0.9)

        assert policy_50.refresh_threshold_seconds == 50.0
        assert policy_90.refresh_threshold_seconds == 90.0

    def test_fallback_enabled_default(self):
        """fallback_enabled should default to True."""
        policy = CachePolicy(ttl_seconds=100, max_entries=100)
        assert policy.fallback_enabled is True

    def test_fallback_enabled_custom(self):
        """fallback_enabled can be set to False."""
        policy = CachePolicy(ttl_seconds=100, max_entries=100, fallback_enabled=False)
        assert policy.fallback_enabled is False

    def test_all_priority_levels(self):
        """All priority levels should be settable."""
        for priority in CachePriority:
            policy = CachePolicy(ttl_seconds=100, max_entries=100, priority=priority)
            assert policy.priority == priority


# =============================================================================
# CacheEntry Tests
# =============================================================================

class TestCacheEntry:
    """Tests for CacheEntry."""

    def test_creation(self):
        """CacheEntry should store data and timestamp."""
        now = datetime.now()
        entry = CacheEntry(
            key="test_key",
            value={"foo": "bar"},
            created_at=now,
            expires_at=now + timedelta(seconds=300)
        )

        assert entry.value == {"foo": "bar"}
        assert entry.created_at is not None
        assert entry.access_count == 0

    def test_is_expired(self):
        """is_expired should check against expiry time."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300)
        )

        assert not entry.is_expired

        # Simulate expired entry
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now - timedelta(seconds=400),
            expires_at=now - timedelta(seconds=100)
        )
        assert entry.is_expired

    def test_is_expired_exactly_at_expiry(self):
        """Entry should be expired exactly at expiry time."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now - timedelta(seconds=1),
            expires_at=now - timedelta(microseconds=1)  # Just past expiry
        )
        assert entry.is_expired

    def test_age_seconds(self):
        """age_seconds should return correct age."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300)
        )

        assert entry.age_seconds >= 0
        assert entry.age_seconds < 1  # Should be very recent

    def test_age_seconds_older_entry(self):
        """age_seconds should correctly calculate for older entries."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now - timedelta(seconds=60),
            expires_at=now + timedelta(seconds=240)
        )

        assert entry.age_seconds >= 60
        assert entry.age_seconds < 61

    def test_touch_increments_access(self):
        """touch should increment access count and update timestamp."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300)
        )
        original_access = entry.last_accessed_at

        time.sleep(0.01)  # Small delay
        entry.touch()

        assert entry.access_count == 1
        assert entry.last_accessed_at is not None

    def test_touch_multiple_times(self):
        """Multiple touches should increment access count correctly."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now,
            expires_at=now + timedelta(seconds=300)
        )

        for i in range(5):
            entry.touch()

        assert entry.access_count == 5

    def test_time_to_expiry(self):
        """time_to_expiry_seconds should return remaining time."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now,
            expires_at=now + timedelta(seconds=100)
        )

        assert entry.time_to_expiry_seconds <= 100
        assert entry.time_to_expiry_seconds > 99  # Very recent

    def test_time_to_expiry_expired(self):
        """time_to_expiry_seconds should return 0 for expired entries."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now - timedelta(seconds=200),
            expires_at=now - timedelta(seconds=100)
        )

        assert entry.time_to_expiry_seconds == 0

    def test_should_refresh(self):
        """should_refresh checks if proactive refresh is needed."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now - timedelta(seconds=90),  # 90 seconds old
            expires_at=now + timedelta(seconds=10)   # 100 total TTL
        )

        # 90% threshold - 90 seconds of 100 = should refresh
        assert entry.should_refresh(0.8)  # 80% threshold
        assert not entry.should_refresh(0.95)  # 95% threshold

    def test_should_refresh_fresh_entry(self):
        """Fresh entries should not need refresh."""
        now = datetime.now()
        entry = CacheEntry(
            key="test",
            value="test",
            created_at=now,
            expires_at=now + timedelta(seconds=100)
        )

        assert not entry.should_refresh(0.8)
        assert not entry.should_refresh(0.5)

    def test_entry_stores_different_value_types(self):
        """CacheEntry should store various value types."""
        now = datetime.now()
        expires = now + timedelta(seconds=100)

        # Dict
        entry1 = CacheEntry(key="dict", value={"a": 1}, created_at=now, expires_at=expires)
        assert entry1.value == {"a": 1}

        # List
        entry2 = CacheEntry(key="list", value=[1, 2, 3], created_at=now, expires_at=expires)
        assert entry2.value == [1, 2, 3]

        # None
        entry3 = CacheEntry(key="none", value=None, created_at=now, expires_at=expires)
        assert entry3.value is None

        # Complex object
        entry4 = CacheEntry(key="complex", value={"nested": {"data": [1, 2]}}, created_at=now, expires_at=expires)
        assert entry4.value == {"nested": {"data": [1, 2]}}


# =============================================================================
# BaseCache Tests
# =============================================================================

class TestBaseCache:
    """Tests for BaseCache."""

    def _create_cache(self, name="test", ttl=300, max_entries=100, priority=CachePriority.NORMAL):
        """Helper to create a cache with policy."""
        policy = CachePolicy(ttl_seconds=ttl, max_entries=max_entries, priority=priority)
        return BaseCache(policy, name)

    def test_get_set(self):
        """Basic get/set should work."""
        cache = self._create_cache()

        cache.set("key1", "value1")
        result = cache.get("key1")

        assert result == "value1"

    def test_get_missing_key(self):
        """get should return None for missing keys."""
        cache = self._create_cache()

        result = cache.get("nonexistent")

        assert result is None

    def test_get_missing_returns_none(self):
        """get should return None for missing keys (no default param)."""
        cache = self._create_cache()

        result = cache.get("nonexistent")

        # BaseCache.get() returns None for missing keys, no default param
        assert result is None

    def test_set_overwrites_existing(self):
        """set should overwrite existing values."""
        cache = self._create_cache()

        cache.set("key1", "value1")
        cache.set("key1", "value2")

        assert cache.get("key1") == "value2"

    def test_set_with_custom_ttl(self):
        """set with custom TTL should override policy TTL."""
        cache = self._create_cache(ttl=300)

        cache.set("key1", "value1", ttl_seconds=1)

        # Value should exist initially
        assert cache.get("key1") == "value1"

    def test_set_with_custom_priority(self):
        """set with custom priority should override policy priority."""
        cache = self._create_cache(priority=CachePriority.NORMAL)

        cache.set("key1", "value1", priority=CachePriority.HIGH)

        # Check the entry has the custom priority
        entry = cache._entries.get("key1")
        assert entry is not None
        assert entry.priority == CachePriority.HIGH

    def test_ttl_expiration(self):
        """Expired entries should return None."""
        cache = self._create_cache(ttl=1)

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Manually expire by modifying the entry
        cache._entries["key1"] = CacheEntry(
            key="key1",
            value="value1",
            created_at=datetime.now() - timedelta(seconds=10),
            expires_at=datetime.now() - timedelta(seconds=5)
        )
        assert cache.get("key1") is None

    def test_get_expired_removes_entry(self):
        """Getting expired entry should remove it from cache."""
        cache = self._create_cache()

        cache.set("key1", "value1")

        # Manually expire
        cache._entries["key1"] = CacheEntry(
            key="key1",
            value="value1",
            created_at=datetime.now() - timedelta(seconds=10),
            expires_at=datetime.now() - timedelta(seconds=5)
        )

        # Get should return None and remove entry
        result = cache.get("key1")
        assert result is None
        assert "key1" not in cache._entries

    def test_remove(self):
        """remove should remove entry."""
        cache = self._create_cache()

        cache.set("key1", "value1")
        result = cache.remove("key1")

        assert result is True
        assert cache.get("key1") is None

    def test_remove_nonexistent(self):
        """remove should return False for nonexistent key."""
        cache = self._create_cache()

        result = cache.remove("nonexistent")

        assert result is False

    def test_clear(self):
        """clear should remove all entries."""
        cache = self._create_cache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        count = cache.clear()

        assert count == 2
        assert len(cache) == 0
        assert cache.get("key1") is None

    def test_clear_empty_cache(self):
        """clear on empty cache should return 0."""
        cache = self._create_cache()

        count = cache.clear()

        assert count == 0

    def test_contains(self):
        """contains should check key existence."""
        cache = self._create_cache()

        cache.set("key1", "value1")

        assert cache.contains("key1")
        assert not cache.contains("nonexistent")

    def test_contains_ignores_expiration(self):
        """contains should not check expiration."""
        cache = self._create_cache()

        cache.set("key1", "value1")

        # Manually expire
        cache._entries["key1"] = CacheEntry(
            key="key1",
            value="value1",
            created_at=datetime.now() - timedelta(seconds=10),
            expires_at=datetime.now() - timedelta(seconds=5)
        )

        # contains should still return True (no expiration check)
        assert cache.contains("key1")

    def test_len(self):
        """len should return entry count."""
        cache = self._create_cache()

        assert len(cache) == 0

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        assert len(cache) == 2

    def test_max_entries_eviction(self):
        """Setting more than max_entries should evict oldest."""
        cache = self._create_cache(max_entries=3)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key4", "value4")  # Should evict oldest

        assert len(cache) == 3
        # key1 should be evicted (oldest)
        assert not cache.contains("key1")
        assert cache.contains("key4")

    def test_eviction_respects_priority(self):
        """Eviction should respect priority levels."""
        cache = self._create_cache(max_entries=3)

        # Set entries with different priorities
        cache.set("low", "value1", priority=CachePriority.LOW)
        cache.set("normal", "value2", priority=CachePriority.NORMAL)
        cache.set("high", "value3", priority=CachePriority.HIGH)

        # Add another entry, should evict LOW priority first
        cache.set("new", "value4")

        assert len(cache) == 3
        assert not cache.contains("low")  # LOW priority evicted
        assert cache.contains("normal")
        assert cache.contains("high")
        assert cache.contains("new")

    def test_get_keys(self):
        """get_keys should return all keys."""
        cache = self._create_cache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        keys = cache.get_keys()

        assert "key1" in keys
        assert "key2" in keys

    def test_get_keys_empty_cache(self):
        """get_keys should return empty list for empty cache."""
        cache = self._create_cache()

        keys = cache.get_keys()

        assert keys == []

    def test_cleanup_expired(self):
        """cleanup_expired should remove expired entries."""
        cache = self._create_cache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Expire one entry
        cache._entries["key1"] = CacheEntry(
            key="key1",
            value="value1",
            created_at=datetime.now() - timedelta(seconds=10),
            expires_at=datetime.now() - timedelta(seconds=5)
        )

        count = cache.cleanup_expired()

        assert count == 1
        assert not cache.contains("key1")
        assert cache.contains("key2")

    def test_cleanup_expired_no_expired(self):
        """cleanup_expired should return 0 when no entries expired."""
        cache = self._create_cache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        count = cache.cleanup_expired()

        assert count == 0
        assert len(cache) == 2

    def test_should_refresh(self):
        """should_refresh should check if entry needs proactive refresh."""
        cache = self._create_cache()

        cache.set("key1", "value1")

        # Fresh entry should not need refresh
        assert not cache.should_refresh("key1")

        # Modify to be near expiry
        # Make entry 85% through its TTL
        total_ttl = 300
        age = total_ttl * 0.85
        cache._entries["key1"] = CacheEntry(
            key="key1",
            value="value1",
            created_at=datetime.now() - timedelta(seconds=age),
            expires_at=datetime.now() + timedelta(seconds=total_ttl - age)
        )

        # Should need refresh at 80% threshold
        assert cache.should_refresh("key1")

    def test_should_refresh_missing_key(self):
        """should_refresh should return False for missing key."""
        cache = self._create_cache()

        assert not cache.should_refresh("nonexistent")

    def test_name_property(self):
        """name property should return cache name."""
        cache = self._create_cache(name="my_cache")

        assert cache.name == "my_cache"

    def test_metrics_property(self):
        """metrics property should return CacheMetrics."""
        cache = self._create_cache(name="test")

        metrics = cache.metrics

        assert metrics.name == "test"

    def test_metrics_record_hit_miss(self):
        """Metrics should record hits and misses correctly."""
        cache = self._create_cache()

        cache.set("key1", "value1")

        # Hit
        cache.get("key1")
        assert cache.metrics.hits == 1

        # Miss
        cache.get("nonexistent")
        assert cache.metrics.misses == 1

    def test_metrics_record_eviction(self):
        """Metrics should record evictions."""
        cache = self._create_cache(max_entries=2)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Triggers eviction

        assert cache.metrics.evictions == 1


# =============================================================================
# CacheManager Initialization Tests
# =============================================================================

class TestCacheManagerInitialization:
    """Tests for CacheManager initialization."""

    def test_default_caches_created(self):
        """CacheManager should create default caches."""
        manager = CacheManager()

        # Should have default caches
        assert "historical" in manager._caches
        assert "quotes" in manager._caches
        assert "earnings" in manager._caches
        assert "scans" in manager._caches
        assert "iv" in manager._caches
        assert "options" in manager._caches

    def test_default_policies_applied(self):
        """Default policies should be applied to caches."""
        manager = CacheManager()

        # Check historical cache policy
        historical = manager.get_cache("historical")
        assert historical._policy.ttl_seconds == 900
        assert historical._policy.max_entries == 2000
        assert historical._policy.priority == CachePriority.HIGH

    def test_custom_policies(self):
        """Custom policies should override defaults."""
        custom_policies = {
            "historical": CachePolicy(ttl_seconds=100, max_entries=50)
        }
        manager = CacheManager(policies=custom_policies)

        historical = manager.get_cache("historical")
        assert historical._policy.ttl_seconds == 100
        assert historical._policy.max_entries == 50

    def test_custom_policies_merged_with_defaults(self):
        """Custom policies should merge with defaults, not replace."""
        custom_policies = {
            "custom": CachePolicy(ttl_seconds=100, max_entries=50)
        }
        manager = CacheManager(policies=custom_policies)

        # Should have both default and custom
        assert "historical" in manager._caches  # default
        assert "custom" in manager._caches  # custom

    def test_create_default_factory(self):
        """create_default should return default configuration."""
        manager = CacheManager.create_default()

        assert isinstance(manager, CacheManager)
        assert len(manager._caches) == 6

    def test_create_for_testing_short_ttl(self):
        """create_for_testing with short_ttl should use 1 second TTL."""
        manager = CacheManager.create_for_testing(short_ttl=True)

        historical = manager.get_cache("historical")
        assert historical._policy.ttl_seconds == 1
        assert historical._policy.refresh_at_pct == 0.5

    def test_create_for_testing_normal(self):
        """create_for_testing without short_ttl should use default TTLs."""
        manager = CacheManager.create_for_testing(short_ttl=False)

        historical = manager.get_cache("historical")
        assert historical._policy.ttl_seconds == 900  # Default

    def test_default_dependencies(self):
        """Manager should have default dependencies."""
        manager = CacheManager()

        assert "scans" in manager._dependencies.get("earnings", [])
        assert "scans" in manager._dependencies.get("iv", [])
        assert "quotes" in manager._dependencies.get("historical", [])
        assert "scans" in manager._dependencies.get("historical", [])


# =============================================================================
# CacheManager Get/Set Tests
# =============================================================================

class TestCacheManagerGetSet:
    """Tests for CacheManager get/set operations."""

    def test_get_cache(self):
        """get_cache should return cache by name."""
        manager = CacheManager()

        cache = manager.get_cache("quotes")

        assert cache is not None
        assert isinstance(cache, BaseCache)

    def test_get_cache_nonexistent(self):
        """get_cache should raise KeyError for nonexistent cache."""
        manager = CacheManager()

        with pytest.raises(KeyError) as exc_info:
            manager.get_cache("nonexistent")

        assert "nonexistent" in str(exc_info.value)
        assert "Available" in str(exc_info.value)

    def test_get_value(self):
        """get should return value from cache."""
        manager = CacheManager()
        manager.set("quotes", "AAPL", {"price": 150.0})

        result = manager.get("quotes", "AAPL")

        assert result == {"price": 150.0}

    def test_get_missing_value(self):
        """get should return None for missing values."""
        manager = CacheManager()

        result = manager.get("quotes", "nonexistent")

        assert result is None

    def test_set_value(self):
        """set should store value in cache."""
        manager = CacheManager()

        manager.set("quotes", "AAPL", {"price": 150.0})

        cache = manager.get_cache("quotes")
        assert cache.get("AAPL") == {"price": 150.0}

    def test_set_with_custom_ttl(self):
        """set with custom TTL should work."""
        manager = CacheManager()

        manager.set("quotes", "AAPL", {"price": 150.0}, ttl_seconds=10)

        result = manager.get("quotes", "AAPL")
        assert result == {"price": 150.0}

    def test_remove_value(self):
        """remove should remove value from cache."""
        manager = CacheManager()
        manager.set("quotes", "AAPL", {"price": 150.0})

        result = manager.remove("quotes", "AAPL")

        assert result is True
        assert manager.get("quotes", "AAPL") is None

    def test_remove_nonexistent(self):
        """remove should return False for nonexistent key."""
        manager = CacheManager()

        result = manager.remove("quotes", "nonexistent")

        assert result is False

    def test_should_refresh(self):
        """should_refresh should delegate to cache."""
        manager = CacheManager()
        manager.set("quotes", "AAPL", {"price": 150.0})

        # Fresh entry should not need refresh
        assert not manager.should_refresh("quotes", "AAPL")


# =============================================================================
# CacheManager Invalidation Tests
# =============================================================================

class TestCacheManagerInvalidation:
    """Tests for CacheManager invalidation."""

    def test_invalidate_cache(self):
        """invalidate should clear cache."""
        manager = CacheManager()
        quotes = manager.get_cache("quotes")
        quotes.set("AAPL", {"price": 150.0})

        manager.invalidate("quotes")

        assert len(quotes) == 0

    def test_invalidate_key(self):
        """invalidate with key should only remove that key."""
        manager = CacheManager()
        quotes = manager.get_cache("quotes")
        quotes.set("AAPL", {"price": 150.0})
        quotes.set("MSFT", {"price": 300.0})

        manager.invalidate("quotes", key="AAPL")

        assert not quotes.contains("AAPL")
        assert quotes.contains("MSFT")

    def test_invalidate_returns_count(self):
        """invalidate should return count of removed entries."""
        manager = CacheManager()
        quotes = manager.get_cache("quotes")
        quotes.set("AAPL", {"price": 150.0})
        quotes.set("MSFT", {"price": 300.0})

        count = manager.invalidate("quotes")

        assert count == 2

    def test_clear_all(self):
        """clear_all should clear all caches."""
        manager = CacheManager()
        manager.get_cache("quotes").set("AAPL", {"price": 150.0})
        manager.get_cache("historical").set("AAPL:90", [100, 110, 120])

        count = manager.clear_all()

        assert len(manager.get_cache("quotes")) == 0
        assert len(manager.get_cache("historical")) == 0
        assert count == 2

    def test_cascading_invalidation(self):
        """invalidate with cascade=True should invalidate dependents."""
        manager = CacheManager()

        # Setup data - earnings depends on scans
        manager.get_cache("earnings").set("AAPL", {"date": "2024-01-15"})
        manager.get_cache("scans").set("pullback", ["AAPL", "MSFT"])

        # Invalidate earnings should cascade to scans
        manager.invalidate("earnings", cascade=True)

        assert len(manager.get_cache("earnings")) == 0
        assert len(manager.get_cache("scans")) == 0

    def test_no_cascade(self):
        """invalidate with cascade=False should not affect dependents."""
        manager = CacheManager()

        manager.get_cache("earnings").set("AAPL", {"date": "2024-01-15"})
        manager.get_cache("scans").set("pullback", ["AAPL", "MSFT"])

        manager.invalidate("earnings", cascade=False)

        assert len(manager.get_cache("earnings")) == 0
        assert len(manager.get_cache("scans")) == 1  # Not affected

    def test_cascading_invalidation_historical(self):
        """Historical cache invalidation should cascade to quotes and scans."""
        manager = CacheManager()

        manager.get_cache("historical").set("AAPL:90", [100, 110, 120])
        manager.get_cache("quotes").set("AAPL", {"price": 150.0})
        manager.get_cache("scans").set("pullback", ["AAPL"])

        manager.invalidate("historical", cascade=True)

        assert len(manager.get_cache("historical")) == 0
        assert len(manager.get_cache("quotes")) == 0
        assert len(manager.get_cache("scans")) == 0

    def test_cleanup_expired(self):
        """cleanup_expired should clean all caches."""
        manager = CacheManager()

        # Add entries to multiple caches
        manager.get_cache("quotes").set("AAPL", {"price": 150.0})
        manager.get_cache("historical").set("AAPL:90", [100])

        # Manually expire one
        quotes = manager.get_cache("quotes")
        quotes._entries["AAPL"] = CacheEntry(
            key="AAPL",
            value={"price": 150.0},
            created_at=datetime.now() - timedelta(seconds=1000),
            expires_at=datetime.now() - timedelta(seconds=100)
        )

        count = manager.cleanup_expired()

        assert count == 1


# =============================================================================
# CacheManager Stats Tests
# =============================================================================

class TestCacheManagerStats:
    """Tests for CacheManager stats methods."""

    def test_get_unified_stats(self):
        """get_unified_stats should return stats for all caches."""
        manager = CacheManager()
        manager.get_cache("quotes").set("AAPL", {"price": 150.0})

        stats = manager.get_unified_stats()

        # Stats are nested under "caches" key
        assert "caches" in stats
        assert "quotes" in stats["caches"]
        assert stats["caches"]["quotes"]["current_entries"] == 1
        # Summary stats
        assert "summary" in stats
        assert stats["summary"]["total_entries"] >= 1

    def test_unified_stats_summary(self):
        """Summary should aggregate stats across all caches."""
        manager = CacheManager()

        # Add entries to multiple caches
        quotes = manager.get_cache("quotes")
        quotes.set("AAPL", {"price": 150.0})
        quotes.get("AAPL")  # Hit
        quotes.get("MSFT")  # Miss

        historical = manager.get_cache("historical")
        historical.set("AAPL:90", [100])
        historical.get("AAPL:90")  # Hit

        stats = manager.get_unified_stats()

        assert stats["summary"]["total_entries"] >= 2
        assert stats["summary"]["total_hits"] == 2
        assert stats["summary"]["total_misses"] == 1

    def test_unified_stats_hit_rate(self):
        """Hit rate should be calculated correctly."""
        manager = CacheManager()

        quotes = manager.get_cache("quotes")
        quotes.set("AAPL", {"price": 150.0})

        # 3 hits, 1 miss = 75% hit rate
        for _ in range(3):
            quotes.get("AAPL")
        quotes.get("nonexistent")

        stats = manager.get_unified_stats()

        assert stats["summary"]["overall_hit_rate_pct"] == 75.0

    def test_unified_stats_zero_requests(self):
        """Hit rate should be 0 when no requests."""
        manager = CacheManager()

        stats = manager.get_unified_stats()

        assert stats["summary"]["overall_hit_rate_pct"] == 0.0

    def test_get_health(self):
        """get_health should return health status."""
        manager = CacheManager()

        health = manager.get_health()

        assert "status" in health
        assert "warnings" in health
        assert "summary" in health
        assert "caches" in health

    def test_health_status_healthy(self):
        """Health should be healthy when no warnings."""
        manager = CacheManager()

        health = manager.get_health()

        assert health["status"] == "healthy"
        assert health["warnings"] == []

    def test_health_status_warning_high_fill_rate(self):
        """Health should warn on high fill rate."""
        manager = CacheManager()

        # Fill cache to > 90%
        quotes = manager.get_cache("quotes")
        for i in range(int(quotes._policy.max_entries * 0.95)):
            quotes.set(f"key{i}", f"value{i}")

        health = manager.get_health()

        assert health["status"] == "warning"
        assert any("High fill rate" in w for w in health["warnings"])

    def test_health_status_warning_low_hit_rate(self):
        """Health should warn on low hit rate (< 50%)."""
        manager = CacheManager()

        quotes = manager.get_cache("quotes")
        quotes.set("key1", "value1")

        # Generate > 100 requests with < 50% hit rate
        for _ in range(40):
            quotes.get("key1")  # hit
        for _ in range(70):
            quotes.get("nonexistent")  # miss

        health = manager.get_health()

        assert health["status"] == "warning"
        assert any("Low hit rate" in w for w in health["warnings"])


# =============================================================================
# CacheManager Singleton Tests
# =============================================================================

class TestCacheManagerSingleton:
    """Tests for CacheManager Singleton."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_cache_manager()

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_cache_manager()

    def test_get_cache_manager(self):
        """get_cache_manager should return singleton."""
        manager1 = get_cache_manager()
        manager2 = get_cache_manager()

        assert manager1 is manager2

    def test_reset_cache_manager(self):
        """reset_cache_manager should create new instance."""
        manager1 = get_cache_manager()
        reset_cache_manager()
        manager2 = get_cache_manager()

        assert manager1 is not manager2

    def test_reset_clears_data(self):
        """reset_cache_manager should clear all cached data."""
        manager1 = get_cache_manager()
        manager1.set("quotes", "AAPL", {"price": 150.0})

        reset_cache_manager()

        manager2 = get_cache_manager()
        assert manager2.get("quotes", "AAPL") is None


# =============================================================================
# CacheManager Dependencies Tests
# =============================================================================

class TestCacheManagerDependencies:
    """Tests for Dependency-Management."""

    def test_default_dependencies(self):
        """Manager should have default dependencies."""
        manager = CacheManager()

        # earnings -> scans (defined in DEFAULT_DEPENDENCIES)
        assert "scans" in manager._dependencies.get("earnings", [])

    def test_dependencies_used_in_cascade(self):
        """Dependencies should be used for cascading invalidation."""
        manager = CacheManager()

        # Setup data
        manager.get_cache("earnings").set("AAPL", {"date": "2024-01-15"})
        manager.get_cache("scans").set("pullback", ["AAPL", "MSFT"])

        # Invalidate with cascade should clear dependents
        manager.invalidate("earnings", cascade=True)

        # Both caches cleared due to dependency
        assert len(manager.get_cache("earnings")) == 0
        assert len(manager.get_cache("scans")) == 0

    def test_custom_dependencies(self):
        """Custom dependencies can be passed at construction."""
        custom_deps = {
            "quotes": ["scans", "options"]
        }
        manager = CacheManager(dependencies=custom_deps)

        # Should have both default and custom
        assert "scans" in manager._dependencies.get("earnings", [])  # default
        assert "scans" in manager._dependencies.get("quotes", [])  # custom
        assert "options" in manager._dependencies.get("quotes", [])  # custom

    def test_nonexistent_dependent_cache_ignored(self):
        """Cascade to nonexistent dependent cache should be ignored."""
        custom_deps = {
            "quotes": ["nonexistent_cache"]
        }
        manager = CacheManager(dependencies=custom_deps)
        manager.get_cache("quotes").set("AAPL", {"price": 150.0})

        # Should not raise error
        count = manager.invalidate("quotes", cascade=True)

        assert count == 1  # Only the quotes entry


# =============================================================================
# CachePriority Tests
# =============================================================================

class TestCachePriority:
    """Tests for CachePriority."""

    def test_priority_ordering_by_value(self):
        """Priorities should have correct value ordering."""
        assert CachePriority.LOW.value < CachePriority.NORMAL.value
        assert CachePriority.NORMAL.value < CachePriority.HIGH.value
        assert CachePriority.HIGH.value < CachePriority.CRITICAL.value

    def test_priority_names(self):
        """Priorities should have expected names."""
        assert CachePriority.LOW.name == "LOW"
        assert CachePriority.NORMAL.name == "NORMAL"
        assert CachePriority.HIGH.name == "HIGH"
        assert CachePriority.CRITICAL.name == "CRITICAL"

    def test_priority_values(self):
        """Priorities should have expected values."""
        assert CachePriority.LOW.value == 1
        assert CachePriority.NORMAL.value == 2
        assert CachePriority.HIGH.value == 3
        assert CachePriority.CRITICAL.value == 4


# =============================================================================
# Thread Safety Tests
# =============================================================================

class TestCacheThreadSafety:
    """Tests for thread safety of cache operations."""

    def test_concurrent_reads_dont_crash(self):
        """Concurrent reads should not crash."""
        manager = CacheManager()
        quotes = manager.get_cache("quotes")

        # Pre-populate cache
        for i in range(100):
            quotes.set(f"key{i}", f"value{i}")

        errors = []

        def read_task(thread_id):
            try:
                for _ in range(100):
                    for i in range(10):
                        quotes.get(f"key{i}")
                return True
            except Exception as e:
                errors.append(str(e))
                return False

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_task, i) for i in range(10)]
            results = [f.result() for f in as_completed(futures)]

        assert all(results), f"Errors: {errors}"

    def test_concurrent_writes_dont_corrupt(self):
        """Concurrent writes should not corrupt cache."""
        manager = CacheManager()
        quotes = manager.get_cache("quotes")

        errors = []

        def write_task(thread_id):
            try:
                for i in range(100):
                    quotes.set(f"thread{thread_id}_key{i}", f"value{i}")
                return True
            except Exception as e:
                errors.append(str(e))
                return False

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_task, i) for i in range(10)]
            results = [f.result() for f in as_completed(futures)]

        assert all(results), f"Errors: {errors}"

    def test_concurrent_read_write(self):
        """Concurrent reads and writes should work together."""
        manager = CacheManager()
        quotes = manager.get_cache("quotes")

        # Pre-populate
        for i in range(50):
            quotes.set(f"key{i}", f"value{i}")

        errors = []

        def mixed_task(thread_id):
            try:
                for i in range(100):
                    if i % 2 == 0:
                        quotes.set(f"thread{thread_id}_key{i}", f"value{i}")
                    else:
                        quotes.get(f"key{i % 50}")
                return True
            except Exception as e:
                errors.append(str(e))
                return False

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(mixed_task, i) for i in range(10)]
            results = [f.result() for f in as_completed(futures)]

        assert all(results), f"Errors: {errors}"

    def test_concurrent_clear_and_access(self):
        """Concurrent clear and access should not crash."""
        manager = CacheManager()
        quotes = manager.get_cache("quotes")

        errors = []

        def access_task():
            try:
                for _ in range(100):
                    quotes.set("key", "value")
                    quotes.get("key")
                return True
            except Exception as e:
                errors.append(str(e))
                return False

        def clear_task():
            try:
                for _ in range(10):
                    quotes.clear()
                    time.sleep(0.001)
                return True
            except Exception as e:
                errors.append(str(e))
                return False

        with ThreadPoolExecutor(max_workers=5) as executor:
            access_futures = [executor.submit(access_task) for _ in range(4)]
            clear_futures = [executor.submit(clear_task)]
            all_futures = access_futures + clear_futures
            results = [f.result() for f in as_completed(all_futures)]

        assert all(results), f"Errors: {errors}"

    def test_singleton_thread_safety(self):
        """get_cache_manager should be thread-safe."""
        reset_cache_manager()

        managers = []
        errors = []

        def get_manager_task():
            try:
                manager = get_cache_manager()
                managers.append(manager)
                return True
            except Exception as e:
                errors.append(str(e))
                return False

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(get_manager_task) for _ in range(100)]
            results = [f.result() for f in as_completed(futures)]

        assert all(results), f"Errors: {errors}"
        # All managers should be the same instance
        assert all(m is managers[0] for m in managers)

        reset_cache_manager()


# =============================================================================
# Async Background Refresh Tests
# =============================================================================

class TestAsyncBackgroundRefresh:
    """Tests for async background refresh functionality."""

    @pytest.mark.asyncio
    async def test_get_with_refresh_returns_value(self):
        """get_with_refresh should return cached value."""
        manager = CacheManager()
        manager.set("quotes", "AAPL", {"price": 150.0})

        async def refresh_func():
            return {"price": 155.0}

        result = await manager.get_with_refresh("quotes", "AAPL", refresh_func)

        assert result == {"price": 150.0}

    @pytest.mark.asyncio
    async def test_get_with_refresh_returns_none_for_missing(self):
        """get_with_refresh should return None for missing key."""
        manager = CacheManager()

        async def refresh_func():
            return {"price": 155.0}

        result = await manager.get_with_refresh("quotes", "AAPL", refresh_func)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_with_refresh_triggers_refresh_when_needed(self):
        """get_with_refresh should trigger refresh for stale entries."""
        manager = CacheManager()

        # Set up entry that needs refresh (85% through TTL)
        quotes = manager.get_cache("quotes")
        total_ttl = 60  # quotes TTL is 60 seconds
        age = total_ttl * 0.85
        quotes._entries["AAPL"] = CacheEntry(
            key="AAPL",
            value={"price": 150.0},
            created_at=datetime.now() - timedelta(seconds=age),
            expires_at=datetime.now() + timedelta(seconds=total_ttl - age),
            priority=CachePriority.NORMAL
        )

        refresh_called = False

        async def refresh_func():
            nonlocal refresh_called
            refresh_called = True
            return {"price": 155.0}

        # Get value - should trigger background refresh
        result = await manager.get_with_refresh("quotes", "AAPL", refresh_func)

        # Original value returned immediately
        assert result == {"price": 150.0}

        # Give background task time to run
        await asyncio.sleep(0.1)

        assert refresh_called

    @pytest.mark.asyncio
    async def test_get_with_refresh_no_duplicate_refreshes(self):
        """get_with_refresh should not trigger duplicate refreshes."""
        manager = CacheManager()

        # Set up entry that needs refresh
        quotes = manager.get_cache("quotes")
        total_ttl = 60
        age = total_ttl * 0.85
        quotes._entries["AAPL"] = CacheEntry(
            key="AAPL",
            value={"price": 150.0},
            created_at=datetime.now() - timedelta(seconds=age),
            expires_at=datetime.now() + timedelta(seconds=total_ttl - age),
            priority=CachePriority.NORMAL
        )

        refresh_count = 0

        async def refresh_func():
            nonlocal refresh_count
            refresh_count += 1
            await asyncio.sleep(0.1)  # Slow refresh
            return {"price": 155.0}

        # Call multiple times quickly
        await manager.get_with_refresh("quotes", "AAPL", refresh_func)
        await manager.get_with_refresh("quotes", "AAPL", refresh_func)
        await manager.get_with_refresh("quotes", "AAPL", refresh_func)

        # Wait for refresh to complete
        await asyncio.sleep(0.2)

        # Should only trigger one refresh
        assert refresh_count == 1

    @pytest.mark.asyncio
    async def test_background_refresh_updates_cache(self):
        """Background refresh should update cache with new value."""
        manager = CacheManager()

        # Set up entry that needs refresh
        quotes = manager.get_cache("quotes")
        total_ttl = 60
        age = total_ttl * 0.85
        quotes._entries["AAPL"] = CacheEntry(
            key="AAPL",
            value={"price": 150.0},
            created_at=datetime.now() - timedelta(seconds=age),
            expires_at=datetime.now() + timedelta(seconds=total_ttl - age),
            priority=CachePriority.NORMAL
        )

        async def refresh_func():
            return {"price": 155.0}

        await manager.get_with_refresh("quotes", "AAPL", refresh_func)

        # Wait for background refresh
        await asyncio.sleep(0.1)

        # Cache should be updated
        result = manager.get("quotes", "AAPL")
        assert result == {"price": 155.0}

    @pytest.mark.asyncio
    async def test_background_refresh_handles_errors_gracefully(self):
        """Background refresh errors should not crash."""
        manager = CacheManager()

        # Set up entry that needs refresh
        quotes = manager.get_cache("quotes")
        total_ttl = 60
        age = total_ttl * 0.85
        quotes._entries["AAPL"] = CacheEntry(
            key="AAPL",
            value={"price": 150.0},
            created_at=datetime.now() - timedelta(seconds=age),
            expires_at=datetime.now() + timedelta(seconds=total_ttl - age),
            priority=CachePriority.NORMAL
        )

        async def failing_refresh():
            raise ValueError("Refresh failed!")

        # Should not raise
        result = await manager.get_with_refresh("quotes", "AAPL", failing_refresh)

        # Original value returned
        assert result == {"price": 150.0}

        # Wait for background task
        await asyncio.sleep(0.1)

        # Original value should still be there
        assert manager.get("quotes", "AAPL") == {"price": 150.0}

    @pytest.mark.asyncio
    async def test_background_refresh_none_result_not_cached(self):
        """Background refresh returning None should not update cache."""
        manager = CacheManager()

        # Set up entry that needs refresh
        quotes = manager.get_cache("quotes")
        total_ttl = 60
        age = total_ttl * 0.85
        quotes._entries["AAPL"] = CacheEntry(
            key="AAPL",
            value={"price": 150.0},
            created_at=datetime.now() - timedelta(seconds=age),
            expires_at=datetime.now() + timedelta(seconds=total_ttl - age),
            priority=CachePriority.NORMAL
        )

        async def refresh_returns_none():
            return None

        await manager.get_with_refresh("quotes", "AAPL", refresh_returns_none)

        # Wait for background task
        await asyncio.sleep(0.1)

        # Original value should still be there (None not cached)
        assert manager.get("quotes", "AAPL") == {"price": 150.0}


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_cache_operations(self):
        """Operations on empty cache should not crash."""
        cache = BaseCache(CachePolicy(ttl_seconds=300, max_entries=100), "test")

        assert cache.get("nonexistent") is None
        assert cache.remove("nonexistent") is False
        assert cache.clear() == 0
        assert cache.cleanup_expired() == 0
        assert not cache.contains("nonexistent")
        assert cache.get_keys() == []
        assert len(cache) == 0

    def test_cache_with_none_values(self):
        """Cache should handle None values correctly."""
        cache = BaseCache(CachePolicy(ttl_seconds=300, max_entries=100), "test")

        cache.set("key", None)

        # None is a valid cached value
        assert cache.contains("key")
        result = cache.get("key")
        # get returns None for both missing and None-valued entries
        # This is expected behavior - we can use contains to check if key exists
        assert result is None

    def test_cache_with_complex_keys(self):
        """Cache should handle various key formats."""
        cache = BaseCache(CachePolicy(ttl_seconds=300, max_entries=100), "test")

        keys = [
            "simple",
            "with:colon",
            "with-dash",
            "with_underscore",
            "with.dot",
            "WITH_CAPS",
            "123numeric",
            "mixed123_key-test",
        ]

        for key in keys:
            cache.set(key, f"value_{key}")

        for key in keys:
            assert cache.get(key) == f"value_{key}"

    def test_cache_with_large_values(self):
        """Cache should handle large values."""
        cache = BaseCache(CachePolicy(ttl_seconds=300, max_entries=100), "test")

        large_value = {"data": "x" * 1_000_000}  # 1MB string

        cache.set("large_key", large_value)

        result = cache.get("large_key")
        assert result == large_value

    def test_max_entries_zero(self):
        """Cache with max_entries=0 should still work (evict everything)."""
        # This is an edge case - max_entries=0 is unusual but shouldn't crash
        cache = BaseCache(CachePolicy(ttl_seconds=300, max_entries=0), "test")

        # Setting should trigger eviction immediately
        cache.set("key1", "value1")

        # Behavior depends on implementation - entry may or may not exist
        # Just verify no crash
        _ = cache.get("key1")

    def test_ttl_zero(self):
        """Cache with ttl=0 should expire immediately."""
        cache = BaseCache(CachePolicy(ttl_seconds=0, max_entries=100), "test")

        cache.set("key1", "value1")

        # Entry should be expired immediately (or very quickly)
        time.sleep(0.001)
        result = cache.get("key1")
        assert result is None

    def test_metrics_overflow_protection(self):
        """Metrics counters should handle many operations."""
        cache = BaseCache(CachePolicy(ttl_seconds=300, max_entries=100), "test")

        cache.set("key", "value")

        # Many operations
        for _ in range(10000):
            cache.get("key")

        assert cache.metrics.hits == 10000


# =============================================================================
# Integration Tests
# =============================================================================

class TestCacheManagerIntegration:
    """Integration tests for CacheManager."""

    def test_full_lifecycle(self):
        """Test complete cache lifecycle."""
        manager = CacheManager()

        # Set values
        manager.set("quotes", "AAPL", {"price": 150.0})
        manager.set("quotes", "MSFT", {"price": 300.0})
        manager.set("historical", "AAPL:90", [100, 110, 120])

        # Get values
        assert manager.get("quotes", "AAPL") == {"price": 150.0}
        assert manager.get("historical", "AAPL:90") == [100, 110, 120]

        # Check stats
        stats = manager.get_unified_stats()
        assert stats["summary"]["total_entries"] == 3
        assert stats["summary"]["total_hits"] == 2

        # Invalidate one cache
        manager.invalidate("quotes")
        assert len(manager.get_cache("quotes")) == 0
        assert len(manager.get_cache("historical")) == 1

        # Clear all
        manager.clear_all()
        assert len(manager.get_cache("historical")) == 0

    def test_multi_cache_operations(self):
        """Test operations across multiple caches."""
        manager = CacheManager()

        # Populate multiple caches
        for i in range(10):
            manager.set("quotes", f"SYM{i}", {"price": i * 10.0})
            manager.set("historical", f"SYM{i}:90", list(range(i)))
            manager.set("earnings", f"SYM{i}", {"date": f"2024-01-{i+1:02d}"})

        # Verify
        stats = manager.get_unified_stats()
        assert stats["summary"]["total_entries"] == 30

        # Cascade invalidation
        manager.invalidate("earnings", cascade=True)

        # Earnings and scans should be empty
        assert len(manager.get_cache("earnings")) == 0
        assert len(manager.get_cache("scans")) == 0

        # Others should remain
        assert len(manager.get_cache("quotes")) == 10
        assert len(manager.get_cache("historical")) == 10

    def test_health_monitoring(self):
        """Test health monitoring functionality."""
        manager = CacheManager()

        # Initial health should be healthy
        health = manager.get_health()
        assert health["status"] == "healthy"

        # Add some data and generate some activity
        quotes = manager.get_cache("quotes")
        for i in range(50):
            quotes.set(f"key{i}", f"value{i}")

        # Generate mixed hit/miss
        for i in range(30):
            quotes.get(f"key{i}")  # hits
        for i in range(20):
            quotes.get(f"nonexistent{i}")  # misses

        health = manager.get_health()
        assert "caches" in health
        assert "quotes" in health["caches"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
