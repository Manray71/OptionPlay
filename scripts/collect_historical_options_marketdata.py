#!/usr/bin/env python3
"""
OptionPlay - Historical Options Data Collector (Marketdata.app)
===============================================================

Sammelt historische End-of-Day Options-Daten von Marketdata.app und
berechnet Greeks mit dem kalibrierten Black-Scholes Modell.

Marketdata.app liefert für historische Daten:
- Bid/Ask/Mid/Last Preise
- Volume, Open Interest
- KEINE Greeks (nur für Live-Daten)

Dieses Script:
1. Ruft historische Options-Chains ab (mit date Parameter)
2. Berechnet IV aus Mid-Price mit Newton-Raphson
3. Berechnet Greeks (Delta, Gamma, Theta, Vega) mit Black-Scholes
4. Wendet kalibrierte Symbol-Korrekturfaktoren an
5. Speichert alles in der SQLite-Datenbank

Usage:
    # Test mit wenigen Symbolen
    python scripts/collect_historical_options_marketdata.py --test

    # Spezifische Symbole
    python scripts/collect_historical_options_marketdata.py --symbols AAPL,MSFT,SPY

    # Alle Watchlist-Symbole (mit Rate-Limiting)
    python scripts/collect_historical_options_marketdata.py --all --days 30

    # Status prüfen
    python scripts/collect_historical_options_marketdata.py --status
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

import aiohttp
import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.pricing.black_scholes import (
    black_scholes_put,
    black_scholes_call,
    black_scholes_greeks,
    implied_volatility,
    estimate_iv_calibrated,
    get_symbol_iv_multiplier,
)
from src.config.watchlist_loader import get_watchlist_loader

# Logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class HistoricalOptionQuote:
    """Historische Options-Quote mit berechneten Greeks"""

    # Identifikation
    occ_symbol: str
    underlying: str
    expiration: date
    strike: float
    option_type: str  # 'P' or 'C'

    # Marktdaten (von Marketdata.app)
    quote_date: date
    bid: float
    ask: float
    mid: float
    last: Optional[float]
    volume: int
    open_interest: int
    underlying_price: float

    # Berechnete Werte
    dte: int
    moneyness: float  # strike / underlying_price

    # Berechnete Greeks (Black-Scholes mit Kalibrierung)
    iv_calculated: float  # Aus Mid-Price berechnet
    delta: float
    gamma: float
    theta: float
    vega: float

    # Meta
    iv_calibration_factor: float  # Angewendeter Korrekturfaktor


@dataclass
class CollectionStats:
    """Statistiken einer Sammlungssession"""

    symbols_requested: int = 0
    symbols_processed: int = 0
    symbols_failed: int = 0
    dates_processed: int = 0
    options_collected: int = 0
    options_with_greeks: int = 0
    api_calls: int = 0
    errors: List[str] = field(default_factory=list)


# =============================================================================
# DATABASE SCHEMA EXTENSION
# =============================================================================


def ensure_schema(db_path: str):
    """Stellt sicher, dass die erweiterte Tabelle existiert"""
    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Erweiterte Options-Tabelle mit Greeks
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historical_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occ_symbol TEXT NOT NULL,
            underlying TEXT NOT NULL,
            expiration TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            quote_date TEXT NOT NULL,

            -- Marktdaten
            bid REAL,
            ask REAL,
            mid REAL,
            last REAL,
            volume INTEGER,
            open_interest INTEGER,
            underlying_price REAL,

            -- Berechnete Werte
            dte INTEGER,
            moneyness REAL,

            -- Berechnete Greeks
            iv_calculated REAL,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,

            -- Meta
            iv_calibration_factor REAL,
            created_at TEXT,

            UNIQUE(occ_symbol, quote_date)
        )
    """)

    # Indices für schnelle Abfragen
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hist_opt_underlying
        ON historical_options(underlying)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hist_opt_date
        ON historical_options(quote_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hist_opt_delta
        ON historical_options(delta)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hist_opt_expiration
        ON historical_options(expiration)
    """)

    conn.commit()
    conn.close()

    logger.info("Database schema verified/created")


def store_historical_options(db_path: str, options: List[HistoricalOptionQuote]) -> int:
    """Speichert historische Options-Daten in der Datenbank"""
    import sqlite3

    if not options:
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    now = datetime.now().isoformat()
    stored = 0

    for opt in options:
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO historical_options (
                    occ_symbol, underlying, expiration, strike, option_type,
                    quote_date, bid, ask, mid, last, volume, open_interest,
                    underlying_price, dte, moneyness,
                    iv_calculated, delta, gamma, theta, vega,
                    iv_calibration_factor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    opt.occ_symbol,
                    opt.underlying,
                    opt.expiration.isoformat(),
                    opt.strike,
                    opt.option_type,
                    opt.quote_date.isoformat(),
                    opt.bid,
                    opt.ask,
                    opt.mid,
                    opt.last,
                    opt.volume,
                    opt.open_interest,
                    opt.underlying_price,
                    opt.dte,
                    opt.moneyness,
                    opt.iv_calculated,
                    opt.delta,
                    opt.gamma,
                    opt.theta,
                    opt.vega,
                    opt.iv_calibration_factor,
                    now,
                ),
            )
            stored += 1
        except Exception as e:
            logger.debug(f"Error storing {opt.occ_symbol}: {e}")

    conn.commit()
    conn.close()

    return stored


# =============================================================================
# MARKETDATA.APP CLIENT
# =============================================================================


class MarketdataOptionsClient:
    """Client für Marketdata.app Options API"""

    BASE_URL = "https://api.marketdata.app"

    # Quant Plan: 10,000 credits/minute
    # Konservativ: 8,000 requests/minute = ~133 requests/sekunde
    # Wir nutzen 100 requests/sekunde als sicheren Wert
    DEFAULT_REQUESTS_PER_MINUTE = 6000  # 100/sec, lässt Puffer

    def __init__(self, api_key: str, requests_per_minute: int = None):
        self.api_key = api_key
        self.requests_per_minute = requests_per_minute or self.DEFAULT_REQUESTS_PER_MINUTE
        self.rate_limit_delay = 60.0 / self.requests_per_minute  # Sekunden zwischen Requests
        self.session: Optional[aiohttp.ClientSession] = None
        self._last_request_time = 0
        self._requests_this_minute = 0
        self._minute_start = 0

    async def __aenter__(self):
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        self.session = aiohttp.ClientSession(headers=headers)
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def _rate_limit(self):
        """
        Rate-Limiting basierend auf Quant Plan (10,000 credits/minute).

        Verwendet einen gleitenden Fenster-Ansatz um gleichmäßige
        Verteilung der Requests über die Minute zu gewährleisten.
        """
        import time

        current_time = time.time()

        # Neues Minuten-Fenster?
        if current_time - self._minute_start >= 60:
            self._minute_start = current_time
            self._requests_this_minute = 0

        # Limit erreicht? Warte bis nächste Minute
        if self._requests_this_minute >= self.requests_per_minute:
            wait_time = 60 - (current_time - self._minute_start)
            if wait_time > 0:
                logger.debug(f"Rate limit reached, waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
                self._minute_start = time.time()
                self._requests_this_minute = 0

        # Minimaler Delay zwischen Requests für gleichmäßige Verteilung
        elapsed = current_time - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)

        self._last_request_time = time.time()
        self._requests_this_minute += 1

    async def get_historical_chain(
        self,
        symbol: str,
        quote_date: date,
        dte_min: int = 7,
        dte_max: int = 60,
        delta_min: float = 0.03,
        delta_max: float = 0.40,
    ) -> Tuple[List[Dict], Optional[str]]:
        """
        Holt historische Options-Chain für ein Datum.

        Da Marketdata.app keinen Delta-Filter für historische Daten hat,
        holen wir alle Daten und filtern später.

        Returns:
            Tuple von (options_list, error_message)
        """
        await self._rate_limit()

        # Calculate expiration date range from quote_date
        exp_from = (quote_date + timedelta(days=dte_min)).isoformat()
        exp_to = (quote_date + timedelta(days=dte_max)).isoformat()

        params = {
            "date": quote_date.isoformat(),
            "from": exp_from,  # Expiration from
            "to": exp_to,  # Expiration to
        }

        url = f"{self.BASE_URL}/v1/options/chain/{symbol}/"

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 404:
                    return [], "no_data"

                if resp.status not in [200, 203]:
                    text = await resp.text()
                    return [], f"HTTP {resp.status}: {text[:100]}"

                data = await resp.json()

                if data.get("s") != "ok":
                    return [], data.get("errmsg", "unknown error")

                # Parse response arrays into list of dicts
                options = []
                n = len(data.get("optionSymbol", []))

                for i in range(n):
                    opt = {
                        "occ_symbol": data["optionSymbol"][i],
                        "underlying": data["underlying"][i] if "underlying" in data else symbol,
                        "expiration": data["expiration"][i],
                        "strike": data["strike"][i],
                        "side": data["side"][i],
                        "bid": data["bid"][i],
                        "ask": data["ask"][i],
                        "mid": data["mid"][i] if "mid" in data else None,
                        "last": data["last"][i] if "last" in data else None,
                        "volume": data["volume"][i] if "volume" in data else 0,
                        "open_interest": data["openInterest"][i] if "openInterest" in data else 0,
                        "underlying_price": (
                            data["underlyingPrice"][i] if "underlyingPrice" in data else None
                        ),
                        "dte": data["dte"][i] if "dte" in data else None,
                    }

                    # Calculate mid if not provided
                    if opt["mid"] is None and opt["bid"] and opt["ask"]:
                        opt["mid"] = (opt["bid"] + opt["ask"]) / 2

                    options.append(opt)

                return options, None

        except Exception as e:
            return [], str(e)

    async def get_spot_price(self, symbol: str, quote_date: date) -> Optional[float]:
        """Holt historischen Spot-Preis"""
        await self._rate_limit()

        params = {
            "from": quote_date.isoformat(),
            "to": (quote_date + timedelta(days=1)).isoformat(),
        }

        url = f"{self.BASE_URL}/v1/stocks/candles/D/{symbol}/"

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status not in [200, 203]:
                    return None

                data = await resp.json()
                if data.get("s") == "ok" and data.get("c"):
                    return data["c"][0]  # Close price

                return None
        except:
            return None


# =============================================================================
# GREEKS CALCULATOR
# =============================================================================


class GreeksCalculator:
    """Berechnet Greeks mit kalibriertem Black-Scholes Modell"""

    def __init__(self, risk_free_rate: float = 0.05):
        self.risk_free_rate = risk_free_rate
        self._hv_cache: Dict[str, Dict[date, float]] = {}
        self._vix_cache: Dict[date, float] = {}

    def load_vix_data(self, db_path: str):
        """Lädt VIX-Daten aus der Datenbank"""
        import sqlite3

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT date, value FROM vix_data")

            for row in cursor.fetchall():
                vix_date = date.fromisoformat(row[0])
                self._vix_cache[vix_date] = row[1]

            conn.close()
            logger.info(f"Loaded {len(self._vix_cache)} VIX data points")
        except Exception as e:
            logger.warning(f"Could not load VIX data: {e}")

    def load_hv_data(self, db_path: str, symbols: List[str], window: int = 20):
        """Berechnet und cached Historical Volatility für alle Symbole"""
        import sqlite3

        conn = sqlite3.connect(db_path)

        for symbol in symbols:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT date, close FROM (
                        SELECT date, close FROM price_data
                        WHERE symbol = ?
                        ORDER BY date DESC
                    ) ORDER BY date ASC
                """,
                    (symbol,),
                )

                rows = cursor.fetchall()
                if len(rows) < window + 1:
                    continue

                # Berechne HV für jeden Tag
                prices = [(date.fromisoformat(r[0]), r[1]) for r in rows]
                hv_dict = {}

                for i in range(window, len(prices)):
                    window_prices = [p[1] for p in prices[i - window : i + 1]]
                    returns = np.log(np.array(window_prices[1:]) / np.array(window_prices[:-1]))
                    hv = float(np.std(returns, ddof=1) * np.sqrt(252))
                    hv_dict[prices[i][0]] = hv

                self._hv_cache[symbol] = hv_dict

            except Exception as e:
                logger.debug(f"Could not calculate HV for {symbol}: {e}")

        conn.close()
        logger.info(f"Calculated HV for {len(self._hv_cache)} symbols")

    def get_hv(self, symbol: str, quote_date: date) -> Optional[float]:
        """Gibt HV für Symbol und Datum zurück"""
        if symbol not in self._hv_cache:
            return None

        hv_dict = self._hv_cache[symbol]

        # Suche exaktes oder nächstgelegenes Datum
        if quote_date in hv_dict:
            return hv_dict[quote_date]

        # Finde nächstes verfügbares Datum
        available_dates = sorted(hv_dict.keys())
        for d in reversed(available_dates):
            if d <= quote_date:
                return hv_dict[d]

        return None

    def get_vix(self, quote_date: date) -> Optional[float]:
        """Gibt VIX für Datum zurück"""
        if quote_date in self._vix_cache:
            return self._vix_cache[quote_date]

        # Finde nächstes verfügbares Datum
        available_dates = sorted(self._vix_cache.keys())
        for d in reversed(available_dates):
            if d <= quote_date:
                return self._vix_cache[d]

        return None

    def calculate_greeks(
        self,
        option_data: Dict,
        symbol: str,
        quote_date: date,
    ) -> Optional[HistoricalOptionQuote]:
        """
        Berechnet Greeks für eine Option.

        1. Berechnet IV aus Mid-Price (Newton-Raphson)
        2. Falls nicht konvergiert: Schätzt IV mit kalibrierter Formel
        3. Berechnet alle Greeks mit Black-Scholes
        """
        # Extrahiere Daten
        strike = option_data["strike"]
        underlying_price = option_data.get("underlying_price")
        mid_price = option_data.get("mid")
        bid = option_data.get("bid", 0)
        ask = option_data.get("ask", 0)

        # Validierung
        if not underlying_price or underlying_price <= 0:
            return None
        if not mid_price or mid_price <= 0:
            if bid and ask:
                mid_price = (bid + ask) / 2
            else:
                return None

        # Parse expiration
        exp_str = option_data["expiration"]
        if isinstance(exp_str, int):
            expiration = date.fromtimestamp(exp_str)
        else:
            expiration = date.fromisoformat(str(exp_str)[:10])

        # DTE
        dte = (expiration - quote_date).days
        if dte <= 0:
            return None

        T = dte / 365.0

        # Moneyness
        moneyness = strike / underlying_price

        # Option type
        side = option_data.get("side", "put").lower()
        option_type = "P" if side == "put" else "C"

        # 1. Versuche IV aus Mid-Price zu berechnen
        iv_from_price = implied_volatility(
            mid_price, underlying_price, strike, T, self.risk_free_rate, option_type
        )

        # 2. Falls nicht konvergiert, schätze IV
        calibration_factor = get_symbol_iv_multiplier(symbol)

        if iv_from_price is not None and 0.05 <= iv_from_price <= 2.0:
            iv_calculated = iv_from_price
        else:
            # Fallback: Schätze IV aus HV mit Kalibrierung
            hv = self.get_hv(symbol, quote_date)
            vix = self.get_vix(quote_date)

            if hv is None:
                hv = 0.25  # Default fallback

            iv_calculated = estimate_iv_calibrated(
                historical_volatility=hv,
                symbol=symbol,
                vix=vix,
                moneyness=moneyness,
                dte=dte,
            )

        # 3. Berechne Greeks
        greeks = black_scholes_greeks(
            S=underlying_price,
            K=strike,
            T=T,
            r=self.risk_free_rate,
            sigma=iv_calculated,
            option_type=option_type,
        )

        return HistoricalOptionQuote(
            occ_symbol=option_data["occ_symbol"],
            underlying=symbol,
            expiration=expiration,
            strike=strike,
            option_type=option_type,
            quote_date=quote_date,
            bid=bid,
            ask=ask,
            mid=mid_price,
            last=option_data.get("last"),
            volume=option_data.get("volume", 0) or 0,
            open_interest=option_data.get("open_interest", 0) or 0,
            underlying_price=underlying_price,
            dte=dte,
            moneyness=moneyness,
            iv_calculated=iv_calculated,
            delta=greeks.delta,
            gamma=greeks.gamma,
            theta=greeks.theta,
            vega=greeks.vega,
            iv_calibration_factor=calibration_factor,
        )


