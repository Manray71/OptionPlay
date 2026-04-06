# OptionPlay - Spread Analyzer Tests
# ====================================
# Comprehensive tests for spread_analyzer.py
#
# Tests cover:
# 1. SpreadAnalyzer initialization
# 2. analyze_spread method
# 3. calculate_risk_reward method
# 4. calculate_probability_of_profit method
# 5. Greeks calculation
# 6. Edge cases and validation

import pytest
import math
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.options.spread_analyzer import (
    SpreadAnalyzer,
    BullPutSpreadParams,
    SpreadAnalysis,
    SpreadRiskLevel,
    PnLScenario,
    analyze_bull_put_spread,
)


# =============================================================================
# TEST DATA FIXTURES
# =============================================================================


@pytest.fixture
def default_analyzer():
    """Standard SpreadAnalyzer with default config."""
    return SpreadAnalyzer()


@pytest.fixture
def sample_params():
    """Standard Bull-Put-Spread parameters for testing."""
    return BullPutSpreadParams(
        symbol="AAPL",
        current_price=180.0,
        short_strike=175.0,
        long_strike=170.0,
        net_credit=1.50,
        dte=45,
        contracts=1,
    )


@pytest.fixture
def params_with_greeks():
    """Bull-Put-Spread parameters with Greeks provided."""
    return BullPutSpreadParams(
        symbol="AAPL",
        current_price=180.0,
        short_strike=175.0,
        long_strike=170.0,
        net_credit=1.50,
        dte=45,
        contracts=1,
        short_delta=-0.25,
        long_delta=-0.12,
        short_theta=0.05,
        short_iv=0.30,
    )


@pytest.fixture
def params_with_iv_only():
    """Bull-Put-Spread parameters with only IV provided (for Black-Scholes path)."""
    return BullPutSpreadParams(
        symbol="MSFT",
        current_price=400.0,
        short_strike=380.0,
        long_strike=370.0,
        net_credit=2.50,
        dte=30,
        contracts=2,
        short_iv=0.28,
    )


# =============================================================================
# BULLPUTSPREADPARAMS VALIDATION TESTS
# =============================================================================


