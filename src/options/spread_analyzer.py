#!/usr/bin/env python3
"""
Spread Analysis Module for Bull-Put-Spreads

Provides comprehensive analysis of Credit Spreads:
- Risk/Reward Calculation
- Break-Even Analysis
- P&L Scenarios (at various prices/times)
- Greeks-based Sensitivity
- Profit Probability

Usage:
    from src.spread_analyzer import SpreadAnalyzer, BullPutSpreadParams

    params = BullPutSpreadParams(
        symbol="AAPL",
        current_price=182.50,
        short_strike=175.0,
        long_strike=170.0,
        net_credit=1.25,
        dte=45,
        contracts=1
    )

    analyzer = SpreadAnalyzer()
    analysis = analyzer.analyze(params)
    print(analysis.summary())
"""

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from ..constants.trading_rules import (
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_STOP_LOSS_MULTIPLIER,
    SPREAD_MIN_CREDIT_PCT,
)

# Black-Scholes Integration for accurate pricing and Greeks
try:
    from .black_scholes import (
        BlackScholes,
    )
    from .black_scholes import BullPutSpread as BSBullPutSpread
    from .black_scholes import (
        OptionType,
        calculate_probability_otm,
    )

    _BLACK_SCHOLES_AVAILABLE = True
except ImportError:
    try:
        from src.options.black_scholes import (
            BlackScholes,
        )
        from src.options.black_scholes import BullPutSpread as BSBullPutSpread
        from src.options.black_scholes import (
            OptionType,
            calculate_probability_otm,
        )

        _BLACK_SCHOLES_AVAILABLE = True
    except ImportError:
        _BLACK_SCHOLES_AVAILABLE = False

logger = logging.getLogger(__name__)


class SpreadRiskLevel(Enum):
    """Risk classification of the spread"""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class BullPutSpreadParams:
    """Parameters for a Bull-Put-Spread"""

    symbol: str
    current_price: float
    short_strike: float
    long_strike: float
    net_credit: float  # Credit received per share
    dte: int  # Days to Expiration
    contracts: int = 1

    # Optional Greeks (if available)
    short_delta: Optional[float] = None
    short_theta: Optional[float] = None
    short_iv: Optional[float] = None
    long_delta: Optional[float] = None

    def __post_init__(self) -> None:
        """Validation of parameters"""
        if self.short_strike <= self.long_strike:
            raise ValueError("Short Strike must be higher than Long Strike")
        if self.net_credit <= 0:
            raise ValueError("Net Credit must be positive")
        if self.short_strike >= self.current_price:
            raise ValueError("Short Strike should be below current price (OTM)")


@dataclass
class PnLScenario:
    """A P&L scenario at a specific price"""

    price: float
    pnl_per_contract: float
    pnl_total: float
    pnl_percent: float  # % des max Profits
    status: str  # "max_profit", "profit", "loss", "max_loss"


