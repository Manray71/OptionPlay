#!/usr/bin/env python3
"""
OptionPlay - Full Walk-Forward Training (Multi-Core, Real Option Chains)
=========================================================================

Production-grade Walk-Forward training using:
- Real strategy analyzers (Pullback, Bounce, ATH, EarningsDip, TrendCont)
- Real OHLCV data from price_data table
- REAL option chains from options_prices (19.3M rows) for entry pricing
- Multi-core parallelization (all available CPUs)
- 18/6/6 month rolling windows
- Per-strategy threshold optimization
- VIX regime segmentation

Output:
    ~/.optionplay/models/trained_models.json
    ~/.optionplay/models/component_weights.json

Usage:
    python scripts/full_walkforward_train.py                      # All strategies, all cores
    python scripts/full_walkforward_train.py --strategy pullback   # Single strategy
    python scripts/full_walkforward_train.py --workers 4           # Limit workers
    python scripts/full_walkforward_train.py --dry-run             # Show epoch plan only
    python scripts/full_walkforward_train.py --mode simulated      # Fallback to simulated pricing
"""

import argparse
import json
import logging
import multiprocessing as mp
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

# Project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.backtesting import TradeTracker
from src.backtesting.core import TradeOutcome, ExitReason

logger = logging.getLogger("wf_train")

# ===========================================================================
# CONFIGURATION
# ===========================================================================

STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip", "trend_continuation"]

SCORE_THRESHOLDS = [3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0]

VIX_REGIMES = {
    "normal": (0, 18),
    "elevated": (18, 25),
    "high": (25, 35),
    "extreme": (35, 100),
}

MODELS_DIR = Path.home() / ".optionplay" / "models"
DB_PATH = Path.home() / ".optionplay" / "trades.db"


@dataclass
class WFConfig:
    """Walk-Forward configuration"""
    train_months: int = 18
    test_months: int = 6
    step_months: int = 6
    min_trades_per_epoch: int = 20
    min_valid_epochs: int = 2
    # Backtest params
    initial_capital: float = 100_000.0
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 100.0
    dte_min: int = 60
    dte_max: int = 90
    dte_exit_threshold: int = 14
    min_otm_pct: float = 8.0
    spread_width_pct: float = 5.0
    min_credit_pct: float = 20.0
    slippage_pct: float = 1.0
    commission_per_contract: float = 1.30
    max_position_pct: float = 5.0
    max_total_risk_pct: float = 25.0
    # Mode: "real" (option chains) or "simulated"
    pricing_mode: str = "real"


@dataclass
class EpochResult:
    """Single epoch result for one strategy"""
    epoch_id: int
    strategy: str
    min_score: float
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    # In-sample
    is_trades: int = 0
    is_wins: int = 0
    is_win_rate: float = 0.0
    is_pnl: float = 0.0
    is_real_entries: int = 0  # entries with real option chains
    # Out-of-sample
    oos_trades: int = 0
    oos_wins: int = 0
    oos_win_rate: float = 0.0
    oos_pnl: float = 0.0
    oos_real_entries: int = 0
    # Overfitting
    degradation: float = 0.0
    # Regime breakdown
    regime_trades: Dict[str, int] = field(default_factory=dict)
    regime_wins: Dict[str, int] = field(default_factory=dict)
    regime_pnl: Dict[str, float] = field(default_factory=dict)
    # Component weights (score breakdown aggregates)
    component_correlations: Dict[str, float] = field(default_factory=dict)
    # Sector breakdown (OOS only)
    sector_trades: Dict[str, int] = field(default_factory=dict)
    sector_wins: Dict[str, int] = field(default_factory=dict)
    sector_pnl: Dict[str, float] = field(default_factory=dict)
    is_valid: bool = True
    error: Optional[str] = None


# ===========================================================================
# EPOCH GENERATION
# ===========================================================================

def generate_epochs(
    data_start: date, data_end: date, config: WFConfig
) -> List[Tuple[date, date, date, date]]:
    """Generate (train_start, train_end, test_start, test_end) tuples"""
    from dateutil.relativedelta import relativedelta

    epochs = []
    current_start = data_start

    while True:
        train_end = current_start + relativedelta(months=config.train_months)
        test_start = train_end
        test_end = test_start + relativedelta(months=config.test_months)

        if test_end > data_end:
            break

        epochs.append((current_start, train_end, test_start, test_end))
        current_start += relativedelta(months=config.step_months)

    return epochs


# ===========================================================================
# REAL OPTION CHAIN ENTRY
# ===========================================================================

def _find_real_spread(spread_finder, symbol, entry_date, config):
    """
    Find a real bull-put spread using actual option chain data.
    Returns position dict or None.
    """
    entry = spread_finder.find_spread(
        symbol=symbol,
        quote_date=entry_date,
        target_short_otm_pct=config.min_otm_pct,
        spread_width_pct=config.spread_width_pct,
        dte_min=config.dte_min,
        dte_max=config.dte_max,
    )

    if entry is None:
        return None

    # Calculate position sizing
    max_loss_per = entry.max_loss  # Already per contract from SpreadEntry
    if max_loss_per <= 0:
        return None

    max_risk = config.initial_capital * (config.max_position_pct / 100)
    contracts = max(1, int(max_risk / max_loss_per))
    commission = config.commission_per_contract * contracts * 2

    return {
        "symbol": symbol,
        "entry_date": entry_date,
        "entry_price": entry.underlying_price,
        "short_strike": entry.short_strike,
        "long_strike": entry.long_strike,
        "spread_width": entry.spread_width,
        "net_credit": entry.net_credit,
        "contracts": contracts,
        "max_profit": entry.max_profit * contracts - commission,
        "max_loss": max_loss_per * contracts + commission,
        "dte_at_entry": entry.dte,
        "expiry_date": entry.expiration,
        "is_real": True,
        # Real bid/ask data
        "short_bid": entry.short_bid,
        "short_ask": entry.short_ask,
        "long_bid": entry.long_bid,
        "long_ask": entry.long_ask,
        "short_otm_pct": entry.short_otm_pct,
    }


