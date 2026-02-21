# OptionPlay - Trend Continuation Analyzer (v2)
# ===============================================
# Analyzes stocks in stable uptrends — state-based signal (no event trigger)
#
# Strategy: Sell Bull-Put-Spreads on stocks with perfect SMA alignment,
# placing the short strike below SMA 50 as dynamic support.
#
# 5-Component Scoring (max 10.5):
#   1. SMA Alignment      (0 – 2.5)
#   2. Trend Stability     (0 – 2.0, +0.5 bonus)
#   3. Trend Buffer        (0 – 2.0)
#   4. Momentum Health     (0 – 2.0, penalties possible)
#   5. Volatility Suitab.  (0 – 1.5)
#
# Minimum for signal: 5.0 (stricter than event-based strategies)

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..constants.trading_rules import (
    ENTRY_VOLUME_MIN,
    VIX_DANGER_ZONE_MAX,
    VIX_LOW_VOL_MAX,
    VIX_NORMAL_MAX,
)
from ..models.base import SignalStrength, SignalType, TradeSignal
from ..models.strategy_breakdowns import TrendContinuationScoreBreakdown
from .base import BaseAnalyzer
from .context import AnalysisContext

# Import Feature Scoring Mixin
from .feature_scoring_mixin import FeatureScoringMixin
from .score_normalization import STRATEGY_SCORE_CONFIGS, clamp_score, normalize_score

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS for Trend Continuation Strategy  (loaded from config/analyzer_thresholds.yaml)
# =============================================================================
from ..config.analyzer_thresholds import get_analyzer_thresholds as _get_cfg

_cfg = _get_cfg()

TREND_MIN_SCORE = _cfg.get("trend_continuation.general.min_score", 5.0)
TREND_MAX_SCORE = _cfg.get("trend_continuation.general.max_score", 10.5)

# SMA Periods
TREND_SMA_SHORT = _cfg.get("trend_continuation.sma.short", 20)
TREND_SMA_MED = _cfg.get("trend_continuation.sma.med", 50)
TREND_SMA_LONG = _cfg.get("trend_continuation.sma.long", 200)

# SMA Slope Lookback (in days)
TREND_SMA20_SLOPE_DAYS = _cfg.get("trend_continuation.sma_slope.short_days", 5)
TREND_SMA50_SLOPE_DAYS = _cfg.get("trend_continuation.sma_slope.med_days", 10)
TREND_SMA200_SLOPE_DAYS = _cfg.get("trend_continuation.sma_slope.long_days", 20)

# Trend Stability
TREND_STABILITY_LOOKBACK = _cfg.get("trend_continuation.stability.lookback", 60)
TREND_MAX_CLOSES_BELOW_SMA50 = _cfg.get("trend_continuation.stability.max_closes_below_sma50", 5)

# Disqualification Thresholds
TREND_MIN_BUFFER_PCT = _cfg.get("trend_continuation.disqualification.min_buffer_pct", 3.0)
TREND_RSI_OVERBOUGHT = _cfg.get("trend_continuation.disqualification.rsi_overbought", 80)
TREND_ADX_MIN = _cfg.get("trend_continuation.disqualification.adx_min", 15)
TREND_MIN_AVG_VOLUME = ENTRY_VOLUME_MIN  # Stays linked to trading_rules
TREND_MIN_STABILITY_SCORE = _cfg.get("trend_continuation.disqualification.min_stability_score", 70)
TREND_MIN_EARNINGS_DAYS = _cfg.get("trend_continuation.disqualification.min_earnings_days", 14)
TREND_VIX_MAX = VIX_DANGER_ZONE_MAX  # Stays linked to trading_rules

# Volume average period
TREND_VOLUME_AVG_PERIOD = _cfg.get("trend_continuation.volume.avg_period", 20)


@dataclass
class TrendContinuationConfig:
    """Configuration for Trend Continuation Analyzer."""

    # SMA Periods
    sma_short: int = TREND_SMA_SHORT
    sma_med: int = TREND_SMA_MED
    sma_long: int = TREND_SMA_LONG

    # SMA Slope Lookback
    sma_short_slope_days: int = TREND_SMA20_SLOPE_DAYS
    sma_med_slope_days: int = TREND_SMA50_SLOPE_DAYS
    sma_long_slope_days: int = TREND_SMA200_SLOPE_DAYS

    # Trend Stability
    stability_lookback_days: int = TREND_STABILITY_LOOKBACK
    max_closes_below_sma50: int = TREND_MAX_CLOSES_BELOW_SMA50

    # Disqualification
    min_buffer_pct: float = TREND_MIN_BUFFER_PCT
    rsi_overbought: float = TREND_RSI_OVERBOUGHT
    adx_min: float = TREND_ADX_MIN
    min_avg_volume: int = TREND_MIN_AVG_VOLUME
    min_stability_score: float = TREND_MIN_STABILITY_SCORE
    min_earnings_days: int = TREND_MIN_EARNINGS_DAYS
    vix_max: float = TREND_VIX_MAX

    # Scoring
    min_score_for_signal: float = TREND_MIN_SCORE
    max_score: float = TREND_MAX_SCORE

    # Volume
    volume_avg_period: int = TREND_VOLUME_AVG_PERIOD

    # Risk Management
    stop_below_sma50_pct: float = 2.0
    target_risk_reward: float = 2.0


