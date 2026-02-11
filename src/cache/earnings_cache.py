# OptionPlay - Earnings Cache
# ============================
# Re-export der Implementierung für saubere Imports
#
# Usage:
#     from src.cache.earnings_cache import EarningsCache, get_earnings
#     # oder
#     from src.cache import EarningsCache, get_earnings

from .earnings_cache_impl import (  # Classes; Functions; Constants
    DEFAULT_CACHE_FILE,
    DEFAULT_CACHE_MAX_AGE_HOURS,
    EarningsCache,
    EarningsCacheEntry,
    EarningsFetcher,
    EarningsInfo,
    EarningsSource,
    get_earnings,
    get_earnings_cache,
    get_earnings_fetcher,
    is_earnings_safe,
    reset_earnings_cache,
    retry_on_failure,
)

__all__ = [
    # Classes
    "EarningsCache",
    "EarningsFetcher",
    "EarningsInfo",
    "EarningsCacheEntry",
    "EarningsSource",
    # Functions
    "get_earnings_cache",
    "get_earnings_fetcher",
    "reset_earnings_cache",
    "get_earnings",
    "is_earnings_safe",
    "retry_on_failure",
    # Constants
    "DEFAULT_CACHE_FILE",
    "DEFAULT_CACHE_MAX_AGE_HOURS",
]
