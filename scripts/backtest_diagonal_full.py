#!/usr/bin/env python3
"""
OptionPlay - Vollständiger Diagonaler Roll-Strategie Backtest
==============================================================

Nutzt die historischen Daten aus der trades.db Datenbank.
Black-Scholes für Options-Pricing wenn keine echten Preise verfügbar.

Features:
- Lädt Preisdaten aus der lokalen DB (628 Symbole, 5+ Jahre)
- VIX-Daten für Regime-Tracking
- Optionale echte Options-Preise (ab Mai 2025)
- Multi-Worker Unterstützung (auch über Thunderbolt-Verbindung)

Usage:
    # Vollständiger Backtest mit allen Symbolen
    python scripts/backtest_diagonal_full.py --all --workers 8

    # Nur Symbole mit mindestens 3 Jahren Daten
    python scripts/backtest_diagonal_full.py --min-years 3 --workers 8

    # Watchlist
    python scripts/backtest_diagonal_full.py --watchlist default_275 --workers 8

    # Distributed (für Thunderbolt-verbundenen Worker)
    python scripts/backtest_diagonal_full.py --distributed --worker-id 0 --total-workers 2
"""

import argparse
import json
import logging
import math
import multiprocessing as mp
import sqlite3
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
import pickle
import socket

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from tqdm import tqdm

# Import from project
from src.backtesting.tracking import TradeTracker, PriceBar, SymbolPriceData, VixDataPoint

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# Delta targets (from PLAYBOOK)
from src.constants.trading_rules import SPREAD_SHORT_DELTA_TARGET, SPREAD_LONG_DELTA_TARGET
SHORT_DELTA_TARGET = SPREAD_SHORT_DELTA_TARGET
LONG_DELTA_TARGET = SPREAD_LONG_DELTA_TARGET
INITIAL_DTE = 45
RISK_FREE_RATE = 0.05

# Diagonal Roll Parameters
ROLL_TRIGGER_PCT = -50.0
ROLL_DTE_EXTENSION = 60
ROLL_DTE_EXTENSION_MAX = 90
MAX_ROLLS_PER_TRADE = 5
MIN_ROLL_CREDIT_PCT = 0.50
SUPPORT_BUFFER_PCT = 2.0

# Exit Parameters
PROFIT_TARGET_PCT = 50.0
MAX_HOLDING_DAYS = 365

# Database paths
TRADES_DB_PATH = Path.home() / ".optionplay" / "trades.db"
RESULTS_DB_PATH = Path.home() / ".optionplay" / "backtest_diagonal_full.db"


# =============================================================================
# Enums
# =============================================================================

class RollType(Enum):
    NONE = "none"
    DIAGONAL_ROLL = "diagonal_roll"
    AGGRESSIVE_ROLL = "aggressive_roll"
    DEFENSIVE_ROLL = "defensive_roll"


class TradeOutcome(Enum):
    WIN = "win"
    LOSS = "loss"
    MAX_LOSS = "max_loss"
    ROLLED_WIN = "rolled_win"
    ROLLED_LOSS = "rolled_loss"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DiagonalRollEvent:
    roll_day: int
    roll_type: RollType
    old_short_strike: float
    new_short_strike: float
    old_long_strike: float
    new_long_strike: float
    old_expiry_dte: int
    new_expiry_dte: int
    close_cost: float
    new_credit: float
    roll_net: float
    stock_price_at_roll: float
    support_level_used: Optional[float]
    loss_at_roll_pct: float
    cumulative_credit: float
    cumulative_cost: float
    vix_at_roll: Optional[float] = None


@dataclass
class DiagonalTradeResult:
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    initial_short_strike: float
    initial_long_strike: float
    initial_dte: int
    initial_credit: float
    final_short_strike: float
    final_long_strike: float
    final_dte_remaining: int
    total_credits_received: float
    total_costs_paid: float
    final_pnl: float
    outcome: TradeOutcome
    roll_count: int = 0
    roll_events: List[DiagonalRollEvent] = field(default_factory=list)
    max_drawdown_pct: float = 0.0
    holding_days: int = 0
    iv_at_entry: float = 0.0
    vix_at_entry: Optional[float] = None
    lowest_price_seen: float = 0.0
    support_levels_used: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'entry_date': self.entry_date.isoformat(),
            'exit_date': self.exit_date.isoformat(),
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'initial_short_strike': self.initial_short_strike,
            'initial_long_strike': self.initial_long_strike,
            'initial_dte': self.initial_dte,
            'initial_credit': self.initial_credit,
            'final_short_strike': self.final_short_strike,
            'final_long_strike': self.final_long_strike,
            'final_dte_remaining': self.final_dte_remaining,
            'total_credits_received': self.total_credits_received,
            'total_costs_paid': self.total_costs_paid,
            'final_pnl': self.final_pnl,
            'outcome': self.outcome.value,
            'roll_count': self.roll_count,
            'max_drawdown_pct': self.max_drawdown_pct,
            'holding_days': self.holding_days,
            'iv_at_entry': self.iv_at_entry,
            'vix_at_entry': self.vix_at_entry,
            'lowest_price_seen': self.lowest_price_seen,
        }


