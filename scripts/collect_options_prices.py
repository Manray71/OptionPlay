#!/usr/bin/env python3
"""
OptionPlay - Historical Options Price Collector (Marketdata.app)
================================================================

Sammelt NUR historische End-of-Day Options-Preise von Marketdata.app.
Greeks werden in einem separaten Schritt berechnet.

Strategie:
1. Dieses Script: Lädt Bid/Ask/Mid/Last, Volume, OI in die Datenbank
2. Separates Script: Berechnet Greeks nachträglich

Usage:
    # Test mit wenigen Symbolen
    python scripts/collect_options_prices.py --test

    # Spezifische Symbole
    python scripts/collect_options_prices.py --symbols AAPL,MSFT,SPY

    # Alle Watchlist-Symbole
    python scripts/collect_options_prices.py --all --days 30

    # Mit mehr Workers für schnelleren Abruf
    python scripts/collect_options_prices.py --all --days 30 --workers 50

    # Status prüfen
    python scripts/collect_options_prices.py --status
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import sqlite3

import aiohttp

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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
class OptionPrice:
    """Historische Options-Preisdaten (ohne Greeks)"""

    occ_symbol: str
    underlying: str
    expiration: date
    strike: float
    option_type: str  # 'P' or 'C'
    quote_date: date
    bid: float
    ask: float
    mid: float
    last: Optional[float]
    volume: int
    open_interest: int
    underlying_price: float
    dte: int
    moneyness: float


@dataclass
class CollectionStats:
    """Sammlungsstatistik"""

    symbols_requested: int = 0
    symbols_processed: int = 0
    symbols_failed: int = 0
    options_collected: int = 0
    api_calls: int = 0
    errors: List[str] = field(default_factory=list)


# =============================================================================
# DATABASE
# =============================================================================


def ensure_schema(db_path: str):
    """Stellt sicher, dass das Schema existiert"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Tabelle für Options-Preise (ohne Greeks)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS options_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occ_symbol TEXT NOT NULL,
            underlying TEXT NOT NULL,
            expiration TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            quote_date TEXT NOT NULL,
            bid REAL,
            ask REAL,
            mid REAL,
            last REAL,
            volume INTEGER,
            open_interest INTEGER,
            underlying_price REAL,
            dte INTEGER,
            moneyness REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(occ_symbol, quote_date)
        )
    """)

    # Indices für schnelle Abfragen
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_options_prices_underlying
        ON options_prices(underlying)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_options_prices_quote_date
        ON options_prices(quote_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_options_prices_dte
        ON options_prices(dte)
    """)

    conn.commit()
    conn.close()
    logger.info("Database schema verified/created")


