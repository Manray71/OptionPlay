#!/usr/bin/env python3
"""
OptionPlay - Comprehensive Backtest with Roll Maneuvers
========================================================
Umfangreicher Backtest mit Roll-Tracking in SQLite-Datenbank.

Features:
- Delta-basierte Strike-Auswahl (Short: -0.20, Long: -0.05)
- Roll-Manöver: Roll Down, Roll Out, Roll Down and Out
- Vollständiges Tracking in SQLite für Analyse
- Parallele Verarbeitung für Geschwindigkeit

Usage:
    python scripts/backtest_with_rolls.py --symbols AAPL,MSFT,GOOGL
    python scripts/backtest_with_rolls.py --watchlist core_growth
    python scripts/backtest_with_rolls.py --all --workers 8
"""

import argparse
import json
import logging
import math
import multiprocessing as mp
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Iterator
import traceback

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import yfinance as yf
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# Delta targets from strategies.yaml
SHORT_DELTA_TARGET = -0.20  # Short Put Delta
LONG_DELTA_TARGET = -0.05   # Long Put Delta (protective)
HOLDING_DAYS = 75           # Target DTE
RISK_FREE_RATE = 0.05       # 5% annualized

# Roll thresholds
ROLL_LOSS_THRESHOLD = 0.25  # Roll when loss > 25% of max profit
ROLL_PRICE_PROXIMITY = 1.03  # Roll when price within 3% of short strike
ROLL_MIN_DTE = 30           # Roll Out when DTE < 30 days
MAX_ROLLS_PER_TRADE = 2     # Maximum rolls allowed

# Database path
DB_PATH = Path.home() / ".optionplay" / "backtest_rolls.db"


# =============================================================================
# Enums
# =============================================================================

class RollType(Enum):
    """Type of roll maneuver"""
    NONE = "none"
    ROLL_DOWN = "roll_down"
    ROLL_OUT = "roll_out"
    ROLL_DOWN_AND_OUT = "roll_down_and_out"


class TradeOutcome(Enum):
    """Trade outcome"""
    WIN = "win"
    LOSS = "loss"
    MAX_LOSS = "max_loss"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class RollEvent:
    """A single roll event"""
    roll_day: int  # Day of trade when roll occurred
    roll_type: RollType
    old_short_strike: float
    new_short_strike: float
    old_long_strike: float
    new_long_strike: float
    roll_cost: float  # Positive = debit, Negative = credit
    stock_price_at_roll: float
    dte_at_roll: int


@dataclass
class TradeResult:
    """Complete result of a simulated trade"""
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float  # Stock price at entry
    exit_price: float   # Stock price at exit

    # Strike info
    initial_short_strike: float
    initial_long_strike: float
    final_short_strike: float
    final_long_strike: float

    # P&L
    initial_credit: float  # Credit received at entry
    final_pnl: float       # Total P&L including rolls
    outcome: TradeOutcome

    # Roll info
    roll_count: int = 0
    roll_events: List[RollEvent] = field(default_factory=list)
    total_roll_cost: float = 0.0

    # Additional metrics
    max_drawdown: float = 0.0
    holding_days: int = 0
    iv_at_entry: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'entry_date': self.entry_date.isoformat(),
            'exit_date': self.exit_date.isoformat(),
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'initial_short_strike': self.initial_short_strike,
            'initial_long_strike': self.initial_long_strike,
            'final_short_strike': self.final_short_strike,
            'final_long_strike': self.final_long_strike,
            'initial_credit': self.initial_credit,
            'final_pnl': self.final_pnl,
            'outcome': self.outcome.value,
            'roll_count': self.roll_count,
            'roll_events': [
                {
                    'roll_day': r.roll_day,
                    'roll_type': r.roll_type.value,
                    'old_short_strike': r.old_short_strike,
                    'new_short_strike': r.new_short_strike,
                    'old_long_strike': r.old_long_strike,
                    'new_long_strike': r.new_long_strike,
                    'roll_cost': r.roll_cost,
                    'stock_price_at_roll': r.stock_price_at_roll,
                    'dte_at_roll': r.dte_at_roll,
                }
                for r in self.roll_events
            ],
            'total_roll_cost': self.total_roll_cost,
            'max_drawdown': self.max_drawdown,
            'holding_days': self.holding_days,
            'iv_at_entry': self.iv_at_entry,
        }


# =============================================================================
# Black-Scholes Functions (Standalone - no scipy dependency)
# =============================================================================