# =============================================================================
# Black-Scholes Functions
# =============================================================================

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(K - S, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return max(K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1), 0)


def black_scholes_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return -1.0 if K > S else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) - 1.0


def find_strike_for_delta(S: float, T: float, r: float, sigma: float,
                          target_delta: float, strike_step: float = 1.0) -> float:
    low, high = S * 0.50, S * 1.20
    for _ in range(50):
        mid = (low + high) / 2
        delta = black_scholes_delta(S, mid, T, r, sigma)
        if abs(delta - target_delta) < 0.001:
            break
        if delta < target_delta:
            low = mid
        else:
            high = mid
    return round(mid / strike_step) * strike_step


def estimate_iv_from_history(prices: np.ndarray, days: int = 30) -> float:
    if len(prices) < days + 1:
        return 0.30
    returns = np.diff(np.log(prices[-days-1:]))
    daily_vol = np.std(returns)
    annual_vol = daily_vol * math.sqrt(252)
    return min(max(annual_vol * 1.20, 0.15), 1.50)


# =============================================================================
# Support Level Detection
# =============================================================================

def find_support_levels_simple(lows: np.ndarray, lookback: int = 60,
                               window: int = 5, max_levels: int = 5,
                               tolerance_pct: float = 1.5) -> List[float]:
    if len(lows) < 2 * window + 1:
        return []

    lookback = min(lookback, len(lows))
    recent_lows = lows[-lookback:]

    swing_lows = []
    for i in range(window, len(recent_lows) - window):
        is_minimum = True
        for j in range(1, window + 1):
            if recent_lows[i] >= recent_lows[i - j] or recent_lows[i] >= recent_lows[i + j]:
                is_minimum = False
                break
        if is_minimum:
            swing_lows.append(recent_lows[i])

    if not swing_lows:
        return [float(np.min(recent_lows))]

    swing_lows = sorted(swing_lows)
    clusters = []

    for price in swing_lows:
        found = False
        for cluster in clusters:
            if abs(price - cluster['avg']) / cluster['avg'] * 100 <= tolerance_pct:
                cluster['prices'].append(price)
                cluster['avg'] = sum(cluster['prices']) / len(cluster['prices'])
                cluster['count'] += 1
                found = True
                break
        if not found:
            clusters.append({'avg': price, 'prices': [price], 'count': 1})

    clusters.sort(key=lambda x: x['count'], reverse=True)
    return [c['avg'] for c in clusters[:max_levels]]


def find_next_support_below(current_price: float, support_levels: List[float],
                            buffer_pct: float = 2.0) -> Optional[float]:
    supports_below = [s for s in support_levels if s < current_price]
    if not supports_below:
        return None
    return max(supports_below) * (1 - buffer_pct / 100)


# =============================================================================
# Data Loading from Database
# =============================================================================

def load_price_data_from_db(symbols: Optional[List[str]] = None,
                            min_bars: int = 252) -> Dict[str, SymbolPriceData]:
    """Load price data from trades.db database"""
    tracker = TradeTracker(str(TRADES_DB_PATH))

    # Get list of symbols with sufficient data
    available = tracker.list_symbols_with_price_data()

    if symbols:
        # Filter to requested symbols
        available = [s for s in available if s['symbol'] in symbols]

    # Filter by minimum bars
    available = [s for s in available if s['bar_count'] >= min_bars]

    logger.info(f"Loading price data for {len(available)} symbols (min {min_bars} bars)")

    price_data = {}
    for item in tqdm(available, desc="Loading price data"):
        symbol = item['symbol']
        try:
            data = tracker.get_price_data(symbol)
            if data and data.bars:
                price_data[symbol] = data
        except Exception as e:
            logger.warning(f"Failed to load {symbol}: {e}")

    return price_data


