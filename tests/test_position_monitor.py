"""
Tests for src/services/position_monitor.py

Tests the PositionMonitor service — exit signal generation per PLAYBOOK §4.
"""

import math
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

from src.constants.trading_rules import (
    ExitAction,
    EXIT_FORCE_CLOSE_DTE,
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_STOP_LOSS_MULTIPLIER,
    EXIT_ROLL_DTE,
    ROLL_NEW_DTE_MAX,
    VIX_ELEVATED_MAX,
)
from src.services.position_monitor import (
    PositionMonitor,
    PositionSnapshot,
    PositionSignal,
    MonitorResult,
    get_position_monitor,
    reset_position_monitor,
    snapshot_from_internal,
    snapshot_from_ibkr,
    estimate_pnl_from_theta,
)


# =============================================================================
# FIXTURES
# =============================================================================

def make_snapshot(
    symbol="AAPL",
    dte=45,
    pnl_pct=None,
    unrealized_pnl=None,
    short_strike=180.0,
    long_strike=170.0,
    net_credit=2.50,
    contracts=1,
    source="internal",
    position_id=None,
) -> PositionSnapshot:
    """Helper to create test snapshots."""
    spread_width = short_strike - long_strike
    max_profit = net_credit * contracts * 100
    max_loss = (spread_width - net_credit) * contracts * 100
    exp_date = (date.today() + timedelta(days=dte)).isoformat()

    return PositionSnapshot(
        position_id=position_id or f"test_{symbol}_{dte}",
        symbol=symbol,
        short_strike=short_strike,
        long_strike=long_strike,
        spread_width=spread_width,
        net_credit=net_credit,
        contracts=contracts,
        expiration=exp_date,
        dte=dte,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=short_strike - net_credit,
        source=source,
        pnl_pct_of_max_profit=pnl_pct,
        unrealized_pnl=unrealized_pnl,
    )


def _safe_earnings_mock():
    """Returns a mock earnings manager that always reports 'safe'."""
    mock = MagicMock()
    mock.is_earnings_day_safe.return_value = (True, 120, "safe")
    return mock


@pytest.fixture
def monitor():
    """Fresh PositionMonitor for each test.

    Uses a mock earnings manager that always returns safe,
    so earnings check doesn't interfere with other tests.
    """
    reset_position_monitor()
    m = PositionMonitor()
    m._earnings_manager = _safe_earnings_mock()
    return m


# =============================================================================
# SNAPSHOT BUILDERS
# =============================================================================

class TestSnapshotFromInternal:
    """Test snapshot_from_internal builder."""

    def test_basic_conversion(self):
        """BullPutSpread converts to PositionSnapshot."""
        pos = MagicMock()
        pos.id = "abc123"
        pos.symbol = "AAPL"
        pos.short_leg.strike = 180.0
        pos.long_leg.strike = 170.0
        pos.spread_width = 10.0
        pos.net_credit = 2.50
        pos.contracts = 2
        pos.expiration = "2026-04-17"
        pos.days_to_expiration = 73
        pos.max_profit = 500.0
        pos.max_loss = 1500.0
        pos.breakeven = 177.50

        snap = snapshot_from_internal(pos)

        assert snap.position_id == "abc123"
        assert snap.symbol == "AAPL"
        assert snap.short_strike == 180.0
        assert snap.long_strike == 170.0
        assert snap.spread_width == 10.0
        assert snap.net_credit == 2.50
        assert snap.contracts == 2
        assert snap.dte == 73
        assert snap.source == "internal"
        assert snap.pnl_pct_of_max_profit is None


