#!/usr/bin/env python3
"""
OptionPlay - Diagonale Roll-Strategie Backtest
===============================================

Implementiert die folgende Roll-Regel:
1. Trigger: Wenn Bull-Put-Spread auf -50% des initialen Credits fällt
2. Aktion: Diagonal rollen (2-3 Monate in die Zukunft)
3. Strike-Ziel: Unterhalb des nächsten Support-Levels
4. Credit-Ziel: Idealerweise Verlust mit neuem Credit ausgleichen
5. Wiederholung: Bei erneutem -50% wieder rollen bis Boden erreicht

Die Strategie nutzt Zeitwertabbau während die Aktie korrigiert.

Usage:
    python scripts/backtest_diagonal_roll.py --symbols AAPL,MSFT
    python scripts/backtest_diagonal_roll.py --watchlist core_growth
    python scripts/backtest_diagonal_roll.py --all --workers 8
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

# Delta targets
SHORT_DELTA_TARGET = -0.20  # Short Put Delta
LONG_DELTA_TARGET = -0.05   # Long Put Delta (protective)
INITIAL_DTE = 45            # Initial DTE
RISK_FREE_RATE = 0.05       # 5% annualized

# Diagonal Roll Parameters
ROLL_TRIGGER_PCT = -50.0    # Roll when at -50% of initial credit
ROLL_DTE_EXTENSION = 60     # Roll 2 months (60 days) into future
ROLL_DTE_EXTENSION_MAX = 90 # Maximum 3 months
MAX_ROLLS_PER_TRADE = 5     # Allow multiple rolls until recovery
MIN_ROLL_CREDIT_PCT = 0.50  # New credit should be at least 50% of loss
SUPPORT_BUFFER_PCT = 2.0    # Place new strike 2% below support

# Exit Parameters
PROFIT_TARGET_PCT = 50.0    # Close at 50% profit
MAX_HOLDING_DAYS = 365      # Maximum total holding (with rolls)

# Database path
DB_PATH = Path.home() / ".optionplay" / "backtest_diagonal_rolls.db"


# =============================================================================
# Enums
# =============================================================================

class RollType(Enum):
    """Type of roll maneuver"""
    NONE = "none"
    DIAGONAL_ROLL = "diagonal_roll"          # Standard diagonal roll
    AGGRESSIVE_ROLL = "aggressive_roll"      # Roll with extra DTE
    DEFENSIVE_ROLL = "defensive_roll"        # Roll to deeper OTM


class TradeOutcome(Enum):
    """Trade outcome"""
    WIN = "win"                     # Profit (including rolled trades)
    LOSS = "loss"                   # Loss (couldn't recover)
    MAX_LOSS = "max_loss"           # Hit max loss
    ROLLED_WIN = "rolled_win"       # Won after rolling
    ROLLED_LOSS = "rolled_loss"     # Lost despite rolling


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DiagonalRollEvent:
    """A single diagonal roll event"""
    roll_day: int               # Day of trade when roll occurred
    roll_type: RollType

    # Old position
    old_short_strike: float
    old_long_strike: float
    old_expiry_dte: int

    # New position
    new_short_strike: float
    new_long_strike: float
    new_expiry_dte: int

    # Costs and credits
    close_cost: float           # Cost to close old position (debit)
    new_credit: float           # Credit from new position
    roll_net: float             # Net result (negative = debit, positive = credit)

    # Context
    stock_price_at_roll: float
    support_level_used: Optional[float]
    loss_at_roll_pct: float     # How much were we losing before roll

    # Cumulative tracking
    cumulative_credit: float    # Total credits received so far
    cumulative_cost: float      # Total costs paid so far


@dataclass
class DiagonalTradeResult:
    """Complete result of a diagonal roll trade"""
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float      # Stock price at entry
    exit_price: float       # Stock price at exit

    # Initial position
    initial_short_strike: float
    initial_long_strike: float
    initial_dte: int
    initial_credit: float

    # Final position
    final_short_strike: float
    final_long_strike: float
    final_dte_remaining: int

    # P&L
    total_credits_received: float  # Sum of all credits
    total_costs_paid: float        # Sum of all close costs
    final_pnl: float               # Net P&L
    outcome: TradeOutcome

    # Roll tracking
    roll_count: int = 0
    roll_events: List[DiagonalRollEvent] = field(default_factory=list)

    # Additional metrics
    max_drawdown_pct: float = 0.0
    holding_days: int = 0
    iv_at_entry: float = 0.0
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
            'roll_events': [
                {
                    'roll_day': r.roll_day,
                    'roll_type': r.roll_type.value,
                    'old_short_strike': r.old_short_strike,
                    'new_short_strike': r.new_short_strike,
                    'old_long_strike': r.old_long_strike,
                    'new_long_strike': r.new_long_strike,
                    'old_expiry_dte': r.old_expiry_dte,
                    'new_expiry_dte': r.new_expiry_dte,
                    'close_cost': r.close_cost,
                    'new_credit': r.new_credit,
                    'roll_net': r.roll_net,
                    'stock_price_at_roll': r.stock_price_at_roll,
                    'support_level_used': r.support_level_used,
                    'loss_at_roll_pct': r.loss_at_roll_pct,
                }
                for r in self.roll_events
            ],
            'max_drawdown_pct': self.max_drawdown_pct,
            'holding_days': self.holding_days,
            'iv_at_entry': self.iv_at_entry,
            'lowest_price_seen': self.lowest_price_seen,
            'support_levels_used': self.support_levels_used,
        }


# =============================================================================
# Black-Scholes Functions
# =============================================================================

def norm_cdf(x: float) -> float:
    """Standard normal CDF using error function"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes Put price"""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(K - S, 0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    put_price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    return max(put_price, 0)


def black_scholes_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes Put Delta"""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return -1.0 if K > S else 0.0

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) - 1.0


def find_strike_for_delta(
    S: float, T: float, r: float, sigma: float,
    target_delta: float, strike_step: float = 1.0
) -> float:
    """Find strike price that gives target delta using bisection"""
    low = S * 0.50
    high = S * 1.20

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
    """Estimate IV from historical price data"""
    if len(prices) < days + 1:
        return 0.30

    returns = np.diff(np.log(prices[-days-1:]))
    daily_vol = np.std(returns)
    annual_vol = daily_vol * math.sqrt(252)
    iv_premium = 1.20

    return min(max(annual_vol * iv_premium, 0.15), 1.50)


# =============================================================================
# Support Level Detection
# =============================================================================

def find_support_levels_simple(
    lows: np.ndarray,
    lookback: int = 60,
    window: int = 5,
    max_levels: int = 5,
    tolerance_pct: float = 1.5
) -> List[float]:
    """
    Find support levels from price lows.

    Returns list of support prices sorted by strength (strongest first).
    """
    if len(lows) < 2 * window + 1:
        return []

    # Use last 'lookback' days
    lookback = min(lookback, len(lows))
    recent_lows = lows[-lookback:]

    # Find local minima (swing lows)
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
        # Fallback: use overall minimum
        return [float(np.min(recent_lows))]

    # Cluster similar levels
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
            clusters.append({
                'avg': price,
                'prices': [price],
                'count': 1
            })

    # Sort by touch count (more touches = stronger)
    clusters.sort(key=lambda x: x['count'], reverse=True)

    return [c['avg'] for c in clusters[:max_levels]]


def find_next_support_below(
    current_price: float,
    support_levels: List[float],
    buffer_pct: float = 2.0
) -> Optional[float]:
    """
    Find the next support level below current price.

    Returns the support price with buffer, or None if no support found.
    """
    # Filter supports below current price
    supports_below = [s for s in support_levels if s < current_price]

    if not supports_below:
        return None

    # Get closest support below
    closest_support = max(supports_below)

    # Apply buffer (place strike below support)
    buffered_price = closest_support * (1 - buffer_pct / 100)

    return buffered_price


# =============================================================================
# Diagonal Roll Simulation
# =============================================================================

def simulate_diagonal_roll_trade(
    prices: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    entry_idx: int,
    symbol: str,
    entry_date: date,
) -> Optional[DiagonalTradeResult]:
    """
    Simulate a Bull-Put-Spread trade with diagonal roll strategy.

    Roll Rule:
    - Trigger: When spread reaches -50% of initial credit
    - Action: Roll diagonal (2-3 months forward)
    - Strike: Below next support level
    - Goal: Offset loss with new credit
    - Repeat: Until stock bottoms and recovers
    """
    # Minimum data needed
    if entry_idx + INITIAL_DTE >= len(prices):
        return None

    entry_price = prices[entry_idx]

    # Estimate IV
    lookback = min(60, entry_idx)
    recent_prices = prices[entry_idx - lookback:entry_idx + 1]
    iv = estimate_iv_from_history(recent_prices)

    # Determine strike step
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

    total_credits = initial_credit * 100  # Per contract, in dollars
    total_costs = 0.0
    roll_count = 0
    roll_events = []
    max_drawdown_pct = 0.0
    lowest_price = entry_price
    support_levels_used = []

    day = 0
    max_day = min(MAX_HOLDING_DAYS, len(prices) - entry_idx - 1)

    while day < max_day:
        day += 1
        current_idx = entry_idx + day

        if current_idx >= len(prices):
            break

        current_price = prices[current_idx]
        lowest_price = min(lowest_price, current_price)

        # Calculate DTE remaining
        dte_remaining = current_expiry_day - current_idx
        T_remaining = max(dte_remaining, 0) / 365.0

        # Current spread value (cost to close)
        if T_remaining > 0:
            short_val = black_scholes_put(current_price, current_short, T_remaining, RISK_FREE_RATE, iv)
            long_val = black_scholes_put(current_price, current_long, T_remaining, RISK_FREE_RATE, iv)
        else:
            # At expiration - intrinsic value
            short_val = max(current_short - current_price, 0)
            long_val = max(current_long - current_price, 0)

        spread_value = short_val - long_val

        # Current P&L (credits - costs - current close cost)
        current_pnl = total_credits - total_costs - (spread_value * 100)

        # Calculate P&L percentage relative to initial credit
        # Positive = profit, Negative = loss
        # Example: initial_credit=50, current_pnl=25 -> pnl_pct = 50% (profit)
        # Example: initial_credit=50, current_pnl=-25 -> pnl_pct = -50% (loss)
        initial_credit_dollars = initial_credit * 100
        if initial_credit_dollars > 0.01:  # Avoid division by zero
            pnl_pct = (current_pnl / initial_credit_dollars) * 100
        else:
            pnl_pct = 0.0

        # Track max drawdown (most negative P&L %)
        # Clamp to reasonable bounds
        if pnl_pct < max_drawdown_pct and pnl_pct > -500:
            max_drawdown_pct = pnl_pct

        # Check for profit target
        profit_pct = pnl_pct
        if profit_pct >= PROFIT_TARGET_PCT:
            # Take profit
            exit_price = current_price
            exit_date = entry_date + timedelta(days=day)

            final_pnl = current_pnl
            outcome = TradeOutcome.ROLLED_WIN if roll_count > 0 else TradeOutcome.WIN

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
                lowest_price_seen=lowest_price,
                support_levels_used=support_levels_used,
            )

        # Check expiration
        if dte_remaining <= 0:
            # Position expired
            exit_price = current_price
            exit_date = entry_date + timedelta(days=day)

            # Final P&L based on intrinsic
            final_spread_value = max(current_short - current_price, 0) - max(current_long - current_price, 0)
            final_pnl = total_credits - total_costs - (final_spread_value * 100)

            if final_pnl > 0:
                outcome = TradeOutcome.ROLLED_WIN if roll_count > 0 else TradeOutcome.WIN
            elif current_price <= current_long:
                outcome = TradeOutcome.MAX_LOSS
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
                lowest_price_seen=lowest_price,
                support_levels_used=support_levels_used,
            )

        # ========================================
        # DIAGONAL ROLL TRIGGER: -50% of credit
        # ========================================
        if pnl_pct <= ROLL_TRIGGER_PCT and roll_count < MAX_ROLLS_PER_TRADE:
            # Find support levels
            lookback_lows = lows[max(0, current_idx - 252):current_idx]
            support_levels = find_support_levels_simple(lookback_lows)

            # Find target strike below next support
            target_price = find_next_support_below(
                current_price=current_price,
                support_levels=support_levels,
                buffer_pct=SUPPORT_BUFFER_PCT
            )

            if target_price is None:
                # No support found, use percentage OTM
                target_price = current_price * 0.90  # 10% OTM

            # Calculate new expiry (extend 2-3 months)
            extension = ROLL_DTE_EXTENSION
            if roll_count >= 2:
                extension = ROLL_DTE_EXTENSION_MAX  # Longer extension for repeated rolls

            new_dte = extension
            new_T = new_dte / 365.0
            new_expiry_day = current_idx + new_dte

            # Ensure we have price data for new expiry
            if new_expiry_day >= len(prices) - 1:
                new_expiry_day = len(prices) - 30
                new_dte = new_expiry_day - current_idx
                new_T = new_dte / 365.0

            # Find new strikes
            # Short strike: below support level
            new_short = round(target_price / strike_step) * strike_step
            # Ensure short strike is below current price
            if new_short >= current_price:
                new_short = find_strike_for_delta(current_price, new_T, RISK_FREE_RATE, iv, SHORT_DELTA_TARGET, strike_step)

            # Long strike: standard delta
            new_long = find_strike_for_delta(current_price, new_T, RISK_FREE_RATE, iv, LONG_DELTA_TARGET, strike_step)

            if new_long >= new_short:
                new_long = new_short - strike_step

            # Calculate roll costs
            # 1. Cost to close current position
            close_cost = spread_value * 100  # Debit

            # 2. Credit from new position
            new_short_put = black_scholes_put(current_price, new_short, new_T, RISK_FREE_RATE, iv)
            new_long_put = black_scholes_put(current_price, new_long, new_T, RISK_FREE_RATE, iv)
            new_credit = (new_short_put - new_long_put) * 100

            # Check if roll is worthwhile
            # Goal: New credit should help offset the loss
            roll_net = new_credit - close_cost

            # Calculate credit recovery ratio
            current_loss = abs(current_pnl) if current_pnl < 0 else 0
            credit_recovery = new_credit / max(current_loss, 1)

            # Only roll if we get meaningful credit
            if new_credit > 0 and (roll_net >= 0 or credit_recovery >= MIN_ROLL_CREDIT_PCT):
                # Execute roll
                support_used = target_price if target_price else None

                # Clamp pnl_pct for roll event to reasonable bounds
                roll_pnl_pct = max(-500, min(500, pnl_pct))

                roll_event = DiagonalRollEvent(
                    roll_day=day,
                    roll_type=RollType.DIAGONAL_ROLL if roll_count < 2 else RollType.AGGRESSIVE_ROLL,
                    old_short_strike=current_short,
                    old_long_strike=current_long,
                    old_expiry_dte=dte_remaining,
                    new_short_strike=new_short,
                    new_long_strike=new_long,
                    new_expiry_dte=new_dte,
                    close_cost=close_cost,
                    new_credit=new_credit,
                    roll_net=roll_net,
                    stock_price_at_roll=current_price,
                    support_level_used=support_used,
                    loss_at_roll_pct=roll_pnl_pct,
                    cumulative_credit=total_credits + new_credit,
                    cumulative_cost=total_costs + close_cost,
                )

                roll_events.append(roll_event)
                roll_count += 1

                # Update state
                total_credits += new_credit
                total_costs += close_cost
                current_short = new_short
                current_long = new_long
                current_expiry_day = new_expiry_day

                if support_used:
                    support_levels_used.append(support_used)

                logger.debug(
                    f"{symbol} Day {day}: ROLL #{roll_count} at ${current_price:.2f} "
                    f"(P&L: {pnl_pct:.1f}%) -> New strikes: {new_short}/{new_long} "
                    f"DTE: {new_dte}, Roll net: ${roll_net:.2f}"
                )

    # End of simulation (max days reached)
    exit_idx = min(entry_idx + day, len(prices) - 1)
    exit_price = prices[exit_idx]
    exit_date = entry_date + timedelta(days=day)

    # Final P&L
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
        lowest_price_seen=lowest_price,
        support_levels_used=support_levels_used,
    )


# =============================================================================
# Database Management
# =============================================================================

class DiagonalRollDatabase:
    """SQLite database for diagonal roll backtest results"""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
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
                    initial_dte INTEGER,
                    initial_credit REAL,
                    final_short_strike REAL,
                    final_long_strike REAL,
                    total_credits REAL,
                    total_costs REAL,
                    final_pnl REAL,
                    outcome TEXT,
                    roll_count INTEGER DEFAULT 0,
                    max_drawdown_pct REAL,
                    holding_days INTEGER,
                    iv_at_entry REAL,
                    lowest_price_seen REAL,
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
                    old_expiry_dte INTEGER,
                    new_expiry_dte INTEGER,
                    close_cost REAL,
                    new_credit REAL,
                    roll_net REAL,
                    stock_price_at_roll REAL,
                    support_level_used REAL,
                    loss_at_roll_pct REAL,
                    cumulative_credit REAL,
                    cumulative_cost REAL,
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

    def create_run(self, run_name: str, total_symbols: int, config: Dict[str, Any]) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO backtest_runs (
                    run_name, run_date, total_symbols, total_trades,
                    win_rate, total_pnl, config_json, created_at
                ) VALUES (?, ?, ?, 0, 0, 0, ?, ?)
            """, (run_name, now[:10], total_symbols, json.dumps(config), now))

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
                    iv_at_entry, lowest_price_seen, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                trade.iv_at_entry, trade.lowest_price_seen, now
            ))

            trade_id = cursor.lastrowid

            # Add roll events
            for roll in trade.roll_events:
                cursor.execute("""
                    INSERT INTO roll_events (
                        trade_id, roll_day, roll_type,
                        old_short_strike, new_short_strike,
                        old_long_strike, new_long_strike,
                        old_expiry_dte, new_expiry_dte,
                        close_cost, new_credit, roll_net,
                        stock_price_at_roll, support_level_used,
                        loss_at_roll_pct, cumulative_credit, cumulative_cost,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_id, roll.roll_day, roll.roll_type.value,
                    roll.old_short_strike, roll.new_short_strike,
                    roll.old_long_strike, roll.new_long_strike,
                    roll.old_expiry_dte, roll.new_expiry_dte,
                    roll.close_cost, roll.new_credit, roll.roll_net,
                    roll.stock_price_at_roll, roll.support_level_used,
                    roll.loss_at_roll_pct, roll.cumulative_credit, roll.cumulative_cost,
                    now
                ))

            return trade_id

    def update_run_stats(self, run_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN outcome IN ('win', 'rolled_win') THEN 1 ELSE 0 END) as wins,
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
        with self._get_connection() as conn:
            cursor = conn.cursor()

            run_filter = "WHERE t.run_id = ?" if run_id else ""
            params = (run_id,) if run_id else ()

            # Total trades and rolled trades
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN roll_count > 0 THEN 1 ELSE 0 END) as rolled_trades,
                    SUM(roll_count) as total_rolls,
                    AVG(roll_count) as avg_rolls_per_trade,
                    MAX(roll_count) as max_rolls_single_trade
                FROM trades t {run_filter}
            """, params)
            row = cursor.fetchone()

            stats = {
                'total_trades': row['total_trades'] or 0,
                'rolled_trades': row['rolled_trades'] or 0,
                'total_rolls': row['total_rolls'] or 0,
                'avg_rolls_per_trade': row['avg_rolls_per_trade'] or 0,
                'max_rolls_single_trade': row['max_rolls_single_trade'] or 0,
            }

            # Win rate for rolled vs non-rolled
            cursor.execute(f"""
                SELECT
                    CASE WHEN roll_count > 0 THEN 'rolled' ELSE 'not_rolled' END as category,
                    COUNT(*) as trades,
                    SUM(CASE WHEN outcome IN ('win', 'rolled_win') THEN 1 ELSE 0 END) as wins,
                    AVG(final_pnl) as avg_pnl,
                    SUM(final_pnl) as total_pnl,
                    AVG(holding_days) as avg_holding_days,
                    AVG(max_drawdown_pct) as avg_drawdown
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
                    'avg_holding_days': row['avg_holding_days'] or 0,
                    'avg_drawdown': row['avg_drawdown'] or 0,
                }

            # Roll effectiveness (did roll save the trade?)
            cursor.execute(f"""
                SELECT
                    outcome,
                    COUNT(*) as count,
                    AVG(final_pnl) as avg_pnl,
                    AVG(roll_count) as avg_rolls
                FROM trades t
                {run_filter.replace('WHERE', 'WHERE t.roll_count > 0 AND') if run_filter else 'WHERE t.roll_count > 0'}
                GROUP BY outcome
            """, params)

            stats['rolled_outcomes'] = {}
            for row in cursor.fetchall():
                stats['rolled_outcomes'][row['outcome']] = {
                    'count': row['count'],
                    'avg_pnl': row['avg_pnl'] or 0,
                    'avg_rolls': row['avg_rolls'] or 0,
                }

            # Roll net analysis
            roll_filter = f"WHERE r.trade_id IN (SELECT id FROM trades t {run_filter})" if run_id else ""
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_rolls,
                    AVG(roll_net) as avg_roll_net,
                    SUM(CASE WHEN roll_net >= 0 THEN 1 ELSE 0 END) as credit_rolls,
                    SUM(CASE WHEN roll_net < 0 THEN 1 ELSE 0 END) as debit_rolls,
                    AVG(new_credit) as avg_new_credit,
                    AVG(close_cost) as avg_close_cost,
                    AVG(loss_at_roll_pct) as avg_loss_at_roll
                FROM roll_events r {roll_filter}
            """, params if run_id else ())

            row = cursor.fetchone()
            if row:
                stats['roll_economics'] = {
                    'total_rolls': row['total_rolls'] or 0,
                    'avg_roll_net': row['avg_roll_net'] or 0,
                    'credit_rolls': row['credit_rolls'] or 0,
                    'debit_rolls': row['debit_rolls'] or 0,
                    'avg_new_credit': row['avg_new_credit'] or 0,
                    'avg_close_cost': row['avg_close_cost'] or 0,
                    'avg_loss_at_roll': row['avg_loss_at_roll'] or 0,
                }

            return stats

    def get_summary(self, run_id: Optional[int] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if run_id:
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
                        AVG(iv_at_entry) as avg_iv,
                        AVG(max_drawdown_pct) as avg_drawdown
                    FROM trades WHERE run_id = ?
                """, (run_id,))
            else:
                run = None
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN outcome IN ('win', 'rolled_win') THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN outcome IN ('loss', 'rolled_loss') THEN 1 ELSE 0 END) as losses,
                        SUM(CASE WHEN outcome = 'max_loss' THEN 1 ELSE 0 END) as max_losses,
                        AVG(final_pnl) as avg_pnl,
                        SUM(final_pnl) as total_pnl,
                        AVG(holding_days) as avg_holding,
                        AVG(iv_at_entry) as avg_iv,
                        AVG(max_drawdown_pct) as avg_drawdown
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
                'avg_drawdown': stats['avg_drawdown'] or 0,
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
        return []

    try:
        import yaml
        with open(watchlist_path) as f:
            config = yaml.safe_load(f)

        watchlists = config.get('watchlists', {})

        if watchlist_name in watchlists:
            return watchlists[watchlist_name].get('symbols', [])

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
        watchlists = config.get('watchlists', config)

        for wl_name, wl_data in watchlists.items():
            if not isinstance(wl_data, dict):
                continue

            if 'symbols' in wl_data:
                symbols = wl_data.get('symbols', [])
                if isinstance(symbols, list):
                    all_symbols.update(s for s in symbols if isinstance(s, str))

            if 'sectors' in wl_data:
                sectors = wl_data.get('sectors', {})
                if isinstance(sectors, dict):
                    for sector_data in sectors.values():
                        if isinstance(sector_data, dict) and 'symbols' in sector_data:
                            symbols = sector_data.get('symbols', [])
                            if isinstance(symbols, list):
                                all_symbols.update(s for s in symbols if isinstance(s, str))

        valid_symbols = [s for s in all_symbols if s and len(s) <= 6 and not s.startswith('#')]
        return sorted(valid_symbols)
    except Exception as e:
        logger.warning(f"Failed to load watchlists: {e}")
        return []


# =============================================================================
# Backtest Runner
# =============================================================================

def backtest_symbol(
    symbol: str,
    start_date: str,
    end_date: str,
    entry_interval: int = 30,
) -> List[DiagonalTradeResult]:
    """Run diagonal roll backtest for a single symbol"""
    df = fetch_price_data(symbol, start_date, end_date)
    if df is None:
        return []

    prices = df['Close'].values
    highs = df['High'].values
    lows = df['Low'].values
    dates = df.index.date

    results = []

    # Enter trades at regular intervals
    idx = INITIAL_DTE + 60  # Need lookback for IV and support calculation
    while idx < len(prices) - INITIAL_DTE - 60:
        entry_date = dates[idx]

        result = simulate_diagonal_roll_trade(
            prices=prices,
            highs=highs,
            lows=lows,
            entry_idx=idx,
            symbol=symbol,
            entry_date=entry_date,
        )

        if result:
            results.append(result)
            # Skip forward based on how long this trade lasted
            idx += max(result.holding_days, entry_interval)
        else:
            idx += entry_interval

    return results


def worker_process(args) -> List[DiagonalTradeResult]:
    """Worker function for multiprocessing"""
    symbol, start_date, end_date, entry_interval = args
    try:
        return backtest_symbol(symbol, start_date, end_date, entry_interval)
    except Exception as e:
        logger.error(f"Error processing {symbol}: {e}")
        traceback.print_exc()
        return []


def run_backtest(
    symbols: List[str],
    start_date: str,
    end_date: str,
    entry_interval: int = 30,
    workers: int = 4,
    run_name: Optional[str] = None,
) -> int:
    """Run full diagonal roll backtest"""
    db = DiagonalRollDatabase()

    config = {
        'short_delta': SHORT_DELTA_TARGET,
        'long_delta': LONG_DELTA_TARGET,
        'initial_dte': INITIAL_DTE,
        'roll_trigger_pct': ROLL_TRIGGER_PCT,
        'roll_dte_extension': ROLL_DTE_EXTENSION,
        'max_rolls': MAX_ROLLS_PER_TRADE,
        'min_roll_credit_pct': MIN_ROLL_CREDIT_PCT,
        'support_buffer_pct': SUPPORT_BUFFER_PCT,
        'profit_target_pct': PROFIT_TARGET_PCT,
        'entry_interval': entry_interval,
        'start_date': start_date,
        'end_date': end_date,
    }

    run_name = run_name or f"diagonal_roll_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_id = db.create_run(run_name, len(symbols), config)

    logger.info(f"Created backtest run {run_id}: {run_name}")
    logger.info(f"Processing {len(symbols)} symbols with {workers} workers")
    logger.info(f"Roll trigger: {ROLL_TRIGGER_PCT}% loss | DTE extension: {ROLL_DTE_EXTENSION} days")

    work_items = [(symbol, start_date, end_date, entry_interval) for symbol in symbols]

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

    db.update_run_stats(run_id)

    logger.info(f"Completed backtest run {run_id} with {len(all_results)} trades")

    return run_id


def print_results(run_id: int):
    """Print backtest results summary"""
    db = DiagonalRollDatabase()

    summary = db.get_summary(run_id)
    roll_stats = db.get_roll_statistics(run_id)

    print("\n" + "=" * 70)
    print("DIAGONAL ROLL STRATEGY - BACKTEST RESULTS")
    print("=" * 70)

    print(f"\nRun ID: {run_id}")
    if summary.get('run'):
        print(f"Name: {summary['run'].get('run_name', 'N/A')}")

    print(f"\n{'='*30} OVERALL {'='*30}")
    print(f"Total Trades: {summary['total_trades']:,}")
    print(f"Wins: {summary['wins']:,}")
    print(f"Losses: {summary['losses']:,}")
    print(f"Max Losses: {summary['max_losses']:,}")
    print(f"Win Rate: {summary['win_rate']:.1f}%")
    print(f"Avg P&L per Trade: ${summary['avg_pnl']:,.2f}")
    print(f"Total P&L: ${summary['total_pnl']:,.2f}")
    print(f"Avg Holding Days: {summary['avg_holding_days']:.1f}")
    print(f"Avg IV at Entry: {summary['avg_iv']*100:.1f}%")
    print(f"Avg Max Drawdown: {summary['avg_drawdown']:.1f}%")

    print(f"\n{'='*30} ROLL STATISTICS {'='*30}")
    print(f"Total Rolls: {roll_stats['total_rolls']:,}")
    print(f"Trades with Rolls: {roll_stats['rolled_trades']:,} ({roll_stats['rolled_trades']/max(roll_stats['total_trades'],1)*100:.1f}%)")
    print(f"Avg Rolls per Trade: {roll_stats['avg_rolls_per_trade']:.2f}")
    print(f"Max Rolls (Single Trade): {roll_stats['max_rolls_single_trade']}")

    if roll_stats.get('by_roll_status'):
        print(f"\n{'='*30} PERFORMANCE BY ROLL STATUS {'='*30}")
        for status, data in roll_stats['by_roll_status'].items():
            print(f"\n  {status.upper()}:")
            print(f"    Trades: {data['trades']:,}")
            print(f"    Win Rate: {data['win_rate']:.1f}%")
            print(f"    Avg P&L: ${data['avg_pnl']:,.2f}")
            print(f"    Total P&L: ${data['total_pnl']:,.2f}")
            print(f"    Avg Holding: {data['avg_holding_days']:.1f} days")
            print(f"    Avg Drawdown: {data['avg_drawdown']:.1f}%")

    if roll_stats.get('roll_economics'):
        econ = roll_stats['roll_economics']
        print(f"\n{'='*30} ROLL ECONOMICS {'='*30}")
        print(f"Total Rolls: {econ['total_rolls']}")
        print(f"Credit Rolls: {econ['credit_rolls']} ({econ['credit_rolls']/max(econ['total_rolls'],1)*100:.1f}%)")
        print(f"Debit Rolls: {econ['debit_rolls']} ({econ['debit_rolls']/max(econ['total_rolls'],1)*100:.1f}%)")
        print(f"Avg Roll Net: ${econ['avg_roll_net']:.2f}")
        print(f"Avg New Credit: ${econ['avg_new_credit']:.2f}")
        print(f"Avg Close Cost: ${econ['avg_close_cost']:.2f}")
        print(f"Avg Loss at Roll: {econ['avg_loss_at_roll']:.1f}%")

    if roll_stats.get('rolled_outcomes'):
        print(f"\n{'='*30} OUTCOMES FOR ROLLED TRADES {'='*30}")
        for outcome, data in roll_stats['rolled_outcomes'].items():
            print(f"  {outcome}: {data['count']} trades (avg P&L: ${data['avg_pnl']:.2f}, avg rolls: {data['avg_rolls']:.1f})")

    print("\n" + "=" * 70)


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="OptionPlay Diagonal Roll Strategy Backtest"
    )

    parser.add_argument('--symbols', '-s', type=str, help='Comma-separated list of symbols')
    parser.add_argument('--watchlist', '-w', type=str, help='Watchlist name from config')
    parser.add_argument('--all', '-a', action='store_true', help='Use all symbols')

    parser.add_argument('--start', type=str, default='2020-01-01', help='Start date')
    parser.add_argument('--end', type=str, default='2024-12-31', help='End date')

    parser.add_argument('--entry-interval', type=int, default=30, help='Days between entries')
    parser.add_argument('--workers', type=int, default=4, help='Parallel workers')
    parser.add_argument('--name', type=str, help='Run name')

    parser.add_argument('--results', type=int, help='Print results for run ID')

    # Roll parameters
    parser.add_argument('--roll-trigger', type=float, default=ROLL_TRIGGER_PCT,
                        help=f'Roll trigger loss %% (default: {ROLL_TRIGGER_PCT})')
    parser.add_argument('--roll-dte', type=int, default=ROLL_DTE_EXTENSION,
                        help=f'DTE extension on roll (default: {ROLL_DTE_EXTENSION})')
    parser.add_argument('--max-rolls', type=int, default=MAX_ROLLS_PER_TRADE,
                        help=f'Max rolls per trade (default: {MAX_ROLLS_PER_TRADE})')

    args = parser.parse_args()

    if args.results:
        print_results(args.results)
        return

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

    # Use args for roll parameters (override module defaults)
    roll_trigger = args.roll_trigger
    roll_dte = args.roll_dte
    max_rolls = args.max_rolls

    print(f"\nDiagonal Roll Strategy Backtest")
    print(f"{'='*40}")
    print(f"Symbols: {len(symbols)}")
    print(f"Date range: {args.start} to {args.end}")
    print(f"Roll trigger: {roll_trigger}% loss")
    print(f"DTE extension: {roll_dte} days")
    print(f"Max rolls: {max_rolls}")
    print(f"{'='*40}\n")

    run_id = run_backtest(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        entry_interval=args.entry_interval,
        workers=args.workers,
        run_name=args.name,
    )

    print_results(run_id)

    print(f"\nResults saved to: {DB_PATH}")
    print(f"View results anytime: python {__file__} --results {run_id}")


if __name__ == '__main__':
    main()
