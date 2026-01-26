# Tests for Event-based S/R Validation
# =====================================

import pytest
from datetime import date, timedelta
from typing import List

import sys
sys.path.insert(0, 'src')

from indicators.events import (
    EventType,
    EventImpact,
    EventScope,
    MarketEvent,
    EventValidationResult,
    EventCalendar,
    get_macro_events,
    get_monthly_opex,
    get_confidence_multiplier,
    validate_sr_levels_with_events,
    DEFAULT_EVENT_IMPACT,
    FOMC_MEETINGS_2025,
    FOMC_MEETINGS_2026,
)


# =============================================================================
# EVENT TYPE TESTS
# =============================================================================

class TestEventTypes:
    """Tests für EventType Enum."""

    def test_event_types_exist(self):
        """Alle wichtigen Event-Types existieren."""
        assert EventType.EARNINGS
        assert EventType.DIVIDEND
        assert EventType.FED_MEETING
        assert EventType.CPI
        assert EventType.NFP
        assert EventType.OPEX

    def test_event_impact_ordering(self):
        """Impact-Levels sind korrekt geordnet."""
        assert EventImpact.NONE.value < EventImpact.LOW.value
        assert EventImpact.LOW.value < EventImpact.MEDIUM.value
        assert EventImpact.MEDIUM.value < EventImpact.HIGH.value
        assert EventImpact.HIGH.value < EventImpact.CRITICAL.value


# =============================================================================
# MARKET EVENT TESTS
# =============================================================================

class TestMarketEvent:
    """Tests für MarketEvent Datenstruktur."""

    def test_create_earnings_event(self):
        """Erstellt Earnings-Event."""
        event = MarketEvent(
            event_type=EventType.EARNINGS,
            event_date=date.today() + timedelta(days=10),
            symbol="AAPL",
            description="AAPL Q1 Earnings",
            impact=EventImpact.CRITICAL,
            scope=EventScope.SYMBOL
        )

        assert event.event_type == EventType.EARNINGS
        assert event.symbol == "AAPL"
        assert event.impact == EventImpact.CRITICAL
        assert event.days_until == 10
        assert event.is_upcoming is True

    def test_days_until_calculation(self):
        """Berechnet Tage bis Event korrekt."""
        # Zukünftiges Event
        future = MarketEvent(
            event_type=EventType.FED_MEETING,
            event_date=date.today() + timedelta(days=5)
        )
        assert future.days_until == 5
        assert future.is_upcoming is True
        assert future.is_imminent is True

        # Vergangenes Event
        past = MarketEvent(
            event_type=EventType.CPI,
            event_date=date.today() - timedelta(days=3)
        )
        assert past.days_until == -3
        assert past.is_upcoming is False

    def test_affects_symbol(self):
        """Prüft affects_symbol Logik."""
        # Symbol-spezifisches Event
        earnings = MarketEvent(
            event_type=EventType.EARNINGS,
            event_date=date.today(),
            symbol="AAPL",
            scope=EventScope.SYMBOL
        )
        assert earnings.affects_symbol("AAPL") is True
        assert earnings.affects_symbol("aapl") is True  # Case-insensitive
        assert earnings.affects_symbol("MSFT") is False

        # Markt-weites Event
        fed = MarketEvent(
            event_type=EventType.FED_MEETING,
            event_date=date.today(),
            scope=EventScope.MARKET
        )
        assert fed.affects_symbol("AAPL") is True
        assert fed.affects_symbol("MSFT") is True

    def test_to_dict(self):
        """Konvertiert zu Dictionary."""
        event = MarketEvent(
            event_type=EventType.DIVIDEND,
            event_date=date.today() + timedelta(days=7),
            symbol="MSFT",
            description="MSFT Ex-Dividend",
            impact=EventImpact.LOW
        )

        d = event.to_dict()

        assert d['event_type'] == 'dividend'
        assert d['symbol'] == 'MSFT'
        assert d['impact'] == 1
        assert d['days_until'] == 7


# =============================================================================
# CONFIDENCE MULTIPLIER TESTS
# =============================================================================

class TestConfidenceMultiplier:
    """Tests für Confidence-Multiplikator Berechnung."""

    def test_critical_impact_imminent(self):
        """Kritisches Event in 0-3 Tagen."""
        multiplier = get_confidence_multiplier(EventImpact.CRITICAL, 1)
        assert multiplier == 0.2

    def test_critical_impact_week(self):
        """Kritisches Event in 4-7 Tagen."""
        multiplier = get_confidence_multiplier(EventImpact.CRITICAL, 5)
        assert multiplier == 0.5

    def test_high_impact(self):
        """Hohes Impact Event."""
        assert get_confidence_multiplier(EventImpact.HIGH, 2) == 0.5
        assert get_confidence_multiplier(EventImpact.HIGH, 6) == 0.7
        assert get_confidence_multiplier(EventImpact.HIGH, 10) == 0.85

    def test_low_impact(self):
        """Niedriges Impact Event."""
        assert get_confidence_multiplier(EventImpact.LOW, 1) == 0.9
        assert get_confidence_multiplier(EventImpact.LOW, 20) == 1.0

    def test_past_event_ignored(self):
        """Vergangene Events werden ignoriert."""
        multiplier = get_confidence_multiplier(EventImpact.CRITICAL, -5)
        assert multiplier == 1.0

    def test_no_impact(self):
        """Kein Impact = volle Confidence."""
        assert get_confidence_multiplier(EventImpact.NONE, 0) == 1.0


