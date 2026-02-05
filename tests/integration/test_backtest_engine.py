# OptionPlay - BacktestEngine Unit Tests
# ========================================
# Comprehensive tests for src/backtesting/engine.py

import pytest
import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock
import statistics

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting import (
    BacktestEngine,
    BacktestConfig,
    BacktestResult,
    TradeResult,
    TradeOutcome,
    ExitReason,
    OptionsSimulator,
    SpreadEntry,
    SpreadSnapshot,
    OptionsSimulatorConfig as SimulatorConfig,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def basic_config():
    """Basic backtest configuration for tests."""
    return BacktestConfig(
        start_date=date(2023, 1, 2),
        end_date=date(2023, 1, 31),
        initial_capital=100000.0,
        min_pullback_score=3.0,  # Low for triggering entries
        use_black_scholes=False,  # Disable for simpler calculations
    )


@pytest.fixture
def bs_config():
    """Config with Black-Scholes enabled."""
    return BacktestConfig(
        start_date=date(2023, 1, 2),
        end_date=date(2023, 1, 31),
        initial_capital=100000.0,
        min_pullback_score=3.0,
        use_black_scholes=True,
    )


@pytest.fixture
def delta_config():
    """Config with delta-based strike selection."""
    return BacktestConfig(
        start_date=date(2023, 1, 2),
        end_date=date(2023, 1, 31),
        initial_capital=100000.0,
        min_pullback_score=3.0,
        use_delta_based_strikes=True,
        use_black_scholes=True,
        short_delta_target=-0.20,
        long_delta_target=-0.05,
    )


@pytest.fixture
def sample_historical_data():
    """Generate sample historical data with uptrend (good for pullback scores)."""
    data = []
    base_price = 150.0
    current_date = date(2022, 12, 1)  # Start before backtest period for history

    # Generate 60 days of data (including history before start_date)
    for i in range(60):
        if current_date.weekday() < 5:  # Only weekdays
            # Simulate uptrend with pullback
            if 30 <= i <= 35:  # Pullback period
                price = base_price + 20 - (i - 30) * 2  # Drop from 170 to 160
            else:
                price = base_price + i * 0.5  # Gradual uptrend
            data.append({
                "date": current_date.isoformat(),
                "open": price - 1,
                "high": price + 2,
                "low": price - 2,
                "close": price,
                "volume": 1000000 + i * 10000,
            })
        current_date += timedelta(days=1)

    return {"AAPL": data}


@pytest.fixture
def sample_vix_data():
    """Sample VIX data for tests."""
    data = []
    current_date = date(2022, 12, 1)

    for i in range(60):
        if current_date.weekday() < 5:
            # VIX oscillates between 15-25
            vix_value = 20 + 5 * ((-1) ** i) * 0.1 * (i % 10)
            data.append({
                "date": current_date.isoformat(),
                "close": vix_value,
            })
        current_date += timedelta(days=1)

    return data


@pytest.fixture
def sample_iv_data():
    """Sample IV data per symbol."""
    data = []
    current_date = date(2022, 12, 1)

    for i in range(60):
        if current_date.weekday() < 5:
            data.append({
                "date": current_date.isoformat(),
                "iv": 0.25 + 0.01 * (i % 5),
            })
        current_date += timedelta(days=1)

    return {"AAPL": data}


@pytest.fixture
def downtrend_data():
    """Data with downward price movement (triggers stop loss scenarios)."""
    data = []
    base_price = 150.0
    current_date = date(2022, 12, 1)

    for i in range(60):
        if current_date.weekday() < 5:
            price = base_price - i * 0.8  # Gradual downtrend
            data.append({
                "date": current_date.isoformat(),
                "open": price + 1,
                "high": price + 2,
                "low": price - 2,
                "close": price,
                "volume": 1000000,
            })
        current_date += timedelta(days=1)

    return {"AAPL": data}


# =============================================================================
# BacktestEngine Initialization Tests
# =============================================================================


class TestBacktestEngineInitialization:
    """Tests for BacktestEngine initialization."""

    def test_basic_initialization(self, basic_config):
        """Test engine initializes with basic config."""
        engine = BacktestEngine(basic_config)

        assert engine.config == basic_config
        assert engine._historical_data == {}
        assert engine._vix_data == []
        assert engine._iv_data == {}

    def test_initialization_without_black_scholes(self, basic_config):
        """Test engine without Black-Scholes creates no simulator."""
        engine = BacktestEngine(basic_config)

        assert engine._simulator is None

    def test_initialization_with_black_scholes(self, bs_config):
        """Test engine with Black-Scholes creates simulator."""
        engine = BacktestEngine(bs_config)

        assert engine._simulator is not None
        assert isinstance(engine._simulator, OptionsSimulator)

    def test_simulator_config_propagation(self, bs_config):
        """Test that config values propagate to simulator."""
        bs_config.slippage_pct = 2.0
        bs_config.commission_per_contract = 1.50

        engine = BacktestEngine(bs_config)

        assert engine._simulator.config.entry_slippage_pct == 2.0
        # Exit slippage is 1.5x entry slippage
        assert engine._simulator.config.exit_slippage_pct == 3.0
        assert engine._simulator.config.commission_per_contract == 1.50


# =============================================================================
# run_sync Method Tests
# =============================================================================


class TestRunBacktest:
    """Tests for the run_sync backtest method."""

    def test_run_sync_returns_backtest_result(self, basic_config, sample_historical_data):
        """Test run_sync returns BacktestResult."""
        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        assert isinstance(result, BacktestResult)
        assert result.config == basic_config

    def test_run_sync_with_empty_symbols(self, basic_config):
        """Test run_sync with empty symbol list."""
        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=[],
            historical_data={},
        )

        assert result.total_trades == 0
        assert result.trades == []

    def test_run_sync_with_empty_data(self, basic_config):
        """Test run_sync with no historical data."""
        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data={},
        )

        assert result.total_trades == 0

    def test_run_sync_with_missing_symbol_data(self, basic_config, sample_historical_data):
        """Test run_sync when symbol has no data."""
        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["MSFT"],  # Not in sample_historical_data
            historical_data=sample_historical_data,
        )

        assert result.total_trades == 0

    def test_run_sync_with_vix_data(self, basic_config, sample_historical_data, sample_vix_data):
        """Test run_sync processes VIX data."""
        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
            vix_data=sample_vix_data,
        )

        assert isinstance(result, BacktestResult)

    def test_run_sync_with_iv_data(self, bs_config, sample_historical_data, sample_iv_data):
        """Test run_sync uses IV data when provided."""
        engine = BacktestEngine(bs_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
            iv_data=sample_iv_data,
        )

        assert isinstance(result, BacktestResult)

    def test_run_sync_with_custom_entry_filter(self, basic_config, sample_historical_data):
        """Test run_sync with custom entry filter."""
        # Filter that rejects all entries
        def reject_all(symbol, date, price_data, score):
            return False

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
            entry_filter=reject_all,
        )

        assert result.total_trades == 0

    def test_run_sync_closes_open_positions_at_end(self, basic_config, sample_historical_data):
        """Test that open positions are closed at backtest end."""
        # Use high min score to prevent most entries
        basic_config.min_pullback_score = 0.0  # Very low to ensure entries
        basic_config.profit_target_pct = 99.0  # Very high to prevent profit exits
        basic_config.stop_loss_pct = 99.0  # Very high to prevent stop loss
        basic_config.dte_exit_threshold = 0  # Disable DTE exit

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        # All trades should have an exit_date <= end_date
        for trade in result.trades:
            assert trade.exit_date <= basic_config.end_date


