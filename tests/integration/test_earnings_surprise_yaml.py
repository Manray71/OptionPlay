"""Regression tests: earnings-surprise thresholds read from YAML.

Verifies that calculate_earnings_surprise_modifier reads threshold values
from config/scoring.yaml, preventing silent drift like OQ-2.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml


def _load_scoring_yaml() -> dict:
    """Load config/scoring.yaml directly (no caching)."""
    config_path = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _es_cfg(key: str):
    """Shortcut: navigate earnings_surprise.thresholds.<key>."""
    data = _load_scoring_yaml()
    return data["earnings_surprise"]["thresholds"][key]


def _make_db(rows: list) -> Path:
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


def _beats(n: int) -> list:
    return [("AAPL", f"2025-{3*i+1:02d}-01", 1.5, 1.0, 0.5) for i in range(n)]


def _misses(n: int) -> list:
    return [("AAPL", f"2025-{3*i+1:02d}-01", 0.8, 1.0, -0.2) for i in range(n)]


class TestEarningsThresholdFromYaml:
    """Verify service reads thresholds from scoring.yaml, not hardcoded values."""

    def test_earnings_threshold_all_beats_from_yaml(self):
        """Module constant _ES_ALL_BEATS matches yaml.all_beats, and is used correctly."""
        from src.services.earnings_quality import _ES_ALL_BEATS, calculate_earnings_surprise_modifier

        expected = _es_cfg("all_beats")
        assert _ES_ALL_BEATS == pytest.approx(expected), (
            f"_ES_ALL_BEATS ({_ES_ALL_BEATS}) != scoring.yaml all_beats ({expected})"
        )

        db = _make_db(_beats(4))
        result = calculate_earnings_surprise_modifier("AAPL", all_beats=expected, db_path=db)
        assert result.modifier == pytest.approx(expected)
        assert result.beats == 4

    def test_earnings_threshold_all_misses_from_yaml(self):
        """get_earnings_surprise_modifier with 4/4 misses returns yaml.all_misses."""
        expected = _es_cfg("all_misses")
        db = _make_db(_misses(4))

        from src.services.earnings_quality import calculate_earnings_surprise_modifier

        result = calculate_earnings_surprise_modifier(
            "AAPL",
            all_misses=expected,
            db_path=db,
        )
        assert result.modifier == pytest.approx(expected)
        assert result.misses == 4

    def test_earnings_n_quarters_from_yaml(self):
        """Module constant _ES_N_QUARTERS matches n_quarters in scoring.yaml."""
        from src.services.earnings_quality import _ES_N_QUARTERS

        yaml_n = _load_scoring_yaml()["earnings_surprise"]["n_quarters"]
        assert _ES_N_QUARTERS == yaml_n, (
            f"_ES_N_QUARTERS ({_ES_N_QUARTERS}) != scoring.yaml n_quarters ({yaml_n})"
        )

    def test_earnings_yaml_section_exists(self):
        """config/scoring.yaml must contain earnings_surprise section."""
        data = _load_scoring_yaml()
        assert "earnings_surprise" in data, "earnings_surprise section missing from scoring.yaml"
        es = data["earnings_surprise"]
        assert "n_quarters" in es
        assert "min_quarters" in es
        assert "thresholds" in es
        thresholds = es["thresholds"]
        for key in ("all_beats", "mostly_beats", "mixed", "mostly_misses", "many_misses", "all_misses"):
            assert key in thresholds, f"thresholds.{key} missing from earnings_surprise config"

    def test_all_beats_value_is_positive(self):
        """all_beats threshold must be positive (beat pattern should boost score)."""
        assert _es_cfg("all_beats") > 0

    def test_all_misses_value_is_negative(self):
        """all_misses threshold must be negative (miss pattern should penalize score)."""
        assert _es_cfg("all_misses") < 0

    def test_thresholds_are_ordered(self):
        """all_beats > mostly_beats > mixed > mostly_misses > many_misses > all_misses."""
        t = _load_scoring_yaml()["earnings_surprise"]["thresholds"]
        assert t["all_beats"] > t["mostly_beats"]
        assert t["mostly_beats"] > t["mixed"]
        assert t["mixed"] > t["mostly_misses"]
        assert t["mostly_misses"] > t["many_misses"]
        assert t["many_misses"] > t["all_misses"]
