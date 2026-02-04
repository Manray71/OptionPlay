# OptionPlay - Marketdata.app Data Provider
# ===========================================
# API Client für marketdata.app
#
# Features:
# - Stock Quotes (real-time)
# - Historical Candles (OHLCV)
# - Options Chains mit Greeks
# - Options Expirations
# - Earnings Daten
# - VIX/Index Daten
#
# API Docs: https://www.marketdata.app/docs/api/
#
# Verwendung:
#     from data_providers.marketdata import MarketDataProvider
#     
#     provider = MarketDataProvider(api_key="your_key")
#     await provider.connect()
#     
#     # Historical Data für Scanner
#     bars = await provider.get_historical("AAPL", days=252)
#     
#     # Options Chain
#     chain = await provider.get_option_chain("AAPL", dte_min=30, dte_max=60)

import asyncio
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

try:
    from .interface import (
        DataProvider,
        DataQuality,
        PriceQuote,
        OptionQuote,
        HistoricalBar
    )
    from ..cache import EarningsInfo, EarningsSource, IVData, IVSource, IVCache, get_iv_cache
except ImportError:
    from data_providers.interface import (
        DataProvider,
        DataQuality,
        PriceQuote,
        OptionQuote,
        HistoricalBar
    )
    from cache import EarningsInfo, EarningsSource, IVData, IVSource, IVCache, get_iv_cache

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class MarketDataConfig:
    """Marketdata.app Konfiguration"""
    api_key: str
    base_url: str = "https://api.marketdata.app"
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    rate_limit_per_minute: int = 100  # Abhängig vom Plan
    
    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }


# =============================================================================
# MARKETDATA PROVIDER
# =============================================================================

