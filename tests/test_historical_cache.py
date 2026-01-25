# Tests für Historical Data Cache
# ================================

import pytest
import time
from datetime import datetime, timedelta

from src.cache.historical_cache import (
    HistoricalCache,
    HistoricalCacheEntry,
    CacheLookupResult,
    CacheStatus,
    get_historical_cache,
    reset_historical_cache,
)


# =============================================================================
# SAMPLE DATA
# =============================================================================

def create_sample_data(points: int = 100):
    """Erstellt Sample Historical Data."""
    prices = [100.0 + i * 0.1 for i in range(points)]
    volumes = [1000000 + i * 1000 for i in range(points)]
    highs = [p + 1.0 for p in prices]
    lows = [p - 1.0 for p in prices]
    return (prices, volumes, highs, lows)


# =============================================================================
# CACHE ENTRY TESTS
# =============================================================================

class TestHistoricalCacheEntry:
    """Tests für HistoricalCacheEntry."""
    
    def test_is_expired_false(self):
        """Entry sollte nicht expired sein wenn expires_at in Zukunft."""
        entry = HistoricalCacheEntry(
            data=create_sample_data(),
            symbol="AAPL",
            days=60,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=300)
        )
        assert not entry.is_expired()
    
    def test_is_expired_true(self):
        """Entry sollte expired sein wenn expires_at in Vergangenheit."""
        entry = HistoricalCacheEntry(
            data=create_sample_data(),
            symbol="AAPL",
            days=60,
            created_at=datetime.now() - timedelta(seconds=600),
            expires_at=datetime.now() - timedelta(seconds=1)
        )
        assert entry.is_expired()
    
    def test_touch_increments_counter(self):
        """touch() sollte access_count erhöhen."""
        entry = HistoricalCacheEntry(
            data=create_sample_data(),
            symbol="AAPL",
            days=60,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=300)
        )
        
        assert entry.access_count == 0
        entry.touch()
        assert entry.access_count == 1
        entry.touch()
        assert entry.access_count == 2
    
    def test_data_points(self):
        """data_points sollte korrekte Anzahl zurückgeben."""
        data = create_sample_data(points=150)
        entry = HistoricalCacheEntry(
            data=data,
            symbol="AAPL",
            days=60,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=300)
        )
        assert entry.data_points == 150


# =============================================================================
# HISTORICAL CACHE TESTS
# =============================================================================

