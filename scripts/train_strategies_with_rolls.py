#!/usr/bin/env python3
"""
Comprehensive Iterative Training with Diagonal Roll Strategy

This script performs multi-phase training of all 4 strategies (Pullback, Bounce,
ATH Breakout, Earnings Dip) using the extended historical database and integrating
the diagonal roll strategy for loss recovery.

Training Phases:
1. Initial Backtest: Run all strategies through historical data with roll support
2. Component Weight Optimization: Find optimal weights per strategy
3. Regime-Aware Training: Optimize parameters per VIX regime
4. Roll Strategy Optimization: Tune roll triggers and recovery parameters
5. Ensemble Meta-Learner Training: Combine all learnings
6. Validation: Out-of-sample testing

Usage:
    # Full training
    python scripts/train_strategies_with_rolls.py --all --workers 6

    # Specific phase
    python scripts/train_strategies_with_rolls.py --phase backtest

    # Distributed training
    python scripts/train_strategies_with_rolls.py --all --distributed --worker-id 0 --total-workers 2
"""

import argparse
import asyncio
import gzip
import json
import logging
import math
import os
import random
import sqlite3
import sys
import zlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set

import numpy as np
from scipy import stats
from scipy.optimize import minimize, differential_evolution

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_PATH = Path.home() / ".optionplay" / "trades.db"
RESULTS_DB_PATH = Path.home() / ".optionplay" / "training_results.db"
OUTPUT_DIR = Path(__file__).parent.parent / "training_outputs"

# Strategy names
STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip"]

# Training parameters
MIN_BARS_REQUIRED = 500  # ~2 years minimum
MIN_YEARS_DATA = 3       # For quality training
TRAIN_TEST_SPLIT = 0.7   # 70% train, 30% test

# Options parameters
SHORT_DELTA_TARGET = -0.20
LONG_DELTA_TARGET = -0.05
INITIAL_DTE = 45
SPREAD_WIDTH = 5.0

# Roll parameters (to be optimized)
DEFAULT_ROLL_TRIGGER_PCT = -50.0
DEFAULT_ROLL_DTE_EXTENSION = 60
DEFAULT_MAX_ROLLS = 5
DEFAULT_MIN_ROLL_CREDIT_PCT = 0.50

# Profit/Loss parameters
PROFIT_TARGET_PCT = 50.0
STOP_LOSS_PCT = -200.0  # Wide stop, let rolls work
MAX_HOLDING_DAYS = 180

# VIX Regime thresholds
VIX_LOW = 15
VIX_NORMAL = 20
VIX_ELEVATED = 30


# =============================================================================
# DATA CLASSES
# =============================================================================

class StrategyType(Enum):
    PULLBACK = "pullback"
    BOUNCE = "bounce"
    ATH_BREAKOUT = "ath_breakout"
    EARNINGS_DIP = "earnings_dip"


class TradeOutcome(Enum):
    WIN = "win"
    LOSS = "loss"
    MAX_LOSS = "max_loss"
    ROLLED_WIN = "rolled_win"
    ROLLED_LOSS = "rolled_loss"
    EXPIRED = "expired"


class VIXRegime(Enum):
    LOW = "low"        # VIX < 15
    NORMAL = "normal"  # 15 <= VIX < 20
    ELEVATED = "elevated"  # 20 <= VIX < 30
    HIGH = "high"      # VIX >= 30


@dataclass
class PriceBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class StrategySignal:
    """Signal from a strategy analyzer."""
    symbol: str
    strategy: StrategyType
    score: float
    components: Dict[str, float]
    date: date
    price: float


@dataclass
class RollEvent:
    """Record of a roll maneuver."""
    roll_day: int
    old_strikes: Tuple[float, float]
    new_strikes: Tuple[float, float]
    old_dte: int
    new_dte: int
    close_cost: float
    new_credit: float
    roll_net: float
    price_at_roll: float
    support_used: Optional[float]
    loss_pct_at_roll: float


@dataclass
class TradeResult:
    """Result of a simulated trade."""
    symbol: str
    strategy: StrategyType
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    initial_credit: float
    final_pnl: float
    pnl_pct: float
    outcome: TradeOutcome
    holding_days: int
    roll_count: int
    roll_events: List[RollEvent]
    max_drawdown_pct: float
    vix_at_entry: float
    regime: VIXRegime
    score_at_entry: float
    components_at_entry: Dict[str, float]


@dataclass
class StrategyPerformance:
    """Aggregated performance metrics for a strategy."""
    strategy: StrategyType
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    avg_holding_days: float
    total_rolls: int
    avg_rolls_per_trade: float
    roll_success_rate: float  # Rolled trades that ended as wins
    avg_drawdown: float
    sharpe_ratio: float
    by_regime: Dict[VIXRegime, Dict[str, float]]


@dataclass
class ComponentWeights:
    """Trainable weights for score components."""
    rsi: float = 1.0
    support: float = 1.0
    fibonacci: float = 1.0
    moving_average: float = 1.0
    volume: float = 1.0
    macd: float = 1.0
    stochastic: float = 1.0
    keltner: float = 1.0
    trend: float = 1.0
    momentum: float = 1.0
    relative_strength: float = 1.0
    candlestick: float = 1.0
    gap: float = 1.0
    stabilization: float = 1.0
    dip_magnitude: float = 1.0
    ath_breakout: float = 1.0
    vwap: float = 1.0
    market_context: float = 1.0


@dataclass
class RollParameters:
    """Trainable roll strategy parameters."""
    trigger_pct: float = -50.0
    dte_extension: int = 60
    dte_extension_max: int = 90
    max_rolls: int = 5
    min_credit_recovery_pct: float = 0.50
    support_buffer_pct: float = 2.0


@dataclass
class TrainingConfig:
    """Configuration for a training run."""
    strategy: StrategyType
    component_weights: ComponentWeights
    roll_params: RollParameters
    min_score: float = 4.0  # Lower threshold for more trades in training
    profit_target_pct: float = 50.0
    stop_loss_pct: float = -200.0
    regime_adjustments: Dict[VIXRegime, Dict[str, float]] = field(default_factory=dict)


