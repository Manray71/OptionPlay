#!/usr/bin/env python3
"""
OptionPlay - Strategy-Specific Backtesting & Training
======================================================

Führt Backtesting und Walk-Forward Training individuell für jede Strategie durch:
- pullback
- bounce
- ath_breakout
- earnings_dip

Usage:
    # Alle Strategien testen
    python scripts/backtest_per_strategy.py

    # Einzelne Strategie
    python scripts/backtest_per_strategy.py --strategy pullback

    # Mit Training
    python scripts/backtest_per_strategy.py --train

    # Verbose Output
    python scripts/backtest_per_strategy.py --verbose
"""

import argparse
import json
import sys
import asyncio
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
import statistics
import logging

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from src.backtesting import TradeTracker, TradeOutcome, ExitReason
from src.config.models import PullbackScoringConfig
from src.analyzers.pullback import PullbackAnalyzer
from src.analyzers.bounce import BounceAnalyzer, BounceConfig
from src.analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
from src.analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
from src.analyzers.trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig
from src.analyzers.base import BaseAnalyzer
from src.models.base import TradeSignal, SignalType

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class StrategyBacktestConfig:
    """Konfiguration für Strategy-Backtest"""
    initial_capital: float = 100000.0
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 100.0
    min_score: float = 5.0
    dte_max: int = 60
    dte_exit_threshold: int = 14
    slippage_pct: float = 1.0
    commission_per_contract: float = 1.30
    max_position_pct: float = 5.0
    max_total_risk_pct: float = 25.0
    min_otm_pct: float = 8.0
    spread_width_pct: float = 5.0
    min_credit_pct: float = 20.0


@dataclass
class TradeRecord:
    """Einzelner Trade-Record"""
    symbol: str
    strategy: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    signal_score: float
    realized_pnl: float
    outcome: TradeOutcome
    hold_days: int
    score_breakdown: Optional[Dict[str, float]] = None


@dataclass
class StrategyResult:
    """Ergebnis für eine Strategie"""
    strategy: str
    trades: List[TradeRecord]
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0

    def __post_init__(self):
        if self.trades:
            self._calculate_metrics()

    def _calculate_metrics(self):
        self.total_trades = len(self.trades)
        winners = [t for t in self.trades if t.realized_pnl > 0]
        losers = [t for t in self.trades if t.realized_pnl < 0]

        self.winning_trades = len(winners)
        self.losing_trades = len(losers)

        total_profit = sum(t.realized_pnl for t in winners)
        total_loss = abs(sum(t.realized_pnl for t in losers))
        self.total_pnl = total_profit - total_loss

        if self.total_trades > 0:
            self.win_rate = (self.winning_trades / self.total_trades) * 100

        if winners:
            self.avg_win = total_profit / len(winners)
        if losers:
            self.avg_loss = total_loss / len(losers)

        if total_loss > 0:
            self.profit_factor = total_profit / total_loss

        # Equity curve for drawdown
        equity = [100000.0]  # Starting capital
        for t in sorted(self.trades, key=lambda x: x.exit_date):
            equity.append(equity[-1] + t.realized_pnl)

        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = peak - e
            if dd > max_dd:
                max_dd = dd
        self.max_drawdown = max_dd

        # Sharpe
        if len(self.trades) >= 2:
            returns = [t.realized_pnl / 100000.0 for t in self.trades]
            avg_ret = statistics.mean(returns)
            std_ret = statistics.stdev(returns) if len(returns) > 1 else 0
            if std_ret > 0:
                self.sharpe_ratio = (avg_ret * 12) / (std_ret * (12 ** 0.5))


# =============================================================================
# STRATEGY BACKTESTER
# =============================================================================

