#!/usr/bin/env python3
"""
Ensemble Re-Training V2 - With New Features
============================================
Trainiert den Ensemble Meta-Learner mit:
- VWAP Score (neu aus Feature Engineering)
- Market Context Score (SPY Trend)
- Sector Score

Generiert Trades aus historischen Preisdaten und
trainiert dann den Meta-Learner für optimale Strategie-Auswahl.
"""

import sys
import json
import logging
import random
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from multiprocessing import Pool, cpu_count
from collections import defaultdict
import numpy as np

# Setup paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from backtesting.trade_tracker import TradeTracker
from backtesting.ensemble_selector import (
    EnsembleSelector,
    MetaLearner,
    StrategyScore,
    STRATEGIES,
)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

NUM_WORKERS = 10


# =============================================================================
# FEATURE CALCULATION
# =============================================================================

def calculate_rsi(prices: np.ndarray, period: int = 14) -> float:
    """Calculate RSI"""
    if len(prices) < period + 1:
        return 50.0

    deltas = np.diff(prices[-period-1:])
    gains = np.maximum(deltas, 0)
    losses = np.maximum(-deltas, 0)

    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_vwap(prices: np.ndarray, volumes: np.ndarray, period: int = 20) -> Tuple[float, float]:
    """Calculate VWAP and distance percentage"""
    if len(prices) < period or len(volumes) < period:
        return 0.0, 0.0

    vwap_prices = prices[-period:]
    vwap_volumes = volumes[-period:]
    total_vol = np.sum(vwap_volumes)

    if total_vol == 0:
        return 0.0, 0.0

    vwap = np.sum(vwap_prices * vwap_volumes) / total_vol
    current = prices[-1]
    distance = (current - vwap) / vwap * 100 if vwap > 0 else 0

    return vwap, distance


def get_market_context(spy_prices: np.ndarray) -> Tuple[float, str]:
    """Calculate market context score based on SPY trend"""
    if len(spy_prices) < 50:
        return 0.0, "unknown"

    current = spy_prices[-1]
    sma20 = np.mean(spy_prices[-20:])
    sma50 = np.mean(spy_prices[-50:])

    if current > sma20 > sma50:
        return 2.0, "strong_uptrend"
    elif current > sma50 and current > sma20:
        return 1.0, "uptrend"
    elif current > sma50:
        return 0.0, "sideways"
    elif current < sma20 < sma50:
        return -1.0, "strong_downtrend"
    else:
        return -0.5, "downtrend"


# Sector mapping
SECTOR_MAP = {
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology',
    'GOOGL': 'Communication', 'META': 'Communication', 'NFLX': 'Communication',
    'AMZN': 'Consumer_Disc', 'TSLA': 'Consumer_Disc', 'HD': 'Consumer_Disc',
    'KO': 'Consumer_Staples', 'PG': 'Consumer_Staples', 'WMT': 'Consumer_Staples',
    'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'PFE': 'Healthcare',
    'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy',
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities',
}

SECTOR_ADJUSTMENTS = {
    'Consumer_Staples': 0.9,
    'Utilities': 0.68,
    'Financials': 0.64,
    'Energy': -0.1,
    'Communication': -0.29,
    'Healthcare': -0.42,
    'Consumer_Disc': -0.69,
    'Technology': -1.0,
}


def get_sector_score(symbol: str) -> Tuple[float, str]:
    """Get sector score for a symbol"""
    sector = SECTOR_MAP.get(symbol.upper(), 'Unknown')
    adjustment = SECTOR_ADJUSTMENTS.get(sector, 0.0)
    return adjustment, sector


# =============================================================================
# SIGNAL GENERATION FOR ALL STRATEGIES
# =============================================================================