# =============================================================================
# COLLECTOR
# =============================================================================


class HistoricalOptionsCollector:
    """Hauptklasse für die Datensammlung mit parallelen Workers"""

    def __init__(
        self,
        api_key: str,
        db_path: str,
        delta_min: float = 0.03,
        delta_max: float = 0.40,
        dte_min: int = 7,
        dte_max: int = 60,
        requests_per_minute: int = 6000,  # Quant Plan: 10k/min, wir nutzen 6k
        concurrent_workers: int = 10,  # Parallele API-Anfragen
    ):
        self.api_key = api_key
        self.db_path = db_path
        self.delta_min = delta_min
        self.delta_max = delta_max
        self.dte_min = dte_min
        self.dte_max = dte_max
        self.requests_per_minute = requests_per_minute
        self.concurrent_workers = concurrent_workers

        self.calculator = GreeksCalculator()
        self.stats = CollectionStats()
        self._progress_lock = asyncio.Lock()
        self._current_op = 0

    async def _process_symbol_date(
        self,
        client: MarketdataOptionsClient,
        symbol: str,
        trade_date: date,
        semaphore: asyncio.Semaphore,
    ) -> List[HistoricalOptionQuote]:
        """Verarbeitet ein Symbol für ein Datum (Worker-Task)"""
        async with semaphore:
            options_data, error = await client.get_historical_chain(
                symbol, trade_date, self.dte_min, self.dte_max
            )

            if error or not options_data:
                return []

            # Berechne Greeks und filtere nach Delta
            processed = []
            for opt_data in options_data:
                quote = self.calculator.calculate_greeks(opt_data, symbol, trade_date)
                if quote and self.delta_min <= abs(quote.delta) <= self.delta_max:
                    processed.append(quote)

            return processed

    async def collect(
        self,
        symbols: List[str],
        days_back: int = 30,
        progress_callback=None,
    ) -> CollectionStats:
        """
        Sammelt historische Options-Daten für alle Symbole mit parallelen Workers.

        Args:
            symbols: Liste der Symbole
            days_back: Tage in die Vergangenheit
            progress_callback: Optional callback(symbol, current, total, status)
        """
        # Schema sicherstellen
        ensure_schema(self.db_path)

        # Lade Hilfsdaten
        logger.info("Loading historical volatility and VIX data...")
        self.calculator.load_vix_data(self.db_path)
        self.calculator.load_hv_data(self.db_path, symbols)

        # Handelstage generieren (Mo-Fr)
        trade_dates = []
        current_date = date.today() - timedelta(days=1)  # Gestern starten

        while len(trade_dates) < days_back:
            if current_date.weekday() < 5:  # Mo-Fr
                trade_dates.append(current_date)
            current_date -= timedelta(days=1)

        trade_dates = list(reversed(trade_dates))  # Älteste zuerst
        logger.info(f"Will collect data for {len(trade_dates)} trading days")
        logger.info(f"Using {self.concurrent_workers} concurrent workers")

        self.stats.symbols_requested = len(symbols)
        total_ops = len(symbols) * len(trade_dates)
        self._current_op = 0

        # Semaphore für Rate-Limiting (concurrent requests)
        semaphore = asyncio.Semaphore(self.concurrent_workers)

        async with MarketdataOptionsClient(self.api_key, self.requests_per_minute) as client:
            # Verarbeite Symbole in Batches
            batch_size = 50  # Symbole pro Batch für DB-Write

            for batch_start in range(0, len(symbols), batch_size):
                batch_symbols = symbols[batch_start : batch_start + batch_size]
                batch_options = []

                # Erstelle Tasks für alle Symbol-Datum-Kombinationen im Batch
                tasks = []
                task_info = []
                for symbol in batch_symbols:
                    for trade_date in trade_dates:
                        task = self._process_symbol_date(client, symbol, trade_date, semaphore)
                        tasks.append(task)
                        task_info.append((symbol, trade_date))

                # Führe alle Tasks PARALLEL aus mit asyncio.gather
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verarbeite Ergebnisse
                for i, result in enumerate(results):
                    symbol, trade_date = task_info[i]
                    self._current_op += 1
                    self.stats.api_calls += 1

                    if isinstance(result, Exception):
                        self.stats.errors.append(f"{symbol}/{trade_date}: {str(result)}")
                    elif result:
                        batch_options.extend(result)
                        self.stats.options_with_greeks += len(result)

                if progress_callback:
                    progress_callback(
                        batch_symbols[-1],
                        self._current_op,
                        total_ops,
                        f"Batch {batch_start//batch_size + 1}",
                    )

                # Batch in DB speichern
                if batch_options:
                    stored = store_historical_options(self.db_path, batch_options)
                    self.stats.options_collected += stored
                    self.stats.dates_processed += len(batch_symbols) * len(trade_dates)

                # Stats pro Symbol im Batch
                symbols_in_batch = set(opt.underlying for opt in batch_options)
                self.stats.symbols_processed += len(symbols_in_batch)
                self.stats.symbols_failed += len(batch_symbols) - len(symbols_in_batch)

                logger.info(
                    f"Batch {batch_start//batch_size + 1}: {len(batch_options)} options from {len(symbols_in_batch)} symbols"
                )

        return self.stats


