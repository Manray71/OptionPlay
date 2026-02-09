#!/usr/bin/env python3
"""
Outcome Database Storage Functions

Extracted from options_backtest.py for modularity.
Contains: create_outcome_database, save_outcomes_to_db, get_outcome_statistics,
          load_outcomes_for_training, load_outcomes_dataframe, get_trades_without_scores,
          update_trade_scores, load_outcomes_with_scores
"""

import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np

from ..models.outcomes import SpreadOutcomeResult

logger = logging.getLogger(__name__)


OUTCOME_DB_PATH = Path.home() / ".optionplay" / "outcomes.db"


def _validate_db_path(db_path: Path) -> Path:
    """
    Validate and resolve a database path to prevent symlink attacks.

    Ensures parent directory exists and is not a symlink.
    Returns the resolved path.

    Raises:
        ValueError: If the path is a symlink or parent doesn't exist.
    """
    db_path = Path(db_path)

    # Check the file itself is not a symlink
    if db_path.exists() and db_path.is_symlink():
        raise ValueError(f"Database path is a symlink (rejected): {db_path}")

    # Resolve and validate parent directory
    parent = db_path.parent
    if parent.exists():
        if parent.is_symlink():
            raise ValueError(f"Parent directory is a symlink (rejected): {parent}")
        resolved = parent.resolve(strict=True) / db_path.name
    else:
        resolved = db_path

    return resolved


# Whitelist for valid strategy names (used in dynamic column references)
VALID_STRATEGIES = frozenset([
    'pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'trend_continuation'
])

# Whitelist for valid column names in ALTER TABLE operations
VALID_COMPONENT_COLUMNS = frozenset([
    'rsi_score', 'support_score', 'fibonacci_score', 'ma_score', 'volume_score',
    'macd_score', 'stoch_score', 'keltner_score', 'trend_strength_score',
    'momentum_score', 'rs_score', 'candlestick_score',
    'vwap_score', 'market_context_score', 'sector_score', 'gap_score',
    'pullback_score', 'bounce_score', 'ath_breakout_score', 'earnings_dip_score',
    'trend_continuation_score',
    'rsi_value', 'distance_to_support_pct', 'spy_trend', 'score_breakdown_json',
])


