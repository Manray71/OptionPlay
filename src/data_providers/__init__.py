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

# EarningsInfo, EarningsSource, IVData, IVSource werden aus den 
# kanonischen Modulen re-exportiert um Abwärtskompatibilität zu gewährleisten
try:
    from ..earnings_cache import EarningsInfo, EarningsSource
    from ..iv_cache import IVData, IVSource
except ImportError:
    from earnings_cache import EarningsInfo, EarningsSource
    from iv_cache import IVData, IVSource

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
    
    # Re-exports aus earnings_cache
    'EarningsInfo',
    'EarningsSource',
    
    # Re-exports aus iv_cache
    'IVData',
    'IVSource'
]
