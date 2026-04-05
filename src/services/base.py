# OptionPlay - Base Service
# ==========================
"""
Basis-Klasse für alle Services.

Stellt gemeinsame Funktionalität bereit:
- API-Key-Verwaltung
- Rate Limiting
- Circuit Breaker
- Caching
- Logging

Verwendung:
    class MyService(BaseService):
        async def do_something(self) -> ServiceResult[str]:
            provider = await self._ensure_connected()
            async with self._rate_limited():
                result = await provider.fetch_data()
            return ServiceResult.ok(result)
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..cache import HistoricalCache, get_historical_cache
from ..config import get_config
from ..utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, get_circuit_breaker
from ..utils.rate_limiter import AdaptiveRateLimiter, get_marketdata_limiter
from ..utils.secure_config import get_api_key, mask_api_key

logger = logging.getLogger(__name__)


@dataclass
class ServiceContext:
    """
    Shared Context für alle Services.

    Ermöglicht das Teilen von Ressourcen zwischen Services,
    ohne dass jeder Service seine eigene Verbindung aufbaut.

    Attributes:
        api_key: Marketdata.app API Key
        config: Configuration (optional, falls back to get_config())
        provider: Shared IBKRDataProvider (lazy init)
        rate_limiter: Shared Rate Limiter
        circuit_breaker: Shared Circuit Breaker
        historical_cache: Shared Cache
        connected: Verbindungsstatus
    """

    api_key: str
    config: Optional[Any] = None  # ConfigLoader
    rate_limiter: AdaptiveRateLimiter = field(default_factory=get_marketdata_limiter)
    historical_cache: Optional[HistoricalCache] = None
    _circuit_breaker: Optional[CircuitBreaker] = None
    _provider: Optional[Any] = None  # IBKRDataProvider
    _connected: bool = False
    _vix_cache: Optional[float] = None
    _vix_updated: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Initialize components after dataclass creation."""
        if self.config is None:
            self.config = get_config()
        perf = self.config.settings.performance
        cb_cfg = self.config.settings.circuit_breaker

        if self.historical_cache is None:
            self.historical_cache = get_historical_cache(
                ttl_seconds=perf.cache_ttl_seconds, max_entries=perf.cache_max_entries
            )

        if self._circuit_breaker is None:
            self._circuit_breaker = get_circuit_breaker(
                name="marketdata_api",
                failure_threshold=cb_cfg.failure_threshold,
                recovery_timeout=cb_cfg.recovery_timeout,
            )

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Gibt den Circuit Breaker zurück."""
        return self._circuit_breaker

    @property
    def api_key_masked(self) -> str:
        """Maskierter API Key für Logging."""
        return mask_api_key(self.api_key)

    async def get_provider(self) -> Any:
        """
        Gibt den verbundenen Provider zurück.

        Lazy-initialisiert die Verbindung wenn nötig.
        """
        if self._provider is None:
            from ..data_providers.ibkr_provider import IBKRDataProvider

            self._provider = IBKRDataProvider()

        if not self._connected:
            await self._connect_provider()

        return self._provider

    async def _connect_provider(self) -> None:
        """Verbindet den Provider mit Retry-Logik."""
        if not self._circuit_breaker.can_execute():
            retry_after = self._circuit_breaker.get_retry_after()
            raise CircuitBreakerOpen("marketdata_api", retry_after)

        api_conn = self.config.settings.api_connection

        for attempt in range(api_conn.max_retries):
            try:
                await self.rate_limiter.acquire()
                connected = await self._provider.connect()
                if connected:
                    self._connected = True
                    self.rate_limiter.record_success()
                    self._circuit_breaker.record_success()
                    logger.info("Connected to Marketdata.app")
                    return
            except CircuitBreakerOpen:
                raise
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                self._circuit_breaker.record_failure(e)
                if attempt < api_conn.max_retries - 1:
                    await asyncio.sleep(api_conn.retry_base_delay**attempt)

        raise ConnectionError(
            f"Cannot connect to Marketdata.app after {api_conn.max_retries} attempts"
        )

    async def disconnect(self) -> None:
        """Trennt die Verbindung zum Provider."""
        if self._provider and self._connected:
            await self._provider.disconnect()
            self._connected = False
            logger.info("Disconnected from Marketdata.app")


class BaseService(ABC):
    """
    Basis-Klasse für alle OptionPlay Services.

    Stellt gemeinsame Funktionalität bereit:
    - Zugriff auf ServiceContext (Provider, Cache, etc.)
    - Rate-limited API-Aufrufe
    - Einheitliches Error-Handling

    Verwendung:
        class MyService(BaseService):
            async def fetch_data(self, symbol: str):
                provider = await self._get_provider()
                async with self._rate_limited():
                    return await provider.get_quote(symbol)
    """

    def __init__(self, context: ServiceContext) -> None:
        """
        Initialisiert den Service mit SharedContext.

        Args:
            context: Shared ServiceContext mit Provider, Cache, etc.
        """
        self._context = context
        self._config = context.config
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def api_key_masked(self) -> str:
        """Maskierter API Key für Logging."""
        return self._context.api_key_masked

    async def _get_provider(self) -> Any:
        """Gibt den verbundenen Provider zurück."""
        return await self._context.get_provider()

    @asynccontextmanager
    async def _rate_limited(self) -> AsyncIterator[None]:
        """
        Context Manager für rate-limited API Calls.

        Verwendung:
            async with self._rate_limited():
                result = await provider.api_call()
        """
        await self._context.rate_limiter.acquire()
        try:
            yield
            self._context.rate_limiter.record_success()
        except Exception:
            self._context.rate_limiter.record_rate_limit()
            raise

    def _get_historical_cache(self) -> HistoricalCache:
        """Gibt den Historical Cache zurück."""
        return self._context.historical_cache

    def _get_circuit_breaker(self) -> CircuitBreaker:
        """Gibt den Circuit Breaker zurück."""
        return self._context.circuit_breaker


def create_service_context(api_key: Optional[str] = None) -> ServiceContext:
    """
    Factory-Funktion für ServiceContext.

    Args:
        api_key: Optional API Key (sonst aus Umgebungsvariable)

    Returns:
        Konfigurierter ServiceContext

    Raises:
        ValueError: Wenn kein API Key gefunden
    """
    if not api_key:
        api_key = get_api_key("MARKETDATA_API_KEY", required=True)

    return ServiceContext(api_key=api_key)