def create_outcome_database(db_path: Path = OUTCOME_DB_PATH) -> sqlite3.Connection:
    """
    Erstellt die Outcome-Datenbank für ML-Training.

    Schema:
    - trade_outcomes: Alle backtesteten Trades mit Features und Outcomes
    - backtest_runs: Metadaten über Backtest-Läufe
    """
    db_path = _validate_db_path(db_path)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Trade Outcomes Tabelle
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trade_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        -- Identifikation
        symbol TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        exit_date TEXT NOT NULL,
        expiration TEXT NOT NULL,

        -- Entry-Daten
        entry_price REAL NOT NULL,
        short_strike REAL NOT NULL,
        long_strike REAL NOT NULL,
        spread_width REAL NOT NULL,
        net_credit REAL NOT NULL,
        dte_at_entry INTEGER NOT NULL,
        short_otm_pct REAL NOT NULL,

        -- Outcome
        exit_price REAL NOT NULL,
        outcome TEXT NOT NULL,  -- max_profit, partial_profit, partial_loss, max_loss
        pnl REAL NOT NULL,
        pnl_pct REAL NOT NULL,
        was_profitable INTEGER NOT NULL,  -- 1 oder 0

        -- Trade-Statistiken
        min_price REAL,
        max_price REAL,
        days_below_short INTEGER,
        max_drawdown_pct REAL,
        held_to_expiration INTEGER,

        -- Market-Kontext (zum Entry-Zeitpunkt)
        vix_at_entry REAL,
        vix_regime TEXT,

        -- Zeitstempel
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,

        -- Index für schnelle Queries
        UNIQUE(symbol, entry_date, short_strike, long_strike, expiration)
    )
    """)

    # =========================================================================
    # KOMPONENTEN-SCORES FÜR ML-TRAINING (Phase 6)
    # =========================================================================
    component_columns = [
        # Technische Indikatoren (zum Entry-Zeitpunkt)
        ("rsi_score", "REAL"),
        ("support_score", "REAL"),
        ("fibonacci_score", "REAL"),
        ("ma_score", "REAL"),
        ("volume_score", "REAL"),
        ("macd_score", "REAL"),
        ("stoch_score", "REAL"),
        ("keltner_score", "REAL"),
        ("trend_strength_score", "REAL"),
        ("momentum_score", "REAL"),
        ("rs_score", "REAL"),
        ("candlestick_score", "REAL"),

        # Feature Engineering Scores
        ("vwap_score", "REAL"),
        ("market_context_score", "REAL"),
        ("sector_score", "REAL"),
        ("gap_score", "REAL"),

        # Strategie-spezifische Scores
        ("pullback_score", "REAL"),
        ("bounce_score", "REAL"),
        ("ath_breakout_score", "REAL"),
        ("earnings_dip_score", "REAL"),
        ("trend_continuation_score", "REAL"),

        # Zusätzliche technische Daten
        ("rsi_value", "REAL"),
        ("distance_to_support_pct", "REAL"),
        ("spy_trend", "TEXT"),

        # Score Breakdown als JSON (für detaillierte Analyse)
        ("score_breakdown_json", "TEXT"),
    ]

    # Füge Spalten hinzu, falls sie nicht existieren
    valid_types = frozenset(["REAL", "TEXT", "INTEGER"])
    for col_name, col_type in component_columns:
        if col_name not in VALID_COMPONENT_COLUMNS:
            raise ValueError(f"Invalid column name: {col_name}")
        if col_type not in valid_types:
            raise ValueError(f"Invalid column type: {col_type}")
        try:
            cursor.execute(f"ALTER TABLE trade_outcomes ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits

    # Backtest Runs Tabelle
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS backtest_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        symbols TEXT NOT NULL,  -- JSON Liste
        parameters TEXT NOT NULL,  -- JSON Dict
        total_trades INTEGER,
        win_rate REAL,
        total_pnl REAL,
        profit_factor REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Indices für Performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_symbol ON trade_outcomes(symbol)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_date ON trade_outcomes(entry_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_profitable ON trade_outcomes(was_profitable)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_outcome ON trade_outcomes(outcome)")

    conn.commit()
    return conn


def save_outcomes_to_db(
    results: List[SpreadOutcomeResult],
    db_path: Path = OUTCOME_DB_PATH,
    vix_data: Dict[date, float] = None,
    component_scores: Dict[Tuple[str, date], Dict] = None,
) -> int:
    """
    Speichert Backtest-Ergebnisse in der Outcome-Datenbank.

    Args:
        results: Liste von SpreadOutcomeResult
        db_path: Pfad zur Datenbank
        vix_data: Dict von date -> VIX-Wert
        component_scores: Dict von (symbol, entry_date) -> {scores...}

    Returns:
        Anzahl der gespeicherten Trades
    """
    conn = create_outcome_database(db_path)
    cursor = conn.cursor()

    saved = 0
    for result in results:
        entry = result.entry

        # VIX-Daten wenn verfügbar
        vix = vix_data.get(entry.entry_date) if vix_data else None
        vix_regime = None
        if vix is not None:
            if vix < 15:
                vix_regime = "low"
            elif vix < 20:
                vix_regime = "medium"
            elif vix < 30:
                vix_regime = "high"
            else:
                vix_regime = "extreme"

        # Komponenten-Scores wenn verfügbar
        scores = {}
        if component_scores:
            key = (entry.symbol, entry.entry_date)
            scores = component_scores.get(key, {})

        try:
            cursor.execute("""
            INSERT OR REPLACE INTO trade_outcomes (
                symbol, entry_date, exit_date, expiration,
                entry_price, short_strike, long_strike, spread_width, net_credit,
                dte_at_entry, short_otm_pct,
                exit_price, outcome, pnl, pnl_pct, was_profitable,
                min_price, max_price, days_below_short, max_drawdown_pct, held_to_expiration,
                vix_at_entry, vix_regime,
                -- Komponenten-Scores (Phase 6)
                rsi_score, support_score, fibonacci_score, ma_score, volume_score,
                macd_score, stoch_score, keltner_score, trend_strength_score,
                momentum_score, rs_score, candlestick_score,
                vwap_score, market_context_score, sector_score, gap_score,
                pullback_score, bounce_score, ath_breakout_score, earnings_dip_score,
                trend_continuation_score,
                rsi_value, distance_to_support_pct, spy_trend, score_breakdown_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.symbol,
                entry.entry_date.isoformat(),
                result.exit_date.isoformat(),
                entry.expiration.isoformat(),
                entry.underlying_price,
                entry.short_strike,
                entry.long_strike,
                entry.spread_width,
                entry.net_credit,
                entry.dte,
                entry.short_otm_pct,
                result.exit_underlying_price,
                result.outcome.value,
                result.pnl_per_contract,
                result.pnl_pct,
                1 if result.was_profitable else 0,
                result.min_price_during_trade,
                result.max_price_during_trade,
                result.days_below_short_strike,
                result.max_drawdown_pct,
                1 if result.held_to_expiration else 0,
                vix,
                vix_regime,
                # Komponenten-Scores
                scores.get('rsi_score'),
                scores.get('support_score'),
                scores.get('fibonacci_score'),
                scores.get('ma_score'),
                scores.get('volume_score'),
                scores.get('macd_score'),
                scores.get('stoch_score'),
                scores.get('keltner_score'),
                scores.get('trend_strength_score'),
                scores.get('momentum_score'),
                scores.get('rs_score'),
                scores.get('candlestick_score'),
                scores.get('vwap_score'),
                scores.get('market_context_score'),
                scores.get('sector_score'),
                scores.get('gap_score'),
                scores.get('pullback_score'),
                scores.get('bounce_score'),
                scores.get('ath_breakout_score'),
                scores.get('earnings_dip_score'),
                scores.get('trend_continuation_score'),
                scores.get('rsi_value'),
                scores.get('distance_to_support_pct'),
                scores.get('spy_trend'),
                scores.get('score_breakdown_json'),
            ))
            saved += 1
        except sqlite3.IntegrityError:
            pass  # Duplicate, skip

    conn.commit()
    conn.close()
    return saved


