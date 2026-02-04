"""
Tests for src/handlers/monitor.py

Tests the MonitorHandlerMixin — MCP endpoint for position monitoring.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.constants.trading_rules import ExitAction
from src.services.position_monitor import (
    PositionSnapshot,
    PositionSignal,
    MonitorResult,
    reset_position_monitor,
)
from src.handlers.monitor import MonitorHandlerMixin


# =============================================================================
# MOCK SERVER
# =============================================================================

class MockServer(MonitorHandlerMixin):
    """Minimal mock server with the MonitorHandlerMixin."""

    def __init__(self):
        self._ibkr_bridge = None

    async def get_vix(self):
        """Return a fixed VIX for testing."""
        return 18.0


@pytest.fixture
def server():
    """Fresh mock server for each test."""
    reset_position_monitor()
    return MockServer()


def _make_signal(
    symbol="AAPL",
    action=ExitAction.HOLD,
    priority=8,
    dte=45,
    pnl_pct=20.0,
    reason="Test reason",
) -> PositionSignal:
    """Helper to create test signals."""
    return PositionSignal(
        position_id=f"test_{symbol}",
        symbol=symbol,
        action=action,
        reason=reason,
        priority=priority,
        dte=dte,
        pnl_pct=pnl_pct,
    )


# =============================================================================
# FORMAT TESTS
# =============================================================================

class TestFormatMonitorResult:
    """Test _format_monitor_result Markdown output."""

    def test_empty_result(self, server):
        """No positions → shows count 0."""
        result = MonitorResult(signals=[], positions_count=0)
        output = server._format_monitor_result(result)

        assert "Position Monitor" in output
        assert "0 Positionen" in output
        assert "0 CLOSE" in output

    def test_hold_only(self, server):
        """All positions HOLD → shows in Halten section."""
        result = MonitorResult(
            signals=[
                _make_signal("AAPL", ExitAction.HOLD, 8, 45, 20.0),
                _make_signal("MSFT", ExitAction.HOLD, 8, 60, 15.0),
            ],
            positions_count=2,
            regime="NORMAL (VIX 18.0)",
        )
        output = server._format_monitor_result(result)

        assert "2 Positionen" in output
        assert "0 CLOSE" in output
        assert "2 HOLD" in output
        assert "Halten" in output
        assert "AAPL" in output
        assert "MSFT" in output
        assert "NORMAL" in output

    def test_close_signals(self, server):
        """CLOSE signals appear in Aktionen section."""
        result = MonitorResult(
            signals=[
                _make_signal("AAPL", ExitAction.CLOSE, 2, 5, 80.0, "FORCE CLOSE — DTE 5"),
                _make_signal("MSFT", ExitAction.HOLD, 8, 45, 20.0),
            ],
            positions_count=2,
        )
        output = server._format_monitor_result(result)

        assert "1 CLOSE" in output
        assert "1 HOLD" in output
        assert "Aktionen erforderlich" in output
        assert "[CLOSE]" in output
        assert "FORCE CLOSE" in output
        assert "AAPL" in output

    def test_roll_signals(self, server):
        """ROLL signals appear in Aktionen section."""
        result = MonitorResult(
            signals=[
                _make_signal("AAPL", ExitAction.ROLL, 5, 20, 30.0, "21-DTE ROLL"),
            ],
            positions_count=1,
        )
        output = server._format_monitor_result(result)

        assert "1 ROLL" in output
        assert "[ROLL]" in output
        assert "21-DTE ROLL" in output

    def test_alert_signals(self, server):
        """ALERT signals appear in Aktionen section."""
        result = MonitorResult(
            signals=[
                _make_signal("AAPL", ExitAction.ALERT, 6, 45, -20.0, "HIGH VIX"),
            ],
            positions_count=1,
        )
        output = server._format_monitor_result(result)

        assert "1 ALERT" in output
        assert "[ALERT]" in output

    def test_mixed_signals(self, server):
        """Multiple action types in one result."""
        result = MonitorResult(
            signals=[
                _make_signal("AAPL", ExitAction.CLOSE, 1, 0, 100.0, "ABGELAUFEN"),
                _make_signal("MSFT", ExitAction.ROLL, 5, 20, 30.0, "21-DTE ROLL"),
                _make_signal("JPM", ExitAction.ALERT, 6, 45, -10.0, "HIGH VIX"),
                _make_signal("AMZN", ExitAction.HOLD, 8, 60, 15.0),
            ],
            positions_count=4,
        )
        output = server._format_monitor_result(result)

        assert "4 Positionen" in output
        assert "1 CLOSE" in output
        assert "1 ROLL" in output
        assert "1 ALERT" in output
        assert "1 HOLD" in output
        assert "Aktionen erforderlich" in output
        assert "Halten" in output

    def test_pnl_formatting(self, server):
        """P&L percentage is shown when available."""
        result = MonitorResult(
            signals=[
                _make_signal("AAPL", ExitAction.HOLD, 8, 45, 25.0),
            ],
            positions_count=1,
        )
        output = server._format_monitor_result(result)

        assert "+25%" in output

    def test_no_pnl_formatting(self, server):
        """Without P&L, no percentage shown."""
        result = MonitorResult(
            signals=[
                _make_signal("AAPL", ExitAction.HOLD, 8, 45, None),
            ],
            positions_count=1,
        )
        output = server._format_monitor_result(result)

        # Should not crash, and should not show P&L
        assert "AAPL" in output


# =============================================================================
# SIGNAL ICON
# =============================================================================

class TestSignalIcon:
    """Test _signal_icon static method."""

    def test_close_icon(self, server):
        assert server._signal_icon(ExitAction.CLOSE) == "[CLOSE]"

    def test_roll_icon(self, server):
        assert server._signal_icon(ExitAction.ROLL) == "[ROLL]"

    def test_alert_icon(self, server):
        assert server._signal_icon(ExitAction.ALERT) == "[ALERT]"

    def test_hold_icon(self, server):
        assert server._signal_icon(ExitAction.HOLD) == "[HOLD]"


# =============================================================================
# COLLECT POSITION SNAPSHOTS
# =============================================================================

class TestCollectPositionSnapshots:
    """Test _collect_position_snapshots source collection."""

    @pytest.mark.asyncio
    async def test_no_sources_returns_empty(self, server):
        """Without IBKR or portfolio → empty list."""
        snapshots = await server._collect_position_snapshots()
        assert isinstance(snapshots, list)

    @pytest.mark.asyncio
    async def test_ibkr_bridge_returns_snapshots(self, server):
        """IBKR Bridge spreads are collected."""
        mock_bridge = MagicMock()
        mock_bridge.get_spreads = AsyncMock(return_value=[
            {
                "symbol": "AAPL",
                "expiry": "20260417",
                "short_strike": 180.0,
                "long_strike": 170.0,
                "width": 10.0,
                "net_credit": 2.50,
                "contracts": 1,
            },
        ])
        server._ibkr_bridge = mock_bridge

        snapshots = await server._collect_position_snapshots()
        assert len(snapshots) >= 1
        assert snapshots[0].symbol == "AAPL"
        assert snapshots[0].source == "ibkr"

    @pytest.mark.asyncio
    async def test_ibkr_exception_graceful(self, server):
        """IBKR exception → falls back gracefully."""
        mock_bridge = MagicMock()
        mock_bridge.get_spreads = AsyncMock(side_effect=Exception("TWS not connected"))
        server._ibkr_bridge = mock_bridge

        snapshots = await server._collect_position_snapshots()
        assert isinstance(snapshots, list)

    @pytest.mark.asyncio
    async def test_internal_portfolio_fallback(self, server):
        """Internal portfolio provides snapshots when IBKR unavailable."""
        mock_pos = MagicMock()
        mock_pos.id = "int123"
        mock_pos.symbol = "MSFT"
        mock_pos.short_leg.strike = 400.0
        mock_pos.long_leg.strike = 390.0
        mock_pos.spread_width = 10.0
        mock_pos.net_credit = 3.0
        mock_pos.contracts = 1
        mock_pos.expiration = "2026-04-17"
        mock_pos.days_to_expiration = 73
        mock_pos.max_profit = 300.0
        mock_pos.max_loss = 700.0
        mock_pos.breakeven = 397.0

        mock_portfolio = MagicMock()
        mock_portfolio.get_open_positions.return_value = [mock_pos]

        with patch("src.portfolio.get_portfolio_manager", return_value=mock_portfolio):
            snapshots = await server._collect_position_snapshots()

        assert len(snapshots) >= 1
        assert snapshots[0].symbol == "MSFT"
        assert snapshots[0].source == "internal"
        assert snapshots[0].pnl_estimated is True

    @pytest.mark.asyncio
    async def test_ibkr_deduplication(self, server):
        """IBKR symbols are not double-counted from internal portfolio."""
        mock_bridge = MagicMock()
        mock_bridge.get_spreads = AsyncMock(return_value=[
            {
                "symbol": "AAPL",
                "expiry": "20260417",
                "short_strike": 180.0,
                "long_strike": 170.0,
                "width": 10.0,
                "net_credit": 2.50,
                "contracts": 1,
            },
        ])
        server._ibkr_bridge = mock_bridge

        # Internal also has AAPL
        mock_pos = MagicMock()
        mock_pos.id = "int_aapl"
        mock_pos.symbol = "AAPL"
        mock_pos.short_leg.strike = 180.0
        mock_pos.long_leg.strike = 170.0
        mock_pos.spread_width = 10.0
        mock_pos.net_credit = 2.50
        mock_pos.contracts = 1
        mock_pos.expiration = "2026-04-17"
        mock_pos.days_to_expiration = 73
        mock_pos.max_profit = 250.0
        mock_pos.max_loss = 750.0
        mock_pos.breakeven = 177.5

        mock_portfolio = MagicMock()
        mock_portfolio.get_open_positions.return_value = [mock_pos]

        with patch("src.portfolio.get_portfolio_manager", return_value=mock_portfolio):
            snapshots = await server._collect_position_snapshots()

        # Should only have 1 AAPL (from IBKR), not 2
        aapl_snaps = [s for s in snapshots if s.symbol == "AAPL"]
        assert len(aapl_snaps) == 1
        assert aapl_snaps[0].source == "ibkr"


# =============================================================================
# ENDPOINT INTEGRATION
# =============================================================================

class TestMonitorPositionsEndpoint:
    """Integration tests for the monitor_positions endpoint."""

    @pytest.mark.asyncio
    async def test_no_positions_message(self, server):
        """No positions → informative message."""
        with patch.object(server, '_collect_position_snapshots', new_callable=AsyncMock, return_value=[]):
            output = await server.monitor_positions.__wrapped__(server)

        assert "Keine offenen Positionen" in output

    @pytest.mark.asyncio
    async def test_with_positions(self, server):
        """With positions → formatted output."""
        snap = PositionSnapshot(
            position_id="test1",
            symbol="AAPL",
            short_strike=180.0,
            long_strike=170.0,
            spread_width=10.0,
            net_credit=2.50,
            contracts=1,
            expiration="2026-06-17",
            dte=45,
            max_profit=250.0,
            max_loss=750.0,
            breakeven=177.5,
            pnl_pct_of_max_profit=20.0,
            unrealized_pnl=50.0,
        )
        with patch.object(server, 'get_vix', new_callable=AsyncMock, return_value=18.0):
            with patch.object(server, '_collect_position_snapshots', new_callable=AsyncMock, return_value=[snap]):
                output = await server.monitor_positions.__wrapped__(server)

        assert "Position Monitor" in output
        assert "AAPL" in output
        assert "1 Positionen" in output