def load_vix_data_from_db() -> Dict[date, float]:
    """Load VIX data from database"""
    tracker = TradeTracker(str(TRADES_DB_PATH))
    vix_points = tracker.get_vix_data()

    return {v.date: v.value for v in vix_points}


# =============================================================================
# Diagonal Roll Simulation
# =============================================================================

def simulate_diagonal_roll_trade(
    bars: List[PriceBar],
    entry_idx: int,
    symbol: str,
    vix_data: Dict[date, float],
) -> Optional[DiagonalTradeResult]:
    """Simulate a Bull-Put-Spread trade with diagonal roll strategy"""

    if entry_idx + INITIAL_DTE >= len(bars):
        return None

    entry_bar = bars[entry_idx]
    entry_price = entry_bar.close
    entry_date = entry_bar.date

    # Get VIX at entry
    vix_at_entry = vix_data.get(entry_date)

    # Build price arrays
    prices = np.array([b.close for b in bars])
    highs = np.array([b.high for b in bars])
    lows = np.array([b.low for b in bars])

    # Estimate IV
    lookback = min(60, entry_idx)
    recent_prices = prices[entry_idx - lookback:entry_idx + 1]
    iv = estimate_iv_from_history(recent_prices)

    # Adjust IV based on VIX if available
    if vix_at_entry:
        vix_iv_ratio = vix_at_entry / 20.0  # VIX 20 = neutral
        iv = iv * (0.5 + 0.5 * vix_iv_ratio)  # Blend

    # Strike step
    if entry_price < 50:
        strike_step = 1.0
    elif entry_price < 200:
        strike_step = 2.5
    else:
        strike_step = 5.0

    # Initial position
    T = INITIAL_DTE / 365.0
    short_strike = find_strike_for_delta(entry_price, T, RISK_FREE_RATE, iv, SHORT_DELTA_TARGET, strike_step)
    long_strike = find_strike_for_delta(entry_price, T, RISK_FREE_RATE, iv, LONG_DELTA_TARGET, strike_step)

    if long_strike >= short_strike:
        long_strike = short_strike - strike_step

    # Calculate initial credit
    short_put = black_scholes_put(entry_price, short_strike, T, RISK_FREE_RATE, iv)
    long_put = black_scholes_put(entry_price, long_strike, T, RISK_FREE_RATE, iv)
    initial_credit = short_put - long_put

    if initial_credit <= 0:
        return None

    # Initialize tracking
    current_short = short_strike
    current_long = long_strike
    current_expiry_day = entry_idx + INITIAL_DTE

    total_credits = initial_credit * 100
    total_costs = 0.0
    roll_count = 0
    roll_events = []
    max_drawdown_pct = 0.0
    lowest_price = entry_price
    support_levels_used = []

    day = 0
    max_day = min(MAX_HOLDING_DAYS, len(bars) - entry_idx - 1)

    while day < max_day:
        day += 1
        current_idx = entry_idx + day

        if current_idx >= len(bars):
            break

        current_bar = bars[current_idx]
        current_price = current_bar.close
        current_date = current_bar.date
        lowest_price = min(lowest_price, current_bar.low)

        # Get VIX for current day
        current_vix = vix_data.get(current_date)

        # Calculate DTE remaining
        dte_remaining = current_expiry_day - current_idx
        T_remaining = max(dte_remaining, 0) / 365.0

        # Current spread value
        if T_remaining > 0:
            short_val = black_scholes_put(current_price, current_short, T_remaining, RISK_FREE_RATE, iv)
            long_val = black_scholes_put(current_price, current_long, T_remaining, RISK_FREE_RATE, iv)
        else:
            short_val = max(current_short - current_price, 0)
            long_val = max(current_long - current_price, 0)

        spread_value = short_val - long_val

        # Current P&L
        current_pnl = total_credits - total_costs - (spread_value * 100)

        # P&L percentage
        initial_credit_dollars = initial_credit * 100
        if initial_credit_dollars > 0.01:
            pnl_pct = (current_pnl / initial_credit_dollars) * 100
        else:
            pnl_pct = 0.0

        # Track drawdown
        if pnl_pct < max_drawdown_pct and pnl_pct > -500:
            max_drawdown_pct = pnl_pct

        # Check profit target
        if pnl_pct >= PROFIT_TARGET_PCT:
            outcome = TradeOutcome.ROLLED_WIN if roll_count > 0 else TradeOutcome.WIN
            return DiagonalTradeResult(
                symbol=symbol,
                entry_date=entry_date,
                exit_date=current_date,
                entry_price=entry_price,
                exit_price=current_price,
                initial_short_strike=short_strike,
                initial_long_strike=long_strike,
                initial_dte=INITIAL_DTE,
                initial_credit=initial_credit * 100,
                final_short_strike=current_short,
                final_long_strike=current_long,
                final_dte_remaining=dte_remaining,
                total_credits_received=total_credits,
                total_costs_paid=total_costs,
                final_pnl=current_pnl,
                outcome=outcome,
                roll_count=roll_count,
                roll_events=roll_events,
                max_drawdown_pct=max_drawdown_pct,
                holding_days=day,
                iv_at_entry=iv,
                vix_at_entry=vix_at_entry,
                lowest_price_seen=lowest_price,
                support_levels_used=support_levels_used,
            )

        # Check expiration
        if dte_remaining <= 0:
            final_spread = max(current_short - current_price, 0) - max(current_long - current_price, 0)
            final_pnl = total_credits - total_costs - (final_spread * 100)

            if final_pnl > 0:
                outcome = TradeOutcome.ROLLED_WIN if roll_count > 0 else TradeOutcome.WIN
            elif current_price <= current_long:
                outcome = TradeOutcome.MAX_LOSS
            else:
                outcome = TradeOutcome.ROLLED_LOSS if roll_count > 0 else TradeOutcome.LOSS

            return DiagonalTradeResult(
                symbol=symbol,
                entry_date=entry_date,
                exit_date=current_date,
                entry_price=entry_price,
                exit_price=current_price,
                initial_short_strike=short_strike,
                initial_long_strike=long_strike,
                initial_dte=INITIAL_DTE,
                initial_credit=initial_credit * 100,
                final_short_strike=current_short,
                final_long_strike=current_long,
                final_dte_remaining=0,
                total_credits_received=total_credits,
                total_costs_paid=total_costs,
                final_pnl=final_pnl,
                outcome=outcome,
                roll_count=roll_count,
                roll_events=roll_events,
                max_drawdown_pct=max_drawdown_pct,
                holding_days=day,
                iv_at_entry=iv,
                vix_at_entry=vix_at_entry,
                lowest_price_seen=lowest_price,
                support_levels_used=support_levels_used,
            )

        # DIAGONAL ROLL TRIGGER
        if pnl_pct <= ROLL_TRIGGER_PCT and roll_count < MAX_ROLLS_PER_TRADE:
            lookback_lows = lows[max(0, current_idx - 252):current_idx]
            support_levels = find_support_levels_simple(lookback_lows)

            target_price = find_next_support_below(current_price, support_levels, SUPPORT_BUFFER_PCT)
            if target_price is None:
                target_price = current_price * 0.90

            extension = ROLL_DTE_EXTENSION if roll_count < 2 else ROLL_DTE_EXTENSION_MAX
            new_dte = extension
            new_T = new_dte / 365.0
            new_expiry_day = current_idx + new_dte

            if new_expiry_day >= len(bars) - 1:
                new_expiry_day = len(bars) - 30
                new_dte = new_expiry_day - current_idx
                new_T = new_dte / 365.0

            new_short = round(target_price / strike_step) * strike_step
            if new_short >= current_price:
                new_short = find_strike_for_delta(current_price, new_T, RISK_FREE_RATE, iv, SHORT_DELTA_TARGET, strike_step)

            new_long = find_strike_for_delta(current_price, new_T, RISK_FREE_RATE, iv, LONG_DELTA_TARGET, strike_step)
            if new_long >= new_short:
                new_long = new_short - strike_step

            # Calculate roll costs
            close_cost = spread_value * 100

            new_short_put = black_scholes_put(current_price, new_short, new_T, RISK_FREE_RATE, iv)
            new_long_put = black_scholes_put(current_price, new_long, new_T, RISK_FREE_RATE, iv)
            new_credit = (new_short_put - new_long_put) * 100

            roll_net = new_credit - close_cost

            current_loss = abs(current_pnl) if current_pnl < 0 else 0
            credit_recovery = new_credit / max(current_loss, 1)

            if new_credit > 0 and (roll_net >= 0 or credit_recovery >= MIN_ROLL_CREDIT_PCT):
                support_used = target_price

                roll_pnl_pct = max(-500, min(500, pnl_pct))

                roll_event = DiagonalRollEvent(
                    roll_day=day,
                    roll_type=RollType.DIAGONAL_ROLL if roll_count < 2 else RollType.AGGRESSIVE_ROLL,
                    old_short_strike=current_short,
                    new_short_strike=new_short,
                    old_long_strike=current_long,
                    new_long_strike=new_long,
                    old_expiry_dte=dte_remaining,
                    new_expiry_dte=new_dte,
                    close_cost=close_cost,
                    new_credit=new_credit,
                    roll_net=roll_net,
                    stock_price_at_roll=current_price,
                    support_level_used=support_used,
                    loss_at_roll_pct=roll_pnl_pct,
                    cumulative_credit=total_credits + new_credit,
                    cumulative_cost=total_costs + close_cost,
                    vix_at_roll=current_vix,
                )

                roll_events.append(roll_event)
                roll_count += 1

                total_credits += new_credit
                total_costs += close_cost
                current_short = new_short
                current_long = new_long
                current_expiry_day = new_expiry_day

                if support_used:
                    support_levels_used.append(support_used)

    # End of simulation
    exit_idx = min(entry_idx + day, len(bars) - 1)
    exit_bar = bars[exit_idx]
    exit_price = exit_bar.close
    exit_date = exit_bar.date

    dte_remaining = max(0, current_expiry_day - exit_idx)
    if dte_remaining > 0:
        T_remaining = dte_remaining / 365.0
        short_val = black_scholes_put(exit_price, current_short, T_remaining, RISK_FREE_RATE, iv)
        long_val = black_scholes_put(exit_price, current_long, T_remaining, RISK_FREE_RATE, iv)
        final_spread = short_val - long_val
    else:
        final_spread = max(current_short - exit_price, 0) - max(current_long - exit_price, 0)

    final_pnl = total_credits - total_costs - (final_spread * 100)

    if final_pnl > 0:
        outcome = TradeOutcome.ROLLED_WIN if roll_count > 0 else TradeOutcome.WIN
    else:
        outcome = TradeOutcome.ROLLED_LOSS if roll_count > 0 else TradeOutcome.LOSS

    return DiagonalTradeResult(
        symbol=symbol,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_price=entry_price,
        exit_price=exit_price,
        initial_short_strike=short_strike,
        initial_long_strike=long_strike,
        initial_dte=INITIAL_DTE,
        initial_credit=initial_credit * 100,
        final_short_strike=current_short,
        final_long_strike=current_long,
        final_dte_remaining=dte_remaining,
        total_credits_received=total_credits,
        total_costs_paid=total_costs,
        final_pnl=final_pnl,
        outcome=outcome,
        roll_count=roll_count,
        roll_events=roll_events,
        max_drawdown_pct=max_drawdown_pct,
        holding_days=day,
        iv_at_entry=iv,
        vix_at_entry=vix_at_entry,
        lowest_price_seen=lowest_price,
        support_levels_used=support_levels_used,
    )


