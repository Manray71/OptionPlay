# OptionPlay - Epoch Generation & Execution
# ==========================================
# Extracted from training/regime_trainer.py (Phase 6e)
#
# Generates walk-forward epoch splits and runs individual epochs
# including trade simulation.

import logging
import random
from datetime import date
from typing import Any, Dict, List, Tuple

from ..models import RegimeConfig
from ..models.training_models import (
    RegimeEpochResult,
    RegimeTrainingConfig,
    StrategyPerformance,
)
from .performance import PerformanceAnalyzer

logger = logging.getLogger(__name__)


class EpochRunner:
    """Generates and executes walk-forward training epochs."""

    ALL_STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip", "trend_continuation"]

    def __init__(self, config: RegimeTrainingConfig) -> None:
        self.config = config
        self._performance = PerformanceAnalyzer()

    def generate_regime_epochs(
        self,
        regime_dates: List[date],
    ) -> List[Tuple[List[date], List[date]]]:
        """Generate train/test epoch splits within regime dates"""
        epochs = []

        train_days = self.config.train_months * 21  # ~21 trading days/month
        test_days = self.config.test_months * 21
        step_days = self.config.step_months * 21

        n = len(regime_dates)
        start_idx = 0

        while start_idx + train_days + test_days <= n:
            train_end_idx = start_idx + train_days
            test_end_idx = train_end_idx + test_days

            train_dates = regime_dates[start_idx:train_end_idx]
            test_dates = regime_dates[train_end_idx:test_end_idx]

            if len(train_dates) >= 60 and len(test_dates) >= 20:
                epochs.append((train_dates, test_dates))

            start_idx += step_days

        return epochs

    def run_regime_epoch(
        self,
        epoch_id: int,
        regime_name: str,
        train_dates: List[date],
        test_dates: List[date],
        historical_data: Dict[str, List[Dict]],
        vix_by_date: Dict[date, float],
        regime_config: RegimeConfig,
    ) -> RegimeEpochResult:
        """Run a single Walk-Forward epoch within a regime"""
        # Simulate trades for train period
        train_trades = self.simulate_trades(
            dates=train_dates,
            historical_data=historical_data,
            min_score=regime_config.min_score,
        )

        # Simulate trades for test period
        test_trades = self.simulate_trades(
            dates=test_dates,
            historical_data=historical_data,
            min_score=regime_config.min_score,
        )

        # Check validity
        if len(train_trades) < self.config.min_trades_per_epoch:
            return RegimeEpochResult(
                epoch_id=epoch_id,
                regime=regime_name,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                in_sample_trades=len(train_trades),
                in_sample_win_rate=0,
                in_sample_pnl=0,
                in_sample_sharpe=0,
                out_sample_trades=len(test_trades),
                out_sample_win_rate=0,
                out_sample_pnl=0,
                out_sample_sharpe=0,
                win_rate_degradation=0,
                pnl_degradation=0,
                is_valid=False,
                skip_reason=f"Only {len(train_trades)} training trades",
            )

        if len(test_trades) < 10:
            return RegimeEpochResult(
                epoch_id=epoch_id,
                regime=regime_name,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                in_sample_trades=len(train_trades),
                in_sample_win_rate=0,
                in_sample_pnl=0,
                in_sample_sharpe=0,
                out_sample_trades=len(test_trades),
                out_sample_win_rate=0,
                out_sample_pnl=0,
                out_sample_sharpe=0,
                win_rate_degradation=0,
                pnl_degradation=0,
                is_valid=False,
                skip_reason=f"Only {len(test_trades)} test trades",
            )

        # Calculate metrics
        is_metrics = self._performance.calculate_trade_metrics(train_trades)
        oos_metrics = self._performance.calculate_trade_metrics(test_trades)

        # Calculate strategy performance within this epoch
        strategy_perf = {}
        for strategy in self.ALL_STRATEGIES:
            strategy_train = [t for t in train_trades if t.get("strategy") == strategy]
            if strategy_train:
                s_metrics = self._performance.calculate_trade_metrics(strategy_train)
                strategy_perf[strategy] = StrategyPerformance(
                    strategy=strategy,
                    regime=regime_name,
                    total_trades=len(strategy_train),
                    winning_trades=sum(1 for t in strategy_train if t.get("pnl", 0) > 0),
                    win_rate=s_metrics["win_rate"],
                    avg_pnl=s_metrics["avg_pnl"],
                    sharpe_ratio=s_metrics["sharpe"],
                    profit_factor=s_metrics["profit_factor"],
                    should_enable=s_metrics["win_rate"] >= self.config.strategy_disable_threshold,
                    confidence="medium" if len(strategy_train) >= 20 else "low",
                )

        return RegimeEpochResult(
            epoch_id=epoch_id,
            regime=regime_name,
            train_start=train_dates[0],
            train_end=train_dates[-1],
            test_start=test_dates[0],
            test_end=test_dates[-1],
            in_sample_trades=len(train_trades),
            in_sample_win_rate=is_metrics["win_rate"],
            in_sample_pnl=is_metrics["total_pnl"],
            in_sample_sharpe=is_metrics["sharpe"],
            out_sample_trades=len(test_trades),
            out_sample_win_rate=oos_metrics["win_rate"],
            out_sample_pnl=oos_metrics["total_pnl"],
            out_sample_sharpe=oos_metrics["sharpe"],
            win_rate_degradation=is_metrics["win_rate"] - oos_metrics["win_rate"],
            pnl_degradation=is_metrics["total_pnl"] - oos_metrics["total_pnl"],
            is_valid=True,
            strategy_performance=strategy_perf,
        )

    def simulate_trades(
        self,
        dates: List[date],
        historical_data: Dict[str, List[Dict]],
        min_score: float,
    ) -> List[Dict]:
        """
        Simulate trade outcomes for given dates.

        This is a simplified simulation that generates trade-like outcomes
        for training purposes. In production, actual analyzer output would
        be used.
        """
        trades = []
        symbols = list(historical_data.keys())

        # Sample dates for trade entry (not every day)
        trade_dates = random.sample(dates, min(len(dates) // 3, 50))

        for d in sorted(trade_dates):
            # Pick random symbols
            selected_symbols = random.sample(symbols, min(5, len(symbols)))

            for symbol in selected_symbols:
                bars = historical_data.get(symbol, [])
                bar = None
                for b in bars:
                    bd = b.get("date")
                    if isinstance(bd, str):
                        bd = date.fromisoformat(bd)
                    if bd == d:
                        bar = b
                        break

                if not bar:
                    continue

                # Simulate score and outcome
                # In real implementation, this would use actual analyzer
                score = random.uniform(3, 12)
                if score < min_score:
                    continue

                # Higher scores = higher win probability (simplified)
                win_prob = 0.40 + (score - 5) * 0.05  # 40% base + 5% per point above 5
                win_prob = min(0.75, max(0.30, win_prob))

                is_winner = random.random() < win_prob

                if is_winner:
                    pnl = random.uniform(50, 200)  # Simulated profit
                else:
                    pnl = random.uniform(-300, -50)  # Simulated loss

                strategy = random.choice(self.ALL_STRATEGIES)

                trades.append(
                    {
                        "symbol": symbol,
                        "date": d,
                        "score": score,
                        "pnl": pnl,
                        "is_winner": is_winner,
                        "strategy": strategy,
                    }
                )

        return trades
