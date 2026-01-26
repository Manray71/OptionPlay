# OptionPlay - Black-Scholes Options Pricing Model
# =================================================
"""
Implementiert das Black-Scholes-Merton Modell für europäische Optionen.

Features:
- Theoretischer Optionspreis (Call & Put)
- Greeks: Delta, Gamma, Theta, Vega, Rho
- Implied Volatility Berechnung (Newton-Raphson)
- Spread-Pricing für Bull-Put-Spreads

Mathematische Grundlagen:
    C = S*N(d1) - K*e^(-rT)*N(d2)
    P = K*e^(-rT)*N(-d2) - S*N(-d1)

    d1 = (ln(S/K) + (r + σ²/2)*T) / (σ*√T)
    d2 = d1 - σ*√T

Verwendung:
    from src.options.black_scholes import BlackScholes, OptionType

    bs = BlackScholes(
        spot=100,
        strike=95,
        time_to_expiry=30/365,
        risk_free_rate=0.05,
        volatility=0.25
    )

    price = bs.put_price()
    delta = bs.delta(OptionType.PUT)
    greeks = bs.all_greeks(OptionType.PUT)
"""

import math
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Tuple
from functools import lru_cache

logger = logging.getLogger(__name__)


class OptionType(Enum):
    """Optionstyp"""
    CALL = "call"
    PUT = "put"


@dataclass
class Greeks:
    """
    Container für alle Greeks einer Option.

    Attributes:
        delta: Preisänderung pro $1 Bewegung im Underlying (-1 bis +1)
        gamma: Änderung von Delta pro $1 Bewegung (immer positiv)
        theta: Täglicher Zeitwertverlust (negativ für Long-Positionen)
        vega: Preisänderung pro 1% IV-Änderung
        rho: Preisänderung pro 1% Zinsänderung
    """
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0  # Täglicher Theta (nicht annualisiert)
    vega: float = 0.0   # Pro 1% IV-Änderung
    rho: float = 0.0    # Pro 1% Zinsänderung

    def to_dict(self) -> Dict[str, float]:
        """Konvertiert zu Dictionary"""
        return {
            'delta': round(self.delta, 4),
            'gamma': round(self.gamma, 4),
            'theta': round(self.theta, 4),
            'vega': round(self.vega, 4),
            'rho': round(self.rho, 4),
        }

    def __repr__(self) -> str:
        return (
            f"Greeks(Δ={self.delta:.4f}, Γ={self.gamma:.4f}, "
            f"Θ={self.theta:.4f}, ν={self.vega:.4f}, ρ={self.rho:.4f})"
        )


@dataclass
class SpreadGreeks:
    """
    Greeks für einen Options-Spread (z.B. Bull-Put-Spread).

    Net Greeks = Short Leg Greeks - Long Leg Greeks (für Credit Spreads)
    """
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    net_rho: float = 0.0

    # Individual Legs
    short_leg: Optional[Greeks] = None
    long_leg: Optional[Greeks] = None

    def to_dict(self) -> Dict[str, any]:
        """Konvertiert zu Dictionary"""
        result = {
            'net_delta': round(self.net_delta, 4),
            'net_gamma': round(self.net_gamma, 4),
            'net_theta': round(self.net_theta, 4),
            'net_vega': round(self.net_vega, 4),
            'net_rho': round(self.net_rho, 4),
        }
        if self.short_leg:
            result['short_leg'] = self.short_leg.to_dict()
        if self.long_leg:
            result['long_leg'] = self.long_leg.to_dict()
        return result