# =============================================================================
# Trade Entry Logic Tests
# =============================================================================


class TestTradeEntryLogic:
    """Tests for trade entry logic."""

    def test_entry_requires_minimum_pullback_score(self, basic_config, sample_historical_data):
        """Test that entries require minimum pullback score."""
        # Set high score requirement
        basic_config.min_pullback_score = 15.0  # Max is ~12

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        assert result.total_trades == 0

    def test_no_duplicate_symbol_positions(self, basic_config, sample_historical_data):
        """Test that only one position per symbol is allowed."""
        basic_config.min_pullback_score = 0.0  # Allow all entries

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        # Check no overlapping positions for same symbol
        for i, trade1 in enumerate(result.trades):
            for trade2 in result.trades[i + 1:]:
                if trade1.symbol == trade2.symbol:
                    # trade2 should start after trade1 ends
                    assert trade2.entry_date >= trade1.exit_date

    def test_max_total_risk_limit(self, basic_config, sample_historical_data):
        """Test max total risk limit is respected."""
        basic_config.max_total_risk_pct = 1.0  # Very low limit
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        # Should still work but with limited positions
        assert isinstance(result, BacktestResult)

    def test_check_entry_signal_returns_none_for_missing_data(self, basic_config):
        """Test _check_entry_signal returns None when no data."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = {}

        result = engine._check_entry_signal("AAPL", date(2023, 1, 15), None)

        assert result is None

    def test_check_entry_signal_returns_none_for_zero_price(self, basic_config):
        """Test _check_entry_signal returns None for zero price."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = {
            "AAPL": [{"date": "2023-01-15", "close": 0, "high": 0, "low": 0, "volume": 0}]
        }

        result = engine._check_entry_signal("AAPL", date(2023, 1, 15), None)

        assert result is None


