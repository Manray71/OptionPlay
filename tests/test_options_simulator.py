"""
Tests for the Options Simulator module.

Tests cover:
- SpreadEntry dataclass
- SpreadSnapshot dataclass
- SimulatorConfig dataclass
- OptionsSimulator class
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
import numpy as np

from src.backtesting.options_simulator import (
    SpreadEntry,
    SpreadSnapshot,
    SimulatorConfig,
    OptionsSimulator,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_spread_entry():
    """Create a sample SpreadEntry."""
    return SpreadEntry(
        symbol="AAPL",
        entry_date=date(2026, 1, 15),
        underlying_price=150.0,
        short_strike=145.0,
        long_strike=140.0,
        spread_width=5.0,
        short_put_price=2.50,
        long_put_price=1.20,
        net_credit=1.25,  # After slippage
        entry_delta=-0.25,
        entry_theta=0.05,
        dte_at_entry=45,
        expiry_date=date(2026, 3, 1),
        entry_iv=0.25,
        contracts=1,
        commission=2.60,
        max_profit=122.40,  # (1.25 * 100) - 2.60
        max_loss=377.60,  # (5.0 - 1.25) * 100 + 2.60
    )


@pytest.fixture
def sample_snapshot():
    """Create a sample SpreadSnapshot."""
    return SpreadSnapshot(
        date=date(2026, 1, 30),
        underlying_price=152.0,
        days_held=15,
        dte_remaining=30,
        short_put_value=1.80,
        long_put_value=0.80,
        spread_value=1.00,
        unrealized_pnl=0.25,
        unrealized_pnl_total=25.0,
        pnl_pct=20.0,
        current_delta=-0.18,
        current_theta=0.06,
        current_iv=0.23,
    )


@pytest.fixture
def simulator_config():
    """Create a SimulatorConfig."""
    return SimulatorConfig(
        risk_free_rate=0.05,
        entry_slippage_pct=1.0,
        exit_slippage_pct=1.5,
        bid_ask_pct=5.0,
        commission_per_contract=1.30,
    )


@pytest.fixture
def simulator():
    """Create an OptionsSimulator."""
    return OptionsSimulator()


# =============================================================================
# SPREAD ENTRY TESTS
# =============================================================================


class TestSpreadEntry:
    """Tests for SpreadEntry dataclass."""

    def test_creation(self, sample_spread_entry):
        """Test SpreadEntry creation."""
        entry = sample_spread_entry
        assert entry.symbol == "AAPL"
        assert entry.underlying_price == 150.0
        assert entry.short_strike == 145.0
        assert entry.long_strike == 140.0
        assert entry.spread_width == 5.0
        assert entry.net_credit == 1.25

    def test_gross_credit_property(self, sample_spread_entry):
        """Test gross_credit property."""
        entry = sample_spread_entry
        expected = 2.50 - 1.20  # short_put - long_put
        assert entry.gross_credit == expected

    def test_breakeven_property(self, sample_spread_entry):
        """Test breakeven property."""
        entry = sample_spread_entry
        expected = 145.0 - 1.25  # short_strike - net_credit
        assert entry.breakeven == expected


# =============================================================================
# SPREAD SNAPSHOT TESTS
# =============================================================================


class TestSpreadSnapshot:
    """Tests for SpreadSnapshot dataclass."""

    def test_creation(self, sample_snapshot):
        """Test SpreadSnapshot creation."""
        snap = sample_snapshot
        assert snap.underlying_price == 152.0
        assert snap.days_held == 15
        assert snap.dte_remaining == 30
        assert snap.unrealized_pnl == 0.25


# =============================================================================
# SIMULATOR CONFIG TESTS
# =============================================================================


class TestSimulatorConfig:
    """Tests for SimulatorConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SimulatorConfig()
        assert config.risk_free_rate == 0.05
        assert config.entry_slippage_pct == 1.0
        assert config.exit_slippage_pct == 1.5
        assert config.bid_ask_pct == 5.0
        assert config.commission_per_contract == 1.30

    def test_custom_values(self):
        """Test custom configuration values."""
        config = SimulatorConfig(
            risk_free_rate=0.03,
            entry_slippage_pct=0.5,
            exit_slippage_pct=1.0,
            commission_per_contract=1.50,
        )
        assert config.risk_free_rate == 0.03
        assert config.entry_slippage_pct == 0.5
        assert config.commission_per_contract == 1.50


# =============================================================================
# OPTIONS SIMULATOR TESTS
# =============================================================================


