# OptionPlay - Tests for Portfolio Manager
# =========================================

import pytest
import tempfile
import json
from pathlib import Path
from datetime import date, timedelta

from src.portfolio.manager import (
    PortfolioManager,
    BullPutSpread,
    SpreadLeg,
    TradeRecord,
    PortfolioSummary,
    PositionStatus,
    TradeAction,
    get_portfolio_manager,
    reset_portfolio_manager,
)


class TestSpreadLeg:
    """Tests for SpreadLeg dataclass."""
    
    def test_short_leg(self):
        """Test short leg properties."""
        leg = SpreadLeg(
            strike=180.0,
            expiration="2025-03-21",
            right="P",
            quantity=-1,
            premium=2.50
        )
        
        assert leg.is_short is True
        assert leg.is_long is False
        assert leg.strike == 180.0
    
    def test_long_leg(self):
        """Test long leg properties."""
        leg = SpreadLeg(
            strike=175.0,
            expiration="2025-03-21",
            right="P",
            quantity=1,
            premium=-0.80
        )
        
        assert leg.is_short is False
        assert leg.is_long is True
    
    def test_to_dict_from_dict(self):
        """Test serialization round-trip."""
        leg = SpreadLeg(
            strike=180.0,
            expiration="2025-03-21",
            right="P",
            quantity=-1,
            premium=2.50
        )
        
        data = leg.to_dict()
        restored = SpreadLeg.from_dict(data)
        
        assert restored.strike == leg.strike
        assert restored.expiration == leg.expiration
        assert restored.quantity == leg.quantity


class TestBullPutSpread:
    """Tests for BullPutSpread dataclass."""
    
    @pytest.fixture
    def sample_spread(self):
        """Create sample Bull Put Spread."""
        return BullPutSpread(
            id="abc123",
            symbol="AAPL",
            short_leg=SpreadLeg(180.0, "2025-03-21", "P", -2, 2.50),
            long_leg=SpreadLeg(175.0, "2025-03-21", "P", 2, -0.80),
            contracts=2,
            open_date="2025-01-15",
        )
    
    def test_spread_width(self, sample_spread):
        """Test spread width calculation."""
        assert sample_spread.spread_width == 5.0
    
    def test_net_credit(self, sample_spread):
        """Test net credit calculation."""
        # 2.50 - 0.80 = 1.70 per contract
        assert sample_spread.net_credit == 1.70
    
    def test_total_credit(self, sample_spread):
        """Test total credit for all contracts."""
        # 1.70 * 2 contracts * 100 = $340
        assert sample_spread.total_credit == 340.0
    
    def test_max_profit(self, sample_spread):
        """Test max profit equals total credit."""
        assert sample_spread.max_profit == 340.0
    
    def test_max_loss(self, sample_spread):
        """Test max loss calculation."""
        # (5.0 - 1.70) * 2 * 100 = $660
        assert sample_spread.max_loss == 660.0
    
    def test_breakeven(self, sample_spread):
        """Test breakeven price."""
        # 180 - 1.70 = 178.30
        assert sample_spread.breakeven == 178.30
    
    def test_realized_pnl_open(self, sample_spread):
        """Test realized P&L for open position."""
        assert sample_spread.realized_pnl() is None
    
    def test_realized_pnl_expired(self, sample_spread):
        """Test realized P&L for expired position."""
        sample_spread.status = PositionStatus.EXPIRED
        sample_spread.close_date = "2025-03-21"
        
        # Full credit = $340
        assert sample_spread.realized_pnl() == 340.0
    
    def test_realized_pnl_closed(self, sample_spread):
        """Test realized P&L for closed position."""
        sample_spread.status = PositionStatus.CLOSED
        sample_spread.close_date = "2025-02-15"
        sample_spread.close_premium = 0.50  # Paid $0.50 per contract to close
        
        # Credit: $340, Close cost: 0.50 * 2 * 100 = $100
        # P&L: 340 - 100 = $240
        assert sample_spread.realized_pnl() == 240.0
    
    def test_realized_pnl_assigned(self, sample_spread):
        """Test realized P&L for assigned position."""
        sample_spread.status = PositionStatus.ASSIGNED
        sample_spread.close_date = "2025-03-21"
        
        # Max loss = -$660
        assert sample_spread.realized_pnl() == -660.0
    
    def test_to_dict_from_dict(self, sample_spread):
        """Test serialization round-trip."""
        data = sample_spread.to_dict()
        restored = BullPutSpread.from_dict(data)
        
        assert restored.id == sample_spread.id
        assert restored.symbol == sample_spread.symbol
        assert restored.contracts == sample_spread.contracts
        assert restored.net_credit == sample_spread.net_credit


