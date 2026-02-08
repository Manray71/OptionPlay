"""
Ensemble Strategy Selection Data Models
========================================

Extracted from ensemble_selector.py (Phase 6a).

Contains:
- SelectionMethod: Enum for strategy selection methods
- RotationTrigger: Enum for rotation triggers
- StrategyScore: Score from a single strategy
- EnsembleRecommendation: Recommendation from ensemble selector
- SymbolPerformance: Historical performance tracking
- RotationState: State tracking for strategy rotation
- Constants: STRATEGIES, DEFAULT_REGIME_PREFERENCES, etc.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# =============================================================================
# CONSTANTS
# =============================================================================

STRATEGIES = ["pullback", "bounce", "ath_breakout", "earnings_dip", "trend_continuation"]

# Default strategy preferences by regime (based on typical performance patterns)
# Updated 2026-01-28 based on training results (52,935 trades):
#   pullback:     55.8% win rate
#   bounce:       54.4% win rate
#   ath_breakout: 55.1% win rate
#   earnings_dip: 55.5% win rate
DEFAULT_REGIME_PREFERENCES = {
    "low_vol": {
        "pullback": 0.22,
        "bounce": 0.19,
        "ath_breakout": 0.22,  # Breakouts work well in low vol
        "earnings_dip": 0.19,
        "trend_continuation": 0.18,  # Trends thrive in low vol
    },
    "normal": {
        "pullback": 0.23,
        "bounce": 0.18,
        "ath_breakout": 0.22,
        "earnings_dip": 0.19,
        "trend_continuation": 0.18,
    },
    "elevated": {
        "pullback": 0.28,  # Mean reversion stronger
        "bounce": 0.28,
        "ath_breakout": 0.18,  # Breakouts less reliable
        "earnings_dip": 0.18,
        "trend_continuation": 0.08,  # Trends weaken in elevated vol
    },
    "high_vol": {
        "pullback": 0.34,  # Only high-conviction plays
        "bounce": 0.34,
        "ath_breakout": 0.14,
        "earnings_dip": 0.14,
        "trend_continuation": 0.04,  # Nearly disabled at high vol
    },
}

# Feature impact from training (2026-01-28):
# - VWAP medium: 59.8% WR (best), high: 54.8%, low: 53.5%
# - Market Context: downtrend: 58.1%, sideways: 59.2%, uptrend: 53.5%
# - Sector: favorable: 74.9% WR (!), neutral: 54.8%, unfavorable: 52.5%
FEATURE_IMPACT = {
    "vwap": {"high": 0.0, "medium": 0.15, "low": -0.05},  # Boost for medium VWAP
    "market_context": {"downtrend": 0.10, "sideways": 0.12, "uptrend": 0.0},
    "sector": {"favorable": 0.40, "neutral": 0.0, "unfavorable": -0.10},  # Big boost for favorable sector
}

# Symbol Clustering Results (2026-01-28):
# Clusters based on volatility regime, price tier, and trend bias
# Key insight: Steady (low vol) stocks perform best with Bounce strategy (80% WR)
CLUSTER_STRATEGY_MAP = {
    # Steady (low vol) clusters - Bounce works best (80% WR)
    "low_medium_mean_reverting": {"strategy": "bounce", "win_rate": 80.9, "confidence": 1.0},
    "low_high_mean_reverting": {"strategy": "bounce", "win_rate": 80.0, "confidence": 0.7},
    "low_low_mean_reverting": {"strategy": "earnings_dip", "win_rate": 76.5, "confidence": 0.6},

    # Moderate (medium vol) clusters
    "medium_medium_mean_reverting": {"strategy": "bounce", "win_rate": 64.3, "confidence": 1.0},
    "medium_high_mean_reverting": {"strategy": "ath_breakout", "win_rate": 65.4, "confidence": 1.0},
    "medium_low_mean_reverting": {"strategy": "earnings_dip", "win_rate": 62.3, "confidence": 0.9},

    # Volatile (high vol) clusters - ATH Breakout or Bounce
    "high_medium_mean_reverting": {"strategy": "ath_breakout", "win_rate": 54.0, "confidence": 1.0},
    "high_high_mean_reverting": {"strategy": "bounce", "win_rate": 54.6, "confidence": 0.9},
    "high_low_mean_reverting": {"strategy": "ath_breakout", "win_rate": 42.5, "confidence": 0.8},
}

# Sector-specific strategy preferences (trained 2026-01-28)
# Based on historical performance per sector
SECTOR_STRATEGY_MAP = {
    "Utilities": {"strategy": "earnings_dip", "win_rate": 90.0, "confidence": 1.0},
    "Energy": {"strategy": "bounce", "win_rate": 76.2, "confidence": 0.9},
    "Healthcare": {"strategy": "pullback", "win_rate": 59.6, "confidence": 0.8},
    "Consumer Staples": {"strategy": "pullback", "win_rate": 60.4, "confidence": 0.8},
    "Industrials": {"strategy": "ath_breakout", "win_rate": 58.6, "confidence": 0.85},
    "Financials": {"strategy": "earnings_dip", "win_rate": 50.4, "confidence": 0.7},
    "Real Estate": {"strategy": "bounce", "win_rate": 53.7, "confidence": 0.7},
    "Communication Services": {"strategy": "pullback", "win_rate": 50.9, "confidence": 0.65},
    "Consumer Discretionary": {"strategy": "ath_breakout", "win_rate": 52.3, "confidence": 0.7},
    "Materials": {"strategy": "ath_breakout", "win_rate": 50.0, "confidence": 0.6},
    "Technology": {"strategy": "ath_breakout", "win_rate": 43.2, "confidence": 0.5},  # Lower confidence
}

# Default component weights (baseline)
DEFAULT_COMPONENT_WEIGHTS = {
    "rsi": 1.0,
    "support": 1.0,
    "fibonacci": 1.0,
    "ma": 1.0,
    "trend": 1.0,
    "volume": 1.0,
    "macd": 1.0,
    "stochastic": 1.0,
    "keltner": 1.0,
    "ath": 1.0,
    "bounce": 1.0,
}

# Minimum score threshold per strategy for consideration
MIN_SCORE_THRESHOLDS = {
    "pullback": 4.0,
    "bounce": 4.0,
    "ath_breakout": 5.0,
    "earnings_dip": 5.0,
    "trend_continuation": 5.0,
}


# =============================================================================
# ENUMS
# =============================================================================

class SelectionMethod(str, Enum):
    """Method for selecting strategy"""
    BEST_SCORE = "best_score"              # Highest raw score
    WEIGHTED_BEST = "weighted_best"         # Regime-weighted best
    ENSEMBLE_VOTE = "ensemble_vote"         # Voting across methods
    META_LEARNER = "meta_learner"           # ML-based selection
    CONFIDENCE_WEIGHTED = "confidence_weighted"  # Confidence-weighted combination


class RotationTrigger(str, Enum):
    """Trigger for strategy rotation"""
    PERFORMANCE_DECAY = "performance_decay"
    REGIME_CHANGE = "regime_change"
    TIME_BASED = "time_based"
    MANUAL = "manual"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class StrategyScore:
    """Score from a single strategy"""
    strategy: str
    raw_score: float
    weighted_score: float  # After ML weights applied
    confidence: float  # 0-1 confidence in this score
    breakdown: Dict[str, float]  # Component breakdown

    @property
    def adjusted_score(self) -> float:
        """Score adjusted by confidence"""
        return self.weighted_score * self.confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "raw_score": round(self.raw_score, 2),
            "weighted_score": round(self.weighted_score, 2),
            "confidence": round(self.confidence, 3),
            "adjusted_score": round(self.adjusted_score, 2),
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
        }


@dataclass
class EnsembleRecommendation:
    """Recommendation from ensemble selector"""
    symbol: str
    timestamp: datetime

    # Primary recommendation
    recommended_strategy: str
    recommended_score: float
    selection_method: SelectionMethod

    # All strategy scores
    strategy_scores: Dict[str, StrategyScore]

    # Ensemble combination (if using weighted approach)
    ensemble_score: float
    ensemble_confidence: float

    # Context
    regime: Optional[str]
    vix: Optional[float]

    # Reasoning
    selection_reason: str
    alternative_strategies: List[str]

    # Risk assessment
    diversification_benefit: float  # 0-1 score
    strategy_correlation: float  # Correlation between top strategies

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "recommendation": {
                "strategy": self.recommended_strategy,
                "score": round(self.recommended_score, 2),
                "method": self.selection_method.value,
                "reason": self.selection_reason,
            },
            "ensemble": {
                "score": round(self.ensemble_score, 2),
                "confidence": round(self.ensemble_confidence, 3),
            },
            "all_strategies": {
                k: v.to_dict() for k, v in self.strategy_scores.items()
            },
            "alternatives": self.alternative_strategies,
            "context": {
                "regime": self.regime,
                "vix": self.vix,
            },
            "risk": {
                "diversification_benefit": round(self.diversification_benefit, 3),
                "strategy_correlation": round(self.strategy_correlation, 3),
            },
        }

    def summary(self) -> str:
        """Format as readable summary"""
        lines = [
            f"Ensemble Recommendation: {self.symbol}",
            f"  Strategy:   {self.recommended_strategy.upper()} (Score: {self.recommended_score:.1f})",
            f"  Method:     {self.selection_method.value}",
            f"  Confidence: {self.ensemble_confidence:.0%}",
            f"  Regime:     {self.regime or 'unknown'}",
            "",
            "  All Strategies:",
        ]

        for strat, score in sorted(
            self.strategy_scores.items(),
            key=lambda x: x[1].adjusted_score,
            reverse=True
        ):
            marker = " *" if strat == self.recommended_strategy else ""
            lines.append(
                f"    {strat:<15} {score.weighted_score:>6.1f} "
                f"(conf: {score.confidence:.0%}){marker}"
            )

        if self.alternative_strategies:
            lines.append(f"\n  Alternatives: {', '.join(self.alternative_strategies)}")

        return "\n".join(lines)


@dataclass
class SymbolPerformance:
    """Historical performance tracking for a symbol"""
    symbol: str

    # Per-strategy win rates
    strategy_win_rates: Dict[str, float] = field(default_factory=dict)
    strategy_sample_sizes: Dict[str, int] = field(default_factory=dict)

    # Per-strategy average returns
    strategy_avg_returns: Dict[str, float] = field(default_factory=dict)

    # Best strategy historically
    best_strategy: Optional[str] = None
    best_strategy_confidence: float = 0.0

    # Last update
    last_updated: Optional[datetime] = None

    def get_preference_weights(self) -> Dict[str, float]:
        """Get strategy preference weights based on history"""
        if not self.strategy_win_rates:
            return {s: 1.0 / len(STRATEGIES) for s in STRATEGIES}

        # Weight by win rate * sqrt(sample size)
        weights = {}
        for strat in STRATEGIES:
            win_rate = self.strategy_win_rates.get(strat, 0.5)
            samples = self.strategy_sample_sizes.get(strat, 0)

            if samples > 0:
                # Bayesian-style shrinkage toward 50% with low samples
                adjusted_wr = (win_rate * samples + 0.5 * 10) / (samples + 10)
                weights[strat] = adjusted_wr * np.sqrt(samples)
            else:
                weights[strat] = 0.5

        # Normalize
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        else:
            weights = {s: 0.25 for s in STRATEGIES}

        return weights

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "win_rates": {k: round(v, 3) for k, v in self.strategy_win_rates.items()},
            "sample_sizes": self.strategy_sample_sizes,
            "avg_returns": {k: round(v, 2) for k, v in self.strategy_avg_returns.items()},
            "best_strategy": self.best_strategy,
            "best_strategy_confidence": round(self.best_strategy_confidence, 3),
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


@dataclass
class RotationState:
    """State tracking for strategy rotation"""
    current_preferences: Dict[str, float]  # Current strategy weights
    last_rotation_date: date
    rotation_reason: Optional[RotationTrigger]

    # Performance tracking
    recent_win_rates: Dict[str, List[float]]  # Rolling window
    consecutive_losses: Dict[str, int]

    # Rotation history
    rotation_history: List[Dict[str, Any]] = field(default_factory=list)

    def should_rotate(
        self,
        current_date: date,
        performance_threshold: float = 0.40,
        max_days: int = 30,
    ) -> Tuple[bool, Optional[RotationTrigger]]:
        """Check if rotation is needed"""
        days_since_rotation = (current_date - self.last_rotation_date).days

        # Time-based rotation
        if days_since_rotation >= max_days:
            return True, RotationTrigger.TIME_BASED

        # Performance-based rotation
        for strat, recent_wrs in self.recent_win_rates.items():
            if len(recent_wrs) >= 10:
                recent_wr = np.mean(recent_wrs[-10:])
                if recent_wr < performance_threshold:
                    return True, RotationTrigger.PERFORMANCE_DECAY

        # Consecutive losses trigger
        for strat, losses in self.consecutive_losses.items():
            if losses >= 5:  # 5 consecutive losses triggers review
                return True, RotationTrigger.PERFORMANCE_DECAY

        return False, None


def create_strategy_score(
    strategy: str,
    raw_score: float,
    breakdown: Dict[str, float],
    weighted_score: Optional[float] = None,
    confidence: Optional[float] = None,
) -> StrategyScore:
    """
    Helper to create StrategyScore from scan results.

    Args:
        strategy: Strategy name
        raw_score: Raw score from scanner
        breakdown: Component breakdown dict
        weighted_score: Optional weighted score (uses raw if not provided)
        confidence: Optional confidence (calculated from components if not provided)

    Returns:
        StrategyScore object
    """
    if weighted_score is None:
        weighted_score = raw_score

    if confidence is None:
        # Calculate confidence based on how many components scored
        max_possible = len(breakdown) * 2  # Assuming max 2 per component
        if max_possible > 0:
            confidence = min(1.0, raw_score / max_possible)
        else:
            confidence = 0.5

    return StrategyScore(
        strategy=strategy,
        raw_score=raw_score,
        weighted_score=weighted_score,
        confidence=confidence,
        breakdown=breakdown,
    )


def format_ensemble_summary(recommendation: EnsembleRecommendation) -> str:
    """Format ensemble recommendation as readable string"""
    return recommendation.summary()