class TrendContinuationAnalyzer(BaseAnalyzer, FeatureScoringMixin):
    """
    Trend Continuation Analyzer (v2 pattern).

    Identifies stocks in stable uptrends suitable for Bull-Put-Spreads.
    State-based signal: no event trigger needed.

    4-Step Pipeline:
        1. Check SMA alignment (PFLICHT)
        2. Check trend stability (PFLICHT)
        3. Check disqualifications (RSI, ADX, buffer, earnings, volume, stability)
        4. Check VIX regime (HIGH → deactivate)
        → Score 5 components
        → Build signal text
    """

    def __init__(self, config: Optional[TrendContinuationConfig] = None, **kwargs) -> None:
        self.config = config or TrendContinuationConfig()

    @property
    def strategy_name(self) -> str:
        return "trend_continuation"

    @property
    def description(self) -> str:
        return "Trend Continuation - Stable uptrend with SMA alignment for safe Bull-Put-Spreads"

    def analyze(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        context: Optional[AnalysisContext] = None,
        **kwargs,
    ) -> TradeSignal:
        """
        Analyze a symbol for trend continuation signal.

        Args:
            symbol: Ticker symbol
            prices: Close prices (oldest first)
            volumes: Volume data
            highs: High prices
            lows: Low prices
            context: Optional pre-calculated AnalysisContext
            **kwargs: Additional params (vix, fundamentals, earnings_days, etc.)

        Returns:
            TradeSignal with trend continuation analysis
        """
        # Validation
        self.validate_inputs(
            prices,
            volumes,
            highs,
            lows,
            min_length=self.config.sma_long + self.config.sma_long_slope_days,
        )

        current_price = prices[-1]
        breakdown = TrendContinuationScoreBreakdown()

        # === VIX REGIME CHECK (Step 0 — early exit) ===
        vix = kwargs.get("vix", None)
        vix_regime = self._get_vix_regime(vix)
        breakdown.vix_regime = vix_regime

        if vix_regime == "high":
            return self._make_disqualified_signal(
                symbol,
                current_price,
                (
                    f"Trend Continuation disabled at HIGH VIX ({vix:.1f})"
                    if vix
                    else "Trend Continuation disabled at HIGH VIX"
                ),
            )

        # === STEP 1: SMA ALIGNMENT (PFLICHT) ===
        sma_info = self._check_sma_alignment(prices)
        if not sma_info["aligned"]:
            return self._make_disqualified_signal(
                symbol, current_price, sma_info.get("reason", "SMA alignment failed")
            )

        breakdown.sma_20 = sma_info["sma_20"]
        breakdown.sma_50 = sma_info["sma_50"]
        breakdown.sma_200 = sma_info["sma_200"]
        breakdown.sma_all_rising = sma_info["all_rising"]

        # === STEP 2: TREND STABILITY (PFLICHT) ===
        stability_info = self._check_trend_stability(prices, sma_info)
        if not stability_info["stable"]:
            return self._make_disqualified_signal(
                symbol, current_price, stability_info.get("reason", "Trend not stable")
            )

        breakdown.closes_below_sma50 = stability_info["closes_below_sma50"]
        breakdown.stability_days = self.config.stability_lookback_days
        breakdown.golden_cross_days = stability_info.get("golden_cross_days", 0)

        # === STEP 3: DISQUALIFICATIONS ===
        # Buffer check
        buffer_to_sma50 = (current_price - sma_info["sma_50"]) / sma_info["sma_50"] * 100
        buffer_to_sma200 = (current_price - sma_info["sma_200"]) / sma_info["sma_200"] * 100
        breakdown.buffer_to_sma50_pct = buffer_to_sma50
        breakdown.buffer_to_sma200_pct = buffer_to_sma200

        if buffer_to_sma50 < self.config.min_buffer_pct:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Insufficient buffer: {buffer_to_sma50:.1f}% to SMA 50 (min {self.config.min_buffer_pct}%)",
            )

        # RSI check (prefer context if available)
        rsi = None
        if context is not None and context.rsi_14 is not None:
            rsi = context.rsi_14
        else:
            rsi = self._calculate_rsi(prices, 14)
        breakdown.rsi_value = rsi if rsi is not None else 0

        if rsi is not None and rsi > self.config.rsi_overbought:
            return self._make_disqualified_signal(
                symbol, current_price, f"Overbought: RSI {rsi:.1f} > {self.config.rsi_overbought}"
            )

        # ADX check
        adx = self._calculate_adx(highs, lows, prices, 14)
        breakdown.adx_value = adx if adx is not None else 0

        if adx is not None and adx < self.config.adx_min:
            return self._make_disqualified_signal(
                symbol, current_price, f"No trend: ADX {adx:.1f} < {self.config.adx_min}"
            )

        # Volume check
        avg_volume = (
            sum(volumes[-self.config.volume_avg_period :]) / self.config.volume_avg_period
            if len(volumes) >= self.config.volume_avg_period
            else sum(volumes) / len(volumes)
        )
        if avg_volume < self.config.min_avg_volume:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Low liquidity: avg volume {avg_volume:,.0f} < {self.config.min_avg_volume:,}",
            )

        # Fundamentals check
        fundamentals = kwargs.get("fundamentals", None)
        if fundamentals:
            stability_score = getattr(fundamentals, "stability_score", None)
            if stability_score is not None and stability_score < self.config.min_stability_score:
                return self._make_disqualified_signal(
                    symbol,
                    current_price,
                    f"Low stability: {stability_score:.0f} < {self.config.min_stability_score}",
                )

        # Earnings check
        earnings_days = kwargs.get("earnings_days", None)
        if earnings_days is not None and 0 < earnings_days < self.config.min_earnings_days:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Earnings in {earnings_days} days (min {self.config.min_earnings_days})",
            )

        # === SCORING: 5 Components ===
        # 1. SMA Alignment Quality
        sma_alignment_score = self._score_sma_alignment(sma_info, current_price)
        breakdown.sma_alignment_score = sma_alignment_score
        breakdown.sma_spread_pct = sma_info.get("spread_pct", 0)

        # 2. Trend Stability
        stability_score = self._score_trend_stability(stability_info)
        breakdown.stability_score = stability_score

        # 3. Trend Buffer
        buffer_score = self._score_trend_buffer(buffer_to_sma50)
        breakdown.buffer_score = buffer_score

        # 4. Momentum Health
        macd_info = self._calculate_macd_info(prices, context)
        volume_divergence = self._check_volume_divergence(prices, volumes)
        momentum_score = self._score_momentum_health(rsi, adx, macd_info, volume_divergence)
        breakdown.momentum_score = momentum_score
        breakdown.macd_bullish = macd_info.get("bullish", False) if macd_info else False
        breakdown.volume_divergence = volume_divergence

        # 5. Volatility Suitability
        atr_pct = self._calculate_atr_pct(prices, highs, lows)
        volatility_score = self._score_volatility(atr_pct)
        breakdown.volatility_score = volatility_score
        breakdown.atr_pct = atr_pct if atr_pct is not None else 0

        # === Apply YAML weights (trained) ===
        # Default max per component (matches hardcoded scoring ranges above)
        _DEFAULTS = {
            "sma_alignment": 2.5,
            "trend_stability": 2.5,
            "trend_buffer": 2.0,
            "momentum_health": 2.0,
            "volatility": 1.5,
        }

        # Load trained weights from scoring_weights.yaml
        regime = getattr(context, "regime", "normal") if context else "normal"
        sector = getattr(context, "sector", None) if context else None
        try:
            resolved = self.get_weights(regime=regime, sector=sector)
            w = resolved.weights
        except (KeyError, AttributeError, ImportError):
            w = {}

        def _scale(component: str, raw: float) -> float:
            """Scale a component score by the ratio of YAML weight to hardcoded default."""
            yaml_max = w.get(component)
            if yaml_max is None:
                return raw
            default_max = _DEFAULTS.get(component, 1.0)
            if default_max <= 0:
                return raw
            return raw * (yaml_max / default_max)

        _components = {
            "sma_alignment": sma_alignment_score,
            "trend_stability": stability_score,
            "trend_buffer": buffer_score,
            "momentum_health": momentum_score,
            "volatility": volatility_score,
        }

        # Total Score with weight scaling
        total_score = sum(_scale(k, v) for k, v in _components.items())

        # VIX Regime Adjustment
        vix_adjustment = self._get_vix_adjustment(vix_regime)
        breakdown.vix_adjustment = vix_adjustment
        total_score = total_score * vix_adjustment

        # Dynamic effective_max: sum of YAML weights (or defaults if no YAML)
        effective_max = sum(w.get(k, _DEFAULTS[k]) for k in _DEFAULTS)

        # Clamp on scaled range
        total_score = clamp_score(total_score, effective_max)
        breakdown.total_score = round(total_score, 1)

        # Strike Zone Recommendation
        conservative_short = math.floor(sma_info["sma_50"] / 5) * 5
        aggressive_short = math.floor((sma_info["sma_20"] + sma_info["sma_50"]) / 2 / 5) * 5
        breakdown.conservative_short_strike = conservative_short
        breakdown.aggressive_short_strike = aggressive_short

        # Build reasons
        sma_desc = "Perfect SMA alignment" if sma_info["all_rising"] else "SMA-aligned"
        stability_desc = f"{self.config.stability_lookback_days}d stable"
        if stability_info["closes_below_sma50"] > 0:
            stability_desc += f", {stability_info['closes_below_sma50']} minor wicks"
        if stability_info.get("golden_cross_days", 0) >= 120:
            stability_desc += f", Golden Cross {stability_info['golden_cross_days']}d ago"

        # Populate breakdown reasons
        breakdown.sma_reason = sma_desc
        breakdown.stability_reason = stability_desc
        breakdown.buffer_reason = f"Buffer {buffer_to_sma50:.1f}% to SMA 50"
        momentum_parts = []
        if rsi is not None:
            momentum_parts.append(f"RSI {rsi:.0f}")
        if adx is not None:
            momentum_parts.append(f"ADX {adx:.0f}")
        if macd_info and macd_info.get("bullish"):
            momentum_parts.append("MACD bullish")
        breakdown.momentum_reason = ", ".join(momentum_parts) if momentum_parts else ""
        breakdown.volatility_reason = f"ATR {atr_pct:.1f}%" if atr_pct is not None else ""

        # Build signal text
        signal_text = self._build_signal_text(
            sma_desc,
            stability_desc,
            buffer_to_sma50,
            buffer_to_sma200,
            rsi,
            adx,
            macd_info,
            atr_pct,
        )

        # Normalize to 0-10 scale using dynamic effective_max
        normalized_score = normalize_score(
            total_score, "trend_continuation", max_possible=effective_max
        )

        # Signal type and strength on normalized 0-10 scale
        tc_config = STRATEGY_SCORE_CONFIGS["trend_continuation"]
        if normalized_score >= tc_config.weak_threshold:
            signal_type = SignalType.LONG
            if normalized_score >= tc_config.strong_threshold:
                strength = SignalStrength.STRONG
            elif normalized_score >= tc_config.moderate_threshold:
                strength = SignalStrength.MODERATE
            else:
                strength = SignalStrength.WEAK
        else:
            signal_type = SignalType.NEUTRAL
            strength = SignalStrength.NONE

        # Entry/Stop/Target
        entry_price = current_price
        stop_loss = sma_info["sma_50"] * (1 - self.config.stop_below_sma50_pct / 100)
        target_price = entry_price + (entry_price - stop_loss) * self.config.target_risk_reward

        # Warnings
        warnings = []
        if vix_regime == "elevated":
            warnings.append(f"Elevated VIX regime — conservative strikes recommended")
        if volume_divergence:
            warnings.append("Volume divergence detected — possible trend weakening")
        if rsi is not None and rsi > 70:
            warnings.append(f"RSI {rsi:.0f} approaching overbought territory")

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=signal_type,
            strength=strength,
            score=round(normalized_score, 1),
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=round(stop_loss, 2),
            target_price=round(target_price, 2),
            reason=signal_text,
            details={
                "score_breakdown": breakdown.to_dict(),
                "raw_score": round(total_score, 1),
                "max_possible": effective_max,
                "strike_zone": {
                    "conservative_short": conservative_short,
                    "aggressive_short": aggressive_short,
                    "sma_50": round(sma_info["sma_50"], 2),
                    "sma_200": round(sma_info["sma_200"], 2),
                },
                "components": {
                    "sma_alignment": sma_alignment_score,
                    "trend_stability": stability_score,
                    "trend_buffer": buffer_score,
                    "momentum_health": momentum_score,
                    "volatility": volatility_score,
                },
            },
            warnings=warnings,
            timestamp=datetime.now(),
        )

    # =========================================================================
    # STEP 1: SMA ALIGNMENT
    # =========================================================================

    def _check_sma_alignment(self, prices: List[float]) -> Dict[str, Any]:
        """
        Check if Close > SMA 20 > SMA 50 > SMA 200, all rising.

        Returns dict with aligned, sma_20, sma_50, sma_200, all_rising, reason.
        """
        n = len(prices)
        sma_short = self.config.sma_short
        sma_med = self.config.sma_med
        sma_long = self.config.sma_long

        if n < sma_long + self.config.sma_long_slope_days:
            return {
                "aligned": False,
                "reason": f"Insufficient data: need {sma_long + self.config.sma_long_slope_days}, have {n}",
            }

        # Current SMAs
        sma_20 = sum(prices[-sma_short:]) / sma_short
        sma_50 = sum(prices[-sma_med:]) / sma_med
        sma_200 = sum(prices[-sma_long:]) / sma_long

        close = prices[-1]

        # Check ordering: Close > SMA 20 > SMA 50 > SMA 200
        if close <= sma_20:
            return {
                "aligned": False,
                "reason": f"Close ${close:.2f} <= SMA 20 ${sma_20:.2f}",
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
            }

        if sma_20 <= sma_50:
            return {
                "aligned": False,
                "reason": f"SMA 20 ${sma_20:.2f} <= SMA 50 ${sma_50:.2f}",
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
            }

        if sma_50 <= sma_200:
            return {
                "aligned": False,
                "reason": f"SMA 50 ${sma_50:.2f} <= SMA 200 ${sma_200:.2f} (Death Cross)",
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
            }

        # Check slopes (all rising)
        slope_20_days = self.config.sma_short_slope_days
        slope_50_days = self.config.sma_med_slope_days
        slope_200_days = self.config.sma_long_slope_days

        sma_20_prev = sum(prices[-(sma_short + slope_20_days) : -(slope_20_days)]) / sma_short
        sma_50_prev = sum(prices[-(sma_med + slope_50_days) : -(slope_50_days)]) / sma_med
        sma_200_prev = sum(prices[-(sma_long + slope_200_days) : -(slope_200_days)]) / sma_long

        sma_20_rising = sma_20 > sma_20_prev
        sma_50_rising = sma_50 > sma_50_prev
        sma_200_rising = sma_200 > sma_200_prev

        all_rising = sma_20_rising and sma_50_rising and sma_200_rising

        if not sma_50_rising and not sma_200_rising:
            return {
                "aligned": False,
                "reason": "SMA 50 and SMA 200 not rising — no uptrend",
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
            }

        # Calculate SMA spread
        spread_pct = (sma_20 - sma_200) / close * 100

        return {
            "aligned": True,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "sma_20_rising": sma_20_rising,
            "sma_50_rising": sma_50_rising,
            "sma_200_rising": sma_200_rising,
            "all_rising": all_rising,
            "spread_pct": spread_pct,
        }

    # =========================================================================
    # STEP 2: TREND STABILITY
    # =========================================================================

    def _check_trend_stability(
        self,
        prices: List[float],
        sma_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Check that price stayed above SMA 50 for last N days.

        Returns dict with stable, closes_below_sma50, golden_cross_days, reason.
        """
        lookback = min(self.config.stability_lookback_days, len(prices) - self.config.sma_med)
        if lookback <= 0:
            return {
                "stable": False,
                "closes_below_sma50": 0,
                "reason": "Insufficient data for stability check",
            }

        closes_below = 0
        # Check last `lookback` days
        for i in range(lookback):
            idx = len(prices) - 1 - i
            if idx < self.config.sma_med:
                break
            sma_50_at_idx = (
                sum(prices[idx - self.config.sma_med + 1 : idx + 1]) / self.config.sma_med
            )
            if prices[idx] < sma_50_at_idx:
                closes_below += 1

        if closes_below > self.config.max_closes_below_sma50:
            return {
                "stable": False,
                "closes_below_sma50": closes_below,
                "reason": f"{closes_below} closes below SMA 50 in {lookback}d (max {self.config.max_closes_below_sma50})",
            }

        # Check golden cross age: how long has SMA 50 been above SMA 200?
        golden_cross_days = 0
        max_check = min(len(prices) - self.config.sma_long, 250)
        for i in range(max_check):
            idx = len(prices) - 1 - i
            if idx < self.config.sma_long:
                break
            sma_50_at_idx = (
                sum(prices[idx - self.config.sma_med + 1 : idx + 1]) / self.config.sma_med
            )
            sma_200_at_idx = (
                sum(prices[idx - self.config.sma_long + 1 : idx + 1]) / self.config.sma_long
            )
            if sma_50_at_idx > sma_200_at_idx:
                golden_cross_days += 1
            else:
                break

        return {
            "stable": True,
            "closes_below_sma50": closes_below,
            "golden_cross_days": golden_cross_days,
        }

    # =========================================================================
    # SCORING COMPONENTS
    # =========================================================================

    def _score_sma_alignment(self, sma_info: Dict[str, Any], current_price: float) -> float:
        """
        Score SMA alignment quality (0 – 2.5).

        Perfect alignment (all rising): 2.0
        SMA spread bonus (>5%): +0.5
        SMA 20 not rising penalty: -0.5
        """
        sma_cfg = _cfg.get_section("trend_continuation.sma_alignment_scoring")
        score = 0.0

        if sma_info.get("all_rising"):
            score = sma_cfg.get("all_rising", 2.0)
        elif sma_info.get("sma_50_rising") and sma_info.get("sma_200_rising"):
            score = sma_cfg.get("partial_rising", 1.5)
        else:
            score = sma_cfg.get("basic", 1.0)

        # SMA spread bonus
        spread_pct = sma_info.get("spread_pct", 0)
        if spread_pct > sma_cfg.get("spread_bonus_above", 5.0):
            score += 0.5
        elif spread_pct < sma_cfg.get("spread_penalty_below", 3.0):
            score -= 0.5

        # Penalty for SMA 20 not rising
        if not sma_info.get("sma_20_rising") and sma_info.get("all_rising") is False:
            score = max(0.0, score - sma_cfg.get("sma20_penalty", 0.5))

        return clamp_score(score, sma_cfg.get("max", 2.5))

    def _score_trend_stability(self, stability_info: Dict[str, Any]) -> float:
        """
        Score trend stability (0 – 2.0, +0.5 bonus).

        0 closes below SMA 50: 2.0
        1-2 closes: 1.5
        3-5 closes: 0.5
        Golden Cross 120+ days ago: +0.5 bonus
        """
        ts_cfg = _cfg.get_section("trend_continuation.trend_stability_scoring")
        closes_below = stability_info.get("closes_below_sma50", 0)

        if closes_below == 0:
            score = ts_cfg.get("zero_closes_below", 2.0)
        elif closes_below <= 2:
            score = ts_cfg.get("few_closes_below", 1.5)
        else:
            score = ts_cfg.get("many_closes_below", 0.5)

        # Golden Cross bonus
        golden_cross_days = stability_info.get("golden_cross_days", 0)
        if golden_cross_days >= ts_cfg.get("golden_cross_days", 120):
            score += ts_cfg.get("golden_cross_bonus", 0.5)

        return min(ts_cfg.get("max", 2.5), score)

    def _score_trend_buffer(self, buffer_to_sma50_pct: float) -> float:
        """
        Score trend buffer — distance from close to SMA 50 (0 – 2.0).

        > 10%: 2.0
        8-10%: 1.5
        5-8%: 1.0
        3-5%: 0.5
        """
        buf_cfg = _cfg.get_section("trend_continuation.buffer_scoring")
        if buffer_to_sma50_pct > buf_cfg.get("tier1_pct", 10.0):
            return buf_cfg.get("tier1_score", 2.0)
        elif buffer_to_sma50_pct > buf_cfg.get("tier2_pct", 8.0):
            return buf_cfg.get("tier2_score", 1.5)
        elif buffer_to_sma50_pct > buf_cfg.get("tier3_pct", 5.0):
            return buf_cfg.get("tier3_score", 1.0)
        elif buffer_to_sma50_pct >= buf_cfg.get("tier4_pct", 3.0):
            return buf_cfg.get("tier4_score", 0.5)
        return 0.0

    def _score_momentum_health(
        self,
        rsi: Optional[float],
        adx: Optional[float],
        macd_info: Optional[Dict[str, Any]],
        volume_divergence: bool,
    ) -> float:
        """
        Score momentum health (0 – 2.0, penalties possible).

        RSI 50-65: +0.5, RSI 65-75: +0.5
        MACD above signal: +0.5
        ADX > 25: +0.5, ADX > 35: +1.0 (replaces +0.5)

        Penalties:
        RSI > 75: -0.5
        MACD divergence (price up, MACD down): -1.0
        Volume divergence: -0.5
        """
        m_cfg = _cfg.get_section("trend_continuation.momentum_scoring")
        score = 0.0

        # RSI
        if rsi is not None:
            rsi_low = m_cfg.get("rsi_low", 50.0)
            rsi_mid = m_cfg.get("rsi_mid", 65.0)
            rsi_high = m_cfg.get("rsi_high", 75.0)
            if rsi_low <= rsi <= rsi_mid:
                score += m_cfg.get("rsi_bonus", 0.5)
            elif rsi_mid < rsi <= rsi_high:
                score += m_cfg.get("rsi_bonus", 0.5)
            if rsi > rsi_high:
                score += m_cfg.get("rsi_penalty", -0.5)

        # MACD
        if macd_info:
            if macd_info.get("bullish"):
                score += m_cfg.get("macd_bullish_bonus", 0.5)
            if macd_info.get("divergence"):
                score += m_cfg.get("macd_divergence_penalty", -1.0)

        # ADX
        if adx is not None:
            if adx > m_cfg.get("adx_strong", 35.0):
                score += m_cfg.get("adx_strong_bonus", 1.0)
            elif adx > m_cfg.get("adx_moderate", 25.0):
                score += m_cfg.get("adx_moderate_bonus", 0.5)

        # Volume divergence
        if volume_divergence:
            score += m_cfg.get("volume_divergence_penalty", -0.5)

        return clamp_score(score, m_cfg.get("score_max", 2.0), m_cfg.get("score_min", -1.0))

    def _score_volatility(self, atr_pct: Optional[float]) -> float:
        """
        Score volatility suitability (0 – 1.5).

        ATR% < 1.0%: 1.5
        ATR% 1.0-1.5%: 1.0
        ATR% 1.5-2.0%: 0.5
        ATR% > 2.0%: 0.0
        """
        v_cfg = _cfg.get_section("trend_continuation.volatility_scoring")
        if atr_pct is None:
            return v_cfg.get("score_unknown", 0.5)

        if atr_pct < v_cfg.get("atr_low", 1.0):
            return v_cfg.get("score_low", 1.5)
        elif atr_pct < v_cfg.get("atr_mid", 1.5):
            return v_cfg.get("score_mid", 1.0)
        elif atr_pct < v_cfg.get("atr_high", 2.0):
            return v_cfg.get("score_high", 0.5)
        return 0.0

    # =========================================================================
    # VIX REGIME
    # =========================================================================

    def _get_vix_regime(self, vix: Optional[float]) -> str:
        """Determine VIX regime from VIX value."""
        if vix is None:
            return "normal"
        if vix > self.config.vix_max:
            return "high"
        elif vix > VIX_NORMAL_MAX:
            return "elevated"
        elif vix < VIX_LOW_VOL_MAX:
            return "low"
        return "normal"

    def _get_vix_adjustment(self, regime: str) -> float:
        """Get score multiplier for VIX regime."""
        vix_cfg = _cfg.get_section("trend_continuation.vix_adjustment")
        adjustments = {
            "low": vix_cfg.get("low", 1.05),
            "normal": vix_cfg.get("normal", 1.00),
            "elevated": vix_cfg.get("elevated", 0.90),
            "high": vix_cfg.get("high", 0.0),
        }
        return adjustments.get(regime, 1.0)

    # =========================================================================
    # SIGNAL TEXT
    # =========================================================================

    def _build_signal_text(
        self,
        sma_desc: str,
        stability_desc: str,
        buffer_sma50: float,
        buffer_sma200: float,
        rsi: Optional[float],
        adx: Optional[float],
        macd_info: Optional[Dict[str, Any]],
        atr_pct: Optional[float],
    ) -> str:
        """
        Build pipe-separated signal text.

        Format: "Trend Continuation: [alignment] ([stability]) | Buffer Y% to SMA 50 (Z% to SMA 200) | RSI R, ADX A[, MACD status] | ATR P%"
        """
        parts = []

        # Part 1: Alignment + Stability
        parts.append(f"Trend Continuation: {sma_desc} ({stability_desc})")

        # Part 2: Buffer
        parts.append(f"Buffer {buffer_sma50:.1f}% to SMA 50 ({buffer_sma200:.1f}% to SMA 200)")

        # Part 3: Momentum
        momentum_parts = []
        if rsi is not None:
            momentum_parts.append(f"RSI {rsi:.0f}")
        if adx is not None:
            if adx > 35:
                momentum_parts.append(f"ADX {adx:.0f} strong trend")
            else:
                momentum_parts.append(f"ADX {adx:.0f}")
        if macd_info and macd_info.get("bullish"):
            momentum_parts.append("MACD bullish")
        if momentum_parts:
            parts.append(", ".join(momentum_parts))

        # Part 4: Volatility
        if atr_pct is not None:
            vol_label = ""
            if atr_pct < 1.0:
                vol_label = " — very low vol"
            elif atr_pct > 2.0:
                vol_label = " — elevated vol"
            parts.append(f"ATR {atr_pct:.1f}%{vol_label}")

        return " | ".join(parts)

    # =========================================================================
    # INDICATOR CALCULATIONS
    # =========================================================================

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Calculate Wilder's smoothed RSI."""
        if len(prices) < period + 1:
            return None

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # Initial average
        gains = [max(d, 0) for d in deltas[:period]]
        losses = [abs(min(d, 0)) for d in deltas[:period]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        # Wilder's smoothing
        for i in range(period, len(deltas)):
            d = deltas[i]
            avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
            avg_loss = (avg_loss * (period - 1) + abs(min(d, 0))) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_adx(
        self,
        highs: List[float],
        lows: List[float],
        prices: List[float],
        period: int = 14,
    ) -> Optional[float]:
        """Calculate Average Directional Index (ADX)."""
        n = len(prices)
        if n < period * 2 + 1:
            return None

        # True Range, +DM, -DM
        tr_list = []
        plus_dm_list = []
        minus_dm_list = []

        for i in range(1, n):
            high_diff = highs[i] - highs[i - 1]
            low_diff = lows[i - 1] - lows[i]
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - prices[i - 1]),
                abs(lows[i] - prices[i - 1]),
            )
            tr_list.append(tr)

            plus_dm = high_diff if high_diff > low_diff and high_diff > 0 else 0
            minus_dm = low_diff if low_diff > high_diff and low_diff > 0 else 0
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        if len(tr_list) < period * 2:
            return None

        # Smoothed averages (Wilder)
        atr = sum(tr_list[:period]) / period
        plus_di_smooth = sum(plus_dm_list[:period]) / period
        minus_di_smooth = sum(minus_dm_list[:period]) / period

        dx_list = []

        for i in range(period, len(tr_list)):
            atr = (atr * (period - 1) + tr_list[i]) / period
            plus_di_smooth = (plus_di_smooth * (period - 1) + plus_dm_list[i]) / period
            minus_di_smooth = (minus_di_smooth * (period - 1) + minus_dm_list[i]) / period

            if atr == 0:
                continue

            plus_di = (plus_di_smooth / atr) * 100
            minus_di = (minus_di_smooth / atr) * 100

            di_sum = plus_di + minus_di
            if di_sum == 0:
                dx_list.append(0)
            else:
                dx = abs(plus_di - minus_di) / di_sum * 100
                dx_list.append(dx)

        if len(dx_list) < period:
            return None

        # ADX = smoothed average of DX
        adx = sum(dx_list[:period]) / period
        for i in range(period, len(dx_list)):
            adx = (adx * (period - 1) + dx_list[i]) / period

        return adx

    def _calculate_atr_pct(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        period: int = 14,
    ) -> Optional[float]:
        """Calculate ATR as percentage of current price."""
        if len(prices) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(prices)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - prices[i - 1]),
                abs(lows[i] - prices[i - 1]),
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        # Wilder smoothing (matches ADX calculation)
        atr = sum(true_ranges[:period]) / period
        for tr in true_ranges[period:]:
            atr = (atr * (period - 1) + tr) / period
        current_price = prices[-1]

        if current_price <= 0:
            return None

        return (atr / current_price) * 100

    def _calculate_macd_info(
        self, prices: List[float], context: Optional[AnalysisContext] = None
    ) -> Optional[Dict[str, Any]]:
        """Calculate MACD and determine status."""
        if len(prices) < 35:  # Need at least 26 + 9
            return None

        # Build full EMA-12 and EMA-26 arrays efficiently (once)
        ema_12_series = self._calculate_ema_series(prices, 12)
        ema_26_series = self._calculate_ema_series(prices, 26)

        if ema_12_series is None or ema_26_series is None:
            return None

        # MACD line = EMA(12) - EMA(26), aligned to EMA-26 start
        offset = 26 - 12  # EMA-26 starts later
        macd_values = [
            ema_12_series[i + offset] - ema_26_series[i]
            for i in range(len(ema_26_series))
        ]

        macd_line = macd_values[-1]

        if len(macd_values) < 9:
            return {"bullish": macd_line > 0, "divergence": False}

        # Signal line = EMA(9) of MACD values
        multiplier = 2.0 / (9 + 1)
        signal = sum(macd_values[:9]) / 9
        for val in macd_values[9:]:
            signal = (val - signal) * multiplier + signal
        signal_line = signal

        # Use context MACD for bullish check if available (more accurate)
        if context is not None and context.macd_line is not None and context.macd_signal is not None:
            bullish = context.macd_line > context.macd_signal
        else:
            bullish = macd_line > signal_line

        # Check divergence: price up but MACD down over last 20 days
        divergence = False
        if len(macd_values) >= 20 and len(prices) >= 20:
            price_up = prices[-1] > prices[-20]
            macd_down = macd_values[-1] < macd_values[-20]
            divergence = price_up and macd_down

        return {
            "bullish": bullish,
            "macd_line": macd_line,
            "signal_line": signal_line,
            "divergence": divergence,
        }

    def _calculate_ema_series(self, prices: List[float], period: int) -> Optional[List[float]]:
        """Calculate full EMA series (all values from period onward)."""
        if len(prices) < period:
            return None

        multiplier = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        result = [ema]

        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
            result.append(ema)

        return result

    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Exponential Moving Average (final value)."""
        if len(prices) < period:
            return None

        multiplier = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def _check_volume_divergence(self, prices: List[float], volumes: List[int]) -> bool:
        """
        Check if price is rising but volume is declining (distribution).

        Looks at 20-day trend: if price is up but average volume in last 10 days
        is less than average volume in the 10 days before that.
        """
        if len(prices) < 20 or len(volumes) < 20:
            return False

        price_up = prices[-1] > prices[-20]
        recent_vol = sum(volumes[-10:]) / 10
        earlier_vol = sum(volumes[-20:-10]) / 10

        if earlier_vol == 0:
            return False

        vol_declining = recent_vol < earlier_vol * 0.85  # 15% decline threshold

        return price_up and vol_declining

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _make_disqualified_signal(
        self,
        symbol: str,
        current_price: float,
        reason: str,
    ) -> TradeSignal:
        """Create NEUTRAL signal for disqualified candidate."""
        return self.create_neutral_signal(symbol, current_price, reason)