# =============================================================================
# CLI
# =============================================================================


def get_api_key() -> str:
    """API Key laden"""
    api_key = os.environ.get("MARKETDATA_API_KEY")

    if not api_key:
        config_file = Path.home() / ".optionplay" / "config.json"
        if config_file.exists():
            with open(config_file) as f:
                config = json.load(f)
                api_key = config.get("marketdata_api_key")

    if not api_key:
        # Try .env
        env_file = project_root / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith("MARKETDATA_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break

    if not api_key:
        print("ERROR: No API key found!")
        print("Set MARKETDATA_API_KEY or add to ~/.optionplay/config.json")
        sys.exit(1)

    return api_key


def get_db_path() -> str:
    """Datenbank-Pfad"""
    return str(Path.home() / ".optionplay" / "trades.db")


def show_status():
    """Zeigt Status der gesammelten Options-Daten"""
    import sqlite3

    db_path = get_db_path()

    if not Path(db_path).exists():
        print("Database not found")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("HISTORICAL OPTIONS DATA STATUS")
    print("=" * 70)

    # Check if table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='historical_options'
    """)

    if not cursor.fetchone():
        print("\nNo historical options data table found.")
        print("Run collection first.")
        conn.close()
        return

    # Stats
    cursor.execute("SELECT COUNT(*) FROM historical_options")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT underlying) FROM historical_options")
    symbols = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT quote_date) FROM historical_options")
    dates = cursor.fetchone()[0]

    cursor.execute("SELECT MIN(quote_date), MAX(quote_date) FROM historical_options")
    date_range = cursor.fetchone()

    print(f"\nTotal Options Records: {total:,}")
    print(f"Symbols with Data: {symbols}")
    print(f"Trading Days: {dates}")
    print(f"Date Range: {date_range[0]} to {date_range[1]}")

    # By option type
    print("\n" + "-" * 70)
    print("BY OPTION TYPE")
    print("-" * 70)
    cursor.execute("""
        SELECT option_type, COUNT(*), AVG(ABS(delta))
        FROM historical_options
        GROUP BY option_type
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]:,} records, avg |delta| = {row[2]:.3f}")

    # Delta distribution
    print("\n" + "-" * 70)
    print("DELTA DISTRIBUTION")
    print("-" * 70)
    cursor.execute("""
        SELECT
            CASE
                WHEN ABS(delta) < 0.10 THEN '0.03-0.10'
                WHEN ABS(delta) < 0.20 THEN '0.10-0.20'
                WHEN ABS(delta) < 0.30 THEN '0.20-0.30'
                ELSE '0.30-0.40'
            END as delta_bucket,
            COUNT(*)
        FROM historical_options
        GROUP BY delta_bucket
        ORDER BY delta_bucket
    """)
    for row in cursor.fetchall():
        print(f"  Delta {row[0]}: {row[1]:,}")

    # Top symbols
    print("\n" + "-" * 70)
    print("TOP 10 SYMBOLS BY DATA VOLUME")
    print("-" * 70)
    cursor.execute("""
        SELECT underlying, COUNT(*), MIN(quote_date), MAX(quote_date)
        FROM historical_options
        GROUP BY underlying
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """)
    print(f"{'Symbol':<8} {'Records':>10} {'From':>12} {'To':>12}")
    print("-" * 50)
    for row in cursor.fetchall():
        print(f"{row[0]:<8} {row[1]:>10,} {row[2]:>12} {row[3]:>12}")

    conn.close()
    print()


