# OptionPlay - Bounce Analyzer (Refactored v2)
# ==============================================
# Analyzes bounces from established support levels
#
# Strategy: Buy when stock bounces off support that has held 2+ times
# - Requires confirmed bounce (not just proximity to support)
# - Dead Cat Bounce filter via volume
# - Trend context via SMA 200 direction
#
# 5-Component Scoring (max 10.0):
#   1. Support Quality    (0 – 2.5)
#   2. Proximity          (0 – 2.0)
#   3. Bounce Confirmation(0 – 2.5)
#   4. Volume             (-1.0 – 1.5)
#   5. Trend Context      (-2.0 – 1.5)
#
# Minimum for signal: 3.5

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Import central constants
from ..constants import (
    BOUNCE_MIN_TOUCHES,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    RSI_PERIOD,
    SMA_LONG,
    SMA_MEDIUM,
    SMA_SHORT,
    SR_LOOKBACK_DAYS_EXTENDED,
    VOLUME_AVG_PERIOD,
)

# Import shared indicators
from ..indicators.divergence import (
    check_cmf_and_macd_falling,
    check_cmf_early_warning,
    check_distribution_pattern,
    check_momentum_divergence,
    check_price_mfi_divergence,
    check_price_obv_divergence,
    check_price_rsi_divergence,
)
from ..indicators.momentum import calculate_macd
from ..indicators.support_resistance import find_support_levels as find_support_optimized
from ..indicators.support_resistance import get_nearest_sr_levels
from ..models.base import SignalStrength, SignalType, TradeSignal
from ..models.strategy_breakdowns import BounceScoreBreakdown
from .base import BaseAnalyzer
from .context import AnalysisContext

# Import Feature Scoring Mixin
from .feature_scoring_mixin import FeatureScoringMixin
from .score_normalization import clamp_score, normalize_score

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS for Bounce Strategy v2  (loaded from config/analyzer_thresholds.yaml)
# =============================================================================
from ..config.analyzer_thresholds import get_analyzer_thresholds as _get_cfg

_cfg = _get_cfg()

BOUNCE_SUPPORT_LOOKBACK = _cfg.get("bounce.general.support_lookback", 120)
BOUNCE_SUPPORT_TOLERANCE = _cfg.get("bounce.general.support_tolerance_pct", 1.0)
BOUNCE_PROXIMITY_MAX_ABOVE = _cfg.get("bounce.general.proximity_max_above_pct", 5.0)
BOUNCE_PROXIMITY_MAX_BELOW = _cfg.get("bounce.general.proximity_max_below_pct", -0.5)
BOUNCE_DCB_THRESHOLD = _cfg.get("bounce.general.dcb_threshold", 0.7)
BOUNCE_MIN_SCORE = _cfg.get("bounce.general.min_score", 3.5)
BOUNCE_MAX_SCORE = _cfg.get("bounce.general.max_score", 10.0)

# Support Quality Scoring
BOUNCE_SUPPORT_TOUCHES_STRONG = _cfg.get("bounce.support_quality.touches_strong", 5)
BOUNCE_SUPPORT_TOUCHES_MODERATE = _cfg.get("bounce.support_quality.touches_moderate", 4)
BOUNCE_SUPPORT_TOUCHES_ESTABLISHED = _cfg.get("bounce.support_quality.touches_established", 3)
BOUNCE_SUPPORT_SCORE_STRONG = _cfg.get("bounce.support_quality.score_strong", 2.0)
BOUNCE_SUPPORT_SCORE_MODERATE = _cfg.get("bounce.support_quality.score_moderate", 1.5)
BOUNCE_SUPPORT_SCORE_ESTABLISHED = _cfg.get("bounce.support_quality.score_established", 1.0)
BOUNCE_SMA200_CONFLUENCE_BONUS = _cfg.get("bounce.support_quality.sma200_confluence_bonus", 0.5)
BOUNCE_SUPPORT_QUALITY_MAX = _cfg.get("bounce.support_quality.quality_max", 2.5)

# Proximity Scoring
BOUNCE_PROXIMITY_TIER1_PCT = _cfg.get("bounce.proximity.tier1_pct", 1.0)
BOUNCE_PROXIMITY_TIER2_PCT = _cfg.get("bounce.proximity.tier2_pct", 2.0)
BOUNCE_PROXIMITY_TIER3_PCT = _cfg.get("bounce.proximity.tier3_pct", 3.0)
BOUNCE_PROXIMITY_TIER4_PCT = _cfg.get("bounce.proximity.tier4_pct", 5.0)
BOUNCE_PROXIMITY_SCORE_AT = _cfg.get("bounce.proximity.score_at", 2.0)
BOUNCE_PROXIMITY_SCORE_NEAR = _cfg.get("bounce.proximity.score_near", 1.5)
BOUNCE_PROXIMITY_SCORE_CLOSE = _cfg.get("bounce.proximity.score_close", 1.0)
BOUNCE_PROXIMITY_SCORE_FAR = _cfg.get("bounce.proximity.score_far", 0.5)
BOUNCE_PROXIMITY_SCORE_BELOW = _cfg.get("bounce.proximity.score_below", 1.0)

# Volume Scoring
BOUNCE_VOLUME_STRONG_RATIO = _cfg.get("bounce.volume.strong_ratio", 2.0)
BOUNCE_VOLUME_MODERATE_RATIO = _cfg.get("bounce.volume.moderate_ratio", 1.5)
BOUNCE_VOLUME_ADEQUATE_RATIO = _cfg.get("bounce.volume.adequate_ratio", 1.0)
BOUNCE_VOLUME_SCORE_STRONG = _cfg.get("bounce.volume.score_strong", 1.5)
BOUNCE_VOLUME_SCORE_MODERATE = _cfg.get("bounce.volume.score_moderate", 1.0)
BOUNCE_VOLUME_SCORE_ADEQUATE = _cfg.get("bounce.volume.score_adequate", 0.5)
BOUNCE_VOLUME_DCB_PENALTY = _cfg.get("bounce.volume.dcb_penalty", -1.0)

