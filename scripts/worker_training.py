#!/usr/bin/env python3
"""
OptionPlay - Worker Training Script
===================================

This script runs on the remote worker machine (larss-macbook-pro-2.local).
It processes assigned symbols and returns results to the master.

Usage:
    python3 scripts/worker_training.py --symbols '["AAPL","MSFT"]' --data-file training_data.json
"""

import json
import sys
import warnings
import multiprocessing as mp
from multiprocessing import Pool
from pathlib import Path
from datetime import date
from typing import Dict, List, Any, Tuple
from collections import defaultdict
import argparse

if sys.platform == 'darwin':
    try:
        mp.set_start_method('fork', force=True)
    except RuntimeError:
        pass

warnings.filterwarnings('ignore')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']
VIX_REGIMES = {'low': (0, 15), 'normal': (15, 20), 'elevated': (20, 30), 'high': (30, 100)}
NUM_WORKERS = 12  # Worker has 14 cores, use 12

# Delta-based strike selection (from strategies.yaml)
SHORT_DELTA_TARGET = -0.20  # Delta für Short Put
LONG_DELTA_TARGET = -0.05   # Delta für Long Put
DTE_MIN = 60
DTE_MAX = 90
HOLDING_DAYS = 75  # Mittlerer Wert zwischen 60-90 DTE


def get_regime(vix: float) -> str:
    for regime, (low, high) in VIX_REGIMES.items():
        if low <= vix < high:
            return regime
    return 'high'


def create_analyzer(strategy: str):
    from src.config.config_loader import PullbackScoringConfig
    from src.analyzers.pullback import PullbackAnalyzer
    from src.analyzers.bounce import BounceAnalyzer, BounceConfig
    from src.analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
    from src.analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig

    if strategy == 'pullback':
        return PullbackAnalyzer(PullbackScoringConfig())
    elif strategy == 'bounce':
        return BounceAnalyzer(BounceConfig())
    elif strategy == 'ath_breakout':
        return ATHBreakoutAnalyzer(ATHBreakoutConfig())
    elif strategy == 'earnings_dip':
        return EarningsDipAnalyzer(EarningsDipConfig())
    raise ValueError(f"Unknown strategy: {strategy}")


def norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal."""
    import math
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def black_scholes_put_simple(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Simplified Black-Scholes Put price calculation."""
    import numpy as np
    if T <= 0 or sigma <= 0:
        return max(K - S, 0)

    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    put_price = K * np.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    return max(put_price, 0)


