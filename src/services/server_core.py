# OptionPlay - Server Core
# ========================
"""
Zentraler Koordinator für alle Services.

Ersetzt das "God Object" Pattern durch Service Composition.
Der ServerCore verwaltet:
- Service-Instanzen (QuoteService, OptionsService, VIXService, etc.)
- Zentralen ServerState
- Einheitliche Connection-Verwaltung

Verwendung:
    core = ServerCore.create_default()

    # Connection-Lifecycle
    await core.connect()

    # Service-Aufrufe
    vix = await core.vix.get_vix()
    quote = await core.quotes.get_quote("AAPL")

    await core.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from ..config import get_config
from ..container import ServiceContainer
from ..state import ConnectionStatus, ServerState
from ..utils.circuit_breaker import CircuitBreakerOpen

if TYPE_CHECKING:
    from ..data_providers.ibkr_provider import IBKRDataProvider
    from .base import ServiceContext
    from .options_service import OptionsService
    from .quote_service import QuoteService
    from .scanner_service import ScannerService
    from .vix_service import VIXService

logger = logging.getLogger(__name__)


@dataclass
class ServerCore:
    """
    Zentraler Service-Koordinator.

    Verwaltet alle Services und den globalen Server-State.
    Implementiert das Composition Pattern statt eines God Objects.

    Attributes:
        state: Zentraler ServerState
        container: DI Container für shared dependencies
        quotes: QuoteService für Kursabfragen
        options: OptionsService für Options-Chain
        vix: VIXService für VIX und Strategy
        scanner: ScannerService für Multi-Strategy Scanning
    """

    # State
    state: ServerState = field(default_factory=ServerState)

    # Container (shared dependencies)
    container: Optional[ServiceContainer] = None

    # API Key (stored for provider init)
    _api_key: str = field(default="", repr=False)

    # Provider (lazy-loaded)
    _provider: Optional["IBKRDataProvider"] = field(default=None, repr=False)

    # Services (lazy-initialized)
    _quote_service: Optional["QuoteService"] = field(default=None, repr=False)
    _options_service: Optional["OptionsService"] = field(default=None, repr=False)
    _vix_service: Optional["VIXService"] = field(default=None, repr=False)
    _scanner_service: Optional["ScannerService"] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize after dataclass creation."""
        pass  # IBKR TWS does not require an API key

    # =========================================================================
    # FACTORY METHODS
    # =========================================================================

    @classmethod
    def create_default(cls, api_key: Optional[str] = None) -> "ServerCore":
        """
        Erstellt ServerCore mit Standard-Konfiguration.

        Args:
            api_key: Optional API key override

        Returns:
            Konfigurierter ServerCore
        """
        container = ServiceContainer.create_default(api_key=api_key)

        return cls(
            container=container,
            _api_key=api_key or "",
        )

    @classmethod
    def create_for_testing(
        cls,
        container: Optional[ServiceContainer] = None,
        state: Optional[ServerState] = None,
    ) -> "ServerCore":
        """
        Erstellt ServerCore für Tests mit Mock-Dependencies.

        Args:
            container: Optional mock container
            state: Optional initial state

        Returns:
            Test-ServerCore
        """
        return cls(
            container=container,
            state=state or ServerState(),
            _api_key="test_key",
        )

    # Service context (lazy-created)
    _service_context: Optional["ServiceContext"] = field(default=None, repr=False)

    def _get_service_context(self) -> "ServiceContext":
        """Lazy-creates shared ServiceContext."""
        if self._service_context is None:
            from .base import ServiceContext

            self._service_context = ServiceContext(api_key=self._api_key)
        return self._service_context

    # =========================================================================
    # SERVICE PROPERTIES (Lazy Loading)
    # =========================================================================

    @property
    def quotes(self) -> "QuoteService":
        """QuoteService (lazy-loaded)."""
        if self._quote_service is None:
            from .quote_service import QuoteService

            self._quote_service = QuoteService(context=self._get_service_context())
        return self._quote_service

    @property
    def options(self) -> "OptionsService":
        """OptionsService (lazy-loaded)."""
        if self._options_service is None:
            from .options_service import OptionsService

            self._options_service = OptionsService(context=self._get_service_context())
        return self._options_service

    @property
    def vix(self) -> "VIXService":
        """VIXService (lazy-loaded)."""
        if self._vix_service is None:
            from .vix_service import VIXService

            self._vix_service = VIXService(context=self._get_service_context())
        return self._vix_service

    @property
    def scanner(self) -> "ScannerService":
        """ScannerService (lazy-loaded)."""
        if self._scanner_service is None:
            from .scanner_service import ScannerService

            self._scanner_service = ScannerService(context=self._get_service_context())
        return self._scanner_service

    @property
    def provider(self) -> Optional["IBKRDataProvider"]:
        """Data Provider (may be None if not connected)."""
        return self._provider

    @property
    def is_connected(self) -> bool:
        """Prüft ob Provider verbunden ist."""
        return self.state.connection.is_connected

    # =========================================================================
    # CONNECTION LIFECYCLE
    # =========================================================================

    async def connect(self) -> bool:
        """
        Verbindet alle Services mit dem Data Provider.

        Returns:
            True wenn erfolgreich verbunden

        Raises:
            CircuitBreakerOpen: Wenn Circuit Breaker offen
            ConnectionError: Bei Verbindungsfehler
        """
        if self.state.connection.is_connected:
            logger.debug("Already connected")
            return True

        if not self.state.connection.can_attempt_connection:
            logger.warning("Connection attempt already in progress")
            return False

        self.state.connection.mark_connecting()

        try:
            # Check circuit breaker from container
            if self.container and self.container.circuit_breaker:
                if not self.container.circuit_breaker.can_execute():
                    retry_after = self.container.circuit_breaker.get_retry_after()
                    raise CircuitBreakerOpen("ibkr_api", retry_after)

            # Initialize provider
            if self._provider is None:
                from ..data_providers.ibkr_provider import IBKRDataProvider

                from ..data_providers.ibkr_provider import IBKRDataProvider

                self._provider = IBKRDataProvider()

            # Connect with rate limiting
            if self.container and self.container.rate_limiter:
                await self.container.rate_limiter.acquire()

            connected = await self._provider.connect()

            if connected:
                self.state.connection.mark_connected()

                if self.container and self.container.rate_limiter:
                    self.container.rate_limiter.record_success()
                if self.container and self.container.circuit_breaker:
                    self.container.circuit_breaker.record_success()

                logger.info("Connected to IBKR TWS")
                return True
            else:
                self.state.connection.mark_failed("Connection returned False")
                return False

        except CircuitBreakerOpen:
            self.state.connection.mark_failed("Circuit breaker open")
            raise
        except Exception as e:
            error_msg = str(e)
            self.state.connection.mark_failed(error_msg)

            if self.container and self.container.circuit_breaker:
                self.container.circuit_breaker.record_failure(e)

            logger.error(f"Connection failed: {error_msg}")
            raise ConnectionError(f"Failed to connect: {error_msg}") from e

    async def disconnect(self) -> None:
        """Trennt alle Verbindungen."""
        if self._provider:
            try:
                await self._provider.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")

        self.state.connection.mark_disconnected()
        logger.info("Disconnected")

    async def ensure_connected(self) -> "IBKRDataProvider":
        """
        Stellt sicher, dass Provider verbunden ist.

        Returns:
            Verbundener Provider

        Raises:
            ConnectionError: Wenn Verbindung fehlschlägt
        """
        if not self.is_connected:
            await self.connect()

        if self._provider is None:
            raise ConnectionError("Provider not initialized")

        return self._provider

    # =========================================================================
    # ASYNC CONTEXT MANAGER
    # =========================================================================

    async def __aenter__(self) -> "ServerCore":
        """Enter async context - connect."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context - disconnect."""
        await self.disconnect()
        return None

    # =========================================================================
    # HEALTH & STATS
    # =========================================================================

    def health_summary(self) -> dict[str, Any]:
        """
        Gibt Health-Zusammenfassung zurück.

        Returns:
            Dict mit Health-Status
        """
        return self.state.health_summary()

    def get_stats(self) -> dict[str, Any]:
        """
        Gibt detaillierte Statistiken zurück.

        Returns:
            Dict mit allen Metriken
        """
        stats = self.state.to_dict()

        # Add container stats if available
        if self.container:
            stats["container"] = self.container.get_stats()

        return stats

    def record_request(self) -> None:
        """Zählt einen Request für Metriken."""
        self.state.record_request()

    # =========================================================================
    # CONVENIENCE METHODS (Delegates to Services)
    # =========================================================================

    async def get_vix(self, force_refresh: bool = False) -> Optional[float]:
        """
        Holt VIX-Wert (Convenience-Methode).

        Delegiert an VIXService und aktualisiert ServerState.

        Args:
            force_refresh: Force refresh ignoriert Cache

        Returns:
            VIX-Wert oder None
        """
        # Check cached value in state
        if not force_refresh and not self.state.vix.is_stale:
            return self.state.vix.current_value

        # Fetch via service
        result = await self.vix.get_vix()

        if result.success and result.data is not None:
            vix_value: float = result.data
            self.state.vix.update(vix_value)
            return vix_value

        return self.state.vix.current_value

    async def get_quote(self, symbol: str) -> Optional[dict[str, Any]]:
        """
        Holt Quote (Convenience-Methode).

        Args:
            symbol: Ticker symbol

        Returns:
            Quote dict oder None
        """
        result = await self.quotes.get_quote(symbol)

        if result.success:
            self.state.quote_cache.record_hit()
            return result.data
        else:
            self.state.quote_cache.record_miss()
            return None
