# OptionPlay - Pullback Scoring Mixin
# ====================================
# Scoring methods extracted from PullbackAnalyzer to reduce module size.
# All methods are accessible as self._score_*() via mixin inheritance.

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

# Import central constants
from ..constants import (
    GAP_LOOKBACK_DAYS,
    GAP_SIZE_LARGE,
    GAP_SIZE_MEDIUM,
    GAP_SIZE_SMALL_NEG,
    KELTNER_NEUTRAL_LOW,
    SMA_MEDIUM,
    SMA_SHORT,
    VWAP_ABOVE,
    VWAP_BELOW,
    VWAP_PERIOD,
    VWAP_STRONG_ABOVE,
    VWAP_STRONG_BELOW,
)

# Import Gap Analysis
from ..indicators.gap_analysis import analyze_gap

# Import shared indicator functions used by scoring/calculation methods
from ..indicators.volatility import calculate_atr_simple, calculate_keltner_channel

# Import Volume Profile indicators
from ..indicators.volume_profile import (
    calculate_vwap,
    get_sector,
    get_sector_adjustment,
)
from ..models.indicators import (
    KeltnerChannelResult,
    MACDResult,
    RSIDivergenceResult,
    StochasticResult,
)

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS (loaded from config/analyzer_thresholds.yaml)
# =============================================================================
from ..config.analyzer_thresholds import get_analyzer_thresholds as _get_cfg

_cfg = _get_cfg()

# RSI Divergence Scoring
SCORE_DIVERGENCE_STRONG = _cfg.get("pullback.divergence.strong_threshold", 0.7)
SCORE_DIVERGENCE_MODERATE = _cfg.get("pullback.divergence.moderate_threshold", 0.4)
SCORE_DIVERGENCE_STRONG_PTS = _cfg.get("pullback.divergence_scoring.strong_pts", 3.0)
SCORE_DIVERGENCE_MODERATE_PTS = _cfg.get("pullback.divergence_scoring.moderate_pts", 2.0)
SCORE_DIVERGENCE_WEAK_PTS = _cfg.get("pullback.divergence_scoring.weak_pts", 1.0)

# Moving Average Scoring
SCORE_MA_DIP_IN_UPTREND = _cfg.get("pullback.ma_scoring.dip_in_uptrend", 2.0)

# Support Strength
SCORE_SUPPORT_STRONG_BONUS = _cfg.get("pullback.support.strong_bonus", 0.5)
SCORE_SUPPORT_STRONG_EXTRA_TOUCHES = _cfg.get("pullback.support.strong_extra_touches", 2)

# Keltner Channel
SCORE_KELTNER_LOWER_THIRD_MULT = _cfg.get("pullback.keltner.lower_third_mult", 0.5)

# VWAP Scoring
SCORE_VWAP_STRONG_ABOVE_PTS = _cfg.get("pullback.vwap.strong_above_pts", 3.0)
SCORE_VWAP_ABOVE_PTS = _cfg.get("pullback.vwap.above_pts", 2.0)
SCORE_VWAP_NEAR_PTS = _cfg.get("pullback.vwap.near_pts", 1.0)

# Market Context Scoring
SCORE_MARKET_STRONG_UPTREND = _cfg.get("pullback.market_context.strong_uptrend", 2.0)
SCORE_MARKET_UPTREND = _cfg.get("pullback.market_context.uptrend", 1.0)
SCORE_MARKET_STRONG_DOWNTREND = _cfg.get("pullback.market_context.strong_downtrend", -1.0)
SCORE_MARKET_DOWNTREND = _cfg.get("pullback.market_context.downtrend", -0.5)

# Sector Scoring Thresholds
SCORE_SECTOR_STRONG_THRESHOLD = _cfg.get("pullback.sector.strong_threshold", 0.5)
SCORE_SECTOR_WEAK_THRESHOLD = _cfg.get("pullback.sector.weak_threshold", -0.5)


