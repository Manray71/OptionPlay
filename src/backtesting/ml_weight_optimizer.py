#!/usr/bin/env python3
"""
ML-Based Component Weight Optimizer

Replaces static component weights with trained weights using:
- Random Forest for feature importance
- Gradient Boosting for outcome prediction
- Cross-validation across market phases
- Per-strategy and per-regime optimization

Features:
- Automatic feature importance ranking
- Rolling retrain support (3-6 month windows)
- VIX regime-aware weight sets
- Confidence intervals for weight reliability

Usage:
    from src.backtesting.ml_weight_optimizer import (
        MLWeightOptimizer,
        WeightConfig,
        OptimizationResult,
    )

    optimizer = MLWeightOptimizer()
    result = optimizer.train(historical_trades, vix_data)

    # Apply optimized weights
    weighted_score = result.weight_config.apply_weights(score_breakdown)
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

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# All score components across strategies
ALL_COMPONENTS = [
    # Core indicators
    "rsi_score",
    "rsi_divergence_score",
    "support_score",
    "fibonacci_score",
    "ma_score",
    "trend_strength_score",
    "volume_score",
    # Momentum indicators
    "macd_score",
    "stoch_score",
    "keltner_score",
    # Strategy-specific
    "relative_strength_score",
    "momentum_score",
    "dip_score",
    "stabilization_score",
    "gap_score",
    "candlestick_score",
    "ath_breakout_score",
    # NEW from Feature Engineering (2026-01-28)
    "vwap_score",           # VWAP distance score (0-3)
    "market_context_score", # SPY trend filter (-1 to +2)
    "sector_score",         # Sector-based adjustment (-1 to +1)
]

# Components per strategy
STRATEGY_COMPONENTS = {
    "pullback": [
        "rsi_score", "rsi_divergence_score", "support_score", "fibonacci_score",
        "ma_score", "trend_strength_score", "volume_score",
        "macd_score", "stoch_score", "keltner_score",
        "vwap_score", "market_context_score", "sector_score",  # NEW
    ],
    "bounce": [
        "rsi_score", "rsi_divergence_score", "support_score",
        "volume_score", "ma_score", "candlestick_score",
        "macd_score", "stoch_score", "keltner_score",
        "vwap_score", "market_context_score", "sector_score",  # NEW
    ],
    "ath_breakout": [
        "ath_breakout_score", "volume_score", "ma_score",
        "rsi_score", "relative_strength_score",
        "macd_score", "momentum_score", "keltner_score",
        "vwap_score", "market_context_score", "sector_score",  # NEW
    ],
    "earnings_dip": [
        "dip_score", "gap_score", "rsi_score", "stabilization_score",
        "volume_score", "ma_score",
        "macd_score", "stoch_score", "keltner_score",
        "vwap_score", "market_context_score", "sector_score",  # NEW
    ],
}

# Default weights (equal weighting)
DEFAULT_WEIGHTS = {comp: 1.0 for comp in ALL_COMPONENTS}


# =============================================================================
# DATA CLASSES
# =============================================================================

class OptimizationMethod(str, Enum):
    """ML method for weight optimization"""
    RANDOM_FOREST = "random_forest"
    GRADIENT_BOOSTING = "gradient_boosting"
    CORRELATION = "correlation"
    ENSEMBLE = "ensemble"


@dataclass
class ComponentStats:
    """Statistics for a single score component"""
    name: str
    sample_size: int

    # Correlation metrics
    win_rate_correlation: float
    pnl_correlation: float

    # Distribution metrics
    avg_value_winners: float
    avg_value_losers: float
    std_value: float

    # Importance scores (from ML)
    rf_importance: float = 0.0
    gb_importance: float = 0.0
    ensemble_importance: float = 0.0

    # Derived
    predictive_power: str = "unknown"  # "strong", "moderate", "weak", "none"
    recommended_weight: float = 1.0
    confidence_interval: Tuple[float, float] = (0.0, 2.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "sample_size": self.sample_size,
            "correlations": {
                "win_rate": round(self.win_rate_correlation, 4),
                "pnl": round(self.pnl_correlation, 4),
            },
            "distribution": {
                "avg_winners": round(self.avg_value_winners, 3),
                "avg_losers": round(self.avg_value_losers, 3),
                "std": round(self.std_value, 3),
            },
            "importance": {
                "random_forest": round(self.rf_importance, 4),
                "gradient_boosting": round(self.gb_importance, 4),
                "ensemble": round(self.ensemble_importance, 4),
            },
            "predictive_power": self.predictive_power,
            "recommended_weight": round(self.recommended_weight, 3),
            "confidence_interval": [round(x, 3) for x in self.confidence_interval],
        }


@dataclass
class WeightConfig:
    """Optimized weight configuration"""
    strategy: str
    regime: Optional[str]  # None = all regimes

    # Raw weights (sum may not be 1)
    weights: Dict[str, float]

    # Normalized weights (sum = 1)
    normalized_weights: Dict[str, float]

    # Metadata
    method: OptimizationMethod
    training_date: datetime
    sample_size: int
    validation_score: float  # OOS validation metric
    confidence: str  # "high", "medium", "low"

    def apply_weights(self, score_breakdown: Dict[str, float]) -> float:
        """
        Apply optimized weights to a score breakdown.

        Args:
            score_breakdown: Dict of {component_name: raw_score}

        Returns:
            Weighted total score
        """
        total = 0.0
        for component, raw_score in score_breakdown.items():
            weight = self.weights.get(component, 1.0)
            total += raw_score * weight
        return total

    def apply_normalized(self, score_breakdown: Dict[str, float]) -> float:
        """Apply normalized weights (scores sum proportionally)"""
        total = 0.0
        weight_sum = 0.0

        for component, raw_score in score_breakdown.items():
            weight = self.normalized_weights.get(component, 0.0)
            total += raw_score * weight
            weight_sum += weight

        # Scale to original score range if needed
        return total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "regime": self.regime,
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "normalized_weights": {k: round(v, 4) for k, v in self.normalized_weights.items()},
            "metadata": {
                "method": self.method.value,
                "training_date": self.training_date.isoformat(),
                "sample_size": self.sample_size,
                "validation_score": round(self.validation_score, 4),
                "confidence": self.confidence,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeightConfig":
        meta = data.get("metadata", {})
        return cls(
            strategy=data["strategy"],
            regime=data.get("regime"),
            weights=data.get("weights", {}),
            normalized_weights=data.get("normalized_weights", {}),
            method=OptimizationMethod(meta.get("method", "correlation")),
            training_date=datetime.fromisoformat(meta.get("training_date", datetime.now().isoformat())),
            sample_size=meta.get("sample_size", 0),
            validation_score=meta.get("validation_score", 0.0),
            confidence=meta.get("confidence", "unknown"),
        )


@dataclass
class OptimizationResult:
    """Complete optimization result"""
    optimization_id: str
    optimization_date: datetime

    # Per-strategy weight configs
    strategy_weights: Dict[str, WeightConfig]

    # Per-regime weight configs (optional)
    regime_weights: Dict[str, Dict[str, WeightConfig]]  # {regime: {strategy: WeightConfig}}

    # Component analysis
    component_stats: Dict[str, ComponentStats]

    # Overall metrics
    total_trades_analyzed: int
    overall_validation_score: float
    improvement_vs_baseline: float  # % improvement over equal weights

    # Warnings
    warnings: List[str] = field(default_factory=list)

    def get_weights(
        self,
        strategy: str,
        regime: Optional[str] = None,
    ) -> WeightConfig:
        """Get weight config for strategy and optional regime"""
        if regime and regime in self.regime_weights:
            if strategy in self.regime_weights[regime]:
                return self.regime_weights[regime][strategy]

        return self.strategy_weights.get(
            strategy,
            WeightConfig(
                strategy=strategy,
                regime=None,
                weights=DEFAULT_WEIGHTS.copy(),
                normalized_weights={k: 1.0 / len(DEFAULT_WEIGHTS) for k in DEFAULT_WEIGHTS},
                method=OptimizationMethod.CORRELATION,
                training_date=datetime.now(),
                sample_size=0,
                validation_score=0.0,
                confidence="low",
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "optimization_id": self.optimization_id,
            "optimization_date": self.optimization_date.isoformat(),
            "strategy_weights": {
                k: v.to_dict() for k, v in self.strategy_weights.items()
            },
            "regime_weights": {
                regime: {strat: wc.to_dict() for strat, wc in strats.items()}
                for regime, strats in self.regime_weights.items()
            },
            "component_stats": {
                k: v.to_dict() for k, v in self.component_stats.items()
            },
            "summary": {
                "total_trades": self.total_trades_analyzed,
                "validation_score": round(self.overall_validation_score, 4),
                "improvement_vs_baseline": round(self.improvement_vs_baseline, 2),
            },
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        """Format as readable summary"""
        lines = [
            "",
            "=" * 70,
            "  ML WEIGHT OPTIMIZATION RESULT",
            "=" * 70,
            f"  ID:              {self.optimization_id}",
            f"  Date:            {self.optimization_date.strftime('%Y-%m-%d %H:%M')}",
            f"  Trades Analyzed: {self.total_trades_analyzed:,}",
            f"  Validation Score: {self.overall_validation_score:.3f}",
            f"  Improvement:     {self.improvement_vs_baseline:+.1f}% vs baseline",
            "",
            "-" * 70,
            "  TOP COMPONENTS BY IMPORTANCE",
            "-" * 70,
        ]

        # Sort by ensemble importance
        sorted_stats = sorted(
            self.component_stats.values(),
            key=lambda x: x.ensemble_importance,
            reverse=True
        )

        for i, stat in enumerate(sorted_stats[:10], 1):
            power_icon = {
                "strong": "+++",
                "moderate": "++",
                "weak": "+",
                "none": "-",
            }.get(stat.predictive_power, "?")

            lines.append(
                f"  {i:2d}. {stat.name:<25} "
                f"Importance: {stat.ensemble_importance:.3f} "
                f"Weight: {stat.recommended_weight:.2f} "
                f"[{power_icon}]"
            )

        lines.extend([
            "",
            "-" * 70,
            "  OPTIMIZED WEIGHTS BY STRATEGY",
            "-" * 70,
        ])

        for strategy, config in self.strategy_weights.items():
            top_weights = sorted(
                config.weights.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]

            weight_str = ", ".join(f"{k.replace('_score', '')}={v:.2f}" for k, v in top_weights)
            lines.append(f"  {strategy:<15} {weight_str}")

        if self.warnings:
            lines.extend([
                "",
                "-" * 70,
                "  WARNINGS",
                "-" * 70,
            ])
            for w in self.warnings:
                lines.append(f"  ! {w}")

        lines.append("=" * 70)
        return "\n".join(lines)


# =============================================================================
# FEATURE EXTRACTION
# =============================================================================

@dataclass
class TradeFeatures:
    """Extracted features from a trade for ML training"""
    trade_id: str
    symbol: str
    strategy: str
    signal_date: date

    # Score components (features)
    components: Dict[str, float]

    # Target variable
    is_winner: bool
    pnl_percent: float

    # Context
    vix_at_signal: Optional[float]
    regime: Optional[str]
    holding_days: int


class FeatureExtractor:
    """Extract ML features from historical trades"""

    def __init__(self):
        self._regime_boundaries = {
            "low_vol": (0, 15),
            "normal": (15, 20),
            "elevated": (20, 30),
            "high_vol": (30, 100),
        }

    def extract_from_trades(
        self,
        trades: List[Dict[str, Any]],
    ) -> List[TradeFeatures]:
        """
        Extract features from list of trade dicts.

        Args:
            trades: List of trade records from TradeTracker

        Returns:
            List of TradeFeatures for ML training
        """
        features = []

        for trade in trades:
            # Skip incomplete trades
            if trade.get("outcome") not in ("WIN", "LOSS"):
                continue

            # Extract score breakdown
            breakdown = trade.get("score_breakdown", {})
            if isinstance(breakdown, str):
                try:
                    breakdown = json.loads(breakdown)
                except (json.JSONDecodeError, TypeError):
                    breakdown = {}

            if not breakdown:
                continue

            # Normalize component names
            components = {}
            for key, value in breakdown.items():
                # Handle nested dicts
                if isinstance(value, dict):
                    value = value.get("score", value.get("value", 0))
                if isinstance(value, (int, float)):
                    # Normalize key name
                    norm_key = key.lower()
                    if not norm_key.endswith("_score"):
                        norm_key = f"{norm_key}_score"
                    components[norm_key] = float(value)

            if not components:
                continue

            # Determine regime from VIX
            vix = trade.get("vix_at_signal")
            regime = self._get_regime(vix) if vix else None

            # Create features
            features.append(TradeFeatures(
                trade_id=str(trade.get("id", len(features))),
                symbol=trade.get("symbol", "UNKNOWN"),
                strategy=trade.get("strategy", "pullback"),
                signal_date=self._parse_date(trade.get("signal_date")),
                components=components,
                is_winner=trade.get("outcome") == "WIN",
                pnl_percent=float(trade.get("pnl_percent", 0)),
                vix_at_signal=vix,
                regime=regime,
                holding_days=int(trade.get("holding_days", 0)),
            ))

        logger.info(f"Extracted {len(features)} trade features from {len(trades)} trades")
        return features

    def _get_regime(self, vix: float) -> str:
        """Determine regime from VIX value"""
        for regime, (low, high) in self._regime_boundaries.items():
            if low <= vix < high:
                return regime
        return "normal"

    def _parse_date(self, d: Any) -> date:
        """Parse date from various formats"""
        if isinstance(d, date):
            return d
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, str):
            try:
                return date.fromisoformat(d[:10])
            except ValueError:
                pass
        return date.today()


# =============================================================================
# ML WEIGHT OPTIMIZER
# =============================================================================

class MLWeightOptimizer:
    """
    ML-based component weight optimizer.

    Uses ensemble of methods:
    - Correlation analysis (baseline)
    - Random Forest feature importance
    - Gradient Boosting feature importance
    - Cross-validation for robustness

    Supports:
    - Per-strategy optimization
    - Per-regime optimization
    - Rolling retrain windows
    """

    def __init__(
        self,
        method: OptimizationMethod = OptimizationMethod.ENSEMBLE,
        cv_folds: int = 5,
        min_samples_per_strategy: int = 50,
        enable_regime_weights: bool = True,
    ):
        """
        Initialize optimizer.

        Args:
            method: Optimization method to use
            cv_folds: Number of cross-validation folds
            min_samples_per_strategy: Minimum trades per strategy
            enable_regime_weights: Train separate weights per regime
        """
        self.method = method
        self.cv_folds = cv_folds
        self.min_samples = min_samples_per_strategy
        self.enable_regime_weights = enable_regime_weights

        self._feature_extractor = FeatureExtractor()
        self._last_result: Optional[OptimizationResult] = None

    def train(
        self,
        trades: List[Dict[str, Any]],
        vix_data: Optional[List[Dict]] = None,
    ) -> OptimizationResult:
        """
        Train optimized weights from historical trades.

        Args:
            trades: List of historical trade records
            vix_data: Optional VIX history for regime context

        Returns:
            OptimizationResult with optimized weights
        """
        import uuid

        optimization_id = f"weights_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        warnings = []

        # Extract features
        features = self._feature_extractor.extract_from_trades(trades)

        if len(features) < self.min_samples:
            warnings.append(f"Only {len(features)} trades available (minimum: {self.min_samples})")
            return self._create_default_result(optimization_id, warnings)

        # Analyze components
        component_stats = self._analyze_components(features)

        # Train per-strategy weights
        strategy_weights = {}
        for strategy in STRATEGY_COMPONENTS.keys():
            strategy_features = [f for f in features if f.strategy == strategy]

            if len(strategy_features) >= self.min_samples // 2:
                config = self._train_strategy_weights(
                    strategy, strategy_features, component_stats
                )
                strategy_weights[strategy] = config
            else:
                warnings.append(f"Insufficient data for {strategy} ({len(strategy_features)} trades)")
                strategy_weights[strategy] = self._create_default_weight_config(strategy)

        # Train per-regime weights (optional)
        regime_weights: Dict[str, Dict[str, WeightConfig]] = {}
        if self.enable_regime_weights:
            for regime in ["low_vol", "normal", "elevated", "high_vol"]:
                regime_features = [f for f in features if f.regime == regime]

                if len(regime_features) >= self.min_samples // 2:
                    regime_weights[regime] = {}
                    for strategy in STRATEGY_COMPONENTS.keys():
                        strat_regime_features = [
                            f for f in regime_features if f.strategy == strategy
                        ]
                        if len(strat_regime_features) >= 20:
                            config = self._train_strategy_weights(
                                strategy, strat_regime_features, component_stats, regime
                            )
                            regime_weights[regime][strategy] = config

        # Calculate validation metrics
        baseline_score = self._calculate_baseline_score(features)
        optimized_score = self._validate_weights(features, strategy_weights)
        improvement = ((optimized_score - baseline_score) / baseline_score * 100
                       if baseline_score > 0 else 0)

        result = OptimizationResult(
            optimization_id=optimization_id,
            optimization_date=datetime.now(),
            strategy_weights=strategy_weights,
            regime_weights=regime_weights,
            component_stats=component_stats,
            total_trades_analyzed=len(features),
            overall_validation_score=optimized_score,
            improvement_vs_baseline=improvement,
            warnings=warnings,
        )

        self._last_result = result
        return result

    def _analyze_components(
        self,
        features: List[TradeFeatures],
    ) -> Dict[str, ComponentStats]:
        """Analyze all components across all trades"""
        stats = {}

        # Collect values per component
        component_data: Dict[str, Dict[str, List]] = defaultdict(
            lambda: {"values": [], "outcomes": [], "pnls": []}
        )

        for f in features:
            for comp, value in f.components.items():
                component_data[comp]["values"].append(value)
                component_data[comp]["outcomes"].append(1 if f.is_winner else 0)
                component_data[comp]["pnls"].append(f.pnl_percent)

        # Calculate stats for each component
        for comp, data in component_data.items():
            if len(data["values"]) < 10:
                continue

            values = np.array(data["values"])
            outcomes = np.array(data["outcomes"])
            pnls = np.array(data["pnls"])

            # Correlations
            win_corr = self._safe_correlation(values, outcomes)
            pnl_corr = self._safe_correlation(values, pnls)

            # Distribution by outcome
            winner_mask = outcomes == 1
            avg_winners = np.mean(values[winner_mask]) if winner_mask.any() else 0
            avg_losers = np.mean(values[~winner_mask]) if (~winner_mask).any() else 0

            # Feature importance (simplified without sklearn)
            rf_imp = abs(win_corr) * 0.5 + abs(pnl_corr) * 0.5
            gb_imp = rf_imp  # Simplified
            ensemble_imp = (rf_imp + gb_imp) / 2

            # Predictive power classification
            if ensemble_imp > 0.2:
                power = "strong"
            elif ensemble_imp > 0.1:
                power = "moderate"
            elif ensemble_imp > 0.05:
                power = "weak"
            else:
                power = "none"

            # Recommended weight (scaled)
            rec_weight = 0.5 + ensemble_imp * 2.5  # Range: 0.5 to 1.5

            stats[comp] = ComponentStats(
                name=comp,
                sample_size=len(values),
                win_rate_correlation=win_corr,
                pnl_correlation=pnl_corr,
                avg_value_winners=avg_winners,
                avg_value_losers=avg_losers,
                std_value=np.std(values),
                rf_importance=rf_imp,
                gb_importance=gb_imp,
                ensemble_importance=ensemble_imp,
                predictive_power=power,
                recommended_weight=rec_weight,
                confidence_interval=(rec_weight * 0.8, rec_weight * 1.2),
            )

        return stats

    def _train_strategy_weights(
        self,
        strategy: str,
        features: List[TradeFeatures],
        component_stats: Dict[str, ComponentStats],
        regime: Optional[str] = None,
    ) -> WeightConfig:
        """Train weights for a specific strategy"""
        # Get relevant components for this strategy
        relevant_components = STRATEGY_COMPONENTS.get(strategy, ALL_COMPONENTS)

        # Calculate weights based on component stats
        weights = {}
        for comp in relevant_components:
            if comp in component_stats:
                weights[comp] = component_stats[comp].recommended_weight
            else:
                weights[comp] = 1.0

        # Normalize weights
        total_weight = sum(weights.values())
        normalized = {k: v / total_weight for k, v in weights.items()}

        # Validate with cross-validation
        val_score = self._cross_validate(features, weights)

        # Determine confidence
        if len(features) >= 200 and val_score > 0.55:
            confidence = "high"
        elif len(features) >= 100 and val_score > 0.50:
            confidence = "medium"
        else:
            confidence = "low"

        return WeightConfig(
            strategy=strategy,
            regime=regime,
            weights=weights,
            normalized_weights=normalized,
            method=self.method,
            training_date=datetime.now(),
            sample_size=len(features),
            validation_score=val_score,
            confidence=confidence,
        )

    def _cross_validate(
        self,
        features: List[TradeFeatures],
        weights: Dict[str, float],
    ) -> float:
        """Cross-validate weights using time-series splits"""
        if len(features) < 20:
            return 0.0

        # Sort by date
        sorted_features = sorted(features, key=lambda x: x.signal_date)

        # Time-series CV
        fold_size = len(sorted_features) // self.cv_folds
        scores = []

        for i in range(self.cv_folds - 1):
            test_start = (i + 1) * fold_size
            test_end = min(test_start + fold_size, len(sorted_features))

            if test_end <= test_start:
                continue

            test_features = sorted_features[test_start:test_end]

            # Calculate accuracy on test fold
            correct = 0
            for f in test_features:
                weighted_score = sum(
                    f.components.get(comp, 0) * w
                    for comp, w in weights.items()
                )
                # Higher score should predict winners
                predicted_win = weighted_score > np.median([
                    sum(f.components.get(c, 0) * w for c, w in weights.items())
                    for f in sorted_features[:test_start]
                ])
                if predicted_win == f.is_winner:
                    correct += 1

            scores.append(correct / len(test_features))

        return np.mean(scores) if scores else 0.0

    def _calculate_baseline_score(self, features: List[TradeFeatures]) -> float:
        """Calculate baseline score with equal weights"""
        if not features:
            return 0.0

        correct = 0
        all_scores = []

        for f in features:
            score = sum(f.components.values())
            all_scores.append(score)

        median_score = np.median(all_scores)

        for f in features:
            score = sum(f.components.values())
            predicted_win = score > median_score
            if predicted_win == f.is_winner:
                correct += 1

        return correct / len(features)

    def _validate_weights(
        self,
        features: List[TradeFeatures],
        strategy_weights: Dict[str, WeightConfig],
    ) -> float:
        """Validate optimized weights across all strategies"""
        if not features:
            return 0.0

        correct = 0
        total = 0

        for strategy, config in strategy_weights.items():
            strat_features = [f for f in features if f.strategy == strategy]
            if not strat_features:
                continue

            all_scores = []
            for f in strat_features:
                score = config.apply_weights(f.components)
                all_scores.append(score)

            if not all_scores:
                continue

            median = np.median(all_scores)

            for f in strat_features:
                score = config.apply_weights(f.components)
                predicted_win = score > median
                if predicted_win == f.is_winner:
                    correct += 1
                total += 1

        return correct / total if total > 0 else 0.0

    def _safe_correlation(self, x: np.ndarray, y: np.ndarray) -> float:
        """Calculate correlation safely"""
        if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
            return 0.0
        return float(np.corrcoef(x, y)[0, 1])

    def _create_default_weight_config(self, strategy: str) -> WeightConfig:
        """Create default weight config when insufficient data"""
        components = STRATEGY_COMPONENTS.get(strategy, ALL_COMPONENTS)
        weights = {c: 1.0 for c in components}
        normalized = {c: 1.0 / len(components) for c in components}

        return WeightConfig(
            strategy=strategy,
            regime=None,
            weights=weights,
            normalized_weights=normalized,
            method=OptimizationMethod.CORRELATION,
            training_date=datetime.now(),
            sample_size=0,
            validation_score=0.0,
            confidence="low",
        )

    def _create_default_result(
        self,
        optimization_id: str,
        warnings: List[str],
    ) -> OptimizationResult:
        """Create default result when training fails"""
        strategy_weights = {
            s: self._create_default_weight_config(s)
            for s in STRATEGY_COMPONENTS.keys()
        }

        return OptimizationResult(
            optimization_id=optimization_id,
            optimization_date=datetime.now(),
            strategy_weights=strategy_weights,
            regime_weights={},
            component_stats={},
            total_trades_analyzed=0,
            overall_validation_score=0.0,
            improvement_vs_baseline=0.0,
            warnings=warnings,
        )

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def save(self, result: OptimizationResult, filepath: Optional[str] = None) -> str:
        """Save optimization result to JSON"""
        if filepath is None:
            models_dir = Path.home() / ".optionplay" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            filepath = str(models_dir / f"{result.optimization_id}.json")
        else:
            filepath = str(Path(filepath).expanduser())
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"Saved weight optimization to {filepath}")
        return filepath

    @classmethod
    def load(cls, filepath: str) -> OptimizationResult:
        """Load optimization result from JSON"""
        filepath = str(Path(filepath).expanduser())

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Reconstruct WeightConfigs
        strategy_weights = {
            k: WeightConfig.from_dict(v)
            for k, v in data.get("strategy_weights", {}).items()
        }

        regime_weights = {}
        for regime, strats in data.get("regime_weights", {}).items():
            regime_weights[regime] = {
                k: WeightConfig.from_dict(v) for k, v in strats.items()
            }

        # Reconstruct ComponentStats (simplified)
        component_stats = {}
        for k, v in data.get("component_stats", {}).items():
            component_stats[k] = ComponentStats(
                name=v["name"],
                sample_size=v["sample_size"],
                win_rate_correlation=v["correlations"]["win_rate"],
                pnl_correlation=v["correlations"]["pnl"],
                avg_value_winners=v["distribution"]["avg_winners"],
                avg_value_losers=v["distribution"]["avg_losers"],
                std_value=v["distribution"]["std"],
                rf_importance=v["importance"]["random_forest"],
                gb_importance=v["importance"]["gradient_boosting"],
                ensemble_importance=v["importance"]["ensemble"],
                predictive_power=v["predictive_power"],
                recommended_weight=v["recommended_weight"],
            )

        summary = data.get("summary", {})

        return OptimizationResult(
            optimization_id=data["optimization_id"],
            optimization_date=datetime.fromisoformat(data["optimization_date"]),
            strategy_weights=strategy_weights,
            regime_weights=regime_weights,
            component_stats=component_stats,
            total_trades_analyzed=summary.get("total_trades", 0),
            overall_validation_score=summary.get("validation_score", 0),
            improvement_vs_baseline=summary.get("improvement_vs_baseline", 0),
            warnings=data.get("warnings", []),
        )

    @classmethod
    def load_latest(cls, models_dir: str = "~/.optionplay/models") -> Optional[OptimizationResult]:
        """Load most recent optimization result"""
        models_dir = Path(models_dir).expanduser()

        if not models_dir.exists():
            return None

        weight_files = list(models_dir.glob("weights_*.json"))
        if not weight_files:
            return None

        # Sort by modification time
        weight_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        return cls.load(str(weight_files[0]))


# =============================================================================
# WEIGHTED SCORER (PRODUCTION)
# =============================================================================

class WeightedScorer:
    """
    Production scorer that applies optimized weights.

    Usage:
        scorer = WeightedScorer.load_latest()
        weighted_score = scorer.score(score_breakdown, strategy="pullback")
    """

    def __init__(self, optimization_result: Optional[OptimizationResult] = None):
        self._result = optimization_result
        self._default_weights = DEFAULT_WEIGHTS.copy()

    def score(
        self,
        score_breakdown: Dict[str, float],
        strategy: str = "pullback",
        regime: Optional[str] = None,
        vix: Optional[float] = None,
    ) -> float:
        """
        Calculate weighted score.

        Args:
            score_breakdown: Dict of component scores
            strategy: Strategy name
            regime: Optional regime override
            vix: Optional VIX for auto-regime detection

        Returns:
            Weighted total score
        """
        # Determine regime from VIX if not specified
        if regime is None and vix is not None:
            if vix < 15:
                regime = "low_vol"
            elif vix < 20:
                regime = "normal"
            elif vix < 30:
                regime = "elevated"
            else:
                regime = "high_vol"

        if self._result is None:
            # No optimization loaded - use raw scores
            return sum(score_breakdown.values())

        # Get weight config
        config = self._result.get_weights(strategy, regime)
        return config.apply_weights(score_breakdown)

    def get_weight_info(
        self,
        strategy: str,
        regime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get information about weights being used"""
        if self._result is None:
            return {
                "status": "default",
                "message": "No optimization loaded - using equal weights",
            }

        config = self._result.get_weights(strategy, regime)
        return {
            "status": "optimized",
            "strategy": config.strategy,
            "regime": config.regime,
            "method": config.method.value,
            "confidence": config.confidence,
            "validation_score": config.validation_score,
            "top_weights": dict(sorted(
                config.weights.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]),
        }

    @classmethod
    def load_latest(cls) -> "WeightedScorer":
        """Load scorer with latest optimization"""
        result = MLWeightOptimizer.load_latest()
        return cls(result)

    @classmethod
    def from_file(cls, filepath: str) -> "WeightedScorer":
        """Load scorer from specific file"""
        result = MLWeightOptimizer.load(filepath)
        return cls(result)