class TestSnapshotFromIbkr:
    """Test snapshot_from_ibkr builder."""

    def test_yyyymmdd_format(self):
        """IBKR YYYYMMDD expiry is converted to YYYY-MM-DD."""
        spread = {
            "symbol": "MSFT",
            "expiry": "20260417",
            "short_strike": 400.0,
            "long_strike": 390.0,
            "width": 10.0,
            "net_credit": 3.0,
            "contracts": 1,
        }
        snap = snapshot_from_ibkr(spread)

        assert snap.expiration == "2026-04-17"
        assert snap.symbol == "MSFT"
        assert snap.short_strike == 400.0
        assert snap.long_strike == 390.0
        assert snap.source == "ibkr"
        assert "ibkr_" in snap.position_id

    def test_already_formatted_date(self):
        """Handles already formatted YYYY-MM-DD dates."""
        spread = {
            "symbol": "AAPL",
            "expiry": "2026-04-17",
            "short_strike": 180.0,
            "long_strike": 170.0,
            "width": 10.0,
            "net_credit": 2.50,
            "contracts": 1,
        }
        snap = snapshot_from_ibkr(spread)
        assert snap.expiration == "2026-04-17"

    def test_max_profit_calculation(self):
        """Max profit = net_credit * contracts * 100."""
        spread = {
            "symbol": "AAPL",
            "expiry": "20260617",
            "short_strike": 180.0,
            "long_strike": 170.0,
            "width": 10.0,
            "net_credit": 2.50,
            "contracts": 2,
        }
        snap = snapshot_from_ibkr(spread)
        assert snap.max_profit == 500.0
        assert snap.max_loss == 1500.0
        assert snap.breakeven == 177.5


class TestEstimatePnlFromTheta:
    """Test theta decay approximation."""

    def test_expired_position(self):
        """DTE <= 0 → 100% profit."""
        snap = make_snapshot(dte=0)
        estimate_pnl_from_theta(snap)

        assert snap.pnl_pct_of_max_profit == 100.0
        assert snap.unrealized_pnl == snap.max_profit
        assert snap.pnl_estimated is True

    def test_fresh_position(self):
        """Position just opened (dte=75) → ~0% profit."""
        snap = make_snapshot(dte=75)
        estimate_pnl_from_theta(snap)

        assert snap.pnl_pct_of_max_profit == 0.0
        assert snap.pnl_estimated is True

    def test_half_time_position(self):
        """Midpoint (~37 DTE) → ~71% profit via sqrt model."""
        snap = make_snapshot(dte=38)  # 75-38=37 elapsed
        estimate_pnl_from_theta(snap)

        # sqrt(37/75) ≈ 0.702 → ~70%
        assert 65.0 <= snap.pnl_pct_of_max_profit <= 75.0
        assert snap.pnl_estimated is True

    def test_near_expiration(self):
        """10 DTE → high profit estimate."""
        snap = make_snapshot(dte=10)
        estimate_pnl_from_theta(snap)

        # sqrt(65/75) ≈ 0.93 → ~93%
        assert snap.pnl_pct_of_max_profit >= 90.0

    def test_returns_snapshot(self):
        """Modifies in-place and returns the snapshot."""
        snap = make_snapshot(dte=30)
        result = estimate_pnl_from_theta(snap)
        assert result is snap


# =============================================================================
# EXIT CHECKS
# =============================================================================

class TestCheckExpired:
    """Priority 1: Expired positions."""

    @pytest.mark.asyncio
    async def test_expired_is_close(self, monitor):
        snap = make_snapshot(dte=0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 1
        assert "ABGELAUFEN" in result.signals[0].reason

    @pytest.mark.asyncio
    async def test_negative_dte_is_close(self, monitor):
        snap = make_snapshot(dte=-3)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 1

    @pytest.mark.asyncio
    async def test_positive_dte_not_expired(self, monitor):
        snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].priority != 1


