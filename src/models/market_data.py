# OptionPlay - Market Data Models
# =================================
# Dataclasses für Earnings, IV und andere Marktdaten

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class EarningsSource(Enum):
    """Datenquelle für Earnings"""
    YFINANCE = "yfinance"
    YAHOO_SCRAPE = "yahoo_scrape"
    TRADIER = "tradier"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class IVSource(Enum):
    """Datenquelle für IV-Daten"""
    TRADIER = "tradier"
    CBOE = "cboe"
    CALCULATED = "calculated"
    UNKNOWN = "unknown"


@dataclass
class EarningsInfo:
    """Earnings-Information für ein Symbol"""
    symbol: str
    earnings_date: Optional[str]  # ISO Format: YYYY-MM-DD
    days_to_earnings: Optional[int]
    source: EarningsSource
    updated_at: str  # ISO Format Timestamp
    confirmed: bool = False  # True wenn Datum bestätigt
    
    def is_safe(self, min_days: int = 60) -> bool:
        """Prüft ob genug Abstand zu Earnings"""
        if self.days_to_earnings is None:
            return True  # Unbekannt = akzeptieren (mit Warnung)
        return self.days_to_earnings >= min_days
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'earnings_date': self.earnings_date,
            'days_to_earnings': self.days_to_earnings,
            'source': self.source.value,
            'updated_at': self.updated_at,
            'confirmed': self.confirmed,
            'is_safe_60d': self.is_safe(60)
        }


@dataclass
class IVData:
    """Implied Volatility Daten für ein Symbol"""
    symbol: str
    current_iv: float  # Aktuelle IV in Dezimal (z.B. 0.25 für 25%)
    iv_rank: float  # 0-100
    iv_percentile: float  # 0-100
    hv_20: Optional[float] = None  # 20-Tage Historical Volatility
    hv_50: Optional[float] = None  # 50-Tage Historical Volatility
    iv_hv_ratio: Optional[float] = None  # IV / HV Verhältnis
    source: IVSource = IVSource.UNKNOWN
    updated_at: str = ""
    
    def is_elevated(self, threshold: float = 50.0) -> bool:
        """Prüft ob IV-Rang erhöht ist"""
        return self.iv_rank >= threshold
    
    def iv_regime(self) -> str:
        """Bestimmt IV-Regime"""
        if self.iv_rank >= 80:
            return "very_high"
        elif self.iv_rank >= 50:
            return "elevated"
        elif self.iv_rank >= 20:
            return "normal"
        else:
            return "low"
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'current_iv': round(self.current_iv * 100, 2),  # Als Prozent
            'iv_rank': round(self.iv_rank, 2),
            'iv_percentile': round(self.iv_percentile, 2),
            'hv_20': round(self.hv_20 * 100, 2) if self.hv_20 else None,
            'hv_50': round(self.hv_50 * 100, 2) if self.hv_50 else None,
            'iv_hv_ratio': round(self.iv_hv_ratio, 2) if self.iv_hv_ratio else None,
            'regime': self.iv_regime(),
            'is_elevated': self.is_elevated(),
            'source': self.source.value,
            'updated_at': self.updated_at
        }


@dataclass
class HistoricalBar:
    """Einzelner OHLCV-Datenpunkt"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }
