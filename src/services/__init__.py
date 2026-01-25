# OptionPlay - Services Package
# ==============================
"""
Service-Layer für OptionPlay.

Aufgeteilte Business-Logik aus dem ursprünglichen OptionPlayServer "God Object".
Jeder Service hat eine klar definierte Verantwortlichkeit.

Services:
    - VIXService: VIX-Daten und Strategie-Empfehlungen
    - ScannerService: Multi-Strategy Scanning
    - QuoteService: Stock Quotes und Historical Data
    - OptionsService: Options Chain und Strike-Empfehlungen
    - EarningsService: Earnings-Daten und Pre-Filter
    - PortfolioService: Portfolio-Management

Verwendung:
    from src.services import VIXService, ScannerService
    
    vix_service = VIXService(api_key="...")
    vix = await vix_service.get_vix()
    
    scanner = ScannerService(api_key="...")
    result = await scanner.scan_pullback(symbols=["AAPL", "MSFT"])
"""

from .base import BaseService, ServiceContext
from .vix_service import VIXService
from .scanner_service import ScannerService

__all__ = [
    'BaseService',
    'ServiceContext',
    'VIXService',
    'ScannerService',
]