class TestCheckForceClose:
    """Priority 2: Force close at DTE <= 7."""

    @pytest.mark.asyncio
    async def test_dte_7_is_force_close(self, monitor):
        snap = make_snapshot(dte=7, pnl_pct=20.0, unrealized_pnl=50.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 2
        assert "FORCE CLOSE" in result.signals[0].reason

    @pytest.mark.asyncio
    async def test_dte_5_is_force_close(self, monitor):
        snap = make_snapshot(dte=5)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 2

    @pytest.mark.asyncio
    async def test_dte_8_not_force_close(self, monitor):
        snap = make_snapshot(dte=8, pnl_pct=20.0, unrealized_pnl=50.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].priority != 2

    @pytest.mark.asyncio
    async def test_uses_playbook_constant(self, monitor):
        """Force close uses EXIT_FORCE_CLOSE_DTE = 7."""
        assert EXIT_FORCE_CLOSE_DTE == 7


class TestCheckProfitTarget:
    """Priority 3: Profit target reached."""

    @pytest.mark.asyncio
    async def test_profit_50pct_at_normal_vix(self, monitor):
        """50% profit → CLOSE at VIX 18 (normal regime)."""
        snap = make_snapshot(dte=45, pnl_pct=55.0, unrealized_pnl=137.5)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 3
        assert "PROFIT TARGET" in result.signals[0].reason

    @pytest.mark.asyncio
    async def test_profit_30pct_at_danger_zone(self, monitor):
        """30% profit → CLOSE at VIX 22 (danger zone, target=30%)."""
        snap = make_snapshot(dte=45, pnl_pct=35.0, unrealized_pnl=87.5)
        result = await monitor.check_positions([snap], current_vix=22.0)
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 3

    @pytest.mark.asyncio
    async def test_profit_below_target_is_hold(self, monitor):
        """40% profit at VIX 18 (target=50%) → HOLD."""
        snap = make_snapshot(dte=45, pnl_pct=40.0, unrealized_pnl=100.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.HOLD

    @pytest.mark.asyncio
    async def test_high_vix_close_all_winners(self, monitor):
        """VIX > 30 regime: profit_exit_pct=0, close all winners."""
        snap = make_snapshot(dte=45, pnl_pct=10.0, unrealized_pnl=25.0)
        result = await monitor.check_positions([snap], current_vix=32.0)
        signal = result.signals[0]
        # Should be caught by either profit target (prio 3) or high VIX (prio 6)
        assert signal.action == ExitAction.CLOSE

    @pytest.mark.asyncio
    async def test_no_pnl_data_skips(self, monitor):
        """Without P&L data, profit check is skipped."""
        snap = make_snapshot(dte=45, pnl_pct=None)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.HOLD


class TestCheckStopLoss:
    """Priority 4: Stop loss at 200% of credit."""

    @pytest.mark.asyncio
    async def test_loss_exceeds_200pct(self, monitor):
        """Loss >= 2x credit → CLOSE."""
        # net_credit=2.50, contracts=1 → credit=$250
        # Stop loss = $250 * 2.0 = $500
        # unrealized_pnl = -$500 → loss = $500 >= $500 → trigger
        snap = make_snapshot(dte=45, pnl_pct=-200.0, unrealized_pnl=-500.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 4
        assert "STOP LOSS" in result.signals[0].reason

    @pytest.mark.asyncio
    async def test_loss_below_stop(self, monitor):
        """Loss < 2x credit → not triggered."""
        snap = make_snapshot(dte=45, pnl_pct=-50.0, unrealized_pnl=-125.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.HOLD

    @pytest.mark.asyncio
    async def test_uses_playbook_multiplier(self, monitor):
        """Stop loss multiplier = 2.0 (PLAYBOOK §4)."""
        assert EXIT_STOP_LOSS_MULTIPLIER == 2.0


class TestCheck21DTEDecision:
    """Priority 5: 21 DTE decision point — roll or close."""

    @pytest.mark.asyncio
    async def test_21dte_profitable_rollable_is_roll(self, monitor):
        """At 21 DTE, profitable + can roll → ROLL."""
        snap = make_snapshot(dte=20, pnl_pct=30.0, unrealized_pnl=75.0)
        with patch("src.utils.validation.is_etf", return_value=False):
            result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.ROLL
        assert result.signals[0].priority == 5

    @pytest.mark.asyncio
    async def test_21dte_losing_is_close(self, monitor):
        """At 21 DTE, in loss → CLOSE."""
        snap = make_snapshot(dte=18, pnl_pct=-20.0, unrealized_pnl=-50.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 5
        assert "im Verlust" in result.signals[0].reason

    @pytest.mark.asyncio
    async def test_21dte_profitable_high_vix_no_roll(self, monitor):
        """At 21 DTE, profitable but VIX > 30 → can't roll → CLOSE."""
        snap = make_snapshot(dte=18, pnl_pct=30.0, unrealized_pnl=75.0)
        # VIX=32 means _can_roll returns False
        result = await monitor.check_positions([snap], current_vix=32.0)
        signal = result.signals[0]
        # Either caught by profit target (prio 3, vix regime 0%) or 21DTE (prio 5)
        assert signal.action == ExitAction.CLOSE

    @pytest.mark.asyncio
    async def test_above_21dte_not_triggered(self, monitor):
        """DTE > 21 → not triggered."""
        snap = make_snapshot(dte=25, pnl_pct=30.0, unrealized_pnl=75.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].priority != 5

    @pytest.mark.asyncio
    async def test_uses_roll_dte_constant(self, monitor):
        """Roll DTE = 21 (PLAYBOOK §4)."""
        assert EXIT_ROLL_DTE == 21


class TestCheckHighVIX:
    """Priority 6: VIX > 30 — close winners, alert losers."""

    @pytest.mark.asyncio
    async def test_vix_31_winner_is_close(self, monitor):
        """VIX > 30, profitable → CLOSE."""
        snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        result = await monitor.check_positions([snap], current_vix=31.0)
        signal = result.signals[0]
        assert signal.action == ExitAction.CLOSE
        assert "HIGH VIX" in signal.reason or "VIX-Regime" in signal.reason

    @pytest.mark.asyncio
    async def test_vix_31_loser_is_alert(self, monitor):
        """VIX > 30, in loss → ALERT."""
        snap = make_snapshot(dte=45, pnl_pct=-20.0, unrealized_pnl=-50.0)
        result = await monitor.check_positions([snap], current_vix=31.0)
        signal = result.signals[0]
        # Either caught by high VIX (prio 6) as ALERT or by profit target exit
        assert signal.action in (ExitAction.ALERT, ExitAction.CLOSE)

    @pytest.mark.asyncio
    async def test_vix_below_30_not_triggered(self, monitor):
        """VIX 28 → high VIX check not triggered."""
        snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        result = await monitor.check_positions([snap], current_vix=28.0)
        assert result.signals[0].action == ExitAction.HOLD

    @pytest.mark.asyncio
    async def test_uses_vix_elevated_max(self, monitor):
        """VIX threshold = 30.0 (VIX_ELEVATED_MAX)."""
        assert VIX_ELEVATED_MAX == 30.0


class TestCheckEarningsRisk:
    """Priority 7: Earnings before expiration."""

    @pytest.mark.asyncio
    async def test_earnings_before_expiration_is_close(self, monitor):
        """Earnings falling before expiration → CLOSE."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.return_value = (False, 30, "too_close")
        monitor._earnings_manager = mock_earnings

        snap = make_snapshot(dte=45)
        with patch("src.utils.validation.is_etf", return_value=False):
            result = await monitor.check_positions([snap], current_vix=18.0)

        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 7
        assert "EARNINGS" in result.signals[0].reason

    @pytest.mark.asyncio
    async def test_earnings_after_expiration_is_hold(self, monitor):
        """Earnings after expiration → no signal."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.return_value = (True, 60, "safe")
        monitor._earnings_manager = mock_earnings

        snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        with patch("src.utils.validation.is_etf", return_value=False):
            result = await monitor.check_positions([snap], current_vix=18.0)

        assert result.signals[0].action == ExitAction.HOLD

    @pytest.mark.asyncio
    async def test_etf_skips_earnings(self, monitor):
        """ETFs have no earnings — skip check."""
        snap = make_snapshot(symbol="SPY", dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        with patch("src.utils.validation.is_etf", return_value=True):
            result = await monitor.check_positions([snap], current_vix=18.0)

        assert result.signals[0].action == ExitAction.HOLD

    @pytest.mark.asyncio
    async def test_no_earnings_manager_is_hold(self, monitor):
        """Without earnings manager, check is skipped."""
        # Force earnings property to return None (prevent lazy-loading)
        with patch.object(type(monitor), 'earnings', new_callable=lambda: property(lambda self: None)):
            snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
            with patch("src.utils.validation.is_etf", return_value=False):
                result = await monitor.check_positions([snap], current_vix=18.0)

            assert result.signals[0].action == ExitAction.HOLD

    @pytest.mark.asyncio
    async def test_earnings_exception_is_skipped(self, monitor):
        """Earnings check exception → skip, don't crash."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.side_effect = Exception("DB error")
        monitor._earnings_manager = mock_earnings

        snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        with patch("src.utils.validation.is_etf", return_value=False):
            result = await monitor.check_positions([snap], current_vix=18.0)

        assert result.signals[0].action == ExitAction.HOLD


class TestCanRoll:
    """Test _can_roll logic (roll eligibility)."""

    def test_normal_vix_allows_roll(self, monitor):
        """Normal VIX + no earnings conflict → roll allowed."""
        snap = make_snapshot(dte=20)
        # Earnings manager already set to safe in fixture
        with patch("src.utils.validation.is_etf", return_value=False):
            result = monitor._can_roll(snap, current_vix=18.0)
        assert result is True

    def test_high_vix_blocks_roll(self, monitor):
        """VIX >= 30 → no rolling."""
        snap = make_snapshot(dte=20)
        assert monitor._can_roll(snap, current_vix=30.0) is False

    def test_vix_none_allows_roll(self, monitor):
        """No VIX data → allow roll."""
        snap = make_snapshot(dte=20)
        with patch("src.utils.validation.is_etf", return_value=True):
            assert monitor._can_roll(snap, current_vix=None) is True

    def test_earnings_in_roll_window_blocks(self, monitor):
        """Earnings in new 60-90 DTE window → no roll."""
        mock_earnings = MagicMock()
        mock_earnings.is_earnings_day_safe.return_value = (False, 70, "too_close")
        monitor._earnings_manager = mock_earnings

        snap = make_snapshot(dte=20, symbol="AAPL")
        with patch("src.utils.validation.is_etf", return_value=False):
            assert monitor._can_roll(snap, current_vix=18.0) is False

    def test_etf_skips_earnings_for_roll(self, monitor):
        """ETFs skip earnings check for roll."""
        snap = make_snapshot(dte=20, symbol="SPY")
        with patch("src.utils.validation.is_etf", return_value=True):
            assert monitor._can_roll(snap, current_vix=18.0) is True


class TestCanRollStability:
    """Test _can_roll stability re-validation (Task 4.3)."""

    def test_low_stability_blocks_roll(self, monitor):
        """Symbol with stability < 70 → roll blocked."""
        mock_fund = MagicMock()
        mock_f = MagicMock()
        mock_f.stability_score = 55.0  # Below minimum 70
        mock_fund.get_fundamentals.return_value = mock_f
        monitor._fundamentals_manager = mock_fund

        snap = make_snapshot(dte=20, symbol="WEAK")
        with patch("src.utils.validation.is_etf", return_value=False):
            result = monitor._can_roll(snap, current_vix=18.0)
        assert result is False

    def test_high_stability_allows_roll(self, monitor):
        """Symbol with stability >= 70 → roll allowed."""
        mock_fund = MagicMock()
        mock_f = MagicMock()
        mock_f.stability_score = 85.0  # Above minimum
        mock_fund.get_fundamentals.return_value = mock_f
        monitor._fundamentals_manager = mock_fund

        snap = make_snapshot(dte=20, symbol="STRONG")
        with patch("src.utils.validation.is_etf", return_value=False):
            result = monitor._can_roll(snap, current_vix=18.0)
        assert result is True

    def test_danger_zone_vix_raises_stability_min(self, monitor):
        """VIX 22 (Danger Zone) → stability min 80, blocks 75-stability symbol."""
        mock_fund = MagicMock()
        mock_f = MagicMock()
        mock_f.stability_score = 75.0  # Above 70 but below 80
        mock_fund.get_fundamentals.return_value = mock_f
        monitor._fundamentals_manager = mock_fund

        snap = make_snapshot(dte=20, symbol="MID")
        with patch("src.utils.validation.is_etf", return_value=False):
            result = monitor._can_roll(snap, current_vix=22.0)
        assert result is False

    def test_danger_zone_vix_allows_high_stability(self, monitor):
        """VIX 22 (Danger Zone) → stability 85 >= 80 → allowed."""
        mock_fund = MagicMock()
        mock_f = MagicMock()
        mock_f.stability_score = 85.0
        mock_fund.get_fundamentals.return_value = mock_f
        monitor._fundamentals_manager = mock_fund

        snap = make_snapshot(dte=20, symbol="STRONG")
        with patch("src.utils.validation.is_etf", return_value=False):
            result = monitor._can_roll(snap, current_vix=22.0)
        assert result is True

    def test_no_fundamentals_allows_roll(self, monitor):
        """No fundamentals manager → allow roll (conservative)."""
        monitor._fundamentals_manager = None

        snap = make_snapshot(dte=20)
        with patch("src.utils.validation.is_etf", return_value=True):
            result = monitor._can_roll(snap, current_vix=18.0)
        assert result is True

    def test_fundamentals_exception_allows_roll(self, monitor):
        """Fundamentals exception → allow roll."""
        mock_fund = MagicMock()
        mock_fund.get_fundamentals.side_effect = Exception("DB error")
        monitor._fundamentals_manager = mock_fund

        snap = make_snapshot(dte=20, symbol="ERR")
        with patch("src.utils.validation.is_etf", return_value=False):
            result = monitor._can_roll(snap, current_vix=18.0)
        assert result is True

    def test_no_stability_score_allows_roll(self, monitor):
        """Symbol without stability_score → allow roll."""
        mock_fund = MagicMock()
        mock_f = MagicMock()
        mock_f.stability_score = None
        mock_fund.get_fundamentals.return_value = mock_f
        monitor._fundamentals_manager = mock_fund

        snap = make_snapshot(dte=20, symbol="NOSCORE")
        with patch("src.utils.validation.is_etf", return_value=False):
            result = monitor._can_roll(snap, current_vix=18.0)
        assert result is True

    def test_acceptance_stability_below_70_blocked(self, monitor):
        """TASKS acceptance: Roll rejected when stability < 70."""
        mock_fund = MagicMock()
        mock_f = MagicMock()
        mock_f.stability_score = 65.0
        mock_fund.get_fundamentals.return_value = mock_f
        monitor._fundamentals_manager = mock_fund

        snap = make_snapshot(dte=20, symbol="LOWSTAB")
        with patch("src.utils.validation.is_etf", return_value=False):
            result = monitor._can_roll(snap, current_vix=18.0)
        assert result is False


# =============================================================================
# MONITOR RESULT
# =============================================================================

class TestMonitorResult:
    """Test MonitorResult dataclass properties."""

    def test_close_signals(self):
        signals = [
            PositionSignal("1", "AAPL", ExitAction.CLOSE, "test", 2, 5),
            PositionSignal("2", "MSFT", ExitAction.HOLD, "test", 8, 45),
            PositionSignal("3", "JPM", ExitAction.CLOSE, "test", 3, 7),
        ]
        result = MonitorResult(signals=signals, positions_count=3)
        assert len(result.close_signals) == 2
        assert len(result.hold_signals) == 1

    def test_roll_signals(self):
        signals = [
            PositionSignal("1", "AAPL", ExitAction.ROLL, "test", 5, 20),
            PositionSignal("2", "MSFT", ExitAction.HOLD, "test", 8, 45),
        ]
        result = MonitorResult(signals=signals, positions_count=2)
        assert len(result.roll_signals) == 1

    def test_alert_signals(self):
        signals = [
            PositionSignal("1", "AAPL", ExitAction.ALERT, "test", 6, 45),
        ]
        result = MonitorResult(signals=signals, positions_count=1)
        assert len(result.alert_signals) == 1

    def test_empty_result(self):
        result = MonitorResult(signals=[], positions_count=0)
        assert len(result.close_signals) == 0
        assert len(result.roll_signals) == 0
        assert len(result.alert_signals) == 0
        assert len(result.hold_signals) == 0


# =============================================================================
# FULL MONITORING
# =============================================================================

class TestCheckPositions:
    """Integration tests for full position checking."""

    @pytest.mark.asyncio
    async def test_multiple_positions(self, monitor):
        """Monitor multiple positions at once."""
        snapshots = [
            make_snapshot(symbol="AAPL", dte=45, pnl_pct=20.0, unrealized_pnl=50.0),
            make_snapshot(symbol="MSFT", dte=5, pnl_pct=80.0, unrealized_pnl=200.0),
            make_snapshot(symbol="JPM", dte=0),
        ]
        result = await monitor.check_positions(snapshots, current_vix=18.0)

        assert result.positions_count == 3
        assert len(result.signals) == 3

        # Should be sorted by priority
        assert result.signals[0].priority <= result.signals[1].priority
        assert result.signals[1].priority <= result.signals[2].priority

    @pytest.mark.asyncio
    async def test_regime_info(self, monitor):
        """Result includes VIX regime info."""
        snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        result = await monitor.check_positions([snap], current_vix=18.0)

        assert result.vix == 18.0
        assert "NORMAL" in result.regime
        assert result.timestamp is not None

    @pytest.mark.asyncio
    async def test_no_vix_still_works(self, monitor):
        """Monitor works without VIX (regime=None)."""
        snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        result = await monitor.check_positions([snap], current_vix=None)

        assert result.regime is None
        assert len(result.signals) == 1

    @pytest.mark.asyncio
    async def test_empty_positions(self, monitor):
        """Empty position list returns empty result."""
        result = await monitor.check_positions([], current_vix=18.0)
        assert result.positions_count == 0
        assert len(result.signals) == 0

    @pytest.mark.asyncio
    async def test_priority_order_expired_before_force_close(self, monitor):
        """Expired (prio 1) beats force close (prio 2)."""
        snap = make_snapshot(dte=0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].priority == 1  # expired, not force close


class TestDefaultHold:
    """Priority 8: Default HOLD signal."""

    @pytest.mark.asyncio
    async def test_normal_position_is_hold(self, monitor):
        """Position with nothing notable → HOLD."""
        snap = make_snapshot(dte=45, pnl_pct=20.0, unrealized_pnl=50.0)
        result = await monitor.check_positions([snap], current_vix=18.0)
        assert result.signals[0].action == ExitAction.HOLD
        assert result.signals[0].priority == 8


# =============================================================================
# FACTORY
# =============================================================================

class TestFactory:
    """Test singleton factory."""

    def test_get_position_monitor(self):
        reset_position_monitor()
        m1 = get_position_monitor()
        m2 = get_position_monitor()
        assert m1 is m2

    def test_reset_position_monitor(self):
        reset_position_monitor()
        m1 = get_position_monitor()
        reset_position_monitor()
        m2 = get_position_monitor()
        assert m1 is not m2