class TestBullPutSpreadParamsValidation:
    """Tests for BullPutSpreadParams dataclass validation."""

    def test_valid_params_accepted(self):
        """Valid parameters should create instance successfully."""
        params = BullPutSpreadParams(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45,
        )
        assert params.symbol == "AAPL"
        assert params.short_strike == 175.0
        assert params.long_strike == 170.0
        assert params.contracts == 1  # Default value

    def test_short_strike_below_long_rejected(self):
        """Short strike below long strike should raise ValueError."""
        with pytest.raises(ValueError, match="Short Strike must be higher"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=90.0,
                long_strike=95.0,
                net_credit=1.00,
                dte=30,
            )

    def test_short_strike_equals_long_rejected(self):
        """Short strike equal to long strike should raise ValueError."""
        with pytest.raises(ValueError, match="Short Strike must be higher"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=90.0,
                long_strike=90.0,
                net_credit=1.00,
                dte=30,
            )

    def test_negative_credit_rejected(self):
        """Negative net credit should raise ValueError."""
        with pytest.raises(ValueError, match="Net Credit must be positive"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=95.0,
                long_strike=90.0,
                net_credit=-0.50,
                dte=30,
            )

    def test_zero_credit_rejected(self):
        """Zero net credit should raise ValueError."""
        with pytest.raises(ValueError, match="Net Credit must be positive"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=95.0,
                long_strike=90.0,
                net_credit=0.0,
                dte=30,
            )

    def test_itm_short_strike_rejected(self):
        """Short strike above current price (ITM) should raise ValueError."""
        with pytest.raises(ValueError, match="Short Strike should be below current price"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=105.0,
                long_strike=100.0,
                net_credit=2.00,
                dte=30,
            )

    def test_short_strike_at_current_price_rejected(self):
        """Short strike at current price should raise ValueError."""
        with pytest.raises(ValueError, match="Short Strike should be below current price"):
            BullPutSpreadParams(
                symbol="TEST",
                current_price=100.0,
                short_strike=100.0,
                long_strike=95.0,
                net_credit=1.50,
                dte=30,
            )

    def test_optional_greeks_default_to_none(self):
        """Optional Greeks parameters should default to None."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
        )
        assert params.short_delta is None
        assert params.short_theta is None
        assert params.short_iv is None
        assert params.long_delta is None


# =============================================================================
# SPREADANALYZER INITIALIZATION TESTS
# =============================================================================


class TestSpreadAnalyzerInitialization:
    """Tests for SpreadAnalyzer initialization and configuration."""

    def test_default_initialization(self):
        """Analyzer should initialize with default config."""
        analyzer = SpreadAnalyzer()
        assert analyzer is not None
        assert analyzer.config is not None
        assert isinstance(analyzer.config, dict)

    def test_default_config_values(self):
        """Default config should have all required keys with correct values."""
        analyzer = SpreadAnalyzer()

        # Risk level thresholds
        assert analyzer.config["low_risk_max_credit_pct"] == 20
        assert analyzer.config["moderate_risk_max_credit_pct"] == 30
        assert analyzer.config["high_risk_max_credit_pct"] == 40

        # Warning thresholds
        assert analyzer.config["min_buffer_pct"] == 5.0
        assert analyzer.config["min_credit_pct"] == 10.0
        assert analyzer.config["max_dte_for_theta"] == 60

        # Profit targets
        assert analyzer.config["profit_target_conservative"] == 50
        assert analyzer.config["profit_target_standard"] == 50
        assert analyzer.config["profit_target_aggressive"] == 50

    def test_custom_config_overrides(self):
        """Custom config should override defaults."""
        custom_config = {
            "low_risk_max_credit_pct": 15,
            "min_buffer_pct": 8.0,
            "profit_target_standard": 70,
        }
        analyzer = SpreadAnalyzer(config=custom_config)

        # Overridden values
        assert analyzer.config["low_risk_max_credit_pct"] == 15
        assert analyzer.config["min_buffer_pct"] == 8.0
        assert analyzer.config["profit_target_standard"] == 70

        # Non-overridden defaults preserved
        assert analyzer.config["moderate_risk_max_credit_pct"] == 30
        assert analyzer.config["high_risk_max_credit_pct"] == 40

    def test_empty_config_uses_defaults(self):
        """Empty custom config should use all defaults."""
        analyzer = SpreadAnalyzer(config={})
        assert analyzer.config["low_risk_max_credit_pct"] == 20

    def test_none_config_uses_defaults(self):
        """None config should use all defaults."""
        analyzer = SpreadAnalyzer(config=None)
        assert analyzer.config["low_risk_max_credit_pct"] == 20


# =============================================================================
# ANALYZE METHOD TESTS
# =============================================================================


class TestAnalyzeMethod:
    """Tests for the main analyze() method."""

    def test_analyze_returns_spread_analysis(self, default_analyzer, sample_params):
        """analyze() should return SpreadAnalysis instance."""
        result = default_analyzer.analyze(sample_params)
        assert isinstance(result, SpreadAnalysis)

    def test_analyze_populates_all_required_fields(self, default_analyzer, sample_params):
        """analyze() should populate all required fields in SpreadAnalysis."""
        result = default_analyzer.analyze(sample_params)

        # Basic info
        assert result.symbol == "AAPL"
        assert result.current_price == 180.0
        assert result.short_strike == 175.0
        assert result.long_strike == 170.0
        assert result.spread_width == 5.0
        assert result.net_credit == 1.50
        assert result.contracts == 1
        assert result.dte == 45

        # Calculated metrics - should be numbers
        assert isinstance(result.max_profit, (int, float))
        assert isinstance(result.max_loss, (int, float))
        assert isinstance(result.break_even, (int, float))
        assert isinstance(result.risk_reward_ratio, (int, float))
        assert isinstance(result.distance_to_short_strike, (int, float))
        assert isinstance(result.distance_to_break_even, (int, float))
        assert isinstance(result.buffer_to_loss, (int, float))
        assert isinstance(result.prob_profit, (int, float))
        assert isinstance(result.prob_max_profit, (int, float))
        assert isinstance(result.expected_value, (int, float))
        assert isinstance(result.credit_to_width_ratio, (int, float))

        # Risk level
        assert isinstance(result.risk_level, SpreadRiskLevel)

        # Lists
        assert isinstance(result.scenarios, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.recommendations, list)

    def test_analyze_with_multiple_contracts(self, default_analyzer):
        """analyze() should correctly scale for multiple contracts."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=5,
        )
        result = default_analyzer.analyze(params)

        # Max profit = $1.00 * 100 * 5 = $500
        assert result.max_profit == 500.0
        # Max loss = ($5.00 - $1.00) * 100 * 5 = $2000
        assert result.max_loss == 2000.0

    def test_analyze_with_greeks_provided(self, default_analyzer, params_with_greeks):
        """analyze() should use provided Greeks when available."""
        result = default_analyzer.analyze(params_with_greeks)

        # Greeks should be populated
        assert result.net_delta is not None
        assert result.net_theta is not None
        assert result.theta_per_day is not None

    def test_analyze_generates_scenarios(self, default_analyzer, sample_params):
        """analyze() should generate P&L scenarios."""
        result = default_analyzer.analyze(sample_params)

        assert len(result.scenarios) > 0
        assert all(isinstance(s, PnLScenario) for s in result.scenarios)

        # Scenarios should include key price points
        prices = [s.price for s in result.scenarios]
        # Should have at least short strike and long strike nearby
        assert any(abs(p - 175.0) < 1 for p in prices)  # Short strike
        assert any(abs(p - 170.0) < 1 for p in prices)  # Long strike


