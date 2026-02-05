#!/usr/bin/env python3
"""
Ensemble Strategy Selection Module

Combines all 4 strategies (Pullback, Bounce, Breakout, EarningsDip) using:
- Meta-Learner that selects best strategy per symbol/regime
- Weighted combination of scores across strategies
- Automatic strategy rotation based on performance
- Diversification benefits through ensemble approach

Features:
- Symbol-specific strategy preferences (learned from history)
- Regime-aware strategy selection
- Confidence-weighted strategy combination
- Performance tracking and auto-rotation
- Decay mechanism for outdated signals

Usage:
    from src.backtesting.ensemble_selector import (
        EnsembleSelector,
        MetaLearner,
        StrategyRotationEngine,
    )

    selector = EnsembleSelector()
    recommendation = selector.get_recommendation(symbol, scores_by_strategy, vix)
"""

import json
import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

import numpy as np

from .ensemble_models import (
    # Constants
    STRATEGIES,
    DEFAULT_REGIME_PREFERENCES,
    FEATURE_IMPACT,
    CLUSTER_STRATEGY_MAP,
    SECTOR_STRATEGY_MAP,
    DEFAULT_COMPONENT_WEIGHTS,
    MIN_SCORE_THRESHOLDS,
    # Enums
    SelectionMethod,
    RotationTrigger,
    # Data Classes
    StrategyScore,
    EnsembleRecommendation,
    SymbolPerformance,
    RotationState,
    # Functions
    create_strategy_score,
    format_ensemble_summary,
)

logger = logging.getLogger(__name__)


# Constants, Enums and Data Classes imported from .ensemble_models







# =============================================================================
# META-LEARNER
# =============================================================================

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
    ):
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
            symbol_weights = {s: 0.25 for s in STRATEGIES}

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
    ):
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
        # Get recent data for this regime
        # (In production, this would filter by regime)
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

    def save(self, filepath: str):
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


# =============================================================================
# STRATEGY ROTATION ENGINE
# =============================================================================

class StrategyRotationEngine:
    """
    Manages automatic strategy rotation based on performance.

    Tracks recent performance and adjusts strategy preferences
    when underperformance is detected.
    """

    def __init__(
        self,
        rotation_window_days: int = 30,
        performance_threshold: float = 0.40,
        min_trades_for_rotation: int = 10,
    ):
        self.rotation_window = rotation_window_days
        self.performance_threshold = performance_threshold
        self.min_trades = min_trades_for_rotation

        self._state = RotationState(
            current_preferences={s: 0.25 for s in STRATEGIES},
            last_rotation_date=date.today(),
            rotation_reason=None,
            recent_win_rates={s: [] for s in STRATEGIES},
            consecutive_losses={s: 0 for s in STRATEGIES},
        )

    def record_trade_result(
        self,
        strategy: str,
        outcome: bool,
        trade_date: date,
    ):
        """Record a trade result for rotation tracking"""
        # Update win rates
        self._state.recent_win_rates[strategy].append(1.0 if outcome else 0.0)

        # Keep only recent window
        max_trades = 50  # Rolling window
        if len(self._state.recent_win_rates[strategy]) > max_trades:
            self._state.recent_win_rates[strategy] = \
                self._state.recent_win_rates[strategy][-max_trades:]

        # Update consecutive losses
        if outcome:
            self._state.consecutive_losses[strategy] = 0
        else:
            self._state.consecutive_losses[strategy] += 1

    def check_rotation(self, current_date: date) -> Optional[Dict[str, Any]]:
        """
        Check if strategy rotation is needed.

        Returns:
            Rotation info dict if rotation triggered, None otherwise
        """
        should_rotate, trigger = self._state.should_rotate(
            current_date,
            self.performance_threshold,
            self.rotation_window,
        )

        if not should_rotate:
            return None

        # Calculate new preferences
        new_prefs = self._calculate_new_preferences()
        old_prefs = self._state.current_preferences.copy()

        # Record rotation
        rotation_info = {
            "date": current_date.isoformat(),
            "trigger": trigger.value,
            "old_preferences": old_prefs,
            "new_preferences": new_prefs,
            "recent_performance": {
                s: np.mean(wrs) if wrs else 0.5
                for s, wrs in self._state.recent_win_rates.items()
            },
        }

        self._state.rotation_history.append(rotation_info)
        self._state.current_preferences = new_prefs
        self._state.last_rotation_date = current_date
        self._state.rotation_reason = trigger

        # Reset consecutive losses
        self._state.consecutive_losses = {s: 0 for s in STRATEGIES}

        logger.info(f"Strategy rotation triggered: {trigger.value}")
        return rotation_info

    def _calculate_new_preferences(self) -> Dict[str, float]:
        """Calculate new strategy preferences based on recent performance"""
        performances = {}

        for strat in STRATEGIES:
            wrs = self._state.recent_win_rates.get(strat, [])
            if len(wrs) >= 5:
                # Recent win rate with recency weighting
                weights = [0.5 ** i for i in range(len(wrs))]
                weights = weights[::-1]  # More weight to recent
                performances[strat] = np.average(wrs, weights=weights[:len(wrs)])
            else:
                # Default to prior
                performances[strat] = self._state.current_preferences.get(strat, 0.25)

        # Normalize
        total = sum(performances.values())
        if total > 0:
            return {k: v / total for k, v in performances.items()}
        else:
            return {s: 0.25 for s in STRATEGIES}

    def get_current_preferences(self) -> Dict[str, float]:
        """Get current strategy preferences"""
        return self._state.current_preferences.copy()

    def get_rotation_summary(self) -> Dict[str, Any]:
        """Get summary of rotation state"""
        return {
            "current_preferences": self._state.current_preferences,
            "last_rotation": self._state.last_rotation_date.isoformat(),
            "last_rotation_reason": self._state.rotation_reason.value if self._state.rotation_reason else None,
            "days_since_rotation": (date.today() - self._state.last_rotation_date).days,
            "recent_performance": {
                s: round(np.mean(wrs), 3) if wrs else None
                for s, wrs in self._state.recent_win_rates.items()
            },
            "consecutive_losses": self._state.consecutive_losses,
            "rotation_count": len(self._state.rotation_history),
        }


