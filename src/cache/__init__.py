# OptionPlay - Cache Package
# ===========================
# Caching für Earnings und IV-Daten
#
# Usage:
#     from src.cache import EarningsCache, IVCache, get_earnings, get_iv_rank

from .earnings_cache import (
    # Classes
    EarningsCache,
    EarningsFetcher,
    EarningsInfo,
    EarningsCacheEntry,
    EarningsSource,
    
    # Functions
    get_earnings_cache,
    get_earnings_fetcher,
    get_earnings,
    is_earnings_safe,
)

from .iv_cache import (
    # Classes
    IVCache,
    IVFetcher,
    IVData,
    IVCacheEntry,
    IVSource,
    HistoricalIVFetcher,
    
    # Functions
    calculate_iv_rank,
    calculate_iv_percentile,
    get_iv_cache,
    get_iv_fetcher,
    get_iv_rank,
    is_iv_elevated,
    get_historical_iv_fetcher,
    fetch_iv_history,
    update_iv_cache,
)

from .historical_cache import (
    # Classes
    HistoricalCache,
    HistoricalCacheEntry,
    CacheLookupResult,
    CacheStatus,
    
    # Functions
    get_historical_cache,
    reset_historical_cache,
)

__all__ = [
    # Earnings Classes
    'EarningsCache',
    'EarningsFetcher', 
    'EarningsInfo',
    'EarningsCacheEntry',
    'EarningsSource',
    
    # Earnings Functions
    'get_earnings_cache',
    'get_earnings_fetcher',
    'get_earnings',
    'is_earnings_safe',
    
    # IV Classes
    'IVCache',
    'IVFetcher',
    'IVData',
    'IVCacheEntry',
    'IVSource',
    'HistoricalIVFetcher',
    
    # IV Functions
    'calculate_iv_rank',
    'calculate_iv_percentile',
    'get_iv_cache',
    'get_iv_fetcher',
    'get_iv_rank',
    'is_iv_elevated',
    'get_historical_iv_fetcher',
    'fetch_iv_history',
    'update_iv_cache',
    
    # Historical Cache Classes
    'HistoricalCache',
    'HistoricalCacheEntry',
    'CacheLookupResult',
    'CacheStatus',
    
    # Historical Cache Functions
    'get_historical_cache',
    'reset_historical_cache',
]
