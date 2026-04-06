"""
Integration Tests: Daily Picks → Validate → Monitor
=====================================================

End-to-end workflow tests for the 3 Jobs defined in UMBAUPLAN.
All external dependencies (API, DB, IBKR) are mocked.
Tests verify the logic chain, not API connectivity.

UMBAUPLAN Erfolgskriterium:
- "Zeig mir die heutigen Picks" → 3-5 Setups
- "Ich will MSFT traden" → GO / NO-GO mit Begründung
- "Wie stehen meine Positionen?" → HOLD / CLOSE / ROLL pro Position
"""

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

from src.constants.trading_rules import (
    TradeDecision,
    ExitAction,
    EXIT_FORCE_CLOSE_DTE,
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_STOP_LOSS_MULTIPLIER,
    EXIT_ROLL_DTE,
)
from src.services.trade_validator import (
    TradeValidator,
    TradeValidationRequest,
    ValidationCheck,
    get_trade_validator,
    reset_trade_validator,
)
from src.services.position_monitor import (
    PositionMonitor,
    PositionSnapshot,
    PositionSignal,
    MonitorResult,
    get_position_monitor,
    reset_position_monitor,
    snapshot_from_internal,
    estimate_pnl_from_theta,
)
from src.handlers.validate import ValidateHandlerMixin
from src.handlers.monitor import MonitorHandlerMixin


# =============================================================================
# HELPERS
# =============================================================================

def _safe_earnings_mock():
    """Earnings manager that always says safe (120 days away)."""
    mock = MagicMock()
    mock.is_earnings_day_safe.return_value = (True, 120, "safe")
    return mock


def _unsafe_earnings_mock(days=10):
    """Earnings manager that says NOT safe."""
    mock = MagicMock()
    mock.is_earnings_day_safe.return_value = (False, days, "too_close")
    return mock


def _fundamentals_mock(
    symbol="AAPL",
    stability_score=85.0,
    sector="Technology",
    historical_win_rate=90.0,
    avg_drawdown=3.5,
    current_price=180.0,
):
    """Create mock fundamentals data."""
    f = MagicMock()
    f.symbol = symbol
    f.stability_score = stability_score
    f.sector = sector
    f.historical_win_rate = historical_win_rate
    f.avg_drawdown = avg_drawdown
    f.market_cap_category = "Mega"
    f.current_price = current_price
    f.iv_rank_252d = 55.0
    f.beta = 1.1
    return f


def _fundamentals_manager_mock(fundamentals):
    """Create mock fundamentals manager returning given fundamentals."""
    mgr = MagicMock()
    mgr.get_fundamentals.return_value = fundamentals
    return mgr


def _make_snapshot(
    symbol="AAPL",
    dte=45,
    pnl_pct=20.0,
    short_strike=175.0,
    long_strike=170.0,
    net_credit=1.50,
    contracts=1,
    source="internal",
) -> PositionSnapshot:
    """Create a test position snapshot."""
    spread_width = short_strike - long_strike
    max_profit = net_credit * 100 * contracts
    max_loss = (spread_width - net_credit) * 100 * contracts
    exp = date.today() + timedelta(days=dte)

    return PositionSnapshot(
        position_id=f"test_{symbol}",
        symbol=symbol,
        short_strike=short_strike,
        long_strike=long_strike,
        spread_width=spread_width,
        net_credit=net_credit,
        contracts=contracts,
        expiration=exp.isoformat(),
        dte=dte,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=short_strike - net_credit,
        unrealized_pnl=pnl_pct / 100 * max_profit if pnl_pct else None,
        pnl_pct_of_max_profit=pnl_pct,
        source=source,
    )


def _make_validator(fundamentals, earnings=None, vix=None):
    """Create a TradeValidator with pre-set mocks."""
    v = TradeValidator()
    v._fundamentals_manager = _fundamentals_manager_mock(fundamentals)
    v._earnings_manager = earnings or _safe_earnings_mock()
    return v


def _make_monitor(earnings=None):
    """Create a PositionMonitor with pre-set earnings mock."""
    m = PositionMonitor()
    m._earnings_manager = earnings or _safe_earnings_mock()
    return m


