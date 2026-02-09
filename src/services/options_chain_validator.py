"""
Options Chain Validator — prüft ob ein Bull-Put-Spread echte Marktdaten hat.

Datenquellen-Priorität:
  1. IBKR (wenn TWS verbunden) — Live Bid/Ask
  2. Tradier — Delayed, aber zuverlässig

Verwendet wird:
  - trading_rules.py für alle Konstanten (DTE, Delta, Credit)
  - Keine eigenen Konstanten definieren

Author: OptionPlay Team
Created: 2026-02-04
"""

# mypy: warn_unused_ignores=False
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Any
from datetime import date, timedelta

try:
    from ..constants.trading_rules import (
        SPREAD_DTE_MIN,
        SPREAD_DTE_MAX,
        SPREAD_DTE_TARGET,
        SPREAD_SHORT_DELTA_TARGET,
        SPREAD_SHORT_DELTA_MIN,
        SPREAD_SHORT_DELTA_MAX,
        SPREAD_LONG_DELTA_TARGET,
        SPREAD_LONG_DELTA_MIN,
        SPREAD_LONG_DELTA_MAX,
        SPREAD_MIN_CREDIT_PCT,
        ENTRY_OPEN_INTEREST_MIN,
        ENTRY_BID_ASK_SPREAD_MAX,
    )