def norm_cdf(x: float) -> float:
    """Standard normal CDF using error function"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Standard normal PDF"""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Black-Scholes Put price.

    Args:
        S: Stock price
        K: Strike price
        T: Time to expiry in years
        r: Risk-free rate (annualized)
        sigma: Implied volatility (annualized)

    Returns:
        Put option price
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        # Intrinsic value for edge cases
        return max(K - S, 0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    put_price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    return max(put_price, 0)


def black_scholes_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Black-Scholes Put Delta.

    Returns:
        Delta (negative for puts, between -1 and 0)
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return -1.0 if K > S else 0.0

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) - 1.0  # Put delta


def find_strike_for_delta(
    S: float,
    T: float,
    r: float,
    sigma: float,
    target_delta: float,
    strike_step: float = 1.0,
) -> float:
    """
    Find strike price that gives target delta using bisection.

    Args:
        S: Stock price
        T: Time to expiry in years
        r: Risk-free rate
        sigma: Implied volatility
        target_delta: Target delta (negative for puts)
        strike_step: Strike grid step for rounding

    Returns:
        Strike price rounded to nearest strike_step
    """
    # Bisection search
    low = S * 0.50   # Deep ITM
    high = S * 1.20  # OTM

    for _ in range(50):  # Max iterations
        mid = (low + high) / 2
        delta = black_scholes_delta(S, mid, T, r, sigma)

        if abs(delta - target_delta) < 0.001:
            break

        # For puts: lower strike = more negative delta
        if delta < target_delta:
            low = mid
        else:
            high = mid

    # Round to nearest strike step
    rounded = round(mid / strike_step) * strike_step
    return rounded


def estimate_iv_from_history(prices: np.ndarray, days: int = 30) -> float:
    """
    Estimate implied volatility from historical price data.
    Uses 30-day rolling standard deviation, annualized.
    """
    if len(prices) < days + 1:
        return 0.30  # Default 30% IV

    returns = np.diff(np.log(prices[-days-1:]))
    daily_vol = np.std(returns)
    annual_vol = daily_vol * math.sqrt(252)

    # Apply IV premium (options typically trade above HV)
    iv_premium = 1.20
    return min(max(annual_vol * iv_premium, 0.15), 1.50)


# =============================================================================
# Trade Simulation
# =============================================================================