# Trend Context Scoring
BOUNCE_SMA200_RISING_MULT = _cfg.get("bounce.trend.sma200_rising_mult", 1.001)
BOUNCE_SMA200_FALLING_MULT = _cfg.get("bounce.trend.sma200_falling_mult", 0.999)
BOUNCE_SMA200_DIRECTION_LOOKBACK = _cfg.get("bounce.trend.sma200_direction_lookback", 20)
BOUNCE_SMA200_NEAR_PCT = _cfg.get("bounce.trend.sma200_near_pct", 2.0)
BOUNCE_TREND_SCORE_UPTREND = _cfg.get("bounce.trend.score_uptrend", 1.5)
BOUNCE_TREND_SCORE_ABOVE_SMA200 = _cfg.get("bounce.trend.score_above_sma200", 1.0)
BOUNCE_TREND_SCORE_NEAR_SMA200 = _cfg.get("bounce.trend.score_near_sma200", 0.5)
BOUNCE_TREND_SLOPE_STEEP = _cfg.get("bounce.trend.slope_steep", -1.0)
BOUNCE_TREND_SCORE_STEEP_DOWN = _cfg.get("bounce.trend.score_steep_down", -2.0)
BOUNCE_TREND_SLOPE_MODERATE = _cfg.get("bounce.trend.slope_moderate", -0.5)
BOUNCE_TREND_SCORE_MOD_DOWN = _cfg.get("bounce.trend.score_mod_down", -1.5)
BOUNCE_TREND_SCORE_MILD_DOWN = _cfg.get("bounce.trend.score_mild_down", -1.0)
BOUNCE_TREND_SCORE_BELOW_SMA200 = _cfg.get("bounce.trend.score_below_sma200", -0.5)

# Bounce Confirmation
BOUNCE_CONFIRM_SCORE_REVERSAL = _cfg.get("bounce.confirmation.score_reversal", 1.0)
BOUNCE_CONFIRM_SCORE_CLOSE_UP = _cfg.get("bounce.confirmation.score_close_up", 0.5)
BOUNCE_CONFIRM_SCORE_GREEN_SEQ = _cfg.get("bounce.confirmation.score_green_seq", 1.0)
BOUNCE_RSI_OVERSOLD = _cfg.get("bounce.confirmation.rsi_oversold", 40)
BOUNCE_CONFIRM_SCORE_RSI_TURN = _cfg.get("bounce.confirmation.score_rsi_turn", 0.5)
BOUNCE_CONFIRM_SCORE_MACD_CROSS = _cfg.get("bounce.confirmation.score_macd_cross", 0.5)
BOUNCE_CONFIRM_SCORE_MACD_POS = _cfg.get("bounce.confirmation.score_macd_pos", 0.25)
BOUNCE_CONFIRM_PENALTY_MOMENTUM = _cfg.get("bounce.confirmation.penalty_momentum", -0.5)
BOUNCE_CONFIRM_PENALTY_MACD = _cfg.get("bounce.confirmation.penalty_macd", -0.5)
BOUNCE_CONFIRM_MAX = _cfg.get("bounce.confirmation.confirm_max", 2.5)

# Fibonacci DCB Filter (B1)
BOUNCE_FIB_DCB_WARNING = _cfg.get("bounce.fibonacci.dcb_warning", 38.2)
BOUNCE_FIB_STRONG_THRESHOLD = _cfg.get("bounce.fibonacci.strong_threshold", 50.0)
BOUNCE_FIB_WEAK_THRESHOLD = _cfg.get("bounce.fibonacci.weak_threshold", 23.6)
BOUNCE_FIB_LOOKBACK_HIGH = _cfg.get("bounce.fibonacci.lookback_high", 30)
BOUNCE_FIB_LOOKBACK_LOW = _cfg.get("bounce.fibonacci.lookback_low", 10)
BOUNCE_FIB_STRONG_BONUS = _cfg.get("bounce.fibonacci.strong_bonus", 0.5)
BOUNCE_FIB_WEAK_PENALTY = _cfg.get("bounce.fibonacci.weak_penalty", -0.5)

# SMA Reclaim (B2)
BOUNCE_SMA_RECLAIM_20_BONUS = _cfg.get("bounce.sma_reclaim.sma20_bonus", 0.5)
BOUNCE_SMA_RECLAIM_50_BONUS = _cfg.get("bounce.sma_reclaim.sma50_bonus", 0.25)
BOUNCE_SMA_BELOW_BOTH_PENALTY = _cfg.get("bounce.sma_reclaim.below_both_penalty", -0.25)

# RSI Bullish Divergence (B3)
BOUNCE_RSI_DIV_LOOKBACK = _cfg.get("bounce.rsi_divergence.lookback", 20)
BOUNCE_RSI_DIV_THRESHOLD = _cfg.get("bounce.rsi_divergence.threshold", 2.0)
BOUNCE_RSI_DIV_BONUS = _cfg.get("bounce.rsi_divergence.bonus", 0.75)

# Downtrend Filter (B4)
BOUNCE_DOWNTREND_DISQUALIFY_PCT = _cfg.get(
    "bounce.downtrend_filter.disqualify_below_sma200_pct", 10.0
)
BOUNCE_DOWNTREND_SEVERE_PENALTY = _cfg.get("bounce.downtrend_filter.severe_penalty", -2.5)

# Market Context (B5)
BOUNCE_MARKET_CONTEXT_ENABLED = _cfg.get("bounce.market_context.enabled", False)
BOUNCE_MARKET_BEARISH_MULT = _cfg.get("bounce.market_context.bearish_multiplier", 0.8)
BOUNCE_MARKET_NEUTRAL_MULT = _cfg.get("bounce.market_context.neutral_multiplier", 0.9)
BOUNCE_SECTOR_WEAK_MULT = _cfg.get("bounce.market_context.sector_weak_multiplier", 0.9)

# Bollinger Band Confluence (B6)
BOUNCE_BB_ENABLED = _cfg.get("bounce.bollinger.enabled", False)
BOUNCE_BB_TOLERANCE_PCT = _cfg.get("bounce.bollinger.confluence_tolerance_pct", 1.0)
BOUNCE_BB_BONUS = _cfg.get("bounce.bollinger.confluence_bonus", 0.25)

# Candlestick Pattern Detection
BOUNCE_HAMMER_WICK_BODY_RATIO = _cfg.get("bounce.candlestick.hammer_wick_body_ratio", 2)
BOUNCE_HAMMER_UPPER_WICK_PCT = _cfg.get("bounce.candlestick.hammer_upper_wick_pct", 0.5)
BOUNCE_DOJI_BODY_RANGE_PCT = _cfg.get("bounce.candlestick.doji_body_range_pct", 0.1)
BOUNCE_DOJI_SUPPORT_PCT = _cfg.get("bounce.candlestick.doji_support_pct", 0.02)

# SMA Confluence
BOUNCE_SMA200_CONFLUENCE_PCT = _cfg.get("bounce.sma_confluence.sma200_pct", 0.02)

# Signal Strength
BOUNCE_SIGNAL_STRONG = _cfg.get("bounce.signal.strong", 7.0)
BOUNCE_SIGNAL_MODERATE = _cfg.get("bounce.signal.moderate", 5.0)

# DCB Filter
BOUNCE_DCB_RSI_OVERBOUGHT = _cfg.get("bounce.dcb.rsi_overbought", 70)

