# Tests for Black-Scholes Pricing
# ================================
"""
Tests for Black-Scholes options pricing functions.
"""

import pytest
import math
import numpy as np

from src.pricing.black_scholes import (
    _norm_cdf_np,
    _norm_pdf_np,
    _norm_cdf,
    _norm_pdf,
    _calculate_d1_d2_np,
    _calculate_d1_d2,
    black_scholes_call_np,
    black_scholes_put_np,
)


# =============================================================================
# NORM CDF TESTS
# =============================================================================

class TestNormCDF:
    """Tests for normal cumulative distribution function."""

    def test_cdf_at_zero(self):
        """Test CDF at x=0 equals 0.5."""
        result = _norm_cdf_np(0.0)
        assert abs(result - 0.5) < 0.0001

    def test_cdf_large_positive(self):
        """Test CDF at large positive x approaches 1."""
        result = _norm_cdf_np(5.0)
        assert result > 0.999

    def test_cdf_large_negative(self):
        """Test CDF at large negative x approaches 0."""
        result = _norm_cdf_np(-5.0)
        assert result < 0.001

    def test_cdf_symmetric(self):
        """Test CDF is symmetric around 0.5."""
        result_pos = _norm_cdf_np(1.0)
        result_neg = _norm_cdf_np(-1.0)
        assert abs((result_pos + result_neg) - 1.0) < 0.0001

    def test_cdf_known_values(self):
        """Test CDF against known values."""
        # N(1) ≈ 0.8413
        result = _norm_cdf_np(1.0)
        assert abs(result - 0.8413) < 0.01

        # N(-1) ≈ 0.1587
        result = _norm_cdf_np(-1.0)
        assert abs(result - 0.1587) < 0.01

    def test_cdf_array_input(self):
        """Test CDF with numpy array input."""
        x = np.array([-1.0, 0.0, 1.0])
        result = _norm_cdf_np(x)

        assert isinstance(result, np.ndarray)
        assert len(result) == 3
        assert abs(result[1] - 0.5) < 0.0001

    def test_cdf_scalar_wrapper(self):
        """Test scalar CDF wrapper."""
        result = _norm_cdf(0.0)
        assert isinstance(result, float)
        assert abs(result - 0.5) < 0.0001


# =============================================================================
# NORM PDF TESTS
# =============================================================================

class TestNormPDF:
    """Tests for normal probability density function."""

    def test_pdf_at_zero(self):
        """Test PDF at x=0 equals 1/sqrt(2*pi)."""
        expected = 1.0 / math.sqrt(2 * math.pi)
        result = _norm_pdf_np(0.0)
        assert abs(result - expected) < 0.0001

    def test_pdf_large_x(self):
        """Test PDF at large x approaches 0."""
        result = _norm_pdf_np(5.0)
        assert result < 0.0001

    def test_pdf_symmetric(self):
        """Test PDF is symmetric."""
        result_pos = _norm_pdf_np(1.0)
        result_neg = _norm_pdf_np(-1.0)
        assert abs(result_pos - result_neg) < 0.0001

    def test_pdf_always_positive(self):
        """Test PDF is always positive."""
        for x in [-5, -1, 0, 1, 5]:
            result = _norm_pdf_np(x)
            assert result > 0

    def test_pdf_array_input(self):
        """Test PDF with numpy array input."""
        x = np.array([-1.0, 0.0, 1.0])
        result = _norm_pdf_np(x)

        assert isinstance(result, np.ndarray)
        assert len(result) == 3

    def test_pdf_scalar_wrapper(self):
        """Test scalar PDF wrapper."""
        result = _norm_pdf(0.0)
        assert isinstance(result, float)


# =============================================================================
# D1 D2 CALCULATION TESTS
# =============================================================================