def store_options(db_path: str, options: List[OptionPrice]) -> int:
    """Speichert Options-Preise in der Datenbank"""
    if not options:
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    inserted = 0
    for opt in options:
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO options_prices (
                    occ_symbol, underlying, expiration, strike, option_type,
                    quote_date, bid, ask, mid, last, volume, open_interest,
                    underlying_price, dte, moneyness
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            inserted += 1
        except Exception as e:
            logger.debug(f"Insert error for {opt.occ_symbol}: {e}")

    conn.commit()
    conn.close()
    return inserted


# =============================================================================
# MARKETDATA.APP CLIENT
# =============================================================================


class MarketdataClient:
    """Async Client für Marketdata.app API"""

    BASE_URL = "https://api.marketdata.app"

    def __init__(self, api_key: str, requests_per_minute: int = 6000):
        self.api_key = api_key
        self.requests_per_minute = requests_per_minute
        self._request_times: List[float] = []
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Accept": "application/json",
        }
        self.session = aiohttp.ClientSession(headers=headers)
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def _rate_limit(self):
        """Einfaches Rate-Limiting"""
        import time

        now = time.time()
        minute_ago = now - 60

        # Alte Requests entfernen
        self._request_times = [t for t in self._request_times if t > minute_ago]

        # Warten wenn nötig
        if len(self._request_times) >= self.requests_per_minute:
            wait_time = self._request_times[0] - minute_ago + 0.1
            if wait_time > 0:
                await asyncio.sleep(wait_time)

        self._request_times.append(now)

    async def get_options_chain(
        self,
        symbol: str,
        quote_date: date,
        dte_min: int = 7,
        dte_max: int = 60,
    ) -> Optional[List[Dict]]:
        """
        Holt historische Options-Chain für ein Symbol an einem Datum.
        """
        await self._rate_limit()

        # Expiration date range
        exp_from = quote_date + timedelta(days=dte_min)
        exp_to = quote_date + timedelta(days=dte_max)

        params = {
            "date": quote_date.isoformat(),
            "from": exp_from.isoformat(),
            "to": exp_to.isoformat(),
        }

        url = f"{self.BASE_URL}/v1/options/chain/{symbol}/"

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 404:
                        return None
                    if resp.status == 429:
                        wait_time = 10 * (attempt + 1)  # 10s, 20s, 30s
                        logger.warning(
                            f"Rate limit for {symbol}, waiting {wait_time}s (attempt {attempt+1}/{max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue  # Retry
                    if resp.status not in [200, 203]:
                        return None

                    data = await resp.json()
                    if data.get("s") != "ok":
                        return None

                    return self._parse_chain(data, quote_date)

            except Exception as e:
                logger.debug(f"Error fetching {symbol}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                    continue
                return None

        return None  # All retries failed

    def _parse_chain(self, data: Dict, quote_date: date) -> List[Dict]:
        """Parsed die API-Response in eine Liste von Optionen"""
        options = []

        occ_symbols = data.get("optionSymbol", [])
        underlyings = data.get("underlying", [])
        expirations = data.get("expiration", [])
        strikes = data.get("strike", [])
        sides = data.get("side", [])
        bids = data.get("bid", [])
        asks = data.get("ask", [])
        mids = data.get("mid", [])
        lasts = data.get("last", [])
        volumes = data.get("volume", [])
        ois = data.get("openInterest", [])
        underlying_prices = data.get("underlyingPrice", [])

        for i in range(len(occ_symbols)):
            try:
                exp_ts = expirations[i]
                exp_date = date.fromtimestamp(exp_ts)

                options.append(
                    {
                        "occ_symbol": occ_symbols[i],
                        "underlying": underlyings[i] if i < len(underlyings) else None,
                        "expiration": exp_date,
                        "strike": strikes[i],
                        "side": sides[i],  # 'call' or 'put'
                        "bid": bids[i] if i < len(bids) else 0,
                        "ask": asks[i] if i < len(asks) else 0,
                        "mid": mids[i] if i < len(mids) else 0,
                        "last": lasts[i] if i < len(lasts) else None,
                        "volume": volumes[i] if i < len(volumes) else 0,
                        "open_interest": ois[i] if i < len(ois) else 0,
                        "underlying_price": (
                            underlying_prices[i] if i < len(underlying_prices) else None
                        ),
                        "quote_date": quote_date,
                    }
                )
            except Exception as e:
                continue

        return options

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
                    return data["c"][0]

                return None
        except:
            return None


# =============================================================================
# COLLECTOR
# =============================================================================


class OptionsCollector:
    """Sammelt Options-Preise"""

    def __init__(
        self,
        api_key: str,
        db_path: str,
        requests_per_minute: int = 6000,
        concurrent_workers: int = 30,
        strike_below_pct: float = 0.20,  # 20% unter Spot
        strike_above_pct: float = 0.20,  # 20% über Spot
    ):
        self.api_key = api_key
        self.db_path = db_path
        self.requests_per_minute = requests_per_minute
        self.concurrent_workers = concurrent_workers
        self.strike_below_pct = strike_below_pct
        self.strike_above_pct = strike_above_pct
        self.stats = CollectionStats()

    def _get_monthly_expirations(self, quote_date: date, num_months: int = 4) -> List[date]:
        """
        Berechnet die nächsten N monatlichen Verfallsdaten (3. Freitag im Monat).
        """
        from calendar import monthcalendar, FRIDAY

        expirations = []
        current = quote_date

        while len(expirations) < num_months:
            year = current.year
            month = current.month

            # Finde 3. Freitag des Monats
            cal = monthcalendar(year, month)
            fridays = [week[FRIDAY] for week in cal if week[FRIDAY] != 0]
            third_friday = date(year, month, fridays[2])

            # Nur zukünftige Expirations
            if third_friday > quote_date:
                expirations.append(third_friday)

            # Nächster Monat
            if month == 12:
                current = date(year + 1, 1, 1)
            else:
                current = date(year, month + 1, 1)

        return expirations

    def _filter_by_strike_range(self, options: List[Dict], quote_date: date) -> List[Dict]:
        """
        Filtert Optionen nach Strike-Bereich und monatlichen Expirations.

        Filter:
        - Puts: Strike 0% bis 20% unter Spot (Moneyness 0.80-1.00)
        - Calls: Strike 0% bis 20% über Spot (Moneyness 1.00-1.20)
        - Nur monatliche Expirations (3. Freitag)
        """
        # Berechne erlaubte monatliche Expirations
        monthly_exps = self._get_monthly_expirations(quote_date, num_months=4)
        monthly_exp_set = set(monthly_exps)

        filtered = []

        for opt in options:
            underlying_price = opt.get("underlying_price")
            strike = opt.get("strike")
            expiration = opt.get("expiration")

            if not underlying_price or underlying_price <= 0:
                continue
            if not strike or strike <= 0:
                continue
            if not expiration:
                continue

            # Nur monatliche Expirations
            if expiration not in monthly_exp_set:
                continue

            moneyness = strike / underlying_price
            side = opt.get("side", "").lower()

            # Puts: Strike bis 20% unter Spot (Moneyness 0.80-1.00)
            if side == "put":
                min_moneyness = 1.0 - self.strike_below_pct  # 0.87
                if min_moneyness <= moneyness <= 1.00:
                    filtered.append(opt)
            # Calls: Strike bis 16% über Spot (Moneyness 1.00-1.16)
            elif side == "call":
                max_moneyness = 1.0 + self.strike_above_pct  # 1.16
                if 1.00 <= moneyness <= max_moneyness:
                    filtered.append(opt)

        return filtered

    def _to_option_price(self, opt: Dict) -> Optional[OptionPrice]:
        """Konvertiert Dict zu OptionPrice"""
        try:
            underlying_price = opt.get("underlying_price")
            strike = opt.get("strike")

            if not underlying_price or underlying_price <= 0:
                return None

            expiration = opt["expiration"]
            quote_date = opt["quote_date"]
            dte = (expiration - quote_date).days

            return OptionPrice(
                occ_symbol=opt["occ_symbol"],
                underlying=opt.get("underlying", ""),
                expiration=expiration,
                strike=strike,
                option_type="P" if opt.get("side", "").lower() == "put" else "C",
                quote_date=quote_date,
                bid=opt.get("bid", 0) or 0,
                ask=opt.get("ask", 0) or 0,
                mid=opt.get("mid", 0) or 0,
                last=opt.get("last"),
                volume=opt.get("volume", 0) or 0,
                open_interest=opt.get("open_interest", 0) or 0,
                underlying_price=underlying_price,
                dte=dte,
                moneyness=strike / underlying_price,
            )
        except Exception as e:
            return None

    async def _process_symbol_date(
        self,
        client: MarketdataClient,
        symbol: str,
        trade_date: date,
        semaphore: asyncio.Semaphore,
    ) -> List[OptionPrice]:
        """Verarbeitet ein Symbol für ein Datum"""
        async with semaphore:
            try:
                # Hole Options mit erweitertem DTE-Bereich für 4 Monats-Expirations
                raw_options = await client.get_options_chain(
                    symbol, trade_date, dte_min=1, dte_max=130
                )

                if not raw_options:
                    return []

                # Nach Strike-Bereich und monatlichen Expirations filtern
                filtered = self._filter_by_strike_range(raw_options, trade_date)

                # Zu OptionPrice konvertieren
                results = []
                for opt in filtered:
                    price = self._to_option_price(opt)
                    if price:
                        results.append(price)

                return results

            except Exception as e:
                return []

    async def collect(
        self,
        symbols: List[str],
        days_back: int = 30,
    ) -> CollectionStats:
        """Sammelt Options-Preise für alle Symbole"""

        ensure_schema(self.db_path)

        # Handelstage generieren
        trade_dates = []
        current_date = date.today() - timedelta(days=1)

        while len(trade_dates) < days_back:
            if current_date.weekday() < 5:
                trade_dates.append(current_date)
            current_date -= timedelta(days=1)

        trade_dates = list(reversed(trade_dates))

        logger.info(f"Collecting {len(symbols)} symbols x {len(trade_dates)} days")
        logger.info(f"Using {self.concurrent_workers} concurrent workers")

        self.stats.symbols_requested = len(symbols)
        total_ops = len(symbols) * len(trade_dates)
        completed_ops = 0

        semaphore = asyncio.Semaphore(self.concurrent_workers)

        async with MarketdataClient(self.api_key, self.requests_per_minute) as client:
            batch_size = 30  # Symbole pro Batch

            for batch_start in range(0, len(symbols), batch_size):
                batch_symbols = symbols[batch_start : batch_start + batch_size]
                batch_options = []

                # Tasks erstellen
                tasks = []
                task_info = []

                for symbol in batch_symbols:
                    for trade_date in trade_dates:
                        task = self._process_symbol_date(client, symbol, trade_date, semaphore)
                        tasks.append(task)
                        task_info.append((symbol, trade_date))

                # Parallel ausführen
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Ergebnisse verarbeiten
                for i, result in enumerate(results):
                    completed_ops += 1
                    self.stats.api_calls += 1

                    if isinstance(result, Exception):
                        self.stats.errors.append(str(result))
                    elif result:
                        batch_options.extend(result)

                # In DB speichern
                if batch_options:
                    stored = store_options(self.db_path, batch_options)
                    self.stats.options_collected += stored

                # Fortschritt
                symbols_done = set(opt.underlying for opt in batch_options)
                self.stats.symbols_processed += len(symbols_done)

                progress = (batch_start + len(batch_symbols)) / len(symbols) * 100
                logger.info(
                    f"[{progress:5.1f}%] Batch {batch_start//batch_size + 1}: "
                    f"{len(batch_options)} options from {len(symbols_done)} symbols | "
                    f"Total: {self.stats.options_collected:,}"
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
        env_file = project_root / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith("MARKETDATA_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break

    if not api_key:
        print("ERROR: No API key found!")
        sys.exit(1)

    return api_key


def get_db_path() -> str:
    return str(Path.home() / ".optionplay" / "trades.db")


def show_status():
    """Zeigt Status der gesammelten Options-Preise"""
    db_path = get_db_path()

    if not Path(db_path).exists():
        print("Database not found")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("OPTIONS PRICES STATUS")
    print("=" * 70)

    # Check if table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='options_prices'
    """)
    if not cursor.fetchone():
        print("\nNo options_prices table found.")
        print("Run collection first: python scripts/collect_options_prices.py --all")
        conn.close()
        return

    # Total records
    cursor.execute("SELECT COUNT(*) FROM options_prices")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT underlying) FROM options_prices")
    symbols = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT quote_date) FROM options_prices")
    dates = cursor.fetchone()[0]

    cursor.execute("SELECT MIN(quote_date), MAX(quote_date) FROM options_prices")
    date_range = cursor.fetchone()

    print(f"\nTotal Records: {total:,}")
    print(f"Symbols: {symbols}")
    print(f"Trading Days: {dates}")
    print(f"Date Range: {date_range[0]} to {date_range[1]}")

    # By option type
    print("\n" + "-" * 70)
    print("BY OPTION TYPE")
    print("-" * 70)

    cursor.execute("""
        SELECT option_type, COUNT(*) as cnt
        FROM options_prices
        GROUP BY option_type
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]:,} records")

    # Top symbols
    print("\n" + "-" * 70)
    print("TOP 10 SYMBOLS BY VOLUME")
    print("-" * 70)

    cursor.execute("""
        SELECT underlying, COUNT(*) as cnt, MIN(quote_date), MAX(quote_date)
        FROM options_prices
        GROUP BY underlying
        ORDER BY cnt DESC
        LIMIT 10
    """)
    print(f"{'Symbol':<10} {'Records':>10} {'From':>15} {'To':>15}")
    print("-" * 50)
    for row in cursor.fetchall():
        print(f"{row[0]:<10} {row[1]:>10,} {row[2]:>15} {row[3]:>15}")

    # Database size
    db_size = Path(db_path).stat().st_size / 1024 / 1024
    print(f"\nDatabase size: {db_size:.1f} MB")

    conn.close()


async def main():
    parser = argparse.ArgumentParser(description="Collect historical options prices")
    parser.add_argument("--test", action="store_true", help="Test with 3 symbols")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    parser.add_argument("--all", action="store_true", help="All watchlist symbols")
    parser.add_argument("--days", type=int, default=30, help="Days back (default: 30)")
    parser.add_argument("--workers", type=int, default=50, help="Concurrent workers (default: 50)")
    parser.add_argument("--rpm", type=int, default=8000, help="Requests per minute (default: 8000)")
    parser.add_argument("--status", action="store_true", help="Show collection status")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # Symbole bestimmen
    if args.test:
        symbols = ["AAPL", "MSFT", "SPY"]
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.all:
        loader = get_watchlist_loader()
        symbols = loader.get_all_symbols()
        logger.info(f"Watchlist loaded: {len(symbols)} symbols")
    else:
        parser.print_help()
        return

    # Collector starten
    api_key = get_api_key()
    db_path = get_db_path()

    collector = OptionsCollector(
        api_key=api_key,
        db_path=db_path,
        requests_per_minute=args.rpm,
        concurrent_workers=args.workers,
    )

    logger.info(f"Starting collection for {len(symbols)} symbols, {args.days} days")

    stats = await collector.collect(symbols, args.days)

    print("\n" + "=" * 70)
    print("COLLECTION COMPLETE")
    print("=" * 70)
    print(f"Symbols requested: {stats.symbols_requested}")
    print(f"Symbols with data: {stats.symbols_processed}")
    print(f"Options collected: {stats.options_collected:,}")
    print(f"API calls: {stats.api_calls:,}")
    if stats.errors:
        print(f"Errors: {len(stats.errors)}")

    show_status()


if __name__ == "__main__":
    asyncio.run(main())