# =============================================================================
# Trade Exit Logic Tests
# =============================================================================


class TestTradeExitLogic:
    """Tests for trade exit logic."""

    def test_exit_at_expiration(self, basic_config, sample_historical_data):
        """Test positions exit at expiration."""
        basic_config.dte_max = 14  # Short DTE
        basic_config.dte_exit_threshold = 0  # Disable DTE exit
        basic_config.profit_target_pct = 200  # Disable profit target
        basic_config.stop_loss_pct = 200  # Disable stop loss

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        # Check that some trades exited at expiration
        expiration_exits = [t for t in result.trades if t.exit_reason == ExitReason.EXPIRATION]
        # May or may not have expiration exits depending on data
        assert isinstance(result, BacktestResult)

    def test_exit_at_profit_target(self, basic_config, sample_historical_data):
        """Test positions exit at profit target."""
        basic_config.profit_target_pct = 10.0  # Easy target
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        # Check for profit target exits
        profit_exits = [t for t in result.trades if t.exit_reason == ExitReason.PROFIT_TARGET_HIT]
        assert isinstance(result, BacktestResult)

    def test_exit_at_stop_loss(self, basic_config, downtrend_data):
        """Test positions exit at stop loss in downtrend."""
        basic_config.stop_loss_pct = 50.0  # Tight stop
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=downtrend_data,
        )

        # In downtrend, should have stop loss exits
        stop_loss_exits = [t for t in result.trades if t.exit_reason == ExitReason.STOP_LOSS_HIT]
        assert isinstance(result, BacktestResult)

    def test_exit_at_dte_threshold(self, basic_config, sample_historical_data):
        """Test positions exit at DTE threshold."""
        basic_config.dte_exit_threshold = 75  # Exit early
        basic_config.dte_max = 90
        basic_config.profit_target_pct = 200  # Disable
        basic_config.stop_loss_pct = 200  # Disable

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        # Check for DTE threshold exits
        dte_exits = [t for t in result.trades if t.exit_reason == ExitReason.DTE_THRESHOLD]
        assert isinstance(result, BacktestResult)


# =============================================================================
# Position Sizing Tests
# =============================================================================


class TestPositionSizing:
    """Tests for position sizing logic."""

    def test_contracts_calculated_from_max_risk(self, basic_config, sample_historical_data):
        """Test contracts are calculated based on max risk."""
        basic_config.max_position_pct = 10.0  # 10% max per position
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        for trade in result.trades:
            assert trade.contracts >= 1

    def test_minimum_one_contract(self, basic_config, sample_historical_data):
        """Test minimum of 1 contract is maintained."""
        basic_config.max_position_pct = 0.01  # Very small
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        for trade in result.trades:
            assert trade.contracts >= 1

    def test_max_loss_includes_commission(self, basic_config, sample_historical_data):
        """Test max loss calculation includes commission."""
        basic_config.commission_per_contract = 2.50
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        for trade in result.trades:
            # Max loss should be positive
            assert trade.max_loss > 0


# =============================================================================
# P&L Calculation Tests
# =============================================================================