class TestCalculateD1D2:
    """Tests for d1 and d2 calculation."""

    def test_basic_calculation(self):
        """Test basic d1, d2 calculation."""
        S = 100.0  # Stock price
        K = 100.0  # Strike (ATM)
        T = 1.0    # 1 year
        r = 0.05   # 5% rate
        sigma = 0.20  # 20% volatility

        d1, d2 = _calculate_d1_d2_np(S, K, T, r, sigma)

        # For ATM option: d1 = (r + 0.5*sigma^2) * T / (sigma * sqrt(T))
        # d1 = (0.05 + 0.02) / 0.20 = 0.35
        assert abs(d1 - 0.35) < 0.01

        # d2 = d1 - sigma * sqrt(T) = 0.35 - 0.20 = 0.15
        assert abs(d2 - 0.15) < 0.01

    def test_zero_time_returns_zero(self):
        """Test T=0 returns d1=d2=0."""
        d1, d2 = _calculate_d1_d2_np(100.0, 100.0, 0.0, 0.05, 0.20)

        assert d1 == 0.0
        assert d2 == 0.0

    def test_zero_volatility_returns_zero(self):
        """Test sigma=0 returns d1=d2=0."""
        d1, d2 = _calculate_d1_d2_np(100.0, 100.0, 1.0, 0.05, 0.0)

        assert d1 == 0.0
        assert d2 == 0.0

    def test_itm_call(self):
        """Test d1, d2 for in-the-money call (S > K)."""
        S = 110.0
        K = 100.0
        T = 0.5
        r = 0.05
        sigma = 0.25

        d1, d2 = _calculate_d1_d2_np(S, K, T, r, sigma)

        # S > K should give positive d1
        assert d1 > 0

    def test_otm_call(self):
        """Test d1, d2 for out-of-money call (S < K)."""
        S = 90.0
        K = 100.0
        T = 0.5
        r = 0.05
        sigma = 0.25

        d1, d2 = _calculate_d1_d2_np(S, K, T, r, sigma)

        # S < K should give negative d1 (depending on time value)
        # But for short time and low rate, d1 can still be negative
        assert isinstance(d1, float)

    def test_array_inputs(self):
        """Test with array inputs."""
        S = np.array([100.0, 110.0])
        K = np.array([100.0, 100.0])
        T = 0.5
        r = 0.05
        sigma = 0.20

        d1, d2 = _calculate_d1_d2_np(S, K, T, r, sigma)

        assert len(d1) == 2
        assert len(d2) == 2

    def test_scalar_wrapper(self):
        """Test scalar version."""
        d1, d2 = _calculate_d1_d2(100.0, 100.0, 1.0, 0.05, 0.20)

        assert isinstance(d1, float)
        assert isinstance(d2, float)


# =============================================================================
# BLACK-SCHOLES CALL TESTS
# =============================================================================

class TestBlackScholesCall:
    """Tests for Black-Scholes call option pricing."""

    def test_atm_call_price(self):
        """Test ATM call price is reasonable."""
        S = 100.0
        K = 100.0
        T = 0.25  # 3 months
        r = 0.05
        sigma = 0.20

        price = black_scholes_call_np(S, K, T, r, sigma)

        # ATM call should be roughly S * N(d1) - K * e^(-rT) * N(d2)
        # For these params, call price should be around 4-5
        assert 3.0 < price < 7.0

    def test_deep_itm_call(self):
        """Test deep ITM call approaches intrinsic value."""
        S = 150.0
        K = 100.0
        T = 0.5
        r = 0.05
        sigma = 0.20

        price = black_scholes_call_np(S, K, T, r, sigma)

        # Deep ITM: price ≈ S - K * e^(-rT) > intrinsic
        intrinsic = S - K
        assert price > intrinsic - 1  # Allow for discounting

    def test_deep_otm_call(self):
        """Test deep OTM call approaches zero."""
        S = 50.0
        K = 100.0
        T = 0.25
        r = 0.05
        sigma = 0.20

        price = black_scholes_call_np(S, K, T, r, sigma)

        # Deep OTM: price should be very small
        assert price < 0.5

    def test_call_price_positive(self):
        """Test call price is always positive."""
        price = black_scholes_call_np(100.0, 100.0, 0.5, 0.05, 0.30)
        assert price > 0

    def test_higher_vol_higher_price(self):
        """Test higher volatility means higher call price."""
        S, K, T, r = 100.0, 100.0, 0.5, 0.05

        price_low_vol = black_scholes_call_np(S, K, T, r, 0.15)
        price_high_vol = black_scholes_call_np(S, K, T, r, 0.35)

        assert price_high_vol > price_low_vol

    def test_longer_time_higher_price(self):
        """Test longer time means higher call price."""
        S, K, r, sigma = 100.0, 100.0, 0.05, 0.25

        price_short = black_scholes_call_np(S, K, 0.25, r, sigma)
        price_long = black_scholes_call_np(S, K, 1.0, r, sigma)

        assert price_long > price_short


