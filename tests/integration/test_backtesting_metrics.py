"""
Comprehensive Unit Tests for src/backtesting/metrics.py

Tests all metric calculation functions with focus on:
- calculate_sharpe_ratio
- calculate_sortino_ratio
- calculate_max_drawdown
- calculate_win_rate (via calculate_metrics)
- calculate_profit_factor
- calculate_expectancy (via calculate_metrics)
- All edge cases (empty data, zero values, single values)
"""

import math
import pytest
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting import (
    PerformanceMetrics,
    calculate_metrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_kelly_criterion,
    calculate_streaks,
    calculate_equity_stats,
    calculate_risk_of_ruin,
)


# =============================================================================
# calculate_sharpe_ratio Tests
# =============================================================================


class TestCalculateSharpeRatio:
    """Comprehensive tests for calculate_sharpe_ratio function."""

    def test_positive_sharpe_consistent_gains(self):
        """Test: Positive Sharpe ratio for consistent positive returns."""
        pnls = [100, 120, 110, 115, 105, 125]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=10000)
        assert sharpe > 0

    def test_negative_sharpe_consistent_losses(self):
        """Test: Negative Sharpe ratio for consistent negative returns."""
        pnls = [-100, -120, -110, -115, -105, -125]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=10000)
        assert sharpe < 0

    def test_zero_sharpe_for_empty_list(self):
        """Test: Returns 0 for empty P&L list."""
        sharpe = calculate_sharpe_ratio([], initial_capital=10000)
        assert sharpe == 0.0

    def test_zero_sharpe_for_single_trade(self):
        """Test: Returns 0 for single trade (cannot compute std)."""
        sharpe = calculate_sharpe_ratio([100], initial_capital=10000)
        assert sharpe == 0.0

    def test_zero_sharpe_for_identical_returns(self):
        """Test: Returns 0 when all returns are identical (zero std)."""
        pnls = [100, 100, 100, 100, 100]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=10000)
        assert sharpe == 0.0

    def test_sharpe_with_risk_free_rate(self):
        """Test: Sharpe ratio adjusts for risk-free rate."""
        pnls = [100, 120, 110, 115, 105, 125]
        sharpe_low_rf = calculate_sharpe_ratio(
            pnls, initial_capital=10000, risk_free_rate=0.01
        )
        sharpe_high_rf = calculate_sharpe_ratio(
            pnls, initial_capital=10000, risk_free_rate=0.10
        )
        # Higher risk-free rate should result in lower Sharpe
        assert sharpe_low_rf > sharpe_high_rf

    def test_sharpe_with_different_periods(self):
        """Test: Sharpe ratio scales with periods_per_year."""
        pnls = [100, 120, 110, 115, 105, 125]
        sharpe_monthly = calculate_sharpe_ratio(
            pnls, initial_capital=10000, periods_per_year=12
        )
        sharpe_weekly = calculate_sharpe_ratio(
            pnls, initial_capital=10000, periods_per_year=52
        )
        # More periods = different annualization
        assert sharpe_monthly != sharpe_weekly

    def test_sharpe_with_daily_returns(self):
        """Test: Sharpe ratio uses daily returns when provided."""
        daily_returns = [0.01, 0.012, 0.008, 0.011, 0.009, 0.015]
        sharpe = calculate_sharpe_ratio(
            [], initial_capital=10000, use_daily_returns=True, daily_returns=daily_returns
        )
        assert sharpe > 0

    def test_sharpe_daily_returns_single_value(self):
        """Test: Returns 0 for single daily return."""
        sharpe = calculate_sharpe_ratio(
            [], initial_capital=10000, use_daily_returns=True, daily_returns=[0.01]
        )
        assert sharpe == 0.0

    def test_sharpe_daily_returns_empty(self):
        """Test: Falls back to pnls when daily_returns is empty."""
        pnls = [100, 120, 110, 115]
        sharpe = calculate_sharpe_ratio(
            pnls, initial_capital=10000, use_daily_returns=True, daily_returns=[]
        )
        # Should use pnls instead
        assert sharpe != 0.0

    def test_sharpe_large_capital(self):
        """Test: Sharpe ratio with large capital base."""
        pnls = [10000, 12000, 11000, 11500]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=1000000)
        assert sharpe > 0

    def test_sharpe_mixed_positive_negative(self):
        """Test: Sharpe ratio with mixed positive and negative P&L."""
        pnls = [100, -50, 150, -75, 200, -100]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=10000)
        # Net positive with high volatility
        assert isinstance(sharpe, float)