class PullbackScoringMixin:
    """
    Mixin class containing all scoring methods for PullbackAnalyzer.

    This mixin expects the host class to have:
    - self.config: PullbackScoringConfig instance
    - self.STOCH_OVERSOLD / self.STOCH_OVERBOUGHT class attributes

    All methods are prefixed with _score_ or are helper calculation methods
    used exclusively by the scoring logic (Keltner, ATR).
    """

    # =========================================================================
    # SCORING METHODS
    # =========================================================================

    def _score_rsi_divergence(
        self,
        divergence: Optional[RSIDivergenceResult],
    ) -> Tuple[float, str]:
        """
        RSI Divergence Score (0-3 points).

        Bullish divergence is a strong signal for pullback entry:
        - Price makes lower low
        - RSI makes higher low
        - Selling pressure decreasing -> bottom formation likely

        Bearish divergence is a warning signal (no point deduction, but warning).
        """
        if not divergence:
            return 0, "No RSI divergence detected"

        if divergence.divergence_type == "bullish":
            # Scoring based on divergence strength
            strength = divergence.strength

            if strength >= SCORE_DIVERGENCE_STRONG:
                score = SCORE_DIVERGENCE_STRONG_PTS
                reason = f"Strong bullish divergence (strength: {strength:.0%}, {divergence.formation_days} days)"
            elif strength >= SCORE_DIVERGENCE_MODERATE:
                score = SCORE_DIVERGENCE_MODERATE_PTS
                reason = f"Moderate bullish divergence (strength: {strength:.0%}, {divergence.formation_days} days)"
            else:
                score = SCORE_DIVERGENCE_WEAK_PTS
                reason = f"Weak bullish divergence (strength: {strength:.0%}, {divergence.formation_days} days)"

            return score, reason

        elif divergence.divergence_type == "bearish":
            # Bearish divergence in pullback = warning signal, but no deduction
            return (
                0,
                f"Bearish divergence detected - caution! (strength: {divergence.strength:.0%})",
            )

        return 0, "No significant divergence"

    def _score_rsi(
        self,
        rsi: float,
        stability_score: Optional[float] = None,
        rsi_series: Optional[List[float]] = None,
    ) -> Tuple[float, str]:
        """RSI Score (0-3 points).

        Uses adaptive neutral threshold based on stability score:
        - High stability (85+): neutral at 50
        - Medium stability (70+): neutral at 45
        - Low stability (60+): neutral at 40
        - Very low (<60): neutral at 35

        RSI-Hook bonus (+0.5): If RSI turned upward from oversold in last 2 days,
        this signals the pullback is ending (literature: "enter when RSI turns up").
        """
        cfg = self.config.rsi

        # Adaptive neutral threshold from scanner config
        if stability_score is not None:
            from ..utils.scanner_config_loader import get_scanner_config

            scanner_cfg = get_scanner_config()
            neutral = scanner_cfg.get_rsi_neutral_threshold(stability_score)
        else:
            neutral = cfg.neutral  # Fallback to original fixed 50

        if rsi < cfg.extreme_oversold:
            score = cfg.weight_extreme
            reason = f"RSI {rsi:.1f} < {cfg.extreme_oversold} (extreme oversold)"
        elif rsi < cfg.oversold:
            score = cfg.weight_oversold
            reason = f"RSI {rsi:.1f} < {cfg.oversold} (oversold)"
        elif rsi < neutral:
            score = cfg.weight_neutral
            reason = f"RSI {rsi:.1f} < {neutral} (neutral-low, adaptive)"
        else:
            return 0, f"RSI {rsi:.1f} >= {neutral} (not in pullback zone)"

        # RSI-Hook bonus: RSI turning up from oversold in last 2 days
        # Literature: "enter when RSI turns up from this area"
        if rsi_series is not None and len(rsi_series) >= 3:
            rsi_delta = rsi_series[-1] - rsi_series[-3]
            if rsi_delta >= 2.0 and rsi_series[-1] < neutral + 10:
                score = min(score + 0.5, cfg.weight_extreme)  # Cap at component max
                reason += f" | Hook +0.5 (RSI turning up {rsi_delta:+.1f})"

        return score, reason

    def _score_support(self, price: float, supports: List[float]) -> Tuple[float, str]:
        """Support proximity Score (0-2 points)"""
        if not supports:
            return 0, "No support levels found"

        cfg = self.config.support
        nearest = min(supports, key=lambda x: abs(x - price))
        distance_pct = abs(price - nearest) / price * 100

        if distance_pct <= cfg.proximity_percent:
            return cfg.weight_close, f"Within {cfg.proximity_percent}% of support ${nearest:.2f}"
        elif distance_pct <= cfg.proximity_percent_wide:
            return (
                cfg.weight_near,
                f"Within {cfg.proximity_percent_wide}% of support ${nearest:.2f}",
            )
        else:
            return 0, f"{distance_pct:.1f}% from nearest support"

    def _score_fibonacci(
        self,
        price: float,
        fib_levels: Dict[str, float],
    ) -> Tuple[float, Optional[str], str]:
        """Fibonacci Score (0-2 points)"""
        for lvl in self.config.fibonacci.levels:
            level_name = f"{lvl.level * 100:.1f}%"
            level_price = fib_levels.get(level_name)

            if level_price and abs(price - level_price) / price <= lvl.tolerance:
                return lvl.points, level_name, f"At Fib {level_name}"

        return 0, None, "Not at significant Fib level"

    def _score_moving_averages(
        self,
        price: float,
        sma_20: float,
        sma_200: float,
    ) -> Tuple[float, str]:
        """Moving Average Score (0-2 points)"""
        if price > sma_200 and price < sma_20:
            return SCORE_MA_DIP_IN_UPTREND, "Dip in uptrend (price > SMA200, < SMA20)"
        elif price > sma_200 and price > sma_20:
            return 0, "Strong uptrend, no pullback"
        elif price < sma_200:
            return 0, "Below SMA200, no primary uptrend"

        return 0, "MA config doesn't indicate pullback"

    @staticmethod
    def _intraday_volume_scale() -> float:
        """
        Returns a scaling factor to normalize intraday partial volume
        to a full-day estimate.

        US market hours: 9:30-16:00 ET (390 minutes).
        If called at 11:00 ET (90 min elapsed), returns 390/90 = 4.33.
        Outside market hours or after close, returns 1.0 (no adjustment).
        """
        from datetime import datetime, timezone, timedelta

        et = timezone(timedelta(hours=-5))
        now = datetime.now(et)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

        if now >= market_close or now <= market_open:
            return 1.0  # After hours or pre-market: no adjustment

        elapsed_min = (now - market_open).total_seconds() / 60.0
        if elapsed_min < 1:
            return 1.0

        return min(390.0 / elapsed_min, 10.0)  # Cap at 10x to avoid extremes at open

    def _score_volume(self, current: int, average: int) -> Tuple[float, str, str]:
        """
        Volume Score (0-1 point)

        NEW: Decreasing volume during pullback = healthy (no panic selling)
        Intraday adjustment: scales partial-day volume to full-day estimate.
        """
        if average == 0:
            return 0, "No average volume data", "unknown"

        # Adjust for intraday partial volume
        scale = self._intraday_volume_scale()
        adjusted_current = current * scale
        ratio = adjusted_current / average
        cfg = self.config.volume

        # E.3: Very low volume = weak conviction penalty
        if ratio < cfg.very_low_threshold:
            return (
                cfg.weight_very_low,
                f"Very low volume: {ratio:.1f}x avg (weak conviction)",
                "very_low",
            )
        # NEW: Decreasing volume is POSITIVE during a pullback
        elif ratio < cfg.decrease_threshold:
            return (
                cfg.weight_decreasing,
                f"Low volume pullback: {ratio:.1f}x avg (healthy)",
                "decreasing",
            )
        elif ratio >= cfg.spike_multiplier:
            # High volume during pullback = potentially problematic (panic)
            return 0, f"Volume spike: {ratio:.1f}x avg (caution)", "increasing"
        else:
            return 0, f"Volume normal: {ratio:.1f}x avg", "stable"

    def _score_macd(self, macd: Optional[MACDResult]) -> Tuple[float, str, str]:
        """
        MACD Score (0-2 points)

        - Bullish Cross: 2 points (strong reversal signal)
        - Histogram positive: 1 point
        """
        if not macd:
            return 0, "No MACD data", "neutral"

        cfg = self.config.macd

        if macd.crossover == "bullish":
            return cfg.weight_bullish_cross, "MACD bullish crossover", "bullish_cross"
        elif macd.histogram and macd.histogram > 0:
            return cfg.weight_bullish, "MACD histogram positive", "bullish"
        elif macd.histogram and macd.histogram < 0:
            return 0, "MACD histogram negative", "bearish"

        return cfg.weight_neutral, "MACD neutral", "neutral"

    def _score_stochastic(self, stoch: Optional[StochasticResult]) -> Tuple[float, str, str]:
        """
        Stochastic Score (0-2 points)

        - Oversold + Bullish Cross: 2 points (very strong signal)
        - Only Oversold: 1 point
        """
        if not stoch:
            return 0, "No Stochastic data", "neutral"

        cfg = self.config.stochastic

        if stoch.zone == "oversold":
            if stoch.crossover == "bullish":
                return (
                    cfg.weight_oversold_cross,
                    f"Stoch oversold ({stoch.k:.0f}) + bullish cross",
                    "oversold_bullish_cross",
                )
            return cfg.weight_oversold, f"Stoch oversold ({stoch.k:.0f})", "oversold"
        elif stoch.zone == "overbought":
            return 0, f"Stoch overbought ({stoch.k:.0f})", "overbought"

        return 0, f"Stoch neutral ({stoch.k:.0f})", "neutral"

    def _score_trend_strength(
        self,
        prices: List[float],
        sma_20: float,
        sma_50: Optional[float],
        sma_200: float,
    ) -> Tuple[float, str, float, str]:
        """
        Trend Strength Score (0-2 points)

        - Strong alignment (SMA20 > SMA50 > SMA200): 2 points
        - Moderate alignment (Price > SMA200): 1 point
        - No alignment: 0 points

        Returns:
            (score, alignment, sma20_slope, reason)
        """
        cfg = self.config.trend_strength
        current_price = prices[-1]

        # Calculate SMA20 slope
        slope_lookback = min(cfg.slope_lookback, len(prices) - 1)
        if slope_lookback > 0:
            sma20_recent = sum(prices[-20:]) / 20 if len(prices) >= 20 else current_price
            sma20_older = (
                sum(prices[-20 - slope_lookback : -slope_lookback]) / 20
                if len(prices) >= 20 + slope_lookback
                else sma20_recent
            )
            sma20_slope = (sma20_recent - sma20_older) / sma20_older if sma20_older > 0 else 0
        else:
            sma20_slope = 0

        # Check SMA alignment
        if sma_50 is not None:
            # Full alignment: SMA20 > SMA50 > SMA200
            if sma_20 > sma_50 > sma_200 and current_price > sma_200:
                if sma20_slope >= cfg.min_positive_slope:
                    return (
                        cfg.weight_strong_alignment,
                        "strong",
                        sma20_slope,
                        "Strong uptrend (SMA20 > SMA50 > SMA200, rising)",
                    )
                else:
                    return (
                        cfg.weight_moderate_alignment,
                        "moderate",
                        sma20_slope,
                        "Aligned SMAs but flat/declining slope",
                    )
            elif current_price > sma_200 and sma_20 > sma_200:
                return (
                    cfg.weight_moderate_alignment,
                    "moderate",
                    sma20_slope,
                    "Above SMA200, partial alignment",
                )
        else:
            # Without SMA50: Only check SMA20 vs SMA200
            if sma_20 > sma_200 and current_price > sma_200:
                if sma20_slope >= cfg.min_positive_slope:
                    return (
                        cfg.weight_strong_alignment,
                        "strong",
                        sma20_slope,
                        "Strong uptrend (SMA20 > SMA200, rising)",
                    )
                else:
                    return (
                        cfg.weight_moderate_alignment,
                        "moderate",
                        sma20_slope,
                        "Above SMA200 but flat slope",
                    )

        # No uptrend
        if current_price < sma_200:
            return 0, "none", sma20_slope, "Below SMA200 - no uptrend"

        return 0, "weak", sma20_slope, "Weak trend structure"

    def _score_support_with_strength(
        self,
        price: float,
        supports: List[float],
        volumes: Optional[List[int]] = None,
        lows: Optional[List[float]] = None,
    ) -> Tuple[float, str, str, int]:
        """
        Extended support scoring with strength rating.

        Returns:
            (score, reason, strength, touches)
        """
        if not supports:
            return 0, "No support levels found", "none", 0

        cfg = self.config.support
        nearest = min(supports, key=lambda x: abs(x - price))
        distance_pct = abs(price - nearest) / price * 100

        # Estimate support strength based on frequency
        touches = 0
        strength = "weak"

        if lows is not None:
            tolerance = nearest * (cfg.touch_tolerance_pct / 100)
            touches = sum(
                1 for low in lows[-cfg.lookback_days :] if abs(low - nearest) <= tolerance
            )

            if touches >= cfg.min_touches + SCORE_SUPPORT_STRONG_EXTRA_TOUCHES:
                strength = "strong"
            elif touches >= cfg.min_touches:
                strength = "moderate"
            else:
                strength = "weak"

        # Scoring based on distance AND strength
        base_score = 0
        if distance_pct <= cfg.proximity_percent:
            base_score = cfg.weight_close
        elif distance_pct <= cfg.proximity_percent_wide:
            base_score = cfg.weight_near

        # Bonus for strong support
        if strength == "strong" and base_score > 0:
            base_score += SCORE_SUPPORT_STRONG_BONUS  # Bonus for strong support

        reason = (
            f"Within {distance_pct:.1f}% of {strength} support ${nearest:.2f} ({touches} touches)"
        )
        return base_score, reason, strength, touches

    # =========================================================================
    # CANDLESTICK REVERSAL SCORING (Component #15)
    # =========================================================================

    def _score_candlestick_reversal(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        support_score: float = 0,
        fibonacci_score: float = 0,
    ) -> Tuple[float, str, str]:
        """
        Candlestick Reversal Score (0-2 points).

        Detects reversal candlestick patterns at relevant levels.
        Only fires when Support or Fibonacci is also active (contextual anchor).

        Patterns:
        - Hammer: lower shadow > 2x body, small upper shadow → 2.0
        - Bullish Engulfing: today's green body engulfs yesterday's red body → 1.5
        - Doji with lower shadow: body < 0.3% of price → 1.0

        Returns:
            (score, pattern_name, reason)
        """
        if len(prices) < 2 or len(highs) < 2 or len(lows) < 2:
            return 0, "none", "Insufficient data for candlestick analysis"

        # Only score if Support or Fibonacci provides context
        has_context = support_score > 0 or fibonacci_score > 0
        if not has_context:
            return 0, "none", "No support/fibonacci context for candlestick"

        # Today's candle
        open_today = prices[-2]  # Approximate open as previous close
        close_today = prices[-1]
        high_today = highs[-1]
        low_today = lows[-1]
        body = abs(close_today - open_today)
        full_range = high_today - low_today

        if full_range <= 0:
            return 0, "none", "No price range"

        # Yesterday's candle
        open_yest = prices[-3] if len(prices) >= 3 else prices[-2]
        close_yest = prices[-2]

        # --- Hammer Detection ---
        # Lower shadow > 2x body, upper shadow < 30% of full range
        lower_shadow = min(open_today, close_today) - low_today
        upper_shadow = high_today - max(open_today, close_today)

        if body > 0 and lower_shadow >= 2 * body and upper_shadow <= 0.3 * full_range:
            return 2.0, "hammer", f"Hammer at support (shadow {lower_shadow/body:.1f}x body)"

        # --- Bullish Engulfing Detection ---
        # Yesterday red (close < open), today green (close > open),
        # today's body engulfs yesterday's body
        yest_red = close_yest < open_yest
        today_green = close_today > open_today
        if yest_red and today_green:
            if close_today > open_yest and open_today <= close_yest:
                return 1.5, "bullish_engulfing", "Bullish Engulfing at support"

        # --- Doji with Lower Shadow ---
        # Body < 0.3% of price, meaningful lower shadow
        body_pct = body / close_today * 100
        if body_pct < 0.3 and lower_shadow > body * 1.5:
            return 1.0, "doji", f"Doji with lower shadow at support (body {body_pct:.2f}%)"

        return 0, "none", "No reversal candlestick pattern"

    # =========================================================================
    # SIGNAL HELPER (Legacy - for backward compatibility)
    # =========================================================================

    def _get_macd_signal(self, macd: Optional[MACDResult]) -> Optional[str]:
        """Determines MACD signal for display"""
        if not macd:
            return None

        if macd.crossover == "bullish":
            return "bullish_cross"
        elif macd.crossover == "bearish":
            return "bearish_cross"
        elif macd.histogram > 0:
            return "bullish"
        elif macd.histogram < 0:
            return "bearish"

        return "neutral"

    def _get_stoch_signal(self, stoch: Optional[StochasticResult]) -> Optional[str]:
        """Determines Stochastic signal for display"""
        if not stoch:
            return None

        if stoch.zone == "oversold":
            if stoch.crossover == "bullish":
                return "oversold_bullish_cross"
            return "oversold"
        elif stoch.zone == "overbought":
            if stoch.crossover == "bearish":
                return "overbought_bearish_cross"
            return "overbought"

        return "neutral"

    # =========================================================================
    # KELTNER CHANNEL (calculation + scoring)
    # =========================================================================

    def _calculate_keltner_channel(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
    ) -> Optional[KeltnerChannelResult]:
        """Calculates Keltner Channel. Delegates to shared indicators library."""
        cfg = self.config.keltner
        return calculate_keltner_channel(
            prices=prices,
            highs=highs,
            lows=lows,
            ema_period=cfg.ema_period,
            atr_period=cfg.atr_period,
            atr_multiplier=cfg.atr_multiplier,
        )

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> Optional[float]:
        """Calculates ATR (SMA-based). Delegates to shared indicators library."""
        return calculate_atr_simple(highs, lows, closes, period)

    def _score_keltner(
        self,
        keltner: KeltnerChannelResult,
        current_price: float,
    ) -> Tuple[float, str]:
        """
        Keltner Channel Score (0-2 points).

        Scoring logic for pullbacks:
        - Price below lower band: 2 points (strongly oversold, mean reversion expected)
        - Price near lower band: 1 point (pullback in oversold territory)
        - Price in channel: 0 points (neutral)
        - Price above upper band: 0 points (overbought, no pullback setup)

        Returns:
            (score, reason)
        """
        cfg = self.config.keltner
        position = keltner.price_position
        pct = keltner.percent_position

        if position == "below_lower":
            return cfg.weight_below_lower, f"Price below Keltner Lower Band ({pct:.2f})"

        if position == "near_lower":
            # Near lower band = potential buy opportunity
            return cfg.weight_near_lower, f"Price near Keltner Lower Band ({pct:.2f})"

        if position == "in_channel" and pct < KELTNER_NEUTRAL_LOW:
            # In channel, but in lower third
            return (
                cfg.weight_mean_reversion * SCORE_KELTNER_LOWER_THIRD_MULT,
                f"Pullback in lower channel area ({pct:.2f})",
            )

        if position == "above_upper":
            # Overbought = no pullback signal
            return 0, f"Price above Keltner Upper Band ({pct:.2f}) - overbought"

        return 0, f"Price in neutral channel position ({pct:.2f})"

    # =========================================================================
    # FEATURE ENGINEERING SCORING METHODS
    # =========================================================================

    def _score_vwap(
        self,
        prices: List[float],
        volumes: List[int],
    ) -> Tuple[float, float, float, str, str]:
        """
        VWAP Score (0-3 points).

        Based on Feature Engineering Training:
        - Above VWAP >3%: 91.9% win rate -> 3 points
        - Above VWAP 1-3%: 87.6% win rate -> 2 points
        - Near VWAP: 78.3% win rate -> 1 point
        - Below VWAP: 51.7-66.1% win rate -> 0 points

        Returns:
            (score, vwap_value, distance_pct, position, reason)
        """
        vwap_result = calculate_vwap(prices, volumes, period=VWAP_PERIOD)

        if not vwap_result:
            return 0, 0, 0, "unknown", "Insufficient data for VWAP"

        vwap = vwap_result.vwap
        distance = vwap_result.distance_pct
        position = vwap_result.position

        # Scoring based on training results
        if distance > VWAP_STRONG_ABOVE:
            score = SCORE_VWAP_STRONG_ABOVE_PTS
            reason = f"Strong momentum: {distance:.1f}% above VWAP (91.9% win rate)"
        elif distance > VWAP_ABOVE:
            score = SCORE_VWAP_ABOVE_PTS
            reason = f"Above VWAP: {distance:.1f}% (87.6% win rate)"
        elif distance > VWAP_BELOW:
            score = SCORE_VWAP_NEAR_PTS
            reason = f"Near VWAP: {distance:.1f}% (78.3% win rate)"
        elif distance > VWAP_STRONG_BELOW:
            score = 0.0
            reason = f"Below VWAP: {distance:.1f}% (66.1% win rate)"
        else:
            score = 0.0
            reason = f"Weak: {distance:.1f}% below VWAP (51.7% win rate)"

        return score, vwap, distance, position, reason

    def _score_market_context(
        self,
        spy_prices: Optional[List[float]],
    ) -> Tuple[float, str, str]:
        """
        Market Context Score (0-2 points).

        Based on Feature Engineering Training:
        - Strong uptrend: 76.1% win rate, +$1.03M -> 2 points
        - Uptrend: 70.9% win rate -> 1 point
        - Sideways: neutral -> 0 points
        - Downtrend: 60.1% win rate, -$470k -> -0.5 points (penalty)
        - Strong downtrend: 59.3% win rate -> -1 point (penalty)

        Returns:
            (score, spy_trend, reason)
        """
        if not spy_prices or len(spy_prices) < SMA_MEDIUM:
            return 0, "unknown", "No SPY data for market context"

        # Determine SPY trend
        current = spy_prices[-1]
        sma20 = float(np.mean(spy_prices[-SMA_SHORT:]))
        sma50 = float(np.mean(spy_prices[-SMA_MEDIUM:]))

        if current > sma20 > sma50:
            trend = "strong_uptrend"
            score = SCORE_MARKET_STRONG_UPTREND
            reason = "Strong market uptrend (76.1% win rate)"
        elif current > sma50 and current > sma20:
            trend = "uptrend"
            score = SCORE_MARKET_UPTREND
            reason = "Market uptrend (70.9% win rate)"
        elif current > sma50:
            trend = "sideways"
            score = 0.0
            reason = "Market sideways"
        elif current < sma20 < sma50:
            trend = "strong_downtrend"
            score = SCORE_MARKET_STRONG_DOWNTREND
            reason = "Strong market downtrend - CAUTION (59.3% win rate)"
        else:
            trend = "downtrend"
            score = SCORE_MARKET_DOWNTREND
            reason = "Market downtrend - reduced expectation (60.1% win rate)"

        return score, trend, reason

    def _score_sector(self, symbol: str) -> Tuple[float, str, str]:
        """
        Sector Score (-1 to +1 point).

        Based on Feature Engineering Training:
        - Consumer Staples: +9% win rate -> +0.9 points
        - Utilities: +6.8% -> +0.7 points
        - Financials: +6.4% -> +0.6 points
        - Technology: -10% -> -1.0 points
        - Materials: -7.5% -> -0.75 points

        Returns:
            (score, sector_name, reason)
        """
        sector = get_sector(symbol)
        adjustment = get_sector_adjustment(symbol)

        if adjustment > SCORE_SECTOR_STRONG_THRESHOLD:
            reason = f"{sector}: strong sector (+{adjustment * 10:.0f}% win rate)"
        elif adjustment > 0:
            reason = f"{sector}: favorable sector (+{adjustment * 10:.0f}% win rate)"
        elif adjustment < SCORE_SECTOR_WEAK_THRESHOLD:
            reason = f"{sector}: challenging sector ({adjustment * 10:.0f}% win rate)"
        elif adjustment < 0:
            reason = f"{sector}: slightly unfavorable ({adjustment * 10:.0f}% win rate)"
        else:
            reason = f"{sector}: neutral sector"

        return adjustment, sector, reason

    def _score_gap(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        context=None,
    ) -> Tuple[float, str, float, bool, str]:
        """
        Gap Score (0-1 for down-gaps, -0.5 to 0 for up-gaps).

        Validated with 174k+ Gap Events (907 symbols, 5 years):
        - Down-gaps: +0.43% better 30d returns, +1.9pp higher win rate
        - Large down-gaps (>3%): +1.21% outperformance at 5d
        - 30-Day Win Rate: 56.7% (down) vs 54.8% (up)

        Returns:
            (score, gap_type, gap_size_pct, is_filled, reason)
        """
        # Use context if available (already calculated)
        if context and hasattr(context, "gap_result") and context.gap_result:
            gap = context.gap_result
            gap_type = gap.gap_type
            gap_size = gap.gap_size_pct
            is_filled = gap.is_filled
            quality_score = gap.quality_score

            # Convert quality_score (-1 to +1) to display score
            if gap_type in ("down", "partial_down"):
                score = max(0, quality_score)  # 0 to 1
                if abs(gap_size) >= GAP_SIZE_LARGE:
                    reason = (
                        f"Large down-gap: {gap_size:.1f}% - strong entry (+1.21% outperformance)"
                    )
                elif abs(gap_size) >= GAP_SIZE_MEDIUM:
                    reason = f"Down-gap: {gap_size:.1f}% - favorable entry (+0.43% 30d)"
                else:
                    reason = f"Small down-gap: {gap_size:.1f}% - mild positive"
            elif gap_type in ("up", "partial_up"):
                score = min(0, quality_score)  # -0.5 to 0
                if abs(gap_size) >= GAP_SIZE_LARGE:
                    reason = f"Large up-gap: {gap_size:+.1f}% - caution, overbought risk"
                elif abs(gap_size) >= GAP_SIZE_MEDIUM:
                    reason = f"Up-gap: {gap_size:+.1f}% - short-term momentum"
                else:
                    reason = f"Small up-gap: {gap_size:+.1f}% - neutral"
            else:
                score = 0.0
                gap_type = "none"
                gap_size = 0.0
                is_filled = False
                reason = "No significant gap"

            return score, gap_type, gap_size, is_filled, reason

        # Calculate directly if context not available
        if len(prices) < 2:
            return 0.0, "none", 0.0, False, "Insufficient data"

        try:
            # Approximate opens from closes (previous close)
            opens = [prices[0]] + prices[:-1]

            gap_result = analyze_gap(
                opens=opens,
                highs=highs,
                lows=lows,
                closes=prices,
                lookback_days=GAP_LOOKBACK_DAYS,
                min_gap_pct=abs(GAP_SIZE_SMALL_NEG),
            )

            if gap_result and gap_result.gap_type != "none":
                # Recursively call with context
                class TempContext:
                    pass

                temp_ctx = TempContext()
                temp_ctx.gap_result = gap_result
                return self._score_gap(prices, highs, lows, temp_ctx)
            else:
                return 0.0, "none", 0.0, False, "No significant gap"

        except Exception as e:
            logger.debug(f"Gap scoring error: {e}")
            return 0.0, "none", 0.0, False, "Gap analysis error"
