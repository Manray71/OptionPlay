#!/usr/bin/env python3
"""
Walk-Forward-Backtest: EQS Ranking vs. Signal-Score-Only Ranking

Vergleicht zwei Ranking-Methoden auf historischen Trades:
  A) Baseline: Ranking nur nach Signal Score (Summe aller Sub-Scores)
  B) EQS:     Ranking nach Signal Score * (1 + EQS * 0.3)

Split:
  Train: 2021-01 bis 2023-12
  Test:  2024-01 bis 2025-10

Metriken:
  - Win Rate (%)
  - Avg Capital Efficiency (Profit / Max_Risk / Haltezeit)
  - Avg P&L pro Trade ($)
  - Max Drawdown Serie
  - Avg Profit (nur Gewinner)
  - Avg Loss (nur Verlierer)

Usage:
    python scripts/eqs_backtest.py
"""

import sqlite3
import sys
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.entry_quality_scorer import EntryQualityScorer


# =============================================================================
# CONFIGURATION
# =============================================================================

OUTCOMES_DB = Path.home() / ".optionplay" / "outcomes.db"
TRADES_DB = Path.home() / ".optionplay" / "trades.db"

TRAIN_END = "2024-01-01"    # Train: everything before this
TEST_START = "2024-01-01"    # Test: everything from this date

# Simulate daily picks: pick top N per day
PICKS_PER_DAY = 5


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TradeRecord:
    """A single backtested trade."""
    symbol: str
    entry_date: str
    exit_date: str
    net_credit: float
    spread_width: float
    pnl: float
    pnl_pct: float
    was_profitable: int
    dte_at_entry: int
    vix_at_entry: float
    max_drawdown_pct: float
    held_to_expiration: int

    # Signal Scores
    signal_score: float      # Sum of all sub-scores
    pullback_score: float
    bounce_score: float
    ath_breakout_score: float
    earnings_dip_score: float

    # EQS inputs
    rsi_value: Optional[float]
    credit_pct: float        # net_credit / spread_width * 100

    # Computed
    eqs_total: float = 0.0
    eqs_normalized: float = 0.0
    ranking_score_baseline: float = 0.0
    ranking_score_eqs: float = 0.0

    # Duration
    @property
    def holding_days(self) -> int:
        from datetime import datetime
        d1 = datetime.strptime(self.entry_date, "%Y-%m-%d")
        d2 = datetime.strptime(self.exit_date, "%Y-%m-%d")
        return (d2 - d1).days

    @property
    def capital_efficiency(self) -> float:
        """Profit / Max_Risk / Haltezeit (annualized)."""
        max_risk = (self.spread_width - self.net_credit) * 100
        if max_risk <= 0 or self.holding_days <= 0:
            return 0.0
        # Annualized return
        return (self.pnl / max_risk) * (365 / self.holding_days)


@dataclass
class BacktestMetrics:
    """Metrics for a ranking method."""
    name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    avg_capital_efficiency: float = 0.0
    avg_profit_winners: float = 0.0
    avg_loss_losers: float = 0.0
    max_consecutive_losses: int = 0
    avg_holding_days: float = 0.0


# =============================================================================
# DATA LOADING
# =============================================================================