# RSI Momentum
BOUNCE_RSI_MOMENTUM_FADE = _cfg.get("bounce.rsi.momentum_fade", 50)

# Bearish Divergence Penalties (negative values)
BOUNCE_DIV_PENALTY_PRICE_RSI = _cfg.get("bounce.divergence.price_rsi", -2.0)
BOUNCE_DIV_PENALTY_PRICE_OBV = _cfg.get("bounce.divergence.price_obv", -1.5)
BOUNCE_DIV_PENALTY_PRICE_MFI = _cfg.get("bounce.divergence.price_mfi", -1.5)
BOUNCE_DIV_PENALTY_CMF_MACD = _cfg.get("bounce.divergence.cmf_macd_falling", -1.0)
BOUNCE_DIV_PENALTY_MOMENTUM = _cfg.get("bounce.divergence.momentum_divergence", -1.5)
BOUNCE_DIV_PENALTY_DISTRIBUTION = _cfg.get("bounce.divergence.distribution_pattern", -3.0)
BOUNCE_DIV_PENALTY_CMF_EARLY = _cfg.get("bounce.divergence.cmf_early_warning", -1.0)


@dataclass
class BounceConfig:
    """Configuration for Bounce Analyzer v2"""

    # Support Detection
    support_lookback_days: int = BOUNCE_SUPPORT_LOOKBACK
    support_touches_min: int = BOUNCE_MIN_TOUCHES  # Minimum 2x tested
    support_tolerance_pct: float = BOUNCE_SUPPORT_TOLERANCE

    # Proximity
    max_above_support_pct: float = BOUNCE_PROXIMITY_MAX_ABOVE
    max_below_support_pct: float = BOUNCE_PROXIMITY_MAX_BELOW

    # Volume
    volume_avg_period: int = VOLUME_AVG_PERIOD
    dcb_threshold: float = BOUNCE_DCB_THRESHOLD

    # RSI
    rsi_period: int = RSI_PERIOD

    # Risk Management
    stop_below_support_pct: float = 2.0
    target_risk_reward: float = 2.0

    # Scoring
    min_score_for_signal: float = BOUNCE_MIN_SCORE
    max_score: float = BOUNCE_MAX_SCORE


