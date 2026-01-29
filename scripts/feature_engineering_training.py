#!/usr/bin/env python3
"""
Feature Engineering Training
============================
Trainiert und analysiert neue Features:
1. Volume Profile (VWAP, POC)
2. SPY/QQQ Korrelation als Marktfilter
3. Sektor-basierte Anpassungen
4. Feature-Importance Analyse

Parallelisiert mit 10 Workern für M2.
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field, asdict
from multiprocessing import Pool, cpu_count
from collections import defaultdict
import numpy as np

# Setup paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from backtesting.trade_tracker import TradeTracker


def get_price_bars(tracker: TradeTracker, symbol: str) -> List[Dict]:
    """Load price bars for a symbol as list of dicts."""
    price_data = tracker.get_price_data(symbol)
    if not price_data or not price_data.bars:
        return []
    return [
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

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

NUM_WORKERS = 10
MODELS_DIR = Path.home() / ".optionplay" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Sector mapping (GICS-based)
SECTOR_MAP = {
    # Technology
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'AVGO': 'Technology',
    'CSCO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology', 'ORCL': 'Technology',
    'ACN': 'Technology', 'IBM': 'Technology', 'INTC': 'Technology', 'AMD': 'Technology',
    'QCOM': 'Technology', 'TXN': 'Technology', 'AMAT': 'Technology', 'ADI': 'Technology',
    'MU': 'Technology', 'LRCX': 'Technology', 'KLAC': 'Technology', 'SNPS': 'Technology',
    'CDNS': 'Technology', 'MCHP': 'Technology', 'HPQ': 'Technology', 'HPE': 'Technology',

    # Communication Services
    'GOOGL': 'Communication', 'GOOG': 'Communication', 'META': 'Communication',
    'NFLX': 'Communication', 'DIS': 'Communication', 'CMCSA': 'Communication',
    'VZ': 'Communication', 'T': 'Communication', 'TMUS': 'Communication',

    # Consumer Discretionary
    'AMZN': 'Consumer_Disc', 'TSLA': 'Consumer_Disc', 'HD': 'Consumer_Disc',
    'NKE': 'Consumer_Disc', 'MCD': 'Consumer_Disc', 'SBUX': 'Consumer_Disc',
    'LOW': 'Consumer_Disc', 'TJX': 'Consumer_Disc', 'BKNG': 'Consumer_Disc',

    # Consumer Staples
    'PG': 'Consumer_Staples', 'KO': 'Consumer_Staples', 'PEP': 'Consumer_Staples',
    'COST': 'Consumer_Staples', 'WMT': 'Consumer_Staples', 'PM': 'Consumer_Staples',
    'MO': 'Consumer_Staples', 'CL': 'Consumer_Staples', 'KMB': 'Consumer_Staples',
    'GIS': 'Consumer_Staples', 'K': 'Consumer_Staples', 'KR': 'Consumer_Staples',

    # Healthcare
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'PFE': 'Healthcare',
    'ABBV': 'Healthcare', 'MRK': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'BMY': 'Healthcare', 'AMGN': 'Healthcare', 'MDT': 'Healthcare',
    'GILD': 'Healthcare', 'CVS': 'Healthcare', 'BSX': 'Healthcare',

    # Financials
    'BRK.B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'BLK': 'Financials', 'C': 'Financials', 'AXP': 'Financials', 'SCHW': 'Financials',
    'CB': 'Financials', 'MMC': 'Financials', 'PGR': 'Financials', 'MET': 'Financials',
    'AIG': 'Financials', 'AFL': 'Financials', 'TRV': 'Financials', 'CME': 'Financials',

    # Industrials
    'GE': 'Industrials', 'CAT': 'Industrials', 'HON': 'Industrials', 'UNP': 'Industrials',
    'BA': 'Industrials', 'RTX': 'Industrials', 'DE': 'Industrials', 'LMT': 'Industrials',
    'UPS': 'Industrials', 'ADP': 'Industrials', 'MMM': 'Industrials', 'GD': 'Industrials',
    'ITW': 'Industrials', 'EMR': 'Industrials', 'ETN': 'Industrials', 'WM': 'Industrials',

    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'EOG': 'Energy',
    'SLB': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'OXY': 'Energy', 'KMI': 'Energy', 'WMB': 'Energy', 'HAL': 'Energy',

    # Materials
    'LIN': 'Materials', 'APD': 'Materials', 'SHW': 'Materials', 'ECL': 'Materials',
    'DD': 'Materials', 'NEM': 'Materials', 'FCX': 'Materials', 'NUE': 'Materials',

    # Real Estate
    'AMT': 'Real_Estate', 'PLD': 'Real_Estate', 'CCI': 'Real_Estate', 'EQIX': 'Real_Estate',
    'PSA': 'Real_Estate', 'O': 'Real_Estate', 'SPG': 'Real_Estate', 'AVB': 'Real_Estate',
    'EQR': 'Real_Estate', 'DLR': 'Real_Estate', 'WELL': 'Real_Estate', 'VTR': 'Real_Estate',
    'MAA': 'Real_Estate', 'CPT': 'Real_Estate', 'KIM': 'Real_Estate', 'INVH': 'Real_Estate',

    # Utilities
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities',
    'AEP': 'Utilities', 'EXC': 'Utilities', 'SRE': 'Utilities', 'XEL': 'Utilities',
    'ED': 'Utilities', 'WEC': 'Utilities', 'ES': 'Utilities', 'AWK': 'Utilities',
    'DTE': 'Utilities', 'AEE': 'Utilities', 'CMS': 'Utilities', 'ETR': 'Utilities',
    'FE': 'Utilities', 'EIX': 'Utilities', 'EVRG': 'Utilities', 'LNT': 'Utilities',
    'ATO': 'Utilities',
}


@dataclass
class FeatureMetrics:
    """Metrics for a single feature"""
    feature_name: str
    correlation_with_win: float = 0.0
    information_gain: float = 0.0
    mean_when_win: float = 0.0
    mean_when_loss: float = 0.0
    separation: float = 0.0  # How well it separates wins from losses


@dataclass
class TradeWithFeatures:
    """Single trade with all feature values"""
    symbol: str
    date: str
    strategy: str
    entry_price: float
    exit_price: float
    is_win: bool
    pnl: float
    vix: float

    # Existing features
    rsi: float = 0.0
    macd_histogram: float = 0.0
    stoch_k: float = 0.0
    support_distance_pct: float = 0.0
    volume_ratio: float = 0.0
    trend_strength: float = 0.0

    # New features
    vwap_distance_pct: float = 0.0
    volume_profile_poc_distance: float = 0.0
    spy_correlation_20d: float = 0.0
    qqq_correlation_20d: float = 0.0
    spy_trend: str = ""
    sector: str = ""
    sector_relative_strength: float = 0.0

    # Feature scores
    score: float = 0.0


def calculate_vwap(prices: List[float], volumes: List[int], period: int = 20) -> float:
    """
    Calculate Volume Weighted Average Price.

    VWAP = Sum(Price * Volume) / Sum(Volume)
    """
    if len(prices) < period or len(volumes) < period:
        return prices[-1] if prices else 0

    prices_arr = np.array(prices[-period:])
    volumes_arr = np.array(volumes[-period:])

    if np.sum(volumes_arr) == 0:
        return float(np.mean(prices_arr))

    vwap = np.sum(prices_arr * volumes_arr) / np.sum(volumes_arr)
    return float(vwap)


def calculate_volume_profile_poc(
    prices: List[float],
    volumes: List[int],
    num_bins: int = 20,
    period: int = 50
) -> float:
    """
    Calculate Point of Control (POC) from Volume Profile.

    POC = Price level with highest traded volume.
    """
    if len(prices) < period or len(volumes) < period:
        return prices[-1] if prices else 0

    prices_arr = np.array(prices[-period:])
    volumes_arr = np.array(volumes[-period:])

    # Create price bins
    price_min, price_max = prices_arr.min(), prices_arr.max()
    if price_max == price_min:
        return float(price_min)

    bins = np.linspace(price_min, price_max, num_bins + 1)
    bin_volumes = np.zeros(num_bins)

    # Assign volumes to bins
    for i, (price, volume) in enumerate(zip(prices_arr, volumes_arr)):
        bin_idx = min(int((price - price_min) / (price_max - price_min) * num_bins), num_bins - 1)
        bin_volumes[bin_idx] += volume

    # Find bin with highest volume
    poc_bin_idx = np.argmax(bin_volumes)
    poc_price = (bins[poc_bin_idx] + bins[poc_bin_idx + 1]) / 2

    return float(poc_price)


def calculate_correlation(series1: List[float], series2: List[float], period: int = 20) -> float:
    """Calculate Pearson correlation between two price series."""
    if len(series1) < period or len(series2) < period:
        return 0.0

    s1 = np.array(series1[-period:])
    s2 = np.array(series2[-period:])

    # Calculate returns
    returns1 = np.diff(s1) / s1[:-1]
    returns2 = np.diff(s2) / s2[:-1]

    if len(returns1) < 2:
        return 0.0

    # Handle zero variance
    if np.std(returns1) == 0 or np.std(returns2) == 0:
        return 0.0

    correlation = np.corrcoef(returns1, returns2)[0, 1]
    return float(correlation) if not np.isnan(correlation) else 0.0


def get_spy_trend(spy_prices: List[float]) -> str:
    """Determine SPY trend based on SMAs."""
    if len(spy_prices) < 50:
        return "unknown"

    sma20 = np.mean(spy_prices[-20:])
    sma50 = np.mean(spy_prices[-50:])
    current = spy_prices[-1]

    if current > sma20 > sma50:
        return "strong_uptrend"
    elif current > sma50:
        return "uptrend"
    elif current < sma20 < sma50:
        return "strong_downtrend"
    elif current < sma50:
        return "downtrend"
    else:
        return "sideways"


def analyze_symbol_features_worker(args: Tuple) -> Dict[str, Any]:
    """Worker function to analyze features for a single symbol."""
    symbol, bars, vix_data, spy_data, qqq_data, strategies = args

    results = {
        'symbol': symbol,
        'trades': [],
        'sector': SECTOR_MAP.get(symbol, 'Unknown')
    }

    if len(bars) < 200:
        return results

    # Prepare data
    prices = [b['close'] for b in bars]
    volumes = [b['volume'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    dates = [b['date'] for b in bars]

    # Get SPY/QQQ prices aligned with symbol dates
    spy_prices_aligned = []
    qqq_prices_aligned = []

    for date in dates:
        spy_prices_aligned.append(spy_data.get(date, {}).get('close', 0))
        qqq_prices_aligned.append(qqq_data.get(date, {}).get('close', 0))

    # Simulate trades for each strategy
    for strategy in strategies:
        for i in range(60, len(bars) - 45):  # Leave room for 45-day holding
            date = dates[i]

            # Get VIX for this date
            vix = vix_data.get(date, {}).get('close', 20)

            # Calculate features at entry point
            entry_price = prices[i]

            # RSI
            rsi = calculate_rsi_fast(prices[:i+1])

            # VWAP distance
            vwap = calculate_vwap(prices[:i+1], volumes[:i+1])
            vwap_distance = (entry_price - vwap) / vwap * 100 if vwap > 0 else 0

            # Volume Profile POC
            poc = calculate_volume_profile_poc(prices[:i+1], volumes[:i+1])
            poc_distance = (entry_price - poc) / poc * 100 if poc > 0 else 0

            # SPY/QQQ correlation
            spy_corr = calculate_correlation(prices[:i+1], spy_prices_aligned[:i+1])
            qqq_corr = calculate_correlation(prices[:i+1], qqq_prices_aligned[:i+1])

            # SPY trend
            spy_trend = get_spy_trend(spy_prices_aligned[:i+1])

            # Volume ratio
            avg_vol = np.mean(volumes[max(0, i-20):i]) if i > 0 else volumes[i]
            volume_ratio = volumes[i] / avg_vol if avg_vol > 0 else 1

            # Check if this is a valid entry based on strategy
            is_valid_entry = check_strategy_entry(
                strategy, rsi, entry_price, prices[:i+1], highs[:i+1], lows[:i+1]
            )

            if not is_valid_entry:
                continue

            # Simulate trade outcome (Bull-Put-Spread)
            holding_days = 30
            future_bars = bars[i+1:i+1+holding_days]

            if len(future_bars) < holding_days:
                continue

            # Simple win/loss based on price staying above support
            support_level = min(lows[max(0, i-20):i+1])
            stop_level = support_level * 0.95

            is_win = True
            exit_price = entry_price
            for fb in future_bars:
                if fb['low'] < stop_level:
                    is_win = False
                    exit_price = fb['low']
                    break

            if is_win:
                exit_price = future_bars[-1]['close']

            # Calculate P&L (simplified Bull-Put-Spread)
            if is_win:
                pnl = 75  # $75 credit kept
            else:
                pnl = -175  # $175 loss (5-wide spread - credit)

            trade = TradeWithFeatures(
                symbol=symbol,
                date=date,
                strategy=strategy,
                entry_price=entry_price,
                exit_price=exit_price,
                is_win=is_win,
                pnl=pnl,
                vix=vix,
                rsi=rsi,
                vwap_distance_pct=vwap_distance,
                volume_profile_poc_distance=poc_distance,
                spy_correlation_20d=spy_corr,
                qqq_correlation_20d=qqq_corr,
                spy_trend=spy_trend,
                sector=SECTOR_MAP.get(symbol, 'Unknown'),
                volume_ratio=volume_ratio
            )

            results['trades'].append(asdict(trade))

    return results


def calculate_rsi_fast(prices: List[float], period: int = 14) -> float:
    """Fast RSI calculation."""
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


def check_strategy_entry(
    strategy: str,
    rsi: float,
    current_price: float,
    prices: List[float],
    highs: List[float],
    lows: List[float]
) -> bool:
    """Check if current conditions match strategy entry criteria."""
    if len(prices) < 50:
        return False

    sma20 = np.mean(prices[-20:])
    sma50 = np.mean(prices[-50:])

    if strategy == 'pullback':
        # RSI pullback in uptrend
        return rsi < 40 and current_price > sma50 and current_price < sma20

    elif strategy == 'bounce':
        # Near recent lows
        recent_low = min(lows[-20:])
        return current_price < recent_low * 1.03 and current_price > sma50

    elif strategy == 'ath_breakout':
        # Near all-time high
        ath = max(highs)
        return current_price > ath * 0.97

    elif strategy == 'earnings_dip':
        # Any significant pullback (simplified - real would check earnings dates)
        recent_high = max(highs[-20:])
        return current_price < recent_high * 0.92

    return False


def calculate_feature_importance(trades: List[Dict]) -> Dict[str, FeatureMetrics]:
    """
    Calculate feature importance metrics.
    """
    if not trades:
        return {}

    features_to_analyze = [
        'rsi', 'vwap_distance_pct', 'volume_profile_poc_distance',
        'spy_correlation_20d', 'qqq_correlation_20d', 'volume_ratio', 'vix'
    ]

    importance = {}

    for feature in features_to_analyze:
        values_win = [t[feature] for t in trades if t['is_win'] and t[feature] is not None]
        values_loss = [t[feature] for t in trades if not t['is_win'] and t[feature] is not None]

        if not values_win or not values_loss:
            continue

        mean_win = np.mean(values_win)
        mean_loss = np.mean(values_loss)
        std_combined = np.std(values_win + values_loss)

        # Separation: how different are wins from losses
        separation = abs(mean_win - mean_loss) / std_combined if std_combined > 0 else 0

        # Correlation with win (1 for win, 0 for loss)
        all_values = [t[feature] for t in trades if t[feature] is not None]
        all_outcomes = [1 if t['is_win'] else 0 for t in trades if t[feature] is not None]

        if len(all_values) > 2:
            correlation = np.corrcoef(all_values, all_outcomes)[0, 1]
            correlation = correlation if not np.isnan(correlation) else 0
        else:
            correlation = 0

        importance[feature] = FeatureMetrics(
            feature_name=feature,
            correlation_with_win=correlation,
            mean_when_win=mean_win,
            mean_when_loss=mean_loss,
            separation=separation,
            information_gain=separation * abs(correlation)
        )

    return importance


def analyze_sector_performance(trades: List[Dict]) -> Dict[str, Dict]:
    """Analyze performance by sector."""
    sector_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0, 'trades': 0})

    for trade in trades:
        sector = trade['sector']
        sector_stats[sector]['trades'] += 1
        sector_stats[sector]['total_pnl'] += trade['pnl']

        if trade['is_win']:
            sector_stats[sector]['wins'] += 1
        else:
            sector_stats[sector]['losses'] += 1

    # Calculate win rates
    for sector, stats in sector_stats.items():
        if stats['trades'] > 0:
            stats['win_rate'] = stats['wins'] / stats['trades'] * 100
        else:
            stats['win_rate'] = 0

    return dict(sector_stats)


def analyze_spy_trend_filter(trades: List[Dict]) -> Dict[str, Dict]:
    """Analyze how SPY trend affects win rates."""
    trend_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0, 'trades': 0})

    for trade in trades:
        trend = trade['spy_trend']
        trend_stats[trend]['trades'] += 1
        trend_stats[trend]['total_pnl'] += trade['pnl']

        if trade['is_win']:
            trend_stats[trend]['wins'] += 1
        else:
            trend_stats[trend]['losses'] += 1

    # Calculate win rates
    for trend, stats in trend_stats.items():
        if stats['trades'] > 0:
            stats['win_rate'] = stats['wins'] / stats['trades'] * 100

    return dict(trend_stats)


def main():
    logger.info("=" * 70)
    logger.info("  FEATURE ENGINEERING TRAINING")
    logger.info("  Workers: %d / %d cores", NUM_WORKERS, cpu_count())
    logger.info("  Started: %s", datetime.now())
    logger.info("=" * 70)

    # Load data
    tracker = TradeTracker()
    symbol_data = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_data]

    logger.info("  Symbols: %d", len(symbols))

    # Load VIX data
    vix_bars = get_price_bars(tracker, '^VIX')
    vix_data = {b['date']: b for b in vix_bars} if vix_bars else {}
    logger.info("  VIX bars: %d", len(vix_data))

    # Load SPY data
    spy_bars = get_price_bars(tracker, 'SPY')
    spy_data = {b['date']: b for b in spy_bars} if spy_bars else {}
    logger.info("  SPY bars: %d", len(spy_data))

    # Load QQQ data
    qqq_bars = get_price_bars(tracker, 'QQQ')
    qqq_data = {b['date']: b for b in qqq_bars} if qqq_bars else {}
    logger.info("  QQQ bars: %d", len(qqq_data))

    strategies = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']

    # Prepare worker arguments
    worker_args = []
    for symbol in symbols:
        if symbol.startswith('^'):
            continue
        bars = get_price_bars(tracker, symbol)
        if bars and len(bars) >= 200:
            worker_args.append((symbol, bars, vix_data, spy_data, qqq_data, strategies))

    logger.info("  Analyzing %d symbols...", len(worker_args))
    logger.info("=" * 70)

    # Phase 1: Collect trades with features
    logger.info("")
    logger.info("  PHASE 1: FEATURE EXTRACTION")
    logger.info("=" * 70)

    all_trades = []
    symbol_count = 0

    with Pool(NUM_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(analyze_symbol_features_worker, worker_args)):
            trades = result.get('trades', [])
            all_trades.extend(trades)
            symbol_count += 1

            if (i + 1) % 50 == 0:
                logger.info("  Processed %d/%d symbols, %d trades collected",
                           i + 1, len(worker_args), len(all_trades))

    logger.info("  Total trades: %d", len(all_trades))

    # Phase 2: Feature Importance Analysis
    logger.info("")
    logger.info("  PHASE 2: FEATURE IMPORTANCE ANALYSIS")
    logger.info("=" * 70)

    feature_importance = calculate_feature_importance(all_trades)

    # Sort by information gain
    sorted_features = sorted(
        feature_importance.values(),
        key=lambda x: x.information_gain,
        reverse=True
    )

    logger.info("  Feature Importance (by Information Gain):")
    for fm in sorted_features:
        logger.info("    %s: IG=%.4f, Corr=%.3f, Sep=%.3f, Win=%.2f, Loss=%.2f",
                   fm.feature_name, fm.information_gain, fm.correlation_with_win,
                   fm.separation, fm.mean_when_win, fm.mean_when_loss)

    # Phase 3: Sector Analysis
    logger.info("")
    logger.info("  PHASE 3: SECTOR PERFORMANCE ANALYSIS")
    logger.info("=" * 70)

    sector_perf = analyze_sector_performance(all_trades)

    # Sort by win rate
    sorted_sectors = sorted(
        sector_perf.items(),
        key=lambda x: x[1]['win_rate'],
        reverse=True
    )

    for sector, stats in sorted_sectors:
        if stats['trades'] >= 100:
            logger.info("  %s: WR=%.1f%%, Trades=%d, P&L=$%.0f",
                       sector, stats['win_rate'], stats['trades'], stats['total_pnl'])

    # Phase 4: SPY Trend Filter Analysis
    logger.info("")
    logger.info("  PHASE 4: SPY TREND FILTER ANALYSIS")
    logger.info("=" * 70)

    spy_trend_perf = analyze_spy_trend_filter(all_trades)

    for trend, stats in sorted(spy_trend_perf.items(), key=lambda x: x[1]['win_rate'], reverse=True):
        if stats['trades'] >= 100:
            logger.info("  SPY %s: WR=%.1f%%, Trades=%d, P&L=$%.0f",
                       trend, stats['win_rate'], stats['trades'], stats['total_pnl'])

    # Phase 5: VWAP and Volume Profile Analysis
    logger.info("")
    logger.info("  PHASE 5: VWAP/VOLUME PROFILE ANALYSIS")
    logger.info("=" * 70)

    # Analyze VWAP distance bins
    vwap_bins = [
        (-100, -3, "Below VWAP >3%"),
        (-3, -1, "Below VWAP 1-3%"),
        (-1, 1, "Near VWAP"),
        (1, 3, "Above VWAP 1-3%"),
        (3, 100, "Above VWAP >3%")
    ]

    logger.info("  VWAP Distance Analysis:")
    for low, high, label in vwap_bins:
        bin_trades = [t for t in all_trades if low <= t['vwap_distance_pct'] < high]
        if len(bin_trades) >= 50:
            wins = sum(1 for t in bin_trades if t['is_win'])
            wr = wins / len(bin_trades) * 100
            pnl = sum(t['pnl'] for t in bin_trades)
            logger.info("    %s: WR=%.1f%%, Trades=%d, P&L=$%.0f",
                       label, wr, len(bin_trades), pnl)

    # Volume Profile POC distance
    poc_bins = [
        (-100, -3, "Below POC >3%"),
        (-3, -1, "Below POC 1-3%"),
        (-1, 1, "Near POC"),
        (1, 3, "Above POC 1-3%"),
        (3, 100, "Above POC >3%")
    ]

    logger.info("")
    logger.info("  Volume Profile POC Distance Analysis:")
    for low, high, label in poc_bins:
        bin_trades = [t for t in all_trades if low <= t['volume_profile_poc_distance'] < high]
        if len(bin_trades) >= 50:
            wins = sum(1 for t in bin_trades if t['is_win'])
            wr = wins / len(bin_trades) * 100
            pnl = sum(t['pnl'] for t in bin_trades)
            logger.info("    %s: WR=%.1f%%, Trades=%d, P&L=$%.0f",
                       label, wr, len(bin_trades), pnl)

    # Phase 6: Strategy-specific analysis
    logger.info("")
    logger.info("  PHASE 6: STRATEGY-SPECIFIC FEATURE ANALYSIS")
    logger.info("=" * 70)

    strategy_feature_importance = {}
    for strategy in strategies:
        strategy_trades = [t for t in all_trades if t['strategy'] == strategy]
        if len(strategy_trades) >= 100:
            fi = calculate_feature_importance(strategy_trades)
            strategy_feature_importance[strategy] = fi

            wins = sum(1 for t in strategy_trades if t['is_win'])
            wr = wins / len(strategy_trades) * 100

            logger.info("")
            logger.info("  %s (WR=%.1f%%, N=%d):", strategy.upper(), wr, len(strategy_trades))

            sorted_fi = sorted(fi.values(), key=lambda x: x.information_gain, reverse=True)
            for fm in sorted_fi[:5]:
                logger.info("    %s: IG=%.4f, Corr=%.3f",
                           fm.feature_name, fm.information_gain, fm.correlation_with_win)

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    results = {
        'version': '1.0.0',
        'created_at': datetime.now().isoformat(),
        'total_trades': len(all_trades),
        'total_symbols': symbol_count,
        'feature_importance': {
            k: asdict(v) for k, v in feature_importance.items()
        },
        'sector_performance': sector_perf,
        'spy_trend_filter': spy_trend_perf,
        'strategy_feature_importance': {
            strategy: {k: asdict(v) for k, v in fi.items()}
            for strategy, fi in strategy_feature_importance.items()
        },
        'recommendations': {
            'vwap': {
                'use_as_filter': True,
                'optimal_zone': 'Near or below VWAP',
                'description': 'Entries near/below VWAP tend to perform better'
            },
            'spy_trend': {
                'use_as_filter': True,
                'optimal_trends': ['strong_uptrend', 'uptrend'],
                'description': 'Avoid entries during SPY downtrends'
            },
            'sector_adjustments': {
                sector: stats['win_rate'] - 80  # Adjustment vs baseline
                for sector, stats in sector_perf.items()
                if stats['trades'] >= 100
            }
        }
    }

    # Save detailed results
    results_file = MODELS_DIR / f"feature_engineering_results_{timestamp}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    # Save compact config
    config = {
        'version': '1.0.0',
        'created_at': datetime.now().isoformat(),
        'feature_weights': {
            fm.feature_name: round(max(0, fm.information_gain * 10), 2)
            for fm in sorted_features
        },
        'sector_adjustments': {
            sector: round(stats['win_rate'] - 80, 2)
            for sector, stats in sector_perf.items()
            if stats['trades'] >= 100
        },
        'spy_trend_filter': {
            'strong_uptrend': 1.0,
            'uptrend': 0.5,
            'sideways': 0.0,
            'downtrend': -0.5,
            'strong_downtrend': -1.0
        },
        'vwap_filter': {
            'below_3pct': 0.5,
            'near_vwap': 0.25,
            'above_3pct': -0.25
        }
    }

    config_file = MODELS_DIR / "FEATURE_CONFIG.json"
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    logger.info("")
    logger.info("=" * 70)
    logger.info("  TRAINING COMPLETE")
    logger.info("=" * 70)
    logger.info("  Results saved to: %s", results_file)
    logger.info("  Config saved to: %s", config_file)
    logger.info("=" * 70)

    return results


if __name__ == '__main__':
    main()
