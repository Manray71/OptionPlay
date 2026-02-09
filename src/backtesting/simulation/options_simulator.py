#!/usr/bin/env python3
"""
Options Simulator für realistisches Backtesting
================================================

Simuliert Bull-Put-Spread P&L basierend auf:
1. Echten historischen Options-Daten (wenn verfügbar via Tradier)
2. Black-Scholes Pricing mit historischer/geschätzter IV

Verwendet für realistische Backtests:
- Theta-Decay über Zeit
- IV-Veränderungen (Mean Reversion, VIX-Korrelation)
- Bid-Ask-Spread Simulation
- Slippage-Modellierung

Verwendung:
    from src.backtesting.options_simulator import OptionsSimulator

    simulator = OptionsSimulator()

    # Spread-Eröffnung simulieren
    entry = simulator.simulate_entry(
        underlying_price=100,
        short_strike=95,
        long_strike=90,
        dte=45,
        iv=0.25
    )

    # P&L während der Laufzeit berechnen
    pnl = simulator.calculate_pnl(
        entry=entry,
        current_price=102,
        days_held=15,
        current_iv=0.22
    )
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Dict, List, Tuple
import math

import numpy as np
from numpy.typing import NDArray

from ...pricing import (
    OptionPricer,
    PricingResult,
    black_scholes_put_np,
    batch_spread_credit,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SpreadEntry:
    """Daten eines eröffneten Spreads"""
    symbol: str
    entry_date: date
    underlying_price: float

    # Strikes
    short_strike: float
    long_strike: float
    spread_width: float

    # Entry Pricing
    short_put_price: float
    long_put_price: float
    net_credit: float           # Pro Aktie, nach Slippage

    # Greeks at Entry
    entry_delta: float
    entry_theta: float

    # Configuration
    dte_at_entry: int
    expiry_date: date
    entry_iv: float

    # Contracts
    contracts: int
    commission: float

    # Calculated
    max_profit: float           # Total, nach Kommission
    max_loss: float             # Total, nach Kommission

    @property
    def gross_credit(self) -> float:
        """Credit vor Slippage"""
        return self.short_put_price - self.long_put_price

    @property
    def breakeven(self) -> float:
        """Breakeven-Preis"""
        return self.short_strike - self.net_credit


@dataclass
class SpreadSnapshot:
    """Momentaufnahme eines Spreads"""
    date: date
    underlying_price: float
    days_held: int
    dte_remaining: int

    # Current Pricing
    short_put_value: float
    long_put_value: float
    spread_value: float         # Cost to close

    # P&L
    unrealized_pnl: float       # Pro Aktie
    unrealized_pnl_total: float # Total
    pnl_pct: float              # % des Max Profits

    # Greeks
    current_delta: float
    current_theta: float

    # IV
    current_iv: float


@dataclass
class SimulatorConfig:
    """Konfiguration für den Options-Simulator"""
    # Risk-free rate
    risk_free_rate: float = 0.05

    # Slippage (% des Mid-Price)
    entry_slippage_pct: float = 1.0   # 1% beim Einstieg
    exit_slippage_pct: float = 1.5    # 1.5% beim Ausstieg (weniger Liquidität)

    # Bid-Ask Spread Schätzung (% des Options-Preises)
    bid_ask_pct: float = 5.0          # 5% typischer Bid-Ask

    # Commission
    commission_per_contract: float = 1.30

    # IV Dynamics
    iv_mean_reversion_speed: float = 0.05  # Tägliche Mean Reversion
    iv_vix_correlation: float = 0.7        # Korrelation zwischen Aktien-IV und VIX

    # Volatility Skew (OTM Puts haben höhere IV)
    put_skew_per_delta: float = 0.02  # +2% IV pro 0.1 Delta OTM


# =============================================================================
# OPTIONS SIMULATOR
# =============================================================================

class OptionsSimulator:
    """
    Simuliert Options-Preise und P&L für Backtesting.

    Verwendet Black-Scholes mit realistischen Anpassungen:
    - Volatility Skew
    - IV Mean Reversion
    - Slippage und Bid-Ask
    """

    def __init__(self, config: Optional[SimulatorConfig] = None) -> None:
        self.config = config or SimulatorConfig()
        self.pricer = OptionPricer(risk_free_rate=self.config.risk_free_rate)

    def simulate_entry(
        self,
        symbol: str,
        underlying_price: float,
        short_strike: float,
        long_strike: float,
        dte: int,
        iv: float,
        entry_date: Optional[date] = None,
        contracts: int = 1,
        vix: Optional[float] = None
    ) -> SpreadEntry:
        """
        Simuliert die Eröffnung eines Bull-Put-Spreads.

        Args:
            symbol: Ticker-Symbol
            underlying_price: Aktienkurs
            short_strike: Short Put Strike
            long_strike: Long Put Strike
            dte: Days to Expiration
            iv: Basis-IV (ATM)
            entry_date: Entry-Datum (default: heute)
            contracts: Anzahl Kontrakte
            vix: Aktueller VIX (für IV-Anpassung)

        Returns:
            SpreadEntry mit allen Details
        """
        entry_date = entry_date or date.today()
        expiry_date = entry_date + timedelta(days=dte)

        # IV-Anpassung für Skew (OTM Puts haben höhere IV)
        short_iv = self._adjust_iv_for_skew(iv, underlying_price, short_strike)
        long_iv = self._adjust_iv_for_skew(iv, underlying_price, long_strike)

        # Pricing
        result = self.pricer.price_bull_put_spread(
            underlying_price=underlying_price,
            short_strike=short_strike,
            long_strike=long_strike,
            days_to_expiry=dte,
            volatility=iv,
            short_iv=short_iv,
            long_iv=long_iv
        )

        # Slippage anwenden (wir verkaufen Short Put, kaufen Long Put)
        # Bei Entry: Wir erhalten weniger als Mid
        slippage_factor = 1 - (self.config.entry_slippage_pct / 100)
        net_credit = result.net_credit * slippage_factor

        # Commission
        commission = self.config.commission_per_contract * contracts * 2

        # Max Profit/Loss
        spread_width = short_strike - long_strike
        max_profit = (net_credit * 100 * contracts) - commission
        max_loss = ((spread_width - net_credit) * 100 * contracts) + commission

        return SpreadEntry(
            symbol=symbol,
            entry_date=entry_date,
            underlying_price=underlying_price,
            short_strike=short_strike,
            long_strike=long_strike,
            spread_width=spread_width,
            short_put_price=result.short_put_price,
            long_put_price=result.long_put_price,
            net_credit=net_credit,
            entry_delta=result.delta,
            entry_theta=result.theta,
            dte_at_entry=dte,
            expiry_date=expiry_date,
            entry_iv=iv,
            contracts=contracts,
            commission=commission,
            max_profit=max_profit,
            max_loss=max_loss
        )

    def calculate_snapshot(
        self,
        entry: SpreadEntry,
        current_date: date,
        current_price: float,
        current_iv: Optional[float] = None,
        vix: Optional[float] = None
    ) -> SpreadSnapshot:
        """
        Berechnet den aktuellen Stand eines Spreads.

        Args:
            entry: SpreadEntry von simulate_entry()
            current_date: Aktuelles Datum
            current_price: Aktueller Aktienkurs
            current_iv: Aktuelle IV (wenn None, wird geschätzt)
            vix: Aktueller VIX (für IV-Schätzung)

        Returns:
            SpreadSnapshot mit P&L und Greeks
        """
        days_held = (current_date - entry.entry_date).days
        dte_remaining = (entry.expiry_date - current_date).days

        # IV-Schätzung wenn nicht gegeben
        if current_iv is None:
            current_iv = self._estimate_iv_change(
                entry.entry_iv,
                days_held,
                vix
            )

        # IV für Skew anpassen
        short_iv = self._adjust_iv_for_skew(current_iv, current_price, entry.short_strike)
        long_iv = self._adjust_iv_for_skew(current_iv, current_price, entry.long_strike)

        # Bei Expiration: Intrinsic Value
        if dte_remaining <= 0:
            short_put_value = max(0, entry.short_strike - current_price)
            long_put_value = max(0, entry.long_strike - current_price)
            spread_value = short_put_value - long_put_value

            # P&L
            unrealized_pnl = entry.net_credit - spread_value
            current_delta = 0
            current_theta = 0
        else:
            # Aktuellen Spread-Wert berechnen
            result = self.pricer.price_bull_put_spread(
                underlying_price=current_price,
                short_strike=entry.short_strike,
                long_strike=entry.long_strike,
                days_to_expiry=dte_remaining,
                volatility=current_iv,
                short_iv=short_iv,
                long_iv=long_iv
            )

            short_put_value = result.short_put_price
            long_put_value = result.long_put_price
            spread_value = result.net_credit  # Cost to close

            # P&L = Initial Credit - Cost to Close
            unrealized_pnl = entry.net_credit - spread_value
            current_delta = result.delta
            current_theta = result.theta

        # Exit-Slippage einberechnen (wir würden mehr zahlen um zu schließen)
        if dte_remaining > 0:
            slippage_cost = spread_value * (self.config.exit_slippage_pct / 100)
            unrealized_pnl -= slippage_cost

        unrealized_pnl_total = unrealized_pnl * 100 * entry.contracts

        # P&L als % des Max Profits
        if entry.max_profit > 0:
            pnl_pct = (unrealized_pnl_total / entry.max_profit) * 100
        else:
            pnl_pct = 0

        return SpreadSnapshot(
            date=current_date,
            underlying_price=current_price,
            days_held=days_held,
            dte_remaining=max(0, dte_remaining),
            short_put_value=short_put_value,
            long_put_value=long_put_value,
            spread_value=spread_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_total=unrealized_pnl_total,
            pnl_pct=pnl_pct,
            current_delta=current_delta,
            current_theta=current_theta,
            current_iv=current_iv
        )

    def simulate_trade_path(
        self,
        entry: SpreadEntry,
        price_path: List[Tuple[date, float]],
        iv_path: Optional[List[Tuple[date, float]]] = None,
        vix_path: Optional[List[Tuple[date, float]]] = None
    ) -> List[SpreadSnapshot]:
        """
        Simuliert den kompletten Verlauf eines Trades.

        Args:
            entry: SpreadEntry
            price_path: Liste von (date, price) Tupeln
            iv_path: Optional Liste von (date, iv) Tupeln
            vix_path: Optional Liste von (date, vix) Tupeln

        Returns:
            Liste von SpreadSnapshot für jeden Tag
        """
        # Konvertiere zu Dicts für einfachen Lookup
        iv_dict = dict(iv_path) if iv_path else {}
        vix_dict = dict(vix_path) if vix_path else {}

        snapshots = []

        for current_date, current_price in price_path:
            # Skip if before entry
            if current_date < entry.entry_date:
                continue

            # Stop if after expiry
            if current_date > entry.expiry_date:
                break

            current_iv = iv_dict.get(current_date)
            vix = vix_dict.get(current_date)

            snapshot = self.calculate_snapshot(
                entry=entry,
                current_date=current_date,
                current_price=current_price,
                current_iv=current_iv,
                vix=vix
            )
            snapshots.append(snapshot)

        return snapshots

    def check_exit_conditions(
        self,
        snapshot: SpreadSnapshot,
        entry: SpreadEntry,
        profit_target_pct: float = 50.0,
        stop_loss_pct: float = 100.0,
        dte_exit_threshold: int = 7
    ) -> Optional[str]:
        """
        Prüft ob Exit-Bedingungen erfüllt sind.

        Args:
            snapshot: Aktueller SpreadSnapshot
            entry: Original SpreadEntry
            profit_target_pct: Profit Target als % des Max Profits
            stop_loss_pct: Stop Loss als % des Max Loss
            dte_exit_threshold: Exit wenn DTE < threshold

        Returns:
            Exit-Grund oder None wenn kein Exit
        """
        # Expiration
        if snapshot.dte_remaining <= 0:
            return "expiration"

        # Profit Target (basierend auf P&L % des Max Profits)
        if snapshot.pnl_pct >= profit_target_pct:
            return "profit_target"

        # Stop Loss
        # Verlust als % des Max Loss berechnen
        if snapshot.unrealized_pnl_total < 0:
            loss_pct = abs(snapshot.unrealized_pnl_total) / entry.max_loss * 100
            if loss_pct >= stop_loss_pct:
                return "stop_loss"

        # DTE Threshold (Gamma Risk)
        if snapshot.dte_remaining <= dte_exit_threshold:
            return "dte_threshold"

        # Short Strike Breach
        if snapshot.underlying_price < entry.short_strike:
            # ITM - erhöhtes Risiko
            itm_amount = entry.short_strike - snapshot.underlying_price
            if itm_amount >= entry.spread_width * 0.5:
                return "deep_itm"

        return None

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _adjust_iv_for_skew(
        self,
        base_iv: float,
        underlying_price: float,
        strike: float
    ) -> float:
        """
        Passt IV für Volatility Skew an.

        OTM Puts haben typischerweise höhere IV (Skew/Smile).
        """
        moneyness = strike / underlying_price

        if moneyness < 1.0:
            # OTM Put - höhere IV
            otm_pct = (1.0 - moneyness) * 100
            skew_adjustment = otm_pct * self.config.put_skew_per_delta
            return base_iv + skew_adjustment
        else:
            # ATM oder ITM
            return base_iv

    def _estimate_iv_change(
        self,
        entry_iv: float,
        days_held: int,
        vix: Optional[float] = None
    ) -> float:
        """
        Schätzt IV-Veränderung über Zeit.

        Verwendet Mean Reversion zur langfristigen IV (ca. 20%)
        und VIX-Korrelation wenn verfügbar.
        """
        # Langfristige Mean-IV (etwa 20% historisch)
        mean_iv = 0.20

        # Mean Reversion
        reversion_factor = 1 - math.exp(-self.config.iv_mean_reversion_speed * days_held)
        estimated_iv = entry_iv + (mean_iv - entry_iv) * reversion_factor

        # VIX-Anpassung wenn verfügbar
        if vix is not None:
            # VIX 20 = neutral, höher/niedriger = IV adjustment
            vix_adjustment = ((vix - 20) / 100) * self.config.iv_vix_correlation
            estimated_iv += vix_adjustment

        # Bounds
        return max(0.10, min(1.0, estimated_iv))


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def quick_spread_pnl(
    underlying_price: float,
    short_strike: float,
    long_strike: float,
    dte_entry: int,
    dte_current: int,
    entry_price: float,
    current_price: float,
    entry_iv: float = 0.25,
    current_iv: Optional[float] = None
) -> float:
    """
    Schnelle P&L Berechnung für einen Bull-Put-Spread.

    Args:
        underlying_price: Preis bei Entry
        short_strike: Short Put Strike
        long_strike: Long Put Strike
        dte_entry: DTE bei Entry
        dte_current: Aktueller DTE
        entry_price: Aktienkurs bei Entry
        current_price: Aktueller Aktienkurs
        entry_iv: IV bei Entry
        current_iv: Aktuelle IV (wenn None: entry_iv * mean_reversion)

    Returns:
        P&L pro Aktie (positiv = Gewinn)
    """
    simulator = OptionsSimulator()

    # Entry simulieren
    entry = simulator.simulate_entry(
        symbol="TEST",
        underlying_price=entry_price,
        short_strike=short_strike,
        long_strike=long_strike,
        dte=dte_entry,
        iv=entry_iv
    )

    # Current snapshot
    days_held = dte_entry - dte_current
    current_date = entry.entry_date + timedelta(days=days_held)

    snapshot = simulator.calculate_snapshot(
        entry=entry,
        current_date=current_date,
        current_price=current_price,
        current_iv=current_iv
    )

    return snapshot.unrealized_pnl


# =============================================================================
# BATCH/VECTORIZED FUNCTIONS (für Backtesting Performance)
# =============================================================================

def batch_calculate_spread_values(
    current_prices: NDArray[np.float64],
    short_strikes: NDArray[np.float64],
    long_strikes: NDArray[np.float64],
    dtes_remaining: NDArray[np.float64],
    current_ivs: NDArray[np.float64],
    rate: float = 0.05
) -> Tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """
    Batch-Berechnung von Spread-Werten mit NumPy.

    10-100x schneller als Schleifen für große Datasets.

    Args:
        current_prices: Array von Aktienkursen
        short_strikes: Array von Short-Put-Strikes
        long_strikes: Array von Long-Put-Strikes
        dtes_remaining: Array von verbleibenden DTE
        current_ivs: Array von aktuellen IVs
        rate: Risikofreier Zins

    Returns:
        Tuple von (short_put_values, long_put_values, spread_values)
    """
    T = dtes_remaining / 365.0

    # Bei Expiration: Intrinsic Value
    expired_mask = dtes_remaining <= 0

    # Black-Scholes für nicht-expired
    short_put_values = black_scholes_put_np(current_prices, short_strikes, T, rate, current_ivs)
    long_put_values = black_scholes_put_np(current_prices, long_strikes, T, rate, current_ivs)

    # Intrinsic für expired
    short_put_values = np.where(
        expired_mask,
        np.maximum(0, short_strikes - current_prices),
        short_put_values
    )
    long_put_values = np.where(
        expired_mask,
        np.maximum(0, long_strikes - current_prices),
        long_put_values
    )

    spread_values = short_put_values - long_put_values

    return short_put_values, long_put_values, spread_values


def batch_calculate_pnl(
    entry_credits: NDArray[np.float64],
    current_prices: NDArray[np.float64],
    short_strikes: NDArray[np.float64],
    long_strikes: NDArray[np.float64],
    dtes_remaining: NDArray[np.float64],
    current_ivs: NDArray[np.float64],
    contracts: NDArray[np.float64],
    slippage_pct: float = 1.5,
    rate: float = 0.05
) -> NDArray[np.float64]:
    """
    Batch-Berechnung von P&Ls für viele Positionen.

    Args:
        entry_credits: Array von Entry-Credits (pro Aktie)
        current_prices: Array von aktuellen Aktienkursen
        short_strikes: Array von Short-Put-Strikes
        long_strikes: Array von Long-Put-Strikes
        dtes_remaining: Array von verbleibenden DTE
        current_ivs: Array von aktuellen IVs
        contracts: Array von Contract-Anzahlen
        slippage_pct: Exit-Slippage in %
        rate: Risikofreier Zins

    Returns:
        Array von realisierten P&Ls in Dollar
    """
    _, _, spread_values = batch_calculate_spread_values(
        current_prices, short_strikes, long_strikes,
        dtes_remaining, current_ivs, rate
    )

    # P&L pro Aktie = Entry Credit - Cost to Close
    pnl_per_share = entry_credits - spread_values

    # Exit-Slippage einberechnen (nur wenn nicht expired)
    slippage_cost = np.where(
        dtes_remaining > 0,
        spread_values * (slippage_pct / 100),
        0
    )
    pnl_per_share = pnl_per_share - slippage_cost

    # Total P&L (100 shares per contract)
    return pnl_per_share * 100 * contracts


def batch_check_exit_signals(
    current_prices: NDArray[np.float64],
    short_strikes: NDArray[np.float64],
    long_strikes: NDArray[np.float64],
    spread_widths: NDArray[np.float64],
    max_profits: NDArray[np.float64],
    max_losses: NDArray[np.float64],
    pnl_totals: NDArray[np.float64],
    dtes_remaining: NDArray[np.float64],
    profit_target_pct: float = 50.0,
    stop_loss_pct: float = 100.0,
    dte_exit_threshold: int = 7
) -> NDArray[np.int32]:
    """
    Batch-Prüfung von Exit-Signalen für viele Positionen.

    Returns Exit-Codes:
    - 0: Kein Exit
    - 1: Expiration
    - 2: Profit Target
    - 3: Stop Loss
    - 4: DTE Threshold
    - 5: Deep ITM

    Args:
        current_prices: Array von Aktienkursen
        short_strikes: Array von Short-Put-Strikes
        long_strikes: Array von Long-Put-Strikes
        spread_widths: Array von Spread-Widths
        max_profits: Array von Max-Profits
        max_losses: Array von Max-Losses
        pnl_totals: Array von Total-P&Ls
        dtes_remaining: Array von verbleibenden DTE
        profit_target_pct: Profit Target als % des Max Profits
        stop_loss_pct: Stop Loss als % des Max Loss
        dte_exit_threshold: Exit wenn DTE < threshold

    Returns:
        Array von Exit-Codes (0 = kein Exit)
    """
    n = len(current_prices)
    exit_codes = np.zeros(n, dtype=np.int32)

    # 1. Expiration (höchste Priorität)
    expiration_mask = dtes_remaining <= 0
    exit_codes = np.where(expiration_mask, 1, exit_codes)

    # 2. Profit Target
    with np.errstate(divide='ignore', invalid='ignore'):
        pnl_pct = np.where(max_profits > 0, (pnl_totals / max_profits) * 100, 0)
    profit_target_mask = (pnl_pct >= profit_target_pct) & (exit_codes == 0)
    exit_codes = np.where(profit_target_mask, 2, exit_codes)

    # 3. Stop Loss
    loss_mask = pnl_totals < 0
    loss_pct = np.where(
        loss_mask & (max_losses > 0),
        np.abs(pnl_totals) / max_losses * 100,
        0
    )
    stop_loss_mask = (loss_pct >= stop_loss_pct) & (exit_codes == 0)
    exit_codes = np.where(stop_loss_mask, 3, exit_codes)

    # 4. DTE Threshold
    dte_mask = (dtes_remaining <= dte_exit_threshold) & (dtes_remaining > 0) & (exit_codes == 0)
    exit_codes = np.where(dte_mask, 4, exit_codes)

    # 5. Deep ITM
    itm_amount = short_strikes - current_prices
    deep_itm_mask = (itm_amount >= spread_widths * 0.5) & (exit_codes == 0)
    exit_codes = np.where(deep_itm_mask, 5, exit_codes)

    return exit_codes


EXIT_CODE_NAMES = {
    0: None,
    1: "expiration",
    2: "profit_target",
    3: "stop_loss",
    4: "dte_threshold",
    5: "deep_itm",
}
