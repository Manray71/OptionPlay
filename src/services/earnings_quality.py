"""Earnings-Surprise Quality Service.

Berechnet einen additiven Score-Modifier basierend auf den letzten N
Earnings-Quartalen eines Symbols. Beat = eps_actual > eps_estimate.

Konfiguration in config/scoring.yaml unter earnings_surprise.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from ..config.analyzer_thresholds import get_analyzer_thresholds as _get_cfg

_cfg = _get_cfg()

_ES_N_QUARTERS: int = int(_cfg.get("earnings_surprise.n_quarters", 4))
_ES_MIN_QUARTERS: int = int(_cfg.get("earnings_surprise.min_quarters", 4))
_ES_ALL_BEATS: float = float(_cfg.get("earnings_surprise.thresholds.all_beats", 1.2))
_ES_MOSTLY_BEATS: float = float(_cfg.get("earnings_surprise.thresholds.mostly_beats", 0.6))
_ES_MIXED: float = float(_cfg.get("earnings_surprise.thresholds.mixed", 0.0))
_ES_MOSTLY_MISSES: float = float(_cfg.get("earnings_surprise.thresholds.mostly_misses", -1.0))
_ES_MANY_MISSES: float = float(_cfg.get("earnings_surprise.thresholds.many_misses", -1.8))
_ES_ALL_MISSES: float = float(_cfg.get("earnings_surprise.thresholds.all_misses", -2.8))

_DEFAULT_DB = Path.home() / ".optionplay" / "trades.db"


@dataclass(frozen=True)
class EarningsSurpriseResult:
    """Ergebnis der Earnings-Surprise-Analyse.

    Attributes:
        modifier: Additiver Score-Modifier (z.B. +1.2, -2.8, 0.0)
        beats: Anzahl Beats in den letzten n Quartalen
        misses: Anzahl Misses
        meets: Anzahl Meets (eps_actual == eps_estimate)
        total: Anzahl ausgewerteter Quartale
        pattern: Human-readable Pattern ('4/4 beats', '2/4 misses', etc.)
    """

    modifier: float
    beats: int
    misses: int
    meets: int
    total: int
    pattern: str


def get_recent_earnings(
    symbol: str,
    n: int = 4,
    db_path: Optional[Path] = None,
) -> List[Tuple[str, float, float, float]]:
    """Letzte n Earnings mit eps_actual, eps_estimate, eps_surprise.

    Returns: [(earnings_date, eps_actual, eps_estimate, eps_surprise), ...]
             sortiert nach Datum absteigend (neuestes zuerst).
             Nur Zeilen mit NOT NULL eps_actual AND eps_estimate.
    """
    db = db_path or _DEFAULT_DB
    if not db.exists():
        return []

    conn = sqlite3.connect(str(db))
    try:
        cursor = conn.execute(
            """SELECT earnings_date, eps_actual, eps_estimate, eps_surprise
               FROM earnings_history
               WHERE symbol = ?
                 AND eps_actual IS NOT NULL
                 AND eps_estimate IS NOT NULL
               ORDER BY earnings_date DESC
               LIMIT ?""",
            (symbol, n),
        )
        return cursor.fetchall()
    finally:
        conn.close()


def calculate_earnings_surprise_modifier(
    symbol: str,
    n_quarters: int = 4,
    min_quarters: int = 4,
    db_path: Optional[Path] = None,
    all_beats: float = _ES_ALL_BEATS,
    mostly_beats: float = _ES_MOSTLY_BEATS,
    mixed: float = _ES_MIXED,
    mostly_misses: float = _ES_MOSTLY_MISSES,
    many_misses: float = _ES_MANY_MISSES,
    all_misses: float = _ES_ALL_MISSES,
) -> EarningsSurpriseResult:
    """Berechnet den Earnings-Surprise-Modifier.

    Logik:
      beats  = Anzahl Quartale wo eps_actual > eps_estimate
      misses = Anzahl Quartale wo eps_actual < eps_estimate
      meets  = Anzahl Quartale wo eps_actual == eps_estimate

      Pattern-Mapping (bei n_quarters=4):
        4 beats, 0 misses → all_beats    (+1.2)
        3 beats, 0 misses → mostly_beats (+0.6)
        0 beats, 4 misses → all_misses   (-2.8)
        1 beat,  3 misses → many_misses  (-1.8)
        ≥2 misses         → mostly_misses(-1.0)
        sonst             → mixed        (0.0)

      Bei < min_quarters Daten: modifier = 0.0 (neutral).
    """
    earnings = get_recent_earnings(symbol, n=n_quarters, db_path=db_path)

    total = len(earnings)
    if total < min_quarters:
        return EarningsSurpriseResult(
            modifier=0.0,
            beats=0,
            misses=0,
            meets=0,
            total=total,
            pattern=f"insufficient data ({total}/{min_quarters} quarters)",
        )

    beats = sum(1 for _, actual, estimate, _ in earnings if actual > estimate)
    misses = sum(1 for _, actual, estimate, _ in earnings if actual < estimate)
    meets = total - beats - misses

    if misses == 0 and beats == total:
        modifier = all_beats
        pattern = f"{beats}/{total} beats"
    elif misses == 0 and beats >= total - 1:
        modifier = mostly_beats
        pattern = f"{beats}/{total} beats"
    elif misses >= total:
        modifier = all_misses
        pattern = f"{misses}/{total} misses"
    elif misses >= total - 1:
        modifier = many_misses
        pattern = f"{misses}/{total} misses"
    elif misses > beats:
        modifier = mostly_misses
        pattern = f"{misses}/{total} misses"
    else:
        modifier = mixed
        pattern = f"{beats}B/{misses}M/{meets}E of {total}"

    return EarningsSurpriseResult(
        modifier=modifier,
        beats=beats,
        misses=misses,
        meets=meets,
        total=total,
        pattern=pattern,
    )


def get_earnings_surprise_modifier(
    symbol: str,
    db_path: Optional[Path] = None,
) -> float:
    """Convenience: liest Config aus YAML, gibt nur den Modifier zurück.

    Für Analyzer-Integration:
      score += get_earnings_surprise_modifier(symbol)
    """
    result = calculate_earnings_surprise_modifier(
        symbol=symbol,
        n_quarters=_ES_N_QUARTERS,
        min_quarters=_ES_MIN_QUARTERS,
        all_beats=_ES_ALL_BEATS,
        mostly_beats=_ES_MOSTLY_BEATS,
        mixed=_ES_MIXED,
        mostly_misses=_ES_MOSTLY_MISSES,
        many_misses=_ES_MANY_MISSES,
        all_misses=_ES_ALL_MISSES,
        db_path=db_path,
    )
    return result.modifier
