# OptionPlay - Cache Manager Tests
# ==================================
"""
Tests für den unified CacheManager.

Testet:
- CachePolicy und CacheEntry
- BaseCache Grundfunktionen
- CacheManager Koordination
- Cascading Invalidation
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import time

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


class TestCachePolicy:
    """Tests für CachePolicy."""

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


class TestCacheEntry:
    """Tests für CacheEntry."""

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


class TestBaseCache:
    """Tests für BaseCache."""

    def _create_cache(self, name="test", ttl=300, max_entries=100):
        """Helper to create a cache with policy."""
        policy = CachePolicy(ttl_seconds=ttl, max_entries=max_entries)
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

    def test_contains(self):
        """contains should check key existence."""
        cache = self._create_cache()

        cache.set("key1", "value1")

        assert cache.contains("key1")
        assert not cache.contains("nonexistent")

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

    def test_get_keys(self):
        """get_keys should return all keys."""
        cache = self._create_cache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        keys = cache.get_keys()

        assert "key1" in keys
        assert "key2" in keys

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


class TestCacheManager:
    """Tests für CacheManager Koordination."""

    def test_default_caches_created(self):
        """CacheManager should create default caches."""
        manager = CacheManager()

        # Should have default caches
        assert "historical" in manager._caches
        assert "quotes" in manager._caches
        assert "earnings" in manager._caches

    def test_get_cache(self):
        """get_cache should return cache by name."""
        manager = CacheManager()

        cache = manager.get_cache("quotes")

        assert cache is not None
        assert isinstance(cache, BaseCache)

    def test_get_cache_nonexistent(self):
        """get_cache should raise KeyError for nonexistent cache."""
        manager = CacheManager()

        with pytest.raises(KeyError):
            manager.get_cache("nonexistent")

    def test_get_value(self):
        """get should return value from cache."""
        manager = CacheManager()
        manager.set("quotes", "AAPL", {"price": 150.0})

        result = manager.get("quotes", "AAPL")

        assert result == {"price": 150.0}

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

    def test_clear_all(self):
        """clear_all should clear all caches."""
        manager = CacheManager()
        manager.get_cache("quotes").set("AAPL", {"price": 150.0})
        manager.get_cache("historical").set("AAPL:90", [100, 110, 120])

        manager.clear_all()

        assert len(manager.get_cache("quotes")) == 0
        assert len(manager.get_cache("historical")) == 0

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

    def test_stats(self):
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


class TestCacheManagerSingleton:
    """Tests für CacheManager Singleton."""

    def test_get_cache_manager(self):
        """get_cache_manager should return singleton."""
        reset_cache_manager()

        manager1 = get_cache_manager()
        manager2 = get_cache_manager()

        assert manager1 is manager2

    def test_reset_cache_manager(self):
        """reset_cache_manager should create new instance."""
        manager1 = get_cache_manager()
        reset_cache_manager()
        manager2 = get_cache_manager()

        assert manager1 is not manager2


class TestCacheManagerDependencies:
    """Tests für Dependency-Management."""

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


class TestCachePriority:
    """Tests für CachePriority."""

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