# =============================================================================
# Database for Results
# =============================================================================

class ResultsDatabase:
    """SQLite database for backtest results"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or RESULTS_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_name TEXT NOT NULL,
                    run_date TEXT NOT NULL,
                    total_symbols INTEGER,
                    total_trades INTEGER,
                    win_rate REAL,
                    total_pnl REAL,
                    config_json TEXT,
                    hostname TEXT,
                    created_at TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    entry_date TEXT,
                    exit_date TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    initial_short_strike REAL,
                    initial_long_strike REAL,
                    initial_dte INTEGER,
                    initial_credit REAL,
                    final_short_strike REAL,
                    final_long_strike REAL,
                    total_credits REAL,
                    total_costs REAL,
                    final_pnl REAL,
                    outcome TEXT,
                    roll_count INTEGER,
                    max_drawdown_pct REAL,
                    holding_days INTEGER,
                    iv_at_entry REAL,
                    vix_at_entry REAL,
                    lowest_price REAL,
                    created_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES backtest_runs(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS roll_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER NOT NULL,
                    roll_day INTEGER,
                    roll_type TEXT,
                    old_short_strike REAL,
                    new_short_strike REAL,
                    roll_net REAL,
                    stock_price REAL,
                    loss_at_roll_pct REAL,
                    vix_at_roll REAL,
                    created_at TEXT,
                    FOREIGN KEY (trade_id) REFERENCES trades(id)
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_run ON trades(run_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")

    def create_run(self, run_name: str, total_symbols: int, config: Dict) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            hostname = socket.gethostname()

            cursor.execute("""
                INSERT INTO backtest_runs (
                    run_name, run_date, total_symbols, total_trades,
                    win_rate, total_pnl, config_json, hostname, created_at
                ) VALUES (?, ?, ?, 0, 0, 0, ?, ?, ?)
            """, (run_name, now[:10], total_symbols, json.dumps(config), hostname, now))

            return cursor.lastrowid

    def add_trade(self, run_id: int, trade: DiagonalTradeResult) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO trades (
                    run_id, symbol, entry_date, exit_date,
                    entry_price, exit_price,
                    initial_short_strike, initial_long_strike,
                    initial_dte, initial_credit,
                    final_short_strike, final_long_strike,
                    total_credits, total_costs, final_pnl, outcome,
                    roll_count, max_drawdown_pct, holding_days,
                    iv_at_entry, vix_at_entry, lowest_price, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, trade.symbol,
                trade.entry_date.isoformat(), trade.exit_date.isoformat(),
                trade.entry_price, trade.exit_price,
                trade.initial_short_strike, trade.initial_long_strike,
                trade.initial_dte, trade.initial_credit,
                trade.final_short_strike, trade.final_long_strike,
                trade.total_credits_received, trade.total_costs_paid,
                trade.final_pnl, trade.outcome.value,
                trade.roll_count, trade.max_drawdown_pct, trade.holding_days,
                trade.iv_at_entry, trade.vix_at_entry, trade.lowest_price_seen, now
            ))

            trade_id = cursor.lastrowid

            for roll in trade.roll_events:
                cursor.execute("""
                    INSERT INTO roll_events (
                        trade_id, roll_day, roll_type,
                        old_short_strike, new_short_strike,
                        roll_net, stock_price, loss_at_roll_pct,
                        vix_at_roll, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_id, roll.roll_day, roll.roll_type.value,
                    roll.old_short_strike, roll.new_short_strike,
                    roll.roll_net, roll.stock_price_at_roll,
                    roll.loss_at_roll_pct, roll.vix_at_roll, now
                ))

            return trade_id

    def update_run_stats(self, run_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome IN ('win', 'rolled_win') THEN 1 ELSE 0 END) as wins,
                    SUM(final_pnl) as total_pnl
                FROM trades WHERE run_id = ?
            """, (run_id,))

            row = cursor.fetchone()
            total = row['total'] or 0
            wins = row['wins'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0

            cursor.execute("""
                UPDATE backtest_runs SET
                    total_trades = ?, win_rate = ?, total_pnl = ?
                WHERE id = ?
            """, (total, win_rate, row['total_pnl'] or 0, run_id))

    def get_summary(self, run_id: int) -> Dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,))
            run = cursor.fetchone()

            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome IN ('win', 'rolled_win') THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome IN ('loss', 'rolled_loss') THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN outcome = 'max_loss' THEN 1 ELSE 0 END) as max_losses,
                    AVG(final_pnl) as avg_pnl,
                    SUM(final_pnl) as total_pnl,
                    AVG(holding_days) as avg_holding,
                    AVG(roll_count) as avg_rolls,
                    SUM(roll_count) as total_rolls,
                    AVG(max_drawdown_pct) as avg_drawdown
                FROM trades WHERE run_id = ?
            """, (run_id,))
            stats = cursor.fetchone()

            # Rolled vs non-rolled
            cursor.execute("""
                SELECT
                    CASE WHEN roll_count > 0 THEN 'rolled' ELSE 'not_rolled' END as cat,
                    COUNT(*) as trades,
                    SUM(CASE WHEN outcome IN ('win', 'rolled_win') THEN 1 ELSE 0 END) as wins,
                    AVG(final_pnl) as avg_pnl,
                    SUM(final_pnl) as total_pnl
                FROM trades WHERE run_id = ?
                GROUP BY cat
            """, (run_id,))

            by_roll = {}
            for row in cursor.fetchall():
                by_roll[row['cat']] = {
                    'trades': row['trades'],
                    'wins': row['wins'],
                    'win_rate': (row['wins'] / row['trades'] * 100) if row['trades'] > 0 else 0,
                    'avg_pnl': row['avg_pnl'],
                    'total_pnl': row['total_pnl'],
                }

            return {
                'run': dict(run) if run else None,
                'total_trades': stats['total'] or 0,
                'wins': stats['wins'] or 0,
                'losses': stats['losses'] or 0,
                'max_losses': stats['max_losses'] or 0,
                'win_rate': (stats['wins'] / stats['total'] * 100) if stats['total'] else 0,
                'avg_pnl': stats['avg_pnl'] or 0,
                'total_pnl': stats['total_pnl'] or 0,
                'avg_holding_days': stats['avg_holding'] or 0,
                'avg_rolls': stats['avg_rolls'] or 0,
                'total_rolls': stats['total_rolls'] or 0,
                'avg_drawdown': stats['avg_drawdown'] or 0,
                'by_roll_status': by_roll,
            }


