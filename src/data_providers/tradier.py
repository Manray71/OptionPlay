# OptionPlay - Tradier Data Provider
# ====================================
# Vollständiger Tradier API Client für Options-Daten
#
# Features:
# - Real-time und delayed Quotes
# - Options-Chains mit Greeks und IV (via ORATS)
# - Historische Preisdaten
# - Verfallstermine und Strikes
#
# Verwendung:
#     from data_providers.tradier import TradierProvider
#     
#     provider = TradierProvider(api_key="your_key")
#     await provider.connect()
#     
#     chain = await provider.get_option_chain("AAPL", dte_min=30, dte_max=60)
#     quote = await provider.get_quote("AAPL")

import asyncio
import aiohttp
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

from .interface import (
    DataProvider,
    DataQuality,
    PriceQuote,
    OptionQuote,
    HistoricalBar
)

try:
    from ..cache import EarningsInfo, EarningsSource
except ImportError:
    from cache import EarningsInfo, EarningsSource


# =============================================================================
# HISTORICAL OPTIONS DATA
# =============================================================================

@dataclass
class HistoricalOptionBar:
    """
    Historischer Options-Preis-Datenpunkt von Tradier.

    Tradier liefert OHLCV-Daten für Options via OCC-Symbol.
    """
    symbol: str           # OCC Symbol (z.B. AAPL240119P00150000)
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    underlying_symbol: str
    strike: float
    expiry: date
    option_type: str      # 'P' or 'C'

    @classmethod
    def from_occ_symbol(cls, occ_symbol: str, bar_data: Dict) -> 'HistoricalOptionBar':
        """
        Erstellt HistoricalOptionBar aus OCC-Symbol und Tradier Bar-Daten.

        OCC Format: AAPL240119P00150000
        - AAPL = Underlying (1-6 chars)
        - 240119 = Expiry (YYMMDD)
        - P = Put (or C = Call)
        - 00150000 = Strike * 1000 (8 digits)
        """
        # Parse OCC Symbol
        underlying, expiry, opt_type, strike = parse_occ_symbol(occ_symbol)

        return cls(
            symbol=occ_symbol,
            date=datetime.strptime(bar_data["date"], "%Y-%m-%d").date(),
            open=float(bar_data.get("open", 0)),
            high=float(bar_data.get("high", 0)),
            low=float(bar_data.get("low", 0)),
            close=float(bar_data.get("close", 0)),
            volume=int(bar_data.get("volume", 0)),
            underlying_symbol=underlying,
            strike=strike,
            expiry=expiry,
            option_type=opt_type
        )


def parse_occ_symbol(occ_symbol: str) -> Tuple[str, date, str, float]:
    """
    Parst ein OCC-Options-Symbol.

    Format: AAPL240119P00150000
    - Underlying: Variable Länge (1-6 Zeichen)
    - Expiry: 6 Ziffern (YYMMDD)
    - Type: 1 Zeichen (P oder C)
    - Strike: 8 Ziffern (Strike * 1000)

    Returns:
        Tuple von (underlying, expiry_date, option_type, strike)
    """
    # OCC symbol is always 21 chars for standard options
    # Last 15 chars are: YYMMDD + P/C + 8-digit strike
    if len(occ_symbol) < 15:
        raise ValueError(f"Invalid OCC symbol: {occ_symbol}")

    # Extract from the end
    strike_str = occ_symbol[-8:]  # Last 8 digits
    opt_type = occ_symbol[-9]     # P or C
    expiry_str = occ_symbol[-15:-9]  # YYMMDD
    underlying = occ_symbol[:-15]  # Everything before

    # Parse expiry
    year = 2000 + int(expiry_str[:2])
    month = int(expiry_str[2:4])
    day = int(expiry_str[4:6])
    expiry = date(year, month, day)

    # Parse strike (divide by 1000)
    strike = float(strike_str) / 1000

    return (underlying, expiry, opt_type, strike)