def generate_strategy_scores(
    prices: np.ndarray,
    volumes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    spy_prices: np.ndarray,
    symbol: str
) -> Dict[str, Dict[str, float]]:
    """
    Generate scores for all 4 strategies at current bar.
    Returns dict of strategy -> component scores.
    """
    n = len(prices)
    if n < 200:
        return {}

    current = prices[-1]
    scores = {}

    # Common calculations
    rsi = calculate_rsi(prices)
    sma20 = np.mean(prices[-20:])
    sma50 = np.mean(prices[-50:])
    sma200 = np.mean(prices[-200:])
    vwap, vwap_dist = calculate_vwap(prices, volumes)
    market_score, market_trend = get_market_context(spy_prices)
    sector_score, sector_name = get_sector_score(symbol)

    # Volume analysis
    avg_vol = np.mean(volumes[-20:])
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1

    # Support (simplified)
    low_52w = np.min(prices[-252:]) if n >= 252 else np.min(prices)
    high_52w = np.max(prices[-252:]) if n >= 252 else np.max(prices)

    # Stochastic
    low14 = np.min(lows[-14:])
    high14 = np.max(highs[-14:])
    stoch = (current - low14) / (high14 - low14) * 100 if high14 > low14 else 50

    # VWAP Score (0-3)
    if vwap_dist > 3:
        vwap_score = 3.0
    elif vwap_dist > 1:
        vwap_score = 2.0
    elif vwap_dist > -1:
        vwap_score = 1.0
    else:
        vwap_score = 0.0

    # =========================================================================
    # PULLBACK STRATEGY
    # =========================================================================
    pullback = {}

    # RSI (0-3)
    if rsi < 30:
        pullback['rsi_score'] = 3.0
    elif rsi < 40:
        pullback['rsi_score'] = 2.0
    elif rsi < 50:
        pullback['rsi_score'] = 1.0
    else:
        pullback['rsi_score'] = 0.0

    # Support (0-2.5)
    if current > sma200 and current < sma20:
        pullback['support_score'] = 2.5
    elif current > sma200:
        pullback['support_score'] = 1.5
    else:
        pullback['support_score'] = 0.0

    # Fibonacci (0-2)
    fib_range = high_52w - low_52w
    if fib_range > 0:
        retrace = (high_52w - current) / fib_range
        if 0.50 <= retrace <= 0.65:
            pullback['fibonacci_score'] = 2.0
        elif 0.36 <= retrace <= 0.42:
            pullback['fibonacci_score'] = 1.5
        else:
            pullback['fibonacci_score'] = 0.0
    else:
        pullback['fibonacci_score'] = 0.0

    # MA (0-2)
    pullback['ma_score'] = 2.0 if current > sma200 and current < sma20 else 1.0 if current > sma200 else 0.0

    # Trend strength (0-2)
    pullback['trend_strength_score'] = 2.0 if sma20 > sma200 else 0.0

    # Volume (0-1)
    pullback['volume_score'] = 1.0 if vol_ratio < 0.8 else 0.0

    # Stochastic (0-2)
    pullback['stoch_score'] = 2.0 if stoch < 20 else 1.0 if stoch < 30 else 0.0

    # New features
    pullback['vwap_score'] = vwap_score
    pullback['market_context_score'] = market_score
    pullback['sector_score'] = sector_score

    pullback['total'] = sum(pullback.values())
    scores['pullback'] = pullback

    # =========================================================================
    # BOUNCE STRATEGY
    # =========================================================================
    bounce = {}
    bounce['rsi_score'] = pullback['rsi_score']
    bounce['support_score'] = pullback['support_score']
    bounce['volume_score'] = pullback['volume_score']
    bounce['ma_score'] = pullback['ma_score']
    bounce['stoch_score'] = pullback['stoch_score']

    # Candlestick (simplified - 0-2)
    prev_close = prices[-2] if n > 1 else current
    if current > prev_close and lows[-1] < prev_close * 0.98:
        bounce['candlestick_score'] = 2.0  # Hammer-like
    else:
        bounce['candlestick_score'] = 0.0

    bounce['vwap_score'] = vwap_score
    bounce['market_context_score'] = market_score
    bounce['sector_score'] = sector_score

    bounce['total'] = sum(bounce.values())
    scores['bounce'] = bounce

    # =========================================================================
    # ATH BREAKOUT STRATEGY
    # =========================================================================
    ath_breakout = {}

    # ATH Breakout (0-3)
    if current >= high_52w * 0.98:
        ath_breakout['ath_breakout_score'] = 3.0
    elif current >= high_52w * 0.95:
        ath_breakout['ath_breakout_score'] = 2.0
    else:
        ath_breakout['ath_breakout_score'] = 0.0

    # Volume confirmation (0-2)
    ath_breakout['volume_score'] = 2.0 if vol_ratio > 1.5 else 1.0 if vol_ratio > 1.2 else 0.0

    # MA alignment (0-2)
    ath_breakout['ma_score'] = 2.0 if current > sma20 > sma50 > sma200 else 1.0 if current > sma200 else 0.0

    # RSI momentum (0-2)
    ath_breakout['rsi_score'] = 2.0 if 50 < rsi < 70 else 1.0 if rsi > 40 else 0.0

    # Momentum (0-2)
    roc_10 = (current - prices[-10]) / prices[-10] * 100 if n > 10 else 0
    ath_breakout['momentum_score'] = 2.0 if roc_10 > 5 else 1.0 if roc_10 > 2 else 0.0

    ath_breakout['vwap_score'] = vwap_score
    ath_breakout['market_context_score'] = market_score
    ath_breakout['sector_score'] = sector_score

    ath_breakout['total'] = sum(ath_breakout.values())
    scores['ath_breakout'] = ath_breakout

    # =========================================================================
    # EARNINGS DIP STRATEGY
    # =========================================================================
    earnings_dip = {}

    # Dip magnitude (0-3)
    week_ago = prices[-5] if n > 5 else current
    dip_pct = (week_ago - current) / week_ago * 100 if week_ago > 0 else 0

    if 5 < dip_pct < 15:
        earnings_dip['dip_score'] = 3.0
    elif 3 < dip_pct < 20:
        earnings_dip['dip_score'] = 2.0
    else:
        earnings_dip['dip_score'] = 0.0

    # Gap analysis (0-1)
    earnings_dip['gap_score'] = 1.0 if dip_pct > 3 else 0.0

    # RSI (0-2)
    earnings_dip['rsi_score'] = pullback['rsi_score']

    # Stabilization (0-2)
    daily_range = (highs[-1] - lows[-1]) / current * 100
    earnings_dip['stabilization_score'] = 2.0 if daily_range < 2 else 1.0 if daily_range < 4 else 0.0

    earnings_dip['volume_score'] = pullback['volume_score']
    earnings_dip['ma_score'] = pullback['ma_score']
    earnings_dip['stoch_score'] = pullback['stoch_score']

    earnings_dip['vwap_score'] = vwap_score
    earnings_dip['market_context_score'] = market_score
    earnings_dip['sector_score'] = sector_score

    earnings_dip['total'] = sum(earnings_dip.values())
    scores['earnings_dip'] = earnings_dip

    return scores