# =============================================================================
# PROFIT/LOSS CALCULATION TESTS
# =============================================================================


class TestProfitLossCalculations:
    """Tests for profit/loss calculations."""

    def test_max_profit_formula(self, default_analyzer):
        """Max profit = credit * 100 * contracts."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.25,
            dte=30,
            contracts=3,
        )
        result = default_analyzer.analyze(params)

        # $1.25 * 100 * 3 = $375
        assert result.max_profit == 375.0

    def test_max_loss_formula(self, default_analyzer):
        """Max loss = (width - credit) * 100 * contracts."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.25,
            dte=30,
            contracts=3,
        )
        result = default_analyzer.analyze(params)

        # ($5.00 - $1.25) * 100 * 3 = $1125
        assert result.max_loss == 1125.0

    def test_break_even_formula(self, default_analyzer):
        """Break even = short strike - credit."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.75,
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # $95.00 - $1.75 = $93.25
        assert result.break_even == 93.25

    def test_risk_reward_ratio(self, default_analyzer):
        """Risk/reward ratio = max_profit / max_loss."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # Max profit = $100, Max loss = $400
        # R/R = 100/400 = 0.25
        assert abs(result.risk_reward_ratio - 0.25) < 0.01

    def test_credit_to_width_ratio(self, default_analyzer):
        """Credit to width ratio as percentage."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # $1.50 / $5.00 = 30%
        assert result.credit_to_width_ratio == 30.0


# =============================================================================
# DISTANCE CALCULATION TESTS
# =============================================================================


class TestDistanceCalculations:
    """Tests for distance calculations."""

    def test_distance_to_short_strike(self, default_analyzer):
        """Distance to short strike as percentage of current price."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=1.00,
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # (100 - 90) / 100 * 100 = 10%
        assert abs(result.distance_to_short_strike - 10.0) < 0.1

    def test_distance_to_break_even(self, default_analyzer):
        """Distance to break even as percentage of current price."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=2.00,
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # BE = 90 - 2 = 88
        # Distance = (100 - 88) / 100 * 100 = 12%
        assert abs(result.distance_to_break_even - 12.0) < 0.1

    def test_buffer_to_loss_equals_distance_to_break_even(self, default_analyzer, sample_params):
        """Buffer to loss should equal distance to break even."""
        result = default_analyzer.analyze(sample_params)
        assert result.buffer_to_loss == result.distance_to_break_even


# =============================================================================
# PNL AT PRICE TESTS
# =============================================================================


class TestPnLAtPrice:
    """Tests for calculate_pnl_at_price method."""

    @pytest.fixture
    def params(self):
        return BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=2,
        )

    def test_pnl_above_short_strike(self, default_analyzer, params):
        """Price above short strike = max profit."""
        pnl_per, pnl_total, status = default_analyzer.calculate_pnl_at_price(params, 100.0)

        # $1.50 * 100 = $150 per contract
        assert pnl_per == 150.0
        # $150 * 2 contracts = $300
        assert pnl_total == 300.0
        assert status == "max_profit"

    def test_pnl_at_short_strike(self, default_analyzer, params):
        """Price at short strike = max profit."""
        pnl_per, pnl_total, status = default_analyzer.calculate_pnl_at_price(params, 95.0)

        assert pnl_per == 150.0
        assert pnl_total == 300.0
        assert status == "max_profit"

    def test_pnl_below_long_strike(self, default_analyzer, params):
        """Price below long strike = max loss."""
        pnl_per, pnl_total, status = default_analyzer.calculate_pnl_at_price(params, 85.0)

        # Max loss = (5 - 1.5) * 100 = $350 per contract
        assert pnl_per == -350.0
        # $350 * 2 = $700
        assert pnl_total == -700.0
        assert status == "max_loss"

    def test_pnl_at_long_strike(self, default_analyzer, params):
        """Price at long strike = max loss."""
        pnl_per, pnl_total, status = default_analyzer.calculate_pnl_at_price(params, 90.0)

        assert pnl_per == -350.0
        assert status == "max_loss"

    def test_pnl_at_break_even(self, default_analyzer, params):
        """Price at break even = approximately 0."""
        break_even = 93.50  # 95 - 1.5
        pnl_per, pnl_total, status = default_analyzer.calculate_pnl_at_price(params, break_even)

        assert abs(pnl_per) < 1.0  # Essentially 0
        assert status in ["profit", "loss"]  # Could be either due to rounding

    def test_pnl_between_strikes_profit_zone(self, default_analyzer, params):
        """Price between strikes in profit zone."""
        # At 94, intrinsic = 95 - 94 = 1
        # P&L = (1.50 - 1.00) * 100 = $50
        pnl_per, pnl_total, status = default_analyzer.calculate_pnl_at_price(params, 94.0)

        assert pnl_per == 50.0
        assert pnl_total == 100.0  # 2 contracts
        assert status == "profit"

    def test_pnl_between_strikes_loss_zone(self, default_analyzer, params):
        """Price between strikes in loss zone."""
        # At 92, intrinsic = 95 - 92 = 3
        # P&L = (1.50 - 3.00) * 100 = -$150
        pnl_per, pnl_total, status = default_analyzer.calculate_pnl_at_price(params, 92.0)

        assert pnl_per == -150.0
        assert pnl_total == -300.0  # 2 contracts
        assert status == "loss"


# =============================================================================
# EXIT PRICE CALCULATION TESTS
# =============================================================================


class TestExitPriceCalculation:
    """Tests for calculate_exit_price method."""

    @pytest.fixture
    def params(self):
        return BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=2.00,
            dte=45,
            contracts=1,
        )

    def test_exit_50_percent_profit(self, default_analyzer, params):
        """Exit price for 50% profit target."""
        exit_price = default_analyzer.calculate_exit_price(params, 50)

        # 50% profit = keep $1.00, exit at $1.00
        assert exit_price == 1.00

    def test_exit_75_percent_profit(self, default_analyzer, params):
        """Exit price for 75% profit target."""
        exit_price = default_analyzer.calculate_exit_price(params, 75)

        # 75% profit = keep $1.50, exit at $0.50
        assert exit_price == 0.50

    def test_exit_100_percent_profit(self, default_analyzer, params):
        """Exit price for 100% profit (full credit kept)."""
        exit_price = default_analyzer.calculate_exit_price(params, 100)

        # 100% profit = keep all, exit at $0
        assert exit_price == 0.0

    def test_exit_0_percent_profit(self, default_analyzer, params):
        """Exit price for 0% profit (exit at original credit)."""
        exit_price = default_analyzer.calculate_exit_price(params, 0)

        # 0% profit = exit at original credit
        assert exit_price == 2.00

    def test_exit_price_cannot_be_negative(self, default_analyzer, params):
        """Exit price should never be negative."""
        exit_price = default_analyzer.calculate_exit_price(params, 150)

        # Even with >100% target, price should be 0
        assert exit_price == 0.0


# =============================================================================
# RISK LEVEL ASSESSMENT TESTS
# =============================================================================


class TestRiskLevelAssessment:
    """Tests for risk level assessment."""

    def test_low_risk_conservative_spread(self, default_analyzer):
        """Conservative spread should be LOW risk."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=85.0,  # 15% OTM
            long_strike=80.0,
            net_credit=0.75,  # 15% of width
            dte=60,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.risk_level == SpreadRiskLevel.LOW

    def test_moderate_risk_spread(self, default_analyzer):
        """Moderately aggressive spread should be MODERATE risk."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=92.0,  # 8% OTM
            long_strike=87.0,
            net_credit=1.25,  # 25% of width
            dte=45,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.risk_level in [SpreadRiskLevel.LOW, SpreadRiskLevel.MODERATE]

    def test_high_risk_aggressive_spread(self, default_analyzer):
        """Aggressive spread with short DTE should be HIGH risk."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=97.0,  # Only 3% OTM
            long_strike=92.0,
            net_credit=1.75,  # 35% of width
            dte=14,  # Short DTE
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.risk_level in [SpreadRiskLevel.HIGH, SpreadRiskLevel.VERY_HIGH]

    def test_very_high_risk_extreme_spread(self, default_analyzer):
        """Very aggressive spread should be VERY_HIGH risk."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=98.0,  # Only 2% OTM
            long_strike=93.0,
            net_credit=2.25,  # 45% of width
            dte=7,  # Very short DTE
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.risk_level == SpreadRiskLevel.VERY_HIGH


# =============================================================================
# PROBABILITY ESTIMATION TESTS
# =============================================================================


class TestProbabilityEstimation:
    """Tests for probability estimation methods."""

    def test_probability_with_black_scholes_available(self, default_analyzer, params_with_iv_only):
        """Probability should use Black-Scholes when IV is available."""
        result = default_analyzer.analyze(params_with_iv_only)

        # Probabilities should be in valid range
        assert 0 <= result.prob_profit <= 100
        assert 0 <= result.prob_max_profit <= 100

        # Prob profit should be >= prob max profit
        assert result.prob_profit >= result.prob_max_profit

    def test_probability_with_delta_provided(self, default_analyzer, params_with_greeks):
        """Probability should use Delta when provided and Black-Scholes unavailable."""
        # Mock Black-Scholes as unavailable to test delta fallback
        with patch("src.options.spread_analyzer._BLACK_SCHOLES_AVAILABLE", False):
            result = default_analyzer.analyze(params_with_greeks)

            # Should still calculate probabilities
            assert result.prob_profit > 0
            assert result.prob_max_profit > 0

    def test_probability_heuristic_fallback(self, default_analyzer):
        """Probability should use heuristic when no Greeks available."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,  # 10% OTM
            long_strike=85.0,
            net_credit=1.00,
            dte=30,
            contracts=1,
        )

        with patch("src.options.spread_analyzer._BLACK_SCHOLES_AVAILABLE", False):
            result = default_analyzer.analyze(params)

            # Heuristic: 10% OTM should give reasonable probability
            assert 60 < result.prob_max_profit < 90

    def test_prob_profit_greater_than_prob_max_profit(self, default_analyzer, sample_params):
        """Prob of any profit should be >= prob of max profit."""
        result = default_analyzer.analyze(sample_params)

        assert result.prob_profit >= result.prob_max_profit

    def test_expected_value_calculation(self, default_analyzer, sample_params):
        """Expected value should be calculated from probabilities."""
        result = default_analyzer.analyze(sample_params)

        # EV = P(profit) * max_profit - P(loss) * avg_loss
        # This is a simplified formula, just check it's reasonable
        assert isinstance(result.expected_value, (int, float))


