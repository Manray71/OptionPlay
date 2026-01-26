# OptionPlay - Backtesting Module
# ================================

from .engine import (
    BacktestEngine,
    BacktestConfig,
    BacktestResult,
    TradeResult,
    TradeOutcome,
    ExitReason,
)
from .metrics import (
    PerformanceMetrics,
    calculate_metrics,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
)
from .simulator import (
    TradeSimulator,
    SimulatedTrade,
    PriceSimulator,
)
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
from .walk_forward import (
    WalkForwardTrainer,
    TrainingConfig,
    TrainingResult,
    EpochResult,
    format_training_summary,
)
from .reliability import (
    ReliabilityScorer,
    ReliabilityResult,
    ScorerConfig,
    create_scorer_from_latest_model,
    format_reliability_badge,
)
from .trade_tracker import (
    TradeTracker,
    TrackedTrade,
    TradeStats,
    TradeStatus,
    TradeOutcome as TrackerOutcome,  # Alias to avoid conflict with engine.TradeOutcome
    PriceBar,
    SymbolPriceData,
    VixDataPoint,
    format_trade_stats,
    create_tracker,
)
from .data_collector import (
    DataCollector,
    CollectionConfig,
    CollectionResult,
    format_collection_status,
    run_daily_collection,
    create_collector,
)

__all__ = [
    # Engine
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
    "TradeResult",
    "TradeOutcome",
    "ExitReason",
    # Metrics
    "PerformanceMetrics",
    "calculate_metrics",
    "calculate_sharpe_ratio",
    "calculate_max_drawdown",
    "calculate_profit_factor",
    # Simulator
    "TradeSimulator",
    "SimulatedTrade",
    "PriceSimulator",
    # Signal Validation
    "SignalValidator",
    "SignalValidationResult",
    "SignalReliability",
    "ScoreBucketStats",
    "ComponentCorrelation",
    "RegimeBucketStats",
    "StatisticalCalculator",
    "format_reliability_report",
    # Walk-Forward Training
    "WalkForwardTrainer",
    "TrainingConfig",
    "TrainingResult",
    "EpochResult",
    "format_training_summary",
    # Reliability Scoring
    "ReliabilityScorer",
    "ReliabilityResult",
    "ScorerConfig",
    "create_scorer_from_latest_model",
    "format_reliability_badge",
    # Trade Tracker
    "TradeTracker",
    "TrackedTrade",
    "TradeStats",
    "TradeStatus",
    "TrackerOutcome",
    "PriceBar",
    "SymbolPriceData",
    "VixDataPoint",
    "format_trade_stats",
    "create_tracker",
    # Data Collector
    "DataCollector",
    "CollectionConfig",
    "CollectionResult",
    "format_collection_status",
    "run_daily_collection",
    "create_collector",
]
