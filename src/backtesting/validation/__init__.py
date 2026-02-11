# OptionPlay - Backtesting Validation Package
# ============================================
# Signal Validation and Reliability Scoring

from .reliability import (
    ReliabilityResult,
    ReliabilityScorer,
    ScorerConfig,
    create_scorer_from_latest_model,
    format_reliability_badge,
)
from .signal_validation import (
    ComponentCorrelation,
    RegimeBucketStats,
    ScoreBucketStats,
    SignalReliability,
    SignalValidationResult,
    SignalValidator,
    StatisticalCalculator,
    format_reliability_report,
)

__all__ = [
    # Signal Validation
    "SignalValidator",
    "SignalValidationResult",
    "SignalReliability",
    "ScoreBucketStats",
    "ComponentCorrelation",
    "RegimeBucketStats",
    "StatisticalCalculator",
    "format_reliability_report",
    # Reliability
    "ReliabilityScorer",
    "ReliabilityResult",
    "ScorerConfig",
    "create_scorer_from_latest_model",
    "format_reliability_badge",
]