def load_outcomes_for_training(
    db_path: Path = OUTCOME_DB_PATH,
    min_trades: int = 100,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Lädt Outcomes für ML-Training.

    Returns:
        X: Feature-Matrix (n_samples, n_features)
        y: Labels (1 = profitable, 0 = nicht profitable)
    """
    db_path = _validate_db_path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        dte_at_entry,
        short_otm_pct,
        spread_width,
        net_credit,
        vix_at_entry,
        was_profitable
    FROM trade_outcomes
    WHERE vix_at_entry IS NOT NULL
    """)

    rows = cursor.fetchall()
    conn.close()

    if len(rows) < min_trades:
        logger.warning(f"Only {len(rows)} trades in database, need {min_trades}")
        return np.array([]), np.array([])

    # Features: DTE, OTM%, Spread Width, Credit, VIX
    X = np.array([
        [r['dte_at_entry'], r['short_otm_pct'], r['spread_width'],
         r['net_credit'], r['vix_at_entry']]
        for r in rows
    ])

    # Labels: profitable oder nicht
    y = np.array([r['was_profitable'] for r in rows])

    return X, y


def load_outcomes_dataframe(
    db_path: Path = OUTCOME_DB_PATH,
) -> "pd.DataFrame":
    """
    Lädt alle Outcomes als DataFrame für Analyse und ML.

    Returns:
        DataFrame mit allen Trade-Outcomes
    """
    import pandas as pd

    db_path = _validate_db_path(db_path)
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query("SELECT * FROM trade_outcomes", conn)
    conn.close()

    # Konvertiere Datumsfelder
    for col in ['entry_date', 'exit_date', 'expiration']:
        df[col] = pd.to_datetime(df[col])

    return df