class TestPortfolioManager:
    """Tests for PortfolioManager class."""
    
    @pytest.fixture
    def temp_portfolio(self):
        """Create portfolio manager with temp file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            filepath = Path(f.name)
        
        manager = PortfolioManager(filepath)
        yield manager
        
        # Cleanup
        if filepath.exists():
            filepath.unlink()
    
    def test_add_position(self, temp_portfolio):
        """Test adding a position."""
        position = temp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180.0,
            long_strike=175.0,
            expiration="2025-03-21",
            net_credit=1.50,
            contracts=2,
        )
        
        assert position.symbol == "AAPL"
        assert position.contracts == 2
        assert position.status == PositionStatus.OPEN
        assert len(temp_portfolio.get_all_positions()) == 1
    
    def test_add_position_validation(self, temp_portfolio):
        """Test position validation."""
        # Short strike must be higher
        with pytest.raises(ValueError):
            temp_portfolio.add_bull_put_spread(
                symbol="AAPL",
                short_strike=175.0,  # Lower than long!
                long_strike=180.0,
                expiration="2025-03-21",
                net_credit=1.50,
            )
        
        # Credit must be positive
        with pytest.raises(ValueError):
            temp_portfolio.add_bull_put_spread(
                symbol="AAPL",
                short_strike=180.0,
                long_strike=175.0,
                expiration="2025-03-21",
                net_credit=-1.50,  # Negative!
            )
    
    def test_close_position(self, temp_portfolio):
        """Test closing a position."""
        position = temp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180.0,
            long_strike=175.0,
            expiration="2025-03-21",
            net_credit=1.50,
            contracts=1,
        )
        
        closed = temp_portfolio.close_position(position.id, close_premium=0.30)
        
        assert closed.status == PositionStatus.CLOSED
        assert closed.close_premium == 0.30
        assert closed.realized_pnl() == 120.0  # (1.50 - 0.30) * 100
    
    def test_expire_position(self, temp_portfolio):
        """Test expiring a position."""
        position = temp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180.0,
            long_strike=175.0,
            expiration="2025-03-21",
            net_credit=1.50,
            contracts=1,
        )
        
        expired = temp_portfolio.expire_position(position.id)
        
        assert expired.status == PositionStatus.EXPIRED
        assert expired.realized_pnl() == 150.0  # Full credit
    
    def test_get_open_positions(self, temp_portfolio):
        """Test filtering open positions."""
        # Add two positions
        pos1 = temp_portfolio.add_bull_put_spread(
            symbol="AAPL", short_strike=180, long_strike=175,
            expiration="2025-03-21", net_credit=1.50
        )
        pos2 = temp_portfolio.add_bull_put_spread(
            symbol="MSFT", short_strike=400, long_strike=395,
            expiration="2025-03-21", net_credit=2.00
        )
        
        # Close one
        temp_portfolio.close_position(pos1.id, 0.30)
        
        open_positions = temp_portfolio.get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0].symbol == "MSFT"
    
    def test_persistence(self, temp_portfolio):
        """Test that positions persist to file."""
        position = temp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180.0,
            long_strike=175.0,
            expiration="2025-03-21",
            net_credit=1.50,
        )
        
        # Create new manager with same file
        manager2 = PortfolioManager(temp_portfolio.filepath)
        
        assert len(manager2.get_all_positions()) == 1
        restored = manager2.get_position(position.id)
        assert restored.symbol == "AAPL"
        assert restored.net_credit == 1.50
    
    def test_get_summary(self, temp_portfolio):
        """Test portfolio summary."""
        # Add and close a winning position
        pos1 = temp_portfolio.add_bull_put_spread(
            symbol="AAPL", short_strike=180, long_strike=175,
            expiration="2025-03-21", net_credit=1.50
        )
        temp_portfolio.close_position(pos1.id, 0.30)  # Win: $120
        
        # Add an open position
        temp_portfolio.add_bull_put_spread(
            symbol="MSFT", short_strike=400, long_strike=395,
            expiration="2025-04-18", net_credit=2.00
        )
        
        summary = temp_portfolio.get_summary()
        
        assert summary.total_positions == 2
        assert summary.open_positions == 1
        assert summary.closed_positions == 1
        assert summary.total_realized_pnl == 120.0
        assert summary.win_rate == 100.0
    
    def test_trade_history(self, temp_portfolio):
        """Test trade history recording."""
        position = temp_portfolio.add_bull_put_spread(
            symbol="AAPL", short_strike=180, long_strike=175,
            expiration="2025-03-21", net_credit=1.50
        )
        temp_portfolio.close_position(position.id, 0.30)
        
        trades = temp_portfolio.get_trades()
        
        assert len(trades) == 2
        assert trades[0].action == TradeAction.OPEN
        assert trades[1].action == TradeAction.CLOSE


class TestPortfolioPnL:
    """Tests for P&L calculations."""
    
    @pytest.fixture
    def portfolio_with_trades(self):
        """Create portfolio with multiple trades."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            filepath = Path(f.name)
        
        manager = PortfolioManager(filepath)
        
        # AAPL win
        pos1 = manager.add_bull_put_spread(
            symbol="AAPL", short_strike=180, long_strike=175,
            expiration="2025-02-21", net_credit=1.50
        )
        manager.expire_position(pos1.id)
        
        # AAPL another win
        pos2 = manager.add_bull_put_spread(
            symbol="AAPL", short_strike=175, long_strike=170,
            expiration="2025-03-21", net_credit=1.20
        )
        manager.close_position(pos2.id, 0.40)
        
        # MSFT loss
        pos3 = manager.add_bull_put_spread(
            symbol="MSFT", short_strike=400, long_strike=395,
            expiration="2025-02-21", net_credit=2.00
        )
        manager.assign_position(pos3.id)
        
        yield manager
        
        if filepath.exists():
            filepath.unlink()
    
    def test_pnl_by_symbol(self, portfolio_with_trades):
        """Test P&L grouped by symbol."""
        pnl = portfolio_with_trades.get_pnl_by_symbol()
        
        # AAPL: $150 + $80 = $230
        assert pnl["AAPL"] == 230.0
        
        # MSFT: -$300 (max loss on 5-wide spread minus $2 credit)
        assert pnl["MSFT"] == -300.0
    
    def test_summary_win_rate(self, portfolio_with_trades):
        """Test win rate calculation."""
        summary = portfolio_with_trades.get_summary()
        
        # 2 wins, 1 loss = 66.67%
        assert summary.win_rate == pytest.approx(66.67, rel=0.01)


class TestGlobalPortfolioManager:
    """Tests for global portfolio manager."""
    
    def test_singleton(self):
        """Test that get_portfolio_manager returns singleton."""
        reset_portfolio_manager()
        
        manager1 = get_portfolio_manager()
        manager2 = get_portfolio_manager()
        
        assert manager1 is manager2
    
    def test_reset(self):
        """Test resetting the global manager."""
        manager1 = get_portfolio_manager()
        reset_portfolio_manager()
        manager2 = get_portfolio_manager()
        
        assert manager1 is not manager2