except ImportError:
    from constants.trading_rules import (  # type: ignore[no-redef]  # fallback for non-package execution
        SPREAD_DTE_MIN,
        SPREAD_DTE_MAX,
        SPREAD_DTE_TARGET,
        SPREAD_SHORT_DELTA_TARGET,
        SPREAD_SHORT_DELTA_MIN,
        SPREAD_SHORT_DELTA_MAX,
        SPREAD_LONG_DELTA_TARGET,
        SPREAD_LONG_DELTA_MIN,
        SPREAD_LONG_DELTA_MAX,
        SPREAD_MIN_CREDIT_PCT,
        ENTRY_OPEN_INTEREST_MIN,
        ENTRY_BID_ASK_SPREAD_MAX,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class OptionLeg:
    """Ein Leg eines Spreads mit echten Marktdaten."""
    strike: float
    expiration: str           # YYYY-MM-DD
    dte: int
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float                 # Implied Volatility (Dezimal)
    bid: float
    ask: float
    mid: float
    last: Optional[float]
    open_interest: int
    volume: int


@dataclass
class SpreadValidation:
    """Ergebnis der Options-Chain-Validierung."""
    tradeable: bool
    reason: str = ""
    warning: bool = False

    # Spread-Daten (nur wenn tradeable=True)
    short_leg: Optional[OptionLeg] = None
    long_leg: Optional[OptionLeg] = None
    expiration: Optional[str] = None
    dte: Optional[int] = None

    # Credit-Daten
    credit_bid: Optional[float] = None    # Konservativ: Short Bid - Long Ask
    credit_mid: Optional[float] = None    # Mittel: Short Mid - Long Mid
    spread_width: Optional[float] = None
    credit_pct: Optional[float] = None    # Credit / Spread-Breite in %

    # Spread-Greeks
    spread_theta: Optional[float] = None  # Theta des Spreads pro Tag
    spread_delta: Optional[float] = None  # Netto-Delta
    spread_vega: Optional[float] = None   # Netto-Vega

    # Risiko
    max_loss_per_contract: Optional[float] = None  # (Breite - Credit) × 100

    # IV-Kontext
    short_iv: Optional[float] = None
    long_iv: Optional[float] = None

    # Provider-Info
    data_source: str = ""


# =============================================================================
# OPTIONS CHAIN VALIDATOR
# =============================================================================

class OptionsChainValidator:
    """
    Validiert ob ein Bull-Put-Spread echte Marktdaten hat.

    Ablauf:
    1. Expirations im DTE-Fenster finden (60-90 Tage)
    2. Beste Expiration wählen (~75 DTE)
    3. Puts-Chain abrufen
    4. Short Strike finden (Delta ≈ -0.20)
    5. Long Strike finden (Delta ≈ -0.05)
    6. Credit berechnen (Short Bid - Long Ask)
    7. Credit >= 10% Spread-Breite?
    8. Liquiditäts-Check (OI, Bid-Ask)
    """

    def __init__(self, options_provider: Any, ibkr_bridge: Any = None) -> None:
        """
        Args:
            options_provider: Provider mit get_option_chain() und get_expirations()
                            (Tradier oder MarketData)
            ibkr_bridge: Optional IBKR-Bridge für Live-Daten
        """
        self._provider = options_provider
        self._ibkr = ibkr_bridge
        self._data_source = "unknown"

    async def validate_spread(self, symbol: str) -> SpreadValidation:
        """
        Hauptmethode: Prüft ob für ein Symbol ein handelbarer
        Bull-Put-Spread existiert.

        Returns:
            SpreadValidation mit echten Marktdaten oder Ablehnungsgrund
        """
        try:
            # 1. Expirations im DTE-Fenster
            expirations = await self._get_valid_expirations(symbol)
            if not expirations:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Keine Expiration im DTE-Fenster {SPREAD_DTE_MIN}-{SPREAD_DTE_MAX}",
                )

            # 2. Beste Expiration (nächste an DTE_TARGET = 75)
            best_exp, best_dte = self._select_optimal_expiration(expirations)

            # 3. Puts-Chain abrufen
            chain = await self._get_puts_chain(symbol, best_exp)
            if not chain:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Options Chain für {best_exp} nicht verfügbar",
                )

            # 4. Short Strike (Delta ≈ -0.20, Toleranz ±0.03)
            short = self._find_strike_by_delta(
                chain,
                target=SPREAD_SHORT_DELTA_TARGET,    # -0.20
                min_delta=SPREAD_SHORT_DELTA_MAX,     # -0.23 (more negative)
                max_delta=SPREAD_SHORT_DELTA_MIN,     # -0.17 (less negative)
            )
            if not short:
                return SpreadValidation(
                    tradeable=False,
                    reason=(
                        f"Kein Put mit Delta im Bereich "
                        f"[{SPREAD_SHORT_DELTA_MAX}, {SPREAD_SHORT_DELTA_MIN}] gefunden"
                    ),
                )

            # 5. Long Strike (Delta ≈ -0.05, Toleranz ±0.02)
            long = self._find_strike_by_delta(
                chain,
                target=SPREAD_LONG_DELTA_TARGET,      # -0.05
                min_delta=SPREAD_LONG_DELTA_MAX,       # -0.07
                max_delta=SPREAD_LONG_DELTA_MIN,       # -0.03
            )
            if not long:
                return SpreadValidation(
                    tradeable=False,
                    reason=(
                        f"Kein Put mit Delta im Bereich "
                        f"[{SPREAD_LONG_DELTA_MAX}, {SPREAD_LONG_DELTA_MIN}] gefunden"
                    ),
                )

            # Sicherstellen: Short Strike > Long Strike (Bull Put Spread)
            if short.strike <= long.strike:
                return SpreadValidation(
                    tradeable=False,
                    reason=f"Strike-Reihenfolge ungültig: Short {short.strike} <= Long {long.strike}",
                )

            # 6. Credit berechnen
            credit_bid = short.bid - long.ask    # Konservativ
            credit_mid = short.mid - long.mid    # Mittel
            spread_width = short.strike - long.strike

            if credit_bid <= 0:
                return SpreadValidation(
                    tradeable=False,
                    reason=(
                        f"Negativer Credit: Short Bid {short.bid:.2f} - "
                        f"Long Ask {long.ask:.2f} = {credit_bid:.2f}"
                    ),
                )

            # 7. Credit >= 10% Spread-Breite?
            credit_pct = (credit_bid / spread_width) * 100

            if credit_pct < SPREAD_MIN_CREDIT_PCT:
                return SpreadValidation(
                    tradeable=False,
                    reason=(
                        f"Credit {credit_pct:.1f}% < {SPREAD_MIN_CREDIT_PCT}% Minimum "
                        f"(${credit_bid:.2f} auf ${spread_width:.0f} Spread)"
                    ),
                )

            # 8. Liquiditäts-Check
            warnings = []

            if short.open_interest < ENTRY_OPEN_INTEREST_MIN:
                warnings.append(
                    f"Short OI {short.open_interest} < {ENTRY_OPEN_INTEREST_MIN}"
                )
            if long.open_interest < ENTRY_OPEN_INTEREST_MIN:
                warnings.append(
                    f"Long OI {long.open_interest} < {ENTRY_OPEN_INTEREST_MIN}"
                )

            bid_ask_spread_short = short.ask - short.bid
            if bid_ask_spread_short > ENTRY_BID_ASK_SPREAD_MAX:
                warnings.append(
                    f"Short Bid-Ask ${bid_ask_spread_short:.2f} > "
                    f"${ENTRY_BID_ASK_SPREAD_MAX:.2f}"
                )

            # Spread-Greeks
            spread_theta = short.theta - long.theta  # Positiv = Geld pro Tag
            spread_delta = short.delta - long.delta
            spread_vega = short.vega - long.vega
            max_loss = (spread_width - credit_bid) * 100

            return SpreadValidation(
                tradeable=True,
                warning=len(warnings) > 0,
                reason="; ".join(warnings) if warnings else "Alle Checks bestanden",
                short_leg=short,
                long_leg=long,
                expiration=best_exp.isoformat() if isinstance(best_exp, date) else str(best_exp),
                dte=best_dte,
                credit_bid=round(credit_bid, 2),
                credit_mid=round(credit_mid, 2),
                spread_width=spread_width,
                credit_pct=round(credit_pct, 1),
                spread_theta=round(spread_theta, 4),
                spread_delta=round(spread_delta, 4),
                spread_vega=round(spread_vega, 4),
                max_loss_per_contract=round(max_loss, 2),
                short_iv=short.iv,
                long_iv=long.iv,
                data_source=self._data_source,
            )

        except Exception as e:
            logger.error(f"Chain-Validierung für {symbol} fehlgeschlagen: {e}")
            return SpreadValidation(
                tradeable=False,
                reason=f"Fehler: {e}",
            )

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    async def _get_valid_expirations(self, symbol: str) -> list[tuple[date, int]]:
        """
        Gibt Liste von (expiration_date, dte) im gültigen DTE-Fenster zurück.

        Versucht zuerst IBKR, dann Tradier.
        """
        today = date.today()
        expirations = []

        # IBKR zuerst (wenn verbunden)
        if self._ibkr and hasattr(self._ibkr, 'is_connected') and self._ibkr.is_connected():
            try:
                chain = await self._ibkr.get_option_chain(
                    symbol, dte_min=SPREAD_DTE_MIN, dte_max=SPREAD_DTE_MAX, right="P"
                )
                if chain:
                    self._data_source = "IBKR"
                    # Unique expirations aus Chain extrahieren
                    seen = set()
                    for opt in chain:
                        exp = opt.expiry if hasattr(opt, 'expiry') else None
                        if exp and exp not in seen:
                            dte = (exp - today).days
                            if SPREAD_DTE_MIN <= dte <= SPREAD_DTE_MAX:
                                expirations.append((exp, dte))
                                seen.add(exp)
                    if expirations:
                        return sorted(expirations, key=lambda x: x[1])
            except Exception as e:
                logger.warning(f"IBKR Expirations für {symbol} fehlgeschlagen: {e}")

        # Tradier Fallback
        try:
            all_exps = await self._provider.get_expirations(symbol)
            self._data_source = "Tradier"
            for exp in all_exps:
                dte = (exp - today).days
                if SPREAD_DTE_MIN <= dte <= SPREAD_DTE_MAX:
                    expirations.append((exp, dte))
        except Exception as e:
            logger.error(f"Tradier Expirations für {symbol} fehlgeschlagen: {e}")

        return sorted(expirations, key=lambda x: x[1])

    def _select_optimal_expiration(self, expirations: list[tuple[date, int]]) -> tuple[date, int]:
        """Wählt Expiration am nächsten an DTE_TARGET (75 Tage)."""
        return min(expirations, key=lambda x: abs(x[1] - SPREAD_DTE_TARGET))

    async def _get_puts_chain(self, symbol: str, expiration: date) -> list[OptionLeg]:
        """
        Ruft Put-Options für Symbol+Expiration ab.

        Provider-Kaskade: IBKR → Tradier
        """
        option_quotes = []

        # IBKR zuerst
        if self._ibkr and hasattr(self._ibkr, 'is_connected') and self._ibkr.is_connected():
            try:
                chain = await self._ibkr.get_option_chain(
                    symbol,
                    dte_min=(expiration - date.today()).days,
                    dte_max=(expiration - date.today()).days + 1,
                    right="P",
                )
                if chain:
                    self._data_source = "IBKR"
                    option_quotes = chain
            except Exception as e:
                logger.warning(f"IBKR Chain für {symbol} {expiration} fehlgeschlagen: {e}")

        # Tradier Fallback
        if not option_quotes:
            try:
                option_quotes = await self._provider.get_option_chain(
                    symbol, expiry=expiration, right="P"
                )
                self._data_source = "Tradier"
            except Exception as e:
                logger.error(f"Tradier Chain für {symbol} {expiration} fehlgeschlagen: {e}")
                return []

        if not option_quotes:
            return []

        # OptionQuote → OptionLeg konvertieren
        legs = []
        today = date.today()

        for oq in option_quotes:
            # Validierung: Mindestens Delta und Bid müssen vorhanden sein
            if oq.delta is None or oq.bid is None or oq.ask is None:
                continue

            dte = (oq.expiry - today).days if hasattr(oq, 'expiry') and oq.expiry else 0

            leg = OptionLeg(
                strike=oq.strike,
                expiration=oq.expiry.isoformat() if hasattr(oq, 'expiry') and oq.expiry else "",
                dte=dte,
                delta=oq.delta,
                gamma=oq.gamma or 0.0,
                theta=oq.theta or 0.0,
                vega=oq.vega or 0.0,
                iv=oq.implied_volatility or 0.0,
                bid=oq.bid,
                ask=oq.ask,
                mid=(oq.bid + oq.ask) / 2,
                last=oq.last,
                open_interest=oq.open_interest or 0,
                volume=oq.volume or 0,
            )
            legs.append(leg)

        return legs

    def _find_strike_by_delta(
        self,
        chain: list[OptionLeg],
        target: float,
        min_delta: float,
        max_delta: float,
    ) -> Optional[OptionLeg]:
        """
        Findet den Strike mit Delta am nächsten zum Target,
        innerhalb des erlaubten Bereichs.

        Args:
            chain: Liste von OptionLeg
            target: Ziel-Delta (z.B. -0.20)
            min_delta: Untere Grenze (negativer, z.B. -0.23)
            max_delta: Obere Grenze (weniger negativ, z.B. -0.17)
        """
        # Puts haben negative Deltas
        candidates = [
            leg for leg in chain
            if min_delta <= leg.delta <= max_delta
            and leg.bid > 0  # Mindestens Bid > 0
        ]

        if not candidates:
            # Fallback: erweitere Suche um ±0.02 wenn nichts gefunden
            expanded_candidates = [
                leg for leg in chain
                if (min_delta - 0.02) <= leg.delta <= (max_delta + 0.02)
                and leg.bid > 0
            ]
            if expanded_candidates:
                logger.info(
                    f"Delta-Suche erweitert: {len(expanded_candidates)} Kandidaten "
                    f"im erweiterten Bereich [{min_delta - 0.02:.2f}, {max_delta + 0.02:.2f}]"
                )
                candidates = expanded_candidates

        if not candidates:
            return None

        # Nächster an Target-Delta
        return min(candidates, key=lambda x: abs(x.delta - target))
