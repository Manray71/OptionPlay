# OptionPlay - Rate Limiter
# ==========================
# Rate Limiting für API-Calls mit Token Bucket Algorithmus
#
# Features:
# - Thread-safe
# - Async-kompatibel
# - Exponentielles Backoff bei 429-Fehlern
# - Konfigurierbar pro Provider
#
# Usage:
#     limiter = RateLimiter(calls_per_minute=100)
#     await limiter.acquire()
#     # ... make API call ...

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable, TypeVar, Any
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class RateLimitConfig:
    """Rate Limit Konfiguration"""
    calls_per_minute: int = 100
    calls_per_second: int = 10
    burst_limit: int = 5  # Max Burst innerhalb von 1 Sekunde
    backoff_base: float = 1.0  # Basis für exponentielles Backoff
    backoff_max: float = 60.0  # Max Backoff in Sekunden
    backoff_factor: float = 2.0  # Multiplikator pro Retry


class RateLimiter:
    """
    Token Bucket Rate Limiter.
    
    Implementiert Rate Limiting mit Token Bucket Algorithmus:
    - Tokens werden mit konstanter Rate aufgefüllt
    - Requests verbrauchen Tokens
    - Bei leeren Bucket wird gewartet
    
    Thread-safe und async-kompatibel.
    
    Verwendung:
        limiter = RateLimiter(calls_per_minute=100)
        
        # Sync
        limiter.acquire_sync()
        
        # Async
        await limiter.acquire()
        
        # Als Decorator
        @limiter.limit
        async def api_call():
            ...
    """
    
    def __init__(
        self,
        calls_per_minute: int = 100,
        burst_limit: Optional[int] = None,
        name: str = "default"
    ) -> None:
        self.calls_per_minute = calls_per_minute
        self.calls_per_second = calls_per_minute / 60.0
        self.burst_limit = burst_limit or min(10, calls_per_minute // 10)
        self.name = name
        
        # Token Bucket State
        self._tokens = float(self.burst_limit)
        self._last_update = time.monotonic()
        self._lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None
        
        # Statistics
        self._total_requests = 0
        self._total_waits = 0
        self._total_wait_time = 0.0
        
        logger.debug(
            f"RateLimiter '{name}' created: {calls_per_minute}/min, "
            f"burst={self.burst_limit}"
        )
    
    def _get_async_lock(self) -> asyncio.Lock:
        """
        Lazy-creates async lock (thread-safe).

        The lock must be created within an event loop context,
        but we need thread-safety for the check-and-create operation.
        """
        with self._lock:
            if self._async_lock is None:
                self._async_lock = asyncio.Lock()
            return self._async_lock
    
    def _refill_tokens(self) -> None:
        """Füllt Tokens basierend auf vergangener Zeit auf."""
        now = time.monotonic()
        elapsed = now - self._last_update
        self._last_update = now
        
        # Tokens auffüllen
        new_tokens = elapsed * self.calls_per_second
        self._tokens = min(self.burst_limit, self._tokens + new_tokens)
    
    def _wait_time(self) -> float:
        """Berechnet Wartezeit bis nächstes Token verfügbar."""
        if self._tokens >= 1:
            return 0.0
        
        # Zeit bis 1 Token aufgefüllt ist
        tokens_needed = 1 - self._tokens
        return tokens_needed / self.calls_per_second
    
    def acquire_sync(self) -> float:
        """
        Synchrones Token erwerben.
        
        Wartet falls nötig und gibt Wartezeit zurück.
        """
        with self._lock:
            self._refill_tokens()
            
            wait_time = self._wait_time()
            
            if wait_time > 0:
                logger.debug(f"RateLimiter '{self.name}': waiting {wait_time:.3f}s")
                self._total_waits += 1
                self._total_wait_time += wait_time
                time.sleep(wait_time)
                self._refill_tokens()
            
            self._tokens -= 1
            self._total_requests += 1
            
            return wait_time
    
    async def acquire(self) -> float:
        """
        Asynchrones Token erwerben.
        
        Wartet falls nötig und gibt Wartezeit zurück.
        """
        async with self._get_async_lock():
            self._refill_tokens()
            
            wait_time = self._wait_time()
            
            if wait_time > 0:
                logger.debug(f"RateLimiter '{self.name}': waiting {wait_time:.3f}s")
                self._total_waits += 1
                self._total_wait_time += wait_time
                await asyncio.sleep(wait_time)
                self._refill_tokens()
            
            self._tokens -= 1
            self._total_requests += 1
            
            return wait_time
    
    def limit(self, func: Callable[..., T]) -> Callable[..., T]:
        """
        Decorator für Rate-Limited Funktionen.
        
        Unterstützt sync und async Funktionen.
        """
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs) -> T:
                await self.acquire()
                return await func(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs) -> T:
                self.acquire_sync()
                return func(*args, **kwargs)
            return sync_wrapper
    
    def try_acquire(self) -> bool:
        """
        Versucht Token zu erwerben ohne zu warten.
        
        Returns:
            True wenn erfolgreich, False wenn Rate Limit erreicht
        """
        with self._lock:
            self._refill_tokens()
            
            if self._tokens >= 1:
                self._tokens -= 1
                self._total_requests += 1
                return True
            
            return False
    
    @property
    def available_tokens(self) -> float:
        """Aktuelle verfügbare Tokens"""
        with self._lock:
            self._refill_tokens()
            return self._tokens
    
    def stats(self) -> dict:
        """Statistiken"""
        return {
            "name": self.name,
            "calls_per_minute": self.calls_per_minute,
            "burst_limit": self.burst_limit,
            "available_tokens": round(self.available_tokens, 2),
            "total_requests": self._total_requests,
            "total_waits": self._total_waits,
            "total_wait_time": round(self._total_wait_time, 3),
            "avg_wait_time": round(
                self._total_wait_time / self._total_waits, 3
            ) if self._total_waits > 0 else 0
        }
    
    def reset(self) -> None:
        """Setzt Rate Limiter zurück"""
        with self._lock:
            self._tokens = float(self.burst_limit)
            self._last_update = time.monotonic()
            self._total_requests = 0
            self._total_waits = 0
            self._total_wait_time = 0.0