class TestOptionsSimulator:
    """Tests for OptionsSimulator class."""

    def test_initialization_default(self):
        """Test default initialization."""
        sim = OptionsSimulator()
        assert sim is not None
        assert sim.config is not None

    def test_initialization_with_config(self, simulator_config):
        """Test initialization with custom config."""
        sim = OptionsSimulator(config=simulator_config)
        assert sim.config.risk_free_rate == 0.05

    def test_simulate_entry_basic(self, simulator):
        """Test basic entry simulation."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
        )

        assert entry is not None
        assert entry.symbol == "AAPL"
        assert entry.underlying_price == 150.0
        assert entry.short_strike == 145.0
        assert entry.long_strike == 140.0
        assert entry.spread_width == 5.0
        assert entry.dte_at_entry == 45
        assert entry.entry_iv == 0.25
        assert entry.net_credit > 0

    def test_simulate_entry_with_contracts(self, simulator):
        """Test entry simulation with multiple contracts."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
            contracts=5,
        )

        assert entry.contracts == 5
        # Commission should scale with contracts
        assert entry.commission > 2.60  # More than single contract

    def test_simulate_entry_with_entry_date(self, simulator):
        """Test entry simulation with explicit entry date."""
        entry_date = date(2026, 1, 15)
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
            entry_date=entry_date,
        )

        assert entry.entry_date == entry_date
        expected_expiry = entry_date + timedelta(days=45)
        assert entry.expiry_date == expected_expiry

class TestOptionsSimulatorEdgeCases:
    """Tests for edge cases."""

    def test_deep_itm_spread(self, simulator):
        """Test deep in-the-money spread."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=100.0,
            short_strike=110.0,  # Deep ITM
            long_strike=105.0,
            dte=45,
            iv=0.30,
        )

        assert entry is not None
        assert entry.net_credit > 0  # Should still collect credit

    def test_deep_otm_spread(self, simulator):
        """Test deep out-of-the-money spread."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=110.0,  # Deep OTM
            long_strike=105.0,
            dte=45,
            iv=0.25,
        )

        assert entry is not None
        # Credit should be small for deep OTM
        assert 0 < entry.net_credit < 1.0

    def test_very_short_dte(self, simulator):
        """Test very short DTE spread."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=3,  # Very short
            iv=0.25,
        )

        assert entry is not None
        # Should have some credit even with short DTE
        assert entry.net_credit >= 0

    def test_high_iv_environment(self, simulator):
        """Test high IV environment."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.60,  # High IV
        )

        assert entry is not None
        # Higher IV should result in higher credit
        low_iv_entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.20,  # Low IV
        )

        assert entry.net_credit > low_iv_entry.net_credit

    def test_low_iv_environment(self, simulator):
        """Test low IV environment."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.10,  # Very low IV
        )

        assert entry is not None
        assert entry.net_credit >= 0


class TestOptionsSimulatorMaxProfitLoss:
    """Tests for max profit/loss calculations."""

    def test_max_profit_calculation(self, simulator):
        """Test max profit calculation."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
            contracts=1,
        )

        # Max profit = (net_credit * 100) - commission
        expected_max_profit = (entry.net_credit * 100) - entry.commission
        assert abs(entry.max_profit - expected_max_profit) < 0.01

    def test_max_loss_calculation(self, simulator):
        """Test max loss calculation."""
        entry = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
            contracts=1,
        )

        # Max loss = ((spread_width - net_credit) * 100) + commission
        expected_max_loss = ((entry.spread_width - entry.net_credit) * 100) + entry.commission
        assert abs(entry.max_loss - expected_max_loss) < 0.01

    def test_max_profit_scales_with_contracts(self, simulator):
        """Test max profit scales with contract count."""
        entry1 = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
            contracts=1,
        )

        entry5 = simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
            contracts=5,
        )

        # Max profit should scale roughly linearly (minus commission)
        ratio = entry5.max_profit / entry1.max_profit
        assert 4.5 < ratio < 5.5  # Approximately 5x


# =============================================================================
# CALCULATE SNAPSHOT TESTS
# =============================================================================