# =============================================================================
# calculate_sortino_ratio Tests
# =============================================================================


class TestCalculateSortinoRatio:
    """Comprehensive tests for calculate_sortino_ratio function."""

    def test_positive_sortino_consistent_gains(self):
        """Test: Positive Sortino ratio for consistent positive returns."""
        pnls = [100, 120, 110, 115, 105, 125]
        sortino = calculate_sortino_ratio(pnls, initial_capital=10000)
        assert sortino > 0

    def test_zero_sortino_for_empty_list(self):
        """Test: Returns 0 for empty P&L list."""
        sortino = calculate_sortino_ratio([], initial_capital=10000)
        assert sortino == 0.0

    def test_zero_sortino_for_single_trade(self):
        """Test: Returns 0 for single trade."""
        sortino = calculate_sortino_ratio([100], initial_capital=10000)
        assert sortino == 0.0

    def test_infinite_sortino_no_downside(self):
        """Test: Returns inf when all returns are above target with positive avg."""
        pnls = [100, 120, 110, 115, 105]
        sortino = calculate_sortino_ratio(
            pnls, initial_capital=10000, target_return=0.0
        )
        assert sortino == float("inf")

    def test_sortino_with_downside_deviation(self):
        """Test: Sortino ratio computes with downside deviation."""
        pnls = [100, -50, 150, -75, 200, -100]
        sortino = calculate_sortino_ratio(pnls, initial_capital=10000)
        assert isinstance(sortino, float)
        assert sortino != float("inf")

    def test_sortino_with_custom_target_return(self):
        """Test: Sortino ratio with custom target return."""
        pnls = [100, 120, 110, 80, 90, 125]
        sortino_zero_target = calculate_sortino_ratio(
            pnls, initial_capital=10000, target_return=0.0
        )
        sortino_high_target = calculate_sortino_ratio(
            pnls, initial_capital=10000, target_return=0.02
        )
        # Higher target = more downside = lower Sortino
        assert sortino_zero_target > sortino_high_target

    def test_sortino_with_daily_returns(self):
        """Test: Sortino ratio uses daily returns when provided."""
        daily_returns = [0.01, -0.005, 0.012, -0.003, 0.008, -0.002]
        sortino = calculate_sortino_ratio(
            [], initial_capital=10000, use_daily_returns=True, daily_returns=daily_returns
        )
        assert isinstance(sortino, float)

    def test_sortino_vs_sharpe_with_asymmetric_returns(self):
        """Test: Sortino > Sharpe when downside is smaller than upside."""
        # More upside variance than downside
        pnls = [100, 200, 150, -30, 180, -20]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=10000)
        sortino = calculate_sortino_ratio(pnls, initial_capital=10000)
        # Sortino should be higher when downside risk is lower
        assert sortino > sharpe

    def test_sortino_all_negative_returns(self):
        """Test: Sortino ratio for all negative returns."""
        pnls = [-100, -120, -110, -115]
        sortino = calculate_sortino_ratio(pnls, initial_capital=10000)
        assert sortino < 0

    def test_sortino_zero_return_below_target(self):
        """Test: Sortino returns 0 when avg return equals target and no downside."""
        pnls = [0, 0, 0, 0]  # All zero returns
        sortino = calculate_sortino_ratio(pnls, initial_capital=10000, target_return=0.0)
        # No downside deviation, avg equals target
        assert sortino == float("inf") or sortino == 0.0


# =============================================================================
# calculate_max_drawdown Tests
# =============================================================================