def load_trades() -> List[TradeRecord]:
    """Load trades from outcomes.db with computed signal scores."""
    conn = sqlite3.connect(str(OUTCOMES_DB))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT symbol, entry_date, exit_date, net_credit, spread_width,
               pnl, pnl_pct, was_profitable, dte_at_entry,
               vix_at_entry, max_drawdown_pct, held_to_expiration,
               rsi_score, support_score, fibonacci_score, ma_score,
               volume_score, macd_score, stoch_score, keltner_score,
               trend_strength_score, momentum_score, rs_score,
               candlestick_score, vwap_score, market_context_score,
               sector_score, gap_score,
               pullback_score, bounce_score, ath_breakout_score, earnings_dip_score,
               rsi_value
        FROM trade_outcomes
        WHERE rsi_score IS NOT NULL
          AND spread_width > 0
          AND net_credit > 0
        ORDER BY entry_date
    """)

    trades = []
    for row in cursor.fetchall():
        # Sum all technical sub-scores for signal score
        signal_score = sum(filter(None, [
            row['rsi_score'], row['support_score'], row['fibonacci_score'],
            row['ma_score'], row['volume_score'], row['macd_score'],
            row['stoch_score'], row['keltner_score'], row['trend_strength_score'],
            row['momentum_score'], row['rs_score'], row['candlestick_score'],
            row['vwap_score'], row['market_context_score'], row['sector_score'],
            row['gap_score'],
        ]))

        credit_pct = (row['net_credit'] / row['spread_width']) * 100 if row['spread_width'] > 0 else 0

        trade = TradeRecord(
            symbol=row['symbol'],
            entry_date=row['entry_date'],
            exit_date=row['exit_date'],
            net_credit=row['net_credit'],
            spread_width=row['spread_width'],
            pnl=row['pnl'],
            pnl_pct=row['pnl_pct'],
            was_profitable=row['was_profitable'],
            dte_at_entry=row['dte_at_entry'],
            vix_at_entry=row['vix_at_entry'] or 20.0,
            max_drawdown_pct=row['max_drawdown_pct'] or 0.0,
            held_to_expiration=row['held_to_expiration'] or 0,
            signal_score=signal_score,
            pullback_score=row['pullback_score'] or 0.0,
            bounce_score=row['bounce_score'] or 0.0,
            ath_breakout_score=row['ath_breakout_score'] or 0.0,
            earnings_dip_score=row['earnings_dip_score'] or 0.0,
            rsi_value=row['rsi_value'],
            credit_pct=credit_pct,
        )
        trades.append(trade)

    conn.close()
    return trades


def load_iv_data() -> Dict[str, Dict[str, float]]:
    """
    Load IV Rank proxy data from trades.db.

    Returns dict of {symbol: {date: iv_value}}.
    We use ATM put IV (delta ~ -0.50) as the IV proxy.
    """
    if not TRADES_DB.exists():
        print("WARNING: trades.db not found, using default IV values")
        return {}

    conn = sqlite3.connect(str(TRADES_DB))
    cursor = conn.cursor()

    # Get daily average ATM IV per symbol
    cursor.execute("""
        SELECT p.underlying, p.quote_date, AVG(g.iv_calculated) as avg_iv
        FROM options_greeks g
        JOIN options_prices p ON g.options_price_id = p.id
        WHERE p.option_type = 'P'
          AND g.delta BETWEEN -0.55 AND -0.45
          AND p.dte BETWEEN 25 AND 35
          AND g.iv_calculated IS NOT NULL
          AND g.iv_calculated > 0
        GROUP BY p.underlying, p.quote_date
        ORDER BY p.underlying, p.quote_date
    """)

    iv_data: Dict[str, Dict[str, float]] = defaultdict(dict)
    for row in cursor.fetchall():
        symbol, qdate, avg_iv = row
        iv_data[symbol][qdate] = avg_iv

    conn.close()
    print(f"Loaded IV data for {len(iv_data)} symbols")
    return iv_data


def compute_iv_rank_for_trade(
    symbol: str,
    entry_date: str,
    iv_data: Dict[str, Dict[str, float]],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute IV Rank and IV Percentile for a trade at entry date.

    Uses 252-day lookback from entry date.
    """
    from src.cache.iv_cache_impl import calculate_iv_rank, calculate_iv_percentile

    sym_data = iv_data.get(symbol, {})
    if not sym_data:
        return None, None

    # Get sorted dates up to entry_date
    dates = sorted([d for d in sym_data.keys() if d <= entry_date])

    if len(dates) < 30:
        return None, None

    # Use last 252 trading days
    lookback = dates[-252:] if len(dates) >= 252 else dates
    iv_history = [sym_data[d] for d in lookback]

    # Current IV = last available before entry
    current_iv = iv_history[-1]

    iv_rank = calculate_iv_rank(current_iv, iv_history)
    iv_percentile = calculate_iv_percentile(current_iv, iv_history)

    return iv_rank, iv_percentile


# =============================================================================
# EQS COMPUTATION
# =============================================================================

def compute_eqs_for_trades(
    trades: List[TradeRecord],
    iv_data: Dict[str, Dict[str, float]],
) -> List[TradeRecord]:
    """Compute EQS for all trades using available data."""
    scorer = EntryQualityScorer()
    enriched = 0

    for trade in trades:
        # Get IV metrics
        iv_rank, iv_percentile = compute_iv_rank_for_trade(
            trade.symbol, trade.entry_date, iv_data
        )

        # Estimate pullback_pct from pullback_score
        # pullback_score 0-1 range, higher = deeper pullback
        # Approximate: score * 10 = ~pullback%
        pullback_pct = -(trade.pullback_score * 8) if trade.pullback_score else None

        # Estimate trend from ma_score (if > 1.5, trend is bullish)
        trend_bullish = trade.signal_score > 5.0  # Rough proxy

        # Compute EQS
        eq = scorer.score(
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            credit_pct=trade.credit_pct,
            spread_theta=None,  # Not available in outcomes
            credit_bid=trade.net_credit,
            pullback_pct=pullback_pct,
            rsi=trade.rsi_value,
            trend_bullish=trend_bullish,
        )

        trade.eqs_total = eq.eqs_total
        trade.eqs_normalized = eq.eqs_normalized

        # Baseline ranking
        trade.ranking_score_baseline = trade.signal_score

        # EQS-enhanced ranking
        trade.ranking_score_eqs = scorer.apply_eqs_bonus(
            trade.signal_score, eq, max_bonus_pct=0.3
        )

        if iv_rank is not None:
            enriched += 1

    print(f"Enriched {enriched}/{len(trades)} trades with IV data")
    return trades


