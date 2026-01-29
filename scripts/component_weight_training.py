#!/usr/bin/env python3
"""
Component Weight Training - Phase 2 (Optimized)
================================================
Optimiert die Gewichte für alle Scoring-Komponenten.
Verwendet Grid Search statt genetischen Algorithmus für Geschwindigkeit.
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
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
# COMPONENT NAMES AND DEFAULT WEIGHTS
# =============================================================================

COMPONENT_NAMES = [
    'rsi', 'support', 'fibonacci', 'ma', 'trend_strength',
    'volume', 'macd', 'stochastic', 'keltner',
    'vwap', 'market_context', 'sector'
]

DEFAULT_WEIGHTS = {
    'rsi': 1.0, 'support': 1.0, 'fibonacci': 1.0, 'ma': 1.0,
    'trend_strength': 1.0, 'volume': 1.0, 'macd': 1.0,
    'stochastic': 1.0, 'keltner': 1.0,
    'vwap': 1.5, 'market_context': 1.2, 'sector': 0.5
}


# =============================================================================
# SIGNAL CALCULATION (Simplified for speed)
# =============================================================================

def calculate_component_scores_fast(
    prices: np.ndarray,
    volumes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    spy_prices: Optional[np.ndarray] = None
) -> Dict[str, float]:
    """Fast component score calculation using NumPy arrays"""

    n = len(prices)
    if n < 200:
        return {}

    current_price = prices[-1]
    scores = {}

    # RSI (0-3)
    deltas = np.diff(prices[-15:])
    gains = np.maximum(deltas, 0)
    losses = np.maximum(-deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - (100 / (1 + rs))

    if rsi < 30:
        scores['rsi'] = 3.0
    elif rsi < 40:
        scores['rsi'] = 2.0
    elif rsi < 50:
        scores['rsi'] = 1.0
    else:
        scores['rsi'] = 0.0

    # Support (0-2.5)
    sma50 = np.mean(prices[-50:])
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
    high_52w = np.max(prices[-252:]) if n >= 252 else np.max(prices)
    low_52w = np.min(prices[-252:]) if n >= 252 else np.min(prices)
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
    sma20 = np.mean(prices[-20:])
    sma200 = np.mean(prices[-200:])
    if current_price > sma200 and current_price < sma20:
        scores['ma'] = 2.0
    elif current_price > sma200:
        scores['ma'] = 1.0
    else:
        scores['ma'] = 0.0

    # Trend Strength (0-2)
    if sma20 > sma200:
        scores['trend_strength'] = 2.0
    elif sma20 > sma200 * 0.98:
        scores['trend_strength'] = 1.0
    else:
        scores['trend_strength'] = 0.0

    # Volume (0-1)
    avg_vol = np.mean(volumes[-20:])
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
    scores['volume'] = 1.0 if vol_ratio < 0.8 else 0.5 if vol_ratio < 1.2 else 0.0

    # MACD (0-2)
    ema12 = np.mean(prices[-12:])  # Simplified
    ema26 = np.mean(prices[-26:])
    scores['macd'] = 1.0 if ema12 > ema26 else 0.0

    # Stochastic (0-2)
    low14 = np.min(lows[-14:])
    high14 = np.max(highs[-14:])
    if high14 > low14:
        stoch = (current_price - low14) / (high14 - low14) * 100
        scores['stochastic'] = 2.0 if stoch < 20 else 1.0 if stoch < 30 else 0.0
    else:
        scores['stochastic'] = 0.0

    # Keltner (0-2)
    atr = np.mean(highs[-20:] - lows[-20:])
    keltner_lower = sma20 - 2 * atr
    if current_price < keltner_lower:
        scores['keltner'] = 2.0
    elif current_price < sma20:
        scores['keltner'] = 1.0
    else:
        scores['keltner'] = 0.0

    # VWAP (0-3)
    vwap_prices = prices[-20:]
    vwap_volumes = volumes[-20:]
    total_vol = np.sum(vwap_volumes)
    if total_vol > 0:
        vwap = np.sum(vwap_prices * vwap_volumes) / total_vol
        vwap_dist = (current_price - vwap) / vwap * 100
        if vwap_dist > 3:
            scores['vwap'] = 3.0
        elif vwap_dist > 1:
            scores['vwap'] = 2.0
        elif vwap_dist > -1:
            scores['vwap'] = 1.0
        else:
            scores['vwap'] = 0.0
    else:
        scores['vwap'] = 0.0

    # Market Context (-1 to +2)
    if spy_prices is not None and len(spy_prices) >= 50:
        spy_curr = spy_prices[-1]
        spy_sma20 = np.mean(spy_prices[-20:])
        spy_sma50 = np.mean(spy_prices[-50:])
        if spy_curr > spy_sma20 > spy_sma50:
            scores['market_context'] = 2.0
        elif spy_curr > spy_sma50:
            scores['market_context'] = 1.0
        elif spy_curr < spy_sma20 < spy_sma50:
            scores['market_context'] = -1.0
        else:
            scores['market_context'] = 0.0
    else:
        scores['market_context'] = 0.0

    # Sector (placeholder)
    scores['sector'] = 0.0

    return scores


def weighted_score(scores: Dict[str, float], weights: Dict[str, float]) -> float:
    """Calculate weighted total score"""
    total = 0.0
    for name, score in scores.items():
        total += score * weights.get(name, 1.0)
    return total


# =============================================================================
# SYMBOL ANALYSIS WORKER
# =============================================================================

def analyze_symbol_with_weights(args: Tuple) -> Dict:
    """Analyze single symbol with given weight set"""
    symbol, bars_data, spy_arr, weight_sets = args

    prices = bars_data['prices']
    volumes = bars_data['volumes']
    highs = bars_data['highs']
    lows = bars_data['lows']

    n = len(prices)
    if n < 250:
        return {'symbol': symbol, 'results': []}

    results = []

    # Pre-calculate component scores at each valid index
    score_cache = {}
    for i in range(200, n - 30, 5):  # Sample every 5 days
        scores = calculate_component_scores_fast(
            prices[:i+1], volumes[:i+1], highs[:i+1], lows[:i+1],
            spy_arr[:i+1] if spy_arr is not None else None
        )
        if scores:
            score_cache[i] = scores

    # Test each weight set
    for weight_idx, weights in enumerate(weight_sets):
        trades = 0
        wins = 0

        for i, scores in score_cache.items():
            total_score = weighted_score(scores, weights)

            if total_score >= 5.0:  # Signal threshold
                # Check if trade would be a win
                entry_price = prices[i]
                short_strike = entry_price * 0.95

                # Check next 30 days
                exit_idx = min(i + 30, n - 1)
                win = all(prices[j] > short_strike for j in range(i, exit_idx + 1))

                trades += 1
                if win:
                    wins += 1

        if trades > 0:
            results.append({
                'weight_idx': weight_idx,
                'trades': trades,
                'wins': wins,
                'win_rate': wins / trades * 100
            })

    return {'symbol': symbol, 'results': results}


# =============================================================================
# MAIN TRAINING
# =============================================================================

def generate_weight_variations() -> List[Dict[str, float]]:
    """Generate weight variations to test"""
    variations = []

    # Default weights
    variations.append(DEFAULT_WEIGHTS.copy())

    # Emphasize new features
    for vwap_w in [1.0, 1.5, 2.0, 2.5]:
        for market_w in [0.5, 1.0, 1.5, 2.0]:
            for sector_w in [0.0, 0.5, 1.0]:
                w = DEFAULT_WEIGHTS.copy()
                w['vwap'] = vwap_w
                w['market_context'] = market_w
                w['sector'] = sector_w
                variations.append(w)

    # Emphasize traditional indicators
    for rsi_w in [1.0, 1.5, 2.0]:
        for support_w in [1.0, 1.5, 2.0]:
            w = DEFAULT_WEIGHTS.copy()
            w['rsi'] = rsi_w
            w['support'] = support_w
            variations.append(w)

    # Reduce duplicates
    unique = []
    seen = set()
    for w in variations:
        key = tuple(sorted(w.items()))
        if key not in seen:
            seen.add(key)
            unique.append(w)

    return unique[:100]  # Limit to 100 variations


def main():
    logger.info("=" * 70)
    logger.info("  COMPONENT WEIGHT TRAINING - Phase 2 (Optimized)")
    logger.info("  Workers: %d / %d cores", NUM_WORKERS, cpu_count())
    logger.info("  Started: %s", datetime.now())
    logger.info("=" * 70)

    # Load data
    tracker = TradeTracker()

    symbol_list = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_list if not s['symbol'].startswith('^')]
    logger.info("  Symbols available: %d", len(symbols))

    # Load SPY data
    spy_arr = None
    spy_data = tracker.get_price_data('SPY')
    if spy_data and spy_data.bars:
        spy_arr = np.array([b.close for b in spy_data.bars])
    logger.info("  SPY bars: %d", len(spy_arr) if spy_arr is not None else 0)

    # Prepare symbol data
    symbol_data = []
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars and len(price_data.bars) >= 250:
            bars_data = {
                'prices': np.array([b.close for b in price_data.bars]),
                'volumes': np.array([b.volume for b in price_data.bars]),
                'highs': np.array([b.high for b in price_data.bars]),
                'lows': np.array([b.low for b in price_data.bars])
            }
            symbol_data.append((symbol, bars_data))

    logger.info("  Symbols with sufficient data: %d", len(symbol_data))

    # Generate weight variations
    weight_sets = generate_weight_variations()
    logger.info("  Weight variations to test: %d", len(weight_sets))
    logger.info("=" * 70)

    # Prepare worker arguments
    worker_args = [(sym, data, spy_arr, weight_sets) for sym, data in symbol_data]

    # Run analysis
    logger.info("\nAnalyzing symbols...")
    all_results = []
    with Pool(NUM_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(analyze_symbol_with_weights, worker_args)):
            all_results.append(result)
            if (i + 1) % 50 == 0:
                logger.info(f"  Processed {i+1}/{len(worker_args)} symbols...")

    logger.info(f"  Completed: {len(all_results)} symbols")

    # Aggregate results by weight set
    logger.info("\nAggregating results...")
    weight_totals = defaultdict(lambda: {'trades': 0, 'wins': 0})

    for result in all_results:
        for wr in result.get('results', []):
            idx = wr['weight_idx']
            weight_totals[idx]['trades'] += wr['trades']
            weight_totals[idx]['wins'] += wr['wins']

    # Calculate win rates
    weight_performance = []
    for idx, totals in weight_totals.items():
        if totals['trades'] > 0:
            win_rate = totals['wins'] / totals['trades'] * 100
            weight_performance.append({
                'weight_idx': idx,
                'weights': weight_sets[idx],
                'trades': totals['trades'],
                'wins': totals['wins'],
                'win_rate': win_rate
            })

    # Sort by win rate
    weight_performance.sort(key=lambda x: x['win_rate'], reverse=True)

    # Print results
    print("\n" + "=" * 80)
    print("TOP 15 WEIGHT CONFIGURATIONS BY WIN RATE")
    print("=" * 80)
    print(f"{'Rank':<5} {'Trades':<10} {'WinRate':<10} {'VWAP':<8} {'Market':<8} {'Sector':<8} {'RSI':<8}")
    print("-" * 80)

    for i, wp in enumerate(weight_performance[:15], 1):
        w = wp['weights']
        print(f"{i:<5} {wp['trades']:<10} {wp['win_rate']:<10.1f} "
              f"{w['vwap']:<8.1f} {w['market_context']:<8.1f} {w['sector']:<8.1f} {w['rsi']:<8.1f}")

    # Best configuration
    if weight_performance:
        best = weight_performance[0]
        print("\n" + "=" * 80)
        print("BEST WEIGHT CONFIGURATION")
        print("=" * 80)
        print(f"\nTotal Trades: {best['trades']:,}")
        print(f"Win Rate: {best['win_rate']:.1f}%")
        print("\nOptimal Weights:")

        sorted_weights = sorted(best['weights'].items(), key=lambda x: x[1], reverse=True)
        for name, weight in sorted_weights:
            print(f"  {name:20s}: {weight:.2f}")

        # Save results
        output_path = Path.home() / '.optionplay' / 'models' / 'COMPONENT_WEIGHTS_TRAINED.json'
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'training_type': 'grid_search',
                'variations_tested': len(weight_sets),
                'symbols_used': len(symbol_data),
                'best_performance': {
                    'trades': best['trades'],
                    'wins': best['wins'],
                    'win_rate': best['win_rate']
                },
                'optimal_weights': best['weights'],
                'top_10_configurations': [
                    {
                        'rank': i+1,
                        'trades': wp['trades'],
                        'win_rate': wp['win_rate'],
                        'weights': wp['weights']
                    }
                    for i, wp in enumerate(weight_performance[:10])
                ]
            }, f, indent=2)

        logger.info(f"\nResults saved to {output_path}")

    logger.info("\n" + "=" * 70)
    logger.info("  COMPONENT WEIGHT TRAINING COMPLETE")
    logger.info("  Finished: %s", datetime.now())
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
