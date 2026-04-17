"""Unit tests for src/services/earnings_quality.py.

Uses in-memory SQLite to avoid touching the production DB.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.services.earnings_quality import (
    EarningsSurpriseResult,
    calculate_earnings_surprise_modifier,
    get_earnings_surprise_modifier,
    get_recent_earnings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(rows: list) -> Path:
    """Create a temp SQLite DB with earnings_history rows.

    rows: [(symbol, earnings_date, eps_actual, eps_estimate, eps_surprise), ...]
    """
    tmp = tempfile.mktemp(suffix=".db")
    path = Path(tmp)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE earnings_history (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               symbol TEXT NOT NULL,
               earnings_date DATE NOT NULL,
               eps_actual REAL,
               eps_estimate REAL,
               eps_surprise REAL
           )"""
    )
    conn.executemany(
        "INSERT INTO earnings_history (symbol, earnings_date, eps_actual, eps_estimate, eps_surprise) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return path


def _beats(n: int, symbol: str = "AAPL") -> list:
    """n beat rows (eps_actual > eps_estimate)."""
    return [
        (symbol, f"2025-{3*i+1:02d}-01", 1.5, 1.0, 0.5)
        for i in range(n)
    ]


def _misses(n: int, symbol: str = "AAPL") -> list:
    """n miss rows (eps_actual < eps_estimate)."""
    return [
        (symbol, f"2025-{3*i+1:02d}-01", 0.8, 1.0, -0.2)
        for i in range(n)
    ]


def _meets(n: int, symbol: str = "AAPL") -> list:
    """n meet rows (eps_actual == eps_estimate)."""
    return [
        (symbol, f"2025-{3*i+1:02d}-01", 1.0, 1.0, 0.0)
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAllBeats:
    def test_all_beats_4_of_4(self):
        db = _make_db(_beats(4))
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.modifier == pytest.approx(1.2)
        assert result.beats == 4
        assert result.misses == 0
        assert result.total == 4
        assert "4/4 beats" in result.pattern

    def test_all_beats_returns_correct_dataclass_type(self):
        db = _make_db(_beats(4))
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert isinstance(result, EarningsSurpriseResult)


class TestMostlyBeats:
    def test_mostly_beats_3_of_4(self):
        """3 beats + 0 misses + 1 meet → mostly_beats."""
        rows = _beats(3) + _meets(1)
        db = _make_db(rows)
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.modifier == pytest.approx(0.6)
        assert result.beats == 3
        assert result.misses == 0
        assert "3/4 beats" in result.pattern


class TestMixed:
    def test_mixed_2_beats_2_misses(self):
        """2 beats, 2 misses: beats == misses → not mostly_misses → mixed."""
        rows = _beats(2) + _misses(2)
        db = _make_db(rows)
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.modifier == pytest.approx(0.0)

    def test_mixed_1_beat_1_miss_2_meets(self):
        rows = _beats(1) + _misses(1) + _meets(2)
        db = _make_db(rows)
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.modifier == pytest.approx(0.0)


class TestMostlyMisses:
    def test_mostly_misses_1_beat_2_misses_1_meet(self):
        """1 beat, 2 misses, 1 meet → misses > beats → mostly_misses (-1.0)."""
        rows = _beats(1) + _misses(2) + _meets(1)
        db = _make_db(rows)
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.modifier == pytest.approx(-1.0)
        assert result.misses == 2
        assert result.beats == 1

    def test_mostly_misses_uses_correct_threshold(self):
        """Custom mostly_misses threshold is respected."""
        rows = _beats(1) + _misses(2) + _meets(1)
        db = _make_db(rows)
        result = calculate_earnings_surprise_modifier("AAPL", mostly_misses=-5.0, db_path=db)
        assert result.modifier == pytest.approx(-5.0)


class TestManyMisses:
    def test_many_misses_3_of_4(self):
        """3 misses out of 4 → many_misses (-1.8)."""
        rows = _beats(1) + _misses(3)
        db = _make_db(rows)
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.modifier == pytest.approx(-1.8)
        assert result.misses == 3
        assert "3/4 misses" in result.pattern


class TestAllMisses:
    def test_all_misses_4_of_4(self):
        db = _make_db(_misses(4))
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.modifier == pytest.approx(-2.8)
        assert result.beats == 0
        assert result.misses == 4
        assert "4/4 misses" in result.pattern

    def test_all_misses_custom_threshold(self):
        db = _make_db(_misses(4))
        result = calculate_earnings_surprise_modifier("AAPL", all_misses=-9.9, db_path=db)
        assert result.modifier == pytest.approx(-9.9)


class TestInsufficientData:
    def test_insufficient_data_3_quarters_min_4(self):
        """3 rows when min_quarters=4 → neutral modifier 0.0."""
        db = _make_db(_beats(3))
        result = calculate_earnings_surprise_modifier("AAPL", n_quarters=4, min_quarters=4, db_path=db)
        assert result.modifier == pytest.approx(0.0)
        assert result.total == 3
        assert "insufficient" in result.pattern

    def test_zero_quarters(self):
        """No rows at all → neutral."""
        db = _make_db([])
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.modifier == pytest.approx(0.0)
        assert result.total == 0

    def test_nonexistent_db_returns_neutral(self):
        """Missing DB → neutral."""
        result = calculate_earnings_surprise_modifier(
            "AAPL", db_path=Path("/nonexistent/path/db.sqlite")
        )
        assert result.modifier == pytest.approx(0.0)


class TestMeetsCount:
    def test_meets_count_correct(self):
        """eps_actual == eps_estimate counts as meet, not beat or miss."""
        rows = _beats(2) + _meets(2)
        db = _make_db(rows)
        result = calculate_earnings_surprise_modifier("AAPL", db_path=db)
        assert result.meets == 2
        assert result.beats == 2
        assert result.misses == 0
        # 0 misses, beats(2) not >= total-1(3) → falls through to mixed
        assert result.modifier == pytest.approx(0.0)


class TestGetRecentEarnings:
    def test_returns_sorted_descending(self):
        """Most recent row should come first."""
        rows = [
            ("AAPL", "2024-01-01", 1.0, 0.9, 0.1),
            ("AAPL", "2024-04-01", 1.1, 1.0, 0.1),
            ("AAPL", "2024-07-01", 1.2, 1.1, 0.1),
            ("AAPL", "2024-10-01", 1.3, 1.2, 0.1),
        ]
        db = _make_db(rows)
        result = get_recent_earnings("AAPL", n=4, db_path=db)
        dates = [r[0] for r in result]
        assert dates == sorted(dates, reverse=True)

    def test_excludes_null_eps(self):
        """Rows with NULL eps_actual or eps_estimate are excluded."""
        conn_path = tempfile.mktemp(suffix=".db")
        path = Path(conn_path)
        conn = sqlite3.connect(str(path))
        conn.execute(
            """CREATE TABLE earnings_history (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   symbol TEXT, earnings_date DATE,
                   eps_actual REAL, eps_estimate REAL, eps_surprise REAL
               )"""
        )
        conn.executemany(
            "INSERT INTO earnings_history VALUES (NULL, ?, ?, ?, ?, ?)",
            [
                ("AAPL", "2024-01-01", None, 1.0, None),   # NULL actual → excluded
                ("AAPL", "2024-04-01", 1.1, None, None),   # NULL estimate → excluded
                ("AAPL", "2024-07-01", 1.2, 1.1, 0.1),     # valid
            ],
        )
        conn.commit()
        conn.close()
        rows = get_recent_earnings("AAPL", n=4, db_path=path)
        assert len(rows) == 1


class TestConvenienceWrapper:
    def test_get_earnings_surprise_modifier_returns_float(self):
        db = _make_db(_beats(4))
        val = get_earnings_surprise_modifier("AAPL", db_path=db)
        assert isinstance(val, float)

    def test_get_earnings_surprise_modifier_all_beats(self):
        db = _make_db(_beats(4))
        val = get_earnings_surprise_modifier("AAPL", db_path=db)
        assert val == pytest.approx(1.2)

    def test_get_earnings_surprise_modifier_missing_db(self):
        val = get_earnings_surprise_modifier("AAPL", db_path=Path("/no/db.sqlite"))
        assert val == pytest.approx(0.0)