# =============================================================================
# DATABASE ACCESS
# =============================================================================

def get_db_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Get database connection."""
    return sqlite3.connect(str(db_path))


def get_symbols_with_data(conn: sqlite3.Connection, min_bars: int = MIN_BARS_REQUIRED) -> List[str]:
    """Get symbols with sufficient historical data."""
    cursor = conn.execute("""
        SELECT symbol FROM price_data
        WHERE bar_count >= ?
        ORDER BY bar_count DESC
    """, (min_bars,))
    return [row[0] for row in cursor.fetchall()]


def load_price_data(conn: sqlite3.Connection, symbol: str) -> List[PriceBar]:
    """Load price data for a symbol."""
    cursor = conn.execute("""
        SELECT data_compressed FROM price_data WHERE symbol = ?
    """, (symbol,))
    row = cursor.fetchone()

    if not row or not row[0]:
        return []

    # Decompress
    try:
        decompressed = gzip.decompress(row[0])
    except:
        try:
            decompressed = zlib.decompress(row[0])
        except:
            return []

    data = json.loads(decompressed.decode('utf-8'))

    bars = []
    for item in data:
        try:
            bar_date = item.get('date', item.get('d'))
            if isinstance(bar_date, str):
                bar_date = datetime.strptime(bar_date, "%Y-%m-%d").date()

            bars.append(PriceBar(
                date=bar_date,
                open=float(item.get('open', item.get('o', 0))),
                high=float(item.get('high', item.get('h', 0))),
                low=float(item.get('low', item.get('l', 0))),
                close=float(item.get('close', item.get('c', 0))),
                volume=int(item.get('volume', item.get('v', 0)))
            ))
        except:
            continue

    bars.sort(key=lambda x: x.date)
    return bars


def load_vix_data(conn: sqlite3.Connection) -> Dict[date, float]:
    """Load VIX data."""
    cursor = conn.execute("SELECT date, value FROM vix_data ORDER BY date")
    vix = {}
    for row in cursor.fetchall():
        try:
            d = datetime.strptime(row[0], "%Y-%m-%d").date() if isinstance(row[0], str) else row[0]
            vix[d] = float(row[1])
        except:
            continue
    return vix


# =============================================================================
# STRATEGY SCORING (Simplified for training)
# =============================================================================

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Calculate RSI."""
    if len(prices) < period + 1:
        return 50.0

    deltas = np.diff(prices[-period-1:])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0.0001

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_sma(prices: List[float], period: int) -> float:
    """Calculate Simple Moving Average."""
    if len(prices) < period:
        return prices[-1] if prices else 0
    return np.mean(prices[-period:])


def find_support_levels(lows: List[float], window: int = 20, num_levels: int = 3) -> List[float]:
    """Find support levels from swing lows."""
    if len(lows) < window:
        return []

    swing_lows = []
    half_window = window // 2

    for i in range(half_window, len(lows) - half_window):
        is_low = True
        for j in range(i - half_window, i + half_window + 1):
            if j != i and lows[j] < lows[i]:
                is_low = False
                break
        if is_low:
            swing_lows.append(lows[i])

    if not swing_lows:
        return [min(lows[-60:])] if len(lows) >= 60 else []

    # Cluster similar levels
    swing_lows.sort()
    clusters = []
    current_cluster = [swing_lows[0]]

    for level in swing_lows[1:]:
        if level <= current_cluster[-1] * 1.02:  # Within 2%
            current_cluster.append(level)
        else:
            clusters.append(np.mean(current_cluster))
            current_cluster = [level]
    clusters.append(np.mean(current_cluster))

    return sorted(clusters)[-num_levels:]


def score_pullback(bars: List[PriceBar], weights: ComponentWeights) -> Tuple[float, Dict[str, float]]:
    """Score a pullback setup."""
    if len(bars) < 50:
        return 0.0, {}

    prices = [b.close for b in bars]
    lows = [b.low for b in bars]
    volumes = [b.volume for b in bars]
    current_price = prices[-1]

    components = {}

    # RSI Component (0-3 points)
    rsi = calculate_rsi(prices)
    if rsi < 30:
        components['rsi'] = 3.0
    elif rsi < 40:
        components['rsi'] = 2.0
    elif rsi < 50:
        components['rsi'] = 1.0
    else:
        components['rsi'] = 0.0

    # Support Proximity (0-2 points)
    supports = find_support_levels(lows[-120:])
    if supports:
        closest_support = min(supports, key=lambda s: abs(s - current_price))
        distance_pct = (current_price - closest_support) / current_price * 100
        if 0 <= distance_pct <= 3:
            components['support'] = 2.0
        elif 0 <= distance_pct <= 5:
            components['support'] = 1.0
        else:
            components['support'] = 0.0
    else:
        components['support'] = 0.0

    # Moving Average (0-2 points) - Dip in uptrend
    sma20 = calculate_sma(prices, 20)
    sma200 = calculate_sma(prices, 200) if len(prices) >= 200 else sma20
    if current_price > sma200 and current_price < sma20:
        components['moving_average'] = 2.0
    elif current_price > sma200:
        components['moving_average'] = 1.0
    else:
        components['moving_average'] = 0.0

    # Volume Spike (0-1 point)
    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
    if volumes[-1] > avg_vol * 1.5:
        components['volume'] = 1.0
    else:
        components['volume'] = 0.0

    # Fibonacci (0-2 points)
    high_90d = max(prices[-90:]) if len(prices) >= 90 else max(prices)
    low_90d = min(prices[-90:]) if len(prices) >= 90 else min(prices)
    if high_90d > low_90d:
        retracement = (high_90d - current_price) / (high_90d - low_90d)
        if 0.58 <= retracement <= 0.68:
            components['fibonacci'] = 2.0
        elif 0.45 <= retracement <= 0.55:
            components['fibonacci'] = 1.5
        elif 0.33 <= retracement <= 0.43:
            components['fibonacci'] = 1.0
        else:
            components['fibonacci'] = 0.0
    else:
        components['fibonacci'] = 0.0

    # Calculate weighted score (sum all components)
    score = (
        components.get('rsi', 0) * weights.rsi +
        components.get('support', 0) * weights.support +
        components.get('moving_average', 0) * weights.moving_average +
        components.get('volume', 0) * weights.volume +
        components.get('fibonacci', 0) * weights.fibonacci
    )

    # Score is already 0-9 range, cap at 10
    score = min(10.0, score)

    return score, components