def black_scholes_delta_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate Put Delta."""
    import numpy as np
    if T <= 0 or sigma <= 0:
        return -1.0 if K > S else 0.0

    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    return norm_cdf(d1) - 1.0  # Put delta is N(d1) - 1


def find_strike_for_delta_simple(
    target_delta: float,
    S: float,
    T: float,
    sigma: float,
    r: float = 0.05
) -> float:
    """
    Find strike for a target Put delta using bisection.

    For puts: higher strike → more negative delta, lower strike → less negative delta.
    """
    # Search range: 70% to 110% of stock price
    low_strike = S * 0.70
    high_strike = S * 1.10

    for _ in range(50):  # Max iterations
        mid_strike = (low_strike + high_strike) / 2
        current_delta = black_scholes_delta_put(S, mid_strike, T, r, sigma)

        if abs(current_delta - target_delta) < 0.001:
            # Round to standard strike increments
            if S < 30:
                return round(mid_strike * 2) / 2  # $0.50 increments
            elif S < 100:
                return round(mid_strike)  # $1 increments
            else:
                return round(mid_strike / 5) * 5  # $5 increments

        # For puts: if delta too negative, lower the strike
        if current_delta < target_delta:
            high_strike = mid_strike
        else:
            low_strike = mid_strike

    return mid_strike


def simulate_trade(
    entry_price: float,
    future_bars: List[Dict],
    holding_days: int = HOLDING_DAYS,
    historical_volatility: float = 0.25,
    enable_rolls: bool = True,
    max_rolls: int = 2
) -> Tuple[int, float]:
    """
    Simulate Bull-Put-Spread with delta-based strike selection and roll management.

    Uses Black-Scholes to find strikes based on target deltas:
    - Short Put: Delta -0.20 (higher premium, closer to money)
    - Long Put:  Delta -0.05 (protection, farther OTM)

    Roll Logic:
    - Roll Down: When price approaches short strike (within 2%), roll to lower strikes
    - Roll Out: When DTE < 21 and position is under pressure, extend expiration
    - Roll Down and Out: Combine both when situation is critical
    - Max 2 rolls per trade to limit chasing losses

    Args:
        entry_price: Current stock price at entry
        future_bars: Future price bars for simulation
        holding_days: Days to hold (default 75, middle of 60-90 DTE)
        historical_volatility: Estimated IV for strike calculation
        enable_rolls: Whether to allow roll maneuvers
        max_rolls: Maximum number of rolls allowed (default 2)

    Returns:
        Tuple of (win: 0 or 1, pnl: float)
    """
    if len(future_bars) < 30:
        return 0, 0.0

    # Time to expiration in years
    T = holding_days / 365.0

    # Find strikes based on target deltas
    short_strike = find_strike_for_delta_simple(
        target_delta=SHORT_DELTA_TARGET,
        S=entry_price,
        T=T,
        sigma=historical_volatility
    )

    long_strike = find_strike_for_delta_simple(
        target_delta=LONG_DELTA_TARGET,
        S=entry_price,
        T=T,
        sigma=historical_volatility
    )

    # Fallback to OTM% if delta calculation fails
    if short_strike is None or long_strike is None:
        short_strike = entry_price * 0.92  # ~8% OTM
        long_strike = entry_price * 0.85   # ~15% OTM

    # Ensure short > long (valid spread)
    if short_strike <= long_strike:
        short_strike = entry_price * 0.92
        long_strike = entry_price * 0.85

    spread_width = short_strike - long_strike

    # Calculate initial premium using Black-Scholes
    short_premium = black_scholes_put_simple(entry_price, short_strike, T, 0.05, historical_volatility)
    long_premium = black_scholes_put_simple(entry_price, long_strike, T, 0.05, historical_volatility)
    net_credit = short_premium - long_premium

    # Ensure minimum credit (at least 20% of spread width)
    if net_credit < spread_width * 0.20:
        net_credit = spread_width * 0.20

    # Track cumulative P&L and rolls
    total_credit = net_credit * 100  # Initial credit received
    total_debit = 0.0  # Costs from closing/rolling
    rolls_used = 0
    current_dte = holding_days

    for day, bar in enumerate(future_bars[:holding_days + 60]):  # Extended window for rolls
        current_price = bar['close']
        days_remaining = holding_days - day + (rolls_used * 30)  # Each roll adds ~30 days

        # =====================================================================
        # ROLL LOGIC
        # =====================================================================
        if enable_rolls and rolls_used < max_rolls:
            # Calculate current position value
            current_T = max(days_remaining, 1) / 365.0
            current_short_value = black_scholes_put_simple(
                current_price, short_strike, current_T, 0.05, historical_volatility
            )
            current_long_value = black_scholes_put_simple(
                current_price, long_strike, current_T, 0.05, historical_volatility
            )
            current_spread_value = current_short_value - current_long_value

            # Roll trigger conditions:
            # 1. Price within 3% of short strike (tested)
            price_near_short = current_price <= short_strike * 1.03
            # 2. Position showing loss > 25% of max loss (under pressure)
            current_loss = current_spread_value - net_credit
            max_possible_loss = spread_width - net_credit
            loss_ratio = current_loss / max_possible_loss if max_possible_loss > 0 else 0
            under_pressure = loss_ratio > 0.25
            # 3. DTE < 30 (approaching gamma acceleration)
            low_dte = days_remaining < 30

            should_roll = False
            roll_type = None

            # Decision matrix for rolling
            if price_near_short and under_pressure and low_dte:
                # Critical: Roll Down AND Out
                should_roll = True
                roll_type = "down_and_out"
            elif price_near_short and under_pressure:
                # Defensive: Roll Down only
                should_roll = True
                roll_type = "down"
            elif low_dte and under_pressure and current_price < short_strike * 1.03:
                # Time pressure: Roll Out
                should_roll = True
                roll_type = "out"

            if should_roll and rolls_used < max_rolls:
                # Calculate cost to close current position
                close_cost = current_spread_value * 100

                # Calculate new position based on roll type
                if roll_type == "down_and_out":
                    # Roll down 5% and out 30 days
                    new_entry_price = current_price
                    new_T = (days_remaining + 30) / 365.0
                    new_short = find_strike_for_delta_simple(SHORT_DELTA_TARGET, new_entry_price, new_T, historical_volatility)
                    new_long = find_strike_for_delta_simple(LONG_DELTA_TARGET, new_entry_price, new_T, historical_volatility)
                    holding_days = day + days_remaining + 30  # Extend holding period

                elif roll_type == "down":
                    # Roll down to new delta-based strikes at current price
                    new_entry_price = current_price
                    new_T = days_remaining / 365.0
                    new_short = find_strike_for_delta_simple(SHORT_DELTA_TARGET, new_entry_price, new_T, historical_volatility)
                    new_long = find_strike_for_delta_simple(LONG_DELTA_TARGET, new_entry_price, new_T, historical_volatility)

                elif roll_type == "out":
                    # Keep strikes, extend expiration by 30 days
                    new_short = short_strike
                    new_long = long_strike
                    new_T = (days_remaining + 30) / 365.0
                    holding_days = day + days_remaining + 30

                # Ensure valid new strikes
                if new_short is None or new_long is None or new_short <= new_long:
                    new_short = current_price * 0.92
                    new_long = current_price * 0.85

                # Calculate new credit
                new_short_premium = black_scholes_put_simple(current_price, new_short, new_T, 0.05, historical_volatility)
                new_long_premium = black_scholes_put_simple(current_price, new_long, new_T, 0.05, historical_volatility)
                new_credit = (new_short_premium - new_long_premium) * 100

                # Net cost of roll = close cost - new credit
                # (We pay to close, receive credit for new position)
                roll_net_cost = close_cost - new_credit

                # IMPROVED ROLL DECISION:
                # 1. Only roll if we can do it for a net CREDIT (getting paid to roll)
                # 2. Or if the debit is very small (< 10% of original credit)
                # 3. AND the new strikes give us more room
                new_strike_gives_room = new_short < short_strike * 0.98  # New short at least 2% lower

                can_roll_for_credit = roll_net_cost <= 0
                small_debit_acceptable = roll_net_cost > 0 and roll_net_cost < (net_credit * 100 * 0.10)
                roll_is_worthwhile = (can_roll_for_credit or small_debit_acceptable) and new_strike_gives_room

                if roll_is_worthwhile:
                    total_debit += max(0, roll_net_cost)  # Add debit if any
                    if roll_net_cost < 0:
                        total_credit += abs(roll_net_cost)  # Add credit if we get paid

                    # Update position
                    short_strike = new_short
                    long_strike = new_long
                    spread_width = short_strike - long_strike
                    net_credit = new_short_premium - new_long_premium
                    rolls_used += 1

        # =====================================================================
        # EXIT CONDITIONS
        # =====================================================================
        # Max loss trigger (breach long strike)
        if bar['low'] < long_strike:
            max_loss = spread_width * 100
            return 0, total_credit - total_debit - max_loss

        # Early exit at DTE=7 (gamma risk management)
        days_remaining = holding_days - day + (rolls_used * 30)
        if days_remaining <= 7 and bar['close'] >= short_strike:
            # Close for 80% of remaining credit
            return 1, (total_credit - total_debit) * 0.80

        # Check if we've exceeded extended holding period
        if day >= holding_days + (rolls_used * 30):
            break

    # Final settlement
    final_idx = min(holding_days + (rolls_used * 30) - 1, len(future_bars) - 1)
    final_price = future_bars[final_idx]['close']

    if final_price >= short_strike:
        # Full profit: keep all credits minus debits
        return 1, total_credit - total_debit
    elif final_price >= long_strike:
        # Partial: intrinsic value at expiration
        intrinsic = (short_strike - final_price) * 100
        final_pnl = total_credit - total_debit - intrinsic
        return (1 if final_pnl > 0 else 0), final_pnl
    else:
        # Max loss
        max_loss = spread_width * 100
        return 0, total_credit - total_debit - max_loss


def analyze_symbol_worker(args: Tuple) -> Dict[str, Any]:
    symbol, symbol_data, vix_data, strategies = args

    from src.models.base import SignalType

    results = {
        'symbol': symbol,
        'total_trades': 0,
        'total_wins': 0,
        'total_pnl': 0.0,
        'strategies': {},
        'best_strategy': '',
        'best_strategy_wr': 0.0
    }

    if len(symbol_data) < 300:
        return results

    sorted_data = sorted(
        symbol_data,
        key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
    )

    for bar in sorted_data:
        if isinstance(bar['date'], str):
            bar['date'] = date.fromisoformat(bar['date'])

    split_idx = int(len(sorted_data) * 0.8)

    for strategy in strategies:
        try:
            analyzer = create_analyzer(strategy)
        except Exception:
            continue

        strat_results = {
            'train_trades': 0, 'train_wins': 0, 'train_pnl': 0.0,
            'test_trades': 0, 'test_wins': 0, 'test_pnl': 0.0,
            'by_score': defaultdict(lambda: {'trades': 0, 'wins': 0}),
            'by_regime': defaultdict(lambda: {'trades': 0, 'wins': 0})
        }

        for idx in range(250, len(sorted_data) - 100, 2):  # Need 90+ days future data
            history = sorted_data[max(0, idx-259):idx]
            future = sorted_data[idx:idx+100]  # Extended for 60-90 DTE

            if len(history) < 200 or len(future) < 75:  # Need at least 75 days
                continue

            prices = [bar['close'] for bar in history]
            volumes = [bar['volume'] for bar in history]
            highs = [bar['high'] for bar in history]
            lows = [bar['low'] for bar in history]

            try:
                signal = analyzer.analyze(
                    symbol=symbol,
                    prices=prices,
                    volumes=volumes,
                    highs=highs,
                    lows=lows
                )
            except Exception:
                continue

            if signal.signal_type != SignalType.LONG or signal.score < 5.0:
                continue

            current_date = sorted_data[idx]['date']
            vix = vix_data.get(str(current_date), 20.0)
            regime = get_regime(vix)

            # Calculate historical volatility for delta-based strike selection
            import numpy as np
            returns = np.diff(np.log(prices[-30:])) if len(prices) >= 30 else np.diff(np.log(prices))
            historical_vol = np.std(returns) * np.sqrt(252) if len(returns) > 0 else 0.25
            historical_vol = max(0.15, min(0.60, historical_vol))  # Clamp to reasonable range

            # Increase future window for longer DTE
            future_extended = sorted_data[idx:idx+90]  # 90 days for DTE 60-90
            outcome, pnl = simulate_trade(prices[-1], future_extended, HOLDING_DAYS, historical_vol)

            is_train = idx < split_idx

            if is_train:
                strat_results['train_trades'] += 1
                strat_results['train_wins'] += outcome
                strat_results['train_pnl'] += pnl
            else:
                strat_results['test_trades'] += 1
                strat_results['test_wins'] += outcome
                strat_results['test_pnl'] += pnl

            score_bucket = int(signal.score)
            strat_results['by_score'][score_bucket]['trades'] += 1
            strat_results['by_score'][score_bucket]['wins'] += outcome

            strat_results['by_regime'][regime]['trades'] += 1
            strat_results['by_regime'][regime]['wins'] += outcome

        total = strat_results['train_trades'] + strat_results['test_trades']
        wins = strat_results['train_wins'] + strat_results['test_wins']

        if total >= 10:
            wr = wins / total * 100
            train_wr = strat_results['train_wins'] / strat_results['train_trades'] * 100 if strat_results['train_trades'] > 0 else 0
            test_wr = strat_results['test_wins'] / strat_results['test_trades'] * 100 if strat_results['test_trades'] > 0 else 0

            results['strategies'][strategy] = {
                'trades': total,
                'wins': wins,
                'win_rate': wr,
                'pnl': strat_results['train_pnl'] + strat_results['test_pnl'],
                'train_wr': train_wr,
                'test_wr': test_wr,
                'degradation': train_wr - test_wr,
                'by_score': dict(strat_results['by_score']),
                'by_regime': dict(strat_results['by_regime'])
            }

            results['total_trades'] += total
            results['total_wins'] += wins
            results['total_pnl'] += strat_results['train_pnl'] + strat_results['test_pnl']

            if wr > results['best_strategy_wr'] and total >= 20:
                results['best_strategy'] = strategy
                results['best_strategy_wr'] = wr

    return results


def process_symbols(symbols: List[str], data: Dict) -> List[Dict]:
    """Process a list of symbols and return results"""
    historical_data = data['historical_data']
    vix_data = data['vix_data']

    symbol_args = [
        (symbol, historical_data[symbol], vix_data, STRATEGIES)
        for symbol in symbols
        if symbol in historical_data
    ]

    print(f"Worker processing {len(symbol_args)} symbols with {NUM_WORKERS} workers...", file=sys.stderr)

    results = []
    with Pool(NUM_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(analyze_symbol_worker, symbol_args)):
            if result['total_trades'] >= 10:
                results.append(result)
            if (i + 1) % 20 == 0:
                print(f"  Worker progress: {i+1}/{len(symbol_args)}", file=sys.stderr)

    print(f"Worker completed: {len(results)} valid symbols", file=sys.stderr)
    return results


def main():
    parser = argparse.ArgumentParser(description='Worker training script')
    parser.add_argument('--symbols', type=str, required=True, help='JSON list of symbols')
    parser.add_argument('--data-file', type=str, required=True, help='Path to data file')
    args = parser.parse_args()

    symbols = json.loads(args.symbols)

    data_path = Path(args.data_file)
    if not data_path.is_absolute():
        data_path = project_root / args.data_file

    print(f"Loading data from {data_path}...", file=sys.stderr)

    with open(data_path, 'r') as f:
        data = json.load(f)

    results = process_symbols(symbols, data)

    # Output results as JSON to stdout (for master to capture)
    print(json.dumps(results))


if __name__ == '__main__':
    main()