def build_occ_symbol(
    underlying: str,
    expiry: date,
    option_type: str,
    strike: float
) -> str:
    """
    Erstellt ein OCC-Options-Symbol.

    Args:
        underlying: Ticker (z.B. "AAPL")
        expiry: Verfallsdatum
        option_type: "P" oder "C"
        strike: Strike-Preis

    Returns:
        OCC Symbol (z.B. "AAPL240119P00150000")
    """
    # Underlying muss linksbündig sein (max 6 chars)
    underlying = underlying.upper()[:6]

    # Expiry als YYMMDD
    expiry_str = expiry.strftime("%y%m%d")

    # Option type
    opt_type = option_type.upper()[0]

    # Strike als 8-stellige Zahl (Strike * 1000)
    strike_int = int(strike * 1000)
    strike_str = f"{strike_int:08d}"

    return f"{underlying}{expiry_str}{opt_type}{strike_str}"

try:
    from ..cache import IVData, IVSource, IVCache, get_iv_cache
except ImportError:
    from cache import IVData, IVSource, IVCache, get_iv_cache

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

class TradierEnvironment(Enum):
    """Tradier API Umgebungen"""
    PRODUCTION = "production"
    SANDBOX = "sandbox"


@dataclass
class TradierConfig:
    """Tradier Konfiguration"""
    api_key: str
    environment: TradierEnvironment = TradierEnvironment.PRODUCTION
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    rate_limit_per_minute: int = 120  # Tradier Standard-Limit
    
    @property
    def base_url(self) -> str:
        if self.environment == TradierEnvironment.SANDBOX:
            return "https://sandbox.tradier.com"
        return "https://api.tradier.com"
    
    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }


# =============================================================================
# TRADIER PROVIDER
# =============================================================================

