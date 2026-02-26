#!/usr/bin/env python3
"""
Full Backtesting with v3.8.1 Weights and Volatility Filters
============================================================

Tests all strategies (PULLBACK, BOUNCE, ATH_BREAKOUT, EARNINGS_DIP)
with the optimized weights and volatility filters over the entire database.

Usage:
    python scripts/backtest_full_v381.py
    python scripts/backtest_full_v381.py --strategy pullback
    python scripts/backtest_full_v381.py --detailed
"""

import argparse
import gzip
import json
import logging
import sqlite3
import sys
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

import numpy as np
import yaml

try:
    from scipy.stats import norm

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

    # Fallback: approximate norm.ppf(0.80) ≈ 0.84
    class norm:
        @staticmethod
        def ppf(x):
            # Simple approximation for common values
            if x >= 0.80:
                return 0.84
            elif x >= 0.70:
                return 0.52
            else:
                return 0.25


# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(iterable, **kwargs):
        return iterable


# Import EarningsHistoryManager
try:
    from cache.earnings_history import get_earnings_history_manager

    EARNINGS_HISTORY_AVAILABLE = True
except ImportError:
    EARNINGS_HISTORY_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_PATH = Path.home() / ".optionplay" / "trades.db"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "trained_weights_v3.8.1.yaml"
MIN_BARS_REQUIRED = 500

EARNINGS_EXCLUSION_DAYS_BEFORE = 14
EARNINGS_EXCLUSION_DAYS_AFTER = 7

# =============================================================================
# PUT CREDIT SPREAD PARAMETERS
# =============================================================================
SPREAD_WIDTH = 5.0  # $5 spread width
TARGET_DELTA = 0.20  # 20 Delta short put
CONTRACTS = 1  # 1 contract = 100 shares
DTE = 75  # Days to expiration (60-90 range, using midpoint)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class PriceBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class SymbolMetrics:
    symbol: str
    volatility: float
    beta: float
    avg_volume: float


@dataclass
class TradeResult:
    symbol: str
    entry_date: date
    exit_date: date
    strategy: str
    entry_price: float
    exit_price: float
    short_strike: float
    long_strike: float
    premium_received: float
    score: float
    win: bool
    pnl: float
    max_drawdown: float
    vix_regime: str


@dataclass
class BacktestResult:
    strategy: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    trades_by_vix: Dict[str, Dict]
    trades_by_year: Dict[int, Dict]
    filtered_symbols: int
    active_symbols: int


# =============================================================================
# LOAD CONFIG
# =============================================================================


