# OptionPlay - Event-basierte S/R Validierung
# ============================================
# Integration von News und Events in die Support/Resistance Bewertung
#
# Features:
# - Earnings-Integration (wichtigster Faktor)
# - Makro-Events (Fed, CPI, NFP)
# - Ex-Dividend Tracking
# - Event-Impact Scoring
#
# Events können S/R Levels invalidieren oder deren Stärke reduzieren:
# - Earnings Gap kann technische Levels überspringen
# - Fed-Entscheidungen beeinflussen Sektor-weite Levels
# - Dividenden können Preis-Adjustierungen verursachen

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# EVENT TYPES
# =============================================================================

class EventType(Enum):
    """Typen von marktrelevanten Events."""
    EARNINGS = "earnings"           # Quartalszahlen
    DIVIDEND = "dividend"           # Ex-Dividend Datum
    SPLIT = "split"                 # Aktien-Split
    FED_MEETING = "fed_meeting"     # FOMC Meeting
    FED_MINUTES = "fed_minutes"     # FOMC Minutes Release
    CPI = "cpi"                     # Consumer Price Index
    PPI = "ppi"                     # Producer Price Index
    NFP = "nfp"                     # Non-Farm Payrolls
    GDP = "gdp"                     # GDP Release
    RETAIL_SALES = "retail_sales"   # Retail Sales Data
    OPEX = "opex"                   # Options Expiration
    FDA = "fda"                     # FDA Decision (Biotech)
    ANALYST = "analyst"             # Analyst Rating Change
    MERGER = "merger"               # M&A Announcement
    GUIDANCE = "guidance"           # Guidance Update
    OTHER = "other"


class EventImpact(Enum):
    """Erwarteter Impact eines Events auf S/R Levels."""
    NONE = 0           # Kein Impact
    LOW = 1            # Geringer Impact (z.B. Minor News)
    MEDIUM = 2         # Mittlerer Impact (z.B. CPI)
    HIGH = 3           # Hoher Impact (z.B. Fed)
    CRITICAL = 4       # Kritisch - Levels wahrscheinlich invalidiert (Earnings, FDA)


class EventScope(Enum):
    """Gültigkeitsbereich eines Events."""
    SYMBOL = "symbol"      # Nur ein Symbol betroffen
    SECTOR = "sector"      # Gesamter Sektor betroffen
    MARKET = "market"      # Gesamter Markt betroffen


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class MarketEvent:
    """
    Repräsentiert ein marktrelevantes Event.

    Attributes:
        event_type: Typ des Events
        event_date: Datum des Events
        symbol: Betroffenes Symbol (None für Makro-Events)
        description: Beschreibung
        impact: Erwarteter Impact auf S/R Levels
        scope: Gültigkeitsbereich
        source: Datenquelle
        confirmed: True wenn Datum bestätigt
        pre_market: True wenn vor Marktöffnung
        details: Zusätzliche Event-Details
    """
    event_type: EventType
    event_date: date
    symbol: Optional[str] = None
    description: str = ""
    impact: EventImpact = EventImpact.MEDIUM
    scope: EventScope = EventScope.SYMBOL
    source: str = "manual"
    confirmed: bool = False
    pre_market: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def days_until(self) -> int:
        """Tage bis zum Event."""
        return (self.event_date - date.today()).days

    @property
    def is_upcoming(self) -> bool:
        """True wenn Event in der Zukunft liegt."""
        return self.days_until >= 0

    @property
    def is_imminent(self) -> bool:
        """True wenn Event innerhalb von 5 Tagen."""
        return 0 <= self.days_until <= 5

    def affects_symbol(self, symbol: str) -> bool:
        """Prüft ob Event dieses Symbol betrifft."""
        if self.scope == EventScope.MARKET:
            return True
        if self.scope == EventScope.SYMBOL:
            return self.symbol and self.symbol.upper() == symbol.upper()
        # Sector-Events würden zusätzliche Logik benötigen
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary."""
        return {
            'event_type': self.event_type.value,
            'event_date': self.event_date.isoformat(),
            'symbol': self.symbol,
            'description': self.description,
            'impact': self.impact.value,
            'scope': self.scope.value,
            'days_until': self.days_until,
            'confirmed': self.confirmed,
            'pre_market': self.pre_market
        }


@dataclass
class EventValidationResult:
    """
    Ergebnis der Event-basierten S/R Validierung.

    Attributes:
        is_valid: True wenn S/R Levels verwendet werden können
        confidence_multiplier: Multiplikator für Level-Stärke (0.0-1.0)
        blocking_events: Events die Levels invalidieren könnten
        warning_events: Events die Vorsicht erfordern
        recommendations: Empfehlungen basierend auf Events
    """
    is_valid: bool = True
    confidence_multiplier: float = 1.0
    blocking_events: List[MarketEvent] = field(default_factory=list)
    warning_events: List[MarketEvent] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        """True wenn Warnungen vorliegen."""
        return len(self.warning_events) > 0 or len(self.blocking_events) > 0

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary."""
        return {
            'is_valid': self.is_valid,
            'confidence_multiplier': round(self.confidence_multiplier, 2),
            'blocking_events': [e.to_dict() for e in self.blocking_events],
            'warning_events': [e.to_dict() for e in self.warning_events],
            'recommendations': self.recommendations
        }


