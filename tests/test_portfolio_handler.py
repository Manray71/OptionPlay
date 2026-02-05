# Tests for Portfolio Handler Module
# ==================================
"""
Comprehensive tests for PortfolioHandlerMixin class.

Tests cover:
1. PortfolioHandlerMixin methods
2. add_position method (with constraint validation)
3. close_position method
4. get_positions method (with filtering)
5. P&L calculations
6. Position tracking
7. Error handling
8. Edge cases
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, date
from dataclasses import dataclass
from typing import List, Optional

from src.handlers.portfolio import PortfolioHandlerMixin
from src.portfolio.manager import (
    BullPutSpread,
    SpreadLeg,
    PositionStatus,
    PortfolioSummary,
    TradeRecord,
    TradeAction,
)
from src.services.portfolio_constraints import ConstraintResult


# =============================================================================
# MOCK CLASSES
# =============================================================================

class MockPortfolioHandler(PortfolioHandlerMixin):
    """Mock handler for testing PortfolioHandlerMixin."""
    pass


# =============================================================================
# SAMPLE DATA FACTORIES
# =============================================================================

def create_mock_spread_leg(
    strike: float = 150.0,
    expiration: str = "2024-03-15",
    right: str = "P",
    quantity: int = -1,
    premium: float = 2.50,
) -> MagicMock:
    """Create a mock SpreadLeg object."""
    leg = MagicMock(spec=SpreadLeg)
    leg.strike = strike
    leg.expiration = expiration
    leg.right = right
    leg.quantity = quantity
    leg.premium = premium
    leg.is_short = quantity < 0
    leg.is_long = quantity > 0
    return leg


def create_mock_position(
    position_id: str = "pos_001",
    symbol: str = "AAPL",
    status: PositionStatus = PositionStatus.OPEN,
    short_strike: float = 150.0,
    long_strike: float = 145.0,
    expiration: str = "2024-03-15",
    net_credit: float = 1.50,
    contracts: int = 2,
    close_premium: Optional[float] = None,
    close_date: Optional[str] = None,
    notes: str = "",
    tags: Optional[List[str]] = None,
) -> MagicMock:
    """Create a mock BullPutSpread position object."""
    pos = MagicMock(spec=BullPutSpread)
    pos.id = position_id
    pos.symbol = symbol
    pos.status = status
    pos.contracts = contracts
    pos.notes = notes
    pos.tags = tags or []
    pos.open_date = "2024-01-15"
    pos.close_date = close_date
    pos.close_premium = close_premium

    # Create legs
    pos.short_leg = create_mock_spread_leg(
        strike=short_strike,
        expiration=expiration,
        quantity=-contracts,
        premium=net_credit * 0.7,
    )
    pos.long_leg = create_mock_spread_leg(
        strike=long_strike,
        expiration=expiration,
        quantity=contracts,
        premium=-(net_credit * 0.3),
    )

    # Computed properties
    pos.spread_width = short_strike - long_strike
    pos.net_credit = net_credit
    pos.total_credit = net_credit * contracts * 100
    pos.max_profit = pos.total_credit
    pos.max_loss = (pos.spread_width - net_credit) * contracts * 100
    pos.breakeven = short_strike - net_credit
    pos.expiration = expiration
    pos.days_to_expiration = 30  # Fixed for tests

    # P&L methods
    if status == PositionStatus.OPEN:
        pos.realized_pnl.return_value = None
    elif status == PositionStatus.EXPIRED:
        pos.realized_pnl.return_value = pos.total_credit
    elif status == PositionStatus.CLOSED and close_premium is not None:
        pos.realized_pnl.return_value = pos.total_credit - (close_premium * contracts * 100)
    elif status == PositionStatus.ASSIGNED:
        pos.realized_pnl.return_value = -pos.max_loss
    else:
        pos.realized_pnl.return_value = None

    return pos


def create_mock_summary(
    total_positions: int = 5,
    open_positions: int = 3,
    closed_positions: int = 2,
    total_realized_pnl: float = 1500.0,
    total_unrealized_pnl: float = 200.0,
    win_rate: float = 75.0,
    avg_profit: float = 300.0,
    total_capital_at_risk: float = 2500.0,
    positions_expiring_soon: int = 1,
) -> MagicMock:
    """Create a mock PortfolioSummary object."""
    summary = MagicMock(spec=PortfolioSummary)
    summary.total_positions = total_positions
    summary.open_positions = open_positions
    summary.closed_positions = closed_positions
    summary.total_realized_pnl = total_realized_pnl
    summary.total_unrealized_pnl = total_unrealized_pnl
    summary.win_rate = win_rate
    summary.avg_profit = avg_profit
    summary.total_capital_at_risk = total_capital_at_risk
    summary.positions_expiring_soon = positions_expiring_soon
    return summary


def create_mock_constraint_result(
    allowed: bool = True,
    blockers: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    details: Optional[dict] = None,
) -> MagicMock:
    """Create a mock ConstraintResult object."""
    result = MagicMock(spec=ConstraintResult)
    result.allowed = allowed
    result.blockers = blockers or []
    result.warnings = warnings or []
    result.details = details or {}
    result.messages = result.blockers + result.warnings
    return result


def create_mock_trade_record(
    trade_id: str = "trade_001",
    position_id: str = "pos_001",
    action: TradeAction = TradeAction.OPEN,
    symbol: str = "AAPL",
    details: Optional[dict] = None,
    notes: str = "",
) -> MagicMock:
    """Create a mock TradeRecord object."""
    trade = MagicMock(spec=TradeRecord)
    trade.id = trade_id
    trade.position_id = position_id
    trade.action = action
    trade.timestamp = datetime.now().isoformat()
    trade.symbol = symbol
    trade.details = details or {"net_credit": 1.50}
    trade.notes = notes
    return trade


# =============================================================================
# PORTFOLIO SUMMARY TESTS
# =============================================================================

class TestPortfolioSummary:
    """Tests for portfolio_summary method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_string(self, handler):
        """Test portfolio_summary returns a string."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_summary.return_value = create_mock_summary()
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_summary.return_value = "Summary Output"

                result = handler.portfolio_summary()

        assert isinstance(result, str)
        assert result == "Summary Output"

    def test_calls_portfolio_manager(self, handler):
        """Test portfolio_summary calls portfolio manager."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_summary.return_value = create_mock_summary()
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_summary.return_value = "Summary"

                handler.portfolio_summary()

        mock_manager.get_summary.assert_called_once()

    def test_passes_summary_to_formatter(self, handler):
        """Test that summary is passed to formatter."""
        mock_summary = create_mock_summary()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_summary.return_value = mock_summary
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_summary.return_value = "Formatted"

                handler.portfolio_summary()

        mock_fmt.format_summary.assert_called_once_with(mock_summary)


