#!/usr/bin/env python3
"""
Outcome Analysis and ML Training Functions

Extracted from options_backtest.py for modularity.
Contains: train_outcome_predictor, analyze_winning_patterns,
          calculate_symbol_stability, train_component_weights_from_outcomes,
          get_recommended_symbols, get_blacklisted_symbols, get_symbol_stability_score
"""

import json
import logging
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .outcome_storage import OUTCOME_DB_PATH

logger = logging.getLogger(__name__)


def train_outcome_predictor(
    db_path: Path = OUTCOME_DB_PATH,
) -> Optional[Dict]:
    """
    Trainiert einen einfachen Outcome-Predictor basierend auf historischen Trades.

    Verwendet Naive Bayes-artigen Ansatz (ohne sklearn):
    - Berechnet bedingte Wahrscheinlichkeiten für Win/Loss
    - Basierend auf: OTM%, DTE, VIX-Regime, Spread-Width

    Returns:
        Dict mit Predictor-Parametern oder None
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM trade_outcomes
    WHERE vix_at_entry IS NOT NULL
      AND short_otm_pct > 0
    """)

    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 100:
        logger.warning(f"Insufficient data for training: {len(rows)} trades")
        return None

    # Berechne bedingte Statistiken
    predictor = {
        "total_trades": len(rows),
        "base_win_rate": sum(1 for r in rows if r["was_profitable"]) / len(rows),
        "by_otm_bucket": {},
        "by_vix_regime": {},
        "by_dte_bucket": {},
    }

    # OTM% Buckets
    for bucket_name, (low, high) in [
        ("5-10%", (5, 10)),
        ("10-15%", (10, 15)),
        ("15-20%", (15, 20)),
        ("20%+", (20, 100)),
    ]:
        bucket_trades = [r for r in rows if low <= r["short_otm_pct"] < high]
        if bucket_trades:
            predictor["by_otm_bucket"][bucket_name] = {
                "trades": len(bucket_trades),
                "win_rate": sum(1 for r in bucket_trades if r["was_profitable"])
                / len(bucket_trades),
                "avg_pnl": sum(r["pnl"] for r in bucket_trades) / len(bucket_trades),
            }

    # VIX Regimes
    for regime in ["low", "medium", "high", "extreme"]:
        regime_trades = [r for r in rows if r["vix_regime"] == regime]
        if regime_trades:
            predictor["by_vix_regime"][regime] = {
                "trades": len(regime_trades),
                "win_rate": sum(1 for r in regime_trades if r["was_profitable"])
                / len(regime_trades),
                "avg_pnl": sum(r["pnl"] for r in regime_trades) / len(regime_trades),
            }

    # DTE Buckets
    for bucket_name, (low, high) in [
        ("30-45", (30, 45)),
        ("45-60", (45, 60)),
        ("60-90", (60, 90)),
        ("90+", (90, 365)),
    ]:
        bucket_trades = [r for r in rows if low <= r["dte_at_entry"] < high]
        if bucket_trades:
            predictor["by_dte_bucket"][bucket_name] = {
                "trades": len(bucket_trades),
                "win_rate": sum(1 for r in bucket_trades if r["was_profitable"])
                / len(bucket_trades),
                "avg_pnl": sum(r["pnl"] for r in bucket_trades) / len(bucket_trades),
            }

    return predictor


