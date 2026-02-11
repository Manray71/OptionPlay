# OptionPlay - VIX Cache Tests
# ==============================
# Tests für src/cache/vix_cache.py

import pytest
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
import datetime as dt
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cache.vix_cache import (
    VixCacheManager,
    VixDataPoint,
    get_vix_manager,
    reset_vix_manager,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_db():
    """Create a temporary database with VIX data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE vix_data (
            date TEXT PRIMARY KEY,
            value REAL NOT NULL,
            created_at TEXT
        )
    """)

    # Insert test data (10 days)
    base_date = date(2026, 1, 20)
    vix_values = [18.5, 19.2, 20.1, 19.8, 21.3, 22.0, 20.5, 19.0, 18.0, 17.5]

    for i, vix in enumerate(vix_values):
        d = base_date + timedelta(days=i)
        conn.execute(
            "INSERT INTO vix_data (date, value) VALUES (?, ?)",
            (d.isoformat(), vix)
        )

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)


@pytest.fixture
def manager(temp_db):
    """Create a VixCacheManager with temp database."""
    return VixCacheManager(db_path=temp_db)


@pytest.fixture
def empty_manager(tmp_path):
    """Create a VixCacheManager with empty database."""
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE vix_data (
            date TEXT PRIMARY KEY,
            value REAL NOT NULL,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    return VixCacheManager(db_path=db_path)


# =============================================================================
# VixDataPoint Tests
# =============================================================================

class TestVixDataPoint:
    """Tests für VixDataPoint dataclass."""

    def test_create_datapoint(self):
        """Test: VixDataPoint erstellen."""
        dp = VixDataPoint(date=date(2026, 1, 30), value=19.5)

        assert dp.date == date(2026, 1, 30)
        assert dp.value == 19.5

    def test_datapoint_equality(self):
        """Test: VixDataPoint Gleichheit."""
        dp1 = VixDataPoint(date=date(2026, 1, 30), value=19.5)
        dp2 = VixDataPoint(date=date(2026, 1, 30), value=19.5)

        assert dp1 == dp2


# =============================================================================
# VixCacheManager Initialization Tests
# =============================================================================

class TestVixCacheManagerInit:
    """Tests für VixCacheManager Initialisierung."""

    def test_init_with_default_path(self):
        """Test: Manager mit Default-Pfad erstellen."""
        manager = VixCacheManager()

        assert manager.db_path is not None
        assert "trades.db" in str(manager.db_path)

    def test_init_with_custom_path(self, temp_db):
        """Test: Manager mit Custom-Pfad erstellen."""
        manager = VixCacheManager(db_path=temp_db)

        assert manager.db_path == temp_db

    def test_init_has_lock(self, manager):
        """Test: Manager has a thread-safe lock initialized."""
        assert hasattr(manager, '_lock')
        assert manager._lock is not None


# =============================================================================
# Database Existence Tests
# =============================================================================

class TestDatabaseExistence:
    """Tests für DB-Existenz-Prüfung."""

    def test_db_exists(self, manager):
        """Test: DB existiert."""
        assert manager._ensure_db_exists() == True

    def test_db_not_exists(self, tmp_path):
        """Test: DB existiert nicht."""
        non_existent = tmp_path / "nonexistent.db"
        manager = VixCacheManager(db_path=non_existent)

        assert manager._ensure_db_exists() == False


# =============================================================================
# get_latest_vix Tests
# =============================================================================

class TestGetLatestVix:
    """Tests für get_latest_vix()."""

    def test_get_latest_vix(self, manager):
        """Test: Letzten VIX abrufen."""
        vix = manager.get_latest_vix()

        assert vix is not None
        assert vix == 17.5  # Letzter Wert in unseren Testdaten

    def test_get_latest_vix_empty_db(self, empty_manager):
        """Test: Letzten VIX bei leerer DB."""
        vix = empty_manager.get_latest_vix()

        assert vix is None

    def test_get_latest_vix_no_db(self, tmp_path):
        """Test: Letzten VIX ohne DB."""
        manager = VixCacheManager(db_path=tmp_path / "missing.db")
        vix = manager.get_latest_vix()

        assert vix is None


# =============================================================================
# get_vix_at_date Tests
# =============================================================================

class TestGetVixAtDate:
    """Tests für get_vix_at_date()."""

    def test_get_vix_exact_date(self, manager):
        """Test: VIX für exaktes Datum."""
        vix = manager.get_vix_at_date(date(2026, 1, 20))

        assert vix == 18.5  # Erster Wert

    def test_get_vix_fallback_to_previous(self, manager):
        """Test: Fallback zu vorherigem Datum."""
        # 2026-01-31 gibt es nicht - sollte 2026-01-29 (17.5) nehmen
        vix = manager.get_vix_at_date(date(2026, 1, 31))

        assert vix == 17.5

    def test_get_vix_before_data_start(self, manager):
        """Test: Datum vor Daten-Start."""
        vix = manager.get_vix_at_date(date(2025, 1, 1))

        assert vix is None

    def test_get_vix_empty_db(self, empty_manager):
        """Test: VIX bei leerer DB."""
        vix = empty_manager.get_vix_at_date(date(2026, 1, 20))

        assert vix is None


# =============================================================================
# get_vix_range Tests
# =============================================================================

class TestGetVixRange:
    """Tests für get_vix_range()."""

    def test_get_range(self, manager):
        """Test: VIX-Range abrufen."""
        range_data = manager.get_vix_range()

        assert range_data is not None
        first, last = range_data
        assert first == date(2026, 1, 20)
        assert last == date(2026, 1, 29)

    def test_get_range_empty_db(self, empty_manager):
        """Test: Range bei leerer DB."""
        range_data = empty_manager.get_vix_range()

        assert range_data is None


# =============================================================================
# get_vix_count Tests
# =============================================================================

class TestGetVixCount:
    """Tests für get_vix_count()."""

    def test_get_count(self, manager):
        """Test: VIX-Count abrufen."""
        count = manager.get_vix_count()

        assert count == 10  # 10 Testdaten-Einträge

    def test_get_count_empty_db(self, empty_manager):
        """Test: Count bei leerer DB."""
        count = empty_manager.get_vix_count()

        assert count == 0


# =============================================================================
# get_vix_history Tests
# =============================================================================

class TestGetVixHistory:
    """Tests für get_vix_history()."""

    def test_get_history_default(self, manager):
        """Test: VIX-History (Default 10 Tage)."""
        history = manager.get_vix_history()

        assert len(history) == 10
        # Oldest first
        assert history[0] == 18.5
        assert history[-1] == 17.5

    def test_get_history_limited(self, manager):
        """Test: VIX-History mit Limit."""
        history = manager.get_vix_history(days=5)

        assert len(history) == 5
        # Die letzten 5 Tage (oldest first)
        assert history == [22.0, 20.5, 19.0, 18.0, 17.5]

    def test_get_history_empty_db(self, empty_manager):
        """Test: History bei leerer DB."""
        history = empty_manager.get_vix_history()

        assert history == []


# =============================================================================
# get_vix_statistics Tests
# =============================================================================

class TestGetVixStatistics:
    """Tests für get_vix_statistics()."""

    def test_get_statistics(self, manager):
        """Test: VIX-Statistiken abrufen."""
        stats = manager.get_vix_statistics(days=10)

        assert stats is not None
        assert stats['current'] == 17.5  # Letzter Wert
        assert stats['min'] == 17.5
        assert stats['max'] == 22.0
        assert 18 < stats['mean'] < 20  # Durchschnitt ca. 19.59
        assert stats['days_analyzed'] == 10

    def test_get_statistics_limited(self, manager):
        """Test: VIX-Statistiken mit Limit."""
        stats = manager.get_vix_statistics(days=5)

        assert stats is not None
        assert stats['days_analyzed'] == 5

    def test_get_statistics_empty_db(self, empty_manager):
        """Test: Statistiken bei leerer DB."""
        stats = empty_manager.get_vix_statistics()

        assert stats is None


# =============================================================================
# find_gaps Tests
# =============================================================================

class TestFindGaps:
    """Tests für find_gaps()."""

    def test_find_gaps_no_db(self, tmp_path):
        """Test: Gaps ohne DB."""
        manager = VixCacheManager(db_path=tmp_path / "missing.db")
        gaps = manager.find_gaps()

        assert gaps == []

    def test_find_gaps_empty_db(self, empty_manager):
        """Test: Gaps bei leerer DB (alle Tage fehlen)."""
        gaps = empty_manager.find_gaps(days_back=5)

        # Sollte alle Werktage der letzten 5 Tage enthalten
        assert isinstance(gaps, list)


# =============================================================================
# is_data_stale Tests
# =============================================================================

class TestIsDataStale:
    """Tests für is_data_stale()."""

    def test_data_stale_old_data(self, manager):
        """Test: Daten sind stale (alt)."""
        # Unsere Testdaten gehen bis 2026-01-29
        # Heute ist 2026-02-01 - das sind 3 Tage
        is_stale = manager.is_data_stale(max_age_days=2)

        assert is_stale == True

    def test_data_stale_fresh_data(self, manager):
        """Test: Daten sind frisch (fixture data ends 2026-01-29)."""
        # Mock date.today() to 1 day after fixture data to avoid flakiness
        with patch('src.cache.vix_cache.date') as mock_date:
            mock_date.today.return_value = date(2026, 1, 30)
            mock_date.fromisoformat.side_effect = dt.date.fromisoformat
            is_stale = manager.is_data_stale(max_age_days=10)

        assert is_stale == False

    def test_data_stale_no_data(self, empty_manager):
        """Test: Stale bei leerer DB."""
        is_stale = empty_manager.is_data_stale()

        assert is_stale == True


# =============================================================================
# Singleton Tests
# =============================================================================

class TestSingleton:
    """Tests für Singleton-Pattern."""

    def test_get_vix_manager_returns_same_instance(self):
        """Test: get_vix_manager gibt gleiche Instanz zurück."""
        reset_vix_manager()

        m1 = get_vix_manager()
        m2 = get_vix_manager()

        assert m1 is m2

    def test_reset_vix_manager(self):
        """Test: reset_vix_manager setzt Singleton zurück."""
        m1 = get_vix_manager()
        reset_vix_manager()
        m2 = get_vix_manager()

        assert m1 is not m2

    def test_cleanup(self):
        """Cleanup: Singleton zurücksetzen."""
        reset_vix_manager()


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests für Grenzfälle."""

    def test_vix_value_types(self, temp_db):
        """Test: VIX-Werte sind Floats."""
        manager = VixCacheManager(db_path=temp_db)

        vix = manager.get_latest_vix()
        assert isinstance(vix, float)

        history = manager.get_vix_history()
        assert all(isinstance(v, float) for v in history)

    def test_date_iso_format(self, temp_db):
        """Test: Daten werden korrekt als ISO-Format behandelt."""
        manager = VixCacheManager(db_path=temp_db)

        vix = manager.get_vix_at_date(date(2026, 1, 25))
        assert vix is not None

    def test_large_history_request(self, manager):
        """Test: Große History-Anfrage (mehr als vorhanden)."""
        history = manager.get_vix_history(days=1000)

        # Sollte nur die vorhandenen 10 Einträge zurückgeben
        assert len(history) == 10

    def test_statistics_single_value(self, tmp_path):
        """Test: Statistiken mit nur einem Wert."""
        db_path = tmp_path / "single.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE vix_data (
                date TEXT PRIMARY KEY,
                value REAL NOT NULL,
                created_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO vix_data (date, value) VALUES (?, ?)",
            (date(2026, 1, 30).isoformat(), 20.0)
        )
        conn.commit()
        conn.close()

        manager = VixCacheManager(db_path=db_path)
        stats = manager.get_vix_statistics()

        assert stats is not None
        assert stats['current'] == 20.0
        assert stats['min'] == 20.0
        assert stats['max'] == 20.0
        assert stats['stdev'] == 0  # Nur ein Wert


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
