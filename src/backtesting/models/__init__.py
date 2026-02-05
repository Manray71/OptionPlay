# OptionPlay - Backtesting Models Package
# ========================================
# Regime Configuration, Regime Model, Ensemble Selector, Outcomes, Training Models

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
from .regime_model import (
    RegimeModel,
    TradingParameters,
    TradeDecision,
    RegimeStatus,
    get_regime_recommendation,
    format_regime_status,
)
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
from .ensemble_selector import (
    EnsembleSelector,
    MetaLearner,
    StrategyRotationEngine,
)
from .outcomes import (
    SpreadOutcome,
    OptionQuote,
    SpreadEntry as RealSpreadEntry,
    SpreadOutcomeResult,
    SetupFeatures,
    BacktestTradeRecord,
)
from .training_models import (
    RegimeTrainingConfig,
    StrategyPerformance,
    RegimeEpochResult,
    RegimeTrainingResult,
    FullRegimeTrainingResult,
)

__all__ = [
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
    # Regime Model
    "RegimeModel",
    "TradingParameters",
    "TradeDecision",
    "RegimeStatus",
    "get_regime_recommendation",
    "format_regime_status",
    # Ensemble Models (Data Classes)
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
    "FEATURE_IMPACT",
    "CLUSTER_STRATEGY_MAP",
    "SECTOR_STRATEGY_MAP",
    "DEFAULT_COMPONENT_WEIGHTS",
    "MIN_SCORE_THRESHOLDS",
    # Ensemble Selector (Logic Classes)
    "EnsembleSelector",
    "MetaLearner",
    "StrategyRotationEngine",
    # Outcome Models
    "SpreadOutcome",
    "OptionQuote",
    "RealSpreadEntry",
    "SpreadOutcomeResult",
    "SetupFeatures",
    "BacktestTradeRecord",
    # Training Models
    "RegimeTrainingConfig",
    "StrategyPerformance",
    "RegimeEpochResult",
    "RegimeTrainingResult",
    "FullRegimeTrainingResult",
]