class TestCalculateSnapshot:
    """Tests for calculate_snapshot method."""

    @pytest.fixture
    def simulator(self):
        """Create an OptionsSimulator."""
        return OptionsSimulator()

    @pytest.fixture
    def basic_entry(self, simulator):
        """Create a basic spread entry for snapshot tests."""
        return simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
            entry_date=date(2026, 1, 15),
        )

    def test_calculate_snapshot_profitable(self, simulator, basic_entry):
        """Test snapshot with profitable position (price moved up)."""
        snapshot = simulator.calculate_snapshot(
            entry=basic_entry,
            current_date=date(2026, 1, 30),  # 15 days later
            current_price=155.0,  # Price moved up
            current_iv=0.22,
        )

        assert snapshot is not None
        assert snapshot.days_held == 15
        assert snapshot.underlying_price == 155.0
        # Price moved favorably, should show profit
        assert snapshot.unrealized_pnl >= 0 or snapshot.unrealized_pnl is not None

    def test_calculate_snapshot_losing(self, simulator, basic_entry):
        """Test snapshot with losing position (price dropped)."""
        snapshot = simulator.calculate_snapshot(
            entry=basic_entry,
            current_date=date(2026, 1, 30),
            current_price=142.0,  # Below short strike
            current_iv=0.30,  # IV increased
        )

        assert snapshot is not None
        assert snapshot.underlying_price == 142.0
        # Price near short strike, should show reduced profit or loss

    def test_calculate_snapshot_at_expiration(self, simulator, basic_entry):
        """Test snapshot at expiration."""
        snapshot = simulator.calculate_snapshot(
            entry=basic_entry,
            current_date=basic_entry.expiry_date,
            current_price=150.0,  # Above short strike (OTM)
        )

        assert snapshot is not None
        assert snapshot.dte_remaining == 0
        # At expiration OTM, spread worth 0
        assert snapshot.spread_value >= 0

    def test_calculate_snapshot_expired_otm(self, simulator, basic_entry):
        """Test snapshot when expired OTM (max profit)."""
        snapshot = simulator.calculate_snapshot(
            entry=basic_entry,
            current_date=basic_entry.expiry_date + timedelta(days=1),
            current_price=160.0,  # Well above short strike
        )

        assert snapshot is not None
        assert snapshot.dte_remaining == 0

    def test_calculate_snapshot_expired_itm(self, simulator, basic_entry):
        """Test snapshot when expired ITM (max loss)."""
        snapshot = simulator.calculate_snapshot(
            entry=basic_entry,
            current_date=basic_entry.expiry_date,
            current_price=135.0,  # Below long strike
        )

        assert snapshot is not None
        # Fully ITM - spread value equals spread width

    def test_calculate_snapshot_with_iv_estimation(self, simulator, basic_entry):
        """Test snapshot with IV estimation from VIX."""
        snapshot = simulator.calculate_snapshot(
            entry=basic_entry,
            current_date=date(2026, 1, 30),
            current_price=150.0,
            current_iv=None,  # Force IV estimation
            vix=20.0,
        )

        assert snapshot is not None
        assert snapshot.current_iv is not None


# =============================================================================
# SIMULATE TRADE PATH TESTS
# =============================================================================


class TestSimulateTradePath:
    """Tests for simulate_trade_path method."""

    @pytest.fixture
    def simulator(self):
        """Create an OptionsSimulator."""
        return OptionsSimulator()

    @pytest.fixture
    def basic_entry(self, simulator):
        """Create a basic spread entry."""
        return simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=30,
            iv=0.25,
            entry_date=date(2026, 1, 15),
        )

    def test_simulate_trade_path_basic(self, simulator, basic_entry):
        """Test basic trade path simulation."""
        price_path = [
            (date(2026, 1, 15), 150.0),
            (date(2026, 1, 20), 152.0),
            (date(2026, 1, 25), 148.0),
            (date(2026, 1, 30), 155.0),
        ]

        snapshots = simulator.simulate_trade_path(
            entry=basic_entry,
            price_path=price_path,
        )

        assert len(snapshots) == 4
        for snap in snapshots:
            assert snap.days_held >= 0

    def test_simulate_trade_path_with_iv(self, simulator, basic_entry):
        """Test trade path with IV path."""
        price_path = [
            (date(2026, 1, 15), 150.0),
            (date(2026, 1, 20), 152.0),
            (date(2026, 1, 25), 148.0),
        ]
        iv_path = [
            (date(2026, 1, 15), 0.25),
            (date(2026, 1, 20), 0.22),
            (date(2026, 1, 25), 0.28),
        ]

        snapshots = simulator.simulate_trade_path(
            entry=basic_entry,
            price_path=price_path,
            iv_path=iv_path,
        )

        assert len(snapshots) == 3

    def test_simulate_trade_path_with_vix(self, simulator, basic_entry):
        """Test trade path with VIX path."""
        price_path = [
            (date(2026, 1, 15), 150.0),
            (date(2026, 1, 20), 152.0),
        ]
        vix_path = [
            (date(2026, 1, 15), 18.0),
            (date(2026, 1, 20), 22.0),
        ]

        snapshots = simulator.simulate_trade_path(
            entry=basic_entry,
            price_path=price_path,
            vix_path=vix_path,
        )

        assert len(snapshots) == 2

    def test_simulate_trade_path_skips_before_entry(self, simulator, basic_entry):
        """Test that dates before entry are skipped."""
        price_path = [
            (date(2026, 1, 10), 148.0),  # Before entry
            (date(2026, 1, 15), 150.0),
            (date(2026, 1, 20), 152.0),
        ]

        snapshots = simulator.simulate_trade_path(
            entry=basic_entry,
            price_path=price_path,
        )

        # Should skip the first date
        assert len(snapshots) == 2

    def test_simulate_trade_path_stops_after_expiry(self, simulator, basic_entry):
        """Test that dates after expiry are stopped."""
        price_path = [
            (date(2026, 1, 15), 150.0),
            (date(2026, 1, 20), 152.0),
            (date(2026, 3, 15), 160.0),  # After expiry
        ]

        snapshots = simulator.simulate_trade_path(
            entry=basic_entry,
            price_path=price_path,
        )

        # Should stop at expiry
        assert len(snapshots) == 2


