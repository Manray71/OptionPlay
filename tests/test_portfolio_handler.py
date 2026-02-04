# Tests for Portfolio Handler Module
# ==================================
"""
Tests for PortfolioHandlerMixin class.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from src.handlers.portfolio import PortfolioHandlerMixin


# =============================================================================
# MOCK CLASSES
# =============================================================================

class MockPortfolioHandler(PortfolioHandlerMixin):
    """Mock handler for testing PortfolioHandlerMixin."""
    pass


# =============================================================================
# SAMPLE DATA
# =============================================================================

def create_mock_position(
    position_id: str = "pos_001",
    symbol: str = "AAPL",
    status: str = "open"
):
    """Create a mock position object."""
    pos = MagicMock()
    pos.id = position_id
    pos.symbol = symbol
    pos.status = status
    pos.short_strike = 150.0
    pos.long_strike = 145.0
    pos.expiration = "2024-03-15"
    pos.credit = 1.50
    pos.contracts = 2
    pos.current_value = 0.75
    pos.unrealized_pnl = 0.75 * 100 * 2
    return pos


def create_mock_summary():
    """Create a mock portfolio summary."""
    summary = MagicMock()
    summary.total_positions = 5
    summary.open_positions = 3
    summary.closed_positions = 2
    summary.total_pnl = 1500.0
    summary.win_rate = 0.75
    return summary


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
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = [create_mock_position()]
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "Open Positions"

                handler.portfolio_positions(status="open")

        mock_manager.get_open_positions.assert_called_once()

    def test_filter_closed(self, handler):
        """Test filtering by closed status."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_closed_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "Closed Positions"

                handler.portfolio_positions(status="closed")

        mock_manager.get_closed_positions.assert_called_once()

    def test_filter_all(self, handler):
        """Test filtering by all (default)."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_all_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_positions_table.return_value = "All Positions"

                handler.portfolio_positions(status="all")

        mock_manager.get_all_positions.assert_called_once()


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


# =============================================================================
# PORTFOLIO ADD TESTS
# =============================================================================

class TestPortfolioAdd:
    """Tests for portfolio_add method."""

    @pytest.fixture
    def handler(self):
        return MockPortfolioHandler()

    def test_adds_position(self, handler):
        """Test adding a position."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = create_mock_position()
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_result = MagicMock()
                mock_result.allowed = True
                mock_result.warnings = []
                mock_checker.check_all_constraints.return_value = mock_result
                mock_cc.return_value = mock_checker

                with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                    mock_fmt.format_position_added.return_value = "Position Added"

                    result = handler.portfolio_add(
                        symbol="AAPL",
                        short_strike=150.0,
                        long_strike=145.0,
                        expiration="2024-03-15",
                        credit=1.50,
                    )

        assert isinstance(result, str)

    def test_validates_symbol(self, handler):
        """Test symbol is validated."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_manager.add_bull_put_spread.return_value = create_mock_position()
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_result = MagicMock()
                mock_result.allowed = True
                mock_result.warnings = []
                mock_checker.check_all_constraints.return_value = mock_result
                mock_cc.return_value = mock_checker

                with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                    mock_fmt.format_position_added.return_value = "Added"

                    # Should work with lowercase
                    result = handler.portfolio_add(
                        symbol="aapl",
                        short_strike=150.0,
                        long_strike=145.0,
                        expiration="2024-03-15",
                        credit=1.50,
                    )

        assert isinstance(result, str)

    def test_blocked_by_constraints(self, handler):
        """Test position blocked by constraints."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.get_open_positions.return_value = []
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.get_constraint_checker") as mock_cc:
                mock_checker = MagicMock()
                mock_result = MagicMock()
                mock_result.allowed = False
                mock_result.blockers = ["Max positions reached"]
                mock_checker.check_all_constraints.return_value = mock_result
                mock_cc.return_value = mock_checker

                result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                )

        assert "Blocked" in result

    def test_skip_constraints(self, handler):
        """Test skipping constraint checks."""
        with patch("src.handlers.portfolio.get_portfolio_manager") as mock_pm:
            mock_manager = MagicMock()
            mock_manager.add_bull_put_spread.return_value = create_mock_position()
            mock_pm.return_value = mock_manager

            with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                mock_fmt.format_position_added.return_value = "Added"

                result = handler.portfolio_add(
                    symbol="AAPL",
                    short_strike=150.0,
                    long_strike=145.0,
                    expiration="2024-03-15",
                    credit=1.50,
                    skip_constraints=True,
                )

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
                mock_result = MagicMock()
                mock_result.allowed = True
                mock_result.warnings = []
                mock_checker.check_all_constraints.return_value = mock_result
                mock_cc.return_value = mock_checker

                with patch("src.handlers.portfolio.portfolio_formatter") as mock_fmt:
                    mock_fmt.format_position_added.return_value = "Added"
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
