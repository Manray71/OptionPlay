# OptionPlay - Deprecation Utilities
# ===================================
"""
Utilities für Deprecation-Warnungen bei der Migration zu DI.

Verwendung:
    from src.utils.deprecation import deprecated_singleton

    @deprecated_singleton("get_config", alternative="ServiceContainer.config")
    def get_config() -> ConfigLoader:
        ...

Oder manuell:
    from src.utils.deprecation import warn_singleton_usage

    def get_config() -> ConfigLoader:
        warn_singleton_usage("get_config", "ServiceContainer.config")
        ...
"""

import functools
import logging
import warnings
from typing import Callable, TypeVar, Optional

logger = logging.getLogger(__name__)

# Track which warnings have been issued to avoid spam
_warned_singletons: set = set()


def warn_singleton_usage(
    getter_name: str,
    alternative: str,
    stacklevel: int = 3
) -> None:
    """
    Gibt eine Deprecation-Warnung für Singleton-Getter aus.

    Args:
        getter_name: Name der deprecated Funktion
        alternative: Empfohlene Alternative
        stacklevel: Stack level für die Warnung (default 3 für Decorator)

    Note:
        Warnung wird nur einmal pro getter_name ausgegeben.
    """
    if getter_name in _warned_singletons:
        return

    _warned_singletons.add(getter_name)

    message = (
        f"'{getter_name}()' is deprecated and will be removed in v4.0. "
        f"Use {alternative} instead. "
        f"See docs/migration-to-di.md for migration guide."
    )

    warnings.warn(message, DeprecationWarning, stacklevel=stacklevel)
    logger.debug(f"Deprecation warning issued for: {getter_name}")


T = TypeVar('T')


def deprecated_singleton(
    getter_name: Optional[str] = None,
    alternative: str = "ServiceContainer",
    warn_level: str = "warn"
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator für deprecated Singleton-Getter.

    Args:
        getter_name: Name der Funktion (auto-detected wenn None)
        alternative: Empfohlene Alternative
        warn_level: "warn" für DeprecationWarning, "log" nur für Logging

    Returns:
        Decorator-Funktion

    Example:
        @deprecated_singleton(alternative="container.config")
        def get_config() -> ConfigLoader:
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        name = getter_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            if warn_level == "warn":
                warn_singleton_usage(name, alternative, stacklevel=2)
            elif warn_level == "log":
                if name not in _warned_singletons:
                    _warned_singletons.add(name)
                    logger.warning(
                        f"'{name}()' is deprecated. Use {alternative} instead."
                    )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def reset_warnings() -> None:
    """
    Setzt ausgegebene Warnungen zurück (für Tests).
    """
    global _warned_singletons
    _warned_singletons = set()


def get_warned_singletons() -> set:
    """
    Gibt Liste der bereits gewarnten Singletons zurück (für Tests).
    """
    return _warned_singletons.copy()


# =============================================================================
# SPECIFIC DEPRECATION MESSAGES
# =============================================================================

DEPRECATION_MESSAGES = {
    # Cache singletons
    "get_earnings_cache": "container.earnings_cache",
    "get_earnings_fetcher": "container.earnings_fetcher",
    "get_iv_cache": "container.iv_cache",
    "get_iv_fetcher": "container.iv_fetcher",
    "get_historical_cache": "container.historical_cache",
    "get_historical_iv_fetcher": "container.historical_iv_fetcher",

    # Config singletons
    "get_config": "container.config",
    "get_scan_config": "container.config.get_scan_config()",
    "get_watchlist_loader": "container.config.get_watchlist_loader()",

    # Provider singletons
    "get_marketdata_limiter": "container.rate_limiter",
    "get_circuit_breaker": "container.circuit_breaker",
    "get_circuit_breaker_registry": "container.circuit_breaker_registry",
    "get_request_deduplicator": "container.request_deduplicator",
    "get_orchestrator": "container.orchestrator",
    "get_earnings_aggregator": "container.earnings_aggregator",

    # Portfolio/IBKR
    "get_portfolio_manager": "container.portfolio_manager",
    "get_ibkr_bridge": "container.ibkr_bridge",

    # MCP
    "get_server": "ServerCore.create_default()",
    "get_container": "ServiceContainer.create_default()",
}


def deprecate_getter(getter_name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Convenience-Funktion für Standard-Deprecation mit bekanntem Alternative.

    Args:
        getter_name: Name des Getters (muss in DEPRECATION_MESSAGES sein)

    Returns:
        Decorator

    Example:
        @deprecate_getter("get_config")
        def get_config() -> ConfigLoader:
            ...
    """
    alternative = DEPRECATION_MESSAGES.get(getter_name, "ServiceContainer")
    return deprecated_singleton(getter_name=getter_name, alternative=alternative)