# =============================================================================
# GREEKS CALCULATION TESTS
# =============================================================================


class TestGreeksCalculation:
    """Tests for Greeks calculation."""

    def test_greeks_via_black_scholes(self, default_analyzer, params_with_iv_only):
        """Greeks should be calculated via Black-Scholes when IV available."""
        result = default_analyzer.analyze(params_with_iv_only)

        # All Greeks should be populated
        assert result.net_delta is not None
        assert result.net_theta is not None
        assert result.theta_per_day is not None

        # Bull put spread has positive delta (bullish)
        assert result.net_delta > 0

        # Credit spread has positive theta per day
        assert result.theta_per_day > 0

    def test_greeks_from_provided_values(self, default_analyzer, params_with_greeks):
        """Greeks should use provided values when Black-Scholes unavailable."""
        with patch("src.options.spread_analyzer._BLACK_SCHOLES_AVAILABLE", False):
            result = default_analyzer.analyze(params_with_greeks)

            assert result.net_delta is not None
            # Net delta = -(-0.25) + (-0.12) = 0.25 - 0.12 = 0.13
            assert abs(result.net_delta - 0.13) < 0.02

    def test_theta_per_day_scaled_by_contracts(self, default_analyzer):
        """Theta per day should be scaled by number of contracts."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=5,
            short_iv=0.25,
        )
        result = default_analyzer.analyze(params)

        if result.theta_per_day and result.net_theta:
            # theta_per_day = net_theta * contracts
            assert abs(result.theta_per_day - result.net_theta * 5) < 0.01

    def test_greeks_none_without_data(self, default_analyzer):
        """Greeks should be None when no data available."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=1,
            # No delta, theta, or IV
        )

        with patch("src.options.spread_analyzer._BLACK_SCHOLES_AVAILABLE", False):
            result = default_analyzer.analyze(params)

            assert result.net_delta is None
            assert result.net_theta is None


