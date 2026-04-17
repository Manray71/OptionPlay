# OptionPlay - Position Sizing Module
# ====================================
"""
Intelligentes Position Sizing mit Kelly Criterion und VIX-Anpassung.

Features:
- Kelly Criterion Integration für optimale Positionsgröße
- VIX-basierte Skalierung (höhere Volatilität = kleinere Positionen)
- Risk-per-Trade Limits
- Portfolio-Level Exposure Management
- Reliability-Grade basierte Adjustments

Verwendung:
    from src.risk.position_sizing import PositionSizer, PositionSizeResult

    sizer = PositionSizer(
        account_size=100000,
        max_risk_per_trade=0.02,  # 2% max risk
        max_portfolio_risk=0.20,  # 20% total exposure
    )

    # Berechne Positionsgröße für einen Trade
    result = sizer.calculate_position_size(
        signal_score=8.5,
        win_rate=0.65,
        avg_win=150,
        avg_loss=100,
        max_loss_per_contract=500,
        vix_level=22,
        reliability_grade="B",
    )

    print(f"Contracts: {result.contracts}")
    print(f"Capital at risk: ${result.capital_at_risk}")
"""

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from ..constants.trading_rules import (
    VIX_ELEVATED_MAX,
    VIX_LOW_VOL_MAX,
    VIX_NO_TRADING_THRESHOLD,
    VIX_NORMAL_MAX,
)

logger = logging.getLogger(__name__)


class KellyMode(Enum):
    """Kelly Criterion Modus"""

    FULL = "full"  # Volle Kelly-Fraktion
    HALF = "half"  # Half-Kelly (konservativer)
    QUARTER = "quarter"  # Quarter-Kelly (sehr konservativ)
    FIXED = "fixed"  # Feste Prozent, kein Kelly


class VIXRegime(Enum):
    """VIX-basierte Markt-Regime"""

    LOW = "low"  # VIX < 15
    NORMAL = "normal"  # VIX 15-20
    ELEVATED = "elevated"  # VIX 20-30
    HIGH = "high"  # VIX 30-40
    EXTREME = "extreme"  # VIX > 40