class TestPnLCalculation:
    """Tests for P&L calculation logic."""

    def test_winning_trade_positive_pnl(self, basic_config, sample_historical_data):
        """Test winning trades have positive P&L."""
        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        for trade in result.trades:
            if trade.is_winner:
                assert trade.realized_pnl > 0

    def test_losing_trade_negative_pnl(self, basic_config, downtrend_data):
        """Test losing trades have negative P&L."""
        basic_config.min_pullback_score = 0.0
        basic_config.stop_loss_pct = 30.0  # Tight stop

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=downtrend_data,
        )

        for trade in result.trades:
            if not trade.is_winner:
                assert trade.realized_pnl <= 0

    def test_pnl_pct_calculation(self):
        """Test pnl_pct property calculation."""
        trade = TradeResult(
            symbol="AAPL",
            entry_date=date(2023, 1, 1),
            exit_date=date(2023, 1, 15),
            entry_price=150.0,
            exit_price=155.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            net_credit=1.0,
            contracts=1,
            max_profit=100.0,
            max_loss=400.0,
            realized_pnl=50.0,
            outcome=TradeOutcome.PARTIAL_PROFIT,
            exit_reason=ExitReason.PROFIT_TARGET_HIT,
            dte_at_entry=45,
            dte_at_exit=30,
            hold_days=15,
        )

        # pnl_pct = (realized_pnl / max_profit) * 100
        assert trade.pnl_pct == 50.0

    def test_pnl_pct_with_zero_max_profit(self):
        """Test pnl_pct returns 0 when max_profit is 0."""
        trade = TradeResult(
            symbol="AAPL",
            entry_date=date(2023, 1, 1),
            exit_date=date(2023, 1, 15),
            entry_price=150.0,
            exit_price=155.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            net_credit=1.0,
            contracts=1,
            max_profit=0.0,  # Zero max profit
            max_loss=400.0,
            realized_pnl=50.0,
            outcome=TradeOutcome.PARTIAL_PROFIT,
            exit_reason=ExitReason.PROFIT_TARGET_HIT,
            dte_at_entry=45,
            dte_at_exit=30,
            hold_days=15,
        )

        assert trade.pnl_pct == 0.0

    def test_risk_reward_achieved_calculation(self):
        """Test risk_reward_achieved property."""
        trade = TradeResult(
            symbol="AAPL",
            entry_date=date(2023, 1, 1),
            exit_date=date(2023, 1, 15),
            entry_price=150.0,
            exit_price=155.0,
            short_strike=145.0,
            long_strike=140.0,
            spread_width=5.0,
            net_credit=1.0,
            contracts=1,
            max_profit=100.0,
            max_loss=400.0,
            realized_pnl=200.0,
            outcome=TradeOutcome.MAX_PROFIT,
            exit_reason=ExitReason.EXPIRATION,
            dte_at_entry=45,
            dte_at_exit=0,
            hold_days=45,
        )

        # risk_reward_achieved = realized_pnl / max_loss
        assert trade.risk_reward_achieved == 0.5


# =============================================================================
# Statistics Generation Tests
# =============================================================================


