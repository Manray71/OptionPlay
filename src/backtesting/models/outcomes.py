"""
Outcome Data Models for Real Options Backtesting
=================================================

Extracted from real_options_backtester.py (Phase 6a).

Contains:
- SpreadOutcome: Enum for Bull-Put-Spread outcomes
- OptionQuote: Single options quote from database
- SpreadEntry: Entry data for a Bull-Put-Spread
- SpreadOutcomeResult: Outcome result at expiration
- SetupFeatures: ML training features at entry time
- BacktestTradeRecord: Complete backtested trade record
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, Optional

# =============================================================================
# ENUMS
# =============================================================================


class SpreadOutcome(Enum):
    """Mögliche Outcomes eines Bull-Put-Spreads"""

    MAX_PROFIT = "max_profit"  # Preis > Short Strike bei Expiration (voller Credit behalten)
    PARTIAL_PROFIT = "partial_profit"  # Preis zwischen Strikes, aber netto Gewinn
    PARTIAL_LOSS = "partial_loss"  # Preis zwischen Strikes, netto Verlust
    MAX_LOSS = "max_loss"  # Preis <= Long Strike bei Expiration (max Verlust)
    EARLY_EXIT = "early_exit"  # Vor Expiration geschlossen


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class OptionQuote:
    """Eine einzelne Options-Quote aus der Datenbank"""

    occ_symbol: str
    underlying: str
    expiration: date
    strike: float
    option_type: str  # 'P' or 'C'
    quote_date: date
    bid: float
    ask: float
    mid: float
    last: Optional[float]
    volume: int
    open_interest: int
    underlying_price: float
    dte: int
    moneyness: float

    @property
    def is_otm(self) -> bool:
        """Ist die Option Out-of-the-Money?"""
        if self.option_type == "P":
            return self.strike < self.underlying_price
        else:
            return self.strike > self.underlying_price

    @property
    def otm_pct(self) -> float:
        """Out-of-the-Money Prozent"""
        if self.option_type == "P":
            return (self.underlying_price - self.strike) / self.underlying_price * 100
        else:
            return (self.strike - self.underlying_price) / self.underlying_price * 100


@dataclass
class SpreadEntry:
    """Entry-Daten eines Bull-Put-Spreads mit echten Preisen"""

    symbol: str
    entry_date: date
    expiration: date

    # Underlying
    underlying_price: float

    # Short Put (verkauft)
    short_strike: float
    short_bid: float
    short_ask: float
    short_mid: float

    # Long Put (gekauft)
    long_strike: float
    long_bid: float
    long_ask: float
    long_mid: float

    # Spread-Daten
    spread_width: float  # short_strike - long_strike

    # Credit (was wir erhalten)
    # Realistisch: Verkaufe Short Put zu Bid, Kaufe Long Put zu Ask
    gross_credit: float  # mid-to-mid
    net_credit: float  # bid-ask realistic

    # DTE
    dte: int

    # Moneyness
    short_otm_pct: float
    long_otm_pct: float

    @property
    def max_profit(self) -> float:
        """Max Profit = Net Credit * 100 (pro Contract)"""
        return self.net_credit * 100

    @property
    def max_loss(self) -> float:
        """Max Loss = (Spread Width - Net Credit) * 100"""
        return (self.spread_width - self.net_credit) * 100

    @property
    def risk_reward_ratio(self) -> float:
        """Risk/Reward Ratio"""
        if self.max_profit > 0:
            return self.max_loss / self.max_profit
        return float("inf")


@dataclass
class SpreadOutcomeResult:
    """Ergebnis eines Bull-Put-Spreads bei Expiration"""

    entry: SpreadEntry

    # Exit-Daten
    exit_date: date
    exit_underlying_price: float

    # Outcome
    outcome: SpreadOutcome

    # P&L
    pnl_per_contract: float  # In Dollar
    pnl_pct: float  # Prozent vom Max Profit

    # Was passierte während der Laufzeit
    min_price_during_trade: float
    max_price_during_trade: float
    days_below_short_strike: int
    max_drawdown_pct: float

    # Trade-Qualität
    was_profitable: bool
    held_to_expiration: bool

    def to_dict(self) -> dict:
        """Konvertiert zu Dictionary für Speicherung"""
        return {
            "symbol": self.entry.symbol,
            "entry_date": self.entry.entry_date.isoformat(),
            "exit_date": self.exit_date.isoformat(),
            "expiration": self.entry.expiration.isoformat(),
            "entry_price": self.entry.underlying_price,
            "exit_price": self.exit_underlying_price,
            "short_strike": self.entry.short_strike,
            "long_strike": self.entry.long_strike,
            "spread_width": self.entry.spread_width,
            "net_credit": self.entry.net_credit,
            "dte_at_entry": self.entry.dte,
            "short_otm_pct": self.entry.short_otm_pct,
            "outcome": self.outcome.value,
            "pnl": self.pnl_per_contract,
            "pnl_pct": self.pnl_pct,
            "min_price": self.min_price_during_trade,
            "max_price": self.max_price_during_trade,
            "days_below_short": self.days_below_short_strike,
            "max_drawdown_pct": self.max_drawdown_pct,
            "was_profitable": self.was_profitable,
        }


@dataclass
class SetupFeatures:
    """
    Features eines Trading-Setups zum Zeitpunkt des Entries.
    Diese werden später für ML-Training verwendet.
    """

    # Symbol & Datum
    symbol: str
    date: date

    # Preis-basiert
    price: float

    # Technische Indikatoren (zum Zeitpunkt des Entries)
    rsi_14: Optional[float] = None
    macd_histogram: Optional[float] = None
    stoch_k: Optional[float] = None

    # Trend
    above_sma20: Optional[bool] = None
    above_sma50: Optional[bool] = None
    above_sma200: Optional[bool] = None
    trend: Optional[str] = None  # 'uptrend', 'downtrend', 'sideways'

    # Support/Resistance
    distance_to_support_pct: Optional[float] = None
    support_strength: Optional[int] = None  # Anzahl Touches

    # Volatilität
    historical_vol_20d: Optional[float] = None
    historical_vol_60d: Optional[float] = None

    # Markt-Kontext
    vix: Optional[float] = None
    vix_regime: Optional[str] = None  # 'low', 'medium', 'high', 'extreme'

    # Symbol-spezifisch
    avg_volume_20d: Optional[float] = None
    relative_volume: Optional[float] = None  # Heutiges Vol / Avg Vol

    # Earnings
    days_to_earnings: Optional[int] = None
    days_since_earnings: Optional[int] = None

    # Strategie-Score (falls vorhanden)
    pullback_score: Optional[float] = None
    bounce_score: Optional[float] = None
    ath_breakout_score: Optional[float] = None
    earnings_dip_score: Optional[float] = None
    trend_continuation_score: Optional[float] = None

    def to_dict(self) -> dict:
        """Konvertiert zu Dictionary"""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class BacktestTradeRecord:
    """
    Vollständiger Record eines backtesteten Trades.
    Enthält Setup-Features UND Outcome - perfekt für ML-Training.
    """

    # Setup-Features zum Entry-Zeitpunkt
    features: SetupFeatures

    # Spread-Konfiguration
    entry: SpreadEntry

    # Outcome
    outcome: SpreadOutcomeResult

    def to_dict(self) -> dict:
        """Konvertiert zu Dictionary für Speicherung/Training"""
        return {
            "features": self.features.to_dict(),
            "spread": {
                "short_strike": self.entry.short_strike,
                "long_strike": self.entry.long_strike,
                "spread_width": self.entry.spread_width,
                "net_credit": self.entry.net_credit,
                "dte": self.entry.dte,
                "short_otm_pct": self.entry.short_otm_pct,
            },
            "outcome": self.outcome.to_dict(),
        }
