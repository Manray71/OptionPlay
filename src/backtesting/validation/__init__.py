# OptionPlay - Backtesting Validation Package
# ============================================
# Signal Validation and Reliability Scoring

from .signal_validation import (
    SignalValidator,
    SignalValidationResult,
    SignalReliability,
    ScoreBucketStats,
    ComponentCorrelation,
    RegimeBucketStats,
    StatisticalCalculator,
    format_reliability_report,
)
from .reliability import (
    ReliabilityScorer,
    ReliabilityResult,
    ScorerConfig,
    create_scorer_from_latest_model,
    format_reliability_badge,
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
