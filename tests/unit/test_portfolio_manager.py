# OptionPlay - Portfolio Management Tests (L.1)
# ==============================================
# Comprehensive tests for:
# 1. PortfolioManager — CRUD, P&L, persistence, statistics
# 2. PortfolioConstraintChecker — limits, VIX-adjusted constraints
# 3. PositionSizer — Kelly Criterion, VIX adjustments, stop loss
#
# Test Coverage:
# 1. BullPutSpread Properties (8 tests)
# 2. PortfolioManager CRUD (10 tests)
# 3. P&L Calculations (8 tests)
# 4. Portfolio Statistics (6 tests)
# 5. JSON Persistence (5 tests)
# 6. PortfolioConstraintChecker (10 tests)
# 7. PositionSizer Kelly Criterion (6 tests)
# 8. PositionSizer VIX Adjustments (5 tests)
# 9. PositionSizer Edge Cases (5 tests)
# 10. Stop Loss Calculation (4 tests)

import json
import math
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.portfolio.manager import (
    BullPutSpread,
    PortfolioManager,
    PortfolioSummary,
    PositionStatus,
    SpreadLeg,
    TradeAction,
    TradeRecord,
)
from src.risk.position_sizing import (
    KellyMode,
    PositionSizer,
    PositionSizerConfig,
    PositionSizeResult,
    VIXRegime,
    calculate_optimal_position,
    get_recommended_stop_loss,
)
from src.services.portfolio_constraints import (
    ConstraintResult,
    PortfolioConstraintChecker,
    PortfolioConstraints,
)

# =============================================================================
# FIXTURES
# =============================================================================


def make_spread(
    short_strike=180.0,
    long_strike=175.0,
    short_premium=2.50,
    long_premium=-1.00,
    contracts=1,
    expiration=None,
    status=PositionStatus.OPEN,
    spread_id="test-001",
    symbol="AAPL",
) -> BullPutSpread:
    """Create a test BullPutSpread."""
    if expiration is None:
        expiration = (date.today() + timedelta(days=30)).isoformat()
    return BullPutSpread(
        id=spread_id,
        symbol=symbol,
        short_leg=SpreadLeg(
            strike=short_strike,
            expiration=expiration,
            right="P",
            quantity=-contracts,
            premium=short_premium,
        ),
        long_leg=SpreadLeg(
            strike=long_strike,
            expiration=expiration,
            right="P",
            quantity=contracts,
            premium=long_premium,
        ),
        contracts=contracts,
        open_date=date.today().isoformat(),
        status=status,
    )


@pytest.fixture
def tmp_portfolio(tmp_path):
    """Portfolio manager with temp file."""
    filepath = tmp_path / "test_portfolio.json"
    return PortfolioManager(filepath=filepath)


@pytest.fixture
def sizer():
    """Standard position sizer with $100k account."""
    return PositionSizer(account_size=100_000)


@pytest.fixture
def checker():
    """Constraint checker with no fundamentals (mocked away)."""
    c = PortfolioConstraintChecker()
    c._fundamentals_manager = MagicMock()
    c._fundamentals_manager.get_fundamentals.return_value = None
    return c


# =============================================================================
# 1. BULL PUT SPREAD PROPERTIES
# =============================================================================


class TestBullPutSpreadProperties:
    """Tests for BullPutSpread calculated properties."""

    def test_spread_width(self):
        s = make_spread(short_strike=180, long_strike=175)
        assert s.spread_width == 5.0

    def test_net_credit(self):
        s = make_spread(short_premium=2.50, long_premium=-1.00)
        assert s.net_credit == 1.50

    def test_total_credit_single_contract(self):
        s = make_spread(short_premium=2.50, long_premium=-1.00, contracts=1)
        assert s.total_credit == 150.0  # 1.50 * 1 * 100

    def test_total_credit_multiple_contracts(self):
        s = make_spread(short_premium=2.50, long_premium=-1.00, contracts=3)
        assert s.total_credit == 450.0  # 1.50 * 3 * 100

    def test_max_profit_equals_total_credit(self):
        s = make_spread()
        assert s.max_profit == s.total_credit

    def test_max_loss(self):
        s = make_spread(
            short_strike=180,
            long_strike=175,
            short_premium=2.50,
            long_premium=-1.00,
            contracts=2,
        )
        # (5.0 - 1.50) * 2 * 100 = 700
        assert s.max_loss == 700.0

    def test_breakeven(self):
        s = make_spread(short_strike=180, short_premium=2.50, long_premium=-1.00)
        # 180 - 1.50 = 178.50
        assert s.breakeven == 178.50

    def test_days_to_expiration(self):
        exp = (date.today() + timedelta(days=15)).isoformat()
        s = make_spread(expiration=exp)
        assert s.days_to_expiration == 15

    def test_is_expired(self):
        exp = (date.today() - timedelta(days=1)).isoformat()
        s = make_spread(expiration=exp)
        assert s.is_expired is True


