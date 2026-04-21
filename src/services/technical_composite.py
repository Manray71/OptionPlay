"""
TechnicalComposite — E.2b: Multi-Faktor Alpha-Composite.

Berechnet CompositeScore pro Symbol aus:
  E.2b.1: RSI-Score + Quadrant-Kombinations-Matrix (4x4)
  E.2b.2: Money Flow + Divergenz-Penalty + PRE-BREAKOUT Signal
  E.2b.3: Tech Score + Breakout-Patterns + Earnings + Seasonality
  E.2b.4: Integration in AlphaScorer  (TODO)

OHLCV-Daten werden als Parameter übergeben (Batch-Loading durch Caller).
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from src.indicators.momentum import calculate_rsi
from src.indicators.trend import calculate_adx

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path.home() / ".optionplay" / "trades.db"

# Static sector × month seasonality matrix.
# Monthly average returns (%) by GICS sector, index 0 = January.
# Approximation — calibrated in E.2b.5 against shadow data.
_SECTOR_SEASONALITY: Dict[str, List[float]] = {
    #                          Jan  Feb  Mar  Apr  May  Jun  Jul  Aug  Sep  Oct  Nov  Dec
    "Technology": [1.8, 0.5, 0.8, 1.5, 0.3, -0.5, 1.0, 0.5, -1.5, 0.5, 2.0, 1.5],
    "Healthcare": [1.5, 0.5, 0.8, 1.2, 0.5, 0.2, 0.5, 0.3, -0.8, 0.8, 1.5, 1.2],
    "Financials": [0.8, 0.5, 0.8, 1.0, -0.3, 0.5, 1.0, 0.3, -0.5, 0.8, 1.5, 0.8],
    "Consumer Discretionary": [0.5, 0.3, 0.5, 1.0, 0.5, -0.5, 0.5, 0.3, -1.0, 0.5, 2.5, 2.0],
    "Consumer Staples": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.3, 0.5, 0.8, 0.8],
    "Industrials": [0.5, 0.5, 1.0, 1.5, 0.5, -0.3, 0.5, 0.3, -0.5, 0.5, 1.5, 0.8],
    "Energy": [-0.5, 0.5, 1.5, 1.2, 1.0, 0.8, 0.5, 0.3, 0.3, -0.8, -0.5, -0.3],
    "Materials": [0.5, 0.5, 1.2, 1.5, 1.0, 0.5, 0.5, 0.3, -0.5, 0.5, 0.8, 0.5],
    "Real Estate": [1.5, 1.0, 0.5, 0.5, -0.5, -0.5, 0.5, 0.8, -1.0, 0.5, 1.2, 1.0],
    "Utilities": [1.0, 0.5, 0.3, -0.5, -0.8, -0.5, 0.5, 0.5, 0.5, 0.8, 0.8, 0.8],
    "Communication Services": [0.8, 0.5, 0.8, 1.0, 0.3, -0.3, 0.8, 0.3, -1.2, 0.5, 1.5, 1.2],
}


def _seasonality_avg_to_score(avg_return: float) -> float:
    if avg_return >= 3.0:
        return 3.0
    if avg_return >= 1.5:
        return 1.5
    if avg_return >= 0.5:
        return 0.5
    if avg_return >= -0.5:
        return 0.0
    if avg_return >= -1.5:
        return -1.0
    return -2.0


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
    breakout_score: float = 0.0
    pre_breakout: bool = False
    breakout_signals: tuple = ()


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
        *,
        opens: Optional[List[float]] = None,
        month: Optional[int] = None,
        db_path: Optional[Path] = None,
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
            opens: Daily open prices (optional, enables 3-bar play detection).
            month: Calendar month 1-12 for seasonality (defaults to today).
            db_path: Path to trades.db (defaults to ~/.optionplay/trades.db).

        Returns:
            CompositeScore with all E.2b.1–E.2b.3 components populated.
        """
        rsi_sc = self._rsi_score(closes, self._rsi_period)
        quad_sc = self._quadrant_combo_score(classic_quadrant, fast_quadrant)
        mf_sc = self._money_flow_score(closes, highs, lows, volumes)
        div_pen = self._divergence_penalty(closes, highs, lows, volumes)
        pre_bo = self._pre_breakout_check(closes, highs, lows, volumes)

        tech_sc = self._tech_score(closes, highs, lows)
        earn_sc = self._earnings_score(symbol, db_path=db_path)
        _month = month if month is not None else datetime.date.today().month
        seas_sc = self._seasonality_score(symbol, _month, db_path=db_path)
        brk_sc, brk_signals = self._breakout_score(closes, highs, lows, volumes, opens=opens)

        w = self._weights
        total = (
            rsi_sc * w["rsi"]
            + mf_sc * w["money_flow"]
            + tech_sc * w["tech"]
            + div_pen * w["divergence"]
            + earn_sc * w["earnings"]
            + seas_sc * w["seasonality"]
            + quad_sc * w["quadrant_combo"]
            + brk_sc  # breakout bonus is unweighted
        )

        return CompositeScore(
            symbol=symbol,
            timeframe=timeframe,
            total=total,
            rsi_score=rsi_sc,
            money_flow_score=mf_sc,
            tech_score=tech_sc,
            divergence_penalty=div_pen,
            earnings_score=earn_sc,
            seasonality_score=seas_sc,
            quadrant_combo_score=quad_sc,
            breakout_score=brk_sc,
            pre_breakout=pre_bo,
            breakout_signals=tuple(brk_signals),
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

    # -------------------------------------------------------------------------
    # E.2b.3 — Tech Score
    # -------------------------------------------------------------------------

    def _tech_score(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
    ) -> float:
        """SMA alignment + ADX trend strength + RSI peak-drop penalty.

        Range approx. -3.5 to +4.0.
        Falls back gracefully when < 200 bars are available.
        """
        if len(closes) < 20:
            return 0.0

        score = 0.0
        close = closes[-1]

        # --- SMA Alignment ---
        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
        sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None

        if close > sma20:
            score += 0.5
        if sma50 is not None:
            if close > sma50:
                score += 0.8
            if sma20 > sma50:
                score += 0.4
        if sma200 is not None:
            if close > sma200:
                score += 1.0
            if sma50 is not None and sma50 > sma200:
                score += 0.3
        # Downtrend penalty: both SMA50 and SMA200 above price
        if sma50 is not None and sma200 is not None:
            if close < sma50 and close < sma200:
                score -= 1.5

        # --- ADX Trend Strength ---
        adx = calculate_adx(highs, lows, closes, 14)
        if adx is not None:
            if adx >= 30:
                score += 1.0
            elif adx >= 20:
                score += 0.5
            elif adx < 15:
                score -= 0.3

        # --- RSI Peak-Drop K.O. (Christian's scanner.py L350-380) ---
        # Penalty when RSI was at 70+ recently but has since dropped ≥ 5 points.
        # Indicates momentum peak is over.
        if len(closes) >= self._rsi_period + 10:
            rsi_now = calculate_rsi(closes, self._rsi_period)
            rsi_peak_10d = rsi_now
            for i in range(1, 10):
                rsi_i = calculate_rsi(closes[:-i], self._rsi_period)
                if rsi_i > rsi_peak_10d:
                    rsi_peak_10d = rsi_i
            rsi_drop = rsi_peak_10d - rsi_now
            if rsi_now >= 65 and rsi_peak_10d >= 70 and rsi_drop >= 5:
                score -= 2.0

        return score

    # -------------------------------------------------------------------------
    # E.2b.3 — Breakout Pattern Detectors
    # -------------------------------------------------------------------------

    def _detect_bull_flag(
        self,
        closes: List[float],
        volumes: List[float],
        highs: List[float],
        lows: List[float],
    ) -> Dict[str, Any]:
        """Erkennt Bull Flag in 2 Stufen (Christian's technical.py:1554-1655).

        Returns dict with bull_flag (bool), breakout_imminent (bool).
        """
        result: Dict[str, Any] = {"bull_flag": False, "breakout_imminent": False}
        try:
            if len(closes) < 20 or len(volumes) < 20:
                return result

            lookback = min(15, len(closes) - 5)
            window = closes[-lookback:]
            peak_val = max(window)
            peak_idx = closes.index(peak_val, len(closes) - lookback)

            base_idx = max(0, peak_idx - 10)
            base = min(closes[base_idx : peak_idx + 1]) if base_idx < peak_idx else closes[base_idx]

            flagpole_pct = (peak_val / base - 1) * 100 if base > 0 else 0
            if flagpole_pct < 5.0:
                return result

            current = closes[-1]
            retracement = (
                (peak_val - current) / (peak_val - base) * 100 if (peak_val - base) > 0 else 0
            )
            if retracement > 30 or retracement < 0:
                return result

            flag_bars = len(closes) - 1 - peak_idx
            if flag_bars < 3:
                return result

            vol_flagpole = sum(volumes[base_idx : peak_idx + 1]) / max(peak_idx - base_idx, 1)
            vol_flag = sum(volumes[peak_idx + 1 :]) / max(flag_bars, 1)
            if vol_flag >= vol_flagpole * 0.80:
                return result

            result["bull_flag"] = True

            # --- Stufe 2: BREAKOUT IMMINENT ---
            if len(lows) != len(closes) or len(highs) != len(closes):
                return result

            flag_lows = lows[peak_idx + 1 :]
            flag_vols = volumes[peak_idx + 1 :]

            higher_lows = len(flag_lows) >= 3 and all(
                flag_lows[i] >= flag_lows[i - 1] * 0.995 for i in range(1, len(flag_lows))
            )

            vol_contracting = False
            if len(flag_vols) >= 3:
                vol_last2 = sum(flag_vols[-2:]) / 2
                vol_contracting = vol_last2 < vol_flag * 0.70

            from src.indicators.momentum import calculate_obv_series

            int_vol = [int(v) for v in volumes]
            obv_all = calculate_obv_series(closes, int_vol)
            obv_rising = len(obv_all) >= 4 and obv_all[-1] > obv_all[-(flag_bars + 1)]

            rsi_val = calculate_rsi(closes, self._rsi_period)
            rsi_recovering = 50 <= rsi_val <= 65

            imminent = higher_lows and vol_contracting and (obv_rising or rsi_recovering)
            if imminent:
                result["breakout_imminent"] = True

        except Exception:
            pass
        return result

    def _detect_bb_squeeze_release(self, closes: List[float]) -> bool:
        """True when Bollinger Bands are in squeeze AND expanding today.

        Squeeze: current bandwidth in bottom 20% of last 50 days.
        Release: bandwidth > 5% wider than yesterday's.
        """
        period = 20
        mult = 2.0
        if len(closes) < period + 10:
            return False
        try:

            def _bb(data: List[float], n: int, m: float) -> Tuple[float, float, float]:
                mid = sum(data[-n:]) / n
                std = (sum((x - mid) ** 2 for x in data[-n:]) / n) ** 0.5
                return mid - m * std, mid, mid + m * std

            lb, mb, ub = _bb(closes, period, mult)
            if mb <= 0:
                return False
            bandwidth = (ub - lb) / mb

            bandwidths = []
            for i in range(50, 0, -1):
                if len(closes) >= period + i:
                    _lb, _mb, _ub = _bb(closes[:-i], period, mult)
                    if _mb > 0:
                        bandwidths.append((_ub - _lb) / _mb)

            if not bandwidths:
                return False

            pct_rank = sum(1 for b in bandwidths if b < bandwidth) / len(bandwidths)
            squeeze = pct_rank <= 0.20

            if not squeeze:
                return False

            if len(closes) < period + 2:
                return False
            _lb2, _mb2, _ub2 = _bb(closes[:-1], period, mult)
            prev_bw = (_ub2 - _lb2) / _mb2 if _mb2 > 0 else 0
            return bandwidth > prev_bw * 1.05

        except Exception:
            return False

    def _detect_vwap_reclaim(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
        weeks: int = 2,
    ) -> bool:
        """True when price reclaims weekly VWAP (was below, now above).

        Uses 2-week (10-day) typical-price VWAP.
        """
        days = weeks * 5
        if len(closes) < days + 5:
            return False
        try:
            typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(-days, 0)]
            vols_w = volumes[-days:]
            total_vol = sum(vols_w)
            if total_vol <= 0:
                return False

            vwap = sum(t * v for t, v in zip(typical, vols_w)) / total_vol
            current = closes[-1]
            prev = closes[-2]
            prev2 = closes[-3] if len(closes) >= 3 else closes[-2]

            above_vwap = current > vwap
            was_below = prev < vwap or prev2 < vwap
            return above_vwap and was_below and current > prev

        except Exception:
            return False

    def _detect_three_bar_play(
        self,
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
    ) -> bool:
        """True for 3 consecutive bullish bars with rising volume and no long upper wick."""
        if len(closes) < 5 or len(opens) < 5:
            return False
        try:
            for offset in range(0, 3):
                i1, i2, i3 = -(3 + offset), -(2 + offset), -(1 + offset)
                o1, h1, l1, c1, v1 = opens[i1], highs[i1], lows[i1], closes[i1], volumes[i1]
                o2, h2, l2, c2, v2 = opens[i2], highs[i2], lows[i2], closes[i2], volumes[i2]
                o3, h3, l3, c3, v3 = opens[i3], highs[i3], lows[i3], closes[i3], volumes[i3]

                if not (c1 > o1 and c2 > o2 and c3 > o3):
                    continue
                if not (c2 > c1 and c3 > c2):
                    continue

                def upper_half(o: float, h: float, l: float, c: float) -> bool:
                    rng = h - l
                    return rng > 0 and c >= l + rng * 0.5

                if not (
                    upper_half(o1, h1, l1, c1)
                    and upper_half(o2, h2, l2, c2)
                    and upper_half(o3, h3, l3, c3)
                ):
                    continue

                if not (v2 > v1 and v3 > v2):
                    continue

                def short_upper_wick(h: float, c: float, o: float) -> bool:
                    body = abs(c - o)
                    wick = h - max(c, o)
                    return body > 0 and wick <= body * 0.50

                if not (
                    short_upper_wick(h1, c1, o1)
                    and short_upper_wick(h2, c2, o2)
                    and short_upper_wick(h3, c3, o3)
                ):
                    continue

                return True

        except Exception:
            pass
        return False

    def _detect_golden_pocket(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
        lookback: int = 60,
    ) -> bool:
        """True when price is in Golden Pocket (Fib 50-65%) WITH >= 2 confluence signals.

        Confluence signals available without RRG (E.2b.4 will add RRG):
          1. RSI recovery: RSI 45-65
          2. RVOL >= 1.2 (vs 20-day avg volume)

        Both signals must be present (= 2/2 confluence).
        """
        if len(closes) < 30:
            return False
        try:
            window = closes[-lookback:] if len(closes) >= lookback else closes[:]
            n = len(window)

            swing_high_idx = window.index(max(window))
            if n - swing_high_idx < 5:
                return False

            swing_high = window[swing_high_idx]
            after_peak = window[swing_high_idx + 1 : -1]
            if len(after_peak) < 3:
                return False

            swing_low = min(after_peak)
            swing_range = swing_high - swing_low
            if swing_range <= 0 or swing_range / swing_high < 0.05:
                return False

            gp_high = swing_high - swing_range * 0.50
            gp_low = swing_high - swing_range * 0.65

            current = closes[-1]
            prev = closes[-2]

            if not (gp_low <= current <= gp_high and current > prev):
                return False

            # Confluence check
            rsi_val = calculate_rsi(closes, self._rsi_period)
            rsi_ok = 45.0 <= rsi_val <= 65.0

            rvol_ok = False
            if len(volumes) >= 21 and volumes[-1] > 0:
                avg_vol = sum(volumes[-21:-1]) / 20
                rvol_ok = avg_vol > 0 and (volumes[-1] / avg_vol) >= 1.2

            return rsi_ok and rvol_ok

        except Exception:
            return False

    def _detect_nr7_inside_bar(
        self,
        highs: List[float],
        lows: List[float],
    ) -> bool:
        """True ONLY when both NR7 AND Inside Bar are simultaneously present.

        NR7: current bar has the narrowest range of the last 7 bars.
        Inside Bar: current bar's range fits within the prior bar's range.
        Standalone NR7 or standalone Inside Bar scores 0 — combination only.
        """
        if len(highs) < 8 or len(lows) < 8:
            return False
        try:
            curr_high, curr_low = highs[-1], lows[-1]
            prev_high, prev_low = highs[-2], lows[-2]
            inside_bar = curr_high <= prev_high and curr_low >= prev_low

            ranges = [highs[i] - lows[i] for i in range(-7, 0)]
            curr_range = ranges[-1]
            nr7 = curr_range == min(ranges) and curr_range > 0

            return inside_bar and nr7

        except Exception:
            return False

    def _breakout_score(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
        opens: Optional[List[float]] = None,
    ) -> Tuple[float, List[str]]:
        """Aggregate score from all 6 breakout pattern detectors.

        Returns (total_score, active_signal_names).
        Score is unweighted (already calibrated per pattern).
        """
        total = 0.0
        signals: List[str] = []

        bf = self._detect_bull_flag(closes, volumes, highs, lows)
        if bf["breakout_imminent"]:
            total += 5.0
            signals.append("BREAKOUT IMMINENT")
        elif bf["bull_flag"]:
            total += 2.5
            signals.append("Bull Flag")

        if self._detect_bb_squeeze_release(closes):
            total += 2.5
            signals.append("BB Squeeze Release")

        if self._detect_vwap_reclaim(closes, highs, lows, volumes):
            total += 3.0
            signals.append("VWAP Reclaim")

        if opens is not None and self._detect_three_bar_play(opens, highs, lows, closes, volumes):
            total += 2.5
            signals.append("3-Bar Play")

        if self._detect_golden_pocket(closes, highs, lows, volumes):
            total += 2.0
            signals.append("Golden Pocket+")

        if self._detect_nr7_inside_bar(highs, lows):
            total += 2.0
            signals.append("NR7+Inside Bar")

        return total, signals

    # -------------------------------------------------------------------------
    # E.2b.3 — Earnings Score
    # -------------------------------------------------------------------------

    def _earnings_score(
        self,
        symbol: str,
        db_path: Optional[Path] = None,
    ) -> float:
        """Maps existing earnings modifier to Christian's scale (+12 to -28).

        The existing modifier range +1.2 to -2.8 maps exactly to +12 to -28
        when multiplied by 10.
        Returns 0.0 when insufficient earnings data or DB unavailable.
        """
        try:
            from src.services.earnings_quality import calculate_earnings_surprise_modifier

            result = calculate_earnings_surprise_modifier(symbol, db_path=db_path)
            return result.modifier * 10.0
        except Exception:
            return 0.0

    # -------------------------------------------------------------------------
    # E.2b.3 — Seasonality Score
    # -------------------------------------------------------------------------

    def _get_sector(self, symbol: str, db_path: Optional[Path] = None) -> Optional[str]:
        """Look up sector for symbol from symbol_fundamentals."""
        db = db_path or _DEFAULT_DB
        if not Path(db).exists():
            return None
        try:
            conn = sqlite3.connect(str(db))
            cursor = conn.execute(
                "SELECT sector FROM symbol_fundamentals WHERE symbol = ?", (symbol,)
            )
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None

    def _seasonality_score(
        self,
        symbol: str,
        month: int,
        db_path: Optional[Path] = None,
    ) -> float:
        """Score based on static sector × month seasonality matrix.

        Uses _SECTOR_SEASONALITY (Option C from kickoff). Returns 0.0 when
        sector is unknown. Symbol-specific seasonality from DB added in E.2b.5.
        """
        if not (1 <= month <= 12):
            return 0.0

        sector = self._get_sector(symbol, db_path=db_path)
        if sector is None:
            return 0.0

        monthly_returns = _SECTOR_SEASONALITY.get(sector)
        if monthly_returns is None:
            return 0.0

        avg_return = monthly_returns[month - 1]
        return _seasonality_avg_to_score(avg_return)
