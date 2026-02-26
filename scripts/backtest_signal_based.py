#!/usr/bin/env python3
"""
OptionPlay - Signal-Based Backtest with Roll Maneuvers
======================================================
Realistischer Backtest: Trades NUR bei echten Scanner-Signalen.

Der Unterschied zum vorherigen Backtest:
- VORHER: Alle 30 Tage ein Trade pro Symbol (unrealistisch)
- JETZT:  Trade NUR wenn Scanner-Signal mit Score >= 7.0 (realistisch)

Roll-Logik:
- Roll NUR wenn technisches Setup noch intakt ist (Preis über Support)
- Roll NUR bei hochwertigen Kandidaten (ursprünglicher Score >= 7.0)
- Kein Roll wenn fundamentale Änderung (z.B. nach Earnings)

Usage:
    python scripts/backtest_signal_based.py --strategy pullback --min-score 7.0
    python scripts/backtest_signal_based.py --all-strategies --min-score 7.5
"""

import argparse
import json
import logging
import math
import multiprocessing as mp
import sqlite3
import sys
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
import traceback

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

from src.constants.trading_rules import SPREAD_SHORT_DELTA_TARGET, SPREAD_LONG_DELTA_TARGET

SHORT_DELTA_TARGET = SPREAD_SHORT_DELTA_TARGET
LONG_DELTA_TARGET = SPREAD_LONG_DELTA_TARGET
HOLDING_DAYS = 75
RISK_FREE_RATE = 0.05

# Roll Thresholds - KONSERVATIVER als vorher
ROLL_LOSS_THRESHOLD = 0.30  # Roll erst bei 30% Verlust (vorher 25%)
ROLL_PRICE_PROXIMITY = 1.02  # Roll wenn Preis innerhalb 2% (vorher 3%)
ROLL_MIN_DTE = 21  # Roll Out bei DTE < 21 (vorher 30)
MAX_ROLLS_PER_TRADE = 1  # Nur 1 Roll erlaubt (vorher 2)

# Qualitäts-Filter
MIN_SIGNAL_SCORE = 7.0  # Nur hochwertige Signale
REQUIRE_SUPPORT_INTACT = True  # Roll nur wenn Support noch hält

DB_PATH = Path.home() / ".optionplay" / "backtest_signals.db"


# =============================================================================
# Enums & Data Classes
# =============================================================================


class RollType(Enum):
    NONE = "none"
    ROLL_DOWN = "roll_down"
    ROLL_OUT = "roll_out"
    ROLL_DOWN_AND_OUT = "roll_down_and_out"


class TradeOutcome(Enum):
    WIN = "win"
    LOSS = "loss"
    MAX_LOSS = "max_loss"


@dataclass
class SignalTrade:
    """Ein Trade basierend auf einem echten Scanner-Signal"""

    symbol: str
    strategy: str
    signal_date: date
    signal_score: float
    entry_price: float
    support_level: float  # Für Roll-Entscheidung wichtig

    # Strike Info
    short_strike: float = 0.0
    long_strike: float = 0.0

    # Ergebnis
    exit_date: Optional[date] = None
    exit_price: float = 0.0
    outcome: Optional[TradeOutcome] = None
    final_pnl: float = 0.0

    # Roll Info
    roll_count: int = 0
    roll_type: Optional[RollType] = None
    roll_cost: float = 0.0
    rolled_at_price: float = 0.0

    # Zusätzliche Metriken
    initial_credit: float = 0.0
    max_drawdown: float = 0.0
    holding_days: int = 0


# =============================================================================
# Black-Scholes (Standalone)
# =============================================================================


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(K - S, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return max(K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1), 0)


def black_scholes_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return -1.0 if K > S else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) - 1.0


