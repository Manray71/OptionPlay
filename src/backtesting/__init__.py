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
]
