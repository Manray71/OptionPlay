# OptionPlay - Meta-Learner for Strategy Selection
# =================================================
# Extracted from models/ensemble_selector.py (Phase 6d)
#
# ML-based meta-learner that selects best strategy per symbol/regime.

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..models.ensemble_models import (
    STRATEGIES,
    DEFAULT_REGIME_PREFERENCES,
    StrategyScore,
    SymbolPerformance,
)

logger = logging.getLogger(__name__)


class MetaLearner:
    """
    ML-based meta-learner for strategy selection.

    Learns which strategy works best for:
    - Specific symbols (stock characteristics)
    - Market regimes (VIX environment)
    - Recent performance patterns
    """

    def __init__(
        self,
        history_window_days: int = 90,
        min_samples_per_strategy: int = 10,
        decay_factor: float = 0.95,
    ) -> None:
        self.history_window = history_window_days
        self.min_samples = min_samples_per_strategy
        self.decay_factor = decay_factor

        # Symbol-specific performance
        self._symbol_performance: Dict[str, SymbolPerformance] = {}

        # Regime-specific preferences (learned)
        self._regime_preferences: Dict[str, Dict[str, float]] = DEFAULT_REGIME_PREFERENCES.copy()

        # Global strategy performance
        self._global_performance: Dict[str, List[Tuple[date, bool, float]]] = {
            s: [] for s in STRATEGIES
        }

    def predict_best_strategy(
        self,
        symbol: str,
        strategy_scores: Dict[str, StrategyScore],
        regime: Optional[str] = None,
    ) -> Tuple[str, float, str]:
        """
        Predict best strategy for symbol.

        Args:
            symbol: Stock symbol
            strategy_scores: Scores from each strategy
            regime: Current market regime

        Returns:
            Tuple of (strategy_name, confidence, reason)
        """
        # Get symbol-specific weights if available
        symbol_perf = self._symbol_performance.get(symbol)
        if symbol_perf and symbol_perf.best_strategy:
            symbol_weights = symbol_perf.get_preference_weights()
        else:
            symbol_weights = {s: 1.0 / len(STRATEGIES) for s in STRATEGIES}

        # Get regime weights
        regime_weights = self._regime_preferences.get(
            regime or "normal",
            DEFAULT_REGIME_PREFERENCES["normal"]
        )

        # Combine weights
        combined_weights = {}
        for strat in STRATEGIES:
            # 40% symbol history, 30% regime, 30% global score
            sw = symbol_weights.get(strat, 0.25)
            rw = regime_weights.get(strat, 0.25)

            score = strategy_scores.get(strat)
            if score:
                # Normalize score to 0-1 range (assuming max 15)
                score_weight = min(score.adjusted_score / 15.0, 1.0)
            else:
                score_weight = 0.0

            combined_weights[strat] = 0.4 * sw + 0.3 * rw + 0.3 * score_weight

        # Select best
        best_strat = max(combined_weights, key=combined_weights.get)
        confidence = combined_weights[best_strat]

        # Build reason
        reasons = []
        if symbol_perf and symbol_perf.best_strategy == best_strat:
            reasons.append(f"historically best for {symbol}")
        if regime_weights.get(best_strat, 0) == max(regime_weights.values()):
            reasons.append(f"preferred in {regime} regime")
        if strategy_scores.get(best_strat):
            if strategy_scores[best_strat].raw_score == max(
                s.raw_score for s in strategy_scores.values()
            ):
                reasons.append("highest raw score")

        reason = "; ".join(reasons) if reasons else "ensemble selection"

        return best_strat, confidence, reason

    def update_performance(
        self,
        symbol: str,
        strategy: str,
        outcome: bool,  # True = win
        pnl_percent: float,
        signal_date: date,
        regime: Optional[str] = None,
    ) -> None:
        """Update performance tracking with new trade result"""
        # Update symbol performance
        if symbol not in self._symbol_performance:
            self._symbol_performance[symbol] = SymbolPerformance(symbol=symbol)

        perf = self._symbol_performance[symbol]

        # Update strategy stats
        current_wins = perf.strategy_win_rates.get(strategy, 0.5) * perf.strategy_sample_sizes.get(strategy, 0)
        current_samples = perf.strategy_sample_sizes.get(strategy, 0)

        new_samples = current_samples + 1
        new_wins = current_wins + (1 if outcome else 0)

        perf.strategy_win_rates[strategy] = new_wins / new_samples
        perf.strategy_sample_sizes[strategy] = new_samples

        # Update average returns (exponential moving average)
        alpha = 0.2
        current_avg = perf.strategy_avg_returns.get(strategy, 0)
        perf.strategy_avg_returns[strategy] = alpha * pnl_percent + (1 - alpha) * current_avg

        # Update best strategy
        if perf.strategy_sample_sizes:
            best = max(
                perf.strategy_win_rates,
                key=lambda s: perf.strategy_win_rates.get(s, 0) * np.sqrt(perf.strategy_sample_sizes.get(s, 0))
            )
            perf.best_strategy = best
            best_samples = perf.strategy_sample_sizes.get(best, 0)
            perf.best_strategy_confidence = min(1.0, best_samples / 30)  # Max confidence at 30 samples

        perf.last_updated = datetime.now()

        # Update global performance
        self._global_performance[strategy].append((signal_date, outcome, pnl_percent))

        # Update regime preferences if enough data
        if regime:
            self._update_regime_preferences(regime)

    def _update_regime_preferences(self, regime: str):
        """Update regime preferences based on recent performance"""
        cutoff = date.today() - timedelta(days=self.history_window)

        regime_win_rates = {}
        for strat, trades in self._global_performance.items():
            recent = [(d, w, p) for d, w, p in trades if d >= cutoff]
            if len(recent) >= self.min_samples:
                win_rate = sum(1 for _, w, _ in recent if w) / len(recent)
                regime_win_rates[strat] = win_rate

        if not regime_win_rates:
            return

        # Normalize to preferences
        total = sum(regime_win_rates.values())
        if total > 0:
            self._regime_preferences[regime] = {
                k: v / total for k, v in regime_win_rates.items()
            }

    def get_symbol_insights(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get insights for a specific symbol"""
        perf = self._symbol_performance.get(symbol)
        if not perf:
            return None

        return {
            "symbol": symbol,
            "best_strategy": perf.best_strategy,
            "confidence": perf.best_strategy_confidence,
            "win_rates": perf.strategy_win_rates,
            "avg_returns": perf.strategy_avg_returns,
            "sample_sizes": perf.strategy_sample_sizes,
            "preference_weights": perf.get_preference_weights(),
        }

    def save(self, filepath: str) -> None:
        """Save meta-learner state"""
        filepath = Path(filepath).expanduser()
        filepath.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": "1.0.0",
            "saved_date": datetime.now().isoformat(),
            "symbol_performance": {
                k: v.to_dict() for k, v in self._symbol_performance.items()
            },
            "regime_preferences": self._regime_preferences,
            "global_performance": {
                strat: [
                    {"date": d.isoformat(), "win": w, "pnl": p}
                    for d, w, p in trades[-500:]  # Keep last 500
                ]
                for strat, trades in self._global_performance.items()
            },
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved meta-learner state to {filepath}")

    @classmethod
    def load(cls, filepath: str) -> "MetaLearner":
        """Load meta-learner from file"""
        filepath = Path(filepath).expanduser()

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        learner = cls()

        # Restore symbol performance
        for symbol, perf_data in data.get("symbol_performance", {}).items():
            learner._symbol_performance[symbol] = SymbolPerformance(
                symbol=symbol,
                strategy_win_rates=perf_data.get("win_rates", {}),
                strategy_sample_sizes=perf_data.get("sample_sizes", {}),
                strategy_avg_returns=perf_data.get("avg_returns", {}),
                best_strategy=perf_data.get("best_strategy"),
                best_strategy_confidence=perf_data.get("best_strategy_confidence", 0),
                last_updated=datetime.fromisoformat(perf_data["last_updated"]) if perf_data.get("last_updated") else None,
            )

        # Restore regime preferences
        learner._regime_preferences = data.get("regime_preferences", DEFAULT_REGIME_PREFERENCES.copy())

        # Restore global performance
        for strat, trades in data.get("global_performance", {}).items():
            learner._global_performance[strat] = [
                (date.fromisoformat(t["date"]), t["win"], t["pnl"])
                for t in trades
            ]

        logger.info(f"Loaded meta-learner from {filepath}")
        return learner