class AdaptiveRateLimiter(RateLimiter):
    """
    Adaptiver Rate Limiter mit automatischem Backoff.
    
    Reduziert Rate automatisch bei 429-Fehlern und
    erhöht sie wieder bei Erfolg.
    
    Verwendung:
        limiter = AdaptiveRateLimiter(calls_per_minute=100)
        
        try:
            await limiter.acquire()
            response = await api_call()
            limiter.record_success()
        except RateLimitError:
            limiter.record_rate_limit()
    """
    
    def __init__(
        self,
        calls_per_minute: int = 100,
        min_rate: int = 10,
        backoff_factor: float = 0.5,
        recovery_factor: float = 1.1,
        name: str = "adaptive"
    ) -> None:
        super().__init__(calls_per_minute, name=name)
        
        self.original_rate = calls_per_minute
        self.min_rate = min_rate
        self.backoff_factor = backoff_factor
        self.recovery_factor = recovery_factor
        
        self._consecutive_successes = 0
        self._consecutive_rate_limits = 0
        self._recovery_threshold = 10  # Erfolge bis Rate-Erhöhung
    
    def record_success(self) -> None:
        """Zeichnet erfolgreichen Request auf."""
        self._consecutive_successes += 1
        self._consecutive_rate_limits = 0
        
        # Rate erhöhen nach genug Erfolgen
        if self._consecutive_successes >= self._recovery_threshold:
            self._increase_rate()
            self._consecutive_successes = 0
    
    def record_rate_limit(self) -> None:
        """Zeichnet Rate-Limit-Fehler auf."""
        self._consecutive_rate_limits += 1
        self._consecutive_successes = 0
        self._decrease_rate()
    
    def _decrease_rate(self) -> None:
        """Reduziert Rate nach 429-Fehler."""
        new_rate = max(
            self.min_rate,
            int(self.calls_per_minute * self.backoff_factor)
        )
        
        if new_rate != self.calls_per_minute:
            logger.warning(
                f"RateLimiter '{self.name}': reducing rate "
                f"{self.calls_per_minute} -> {new_rate}/min"
            )
            self.calls_per_minute = new_rate
            self.calls_per_second = new_rate / 60.0
    
    def _increase_rate(self) -> None:
        """Erhöht Rate nach erfolgreichen Requests."""
        new_rate = min(
            self.original_rate,
            int(self.calls_per_minute * self.recovery_factor)
        )
        
        if new_rate != self.calls_per_minute:
            logger.info(
                f"RateLimiter '{self.name}': increasing rate "
                f"{self.calls_per_minute} -> {new_rate}/min"
            )
            self.calls_per_minute = new_rate
            self.calls_per_second = new_rate / 60.0
    
    def reset_to_original(self) -> None:
        """Setzt Rate auf Originalwert zurück."""
        self.calls_per_minute = self.original_rate
        self.calls_per_second = self.original_rate / 60.0
        self._consecutive_successes = 0
        self._consecutive_rate_limits = 0


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """
    Decorator für Retry mit exponentiellem Backoff.
    
    Args:
        max_retries: Maximale Anzahl Versuche
        base_delay: Initiale Wartezeit
        max_delay: Maximale Wartezeit
        backoff_factor: Multiplikator pro Versuch
        exceptions: Exception-Typen die Retry auslösen
        
    Verwendung:
        @retry_with_backoff(max_retries=3)
        async def api_call():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs) -> T:
                delay = base_delay
                last_exception = None
                
                for attempt in range(max_retries):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        
                        if attempt < max_retries - 1:
                            wait_time = min(delay, max_delay)
                            logger.warning(
                                f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): "
                                f"{e}. Retrying in {wait_time:.1f}s..."
                            )
                            await asyncio.sleep(wait_time)
                            delay *= backoff_factor
                        else:
                            logger.error(
                                f"{func.__name__} failed after {max_retries} attempts: {e}"
                            )
                
                raise last_exception
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs) -> T:
                delay = base_delay
                last_exception = None
                
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        
                        if attempt < max_retries - 1:
                            wait_time = min(delay, max_delay)
                            logger.warning(
                                f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): "
                                f"{e}. Retrying in {wait_time:.1f}s..."
                            )
                            time.sleep(wait_time)
                            delay *= backoff_factor
                        else:
                            logger.error(
                                f"{func.__name__} failed after {max_retries} attempts: {e}"
                            )
                
                raise last_exception
            return sync_wrapper
    return decorator


# =============================================================================
# PRE-CONFIGURED LIMITERS
# =============================================================================

# Globale Limiter-Instanzen pro Provider
_limiters: dict = {}


def get_limiter(
    provider: str,
    calls_per_minute: int = 100,
    adaptive: bool = True
) -> RateLimiter:
    """
    Gibt Rate Limiter für einen Provider zurück.
    
    Erstellt einen neuen Limiter wenn keiner existiert.
    
    Args:
        provider: Provider-Name (z.B. "marketdata", "tradier")
        calls_per_minute: Rate Limit
        adaptive: True für AdaptiveRateLimiter
        
    Returns:
        RateLimiter Instanz
    """
    if provider not in _limiters:
        if adaptive:
            _limiters[provider] = AdaptiveRateLimiter(
                calls_per_minute=calls_per_minute,
                name=provider
            )
        else:
            _limiters[provider] = RateLimiter(
                calls_per_minute=calls_per_minute,
                name=provider
            )
    
    return _limiters[provider]


def get_marketdata_limiter() -> AdaptiveRateLimiter:
    """
    Rate Limiter für Marketdata.app (100 req/min).

    .. deprecated:: 3.5.0
        Use ``ServiceContainer.rate_limiter`` instead. Will be removed in v4.0.
    """
    try:
        from .deprecation import warn_singleton_usage
        warn_singleton_usage("get_marketdata_limiter", "container.rate_limiter")
    except ImportError:
        pass

    return get_limiter("marketdata", calls_per_minute=100, adaptive=True)


def get_tradier_limiter() -> AdaptiveRateLimiter:
    """
    Rate Limiter für Tradier (120 req/min).

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.
    """
    try:
        from .deprecation import warn_singleton_usage
        warn_singleton_usage("get_tradier_limiter", "container.tradier_rate_limiter")
    except ImportError:
        pass

    return get_limiter("tradier", calls_per_minute=120, adaptive=True)


def get_yahoo_limiter() -> RateLimiter:
    """
    Rate Limiter für Yahoo Finance (2 req/sec, nicht adaptiv).

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.
    """
    try:
        from .deprecation import warn_singleton_usage
        warn_singleton_usage("get_yahoo_limiter", "container.yahoo_rate_limiter")
    except ImportError:
        pass

    return get_limiter("yahoo", calls_per_minute=120, adaptive=False)
