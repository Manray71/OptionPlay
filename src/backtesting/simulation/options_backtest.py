#!/usr/bin/env python3
"""
Real Options Backtester - Outcome-basiertes Backtesting
========================================================
Extracted from real_options_backtester.py (Phase 6c)

Verwendet ECHTE historische Optionspreise aus der Datenbank für:
1. Realistische Spread-Pricing (keine Black-Scholes Approximation)
2. Echte Bid/Ask-Spreads
3. Tatsächliche P&L-Berechnung bei Expiration

Implementation split into sub-modules:
- simulation/outcome_storage.py - Database functions
- simulation/outcome_analysis.py - ML training functions

Verwendung:
    from src.backtesting.simulation.options_backtest import RealOptionsBacktester

    backtester = RealOptionsBacktester()
    result = backtester.backtest_spread(
        symbol="AAPL",
        entry_date=date(2024, 6, 15),
        short_strike=180,
        long_strike=175,
        expiration=date(2024, 7, 19)
    )
"""

import logging
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ...constants.trading_rules import SPREAD_DTE_MAX, SPREAD_DTE_MIN
from ..core.database import DB_PATH, OptionsDatabase
from ..core.spread_engine import OutcomeCalculator, SpreadFinder
from ..models.outcomes import (
    BacktestTradeRecord,
    OptionQuote,
    SetupFeatures,
    SpreadEntry,
    SpreadOutcome,
    SpreadOutcomeResult,
)
from .outcome_analysis import (
    analyze_winning_patterns,
    calculate_symbol_stability,
    get_blacklisted_symbols,
    get_recommended_symbols,
    get_symbol_stability_score,
    train_component_weights_from_outcomes,
    train_outcome_predictor,
)

# Re-export from sub-modules for backward compatibility
from .outcome_storage import (
    OUTCOME_DB_PATH,
    create_outcome_database,
    get_outcome_statistics,
    get_trades_without_scores,
    load_outcomes_dataframe,
    load_outcomes_for_training,
    load_outcomes_with_scores,
    save_outcomes_to_db,
    update_trade_scores,
)

logger = logging.getLogger(__name__)


# =============================================================================
# MAIN BACKTESTER
# =============================================================================


