# OptionPlay - Unified Cache Manager
# ====================================
"""
Zentralisierte Cache-Verwaltung mit koordinierter Invalidierung.

Ersetzt verstreute Cache-Instanzen durch einen einheitlichen Manager:
- Koordinierte Invalidierung über abhängige Caches
- Einheitliche Statistiken
- Proaktiver Refresh bei drohendem Expire
- Event-basierte Invalidierung

Verwendung:
    from src.cache import CacheManager

    manager = CacheManager.create_default()

    # Get mit Auto-Refresh
    data = await manager.get("historical", "AAPL:90")

    # Koordinierte Invalidierung
    await manager.invalidate("earnings", "AAPL")  # Invalidiert auch dependent caches

    # Einheitliche Stats
    stats = manager.get_unified_stats()
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from enum import Enum
import threading

try:
    from src.state.server_state import CacheMetrics
except ImportError:
    from state.server_state import CacheMetrics

logger = logging.getLogger(__name__)


class CachePriority(Enum):
    """Cache-Priorität für Eviction-Entscheidungen."""
    LOW = 1       # Kann jederzeit evicted werden
    NORMAL = 2    # Standard
    HIGH = 3      # Behalte länger
    CRITICAL = 4  # Evict nur wenn nötig


@dataclass
class CachePolicy:
    """
    Einheitliche Cache-Konfiguration.

    Attributes:
        ttl_seconds: Time-to-live in Sekunden
        max_entries: Maximale Anzahl Einträge
        refresh_at_pct: Bei X% des TTL proaktiv refreshen (0.0-1.0)
        fallback_enabled: Fallback zu stale data wenn Refresh fehlschlägt
        priority: Eviction-Priorität
    """
    ttl_seconds: int
    max_entries: int
    refresh_at_pct: float = 0.8  # Bei 80% TTL proaktiv refreshen
    fallback_enabled: bool = True
    priority: CachePriority = CachePriority.NORMAL

    @property
    def refresh_threshold_seconds(self) -> float:
        """Sekunden nach denen Refresh gestartet wird."""
        return self.ttl_seconds * self.refresh_at_pct


@dataclass
class CacheEntry:
    """
    Ein Cache-Eintrag mit Metadaten.

    Attributes:
        key: Cache-Key
        value: Cached Value
        created_at: Erstellungszeit
        expires_at: Ablaufzeit
        access_count: Anzahl Zugriffe
        last_accessed_at: Letzter Zugriff
        priority: Eviction-Priorität
    """
    key: str
    value: Any
    created_at: datetime
    expires_at: datetime
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    priority: CachePriority = CachePriority.NORMAL

    @property
    def is_expired(self) -> bool:
        """Prüft ob Eintrag abgelaufen ist."""
        return datetime.now() > self.expires_at

    @property
    def age_seconds(self) -> float:
        """Alter des Eintrags in Sekunden."""
        return (datetime.now() - self.created_at).total_seconds()

    @property
    def time_to_expiry_seconds(self) -> float:
        """Verbleibende Zeit bis Ablauf in Sekunden."""
        remaining = (self.expires_at - datetime.now()).total_seconds()
        return max(0, remaining)

    def should_refresh(self, threshold_pct: float) -> bool:
        """Prüft ob proaktiver Refresh nötig ist."""
        total_ttl = (self.expires_at - self.created_at).total_seconds()
        threshold = total_ttl * threshold_pct
        return self.age_seconds >= threshold

    def touch(self) -> None:
        """Markiert als zugegriffen (für LRU)."""
        self.access_count += 1
        self.last_accessed_at = datetime.now()


class BaseCache:
    """
    Basis-Klasse für einzelne Cache-Instanzen.

    Implementiert:
    - TTL-basierte Expiration
    - LRU Eviction
    - Thread-Safety mit RLock
    - Statistiken via CacheMetrics
    """

    def __init__(self, policy: CachePolicy, name: str):
        """
        Initialisiert Cache mit Policy.

        Args:
            policy: Cache-Konfiguration
            name: Cache-Name für Logging/Stats
        """
        self._policy = policy
        self._name = name
        self._entries: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._metrics = CacheMetrics(
            name=name,
            ttl_seconds=policy.ttl_seconds,
            max_entries=policy.max_entries
        )

    @property
    def name(self) -> str:
        """Cache-Name."""
        return self._name

    @property
    def metrics(self) -> CacheMetrics:
        """Cache-Statistiken."""
        return self._metrics

    def __len__(self) -> int:
        """Anzahl Einträge."""
        with self._lock:
            return len(self._entries)

    def get(self, key: str) -> Optional[Any]:
        """
        Holt Wert aus Cache.

        Args:
            key: Cache-Key

        Returns:
            Cached value oder None wenn nicht gefunden/expired
        """
        with self._lock:
            entry = self._entries.get(key)

            if entry is None:
                self._metrics.record_miss()
                return None

            if entry.is_expired:
                # Expired - entfernen und miss zählen
                del self._entries[key]
                self._metrics.record_miss()
                self._update_entry_count()
                return None

            # Hit
            entry.touch()
            self._metrics.record_hit()
            return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
        priority: Optional[CachePriority] = None
    ) -> None:
        """
        Setzt Wert im Cache.

        Args:
            key: Cache-Key
            value: Zu cachender Wert
            ttl_seconds: Optional custom TTL (sonst policy default)
            priority: Optional custom Priority (sonst policy default)
        """
        ttl = ttl_seconds or self._policy.ttl_seconds
        prio = priority or self._policy.priority

        with self._lock:
            # Evict wenn nötig
            if len(self._entries) >= self._policy.max_entries:
                self._evict_one()

            now = datetime.now()
            self._entries[key] = CacheEntry(
                key=key,
                value=value,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl),
                priority=prio
            )
            self._update_entry_count()

    def remove(self, key: str) -> bool:
        """
        Entfernt Eintrag aus Cache.

        Args:
            key: Cache-Key

        Returns:
            True wenn Eintrag existierte und entfernt wurde
        """
        with self._lock:
            if key in self._entries:
                del self._entries[key]
                self._update_entry_count()
                return True
            return False

    def clear(self) -> int:
        """
        Leert den gesamten Cache.

        Returns:
            Anzahl entfernter Einträge
        """
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            self._update_entry_count()
            return count

    def contains(self, key: str) -> bool:
        """Prüft ob Key im Cache ist (ohne Expiration-Check)."""
        with self._lock:
            return key in self._entries

    def should_refresh(self, key: str) -> bool:
        """Prüft ob proaktiver Refresh empfohlen wird."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            return entry.should_refresh(self._policy.refresh_at_pct)

    def get_keys(self) -> List[str]:
        """Gibt alle Keys zurück."""
        with self._lock:
            return list(self._entries.keys())

    def cleanup_expired(self) -> int:
        """
        Entfernt alle abgelaufenen Einträge.

        Returns:
            Anzahl entfernter Einträge
        """
        with self._lock:
            expired_keys = [
                key for key, entry in self._entries.items()
                if entry.is_expired
            ]
            for key in expired_keys:
                del self._entries[key]
            self._update_entry_count()
            return len(expired_keys)

    def _evict_one(self) -> Optional[str]:
        """
        Evicted einen Eintrag (LRU mit Priority).

        Returns:
            Evicted key oder None wenn leer
        """
        if not self._entries:
            return None

        # Sortiere nach: Priority (niedrig zuerst), dann last_accessed (älteste zuerst)
        candidates = sorted(
            self._entries.items(),
            key=lambda x: (
                x[1].priority.value,
                x[1].last_accessed_at or x[1].created_at
            )
        )

        if candidates:
            evict_key = candidates[0][0]
            del self._entries[evict_key]
            self._metrics.record_eviction()
            logger.debug(f"Evicted {evict_key} from cache {self._name}")
            return evict_key

        return None

    def _update_entry_count(self) -> None:
        """Aktualisiert Entry-Count in Metrics."""
        self._metrics.set_current_entries(len(self._entries))