# =============================================================================
# ENSEMBLE SELECTOR (MAIN CLASS)
# =============================================================================

class EnsembleSelector:
    """
    Main ensemble strategy selector.

    Combines multiple selection methods:
    1. Raw score comparison
    2. Regime-weighted selection
    3. Meta-learner prediction
    4. Confidence-weighted combination

    Usage:
        selector = EnsembleSelector()
        recommendation = selector.get_recommendation(
            symbol="AAPL",
            strategy_scores={
                "pullback": StrategyScore(...),
                "bounce": StrategyScore(...),
            },
            vix=18.5
        )
    """

    def __init__(
        self,
        method: SelectionMethod = SelectionMethod.META_LEARNER,
        enable_rotation: bool = True,
        min_score_threshold: float = 4.0,
    ):
        """
        Initialize ensemble selector.

        Args:
            method: Primary selection method
            enable_rotation: Enable automatic strategy rotation
            min_score_threshold: Minimum score to consider a strategy
        """
        self.method = method
        self.enable_rotation = enable_rotation
        self.min_score_threshold = min_score_threshold

        self._meta_learner = MetaLearner()
        self._rotation_engine = StrategyRotationEngine() if enable_rotation else None

    def get_recommendation(
        self,
        symbol: str,
        strategy_scores: Dict[str, StrategyScore],
        vix: Optional[float] = None,
        regime: Optional[str] = None,
        sector: Optional[str] = None,
    ) -> EnsembleRecommendation:
        """
        Get ensemble strategy recommendation.

        Args:
            symbol: Stock symbol
            strategy_scores: Dict of strategy -> StrategyScore
            vix: Current VIX value
            regime: Optional regime override
            sector: Optional sector for sector-specific weights

        Returns:
            EnsembleRecommendation with full analysis
        """
        # Determine regime from VIX if not provided
        if regime is None and vix is not None:
            regime = self._get_regime_from_vix(vix)

        # Filter to valid strategies (meeting minimum threshold)
        valid_scores = {
            strat: score for strat, score in strategy_scores.items()
            if score.weighted_score >= MIN_SCORE_THRESHOLDS.get(strat, self.min_score_threshold)
        }

        if not valid_scores:
            # No strategies meet threshold - use best available
            valid_scores = strategy_scores

        # Check for sector/cluster-based strategy preference
        sector_cluster_pref = self.get_strategy_preference(symbol, sector)
        cluster_rec = self.get_cluster_recommendation(symbol) if hasattr(self, '_symbol_clusters') else None
        sector_rec = self.get_sector_recommendation(sector) if sector else None

        # Select based on method
        if self.method == SelectionMethod.BEST_SCORE:
            best_strat, confidence, reason = self._select_best_score(valid_scores)
        elif self.method == SelectionMethod.WEIGHTED_BEST:
            best_strat, confidence, reason = self._select_weighted_best(valid_scores, regime)
        elif self.method == SelectionMethod.META_LEARNER:
            best_strat, confidence, reason = self._meta_learner.predict_best_strategy(
                symbol, valid_scores, regime
            )
            # Check for sector/cluster preference override
            pref_strat, pref_conf, pref_source = sector_cluster_pref
            if pref_strat and pref_conf >= 0.55 and pref_strat in valid_scores:
                # Use sector/cluster preference if it has valid score and high confidence
                best_strat = pref_strat
                confidence = pref_conf
                reason = pref_source
            # Fallback to cluster recommendation if no sector/cluster preference
            elif cluster_rec and cluster_rec.get('confidence', 0) >= 0.8:
                cluster_strat = cluster_rec['strategy']
                cluster_wr = cluster_rec['win_rate']
                if cluster_strat in valid_scores and cluster_wr >= 65:
                    best_strat = cluster_strat
                    confidence = cluster_rec['confidence']
                    reason = f"cluster: {cluster_rec['cluster_name']} ({cluster_wr:.1f}% WR)"
        elif self.method == SelectionMethod.CONFIDENCE_WEIGHTED:
            best_strat, confidence, reason = self._select_confidence_weighted(valid_scores)
        else:  # ENSEMBLE_VOTE
            best_strat, confidence, reason = self._select_ensemble_vote(
                symbol, valid_scores, regime
            )

        # Calculate ensemble score (weighted combination)
        ensemble_score, ensemble_conf = self._calculate_ensemble_score(
            valid_scores, regime
        )

        # Get alternative strategies
        alternatives = self._get_alternatives(valid_scores, best_strat)

        # Calculate diversification metrics
        div_benefit = self._calculate_diversification_benefit(valid_scores)
        strat_corr = self._calculate_strategy_correlation(valid_scores, best_strat)

        best_score = valid_scores.get(best_strat)

        return EnsembleRecommendation(
            symbol=symbol,
            timestamp=datetime.now(),
            recommended_strategy=best_strat,
            recommended_score=best_score.weighted_score if best_score else 0,
            selection_method=self.method,
            strategy_scores=strategy_scores,
            ensemble_score=ensemble_score,
            ensemble_confidence=ensemble_conf,
            regime=regime,
            vix=vix,
            selection_reason=reason,
            alternative_strategies=alternatives,
            diversification_benefit=div_benefit,
            strategy_correlation=strat_corr,
        )

    def update_with_result(
        self,
        symbol: str,
        strategy: str,
        outcome: bool,
        pnl_percent: float,
        signal_date: date,
        regime: Optional[str] = None,
    ):
        """
        Update selector with trade result.

        Call this after a trade completes to update meta-learner
        and rotation engine.
        """
        # Update meta-learner
        self._meta_learner.update_performance(
            symbol, strategy, outcome, pnl_percent, signal_date, regime
        )

        # Update rotation engine
        if self._rotation_engine:
            self._rotation_engine.record_trade_result(strategy, outcome, signal_date)

            # Check for rotation
            rotation = self._rotation_engine.check_rotation(signal_date)
            if rotation:
                logger.info(f"Strategy rotation: {rotation['trigger']}")

    def _get_regime_from_vix(self, vix: float) -> str:
        """Determine regime from VIX value"""
        if vix < 15:
            return "low_vol"
        elif vix < 20:
            return "normal"
        elif vix < 30:
            return "elevated"
        else:
            return "high_vol"

    def _select_best_score(
        self,
        scores: Dict[str, StrategyScore],
    ) -> Tuple[str, float, str]:
        """Select strategy with highest raw score"""
        if not scores:
            return "pullback", 0.0, "default (no valid scores)"

        best = max(scores, key=lambda s: scores[s].raw_score)
        return best, 0.7, f"highest raw score ({scores[best].raw_score:.1f})"

    def _select_weighted_best(
        self,
        scores: Dict[str, StrategyScore],
        regime: Optional[str],
    ) -> Tuple[str, float, str]:
        """Select best strategy with regime weighting"""
        regime_prefs = DEFAULT_REGIME_PREFERENCES.get(
            regime or "normal",
            DEFAULT_REGIME_PREFERENCES["normal"]
        )

        # Apply rotation preferences if available
        if self._rotation_engine:
            rotation_prefs = self._rotation_engine.get_current_preferences()
            # Blend: 70% regime, 30% rotation
            regime_prefs = {
                s: 0.7 * regime_prefs.get(s, 0.25) + 0.3 * rotation_prefs.get(s, 0.25)
                for s in STRATEGIES
            }

        # Calculate weighted scores
        weighted = {}
        for strat, score in scores.items():
            pref = regime_prefs.get(strat, 0.25)
            weighted[strat] = score.weighted_score * (0.5 + pref)  # Scale by preference

        if not weighted:
            return "pullback", 0.0, "default"

        best = max(weighted, key=weighted.get)
        confidence = min(1.0, weighted[best] / 10.0)  # Normalize

        return best, confidence, f"regime-weighted best ({regime})"

    def _select_confidence_weighted(
        self,
        scores: Dict[str, StrategyScore],
    ) -> Tuple[str, float, str]:
        """Select strategy with highest confidence-adjusted score"""
        if not scores:
            return "pullback", 0.0, "default"

        best = max(scores, key=lambda s: scores[s].adjusted_score)
        return best, scores[best].confidence, "highest confidence-adjusted score"

    def _select_ensemble_vote(
        self,
        symbol: str,
        scores: Dict[str, StrategyScore],
        regime: Optional[str],
    ) -> Tuple[str, float, str]:
        """Use voting across multiple selection methods"""
        votes = defaultdict(float)

        # Method 1: Best raw score
        best_raw, _, _ = self._select_best_score(scores)
        votes[best_raw] += 1.0

        # Method 2: Regime-weighted
        best_regime, _, _ = self._select_weighted_best(scores, regime)
        votes[best_regime] += 1.0

        # Method 3: Confidence-weighted
        best_conf, _, _ = self._select_confidence_weighted(scores)
        votes[best_conf] += 1.0

        # Method 4: Meta-learner
        best_ml, ml_conf, _ = self._meta_learner.predict_best_strategy(
            symbol, scores, regime
        )
        votes[best_ml] += ml_conf  # Weight by ML confidence

        # Winner
        winner = max(votes, key=votes.get)
        confidence = votes[winner] / (3.0 + 1.0)  # Normalize by total possible

        vote_counts = {k: f"{v:.1f}" for k, v in sorted(votes.items(), key=lambda x: -x[1])}

        return winner, confidence, f"ensemble vote: {vote_counts}"

    def _calculate_ensemble_score(
        self,
        scores: Dict[str, StrategyScore],
        regime: Optional[str],
    ) -> Tuple[float, float]:
        """Calculate combined ensemble score"""
        if not scores:
            return 0.0, 0.0

        # Get weights
        regime_prefs = DEFAULT_REGIME_PREFERENCES.get(
            regime or "normal",
            DEFAULT_REGIME_PREFERENCES["normal"]
        )

        # Weighted average of scores
        total_weight = 0.0
        total_score = 0.0
        total_confidence = 0.0

        for strat, score in scores.items():
            weight = regime_prefs.get(strat, 0.25)
            total_weight += weight
            total_score += score.weighted_score * weight
            total_confidence += score.confidence * weight

        if total_weight > 0:
            return total_score / total_weight, total_confidence / total_weight
        else:
            return 0.0, 0.0

    def _get_alternatives(
        self,
        scores: Dict[str, StrategyScore],
        selected: str,
    ) -> List[str]:
        """Get alternative strategies (sorted by score)"""
        others = [
            (strat, score.adjusted_score)
            for strat, score in scores.items()
            if strat != selected
        ]
        others.sort(key=lambda x: -x[1])

        # Return top 2 alternatives that meet threshold
        return [
            strat for strat, adj_score in others[:2]
            if adj_score >= self.min_score_threshold
        ]

    def _calculate_diversification_benefit(
        self,
        scores: Dict[str, StrategyScore],
    ) -> float:
        """
        Calculate diversification benefit.

        Higher score = more strategies have similar scores = more diversification options.
        """
        if len(scores) < 2:
            return 0.0

        adjusted_scores = [s.adjusted_score for s in scores.values()]

        # Calculate coefficient of variation (lower = more similar)
        mean_score = np.mean(adjusted_scores)
        if mean_score == 0:
            return 0.0

        cv = np.std(adjusted_scores) / mean_score

        # Convert to 0-1 benefit (lower CV = higher benefit)
        # CV of 0 = perfect diversification, CV > 1 = no diversification
        return max(0, 1 - cv)

    def _calculate_strategy_correlation(
        self,
        scores: Dict[str, StrategyScore],
        selected: str,
    ) -> float:
        """
        Calculate correlation between selected strategy and others.

        Based on component overlap (higher = more correlated = less diversification).
        """
        if selected not in scores:
            return 0.0

        selected_breakdown = scores[selected].breakdown

        correlations = []
        for strat, score in scores.items():
            if strat == selected:
                continue

            # Find common components
            common = set(selected_breakdown.keys()) & set(score.breakdown.keys())
            if not common:
                correlations.append(0.0)
                continue

            # Calculate correlation on common components
            vals1 = [selected_breakdown.get(c, 0) for c in common]
            vals2 = [score.breakdown.get(c, 0) for c in common]

            if np.std(vals1) > 0 and np.std(vals2) > 0:
                corr = np.corrcoef(vals1, vals2)[0, 1]
                correlations.append(abs(corr))
            else:
                correlations.append(0.5)

        return np.mean(correlations) if correlations else 0.0

    def get_insights(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get symbol-specific insights from meta-learner"""
        return self._meta_learner.get_symbol_insights(symbol)

    def get_rotation_status(self) -> Optional[Dict[str, Any]]:
        """Get current rotation status"""
        if self._rotation_engine:
            return self._rotation_engine.get_rotation_summary()
        return None

    def save(self, filepath: str):
        """Save ensemble selector state"""
        filepath = Path(filepath).expanduser()
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Save meta-learner
        ml_path = filepath.parent / f"{filepath.stem}_meta_learner.json"
        self._meta_learner.save(str(ml_path))

        # Save main state
        data = {
            "version": "1.0.0",
            "saved_date": datetime.now().isoformat(),
            "method": self.method.value,
            "enable_rotation": self.enable_rotation,
            "min_score_threshold": self.min_score_threshold,
            "meta_learner_path": str(ml_path),
        }

        if self._rotation_engine:
            data["rotation"] = self._rotation_engine.get_rotation_summary()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved ensemble selector to {filepath}")

    @classmethod
    def load(cls, filepath: str) -> "EnsembleSelector":
        """Load ensemble selector from file"""
        filepath = Path(filepath).expanduser()

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        selector = cls(
            method=SelectionMethod(data.get("method", "meta_learner")),
            enable_rotation=data.get("enable_rotation", True),
            min_score_threshold=data.get("min_score_threshold", 4.0),
        )

        # Load meta-learner if available
        ml_path = data.get("meta_learner_path")
        if ml_path and Path(ml_path).exists():
            selector._meta_learner = MetaLearner.load(ml_path)

        logger.info(f"Loaded ensemble selector from {filepath}")
        return selector

    @classmethod
    def load_trained_model(cls) -> "EnsembleSelector":
        """
        Load pre-trained ensemble model with symbol preferences.

        Loads from:
        - ~/.optionplay/models/ENSEMBLE_V2_TRAINED.json (feature impact, symbol prefs)
        - ~/.optionplay/models/SYMBOL_CLUSTERS.json (symbol clustering)
        - ~/.optionplay/models/SECTOR_CLUSTER_WEIGHTS.json (sector/cluster weights)

        Returns:
            Pre-configured EnsembleSelector with trained weights
        """
        selector = cls(
            method=SelectionMethod.META_LEARNER,
            enable_rotation=True,
            min_score_threshold=4.0,
        )

        # Load trained model data
        model_path = Path.home() / ".optionplay" / "models" / "ENSEMBLE_V2_TRAINED.json"
        if model_path.exists():
            try:
                with open(model_path, "r", encoding="utf-8") as f:
                    trained_data = json.load(f)

                # Load symbol preferences into meta-learner
                symbol_prefs = trained_data.get("top_symbol_preferences", {})
                for symbol, pref_data in symbol_prefs.items():
                    best_strat = pref_data.get("strategy")
                    win_rate = pref_data.get("win_rate", 50.0) / 100.0
                    trades = pref_data.get("trades", 0)

                    if best_strat and trades > 0:
                        perf = SymbolPerformance(
                            symbol=symbol,
                            strategy_win_rates={best_strat: win_rate},
                            strategy_sample_sizes={best_strat: trades},
                            best_strategy=best_strat,
                            best_strategy_confidence=min(1.0, trades / 30),
                            last_updated=datetime.now(),
                        )
                        selector._meta_learner._symbol_performance[symbol] = perf

                logger.info(
                    f"Loaded trained ensemble model with {len(symbol_prefs)} symbol preferences"
                )

            except Exception as e:
                logger.warning(f"Could not load trained model: {e}")

        # Load symbol cluster data
        cluster_path = Path.home() / ".optionplay" / "models" / "SYMBOL_CLUSTERS.json"
        if cluster_path.exists():
            try:
                with open(cluster_path, "r", encoding="utf-8") as f:
                    cluster_data = json.load(f)

                # Store cluster mappings
                selector._symbol_clusters = cluster_data.get("symbol_to_cluster", {})
                logger.info(
                    f"Loaded symbol cluster data with {len(selector._symbol_clusters)} symbols"
                )

            except Exception as e:
                logger.warning(f"Could not load cluster data: {e}")
                selector._symbol_clusters = {}
        else:
            selector._symbol_clusters = {}

        # Load sector and cluster weights
        weights_path = Path.home() / ".optionplay" / "models" / "SECTOR_CLUSTER_WEIGHTS.json"
        if weights_path.exists():
            try:
                with open(weights_path, "r", encoding="utf-8") as f:
                    weights_data = json.load(f)

                selector._sector_weights = weights_data.get("sector_weights", {})
                selector._cluster_weights = weights_data.get("cluster_weights", {})
                logger.info(
                    f"Loaded sector/cluster weights: {len(selector._sector_weights)} sectors, "
                    f"{len(selector._cluster_weights)} clusters"
                )

            except Exception as e:
                logger.warning(f"Could not load sector/cluster weights: {e}")
                selector._sector_weights = {}
                selector._cluster_weights = {}
        else:
            selector._sector_weights = {}
            selector._cluster_weights = {}

        return selector

    def get_cluster_recommendation(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get strategy recommendation based on symbol's cluster.

        Args:
            symbol: Stock symbol

        Returns:
            Dict with recommended strategy and confidence, or None if not found
        """
        if not hasattr(self, '_symbol_clusters') or not self._symbol_clusters:
            return None

        cluster_info = self._symbol_clusters.get(symbol)
        if not cluster_info:
            return None

        # Build cluster key from characteristics
        vol_regime = cluster_info.get('vol_regime', 'medium')
        price_tier = cluster_info.get('price_tier', 'medium')
        trend_bias = cluster_info.get('trend_bias', 'mean_reverting')

        cluster_key = f"{vol_regime}_{price_tier}_{trend_bias}"

        # Look up in strategy map
        strategy_info = CLUSTER_STRATEGY_MAP.get(cluster_key)
        if strategy_info:
            return {
                "symbol": symbol,
                "cluster_name": cluster_info.get('cluster_name', 'Unknown'),
                "strategy": strategy_info["strategy"],
                "win_rate": strategy_info["win_rate"],
                "confidence": strategy_info["confidence"],
                "vol_regime": vol_regime,
                "price_tier": price_tier,
            }

        # Fallback to cluster's recorded best strategy
        return {
            "symbol": symbol,
            "cluster_name": cluster_info.get('cluster_name', 'Unknown'),
            "strategy": cluster_info.get('best_strategy', 'pullback'),
            "win_rate": cluster_info.get('strategy_win_rate', 50.0),
            "confidence": 0.5,
            "vol_regime": vol_regime,
            "price_tier": price_tier,
        }

    def get_sector_recommendation(self, sector: str) -> Optional[Dict[str, Any]]:
        """
        Get strategy recommendation based on sector.

        Args:
            sector: Sector name (e.g., "Technology", "Utilities")

        Returns:
            Dict with recommended strategy and confidence, or None if not found
        """
        strategy_info = SECTOR_STRATEGY_MAP.get(sector)
        if strategy_info:
            return {
                "sector": sector,
                "strategy": strategy_info["strategy"],
                "win_rate": strategy_info["win_rate"],
                "confidence": strategy_info["confidence"],
            }
        return None

    def get_sector_weights(self, sector: str) -> Dict[str, float]:
        """
        Get trained component weights for a specific sector.

        Args:
            sector: Sector name

        Returns:
            Dict of component weights (defaults to 1.0 if not found)
        """
        if not hasattr(self, '_sector_weights') or not self._sector_weights:
            return DEFAULT_COMPONENT_WEIGHTS.copy()

        sector_data = self._sector_weights.get(sector)
        if sector_data and "optimal_weights" in sector_data:
            return sector_data["optimal_weights"]

        return DEFAULT_COMPONENT_WEIGHTS.copy()

    def get_cluster_weights(self, cluster_name: str) -> Dict[str, float]:
        """
        Get trained component weights for a specific cluster.

        Args:
            cluster_name: Cluster name (e.g., "Steady Mean-Reverting Medium")

        Returns:
            Dict of component weights (defaults to 1.0 if not found)
        """
        if not hasattr(self, '_cluster_weights') or not self._cluster_weights:
            return DEFAULT_COMPONENT_WEIGHTS.copy()

        cluster_data = self._cluster_weights.get(cluster_name)
        if cluster_data and "optimal_weights" in cluster_data:
            return cluster_data["optimal_weights"]

        return DEFAULT_COMPONENT_WEIGHTS.copy()

    def get_combined_weights(
        self,
        symbol: str,
        sector: Optional[str] = None,
    ) -> Tuple[Dict[str, float], str]:
        """
        Get combined component weights for a symbol based on sector and cluster.

        Priority:
        1. Cluster weights (if available and cluster win rate > 60%)
        2. Sector weights (if available)
        3. Default weights

        Args:
            symbol: Stock symbol
            sector: Optional sector override

        Returns:
            Tuple of (weights dict, source description)
        """
        # Try cluster weights first
        cluster_info = self._symbol_clusters.get(symbol) if hasattr(self, '_symbol_clusters') else None
        if cluster_info:
            cluster_name = cluster_info.get('cluster_name')
            if cluster_name and hasattr(self, '_cluster_weights'):
                cluster_data = self._cluster_weights.get(cluster_name)
                if cluster_data:
                    cluster_wr = cluster_data.get('win_rate', 0)
                    # Only use cluster weights if win rate is significant
                    if cluster_wr >= 55:
                        weights = cluster_data.get('optimal_weights', DEFAULT_COMPONENT_WEIGHTS.copy())
                        return weights, f"cluster:{cluster_name} ({cluster_wr:.1f}% WR)"

        # Try sector weights
        if sector and hasattr(self, '_sector_weights'):
            sector_data = self._sector_weights.get(sector)
            if sector_data:
                sector_wr = sector_data.get('win_rate', 0)
                if sector_wr >= 50:
                    weights = sector_data.get('optimal_weights', DEFAULT_COMPONENT_WEIGHTS.copy())
                    return weights, f"sector:{sector} ({sector_wr:.1f}% WR)"

        return DEFAULT_COMPONENT_WEIGHTS.copy(), "default"

    def get_strategy_preference(
        self,
        symbol: str,
        sector: Optional[str] = None,
    ) -> Tuple[Optional[str], float, str]:
        """
        Get preferred strategy for a symbol based on sector and cluster.

        Combines sector and cluster preferences with confidence weighting.

        Args:
            symbol: Stock symbol
            sector: Optional sector name

        Returns:
            Tuple of (strategy name or None, confidence, source description)
        """
        cluster_rec = self.get_cluster_recommendation(symbol)
        sector_rec = self.get_sector_recommendation(sector) if sector else None

        # Priority: high-confidence cluster > high-confidence sector > lower confidence
        candidates = []

        if cluster_rec and cluster_rec.get('win_rate', 0) >= 60:
            candidates.append((
                cluster_rec['strategy'],
                cluster_rec['confidence'] * (cluster_rec['win_rate'] / 100),
                f"cluster:{cluster_rec['cluster_name']}"
            ))

        if sector_rec and sector_rec.get('win_rate', 0) >= 55:
            candidates.append((
                sector_rec['strategy'],
                sector_rec['confidence'] * (sector_rec['win_rate'] / 100),
                f"sector:{sector}"
            ))

        if not candidates:
            return None, 0.0, "no preference"

        # Return highest confidence preference
        best = max(candidates, key=lambda x: x[1])
        return best


# Helper functions (create_strategy_score, format_ensemble_summary)
# are now imported from .ensemble_models
