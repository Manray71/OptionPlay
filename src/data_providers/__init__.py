# OptionPlay - Data Providers
# ============================

from .interface import (
    DataProvider,
    DataProviderRegistry,
    DataFetcher,
    PriceQuote,
    OptionQuote,
    HistoricalBar,
    DataQuality
)

# Tradier Provider
from .tradier import (
    TradierProvider,
    TradierConfig,
    TradierEnvironment,
    get_tradier_provider,
    fetch_option_chain,
    fetch_quote
)

# Marketdata.app Provider
from .marketdata import (
    MarketDataProvider,
    MarketDataConfig,
    get_marketdata_provider,
    fetch_historical,
    create_scanner_data_fetcher
)

# Local Database Provider
from .local_db import (
    LocalDBProvider,
    get_local_db_provider,
    reset_local_db_provider
)

# EarningsInfo, EarningsSource, IVData, IVSource from cache package
try:
    from ..cache import EarningsInfo, EarningsSource, IVData, IVSource
except ImportError:
    from cache import EarningsInfo, EarningsSource, IVData, IVSource

__all__ = [
    # Interface-Klassen
    'DataProvider',
    'DataProviderRegistry',
    'DataFetcher',
    
    # Quote-Datenklassen (lokal definiert)
    'PriceQuote',
    'OptionQuote',
    'HistoricalBar',
    'DataQuality',
    
    # Tradier Provider
    'TradierProvider',
    'TradierConfig',
    'TradierEnvironment',
    'get_tradier_provider',
    'fetch_option_chain',
    'fetch_quote',
    
    # Marketdata.app Provider
    'MarketDataProvider',
    'MarketDataConfig',
    'get_marketdata_provider',
    'fetch_historical',
    'create_scanner_data_fetcher',

    # Local Database Provider
    'LocalDBProvider',
    'get_local_db_provider',
    'reset_local_db_provider',

    # Re-exports aus earnings_cache
    'EarningsInfo',
    'EarningsSource',
    
    # Re-exports aus iv_cache
    'IVData',
    'IVSource'
]
