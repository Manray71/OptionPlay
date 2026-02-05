"""
OptionPlay - Service Registry
=============================

Registry-based Dependency Injection container with recursive resolution.

ATOM Pattern: Register → Resolve → Inject → Reset
-------------------------------------------------
Every service lifecycle follows this flow:
1. REGISTER: Define service factory and its dependencies
2. RESOLVE: Recursively instantiate service and all dependencies
3. INJECT: Provide resolved instance to consumer
4. RESET: Clear instance and cascade to dependents

This module provides:
- ServiceRegistry: Central registry for all services
- Automatic dependency resolution
- Cascading reset for dependent services
- Thread-safe singleton management

Design Goals:
- Replace 87 scattered get_*/reset_* singleton pairs
- Make dependencies explicit and visible
- Enable easy testing through mock injection
- Support gradual migration from existing singletons

Usage::

    from src.core import ServiceRegistry

    # Register services with dependencies
    ServiceRegistry.register(
        "config",
        factory=ConfigLoader,
    )
    ServiceRegistry.register(
        "rate_limiter",
        factory=AdaptiveRateLimiter,
        depends_on=["config"],
    )
    ServiceRegistry.register(
        "provider",
        factory=MarketDataProvider,
        depends_on=["config", "rate_limiter"],
    )

    # Get service (dependencies auto-resolved)
    provider = ServiceRegistry.get("provider")

    # Reset cascades to dependents
    ServiceRegistry.reset("config")  # Also resets rate_limiter, provider

Migration Strategy:
    Phase 2.5 will migrate existing get_*/reset_* pairs to use this registry.
    Until then, both systems coexist.

Note:
    This is separate from src/container.py which is a manual dataclass-based
    container. ServiceRegistry provides automatic dependency resolution.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """
    Central registry for dependency injection with recursive resolution.

    Services are registered with their factory (class or callable) and
    optional dependencies. When a service is requested, all dependencies
    are resolved first, then injected into the factory.

    Thread-Safety:
        All operations are thread-safe via a class-level lock.

    Example:
        >>> ServiceRegistry.register("config", ConfigLoader)
        >>> ServiceRegistry.register("cache", HistoricalCache, depends_on=["config"])
        >>> cache = ServiceRegistry.get("cache")  # Config auto-resolved
    """

    # Class-level storage (singleton pattern at class level)
    _registry: Dict[str, Type] = {}
    _instances: Dict[str, Any] = {}
    _dependencies: Dict[str, List[str]] = {}
    _factory_kwargs: Dict[str, Dict[str, Any]] = {}
    _lock: threading.RLock = threading.RLock()

    # Track which services depend on each service (reverse lookup for reset cascade)
    _dependents: Dict[str, Set[str]] = {}

    @classmethod
    def register(
        cls,
        name: str,
        factory: Union[Type, Callable[..., Any]],
        depends_on: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Register a service factory with optional dependencies.

        Args:
            name: Unique service identifier
            factory: Class or callable that creates the service
            depends_on: List of service names this service depends on
            **kwargs: Additional keyword arguments to pass to factory

        Raises:
            ValueError: If service with this name already registered

        Example:
            >>> ServiceRegistry.register(
            ...     "provider",
            ...     MarketDataProvider,
            ...     depends_on=["config", "rate_limiter"],
            ...     api_key="xxx",
            ... )
        """
        with cls._lock:
            if name in cls._registry:
                logger.warning(f"Service '{name}' already registered, replacing")

            cls._registry[name] = factory
            cls._dependencies[name] = depends_on or []
            cls._factory_kwargs[name] = kwargs

            # Build reverse dependency map for reset cascade
            for dep in cls._dependencies[name]:
                if dep not in cls._dependents:
                    cls._dependents[dep] = set()
                cls._dependents[dep].add(name)

            logger.debug(
                f"Registered service '{name}' with dependencies: {depends_on or []}"
            )

    @classmethod
    def get(cls, name: str) -> Any:
        """
        Get a service instance, resolving dependencies recursively.

        If the service is not yet instantiated, creates it along with
        all its dependencies (depth-first).

        Args:
            name: Service identifier

        Returns:
            The service instance

        Raises:
            KeyError: If service not registered
            RuntimeError: If circular dependency detected

        Example:
            >>> provider = ServiceRegistry.get("provider")
        """
        with cls._lock:
            return cls._resolve(name, resolving=set())

    @classmethod
    def _resolve(cls, name: str, resolving: Set[str]) -> Any:
        """
        Internal recursive resolution with cycle detection.

        Args:
            name: Service to resolve
            resolving: Set of services currently being resolved (for cycle detection)

        Returns:
            Resolved service instance

        Raises:
            KeyError: If service not registered (and not overridden)
            RuntimeError: If circular dependency detected
        """
        # Return cached/overridden instance if available (even without registration)
        if name in cls._instances:
            return cls._instances[name]

        if name not in cls._registry:
            raise KeyError(f"Service '{name}' not registered")

        # Cycle detection
        if name in resolving:
            cycle = " → ".join(list(resolving) + [name])
            raise RuntimeError(f"Circular dependency detected: {cycle}")

        resolving.add(name)

        # Resolve all dependencies first
        deps = {}
        for dep_name in cls._dependencies.get(name, []):
            deps[dep_name] = cls._resolve(dep_name, resolving)

        # Create instance with resolved dependencies and extra kwargs
        factory = cls._registry[name]
        kwargs = {**cls._factory_kwargs.get(name, {})}

        # Inject dependencies as keyword arguments
        # Convention: dependency "config" becomes kwarg "config"
        kwargs.update(deps)

        try:
            instance = factory(**kwargs)
        except TypeError as e:
            # Factory might not accept dependency kwargs, try without
            logger.debug(f"Factory {name} kwargs failed ({e}), trying positional")
            try:
                instance = factory(*deps.values())
            except TypeError:
                # Last resort: no args
                instance = factory()

        cls._instances[name] = instance
        resolving.discard(name)

        logger.debug(f"Created service '{name}'")
        return instance

    @classmethod
    def reset(cls, name: Optional[str] = None) -> None:
        """
        Reset service instance(s), cascading to dependents.

        If name is provided, resets that service and all services that
        depend on it (recursively). If name is None, resets all services.

        Args:
            name: Service to reset (None for all)

        Example:
            >>> ServiceRegistry.reset("config")  # Cascades to dependents
            >>> ServiceRegistry.reset()  # Reset everything
        """
        with cls._lock:
            if name is None:
                # Reset all
                count = len(cls._instances)
                cls._instances.clear()
                logger.debug(f"Reset all services ({count} instances)")
            else:
                cls._reset_cascade(name)

    @classmethod
    def _reset_cascade(cls, name: str) -> None:
        """
        Reset a service and cascade to all its dependents.

        Args:
            name: Service to reset
        """
        if name not in cls._instances:
            return

        # First, reset all services that depend on this one
        for dependent in cls._dependents.get(name, set()):
            cls._reset_cascade(dependent)

        # Then reset this service
        cls._instances.pop(name, None)
        logger.debug(f"Reset service '{name}'")

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """
        Check if a service is registered.

        Args:
            name: Service identifier

        Returns:
            True if registered
        """
        return name in cls._registry

    @classmethod
    def is_instantiated(cls, name: str) -> bool:
        """
        Check if a service has been instantiated.

        Args:
            name: Service identifier

        Returns:
            True if instance exists
        """
        return name in cls._instances

    @classmethod
    def get_dependencies(cls, name: str) -> List[str]:
        """
        Get the dependencies of a service.

        Args:
            name: Service identifier

        Returns:
            List of dependency names

        Raises:
            KeyError: If service not registered
        """
        if name not in cls._registry:
            raise KeyError(f"Service '{name}' not registered")
        return cls._dependencies.get(name, []).copy()

    @classmethod
    def get_dependents(cls, name: str) -> Set[str]:
        """
        Get services that depend on this service.

        Args:
            name: Service identifier

        Returns:
            Set of dependent service names
        """
        return cls._dependents.get(name, set()).copy()

    @classmethod
    def list_services(cls) -> List[str]:
        """
        List all registered service names.

        Returns:
            List of service names
        """
        return list(cls._registry.keys())

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """
        Get registry statistics.

        Returns:
            Dictionary with registry stats
        """
        return {
            "registered": len(cls._registry),
            "instantiated": len(cls._instances),
            "services": {
                name: {
                    "instantiated": name in cls._instances,
                    "dependencies": cls._dependencies.get(name, []),
                    "dependents": list(cls._dependents.get(name, set())),
                }
                for name in cls._registry
            },
        }

    @classmethod
    def clear(cls) -> None:
        """
        Clear all registrations and instances.

        Use for testing cleanup only.
        """
        with cls._lock:
            cls._registry.clear()
            cls._instances.clear()
            cls._dependencies.clear()
            cls._factory_kwargs.clear()
            cls._dependents.clear()
            logger.debug("ServiceRegistry cleared")

    @classmethod
    def override(cls, name: str, instance: Any) -> None:
        """
        Override a service with a specific instance (for testing).

        Args:
            name: Service identifier
            instance: Instance to use

        Example:
            >>> mock_config = Mock()
            >>> ServiceRegistry.override("config", mock_config)
        """
        with cls._lock:
            cls._instances[name] = instance
            logger.debug(f"Service '{name}' overridden with custom instance")


