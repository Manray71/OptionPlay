#!/usr/bin/env python3
"""
OptionPlay - Distributed Training (Thunderbolt Bridge)
======================================================

Distributes training workload across two MacBooks connected via Thunderbolt Bridge.

Architecture:
- Master (this machine): Coordinates work, collects results, 12 cores
- Worker (larss-macbook-pro-2.local): Processes assigned symbols, 14 cores

Usage:
    python scripts/distributed_training.py

Requirements:
    - SSH key-based auth to worker (ssh-copy-id larss-macbook-pro-2.local)
    - Project synced to worker (rsync)
    - Python + dependencies on worker
"""

import json
import sys
import subprocess
import warnings
import logging
import multiprocessing as mp
from multiprocessing import Pool
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Dict, List, Any, Tuple
from collections import defaultdict
import statistics
import tempfile
import time
import os

# Set multiprocessing start method for macOS
if sys.platform == 'darwin':
    try:
        mp.set_start_method('fork', force=True)
    except RuntimeError:
        pass

warnings.filterwarnings('ignore')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.config.liquidity_blacklist import filter_liquid_symbols, ILLIQUID_OPTIONS_BLACKLIST

# Setup
LOG_DIR = Path.home() / '.optionplay'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'distributed_training.log'
OUTPUT_DIR = LOG_DIR / 'models'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']
VIX_REGIMES = {'low': (0, 15), 'normal': (15, 20), 'elevated': (20, 30), 'high': (30, 100)}
MIN_SCORES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]

# Delta-based strike selection (from strategies.yaml)
SHORT_DELTA_TARGET = -0.20  # Delta für Short Put
LONG_DELTA_TARGET = -0.05   # Delta für Long Put
DTE_MIN = 60
DTE_MAX = 90
HOLDING_DAYS = 75  # Mittlerer Wert zwischen 60-90 DTE

# Worker configuration
WORKER_HOST = 'larss-macbook-pro-2.local'
WORKER_PROJECT_PATH = '~/OptionPlay'
MASTER_WORKERS = 10  # Local cores to use
WORKER_WORKERS = 12  # Remote cores to use


def get_regime(vix: float) -> str:
    for regime, (low, high) in VIX_REGIMES.items():
        if low <= vix < high:
            return regime
    return 'high'


