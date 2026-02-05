# OptionPlay - Portfolio Formatter Tests
# ========================================
# Tests für src/formatters/portfolio_formatter.py

import pytest
import sys
from pathlib import Path
from datetime import date, timedelta
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.formatters.portfolio_formatter import PortfolioFormatter, portfolio_formatter
from src.portfolio.manager import (
    BullPutSpread,
    PortfolioSummary,
    TradeRecord,
    PositionStatus,
    TradeAction,
    SpreadLeg,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def formatter():
    """Create a PortfolioFormatter instance."""
    return PortfolioFormatter()


@pytest.fixture
def sample_summary():
    """Create a sample PortfolioSummary."""
    return PortfolioSummary(
        total_positions=10,
        open_positions=3,
        closed_positions=7,
        total_realized_pnl=1500.00,
        total_unrealized_pnl=200.00,
        win_rate=70.0,
        avg_profit=214.29,
        total_capital_at_risk=3000.00,
        positions_expiring_soon=2,
    )


@pytest.fixture
def sample_position():
    """Create a sample BullPutSpread position."""
    return BullPutSpread(
        id="pos-001",
        symbol="AAPL",
        short_leg=SpreadLeg(strike=180.0, premium=2.50, expiration="2026-03-21", right="P", quantity=-1),
        long_leg=SpreadLeg(strike=175.0, premium=-1.00, expiration="2026-03-21", right="P", quantity=1),
        contracts=1,
        open_date="2026-02-01",
        status=PositionStatus.OPEN,
        notes="Test position",
        tags=["earnings", "tech"],
    )


@pytest.fixture
def closed_position():
    """Create a closed position."""
    return BullPutSpread(
        id="pos-002",
        symbol="MSFT",
        short_leg=SpreadLeg(strike=400.0, premium=3.00, expiration="2026-02-21", right="P", quantity=-1),
        long_leg=SpreadLeg(strike=395.0, premium=-1.50, expiration="2026-02-21", right="P", quantity=1),
        contracts=2,
        open_date="2026-01-15",
        status=PositionStatus.CLOSED,
        close_date="2026-02-20",
        close_premium=0.20,
        notes="Closed early for profit",
    )


@pytest.fixture
def sample_trades():
    """Create sample trade records."""
    return [
        TradeRecord(
            id="tr-001",
            position_id="pos-001",
            symbol="AAPL",
            action=TradeAction.OPEN,
            timestamp="2026-02-01T10:00:00",
            details={"net_credit": 1.50},
        ),
        TradeRecord(
            id="tr-002",
            position_id="pos-002",
            symbol="MSFT",
            action=TradeAction.CLOSE,
            timestamp="2026-02-20T14:30:00",
            details={"realized_pnl": 260.00},
        ),
        TradeRecord(
            id="tr-003",
            position_id="pos-003",
            symbol="GOOGL",
            action=TradeAction.EXPIRE,
            timestamp="2026-02-15T16:00:00",
            details={"realized_pnl": 150.00},
        ),
    ]


# =============================================================================
# format_summary Tests
# =============================================================================

class TestFormatSummary:
    """Tests für format_summary()."""

    def test_format_summary_basic(self, formatter, sample_summary):
        """Test: Summary wird formatiert."""
        result = formatter.format_summary(sample_summary)

        assert "Portfolio Summary" in result
        assert "Total Positions" in result
        assert "10" in result

    def test_format_summary_pnl_positive(self, formatter, sample_summary):
        """Test: Positive P&L mit grünem Icon."""
        result = formatter.format_summary(sample_summary)

        assert "Realized P&L" in result
        assert "1,500.00" in result

    def test_format_summary_pnl_negative(self, formatter):
        """Test: Negative P&L mit rotem Icon."""
        summary = PortfolioSummary(
            total_positions=5,
            open_positions=2,
            closed_positions=3,
            total_realized_pnl=-500.00,
            total_unrealized_pnl=0,
            win_rate=40.0,
            avg_profit=-166.67,
            total_capital_at_risk=2000.00,
            positions_expiring_soon=0,
        )
        result = formatter.format_summary(summary)

        assert "-500.00" in result

    def test_format_summary_win_rate(self, formatter, sample_summary):
        """Test: Win Rate wird angezeigt."""
        result = formatter.format_summary(sample_summary)

        assert "Win Rate" in result
        assert "70.0%" in result

    def test_format_summary_expiring_soon(self, formatter, sample_summary):
        """Test: Expiring soon wird angezeigt."""
        result = formatter.format_summary(sample_summary)

        assert "Expiring Soon" in result
        assert "2 positions" in result

    def test_format_summary_no_expiring(self, formatter):
        """Test: Keine Positionen expiring."""
        summary = PortfolioSummary(
            total_positions=3,
            open_positions=1,
            closed_positions=2,
            total_realized_pnl=300.00,
            total_unrealized_pnl=0,
            win_rate=66.7,
            avg_profit=150.00,
            total_capital_at_risk=500.00,
            positions_expiring_soon=0,
        )
        result = formatter.format_summary(summary)

        assert "None" in result  # "Expiring Soon: None"


# =============================================================================
# format_positions_table Tests
# =============================================================================

class TestFormatPositionsTable:
    """Tests für format_positions_table()."""

    def test_format_positions_empty(self, formatter):
        """Test: Leere Positionsliste."""
        result = formatter.format_positions_table([])

        assert "No positions found" in result

    def test_format_positions_with_data(self, formatter, sample_position):
        """Test: Positionen werden tabellarisch formatiert."""
        result = formatter.format_positions_table([sample_position])

        assert "AAPL" in result
        assert "pos-001" in result
        assert "$175/$180" in result

    def test_format_positions_custom_title(self, formatter, sample_position):
        """Test: Custom Title."""
        result = formatter.format_positions_table([sample_position], title="Open Positions")

        assert "Open Positions" in result

    def test_format_positions_multiple(self, formatter, sample_position, closed_position):
        """Test: Mehrere Positionen."""
        result = formatter.format_positions_table([sample_position, closed_position])

        assert "AAPL" in result
        assert "MSFT" in result


# =============================================================================
# format_position_detail Tests
# =============================================================================

class TestFormatPositionDetail:
    """Tests für format_position_detail()."""

    def test_format_detail_open(self, formatter, sample_position):
        """Test: Open Position Detail."""
        result = formatter.format_position_detail(sample_position)

        assert "Position: AAPL" in result
        assert "OPEN" in result
        assert "Bull Put Spread" in result
        assert "$180.00" in result  # Short strike
        assert "$175.00" in result  # Long strike

    def test_format_detail_closed(self, formatter, closed_position):
        """Test: Closed Position Detail."""
        result = formatter.format_position_detail(closed_position)

        assert "CLOSED" in result
        assert "MSFT" in result
        assert "Closed" in result

    def test_format_detail_with_notes(self, formatter, sample_position):
        """Test: Notes werden angezeigt."""
        result = formatter.format_position_detail(sample_position)

        assert "Notes" in result
        assert "Test position" in result

    def test_format_detail_with_tags(self, formatter, sample_position):
        """Test: Tags werden angezeigt."""
        result = formatter.format_position_detail(sample_position)

        assert "Tags" in result
        assert "earnings" in result
        assert "tech" in result


# =============================================================================
# format_trades Tests
# =============================================================================

class TestFormatTrades:
    """Tests für format_trades()."""

    def test_format_trades_empty(self, formatter):
        """Test: Keine Trades."""
        result = formatter.format_trades([])

        assert "No trades recorded" in result

    def test_format_trades_with_data(self, formatter, sample_trades):
        """Test: Trades werden formatiert."""
        result = formatter.format_trades(sample_trades)

        assert "Trade History" in result
        assert "AAPL" in result
        assert "MSFT" in result
        assert "GOOGL" in result

    def test_format_trades_actions(self, formatter, sample_trades):
        """Test: Trade Actions werden angezeigt."""
        result = formatter.format_trades(sample_trades)

        assert "OPEN" in result
        assert "CLOSE" in result
        assert "EXPIRE" in result

    def test_format_trades_limit(self, formatter):
        """Test: Trades mit Limit."""
        many_trades = [
            TradeRecord(
                id=f"tr-{i:03d}",
                position_id=f"pos-{i:03d}",
                symbol="AAPL",
                action=TradeAction.OPEN,
                timestamp=f"2026-02-{i+1:02d}T10:00:00",
                details={"net_credit": 1.50},
            )
            for i in range(30)
        ]
        result = formatter.format_trades(many_trades, limit=10)

        assert "Showing 10 of 30 trades" in result


# =============================================================================
# format_pnl_by_symbol Tests
# =============================================================================

class TestFormatPnlBySymbol:
    """Tests für format_pnl_by_symbol()."""

    def test_format_pnl_empty(self, formatter):
        """Test: Keine Daten."""
        result = formatter.format_pnl_by_symbol({})

        assert "No closed positions" in result

    def test_format_pnl_with_data(self, formatter):
        """Test: P&L nach Symbol."""
        pnl_data = {
            "AAPL": 500.00,
            "MSFT": 300.00,
            "GOOGL": -100.00,
        }
        result = formatter.format_pnl_by_symbol(pnl_data)

        assert "P&L by Symbol" in result
        assert "AAPL" in result
        assert "MSFT" in result
        assert "GOOGL" in result

    def test_format_pnl_total(self, formatter):
        """Test: Total wird berechnet."""
        pnl_data = {
            "AAPL": 500.00,
            "MSFT": 300.00,
        }
        result = formatter.format_pnl_by_symbol(pnl_data)

        assert "Total" in result
        assert "+800.00" in result


# =============================================================================
# format_monthly_pnl Tests
# =============================================================================

class TestFormatMonthlyPnl:
    """Tests für format_monthly_pnl()."""

    def test_format_monthly_empty(self, formatter):
        """Test: Keine Daten."""
        result = formatter.format_monthly_pnl({})

        assert "No closed positions" in result

    def test_format_monthly_with_data(self, formatter):
        """Test: Monthly P&L."""
        monthly_data = {
            "2026-01": 800.00,
            "2026-02": -200.00,
        }
        result = formatter.format_monthly_pnl(monthly_data)

        assert "Monthly P&L" in result
        assert "2026-01" in result
        assert "2026-02" in result

    def test_format_monthly_totals(self, formatter):
        """Test: Total und Average."""
        monthly_data = {
            "2026-01": 600.00,
            "2026-02": 400.00,
        }
        result = formatter.format_monthly_pnl(monthly_data)

        assert "Total" in result
        assert "+1,000.00" in result
        assert "Average/Month" in result
        assert "+500.00" in result


# =============================================================================
# format_expiring_soon Tests
# =============================================================================

class TestFormatExpiringSoon:
    """Tests für format_expiring_soon()."""

    def test_format_expiring_empty(self, formatter):
        """Test: Keine expirierenden Positionen."""
        result = formatter.format_expiring_soon([])

        assert "No positions expiring" in result

    def test_format_expiring_with_positions(self, formatter, sample_position):
        """Test: Expiring Positions werden formatiert."""
        result = formatter.format_expiring_soon([sample_position])

        assert "Positions Expiring Soon" in result
        assert "AAPL" in result
        assert "Consider closing or rolling" in result


# =============================================================================
# Global Instance Tests
# =============================================================================

class TestGlobalInstance:
    """Tests für globale Formatter-Instanz."""

    def test_global_instance_exists(self):
        """Test: Globale Instanz existiert."""
        assert portfolio_formatter is not None
        assert isinstance(portfolio_formatter, PortfolioFormatter)

    def test_global_instance_works(self):
        """Test: Globale Instanz funktioniert."""
        result = portfolio_formatter.format_pnl_by_symbol({})
        assert "No closed positions" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