# =============================================================================
# Backtest Runner
# =============================================================================

def backtest_symbol_worker(args) -> List[DiagonalTradeResult]:
    """Worker function for backtesting a single symbol"""
    symbol, bars, vix_data, entry_interval = args

    results = []
    idx = INITIAL_DTE + 60

    while idx < len(bars) - INITIAL_DTE - 60:
        result = simulate_diagonal_roll_trade(
            bars=bars,
            entry_idx=idx,
            symbol=symbol,
            vix_data=vix_data,
        )

        if result:
            results.append(result)
            idx += max(result.holding_days, entry_interval)
        else:
            idx += entry_interval

    return results


def run_full_backtest(
    symbols: Optional[List[str]] = None,
    min_bars: int = 252,
    entry_interval: int = 30,
    workers: int = 4,
    run_name: Optional[str] = None,
    worker_id: int = 0,
    total_workers: int = 1,
) -> int:
    """Run full backtest using database data"""

    logger.info(f"Loading price data from database...")
    price_data = load_price_data_from_db(symbols, min_bars)

    logger.info(f"Loading VIX data...")
    vix_data = load_vix_data_from_db()

    all_symbols = sorted(price_data.keys())

    # Distribute symbols across workers (for Thunderbolt setup)
    if total_workers > 1:
        my_symbols = [s for i, s in enumerate(all_symbols) if i % total_workers == worker_id]
        logger.info(f"Worker {worker_id}/{total_workers}: Processing {len(my_symbols)} of {len(all_symbols)} symbols")
    else:
        my_symbols = all_symbols

    db = ResultsDatabase()

    config = {
        'short_delta': SHORT_DELTA_TARGET,
        'long_delta': LONG_DELTA_TARGET,
        'initial_dte': INITIAL_DTE,
        'roll_trigger_pct': ROLL_TRIGGER_PCT,
        'roll_dte_extension': ROLL_DTE_EXTENSION,
        'max_rolls': MAX_ROLLS_PER_TRADE,
        'entry_interval': entry_interval,
        'min_bars': min_bars,
        'worker_id': worker_id,
        'total_workers': total_workers,
    }

    run_name = run_name or f"diagonal_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if total_workers > 1:
        run_name = f"{run_name}_worker{worker_id}"

    run_id = db.create_run(run_name, len(my_symbols), config)

    logger.info(f"Created backtest run {run_id}: {run_name}")
    logger.info(f"Processing {len(my_symbols)} symbols with {workers} local workers")

    # Prepare work items
    work_items = [
        (symbol, price_data[symbol].bars, vix_data, entry_interval)
        for symbol in my_symbols
    ]

    all_results = []

    with mp.Pool(workers) as pool:
        for results in tqdm(
            pool.imap_unordered(backtest_symbol_worker, work_items),
            total=len(work_items),
            desc=f"Backtesting (Worker {worker_id})"
        ):
            for result in results:
                db.add_trade(run_id, result)
                all_results.append(result)

    db.update_run_stats(run_id)

    logger.info(f"Completed run {run_id} with {len(all_results)} trades")

    return run_id