def simulate_trade(
    prices: np.ndarray,
    entry_idx: int,
    symbol: str,
    entry_date: date,
    enable_rolls: bool = True,
) -> Optional[TradeResult]:
    """
    Simulate a Bull-Put-Spread trade with optional roll maneuvers.

    Args:
        prices: Full price array for the symbol
        entry_idx: Index in prices array for trade entry
        symbol: Stock symbol
        entry_date: Entry date
        enable_rolls: Whether to enable roll maneuvers

    Returns:
        TradeResult or None if trade cannot be executed
    """
    # Minimum data needed
    holding_days = HOLDING_DAYS
    if entry_idx + holding_days >= len(prices):
        return None

    entry_price = prices[entry_idx]

    # Estimate IV from recent history
    lookback = min(60, entry_idx)
    recent_prices = prices[entry_idx - lookback:entry_idx + 1]
    iv = estimate_iv_from_history(recent_prices)

    # Time to expiry in years
    T = holding_days / 365.0

    # Determine strike step based on price
    if entry_price < 50:
        strike_step = 1.0
    elif entry_price < 200:
        strike_step = 2.5
    else:
        strike_step = 5.0

    # Find strikes for target deltas
    short_strike = find_strike_for_delta(
        entry_price, T, RISK_FREE_RATE, iv, SHORT_DELTA_TARGET, strike_step
    )
    long_strike = find_strike_for_delta(
        entry_price, T, RISK_FREE_RATE, iv, LONG_DELTA_TARGET, strike_step
    )

    # Ensure proper spread
    if long_strike >= short_strike:
        long_strike = short_strike - strike_step

    # Calculate initial credit
    short_put_price = black_scholes_put(entry_price, short_strike, T, RISK_FREE_RATE, iv)
    long_put_price = black_scholes_put(entry_price, long_strike, T, RISK_FREE_RATE, iv)
    net_credit = short_put_price - long_put_price

    if net_credit <= 0:
        return None  # No credit, skip trade

    # Track state
    current_short = short_strike
    current_long = long_strike
    roll_count = 0
    roll_events = []
    total_roll_cost = 0.0
    max_drawdown = 0.0

    # Simulate daily price movement
    for day in range(1, holding_days + 1):
        if entry_idx + day >= len(prices):
            break

        current_price = prices[entry_idx + day]
        remaining_dte = holding_days - day
        T_remaining = remaining_dte / 365.0

        # Current spread value (cost to close)
        short_val = black_scholes_put(current_price, current_short, T_remaining, RISK_FREE_RATE, iv)
        long_val = black_scholes_put(current_price, current_long, T_remaining, RISK_FREE_RATE, iv)
        spread_value = short_val - long_val

        # Current P&L (credit received - cost to close)
        current_pnl = (net_credit - spread_value) * 100  # Per contract

        # Track max drawdown
        if current_pnl < 0:
            max_drawdown = min(max_drawdown, current_pnl)

        # Check for roll conditions (if rolls enabled)
        if enable_rolls and roll_count < MAX_ROLLS_PER_TRADE:
            # Calculate max loss for this spread
            spread_width = current_short - current_long
            max_loss = (spread_width - net_credit) * 100

            # Position loss percentage
            position_loss_pct = abs(current_pnl) / max_loss if max_loss > 0 else 0

            # Conditions for rolling
            price_near_short = current_price <= current_short * ROLL_PRICE_PROXIMITY
            under_pressure = position_loss_pct > ROLL_LOSS_THRESHOLD
            low_dte = remaining_dte < ROLL_MIN_DTE

            roll_type = RollType.NONE

            if price_near_short and under_pressure and low_dte:
                roll_type = RollType.ROLL_DOWN_AND_OUT
            elif low_dte and under_pressure:
                roll_type = RollType.ROLL_OUT
            elif price_near_short and under_pressure:
                roll_type = RollType.ROLL_DOWN

            if roll_type != RollType.NONE:
                # Calculate new strikes
                new_T = T_remaining + (30 / 365.0) if roll_type in [RollType.ROLL_OUT, RollType.ROLL_DOWN_AND_OUT] else T_remaining

                if roll_type in [RollType.ROLL_DOWN, RollType.ROLL_DOWN_AND_OUT]:
                    new_short = find_strike_for_delta(
                        current_price, new_T, RISK_FREE_RATE, iv, SHORT_DELTA_TARGET, strike_step
                    )
                    new_long = find_strike_for_delta(
                        current_price, new_T, RISK_FREE_RATE, iv, LONG_DELTA_TARGET, strike_step
                    )
                else:
                    new_short = current_short
                    new_long = current_long

                # Ensure valid spread
                if new_long >= new_short:
                    new_long = new_short - strike_step

                # Calculate roll cost
                close_short = black_scholes_put(current_price, current_short, T_remaining, RISK_FREE_RATE, iv)
                close_long = black_scholes_put(current_price, current_long, T_remaining, RISK_FREE_RATE, iv)
                close_cost = close_short - close_long  # Cost to close current

                new_short_premium = black_scholes_put(current_price, new_short, new_T, RISK_FREE_RATE, iv)
                new_long_premium = black_scholes_put(current_price, new_long, new_T, RISK_FREE_RATE, iv)
                open_credit = new_short_premium - new_long_premium

                roll_net_cost = close_cost - open_credit  # Positive = debit

                # Only roll if beneficial
                new_strike_gives_room = new_short < current_short * 0.98
                can_roll_for_credit = roll_net_cost <= 0
                small_debit_acceptable = roll_net_cost > 0 and roll_net_cost < (net_credit * 0.10)
                roll_is_worthwhile = (can_roll_for_credit or small_debit_acceptable) and new_strike_gives_room

                if roll_is_worthwhile:
                    # Execute roll
                    roll_event = RollEvent(
                        roll_day=day,
                        roll_type=roll_type,
                        old_short_strike=current_short,
                        new_short_strike=new_short,
                        old_long_strike=current_long,
                        new_long_strike=new_long,
                        roll_cost=roll_net_cost * 100,  # Per contract
                        stock_price_at_roll=current_price,
                        dte_at_roll=remaining_dte,
                    )

                    roll_events.append(roll_event)
                    roll_count += 1
                    total_roll_cost += roll_net_cost * 100

                    # Update state
                    current_short = new_short
                    current_long = new_long
                    net_credit = open_credit

                    # Extend holding if rolled out
                    if roll_type in [RollType.ROLL_OUT, RollType.ROLL_DOWN_AND_OUT]:
                        holding_days = day + 30

    # Final exit
    exit_idx = min(entry_idx + holding_days, len(prices) - 1)
    exit_price = prices[exit_idx]
    exit_date = entry_date + timedelta(days=holding_days)

    # Final spread value at expiry (intrinsic)
    short_intrinsic = max(current_short - exit_price, 0)
    long_intrinsic = max(current_long - exit_price, 0)
    final_spread_value = short_intrinsic - long_intrinsic

    # Final P&L
    final_pnl = (net_credit - final_spread_value) * 100 - total_roll_cost

    # Determine outcome
    if final_pnl > 0:
        outcome = TradeOutcome.WIN
    elif exit_price <= current_long:
        outcome = TradeOutcome.MAX_LOSS
    else:
        outcome = TradeOutcome.LOSS

    return TradeResult(
        symbol=symbol,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_price=entry_price,
        exit_price=exit_price,
        initial_short_strike=short_strike,
        initial_long_strike=long_strike,
        final_short_strike=current_short,
        final_long_strike=current_long,
        initial_credit=net_credit * 100,
        final_pnl=final_pnl,
        outcome=outcome,
        roll_count=roll_count,
        roll_events=roll_events,
        total_roll_cost=total_roll_cost,
        max_drawdown=max_drawdown,
        holding_days=holding_days,
        iv_at_entry=iv,
    )