def score_bounce(bars: List[PriceBar], weights: ComponentWeights) -> Tuple[float, Dict[str, float]]:
    """Score a bounce setup."""
    if len(bars) < 50:
        return 0.0, {}

    prices = [b.close for b in bars]
    lows = [b.low for b in bars]
    current_price = prices[-1]

    components = {}

    # Support Test (0-3 points)
    supports = find_support_levels(lows[-120:])
    if supports:
        closest = min(supports, key=lambda s: abs(s - current_price))
        distance_pct = abs(current_price - closest) / current_price * 100
        if distance_pct <= 1:
            components['support'] = 3.0
        elif distance_pct <= 2:
            components['support'] = 2.0
        elif distance_pct <= 3:
            components['support'] = 1.0
        else:
            components['support'] = 0.0
    else:
        components['support'] = 0.0

    # RSI Oversold (0-2 points)
    rsi = calculate_rsi(prices)
    if rsi < 30:
        components['rsi'] = 2.0
    elif rsi < 40:
        components['rsi'] = 1.0
    else:
        components['rsi'] = 0.0

    # Bullish reversal (0-2 points) - Close > Open on last bar
    if bars[-1].close > bars[-1].open:
        components['candlestick'] = 1.5
        if bars[-2].close < bars[-2].open:  # Previous was bearish
            components['candlestick'] = 2.0
    else:
        components['candlestick'] = 0.0

    # Trend (above SMA200)
    sma200 = calculate_sma(prices, 200) if len(prices) >= 200 else calculate_sma(prices, 50)
    components['trend'] = 2.0 if current_price > sma200 else 0.0

    score = (
        components.get('support', 0) * weights.support +
        components.get('rsi', 0) * weights.rsi +
        components.get('candlestick', 0) * weights.candlestick +
        components.get('trend', 0) * weights.trend
    )

    score = min(10.0, score)
    return score, components


def score_ath_breakout(bars: List[PriceBar], weights: ComponentWeights) -> Tuple[float, Dict[str, float]]:
    """Score an ATH breakout setup."""
    if len(bars) < 250:
        return 0.0, {}

    prices = [b.close for b in bars]
    highs = [b.high for b in bars]
    volumes = [b.volume for b in bars]
    current_price = prices[-1]

    components = {}

    # ATH Breakout (0-3 points)
    ath = max(highs[:-5])  # Exclude last 5 days
    if current_price > ath:
        breakout_pct = (current_price - ath) / ath * 100
        if breakout_pct > 2:
            components['ath_breakout'] = 3.0
        elif breakout_pct > 0:
            components['ath_breakout'] = 2.0
        else:
            components['ath_breakout'] = 1.0
    else:
        distance_to_ath = (ath - current_price) / ath * 100
        if distance_to_ath < 2:
            components['ath_breakout'] = 1.0
        else:
            components['ath_breakout'] = 0.0

    # Volume Confirmation (0-2 points)
    avg_vol = np.mean(volumes[-20:])
    if volumes[-1] > avg_vol * 2:
        components['volume'] = 2.0
    elif volumes[-1] > avg_vol * 1.5:
        components['volume'] = 1.0
    else:
        components['volume'] = 0.0

    # Trend Strength (0-2 points)
    sma20 = calculate_sma(prices, 20)
    sma50 = calculate_sma(prices, 50)
    if current_price > sma20 > sma50:
        components['trend'] = 2.0
    elif current_price > sma50:
        components['trend'] = 1.0
    else:
        components['trend'] = 0.0

    # RSI not overbought (0-1 point)
    rsi = calculate_rsi(prices)
    if rsi < 70:
        components['rsi'] = 1.0
    else:
        components['rsi'] = 0.0

    # Momentum (0-2 points)
    if len(prices) >= 20:
        momentum = (prices[-1] - prices[-20]) / prices[-20] * 100
        if momentum > 10:
            components['momentum'] = 2.0
        elif momentum > 5:
            components['momentum'] = 1.0
        else:
            components['momentum'] = 0.0
    else:
        components['momentum'] = 0.0

    score = (
        components.get('ath_breakout', 0) * weights.ath_breakout +
        components.get('volume', 0) * weights.volume +
        components.get('trend', 0) * weights.trend +
        components.get('rsi', 0) * weights.rsi +
        components.get('momentum', 0) * weights.momentum
    )

    score = min(10.0, score)
    return score, components


