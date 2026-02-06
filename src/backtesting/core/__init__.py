# OptionPlay - Backtesting Core Package
# ======================================
# Engine, Metrics, Simulator, Database, and Spread Engine

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
from .database import (
    OptionsDatabase,
    DB_PATH,
)
from .spread_engine import (
    SpreadFinder,
    OutcomeCalculator,
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
    # Database (Phase 6c)
    "OptionsDatabase",
    "DB_PATH",
    # Spread Engine (Phase 6c)
    "SpreadFinder",
    "OutcomeCalculator",
]