# =============================================================================
# Database Management
# =============================================================================

class BacktestDatabase:
    """SQLite database for backtest results with roll tracking"""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
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
        """Initialize database schema"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Backtest runs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_name TEXT NOT NULL,
                    run_date TEXT NOT NULL,
                    total_symbols INTEGER,
                    total_trades INTEGER,
                    win_rate REAL,
                    total_pnl REAL,
                    rolls_enabled INTEGER,
                    config_json TEXT,
                    created_at TEXT
                )
            """)

            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    exit_date TEXT NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    initial_short_strike REAL,
                    initial_long_strike REAL,
                    final_short_strike REAL,
                    final_long_strike REAL,
                    initial_credit REAL,
                    final_pnl REAL,
                    outcome TEXT,
                    roll_count INTEGER DEFAULT 0,
                    total_roll_cost REAL DEFAULT 0,
                    max_drawdown REAL,
                    holding_days INTEGER,
                    iv_at_entry REAL,
                    created_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES backtest_runs(id)
                )
            """)

            # Roll events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS roll_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER NOT NULL,
                    roll_day INTEGER,
                    roll_type TEXT,
                    old_short_strike REAL,
                    new_short_strike REAL,
                    old_long_strike REAL,
                    new_long_strike REAL,
                    roll_cost REAL,
                    stock_price_at_roll REAL,
                    dte_at_roll INTEGER,
                    created_at TEXT,
                    FOREIGN KEY (trade_id) REFERENCES trades(id)
                )
            """)

            # Create indices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_run ON trades(run_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_roll_count ON trades(roll_count)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rolls_trade ON roll_events(trade_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rolls_type ON roll_events(roll_type)")

            # Meta table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(self.SCHEMA_VERSION),)
            )

    def create_run(
        self,
        run_name: str,
        total_symbols: int,
        rolls_enabled: bool,
        config: Dict[str, Any],
    ) -> int:
        """Create a new backtest run"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO backtest_runs (
                    run_name, run_date, total_symbols, total_trades,
                    win_rate, total_pnl, rolls_enabled, config_json, created_at
                ) VALUES (?, ?, ?, 0, 0, 0, ?, ?, ?)
            """, (
                run_name,
                now[:10],
                total_symbols,
                1 if rolls_enabled else 0,
                json.dumps(config),
                now,
            ))

            return cursor.lastrowid

    def add_trade(self, run_id: int, trade: TradeResult) -> int:
        """Add a trade result to the database"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO trades (
                    run_id, symbol, entry_date, exit_date,
                    entry_price, exit_price,
                    initial_short_strike, initial_long_strike,
                    final_short_strike, final_long_strike,
                    initial_credit, final_pnl, outcome,
                    roll_count, total_roll_cost,
                    max_drawdown, holding_days, iv_at_entry,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                trade.symbol,
                trade.entry_date.isoformat(),
                trade.exit_date.isoformat(),
                trade.entry_price,
                trade.exit_price,
                trade.initial_short_strike,
                trade.initial_long_strike,
                trade.final_short_strike,
                trade.final_long_strike,
                trade.initial_credit,
                trade.final_pnl,
                trade.outcome.value,
                trade.roll_count,
                trade.total_roll_cost,
                trade.max_drawdown,
                trade.holding_days,
                trade.iv_at_entry,
                now,
            ))

            trade_id = cursor.lastrowid

            # Add roll events
            for roll in trade.roll_events:
                cursor.execute("""
                    INSERT INTO roll_events (
                        trade_id, roll_day, roll_type,
                        old_short_strike, new_short_strike,
                        old_long_strike, new_long_strike,
                        roll_cost, stock_price_at_roll, dte_at_roll,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_id,
                    roll.roll_day,
                    roll.roll_type.value,
                    roll.old_short_strike,
                    roll.new_short_strike,
                    roll.old_long_strike,
                    roll.new_long_strike,
                    roll.roll_cost,
                    roll.stock_price_at_roll,
                    roll.dte_at_roll,
                    now,
                ))

            return trade_id

    def update_run_stats(self, run_id: int):
        """Update run statistics after all trades are added"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                    SUM(final_pnl) as total_pnl
                FROM trades WHERE run_id = ?
            """, (run_id,))

            row = cursor.fetchone()
            total_trades = row['total_trades'] or 0
            wins = row['wins'] or 0
            total_pnl = row['total_pnl'] or 0
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            cursor.execute("""
                UPDATE backtest_runs SET
                    total_trades = ?,
                    win_rate = ?,
                    total_pnl = ?
                WHERE id = ?
            """, (total_trades, win_rate, total_pnl, run_id))

    def get_roll_statistics(self, run_id: Optional[int] = None) -> Dict[str, Any]:
        """Get comprehensive roll statistics"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Base query filter
            run_filter = "WHERE t.run_id = ?" if run_id else ""
            params = (run_id,) if run_id else ()

            # Total trades and rolled trades
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN roll_count > 0 THEN 1 ELSE 0 END) as rolled_trades,
                    SUM(roll_count) as total_rolls,
                    AVG(roll_count) as avg_rolls_per_trade,
                    SUM(total_roll_cost) as total_roll_cost
                FROM trades t {run_filter}
            """, params)
            row = cursor.fetchone()

            stats = {
                'total_trades': row['total_trades'] or 0,
                'rolled_trades': row['rolled_trades'] or 0,
                'total_rolls': row['total_rolls'] or 0,
                'avg_rolls_per_trade': row['avg_rolls_per_trade'] or 0,
                'total_roll_cost': row['total_roll_cost'] or 0,
            }

            # Win rate for rolled vs non-rolled
            cursor.execute(f"""
                SELECT
                    CASE WHEN roll_count > 0 THEN 'rolled' ELSE 'not_rolled' END as category,
                    COUNT(*) as trades,
                    SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                    AVG(final_pnl) as avg_pnl,
                    SUM(final_pnl) as total_pnl
                FROM trades t {run_filter}
                GROUP BY category
            """, params)

            stats['by_roll_status'] = {}
            for row in cursor.fetchall():
                cat = row['category']
                trades = row['trades']
                stats['by_roll_status'][cat] = {
                    'trades': trades,
                    'wins': row['wins'],
                    'win_rate': (row['wins'] / trades * 100) if trades > 0 else 0,
                    'avg_pnl': row['avg_pnl'] or 0,
                    'total_pnl': row['total_pnl'] or 0,
                }

            # Roll type distribution
            roll_filter = f"WHERE r.trade_id IN (SELECT id FROM trades t {run_filter})" if run_id else ""
            cursor.execute(f"""
                SELECT
                    r.roll_type,
                    COUNT(*) as count,
                    AVG(r.roll_cost) as avg_cost
                FROM roll_events r {roll_filter}
                GROUP BY r.roll_type
            """, params if run_id else ())

            stats['by_roll_type'] = {}
            for row in cursor.fetchall():
                stats['by_roll_type'][row['roll_type']] = {
                    'count': row['count'],
                    'avg_cost': row['avg_cost'] or 0,
                }

            # Outcome after roll (did roll save the trade?)
            cursor.execute(f"""
                SELECT
                    t.outcome,
                    COUNT(*) as count,
                    AVG(t.final_pnl) as avg_pnl
                FROM trades t
                {run_filter.replace('WHERE', 'WHERE t.roll_count > 0 AND') if run_filter else 'WHERE t.roll_count > 0'}
                GROUP BY t.outcome
            """, params)

            stats['rolled_outcomes'] = {}
            for row in cursor.fetchall():
                stats['rolled_outcomes'][row['outcome']] = {
                    'count': row['count'],
                    'avg_pnl': row['avg_pnl'] or 0,
                }

            return stats

    def get_summary(self, run_id: Optional[int] = None) -> Dict[str, Any]:
        """Get overall backtest summary"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if run_id:
                cursor.execute("""
                    SELECT * FROM backtest_runs WHERE id = ?
                """, (run_id,))
                run = cursor.fetchone()

                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
                        SUM(CASE WHEN outcome = 'max_loss' THEN 1 ELSE 0 END) as max_losses,
                        AVG(final_pnl) as avg_pnl,
                        SUM(final_pnl) as total_pnl,
                        AVG(holding_days) as avg_holding,
                        AVG(iv_at_entry) as avg_iv
                    FROM trades WHERE run_id = ?
                """, (run_id,))
            else:
                run = None
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
                        SUM(CASE WHEN outcome = 'max_loss' THEN 1 ELSE 0 END) as max_losses,
                        AVG(final_pnl) as avg_pnl,
                        SUM(final_pnl) as total_pnl,
                        AVG(holding_days) as avg_holding,
                        AVG(iv_at_entry) as avg_iv
                    FROM trades
                """)

            stats = cursor.fetchone()

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
                'avg_iv': stats['avg_iv'] or 0,
            }


# =============================================================================
# Data Fetching
# =============================================================================

def fetch_price_data(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """Fetch historical price data from Yahoo Finance"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date)

        if df.empty or len(df) < 100:
            return None

        return df
    except Exception as e:
        logger.warning(f"Failed to fetch data for {symbol}: {e}")
        return None