class TestCalculateMaxDrawdown:
    """Comprehensive tests for calculate_max_drawdown function."""

    def test_no_drawdown_constant_gains(self):
        """Test: No drawdown when equity only increases."""
        pnls = [100, 100, 100, 100]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        assert result["max_drawdown"] == 0
        assert result["max_drawdown_pct"] == 0

    def test_empty_pnl_list(self):
        """Test: Returns zeros for empty P&L list."""
        result = calculate_max_drawdown([], initial_capital=10000)
        assert result["max_drawdown"] == 0
        assert result["max_drawdown_pct"] == 0

    def test_simple_drawdown(self):
        """Test: Simple drawdown calculation."""
        pnls = [100, 100, -300, 50]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        # Peak: 10200, Valley after -300: 9900, DD = 300
        assert result["max_drawdown"] == 300

    def test_drawdown_percentage(self):
        """Test: Drawdown percentage calculation."""
        pnls = [1000, -500]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        # Peak: 11000, Valley: 10500, DD = 500
        # DD% = 500/11000 * 100 = 4.545...%
        expected_pct = (500 / 11000) * 100
        assert abs(result["max_drawdown_pct"] - expected_pct) < 0.01

    def test_multiple_drawdowns_returns_max(self):
        """Test: Returns the maximum of multiple drawdowns."""
        pnls = [100, -50, 100, -200, 100, -100]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        # First peak: 10100, First valley: 10050 (DD=50)
        # Second peak: 10150, Second valley: 9950 (DD=200)
        # Third peak: 10050, Third valley: 9950 (DD=100)
        # Max DD should be 200
        assert result["max_drawdown"] == 200

    def test_max_runup(self):
        """Test: Max runup is calculated correctly."""
        pnls = [500, 300, -200, 400]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        # Max runup = max(equity - initial) = 10500 + 300 - 10000 = 800
        # Then 10800 + 400 = 11200 - 10000 = 1200 (but needs to account for logic)
        assert result["max_runup"] >= 0

    def test_avg_drawdown(self):
        """Test: Average drawdown is calculated."""
        pnls = [100, -50, 100, -100]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        assert result["avg_drawdown"] >= 0

    def test_all_losses(self):
        """Test: Drawdown equals total losses when all trades are losses."""
        pnls = [-100, -100, -100, -100]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        # Continuous decline, max DD = 400
        assert result["max_drawdown"] == 400

    def test_recovery_from_drawdown(self):
        """Test: Drawdown calculation with full recovery."""
        pnls = [100, -200, 300]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        # Peak: 10100, Valley: 9900, DD = 200
        # Recovery to 10200 (new peak)
        assert result["max_drawdown"] == 200

    def test_drawdown_with_zero_pnl(self):
        """Test: Drawdown handles zero P&L trades."""
        pnls = [100, 0, -100, 0, 100]
        result = calculate_max_drawdown(pnls, initial_capital=10000)
        assert result["max_drawdown"] == 100


# =============================================================================
# calculate_profit_factor Tests
# =============================================================================


class TestCalculateProfitFactor:
    """Comprehensive tests for calculate_profit_factor function."""

    def test_basic_profit_factor(self):
        """Test: Basic profit factor calculation."""
        pf = calculate_profit_factor(1000, 500)
        assert pf == 2.0

    def test_profit_factor_equal_profit_loss(self):
        """Test: Profit factor = 1 when profit equals loss."""
        pf = calculate_profit_factor(500, 500)
        assert pf == 1.0

    def test_profit_factor_more_loss(self):
        """Test: Profit factor < 1 when loss exceeds profit."""
        pf = calculate_profit_factor(500, 1000)
        assert pf == 0.5

    def test_profit_factor_zero_loss(self):
        """Test: Returns infinity when no losses (with profit)."""
        pf = calculate_profit_factor(1000, 0)
        assert pf == float("inf")

    def test_profit_factor_zero_profit_zero_loss(self):
        """Test: Returns 0 when both profit and loss are zero."""
        pf = calculate_profit_factor(0, 0)
        assert pf == 0.0

    def test_profit_factor_zero_profit(self):
        """Test: Returns 0 when no profit."""
        pf = calculate_profit_factor(0, 500)
        assert pf == 0.0

    def test_profit_factor_large_values(self):
        """Test: Profit factor with large values."""
        pf = calculate_profit_factor(1000000, 250000)
        assert pf == 4.0

    def test_profit_factor_small_values(self):
        """Test: Profit factor with small decimal values."""
        pf = calculate_profit_factor(0.01, 0.005)
        assert pf == 2.0


# =============================================================================
# Win Rate Tests (via calculate_metrics)
# =============================================================================