# =============================================================================
# PORTFOLIO POSITIONS TESTS
# =============================================================================

class TestPortfolioPositions:
    """Tests for portfolio_positions method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_string(self, handler):
        """Test portfolio_positions returns a string."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_all_positions.return_value = [create_mock_position()]
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "Positions Table"

                result = handler.portfolio_positions()

        assert isinstance(result, str)

    def test_filter_open(self, handler):
        """Test filtering by open status."""
        mock_positions = [create_mock_position(status=PositionStatus.OPEN)]

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = mock_positions
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "Open Positions"

                result = handler.portfolio_positions(status="open")

        mock_manager.get_open_positions.assert_called_once()
        mock_fmt.format_positions_table.assert_called_once_with(
            mock_positions, "Open Positions"
        )

    def test_filter_closed(self, handler):
        """Test filtering by closed status."""
        mock_positions = [
            create_mock_position(status=PositionStatus.CLOSED, close_premium=0.30)
        ]

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_closed_positions.return_value = mock_positions
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "Closed Positions"

                result = handler.portfolio_positions(status="closed")

        mock_manager.get_closed_positions.assert_called_once()
        mock_fmt.format_positions_table.assert_called_once_with(
            mock_positions, "Closed Positions"
        )

    def test_filter_all(self, handler):
        """Test filtering by all (default)."""
        mock_positions = [
            create_mock_position(status=PositionStatus.OPEN),
            create_mock_position(
                position_id="pos_002", status=PositionStatus.CLOSED, close_premium=0.30
            ),
        ]

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_all_positions.return_value = mock_positions
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "All Positions"

                handler.portfolio_positions(status="all")

        mock_manager.get_all_positions.assert_called_once()

    def test_filter_case_insensitive(self, handler):
        """Test status filter is case insensitive."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "Positions"

                handler.portfolio_positions(status="OPEN")

        mock_manager.get_open_positions.assert_called_once()

    def test_empty_positions(self, handler):
        """Test handling of empty positions list."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_all_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "No positions found"

                result = handler.portfolio_positions()

        assert isinstance(result, str)
        mock_fmt.format_positions_table.assert_called_once_with([], "All Positions")


