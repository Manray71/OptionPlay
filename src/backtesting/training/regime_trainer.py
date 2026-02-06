# OptionPlay - Regime Trainer (Re-export Stub)
# =============================================
# Refactored in Phase 6e:
# - DataPrep → training/data_prep.py
# - EpochRunner → training/epoch_runner.py
# - PerformanceAnalyzer → training/performance.py
# - ParameterOptimizer, ResultProcessor → training/optimizer.py
# - RegimeTrainer (Facade) → training/trainer.py
#
# This file re-exports everything for backward compatibility.

from .trainer import RegimeTrainer
from ..models.training_models import (
    RegimeTrainingConfig,
    RegimeTrainingResult,
    FullRegimeTrainingResult,
    RegimeEpochResult,
    StrategyPerformance,
)

__all__ = [
    "RegimeTrainer",
    "RegimeTrainingConfig",
    "RegimeTrainingResult",
    "FullRegimeTrainingResult",
    "RegimeEpochResult",
    "StrategyPerformance",
]