def get_watchlist_symbols(watchlist_name: str) -> List[str]:
    """Load symbols from watchlist config"""
    watchlist_path = PROJECT_ROOT / "config" / "watchlists.yaml"

    if not watchlist_path.exists():
        logger.warning(f"Watchlist file not found: {watchlist_path}")
        return []

    try:
        import yaml
        with open(watchlist_path) as f:
            config = yaml.safe_load(f)

        watchlists = config.get('watchlists', {})

        if watchlist_name in watchlists:
            return watchlists[watchlist_name].get('symbols', [])

        # Try to find partial match
        for name, data in watchlists.items():
            if watchlist_name.lower() in name.lower():
                return data.get('symbols', [])

        return []
    except Exception as e:
        logger.warning(f"Failed to load watchlist: {e}")
        return []


def get_all_symbols() -> List[str]:
    """Get all symbols from all watchlists"""
    watchlist_path = PROJECT_ROOT / "config" / "watchlists.yaml"

    if not watchlist_path.exists():
        return []

    try:
        import yaml
        with open(watchlist_path) as f:
            config = yaml.safe_load(f)

        all_symbols = set()

        # Handle both top-level watchlists and nested formats
        watchlists = config.get('watchlists', config)

        for wl_name, wl_data in watchlists.items():
            if not isinstance(wl_data, dict):
                continue

            # Direct symbols list
            if 'symbols' in wl_data:
                symbols = wl_data.get('symbols', [])
                if isinstance(symbols, list):
                    all_symbols.update(s for s in symbols if isinstance(s, str))

            # Nested sectors structure
            if 'sectors' in wl_data:
                sectors = wl_data.get('sectors', {})
                if isinstance(sectors, dict):
                    for sector_data in sectors.values():
                        if isinstance(sector_data, dict) and 'symbols' in sector_data:
                            symbols = sector_data.get('symbols', [])
                            if isinstance(symbols, list):
                                all_symbols.update(s for s in symbols if isinstance(s, str))

        # Filter out invalid symbols
        valid_symbols = [s for s in all_symbols if s and len(s) <= 6 and not s.startswith('#')]
        return sorted(valid_symbols)
    except Exception as e:
        logger.warning(f"Failed to load watchlists: {e}")
        import traceback
        traceback.print_exc()
        return []


