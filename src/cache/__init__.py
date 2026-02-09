# OptionPlay - Cache Package
# ===========================
# Caching for Earnings, IV data, and Historical Data
#
# Usage:
#     from src.cache import EarningsCache, IVCache, get_earnings, get_iv_rank
#     from src.cache import CacheManager, get_cache_manager

from .cache_manager import (
    # Classes
    CacheManager,
    BaseCache,
    CachePolicy,
    CacheEntry,
    CachePriority,

    # Functions
    get_cache_manager,
    reset_cache_manager,
)

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
    reset_earnings_cache,
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
    reset_iv_cache,
    get_iv_rank,
    is_iv_elevated,
    get_historical_iv_fetcher,
    reset_historical_iv_fetcher,
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

from .earnings_history import (
    # Classes
    EarningsHistoryManager,
    EarningsRecord,

    # Functions
    get_earnings_history_manager,
    reset_earnings_history_manager,
)

from .symbol_fundamentals import (
    # Classes
    SymbolFundamentalsManager,
    SymbolFundamentals,

    # Functions
    get_fundamentals_manager,
    reset_fundamentals_manager,
    categorize_market_cap,
)

from .dividend_history import (
    # Classes
    DividendHistoryManager,
    DividendRecord,

    # Functions
    get_dividend_history_manager,
    reset_dividend_history_manager,
)

from .vix_cache import (
    # Classes
    VixCacheManager,
    VixDataPoint,

    # Functions
    get_vix_manager,
    reset_vix_manager,
)

__all__ = [
    # Cache Manager Classes
    'CacheManager',
    'BaseCache',
    'CachePolicy',
    'CacheEntry',
    'CachePriority',

    # Cache Manager Functions
    'get_cache_manager',
    'reset_cache_manager',

    # Earnings Classes
    'EarningsCache',
    'EarningsFetcher', 
    'EarningsInfo',
    'EarningsCacheEntry',
    'EarningsSource',
    
    # Earnings Functions
    'get_earnings_cache',
    'get_earnings_fetcher',
    'reset_earnings_cache',
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
    'reset_iv_cache',
    'get_iv_rank',
    'is_iv_elevated',
    'get_historical_iv_fetcher',
    'reset_historical_iv_fetcher',
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

    # Earnings History Classes
    'EarningsHistoryManager',
    'EarningsRecord',

    # Earnings History Functions
    'get_earnings_history_manager',
    'reset_earnings_history_manager',

    # Symbol Fundamentals Classes
    'SymbolFundamentalsManager',
    'SymbolFundamentals',

    # Symbol Fundamentals Functions
    'get_fundamentals_manager',
    'reset_fundamentals_manager',
    'categorize_market_cap',

    # Dividend History Classes
    'DividendHistoryManager',
    'DividendRecord',

    # Dividend History Functions
    'get_dividend_history_manager',
    'reset_dividend_history_manager',

    # VIX Cache Classes
    'VixCacheManager',
    'VixDataPoint',

    # VIX Cache Functions
    'get_vix_manager',
    'reset_vix_manager',
]
