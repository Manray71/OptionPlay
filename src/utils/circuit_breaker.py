# OptionPlay - Circuit Breaker Pattern
# =====================================
"""
Circuit Breaker für API-Verbindungen.

Verhindert kaskadierende Fehler bei API-Ausfällen durch:
- Automatisches Öffnen nach X Fehlern
- Timeout im offenen Zustand
- Half-Open State für Recovery-Tests

States:
- CLOSED: Normal, Requests werden durchgelassen
- OPEN: Fehler, Requests werden sofort abgelehnt
- HALF_OPEN: Test-Phase, ein Request wird durchgelassen

Verwendung:
    from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen

    breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60,
        half_open_max_calls=3
    )

    async with breaker:
        result = await api_call()

    # Oder manuell:
    if breaker.can_execute():
        try:
            result = await api_call()
            breaker.record_success()
        except Exception as e:
            breaker.record_failure()
            raise
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# EXCEPTIONS
# =============================================================================


class CircuitBreakerOpen(Exception):
    """Wird geworfen wenn der Circuit Breaker offen ist."""

    def __init__(self, breaker_name: str, retry_after: Optional[float] = None):
        self.breaker_name = breaker_name
        self.retry_after = retry_after
        message = f"Circuit breaker '{breaker_name}' is OPEN"
        if retry_after:
            message += f" (retry after {retry_after:.1f}s)"
        super().__init__(message)


class CircuitBreakerError(Exception):
    """Allgemeiner Circuit Breaker Fehler."""

    pass


# =============================================================================
# CIRCUIT BREAKER STATE
# =============================================================================


class CircuitState(Enum):
    """Circuit Breaker Zustände."""

    CLOSED = "closed"  # Normal, Requests erlaubt
    OPEN = "open"  # Fehler, Requests blockiert
    HALF_OPEN = "half_open"  # Test-Phase


@dataclass
class CircuitBreakerStats:
    """Statistiken für einen Circuit Breaker."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0


# =============================================================================
# CIRCUIT BREAKER
# =============================================================================


