from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Tuple

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
    # E.2b.4: TechnicalComposite details (None when alpha_composite.enabled = false)
    b_composite: Optional[float] = None  # classic-window composite total
    f_composite: Optional[float] = None  # fast-window composite total
    breakout_signals: Tuple[str, ...] = field(default_factory=tuple)
    pre_breakout: bool = False
