# OptionPlay - Server State Management
# =====================================
"""
Zentralisierte State-Objekte für den OptionPlay Server.

Ersetzt verstreute Instanzvariablen durch gruppierte Dataclasses:
- ServerState: Gesamter Server-State (Composition)
- ConnectionState: Connection-Lifecycle mit State Machine
- VIXState: VIX-bezogener State mit Staleness-Detection
- CacheMetrics: Einheitliche Cache-Statistiken

Verwendung:
    state = ServerState()

    # Connection State Machine
    state.connection.mark_connecting()
    state.connection.mark_connected()

    # VIX State
    state.vix.update(18.5, MarketRegime.STANDARD)
    if state.vix.is_stale:
        vix = await fetch_vix()

    # Cache Metrics
    state.quote_cache.record_hit()
    print(state.quote_cache.hit_rate)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any

# Import MarketRegime for VIX state
# Use fallback if vix_strategy can't be imported (e.g., missing dependencies)
try:
    from ..vix_strategy import MarketRegime
except (ImportError, ModuleNotFoundError):
    # Fallback if not available (e.g., yaml not installed)
    class MarketRegime(Enum):
        LOW_VOL = "low_vol"
        NORMAL = "normal"
        ELEVATED = "elevated"
        HIGH_VOL = "high_vol"
        UNKNOWN = "unknown"


class ConnectionStatus(Enum):
    """
    Connection State Machine für Provider.

    Übergänge:
        DISCONNECTED → CONNECTING → CONNECTED
                    ↘ FAILED ↙
        CONNECTED → RECONNECTING → CONNECTED
                               ↘ FAILED
    """
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class ConnectionState:
    """
    Gruppiert Connection-bezogenen State.

    Implementiert State Machine für Connection Lifecycle.

    Attributes:
        status: Aktueller Connection-Status
        last_connected_at: Zeitpunkt der letzten erfolgreichen Verbindung
        last_attempt_at: Zeitpunkt des letzten Verbindungsversuchs
        consecutive_failures: Anzahl aufeinanderfolgender Fehlversuche
        total_reconnects: Gesamtzahl der Reconnects
        last_error: Letzter Fehler (für Debugging)
    """
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    last_connected_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    consecutive_failures: int = 0
    total_reconnects: int = 0
    last_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        """Prüft ob aktuell verbunden."""
        return self.status == ConnectionStatus.CONNECTED

    @property
    def is_connecting(self) -> bool:
        """Prüft ob Verbindungsaufbau läuft."""
        return self.status in (ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING)

    @property
    def is_failed(self) -> bool:
        """Prüft ob Verbindung fehlgeschlagen."""
        return self.status == ConnectionStatus.FAILED

    @property
    def can_attempt_connection(self) -> bool:
        """Prüft ob Verbindungsversuch erlaubt (nicht in CONNECTING/RECONNECTING)."""
        return self.status not in (ConnectionStatus.CONNECTING, ConnectionStatus.RECONNECTING)

    @property
    def uptime_seconds(self) -> Optional[float]:
        """Zeit seit letzter erfolgreicher Verbindung in Sekunden."""
        if self.last_connected_at and self.is_connected:
            return (datetime.now() - self.last_connected_at).total_seconds()
        return None

    def mark_connecting(self) -> None:
        """Markiert als 'verbindet'."""
        if self.status == ConnectionStatus.CONNECTED:
            self.status = ConnectionStatus.RECONNECTING
            self.total_reconnects += 1
        else:
            self.status = ConnectionStatus.CONNECTING
        self.last_attempt_at = datetime.now()

    def mark_connected(self) -> None:
        """Markiert als 'verbunden' nach erfolgreichem Connect."""
        self.status = ConnectionStatus.CONNECTED
        self.last_connected_at = datetime.now()
        self.consecutive_failures = 0
        self.last_error = None

    def mark_disconnected(self) -> None:
        """Markiert als 'getrennt' (gewollte Trennung)."""
        self.status = ConnectionStatus.DISCONNECTED

    def mark_failed(self, error: Optional[str] = None) -> None:
        """Markiert als 'fehlgeschlagen' nach Connection-Fehler."""
        self.status = ConnectionStatus.FAILED
        self.consecutive_failures += 1
        self.last_error = error
        self.last_attempt_at = datetime.now()

    def reset(self) -> None:
        """Setzt State komplett zurück."""
        self.status = ConnectionStatus.DISCONNECTED
        self.last_connected_at = None
        self.last_attempt_at = None
        self.consecutive_failures = 0
        self.last_error = None
        # total_reconnects bleibt für Statistik

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary für Logging/Serialisierung."""
        return {
            "status": self.status.value,
            "is_connected": self.is_connected,
            "last_connected_at": self.last_connected_at.isoformat() if self.last_connected_at else None,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "consecutive_failures": self.consecutive_failures,
            "total_reconnects": self.total_reconnects,
            "uptime_seconds": self.uptime_seconds,
            "last_error": self.last_error,
        }


