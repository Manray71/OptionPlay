# OptionPlay - Backtesting Core Package
# ======================================
# Engine, Metrics, Simulator, Database, and Spread Engine

from .database import (
    DB_PATH,
    OptionsDatabase,
)
from .engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    ExitReason,
    TradeOutcome,
    TradeResult,
)
from .metrics import (
    PerformanceMetrics,
    calculate_equity_stats,
    calculate_kelly_criterion,
    calculate_max_drawdown,
    calculate_metrics,
    calculate_profit_factor,
    calculate_risk_of_ruin,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_streaks,
)
from .simulator import (
    PriceSimulator,
    SimulatedTrade,
    TradeSimulator,
)
from .spread_engine import (
    OutcomeCalculator,
    SpreadFinder,
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