class ProgressTracker:
    """Progress-Tracker für CLI"""

    def __init__(self):
        self.start_time = datetime.now()
        self.last_symbol = ""

    def update(self, symbol: str, current: int, total: int, status: str):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        pct = (current / total) * 100 if total > 0 else 0

        # Progress bar
        bar_width = 25
        filled = int(bar_width * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)

        # ETA
        if current > 0 and elapsed > 0:
            rate = current / elapsed
            remaining = total - current
            eta = remaining / rate if rate > 0 else 0
            eta_str = f"{int(eta // 60):02d}:{int(eta % 60):02d}"
        else:
            eta_str = "--:--"

        print(
            f"\r[{bar}] {pct:5.1f}% | {symbol:<6} | {status:<20} | ETA {eta_str}",
            end="",
            flush=True,
        )


async def main():
    parser = argparse.ArgumentParser(
        description="Collect historical options data with calculated Greeks"
    )

    parser.add_argument("--test", action="store_true", help="Test mode with 3 symbols, 5 days")
    parser.add_argument("--symbols", type=str, help="Comma-separated list of symbols")
    parser.add_argument("--all", action="store_true", help="Process all watchlist symbols")
    parser.add_argument("--days", type=int, default=30, help="Days of history (default: 30)")
    parser.add_argument("--status", action="store_true", help="Show collection status")
    parser.add_argument(
        "--delta-min", type=float, default=0.03, help="Minimum |delta| filter (default: 0.03)"
    )
    parser.add_argument(
        "--delta-max", type=float, default=0.40, help="Maximum |delta| filter (default: 0.40)"
    )
    parser.add_argument("--dte-min", type=int, default=7, help="Minimum DTE (default: 7)")
    parser.add_argument("--dte-max", type=int, default=60, help="Maximum DTE (default: 60)")
    parser.add_argument(
        "--rpm",
        type=int,
        default=6000,
        help="Requests per minute (Quant plan: 10000, default: 6000)",
    )
    parser.add_argument(
        "--workers", type=int, default=20, help="Concurrent API workers (default: 20)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.status:
        show_status()
        return

    # Symbole bestimmen
    if args.test:
        symbols = ["AAPL", "SPY", "MSFT"]
        days = 5
        logger.info("Test mode: 3 symbols, 5 days")
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        days = args.days
    elif args.all:
        loader = get_watchlist_loader()
        symbols = sorted(set(loader.get_all_symbols()))
        days = args.days
        logger.info(f"All watchlist symbols: {len(symbols)}")
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python scripts/collect_historical_options_marketdata.py --test")
        print(
            "  python scripts/collect_historical_options_marketdata.py --symbols AAPL,MSFT --days 30"
        )
        print("  python scripts/collect_historical_options_marketdata.py --all --days 14")
        return

    api_key = get_api_key()
    db_path = get_db_path()

    print(f"\n{'='*70}")
    print("HISTORICAL OPTIONS DATA COLLECTION")
    print(f"{'='*70}")
    print(f"  Symbols:    {len(symbols)}")
    print(f"  Days back:  {days}")
    print(f"  Delta:      {args.delta_min} - {args.delta_max}")
    print(f"  DTE:        {args.dte_min} - {args.dte_max}")
    print(f"  Rate Limit: {args.rpm:,} requests/minute (Quant: 10,000)")
    print(f"  Workers:    {args.workers} concurrent")
    print(f"  Database:   {db_path}")
    print(f"{'='*70}\n")

    collector = HistoricalOptionsCollector(
        api_key=api_key,
        db_path=db_path,
        delta_min=args.delta_min,
        delta_max=args.delta_max,
        dte_min=args.dte_min,
        dte_max=args.dte_max,
        requests_per_minute=args.rpm,
        concurrent_workers=args.workers,
    )

    progress = ProgressTracker()

    try:
        stats = await collector.collect(
            symbols=symbols,
            days_back=days,
            progress_callback=progress.update,
        )

        print("\n\n" + "=" * 70)
        print("COLLECTION COMPLETE")
        print("=" * 70)
        print(f"  Symbols processed:   {stats.symbols_processed}/{stats.symbols_requested}")
        print(f"  Symbols failed:      {stats.symbols_failed}")
        print(f"  Trading days:        {stats.dates_processed}")
        print(f"  Options collected:   {stats.options_collected:,}")
        print(f"  Options with Greeks: {stats.options_with_greeks:,}")
        print(f"  API calls:           {stats.api_calls}")

        if stats.errors:
            print(f"\n  Errors ({len(stats.errors)}):")
            for err in stats.errors[:10]:
                print(f"    - {err}")
            if len(stats.errors) > 10:
                print(f"    ... and {len(stats.errors) - 10} more")

        print("=" * 70)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")


if __name__ == "__main__":
    asyncio.run(main())