@dataclass
class SpreadAnalysis:
    """Complete analysis of a Bull-Put-Spread"""

    # Base metrics
    symbol: str
    current_price: float
    short_strike: float
    long_strike: float
    spread_width: float
    net_credit: float
    contracts: int
    dte: int

    # Profit/Loss metrics
    max_profit: float  # Total (all contracts)
    max_loss: float  # Total (all contracts)
    break_even: float
    risk_reward_ratio: float  # Max Profit / Max Loss

    # Distances
    distance_to_short_strike: float  # in %
    distance_to_break_even: float  # in %
    buffer_to_loss: float  # in %

    # Probabilities (estimated)
    prob_profit: float  # P(OTM at expiration)
    prob_max_profit: float  # P(Price > Short Strike)
    expected_value: float  # EV = P(profit) * max_profit - P(loss) * avg_loss

    # Risk assessment
    risk_level: SpreadRiskLevel
    credit_to_width_ratio: float  # Credit as % of spread width

    # Greeks (if available)
    net_delta: Optional[float] = None
    net_theta: Optional[float] = None
    theta_per_day: Optional[float] = None

    # Scenarios
    scenarios: List[PnLScenario] = field(default_factory=list)

    # Recommendations
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """Formatted summary"""
        lines = [
            f"═══════════════════════════════════════════════════════════",
            f"  SPREAD-ANALYSE: {self.symbol}",
            f"═══════════════════════════════════════════════════════════",
            f"",
            f"  Current Price:      ${self.current_price:.2f}",
            f"  Short Strike:       ${self.short_strike:.2f} ({self.distance_to_short_strike:+.1f}% OTM)",
            f"  Long Strike:        ${self.long_strike:.2f}",
            f"  Spread Width:       ${self.spread_width:.2f}",
            f"  Net Credit:         ${self.net_credit:.2f} x {self.contracts}",
            f"  DTE:                {self.dte} days",
            f"",
            f"───────────────────────────────────────────────────────────",
            f"  PROFIT/LOSS",
            f"───────────────────────────────────────────────────────────",
            f"  Max Profit:         ${self.max_profit:,.2f} ({self.credit_to_width_ratio:.0f}% of width)",
            f"  Max Loss:           ${self.max_loss:,.2f}",
            f"  Risk/Reward:        1:{self.risk_reward_ratio:.2f}",
            f"  Break-Even:         ${self.break_even:.2f} ({self.distance_to_break_even:+.1f}%)",
            f"",
            f"───────────────────────────────────────────────────────────",
            f"  PROBABILITIES",
            f"───────────────────────────────────────────────────────────",
            f"  P(Profit):          {self.prob_profit:.0f}%",
            f"  P(Max Profit):      {self.prob_max_profit:.0f}%",
            f"  Expected Value:     ${self.expected_value:+.2f}",
            f"  Risk Level:         {self.risk_level.value.upper()}",
        ]

        if self.net_theta:
            lines.extend(
                [
                    f"",
                    f"───────────────────────────────────────────────────────────",
                    f"  GREEKS",
                    f"───────────────────────────────────────────────────────────",
                    f"  Net Delta:          {self.net_delta:.3f}" if self.net_delta else "",
                    (
                        f"  Net Theta:          ${self.theta_per_day:.2f}/day"
                        if self.theta_per_day
                        else ""
                    ),
                ]
            )

        if self.warnings:
            lines.extend(
                [
                    f"",
                    f"───────────────────────────────────────────────────────────",
                    f"  ⚠️  WARNINGS",
                    f"───────────────────────────────────────────────────────────",
                ]
            )
            for warning in self.warnings:
                lines.append(f"  • {warning}")

        if self.recommendations:
            lines.extend(
                [
                    f"",
                    f"───────────────────────────────────────────────────────────",
                    f"  💡 RECOMMENDATIONS",
                    f"───────────────────────────────────────────────────────────",
                ]
            )
            for rec in self.recommendations:
                lines.append(f"  • {rec}")

        lines.append(f"═══════════════════════════════════════════════════════════")

        return "\n".join(lines)

    def to_dict(self) -> Dict:
        """Converts to dictionary"""
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "short_strike": self.short_strike,
            "long_strike": self.long_strike,
            "spread_width": self.spread_width,
            "net_credit": self.net_credit,
            "contracts": self.contracts,
            "dte": self.dte,
            "max_profit": self.max_profit,
            "max_loss": self.max_loss,
            "break_even": self.break_even,
            "risk_reward_ratio": self.risk_reward_ratio,
            "distance_to_short_strike": self.distance_to_short_strike,
            "distance_to_break_even": self.distance_to_break_even,
            "buffer_to_loss": self.buffer_to_loss,
            "prob_profit": self.prob_profit,
            "prob_max_profit": self.prob_max_profit,
            "expected_value": self.expected_value,
            "risk_level": self.risk_level.value,
            "credit_to_width_ratio": self.credit_to_width_ratio,
            "net_delta": self.net_delta,
            "net_theta": self.net_theta,
            "theta_per_day": self.theta_per_day,
            "scenarios": [
                {
                    "price": s.price,
                    "pnl_per_contract": s.pnl_per_contract,
                    "pnl_total": s.pnl_total,
                    "pnl_percent": s.pnl_percent,
                    "status": s.status,
                }
                for s in self.scenarios
            ],
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