def get_outcome_statistics(db_path: Path = OUTCOME_DB_PATH) -> Dict:
    """
    Generiert Statistiken aus der Outcome-Datenbank.
    """
    db_path = _validate_db_path(db_path)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Gesamt-Statistiken
    cursor.execute("""
    SELECT
        COUNT(*) as total,
        SUM(was_profitable) as wins,
        AVG(pnl) as avg_pnl,
        SUM(pnl) as total_pnl,
        COUNT(DISTINCT symbol) as symbols
    FROM trade_outcomes
    """)
    row = cursor.fetchone()

    stats = {
        'total_trades': row[0],
        'wins': row[1] or 0,
        'win_rate': (row[1] or 0) / row[0] * 100 if row[0] > 0 else 0,
        'avg_pnl': row[2] or 0,
        'total_pnl': row[3] or 0,
        'unique_symbols': row[4] or 0,
    }

    # Per Outcome
    cursor.execute("""
    SELECT outcome, COUNT(*) as cnt
    FROM trade_outcomes
    GROUP BY outcome
    """)
    stats['outcomes'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Per VIX Regime
    cursor.execute("""
    SELECT
        vix_regime,
        COUNT(*) as total,
        SUM(was_profitable) as wins,
        AVG(pnl) as avg_pnl
    FROM trade_outcomes
    WHERE vix_regime IS NOT NULL
    GROUP BY vix_regime
    """)
    stats['by_vix_regime'] = {
        row[0]: {
            'total': row[1],
            'win_rate': row[2] / row[1] * 100 if row[1] > 0 else 0,
            'avg_pnl': row[3],
        }
        for row in cursor.fetchall()
    }

    conn.close()
    return stats


def get_trades_without_scores(
    db_path: Path = OUTCOME_DB_PATH,
    limit: int = None,
) -> List[Dict]:
    """
    Findet Trades ohne Komponenten-Scores für nachträgliche Berechnung.

    Returns:
        Liste von Trades (symbol, entry_date) ohne scores
    """
    db_path = _validate_db_path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
    SELECT id, symbol, entry_date, entry_price
    FROM trade_outcomes
    WHERE pullback_score IS NULL
      AND bounce_score IS NULL
    ORDER BY entry_date
    """
    params = []
    if limit:
        query += " LIMIT ?"
        params.append(int(limit))

    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return rows


def update_trade_scores(
    trade_id: int,
    scores: Dict,
    db_path: Path = OUTCOME_DB_PATH,
) -> bool:
    """
    Aktualisiert die Komponenten-Scores für einen bestehenden Trade.

    Args:
        trade_id: ID des Trades
        scores: Dict mit Score-Werten

    Returns:
        True wenn erfolgreich
    """
    db_path = _validate_db_path(db_path)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Baue UPDATE-Statement dynamisch
    score_columns = [
        'rsi_score', 'support_score', 'fibonacci_score', 'ma_score', 'volume_score',
        'macd_score', 'stoch_score', 'keltner_score', 'trend_strength_score',
        'momentum_score', 'rs_score', 'candlestick_score',
        'vwap_score', 'market_context_score', 'sector_score', 'gap_score',
        'pullback_score', 'bounce_score', 'ath_breakout_score', 'earnings_dip_score', 'trend_continuation_score',
        'rsi_value', 'distance_to_support_pct', 'spy_trend', 'score_breakdown_json',
    ]

    updates = []
    values = []
    for col in score_columns:
        if col in scores and scores[col] is not None:
            updates.append(f"{col} = ?")
            values.append(scores[col])

    if not updates:
        return False

    values.append(trade_id)
    cursor.execute(
        f"UPDATE trade_outcomes SET {', '.join(updates)} WHERE id = ?",
        values
    )

    conn.commit()
    success = cursor.rowcount > 0
    conn.close()

    return success


def load_outcomes_with_scores(
    db_path: Path = OUTCOME_DB_PATH,
    strategy: str = None,
    min_trades_with_scores: int = 100,
) -> "pd.DataFrame":
    """
    Lädt Outcomes MIT Komponenten-Scores für ML-Training.

    Args:
        strategy: Filtert auf Trades mit Score für diese Strategie
        min_trades_with_scores: Mindestanzahl Trades mit Scores

    Returns:
        DataFrame mit Trades die Scores haben
    """
    import pandas as pd

    if strategy:
        if strategy not in VALID_STRATEGIES:
            raise ValueError(
                f"Invalid strategy: {strategy!r}. "
                f"Must be one of: {sorted(VALID_STRATEGIES)}"
            )
        score_col = f"{strategy}_score"
    else:
        score_col = "pullback_score"

    db_path = _validate_db_path(db_path)
    conn = sqlite3.connect(str(db_path))
    query = f"""
    SELECT *
    FROM trade_outcomes
    WHERE {score_col} IS NOT NULL
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    if len(df) < min_trades_with_scores:
        logger.warning(
            f"Only {len(df)} trades with {score_col}, need {min_trades_with_scores}"
        )

    return df