class MarketDataProvider(DataProvider):
    """
    Marketdata.app API Data Provider.
    
    Implementiert das DataProvider Interface für marketdata.app's API.
    
    Features:
    - Real-time Stock Quotes
    - Historical Candles (Daily, Intraday)
    - Options Chains mit Greeks und IV
    - Options Expirations und Strikes
    - Earnings Daten
    - Index Daten (VIX etc.)
    
    API Endpoints:
    - /v1/stocks/quotes/{symbol}
    - /v1/stocks/candles/{resolution}/{symbol}
    - /v1/options/chain/{symbol}
    - /v1/options/expirations/{symbol}
    - /v1/stocks/earnings/{symbol}
    - /v1/indices/candles/{resolution}/{symbol}
    
    Verwendung als Context Manager:
        async with MarketDataProvider(api_key) as provider:
            bars = await provider.get_historical("AAPL", days=100)
    """
    
    def __init__(
        self,
        api_key: str,
        iv_cache: Optional[IVCache] = None,
        config: Optional[MarketDataConfig] = None
    ):
        self.config = config or MarketDataConfig(api_key=api_key)
        # Note: Using urllib.request for HTTP calls (Python 3.14 compatible)
        self._connected = False
        self._iv_cache = iv_cache or get_iv_cache()
        self._request_count = 0
        self._last_request_time: Optional[datetime] = None
    
    async def __aenter__(self) -> 'MarketDataProvider':
        """Async Context Manager Entry"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async Context Manager Exit"""
        await self.disconnect()
    
    # =========================================================================
    # DataProvider Interface Implementation
    # =========================================================================
    
    @property
    def name(self) -> str:
        return "marketdata"
    
    @property
    def supported_features(self) -> List[str]:
        return ["quotes", "historical", "options", "expirations", "earnings", "indices"]
    
    async def connect(self) -> bool:
        """Verbindung herstellen (Test mit Quote-Endpoint)"""
        # Using urllib instead of aiohttp/httpx for Python 3.14 compatibility
        try:
            # Test mit SPY Quote
            data = await self._get("/v1/stocks/quotes/SPY/", _skip_connect_check=True)
            self._connected = data is not None and data.get("s") == "ok"

            if self._connected:
                logger.info("Marketdata.app verbunden")
            else:
                logger.warning("Marketdata.app Verbindung fehlgeschlagen")

            return self._connected

        except Exception as e:
            logger.error(f"Marketdata.app Verbindungsfehler: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Verbindung trennen"""
        self._connected = False
        logger.info("Marketdata.app getrennt")

    async def is_connected(self) -> bool:
        """Verbindungsstatus"""
        return self._connected
    
    # =========================================================================
    # Stock Quotes
    # =========================================================================
    
    async def get_quote(self, symbol: str) -> Optional[PriceQuote]:
        """Einzelnes Quote abrufen"""
        data = await self._get(f"/v1/stocks/quotes/{symbol.upper()}/")
        
        if not data or data.get("s") != "ok":
            return None
        
        return self._parse_quote(symbol, data)
    
    async def get_quotes(self, symbols: List[str]) -> Dict[str, PriceQuote]:
        """Mehrere Quotes abrufen (Bulk)"""
        if not symbols:
            return {}
        
        symbols_str = ",".join(s.upper() for s in symbols)
        data = await self._get(f"/v1/stocks/bulkquotes/", params={"symbols": symbols_str})
        
        if not data or data.get("s") != "ok":
            return {}
        
        result = {}
        
        # Bulk response hat Arrays
        symbols_arr = data.get("symbol", [])
        for i, sym in enumerate(symbols_arr):
            try:
                quote = PriceQuote(
                    symbol=sym,
                    last=self._safe_get_index(data.get("last"), i),
                    bid=self._safe_get_index(data.get("bid"), i),
                    ask=self._safe_get_index(data.get("ask"), i),
                    volume=self._safe_get_index(data.get("volume"), i),
                    timestamp=datetime.now(),
                    data_quality=DataQuality.REALTIME,
                    source="marketdata"
                )
                result[sym] = quote
            except Exception as e:
                logger.debug(f"Error parsing quote for {sym}: {e}")
        
        return result
    
    # =========================================================================
    # Historical Data
    # =========================================================================
    
    async def get_historical(
        self,
        symbol: str,
        days: int = 90,
        resolution: str = "D"
    ) -> List[HistoricalBar]:
        """
        Historische Preisdaten abrufen.
        
        Args:
            symbol: Ticker-Symbol
            days: Anzahl Tage (für Berechnung des from-Datums)
            resolution: D=Daily, W=Weekly, M=Monthly, oder Minuten (1, 5, 15, etc.)
            
        Returns:
            Liste von HistoricalBar
        """
        symbol = symbol.upper()
        
        # Berechne Datumsbereich
        to_date = date.today()
        # Mehr Tage für Wochenenden/Feiertage
        from_date = to_date - timedelta(days=int(days * 1.5))
        
        params = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat()
        }
        
        data = await self._get(f"/v1/stocks/candles/{resolution}/{symbol}/", params=params)
        
        if not data or data.get("s") != "ok":
            logger.warning(f"Keine historischen Daten für {symbol}")
            return []
        
        return self._parse_candles(symbol, data, days)
    
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
    
    # =========================================================================
    # Options Data
    # =========================================================================
    
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
        
        # Marketdata.app: Use 'from' and 'to' for date range filtering
        from_date = (date.today() + timedelta(days=dte_min)).isoformat()
        to_date = (date.today() + timedelta(days=dte_max)).isoformat()
        
        params = {
            "from": from_date,
            "to": to_date
        }
        
        # Side Filter
        if right == "P":
            params["side"] = "put"
        elif right == "C":
            params["side"] = "call"
        
        # Spezifischer Verfall (überschreibt from/to)
        if expiry:
            params = {"expiration": expiry.isoformat()}
            if right == "P":
                params["side"] = "put"
            elif right == "C":
                params["side"] = "call"
        
        data = await self._get(f"/v1/options/chain/{symbol}/", params=params)
        
        if not data or data.get("s") != "ok":
            logger.warning(f"Keine Options-Chain für {symbol}")
            return []
        
        # Underlying-Preis holen
        quote = await self.get_quote(symbol)
        underlying_price = quote.last if quote else None
        
        return self._parse_option_chain(symbol, data, underlying_price)
    
    async def get_expirations(self, symbol: str) -> List[date]:
        """Verfügbare Verfallstermine"""
        data = await self._get(f"/v1/options/expirations/{symbol.upper()}/")
        
        if not data or data.get("s") != "ok":
            return []
        
        expirations = data.get("expirations", [])
        
        result = []
        for exp in expirations:
            try:
                if isinstance(exp, int):
                    # Unix timestamp
                    result.append(datetime.fromtimestamp(exp).date())
                else:
                    result.append(datetime.strptime(str(exp), "%Y-%m-%d").date())
            except (ValueError, TypeError):
                continue
        
        return sorted(result)
    
    async def get_strikes(self, symbol: str, expiry: date) -> List[float]:
        """Verfügbare Strikes für einen Verfall"""
        params = {"expiration": expiry.isoformat()}
        data = await self._get(f"/v1/options/strikes/{symbol.upper()}/", params=params)
        
        if not data or data.get("s") != "ok":
            return []
        
        strikes = data.get("strikes", [])
        return sorted([float(s) for s in strikes])
    
    # =========================================================================
    # IV Data
    # =========================================================================
    
    async def get_iv_data(self, symbol: str) -> Optional[IVData]:
        """
        IV-Daten extrahieren aus Options-Chain.
        
        Holt ATM-IV und berechnet IV-Rank aus Cache.
        """
        symbol = symbol.upper()
        
        # Options-Chain für ATM-IV
        chain = await self.get_option_chain(symbol, dte_min=20, dte_max=45, right="P")
        
        if not chain:
            return None
        
        # Quote für ATM-Bestimmung
        quote = await self.get_quote(symbol)
        if not quote or not quote.last:
            return None
        
        # ATM-Option finden
        atm_option = min(chain, key=lambda opt: abs(opt.strike - quote.last))
        atm_iv = atm_option.implied_volatility
        
        if atm_iv is None:
            return None
        
        # IV zu Cache hinzufügen
        self._iv_cache.add_iv_point(symbol, atm_iv, IVSource.MARKETDATA)
        
        return self._iv_cache.get_iv_data(symbol, atm_iv)
    
    # =========================================================================
    # Earnings
    # =========================================================================
    
    async def get_earnings_date(self, symbol: str) -> Optional[EarningsInfo]:
        """Nächstes Earnings-Datum abrufen"""
        data = await self._get(f"/v1/stocks/earnings/{symbol.upper()}/")
        
        if not data or data.get("s") != "ok":
            return None
        
        # Finde nächstes Earnings nach heute
        fiscal_years = data.get("fiscalYear", [])
        fiscal_quarters = data.get("fiscalQuarter", [])
        report_dates = data.get("reportDate", [])
        
        today = date.today()
        next_earnings = None
        
        for i, report_date in enumerate(report_dates):
            try:
                if isinstance(report_date, int):
                    rd = datetime.fromtimestamp(report_date).date()
                else:
                    rd = datetime.strptime(str(report_date), "%Y-%m-%d").date()
                
                if rd >= today:
                    if next_earnings is None or rd < next_earnings:
                        next_earnings = rd
            except (ValueError, TypeError):
                continue
        
        if next_earnings is None:
            return None
        
        days_to = (next_earnings - today).days
        
        return EarningsInfo(
            symbol=symbol.upper(),
            earnings_date=next_earnings.isoformat(),
            days_to_earnings=days_to,
            source=EarningsSource.MARKETDATA,
            updated_at=datetime.now().isoformat(),
            confirmed=True
        )

    async def get_historical_earnings(
        self,
        symbol: str,
        from_date: str = "2020-01-01",
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Historische Earnings-Daten abrufen.

        Args:
            symbol: Ticker-Symbol
            from_date: Start-Datum (ISO format, default: 2020-01-01)
            to_date: End-Datum (ISO format, default: heute)

        Returns:
            Liste von Dicts mit Earnings-Daten:
            - earnings_date: Datum des Earnings-Calls
            - fiscal_year: Geschäftsjahr
            - fiscal_quarter: Q1, Q2, Q3, Q4
            - eps_actual: Tatsächlicher EPS
            - eps_estimate: Erwarteter EPS
            - eps_surprise: Überraschung (absolut)
            - eps_surprise_pct: Überraschung in Prozent
            - time_of_day: 'bmo', 'amc', 'dmh'
        """
        symbol = symbol.upper()

        if to_date is None:
            to_date = date.today().isoformat()

        params = {
            "from": from_date,
            "to": to_date
        }

        data = await self._get(f"/v1/stocks/earnings/{symbol}/", params=params)

        if not data or data.get("s") != "ok":
            logger.debug(f"Keine historischen Earnings für {symbol}")
            return []

        # Parse Arrays aus Response
        report_dates = data.get("reportDate", [])
        fiscal_years = data.get("fiscalYear", [])
        fiscal_quarters = data.get("fiscalQuarter", [])
        report_times = data.get("reportTime", [])
        eps_reported = data.get("epsReported", [])
        eps_estimated = data.get("epsEstimate", [])
        eps_surprise = data.get("epsSurprise", [])
        eps_surprise_pct = data.get("epsSurprisePct", [])

        results = []

        for i in range(len(report_dates)):
            try:
                # Parse Datum
                rd = report_dates[i]
                if isinstance(rd, int):
                    earnings_date = datetime.fromtimestamp(rd).date()
                else:
                    earnings_date = datetime.strptime(str(rd), "%Y-%m-%d").date()

                # Fiscal Quarter formatieren (1 -> Q1, etc.)
                fq = fiscal_quarters[i] if i < len(fiscal_quarters) else None
                quarter_str = f"Q{fq}" if fq else None

                result = {
                    "earnings_date": earnings_date.isoformat(),
                    "fiscal_year": fiscal_years[i] if i < len(fiscal_years) else None,
                    "fiscal_quarter": quarter_str,
                    "eps_actual": self._safe_float(eps_reported[i]) if i < len(eps_reported) else None,
                    "eps_estimate": self._safe_float(eps_estimated[i]) if i < len(eps_estimated) else None,
                    "eps_surprise": self._safe_float(eps_surprise[i]) if i < len(eps_surprise) else None,
                    "eps_surprise_pct": self._safe_float(eps_surprise_pct[i]) if i < len(eps_surprise_pct) else None,
                    "time_of_day": report_times[i] if i < len(report_times) else None
                }
                results.append(result)

            except (ValueError, TypeError, IndexError) as e:
                logger.debug(f"Error parsing earnings record {i} for {symbol}: {e}")
                continue

        # Nach Datum sortieren (neueste zuerst)
        results.sort(key=lambda x: x["earnings_date"], reverse=True)

        logger.debug(f"{symbol}: {len(results)} historische Earnings gefunden")
        return results

    # =========================================================================
    # Index Data (VIX etc.)
    # =========================================================================
    
    async def get_vix(self) -> Optional[float]:
        """
        Aktuellen VIX-Wert abrufen.
        
        Strategie:
        1. Zuerst Candles (funktioniert zuverlässiger)
        2. Dann Quote als Fallback
        
        Note: Das Symbol ist einfach 'VIX' ohne Prefix ($, ^, etc.)
        Siehe: https://www.marketdata.app/docs/api/indices/quotes
        """
        # 1. Versuche Candles (zuverlässiger)
        bars = await self.get_index_candles("VIX", days=5)
        if bars:
            return bars[-1].close
        
        # 2. Fallback: Quote Endpoint
        data = await self._get("/v1/indices/quotes/VIX/")
        if data and data.get("s") == "ok":
            last_values = data.get("last", [])
            if last_values and len(last_values) > 0:
                return float(last_values[0])
        
        return None
    
    async def get_index_candles(
        self,
        symbol: str,
        days: int = 30,
        resolution: str = "D"
    ) -> List[HistoricalBar]:
        """Historische Index-Daten (VIX, SPX etc.)"""
        to_date = date.today()
        from_date = to_date - timedelta(days=int(days * 1.5))
        
        params = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat()
        }
        
        data = await self._get(f"/v1/indices/candles/{resolution}/{symbol.upper()}/", params=params)
        
        if not data or data.get("s") != "ok":
            return []
        
        return self._parse_candles(symbol, data, days)
    
    # =========================================================================
    # Bulk Operations
    # =========================================================================
    
    async def get_historical_bulk(
        self,
        symbols: List[str],
        days: int = 260,
        delay_seconds: float = 0.1
    ) -> Dict[str, Tuple[List[float], List[int], List[float], List[float]]]:
        """
        Historische Daten für mehrere Symbole.
        
        Returns:
            Dict mit Symbol -> (prices, volumes, highs, lows)
        """
        result = {}
        
        for i, symbol in enumerate(symbols):
            try:
                data = await self.get_historical_for_scanner(symbol, days)
                if data:
                    result[symbol.upper()] = data
                    logger.debug(f"[{i+1}/{len(symbols)}] {symbol}: {len(data[0])} Datenpunkte")
            except Exception as e:
                logger.warning(f"Fehler bei {symbol}: {e}")
            
            if i < len(symbols) - 1 and delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
        
        logger.info(f"Historische Daten: {len(result)}/{len(symbols)} Symbole geladen")
        return result
    
    # =========================================================================
    # Private Helpers
    # =========================================================================
    
    async def _get(self, endpoint: str, params: Optional[Dict] = None, _skip_connect_check: bool = False) -> Optional[Dict]:
        """GET Request mit Retry-Logik"""
        # Using synchronous urllib for Python 3.14 compatibility
        # (aiohttp and httpx have issues with Python 3.14's asyncio changes)
        url = f"{self.config.base_url}{endpoint}"
        if params:
            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{param_str}"

        for attempt in range(self.config.max_retries):
            try:
                req = urllib.request.Request(url)
                req.add_header('Authorization', f'Token {self.config.api_key}')

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
                    logger.error("Marketdata.app: Unauthorized - API Key ungültig")
                    return None
                elif e.code == 429:
                    logger.warning("Marketdata.app: Rate Limit erreicht")
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
                    continue
                elif e.code == 402:
                    logger.warning("Marketdata.app: Quota erschöpft")
                    return None
                elif e.code == 404:
                    logger.debug(f"Marketdata.app: Keine Daten für {endpoint}")
                    return None
                else:
                    logger.warning(f"Marketdata.app API Fehler {e.code}: {e.reason}")

            except urllib.error.URLError as e:
                logger.warning(f"Marketdata.app Netzwerkfehler (Versuch {attempt + 1}): {e}")

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay_seconds)

        return None
    
    def _parse_quote(self, symbol: str, data: Dict) -> PriceQuote:
        """Parse Quote Response"""
        return PriceQuote(
            symbol=symbol.upper(),
            last=self._safe_get_first(data.get("last")),
            bid=self._safe_get_first(data.get("bid")),
            ask=self._safe_get_first(data.get("ask")),
            volume=self._safe_int(self._safe_get_first(data.get("volume"))),
            timestamp=datetime.now(),
            data_quality=DataQuality.REALTIME,
            source="marketdata"
        )
    
    def _parse_candles(
        self, 
        symbol: str, 
        data: Dict,
        max_days: int
    ) -> List[HistoricalBar]:
        """Parse Candles Response"""
        bars = []
        
        opens = data.get("o", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        closes = data.get("c", [])
        volumes = data.get("v", [])
        timestamps = data.get("t", [])
        
        for i in range(len(closes)):
            try:
                # Unix Timestamp zu Date
                ts = timestamps[i] if i < len(timestamps) else None
                if ts:
                    bar_date = datetime.fromtimestamp(ts).date()
                else:
                    continue
                
                bar = HistoricalBar(
                    symbol=symbol.upper(),
                    date=bar_date,
                    open=float(opens[i]) if i < len(opens) else 0,
                    high=float(highs[i]) if i < len(highs) else 0,
                    low=float(lows[i]) if i < len(lows) else 0,
                    close=float(closes[i]),
                    volume=int(volumes[i]) if i < len(volumes) else 0,
                    source="marketdata"
                )
                bars.append(bar)
            except (ValueError, IndexError, TypeError) as e:
                logger.debug(f"Error parsing candle {i}: {e}")
                continue
        
        # Nach Datum sortieren
        bars.sort(key=lambda x: x.date)
        
        # Auf max_days begrenzen
        if len(bars) > max_days:
            bars = bars[-max_days:]
        
        return bars
    
    def _parse_option_chain(
        self, 
        symbol: str, 
        data: Dict,
        underlying_price: Optional[float]
    ) -> List[OptionQuote]:
        """Parse Option Chain Response"""
        options = []
        
        # Marketdata.app gibt Arrays zurück
        option_symbols = data.get("optionSymbol", [])
        strikes = data.get("strike", [])
        expirations = data.get("expiration", [])
        sides = data.get("side", [])
        bids = data.get("bid", [])
        asks = data.get("ask", [])
        lasts = data.get("last", [])
        volumes = data.get("volume", [])
        ois = data.get("openInterest", [])
        ivs = data.get("iv", [])
        deltas = data.get("delta", [])
        gammas = data.get("gamma", [])
        thetas = data.get("theta", [])
        vegas = data.get("vega", [])
        
        for i in range(len(option_symbols)):
            try:
                # Expiration parsen
                exp_ts = expirations[i] if i < len(expirations) else None
                if exp_ts:
                    if isinstance(exp_ts, int):
                        expiry = datetime.fromtimestamp(exp_ts).date()
                    else:
                        expiry = datetime.strptime(str(exp_ts), "%Y-%m-%d").date()
                else:
                    continue
                
                # Side
                side = sides[i] if i < len(sides) else ""
                right = "P" if side.lower() == "put" else "C"
                
                option = OptionQuote(
                    symbol=option_symbols[i],
                    underlying=symbol.upper(),
                    underlying_price=underlying_price or 0,
                    expiry=expiry,
                    strike=float(strikes[i]) if i < len(strikes) else 0,
                    right=right,
                    bid=self._safe_float(bids[i]) if i < len(bids) else None,
                    ask=self._safe_float(asks[i]) if i < len(asks) else None,
                    last=self._safe_float(lasts[i]) if i < len(lasts) else None,
                    volume=self._safe_int(volumes[i]) if i < len(volumes) else None,
                    open_interest=self._safe_int(ois[i]) if i < len(ois) else None,
                    implied_volatility=self._safe_float(ivs[i]) if i < len(ivs) else None,
                    delta=self._safe_float(deltas[i]) if i < len(deltas) else None,
                    gamma=self._safe_float(gammas[i]) if i < len(gammas) else None,
                    theta=self._safe_float(thetas[i]) if i < len(thetas) else None,
                    vega=self._safe_float(vegas[i]) if i < len(vegas) else None,
                    timestamp=datetime.now(),
                    data_quality=DataQuality.REALTIME,
                    source="marketdata"
                )
                options.append(option)
                
            except Exception as e:
                logger.debug(f"Error parsing option {i}: {e}")
                continue
        
        return options
    
    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Sichere Float-Konvertierung"""
        if value is None:
            return None
        try:
            return float(value)
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
    
    @staticmethod
    def _safe_get_first(arr: Any) -> Any:
        """Erstes Element aus Array oder None"""
        if arr and isinstance(arr, list) and len(arr) > 0:
            return arr[0]
        return arr if not isinstance(arr, list) else None
    
    @staticmethod
    def _safe_get_index(arr: Any, index: int) -> Any:
        """Element an Index aus Array oder None"""
        if arr and isinstance(arr, list) and len(arr) > index:
            return arr[index]
        return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_provider: Optional[MarketDataProvider] = None


def get_marketdata_provider(api_key: Optional[str] = None) -> MarketDataProvider:
    """
    Gibt globale MarketData Provider Instanz zurück.
    
    Bei erstem Aufruf muss api_key angegeben werden.
    """
    global _default_provider
    
    if _default_provider is None:
        if not api_key:
            raise ValueError("API Key erforderlich beim ersten Aufruf")
        _default_provider = MarketDataProvider(api_key)
    
    return _default_provider


async def fetch_historical(
    symbol: str,
    api_key: str,
    days: int = 252
) -> List[HistoricalBar]:
    """
    Convenience-Funktion für schnellen Historical-Abruf.
    """
    async with MarketDataProvider(api_key) as provider:
        return await provider.get_historical(symbol, days)


async def create_scanner_data_fetcher(api_key: str):
    """
    Erstellt einen Data Fetcher für den MultiStrategyScanner.
    
    Verwendung:
        fetcher = await create_scanner_data_fetcher("your_key")
        scanner = MultiStrategyScanner()
        result = await scanner.scan_async(symbols, fetcher)
    """
    provider = MarketDataProvider(api_key)
    await provider.connect()
    
    async def fetcher(symbol: str):
        return await provider.get_historical_for_scanner(symbol)
    
    return fetcher, provider  # Return provider to disconnect later
