#!/usr/bin/env python3
"""
OptionPlay - Historical Options Data Collector
==============================================

Sammelt historische Optionsdaten von Tradier und speichert sie in der Datenbank.

Usage:
    python scripts/collect_options_history.py --symbols AAPL,MSFT,GOOGL --days 90
    python scripts/collect_options_history.py --watchlist config/watchlists.yaml --days 60
    python scripts/collect_options_history.py --all --days 30

Die gesammelten Daten können später für:
- Vergleich Black-Scholes vs. Marktpreise
- Backtesting mit echten Options-Preisen
- IV-Analyse
verwendet werden.
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Set, Tuple

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_providers.tradier import (
    TradierProvider,
    build_occ_symbol,
    parse_occ_symbol,
)
from src.backtesting.tracking import TradeTracker, OptionBar
from src.config.watchlist_loader import get_watchlist_loader

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def get_available_expirations(
    provider: TradierProvider,
    symbol: str,
    min_dte: int = 0,
    max_dte: int = 120,
) -> List[date]:
    """
    Holt verfügbare Verfallstermine für ein Symbol.
    """
    expirations = await provider.get_expirations(symbol)
    today = date.today()

    # Filter nach DTE
    filtered = [exp for exp in expirations if min_dte <= (exp - today).days <= max_dte]

    return sorted(filtered)


async def get_strikes_for_expiry(
    provider: TradierProvider,
    symbol: str,
    expiry: date,
    current_price: float,
    otm_range: float = 0.20,  # 20% OTM auf jeder Seite (increased from 15%)
) -> List[float]:
    """
    Holt relevante Strikes für einen Verfall.
    Fokus auf ATM und leicht OTM Puts für Bull-Put-Spreads.
    """
    all_strikes = await provider.get_strikes(symbol, expiry)

    if not all_strikes:
        return []

    # Filter: Nur Strikes zwischen price * (1 - otm_range) und price * 1.05
    min_strike = current_price * (1 - otm_range)
    max_strike = current_price * 1.05  # Leicht ITM auch

    filtered = [s for s in all_strikes if min_strike <= s <= max_strike]

    return sorted(filtered)


async def collect_option_history_for_symbol(
    provider: TradierProvider,
    tracker: TradeTracker,
    symbol: str,
    days: int = 90,
    max_expirations: int = 4,
    otm_range: float = 0.15,
) -> Tuple[int, int]:
    """
    Sammelt historische Options-Daten für ein Symbol.

    Returns:
        Tuple (options_collected, bars_collected)
    """
    logger.info(f"Collecting options for {symbol}...")

    # Aktuellen Preis holen
    quote = await provider.get_quote(symbol)
    if not quote or not quote.last:
        logger.warning(f"No quote for {symbol}")
        return 0, 0

    current_price = quote.last
    logger.info(f"  {symbol} @ ${current_price:.2f}")

    # Verfallstermine holen
    expirations = await get_available_expirations(provider, symbol, min_dte=20, max_dte=90)

    if not expirations:
        logger.warning(f"No expirations for {symbol}")
        return 0, 0

    # Limitiere Anzahl der Expirations
    expirations = expirations[:max_expirations]
    logger.info(f"  Found {len(expirations)} expirations")

    options_collected = 0
    bars_collected = 0

    for expiry in expirations:
        # Strikes für diesen Verfall
        strikes = await get_strikes_for_expiry(provider, symbol, expiry, current_price, otm_range)

        if not strikes:
            continue

        logger.info(f"  Expiry {expiry}: {len(strikes)} strikes")

        for strike in strikes:
            # OCC Symbol erstellen
            occ_symbol = build_occ_symbol(symbol, expiry, "P", strike)

            try:
                # Historische Daten holen
                bars = await provider.get_option_history(occ_symbol, days=days)

                if bars:
                    # Konvertiere zu OptionBar
                    option_bars = []
                    for bar in bars:
                        option_bars.append(
                            OptionBar(
                                occ_symbol=occ_symbol,
                                underlying=symbol,
                                strike=strike,
                                expiry=expiry,
                                option_type="P",
                                trade_date=bar.date,
                                open=bar.open,
                                high=bar.high,
                                low=bar.low,
                                close=bar.close,
                                volume=bar.volume,
                            )
                        )

                    # In DB speichern
                    count = tracker.store_option_bars(option_bars)
                    bars_collected += count
                    options_collected += 1

                    logger.debug(f"    {occ_symbol}: {count} bars")

                # Rate limiting
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.warning(f"    Error fetching {occ_symbol}: {e}")
                continue

    logger.info(f"  {symbol}: {options_collected} options, {bars_collected} bars")
    return options_collected, bars_collected


async def collect_all_options(
    api_key: str,
    symbols: List[str],
    days: int = 90,
    max_expirations: int = 4,
) -> dict:
    """
    Sammelt Options-Daten für alle Symbole.
    """
    tracker = TradeTracker()

    total_options = 0
    total_bars = 0
    failed_symbols = []

    async with TradierProvider(api_key) as provider:
        logger.info(f"Connected to Tradier")
        logger.info(f"Collecting options for {len(symbols)} symbols, {days} days history")

        for i, symbol in enumerate(symbols):
            logger.info(f"[{i+1}/{len(symbols)}] Processing {symbol}")

            try:
                options, bars = await collect_option_history_for_symbol(
                    provider=provider,
                    tracker=tracker,
                    symbol=symbol,
                    days=days,
                    max_expirations=max_expirations,
                )
                total_options += options
                total_bars += bars

            except Exception as e:
                logger.error(f"Failed to process {symbol}: {e}")
                failed_symbols.append(symbol)

            # Rate limiting zwischen Symbolen
            await asyncio.sleep(0.5)

    return {
        "symbols_processed": len(symbols),
        "symbols_failed": failed_symbols,
        "total_options": total_options,
        "total_bars": total_bars,
    }


def load_symbols_from_watchlist(watchlist_path: str = None) -> List[str]:
    """Lädt Symbole aus Watchlist YAML."""
    try:
        watchlist = get_watchlist_loader()
        return watchlist.get_all_symbols()
    except Exception as e:
        logger.error(f"Failed to load watchlist: {e}")
        return []


def get_default_symbols() -> List[str]:
    """Standard-Symbole für Options-Datensammlung."""
    return [
        # Mega Cap Tech
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "META",
        "NVDA",
        "TSLA",
        # Large Cap
        "JPM",
        "V",
        "MA",
        "HD",
        "UNH",
        "JNJ",
        "PG",
        # ETFs
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        # Volatile/Popular
        "AMD",
        "CRM",
        "NFLX",
        "ADBE",
        "PYPL",
    ]


def get_extended_symbols() -> List[str]:
    """Erweiterte Symbol-Liste für maximale Datensammlung."""
    return [
        # ===== MEGA CAP TECH (20) =====
        "AAPL",
        "MSFT",
        "GOOGL",
        "GOOG",
        "AMZN",
        "META",
        "NVDA",
        "TSLA",
        "AVGO",
        "ORCL",
        "CRM",
        "ADBE",
        "AMD",
        "CSCO",
        "ACN",
        "INTC",
        "IBM",
        "INTU",
        "TXN",
        "QCOM",
        # ===== FINANCIALS (20) =====
        "JPM",
        "V",
        "MA",
        "BAC",
        "WFC",
        "GS",
        "MS",
        "C",
        "AXP",
        "BLK",
        "SCHW",
        "PGR",
        "CB",
        "CME",
        "ICE",
        "USB",
        "PNC",
        "MET",
        "AIG",
        "COF",
        # ===== HEALTHCARE (15) =====
        "UNH",
        "JNJ",
        "LLY",
        "ABBV",
        "MRK",
        "PFE",
        "TMO",
        "ABT",
        "DHR",
        "AMGN",
        "BMY",
        "ISRG",
        "GILD",
        "VRTX",
        "MDT",
        # ===== CONSUMER (15) =====
        "HD",
        "MCD",
        "NKE",
        "LOW",
        "SBUX",
        "TJX",
        "BKNG",
        "CMG",
        "MAR",
        "GM",
        "F",
        "TGT",
        "COST",
        "WMT",
        "DG",
        # ===== INDUSTRIALS (15) =====
        "GE",
        "CAT",
        "RTX",
        "HON",
        "UNP",
        "UPS",
        "BA",
        "DE",
        "LMT",
        "ADP",
        "ETN",
        "GD",
        "NOC",
        "WM",
        "CSX",
        # ===== COMMUNICATION (10) =====
        "NFLX",
        "DIS",
        "CMCSA",
        "VZ",
        "T",
        "TMUS",
        "EA",
        "TTWO",
        "SNAP",
        "PINS",
        # ===== ENERGY (10) =====
        "XOM",
        "CVX",
        "COP",
        "SLB",
        "EOG",
        "MPC",
        "PSX",
        "VLO",
        "OXY",
        "HAL",
        # ===== MATERIALS & UTILITIES (10) =====
        "LIN",
        "APD",
        "SHW",
        "FCX",
        "NUE",
        "NEE",
        "SO",
        "DUK",
        "AEP",
        "D",
        # ===== REAL ESTATE (5) =====
        "PLD",
        "AMT",
        "EQIX",
        "CCI",
        "PSA",
        # ===== ETFS (15) =====
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "XLK",
        "XLF",
        "XLE",
        "XLV",
        "XLI",
        "XLY",
        "XLP",
        "XLB",
        "XLU",
        "XLRE",
        "SMH",
        # ===== HIGH VOLATILITY / POPULAR (25) =====
        "PYPL",
        "SQ",
        "COIN",
        "SHOP",
        "ROKU",
        "ZM",
        "DKNG",
        "SOFI",
        "RIVN",
        "LCID",
        "NIO",
        "BABA",
        "MARA",
        "MSTR",
        "ARM",
        "CRWD",
        "SNOW",
        "NET",
        "MDB",
        "PANW",
        "ZS",
        "PLTR",
        "UBER",
        "ABNB",
        "DASH",
    ]


async def main():
    parser = argparse.ArgumentParser(description="Collect historical options data from Tradier")
    parser.add_argument(
        "--symbols", type=str, help="Comma-separated list of symbols (e.g., AAPL,MSFT,GOOGL)"
    )
    parser.add_argument("--watchlist", type=str, help="Path to watchlist YAML file")
    parser.add_argument("--all", action="store_true", help="Use default symbol list")
    parser.add_argument(
        "--days", type=int, default=90, help="Days of history to collect (default: 90)"
    )
    parser.add_argument(
        "--max-expirations", type=int, default=4, help="Max expirations per symbol (default: 4)"
    )
    parser.add_argument(
        "--api-key", type=str, help="Tradier API key (or set TRADIER_API_KEY env var)"
    )
    parser.add_argument(
        "--status", action="store_true", help="Show current options data status and exit"
    )

    args = parser.parse_args()

    # Status anzeigen
    if args.status:
        tracker = TradeTracker()
        underlyings = tracker.list_options_underlyings()
        total_bars = tracker.count_option_bars()

        print("\n" + "=" * 60)
        print("OPTIONS DATA STATUS")
        print("=" * 60)
        print(f"\nTotal option bars: {total_bars:,}")
        print(f"Underlyings with data: {len(underlyings)}")

        if underlyings:
            print("\nBy underlying:")
            print("-" * 50)
            for u in underlyings:
                print(
                    f"  {u['underlying']:6s}: {u['bar_count']:6,} bars, "
                    f"{u['option_count']:3} options, "
                    f"{u['first_date']} to {u['last_date']}"
                )

        return

    # API Key
    api_key = args.api_key or os.environ.get("TRADIER_API_KEY")
    if not api_key:
        # Versuche aus .env zu laden
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    if line.startswith("TRADIER_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break

    if not api_key:
        logger.error("No API key provided. Use --api-key or set TRADIER_API_KEY")
        sys.exit(1)

    # Symbole bestimmen
    symbols = []

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.watchlist:
        symbols = load_symbols_from_watchlist(args.watchlist)
    elif args.all:
        symbols = get_extended_symbols()  # Use extended list for --all
    else:
        # Default: einige wichtige Symbole
        symbols = get_default_symbols()[:10]
        logger.info("No symbols specified, using top 10 default symbols")

    if not symbols:
        logger.error("No symbols to process")
        sys.exit(1)

    logger.info(
        f"Processing {len(symbols)} symbols: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}"
    )

    # Daten sammeln
    result = await collect_all_options(
        api_key=api_key,
        symbols=symbols,
        days=args.days,
        max_expirations=args.max_expirations,
    )

    # Ergebnis
    print("\n" + "=" * 60)
    print("COLLECTION COMPLETE")
    print("=" * 60)
    print(f"Symbols processed: {result['symbols_processed']}")
    print(f"Symbols failed: {len(result['symbols_failed'])}")
    print(f"Total options: {result['total_options']}")
    print(f"Total bars collected: {result['total_bars']:,}")

    if result["symbols_failed"]:
        print(f"\nFailed symbols: {', '.join(result['symbols_failed'])}")


if __name__ == "__main__":
    asyncio.run(main())