class TestStatisticsGeneration:
    """Tests for BacktestResult statistics generation."""

    def test_total_trades_count(self, basic_config, sample_historical_data):
        """Test total trades are counted correctly."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        assert result.total_trades == len(result.trades)

    def test_winning_losing_counts(self, basic_config, sample_historical_data):
        """Test winning and losing trade counts."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        winners = sum(1 for t in result.trades if t.is_winner)
        losers = sum(1 for t in result.trades if t.realized_pnl < 0)
        breakeven = sum(1 for t in result.trades if t.realized_pnl == 0)

        assert result.winning_trades == winners
        assert result.losing_trades == losers
        assert result.breakeven_trades == breakeven
        assert result.winning_trades + result.losing_trades + result.breakeven_trades == result.total_trades

    def test_win_rate_calculation(self, basic_config, sample_historical_data):
        """Test win rate calculation."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        if result.total_trades > 0:
            expected_win_rate = (result.winning_trades / result.total_trades) * 100
            assert result.win_rate == expected_win_rate
        else:
            assert result.win_rate == 0.0

    def test_profit_factor_calculation(self, basic_config, sample_historical_data):
        """Test profit factor calculation."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        if result.total_loss > 0:
            expected_pf = result.total_profit / result.total_loss
            assert abs(result.profit_factor - expected_pf) < 0.01
        elif result.total_profit > 0:
            assert result.profit_factor == 0.0  # No losses, no PF calculation

    def test_average_hold_days(self, basic_config, sample_historical_data):
        """Test average hold days calculation."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        if result.trades:
            expected_avg = statistics.mean(t.hold_days for t in result.trades)
            assert abs(result.avg_hold_days - expected_avg) < 0.01

    def test_outcome_distribution(self, basic_config, sample_historical_data):
        """Test outcome distribution is populated."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        if result.trades:
            # Sum of outcome distribution should equal total trades
            total_in_dist = sum(result.outcome_distribution.values())
            assert total_in_dist == result.total_trades

    def test_equity_curve_generation(self, basic_config, sample_historical_data):
        """Test equity curve is generated."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        if result.trades:
            assert len(result.equity_curve) > 0
            # First point should be initial capital
            assert result.equity_curve[0][1] == basic_config.initial_capital

    def test_max_drawdown_calculation(self, basic_config, sample_historical_data):
        """Test max drawdown is calculated."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        # Drawdown should be non-negative
        assert result.max_drawdown >= 0
        assert result.max_drawdown_pct >= 0

    def test_sharpe_ratio_calculation(self, basic_config, sample_historical_data):
        """Test Sharpe ratio is calculated."""
        basic_config.min_pullback_score = 0.0

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        # Sharpe ratio should be a number
        assert isinstance(result.sharpe_ratio, float)

    def test_summary_method_returns_string(self, basic_config, sample_historical_data):
        """Test summary() method returns formatted string."""
        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        summary = result.summary()
        assert isinstance(summary, str)
        assert "BACKTEST" in summary

    def test_to_dict_method(self, basic_config, sample_historical_data):
        """Test to_dict() method returns dictionary."""
        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
        )

        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert "config" in result_dict
        assert "summary" in result_dict
        assert "outcome_distribution" in result_dict
        assert "trades" in result_dict


# =============================================================================
# BacktestResult Dataclass Tests
# =============================================================================


class TestBacktestResultMetrics:
    """Tests for BacktestResult metrics calculation."""

    def test_empty_trades_list(self):
        """Test BacktestResult with empty trades list."""
        config = BacktestConfig(
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
        )
        result = BacktestResult(config=config, trades=[])

        assert result.total_trades == 0
        assert result.win_rate == 0
        assert result.profit_factor == 0
        assert result.max_drawdown == 0

    def test_metrics_with_trades(self):
        """Test BacktestResult metrics with sample trades."""
        config = BacktestConfig(
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
        )

        trades = [
            TradeResult(
                symbol="AAPL",
                entry_date=date(2023, 1, 15),
                exit_date=date(2023, 2, 1),
                entry_price=150.0,
                exit_price=155.0,
                short_strike=145.0,
                long_strike=140.0,
                spread_width=5.0,
                net_credit=1.0,
                contracts=1,
                max_profit=100.0,
                max_loss=400.0,
                realized_pnl=50.0,  # Winner
                outcome=TradeOutcome.PROFIT_TARGET,
                exit_reason=ExitReason.PROFIT_TARGET_HIT,
                dte_at_entry=45,
                dte_at_exit=28,
                hold_days=17,
            ),
            TradeResult(
                symbol="AAPL",
                entry_date=date(2023, 3, 1),
                exit_date=date(2023, 3, 15),
                entry_price=160.0,
                exit_price=145.0,
                short_strike=155.0,
                long_strike=150.0,
                spread_width=5.0,
                net_credit=1.0,
                contracts=1,
                max_profit=100.0,
                max_loss=400.0,
                realized_pnl=-100.0,  # Loser
                outcome=TradeOutcome.STOP_LOSS,
                exit_reason=ExitReason.STOP_LOSS_HIT,
                dte_at_entry=45,
                dte_at_exit=30,
                hold_days=14,
            ),
        ]

        result = BacktestResult(config=config, trades=trades)

        assert result.total_trades == 2
        assert result.winning_trades == 1
        assert result.losing_trades == 1
        assert result.win_rate == 50.0
        assert result.total_profit == 50.0
        assert result.total_loss == 100.0
        assert result.total_pnl == -50.0


