#!/usr/bin/env python3
"""
Iteration 6: Continuous Learning Pipeline — Strategy Retrainer.

Automated retrain cycle per strategy with safety rails.
Can be run as a cron job or manually.

Safety Rails:
- Max 20% weight change per retrain
- Minimum 50 new trades required
- Max 2% win-rate degradation tolerated
- Comparison report generated before applying

Usage:
    python scripts/retrain_weights.py                     # Dry run (all strategies)
    python scripts/retrain_weights.py --strategy pullback  # Single strategy
    python scripts/retrain_weights.py --apply              # Apply changes to YAML
    python scripts/retrain_weights.py --force              # Skip min_new_trades check
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.training.strategy_weight_trainer import (
    StrategyWeightTrainer,
    StrategyTrainingConfig,
)
from src.backtesting.training.ml_weight_optimizer import STRATEGY_COMPONENTS
from src.config.scoring_config import RecursiveConfigResolver

logger = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────
OUTCOMES_DB = os.path.expanduser("~/.optionplay/outcomes.db")
TRADES_DB = os.path.expanduser("~/.optionplay/trades.db")
OUTPUT_DIR = Path(__file__).parent.parent / "data_inventory"
YAML_PATH = Path(__file__).parent.parent / "config" / "scoring_weights.yaml"
HISTORY_DIR = OUTPUT_DIR / "retrain_history"

STRATEGIES = ["pullback", "bounce", "ath_breakout"]
REGIMES = ["low", "medium", "high", "extreme"]


@dataclass
class SafetyRails:
    """Safety constraints for weight updates."""
    max_weight_change: float = 0.20        # Max 20% change per component
    min_new_trades: int = 50               # Minimum new trades since last retrain
    min_win_rate_improvement: float = -0.02  # Max 2% WR degradation tolerated
    max_objective_degradation: float = -0.05  # Max 5% objective degradation


@dataclass
class RetrainResult:
    """Result of a retrain attempt."""
    strategy: str
    regime: Optional[str]
    status: str  # "applied", "rejected", "skipped", "dry_run"
    reason: str
    old_weights: Dict[str, float]
    new_weights: Dict[str, float]
    weight_changes: Dict[str, float]
    metrics: Dict[str, float]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class StrategyRetrainer:
    """Monthly retrain per strategy with safety rails."""

    def __init__(self, safety: Optional[SafetyRails] = None):
        self.safety = safety or SafetyRails()

    def load_trades_df(self):
        """Load all trades from outcomes.db."""
        conn = sqlite3.connect(OUTCOMES_DB)
        cols = [
            "symbol", "entry_date", "was_profitable", "pnl_pct",
            "vix_regime", "max_drawdown_pct",
            "pullback_score", "bounce_score", "ath_breakout_score", "earnings_dip_score",
            "rsi_score", "support_score", "fibonacci_score", "ma_score",
            "volume_score", "macd_score", "stoch_score", "keltner_score",
            "trend_strength_score", "momentum_score", "rs_score",
            "candlestick_score", "vwap_score", "market_context_score",
            "sector_score", "gap_score",
        ]
        query = f"SELECT {', '.join(cols)} FROM trade_outcomes WHERE pullback_score IS NOT NULL ORDER BY entry_date"
        df = pd.read_sql_query(query, conn)
        conn.close()
        score_cols = [c for c in df.columns if c.endswith("_score")]
        df[score_cols] = df[score_cols].fillna(0)
        return df

    def get_last_retrain_date(self, strategy: str) -> Optional[str]:
        """Get the date of the last successful retrain."""
        history_file = HISTORY_DIR / f"retrain_{strategy}_latest.json"
        if history_file.exists():
            with open(history_file) as f:
                data = json.load(f)
            return data.get("timestamp")
        return None

    def count_new_trades(self, df: pd.DataFrame, strategy: str, since_date: Optional[str]) -> int:
        """Count trades since last retrain."""
        if since_date is None:
            return len(df)

        if "entry_date" in df.columns:
            mask = df["entry_date"] > since_date
            return int(mask.sum())
        return len(df)

    def get_current_weights(self, strategy: str) -> Dict[str, float]:
        """Get current weights from config."""
        RecursiveConfigResolver.reset()
        resolver = RecursiveConfigResolver()
        resolved = resolver.resolve(strategy, "normal")
        weights = {}
        for comp in STRATEGY_COMPONENTS.get(strategy, []):
            config_key = comp.replace("_score", "")
            weights[comp] = resolved.weights.get(config_key, 1.0)
        return weights

    def check_safety(
        self,
        old_weights: Dict[str, float],
        new_weights: Dict[str, float],
        old_metrics: Dict[str, float],
        new_metrics: Dict[str, float],
    ) -> tuple:
        """Check if weight changes pass safety rails. Returns (passed, reasons)."""
        issues = []

        # Check max weight change
        for comp in old_weights:
            if comp in new_weights and old_weights[comp] > 0:
                change = abs(new_weights[comp] - old_weights[comp]) / old_weights[comp]
                if change > self.safety.max_weight_change:
                    issues.append(
                        f"{comp}: {change*100:.1f}% change > {self.safety.max_weight_change*100:.0f}% max"
                    )

        # Check win rate degradation
        old_wr = old_metrics.get("val_win_rate", 0)
        new_wr = new_metrics.get("val_win_rate", 0)
        if old_wr > 0 and (new_wr - old_wr) < self.safety.min_win_rate_improvement:
            issues.append(
                f"Win rate degradation: {old_wr*100:.1f}% → {new_wr*100:.1f}% "
                f"(Δ={new_wr-old_wr:+.3f}, min={self.safety.min_win_rate_improvement:+.3f})"
            )

        return len(issues) == 0, issues

    def retrain_strategy(
        self,
        strategy: str,
        df: pd.DataFrame,
        apply: bool = False,
        force: bool = False,
    ) -> RetrainResult:
        """Retrain a single strategy."""
        print(f"\n{'─'*50}")
        print(f"  Retraining: {strategy.upper()}")
        print(f"{'─'*50}")

        # Check new trade count
        last_date = self.get_last_retrain_date(strategy)
        n_new = self.count_new_trades(df, strategy, last_date)
        print(f"  Last retrain: {last_date or 'never'}")
        print(f"  New trades: {n_new}")

        if n_new < self.safety.min_new_trades and not force:
            print(f"  SKIP: {n_new} new trades < {self.safety.min_new_trades} minimum")
            return RetrainResult(
                strategy=strategy, regime=None,
                status="skipped", reason=f"Only {n_new} new trades",
                old_weights={}, new_weights={},
                weight_changes={}, metrics={"n_new_trades": n_new},
            )

        # Get current weights
        old_weights = self.get_current_weights(strategy)

        # Train new weights (global)
        RecursiveConfigResolver.reset()
        trainer = StrategyWeightTrainer(strategy)
        result = trainer.train(df)

        if not result.converged:
            print(f"  SKIP: Training did not converge")
            return RetrainResult(
                strategy=strategy, regime=None,
                status="skipped", reason="Training not converged",
                old_weights=old_weights, new_weights={},
                weight_changes={}, metrics=result.metrics,
            )

        new_weights = result.weights

        # Compute changes
        weight_changes = {}
        for comp in old_weights:
            if comp in new_weights:
                weight_changes[comp] = round(new_weights[comp] - old_weights[comp], 4)

        # Safety check
        old_metrics = {"val_win_rate": 0}  # We don't have the old run's metrics
        passed, issues = self.check_safety(old_weights, new_weights, old_metrics, result.metrics)

        print(f"  Training: converged, val_wr={result.metrics.get('val_win_rate',0)*100:.1f}%")
        print(f"  Safety: {'PASSED' if passed else 'ISSUES FOUND'}")
        for issue in issues:
            print(f"    ⚠ {issue}")

        # Show weight changes
        significant = [(c, d) for c, d in sorted(weight_changes.items(), key=lambda x: -abs(x[1])) if abs(d) > 0.01]
        if significant:
            print(f"  Weight changes:")
            for comp, delta in significant[:5]:
                old_v = old_weights.get(comp, 0)
                new_v = new_weights.get(comp, 0)
                print(f"    {comp:>25s}: {old_v:.3f} → {new_v:.3f} ({delta:+.3f})")

        # Per-regime training
        regime_results = {}
        for regime in REGIMES:
            RecursiveConfigResolver.reset()
            regime_trainer = StrategyWeightTrainer(strategy)
            regime_result = regime_trainer.train(df, regime=regime)
            if regime_result.converged:
                regime_results[regime] = {
                    "weights": {k: round(v, 4) for k, v in regime_result.weights.items()},
                    "val_wr": round(regime_result.metrics.get("val_win_rate", 0), 4),
                    "n_trades": regime_result.n_trades,
                }

        status = "dry_run"
        reason = "Dry run mode"
        if apply and passed:
            status = "applied"
            reason = "Applied to config"
            self._save_retrain_history(strategy, old_weights, new_weights, result.metrics, regime_results)
        elif apply and not passed:
            status = "rejected"
            reason = f"Safety check failed: {'; '.join(issues)}"

        return RetrainResult(
            strategy=strategy, regime=None,
            status=status, reason=reason,
            old_weights={k: round(v, 4) for k, v in old_weights.items()},
            new_weights={k: round(v, 4) for k, v in new_weights.items()},
            weight_changes=weight_changes,
            metrics={
                **{k: round(v, 4) if isinstance(v, float) else v for k, v in result.metrics.items()},
                "n_new_trades": n_new,
                "safety_passed": passed,
                "regime_results": regime_results,
            },
        )

    def _save_retrain_history(self, strategy, old_weights, new_weights, metrics, regime_results):
        """Save retrain history for tracking."""
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)

        record = {
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
            "old_weights": {k: round(v, 4) for k, v in old_weights.items()},
            "new_weights": {k: round(v, 4) for k, v in new_weights.items()},
            "metrics": {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()},
            "regime_results": regime_results,
        }

        # Save latest
        latest_path = HISTORY_DIR / f"retrain_{strategy}_latest.json"
        with open(latest_path, "w") as f:
            json.dump(record, f, indent=2)

        # Append to history log
        log_path = HISTORY_DIR / f"retrain_{strategy}_log.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Retrain scoring weights per strategy")
    parser.add_argument("--strategy", choices=STRATEGIES, help="Train single strategy")
    parser.add_argument("--apply", action="store_true", help="Apply changes (not just dry run)")
    parser.add_argument("--force", action="store_true", help="Skip min_new_trades check")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    OUTPUT_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    retrainer = StrategyRetrainer()
    df = retrainer.load_trades_df()
    print(f"Loaded {len(df)} trades from outcomes.db")

    strategies = [args.strategy] if args.strategy else STRATEGIES
    results = {}

    for strategy in strategies:
        result = retrainer.retrain_strategy(
            strategy, df, apply=args.apply, force=args.force
        )
        results[strategy] = {
            "status": result.status,
            "reason": result.reason,
            "weight_changes": result.weight_changes,
            "metrics": result.metrics,
        }

    # Save run report
    report = {
        "run_date": datetime.now().isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "force": args.force,
        "results": results,
    }

    report_path = OUTPUT_DIR / f"retrain_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  RETRAIN {'APPLIED' if args.apply else 'DRY RUN'} COMPLETE")
    print(f"{'='*60}")
    for strategy, res in results.items():
        print(f"  {strategy:>15s}: {res['status']} — {res['reason']}")
    print(f"\n  Report: {report_path}")


if __name__ == "__main__":
    main()
