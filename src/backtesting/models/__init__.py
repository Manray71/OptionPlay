# OptionPlay - Backtesting Models Package
# ========================================
# Regime Configuration, Regime Model, Ensemble Selector, Outcomes, Training Models

from .ensemble_models import (  # Constants; Enums; Data Classes; Functions
    CLUSTER_STRATEGY_MAP,
    DEFAULT_COMPONENT_WEIGHTS,
    DEFAULT_REGIME_PREFERENCES,
    FEATURE_IMPACT,
    MIN_SCORE_THRESHOLDS,
    SECTOR_STRATEGY_MAP,
    STRATEGIES,
    EnsembleRecommendation,
    RotationState,
    RotationTrigger,
    SelectionMethod,
    StrategyScore,
    SymbolPerformance,
    create_strategy_score,
    format_ensemble_summary,
)
from .ensemble_selector import (
    EnsembleSelector,
    MetaLearner,
    StrategyRotationEngine,
)
from .outcomes import (
    BacktestTradeRecord,
    OptionQuote,
    SetupFeatures,
)
from .outcomes import SpreadEntry as RealSpreadEntry
from .outcomes import (
    SpreadOutcome,
    SpreadOutcomeResult,
)
from .regime_config import (  # Trained Model Support
    FIXED_REGIMES,
    REGIME_NAME_MAPPING,
    RegimeBoundaryMethod,
    RegimeConfig,
    RegimeState,
    RegimeTransition,
    RegimeType,
    TrainedModelLoader,
    TrainedRegimeConfig,
    TrainedStrategyConfig,
    create_percentile_regimes,
    format_regime_summary,
    get_regime_for_vix,
    get_trained_model_loader,
    load_regimes,
    load_trained_regimes,
    save_regimes,
)
from .regime_model import (
    RegimeModel,
    RegimeStatus,
    TradeDecision,
    TradingParameters,
    format_regime_status,
    get_regime_recommendation,
)
from .training_models import (
    FullRegimeTrainingResult,
    RegimeEpochResult,
    RegimeTrainingConfig,
    RegimeTrainingResult,
    StrategyPerformance,
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