class CacheManager:
    """
    Zentralisierte Cache-Verwaltung.

    Features:
    - Verwaltet alle Caches an einem Ort
    - Koordinierte Invalidierung über Abhängigkeiten
    - Einheitliche Statistiken
    - Proaktiver Background-Refresh

    Cache Dependencies:
        earnings → [scans]          # Earnings ändern sich → Scans invalidieren
        iv → [scans]                # IV ändert sich → Scans invalidieren
        historical → [quotes, scans] # Neue Preise → alles invalidieren
    """

    # Standard Cache Policies
    DEFAULT_POLICIES = {
        "historical": CachePolicy(ttl_seconds=900, max_entries=2000, priority=CachePriority.HIGH),
        "quotes": CachePolicy(ttl_seconds=60, max_entries=2000, priority=CachePriority.NORMAL),
        "scans": CachePolicy(ttl_seconds=1800, max_entries=200, priority=CachePriority.NORMAL),
        "earnings": CachePolicy(ttl_seconds=2_592_000, max_entries=5000, priority=CachePriority.HIGH),  # 30 Tage
        "iv": CachePolicy(ttl_seconds=300, max_entries=2000, priority=CachePriority.NORMAL),
        "options": CachePolicy(ttl_seconds=120, max_entries=500, priority=CachePriority.LOW),
    }

    # Cache Dependencies für koordinierte Invalidierung
    DEFAULT_DEPENDENCIES = {
        "earnings": ["scans"],
        "iv": ["scans"],
        "historical": ["quotes", "scans"],
    }

    def __init__(
        self,
        policies: Optional[Dict[str, CachePolicy]] = None,
        dependencies: Optional[Dict[str, List[str]]] = None
    ):
        """
        Initialisiert CacheManager.

        Args:
            policies: Custom Policies (merged mit Defaults)
            dependencies: Custom Dependencies (merged mit Defaults)
        """
        # Merge policies
        self._policies = {**self.DEFAULT_POLICIES}
        if policies:
            self._policies.update(policies)

        # Merge dependencies
        self._dependencies = {**self.DEFAULT_DEPENDENCIES}
        if dependencies:
            self._dependencies.update(dependencies)

        # Create caches
        self._caches: Dict[str, BaseCache] = {}
        for name, policy in self._policies.items():
            self._caches[name] = BaseCache(policy, name)

        # Background refresh tracking
        self._refresh_in_progress: Set[str] = set()
        self._refresh_lock = threading.Lock()
        self._refresh_failures: Dict[str, int] = {}
        self._refresh_circuit_open: Dict[str, float] = {}  # key → circuit-open-until timestamp

        logger.info(f"CacheManager initialized with {len(self._caches)} caches")

    @classmethod
    def create_default(cls) -> "CacheManager":
        """Factory für Standard-Konfiguration."""
        return cls()

    @classmethod
    def create_for_testing(
        cls,
        short_ttl: bool = True
    ) -> "CacheManager":
        """
        Factory für Test-Konfiguration.

        Args:
            short_ttl: Wenn True, verwende kurze TTLs für schnellere Tests
        """
        if short_ttl:
            policies = {
                name: CachePolicy(
                    ttl_seconds=1,  # 1 Sekunde für Tests
                    max_entries=policy.max_entries,
                    refresh_at_pct=0.5,
                    priority=policy.priority
                )
                for name, policy in cls.DEFAULT_POLICIES.items()
            }
            return cls(policies=policies)
        return cls()

    def get_cache(self, name: str) -> BaseCache:
        """
        Gibt einzelnen Cache zurück.

        Args:
            name: Cache-Name

        Returns:
            BaseCache Instanz

        Raises:
            KeyError: Wenn Cache nicht existiert
        """
        if name not in self._caches:
            raise KeyError(f"Unknown cache: {name}. Available: {list(self._caches.keys())}")
        return self._caches[name]

    def get(self, cache_name: str, key: str) -> Optional[Any]:
        """
        Holt Wert aus benanntem Cache.

        Args:
            cache_name: Cache-Name
            key: Cache-Key

        Returns:
            Cached value oder None
        """
        cache = self.get_cache(cache_name)
        return cache.get(key)

    def set(
        self,
        cache_name: str,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Setzt Wert in benanntem Cache.

        Args:
            cache_name: Cache-Name
            key: Cache-Key
            value: Zu cachender Wert
            ttl_seconds: Optional custom TTL
        """
        cache = self.get_cache(cache_name)
        cache.set(key, value, ttl_seconds)

    def remove(self, cache_name: str, key: str) -> bool:
        """Entfernt einzelnen Eintrag."""
        cache = self.get_cache(cache_name)
        return cache.remove(key)

    def should_refresh(self, cache_name: str, key: str) -> bool:
        """Prüft ob proaktiver Refresh empfohlen wird."""
        cache = self.get_cache(cache_name)
        return cache.should_refresh(key)

    async def get_with_refresh(
        self,
        cache_name: str,
        key: str,
        refresh_func: Callable[[], Coroutine[Any, Any, Any]]
    ) -> Optional[Any]:
        """
        Holt Wert und startet Background-Refresh wenn nötig.

        Args:
            cache_name: Cache-Name
            key: Cache-Key
            refresh_func: Async Function die neuen Wert liefert

        Returns:
            Cached (evtl. stale) value oder None
        """
        cache = self.get_cache(cache_name)
        value = cache.get(key)

        # Proaktiver Refresh wenn nötig
        if value is not None and cache.should_refresh(key):
            refresh_key = f"{cache_name}:{key}"
            now = datetime.now().timestamp()
            with self._refresh_lock:
                # Circuit breaker: skip if circuit is open
                circuit_until = self._refresh_circuit_open.get(refresh_key, 0)
                if now < circuit_until:
                    return value
                if refresh_key not in self._refresh_in_progress:
                    self._refresh_in_progress.add(refresh_key)
                    asyncio.create_task(
                        self._background_refresh(cache_name, key, refresh_func, refresh_key)
                    )

        return value

    _REFRESH_MAX_RETRIES = 3
    _REFRESH_CIRCUIT_OPEN_SECONDS = 60
    _REFRESH_TIMEOUT_SECONDS = 30

    async def _background_refresh(
        self,
        cache_name: str,
        key: str,
        refresh_func: Callable[[], Coroutine[Any, Any, Any]],
        refresh_key: str
    ) -> None:
        """Background-Refresh Task with circuit breaker."""
        try:
            logger.debug(f"Background refresh for {cache_name}:{key}")
            new_value = await asyncio.wait_for(
                refresh_func(), timeout=self._REFRESH_TIMEOUT_SECONDS
            )
            if new_value is not None:
                self.set(cache_name, key, new_value)
            # Reset failure count on success
            self._refresh_failures.pop(refresh_key, None)
        except Exception as e:
            failures = self._refresh_failures.get(refresh_key, 0) + 1
            self._refresh_failures[refresh_key] = failures
            if failures >= self._REFRESH_MAX_RETRIES:
                self._refresh_circuit_open[refresh_key] = (
                    datetime.now().timestamp() + self._REFRESH_CIRCUIT_OPEN_SECONDS
                )
                logger.warning(
                    f"Background refresh circuit open for {cache_name}:{key} "
                    f"after {failures} failures (pausing {self._REFRESH_CIRCUIT_OPEN_SECONDS}s): {e}"
                )
                self._refresh_failures.pop(refresh_key, None)
            else:
                logger.warning(
                    f"Background refresh failed for {cache_name}:{key} "
                    f"(attempt {failures}/{self._REFRESH_MAX_RETRIES}): {e}"
                )
        finally:
            with self._refresh_lock:
                self._refresh_in_progress.discard(refresh_key)

    def invalidate(
        self,
        cache_name: str,
        key: Optional[str] = None,
        cascade: bool = True
    ) -> int:
        """
        Invalidiert Cache-Einträge mit optionaler Kaskadierung.

        Args:
            cache_name: Cache-Name
            key: Optional spezifischer Key (sonst gesamter Cache)
            cascade: Wenn True, invalidiere auch abhängige Caches

        Returns:
            Anzahl invalidierter Einträge
        """
        count = 0

        # Primären Cache invalidieren
        cache = self.get_cache(cache_name)
        if key:
            if cache.remove(key):
                count += 1
        else:
            count += cache.clear()

        # Kaskadierte Invalidierung
        if cascade:
            dependent_caches = self._dependencies.get(cache_name, [])
            for dependent_name in dependent_caches:
                if dependent_name in self._caches:
                    dependent_count = self._caches[dependent_name].clear()
                    count += dependent_count
                    logger.info(
                        f"Cascading invalidation: {cache_name} → {dependent_name} "
                        f"({dependent_count} entries)"
                    )

        return count

    def clear_all(self) -> int:
        """
        Leert alle Caches.

        Returns:
            Gesamtzahl entfernter Einträge
        """
        count = 0
        for cache in self._caches.values():
            count += cache.clear()
        logger.info(f"Cleared all caches ({count} entries)")
        return count

    def cleanup_expired(self) -> int:
        """
        Entfernt alle abgelaufenen Einträge aus allen Caches.

        Returns:
            Anzahl entfernter Einträge
        """
        count = 0
        for cache in self._caches.values():
            count += cache.cleanup_expired()
        return count

    def get_unified_stats(self) -> Dict[str, Any]:
        """
        Gibt einheitliche Statistiken über alle Caches zurück.

        Returns:
            Dictionary mit Stats pro Cache und Gesamtübersicht
        """
        stats = {
            "caches": {},
            "summary": {
                "total_entries": 0,
                "total_hits": 0,
                "total_misses": 0,
                "total_evictions": 0,
                "overall_hit_rate_pct": 0.0,
            }
        }

        total_hits = 0
        total_misses = 0

        for name, cache in self._caches.items():
            metrics = cache.metrics
            stats["caches"][name] = metrics.to_dict()

            stats["summary"]["total_entries"] += len(cache)
            total_hits += metrics.hits
            total_misses += metrics.misses
            stats["summary"]["total_evictions"] += metrics.evictions

        stats["summary"]["total_hits"] = total_hits
        stats["summary"]["total_misses"] = total_misses

        total_requests = total_hits + total_misses
        if total_requests > 0:
            stats["summary"]["overall_hit_rate_pct"] = round(
                (total_hits / total_requests) * 100, 2
            )

        return stats

    def get_health(self) -> Dict[str, Any]:
        """
        Gibt Health-Status für alle Caches zurück.

        Returns:
            Dictionary mit Health-Infos
        """
        stats = self.get_unified_stats()

        # Warnungen generieren
        warnings = []

        for name, cache_stats in stats["caches"].items():
            # Warnung bei hoher Fill-Rate
            if cache_stats["fill_rate_pct"] > 90:
                warnings.append(f"{name}: High fill rate ({cache_stats['fill_rate_pct']}%)")

            # Warnung bei niedriger Hit-Rate
            if cache_stats["total_requests"] > 100 and cache_stats["hit_rate_pct"] < 50:
                warnings.append(f"{name}: Low hit rate ({cache_stats['hit_rate_pct']}%)")

        return {
            "status": "healthy" if not warnings else "warning",
            "warnings": warnings,
            "summary": stats["summary"],
            "caches": {name: cache_stats["hit_rate_pct"] for name, cache_stats in stats["caches"].items()}
        }


# =============================================================================
# SINGLETON INSTANCE (für graduelle Migration)
# =============================================================================

_cache_manager_instance: Optional[CacheManager] = None
_cache_manager_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    """
    Gibt die globale CacheManager-Instanz zurück.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.

    Returns:
        CacheManager Instanz
    """
    try:
        from ..utils.deprecation import warn_singleton_usage
        warn_singleton_usage("get_cache_manager", "ServiceContainer.cache_manager")
    except ImportError:
        pass  # Called from tests with different import setup

    global _cache_manager_instance
    with _cache_manager_lock:
        if _cache_manager_instance is None:
            _cache_manager_instance = CacheManager.create_default()
        return _cache_manager_instance


def reset_cache_manager() -> None:
    """Setzt den globalen CacheManager zurück (für Tests)."""
    global _cache_manager_instance
    with _cache_manager_lock:
        if _cache_manager_instance is not None:
            _cache_manager_instance.clear_all()
        _cache_manager_instance = None
