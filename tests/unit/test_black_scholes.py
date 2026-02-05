#!/usr/bin/env python3
"""
Tests für das Black-Scholes Options Pricing Modul.

Verifiziert:
- Korrekte Preisberechnung gegen bekannte Werte
- Greeks Berechnung (Delta, Gamma, Theta, Vega)
- Implied Volatility Konvergenz
- Bull-Put-Spread Pricing
- Edge Cases und numerische Stabilität
"""

import pytest
import math
from src.options.black_scholes import (
    BlackScholes,
    BullPutSpread,
    OptionType,
    Greeks,
    SpreadGreeks,
    calculate_put_price,
    calculate_call_price,
    calculate_delta,
    calculate_probability_otm,
)


class TestBlackScholesBasics:
    """Grundlegende Black-Scholes Tests"""

    def test_call_price_atm(self):
        """ATM Call sollte positiv und reasonable bei 25% IV, 30 DTE sein"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        call = bs.call_price()

        # ATM Call bei 30 DTE, 25% IV sollte ~$2.5-5 sein
        assert 2.0 < call < 6.0, f"ATM Call price unexpected: {call}"

    def test_put_price_atm(self):
        """ATM Put sollte ähnlich wie ATM Call sein (Put-Call Parity)"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        put = bs.put_price()

        # ATM Put bei 30 DTE, 25% IV
        assert 2.0 < put < 5.0, f"ATM Put price unexpected: {put}"

    def test_put_call_parity(self):
        """Put-Call Parity: C - P = S - K*e^(-rT)"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        call = bs.call_price()
        put = bs.put_price()

        # Put-Call Parity
        S = 100
        K = 100
        r = 0.05
        T = 30 / 365
        expected_diff = S - K * math.exp(-r * T)
        actual_diff = call - put

        assert abs(expected_diff - actual_diff) < 0.01, \
            f"Put-Call Parity violated: {expected_diff} vs {actual_diff}"

    def test_deep_itm_call(self):
        """Deep ITM Call sollte ~Intrinsic Value haben"""
        bs = BlackScholes(
            spot=100,
            strike=80,  # Deep ITM
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        call = bs.call_price()
        intrinsic = 100 - 80  # $20

        # Deep ITM sollte nahe Intrinsic sein
        assert call >= intrinsic, f"ITM Call below intrinsic: {call} < {intrinsic}"
        assert call < intrinsic + 2, f"ITM Call too expensive: {call}"

    def test_deep_otm_put(self):
        """Deep OTM Put sollte nahe 0 sein"""
        bs = BlackScholes(
            spot=100,
            strike=70,  # Deep OTM Put
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        put = bs.put_price()

        # Deep OTM Put sollte sehr klein sein
        assert put < 0.5, f"Deep OTM Put too expensive: {put}"
        assert put >= 0, f"Put price negative: {put}"


class TestGreeks:
    """Tests für Greeks Berechnung"""

    def test_call_delta_range(self):
        """Call Delta sollte zwischen 0 und 1 sein"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        delta = bs.delta(OptionType.CALL)

        assert 0 <= delta <= 1, f"Call delta out of range: {delta}"
        # ATM sollte ~0.5 sein
        assert 0.45 < delta < 0.60, f"ATM Call delta unexpected: {delta}"

    def test_put_delta_range(self):
        """Put Delta sollte zwischen -1 und 0 sein"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        delta = bs.delta(OptionType.PUT)

        assert -1 <= delta <= 0, f"Put delta out of range: {delta}"
        # ATM sollte ~-0.5 sein
        assert -0.55 < delta < -0.40, f"ATM Put delta unexpected: {delta}"

    def test_gamma_positive(self):
        """Gamma sollte immer positiv sein"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        gamma = bs.gamma()

        assert gamma > 0, f"Gamma should be positive: {gamma}"
        # ATM Gamma bei 30 DTE sollte ~0.05-0.08 sein
        assert 0.03 < gamma < 0.12, f"Gamma unexpected: {gamma}"

    def test_theta_negative_for_long(self):
        """Theta für Long-Positionen sollte negativ sein"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        theta_call = bs.theta(OptionType.CALL)
        theta_put = bs.theta(OptionType.PUT)

        # Theta ist für Long-Positionen negativ (Zeitwertverfall)
        assert theta_call < 0, f"Call theta should be negative: {theta_call}"
        assert theta_put < 0, f"Put theta should be negative: {theta_put}"

    def test_vega_positive(self):
        """Vega sollte immer positiv sein"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        vega = bs.vega()

        assert vega > 0, f"Vega should be positive: {vega}"

    def test_all_greeks_returns_greeks_object(self):
        """all_greeks() sollte Greeks Objekt zurückgeben"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )
        greeks = bs.all_greeks(OptionType.PUT)

        assert isinstance(greeks, Greeks)
        assert hasattr(greeks, 'delta')
        assert hasattr(greeks, 'gamma')
        assert hasattr(greeks, 'theta')
        assert hasattr(greeks, 'vega')
        assert hasattr(greeks, 'rho')


class TestImpliedVolatility:
    """Tests für IV Berechnung"""

    def test_iv_round_trip(self):
        """IV Berechnung sollte ursprüngliche IV zurückgeben"""
        original_iv = 0.30
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            risk_free_rate=0.05,
            volatility=original_iv,
        )

        price = bs.put_price()
        calculated_iv = bs.implied_volatility(price, OptionType.PUT)

        assert calculated_iv is not None
        assert abs(calculated_iv - original_iv) < 0.001, \
            f"IV round-trip failed: {original_iv} vs {calculated_iv}"

    def test_iv_convergence(self):
        """IV sollte für verschiedene Preise konvergieren"""
        bs = BlackScholes(
            spot=100,
            strike=95,
            time_to_expiry=45 / 365,
            risk_free_rate=0.05,
            volatility=0.25,
        )

        # Teste mit realistischem Marktpreis
        market_price = 2.50
        iv = bs.implied_volatility(market_price, OptionType.PUT)

        assert iv is not None
        assert 0.01 < iv < 2.0, f"IV out of reasonable range: {iv}"


class TestBullPutSpread:
    """Tests für Bull-Put-Spread Pricing"""

    def test_spread_creation(self):
        """Bull-Put-Spread sollte korrekt erstellt werden"""
        spread = BullPutSpread(
            spot=100,
            short_strike=95,
            long_strike=90,
            time_to_expiry=45 / 365,
            volatility=0.25,
            risk_free_rate=0.05,
        )

        assert spread.spread_width == 5
        assert spread.net_credit > 0
        assert spread.max_profit == spread.net_credit
        assert spread.max_loss == spread.spread_width - spread.net_credit
        assert spread.break_even == spread.short_strike - spread.net_credit

    def test_spread_validation(self):
        """Ungültige Spreads sollten ValidationError werfen"""
        # Short Strike muss > Long Strike sein
        with pytest.raises(ValueError):
            BullPutSpread(
                spot=100,
                short_strike=90,  # Niedriger als Long!
                long_strike=95,
                time_to_expiry=45 / 365,
            )

    def test_spread_probabilities(self):
        """Spread Wahrscheinlichkeiten sollten valide sein"""
        spread = BullPutSpread(
            spot=100,
            short_strike=95,
            long_strike=90,
            time_to_expiry=45 / 365,
            volatility=0.25,
        )

        p_max_profit = spread.probability_max_profit()
        p_any_profit = spread.probability_any_profit()
        p_max_loss = spread.probability_max_loss()

        # Wahrscheinlichkeiten sollten 0-1 sein
        assert 0 <= p_max_profit <= 1
        assert 0 <= p_any_profit <= 1
        assert 0 <= p_max_loss <= 1

        # P(any profit) >= P(max profit)
        assert p_any_profit >= p_max_profit

        # Bei OTM Put: P(max profit) sollte hoch sein
        assert p_max_profit > 0.5, f"OTM spread P(max profit) too low: {p_max_profit}"

    def test_spread_greeks(self):
        """Spread Greeks sollten korrekte Net-Werte haben"""
        spread = BullPutSpread(
            spot=100,
            short_strike=95,
            long_strike=90,
            time_to_expiry=45 / 365,
            volatility=0.25,
        )

        greeks = spread.greeks()

        assert isinstance(greeks, SpreadGreeks)

        # Credit Spread hat positive Theta (verkauft Zeit)
        assert greeks.net_theta > 0, f"Credit spread should have positive theta: {greeks.net_theta}"

        # Credit Spread hat negative Gamma (short gamma)
        assert greeks.net_gamma < 0, f"Credit spread should have negative gamma: {greeks.net_gamma}"

        # Bull Put hat positives Delta
        assert greeks.net_delta > 0, f"Bull put should have positive delta: {greeks.net_delta}"

    def test_spread_value_at_price(self):
        """Spread Value bei verschiedenen Preisen sollte korrekt sein"""
        spread = BullPutSpread(
            spot=100,
            short_strike=95,
            long_strike=90,
            time_to_expiry=45 / 365,
            volatility=0.25,
        )

        # Bei Preis > Short Strike: Max Profit
        value_above = spread.value_at_price(100)
        assert abs(value_above - spread.max_profit) < 0.01

        # Bei Preis < Long Strike: Max Loss (negativ)
        value_below = spread.value_at_price(85)
        assert abs(value_below - (-spread.max_loss)) < 0.01

        # Bei Break-Even: ~0
        value_be = spread.value_at_price(spread.break_even)
        assert abs(value_be) < 0.01


class TestConvenienceFunctions:
    """Tests für Convenience Functions"""

    def test_calculate_put_price(self):
        """calculate_put_price sollte funktionieren"""
        price = calculate_put_price(
            spot=100,
            strike=95,
            dte=30,
            volatility=0.25,
        )
        assert price > 0
        assert price < 5  # OTM Put sollte nicht zu teuer sein

    def test_calculate_call_price(self):
        """calculate_call_price sollte funktionieren"""
        price = calculate_call_price(
            spot=100,
            strike=105,
            dte=30,
            volatility=0.25,
        )
        assert price > 0
        assert price < 5  # OTM Call sollte nicht zu teuer sein

    def test_calculate_delta(self):
        """calculate_delta sollte korrekte Range haben"""
        put_delta = calculate_delta(
            spot=100,
            strike=95,
            dte=30,
            volatility=0.25,
            option_type=OptionType.PUT,
        )
        assert -1 <= put_delta <= 0

        call_delta = calculate_delta(
            spot=100,
            strike=105,
            dte=30,
            volatility=0.25,
            option_type=OptionType.CALL,
        )
        assert 0 <= call_delta <= 1

    def test_calculate_probability_otm(self):
        """calculate_probability_otm sollte valide Werte liefern"""
        prob = calculate_probability_otm(
            spot=100,
            strike=90,
            dte=45,
            volatility=0.25,
            option_type=OptionType.PUT,
        )

        assert 0 <= prob <= 1
        # OTM Put mit 10% Abstand sollte hohe OTM Prob haben
        assert prob > 0.7


class TestEdgeCases:
    """Tests für Grenzfälle"""

    def test_very_short_dte(self):
        """Sehr kurze DTE sollte funktionieren"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=1 / 365,  # 1 Tag
            volatility=0.25,
        )
        price = bs.call_price()
        assert price >= 0

    def test_very_high_volatility(self):
        """Sehr hohe IV sollte funktionieren"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            volatility=2.0,  # 200% IV
        )
        price = bs.call_price()
        assert price > 0

    def test_very_low_volatility(self):
        """Sehr niedrige IV sollte funktionieren"""
        bs = BlackScholes(
            spot=100,
            strike=100,
            time_to_expiry=30 / 365,
            volatility=0.01,  # 1% IV
        )
        price = bs.call_price()
        assert price >= 0

    def test_deep_otm_greeks(self):
        """Deep OTM Greeks sollten nicht NaN/Inf sein"""
        bs = BlackScholes(
            spot=100,
            strike=50,  # Very deep OTM Put
            time_to_expiry=30 / 365,
            volatility=0.25,
        )
        greeks = bs.all_greeks(OptionType.PUT)

        assert not math.isnan(greeks.delta)
        assert not math.isnan(greeks.gamma)
        assert not math.isnan(greeks.theta)
        assert not math.isnan(greeks.vega)
        assert not math.isinf(greeks.delta)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