# =============================================================================
# BLACK-SCHOLES PUT TESTS
# =============================================================================

class TestBlackScholesPut:
    """Tests for Black-Scholes put option pricing."""

    def test_atm_put_price(self):
        """Test ATM put price is reasonable."""
        S = 100.0
        K = 100.0
        T = 0.25
        r = 0.05
        sigma = 0.20

        price = black_scholes_put_np(S, K, T, r, sigma)

        # ATM put should be reasonable
        assert 2.0 < price < 6.0

    def test_deep_itm_put(self):
        """Test deep ITM put approaches intrinsic value."""
        S = 50.0
        K = 100.0
        T = 0.5
        r = 0.05
        sigma = 0.20

        price = black_scholes_put_np(S, K, T, r, sigma)

        # Deep ITM put: price ≈ K * e^(-rT) - S
        intrinsic = K - S
        assert price > intrinsic - 5  # Allow for time value

    def test_deep_otm_put(self):
        """Test deep OTM put approaches zero."""
        S = 150.0
        K = 100.0
        T = 0.25
        r = 0.05
        sigma = 0.20

        price = black_scholes_put_np(S, K, T, r, sigma)

        # Deep OTM put: price should be very small
        assert price < 0.5

    def test_put_price_positive(self):
        """Test put price is always positive."""
        price = black_scholes_put_np(100.0, 100.0, 0.5, 0.05, 0.30)
        assert price > 0

    def test_higher_vol_higher_price(self):
        """Test higher volatility means higher put price."""
        S, K, T, r = 100.0, 100.0, 0.5, 0.05

        price_low_vol = black_scholes_put_np(S, K, T, r, 0.15)
        price_high_vol = black_scholes_put_np(S, K, T, r, 0.35)

        assert price_high_vol > price_low_vol


# =============================================================================
# PUT-CALL PARITY TESTS
# =============================================================================

class TestPutCallParity:
    """Tests for put-call parity relationship."""

    def test_put_call_parity(self):
        """Test C - P = S - K * e^(-rT)."""
        S = 100.0
        K = 100.0
        T = 0.5
        r = 0.05
        sigma = 0.25

        call_price = black_scholes_call_np(S, K, T, r, sigma)
        put_price = black_scholes_put_np(S, K, T, r, sigma)

        # C - P = S - K * e^(-rT)
        expected_diff = S - K * math.exp(-r * T)
        actual_diff = call_price - put_price

        assert abs(actual_diff - expected_diff) < 0.01

    def test_put_call_parity_itm(self):
        """Test put-call parity for ITM options."""
        S = 110.0
        K = 100.0
        T = 0.25
        r = 0.05
        sigma = 0.30

        call_price = black_scholes_call_np(S, K, T, r, sigma)
        put_price = black_scholes_put_np(S, K, T, r, sigma)

        expected_diff = S - K * math.exp(-r * T)
        actual_diff = call_price - put_price

        assert abs(actual_diff - expected_diff) < 0.01

    def test_put_call_parity_otm(self):
        """Test put-call parity for OTM options."""
        S = 90.0
        K = 100.0
        T = 0.25
        r = 0.05
        sigma = 0.30

        call_price = black_scholes_call_np(S, K, T, r, sigma)
        put_price = black_scholes_put_np(S, K, T, r, sigma)

        expected_diff = S - K * math.exp(-r * T)
        actual_diff = call_price - put_price

        assert abs(actual_diff - expected_diff) < 0.01