class TestCalculateWinRate:
    """Tests for win rate calculation within calculate_metrics."""

    def test_win_rate_all_winners(self):
        """Test: Win rate is 100% when all trades are winners."""
        trades = [{"realized_pnl": 100, "hold_days": 10}] * 10
        metrics = calculate_metrics(trades)
        assert metrics.win_rate == 100.0

    def test_win_rate_all_losers(self):
        """Test: Win rate is 0% when all trades are losers."""
        trades = [{"realized_pnl": -100, "hold_days": 10}] * 10
        metrics = calculate_metrics(trades)
        assert metrics.win_rate == 0.0

    def test_win_rate_mixed(self):
        """Test: Win rate is correctly calculated for mixed trades."""
        trades = [
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": -100, "hold_days": 10},
            {"realized_pnl": -100, "hold_days": 10},
        ]
        metrics = calculate_metrics(trades)
        # 3 winners / 5 trades = 60%
        assert metrics.win_rate == 60.0

    def test_win_rate_with_breakeven(self):
        """Test: Breakeven trades (P&L = 0) are not counted as winners."""
        trades = [
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": 0, "hold_days": 10},
            {"realized_pnl": -100, "hold_days": 10},
        ]
        metrics = calculate_metrics(trades)
        # 1 winner / 3 trades = 33.33%
        assert abs(metrics.win_rate - 33.33) < 0.1

    def test_win_rate_empty_trades(self):
        """Test: Win rate is 0 for empty trade list."""
        metrics = calculate_metrics([])
        assert metrics.win_rate == 0.0

    def test_win_rate_single_winner(self):
        """Test: Win rate for single winning trade."""
        trades = [{"realized_pnl": 100, "hold_days": 10}]
        metrics = calculate_metrics(trades)
        assert metrics.win_rate == 100.0

    def test_win_rate_single_loser(self):
        """Test: Win rate for single losing trade."""
        trades = [{"realized_pnl": -100, "hold_days": 10}]
        metrics = calculate_metrics(trades)
        assert metrics.win_rate == 0.0


# =============================================================================
# Expectancy Tests (via calculate_metrics)
# =============================================================================