@dataclass
class VIXState:
    """
    Gruppiert VIX-bezogenen State.

    Implementiert:
    - Caching mit TTL
    - Staleness Detection
    - Market Regime Tracking

    Attributes:
        current_value: Aktueller VIX-Wert
        updated_at: Zeitpunkt der letzten Aktualisierung
        regime: Aktuelles Market Regime
        stale_threshold_seconds: Sekunden bis VIX als stale gilt
        previous_value: Vorheriger VIX für Change-Detection
    """
    current_value: Optional[float] = None
    updated_at: Optional[datetime] = None
    regime: Optional[MarketRegime] = None
    stale_threshold_seconds: int = 300  # 5 Minuten
    previous_value: Optional[float] = None

    @property
    def is_stale(self) -> bool:
        """Prüft ob VIX-Daten veraltet sind (älter als threshold)."""
        if self.updated_at is None:
            return True
        age = (datetime.now() - self.updated_at).total_seconds()
        return age > self.stale_threshold_seconds

    @property
    def age_seconds(self) -> Optional[float]:
        """Alter der VIX-Daten in Sekunden."""
        if self.updated_at is None:
            return None
        return (datetime.now() - self.updated_at).total_seconds()

    @property
    def change_pct(self) -> Optional[float]:
        """Prozentuale Änderung seit letztem Update."""
        if self.current_value is None or self.previous_value is None:
            return None
        if self.previous_value == 0:
            return None
        return ((self.current_value - self.previous_value) / self.previous_value) * 100

    @property
    def regime_description(self) -> str:
        """Beschreibung des aktuellen Regimes."""
        if self.regime is None:
            return "Unknown"

        descriptions = {
            MarketRegime.LOW_VOL: "Low Volatility (Conservative)",
            MarketRegime.NORMAL: "Normal Volatility",
            MarketRegime.ELEVATED: "Elevated Volatility (Aggressive)",
            MarketRegime.HIGH_VOL: "High Volatility (Crisis)",
        }
        return descriptions.get(self.regime, str(self.regime.value))

    def update(
        self,
        value: float,
        regime: Optional[MarketRegime] = None
    ) -> None:
        """
        Aktualisiert VIX-Wert und Regime.

        Args:
            value: Neuer VIX-Wert
            regime: Optional neues Regime (wird aus value berechnet wenn None)
        """
        self.previous_value = self.current_value
        self.current_value = value
        self.updated_at = datetime.now()

        if regime is not None:
            self.regime = regime
        else:
            # Auto-detect regime based on VIX value
            self.regime = self._detect_regime(value)

    def _detect_regime(self, vix: float) -> MarketRegime:
        """Erkennt Market Regime basierend auf VIX-Level."""
        if vix < 15:
            return MarketRegime.LOW_VOL
        elif vix < 20:
            return MarketRegime.NORMAL
        elif vix < 30:
            return MarketRegime.ELEVATED
        else:
            return MarketRegime.HIGH_VOL

    def invalidate(self) -> None:
        """Invalidiert cached VIX (z.B. bei Marktschluss)."""
        self.updated_at = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary."""
        return {
            "current_value": self.current_value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "age_seconds": self.age_seconds,
            "is_stale": self.is_stale,
            "regime": self.regime.value if self.regime else None,
            "regime_description": self.regime_description,
            "change_pct": self.change_pct,
        }


@dataclass
class CacheMetrics:
    """
    Einheitliche Cache-Statistiken.

    Ersetzt verstreute hit/miss Counter.

    Attributes:
        name: Cache-Name für Identifikation
        hits: Anzahl Cache Hits
        misses: Anzahl Cache Misses
        evictions: Anzahl Evictions
        ttl_seconds: Configured TTL
        max_entries: Configured max entries
    """
    name: str
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    evictions_ttl: int = 0
    evictions_lru: int = 0
    circuit_breaker_opens: int = 0
    ttl_seconds: int = 0
    max_entries: int = 0
    _current_entries: int = 0

    @property
    def total_requests(self) -> int:
        """Gesamtzahl der Anfragen."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Hit Rate (0.0 - 1.0)."""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    @property
    def hit_rate_pct(self) -> float:
        """Hit Rate in Prozent."""
        return self.hit_rate * 100

    @property
    def miss_rate(self) -> float:
        """Miss Rate (0.0 - 1.0)."""
        return 1.0 - self.hit_rate

    @property
    def current_entries(self) -> int:
        """Aktuelle Anzahl Einträge."""
        return self._current_entries

    @property
    def fill_rate(self) -> float:
        """Füllstand (0.0 - 1.0) relativ zu max_entries."""
        if self.max_entries == 0:
            return 0.0
        return min(1.0, self._current_entries / self.max_entries)

    def record_hit(self) -> None:
        """Zählt einen Cache Hit."""
        self.hits += 1

    def record_miss(self) -> None:
        """Zählt einen Cache Miss."""
        self.misses += 1

    def record_eviction(self) -> None:
        """Zählt eine Eviction."""
        self.evictions += 1

    def set_current_entries(self, count: int) -> None:
        """Setzt aktuelle Anzahl Einträge."""
        self._current_entries = count

    def reset(self) -> None:
        """Setzt Statistiken zurück (nicht Konfiguration)."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.evictions_ttl = 0
        self.evictions_lru = 0
        self.circuit_breaker_opens = 0
        self._current_entries = 0

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary."""
        return {
            "name": self.name,
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": self.total_requests,
            "hit_rate_pct": round(self.hit_rate_pct, 2),
            "evictions": self.evictions,
            "evictions_ttl": self.evictions_ttl,
            "evictions_lru": self.evictions_lru,
            "circuit_breaker_opens": self.circuit_breaker_opens,
            "current_entries": self.current_entries,
            "max_entries": self.max_entries,
            "fill_rate_pct": round(self.fill_rate * 100, 2),
            "ttl_seconds": self.ttl_seconds,
        }