# =============================================================================
# 2. PORTFOLIO MANAGER CRUD
# =============================================================================


class TestPortfolioManagerCRUD:
    """Tests for adding, closing, expiring, assigning, and deleting positions."""

    def test_add_bull_put_spread(self, tmp_portfolio):
        pos = tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
            contracts=2,
        )
        assert pos.symbol == "AAPL"
        assert pos.contracts == 2
        assert pos.status == PositionStatus.OPEN
        assert len(tmp_portfolio.get_all_positions()) == 1

    def test_add_validates_strikes(self, tmp_portfolio):
        with pytest.raises(ValueError, match="Short strike must be higher"):
            tmp_portfolio.add_bull_put_spread(
                symbol="AAPL",
                short_strike=175,
                long_strike=180,
                expiration="2026-06-20",
                net_credit=1.50,
            )

    def test_add_validates_credit(self, tmp_portfolio):
        with pytest.raises(ValueError, match="Net credit must be positive"):
            tmp_portfolio.add_bull_put_spread(
                symbol="AAPL",
                short_strike=180,
                long_strike=175,
                expiration="2026-06-20",
                net_credit=-0.50,
            )

    def test_add_validates_contracts(self, tmp_portfolio):
        with pytest.raises(ValueError, match="Contracts must be at least 1"):
            tmp_portfolio.add_bull_put_spread(
                symbol="AAPL",
                short_strike=180,
                long_strike=175,
                expiration="2026-06-20",
                net_credit=1.50,
                contracts=0,
            )

    def test_close_position(self, tmp_portfolio):
        pos = tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
        )
        closed = tmp_portfolio.close_position(pos.id, close_premium=0.30)
        assert closed.status == PositionStatus.CLOSED
        assert closed.close_premium == 0.30

    def test_close_nonexistent_raises(self, tmp_portfolio):
        with pytest.raises(ValueError, match="Position not found"):
            tmp_portfolio.close_position("nonexistent", close_premium=0.30)

    def test_close_already_closed_raises(self, tmp_portfolio):
        pos = tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
        )
        tmp_portfolio.close_position(pos.id, close_premium=0.30)
        with pytest.raises(ValueError, match="Position is not open"):
            tmp_portfolio.close_position(pos.id, close_premium=0.20)

    def test_expire_position(self, tmp_portfolio):
        pos = tmp_portfolio.add_bull_put_spread(
            symbol="MSFT",
            short_strike=400,
            long_strike=395,
            expiration="2026-06-20",
            net_credit=1.20,
        )
        expired = tmp_portfolio.expire_position(pos.id)
        assert expired.status == PositionStatus.EXPIRED

    def test_assign_position(self, tmp_portfolio):
        pos = tmp_portfolio.add_bull_put_spread(
            symbol="TSLA",
            short_strike=200,
            long_strike=190,
            expiration="2026-06-20",
            net_credit=2.00,
        )
        assigned = tmp_portfolio.assign_position(pos.id)
        assert assigned.status == PositionStatus.ASSIGNED

    def test_delete_position(self, tmp_portfolio):
        pos = tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
        )
        tmp_portfolio.delete_position(pos.id)
        assert len(tmp_portfolio.get_all_positions()) == 0
        assert tmp_portfolio.get_position(pos.id) is None


# =============================================================================
# 3. P&L CALCULATIONS
# =============================================================================


