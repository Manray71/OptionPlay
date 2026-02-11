# OptionPlay - Backtesting Simulation Package
# ============================================
# Options Simulator and Real Options Backtester

from .options_simulator import (
    EXIT_CODE_NAMES,
    OptionsSimulator,
)
from .options_simulator import SimulatorConfig as OptionsSimulatorConfig  # NumPy batch functions
from .options_simulator import (
    SpreadEntry,
    SpreadSnapshot,
    batch_calculate_pnl,
    batch_calculate_spread_values,
    batch_check_exit_signals,
    quick_spread_pnl,
)
from .real_options_backtester import (
    OUTCOME_DB_PATH,
    BacktestTradeRecord,
    OptionQuote,
    OptionsDatabase,
    OutcomeCalculator,
    RealOptionsBacktester,
    SetupFeatures,
)
from .real_options_backtester import (
    SpreadEntry as RealSpreadEntry,  # Phase 6: Component Score Training
)
from .real_options_backtester import (
    SpreadFinder,
    SpreadOutcome,
    SpreadOutcomeResult,
    analyze_winning_patterns,
    calculate_symbol_stability,
    create_outcome_database,
    get_blacklisted_symbols,
    get_outcome_statistics,
    get_recommended_symbols,
    get_symbol_stability_score,
    get_trades_without_scores,
    load_outcomes_dataframe,
    load_outcomes_for_training,
    load_outcomes_with_scores,
    quick_backtest,
    run_symbol_backtest,
    save_outcomes_to_db,
    train_component_weights_from_outcomes,
    train_outcome_predictor,
    update_trade_scores,
)

__all__ = [
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
    # Real Options Backtester (Historical Data)
    "RealOptionsBacktester",
    "OptionsDatabase",
    "SpreadFinder",
    "OutcomeCalculator",
    "OptionQuote",
    "RealSpreadEntry",
    "SpreadOutcome",
    "SpreadOutcomeResult",
    "SetupFeatures",
    "BacktestTradeRecord",
    "quick_backtest",
    "run_symbol_backtest",
    "create_outcome_database",
    "save_outcomes_to_db",
    "load_outcomes_for_training",
    "load_outcomes_dataframe",
    "get_outcome_statistics",
    "train_outcome_predictor",
    "analyze_winning_patterns",
    "calculate_symbol_stability",
    "get_recommended_symbols",
    "get_blacklisted_symbols",
    "get_symbol_stability_score",
    "OUTCOME_DB_PATH",
    # Phase 6: Component Score Training
    "get_trades_without_scores",
    "update_trade_scores",
    "load_outcomes_with_scores",
    "train_component_weights_from_outcomes",
]