def score_earnings_dip(bars: List[PriceBar], weights: ComponentWeights) -> Tuple[float, Dict[str, float]]:
    """Score an earnings dip setup."""
    if len(bars) < 50:
        return 0.0, {}

    prices = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    current_price = prices[-1]

    components = {}

    # Check for recent significant drop (5-15%)
    recent_high = max(prices[-20:])
    dip_pct = (recent_high - current_price) / recent_high * 100

    if 5 <= dip_pct <= 15:
        components['dip_magnitude'] = 3.0
    elif 3 <= dip_pct <= 20:
        components['dip_magnitude'] = 2.0
    elif dip_pct > 0:
        components['dip_magnitude'] = 1.0
    else:
        components['dip_magnitude'] = 0.0

    # RSI Oversold (0-2 points)
    rsi = calculate_rsi(prices)
    if rsi < 35:
        components['rsi'] = 2.0
    elif rsi < 45:
        components['rsi'] = 1.0
    else:
        components['rsi'] = 0.0

    # Stabilization (0-2 points) - Last 3 days showing smaller range
    if len(bars) >= 5:
        recent_ranges = [(b.high - b.low) / b.close for b in bars[-3:]]
        prior_ranges = [(b.high - b.low) / b.close for b in bars[-6:-3]]
        if np.mean(recent_ranges) < np.mean(prior_ranges):
            components['stabilization'] = 2.0
        else:
            components['stabilization'] = 0.5
    else:
        components['stabilization'] = 0.0

    # Volume Pattern (0-1 point) - Volume decreasing (selling exhaustion)
    if len(volumes) >= 5:
        recent_vol = np.mean(volumes[-3:])
        prior_vol = np.mean(volumes[-6:-3])
        if recent_vol < prior_vol:
            components['volume'] = 1.0
        else:
            components['volume'] = 0.0
    else:
        components['volume'] = 0.0

    # Above major support (SMA200)
    sma200 = calculate_sma(prices, 200) if len(prices) >= 200 else calculate_sma(prices, 50)
    if current_price > sma200 * 0.9:  # Within 10% of SMA200
        components['trend'] = 1.0
    else:
        components['trend'] = 0.0

    score = (
        components.get('dip_magnitude', 0) * weights.dip_magnitude +
        components.get('rsi', 0) * weights.rsi +
        components.get('stabilization', 0) * weights.stabilization +
        components.get('volume', 0) * weights.volume +
        components.get('trend', 0) * weights.trend
    )

    score = min(10.0, score)
    return score, components


def get_strategy_score(
    bars: List[PriceBar],
    strategy: StrategyType,
    weights: ComponentWeights
) -> Tuple[float, Dict[str, float]]:
    """Get score for a strategy."""
    if strategy == StrategyType.PULLBACK:
        return score_pullback(bars, weights)
    elif strategy == StrategyType.BOUNCE:
        return score_bounce(bars, weights)
    elif strategy == StrategyType.ATH_BREAKOUT:
        return score_ath_breakout(bars, weights)
    elif strategy == StrategyType.EARNINGS_DIP:
        return score_earnings_dip(bars, weights)
    return 0.0, {}


# =============================================================================
# BLACK-SCHOLES OPTIONS PRICING
# =============================================================================

def norm_cdf(x: float) -> float:
    """Standard normal CDF."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes put option price."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(K - S, 0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    put_price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    return max(put_price, 0)


def calculate_put_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate put delta."""
    if T <= 0 or sigma <= 0:
        return -1.0 if K > S else 0.0

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) - 1


def find_strike_by_delta(
    S: float,
    T: float,
    r: float,
    sigma: float,
    target_delta: float
) -> float:
    """Find strike that gives target delta."""
    # Binary search for strike
    low_k = S * 0.5
    high_k = S * 1.5

    for _ in range(50):
        mid_k = (low_k + high_k) / 2
        delta = calculate_put_delta(S, mid_k, T, r, sigma)

        if abs(delta - target_delta) < 0.001:
            return mid_k

        if delta < target_delta:
            high_k = mid_k
        else:
            low_k = mid_k

    return mid_k


def estimate_iv(vix: float, base_iv: float = 0.25) -> float:
    """Estimate stock IV from VIX."""
    # Stock IV is typically VIX * multiplier
    return max(0.15, min(1.0, vix / 100 * 1.2 + base_iv * 0.3))


# =============================================================================
# TRADE SIMULATION WITH ROLLS
# =============================================================================