class CircuitBreaker:
    """
    Circuit Breaker für API-Verbindungen.

    Schützt vor kaskadierenden Fehlern bei API-Ausfällen.

    Args:
        name: Name des Circuit Breakers (für Logging)
        failure_threshold: Anzahl Fehler bevor OPEN
        recovery_timeout: Sekunden im OPEN-State bevor HALF_OPEN
        half_open_max_calls: Max Calls im HALF_OPEN-State
        success_threshold: Erfolge im HALF_OPEN für CLOSED

    Verwendung als Context Manager:
        async with breaker:
            result = await api_call()

    Verwendung als Decorator:
        @breaker
        async def api_call():
            ...
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        success_threshold: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: Optional[datetime] = None
        self._opened_at: Optional[datetime] = None

        self._lock = threading.RLock()
        self._stats = CircuitBreakerStats()

        # Callbacks
        self._on_open: Optional[Callable[[], None]] = None
        self._on_close: Optional[Callable[[], None]] = None
        self._on_half_open: Optional[Callable[[], None]] = None

    @property
    def state(self) -> CircuitState:
        """Aktueller Zustand (mit automatischer Transition zu HALF_OPEN)."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_try_reset():
                    self._transition_to(CircuitState.HALF_OPEN)
            return self._state

    @property
    def is_closed(self) -> bool:
        """Prüft ob Circuit geschlossen ist (normal)."""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Prüft ob Circuit offen ist (blockiert)."""
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Prüft ob Circuit halb-offen ist (Test-Phase)."""
        return self.state == CircuitState.HALF_OPEN

    def _should_try_reset(self) -> bool:
        """Prüft ob Recovery-Timeout abgelaufen ist."""
        if self._opened_at is None:
            return False
        elapsed = (datetime.now() - self._opened_at).total_seconds()
        return elapsed >= self.recovery_timeout

    def _transition_to(self, new_state: CircuitState) -> None:
        """Wechselt in einen neuen Zustand."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changes += 1

        logger.info(f"Circuit breaker '{self.name}': {old_state.value} → {new_state.value}")

        if new_state == CircuitState.OPEN:
            self._opened_at = datetime.now()
            self._half_open_calls = 0
            if self._on_open:
                self._on_open()

        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0
            if self._on_half_open:
                self._on_half_open()

        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._opened_at = None
            if self._on_close:
                self._on_close()

    def can_execute(self) -> bool:
        """
        Prüft ob ein Request ausgeführt werden kann.

        Returns:
            True wenn Request erlaubt
        """
        with self._lock:
            state = self.state  # Trigger auto-transition

            if state == CircuitState.CLOSED:
                return True

            if state == CircuitState.OPEN:
                return False

            if state == CircuitState.HALF_OPEN:
                # Limitiere Calls im Half-Open State
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

            # Should never reach here, but satisfy type checker
            return False  # pragma: no cover

    def record_success(self) -> None:
        """Registriert einen erfolgreichen Request."""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.successful_calls += 1
            self._stats.last_success_time = datetime.now()
            self._stats.consecutive_successes += 1
            self._stats.consecutive_failures = 0

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition_to(CircuitState.CLOSED)

            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    def record_failure(self, exception: Optional[Exception] = None) -> None:
        """Registriert einen fehlgeschlagenen Request."""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._stats.last_failure_time = datetime.now()
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._last_failure_time = datetime.now()

            if self._state == CircuitState.HALF_OPEN:
                # Ein Fehler im Half-Open → zurück zu Open
                self._transition_to(CircuitState.OPEN)

            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

            if exception:
                logger.warning(f"Circuit breaker '{self.name}' recorded failure: {exception}")

    def record_rejected(self) -> None:
        """Registriert einen abgelehnten Request (Circuit offen)."""
        with self._lock:
            self._stats.rejected_calls += 1

    def reset(self) -> None:
        """Setzt den Circuit Breaker manuell zurück."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            logger.info(f"Circuit breaker '{self.name}' manually reset")

    def get_retry_after(self) -> Optional[float]:
        """Gibt verbleibende Zeit bis Recovery zurück."""
        with self._lock:
            if self._state != CircuitState.OPEN or self._opened_at is None:
                return None
            elapsed = (datetime.now() - self._opened_at).total_seconds()
            remaining = self.recovery_timeout - elapsed
            return max(0, remaining)

    def stats(self) -> Dict[str, Any]:
        """Gibt Statistiken zurück."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "total_calls": self._stats.total_calls,
                "successful_calls": self._stats.successful_calls,
                "failed_calls": self._stats.failed_calls,
                "rejected_calls": self._stats.rejected_calls,
                "consecutive_failures": self._stats.consecutive_failures,
                "consecutive_successes": self._stats.consecutive_successes,
                "state_changes": self._stats.state_changes,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "retry_after": self.get_retry_after(),
            }

    # =========================================================================
    # CONTEXT MANAGER & DECORATOR
    # =========================================================================

    async def __aenter__(self) -> "CircuitBreaker":
        """Async context manager entry."""
        if not self.can_execute():
            self.record_rejected()
            raise CircuitBreakerOpen(self.name, self.get_retry_after())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit."""
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure(exc_val)
        return False  # Don't suppress exceptions

    def __enter__(self) -> "CircuitBreaker":
        """Sync context manager entry."""
        if not self.can_execute():
            self.record_rejected()
            raise CircuitBreakerOpen(self.name, self.get_retry_after())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Sync context manager exit."""
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure(exc_val)
        return False

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator für Funktionen."""
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                async with self:
                    return await func(*args, **kwargs)

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                with self:
                    return func(*args, **kwargs)

            return sync_wrapper

    # =========================================================================
    # CALLBACKS
    # =========================================================================

    def on_open(self, callback: Callable[[], None]) -> "CircuitBreaker":
        """Registriert Callback für OPEN-Transition."""
        self._on_open = callback
        return self

    def on_close(self, callback: Callable[[], None]) -> "CircuitBreaker":
        """Registriert Callback für CLOSE-Transition."""
        self._on_close = callback
        return self

    def on_half_open(self, callback: Callable[[], None]) -> "CircuitBreaker":
        """Registriert Callback für HALF_OPEN-Transition."""
        self._on_half_open = callback
        return self