class BounceAnalyzer(BaseAnalyzer, FeatureScoringMixin):
    """
    Analyzes stocks for support bounces (v2 — Refactored).

    Implements a strict 4-step filter pipeline:
      1. Valid support level (>= 2 touches in 120 days)
      2. Price at or above support (max -0.5% tolerance)
      3. Bounce confirmation (at least one reversal signal)
      4. Volume check (< 0.7x avg = Dead Cat Bounce → disqualify)

    5-Component Scoring (max 10.0):
      - Support Quality:       0 – 2.5
      - Proximity:             0 – 2.0
      - Bounce Confirmation:   0 – 2.5
      - Volume:               -1.0 – 1.5
      - Trend Context:        -2.0 – 1.5

    Signal threshold: total_score >= 3.5

    Usage:
        analyzer = BounceAnalyzer()
        signal = analyzer.analyze("AAPL", prices, volumes, highs, lows)
        if signal.signal_type == SignalType.LONG:
            print(f"Bounce Signal: {signal.score}/10")
    """

    def __init__(self, config: Optional[BounceConfig] = None, **kwargs) -> None:
        # Accept scoring_config for backward compat but ignore it
        self.config = config or BounceConfig()

    @property
    def strategy_name(self) -> str:
        return "bounce"

    @property
    def description(self) -> str:
        return "Support Bounce - Buy on confirmed bounce from established support level"

    # =========================================================================
    # MAIN ANALYZE METHOD
    # =========================================================================

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
        Analyzes a symbol for support bounce.

        Pipeline:
          1. Find valid support levels (>= 2 touches)
          2. Check proximity (price at/above support)
          3. Check bounce confirmation (reversal signals)
          4. Check volume (Dead Cat Bounce filter)
          5. Score all 5 components
          6. Build signal text

        Args:
            symbol: Ticker symbol
            prices: Closing prices (oldest first)
            volumes: Daily volume
            highs: Daily highs
            lows: Daily lows
            context: Optional pre-calculated AnalysisContext

        Returns:
            TradeSignal with bounce rating (score 0-10)
        """
        min_data = self.config.support_lookback_days
        self.validate_inputs(prices, volumes, highs, lows, min_length=min_data)

        current_price = prices[-1]

        # Initialize breakdown
        breakdown = BounceScoreBreakdown()
        reasons = []
        warnings = []

        # =====================================================================
        # STEP 1: Find valid support level (PFLICHT — >= 2 touches)
        # =====================================================================
        support_info = self._find_valid_support(prices, lows, volumes, context)

        if not support_info["valid"]:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                support_info.get("disqualify_reason", "No valid support level"),
                support_info,
            )

        support_level = support_info["support_level"]
        touches = support_info["touches"]
        sma_200_confluence = support_info.get("sma_200_confluence", False)

        breakdown.support_level = support_level
        breakdown.support_touches = touches
        breakdown.support_strength = support_info["strength"]

        # =====================================================================
        # STEP 2: Proximity check — price must be AT or ABOVE support
        # =====================================================================
        distance_pct = (current_price - support_level) / support_level * 100
        breakdown.support_distance_pct = distance_pct

        if distance_pct < self.config.max_below_support_pct:
            # Support broken — price too far below
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Support broken: price ${current_price:.2f} is {distance_pct:.1f}% below support ${support_level:.2f}",
                support_info,
            )

        if distance_pct > self.config.max_above_support_pct:
            # Too far above support
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Too far from support: price ${current_price:.2f} is {distance_pct:.1f}% above support ${support_level:.2f}",
                support_info,
            )

        # =====================================================================
        # STEP 3: Bounce confirmation (PFLICHT — at least one signal)
        # =====================================================================
        confirmations = self._check_bounce_confirmation(prices, highs, lows, volumes, support_level)

        if not confirmations["confirmed"]:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Bounce not confirmed at support ${support_level:.2f} — no reversal signals",
                support_info,
            )

        # =====================================================================
        # STEP 4: Dead Cat Bounce filter (volume + momentum checks)
        # =====================================================================
        volume_info = self._check_volume(volumes)

        if volume_info["dcb_risk"] == "high":
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Dead Cat Bounce risk: volume {volume_info['ratio']:.2f}x avg (< {self.config.dcb_threshold}x)",
                support_info,
            )

        # E.4: RSI overbought after bounce — unsustainable short squeeze
        rsi_values = confirmations.get("rsi_values", [])
        if rsi_values and rsi_values[-1] > BOUNCE_DCB_RSI_OVERBOUGHT:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Dead Cat Bounce: RSI overbought ({rsi_values[-1]:.0f})",
                support_info,
            )

        # E.4: No green candle in last 2 bars — no actual bounce
        if len(prices) >= 3:
            last_red = prices[-1] < prices[-2]
            prev_red = prices[-2] < prices[-3]
            if last_red and prev_red:
                return self._make_disqualified_signal(
                    symbol,
                    current_price,
                    "Dead Cat Bounce: no green candles (2 consecutive red)",
                    support_info,
                )

        # =====================================================================
        # B4: Downtrend Filter — disqualify extreme downtrends
        # =====================================================================
        sma_200 = (
            sum(prices[-SMA_LONG:]) / SMA_LONG
            if len(prices) >= SMA_LONG
            else sum(prices) / len(prices)
        )
        distance_to_sma200 = (current_price - sma_200) / sma_200 * 100

        if distance_to_sma200 < -BOUNCE_DOWNTREND_DISQUALIFY_PCT:
            # Check if SMA 200 is also falling (steep)
            if len(prices) >= SMA_LONG + BOUNCE_SMA200_DIRECTION_LOOKBACK:
                sma_200_prev = (
                    sum(
                        prices[
                            -(
                                SMA_LONG + BOUNCE_SMA200_DIRECTION_LOOKBACK
                            ) : -BOUNCE_SMA200_DIRECTION_LOOKBACK
                        ]
                    )
                    / SMA_LONG
                )
                sma_slope_pct = (sma_200 - sma_200_prev) / sma_200_prev * 100
                if sma_slope_pct < BOUNCE_TREND_SLOPE_STEEP:
                    return self._make_disqualified_signal(
                        symbol,
                        current_price,
                        f"Strong downtrend: {distance_to_sma200:.1f}% below falling SMA 200",
                        support_info,
                    )

        # =====================================================================
        # SCORING: 5 Components
        # =====================================================================

        # 1. Support Quality (0 – 2.5)
        support_score = self._score_support_quality(touches, sma_200_confluence)

        # B6: Bollinger Band confluence bonus
        if BOUNCE_BB_ENABLED and len(prices) >= SMA_SHORT:
            bb_middle = sum(prices[-SMA_SHORT:]) / SMA_SHORT
            bb_std = float(np.std(prices[-SMA_SHORT:]))
            bb_lower = bb_middle - 2 * bb_std
            if bb_lower > 0:
                bb_distance_pct = abs(current_price - bb_lower) / bb_lower * 100
                if bb_distance_pct <= BOUNCE_BB_TOLERANCE_PCT:
                    support_score = min(support_score + BOUNCE_BB_BONUS, BOUNCE_SUPPORT_QUALITY_MAX)
                    reasons.append("BB confluence")

        breakdown.support_score = support_score
        breakdown.support_reason = f"{touches}x tested" + (
            " + SMA 200 confluence" if sma_200_confluence else ""
        )

        # 2. Proximity (0 – 2.0)
        proximity_score = self._score_proximity(distance_pct)

        # 3. Bounce Confirmation (0 – 2.5)
        confirmation_score = confirmations["score"]

        # 4. Volume (-1.0 – 1.5)
        volume_score = self._score_volume(volume_info["ratio"])
        breakdown.volume_score = volume_score
        breakdown.volume_ratio = volume_info["ratio"]
        breakdown.volume_reason = volume_info.get("reason", "")

        # 5. Trend Context (-1.0 – 1.5)
        trend_info = self._score_trend_context(prices)
        trend_score = trend_info["score"]
        breakdown.trend_score = trend_score
        breakdown.trend_status = trend_info["status"]
        breakdown.trend_reason = trend_info["reason"]

        # Total score
        total_score = (
            support_score + proximity_score + confirmation_score + volume_score + trend_score
        )

        # B5: Market context multiplier (disabled by default)
        if BOUNCE_MARKET_CONTEXT_ENABLED and context is not None:
            sector_status = getattr(context, "sector_status", None)
            if sector_status:
                market_trend = getattr(sector_status, "market_trend", None)
                if market_trend == "bearish":
                    total_score *= BOUNCE_MARKET_BEARISH_MULT
                elif market_trend == "neutral":
                    total_score *= BOUNCE_MARKET_NEUTRAL_MULT
                sector_rs = getattr(sector_status, "sector_rs", None)
                if sector_rs is not None and sector_rs < 0:
                    total_score *= BOUNCE_SECTOR_WEAK_MULT

        # Bearish divergence penalties (applied before clamping)
        total_score = self._apply_divergence_penalties(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            score=total_score,
        )

        # Earnings-surprise modifier (additive, after divergence penalties)
        from ..services.earnings_quality import get_earnings_surprise_modifier  # noqa: PLC0415

        total_score += get_earnings_surprise_modifier(symbol)

        total_score = clamp_score(total_score, BOUNCE_MAX_SCORE)
        breakdown.total_score = round(total_score, 1)
        breakdown.max_possible = BOUNCE_MAX_SCORE

        # =====================================================================
        # BUILD SIGNAL
        # =====================================================================
        signal_text = self._build_signal_text(
            support_level,
            touches,
            sma_200_confluence,
            confirmations,
            volume_info,
            trend_info,
            distance_pct,
        )

        # Signal strength (compared on native scale before normalization)
        if total_score >= BOUNCE_SIGNAL_STRONG:
            strength = SignalStrength.STRONG
        elif total_score >= BOUNCE_SIGNAL_MODERATE:
            strength = SignalStrength.MODERATE
        elif total_score >= BOUNCE_MIN_SCORE:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE

        is_actionable = total_score >= BOUNCE_MIN_SCORE

        # Normalize to 0-10 scale for fair cross-strategy comparison
        normalized_score = normalize_score(total_score, "bounce")

        # Entry/Stop/Target
        entry_price = current_price
        stop_loss = support_level * (1 - self.config.stop_below_support_pct / 100)
        target_price = entry_price + (entry_price - stop_loss) * self.config.target_risk_reward

        # Extended S/R for context
        sr_levels = get_nearest_sr_levels(
            current_price=current_price,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            lookback=SR_LOOKBACK_DAYS_EXTENDED,
            num_levels=3,
        )

        # Warnings
        if trend_score < 0:
            warnings.append("Downtrend context — higher risk")
        if volume_info["ratio"] < 1.0:
            warnings.append(f"Below-average volume ({volume_info['ratio']:.1f}x)")

        # Store component scores in breakdown for compatibility
        breakdown.rsi_score = 0
        breakdown.rsi_value = confirmations.get("rsi_value", 50.0)
        breakdown.rsi_reason = f"RSI={breakdown.rsi_value:.1f}"
        breakdown.candlestick_score = 0
        breakdown.candlestick_pattern = confirmations.get("candle_pattern")
        breakdown.candlestick_bullish = confirmations.get("candle_pattern") is not None
        breakdown.candlestick_reason = f"Pattern: {breakdown.candlestick_pattern or 'None'}"

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.LONG if is_actionable else SignalType.NEUTRAL,
            strength=strength,
            score=round(normalized_score, 1),
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=signal_text,
            details={
                "score_breakdown": breakdown.to_dict(),
                "raw_score": total_score,
                "max_possible": BOUNCE_MAX_SCORE,
                "support_levels": [support_level],
                "support_info": support_info,
                "trend_info": trend_info,
                "rsi": confirmations.get("rsi_value", 50.0),
                "candle_info": {
                    "pattern": confirmations.get("candle_pattern"),
                    "bullish": confirmations.get("candle_pattern") is not None,
                },
                "sr_levels": sr_levels,
                "confirmations": confirmations["signals"],
                "volume_ratio": volume_info["ratio"],
                "distance_pct": distance_pct,
                "components": {
                    "support_quality": support_score,
                    "proximity": proximity_score,
                    "bounce_confirmation": confirmation_score,
                    "volume": volume_score,
                    "trend_context": trend_score,
                },
            },
            warnings=warnings,
        )

    # =========================================================================
    # STEP 1: SUPPORT LEVEL DETECTION
    # =========================================================================

    def _find_valid_support(
        self,
        prices: List[float],
        lows: List[float],
        volumes: List[int],
        context: Optional[AnalysisContext] = None,
    ) -> Dict[str, Any]:
        """
        Find the nearest valid support level with >= min touches.

        Uses pivot-low detection with clustering. A valid support needs
        at least 2 touches within tolerance_pct.

        Returns dict with:
            valid: bool
            support_level: float or None
            touches: int
            strength: str
            sma_200_confluence: bool
            disqualify_reason: str (if not valid)
        """
        current_price = prices[-1]
        lookback = self.config.support_lookback_days
        tolerance = self.config.support_tolerance_pct / 100

        # Get support levels from context or calculate
        if context and context.support_levels:
            raw_levels = context.support_levels
        else:
            raw_levels = find_support_optimized(
                lows=lows,
                lookback=lookback,
                window=5,
                max_levels=10,
                volumes=volumes if volumes else None,
                tolerance_pct=self.config.support_tolerance_pct,
            )

        if not raw_levels:
            return {
                "valid": False,
                "support_level": None,
                "touches": 0,
                "strength": "none",
                "sma_200_confluence": False,
                "disqualify_reason": "No support levels found",
            }

        # Find nearest support BELOW or AT current price (with tolerance)
        # We want supports that are below current price (support must be below)
        candidates = []
        for level in raw_levels:
            dist_pct = (current_price - level) / level * 100
            # Accept levels below price and up to 0.5% above (wick tolerance)
            if dist_pct >= self.config.max_below_support_pct:
                touches = self._count_support_touches(lows, level, tolerance, lookback)
                candidates.append((level, touches, dist_pct))

        if not candidates:
            nearest = min(raw_levels, key=lambda s: abs(current_price - s))
            return {
                "valid": False,
                "support_level": nearest,
                "touches": 0,
                "strength": "none",
                "sma_200_confluence": False,
                "disqualify_reason": f"No support below current price ${current_price:.2f}",
            }

        # Pick the nearest valid support (closest to current price)
        # Filter for min touches first
        valid_candidates = [
            (l, t, d) for l, t, d in candidates if t >= self.config.support_touches_min
        ]

        if not valid_candidates:
            best = min(candidates, key=lambda x: x[2])
            return {
                "valid": False,
                "support_level": best[0],
                "touches": best[1],
                "strength": "weak",
                "sma_200_confluence": False,
                "disqualify_reason": f"Support at ${best[0]:.2f} has only {best[1]} touch(es), need >= {self.config.support_touches_min}",
            }

        # Pick closest valid support
        best = min(valid_candidates, key=lambda x: x[2])
        level, touches, dist_pct = best

        # Strength classification
        if touches >= BOUNCE_SUPPORT_TOUCHES_STRONG:
            strength = "strong"
        elif touches >= BOUNCE_SUPPORT_TOUCHES_MODERATE:
            strength = "moderate"
        else:
            strength = "established"

        # SMA 200 confluence check
        sma_200 = (
            sum(prices[-SMA_LONG:]) / SMA_LONG
            if len(prices) >= SMA_LONG
            else sum(prices) / len(prices)
        )
        sma_200_confluence = abs(level - sma_200) / sma_200 <= BOUNCE_SMA200_CONFLUENCE_PCT

        return {
            "valid": True,
            "support_level": level,
            "touches": touches,
            "strength": strength,
            "sma_200_confluence": sma_200_confluence,
            "sma_200": sma_200,
            "distance_pct": dist_pct,
        }

    def _count_support_touches(
        self,
        lows: List[float],
        support_level: float,
        tolerance: float,
        lookback: int = 120,
    ) -> int:
        """Count how many times price touched this support level."""
        touches = 0
        n = len(lows)
        start = max(0, n - lookback)

        # Group consecutive touches as one touch
        in_touch = False
        for i in range(start, n):
            low = lows[i]
            if abs(low - support_level) / support_level <= tolerance:
                if not in_touch:
                    touches += 1
                    in_touch = True
            else:
                in_touch = False

        return touches

    # =========================================================================
    # STEP 3: BOUNCE CONFIRMATION
    # =========================================================================

    def _check_bounce_confirmation(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[int],
        support_level: float,
    ) -> Dict[str, Any]:
        """
        Check if a bounce at support is confirmed.

        At least ONE of these signals must be present:
          1. Reversal Candlestick (Hammer, Bullish Engulfing, Doji)
          2. Price Action: close[-1] > close[-2]
          3. Green Sequence: 2+ green days after support test
          4. RSI turning up: RSI < 40 AND RSI today > RSI yesterday
          5. MACD histogram turning positive

        Returns dict with:
            confirmed: bool
            signals: list[str]
            score: float (0-2.5)
            candle_pattern: str or None
            rsi_value: float
        """
        signals = []
        score = 0.0
        candle_pattern = None
        rsi_value = 50.0

        if len(prices) < 3:
            return {
                "confirmed": False,
                "signals": [],
                "score": 0,
                "candle_pattern": None,
                "rsi_value": 50.0,
            }

        # --- 1. Reversal Candlestick ---
        candle = self._detect_reversal_candle(prices, highs, lows, support_level)
        if candle:
            signals.append(candle)
            candle_pattern = candle
            score += BOUNCE_CONFIRM_SCORE_REVERSAL

        # --- 2. Price Action: close > prev close ---
        if prices[-1] > prices[-2]:
            signals.append("Close > prev close")
            score += BOUNCE_CONFIRM_SCORE_CLOSE_UP

        # --- 3. Green Sequence: 2+ consecutive green days ---
        if len(prices) >= 3:
            # Approximate open as previous close
            green_today = prices[-1] > prices[-2]
            green_yesterday = prices[-2] > prices[-3]
            if green_today and green_yesterday:
                signals.append("2 green days")
                score += BOUNCE_CONFIRM_SCORE_GREEN_SEQ

        # --- 4. RSI < BOUNCE_RSI_OVERSOLD AND turning up ---
        rsi_values = self._calculate_rsi(prices)
        if len(rsi_values) >= 2:
            rsi_value = rsi_values[-1]
            if rsi_value < BOUNCE_RSI_OVERSOLD and rsi_values[-1] > rsi_values[-2]:
                signals.append(f"RSI oversold turning up ({rsi_value:.0f})")
                score += BOUNCE_CONFIRM_SCORE_RSI_TURN

        # --- 5. MACD histogram turning positive ---
        macd_result = calculate_macd(
            prices, fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
        )
        if macd_result:
            if macd_result.crossover == "bullish":
                signals.append("MACD bullish cross")
                score += BOUNCE_CONFIRM_SCORE_MACD_CROSS
            elif macd_result.histogram > 0:
                signals.append("MACD positive")
                score += BOUNCE_CONFIRM_SCORE_MACD_POS

        # --- B1: Fibonacci Retracement DCB filter ---
        if len(prices) >= BOUNCE_FIB_LOOKBACK_HIGH + 5:
            # Find swing high (before the pullback) and swing low (recent)
            swing_high = max(prices[-(BOUNCE_FIB_LOOKBACK_HIGH + 5) : -5])
            swing_low = min(prices[-BOUNCE_FIB_LOOKBACK_LOW:])
            decline = swing_high - swing_low

            if decline > 0:
                retracement_pct = (prices[-1] - swing_low) / decline * 100
                if retracement_pct > BOUNCE_FIB_STRONG_THRESHOLD:
                    signals.append(f"Fib retracement {retracement_pct:.0f}% (strong)")
                    score += BOUNCE_FIB_STRONG_BONUS
                elif retracement_pct < BOUNCE_FIB_WEAK_THRESHOLD:
                    signals.append(f"Fib retracement {retracement_pct:.0f}% (weak — DCB risk)")
                    score += BOUNCE_FIB_WEAK_PENALTY

        # --- B2: SMA 20/50 Reclaim check ---
        if len(prices) >= SMA_MEDIUM:
            sma_20 = sum(prices[-SMA_SHORT:]) / SMA_SHORT if len(prices) >= SMA_SHORT else None
            sma_50 = sum(prices[-SMA_MEDIUM:]) / SMA_MEDIUM

            current = prices[-1]
            if sma_20 is not None and current > sma_20:
                signals.append("Close > SMA 20")
                score += BOUNCE_SMA_RECLAIM_20_BONUS
                if current > sma_50:
                    signals.append("Close > SMA 50")
                    score += BOUNCE_SMA_RECLAIM_50_BONUS
            elif sma_20 is not None and current < sma_20 and current < sma_50:
                signals.append("Below SMA 20 & 50")
                score += BOUNCE_SMA_BELOW_BOTH_PENALTY

        # --- B3: RSI Bullish Divergence ---
        if len(rsi_values) >= BOUNCE_RSI_DIV_LOOKBACK and len(prices) >= BOUNCE_RSI_DIV_LOOKBACK:
            mid = BOUNCE_RSI_DIV_LOOKBACK // 2
            # Price: compare lows in two halves
            price_low_1 = min(prices[-BOUNCE_RSI_DIV_LOOKBACK:-mid])
            price_low_2 = min(prices[-mid:])
            # Find RSI at those price low points
            idx_low_1 = prices[-BOUNCE_RSI_DIV_LOOKBACK:-mid].index(price_low_1)
            idx_low_2 = prices[-mid:].index(price_low_2)
            rsi_at_low_1 = rsi_values[-(BOUNCE_RSI_DIV_LOOKBACK - idx_low_1)]
            rsi_at_low_2 = rsi_values[-(mid - idx_low_2)]

            # Bullish divergence: price equal/lower low, RSI higher low
            if (
                price_low_2 <= price_low_1 * 1.01
                and rsi_at_low_2 > rsi_at_low_1 + BOUNCE_RSI_DIV_THRESHOLD
            ):
                signals.append(
                    f"RSI bullish divergence (price low ≈ RSI {rsi_at_low_2:.0f} > {rsi_at_low_1:.0f})"
                )
                score += BOUNCE_RSI_DIV_BONUS

        # --- E.1: Momentum penalty (bearish momentum reduces score) ---
        # RSI falling above BOUNCE_RSI_MOMENTUM_FADE = momentum fading, not oversold
        if len(rsi_values) >= 2:
            if rsi_values[-1] > BOUNCE_RSI_MOMENTUM_FADE and rsi_values[-1] < rsi_values[-2]:
                signals.append(f"Momentum fading (RSI {rsi_values[-1]:.0f} falling)")
                score += BOUNCE_CONFIRM_PENALTY_MOMENTUM

        # MACD histogram increasingly negative = declining momentum
        if macd_result and macd_result.histogram < 0:
            # Calculate previous histogram from prices[:-1]
            prev_macd = calculate_macd(
                prices[:-1], fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
            )
            if prev_macd is not None and macd_result.histogram < prev_macd.histogram:
                signals.append("MACD momentum declining")
                score += BOUNCE_CONFIRM_PENALTY_MACD

        # Floor at 0.0, cap at BOUNCE_CONFIRM_MAX
        score = clamp_score(score, BOUNCE_CONFIRM_MAX)

        return {
            "confirmed": len(signals) > 0,
            "signals": signals,
            "score": score,
            "candle_pattern": candle_pattern,
            "rsi_value": rsi_value,
            "rsi_values": rsi_values,
        }

    def _detect_reversal_candle(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        support_level: float,
    ) -> Optional[str]:
        """Detect reversal candlestick patterns near support."""
        if len(prices) < 3:
            return None

        # Use previous close as approximation for open
        open_price = prices[-2]
        close = prices[-1]
        high = highs[-1]
        low = lows[-1]

        body = close - open_price
        body_size = abs(body)
        lower_wick = min(open_price, close) - low
        upper_wick = high - max(open_price, close)
        total_range = high - low

        # Hammer: small body at top, long lower wick (>= 2x body)
        if (
            body_size > 0
            and lower_wick >= body_size * BOUNCE_HAMMER_WICK_BODY_RATIO
            and upper_wick < body_size * BOUNCE_HAMMER_UPPER_WICK_PCT
        ):
            return "Hammer"

        # Bullish Engulfing: red day followed by larger green day
        if len(prices) >= 3:
            prev_body = prices[-2] - prices[-3]
            if prev_body < 0 and body > 0 and body > abs(prev_body):
                return "Bullish Engulfing"

        # Doji at support: very small body relative to range
        if total_range > 0 and body_size / total_range < BOUNCE_DOJI_BODY_RANGE_PCT:
            # Only count if low is near support
            if (
                support_level > 0
                and abs(low - support_level) / support_level <= BOUNCE_DOJI_SUPPORT_PCT
            ):
                return "Doji"

        return None

    # =========================================================================
    # STEP 4: VOLUME CHECK
    # =========================================================================

    def _check_volume(self, volumes: List[int]) -> Dict[str, Any]:
        """
        Check bounce volume relative to 20-day average.

        Returns:
            ratio: float (bounce vol / avg vol)
            dcb_risk: 'low' | 'medium' | 'high'
            reason: str
        """
        avg_period = self.config.volume_avg_period

        if len(volumes) < avg_period + 1:
            return {"ratio": 1.0, "dcb_risk": "low", "reason": "Insufficient volume data"}

        avg_volume = sum(volumes[-avg_period - 1 : -1]) / avg_period
        bounce_volume = volumes[-1]

        # Weekend/holiday fallback: use last non-zero volume
        if bounce_volume == 0 and len(volumes) >= 2:
            for v in reversed(volumes[:-1]):
                if v > 0:
                    bounce_volume = v
                    break

        ratio = bounce_volume / avg_volume if avg_volume > 0 else 0

        if ratio < self.config.dcb_threshold:
            return {
                "ratio": ratio,
                "dcb_risk": "high",
                "reason": f"Dead Cat Bounce risk: vol {ratio:.2f}x avg",
            }
        elif ratio < 1.0:
            return {
                "ratio": ratio,
                "dcb_risk": "medium",
                "reason": f"Below-average volume: {ratio:.2f}x",
            }
        else:
            return {
                "ratio": ratio,
                "dcb_risk": "low",
                "reason": f"Volume confirms: {ratio:.2f}x avg",
            }

    # =========================================================================
    # SCORING COMPONENTS
    # =========================================================================

    def _score_support_quality(self, touches: int, sma_200_confluence: bool) -> float:
        """
        Score support quality (0 – 2.5).

        2 touches = 1.0, 3 = 1.5, 4+ = 2.0
        SMA 200 confluence = +0.5 bonus
        """
        if touches >= BOUNCE_SUPPORT_TOUCHES_STRONG:
            score = BOUNCE_SUPPORT_SCORE_STRONG
        elif touches >= BOUNCE_SUPPORT_TOUCHES_MODERATE:
            score = BOUNCE_SUPPORT_SCORE_MODERATE
        elif touches >= BOUNCE_SUPPORT_TOUCHES_ESTABLISHED:
            score = BOUNCE_SUPPORT_SCORE_ESTABLISHED
        else:
            score = 0.0

        if sma_200_confluence:
            score += BOUNCE_SMA200_CONFLUENCE_BONUS

        return clamp_score(score, BOUNCE_SUPPORT_QUALITY_MAX)

    def _score_proximity(self, distance_pct: float) -> float:
        """
        Score proximity to support (0 – 2.0).

        0% to +1%:   2.0 (directly at support)
        +1% to +2%:  1.5
        +2% to +3%:  1.0
        +3% to +5%:  0.5
        -0.5% to 0%: 1.0 (slightly below, wick tolerance)
        """
        if distance_pct < 0:
            # Below support (within tolerance)
            return BOUNCE_PROXIMITY_SCORE_BELOW
        elif distance_pct <= BOUNCE_PROXIMITY_TIER1_PCT:
            return BOUNCE_PROXIMITY_SCORE_AT
        elif distance_pct <= BOUNCE_PROXIMITY_TIER2_PCT:
            return BOUNCE_PROXIMITY_SCORE_NEAR
        elif distance_pct <= BOUNCE_PROXIMITY_TIER3_PCT:
            return BOUNCE_PROXIMITY_SCORE_CLOSE
        elif distance_pct <= BOUNCE_PROXIMITY_TIER4_PCT:
            return BOUNCE_PROXIMITY_SCORE_FAR
        else:
            return 0.0

    def _score_volume(self, ratio: float) -> float:
        """
        Score volume confirmation (-1.0 – 1.5).

        > 2.0x:  1.5
        > 1.5x:  1.0
        > 1.0x:  0.5
        < 1.0x:  0.0
        < 0.7x: -1.0 (penalty — Dead Cat Bounce)
        """
        if ratio >= BOUNCE_VOLUME_STRONG_RATIO:
            return BOUNCE_VOLUME_SCORE_STRONG
        elif ratio >= BOUNCE_VOLUME_MODERATE_RATIO:
            return BOUNCE_VOLUME_SCORE_MODERATE
        elif ratio >= BOUNCE_VOLUME_ADEQUATE_RATIO:
            return BOUNCE_VOLUME_SCORE_ADEQUATE
        elif ratio >= self.config.dcb_threshold:
            return 0.0
        else:
            return BOUNCE_VOLUME_DCB_PENALTY

    def _score_trend_context(self, prices: List[float]) -> Dict[str, Any]:
        """
        Score trend context (-2.0 – 1.5).

        Price above SMA 200, SMA 200 rising:  1.5 (uptrend)
        Price above SMA 200, SMA 200 flat:    1.0
        Price near SMA 200 (±2%):             0.5
        Price below SMA 200, SMA 200 falling:
          - Steep decline (slope < -1%):      -2.0
          - Moderate decline (-1% to -0.5%):  -1.5
          - Mild decline (> -0.5%):           -1.0
        """
        sma_200 = (
            sum(prices[-SMA_LONG:]) / SMA_LONG
            if len(prices) >= SMA_LONG
            else sum(prices) / len(prices)
        )
        current = prices[-1]

        # SMA 200 direction (compare current SMA vs BOUNCE_SMA200_DIRECTION_LOOKBACK days ago)
        if len(prices) >= SMA_LONG + BOUNCE_SMA200_DIRECTION_LOOKBACK:
            sma_200_prev = (
                sum(
                    prices[
                        -(
                            SMA_LONG + BOUNCE_SMA200_DIRECTION_LOOKBACK
                        ) : -BOUNCE_SMA200_DIRECTION_LOOKBACK
                    ]
                )
                / SMA_LONG
            )
            sma_direction = (
                "rising"
                if sma_200 > sma_200_prev * BOUNCE_SMA200_RISING_MULT
                else ("falling" if sma_200 < sma_200_prev * BOUNCE_SMA200_FALLING_MULT else "flat")
            )
        else:
            sma_direction = "flat"

        distance_to_sma = (current - sma_200) / sma_200 * 100

        if current > sma_200:
            if sma_direction == "rising":
                return {
                    "score": BOUNCE_TREND_SCORE_UPTREND,
                    "status": "uptrend",
                    "reason": "Uptrend: above rising SMA 200",
                    "sma_200": sma_200,
                }
            else:
                return {
                    "score": BOUNCE_TREND_SCORE_ABOVE_SMA200,
                    "status": "above_sma200",
                    "reason": f"Above SMA 200 (SMA {sma_direction})",
                    "sma_200": sma_200,
                }
        elif abs(distance_to_sma) <= BOUNCE_SMA200_NEAR_PCT:
            return {
                "score": BOUNCE_TREND_SCORE_NEAR_SMA200,
                "status": "near_sma200",
                "reason": f"Near SMA 200 ({distance_to_sma:+.1f}%)",
                "sma_200": sma_200,
            }
        else:
            if sma_direction == "falling":
                # E.2: Gradient penalty based on SMA200 slope steepness
                if len(prices) >= SMA_LONG + BOUNCE_SMA200_DIRECTION_LOOKBACK:
                    sma_slope_pct = (sma_200 - sma_200_prev) / sma_200_prev * 100
                else:
                    sma_slope_pct = 0.0

                if sma_slope_pct < BOUNCE_TREND_SLOPE_STEEP:
                    return {
                        "score": BOUNCE_TREND_SCORE_STEEP_DOWN,
                        "status": "downtrend",
                        "reason": f"Strong downtrend: SMA200 slope {sma_slope_pct:.1f}%",
                        "sma_200": sma_200,
                    }
                elif sma_slope_pct < BOUNCE_TREND_SLOPE_MODERATE:
                    return {
                        "score": BOUNCE_TREND_SCORE_MOD_DOWN,
                        "status": "downtrend",
                        "reason": f"Downtrend: SMA200 slope {sma_slope_pct:.1f}%",
                        "sma_200": sma_200,
                    }
                else:
                    return {
                        "score": BOUNCE_TREND_SCORE_MILD_DOWN,
                        "status": "downtrend",
                        "reason": f"Mild downtrend: SMA200 slope {sma_slope_pct:.1f}%",
                        "sma_200": sma_200,
                    }
            else:
                return {
                    "score": BOUNCE_TREND_SCORE_BELOW_SMA200,
                    "status": "below_sma200",
                    "reason": f"Below SMA 200 ({distance_to_sma:+.1f}%)",
                    "sma_200": sma_200,
                }

    # =========================================================================
    # RSI CALCULATION (internal)
    # =========================================================================

    def _calculate_rsi(self, prices: List[float], period: int = None) -> List[float]:
        """Calculate RSI values for the last few periods."""
        period = period or self.config.rsi_period

        if len(prices) < period + 2:
            return [50.0]

        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # Wilder's smoothed RSI
        gains = [max(c, 0) for c in changes[:period]]
        losses = [max(-c, 0) for c in changes[:period]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        rsi_values = []
        for i in range(period, len(changes)):
            c = changes[i]
            avg_gain = (avg_gain * (period - 1) + max(c, 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-c, 0)) / period

            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100 - (100 / (1 + rs)))

        return rsi_values if rsi_values else [50.0]

    # =========================================================================
    # SIGNAL TEXT
    # =========================================================================

    def _build_signal_text(
        self,
        support_level: float,
        touches: int,
        sma_200_confluence: bool,
        confirmations: Dict[str, Any],
        volume_info: Dict[str, Any],
        trend_info: Dict[str, Any],
        distance_pct: float,
    ) -> str:
        """
        Build signal text in the new format:
        "Bounce at support $X (Nx tested) | [Confirmation] | [Indicators]"
        """
        parts = []

        # Support info
        proximity = "at" if distance_pct <= 2.0 else "near"
        support_desc = f"${support_level:.2f} ({touches}x tested"
        if sma_200_confluence:
            support_desc += ", SMA 200 confluence"
        support_desc += ")"
        parts.append(f"Bounce {proximity} support {support_desc}")

        # Confirmation signals
        if confirmations["signals"]:
            parts.append(" + ".join(confirmations["signals"]))

        # Volume
        ratio = volume_info["ratio"]
        if ratio >= 1.5:
            parts.append(f"Vol {ratio:.1f}x avg")

        # Trend
        if trend_info["status"] == "uptrend":
            parts.append("Uptrend intact")
        elif trend_info["status"] == "downtrend":
            parts.append("Downtrend caution")

        return " | ".join(parts)

    # =========================================================================
    # HELPER: Create disqualified/neutral signal
    # =========================================================================

    def _make_disqualified_signal(
        self,
        symbol: str,
        current_price: float,
        reason: str,
        support_info: Dict[str, Any],
    ) -> TradeSignal:
        """Create a neutral signal for disqualified candidates."""
        return self.create_neutral_signal(symbol, current_price, reason)

    # =========================================================================
    # LEGACY HELPER METHODS (kept for backward compatibility)
    # =========================================================================

    def _calculate_target(self, entry: float, stop: float) -> float:
        """Calculates target based on Risk/Reward"""
        risk = entry - stop
        return entry + (risk * self.config.target_risk_reward)

    def _apply_divergence_penalties(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[int],
        score: float,
    ) -> float:
        """Apply bearish divergence penalties to the score.

        Runs all 7 divergence checks and sums detected penalties.
        Applied AFTER main scoring, BEFORE normalization to 0-10 scale.

        Returns:
            Adjusted score (may be lower than input if divergences detected).
        """
        signals = [
            check_price_rsi_divergence(
                prices=prices,
                lows=lows,
                highs=highs,
                severity=BOUNCE_DIV_PENALTY_PRICE_RSI,
            ),
            check_price_obv_divergence(
                prices=prices,
                volumes=volumes,
                severity=BOUNCE_DIV_PENALTY_PRICE_OBV,
            ),
            check_price_mfi_divergence(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=BOUNCE_DIV_PENALTY_PRICE_MFI,
            ),
            check_cmf_and_macd_falling(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=BOUNCE_DIV_PENALTY_CMF_MACD,
            ),
            check_momentum_divergence(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=BOUNCE_DIV_PENALTY_MOMENTUM,
            ),
            check_distribution_pattern(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=BOUNCE_DIV_PENALTY_DISTRIBUTION,
            ),
            check_cmf_early_warning(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=BOUNCE_DIV_PENALTY_CMF_EARLY,
            ),
        ]

        total_penalty = sum(sig.severity for sig in signals if sig.detected)
        if total_penalty < 0:
            logger.debug(
                "BounceAnalyzer: bearish divergence penalties applied: %.2f", total_penalty
            )
        return score + total_penalty
