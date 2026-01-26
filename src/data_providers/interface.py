# OptionPlay - Data Provider Interface
# =====================================
# Abstraktion für austauschbare Datenquellen

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from enum import Enum

# Import der kanonischen Datenklassen aus den Cache-Modulen
# Vermeidet doppelte Definitionen und stellt Konsistenz sicher
try:
    from src.earnings_cache import EarningsInfo, EarningsSource
    from src.iv_cache import IVData, IVSource
except ImportError:
    try:
        from earnings_cache import EarningsInfo, EarningsSource
        from iv_cache import IVData, IVSource
    except ImportError:
        from ..earnings_cache import EarningsInfo, EarningsSource
        from ..iv_cache import IVData, IVSource


class DataQuality(Enum):
    """Qualitätsstufen der Daten"""
    REALTIME = "realtime"
    DELAYED_15MIN = "delayed_15"
    DELAYED_20MIN = "delayed_20"
    END_OF_DAY = "eod"
    UNKNOWN = "unknown"


@dataclass
class PriceQuote:
    """Standard-Preisdaten"""
    symbol: str
    last: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    volume: Optional[int]
    timestamp: datetime
    data_quality: DataQuality
    source: str
    
    @property
    def mid(self) -> Optional[float]:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.last
    
    @property
    def spread(self) -> Optional[float]:
        if self.bid and self.ask:
            return self.ask - self.bid
        return None
    
    def is_valid(self) -> bool:
        """Prüft ob Quote valide ist"""
        return self.bid is not None and self.ask is not None


@dataclass
class OptionQuote:
    """Options-Daten"""
    symbol: str
    underlying: str
    underlying_price: float
    expiry: date
    strike: float
    right: str  # "P" or "C"
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    implied_volatility: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]
    timestamp: datetime
    data_quality: DataQuality
    source: str
    
    @property
    def mid(self) -> Optional[float]:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.last
    
    def is_valid(self) -> bool:
        """Prüft ob Option valide ist"""
        return (
            self.bid is not None and 
            self.ask is not None and
            self.bid > 0
        )


@dataclass
class HistoricalBar:
    """Historische Preisdaten (OHLCV)"""
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


# =============================================================================
# HINWEIS ZU IMPORTIERTEN DATENKLASSEN
# =============================================================================
#
# EarningsInfo wird aus earnings_cache importiert (siehe oben)
# Die kanonische Definition ist in src/earnings_cache.py:
#
# @dataclass
# class EarningsInfo:
#     symbol: str
#     earnings_date: Optional[str]  # ISO Format: YYYY-MM-DD
#     days_to_earnings: Optional[int]
#     source: EarningsSource
#     updated_at: str
#     confirmed: bool = False
#
# -----------------------------------------------------------------------------
#
# IVData wird aus iv_cache importiert (siehe oben)
# Die kanonische Definition ist in src/iv_cache.py:
#
# @dataclass
# class IVData:
#     symbol: str
#     current_iv: Optional[float]      # Dezimal, z.B. 0.35 = 35%
#     iv_rank: Optional[float]         # 0-100%
#     iv_percentile: Optional[float]   # 0-100%
#     iv_high_52w: Optional[float]     # 52-Wochen-Hoch
#     iv_low_52w: Optional[float]      # 52-Wochen-Tief
#     data_points: int                 # Anzahl historischer Datenpunkte
#     source: IVSource                 # Enum: TRADIER, YAHOO, IBKR, etc.
#     updated_at: str                  # ISO Timestamp
#
# =============================================================================


