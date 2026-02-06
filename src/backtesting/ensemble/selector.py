#!/usr/bin/env python3
"""
Ensemble Strategy Selection - Main Selector (Facade)
=====================================================
Extracted from models/ensemble_selector.py (Phase 6d)

Combines multiple selection methods:
1. Raw score comparison
2. Regime-weighted selection
3. Meta-learner prediction
4. Confidence-weighted combination
"""

import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..models.ensemble_models import (
    STRATEGIES,
    DEFAULT_REGIME_PREFERENCES,
    CLUSTER_STRATEGY_MAP,
    SECTOR_STRATEGY_MAP,
    DEFAULT_COMPONENT_WEIGHTS,
    MIN_SCORE_THRESHOLDS,
    SelectionMethod,
    StrategyScore,
    EnsembleRecommendation,
    SymbolPerformance,
)
from .meta_learner import MetaLearner
from .rotation_engine import StrategyRotationEngine

logger = logging.getLogger(__name__)


class EnsembleSelector:
    """
    Main ensemble strategy selector (Facade).

    Delegates to:
    - MetaLearner: Symbol/regime-specific strategy prediction
    - StrategyRotationEngine: Automatic strategy rotation

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
                best_strat = pref_strat
                confidence = pref_conf
                reason = pref_source
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
        return max(0, 1 - cv)

    def _calculate_strategy_correlation(
        self,
        scores: Dict[str, StrategyScore],
        selected: str,
    ) -> float:
        """
        Calculate correlation between selected strategy and others.

        Based on component overlap.
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
        - ~/.optionplay/models/ENSEMBLE_V2_TRAINED.json
        - ~/.optionplay/models/SYMBOL_CLUSTERS.json
        - ~/.optionplay/models/SECTOR_CLUSTER_WEIGHTS.json
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
        """Get strategy recommendation based on symbol's cluster."""
        if not hasattr(self, '_symbol_clusters') or not self._symbol_clusters:
            return None

        cluster_info = self._symbol_clusters.get(symbol)
        if not cluster_info:
            return None

        vol_regime = cluster_info.get('vol_regime', 'medium')
        price_tier = cluster_info.get('price_tier', 'medium')
        trend_bias = cluster_info.get('trend_bias', 'mean_reverting')

        cluster_key = f"{vol_regime}_{price_tier}_{trend_bias}"

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
        """Get strategy recommendation based on sector."""
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
        """Get trained component weights for a specific sector."""
        if not hasattr(self, '_sector_weights') or not self._sector_weights:
            return DEFAULT_COMPONENT_WEIGHTS.copy()

        sector_data = self._sector_weights.get(sector)
        if sector_data and "optimal_weights" in sector_data:
            return sector_data["optimal_weights"]

        return DEFAULT_COMPONENT_WEIGHTS.copy()

    def get_cluster_weights(self, cluster_name: str) -> Dict[str, float]:
        """Get trained component weights for a specific cluster."""
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
        """
        # Try cluster weights first
        cluster_info = self._symbol_clusters.get(symbol) if hasattr(self, '_symbol_clusters') else None
        if cluster_info:
            cluster_name = cluster_info.get('cluster_name')
            if cluster_name and hasattr(self, '_cluster_weights'):
                cluster_data = self._cluster_weights.get(cluster_name)
                if cluster_data:
                    cluster_wr = cluster_data.get('win_rate', 0)
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
        """
        cluster_rec = self.get_cluster_recommendation(symbol)
        sector_rec = self.get_sector_recommendation(sector) if sector else None

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

        best = max(candidates, key=lambda x: x[1])
        return best
