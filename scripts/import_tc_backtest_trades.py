#!/usr/bin/env python3
"""
Import Trend Continuation backtest trades into outcomes.db.

Runs the TrendContinuationAnalyzer on historical data (from trades.db),
simulates Bull-Put-Spread entries and exits, then inserts the resulting
trades into outcomes.db with full component scores.

Usage:
    python scripts/import_tc_backtest_trades.py
    python scripts/import_tc_backtest_trades.py --dry-run    # just count, don't insert
"""

import argparse
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv()

from src.analyzers.trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig
from src.models.base import SignalType

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TRADES_DB = Path.home() / ".optionplay" / "trades.db"
OUTCOMES_DB = Path.home() / ".optionplay" / "outcomes.db"

# Trade simulation parameters (same as full_strategy_backtest.py)
MIN_SCORE = 5.0
OTM_PCT = 5.0  # 5% OTM for short strike
SPREAD_WIDTH_PCT = 3.0
MIN_CREDIT_PCT = 30.0
DTE = 45
PROFIT_TARGET_PCT = 50.0
STOP_LOSS_PCT = 100.0
MIN_BARS = 220


@dataclass
class SimulatedTrade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    short_strike: float
    long_strike: float
    spread_width: float
    net_credit: float
    dte_at_entry: int
    short_otm_pct: float
    outcome: str
    pnl: float
    pnl_pct: float
    was_profitable: int
    vix_at_entry: Optional[float]
    vix_regime: Optional[str]
    hold_days: int
    min_price: float
    max_price: float
    max_drawdown_pct: float
    # TC scores
    tc_score: float
    tc_sma_alignment: float
    tc_stability: float
    tc_buffer: float
    tc_momentum: float
    tc_volatility: float


def load_symbols() -> List[str]:
    """Load all symbols from trades.db."""
    conn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT underlying FROM options_prices ORDER BY underlying")
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    return symbols