def _find_simulated_spread(symbol, entry_date, current_price, config):
    """Fallback: simulated spread pricing when no option chain data available."""
    otm = config.min_otm_pct / 100
    short_strike = round(current_price * (1 - otm), 0)
    sw_pct = config.spread_width_pct / 100
    spread_width = max(5.0, round(current_price * sw_pct / 5) * 5)
    long_strike = short_strike - spread_width
    credit_pct = config.min_credit_pct / 100
    net_credit = spread_width * credit_pct * (1 - config.slippage_pct / 100)
    max_loss_per = (spread_width - net_credit) * 100
    if max_loss_per <= 0:
        return None
    max_risk = config.initial_capital * (config.max_position_pct / 100)
    contracts = max(1, int(max_risk / max_loss_per))
    commission = config.commission_per_contract * contracts * 2
    return {
        "symbol": symbol, "entry_date": entry_date, "entry_price": current_price,
        "short_strike": short_strike, "long_strike": long_strike,
        "spread_width": spread_width, "net_credit": net_credit,
        "contracts": contracts, "max_profit": net_credit * 100 * contracts - commission,
        "max_loss": max_loss_per * contracts + commission,
        "dte_at_entry": config.dte_max,
        "expiry_date": entry_date + timedelta(days=config.dte_max),
        "is_real": False,
    }


# ===========================================================================
# ANALYZER INIT
# ===========================================================================

def _init_analyzer(strategy: str):
    """Initialize a strategy analyzer (called per-process)"""
    from src.config.models import PullbackScoringConfig
    from src.analyzers.pullback import PullbackAnalyzer
    from src.analyzers.bounce import BounceAnalyzer, BounceConfig
    from src.analyzers.ath_breakout import ATHBreakoutAnalyzer, ATHBreakoutConfig
    from src.analyzers.earnings_dip import EarningsDipAnalyzer, EarningsDipConfig
    from src.analyzers.trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig

    if strategy == "pullback":
        return PullbackAnalyzer(PullbackScoringConfig())
    elif strategy == "bounce":
        return BounceAnalyzer(BounceConfig())
    elif strategy == "ath_breakout":
        return ATHBreakoutAnalyzer(ATHBreakoutConfig())
    elif strategy == "earnings_dip":
        return EarningsDipAnalyzer(EarningsDipConfig())
    elif strategy == "trend_continuation":
        return TrendContinuationAnalyzer(TrendContinuationConfig())
    raise ValueError(f"Unknown strategy: {strategy}")


# ===========================================================================
# EXIT LOGIC + P&L
# ===========================================================================

def _check_exit(pos, current_date, symbol_data, config):
    """Check if position should exit. Returns (reason, exit_price) or None."""
    price_data = None
    for bar in symbol_data:
        d = bar["date"] if isinstance(bar["date"], date) else date.fromisoformat(bar["date"])
        if d == current_date:
            price_data = bar
            break
    current_price = price_data["close"] if price_data else pos["entry_price"]
    expiry = pos["expiry_date"]
    dte = (expiry - current_date).days

    # Expiration
    if current_date >= expiry:
        return (ExitReason.EXPIRATION, current_price)

    # Short strike breached badly
    if current_price < pos["short_strike"]:
        sv = pos["short_strike"] - current_price
        if sv >= pos["spread_width"] * 0.8:
            return (ExitReason.BREACH_SHORT_STRIKE, current_price)

    # Profit target (time decay estimate)
    days_held = (current_date - pos["entry_date"]).days
    if days_held > 0 and dte > 0:
        tdf = days_held / pos["dte_at_entry"]
        buf = ((current_price - pos["short_strike"]) / pos["short_strike"]) * 100 if pos["short_strike"] > 0 else 0
        est_profit = min((tdf * 50) + (buf * 5), 100)
        if est_profit >= config.profit_target_pct:
            return (ExitReason.PROFIT_TARGET_HIT, current_price)

    # DTE threshold
    if dte <= config.dte_exit_threshold and dte > 0:
        return (ExitReason.DTE_THRESHOLD, current_price)

    # Stop loss
    if current_price < pos["short_strike"]:
        loss = ((pos["short_strike"] - current_price) / pos["net_credit"]) * 100 if pos["net_credit"] > 0 else 0
        if loss >= config.stop_loss_pct:
            return (ExitReason.STOP_LOSS_HIT, current_price)

    return None


def _close_position(pos, exit_date, reason, exit_price, strategy, config):
    """Close position and calculate P&L."""
    short = pos["short_strike"]
    long = pos["long_strike"]
    nc = pos["net_credit"]
    contracts = pos["contracts"]
    commission = config.commission_per_contract * contracts * 2

    if exit_price >= short:
        pnl = pos["max_profit"]
        is_win = True
    elif exit_price <= long:
        pnl = -pos["max_loss"]
        is_win = False
    else:
        iv = short - exit_price
        cost = iv * 100 * contracts
        pnl = (nc * 100 * contracts) - cost - commission
        is_win = pnl > 0

    return {
        "symbol": pos["symbol"], "strategy": strategy,
        "entry_date": pos["entry_date"], "exit_date": exit_date,
        "entry_price": pos["entry_price"], "exit_price": exit_price,
        "score": pos.get("score", 0), "pnl": pnl, "is_win": is_win,
        "hold_days": max(1, (exit_date - pos["entry_date"]).days),
        "score_breakdown": pos.get("score_breakdown"),
        "is_real": pos.get("is_real", False),
        "sector": pos.get("sector", "Unknown"),
    }


# ===========================================================================
# BACKTEST PERIOD
# ===========================================================================

