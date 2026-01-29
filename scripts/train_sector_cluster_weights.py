#!/usr/bin/env python3
"""
Sector & Cluster Weight Training
================================
Trains optimal component weights for each:
1. Sector (Technology, Financials, Healthcare, etc.)
2. Cluster (Steady Medium, Volatile High, etc.)

This allows the system to use different indicator weights
depending on the stock's characteristics.

Output:
- Sector-specific weights
- Cluster-specific weights
- Strategy preferences per sector/cluster
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
from multiprocessing import Pool, cpu_count
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
# SECTOR MAPPING (expanded)
# =============================================================================

SECTOR_MAP = {
    # Technology
    'AAPL': 'Technology', 'MSFT': 'Technology', 'GOOGL': 'Technology', 'GOOG': 'Technology',
    'META': 'Technology', 'NVDA': 'Technology', 'AMD': 'Technology', 'INTC': 'Technology',
    'AVGO': 'Technology', 'QCOM': 'Technology', 'TXN': 'Technology', 'AMAT': 'Technology',
    'ADBE': 'Technology', 'CRM': 'Technology', 'ORCL': 'Technology', 'IBM': 'Technology',
    'NOW': 'Technology', 'INTU': 'Technology', 'CSCO': 'Technology', 'ACN': 'Technology',
    'ADI': 'Technology', 'LRCX': 'Technology', 'MU': 'Technology', 'KLAC': 'Technology',
    'SNPS': 'Technology', 'CDNS': 'Technology', 'MRVL': 'Technology', 'ON': 'Technology',
    'ARM': 'Technology', 'PLTR': 'Technology', 'CRWD': 'Technology', 'PANW': 'Technology',
    'DELL': 'Technology', 'HPE': 'Technology', 'HPQ': 'Technology', 'CRUS': 'Technology',

    # Financials
    'JPM': 'Financials', 'BAC': 'Financials', 'WFC': 'Financials', 'C': 'Financials',
    'GS': 'Financials', 'MS': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials',
    'AXP': 'Financials', 'V': 'Financials', 'MA': 'Financials', 'PYPL': 'Financials',
    'COF': 'Financials', 'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials',
    'AIG': 'Financials', 'MET': 'Financials', 'PRU': 'Financials', 'AFL': 'Financials',
    'CB': 'Financials', 'MMC': 'Financials', 'AON': 'Financials', 'ICE': 'Financials',
    'CME': 'Financials', 'SPGI': 'Financials', 'MCO': 'Financials',

    # Healthcare
    'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'PFE': 'Healthcare', 'MRK': 'Healthcare',
    'ABBV': 'Healthcare', 'LLY': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'BMY': 'Healthcare', 'AMGN': 'Healthcare', 'GILD': 'Healthcare',
    'MDT': 'Healthcare', 'ISRG': 'Healthcare', 'SYK': 'Healthcare', 'BSX': 'Healthcare',
    'VRTX': 'Healthcare', 'REGN': 'Healthcare', 'ZTS': 'Healthcare', 'BDX': 'Healthcare',
    'CVS': 'Healthcare', 'CI': 'Healthcare', 'ELV': 'Healthcare', 'HUM': 'Healthcare',
    'EW': 'Healthcare',

    # Consumer Discretionary
    'AMZN': 'Consumer Discretionary', 'TSLA': 'Consumer Discretionary', 'HD': 'Consumer Discretionary',
    'NKE': 'Consumer Discretionary', 'MCD': 'Consumer Discretionary', 'SBUX': 'Consumer Discretionary',
    'LOW': 'Consumer Discretionary', 'TJX': 'Consumer Discretionary', 'BKNG': 'Consumer Discretionary',
    'MAR': 'Consumer Discretionary', 'CMG': 'Consumer Discretionary', 'ORLY': 'Consumer Discretionary',
    'AZO': 'Consumer Discretionary', 'ROST': 'Consumer Discretionary', 'DHI': 'Consumer Discretionary',
    'LEN': 'Consumer Discretionary', 'GM': 'Consumer Discretionary', 'F': 'Consumer Discretionary',
    'ANF': 'Consumer Discretionary', 'LULU': 'Consumer Discretionary', 'DPZ': 'Consumer Discretionary',
    'CCL': 'Consumer Discretionary', 'LVS': 'Consumer Discretionary', 'WYNN': 'Consumer Discretionary',

    # Consumer Staples
    'PG': 'Consumer Staples', 'KO': 'Consumer Staples', 'PEP': 'Consumer Staples',
    'COST': 'Consumer Staples', 'WMT': 'Consumer Staples', 'PM': 'Consumer Staples',
    'MO': 'Consumer Staples', 'CL': 'Consumer Staples', 'MDLZ': 'Consumer Staples',
    'KMB': 'Consumer Staples', 'GIS': 'Consumer Staples', 'K': 'Consumer Staples',
    'HSY': 'Consumer Staples', 'SYY': 'Consumer Staples', 'ADM': 'Consumer Staples',
    'STZ': 'Consumer Staples', 'CAG': 'Consumer Staples', 'KHC': 'Consumer Staples',
    'CLX': 'Consumer Staples', 'SJM': 'Consumer Staples', 'HRL': 'Consumer Staples',
    'MKC': 'Consumer Staples', 'CHD': 'Consumer Staples', 'KR': 'Consumer Staples',

    # Industrials
    'CAT': 'Industrials', 'DE': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
    'UNP': 'Industrials', 'UPS': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials',
    'GE': 'Industrials', 'MMM': 'Industrials', 'EMR': 'Industrials', 'ETN': 'Industrials',
    'ITW': 'Industrials', 'WM': 'Industrials', 'RSG': 'Industrials', 'CSX': 'Industrials',
    'NSC': 'Industrials', 'FDX': 'Industrials', 'GD': 'Industrials', 'NOC': 'Industrials',
    'CARR': 'Industrials', 'IR': 'Industrials', 'ROK': 'Industrials', 'CMI': 'Industrials',
    'PCAR': 'Industrials', 'FAST': 'Industrials', 'JCI': 'Industrials', 'PH': 'Industrials',

    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'EOG': 'Energy',
    'SLB': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'OXY': 'Energy', 'HAL': 'Energy', 'DVN': 'Energy', 'FANG': 'Energy',
    'HES': 'Energy', 'BKR': 'Energy', 'APA': 'Energy', 'AR': 'Energy',
    'CTRA': 'Energy', 'OKE': 'Energy', 'KMI': 'Energy', 'WMB': 'Energy',

    # Utilities
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities',
    'AEP': 'Utilities', 'EXC': 'Utilities', 'SRE': 'Utilities', 'XEL': 'Utilities',
    'ED': 'Utilities', 'WEC': 'Utilities', 'ES': 'Utilities', 'AEE': 'Utilities',
    'DTE': 'Utilities', 'FE': 'Utilities', 'PPL': 'Utilities', 'AWK': 'Utilities',
    'ATO': 'Utilities', 'NI': 'Utilities', 'CMS': 'Utilities', 'EVRG': 'Utilities',
    'CNP': 'Utilities', 'LNT': 'Utilities', 'ETR': 'Utilities', 'EIX': 'Utilities',

    # Real Estate
    'AMT': 'Real Estate', 'PLD': 'Real Estate', 'CCI': 'Real Estate', 'EQIX': 'Real Estate',
    'PSA': 'Real Estate', 'O': 'Real Estate', 'WELL': 'Real Estate', 'SPG': 'Real Estate',
    'DLR': 'Real Estate', 'AVB': 'Real Estate', 'EQR': 'Real Estate', 'VICI': 'Real Estate',
    'ARE': 'Real Estate', 'VTR': 'Real Estate', 'MAA': 'Real Estate', 'UDR': 'Real Estate',
    'SBAC': 'Real Estate', 'EXR': 'Real Estate', 'CPT': 'Real Estate', 'INVH': 'Real Estate',
    'KIM': 'Real Estate', 'REG': 'Real Estate', 'HST': 'Real Estate',

    # Materials
    'LIN': 'Materials', 'APD': 'Materials', 'SHW': 'Materials', 'ECL': 'Materials',
    'NEM': 'Materials', 'FCX': 'Materials', 'DOW': 'Materials', 'DD': 'Materials',
    'PPG': 'Materials', 'NUE': 'Materials', 'VMC': 'Materials', 'MLM': 'Materials',
    'ALB': 'Materials', 'BALL': 'Materials', 'AVY': 'Materials', 'PKG': 'Materials',
    'BHP': 'Materials', 'RIO': 'Materials', 'AA': 'Materials', 'CLF': 'Materials',
    'CF': 'Materials', 'FMC': 'Materials', 'CE': 'Materials', 'IFF': 'Materials',

    # Communication Services
    'NFLX': 'Communication Services', 'DIS': 'Communication Services', 'CMCSA': 'Communication Services',
    'VZ': 'Communication Services', 'T': 'Communication Services', 'TMUS': 'Communication Services',
    'CHTR': 'Communication Services', 'EA': 'Communication Services', 'TTWO': 'Communication Services',
    'WBD': 'Communication Services', 'PARA': 'Communication Services', 'FOX': 'Communication Services',
    'FOXA': 'Communication Services', 'LYV': 'Communication Services', 'OMC': 'Communication Services',
    'IPG': 'Communication Services',
}


# =============================================================================
# INDICATOR CALCULATION
# =============================================================================

def calculate_rsi(prices: np.ndarray, period: int = 14) -> float:
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


def calculate_all_scores(
    prices: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    idx: int,
) -> Dict[str, float]:
    """Calculate all component scores at index"""
    if idx < 200:
        return {}

    current_price = prices[idx]
    scores = {}

    # RSI (0-3)
    rsi = calculate_rsi(prices[:idx+1])
    if rsi < 30:
        scores['rsi'] = 3.0
    elif rsi < 40:
        scores['rsi'] = 2.0
    elif rsi < 50:
        scores['rsi'] = 1.0
    else:
        scores['rsi'] = 0.0

    # Support (0-2.5)
    sma50 = np.mean(prices[idx-49:idx+1])
    support_distance = (current_price - sma50) / current_price * 100
    if support_distance < 3:
        scores['support'] = 2.5
    elif support_distance < 5:
        scores['support'] = 1.5
    elif support_distance < 10:
        scores['support'] = 0.5
    else:
        scores['support'] = 0.0

    # Fibonacci (0-2)
    high_52w = np.max(prices[max(0, idx-251):idx+1])
    low_52w = np.min(prices[max(0, idx-251):idx+1])
    fib_range = high_52w - low_52w
    if fib_range > 0:
        retrace = (high_52w - current_price) / fib_range
        if 0.50 <= retrace <= 0.65:
            scores['fibonacci'] = 2.0
        elif 0.36 <= retrace <= 0.42:
            scores['fibonacci'] = 1.5
        elif 0.22 <= retrace <= 0.28:
            scores['fibonacci'] = 1.0
        else:
            scores['fibonacci'] = 0.0
    else:
        scores['fibonacci'] = 0.0

    # MA (0-2)
    sma20 = np.mean(prices[idx-19:idx+1])
    sma200 = np.mean(prices[idx-199:idx+1])
    if current_price > sma200 and current_price < sma20:
        scores['ma'] = 2.0
    elif current_price > sma200:
        scores['ma'] = 1.0
    else:
        scores['ma'] = 0.0

    # Trend Strength (0-2)
    if sma20 > sma200:
        scores['trend'] = 2.0
    elif sma20 > sma200 * 0.98:
        scores['trend'] = 1.0
    else:
        scores['trend'] = 0.0

    # Volume (0-1)
    avg_vol = np.mean(volumes[idx-19:idx+1])
    vol_ratio = volumes[idx] / avg_vol if avg_vol > 0 else 1
    scores['volume'] = 1.0 if vol_ratio < 0.8 else 0.5 if vol_ratio < 1.2 else 0.0

    # MACD (0-1)
    ema12 = np.mean(prices[idx-11:idx+1])
    ema26 = np.mean(prices[idx-25:idx+1])
    scores['macd'] = 1.0 if ema12 > ema26 else 0.0

    # Stochastic (0-2)
    low14 = np.min(lows[idx-13:idx+1])
    high14 = np.max(highs[idx-13:idx+1])
    if high14 > low14:
        stoch = (current_price - low14) / (high14 - low14) * 100
        scores['stochastic'] = 2.0 if stoch < 20 else 1.0 if stoch < 30 else 0.0
    else:
        scores['stochastic'] = 0.0

    # Keltner (0-2)
    atr = np.mean(highs[idx-19:idx+1] - lows[idx-19:idx+1])
    keltner_lower = sma20 - 2 * atr
    if current_price < keltner_lower:
        scores['keltner'] = 2.0
    elif current_price < sma20:
        scores['keltner'] = 1.0
    else:
        scores['keltner'] = 0.0

    # ATH Distance (0-3) - for breakout
    ath_dist = (high_52w - current_price) / high_52w * 100
    if ath_dist < 2:
        scores['ath'] = 3.0
    elif ath_dist < 5:
        scores['ath'] = 2.0
    elif ath_dist < 10:
        scores['ath'] = 1.0
    else:
        scores['ath'] = 0.0

    # Bounce Support (0-2.5)
    low_20d = np.min(lows[idx-19:idx+1])
    bounce_dist = (current_price - low_20d) / low_20d * 100
    if bounce_dist < 1:
        scores['bounce'] = 2.5
    elif bounce_dist < 3:
        scores['bounce'] = 1.5
    elif bounce_dist < 5:
        scores['bounce'] = 0.5
    else:
        scores['bounce'] = 0.0

    return scores


def weighted_score(scores: Dict[str, float], weights: Dict[str, float]) -> float:
    """Calculate weighted total score"""
    total = 0.0
    for name, score in scores.items():
        total += score * weights.get(name, 1.0)
    return total


# =============================================================================
# TRAINING FUNCTIONS
# =============================================================================

def simulate_trade(prices: np.ndarray, entry_idx: int, dte: int = 45) -> bool:
    """Check if trade is a win (price stays above 95% of entry)"""
    entry_price = prices[entry_idx]
    short_strike = entry_price * 0.95

    exit_idx = min(entry_idx + dte, len(prices) - 1)
    return all(prices[j] > short_strike for j in range(entry_idx, exit_idx + 1))


def train_weights_for_group(
    symbol_data: List[Tuple[str, Dict]],
    group_name: str,
) -> Dict:
    """Train optimal weights for a group of symbols"""

    # Default weights
    default_weights = {
        'rsi': 1.0, 'support': 1.0, 'fibonacci': 1.0, 'ma': 1.0,
        'trend': 1.0, 'volume': 1.0, 'macd': 1.0, 'stochastic': 1.0,
        'keltner': 1.0, 'ath': 1.0, 'bounce': 1.0,
    }

    # Weight variations to test
    weight_variations = [default_weights.copy()]

    # Test emphasizing different components
    for component in ['rsi', 'support', 'ma', 'trend', 'ath', 'bounce']:
        for multiplier in [0.5, 1.5, 2.0]:
            w = default_weights.copy()
            w[component] = multiplier
            weight_variations.append(w)

    # Test combined variations
    combos = [
        {'rsi': 1.5, 'support': 1.5},
        {'rsi': 2.0, 'ma': 0.5},
        {'ath': 2.0, 'trend': 1.5},
        {'bounce': 2.0, 'support': 1.5},
        {'ma': 1.5, 'trend': 1.5, 'rsi': 0.5},
    ]
    for combo in combos:
        w = default_weights.copy()
        w.update(combo)
        weight_variations.append(w)

    # Test each weight configuration
    best_wr = 0
    best_weights = default_weights
    best_trades = 0

    results_by_weights = []

    for weights in weight_variations:
        trades = 0
        wins = 0

        for symbol, data in symbol_data:
            prices = data['prices']
            highs = data['highs']
            lows = data['lows']
            volumes = data['volumes']

            n = len(prices)
            if n < 252:
                continue

            # Test period: last 30%
            test_start = int(n * 0.7)

            for i in range(test_start, n - 50, 5):
                scores = calculate_all_scores(prices, highs, lows, volumes, i)
                if not scores:
                    continue

                total_score = weighted_score(scores, weights)

                if total_score >= 5.0:  # Signal threshold
                    win = simulate_trade(prices, i)
                    trades += 1
                    if win:
                        wins += 1

        if trades >= 20:  # Minimum sample size
            wr = wins / trades * 100
            results_by_weights.append({
                'weights': weights,
                'trades': trades,
                'wins': wins,
                'win_rate': wr,
            })

            if wr > best_wr:
                best_wr = wr
                best_weights = weights
                best_trades = trades

    # Also calculate strategy preferences
    strategy_performance = defaultdict(lambda: {'trades': 0, 'wins': 0})

    for symbol, data in symbol_data:
        prices = data['prices']
        highs = data['highs']
        lows = data['lows']

        n = len(prices)
        if n < 252:
            continue

        test_start = int(n * 0.7)

        for i in range(test_start, n - 50, 5):
            current_price = prices[i]
            rsi = calculate_rsi(prices[:i+1])
            sma20 = np.mean(prices[i-19:i+1])
            sma200 = np.mean(prices[i-199:i+1])
            high_52w = np.max(prices[max(0,i-251):i+1])
            low_20d = np.min(lows[i-19:i+1])

            strategies_triggered = []

            # Pullback
            if rsi < 40 and current_price > sma200 and current_price < sma20:
                strategies_triggered.append('pullback')

            # Bounce
            if (current_price - low_20d) / low_20d * 100 < 3 and current_price > sma200:
                strategies_triggered.append('bounce')

            # ATH Breakout
            if (high_52w - current_price) / high_52w * 100 < 5 and current_price > sma20:
                strategies_triggered.append('ath_breakout')

            # Earnings Dip
            recent_high = np.max(prices[max(0,i-20):i+1])
            drop_pct = (recent_high - current_price) / recent_high * 100
            if 5 <= drop_pct <= 15 and current_price > sma200:
                strategies_triggered.append('earnings_dip')

            # Simulate each strategy
            win = simulate_trade(prices, i)
            for strat in strategies_triggered:
                strategy_performance[strat]['trades'] += 1
                if win:
                    strategy_performance[strat]['wins'] += 1

    # Calculate strategy win rates
    strategy_win_rates = {}
    best_strategy = None
    best_strat_wr = 0

    for strat, perf in strategy_performance.items():
        if perf['trades'] >= 10:
            wr = perf['wins'] / perf['trades'] * 100
            strategy_win_rates[strat] = {
                'win_rate': wr,
                'trades': perf['trades'],
            }
            if wr > best_strat_wr:
                best_strat_wr = wr
                best_strategy = strat

    return {
        'group': group_name,
        'symbols': len(symbol_data),
        'optimal_weights': best_weights,
        'weight_win_rate': best_wr,
        'weight_trades': best_trades,
        'strategy_performance': strategy_win_rates,
        'best_strategy': best_strategy,
        'best_strategy_win_rate': best_strat_wr,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    logger.info("=" * 70)
    logger.info("  SECTOR & CLUSTER WEIGHT TRAINING")
    logger.info("  Started: %s", datetime.now())
    logger.info("=" * 70)

    # Load data
    tracker = TradeTracker()

    symbol_list = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_list if not s['symbol'].startswith('^')]
    logger.info("  Symbols available: %d", len(symbols))

    # Load cluster data
    cluster_path = Path.home() / '.optionplay' / 'models' / 'SYMBOL_CLUSTERS.json'
    cluster_data = {}
    if cluster_path.exists():
        with open(cluster_path, 'r') as f:
            data = json.load(f)
            cluster_data = data.get('symbol_to_cluster', {})
    logger.info("  Cluster data loaded: %d symbols", len(cluster_data))

    # Prepare symbol data
    symbol_data_all = {}
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars and len(price_data.bars) >= 252:
            symbol_data_all[symbol] = {
                'prices': np.array([b.close for b in price_data.bars]),
                'highs': np.array([b.high for b in price_data.bars]),
                'lows': np.array([b.low for b in price_data.bars]),
                'volumes': np.array([b.volume for b in price_data.bars]),
            }

    logger.info("  Symbols with sufficient data: %d", len(symbol_data_all))

    # Group by Sector
    sector_groups = defaultdict(list)
    for symbol, data in symbol_data_all.items():
        sector = SECTOR_MAP.get(symbol, 'Unknown')
        sector_groups[sector].append((symbol, data))

    # Group by Cluster
    cluster_groups = defaultdict(list)
    for symbol, data in symbol_data_all.items():
        if symbol in cluster_data:
            cluster_name = cluster_data[symbol].get('cluster_name', 'Unknown')
            cluster_groups[cluster_name].append((symbol, data))

    logger.info("  Sectors: %d", len(sector_groups))
    logger.info("  Clusters: %d", len(cluster_groups))
    logger.info("=" * 70)

    # Train Sector Weights
    logger.info("\nPhase 1: Training Sector Weights...")
    sector_results = {}

    for sector, symbols_data in sector_groups.items():
        if len(symbols_data) >= 5:  # Minimum 5 symbols per sector
            logger.info(f"  Training {sector} ({len(symbols_data)} symbols)...")
            result = train_weights_for_group(symbols_data, sector)
            sector_results[sector] = result

    # Train Cluster Weights
    logger.info("\nPhase 2: Training Cluster Weights...")
    cluster_results = {}

    for cluster, symbols_data in cluster_groups.items():
        if len(symbols_data) >= 5:  # Minimum 5 symbols per cluster
            logger.info(f"  Training {cluster} ({len(symbols_data)} symbols)...")
            result = train_weights_for_group(symbols_data, cluster)
            cluster_results[cluster] = result

    # Print Sector Results
    print("\n" + "=" * 90)
    print("SECTOR RESULTS")
    print("=" * 90)
    print(f"{'Sector':<25} {'Symbols':>8} {'WinRate':>10} {'BestStrategy':<15} {'StratWR':>10}")
    print("-" * 90)

    for sector, result in sorted(sector_results.items(), key=lambda x: x[1]['weight_win_rate'], reverse=True):
        print(f"{sector:<25} {result['symbols']:>8} {result['weight_win_rate']:>10.1f}% "
              f"{result['best_strategy'] or 'N/A':<15} {result['best_strategy_win_rate']:>10.1f}%")

    # Print Cluster Results
    print("\n" + "=" * 90)
    print("CLUSTER RESULTS")
    print("=" * 90)
    print(f"{'Cluster':<35} {'Symbols':>8} {'WinRate':>10} {'BestStrategy':<15} {'StratWR':>10}")
    print("-" * 90)

    for cluster, result in sorted(cluster_results.items(), key=lambda x: x[1]['weight_win_rate'], reverse=True):
        print(f"{cluster:<35} {result['symbols']:>8} {result['weight_win_rate']:>10.1f}% "
              f"{result['best_strategy'] or 'N/A':<15} {result['best_strategy_win_rate']:>10.1f}%")

    # Print top weight differences by sector
    print("\n" + "=" * 90)
    print("NOTABLE WEIGHT DIFFERENCES BY SECTOR")
    print("=" * 90)

    default_weights = {
        'rsi': 1.0, 'support': 1.0, 'fibonacci': 1.0, 'ma': 1.0,
        'trend': 1.0, 'volume': 1.0, 'macd': 1.0, 'stochastic': 1.0,
        'keltner': 1.0, 'ath': 1.0, 'bounce': 1.0,
    }

    for sector, result in sorted(sector_results.items(), key=lambda x: x[1]['weight_win_rate'], reverse=True)[:5]:
        differences = []
        for comp, weight in result['optimal_weights'].items():
            if weight != default_weights.get(comp, 1.0):
                differences.append(f"{comp}={weight}")
        if differences:
            print(f"{sector}: {', '.join(differences)}")

    # Save results
    output_path = Path.home() / '.optionplay' / 'models' / 'SECTOR_CLUSTER_WEIGHTS.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'sector_weights': {
                sector: {
                    'optimal_weights': result['optimal_weights'],
                    'win_rate': result['weight_win_rate'],
                    'trades': result['weight_trades'],
                    'best_strategy': result['best_strategy'],
                    'best_strategy_win_rate': result['best_strategy_win_rate'],
                    'strategy_performance': result['strategy_performance'],
                }
                for sector, result in sector_results.items()
            },
            'cluster_weights': {
                cluster: {
                    'optimal_weights': result['optimal_weights'],
                    'win_rate': result['weight_win_rate'],
                    'trades': result['weight_trades'],
                    'best_strategy': result['best_strategy'],
                    'best_strategy_win_rate': result['best_strategy_win_rate'],
                    'strategy_performance': result['strategy_performance'],
                }
                for cluster, result in cluster_results.items()
            },
        }, f, indent=2)

    logger.info(f"\nResults saved to {output_path}")

    logger.info("\n" + "=" * 70)
    logger.info("  SECTOR & CLUSTER WEIGHT TRAINING COMPLETE")
    logger.info("  Finished: %s", datetime.now())
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