def create_analyzer(strategy: str):
    """Create analyzer - must be called within worker process"""
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

    from src.pricing import find_strike_for_delta, black_scholes_put

    # Time to expiration in years
    T = holding_days / 365.0

    # Find strikes based on target deltas
    short_strike = find_strike_for_delta(
        target_delta=SHORT_DELTA_TARGET,
        S=entry_price,
        T=T,
        sigma=historical_volatility,
        option_type="P"
    )

    long_strike = find_strike_for_delta(
        target_delta=LONG_DELTA_TARGET,
        S=entry_price,
        T=T,
        sigma=historical_volatility,
        option_type="P"
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
    short_premium = black_scholes_put(entry_price, short_strike, T, 0.05, historical_volatility)
    long_premium = black_scholes_put(entry_price, long_strike, T, 0.05, historical_volatility)
    net_credit = short_premium - long_premium

    # Ensure minimum credit (at least 20% of spread width)
    if net_credit < spread_width * 0.20:
        net_credit = spread_width * 0.20

    # Track cumulative P&L and rolls
    total_credit = net_credit * 100  # Initial credit received
    total_debit = 0.0  # Costs from closing/rolling
    rolls_used = 0
    current_holding_days = holding_days

    for day, bar in enumerate(future_bars[:holding_days + 60]):  # Extended window for rolls
        current_price = bar['close']
        days_remaining = current_holding_days - day + (rolls_used * 30)  # Each roll adds ~30 days

        # =====================================================================
        # ROLL LOGIC
        # =====================================================================
        if enable_rolls and rolls_used < max_rolls:
            # Calculate current position value
            current_T = max(days_remaining, 1) / 365.0
            current_short_value = black_scholes_put(
                current_price, short_strike, current_T, 0.05, historical_volatility
            )
            current_long_value = black_scholes_put(
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
                    new_short = find_strike_for_delta(SHORT_DELTA_TARGET, new_entry_price, new_T, historical_volatility, option_type="P")
                    new_long = find_strike_for_delta(LONG_DELTA_TARGET, new_entry_price, new_T, historical_volatility, option_type="P")
                    current_holding_days = day + days_remaining + 30  # Extend holding period

                elif roll_type == "down":
                    # Roll down to new delta-based strikes at current price
                    new_entry_price = current_price
                    new_T = days_remaining / 365.0
                    new_short = find_strike_for_delta(SHORT_DELTA_TARGET, new_entry_price, new_T, historical_volatility, option_type="P")
                    new_long = find_strike_for_delta(LONG_DELTA_TARGET, new_entry_price, new_T, historical_volatility, option_type="P")

                elif roll_type == "out":
                    # Keep strikes, extend expiration by 30 days
                    new_short = short_strike
                    new_long = long_strike
                    new_T = (days_remaining + 30) / 365.0
                    current_holding_days = day + days_remaining + 30

                # Ensure valid new strikes
                if new_short is None or new_long is None or new_short <= new_long:
                    new_short = current_price * 0.92
                    new_long = current_price * 0.85

                # Calculate new credit
                new_short_premium = black_scholes_put(current_price, new_short, new_T, 0.05, historical_volatility)
                new_long_premium = black_scholes_put(current_price, new_long, new_T, 0.05, historical_volatility)
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
        days_remaining = current_holding_days - day + (rolls_used * 30)
        if days_remaining <= 7 and bar['close'] >= short_strike:
            # Close for 80% of remaining credit
            return 1, (total_credit - total_debit) * 0.80

        # Check if we've exceeded extended holding period
        if day >= current_holding_days + (rolls_used * 30):
            break

    # Final settlement
    final_idx = min(current_holding_days + (rolls_used * 30) - 1, len(future_bars) - 1)
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
    """Worker function to analyze a single symbol"""
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
            vix = vix_data.get(current_date, 20.0)
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


def check_worker_connection() -> bool:
    """Check if worker is reachable via SSH"""
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', WORKER_HOST, 'echo OK'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and 'OK' in result.stdout
    except Exception as e:
        logger.error(f"Worker connection failed: {e}")
        return False


def sync_data_to_worker(data_file: Path) -> bool:
    """Sync data file to worker"""
    try:
        result = subprocess.run(
            ['rsync', '-az', str(data_file), f'{WORKER_HOST}:{WORKER_PROJECT_PATH}/'],
            capture_output=True, text=True, timeout=120
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Data sync failed: {e}")
        return False


def run_worker_training(symbols: List[str], data_file: str) -> List[Dict]:
    """Run training on remote worker and collect results"""

    worker_script = f'''
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "OptionPlay"))

# Load the worker script
exec(open(Path.home() / "OptionPlay" / "scripts" / "worker_training.py").read())

# Load data
with open(Path.home() / "OptionPlay" / "{data_file}", "r") as f:
    data = json.load(f)

# Process assigned symbols
results = process_symbols({json.dumps(symbols)}, data)

# Output results as JSON
print("RESULTS_START")
print(json.dumps(results))
print("RESULTS_END")
'''

    try:
        result = subprocess.run(
            ['ssh', WORKER_HOST, 'python3', '-c', worker_script],
            capture_output=True, text=True, timeout=3600  # 1 hour timeout
        )

        if result.returncode != 0:
            logger.error(f"Worker training failed: {result.stderr}")
            return []

        # Extract results from output
        output = result.stdout
        start_idx = output.find("RESULTS_START") + len("RESULTS_START")
        end_idx = output.find("RESULTS_END")

        if start_idx > len("RESULTS_START") and end_idx > start_idx:
            results_json = output[start_idx:end_idx].strip()
            return json.loads(results_json)
        else:
            logger.error("Could not parse worker results")
            return []

    except subprocess.TimeoutExpired:
        logger.error("Worker training timed out")
        return []
    except Exception as e:
        logger.error(f"Worker training error: {e}")
        return []


def sync_worker_script():
    """Sync the worker training script to the remote worker.

    The worker_training.py script is maintained separately with delta-based
    strike selection. This function syncs it to the worker machine.
    """
    worker_path = project_root / 'scripts' / 'worker_training.py'

    if not worker_path.exists():
        logger.error(f"Worker script not found: {worker_path}")
        return None

    # Sync to worker
    result = subprocess.run(
        ['rsync', '-az', str(worker_path), f'{WORKER_HOST}:{WORKER_PROJECT_PATH}/scripts/'],
        capture_output=True, timeout=30
    )

    if result.returncode != 0:
        logger.error(f"Failed to sync worker script: {result.stderr}")
        return None

    logger.info(f"  Worker script synced: {worker_path.name}")
    return worker_path


def save_progress(phase: str, detail: str, stats: Dict):
    """Save progress to file"""
    progress = {
        'timestamp': datetime.now().isoformat(),
        'phase': phase,
        'detail': detail,
        'distributed': True,
        'master_workers': MASTER_WORKERS,
        'remote_workers': WORKER_WORKERS,
        **stats
    }
    with open(OUTPUT_DIR / 'distributed_progress.json', 'w') as f:
        json.dump(progress, f, indent=2)


def main():
    """Main distributed training pipeline"""

    start_time = datetime.now()

    logger.info("=" * 70)
    logger.info("  DISTRIBUTED TRAINING (Thunderbolt Bridge)")
    logger.info("=" * 70)
    logger.info(f"  Master: {MASTER_WORKERS} workers")
    logger.info(f"  Worker: {WORKER_HOST} with {WORKER_WORKERS} workers")
    logger.info(f"  Started: {start_time}")
    logger.info("=" * 70)

    # Check worker connection
    logger.info("\nChecking worker connection...")
    if not check_worker_connection():
        logger.error("Cannot connect to worker. Running in single-node mode.")
        use_distributed = False
    else:
        logger.info("  Worker connected!")
        use_distributed = True

        # Sync worker script to remote machine
        logger.info("  Syncing worker script...")
        sync_worker_script()

    # Load data
    logger.info("\nLoading data...")

    from src.backtesting import TradeTracker

    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    logger.info(f"  Symbols: {stats['symbols_with_price_data']}")
    logger.info(f"  Price Bars: {stats['total_price_bars']:,}")

    symbol_info = tracker.list_symbols_with_price_data()
    all_symbols_raw = [s['symbol'] for s in symbol_info]

    # Filter out illiquid symbols
    symbols = filter_liquid_symbols(all_symbols_raw)
    blacklisted_count = len(all_symbols_raw) - len(symbols)
    logger.info(f"  Blacklist: {blacklisted_count} illiquid symbols excluded")

    historical_data = {}
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            historical_data[symbol] = [
                {
                    'date': str(bar.date),
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume,
                }
                for bar in price_data.bars
            ]

    vix_data = {}
    for p in tracker.get_vix_data():
        vix_data[str(p.date)] = p.value

    logger.info(f"  Loaded: {len(historical_data)} symbols")

    # Split symbols between master and worker
    all_symbols = list(historical_data.keys())

    if use_distributed:
        # 55% to worker (more cores), 45% to master
        split_point = int(len(all_symbols) * 0.55)
        worker_symbols = all_symbols[:split_point]
        master_symbols = all_symbols[split_point:]

        logger.info(f"\n  Work distribution:")
        logger.info(f"    Master: {len(master_symbols)} symbols")
        logger.info(f"    Worker: {len(worker_symbols)} symbols")

        # Save data for worker
        data_file = 'training_data.json'
        data_path = project_root / data_file
        with open(data_path, 'w') as f:
            json.dump({
                'historical_data': {s: historical_data[s] for s in worker_symbols},
                'vix_data': vix_data
            }, f)

        # Sync data to worker
        logger.info("\n  Syncing data to worker...")
        sync_data_to_worker(data_path)
    else:
        master_symbols = all_symbols
        worker_symbols = []

    # =========================================================================
    # PARALLEL PROCESSING
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  DISTRIBUTED SYMBOL ANALYSIS")
    logger.info("=" * 70)

    save_progress("Analysis", "Starting", {
        'master_symbols': len(master_symbols),
        'worker_symbols': len(worker_symbols)
    })

    # Start worker training in background (if distributed)
    worker_results = []
    if use_distributed and worker_symbols:
        logger.info(f"\n  Starting worker training ({len(worker_symbols)} symbols)...")

        # Run worker via SSH in background
        worker_cmd = f'''cd {WORKER_PROJECT_PATH} && python3 scripts/worker_training.py --symbols '{json.dumps(worker_symbols)}' --data-file training_data.json'''

        worker_process = subprocess.Popen(
            ['ssh', WORKER_HOST, worker_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

    # Process master symbols locally
    logger.info(f"\n  Processing master symbols ({len(master_symbols)} symbols)...")

    # Convert vix_data keys back to date objects for local processing
    vix_data_dates = {}
    for k, v in vix_data.items():
        vix_data_dates[date.fromisoformat(k)] = v

    # Convert historical_data dates back for local processing
    for sym in master_symbols:
        if sym in historical_data:
            for bar in historical_data[sym]:
                if isinstance(bar['date'], str):
                    bar['date'] = date.fromisoformat(bar['date'])

    master_args = [
        (symbol, historical_data[symbol], vix_data_dates, STRATEGIES)
        for symbol in master_symbols
        if symbol in historical_data
    ]

    master_results = []
    with Pool(MASTER_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(analyze_symbol_worker, master_args)):
            if result['total_trades'] >= 10:
                master_results.append(result)

            if (i + 1) % 50 == 0:
                logger.info(f"    Master progress: {i+1}/{len(master_args)} symbols")
                save_progress("Analysis", f"Master: {i+1}/{len(master_args)}", {
                    'master_completed': i + 1,
                    'master_valid': len(master_results)
                })

    logger.info(f"  Master completed: {len(master_results)} valid symbols")

    # Collect worker results
    if use_distributed and worker_symbols:
        logger.info("\n  Waiting for worker results...")
        try:
            stdout, stderr = worker_process.communicate(timeout=3600)
            if worker_process.returncode == 0 and stdout.strip():
                worker_results = json.loads(stdout.strip())
                logger.info(f"  Worker completed: {len(worker_results)} valid symbols")
            else:
                logger.error(f"  Worker failed: {stderr}")
        except subprocess.TimeoutExpired:
            worker_process.kill()
            logger.error("  Worker timed out")
        except json.JSONDecodeError as e:
            logger.error(f"  Failed to parse worker results: {e}")

    # Combine results
    all_results = master_results + worker_results
    logger.info(f"\n  Total results: {len(all_results)} symbols")

    # =========================================================================
    # AGGREGATE AND SAVE
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  AGGREGATION AND EXPORT")
    logger.info("=" * 70)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    total_trades = sum(r['total_trades'] for r in all_results)
    total_wins = sum(r['total_wins'] for r in all_results)
    total_pnl = sum(r['total_pnl'] for r in all_results)

    strategy_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0})
    for r in all_results:
        for strat, data in r['strategies'].items():
            strategy_stats[strat]['trades'] += data['trades']
            strategy_stats[strat]['wins'] += data['wins']
            strategy_stats[strat]['pnl'] += data['pnl']

    final_config = {
        'version': '7.0.0',
        'created_at': datetime.now().isoformat(),
        'training_type': 'distributed_thunderbolt',
        'training_duration_minutes': (datetime.now() - start_time).total_seconds() / 60,
        'distributed': use_distributed,
        'master_workers': MASTER_WORKERS,
        'worker_workers': WORKER_WORKERS if use_distributed else 0,

        'summary': {
            'total_trades': total_trades,
            'total_wins': total_wins,
            'win_rate': total_wins / total_trades * 100 if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'symbols_analyzed': len(all_results),
            'master_symbols': len(master_results),
            'worker_symbols': len(worker_results)
        },

        'strategies': {}
    }

    for strategy in STRATEGIES:
        strat_stats = strategy_stats.get(strategy, {})
        overall_wr = strat_stats['wins'] / strat_stats['trades'] * 100 if strat_stats.get('trades', 0) > 0 else 0

        final_config['strategies'][strategy] = {
            'enabled': True,
            'overall_win_rate': overall_wr,
            'total_trades': strat_stats.get('trades', 0),
            'total_pnl': strat_stats.get('pnl', 0)
        }

    # Save results
    with open(OUTPUT_DIR / f'distributed_results_{timestamp}.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    with open(OUTPUT_DIR / 'DISTRIBUTED_FINAL_CONFIG.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    # Final summary
    duration = (datetime.now() - start_time).total_seconds() / 60

    logger.info(f"\n  Results saved to {OUTPUT_DIR}")

    logger.info("\n" + "=" * 70)
    logger.info("  DISTRIBUTED TRAINING COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Duration: {duration:.1f} minutes")
    logger.info(f"  Total Workers: {MASTER_WORKERS + (WORKER_WORKERS if use_distributed else 0)}")
    logger.info(f"  Total Trades: {total_trades:,}")
    logger.info(f"  Overall Win Rate: {total_wins/total_trades*100:.1f}%" if total_trades > 0 else "  No trades")
    logger.info(f"  Total P&L: ${total_pnl:,.0f}")

    if use_distributed:
        speedup = (MASTER_WORKERS + WORKER_WORKERS) / MASTER_WORKERS
        logger.info(f"\n  Distributed speedup: ~{speedup:.1f}x")

    logger.info("\n  Strategy Results:")
    for strategy, config in final_config['strategies'].items():
        logger.info(f"    {strategy}: {config['overall_win_rate']:.1f}% WR, {config['total_trades']} trades")

    logger.info("\n" + "=" * 70)

    save_progress("Complete", "Done", {
        'duration_minutes': duration,
        'total_trades': total_trades,
        'win_rate': total_wins / total_trades * 100 if total_trades > 0 else 0
    })


if __name__ == '__main__':
    main()
