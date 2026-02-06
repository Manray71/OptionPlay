# OptionPlay - Real Options Backtester (Re-export Stub)
# ======================================================
# Refactored in Phase 6c:
# - OptionsDatabase → core/database.py
# - SpreadFinder, OutcomeCalculator → core/spread_engine.py
# - RealOptionsBacktester + functions → simulation/options_backtest.py
#
# This file re-exports everything for backward compatibility.

from ..models.outcomes import (
    SpreadOutcome,
    OptionQuote,
    SpreadEntry,
    SpreadOutcomeResult,
    SetupFeatures,
    BacktestTradeRecord,
)
from ..core.database import OptionsDatabase, DB_PATH
from ..core.spread_engine import SpreadFinder, OutcomeCalculator
from .options_backtest import (
    RealOptionsBacktester,
    quick_backtest,
    run_symbol_backtest,
    OUTCOME_DB_PATH,
    create_outcome_database,
    save_outcomes_to_db,
    load_outcomes_for_training,
    load_outcomes_dataframe,
    train_outcome_predictor,
    analyze_winning_patterns,
    calculate_symbol_stability,
    get_recommended_symbols,
    get_blacklisted_symbols,
    get_symbol_stability_score,
    get_outcome_statistics,
    get_trades_without_scores,
    update_trade_scores,
    load_outcomes_with_scores,
    train_component_weights_from_outcomes,
)

__all__ = [
    # Models (from models.outcomes)
    'SpreadOutcome',
    'OptionQuote',
    'SpreadEntry',
    'SpreadOutcomeResult',
    'SetupFeatures',
    'BacktestTradeRecord',
    # Database (from core.database)
    'OptionsDatabase',
    'DB_PATH',
    # Spread Engine (from core.spread_engine)
    'SpreadFinder',
    'OutcomeCalculator',
    # Backtester (from simulation.options_backtest)
    'RealOptionsBacktester',
    'quick_backtest',
    'run_symbol_backtest',
    'OUTCOME_DB_PATH',
    'create_outcome_database',
    'save_outcomes_to_db',
    'load_outcomes_for_training',
    'load_outcomes_dataframe',
    'train_outcome_predictor',
    'analyze_winning_patterns',
    'calculate_symbol_stability',
    'get_recommended_symbols',
    'get_blacklisted_symbols',
    'get_symbol_stability_score',
    'get_outcome_statistics',
    'get_trades_without_scores',
    'update_trade_scores',
    'load_outcomes_with_scores',
    'train_component_weights_from_outcomes',
]