def print_results(run_id: int):
    """Print backtest results"""
    db = ResultsDatabase()
    summary = db.get_summary(run_id)

    print("\n" + "=" * 70)
    print("DIAGONAL ROLL STRATEGY - FULL DATABASE BACKTEST")
    print("=" * 70)

    if summary.get('run'):
        print(f"\nRun ID: {run_id}")
        print(f"Name: {summary['run'].get('run_name', 'N/A')}")
        print(f"Host: {summary['run'].get('hostname', 'N/A')}")
        print(f"Symbols: {summary['run'].get('total_symbols', 0)}")

    print(f"\n{'='*30} OVERALL {'='*30}")
    print(f"Total Trades: {summary['total_trades']:,}")
    print(f"Wins: {summary['wins']:,}")
    print(f"Losses: {summary['losses']:,}")
    print(f"Max Losses: {summary['max_losses']:,}")
    print(f"Win Rate: {summary['win_rate']:.1f}%")
    print(f"Avg P&L: ${summary['avg_pnl']:.2f}")
    print(f"Total P&L: ${summary['total_pnl']:,.2f}")
    print(f"Avg Holding: {summary['avg_holding_days']:.1f} days")
    print(f"Total Rolls: {summary['total_rolls']:,}")
    print(f"Avg Rolls/Trade: {summary['avg_rolls']:.2f}")
    print(f"Avg Drawdown: {summary['avg_drawdown']:.1f}%")

    if summary.get('by_roll_status'):
        print(f"\n{'='*30} BY ROLL STATUS {'='*30}")
        for cat, data in summary['by_roll_status'].items():
            print(f"\n  {cat.upper()}:")
            print(f"    Trades: {data['trades']:,}")
            print(f"    Win Rate: {data['win_rate']:.1f}%")
            print(f"    Avg P&L: ${data['avg_pnl']:.2f}")
            print(f"    Total P&L: ${data['total_pnl']:,.2f}")

    print("\n" + "=" * 70)


