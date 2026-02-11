# OptionPlay - Spread Finder & Outcome Calculator
# =================================================
# Extracted from simulation/real_options_backtester.py (Phase 6c)
#
# Contains logic for finding Bull-Put-Spreads and calculating outcomes.

import logging
from datetime import date
from typing import Dict, List, Optional

from ...constants.trading_rules import SPREAD_DTE_MAX, SPREAD_DTE_MIN
from ..models.outcomes import (
    OptionQuote,
    SpreadEntry,
    SpreadOutcome,
    SpreadOutcomeResult,
)
from .database import OptionsDatabase

logger = logging.getLogger(__name__)


class SpreadFinder:
    """Findet passende Bull-Put-Spreads in den Optionsdaten"""

    def __init__(self, db: OptionsDatabase) -> None:
        self.db = db

    def find_spread(
        self,
        symbol: str,
        quote_date: date,
        target_short_otm_pct: float = 10.0,  # 10% OTM
        spread_width_pct: float = 5.0,  # 5% des Aktienkurses
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
    ) -> Optional[SpreadEntry]:
        """
        Findet einen Bull-Put-Spread basierend auf Kriterien.

        Args:
            symbol: Ticker
            quote_date: Entry-Datum
            target_short_otm_pct: Ziel OTM% für Short Strike
            spread_width_pct: Spread-Breite als % des Aktienkurses (z.B. 5% = $10 bei $200)
            dte_min/max: DTE-Range

        Returns:
            SpreadEntry oder None wenn kein passender Spread gefunden
        """
        # Hole alle OTM Puts
        puts = self.db.get_puts_for_date(
            symbol=symbol,
            quote_date=quote_date,
            dte_min=dte_min,
            dte_max=dte_max,
            moneyness_min=0.80,  # 20% OTM max
            moneyness_max=0.98,  # leicht OTM
        )

        if not puts:
            return None

        # Gruppiere nach Expiration
        by_expiration: Dict[date, List[OptionQuote]] = {}
        for put in puts:
            if put.expiration not in by_expiration:
                by_expiration[put.expiration] = []
            by_expiration[put.expiration].append(put)

        # Finde beste Expiration (nächste mit genug Liquidität)
        best_spread = None

        for expiry, expiry_puts in sorted(by_expiration.items()):
            # Finde Short Put nahe target OTM%
            short_put = self._find_nearest_otm(expiry_puts, target_short_otm_pct)
            if not short_put:
                continue

            # Berechne Spread-Width basierend auf Prozent des Aktienkurses
            # 5% von $200 = $10, gerundet auf $5 Inkremente
            underlying_price = short_put.underlying_price
            spread_width_dollars = underlying_price * (spread_width_pct / 100.0)
            if underlying_price >= 100:
                spread_width_dollars = max(5.0, round(spread_width_dollars / 5.0) * 5.0)
            else:
                spread_width_dollars = max(2.5, round(spread_width_dollars / 2.5) * 2.5)

            # Finde Long Put mit passendem Strike
            long_strike = short_put.strike - spread_width_dollars
            long_put = self._find_strike(expiry_puts, long_strike)
            if not long_put:
                continue

            # Prüfe Liquidität (Bid > 0)
            if short_put.bid <= 0 or long_put.ask <= 0:
                continue

            # Berechne Credit
            # Realistisch: Verkaufe zu Bid, Kaufe zu Ask
            net_credit = short_put.bid - long_put.ask
            gross_credit = short_put.mid - long_put.mid

            if net_credit <= 0:
                continue  # Kein positiver Credit

            spread = SpreadEntry(
                symbol=symbol,
                entry_date=quote_date,
                expiration=expiry,
                underlying_price=short_put.underlying_price,
                short_strike=short_put.strike,
                short_bid=short_put.bid,
                short_ask=short_put.ask,
                short_mid=short_put.mid,
                long_strike=long_put.strike,
                long_bid=long_put.bid,
                long_ask=long_put.ask,
                long_mid=long_put.mid,
                spread_width=short_put.strike - long_put.strike,
                gross_credit=gross_credit,
                net_credit=net_credit,
                dte=short_put.dte,
                short_otm_pct=short_put.otm_pct,
                long_otm_pct=long_put.otm_pct,
            )

            best_spread = spread
            break  # Nimm den ersten passenden

        return best_spread

    def _find_nearest_otm(
        self,
        puts: List[OptionQuote],
        target_otm_pct: float,
    ) -> Optional[OptionQuote]:
        """Findet Put mit OTM% am nächsten zum Target"""
        otm_puts = [p for p in puts if p.otm_pct > 0]
        if not otm_puts:
            return None

        return min(otm_puts, key=lambda p: abs(p.otm_pct - target_otm_pct))

    def _find_strike(
        self,
        puts: List[OptionQuote],
        target_strike: float,
        tolerance: float = 2.5,
    ) -> Optional[OptionQuote]:
        """Findet Put mit Strike am nächsten zum Target"""
        candidates = [p for p in puts if abs(p.strike - target_strike) <= tolerance]
        if not candidates:
            return None

        return min(candidates, key=lambda p: abs(p.strike - target_strike))