# =============================================================================
# CIRCUIT BREAKER REGISTRY
# =============================================================================


class CircuitBreakerRegistry:
    """
    Registry für mehrere Circuit Breaker.

    Ermöglicht zentrale Verwaltung und Überwachung.

    Verwendung:
        registry = CircuitBreakerRegistry()

        ibkr_breaker = registry.get_or_create("ibkr_api")
        ibkr_strict = registry.get_or_create("ibkr", failure_threshold=3)

        # Alle Stats
        all_stats = registry.all_stats()
    """

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()

        # Default-Konfiguration
        self._default_failure_threshold = 5
        self._default_recovery_timeout = 60.0
        self._default_half_open_max_calls = 3
        self._default_success_threshold = 2

    def configure_defaults(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        success_threshold: int = 2,
    ) -> None:
        """Konfiguriert Default-Werte für neue Breaker."""
        self._default_failure_threshold = failure_threshold
        self._default_recovery_timeout = recovery_timeout
        self._default_half_open_max_calls = half_open_max_calls
        self._default_success_threshold = success_threshold

    def get_or_create(
        self,
        name: str,
        failure_threshold: Optional[int] = None,
        recovery_timeout: Optional[float] = None,
        half_open_max_calls: Optional[int] = None,
        success_threshold: Optional[int] = None,
    ) -> CircuitBreaker:
        """
        Gibt existierenden Breaker zurück oder erstellt neuen.

        Args:
            name: Eindeutiger Name des Breakers
            failure_threshold: Überschreibt Default
            recovery_timeout: Überschreibt Default
            half_open_max_calls: Überschreibt Default
            success_threshold: Überschreibt Default

        Returns:
            CircuitBreaker Instanz
        """
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold or self._default_failure_threshold,
                    recovery_timeout=recovery_timeout or self._default_recovery_timeout,
                    half_open_max_calls=half_open_max_calls or self._default_half_open_max_calls,
                    success_threshold=success_threshold or self._default_success_threshold,
                )
                logger.debug(f"Created circuit breaker: {name}")
            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Gibt Breaker zurück oder None."""
        with self._lock:
            return self._breakers.get(name)

    def remove(self, name: str) -> bool:
        """Entfernt einen Breaker."""
        with self._lock:
            if name in self._breakers:
                del self._breakers[name]
                return True
            return False

    def reset_all(self) -> None:
        """Setzt alle Breaker zurück."""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()

    def all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Gibt Stats aller Breaker zurück."""
        with self._lock:
            return {name: breaker.stats() for name, breaker in self._breakers.items()}

    def get_open_breakers(self) -> list[str]:
        """Gibt Namen aller offenen Breaker zurück."""
        with self._lock:
            return [name for name, breaker in self._breakers.items() if breaker.is_open]


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_registry_instance: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """
    Gibt die globale Registry-Instanz zurück.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer.circuit_breaker_registry`` instead. Will be removed in v4.0.
    """
    try:
        from .deprecation import warn_singleton_usage

        warn_singleton_usage("get_circuit_breaker_registry", "container.circuit_breaker_registry")
    except ImportError:
        pass

    global _registry_instance
    if _registry_instance is None:
        _registry_instance = CircuitBreakerRegistry()
    return _registry_instance


def get_circuit_breaker(
    name: str,
    failure_threshold: Optional[int] = None,
    recovery_timeout: Optional[float] = None,
) -> CircuitBreaker:
    """
    Convenience-Funktion für Circuit Breaker.

    Args:
        name: Name des Breakers
        failure_threshold: Optional, überschreibt Default
        recovery_timeout: Optional, überschreibt Default

    Returns:
        CircuitBreaker Instanz
    """
    registry = get_circuit_breaker_registry()
    return registry.get_or_create(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
    )


def reset_circuit_breakers() -> None:
    """Setzt alle Circuit Breaker zurück."""
    global _registry_instance
    if _registry_instance:
        _registry_instance.reset_all()
    _registry_instance = None