class BlackScholes:
    """
    Black-Scholes-Merton Options-Pricing Modell.

    Berechnet theoretische Preise und Greeks für europäische Optionen.

    Args:
        spot: Aktueller Kurs des Underlyings
        strike: Strike-Preis der Option
        time_to_expiry: Zeit bis Verfall in Jahren (z.B. 30/365 für 30 Tage)
        risk_free_rate: Risikofreier Zinssatz (annualisiert, z.B. 0.05 für 5%)
        volatility: Implizite Volatilität (annualisiert, z.B. 0.25 für 25%)
        dividend_yield: Dividendenrendite (annualisiert, default 0)

    Example:
        >>> bs = BlackScholes(100, 95, 30/365, 0.05, 0.25)
        >>> bs.put_price()
        1.234
        >>> bs.delta(OptionType.PUT)
        -0.234
    """

    # Konstante für numerische Stabilität
    MIN_VOLATILITY = 0.001
    MIN_TIME = 1e-10
    MAX_VOLATILITY = 5.0  # 500% IV cap

    def __init__(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float = 0.05,
        volatility: float = 0.25,
        dividend_yield: float = 0.0,
    ):
        self.spot = spot
        self.strike = strike
        self.time_to_expiry = max(time_to_expiry, self.MIN_TIME)
        self.risk_free_rate = risk_free_rate
        self.volatility = max(min(volatility, self.MAX_VOLATILITY), self.MIN_VOLATILITY)
        self.dividend_yield = dividend_yield

        # Pre-calculate common values
        self._calculate_d1_d2()

    def _calculate_d1_d2(self) -> None:
        """Berechnet d1 und d2 für Black-Scholes Formel"""
        S = self.spot
        K = self.strike
        T = self.time_to_expiry
        r = self.risk_free_rate
        q = self.dividend_yield
        σ = self.volatility

        sqrt_T = math.sqrt(T)

        # d1 = (ln(S/K) + (r - q + σ²/2)*T) / (σ*√T)
        self._d1 = (
            math.log(S / K) + (r - q + 0.5 * σ ** 2) * T
        ) / (σ * sqrt_T)

        # d2 = d1 - σ*√T
        self._d2 = self._d1 - σ * sqrt_T

        # Pre-calculate N(d1), N(d2), N(-d1), N(-d2)
        self._Nd1 = self._norm_cdf(self._d1)
        self._Nd2 = self._norm_cdf(self._d2)
        self._Nnd1 = self._norm_cdf(-self._d1)
        self._Nnd2 = self._norm_cdf(-self._d2)

        # Pre-calculate n(d1) for Greeks
        self._nd1 = self._norm_pdf(self._d1)

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """
        Kumulative Standardnormalverteilung N(x).

        Verwendet Approximation mit hoher Genauigkeit.
        """
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    @staticmethod
    def _norm_pdf(x: float) -> float:
        """Standardnormalverteilungs-Dichte n(x)"""
        return math.exp(-0.5 * x ** 2) / math.sqrt(2 * math.pi)

    # =========================================================================
    # OPTION PRICES
    # =========================================================================

    def call_price(self) -> float:
        """
        Berechnet den theoretischen Call-Preis.

        C = S*e^(-qT)*N(d1) - K*e^(-rT)*N(d2)

        Returns:
            Call-Optionspreis
        """
        S = self.spot
        K = self.strike
        T = self.time_to_expiry
        r = self.risk_free_rate
        q = self.dividend_yield

        call = (
            S * math.exp(-q * T) * self._Nd1
            - K * math.exp(-r * T) * self._Nd2
        )

        return max(0, call)

    def put_price(self) -> float:
        """
        Berechnet den theoretischen Put-Preis.

        P = K*e^(-rT)*N(-d2) - S*e^(-qT)*N(-d1)

        Returns:
            Put-Optionspreis
        """
        S = self.spot
        K = self.strike
        T = self.time_to_expiry
        r = self.risk_free_rate
        q = self.dividend_yield

        put = (
            K * math.exp(-r * T) * self._Nnd2
            - S * math.exp(-q * T) * self._Nnd1
        )

        return max(0, put)

    def price(self, option_type: OptionType) -> float:
        """Gibt Preis basierend auf Optionstyp zurück"""
        if option_type == OptionType.CALL:
            return self.call_price()
        return self.put_price()

    # =========================================================================
    # GREEKS
    # =========================================================================

    def delta(self, option_type: OptionType) -> float:
        """
        Berechnet Delta - Preisänderung pro $1 im Underlying.

        Call Delta: e^(-qT) * N(d1)  → Range: [0, 1]
        Put Delta: -e^(-qT) * N(-d1) → Range: [-1, 0]

        Args:
            option_type: CALL oder PUT

        Returns:
            Delta (-1 bis +1)
        """
        q = self.dividend_yield
        T = self.time_to_expiry
        discount = math.exp(-q * T)

        if option_type == OptionType.CALL:
            return discount * self._Nd1
        return -discount * self._Nnd1

    def gamma(self) -> float:
        """
        Berechnet Gamma - Änderung von Delta pro $1 im Underlying.

        Gamma = e^(-qT) * n(d1) / (S * σ * √T)

        Gleich für Calls und Puts (immer positiv).

        Returns:
            Gamma (immer >= 0)
        """
        S = self.spot
        T = self.time_to_expiry
        q = self.dividend_yield
        σ = self.volatility

        gamma = (
            math.exp(-q * T) * self._nd1
            / (S * σ * math.sqrt(T))
        )

        return gamma

    def theta(self, option_type: OptionType) -> float:
        """
        Berechnet Theta - täglicher Zeitwertverlust.

        Call Theta = -[S*σ*e^(-qT)*n(d1)/(2√T)] - r*K*e^(-rT)*N(d2) + q*S*e^(-qT)*N(d1)
        Put Theta = -[S*σ*e^(-qT)*n(d1)/(2√T)] + r*K*e^(-rT)*N(-d2) - q*S*e^(-qT)*N(-d1)

        Args:
            option_type: CALL oder PUT

        Returns:
            Theta pro Tag (typischerweise negativ für Long-Positionen)
        """
        S = self.spot
        K = self.strike
        T = self.time_to_expiry
        r = self.risk_free_rate
        q = self.dividend_yield
        σ = self.volatility

        sqrt_T = math.sqrt(T)
        exp_qT = math.exp(-q * T)
        exp_rT = math.exp(-r * T)

        # Gemeinsamer Term
        first_term = -(S * σ * exp_qT * self._nd1) / (2 * sqrt_T)

        if option_type == OptionType.CALL:
            theta_annual = (
                first_term
                - r * K * exp_rT * self._Nd2
                + q * S * exp_qT * self._Nd1
            )
        else:
            theta_annual = (
                first_term
                + r * K * exp_rT * self._Nnd2
                - q * S * exp_qT * self._Nnd1
            )

        # Konvertiere zu täglichem Theta (252 Handelstage)
        return theta_annual / 365

    def vega(self) -> float:
        """
        Berechnet Vega - Preisänderung pro 1% IV-Änderung.

        Vega = S * e^(-qT) * √T * n(d1)

        Gleich für Calls und Puts (immer positiv).
        Ergebnis ist für 1% (0.01) Änderung, nicht 100%.

        Returns:
            Vega (pro 1% IV-Änderung)
        """
        S = self.spot
        T = self.time_to_expiry
        q = self.dividend_yield

        # Vega für 100% (1.0) Änderung
        vega_full = S * math.exp(-q * T) * math.sqrt(T) * self._nd1

        # Konvertiere zu 1% Änderung
        return vega_full / 100

    def rho(self, option_type: OptionType) -> float:
        """
        Berechnet Rho - Preisänderung pro 1% Zinsänderung.

        Call Rho = K * T * e^(-rT) * N(d2)
        Put Rho = -K * T * e^(-rT) * N(-d2)

        Args:
            option_type: CALL oder PUT

        Returns:
            Rho (pro 1% Zinsänderung)
        """
        K = self.strike
        T = self.time_to_expiry
        r = self.risk_free_rate

        exp_rT = math.exp(-r * T)

        if option_type == OptionType.CALL:
            rho_full = K * T * exp_rT * self._Nd2
        else:
            rho_full = -K * T * exp_rT * self._Nnd2

        # Konvertiere zu 1% Änderung
        return rho_full / 100

    def all_greeks(self, option_type: OptionType) -> Greeks:
        """
        Berechnet alle Greeks auf einmal.

        Args:
            option_type: CALL oder PUT

        Returns:
            Greeks-Objekt mit allen Werten
        """
        return Greeks(
            delta=self.delta(option_type),
            gamma=self.gamma(),
            theta=self.theta(option_type),
            vega=self.vega(),
            rho=self.rho(option_type),
        )

    # =========================================================================
    # IMPLIED VOLATILITY
    # =========================================================================

    def implied_volatility(
        self,
        market_price: float,
        option_type: OptionType,
        max_iterations: int = 100,
        tolerance: float = 1e-6,
    ) -> Optional[float]:
        """
        Berechnet die Implied Volatility aus dem Marktpreis.

        Verwendet Newton-Raphson Iteration:
        σ_new = σ_old - (Price(σ) - Market) / Vega(σ)

        Args:
            market_price: Aktueller Marktpreis der Option
            option_type: CALL oder PUT
            max_iterations: Max. Iterationen (default 100)
            tolerance: Genauigkeit (default 1e-6)

        Returns:
            Implied Volatility oder None wenn nicht konvergiert
        """
        # Intrinsic Value Check
        if option_type == OptionType.CALL:
            intrinsic = max(0, self.spot - self.strike)
        else:
            intrinsic = max(0, self.strike - self.spot)

        if market_price < intrinsic:
            logger.warning(f"Market price {market_price} below intrinsic {intrinsic}")
            return None

        # Initialer Schätzwert
        σ = 0.25  # Start bei 25% IV

        for i in range(max_iterations):
            # Erstelle BS mit aktueller IV
            bs = BlackScholes(
                spot=self.spot,
                strike=self.strike,
                time_to_expiry=self.time_to_expiry,
                risk_free_rate=self.risk_free_rate,
                volatility=σ,
                dividend_yield=self.dividend_yield,
            )

            # Berechne Preis und Vega
            price = bs.price(option_type)
            vega = bs.vega() * 100  # Volle Vega für Newton-Raphson

            # Fehler
            diff = price - market_price

            # Konvergenz Check
            if abs(diff) < tolerance:
                return σ

            # Vega zu klein für sichere Division
            if abs(vega) < 1e-10:
                # Bisection Fallback
                if diff > 0:
                    σ *= 0.9
                else:
                    σ *= 1.1
                continue

            # Newton-Raphson Update
            σ_new = σ - diff / vega

            # Bounds enforcing
            σ = max(self.MIN_VOLATILITY, min(self.MAX_VOLATILITY, σ_new))

        logger.warning(f"IV calculation did not converge after {max_iterations} iterations")
        return σ  # Return best estimate

    # =========================================================================
    # PROBABILITY CALCULATIONS
    # =========================================================================

    def probability_itm(self, option_type: OptionType) -> float:
        """
        Wahrscheinlichkeit dass Option ITM verfällt.

        P(ITM Call) = N(d2)
        P(ITM Put) = N(-d2)

        Args:
            option_type: CALL oder PUT

        Returns:
            Wahrscheinlichkeit (0-1)
        """
        if option_type == OptionType.CALL:
            return self._Nd2
        return self._Nnd2

    def probability_otm(self, option_type: OptionType) -> float:
        """Wahrscheinlichkeit dass Option OTM verfällt (1 - P(ITM))"""
        return 1 - self.probability_itm(option_type)

    def probability_touch(self, option_type: OptionType) -> float:
        """
        Wahrscheinlichkeit dass Strike während Laufzeit berührt wird.

        Approximation: ~2 * P(ITM) für OTM Optionen

        Returns:
            Wahrscheinlichkeit (0-1)
        """
        p_itm = self.probability_itm(option_type)

        # Nur für OTM relevant
        if option_type == OptionType.PUT and self.spot > self.strike:
            return min(1.0, 2 * p_itm)
        elif option_type == OptionType.CALL and self.spot < self.strike:
            return min(1.0, 2 * p_itm)

        return 1.0  # ITM option will certainly touch strike


