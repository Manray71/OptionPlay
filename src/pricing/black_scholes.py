#!/usr/bin/env python3
"""
Black-Scholes Options Pricing Model — Batch/Backtesting Module
================================================================

NumPy-vektorisierte Implementierung fuer Batch-Operationen und Backtesting.
Enthaelt kalibrierte IV-Schaetzungen mit symbol-spezifischen Multiplikatoren.

HINWEIS: Fuer interaktive Analyse und Spread-Bewertung siehe
``src/options/black_scholes.py`` (OOP-basiert, ``BlackScholes`` Klasse).

Features:
- NumPy-vektorisiertes Pricing (batch_spread_credit, batch_spread_pnl)
- Kalibrierte IV-Schaetzung (estimate_iv_calibrated) mit 347 Symbolen
- OptionPricer Klasse fuer Spread-Bewertung
- Greeks (Delta, Gamma, Theta, Vega, Rho)
- Implied Volatility (Newton-Raphson + Bisection Fallback)
- find_strike_for_delta() fuer Strike-Empfehlungen

Verwendung:
    from src.pricing import OptionPricer, black_scholes_put

    # Einzelne Option
    put_price = black_scholes_put(
        S=100,      # Aktienkurs
        K=95,       # Strike
        T=0.25,     # Zeit bis Verfall (Jahre)
        r=0.05,     # Risikofreier Zins
        sigma=0.20  # Volatilität
    )

    # Mit Pricer-Klasse
    pricer = OptionPricer(risk_free_rate=0.05)
    result = pricer.price_bull_put_spread(
        underlying_price=100,
        short_strike=95,
        long_strike=90,
        days_to_expiry=45,
        volatility=0.25
    )
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple, Union
from datetime import date
import logging

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# Type alias for scalar or array inputs
FloatOrArray = Union[float, NDArray[np.float64]]


# =============================================================================
# CONSTANTS
# =============================================================================

# Standard Normal Distribution
_SQRT_2PI = math.sqrt(2 * math.pi)


# =============================================================================
# HELPER FUNCTIONS - NumPy Vectorized
# =============================================================================

def _norm_cdf_np(x: FloatOrArray) -> FloatOrArray:
    """
    Cumulative Distribution Function der Standardnormalverteilung.

    NumPy-vektorisiert für Batch-Berechnungen.
    Verwendet die Abramowitz-Stegun Approximation für hohe Genauigkeit.
    """
    x = np.asarray(x)

    # Abramowitz-Stegun Koeffizienten
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    sign = np.where(x >= 0, 1.0, -1.0)
    x_abs = np.abs(x) / np.sqrt(2.0)

    t = 1.0 / (1.0 + p * x_abs)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * np.exp(-x_abs * x_abs)

    result = 0.5 * (1.0 + sign * y)

    # Return scalar if input was scalar
    return float(result) if result.ndim == 0 else result


def _norm_pdf_np(x: FloatOrArray) -> FloatOrArray:
    """
    Probability Density Function der Standardnormalverteilung.
    NumPy-vektorisiert.
    """
    x = np.asarray(x)
    result = np.exp(-0.5 * x * x) / _SQRT_2PI
    return float(result) if result.ndim == 0 else result


# Legacy scalar functions (for backwards compatibility)
def _norm_cdf(x: float) -> float:
    """Scalar CDF - verwendet NumPy intern."""
    return float(_norm_cdf_np(x))


def _norm_pdf(x: float) -> float:
    """Scalar PDF - verwendet NumPy intern."""
    return float(_norm_pdf_np(x))


# =============================================================================
# BLACK-SCHOLES FORMULAS - NumPy Vectorized
# =============================================================================

def _calculate_d1_d2_np(
    S: FloatOrArray,
    K: FloatOrArray,
    T: FloatOrArray,
    r: FloatOrArray,
    sigma: FloatOrArray
) -> Tuple[FloatOrArray, FloatOrArray]:
    """
    Berechnet d1 und d2 Parameter für Black-Scholes.
    NumPy-vektorisiert für Batch-Berechnungen.

    Args:
        S: Aktienkurs (Spot) - scalar oder array
        K: Strike-Preis - scalar oder array
        T: Zeit bis Verfall in Jahren - scalar oder array
        r: Risikofreier Zinssatz (annualisiert) - scalar oder array
        sigma: Volatilität (annualisiert) - scalar oder array

    Returns:
        Tuple von (d1, d2) - scalars oder arrays
    """
    S = np.asarray(S, dtype=np.float64)
    K = np.asarray(K, dtype=np.float64)
    T = np.asarray(T, dtype=np.float64)
    r = np.asarray(r, dtype=np.float64)
    sigma = np.asarray(sigma, dtype=np.float64)

    # Handle edge cases with masking
    valid = (T > 0) & (sigma > 0)

    # Initialize with zeros
    d1 = np.zeros_like(S + K + T + r + sigma, dtype=np.float64)
    d2 = np.zeros_like(d1)

    if np.any(valid):
        sqrt_T = np.sqrt(np.where(valid, T, 1.0))  # Avoid sqrt(0)
        sigma_safe = np.where(valid, sigma, 1.0)   # Avoid div by zero

        d1_calc = (np.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma_safe * sqrt_T)
        d2_calc = d1_calc - sigma_safe * sqrt_T

        d1 = np.where(valid, d1_calc, 0.0)
        d2 = np.where(valid, d2_calc, 0.0)

    # Return scalars if inputs were scalars
    if d1.ndim == 0:
        return (float(d1), float(d2))
    return (d1, d2)


def _calculate_d1_d2(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float
) -> Tuple[float, float]:
    """Legacy scalar version - verwendet NumPy intern."""
    if T <= 0 or sigma <= 0:
        return (0.0, 0.0)
    return _calculate_d1_d2_np(S, K, T, r, sigma)


def black_scholes_call_np(
    S: FloatOrArray,
    K: FloatOrArray,
    T: FloatOrArray,
    r: FloatOrArray,
    sigma: FloatOrArray
) -> FloatOrArray:
    """
    Black-Scholes Preis für europäische Call Option.
    NumPy-vektorisiert für Batch-Berechnungen.

    Args:
        S: Aktienkurs (Spot) - scalar oder array
        K: Strike-Preis - scalar oder array
        T: Zeit bis Verfall in Jahren - scalar oder array
        r: Risikofreier Zinssatz (annualisiert) - scalar oder array
        sigma: Volatilität (annualisiert) - scalar oder array

    Returns:
        Call-Optionspreis(e)
    """
    S = np.asarray(S, dtype=np.float64)
    K = np.asarray(K, dtype=np.float64)
    T = np.asarray(T, dtype=np.float64)
    r = np.asarray(r, dtype=np.float64)
    sigma = np.asarray(sigma, dtype=np.float64)

    # Mask für gültige T > 0
    expired = T <= 0

    # Intrinsic value für expired options
    intrinsic = np.maximum(0, S - K)

    # Berechne d1, d2 für nicht-expired
    d1, d2 = _calculate_d1_d2_np(S, K, np.maximum(T, 1e-10), r, sigma)

    # Black-Scholes Formula
    call_price = S * _norm_cdf_np(d1) - K * np.exp(-r * T) * _norm_cdf_np(d2)
    call_price = np.maximum(0, call_price)

    # Kombiniere expired und non-expired
    result = np.where(expired, intrinsic, call_price)

    return float(result) if result.ndim == 0 else result


def black_scholes_put_np(
    S: FloatOrArray,
    K: FloatOrArray,
    T: FloatOrArray,
    r: FloatOrArray,
    sigma: FloatOrArray
) -> FloatOrArray:
    """
    Black-Scholes Preis für europäische Put Option.
    NumPy-vektorisiert für Batch-Berechnungen.

    Args:
        S: Aktienkurs (Spot) - scalar oder array
        K: Strike-Preis - scalar oder array
        T: Zeit bis Verfall in Jahren - scalar oder array
        r: Risikofreier Zinssatz (annualisiert) - scalar oder array
        sigma: Volatilität (annualisiert) - scalar oder array

    Returns:
        Put-Optionspreis(e)
    """
    S = np.asarray(S, dtype=np.float64)
    K = np.asarray(K, dtype=np.float64)
    T = np.asarray(T, dtype=np.float64)
    r = np.asarray(r, dtype=np.float64)
    sigma = np.asarray(sigma, dtype=np.float64)

    # Mask für gültige T > 0
    expired = T <= 0

    # Intrinsic value für expired options
    intrinsic = np.maximum(0, K - S)

    # Berechne d1, d2 für nicht-expired
    d1, d2 = _calculate_d1_d2_np(S, K, np.maximum(T, 1e-10), r, sigma)

    # Black-Scholes Formula
    put_price = K * np.exp(-r * T) * _norm_cdf_np(-d2) - S * _norm_cdf_np(-d1)
    put_price = np.maximum(0, put_price)

    # Kombiniere expired und non-expired
    result = np.where(expired, intrinsic, put_price)

    return float(result) if result.ndim == 0 else result


def black_scholes_call(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float
) -> float:
    """Black-Scholes Call - scalar wrapper."""
    return float(black_scholes_call_np(S, K, T, r, sigma))


def black_scholes_put(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float
) -> float:
    """Black-Scholes Put - scalar wrapper."""
    return float(black_scholes_put_np(S, K, T, r, sigma))


def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "P"
) -> float:
    """
    Black-Scholes Preis für Call oder Put.

    Args:
        S: Aktienkurs
        K: Strike-Preis
        T: Zeit bis Verfall in Jahren
        r: Risikofreier Zinssatz
        sigma: Volatilität
        option_type: "C" für Call, "P" für Put

    Returns:
        Optionspreis
    """
    if option_type.upper() in ("C", "CALL"):
        return black_scholes_call(S, K, T, r, sigma)
    else:
        return black_scholes_put(S, K, T, r, sigma)


# =============================================================================
# GREEKS
# =============================================================================

@dataclass
class Greeks:
    """Options Greeks"""
    delta: float
    gamma: float
    theta: float  # Per Tag
    vega: float   # Per 1% IV Änderung
    rho: float


def black_scholes_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "P"
) -> Greeks:
    """
    Berechnet alle Greeks für eine Option.

    Args:
        S: Aktienkurs
        K: Strike-Preis
        T: Zeit bis Verfall in Jahren
        r: Risikofreier Zinssatz
        sigma: Volatilität
        option_type: "C" für Call, "P" für Put

    Returns:
        Greeks Objekt
    """
    if T <= 0:
        # At expiration
        is_call = option_type.upper() in ("C", "CALL")
        itm = (S > K) if is_call else (S < K)
        return Greeks(
            delta=1.0 if (is_call and itm) else (-1.0 if (not is_call and itm) else 0.0),
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            rho=0.0
        )

    d1, d2 = _calculate_d1_d2(S, K, T, r, sigma)
    sqrt_T = math.sqrt(T)

    # Common terms
    pdf_d1 = _norm_pdf(d1)
    discount = math.exp(-r * T)

    # Gamma (same for call and put)
    gamma = pdf_d1 / (S * sigma * sqrt_T)

    # Vega (same for call and put, per 1% IV change)
    vega = S * pdf_d1 * sqrt_T / 100

    is_call = option_type.upper() in ("C", "CALL")

    if is_call:
        # Call Greeks
        delta = _norm_cdf(d1)
        theta = (
            -S * pdf_d1 * sigma / (2 * sqrt_T)
            - r * K * discount * _norm_cdf(d2)
        ) / 365  # Per day
        rho = K * T * discount * _norm_cdf(d2) / 100  # Per 1% rate change
    else:
        # Put Greeks
        delta = _norm_cdf(d1) - 1
        theta = (
            -S * pdf_d1 * sigma / (2 * sqrt_T)
            + r * K * discount * _norm_cdf(-d2)
        ) / 365  # Per day
        rho = -K * T * discount * _norm_cdf(-d2) / 100  # Per 1% rate change

    return Greeks(
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho
    )


# =============================================================================
# IMPLIED VOLATILITY
# =============================================================================

def implied_volatility(
    option_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str = "P",
    max_iterations: int = 100,
    tolerance: float = 1e-6
) -> Optional[float]:
    """
    Berechnet Implied Volatility mittels Newton-Raphson.

    Args:
        option_price: Marktpreis der Option
        S: Aktienkurs
        K: Strike-Preis
        T: Zeit bis Verfall in Jahren
        r: Risikofreier Zinssatz
        option_type: "C" für Call, "P" für Put
        max_iterations: Max Iterationen
        tolerance: Konvergenz-Toleranz

    Returns:
        Implied Volatility oder None wenn nicht konvergiert
    """
    if T <= 0 or option_price <= 0:
        return None

    # Initial guess based on option price
    sigma = 0.25  # Start with 25% IV

    for _ in range(max_iterations):
        price = black_scholes_price(S, K, T, r, sigma, option_type)
        diff = price - option_price

        if abs(diff) < tolerance:
            return sigma

        # Vega for Newton-Raphson step
        d1, _ = _calculate_d1_d2(S, K, T, r, sigma)
        vega = S * _norm_pdf(d1) * math.sqrt(T)

        if vega < 1e-10:
            # Vega too small, try different approach
            if diff > 0:
                sigma *= 0.8
            else:
                sigma *= 1.2
            continue

        # Newton-Raphson step
        sigma = sigma - diff / vega

        # Bounds check
        if sigma <= 0.001:
            sigma = 0.001
        if sigma > 5.0:  # 500% IV cap
            sigma = 5.0

    logger.warning(f"IV did not converge for price={option_price}, S={S}, K={K}, T={T}")
    return None


# =============================================================================
# DELTA-BASED STRIKE FINDER
# =============================================================================

def find_strike_for_delta(
    target_delta: float,
    S: float,
    T: float,
    sigma: float,
    r: float = 0.05,
    option_type: str = "P",
    max_iterations: int = 50,
    tolerance: float = 0.001
) -> Optional[float]:
    """
    Findet den Strike für ein gegebenes Ziel-Delta mittels Bisection.

    Für Put-Optionen:
    - Delta ist negativ (typisch -0.05 bis -0.50)
    - Niedrigerer Strike → kleineres (mehr negatives) Delta
    - Höherer Strike → größeres (weniger negatives) Delta

    Args:
        target_delta: Ziel-Delta (z.B. -0.20 für Short Put, -0.05 für Long Put)
        S: Aktueller Aktienkurs
        T: Zeit bis Verfall in Jahren
        sigma: Implizite Volatilität
        r: Risikofreier Zinssatz (default 0.05)
        option_type: "P" für Put, "C" für Call
        max_iterations: Maximale Iterationen
        tolerance: Delta-Toleranz

    Returns:
        Strike-Preis oder None bei Fehler

    Example:
        # Finde Strike für Short Put mit Delta -0.20 bei $100 Aktie
        short_strike = find_strike_for_delta(-0.20, 100, 60/365, 0.25)
        # -> ca. $95 (5% OTM)

        # Finde Strike für Long Put mit Delta -0.05
        long_strike = find_strike_for_delta(-0.05, 100, 60/365, 0.25)
        # -> ca. $85 (15% OTM)
    """
    if T <= 0 or sigma <= 0 or S <= 0:
        return None

    is_put = option_type.upper() in ("P", "PUT")

    # Suchbereich für Strike: 50% bis 150% des Aktienkurses
    low_strike = S * 0.50
    high_strike = S * 1.50

    # Für Puts: Delta ist negativ (-1 bis 0)
    # Höherer Strike → mehr negatives Delta (z.B. -0.80, tiefer ITM)
    # Niedrigerer Strike → weniger negatives Delta (z.B. -0.05, weiter OTM)
    #
    # Beispiel bei S=100, T=60d, IV=25%:
    # K=110: Delta=-0.79 (deep ITM)
    # K=100: Delta=-0.45 (ATM)
    # K=90:  Delta=-0.12 (OTM)
    # K=80:  Delta=-0.01 (deep OTM)

    for _ in range(max_iterations):
        mid_strike = (low_strike + high_strike) / 2

        # Berechne Delta für mittleren Strike
        greeks = black_scholes_greeks(S, mid_strike, T, r, sigma, option_type)
        current_delta = greeks.delta

        # Prüfe Konvergenz
        if abs(current_delta - target_delta) < tolerance:
            # Runde auf Standard-Strike-Inkremente
            if S < 30:
                return round(mid_strike * 2) / 2  # $0.50 Inkremente
            elif S < 100:
                return round(mid_strike)  # $1 Inkremente
            else:
                return round(mid_strike / 5) * 5  # $5 Inkremente

        # Bisection: Für Puts (Delta ist negativ)
        if is_put:
            # target_delta z.B. -0.20
            # current_delta z.B. -0.45
            if current_delta < target_delta:
                # Delta ist zu negativ (-0.45 < -0.20) → Strike zu hoch → senken
                high_strike = mid_strike
            else:
                # Delta ist nicht negativ genug (-0.10 > -0.20) → Strike erhöhen
                low_strike = mid_strike
        else:
            # Für Calls (Delta ist positiv, 0 bis 1)
            if current_delta < target_delta:
                # Delta zu klein → Strike senken (mehr ITM)
                high_strike = mid_strike
            else:
                # Delta zu groß → Strike erhöhen (mehr OTM)
                low_strike = mid_strike

    # Rückfall: beste Schätzung zurückgeben
    mid_strike = (low_strike + high_strike) / 2
    if S < 30:
        return round(mid_strike * 2) / 2
    elif S < 100:
        return round(mid_strike)
    else:
        return round(mid_strike / 5) * 5


# =============================================================================
# PRICING RESULT
# =============================================================================

@dataclass
class PricingResult:
    """Ergebnis einer Spread-Bewertung"""
    # Prices
    short_put_price: float
    long_put_price: float
    net_credit: float  # Pro Aktie
    spread_width: float

    # Greeks (für den Spread)
    delta: float
    gamma: float
    theta: float  # Per Tag
    vega: float

    # Risiko-Metriken
    max_profit: float  # Pro Aktie
    max_loss: float    # Pro Aktie
    breakeven: float   # Aktienkurs

    # Probability metrics (simplified)
    prob_profit: float  # Geschätzte Gewinnwahrscheinlichkeit

    # Inputs (für Referenz)
    underlying_price: float
    short_strike: float
    long_strike: float
    days_to_expiry: int
    volatility: float

    @property
    def credit_pct(self) -> float:
        """Credit als % der Spread-Width"""
        if self.spread_width == 0:
            return 0.0
        return (self.net_credit / self.spread_width) * 100

    @property
    def risk_reward_ratio(self) -> float:
        """Risk/Reward Verhältnis"""
        if self.max_profit == 0:
            return 0.0
        return self.max_loss / self.max_profit


# =============================================================================
# OPTION PRICER CLASS
# =============================================================================

class OptionPricer:
    """
    Options-Pricer für Bull-Put-Spreads.

    Verwendet Black-Scholes für theoretische Preise.
    Kann mit historischen IV-Daten kalibriert werden.
    """

    def __init__(
        self,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.0
    ):
        """
        Args:
            risk_free_rate: Risikofreier Zinssatz (annualisiert)
            dividend_yield: Dividendenrendite (annualisiert)
        """
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield

    def price_put(
        self,
        underlying_price: float,
        strike: float,
        days_to_expiry: int,
        volatility: float
    ) -> Tuple[float, Greeks]:
        """
        Bewertet eine einzelne Put-Option.

        Args:
            underlying_price: Aktueller Aktienkurs
            strike: Strike-Preis
            days_to_expiry: Tage bis Verfall
            volatility: Implied Volatility (als Dezimalzahl, z.B. 0.25 für 25%)

        Returns:
            Tuple von (price, greeks)
        """
        T = days_to_expiry / 365.0

        # Adjust for dividends (simplified)
        S_adj = underlying_price * math.exp(-self.dividend_yield * T)

        price = black_scholes_put(S_adj, strike, T, self.risk_free_rate, volatility)
        greeks = black_scholes_greeks(S_adj, strike, T, self.risk_free_rate, volatility, "P")

        return (price, greeks)

    def price_call(
        self,
        underlying_price: float,
        strike: float,
        days_to_expiry: int,
        volatility: float
    ) -> Tuple[float, Greeks]:
        """
        Bewertet eine einzelne Call-Option.
        """
        T = days_to_expiry / 365.0
        S_adj = underlying_price * math.exp(-self.dividend_yield * T)

        price = black_scholes_call(S_adj, strike, T, self.risk_free_rate, volatility)
        greeks = black_scholes_greeks(S_adj, strike, T, self.risk_free_rate, volatility, "C")

        return (price, greeks)

    def price_bull_put_spread(
        self,
        underlying_price: float,
        short_strike: float,
        long_strike: float,
        days_to_expiry: int,
        volatility: float,
        short_iv: Optional[float] = None,
        long_iv: Optional[float] = None
    ) -> PricingResult:
        """
        Bewertet einen Bull-Put-Spread.

        Ein Bull-Put-Spread besteht aus:
        - Short Put (höherer Strike) - erhält Prämie
        - Long Put (niedrigerer Strike) - zahlt Prämie

        Args:
            underlying_price: Aktueller Aktienkurs
            short_strike: Strike des Short Put (höher)
            long_strike: Strike des Long Put (niedriger)
            days_to_expiry: Tage bis Verfall
            volatility: Base IV (wenn short_iv/long_iv nicht gesetzt)
            short_iv: IV für Short Put (optional, für Skew)
            long_iv: IV für Long Put (optional, für Skew)

        Returns:
            PricingResult mit allen Metriken
        """
        # Use specific IVs if provided (for volatility skew)
        iv_short = short_iv if short_iv is not None else volatility
        iv_long = long_iv if long_iv is not None else volatility

        # Price both legs
        short_price, short_greeks = self.price_put(
            underlying_price, short_strike, days_to_expiry, iv_short
        )
        long_price, long_greeks = self.price_put(
            underlying_price, long_strike, days_to_expiry, iv_long
        )

        # Spread metrics
        net_credit = short_price - long_price
        spread_width = short_strike - long_strike

        # Combined Greeks
        delta = short_greeks.delta - long_greeks.delta
        gamma = short_greeks.gamma - long_greeks.gamma
        theta = short_greeks.theta - long_greeks.theta  # Positive theta = good
        vega = short_greeks.vega - long_greeks.vega

        # Risk metrics
        max_profit = net_credit
        max_loss = spread_width - net_credit
        breakeven = short_strike - net_credit

        # Probability of profit (simplified using delta)
        # Delta of short put gives approximate probability of being ITM
        # Prob(profit) ≈ 1 - |delta of short put|
        prob_profit = 1.0 - abs(short_greeks.delta)

        return PricingResult(
            short_put_price=short_price,
            long_put_price=long_price,
            net_credit=net_credit,
            spread_width=spread_width,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven=breakeven,
            prob_profit=prob_profit,
            underlying_price=underlying_price,
            short_strike=short_strike,
            long_strike=long_strike,
            days_to_expiry=days_to_expiry,
            volatility=volatility
        )

    def estimate_iv_from_hv(
        self,
        historical_volatility: float,
        vix: Optional[float] = None,
        iv_premium: float = 1.25,  # Increased from 1.1 based on market comparison
        moneyness: Optional[float] = None,  # strike / spot for skew adjustment
    ) -> float:
        """
        Schätzt IV basierend auf historischer Volatilität.

        In der Regel ist IV > HV aufgrund des Volatilitäts-Risikoprämiums.
        Kalibriert basierend auf Vergleich mit 92k+ echten Marktpreisen.

        Args:
            historical_volatility: Historische Volatilität (z.B. 20-Tage)
            vix: Aktueller VIX (für Regime-Anpassung)
            iv_premium: Multiplikator für IV-Premium (default: 1.25 = 25%)
            moneyness: Optional strike/spot ratio für Volatility Skew

        Returns:
            Geschätzte IV
        """
        base_iv = historical_volatility * iv_premium

        # Adjust based on VIX regime
        if vix is not None:
            if vix > 30:
                # High vol environment: IV premium increases significantly
                base_iv *= 1.25
            elif vix > 25:
                base_iv *= 1.15
            elif vix > 20:
                base_iv *= 1.08
            elif vix < 15:
                # Low vol environment: IV premium decreases slightly
                base_iv *= 0.98

        # Volatility Skew Adjustment für OTM Puts
        # OTM Puts haben höhere IV als ATM (Put Skew)
        if moneyness is not None and moneyness < 1.0:
            # Je weiter OTM, desto höher die IV
            otm_distance = 1.0 - moneyness  # z.B. 0.10 für 90% moneyness
            # Skew factor: +2% IV pro 1% OTM (typischer Skew)
            skew_adjustment = 1.0 + (otm_distance * 2.0)
            base_iv *= skew_adjustment

        return base_iv

    def calculate_spread_value_at_price(
        self,
        underlying_price: float,
        short_strike: float,
        long_strike: float,
        days_to_expiry: int,
        volatility: float,
        initial_credit: float
    ) -> Tuple[float, float]:
        """
        Berechnet den aktuellen Wert eines Spreads und den P&L.

        Args:
            underlying_price: Aktueller Aktienkurs
            short_strike: Short Put Strike
            long_strike: Long Put Strike
            days_to_expiry: Verbleibende Tage
            volatility: Aktuelle IV
            initial_credit: Ursprünglich erhaltenes Credit

        Returns:
            Tuple von (current_spread_value, pnl_per_share)
        """
        result = self.price_bull_put_spread(
            underlying_price, short_strike, long_strike,
            days_to_expiry, volatility
        )

        # Current value to close = what we'd pay to buy back the spread
        current_value = result.short_put_price - result.long_put_price

        # P&L = initial credit - cost to close
        pnl = initial_credit - current_value

        return (current_value, pnl)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_pricer(risk_free_rate: float = 0.05) -> OptionPricer:
    """Erstellt einen OptionPricer mit Standard-Einstellungen."""
    return OptionPricer(risk_free_rate=risk_free_rate)


# =============================================================================
# SYMBOL CATEGORY IV ADJUSTMENTS
# =============================================================================

# Kalibriert mit 92k+ echten Marktpreisen
# Kategorien basierend auf beobachteten Pricing-Fehlern

# Sektor-ETFs - hohe IV-Prämien, aber weniger als Index-ETFs
# SMH war +56% zu hoch → Sektor-ETFs brauchen weniger Anpassung
SECTOR_ETF_SYMBOLS = {
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLB",
    "XLU", "XLRE", "XLC", "SMH",
}

# Index-ETFs - SEHR hohe IV-Prämien vs HV
# Nach Kalibrierung: SPY -21%, QQQ +12% → SPY braucht mehr, QQQ weniger
INDEX_ETF_SYMBOLS = {
    "SPY", "DIA",  # Large Cap Index - höchste Prämie
}

# QQQ und IWM separat - mittlere Prämie
TECH_INDEX_ETF_SYMBOLS = {
    "QQQ", "IWM",  # QQQ war +12%, IWM +27% zu hoch
}

# Andere ETFs
OTHER_ETF_SYMBOLS = {
    "TLT", "GLD", "SLV", "EEM", "EFA", "VXX", "UVXY",
}

# Mega-Cap Tech - hohe IV-Prämien (ähnlich wie ETFs)
# Beobachtung: GOOGL -40%, MSFT -34%, META -20% Fehler → brauchen +30-40%
MEGA_CAP_TECH_SYMBOLS = {
    "GOOGL", "GOOG", "MSFT", "AAPL", "META", "AMZN", "AVGO",
}

# High-IV Aktien (Volatile Tech, Crypto-adjacent, Meme)
# TSLA +9%, gut kalibriert
# NFLX -33% → NFLX raus aus High-IV, in separate Kategorie
HIGH_IV_SYMBOLS = {
    "TSLA", "NVDA", "AMD", "COIN", "MSTR",
    "MARA", "RIOT", "RIVN", "LCID", "NIO", "PLTR", "SNOW",
    "CRWD", "ZS", "NET", "MDB", "SHOP", "SQ", "SOFI",
    "ARM", "SMCI", "ROKU", "DKNG", "ABNB", "DASH", "UBER",
}

# Streaming/Media
STREAMING_SYMBOLS = {
    "NFLX", "DIS", "PARA", "WBD",
}

# Healthcare/Pharma
PHARMA_SYMBOLS = {
    "MRK", "ABBV", "BMY", "GILD", "VRTX", "REGN",
}

# Payment/Fintech
PAYMENT_SYMBOLS = {
    "MA", "V", "PYPL", "ADYEN",
}

# Individuelle Symbol-Anpassungen basierend auf 409k Datenpunkten
# Format: {symbol: multiplikator}
# Diese überschreiben die Kategorien
# Kalibriert am 2026-01-28 mit Iteration 5
SYMBOL_OVERRIDES = {
    # === INDEX ETFs ===
    # SPY: +1.8% → gut, leicht reduzieren
    "SPY": 1.58,
    # QQQ: -14.6% → braucht +12%
    "QQQ": 1.48,
    # IWM: -11.9% → braucht +10%
    "IWM": 1.40,

    # === MEGA CAP TECH ===
    # AAPL: -34.2% → braucht +30%
    "AAPL": 1.58,
    # GOOGL: -24.3% → braucht +20%
    "GOOGL": 1.60,
    "GOOG": 1.60,
    # META: +10.4% → leicht reduzieren
    "META": 1.18,
    # MSFT: -1.8% → gut
    "MSFT": 1.32,
    # NVDA: -27.1% → braucht +22%
    "NVDA": 1.25,
    # AVGO: +24.1% → reduzieren
    "AVGO": 1.02,

    # === FINANCIALS ===
    # GS: -12.8% mit 0.75 → braucht ~0.82
    "GS": 0.82,
    # JPM: +30.5% → reduzieren
    "JPM": 0.78,
    # BAC: -21.2% → erhöhen
    "BAC": 1.02,
    # C: +25.7% → reduzieren
    "C": 0.80,

    # === HIGH IV ===
    # TSLA: -4.0% → leicht erhöhen
    "TSLA": 1.08,
    # COIN: +35.3% → reduzieren
    "COIN": 0.72,
    # MSTR: +25.2% → reduzieren
    "MSTR": 0.80,
    # ARM: -25.9% → erhöhen
    "ARM": 1.30,

    # === STREAMING/MEDIA ===
    # NFLX: -40.3% → stark erhöhen
    "NFLX": 1.65,
    # DIS: war nicht in Top, default lassen

    # === PAYMENT ===
    # MA: -8.6% mit 1.10 → braucht ~1.15
    "MA": 1.15,
    # PYPL: -57.6% → stark erhöhen
    "PYPL": 1.60,

    # === PHARMA ===
    # LLY: -1.4% → gut
    "LLY": 1.02,
    # ABBV: +78.0% → stark reduzieren
    "ABBV": 0.55,
    # GILD: +61.5% → reduzieren
    "GILD": 0.60,
    # VRTX: +31.4% → reduzieren
    "VRTX": 0.82,
    # MRK: war nicht in Top, default lassen

    # === ANDERE GROSSE FEHLER ===
    # BKNG: -43.2% → stark erhöhen
    "BKNG": 1.55,
    # SPOT: -32.4% → erhöhen
    "SPOT": 1.40,
    # CRM: +52.3% → reduzieren
    "CRM": 0.65,
    # INTU: +48.1% → reduzieren
    "INTU": 0.68,
    # BLK: +67.4% → stark reduzieren
    "BLK": 0.52,
    # LMT: +77.2% → stark reduzieren
    "LMT": 0.50,
    # NOC: +126.0% → sehr stark reduzieren
    "NOC": 0.38,
    # CEG: +65.1% → reduzieren
    "CEG": 0.55,
    # INTC: +128.7% → sehr stark reduzieren
    "INTC": 0.40,
    # GE: +97.5% → sehr stark reduzieren
    "GE": 0.48,
    # BABA: +103.7% → sehr stark reduzieren
    "BABA": 0.45,
    # ACN: +105.5% → sehr stark reduzieren
    "ACN": 0.45,
    # VST: +118.9% → sehr stark reduzieren
    "VST": 0.42,
    # BIDU: +123.0% → sehr stark reduzieren
    "BIDU": 0.40,
}

# Financials - niedrigere IV-Prämien als erwartet
# Beobachtung: GS +31%, JPM +54% Fehler → brauchen -15-25%
FINANCIAL_SYMBOLS = {
    "GS", "JPM", "MS", "BAC", "C", "WFC", "USB", "PNC",
    "BLK", "SCHW", "AXP", "COF",
}

# Niedrige IV Aktien (Utilities, Staples, Defensive)
LOW_IV_SYMBOLS = {
    "JNJ", "PG", "KO", "PEP", "WMT", "MCD", "VZ", "T",
    "NEE", "SO", "DUK", "D", "AEP", "XEL", "ED",
    "CL", "KMB", "GIS", "K", "HSY", "CPB",
}


def get_symbol_iv_multiplier(symbol: str) -> float:
    """
    Gibt einen Symbol-spezifischen IV-Multiplikator zurück.

    Kalibriert mit 92k+ echten Marktpreisen (4. Iteration).

    Hierarchie:
    1. Individuelle Symbol-Overrides (für wichtige Symbole mit viel Daten)
    2. Kategorie-basierte Multiplikatoren
    3. Default

    Args:
        symbol: Ticker-Symbol

    Returns:
        Multiplikator (z.B. 1.55 für +55%)
    """
    symbol_upper = symbol.upper()

    # 1. Individuelle Overrides haben höchste Priorität
    if symbol_upper in SYMBOL_OVERRIDES:
        return SYMBOL_OVERRIDES[symbol_upper]

    # 2. Kategorie-basierte Multiplikatoren
    # Index-ETFs
    if symbol_upper in INDEX_ETF_SYMBOLS:
        return 1.55

    # Tech/Small-Cap Index ETFs
    if symbol_upper in TECH_INDEX_ETF_SYMBOLS:
        return 1.28

    # Sektor-ETFs
    if symbol_upper in SECTOR_ETF_SYMBOLS:
        return 1.12

    # Andere ETFs
    if symbol_upper in OTHER_ETF_SYMBOLS:
        return 1.25

    # Streaming/Media
    if symbol_upper in STREAMING_SYMBOLS:
        return 1.25

    # Pharma
    if symbol_upper in PHARMA_SYMBOLS:
        return 1.15

    # Payment
    if symbol_upper in PAYMENT_SYMBOLS:
        return 1.05

    # Mega-Cap Tech
    if symbol_upper in MEGA_CAP_TECH_SYMBOLS:
        return 1.28

    # High-IV volatile Aktien
    if symbol_upper in HIGH_IV_SYMBOLS:
        return 1.02

    # Financials
    if symbol_upper in FINANCIAL_SYMBOLS:
        return 0.82

    # Low-IV defensive
    if symbol_upper in LOW_IV_SYMBOLS:
        return 0.93

    # Default für alle anderen
    return 1.0


def estimate_iv_calibrated(
    historical_volatility: float,
    symbol: str,
    vix: Optional[float] = None,
    moneyness: Optional[float] = None,
    dte: Optional[int] = None,
) -> float:
    """
    Kalibrierte IV-Schätzung mit allen Anpassungen.

    Kalibriert mit 92k+ echten Marktpreisen. Ziel: minimaler Bias.

    Kombiniert:
    - Basis HV-zu-IV Premium (15%)
    - Symbol-Kategorie Anpassung (stark differenziert)
    - VIX-Regime Anpassung
    - Volatility Skew (OTM Puts) - moderat
    - DTE-Anpassung

    Args:
        historical_volatility: 20-Tage HV
        symbol: Ticker-Symbol
        vix: Aktueller VIX-Wert
        moneyness: strike / spot (< 1.0 für OTM puts)
        dte: Days to Expiration

    Returns:
        Kalibrierte IV-Schätzung
    """
    # Basis: HV * 1.15 (reduziert, weil Symbol-Multiplikatoren jetzt stärker sind)
    iv = historical_volatility * 1.15

    # Symbol-Kategorie zuerst anwenden (vollständig, nicht gedämpft)
    # Die Multiplikatoren wurden sorgfältig kalibriert
    symbol_mult = get_symbol_iv_multiplier(symbol)
    iv *= symbol_mult

    # VIX Regime (leicht moderater)
    if vix is not None:
        if vix > 30:
            iv *= 1.15
        elif vix > 25:
            iv *= 1.10
        elif vix > 20:
            iv *= 1.04
        elif vix < 15:
            iv *= 0.98

    # Volatility Skew für OTM Puts
    # Moderater Skew, abflachend bei sehr tiefem OTM
    if moneyness is not None and moneyness < 1.0:
        otm_distance = 1.0 - moneyness
        # Progressiver Skew: stärker bei leichtem OTM, schwächer bei tiefem OTM
        if otm_distance <= 0.10:
            # 0-10% OTM: +1.5% IV pro 1% OTM
            skew_factor = otm_distance * 1.5
        else:
            # >10% OTM: flacher (+0.8% pro 1% OTM für den Rest)
            skew_factor = 0.10 * 1.5 + (otm_distance - 0.10) * 0.8
        iv *= (1.0 + skew_factor)

    # DTE Adjustment (Term Structure)
    if dte is not None:
        if dte > 60:
            iv *= 1.02  # Längere Laufzeit = etwas höhere IV
        elif dte < 14:
            iv *= 0.98  # Kurze Laufzeit = IV crush nähert sich

    # Clamp
    return max(0.10, min(1.50, iv))  # Erhöhter Max für extreme Fälle


def quick_put_price(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    rate: float = 0.05
) -> float:
    """
    Schnelle Put-Preis Berechnung.

    Args:
        spot: Aktienkurs
        strike: Strike-Preis
        dte: Days to Expiration
        iv: Implied Volatility (z.B. 0.25 für 25%)
        rate: Risikofreier Zins (default 5%)

    Returns:
        Put-Preis
    """
    T = dte / 365.0
    return black_scholes_put(spot, strike, T, rate, iv)


def quick_spread_credit(
    spot: float,
    short_strike: float,
    long_strike: float,
    dte: int,
    iv: float,
    rate: float = 0.05
) -> float:
    """
    Schnelle Credit-Berechnung für Bull-Put-Spread.

    Returns:
        Net Credit pro Aktie
    """
    T = dte / 365.0
    short_price = black_scholes_put(spot, short_strike, T, rate, iv)
    long_price = black_scholes_put(spot, long_strike, T, rate, iv)
    return short_price - long_price


# =============================================================================
# BATCH/VECTORIZED FUNCTIONS (für Backtesting Performance)
# =============================================================================

def batch_spread_credit(
    spots: NDArray[np.float64],
    short_strikes: NDArray[np.float64],
    long_strikes: NDArray[np.float64],
    dtes: NDArray[np.float64],
    ivs: NDArray[np.float64],
    rate: float = 0.05
) -> NDArray[np.float64]:
    """
    Batch-Berechnung von Bull-Put-Spread Credits.

    Berechnet viele Spreads gleichzeitig mit NumPy-Vektorisierung.
    10-100x schneller als Schleifen für große Datasets.

    Args:
        spots: Array von Aktienkursen
        short_strikes: Array von Short-Put-Strikes
        long_strikes: Array von Long-Put-Strikes
        dtes: Array von Days-to-Expiration
        ivs: Array von Implied Volatilities
        rate: Risikofreier Zins (scalar)

    Returns:
        Array von Net Credits (short_put_price - long_put_price)

    Example:
        >>> spots = np.array([100, 105, 110])
        >>> shorts = np.array([95, 100, 105])
        >>> longs = np.array([90, 95, 100])
        >>> dtes = np.array([30, 30, 30])
        >>> ivs = np.array([0.25, 0.25, 0.25])
        >>> credits = batch_spread_credit(spots, shorts, longs, dtes, ivs)
    """
    T = dtes / 365.0
    short_prices = black_scholes_put_np(spots, short_strikes, T, rate, ivs)
    long_prices = black_scholes_put_np(spots, long_strikes, T, rate, ivs)
    return short_prices - long_prices


def batch_spread_pnl(
    entry_credits: NDArray[np.float64],
    current_spots: NDArray[np.float64],
    short_strikes: NDArray[np.float64],
    long_strikes: NDArray[np.float64],
    dtes_remaining: NDArray[np.float64],
    current_ivs: NDArray[np.float64],
    rate: float = 0.05
) -> NDArray[np.float64]:
    """
    Batch-Berechnung von Bull-Put-Spread P&Ls.

    Args:
        entry_credits: Array von ursprünglichen Credits bei Entry
        current_spots: Array von aktuellen Aktienkursen
        short_strikes: Array von Short-Put-Strikes
        long_strikes: Array von Long-Put-Strikes
        dtes_remaining: Array von verbleibenden DTE
        current_ivs: Array von aktuellen IVs
        rate: Risikofreier Zins

    Returns:
        Array von P&Ls pro Aktie (positiv = Gewinn)
    """
    current_credits = batch_spread_credit(
        current_spots, short_strikes, long_strikes,
        dtes_remaining, current_ivs, rate
    )
    # P&L = Entry Credit - Cost to Close
    # Cost to Close = Current Credit (was wir zahlen würden um zu schließen)
    return entry_credits - current_credits


def batch_historical_volatility(
    price_matrix: NDArray[np.float64],
    window: int = 20,
    annualize: bool = True
) -> NDArray[np.float64]:
    """
    Batch-Berechnung von Historical Volatility für mehrere Symbole.

    Args:
        price_matrix: 2D Array [symbols, days] von Schlusskursen
                     oder 1D Array [days] für ein Symbol
        window: Lookback-Window für HV (default: 20 Tage)
        annualize: Annualisieren mit sqrt(252)?

    Returns:
        Array von HV-Werten (ein pro Symbol wenn 2D, scalar wenn 1D)
    """
    prices = np.asarray(price_matrix, dtype=np.float64)

    if prices.ndim == 1:
        # Single symbol
        prices = prices.reshape(1, -1)

    # Log-Returns
    # prices[:, :-1] / prices[:, 1:] für returns über Zeit
    returns = np.log(prices[:, :-1] / prices[:, 1:])

    # Standardabweichung der letzten 'window' returns
    if returns.shape[1] >= window:
        recent_returns = returns[:, :window]
    else:
        recent_returns = returns

    hv = np.std(recent_returns, axis=1, ddof=1)

    if annualize:
        hv = hv * np.sqrt(252)

    return hv.squeeze() if hv.shape[0] == 1 else hv


def batch_estimate_iv(
    historical_vols: NDArray[np.float64],
    vix_values: Optional[NDArray[np.float64]] = None,
    iv_premium: float = 1.25,  # Increased from 1.1 based on market comparison
    moneyness: Optional[NDArray[np.float64]] = None,  # strike / spot for skew
) -> NDArray[np.float64]:
    """
    Batch-Schätzung von IV basierend auf HV und VIX.

    Kalibriert basierend auf Vergleich mit 92k+ echten Marktpreisen.

    Args:
        historical_vols: Array von Historical Volatilities
        vix_values: Optional Array von VIX-Werten (oder scalar)
        iv_premium: Basis-Multiplikator für IV-Premium (default: 1.25)
        moneyness: Optional Array von strike/spot ratios für Volatility Skew

    Returns:
        Array von geschätzten IVs
    """
    hv = np.asarray(historical_vols, dtype=np.float64)

    # Basis-IV mit Premium
    iv = hv * iv_premium

    # VIX-Adjustment wenn verfügbar
    if vix_values is not None:
        vix = np.asarray(vix_values, dtype=np.float64)

        # Regime-basierte Anpassung (kalibriert)
        # VIX > 30: High vol, +25%
        # VIX > 25: Elevated high, +15%
        # VIX > 20: Elevated, +8%
        # VIX < 15: Low vol, -2%
        adjustment = np.where(
            vix > 30, 1.25,
            np.where(vix > 25, 1.15,
                np.where(vix > 20, 1.08,
                    np.where(vix < 15, 0.98, 1.0)))
        )
        iv = iv * adjustment

    # Volatility Skew Adjustment für OTM Puts
    if moneyness is not None:
        money = np.asarray(moneyness, dtype=np.float64)
        # OTM puts (moneyness < 1.0) haben höhere IV
        otm_distance = np.maximum(0, 1.0 - money)  # 0 für ATM/ITM
        # Skew: +2% IV pro 1% OTM (typischer Put Skew)
        skew_adjustment = 1.0 + (otm_distance * 2.0)
        iv = iv * skew_adjustment

    # Clamp zu vernünftigen Werten
    return np.clip(iv, 0.10, 1.00)  # Increased max from 0.80 to 1.00