# =============================================================================
# SCENARIO GENERATION TESTS
# =============================================================================


class TestScenarioGeneration:
    """Tests for P&L scenario generation."""

    def test_scenarios_generated(self, default_analyzer, sample_params):
        """Scenarios should be generated."""
        result = default_analyzer.analyze(sample_params)

        assert len(result.scenarios) > 0

    def test_scenarios_are_pnl_scenario_objects(self, default_analyzer, sample_params):
        """All scenarios should be PnLScenario instances."""
        result = default_analyzer.analyze(sample_params)

        assert all(isinstance(s, PnLScenario) for s in result.scenarios)

    def test_scenarios_include_key_prices(self, default_analyzer, sample_params):
        """Scenarios should include short strike and long strike."""
        result = default_analyzer.analyze(sample_params)

        prices = [s.price for s in result.scenarios]

        # Should have short strike (175) and long strike (170)
        assert any(abs(p - 175.0) < 1 for p in prices)
        assert any(abs(p - 170.0) < 1 for p in prices)

    def test_scenarios_sorted_descending_by_price(self, default_analyzer, sample_params):
        """Scenarios should be sorted by price in descending order."""
        result = default_analyzer.analyze(sample_params)

        prices = [s.price for s in result.scenarios]
        assert prices == sorted(prices, reverse=True)

    def test_scenario_has_required_fields(self, default_analyzer, sample_params):
        """Each scenario should have all required fields."""
        result = default_analyzer.analyze(sample_params)

        for scenario in result.scenarios:
            assert hasattr(scenario, 'price')
            assert hasattr(scenario, 'pnl_per_contract')
            assert hasattr(scenario, 'pnl_total')
            assert hasattr(scenario, 'pnl_percent')
            assert hasattr(scenario, 'status')
            assert scenario.status in ["max_profit", "profit", "loss", "max_loss"]