# =============================================================================
# TRADE SIMULATION
# =============================================================================

def simulate_trade(
    prices: np.ndarray,
    entry_idx: int,
    strategy: str,
    dte: int = 30
) -> Tuple[bool, float]:
    """
    Simulate a Bull-Put-Spread trade.
    Returns (win, pnl_pct)
    """
    if entry_idx + dte >= len(prices):
        return False, 0.0

    entry_price = prices[entry_idx]
    short_strike = entry_price * 0.95  # 5% OTM

    # Check if price stays above short strike
    exit_idx = entry_idx + dte
    trade_prices = prices[entry_idx:exit_idx+1]

    win = all(p > short_strike for p in trade_prices)

    if win:
        pnl_pct = 30.0  # 30% of credit (max profit)
    else:
        # Partial loss based on how far it dropped
        min_price = np.min(trade_prices)
        if min_price < short_strike:
            loss_depth = (short_strike - min_price) / (entry_price * 0.05)
            pnl_pct = -min(100.0, loss_depth * 70)  # Max 100% loss
        else:
            pnl_pct = 30.0

    return win, pnl_pct


# =============================================================================
# WORKER FUNCTION
# =============================================================================

def analyze_symbol(args: Tuple) -> Dict[str, Any]:
    """Analyze one symbol for all strategies"""
    symbol, bars_data, spy_arr = args

    prices = bars_data['prices']
    volumes = bars_data['volumes']
    highs = bars_data['highs']
    lows = bars_data['lows']

    n = len(prices)
    if n < 300:
        return {'symbol': symbol, 'trades': []}

    trades = []

    # Generate signals and trades every 10 days
    for i in range(200, n - 35, 10):
        # Get scores for all strategies
        all_scores = generate_strategy_scores(
            prices[:i+1], volumes[:i+1], highs[:i+1], lows[:i+1],
            spy_arr[:i+1] if spy_arr is not None and len(spy_arr) > i else spy_arr,
            symbol
        )

        if not all_scores:
            continue

        # For each strategy with score > threshold, simulate trade
        for strategy, scores in all_scores.items():
            total = scores.get('total', 0)
            threshold = 5.0 if strategy in ['pullback', 'bounce'] else 6.0

            if total >= threshold:
                win, pnl = simulate_trade(prices, i, strategy)

                trades.append({
                    'symbol': symbol,
                    'strategy': strategy,
                    'entry_idx': i,
                    'total_score': total,
                    'scores': {k: v for k, v in scores.items() if k != 'total'},
                    'win': win,
                    'pnl_pct': pnl,
                    'vwap_score': scores.get('vwap_score', 0),
                    'market_context_score': scores.get('market_context_score', 0),
                    'sector_score': scores.get('sector_score', 0),
                })

    return {'symbol': symbol, 'trades': trades}


