# OptionPlay - Dependency Injection Container
# ============================================
# Centralized dependency management for better testability and maintainability.
#
# Benefits:
# - No global singletons scattered across modules
# - Easy mocking in tests
# - Clear dependency graph
# - Configuration-driven service creation
#
# Usage:
#     # Production
#     container = ServiceContainer.create_default()
#     server = OptionPlayServer(container=container)
#
#     # Testing
#     mock_provider = Mock(spec=MarketDataProvider)
#     container = ServiceContainer.create_for_testing(provider=mock_provider)
#     server = OptionPlayServer(container=container)

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .data_providers.marketdata import MarketDataProvider
    from .data_providers.tradier import TradierProvider
    from .cache.earnings_cache_impl import EarningsCache, EarningsFetcher
    from .cache.iv_cache_impl import IVCache, IVFetcher
    from .cache.historical_cache import HistoricalCache
    from .utils.rate_limiter import AdaptiveRateLimiter
    from .utils.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry
    from .utils.earnings_aggregator import EarningsAggregator
    from .config import ConfigLoader

logger = logging.getLogger(__name__)


@dataclass
class ServiceContainer:
    """
    Dependency Injection Container for OptionPlay services.

    This container holds all shared services and dependencies, replacing
    scattered global singletons with a single, manageable instance.

    Attributes:
        config: Configuration loader with settings from YAML files
        rate_limiter: Adaptive rate limiter for API calls
        circuit_breaker: Circuit breaker for fault tolerance
        circuit_breaker_registry: Registry of all circuit breakers
        historical_cache: Cache for historical price data
        earnings_cache: Cache for earnings dates
        earnings_fetcher: Fetcher for earnings data
        earnings_aggregator: Aggregator for multi-source earnings
        iv_cache: Cache for implied volatility data
        iv_fetcher: Fetcher for IV data
        provider: Market data provider (optional, lazy-loaded)

    Example:
        >>> container = ServiceContainer.create_default()
        >>> vix = await container.provider.get_vix()
    """

    # Core configuration
    config: Optional['ConfigLoader'] = None

    # Rate limiting and resilience
    rate_limiter: Optional['AdaptiveRateLimiter'] = None
    circuit_breaker: Optional['CircuitBreaker'] = None
    circuit_breaker_registry: Optional['CircuitBreakerRegistry'] = None

    # Caching
    historical_cache: Optional['HistoricalCache'] = None
    earnings_cache: Optional['EarningsCache'] = None
    earnings_fetcher: Optional['EarningsFetcher'] = None
    earnings_aggregator: Optional['EarningsAggregator'] = None
    iv_cache: Optional['IVCache'] = None
    iv_fetcher: Optional['IVFetcher'] = None

    # Data providers (lazy-loaded)
    provider: Optional['MarketDataProvider'] = None
    tradier_provider: Optional['TradierProvider'] = None

    # Active provider name (for routing)
    active_provider: str = field(default="marketdata", repr=False)

    # Internal state
    _initialized: bool = field(default=False, repr=False)

    def __post_init__(self):
        """Validate container after initialization."""
        if self.config is not None:
            self._initialized = True

    @classmethod
    def create_default(cls, api_key: Optional[str] = None) -> 'ServiceContainer':
        """
        Create a container with default production services.

        This factory method creates and wires all services using
        the standard configuration from settings.yaml.

        Args:
            api_key: Optional API key override (otherwise from env/config)

        Returns:
            Fully configured ServiceContainer

        Example:
            >>> container = ServiceContainer.create_default()
            >>> assert container.config is not None
            >>> assert container.rate_limiter is not None
        """
        # Import here to avoid circular imports
        from .config import get_config
        from .utils.rate_limiter import get_marketdata_limiter
        from .utils.circuit_breaker import CircuitBreaker, get_circuit_breaker_registry
        from .cache.historical_cache import get_historical_cache
        from .cache.earnings_cache_impl import get_earnings_cache, get_earnings_fetcher
        from .cache.iv_cache_impl import get_iv_cache, get_iv_fetcher
        from .utils.earnings_aggregator import get_earnings_aggregator
        from .utils.secure_config import get_api_key

        # Load configuration
        config = get_config()

        # Get API key
        resolved_api_key = api_key or get_api_key("MARKETDATA_API_KEY")

        # Get rate limiter (uses default 100 req/min for marketdata)
        rate_limiter = get_marketdata_limiter()

        # Create circuit breaker
        circuit_breaker = CircuitBreaker(
            name="marketdata_api",
            failure_threshold=config.settings.circuit_breaker.failure_threshold,
            recovery_timeout=config.settings.circuit_breaker.recovery_timeout,
            half_open_max_calls=config.settings.circuit_breaker.half_open_max_calls,
        )

        # Get caches (reuse existing singletons for now to avoid breaking changes)
        historical_cache = get_historical_cache()
        earnings_cache = get_earnings_cache()
        earnings_fetcher = get_earnings_fetcher()
        iv_cache = get_iv_cache()
        iv_fetcher = get_iv_fetcher()
        earnings_aggregator = get_earnings_aggregator()

        container = cls(
            config=config,
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
            circuit_breaker_registry=get_circuit_breaker_registry(),
            historical_cache=historical_cache,
            earnings_cache=earnings_cache,
            earnings_fetcher=earnings_fetcher,
            earnings_aggregator=earnings_aggregator,
            iv_cache=iv_cache,
            iv_fetcher=iv_fetcher,
        )

        logger.info("ServiceContainer created with default configuration")
        return container

    @classmethod
    def create_for_testing(
        cls,
        config: Optional['ConfigLoader'] = None,
        rate_limiter: Optional['AdaptiveRateLimiter'] = None,
        circuit_breaker: Optional['CircuitBreaker'] = None,
        historical_cache: Optional['HistoricalCache'] = None,
        earnings_fetcher: Optional['EarningsFetcher'] = None,
        provider: Optional['MarketDataProvider'] = None,
        **overrides
    ) -> 'ServiceContainer':
        """
        Create a container for testing with mock services.

        This factory allows injecting mock objects for testing without
        affecting the global state of the application.

        Args:
            config: Mock config loader
            rate_limiter: Mock rate limiter
            circuit_breaker: Mock circuit breaker
            historical_cache: Mock historical cache
            earnings_fetcher: Mock earnings fetcher
            provider: Mock data provider
            **overrides: Additional service overrides

        Returns:
            ServiceContainer with test services

        Example:
            >>> from unittest.mock import Mock, AsyncMock
            >>> mock_provider = Mock()
            >>> mock_provider.get_quote = AsyncMock(return_value=Quote(last=150.0))
            >>> container = ServiceContainer.create_for_testing(provider=mock_provider)
        """
        from .config import ConfigLoader

        # Create minimal config if not provided
        if config is None:
            config = ConfigLoader()
            config.load_all()

        container = cls(
            config=config,
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
            historical_cache=historical_cache,
            earnings_fetcher=earnings_fetcher,
            provider=provider,
        )

        # Apply any additional overrides
        for key, value in overrides.items():
            if hasattr(container, key):
                setattr(container, key, value)

        logger.debug("ServiceContainer created for testing")
        return container

    @classmethod
    def create_minimal(cls) -> 'ServiceContainer':
        """
        Create a minimal container with only config loaded.

        Useful for lightweight operations that don't need full services.

        Returns:
            Minimal ServiceContainer with just config
        """
        from .config import get_config

        return cls(config=get_config())

    async def ensure_provider(self, api_key: Optional[str] = None) -> 'MarketDataProvider':
        """
        Ensure data provider is initialized and connected.

        Lazy-loads the provider on first call.

        Args:
            api_key: Optional API key override

        Returns:
            Connected MarketDataProvider

        Raises:
            ConnectionError: If unable to connect
        """
        if self.provider is None:
            from .data_providers.marketdata import MarketDataProvider
            from .utils.secure_config import get_api_key

            resolved_key = api_key or get_api_key("MARKETDATA_API_KEY")
            self.provider = MarketDataProvider(api_key=resolved_key)

        if not await self.provider.is_connected():
            await self.provider.connect()

        return self.provider

    async def ensure_tradier_provider(self, api_key: Optional[str] = None) -> 'TradierProvider':
        """
        Ensure Tradier provider is initialized and connected.

        Lazy-loads the provider on first call.

        Args:
            api_key: Optional API key override

        Returns:
            Connected TradierProvider

        Raises:
            ConnectionError: If unable to connect
            ValueError: If API key not found
        """
        if self.tradier_provider is None:
            from .data_providers.tradier import TradierProvider, TradierEnvironment
            from .utils.secure_config import get_api_key

            resolved_key = api_key or get_api_key("TRADIER_API_KEY")
            if not resolved_key:
                raise ValueError(
                    "TRADIER_API_KEY required for Tradier provider. "
                    "Set environment variable or create .env file."
                )

            # Get environment from config
            env = TradierEnvironment.SANDBOX
            if self.config:
                tradier_cfg = self.config.settings.tradier
                if tradier_cfg.is_production:
                    env = TradierEnvironment.PRODUCTION

            self.tradier_provider = TradierProvider(
                api_key=resolved_key,
                environment=env
            )

        if not await self.tradier_provider.is_connected():
            connected = await self.tradier_provider.connect()
            if not connected:
                raise ConnectionError("Failed to connect to Tradier API")

        return self.tradier_provider

    def is_tradier_configured(self) -> bool:
        """Check if Tradier API key is configured."""
        from .utils.secure_config import get_api_key
        try:
            key = get_api_key("TRADIER_API_KEY", required=False)
            return bool(key)
        except (KeyError, ValueError):
            return False

    async def disconnect(self) -> None:
        """Disconnect all services that have connections."""
        if self.provider and hasattr(self.provider, 'disconnect'):
            await self.provider.disconnect()
            logger.debug("Marketdata provider disconnected")

        if self.tradier_provider and hasattr(self.tradier_provider, 'disconnect'):
            await self.tradier_provider.disconnect()
            logger.debug("Tradier provider disconnected")

    def get_stats(self) -> dict:
        """
        Get statistics from all services.

        Returns:
            Dictionary with stats from rate limiter, circuit breaker, caches
        """
        stats = {}

        if self.rate_limiter:
            stats['rate_limiter'] = self.rate_limiter.stats()

        if self.circuit_breaker:
            stats['circuit_breaker'] = self.circuit_breaker.stats()

        if self.historical_cache:
            stats['historical_cache'] = {
                'size': len(self.historical_cache) if hasattr(self.historical_cache, '__len__') else 'N/A',
            }

        if self.earnings_cache:
            stats['earnings_cache'] = {
                'size': len(self.earnings_cache) if hasattr(self.earnings_cache, '__len__') else 'N/A',
            }

        return stats

    def reset(self) -> None:
        """Reset all resettable services (useful for testing)."""
        if self.rate_limiter and hasattr(self.rate_limiter, 'reset'):
            self.rate_limiter.reset()

        if self.circuit_breaker and hasattr(self.circuit_breaker, 'reset'):
            self.circuit_breaker.reset()

        if self.historical_cache and hasattr(self.historical_cache, 'clear'):
            self.historical_cache.clear()

        logger.debug("ServiceContainer reset")

    # =========================================================================
    # ASYNC CONTEXT MANAGER
    # =========================================================================

    async def __aenter__(self) -> 'ServiceContainer':
        """
        Enter async context - ensure provider is connected.

        Usage:
            async with ServiceContainer.create_default() as container:
                quote = await container.provider.get_quote("AAPL")

        Returns:
            Container with connected provider
        """
        await self.ensure_provider()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit async context - disconnect provider.

        Args:
            exc_type: Exception type if any
            exc_val: Exception value if any
            exc_tb: Exception traceback if any
        """
        await self.disconnect()
        return None


# =============================================================================
# GLOBAL CONTAINER (optional, for gradual migration)
# =============================================================================

_default_container: Optional[ServiceContainer] = None


def get_container() -> ServiceContainer:
    """
    Get the default global container.

    Creates one if it doesn't exist. This function exists for gradual
    migration from global singletons - new code should prefer explicit
    dependency injection.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer.create_default()`` instead and pass container
        explicitly to components. Will be removed in v4.0.

    Returns:
        The default ServiceContainer instance
    """
    from .utils.deprecation import warn_singleton_usage
    warn_singleton_usage("get_container", "ServiceContainer.create_default()")

    global _default_container
    if _default_container is None:
        _default_container = ServiceContainer.create_default()
    return _default_container


def set_container(container: ServiceContainer) -> None:
    """
    Set the global container (useful for testing).

    Args:
        container: Container to use as default
    """
    global _default_container
    _default_container = container
    logger.debug("Global container replaced")


def reset_container() -> None:
    """Reset the global container to None (for testing cleanup)."""
    global _default_container
    _default_container = None
    logger.debug("Global container reset to None")