@dataclass
class ServerState:
    """
    Gesamter Server-State als Composition.

    Gruppiert alle State-Komponenten an einem Ort.
    Ersetzt 16+ verstreute Instanzvariablen in OptionPlayServer.

    Attributes:
        connection: Connection-Lifecycle State
        vix: VIX-bezogener State
        quote_cache: Quote Cache Metriken
        scan_cache: Scan Cache Metriken
        historical_cache: Historical Cache Metriken
        started_at: Server-Startzeit
        request_count: Gesamtzahl der Requests
    """
    connection: ConnectionState = field(default_factory=ConnectionState)
    vix: VIXState = field(default_factory=VIXState)
    quote_cache: CacheMetrics = field(
        default_factory=lambda: CacheMetrics(name="quote", ttl_seconds=60, max_entries=1000)
    )
    scan_cache: CacheMetrics = field(
        default_factory=lambda: CacheMetrics(name="scan", ttl_seconds=1800, max_entries=100)
    )
    historical_cache: CacheMetrics = field(
        default_factory=lambda: CacheMetrics(name="historical", ttl_seconds=900, max_entries=500)
    )
    started_at: datetime = field(default_factory=datetime.now)
    request_count: int = 0
    last_request_at: Optional[datetime] = None

    @property
    def uptime_seconds(self) -> float:
        """Server Uptime in Sekunden."""
        return (datetime.now() - self.started_at).total_seconds()

    @property
    def uptime_human(self) -> str:
        """Human-readable Uptime (z.B. '2h 15m')."""
        seconds = self.uptime_seconds
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.0f}m"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}d {hours}h"

    @property
    def total_cache_requests(self) -> int:
        """Gesamtzahl Cache-Anfragen über alle Caches."""
        return (
            self.quote_cache.total_requests +
            self.scan_cache.total_requests +
            self.historical_cache.total_requests
        )

    @property
    def overall_cache_hit_rate(self) -> float:
        """Gesamte Cache Hit Rate (gewichtet nach Requests)."""
        total = self.total_cache_requests
        if total == 0:
            return 0.0

        total_hits = (
            self.quote_cache.hits +
            self.scan_cache.hits +
            self.historical_cache.hits
        )
        return total_hits / total

    def record_request(self) -> None:
        """Zählt einen Request."""
        self.request_count += 1
        self.last_request_at = datetime.now()

    def reset_caches(self) -> None:
        """Setzt alle Cache-Metriken zurück."""
        self.quote_cache.reset()
        self.scan_cache.reset()
        self.historical_cache.reset()

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert gesamten State zu Dictionary."""
        return {
            "connection": self.connection.to_dict(),
            "vix": self.vix.to_dict(),
            "caches": {
                "quote": self.quote_cache.to_dict(),
                "scan": self.scan_cache.to_dict(),
                "historical": self.historical_cache.to_dict(),
                "overall_hit_rate_pct": round(self.overall_cache_hit_rate * 100, 2),
            },
            "uptime_seconds": self.uptime_seconds,
            "uptime_human": self.uptime_human,
            "request_count": self.request_count,
            "last_request_at": self.last_request_at.isoformat() if self.last_request_at else None,
            "started_at": self.started_at.isoformat(),
        }

    def health_summary(self) -> Dict[str, Any]:
        """Kompakte Health-Zusammenfassung."""
        return {
            "status": "healthy" if self.connection.is_connected else "degraded",
            "connected": self.connection.is_connected,
            "vix": self.vix.current_value,
            "vix_stale": self.vix.is_stale,
            "cache_hit_rate_pct": round(self.overall_cache_hit_rate * 100, 1),
            "uptime": self.uptime_human,
            "requests": self.request_count,
        }
