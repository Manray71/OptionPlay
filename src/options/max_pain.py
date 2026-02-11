# OptionPlay - Max Pain Calculator
# ==================================
# Berechnet Max Pain, Put/Call Walls und PCR aus Open Interest

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class MaxPainResult:
    """Ergebnis der Max Pain Berechnung"""

    symbol: str
    expiry: str
    current_price: float

    # Max Pain
    max_pain: float
    distance_pct: float  # Abstand zum aktuellen Preis in %

    # Walls (höchstes Open Interest)
    put_wall: Optional[float]
    put_wall_oi: int
    call_wall: Optional[float]
    call_wall_oi: int

    # Totals
    total_put_oi: int
    total_call_oi: int
    pcr: float  # Put/Call Ratio

    def price_vs_max_pain(self) -> str:
        """Zeigt ob Preis über oder unter Max Pain liegt"""
        if self.current_price > self.max_pain:
            return "above"
        elif self.current_price < self.max_pain:
            return "below"
        return "at"

    def sentiment(self) -> str:
        """
        Interpretation des PCR.

        Returns:
            'bearish' wenn PCR > 1.2 (mehr Puts)
            'bullish' wenn PCR < 0.8 (mehr Calls)
            'neutral' sonst
            'extreme_bearish' wenn PCR ist unendlich (keine Calls)
        """
        import math

        if math.isinf(self.pcr):
            return "extreme_bearish"  # Keine Calls, nur Puts
        elif self.pcr > 1.2:
            return "bearish"  # Mehr Puts = bearish sentiment
        elif self.pcr < 0.8:
            return "bullish"  # Mehr Calls = bullish sentiment
        return "neutral"

    def gravity_direction(self) -> str:
        """
        Zeigt erwartete Preisbewegung Richtung Max Pain.

        Max Pain Theorie: Preis tendiert zum Verfall hin zu Max Pain.
        """
        if abs(self.distance_pct) > 3:
            return "down" if self.current_price > self.max_pain else "up"
        return "neutral"

    def to_dict(self) -> Dict:
        import math

        # PCR kann unendlich sein wenn keine Calls vorhanden
        # JSON kann kein Infinity, daher als String oder None
        if math.isinf(self.pcr):
            pcr_value = "inf"
        else:
            pcr_value = round(self.pcr, 2)

        return {
            "symbol": self.symbol,
            "expiry": self.expiry,
            "current_price": round(self.current_price, 2),
            "max_pain": round(self.max_pain, 2),
            "distance_pct": round(self.distance_pct, 2),
            "price_vs_max_pain": self.price_vs_max_pain(),
            "gravity_direction": self.gravity_direction(),
            "put_wall": round(self.put_wall, 2) if self.put_wall else None,
            "put_wall_oi": self.put_wall_oi,
            "call_wall": round(self.call_wall, 2) if self.call_wall else None,
            "call_wall_oi": self.call_wall_oi,
            "total_put_oi": self.total_put_oi,
            "total_call_oi": self.total_call_oi,
            "pcr": pcr_value,
            "sentiment": self.sentiment(),
        }


@dataclass
class StrikePainData:
    """Pain-Daten für einen einzelnen Strike"""

    strike: float
    call_oi: int
    put_oi: int
    total_pain: float  # Gesamtverlust der Options-Käufer bei diesem Settlement


# =============================================================================
# MAX PAIN CALCULATOR
# =============================================================================


