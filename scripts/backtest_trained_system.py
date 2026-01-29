#!/usr/bin/env python3
"""
Comprehensive Backtest of Trained System
=========================================
Tests the full trained system including:
- Exit Strategy (PT=75%, SL=100%, DTE=7)
- Symbol Clustering
- Ensemble Strategy Selection

Compares trained system vs baseline (equal weights, no clustering).
Uses walk-forward approach: train on first 70%, test on last 30%.
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import numpy as np

# Setup paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from backtesting.trade_tracker import TradeTracker

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# TRAINED PARAMETERS
# =============================================================================

# Exit Strategy (from training)
EXIT_STRATEGY = {
    'profit_target_pct': 75,  # Close at 75% of max profit
    'stop_loss_pct': 100,     # Close at 100% of max loss (full spread)
    'dte_exit': 7,            # Close at 7 DTE
}

# Baseline (no exit management)
BASELINE_EXIT = {
    'profit_target_pct': 100,  # Hold to expiration
    'stop_loss_pct': 200,      # No stop loss
    'dte_exit': 0,
}

# Load cluster data
def load_cluster_data() -> Dict:
    """Load symbol cluster mappings"""
    cluster_path = Path.home() / '.optionplay' / 'models' / 'SYMBOL_CLUSTERS.json'
    if cluster_path.exists():
        with open(cluster_path, 'r') as f:
            data = json.load(f)
            return data.get('symbol_to_cluster', {})
    return {}

# Load ensemble data
def load_ensemble_data() -> Dict:
    """Load ensemble symbol preferences"""
    ensemble_path = Path.home() / '.optionplay' / 'models' / 'ENSEMBLE_V2_TRAINED.json'
    if ensemble_path.exists():
        with open(ensemble_path, 'r') as f:
            return json.load(f)
    return {}


# =============================================================================
# STRATEGY SIGNALS
# =============================================================================

def calculate_rsi(prices: np.ndarray, period: int = 14) -> float:
    """Calculate RSI"""
    if len(prices) < period + 1:
        return 50
    deltas = np.diff(prices[-period-1:])
    gains = np.maximum(deltas, 0)
    losses = np.maximum(-deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_strategy_signal(
    strategy: str,
    prices: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    idx: int,
) -> Tuple[bool, float]:
    """
    Check if strategy generates signal at index.
    Returns (has_signal, score)
    """
    if idx < 252:
        return False, 0

    current_price = prices[idx]
    rsi = calculate_rsi(prices[:idx+1])
    sma20 = np.mean(prices[idx-19:idx+1])
    sma50 = np.mean(prices[idx-49:idx+1])
    sma200 = np.mean(prices[idx-199:idx+1])
    high_52w = np.max(prices[max(0,idx-251):idx+1])
    low_20d = np.min(lows[idx-19:idx+1])

    score = 0

    if strategy == 'pullback':
        # RSI < 40, above SMA200, below SMA20
        if rsi < 40 and current_price > sma200 and current_price < sma20:
            score = 3.0 if rsi < 30 else 2.0 if rsi < 35 else 1.0
            # Support proximity
            if current_price > sma200 * 0.97:
                score += 1.5
            # Trend strength
            if sma20 > sma50 > sma200:
                score += 1.0
            return score >= 4.0, score

    elif strategy == 'bounce':
        # Near support (within 3% of 20-day low), above SMA200
        support_dist = (current_price - low_20d) / low_20d * 100
        if support_dist < 3 and current_price > sma200:
            score = 2.5 if support_dist < 1 else 1.5
            # RSI confirmation
            if rsi < 35:
                score += 2.0
            elif rsi < 45:
                score += 1.0
            # Volume (simplified - assume moderate)
            score += 0.5
            return score >= 4.0, score

    elif strategy == 'ath_breakout':
        # Within 5% of 52-week high, above all MAs
        ath_dist = (high_52w - current_price) / high_52w * 100
        if ath_dist < 5 and current_price > sma20 > sma50:
            score = 3.0 if ath_dist < 2 else 2.0 if ath_dist < 3 else 1.0
            # Volume confirmation (simplified)
            score += 1.0
            # Momentum
            if current_price > sma20:
                score += 1.0
            return score >= 5.0, score

    elif strategy == 'earnings_dip':
        # 5-15% below recent high, above SMA200
        recent_high = np.max(prices[max(0,idx-20):idx+1])
        drop_pct = (recent_high - current_price) / recent_high * 100
        if 5 <= drop_pct <= 15 and current_price > sma200:
            score = 3.0 if 8 <= drop_pct <= 12 else 2.0
            # Quality (trend)
            if sma50 > sma200:
                score += 1.5
            # Recovery signs
            if prices[idx] > prices[idx-1]:
                score += 1.0
            return score >= 5.0, score

    return False, 0


def select_best_strategy(
    symbol: str,
    prices: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    idx: int,
    cluster_data: Dict,
    use_trained: bool = True,
) -> Optional[Tuple[str, float]]:
    """
    Select best strategy for symbol at index.
    Returns (strategy, score) or None if no signal.
    """
    strategies = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']

    # Get signals for all strategies
    signals = {}
    for strat in strategies:
        has_signal, score = get_strategy_signal(strat, prices, highs, lows, idx)
        if has_signal:
            signals[strat] = score

    if not signals:
        return None

    if use_trained and symbol in cluster_data:
        # Use cluster-based selection
        cluster_info = cluster_data[symbol]
        best_strat = cluster_info.get('best_strategy')
        cluster_wr = cluster_info.get('strategy_win_rate', 50)

        # If cluster's best strategy has signal and good win rate, use it
        if best_strat in signals and cluster_wr >= 60:
            return best_strat, signals[best_strat]

    # Fallback to highest score
    best = max(signals, key=signals.get)
    return best, signals[best]


# =============================================================================
# TRADE SIMULATION
# =============================================================================

@dataclass
class Trade:
    """Represents a single trade"""
    symbol: str
    strategy: str
    entry_date: date
    entry_price: float
    short_strike: float
    long_strike: float
    spread_width: float
    premium: float
    max_profit: float
    max_loss: float
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0
    pnl_pct: float = 0
    is_win: bool = False


def simulate_trade(
    prices: np.ndarray,
    entry_idx: int,
    entry_price: float,
    exit_params: Dict,
    dte: int = 45,
) -> Tuple[float, str, int]:
    """
    Simulate trade with exit strategy.

    Returns:
        (pnl_pct, exit_reason, days_held)
    """
    # Setup spread
    short_strike = entry_price * 0.95  # 5% OTM
    spread_width = 5.0
    long_strike = short_strike - spread_width

    # Premium received (simplified: ~30% of spread width for -0.20 delta)
    premium = spread_width * 0.30
    max_profit = premium
    max_loss = spread_width - premium

    # Exit parameters
    profit_target = max_profit * (exit_params['profit_target_pct'] / 100)
    stop_loss = max_loss * (exit_params['stop_loss_pct'] / 100)
    dte_exit = exit_params['dte_exit']

    n = len(prices)
    exit_idx = min(entry_idx + dte, n - 1)

    # Simulate daily
    for day in range(1, dte + 1):
        idx = entry_idx + day
        if idx >= n:
            break

        current_price = prices[idx]
        days_remaining = dte - day

        # Calculate current P&L (simplified)
        if current_price >= short_strike:
            # OTM - profitable
            # Estimate profit based on time decay
            time_factor = 1 - (days_remaining / dte)
            current_pnl = premium * time_factor
        else:
            # ITM - losing
            intrinsic = short_strike - current_price
            current_pnl = premium - min(intrinsic, spread_width)

        # Check profit target
        if current_pnl >= profit_target:
            return (current_pnl / max_loss) * 100, "profit_target", day

        # Check stop loss
        if current_pnl <= -stop_loss:
            return (current_pnl / max_loss) * 100, "stop_loss", day

        # Check DTE exit
        if dte_exit > 0 and days_remaining <= dte_exit:
            return (current_pnl / max_loss) * 100, "dte_exit", day

    # Expiration
    final_price = prices[min(entry_idx + dte, n - 1)]
    if final_price >= short_strike:
        return (premium / max_loss) * 100, "expiration_win", dte
    else:
        intrinsic = short_strike - final_price
        final_pnl = premium - min(intrinsic, spread_width)
        return (final_pnl / max_loss) * 100, "expiration_loss", dte


# =============================================================================
# BACKTEST ENGINE
# =============================================================================

@dataclass
class BacktestResults:
    """Backtest results summary"""
    name: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl_pct: float
    avg_pnl_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float

    # By strategy breakdown
    strategy_results: Dict[str, Dict]

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': round(self.win_rate, 2),
            'total_pnl_pct': round(self.total_pnl_pct, 2),
            'avg_pnl_pct': round(self.avg_pnl_pct, 2),
            'avg_win_pct': round(self.avg_win_pct, 2),
            'avg_loss_pct': round(self.avg_loss_pct, 2),
            'profit_factor': round(self.profit_factor, 2),
            'strategy_results': self.strategy_results,
        }


def run_backtest(
    symbol_data: Dict[str, Dict],
    cluster_data: Dict,
    exit_params: Dict,
    use_trained: bool = True,
    test_start_pct: float = 0.7,  # Use last 30% for testing
    name: str = "Backtest",
) -> BacktestResults:
    """
    Run backtest on symbol data.

    Args:
        symbol_data: Dict of symbol -> {prices, highs, lows}
        cluster_data: Symbol cluster mappings
        exit_params: Exit strategy parameters
        use_trained: Use trained system vs baseline
        test_start_pct: Start testing at this percentage of data
        name: Name for this backtest

    Returns:
        BacktestResults
    """
    all_trades = []
    strategy_trades = defaultdict(list)

    for symbol, data in symbol_data.items():
        prices = data['prices']
        highs = data['highs']
        lows = data['lows']

        n = len(prices)
        if n < 300:
            continue

        # Test period: last 30% of data
        test_start = int(n * test_start_pct)

        # Scan for signals every 5 days
        i = test_start
        while i < n - 50:  # Need 50 days for trade
            result = select_best_strategy(
                symbol, prices, highs, lows, i, cluster_data, use_trained
            )

            if result:
                strategy, score = result
                entry_price = prices[i]

                # Simulate trade
                pnl_pct, exit_reason, days_held = simulate_trade(
                    prices, i, entry_price, exit_params, dte=45
                )

                trade = {
                    'symbol': symbol,
                    'strategy': strategy,
                    'score': score,
                    'entry_price': entry_price,
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason,
                    'days_held': days_held,
                    'is_win': pnl_pct > 0,
                }

                all_trades.append(trade)
                strategy_trades[strategy].append(trade)

                # Skip ahead to avoid overlapping trades
                i += 30
            else:
                i += 5

    # Calculate results
    if not all_trades:
        return BacktestResults(
            name=name,
            total_trades=0, wins=0, losses=0, win_rate=0,
            total_pnl_pct=0, avg_pnl_pct=0, avg_win_pct=0, avg_loss_pct=0,
            profit_factor=0, max_drawdown_pct=0, sharpe_ratio=0,
            strategy_results={},
        )

    wins = [t for t in all_trades if t['is_win']]
    losses = [t for t in all_trades if not t['is_win']]

    total_pnl = sum(t['pnl_pct'] for t in all_trades)
    avg_pnl = total_pnl / len(all_trades)
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0

    gross_profit = sum(t['pnl_pct'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl_pct'] for t in losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Max drawdown (simplified)
    running_pnl = np.cumsum([t['pnl_pct'] for t in all_trades])
    peak = np.maximum.accumulate(running_pnl)
    drawdown = peak - running_pnl
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0

    # Sharpe (simplified)
    pnls = [t['pnl_pct'] for t in all_trades]
    sharpe = np.mean(pnls) / np.std(pnls) if np.std(pnls) > 0 else 0

    # Strategy breakdown
    strategy_results = {}
    for strat, trades in strategy_trades.items():
        strat_wins = [t for t in trades if t['is_win']]
        strategy_results[strat] = {
            'trades': len(trades),
            'wins': len(strat_wins),
            'win_rate': len(strat_wins) / len(trades) * 100 if trades else 0,
            'total_pnl': sum(t['pnl_pct'] for t in trades),
            'avg_pnl': np.mean([t['pnl_pct'] for t in trades]) if trades else 0,
        }

    return BacktestResults(
        name=name,
        total_trades=len(all_trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / len(all_trades) * 100,
        total_pnl_pct=total_pnl,
        avg_pnl_pct=avg_pnl,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd,
        sharpe_ratio=sharpe,
        strategy_results=strategy_results,
    )


# =============================================================================
# MAIN
# =============================================================================

def main():
    logger.info("=" * 70)
    logger.info("  COMPREHENSIVE BACKTEST - Trained System vs Baseline")
    logger.info("  Started: %s", datetime.now())
    logger.info("=" * 70)

    # Load data
    tracker = TradeTracker()

    symbol_list = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_list if not s['symbol'].startswith('^')]
    logger.info("  Symbols available: %d", len(symbols))

    # Load trained models
    cluster_data = load_cluster_data()
    logger.info("  Cluster data loaded: %d symbols", len(cluster_data))

    # Prepare symbol data
    symbol_data = {}
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars and len(price_data.bars) >= 300:
            symbol_data[symbol] = {
                'prices': np.array([b.close for b in price_data.bars]),
                'highs': np.array([b.high for b in price_data.bars]),
                'lows': np.array([b.low for b in price_data.bars]),
            }

    logger.info("  Symbols with sufficient data: %d", len(symbol_data))
    logger.info("=" * 70)

    # Run backtests
    logger.info("\nRunning Baseline Backtest (no exit management, no clustering)...")
    baseline_results = run_backtest(
        symbol_data, cluster_data,
        exit_params=BASELINE_EXIT,
        use_trained=False,
        name="Baseline"
    )

    logger.info("Running Trained System Backtest...")
    trained_results = run_backtest(
        symbol_data, cluster_data,
        exit_params=EXIT_STRATEGY,
        use_trained=True,
        name="Trained System"
    )

    # Print comparison
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS COMPARISON")
    print("=" * 80)
    print(f"Test Period: Last 30% of data (out-of-sample)")
    print()

    print(f"{'Metric':<25} {'Baseline':>15} {'Trained':>15} {'Improvement':>15}")
    print("-" * 80)

    metrics = [
        ('Total Trades', baseline_results.total_trades, trained_results.total_trades),
        ('Win Rate (%)', baseline_results.win_rate, trained_results.win_rate),
        ('Avg P&L (%)', baseline_results.avg_pnl_pct, trained_results.avg_pnl_pct),
        ('Total P&L (%)', baseline_results.total_pnl_pct, trained_results.total_pnl_pct),
        ('Avg Win (%)', baseline_results.avg_win_pct, trained_results.avg_win_pct),
        ('Avg Loss (%)', baseline_results.avg_loss_pct, trained_results.avg_loss_pct),
        ('Profit Factor', baseline_results.profit_factor, trained_results.profit_factor),
        ('Max Drawdown (%)', baseline_results.max_drawdown_pct, trained_results.max_drawdown_pct),
        ('Sharpe Ratio', baseline_results.sharpe_ratio, trained_results.sharpe_ratio),
    ]

    for name, baseline_val, trained_val in metrics:
        if isinstance(baseline_val, float):
            if baseline_val != 0:
                improvement = ((trained_val - baseline_val) / abs(baseline_val)) * 100
                imp_str = f"{improvement:+.1f}%"
            else:
                imp_str = "N/A"
            print(f"{name:<25} {baseline_val:>15.2f} {trained_val:>15.2f} {imp_str:>15}")
        else:
            print(f"{name:<25} {baseline_val:>15} {trained_val:>15}")

    # Strategy breakdown
    print("\n" + "=" * 80)
    print("STRATEGY BREAKDOWN - TRAINED SYSTEM")
    print("=" * 80)
    print(f"{'Strategy':<15} {'Trades':>10} {'WinRate':>10} {'AvgP&L':>10} {'TotalP&L':>12}")
    print("-" * 60)

    for strat, data in sorted(trained_results.strategy_results.items(),
                               key=lambda x: x[1]['win_rate'], reverse=True):
        print(f"{strat:<15} {data['trades']:>10} {data['win_rate']:>10.1f}% "
              f"{data['avg_pnl']:>10.2f}% {data['total_pnl']:>12.1f}%")

    # Save results
    output_path = Path.home() / '.optionplay' / 'models' / 'BACKTEST_RESULTS.json'
    with open(output_path, 'w') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'baseline': baseline_results.to_dict(),
            'trained': trained_results.to_dict(),
            'improvement': {
                'win_rate_delta': trained_results.win_rate - baseline_results.win_rate,
                'avg_pnl_delta': trained_results.avg_pnl_pct - baseline_results.avg_pnl_pct,
                'profit_factor_delta': trained_results.profit_factor - baseline_results.profit_factor,
            }
        }, f, indent=2)

    logger.info(f"\nResults saved to {output_path}")

    logger.info("\n" + "=" * 70)
    logger.info("  BACKTEST COMPLETE")
    logger.info("  Finished: %s", datetime.now())
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