# =============================================================================
# MOCK SERVERS
# =============================================================================

class MockValidateServer(ValidateHandlerMixin):
    """Minimal server with ValidateHandlerMixin."""

    def __init__(self, vix=18.0):
        self._ibkr_bridge = None
        self._vix = vix

    async def get_vix(self):
        return self._vix


class MockMonitorServer(MonitorHandlerMixin):
    """Minimal server with MonitorHandlerMixin."""

    def __init__(self, vix=18.0):
        self._ibkr_bridge = None
        self._vix = vix

    async def get_vix(self):
        return self._vix


# =============================================================================
# JOB 2: TRADE VALIDATOR WORKFLOW
# =============================================================================

class TestValidateWorkflow:
    """Job 2: 'Ich will MSFT traden' → GO / NO-GO mit Begründung."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_trade_validator()

    @pytest.mark.asyncio
    async def test_go_trade_all_rules_pass(self):
        """GO: Stable symbol, no earnings, normal VIX, not blacklisted."""
        fundamentals = _fundamentals_mock("AAPL", stability_score=85.0)
        validator = _make_validator(fundamentals)

        request = TradeValidationRequest(symbol="AAPL")
        result = await validator.validate(
            request=request, current_vix=18.0, open_positions=[]
        )

        assert result.decision == TradeDecision.GO

    @pytest.mark.asyncio
    async def test_no_go_blacklisted_symbol(self):
        """NO-GO: Blacklisted symbol (TSLA)."""
        fundamentals = _fundamentals_mock("TSLA", stability_score=60.0)
        validator = _make_validator(fundamentals)

        request = TradeValidationRequest(symbol="TSLA")
        result = await validator.validate(
            request=request, current_vix=18.0, open_positions=[]
        )

        assert result.decision == TradeDecision.NO_GO

    @pytest.mark.asyncio
    async def test_no_go_earnings_too_close(self):
        """NO-GO: Earnings within ENTRY_EARNINGS_MIN_DAYS."""
        fundamentals = _fundamentals_mock("MSFT", stability_score=88.0)
        earnings = _unsafe_earnings_mock(days=25)
        validator = _make_validator(fundamentals, earnings=earnings)

        request = TradeValidationRequest(symbol="MSFT")
        result = await validator.validate(
            request=request, current_vix=18.0, open_positions=[]
        )

        assert result.decision == TradeDecision.NO_GO

    @pytest.mark.asyncio
    async def test_no_go_low_stability(self):
        """NO-GO: Stability below 70."""
        fundamentals = _fundamentals_mock("XYZ", stability_score=55.0)
        validator = _make_validator(fundamentals)

        request = TradeValidationRequest(symbol="XYZ")
        result = await validator.validate(
            request=request, current_vix=18.0, open_positions=[]
        )

        assert result.decision == TradeDecision.NO_GO

    @pytest.mark.asyncio
    async def test_warning_vix_danger_zone(self):
        """VIX 22 = Danger Zone → elevated stability requirement."""
        # Stability 75 < 80 (Danger Zone minimum)
        fundamentals = _fundamentals_mock("AAPL", stability_score=75.0)
        validator = _make_validator(fundamentals)

        request = TradeValidationRequest(symbol="AAPL")
        result = await validator.validate(
            request=request, current_vix=22.0, open_positions=[]
        )

        # In Danger Zone, stability 75 < 80 required → NO-GO or WARNING
        assert result.decision in (TradeDecision.NO_GO, TradeDecision.WARNING)

    @pytest.mark.asyncio
    async def test_validate_handler_output_format(self):
        """Handler validate_trade returns formatted Markdown with decision."""
        server = MockValidateServer(vix=18.0)
        fundamentals = _fundamentals_mock("AAPL", stability_score=85.0)

        with patch("src.cache.get_fundamentals_manager") as fm, \
             patch("src.cache.get_earnings_history_manager") as em:
            fm.return_value = _fundamentals_manager_mock(fundamentals)
            em.return_value = _safe_earnings_mock()

            result = await server.validate_trade.__wrapped__(server, symbol="AAPL")

        assert "[GO]" in result
        assert "AAPL" in result
        # Contains VIX regime info
        assert "NORMAL" in result or "VIX" in result


# =============================================================================
# JOB 3: POSITION MONITOR WORKFLOW
# =============================================================================

class TestMonitorWorkflow:
    """Job 3: 'Wie stehen meine Positionen?' → HOLD / CLOSE / ROLL."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_position_monitor()

    @pytest.fixture
    def monitor(self):
        return _make_monitor()

    @pytest.mark.asyncio
    async def test_healthy_position_hold(self, monitor):
        """Healthy position (45 DTE, 20% profit, normal VIX) → HOLD."""
        snapshot = _make_snapshot(dte=45, pnl_pct=20.0)
        result = await monitor.check_positions([snapshot], current_vix=18.0)

        assert len(result.signals) == 1
        assert result.signals[0].action == ExitAction.HOLD

    @pytest.mark.asyncio
    async def test_profit_target_reached_close(self, monitor):
        """Profit >= 50% → CLOSE."""
        snapshot = _make_snapshot(dte=30, pnl_pct=55.0)
        result = await monitor.check_positions([snapshot], current_vix=18.0)

        assert len(result.signals) == 1
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority <= 3

    @pytest.mark.asyncio
    async def test_stop_loss_hit_close(self, monitor):
        """Loss >= 200% of credit → CLOSE."""
        snapshot = _make_snapshot(dte=30, pnl_pct=-210.0)
        result = await monitor.check_positions([snapshot], current_vix=18.0)

        assert len(result.signals) == 1
        assert result.signals[0].action == ExitAction.CLOSE

    @pytest.mark.asyncio
    async def test_21_dte_decision(self, monitor):
        """DTE <= 21 → ROLL or CLOSE."""
        snapshot = _make_snapshot(dte=18, pnl_pct=10.0)
        result = await monitor.check_positions([snapshot], current_vix=18.0)

        assert len(result.signals) == 1
        assert result.signals[0].action in (ExitAction.ROLL, ExitAction.CLOSE)

    @pytest.mark.asyncio
    async def test_force_close_7_dte(self, monitor):
        """DTE <= 7 → CLOSE (forced)."""
        snapshot = _make_snapshot(dte=5, pnl_pct=10.0)
        result = await monitor.check_positions([snapshot], current_vix=18.0)

        assert len(result.signals) == 1
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority <= 2

    @pytest.mark.asyncio
    async def test_expired_position_close(self, monitor):
        """DTE = 0 → CLOSE (expired)."""
        snapshot = _make_snapshot(dte=0, pnl_pct=50.0)
        result = await monitor.check_positions([snapshot], current_vix=18.0)

        assert len(result.signals) == 1
        assert result.signals[0].action == ExitAction.CLOSE
        assert result.signals[0].priority == 1

    @pytest.mark.asyncio
    async def test_high_vix_alert(self, monitor):
        """VIX > 30 + position in loss → ALERT."""
        snapshot = _make_snapshot(dte=45, pnl_pct=-30.0)
        result = await monitor.check_positions([snapshot], current_vix=32.0)

        assert len(result.signals) == 1
        assert result.signals[0].action in (ExitAction.ALERT, ExitAction.CLOSE)

    @pytest.mark.asyncio
    async def test_multiple_positions_mixed_signals(self, monitor):
        """Multiple positions get individual signals."""
        snapshots = [
            _make_snapshot(symbol="AAPL", dte=45, pnl_pct=20.0),
            _make_snapshot(symbol="MSFT", dte=30, pnl_pct=55.0),
            _make_snapshot(symbol="GOOGL", dte=5, pnl_pct=10.0),
        ]
        result = await monitor.check_positions(snapshots, current_vix=18.0)

        assert len(result.signals) == 3
        symbols = {s.symbol: s.action for s in result.signals}
        assert symbols["AAPL"] == ExitAction.HOLD
        assert symbols["MSFT"] == ExitAction.CLOSE
        assert symbols["GOOGL"] == ExitAction.CLOSE

    @pytest.mark.asyncio
    async def test_monitor_result_properties(self, monitor):
        """MonitorResult has correct summary properties."""
        snapshots = [
            _make_snapshot(symbol="AAPL", dte=45, pnl_pct=20.0),
            _make_snapshot(symbol="MSFT", dte=30, pnl_pct=55.0),
        ]
        result = await monitor.check_positions(snapshots, current_vix=18.0)

        assert result.positions_count == 2
        assert len(result.hold_signals) == 1
        assert len(result.close_signals) == 1