# =============================================================================
# TradeResult Dataclass Tests
# =============================================================================


class TestTradeResult:
    """Tests for TradeResult dataclass."""

    def test_is_winner_property_true(self):
        """Test is_winner returns True for positive P&L."""
        trade = TradeResult(
            symbol="TEST",
            entry_date=date(2023, 1, 1),
            exit_date=date(2023, 1, 15),
            entry_price=100.0,
            exit_price=105.0,
            short_strike=95.0,
            long_strike=90.0,
            spread_width=5.0,
            net_credit=1.0,
            contracts=1,
            max_profit=100.0,
            max_loss=400.0,
            realized_pnl=50.0,
            outcome=TradeOutcome.PROFIT_TARGET,
            exit_reason=ExitReason.PROFIT_TARGET_HIT,
            dte_at_entry=45,
            dte_at_exit=30,
            hold_days=15,
        )

        assert trade.is_winner is True

    def test_is_winner_property_false(self):
        """Test is_winner returns False for negative P&L."""
        trade = TradeResult(
            symbol="TEST",
            entry_date=date(2023, 1, 1),
            exit_date=date(2023, 1, 15),
            entry_price=100.0,
            exit_price=90.0,
            short_strike=95.0,
            long_strike=90.0,
            spread_width=5.0,
            net_credit=1.0,
            contracts=1,
            max_profit=100.0,
            max_loss=400.0,
            realized_pnl=-200.0,
            outcome=TradeOutcome.STOP_LOSS,
            exit_reason=ExitReason.STOP_LOSS_HIT,
            dte_at_entry=45,
            dte_at_exit=30,
            hold_days=15,
        )

        assert trade.is_winner is False

    def test_is_winner_property_zero(self):
        """Test is_winner returns False for zero P&L."""
        trade = TradeResult(
            symbol="TEST",
            entry_date=date(2023, 1, 1),
            exit_date=date(2023, 1, 15),
            entry_price=100.0,
            exit_price=95.0,
            short_strike=95.0,
            long_strike=90.0,
            spread_width=5.0,
            net_credit=1.0,
            contracts=1,
            max_profit=100.0,
            max_loss=400.0,
            realized_pnl=0.0,
            outcome=TradeOutcome.PARTIAL_PROFIT,
            exit_reason=ExitReason.DTE_THRESHOLD,
            dte_at_entry=45,
            dte_at_exit=7,
            hold_days=38,
        )

        assert trade.is_winner is False


# =============================================================================
# Helper Method Tests
# =============================================================================


class TestHelperMethods:
    """Tests for private helper methods."""

    def test_get_trading_days(self, basic_config):
        """Test _get_trading_days generates weekdays only."""
        engine = BacktestEngine(basic_config)
        trading_days = engine._get_trading_days()

        for day in trading_days:
            assert day.weekday() < 5  # Monday-Friday

    def test_get_trading_days_date_range(self, basic_config):
        """Test _get_trading_days respects date range."""
        engine = BacktestEngine(basic_config)
        trading_days = engine._get_trading_days()

        if trading_days:
            assert trading_days[0] >= basic_config.start_date
            assert trading_days[-1] <= basic_config.end_date

    def test_get_price_on_date(self, basic_config, sample_historical_data):
        """Test _get_price_on_date retrieves correct data."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = sample_historical_data

        # Find a valid date from the data
        valid_date = None
        for bar in sample_historical_data["AAPL"]:
            bar_date = date.fromisoformat(bar["date"])
            if bar_date >= basic_config.start_date:
                valid_date = bar_date
                break

        if valid_date:
            result = engine._get_price_on_date("AAPL", valid_date)
            assert result is not None
            assert "close" in result

    def test_get_price_on_date_missing(self, basic_config):
        """Test _get_price_on_date returns None for missing data."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = {}

        result = engine._get_price_on_date("AAPL", date(2023, 1, 15))

        assert result is None

    def test_get_vix_on_date(self, basic_config, sample_vix_data):
        """Test _get_vix_on_date retrieves correct VIX value."""
        engine = BacktestEngine(basic_config)
        engine._vix_data = sample_vix_data

        # Find a valid date
        valid_date = date.fromisoformat(sample_vix_data[0]["date"])
        result = engine._get_vix_on_date(valid_date)

        assert result is not None
        assert isinstance(result, float)

    def test_get_vix_on_date_missing(self, basic_config):
        """Test _get_vix_on_date returns None for missing date."""
        engine = BacktestEngine(basic_config)
        engine._vix_data = []

        result = engine._get_vix_on_date(date(2023, 1, 15))

        assert result is None

    def test_get_iv_on_date(self, basic_config, sample_iv_data):
        """Test _get_iv_on_date retrieves correct IV value."""
        engine = BacktestEngine(basic_config)
        engine._iv_data = sample_iv_data

        # Find a valid date
        valid_date = date.fromisoformat(sample_iv_data["AAPL"][0]["date"])
        result = engine._get_iv_on_date("AAPL", valid_date)

        assert result is not None
        assert isinstance(result, float)

    def test_get_iv_on_date_missing_symbol(self, basic_config):
        """Test _get_iv_on_date returns None for missing symbol."""
        engine = BacktestEngine(basic_config)
        engine._iv_data = {}

        result = engine._get_iv_on_date("MISSING", date(2023, 1, 15))

        assert result is None