# =============================================================================
# ARRAY VECTORIZATION TESTS
# =============================================================================

class TestVectorization:
    """Tests for numpy array vectorization."""

    def test_call_with_multiple_strikes(self):
        """Test call pricing with multiple strikes."""
        S = 100.0
        K = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
        T = 0.5
        r = 0.05
        sigma = 0.25

        prices = black_scholes_call_np(S, K, T, r, sigma)

        assert len(prices) == 5
        # Lower strikes should have higher call prices
        assert all(prices[i] > prices[i+1] for i in range(len(prices)-1))

    def test_put_with_multiple_strikes(self):
        """Test put pricing with multiple strikes."""
        S = 100.0
        K = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
        T = 0.5
        r = 0.05
        sigma = 0.25

        prices = black_scholes_put_np(S, K, T, r, sigma)

        assert len(prices) == 5
        # Higher strikes should have higher put prices
        assert all(prices[i] < prices[i+1] for i in range(len(prices)-1))

    def test_call_with_multiple_spots(self):
        """Test call pricing with multiple spot prices."""
        S = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
        K = 100.0
        T = 0.5
        r = 0.05
        sigma = 0.25

        prices = black_scholes_call_np(S, K, T, r, sigma)

        assert len(prices) == 5
        # Higher spots should have higher call prices
        assert all(prices[i] < prices[i+1] for i in range(len(prices)-1))


# =============================================================================
# GREEKS TESTS
# =============================================================================

from src.pricing.black_scholes import (
    Greeks,
    black_scholes_greeks,
    black_scholes_call,
    black_scholes_put,
    black_scholes_price,
    implied_volatility,
    find_strike_for_delta,
    PricingResult,
    OptionPricer,
    get_symbol_iv_multiplier,
    estimate_iv_calibrated,
    quick_put_price,
    quick_spread_credit,
    batch_spread_credit,
    batch_spread_pnl,
    batch_historical_volatility,
    batch_estimate_iv,
)


class TestGreeks:
    """Tests for Greeks calculation."""

    def test_greeks_put_delta_negative(self):
        """Test put delta is negative."""
        greeks = black_scholes_greeks(100.0, 100.0, 0.5, 0.05, 0.25, "P")
        assert greeks.delta < 0
        assert -1.0 <= greeks.delta <= 0.0

    def test_greeks_call_delta_positive(self):
        """Test call delta is positive."""
        greeks = black_scholes_greeks(100.0, 100.0, 0.5, 0.05, 0.25, "C")
        assert greeks.delta > 0
        assert 0.0 <= greeks.delta <= 1.0

    def test_greeks_gamma_positive(self):
        """Test gamma is always positive."""
        greeks_call = black_scholes_greeks(100.0, 100.0, 0.5, 0.05, 0.25, "C")
        greeks_put = black_scholes_greeks(100.0, 100.0, 0.5, 0.05, 0.25, "P")

        assert greeks_call.gamma > 0
        assert greeks_put.gamma > 0
        # Gamma should be same for call and put
        assert abs(greeks_call.gamma - greeks_put.gamma) < 0.0001

    def test_greeks_vega_positive(self):
        """Test vega is always positive."""
        greeks = black_scholes_greeks(100.0, 100.0, 0.5, 0.05, 0.25, "P")
        assert greeks.vega > 0

    def test_greeks_at_expiration(self):
        """Test greeks at T=0."""
        # ITM put at expiration
        greeks = black_scholes_greeks(90.0, 100.0, 0.0, 0.05, 0.25, "P")
        assert greeks.delta == -1.0
        assert greeks.gamma == 0.0

        # OTM put at expiration
        greeks = black_scholes_greeks(110.0, 100.0, 0.0, 0.05, 0.25, "P")
        assert greeks.delta == 0.0

    def test_greeks_dataclass(self):
        """Test Greeks dataclass attributes."""
        greeks = black_scholes_greeks(100.0, 100.0, 0.5, 0.05, 0.25, "P")

        assert hasattr(greeks, 'delta')
        assert hasattr(greeks, 'gamma')
        assert hasattr(greeks, 'theta')
        assert hasattr(greeks, 'vega')
        assert hasattr(greeks, 'rho')


