from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.sector_rs import RSQuadrant


@dataclass(frozen=True)
class AlphaCandidate:
    """Single candidate on the Alpha-Longlist (E.2)."""

    symbol: str
    # Raw RS values (from StockRS)
    b_raw: float  # slow RS-Ratio - 100
    f_raw: float  # fast RS-Ratio - 100
    # Composite
    alpha_raw: float  # B + weight * F
    alpha_percentile: int  # 0-100 (Percentile-Rank)
    # Quadrants
    quadrant_slow: RSQuadrant
    quadrant_fast: RSQuadrant
    dual_label: str  # "LAG->IMP", "LEADING" etc.
    # Context
    sector: str  # GICS sector (from fundamentals DB)