# =============================================================================
# Backtest Runner
# =============================================================================

def backtest_symbol(
    symbol: str,
    start_date: str,
    end_date: str,
    enable_rolls: bool,
    entry_interval: int = 30,
) -> List[TradeResult]:
    """
    Run backtest for a single symbol.

    Args:
        symbol: Stock symbol
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        enable_rolls: Whether to enable roll maneuvers
        entry_interval: Days between trade entries

    Returns:
        List of TradeResults
    """
    # Fetch data
    df = fetch_price_data(symbol, start_date, end_date)
    if df is None:
        return []

    prices = df['Close'].values
    dates = df.index.date

    results = []

    # Enter trades at regular intervals
    idx = HOLDING_DAYS  # Need lookback for IV calculation
    while idx < len(prices) - HOLDING_DAYS - 30:
        entry_date = dates[idx]

        result = simulate_trade(
            prices=prices,
            entry_idx=idx,
            symbol=symbol,
            entry_date=entry_date,
            enable_rolls=enable_rolls,
        )

        if result:
            results.append(result)

        idx += entry_interval

    return results


def worker_process(args) -> List[TradeResult]:
    """Worker function for multiprocessing"""
    symbol, start_date, end_date, enable_rolls, entry_interval = args
    try:
        return backtest_symbol(symbol, start_date, end_date, enable_rolls, entry_interval)
    except Exception as e:
        logger.error(f"Error processing {symbol}: {e}")
        traceback.print_exc()
        return []