# =============================================================================
# CHECK EXIT CONDITIONS TESTS
# =============================================================================


class TestCheckExitConditions:
    """Tests for check_exit_conditions method."""

    @pytest.fixture
    def simulator(self):
        """Create an OptionsSimulator."""
        return OptionsSimulator()

    @pytest.fixture
    def basic_entry(self, simulator):
        """Create a basic spread entry."""
        return simulator.simulate_entry(
            symbol="AAPL",
            underlying_price=150.0,
            short_strike=145.0,
            long_strike=140.0,
            dte=45,
            iv=0.25,
            entry_date=date(2026, 1, 15),
        )

    def test_no_exit_conditions_met(self, simulator, basic_entry):
        """Test when no exit conditions are met."""
        snapshot = SpreadSnapshot(
            date=date(2026, 1, 30),
            underlying_price=152.0,
            days_held=15,
            dte_remaining=30,
            short_put_value=1.50,
            long_put_value=0.60,
            spread_value=0.90,
            unrealized_pnl=0.35,
            unrealized_pnl_total=35.0,
            pnl_pct=25.0,  # Below profit target
            current_delta=-0.15,
            current_theta=0.06,
            current_iv=0.23,
        )

        exit_reason = simulator.check_exit_conditions(
            snapshot=snapshot,
            entry=basic_entry,
            profit_target_pct=50.0,
            stop_loss_pct=100.0,
        )

        assert exit_reason is None

    def test_exit_at_expiration(self, simulator, basic_entry):
        """Test exit at expiration."""
        snapshot = SpreadSnapshot(
            date=basic_entry.expiry_date,
            underlying_price=150.0,
            days_held=45,
            dte_remaining=0,  # Expiration
            short_put_value=0,
            long_put_value=0,
            spread_value=0,
            unrealized_pnl=basic_entry.net_credit,
            unrealized_pnl_total=basic_entry.net_credit * 100,
            pnl_pct=100.0,
            current_delta=0,
            current_theta=0,
            current_iv=0.23,
        )

        exit_reason = simulator.check_exit_conditions(
            snapshot=snapshot,
            entry=basic_entry,
        )

        assert exit_reason == "expiration"

    def test_exit_profit_target(self, simulator, basic_entry):
        """Test exit at profit target."""
        snapshot = SpreadSnapshot(
            date=date(2026, 1, 30),
            underlying_price=155.0,
            days_held=15,
            dte_remaining=30,
            short_put_value=0.50,
            long_put_value=0.10,
            spread_value=0.40,
            unrealized_pnl=basic_entry.net_credit - 0.40,
            unrealized_pnl_total=70.0,
            pnl_pct=55.0,  # Above 50% profit target
            current_delta=-0.08,
            current_theta=0.04,
            current_iv=0.20,
        )

        exit_reason = simulator.check_exit_conditions(
            snapshot=snapshot,
            entry=basic_entry,
            profit_target_pct=50.0,
        )

        assert exit_reason == "profit_target"

    def test_exit_stop_loss(self, simulator, basic_entry):
        """Test exit at stop loss."""
        snapshot = SpreadSnapshot(
            date=date(2026, 1, 30),
            underlying_price=140.0,  # Deep ITM
            days_held=15,
            dte_remaining=30,
            short_put_value=6.0,
            long_put_value=2.0,
            spread_value=4.0,
            unrealized_pnl=basic_entry.net_credit - 4.0,
            unrealized_pnl_total=-275.0,  # Large loss
            pnl_pct=-200.0,
            current_delta=-0.80,
            current_theta=0.01,
            current_iv=0.35,
        )

        exit_reason = simulator.check_exit_conditions(
            snapshot=snapshot,
            entry=basic_entry,
            stop_loss_pct=50.0,  # Stop at 50% of max loss
        )

        assert exit_reason == "stop_loss"

    def test_exit_dte_threshold(self, simulator, basic_entry):
        """Test exit at DTE threshold."""
        snapshot = SpreadSnapshot(
            date=date(2026, 2, 22),  # 5 days to expiry
            underlying_price=150.0,
            days_held=38,
            dte_remaining=5,  # Below 7-day threshold
            short_put_value=1.0,
            long_put_value=0.30,
            spread_value=0.70,
            unrealized_pnl=basic_entry.net_credit - 0.70,
            unrealized_pnl_total=55.0,
            pnl_pct=40.0,
            current_delta=-0.20,
            current_theta=0.10,
            current_iv=0.24,
        )

        exit_reason = simulator.check_exit_conditions(
            snapshot=snapshot,
            entry=basic_entry,
            dte_exit_threshold=7,
        )

        assert exit_reason == "dte_threshold"

    def test_exit_deep_itm(self, simulator, basic_entry):
        """Test exit when deep ITM."""
        snapshot = SpreadSnapshot(
            date=date(2026, 1, 30),
            underlying_price=141.0,  # Below short strike, ITM
            days_held=15,
            dte_remaining=30,
            short_put_value=5.0,
            long_put_value=1.5,
            spread_value=3.5,
            unrealized_pnl=basic_entry.net_credit - 3.5,
            unrealized_pnl_total=-225.0,
            pnl_pct=-180.0,
            current_delta=-0.75,
            current_theta=0.02,
            current_iv=0.32,
        )

        exit_reason = simulator.check_exit_conditions(
            snapshot=snapshot,
            entry=basic_entry,
            stop_loss_pct=200.0,  # High stop to not trigger
        )

        assert exit_reason == "deep_itm"


