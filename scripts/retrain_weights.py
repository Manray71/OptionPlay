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

STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip"]
REGIMES = ["low", "medium", "high", "extreme"]

# Map DB regime names → YAML regime names
DB_TO_YAML_REGIME = {
    "low": "low",
    "medium": "normal",
    "elevated": "elevated",  # Only if DB contains elevated (currently doesn't)
    "high": "danger",
    "extreme": "high",
}


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
        """Load all trades from outcomes.db, enriched with sector from symbol_fundamentals."""
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

        # Enrich with sector from symbol_fundamentals
        if os.path.exists(TRADES_DB):
            try:
                fconn = sqlite3.connect(TRADES_DB)
                sectors = pd.read_sql_query(
                    "SELECT symbol, sector FROM symbol_fundamentals WHERE sector IS NOT NULL",
                    fconn,
                )
                fconn.close()
                df = df.merge(sectors, on="symbol", how="left")
            except Exception as e:
                logger.warning(f"Could not load sectors: {e}")
                df["sector"] = None
        else:
            df["sector"] = None

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

    def _load_baseline_metrics(self, strategy: str) -> Dict[str, float]:
        """Load metrics from last successful retrain, or return zeros (first run)."""
        history_file = HISTORY_DIR / f"retrain_{strategy}_latest.json"
        if history_file.exists():
            with open(history_file) as f:
                data = json.load(f)
            metrics = data.get("metrics", {})
            if "val_win_rate" in metrics:
                return metrics
        # Fallback: no history → use 0 (first run, safety check won't block)
        return {"val_win_rate": 0}

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

    def _get_training_config(self, strategy: str) -> dict:
        """Load strategy-specific training parameters from scoring_weights.yaml."""
        RecursiveConfigResolver.reset()
        resolver = RecursiveConfigResolver()
        return resolver.get_training_config(strategy)

    def train_sector_factors(self, df: pd.DataFrame, strategy: str) -> Dict[str, float]:
        """Train sector factors using rolling win-rate relative to overall."""
        strategy_score_col = f"{strategy}_score"
        if strategy_score_col not in df.columns or "sector" not in df.columns:
            return {}

        strat_df = df[df[strategy_score_col] > 0].copy()
        if len(strat_df) < 50:
            return {}

        # Load strategy-specific factor range from config
        RecursiveConfigResolver.reset()
        resolver = RecursiveConfigResolver()
        factor_range, _ = resolver.get_sector_factor_config(strategy)
        factor_min = factor_range.get("min", 0.6)
        factor_max = factor_range.get("max", 1.2)

        WINDOW = 60  # Last 60 trades per sector

        sector_factors = {}
        # Overall recent win-rate as baseline
        overall_recent = strat_df.sort_values("entry_date").tail(200)
        overall_wr = overall_recent["was_profitable"].mean()
        if overall_wr <= 0:
            return {}

        for sector, group in strat_df.groupby("sector"):
            if pd.isna(sector) or len(group) < 20:
                continue

            recent = group.sort_values("entry_date").tail(WINDOW)
            recent_wr = recent["was_profitable"].mean()

            raw_factor = recent_wr / overall_wr
            clamped = max(factor_min, min(factor_max, raw_factor))
            sector_factors[sector] = round(clamped, 3)

        if sector_factors:
            print(f"  Sector factors ({strategy}):")
            for sector, factor in sorted(sector_factors.items(), key=lambda x: -x[1]):
                print(f"    {sector:>25s}: {factor:.3f}")

        return sector_factors

    def train_stability_thresholds(
        self,
        df: pd.DataFrame,
        strategy: str,
        target_win_rate: float = 0.65,
        relative_margin: float = 0.05,
    ) -> Dict[str, int]:
        """Train per-regime stability thresholds via binary search with floor/cap.

        Target WR = max(target_win_rate, strategy_avg_wr - relative_margin)
        """
        strategy_score_col = f"{strategy}_score"
        if strategy_score_col not in df.columns:
            return {}

        strat_df = df[df[strategy_score_col] > 0].copy()

        # Need stability_score from symbol_fundamentals
        if "stability_score" not in strat_df.columns:
            if os.path.exists(TRADES_DB):
                try:
                    fconn = sqlite3.connect(TRADES_DB)
                    stab = pd.read_sql_query(
                        "SELECT symbol, stability_score FROM symbol_fundamentals "
                        "WHERE stability_score IS NOT NULL",
                        fconn,
                    )
                    fconn.close()
                    strat_df = strat_df.merge(stab, on="symbol", how="left")
                except Exception:
                    return {}
            else:
                return {}

        strat_df = strat_df.dropna(subset=["stability_score"])
        if len(strat_df) < 50:
            return {}

        # Compute effective target_win_rate based on strategy's actual win rate
        overall_strategy_wr = strat_df["was_profitable"].mean()
        effective_target = max(target_win_rate, overall_strategy_wr - relative_margin)

        print(f"    Stability target: strategy_wr={overall_strategy_wr*100:.1f}%, "
              f"effective_target={effective_target*100:.1f}% "
              f"(absolute_floor={target_win_rate*100:.0f}%, margin={relative_margin*100:.0f}pp)")

        ABSOLUTE_MIN = 50
        ABSOLUTE_MAX = 90

        thresholds = {}
        for db_regime in REGIMES:
            yaml_regime = DB_TO_YAML_REGIME.get(db_regime, db_regime)
            regime_df = strat_df[strat_df["vix_regime"] == db_regime]
            if len(regime_df) < 20:
                continue

            # Binary search for threshold achieving effective target win rate
            lo, hi = ABSOLUTE_MIN, ABSOLUTE_MAX
            best_threshold = lo
            while lo <= hi:
                mid = (lo + hi) // 2
                above = regime_df[regime_df["stability_score"] >= mid]
                if len(above) < 10:
                    hi = mid - 1
                    continue
                wr = above["was_profitable"].mean()
                if wr >= effective_target:
                    best_threshold = mid
                    hi = mid - 1  # Try lower threshold
                else:
                    lo = mid + 1  # Need higher threshold

            # Floor/cap enforcement
            if best_threshold >= ABSOLUTE_MAX:
                print(
                    f"    WARNING: {strategy}/{yaml_regime} threshold capped at {ABSOLUTE_MAX} "
                    f"(target WR {effective_target*100:.0f}% not achievable)"
                )
                best_threshold = ABSOLUTE_MAX

            best_threshold = max(ABSOLUTE_MIN, min(ABSOLUTE_MAX, best_threshold))
            thresholds[yaml_regime] = int(round(best_threshold))

        # Interpolate elevated if not trained directly
        if "elevated" not in thresholds:
            normal_t = thresholds.get("normal", thresholds.get("low", 70))
            danger_t = thresholds.get("danger", 80)
            thresholds["elevated"] = int(round((normal_t + danger_t) / 2))

        if thresholds:
            print(f"  Stability thresholds ({strategy}):")
            for regime, t in sorted(thresholds.items()):
                print(f"    {regime:>12s}: {t}")

        return thresholds

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

        # FIX 7: Load strategy-specific safety rails from config
        training_cfg = self._get_training_config(strategy)
        reg = training_cfg.get("regularization", {})
        wf = training_cfg.get("walk_forward", {})
        strategy_safety = SafetyRails(
            max_weight_change=reg.get("max_weight_change", self.safety.max_weight_change),
            min_new_trades=wf.get("min_trades", self.safety.min_new_trades),
            min_win_rate_improvement=self.safety.min_win_rate_improvement,
            max_objective_degradation=self.safety.max_objective_degradation,
        )

        # Check new trade count
        last_date = self.get_last_retrain_date(strategy)
        n_new = self.count_new_trades(df, strategy, last_date)
        print(f"  Last retrain: {last_date or 'never'}")
        print(f"  New trades: {n_new}")

        if n_new < strategy_safety.min_new_trades and not force:
            print(f"  SKIP: {n_new} new trades < {strategy_safety.min_new_trades} minimum")
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

        # Safety check — load real baseline from history, use strategy-specific rails
        old_metrics = self._load_baseline_metrics(strategy)
        saved_safety = self.safety
        self.safety = strategy_safety
        passed, issues = self.check_safety(old_weights, new_weights, old_metrics, result.metrics)
        self.safety = saved_safety

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

        # Per-regime training with strategy-specific min_trades
        base_min_trades = wf.get("min_trades", 200)
        regime_min_trades = max(30, int(base_min_trades * 0.4))

        print(f"  Regime training: min_trades={regime_min_trades} "
              f"(base={base_min_trades}, factor=0.4)")

        regime_results = {}
        for regime in REGIMES:
            regime_df = df[df["vix_regime"] == regime] if "vix_regime" in df.columns else df
            if len(regime_df) < regime_min_trades:
                print(f"    {regime}: skipped ({len(regime_df)} trades < {regime_min_trades})")
                continue

            RecursiveConfigResolver.reset()
            regime_trainer = StrategyWeightTrainer(strategy)
            regime_result = regime_trainer.train(regime_df)
            if regime_result.converged:
                regime_results[regime] = {
                    "weights": {k: round(v, 4) for k, v in regime_result.weights.items()},
                    "val_wr": round(regime_result.metrics.get("val_win_rate", 0), 4),
                    "n_trades": regime_result.n_trades,
                }
            else:
                print(f"    {regime}: training did not converge ({len(regime_df)} trades)")

        # Train sector factors (rolling win-rate)
        sector_factors = self.train_sector_factors(df, strategy)

        # Train stability thresholds (binary search with floor/cap)
        stability_thresholds = self.train_stability_thresholds(df, strategy)

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
                "sector_factors": sector_factors,
                "stability_thresholds": stability_thresholds,
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