def analyze_winning_patterns(
    db_path: Path = OUTCOME_DB_PATH,
) -> Dict:
    """
    Analysiert Muster bei gewinnenden Trades.

    Returns:
        Dict mit Mustern und Empfehlungen
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Gewinner vs. Verlierer vergleichen
    patterns = {
        "winners": {},
        "losers": {},
        "recommendations": [],
    }

    for label, condition in [("winners", "was_profitable = 1"), ("losers", "was_profitable = 0")]:
        cursor.execute(f"""
        SELECT
            AVG(short_otm_pct) as avg_otm,
            AVG(dte_at_entry) as avg_dte,
            AVG(spread_width) as avg_width,
            AVG(net_credit) as avg_credit,
            AVG(vix_at_entry) as avg_vix,
            AVG(max_drawdown_pct) as avg_drawdown,
            AVG(CASE WHEN held_to_expiration = 1 THEN 1 ELSE 0 END) as hold_to_exp_pct
        FROM trade_outcomes
        WHERE {condition}
        """)

        row = cursor.fetchone()
        if row:
            patterns[label] = {
                "avg_otm_pct": round(row["avg_otm"] or 0, 1),
                "avg_dte": round(row["avg_dte"] or 0, 0),
                "avg_spread_width": round(row["avg_width"] or 0, 1),
                "avg_credit": round(row["avg_credit"] or 0, 2),
                "avg_vix": round(row["avg_vix"] or 0, 1),
                "avg_drawdown_pct": round(row["avg_drawdown"] or 0, 1),
                "hold_to_expiration_pct": round((row["hold_to_exp_pct"] or 0) * 100, 1),
            }

    # Empfehlungen generieren
    w = patterns.get("winners", {})
    l = patterns.get("losers", {})

    if w and l:
        if w.get("avg_otm_pct", 0) > l.get("avg_otm_pct", 0):
            patterns["recommendations"].append(
                f"Winners have higher OTM%: {w['avg_otm_pct']}% vs {l['avg_otm_pct']}%"
            )
        if w.get("avg_vix", 0) < l.get("avg_vix", 0):
            patterns["recommendations"].append(
                f"Winners tend to enter at lower VIX: {w['avg_vix']} vs {l['avg_vix']}"
            )

    conn.close()
    return patterns


def calculate_symbol_stability(
    db_path: Path = OUTCOME_DB_PATH,
    min_trades: int = 20,
) -> Dict[str, Dict]:
    """
    Berechnet Symbol-Stabilität basierend auf historischer Trading-Performance.

    Returns:
        Dict von symbol -> {win_rate, avg_pnl, stability_score, trades}
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
    SELECT
        symbol,
        COUNT(*) as trades,
        SUM(was_profitable) as wins,
        AVG(pnl) as avg_pnl,
        AVG(pnl_pct) as avg_pnl_pct,
        AVG(max_drawdown_pct) as avg_drawdown,
        MIN(pnl) as worst_pnl,
        MAX(pnl) as best_pnl,
        GROUP_CONCAT(was_profitable) as outcome_sequence
    FROM trade_outcomes
    GROUP BY symbol
    HAVING trades >= ?
    ORDER BY trades DESC
    """,
        (min_trades,),
    )

    results = {}
    for row in cursor.fetchall():
        win_rate = row["wins"] / row["trades"] * 100 if row["trades"] > 0 else 0
        avg_pnl = row["avg_pnl"] or 0
        avg_drawdown = abs(row["avg_drawdown"] or 0)

        # Stability Score: Kombination aus Win Rate, Konsistenz und Drawdown
        # Higher is better (0-100)
        consistency = _calculate_consistency(row["outcome_sequence"])

        stability = (
            win_rate * 0.4  # 40% Win Rate
            + consistency * 0.3  # 30% Konsistenz
            + max(0, 100 - avg_drawdown) * 0.3  # 30% niedriger Drawdown
        )

        results[row["symbol"]] = {
            "trades": row["trades"],
            "win_rate": round(win_rate, 1),
            "avg_pnl": round(avg_pnl, 2),
            "avg_pnl_pct": round(row["avg_pnl_pct"] or 0, 2),
            "avg_drawdown_pct": round(avg_drawdown, 1),
            "worst_trade": round(row["worst_pnl"] or 0, 2),
            "best_trade": round(row["best_pnl"] or 0, 2),
            "consistency": round(consistency, 1),
            "stability_score": round(stability, 1),
        }

    conn.close()
    return results


def _calculate_consistency(outcome_sequence: str) -> float:
    """
    Berechnet Konsistenz aus einer Sequence von 0/1 Ergebnissen.
    Höhere Konsistenz = weniger abwechselnde Streaks.
    """
    if not outcome_sequence:
        return 50.0

    outcomes = outcome_sequence.split(",")
    if len(outcomes) < 3:
        return 50.0

    # Zähle Streak-Wechsel
    changes = sum(1 for i in range(1, len(outcomes)) if outcomes[i] != outcomes[i - 1])

    # Weniger Wechsel = mehr Konsistenz (bei hoher Win Rate = gut)
    max_changes = len(outcomes) - 1
    change_rate = changes / max_changes if max_changes > 0 else 0

    # Konsistenz = 100 * (1 - change_rate) * win_adjustment
    wins = sum(1 for o in outcomes if o == "1")
    win_rate = wins / len(outcomes)

    # Hohe Win Rate + niedrige Change Rate = hohe Konsistenz
    if win_rate >= 0.6:
        return 100 * (1 - change_rate * 0.5)  # Weniger Bestrafung bei hoher WR
    else:
        return 50 * (1 - change_rate)  # Mehr Bestrafung bei niedriger WR


def get_recommended_symbols(
    db_path: Path = OUTCOME_DB_PATH,
    min_trades: int = 20,
    min_win_rate: float = 55.0,
    min_stability: float = 50.0,
) -> List[str]:
    """
    Gibt empfohlene Symbole basierend auf historischer Performance zurück.
    """
    stability = calculate_symbol_stability(db_path, min_trades)

    recommended = [
        symbol
        for symbol, data in stability.items()
        if data["win_rate"] >= min_win_rate and data["stability_score"] >= min_stability
    ]

    # Sortiere nach Stability Score
    recommended.sort(key=lambda s: stability[s]["stability_score"], reverse=True)

    return recommended


def get_blacklisted_symbols(
    db_path: Path = OUTCOME_DB_PATH,
    min_trades: int = 15,
    max_win_rate: float = 40.0,
) -> List[str]:
    """
    Gibt Symbole zurück die gemieden werden sollten.
    """
    stability = calculate_symbol_stability(db_path, min_trades)

    blacklisted = [
        symbol
        for symbol, data in stability.items()
        if data["win_rate"] < max_win_rate or data["stability_score"] < 30
    ]

    return blacklisted


def get_symbol_stability_score(
    symbol: str,
    db_path: Path = OUTCOME_DB_PATH,
    min_trades: int = 10,
) -> Optional[float]:
    """
    Holt den Stability Score für ein einzelnes Symbol.

    Returns:
        Stability Score (0-100) oder None wenn nicht genug Daten
    """
    stability = calculate_symbol_stability(db_path, min_trades)
    data = stability.get(symbol)
    if data:
        return data["stability_score"]
    return None


def train_component_weights_from_outcomes(
    db_path: Path = OUTCOME_DB_PATH,
    strategy: str = None,
) -> Optional[Dict[str, float]]:
    """
    Trainiert optimale Gewichtungen für Score-Komponenten basierend auf Outcomes.

    Verwendet Korrelationsanalyse: Wie stark korreliert jede Komponente mit Wins?

    Args:
        strategy: Optional Strategie-Filter

    Returns:
        Dict von {component_name: optimized_weight} oder None
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Score-Spalten die in der DB verfügbar sind
    score_columns = [
        "rsi_score",
        "support_score",
        "fibonacci_score",
        "ma_score",
        "volume_score",
        "macd_score",
        "stoch_score",
        "keltner_score",
        "trend_strength_score",
        "momentum_score",
        "rs_score",
        "vwap_score",
        "market_context_score",
        "sector_score",
    ]

    # Lade Trades mit Scores
    query = """
    SELECT was_profitable, {}
    FROM trade_outcomes
    WHERE pullback_score IS NOT NULL
       OR bounce_score IS NOT NULL
    """.format(", ".join(score_columns))

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 50:
        logger.warning(f"Insufficient scored trades for weight training: {len(rows)}")
        return None

    # Berechne Korrelation jeder Komponente mit was_profitable
    outcomes = np.array([r["was_profitable"] for r in rows])
    weights = {}

    for col in score_columns:
        values = np.array([r[col] if r[col] is not None else 0 for r in rows])

        # Skip wenn keine Varianz
        if np.std(values) == 0:
            weights[col] = 1.0
            continue

        # Pearson Korrelation
        correlation = np.corrcoef(values, outcomes)[0, 1]

        # Gewicht: basierend auf Korrelationsstärke
        # Positive Korrelation = höheres Gewicht
        # Negative Korrelation = niedrigeres Gewicht
        weight = 1.0 + correlation * 2.0  # Range: ~-1 bis ~3
        weight = max(0.1, min(3.0, weight))  # Clamp

        weights[col] = round(weight, 3)

    logger.info(f"Trained weights from {len(rows)} outcome trades")
    return weights
