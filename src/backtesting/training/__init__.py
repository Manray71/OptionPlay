# OptionPlay - Backtesting Training Package
# ==========================================
# Walk-Forward Training, Regime Training, ML Weight Optimization
#
# Phase 6e: RegimeTrainer broken into sub-modules:
#   data_prep.py, epoch_runner.py, performance.py, optimizer.py, trainer.py

from .walk_forward import (
    WalkForwardTrainer,
    TrainingConfig,
    TrainingResult,
    EpochResult,
    format_training_summary,
)
from .regime_trainer import (
    RegimeTrainer,
    RegimeTrainingConfig,
    RegimeTrainingResult,
    FullRegimeTrainingResult,
    RegimeEpochResult,
    StrategyPerformance,
)
from .ml_weight_optimizer import (
    MLWeightOptimizer,
    OptimizationMethod,
    OptimizationResult,
    WeightConfig,
    ComponentStats,
    WeightedScorer,
    TradeFeatures,
    FeatureExtractor,
    STRATEGY_COMPONENTS,
    ALL_COMPONENTS,
    DEFAULT_WEIGHTS,
)
from .data_prep import DataPrep
from .epoch_runner import EpochRunner
from .performance import PerformanceAnalyzer
from .optimizer import ParameterOptimizer, ResultProcessor

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
    # Phase 6e Sub-Modules
    "DataPrep",
    "EpochRunner",
    "PerformanceAnalyzer",
    "ParameterOptimizer",
    "ResultProcessor",
]