# =============================================================================
# OPEX CALCULATION TESTS
# =============================================================================

class TestOpexCalculation:
    """Tests für OPEX-Berechnung."""

    def test_january_2025_opex(self):
        """OPEX für Januar 2025."""
        opex = get_monthly_opex(2025, 1)
        assert opex == date(2025, 1, 17)  # 3. Freitag

    def test_march_2025_opex(self):
        """OPEX für März 2025."""
        opex = get_monthly_opex(2025, 3)
        assert opex == date(2025, 3, 21)

    def test_december_2025_opex(self):
        """OPEX für Dezember 2025."""
        opex = get_monthly_opex(2025, 12)
        assert opex == date(2025, 12, 19)

    def test_opex_is_friday(self):
        """OPEX ist immer ein Freitag."""
        for month in range(1, 13):
            opex = get_monthly_opex(2025, month)
            assert opex.weekday() == 4  # Freitag


# =============================================================================
# MACRO EVENTS TESTS
# =============================================================================

class TestMacroEvents:
    """Tests für Makro-Event Generierung."""

    def test_generates_fomc_meetings(self):
        """Generiert FOMC Meetings."""
        events = get_macro_events(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31)
        )

        fomc = [e for e in events if e.event_type == EventType.FED_MEETING]
        assert len(fomc) == 8  # 8 FOMC Meetings 2025

    def test_generates_opex(self):
        """Generiert OPEX Events."""
        events = get_macro_events(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
            include_opex=True
        )

        opex = [e for e in events if e.event_type == EventType.OPEX]
        assert len(opex) == 3  # Jan, Feb, Mar

    def test_without_opex(self):
        """Kann OPEX ausschließen."""
        events = get_macro_events(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
            include_opex=False
        )

        opex = [e for e in events if e.event_type == EventType.OPEX]
        assert len(opex) == 0

    def test_events_sorted_by_date(self):
        """Events sind nach Datum sortiert."""
        events = get_macro_events()
        dates = [e.event_date for e in events]
        assert dates == sorted(dates)


# =============================================================================
# EVENT CALENDAR TESTS
# =============================================================================

class TestEventCalendar:
    """Tests für EventCalendar."""

    def test_create_calendar(self):
        """Erstellt Kalender mit Makro-Events."""
        calendar = EventCalendar(include_macro_events=True)
        stats = calendar.stats()

        assert stats['total_events'] > 0

    def test_add_earnings(self):
        """Fügt Earnings hinzu."""
        calendar = EventCalendar(include_macro_events=False)
        calendar.add_earnings(
            symbol="AAPL",
            earnings_date=date.today() + timedelta(days=30),
            confirmed=True
        )

        events = calendar.get_events_for_symbol("AAPL")
        assert len(events) == 1
        assert events[0].event_type == EventType.EARNINGS

    def test_add_dividend(self):
        """Fügt Dividend hinzu."""
        calendar = EventCalendar(include_macro_events=False)
        calendar.add_dividend(
            symbol="MSFT",
            ex_date=date.today() + timedelta(days=7),
            amount=0.75
        )

        events = calendar.get_events_for_symbol("MSFT")
        assert len(events) == 1
        assert events[0].event_type == EventType.DIVIDEND
        assert events[0].details['amount'] == 0.75

    def test_get_next_earnings(self):
        """Findet nächstes Earnings."""
        calendar = EventCalendar(include_macro_events=False)
        calendar.add_earnings("AAPL", date.today() + timedelta(days=20))
        calendar.add_earnings("AAPL", date.today() + timedelta(days=90))

        next_earnings = calendar.get_next_earnings("AAPL")
        assert next_earnings is not None
        assert next_earnings.days_until == 20

    def test_get_events_includes_market_events(self):
        """Symbol-Abfrage enthält Markt-Events."""
        calendar = EventCalendar(include_macro_events=True)
        calendar.add_earnings("AAPL", date.today() + timedelta(days=10))

        events = calendar.get_events_for_symbol("AAPL")

        # Sollte Earnings UND Makro-Events enthalten
        event_types = [e.event_type for e in events]
        assert EventType.EARNINGS in event_types


# =============================================================================
# VALIDATION TESTS
# =============================================================================

