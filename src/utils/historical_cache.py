# OptionPlay - Historical Data Cache
# ====================================
# Cache für historische Kursdaten mit TTL (Time-To-Live)
#
# Features:
# - Automatische Invalidierung nach TTL
# - Thread-safe Implementation
# - Speicher-Limits
# - Cache-Statistiken
#
# Verwendung:
#     from utils.historical_cache import get_historical_cache
#
#     cache = get_historical_cache()
#     
#     # Daten cachen
#     cache.set("AAPL", data, days=260)
#     
#     # Daten abrufen
#     data = cache.get("AAPL", days=260)

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# CACHE ENTRY
# =============================================================================

@dataclass
class CacheEntry:
    """Einzelner Cache-Eintrag mit Metadaten."""
    data: Any
    created_at: datetime
    expires_at: datetime
    days: int  # Anzahl Tage der historischen Daten
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    
    def is_expired(self) -> bool:
        """Prüft ob der Eintrag abgelaufen ist."""
        return datetime.now() > self.expires_at
    
    def touch(self) -> None:
        """Aktualisiert Zugriffszähler und -zeit."""
        self.access_count += 1
        self.last_accessed = datetime.now()


# =============================================================================
# HISTORICAL DATA CACHE
# =============================================================================

class HistoricalDataCache:
    """
    Cache für historische Kursdaten.
    
    Features:
    - TTL-basierte Invalidierung
    - Thread-safe mit Lock
    - Max-Entries Limit
    - LRU-ähnliche Eviction
    
    Verwendung:
        cache = HistoricalDataCache(ttl_seconds=300, max_entries=500)
        
        # Speichern
        cache.set("AAPL", historical_data, days=260)
        
        # Abrufen
        data = cache.get("AAPL", days=260)  # None wenn nicht vorhanden oder expired
        
        # Prüfen
        if cache.has("AAPL", days=260):
            ...
    """
    
    # Standard TTL: 5 Minuten
    DEFAULT_TTL_SECONDS = 300
    
    # Max Einträge bevor Cleanup
    DEFAULT_MAX_ENTRIES = 500
    
    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES
    ):
        """
        Initialisiert den Cache.
        
        Args:
            ttl_seconds: Time-to-Live in Sekunden (default: 300 = 5 Min)
            max_entries: Maximale Anzahl Einträge (default: 500)
        """
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        
        # Statistiken
        self._hits = 0
        self._misses = 0
        self._evictions = 0
    
    def _make_key(self, symbol: str, days: int) -> str:
        """Erstellt Cache-Key aus Symbol und Tagen."""
        return f"{symbol.upper()}:{days}"
    
    def _cleanup_expired(self) -> int:
        """
        Entfernt abgelaufene Einträge.
        
        Returns:
            Anzahl entfernter Einträge
        """
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self._cache[key]
            self._evictions += 1
        
        if expired_keys:
            logger.debug(f"Cache cleanup: {len(expired_keys)} expired entries removed")
        
        return len(expired_keys)
    
    def _evict_lru(self, count: int = 1) -> int:
        """
        Entfernt die am längsten nicht genutzten Einträge.
        
        Args:
            count: Anzahl zu entfernender Einträge
            
        Returns:
            Anzahl tatsächlich entfernter Einträge
        """
        if not self._cache:
            return 0
        
        # Nach letztem Zugriff sortieren
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].last_accessed
        )
        
        removed = 0
        for key, _ in sorted_entries[:count]:
            del self._cache[key]
            self._evictions += 1
            removed += 1
        
        if removed:
            logger.debug(f"Cache LRU eviction: {removed} entries removed")
        
        return removed
    
    def get(
        self,
        symbol: str,
        days: int,
        min_days: Optional[int] = None
    ) -> Optional[Any]:
        """
        Ruft gecachte Daten ab.
        
        Args:
            symbol: Ticker-Symbol
            days: Anzahl Tage der historischen Daten
            min_days: Mindestanzahl Tage (akzeptiert Cache mit mehr Tagen)
            
        Returns:
            Gecachte Daten oder None wenn nicht vorhanden/expired
        """
        with self._lock:
            key = self._make_key(symbol, days)
            entry = self._cache.get(key)
            
            # Direkter Match
            if entry and not entry.is_expired():
                entry.touch()
                self._hits += 1
                logger.debug(f"Cache HIT: {key}")
                return entry.data
            
            # Wenn min_days angegeben, suche nach größerem Cache
            if min_days:
                for cache_days in [260, 365, 180, 120, 90, 60, 30]:
                    if cache_days >= min_days:
                        alt_key = self._make_key(symbol, cache_days)
                        alt_entry = self._cache.get(alt_key)
                        if alt_entry and not alt_entry.is_expired():
                            alt_entry.touch()
                            self._hits += 1
                            logger.debug(f"Cache HIT (alt): {alt_key} for {key}")
                            return alt_entry.data
            
            self._misses += 1
            logger.debug(f"Cache MISS: {key}")
            return None
    
    def set(
        self,
        symbol: str,
        data: Any,
        days: int,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Speichert Daten im Cache.
        
        Args:
            symbol: Ticker-Symbol
            data: Zu cachende Daten
            days: Anzahl Tage der historischen Daten
            ttl_seconds: Optionale TTL (überschreibt Default)
        """
        with self._lock:
            # Cleanup wenn Cache voll
            if len(self._cache) >= self._max_entries:
                self._cleanup_expired()
                
                # Wenn immer noch voll, LRU Eviction
                if len(self._cache) >= self._max_entries:
                    self._evict_lru(count=max(1, self._max_entries // 10))
            
            key = self._make_key(symbol, days)
            ttl = ttl_seconds or self._ttl_seconds
            now = datetime.now()
            
            self._cache[key] = CacheEntry(
                data=data,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl),
                days=days
            )
            
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
    
    def has(self, symbol: str, days: int) -> bool:
        """
        Prüft ob gültige Daten im Cache vorhanden sind.
        
        Args:
            symbol: Ticker-Symbol
            days: Anzahl Tage
            
        Returns:
            True wenn gültige Daten vorhanden
        """
        with self._lock:
            key = self._make_key(symbol, days)
            entry = self._cache.get(key)
            return entry is not None and not entry.is_expired()
    
    def invalidate(self, symbol: str, days: Optional[int] = None) -> int:
        """
        Invalidiert Cache-Einträge für ein Symbol.
        
        Args:
            symbol: Ticker-Symbol
            days: Optional - nur bestimmte Tage invalidieren
            
        Returns:
            Anzahl invalidierter Einträge
        """
        with self._lock:
            if days is not None:
                key = self._make_key(symbol, days)
                if key in self._cache:
                    del self._cache[key]
                    return 1
                return 0
            
            # Alle Einträge für Symbol entfernen
            prefix = f"{symbol.upper()}:"
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(prefix)]
            
            for key in keys_to_remove:
                del self._cache[key]
            
            return len(keys_to_remove)
    
    def clear(self) -> int:
        """
        Leert den gesamten Cache.
        
        Returns:
            Anzahl entfernter Einträge
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cache cleared: {count} entries removed")
            return count
    
    def stats(self) -> Dict[str, Any]:
        """
        Gibt Cache-Statistiken zurück.
        
        Returns:
            Dict mit Statistiken
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
            
            # Berechne durchschnittliches Alter
            ages = []
            for entry in self._cache.values():
                if not entry.is_expired():
                    age = (datetime.now() - entry.created_at).total_seconds()
                    ages.append(age)
            
            avg_age = sum(ages) / len(ages) if ages else 0
            
            return {
                "entries": len(self._cache),
                "max_entries": self._max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_percent": round(hit_rate, 1),
                "evictions": self._evictions,
                "ttl_seconds": self._ttl_seconds,
                "avg_entry_age_seconds": round(avg_age, 1),
            }
    
    def get_cached_symbols(self) -> List[str]:
        """
        Gibt Liste der gecachten Symbole zurück.
        
        Returns:
            Liste der Symbole (ohne Duplikate)
        """
        with self._lock:
            symbols = set()
            for key in self._cache.keys():
                symbol = key.split(":")[0]
                symbols.add(symbol)
            return sorted(list(symbols))


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_cache_instance: Optional[HistoricalDataCache] = None


def get_historical_cache(
    ttl_seconds: int = HistoricalDataCache.DEFAULT_TTL_SECONDS,
    max_entries: int = HistoricalDataCache.DEFAULT_MAX_ENTRIES
) -> HistoricalDataCache:
    """
    Gibt die globale Cache-Instanz zurück.
    
    Erstellt bei Bedarf eine neue Instanz.
    
    Args:
        ttl_seconds: TTL für neue Instanz
        max_entries: Max Entries für neue Instanz
        
    Returns:
        HistoricalDataCache Instanz
    """
    global _cache_instance
    
    if _cache_instance is None:
        _cache_instance = HistoricalDataCache(
            ttl_seconds=ttl_seconds,
            max_entries=max_entries
        )
        logger.info(f"Historical cache initialized (TTL: {ttl_seconds}s, Max: {max_entries})")
    
    return _cache_instance


def reset_historical_cache() -> None:
    """Setzt den globalen Cache zurück (für Tests)."""
    global _cache_instance
    if _cache_instance:
        _cache_instance.clear()
    _cache_instance = None