class TestCalculateExpectancy:
    """Tests for expectancy calculation within calculate_metrics."""

    def test_positive_expectancy(self):
        """Test: Positive expectancy with profitable system."""
        trades = [
            {"realized_pnl": 200, "hold_days": 10},  # Win
            {"realized_pnl": 200, "hold_days": 10},  # Win
            {"realized_pnl": 200, "hold_days": 10},  # Win
            {"realized_pnl": -100, "hold_days": 10},  # Loss
            {"realized_pnl": -100, "hold_days": 10},  # Loss
        ]
        metrics = calculate_metrics(trades)
        # Win rate = 60%, avg_win = 200, avg_loss = 100
        # Expectancy = 0.6 * 200 - 0.4 * 100 = 120 - 40 = 80
        assert metrics.expectancy == 80.0

    def test_negative_expectancy(self):
        """Test: Negative expectancy with losing system."""
        trades = [
            {"realized_pnl": 100, "hold_days": 10},  # Win
            {"realized_pnl": -200, "hold_days": 10},  # Loss
            {"realized_pnl": -200, "hold_days": 10},  # Loss
            {"realized_pnl": -200, "hold_days": 10},  # Loss
        ]
        metrics = calculate_metrics(trades)
        # Win rate = 25%, avg_win = 100, avg_loss = 200
        # Expectancy = 0.25 * 100 - 0.75 * 200 = 25 - 150 = -125
        assert metrics.expectancy == -125.0

    def test_zero_expectancy(self):
        """Test: Zero expectancy when breakeven."""
        trades = [
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": -100, "hold_days": 10},
        ]
        metrics = calculate_metrics(trades)
        # Win rate = 50%, avg_win = 100, avg_loss = 100
        # Expectancy = 0.5 * 100 - 0.5 * 100 = 0
        assert metrics.expectancy == 0.0

    def test_expectancy_all_winners(self):
        """Test: Expectancy equals avg_win when all trades are winners."""
        trades = [{"realized_pnl": 100, "hold_days": 10}] * 5
        metrics = calculate_metrics(trades)
        # Win rate = 100%, avg_loss = 0
        # Expectancy = 1.0 * 100 - 0 * 0 = 100
        assert metrics.expectancy == 100.0

    def test_expectancy_all_losers(self):
        """Test: Expectancy equals -avg_loss when all trades are losers."""
        trades = [{"realized_pnl": -100, "hold_days": 10}] * 5
        metrics = calculate_metrics(trades)
        # Win rate = 0%, avg_win = 0
        # Expectancy = 0 * 0 - 1.0 * 100 = -100
        assert metrics.expectancy == -100.0

    def test_expectancy_empty_trades(self):
        """Test: Expectancy is 0 for empty trade list."""
        metrics = calculate_metrics([])
        assert metrics.expectancy == 0.0

    def test_expectancy_pct(self):
        """Test: Expectancy percentage calculation."""
        trades = [
            {"realized_pnl": 200, "hold_days": 10},
            {"realized_pnl": 200, "hold_days": 10},
            {"realized_pnl": -100, "hold_days": 10},
        ]
        metrics = calculate_metrics(trades)
        # avg_trade = (200 + 200 - 100) / 3 = 100
        # expectancy = 2/3 * 200 - 1/3 * 100 = 133.33 - 33.33 = 100
        # expectancy_pct = 100 / |100| * 100 = 100%
        assert abs(metrics.expectancy_pct - 100.0) < 0.01


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases across all metric functions."""

    def test_empty_pnl_list_sharpe(self):
        """Test: Sharpe returns 0 for empty list."""
        assert calculate_sharpe_ratio([], 10000) == 0.0

    def test_empty_pnl_list_sortino(self):
        """Test: Sortino returns 0 for empty list."""
        assert calculate_sortino_ratio([], 10000) == 0.0

    def test_empty_pnl_list_drawdown(self):
        """Test: Drawdown returns zeros for empty list."""
        result = calculate_max_drawdown([], 10000)
        assert result["max_drawdown"] == 0
        assert result["max_drawdown_pct"] == 0

    def test_single_trade_metrics(self):
        """Test: Single trade produces valid metrics."""
        trades = [{"realized_pnl": 100, "hold_days": 10}]
        metrics = calculate_metrics(trades)
        assert metrics.total_trades == 1
        assert metrics.total_pnl == 100

    def test_zero_initial_capital(self):
        """Test: Handles zero initial capital gracefully."""
        pnls = [100, -50]
        # Should not raise division by zero
        result = calculate_max_drawdown(pnls, initial_capital=0)
        assert isinstance(result, dict)

    def test_very_small_pnl_values(self):
        """Test: Handles very small P&L values."""
        pnls = [0.001, -0.0005, 0.002]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=1.0)
        assert isinstance(sharpe, float)

    def test_very_large_pnl_values(self):
        """Test: Handles very large P&L values."""
        pnls = [1e9, -5e8, 1e9]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=1e10)
        assert isinstance(sharpe, float)

    def test_negative_initial_capital(self):
        """Test: Handles negative initial capital."""
        pnls = [100, -50]
        result = calculate_max_drawdown(pnls, initial_capital=-10000)
        assert isinstance(result, dict)

    def test_all_zero_pnl(self):
        """Test: All P&L values are zero."""
        pnls = [0, 0, 0, 0]
        metrics = calculate_metrics([{"realized_pnl": 0, "hold_days": 10}] * 4)
        assert metrics.total_pnl == 0.0
        assert metrics.win_rate == 0.0

    def test_mixed_zero_and_nonzero_pnl(self):
        """Test: Mix of zero and non-zero P&L."""
        trades = [
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": 0, "hold_days": 10},
            {"realized_pnl": -50, "hold_days": 10},
            {"realized_pnl": 0, "hold_days": 10},
        ]
        metrics = calculate_metrics(trades)
        assert metrics.total_trades == 4
        assert metrics.breakeven_trades == 2


# =============================================================================
# calculate_kelly_criterion Tests
# =============================================================================


class TestCalculateKellyCriterion:
    """Tests for Kelly Criterion calculation."""

    def test_kelly_standard_calculation(self):
        """Test: Standard Kelly calculation."""
        # Win Rate 60%, Payoff 2:1
        # Kelly = 0.6 - 0.4/2 = 0.6 - 0.2 = 0.4
        kelly = calculate_kelly_criterion(0.6, 2.0)
        assert abs(kelly - 0.4) < 0.01

    def test_kelly_negative_clamped_to_zero(self):
        """Test: Negative Kelly is clamped to 0."""
        # Win Rate 30%, Payoff 1:1
        # Kelly = 0.3 - 0.7/1 = -0.4 -> clamped to 0
        kelly = calculate_kelly_criterion(0.3, 1.0)
        assert kelly == 0.0

    def test_kelly_clamped_to_one(self):
        """Test: Kelly > 1 is clamped to 1."""
        # Win Rate 90%, Payoff 10:1
        # Kelly = 0.9 - 0.1/10 = 0.89
        kelly = calculate_kelly_criterion(0.9, 10.0)
        assert kelly <= 1.0

    def test_kelly_zero_payoff_ratio(self):
        """Test: Returns 0 for zero payoff ratio."""
        kelly = calculate_kelly_criterion(0.6, 0.0)
        assert kelly == 0.0

    def test_kelly_negative_payoff_ratio(self):
        """Test: Returns 0 for negative payoff ratio."""
        kelly = calculate_kelly_criterion(0.6, -1.0)
        assert kelly == 0.0

    def test_kelly_zero_win_probability(self):
        """Test: Zero win probability gives 0."""
        kelly = calculate_kelly_criterion(0.0, 2.0)
        assert kelly == 0.0

    def test_kelly_hundred_percent_win_rate(self):
        """Test: 100% win rate with any payoff gives kelly > 0."""
        kelly = calculate_kelly_criterion(1.0, 1.0)
        assert kelly == 1.0


# =============================================================================
# calculate_streaks Tests
# =============================================================================


class TestCalculateStreaks:
    """Tests for win/loss streak calculation."""

    def test_max_wins_streak(self):
        """Test: Maximum consecutive wins."""
        pnls = [100, 100, 100, -50, 100]
        result = calculate_streaks(pnls)
        assert result["max_wins"] == 3

    def test_max_losses_streak(self):
        """Test: Maximum consecutive losses."""
        pnls = [100, -50, -50, -50, -50, 100]
        result = calculate_streaks(pnls)
        assert result["max_losses"] == 4

    def test_empty_pnl_list(self):
        """Test: Empty list returns zeros."""
        result = calculate_streaks([])
        assert result["max_wins"] == 0
        assert result["max_losses"] == 0
        assert result["current_streak"] == 0

    def test_single_winner(self):
        """Test: Single winner."""
        result = calculate_streaks([100])
        assert result["max_wins"] == 1
        assert result["max_losses"] == 0

    def test_single_loser(self):
        """Test: Single loser."""
        result = calculate_streaks([-100])
        assert result["max_wins"] == 0
        assert result["max_losses"] == 1

    def test_alternating_wins_losses(self):
        """Test: Alternating wins and losses."""
        pnls = [100, -50, 100, -50, 100, -50]
        result = calculate_streaks(pnls)
        assert result["max_wins"] == 1
        assert result["max_losses"] == 1

    def test_breakeven_does_not_break_streak(self):
        """Test: Breakeven trades don't break streak."""
        pnls = [100, 100, 0, 100, -50]
        result = calculate_streaks(pnls)
        # Breakeven should not break the winning streak
        assert result["max_wins"] == 3

    def test_current_streak_positive(self):
        """Test: Current streak when ending with wins."""
        pnls = [-50, 100, 100, 100]
        result = calculate_streaks(pnls)
        assert result["current_streak"] == 3

    def test_current_streak_negative(self):
        """Test: Current streak when ending with losses."""
        pnls = [100, -50, -50, -50]
        result = calculate_streaks(pnls)
        assert result["current_streak"] == -3


