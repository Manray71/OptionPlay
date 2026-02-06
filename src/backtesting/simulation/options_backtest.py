#!/usr/bin/env python3
"""
Real Options Backtester - Outcome-basiertes Backtesting
========================================================
Extracted from real_options_backtester.py (Phase 6c)

Verwendet ECHTE historische Optionspreise aus der Datenbank für:
1. Realistische Spread-Pricing (keine Black-Scholes Approximation)
2. Echte Bid/Ask-Spreads
3. Tatsächliche P&L-Berechnung bei Expiration

Verwendung:
    from src.backtesting.simulation.options_backtest import RealOptionsBacktester

    backtester = RealOptionsBacktester()
    result = backtester.backtest_spread(
        symbol="AAPL",
        entry_date=date(2024, 6, 15),
        short_strike=180,
        long_strike=175,
        expiration=date(2024, 7, 19)
    )
"""

import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np

from ..models.outcomes import (
    SpreadOutcome,
    OptionQuote,
    SpreadEntry,
    SpreadOutcomeResult,
    SetupFeatures,
    BacktestTradeRecord,
)
from ..core.database import OptionsDatabase, DB_PATH
from ..core.spread_engine import SpreadFinder, OutcomeCalculator

logger = logging.getLogger(__name__)


# =============================================================================
# MAIN BACKTESTER
# =============================================================================