# =============================================================================
# DECORATOR FOR SERVICE REGISTRATION
# =============================================================================


def service(
    name: str,
    depends_on: Optional[List[str]] = None,
    **kwargs: Any,
) -> Callable[[Type], Type]:
    """
    Decorator to register a class as a service.

    Args:
        name: Service identifier
        depends_on: List of dependency names
        **kwargs: Additional factory kwargs

    Returns:
        Decorator function

    Example:
        >>> @service("config")
        ... class ConfigLoader:
        ...     pass
        ...
        >>> @service("cache", depends_on=["config"])
        ... class HistoricalCache:
        ...     def __init__(self, config):
        ...         self.config = config
    """

    def decorator(cls: Type) -> Type:
        ServiceRegistry.register(name, cls, depends_on=depends_on, **kwargs)
        return cls

    return decorator


# =============================================================================
# EXAMPLE REGISTRATIONS (Phase 1 demonstration)
# =============================================================================


def register_example_services() -> None:
    """
    Register example services to demonstrate the ServiceRegistry pattern.

    This function registers 3 core services as a proof-of-concept:
    1. config - Configuration loader (no dependencies)
    2. rate_limiter - Rate limiter (depends on config)
    3. historical_cache - Historical data cache (depends on config)

    Usage:
        >>> from src.core.service_registry import ServiceRegistry, register_example_services
        >>> register_example_services()
        >>> config = ServiceRegistry.get("config")
        >>> limiter = ServiceRegistry.get("rate_limiter")

    Note:
        This is for Phase 1 demonstration only. Full migration of all 87
        singleton pairs will happen in Phase 2.5.
    """
    # Import here to avoid circular imports and allow lazy loading
    from ..config.config_loader import ConfigLoader
    from ..utils.rate_limiter import AdaptiveRateLimiter
    from ..cache.historical_cache import HistoricalCache

    # 1. Config - no dependencies
    ServiceRegistry.register(
        "config",
        ConfigLoader,
    )

    # 2. Rate limiter - depends on config for settings
    def create_rate_limiter(config: ConfigLoader) -> AdaptiveRateLimiter:
        """Factory that creates rate limiter from config."""
        # Use tradier rate limit from config (consistent with existing code)
        rate_limit = getattr(config.settings.tradier, 'rate_limit_per_minute', 120)
        return AdaptiveRateLimiter(
            calls_per_minute=rate_limit,
        )

    ServiceRegistry.register(
        "rate_limiter",
        create_rate_limiter,
        depends_on=["config"],
    )

    # 3. Historical cache - depends on config for TTL settings
    def create_historical_cache(config: ConfigLoader) -> HistoricalCache:
        """Factory that creates historical cache from config."""
        # Use data_sources config (consistent with existing structure)
        ds_cfg = config.settings.data_sources
        return HistoricalCache(
            max_entries=getattr(ds_cfg, 'cache_max_entries', 500),
            ttl_seconds=getattr(ds_cfg, 'cache_ttl_seconds', 900),
        )

    ServiceRegistry.register(
        "historical_cache",
        create_historical_cache,
        depends_on=["config"],
    )

    logger.info(
        f"Registered {len(ServiceRegistry.list_services())} example services: "
        f"{ServiceRegistry.list_services()}"
    )