# =============================================================================
# IMPLIED VOLATILITY TESTS
# =============================================================================

class TestImpliedVolatility:
    """Tests for implied volatility calculation."""

    def test_iv_roundtrip(self):
        """Test IV calculation roundtrips with BS price."""
        S, K, T, r = 100.0, 100.0, 0.5, 0.05
        sigma_original = 0.25

        # Price the option
        price = black_scholes_put(S, K, T, r, sigma_original)

        # Calculate IV from price
        sigma_calculated = implied_volatility(price, S, K, T, r, "P")

        assert sigma_calculated is not None
        assert abs(sigma_calculated - sigma_original) < 0.01

    def test_iv_zero_price_returns_none(self):
        """Test IV returns None for zero price."""
        result = implied_volatility(0.0, 100.0, 100.0, 0.5, 0.05, "P")
        assert result is None

    def test_iv_zero_time_returns_none(self):
        """Test IV returns None for T=0."""
        result = implied_volatility(5.0, 100.0, 100.0, 0.0, 0.05, "P")
        assert result is None

    def test_iv_call_option(self):
        """Test IV calculation for call option."""
        S, K, T, r = 100.0, 100.0, 0.5, 0.05
        sigma = 0.30

        price = black_scholes_call(S, K, T, r, sigma)
        sigma_calc = implied_volatility(price, S, K, T, r, "C")

        assert sigma_calc is not None
        assert abs(sigma_calc - sigma) < 0.01


# =============================================================================
# FIND STRIKE FOR DELTA TESTS
# =============================================================================

class TestFindStrikeForDelta:
    """Tests for delta-based strike finder."""

    def test_find_strike_for_put_delta(self):
        """Test finding strike for target put delta."""
        S = 100.0
        T = 60 / 365.0
        sigma = 0.25
        target_delta = -0.20

        strike = find_strike_for_delta(target_delta, S, T, sigma)

        assert strike is not None
        assert strike < S  # OTM put

        # Verify the delta is in reasonable range (strike rounding affects accuracy)
        greeks = black_scholes_greeks(S, strike, T, 0.05, sigma, "P")
        assert abs(greeks.delta - target_delta) < 0.10  # Allow for strike rounding

    def test_find_strike_for_call_delta(self):
        """Test finding strike for target call delta."""
        S = 100.0
        T = 60 / 365.0
        sigma = 0.25
        target_delta = 0.30

        strike = find_strike_for_delta(target_delta, S, T, sigma, option_type="C")

        assert strike is not None
        assert strike > S  # OTM call

    def test_find_strike_invalid_inputs(self):
        """Test find_strike handles invalid inputs."""
        # Zero time
        result = find_strike_for_delta(-0.20, 100.0, 0.0, 0.25)
        assert result is None

        # Zero volatility
        result = find_strike_for_delta(-0.20, 100.0, 0.25, 0.0)
        assert result is None

        # Zero spot
        result = find_strike_for_delta(-0.20, 0.0, 0.25, 0.25)
        assert result is None


# =============================================================================
# OPTION PRICER CLASS TESTS
# =============================================================================