class TestPnLCalculations:
    """Tests for realized and unrealized P&L."""

    def test_realized_pnl_closed_profit(self):
        """Close at profit: credit $150, close cost $30 => P&L $120."""
        s = make_spread(
            short_premium=2.50,
            long_premium=-1.00,
            status=PositionStatus.CLOSED,
            contracts=1,
        )
        s.close_premium = 0.30
        assert s.realized_pnl() == pytest.approx(120.0)

    def test_realized_pnl_closed_loss(self):
        """Close at loss: credit $150, close cost $400 => P&L -$250."""
        s = make_spread(
            short_premium=2.50,
            long_premium=-1.00,
            status=PositionStatus.CLOSED,
            contracts=1,
        )
        s.close_premium = 4.00
        assert s.realized_pnl() == pytest.approx(-250.0)

    def test_realized_pnl_expired(self):
        """Expired worthless: keep full credit."""
        s = make_spread(
            short_premium=2.50,
            long_premium=-1.00,
            status=PositionStatus.EXPIRED,
            contracts=2,
        )
        assert s.realized_pnl() == pytest.approx(300.0)

    def test_realized_pnl_assigned(self):
        """Assignment: max loss."""
        s = make_spread(
            short_strike=180,
            long_strike=175,
            short_premium=2.50,
            long_premium=-1.00,
            status=PositionStatus.ASSIGNED,
            contracts=1,
        )
        # Max loss = (5.0 - 1.50) * 1 * 100 = 350
        assert s.realized_pnl() == pytest.approx(-350.0)

    def test_realized_pnl_open_returns_none(self):
        s = make_spread(status=PositionStatus.OPEN)
        assert s.realized_pnl() is None

    def test_unrealized_pnl_profit(self):
        """Open with credit $150, current cost $80 => unrealized $70."""
        s = make_spread(short_premium=2.50, long_premium=-1.00, contracts=1)
        assert s.unrealized_pnl(0.80) == pytest.approx(70.0)

    def test_unrealized_pnl_loss(self):
        """Open with credit $150, current cost $300 => unrealized -$150."""
        s = make_spread(short_premium=2.50, long_premium=-1.00, contracts=1)
        assert s.unrealized_pnl(3.00) == pytest.approx(-150.0)

    def test_unrealized_pnl_closed_returns_zero(self):
        s = make_spread(status=PositionStatus.CLOSED)
        assert s.unrealized_pnl(1.00) == 0.0


# =============================================================================
# 4. PORTFOLIO STATISTICS
# =============================================================================


class TestPortfolioStatistics:
    """Tests for portfolio summary and aggregated statistics."""

    def test_summary_empty_portfolio(self, tmp_portfolio):
        summary = tmp_portfolio.get_summary()
        assert summary.total_positions == 0
        assert summary.win_rate == 0.0

    def test_summary_with_positions(self, tmp_portfolio):
        # Add 3 positions
        p1 = tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
        )
        p2 = tmp_portfolio.add_bull_put_spread(
            symbol="MSFT",
            short_strike=400,
            long_strike=395,
            expiration="2026-06-20",
            net_credit=1.20,
        )
        p3 = tmp_portfolio.add_bull_put_spread(
            symbol="GOOG",
            short_strike=170,
            long_strike=165,
            expiration="2026-06-20",
            net_credit=1.00,
        )
        # Close 2: one profit, one loss
        tmp_portfolio.expire_position(p1.id)
        tmp_portfolio.close_position(p2.id, close_premium=3.00)

        summary = tmp_portfolio.get_summary()
        assert summary.total_positions == 3
        assert summary.open_positions == 1
        assert summary.closed_positions == 2
        assert summary.win_rate == 50.0  # 1 win / 2 closed

    def test_win_rate_all_wins(self, tmp_portfolio):
        for sym in ["AAPL", "MSFT", "GOOG"]:
            p = tmp_portfolio.add_bull_put_spread(
                symbol=sym,
                short_strike=180,
                long_strike=175,
                expiration="2026-06-20",
                net_credit=1.50,
            )
            tmp_portfolio.expire_position(p.id)

        summary = tmp_portfolio.get_summary()
        assert summary.win_rate == 100.0

    def test_capital_at_risk(self, tmp_portfolio):
        tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
            contracts=2,
        )
        summary = tmp_portfolio.get_summary()
        # max_loss = (5 - 1.50) * 2 * 100 = 700
        assert summary.total_capital_at_risk == pytest.approx(700.0)

    def test_pnl_by_symbol(self, tmp_portfolio):
        p1 = tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
        )
        p2 = tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=185,
            long_strike=180,
            expiration="2026-06-20",
            net_credit=1.00,
        )
        tmp_portfolio.expire_position(p1.id)
        tmp_portfolio.expire_position(p2.id)

        pnl_map = tmp_portfolio.get_pnl_by_symbol()
        assert "AAPL" in pnl_map
        assert pnl_map["AAPL"] == pytest.approx(250.0)  # 150 + 100

    def test_monthly_pnl(self, tmp_portfolio):
        p = tmp_portfolio.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
        )
        tmp_portfolio.expire_position(p.id)

        monthly = tmp_portfolio.get_monthly_pnl()
        today_month = date.today().isoformat()[:7]
        assert today_month in monthly