def load_config() -> dict:
    """Load v3.8.1 configuration."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# =============================================================================
# DATA LOADING
# =============================================================================


def load_all_symbols(conn: sqlite3.Connection) -> List[str]:
    """Load all symbols from database."""
    cursor = conn.execute("SELECT DISTINCT symbol FROM price_data")
    return [row[0] for row in cursor]


def load_price_data(conn: sqlite3.Connection, symbol: str) -> List[PriceBar]:
    """Load price data for a symbol."""
    cursor = conn.execute("SELECT data_compressed FROM price_data WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()

    if not row:
        return []

    data_blob = row[0]

    # Decompress
    try:
        json_str = gzip.decompress(data_blob).decode("utf-8")
    except:
        try:
            json_str = zlib.decompress(data_blob).decode("utf-8")
        except:
            json_str = data_blob.decode("utf-8") if isinstance(data_blob, bytes) else data_blob

    data = json.loads(json_str)

    bars = []
    for bar in data:
        try:
            d = (
                datetime.strptime(bar["date"], "%Y-%m-%d").date()
                if isinstance(bar["date"], str)
                else bar["date"]
            )
            bars.append(
                PriceBar(
                    date=d,
                    open=float(bar["open"]),
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    volume=int(bar.get("volume", 0)),
                )
            )
        except:
            continue

    return sorted(bars, key=lambda x: x.date)


def load_spy_data(conn: sqlite3.Connection) -> List[PriceBar]:
    """Load SPY data for beta calculation."""
    return load_price_data(conn, "SPY")


def load_vix_data(conn: sqlite3.Connection) -> Dict[date, float]:
    """Load VIX data."""
    cursor = conn.execute("SELECT date, value FROM vix_data ORDER BY date")
    vix_data = {}
    for row in cursor:
        try:
            d = datetime.strptime(row[0], "%Y-%m-%d").date() if isinstance(row[0], str) else row[0]
            vix_data[d] = float(row[1])
        except:
            continue
    return vix_data


def load_earnings_data(symbols: List[str]) -> Dict[str, Set[date]]:
    """Load earnings data for symbols."""
    if not EARNINGS_HISTORY_AVAILABLE:
        return {}

    earnings_data = {}
    earnings_mgr = get_earnings_history_manager()

    for symbol in symbols:
        earnings = earnings_mgr.get_all_earnings(symbol)
        if earnings:
            earnings_data[symbol] = {e.earnings_date for e in earnings}

    return earnings_data


# =============================================================================
# METRICS CALCULATION
# =============================================================================


def calculate_metrics(
    symbol: str, bars: List[PriceBar], spy_returns: List[float]
) -> Optional[SymbolMetrics]:
    """Calculate volatility and beta for a symbol."""
    if len(bars) < 252:
        return None

    closes = [b.close for b in bars[-252:]]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    if len(returns) < 60:
        return None

    # Annualized volatility
    volatility = np.std(returns) * np.sqrt(252) * 100

    # Beta vs SPY
    if len(spy_returns) >= len(returns):
        spy_ret = spy_returns[-len(returns) :]
        if len(spy_ret) == len(returns):
            cov = np.cov(returns, spy_ret)[0][1]
            var = np.var(spy_ret)
            beta = cov / var if var > 0 else 1.0
        else:
            beta = 1.0
    else:
        beta = 1.0

    volatility = max(5, min(150, volatility))
    beta = max(0.1, min(4.0, beta))
    avg_volume = np.mean([b.volume for b in bars[-60:]])

    return SymbolMetrics(symbol=symbol, volatility=volatility, beta=beta, avg_volume=avg_volume)


# =============================================================================
# SCORING
# =============================================================================


def calculate_entry_score(
    bars: List[PriceBar], idx: int, weights: Dict[str, float], strategy: str
) -> float:
    """Calculate entry score for a position."""
    if idx < 50:
        return 0.0

    score = 0.0
    close = bars[idx].close

    # RSI component
    deltas = [bars[i].close - bars[i - 1].close for i in range(idx - 13, idx + 1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 50
    score += weights.get("rsi", 1.0) * (100 - rsi) / 100

    # Support component
    low_20 = min(b.low for b in bars[idx - 20 : idx + 1])
    high_20 = max(b.high for b in bars[idx - 20 : idx + 1])
    if high_20 > low_20:
        support_dist = (close - low_20) / (high_20 - low_20)
        score += weights.get("support", 1.0) * (1 - support_dist)

    # Trend component
    ma_20 = sum(b.close for b in bars[idx - 20 : idx]) / 20
    trend = (close - ma_20) / ma_20 if ma_20 > 0 else 0
    if strategy == "pullback":
        score += weights.get("trend", 1.0) * max(0, -trend * 10)
    else:
        score += weights.get("trend", 1.0) * max(0, trend * 10)

    # Volume component
    avg_vol = sum(b.volume for b in bars[idx - 20 : idx]) / 20
    vol_ratio = bars[idx].volume / avg_vol if avg_vol > 0 else 1
    score += weights.get("volume", 1.0) * min(vol_ratio / 2, 1.0)

    # Momentum component
    mom_5 = (close - bars[idx - 5].close) / bars[idx - 5].close if bars[idx - 5].close > 0 else 0
    score += weights.get("momentum", 1.0) * (0.5 - mom_5 * 5)

    # Stabilization component
    recent_ranges = [(b.high - b.low) / b.close for b in bars[idx - 5 : idx + 1]]
    avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 0
    score += weights.get("stabilization", 1.0) * (1 - min(avg_range * 10, 1))

    # ATH component
    high_252 = max(b.high for b in bars[max(0, idx - 252) : idx + 1])
    ath_dist = (high_252 - close) / high_252 if high_252 > 0 else 0
    if strategy == "ath_breakout":
        score += weights.get("ath_breakout", 1.0) * (1 - ath_dist)
    else:
        score += weights.get("ath_breakout", 1.0) * ath_dist * 0.5

    # MACD component
    ema_12 = sum(b.close for b in bars[idx - 12 : idx]) / 12
    ema_26 = sum(b.close for b in bars[idx - 26 : idx]) / 26
    macd = (ema_12 - ema_26) / ema_26 if ema_26 > 0 else 0
    score += weights.get("macd", 1.0) * (0.5 + macd * 10)

    # VWAP component
    if strategy in ["pullback", "bounce"]:
        vwap_sum = sum(b.close * b.volume for b in bars[idx - 20 : idx + 1])
        vol_sum = sum(b.volume for b in bars[idx - 20 : idx + 1])
        vwap = vwap_sum / vol_sum if vol_sum > 0 else close
        vwap_dist = (close - vwap) / vwap if vwap > 0 else 0
        score += weights.get("vwap", 1.0) * (0.5 - vwap_dist * 5)

    # Stochastic component
    low_14 = min(b.low for b in bars[idx - 14 : idx + 1])
    high_14 = max(b.high for b in bars[idx - 14 : idx + 1])
    if high_14 > low_14:
        stoch_k = (close - low_14) / (high_14 - low_14) * 100
        score += weights.get("stochastic", 1.0) * (100 - stoch_k) / 100

    # Keltner channel component
    atr_sum = sum(
        max(
            b.high - b.low,
            abs(b.high - bars[idx - i - 1].close),
            abs(b.low - bars[idx - i - 1].close),
        )
        for i, b in enumerate(bars[idx - 19 : idx + 1])
    )
    atr = atr_sum / 20
    keltner_upper = ma_20 + 2 * atr
    keltner_lower = ma_20 - 2 * atr
    if keltner_upper > keltner_lower:
        keltner_pos = (close - keltner_lower) / (keltner_upper - keltner_lower)
        score += weights.get("keltner", 1.0) * (1 - keltner_pos)

    # Dip magnitude component
    if strategy in ["pullback", "bounce", "earnings_dip"]:
        recent_high = max(b.high for b in bars[idx - 10 : idx])
        dip = (recent_high - close) / recent_high if recent_high > 0 else 0
        score += weights.get("dip_magnitude", 1.0) * min(dip * 5, 1.0)

    # Market context (simplified)
    ma_50 = sum(b.close for b in bars[idx - 50 : idx]) / 50 if idx >= 50 else ma_20
    market_trend = (ma_20 - ma_50) / ma_50 if ma_50 > 0 else 0
    score += weights.get("market_context", 1.0) * (0.5 + market_trend * 5)

    # Candlestick patterns
    body = abs(bars[idx].close - bars[idx].open)
    range_full = bars[idx].high - bars[idx].low
    if range_full > 0:
        body_ratio = body / range_full
        # Doji or hammer patterns
        if body_ratio < 0.3:
            score += weights.get("candlestick", 1.0) * 0.5

    return max(0, score)


# =============================================================================
# TRADE SIMULATION
# =============================================================================


def get_vix_regime(vix: float) -> str:
    """Classify VIX into regimes."""
    if vix < 15:
        return "low"
    elif vix < 20:
        return "normal"
    elif vix < 30:
        return "elevated"
    else:
        return "high"


def calculate_historical_volatility(bars: List[PriceBar], idx: int, lookback: int = 20) -> float:
    """Calculate annualized historical volatility."""
    if idx < lookback:
        return 0.30  # Default 30%

    closes = [b.close for b in bars[idx - lookback : idx + 1]]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    if not returns:
        return 0.30

    daily_vol = np.std(returns)
    annual_vol = daily_vol * np.sqrt(252)

    return max(0.10, min(1.50, annual_vol))  # Clamp between 10% and 150%


def calculate_short_strike(
    current_price: float, iv: float, dte: int, target_delta: float = 0.20
) -> float:
    """
    Calculate short strike price for target delta using simplified Black-Scholes.

    For a 20 delta put, we want the strike where:
    N(d1) ≈ 0.80 (since put delta = N(d1) - 1)

    Simplified: Strike ≈ Price * (1 - z * IV * sqrt(T))
    where z is the z-score for the target delta (~0.84 for 20 delta)
    """
    # Z-score for target delta (inverted because it's a put)
    # 20 delta put means 80% probability of expiring OTM
    # norm.ppf(0.80) ≈ 0.84
    from scipy.stats import norm

    z_score = norm.ppf(1 - target_delta)  # ~0.84 for 20 delta

    # Time to expiration in years
    t = dte / 365

    # Short strike calculation
    short_strike = current_price * (1 - z_score * iv * np.sqrt(t))

    # Round to nearest $0.50 (realistic strike increments)
    short_strike = round(short_strike * 2) / 2

    return short_strike


def calculate_premium(
    current_price: float, short_strike: float, long_strike: float, iv: float, dte: int, vix: float
) -> float:
    """
    Calculate premium received for put credit spread.

    Premium is affected by:
    - Distance from current price (further OTM = less premium)
    - IV level (higher IV = more premium)
    - VIX level (market fear = more premium)
    - Time to expiration
    """
    # Base premium as percentage of spread width
    # At 20 delta, typical premium is 20-35% of spread width
    otm_pct = (current_price - short_strike) / current_price

    # Base premium calculation
    # Higher IV = more premium
    iv_factor = iv / 0.30  # Normalized to 30% IV

    # VIX adjustment
    vix_factor = vix / 20  # Normalized to VIX 20

    # Time factor (more time = more premium, but not linear)
    time_factor = np.sqrt(dte / 30)  # Normalized to 30 DTE

    # Base credit as % of spread width (typically 25-40% at 20 delta)
    base_credit_pct = 0.30  # 30% of spread width

    # Adjusted credit percentage
    credit_pct = base_credit_pct * iv_factor * vix_factor * time_factor
    credit_pct = max(0.15, min(0.50, credit_pct))  # Clamp between 15% and 50%

    # Calculate premium in dollars
    spread_width = short_strike - long_strike
    premium = spread_width * credit_pct * 100 * CONTRACTS

    return premium


def simulate_trade(
    bars: List[PriceBar],
    entry_idx: int,
    vix_data: Dict[date, float],
    strategy: str,
    symbol_vol: float = None,
    dte: int = DTE,
) -> Optional[TradeResult]:
    """
    Simulate a put credit spread trade with realistic strike/premium calculation.

    Put Credit Spread Structure:
    - Sell short put at ~20 delta
    - Buy long put $5 below (protection)
    - Max profit = premium received
    - Max loss = spread width - premium
    - Win if price stays above short strike at expiration
    """
    if entry_idx >= len(bars) - dte:
        return None

    entry_price = bars[entry_idx].close
    entry_date = bars[entry_idx].date

    # Get VIX for the entry date
    vix = vix_data.get(entry_date, 20.0)
    vix_regime = get_vix_regime(vix)

    # Calculate historical volatility if not provided
    if symbol_vol is None:
        symbol_vol = calculate_historical_volatility(bars, entry_idx)

    # Use higher of historical vol or VIX-implied vol for conservative estimate
    iv = max(symbol_vol, vix / 100)

    # Calculate short strike (20 delta put)
    try:
        short_strike = calculate_short_strike(entry_price, iv, dte, TARGET_DELTA)
    except:
        # Fallback if scipy not available
        short_strike = entry_price * (1 - 0.84 * iv * np.sqrt(dte / 365))
        short_strike = round(short_strike * 2) / 2

    # Long strike is $5 below short strike
    long_strike = short_strike - SPREAD_WIDTH

    # Ensure strikes are valid
    if short_strike >= entry_price or long_strike <= 0:
        return None

    # Calculate premium received
    premium = calculate_premium(entry_price, short_strike, long_strike, iv, dte, vix)

    # Max loss per contract
    max_loss = (SPREAD_WIDTH * 100 * CONTRACTS) - premium

    # Find exit conditions
    exit_idx = min(entry_idx + dte, len(bars) - 1)
    exit_date = bars[exit_idx].date
    exit_price = bars[exit_idx].close

    # Find minimum price during trade (for drawdown calculation)
    min_price = min(b.low for b in bars[entry_idx : exit_idx + 1])
    max_drawdown = (entry_price - min_price) / entry_price * 100

    # Determine win/loss based on whether short strike was breached
    # WIN: Price stays above short strike at expiration
    # LOSS: Price closes below short strike at expiration

    if exit_price >= short_strike:
        # Full win - keep entire premium
        win = True
        pnl = premium
    elif exit_price <= long_strike:
        # Max loss - price below long strike
        win = False
        pnl = -max_loss
    else:
        # Partial loss - price between strikes
        win = False
        # Loss is proportional to how far below short strike
        intrinsic_value = (short_strike - exit_price) * 100 * CONTRACTS
        pnl = premium - intrinsic_value

    return TradeResult(
        symbol="",  # Will be set by caller
        entry_date=entry_date,
        exit_date=exit_date,
        strategy=strategy,
        entry_price=entry_price,
        exit_price=exit_price,
        short_strike=short_strike,
        long_strike=long_strike,
        premium_received=premium,
        score=0.0,  # Will be set by caller
        win=win,
        pnl=pnl,
        max_drawdown=max_drawdown,
        vix_regime=vix_regime,
    )


def is_near_earnings(trade_date: date, symbol: str, earnings_data: Dict[str, Set[date]]) -> bool:
    """Check if date is near earnings."""
    if symbol not in earnings_data:
        return False

    for ed in earnings_data[symbol]:
        days_diff = (trade_date - ed).days
        if -EARNINGS_EXCLUSION_DAYS_BEFORE <= days_diff <= EARNINGS_EXCLUSION_DAYS_AFTER:
            return True
    return False


def is_post_earnings_dip(
    trade_date: date,
    symbol: str,
    earnings_data: Dict[str, Set[date]],
    min_days: int = 1,
    max_days: int = 21,
) -> bool:
    """Check if date is in post-earnings dip window."""
    if symbol not in earnings_data:
        return False

    for ed in earnings_data[symbol]:
        days_diff = (trade_date - ed).days
        if min_days <= days_diff <= max_days:
            return True
    return False


# =============================================================================
# VOLATILITY FILTERING & SCORE ADJUSTMENT
# =============================================================================

# High-Vol symbols require higher scores to qualify
HIGH_VOL_THRESHOLD = 50  # Symbols with vol > 50% are "high-vol"
HIGH_VOL_SCORE_BOOST = 1.5  # Require 1.5x higher score for high-vol symbols


def filter_symbols_by_volatility(
    metrics: Dict[str, SymbolMetrics], strategy: str, config: dict
) -> Tuple[List[str], List[str]]:
    """Filter symbols based on volatility limits."""

    vol_filters = config.get("volatility_filters", {})
    blacklist = set(vol_filters.get("blacklist", []))

    strategy_filters = vol_filters.get(strategy, {})
    max_vol = strategy_filters.get("max_volatility", 100)
    max_beta = strategy_filters.get("max_beta", 3.0)

    active = []
    filtered = []

    for symbol, m in metrics.items():
        if symbol in blacklist:
            filtered.append(symbol)
            continue

        if m.volatility > max_vol or m.beta > max_beta:
            filtered.append(symbol)
            continue

        active.append(symbol)

    return active, filtered


def get_adjusted_min_score(
    base_score: float, symbol: str, metrics: Dict[str, SymbolMetrics]
) -> float:
    """
    Get volatility-adjusted minimum score for a symbol.
    High-vol symbols (>50%) require higher scores to qualify.
    """
    if symbol not in metrics:
        return base_score

    vol = metrics[symbol].volatility

    if vol > HIGH_VOL_THRESHOLD:
        # Linear scaling: 50% vol = 1.0x, 80% vol = 1.5x
        vol_factor = 1.0 + (vol - HIGH_VOL_THRESHOLD) / (80 - HIGH_VOL_THRESHOLD) * (
            HIGH_VOL_SCORE_BOOST - 1.0
        )
        vol_factor = min(vol_factor, HIGH_VOL_SCORE_BOOST)  # Cap at 1.5x
        return base_score * vol_factor

    return base_score


# =============================================================================
# BACKTEST EXECUTION
# =============================================================================


def run_backtest(
    strategy: str,
    all_bars: Dict[str, List[PriceBar]],
    vix_data: Dict[date, float],
    earnings_data: Dict[str, Set[date]],
    metrics: Dict[str, SymbolMetrics],
    config: dict,
    min_score: float = 5.0,
) -> BacktestResult:
    """Run backtest for a single strategy."""

    logger.info(f"\n{'='*60}")
    logger.info(f"  BACKTEST: {strategy.upper()}")
    logger.info(f"{'='*60}")

    # Get weights
    weights = config.get(strategy, {}).get("weights", {})
    if not weights:
        logger.warning(f"No weights found for {strategy}")
        weights = {
            k: 1.0
            for k in [
                "rsi",
                "support",
                "trend",
                "volume",
                "momentum",
                "stabilization",
                "ath_breakout",
                "macd",
                "vwap",
                "stochastic",
                "keltner",
                "dip_magnitude",
                "market_context",
                "candlestick",
            ]
        }

    # Get optimal threshold if available
    perf = config.get(strategy, {}).get("performance", {})
    if strategy == "earnings_dip":
        min_score = config.get(strategy, {}).get("optimal_threshold", 6.86)

    # Filter symbols by volatility
    active_symbols, filtered_symbols = filter_symbols_by_volatility(metrics, strategy, config)

    logger.info(f"  Active symbols: {len(active_symbols)}")
    logger.info(f"  Filtered (Vol/Beta): {len(filtered_symbols)}")

    # Get earnings windows for earnings_dip
    earnings_windows = {}
    if strategy == "earnings_dip":
        ew_config = config.get(strategy, {}).get("earnings_windows", {})
        cluster_windows = ew_config.get("cluster_windows", {})
        cluster_symbols = ew_config.get("cluster_symbols", {})

        for cluster, symbols in cluster_symbols.items():
            window = cluster_windows.get(cluster, {"min_days": 3, "max_days": 14})
            if window.get("enabled", True):
                for s in symbols:
                    earnings_windows[s] = (window.get("min_days", 3), window.get("max_days", 14))

    # Run backtest
    trades = []

    for symbol in tqdm(active_symbols, desc=f"Backtesting {strategy}"):
        if symbol not in all_bars:
            continue

        bars = all_bars[symbol]
        if len(bars) < MIN_BARS_REQUIRED:
            continue

        # Scan for entries
        for i in range(100, len(bars) - 50, 3):
            trade_date = bars[i].date

            # Earnings filter
            if strategy == "earnings_dip":
                # Must be in post-earnings window
                if symbol in earnings_windows:
                    min_d, max_d = earnings_windows[symbol]
                else:
                    min_d, max_d = 3, 14

                if not is_post_earnings_dip(trade_date, symbol, earnings_data, min_d, max_d):
                    continue
            else:
                # Exclude earnings periods for other strategies
                if is_near_earnings(trade_date, symbol, earnings_data):
                    continue

            # Calculate score
            score = calculate_entry_score(bars, i, weights, strategy)

            # Apply volatility-adjusted minimum score
            adjusted_min_score = get_adjusted_min_score(min_score, symbol, metrics)

            if score < adjusted_min_score:
                continue

            # Get symbol volatility from metrics
            symbol_vol = metrics[symbol].volatility / 100 if symbol in metrics else None

            # Simulate trade with realistic P&L calculation
            result = simulate_trade(bars, i, vix_data, strategy, symbol_vol=symbol_vol)

            if result:
                result.symbol = symbol
                result.score = score
                trades.append(result)

    # Analyze results
    if not trades:
        return BacktestResult(
            strategy=strategy,
            total_trades=0,
            wins=0,
            losses=0,
            win_rate=0.0,
            total_pnl=0.0,
            avg_pnl=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            trades_by_vix={},
            trades_by_year={},
            filtered_symbols=len(filtered_symbols),
            active_symbols=len(active_symbols),
        )

    wins = sum(1 for t in trades if t.win)
    losses = len(trades) - wins
    pnls = [t.pnl for t in trades]

    win_rate = wins / len(trades) * 100
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(trades)
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252) if np.std(pnls) > 0 else 0
    max_dd = max(t.max_drawdown for t in trades)

    # Analyze by VIX regime
    trades_by_vix = {}
    for regime in ["low", "normal", "elevated", "high"]:
        regime_trades = [t for t in trades if t.vix_regime == regime]
        if regime_trades:
            r_wins = sum(1 for t in regime_trades if t.win)
            r_pnls = [t.pnl for t in regime_trades]
            trades_by_vix[regime] = {
                "trades": len(regime_trades),
                "wins": r_wins,
                "win_rate": r_wins / len(regime_trades) * 100,
                "avg_pnl": sum(r_pnls) / len(r_pnls),
            }

    # Analyze by year
    trades_by_year = {}
    for trade in trades:
        year = trade.entry_date.year
        if year not in trades_by_year:
            trades_by_year[year] = {"trades": 0, "wins": 0, "pnl": 0.0}
        trades_by_year[year]["trades"] += 1
        if trade.win:
            trades_by_year[year]["wins"] += 1
        trades_by_year[year]["pnl"] += trade.pnl

    for year in trades_by_year:
        y = trades_by_year[year]
        y["win_rate"] = y["wins"] / y["trades"] * 100 if y["trades"] > 0 else 0
        y["avg_pnl"] = y["pnl"] / y["trades"] if y["trades"] > 0 else 0

    return BacktestResult(
        strategy=strategy,
        total_trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_pnl=avg_pnl,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        trades_by_vix=trades_by_vix,
        trades_by_year=trades_by_year,
        filtered_symbols=len(filtered_symbols),
        active_symbols=len(active_symbols),
    )


def print_results(result: BacktestResult, detailed: bool = False):
    """Print backtest results."""

    print(f"\n{'='*70}")
    print(f"  {result.strategy.upper()} BACKTEST RESULTS")
    print(f"{'='*70}")

    print(f"\n  SUMMARY:")
    print(f"  {'─'*50}")
    print(f"  Total Trades:      {result.total_trades:,}")
    print(f"  Wins:              {result.wins:,}")
    print(f"  Losses:            {result.losses:,}")
    print(f"  Win Rate:          {result.win_rate:.1f}%")
    print(f"  Total P&L:         ${result.total_pnl:,.2f}")
    print(f"  Avg P&L per Trade: ${result.avg_pnl:.2f}")
    print(f"  Sharpe Ratio:      {result.sharpe_ratio:.2f}")
    print(f"  Max Drawdown:      {result.max_drawdown:.1f}%")
    print(f"  Active Symbols:    {result.active_symbols}")
    print(f"  Filtered Symbols:  {result.filtered_symbols}")

    if result.trades_by_vix:
        print(f"\n  VIX REGIME PERFORMANCE:")
        print(f"  {'─'*50}")
        print(f"  {'Regime':<12} {'Trades':>8} {'WR':>8} {'Avg P&L':>10}")
        print(f"  {'─'*50}")
        for regime in ["low", "normal", "elevated", "high"]:
            if regime in result.trades_by_vix:
                r = result.trades_by_vix[regime]
                print(
                    f"  {regime:<12} {r['trades']:>8} {r['win_rate']:>7.1f}% ${r['avg_pnl']:>8.2f}"
                )

    if detailed and result.trades_by_year:
        print(f"\n  YEARLY PERFORMANCE:")
        print(f"  {'─'*50}")
        print(f"  {'Year':<8} {'Trades':>8} {'WR':>8} {'Avg P&L':>10} {'Total P&L':>12}")
        print(f"  {'─'*50}")
        for year in sorted(result.trades_by_year.keys()):
            y = result.trades_by_year[year]
            print(
                f"  {year:<8} {y['trades']:>8} {y['win_rate']:>7.1f}% ${y['avg_pnl']:>8.2f} ${y['pnl']:>11,.2f}"
            )


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Full backtest with v3.8.1 weights")
    parser.add_argument(
        "--strategy",
        choices=["pullback", "bounce", "ath_breakout", "earnings_dip"],
        help="Run backtest for specific strategy only",
    )
    parser.add_argument("--detailed", action="store_true", help="Show detailed yearly breakdown")
    args = parser.parse_args()

    strategies = (
        [args.strategy] if args.strategy else ["pullback", "bounce", "ath_breakout", "earnings_dip"]
    )

    print("=" * 70)
    print("  FULL BACKTEST v3.8.1")
    print("=" * 70)

    # Load config
    logger.info("[1/6] Loading configuration...")
    config = load_config()
    print(f"  Config version: {config.get('version', 'unknown')}")

    # Connect to database
    conn = sqlite3.connect(DB_PATH)

    # Load symbols
    logger.info("[2/6] Loading symbols...")
    symbols = load_all_symbols(conn)
    print(f"  Found {len(symbols)} symbols")

    # Load price data
    logger.info("[3/6] Loading price data...")
    all_bars = {}
    for symbol in tqdm(symbols, desc="Loading"):
        bars = load_price_data(conn, symbol)
        if len(bars) >= MIN_BARS_REQUIRED:
            all_bars[symbol] = bars
    print(f"  Loaded {len(all_bars)} symbols with sufficient data")

    # Load SPY for beta calculation
    logger.info("[4/6] Loading SPY data...")
    spy_bars = load_price_data(conn, "SPY")
    spy_closes = [b.close for b in spy_bars[-252:]]
    spy_returns = [
        (spy_closes[i] - spy_closes[i - 1]) / spy_closes[i - 1] for i in range(1, len(spy_closes))
    ]
    print(f"  Loaded {len(spy_bars)} SPY bars")

    # Load VIX
    logger.info("[5/6] Loading VIX data...")
    vix_data = load_vix_data(conn)
    print(f"  Loaded {len(vix_data)} VIX data points")

    # Load earnings
    logger.info("[6/6] Loading earnings data...")
    earnings_data = load_earnings_data(list(all_bars.keys()))
    print(f"  Loaded earnings for {len(earnings_data)} symbols")

    # Calculate metrics for all symbols
    logger.info("Calculating symbol metrics...")
    metrics = {}
    for symbol, bars in tqdm(all_bars.items(), desc="Metrics"):
        m = calculate_metrics(symbol, bars, spy_returns)
        if m:
            metrics[symbol] = m
    print(f"  Calculated metrics for {len(metrics)} symbols")

    conn.close()

    # Run backtests
    results = []
    for strategy in strategies:
        result = run_backtest(
            strategy=strategy,
            all_bars=all_bars,
            vix_data=vix_data,
            earnings_data=earnings_data,
            metrics=metrics,
            config=config,
        )
        results.append(result)
        print_results(result, detailed=args.detailed)

    # Summary comparison
    if len(results) > 1:
        print(f"\n{'='*70}")
        print("  STRATEGY COMPARISON")
        print(f"{'='*70}")
        print(
            f"\n  {'Strategy':<15} {'Trades':>8} {'WR':>8} {'Avg P&L':>10} {'Sharpe':>8} {'Total P&L':>12}"
        )
        print(f"  {'─'*65}")

        for r in results:
            print(
                f"  {r.strategy:<15} {r.total_trades:>8} {r.win_rate:>7.1f}% ${r.avg_pnl:>8.2f} {r.sharpe_ratio:>8.2f} ${r.total_pnl:>11,.2f}"
            )

        # Total
        total_trades = sum(r.total_trades for r in results)
        total_wins = sum(r.wins for r in results)
        total_pnl = sum(r.total_pnl for r in results)
        total_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        print(f"  {'─'*65}")
        print(
            f"  {'TOTAL':<15} {total_trades:>8} {total_wr:>7.1f}% ${avg_pnl:>8.2f} {'':>8} ${total_pnl:>11,.2f}"
        )

    print(f"\n{'='*70}")
    print("  BACKTEST COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