class TestOptionPricer:
    """Tests for OptionPricer class."""

    def test_pricer_init(self):
        """Test pricer initialization."""
        pricer = OptionPricer(risk_free_rate=0.05, dividend_yield=0.02)
        assert pricer.risk_free_rate == 0.05
        assert pricer.dividend_yield == 0.02

    def test_pricer_price_put(self):
        """Test put pricing."""
        pricer = OptionPricer()
        price, greeks = pricer.price_put(100.0, 95.0, 45, 0.25)

        assert price > 0
        assert greeks.delta < 0

    def test_pricer_price_call(self):
        """Test call pricing."""
        pricer = OptionPricer()
        price, greeks = pricer.price_call(100.0, 105.0, 45, 0.25)

        assert price > 0
        assert greeks.delta > 0

    def test_pricer_bull_put_spread(self):
        """Test bull put spread pricing."""
        pricer = OptionPricer()
        result = pricer.price_bull_put_spread(
            underlying_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            days_to_expiry=45,
            volatility=0.25
        )

        assert isinstance(result, PricingResult)
        assert result.net_credit > 0
        assert result.spread_width == 5.0
        assert result.max_loss == result.spread_width - result.net_credit
        assert result.breakeven == result.short_strike - result.net_credit

    def test_pricer_spread_with_skew(self):
        """Test spread pricing with volatility skew."""
        pricer = OptionPricer()
        result = pricer.price_bull_put_spread(
            underlying_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            days_to_expiry=45,
            volatility=0.25,
            short_iv=0.26,
            long_iv=0.28
        )

        assert result.net_credit > 0

    def test_pricer_estimate_iv_from_hv(self):
        """Test IV estimation from historical volatility."""
        pricer = OptionPricer()

        # Basic estimation
        iv = pricer.estimate_iv_from_hv(0.20)
        assert iv > 0.20  # IV premium

        # With high VIX
        iv_high_vix = pricer.estimate_iv_from_hv(0.20, vix=35.0)
        assert iv_high_vix > iv  # Higher in high vol environment

        # With low VIX
        iv_low_vix = pricer.estimate_iv_from_hv(0.20, vix=12.0)
        assert iv_low_vix < iv_high_vix

    def test_pricer_calculate_spread_value(self):
        """Test spread value calculation."""
        pricer = OptionPricer()

        current_value, pnl = pricer.calculate_spread_value_at_price(
            underlying_price=105.0,  # Price moved up
            short_strike=95.0,
            long_strike=90.0,
            days_to_expiry=30,
            volatility=0.22,
            initial_credit=1.50
        )

        # With price moved up, spread should be worth less (profitable)
        assert pnl > 0


# =============================================================================
# PRICING RESULT TESTS
# =============================================================================

class TestPricingResult:
    """Tests for PricingResult dataclass."""

    def test_credit_pct_property(self):
        """Test credit_pct calculation."""
        result = PricingResult(
            short_put_price=2.50,
            long_put_price=1.00,
            net_credit=1.50,
            spread_width=5.0,
            delta=0.15,
            gamma=0.02,
            theta=0.05,
            vega=0.10,
            max_profit=1.50,
            max_loss=3.50,
            breakeven=93.50,
            prob_profit=0.80,
            underlying_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            days_to_expiry=45,
            volatility=0.25
        )

        assert result.credit_pct == 30.0  # 1.50 / 5.0 * 100

    def test_risk_reward_ratio_property(self):
        """Test risk_reward_ratio calculation."""
        result = PricingResult(
            short_put_price=2.50,
            long_put_price=1.00,
            net_credit=1.50,
            spread_width=5.0,
            delta=0.15,
            gamma=0.02,
            theta=0.05,
            vega=0.10,
            max_profit=1.50,
            max_loss=3.50,
            breakeven=93.50,
            prob_profit=0.80,
            underlying_price=100.0,
            short_strike=95.0,
            long_strike=90.0,
            days_to_expiry=45,
            volatility=0.25
        )

        assert abs(result.risk_reward_ratio - (3.50 / 1.50)) < 0.01

    def test_zero_spread_width_credit_pct(self):
        """Test credit_pct with zero spread width."""
        result = PricingResult(
            short_put_price=2.50,
            long_put_price=2.50,
            net_credit=0.0,
            spread_width=0.0,
            delta=0.0,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            max_profit=0.0,
            max_loss=0.0,
            breakeven=95.0,
            prob_profit=0.5,
            underlying_price=100.0,
            short_strike=95.0,
            long_strike=95.0,
            days_to_expiry=45,
            volatility=0.25
        )

        assert result.credit_pct == 0.0