# =============================================================================
# EVENT IMPACT CONFIGURATION
# =============================================================================

# Standard-Impact pro Event-Typ
DEFAULT_EVENT_IMPACT: Dict[EventType, EventImpact] = {
    EventType.EARNINGS: EventImpact.CRITICAL,
    EventType.DIVIDEND: EventImpact.LOW,
    EventType.SPLIT: EventImpact.HIGH,
    EventType.FED_MEETING: EventImpact.HIGH,
    EventType.FED_MINUTES: EventImpact.MEDIUM,
    EventType.CPI: EventImpact.HIGH,
    EventType.PPI: EventImpact.MEDIUM,
    EventType.NFP: EventImpact.HIGH,
    EventType.GDP: EventImpact.MEDIUM,
    EventType.RETAIL_SALES: EventImpact.LOW,
    EventType.OPEX: EventImpact.MEDIUM,
    EventType.FDA: EventImpact.CRITICAL,
    EventType.ANALYST: EventImpact.LOW,
    EventType.MERGER: EventImpact.CRITICAL,
    EventType.GUIDANCE: EventImpact.HIGH,
    EventType.OTHER: EventImpact.LOW,
}

# Confidence-Reduktion pro Impact-Level und Tage bis Event
# Format: {impact: {days_range: multiplier}}
IMPACT_MULTIPLIERS: Dict[EventImpact, Dict[str, float]] = {
    EventImpact.NONE: {
        "0-3": 1.0, "4-7": 1.0, "8-14": 1.0, "15+": 1.0
    },
    EventImpact.LOW: {
        "0-3": 0.9, "4-7": 0.95, "8-14": 1.0, "15+": 1.0
    },
    EventImpact.MEDIUM: {
        "0-3": 0.7, "4-7": 0.85, "8-14": 0.95, "15+": 1.0
    },
    EventImpact.HIGH: {
        "0-3": 0.5, "4-7": 0.7, "8-14": 0.85, "15+": 0.95
    },
    EventImpact.CRITICAL: {
        "0-3": 0.2, "4-7": 0.5, "8-14": 0.7, "15+": 0.85
    },
}


def get_confidence_multiplier(impact: EventImpact, days_until: int) -> float:
    """
    Berechnet Confidence-Multiplikator basierend auf Event-Impact und Tagen.

    Args:
        impact: Event-Impact Level
        days_until: Tage bis zum Event

    Returns:
        Multiplikator zwischen 0.0 und 1.0
    """
    if days_until < 0:
        return 1.0  # Vergangene Events ignorieren

    multipliers = IMPACT_MULTIPLIERS.get(impact, IMPACT_MULTIPLIERS[EventImpact.LOW])

    if days_until <= 3:
        return multipliers["0-3"]
    elif days_until <= 7:
        return multipliers["4-7"]
    elif days_until <= 14:
        return multipliers["8-14"]
    else:
        return multipliers["15+"]