class DataProvider(ABC):
    """
    Abstrakte Basisklasse für Datenquellen.
    Jede Quelle (Tradier, IBKR, etc.) implementiert dieses Interface.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Name des Providers"""
        pass
    
    @property
    @abstractmethod
    def supported_features(self) -> List[str]:
        """Unterstützte Features: quotes, options, historical, earnings, iv"""
        pass
    
    @abstractmethod
    async def connect(self) -> bool:
        """Verbindung herstellen"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Verbindung trennen"""
        pass
    
    @abstractmethod
    async def is_connected(self) -> bool:
        """Verbindungsstatus"""
        pass
    
    # Price Data
    @abstractmethod
    async def get_quote(self, symbol: str) -> Optional[PriceQuote]:
        """Einzelnes Quote"""
        pass
    
    @abstractmethod
    async def get_quotes(self, symbols: List[str]) -> Dict[str, PriceQuote]:
        """Mehrere Quotes"""
        pass
    
    # Historical Data
    @abstractmethod
    async def get_historical(
        self, 
        symbol: str, 
        days: int = 90
    ) -> List[HistoricalBar]:
        """Historische Daten"""
        pass
    
    # Options Data
    @abstractmethod
    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
        dte_min: int = 30,
        dte_max: int = 60,
        right: str = "P"
    ) -> List[OptionQuote]:
        """Options-Chain"""
        pass
    
    @abstractmethod
    async def get_expirations(self, symbol: str) -> List[date]:
        """Verfügbare Verfallstermine"""
        pass
    
    # IV Data
    @abstractmethod
    async def get_iv_data(self, symbol: str) -> Optional[IVData]:
        """
        IV-Rank und IV-Percentile.
        
        Returns:
            IVData aus iv_cache mit Feldern:
            - symbol: str
            - current_iv: Optional[float] (dezimal, z.B. 0.35)
            - iv_rank: Optional[float] (0-100%)
            - iv_percentile: Optional[float] (0-100%)
            - iv_high_52w: Optional[float]
            - iv_low_52w: Optional[float]
            - data_points: int
            - source: IVSource (Enum)
            - updated_at: str
        """
        pass
    
    # Earnings
    @abstractmethod
    async def get_earnings_date(self, symbol: str) -> Optional[EarningsInfo]:
        """
        Nächstes Earnings-Datum.
        
        Returns:
            EarningsInfo aus earnings_cache mit Feldern:
            - symbol: str
            - earnings_date: Optional[str] (ISO Format YYYY-MM-DD)
            - days_to_earnings: Optional[int]
            - source: EarningsSource (Enum)
            - updated_at: str
            - confirmed: bool
        """
        pass


class DataProviderRegistry:
    """
    Registry für alle Datenquellen.
    Ermöglicht Fallback-Logik.
    """
    
    def __init__(self):
        self._providers: Dict[str, DataProvider] = {}
        self._primary: Optional[str] = None
        self._fallbacks: Dict[str, List[str]] = {
            'quotes': [],
            'options': [],
            'historical': [],
            'earnings': [],
            'iv': []
        }
    
    def register(self, provider: DataProvider, primary: bool = False) -> None:
        """Provider registrieren"""
        self._providers[provider.name] = provider
        if primary:
            self._primary = provider.name
            
    def set_fallback_order(self, feature: str, providers: List[str]) -> None:
        """Fallback-Reihenfolge setzen"""
        self._fallbacks[feature] = providers
        
    def get_provider(self, name: str) -> Optional[DataProvider]:
        """Spezifischen Provider"""
        return self._providers.get(name)
    
    def get_primary(self) -> Optional[DataProvider]:
        """Primären Provider"""
        if self._primary:
            return self._providers.get(self._primary)
        return None
    
    def get_providers_for_feature(self, feature: str) -> List[DataProvider]:
        """Provider für Feature in Fallback-Reihenfolge"""
        names = self._fallbacks.get(feature, [])
        return [self._providers[n] for n in names if n in self._providers]


class DataFetcher:
    """
    High-Level Data Fetcher mit Fallback.
    """
    
    def __init__(self, registry: DataProviderRegistry):
        self.registry = registry
        self._cache: Dict[str, Any] = {}
        
    async def get_quote_with_fallback(self, symbol: str) -> Optional[PriceQuote]:
        """Quote mit Fallback bei Fehlern"""
        providers = self.registry.get_providers_for_feature('quotes')
        
        for provider in providers:
            try:
                if not await provider.is_connected():
                    await provider.connect()
                    
                quote = await provider.get_quote(symbol)
                
                if quote and quote.is_valid():
                    return quote
                    
            except Exception as e:
                print(f"[{provider.name}] Error: {e}")
                continue
                
        return None
    
    async def get_options_with_fallback(
        self, 
        symbol: str,
        **kwargs
    ) -> List[OptionQuote]:
        """Options-Chain mit Fallback"""
        providers = self.registry.get_providers_for_feature('options')
        
        for provider in providers:
            try:
                chain = await provider.get_option_chain(symbol, **kwargs)
                
                # Nur valide Options
                valid = [opt for opt in chain if opt.is_valid()]
                
                if valid:
                    return valid
                    
            except Exception as e:
                print(f"[{provider.name}] Error: {e}")
                continue
                
        return []