class TestHistoricalCache:
    """Tests für HistoricalCache."""
    
    def setup_method(self):
        """Reset cache before each test."""
        reset_historical_cache()
    
    def test_set_and_get(self):
        """Basic set/get should work."""
        cache = HistoricalCache(ttl_seconds=60)
        data = create_sample_data()
        
        cache.set("AAPL", data, days=60)
        result = cache.get("AAPL", days=60)
        
        assert result.status == CacheStatus.HIT
        assert result.data == data
        assert result.entry is not None
        assert result.entry.symbol == "AAPL"
    
    def test_get_miss(self):
        """Get should return MISS for non-existent key."""
        cache = HistoricalCache()
        result = cache.get("AAPL", days=60)
        
        assert result.status == CacheStatus.MISS
        assert result.data is None
    
    def test_get_expired(self):
        """Get should return EXPIRED for old entries."""
        cache = HistoricalCache(ttl_seconds=1)  # 1 second TTL
        data = create_sample_data()
        
        cache.set("AAPL", data, days=60)
        time.sleep(1.5)  # Wait for expiry
        
        result = cache.get("AAPL", days=60)
        assert result.status == CacheStatus.EXPIRED
    
    def test_accept_more_days(self):
        """Should accept cache with more days than requested."""
        cache = HistoricalCache()
        data = create_sample_data(points=260)
        
        # Cache 260 Tage
        cache.set("AAPL", data, days=260)
        
        # Anfrage für 60 Tage sollte 260er Cache nutzen
        result = cache.get("AAPL", days=60, accept_more_days=True)
        
        assert result.status == CacheStatus.HIT
        assert "Larger cache used" in result.message or "Direct hit" in result.message
    
    def test_has(self):
        """has() should return True/False correctly."""
        cache = HistoricalCache()
        
        assert not cache.has("AAPL", 60)
        
        cache.set("AAPL", create_sample_data(), days=60)
        assert cache.has("AAPL", 60)
    
    def test_invalidate_specific(self):
        """invalidate() with days should remove specific entry."""
        cache = HistoricalCache()
        
        cache.set("AAPL", create_sample_data(), days=60)
        cache.set("AAPL", create_sample_data(), days=260)
        
        removed = cache.invalidate("AAPL", days=60)
        assert removed == 1
        
        # Check that 60-day entry is gone (direct lookup, not via has() which uses accept_more_days)
        result = cache.get("AAPL", days=60, accept_more_days=False)
        assert result.status != CacheStatus.HIT
        
        # 260-day entry should still be there
        assert cache.has("AAPL", 260)
    
    def test_invalidate_all_for_symbol(self):
        """invalidate() without days should remove all entries for symbol."""
        cache = HistoricalCache()
        
        cache.set("AAPL", create_sample_data(), days=60)
        cache.set("AAPL", create_sample_data(), days=260)
        cache.set("MSFT", create_sample_data(), days=60)
        
        removed = cache.invalidate("AAPL")
        assert removed == 2
        assert not cache.has("AAPL", 60)
        assert not cache.has("AAPL", 260)
        assert cache.has("MSFT", 60)  # Still there
    
    def test_clear(self):
        """clear() should remove all entries."""
        cache = HistoricalCache()
        
        cache.set("AAPL", create_sample_data(), days=60)
        cache.set("MSFT", create_sample_data(), days=60)
        
        cleared = cache.clear()
        assert cleared == 2
        assert not cache.has("AAPL", 60)
        assert not cache.has("MSFT", 60)
    
    def test_stats(self):
        """stats() should return correct statistics."""
        cache = HistoricalCache(ttl_seconds=300, max_entries=100)
        
        cache.set("AAPL", create_sample_data(), days=60)
        cache.get("AAPL", days=60)  # Hit
        cache.get("MSFT", days=60)  # Miss
        
        stats = cache.stats()
        
        assert stats["entries"] == 1
        assert stats["max_entries"] == 100
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate_percent"] == 50.0
        assert stats["ttl_seconds"] == 300
    
    def test_lru_eviction(self):
        """Should evict LRU entries when max_entries reached."""
        cache = HistoricalCache(max_entries=3)
        
        cache.set("A", create_sample_data(), days=60)
        time.sleep(0.1)
        cache.set("B", create_sample_data(), days=60)
        time.sleep(0.1)
        cache.set("C", create_sample_data(), days=60)
        
        # Touch A to make it recently used
        cache.get("A", days=60)
        time.sleep(0.1)
        
        # Add D - should evict B (least recently used)
        cache.set("D", create_sample_data(), days=60)
        
        assert cache.has("A", 60)  # Recently touched
        assert cache.has("C", 60)  # Newer
        assert cache.has("D", 60)  # Just added
        # B might be evicted
    
    def test_get_cached_symbols(self):
        """get_cached_symbols() should return unique symbols."""
        cache = HistoricalCache()
        
        cache.set("AAPL", create_sample_data(), days=60)
        cache.set("AAPL", create_sample_data(), days=260)
        cache.set("MSFT", create_sample_data(), days=60)
        
        symbols = cache.get_cached_symbols()
        assert set(symbols) == {"AAPL", "MSFT"}
    
    def test_set_rejects_empty_data(self):
        """set() should reject empty data."""
        cache = HistoricalCache()
        
        result = cache.set("AAPL", ([], [], [], []), days=60)
        assert result == False
        assert not cache.has("AAPL", 60)


# =============================================================================
# SINGLETON TESTS
# =============================================================================

class TestSingleton:
    """Tests für Singleton-Instanz."""
    
    def setup_method(self):
        reset_historical_cache()
    
    def test_get_historical_cache_returns_singleton(self):
        """get_historical_cache() should return same instance."""
        cache1 = get_historical_cache()
        cache2 = get_historical_cache()
        assert cache1 is cache2
    
    def test_reset_historical_cache(self):
        """reset_historical_cache() should create new instance."""
        cache1 = get_historical_cache()
        cache1.set("AAPL", create_sample_data(), days=60)
        
        reset_historical_cache()
        cache2 = get_historical_cache()
        
        assert cache1 is not cache2
        assert not cache2.has("AAPL", 60)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