# =============================================================================
# BACKTEST SIMULATION
# =============================================================================

def simulate_daily_picks(
    trades: List[TradeRecord],
    ranking_key: str,
    picks_per_day: int = PICKS_PER_DAY,
) -> List[TradeRecord]:
    """
    Simulate daily picks by selecting top-N per day.

    Args:
        trades: All trades sorted by entry_date
        ranking_key: 'ranking_score_baseline' or 'ranking_score_eqs'
        picks_per_day: How many picks per day

    Returns:
        Selected trades
    """
    # Group by entry_date
    by_date: Dict[str, List[TradeRecord]] = defaultdict(list)
    for t in trades:
        by_date[t.entry_date].append(t)

    selected = []
    for date_str in sorted(by_date.keys()):
        day_trades = by_date[date_str]
        # Sort by ranking score (descending) and pick top N
        day_trades.sort(key=lambda t: getattr(t, ranking_key), reverse=True)
        selected.extend(day_trades[:picks_per_day])

    return selected


def calculate_metrics(
    trades: List[TradeRecord],
    name: str,
) -> BacktestMetrics:
    """Calculate backtest metrics for a set of trades."""
    if not trades:
        return BacktestMetrics(name=name)

    wins = [t for t in trades if t.was_profitable]
    losses = [t for t in trades if not t.was_profitable]

    # Capital efficiency
    cap_effs = [t.capital_efficiency for t in trades if t.holding_days > 0]
    avg_cap_eff = sum(cap_effs) / len(cap_effs) if cap_effs else 0.0

    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for t in trades:
        if not t.was_profitable:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0

    # Holding days
    holding_days = [t.holding_days for t in trades if t.holding_days > 0]

    return BacktestMetrics(
        name=name,
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        total_pnl=sum(t.pnl for t in trades),
        avg_pnl=sum(t.pnl for t in trades) / len(trades),
        win_rate=len(wins) / len(trades) * 100,
        avg_capital_efficiency=avg_cap_eff,
        avg_profit_winners=sum(t.pnl for t in wins) / len(wins) if wins else 0,
        avg_loss_losers=sum(t.pnl for t in losses) / len(losses) if losses else 0,
        max_consecutive_losses=max_consec,
        avg_holding_days=sum(holding_days) / len(holding_days) if holding_days else 0,
    )


# =============================================================================
# REPORTING
# =============================================================================