class StrategyBacktester:
    """Führt Backtests für einzelne Strategien durch"""

    STRATEGIES = ['pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'trend_continuation']

    def __init__(self, config: StrategyBacktestConfig):
        self.config = config
        self._analyzers: Dict[str, BaseAnalyzer] = {}
        self._init_analyzers()

    def _init_analyzers(self):
        """Initialisiert alle Strategy-Analyzer"""
        # Pullback
        pullback_config = PullbackScoringConfig()
        self._analyzers['pullback'] = PullbackAnalyzer(pullback_config)

        # Bounce
        bounce_config = BounceConfig()
        self._analyzers['bounce'] = BounceAnalyzer(bounce_config)

        # ATH Breakout
        breakout_config = ATHBreakoutConfig()
        self._analyzers['ath_breakout'] = ATHBreakoutAnalyzer(breakout_config)

        # Earnings Dip
        dip_config = EarningsDipConfig()
        self._analyzers['earnings_dip'] = EarningsDipAnalyzer(dip_config)

        # Trend Continuation
        tc_config = TrendContinuationConfig()
        self._analyzers['trend_continuation'] = TrendContinuationAnalyzer(tc_config)

    def run_backtest(
        self,
        strategy: str,
        historical_data: Dict[str, List[Dict]],
        vix_data: Optional[List[Dict]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> StrategyResult:
        """
        Führt Backtest für eine spezifische Strategie durch.

        Args:
            strategy: Name der Strategie
            historical_data: {symbol: [{date, open, high, low, close, volume}, ...]}
            vix_data: Optional VIX data
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            StrategyResult mit allen Trades und Metriken
        """
        if strategy not in self._analyzers:
            raise ValueError(f"Unknown strategy: {strategy}. Available: {self.STRATEGIES}")

        analyzer = self._analyzers[strategy]
        trades: List[TradeRecord] = []

        # Determine date range
        all_dates = set()
        for sym_data in historical_data.values():
            for bar in sym_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                all_dates.add(d)

        if not all_dates:
            return StrategyResult(strategy=strategy, trades=[])

        min_date = start_date or min(all_dates)
        max_date = end_date or max(all_dates)

        # Generate trading days
        trading_days = sorted([d for d in all_dates if min_date <= d <= max_date])

        # Track open positions
        open_positions: Dict[str, Dict] = {}  # symbol -> position
        current_capital = self.config.initial_capital
        current_risk = 0.0

        symbols = list(historical_data.keys())

        for current_date in trading_days:
            # Check exits for open positions
            positions_to_close = []
            for symbol, pos in list(open_positions.items()):
                exit_signal = self._check_exit(pos, current_date, historical_data.get(symbol, []))
                if exit_signal:
                    positions_to_close.append((symbol, pos, exit_signal))

            # Close positions
            for symbol, pos, (reason, exit_price) in positions_to_close:
                trade = self._close_position(pos, current_date, reason, exit_price, strategy)
                trades.append(trade)
                current_capital += trade.realized_pnl
                current_risk -= pos.get('max_loss', 0)
                del open_positions[symbol]

            # Check for new entries
            for symbol in symbols:
                # Skip if already have position
                if symbol in open_positions:
                    continue

                # Skip if at risk limit
                if current_risk >= self.config.initial_capital * (self.config.max_total_risk_pct / 100):
                    continue

                # Get data up to current_date
                symbol_data = historical_data.get(symbol, [])
                history = self._get_history_up_to(symbol_data, current_date, lookback=260)

                if len(history) < 60:
                    continue

                # Prepare arrays for analyzer
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
                except Exception as e:
                    logger.debug(f"Error analyzing {symbol}: {e}")
                    continue

                # Check if signal qualifies
                if signal.signal_type != SignalType.LONG:
                    continue
                if signal.score < self.config.min_score:
                    continue

                # Open position
                current_price = prices[-1]
                max_position_risk = self.config.initial_capital * (self.config.max_position_pct / 100)
                available_risk = (self.config.initial_capital * (self.config.max_total_risk_pct / 100)) - current_risk

                position = self._open_position(
                    symbol, current_date, current_price, signal.score,
                    min(max_position_risk, available_risk),
                    signal.details.get('score_breakdown') if signal.details else None
                )

                if position:
                    open_positions[symbol] = position
                    current_risk += position.get('max_loss', 0)

        # Close remaining positions at end
        for symbol, pos in open_positions.items():
            symbol_data = historical_data.get(symbol, [])
            last_price = pos['entry_price']
            for bar in symbol_data:
                d = bar['date']
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if d == max_date:
                    last_price = bar['close']
                    break

            trade = self._close_position(
                pos, max_date, ExitReason.MANUAL, last_price, strategy
            )
            trades.append(trade)

        return StrategyResult(strategy=strategy, trades=trades)

    def _get_history_up_to(
        self,
        symbol_data: List[Dict],
        target_date: date,
        lookback: int = 260
    ) -> List[Dict]:
        """Gets historical bars up to (not including) target_date"""
        bars_before = []
        for bar in symbol_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if d < target_date:
                bars_before.append({**bar, 'date': d})

        # Sort by date and take last N bars
        bars_before.sort(key=lambda x: x['date'])
        return bars_before[-lookback:] if len(bars_before) > lookback else bars_before

    def _get_price_on_date(self, symbol_data: List[Dict], target_date: date) -> Optional[Dict]:
        """Gets price data for specific date"""
        for bar in symbol_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if d == target_date:
                return bar
        return None

    def _open_position(
        self,
        symbol: str,
        entry_date: date,
        current_price: float,
        score: float,
        max_risk: float,
        score_breakdown: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Opens a new position"""
        otm_pct = self.config.min_otm_pct / 100
        short_strike = round(current_price * (1 - otm_pct), 0)

        spread_width_pct = self.config.spread_width_pct / 100
        spread_width = max(5.0, round(current_price * spread_width_pct / 5) * 5)
        long_strike = short_strike - spread_width

        credit_pct = self.config.min_credit_pct / 100
        net_credit = spread_width * credit_pct
        net_credit *= (1 - self.config.slippage_pct / 100)

        max_loss_per_contract = (spread_width - net_credit) * 100
        contracts = max(1, int(max_risk / max_loss_per_contract))

        total_max_profit = net_credit * 100 * contracts
        total_max_loss = max_loss_per_contract * contracts
        commission = self.config.commission_per_contract * contracts * 2

        return {
            'symbol': symbol,
            'entry_date': entry_date,
            'entry_price': current_price,
            'short_strike': short_strike,
            'long_strike': long_strike,
            'spread_width': spread_width,
            'net_credit': net_credit,
            'contracts': contracts,
            'max_profit': total_max_profit - commission,
            'max_loss': total_max_loss + commission,
            'score': score,
            'score_breakdown': score_breakdown,
            'dte_at_entry': self.config.dte_max,
            'expiry_date': entry_date + timedelta(days=self.config.dte_max),
        }

    def _check_exit(
        self,
        position: Dict,
        current_date: date,
        symbol_data: List[Dict]
    ) -> Optional[Tuple[ExitReason, float]]:
        """Checks if position should exit"""
        price_data = self._get_price_on_date(symbol_data, current_date)
        current_price = price_data['close'] if price_data else position['entry_price']

        short_strike = position['short_strike']
        net_credit = position['net_credit']
        expiry = position['expiry_date']
        dte = (expiry - current_date).days

        # Expiration
        if current_date >= expiry:
            return (ExitReason.EXPIRATION, current_price)

        # Short strike breached
        if current_price < short_strike:
            spread_value = short_strike - current_price
            if spread_value >= position['spread_width'] * 0.8:
                return (ExitReason.BREACH_SHORT_STRIKE, current_price)

        # Profit target
        days_held = (current_date - position['entry_date']).days
        if days_held > 0 and dte > 0:
            time_decay_factor = days_held / position['dte_at_entry']
            price_buffer_pct = ((current_price - short_strike) / short_strike) * 100 if short_strike > 0 else 0
            estimated_profit_pct = min((time_decay_factor * 50) + (price_buffer_pct * 5), 100)

            if estimated_profit_pct >= self.config.profit_target_pct:
                return (ExitReason.PROFIT_TARGET_HIT, current_price)

        # DTE threshold
        if dte <= self.config.dte_exit_threshold and dte > 0:
            return (ExitReason.DTE_THRESHOLD, current_price)

        # Stop loss
        if current_price < short_strike:
            loss_pct = ((short_strike - current_price) / net_credit) * 100 if net_credit > 0 else 0
            if loss_pct >= self.config.stop_loss_pct:
                return (ExitReason.STOP_LOSS_HIT, current_price)

        return None

    def _close_position(
        self,
        position: Dict,
        exit_date: date,
        exit_reason: ExitReason,
        exit_price: float,
        strategy: str
    ) -> TradeRecord:
        """Closes position and calculates P&L"""
        short_strike = position['short_strike']
        long_strike = position['long_strike']
        net_credit = position['net_credit']
        contracts = position['contracts']

        if exit_price >= short_strike:
            realized_pnl = position['max_profit']
            outcome = TradeOutcome.MAX_PROFIT
        elif exit_price <= long_strike:
            realized_pnl = -position['max_loss']
            outcome = TradeOutcome.MAX_LOSS
        else:
            intrinsic_value = short_strike - exit_price
            spread_cost = intrinsic_value * 100 * contracts
            commission = self.config.commission_per_contract * contracts * 2
            realized_pnl = (net_credit * 100 * contracts) - spread_cost - commission

            if realized_pnl > 0:
                outcome = TradeOutcome.PROFIT_TARGET if exit_reason == ExitReason.PROFIT_TARGET_HIT else TradeOutcome.PARTIAL_PROFIT
            elif realized_pnl < 0:
                outcome = TradeOutcome.STOP_LOSS if exit_reason == ExitReason.STOP_LOSS_HIT else TradeOutcome.PARTIAL_LOSS
            else:
                outcome = TradeOutcome.PARTIAL_PROFIT

        hold_days = (exit_date - position['entry_date']).days

        return TradeRecord(
            symbol=position['symbol'],
            strategy=strategy,
            entry_date=position['entry_date'],
            exit_date=exit_date,
            entry_price=position['entry_price'],
            exit_price=exit_price,
            signal_score=position['score'],
            realized_pnl=realized_pnl,
            outcome=outcome,
            hold_days=max(1, hold_days),
            score_breakdown=position.get('score_breakdown')
        )


# =============================================================================
# DATA LOADING
# =============================================================================

def load_historical_data(tracker: TradeTracker, symbols: List[str]) -> Dict[str, List[Dict]]:
    """Loads historical data from database"""
    data = {}
    for symbol in symbols:
        price_data = tracker.get_price_data(symbol)
        if price_data and price_data.bars:
            data[symbol] = [
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
    return data


def load_vix_data(tracker: TradeTracker) -> List[Dict]:
    """Loads VIX data from database"""
    vix_points = tracker.get_vix_data()
    if not vix_points:
        return []
    return [{'date': p.date, 'close': p.value} for p in vix_points]


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def print_strategy_result(result: StrategyResult):
    """Prints formatted strategy result"""
    print()
    print("═" * 70)
    print(f"  STRATEGY: {result.strategy.upper()}")
    print("═" * 70)
    print()
    print(f"  Total Trades:     {result.total_trades}")
    print(f"  Winning Trades:   {result.winning_trades} ({result.win_rate:.1f}%)")
    print(f"  Losing Trades:    {result.losing_trades}")
    print()
    print(f"  Total P&L:        ${result.total_pnl:+,.2f}")
    print(f"  Profit Factor:    {result.profit_factor:.2f}")
    print(f"  Avg Win:          ${result.avg_win:,.2f}")
    print(f"  Avg Loss:         ${result.avg_loss:,.2f}")
    print()
    print(f"  Max Drawdown:     ${result.max_drawdown:,.2f}")
    print(f"  Sharpe Ratio:     {result.sharpe_ratio:.2f}")
    print("═" * 70)


def print_comparison_table(results: List[StrategyResult]):
    """Prints comparison table for all strategies"""
    print()
    print("═" * 90)
    print("  STRATEGY COMPARISON")
    print("═" * 90)
    print()
    print(f"{'Strategy':<15} {'Trades':>8} {'Win%':>8} {'P&L':>12} {'PF':>8} {'Sharpe':>8} {'MaxDD':>12}")
    print("─" * 90)

    for r in sorted(results, key=lambda x: x.total_pnl, reverse=True):
        win_indicator = "🟢" if r.win_rate >= 60 else "🟡" if r.win_rate >= 50 else "🔴"
        pnl_indicator = "🟢" if r.total_pnl > 0 else "🔴"

        print(
            f"{r.strategy:<15} "
            f"{r.total_trades:>8} "
            f"{win_indicator} {r.win_rate:>5.1f}% "
            f"{pnl_indicator} ${r.total_pnl:>+9,.0f} "
            f"{r.profit_factor:>8.2f} "
            f"{r.sharpe_ratio:>8.2f} "
            f"${r.max_drawdown:>10,.0f}"
        )

    print("═" * 90)


def save_results(results: List[StrategyResult], output_path: Path):
    """Saves results to JSON"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'strategies': {}
    }

    for r in results:
        data['strategies'][r.strategy] = {
            'total_trades': r.total_trades,
            'winning_trades': r.winning_trades,
            'losing_trades': r.losing_trades,
            'total_pnl': r.total_pnl,
            'win_rate': r.win_rate,
            'profit_factor': r.profit_factor,
            'max_drawdown': r.max_drawdown,
            'sharpe_ratio': r.sharpe_ratio,
            'trades': [
                {
                    'symbol': t.symbol,
                    'entry_date': str(t.entry_date),
                    'exit_date': str(t.exit_date),
                    'realized_pnl': t.realized_pnl,
                    'outcome': t.outcome.value,
                    'signal_score': t.signal_score,
                }
                for t in r.trades
            ]
        }

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\nResults saved to: {output_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Strategy-specific backtesting and training',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--strategy', type=str, choices=['pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'trend_continuation', 'all'],
                        default='all', help='Strategy to test (default: all)')
    parser.add_argument('--min-score', type=float, default=5.0,
                        help='Minimum signal score (default: 5.0)')
    parser.add_argument('--profit-target', type=float, default=50.0,
                        help='Profit target %% (default: 50)')
    parser.add_argument('--stop-loss', type=float, default=100.0,
                        help='Stop loss %% (default: 100)')
    parser.add_argument('--capital', type=float, default=100000.0,
                        help='Initial capital (default: 100000)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    parser.add_argument('--output', type=str,
                        help='Save results to JSON file')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
    )

    print("═" * 70)
    print("  OPTIONPLAY STRATEGY-SPECIFIC BACKTEST")
    print("═" * 70)

    # Load data
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()

    if stats['symbols_with_price_data'] == 0:
        print("\n❌ No historical data found!")
        print("   Run first: python scripts/collect_historical_data.py --all")
        sys.exit(1)

    print(f"\n  Database: {stats['symbols_with_price_data']} symbols, {stats['total_price_bars']:,} bars")

    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s['symbol'] for s in symbol_info]

    print(f"  Loading historical data for {len(symbols)} symbols...")
    historical_data = load_historical_data(tracker, symbols)
    vix_data = load_vix_data(tracker)

    print(f"  Loaded: {len(historical_data)} symbols with data")

    # Determine date range
    all_dates = []
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar['date']
            if isinstance(d, str):
                d = date.fromisoformat(d)
            all_dates.append(d)

    start_date = min(all_dates)
    end_date = max(all_dates)
    print(f"  Date range: {start_date} to {end_date}")

    # Configure backtest
    config = StrategyBacktestConfig(
        initial_capital=args.capital,
        profit_target_pct=args.profit_target,
        stop_loss_pct=args.stop_loss,
        min_score=args.min_score,
    )

    print(f"\n  Config:")
    print(f"    Capital:       ${config.initial_capital:,.0f}")
    print(f"    Profit Target: {config.profit_target_pct}%")
    print(f"    Stop Loss:     {config.stop_loss_pct}%")
    print(f"    Min Score:     {config.min_score}")

    # Run backtests
    backtester = StrategyBacktester(config)
    results: List[StrategyResult] = []

    strategies = [args.strategy] if args.strategy != 'all' else StrategyBacktester.STRATEGIES

    print("\n" + "═" * 70)
    print("  RUNNING BACKTESTS...")
    print("═" * 70)

    for strategy in strategies:
        print(f"\n  Testing {strategy}...")

        try:
            result = backtester.run_backtest(
                strategy=strategy,
                historical_data=historical_data,
                vix_data=vix_data,
                start_date=start_date,
                end_date=end_date,
            )
            results.append(result)
            print(f"    ✓ {result.total_trades} trades, Win Rate: {result.win_rate:.1f}%, P&L: ${result.total_pnl:+,.0f}")
        except Exception as e:
            print(f"    ✗ Error: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Print results
    for result in results:
        if args.verbose:
            print_strategy_result(result)

    if len(results) > 1:
        print_comparison_table(results)
    elif results:
        print_strategy_result(results[0])

    # Save if requested
    if args.output:
        save_results(results, Path(args.output))

    # Summary
    print("\n" + "═" * 70)
    if results:
        best = max(results, key=lambda x: x.total_pnl)
        print(f"  Best Strategy: {best.strategy.upper()}")
        print(f"  P&L: ${best.total_pnl:+,.0f} | Win Rate: {best.win_rate:.1f}% | PF: {best.profit_factor:.2f}")
    print("═" * 70)


if __name__ == '__main__':
    main()
