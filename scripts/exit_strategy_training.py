#!/usr/bin/env python3
"""
Exit Strategy Training - Phase 1
================================
Optimiert Exit-Strategien für Bull-Put-Spreads:
- Profit-Taking Levels (wann Gewinne mitnehmen)
- Stop-Loss Levels (maximaler Verlust)
- Time-based Exits (DTE-basierte Regeln)

Generiert Signale aus historischen Preisdaten und simuliert dann
verschiedene Exit-Strategien.
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from multiprocessing import Pool, cpu_count
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

NUM_WORKERS = 10


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ExitScenario:
    """Ein simuliertes Exit-Szenario"""
    profit_target_pct: float  # % of max profit to take (e.g., 50 = 50%)
    stop_loss_pct: float      # % of spread width to risk (e.g., 100 = 100%)
    dte_exit: int             # Exit at this DTE regardless (0 = hold to expiration)


@dataclass
class SimulatedTrade:
    """Ergebnis einer Trade-Simulation mit bestimmter Exit-Strategie"""
    symbol: str
    entry_date: str
    exit_date: str
    holding_days: int
    entry_price: float        # Stock price at entry
    exit_price: float         # Stock price at exit
    short_strike: float       # Short put strike
    premium_received: float   # Credit received (as % of spread)
    pnl: float               # Profit/Loss (as multiple of premium)
    pnl_pct: float           # P&L as % of max profit
    exit_reason: str         # 'profit_target', 'stop_loss', 'dte_exit', 'expiration'
    win: bool                # True if pnl > 0


@dataclass
class ExitStrategyResult:
    """Ergebnis einer Exit-Strategie über alle Trades"""
    profit_target_pct: float
    stop_loss_pct: float
    dte_exit: int
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_pnl_pct: float
    total_pnl_pct: float
    avg_holding_days: float
    profit_target_exits: int
    stop_loss_exits: int
    dte_exits: int
    expiration_exits: int
    profit_factor: float


# =============================================================================
# EXIT SCENARIOS TO TEST
# =============================================================================

def get_exit_scenarios() -> List[ExitScenario]:
    """
    Generiert alle zu testenden Exit-Szenarien.
    """
    scenarios = []

    # Profit Target Levels: 25% to 100% (hold to expiration)
    profit_targets = [25, 50, 65, 75, 85, 100]

    # Stop Loss Levels: 50% to 200% of max loss
    # 100% = full spread width loss, 200% = 2x (shouldn't happen with spreads)
    stop_losses = [50, 75, 100, 150, 200]

    # DTE Exit: 0 (hold to exp), 7, 14, 21
    dte_exits = [0, 7, 14, 21]

    for pt in profit_targets:
        for sl in stop_losses:
            for dte in dte_exits:
                scenarios.append(ExitScenario(
                    profit_target_pct=pt,
                    stop_loss_pct=sl,
                    dte_exit=dte
                ))

    return scenarios


# =============================================================================
# SIGNAL GENERATION (Simple RSI-based)
# =============================================================================

def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """Calculate RSI for a price series"""
    if len(prices) < period + 1:
        return []

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.zeros(len(deltas))
    avg_loss = np.zeros(len(deltas))

    avg_gain[period-1] = np.mean(gains[:period])
    avg_loss[period-1] = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain[i] = (avg_gain[i-1] * (period-1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i-1] * (period-1) + losses[i]) / period

    rs = np.where(avg_loss != 0, avg_gain / avg_loss, 100)
    rsi = 100 - (100 / (1 + rs))

    return list(rsi[period-1:])


def generate_signals(bars: List[Dict], lookback: int = 200) -> List[Dict]:
    """
    Generate entry signals from price bars.

    Signal criteria:
    - RSI < 35 (oversold)
    - Price above 200 SMA (uptrend)
    """
    if len(bars) < lookback:
        return []

    prices = [b['close'] for b in bars]
    rsi_values = calculate_rsi(prices)

    signals = []

    # Start after we have enough data
    for i in range(lookback, len(bars)):
        bar = bars[i]

        # Calculate SMA200
        sma200 = np.mean(prices[i-200:i])
        current_price = prices[i]

        # RSI index offset
        rsi_idx = i - 14  # RSI starts at index period-1
        if rsi_idx < 0 or rsi_idx >= len(rsi_values):
            continue

        rsi = rsi_values[rsi_idx]

        # Signal criteria: RSI oversold + above SMA200
        if rsi < 35 and current_price > sma200:
            signals.append({
                'date': bar['date'],
                'price': current_price,
                'rsi': rsi,
                'sma200': sma200
            })

    return signals


# =============================================================================
# TRADE SIMULATION
# =============================================================================

def simulate_single_trade(
    signal: Dict,
    bars: List[Dict],
    scenario: ExitScenario,
    dte: int = 30
) -> Optional[SimulatedTrade]:
    """
    Simuliert einen Bull-Put-Spread Trade.

    Bull-Put-Spread:
    - Sell OTM put (short_strike = price * 0.95)
    - Buy further OTM put (long_strike = short_strike - 5)
    - Max profit = premium received
    - Max loss = spread_width - premium

    Exit logic:
    - Profit Target: Close when spread value drops to target % of initial
    - Stop Loss: Close when loss exceeds % of max loss
    - DTE Exit: Close at specific DTE
    - Expiration: Hold to expiration
    """
    entry_date_str = signal['date']
    entry_price = signal['price']

    # Find entry bar index
    bars_by_date = {b['date']: (i, b) for i, b in enumerate(bars)}
    if entry_date_str not in bars_by_date:
        return None

    entry_idx, entry_bar = bars_by_date[entry_date_str]

    # Set up the spread
    spread_width = 5.0  # $5 wide spread
    short_strike = round(entry_price * 0.95 / 5) * 5  # 5% OTM, round to $5
    long_strike = short_strike - spread_width

    # Premium received (simplified: ~30% of spread width for 30 DTE, 5% OTM)
    premium_pct = 0.30  # 30% of spread width
    max_profit_pct = premium_pct  # 30%
    max_loss_pct = 1.0 - premium_pct  # 70%

    # Calculate exit thresholds (as % of spread)
    profit_target_value = premium_pct * (1 - scenario.profit_target_pct / 100)  # Value at which we exit
    stop_loss_value = premium_pct + (max_loss_pct * scenario.stop_loss_pct / 100)  # Max 1.0
    stop_loss_value = min(stop_loss_value, 1.0)

    # Expiration date
    try:
        entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
    except ValueError:
        return None

    expiration_date = entry_date + timedelta(days=dte)

    # Simulate day by day
    exit_date = None
    exit_reason = 'expiration'
    exit_price = entry_price
    current_value = premium_pct  # Start with premium received

    for day_offset in range(1, dte + 1):
        current_date = entry_date + timedelta(days=day_offset)
        current_date_str = current_date.isoformat()
        days_remaining = dte - day_offset

        if current_date_str not in bars_by_date:
            continue

        _, bar = bars_by_date[current_date_str]
        current_stock_price = bar['close']

        # Simplified spread value model
        # Value increases as price approaches/goes below short strike
        # Value decreases with time (theta decay)

        moneyness = (short_strike - current_stock_price) / spread_width
        time_factor = days_remaining / dte

        if current_stock_price >= short_strike:
            # OTM (good) - value decays
            current_value = premium_pct * time_factor * 0.8  # Theta decay
        elif current_stock_price <= long_strike:
            # Deep ITM (bad) - max loss
            current_value = 1.0
        else:
            # ITM (bad) - somewhere between
            intrinsic = (short_strike - current_stock_price) / spread_width
            time_value = premium_pct * time_factor * 0.5
            current_value = intrinsic + time_value

        current_value = max(0, min(current_value, 1.0))

        # Check exit conditions

        # 1. DTE Exit
        if scenario.dte_exit > 0 and days_remaining <= scenario.dte_exit:
            exit_date = current_date
            exit_price = current_stock_price
            exit_reason = 'dte_exit'
            break

        # 2. Profit Target (value dropped to target)
        if current_value <= profit_target_value:
            exit_date = current_date
            exit_price = current_stock_price
            exit_reason = 'profit_target'
            break

        # 3. Stop Loss (value increased to max acceptable loss)
        if current_value >= stop_loss_value:
            exit_date = current_date
            exit_price = current_stock_price
            exit_reason = 'stop_loss'
            break

    # If no exit, hold to expiration
    if exit_date is None:
        exit_date = expiration_date
        exp_date_str = expiration_date.isoformat()
        if exp_date_str in bars_by_date:
            _, exp_bar = bars_by_date[exp_date_str]
            exit_price = exp_bar['close']

        # Expiration value
        if exit_price >= short_strike:
            current_value = 0  # Worthless = max profit
        elif exit_price <= long_strike:
            current_value = 1.0  # Max loss
        else:
            current_value = (short_strike - exit_price) / spread_width

    # Calculate P&L
    pnl = premium_pct - current_value  # Positive = profit
    pnl_pct = (pnl / premium_pct) * 100 if premium_pct > 0 else 0  # As % of max profit
    holding_days = (exit_date - entry_date).days

    return SimulatedTrade(
        symbol='',  # Will be set by caller
        entry_date=entry_date_str,
        exit_date=exit_date.isoformat(),
        holding_days=holding_days,
        entry_price=entry_price,
        exit_price=exit_price,
        short_strike=short_strike,
        premium_received=premium_pct,
        pnl=pnl,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
        win=pnl > 0
    )


# =============================================================================
# WORKER FUNCTION
# =============================================================================

def analyze_symbol(args: Tuple) -> Dict[str, Any]:
    """Worker function: analyze one symbol with all exit scenarios"""
    symbol, bars, scenarios = args

    results = {
        'symbol': symbol,
        'signals': 0,
        'scenario_results': []
    }

    if not bars or len(bars) < 250:
        return results

    # Generate signals
    signals = generate_signals(bars)
    results['signals'] = len(signals)

    if not signals:
        return results

    # Test each scenario
    for scenario in scenarios:
        trades = []

        for signal in signals:
            trade = simulate_single_trade(signal, bars, scenario)
            if trade:
                trade.symbol = symbol
                trades.append(trade)

        if trades:
            wins = [t for t in trades if t.win]
            losses = [t for t in trades if not t.win]

            total_profit = sum(t.pnl for t in wins)
            total_loss = abs(sum(t.pnl for t in losses))

            results['scenario_results'].append({
                'scenario': asdict(scenario),
                'trades': len(trades),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': len(wins) / len(trades) * 100,
                'avg_pnl_pct': np.mean([t.pnl_pct for t in trades]),
                'total_pnl_pct': sum(t.pnl_pct for t in trades),
                'avg_holding_days': np.mean([t.holding_days for t in trades]),
                'profit_target_exits': len([t for t in trades if t.exit_reason == 'profit_target']),
                'stop_loss_exits': len([t for t in trades if t.exit_reason == 'stop_loss']),
                'dte_exits': len([t for t in trades if t.exit_reason == 'dte_exit']),
                'expiration_exits': len([t for t in trades if t.exit_reason == 'expiration']),
                'profit_factor': total_profit / total_loss if total_loss > 0 else float('inf'),
            })

    return results


# =============================================================================
# AGGREGATION & REPORTING
# =============================================================================

def aggregate_results(symbol_results: List[Dict]) -> List[ExitStrategyResult]:
    """Aggregate results across all symbols"""

    scenario_data = defaultdict(lambda: {
        'trades': 0, 'wins': 0, 'losses': 0,
        'total_pnl_pct': 0, 'total_holding_days': 0,
        'profit_target_exits': 0, 'stop_loss_exits': 0,
        'dte_exits': 0, 'expiration_exits': 0,
        'total_profit': 0, 'total_loss': 0
    })

    for result in symbol_results:
        for sr in result.get('scenario_results', []):
            key = json.dumps(sr['scenario'], sort_keys=True)
            data = scenario_data[key]

            data['trades'] += sr['trades']
            data['wins'] += sr['wins']
            data['losses'] += sr['losses']
            data['total_pnl_pct'] += sr['total_pnl_pct']
            data['total_holding_days'] += sr['avg_holding_days'] * sr['trades']
            data['profit_target_exits'] += sr['profit_target_exits']
            data['stop_loss_exits'] += sr['stop_loss_exits']
            data['dte_exits'] += sr['dte_exits']
            data['expiration_exits'] += sr['expiration_exits']

            # For profit factor
            if sr['total_pnl_pct'] > 0:
                data['total_profit'] += sr['total_pnl_pct']
            else:
                data['total_loss'] += abs(sr['total_pnl_pct'])

    # Convert to ExitStrategyResult
    results = []
    for key, data in scenario_data.items():
        if data['trades'] == 0:
            continue

        scenario = json.loads(key)

        results.append(ExitStrategyResult(
            profit_target_pct=scenario['profit_target_pct'],
            stop_loss_pct=scenario['stop_loss_pct'],
            dte_exit=scenario['dte_exit'],
            total_trades=data['trades'],
            wins=data['wins'],
            losses=data['losses'],
            win_rate=data['wins'] / data['trades'] * 100,
            avg_pnl_pct=data['total_pnl_pct'] / data['trades'],
            total_pnl_pct=data['total_pnl_pct'],
            avg_holding_days=data['total_holding_days'] / data['trades'],
            profit_target_exits=data['profit_target_exits'],
            stop_loss_exits=data['stop_loss_exits'],
            dte_exits=data['dte_exits'],
            expiration_exits=data['expiration_exits'],
            profit_factor=data['total_profit'] / data['total_loss'] if data['total_loss'] > 0 else 999
        ))

    return results


def print_results(results: List[ExitStrategyResult]):
    """Print results in formatted tables"""

    # Sort by different metrics
    by_pnl = sorted(results, key=lambda x: x.total_pnl_pct, reverse=True)
    by_winrate = sorted(results, key=lambda x: x.win_rate, reverse=True)
    by_pf = sorted(results, key=lambda x: min(x.profit_factor, 100), reverse=True)

    print("\n" + "=" * 90)
    print("TOP 15 EXIT STRATEGIES BY TOTAL P&L")
    print("=" * 90)
    print(f"{'Rank':<5} {'PT%':<6} {'SL%':<6} {'DTE':<5} {'Trades':<8} {'WinRate':<9} {'AvgPnL%':<10} {'TotalPnL%':<12} {'PF':<8}")
    print("-" * 90)

    for i, r in enumerate(by_pnl[:15], 1):
        pf = min(r.profit_factor, 999)
        print(f"{i:<5} {r.profit_target_pct:<6.0f} {r.stop_loss_pct:<6.0f} {r.dte_exit:<5} "
              f"{r.total_trades:<8} {r.win_rate:<9.1f} {r.avg_pnl_pct:<10.1f} "
              f"{r.total_pnl_pct:<12,.0f} {pf:<8.2f}")

    print("\n" + "=" * 90)
    print("TOP 15 EXIT STRATEGIES BY WIN RATE")
    print("=" * 90)
    print(f"{'Rank':<5} {'PT%':<6} {'SL%':<6} {'DTE':<5} {'Trades':<8} {'WinRate':<9} {'AvgPnL%':<10} {'AvgDays':<8} {'PF':<8}")
    print("-" * 90)

    for i, r in enumerate(by_winrate[:15], 1):
        pf = min(r.profit_factor, 999)
        print(f"{i:<5} {r.profit_target_pct:<6.0f} {r.stop_loss_pct:<6.0f} {r.dte_exit:<5} "
              f"{r.total_trades:<8} {r.win_rate:<9.1f} {r.avg_pnl_pct:<10.1f} "
              f"{r.avg_holding_days:<8.1f} {pf:<8.2f}")

    print("\n" + "=" * 90)
    print("TOP 15 EXIT STRATEGIES BY PROFIT FACTOR")
    print("=" * 90)
    print(f"{'Rank':<5} {'PT%':<6} {'SL%':<6} {'DTE':<5} {'Trades':<8} {'WinRate':<9} {'TotalPnL%':<12} {'PF':<8}")
    print("-" * 90)

    for i, r in enumerate(by_pf[:15], 1):
        pf = min(r.profit_factor, 999)
        print(f"{i:<5} {r.profit_target_pct:<6.0f} {r.stop_loss_pct:<6.0f} {r.dte_exit:<5} "
              f"{r.total_trades:<8} {r.win_rate:<9.1f} {r.total_pnl_pct:<12,.0f} {pf:<8.2f}")

    # Exit reason analysis
    print("\n" + "=" * 90)
    print("EXIT REASON ANALYSIS (for top strategies by P&L)")
    print("=" * 90)
    print(f"{'PT%':<6} {'SL%':<6} {'DTE':<5} {'Target%':<9} {'StopLoss%':<11} {'DTE%':<8} {'Expiry%':<8}")
    print("-" * 90)

    for r in by_pnl[:10]:
        total = r.total_trades
        if total > 0:
            print(f"{r.profit_target_pct:<6.0f} {r.stop_loss_pct:<6.0f} {r.dte_exit:<5} "
                  f"{r.profit_target_exits/total*100:<9.1f} {r.stop_loss_exits/total*100:<11.1f} "
                  f"{r.dte_exits/total*100:<8.1f} {r.expiration_exits/total*100:<8.1f}")


def save_results(results: List[ExitStrategyResult], output_path: Path):
    """Save results to JSON"""

    results_list = [asdict(r) for r in results]
    results_list.sort(key=lambda x: x['total_pnl_pct'], reverse=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    best_by_pnl = results_list[0] if results_list else None
    best_by_wr = max(results_list, key=lambda x: x['win_rate']) if results_list else None
    best_by_pf = max(results_list, key=lambda x: min(x['profit_factor'], 100)) if results_list else None

    with open(output_path, 'w') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'total_scenarios_tested': len(results_list),
            'recommendations': {
                'best_by_total_pnl': best_by_pnl,
                'best_by_win_rate': best_by_wr,
                'best_by_profit_factor': best_by_pf
            },
            'all_results': results_list
        }, f, indent=2)

    logger.info(f"Results saved to {output_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    logger.info("=" * 70)
    logger.info("  EXIT STRATEGY TRAINING - Phase 1")
    logger.info("  Workers: %d / %d cores", NUM_WORKERS, cpu_count())
    logger.info("  Started: %s", datetime.now())
    logger.info("=" * 70)

    # Load data
    tracker = TradeTracker()

    # Get symbols with price data
    symbol_list = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_list if not s['symbol'].startswith('^')]
    logger.info("  Symbols with price data: %d", len(symbols))

    # Get exit scenarios
    scenarios = get_exit_scenarios()
    logger.info("  Exit scenarios to test: %d", len(scenarios))

    # Prepare worker arguments
    worker_args = []
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            bars = [
                {
                    'date': b.date.isoformat() if hasattr(b.date, 'isoformat') else str(b.date),
                    'open': b.open,
                    'high': b.high,
                    'low': b.low,
                    'close': b.close,
                    'volume': b.volume
                }
                for b in price_data.bars
            ]
            if len(bars) >= 250:
                worker_args.append((symbol, bars, scenarios))

    logger.info("  Symbols to analyze: %d", len(worker_args))
    logger.info("=" * 70)

    # Run analysis
    logger.info("\nAnalyzing exit strategies...")

    all_results = []
    with Pool(NUM_WORKERS) as pool:
        for result in pool.imap_unordered(analyze_symbol, worker_args):
            all_results.append(result)
            if len(all_results) % 50 == 0:
                logger.info(f"  Processed {len(all_results)}/{len(worker_args)} symbols...")

    logger.info(f"  Completed: {len(all_results)} symbols")

    total_signals = sum(r['signals'] for r in all_results)
    logger.info(f"  Total signals generated: {total_signals}")

    # Aggregate results
    logger.info("\nAggregating results...")
    aggregated = aggregate_results(all_results)
    logger.info(f"  Aggregated {len(aggregated)} exit strategies")

    # Print results
    print_results(aggregated)

    # Save results
    output_path = Path.home() / '.optionplay' / 'models' / 'EXIT_STRATEGY_RESULTS.json'
    save_results(aggregated, output_path)

    # Print recommendations
    by_pnl = sorted(aggregated, key=lambda x: x.total_pnl_pct, reverse=True)
    by_wr = sorted(aggregated, key=lambda x: x.win_rate, reverse=True)

    print("\n" + "=" * 90)
    print("RECOMMENDATIONS")
    print("=" * 90)

    if by_pnl:
        best = by_pnl[0]
        print(f"\n✓ BEST EXIT STRATEGY (by Total P&L):")
        print(f"  • Profit Target: {best.profit_target_pct}% of max profit")
        print(f"  • Stop Loss: {best.stop_loss_pct}% of max loss")
        print(f"  • DTE Exit: {best.dte_exit} days before expiration" if best.dte_exit > 0 else "  • Hold to expiration")
        print(f"\n  Results over {best.total_trades:,} trades:")
        print(f"  • Win Rate: {best.win_rate:.1f}%")
        print(f"  • Avg P&L: {best.avg_pnl_pct:.1f}% of max profit")
        print(f"  • Avg Holding Days: {best.avg_holding_days:.1f}")
        print(f"  • Profit Factor: {min(best.profit_factor, 999):.2f}")

    if by_wr and by_wr[0] != by_pnl[0]:
        best_wr = by_wr[0]
        print(f"\n✓ HIGHEST WIN RATE STRATEGY:")
        print(f"  • Profit Target: {best_wr.profit_target_pct}%")
        print(f"  • Stop Loss: {best_wr.stop_loss_pct}%")
        print(f"  • Win Rate: {best_wr.win_rate:.1f}%")

    logger.info("\n" + "=" * 70)
    logger.info("  EXIT STRATEGY TRAINING COMPLETE")
    logger.info("  Finished: %s", datetime.now())
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