# =============================================================================
# MONITOR HANDLER INTEGRATION
# =============================================================================

class TestMonitorHandlerWorkflow:
    """Test Monitor handler Markdown output end-to-end."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_position_monitor()

    @pytest.fixture
    def server(self):
        return MockMonitorServer(vix=18.0)

    @pytest.mark.asyncio
    async def test_no_positions_message(self, server):
        """No positions → informative message."""
        with patch("src.portfolio.get_portfolio_manager") as mock_pm:
            mock_pm.return_value.get_open_positions.return_value = []

            result = await server.monitor_positions.__wrapped__(server)

        assert "Position Monitor" in result
        assert "Keine offenen Positionen" in result

    @pytest.mark.asyncio
    async def test_positions_show_signals(self, server):
        """Positions → each gets a signal in output."""
        mock_pm = MagicMock()
        mock_position = MagicMock()
        mock_position.id = "test_AAPL"
        mock_position.symbol = "AAPL"
        mock_position.short_leg = MagicMock()
        mock_position.short_leg.strike = 175.0
        mock_position.long_leg = MagicMock()
        mock_position.long_leg.strike = 170.0
        mock_position.spread_width = 5.0
        mock_position.net_credit = 1.50
        mock_position.contracts = 1
        mock_position.max_profit = 150.0
        mock_position.max_loss = 350.0
        mock_position.breakeven = 173.50
        mock_position.expiration = (date.today() + timedelta(days=45)).isoformat()
        mock_position.days_to_expiration = 45
        mock_pm.return_value.get_open_positions.return_value = [mock_position]

        with patch("src.portfolio.get_portfolio_manager", return_value=mock_pm.return_value), \
             patch("src.cache.get_earnings_history_manager", return_value=_safe_earnings_mock()):
            result = await server.monitor_positions.__wrapped__(server)

        assert "AAPL" in result
        assert "HOLD" in result or "CLOSE" in result


# =============================================================================
# FULL PIPELINE: VALIDATE → MONITOR
# =============================================================================

class TestFullPipelineWorkflow:
    """End-to-end: Validate a trade → Track position → Monitor exit signals."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_trade_validator()
        reset_position_monitor()

    @pytest.mark.asyncio
    async def test_validate_go_then_monitor_hold(self):
        """Validate GO → Position held → Monitor HOLD."""
        # Step 1: Validate
        fundamentals = _fundamentals_mock("AAPL", stability_score=85.0)
        validator = _make_validator(fundamentals)

        request = TradeValidationRequest(symbol="AAPL")
        result = await validator.validate(
            request=request, current_vix=18.0, open_positions=[]
        )
        assert result.decision == TradeDecision.GO

        # Step 2: Position opens — simulate a healthy 45 DTE position
        snapshot = _make_snapshot(symbol="AAPL", dte=45, pnl_pct=20.0)

        # Step 3: Monitor → HOLD
        monitor = _make_monitor()
        monitor_result = await monitor.check_positions([snapshot], current_vix=18.0)

        assert len(monitor_result.signals) == 1
        assert monitor_result.signals[0].action == ExitAction.HOLD
        assert monitor_result.signals[0].symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_validate_go_then_profit_target_close(self):
        """Validate GO → Profit target reached → Monitor CLOSE."""
        # Step 1: Validate
        fundamentals = _fundamentals_mock("MSFT", stability_score=90.0)
        validator = _make_validator(fundamentals)

        request = TradeValidationRequest(symbol="MSFT")
        result = await validator.validate(
            request=request, current_vix=18.0, open_positions=[]
        )
        assert result.decision == TradeDecision.GO

        # Step 2: Position reaches 55% profit
        snapshot = _make_snapshot(symbol="MSFT", dte=30, pnl_pct=55.0)

        # Step 3: Monitor → CLOSE
        monitor = _make_monitor()
        monitor_result = await monitor.check_positions([snapshot], current_vix=18.0)

        assert len(monitor_result.signals) == 1
        assert monitor_result.signals[0].action == ExitAction.CLOSE
        assert monitor_result.signals[0].symbol == "MSFT"

    @pytest.mark.asyncio
    async def test_validate_no_go_prevents_trade(self):
        """Validate NO-GO → Trade should not be opened."""
        fundamentals = _fundamentals_mock("TSLA", stability_score=40.0)
        validator = _make_validator(fundamentals)

        request = TradeValidationRequest(symbol="TSLA")
        result = await validator.validate(
            request=request, current_vix=18.0, open_positions=[]
        )

        # TSLA is blacklisted → NO-GO
        assert result.decision == TradeDecision.NO_GO

    @pytest.mark.asyncio
    async def test_exit_priority_order(self):
        """Exit signals follow PLAYBOOK priority: expired > force close > profit > hold."""
        monitor = _make_monitor()

        expired = _make_snapshot(symbol="EXPIRED", dte=0, pnl_pct=50.0)
        force_close = _make_snapshot(symbol="FORCED", dte=5, pnl_pct=10.0)
        profit = _make_snapshot(symbol="PROFIT", dte=30, pnl_pct=55.0)
        healthy = _make_snapshot(symbol="HOLD", dte=45, pnl_pct=20.0)

        result = await monitor.check_positions(
            [expired, force_close, profit, healthy],
            current_vix=18.0,
        )

        signals = {s.symbol: s for s in result.signals}

        assert signals["EXPIRED"].action == ExitAction.CLOSE
        assert signals["EXPIRED"].priority == 1
        assert signals["FORCED"].action == ExitAction.CLOSE
        assert signals["FORCED"].priority == 2
        assert signals["PROFIT"].action == ExitAction.CLOSE
        assert signals["PROFIT"].priority == 3
        assert signals["HOLD"].action == ExitAction.HOLD