# =============================================================================
# MACRO EVENT CALENDAR
# =============================================================================

# Bekannte FOMC Meeting Termine 2025-2026
FOMC_MEETINGS_2025 = [
    date(2025, 1, 29),
    date(2025, 3, 19),
    date(2025, 5, 7),
    date(2025, 6, 18),
    date(2025, 7, 30),
    date(2025, 9, 17),
    date(2025, 11, 5),
    date(2025, 12, 17),
]

FOMC_MEETINGS_2026 = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 11, 4),
    date(2026, 12, 16),
]

# Monatliche OPEX (3. Freitag)
def get_monthly_opex(year: int, month: int) -> date:
    """Berechnet den monatlichen Options Expiration Tag (3. Freitag)."""
    first_day = date(year, month, 1)
    # Finde ersten Freitag
    days_until_friday = (4 - first_day.weekday()) % 7
    first_friday = first_day + timedelta(days=days_until_friday)
    # 3. Freitag = erster Freitag + 14 Tage
    third_friday = first_friday + timedelta(days=14)
    return third_friday


def get_macro_events(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_opex: bool = True
) -> List[MarketEvent]:
    """
    Generiert Liste von Makro-Events für einen Zeitraum.

    Args:
        start_date: Startdatum (default: heute)
        end_date: Enddatum (default: +90 Tage)
        include_opex: OPEX Termine einschließen

    Returns:
        Liste von MarketEvent-Objekten
    """
    if start_date is None:
        start_date = date.today()
    if end_date is None:
        end_date = start_date + timedelta(days=90)

    events: List[MarketEvent] = []

    # FOMC Meetings
    all_fomc = FOMC_MEETINGS_2025 + FOMC_MEETINGS_2026
    for meeting_date in all_fomc:
        if start_date <= meeting_date <= end_date:
            events.append(MarketEvent(
                event_type=EventType.FED_MEETING,
                event_date=meeting_date,
                description="FOMC Meeting",
                impact=EventImpact.HIGH,
                scope=EventScope.MARKET,
                source="fed_calendar",
                confirmed=True
            ))

    # Monthly OPEX
    if include_opex:
        current = start_date.replace(day=1)
        while current <= end_date:
            opex = get_monthly_opex(current.year, current.month)
            if start_date <= opex <= end_date:
                events.append(MarketEvent(
                    event_type=EventType.OPEX,
                    event_date=opex,
                    description="Monthly Options Expiration",
                    impact=EventImpact.MEDIUM,
                    scope=EventScope.MARKET,
                    source="calculated",
                    confirmed=True
                ))
            # Nächster Monat
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    return sorted(events, key=lambda e: e.event_date)


# =============================================================================
# EVENT CALENDAR
# =============================================================================