# =============================================================================
# PORTFOLIO POSITION DETAIL TESTS
# =============================================================================

class TestPortfolioPosition:
    """Tests for portfolio_position method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_string(self, handler):
        """Test portfolio_position returns a string."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_position.return_value = create_mock_position()
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_position_detail.return_value = "Position Detail"

                result = handler.portfolio_position("pos_001")

        assert isinstance(result, str)

    def test_position_not_found(self, handler):
        """Test handling of non-existent position."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_position.return_value = None
            mock_pm.return_value = mock_manager

            result = handler.portfolio_position("nonexistent")

        assert "not found" in result.lower()
        assert "nonexistent" in result

    def test_calls_formatter_with_position(self, handler):
        """Test that position is passed to formatter."""
        mock_position = create_mock_position()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_position_detail.return_value = "Detail"

                handler.portfolio_position("pos_001")

        mock_fmt.format_position_detail.assert_called_once_with(mock_position)


# =============================================================================
# PORTFOLIO ADD TESTS
# =============================================================================

class TestPortfolioAdd:
    """Tests for portfolio_add method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_adds_position_successfully(self, handler):
        """Test adding a position successfully."""
        mock_position = create_mock_position()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True, warnings=[]
                )
                mock_cc.return_value = mock_checker

                result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                )

        assert isinstance(result, str)
        assert "Position Added" in result
        mock_manager.add_bull_put_spread.assert_called_once()

    def test_validates_symbol(self, handler):
        """Test symbol is validated and normalized."""
        mock_position = create_mock_position()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_cc.return_value = mock_checker

                # Should work with lowercase
                result = handler.portfolio_add(
                    symbol="aapl",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                )

        # Verify symbol was passed as uppercase to manager
        call_args = mock_manager.add_bull_put_spread.call_args
        assert call_args.kwargs["symbol"] == "AAPL"

    def test_calculates_max_risk(self, handler):
        """Test max risk calculation for constraints."""
        mock_position = create_mock_position()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_cc.return_value = mock_checker

                handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                    contracts=2,
                )

        # Max risk = (150-145) * 100 * 2 = $1000
        call_args = mock_checker.check_all_constraints.call_args
        assert call_args.kwargs["max_risk"] == 1000.0

    def test_blocked_by_constraints(self, handler):
        """Test position blocked by constraints."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=False,
                    blockers=["Max positions reached", "Daily risk exceeded"],
                )
                mock_cc.return_value = mock_checker

                result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                )

        assert "Blocked" in result
        assert "Max positions reached" in result
        mock_manager.add_bull_put_spread.assert_not_called()

    def test_shows_warnings_when_allowed(self, handler):
        """Test warnings are shown even when position is allowed."""
        mock_position = create_mock_position()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True,
                    warnings=["High correlation with existing position"],
                )
                mock_cc.return_value = mock_checker

                result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                )

        assert "Position Added" in result
        assert "Warning" in result
        mock_manager.add_bull_put_spread.assert_called_once()

    def test_skip_constraints(self, handler):
        """Test skipping constraint checks."""
        mock_position = create_mock_position()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.add_bull_put_spread.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_cc.return_value = mock_checker

                result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                    skip_constraints=True,
                )

        # Constraint checker should not be called
        mock_checker.check_all_constraints.assert_not_called()
        mock_manager.add_bull_put_spread.assert_called_once()

    def test_handles_add_error(self, handler):
        """Test handling of add position error."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.side_effect = ValueError(
                "Short strike must be higher than long strike"
            )
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_cc.return_value = mock_checker

                result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=145.0,  # Invalid: lower than long strike
                    long_strike=150.0,
                    expiration="2024-03-15",
                    credit=1.50,
                )

        assert "Error" in result
        assert "Short strike" in result

    def test_passes_notes_to_manager(self, handler):
        """Test that notes are passed to portfolio manager."""
        mock_position = create_mock_position()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_cc.return_value = mock_checker

                handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                    notes="Test trade from support level",
                )

        call_args = mock_manager.add_bull_put_spread.call_args
        assert call_args.kwargs["notes"] == "Test trade from support level"

    def test_includes_position_details_in_response(self, handler):
        """Test that response includes position details."""
        mock_position = create_mock_position(
            position_id="test123",
            symbol="AAPL",
            short_strike=150.0,
            long_strike=145.0,
            net_credit=1.50,
            contracts=2,
        )

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_cc.return_value = mock_checker

                result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                    contracts=2,
                )

        assert "test123" in result or "ID" in result
        assert "AAPL" in result
        assert "$145" in result or "145" in result


