#!/usr/bin/env python3
"""
Backfill Component Scores for Historical Trades
================================================

Berechnet nachträglich die Komponenten-Scores für alle 17.438 Trades
in der outcomes.db, die noch keine Scores haben.

Optimiert für Performance:
- Batch-Loading der Preisdaten pro Symbol
- SPY-Daten einmal laden und cachen
- Multiprocessing für parallele Verarbeitung

Verwendung:
    python scripts/backfill_component_scores.py
    python scripts/backfill_component_scores.py --workers 8
    python scripts/backfill_component_scores.py --limit 100  # Test mit 100 Trades
"""

import argparse
import json
import logging
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import time

import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
TRADES_DB = Path.home() / ".optionplay" / "trades.db"
OUTCOMES_DB = Path.home() / ".optionplay" / "outcomes.db"

# Lookback für Indikatoren
LOOKBACK_DAYS = 100


@dataclass
class TradeToProcess:
    """Ein Trade der Scores braucht."""
    id: int
    symbol: str
    entry_date: str
    entry_price: float


def get_trades_without_scores(limit: int = None) -> List[TradeToProcess]:
    """Hole alle Trades ohne Komponenten-Scores."""
    conn = sqlite3.connect(str(OUTCOMES_DB))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
    SELECT id, symbol, entry_date, entry_price
    FROM trade_outcomes
    WHERE pullback_score IS NULL
      AND bounce_score IS NULL
    ORDER BY symbol, entry_date
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    trades = [
        TradeToProcess(
            id=row['id'],
            symbol=row['symbol'],
            entry_date=row['entry_date'],
            entry_price=row['entry_price']
        )
        for row in cursor.fetchall()
    ]
    conn.close()
    return trades


def get_price_data(symbol: str, start_date: str, end_date: str) -> Dict:
    """Hole Preisdaten aus der trades.db."""
    conn = sqlite3.connect(str(TRADES_DB))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Underlying-Preise aus options_prices
    cursor.execute("""
        SELECT DISTINCT quote_date, underlying_price
        FROM options_prices
        WHERE underlying = ?
          AND quote_date BETWEEN ? AND ?
        ORDER BY quote_date
    """, (symbol, start_date, end_date))

    prices = {}
    for row in cursor.fetchall():
        prices[row['quote_date']] = row['underlying_price']

    conn.close()
    return prices


