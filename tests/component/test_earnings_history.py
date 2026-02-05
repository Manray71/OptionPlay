#!/usr/bin/env python3
"""
Tests für EarningsHistoryManager und historische Earnings-Funktionalität

Usage:
    pytest tests/test_earnings_history.py -v
"""

import pytest
import tempfile
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from src.cache.earnings_history import (
    EarningsHistoryManager,
    EarningsRecord,
    get_earnings_history_manager,
    reset_earnings_history_manager
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_db():
    """Erstellt temporäre DB für Tests"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
    # Cleanup nach Test
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def manager(temp_db):
    """Erstellt Manager mit temporärer DB"""
    return EarningsHistoryManager(db_path=temp_db)


@pytest.fixture
def sample_earnings():
    """Sample Earnings-Daten für Tests"""
    return [
        {
            "earnings_date": "2024-10-31",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q4",
            "eps_actual": 1.64,
            "eps_estimate": 1.60,
            "eps_surprise": 0.04,
            "eps_surprise_pct": 2.5,
            "time_of_day": "amc"
        },
        {
            "earnings_date": "2024-08-01",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q3",
            "eps_actual": 1.40,
            "eps_estimate": 1.35,
            "eps_surprise": 0.05,
            "eps_surprise_pct": 3.7,
            "time_of_day": "amc"
        },
        {
            "earnings_date": "2024-05-02",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q2",
            "eps_actual": 1.53,
            "eps_estimate": 1.50,
            "eps_surprise": 0.03,
            "eps_surprise_pct": 2.0,
            "time_of_day": "amc"
        },
        {
            "earnings_date": "2024-01-25",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q1",
            "eps_actual": 2.18,
            "eps_estimate": 2.10,
            "eps_surprise": 0.08,
            "eps_surprise_pct": 3.8,
            "time_of_day": "amc"
        }
    ]


# =============================================================================
# TABLE CREATION TESTS
# =============================================================================

class TestTableCreation:
    """Tests für Tabellen-Erstellung"""

    def test_table_created(self, manager, temp_db):
        """Prüft ob Tabelle erstellt wurde"""
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='earnings_history'"
        )
        result = cursor.fetchone()
        conn.close()

        assert result is not None
        assert result[0] == "earnings_history"

    def test_indices_created(self, manager, temp_db):
        """Prüft ob Indices erstellt wurden"""
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_eh_%'"
        )
        indices = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "idx_eh_symbol" in indices
        assert "idx_eh_date" in indices
        assert "idx_eh_symbol_date" in indices


# =============================================================================
# SAVE & RETRIEVE TESTS
# =============================================================================

class TestSaveAndRetrieve:
    """Tests für Speichern und Abrufen"""

    def test_save_earnings(self, manager, sample_earnings):
        """Test: Earnings speichern"""
        count = manager.save_earnings("AAPL", sample_earnings)
        assert count == 4

    def test_get_all_earnings(self, manager, sample_earnings):
        """Test: Alle Earnings abrufen"""
        manager.save_earnings("AAPL", sample_earnings)
        earnings = manager.get_all_earnings("AAPL")

        assert len(earnings) == 4
        assert all(isinstance(e, EarningsRecord) for e in earnings)

        # Sollte nach Datum sortiert sein (neueste zuerst)
        assert earnings[0].earnings_date > earnings[-1].earnings_date

    def test_earnings_record_fields(self, manager, sample_earnings):
        """Test: EarningsRecord Felder"""
        manager.save_earnings("AAPL", sample_earnings)
        earnings = manager.get_all_earnings("AAPL")

        latest = earnings[0]
        assert latest.symbol == "AAPL"
        assert latest.earnings_date == date(2024, 10, 31)
        assert latest.fiscal_year == 2024
        assert latest.fiscal_quarter == "Q4"
        assert latest.eps_actual == 1.64
        assert latest.eps_estimate == 1.60
        assert latest.eps_surprise == 0.04
        assert latest.eps_surprise_pct == 2.5
        assert latest.time_of_day == "amc"

    def test_upsert_behavior(self, manager, sample_earnings):
        """Test: UPSERT (Insert or Replace)"""
        # Erste Speicherung
        manager.save_earnings("AAPL", sample_earnings)

        # Update eines Eintrags
        updated = [{
            "earnings_date": "2024-10-31",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q4",
            "eps_actual": 1.70,  # Geändert
            "eps_estimate": 1.60,
            "eps_surprise": 0.10,
            "eps_surprise_pct": 6.25,
            "time_of_day": "amc"
        }]
        manager.save_earnings("AAPL", updated)

        earnings = manager.get_all_earnings("AAPL")
        assert len(earnings) == 4  # Immer noch 4, nicht 5

        latest = earnings[0]
        assert latest.eps_actual == 1.70  # Aktualisiert

    def test_empty_symbol(self, manager):
        """Test: Symbol ohne Earnings"""
        earnings = manager.get_all_earnings("UNKNOWN")
        assert earnings == []


# =============================================================================
# DATE RANGE TESTS
# =============================================================================

class TestDateRangeQueries:
    """Tests für Datumsbereich-Abfragen"""

    def test_get_earnings_in_range(self, manager, sample_earnings):
        """Test: Earnings in Datumsbereich"""
        manager.save_earnings("AAPL", sample_earnings)

        earnings = manager.get_earnings_in_range(
            "AAPL",
            date(2024, 4, 1),
            date(2024, 9, 1)
        )

        assert len(earnings) == 2
        dates = [e.earnings_date for e in earnings]
        assert date(2024, 8, 1) in dates
        assert date(2024, 5, 2) in dates

    def test_get_earnings_around_date(self, manager, sample_earnings):
        """Test: Earnings um Datum herum"""
        manager.save_earnings("AAPL", sample_earnings)

        earnings = manager.get_earnings_around_date(
            "AAPL",
            date(2024, 8, 1),
            days_window=5
        )

        assert len(earnings) == 1
        assert earnings[0].earnings_date == date(2024, 8, 1)


# =============================================================================
# PROXIMITY CHECK TESTS
# =============================================================================

class TestProximityChecks:
    """Tests für Earnings-Nähe-Prüfungen"""

    def test_had_earnings_recently_true(self, manager, sample_earnings):
        """Test: Kürzliche Earnings - positiv"""
        manager.save_earnings("AAPL", sample_earnings)

        # 3 Tage nach Earnings
        result = manager.had_earnings_recently(
            "AAPL",
            date(2024, 11, 3),
            days=5
        )
        assert result is True

    def test_had_earnings_recently_false(self, manager, sample_earnings):
        """Test: Kürzliche Earnings - negativ"""
        manager.save_earnings("AAPL", sample_earnings)

        # 20 Tage nach Earnings
        result = manager.had_earnings_recently(
            "AAPL",
            date(2024, 11, 20),
            days=5
        )
        assert result is False

    def test_will_have_earnings_soon_true(self, manager, sample_earnings):
        """Test: Bevorstehende Earnings - positiv"""
        manager.save_earnings("AAPL", sample_earnings)

        # 3 Tage vor Earnings
        result = manager.will_have_earnings_soon(
            "AAPL",
            date(2024, 10, 28),
            days=5
        )
        assert result is True

    def test_will_have_earnings_soon_false(self, manager, sample_earnings):
        """Test: Bevorstehende Earnings - negativ"""
        manager.save_earnings("AAPL", sample_earnings)

        # 20 Tage vor Earnings
        result = manager.will_have_earnings_soon(
            "AAPL",
            date(2024, 10, 10),
            days=5
        )
        assert result is False

    def test_is_near_earnings(self, manager, sample_earnings):
        """Test: In der Nähe von Earnings"""
        manager.save_earnings("AAPL", sample_earnings)

        # Genau am Earnings-Tag
        assert manager.is_near_earnings("AAPL", date(2024, 10, 31)) is True

        # 2 Tage vorher (innerhalb days_before=5)
        assert manager.is_near_earnings("AAPL", date(2024, 10, 29)) is True

        # 1 Tag danach (innerhalb days_after=2)
        assert manager.is_near_earnings("AAPL", date(2024, 11, 1)) is True

        # 10 Tage vorher (außerhalb)
        assert manager.is_near_earnings("AAPL", date(2024, 10, 20)) is False

    def test_get_nearest_earnings(self, manager, sample_earnings):
        """Test: Nächstes Earnings finden"""
        manager.save_earnings("AAPL", sample_earnings)

        # 2024-09-15 ist näher an 2024-08-01 (45 Tage) als an 2024-10-31 (46 Tage)
        nearest = manager.get_nearest_earnings("AAPL", date(2024, 9, 15))

        assert nearest is not None
        assert nearest.earnings_date == date(2024, 8, 1)  # Näher an Sep 15


# =============================================================================
# STATISTICS TESTS
# =============================================================================

class TestStatistics:
    """Tests für Statistik-Funktionen"""

    def test_get_symbol_count(self, manager, sample_earnings):
        """Test: Anzahl Symbole"""
        manager.save_earnings("AAPL", sample_earnings)
        manager.save_earnings("MSFT", sample_earnings[:2])

        assert manager.get_symbol_count() == 2

    def test_get_total_earnings_count(self, manager, sample_earnings):
        """Test: Gesamtanzahl Earnings"""
        manager.save_earnings("AAPL", sample_earnings)
        manager.save_earnings("MSFT", sample_earnings[:2])

        assert manager.get_total_earnings_count() == 6

    def test_get_symbols_with_earnings(self, manager, sample_earnings):
        """Test: Liste der Symbole"""
        manager.save_earnings("AAPL", sample_earnings)
        manager.save_earnings("MSFT", sample_earnings[:2])
        manager.save_earnings("GOOGL", sample_earnings[:1])

        symbols = manager.get_symbols_with_earnings()
        assert symbols == ["AAPL", "GOOGL", "MSFT"]  # Alphabetisch

    def test_get_date_range(self, manager, sample_earnings):
        """Test: Datumsbereich"""
        manager.save_earnings("AAPL", sample_earnings)

        date_range = manager.get_date_range()
        assert date_range is not None
        assert date_range[0] == "2024-01-25"
        assert date_range[1] == "2024-10-31"

    def test_get_statistics(self, manager, sample_earnings):
        """Test: Statistik-Dict"""
        manager.save_earnings("AAPL", sample_earnings)

        stats = manager.get_statistics()
        assert stats["total_symbols"] == 1
        assert stats["total_earnings"] == 4
        assert stats["date_range"]["from"] == "2024-01-25"
        assert stats["date_range"]["to"] == "2024-10-31"


# =============================================================================
# DELETE TESTS
# =============================================================================

class TestDelete:
    """Tests für Lösch-Funktionen"""

    def test_delete_symbol(self, manager, sample_earnings):
        """Test: Symbol löschen"""
        manager.save_earnings("AAPL", sample_earnings)
        manager.save_earnings("MSFT", sample_earnings[:2])

        deleted = manager.delete_symbol("AAPL")

        assert deleted == 4
        assert manager.get_symbol_count() == 1
        assert manager.get_all_earnings("AAPL") == []
        assert len(manager.get_all_earnings("MSFT")) == 2

    def test_clear_all(self, manager, sample_earnings):
        """Test: Alle löschen"""
        manager.save_earnings("AAPL", sample_earnings)
        manager.save_earnings("MSFT", sample_earnings[:2])

        deleted = manager.clear_all()

        assert deleted == 6
        assert manager.get_symbol_count() == 0
        assert manager.get_total_earnings_count() == 0


# =============================================================================
# EARNINGS RECORD TESTS
# =============================================================================

class TestEarningsRecord:
    """Tests für EarningsRecord Dataclass"""

    def test_to_dict(self):
        """Test: to_dict Konvertierung"""
        record = EarningsRecord(
            symbol="AAPL",
            earnings_date=date(2024, 10, 31),
            fiscal_year=2024,
            fiscal_quarter="Q4",
            eps_actual=1.64,
            eps_estimate=1.60,
            eps_surprise=0.04,
            eps_surprise_pct=2.5,
            time_of_day="amc"
        )

        d = record.to_dict()

        assert d["symbol"] == "AAPL"
        assert d["earnings_date"] == "2024-10-31"
        assert d["fiscal_year"] == 2024
        assert d["fiscal_quarter"] == "Q4"
        assert d["eps_actual"] == 1.64


# =============================================================================
# SINGLETON TESTS
# =============================================================================

class TestSingleton:
    """Tests für Singleton-Pattern"""

    def test_singleton_returns_same_instance(self):
        """Test: Singleton gibt gleiche Instanz"""
        reset_earnings_history_manager()

        manager1 = get_earnings_history_manager()
        manager2 = get_earnings_history_manager()

        assert manager1 is manager2

    def test_reset_creates_new_instance(self):
        """Test: Reset erstellt neue Instanz"""
        manager1 = get_earnings_history_manager()
        reset_earnings_history_manager()
        manager2 = get_earnings_history_manager()

        assert manager1 is not manager2


# =============================================================================
# BMO/AMC TESTS (DEBT-014: Earnings-Filter mit Time-of-Day Handling)
# =============================================================================

class TestBmoAmcHandling:
    """Tests für BMO/AMC Earnings-Handling

    BMO (Before Market Open): Earnings vor Markteröffnung
    - Am Earnings-Tag selbst: Kurs hat bereits reagiert, kann sicher sein (optional)

    AMC (After Market Close): Earnings nach Marktschluss
    - Am Earnings-Tag selbst: NICHT sicher, Reaktion erst am nächsten Tag
    """

    @pytest.fixture
    def future_earnings_amc(self):
        """Zukünftige AMC Earnings (after close)"""
        # Wir erstellen Earnings für "heute + X Tage"
        today = date.today()
        return [
            {
                "earnings_date": (today + timedelta(days=0)).isoformat(),  # Heute
                "fiscal_year": 2026,
                "fiscal_quarter": "Q1",
                "eps_actual": None,
                "eps_estimate": 1.50,
                "time_of_day": "after close"  # AMC
            },
            {
                "earnings_date": (today + timedelta(days=30)).isoformat(),  # In 30 Tagen
                "fiscal_year": 2026,
                "fiscal_quarter": "Q2",
                "eps_actual": None,
                "eps_estimate": 1.55,
                "time_of_day": "after close"
            },
        ]

    @pytest.fixture
    def future_earnings_bmo(self):
        """Zukünftige BMO Earnings (before open)"""
        today = date.today()
        return [
            {
                "earnings_date": (today + timedelta(days=0)).isoformat(),  # Heute
                "fiscal_year": 2026,
                "fiscal_quarter": "Q1",
                "eps_actual": None,
                "eps_estimate": 1.50,
                "time_of_day": "before open"  # BMO
            },
        ]

    @pytest.fixture
    def future_earnings_safe(self):
        """Zukünftige Earnings mit sicherem Abstand"""
        today = date.today()
        return [
            {
                "earnings_date": (today + timedelta(days=60)).isoformat(),  # In 60 Tagen
                "fiscal_year": 2026,
                "fiscal_quarter": "Q2",
                "eps_actual": None,
                "eps_estimate": 1.55,
                "time_of_day": "after close"
            },
        ]

    def test_get_next_future_earnings(self, manager, future_earnings_amc):
        """Test: Nächstes zukünftiges Earnings finden"""
        manager.save_earnings("TEST", future_earnings_amc)
        today = date.today()

        next_earn = manager.get_next_future_earnings("TEST", today)

        assert next_earn is not None
        assert next_earn.earnings_date == today
        assert next_earn.time_of_day == "after close"

    def test_get_next_future_earnings_none_when_empty(self, manager):
        """Test: None wenn keine zukünftigen Earnings"""
        next_earn = manager.get_next_future_earnings("UNKNOWN", date.today())
        assert next_earn is None

    def test_is_earnings_day_safe_amc_today_unsafe(self, manager, future_earnings_amc):
        """Test: AMC am selben Tag = NICHT sicher"""
        manager.save_earnings("TEST", future_earnings_amc)
        today = date.today()

        is_safe, days_to, reason = manager.is_earnings_day_safe(
            "TEST", today, min_days=45, allow_bmo_same_day=False
        )

        assert is_safe is False
        assert days_to == 0
        assert reason == "earnings_amc_today"

    def test_is_earnings_day_safe_bmo_today_conservative(self, manager, future_earnings_bmo):
        """Test: BMO am selben Tag = NICHT sicher (konservativ)"""
        manager.save_earnings("TEST", future_earnings_bmo)
        today = date.today()

        is_safe, days_to, reason = manager.is_earnings_day_safe(
            "TEST", today, min_days=45, allow_bmo_same_day=False
        )

        assert is_safe is False
        assert days_to == 0
        assert reason == "earnings_bmo_today_conservative"

    def test_is_earnings_day_safe_bmo_today_allowed(self, manager, future_earnings_bmo):
        """Test: BMO am selben Tag = sicher wenn erlaubt"""
        manager.save_earnings("TEST", future_earnings_bmo)
        today = date.today()

        is_safe, days_to, reason = manager.is_earnings_day_safe(
            "TEST", today, min_days=45, allow_bmo_same_day=True  # Erlaubt
        )

        assert is_safe is True
        assert days_to == 0
        assert reason == "earnings_bmo_today_allowed"

    def test_is_earnings_day_safe_sufficient_days(self, manager, future_earnings_safe):
        """Test: Ausreichend Abstand = sicher"""
        manager.save_earnings("TEST", future_earnings_safe)
        today = date.today()

        is_safe, days_to, reason = manager.is_earnings_day_safe(
            "TEST", today, min_days=45, allow_bmo_same_day=False
        )

        assert is_safe is True
        assert days_to == 60
        assert reason == "safe"

    def test_is_earnings_day_safe_too_close(self, manager):
        """Test: Zu nahe Earnings = nicht sicher"""
        today = date.today()
        # Earnings in 20 Tagen (unter min_days=45)
        earnings_data = [
            {
                "earnings_date": (today + timedelta(days=20)).isoformat(),
                "time_of_day": "after close"
            }
        ]
        manager.save_earnings("TEST", earnings_data)

        is_safe, days_to, reason = manager.is_earnings_day_safe(
            "TEST", today, min_days=45, allow_bmo_same_day=False
        )

        assert is_safe is False
        assert days_to == 20
        assert "too_close" in reason

    def test_is_earnings_day_safe_no_data(self, manager):
        """Test: Keine Earnings-Daten = nicht sicher (konservativ)"""
        is_safe, days_to, reason = manager.is_earnings_day_safe(
            "UNKNOWN", date.today(), min_days=45, allow_bmo_same_day=False
        )

        assert is_safe is False
        assert days_to is None
        assert reason == "no_earnings_data"

    def test_is_earnings_day_safe_unknown_time_today(self, manager):
        """Test: Earnings heute mit unbekannter Zeit = nicht sicher"""
        today = date.today()
        earnings_data = [
            {
                "earnings_date": today.isoformat(),
                "time_of_day": None  # Unbekannt
            }
        ]
        manager.save_earnings("TEST", earnings_data)

        is_safe, days_to, reason = manager.is_earnings_day_safe(
            "TEST", today, min_days=45, allow_bmo_same_day=False
        )

        assert is_safe is False
        assert days_to == 0
        assert reason == "earnings_today_unknown_time"


# =============================================================================
# BATCH METHOD TESTS (DEBT-003: N+1 Query Optimization)
# =============================================================================

class TestBatchMethods:
    """Tests for batch query methods that avoid N+1 patterns"""

    def test_is_earnings_day_safe_batch_empty(self, manager):
        """Test: Empty symbols list returns empty dict"""
        result = manager.is_earnings_day_safe_batch([], date.today())
        assert result == {}

    def test_is_earnings_day_safe_batch_single_symbol(self, manager):
        """Test: Single symbol batch matches individual call"""
        today = date.today()
        earnings_data = [
            {
                "earnings_date": (today + timedelta(days=60)).isoformat(),
                "time_of_day": "after close"
            }
        ]
        manager.save_earnings("AAPL", earnings_data)

        # Individual call
        individual = manager.is_earnings_day_safe("AAPL", today, min_days=45)

        # Batch call
        batch = manager.is_earnings_day_safe_batch(["AAPL"], today, min_days=45)

        assert batch["AAPL"] == individual

    def test_is_earnings_day_safe_batch_multiple_symbols(self, manager):
        """Test: Multiple symbols in one batch query"""
        today = date.today()

        # Setup: Different earnings scenarios for each symbol
        # AAPL: Safe (60 days out)
        manager.save_earnings("AAPL", [
            {"earnings_date": (today + timedelta(days=60)).isoformat(), "time_of_day": "amc"}
        ])
        # MSFT: Too close (20 days)
        manager.save_earnings("MSFT", [
            {"earnings_date": (today + timedelta(days=20)).isoformat(), "time_of_day": "amc"}
        ])
        # GOOGL: Today AMC (not safe)
        manager.save_earnings("GOOGL", [
            {"earnings_date": today.isoformat(), "time_of_day": "after close"}
        ])
        # TSLA: No earnings data

        batch = manager.is_earnings_day_safe_batch(
            ["AAPL", "MSFT", "GOOGL", "TSLA"],
            today, min_days=45, allow_bmo_same_day=False
        )

        # AAPL: Safe
        assert batch["AAPL"][0] is True
        assert batch["AAPL"][1] == 60
        assert batch["AAPL"][2] == "safe"

        # MSFT: Too close
        assert batch["MSFT"][0] is False
        assert batch["MSFT"][1] == 20
        assert "too_close" in batch["MSFT"][2]

        # GOOGL: Today AMC
        assert batch["GOOGL"][0] is False
        assert batch["GOOGL"][1] == 0
        assert batch["GOOGL"][2] == "earnings_amc_today"

        # TSLA: No data
        assert batch["TSLA"][0] is False
        assert batch["TSLA"][1] is None
        assert batch["TSLA"][2] == "no_earnings_data"

    def test_is_earnings_day_safe_batch_case_insensitive(self, manager):
        """Test: Symbol lookup is case-insensitive"""
        today = date.today()
        manager.save_earnings("AAPL", [
            {"earnings_date": (today + timedelta(days=60)).isoformat(), "time_of_day": "amc"}
        ])

        # Query with lowercase
        batch = manager.is_earnings_day_safe_batch(["aapl"], today, min_days=45)

        # Result should be uppercase
        assert "AAPL" in batch
        assert batch["AAPL"][0] is True

    def test_is_earnings_day_safe_batch_bmo_handling(self, manager):
        """Test: BMO handling in batch mode"""
        today = date.today()
        manager.save_earnings("BMO_TEST", [
            {"earnings_date": today.isoformat(), "time_of_day": "before open"}
        ])

        # Without allow_bmo_same_day
        batch_conservative = manager.is_earnings_day_safe_batch(
            ["BMO_TEST"], today, min_days=45, allow_bmo_same_day=False
        )
        assert batch_conservative["BMO_TEST"][0] is False
        assert batch_conservative["BMO_TEST"][2] == "earnings_bmo_today_conservative"

        # With allow_bmo_same_day
        batch_allowed = manager.is_earnings_day_safe_batch(
            ["BMO_TEST"], today, min_days=45, allow_bmo_same_day=True
        )
        assert batch_allowed["BMO_TEST"][0] is True
        assert batch_allowed["BMO_TEST"][2] == "earnings_bmo_today_allowed"

    def test_is_earnings_day_safe_batch_picks_nearest_future(self, manager):
        """Test: Batch correctly picks nearest future earnings, not past"""
        today = date.today()
        # Two future earnings - should pick the nearest (30 days, not 90 days)
        manager.save_earnings("TEST", [
            {"earnings_date": (today + timedelta(days=30)).isoformat(), "time_of_day": "amc"},
            {"earnings_date": (today + timedelta(days=90)).isoformat(), "time_of_day": "amc"},
        ])

        batch = manager.is_earnings_day_safe_batch(["TEST"], today, min_days=45)

        assert batch["TEST"][0] is False  # 30 days < 45 min_days
        assert batch["TEST"][1] == 30  # Nearest is 30 days

    @pytest.mark.asyncio
    async def test_is_earnings_day_safe_batch_async(self, manager):
        """Test: Async batch wrapper works correctly"""
        today = date.today()
        manager.save_earnings("AAPL", [
            {"earnings_date": (today + timedelta(days=60)).isoformat(), "time_of_day": "amc"}
        ])

        batch = await manager.is_earnings_day_safe_batch_async(
            ["AAPL"], today, min_days=45
        )

        assert "AAPL" in batch
        assert batch["AAPL"][0] is True
        assert batch["AAPL"][1] == 60