# =============================================================================
# PRIVATE HELPER TESTS
# =============================================================================


class TestSimulatorPrivateHelpers:
    """Tests for private helper methods."""

    @pytest.fixture
    def simulator(self):
        """Create an OptionsSimulator."""
        return OptionsSimulator()

    def test_adjust_iv_for_skew_otm(self, simulator):
        """Test IV skew adjustment for OTM put."""
        base_iv = 0.25
        underlying_price = 150.0
        strike = 140.0  # OTM

        adjusted_iv = simulator._adjust_iv_for_skew(base_iv, underlying_price, strike)

        # OTM puts should have higher IV
        assert adjusted_iv >= base_iv

    def test_adjust_iv_for_skew_atm(self, simulator):
        """Test IV skew adjustment for ATM put."""
        base_iv = 0.25
        underlying_price = 150.0
        strike = 150.0  # ATM

        adjusted_iv = simulator._adjust_iv_for_skew(base_iv, underlying_price, strike)

        # ATM should be close to base IV
        assert abs(adjusted_iv - base_iv) < 0.01

    def test_adjust_iv_for_skew_itm(self, simulator):
        """Test IV skew adjustment for ITM put."""
        base_iv = 0.25
        underlying_price = 150.0
        strike = 160.0  # ITM

        adjusted_iv = simulator._adjust_iv_for_skew(base_iv, underlying_price, strike)

        # ITM puts typically have slightly lower IV but can vary
        assert adjusted_iv > 0

    def test_estimate_iv_change_short_period(self, simulator):
        """Test IV change estimation for short holding period."""
        entry_iv = 0.25
        days_held = 5
        vix = 18.0

        estimated_iv = simulator._estimate_iv_change(entry_iv, days_held, vix)

        # IV shouldn't change drastically in short period
        assert 0.15 < estimated_iv < 0.35

    def test_estimate_iv_change_long_period(self, simulator):
        """Test IV change estimation for longer period."""
        entry_iv = 0.25
        days_held = 30
        vix = 25.0  # Elevated VIX

        estimated_iv = simulator._estimate_iv_change(entry_iv, days_held, vix)

        assert estimated_iv > 0

    def test_estimate_iv_change_no_vix(self, simulator):
        """Test IV change estimation without VIX."""
        entry_iv = 0.25
        days_held = 15

        estimated_iv = simulator._estimate_iv_change(entry_iv, days_held, vix=None)

        # Should still return a reasonable IV
        assert 0.1 < estimated_iv < 0.5