def run_backtest(
    symbols: List[str],
    start_date: str,
    end_date: str,
    enable_rolls: bool = True,
    entry_interval: int = 30,
    workers: int = 4,
    run_name: Optional[str] = None,
) -> int:
    """
    Run full backtest with database storage.

    Args:
        symbols: List of symbols to backtest
        start_date: Start date
        end_date: End date
        enable_rolls: Enable roll maneuvers
        entry_interval: Days between entries
        workers: Number of parallel workers
        run_name: Name for this backtest run

    Returns:
        Run ID in database
    """
    # Initialize database
    db = BacktestDatabase()

    # Create run record
    config = {
        'short_delta': SHORT_DELTA_TARGET,
        'long_delta': LONG_DELTA_TARGET,
        'holding_days': HOLDING_DAYS,
        'roll_loss_threshold': ROLL_LOSS_THRESHOLD,
        'roll_price_proximity': ROLL_PRICE_PROXIMITY,
        'roll_min_dte': ROLL_MIN_DTE,
        'max_rolls': MAX_ROLLS_PER_TRADE,
        'entry_interval': entry_interval,
        'start_date': start_date,
        'end_date': end_date,
    }

    run_name = run_name or f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_id = db.create_run(run_name, len(symbols), enable_rolls, config)

    logger.info(f"Created backtest run {run_id}: {run_name}")
    logger.info(f"Processing {len(symbols)} symbols with {workers} workers")
    logger.info(f"Rolls {'ENABLED' if enable_rolls else 'DISABLED'}")

    # Prepare work items
    work_items = [
        (symbol, start_date, end_date, enable_rolls, entry_interval)
        for symbol in symbols
    ]

    # Process with multiprocessing
    all_results = []

    with mp.Pool(workers) as pool:
        for results in tqdm(
            pool.imap_unordered(worker_process, work_items),
            total=len(work_items),
            desc="Backtesting"
        ):
            for result in results:
                db.add_trade(run_id, result)
                all_results.append(result)

    # Update run statistics
    db.update_run_stats(run_id)

    logger.info(f"Completed backtest run {run_id} with {len(all_results)} trades")

    return run_id


