# OptionPlay - Data Providers
# ============================

# EarningsInfo, EarningsSource, IVData, IVSource from cache package
from ..cache import EarningsInfo, EarningsSource, IVData, IVSource
from .interface import (
    DataFetcher,
    DataProvider,
    DataProviderRegistry,
    DataQuality,
    HistoricalBar,
    OptionQuote,
    PriceQuote,
)

# IBKR Provider
from .ibkr_provider import IBKRDataProvider, get_ibkr_provider

# Local Database Provider
from .local_db import LocalDBProvider, get_local_db_provider, reset_local_db_provider

# Marketdata.app Provider
from .marketdata import (
    MarketDataConfig,
    MarketDataProvider,
    create_scanner_data_fetcher,
    fetch_historical,
    get_marketdata_provider,
)

# Tradier Provider
from .tradier import (
    TradierConfig,
    TradierEnvironment,
    TradierProvider,
    fetch_option_chain,
    fetch_quote,
    get_tradier_provider,
)

__all__ = [
    # Interface-Klassen
    "DataProvider",
    "DataProviderRegistry",
    "DataFetcher",
    # Quote-Datenklassen (lokal definiert)
    "PriceQuote",
    "OptionQuote",
    "HistoricalBar",
    "DataQuality",
    # Tradier Provider
    "TradierProvider",
    "TradierConfig",
    "TradierEnvironment",
    "get_tradier_provider",
    "fetch_option_chain",
    "fetch_quote",
    # Marketdata.app Provider
    "MarketDataProvider",
    "MarketDataConfig",
    "get_marketdata_provider",
    "fetch_historical",
    "create_scanner_data_fetcher",
    # IBKR Provider
    "IBKRDataProvider",
    "get_ibkr_provider",
    # Local Database Provider
    "LocalDBProvider",
    "get_local_db_provider",
    "reset_local_db_provider",
    # Re-exports aus earnings_cache
    "EarningsInfo",
    "EarningsSource",
    # Re-exports aus iv_cache
    "IVData",
    "IVSource",
]