# =============================================================================
# SYMBOL IV MULTIPLIER TESTS
# =============================================================================

class TestSymbolIVMultiplier:
    """Tests for symbol-specific IV multipliers."""

    def test_individual_override(self):
        """Test individual symbol override."""
        mult = get_symbol_iv_multiplier("SPY")
        assert mult == 1.58  # From SYMBOL_OVERRIDES

    def test_index_etf_category(self):
        """Test index ETF category."""
        mult = get_symbol_iv_multiplier("DIA")
        assert mult == 1.55

    def test_sector_etf_category(self):
        """Test sector ETF category."""
        mult = get_symbol_iv_multiplier("XLK")
        assert mult == 1.12

    def test_default_multiplier(self):
        """Test unknown symbol gets default."""
        mult = get_symbol_iv_multiplier("UNKNOWN_SYMBOL")
        assert mult == 1.0

    def test_case_insensitive(self):
        """Test symbol lookup is case insensitive."""
        mult_lower = get_symbol_iv_multiplier("spy")
        mult_upper = get_symbol_iv_multiplier("SPY")
        assert mult_lower == mult_upper


# =============================================================================
# ESTIMATE IV CALIBRATED TESTS
# =============================================================================

class TestEstimateIVCalibrated:
    """Tests for calibrated IV estimation."""

    def test_basic_estimation(self):
        """Test basic IV estimation."""
        iv = estimate_iv_calibrated(0.20, "UNKNOWN")
        assert 0.10 < iv < 0.50

    def test_symbol_adjustment(self):
        """Test symbol-specific adjustment."""
        iv_spy = estimate_iv_calibrated(0.20, "SPY")
        iv_unknown = estimate_iv_calibrated(0.20, "UNKNOWN")
        assert iv_spy != iv_unknown

    def test_vix_regime_adjustment(self):
        """Test VIX regime adjustment."""
        iv_low_vix = estimate_iv_calibrated(0.20, "AAPL", vix=12.0)
        iv_high_vix = estimate_iv_calibrated(0.20, "AAPL", vix=35.0)
        assert iv_high_vix > iv_low_vix

    def test_moneyness_skew(self):
        """Test OTM put skew."""
        iv_atm = estimate_iv_calibrated(0.20, "AAPL", moneyness=1.0)
        iv_otm = estimate_iv_calibrated(0.20, "AAPL", moneyness=0.90)
        assert iv_otm > iv_atm

    def test_dte_adjustment(self):
        """Test DTE term structure adjustment."""
        iv_short_dte = estimate_iv_calibrated(0.20, "AAPL", dte=10)
        iv_long_dte = estimate_iv_calibrated(0.20, "AAPL", dte=90)
        assert iv_long_dte > iv_short_dte

    def test_iv_clamped(self):
        """Test IV is clamped to reasonable range."""
        # Very high HV
        iv = estimate_iv_calibrated(2.0, "MSTR", vix=50.0)
        assert iv <= 1.50

        # Very low HV
        iv = estimate_iv_calibrated(0.01, "UNKNOWN")
        assert iv >= 0.10


# =============================================================================
# QUICK PRICING FUNCTIONS TESTS
# =============================================================================

class TestQuickPricingFunctions:
    """Tests for quick pricing convenience functions."""

    def test_quick_put_price(self):
        """Test quick put price calculation."""
        price = quick_put_price(100.0, 95.0, 45, 0.25)
        assert price > 0
        assert price < 10

    def test_quick_spread_credit(self):
        """Test quick spread credit calculation."""
        credit = quick_spread_credit(100.0, 95.0, 90.0, 45, 0.25)
        assert credit > 0


# =============================================================================
# BATCH FUNCTIONS TESTS
# =============================================================================