def simulate_trade(
    bars: List[PriceBar],
    entry_idx: int,
    strategy: StrategyType,
    score: float,
    components: Dict[str, float],
    vix_data: Dict[date, float],
    roll_params: RollParameters,
    config: TrainingConfig
) -> Optional[TradeResult]:
    """Simulate a trade with diagonal roll capability."""

    if entry_idx >= len(bars) - 10:
        return None

    entry_bar = bars[entry_idx]
    entry_price = entry_bar.close
    entry_date = entry_bar.date

    # Get VIX and determine regime
    vix = vix_data.get(entry_date, 18.0)
    if vix < VIX_LOW:
        regime = VIXRegime.LOW
    elif vix < VIX_NORMAL:
        regime = VIXRegime.NORMAL
    elif vix < VIX_ELEVATED:
        regime = VIXRegime.ELEVATED
    else:
        regime = VIXRegime.HIGH

    # Estimate IV and calculate initial strikes
    iv = estimate_iv(vix)
    T = INITIAL_DTE / 365.0
    r = 0.05  # Risk-free rate

    short_strike = find_strike_by_delta(entry_price, T, r, iv, SHORT_DELTA_TARGET)
    long_strike = short_strike - SPREAD_WIDTH

    # Initial credit
    short_put_price = black_scholes_put(entry_price, short_strike, T, r, iv)
    long_put_price = black_scholes_put(entry_price, long_strike, T, r, iv)
    initial_credit = short_put_price - long_put_price

    if initial_credit <= 0.05:
        return None

    # Simulation state
    current_short = short_strike
    current_long = long_strike
    current_dte = INITIAL_DTE
    total_credits = initial_credit
    total_costs = 0.0
    roll_count = 0
    roll_events = []
    max_drawdown_pct = 0.0

    prices = [b.close for b in bars]
    lows = [b.low for b in bars]

    # Simulate each day
    for day in range(1, MAX_HOLDING_DAYS + 1):
        current_idx = entry_idx + day
        if current_idx >= len(bars):
            break

        current_bar = bars[current_idx]
        current_price = current_bar.close
        dte_remaining = max(0, current_dte - day)
        T_remaining = dte_remaining / 365.0

        # Calculate current spread value
        current_vix = vix_data.get(current_bar.date, vix)
        current_iv = estimate_iv(current_vix)

        if dte_remaining > 0:
            short_val = black_scholes_put(current_price, current_short, T_remaining, r, current_iv)
            long_val = black_scholes_put(current_price, current_long, T_remaining, r, current_iv)
        else:
            # At expiration
            short_val = max(current_short - current_price, 0)
            long_val = max(current_long - current_price, 0)

        spread_value = short_val - long_val
        current_pnl = (total_credits - total_costs) * 100 - spread_value * 100

        # Calculate P&L percentage
        initial_credit_dollars = initial_credit * 100
        if initial_credit_dollars > 0.01:
            pnl_pct = (current_pnl / initial_credit_dollars) * 100
        else:
            pnl_pct = 0.0

        # Track max drawdown
        if pnl_pct < max_drawdown_pct and pnl_pct > -500:
            max_drawdown_pct = pnl_pct

        # Check profit target
        if pnl_pct >= config.profit_target_pct:
            return TradeResult(
                symbol=entry_bar.date.isoformat(),  # Placeholder
                strategy=strategy,
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=current_bar.date,
                exit_price=current_price,
                initial_credit=initial_credit,
                final_pnl=current_pnl,
                pnl_pct=pnl_pct,
                outcome=TradeOutcome.ROLLED_WIN if roll_count > 0 else TradeOutcome.WIN,
                holding_days=day,
                roll_count=roll_count,
                roll_events=roll_events,
                max_drawdown_pct=max_drawdown_pct,
                vix_at_entry=vix,
                regime=regime,
                score_at_entry=score,
                components_at_entry=components
            )

        # Check stop loss (only if we've exhausted rolls)
        if pnl_pct <= config.stop_loss_pct and roll_count >= roll_params.max_rolls:
            return TradeResult(
                symbol=entry_bar.date.isoformat(),
                strategy=strategy,
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=current_bar.date,
                exit_price=current_price,
                initial_credit=initial_credit,
                final_pnl=current_pnl,
                pnl_pct=pnl_pct,
                outcome=TradeOutcome.ROLLED_LOSS if roll_count > 0 else TradeOutcome.MAX_LOSS,
                holding_days=day,
                roll_count=roll_count,
                roll_events=roll_events,
                max_drawdown_pct=max_drawdown_pct,
                vix_at_entry=vix,
                regime=regime,
                score_at_entry=score,
                components_at_entry=components
            )

        # Check expiration
        if dte_remaining <= 0:
            outcome = TradeOutcome.ROLLED_WIN if (roll_count > 0 and current_pnl > 0) else \
                      TradeOutcome.ROLLED_LOSS if (roll_count > 0 and current_pnl <= 0) else \
                      TradeOutcome.WIN if current_pnl > 0 else TradeOutcome.LOSS

            return TradeResult(
                symbol=entry_bar.date.isoformat(),
                strategy=strategy,
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=current_bar.date,
                exit_price=current_price,
                initial_credit=initial_credit,
                final_pnl=current_pnl,
                pnl_pct=pnl_pct,
                outcome=outcome,
                holding_days=day,
                roll_count=roll_count,
                roll_events=roll_events,
                max_drawdown_pct=max_drawdown_pct,
                vix_at_entry=vix,
                regime=regime,
                score_at_entry=score,
                components_at_entry=components
            )

        # ========================================
        # DIAGONAL ROLL TRIGGER
        # ========================================
        if pnl_pct <= roll_params.trigger_pct and roll_count < roll_params.max_rolls:
            # Find support levels
            lookback_lows = lows[max(0, current_idx - 252):current_idx]
            supports = find_support_levels(lookback_lows)

            # Find target strike below support
            target_strike = None
            if supports:
                for support in sorted(supports, reverse=True):
                    if support < current_price:
                        target_strike = support * (1 - roll_params.support_buffer_pct / 100)
                        break

            if not target_strike:
                target_strike = current_price * 0.95

            # Calculate new position
            new_dte = min(dte_remaining + roll_params.dte_extension, roll_params.dte_extension_max)
            new_T = new_dte / 365.0

            # Close current position
            close_cost = spread_value

            # New strikes
            new_short = find_strike_by_delta(current_price, new_T, r, current_iv, SHORT_DELTA_TARGET)
            new_short = min(new_short, target_strike)  # Below support
            new_long = new_short - SPREAD_WIDTH

            # New credit
            new_short_price = black_scholes_put(current_price, new_short, new_T, r, current_iv)
            new_long_price = black_scholes_put(current_price, new_long, new_T, r, current_iv)
            new_credit = new_short_price - new_long_price

            roll_net = new_credit - close_cost

            # Only roll if we get meaningful credit
            current_loss = abs(current_pnl) if current_pnl < 0 else 0
            credit_recovery = new_credit / max(current_loss / 100, 0.01)

            if new_credit > 0 and (roll_net >= 0 or credit_recovery >= roll_params.min_credit_recovery_pct):
                roll_events.append(RollEvent(
                    roll_day=day,
                    old_strikes=(current_short, current_long),
                    new_strikes=(new_short, new_long),
                    old_dte=dte_remaining,
                    new_dte=new_dte,
                    close_cost=close_cost,
                    new_credit=new_credit,
                    roll_net=roll_net,
                    price_at_roll=current_price,
                    support_used=target_strike if supports else None,
                    loss_pct_at_roll=pnl_pct
                ))

                roll_count += 1
                current_short = new_short
                current_long = new_long
                current_dte = day + new_dte  # New expiration day
                total_credits += new_credit
                total_costs += close_cost

    # End of simulation (max days reached)
    current_idx = min(entry_idx + MAX_HOLDING_DAYS, len(bars) - 1)
    current_bar = bars[current_idx]
    current_price = current_bar.close

    # Final valuation
    spread_value = max(current_short - current_price, 0) - max(current_long - current_price, 0)
    final_pnl = (total_credits - total_costs) * 100 - spread_value * 100
    pnl_pct = (final_pnl / (initial_credit * 100)) * 100 if initial_credit > 0 else 0

    outcome = TradeOutcome.ROLLED_WIN if (roll_count > 0 and final_pnl > 0) else \
              TradeOutcome.ROLLED_LOSS if (roll_count > 0 and final_pnl <= 0) else \
              TradeOutcome.WIN if final_pnl > 0 else TradeOutcome.EXPIRED

    return TradeResult(
        symbol=entry_bar.date.isoformat(),
        strategy=strategy,
        entry_date=entry_date,
        entry_price=entry_price,
        exit_date=current_bar.date,
        exit_price=current_price,
        initial_credit=initial_credit,
        final_pnl=final_pnl,
        pnl_pct=pnl_pct,
        outcome=outcome,
        holding_days=MAX_HOLDING_DAYS,
        roll_count=roll_count,
        roll_events=roll_events,
        max_drawdown_pct=max_drawdown_pct,
        vix_at_entry=vix,
        regime=regime,
        score_at_entry=score,
        components_at_entry=components
    )