# =============================================================================
# 5. JSON PERSISTENCE
# =============================================================================


class TestPersistence:
    """Tests for save/load cycle."""

    def test_save_and_reload(self, tmp_path):
        filepath = tmp_path / "portfolio.json"
        pm = PortfolioManager(filepath=filepath)
        pos = pm.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
            contracts=2,
        )

        # Reload
        pm2 = PortfolioManager(filepath=filepath)
        assert len(pm2.get_all_positions()) == 1
        reloaded = pm2.get_position(pos.id)
        assert reloaded is not None
        assert reloaded.symbol == "AAPL"
        assert reloaded.contracts == 2

    def test_persistence_across_close(self, tmp_path):
        filepath = tmp_path / "portfolio.json"
        pm = PortfolioManager(filepath=filepath)
        pos = pm.add_bull_put_spread(
            symbol="MSFT",
            short_strike=400,
            long_strike=395,
            expiration="2026-06-20",
            net_credit=1.20,
        )
        pm.close_position(pos.id, close_premium=0.50)

        pm2 = PortfolioManager(filepath=filepath)
        reloaded = pm2.get_position(pos.id)
        assert reloaded.status == PositionStatus.CLOSED
        assert reloaded.close_premium == 0.50

    def test_trade_history_persists(self, tmp_path):
        filepath = tmp_path / "portfolio.json"
        pm = PortfolioManager(filepath=filepath)
        pos = pm.add_bull_put_spread(
            symbol="AAPL",
            short_strike=180,
            long_strike=175,
            expiration="2026-06-20",
            net_credit=1.50,
        )

        pm2 = PortfolioManager(filepath=filepath)
        trades = pm2.get_trades(pos.id)
        assert len(trades) == 1
        assert trades[0].action == TradeAction.OPEN

    def test_empty_file_handled(self, tmp_path):
        filepath = tmp_path / "portfolio.json"
        filepath.write_text("{}")
        pm = PortfolioManager(filepath=filepath)
        assert len(pm.get_all_positions()) == 0

    def test_nonexistent_file_handled(self, tmp_path):
        filepath = tmp_path / "does_not_exist.json"
        pm = PortfolioManager(filepath=filepath)
        assert len(pm.get_all_positions()) == 0


# =============================================================================
# 6. PORTFOLIO CONSTRAINT CHECKER
# =============================================================================