class TradierProvider(DataProvider):
    """
    Tradier API Data Provider.
    
    Implementiert das DataProvider Interface für Tradier's Brokerage API.
    
    Features:
    - Quotes (real-time mit Brokerage Account)
    - Options Chains mit Greeks und IV
    - Historische Preisdaten (Aktien und Optionen)
    - Verfallstermine
    
    Hinweis: Greeks und IV-Daten werden von ORATS bereitgestellt.
    
    Verwendung als Context Manager (empfohlen):
        async with TradierProvider(api_key) as provider:
            chain = await provider.get_option_chain("AAPL")
            # Session wird automatisch geschlossen
    
    Oder manuell:
        provider = TradierProvider(api_key)
        await provider.connect()
        try:
            chain = await provider.get_option_chain("AAPL")
        finally:
            await provider.disconnect()
    """
    
    def __init__(
        self,
        api_key: str,
        environment: TradierEnvironment = TradierEnvironment.PRODUCTION,
        iv_cache: Optional[IVCache] = None,
        config: Optional[TradierConfig] = None
    ):
        self.config = config or TradierConfig(
            api_key=api_key,
            environment=environment
        )
        self._session: Optional[aiohttp.ClientSession] = None
        self._connected = False
        self._iv_cache = iv_cache or get_iv_cache()
        self._request_count = 0
        self._last_request_time: Optional[datetime] = None
    
    async def __aenter__(self) -> 'TradierProvider':
        """Async Context Manager Entry - verbindet automatisch."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async Context Manager Exit - trennt automatisch."""
        await self.disconnect()
    
    # =========================================================================
    # DataProvider Interface Implementation
    # =========================================================================
    
    @property
    def name(self) -> str:
        return "tradier"
    
    @property
    def supported_features(self) -> List[str]:
        return ["quotes", "options", "historical", "expirations", "strikes"]
    
    async def connect(self) -> bool:
        """Verbindung herstellen (Test mit Market Clock)"""
        # Using urllib instead of aiohttp for Python 3.14 compatibility
        try:
            clock = await self._get("/v1/markets/clock", _skip_connect_check=True)
            self._connected = clock is not None

            if self._connected:
                logger.info(f"Tradier verbunden ({self.config.environment.value})")
            else:
                logger.warning("Tradier Verbindung fehlgeschlagen")

            return self._connected

        except Exception as e:
            logger.error(f"Tradier Verbindungsfehler: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Verbindung trennen"""
        self._connected = False
        logger.info("Tradier getrennt")

    async def is_connected(self) -> bool:
        """Verbindungsstatus"""
        return self._connected
    
    async def get_quote(self, symbol: str) -> Optional[PriceQuote]:
        """Einzelnes Quote abrufen"""
        quotes = await self.get_quotes([symbol])
        return quotes.get(symbol.upper())
    
    async def get_quotes(self, symbols: List[str]) -> Dict[str, PriceQuote]:
        """Mehrere Quotes abrufen"""
        if not symbols:
            return {}
        
        symbols_str = ",".join(s.upper() for s in symbols)
        
        data = await self._get("/v1/markets/quotes", params={"symbols": symbols_str})
        
        if not data or "quotes" not in data:
            return {}
        
        quotes_data = data["quotes"]
        
        # Handle single quote vs multiple quotes
        if "quote" not in quotes_data:
            return {}
        
        quote_list = quotes_data["quote"]
        if isinstance(quote_list, dict):
            quote_list = [quote_list]
        
        result = {}
        for q in quote_list:
            if q.get("symbol"):
                result[q["symbol"]] = self._parse_quote(q)
        
        return result
    
    async def get_historical(
        self,
        symbol: str,
        days: int = 90,
        interval: str = "daily"
    ) -> List[HistoricalBar]:
        """
        Historische Preisdaten abrufen.
        
        Args:
            symbol: Ticker oder OCC Options-Symbol
            days: Anzahl Tage
            interval: daily, weekly, monthly
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=int(days * 1.5))  # Buffer für Wochenenden
        
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        }
        
        data = await self._get("/v1/markets/history", params=params)
        
        if not data or "history" not in data:
            return []
        
        history = data["history"]
        if not history or "day" not in history:
            return []
        
        days_data = history["day"]
        if isinstance(days_data, dict):
            days_data = [days_data]
        
        bars = []
        for day in days_data:
            try:
                bar = HistoricalBar(
                    symbol=symbol.upper(),
                    date=datetime.strptime(day["date"], "%Y-%m-%d").date(),
                    open=float(day["open"]),
                    high=float(day["high"]),
                    low=float(day["low"]),
                    close=float(day["close"]),
                    volume=int(day.get("volume", 0)),
                    source="tradier"
                )
                bars.append(bar)
            except (KeyError, ValueError) as e:
                logger.warning(f"Fehler beim Parsen von Bar: {e}")
                continue
        
        # Nach Datum sortieren und auf gewünschte Anzahl begrenzen
        bars.sort(key=lambda x: x.date)
        if len(bars) > days:
            bars = bars[-days:]

        return bars

    async def get_historical_for_scanner(
        self,
        symbol: str,
        days: int = 260
    ) -> Optional[Tuple[List[float], List[int], List[float], List[float], List[float]]]:
        """
        Historische Daten im Scanner-Format.

        Returns:
            Tuple von (prices, volumes, highs, lows, opens) oder None
        """
        bars = await self.get_historical(symbol, days)

        if not bars or len(bars) < 50:
            return None

        prices = [bar.close for bar in bars]
        volumes = [bar.volume for bar in bars]
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        opens = [bar.open for bar in bars]

        return prices, volumes, highs, lows, opens

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
        dte_min: int = 30,
        dte_max: int = 60,
        right: str = "P"
    ) -> List[OptionQuote]:
        """
        Options-Chain abrufen.
        
        Args:
            symbol: Underlying Symbol
            expiry: Spezifisches Verfallsdatum (optional)
            dte_min: Minimale Tage bis Verfall
            dte_max: Maximale Tage bis Verfall
            right: "P" für Puts, "C" für Calls, "PC" für beide
        """
        symbol = symbol.upper()
        
        # Underlying-Preis holen
        quote = await self.get_quote(symbol)
        underlying_price = quote.last if quote else None
        
        if not underlying_price:
            logger.warning(f"Kein Underlying-Preis für {symbol}")
            return []
        
        # Verfallstermine bestimmen
        if expiry:
            expirations = [expiry]
        else:
            all_expirations = await self.get_expirations(symbol)
            today = date.today()
            expirations = [
                exp for exp in all_expirations
                if dte_min <= (exp - today).days <= dte_max
            ]
        
        if not expirations:
            logger.warning(f"Keine passenden Verfallstermine für {symbol}")
            return []
        
        # Options-Chain für jeden Verfall holen
        all_options = []
        
        for exp in expirations:
            params = {
                "symbol": symbol,
                "expiration": exp.isoformat(),
                "greeks": "true"
            }
            
            data = await self._get("/v1/markets/options/chains", params=params)
            
            if not data or "options" not in data:
                continue
            
            options_data = data["options"]
            if not options_data or "option" not in options_data:
                continue
            
            option_list = options_data["option"]
            if isinstance(option_list, dict):
                option_list = [option_list]
            
            for opt in option_list:
                option_type = opt.get("option_type", "").upper()
                
                # Filter nach gewünschtem Typ
                if right == "P" and option_type != "PUT":
                    continue
                if right == "C" and option_type != "CALL":
                    continue
                
                parsed = self._parse_option(opt, symbol, underlying_price, exp)
                if parsed:
                    all_options.append(parsed)
        
        return all_options
    
    async def get_expirations(self, symbol: str) -> List[date]:
        """Verfügbare Verfallstermine"""
        params = {"symbol": symbol.upper()}
        
        data = await self._get("/v1/markets/options/expirations", params=params)
        
        if not data or "expirations" not in data:
            return []
        
        exp_data = data["expirations"]
        if not exp_data or "date" not in exp_data:
            return []
        
        dates = exp_data["date"]
        if isinstance(dates, str):
            dates = [dates]
        
        result = []
        for d in dates:
            try:
                result.append(datetime.strptime(d, "%Y-%m-%d").date())
            except ValueError:
                continue
        
        return sorted(result)
    
    async def get_strikes(self, symbol: str, expiry: date) -> List[float]:
        """Verfügbare Strikes für einen Verfall"""
        params = {
            "symbol": symbol.upper(),
            "expiration": expiry.isoformat()
        }
        
        data = await self._get("/v1/markets/options/strikes", params=params)
        
        if not data or "strikes" not in data:
            return []
        
        strikes_data = data["strikes"]
        if not strikes_data or "strike" not in strikes_data:
            return []
        
        strikes = strikes_data["strike"]
        if isinstance(strikes, (int, float)):
            strikes = [strikes]
        
        return sorted([float(s) for s in strikes])
    
    async def get_iv_data(self, symbol: str) -> Optional[IVData]:
        """
        IV-Daten abrufen.
        
        Extrahiert ATM-IV aus der Options-Chain und kombiniert
        sie mit gecachten historischen Daten für IV-Rank.
        """
        symbol = symbol.upper()
        
        # Aktuelle Options-Chain für ATM-IV
        chain = await self.get_option_chain(symbol, dte_min=20, dte_max=45, right="P")
        
        if not chain:
            return None
        
        # Quote für ATM-Bestimmung
        quote = await self.get_quote(symbol)
        if not quote or not quote.last:
            return None
        
        # ATM-Option finden (nächster Strike zum Preis)
        atm_iv = self._extract_atm_iv(chain, quote.last)
        
        if atm_iv is None:
            return None
        
        # IV zu Cache hinzufügen für zukünftige IV-Rank Berechnung
        self._iv_cache.add_iv_point(symbol, atm_iv, IVSource.TRADIER)
        
        # IV-Daten aus Cache holen (mit History für IV-Rank)
        return self._iv_cache.get_iv_data(symbol, atm_iv)
    
    async def get_earnings_date(self, symbol: str) -> Optional[EarningsInfo]:
        """
        Earnings-Datum abrufen.
        
        HINWEIS: Tradier bietet keine Earnings-Daten.
        Diese Methode gibt None zurück. Verwende stattdessen
        den EarningsFetcher mit yfinance.
        """
        logger.debug(f"Tradier hat keine Earnings-Daten für {symbol}")
        return None
    
    # =========================================================================
    # Historical Options Data (NEU)
    # =========================================================================

    async def get_option_history(
        self,
        occ_symbol: str,
        days: int = 90,
        interval: str = "daily"
    ) -> List[HistoricalOptionBar]:
        """
        Historische Preisdaten für eine Option abrufen.

        Args:
            occ_symbol: OCC Options-Symbol (z.B. AAPL240119P00150000)
            days: Anzahl Tage
            interval: daily, weekly, monthly

        Returns:
            Liste von HistoricalOptionBar
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=int(days * 1.5))  # Buffer

        params = {
            "symbol": occ_symbol,
            "interval": interval,
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        }

        data = await self._get("/v1/markets/history", params=params)

        if not data or "history" not in data:
            return []

        history = data["history"]
        if not history or "day" not in history:
            return []

        days_data = history["day"]
        if isinstance(days_data, dict):
            days_data = [days_data]

        bars = []
        for day in days_data:
            try:
                bar = HistoricalOptionBar.from_occ_symbol(occ_symbol, day)
                bars.append(bar)
            except (KeyError, ValueError) as e:
                logger.warning(f"Fehler beim Parsen von Options-Bar: {e}")
                continue

        # Sortieren und begrenzen
        bars.sort(key=lambda x: x.date)
        if len(bars) > days:
            bars = bars[-days:]

        return bars

    async def get_option_history_for_spread(
        self,
        underlying: str,
        short_strike: float,
        long_strike: float,
        expiry: date,
        days: int = 90
    ) -> Dict[str, List[HistoricalOptionBar]]:
        """
        Historische Daten für einen Bull-Put-Spread.

        Args:
            underlying: Underlying Symbol (z.B. "AAPL")
            short_strike: Strike des Short Put
            long_strike: Strike des Long Put
            expiry: Verfallsdatum
            days: Anzahl Tage

        Returns:
            Dict mit {"short": [bars], "long": [bars]}
        """
        short_occ = build_occ_symbol(underlying, expiry, "P", short_strike)
        long_occ = build_occ_symbol(underlying, expiry, "P", long_strike)

        # Parallel abrufen
        short_task = self.get_option_history(short_occ, days)
        long_task = self.get_option_history(long_occ, days)

        short_bars, long_bars = await asyncio.gather(short_task, long_task)

        return {
            "short": short_bars,
            "long": long_bars,
            "short_symbol": short_occ,
            "long_symbol": long_occ
        }

    async def find_historical_options(
        self,
        underlying: str,
        target_date: date,
        strike_range: Tuple[float, float],
        dte_range: Tuple[int, int] = (30, 60),
        option_type: str = "P"
    ) -> List[str]:
        """
        Findet verfügbare historische Options für ein Datum.

        Da Tradier keine Lookup-API für historische Options hat,
        konstruieren wir OCC-Symbole basierend auf den Parametern.

        Args:
            underlying: Ticker
            target_date: Datum für das wir Options suchen
            strike_range: (min_strike, max_strike)
            dte_range: (min_dte, max_dte)
            option_type: "P" oder "C"

        Returns:
            Liste von OCC-Symbolen die getestet werden sollten
        """
        symbols = []
        min_strike, max_strike = strike_range
        min_dte, max_dte = dte_range

        # Generiere mögliche Expiries (monatlich, 3. Freitag)
        for dte in range(min_dte, max_dte + 1, 7):  # Wöchentliche Schritte
            expiry = target_date + timedelta(days=dte)

            # Finde nächsten 3. Freitag (monatlicher Verfall)
            # Vereinfacht: Nimm den 3. Freitag des Monats
            year = expiry.year
            month = expiry.month

            # Erster Tag des Monats
            first_day = date(year, month, 1)
            # Finde ersten Freitag
            days_until_friday = (4 - first_day.weekday()) % 7
            first_friday = first_day + timedelta(days=days_until_friday)
            # 3. Freitag
            third_friday = first_friday + timedelta(weeks=2)

            # Generiere Strikes (in $5 Schritten für höhere Preise, $2.50 für niedrigere)
            strike = min_strike
            while strike <= max_strike:
                occ = build_occ_symbol(underlying, third_friday, option_type, strike)
                if occ not in symbols:
                    symbols.append(occ)

                # Increment based on price level
                if strike < 50:
                    strike += 2.5
                elif strike < 200:
                    strike += 5
                else:
                    strike += 10

        return symbols

    # =========================================================================
    # Tradier-spezifische Methoden
    # =========================================================================

    async def get_market_clock(self) -> Optional[Dict]:
        """Marktstatus und Handelszeiten"""
        data = await self._get("/v1/markets/clock")
        return data.get("clock") if data else None
    
    async def get_market_calendar(self, month: int = None, year: int = None) -> List[Dict]:
        """Handelskalender"""
        params = {}
        if month:
            params["month"] = month
        if year:
            params["year"] = year
        
        data = await self._get("/v1/markets/calendar", params=params)
        
        if not data or "calendar" not in data:
            return []
        
        cal = data["calendar"]
        if "days" not in cal or "day" not in cal["days"]:
            return []
        
        days = cal["days"]["day"]
        return days if isinstance(days, list) else [days]
    
    async def search_symbols(self, query: str) -> List[Dict]:
        """Symbol-Suche"""
        params = {"q": query}
        
        data = await self._get("/v1/markets/search", params=params)
        
        if not data or "securities" not in data:
            return []
        
        securities = data["securities"]
        if not securities or "security" not in securities:
            return []
        
        result = securities["security"]
        return result if isinstance(result, list) else [result]
    
    async def lookup_symbol(self, query: str) -> List[Dict]:
        """Symbol Lookup (exakter Match)"""
        params = {"q": query}
        
        data = await self._get("/v1/markets/lookup", params=params)
        
        if not data or "securities" not in data:
            return []
        
        securities = data["securities"]
        if not securities or "security" not in securities:
            return []
        
        result = securities["security"]
        return result if isinstance(result, list) else [result]
    
    async def get_etb_securities(self) -> List[str]:
        """Easy-to-Borrow Liste"""
        data = await self._get("/v1/markets/etb")
        
        if not data or "securities" not in data:
            return []
        
        securities = data["securities"]
        if not securities or "security" not in securities:
            return []
        
        sec_list = securities["security"]
        if isinstance(sec_list, dict):
            sec_list = [sec_list]
        
        return [s.get("symbol") for s in sec_list if s.get("symbol")]
    
    # =========================================================================
    # Bulk Operations
    # =========================================================================
    
    async def get_quotes_bulk(
        self,
        symbols: List[str],
        batch_size: int = 100
    ) -> Dict[str, PriceQuote]:
        """
        Quotes für viele Symbole in Batches.
        
        Tradier erlaubt bis zu 100 Symbole pro Request.
        """
        all_quotes = {}
        
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            quotes = await self.get_quotes(batch)
            all_quotes.update(quotes)
            
            # Kurze Pause zwischen Batches
            if i + batch_size < len(symbols):
                await asyncio.sleep(0.1)
        
        return all_quotes
    
    async def get_option_chains_bulk(
        self,
        symbols: List[str],
        dte_min: int = 30,
        dte_max: int = 60,
        right: str = "P",
        max_concurrent: int = 5
    ) -> Dict[str, List[OptionQuote]]:
        """
        Options-Chains für mehrere Symbole (parallelisiert).

        Uses semaphore for controlled concurrency to respect rate limits.

        Args:
            symbols: List of stock symbols
            dte_min: Minimum days to expiration
            dte_max: Maximum days to expiration
            right: Option type (P for puts, C for calls)
            max_concurrent: Maximum concurrent requests (default: 5)
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        result: Dict[str, List[OptionQuote]] = {}
        completed = 0
        total = len(symbols)

        async def fetch_one(symbol: str) -> tuple:
            nonlocal completed
            async with semaphore:
                try:
                    chain = await self.get_option_chain(
                        symbol,
                        dte_min=dte_min,
                        dte_max=dte_max,
                        right=right
                    )
                    completed += 1
                    logger.info(f"[{completed}/{total}] {symbol}: {len(chain)} Optionen")
                    return (symbol.upper(), chain)
                except Exception as e:
                    completed += 1
                    logger.error(f"Fehler bei {symbol}: {e}")
                    return (symbol.upper(), [])

        # Run all fetches concurrently with semaphore limiting
        tasks = [fetch_one(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks)

        # Build result dict
        for symbol, chain in results:
            result[symbol] = chain

        return result
    
    async def update_iv_cache_from_chains(
        self,
        symbols: List[str],
        max_concurrent: int = 5
    ) -> Dict[str, bool]:
        """
        IV-Cache für mehrere Symbole aus Options-Chains aktualisieren (parallelisiert).

        Uses semaphore for controlled concurrency to respect rate limits.

        Args:
            symbols: List of stock symbols
            max_concurrent: Maximum concurrent requests (default: 5)
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        results: Dict[str, bool] = {}
        completed = 0
        total = len(symbols)

        async def fetch_one(symbol: str) -> tuple:
            nonlocal completed
            async with semaphore:
                try:
                    iv_data = await self.get_iv_data(symbol)
                    success = iv_data is not None and iv_data.current_iv is not None
                    completed += 1

                    if success:
                        logger.info(f"[{completed}/{total}] {symbol}: IV={iv_data.current_iv:.1%}")
                    else:
                        logger.warning(f"[{completed}/{total}] {symbol}: Keine IV-Daten")

                    return (symbol.upper(), success)
                except Exception as e:
                    completed += 1
                    logger.error(f"Fehler bei {symbol}: {e}")
                    return (symbol.upper(), False)

        # Run all fetches concurrently with semaphore limiting
        tasks = [fetch_one(symbol) for symbol in symbols]
        fetch_results = await asyncio.gather(*tasks)

        # Build result dict
        for symbol, success in fetch_results:
            results[symbol] = success

        successful = sum(1 for v in results.values() if v)
        logger.info(f"IV-Cache Update: {successful}/{len(symbols)} erfolgreich")

        return results
    
    # =========================================================================
    # Private Helpers
    # =========================================================================
    
    async def _get(self, endpoint: str, params: Optional[Dict] = None, _skip_connect_check: bool = False) -> Optional[Dict]:
        """GET Request mit Retry-Logik (urllib für Python 3.14 Kompatibilität)"""
        # Using synchronous urllib for Python 3.14 compatibility
        url = f"{self.config.base_url}{endpoint}"
        if params:
            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{param_str}"

        for attempt in range(self.config.max_retries):
            try:
                req = urllib.request.Request(url)
                req.add_header('Authorization', f'Bearer {self.config.api_key}')
                req.add_header('Accept', 'application/json')

                # Run synchronous urllib in thread pool
                def do_request():
                    with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                        return json.loads(response.read().decode())

                data = await asyncio.to_thread(do_request)
                self._request_count += 1
                self._last_request_time = datetime.now()
                self._connected = True
                return data

            except urllib.error.HTTPError as e:
                self._request_count += 1
                self._last_request_time = datetime.now()

                if e.code == 401:
                    logger.error("Tradier: Unauthorized - API Key ungültig")
                    return None
                elif e.code == 429:
                    logger.warning("Tradier: Rate Limit erreicht, warte...")
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
                    continue
                else:
                    logger.warning(f"Tradier API Fehler {e.code}: {e.reason}")

            except urllib.error.URLError as e:
                logger.warning(f"Tradier Netzwerkfehler (Versuch {attempt + 1}): {e}")

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay_seconds)

        return None
    
    def _parse_quote(self, data: Dict) -> PriceQuote:
        """Tradier Quote zu PriceQuote konvertieren"""
        return PriceQuote(
            symbol=data.get("symbol", ""),
            last=self._safe_float(data.get("last")),
            bid=self._safe_float(data.get("bid")),
            ask=self._safe_float(data.get("ask")),
            volume=self._safe_int(data.get("volume")),
            timestamp=datetime.now(),
            data_quality=DataQuality.REALTIME if data.get("last") else DataQuality.DELAYED_15MIN,
            source="tradier"
        )
    
    def _parse_option(
        self, 
        data: Dict, 
        underlying: str, 
        underlying_price: float,
        expiry: date
    ) -> Optional[OptionQuote]:
        """Tradier Option zu OptionQuote konvertieren"""
        try:
            greeks = data.get("greeks", {}) or {}
            
            return OptionQuote(
                symbol=data.get("symbol", ""),
                underlying=underlying,
                underlying_price=underlying_price,
                expiry=expiry,
                strike=float(data.get("strike", 0)),
                right="P" if data.get("option_type", "").upper() == "PUT" else "C",
                bid=self._safe_float(data.get("bid")),
                ask=self._safe_float(data.get("ask")),
                last=self._safe_float(data.get("last")),
                volume=self._safe_int(data.get("volume")),
                open_interest=self._safe_int(data.get("open_interest")),
                implied_volatility=self._safe_float(greeks.get("mid_iv") or greeks.get("smv_vol")),
                delta=self._safe_float(greeks.get("delta")),
                gamma=self._safe_float(greeks.get("gamma")),
                theta=self._safe_float(greeks.get("theta")),
                vega=self._safe_float(greeks.get("vega")),
                timestamp=datetime.now(),
                data_quality=DataQuality.REALTIME,
                source="tradier"
            )
        except Exception as e:
            logger.warning(f"Fehler beim Parsen von Option: {e}")
            return None
    
    def _extract_atm_iv(
        self, 
        chain: List[OptionQuote], 
        underlying_price: float
    ) -> Optional[float]:
        """ATM-IV aus Options-Chain extrahieren"""
        if not chain or not underlying_price:
            return None
        
        # Finde Option mit nächstem Strike zum Underlying-Preis
        atm_option = min(
            chain,
            key=lambda opt: abs(opt.strike - underlying_price)
        )
        
        return atm_option.implied_volatility
    
    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Sichere Float-Konvertierung"""
        if value is None:
            return None
        try:
            f = float(value)
            return f if f > 0 else None
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """Sichere Int-Konvertierung"""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_provider: Optional[TradierProvider] = None


def get_tradier_provider(
    api_key: Optional[str] = None,
    environment: TradierEnvironment = TradierEnvironment.PRODUCTION
) -> TradierProvider:
    """
    Gibt globale Tradier Provider Instanz zurück.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer.tradier_provider`` instead. Will be removed in v4.0.

    Bei erstem Aufruf muss api_key angegeben werden.
    """
    try:
        from ..utils.deprecation import warn_singleton_usage
        warn_singleton_usage("get_tradier_provider", "container.tradier_provider")
    except ImportError:
        pass

    global _default_provider

    if _default_provider is None:
        if not api_key:
            raise ValueError("API Key erforderlich beim ersten Aufruf")
        _default_provider = TradierProvider(api_key, environment)

    return _default_provider


async def fetch_option_chain(
    symbol: str,
    api_key: str,
    dte_min: int = 30,
    dte_max: int = 60,
    right: str = "P"
) -> List[OptionQuote]:
    """
    Convenience-Funktion für schnellen Options-Chain Abruf.
    
    Beispiel:
        >>> chain = await fetch_option_chain("AAPL", "your_key")
        >>> for opt in chain[:5]:
        ...     print(f"{opt.strike}: IV={opt.implied_volatility:.1%}")
    """
    provider = TradierProvider(api_key)
    
    try:
        await provider.connect()
        return await provider.get_option_chain(
            symbol, 
            dte_min=dte_min, 
            dte_max=dte_max, 
            right=right
        )
    finally:
        await provider.disconnect()


async def fetch_quote(symbol: str, api_key: str) -> Optional[PriceQuote]:
    """
    Convenience-Funktion für schnellen Quote-Abruf.
    """
    provider = TradierProvider(api_key)
    
    try:
        await provider.connect()
        return await provider.get_quote(symbol)
    finally:
        await provider.disconnect()