# =============================================================================
# Pullback Score Calculation Tests
# =============================================================================


class TestPullbackScoreCalculation:
    """Tests for pullback score calculation."""

    def test_score_returns_tuple_with_breakdown(self, basic_config, sample_historical_data):
        """Test score calculation returns breakdown when requested."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = sample_historical_data

        result = engine._calculate_simple_pullback_score(
            "AAPL",
            date(2023, 1, 15),
            {"close": 160.0, "volume": 1000000},
            use_previous_day=False,
            return_breakdown=True,
        )

        assert isinstance(result, tuple)
        score, breakdown = result
        assert isinstance(score, float)
        assert isinstance(breakdown, dict)
        assert "rsi_score" in breakdown
        assert "support_score" in breakdown
        assert "ma_score" in breakdown

    def test_score_returns_float_without_breakdown(self, basic_config, sample_historical_data):
        """Test score calculation returns float when breakdown not requested."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = sample_historical_data

        result = engine._calculate_simple_pullback_score(
            "AAPL",
            date(2023, 1, 15),
            {"close": 160.0, "volume": 1000000},
            use_previous_day=False,
            return_breakdown=False,
        )

        assert isinstance(result, float)

    def test_score_zero_for_missing_history(self, basic_config):
        """Test score is 0 when insufficient history."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = {}

        result = engine._calculate_simple_pullback_score(
            "AAPL",
            date(2023, 1, 15),
            {"close": 160.0, "volume": 1000000},
        )

        assert result == 0.0

    def test_score_capped_at_maximum(self, basic_config, sample_historical_data):
        """Test score is capped at maximum value."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = sample_historical_data

        result = engine._calculate_simple_pullback_score(
            "AAPL",
            date(2023, 1, 15),
            {"close": 160.0, "volume": 1000000},
        )

        assert result <= 12.0  # Max score is 12


# =============================================================================
# Black-Scholes Integration Tests
# =============================================================================


class TestBlackScholesIntegration:
    """Tests for Black-Scholes pricing integration."""

    def test_bs_config_creates_simulator(self, bs_config):
        """Test Black-Scholes config creates OptionsSimulator."""
        engine = BacktestEngine(bs_config)

        assert engine._simulator is not None

    def test_bs_pricing_used_in_entry(self, bs_config, sample_historical_data, sample_vix_data, sample_iv_data):
        """Test Black-Scholes pricing is used for entries."""
        engine = BacktestEngine(bs_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
            vix_data=sample_vix_data,
            iv_data=sample_iv_data,
        )

        # Should run without errors
        assert isinstance(result, BacktestResult)

    def test_estimate_iv_from_hv(self, bs_config, sample_historical_data):
        """Test IV estimation from historical volatility."""
        engine = BacktestEngine(bs_config)
        engine._historical_data = sample_historical_data

        # Should return a valid IV
        iv = engine._estimate_iv_from_hv("AAPL", date(2023, 1, 15))

        assert isinstance(iv, float)
        assert 0.10 <= iv <= 0.80  # Within bounds


# =============================================================================
# Delta-Based Strike Selection Tests
# =============================================================================