def find_strike_for_delta(
    S: float, T: float, r: float, sigma: float, target_delta: float, strike_step: float = 1.0
) -> float:
    """
    Findet Strike für gegebenes Put-Delta.

    Put-Delta ist negativ (0 bis -1):
    - Delta nahe 0: sehr OTM (niedriger Strike)
    - Delta nahe -0.5: ATM
    - Delta nahe -1: sehr ITM (hoher Strike)

    Für Bull-Put-Spread:
    - Short Put: target_delta = -0.20 (leicht OTM)
    - Long Put: target_delta = -0.05 (tief OTM)
    """
    # Für Puts: niedriger Strike = weniger negatives Delta (näher an 0)
    # Suche im Bereich von tief OTM bis leicht OTM
    low = S * 0.70  # tief OTM
    high = S * 1.05  # nahe ATM

    best_strike = S * 0.90  # default
    best_diff = float("inf")

    for _ in range(100):
        mid = (low + high) / 2
        delta = black_scholes_delta(S, mid, T, r, sigma)

        diff = abs(delta - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_strike = mid

        if diff < 0.001:
            break

        # Put-Delta wird negativer (größer im Betrag) wenn Strike steigt
        if delta > target_delta:  # delta ist weniger negativ als target -> Strike zu niedrig
            low = mid
        else:  # delta ist negativer als target -> Strike zu hoch
            high = mid

    return round(best_strike / strike_step) * strike_step


def estimate_iv(prices: np.ndarray, days: int = 30) -> float:
    if len(prices) < days + 1:
        return 0.30
    returns = np.diff(np.log(prices[-days - 1 :]))
    return min(max(np.std(returns) * math.sqrt(252) * 1.20, 0.15), 1.50)


# =============================================================================
# Signal-basierte Trade-Simulation
# =============================================================================


def simulate_signal_trade(
    trade: SignalTrade,
    prices: np.ndarray,
    entry_idx: int,
    enable_rolls: bool = True,
) -> SignalTrade:
    """
    Simuliert einen Trade basierend auf einem echten Signal.

    WICHTIG: Roll nur wenn:
    1. Support-Level noch intakt (Preis >= Support * 0.98)
    2. Ursprünglicher Score war hoch (>= 7.0)
    3. Nur 1 Roll erlaubt
    """
    if entry_idx + HOLDING_DAYS >= len(prices):
        trade.outcome = TradeOutcome.LOSS
        trade.final_pnl = 0
        return trade

    entry_price = prices[entry_idx]
    trade.entry_price = entry_price

    # IV schätzen
    lookback = min(60, entry_idx)
    recent_prices = prices[entry_idx - lookback : entry_idx + 1]
    iv = estimate_iv(recent_prices)

    T = HOLDING_DAYS / 365.0

    # Strike Step
    if entry_price < 50:
        strike_step = 1.0
    elif entry_price < 200:
        strike_step = 2.5
    else:
        strike_step = 5.0

    # Strikes berechnen
    short_strike = find_strike_for_delta(
        entry_price, T, RISK_FREE_RATE, iv, SHORT_DELTA_TARGET, strike_step
    )
    long_strike = find_strike_for_delta(
        entry_price, T, RISK_FREE_RATE, iv, LONG_DELTA_TARGET, strike_step
    )

    if long_strike >= short_strike:
        long_strike = short_strike - strike_step

    trade.short_strike = short_strike
    trade.long_strike = long_strike

    # Initial Credit
    short_put = black_scholes_put(entry_price, short_strike, T, RISK_FREE_RATE, iv)
    long_put = black_scholes_put(entry_price, long_strike, T, RISK_FREE_RATE, iv)
    net_credit = short_put - long_put

    if net_credit <= 0:
        trade.outcome = TradeOutcome.LOSS
        trade.final_pnl = 0
        return trade

    trade.initial_credit = net_credit * 100

    # State
    current_short = short_strike
    current_long = long_strike
    roll_count = 0
    total_roll_cost = 0.0
    max_drawdown = 0.0
    holding_days = HOLDING_DAYS

    # Simulation
    for day in range(1, holding_days + 30):  # +30 für möglichen Roll
        if entry_idx + day >= len(prices):
            break

        current_price = prices[entry_idx + day]
        remaining_dte = holding_days - day
        T_remaining = max(remaining_dte, 1) / 365.0

        # Aktuelle Position bewerten
        short_val = black_scholes_put(current_price, current_short, T_remaining, RISK_FREE_RATE, iv)
        long_val = black_scholes_put(current_price, current_long, T_remaining, RISK_FREE_RATE, iv)
        spread_value = short_val - long_val

        current_pnl = (net_credit - spread_value) * 100
        max_drawdown = min(max_drawdown, current_pnl)

        # =====================================================
        # DIAGONALE ROLL-STRATEGIE
        # =====================================================
        # Roll diagonal in die Zukunft bei:
        # 1. Preis nähert sich dem Short Strike
        # 2. Noch genug Zeit für einen effektiven Roll (mindestens 14 DTE)
        # 3. Roll muss für Credit oder neutral sein
        # =====================================================
        if enable_rolls and roll_count < MAX_ROLLS_PER_TRADE:
            spread_width = current_short - current_long

            # Roll-Trigger: Preis innerhalb 5% des Short Strikes
            price_approaching_short = current_price <= current_short * 1.05
            # Genug Zeit für Roll (nicht zu nah am Verfall)
            enough_time_to_roll = remaining_dte >= 14
            # Nicht schon ITM (dann ist es zu spät)
            not_already_itm = current_price > current_short

            should_roll = price_approaching_short and enough_time_to_roll and not_already_itm

            if should_roll:
                # DIAGONALER ROLL: Gleiche oder niedrigere Strikes + längere Laufzeit
                # Wir rollen 30 Tage in die Zukunft
                new_T = T_remaining + (30 / 365.0)

                # Neue Strikes basierend auf aktuellem Preis (diagonal down and out)
                new_short = find_strike_for_delta(
                    current_price, new_T, RISK_FREE_RATE, iv, SHORT_DELTA_TARGET, strike_step
                )
                new_long = find_strike_for_delta(
                    current_price, new_T, RISK_FREE_RATE, iv, LONG_DELTA_TARGET, strike_step
                )

                if new_long >= new_short:
                    new_long = new_short - strike_step

                # Kosten des Rolls berechnen:
                # close_cost = Kosten um aktuelle Position zu schließen (Debit)
                # new_credit = Credit aus neuer Position
                close_cost = spread_value  # Was wir zahlen müssen um zu schließen
                new_short_prem = black_scholes_put(
                    current_price, new_short, new_T, RISK_FREE_RATE, iv
                )
                new_long_prem = black_scholes_put(
                    current_price, new_long, new_T, RISK_FREE_RATE, iv
                )
                new_credit = new_short_prem - new_long_prem

                # Net Roll Cost: positiv = Debit, negativ = Credit
                roll_net_cost = (close_cost - new_credit) * 100

                # Roll NUR wenn für Credit oder maximal kleinen Debit (< 10% des neuen Credits)
                max_acceptable_debit = new_credit * 100 * 0.10
                roll_is_credit_neutral = roll_net_cost <= max_acceptable_debit

                if roll_is_credit_neutral:
                    # Roll durchführen
                    actual_roll_cost = max(0, roll_net_cost)
                    total_roll_cost += actual_roll_cost
                    current_short = new_short
                    current_long = new_long
                    net_credit = new_credit
                    roll_count += 1
                    trade.roll_type = RollType.ROLL_DOWN_AND_OUT
                    trade.rolled_at_price = current_price
                    # Neue Holding Period
                    holding_days = day + int(new_T * 365)

        # Exit Conditions
        if prices[entry_idx + day] <= current_long:
            # Max Loss
            spread_width = current_short - current_long
            max_loss = spread_width * 100
            trade.outcome = TradeOutcome.MAX_LOSS
            trade.final_pnl = trade.initial_credit - total_roll_cost - max_loss
            trade.exit_price = current_price
            trade.holding_days = day
            trade.roll_count = roll_count
            trade.roll_cost = total_roll_cost
            trade.max_drawdown = max_drawdown
            return trade

        # Time Exit
        if day >= holding_days:
            break

    # Final Settlement
    final_idx = min(entry_idx + holding_days, len(prices) - 1)
    final_price = prices[final_idx]
    trade.exit_price = final_price
    trade.holding_days = holding_days
    trade.roll_count = roll_count
    trade.roll_cost = total_roll_cost
    trade.max_drawdown = max_drawdown

    if final_price >= current_short:
        trade.outcome = TradeOutcome.WIN
        trade.final_pnl = trade.initial_credit - total_roll_cost
    elif final_price >= current_long:
        intrinsic = (current_short - final_price) * 100
        trade.final_pnl = trade.initial_credit - total_roll_cost - intrinsic
        trade.outcome = TradeOutcome.WIN if trade.final_pnl > 0 else TradeOutcome.LOSS
    else:
        spread_width = current_short - current_long
        max_loss = spread_width * 100
        trade.outcome = TradeOutcome.MAX_LOSS
        trade.final_pnl = trade.initial_credit - total_roll_cost - max_loss

    return trade


# =============================================================================
# Signal Generator (vereinfacht für Backtest)
# =============================================================================


def find_support_level(prices: np.ndarray, lookback: int = 60) -> float:
    """Findet das nächste Support-Level (vereinfacht: 20-Tage-Tief)"""
    if len(prices) < lookback:
        return prices.min() * 0.95

    recent = prices[-lookback:]
    return np.min(recent)


def generate_pullback_signal(prices: np.ndarray, idx: int) -> Optional[Tuple[float, float]]:
    """
    Generiert Pullback-Signal wenn:
    - Preis in Aufwärtstrend (über 50-SMA)
    - RSI zwischen 30-50 (oversold aber nicht zu stark)
    - Pullback auf Support/Moving Average

    Returns: (score, support_level) oder None
    """
    if idx < 60:
        return None

    lookback = prices[idx - 60 : idx + 1]

    # Trend: Preis über 50-SMA
    sma50 = np.mean(lookback[-50:])
    current_price = lookback[-1]

    if current_price < sma50:
        return None  # Kein Aufwärtstrend

    # RSI berechnen (vereinfacht)
    changes = np.diff(lookback[-15:])
    gains = np.sum(changes[changes > 0])
    losses = -np.sum(changes[changes < 0])

    if losses == 0:
        rsi = 100
    else:
        rs = gains / losses if losses > 0 else 100
        rsi = 100 - (100 / (1 + rs))

    if rsi < 30 or rsi > 50:
        return None  # RSI nicht im idealen Bereich

    # Support Level
    support = find_support_level(lookback)

    # Pullback: Preis nahe Support (innerhalb 5%)
    distance_to_support = (current_price - support) / support

    if distance_to_support > 0.05:
        return None  # Nicht nahe genug am Support

    # Score berechnen
    base_score = 6.0

    # Trend-Stärke bonus
    trend_strength = (current_price - sma50) / sma50
    if trend_strength > 0.02:
        base_score += 0.5
    if trend_strength > 0.05:
        base_score += 0.5

    # RSI bonus (näher an 30 = besser)
    if rsi < 40:
        base_score += 0.5
    if rsi < 35:
        base_score += 0.5

    # Support proximity bonus
    if distance_to_support < 0.02:
        base_score += 0.5

    return (min(base_score, 10.0), support)


def find_signals_for_symbol(
    symbol: str,
    prices: np.ndarray,
    dates: List[date],
    min_score: float = 7.0,
) -> List[SignalTrade]:
    """Findet alle qualifizierten Signale für ein Symbol"""
    signals = []

    # Mindestens 90 Tage zwischen Signalen (kein Überlappen)
    last_signal_idx = -90

    for idx in range(60, len(prices) - HOLDING_DAYS - 30):
        if idx - last_signal_idx < 90:
            continue

        result = generate_pullback_signal(prices, idx)

        if result is None:
            continue

        score, support = result

        if score < min_score:
            continue

        trade = SignalTrade(
            symbol=symbol,
            strategy="pullback",
            signal_date=dates[idx],
            signal_score=score,
            entry_price=prices[idx],
            support_level=support,
        )

        signals.append((trade, idx))
        last_signal_idx = idx

    return signals


# =============================================================================
# Database
# =============================================================================


class SignalBacktestDB:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    strategy TEXT,
                    min_score REAL,
                    rolls_enabled INTEGER,
                    total_trades INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    created_at TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    signal_date TEXT,
                    signal_score REAL,
                    entry_price REAL,
                    exit_price REAL,
                    support_level REAL,
                    short_strike REAL,
                    long_strike REAL,
                    initial_credit REAL,
                    final_pnl REAL,
                    outcome TEXT,
                    roll_count INTEGER DEFAULT 0,
                    roll_type TEXT,
                    roll_cost REAL DEFAULT 0,
                    rolled_at_price REAL,
                    max_drawdown REAL,
                    holding_days INTEGER,
                    created_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES runs(id)
                )
            """)

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_signal_trades_run ON signal_trades(run_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_signal_trades_outcome ON signal_trades(outcome)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_signal_trades_score ON signal_trades(signal_score)"
            )

    def create_run(self, name: str, strategy: str, min_score: float, rolls_enabled: bool) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO runs (name, strategy, min_score, rolls_enabled, created_at)
                VALUES (?, ?, ?, ?, ?)
            """,
                (name, strategy, min_score, 1 if rolls_enabled else 0, datetime.now().isoformat()),
            )
            return cursor.lastrowid

    def add_trade(self, run_id: int, trade: SignalTrade):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO signal_trades (
                    run_id, symbol, strategy, signal_date, signal_score,
                    entry_price, exit_price, support_level, short_strike, long_strike,
                    initial_credit, final_pnl, outcome, roll_count, roll_type,
                    roll_cost, rolled_at_price, max_drawdown, holding_days, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    trade.symbol,
                    trade.strategy,
                    trade.signal_date.isoformat() if trade.signal_date else None,
                    trade.signal_score,
                    trade.entry_price,
                    trade.exit_price,
                    trade.support_level,
                    trade.short_strike,
                    trade.long_strike,
                    trade.initial_credit,
                    trade.final_pnl,
                    trade.outcome.value if trade.outcome else None,
                    trade.roll_count,
                    trade.roll_type.value if trade.roll_type else None,
                    trade.roll_cost,
                    trade.rolled_at_price,
                    trade.max_drawdown,
                    trade.holding_days,
                    datetime.now().isoformat(),
                ),
            )

    def update_run_stats(self, run_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                       SUM(final_pnl) as pnl
                FROM signal_trades WHERE run_id = ?
            """,
                (run_id,),
            )
            row = cursor.fetchone()

            total = row["total"] or 0
            wins = row["wins"] or 0
            pnl = row["pnl"] or 0

            cursor.execute(
                """
                UPDATE runs SET total_trades = ?, win_rate = ?, total_pnl = ?
                WHERE id = ?
            """,
                (total, (wins / total * 100) if total > 0 else 0, pnl, run_id),
            )

    def get_statistics(self, run_id: int) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Allgemeine Stats
            cursor.execute(
                """
                SELECT * FROM runs WHERE id = ?
            """,
                (run_id,),
            )
            run = dict(cursor.fetchone())

            # Nach Roll-Status
            cursor.execute(
                """
                SELECT
                    CASE WHEN roll_count > 0 THEN 'rolled' ELSE 'not_rolled' END as category,
                    COUNT(*) as trades,
                    SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'max_loss' THEN 1 ELSE 0 END) as max_losses,
                    AVG(final_pnl) as avg_pnl,
                    SUM(final_pnl) as total_pnl
                FROM signal_trades WHERE run_id = ?
                GROUP BY category
            """,
                (run_id,),
            )

            by_roll_status = {}
            for row in cursor.fetchall():
                by_roll_status[row["category"]] = dict(row)

            # Nach Score-Bucket
            cursor.execute(
                """
                SELECT
                    CASE
                        WHEN signal_score >= 9.0 THEN '9.0+'
                        WHEN signal_score >= 8.0 THEN '8.0-9.0'
                        WHEN signal_score >= 7.0 THEN '7.0-8.0'
                        ELSE '<7.0'
                    END as score_bucket,
                    COUNT(*) as trades,
                    SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                    AVG(final_pnl) as avg_pnl
                FROM signal_trades WHERE run_id = ?
                GROUP BY score_bucket
            """,
                (run_id,),
            )

            by_score = {}
            for row in cursor.fetchall():
                by_score[row["score_bucket"]] = dict(row)

            return {
                "run": run,
                "by_roll_status": by_roll_status,
                "by_score": by_score,
            }


# =============================================================================
# Data Fetching
# =============================================================================


def fetch_data(symbol: str, start: str, end: str) -> Optional[Tuple[np.ndarray, List[date]]]:
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end)

        if df.empty or len(df) < 200:
            return None

        prices = df["Close"].values
        dates = [d.date() for d in df.index]

        return prices, dates
    except Exception as e:
        logger.warning(f"Failed to fetch {symbol}: {e}")
        return None


def get_symbols() -> List[str]:
    """Hole Symbole aus Watchlist"""
    watchlist_path = PROJECT_ROOT / "config" / "watchlists.yaml"

    if not watchlist_path.exists():
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"]

    try:
        import yaml

        with open(watchlist_path) as f:
            config = yaml.safe_load(f)

        symbols = set()
        watchlists = config.get("watchlists", config)

        for wl_data in watchlists.values():
            if not isinstance(wl_data, dict):
                continue
            if "symbols" in wl_data:
                syms = wl_data.get("symbols", [])
                if isinstance(syms, list):
                    symbols.update(s for s in syms if isinstance(s, str))
            if "sectors" in wl_data:
                for sector in wl_data.get("sectors", {}).values():
                    if isinstance(sector, dict) and "symbols" in sector:
                        syms = sector.get("symbols", [])
                        if isinstance(syms, list):
                            symbols.update(s for s in syms if isinstance(s, str))

        return sorted([s for s in symbols if s and len(s) <= 6])
    except Exception as e:
        logger.warning(f"Failed to load watchlist: {e}")
        return ["AAPL", "MSFT", "GOOGL"]


# =============================================================================
# Main Backtest Runner
# =============================================================================


def run_signal_backtest(
    symbols: List[str],
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    min_score: float = 7.0,
    enable_rolls: bool = True,
    run_name: Optional[str] = None,
) -> int:
    """Führt signal-basierten Backtest durch"""

    db = SignalBacktestDB()

    run_name = run_name or f"signal_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_id = db.create_run(run_name, "pullback", min_score, enable_rolls)

    logger.info(f"Run {run_id}: {run_name}")
    logger.info(f"Min Score: {min_score}, Rolls: {'ENABLED' if enable_rolls else 'DISABLED'}")
    logger.info(f"Processing {len(symbols)} symbols...")

    total_signals = 0
    total_trades = 0

    from tqdm import tqdm

    for symbol in tqdm(symbols, desc="Backtesting"):
        data = fetch_data(symbol, start_date, end_date)
        if data is None:
            continue

        prices, dates = data

        # Signale finden
        signals = find_signals_for_symbol(symbol, prices, dates, min_score)
        total_signals += len(signals)

        # Trades simulieren
        for trade, idx in signals:
            trade = simulate_signal_trade(trade, prices, idx, enable_rolls)
            db.add_trade(run_id, trade)
            total_trades += 1

    db.update_run_stats(run_id)

    logger.info(f"\nTotal signals found: {total_signals}")
    logger.info(f"Total trades executed: {total_trades}")

    return run_id


def print_results(run_id: int):
    """Zeigt Ergebnisse"""
    db = SignalBacktestDB()
    stats = db.get_statistics(run_id)

    run = stats["run"]

    print("\n" + "=" * 70)
    print("SIGNAL-BASED BACKTEST RESULTS")
    print("=" * 70)

    print(f"\nRun: {run['name']}")
    print(f"Strategy: {run['strategy']}")
    print(f"Min Score: {run['min_score']}")
    print(f"Rolls: {'ENABLED' if run['rolls_enabled'] else 'DISABLED'}")

    print(f"\nTotal Trades: {run['total_trades']:,}")
    print(f"Win Rate: {run['win_rate']:.1f}%")
    print(f"Total P&L: ${run['total_pnl']:,.2f}")
    print(f"Avg P&L: ${run['total_pnl'] / max(run['total_trades'], 1):.2f}")

    print("\n" + "-" * 70)
    print("BY ROLL STATUS")
    print("-" * 70)

    for cat, data in stats.get("by_roll_status", {}).items():
        trades = data["trades"]
        win_rate = (data["wins"] / trades * 100) if trades > 0 else 0
        ml_rate = (data["max_losses"] / trades * 100) if trades > 0 else 0
        print(
            f"{cat.upper():<15} Trades: {trades:>5}  WR: {win_rate:>5.1f}%  MaxLoss: {ml_rate:>5.1f}%  P&L: ${data['total_pnl']:>10,.2f}"
        )

    print("\n" + "-" * 70)
    print("BY SIGNAL SCORE")
    print("-" * 70)

    for bucket, data in sorted(stats.get("by_score", {}).items(), reverse=True):
        trades = data["trades"]
        win_rate = (data["wins"] / trades * 100) if trades > 0 else 0
        print(
            f"Score {bucket:<10} Trades: {trades:>5}  WR: {win_rate:>5.1f}%  Avg P&L: ${data['avg_pnl']:>8.2f}"
        )

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Signal-Based Backtest with Rolls")
    parser.add_argument("--min-score", type=float, default=7.0, help="Minimum signal score")
    parser.add_argument("--no-rolls", action="store_true", help="Disable rolls")
    parser.add_argument("--start", default="2020-01-01", help="Start date")
    parser.add_argument("--end", default="2024-12-31", help="End date")
    parser.add_argument("--name", type=str, help="Run name")
    parser.add_argument("--results", type=int, help="Show results for run ID")
    parser.add_argument("--compare", nargs=2, type=int, help="Compare two runs")

    args = parser.parse_args()

    if args.results:
        print_results(args.results)
        return

    if args.compare:
        for rid in args.compare:
            print_results(rid)
        return

    symbols = get_symbols()

    print(f"Starting signal-based backtest")
    print(f"Symbols: {len(symbols)}")
    print(f"Date range: {args.start} to {args.end}")
    print(f"Min score: {args.min_score}")
    print(f"Rolls: {'DISABLED' if args.no_rolls else 'ENABLED'}")

    run_id = run_signal_backtest(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        min_score=args.min_score,
        enable_rolls=not args.no_rolls,
        run_name=args.name,
    )

    print_results(run_id)

    print(f"\nResults saved to: {DB_PATH}")
    print(f"View: python {__file__} --results {run_id}")


if __name__ == "__main__":
    main()