class TestPortfolioConstraintChecker:
    """Tests for constraint checking logic."""

    def test_allows_first_position(self, checker):
        allowed, msgs = checker.can_open_position(
            symbol="AAPL",
            max_risk=500,
            open_positions=[],
        )
        assert allowed is True

    def test_blocks_at_position_limit(self, checker):
        positions = [{"symbol": f"SYM{i}"} for i in range(5)]
        allowed, msgs = checker.can_open_position(
            symbol="NEW",
            max_risk=500,
            open_positions=positions,
        )
        assert allowed is False
        assert any("Positions-Limit" in m for m in msgs)

    def test_blocks_oversized_position(self, checker):
        allowed, msgs = checker.can_open_position(
            symbol="AAPL",
            max_risk=5000,
            open_positions=[],
        )
        assert allowed is False
        assert any("Position zu groß" in m for m in msgs)

    def test_blocks_daily_risk_exceeded(self, checker):
        checker.update_risk_used(daily_risk=1400)
        allowed, msgs = checker.can_open_position(
            symbol="AAPL",
            max_risk=200,
            open_positions=[],
        )
        assert allowed is False
        assert any("Tages-Budget" in m for m in msgs)

    def test_blacklisted_symbol(self, checker):
        # Add a symbol to blacklist
        checker.constraints.symbol_blacklist.append("DANGR")
        allowed, msgs = checker.can_open_position(
            symbol="DANGR",
            max_risk=100,
            open_positions=[],
        )
        assert allowed is False
        assert any("Blacklist" in m for m in msgs)

    def test_weekly_risk_warning(self, checker):
        checker.update_risk_used(weekly_risk=4500)
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=400,
            open_positions=[],
        )
        # Should be allowed but with warning
        assert result.allowed is True
        assert any("Wochen-Budget" in w for w in result.warnings)

    def test_vix_no_trading_blocks(self, checker):
        result = checker.check_all_constraints(
            symbol="AAPL",
            max_risk=500,
            open_positions=[],
            current_vix=36.0,
        )
        assert result.allowed is False
        assert any("Keine neuen Trades" in b for b in result.blockers)

    def test_vix_danger_zone_limits(self, checker):
        limits = checker.get_position_limits(vix=22.0)
        assert limits["max_positions"] <= 5
        assert limits["regime"] == "DANGER_ZONE"

    def test_reset_daily_risk(self, checker):
        checker.update_risk_used(daily_risk=1000)
        checker.reset_daily_risk()
        assert checker._daily_risk_used == 0.0

    def test_constraint_result_messages(self, checker):
        """Messages combine blockers and warnings."""
        result = ConstraintResult(
            allowed=False,
            blockers=["Block1"],
            warnings=["Warn1"],
            details={},
        )
        assert len(result.messages) == 2


# =============================================================================
# 7. POSITION SIZER — KELLY CRITERION
# =============================================================================


class TestKellyCriterion:
    """Tests for Kelly fraction calculation."""

    def test_positive_edge_produces_fraction(self, sizer):
        # 65% WR, 1.5:1 payoff => Kelly = 0.65 - 0.35/1.5 = 0.4167
        # Half Kelly => ~0.208, capped at 0.25
        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
        )
        assert kelly > 0
        assert kelly <= sizer.config.kelly_cap

    def test_no_edge_returns_zero(self, sizer):
        # 30% WR, 1:1 payoff => Kelly = 0.30 - 0.70 = -0.40 => 0
        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.30,
            avg_win=100,
            avg_loss=100,
        )
        assert kelly == 0.0

    def test_zero_win_rate(self, sizer):
        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.0,
            avg_win=100,
            avg_loss=100,
        )
        assert kelly == 0.0

    def test_perfect_win_rate_returns_zero(self, sizer):
        """win_rate=1.0 triggers early return."""
        kelly = sizer.calculate_kelly_fraction(
            win_rate=1.0,
            avg_win=100,
            avg_loss=100,
        )
        assert kelly == 0.0

    def test_zero_avg_loss_returns_zero(self, sizer):
        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.65,
            avg_win=100,
            avg_loss=0,
        )
        assert kelly == 0.0

    def test_quarter_kelly_mode(self):
        config = PositionSizerConfig(kelly_mode=KellyMode.QUARTER)
        sizer = PositionSizer(100_000, config=config)
        kelly = sizer.calculate_kelly_fraction(
            win_rate=0.70,
            avg_win=200,
            avg_loss=100,
        )
        # Should be smaller than default half-kelly
        half_sizer = PositionSizer(100_000)
        half_kelly = half_sizer.calculate_kelly_fraction(
            win_rate=0.70,
            avg_win=200,
            avg_loss=100,
        )
        assert kelly < half_kelly


# =============================================================================
# 8. POSITION SIZER — VIX ADJUSTMENTS
# =============================================================================


class TestVIXAdjustments:
    """Tests for VIX-based position sizing."""

    def test_low_vix_no_reduction(self, sizer):
        adj = sizer.get_vix_adjustment(12.0)
        assert adj == 1.0

    def test_normal_vix_no_reduction(self, sizer):
        adj = sizer.get_vix_adjustment(18.0)
        assert adj == 1.0

    def test_elevated_vix_reduces(self, sizer):
        adj = sizer.get_vix_adjustment(25.0)
        assert adj == 0.75

    def test_high_vix_halves(self, sizer):
        adj = sizer.get_vix_adjustment(33.0)
        assert adj == 0.50

    def test_extreme_vix_quarter(self, sizer):
        adj = sizer.get_vix_adjustment(45.0)
        assert adj == 0.25