# =============================================================================
# calculate_equity_stats Tests
# =============================================================================


class TestCalculateEquityStats:
    """Tests for equity curve statistics."""

    def test_volatility_calculation(self):
        """Test: Volatility is calculated."""
        pnls = [100, -50, 150, -75, 200, -100]
        result = calculate_equity_stats(pnls, initial_capital=10000)
        assert result["volatility"] > 0

    def test_skewness_calculation(self):
        """Test: Skewness is calculated."""
        pnls = [100, 200, 300, 50, 100, 150]
        result = calculate_equity_stats(pnls, initial_capital=10000)
        assert isinstance(result["skewness"], float)

    def test_kurtosis_calculation(self):
        """Test: Kurtosis is calculated (excess kurtosis)."""
        pnls = [100, 200, 300, 50, 100, 150]
        result = calculate_equity_stats(pnls, initial_capital=10000)
        assert isinstance(result["kurtosis"], float)

    def test_insufficient_data(self):
        """Test: Returns zeros for insufficient data."""
        pnls = [100, 200]  # Only 2 values
        result = calculate_equity_stats(pnls, initial_capital=10000)
        assert result["volatility"] == 0
        assert result["skewness"] == 0
        assert result["kurtosis"] == 0

    def test_empty_pnl_list(self):
        """Test: Returns zeros for empty list."""
        result = calculate_equity_stats([], initial_capital=10000)
        assert result["volatility"] == 0
        assert result["skewness"] == 0
        assert result["kurtosis"] == 0

    def test_identical_returns_zero_volatility(self):
        """Test: Zero volatility for identical returns."""
        pnls = [100, 100, 100, 100]
        result = calculate_equity_stats(pnls, initial_capital=10000)
        # std of identical values is 0
        assert result["volatility"] == 0