# =============================================================================
# WARNINGS AND RECOMMENDATIONS TESTS
# =============================================================================


class TestWarningsAndRecommendations:
    """Tests for warnings and recommendations generation."""

    def test_warning_for_low_buffer(self, default_analyzer):
        """Warning should be generated for low buffer."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=97.0,  # Only 3% OTM
            long_strike=92.0,
            net_credit=1.50,
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # Should have warning about low buffer
        assert any("Puffer" in w or "Buffer" in w for w in result.warnings)

    def test_warning_for_low_credit_ratio(self, default_analyzer):
        """Warning should be generated for low credit ratio."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=0.30,  # Only 6% of width
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # Should have warning about low credit
        assert any("Credit" in w for w in result.warnings)

    def test_warning_for_short_dte(self, default_analyzer):
        """Warning should be generated for short DTE."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=1.00,
            dte=10,  # Very short
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # Should have warning about short DTE/gamma
        assert any("Laufzeit" in w or "Gamma" in w for w in result.warnings)

    def test_warning_for_very_high_risk(self, default_analyzer):
        """Warning should be generated for very high risk spreads."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=98.0,  # 2% OTM
            long_strike=93.0,
            net_credit=2.50,  # 50% of width
            dte=7,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        if result.risk_level == SpreadRiskLevel.VERY_HIGH:
            assert any("Risiko" in w or "Position" in w for w in result.warnings)

    def test_recommendations_include_profit_target(self, default_analyzer, sample_params):
        """Recommendations should include profit target."""
        result = default_analyzer.analyze(sample_params)

        assert any("Profit" in r or "Target" in r for r in result.recommendations)

    def test_recommendations_include_exit_price(self, default_analyzer, sample_params):
        """Recommendations should include exit price."""
        result = default_analyzer.analyze(sample_params)

        assert any("Exit" in r for r in result.recommendations)

    def test_recommendations_include_stop_loss(self, default_analyzer, sample_params):
        """Recommendations should include stop loss."""
        result = default_analyzer.analyze(sample_params)

        assert any("Stop" in r for r in result.recommendations)

    def test_conservative_target_for_long_dte(self, default_analyzer):
        """Should recommend conservative target for long DTE."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=1.00,
            dte=60,  # > 45 days
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # Should recommend 50% (conservative)
        assert any("50%" in r for r in result.recommendations)

    def test_standard_target_for_shorter_dte(self, default_analyzer):
        """Should recommend standard target for shorter DTE."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=1.00,
            dte=30,  # <= 45 days
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        # Should recommend 50% (Tastytrade standard)
        assert any("50%" in r for r in result.recommendations)


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================