class OutcomeCalculator:
    """Berechnet das Outcome eines Spreads basierend auf Preisverlauf"""

    def __init__(self, db: OptionsDatabase) -> None:
        self.db = db

    def calculate_outcome(
        self,
        entry: SpreadEntry,
        prices: Dict[date, float] = None,
    ) -> Optional[SpreadOutcomeResult]:
        """
        Berechnet das Outcome eines Spreads bei Expiration.

        Args:
            entry: SpreadEntry mit Entry-Daten
            prices: Optional Dict von date -> price (wenn nicht übergeben, aus DB laden)

        Returns:
            SpreadOutcomeResult oder None bei Fehler
        """
        # Lade Preise wenn nicht übergeben
        if prices is None:
            prices = self.db.get_underlying_prices(
                entry.symbol,
                entry.entry_date,
                entry.expiration,
            )

        if not prices:
            logger.warning(
                f"No price data for {entry.symbol} from {entry.entry_date} to {entry.expiration}"
            )
            return None

        # Finde Exit-Preis (bei Expiration oder letzter verfügbarer)
        exit_date = entry.expiration
        if exit_date not in prices:
            # Nimm letzten verfügbaren Preis vor Expiration
            available_dates = [d for d in prices.keys() if d <= exit_date]
            if not available_dates:
                return None
            exit_date = max(available_dates)

        exit_price = prices[exit_date]

        # Berechne Statistiken während der Laufzeit
        trade_dates = [d for d in prices.keys() if entry.entry_date <= d <= exit_date]
        trade_prices = [prices[d] for d in trade_dates]

        if not trade_prices:
            return None

        min_price = min(trade_prices)
        max_price = max(trade_prices)
        days_below_short = sum(1 for p in trade_prices if p < entry.short_strike)

        max_drawdown_pct = (entry.underlying_price - min_price) / entry.underlying_price * 100

        # Bestimme Outcome basierend auf Exit-Preis
        if exit_price >= entry.short_strike:
            # Preis über Short Strike = Max Profit
            outcome = SpreadOutcome.MAX_PROFIT
            pnl = entry.net_credit * 100  # Voller Credit behalten
        elif exit_price <= entry.long_strike:
            # Preis unter Long Strike = Max Loss
            outcome = SpreadOutcome.MAX_LOSS
            pnl = -entry.max_loss
        else:
            # Preis zwischen den Strikes
            intrinsic_loss = (entry.short_strike - exit_price) * 100
            pnl = (entry.net_credit * 100) - intrinsic_loss

            if pnl >= 0:
                outcome = SpreadOutcome.PARTIAL_PROFIT
            else:
                outcome = SpreadOutcome.PARTIAL_LOSS

        # P&L als Prozent vom Max Profit
        pnl_pct = (pnl / entry.max_profit * 100) if entry.max_profit > 0 else 0

        return SpreadOutcomeResult(
            entry=entry,
            exit_date=exit_date,
            exit_underlying_price=exit_price,
            outcome=outcome,
            pnl_per_contract=pnl,
            pnl_pct=pnl_pct,
            min_price_during_trade=min_price,
            max_price_during_trade=max_price,
            days_below_short_strike=days_below_short,
            max_drawdown_pct=max_drawdown_pct,
            was_profitable=pnl > 0,
            held_to_expiration=exit_date == entry.expiration,
        )