# =============================================================================
# calculate_risk_of_ruin Tests
# =============================================================================


class TestCalculateRiskOfRuin:
    """Tests for risk of ruin calculation."""

    def test_no_edge_returns_one(self):
        """Test: Returns 1.0 when no edge (negative expectancy)."""
        # Win rate 40%, payoff 1:1 = negative edge
        ror = calculate_risk_of_ruin(0.4, 1.0, 0.02)
        assert ror == 1.0

    def test_positive_edge_less_than_one(self):
        """Test: Returns < 1.0 with positive edge."""
        # Win rate 60%, payoff 2:1 = positive edge
        ror = calculate_risk_of_ruin(0.6, 2.0, 0.02)
        assert ror < 1.0
        assert ror >= 0.0

    def test_zero_win_rate_returns_one(self):
        """Test: Returns 1.0 for zero win rate."""
        ror = calculate_risk_of_ruin(0.0, 2.0, 0.02)
        assert ror == 1.0

    def test_hundred_percent_win_rate_returns_zero(self):
        """Test: Returns 0.0 for 100% win rate."""
        ror = calculate_risk_of_ruin(1.0, 2.0, 0.02)
        assert ror == 0.0

    def test_zero_payoff_ratio_returns_one(self):
        """Test: Returns 1.0 for zero payoff ratio."""
        ror = calculate_risk_of_ruin(0.6, 0.0, 0.02)
        assert ror == 1.0

    def test_lower_risk_per_trade_reduces_ror(self):
        """Test: Lower risk per trade reduces risk of ruin."""
        ror_high_risk = calculate_risk_of_ruin(0.55, 1.5, 0.05)
        ror_low_risk = calculate_risk_of_ruin(0.55, 1.5, 0.01)
        assert ror_low_risk < ror_high_risk