class TestConvenienceFunction:
    """Tests for analyze_bull_put_spread convenience function."""

    def test_basic_usage(self):
        """Basic usage should work."""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45,
        )

        assert isinstance(result, SpreadAnalysis)
        assert result.symbol == "AAPL"
        assert result.max_profit == 150.0

    def test_with_contracts(self):
        """Should accept contracts parameter."""
        result = analyze_bull_put_spread(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=3,
        )

        assert result.contracts == 3
        assert result.max_profit == 300.0  # $1 * 100 * 3

    def test_with_delta(self):
        """Should accept short_delta parameter."""
        result = analyze_bull_put_spread(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            short_delta=-0.25,
        )

        # Should use delta for probability estimation
        assert result.prob_max_profit > 0


# =============================================================================
# OUTPUT FORMAT TESTS
# =============================================================================


class TestOutputFormats:
    """Tests for output formatting methods."""

    def test_summary_returns_string(self):
        """summary() should return a string."""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45,
        )

        summary = result.summary()
        assert isinstance(summary, str)
        assert len(summary) > 100

    def test_summary_contains_symbol(self):
        """Summary should contain the symbol."""
        result = analyze_bull_put_spread(
            symbol="NVDA",
            current_price=500.0,
            short_strike=480.0,
            long_strike=470.0,
            net_credit=3.00,
            dte=30,
        )

        summary = result.summary()
        assert "NVDA" in summary

    def test_summary_contains_key_metrics(self):
        """Summary should contain key metrics."""
        result = analyze_bull_put_spread(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
        )

        summary = result.summary()
        assert "95" in summary  # Short strike
        assert "90" in summary  # Long strike
        assert "Profit" in summary
        assert "Loss" in summary

    def test_to_dict_returns_dict(self):
        """to_dict() should return a dictionary."""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45,
        )

        data = result.to_dict()
        assert isinstance(data, dict)

    def test_to_dict_has_all_fields(self):
        """to_dict() should include all required fields."""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45,
        )

        data = result.to_dict()

        required_fields = [
            "symbol", "current_price", "short_strike", "long_strike",
            "spread_width", "net_credit", "contracts", "dte",
            "max_profit", "max_loss", "break_even", "risk_reward_ratio",
            "distance_to_short_strike", "distance_to_break_even", "buffer_to_loss",
            "prob_profit", "prob_max_profit", "expected_value",
            "risk_level", "credit_to_width_ratio",
            "scenarios", "warnings", "recommendations",
        ]

        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_to_dict_scenarios_serializable(self):
        """Scenarios in to_dict() should be serializable dicts."""
        result = analyze_bull_put_spread(
            symbol="AAPL",
            current_price=180.0,
            short_strike=175.0,
            long_strike=170.0,
            net_credit=1.50,
            dte=45,
        )

        data = result.to_dict()

        assert isinstance(data["scenarios"], list)
        for scenario in data["scenarios"]:
            assert isinstance(scenario, dict)
            assert "price" in scenario
            assert "pnl_per_contract" in scenario
            assert "pnl_total" in scenario
            assert "status" in scenario


# =============================================================================
# EDGE CASES TESTS
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_wide_spread(self, default_analyzer):
        """Very wide spread should work correctly."""
        params = BullPutSpreadParams(
            symbol="AMZN",
            current_price=200.0,
            short_strike=150.0,
            long_strike=100.0,  # $50 spread
            net_credit=15.00,
            dte=60,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.spread_width == 50.0
        assert result.max_profit == 1500.0  # $15 * 100
        assert result.max_loss == 3500.0    # $35 * 100

    def test_very_narrow_spread(self, default_analyzer):
        """Very narrow $1 spread should work correctly."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=50.0,
            short_strike=45.0,
            long_strike=44.0,  # $1 spread
            net_credit=0.25,
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.spread_width == 1.0
        assert result.max_profit == 25.0
        assert result.max_loss == 75.0

    def test_many_contracts(self, default_analyzer):
        """Many contracts should scale correctly."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.00,
            dte=30,
            contracts=100,
        )
        result = default_analyzer.analyze(params)

        assert result.contracts == 100
        assert result.max_profit == 10000.0  # $1 * 100 * 100
        assert result.max_loss == 40000.0    # $4 * 100 * 100

    def test_long_dte(self, default_analyzer):
        """Long DTE (LEAPS) should work correctly."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=3.00,
            dte=365,  # 1 year
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.dte == 365
        assert result.prob_profit > 0

    def test_short_dte(self, default_analyzer):
        """Very short DTE should work correctly."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=0.50,
            dte=1,  # 1 day
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.dte == 1

    def test_high_credit_ratio(self, default_analyzer):
        """High credit ratio (aggressive) should work."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=99.0,  # Very close to current
            long_strike=94.0,
            net_credit=2.00,  # 40% of width
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.credit_to_width_ratio == 40.0

    def test_fractional_strikes(self, default_analyzer):
        """Fractional strike prices should work."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=55.50,
            short_strike=52.50,
            long_strike=50.00,
            net_credit=0.65,
            dte=30,
            contracts=1,
        )
        result = default_analyzer.analyze(params)

        assert result.spread_width == 2.50
        assert result.break_even == 51.85  # 52.50 - 0.65