class MaxPainCalculator:
    """
    Berechnet Max Pain basierend auf Open Interest.

    Max Pain = Strike-Preis, bei dem Options-Käufer den maximalen
    Gesamtverlust erleiden würden (= Market Makers profitieren am meisten).

    Die Theorie besagt, dass der Preis zum Verfall hin zu diesem
    Level tendiert ("Pinning").

    Verwendung:
        calc = MaxPainCalculator()

        # Aus Tradier Options-Chain
        result = calc.calculate_from_chain(
            symbol="AAPL",
            options_chain=chain_data,
            current_price=175.50,
            expiry="20250321"
        )

        print(f"Max Pain: ${result.max_pain}")
        print(f"Put Wall: ${result.put_wall}")
        print(f"PCR: {result.pcr}")
    """

    def calculate(
        self,
        symbol: str,
        expiry: str,
        current_price: float,
        calls: Dict[float, int],  # strike -> open_interest
        puts: Dict[float, int],  # strike -> open_interest
    ) -> Optional[MaxPainResult]:
        """
        Berechnet Max Pain aus Call/Put Open Interest Dicts.

        Args:
            symbol: Ticker-Symbol
            expiry: Verfalldatum (YYYYMMDD)
            current_price: Aktueller Aktienkurs
            calls: Dict mit Strike -> Open Interest für Calls
            puts: Dict mit Strike -> Open Interest für Puts

        Returns:
            MaxPainResult oder None
        """
        if not calls and not puts:
            return None

        # Alle Strikes sammeln
        all_strikes = sorted(set(calls.keys()) | set(puts.keys()))

        if not all_strikes:
            return None

        # Pain für jeden möglichen Settlement-Preis berechnen
        pain_by_strike: Dict[float, float] = {}

        for settlement in all_strikes:
            total_pain = 0

            # Call-Verlust berechnen
            # Wenn Settlement <= Strike: Call ist OTM, Käufer verliert alles
            # Wenn Settlement > Strike: Call ist ITM, Käufer gewinnt (kein Pain)
            for strike, oi in calls.items():
                if settlement <= strike:
                    # Call OTM - Käufer verliert
                    # Pain = OI * 100 (vereinfacht: jeder Kontrakt = 100 Aktien)
                    total_pain += oi * 100

            # Put-Verlust berechnen
            # Wenn Settlement >= Strike: Put ist OTM, Käufer verliert alles
            # Wenn Settlement < Strike: Put ist ITM, Käufer gewinnt (kein Pain)
            for strike, oi in puts.items():
                if settlement >= strike:
                    # Put OTM - Käufer verliert
                    total_pain += oi * 100

            pain_by_strike[settlement] = total_pain

        # Max Pain = Strike mit höchstem Pain (= meisten wertlosen Optionen)
        # Bei mehreren Strikes mit gleichem Max-Pain: wähle den nächsten zum aktuellen Preis
        max_pain_value = max(pain_by_strike.values())
        candidates = [s for s, p in pain_by_strike.items() if p == max_pain_value]
        max_pain_strike = min(candidates, key=lambda s: abs(s - current_price))

        # Abstand zum aktuellen Preis (mit Null-Check)
        if current_price > 0:
            distance_pct = ((max_pain_strike - current_price) / current_price) * 100
        else:
            distance_pct = 0.0

        # Put Wall (Strike mit höchstem Put OI)
        put_wall = max(puts, key=puts.get) if puts else None
        put_wall_oi = puts.get(put_wall, 0) if put_wall else 0

        # Call Wall (Strike mit höchstem Call OI)
        call_wall = max(calls, key=calls.get) if calls else None
        call_wall_oi = calls.get(call_wall, 0) if call_wall else 0

        # Totals
        total_put_oi = sum(puts.values())
        total_call_oi = sum(calls.values())

        # Put/Call Ratio - robuste Berechnung
        if total_call_oi == 0 and total_put_oi == 0:
            # Keine Daten - neutral
            pcr = 1.0
            logger.warning(f"{symbol}: No open interest data, PCR set to 1.0 (neutral)")
        elif total_call_oi == 0:
            # Nur Puts vorhanden - extrem bearish
            pcr = float("inf")
            logger.warning(f"{symbol}: No call OI, PCR is infinite (extreme bearish)")
        else:
            pcr = total_put_oi / total_call_oi

        return MaxPainResult(
            symbol=symbol,
            expiry=expiry,
            current_price=current_price,
            max_pain=max_pain_strike,
            distance_pct=distance_pct,
            put_wall=put_wall,
            put_wall_oi=put_wall_oi,
            call_wall=call_wall,
            call_wall_oi=call_wall_oi,
            total_put_oi=total_put_oi,
            total_call_oi=total_call_oi,
            pcr=pcr,
        )

    def calculate_from_chain(
        self,
        symbol: str,
        options_chain: List[Dict],
        current_price: float,
        expiry: Optional[str] = None,
    ) -> Optional[MaxPainResult]:
        """
        Berechnet Max Pain aus einer Tradier-Style Options-Chain.

        Args:
            symbol: Ticker-Symbol
            options_chain: Liste von Options-Dicts mit 'strike', 'option_type'/'type', 'open_interest'
            current_price: Aktueller Aktienkurs
            expiry: Verfalldatum (optional, wird aus Chain extrahiert)

        Returns:
            MaxPainResult oder None
        """
        if not options_chain:
            return None

        calls: Dict[float, int] = {}
        puts: Dict[float, int] = {}
        chain_expiry = expiry

        for opt in options_chain:
            strike = opt.get("strike", 0)

            # Option Type (Tradier: 'option_type' oder 'type')
            opt_type = opt.get("option_type", opt.get("type", "")).lower()

            # Open Interest
            oi = opt.get("open_interest", 0) or 0

            # Expiry extrahieren wenn nicht angegeben
            if not chain_expiry:
                # Tradier Format: AAPL250321C00175000 oder expiration_date Feld
                chain_expiry = opt.get("expiration_date", "")
                if not chain_expiry:
                    # Aus Symbol extrahieren
                    occ_symbol = opt.get("symbol", "")
                    if len(occ_symbol) >= 15:
                        # Format: AAPL250321C00175000
                        # Expiry ist an Position 4-10 (YYMMDD)
                        try:
                            exp_part = occ_symbol[-15:-9]
                            chain_expiry = f"20{exp_part}"
                        except (IndexError, ValueError) as e:
                            logger.debug(f"Could not parse OCC expiry from {occ_symbol}: {e}")

            if not strike or strike <= 0:
                continue

            if "call" in opt_type or opt_type == "c":
                calls[strike] = calls.get(strike, 0) + oi
            elif "put" in opt_type or opt_type == "p":
                puts[strike] = puts.get(strike, 0) + oi

        if not calls and not puts:
            return None

        return self.calculate(
            symbol=symbol,
            expiry=chain_expiry or "unknown",
            current_price=current_price,
            calls=calls,
            puts=puts,
        )

    def get_pain_distribution(
        self,
        calls: Dict[float, int],
        puts: Dict[float, int],
        current_price: float,
        num_strikes: int = 10,
    ) -> List[StrikePainData]:
        """
        Gibt Pain-Verteilung für Strikes um den aktuellen Preis zurück.

        Nützlich für Visualisierung.

        Args:
            calls: Strike -> OI für Calls
            puts: Strike -> OI für Puts
            current_price: Aktueller Preis
            num_strikes: Anzahl Strikes pro Seite

        Returns:
            Liste von StrikePainData, sortiert nach Strike
        """
        all_strikes = sorted(set(calls.keys()) | set(puts.keys()))

        if not all_strikes:
            return []

        # Finde Strikes um den aktuellen Preis
        below = [s for s in all_strikes if s <= current_price][-num_strikes:]
        above = [s for s in all_strikes if s > current_price][:num_strikes]
        selected_strikes = below + above

        result = []

        for strike in selected_strikes:
            call_oi = calls.get(strike, 0)
            put_oi = puts.get(strike, 0)

            # Pain bei diesem Strike als Settlement
            total_pain = 0

            for s, oi in calls.items():
                if strike <= s:
                    total_pain += oi * 100

            for s, oi in puts.items():
                if strike >= s:
                    total_pain += oi * 100

            result.append(
                StrikePainData(strike=strike, call_oi=call_oi, put_oi=put_oi, total_pain=total_pain)
            )

        return sorted(result, key=lambda x: x.strike)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def calculate_max_pain(
    symbol: str, options_chain: List[Dict], current_price: float, expiry: Optional[str] = None
) -> Optional[MaxPainResult]:
    """
    Convenience-Funktion für Max Pain Berechnung.

    Beispiel:
        >>> result = calculate_max_pain("AAPL", chain, 175.50)
        >>> print(f"Max Pain: ${result.max_pain}")
        >>> print(f"Distance: {result.distance_pct:+.1f}%")
    """
    calc = MaxPainCalculator()
    return calc.calculate_from_chain(symbol, options_chain, current_price, expiry)


