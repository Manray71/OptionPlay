#!/usr/bin/env python3
"""
Symbol Clustering Training
==========================
Groups symbols by characteristics for better strategy selection.

Clustering Features:
- Volatility (ATR, historical vol)
- Price momentum (trend strength)
- Mean reversion tendency
- Sector
- Market cap tier
- Earnings sensitivity

Output:
- Symbol clusters with optimal strategy per cluster
- Cluster characteristics profile
- Strategy recommendation by cluster
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
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
# SECTOR MAPPING
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

    # Financials
    'JPM': 'Financials', 'BAC': 'Financials', 'WFC': 'Financials', 'C': 'Financials',
    'GS': 'Financials', 'MS': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials',
    'AXP': 'Financials', 'V': 'Financials', 'MA': 'Financials', 'PYPL': 'Financials',
    'COF': 'Financials', 'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials',
    'AIG': 'Financials', 'MET': 'Financials', 'PRU': 'Financials', 'AFL': 'Financials',
    'CB': 'Financials', 'MMC': 'Financials', 'AON': 'Financials', 'ICE': 'Financials',

    # Healthcare
    'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'PFE': 'Healthcare', 'MRK': 'Healthcare',
    'ABBV': 'Healthcare', 'LLY': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'BMY': 'Healthcare', 'AMGN': 'Healthcare', 'GILD': 'Healthcare',
    'MDT': 'Healthcare', 'ISRG': 'Healthcare', 'SYK': 'Healthcare', 'BSX': 'Healthcare',
    'VRTX': 'Healthcare', 'REGN': 'Healthcare', 'ZTS': 'Healthcare', 'BDX': 'Healthcare',
    'CVS': 'Healthcare', 'CI': 'Healthcare', 'ELV': 'Healthcare', 'HUM': 'Healthcare',

    # Consumer Discretionary
    'AMZN': 'Consumer Discretionary', 'TSLA': 'Consumer Discretionary', 'HD': 'Consumer Discretionary',
    'NKE': 'Consumer Discretionary', 'MCD': 'Consumer Discretionary', 'SBUX': 'Consumer Discretionary',
    'LOW': 'Consumer Discretionary', 'TJX': 'Consumer Discretionary', 'BKNG': 'Consumer Discretionary',
    'MAR': 'Consumer Discretionary', 'CMG': 'Consumer Discretionary', 'ORLY': 'Consumer Discretionary',
    'AZO': 'Consumer Discretionary', 'ROST': 'Consumer Discretionary', 'DHI': 'Consumer Discretionary',
    'LEN': 'Consumer Discretionary', 'GM': 'Consumer Discretionary', 'F': 'Consumer Discretionary',
    'ANF': 'Consumer Discretionary', 'LULU': 'Consumer Discretionary', 'DPZ': 'Consumer Discretionary',

    # Consumer Staples
    'PG': 'Consumer Staples', 'KO': 'Consumer Staples', 'PEP': 'Consumer Staples',
    'COST': 'Consumer Staples', 'WMT': 'Consumer Staples', 'PM': 'Consumer Staples',
    'MO': 'Consumer Staples', 'CL': 'Consumer Staples', 'MDLZ': 'Consumer Staples',
    'KMB': 'Consumer Staples', 'GIS': 'Consumer Staples', 'K': 'Consumer Staples',
    'HSY': 'Consumer Staples', 'SYY': 'Consumer Staples', 'ADM': 'Consumer Staples',
    'STZ': 'Consumer Staples', 'CAG': 'Consumer Staples', 'KHC': 'Consumer Staples',

    # Industrials
    'CAT': 'Industrials', 'DE': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
    'UNP': 'Industrials', 'UPS': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials',
    'GE': 'Industrials', 'MMM': 'Industrials', 'EMR': 'Industrials', 'ETN': 'Industrials',
    'ITW': 'Industrials', 'WM': 'Industrials', 'RSG': 'Industrials', 'CSX': 'Industrials',
    'NSC': 'Industrials', 'FDX': 'Industrials', 'GD': 'Industrials', 'NOC': 'Industrials',
    'CARR': 'Industrials', 'IR': 'Industrials', 'ROK': 'Industrials', 'CMI': 'Industrials',

    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'EOG': 'Energy',
    'SLB': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'OXY': 'Energy', 'HAL': 'Energy', 'DVN': 'Energy', 'FANG': 'Energy',
    'HES': 'Energy', 'BKR': 'Energy', 'APA': 'Energy', 'AR': 'Energy',

    # Utilities
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities',
    'AEP': 'Utilities', 'EXC': 'Utilities', 'SRE': 'Utilities', 'XEL': 'Utilities',
    'ED': 'Utilities', 'WEC': 'Utilities', 'ES': 'Utilities', 'AEE': 'Utilities',
    'DTE': 'Utilities', 'FE': 'Utilities', 'PPL': 'Utilities', 'AWK': 'Utilities',
    'ATO': 'Utilities', 'NI': 'Utilities', 'CMS': 'Utilities', 'EVRG': 'Utilities',

    # Real Estate
    'AMT': 'Real Estate', 'PLD': 'Real Estate', 'CCI': 'Real Estate', 'EQIX': 'Real Estate',
    'PSA': 'Real Estate', 'O': 'Real Estate', 'WELL': 'Real Estate', 'SPG': 'Real Estate',
    'DLR': 'Real Estate', 'AVB': 'Real Estate', 'EQR': 'Real Estate', 'VICI': 'Real Estate',
    'ARE': 'Real Estate', 'VTR': 'Real Estate', 'MAA': 'Real Estate', 'UDR': 'Real Estate',

    # Materials
    'LIN': 'Materials', 'APD': 'Materials', 'SHW': 'Materials', 'ECL': 'Materials',
    'NEM': 'Materials', 'FCX': 'Materials', 'DOW': 'Materials', 'DD': 'Materials',
    'PPG': 'Materials', 'NUE': 'Materials', 'VMC': 'Materials', 'MLM': 'Materials',
    'ALB': 'Materials', 'BALL': 'Materials', 'AVY': 'Materials', 'PKG': 'Materials',
    'BHP': 'Materials', 'RIO': 'Materials', 'AA': 'Materials', 'CLF': 'Materials',

    # Communication Services
    'NFLX': 'Communication Services', 'DIS': 'Communication Services', 'CMCSA': 'Communication Services',
    'VZ': 'Communication Services', 'T': 'Communication Services', 'TMUS': 'Communication Services',
    'CHTR': 'Communication Services', 'EA': 'Communication Services', 'TTWO': 'Communication Services',
    'WBD': 'Communication Services', 'PARA': 'Communication Services', 'FOX': 'Communication Services',

    # International / ADRs
    'BABA': 'International', 'TSM': 'International', 'BIDU': 'International', 'JD': 'International',
    'PDD': 'International', 'NIO': 'International', 'SONY': 'International', 'TM': 'International',
}


@dataclass
class SymbolCharacteristics:
    """Characteristics of a symbol for clustering"""
    symbol: str
    sector: str

    # Volatility metrics
    avg_atr_pct: float  # ATR as % of price
    historical_vol: float  # Annualized volatility
    vol_regime: str  # low, medium, high

    # Trend metrics
    trend_strength: float  # -1 to +1
    mean_reversion_score: float  # 0 to 1 (higher = more mean reverting)

    # Price characteristics
    avg_price: float
    price_tier: str  # low (<50), medium (50-200), high (>200)

    # Strategy performance (from historical data)
    best_strategy: Optional[str] = None
    strategy_win_rates: Optional[Dict[str, float]] = None


@dataclass
class SymbolCluster:
    """A cluster of similar symbols"""
    cluster_id: int
    name: str
    description: str

    # Cluster characteristics
    avg_volatility: float
    vol_regime: str
    dominant_sector: str
    price_tier: str
    trend_bias: str  # trending, mean_reverting, neutral

    # Strategy recommendation
    best_strategy: str
    strategy_confidence: float
    strategy_win_rate: float

    # Symbols in cluster
    symbols: List[str]
    symbol_count: int


def calculate_symbol_characteristics(
    symbol: str,
    prices: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
) -> Optional[SymbolCharacteristics]:
    """Calculate characteristics for a single symbol"""

    n = len(prices)
    if n < 252:  # Need at least 1 year of data
        return None

    # Volatility: ATR as % of price
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - prices[:-1]),
            np.abs(lows[1:] - prices[:-1])
        )
    )
    atr_14 = np.mean(tr[-14:])
    avg_price = np.mean(prices[-20:])
    atr_pct = (atr_14 / avg_price) * 100 if avg_price > 0 else 0

    # Historical volatility (annualized)
    returns = np.diff(np.log(prices[-252:]))
    historical_vol = np.std(returns) * np.sqrt(252) * 100

    # Vol regime
    if historical_vol < 20:
        vol_regime = "low"
    elif historical_vol < 35:
        vol_regime = "medium"
    else:
        vol_regime = "high"

    # Trend strength: correlation of price with time
    x = np.arange(min(60, n))
    y = prices[-len(x):]
    if len(x) > 1 and np.std(y) > 0:
        trend_strength = np.corrcoef(x, y)[0, 1]
    else:
        trend_strength = 0

    # Mean reversion score: how often does price return to SMA20 after deviation
    sma20 = np.convolve(prices, np.ones(20)/20, mode='valid')
    if len(sma20) >= 100:
        deviations = prices[-len(sma20):] - sma20

        # Count mean reversions (sign changes after deviation)
        sign_changes = np.diff(np.sign(deviations))
        reversion_count = np.sum(sign_changes != 0)
        mean_reversion_score = min(1.0, reversion_count / (len(deviations) / 10))
    else:
        mean_reversion_score = 0.5

    # Price tier
    if avg_price < 50:
        price_tier = "low"
    elif avg_price < 200:
        price_tier = "medium"
    else:
        price_tier = "high"

    # Sector
    sector = SECTOR_MAP.get(symbol, "Unknown")

    return SymbolCharacteristics(
        symbol=symbol,
        sector=sector,
        avg_atr_pct=atr_pct,
        historical_vol=historical_vol,
        vol_regime=vol_regime,
        trend_strength=trend_strength,
        mean_reversion_score=mean_reversion_score,
        avg_price=avg_price,
        price_tier=price_tier,
    )


def simulate_strategies_for_symbol(
    symbol: str,
    prices: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
) -> Dict[str, Dict]:
    """Simulate all 4 strategies for a symbol and return win rates"""

    n = len(prices)
    if n < 252:
        return {}

    results = {
        'pullback': {'trades': 0, 'wins': 0},
        'bounce': {'trades': 0, 'wins': 0},
        'ath_breakout': {'trades': 0, 'wins': 0},
        'earnings_dip': {'trades': 0, 'wins': 0},
    }

    for i in range(200, n - 30, 5):
        current_price = prices[i]

        # Calculate indicators
        rsi = calculate_rsi(prices[:i+1])
        sma20 = np.mean(prices[i-19:i+1])
        sma50 = np.mean(prices[i-49:i+1])
        sma200 = np.mean(prices[i-199:i+1])
        high_52w = np.max(prices[max(0,i-251):i+1])
        low_20d = np.min(lows[i-19:i+1])

        # Check outcome (price stays above 95% for 30 days)
        short_strike = current_price * 0.95
        exit_idx = min(i + 30, n - 1)
        win = all(prices[j] > short_strike for j in range(i, exit_idx + 1))

        # Pullback Strategy: RSI < 40, above SMA200, below SMA20
        if rsi < 40 and current_price > sma200 and current_price < sma20:
            results['pullback']['trades'] += 1
            if win:
                results['pullback']['wins'] += 1

        # Bounce Strategy: Near support (within 3% of 20-day low)
        if current_price < low_20d * 1.03 and current_price > sma200:
            results['bounce']['trades'] += 1
            if win:
                results['bounce']['wins'] += 1

        # ATH Breakout: Within 5% of 52-week high, above all MAs
        if current_price > high_52w * 0.95 and current_price > sma20 > sma50:
            results['ath_breakout']['trades'] += 1
            if win:
                results['ath_breakout']['wins'] += 1

        # Earnings Dip: 5-15% below recent high (simplified)
        recent_high = np.max(prices[max(0,i-20):i+1])
        drop_pct = (recent_high - current_price) / recent_high * 100
        if 5 <= drop_pct <= 15 and current_price > sma200:
            results['earnings_dip']['trades'] += 1
            if win:
                results['earnings_dip']['wins'] += 1

    # Calculate win rates
    for strat in results:
        if results[strat]['trades'] > 0:
            results[strat]['win_rate'] = results[strat]['wins'] / results[strat]['trades'] * 100
        else:
            results[strat]['win_rate'] = 0

    return results


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


def cluster_symbols(
    characteristics: List[SymbolCharacteristics],
) -> List[SymbolCluster]:
    """
    Cluster symbols based on characteristics.

    Uses rule-based clustering for interpretability:
    - Volatility regime (low, medium, high)
    - Price tier (low, medium, high)
    - Trend bias (trending vs mean-reverting)
    """

    clusters = {}

    for char in characteristics:
        # Determine trend bias
        if char.mean_reversion_score > 0.6:
            trend_bias = "mean_reverting"
        elif abs(char.trend_strength) > 0.3:
            trend_bias = "trending"
        else:
            trend_bias = "neutral"

        # Create cluster key
        cluster_key = f"{char.vol_regime}_{char.price_tier}_{trend_bias}"

        if cluster_key not in clusters:
            clusters[cluster_key] = {
                'symbols': [],
                'characteristics': [],
                'vol_regime': char.vol_regime,
                'price_tier': char.price_tier,
                'trend_bias': trend_bias,
            }

        clusters[cluster_key]['symbols'].append(char.symbol)
        clusters[cluster_key]['characteristics'].append(char)

    # Convert to SymbolCluster objects
    result = []
    for i, (key, data) in enumerate(clusters.items()):
        # Calculate cluster averages
        chars = data['characteristics']
        avg_vol = np.mean([c.historical_vol for c in chars])

        # Count dominant sector
        sector_counts = defaultdict(int)
        for c in chars:
            sector_counts[c.sector] += 1
        dominant_sector = max(sector_counts, key=sector_counts.get) if sector_counts else "Mixed"

        # Determine best strategy based on cluster characteristics
        vol_regime = data['vol_regime']
        trend_bias = data['trend_bias']

        if trend_bias == "mean_reverting":
            if vol_regime == "high":
                best_strategy = "bounce"
            else:
                best_strategy = "pullback"
        elif trend_bias == "trending":
            best_strategy = "ath_breakout"
        else:
            best_strategy = "pullback"  # Default

        # Create cluster name
        name_parts = []
        if vol_regime == "low":
            name_parts.append("Steady")
        elif vol_regime == "high":
            name_parts.append("Volatile")
        else:
            name_parts.append("Moderate")

        if trend_bias == "mean_reverting":
            name_parts.append("Mean-Reverting")
        elif trend_bias == "trending":
            name_parts.append("Trending")

        name_parts.append(data['price_tier'].capitalize())

        cluster = SymbolCluster(
            cluster_id=i,
            name=" ".join(name_parts),
            description=f"{vol_regime} volatility, {data['price_tier']} price, {trend_bias}",
            avg_volatility=avg_vol,
            vol_regime=vol_regime,
            dominant_sector=dominant_sector,
            price_tier=data['price_tier'],
            trend_bias=trend_bias,
            best_strategy=best_strategy,
            strategy_confidence=0.0,  # Will be filled in later
            strategy_win_rate=0.0,   # Will be filled in later
            symbols=data['symbols'],
            symbol_count=len(data['symbols']),
        )
        result.append(cluster)

    return result


def validate_clusters_with_backtests(
    clusters: List[SymbolCluster],
    symbol_results: Dict[str, Dict],
) -> List[SymbolCluster]:
    """Validate cluster strategy recommendations against actual backtest results"""

    for cluster in clusters:
        # Aggregate results for symbols in this cluster
        strategy_totals = defaultdict(lambda: {'trades': 0, 'wins': 0})

        for symbol in cluster.symbols:
            if symbol not in symbol_results:
                continue

            for strat, data in symbol_results[symbol].items():
                strategy_totals[strat]['trades'] += data.get('trades', 0)
                strategy_totals[strat]['wins'] += data.get('wins', 0)

        # Find actual best strategy for this cluster
        best_strat = None
        best_wr = 0
        best_trades = 0

        for strat, totals in strategy_totals.items():
            if totals['trades'] >= 20:  # Minimum sample size
                wr = totals['wins'] / totals['trades'] * 100
                if wr > best_wr:
                    best_wr = wr
                    best_strat = strat
                    best_trades = totals['trades']

        if best_strat:
            cluster.best_strategy = best_strat
            cluster.strategy_win_rate = best_wr
            cluster.strategy_confidence = min(1.0, best_trades / 100)

    return clusters


def main():
    logger.info("=" * 70)
    logger.info("  SYMBOL CLUSTERING TRAINING")
    logger.info("  Started: %s", datetime.now())
    logger.info("=" * 70)

    # Load data
    tracker = TradeTracker()

    symbol_list = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_list if not s['symbol'].startswith('^')]
    logger.info("  Symbols available: %d", len(symbols))

    # Phase 1: Calculate characteristics for each symbol
    logger.info("\nPhase 1: Calculating symbol characteristics...")
    characteristics = []
    symbol_data = {}

    for i, symbol in enumerate(symbols):
        price_data = tracker.get_price_data(symbol)
        if not price_data or not price_data.bars or len(price_data.bars) < 252:
            continue

        prices = np.array([b.close for b in price_data.bars])
        highs = np.array([b.high for b in price_data.bars])
        lows = np.array([b.low for b in price_data.bars])
        volumes = np.array([b.volume for b in price_data.bars])

        char = calculate_symbol_characteristics(symbol, prices, highs, lows, volumes)
        if char:
            characteristics.append(char)
            symbol_data[symbol] = {
                'prices': prices,
                'highs': highs,
                'lows': lows,
            }

        if (i + 1) % 50 == 0:
            logger.info(f"  Processed {i+1}/{len(symbols)} symbols...")

    logger.info(f"  Symbols with valid characteristics: {len(characteristics)}")

    # Phase 2: Cluster symbols
    logger.info("\nPhase 2: Clustering symbols...")
    clusters = cluster_symbols(characteristics)
    logger.info(f"  Created {len(clusters)} clusters")

    # Phase 3: Backtest each symbol for validation
    logger.info("\nPhase 3: Backtesting strategies for validation...")
    symbol_results = {}

    for i, (symbol, data) in enumerate(symbol_data.items()):
        results = simulate_strategies_for_symbol(
            symbol, data['prices'], data['highs'], data['lows']
        )
        if results:
            symbol_results[symbol] = results

        if (i + 1) % 50 == 0:
            logger.info(f"  Backtested {i+1}/{len(symbol_data)} symbols...")

    logger.info(f"  Backtested: {len(symbol_results)} symbols")

    # Phase 4: Validate clusters against backtest results
    logger.info("\nPhase 4: Validating cluster recommendations...")
    clusters = validate_clusters_with_backtests(clusters, symbol_results)

    # Sort clusters by symbol count
    clusters.sort(key=lambda c: c.symbol_count, reverse=True)

    # Print results
    print("\n" + "=" * 80)
    print("SYMBOL CLUSTERS")
    print("=" * 80)
    print(f"{'ID':<4} {'Name':<30} {'Symbols':<8} {'Best Strategy':<15} {'WinRate':<10} {'Sector':<15}")
    print("-" * 80)

    for cluster in clusters:
        print(f"{cluster.cluster_id:<4} {cluster.name:<30} {cluster.symbol_count:<8} "
              f"{cluster.best_strategy:<15} {cluster.strategy_win_rate:<10.1f} {cluster.dominant_sector:<15}")

    # Print detailed cluster info
    print("\n" + "=" * 80)
    print("CLUSTER DETAILS")
    print("=" * 80)

    for cluster in clusters[:10]:  # Top 10 clusters
        print(f"\n{cluster.name} (ID: {cluster.cluster_id})")
        print(f"  Description: {cluster.description}")
        print(f"  Symbols: {cluster.symbol_count}")
        print(f"  Best Strategy: {cluster.best_strategy} ({cluster.strategy_win_rate:.1f}% WR)")
        print(f"  Dominant Sector: {cluster.dominant_sector}")
        print(f"  Avg Volatility: {cluster.avg_volatility:.1f}%")
        print(f"  Symbols: {', '.join(cluster.symbols[:15])}{'...' if len(cluster.symbols) > 15 else ''}")

    # Build symbol-to-cluster mapping
    symbol_to_cluster = {}
    for cluster in clusters:
        for symbol in cluster.symbols:
            symbol_to_cluster[symbol] = {
                'cluster_id': cluster.cluster_id,
                'cluster_name': cluster.name,
                'best_strategy': cluster.best_strategy,
                'strategy_win_rate': cluster.strategy_win_rate,
                'vol_regime': cluster.vol_regime,
                'price_tier': cluster.price_tier,
                'trend_bias': cluster.trend_bias,
            }

    # Save results
    output_path = Path.home() / '.optionplay' / 'models' / 'SYMBOL_CLUSTERS.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'training_type': 'symbol_clustering',
            'total_symbols': len(characteristics),
            'total_clusters': len(clusters),
            'clusters': [
                {
                    'cluster_id': c.cluster_id,
                    'name': c.name,
                    'description': c.description,
                    'avg_volatility': c.avg_volatility,
                    'vol_regime': c.vol_regime,
                    'dominant_sector': c.dominant_sector,
                    'price_tier': c.price_tier,
                    'trend_bias': c.trend_bias,
                    'best_strategy': c.best_strategy,
                    'strategy_win_rate': c.strategy_win_rate,
                    'strategy_confidence': c.strategy_confidence,
                    'symbols': c.symbols,
                    'symbol_count': c.symbol_count,
                }
                for c in clusters
            ],
            'symbol_to_cluster': symbol_to_cluster,
        }, f, indent=2)

    logger.info(f"\nResults saved to {output_path}")

    logger.info("\n" + "=" * 70)
    logger.info("  SYMBOL CLUSTERING COMPLETE")
    logger.info("  Finished: %s", datetime.now())
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