class EventCalendar:
    """
    Zentraler Event-Kalender für S/R Validierung.

    Kombiniert:
    - Symbol-spezifische Events (Earnings, Dividenden)
    - Makro-Events (Fed, CPI, OPEX)
    - Manuelle Events

    Verwendung:
        calendar = EventCalendar()

        # Earnings hinzufügen (aus Cache)
        calendar.add_earnings_from_cache(earnings_cache)

        # Symbol validieren
        result = calendar.validate_for_sr(
            symbol="AAPL",
            lookback_days=7,
            lookahead_days=14
        )

        if not result.is_valid:
            print("S/R Levels nicht zuverlässig wegen:", result.blocking_events)
    """

    def __init__(self, include_macro_events: bool = True):
        self._events: List[MarketEvent] = []
        self._symbols_with_earnings: set = set()

        if include_macro_events:
            self._events.extend(get_macro_events())

    def add_event(self, event: MarketEvent) -> None:
        """Fügt ein Event hinzu."""
        self._events.append(event)
        self._events.sort(key=lambda e: e.event_date)

    def add_earnings(
        self,
        symbol: str,
        earnings_date: date,
        confirmed: bool = False,
        source: str = "unknown"
    ) -> None:
        """Fügt Earnings-Event hinzu."""
        self._symbols_with_earnings.add(symbol.upper())
        self.add_event(MarketEvent(
            event_type=EventType.EARNINGS,
            event_date=earnings_date,
            symbol=symbol.upper(),
            description=f"{symbol} Quarterly Earnings",
            impact=EventImpact.CRITICAL,
            scope=EventScope.SYMBOL,
            source=source,
            confirmed=confirmed
        ))

    def add_dividend(
        self,
        symbol: str,
        ex_date: date,
        amount: Optional[float] = None
    ) -> None:
        """Fügt Ex-Dividend Event hinzu."""
        desc = f"{symbol} Ex-Dividend"
        if amount:
            desc += f" (${amount:.2f})"

        self.add_event(MarketEvent(
            event_type=EventType.DIVIDEND,
            event_date=ex_date,
            symbol=symbol.upper(),
            description=desc,
            impact=EventImpact.LOW,
            scope=EventScope.SYMBOL,
            source="dividend_calendar",
            details={'amount': amount} if amount else {}
        ))

    def add_earnings_from_cache(self, earnings_cache) -> int:
        """
        Importiert Earnings aus EarningsCache.

        Args:
            earnings_cache: EarningsCache Instanz

        Returns:
            Anzahl importierter Events
        """
        count = 0
        for symbol, entry in earnings_cache._cache.items():
            if entry.earnings_date:
                try:
                    earnings_dt = datetime.strptime(entry.earnings_date, "%Y-%m-%d").date()
                    if earnings_dt >= date.today():
                        self.add_earnings(
                            symbol=symbol,
                            earnings_date=earnings_dt,
                            confirmed=entry.confirmed,
                            source=entry.source
                        )
                        count += 1
                except (ValueError, TypeError):
                    pass
        return count

    def get_events_for_symbol(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[MarketEvent]:
        """
        Gibt alle relevanten Events für ein Symbol zurück.

        Inkludiert Symbol-spezifische UND Markt-weite Events.
        """
        if start_date is None:
            start_date = date.today() - timedelta(days=7)
        if end_date is None:
            end_date = date.today() + timedelta(days=30)

        relevant = []
        for event in self._events:
            if start_date <= event.event_date <= end_date:
                if event.affects_symbol(symbol):
                    relevant.append(event)

        return sorted(relevant, key=lambda e: e.event_date)

    def get_upcoming_events(
        self,
        days_ahead: int = 14
    ) -> List[MarketEvent]:
        """Gibt alle Events in den nächsten X Tagen zurück."""
        end_date = date.today() + timedelta(days=days_ahead)
        return [
            e for e in self._events
            if date.today() <= e.event_date <= end_date
        ]

    def validate_for_sr(
        self,
        symbol: str,
        lookback_days: int = 7,
        lookahead_days: int = 14
    ) -> EventValidationResult:
        """
        Validiert ob S/R Levels für ein Symbol zuverlässig sind.

        Prüft:
        - Kürzliche Events die Levels invalidiert haben könnten
        - Bevorstehende Events die Levels gefährden

        Args:
            symbol: Ticker-Symbol
            lookback_days: Tage zurück für vergangene Events
            lookahead_days: Tage voraus für kommende Events

        Returns:
            EventValidationResult mit Details
        """
        start_date = date.today() - timedelta(days=lookback_days)
        end_date = date.today() + timedelta(days=lookahead_days)

        events = self.get_events_for_symbol(symbol, start_date, end_date)

        result = EventValidationResult()
        lowest_multiplier = 1.0

        for event in events:
            days_until = event.days_until
            multiplier = get_confidence_multiplier(event.impact, days_until)

            if multiplier < lowest_multiplier:
                lowest_multiplier = multiplier

            # Kategorisiere Events
            if event.impact == EventImpact.CRITICAL and event.is_imminent:
                result.blocking_events.append(event)
            elif event.impact.value >= EventImpact.MEDIUM.value and event.is_upcoming:
                result.warning_events.append(event)

        # Berechne Gesamt-Confidence
        result.confidence_multiplier = lowest_multiplier

        # Bestimme Validität
        if result.blocking_events:
            result.is_valid = False
            result.recommendations.append(
                "S/R Levels nicht zuverlässig wegen bevorstehendem kritischen Event"
            )
        elif lowest_multiplier < 0.5:
            result.is_valid = False
            result.recommendations.append(
                f"Confidence zu niedrig ({lowest_multiplier:.0%}), Levels mit Vorsicht verwenden"
            )

        # Generiere Empfehlungen
        if result.warning_events:
            event_types = set(e.event_type.value for e in result.warning_events)
            result.recommendations.append(
                f"Bevorstehende Events beachten: {', '.join(event_types)}"
            )

        # Spezielle Warnung für Earnings
        if symbol.upper() not in self._symbols_with_earnings:
            result.recommendations.append(
                "Earnings-Datum unbekannt - manuell prüfen empfohlen"
            )

        return result

    def get_next_earnings(self, symbol: str) -> Optional[MarketEvent]:
        """Gibt das nächste Earnings-Event für ein Symbol zurück."""
        for event in self._events:
            if (event.event_type == EventType.EARNINGS and
                event.symbol == symbol.upper() and
                event.is_upcoming):
                return event
        return None

    def stats(self) -> Dict[str, Any]:
        """Kalender-Statistiken."""
        today = date.today()
        upcoming = [e for e in self._events if e.event_date >= today]

        by_type = {}
        for event in upcoming:
            t = event.event_type.value
            by_type[t] = by_type.get(t, 0) + 1

        return {
            'total_events': len(self._events),
            'upcoming_events': len(upcoming),
            'symbols_with_earnings': len(self._symbols_with_earnings),
            'events_by_type': by_type
        }


# =============================================================================
# INTEGRATION WITH S/R MODULE
# =============================================================================

def validate_sr_levels_with_events(
    symbol: str,
    support_levels: List[float],
    resistance_levels: List[float],
    calendar: Optional[EventCalendar] = None,
    lookahead_days: int = 14
) -> Tuple[List[float], List[float], EventValidationResult]:
    """
    Validiert und adjustiert S/R Levels basierend auf Events.

    Args:
        symbol: Ticker-Symbol
        support_levels: Support-Preise
        resistance_levels: Resistance-Preise
        calendar: EventCalendar (erstellt neuen wenn None)
        lookahead_days: Tage voraus prüfen

    Returns:
        Tuple von:
        - Adjustierte Support-Levels
        - Adjustierte Resistance-Levels
        - EventValidationResult
    """
    if calendar is None:
        calendar = EventCalendar()

    validation = calendar.validate_for_sr(symbol, lookahead_days=lookahead_days)

    # Bei niedriger Confidence: Weniger Levels zurückgeben
    if validation.confidence_multiplier < 0.5:
        # Nur stärkste Levels behalten
        support_levels = support_levels[:1] if support_levels else []
        resistance_levels = resistance_levels[:1] if resistance_levels else []
    elif validation.confidence_multiplier < 0.8:
        # Top 3 behalten
        support_levels = support_levels[:3]
        resistance_levels = resistance_levels[:3]

    return support_levels, resistance_levels, validation


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    'EventType',
    'EventImpact',
    'EventScope',

    # Data Classes
    'MarketEvent',
    'EventValidationResult',

    # Classes
    'EventCalendar',

    # Functions
    'get_macro_events',
    'get_monthly_opex',
    'get_confidence_multiplier',
    'validate_sr_levels_with_events',

    # Constants
    'DEFAULT_EVENT_IMPACT',
    'FOMC_MEETINGS_2025',
    'FOMC_MEETINGS_2026',
]