def _get_history_up_to(symbol_data, target_date, lookback=260):
    bars = []
    for bar in symbol_data:
        d = bar["date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        if d < target_date:
            bars.append({**bar, "date": d})
    bars.sort(key=lambda x: x["date"])
    return bars[-lookback:] if len(bars) > lookback else bars


def _get_regime(vix: float) -> str:
    for regime, (low, high) in VIX_REGIMES.items():
        if low <= vix < high:
            return regime
    return "extreme"


def _run_backtest_period(
    analyzer,
    strategy: str,
    historical_data: Dict[str, List[Dict]],
    vix_by_date: Dict[str, float],
    start_date: date,
    end_date: date,
    min_score: float,
    config: WFConfig,
    spread_finder=None,
    sector_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict], Dict[str, List], int]:
    """
    Run backtest for a specific date range using real analyzers.
    Returns (trades_list, component_scores_dict, real_entry_count).
    """
    from src.models.base import SignalType

    trades = []
    component_scores = defaultdict(list)
    open_positions = {}
    current_risk = 0.0
    real_entries = 0

    # Collect all trading days in range
    all_dates = set()
    for sym_data in historical_data.values():
        for bar in sym_data:
            d = bar["date"]
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if start_date <= d <= end_date:
                all_dates.add(d)

    trading_days = sorted(all_dates)
    symbols = list(historical_data.keys())

    for current_date in trading_days:
        # Check exits for open positions
        for symbol in list(open_positions.keys()):
            pos = open_positions[symbol]
            exit_info = _check_exit(pos, current_date, historical_data.get(symbol, []), config)
            if exit_info:
                reason, exit_price = exit_info
                trade = _close_position(pos, current_date, reason, exit_price, strategy, config)
                vix_val = vix_by_date.get(str(current_date), vix_by_date.get(str(pos["entry_date"]), 20))
                trade["vix_regime"] = _get_regime(vix_val)
                trades.append(trade)
                current_risk -= pos.get("max_loss", 0)
                del open_positions[symbol]

        # Check new entries
        for symbol in symbols:
            if symbol in open_positions:
                continue
            if current_risk >= config.initial_capital * (config.max_total_risk_pct / 100):
                break

            symbol_data = historical_data.get(symbol, [])
            history = _get_history_up_to(symbol_data, current_date, 260)
            if len(history) < 60:
                continue

            prices = [bar["close"] for bar in history]
            volumes = [bar["volume"] for bar in history]
            highs = [bar["high"] for bar in history]
            lows = [bar["low"] for bar in history]

            try:
                signal = analyzer.analyze(
                    symbol=symbol, prices=prices, volumes=volumes,
                    highs=highs, lows=lows,
                )
            except Exception:
                continue

            if signal.signal_type != SignalType.LONG:
                continue
            if signal.score < min_score:
                continue

            # Record component scores (only numeric values)
            breakdown = signal.details.get("score_breakdown") if signal.details else None
            if breakdown:
                # Extract individual component scores from nested structure
                components = breakdown.get("components", {})
                if isinstance(components, dict):
                    for comp, comp_data in components.items():
                        score_val = comp_data.get("score") if isinstance(comp_data, dict) else comp_data
                        if isinstance(score_val, (int, float)):
                            component_scores[comp].append({
                                "score": float(score_val), "total_score": signal.score,
                            })
                # Also record top-level numeric fields
                for key in ("total_score", "max_possible"):
                    if key in breakdown and isinstance(breakdown[key], (int, float)):
                        component_scores[key].append({
                            "score": float(breakdown[key]), "total_score": signal.score,
                        })

            # --- ENTRY: Try real option chain first, fallback to simulated ---
            current_price = prices[-1]
            avail_risk = min(
                config.initial_capital * (config.max_position_pct / 100),
                (config.initial_capital * (config.max_total_risk_pct / 100)) - current_risk,
            )

            pos = None
            if spread_finder and config.pricing_mode == "real":
                pos = _find_real_spread(spread_finder, symbol, current_date, config)
                if pos:
                    real_entries += 1

            # Fallback to simulated if real mode found nothing or in simulated mode
            if pos is None:
                pos = _find_simulated_spread(symbol, current_date, current_price, config)

            if pos:
                pos["score"] = signal.score
                pos["score_breakdown"] = breakdown
                pos["sector"] = sector_map.get(symbol, "Unknown") if sector_map else "Unknown"
                open_positions[symbol] = pos
                current_risk += pos.get("max_loss", 0)

    # Close remaining positions at end
    for symbol, pos in open_positions.items():
        symbol_data = historical_data.get(symbol, [])
        last_price = pos["entry_price"]
        for bar in symbol_data:
            d = bar["date"] if isinstance(bar["date"], date) else date.fromisoformat(bar["date"])
            if d == end_date:
                last_price = bar["close"]
                break
        trade = _close_position(pos, end_date, ExitReason.MANUAL, last_price, strategy, config)
        vix_val = vix_by_date.get(str(end_date), 20)
        trade["vix_regime"] = _get_regime(vix_val)
        trades.append(trade)

    return trades, dict(component_scores), real_entries


# ===========================================================================
# PARALLEL WORKER FUNCTION
# ===========================================================================