class RealOptionsBacktester:
    """
    Haupt-Backtesting-Engine mit echten Optionspreisen.

    Verwendet:
    1. Echte historische Optionspreise für Entry
    2. Echte Underlying-Preise für Outcome-Berechnung
    3. Speichert Ergebnisse für ML-Training
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db = OptionsDatabase(db_path)
        self.spread_finder = SpreadFinder(self.db)
        self.outcome_calc = OutcomeCalculator(self.db)

        # Cache für Preisdaten
        self._price_cache: Dict[str, Dict[date, float]] = {}
        self._vix_cache: Dict[date, float] = {}

    def backtest_spread(
        self,
        symbol: str,
        entry_date: date,
        short_strike: float,
        long_strike: float,
        expiration: date,
    ) -> Optional[SpreadOutcomeResult]:
        """
        Backtestet einen spezifischen Spread.

        Args:
            symbol: Ticker
            entry_date: Entry-Datum
            short_strike: Short Put Strike
            long_strike: Long Put Strike
            expiration: Expiration Date

        Returns:
            SpreadOutcomeResult oder None
        """
        # Hole Options-Quotes für Entry
        puts = self.db.get_puts_for_date(
            symbol=symbol,
            quote_date=entry_date,
            dte_min=1,
            dte_max=365,
            moneyness_min=0.5,
            moneyness_max=1.5,
        )

        # Finde die spezifischen Puts
        short_put = next((p for p in puts if p.strike == short_strike and p.expiration == expiration), None)
        long_put = next((p for p in puts if p.strike == long_strike and p.expiration == expiration), None)

        if not short_put or not long_put:
            return None

        # Erstelle SpreadEntry
        entry = SpreadEntry(
            symbol=symbol,
            entry_date=entry_date,
            expiration=expiration,
            underlying_price=short_put.underlying_price,
            short_strike=short_strike,
            short_bid=short_put.bid,
            short_ask=short_put.ask,
            short_mid=short_put.mid,
            long_strike=long_strike,
            long_bid=long_put.bid,
            long_ask=long_put.ask,
            long_mid=long_put.mid,
            spread_width=short_strike - long_strike,
            gross_credit=short_put.mid - long_put.mid,
            net_credit=short_put.bid - long_put.ask,
            dte=short_put.dte,
            short_otm_pct=short_put.otm_pct,
            long_otm_pct=long_put.otm_pct,
        )

        # Berechne Outcome
        return self.outcome_calc.calculate_outcome(entry)

    def find_and_backtest(
        self,
        symbol: str,
        entry_date: date,
        target_otm_pct: float = 10.0,
        spread_width_pct: float = 5.0,
        dte_min: int = 60,
        dte_max: int = 90,
    ) -> Optional[SpreadOutcomeResult]:
        """
        Findet automatisch einen passenden Spread und backtestet ihn.

        Args:
            symbol: Ticker
            entry_date: Entry-Datum
            target_otm_pct: Ziel OTM% für Short Strike
            spread_width_pct: Spread-Breite als % des Aktienkurses
            dte_min/max: DTE-Range

        Returns:
            SpreadOutcomeResult oder None
        """
        # Finde passenden Spread
        entry = self.spread_finder.find_spread(
            symbol=symbol,
            quote_date=entry_date,
            target_short_otm_pct=target_otm_pct,
            spread_width_pct=spread_width_pct,
            dte_min=dte_min,
            dte_max=dte_max,
        )

        if not entry:
            return None

        # Berechne Outcome
        return self.outcome_calc.calculate_outcome(entry)

    def run_full_backtest(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date,
        entry_interval_days: int = 5,  # Alle 5 Tage neuer Entry
        target_otm_pct: float = 10.0,
        spread_width_pct: float = 5.0,
        dte_min: int = 60,
        dte_max: int = 90,
        progress_callback: callable = None,
    ) -> List[SpreadOutcomeResult]:
        """
        Führt vollständiges Backtesting über alle Symbole und Zeitraum durch.

        Args:
            symbols: Liste von Tickern
            start_date: Start-Datum
            end_date: End-Datum
            entry_interval_days: Tage zwischen Entries
            target_otm_pct: Ziel OTM%
            spread_width_pct: Spread-Breite als % des Aktienkurses
            dte_min/max: DTE-Range
            progress_callback: Optional callback(symbol, date, result)

        Returns:
            Liste aller SpreadOutcomeResults
        """
        all_results = []

        for symbol in symbols:
            logger.info(f"Backtesting {symbol}...")

            # Hole verfügbare Dates
            available_dates = self.db.get_available_dates(symbol, start_date, end_date)

            # Filtere auf Entry-Intervall
            entry_dates = available_dates[::entry_interval_days]

            for entry_date in entry_dates:
                # Skip wenn zu nah am End-Date (brauchen DTE für Expiration)
                if (end_date - entry_date).days < dte_max:
                    continue

                result = self.find_and_backtest(
                    symbol=symbol,
                    entry_date=entry_date,
                    target_otm_pct=target_otm_pct,
                    spread_width_pct=spread_width_pct,
                    dte_min=dte_min,
                    dte_max=dte_max,
                )

                if result:
                    all_results.append(result)

                    if progress_callback:
                        progress_callback(symbol, entry_date, result)

        logger.info(f"Backtest complete: {len(all_results)} trades")
        return all_results

    def generate_outcome_statistics(
        self,
        results: List[SpreadOutcomeResult],
    ) -> Dict:
        """
        Generiert Statistiken aus Backtest-Ergebnissen.

        Returns:
            Dict mit Win-Rate, Avg P&L, etc.
        """
        if not results:
            return {}

        wins = [r for r in results if r.was_profitable]
        losses = [r for r in results if not r.was_profitable]

        pnls = [r.pnl_per_contract for r in results]

        return {
            'total_trades': len(results),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(results) * 100,
            'total_pnl': sum(pnls),
            'avg_pnl': np.mean(pnls),
            'median_pnl': np.median(pnls),
            'std_pnl': np.std(pnls),
            'max_win': max(pnls) if pnls else 0,
            'max_loss': min(pnls) if pnls else 0,
            'profit_factor': abs(sum(p for p in pnls if p > 0) / sum(p for p in pnls if p < 0)) if any(p < 0 for p in pnls) else float('inf'),
            'outcomes': {
                outcome.value: len([r for r in results if r.outcome == outcome])
                for outcome in SpreadOutcome
            },
        }

    def close(self):
        """Schließt Datenbankverbindung"""
        self.db.close()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def quick_backtest(
    symbol: str,
    entry_date: date,
    target_otm_pct: float = 10.0,
    spread_width_pct: float = 5.0,
) -> Optional[SpreadOutcomeResult]:
    """
    Schneller Backtest für einen einzelnen Trade.

    Args:
        spread_width_pct: Spread-Breite als % des Aktienkurses (z.B. 5% = $10 bei $200)

    Usage:
        result = quick_backtest("AAPL", date(2024, 6, 15))
        if result:
            print(f"P&L: ${result.pnl_per_contract:.2f}")
    """
    backtester = RealOptionsBacktester()
    try:
        return backtester.find_and_backtest(
            symbol=symbol,
            entry_date=entry_date,
            target_otm_pct=target_otm_pct,
            spread_width_pct=spread_width_pct,
        )
    finally:
        backtester.close()


def run_symbol_backtest(
    symbol: str,
    start_date: date,
    end_date: date,
    **kwargs,
) -> Dict:
    """
    Führt Backtest für ein einzelnes Symbol durch und gibt Statistiken zurück.

    Usage:
        stats = run_symbol_backtest("AAPL", date(2023, 1, 1), date(2024, 1, 1))
        print(f"Win Rate: {stats['win_rate']:.1f}%")
    """
    backtester = RealOptionsBacktester()
    try:
        results = backtester.run_full_backtest(
            symbols=[symbol],
            start_date=start_date,
            end_date=end_date,
            **kwargs,
        )
        return backtester.generate_outcome_statistics(results)
    finally:
        backtester.close()


# =============================================================================
# OUTCOME DATABASE FOR ML TRAINING
# =============================================================================

OUTCOME_DB_PATH = Path.home() / ".optionplay" / "outcomes.db"


def create_outcome_database(db_path: Path = OUTCOME_DB_PATH) -> sqlite3.Connection:
    """
    Erstellt die Outcome-Datenbank für ML-Training.

    Schema:
    - trade_outcomes: Alle backtesteten Trades mit Features und Outcomes
    - backtest_runs: Metadaten über Backtest-Läufe
    """
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

        # Zusätzliche technische Daten
        ("rsi_value", "REAL"),
        ("distance_to_support_pct", "REAL"),
        ("spy_trend", "TEXT"),

        # Score Breakdown als JSON (für detaillierte Analyse)
        ("score_breakdown_json", "TEXT"),
    ]

    # Füge Spalten hinzu, falls sie nicht existieren
    for col_name, col_type in component_columns:
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
                rsi_value, distance_to_support_pct, spy_trend, score_breakdown_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query("SELECT * FROM trade_outcomes", conn)
    conn.close()

    # Konvertiere Datumsfelder
    for col in ['entry_date', 'exit_date', 'expiration']:
        df[col] = pd.to_datetime(df[col])

    return df


def train_outcome_predictor(
    db_path: Path = OUTCOME_DB_PATH,
    test_size: float = 0.2,
) -> Dict:
    """
    Trainiert ein ML-Modell zur Vorhersage profitabler Trades.

    Uses:
    - Random Forest Classifier
    - Features: DTE, OTM%, Credit, VIX

    Returns:
        Dict mit Model, Accuracy, Feature Importances
    """
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, confusion_matrix
    import pandas as pd

    # Lade Daten
    df = load_outcomes_dataframe(db_path)

    if len(df) < 100:
        logger.warning(f"Only {len(df)} trades, need more for training")
        return {}

    # Features
    feature_cols = [
        'dte_at_entry',
        'short_otm_pct',
        'spread_width',
        'net_credit',
        'vix_at_entry',
    ]

    # Filtere Rows ohne VIX
    df = df[df['vix_at_entry'].notna()].copy()

    X = df[feature_cols].values
    y = df['was_profitable'].values

    # Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y
    )

    # Train Random Forest
    rf = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_leaf=20,
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)

    # Evaluate
    y_pred = rf.predict(X_test)
    accuracy = (y_pred == y_test).mean()

    # Feature Importances
    importances = dict(zip(feature_cols, rf.feature_importances_))

    # Confusion Matrix
    cm = confusion_matrix(y_test, y_pred)

    return {
        'model': rf,
        'accuracy': accuracy,
        'feature_importances': importances,
        'confusion_matrix': cm,
        'n_train': len(X_train),
        'n_test': len(X_test),
        'classification_report': classification_report(y_test, y_pred, output_dict=True),
    }


def analyze_winning_patterns(db_path: Path = OUTCOME_DB_PATH) -> Dict:
    """
    Analysiert Muster in gewinnenden vs. verlierenden Trades.

    Returns:
        Dict mit Insights über profitable Setups
    """
    import pandas as pd

    df = load_outcomes_dataframe(db_path)

    # Filtere auf Trades mit VIX
    df = df[df['vix_at_entry'].notna()].copy()

    winners = df[df['was_profitable'] == 1]
    losers = df[df['was_profitable'] == 0]

    insights = {
        'total_trades': len(df),
        'winners': len(winners),
        'losers': len(losers),
        'overall_win_rate': len(winners) / len(df) * 100,
    }

    # Feature-Vergleich: Winners vs Losers
    features = ['dte_at_entry', 'short_otm_pct', 'net_credit', 'vix_at_entry', 'spread_width']

    insights['feature_comparison'] = {}
    for feat in features:
        insights['feature_comparison'][feat] = {
            'winners_mean': winners[feat].mean(),
            'winners_std': winners[feat].std(),
            'losers_mean': losers[feat].mean(),
            'losers_std': losers[feat].std(),
        }

    # Win Rate by OTM% Buckets
    df['otm_bucket'] = pd.cut(df['short_otm_pct'],
                              bins=[0, 5, 8, 10, 12, 15, 100],
                              labels=['<5%', '5-8%', '8-10%', '10-12%', '12-15%', '>15%'])
    otm_stats = df.groupby('otm_bucket')['was_profitable'].agg(['sum', 'count'])
    otm_stats['win_rate'] = otm_stats['sum'] / otm_stats['count'] * 100
    insights['by_otm_bucket'] = otm_stats.to_dict('index')

    # Win Rate by VIX Buckets
    df['vix_bucket'] = pd.cut(df['vix_at_entry'],
                               bins=[0, 15, 20, 25, 30, 100],
                               labels=['<15', '15-20', '20-25', '25-30', '>30'])
    vix_stats = df.groupby('vix_bucket')['was_profitable'].agg(['sum', 'count'])
    vix_stats['win_rate'] = vix_stats['sum'] / vix_stats['count'] * 100
    insights['by_vix_bucket'] = vix_stats.to_dict('index')

    # Win Rate by DTE Buckets
    df['dte_bucket'] = pd.cut(df['dte_at_entry'],
                               bins=[0, 45, 60, 75, 90, 120],
                               labels=['<45', '45-60', '60-75', '75-90', '>90'])
    dte_stats = df.groupby('dte_bucket')['was_profitable'].agg(['sum', 'count'])
    dte_stats['win_rate'] = dte_stats['sum'] / dte_stats['count'] * 100
    insights['by_dte_bucket'] = dte_stats.to_dict('index')

    # Beste Kombinationen
    combo = df.groupby(['vix_regime', 'otm_bucket'])['was_profitable'].agg(['sum', 'count'])
    combo['win_rate'] = combo['sum'] / combo['count'] * 100
    combo = combo[combo['count'] >= 50].sort_values('win_rate', ascending=False)
    insights['best_combinations'] = combo.head(10).to_dict('index')

    return insights


def calculate_symbol_stability(db_path: Path = OUTCOME_DB_PATH, min_trades: int = 20) -> Dict[str, Dict]:
    """
    Berechnet Symbol-Stabilität basierend auf historischen Backtest-Ergebnissen.

    Returns:
        Dict[symbol] -> {stability_score, win_rate, avg_drawdown, ...}
    """
    import pandas as pd

    df = load_outcomes_dataframe(db_path)

    if len(df) < 100:
        return {}

    # Symbol-Statistiken
    symbol_stats = df.groupby('symbol').agg({
        'was_profitable': ['sum', 'count', 'mean'],
        'pnl': 'sum',
        'max_drawdown_pct': 'mean',
        'days_below_short': 'mean',
    }).reset_index()

    symbol_stats.columns = ['symbol', 'wins', 'total', 'win_rate', 'total_pnl',
                            'avg_drawdown', 'avg_days_below']

    # Filtere auf Symbole mit genug Trades
    symbol_stats = symbol_stats[symbol_stats['total'] >= min_trades]

    # Berechne Stabilität Score
    # Niedriger Drawdown und wenige Days Below = hohe Stabilität
    symbol_stats['stability_score'] = (
        100 - (symbol_stats['avg_drawdown'] * 3 + symbol_stats['avg_days_below'] * 2)
    ).clip(0, 100)

    # Erstelle Result Dict
    result = {}
    for _, row in symbol_stats.iterrows():
        result[row['symbol']] = {
            'stability_score': round(row['stability_score'], 1),
            'win_rate': round(row['win_rate'] * 100, 1),
            'avg_drawdown': round(row['avg_drawdown'], 1),
            'avg_days_below': round(row['avg_days_below'], 1),
            'total_trades': int(row['total']),
            'total_pnl': round(row['total_pnl'], 0),
            'recommended': row['stability_score'] >= 70 and row['win_rate'] >= 0.85,
            'blacklisted': row['stability_score'] < 50 or row['win_rate'] < 0.70,
        }

    return result


def get_recommended_symbols(db_path: Path = OUTCOME_DB_PATH, min_trades: int = 20) -> List[str]:
    """
    Gibt Liste empfohlener Symbole basierend auf Backtest-Stabilität zurück.

    Returns:
        Liste von Symbolen mit Stability >= 70 und Win Rate >= 85%
    """
    stability = calculate_symbol_stability(db_path, min_trades)
    return [sym for sym, data in stability.items() if data['recommended']]


def get_blacklisted_symbols(db_path: Path = OUTCOME_DB_PATH, min_trades: int = 20) -> List[str]:
    """
    Gibt Liste zu vermeidender Symbole basierend auf Backtest-Stabilität zurück.

    Returns:
        Liste von Symbolen mit Stability < 50 oder Win Rate < 70%
    """
    stability = calculate_symbol_stability(db_path, min_trades)
    return [sym for sym, data in stability.items() if data['blacklisted']]


def get_symbol_stability_score(symbol: str, db_path: Path = OUTCOME_DB_PATH) -> Optional[float]:
    """
    Gibt den Stability Score für ein einzelnes Symbol zurück.

    Returns:
        Stability Score (0-100) oder None wenn Symbol nicht in DB
    """
    stability = calculate_symbol_stability(db_path)
    if symbol in stability:
        return stability[symbol]['stability_score']
    return None


def get_outcome_statistics(db_path: Path = OUTCOME_DB_PATH) -> Dict:
    """
    Generiert Statistiken aus der Outcome-Datenbank.
    """
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
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
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
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Baue UPDATE-Statement dynamisch
    score_columns = [
        'rsi_score', 'support_score', 'fibonacci_score', 'ma_score', 'volume_score',
        'macd_score', 'stoch_score', 'keltner_score', 'trend_strength_score',
        'momentum_score', 'rs_score', 'candlestick_score',
        'vwap_score', 'market_context_score', 'sector_score', 'gap_score',
        'pullback_score', 'bounce_score', 'ath_breakout_score', 'earnings_dip_score',
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

    conn = sqlite3.connect(str(db_path))

    # Filtere auf Trades mit Scores
    score_col = f"{strategy}_score" if strategy else "pullback_score"
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


def train_component_weights_from_outcomes(
    db_path: Path = OUTCOME_DB_PATH,
    strategy: str = "pullback",
) -> Dict:
    """
    Trainiert Komponenten-Gewichte basierend auf historischen Outcomes.

    Uses Logistic Regression + Random Forest.

    Returns:
        Dict mit weights, accuracy, feature_importances
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    import pandas as pd

    df = load_outcomes_with_scores(db_path, strategy)

    if len(df) < 100:
        return {'error': f"Only {len(df)} trades with scores, need at least 100"}

    # Feature-Spalten (Komponenten-Scores)
    component_cols = [
        'rsi_score', 'support_score', 'fibonacci_score', 'ma_score', 'volume_score',
        'macd_score', 'stoch_score', 'keltner_score', 'trend_strength_score',
        'momentum_score', 'rs_score', 'candlestick_score',
        'vwap_score', 'market_context_score', 'sector_score', 'gap_score',
    ]

    # Filtere auf vorhandene Spalten mit Daten
    available_cols = [c for c in component_cols if c in df.columns and df[c].notna().sum() > 50]

    if len(available_cols) < 3:
        return {'error': f"Only {len(available_cols)} components with data"}

    # Vorbereitung
    df_clean = df[available_cols + ['was_profitable']].dropna()
    X = df_clean[available_cols].values
    y = df_clean['was_profitable'].values

    # Skalierung
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.2, random_state=42, stratify=y
    )

    # Logistic Regression für interpretierbare Gewichte
    lr = LogisticRegression(max_iter=1000, random_state=42)
    lr.fit(X_train, y_train)
    lr_accuracy = lr.score(X_test, y_test)

    # Random Forest für Feature Importance
    rf = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    rf.fit(X_train, y_train)
    rf_accuracy = rf.score(X_test, y_test)

    # Extrahiere Gewichte
    lr_weights = dict(zip(available_cols, lr.coef_[0]))
    rf_importances = dict(zip(available_cols, rf.feature_importances_))

    # Normalisiere Gewichte auf Summe = 1
    total = sum(abs(v) for v in lr_weights.values())
    normalized_weights = {k: abs(v) / total for k, v in lr_weights.items()}

    return {
        'strategy': strategy,
        'n_trades': len(df_clean),
        'n_features': len(available_cols),
        'lr_accuracy': lr_accuracy,
        'rf_accuracy': rf_accuracy,
        'weights': normalized_weights,
        'lr_raw_weights': lr_weights,
        'rf_feature_importances': rf_importances,
        'feature_columns': available_cols,
    }


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Real Options Backtester")
    parser.add_argument("--symbol", default="AAPL", help="Symbol to backtest")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2024-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--otm", type=float, default=10.0, help="Target OTM%")
    parser.add_argument("--width", type=float, default=5.0, help="Spread width")

    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"\nBacktesting {args.symbol} from {start} to {end}")
    print(f"Target OTM: {args.otm}%, Spread Width: ${args.width}")
    print("-" * 50)

    stats = run_symbol_backtest(
        args.symbol,
        start,
        end,
        target_otm_pct=args.otm,
        spread_width=args.width,
    )

    if stats:
        print(f"\nResults for {args.symbol}:")
        print(f"  Total Trades: {stats['total_trades']}")
        print(f"  Win Rate: {stats['win_rate']:.1f}%")
        print(f"  Total P&L: ${stats['total_pnl']:.2f}")
        print(f"  Avg P&L: ${stats['avg_pnl']:.2f}")
        print(f"  Profit Factor: {stats['profit_factor']:.2f}")
        print(f"\nOutcomes:")
        for outcome, count in stats['outcomes'].items():
            print(f"  {outcome}: {count}")
    else:
        print("No trades found")