def get_watchlist_symbols(watchlist_name: str) -> List[str]:
    """Load symbols from watchlist"""
    import yaml
    watchlist_path = PROJECT_ROOT / "config" / "watchlists.yaml"

    if not watchlist_path.exists():
        return []

    with open(watchlist_path) as f:
        config = yaml.safe_load(f)

    watchlists = config.get('watchlists', {})

    if watchlist_name in watchlists:
        wl = watchlists[watchlist_name]
        if isinstance(wl, dict):
            if 'symbols' in wl:
                return wl['symbols']
            elif 'sectors' in wl:
                symbols = []
                for sector_data in wl['sectors'].values():
                    if isinstance(sector_data, dict) and 'symbols' in sector_data:
                        symbols.extend(sector_data['symbols'])
                return symbols
    return []


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Full Diagonal Roll Backtest from Database")

    parser.add_argument('--symbols', '-s', type=str, help='Comma-separated symbols')
    parser.add_argument('--watchlist', '-w', type=str, help='Watchlist name')
    parser.add_argument('--all', '-a', action='store_true', help='Use all symbols in database')

    parser.add_argument('--min-bars', type=int, default=500, help='Minimum bars required (default: 500 = ~2 years)')
    parser.add_argument('--min-years', type=float, help='Minimum years of data')
    parser.add_argument('--entry-interval', type=int, default=30, help='Days between entries')
    parser.add_argument('--workers', type=int, default=4, help='Local workers')
    parser.add_argument('--name', type=str, help='Run name')

    # Distributed processing
    parser.add_argument('--distributed', action='store_true', help='Enable distributed mode')
    parser.add_argument('--worker-id', type=int, default=0, help='Worker ID (0-indexed)')
    parser.add_argument('--total-workers', type=int, default=1, help='Total workers')

    parser.add_argument('--results', type=int, help='Show results for run ID')

    args = parser.parse_args()

    if args.results:
        print_results(args.results)
        return

    # Determine minimum bars
    min_bars = args.min_bars
    if args.min_years:
        min_bars = int(args.min_years * 252)

    # Get symbols
    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    elif args.watchlist:
        symbols = get_watchlist_symbols(args.watchlist)
    elif not args.all:
        print("Specify --symbols, --watchlist, or --all")
        sys.exit(1)

    # Distributed settings
    worker_id = args.worker_id if args.distributed else 0
    total_workers = args.total_workers if args.distributed else 1

    print(f"\nDiagonal Roll Full Backtest")
    print(f"{'='*50}")
    print(f"Data source: {TRADES_DB_PATH}")
    print(f"Min bars: {min_bars} (~{min_bars/252:.1f} years)")
    print(f"Local workers: {args.workers}")
    if args.distributed:
        print(f"Distributed: Worker {worker_id + 1} of {total_workers}")
    print(f"{'='*50}\n")

    run_id = run_full_backtest(
        symbols=symbols,
        min_bars=min_bars,
        entry_interval=args.entry_interval,
        workers=args.workers,
        run_name=args.name,
        worker_id=worker_id,
        total_workers=total_workers,
    )

    print_results(run_id)

    print(f"\nResults saved to: {RESULTS_DB_PATH}")
    print(f"View: python {__file__} --results {run_id}")


if __name__ == '__main__':
    main()