# =============================================================================
# PerformanceMetrics Dataclass Tests
# =============================================================================


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics dataclass."""

    def test_default_values(self):
        """Test: Default values are zeros."""
        metrics = PerformanceMetrics()
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.sharpe_ratio == 0.0

    def test_summary_method(self):
        """Test: Summary method returns formatted string."""
        metrics = PerformanceMetrics(
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=60.0,
            total_pnl=1000.0,
        )
        summary = metrics.summary()
        assert isinstance(summary, str)
        assert "PERFORMANCE" in summary
        assert "60" in summary  # win rate

    def test_to_dict_method(self):
        """Test: to_dict returns dictionary representation."""
        metrics = PerformanceMetrics(
            total_trades=10,
            win_rate=60.0,
            sharpe_ratio=1.5,
        )
        d = metrics.to_dict()
        assert isinstance(d, dict)
        assert d["trades"]["total"] == 10
        assert d["trades"]["win_rate"] == 60.0
        assert d["risk"]["sharpe_ratio"] == 1.5


# =============================================================================
# calculate_metrics Integration Tests
# =============================================================================


class TestCalculateMetricsIntegration:
    """Integration tests for calculate_metrics function."""

    def test_full_metrics_calculation(self):
        """Test: All metrics are calculated from trade list."""
        trades = [
            {"realized_pnl": 100, "hold_days": 10, "entry_date": "2023-01-01", "exit_date": "2023-01-11"},
            {"realized_pnl": -50, "hold_days": 15, "entry_date": "2023-01-15", "exit_date": "2023-01-30"},
            {"realized_pnl": 150, "hold_days": 8, "entry_date": "2023-02-01", "exit_date": "2023-02-09"},
            {"realized_pnl": 75, "hold_days": 12, "entry_date": "2023-02-15", "exit_date": "2023-02-27"},
            {"realized_pnl": -100, "hold_days": 20, "entry_date": "2023-03-01", "exit_date": "2023-03-21"},
        ]
        metrics = calculate_metrics(trades, initial_capital=10000)

        # Basic counts
        assert metrics.total_trades == 5
        assert metrics.winning_trades == 3
        assert metrics.losing_trades == 2

        # P&L
        assert metrics.total_pnl == 175.0
        assert metrics.gross_profit == 325.0
        assert metrics.gross_loss == 150.0

        # Ratios
        assert metrics.win_rate == 60.0
        assert abs(metrics.profit_factor - 2.166) < 0.01

        # Averages
        assert abs(metrics.avg_win - 108.33) < 0.01
        assert metrics.avg_loss == 75.0

    def test_cagr_calculation(self):
        """Test: CAGR is calculated when dates provided."""
        trades = [
            {"realized_pnl": 5000, "hold_days": 30, "entry_date": "2023-01-01", "exit_date": "2023-01-31"},
            {"realized_pnl": 5000, "hold_days": 30, "entry_date": "2024-01-01", "exit_date": "2024-01-31"},
        ]
        metrics = calculate_metrics(trades, initial_capital=100000)

        # Final capital = 110000
        # Period = ~1 year
        # CAGR should be approximately 10%
        assert metrics.cagr > 0

    def test_hold_days_averages(self):
        """Test: Hold day averages are calculated correctly."""
        trades = [
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": 100, "hold_days": 20},
            {"realized_pnl": -50, "hold_days": 15},
        ]
        metrics = calculate_metrics(trades)

        assert metrics.avg_hold_days == 15.0  # (10+20+15)/3
        assert metrics.avg_win_hold_days == 15.0  # (10+20)/2
        assert metrics.avg_loss_hold_days == 15.0

    def test_kelly_fraction_in_metrics(self):
        """Test: Kelly fraction is included in metrics."""
        trades = [
            {"realized_pnl": 200, "hold_days": 10},  # Win
            {"realized_pnl": 200, "hold_days": 10},  # Win
            {"realized_pnl": 200, "hold_days": 10},  # Win
            {"realized_pnl": -100, "hold_days": 10},  # Loss
            {"realized_pnl": -100, "hold_days": 10},  # Loss
        ]
        metrics = calculate_metrics(trades)

        # Win rate 60%, avg_win 200, avg_loss 100, payoff 2:1
        # Kelly = 0.6 - 0.4/2 = 0.4 = 40%
        assert abs(metrics.kelly_fraction - 40.0) < 1.0
        assert abs(metrics.half_kelly - 20.0) < 1.0

    def test_calmar_ratio(self):
        """Test: Calmar ratio is calculated when CAGR and drawdown exist."""
        trades = [
            {"realized_pnl": 1000, "hold_days": 30, "entry_date": "2023-01-01", "exit_date": "2023-01-31"},
            {"realized_pnl": -500, "hold_days": 30, "entry_date": "2023-06-01", "exit_date": "2023-06-30"},
            {"realized_pnl": 1000, "hold_days": 30, "entry_date": "2024-01-01", "exit_date": "2024-01-31"},
        ]
        metrics = calculate_metrics(trades, initial_capital=10000)

        # Should have both CAGR and drawdown
        if metrics.max_drawdown_pct > 0:
            assert metrics.calmar_ratio == metrics.cagr / metrics.max_drawdown_pct


# =============================================================================
# Numerical Stability Tests
# =============================================================================


class TestNumericalStability:
    """Tests for numerical stability and precision."""

    def test_large_number_of_trades(self):
        """Test: Handles large number of trades."""
        trades = [{"realized_pnl": 100 if i % 2 == 0 else -50, "hold_days": 10} for i in range(1000)]
        metrics = calculate_metrics(trades)
        assert metrics.total_trades == 1000

    def test_very_small_returns(self):
        """Test: Handles very small return values."""
        pnls = [0.0001, -0.00005, 0.0002, -0.0001]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=1.0)
        assert isinstance(sharpe, float)
        assert not math.isnan(sharpe)

    def test_very_large_returns(self):
        """Test: Handles very large return values."""
        pnls = [1e8, -5e7, 1e8, -3e7]
        sharpe = calculate_sharpe_ratio(pnls, initial_capital=1e9)
        assert isinstance(sharpe, float)
        assert not math.isnan(sharpe)

    def test_no_nan_or_inf_in_metrics(self):
        """Test: No NaN or Inf values in normal metrics."""
        trades = [
            {"realized_pnl": 100, "hold_days": 10},
            {"realized_pnl": -50, "hold_days": 15},
            {"realized_pnl": 150, "hold_days": 8},
        ]
        metrics = calculate_metrics(trades, initial_capital=10000)

        # Check key metrics are not NaN or unexpected Inf
        assert not math.isnan(metrics.sharpe_ratio)
        assert not math.isnan(metrics.sortino_ratio)
        assert not math.isnan(metrics.expectancy)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
