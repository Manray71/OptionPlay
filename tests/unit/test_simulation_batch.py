# Tests for Simulation Batch Functions
# =====================================
"""
Tests for options_simulator.py batch/vectorized functions and quick_spread_pnl:
- batch_calculate_spread_values
- batch_calculate_pnl
- batch_check_exit_signals
- quick_spread_pnl
- EXIT_CODE_NAMES
"""

import numpy as np
import pytest

from src.backtesting.simulation.options_simulator import (
    EXIT_CODE_NAMES,
    batch_calculate_pnl,
    batch_calculate_spread_values,
    batch_check_exit_signals,
    quick_spread_pnl,
)

# =============================================================================
# BATCH SPREAD VALUES
# =============================================================================


class TestBatchCalculateSpreadValues:
    """Tests for batch_calculate_spread_values()."""

    def test_basic_otm_spread(self):
        """OTM put spread: both strikes below current price."""
        short_put_vals, long_put_vals, spread_vals = batch_calculate_spread_values(
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([45.0]),
            current_ivs=np.array([0.25]),
        )
        assert len(short_put_vals) == 1
        # OTM puts have positive value (cost to buy back)
        assert short_put_vals[0] > 0
        assert long_put_vals[0] > 0
        # Short put (closer to ATM) worth more than long put (further OTM)
        assert short_put_vals[0] > long_put_vals[0]
        # Spread value = short - long > 0
        assert spread_vals[0] > 0

    def test_expired_otm(self):
        """Expired OTM spread: intrinsic value = 0."""
        short_put_vals, long_put_vals, spread_vals = batch_calculate_spread_values(
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([0.0]),
            current_ivs=np.array([0.25]),
        )
        # Both OTM at expiration → intrinsic = 0
        assert short_put_vals[0] == 0.0
        assert long_put_vals[0] == 0.0
        assert spread_vals[0] == 0.0

    def test_expired_itm(self):
        """Expired ITM spread: full intrinsic value."""
        short_put_vals, long_put_vals, spread_vals = batch_calculate_spread_values(
            current_prices=np.array([160.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([0.0]),
            current_ivs=np.array([0.25]),
        )
        # Short put: max(0, 180-160) = 20
        assert short_put_vals[0] == pytest.approx(20.0)
        # Long put: max(0, 170-160) = 10
        assert long_put_vals[0] == pytest.approx(10.0)
        # Spread = 20 - 10 = 10 (full width)
        assert spread_vals[0] == pytest.approx(10.0)

    def test_expired_partial_itm(self):
        """Price between strikes at expiration."""
        short_put_vals, long_put_vals, spread_vals = batch_calculate_spread_values(
            current_prices=np.array([175.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([0.0]),
            current_ivs=np.array([0.25]),
        )
        # Short put: max(0, 180-175) = 5
        assert short_put_vals[0] == pytest.approx(5.0)
        # Long put: max(0, 170-175) = 0
        assert long_put_vals[0] == pytest.approx(0.0)
        assert spread_vals[0] == pytest.approx(5.0)

    def test_multiple_positions(self):
        """Batch with multiple positions."""
        n = 5
        short_put_vals, long_put_vals, spread_vals = batch_calculate_spread_values(
            current_prices=np.array([200.0] * n),
            short_strikes=np.array([180.0] * n),
            long_strikes=np.array([170.0] * n),
            dtes_remaining=np.array([60.0, 45.0, 30.0, 15.0, 0.0]),
            current_ivs=np.array([0.25] * n),
        )
        assert len(spread_vals) == n
        # Higher DTE → more time value → higher spread value
        assert spread_vals[0] > spread_vals[3]
        # Expired (last) should be 0 (OTM)
        assert spread_vals[4] == 0.0

    def test_negative_dte_treated_as_expired(self):
        """Negative DTE should use intrinsic values."""
        _, _, spread_vals = batch_calculate_spread_values(
            current_prices=np.array([160.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([-5.0]),
            current_ivs=np.array([0.25]),
        )
        # ITM at expiration: spread = 10 (full width)
        assert spread_vals[0] == pytest.approx(10.0)

    def test_high_iv_increases_values(self):
        """Higher IV → higher put values → higher spread value."""
        _, _, spread_low_iv = batch_calculate_spread_values(
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([45.0]),
            current_ivs=np.array([0.15]),
        )
        _, _, spread_high_iv = batch_calculate_spread_values(
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([45.0]),
            current_ivs=np.array([0.50]),
        )
        assert spread_high_iv[0] > spread_low_iv[0]


# =============================================================================
# BATCH P&L
# =============================================================================


class TestBatchCalculatePnl:
    """Tests for batch_calculate_pnl()."""

    def test_profitable_expired_otm(self):
        """OTM at expiration → keep full credit (minus slippage on non-expired)."""
        pnl = batch_calculate_pnl(
            entry_credits=np.array([2.0]),
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([0.0]),
            current_ivs=np.array([0.25]),
            contracts=np.array([1.0]),
        )
        # P&L = (credit - spread_value) * 100 * contracts
        # spread_value = 0 (OTM expired), no slippage (expired)
        assert pnl[0] == pytest.approx(200.0)  # 2.0 * 100

    def test_max_loss_expired_itm(self):
        """Deep ITM at expiration → max loss."""
        pnl = batch_calculate_pnl(
            entry_credits=np.array([2.0]),
            current_prices=np.array([160.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([0.0]),
            current_ivs=np.array([0.25]),
            contracts=np.array([1.0]),
        )
        # spread_value = 10 (full width), no slippage
        # P&L = (2.0 - 10.0) * 100 = -800
        assert pnl[0] == pytest.approx(-800.0)

    def test_multiple_contracts(self):
        """P&L scales with contracts."""
        pnl_1 = batch_calculate_pnl(
            entry_credits=np.array([2.0]),
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([0.0]),
            current_ivs=np.array([0.25]),
            contracts=np.array([1.0]),
        )
        pnl_5 = batch_calculate_pnl(
            entry_credits=np.array([2.0]),
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([0.0]),
            current_ivs=np.array([0.25]),
            contracts=np.array([5.0]),
        )
        assert pnl_5[0] == pytest.approx(5 * pnl_1[0])

    def test_slippage_applied_for_non_expired(self):
        """Non-expired positions incur exit slippage."""
        pnl_no_slip = batch_calculate_pnl(
            entry_credits=np.array([2.0]),
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([30.0]),
            current_ivs=np.array([0.25]),
            contracts=np.array([1.0]),
            slippage_pct=0.0,
        )
        pnl_with_slip = batch_calculate_pnl(
            entry_credits=np.array([2.0]),
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([30.0]),
            current_ivs=np.array([0.25]),
            contracts=np.array([1.0]),
            slippage_pct=1.5,
        )
        # Slippage reduces P&L
        assert pnl_with_slip[0] < pnl_no_slip[0]

    def test_no_slippage_at_expiration(self):
        """Expired positions should not incur slippage."""
        pnl_slip = batch_calculate_pnl(
            entry_credits=np.array([2.0]),
            current_prices=np.array([200.0]),
            short_strikes=np.array([180.0]),
            long_strikes=np.array([170.0]),
            dtes_remaining=np.array([0.0]),
            current_ivs=np.array([0.25]),
            contracts=np.array([1.0]),
            slippage_pct=10.0,  # Very high slippage
        )
        # Should still be full credit since expired
        assert pnl_slip[0] == pytest.approx(200.0)


# =============================================================================
# BATCH EXIT SIGNALS
# =============================================================================


class TestBatchCheckExitSignals:
    """Tests for batch_check_exit_signals()."""

    def _make_arrays(self, n=1, **overrides):
        """Helper to create default arrays."""
        defaults = {
            "current_prices": np.array([200.0] * n),
            "short_strikes": np.array([180.0] * n),
            "long_strikes": np.array([170.0] * n),
            "spread_widths": np.array([10.0] * n),
            "max_profits": np.array([200.0] * n),
            "max_losses": np.array([800.0] * n),
            "pnl_totals": np.array([0.0] * n),
            "dtes_remaining": np.array([45.0] * n),
        }
        defaults.update(overrides)
        return defaults

    def test_no_exit(self):
        """Normal position, no exit condition."""
        args = self._make_arrays()
        codes = batch_check_exit_signals(**args)
        assert codes[0] == 0

    def test_expiration_exit(self):
        """DTE = 0 → expiration (code 1)."""
        args = self._make_arrays(dtes_remaining=np.array([0.0]))
        codes = batch_check_exit_signals(**args)
        assert codes[0] == 1

    def test_profit_target_exit(self):
        """P&L >= 50% of max profit → profit target (code 2)."""
        args = self._make_arrays(pnl_totals=np.array([110.0]))  # 110/200 = 55%
        codes = batch_check_exit_signals(**args)
        assert codes[0] == 2

    def test_stop_loss_exit(self):
        """Loss >= 100% of max loss → stop loss (code 3)."""
        args = self._make_arrays(pnl_totals=np.array([-800.0]))  # 800/800 = 100%
        codes = batch_check_exit_signals(**args)
        assert codes[0] == 3

    def test_dte_threshold_exit(self):
        """DTE <= 7 (but > 0) → DTE threshold (code 4)."""
        args = self._make_arrays(dtes_remaining=np.array([5.0]))
        codes = batch_check_exit_signals(**args)
        assert codes[0] == 4

    def test_deep_itm_exit(self):
        """ITM amount >= 50% spread width → deep ITM (code 5)."""
        # short=180, current=173 → ITM by 7, spread_width=10, 7 >= 5
        args = self._make_arrays(current_prices=np.array([173.0]))
        codes = batch_check_exit_signals(**args)
        assert codes[0] == 5

    def test_expiration_has_highest_priority(self):
        """Expiration should override profit target."""
        args = self._make_arrays(
            dtes_remaining=np.array([0.0]),
            pnl_totals=np.array([110.0]),  # Also profit target
        )
        codes = batch_check_exit_signals(**args)
        assert codes[0] == 1  # Expiration, not profit target

    def test_profit_target_over_stop_loss(self):
        """When both profit and loss conditions met, profit target wins (earlier check)."""
        # This shouldn't happen in practice, but test priority
        args = self._make_arrays(
            pnl_totals=np.array([200.0]),  # 100% profit
            max_profits=np.array([200.0]),
            max_losses=np.array([100.0]),
        )
        codes = batch_check_exit_signals(**args)
        assert codes[0] == 2  # Profit target

    def test_multiple_positions_different_exits(self):
        """Multiple positions with different exit conditions."""
        codes = batch_check_exit_signals(
            current_prices=np.array([200.0, 200.0, 200.0, 200.0, 173.0]),
            short_strikes=np.array([180.0] * 5),
            long_strikes=np.array([170.0] * 5),
            spread_widths=np.array([10.0] * 5),
            max_profits=np.array([200.0] * 5),
            max_losses=np.array([800.0] * 5),
            pnl_totals=np.array([0.0, 110.0, -800.0, 0.0, 0.0]),
            dtes_remaining=np.array([45.0, 45.0, 45.0, 5.0, 45.0]),
        )
        assert codes[0] == 0  # No exit
        assert codes[1] == 2  # Profit target
        assert codes[2] == 3  # Stop loss
        assert codes[3] == 4  # DTE threshold
        assert codes[4] == 5  # Deep ITM

    def test_custom_thresholds(self):
        """Custom profit target and stop loss thresholds."""
        # P&L = 60, max_profit = 200 → 30% (below default 50%, but above custom 25%)
        args = self._make_arrays(pnl_totals=np.array([60.0]))
        codes = batch_check_exit_signals(**args, profit_target_pct=25.0)
        assert codes[0] == 2

    def test_zero_max_profit_no_division_error(self):
        """Zero max profit should not cause division error."""
        args = self._make_arrays(
            max_profits=np.array([0.0]),
            pnl_totals=np.array([50.0]),
        )
        codes = batch_check_exit_signals(**args)
        # pnl_pct = 0 when max_profits = 0 → no profit target
        assert codes[0] == 0


# =============================================================================
# EXIT CODE NAMES
# =============================================================================


class TestExitCodeNames:
    """Tests for EXIT_CODE_NAMES constant."""

    def test_all_codes_present(self):
        assert 0 in EXIT_CODE_NAMES
        assert 1 in EXIT_CODE_NAMES
        assert 2 in EXIT_CODE_NAMES
        assert 3 in EXIT_CODE_NAMES
        assert 4 in EXIT_CODE_NAMES
        assert 5 in EXIT_CODE_NAMES

    def test_code_0_is_none(self):
        assert EXIT_CODE_NAMES[0] is None

    def test_code_names(self):
        assert EXIT_CODE_NAMES[1] == "expiration"
        assert EXIT_CODE_NAMES[2] == "profit_target"
        assert EXIT_CODE_NAMES[3] == "stop_loss"
        assert EXIT_CODE_NAMES[4] == "dte_threshold"
        assert EXIT_CODE_NAMES[5] == "deep_itm"


# =============================================================================
# QUICK SPREAD PNL
# =============================================================================


class TestQuickSpreadPnl:
    """Tests for quick_spread_pnl()."""

    def test_profitable_position(self):
        """Price moved up → profitable."""
        pnl = quick_spread_pnl(
            underlying_price=180.0,
            short_strike=170.0,
            long_strike=160.0,
            dte_entry=60,
            dte_current=30,
            entry_price=180.0,
            current_price=190.0,
            entry_iv=0.25,
        )
        assert pnl > 0

    def test_losing_position(self):
        """Price dropped below short strike → losing."""
        pnl = quick_spread_pnl(
            underlying_price=180.0,
            short_strike=170.0,
            long_strike=160.0,
            dte_entry=60,
            dte_current=30,
            entry_price=180.0,
            current_price=165.0,
            entry_iv=0.25,
        )
        assert pnl < 0

    def test_at_expiration_otm(self):
        """OTM at expiration → full profit."""
        pnl = quick_spread_pnl(
            underlying_price=180.0,
            short_strike=170.0,
            long_strike=160.0,
            dte_entry=60,
            dte_current=0,
            entry_price=180.0,
            current_price=200.0,
            entry_iv=0.25,
        )
        assert pnl > 0

    def test_custom_iv(self):
        """Providing current_iv should not crash."""
        pnl = quick_spread_pnl(
            underlying_price=180.0,
            short_strike=170.0,
            long_strike=160.0,
            dte_entry=60,
            dte_current=30,
            entry_price=180.0,
            current_price=185.0,
            entry_iv=0.25,
            current_iv=0.30,
        )
        assert isinstance(pnl, float)

    def test_returns_float(self):
        pnl = quick_spread_pnl(
            underlying_price=180.0,
            short_strike=170.0,
            long_strike=160.0,
            dte_entry=60,
            dte_current=45,
            entry_price=180.0,
            current_price=180.0,
            entry_iv=0.25,
        )
        assert isinstance(pnl, float)