def worker_run_epoch(args):
    """
    Worker function for multiprocessing.
    Each worker creates its own DB connection for real option chain queries.
    """
    (
        epoch_id, strategy, min_score,
        train_start_str, train_end_str, test_start_str, test_end_str,
        historical_data, vix_by_date, config_dict, sector_map,
    ) = args

    config = WFConfig(**config_dict)
    train_start = date.fromisoformat(train_start_str)
    train_end = date.fromisoformat(train_end_str)
    test_start = date.fromisoformat(test_start_str)
    test_end = date.fromisoformat(test_end_str)

    try:
        analyzer = _init_analyzer(strategy)

        # Create per-worker DB connection for real option chains
        spread_finder = None
        if config.pricing_mode == "real":
            from src.backtesting.core.database import OptionsDatabase
            from src.backtesting.core.spread_engine import SpreadFinder
            db = OptionsDatabase(DB_PATH)
            spread_finder = SpreadFinder(db)

        # In-sample backtest
        is_trades, is_components, is_real = _run_backtest_period(
            analyzer, strategy, historical_data, vix_by_date,
            train_start, train_end, min_score, config,
            spread_finder=spread_finder, sector_map=sector_map,
        )

        # Out-of-sample backtest
        oos_trades, _, oos_real = _run_backtest_period(
            analyzer, strategy, historical_data, vix_by_date,
            test_start, test_end, min_score, config,
            spread_finder=spread_finder, sector_map=sector_map,
        )

        # Clean up DB connection
        if spread_finder:
            spread_finder.db.close()

        is_wins = sum(1 for t in is_trades if t["is_win"])
        oos_wins = sum(1 for t in oos_trades if t["is_win"])
        is_wr = (is_wins / len(is_trades) * 100) if is_trades else 0
        oos_wr = (oos_wins / len(oos_trades) * 100) if oos_trades else 0

        # Regime breakdown (OOS only)
        regime_trades = defaultdict(int)
        regime_wins = defaultdict(int)
        regime_pnl = defaultdict(float)
        for t in oos_trades:
            r = t.get("vix_regime", "normal")
            regime_trades[r] += 1
            if t["is_win"]:
                regime_wins[r] += 1
            regime_pnl[r] += t["pnl"]

        # Sector breakdown (OOS only)
        sector_trades_agg = defaultdict(int)
        sector_wins_agg = defaultdict(int)
        sector_pnl_agg = defaultdict(float)
        for t in oos_trades:
            sec = t.get("sector", "Unknown")
            sector_trades_agg[sec] += 1
            if t["is_win"]:
                sector_wins_agg[sec] += 1
            sector_pnl_agg[sec] += t["pnl"]

        # Component correlations (IS data)
        comp_corr = {}
        for comp, entries in is_components.items():
            if len(entries) >= 20:
                scores = [e["score"] for e in entries]
                total_scores = [e["total_score"] for e in entries]
                if np.std(scores) > 0 and np.std(total_scores) > 0:
                    corr = float(np.corrcoef(scores, total_scores)[0, 1])
                    comp_corr[comp] = round(corr, 4)

        result = EpochResult(
            epoch_id=epoch_id, strategy=strategy, min_score=min_score,
            train_start=train_start_str, train_end=train_end_str,
            test_start=test_start_str, test_end=test_end_str,
            is_trades=len(is_trades), is_wins=is_wins, is_win_rate=is_wr,
            is_pnl=sum(t["pnl"] for t in is_trades),
            is_real_entries=is_real,
            oos_trades=len(oos_trades), oos_wins=oos_wins, oos_win_rate=oos_wr,
            oos_pnl=sum(t["pnl"] for t in oos_trades),
            oos_real_entries=oos_real,
            degradation=is_wr - oos_wr,
            regime_trades=dict(regime_trades), regime_wins=dict(regime_wins),
            regime_pnl=dict(regime_pnl),
            sector_trades=dict(sector_trades_agg), sector_wins=dict(sector_wins_agg),
            sector_pnl=dict(sector_pnl_agg),
            component_correlations=comp_corr,
            is_valid=len(is_trades) >= config.min_trades_per_epoch,
        )
        return result

    except Exception as e:
        import traceback
        return EpochResult(
            epoch_id=epoch_id, strategy=strategy, min_score=min_score,
            train_start=train_start_str, train_end=train_end_str,
            test_start=test_start_str, test_end=test_end_str,
            is_valid=False, error=f"{e}\n{traceback.format_exc()[-200:]}",
        )


# ===========================================================================
# AGGREGATION
# ===========================================================================

