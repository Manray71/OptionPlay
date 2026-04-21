"""
TechnicalComposite — E.2b: Multi-Faktor Alpha-Composite Skelett.

Berechnet CompositeScore pro Symbol aus:
  E.2b.1: RSI-Score + Quadrant-Kombinations-Matrix (4x4)
  E.2b.2: Money Flow + Divergenz-Penalty  (TODO)
  E.2b.3: Tech Score + Breakout-Patterns + Earnings + Seasonality  (TODO)
  E.2b.4: Integration in AlphaScorer  (TODO)

OHLCV-Daten werden als Parameter übergeben (Batch-Loading durch Caller).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.indicators.momentum import calculate_rsi

logger = logging.getLogger(__name__)


def _load_composite_config() -> Dict[str, Any]:
    try:
        config_path = Path(__file__).resolve().parents[2] / "config" / "trading.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
                return data.get("alpha_composite", {})
    except Exception:
        pass
    return {}


_cfg = _load_composite_config()


@dataclass(frozen=True)
class CompositeScore:
    """Immutable composite score for one symbol/timeframe combination."""

    symbol: str
    timeframe: str  # "classic" or "fast"
    total: float
    rsi_score: float = 0.0
    money_flow_score: float = 0.0
    tech_score: float = 0.0
    divergence_penalty: float = 0.0
    earnings_score: float = 0.0
    seasonality_score: float = 0.0
    quadrant_combo_score: float = 0.0


class TechnicalComposite:
    """Computes multi-factor composite scores for alpha ranking."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config if config is not None else _cfg
        self._quadrant_scores: Dict[str, float] = {
            k: float(v) for k, v in cfg.get("quadrant_scores", {}).items()
        }
        rsi_cfg = cfg.get("rsi_scoring", {})
        self._rsi_oversold_threshold: float = float(rsi_cfg.get("oversold_threshold", 30))
        self._rsi_oversold_score: float = float(rsi_cfg.get("oversold_score", 5.0))
        self._rsi_neutral_upper: float = float(rsi_cfg.get("neutral_upper", 70))
        self._rsi_overbought_score: float = float(rsi_cfg.get("overbought_score", -3.0))
        self._rsi_neutral_bullish_score: float = float(rsi_cfg.get("neutral_bullish_score", 3.0))
        self._rsi_period: int = int(rsi_cfg.get("period", 14))

    def compute(
        self,
        symbol: str,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
        timeframe: str,
        classic_quadrant: str,
        fast_quadrant: str,
    ) -> CompositeScore:
        """Compute composite score for a symbol.

        Args:
            symbol: Ticker symbol.
            closes: Daily close prices, oldest first.
            highs: Daily high prices (unused in E.2b.1, reserved for E.2b.2+).
            lows: Daily low prices (unused in E.2b.1, reserved for E.2b.2+).
            volumes: Daily volumes (unused in E.2b.1, reserved for E.2b.2+).
            timeframe: "classic" or "fast".
            classic_quadrant: RRG quadrant from slow window (e.g. "LEADING").
            fast_quadrant: RRG quadrant from fast window.

        Returns:
            CompositeScore with rsi_score and quadrant_combo_score populated.
        """
        rsi_score = self._rsi_score(closes, self._rsi_period)
        quadrant_score = self._quadrant_combo_score(classic_quadrant, fast_quadrant)

        # TODO(E.2b.2): money_flow_score = self._money_flow_score(closes, highs, lows, volumes)
        # TODO(E.2b.2): divergence_penalty = self._divergence_penalty(closes, highs, lows, volumes)
        # TODO(E.2b.3): tech_score = self._tech_score(closes, highs, lows)
        # TODO(E.2b.3): earnings_score = self._earnings_score(symbol)
        # TODO(E.2b.3): seasonality_score = self._seasonality_score(symbol)

        total = rsi_score + quadrant_score

        return CompositeScore(
            symbol=symbol,
            timeframe=timeframe,
            total=total,
            rsi_score=rsi_score,
            quadrant_combo_score=quadrant_score,
        )

    def _rsi_score(self, closes: List[float], period: int) -> float:
        """Map RSI value to a score using YAML-configured thresholds.

        RSI < oversold_threshold  → oversold_score (max bullish)
        RSI oversold..50          → linear interpolation oversold_score → 0
        RSI 50..neutral_upper     → linear interpolation 0 → neutral_bullish_score
        RSI > neutral_upper       → overbought_score
        """
        if len(closes) < period + 1:
            return 0.0

        rsi = calculate_rsi(closes, period)

        oversold = self._rsi_oversold_threshold
        overbought = self._rsi_neutral_upper
        mid = 50.0

        if rsi < oversold:
            return self._rsi_oversold_score
        if rsi > overbought:
            return self._rsi_overbought_score
        if rsi <= mid:
            # linear: oversold_score at `oversold`, 0 at `mid`
            t = (rsi - oversold) / (mid - oversold)
            return self._rsi_oversold_score * (1 - t)
        # linear: 0 at `mid`, neutral_bullish_score at `overbought`
        t = (rsi - mid) / (overbought - mid)
        return self._rsi_neutral_bullish_score * t

    def _quadrant_combo_score(self, classic: str, fast: str) -> float:
        """Return score for (classic_quadrant, fast_quadrant) combination.

        Key format: "{CLASSIC}_{FAST}" (e.g. "LEADING_IMPROVING").
        Returns 0.0 for unknown combinations.
        """
        key = f"{classic}_{fast}"
        return self._quadrant_scores.get(key, 0.0)