# =============================================================================
# PORTFOLIO CLOSE TESTS
# =============================================================================

class TestPortfolioClose:
    """Tests for portfolio_close method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_closes_position_successfully(self, handler):
        """Test closing a position successfully."""
        mock_position = create_mock_position(
            status=PositionStatus.CLOSED,
            close_premium=0.30,
        )

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.close_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            result = handler.portfolio_close("pos_001", close_premium=0.30)

        assert isinstance(result, str)
        assert "Position Closed" in result
        mock_manager.close_position.assert_called_once_with("pos_001", 0.30, "")

    def test_shows_realized_pnl(self, handler):
        """Test that realized P&L is shown in response."""
        mock_position = create_mock_position(
            status=PositionStatus.CLOSED,
            close_premium=0.30,
            net_credit=1.50,
            contracts=2,
        )
        # P&L = (1.50 - 0.30) * 2 * 100 = $240
        mock_position.realized_pnl.return_value = 240.0

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.close_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            result = handler.portfolio_close("pos_001", close_premium=0.30)

        assert "$" in result
        assert "P&L" in result or "P/L" in result or "240" in result

    def test_handles_position_not_found(self, handler):
        """Test handling of position not found error."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.close_position.side_effect = ValueError(
                "Position not found: invalid_id"
            )
            mock_pm.return_value = mock_manager

            result = handler.portfolio_close("invalid_id", close_premium=0.30)

        assert "Error" in result
        assert "not found" in result.lower()

    def test_handles_already_closed(self, handler):
        """Test handling of already closed position."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.close_position.side_effect = ValueError(
                "Position is not open: closed"
            )
            mock_pm.return_value = mock_manager

            result = handler.portfolio_close("pos_001", close_premium=0.30)

        assert "Error" in result

    def test_includes_notes(self, handler):
        """Test closing with notes."""
        mock_position = create_mock_position(
            status=PositionStatus.CLOSED,
            close_premium=0.30,
        )

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.close_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            handler.portfolio_close(
                "pos_001",
                close_premium=0.30,
                notes="Closed early to capture profit",
            )

        mock_manager.close_position.assert_called_once_with(
            "pos_001", 0.30, "Closed early to capture profit"
        )

    def test_shows_loss_correctly(self, handler):
        """Test that losing trades show negative P&L."""
        mock_position = create_mock_position(
            status=PositionStatus.CLOSED,
            close_premium=2.50,  # Paid more than received
            net_credit=1.50,
            contracts=1,
        )
        # P&L = (1.50 - 2.50) * 1 * 100 = -$100
        mock_position.realized_pnl.return_value = -100.0

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.close_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            result = handler.portfolio_close("pos_001", close_premium=2.50)

        # Should show negative indicator
        assert "[-]" in result or "-" in result


# =============================================================================
# PORTFOLIO EXPIRE TESTS
# =============================================================================

class TestPortfolioExpire:
    """Tests for portfolio_expire method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_expires_position_successfully(self, handler):
        """Test expiring a position successfully."""
        mock_position = create_mock_position(
            status=PositionStatus.EXPIRED,
            net_credit=1.50,
            contracts=2,
        )
        mock_position.total_credit = 300.0  # 1.50 * 2 * 100

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.expire_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            result = handler.portfolio_expire("pos_001")

        assert isinstance(result, str)
        assert "Expired" in result
        mock_manager.expire_position.assert_called_once_with("pos_001")

    def test_shows_full_profit(self, handler):
        """Test that full credit is shown as profit."""
        mock_position = create_mock_position(status=PositionStatus.EXPIRED)
        mock_position.total_credit = 300.0

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.expire_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            result = handler.portfolio_expire("pos_001")

        assert "$300" in result or "300" in result
        assert "Profit" in result or "[+]" in result

    def test_handles_position_not_found(self, handler):
        """Test handling of position not found error."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.expire_position.side_effect = ValueError(
                "Position not found: invalid_id"
            )
            mock_pm.return_value = mock_manager

            result = handler.portfolio_expire("invalid_id")

        assert "Error" in result


# =============================================================================
# PORTFOLIO EXPIRING TESTS
# =============================================================================

class TestPortfolioExpiring:
    """Tests for portfolio_expiring method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_expiring_positions(self, handler):
        """Test getting positions expiring soon."""
        mock_positions = [
            create_mock_position(position_id="pos_001"),
            create_mock_position(position_id="pos_002"),
        ]

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_expiring_soon.return_value = mock_positions
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_expiring_soon.return_value = "Expiring Positions"

                result = handler.portfolio_expiring(days=7)

        assert isinstance(result, str)
        mock_manager.get_expiring_soon.assert_called_once_with(7)

    def test_default_days(self, handler):
        """Test default days parameter."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_expiring_soon.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_expiring_soon.return_value = "None"

                handler.portfolio_expiring()

        mock_manager.get_expiring_soon.assert_called_once_with(7)


# =============================================================================
# PORTFOLIO TRADES TESTS
# =============================================================================

class TestPortfolioTrades:
    """Tests for portfolio_trades method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_trade_history(self, handler):
        """Test getting trade history."""
        mock_trades = [
            create_mock_trade_record(trade_id="t1", action=TradeAction.OPEN),
            create_mock_trade_record(trade_id="t2", action=TradeAction.CLOSE),
        ]

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_trades.return_value = mock_trades
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_trades.return_value = "Trade History"

                result = handler.portfolio_trades(limit=20)

        assert isinstance(result, str)
        mock_fmt.format_trades.assert_called_once_with(mock_trades, 20)

    def test_default_limit(self, handler):
        """Test default limit parameter."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_trades.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_trades.return_value = "No trades"

                handler.portfolio_trades()

        mock_fmt.format_trades.assert_called_once_with([], 20)


# =============================================================================
# PORTFOLIO P&L BY SYMBOL TESTS
# =============================================================================

class TestPortfolioPnLSymbols:
    """Tests for portfolio_pnl_symbols method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_pnl_by_symbol(self, handler):
        """Test getting P&L by symbol."""
        mock_pnl = {"AAPL": 500.0, "MSFT": -100.0, "GOOGL": 300.0}

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_pnl_by_symbol.return_value = mock_pnl
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_pnl_by_symbol.return_value = "P&L by Symbol"

                result = handler.portfolio_pnl_symbols()

        assert isinstance(result, str)
        mock_fmt.format_pnl_by_symbol.assert_called_once_with(mock_pnl)


