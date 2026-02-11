#!/usr/bin/env python3
"""
Trade Simulator für Backtesting

Simuliert einzelne Trades mit realistischen Annahmen:
- Preis-Bewegungen basierend auf historischen Daten
- Spread-Pricing basierend auf Greeks
- Time Decay (Theta)
- Volatilitäts-Effekte

Verwendung:
    from src.backtesting import TradeSimulator, SimulatedTrade

    simulator = TradeSimulator()
    trade = simulator.simulate_trade(
        symbol="AAPL",
        entry_price=180.0,
        short_strike=175.0,
        long_strike=170.0,
        net_credit=1.50,
        dte=45,
        price_path=[180, 178, 175, 177, 180, 182]
    )
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from ...constants.trading_rules import EXIT_PROFIT_PCT_NORMAL

# Black-Scholes Integration für akkurates Spread-Pricing
try:
    from ..options.black_scholes import (
        BlackScholes,
    )
    from ..options.black_scholes import BullPutSpread as BSBullPutSpread
    from ..options.black_scholes import (
        OptionType,
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
        )

        _BLACK_SCHOLES_AVAILABLE = True
    except ImportError:
        _BLACK_SCHOLES_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class SimulatedTrade:
    """Ergebnis einer Trade-Simulation"""

    # Entry
    symbol: str
    entry_date: date
    entry_price: float
    short_strike: float
    long_strike: float
    net_credit: float
    dte: int
    contracts: int = 1

    # Exit
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_spread_value: Optional[float] = None
    exit_reason: Optional[str] = None

    # Metriken
    realized_pnl: float = 0.0
    max_unrealized_profit: float = 0.0
    max_unrealized_loss: float = 0.0
    days_held: int = 0

    # Tracking
    daily_values: List[Dict] = field(default_factory=list)

    @property
    def spread_width(self) -> float:
        return self.short_strike - self.long_strike

    @property
    def max_profit(self) -> float:
        return self.net_credit * 100 * self.contracts

    @property
    def max_loss(self) -> float:
        return (self.spread_width - self.net_credit) * 100 * self.contracts

    @property
    def break_even(self) -> float:
        return self.short_strike - self.net_credit

    @property
    def pnl_pct(self) -> float:
        if self.max_profit == 0:
            return 0.0
        return (self.realized_pnl / self.max_profit) * 100


class PriceSimulator:
    """
    Simuliert Preis-Bewegungen basierend auf historischen Daten.

    Nutzt Random Walk mit Drift und Volatilität aus historischen Daten.
    """

    @staticmethod
    def estimate_volatility(prices: List[float], window: int = 20) -> float:
        """
        Schätzt annualisierte Volatilität aus Preisen.

        Args:
            prices: Liste von Schlusskursen
            window: Fenster für Berechnung

        Returns:
            Annualisierte Volatilität (z.B. 0.25 = 25%)
        """
        if len(prices) < window + 1:
            return 0.25  # Default 25%

        returns = []
        for i in range(1, min(window + 1, len(prices))):
            if prices[i - 1] > 0:
                ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                returns.append(ret)

        if not returns:
            return 0.25

        # Tägliche Standardabweichung
        import statistics

        try:
            std = statistics.stdev(returns)
        except statistics.StatisticsError:
            return 0.25

        # Annualisieren (252 Handelstage)
        return std * math.sqrt(252)

    @staticmethod
    def generate_price_path(
        start_price: float,
        days: int,
        volatility: float = 0.25,
        drift: float = 0.0,
        seed: Optional[int] = None,
    ) -> List[float]:
        """
        Generiert einen Preispfad mit Geometric Brownian Motion.

        Args:
            start_price: Startpreis
            days: Anzahl Tage
            volatility: Annualisierte Volatilität
            drift: Annualisierte Drift (z.B. 0.08 = 8%)
            seed: Random Seed für Reproduzierbarkeit

        Returns:
            Liste von Preisen
        """
        import random

        if seed is not None:
            random.seed(seed)

        prices = [start_price]
        dt = 1 / 252  # Täglicher Zeitschritt

        for _ in range(days):
            z = random.gauss(0, 1)
            daily_return = (drift - 0.5 * volatility**2) * dt + volatility * math.sqrt(dt) * z
            new_price = prices[-1] * math.exp(daily_return)
            prices.append(new_price)

        return prices


class TradeSimulator:
    """
    Simuliert einzelne Bull-Put-Spread Trades.

    Features:
    - Realistische Spread-Pricing (Black-Scholes wenn verfügbar)
    - Time Decay Modellierung
    - Exit-Logik (Profit Target, Stop Loss, Expiration)
    """

    DEFAULT_CONFIG = {
        # Exit-Kriterien
        "profit_target_pct": EXIT_PROFIT_PCT_NORMAL,  # Exit bei 50% des Max Profits (PLAYBOOK)
        "stop_loss_pct": 100.0,  # Backtesting-Override: 1x Credit (PLAYBOOK: 200%)
        # Pricing
        "theta_decay_factor": 0.7,  # Theta beschleunigt sich
        "delta_sensitivity": 0.15,  # Delta des Short Puts
        # Kosten
        "slippage_pct": 1.0,
        "commission_per_contract": 1.30,
    }

    def __init__(self, config: Optional[Dict] = None) -> None:
        self.config = {**self.DEFAULT_CONFIG}
        if config:
            self.config.update(config)

    def simulate_trade(
        self,
        symbol: str,
        entry_price: float,
        short_strike: float,
        long_strike: float,
        net_credit: float,
        dte: int,
        price_path: List[float],
        contracts: int = 1,
        entry_date: Optional[date] = None,
        volatility: float = 0.25,
    ) -> SimulatedTrade:
        """
        Simuliert einen Trade über den gegebenen Preispfad.

        Args:
            symbol: Ticker Symbol
            entry_price: Preis bei Entry
            short_strike: Short Put Strike
            long_strike: Long Put Strike
            net_credit: Credit pro Aktie
            dte: Days to Expiration bei Entry
            price_path: Liste von Tagespreisen
            contracts: Anzahl Contracts
            entry_date: Optional Entry-Datum
            volatility: Implied Volatility für Black-Scholes Pricing (default 25%)

        Returns:
            SimulatedTrade mit allen Details
        """
        if entry_date is None:
            entry_date = date.today()

        trade = SimulatedTrade(
            symbol=symbol,
            entry_date=entry_date,
            entry_price=entry_price,
            short_strike=short_strike,
            long_strike=long_strike,
            net_credit=net_credit,
            dte=dte,
            contracts=contracts,
        )

        # Slippage auf Entry
        effective_credit = net_credit * (1 - self.config["slippage_pct"] / 100)

        max_profit = effective_credit * 100 * contracts
        max_loss = (short_strike - long_strike - effective_credit) * 100 * contracts
        commission = self.config["commission_per_contract"] * contracts * 2

        current_value = effective_credit * 100 * contracts
        max_unrealized_profit = 0.0
        max_unrealized_loss = 0.0

        # Simuliere jeden Tag
        for day, price in enumerate(price_path):
            remaining_dte = dte - day

            if remaining_dte <= 0:
                # Expiration
                trade.exit_date = entry_date + timedelta(days=day)
                trade.exit_price = price
                trade.exit_reason = "expiration"
                break

            # Berechne Spread-Wert (mit Black-Scholes wenn verfügbar)
            spread_value = self._calculate_spread_value(
                price,
                short_strike,
                long_strike,
                effective_credit,
                remaining_dte,
                dte,
                volatility=volatility,
            )

            # Unrealized P&L
            unrealized_pnl = (effective_credit * 100 - spread_value * 100) * contracts

            max_unrealized_profit = max(max_unrealized_profit, unrealized_pnl)
            max_unrealized_loss = min(max_unrealized_loss, unrealized_pnl)

            # Log daily values
            trade.daily_values.append(
                {
                    "day": day,
                    "price": price,
                    "spread_value": spread_value,
                    "unrealized_pnl": unrealized_pnl,
                    "dte": remaining_dte,
                }
            )

            # Check Exit Conditions
            exit_signal = self._check_exit(
                price,
                short_strike,
                long_strike,
                effective_credit,
                spread_value,
                unrealized_pnl,
                max_profit,
            )

            if exit_signal:
                trade.exit_date = entry_date + timedelta(days=day)
                trade.exit_price = price
                trade.exit_spread_value = spread_value
                trade.exit_reason = exit_signal
                trade.realized_pnl = unrealized_pnl - commission
                trade.days_held = day
                trade.max_unrealized_profit = max_unrealized_profit
                trade.max_unrealized_loss = max_unrealized_loss
                return trade

        # Falls kein Exit -> bei Expiration
        if trade.exit_date is None:
            final_price = price_path[-1] if price_path else entry_price
            trade.exit_date = entry_date + timedelta(days=dte)
            trade.exit_price = final_price
            trade.exit_reason = "expiration"
            trade.days_held = len(price_path)

            # Berechne finalen P&L
            if final_price >= short_strike:
                trade.realized_pnl = max_profit - commission
            elif final_price <= long_strike:
                trade.realized_pnl = -max_loss - commission
            else:
                intrinsic = short_strike - final_price
                trade.realized_pnl = (effective_credit - intrinsic) * 100 * contracts - commission

        trade.max_unrealized_profit = max_unrealized_profit
        trade.max_unrealized_loss = max_unrealized_loss

        return trade

    def _calculate_spread_value(
        self,
        current_price: float,
        short_strike: float,
        long_strike: float,
        initial_credit: float,
        remaining_dte: int,
        initial_dte: int,
        volatility: float = 0.25,
    ) -> float:
        """
        Berechnet den aktuellen Wert des Spreads.

        Verwendet Black-Scholes für akkurate Pricing wenn verfügbar,
        ansonsten Fallback auf vereinfachtes Modell.
        """
        spread_width = short_strike - long_strike

        # Methode 1: Black-Scholes für akkurates Pricing
        if _BLACK_SCHOLES_AVAILABLE and remaining_dte > 0:
            try:
                time_to_expiry = remaining_dte / 365.0

                # Erstelle Black-Scholes Objekte für beide Puts
                short_put = BlackScholes(
                    spot=current_price,
                    strike=short_strike,
                    time_to_expiry=time_to_expiry,
                    volatility=volatility,
                )
                long_put = BlackScholes(
                    spot=current_price,
                    strike=long_strike,
                    time_to_expiry=time_to_expiry,
                    volatility=volatility,
                )

                # Spread Value = Short Put - Long Put (wir sind short den spread)
                short_put_value = short_put.put_price()
                long_put_value = long_put.put_price()
                spread_value = short_put_value - long_put_value

                # Clamp to valid range
                return max(0, min(spread_width, spread_value))

            except Exception as e:
                logger.debug(f"Black-Scholes calculation failed, using fallback: {e}")
                # Fall through to simplified model

        # Methode 2: Vereinfachtes Modell (Fallback)
        # Intrinsic Value der Puts
        short_put_intrinsic = max(0, short_strike - current_price)
        long_put_intrinsic = max(0, long_strike - current_price)
        spread_intrinsic = short_put_intrinsic - long_put_intrinsic

        # Time Value (decays faster as expiration approaches)
        time_factor = remaining_dte / initial_dte if initial_dte > 0 else 0

        # Theta decay is not linear - accelerates near expiration
        theta_decay = time_factor ** self.config["theta_decay_factor"]

        # Initial time value (Credit - Intrinsic at entry)
        initial_time_value = initial_credit

        # Current time value
        remaining_time_value = initial_time_value * theta_decay

        # Moneyness adjustment
        if current_price < short_strike:
            moneyness = (short_strike - current_price) / short_strike
            delta_effect = moneyness * self.config["delta_sensitivity"] * spread_width
            remaining_time_value += delta_effect

        # Total spread value = Intrinsic + Time Value
        spread_value = spread_intrinsic + remaining_time_value

        # Clamp to valid range
        return max(0, min(spread_width, spread_value))

    def _check_exit(
        self,
        price: float,
        short_strike: float,
        long_strike: float,
        credit: float,
        spread_value: float,
        unrealized_pnl: float,
        max_profit: float,
    ) -> Optional[str]:
        """
        Prüft Exit-Bedingungen.

        Returns:
            Exit-Reason String oder None
        """
        # Profit Target: Exit wenn unrealisierter Gewinn >= X% des Max Profits
        profit_pct = (unrealized_pnl / max_profit) * 100 if max_profit > 0 else 0
        if profit_pct >= self.config["profit_target_pct"]:
            return "profit_target"

        # Stop Loss: Exit wenn Verlust >= X% des Credits
        # Loss = Spread Value - Credit (positiv wenn Spread teurer als Credit)
        # Korrektur: Loss-Prozent basiert auf dem Credit, nicht auf dem Spread-Wert
        # 100% Stop Loss = Verlust = Credit (break-even + Credit verloren)
        if credit > 0:
            loss = spread_value - credit
            # Nur triggern wenn tatsächlich Verlust (loss > 0)
            if loss > 0:
                loss_pct = (loss / credit) * 100
                if loss_pct >= self.config["stop_loss_pct"]:
                    return "stop_loss"

        # Deep ITM (Max Loss likely)
        if price <= long_strike:
            return "max_loss"

        return None

    def run_monte_carlo(
        self,
        symbol: str,
        entry_price: float,
        short_strike: float,
        long_strike: float,
        net_credit: float,
        dte: int,
        volatility: float = 0.25,
        drift: float = 0.0,
        num_simulations: int = 1000,
        contracts: int = 1,
    ) -> Dict:
        """
        Führt Monte-Carlo Simulation durch.

        Args:
            symbol: Ticker Symbol
            entry_price: Preis bei Entry
            short_strike: Short Put Strike
            long_strike: Long Put Strike
            net_credit: Credit pro Aktie
            dte: Days to Expiration
            volatility: Annualisierte Volatilität
            drift: Annualisierte Drift
            num_simulations: Anzahl Simulationen
            contracts: Anzahl Contracts

        Returns:
            Dict mit Statistiken
        """
        results = []

        for i in range(num_simulations):
            price_path = PriceSimulator.generate_price_path(
                start_price=entry_price,
                days=dte,
                volatility=volatility,
                drift=drift,
                seed=i,  # Reproduzierbar
            )

            trade = self.simulate_trade(
                symbol=symbol,
                entry_price=entry_price,
                short_strike=short_strike,
                long_strike=long_strike,
                net_credit=net_credit,
                dte=dte,
                price_path=price_path,
                contracts=contracts,
                volatility=volatility,  # Durchreichen für Black-Scholes Pricing
            )

            results.append(trade)

        # Statistiken
        pnls = [t.realized_pnl for t in results]
        winners = [t for t in results if t.realized_pnl > 0]
        losers = [t for t in results if t.realized_pnl < 0]

        import statistics

        return {
            "num_simulations": num_simulations,
            "volatility": volatility,
            "drift": drift,
            "win_rate": len(winners) / len(results) * 100 if results else 0,
            "avg_pnl": statistics.mean(pnls) if pnls else 0,
            "median_pnl": statistics.median(pnls) if pnls else 0,
            "std_pnl": statistics.stdev(pnls) if len(pnls) > 1 else 0,
            "max_pnl": max(pnls) if pnls else 0,
            "min_pnl": min(pnls) if pnls else 0,
            "avg_hold_days": statistics.mean(t.days_held for t in results) if results else 0,
            "outcome_distribution": {
                "profit_target": len([t for t in results if t.exit_reason == "profit_target"]),
                "stop_loss": len([t for t in results if t.exit_reason == "stop_loss"]),
                "max_loss": len([t for t in results if t.exit_reason == "max_loss"]),
                "expiration": len([t for t in results if t.exit_reason == "expiration"]),
            },
            "percentiles": {
                "p5": sorted(pnls)[int(len(pnls) * 0.05)] if pnls else 0,
                "p25": sorted(pnls)[int(len(pnls) * 0.25)] if pnls else 0,
                "p50": sorted(pnls)[int(len(pnls) * 0.50)] if pnls else 0,
                "p75": sorted(pnls)[int(len(pnls) * 0.75)] if pnls else 0,
                "p95": sorted(pnls)[int(len(pnls) * 0.95)] if pnls else 0,
            },
        }