# =============================================================================
# BACKTEST RUNNER
# =============================================================================

def backtest_symbol(
    symbol: str,
    bars: List[PriceBar],
    vix_data: Dict[date, float],
    config: TrainingConfig,
    entry_interval: int = 14
) -> List[TradeResult]:
    """Backtest a single symbol."""
    results = []

    if len(bars) < 260:  # Need at least 1 year
        return results

    # Start from day 252 to have enough history
    start_idx = 252

    for entry_idx in range(start_idx, len(bars) - 30, entry_interval):
        # Get signal
        score, components = get_strategy_score(
            bars[:entry_idx + 1],
            config.strategy,
            config.component_weights
        )

        if score < config.min_score:
            continue

        # Simulate trade
        result = simulate_trade(
            bars=bars,
            entry_idx=entry_idx,
            strategy=config.strategy,
            score=score,
            components=components,
            vix_data=vix_data,
            roll_params=config.roll_params,
            config=config
        )

        if result:
            result.symbol = symbol
            results.append(result)

    return results


def backtest_strategy(
    symbols: List[str],
    price_data: Dict[str, List[PriceBar]],
    vix_data: Dict[date, float],
    config: TrainingConfig,
    workers: int = 6
) -> List[TradeResult]:
    """Backtest a strategy across all symbols."""
    all_results = []

    # Use sequential processing to avoid pickle issues with nested functions
    for symbol in tqdm(symbols, desc=f"Backtesting {config.strategy.value}"):
        try:
            bars = price_data.get(symbol, [])
            if bars:
                results = backtest_symbol(symbol, bars, vix_data, config)
                all_results.extend(results)
        except Exception as e:
            logger.warning(f"Error processing {symbol}: {e}")

    return all_results


def calculate_performance(results: List[TradeResult], strategy: StrategyType) -> StrategyPerformance:
    """Calculate aggregated performance metrics."""
    if not results:
        return StrategyPerformance(
            strategy=strategy,
            total_trades=0,
            wins=0,
            losses=0,
            win_rate=0.0,
            avg_pnl=0.0,
            total_pnl=0.0,
            avg_holding_days=0.0,
            total_rolls=0,
            avg_rolls_per_trade=0.0,
            roll_success_rate=0.0,
            avg_drawdown=0.0,
            sharpe_ratio=0.0,
            by_regime={}
        )

    wins = sum(1 for r in results if r.outcome in [TradeOutcome.WIN, TradeOutcome.ROLLED_WIN])
    losses = len(results) - wins

    pnls = [r.final_pnl for r in results]

    # Rolled trades
    rolled_trades = [r for r in results if r.roll_count > 0]
    rolled_wins = sum(1 for r in rolled_trades if r.outcome == TradeOutcome.ROLLED_WIN)

    # By regime
    by_regime = {}
    for regime in VIXRegime:
        regime_results = [r for r in results if r.regime == regime]
        if regime_results:
            regime_wins = sum(1 for r in regime_results if r.outcome in [TradeOutcome.WIN, TradeOutcome.ROLLED_WIN])
            by_regime[regime] = {
                'trades': len(regime_results),
                'win_rate': regime_wins / len(regime_results) * 100,
                'avg_pnl': np.mean([r.final_pnl for r in regime_results])
            }

    # Sharpe ratio
    if len(pnls) > 1:
        sharpe = np.mean(pnls) / (np.std(pnls) + 0.001) * np.sqrt(252)
    else:
        sharpe = 0.0

    return StrategyPerformance(
        strategy=strategy,
        total_trades=len(results),
        wins=wins,
        losses=losses,
        win_rate=wins / len(results) * 100,
        avg_pnl=np.mean(pnls),
        total_pnl=sum(pnls),
        avg_holding_days=np.mean([r.holding_days for r in results]),
        total_rolls=sum(r.roll_count for r in results),
        avg_rolls_per_trade=np.mean([r.roll_count for r in results]),
        roll_success_rate=rolled_wins / len(rolled_trades) * 100 if rolled_trades else 0.0,
        avg_drawdown=np.mean([r.max_drawdown_pct for r in results]),
        sharpe_ratio=sharpe,
        by_regime=by_regime
    )


# =============================================================================
# OPTIMIZATION
# =============================================================================