# =============================================================================
# PORTFOLIO MONTHLY P&L TESTS
# =============================================================================

class TestPortfolioPnLMonthly:
    """Tests for portfolio_pnl_monthly method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_monthly_pnl(self, handler):
        """Test getting monthly P&L."""
        mock_pnl = {"2024-01": 1000.0, "2024-02": -200.0}

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_monthly_pnl.return_value = mock_pnl
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_monthly_pnl.return_value = "Monthly P&L"

                result = handler.portfolio_pnl_monthly()

        assert isinstance(result, str)
        mock_fmt.format_monthly_pnl.assert_called_once_with(mock_pnl)


# =============================================================================
# PORTFOLIO CHECK (CONSTRAINT CHECK) TESTS
# =============================================================================

class TestPortfolioCheck:
    """Tests for portfolio_check method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_allowed_result(self, handler):
        """Test constraint check returns allowed result."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_checker.get_status.return_value = {
                    "constraints": {"max_positions": 5, "max_per_sector": 2},
                    "current": {
                        "daily_risk_used": 500.0,
                        "daily_remaining": 1000.0,
                    },
                }
                mock_cc.return_value = mock_checker

                result = handler.portfolio_check(symbol="AAPL", max_risk=500.0)

        assert isinstance(result, str)
        assert "ALLOWED" in result
        assert "AAPL" in result

    def test_returns_blocked_result(self, handler):
        """Test constraint check returns blocked result."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = [
                create_mock_position(),
                create_mock_position(position_id="pos_002"),
            ]
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=False,
                    blockers=["Max positions reached: 5/5"],
                )
                mock_checker.get_status.return_value = {
                    "constraints": {"max_positions": 5, "max_per_sector": 2},
                    "current": {
                        "daily_risk_used": 1500.0,
                        "daily_remaining": 0.0,
                    },
                }
                mock_cc.return_value = mock_checker

                result = handler.portfolio_check(symbol="AAPL")

        assert "BLOCKED" in result
        assert "Max positions" in result

    def test_validates_symbol(self, handler):
        """Test symbol is validated."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_checker.get_status.return_value = {
                    "constraints": {"max_positions": 5, "max_per_sector": 2},
                    "current": {
                        "daily_risk_used": 0.0,
                        "daily_remaining": 1500.0,
                    },
                }
                mock_cc.return_value = mock_checker

                handler.portfolio_check(symbol="aapl", max_risk=500.0)

        # Verify symbol was passed as uppercase
        call_args = mock_checker.check_all_constraints.call_args
        assert call_args.kwargs["symbol"] == "AAPL"

    def test_shows_warnings(self, handler):
        """Test that warnings are shown."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True,
                    warnings=["High correlation warning"],
                )
                mock_checker.get_status.return_value = {
                    "constraints": {"max_positions": 5, "max_per_sector": 2},
                    "current": {
                        "daily_risk_used": 0.0,
                        "daily_remaining": 1500.0,
                    },
                }
                mock_cc.return_value = mock_checker

                result = handler.portfolio_check(symbol="AAPL")

        assert "Warning" in result
        assert "correlation" in result.lower()


