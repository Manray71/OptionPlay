# OptionPlay - Performance Analysis for Training
# ===============================================
# Extracted from training/regime_trainer.py (Phase 6e)
#
# Calculates trade metrics, analyzes strategy performance,
# and classifies overfitting severity.

import logging
import statistics
from typing import Dict, List

from ..models.training_models import (
    RegimeTrainingConfig,
    StrategyPerformance,
)

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """Analyzes trading performance metrics for regime training."""

    OVERFIT_THRESHOLDS = {
        "none": 5.0,
        "mild": 10.0,
        "moderate": 15.0,
        "severe": float("inf"),
    }

    def calculate_trade_metrics(self, trades: List[Dict]) -> Dict[str, float]:
        """Calculate performance metrics from trades"""
        if not trades:
            return {
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0,
                "sharpe": 0,
                "profit_factor": 0,
            }

        winners = [t for t in trades if t.get("pnl", 0) > 0]
        losers = [t for t in trades if t.get("pnl", 0) < 0]
        pnls = [t.get("pnl", 0) for t in trades]

        win_rate = len(winners) / len(trades) * 100 if trades else 0
        total_pnl = sum(pnls)
        avg_pnl = statistics.mean(pnls) if pnls else 0

        # Sharpe (simplified)
        if len(pnls) > 1:
            std = statistics.stdev(pnls)
            sharpe = (avg_pnl / std) * (252**0.5) if std > 0 else 0
        else:
            sharpe = 0

        # Profit factor
        gross_profit = sum(t.get("pnl", 0) for t in winners)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        return {
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "sharpe": sharpe,
            "profit_factor": profit_factor,
        }

    def analyze_strategy_performance(
        self,
        strategy_trades: Dict[str, List[Dict]],
        regime_name: str,
        config: RegimeTrainingConfig,
    ) -> Dict[str, StrategyPerformance]:
        """Analyze aggregate performance per strategy"""
        results = {}

        for strategy, epoch_data in strategy_trades.items():
            if not epoch_data:
                continue

            # Aggregate across epochs
            total_trades = sum(e["trades"] for e in epoch_data)
            avg_win_rate = statistics.mean(e["win_rate"] for e in epoch_data) if epoch_data else 0

            should_enable = avg_win_rate >= config.strategy_disable_threshold

            # Confidence based on sample size
            if total_trades >= 100:
                confidence = "high"
            elif total_trades >= 50:
                confidence = "medium"
            else:
                confidence = "low"

            results[strategy] = StrategyPerformance(
                strategy=strategy,
                regime=regime_name,
                total_trades=total_trades,
                winning_trades=int(total_trades * avg_win_rate / 100),
                win_rate=avg_win_rate,
                avg_pnl=0,  # Not tracked at this level
                sharpe_ratio=0,
                profit_factor=0,
                should_enable=should_enable,
                confidence=confidence,
            )

        return results

    def classify_overfit(self, degradation: float) -> str:
        """Classify overfitting severity"""
        abs_deg = abs(degradation)

        if abs_deg < self.OVERFIT_THRESHOLDS["none"]:
            return "none"
        elif abs_deg < self.OVERFIT_THRESHOLDS["mild"]:
            return "mild"
        elif abs_deg < self.OVERFIT_THRESHOLDS["moderate"]:
            return "moderate"
        else:
            return "severe"