# =============================================================================
# VIX REGIME IMPACT ON DECISIONS
# =============================================================================

class TestVixRegimeIntegration:
    """VIX regime affects both validation and monitoring decisions."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_trade_validator()
        reset_position_monitor()

    @pytest.mark.asyncio
    async def test_high_vix_no_new_trades(self):
        """VIX > 30 → no new trades allowed."""
        fundamentals = _fundamentals_mock("AAPL", stability_score=90.0)
        validator = _make_validator(fundamentals)

        request = TradeValidationRequest(symbol="AAPL")
        result = await validator.validate(
            request=request, current_vix=32.0, open_positions=[]
        )

        assert result.decision in (TradeDecision.NO_GO, TradeDecision.WARNING)

    @pytest.mark.asyncio
    async def test_high_vix_monitor_alert(self):
        """VIX > 30 + position in loss → ALERT or CLOSE."""
        monitor = _make_monitor()

        snapshot = _make_snapshot(dte=45, pnl_pct=-20.0)
        result = await monitor.check_positions([snapshot], current_vix=32.0)

        assert len(result.signals) == 1
        assert result.signals[0].action in (ExitAction.ALERT, ExitAction.CLOSE)

    @pytest.mark.asyncio
    async def test_normal_vix_profit_target_50pct(self):
        """VIX < 20 → normal 50% profit target."""
        monitor = _make_monitor()

        # 45% profit → not yet at 50% target
        below_target = _make_snapshot(dte=30, pnl_pct=45.0)
        result = await monitor.check_positions([below_target], current_vix=18.0)
        assert result.signals[0].action == ExitAction.HOLD

        # 55% profit → above 50% target
        above_target = _make_snapshot(dte=30, pnl_pct=55.0)
        result = await monitor.check_positions([above_target], current_vix=18.0)
        assert result.signals[0].action == ExitAction.CLOSE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