class SpreadAnalyzer:
    """
    Analyzes Bull-Put-Spreads with comprehensive metrics.

    Features:
    - Risk/Reward Calculation
    - Break-Even Analysis
    - P&L at various prices
    - Probability Estimation
    - Risk Assessment
    """

    # Configurable thresholds
    DEFAULT_CONFIG = {
        # Risk levels
        "low_risk_max_credit_pct": 20,  # <20% Credit/Width = Low Risk
        "moderate_risk_max_credit_pct": 30,
        "high_risk_max_credit_pct": 40,
        # Warning thresholds
        "min_buffer_pct": 5.0,  # Warning if buffer < 5%
        "min_credit_pct": SPREAD_MIN_CREDIT_PCT,  # Warning if credit < 10% of width (PLAYBOOK §2)
        "max_dte_for_theta": 60,  # Theta most effective under 60 DTE
        # Profit target recommendations
        "profit_target_conservative": EXIT_PROFIT_PCT_NORMAL,  # 50% of max profit (PLAYBOOK)
        "profit_target_standard": 65,
        "profit_target_aggressive": 80,
    }

    def __init__(self, config: Optional[Dict] = None) -> None:
        """
        Initializes the Analyzer.

        Args:
            config: Optional configuration (overrides defaults)
        """
        self.config = {**self.DEFAULT_CONFIG}
        if config:
            self.config.update(config)

    def analyze(self, params: BullPutSpreadParams) -> SpreadAnalysis:
        """
        Performs complete analysis of a Bull-Put-Spread.

        Args:
            params: Spread parameters

        Returns:
            SpreadAnalysis with all metrics
        """
        # Base calculations
        spread_width = params.short_strike - params.long_strike
        max_profit_per_contract = params.net_credit * 100
        max_loss_per_contract = (spread_width - params.net_credit) * 100

        max_profit = max_profit_per_contract * params.contracts
        max_loss = max_loss_per_contract * params.contracts

        break_even = params.short_strike - params.net_credit

        # Risk/Reward
        risk_reward = max_profit / max_loss if max_loss > 0 else 0

        # Distances
        distance_to_short = (
            (params.current_price - params.short_strike) / params.current_price * 100
        )
        distance_to_be = (params.current_price - break_even) / params.current_price * 100
        buffer_to_loss = distance_to_be  # Buffer until loss begins

        # Credit as % of spread width
        credit_to_width = (params.net_credit / spread_width) * 100

        # Estimate probabilities
        prob_profit, prob_max_profit = self._estimate_probabilities(params, break_even)

        # Expected Value
        avg_loss = max_loss * 0.5  # Simplified: average loss
        expected_value = prob_profit / 100 * max_profit - (1 - prob_profit / 100) * avg_loss

        # Risiko-Level bestimmen
        risk_level = self._assess_risk_level(credit_to_width, buffer_to_loss, params.dte)

        # Greeks berechnen (wenn verfügbar)
        net_delta, net_theta, theta_per_day = self._calculate_greeks(params)

        # P&L Szenarien generieren
        scenarios = self._generate_scenarios(params, break_even, max_profit, max_loss)

        # Warnungen und Empfehlungen
        warnings, recommendations = self._generate_advice(
            params, credit_to_width, buffer_to_loss, risk_level
        )

        return SpreadAnalysis(
            symbol=params.symbol,
            current_price=params.current_price,
            short_strike=params.short_strike,
            long_strike=params.long_strike,
            spread_width=spread_width,
            net_credit=params.net_credit,
            contracts=params.contracts,
            dte=params.dte,
            max_profit=max_profit,
            max_loss=max_loss,
            break_even=break_even,
            risk_reward_ratio=risk_reward,
            distance_to_short_strike=distance_to_short,
            distance_to_break_even=distance_to_be,
            buffer_to_loss=buffer_to_loss,
            prob_profit=prob_profit,
            prob_max_profit=prob_max_profit,
            expected_value=expected_value,
            risk_level=risk_level,
            credit_to_width_ratio=credit_to_width,
            net_delta=net_delta,
            net_theta=net_theta,
            theta_per_day=theta_per_day,
            scenarios=scenarios,
            warnings=warnings,
            recommendations=recommendations,
        )

    def calculate_pnl_at_price(
        self, params: BullPutSpreadParams, target_price: float
    ) -> Tuple[float, float, str]:
        """
        Berechnet P&L bei einem bestimmten Preis (bei Expiration).

        Args:
            params: Spread-Parameter
            target_price: Zielpreis bei Expiration

        Returns:
            Tuple von (P&L pro Contract, P&L Total, Status)
        """
        spread_width = params.short_strike - params.long_strike
        max_profit_per = params.net_credit * 100
        max_loss_per = (spread_width - params.net_credit) * 100

        if target_price >= params.short_strike:
            # Beide Puts OTM -> Max Profit
            pnl_per = max_profit_per
            status = "max_profit"
        elif target_price <= params.long_strike:
            # Beide Puts ITM -> Max Loss
            pnl_per = -max_loss_per
            status = "max_loss"
        else:
            # Zwischen den Strikes
            intrinsic_short = params.short_strike - target_price
            pnl_per = (params.net_credit - intrinsic_short) * 100
            status = "profit" if pnl_per > 0 else "loss"

        pnl_total = pnl_per * params.contracts
        return pnl_per, pnl_total, status

    def calculate_exit_price(self, params: BullPutSpreadParams, profit_target_pct: float) -> float:
        """
        Berechnet den Exit-Preis für ein bestimmtes Profit-Target.

        Args:
            params: Spread-Parameter
            profit_target_pct: Gewünschter Profit in % des Max Profits (z.B. 50)

        Returns:
            Preis für den Rückkauf (Debit)
        """
        target_profit = params.net_credit * (profit_target_pct / 100)
        exit_price = params.net_credit - target_profit
        return max(0, exit_price)  # Kann nicht negativ sein

    def _estimate_probabilities(
        self, params: BullPutSpreadParams, break_even: float
    ) -> Tuple[float, float]:
        """
        Berechnet Wahrscheinlichkeiten mit Black-Scholes oder Delta.

        Verwendet Black-Scholes für akkurate Berechnungen wenn verfügbar,
        ansonsten Fallback auf Delta-basierte Schätzung.

        Returns:
            Tuple von (P(Profit), P(Max Profit))
        """
        # Methode 1: Black-Scholes für akkurate Wahrscheinlichkeiten
        if _BLACK_SCHOLES_AVAILABLE:
            try:
                # IV aus Options-Daten oder Default 25%
                iv = params.short_iv if params.short_iv else 0.25
                time_to_expiry = params.dte / 365.0

                # P(Max Profit) = P(Preis > Short Strike bei Expiration)
                prob_max_profit = (
                    calculate_probability_otm(
                        spot=params.current_price,
                        strike=params.short_strike,
                        dte=params.dte,
                        volatility=iv,
                        option_type=OptionType.PUT,
                    )
                    * 100
                )

                # P(Profit) = P(Preis > Break-Even bei Expiration)
                prob_profit = (
                    calculate_probability_otm(
                        spot=params.current_price,
                        strike=break_even,
                        dte=params.dte,
                        volatility=iv,
                        option_type=OptionType.PUT,
                    )
                    * 100
                )

                return prob_profit, prob_max_profit
            except Exception as e:
                logger.warning(f"Black-Scholes probability calculation failed: {e}")
                # Fall through to Delta/heuristic method

        # Methode 2: Wenn Delta verfügbar, nutze es
        if params.short_delta:
            # P(OTM) ≈ 1 - |Delta|
            prob_max_profit = (1 - abs(params.short_delta)) * 100

            # P(Profit) ist etwas höher wegen Credit-Puffer
            buffer_pct = (params.short_strike - break_even) / params.short_strike * 100
            prob_profit = min(prob_max_profit + buffer_pct * 2, 99)
        else:
            # Methode 3: Heuristische Schätzung basierend auf OTM%
            otm_pct = (params.current_price - params.short_strike) / params.current_price * 100

            # Vereinfachte Schätzung: 10% OTM ≈ 75% P(profit)
            # 15% OTM ≈ 82%, 20% OTM ≈ 88%
            prob_max_profit = min(50 + otm_pct * 2.5, 95)
            prob_profit = min(prob_max_profit + 5, 98)

        return prob_profit, prob_max_profit

    def _assess_risk_level(
        self, credit_to_width: float, buffer_pct: float, dte: int
    ) -> SpreadRiskLevel:
        """Bewertet das Risiko-Level des Spreads"""
        score = 0

        # Credit/Width Ratio (höher = aggressiver)
        if credit_to_width < self.config["low_risk_max_credit_pct"]:
            score += 1
        elif credit_to_width < self.config["moderate_risk_max_credit_pct"]:
            score += 2
        elif credit_to_width < self.config["high_risk_max_credit_pct"]:
            score += 3
        else:
            score += 4

        # Buffer (niedriger = riskanter)
        if buffer_pct < 5:
            score += 2
        elif buffer_pct < 10:
            score += 1

        # DTE (kürzer = riskanter wegen Gamma)
        if dte < 14:
            score += 1
        elif dte < 30:
            score += 0.5

        # Risiko-Level bestimmen
        if score <= 2:
            return SpreadRiskLevel.LOW
        elif score <= 4:
            return SpreadRiskLevel.MODERATE
        elif score <= 6:
            return SpreadRiskLevel.HIGH
        else:
            return SpreadRiskLevel.VERY_HIGH

    def _calculate_greeks(
        self, params: BullPutSpreadParams
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Berechnet Net Greeks für den Spread.

        Verwendet Black-Scholes für akkurate Greeks wenn verfügbar,
        ansonsten Fallback auf übergebene Greeks oder Schätzungen.
        """
        net_delta = None
        net_theta = None
        theta_per_day = None

        # Methode 1: Black-Scholes für akkurate Greeks
        if _BLACK_SCHOLES_AVAILABLE:
            try:
                iv = params.short_iv if params.short_iv else 0.25
                time_to_expiry = params.dte / 365.0

                # Erstelle BullPutSpread für vollständige Greeks-Berechnung
                bs_spread = BSBullPutSpread(
                    spot=params.current_price,
                    short_strike=params.short_strike,
                    long_strike=params.long_strike,
                    time_to_expiry=time_to_expiry,
                    volatility=iv,
                )

                spread_greeks = bs_spread.greeks()
                net_delta = spread_greeks.net_delta
                net_theta = spread_greeks.net_theta
                theta_per_day = net_theta * params.contracts

                return net_delta, net_theta, theta_per_day
            except Exception as e:
                logger.warning(f"Black-Scholes Greeks calculation failed: {e}")
                # Fall through to manual calculation

        # Methode 2: Übergebene Greeks nutzen
        if params.short_delta and params.long_delta:
            # Short Put hat positives Delta (wir sind short)
            # Long Put hat negatives Delta (wir sind long)
            net_delta = -params.short_delta + params.long_delta

        if params.short_theta:
            # Theta ist positiv für Credit Spreads
            # Vereinfacht: Long Put Theta ≈ 60% des Short Put Theta
            long_theta_estimate = params.short_theta * 0.6
            net_theta = params.short_theta - long_theta_estimate
            theta_per_day = net_theta * params.contracts

        return net_delta, net_theta, theta_per_day

    def _generate_scenarios(
        self, params: BullPutSpreadParams, break_even: float, max_profit: float, max_loss: float
    ) -> List[PnLScenario]:
        """Generiert P&L Szenarien bei verschiedenen Preisen"""
        scenarios = []

        # Wichtige Preispunkte
        prices = [
            params.current_price * 1.05,  # +5%
            params.current_price,  # Aktuell
            params.current_price * 0.95,  # -5%
            params.short_strike,  # Short Strike (Break-Even für Max Profit)
            break_even,  # Break-Even
            params.long_strike,  # Long Strike (Max Loss)
            params.current_price * 0.85,  # -15%
        ]

        # Sortieren und Duplikate entfernen
        prices = sorted(set(prices), reverse=True)

        for price in prices:
            pnl_per, pnl_total, status = self.calculate_pnl_at_price(params, price)

            # P&L als % des Max Profits
            if max_profit > 0:
                pnl_pct = (pnl_total / max_profit) * 100
            else:
                pnl_pct = 0

            scenarios.append(
                PnLScenario(
                    price=round(price, 2),
                    pnl_per_contract=round(pnl_per, 2),
                    pnl_total=round(pnl_total, 2),
                    pnl_percent=round(pnl_pct, 1),
                    status=status,
                )
            )

        return scenarios

    def _generate_advice(
        self,
        params: BullPutSpreadParams,
        credit_to_width: float,
        buffer_pct: float,
        risk_level: SpreadRiskLevel,
    ) -> Tuple[List[str], List[str]]:
        """Generiert Warnungen und Empfehlungen"""
        warnings = []
        recommendations = []

        # Warnungen
        if buffer_pct < self.config["min_buffer_pct"]:
            warnings.append(f"Geringer Puffer ({buffer_pct:.1f}%) - Erhöhtes Risiko")

        if credit_to_width < self.config["min_credit_pct"]:
            warnings.append(
                f"Niedriger Credit ({credit_to_width:.0f}% der Width) - " "Schlechtes Risk/Reward"
            )

        if params.dte < 14:
            warnings.append(f"Kurze Laufzeit ({params.dte} Tage) - Hohes Gamma-Risiko")

        if risk_level == SpreadRiskLevel.VERY_HIGH:
            warnings.append("Sehr hohes Risiko - Position klein halten")

        # Empfehlungen
        if params.dte > 45:
            target = self.config["profit_target_conservative"]
            recommendations.append(
                f"Profit-Target: {target:.0f}% ({params.net_credit * target / 100:.2f}$)"
            )
        else:
            target = self.config["profit_target_standard"]
            recommendations.append(
                f"Profit-Target: {target:.0f}% ({params.net_credit * target / 100:.2f}$)"
            )

        exit_price = self.calculate_exit_price(params, target)
        recommendations.append(f"Exit bei Spread-Preis: ${exit_price:.2f}")

        # Stop-Loss Empfehlung
        stop_loss_price = params.net_credit * EXIT_STOP_LOSS_MULTIPLIER  # 200% des Credits
        recommendations.append(
            f"Stop-Loss bei Spread-Preis: ${stop_loss_price:.2f} ({EXIT_STOP_LOSS_MULTIPLIER:.0f}x Credit)"
        )

        if risk_level in [SpreadRiskLevel.HIGH, SpreadRiskLevel.VERY_HIGH]:
            recommendations.append("Position klein halten (max 2-3% des Portfolios)")

        return warnings, recommendations


def analyze_bull_put_spread(
    symbol: str,
    current_price: float,
    short_strike: float,
    long_strike: float,
    net_credit: float,
    dte: int,
    contracts: int = 1,
    short_delta: Optional[float] = None,
) -> SpreadAnalysis:
    """
    Convenience-Funktion für schnelle Spread-Analyse.

    Args:
        symbol: Ticker-Symbol
        current_price: Aktueller Aktienkurs
        short_strike: Strike des Short Puts
        long_strike: Strike des Long Puts
        net_credit: Erhaltener Credit pro Aktie
        dte: Days to Expiration
        contracts: Anzahl Contracts
        short_delta: Delta des Short Puts (optional)

    Returns:
        SpreadAnalysis mit allen Metriken
    """
    params = BullPutSpreadParams(
        symbol=symbol,
        current_price=current_price,
        short_strike=short_strike,
        long_strike=long_strike,
        net_credit=net_credit,
        dte=dte,
        contracts=contracts,
        short_delta=short_delta,
    )

    analyzer = SpreadAnalyzer()
    return analyzer.analyze(params)


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)

    print("\n=== Spread Analyzer Test ===\n")

    # Beispiel: AAPL Bull-Put-Spread
    params = BullPutSpreadParams(
        symbol="AAPL",
        current_price=182.50,
        short_strike=175.0,
        long_strike=170.0,
        net_credit=1.25,
        dte=45,
        contracts=2,
        short_delta=-0.25,
    )

    analyzer = SpreadAnalyzer()
    analysis = analyzer.analyze(params)

    print(analysis.summary())

    print("\n=== P&L Szenarien ===\n")
    for scenario in analysis.scenarios:
        print(
            f"  ${scenario.price:.2f}: ${scenario.pnl_total:+.2f} "
            f"({scenario.pnl_percent:+.0f}%) - {scenario.status}"
        )