def print_comparison(train_a, train_b, test_a, test_b):
    """Print comparison table."""
    print("\n" + "=" * 80)
    print("WALK-FORWARD BACKTEST: EQS Ranking vs. Signal-Score-Only")
    print("=" * 80)

    def print_metrics(label: str, a: BacktestMetrics, b: BacktestMetrics):
        print(f"\n{'─' * 80}")
        print(f"  {label}")
        print(f"{'─' * 80}")
        print(f"{'Metric':<35} {'Baseline':>15} {'EQS-Enhanced':>15} {'Delta':>10}")
        print(f"{'─' * 80}")

        rows = [
            ("Total Trades", f"{a.total_trades:,}", f"{b.total_trades:,}", ""),
            ("Win Rate", f"{a.win_rate:.1f}%", f"{b.win_rate:.1f}%",
             f"{b.win_rate - a.win_rate:+.1f}%"),
            ("Avg P&L / Trade", f"${a.avg_pnl:.2f}", f"${b.avg_pnl:.2f}",
             f"${b.avg_pnl - a.avg_pnl:+.2f}"),
            ("Total P&L", f"${a.total_pnl:,.0f}", f"${b.total_pnl:,.0f}",
             f"${b.total_pnl - a.total_pnl:+,.0f}"),
            ("Avg Capital Efficiency", f"{a.avg_capital_efficiency:.3f}",
             f"{b.avg_capital_efficiency:.3f}",
             f"{(b.avg_capital_efficiency/a.avg_capital_efficiency - 1)*100:+.1f}%" if a.avg_capital_efficiency > 0 else "N/A"),
            ("Avg Profit (Winners)", f"${a.avg_profit_winners:.2f}",
             f"${b.avg_profit_winners:.2f}", ""),
            ("Avg Loss (Losers)", f"${a.avg_loss_losers:.2f}",
             f"${b.avg_loss_losers:.2f}", ""),
            ("Max Consecutive Losses", f"{a.max_consecutive_losses}",
             f"{b.max_consecutive_losses}", ""),
            ("Avg Holding Days", f"{a.avg_holding_days:.1f}",
             f"{b.avg_holding_days:.1f}", ""),
        ]

        for label_r, val_a, val_b, delta in rows:
            print(f"  {label_r:<33} {val_a:>15} {val_b:>15} {delta:>10}")

    print_metrics("TRAIN PERIOD (2021-01 to 2023-12)", train_a, train_b)
    print_metrics("TEST PERIOD  (2024-01 to 2025-10)", test_a, test_b)

    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")

    wr_delta_train = train_b.win_rate - train_a.win_rate
    wr_delta_test = test_b.win_rate - test_a.win_rate
    ce_delta_train = ((train_b.avg_capital_efficiency / train_a.avg_capital_efficiency - 1) * 100
                      if train_a.avg_capital_efficiency > 0 else 0)
    ce_delta_test = ((test_b.avg_capital_efficiency / test_a.avg_capital_efficiency - 1) * 100
                     if test_a.avg_capital_efficiency > 0 else 0)

    print(f"  Win Rate Change:       Train {wr_delta_train:+.1f}%  |  Test {wr_delta_test:+.1f}%")
    print(f"  Cap. Efficiency Change: Train {ce_delta_train:+.1f}%  |  Test {ce_delta_test:+.1f}%")

    # Acceptance criteria
    print(f"\n  Acceptance Criteria:")
    wr_pass = test_b.win_rate >= test_a.win_rate - 0.5  # At least same (±0.5%)
    ce_pass = ce_delta_test > 0  # Measurably better
    overfit = abs(ce_delta_train - ce_delta_test) < 20  # Similar improvement

    print(f"  {'PASS' if wr_pass else 'FAIL'} Win Rate >= Baseline (Test): "
          f"{test_b.win_rate:.1f}% vs {test_a.win_rate:.1f}%")
    print(f"  {'PASS' if ce_pass else 'FAIL'} Capital Efficiency improved (Test): "
          f"{ce_delta_test:+.1f}%")
    print(f"  {'PASS' if overfit else 'WARN'} No overfitting (Train vs Test similar): "
          f"Train {ce_delta_train:+.1f}% vs Test {ce_delta_test:+.1f}%")

    print(f"\n{'=' * 80}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("Loading trades from outcomes.db...")
    trades = load_trades()
    print(f"Loaded {len(trades)} trades")

    print("\nLoading IV data from trades.db...")
    iv_data = load_iv_data()

    print("\nComputing EQS for all trades...")
    trades = compute_eqs_for_trades(trades, iv_data)

    # Split Train/Test
    train = [t for t in trades if t.entry_date < TRAIN_END]
    test = [t for t in trades if t.entry_date >= TEST_START]
    print(f"\nTrain: {len(train)} trades  |  Test: {len(test)} trades")

    # Simulate daily picks
    print(f"\nSimulating daily picks (top {PICKS_PER_DAY}/day)...")

    train_baseline = simulate_daily_picks(train, 'ranking_score_baseline')
    train_eqs = simulate_daily_picks(train, 'ranking_score_eqs')
    test_baseline = simulate_daily_picks(test, 'ranking_score_baseline')
    test_eqs = simulate_daily_picks(test, 'ranking_score_eqs')

    print(f"Train: Baseline {len(train_baseline)} | EQS {len(train_eqs)}")
    print(f"Test:  Baseline {len(test_baseline)} | EQS {len(test_eqs)}")

    # Calculate metrics
    m_train_baseline = calculate_metrics(train_baseline, "Baseline (Train)")
    m_train_eqs = calculate_metrics(train_eqs, "EQS-Enhanced (Train)")
    m_test_baseline = calculate_metrics(test_baseline, "Baseline (Test)")
    m_test_eqs = calculate_metrics(test_eqs, "EQS-Enhanced (Test)")

    # Print comparison
    print_comparison(m_train_baseline, m_train_eqs, m_test_baseline, m_test_eqs)

    # EQS distribution
    eqs_values = [t.eqs_total for t in trades]
    print(f"\n  EQS Distribution:")
    print(f"    Min: {min(eqs_values):.1f}  Max: {max(eqs_values):.1f}  "
          f"Mean: {sum(eqs_values)/len(eqs_values):.1f}  "
          f"Median: {sorted(eqs_values)[len(eqs_values)//2]:.1f}")


if __name__ == "__main__":
    main()