def optimize_component_weights(
    symbols: List[str],
    price_data: Dict[str, List[PriceBar]],
    vix_data: Dict[date, float],
    strategy: StrategyType,
    roll_params: RollParameters,
    iterations: int = 50
) -> Tuple[ComponentWeights, float]:
    """Optimize component weights using evolutionary algorithm."""

    def objective(weights_array: np.ndarray) -> float:
        weights = ComponentWeights(
            rsi=weights_array[0],
            support=weights_array[1],
            fibonacci=weights_array[2],
            moving_average=weights_array[3],
            volume=weights_array[4],
            macd=weights_array[5],
            stochastic=weights_array[6],
            keltner=weights_array[7],
            trend=weights_array[8],
            momentum=weights_array[9],
            relative_strength=weights_array[10],
            candlestick=weights_array[11],
            gap=weights_array[12],
            stabilization=weights_array[13],
            dip_magnitude=weights_array[14],
            ath_breakout=weights_array[15],
            vwap=weights_array[16],
            market_context=weights_array[17]
        )

        config = TrainingConfig(
            strategy=strategy,
            component_weights=weights,
            roll_params=roll_params
        )

        # Quick backtest on subset
        subset = random.sample(symbols, min(50, len(symbols)))
        results = []

        for sym in subset:
            bars = price_data.get(sym, [])
            if len(bars) > 260:
                sym_results = backtest_symbol(sym, bars, vix_data, config, entry_interval=21)
                results.extend(sym_results)

        if not results:
            return 1000.0  # Penalty for no trades

        perf = calculate_performance(results, strategy)

        # Objective: maximize win rate and Sharpe, minimize drawdown
        score = -(perf.win_rate * 0.4 + perf.sharpe_ratio * 10 * 0.3 - abs(perf.avg_drawdown) * 0.3)

        return score

    # Bounds for each weight (0.5 to 2.0)
    bounds = [(0.5, 2.0)] * 18

    logger.info(f"Optimizing weights for {strategy.value}...")

    iteration_count = [0]
    def callback(xk, convergence):
        iteration_count[0] += 1
        if iteration_count[0] % 5 == 0:
            logger.info(f"  Weight optimization iteration {iteration_count[0]}/{iterations}, convergence: {convergence:.4f}")
        return False

    result = differential_evolution(
        objective,
        bounds,
        maxiter=iterations,
        workers=1,  # Use single worker to avoid nested parallelism
        disp=False,
        callback=callback,
        seed=42
    )

    best_weights = ComponentWeights(
        rsi=result.x[0],
        support=result.x[1],
        fibonacci=result.x[2],
        moving_average=result.x[3],
        volume=result.x[4],
        macd=result.x[5],
        stochastic=result.x[6],
        keltner=result.x[7],
        trend=result.x[8],
        momentum=result.x[9],
        relative_strength=result.x[10],
        candlestick=result.x[11],
        gap=result.x[12],
        stabilization=result.x[13],
        dip_magnitude=result.x[14],
        ath_breakout=result.x[15],
        vwap=result.x[16],
        market_context=result.x[17]
    )

    return best_weights, -result.fun


def optimize_roll_parameters(
    symbols: List[str],
    price_data: Dict[str, List[PriceBar]],
    vix_data: Dict[date, float],
    strategy: StrategyType,
    weights: ComponentWeights,
    iterations: int = 30
) -> Tuple[RollParameters, float]:
    """Optimize roll strategy parameters."""

    def objective(params_array: np.ndarray) -> float:
        roll_params = RollParameters(
            trigger_pct=params_array[0],
            dte_extension=int(params_array[1]),
            dte_extension_max=int(params_array[2]),
            max_rolls=int(params_array[3]),
            min_credit_recovery_pct=params_array[4],
            support_buffer_pct=params_array[5]
        )

        config = TrainingConfig(
            strategy=strategy,
            component_weights=weights,
            roll_params=roll_params
        )

        # Quick backtest
        subset = random.sample(symbols, min(30, len(symbols)))
        results = []

        for sym in subset:
            bars = price_data.get(sym, [])
            if len(bars) > 260:
                sym_results = backtest_symbol(sym, bars, vix_data, config, entry_interval=28)
                results.extend(sym_results)

        if not results:
            return 1000.0

        perf = calculate_performance(results, strategy)

        # Objective: maximize roll success rate and overall win rate
        score = -(perf.win_rate * 0.5 + perf.roll_success_rate * 0.3 + perf.sharpe_ratio * 5 * 0.2)

        return score

    # Bounds: trigger_pct, dte_ext, dte_max, max_rolls, min_credit, support_buffer
    bounds = [
        (-70, -30),     # trigger_pct
        (45, 90),       # dte_extension
        (60, 120),      # dte_extension_max
        (3, 7),         # max_rolls
        (0.3, 0.8),     # min_credit_recovery_pct
        (1.0, 5.0)      # support_buffer_pct
    ]

    logger.info(f"Optimizing roll parameters for {strategy.value}...")

    iteration_count = [0]
    def callback(xk, convergence):
        iteration_count[0] += 1
        if iteration_count[0] % 5 == 0:
            logger.info(f"  Roll param optimization iteration {iteration_count[0]}/{iterations}, convergence: {convergence:.4f}")
        return False

    result = differential_evolution(
        objective,
        bounds,
        maxiter=iterations,
        workers=1,
        disp=False,
        callback=callback,
        seed=42
    )

    best_params = RollParameters(
        trigger_pct=result.x[0],
        dte_extension=int(result.x[1]),
        dte_extension_max=int(result.x[2]),
        max_rolls=int(result.x[3]),
        min_credit_recovery_pct=result.x[4],
        support_buffer_pct=result.x[5]
    )

    return best_params, -result.fun


# =============================================================================
# TRAINING ORCHESTRATION
# =============================================================================

def load_all_data(conn: sqlite3.Connection, min_bars: int = MIN_BARS_REQUIRED) -> Tuple[List[str], Dict[str, List[PriceBar]], Dict[date, float]]:
    """Load all data for training."""
    symbols = get_symbols_with_data(conn, min_bars)
    logger.info(f"Found {len(symbols)} symbols with >= {min_bars} bars")

    price_data = {}
    for sym in tqdm(symbols, desc="Loading price data"):
        bars = load_price_data(conn, sym)
        if bars:
            price_data[sym] = bars

    vix_data = load_vix_data(conn)
    logger.info(f"Loaded VIX data: {len(vix_data)} days")

    return symbols, price_data, vix_data