# =============================================================================
# 9. POSITION SIZER — EDGE CASES
# =============================================================================


class TestPositionSizerEdgeCases:
    """Tests for edge cases in position sizing."""

    def test_zero_max_loss_per_contract(self, sizer):
        result = sizer.calculate_position_size(
            max_loss_per_contract=0,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
        )
        assert result.contracts == 0
        assert result.limiting_factor == "invalid_max_loss"

    def test_negative_expectancy_no_trade(self, sizer):
        """Negative edge should produce 0 contracts."""
        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.30,
            avg_win=100,
            avg_loss=200,
        )
        assert result.contracts == 0

    def test_score_below_min_no_trade(self, sizer):
        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            signal_score=3.0,  # Below min 5.0
        )
        assert result.contracts == 0

    def test_full_portfolio_no_capacity(self):
        sizer = PositionSizer(
            account_size=100_000,
            current_exposure=20_000,  # = max_portfolio_risk * account
        )
        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
        )
        assert result.contracts == 0

    def test_reliability_f_no_trade(self, sizer):
        """Grade F reliability should zero out the trade."""
        adj = sizer.get_reliability_adjustment("F")
        assert adj == 0.0
        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
            reliability_grade="F",
        )
        assert result.contracts == 0


# =============================================================================
# 10. STOP LOSS CALCULATION
# =============================================================================


class TestStopLoss:
    """Tests for stop loss calculation."""

    def test_default_stop_loss(self, sizer):
        result = sizer.calculate_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=18.0,
        )
        assert result["stop_loss_pct"] == pytest.approx(100.0)

    def test_high_vix_tighter_stops(self, sizer):
        result = sizer.calculate_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=35.0,
        )
        assert result["stop_loss_pct"] <= 75.0

    def test_good_reliability_wider_stops(self, sizer):
        result = sizer.calculate_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=18.0,
            reliability_grade="A",
        )
        assert result["stop_loss_pct"] > 100.0  # 20% wider

    def test_stop_loss_capped_at_spread_width(self, sizer):
        result = sizer.calculate_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=18.0,
        )
        # max_loss should never exceed spread_width - net_credit
        assert result["max_loss"] <= (5.0 - 1.50)


# =============================================================================
# 11. CONVENIENCE FUNCTIONS
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_calculate_optimal_position(self):
        result = calculate_optimal_position(
            account_size=100_000,
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
        )
        assert isinstance(result, PositionSizeResult)
        assert result.contracts >= 0

    def test_get_recommended_stop_loss(self):
        pct = get_recommended_stop_loss(
            net_credit=1.50,
            spread_width=5.0,
            vix_level=20.0,
        )
        assert 50.0 <= pct <= 150.0


# =============================================================================
# 12. SPREAD LEG AND TRADE RECORD SERIALIZATION
# =============================================================================


class TestSerialization:
    """Tests for to_dict / from_dict round-trips."""

    def test_spread_leg_round_trip(self):
        leg = SpreadLeg(strike=180, expiration="2026-06-20", right="P", quantity=-1, premium=2.50)
        d = leg.to_dict()
        restored = SpreadLeg.from_dict(d)
        assert restored.strike == 180
        assert restored.premium == 2.50

    def test_bull_put_spread_round_trip(self):
        s = make_spread(symbol="NVDA", contracts=3)
        d = s.to_dict()
        restored = BullPutSpread.from_dict(d)
        assert restored.symbol == "NVDA"
        assert restored.contracts == 3
        assert restored.status == PositionStatus.OPEN

    def test_trade_record_round_trip(self):
        tr = TradeRecord(
            id="tr-001",
            position_id="pos-001",
            action=TradeAction.OPEN,
            timestamp="2026-02-17T10:00:00",
            symbol="AAPL",
            details={"strike": 180},
            notes="test",
        )
        d = tr.to_dict()
        restored = TradeRecord.from_dict(d)
        assert restored.action == TradeAction.OPEN
        assert restored.details["strike"] == 180

    def test_position_size_result_to_dict(self, sizer):
        result = sizer.calculate_position_size(
            max_loss_per_contract=500,
            win_rate=0.65,
            avg_win=150,
            avg_loss=100,
        )
        d = result.to_dict()
        assert "position" in d
        assert "kelly" in d
        assert "adjustments" in d
        assert "metrics" in d
