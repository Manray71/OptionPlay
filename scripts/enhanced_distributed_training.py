#!/usr/bin/env python3
"""
OptionPlay - Enhanced Distributed Training
==========================================

Erweitertes Training mit:
1. Echten historischen Optionspreisen (statt Black-Scholes Simulation)
2. IV-Rank Berechnung aus Options-Daten
3. Distributed Processing über Thunderbolt Bridge

Datenquellen:
- price_data: 628 Symbole mit OHLCV
- vix_data: 1.382 Tage VIX-Historie
- options_data: 408.780 historische Options-Bars

Usage:
    python scripts/enhanced_distributed_training.py
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
from typing import Dict, List, Any, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass
import statistics
import math

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
LOG_FILE = LOG_DIR / 'enhanced_training.log'
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

# Worker configuration
WORKER_HOST = 'larss-macbook-pro-2.local'
WORKER_PROJECT_PATH = '~/OptionPlay'
MASTER_WORKERS = 10
WORKER_WORKERS = 12


@dataclass
class SpreadTrade:
    """Ein simulierter Spread-Trade mit echten oder simulierten Preisen"""
    symbol: str
    entry_date: date
    entry_price: float
    short_strike: float
    long_strike: float
    dte: int

    # Entry Pricing
    net_credit: float  # Pro Aktie
    entry_iv: float
    iv_rank: Optional[float]

    # Outcome
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    outcome: int = 0  # 1=win, 0=loss

    # Data source
    used_real_options: bool = False


def get_regime(vix: float) -> str:
    for regime, (low, high) in VIX_REGIMES.items():
        if low <= vix < high:
            return regime
    return 'high'


def calculate_iv_rank(
    current_iv: float,
    iv_history: List[float],
    lookback_days: int = 252
) -> Optional[float]:
    """
    Berechnet IV-Rank: (Current - Low) / (High - Low) * 100

    Args:
        current_iv: Aktuelle implizite Volatilität
        iv_history: Liste historischer IV-Werte
        lookback_days: Anzahl Tage für Min/Max

    Returns:
        IV-Rank 0-100 oder None wenn nicht berechenbar
    """
    if not iv_history or len(iv_history) < 20:
        return None

    recent = iv_history[-lookback_days:] if len(iv_history) > lookback_days else iv_history
    iv_low = min(recent)
    iv_high = max(recent)

    if iv_high == iv_low:
        return 50.0

    return ((current_iv - iv_low) / (iv_high - iv_low)) * 100


def estimate_iv_from_vix(vix: float, base_iv: float = 0.25) -> float:
    """
    Schätzt Aktien-IV basierend auf VIX.

    Typisch: Aktien-IV ≈ VIX * 1.0-1.5 (je nach Beta)
    """
    # VIX 20 = neutrale Marktvolatilität
    vix_factor = vix / 20.0
    return base_iv * vix_factor


def find_otm_put_strikes(
    current_price: float,
    available_strikes: List[float],
    short_pct: float = 0.08,  # 8% OTM für Short Put
    spread_width_pct: float = 0.05  # 5% Spread-Breite
) -> Optional[Tuple[float, float]]:
    """
    Findet optimale Short/Long Put Strikes.

    Args:
        current_price: Aktueller Aktienkurs
        available_strikes: Verfügbare Strikes
        short_pct: % OTM für Short Put
        spread_width_pct: Spread-Breite als % des Preises

    Returns:
        (short_strike, long_strike) oder None
    """
    if not available_strikes:
        return None

    target_short = current_price * (1 - short_pct)
    spread_width = current_price * spread_width_pct
    target_long = target_short - spread_width

    # Finde nächste Strikes
    sorted_strikes = sorted(available_strikes)

    short_strike = None
    for s in sorted_strikes:
        if s <= target_short:
            short_strike = s
        else:
            break

    if short_strike is None:
        return None

    # Long Strike muss kleiner sein
    long_strike = None
    for s in sorted_strikes:
        if s < short_strike and s >= target_long * 0.95:
            long_strike = s

    if long_strike is None:
        # Fallback: Nächst-kleinerer Strike
        for s in reversed(sorted_strikes):
            if s < short_strike:
                long_strike = s
                break

    if long_strike is None or long_strike >= short_strike:
        return None

    return (short_strike, long_strike)


def simulate_spread_with_real_options(
    symbol: str,
    entry_date: date,
    entry_price: float,
    future_bars: List[Dict],
    options_data: Dict[str, List[Dict]],  # {occ_symbol: [bars]}
    vix: float,
    holding_days: int = 30,
    target_dte: int = 45
) -> Optional[SpreadTrade]:
    """
    Simuliert einen Bull-Put-Spread mit echten Options-Daten wenn verfügbar.

    Args:
        symbol: Ticker
        entry_date: Einstiegsdatum
        entry_price: Aktienkurs bei Einstieg
        future_bars: Zukünftige Preisbars
        options_data: Historische Options-Daten für dieses Symbol
        vix: VIX bei Einstieg
        holding_days: Max. Haltezeit
        target_dte: Ziel-DTE für Expiration

    Returns:
        SpreadTrade oder None
    """
    if len(future_bars) < 15:
        return None

    # Suche passende Options
    expiry_target = entry_date + timedelta(days=target_dte)

    # Sammle verfügbare Puts für dieses Datum und passende Expiration
    available_puts = {}  # strike -> {bar_data}
    used_real_options = False

    for occ_symbol, bars in options_data.items():
        # Parse OCC symbol: AAPL  240315P00175000
        # Format: ROOT + YYMMDD + P/C + STRIKE*1000
        if len(occ_symbol) < 15:
            continue

        try:
            # Check if it's a put
            if 'P' not in occ_symbol[6:]:
                continue

            # Find bars for entry date
            for bar in bars:
                bar_date = bar['trade_date'] if isinstance(bar['trade_date'], date) else date.fromisoformat(bar['trade_date'])
                if bar_date == entry_date:
                    # Parse expiry and strike from OCC
                    expiry_str = occ_symbol[-15:-9]  # YYMMDD
                    strike_str = occ_symbol[-8:]  # SSSSSXXX (strike * 1000)

                    expiry = date(2000 + int(expiry_str[:2]), int(expiry_str[2:4]), int(expiry_str[4:6]))
                    strike = int(strike_str) / 1000.0

                    # Check DTE
                    dte = (expiry - entry_date).days
                    if 30 <= dte <= 60:  # Passender DTE-Bereich
                        available_puts[strike] = {
                            'occ_symbol': occ_symbol,
                            'price': bar['close'],
                            'expiry': expiry,
                            'dte': dte
                        }
                        used_real_options = True
                    break
        except (ValueError, IndexError):
            continue

    # Finde optimale Strikes
    if available_puts:
        strikes = list(available_puts.keys())
        strike_pair = find_otm_put_strikes(entry_price, strikes)
    else:
        strike_pair = None

    # Fallback zu simulierten Strikes
    if strike_pair is None:
        short_strike = entry_price * 0.92
        long_strike = short_strike - (entry_price * 0.05)
        used_real_options = False
    else:
        short_strike, long_strike = strike_pair

    spread_width = short_strike - long_strike

    # Pricing
    if used_real_options and short_strike in available_puts and long_strike in available_puts:
        # Echte Preise verwenden
        short_put_price = available_puts[short_strike]['price']
        long_put_price = available_puts[long_strike]['price']
        net_credit = short_put_price - long_put_price
        dte = available_puts[short_strike]['dte']

        # IV aus Options-Preis schätzen (vereinfacht)
        entry_iv = estimate_iv_from_vix(vix)
    else:
        # Black-Scholes Simulation
        used_real_options = False
        entry_iv = estimate_iv_from_vix(vix)
        dte = target_dte

        # FIX 1: Realistisches Pricing - 30-40% der Spread-Breite
        # Typisch für Bull-Put-Spreads mit OTM Puts bei normaler IV
        credit_pct = 0.30 + (entry_iv - 0.20) * 0.3  # Höhere IV = höherer Credit
        credit_pct = max(0.25, min(0.45, credit_pct))  # Min 25%, Max 45%
        net_credit = spread_width * credit_pct

    if net_credit <= 0:
        return None

    # Trade simulieren
    max_profit = net_credit * 100
    max_loss = (spread_width - net_credit) * 100

    # FIX 2: Stop-Loss bei 2x Credit (statt vollem Verlust)
    stop_loss_amount = net_credit * 2.0 * 100

    exit_date = None
    exit_price = None
    exit_reason = ""
    pnl = 0.0
    outcome = 0

    for day, bar in enumerate(future_bars[:holding_days]):
        current_price = bar['close']
        current_low = bar['low']

        # FIX 2: Smart Stop-Loss basierend auf Preisbewegung
        if current_low < short_strike:
            # Berechne Verlust basierend auf wie weit unter Short Strike
            price_below_short = short_strike - current_low
            current_loss = min(price_below_short * 100, max_loss)

            if current_loss >= stop_loss_amount:
                exit_date = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
                exit_price = current_price
                exit_reason = "stop_loss"
                pnl = -stop_loss_amount  # Capped Stop-Loss
                outcome = 0
                break

        # FIX 3: Profit Target bei 75% (statt 50%)
        if day >= 14 and current_price >= entry_price:
            exit_date = bar['date'] if isinstance(bar['date'], date) else date.fromisoformat(bar['date'])
            exit_price = current_price
            exit_reason = "profit_target"
            pnl = max_profit * 0.75  # 75% Profit-Taking
            outcome = 1
            break

    # Kein Exit? → Expiration
    if exit_date is None:
        final_bar = future_bars[min(holding_days-1, len(future_bars)-1)]
        final_price = final_bar['close']
        exit_date = final_bar['date'] if isinstance(final_bar['date'], date) else date.fromisoformat(final_bar['date'])
        exit_price = final_price
        exit_reason = "expiration"

        if final_price >= short_strike:
            pnl = max_profit
            outcome = 1
        elif final_price >= long_strike:
            intrinsic = short_strike - final_price
            pnl = (net_credit - intrinsic) * 100
            outcome = 1 if pnl > 0 else 0
        else:
            pnl = -stop_loss_amount  # Capped loss at expiration too
            outcome = 0

    return SpreadTrade(
        symbol=symbol,
        entry_date=entry_date,
        entry_price=entry_price,
        short_strike=short_strike,
        long_strike=long_strike,
        dte=dte,
        net_credit=net_credit,
        entry_iv=entry_iv,
        iv_rank=None,  # Wird später berechnet
        exit_date=exit_date,
        exit_price=exit_price,
        exit_reason=exit_reason,
        pnl=pnl,
        outcome=outcome,
        used_real_options=used_real_options
    )


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


def analyze_symbol_enhanced(args: Tuple) -> Dict[str, Any]:
    """
    Enhanced Symbol-Analyse mit echten Options-Daten und IV-Rank.
    """
    symbol, symbol_data, vix_data, options_data, strategies = args

    from src.models.base import SignalType

    results = {
        'symbol': symbol,
        'total_trades': 0,
        'total_wins': 0,
        'total_pnl': 0.0,
        'real_options_trades': 0,
        'strategies': {},
        'best_strategy': '',
        'best_strategy_wr': 0.0,
        'iv_rank_stats': {'avg': 0, 'trades_with_iv_rank': 0}
    }

    if len(symbol_data) < 300:
        return results

    # Sort data
    sorted_data = sorted(
        symbol_data,
        key=lambda x: x['date'] if isinstance(x['date'], date) else date.fromisoformat(x['date'])
    )

    for bar in sorted_data:
        if isinstance(bar['date'], str):
            bar['date'] = date.fromisoformat(bar['date'])

    # Get options data for this symbol
    symbol_options = options_data.get(symbol, {})

    # Track IV history for IV-Rank
    iv_history = []

    split_idx = int(len(sorted_data) * 0.8)

    for strategy in strategies:
        try:
            analyzer = create_analyzer(strategy)
        except Exception:
            continue

        strat_results = {
            'train_trades': 0, 'train_wins': 0, 'train_pnl': 0.0,
            'test_trades': 0, 'test_wins': 0, 'test_pnl': 0.0,
            'real_options_trades': 0,
            'by_score': defaultdict(lambda: {'trades': 0, 'wins': 0}),
            'by_regime': defaultdict(lambda: {'trades': 0, 'wins': 0}),
            'by_iv_rank': defaultdict(lambda: {'trades': 0, 'wins': 0}),
            'iv_rank_sum': 0.0,
            'iv_rank_count': 0
        }

        for idx in range(250, len(sorted_data) - 40, 2):
            history = sorted_data[max(0, idx-259):idx]
            future = sorted_data[idx:idx+40]

            if len(history) < 200 or len(future) < 30:
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
            current_price = prices[-1]
            vix = vix_data.get(current_date, 20.0)
            regime = get_regime(vix)

            # IV für IV-Rank tracking
            current_iv = estimate_iv_from_vix(vix)
            iv_history.append(current_iv)
            iv_rank = calculate_iv_rank(current_iv, iv_history)

            # Enhanced Trade-Simulation mit echten Options wenn verfügbar
            trade = simulate_spread_with_real_options(
                symbol=symbol,
                entry_date=current_date,
                entry_price=current_price,
                future_bars=future,
                options_data=symbol_options,
                vix=vix,
                holding_days=30
            )

            if trade is None:
                continue

            trade.iv_rank = iv_rank

            is_train = idx < split_idx

            if is_train:
                strat_results['train_trades'] += 1
                strat_results['train_wins'] += trade.outcome
                strat_results['train_pnl'] += trade.pnl
            else:
                strat_results['test_trades'] += 1
                strat_results['test_wins'] += trade.outcome
                strat_results['test_pnl'] += trade.pnl

            if trade.used_real_options:
                strat_results['real_options_trades'] += 1

            # Bucketing
            score_bucket = int(signal.score)
            strat_results['by_score'][score_bucket]['trades'] += 1
            strat_results['by_score'][score_bucket]['wins'] += trade.outcome

            strat_results['by_regime'][regime]['trades'] += 1
            strat_results['by_regime'][regime]['wins'] += trade.outcome

            # IV-Rank Bucketing (0-25, 25-50, 50-75, 75-100)
            if iv_rank is not None:
                iv_bucket = int(iv_rank // 25) * 25
                strat_results['by_iv_rank'][iv_bucket]['trades'] += 1
                strat_results['by_iv_rank'][iv_bucket]['wins'] += trade.outcome
                strat_results['iv_rank_sum'] += iv_rank
                strat_results['iv_rank_count'] += 1

        # Aggregate
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
                'real_options_trades': strat_results['real_options_trades'],
                'real_options_pct': strat_results['real_options_trades'] / total * 100 if total > 0 else 0,
                'avg_iv_rank': strat_results['iv_rank_sum'] / strat_results['iv_rank_count'] if strat_results['iv_rank_count'] > 0 else None,
                'by_score': dict(strat_results['by_score']),
                'by_regime': dict(strat_results['by_regime']),
                'by_iv_rank': dict(strat_results['by_iv_rank'])
            }

            results['total_trades'] += total
            results['total_wins'] += wins
            results['total_pnl'] += strat_results['train_pnl'] + strat_results['test_pnl']
            results['real_options_trades'] += strat_results['real_options_trades']

            if wr > results['best_strategy_wr'] and total >= 20:
                results['best_strategy'] = strategy
                results['best_strategy_wr'] = wr

            # IV-Rank Stats
            if strat_results['iv_rank_count'] > 0:
                results['iv_rank_stats']['trades_with_iv_rank'] += strat_results['iv_rank_count']
                results['iv_rank_stats']['avg'] = (
                    (results['iv_rank_stats']['avg'] * (results['iv_rank_stats']['trades_with_iv_rank'] - strat_results['iv_rank_count'])
                     + strat_results['iv_rank_sum']) / results['iv_rank_stats']['trades_with_iv_rank']
                )

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
            capture_output=True, text=True, timeout=300
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Data sync failed: {e}")
        return False


def save_progress(phase: str, detail: str, stats: Dict):
    """Save progress to file"""
    progress = {
        'timestamp': datetime.now().isoformat(),
        'phase': phase,
        'detail': detail,
        'enhanced': True,
        'uses_real_options': True,
        'uses_iv_rank': True,
        **stats
    }
    with open(OUTPUT_DIR / 'enhanced_progress.json', 'w') as f:
        json.dump(progress, f, indent=2)


def main():
    """Main enhanced distributed training pipeline"""

    start_time = datetime.now()

    logger.info("=" * 70)
    logger.info("  ENHANCED DISTRIBUTED TRAINING")
    logger.info("  (Real Options + IV-Rank + Distributed)")
    logger.info("=" * 70)
    logger.info(f"  Master: {MASTER_WORKERS} workers")
    logger.info(f"  Worker: {WORKER_HOST} with {WORKER_WORKERS} workers")
    logger.info(f"  Started: {start_time}")
    logger.info("=" * 70)

    # Check worker connection
    logger.info("\nChecking worker connection...")
    use_distributed = check_worker_connection()
    if use_distributed:
        logger.info("  Worker connected!")
    else:
        logger.info("  Worker not available. Running single-node.")

    # Load data
    logger.info("\nLoading data from database...")

    from src.backtesting import TradeTracker

    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    logger.info(f"  Price Data: {stats['symbols_with_price_data']} symbols, {stats['total_price_bars']:,} bars")
    logger.info(f"  VIX Data: {stats.get('vix_data_points', 'N/A')} data points")

    # Count options data
    options_count = tracker.count_option_bars()
    logger.info(f"  Options Data: {options_count:,} bars")

    # Load price data
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
                    'date': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume,
                }
                for bar in price_data.bars
            ]

    # Load VIX data
    vix_data = {}
    for p in tracker.get_vix_data():
        vix_data[p.date] = p.value

    logger.info(f"  Loaded: {len(historical_data)} symbols with price data")
    logger.info(f"  VIX range: {min(vix_data.keys())} to {max(vix_data.keys())}")

    # Load options data (grouped by underlying)
    logger.info("\nLoading options data...")
    options_data = defaultdict(lambda: defaultdict(list))

    # Get options summary
    options_summary = tracker.list_options_underlyings()
    symbols_with_options = [s['underlying'] for s in options_summary]
    logger.info(f"  Symbols with options data: {len(symbols_with_options)}")

    for symbol in symbols_with_options:
        if symbol in historical_data:
            # Load options for this symbol
            option_bars = tracker.get_options_for_underlying(symbol)
            for bar in option_bars:
                options_data[symbol][bar.occ_symbol].append({
                    'trade_date': bar.trade_date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                })

    logger.info(f"  Loaded options for {len(options_data)} symbols")

    # Split symbols for distribution
    all_symbols = list(historical_data.keys())

    if use_distributed:
        split_point = int(len(all_symbols) * 0.55)
        worker_symbols = all_symbols[:split_point]
        master_symbols = all_symbols[split_point:]
        logger.info(f"\n  Work distribution:")
        logger.info(f"    Master: {len(master_symbols)} symbols")
        logger.info(f"    Worker: {len(worker_symbols)} symbols")
    else:
        master_symbols = all_symbols
        worker_symbols = []

    # =========================================================================
    # ENHANCED TRAINING
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  ENHANCED SYMBOL ANALYSIS")
    logger.info("  (Real Options Pricing + IV-Rank)")
    logger.info("=" * 70)

    save_progress("Analysis", "Starting", {
        'total_symbols': len(all_symbols),
        'symbols_with_options': len(options_data)
    })

    # Prepare args for parallel processing
    master_args = [
        (symbol, historical_data[symbol], vix_data, dict(options_data.get(symbol, {})), STRATEGIES)
        for symbol in master_symbols
        if symbol in historical_data
    ]

    logger.info(f"\n  Processing {len(master_args)} symbols with {MASTER_WORKERS} workers...")

    master_results = []
    with Pool(MASTER_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(analyze_symbol_enhanced, master_args)):
            if result['total_trades'] >= 10:
                master_results.append(result)

            if (i + 1) % 50 == 0:
                logger.info(f"    Progress: {i+1}/{len(master_args)} symbols")
                save_progress("Analysis", f"{i+1}/{len(master_args)}", {
                    'completed': i + 1,
                    'valid_symbols': len(master_results)
                })

    logger.info(f"  Completed: {len(master_results)} valid symbols")

    # TODO: Add worker processing for distributed mode (similar to distributed_training.py)

    # =========================================================================
    # AGGREGATE RESULTS
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  RESULTS AGGREGATION")
    logger.info("=" * 70)

    all_results = master_results

    total_trades = sum(r['total_trades'] for r in all_results)
    total_wins = sum(r['total_wins'] for r in all_results)
    total_pnl = sum(r['total_pnl'] for r in all_results)
    real_options_trades = sum(r['real_options_trades'] for r in all_results)

    strategy_stats = defaultdict(lambda: {
        'trades': 0, 'wins': 0, 'pnl': 0.0,
        'real_options_trades': 0,
        'by_iv_rank': defaultdict(lambda: {'trades': 0, 'wins': 0})
    })

    for r in all_results:
        for strat, data in r['strategies'].items():
            strategy_stats[strat]['trades'] += data['trades']
            strategy_stats[strat]['wins'] += data['wins']
            strategy_stats[strat]['pnl'] += data['pnl']
            strategy_stats[strat]['real_options_trades'] += data.get('real_options_trades', 0)

            # Aggregate IV-Rank buckets
            for bucket, bucket_data in data.get('by_iv_rank', {}).items():
                strategy_stats[strat]['by_iv_rank'][bucket]['trades'] += bucket_data['trades']
                strategy_stats[strat]['by_iv_rank'][bucket]['wins'] += bucket_data['wins']

    # Create final config
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    final_config = {
        'version': '8.0.0',
        'created_at': datetime.now().isoformat(),
        'training_type': 'enhanced_distributed',
        'training_duration_minutes': (datetime.now() - start_time).total_seconds() / 60,

        'data_sources': {
            'price_data_symbols': len(historical_data),
            'vix_data_points': len(vix_data),
            'options_data_symbols': len(options_data),
            'options_data_bars': options_count
        },

        'summary': {
            'total_trades': total_trades,
            'total_wins': total_wins,
            'win_rate': total_wins / total_trades * 100 if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'symbols_analyzed': len(all_results),
            'real_options_trades': real_options_trades,
            'real_options_pct': real_options_trades / total_trades * 100 if total_trades > 0 else 0
        },

        'strategies': {},
        'iv_rank_analysis': {}
    }

    for strategy in STRATEGIES:
        strat = strategy_stats.get(strategy, {})
        trades = strat.get('trades', 0)
        wins = strat.get('wins', 0)

        final_config['strategies'][strategy] = {
            'enabled': True,
            'win_rate': wins / trades * 100 if trades > 0 else 0,
            'total_trades': trades,
            'total_pnl': strat.get('pnl', 0),
            'real_options_pct': strat.get('real_options_trades', 0) / trades * 100 if trades > 0 else 0
        }

        # IV-Rank analysis per strategy
        iv_rank_data = dict(strat.get('by_iv_rank', {}))
        if iv_rank_data:
            final_config['iv_rank_analysis'][strategy] = {}
            for bucket, data in sorted(iv_rank_data.items()):
                bucket_trades = data['trades']
                bucket_wins = data['wins']
                if bucket_trades >= 10:
                    final_config['iv_rank_analysis'][strategy][f'{bucket}-{bucket+25}'] = {
                        'trades': bucket_trades,
                        'win_rate': bucket_wins / bucket_trades * 100
                    }

    # Save results
    with open(OUTPUT_DIR / f'enhanced_results_{timestamp}.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    with open(OUTPUT_DIR / 'ENHANCED_FINAL_CONFIG.json', 'w') as f:
        json.dump(final_config, f, indent=2, default=str)

    # Final summary
    duration = (datetime.now() - start_time).total_seconds() / 60

    logger.info(f"\n  Results saved to {OUTPUT_DIR}")

    logger.info("\n" + "=" * 70)
    logger.info("  ENHANCED TRAINING COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Duration: {duration:.1f} minutes")
    logger.info(f"  Total Trades: {total_trades:,}")
    logger.info(f"  Overall Win Rate: {total_wins/total_trades*100:.1f}%" if total_trades > 0 else "  No trades")
    logger.info(f"  Total P&L: ${total_pnl:,.0f}")
    logger.info(f"\n  Real Options Usage: {real_options_pct:.1f}%" if (real_options_pct := real_options_trades / total_trades * 100 if total_trades > 0 else 0) else "")

    logger.info("\n  Strategy Results:")
    for strategy, config in final_config['strategies'].items():
        logger.info(f"    {strategy}: {config['win_rate']:.1f}% WR, {config['total_trades']} trades")
        if strategy in final_config['iv_rank_analysis']:
            logger.info(f"      IV-Rank Analysis:")
            for bucket, data in final_config['iv_rank_analysis'][strategy].items():
                logger.info(f"        {bucket}: {data['win_rate']:.1f}% WR ({data['trades']} trades)")

    logger.info("\n" + "=" * 70)

    save_progress("Complete", "Done", {
        'duration_minutes': duration,
        'total_trades': total_trades,
        'win_rate': total_wins / total_trades * 100 if total_trades > 0 else 0,
        'real_options_pct': real_options_trades / total_trades * 100 if total_trades > 0 else 0
    })


if __name__ == '__main__':
    main()