@dataclass
class PositionSizeResult:
    """Ergebnis der Position Sizing Berechnung"""

    # Empfohlene Positionsgröße
    contracts: int
    capital_at_risk: float
    risk_per_contract: float

    # Kelly-basierte Metriken
    kelly_fraction: float
    kelly_optimal_contracts: float
    kelly_mode_used: KellyMode

    # Adjustments angewendet
    vix_adjustment: float  # Multiplikator (z.B. 0.8 = 20% Reduktion)
    reliability_adjustment: float
    score_adjustment: float

    # Limits
    max_contracts_by_risk: int
    max_contracts_by_capital: int
    limiting_factor: str

    # Risiko-Metriken
    expected_value: float
    risk_reward_ratio: float
    probability_of_profit: float

    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary"""
        return {
            "position": {
                "contracts": self.contracts,
                "capital_at_risk": round(self.capital_at_risk, 2),
                "risk_per_contract": round(self.risk_per_contract, 2),
            },
            "kelly": {
                "fraction": round(self.kelly_fraction * 100, 2),
                "optimal_contracts": round(self.kelly_optimal_contracts, 2),
                "mode": self.kelly_mode_used.value,
            },
            "adjustments": {
                "vix": round(self.vix_adjustment, 2),
                "reliability": round(self.reliability_adjustment, 2),
                "score": round(self.score_adjustment, 2),
            },
            "limits": {
                "max_by_risk": self.max_contracts_by_risk,
                "max_by_capital": self.max_contracts_by_capital,
                "limiting_factor": self.limiting_factor,
            },
            "metrics": {
                "expected_value": round(self.expected_value, 2),
                "risk_reward": round(self.risk_reward_ratio, 2),
                "prob_profit": round(self.probability_of_profit * 100, 1),
            },
        }


@dataclass
class PositionSizerConfig:
    """Konfiguration für Position Sizer"""

    # Basis-Limits
    max_risk_per_trade: float = 0.02  # 2% max pro Trade
    max_portfolio_risk: float = 0.20  # 20% max Gesamt-Exposure
    max_single_position_pct: float = 0.05  # 5% max in einem Trade

    # Kelly Einstellungen
    kelly_mode: KellyMode = KellyMode.HALF
    kelly_cap: float = 0.25  # Max 25% auch bei sehr gutem Edge

    # VIX Adjustment Faktoren (aus trading_rules.py)
    vix_low_threshold: float = VIX_LOW_VOL_MAX
    vix_normal_threshold: float = VIX_NORMAL_MAX
    vix_elevated_threshold: float = VIX_ELEVATED_MAX
    vix_high_threshold: float = VIX_NO_TRADING_THRESHOLD

    # VIX Skalierungsfaktoren (Multiplikatoren)
    vix_scale_low: float = 1.0  # Keine Reduktion bei low VIX
    vix_scale_normal: float = 1.0  # Keine Reduktion
    vix_scale_elevated: float = 0.75  # 25% Reduktion
    vix_scale_high: float = 0.50  # 50% Reduktion
    vix_scale_extreme: float = 0.25  # 75% Reduktion

    # Reliability Adjustments
    reliability_a_factor: float = 1.0  # Grade A: 100%
    reliability_b_factor: float = 0.85  # Grade B: 85%
    reliability_c_factor: float = 0.70  # Grade C: 70%
    reliability_d_factor: float = 0.50  # Grade D: 50%
    reliability_f_factor: float = 0.0  # Grade F: Kein Trade

    # Score-basierte Adjustments
    min_score_for_trade: float = 5.0
    score_full_size_threshold: float = 8.0  # Volle Größe ab Score 8
    score_scale_factor: float = 0.1  # 10% mehr pro Punkt über 5

    # Stop Loss Einstellungen (NEU - korrigiert von 200%)
    default_stop_loss_pct: float = 100.0  # 100% des Credits (1:1 Risk/Reward)
    max_stop_loss_pct: float = 150.0  # Max 150% des Credits

    # Notional-basierte Gesamt-Allokation (B.3.2-light)
    # Approximation der Margin-Belastung bis B.3.4 (IBKR reqAccountSummary) echte Margin liefert.
    # Echte Margin bindet ~70-80% des Notionals; 50% Notional-Grenze ist konservative Näherung.
    max_portfolio_allocation: float = 0.50  # 50% des Portfolios als Notional-Schranke

    # Buying Power pro Einzeltrade (B.3.5): IBKR-Konzept — Buying Power ≈ spread_width × 100
    max_buying_power_pct: float = 0.05  # 5% Buying Power max pro Trade

    @classmethod
    def from_yaml(cls) -> "PositionSizerConfig":
        """Lade YAML-Werte aus trading.yaml in PositionSizerConfig.

        Liest:
        - sizing.max_risk_per_trade_pct → max_risk_per_trade (pct → fraction)
        - sizing.max_portfolio_allocation → max_portfolio_allocation (pct → fraction)

        Alle anderen Felder behalten ihre Dataclass-Defaults.
        Eliminiert Drift zwischen trading.yaml und hartkodierten Dataclass-Defaults
        (analog OQ-2 fix für IV Rank ScanConfig).
        """
        from src.constants.trading_rules import (
            SIZING_MAX_BUYING_POWER_PCT,
            SIZING_MAX_PORTFOLIO_ALLOCATION,
            SIZING_MAX_RISK_PER_TRADE_PCT,
        )

        return cls(
            max_risk_per_trade=SIZING_MAX_RISK_PER_TRADE_PCT / 100.0,
            max_portfolio_allocation=SIZING_MAX_PORTFOLIO_ALLOCATION / 100.0,
            max_buying_power_pct=SIZING_MAX_BUYING_POWER_PCT / 100.0,
        )


class PositionSizer:
    """
    Intelligenter Position Sizer mit Kelly Criterion und VIX-Anpassung.

    Berechnet optimale Positionsgrößen basierend auf:
    1. Kelly Criterion (mathematisch optimale Größe)
    2. VIX-Level (Marktvolatilität)
    3. Signal Reliability Grade
    4. Signal Score
    5. Account und Risk Limits
    """

    def __init__(
        self,
        account_size: float,
        config: Optional[PositionSizerConfig] = None,
        current_exposure: float = 0.0,
    ) -> None:
        """
        Initialisiert den Position Sizer.

        Args:
            account_size: Kontogröße in USD
            config: Konfiguration (optional, verwendet Defaults)
            current_exposure: Aktuelles Risiko im Portfolio
        """
        self.account_size = account_size
        self.config = config or PositionSizerConfig.from_yaml()
        self.current_exposure = current_exposure

    def calculate_kelly_fraction(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """
        Berechnet die optimale Kelly-Fraktion.

        Kelly % = W - (1-W)/R

        Wobei:
        - W = Gewinnwahrscheinlichkeit (0-1)
        - R = Payoff Ratio (avg_win / avg_loss)

        Args:
            win_rate: Gewinnwahrscheinlichkeit (0-1)
            avg_win: Durchschnittlicher Gewinn in $
            avg_loss: Durchschnittlicher Verlust in $ (positiv)

        Returns:
            Kelly Fraktion (0-1, gecapped)
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0

        payoff_ratio = avg_win / avg_loss
        kelly = win_rate - ((1 - win_rate) / payoff_ratio)

        # Anwende Kelly Mode
        if self.config.kelly_mode == KellyMode.HALF:
            kelly *= 0.5
        elif self.config.kelly_mode == KellyMode.QUARTER:
            kelly *= 0.25
        elif self.config.kelly_mode == KellyMode.FIXED:
            kelly = self.config.max_risk_per_trade

        # Cap bei kelly_cap und 0
        return max(0.0, min(self.config.kelly_cap, kelly))

    def get_vix_regime(self, vix_level: float) -> VIXRegime:
        """Bestimmt das VIX-Regime basierend auf Level"""
        if vix_level < self.config.vix_low_threshold:
            return VIXRegime.LOW
        elif vix_level < self.config.vix_normal_threshold:
            return VIXRegime.NORMAL
        elif vix_level < self.config.vix_elevated_threshold:
            return VIXRegime.ELEVATED
        elif vix_level < self.config.vix_high_threshold:
            return VIXRegime.HIGH
        else:
            return VIXRegime.EXTREME

    def get_vix_adjustment(self, vix_level: float) -> float:
        """
        Berechnet den VIX-basierten Adjustment-Faktor.

        Höhere Volatilität = kleinere Positionen

        Args:
            vix_level: Aktueller VIX-Level

        Returns:
            Multiplikator (0.25-1.0)
        """
        regime = self.get_vix_regime(vix_level)

        adjustments = {
            VIXRegime.LOW: self.config.vix_scale_low,
            VIXRegime.NORMAL: self.config.vix_scale_normal,
            VIXRegime.ELEVATED: self.config.vix_scale_elevated,
            VIXRegime.HIGH: self.config.vix_scale_high,
            VIXRegime.EXTREME: self.config.vix_scale_extreme,
        }

        return adjustments.get(regime, 1.0)

    def get_reliability_adjustment(self, reliability_grade: Optional[str]) -> float:
        """
        Berechnet den Reliability-basierten Adjustment-Faktor.

        Bessere Grades = größere Positionen erlaubt

        Args:
            reliability_grade: "A", "B", "C", "D", "F" oder None

        Returns:
            Multiplikator (0.0-1.0)
        """
        if reliability_grade is None:
            return 0.7  # Default: konservativ bei unbekannter Reliability

        adjustments = {
            "A": self.config.reliability_a_factor,
            "B": self.config.reliability_b_factor,
            "C": self.config.reliability_c_factor,
            "D": self.config.reliability_d_factor,
            "F": self.config.reliability_f_factor,
        }

        return adjustments.get(reliability_grade.upper(), 0.5)

    def get_score_adjustment(self, signal_score: float) -> float:
        """
        Berechnet den Score-basierten Adjustment-Faktor.

        Höhere Scores = größere Positionen erlaubt

        Args:
            signal_score: Signal Score (0-16)

        Returns:
            Multiplikator (0.5-1.0)
        """
        if signal_score < self.config.min_score_for_trade:
            return 0.0  # Unter Minimum = kein Trade

        if signal_score >= self.config.score_full_size_threshold:
            return 1.0  # Volle Größe ab Threshold

        # Lineare Skalierung zwischen min und full threshold
        min_score = self.config.min_score_for_trade
        full_score = self.config.score_full_size_threshold

        # Base 0.5 + bis zu 0.5 mehr basierend auf Score
        score_pct = (signal_score - min_score) / (full_score - min_score)
        return 0.5 + (score_pct * 0.5)

    def calculate_position_size(
        self,
        max_loss_per_contract: float,
        win_rate: float = 0.65,
        avg_win: float = 100.0,
        avg_loss: float = 100.0,
        signal_score: float = 7.0,
        vix_level: float = 20.0,
        reliability_grade: Optional[str] = None,
        current_price: Optional[float] = None,
        contracts_multiplier: int = 100,
        current_notional: float = 0.0,
        spread_width: float = 0.0,
    ) -> PositionSizeResult:
        """
        Berechnet die optimale Positionsgröße.

        Args:
            max_loss_per_contract: Maximaler Verlust pro Contract in $
            win_rate: Historische Win Rate (0-1)
            avg_win: Durchschnittlicher Gewinn in $
            avg_loss: Durchschnittlicher Verlust in $
            signal_score: Signal Score (0-16)
            vix_level: Aktueller VIX Level
            reliability_grade: "A", "B", "C", "D", "F" oder None
            current_price: Aktueller Preis (optional, für Margin-Calc)
            contracts_multiplier: Contract Multiplier (default 100)

        Returns:
            PositionSizeResult mit allen Details
        """
        # 1. Berechne Kelly-Fraktion
        kelly_fraction = self.calculate_kelly_fraction(win_rate, avg_win, avg_loss)

        # 2. Berechne Adjustments
        vix_adjustment = self.get_vix_adjustment(vix_level)
        reliability_adjustment = self.get_reliability_adjustment(reliability_grade)
        score_adjustment = self.get_score_adjustment(signal_score)

        # 3. Kombinierter Adjustment
        total_adjustment = vix_adjustment * reliability_adjustment * score_adjustment

        # 4. Adjustierte Kelly-Fraktion
        adjusted_kelly = kelly_fraction * total_adjustment

        # 5. Berechne verfügbares Risiko-Budget
        available_risk = self.account_size * self.config.max_portfolio_risk - self.current_exposure
        available_risk = max(0, available_risk)

        # 6. Risiko für diesen Trade
        trade_risk_kelly = self.account_size * adjusted_kelly
        trade_risk_max = self.account_size * self.config.max_risk_per_trade
        trade_risk = min(trade_risk_kelly, trade_risk_max, available_risk)

        # 7. Berechne Contracts
        if max_loss_per_contract <= 0:
            contracts = 0
            limiting_factor = "invalid_max_loss"
        else:
            # Kelly-basierte optimale Contracts
            kelly_optimal = trade_risk / max_loss_per_contract

            # Max by Risk Limit
            max_by_risk = int(trade_risk_max / max_loss_per_contract)

            # Max by Capital (5% of account)
            max_capital_per_position = self.account_size * self.config.max_single_position_pct
            max_by_capital = int(max_capital_per_position / max_loss_per_contract)

            # Max by Notional Allocation (B.3.2-light)
            # Notional-basierte Approximation der Margin-Belastung bis B.3.4 (IBKR reqAccountSummary)
            if spread_width > 0 and self.config.max_portfolio_allocation > 0:
                notional_capacity = (
                    self.account_size * self.config.max_portfolio_allocation
                ) - current_notional
                notional_capacity = max(0.0, notional_capacity)
                max_new_notional_per_contract = spread_width * contracts_multiplier
                max_by_notional = (
                    int(notional_capacity / max_new_notional_per_contract)
                    if max_new_notional_per_contract > 0
                    else 0
                )
            else:
                max_by_notional = 9999  # No notional constraint when spread_width not provided

            # Max by Buying Power per Trade (B.3.5)
            # Buying Power für einen Bull-Put-Spread ≈ spread_width × 100 (gross notional)
            if spread_width > 0 and self.config.max_buying_power_pct > 0:
                buying_power_limit = self.account_size * self.config.max_buying_power_pct
                max_by_bp = int(buying_power_limit / (spread_width * contracts_multiplier))
            else:
                max_by_bp = 9999  # No BP constraint when spread_width not provided

            # Finaler Contract Count
            contracts = int(
                min(kelly_optimal, max_by_risk, max_by_capital, max_by_notional, max_by_bp)
            )
            contracts = max(0, contracts)

            # Bestimme limitierenden Faktor
            if contracts == 0:
                if notional_capacity <= 0 if spread_width > 0 else False:
                    limiting_factor = "max_portfolio_allocation"
                elif kelly_optimal < 1:
                    limiting_factor = "kelly_too_low"
                elif available_risk < max_loss_per_contract:
                    limiting_factor = "portfolio_risk_full"
                else:
                    limiting_factor = "insufficient_edge"
            elif contracts == max_by_notional and max_by_notional < 9999:
                limiting_factor = "max_portfolio_allocation"
            elif contracts == max_by_bp and max_by_bp < 9999:
                limiting_factor = "max_buying_power"
            elif contracts == int(kelly_optimal):
                limiting_factor = "kelly_optimal"
            elif contracts == max_by_risk:
                limiting_factor = "max_risk_per_trade"
            else:
                limiting_factor = "max_capital_per_position"

        # 8. Berechne Risiko-Metriken
        capital_at_risk = contracts * max_loss_per_contract
        expected_value = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0

        return PositionSizeResult(
            contracts=contracts,
            capital_at_risk=capital_at_risk,
            risk_per_contract=max_loss_per_contract,
            kelly_fraction=kelly_fraction,
            kelly_optimal_contracts=(
                trade_risk / max_loss_per_contract if max_loss_per_contract > 0 else 0
            ),
            kelly_mode_used=self.config.kelly_mode,
            vix_adjustment=vix_adjustment,
            reliability_adjustment=reliability_adjustment,
            score_adjustment=score_adjustment,
            max_contracts_by_risk=max_by_risk if max_loss_per_contract > 0 else 0,
            max_contracts_by_capital=max_by_capital if max_loss_per_contract > 0 else 0,
            limiting_factor=limiting_factor,
            expected_value=expected_value,
            risk_reward_ratio=risk_reward,
            probability_of_profit=win_rate,
        )

    def calculate_stop_loss(
        self,
        net_credit: float,
        spread_width: float,
        vix_level: float = 20.0,
        reliability_grade: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Berechnet empfohlenen Stop Loss basierend auf Kontext.

        WICHTIG: Korrigiert von 200% auf sinnvolle Levels (50-150%)

        Args:
            net_credit: Erhaltener Credit
            spread_width: Spread-Breite
            vix_level: Aktueller VIX
            reliability_grade: Signal Reliability

        Returns:
            Dict mit stop_loss_pct, stop_loss_price, max_loss
        """
        # Base Stop Loss: 100% des Credits (Break-Even auf Risk)
        base_stop_pct = self.config.default_stop_loss_pct

        # VIX Adjustment: In höherer Volatilität engere Stops
        vix_regime = self.get_vix_regime(vix_level)
        if vix_regime in [VIXRegime.HIGH, VIXRegime.EXTREME]:
            # Bei hoher Vol: engere Stops (50-75%)
            base_stop_pct = min(base_stop_pct, 75.0)
        elif vix_regime == VIXRegime.ELEVATED:
            # Bei erhöhter Vol: moderate Stops (75-100%)
            base_stop_pct = min(base_stop_pct, 100.0)

        # Reliability Adjustment: Bessere Signals = mehr Spielraum
        if reliability_grade in ["A", "B"]:
            # Gute Signals: etwas mehr Spielraum
            stop_pct = min(base_stop_pct * 1.2, self.config.max_stop_loss_pct)
        elif reliability_grade in ["D", "F"]:
            # Schlechte Signals: enger
            stop_pct = base_stop_pct * 0.75
        else:
            stop_pct = base_stop_pct

        # Berechne absoluten Stop Loss
        stop_loss_price = net_credit * (1 + stop_pct / 100)
        max_loss = stop_loss_price - net_credit

        # Cap bei Spread Width (kann nicht mehr als Max Loss verlieren)
        effective_max_loss = min(max_loss, spread_width - net_credit)

        return {
            "stop_loss_pct": round(stop_pct, 1),
            "stop_loss_price": round(stop_loss_price, 4),
            "max_loss": round(effective_max_loss, 2),
            "vix_regime": vix_regime.value,
            "risk_reward": (
                round(net_credit / effective_max_loss, 2) if effective_max_loss > 0 else 0
            ),
        }

    def update_exposure(self, delta: float) -> None:
        """
        Aktualisiert das aktuelle Portfolio-Exposure.

        Args:
            delta: Änderung (positiv = mehr Risiko, negativ = weniger)
        """
        self.current_exposure = max(0, self.current_exposure + delta)

    @property
    def remaining_capacity(self) -> float:
        """Verbleibendes Risiko-Budget in $"""
        max_risk = self.account_size * self.config.max_portfolio_risk
        return max(0, max_risk - self.current_exposure)

    @property
    def remaining_capacity_pct(self) -> float:
        """Verbleibendes Risiko-Budget in % des Accounts"""
        return (self.remaining_capacity / self.account_size) * 100


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def calculate_optimal_position(
    account_size: float,
    max_loss_per_contract: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    vix_level: float = 20.0,
    signal_score: float = 7.0,
    reliability_grade: Optional[str] = None,
) -> PositionSizeResult:
    """
    Convenience-Funktion für schnelle Position Sizing Berechnung.

    Args:
        account_size: Kontogröße
        max_loss_per_contract: Max Loss pro Contract
        win_rate: Win Rate (0-1)
        avg_win: Durchschnittlicher Gewinn
        avg_loss: Durchschnittlicher Verlust
        vix_level: VIX Level
        signal_score: Signal Score
        reliability_grade: Reliability Grade

    Returns:
        PositionSizeResult
    """
    sizer = PositionSizer(account_size)
    return sizer.calculate_position_size(
        max_loss_per_contract=max_loss_per_contract,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        signal_score=signal_score,
        vix_level=vix_level,
        reliability_grade=reliability_grade,
    )


def get_recommended_stop_loss(
    net_credit: float,
    spread_width: float,
    vix_level: float = 20.0,
) -> float:
    """
    Gibt empfohlenen Stop Loss Prozentsatz zurück.

    Args:
        net_credit: Erhaltener Credit
        spread_width: Spread-Breite
        vix_level: VIX Level

    Returns:
        Stop Loss als Prozent des Credits (z.B. 100.0 für 100%)
    """
    sizer = PositionSizer(100000)  # Account Size irrelevant für Stop Loss
    result = sizer.calculate_stop_loss(net_credit, spread_width, vix_level)
    return result["stop_loss_pct"]