# =============================================================================
# META-LEARNER TRAINING
# =============================================================================

def train_meta_learner(all_trades: List[Dict]) -> Dict[str, Any]:
    """
    Train the meta-learner from trade results.

    Learns:
    - Which strategy works best per symbol
    - How new features affect win rate
    - Regime-specific strategy preferences
    """
    # Aggregate by symbol and strategy
    symbol_strategy_perf = defaultdict(lambda: defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0}))
    strategy_perf = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0})

    # Feature impact analysis
    vwap_buckets = defaultdict(lambda: {'wins': 0, 'total': 0})
    market_buckets = defaultdict(lambda: {'wins': 0, 'total': 0})
    sector_buckets = defaultdict(lambda: {'wins': 0, 'total': 0})

    for trade in all_trades:
        symbol = trade['symbol']
        strategy = trade['strategy']
        win = trade['win']
        pnl = trade['pnl_pct']

        # Symbol-strategy performance
        if win:
            symbol_strategy_perf[symbol][strategy]['wins'] += 1
            strategy_perf[strategy]['wins'] += 1
        else:
            symbol_strategy_perf[symbol][strategy]['losses'] += 1
            strategy_perf[strategy]['losses'] += 1
        symbol_strategy_perf[symbol][strategy]['total_pnl'] += pnl
        strategy_perf[strategy]['total_pnl'] += pnl

        # Feature buckets
        vwap = trade.get('vwap_score', 0)
        vwap_bucket = 'high' if vwap >= 2 else 'medium' if vwap >= 1 else 'low'
        vwap_buckets[vwap_bucket]['total'] += 1
        if win:
            vwap_buckets[vwap_bucket]['wins'] += 1

        market = trade.get('market_context_score', 0)
        market_bucket = 'uptrend' if market >= 1 else 'sideways' if market >= 0 else 'downtrend'
        market_buckets[market_bucket]['total'] += 1
        if win:
            market_buckets[market_bucket]['wins'] += 1

        sector = trade.get('sector_score', 0)
        sector_bucket = 'favorable' if sector > 0.3 else 'unfavorable' if sector < -0.3 else 'neutral'
        sector_buckets[sector_bucket]['total'] += 1
        if win:
            sector_buckets[sector_bucket]['wins'] += 1

    # Calculate win rates
    def calc_win_rate(d):
        total = d['wins'] + d['losses']
        return d['wins'] / total * 100 if total > 0 else 0

    # Symbol best strategies
    symbol_best = {}
    for symbol, strategies in symbol_strategy_perf.items():
        best_strategy = None
        best_wr = 0
        for strategy, perf in strategies.items():
            wr = calc_win_rate(perf)
            if wr > best_wr:
                best_wr = wr
                best_strategy = strategy
        if best_strategy:
            symbol_best[symbol] = {
                'strategy': best_strategy,
                'win_rate': best_wr,
                'trades': perf['wins'] + perf['losses']
            }

    # Strategy overall performance
    strategy_results = {}
    for strategy, perf in strategy_perf.items():
        strategy_results[strategy] = {
            'win_rate': calc_win_rate(perf),
            'total_trades': perf['wins'] + perf['losses'],
            'total_pnl': perf['total_pnl']
        }

    # Feature impact
    feature_impact = {
        'vwap': {k: {'win_rate': v['wins']/v['total']*100 if v['total']>0 else 0, 'trades': v['total']}
                 for k, v in vwap_buckets.items()},
        'market_context': {k: {'win_rate': v['wins']/v['total']*100 if v['total']>0 else 0, 'trades': v['total']}
                          for k, v in market_buckets.items()},
        'sector': {k: {'win_rate': v['wins']/v['total']*100 if v['total']>0 else 0, 'trades': v['total']}
                   for k, v in sector_buckets.items()},
    }

    return {
        'strategy_performance': strategy_results,
        'symbol_preferences': symbol_best,
        'feature_impact': feature_impact,
        'total_trades': len(all_trades),
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    logger.info("=" * 70)
    logger.info("  ENSEMBLE RE-TRAINING V2 - With New Features")
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
        if price_data and price_data.bars and len(price_data.bars) >= 300:
            bars_data = {
                'prices': np.array([b.close for b in price_data.bars]),
                'volumes': np.array([b.volume for b in price_data.bars]),
                'highs': np.array([b.high for b in price_data.bars]),
                'lows': np.array([b.low for b in price_data.bars])
            }
            symbol_data.append((symbol, bars_data, spy_arr))

    logger.info("  Symbols with sufficient data: %d", len(symbol_data))
    logger.info("=" * 70)

    # Run analysis
    logger.info("\nPhase 1: Generating trades for all strategies...")

    all_trades = []
    with Pool(NUM_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(analyze_symbol, symbol_data)):
            all_trades.extend(result.get('trades', []))
            if (i + 1) % 50 == 0:
                logger.info(f"  Processed {i+1}/{len(symbol_data)} symbols... ({len(all_trades)} trades)")

    logger.info(f"  Total trades generated: {len(all_trades)}")

    # Train meta-learner
    logger.info("\nPhase 2: Training Meta-Learner...")
    meta_learner_result = train_meta_learner(all_trades)

    # Print results
    print("\n" + "=" * 80)
    print("STRATEGY PERFORMANCE")
    print("=" * 80)
    print(f"{'Strategy':<15} {'WinRate':<10} {'Trades':<10} {'TotalPnL':<12}")
    print("-" * 80)

    for strategy, perf in meta_learner_result['strategy_performance'].items():
        print(f"{strategy:<15} {perf['win_rate']:<10.1f} {perf['total_trades']:<10} ${perf['total_pnl']:<11,.0f}")

    print("\n" + "=" * 80)
    print("FEATURE IMPACT ANALYSIS")
    print("=" * 80)

    print("\nVWAP Score Impact:")
    for bucket, data in meta_learner_result['feature_impact']['vwap'].items():
        print(f"  {bucket:<10}: {data['win_rate']:.1f}% ({data['trades']} trades)")

    print("\nMarket Context Impact:")
    for bucket, data in meta_learner_result['feature_impact']['market_context'].items():
        print(f"  {bucket:<10}: {data['win_rate']:.1f}% ({data['trades']} trades)")

    print("\nSector Score Impact:")
    for bucket, data in meta_learner_result['feature_impact']['sector'].items():
        print(f"  {bucket:<10}: {data['win_rate']:.1f}% ({data['trades']} trades)")

    # Save results
    output_path = Path.home() / '.optionplay' / 'models' / 'ENSEMBLE_V2_TRAINED.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'training_version': '2.0',
            'total_trades': len(all_trades),
            'symbols_analyzed': len(symbol_data),
            'features_used': ['vwap_score', 'market_context_score', 'sector_score'],
            'strategy_performance': meta_learner_result['strategy_performance'],
            'feature_impact': meta_learner_result['feature_impact'],
            'top_symbol_preferences': dict(list(meta_learner_result['symbol_preferences'].items())[:50]),
        }, f, indent=2)

    logger.info(f"\nResults saved to {output_path}")

    # Also update the ensemble selector model file
    ensemble_output = Path.home() / '.optionplay' / 'models' / f'ensemble_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(ensemble_output, 'w') as f:
        json.dump({
            'version': '2.0',
            'created_at': datetime.now().isoformat(),
            'trained_with_features': ['vwap', 'market_context', 'sector'],
            'strategy_weights': {
                s: perf['win_rate'] / 100
                for s, perf in meta_learner_result['strategy_performance'].items()
            },
        }, f, indent=2)

    logger.info(f"Ensemble model saved to {ensemble_output}")

    logger.info("\n" + "=" * 70)
    logger.info("  ENSEMBLE RE-TRAINING COMPLETE")
    logger.info("  Finished: %s", datetime.now())
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