def run_training(
    phase: str = "all",
    workers: int = 6,
    distributed: bool = False,
    worker_id: int = 0,
    total_workers: int = 1,
    min_bars: int = MIN_BARS_REQUIRED
):
    """Run the training pipeline."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    symbols, price_data, vix_data = load_all_data(conn, min_bars)
    conn.close()

    # Filter symbols with sufficient data
    symbols = [s for s in symbols if len(price_data.get(s, [])) >= min_bars]

    # Distributed: split symbols
    if distributed and total_workers > 1:
        chunk_size = len(symbols) // total_workers
        start_idx = worker_id * chunk_size
        end_idx = start_idx + chunk_size if worker_id < total_workers - 1 else len(symbols)
        symbols = symbols[start_idx:end_idx]
        logger.info(f"Worker {worker_id}/{total_workers}: Processing {len(symbols)} symbols")

    # Training results
    all_results = {}

    for strategy in [StrategyType.PULLBACK, StrategyType.BOUNCE, StrategyType.ATH_BREAKOUT, StrategyType.EARNINGS_DIP]:
        logger.info(f"\n{'='*60}")
        logger.info(f"Training {strategy.value.upper()}")
        logger.info(f"{'='*60}")

        # Phase 1: Initial backtest with default parameters
        if phase in ["all", "backtest"]:
            logger.info(f"\n[Phase 1] Initial Backtest")
            default_config = TrainingConfig(
                strategy=strategy,
                component_weights=ComponentWeights(),
                roll_params=RollParameters()
            )

            results = backtest_strategy(symbols, price_data, vix_data, default_config, workers)
            perf = calculate_performance(results, strategy)

            logger.info(f"  Trades: {perf.total_trades}")
            logger.info(f"  Win Rate: {perf.win_rate:.1f}%")
            logger.info(f"  Avg P&L: ${perf.avg_pnl:.2f}")
            logger.info(f"  Roll Success Rate: {perf.roll_success_rate:.1f}%")

            all_results[f"{strategy.value}_baseline"] = perf

        # Phase 2: Optimize component weights
        if phase in ["all", "weights"]:
            logger.info(f"\n[Phase 2] Optimizing Component Weights")
            best_weights, score = optimize_component_weights(
                symbols, price_data, vix_data, strategy,
                RollParameters(), iterations=30
            )
            logger.info(f"  Best score: {score:.2f}")

            all_results[f"{strategy.value}_weights"] = asdict(best_weights)
        else:
            best_weights = ComponentWeights()

        # Phase 3: Optimize roll parameters
        if phase in ["all", "rolls"]:
            logger.info(f"\n[Phase 3] Optimizing Roll Parameters")
            best_roll_params, roll_score = optimize_roll_parameters(
                symbols, price_data, vix_data, strategy,
                best_weights, iterations=20
            )
            logger.info(f"  Best roll score: {roll_score:.2f}")
            logger.info(f"  Trigger: {best_roll_params.trigger_pct:.1f}%")
            logger.info(f"  DTE Extension: {best_roll_params.dte_extension}")
            logger.info(f"  Max Rolls: {best_roll_params.max_rolls}")

            all_results[f"{strategy.value}_roll_params"] = asdict(best_roll_params)
        else:
            best_roll_params = RollParameters()

        # Phase 4: Final validation
        if phase in ["all", "validate"]:
            logger.info(f"\n[Phase 4] Final Validation")
            final_config = TrainingConfig(
                strategy=strategy,
                component_weights=best_weights,
                roll_params=best_roll_params
            )

            final_results = backtest_strategy(symbols, price_data, vix_data, final_config, workers)
            final_perf = calculate_performance(final_results, strategy)

            logger.info(f"  Trades: {final_perf.total_trades}")
            logger.info(f"  Win Rate: {final_perf.win_rate:.1f}%")
            logger.info(f"  Avg P&L: ${final_perf.avg_pnl:.2f}")
            logger.info(f"  Sharpe: {final_perf.sharpe_ratio:.3f}")
            logger.info(f"  Roll Success Rate: {final_perf.roll_success_rate:.1f}%")
            logger.info(f"  Avg Rolls/Trade: {final_perf.avg_rolls_per_trade:.2f}")

            # By regime
            for regime, metrics in final_perf.by_regime.items():
                logger.info(f"  {regime.value}: {metrics['trades']} trades, {metrics['win_rate']:.1f}% WR")

            all_results[f"{strategy.value}_final"] = {
                'total_trades': final_perf.total_trades,
                'win_rate': final_perf.win_rate,
                'avg_pnl': final_perf.avg_pnl,
                'sharpe_ratio': final_perf.sharpe_ratio,
                'roll_success_rate': final_perf.roll_success_rate,
                'avg_rolls_per_trade': final_perf.avg_rolls_per_trade,
                'by_regime': {k.value: v for k, v in final_perf.by_regime.items()}
            }

    # Save results
    output_file = OUTPUT_DIR / f"training_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    if distributed:
        output_file = OUTPUT_DIR / f"training_results_worker{worker_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    logger.info(f"\nResults saved to: {output_file}")

    return all_results


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Comprehensive Strategy Training with Roll Support')
    parser.add_argument('--phase', choices=['all', 'backtest', 'weights', 'rolls', 'validate'],
                        default='all', help='Training phase to run')
    parser.add_argument('--workers', type=int, default=6, help='Number of parallel workers')
    parser.add_argument('--distributed', action='store_true', help='Enable distributed mode')
    parser.add_argument('--worker-id', type=int, default=0, help='Worker ID (0-indexed)')
    parser.add_argument('--total-workers', type=int, default=1, help='Total number of workers')
    parser.add_argument('--min-bars', type=int, default=MIN_BARS_REQUIRED,
                        help=f'Minimum bars required (default: {MIN_BARS_REQUIRED})')

    args = parser.parse_args()

    min_bars = args.min_bars

    print(f"\n{'='*60}")
    print(f"COMPREHENSIVE STRATEGY TRAINING WITH ROLL SUPPORT")
    print(f"{'='*60}")
    print(f"Phase: {args.phase}")
    print(f"Workers: {args.workers}")
    print(f"Min Bars: {min_bars}")
    if args.distributed:
        print(f"Distributed: Worker {args.worker_id}/{args.total_workers}")
    print(f"{'='*60}\n")

    run_training(
        phase=args.phase,
        workers=args.workers,
        distributed=args.distributed,
        worker_id=args.worker_id,
        total_workers=args.total_workers,
        min_bars=min_bars
    )


if __name__ == "__main__":
    main()
