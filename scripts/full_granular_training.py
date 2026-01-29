#!/usr/bin/env python3
"""
OptionPlay - Full Granular Distributed Training
===============================================

Maximale Training-Granularität:
- 4 VIX-Regimes × 4 Strategien × 11 Sektoren × 628 Symbole
- Individuelle Gewichte pro Symbol
- Sektor-spezifische Configs
- Komponenten-Gewichte pro Regime × Strategie

Training-Matrix:
┌─────────────────────────────────────────────────────────────────┐
│                    VIX REGIME                                    │
│         low      normal    elevated    high                      │
├─────────────────────────────────────────────────────────────────┤
│ S   pullback  [weights] [weights]  [weights] [weights]          │
│ T   bounce    [weights] [weights]  [weights] [weights]          │
│ R   breakout  [weights] [weights]  [weights] [weights]          │
│ A   dip       [weights] [weights]  [weights] [weights]          │
├─────────────────────────────────────────────────────────────────┤
│ SECTOR    Technology  |  Finance  |  Healthcare  | ...          │
│           [adj]       |  [adj]    |  [adj]       | ...          │
├─────────────────────────────────────────────────────────────────┤
│ SYMBOL    AAPL: best=pullback, score_adj=+0.5, sector_mult=1.2  │
│           MSFT: best=bounce, score_adj=-0.3, sector_mult=1.0    │
│           ...                                                    │
└─────────────────────────────────────────────────────────────────┘

Output: GRANULAR_TRAINED_MODEL.json mit allen Ebenen
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
from dataclasses import dataclass, field, asdict
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
LOG_FILE = LOG_DIR / 'granular_training.log'
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
VIX_REGIMES = {
    'low': (0, 15),
    'normal': (15, 20),
    'elevated': (20, 30),
    'high': (30, 100)
}
SECTORS = [
    'technology', 'finance', 'healthcare', 'consumer_cyclical',
    'consumer_defensive', 'industrials', 'energy', 'utilities',
    'real_estate', 'materials', 'communication'
]
MIN_SCORES = [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]

# Component sets per strategy
STRATEGY_COMPONENTS = {
    'pullback': [
        'rsi_score', 'support_score', 'fibonacci_score', 'ma_score',
        'trend_score', 'volume_score', 'macd_score', 'stochastic_score',
        'keltner_score', 'vwap_score', 'market_context_score', 'sector_score'
    ],
    'bounce': [
        'rsi_score', 'support_score', 'candlestick_score', 'ma_score',
        'trend_score', 'volume_score', 'macd_score', 'stochastic_score',
        'keltner_score', 'vwap_score', 'market_context_score', 'sector_score'
    ],
    'ath_breakout': [
        'ath_breakout_score', 'momentum_score', 'relative_strength_score',
        'volume_score', 'trend_score', 'ma_score', 'vwap_score',
        'market_context_score', 'sector_score'
    ],
    'earnings_dip': [
        'dip_score', 'gap_score', 'stabilization_score', 'volume_score',
        'support_score', 'rsi_score', 'vwap_score', 'market_context_score',
        'sector_score'
    ]
}

# Worker configuration
WORKER_HOST = 'larss-macbook-pro-2.local'
MASTER_WORKERS = 10
WORKER_WORKERS = 12


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ComponentWeights:
    """Gewichte für Score-Komponenten"""
    weights: Dict[str, float] = field(default_factory=dict)

    def get_weight(self, component: str) -> float:
        return self.weights.get(component, 1.0)

    def apply_to_score(self, score_breakdown: Dict[str, float]) -> float:
        """Wendet Gewichte auf Score-Breakdown an"""
        total = 0.0
        for component, value in score_breakdown.items():
            weight = self.get_weight(component)
            total += value * weight
        return total


@dataclass
class RegimeStrategyConfig:
    """Config für eine Regime × Strategie Kombination"""
    regime: str
    strategy: str
    enabled: bool = True
    min_score: float = 5.0
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 150.0
    component_weights: ComponentWeights = field(default_factory=ComponentWeights)

    # Training metrics
    train_trades: int = 0
    train_wins: int = 0
    test_trades: int = 0
    test_wins: int = 0
    total_pnl: float = 0.0

    @property
    def train_wr(self) -> float:
        return self.train_wins / self.train_trades * 100 if self.train_trades > 0 else 0

    @property
    def test_wr(self) -> float:
        return self.test_wins / self.test_trades * 100 if self.test_trades > 0 else 0

    @property
    def degradation(self) -> float:
        return self.train_wr - self.test_wr


@dataclass
class SectorConfig:
    """Sektor-spezifische Konfiguration"""
    sector: str
    score_adjustment: float = 0.0  # Wird zum Score addiert
    strategy_preferences: Dict[str, float] = field(default_factory=dict)  # strategy -> weight
    enabled_strategies: List[str] = field(default_factory=list)

    # Training metrics
    total_trades: int = 0
    total_wins: int = 0
    best_strategy: str = ""
    best_strategy_wr: float = 0.0


@dataclass
class SymbolConfig:
    """Symbol-spezifische Konfiguration"""
    symbol: str
    sector: str = ""
    best_strategy: str = ""
    score_adjustment: float = 0.0  # Symbol-spezifischer Score-Modifier

    # Per-strategy metrics
    strategy_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Per-regime metrics
    regime_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Optimal settings
    optimal_min_score: float = 5.0
    optimal_regime_strategy: Dict[str, str] = field(default_factory=dict)  # regime -> best_strategy

    # Training data
    total_trades: int = 0
    total_wins: int = 0
    total_pnl: float = 0.0


@dataclass
class GranularModel:
    """Vollständiges granulares Modell"""
    version: str = "9.0.0"
    created_at: str = ""
    training_duration_minutes: float = 0.0

    # Level 1: Regime × Strategie (4×4 = 16)
    regime_strategy_configs: Dict[str, Dict[str, RegimeStrategyConfig]] = field(default_factory=dict)

    # Level 2: Sektor (11)
    sector_configs: Dict[str, SectorConfig] = field(default_factory=dict)

    # Level 3: Symbol (628+)
    symbol_configs: Dict[str, SymbolConfig] = field(default_factory=dict)

    # Summary statistics
    summary: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_regime(vix: float) -> str:
    for regime, (low, high) in VIX_REGIMES.items():
        if low <= vix < high:
            return regime
    return 'high'


def get_sector(symbol: str, sector_map: Dict[str, str]) -> str:
    """Holt Sektor für Symbol aus Mapping"""
    return sector_map.get(symbol, 'unknown')


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


def simulate_trade(entry_price: float, future_bars: List[Dict], holding_days: int = 30) -> Tuple[int, float]:
    """
    Simuliert Bull-Put-Spread Trade mit realistischen Parametern.

    Fixes angewendet:
    1. Realistisches Pricing: 33% Net Credit (statt 20%)
    2. Stop-Loss bei 2x Credit (statt vollem Verlust)
    3. Profit Target bei 75% (statt 50%)
    """
    if len(future_bars) < 15:
        return 0, 0.0

    # Strike-Auswahl: Short bei 92% des Entry, 5% Spread-Breite
    short_strike = entry_price * 0.92
    long_strike = short_strike - (entry_price * 0.05)
    spread_width = short_strike - long_strike

    # FIX 1: Realistisches Pricing - 33% Net Credit (typisch für Bull-Put-Spreads)
    net_credit = spread_width * 0.33

    max_profit = net_credit * 100
    max_loss = (spread_width - net_credit) * 100

    # FIX 2: Stop-Loss bei 2x Credit (statt vollem Verlust)
    # Dies entspricht ~100% Verlust auf den Credit, nicht auf den Spread
    stop_loss_amount = net_credit * 2.0 * 100  # 2x Credit = ca. 66% des max_loss

    for day, bar in enumerate(future_bars[:holding_days]):
        # Stop-Loss Check: Wenn Preis unter Short Strike fällt
        # und Verlust > Stop-Loss Level erreicht
        if bar['low'] < short_strike:
            # Berechne aktuellen Verlust basierend auf Preisbewegung
            price_below_short = short_strike - bar['low']
            current_loss = min(price_below_short * 100, max_loss)

            if current_loss >= stop_loss_amount:
                return 0, -stop_loss_amount  # Stop-Loss ausgelöst

        # FIX 3: Profit Target bei 75% (statt 50%)
        if day >= 14 and bar['close'] >= entry_price:
            return 1, max_profit * 0.75

    final_price = future_bars[min(holding_days-1, len(future_bars)-1)]['close']

    if final_price >= short_strike:
        return 1, max_profit
    elif final_price >= long_strike:
        intrinsic = short_strike - final_price
        pnl = (net_credit - intrinsic) * 100
        return (1 if pnl > 0 else 0), pnl
    else:
        # Max Loss, aber durch Stop-Loss sollte dies selten erreicht werden
        return 0, -stop_loss_amount


def optimize_component_weights(
    trades: List[Dict],
    components: List[str],
    iterations: int = 100
) -> ComponentWeights:
    """
    Optimiert Komponenten-Gewichte basierend auf Trade-Ergebnissen.

    Verwendet einfaches Grid-Search mit Random Sampling.
    """
    import random

    if len(trades) < 20:
        return ComponentWeights(weights={c: 1.0 for c in components})

    best_weights = {c: 1.0 for c in components}
    best_wr = 0.0

    for _ in range(iterations):
        # Random weights zwischen 0.5 und 2.0
        test_weights = {c: random.uniform(0.5, 2.0) for c in components}

        # Berechne Win-Rate mit diesen Gewichten
        wins = 0
        total = 0

        for trade in trades:
            breakdown = trade.get('score_breakdown', {})
            if not breakdown:
                continue

            # Gewichteten Score berechnen
            weighted_score = sum(
                breakdown.get(c, 0) * test_weights.get(c, 1.0)
                for c in components
            )

            # Nur Trades mit Score > 5 zählen
            if weighted_score >= 5.0:
                total += 1
                if trade.get('outcome', 0) == 1:
                    wins += 1

        if total >= 10:
            wr = wins / total * 100
            if wr > best_wr:
                best_wr = wr
                best_weights = test_weights.copy()

    return ComponentWeights(weights=best_weights)


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def analyze_symbol_granular(args: Tuple) -> Dict[str, Any]:
    """
    Vollständige granulare Analyse eines Symbols.

    Sammelt Daten für alle Ebenen:
    - Pro Strategie
    - Pro VIX-Regime
    - Pro Strategie × Regime
    - Score-Breakdowns für Gewichtsoptimierung
    """
    symbol, symbol_data, vix_data, sector, strategies = args

    from src.models.base import SignalType

    results = {
        'symbol': symbol,
        'sector': sector,
        'total_trades': 0,
        'total_wins': 0,
        'total_pnl': 0.0,

        # Per strategy
        'strategies': {},

        # Per regime
        'regimes': {},

        # Per regime × strategy
        'regime_strategy': {},

        # Best combinations
        'best_strategy': '',
        'best_strategy_wr': 0.0,
        'best_regime_strategy': {},  # regime -> best_strategy

        # Score breakdowns for weight optimization
        'trades_with_breakdown': []
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

    split_idx = int(len(sorted_data) * 0.8)

    # Initialize containers
    for strategy in strategies:
        results['strategies'][strategy] = {
            'train_trades': 0, 'train_wins': 0,
            'test_trades': 0, 'test_wins': 0,
            'pnl': 0.0
        }

    for regime in VIX_REGIMES.keys():
        results['regimes'][regime] = {
            'trades': 0, 'wins': 0, 'pnl': 0.0
        }
        results['regime_strategy'][regime] = {}
        for strategy in strategies:
            results['regime_strategy'][regime][strategy] = {
                'train_trades': 0, 'train_wins': 0,
                'test_trades': 0, 'test_wins': 0,
                'pnl': 0.0
            }

    # Analyze
    for strategy in strategies:
        try:
            analyzer = create_analyzer(strategy)
        except Exception:
            continue

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
            vix = vix_data.get(current_date, 20.0)
            regime = get_regime(vix)

            outcome, pnl = simulate_trade(prices[-1], future, 30)

            is_train = idx < split_idx

            # Update strategy stats
            if is_train:
                results['strategies'][strategy]['train_trades'] += 1
                results['strategies'][strategy]['train_wins'] += outcome
            else:
                results['strategies'][strategy]['test_trades'] += 1
                results['strategies'][strategy]['test_wins'] += outcome
            results['strategies'][strategy]['pnl'] += pnl

            # Update regime stats
            results['regimes'][regime]['trades'] += 1
            results['regimes'][regime]['wins'] += outcome
            results['regimes'][regime]['pnl'] += pnl

            # Update regime × strategy stats
            if is_train:
                results['regime_strategy'][regime][strategy]['train_trades'] += 1
                results['regime_strategy'][regime][strategy]['train_wins'] += outcome
            else:
                results['regime_strategy'][regime][strategy]['test_trades'] += 1
                results['regime_strategy'][regime][strategy]['test_wins'] += outcome
            results['regime_strategy'][regime][strategy]['pnl'] += pnl

            # Totals
            results['total_trades'] += 1
            results['total_wins'] += outcome
            results['total_pnl'] += pnl

            # Save breakdown for weight optimization (sample)
            if len(results['trades_with_breakdown']) < 500:
                breakdown = {}
                if hasattr(signal, 'breakdown') and signal.breakdown:
                    breakdown = signal.breakdown
                elif hasattr(signal, 'score_breakdown') and signal.score_breakdown:
                    breakdown = signal.score_breakdown

                results['trades_with_breakdown'].append({
                    'strategy': strategy,
                    'regime': regime,
                    'score': signal.score,
                    'score_breakdown': breakdown,
                    'outcome': outcome,
                    'pnl': pnl
                })

    # Calculate best strategy overall
    for strategy, data in results['strategies'].items():
        total = data['train_trades'] + data['test_trades']
        wins = data['train_wins'] + data['test_wins']
        if total >= 10:
            wr = wins / total * 100
            if wr > results['best_strategy_wr']:
                results['best_strategy'] = strategy
                results['best_strategy_wr'] = wr

    # Calculate best strategy per regime
    for regime, strat_data in results['regime_strategy'].items():
        best_strat = ''
        best_wr = 0.0
        for strategy, data in strat_data.items():
            total = data['train_trades'] + data['test_trades']
            wins = data['train_wins'] + data['test_wins']
            if total >= 5:
                wr = wins / total * 100
                if wr > best_wr:
                    best_wr = wr
                    best_strat = strategy
        results['best_regime_strategy'][regime] = best_strat

    return results


def check_worker_connection() -> bool:
    """Check worker connection"""
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', WORKER_HOST, 'echo OK'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and 'OK' in result.stdout
    except Exception:
        return False


def save_progress(phase: str, detail: str, stats: Dict):
    """Save progress"""
    progress = {
        'timestamp': datetime.now().isoformat(),
        'phase': phase,
        'detail': detail,
        'granular': True,
        **stats
    }
    with open(OUTPUT_DIR / 'granular_progress.json', 'w') as f:
        json.dump(progress, f, indent=2)


def main():
    """Main granular training pipeline"""

    start_time = datetime.now()

    logger.info("=" * 70)
    logger.info("  FULL GRANULAR DISTRIBUTED TRAINING")
    logger.info("=" * 70)
    logger.info("  Training Levels:")
    logger.info("    - VIX Regime × Strategy: 4×4 = 16 configs")
    logger.info("    - Sectors: 11 configs")
    logger.info("    - Symbols: 628+ individual configs")
    logger.info("    - Component Weights: per regime×strategy")
    logger.info("=" * 70)

    # Check worker
    use_distributed = check_worker_connection()
    if use_distributed:
        logger.info(f"  Worker ({WORKER_HOST}) connected!")
    else:
        logger.info("  Worker not available. Single-node mode.")

    # Load data
    logger.info("\nLoading data...")

    from src.backtesting import TradeTracker
    from src.config.watchlist_loader import WatchlistLoader

    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    logger.info(f"  Symbols: {stats['symbols_with_price_data']}")
    logger.info(f"  Price Bars: {stats['total_price_bars']:,}")

    # Load symbol info with sectors
    symbol_info = tracker.list_symbols_with_price_data()
    all_symbols_raw = [s['symbol'] for s in symbol_info]

    # Filter out illiquid symbols from blacklist
    symbols = filter_liquid_symbols(all_symbols_raw)
    blacklisted_count = len(all_symbols_raw) - len(symbols)
    logger.info(f"  Blacklist: {blacklisted_count} illiquid symbols excluded")

    # Load sector mapping from watchlist
    try:
        watchlist_loader = WatchlistLoader()
        all_symbols_info = watchlist_loader.get_all_symbols()
        sector_map = {s['symbol']: s.get('sector', 'unknown') for s in all_symbols_info}
    except Exception:
        sector_map = {}

    # Load price data
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

    # Load VIX
    vix_data = {}
    for p in tracker.get_vix_data():
        vix_data[p.date] = p.value

    logger.info(f"  Loaded: {len(historical_data)} symbols")

    # Split for distribution
    all_symbols = list(historical_data.keys())
    if use_distributed:
        split = int(len(all_symbols) * 0.55)
        master_symbols = all_symbols[split:]
    else:
        master_symbols = all_symbols

    # =========================================================================
    # PHASE 1: GRANULAR SYMBOL ANALYSIS
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  PHASE 1: GRANULAR SYMBOL ANALYSIS")
    logger.info("=" * 70)

    save_progress("Phase 1", "Starting symbol analysis", {'total_symbols': len(master_symbols)})

    master_args = [
        (symbol, historical_data[symbol], vix_data, sector_map.get(symbol, 'unknown'), STRATEGIES)
        for symbol in master_symbols
    ]

    all_results = []
    with Pool(MASTER_WORKERS) as pool:
        for i, result in enumerate(pool.imap_unordered(analyze_symbol_granular, master_args)):
            if result['total_trades'] >= 10:
                all_results.append(result)

            if (i + 1) % 50 == 0:
                logger.info(f"    Progress: {i+1}/{len(master_args)} symbols")

    logger.info(f"  Completed: {len(all_results)} valid symbols")

    # =========================================================================
    # PHASE 2: BUILD GRANULAR MODEL
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  PHASE 2: BUILD GRANULAR MODEL")
    logger.info("=" * 70)

    model = GranularModel(
        created_at=datetime.now().isoformat(),
        training_duration_minutes=(datetime.now() - start_time).total_seconds() / 60
    )

    # Initialize regime × strategy configs
    for regime in VIX_REGIMES.keys():
        model.regime_strategy_configs[regime] = {}
        for strategy in STRATEGIES:
            model.regime_strategy_configs[regime][strategy] = RegimeStrategyConfig(
                regime=regime,
                strategy=strategy
            )

    # Initialize sector configs
    for sector in SECTORS + ['unknown']:
        model.sector_configs[sector] = SectorConfig(sector=sector)

    # Aggregate results
    logger.info("  Aggregating per regime × strategy...")
    for result in all_results:
        # Regime × Strategy
        for regime, strat_data in result['regime_strategy'].items():
            for strategy, data in strat_data.items():
                cfg = model.regime_strategy_configs[regime][strategy]
                cfg.train_trades += data['train_trades']
                cfg.train_wins += data['train_wins']
                cfg.test_trades += data['test_trades']
                cfg.test_wins += data['test_wins']
                cfg.total_pnl += data['pnl']

        # Sector
        sector = result.get('sector', 'unknown')
        if sector not in model.sector_configs:
            model.sector_configs[sector] = SectorConfig(sector=sector)

        sec_cfg = model.sector_configs[sector]
        sec_cfg.total_trades += result['total_trades']
        sec_cfg.total_wins += result['total_wins']

        best_strat = result.get('best_strategy', '')
        if best_strat:
            if best_strat not in sec_cfg.strategy_preferences:
                sec_cfg.strategy_preferences[best_strat] = 0
            sec_cfg.strategy_preferences[best_strat] += 1

        # Symbol
        sym_cfg = SymbolConfig(
            symbol=result['symbol'],
            sector=sector,
            best_strategy=result.get('best_strategy', ''),
            total_trades=result['total_trades'],
            total_wins=result['total_wins'],
            total_pnl=result['total_pnl'],
            strategy_metrics=result['strategies'],
            regime_metrics=result['regimes'],
            optimal_regime_strategy=result.get('best_regime_strategy', {})
        )
        model.symbol_configs[result['symbol']] = sym_cfg

    # =========================================================================
    # PHASE 3: OPTIMIZE WEIGHTS
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  PHASE 3: OPTIMIZE COMPONENT WEIGHTS")
    logger.info("=" * 70)

    # Collect all trade breakdowns per regime × strategy
    regime_strategy_trades = defaultdict(list)

    for result in all_results:
        for trade in result.get('trades_with_breakdown', []):
            key = (trade['regime'], trade['strategy'])
            regime_strategy_trades[key].append(trade)

    # Optimize weights
    for regime in VIX_REGIMES.keys():
        for strategy in STRATEGIES:
            trades = regime_strategy_trades.get((regime, strategy), [])
            if len(trades) >= 50:
                components = STRATEGY_COMPONENTS.get(strategy, [])
                weights = optimize_component_weights(trades, components, iterations=200)
                model.regime_strategy_configs[regime][strategy].component_weights = weights
                logger.info(f"    {regime} × {strategy}: Optimized {len(components)} weights from {len(trades)} trades")

    # =========================================================================
    # PHASE 4: DETERMINE ENABLED STRATEGIES & THRESHOLDS
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  PHASE 4: DETERMINE THRESHOLDS & ENABLEMENT")
    logger.info("=" * 70)

    for regime in VIX_REGIMES.keys():
        logger.info(f"\n  {regime.upper()} Regime:")
        for strategy in STRATEGIES:
            cfg = model.regime_strategy_configs[regime][strategy]
            total = cfg.train_trades + cfg.test_trades

            if total < 20:
                cfg.enabled = False
                logger.info(f"    {strategy}: DISABLED (insufficient trades: {total})")
                continue

            # Win rates
            overall_wr = (cfg.train_wins + cfg.test_wins) / total * 100

            # Disable if too low
            if overall_wr < 45:
                cfg.enabled = False
                logger.info(f"    {strategy}: DISABLED (WR: {overall_wr:.1f}%)")
                continue

            # Set min_score based on regime
            base_scores = {'low': 4.5, 'normal': 5.0, 'elevated': 6.0, 'high': 7.5}
            cfg.min_score = base_scores.get(regime, 5.0)

            # Adjust based on degradation
            if cfg.degradation > 10:
                cfg.min_score += 0.5  # More conservative if overfit
            elif cfg.degradation < 0:
                cfg.min_score -= 0.5  # Can be more aggressive if generalizes well

            cfg.min_score = max(4.0, min(9.0, cfg.min_score))

            logger.info(f"    {strategy}: ENABLED, min_score={cfg.min_score:.1f}, WR={overall_wr:.1f}%, deg={cfg.degradation:.1f}%")

    # =========================================================================
    # PHASE 5: SECTOR ANALYSIS
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  PHASE 5: SECTOR ANALYSIS")
    logger.info("=" * 70)

    for sector, cfg in model.sector_configs.items():
        if cfg.total_trades < 20:
            continue

        wr = cfg.total_wins / cfg.total_trades * 100

        # Find best strategy for sector
        if cfg.strategy_preferences:
            best = max(cfg.strategy_preferences.items(), key=lambda x: x[1])
            cfg.best_strategy = best[0]

            # Calculate WR per strategy in sector
            sector_symbols = [s for s in all_results if s.get('sector') == sector]
            strat_wins = defaultdict(int)
            strat_trades = defaultdict(int)

            for sym in sector_symbols:
                for strat, data in sym['strategies'].items():
                    t = data['train_trades'] + data['test_trades']
                    w = data['train_wins'] + data['test_wins']
                    strat_trades[strat] += t
                    strat_wins[strat] += w

            best_wr = 0
            for strat in STRATEGIES:
                if strat_trades[strat] >= 10:
                    swr = strat_wins[strat] / strat_trades[strat] * 100
                    if swr > best_wr:
                        best_wr = swr
                        cfg.best_strategy = strat
                        cfg.best_strategy_wr = swr

        logger.info(f"  {sector}: {cfg.total_trades} trades, {wr:.1f}% WR, best={cfg.best_strategy}")

    # =========================================================================
    # SAVE RESULTS
    # =========================================================================
    logger.info("\n" + "=" * 70)
    logger.info("  SAVING GRANULAR MODEL")
    logger.info("=" * 70)

    # Summary
    total_trades = sum(r['total_trades'] for r in all_results)
    total_wins = sum(r['total_wins'] for r in all_results)
    total_pnl = sum(r['total_pnl'] for r in all_results)

    model.summary = {
        'total_trades': total_trades,
        'total_wins': total_wins,
        'win_rate': total_wins / total_trades * 100 if total_trades > 0 else 0,
        'total_pnl': total_pnl,
        'symbols_analyzed': len(all_results),
        'regime_strategy_configs': 16,
        'sector_configs': len([s for s in model.sector_configs.values() if s.total_trades >= 20]),
        'symbol_configs': len(model.symbol_configs)
    }

    # Convert to serializable format
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output = {
        'version': model.version,
        'created_at': model.created_at,
        'training_duration_minutes': model.training_duration_minutes,
        'summary': model.summary,

        'regime_strategy_configs': {
            regime: {
                strategy: {
                    'enabled': cfg.enabled,
                    'min_score': cfg.min_score,
                    'profit_target_pct': cfg.profit_target_pct,
                    'stop_loss_pct': cfg.stop_loss_pct,
                    'train_trades': cfg.train_trades,
                    'train_wins': cfg.train_wins,
                    'test_trades': cfg.test_trades,
                    'test_wins': cfg.test_wins,
                    'train_wr': cfg.train_wr,
                    'test_wr': cfg.test_wr,
                    'degradation': cfg.degradation,
                    'total_pnl': cfg.total_pnl,
                    'component_weights': cfg.component_weights.weights
                }
                for strategy, cfg in strats.items()
            }
            for regime, strats in model.regime_strategy_configs.items()
        },

        'sector_configs': {
            sector: {
                'total_trades': cfg.total_trades,
                'total_wins': cfg.total_wins,
                'win_rate': cfg.total_wins / cfg.total_trades * 100 if cfg.total_trades > 0 else 0,
                'best_strategy': cfg.best_strategy,
                'best_strategy_wr': cfg.best_strategy_wr,
                'strategy_preferences': cfg.strategy_preferences
            }
            for sector, cfg in model.sector_configs.items()
            if cfg.total_trades >= 10
        },

        'symbol_configs': {
            sym: {
                'sector': cfg.sector,
                'best_strategy': cfg.best_strategy,
                'total_trades': cfg.total_trades,
                'total_wins': cfg.total_wins,
                'win_rate': cfg.total_wins / cfg.total_trades * 100 if cfg.total_trades > 0 else 0,
                'total_pnl': cfg.total_pnl,
                'optimal_regime_strategy': cfg.optimal_regime_strategy
            }
            for sym, cfg in model.symbol_configs.items()
        }
    }

    # Save
    with open(OUTPUT_DIR / f'granular_model_{timestamp}.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    with open(OUTPUT_DIR / 'GRANULAR_TRAINED_MODEL.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    # Final Summary
    duration = (datetime.now() - start_time).total_seconds() / 60

    logger.info(f"\n  Saved to {OUTPUT_DIR}")

    logger.info("\n" + "=" * 70)
    logger.info("  GRANULAR TRAINING COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Duration: {duration:.1f} minutes")
    logger.info(f"  Total Trades: {total_trades:,}")
    logger.info(f"  Win Rate: {total_wins/total_trades*100:.1f}%")
    logger.info(f"  Total P&L: ${total_pnl:,.0f}")
    logger.info(f"\n  Model Components:")
    logger.info(f"    Regime×Strategy Configs: 16")
    logger.info(f"    Sector Configs: {model.summary['sector_configs']}")
    logger.info(f"    Symbol Configs: {model.summary['symbol_configs']}")

    # Show regime × strategy matrix
    logger.info("\n  Regime × Strategy Matrix (Win Rates):")
    logger.info("  " + "-" * 60)
    header = "              " + "  ".join(f"{s[:8]:>8}" for s in STRATEGIES)
    logger.info(f"  {header}")
    logger.info("  " + "-" * 60)

    for regime in VIX_REGIMES.keys():
        row = f"  {regime:>10}:"
        for strategy in STRATEGIES:
            cfg = model.regime_strategy_configs[regime][strategy]
            total = cfg.train_trades + cfg.test_trades
            if total >= 10:
                wr = (cfg.train_wins + cfg.test_wins) / total * 100
                status = "✓" if cfg.enabled else "✗"
                row += f"  {wr:>5.1f}%{status}"
            else:
                row += f"     n/a "
        logger.info(row)

    logger.info("\n" + "=" * 70)

    save_progress("Complete", "Done", model.summary)


if __name__ == '__main__':
    main()