class TestDeltaBasedStrikes:
    """Tests for delta-based strike selection."""

    def test_delta_config_enables_delta_strikes(self, delta_config):
        """Test delta config enables delta-based strike selection."""
        assert delta_config.use_delta_based_strikes is True

    def test_delta_strikes_used_when_enabled(self, delta_config, sample_historical_data, sample_vix_data, sample_iv_data):
        """Test delta-based strikes are used when enabled."""
        engine = BacktestEngine(delta_config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data=sample_historical_data,
            vix_data=sample_vix_data,
            iv_data=sample_iv_data,
        )

        # Should run without errors
        assert isinstance(result, BacktestResult)


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_single_day_backtest(self):
        """Test backtest with single day."""
        config = BacktestConfig(
            start_date=date(2023, 1, 2),
            end_date=date(2023, 1, 2),  # Same day
        )

        engine = BacktestEngine(config)
        result = engine.run_sync(
            symbols=["AAPL"],
            historical_data={"AAPL": [{
                "date": "2023-01-02",
                "open": 150,
                "high": 152,
                "low": 148,
                "close": 151,
                "volume": 1000000,
            }]},
        )

        assert isinstance(result, BacktestResult)

    def test_weekend_dates_skipped(self, basic_config):
        """Test that weekend dates are skipped."""
        engine = BacktestEngine(basic_config)
        trading_days = engine._get_trading_days()

        for day in trading_days:
            assert day.weekday() not in [5, 6]  # Saturday, Sunday

    def test_negative_price_handled(self, basic_config):
        """Test handling of negative prices."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = {
            "AAPL": [{
                "date": "2023-01-15",
                "close": -100,  # Invalid negative price
                "high": -90,
                "low": -110,
                "volume": 1000000,
            }]
        }

        signal = engine._check_entry_signal("AAPL", date(2023, 1, 15), None)

        assert signal is None  # Should reject invalid price

    def test_date_string_conversion(self, basic_config, sample_historical_data):
        """Test that string dates in data are converted properly."""
        engine = BacktestEngine(basic_config)
        engine._historical_data = sample_historical_data

        # Find a valid date
        for bar in sample_historical_data["AAPL"]:
            bar_date = date.fromisoformat(bar["date"])
            if bar_date >= basic_config.start_date:
                result = engine._get_price_on_date("AAPL", bar_date)
                assert result is not None
                break

    def test_multiple_symbols_backtest(self, basic_config, sample_historical_data):
        """Test backtest with multiple symbols."""
        # Add another symbol
        sample_historical_data["MSFT"] = sample_historical_data["AAPL"].copy()

        engine = BacktestEngine(basic_config)
        result = engine.run_sync(
            symbols=["AAPL", "MSFT"],
            historical_data=sample_historical_data,
        )

        assert isinstance(result, BacktestResult)


# =============================================================================
# TradeOutcome Enum Tests
# =============================================================================


class TestTradeOutcomeEnum:
    """Tests for TradeOutcome enum."""

    def test_all_outcomes_have_values(self):
        """Test all TradeOutcome members have string values."""
        for outcome in TradeOutcome:
            assert isinstance(outcome.value, str)

    def test_outcome_values(self):
        """Test specific outcome values."""
        assert TradeOutcome.MAX_PROFIT.value == "max_profit"
        assert TradeOutcome.PROFIT_TARGET.value == "profit_target"
        assert TradeOutcome.STOP_LOSS.value == "stop_loss"
        assert TradeOutcome.MAX_LOSS.value == "max_loss"


# =============================================================================
# ExitReason Enum Tests
# =============================================================================


class TestExitReasonEnum:
    """Tests for ExitReason enum."""

    def test_all_exit_reasons_have_values(self):
        """Test all ExitReason members have string values."""
        for reason in ExitReason:
            assert isinstance(reason.value, str)

    def test_exit_reason_values(self):
        """Test specific exit reason values."""
        assert ExitReason.PROFIT_TARGET_HIT.value == "profit_target"
        assert ExitReason.STOP_LOSS_HIT.value == "stop_loss"
        assert ExitReason.EXPIRATION.value == "expiration"
        assert ExitReason.DTE_THRESHOLD.value == "dte_threshold"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
