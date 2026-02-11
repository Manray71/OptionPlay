# OptionPlay - Backtesting Training Package
# ==========================================
# Walk-Forward Training, Regime Training, ML Weight Optimization
#
# Phase 6e: RegimeTrainer broken into sub-modules:
#   data_prep.py, epoch_runner.py, performance.py, optimizer.py, trainer.py

from .data_prep import DataPrep
from .epoch_runner import EpochRunner
from .ml_weight_optimizer import (
    ALL_COMPONENTS,
    DEFAULT_WEIGHTS,
    STRATEGY_COMPONENTS,
    ComponentStats,
    FeatureExtractor,
    MLWeightOptimizer,
    OptimizationMethod,
    OptimizationResult,
    TradeFeatures,
    WeightConfig,
    WeightedScorer,
)
from .optimizer import ParameterOptimizer, ResultProcessor
from .performance import PerformanceAnalyzer
from .regime_trainer import (
    FullRegimeTrainingResult,
    RegimeEpochResult,
    RegimeTrainer,
    RegimeTrainingConfig,
    RegimeTrainingResult,
    StrategyPerformance,
)
from .strategy_weight_trainer import (
    STRATEGY_OBJECTIVES,
    StrategyTrainingConfig,
    StrategyTrainingResult,
    StrategyWeightTrainer,
)
from .walk_forward import (
    EpochResult,
    TrainingConfig,
    TrainingResult,
    WalkForwardTrainer,
    format_training_summary,
)

__all__ = [
    # Walk-Forward Training
    "WalkForwardTrainer",
    "TrainingConfig",
    "TrainingResult",
    "EpochResult",
    "format_training_summary",
    # Regime Training
    "RegimeTrainer",
    "RegimeTrainingConfig",
    "RegimeTrainingResult",
    "FullRegimeTrainingResult",
    "RegimeEpochResult",
    "StrategyPerformance",
    # ML Weight Optimizer
    "MLWeightOptimizer",
    "OptimizationMethod",
    "OptimizationResult",
    "WeightConfig",
    "ComponentStats",
    "WeightedScorer",
    "TradeFeatures",
    "FeatureExtractor",
    "STRATEGY_COMPONENTS",
    "ALL_COMPONENTS",
    "DEFAULT_WEIGHTS",
    # v3: Strategy Weight Trainer
    "StrategyWeightTrainer",
    "StrategyTrainingConfig",
    "StrategyTrainingResult",
    "STRATEGY_OBJECTIVES",
    # Phase 6e Sub-Modules
    "DataPrep",
    "EpochRunner",
    "PerformanceAnalyzer",
    "ParameterOptimizer",
    "ResultProcessor",
]