class RealOptionsBacktester:
    """
    Haupt-Backtesting-Engine mit echten Optionspreisen.

    Verwendet:
    1. Echte historische Optionspreise für Entry
    2. Echte Underlying-Preise für Outcome-Berechnung
    3. Speichert Ergebnisse für ML-Training
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db = OptionsDatabase(db_path)
        self.spread_finder = SpreadFinder(self.db)
        self.outcome_calc = OutcomeCalculator(self.db)

        # Cache für Preisdaten
        self._price_cache: Dict[str, Dict[date, float]] = {}
        self._vix_cache: Dict[date, float] = {}

    def backtest_spread(
        self,
        symbol: str,
        entry_date: date,
        short_strike: float,
        long_strike: float,
        expiration: date,
    ) -> Optional[SpreadOutcomeResult]:
        """
        Backtestet einen spezifischen Spread.

        Args:
            symbol: Ticker
            entry_date: Entry-Datum
            short_strike: Short Put Strike
            long_strike: Long Put Strike
            expiration: Expiration Date

        Returns:
            SpreadOutcomeResult oder None
        """
        # Hole Options-Quotes für Entry
        puts = self.db.get_puts_for_date(
            symbol=symbol,
            quote_date=entry_date,
            dte_min=1,
            dte_max=365,
            moneyness_min=0.5,
            moneyness_max=1.5,
        )

        # Finde die spezifischen Puts
        short_put = next(
            (p for p in puts if p.strike == short_strike and p.expiration == expiration), None
        )
        long_put = next(
            (p for p in puts if p.strike == long_strike and p.expiration == expiration), None
        )

        if not short_put or not long_put:
            return None

        # Erstelle SpreadEntry
        entry = SpreadEntry(
            symbol=symbol,
            entry_date=entry_date,
            expiration=expiration,
            underlying_price=short_put.underlying_price,
            short_strike=short_strike,
            short_bid=short_put.bid,
            short_ask=short_put.ask,
            short_mid=short_put.mid,
            long_strike=long_strike,
            long_bid=long_put.bid,
            long_ask=long_put.ask,
            long_mid=long_put.mid,
            spread_width=short_strike - long_strike,
            gross_credit=short_put.mid - long_put.mid,
            net_credit=short_put.bid - long_put.ask,
            dte=short_put.dte,
            short_otm_pct=short_put.otm_pct,
            long_otm_pct=long_put.otm_pct,
        )

        # Berechne Outcome
        return self.outcome_calc.calculate_outcome(entry)

    def find_and_backtest(
        self,
        symbol: str,
        entry_date: date,
        target_otm_pct: float = 10.0,
        spread_width_pct: float = 5.0,
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
    ) -> Optional[SpreadOutcomeResult]:
        """
        Findet automatisch einen passenden Spread und backtestet ihn.

        Args:
            symbol: Ticker
            entry_date: Entry-Datum
            target_otm_pct: Ziel OTM% für Short Strike
            spread_width_pct: Spread-Breite als % des Aktienkurses
            dte_min/max: DTE-Range

        Returns:
            SpreadOutcomeResult oder None
        """
        # Finde passenden Spread
        entry = self.spread_finder.find_spread(
            symbol=symbol,
            quote_date=entry_date,
            target_short_otm_pct=target_otm_pct,
            spread_width_pct=spread_width_pct,
            dte_min=dte_min,
            dte_max=dte_max,
        )

        if not entry:
            return None

        # Berechne Outcome
        return self.outcome_calc.calculate_outcome(entry)

    def run_full_backtest(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date,
        entry_interval_days: int = 5,  # Alle 5 Tage neuer Entry
        target_otm_pct: float = 10.0,
        spread_width_pct: float = 5.0,
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
        progress_callback: callable = None,
    ) -> List[SpreadOutcomeResult]:
        """
        Führt vollständiges Backtesting über alle Symbole und Zeitraum durch.

        Args:
            symbols: Liste von Tickern
            start_date: Start-Datum
            end_date: End-Datum
            entry_interval_days: Tage zwischen Entries
            target_otm_pct: Ziel OTM%
            spread_width_pct: Spread-Breite als % des Aktienkurses
            dte_min/max: DTE-Range
            progress_callback: Optional callback(symbol, date, result)

        Returns:
            Liste aller SpreadOutcomeResults
        """
        all_results = []

        for symbol in symbols:
            logger.info(f"Backtesting {symbol}...")

            # Hole verfügbare Dates
            available_dates = self.db.get_available_dates(symbol, start_date, end_date)

            # Filtere auf Entry-Intervall
            entry_dates = available_dates[::entry_interval_days]

            for entry_date in entry_dates:
                # Skip wenn zu nah am End-Date (brauchen DTE für Expiration)
                if (end_date - entry_date).days < dte_max:
                    continue

                result = self.find_and_backtest(
                    symbol=symbol,
                    entry_date=entry_date,
                    target_otm_pct=target_otm_pct,
                    spread_width_pct=spread_width_pct,
                    dte_min=dte_min,
                    dte_max=dte_max,
                )

                if result:
                    all_results.append(result)

                    if progress_callback:
                        progress_callback(symbol, entry_date, result)

        logger.info(f"Backtest complete: {len(all_results)} trades")
        return all_results

    def generate_outcome_statistics(
        self,
        results: List[SpreadOutcomeResult],
    ) -> Dict:
        """
        Generiert Statistiken aus Backtest-Ergebnissen.

        Returns:
            Dict mit Win-Rate, Avg P&L, etc.
        """
        if not results:
            return {}

        wins = [r for r in results if r.was_profitable]
        losses = [r for r in results if not r.was_profitable]

        pnls = [r.pnl_per_contract for r in results]

        return {
            "total_trades": len(results),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(results) * 100,
            "total_pnl": sum(pnls),
            "avg_pnl": np.mean(pnls),
            "median_pnl": np.median(pnls),
            "std_pnl": np.std(pnls),
            "max_win": max(pnls) if pnls else 0,
            "max_loss": min(pnls) if pnls else 0,
            "profit_factor": (
                abs(sum(p for p in pnls if p > 0) / sum(p for p in pnls if p < 0))
                if any(p < 0 for p in pnls)
                else float("inf")
            ),
            "outcomes": {
                outcome.value: len([r for r in results if r.outcome == outcome])
                for outcome in SpreadOutcome
            },
        }

    def close(self) -> None:
        """Schließt Datenbankverbindung"""
        self.db.close()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def quick_backtest(
    symbol: str,
    entry_date: date,
    target_otm_pct: float = 10.0,
    spread_width_pct: float = 5.0,
) -> Optional[SpreadOutcomeResult]:
    """
    Schneller Backtest für einen einzelnen Trade.

    Args:
        spread_width_pct: Spread-Breite als % des Aktienkurses (z.B. 5% = $10 bei $200)

    Usage:
        result = quick_backtest("AAPL", date(2024, 6, 15))
        if result:
            print(f"P&L: ${result.pnl_per_contract:.2f}")
    """
    backtester = RealOptionsBacktester()
    try:
        return backtester.find_and_backtest(
            symbol=symbol,
            entry_date=entry_date,
            target_otm_pct=target_otm_pct,
            spread_width_pct=spread_width_pct,
        )
    finally:
        backtester.close()


def run_symbol_backtest(
    symbol: str,
    start_date: date,
    end_date: date,
    **kwargs,
) -> Dict:
    """
    Führt Backtest für ein einzelnes Symbol durch und gibt Statistiken zurück.

    Usage:
        stats = run_symbol_backtest("AAPL", date(2023, 1, 1), date(2024, 1, 1))
        print(f"Win Rate: {stats['win_rate']:.1f}%")
    """
    backtester = RealOptionsBacktester()
    try:
        results = backtester.run_full_backtest(
            symbols=[symbol],
            start_date=start_date,
            end_date=end_date,
            **kwargs,
        )
        return backtester.generate_outcome_statistics(results)
    finally:
        backtester.close()


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Real Options Backtester")
    parser.add_argument("--symbol", default="AAPL", help="Symbol to backtest")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2024-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--otm", type=float, default=10.0, help="Target OTM%")
    parser.add_argument("--width", type=float, default=5.0, help="Spread width")

    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"\nBacktesting {args.symbol} from {start} to {end}")
    print(f"Target OTM: {args.otm}%, Spread Width: ${args.width}")
    print("-" * 50)

    stats = run_symbol_backtest(
        args.symbol,
        start,
        end,
        target_otm_pct=args.otm,
        spread_width=args.width,
    )

    if stats:
        print(f"\nResults for {args.symbol}:")
        print(f"  Total Trades: {stats['total_trades']}")
        print(f"  Win Rate: {stats['win_rate']:.1f}%")
        print(f"  Total P&L: ${stats['total_pnl']:.2f}")
        print(f"  Avg P&L: ${stats['avg_pnl']:.2f}")
        print(f"  Profit Factor: {stats['profit_factor']:.2f}")
        print(f"\nOutcomes:")
        for outcome, count in stats["outcomes"].items():
            print(f"  {outcome}: {count}")
    else:
        print("No trades found")