def print_results(run_id: int):
    """Print backtest results summary"""
    db = BacktestDatabase()

    summary = db.get_summary(run_id)
    roll_stats = db.get_roll_statistics(run_id)

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    print(f"\nRun ID: {run_id}")
    if summary.get('run'):
        print(f"Name: {summary['run'].get('run_name', 'N/A')}")
        print(f"Rolls Enabled: {'Yes' if summary['run'].get('rolls_enabled') else 'No'}")

    print(f"\nTotal Trades: {summary['total_trades']:,}")
    print(f"Wins: {summary['wins']:,}")
    print(f"Losses: {summary['losses']:,}")
    print(f"Max Losses: {summary['max_losses']:,}")
    print(f"Win Rate: {summary['win_rate']:.1f}%")
    print(f"Avg P&L per Trade: ${summary['avg_pnl']:,.2f}")
    print(f"Total P&L: ${summary['total_pnl']:,.2f}")
    print(f"Avg Holding Days: {summary['avg_holding_days']:.1f}")
    print(f"Avg IV at Entry: {summary['avg_iv']*100:.1f}%")

    print("\n" + "-" * 60)
    print("ROLL STATISTICS")
    print("-" * 60)

    print(f"\nTotal Rolls: {roll_stats['total_rolls']:,}")
    print(f"Trades with Rolls: {roll_stats['rolled_trades']:,} ({roll_stats['rolled_trades']/max(roll_stats['total_trades'],1)*100:.1f}%)")
    print(f"Avg Rolls per Trade: {roll_stats['avg_rolls_per_trade']:.2f}")
    print(f"Total Roll Cost: ${roll_stats['total_roll_cost']:,.2f}")

    if roll_stats.get('by_roll_status'):
        print("\nPerformance by Roll Status:")
        for status, data in roll_stats['by_roll_status'].items():
            print(f"  {status.upper()}:")
            print(f"    Trades: {data['trades']:,}")
            print(f"    Win Rate: {data['win_rate']:.1f}%")
            print(f"    Avg P&L: ${data['avg_pnl']:,.2f}")
            print(f"    Total P&L: ${data['total_pnl']:,.2f}")

    if roll_stats.get('by_roll_type'):
        print("\nRoll Type Distribution:")
        for roll_type, data in roll_stats['by_roll_type'].items():
            print(f"  {roll_type}: {data['count']} rolls (avg cost: ${data['avg_cost']:.2f})")

    if roll_stats.get('rolled_outcomes'):
        print("\nOutcomes for Rolled Trades:")
        for outcome, data in roll_stats['rolled_outcomes'].items():
            print(f"  {outcome}: {data['count']} trades (avg P&L: ${data['avg_pnl']:.2f})")

    print("\n" + "=" * 60)


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="OptionPlay Backtest with Roll Maneuvers"
    )

    # Symbol selection
    parser.add_argument(
        '--symbols', '-s',
        type=str,
        help='Comma-separated list of symbols'
    )
    parser.add_argument(
        '--watchlist', '-w',
        type=str,
        help='Watchlist name from config'
    )
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='Use all symbols from all watchlists'
    )

    # Date range
    parser.add_argument(
        '--start',
        type=str,
        default='2020-01-01',
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end',
        type=str,
        default='2024-12-31',
        help='End date (YYYY-MM-DD)'
    )

    # Options
    parser.add_argument(
        '--no-rolls',
        action='store_true',
        help='Disable roll maneuvers'
    )
    parser.add_argument(
        '--entry-interval',
        type=int,
        default=30,
        help='Days between trade entries (default: 30)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=4,
        help='Number of parallel workers'
    )
    parser.add_argument(
        '--name',
        type=str,
        help='Name for this backtest run'
    )

    # Analysis
    parser.add_argument(
        '--results',
        type=int,
        help='Print results for existing run ID'
    )
    parser.add_argument(
        '--compare',
        nargs=2,
        type=int,
        metavar=('RUN1', 'RUN2'),
        help='Compare two backtest runs'
    )

    args = parser.parse_args()

    # Handle results viewing
    if args.results:
        print_results(args.results)
        return

    # Handle comparison
    if args.compare:
        db = BacktestDatabase()
        print("\n" + "=" * 70)
        print("BACKTEST COMPARISON")
        print("=" * 70)

        for run_id in args.compare:
            print(f"\n--- Run {run_id} ---")
            summary = db.get_summary(run_id)
            roll_stats = db.get_roll_statistics(run_id)

            print(f"Trades: {summary['total_trades']:,}")
            print(f"Win Rate: {summary['win_rate']:.1f}%")
            print(f"Total P&L: ${summary['total_pnl']:,.2f}")
            print(f"Avg P&L: ${summary['avg_pnl']:.2f}")
            print(f"Rolled Trades: {roll_stats['rolled_trades']:,}")

        return

    # Get symbols
    symbols = []
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',')]
    elif args.watchlist:
        symbols = get_watchlist_symbols(args.watchlist)
    elif args.all:
        symbols = get_all_symbols()

    if not symbols:
        print("No symbols specified. Use --symbols, --watchlist, or --all")
        sys.exit(1)

    print(f"Starting backtest with {len(symbols)} symbols")
    print(f"Date range: {args.start} to {args.end}")
    print(f"Rolls: {'DISABLED' if args.no_rolls else 'ENABLED'}")

    # Run backtest
    run_id = run_backtest(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        enable_rolls=not args.no_rolls,
        entry_interval=args.entry_interval,
        workers=args.workers,
        run_name=args.name,
    )

    # Print results
    print_results(run_id)

    print(f"\nResults saved to: {DB_PATH}")
    print(f"View results anytime: python {__file__} --results {run_id}")


if __name__ == '__main__':
    main()
