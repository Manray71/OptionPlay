"""
Security Tests for outcome_storage.py — SQL Injection Prevention (A.3)

Tests that SQL injection attempts are properly blocked via:
- A.3a: LIMIT parameter is parameterized (not f-string)
- A.3b: ALTER TABLE column names validated against whitelist
- A.3c: Strategy name validated against whitelist
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.backtesting.simulation.outcome_storage import (
    VALID_STRATEGIES,
    VALID_COMPONENT_COLUMNS,
    _validate_db_path,
    create_outcome_database,
    get_trades_without_scores,
    load_outcomes_with_scores,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_outcomes.db"
        conn = create_outcome_database(db_path)
        # Insert a test trade
        conn.execute("""
            INSERT INTO trade_outcomes (
                symbol, entry_date, exit_date, expiration,
                entry_price, short_strike, long_strike, spread_width,
                net_credit, dte_at_entry, short_otm_pct,
                exit_price, outcome, pnl, pnl_pct, was_profitable
            ) VALUES (
                'AAPL', '2025-01-15', '2025-02-15', '2025-03-15',
                175.0, 165.0, 160.0, 5.0,
                1.50, 60, 5.7,
                0.05, 'max_profit', 145.0, 96.7, 1
            )
        """)
        conn.commit()
        conn.close()
        yield db_path


class TestSQLInjectionLIMIT:
    """A.3a: LIMIT parameter must be parameterized."""

    def test_limit_with_valid_int(self, temp_db):
        """Normal integer limit should work."""
        rows = get_trades_without_scores(db_path=temp_db, limit=10)
        assert isinstance(rows, list)

    def test_limit_with_zero(self, temp_db):
        """Zero limit should return all (falsy value skips LIMIT)."""
        rows = get_trades_without_scores(db_path=temp_db, limit=0)
        assert isinstance(rows, list)

    def test_limit_with_none(self, temp_db):
        """None limit should return all."""
        rows = get_trades_without_scores(db_path=temp_db, limit=None)
        assert isinstance(rows, list)

    def test_limit_sql_injection_string(self, temp_db):
        """SQL injection via string in limit should raise."""
        with pytest.raises((ValueError, TypeError)):
            get_trades_without_scores(db_path=temp_db, limit="10; DROP TABLE trade_outcomes;--")

    def test_limit_sql_injection_negative(self, temp_db):
        """Negative limit should not crash (SQLite handles it)."""
        rows = get_trades_without_scores(db_path=temp_db, limit=-1)
        assert isinstance(rows, list)


class TestSQLInjectionAlterTable:
    """A.3b: ALTER TABLE column names must be whitelisted."""

    def test_valid_columns_in_whitelist(self):
        """All component columns should be in whitelist."""
        # Verify the hardcoded list matches the whitelist
        expected_columns = {
            'rsi_score', 'support_score', 'fibonacci_score', 'ma_score',
            'volume_score', 'macd_score', 'stoch_score', 'keltner_score',
            'trend_strength_score', 'momentum_score', 'rs_score',
            'candlestick_score', 'vwap_score', 'market_context_score',
            'sector_score', 'gap_score', 'pullback_score', 'bounce_score',
            'ath_breakout_score', 'earnings_dip_score', 'trend_continuation_score',
            'rsi_value', 'distance_to_support_pct', 'spy_trend',
            'score_breakdown_json',
        }
        assert expected_columns == VALID_COMPONENT_COLUMNS

    def test_create_database_succeeds(self, temp_db):
        """Normal database creation should work fine."""
        conn = create_outcome_database(temp_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(trade_outcomes)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        # Verify score columns exist
        assert 'pullback_score' in columns
        assert 'bounce_score' in columns


class TestSQLInjectionStrategy:
    """A.3c: Strategy names must be whitelisted."""

    def test_valid_strategies(self, temp_db):
        """All valid strategies should work."""
        for strategy in VALID_STRATEGIES:
            df = load_outcomes_with_scores(
                db_path=temp_db,
                strategy=strategy,
                min_trades_with_scores=0,
            )
            assert df is not None

    def test_invalid_strategy_raises(self, temp_db):
        """Invalid strategy name should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid strategy"):
            load_outcomes_with_scores(
                db_path=temp_db,
                strategy="malicious'; DROP TABLE trade_outcomes;--",
                min_trades_with_scores=0,
            )

    def test_injection_in_strategy_name(self, temp_db):
        """SQL injection in strategy parameter should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid strategy"):
            load_outcomes_with_scores(
                db_path=temp_db,
                strategy="pullback' OR '1'='1",
                min_trades_with_scores=0,
            )

    def test_empty_strategy_uses_default(self, temp_db):
        """None strategy should use pullback_score as default."""
        df = load_outcomes_with_scores(
            db_path=temp_db,
            strategy=None,
            min_trades_with_scores=0,
        )
        assert df is not None

    def test_valid_strategy_names_constant(self):
        """Verify VALID_STRATEGIES contains all expected strategies."""
        expected = {'pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'trend_continuation'}
        assert VALID_STRATEGIES == expected


class TestPathValidation:
    """A.5: Database path validation to prevent symlink attacks."""

    def test_valid_path_returns_resolved(self, tmp_path):
        """Normal path should be resolved and returned."""
        db_path = tmp_path / "test.db"
        result = _validate_db_path(db_path)
        assert result == db_path.resolve()

    def test_symlinked_file_rejected(self, tmp_path):
        """Symlinked DB file should be rejected."""
        real_db = tmp_path / "real.db"
        real_db.touch()
        link_db = tmp_path / "link.db"
        link_db.symlink_to(real_db)
        with pytest.raises(ValueError, match="symlink"):
            _validate_db_path(link_db)

    def test_symlinked_parent_rejected(self, tmp_path):
        """Symlinked parent directory should be rejected."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(real_dir)
        db_path = link_dir / "test.db"
        with pytest.raises(ValueError, match="symlink"):
            _validate_db_path(db_path)

    def test_nonexistent_path_ok(self, tmp_path):
        """Non-existent DB path should be fine (create_outcome_database will create it)."""
        db_path = tmp_path / "new.db"
        result = _validate_db_path(db_path)
        assert result.name == "new.db"

    def test_create_database_validates_path(self, tmp_path):
        """create_outcome_database should reject symlinked paths."""
        real_db = tmp_path / "real.db"
        real_db.touch()
        link_db = tmp_path / "link.db"
        link_db.symlink_to(real_db)
        with pytest.raises(ValueError, match="symlink"):
            create_outcome_database(link_db)
