"""
TechnicalComposite — E.2b: Multi-Faktor Alpha-Composite.

Berechnet CompositeScore pro Symbol aus:
  E.2b.1: RSI-Score + Quadrant-Kombinations-Matrix (4x4)
  E.2b.2: Money Flow + Divergenz-Penalty + PRE-BREAKOUT Signal
  E.2b.3: Tech Score + Breakout-Patterns + Earnings + Seasonality  (TODO)
  E.2b.4: Integration in AlphaScorer  (TODO)

OHLCV-Daten werden als Parameter übergeben (Batch-Loading durch Caller).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    pre_breakout: bool = False


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

        div_cfg = cfg.get("divergence_penalties", {})
        self._div_penalty_single: float = float(div_cfg.get("single", -6))
        self._div_penalty_double: float = float(div_cfg.get("double", -12))
        self._div_penalty_severe: float = float(div_cfg.get("severe", -20))

        mf_cfg = cfg.get("money_flow_scoring", {})
        self._mf_obv_weight: float = float(mf_cfg.get("obv_weight", 0.40))
        self._mf_mfi_weight: float = float(mf_cfg.get("mfi_weight", 0.35))
        self._mf_cmf_weight: float = float(mf_cfg.get("cmf_weight", 0.25))
        self._mf_obv_sma_period: int = int(mf_cfg.get("obv_sma_period", 20))
        self._mf_mfi_period: int = int(mf_cfg.get("mfi_period", 14))
        self._mf_cmf_period: int = int(mf_cfg.get("cmf_period", 20))

        weights_cfg = cfg.get("weights", {})
        self._weights: Dict[str, float] = {
            "rsi": float(weights_cfg.get("rsi", 1.0)),
            "money_flow": float(weights_cfg.get("money_flow", 1.0)),
            "tech": float(weights_cfg.get("tech", 1.0)),
            "divergence": float(weights_cfg.get("divergence", 1.0)),
            "earnings": float(weights_cfg.get("earnings", 1.0)),
            "seasonality": float(weights_cfg.get("seasonality", 0.5)),
            "quadrant_combo": float(weights_cfg.get("quadrant_combo", 1.0)),
        }

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
            highs: Daily high prices.
            lows: Daily low prices.
            volumes: Daily volumes.
            timeframe: "classic" or "fast".
            classic_quadrant: RRG quadrant from slow window (e.g. "LEADING").
            fast_quadrant: RRG quadrant from fast window.

        Returns:
            CompositeScore with all E.2b.1+E.2b.2 components populated.
        """
        rsi_sc = self._rsi_score(closes, self._rsi_period)
        quad_sc = self._quadrant_combo_score(classic_quadrant, fast_quadrant)
        mf_sc = self._money_flow_score(closes, highs, lows, volumes)
        div_pen = self._divergence_penalty(closes, highs, lows, volumes)
        pre_bo = self._pre_breakout_check(closes, highs, lows, volumes)

        # TODO(E.2b.3): tech_score = self._tech_score(closes, highs, lows)
        # TODO(E.2b.3): earnings_score = self._earnings_score(symbol)
        # TODO(E.2b.3): seasonality_score = self._seasonality_score(symbol)

        w = self._weights
        total = (
            rsi_sc * w["rsi"]
            + mf_sc * w["money_flow"]
            + div_pen * w["divergence"]
            + quad_sc * w["quadrant_combo"]
        )

        return CompositeScore(
            symbol=symbol,
            timeframe=timeframe,
            total=total,
            rsi_score=rsi_sc,
            money_flow_score=mf_sc,
            divergence_penalty=div_pen,
            quadrant_combo_score=quad_sc,
            pre_breakout=pre_bo,
        )

    # -------------------------------------------------------------------------
    # E.2b.1 components
    # -------------------------------------------------------------------------

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
            t = (rsi - oversold) / (mid - oversold)
            return self._rsi_oversold_score * (1 - t)
        t = (rsi - mid) / (overbought - mid)
        return self._rsi_neutral_bullish_score * t

    def _quadrant_combo_score(self, classic: str, fast: str) -> float:
        """Return score for (classic_quadrant, fast_quadrant) combination.

        Key format: "{CLASSIC}_{FAST}" (e.g. "LEADING_IMPROVING").
        Returns 0.0 for unknown combinations.
        """
        key = f"{classic}_{fast}"
        return self._quadrant_scores.get(key, 0.0)

    # -------------------------------------------------------------------------
    # E.2b.2 components
    # -------------------------------------------------------------------------

    def _money_flow_score(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
    ) -> float:
        """Weighted combination: OBV (40%) + MFI (35%) + CMF (25%)."""
        obv_comp = self._obv_component(closes, volumes)
        mfi_comp = self._mfi_component(highs, lows, closes, volumes)
        cmf_comp = self._cmf_component(highs, lows, closes, volumes)
        return (
            obv_comp * self._mf_obv_weight
            + mfi_comp * self._mf_mfi_weight
            + cmf_comp * self._mf_cmf_weight
        )

    def _obv_component(self, closes: List[float], volumes: List[float]) -> float:
        """OBV score relative to its SMA20.

        +1.0  OBV > SMA20 (accumulation)
        +0.5  bonus if OBV crossed SMA20 upward within last 3 bars
        -0.5  OBV < SMA20 (distribution)
        -1.0  additional if price rising while OBV falling (bearish divergence)
        """
        if len(closes) < self._mf_obv_sma_period + 2:
            return 0.0

        from src.indicators.momentum import calculate_obv_series

        int_vol = [int(v) for v in volumes]
        obv = calculate_obv_series(closes, int_vol)
        if len(obv) < self._mf_obv_sma_period:
            return 0.0

        sma20 = sum(obv[-self._mf_obv_sma_period :]) / self._mf_obv_sma_period

        if obv[-1] > sma20:
            score = 1.0
            # Crossover bonus: any of the 3 bars before today was below SMA20
            if len(obv) >= self._mf_obv_sma_period + 3 and any(
                obv[-(j + 1)] < sma20 for j in range(1, 4)
            ):
                score += 0.5
        else:
            score = -0.5

        # Bearish divergence: price rising but OBV falling over last 5 bars
        if len(closes) >= 6 and closes[-1] > closes[-6] and obv[-1] < obv[-6]:
            score -= 1.0

        return score

    def _mfi_component(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
    ) -> float:
        """MFI score based on zone and direction (rising = today > 3 days ago)."""
        if len(closes) < self._mf_mfi_period + 4:
            return 0.0

        from src.indicators.momentum import calculate_mfi_series

        int_vol = [int(v) for v in volumes]
        mfi = calculate_mfi_series(highs, lows, closes, int_vol, period=self._mf_mfi_period)
        if len(mfi) < 4:
            return 0.0

        current = mfi[-1]
        rising = current > mfi[-4]

        if current > 80:
            return -0.5
        if current < 30:
            return 1.5 if rising else -1.0
        if 40 <= current <= 60 and rising:
            return 1.0
        if current > 60:
            return 0.5
        return 0.0

    def _cmf_component(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
    ) -> float:
        """CMF score based on level and direction (rising = today > 3 days ago)."""
        if len(closes) < self._mf_cmf_period + 4:
            return 0.0

        from src.indicators.momentum import calculate_cmf_series

        int_vol = [int(v) for v in volumes]
        cmf = calculate_cmf_series(highs, lows, closes, int_vol, period=self._mf_cmf_period)
        if len(cmf) < 4:
            return 0.0

        current = cmf[-1]
        rising = current > cmf[-4]

        if current > 0.10 and rising:
            return 1.5
        if current > 0.05 and rising:
            return 1.0
        if current > 0:
            return 0.3
        if current < -0.10:
            return -1.5
        if current < -0.05:
            return -0.8
        if current < 0:
            return -0.3
        return 0.0

    def _divergence_penalty(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
    ) -> float:
        """Christian's scale: 0 / -6 / -12 / -20 based on active divergence count.

        Uses 5 existing checks from divergence.py. Penalty scale is independent
        of the Pullback-Analyzer's soft penalties (-1.0 to -2.0).
        """
        from src.indicators.divergence import (
            check_cmf_and_macd_falling,
            check_cmf_early_warning,
            check_price_mfi_divergence,
            check_price_obv_divergence,
            check_price_rsi_divergence,
        )

        int_vol = [int(v) for v in volumes]
        checks = [
            check_price_rsi_divergence(closes, lows, highs),
            check_price_obv_divergence(closes, int_vol),
            check_price_mfi_divergence(closes, highs, lows, int_vol),
            check_cmf_and_macd_falling(closes, highs, lows, int_vol),
            check_cmf_early_warning(closes, highs, lows, int_vol),
        ]

        active = sum(1 for c in checks if c.detected)

        if active == 0:
            return 0.0
        if active == 1:
            return self._div_penalty_single
        if active <= 3:
            return self._div_penalty_double
        return self._div_penalty_severe

    def _pre_breakout_check(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
    ) -> bool:
        """True when all 4 PRE-BREAKOUT Phase 2 conditions are met.

        From Christian's score_technicals() (technical.py L1914-1934):
        - CMF > 0.10 and rising
        - 50 <= MFI <= 65 and rising
        - OBV > SMA20(OBV)
        - 50 <= RSI <= 65
        """
        min_len = max(self._mf_cmf_period, self._mf_mfi_period, self._mf_obv_sma_period) + 4
        if len(closes) < min_len:
            return False

        from src.indicators.momentum import (
            calculate_cmf_series,
            calculate_mfi_series,
            calculate_obv_series,
            calculate_rsi,
        )

        rsi_val = calculate_rsi(closes, self._rsi_period)
        if not (50.0 <= rsi_val <= 65.0):
            return False

        int_vol = [int(v) for v in volumes]

        cmf = calculate_cmf_series(highs, lows, closes, int_vol, period=self._mf_cmf_period)
        if len(cmf) < 4:
            return False
        if not (cmf[-1] > 0.10 and cmf[-1] > cmf[-4]):
            return False

        mfi = calculate_mfi_series(highs, lows, closes, int_vol, period=self._mf_mfi_period)
        if len(mfi) < 4:
            return False
        if not (50.0 <= mfi[-1] <= 65.0 and mfi[-1] > mfi[-4]):
            return False

        obv = calculate_obv_series(closes, int_vol)
        if len(obv) < self._mf_obv_sma_period:
            return False
        sma20_obv = sum(obv[-self._mf_obv_sma_period :]) / self._mf_obv_sma_period
        return obv[-1] > sma20_obv
