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
from .options_simulator import (
    OptionsSimulator,
    SpreadEntry,
    SpreadSnapshot,
    SimulatorConfig as OptionsSimulatorConfig,
    quick_spread_pnl,
    # NumPy batch functions
    batch_calculate_spread_values,
    batch_calculate_pnl,
    batch_check_exit_signals,
    EXIT_CODE_NAMES,
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
from .regime_config import (
    RegimeConfig,
    RegimeType,
    RegimeBoundaryMethod,
    RegimeState,
    RegimeTransition,
    FIXED_REGIMES,
    create_percentile_regimes,
    get_regime_for_vix,
    save_regimes,
    load_regimes,
    format_regime_summary,
    # Trained Model Support
    TrainedModelLoader,
    TrainedRegimeConfig,
    TrainedStrategyConfig,
    get_trained_model_loader,
    load_trained_regimes,
    REGIME_NAME_MAPPING,
)
from .regime_trainer import (
    RegimeTrainer,
    RegimeTrainingConfig,
    RegimeTrainingResult,
    FullRegimeTrainingResult,
    RegimeEpochResult,
    StrategyPerformance,
)
from .regime_model import (
    RegimeModel,
    TradingParameters,
    TradeDecision,
    RegimeStatus,
    get_regime_recommendation,
    format_regime_status,
)
from .ml_weight_optimizer import (
    MLWeightOptimizer,
    OptimizationMethod,
    OptimizationResult,
    WeightConfig,
    ComponentStats,
    WeightedScorer,
    STRATEGY_COMPONENTS,
    ALL_COMPONENTS,
)
from .ensemble_selector import (
    EnsembleSelector,
    MetaLearner,
    StrategyRotationEngine,
    StrategyScore,
    EnsembleRecommendation,
    SymbolPerformance,
    RotationState,
    SelectionMethod,
    RotationTrigger,
    create_strategy_score,
    format_ensemble_summary,
    STRATEGIES,
    DEFAULT_REGIME_PREFERENCES,
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
    # Options Simulator (Black-Scholes)
    "OptionsSimulator",
    "SpreadEntry",
    "SpreadSnapshot",
    "OptionsSimulatorConfig",
    "quick_spread_pnl",
    # NumPy batch functions
    "batch_calculate_spread_values",
    "batch_calculate_pnl",
    "batch_check_exit_signals",
    "EXIT_CODE_NAMES",
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
    # Regime Config
    "RegimeConfig",
    "RegimeType",
    "RegimeBoundaryMethod",
    "RegimeState",
    "RegimeTransition",
    "FIXED_REGIMES",
    "create_percentile_regimes",
    "get_regime_for_vix",
    "save_regimes",
    "load_regimes",
    "format_regime_summary",
    # Trained Model Support
    "TrainedModelLoader",
    "TrainedRegimeConfig",
    "TrainedStrategyConfig",
    "get_trained_model_loader",
    "load_trained_regimes",
    "REGIME_NAME_MAPPING",
    # Regime Training
    "RegimeTrainer",
    "RegimeTrainingConfig",
    "RegimeTrainingResult",
    "FullRegimeTrainingResult",
    "RegimeEpochResult",
    "StrategyPerformance",
    # Regime Model (Production)
    "RegimeModel",
    "TradingParameters",
    "TradeDecision",
    "RegimeStatus",
    "get_regime_recommendation",
    "format_regime_status",
    # ML Weight Optimizer
    "MLWeightOptimizer",
    "OptimizationMethod",
    "OptimizationResult",
    "WeightConfig",
    "ComponentStats",
    "WeightedScorer",
    "STRATEGY_COMPONENTS",
    "ALL_COMPONENTS",
    # Ensemble Strategy Selector
    "EnsembleSelector",
    "MetaLearner",
    "StrategyRotationEngine",
    "StrategyScore",
    "EnsembleRecommendation",
    "SymbolPerformance",
    "RotationState",
    "SelectionMethod",
    "RotationTrigger",
    "create_strategy_score",
    "format_ensemble_summary",
    "STRATEGIES",
    "DEFAULT_REGIME_PREFERENCES",
]