class TestEventValidation:
    """Tests für Event-Validierung."""

    def test_no_events_is_valid(self):
        """Ohne Events ist alles valid."""
        calendar = EventCalendar(include_macro_events=False)
        result = calendar.validate_for_sr("AAPL")

        assert result.is_valid is True
        assert result.confidence_multiplier == 1.0
        assert len(result.blocking_events) == 0

    def test_imminent_earnings_blocks(self):
        """Nahe Earnings blockieren."""
        calendar = EventCalendar(include_macro_events=False)
        calendar.add_earnings("AAPL", date.today() + timedelta(days=2))

        result = calendar.validate_for_sr("AAPL")

        assert result.is_valid is False
        assert len(result.blocking_events) == 1
        assert result.confidence_multiplier < 0.5

    def test_distant_earnings_warns(self):
        """Entfernte Earnings (8-14 Tage) warnen nur."""
        calendar = EventCalendar(include_macro_events=False)
        calendar.add_earnings("AAPL", date.today() + timedelta(days=10))

        result = calendar.validate_for_sr("AAPL")

        # Sollte valid sein aber mit reduzierter Confidence
        # 8-14 Tage für kritische Events: multiplier = 0.7
        assert result.confidence_multiplier < 1.0
        assert result.is_valid is True  # Noch valid, aber mit Vorsicht

    def test_unknown_earnings_warning(self):
        """Warnung wenn Earnings unbekannt."""
        calendar = EventCalendar(include_macro_events=False)
        result = calendar.validate_for_sr("AAPL")

        # Sollte Empfehlung enthalten
        assert any("Earnings-Datum unbekannt" in r for r in result.recommendations)

    def test_validation_to_dict(self):
        """Validation kann zu Dict konvertiert werden."""
        calendar = EventCalendar(include_macro_events=False)
        calendar.add_earnings("AAPL", date.today() + timedelta(days=3))

        result = calendar.validate_for_sr("AAPL")
        d = result.to_dict()

        assert 'is_valid' in d
        assert 'confidence_multiplier' in d
        assert 'blocking_events' in d
        assert 'recommendations' in d


# =============================================================================
# S/R INTEGRATION TESTS
# =============================================================================

class TestSRIntegration:
    """Tests für S/R Integration."""

    def test_validate_sr_levels_without_calendar(self):
        """Funktioniert ohne Calendar."""
        support = [95.0, 90.0]
        resistance = [105.0, 110.0]

        new_support, new_resistance, validation = validate_sr_levels_with_events(
            symbol="AAPL",
            support_levels=support,
            resistance_levels=resistance,
            calendar=None
        )

        assert new_support == support
        assert new_resistance == resistance

    def test_low_confidence_reduces_levels(self):
        """Niedrige Confidence reduziert Level-Anzahl."""
        calendar = EventCalendar(include_macro_events=False)
        calendar.add_earnings("AAPL", date.today() + timedelta(days=2))

        support = [95.0, 90.0, 85.0, 80.0]
        resistance = [105.0, 110.0, 115.0, 120.0]

        new_support, new_resistance, validation = validate_sr_levels_with_events(
            symbol="AAPL",
            support_levels=support,
            resistance_levels=resistance,
            calendar=calendar
        )

        # Bei niedriger Confidence nur wenige Levels
        assert len(new_support) <= 1
        assert len(new_resistance) <= 1
        assert validation.confidence_multiplier < 0.5


# =============================================================================
# FOMC CALENDAR TESTS
# =============================================================================

class TestFOMCCalendar:
    """Tests für FOMC-Kalender Daten."""

    def test_fomc_2025_count(self):
        """8 FOMC Meetings in 2025."""
        assert len(FOMC_MEETINGS_2025) == 8

    def test_fomc_2026_count(self):
        """8 FOMC Meetings in 2026."""
        assert len(FOMC_MEETINGS_2026) == 8

    def test_fomc_dates_valid(self):
        """FOMC Daten sind gültige Daten."""
        for d in FOMC_MEETINGS_2025:
            assert isinstance(d, date)
            assert d.year == 2025

        for d in FOMC_MEETINGS_2026:
            assert isinstance(d, date)
            assert d.year == 2026


# =============================================================================
# DEFAULT IMPACT TESTS
# =============================================================================

class TestDefaultImpact:
    """Tests für Standard-Impact Konfiguration."""

    def test_earnings_is_critical(self):
        """Earnings hat kritischen Impact."""
        assert DEFAULT_EVENT_IMPACT[EventType.EARNINGS] == EventImpact.CRITICAL

    def test_fed_is_high(self):
        """Fed Meeting hat hohen Impact."""
        assert DEFAULT_EVENT_IMPACT[EventType.FED_MEETING] == EventImpact.HIGH

    def test_dividend_is_low(self):
        """Dividend hat niedrigen Impact."""
        assert DEFAULT_EVENT_IMPACT[EventType.DIVIDEND] == EventImpact.LOW

    def test_all_types_have_default(self):
        """Alle Event-Types haben Default-Impact."""
        for event_type in EventType:
            assert event_type in DEFAULT_EVENT_IMPACT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