class TestBatchFunctions:
    """Tests for batch/vectorized functions."""

    def test_batch_spread_credit(self):
        """Test batch spread credit calculation."""
        spots = np.array([100.0, 105.0, 110.0])
        short_strikes = np.array([95.0, 100.0, 105.0])
        long_strikes = np.array([90.0, 95.0, 100.0])
        dtes = np.array([45.0, 45.0, 45.0])
        ivs = np.array([0.25, 0.25, 0.25])

        credits = batch_spread_credit(spots, short_strikes, long_strikes, dtes, ivs)

        assert len(credits) == 3
        assert all(c > 0 for c in credits)

    def test_batch_spread_pnl(self):
        """Test batch P&L calculation."""
        entry_credits = np.array([1.50, 1.50, 1.50])
        current_spots = np.array([105.0, 100.0, 95.0])
        short_strikes = np.array([95.0, 95.0, 95.0])
        long_strikes = np.array([90.0, 90.0, 90.0])
        dtes_remaining = np.array([30.0, 30.0, 30.0])
        current_ivs = np.array([0.22, 0.25, 0.30])

        pnls = batch_spread_pnl(
            entry_credits, current_spots, short_strikes,
            long_strikes, dtes_remaining, current_ivs
        )

        assert len(pnls) == 3
        # Higher spot should have better P&L
        assert pnls[0] > pnls[2]

    def test_batch_historical_volatility_1d(self):
        """Test batch HV with 1D array."""
        prices = np.array([100.0, 101.0, 99.5, 102.0, 100.5] * 10)  # 50 days
        hv = batch_historical_volatility(prices, window=20)

        # Result could be 0-d array or scalar
        hv_float = float(hv)
        assert 0 < hv_float < 1

    def test_batch_historical_volatility_2d(self):
        """Test batch HV with 2D array."""
        prices = np.array([
            [100.0, 101.0, 99.5, 102.0, 100.5] * 10,  # Symbol 1
            [50.0, 51.0, 49.0, 52.0, 50.5] * 10,      # Symbol 2
        ])
        hvs = batch_historical_volatility(prices, window=20)

        assert len(hvs) == 2
        assert all(0 < hv < 1 for hv in hvs)

    def test_batch_estimate_iv(self):
        """Test batch IV estimation."""
        hvs = np.array([0.20, 0.25, 0.30])
        vix = np.array([15.0, 20.0, 30.0])

        ivs = batch_estimate_iv(hvs, vix)

        assert len(ivs) == 3
        # Higher HV should give higher IV
        assert ivs[0] < ivs[1] < ivs[2]

    def test_batch_estimate_iv_with_moneyness(self):
        """Test batch IV estimation with moneyness."""
        hvs = np.array([0.20, 0.20, 0.20])
        moneyness = np.array([1.0, 0.95, 0.90])

        ivs = batch_estimate_iv(hvs, moneyness=moneyness)

        assert len(ivs) == 3
        # OTM should have higher IV (skew)
        assert ivs[0] < ivs[1] < ivs[2]


# =============================================================================
# SCALAR WRAPPER TESTS
# =============================================================================

class TestScalarWrappers:
    """Tests for scalar wrapper functions."""

    def test_black_scholes_call_scalar(self):
        """Test scalar call wrapper."""
        price = black_scholes_call(100.0, 100.0, 0.5, 0.05, 0.25)
        assert isinstance(price, float)

    def test_black_scholes_put_scalar(self):
        """Test scalar put wrapper."""
        price = black_scholes_put(100.0, 100.0, 0.5, 0.05, 0.25)
        assert isinstance(price, float)

    def test_black_scholes_price_call(self):
        """Test generic price function for call."""
        price = black_scholes_price(100.0, 100.0, 0.5, 0.05, 0.25, "C")
        call_price = black_scholes_call(100.0, 100.0, 0.5, 0.05, 0.25)
        assert price == call_price

    def test_black_scholes_price_put(self):
        """Test generic price function for put."""
        price = black_scholes_price(100.0, 100.0, 0.5, 0.05, 0.25, "P")
        put_price = black_scholes_put(100.0, 100.0, 0.5, 0.05, 0.25)
        assert price == put_price


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
