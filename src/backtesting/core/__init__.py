# OptionPlay - Backtesting Core Package
# ======================================
# Engine, Metrics, and Simulator

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
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_kelly_criterion,
    calculate_streaks,
    calculate_equity_stats,
    calculate_risk_of_ruin,
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
    "calculate_sortino_ratio",
    "calculate_max_drawdown",
    "calculate_profit_factor",
    "calculate_kelly_criterion",
    "calculate_streaks",
    "calculate_equity_stats",
    "calculate_risk_of_ruin",
    # Simulator
    "TradeSimulator",
    "SimulatedTrade",
    "PriceSimulator",
]