def format_max_pain_report(result: MaxPainResult) -> str:
    """
    Formatiert Max Pain Ergebnis als lesbaren Report.

    Beispiel:
        >>> print(format_max_pain_report(result))
    """
    direction = (
        "↓"
        if result.current_price > result.max_pain
        else "↑" if result.current_price < result.max_pain else "="
    )

    lines = [
        f"═══════════════════════════════════════════════════════════",
        f"  MAX PAIN ANALYSE: {result.symbol}",
        f"  Expiry: {result.expiry}",
        f"═══════════════════════════════════════════════════════════",
        f"",
        f"  Aktueller Preis:  ${result.current_price:.2f}",
        f"  Max Pain:         ${result.max_pain:.2f}  ({result.distance_pct:+.1f}%) {direction}",
        f"",
        f"───────────────────────────────────────────────────────────",
        f"  WALLS (Höchstes Open Interest)",
        f"───────────────────────────────────────────────────────────",
        (
            f"  Put Wall:   ${result.put_wall:.2f}  ({result.put_wall_oi:,} OI)"
            if result.put_wall
            else "  Put Wall:   n/a"
        ),
        (
            f"  Call Wall:  ${result.call_wall:.2f}  ({result.call_wall_oi:,} OI)"
            if result.call_wall
            else "  Call Wall:  n/a"
        ),
        f"",
        f"───────────────────────────────────────────────────────────",
        f"  OPEN INTEREST SUMMARY",
        f"───────────────────────────────────────────────────────────",
        f"  Total Put OI:   {result.total_put_oi:>12,}",
        f"  Total Call OI:  {result.total_call_oi:>12,}",
        f"  Put/Call Ratio: {result.pcr:>12.2f}  ({result.sentiment()})",
        f"",
        f"═══════════════════════════════════════════════════════════",
    ]

    # Gravity-Hinweis hinzufügen
    gravity = result.gravity_direction()
    if gravity != "neutral":
        hint = (
            "Preis könnte Richtung Max Pain fallen"
            if gravity == "down"
            else "Preis könnte Richtung Max Pain steigen"
        )
        lines.insert(-1, f"  💡 {hint}")
        lines.insert(-1, f"")

    return "\n".join(lines)