# =============================================================================
# SPREAD PRICING
# =============================================================================

@dataclass
class BullPutSpread:
    """
    Bull-Put-Spread (Credit Put Spread) Pricing und Greeks.

    Struktur:
    - Short Put @ higher strike (mehr Premium)
    - Long Put @ lower strike (Absicherung)

    Max Profit: Net Credit erhalten
    Max Loss: Spread Width - Net Credit
    Break-Even: Short Strike - Net Credit

    Args:
        spot: Aktueller Kurs
        short_strike: Strike des verkauften Puts (höher)
        long_strike: Strike des gekauften Puts (niedriger)
        time_to_expiry: Zeit bis Verfall in Jahren
        volatility: Implizite Volatilität
        risk_free_rate: Risikofreier Zinssatz
    """
    spot: float
    short_strike: float
    long_strike: float
    time_to_expiry: float
    volatility: float = 0.25
    risk_free_rate: float = 0.05
    dividend_yield: float = 0.0

    # Calculated values
    short_put_price: float = field(init=False)
    long_put_price: float = field(init=False)
    net_credit: float = field(init=False)
    spread_width: float = field(init=False)
    max_profit: float = field(init=False)
    max_loss: float = field(init=False)
    break_even: float = field(init=False)

    def __post_init__(self):
        """Validierung und Berechnung nach Initialisierung"""
        # Validierung
        if self.short_strike <= self.long_strike:
            raise ValueError(
                f"Short strike ({self.short_strike}) must be > long strike ({self.long_strike})"
            )
        if self.spot <= 0:
            raise ValueError(f"Spot price must be positive, got {self.spot}")
        if self.time_to_expiry <= 0:
            raise ValueError(f"Time to expiry must be positive, got {self.time_to_expiry}")
        if self.volatility <= 0:
            raise ValueError(f"Volatility must be positive, got {self.volatility}")

        # Black-Scholes für beide Legs
        self._short_bs = BlackScholes(
            spot=self.spot,
            strike=self.short_strike,
            time_to_expiry=self.time_to_expiry,
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            dividend_yield=self.dividend_yield,
        )

        self._long_bs = BlackScholes(
            spot=self.spot,
            strike=self.long_strike,
            time_to_expiry=self.time_to_expiry,
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            dividend_yield=self.dividend_yield,
        )

        # Preise berechnen
        self.short_put_price = self._short_bs.put_price()
        self.long_put_price = self._long_bs.put_price()

        # Spread Metrics
        self.net_credit = self.short_put_price - self.long_put_price
        self.spread_width = self.short_strike - self.long_strike
        self.max_profit = self.net_credit
        self.max_loss = self.spread_width - self.net_credit
        self.break_even = self.short_strike - self.net_credit

    def greeks(self) -> SpreadGreeks:
        """
        Berechnet Net Greeks für den Spread.

        Net = Short Leg - Long Leg (wegen Credit Spread)

        Returns:
            SpreadGreeks mit Net-Werten und individuellen Legs
        """
        short_greeks = self._short_bs.all_greeks(OptionType.PUT)
        long_greeks = self._long_bs.all_greeks(OptionType.PUT)

        # Net Greeks (Short - Long, da wir Short den Short Put sind)
        # Short Put = -1 * Put Greeks (wir erhalten Premium)
        # Long Put = +1 * Put Greeks (wir zahlen Premium)
        return SpreadGreeks(
            net_delta=-short_greeks.delta + long_greeks.delta,
            net_gamma=-short_greeks.gamma + long_greeks.gamma,
            net_theta=-short_greeks.theta + long_greeks.theta,  # Positiv für Credit Spreads
            net_vega=-short_greeks.vega + long_greeks.vega,
            net_rho=-short_greeks.rho + long_greeks.rho,
            short_leg=short_greeks,
            long_leg=long_greeks,
        )

    def probability_max_profit(self) -> float:
        """
        Wahrscheinlichkeit für Max Profit (beide Puts OTM).

        Returns:
            Wahrscheinlichkeit (0-1)
        """
        return self._short_bs.probability_otm(OptionType.PUT)

    def probability_any_profit(self) -> float:
        """
        Wahrscheinlichkeit für irgendeinen Profit (über Break-Even).

        Approximation: P(Price > Break-Even at expiry)

        Returns:
            Wahrscheinlichkeit (0-1)
        """
        # Erstelle BS für Break-Even Level
        be_bs = BlackScholes(
            spot=self.spot,
            strike=self.break_even,
            time_to_expiry=self.time_to_expiry,
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            dividend_yield=self.dividend_yield,
        )

        return be_bs.probability_otm(OptionType.PUT)

    def probability_max_loss(self) -> float:
        """
        Wahrscheinlichkeit für Max Loss (Long Put ITM).

        Returns:
            Wahrscheinlichkeit (0-1)
        """
        return self._long_bs.probability_itm(OptionType.PUT)

    def value_at_price(self, underlying_price: float) -> float:
        """
        Berechnet den Spread-Wert bei einem bestimmten Underlying-Preis.

        Args:
            underlying_price: Preis des Underlyings

        Returns:
            Spread-Wert (positiv = Profit, negativ = Loss)
        """
        # Bei Verfall
        short_put_value = max(0, self.short_strike - underlying_price)
        long_put_value = max(0, self.long_strike - underlying_price)

        # Short Put Obligation - Long Put Protection
        spread_cost = short_put_value - long_put_value

        # P&L = Credit erhalten - Spread Cost
        return self.net_credit - spread_cost

    def value_at_price_before_expiry(
        self,
        underlying_price: float,
        remaining_dte: float,
        new_volatility: Optional[float] = None,
    ) -> float:
        """
        Berechnet den Spread-Wert vor Verfall.

        Berücksichtigt Time Value und optionale IV-Änderung.

        Args:
            underlying_price: Neuer Preis des Underlyings
            remaining_dte: Verbleibende Tage bis Verfall
            new_volatility: Neue IV (optional, sonst Original-IV)

        Returns:
            Spread-Wert
        """
        vol = new_volatility if new_volatility else self.volatility
        time_years = remaining_dte / 365

        short_bs = BlackScholes(
            spot=underlying_price,
            strike=self.short_strike,
            time_to_expiry=time_years,
            risk_free_rate=self.risk_free_rate,
            volatility=vol,
            dividend_yield=self.dividend_yield,
        )

        long_bs = BlackScholes(
            spot=underlying_price,
            strike=self.long_strike,
            time_to_expiry=time_years,
            risk_free_rate=self.risk_free_rate,
            volatility=vol,
            dividend_yield=self.dividend_yield,
        )

        current_short = short_bs.put_price()
        current_long = long_bs.put_price()
        current_spread_value = current_short - current_long

        # P&L = Original Credit - Current Spread Value
        # (Lower spread value = profit for credit spread)
        return self.net_credit - current_spread_value

    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary"""
        greeks = self.greeks()
        return {
            'structure': {
                'short_strike': self.short_strike,
                'long_strike': self.long_strike,
                'spread_width': round(self.spread_width, 2),
            },
            'pricing': {
                'short_put_price': round(self.short_put_price, 4),
                'long_put_price': round(self.long_put_price, 4),
                'net_credit': round(self.net_credit, 4),
            },
            'risk_reward': {
                'max_profit': round(self.max_profit, 4),
                'max_loss': round(self.max_loss, 4),
                'break_even': round(self.break_even, 2),
                'risk_reward_ratio': round(self.max_profit / self.max_loss, 2) if self.max_loss > 0 else float('inf'),
            },
            'probabilities': {
                'max_profit': round(self.probability_max_profit() * 100, 1),
                'any_profit': round(self.probability_any_profit() * 100, 1),
                'max_loss': round(self.probability_max_loss() * 100, 1),
            },
            'greeks': greeks.to_dict(),
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def calculate_put_price(
    spot: float,
    strike: float,
    dte: int,
    volatility: float,
    risk_free_rate: float = 0.05,
) -> float:
    """
    Convenience-Funktion für Put-Preis Berechnung.

    Args:
        spot: Aktueller Kurs
        strike: Strike-Preis
        dte: Days to Expiration
        volatility: IV (z.B. 0.25 für 25%)
        risk_free_rate: Risikofreier Zins

    Returns:
        Theoretischer Put-Preis
    """
    bs = BlackScholes(
        spot=spot,
        strike=strike,
        time_to_expiry=dte / 365,
        risk_free_rate=risk_free_rate,
        volatility=volatility,
    )
    return bs.put_price()


def calculate_call_price(
    spot: float,
    strike: float,
    dte: int,
    volatility: float,
    risk_free_rate: float = 0.05,
) -> float:
    """Convenience-Funktion für Call-Preis Berechnung."""
    bs = BlackScholes(
        spot=spot,
        strike=strike,
        time_to_expiry=dte / 365,
        risk_free_rate=risk_free_rate,
        volatility=volatility,
    )
    return bs.call_price()


def calculate_delta(
    spot: float,
    strike: float,
    dte: int,
    volatility: float,
    option_type: OptionType,
    risk_free_rate: float = 0.05,
) -> float:
    """
    Convenience-Funktion für Delta Berechnung.

    Args:
        spot: Aktueller Kurs
        strike: Strike-Preis
        dte: Days to Expiration
        volatility: IV
        option_type: CALL oder PUT
        risk_free_rate: Risikofreier Zins

    Returns:
        Delta (-1 bis +1)
    """
    bs = BlackScholes(
        spot=spot,
        strike=strike,
        time_to_expiry=dte / 365,
        risk_free_rate=risk_free_rate,
        volatility=volatility,
    )
    return bs.delta(option_type)


def calculate_implied_volatility(
    spot: float,
    strike: float,
    dte: int,
    market_price: float,
    option_type: OptionType,
    risk_free_rate: float = 0.05,
) -> Optional[float]:
    """
    Convenience-Funktion für IV Berechnung.

    Args:
        spot: Aktueller Kurs
        strike: Strike-Preis
        dte: Days to Expiration
        market_price: Aktueller Marktpreis der Option
        option_type: CALL oder PUT
        risk_free_rate: Risikofreier Zins

    Returns:
        Implied Volatility oder None
    """
    bs = BlackScholes(
        spot=spot,
        strike=strike,
        time_to_expiry=dte / 365,
        risk_free_rate=risk_free_rate,
        volatility=0.25,  # Initial guess
    )
    return bs.implied_volatility(market_price, option_type)


def calculate_probability_otm(
    spot: float,
    strike: float,
    dte: int,
    volatility: float,
    option_type: OptionType,
    risk_free_rate: float = 0.05,
) -> float:
    """
    Berechnet Wahrscheinlichkeit dass Option OTM verfällt.

    Nützlich für Credit Spread Win-Probability.

    Args:
        spot: Aktueller Kurs
        strike: Strike-Preis
        dte: Days to Expiration
        volatility: IV
        option_type: CALL oder PUT
        risk_free_rate: Risikofreier Zins

    Returns:
        Wahrscheinlichkeit (0-1)
    """
    bs = BlackScholes(
        spot=spot,
        strike=strike,
        time_to_expiry=dte / 365,
        risk_free_rate=risk_free_rate,
        volatility=volatility,
    )
    return bs.probability_otm(option_type)