def get_spy_prices(start_date: str, end_date: str) -> Dict[str, float]:
    """Hole SPY-Preise für Market Context."""
    return get_price_data("SPY", start_date, end_date)


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Berechne RSI."""
    if len(prices) < period + 1:
        return 50.0

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)


def calculate_macd(prices: List[float]) -> Tuple[float, float, float]:
    """Berechne MACD (line, signal, histogram)."""
    if len(prices) < 26:
        return 0.0, 0.0, 0.0

    prices_arr = np.array(prices)

    # EMA 12 und 26
    ema12 = np.mean(prices_arr[-12:])  # Vereinfacht
    ema26 = np.mean(prices_arr[-26:])

    macd_line = ema12 - ema26
    signal = macd_line * 0.9  # Vereinfacht
    histogram = macd_line - signal

    return float(macd_line), float(signal), float(histogram)


def calculate_stochastic(prices: List[float], highs: List[float], lows: List[float], period: int = 14) -> Tuple[float, float]:
    """Berechne Stochastic %K und %D."""
    if len(prices) < period:
        return 50.0, 50.0

    highest_high = max(highs[-period:])
    lowest_low = min(lows[-period:])
    current_close = prices[-1]

    if highest_high == lowest_low:
        k = 50.0
    else:
        k = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100

    d = k  # Vereinfacht (normalerweise 3-Perioden-SMA von K)
    return float(k), float(d)


def find_support_levels(prices: List[float], lows: List[float]) -> Tuple[float, int]:
    """Finde Support-Level und Stärke."""
    if len(lows) < 20:
        return 0.0, 0

    # Finde lokale Tiefs
    local_lows = []
    for i in range(5, len(lows) - 5):
        if lows[i] == min(lows[i-5:i+6]):
            local_lows.append(lows[i])

    if not local_lows:
        return 0.0, 0

    # Clustere ähnliche Levels
    current_price = prices[-1]
    supports_below = [l for l in local_lows if l < current_price]

    if not supports_below:
        return 0.0, 0

    nearest_support = max(supports_below)
    distance_pct = ((current_price - nearest_support) / current_price) * 100

    # Zähle wie oft dieses Level getestet wurde
    tolerance = current_price * 0.02
    touches = sum(1 for l in local_lows if abs(l - nearest_support) < tolerance)

    return distance_pct, touches


def calculate_scores_for_trade(
    trade: TradeToProcess,
    symbol_prices: Dict[str, float],
    spy_prices: Dict[str, float]
) -> Dict:
    """Berechne alle Komponenten-Scores für einen Trade."""
    entry_date = trade.entry_date

    # Sammle Preisdaten bis zum Entry-Datum
    sorted_dates = sorted([d for d in symbol_prices.keys() if d <= entry_date])

    if len(sorted_dates) < 50:
        return {'error': 'Insufficient price data'}

    # Letzte 100 Tage
    recent_dates = sorted_dates[-100:]
    prices = [symbol_prices[d] for d in recent_dates]

    # Approximiere Highs/Lows (wir haben nur closes)
    highs = [p * 1.01 for p in prices]  # ~1% über close
    lows = [p * 0.99 for p in prices]   # ~1% unter close

    current_price = prices[-1]

    # RSI Score (0-2)
    rsi = calculate_rsi(prices)
    if 30 <= rsi <= 40:
        rsi_score = 2.0  # Ideal für Pullback
    elif 40 < rsi <= 50:
        rsi_score = 1.5
    elif 25 <= rsi < 30:
        rsi_score = 1.0  # Überverkauft
    elif rsi < 25:
        rsi_score = 0.5  # Zu überverkauft
    else:
        rsi_score = 0.0

    # Support Score (0-2)
    distance_to_support, support_touches = find_support_levels(prices, lows)
    if 0 < distance_to_support <= 3:
        support_score = 2.0  # Nah am Support
    elif 3 < distance_to_support <= 5:
        support_score = 1.5
    elif 5 < distance_to_support <= 8:
        support_score = 1.0
    else:
        support_score = 0.5

    # Bonus für starken Support
    if support_touches >= 3:
        support_score = min(2.0, support_score + 0.5)

    # MA Score (0-2)
    sma20 = np.mean(prices[-20:])
    sma50 = np.mean(prices[-50:]) if len(prices) >= 50 else sma20

    if current_price > sma20 > sma50:
        ma_score = 2.0  # Starker Aufwärtstrend
    elif current_price > sma50:
        ma_score = 1.0
    else:
        ma_score = 0.0

    # MACD Score (0-1)
    macd_line, signal, histogram = calculate_macd(prices)
    if histogram > 0:
        macd_score = 1.0
    elif histogram > -0.5:
        macd_score = 0.5
    else:
        macd_score = 0.0

    # Stochastic Score (0-1)
    stoch_k, stoch_d = calculate_stochastic(prices, highs, lows)
    if 20 <= stoch_k <= 40:
        stoch_score = 1.0  # Ideal
    elif stoch_k < 20:
        stoch_score = 0.5  # Überverkauft
    else:
        stoch_score = 0.0

    # Volume Score (vereinfacht, 0-1)
    volume_score = 0.5  # Platzhalter ohne echte Volumendaten

    # Trend Strength (0-1)
    if len(prices) >= 50:
        trend_strength = (prices[-1] - prices[-50]) / prices[-50] * 100
        if trend_strength > 10:
            trend_score = 1.0
        elif trend_strength > 0:
            trend_score = 0.5
        else:
            trend_score = 0.0
    else:
        trend_score = 0.5

    # Market Context Score (0-2)
    spy_sorted = sorted([d for d in spy_prices.keys() if d <= entry_date])
    if len(spy_sorted) >= 50:
        spy_recent = [spy_prices[d] for d in spy_sorted[-50:]]
        spy_current = spy_recent[-1]
        spy_sma20 = np.mean(spy_recent[-20:])
        spy_sma50 = np.mean(spy_recent)

        if spy_current > spy_sma20 > spy_sma50:
            market_context_score = 2.0
        elif spy_current > spy_sma50:
            market_context_score = 1.0
        elif spy_current < spy_sma20 < spy_sma50:
            market_context_score = -1.0
        else:
            market_context_score = 0.0

        # SPY Trend
        if spy_current > spy_sma20 > spy_sma50:
            spy_trend = "strong_uptrend"
        elif spy_current > spy_sma50:
            spy_trend = "uptrend"
        elif spy_current < spy_sma20 < spy_sma50:
            spy_trend = "strong_downtrend"
        else:
            spy_trend = "sideways"
    else:
        market_context_score = 0.0
        spy_trend = "unknown"

    # Fibonacci Score (vereinfacht, 0-1)
    if len(prices) >= 50:
        high_50d = max(prices[-50:])
        low_50d = min(prices[-50:])
        fib_range = high_50d - low_50d
        fib_382 = high_50d - fib_range * 0.382
        fib_618 = high_50d - fib_range * 0.618

        if fib_618 <= current_price <= fib_382:
            fibonacci_score = 1.0
        elif low_50d <= current_price < fib_618:
            fibonacci_score = 0.5
        else:
            fibonacci_score = 0.0
    else:
        fibonacci_score = 0.5

    # Gesamtscores pro Strategie
    pullback_score = (
        rsi_score * 0.2 +
        support_score * 0.25 +
        ma_score * 0.15 +
        macd_score * 0.1 +
        stoch_score * 0.1 +
        trend_score * 0.1 +
        market_context_score * 0.1
    )

    bounce_score = (
        support_score * 0.3 +
        rsi_score * 0.2 +
        stoch_score * 0.15 +
        ma_score * 0.15 +
        market_context_score * 0.1 +
        fibonacci_score * 0.1
    )

    # Breakout braucht andere Logik (hier vereinfacht)
    ath_breakout_score = ma_score * 0.4 + trend_score * 0.3 + market_context_score * 0.3

    return {
        'rsi_score': round(rsi_score, 2),
        'support_score': round(support_score, 2),
        'fibonacci_score': round(fibonacci_score, 2),
        'ma_score': round(ma_score, 2),
        'volume_score': round(volume_score, 2),
        'macd_score': round(macd_score, 2),
        'stoch_score': round(stoch_score, 2),
        'keltner_score': 0.5,  # Platzhalter
        'trend_strength_score': round(trend_score, 2),
        'momentum_score': round((rsi_score + macd_score) / 2, 2),
        'rs_score': 0.5,  # Platzhalter (relative strength)
        'candlestick_score': 0.5,  # Platzhalter
        'vwap_score': round(ma_score, 2),  # Approximation
        'market_context_score': round(market_context_score, 2),
        'sector_score': 0.0,  # Würde Sektor-Mapping brauchen
        'gap_score': 0.0,  # Würde Open-Daten brauchen
        'pullback_score': round(pullback_score, 2),
        'bounce_score': round(bounce_score, 2),
        'ath_breakout_score': round(ath_breakout_score, 2),
        'earnings_dip_score': 0.0,  # Würde Earnings-Daten brauchen
        'rsi_value': round(rsi, 2),
        'distance_to_support_pct': round(distance_to_support, 2),
        'spy_trend': spy_trend,
    }


def process_symbol_batch(
    symbol: str,
    trades: List[TradeToProcess],
    spy_prices: Dict[str, float]
) -> List[Tuple[int, Dict]]:
    """Verarbeite alle Trades eines Symbols."""
    results = []

    # Lade ALLE verfügbaren Preisdaten für dieses Symbol
    # (von Anfang der Daten bis zum letzten Trade)
    entry_dates = [t.entry_date for t in trades]
    max_date = max(entry_dates)

    # Start von Anfang 2021 (da Optionsdaten ab 2021-01-04 beginnen)
    start_date = "2021-01-01"

    # Lade alle Preisdaten für dieses Symbol
    symbol_prices = get_price_data(symbol, start_date, max_date)

    if len(symbol_prices) < 50:
        logger.warning(f"{symbol}: Insufficient price data ({len(symbol_prices)} days)")
        return results

    # Berechne Scores für jeden Trade einzeln
    # Prüfe für jeden Trade ob genug Lookback vorhanden ist
    for trade in trades:
        try:
            # Prüfe ob genug Historie für diesen Trade vorhanden ist
            sorted_dates = sorted([d for d in symbol_prices.keys() if d <= trade.entry_date])
            if len(sorted_dates) < 50:
                logger.debug(f"{symbol} {trade.entry_date}: Not enough history ({len(sorted_dates)} days)")
                continue

            scores = calculate_scores_for_trade(trade, symbol_prices, spy_prices)
            if 'error' not in scores:
                results.append((trade.id, scores))
        except Exception as e:
            logger.debug(f"Error processing {symbol} {trade.entry_date}: {e}")

    return results


def update_scores_batch(updates: List[Tuple[int, Dict]]) -> int:
    """Aktualisiere Scores in der Datenbank (Batch)."""
    if not updates:
        return 0

    conn = sqlite3.connect(str(OUTCOMES_DB))
    cursor = conn.cursor()

    score_columns = [
        'rsi_score', 'support_score', 'fibonacci_score', 'ma_score', 'volume_score',
        'macd_score', 'stoch_score', 'keltner_score', 'trend_strength_score',
        'momentum_score', 'rs_score', 'candlestick_score',
        'vwap_score', 'market_context_score', 'sector_score', 'gap_score',
        'pullback_score', 'bounce_score', 'ath_breakout_score', 'earnings_dip_score',
        'rsi_value', 'distance_to_support_pct', 'spy_trend',
    ]

    updated = 0
    for trade_id, scores in updates:
        set_clauses = []
        values = []
        for col in score_columns:
            if col in scores:
                set_clauses.append(f"{col} = ?")
                values.append(scores[col])

        if set_clauses:
            values.append(trade_id)
            cursor.execute(
                f"UPDATE trade_outcomes SET {', '.join(set_clauses)} WHERE id = ?",
                values
            )
            updated += 1

    conn.commit()
    conn.close()
    return updated


def main():
    parser = argparse.ArgumentParser(description="Backfill component scores for historical trades")
    parser.add_argument("--limit", type=int, help="Limit number of trades to process")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel workers")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Backfill Component Scores")
    logger.info("=" * 60)

    # Hole Trades ohne Scores
    trades = get_trades_without_scores(args.limit)
    logger.info(f"Trades ohne Scores: {len(trades):,}")

    if not trades:
        logger.info("Keine Trades zu verarbeiten!")
        return

    # Gruppiere nach Symbol
    by_symbol: Dict[str, List[TradeToProcess]] = {}
    for trade in trades:
        if trade.symbol not in by_symbol:
            by_symbol[trade.symbol] = []
        by_symbol[trade.symbol].append(trade)

    logger.info(f"Unique Symbole: {len(by_symbol)}")

    # Lade SPY-Daten einmal
    logger.info("Lade SPY-Daten...")
    spy_prices = get_spy_prices("2020-01-01", "2026-01-31")
    logger.info(f"SPY-Datenpunkte: {len(spy_prices):,}")

    # Verarbeite Symbol für Symbol
    start_time = time.time()
    total_updated = 0

    symbols = list(by_symbol.keys())
    for i, symbol in enumerate(symbols):
        symbol_trades = by_symbol[symbol]

        # Verarbeite
        results = process_symbol_batch(symbol, symbol_trades, spy_prices)

        # Update DB
        if results:
            updated = update_scores_batch(results)
            total_updated += updated

        # Progress
        if (i + 1) % 10 == 0 or i == len(symbols) - 1:
            elapsed = time.time() - start_time
            rate = total_updated / elapsed if elapsed > 0 else 0
            remaining = (len(trades) - total_updated) / rate if rate > 0 else 0
            logger.info(
                f"Progress: {i+1}/{len(symbols)} Symbole | "
                f"{total_updated:,}/{len(trades):,} Trades | "
                f"{rate:.0f}/s | ETA: {remaining:.0f}s"
            )

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"Fertig! {total_updated:,} Trades aktualisiert in {elapsed:.1f}s")
    logger.info(f"Durchschnitt: {total_updated/elapsed:.0f} Trades/s")


if __name__ == "__main__":
    main()