# =============================================================================
# CUSTOM CONFIG TESTS
# =============================================================================


class TestCustomConfiguration:
    """Tests for custom configuration options."""

    def test_custom_risk_thresholds_affect_risk_level(self):
        """Custom risk thresholds should affect risk level calculation."""
        # Default thresholds
        default_analyzer = SpreadAnalyzer()

        # Stricter thresholds
        strict_analyzer = SpreadAnalyzer(config={
            "low_risk_max_credit_pct": 10,
            "moderate_risk_max_credit_pct": 15,
            "high_risk_max_credit_pct": 20,
        })

        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=0.80,  # 16% of width
            dte=45,
            contracts=1,
        )

        default_result = default_analyzer.analyze(params)
        strict_result = strict_analyzer.analyze(params)

        # With default config (16% < 20%), should be LOW
        assert default_result.risk_level == SpreadRiskLevel.LOW

        # With strict config (16% > 15%), should be MODERATE or higher
        assert strict_result.risk_level in [SpreadRiskLevel.MODERATE, SpreadRiskLevel.HIGH]

    def test_custom_profit_targets_in_recommendations(self):
        """Custom profit targets should appear in recommendations."""
        analyzer = SpreadAnalyzer(config={
            "profit_target_conservative": 45,
            "profit_target_standard": 60,
        })

        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,
            long_strike=85.0,
            net_credit=2.00,
            dte=30,  # Uses standard target
            contracts=1,
        )
        result = analyzer.analyze(params)

        # Should have 60% in recommendations
        assert any("60%" in r for r in result.recommendations)

    def test_custom_warning_thresholds(self):
        """Custom warning thresholds should affect warnings."""
        # Very lenient buffer threshold
        lenient_analyzer = SpreadAnalyzer(config={"min_buffer_pct": 2.0})

        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=97.0,  # 3% buffer
            long_strike=92.0,
            net_credit=1.50,
            dte=30,
            contracts=1,
        )

        result = lenient_analyzer.analyze(params)

        # With 2% threshold and 3% buffer, should NOT warn about buffer
        assert not any("Puffer" in w or "Buffer" in w for w in result.warnings)


# =============================================================================
# INTEGRATION WITH BLACK-SCHOLES TESTS
# =============================================================================


class TestBlackScholesIntegration:
    """Tests for Black-Scholes integration."""

    def test_greeks_calculated_when_black_scholes_available(self, default_analyzer):
        """Greeks should be calculated when Black-Scholes is available."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            net_credit=1.50,
            dte=30,
            contracts=1,
            short_iv=0.25,
        )

        result = default_analyzer.analyze(params)

        # With Black-Scholes available and IV provided
        assert result.net_delta is not None
        assert result.net_theta is not None
        assert result.theta_per_day is not None

    def test_probabilities_via_black_scholes(self, default_analyzer):
        """Probabilities should be calculated via Black-Scholes when available."""
        params = BullPutSpreadParams(
            symbol="TEST",
            current_price=100.0,
            short_strike=90.0,  # 10% OTM
            long_strike=85.0,
            net_credit=1.00,
            dte=45,
            contracts=1,
            short_iv=0.25,
        )

        result = default_analyzer.analyze(params)

        # OTM spread should have high probability of max profit
        assert result.prob_max_profit > 70

        # Prob profit should be higher (includes buffer from credit)
        assert result.prob_profit > result.prob_max_profit


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