def aggregate_strategy_results(
    strategy: str, results: List[EpochResult]
) -> Dict[str, Any]:
    """Aggregate epoch results for one strategy across all score thresholds."""

    by_score = defaultdict(list)
    for r in results:
        if r.is_valid and not r.error:
            by_score[r.min_score].append(r)

    best_score = 5.0
    best_metric = -999
    score_analysis = {}

    for threshold, epoch_results in sorted(by_score.items()):
        valid = [r for r in epoch_results if r.oos_trades >= 10]
        if len(valid) < 2:
            continue

        avg_oos_wr = np.mean([r.oos_win_rate for r in valid])
        total_oos_trades = sum(r.oos_trades for r in valid)
        avg_degrad = np.mean([r.degradation for r in valid])
        total_oos_pnl = sum(r.oos_pnl for r in valid)
        total_real = sum(r.oos_real_entries for r in valid)

        trade_factor = min(total_oos_trades, 500) / 500
        metric = avg_oos_wr * 0.7 + trade_factor * 30

        score_analysis[threshold] = {
            "avg_oos_win_rate": round(avg_oos_wr, 2),
            "total_oos_trades": total_oos_trades,
            "total_oos_pnl": round(total_oos_pnl, 2),
            "avg_degradation": round(avg_degrad, 2),
            "valid_epochs": len(valid),
            "real_option_entries": total_real,
            "composite_metric": round(metric, 2),
        }

        if metric > best_metric:
            best_metric = metric
            best_score = threshold

    best_epochs = [r for r in by_score.get(best_score, []) if r.oos_trades >= 10]

    # Regime analysis
    regime_agg = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for r in best_epochs:
        for regime in VIX_REGIMES:
            regime_agg[regime]["trades"] += r.regime_trades.get(regime, 0)
            regime_agg[regime]["wins"] += r.regime_wins.get(regime, 0)
            regime_agg[regime]["pnl"] += r.regime_pnl.get(regime, 0)

    regime_performance = {}
    regime_adjustments = {}
    for regime, data in regime_agg.items():
        if data["trades"] > 0:
            wr = data["wins"] / data["trades"] * 100
            regime_performance[regime] = {
                "trades": data["trades"], "wins": data["wins"],
                "win_rate": round(wr, 2), "pnl": round(data["pnl"], 2),
            }
            if wr >= 70:
                regime_adjustments[regime] = -0.5
            elif wr < 50:
                regime_adjustments[regime] = 1.0
            else:
                regime_adjustments[regime] = 0.0

    # Component weights
    comp_agg = defaultdict(list)
    for r in best_epochs:
        for comp, corr in r.component_correlations.items():
            comp_agg[comp].append(corr)

    component_weights = {}
    for comp, corrs in comp_agg.items():
        avg_corr = np.mean(corrs)
        component_weights[comp] = round(float(1.0 + avg_corr * 0.5), 4)

    # Validation
    if best_epochs:
        avg_is_wr = np.mean([r.is_win_rate for r in best_epochs])
        avg_oos_wr = np.mean([r.oos_win_rate for r in best_epochs])
        avg_degrad = avg_is_wr - avg_oos_wr
        max_degrad = max((r.degradation for r in best_epochs), default=0)
        total_real = sum(r.oos_real_entries for r in best_epochs)
    else:
        avg_is_wr = avg_oos_wr = avg_degrad = max_degrad = total_real = 0

    severity = "NONE" if avg_degrad < 5 else "MILD" if avg_degrad < 10 else "MODERATE" if avg_degrad < 15 else "SEVERE"

    return {
        "recommended_min_score": best_score,
        "regime_adjustments": regime_adjustments,
        "validation": {
            "total_oos_trades": sum(r.oos_trades for r in best_epochs),
            "avg_is_win_rate": round(avg_is_wr, 2),
            "avg_oos_win_rate": round(avg_oos_wr, 2),
            "avg_degradation": round(avg_degrad, 2),
            "max_degradation": round(max_degrad, 2),
            "overfit_severity": severity,
            "valid_epochs": len(best_epochs),
            "real_option_entries": total_real,
        },
        "regime_performance": regime_performance,
        "component_weights": component_weights,
        "score_analysis": score_analysis,
    }


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Full Walk-Forward Training with real analyzers + real option chains",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--strategy", choices=STRATEGIES + ["all"], default="all")
    parser.add_argument("--workers", type=int, default=0,
                        help="Number of parallel workers (0=all CPUs)")
    parser.add_argument("--train-months", type=int, default=18)
    parser.add_argument("--test-months", type=int, default=6)
    parser.add_argument("--step-months", type=int, default=6)
    parser.add_argument("--mode", choices=["real", "simulated"], default="real",
                        help="Pricing mode: 'real' (option chains) or 'simulated' (formula)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show epoch plan without running")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    num_workers = args.workers or mp.cpu_count()
    strategies = [args.strategy] if args.strategy != "all" else STRATEGIES

    wf_config = WFConfig(
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        pricing_mode=args.mode,
    )
    config_dict = {
        f.name: getattr(wf_config, f.name)
        for f in wf_config.__dataclass_fields__.values()
    }

    print("=" * 70)
    print("  OPTIONPLAY - FULL WALK-FORWARD TRAINING")
    print("=" * 70)
    print(f"  Workers:     {num_workers} CPU cores")
    print(f"  Strategies:  {', '.join(strategies)}")
    print(f"  Walk-Forward: {wf_config.train_months}/{wf_config.test_months}/{wf_config.step_months} months")
    print(f"  Thresholds:  {SCORE_THRESHOLDS}")
    print(f"  Pricing:     {args.mode.upper()} {'(real option chains from DB)' if args.mode == 'real' else '(formula-based)'}")
    print()

    # Load data
    print("  Loading data from price_data...")
    tracker = TradeTracker()
    stats = tracker.get_storage_stats()
    print(f"  Database: {stats['symbols_with_price_data']} symbols, {stats['total_price_bars']:,} bars")

    symbol_info = tracker.list_symbols_with_price_data()
    symbols = [s["symbol"] for s in symbol_info]

    historical_data = {}
    for symbol in symbols:
        pd_obj = tracker.get_price_data(symbol)
        if pd_obj and pd_obj.bars:
            historical_data[symbol] = [
                {
                    "date": bar.date.isoformat() if isinstance(bar.date, date) else bar.date,
                    "open": bar.open, "high": bar.high, "low": bar.low,
                    "close": bar.close, "volume": bar.volume,
                }
                for bar in pd_obj.bars
            ]

    print(f"  Loaded: {len(historical_data)} symbols with OHLCV data")

    # Check options data availability
    if args.mode == "real":
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute("SELECT COUNT(DISTINCT underlying), COUNT(*) FROM options_prices").fetchone()
        conn.close()
        print(f"  Options DB: {row[0]} symbols, {row[1]:,} option quotes")

    # Load VIX
    vix_points = tracker.get_vix_data()
    vix_by_date = {}
    if vix_points:
        for p in vix_points:
            d = p.date.isoformat() if isinstance(p.date, date) else str(p.date)
            vix_by_date[d] = p.value
    print(f"  VIX: {len(vix_by_date)} data points")

    # Load sector mapping
    import sqlite3
    _conn = sqlite3.connect(str(DB_PATH))
    sector_map = {row[0]: row[1] for row in _conn.execute(
        "SELECT symbol, sector FROM symbol_fundamentals WHERE sector IS NOT NULL"
    ).fetchall()}
    _conn.close()
    print(f"  Sectors: {len(sector_map)} symbols mapped to {len(set(sector_map.values()))} sectors")

    # Determine data range
    all_dates = []
    for sym_data in historical_data.values():
        for bar in sym_data:
            all_dates.append(bar["date"])
    all_dates.sort()
    data_start = date.fromisoformat(all_dates[0])
    data_end = date.fromisoformat(all_dates[-1])
    print(f"  Date range: {data_start} to {data_end}")

    # Generate epochs
    epochs = generate_epochs(data_start, data_end, wf_config)
    print(f"\n  Epochs: {len(epochs)}")

    for i, (ts, te, vs, ve) in enumerate(epochs, 1):
        print(f"    Epoch {i}: Train {ts} - {te} | Test {vs} - {ve}")

    total_jobs = len(strategies) * len(epochs) * len(SCORE_THRESHOLDS)
    print(f"\n  Total jobs: {total_jobs} ({len(strategies)} strategies x {len(epochs)} epochs x {len(SCORE_THRESHOLDS)} thresholds)")

    if args.mode == "real":
        print(f"\n  NOTE: Real option chain mode. Each job queries options_prices DB.")
        print(f"  Estimated runtime: 2-6 hours (overnight recommended)")

    if args.dry_run:
        print("\n  DRY RUN - not executing.")
        return

    # Build job list
    print(f"\n  Preparing {total_jobs} jobs...")
    jobs = []
    for strategy in strategies:
        for epoch_id, (ts, te, vs, ve) in enumerate(epochs):
            for min_score in SCORE_THRESHOLDS:
                jobs.append((
                    epoch_id, strategy, min_score,
                    ts.isoformat(), te.isoformat(), vs.isoformat(), ve.isoformat(),
                    historical_data, vix_by_date, config_dict, sector_map,
                ))

    # Execute
    print(f"\n  Running {total_jobs} jobs on {num_workers} cores...")
    print("=" * 70)
    t_start = time.time()

    all_results: List[EpochResult] = []
    completed = 0
    errors = 0

    with mp.Pool(processes=num_workers) as pool:
        for result in pool.imap_unordered(worker_run_epoch, jobs, chunksize=1):
            completed += 1
            if result.error:
                errors += 1
                # Print first 3 errors in detail for debugging
                if errors <= 3:
                    print(f"\n  ERROR [{result.strategy}@{result.min_score} E{result.epoch_id}]: {result.error[:500]}\n")

            if completed % 10 == 0 or completed == total_jobs:
                elapsed = time.time() - t_start
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total_jobs - completed) / rate if rate > 0 else 0
                real_tag = f" R:{result.is_real_entries + result.oos_real_entries}" if result.is_real_entries or result.oos_real_entries else ""
                err_tag = f" [{errors} errors]" if errors else ""
                print(
                    f"  [{completed}/{total_jobs}] "
                    f"{result.strategy}@{result.min_score} E{result.epoch_id} "
                    f"IS:{result.is_trades}t/{result.is_win_rate:.0f}% "
                    f"OOS:{result.oos_trades}t/{result.oos_win_rate:.0f}%{real_tag}"
                    f" [{elapsed:.0f}s, ~{eta:.0f}s left]{err_tag}"
                )
            all_results.append(result)

    elapsed = time.time() - t_start
    print(f"\n  Completed in {elapsed:.1f}s ({elapsed/60:.1f}min)")
    if errors:
        print(f"  Errors: {errors}/{total_jobs}")

    # Aggregate
    print("\n" + "=" * 70)
    print("  AGGREGATING RESULTS...")
    print("=" * 70)

    strategy_results = {}
    component_weights_all = {}

    for strategy in strategies:
        strat_results = [r for r in all_results if r.strategy == strategy]
        agg = aggregate_strategy_results(strategy, strat_results)
        strategy_results[strategy] = agg

        v = agg["validation"]
        print(f"\n  {'=' * 66}")
        print(f"  STRATEGY: {strategy.upper()}")
        print(f"  {'=' * 66}")
        print(f"  Recommended Min Score: {agg['recommended_min_score']}")
        print(f"  Valid Epochs:          {v['valid_epochs']}")
        print(f"  Total OOS Trades:      {v['total_oos_trades']}")
        print(f"  Real Option Entries:   {v.get('real_option_entries', 0)}")
        print(f"  Avg IS Win%:           {v['avg_is_win_rate']:.1f}%")
        print(f"  Avg OOS Win%:          {v['avg_oos_win_rate']:.1f}%")
        print(f"  Avg Degradation:       {v['avg_degradation']:+.1f}%")
        print(f"  Overfit Severity:      {v['overfit_severity']}")

        if agg["regime_performance"]:
            print(f"\n  VIX Regime Performance:")
            print(f"  {'Regime':<12} {'Trades':>8} {'Win%':>8} {'P&L':>14} {'Adj':>6}")
            print(f"  {'-' * 50}")
            for regime in ["normal", "elevated", "high", "extreme"]:
                if regime in agg["regime_performance"]:
                    rp = agg["regime_performance"][regime]
                    adj = agg["regime_adjustments"].get(regime, 0)
                    wr_icon = "+" if rp["win_rate"] >= 60 else "-" if rp["win_rate"] < 50 else "~"
                    print(
                        f"  {regime:<12} {rp['trades']:>8} {wr_icon}{rp['win_rate']:>6.1f}% "
                        f"${rp['pnl']:>+12,.0f} {adj:>+5.1f}"
                    )

        if agg["score_analysis"]:
            print(f"\n  Score Threshold Analysis:")
            print(f"  {'Score':>6} {'OOS WR%':>10} {'OOS Trades':>12} {'OOS P&L':>14} {'Degrad':>8} {'Real':>6}")
            print(f"  {'-' * 58}")
            for sc in sorted(agg["score_analysis"]):
                sa = agg["score_analysis"][sc]
                marker = " <--" if sc == agg["recommended_min_score"] else ""
                print(
                    f"  {sc:>6.1f} {sa['avg_oos_win_rate']:>9.1f}% "
                    f"{sa['total_oos_trades']:>12} "
                    f"${sa['total_oos_pnl']:>+12,.0f} "
                    f"{sa['avg_degradation']:>+7.1f}% "
                    f"{sa.get('real_option_entries', 0):>5}{marker}"
                )

        if agg["component_weights"]:
            component_weights_all[strategy] = {
                "component_weights": agg["component_weights"],
                "validation": {
                    "train_trades": sum(r.is_trades for r in strat_results if r.is_valid and r.min_score == agg["recommended_min_score"]),
                    "test_trades": v["total_oos_trades"],
                    "train_win_rate": v["avg_is_win_rate"],
                    "test_win_rate": v["avg_oos_win_rate"],
                    "degradation": -v["avg_degradation"],
                },
            }

    # Save trained_models.json
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    trained_models = {
        "version": "2.0.0",
        "created_at": datetime.now().isoformat(),
        "training_method": f"full_walkforward_{args.mode}",
        "config": {
            "train_months": wf_config.train_months,
            "test_months": wf_config.test_months,
            "step_months": wf_config.step_months,
            "epochs": len(epochs),
            "thresholds_tested": SCORE_THRESHOLDS,
            "pricing_mode": args.mode,
            "workers": num_workers,
            "duration_seconds": round(elapsed, 1),
        },
        "strategies": {},
    }
    for strategy in strategies:
        agg = strategy_results[strategy]
        trained_models["strategies"][strategy] = {
            "recommended_min_score": agg["recommended_min_score"],
            "regime_adjustments": agg["regime_adjustments"],
            "validation": agg["validation"],
            "regime_performance": agg["regime_performance"],
        }

    models_path = MODELS_DIR / "trained_models.json"
    with open(models_path, "w") as f:
        json.dump(trained_models, f, indent=2, default=str)
    print(f"\n  Saved: {models_path}")

    # Save component_weights.json
    comp_weights = {
        "version": "2.0.0",
        "created_at": datetime.now().isoformat(),
        "training_method": f"full_walkforward_{args.mode}",
        "strategies": component_weights_all,
    }
    weights_path = MODELS_DIR / "component_weights.json"
    with open(weights_path, "w") as f:
        json.dump(comp_weights, f, indent=2, default=str)
    print(f"  Saved: {weights_path}")

    # Save detailed training results
    detailed_results = {
        "version": "2.0.0",
        "created_at": datetime.now().isoformat(),
        "training_method": f"full_walkforward_{args.mode}",
        "config": {
            "train_months": wf_config.train_months,
            "test_months": wf_config.test_months,
            "step_months": wf_config.step_months,
            "epochs": len(epochs),
            "thresholds_tested": SCORE_THRESHOLDS,
            "pricing_mode": args.mode,
            "workers": num_workers,
            "symbols": len(historical_data),
            "duration_seconds": round(elapsed, 1),
        },
        "strategies": {},
    }
    for strategy in strategies:
        agg = strategy_results[strategy]
        # Collect per-epoch results at best score
        best_score = agg["recommended_min_score"]
        epoch_details = []
        for r in all_results:
            if r.strategy == strategy and r.min_score == best_score and r.is_valid and not r.error:
                epoch_details.append({
                    "epoch_id": r.epoch_id,
                    "train_period": f"{r.train_start} to {r.train_end}",
                    "test_period": f"{r.test_start} to {r.test_end}",
                    "is_trades": r.is_trades, "is_win_rate": round(r.is_win_rate, 2),
                    "oos_trades": r.oos_trades, "oos_win_rate": round(r.oos_win_rate, 2),
                    "oos_pnl": round(r.oos_pnl, 2),
                    "degradation": round(r.degradation, 2),
                    "real_entries": r.oos_real_entries,
                    "regime_trades": r.regime_trades,
                    "sector_trades": r.sector_trades,
                    "sector_wins": r.sector_wins,
                })
        detailed_results["strategies"][strategy] = {
            **agg,
            "epoch_details": epoch_details,
        }

    detailed_path = MODELS_DIR / "wf_training_results_detailed.json"
    with open(detailed_path, "w") as f:
        json.dump(detailed_results, f, indent=2, default=str)
    print(f"  Saved: {detailed_path}")

    # Final comparison
    print(f"\n{'=' * 85}")
    print("  STRATEGY COMPARISON")
    print(f"{'=' * 85}")
    print(f"  {'Strategy':<20} {'Score':>6} {'OOS Trades':>10} {'OOS WR%':>10} {'Degrad':>10} {'Real':>6} {'Overfit':>10}")
    print(f"  {'-' * 75}")
    for strategy in strategies:
        agg = strategy_results[strategy]
        v = agg["validation"]
        print(
            f"  {strategy:<20} {agg['recommended_min_score']:>6.1f} "
            f"{v['total_oos_trades']:>10} "
            f"{v['avg_oos_win_rate']:>9.1f}% "
            f"{v['avg_degradation']:>+9.1f}% "
            f"{v.get('real_option_entries', 0):>5} "
            f"{v['overfit_severity']:>10}"
        )

    # ==================================================================
    # SECTOR ROTATION RETRAINING
    # ==================================================================
    print(f"\n{'=' * 85}")
    print("  SECTOR ROTATION ANALYSIS")
    print(f"{'=' * 85}")

    # Aggregate OOS trades by sector × strategy (using best score threshold)
    sector_strategy_perf = defaultdict(lambda: defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0}))
    sector_overall = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})

    for strategy in strategies:
        best_score = strategy_results[strategy]["recommended_min_score"]
        strat_results = [
            r for r in all_results
            if r.strategy == strategy and r.min_score == best_score
            and r.is_valid and not r.error
        ]
        for r in strat_results:
            for sec, count in r.sector_trades.items():
                sector_strategy_perf[sec][strategy]["trades"] += count
                sector_strategy_perf[sec][strategy]["wins"] += r.sector_wins.get(sec, 0)
                sector_strategy_perf[sec][strategy]["pnl"] += r.sector_pnl.get(sec, 0.0)
                sector_overall[sec]["trades"] += count
                sector_overall[sec]["wins"] += r.sector_wins.get(sec, 0)
                sector_overall[sec]["pnl"] += r.sector_pnl.get(sec, 0.0)

    # Compute overall average win rate (for sector_factor baseline)
    total_wins = sum(d["wins"] for d in sector_overall.values())
    total_trades = sum(d["trades"] for d in sector_overall.values())
    avg_overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 50.0

    print(f"\n  Overall: {total_trades} trades, {avg_overall_wr:.1f}% win rate\n")
    print(f"  {'Sector':<25} {'Trades':>7} {'Win%':>7} {'Factor':>8} {'Best Strategy':<20} {'Best WR%':>8}")
    print(f"  {'-' * 80}")

    # Build SECTOR_CLUSTER_WEIGHTS structure
    new_sector_weights = {}
    sector_factors_by_strategy = defaultdict(dict)  # strategy -> sector -> factor

    for sec in sorted(sector_overall.keys()):
        so = sector_overall[sec]
        if so["trades"] < 10:
            continue

        sec_wr = so["wins"] / so["trades"] * 100

        # sector_factor = sector_wr / avg_wr, clamped to 0.5-1.3
        raw_factor = sec_wr / avg_overall_wr if avg_overall_wr > 0 else 1.0
        sector_factor = max(0.5, min(1.3, round(raw_factor, 3)))

        # Find best strategy for this sector
        best_strat = None
        best_strat_wr = 0
        strategy_perf = {}
        for strat, data in sector_strategy_perf[sec].items():
            if data["trades"] >= 5:
                wr = data["wins"] / data["trades"] * 100
                strategy_perf[strat] = {
                    "win_rate": round(wr, 2),
                    "trades": data["trades"],
                }
                if wr > best_strat_wr:
                    best_strat_wr = wr
                    best_strat = strat

                # Compute per-strategy sector_factor
                strat_avg_wr = float(strategy_results[strat]["validation"]["avg_oos_win_rate"])
                if strat_avg_wr > 0:
                    strat_factor = float(max(0.5, min(1.3, round(wr / strat_avg_wr, 3))))
                    sector_factors_by_strategy[strat][sec] = strat_factor

        new_sector_weights[sec] = {
            "win_rate": round(sec_wr, 2),
            "trades": so["trades"],
            "pnl": round(so["pnl"], 2),
            "sector_factor": sector_factor,
            "best_strategy": best_strat or "unknown",
            "best_strategy_win_rate": round(best_strat_wr, 2),
            "strategy_performance": strategy_perf,
        }

        wr_icon = "+" if sec_wr >= avg_overall_wr else "-"
        print(
            f"  {sec:<25} {so['trades']:>7} {wr_icon}{sec_wr:>5.1f}% "
            f"{sector_factor:>7.3f} {best_strat or 'n/a':<20} {best_strat_wr:>7.1f}%"
        )

    # Save SECTOR_CLUSTER_WEIGHTS.json
    scw_path = MODELS_DIR / "SECTOR_CLUSTER_WEIGHTS.json"
    # Preserve cluster_weights from old file if exists
    old_cluster_weights = {}
    if scw_path.exists():
        try:
            with open(scw_path) as f:
                old_data = json.load(f)
            old_cluster_weights = old_data.get("cluster_weights", {})
        except Exception:
            pass

    scw_data = {
        "generated_at": datetime.now().isoformat(),
        "training_method": f"full_walkforward_{args.mode}",
        "overall_win_rate": round(avg_overall_wr, 2),
        "total_trades": total_trades,
        "sector_weights": new_sector_weights,
        "cluster_weights": old_cluster_weights,
    }
    with open(scw_path, "w") as f:
        json.dump(scw_data, f, indent=2, default=str)
    print(f"\n  Saved: {scw_path}")

    # Update scoring_weights.yaml sector_factors
    yaml_path = Path("config/scoring_weights.yaml")
    if yaml_path.exists() and sector_factors_by_strategy:
        try:
            import yaml
            with open(yaml_path) as f:
                yaml_data = yaml.safe_load(f)

            updated_count = 0
            strategies_conf = yaml_data.get("strategies", {})
            for strat, factors in sector_factors_by_strategy.items():
                if strat not in strategies_conf:
                    continue
                strat_conf = strategies_conf[strat]
                sectors_conf = strat_conf.setdefault("sectors", {})
                for sec, factor in factors.items():
                    sec_conf = sectors_conf.setdefault(sec, {})
                    old_factor = sec_conf.get("sector_factor", 1.0)
                    sec_conf["sector_factor"] = round(float(factor), 3)
                    if abs(factor - old_factor) > 0.01:
                        updated_count += 1

            with open(yaml_path, "w") as f:
                yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            print(f"  Updated: {yaml_path} ({updated_count} sector_factors changed)")
        except ImportError:
            print("  WARNING: PyYAML not available, scoring_weights.yaml not updated")
        except Exception as e:
            print(f"  WARNING: Could not update scoring_weights.yaml: {e}")

    # Per-strategy sector breakdown
    for strat in strategies:
        if strat in sector_factors_by_strategy and sector_factors_by_strategy[strat]:
            factors = sector_factors_by_strategy[strat]
            sorted_factors = sorted(factors.items(), key=lambda x: x[1], reverse=True)
            print(f"\n  {strat.upper()} sector_factors:")
            for sec, fac in sorted_factors:
                perf = sector_strategy_perf[sec].get(strat, {})
                trades = perf.get("trades", 0)
                print(f"    {sec:<25} {fac:.3f}  ({trades} trades)")

    print(f"\n{'=' * 85}")
    print(f"  TRAINING COMPLETE ({elapsed:.0f}s / {elapsed/60:.1f}min / {elapsed/3600:.1f}h)")
    print(f"{'=' * 85}")


if __name__ == "__main__":
    main()