def load_price_data(symbol: str) -> List[Tuple[str, float]]:
    """Load distinct closing prices for a symbol."""
    conn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT quote_date, underlying_price
        FROM options_prices
        WHERE underlying = ?
        ORDER BY quote_date
    """,
        (symbol,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def load_vix_data() -> Dict[str, float]:
    """Load all VIX data."""
    conn = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute("SELECT date, value FROM vix_data ORDER BY date")
    vix = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return vix


def get_vix_regime(vix: float) -> str:
    if vix < 15:
        return "low"
    elif vix < 20:
        return "medium"
    elif vix < 30:
        return "high"
    else:
        return "extreme"


def get_vix_for_date(vix_data: Dict[str, float], target_date: str) -> Optional[float]:
    if target_date in vix_data:
        return vix_data[target_date]
    # Find closest prior date
    for i in range(1, 8):
        d = (date.fromisoformat(target_date) - timedelta(days=i)).isoformat()
        if d in vix_data:
            return vix_data[d]
    return None


def simulate_trade(
    symbol: str,
    entry_date: str,
    entry_price: float,
    price_dates: List[str],
    price_values: List[float],
    entry_idx: int,
    vix: Optional[float],
    signal_score: float,
    components: Dict[str, float],
) -> Optional[SimulatedTrade]:
    """Simulate a Bull-Put-Spread trade from entry to exit."""
    short_strike = round(entry_price * (1 - OTM_PCT / 100), 0)
    spread_width = max(5.0, round(entry_price * SPREAD_WIDTH_PCT / 100 / 5) * 5)
    long_strike = short_strike - spread_width
    net_credit = spread_width * MIN_CREDIT_PCT / 100
    short_otm_pct = ((entry_price - short_strike) / entry_price) * 100

    expiry_date = (date.fromisoformat(entry_date) + timedelta(days=DTE)).isoformat()

    min_price = entry_price
    max_price = entry_price
    max_drawdown_pct = 0.0

    exit_date = expiry_date
    exit_price = entry_price

    # Walk forward from entry to find exit
    for i in range(entry_idx + 1, len(price_dates)):
        current_date_str = price_dates[i]
        current_price = price_values[i]

        min_price = min(min_price, current_price)
        max_price = max(max_price, current_price)

        # Calculate drawdown from entry
        if entry_price > 0:
            dd = ((entry_price - min_price) / entry_price) * 100
            max_drawdown_pct = max(max_drawdown_pct, dd)

        days_held = (date.fromisoformat(current_date_str) - date.fromisoformat(entry_date)).days

        # Expiration
        if current_date_str >= expiry_date:
            exit_date = current_date_str
            exit_price = current_price
            break

        # Short strike breach → stop loss
        if current_price < short_strike:
            spread_value = short_strike - current_price
            if spread_value >= spread_width * 0.8:
                exit_date = current_date_str
                exit_price = current_price
                break

        # Profit target (time decay approximation)
        if days_held > 0:
            time_decay = days_held / DTE
            price_buffer = (
                ((current_price - short_strike) / short_strike) * 100 if short_strike > 0 else 0
            )
            est_profit_pct = min((time_decay * 50) + (price_buffer * 5), 100)
            if est_profit_pct >= PROFIT_TARGET_PCT:
                exit_date = current_date_str
                exit_price = current_price
                break
    else:
        # If we exhaust data, use last available price
        if len(price_dates) > entry_idx + 1:
            exit_date = price_dates[-1]
            exit_price = price_values[-1]

    # Calculate outcome
    if exit_price >= short_strike:
        pnl = net_credit * 100  # Full credit kept
        outcome = "max_profit"
    elif exit_price <= long_strike:
        pnl = -(spread_width - net_credit) * 100  # Max loss
        outcome = "max_loss"
    else:
        intrinsic = short_strike - exit_price
        pnl = (net_credit - intrinsic) * 100
        outcome = "partial_profit" if pnl > 0 else "partial_loss"

    pnl_pct = (pnl / (spread_width * 100)) * 100 if spread_width > 0 else 0
    was_profitable = 1 if pnl > 0 else 0

    hold_days = max(1, (date.fromisoformat(exit_date) - date.fromisoformat(entry_date)).days)

    regime = get_vix_regime(vix) if vix else None

    return SimulatedTrade(
        symbol=symbol,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_price=entry_price,
        exit_price=exit_price,
        short_strike=short_strike,
        long_strike=long_strike,
        spread_width=spread_width,
        net_credit=net_credit,
        dte_at_entry=DTE,
        short_otm_pct=round(short_otm_pct, 2),
        outcome=outcome,
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        was_profitable=was_profitable,
        vix_at_entry=vix,
        vix_regime=regime,
        hold_days=hold_days,
        min_price=min_price,
        max_price=max_price,
        max_drawdown_pct=round(max_drawdown_pct, 2),
        tc_score=signal_score,
        tc_sma_alignment=components.get("sma_alignment", 0.0),
        tc_stability=components.get("trend_stability", 0.0),
        tc_buffer=components.get("trend_buffer", 0.0),
        tc_momentum=components.get("momentum_health", 0.0),
        tc_volatility=components.get("volatility", 0.0),
    )


def main():
    parser = argparse.ArgumentParser(description="Import TC backtest trades into outcomes.db")
    parser.add_argument("--dry-run", action="store_true", help="Don't insert, just count")
    args = parser.parse_args()

    analyzer = TrendContinuationAnalyzer(TrendContinuationConfig())
    symbols = load_symbols()
    vix_data = load_vix_data()

    logger.info(f"Symbols: {len(symbols)}, VIX points: {len(vix_data)}")

    all_trades: List[SimulatedTrade] = []
    open_positions = set()  # Track symbols with open positions

    # Process each symbol
    for sym_idx, symbol in enumerate(symbols):
        if sym_idx % 50 == 0:
            logger.info(f"  [{sym_idx}/{len(symbols)}] {symbol}")

        price_rows = load_price_data(symbol)
        if len(price_rows) < MIN_BARS:
            continue

        price_dates = [r[0] for r in price_rows]
        price_values = [r[1] for r in price_rows]

        # Scan each date for entry signals
        cooldown_until = None  # No re-entry for same symbol until cooldown

        for idx in range(MIN_BARS, len(price_rows)):
            current_date = price_dates[idx]

            # Cooldown: skip if we recently had a position
            if cooldown_until and current_date < cooldown_until:
                continue

            closes = price_values[: idx + 1]
            highs = [p * 1.005 for p in closes]
            lows = [p * 0.995 for p in closes]
            volumes = [1_000_000] * len(closes)

            vix = get_vix_for_date(vix_data, current_date)

            try:
                signal = analyzer.analyze(
                    symbol=symbol,
                    prices=closes,
                    volumes=volumes,
                    highs=highs,
                    lows=lows,
                    vix=vix,
                )
            except Exception:
                continue

            if signal.signal_type != SignalType.LONG or signal.score < MIN_SCORE:
                continue

            # Extract components
            components = {}
            if hasattr(signal, "details") and signal.details:
                components = signal.details.get("components", {})

            # Simulate trade
            trade = simulate_trade(
                symbol=symbol,
                entry_date=current_date,
                entry_price=closes[-1],
                price_dates=price_dates,
                price_values=price_values,
                entry_idx=idx,
                vix=vix,
                signal_score=signal.score,
                components=components,
            )

            if trade:
                all_trades.append(trade)
                # Set cooldown: no new entry until exit_date + 1 day
                cooldown_until = (
                    date.fromisoformat(trade.exit_date) + timedelta(days=1)
                ).isoformat()

    logger.info(f"\n{'='*60}")
    logger.info(f"Total TC trades: {len(all_trades)}")

    # Stats
    if all_trades:
        wins = sum(1 for t in all_trades if t.was_profitable)
        logger.info(f"Win rate: {wins/len(all_trades)*100:.1f}%")

        by_outcome = {}
        for t in all_trades:
            by_outcome[t.outcome] = by_outcome.get(t.outcome, 0) + 1
        for outcome, count in sorted(by_outcome.items()):
            logger.info(f"  {outcome}: {count}")

        by_regime = {}
        for t in all_trades:
            r = t.vix_regime or "unknown"
            by_regime.setdefault(r, [0, 0])
            by_regime[r][0] += 1
            if t.was_profitable:
                by_regime[r][1] += 1
        logger.info("Regime breakdown:")
        for regime in sorted(by_regime):
            total, w = by_regime[regime]
            logger.info(f"  {regime}: {total} trades, {w/total*100:.1f}% WR")

    if args.dry_run:
        logger.info("DRY RUN — not inserting into outcomes.db")
        return

    if not all_trades:
        logger.warning("No trades to insert!")
        return

    # Insert into outcomes.db
    conn = sqlite3.connect(str(OUTCOMES_DB))
    cursor = conn.cursor()

    inserted = 0
    skipped = 0
    for trade in all_trades:
        # Check for duplicate (same symbol + entry_date)
        cursor.execute(
            "SELECT COUNT(*) FROM trade_outcomes WHERE symbol = ? AND entry_date = ? AND trend_continuation_score >= 5.0",
            (trade.symbol, trade.entry_date),
        )
        if cursor.fetchone()[0] > 0:
            skipped += 1
            continue

        expiration = (
            date.fromisoformat(trade.entry_date) + timedelta(days=trade.dte_at_entry)
        ).isoformat()

        cursor.execute(
            """
            INSERT INTO trade_outcomes (
                symbol, entry_date, exit_date, expiration,
                entry_price, short_strike, long_strike, spread_width,
                net_credit, dte_at_entry, short_otm_pct, exit_price,
                outcome, pnl, pnl_pct, was_profitable,
                min_price, max_price, max_drawdown_pct,
                vix_at_entry, vix_regime,
                trend_continuation_score,
                tc_sma_alignment_score, tc_stability_score, tc_buffer_score,
                tc_momentum_score, tc_volatility_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                trade.symbol,
                trade.entry_date,
                trade.exit_date,
                expiration,
                trade.entry_price,
                trade.short_strike,
                trade.long_strike,
                trade.spread_width,
                trade.net_credit,
                trade.dte_at_entry,
                trade.short_otm_pct,
                trade.exit_price,
                trade.outcome,
                trade.pnl,
                trade.pnl_pct,
                trade.was_profitable,
                trade.min_price,
                trade.max_price,
                trade.max_drawdown_pct,
                trade.vix_at_entry,
                trade.vix_regime,
                trade.tc_score,
                trade.tc_sma_alignment,
                trade.tc_stability,
                trade.tc_buffer,
                trade.tc_momentum,
                trade.tc_volatility,
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()
    logger.info(f"\nInserted: {inserted}, Skipped (duplicates): {skipped}")


if __name__ == "__main__":
    main()
