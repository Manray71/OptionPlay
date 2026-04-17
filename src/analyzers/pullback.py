# OptionPlay - Pullback Analyzer
# ================================
# Technical analysis for pullback candidates
#
# Scoring methods are in pullback_scoring.py (PullbackScoringMixin).

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..config import PullbackScoringConfig

# Import central constants (with alias to avoid naming conflicts)
from ..constants import (
    DIVERGENCE_MAX_BARS,
    DIVERGENCE_MIN_BARS,
    DIVERGENCE_SWING_WINDOW,
    FIB_LEVELS,
    FIB_LOOKBACK_DAYS,
    GAP_LOOKBACK_DAYS,
    GAP_SIZE_LARGE,
    GAP_SIZE_LARGE_NEG,
    GAP_SIZE_MEDIUM,
    GAP_SIZE_SMALL_NEG,
    KELTNER_ATR_MULTIPLIER,
    KELTNER_LOWER_THRESHOLD,
    KELTNER_NEUTRAL_LOW,
)
from ..constants import MACD_FAST as _MACD_FAST
from ..constants import MACD_SIGNAL as _MACD_SIGNAL
from ..constants import MACD_SLOW as _MACD_SLOW
from ..constants import (
    PRICE_TOLERANCE,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    SMA_LONG,
    SMA_MEDIUM,
    SMA_SHORT,
)
from ..constants import STOCH_D_PERIOD as _STOCH_D
from ..constants import STOCH_K_PERIOD as _STOCH_K
from ..constants import STOCH_OVERBOUGHT as _STOCH_OVERBOUGHT
from ..constants import STOCH_OVERSOLD as _STOCH_OVERSOLD
from ..constants import STOCH_SMOOTH as _STOCH_SMOOTH
from ..constants import (
    SUPPORT_LOOKBACK_DAYS,
    SUPPORT_MAX_LEVELS,
    SUPPORT_TOLERANCE_PCT,
    SUPPORT_WINDOW,
    VOLUME_AVG_PERIOD,
    VOLUME_SPIKE_MULTIPLIER,
    VWAP_ABOVE,
    VWAP_BELOW,
    VWAP_PERIOD,
    VWAP_STRONG_ABOVE,
    VWAP_STRONG_BELOW,
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
from ..indicators.momentum import calculate_macd, calculate_rsi_divergence, calculate_stochastic

# Import optimized support/resistance functions
from ..indicators.support_resistance import find_resistance_levels as find_resistance_optimized
from ..indicators.support_resistance import find_support_levels as find_support_optimized
from ..indicators.trend import calculate_ema
from ..models.base import SignalStrength, SignalType, TradeSignal
from ..models.candidates import PullbackCandidate, ScoreBreakdown
from ..models.indicators import (
    KeltnerChannelResult,
    MACDResult,
    RSIDivergenceResult,
    StochasticResult,
    TechnicalIndicators,
)
from .base import BaseAnalyzer
from .context import AnalysisContext
from .pullback_scoring import PullbackScoringMixin
from .score_normalization import STRATEGY_SCORE_CONFIGS, get_signal_strength, normalize_score

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS (loaded from config/analyzer_thresholds.yaml)
# =============================================================================
from ..config.analyzer_thresholds import get_analyzer_thresholds as _get_cfg

_cfg = _get_cfg()

# Signal strength thresholds (on 0-10 normalized scale)
PULLBACK_SIGNAL_STRONG = _cfg.get("pullback.signal.strong", 7.0)
PULLBACK_SIGNAL_MODERATE = _cfg.get("pullback.signal.moderate", 5.0)
PULLBACK_MIN_NORMALIZED_SCORE = _cfg.get("pullback.signal.min_normalized_score", 3.5)

# Stop loss & targets
PULLBACK_STOP_BUFFER = _cfg.get("pullback.risk.stop_buffer", 0.98)
PULLBACK_TARGET_RR_RATIO = _cfg.get("pullback.risk.target_rr_ratio", 2.0)

# RSI divergence detection
PULLBACK_DIVERGENCE_LOOKBACK = _cfg.get("pullback.divergence.lookback", 60)
PULLBACK_DIVERGENCE_SWING_WINDOW = _cfg.get("pullback.divergence.swing_window", 3)
PULLBACK_DIVERGENCE_MIN_BARS = _cfg.get("pullback.divergence.min_bars", 5)
PULLBACK_DIVERGENCE_MAX_BARS = _cfg.get("pullback.divergence.max_bars", 50)

# Support/resistance detection
PULLBACK_SUPPORT_WINDOW = _cfg.get("pullback.support.window", 5)
PULLBACK_MAX_SUPPORT_LEVELS = _cfg.get("pullback.support.max_levels", 5)
PULLBACK_SUPPORT_TOLERANCE_PCT = _cfg.get("pullback.support.tolerance_pct", 1.5)
PULLBACK_RESISTANCE_LOOKBACK = _cfg.get("pullback.resistance.lookback", 60)
PULLBACK_RESISTANCE_WINDOW = _cfg.get("pullback.resistance.window", 5)
PULLBACK_MAX_RESISTANCE_LEVELS = _cfg.get("pullback.resistance.max_levels", 5)
PULLBACK_RESISTANCE_TOLERANCE_PCT = _cfg.get("pullback.resistance.tolerance_pct", 1.5)

# Gap detection thresholds
PULLBACK_GAP_WARNING_MIN = _cfg.get("pullback.gap.warning_min_pct", -3.0)
PULLBACK_GAP_WARNING_MAX = _cfg.get("pullback.gap.warning_max_pct", -1.0)
PULLBACK_GAP_VOL_THRESHOLD = 0.8  # Not in YAML — structural, not a scoring tier

# Bearish Divergence Penalties (negative values)
PULLBACK_DIV_PENALTY_PRICE_RSI = _cfg.get("pullback.divergence.price_rsi", -2.0)
PULLBACK_DIV_PENALTY_PRICE_OBV = _cfg.get("pullback.divergence.price_obv", -1.5)
PULLBACK_DIV_PENALTY_PRICE_MFI = _cfg.get("pullback.divergence.price_mfi", -1.5)
PULLBACK_DIV_PENALTY_CMF_MACD = _cfg.get("pullback.divergence.cmf_macd_falling", -1.0)
PULLBACK_DIV_PENALTY_MOMENTUM = _cfg.get("pullback.divergence.momentum_divergence", -1.5)
PULLBACK_DIV_PENALTY_DISTRIBUTION = _cfg.get("pullback.divergence.distribution_pattern", -3.0)
PULLBACK_DIV_PENALTY_CMF_EARLY = _cfg.get("pullback.divergence.cmf_early_warning", -1.0)


class PullbackAnalyzer(PullbackScoringMixin, BaseAnalyzer):
    """
    Analyzes stocks for pullback setups.

    Indicators:
    - RSI (14) - Oversold/Overbought
    - MACD (12, 26, 9) - Trend & Momentum
    - Stochastic (14, 3, 3) - Overbought/Oversold
    - SMAs (20, 50, 200) - Trend
    - Support/Resistance - Swing Highs/Lows
    - Fibonacci Retracements

    Scoring methods are provided by PullbackScoringMixin.
    """

    # MACD Default Parameter (from src/constants)
    # Variable names kept for backward compatibility
    MACD_FAST = _MACD_FAST  # 12 - Fast EMA
    MACD_SLOW = _MACD_SLOW  # 26 - Slow EMA
    MACD_SIGNAL = _MACD_SIGNAL  # 9  - Signal Line

    # Stochastic Default Parameters (from src/constants)
    STOCH_K = _STOCH_K  # 14
    STOCH_D = _STOCH_D  # 3
    STOCH_SMOOTH = _STOCH_SMOOTH  # 3
    STOCH_OVERSOLD = _STOCH_OVERSOLD  # 20
    STOCH_OVERBOUGHT = _STOCH_OVERBOUGHT  # 80

    def __init__(self, config: PullbackScoringConfig) -> None:
        self.config = config

    @property
    def strategy_name(self) -> str:
        return "pullback"

    @property
    def description(self) -> str:
        return "Identifies pullback setups in uptrending stocks near support levels"

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
        Analyzes a symbol for pullback setup.

        Args:
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            TradeSignal with score and entry recommendation
        """
        # Perform complete analysis
        candidate = self.analyze_detailed(symbol, prices, volumes, highs, lows, context=context)

        # Normalize score to 0-10 scale for fair cross-strategy comparison
        max_possible = (
            candidate.score_breakdown.max_possible
            if hasattr(candidate.score_breakdown, "max_possible")
            else STRATEGY_SCORE_CONFIGS["pullback"].max_possible
        )
        normalized_score = normalize_score(candidate.score, "pullback", max_possible=max_possible)

        # Convert to TradeSignal (based on normalized 0-10 scale)
        if normalized_score >= PULLBACK_MIN_NORMALIZED_SCORE:
            signal_type = SignalType.LONG
            if normalized_score >= PULLBACK_SIGNAL_STRONG:
                strength = SignalStrength.STRONG
            elif normalized_score >= PULLBACK_SIGNAL_MODERATE:
                strength = SignalStrength.MODERATE
            else:
                strength = SignalStrength.WEAK
        else:
            signal_type = SignalType.NEUTRAL
            strength = SignalStrength.NONE

        # Calculate Entry/Stop/Target
        entry_price = candidate.current_price
        stop_loss = None
        target_price = None

        if candidate.support_levels:
            # Stop below the nearest support
            nearest_support = min(candidate.support_levels, key=lambda x: abs(x - entry_price))
            stop_loss = nearest_support * PULLBACK_STOP_BUFFER  # 2% unter Support

            # Target at next resistance or 2:1 R/R
            if candidate.resistance_levels:
                target_price = min(
                    candidate.resistance_levels,
                    key=lambda x: x if x > entry_price else float("inf"),
                )

            if not target_price or target_price <= entry_price:
                # Fallback: 2:1 Risk/Reward
                risk = entry_price - stop_loss
                target_price = entry_price + (risk * PULLBACK_TARGET_RR_RATIO)

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=signal_type,
            strength=strength,
            score=round(normalized_score, 1),  # Normalized 0-10 score
            current_price=candidate.current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=self._build_reason(candidate),
            details={
                "rsi": candidate.technicals.rsi_14,
                "trend": candidate.technicals.trend,
                "support_levels": candidate.support_levels,
                "score_breakdown": candidate.score_breakdown.to_dict(),
                "raw_score": candidate.score,
                "max_possible": max_possible,
            },
        )

    def analyze_detailed(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        context: Optional[AnalysisContext] = None,
    ) -> PullbackCandidate:
        """
        Complete pullback analysis for a symbol.

        Args:
            symbol: Ticker symbol
            prices: Closing prices (oldest first)
            volumes: Daily volume
            highs: Daily highs
            lows: Daily lows
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            PullbackCandidate with score, breakdown, and all indicators

        Raises:
            ValueError: For invalid or inconsistent input data
        """
        # Input validation
        self._validate_inputs(symbol, prices, volumes, highs, lows)

        min_required = self.config.moving_averages.long_period
        if len(prices) < min_required:
            raise ValueError(f"Need {min_required} data points, got {len(prices)}")

        current_price = prices[-1]
        current_volume = volumes[-1]

        # Weekend/holiday fallback: use last non-zero volume
        if current_volume == 0 and len(volumes) >= 2:
            for v in reversed(volumes[:-1]):
                if v > 0:
                    current_volume = v
                    break

        # Use context if provided, otherwise calculate
        if context and context.rsi_14 is not None:
            # Use pre-calculated values from context
            rsi = context.rsi_14
            sma_20 = context.sma_20
            sma_50 = context.sma_50
            sma_200 = context.sma_200
            above_sma20 = context.above_sma20
            above_sma50 = context.above_sma50
            above_sma200 = context.above_sma200
            trend = context.trend
            support_levels = context.support_levels
            resistance_levels = context.resistance_levels

            # MACD still needs MACDResult format
            if context.macd_line is not None:
                crossover = None
                if context.macd_histogram:
                    crossover = "bullish" if context.macd_histogram > 0 else "bearish"
                macd_result = MACDResult(
                    macd_line=context.macd_line,
                    signal_line=context.macd_signal,
                    histogram=context.macd_histogram,
                    crossover=crossover,
                )
            else:
                macd_result = self._calculate_macd(prices)

            # Stochastic
            if context.stoch_k is not None:
                if context.stoch_k < self.STOCH_OVERSOLD:
                    zone = "oversold"
                elif context.stoch_k > self.STOCH_OVERBOUGHT:
                    zone = "overbought"
                else:
                    zone = "neutral"
                stoch_result = StochasticResult(
                    k=context.stoch_k,
                    d=context.stoch_d,
                    zone=zone,
                )
            else:
                stoch_result = self._calculate_stochastic(highs, lows, prices)
        else:
            # Calculate everything (fallback)
            rsi = self._calculate_rsi(prices, self.config.rsi.period)
            sma_20 = self._calculate_sma(prices, self.config.moving_averages.short_period)
            sma_50 = self._calculate_sma(prices, 50) if len(prices) >= 50 else None
            sma_200 = self._calculate_sma(prices, self.config.moving_averages.long_period)
            macd_result = self._calculate_macd(prices)
            stoch_result = self._calculate_stochastic(highs, lows, prices)

            # Determine trend
            above_sma20 = current_price > sma_20
            above_sma50 = current_price > sma_50 if sma_50 else None
            above_sma200 = current_price > sma_200

            if above_sma200 and above_sma20:
                trend = "uptrend"
            elif not above_sma200 and not above_sma20:
                trend = "downtrend"
            else:
                trend = "sideways"

            # Support/Resistance (using optimized O(n) algorithm)
            support_levels = find_support_optimized(
                lows=lows,
                lookback=self.config.support.lookback_days,
                window=PULLBACK_SUPPORT_WINDOW,
                max_levels=PULLBACK_MAX_SUPPORT_LEVELS,
                volumes=volumes if volumes else None,
                tolerance_pct=PULLBACK_SUPPORT_TOLERANCE_PCT,
            )
            resistance_levels = find_resistance_optimized(
                highs=highs,
                lookback=PULLBACK_RESISTANCE_LOOKBACK,
                window=PULLBACK_RESISTANCE_WINDOW,
                max_levels=PULLBACK_MAX_RESISTANCE_LEVELS,
                volumes=volumes if volumes else None,
                tolerance_pct=PULLBACK_RESISTANCE_TOLERANCE_PCT,
            )

        technicals = TechnicalIndicators(
            rsi_14=rsi,
            sma_20=sma_20,
            sma_50=sma_50,
            sma_200=sma_200,
            macd=macd_result,
            stochastic=stoch_result,
            above_sma20=above_sma20,
            above_sma50=above_sma50,
            above_sma200=above_sma200,
            trend=trend,
        )

        # Fibonacci
        lookback = self.config.fibonacci.lookback_days
        fib_levels = self._calculate_fibonacci(max(highs[-lookback:]), min(lows[-lookback:]))

        # === PULLBACK GATES ===
        # Helper to build a disqualified candidate with score 0
        def _disqualified(reason: str, rsi_reason: str = "") -> PullbackCandidate:
            bd = ScoreBreakdown()
            bd.rsi_value = rsi
            bd.rsi_reason = rsi_reason or reason
            bd.total_score = 0
            bd.max_possible = STRATEGY_SCORE_CONFIGS["pullback"].max_possible
            return PullbackCandidate(
                symbol=symbol,
                current_price=current_price,
                score=0,
                score_breakdown=bd,
                technicals=TechnicalIndicators(
                    rsi_14=rsi,
                    sma_20=sma_20,
                    sma_50=sma_50,
                    sma_200=sma_200,
                    macd=macd_result,
                    stochastic=stoch_result,
                    above_sma20=current_price > sma_20 if sma_20 else False,
                    above_sma50=current_price > sma_50 if sma_50 else None,
                    above_sma200=current_price > sma_200 if sma_200 else False,
                    trend=trend,
                ),
                support_levels=[],
                resistance_levels=[],
                fib_levels={},
                avg_volume=int(np.mean(volumes[-20:])) if len(volumes) >= 20 else 0,
                current_volume=current_volume,
            )

        # Gate 1: RSI overbought — not a pullback, likely reversal
        if rsi is not None and rsi > RSI_OVERBOUGHT:
            return _disqualified(
                f"RSI {rsi:.1f} overbought — not a pullback",
                f"RSI {rsi:.1f} > {RSI_OVERBOUGHT} (overbought, not a pullback)",
            )

        # Gate 2: Must be in uptrend (price above SMA200)
        # A pullback requires a prior uptrend to pull back from.
        # Stocks below SMA200 are in downtrends — those are bounce candidates.
        above_200 = current_price > sma_200 if sma_200 else True
        if not above_200:
            return _disqualified(
                f"Below SMA200 — downtrend, not a pullback",
                f"Price below SMA200 (downtrend, use bounce strategy)",
            )

        # Gate 3: Pullback evidence required when RSI > 50
        # If RSI is not even mildly oversold, we need some sign of a dip
        # (price below SMA20 or near fibonacci). Otherwise it's pure momentum.
        if rsi is not None and rsi > 50:
            has_dip = sma_20 is not None and current_price < sma_20
            if not has_dip:
                return _disqualified(
                    f"RSI {rsi:.1f} with no dip below SMA20 — momentum, not pullback",
                    f"RSI {rsi:.1f} > 50, price above SMA20 (no pullback evidence)",
                )

        # Scoring
        breakdown = ScoreBreakdown()

        # 1. RSI Score (0-3 points) — adaptive threshold based on stability
        # Compute short RSI series for hook detection (last 3 days)
        stability = context.stability_score if context else None
        rsi_series = None
        if len(prices) >= self.config.rsi.period + 4:
            rsi_series = [
                self._calculate_rsi(prices[:-2], self.config.rsi.period),
                self._calculate_rsi(prices[:-1], self.config.rsi.period),
                rsi,
            ]
        breakdown.rsi_score, breakdown.rsi_reason = self._score_rsi(
            rsi, stability, rsi_series=rsi_series
        )
        breakdown.rsi_value = rsi

        # 1b. RSI Divergence (0-3 points) - NEW
        # Bullish divergence is a strong signal for pullback entry
        divergence_result = calculate_rsi_divergence(
            prices=prices,
            lows=lows,
            highs=highs,
            rsi_period=self.config.rsi.period,
            lookback=PULLBACK_DIVERGENCE_LOOKBACK,
            swing_window=PULLBACK_DIVERGENCE_SWING_WINDOW,  # Relaxiert für bessere Swing-Erkennung
            min_divergence_bars=PULLBACK_DIVERGENCE_MIN_BARS,
            max_divergence_bars=PULLBACK_DIVERGENCE_MAX_BARS,  # Längere Formationen erlauben
        )
        div_score_result = self._score_rsi_divergence(divergence_result)
        breakdown.rsi_divergence_score = div_score_result[0]
        breakdown.rsi_divergence_type = (
            divergence_result.divergence_type if divergence_result else None
        )
        breakdown.rsi_divergence_strength = divergence_result.strength if divergence_result else 0
        breakdown.rsi_divergence_formation_days = (
            divergence_result.formation_days if divergence_result else 0
        )
        breakdown.rsi_divergence_reason = div_score_result[1]

        # 2. Support Score with strength rating (0-2.5 points)
        support_result = self._score_support_with_strength(
            current_price, support_levels, volumes, lows
        )
        breakdown.support_score = support_result[0]
        breakdown.support_reason = support_result[1]
        breakdown.support_strength = support_result[2]
        breakdown.support_touches = support_result[3]
        if support_levels:
            nearest = min(support_levels, key=lambda x: abs(x - current_price))
            breakdown.support_level = nearest
            breakdown.support_distance_pct = abs(current_price - nearest) / current_price * 100

        # 3. Fibonacci Score (0-2 points)
        breakdown.fibonacci_score, breakdown.fib_level, breakdown.fib_reason = (
            self._score_fibonacci(current_price, fib_levels)
        )

        # 4. Moving Average Score (0-2 points)
        breakdown.ma_score, breakdown.ma_reason = self._score_moving_averages(
            current_price, sma_20, sma_200
        )
        breakdown.price_vs_sma20 = "above" if above_sma20 else "below"
        breakdown.price_vs_sma200 = "above" if above_sma200 else "below"

        # 5. Trend Strength Score (0-2 points) - NEW
        trend_result = self._score_trend_strength(prices, sma_20, sma_50, sma_200)
        breakdown.trend_strength_score = trend_result[0]
        breakdown.trend_alignment = trend_result[1]
        breakdown.sma20_slope = trend_result[2]
        breakdown.trend_reason = trend_result[3]

        # 6. Volume Score with trend (0-1 point) - IMPROVED
        avg_volume = int(np.mean(volumes[-self.config.volume.average_period :]))
        vol_result = self._score_volume(current_volume, avg_volume)
        breakdown.volume_score = vol_result[0]
        breakdown.volume_reason = vol_result[1]
        breakdown.volume_trend = vol_result[2]
        intraday_scale = self._intraday_volume_scale()
        breakdown.volume_ratio = (
            (current_volume * intraday_scale) / avg_volume if avg_volume > 0 else 0
        )

        warnings = []

        # 7. MACD Score (0-2 points) - NEW
        macd_result_score = self._score_macd(macd_result)
        breakdown.macd_score = macd_result_score[0]
        breakdown.macd_reason = macd_result_score[1]
        breakdown.macd_signal = macd_result_score[2]
        breakdown.macd_histogram = macd_result.histogram if macd_result else 0

        # 8. Stochastic Score (0-2 points)
        stoch_result_score = self._score_stochastic(stoch_result)
        breakdown.stoch_score = stoch_result_score[0]
        breakdown.stoch_reason = stoch_result_score[1]
        breakdown.stoch_signal = stoch_result_score[2]
        breakdown.stoch_k = stoch_result.k if stoch_result else 0
        breakdown.stoch_d = stoch_result.d if stoch_result else 0

        # 9. Keltner Channel Score (0-2 points) - NEW
        keltner_result = self._calculate_keltner_channel(prices, highs, lows)
        if keltner_result:
            keltner_score_result = self._score_keltner(keltner_result, current_price)
            breakdown.keltner_score = keltner_score_result[0]
            breakdown.keltner_reason = keltner_score_result[1]
            breakdown.keltner_position = keltner_result.price_position
            breakdown.keltner_percent = keltner_result.percent_position

        # 10. VWAP Score (0-3 points) - NEW from Feature Engineering
        vwap_result = self._score_vwap(prices, volumes)
        breakdown.vwap_score = vwap_result[0]
        breakdown.vwap_value = vwap_result[1]
        breakdown.vwap_distance_pct = vwap_result[2]
        breakdown.vwap_position = vwap_result[3]
        breakdown.vwap_reason = vwap_result[4]

        # 11. Market Context Score (-1 to +2 points) - NEW from Feature Engineering
        # G.1: Use pre-computed market context if available (avoids redundant SPY SMA computation)
        if context and context.market_context_score is not None:
            breakdown.market_context_score = context.market_context_score
            breakdown.spy_trend = context.market_context_trend or "unknown"
            breakdown.market_context_reason = f"Market: {context.market_context_trend}"
        elif context and hasattr(context, "spy_prices") and context.spy_prices:
            market_result = self._score_market_context(context.spy_prices)
            breakdown.market_context_score = market_result[0]
            breakdown.spy_trend = market_result[1]
            breakdown.market_context_reason = market_result[2]
        else:
            breakdown.market_context_score = 0
            breakdown.spy_trend = "unknown"
            breakdown.market_context_reason = "No SPY data available"

        # 12. Sector Score (-1 to +1 points) - NEW from Feature Engineering
        sector_result = self._score_sector(symbol)
        breakdown.sector_score = sector_result[0]
        breakdown.sector = sector_result[1]
        breakdown.sector_reason = sector_result[2]

        # 13. Candlestick Reversal Score (0-2 points) — Literature alignment
        # Only fires when Support or Fibonacci provides contextual anchor
        candle_result = self._score_candlestick_reversal(
            prices,
            highs,
            lows,
            support_score=breakdown.support_score,
            fibonacci_score=breakdown.fibonacci_score,
        )
        breakdown.candlestick_score = candle_result[0]
        breakdown.candlestick_pattern = candle_result[1]
        breakdown.candlestick_reason = candle_result[2]

        # Gap Score — removed from pullback scoring (Lücke 4: konzeptionell deplatziert)
        # Gap-fill is tracked for display but no longer contributes to score.
        gap_result = self._score_gap(prices, highs, lows, context)
        breakdown.gap_score = 0  # Neutralized — gap doesn't belong in pullback
        breakdown.gap_type = gap_result[1]
        breakdown.gap_size_pct = gap_result[2]
        breakdown.gap_filled = gap_result[3]
        breakdown.gap_reason = f"{gap_result[4]} (not scored in pullback)"

        # E.5: Dividend-Gap-Handling — data-driven when available, heuristic fallback
        # Must run AFTER gap_score is calculated (step 13) so neutralization works
        if context and context.is_near_ex_dividend and len(prices) >= 2:
            overnight_gap_pct = (prices[-1] - prices[-2]) / prices[-2] * 100
            div_amount = context.ex_dividend_amount
            if div_amount and prices[-2] > 0:
                expected_gap_pct = -(div_amount / prices[-2]) * 100
                # If observed gap is within 50% of expected dividend gap, neutralize
                if (
                    overnight_gap_pct < 0
                    and abs(overnight_gap_pct - expected_gap_pct) < abs(expected_gap_pct) * 0.5
                ):
                    breakdown.gap_score = 0.0
                    warnings.append(
                        f"Dividend gap neutralized (${div_amount:.2f}, gap {overnight_gap_pct:.1f}%)"
                    )
                else:
                    warnings.append(
                        f"Near ex-dividend (${div_amount:.2f}) but gap {overnight_gap_pct:.1f}% doesn't match"
                    )
            else:
                warnings.append("Near ex-dividend date (amount unknown)")
        elif len(prices) >= 2 and avg_volume > 0:
            # Heuristic fallback when no dividend data available
            overnight_gap_pct = (prices[-1] - prices[-2]) / prices[-2] * 100
            vol_ratio = current_volume / avg_volume
            if (
                PULLBACK_GAP_WARNING_MIN <= overnight_gap_pct <= PULLBACK_GAP_WARNING_MAX
                and vol_ratio < PULLBACK_GAP_VOL_THRESHOLD
            ):
                warnings.append(
                    f"Potential dividend gap ({overnight_gap_pct:.1f}%, vol {vol_ratio:.1f}x)"
                )

        # Resolve weights from config (4-layer: Base -> Regime -> Sector -> Regime x Sector)
        regime = getattr(context, "regime", "normal") if context else "normal"
        sector = getattr(context, "sector", None) if context else None
        try:
            resolved = self.get_weights(regime=regime, sector=sector)
            w = resolved.weights
        except (KeyError, AttributeError, ImportError):
            w = {}

        # Default max weights per component
        # Lücke 2: VWAP 3.0→1.5 (intraday indicator, less relevant for swing trades)
        #          Support 2.5→3.0, Fibonacci 2.0→2.5 (literature alignment)
        # Lücke 1: Candlestick added (max 2.0)
        # Lücke 4: Gap removed from scoring
        _DEFAULTS = {
            "rsi": 3.0,
            "rsi_divergence": 3.0,
            "support": 3.0,
            "fibonacci": 2.5,
            "ma": 2.0,
            "trend_strength": 2.0,
            "volume": 1.0,
            "macd": 2.0,
            "stoch": 2.0,
            "keltner": 2.0,
            "vwap": 1.5,
            "market_context": 2.0,
            "sector": 1.0,
            "candlestick": 2.0,
        }

        def _scale(component: str, raw: float) -> float:
            """Scale a component score by the ratio of YAML weight to hardcoded default."""
            yaml_max = w.get(component)
            if yaml_max is None:
                return raw
            default_max = _DEFAULTS.get(component, 1.0)
            if default_max <= 0:
                return raw
            return raw * (yaml_max / default_max)

        def _max_weight(component: str) -> float:
            """Get the max weight for a component (YAML or default)."""
            return w.get(component, _DEFAULTS.get(component, 1.0))

        # Score each component and track which ones contributed positively
        # Note: gap removed from scoring (Lücke 4), candlestick added (Lücke 1)
        _components = {
            "rsi": breakdown.rsi_score,
            "rsi_divergence": breakdown.rsi_divergence_score,
            "support": breakdown.support_score,
            "fibonacci": breakdown.fibonacci_score,
            "ma": breakdown.ma_score,
            "trend_strength": breakdown.trend_strength_score,
            "volume": breakdown.volume_score,
            "macd": breakdown.macd_score,
            "stoch": breakdown.stoch_score,
            "keltner": breakdown.keltner_score,
            "vwap": breakdown.vwap_score,
            "market_context": breakdown.market_context_score,
            "sector": breakdown.sector_score,
            "candlestick": breakdown.candlestick_score,
        }

        # Total Score with config-based weight scaling
        breakdown.total_score = sum(_scale(k, v) for k, v in _components.items())

        # Apply sector_factor as multiplicative adjustment (Iter 4 trained)
        if w and resolved.sector_factor != 1.0:
            breakdown.total_score *= resolved.sector_factor

        # Bearish divergence penalties (additive to existing RSI divergence check above)
        breakdown.total_score = self._apply_divergence_penalties(
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            score=breakdown.total_score,
        )

        # Earnings-surprise modifier (additive, after divergence penalties)
        from ..services.earnings_quality import get_earnings_surprise_modifier  # noqa: PLC0415
        breakdown.total_score += get_earnings_surprise_modifier(symbol)

        # Dynamic max_possible: sum of max weights for components that scored > 0.
        # This prevents components that are structurally impossible during a pullback
        # (e.g., MACD bullish cross, VWAP strong above) from diluting the score.
        # A minimum of 3 active components is required to avoid inflated scores
        # from a single lucky indicator.
        # Floor at 50% of full max to prevent score inflation with few components.
        full_max = resolved.max_possible if w else STRATEGY_SCORE_CONFIGS["pullback"].max_possible
        active_maxes = [_max_weight(k) for k, v in _components.items() if v > 0]
        if len(active_maxes) >= 3:
            dynamic_max = sum(active_maxes)
            # Cap at effective_max to prevent score compression from many weak components
            effective_max = _cfg.get("pullback.effective_max", 14.0)
            breakdown.max_possible = min(max(dynamic_max, full_max * 0.5), effective_max)
        else:
            breakdown.max_possible = full_max

        return PullbackCandidate(
            symbol=symbol,
            current_price=current_price,
            score=breakdown.total_score,
            score_breakdown=breakdown,
            technicals=technicals,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            fib_levels=fib_levels,
            avg_volume=avg_volume,
            current_volume=current_volume,
            warnings=warnings,
        )

    def _build_reason(self, candidate: PullbackCandidate) -> str:
        """Creates reasoning from score breakdown (extended for new components)"""
        reasons = []
        bd = candidate.score_breakdown

        # RSI
        if bd.rsi_score > 0:
            reasons.append(f"RSI oversold ({candidate.technicals.rsi_14:.1f})")

        # RSI Divergence (NEW)
        if bd.rsi_divergence_score >= 2:
            reasons.append(f"RSI Bullish Divergence (strength: {bd.rsi_divergence_strength:.0%})")
        elif bd.rsi_divergence_score > 0:
            reasons.append("RSI Divergence detected")

        # Support mit Stärke
        if bd.support_score > 0:
            if bd.support_strength == "strong":
                reasons.append(f"Near strong support ({bd.support_touches} touches)")
            elif bd.support_strength == "moderate":
                reasons.append("Near moderate support")
            else:
                reasons.append("Near support")

        # Trend Strength
        if bd.trend_strength_score > 0:
            if bd.trend_alignment == "strong":
                reasons.append("Strong uptrend")
            else:
                reasons.append("Uptrend")

        # MA-Score (Dip in uptrend)
        if bd.ma_score > 0:
            reasons.append("Dip in uptrend")

        # Fibonacci
        if bd.fibonacci_score > 0:
            reasons.append(f"At Fib {bd.fib_level}")

        # MACD (NEW)
        if bd.macd_score >= 2:
            reasons.append("MACD bullish cross")
        elif bd.macd_score > 0:
            reasons.append("MACD bullish")

        # Stochastic (NEW)
        if bd.stoch_score >= 2:
            reasons.append("Stoch oversold + cross")
        elif bd.stoch_score > 0:
            reasons.append("Stoch oversold")

        # Volume
        if bd.volume_score > 0:
            reasons.append("Healthy low volume")

        # Keltner Channel (NEW)
        if bd.keltner_score >= 2:
            reasons.append("Below Keltner lower band")
        elif bd.keltner_score > 0:
            reasons.append("Near Keltner lower band")

        # VWAP (NEW from Feature Engineering)
        if bd.vwap_score >= 3:
            reasons.append(f"Strong VWAP momentum (+{bd.vwap_distance_pct:.1f}%)")
        elif bd.vwap_score >= 2:
            reasons.append(f"Above VWAP ({bd.vwap_distance_pct:+.1f}%)")
        elif bd.vwap_score >= 1:
            reasons.append("Near VWAP")

        # Market Context (NEW from Feature Engineering)
        if bd.market_context_score >= 2:
            reasons.append("Strong market uptrend")
        elif bd.market_context_score >= 1:
            reasons.append("Market uptrend")
        elif bd.market_context_score < 0:
            reasons.append(f"Market downtrend (CAUTION)")

        # Sector (NEW from Feature Engineering)
        if bd.sector_score >= 0.5:
            reasons.append(f"{bd.sector} (favorable)")
        elif bd.sector_score <= -0.5:
            reasons.append(f"{bd.sector} (challenging)")

        # Gap (NEW - validated with 174k+ events)
        if bd.gap_score >= 0.5:
            reasons.append(f"Down-gap entry ({bd.gap_size_pct:.1f}%)")
        elif bd.gap_score > 0:
            reasons.append(f"Small down-gap")
        elif bd.gap_score <= -0.3:
            reasons.append(f"Up-gap caution")

        return " | ".join(reasons) if reasons else "Weak setup"

    def _validate_inputs(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
    ) -> None:
        """Validates all input arrays for consistency and validity."""
        arrays = {"prices": prices, "volumes": volumes, "highs": highs, "lows": lows}
        lengths = {name: len(arr) for name, arr in arrays.items()}
        unique_lengths = set(lengths.values())

        if len(unique_lengths) != 1:
            raise ValueError(
                f"All input arrays must have same length. Got: "
                f"{', '.join(f'{k}={v}' for k, v in lengths.items())}"
            )

        if len(prices) == 0:
            raise ValueError("Input arrays cannot be empty")

        for name, arr in [("prices", prices), ("highs", highs), ("lows", lows)]:
            if any(v is None for v in arr):
                raise ValueError(f"{name} contains None values")

        if any(p <= 0 for p in prices):
            raise ValueError("All prices must be positive (> 0)")

        invalid_bars = [(i, h, l) for i, (h, l) in enumerate(zip(highs, lows)) if h < l]
        if invalid_bars:
            first_invalid = invalid_bars[0]
            raise ValueError(
                f"High must be >= Low. First violation at index {first_invalid[0]}: "
                f"high={first_invalid[1]}, low={first_invalid[2]}"
            )

        tolerance = 0.0001
        for i, (p, h, l) in enumerate(zip(prices, highs, lows)):
            if p > h * (1 + tolerance) or p < l * (1 - tolerance):
                logger.warning(
                    f"{symbol}: Close price {p} outside High/Low range " f"[{l}, {h}] at index {i}"
                )

    # =========================================================================
    # INDICATORS - CALCULATION
    # =========================================================================

    def _calculate_rsi(self, prices: List[float], period: int) -> float:
        """RSI mit Wilder's Smoothing"""
        if len(prices) < period + 1:
            return 50.0

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """Simple Moving Average"""
        if len(prices) < period:
            return prices[-1]
        return float(np.mean(prices[-period:]))

    def _calculate_ema(self, prices: List[float], period: int) -> List[float]:
        """Calculates EMA. Delegates to shared indicators library."""
        return calculate_ema(prices, period)

    def _calculate_macd(self, prices: List[float]) -> Optional[MACDResult]:
        """Calculates MACD. Delegates to shared indicators library."""
        return calculate_macd(
            prices,
            fast_period=self.MACD_FAST,
            slow_period=self.MACD_SLOW,
            signal_period=self.MACD_SIGNAL,
        )

    def _calculate_stochastic(
        self, highs: List[float], lows: List[float], closes: List[float]
    ) -> Optional[StochasticResult]:
        """Calculates Stochastic Oscillator. Delegates to shared indicators library."""
        return calculate_stochastic(
            highs=highs,
            lows=lows,
            closes=closes,
            k_period=self.STOCH_K,
            d_period=self.STOCH_D,
            smooth=self.STOCH_SMOOTH,
            oversold=self.STOCH_OVERSOLD,
            overbought=self.STOCH_OVERBOUGHT,
        )

    def _calculate_fibonacci(self, high: float, low: float) -> Dict[str, float]:
        """Fibonacci Retracement Levels"""
        diff = high - low
        return {
            "0.0%": high,
            "23.6%": high - diff * 0.236,
            "38.2%": high - diff * 0.382,
            "50.0%": high - diff * 0.5,
            "61.8%": high - diff * 0.618,
            "78.6%": high - diff * 0.786,
            "100.0%": low,
        }

    def _apply_divergence_penalties(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[int],
        score: float,
    ) -> float:
        """Apply bearish divergence penalties to the pullback score.

        Runs all 7 divergence checks and sums detected penalties.
        Applied AFTER main scoring (including the existing bullish RSI divergence
        check in _score_rsi_divergence), BEFORE normalization to 0-10 scale.

        Note: The existing calculate_rsi_divergence call above checks for BULLISH
        divergence (a positive signal for pullback entries). This method checks for
        BEARISH divergence (a negative signal indicating selling pressure). Both
        can coexist without conflict.

        Returns:
            Adjusted score (may be lower than input if divergences detected).
        """
        signals = [
            check_price_rsi_divergence(
                prices=prices,
                lows=lows,
                highs=highs,
                severity=PULLBACK_DIV_PENALTY_PRICE_RSI,
            ),
            check_price_obv_divergence(
                prices=prices,
                volumes=volumes,
                severity=PULLBACK_DIV_PENALTY_PRICE_OBV,
            ),
            check_price_mfi_divergence(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=PULLBACK_DIV_PENALTY_PRICE_MFI,
            ),
            check_cmf_and_macd_falling(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=PULLBACK_DIV_PENALTY_CMF_MACD,
            ),
            check_momentum_divergence(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=PULLBACK_DIV_PENALTY_MOMENTUM,
            ),
            check_distribution_pattern(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=PULLBACK_DIV_PENALTY_DISTRIBUTION,
            ),
            check_cmf_early_warning(
                prices=prices,
                highs=highs,
                lows=lows,
                volumes=volumes,
                severity=PULLBACK_DIV_PENALTY_CMF_EARLY,
            ),
        ]

        total_penalty = sum(sig.severity for sig in signals if sig.detected)
        if total_penalty < 0:
            logger.debug(
                "PullbackAnalyzer: bearish divergence penalties applied: %.2f", total_penalty
            )
        return score + total_penalty