# =============================================================================
# PORTFOLIO CONSTRAINTS TESTS
# =============================================================================

class TestPortfolioConstraints:
    """Tests for portfolio_constraints method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_returns_constraint_status(self, handler):
        """Test getting constraint configuration and status."""
        with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
            mock_checker = MagicMock()
            mock_checker.get_status.return_value = {
                "constraints": {
                    "max_positions": 5,
                    "max_per_sector": 2,
                    "max_daily_risk_usd": 1500.0,
                    "max_weekly_risk_usd": 5000.0,
                    "max_position_size_usd": 2000.0,
                    "max_correlation": 0.70,
                    "symbol_blacklist": ["TSLA", "GME"],
                },
                "current": {
                    "daily_risk_used": 500.0,
                    "daily_remaining": 1000.0,
                    "weekly_risk_used": 1500.0,
                    "weekly_remaining": 3500.0,
                },
            }
            mock_cc.return_value = mock_checker

            result = handler.portfolio_constraints()

        assert isinstance(result, str)
        assert "Constraints" in result
        assert "Max Positions" in result or "max_positions" in result.lower()


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestPortfolioHandlerErrorHandling:
    """Tests for error handling in portfolio handler methods."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_summary_handles_exception(self, handler):
        """Test portfolio_summary handles exceptions gracefully."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_pm.side_effect = Exception("Database connection failed")

            # Should return error response, not raise
            result = handler.portfolio_summary()

        assert isinstance(result, str)
        assert "Error" in result or "error" in result.lower()

    def test_positions_handles_exception(self, handler):
        """Test portfolio_positions handles exceptions gracefully."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_all_positions.side_effect = RuntimeError("IO Error")
            mock_pm.return_value = mock_manager

            result = handler.portfolio_positions()

        assert isinstance(result, str)
        # sync_endpoint decorator handles the exception

    def test_invalid_symbol_format(self, handler):
        """Test handling of invalid symbol format."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_pm.return_value = mock_manager

            # Invalid symbol with special characters
            result = handler.portfolio_add(
                symbol="INVALID!!!",
                short_strike=150.0,
                long_strike=145.0,
                expiration="2024-03-15",
                credit=1.50,
            )

        # Should return error about invalid symbol
        assert isinstance(result, str)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestPortfolioHandlerIntegration:
    """Integration tests for portfolio handler."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_full_workflow(self, handler):
        """Test complete portfolio workflow."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()

            # Setup mocks for workflow
            position = create_mock_position()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = position
            mock_manager.get_position.return_value = position
            mock_manager.get_all_positions.return_value = [position]
            mock_manager.get_summary.return_value = create_mock_summary()
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True, warnings=[]
                )
                mock_cc.return_value = mock_checker

                with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                    mock_fmt.format_position_detail.return_value = "Detail"
                    mock_fmt.format_positions_table.return_value = "Table"
                    mock_fmt.format_summary.return_value = "Summary"

                    # Add position
                    result1 = handler.portfolio_add(
                        symbol="AAPL",
                        short_strike=150.0,
                        long_strike=145.0,
                        expiration="2024-03-15",
                        credit=1.50,
                    )
                    assert isinstance(result1, str)

                    # Get position detail
                    result2 = handler.portfolio_position("pos_001")
                    assert isinstance(result2, str)

                    # Get all positions
                    result3 = handler.portfolio_positions()
                    assert isinstance(result3, str)

                    # Get summary
                    result4 = handler.portfolio_summary()
                    assert isinstance(result4, str)

    def test_add_and_close_workflow(self, handler):
        """Test adding and closing a position."""
        open_position = create_mock_position(status=PositionStatus.OPEN)
        closed_position = create_mock_position(
            status=PositionStatus.CLOSED,
            close_premium=0.30,
        )
        closed_position.realized_pnl.return_value = 240.0

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = open_position
            mock_manager.close_position.return_value = closed_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_cc.return_value = mock_checker

                # Add position
                add_result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                    contracts=2,
                )
                assert "Position Added" in add_result

                # Close position
                close_result = handler.portfolio_close(
                    "pos_001",
                    close_premium=0.30,
                )
                assert "Closed" in close_result

    def test_check_then_add_workflow(self, handler):
        """Test checking constraints before adding."""
        mock_position = create_mock_position()

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = mock_position
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_checker.check_all_constraints.return_value = create_mock_constraint_result(
                    allowed=True
                )
                mock_checker.get_status.return_value = {
                    "constraints": {"max_positions": 5, "max_per_sector": 2},
                    "current": {
                        "daily_risk_used": 0.0,
                        "daily_remaining": 1500.0,
                    },
                }
                mock_cc.return_value = mock_checker

                # Check first
                check_result = handler.portfolio_check(symbol="AAPL", max_risk=500.0)
                assert "ALLOWED" in check_result

                # Then add
                add_result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                )
                assert "Position Added" in add_result


# =============================================================================
# P&L CALCULATION TESTS
# =============================================================================

class TestPnLCalculations:
    """Tests for P&L calculation display in handler responses."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_positive_pnl_display(self, handler):
        """Test positive P&L is displayed with positive indicator."""
        mock_position = create_mock_position(
            status=PositionStatus.CLOSED,
            close_premium=0.30,
        )
        mock_position.realized_pnl.return_value = 240.0  # Profit

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.close_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            result = handler.portfolio_close("pos_001", close_premium=0.30)

        # Should show positive indicator
        assert "[+]" in result or "+" in result

    def test_negative_pnl_display(self, handler):
        """Test negative P&L is displayed with negative indicator."""
        mock_position = create_mock_position(
            status=PositionStatus.CLOSED,
            close_premium=3.00,  # High close cost
        )
        mock_position.realized_pnl.return_value = -150.0  # Loss

        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.close_position.return_value = mock_position
            mock_pm.return_value = mock_manager

            result = handler.portfolio_close("pos_001", close_premium=3.00)

        # Should show negative indicator
        assert "[-]" in result or "-" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
