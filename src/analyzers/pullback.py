# OptionPlay - Pullback Analyzer
# ================================
# Technical analysis for pullback candidates
#
# Scoring methods are in pullback_scoring.py (PullbackScoringMixin).

import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import logging

from .base import BaseAnalyzer
from .context import AnalysisContext
from .pullback_scoring import PullbackScoringMixin
from .score_normalization import normalize_score, get_signal_strength, STRATEGY_SCORE_CONFIGS

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..models.indicators import MACDResult, StochasticResult, TechnicalIndicators, KeltnerChannelResult, RSIDivergenceResult
    from ..models.candidates import PullbackCandidate, ScoreBreakdown
    from ..config import PullbackScoringConfig
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength
    from models.indicators import MACDResult, StochasticResult, TechnicalIndicators, KeltnerChannelResult, RSIDivergenceResult
    from models.candidates import PullbackCandidate, ScoreBreakdown
    from config import PullbackScoringConfig

# Import shared indicators
try:
    from ..indicators.momentum import calculate_rsi_divergence, calculate_macd, calculate_stochastic
    from ..indicators.trend import calculate_ema
except ImportError:
    from indicators.momentum import calculate_rsi_divergence, calculate_macd, calculate_stochastic
    from indicators.trend import calculate_ema

# Import central constants (with alias to avoid naming conflicts)
try:
    from ..constants import (
        MACD_FAST as _MACD_FAST,
        MACD_SLOW as _MACD_SLOW,
        MACD_SIGNAL as _MACD_SIGNAL,
        STOCH_K_PERIOD as _STOCH_K,
        STOCH_D_PERIOD as _STOCH_D,
        STOCH_SMOOTH as _STOCH_SMOOTH,
        STOCH_OVERSOLD as _STOCH_OVERSOLD,
        STOCH_OVERBOUGHT as _STOCH_OVERBOUGHT,
        RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
        SMA_SHORT, SMA_MEDIUM, SMA_LONG,
        FIB_LEVELS, FIB_LOOKBACK_DAYS,
        SUPPORT_LOOKBACK_DAYS, SUPPORT_WINDOW, SUPPORT_MAX_LEVELS, SUPPORT_TOLERANCE_PCT,
        VOLUME_AVG_PERIOD, VOLUME_SPIKE_MULTIPLIER,
        KELTNER_ATR_MULTIPLIER, KELTNER_LOWER_THRESHOLD, KELTNER_NEUTRAL_LOW,
        DIVERGENCE_SWING_WINDOW, DIVERGENCE_MIN_BARS, DIVERGENCE_MAX_BARS,
        VWAP_PERIOD, VWAP_STRONG_ABOVE, VWAP_ABOVE, VWAP_BELOW, VWAP_STRONG_BELOW,
        GAP_LOOKBACK_DAYS, GAP_SIZE_LARGE, GAP_SIZE_MEDIUM, GAP_SIZE_SMALL_NEG, GAP_SIZE_LARGE_NEG,
        PRICE_TOLERANCE,
    )
except ImportError:
    # Fallback for direct execution
    from constants import (
        MACD_FAST as _MACD_FAST,
        MACD_SLOW as _MACD_SLOW,
        MACD_SIGNAL as _MACD_SIGNAL,
        STOCH_K_PERIOD as _STOCH_K,
        STOCH_D_PERIOD as _STOCH_D,
        STOCH_SMOOTH as _STOCH_SMOOTH,
        STOCH_OVERSOLD as _STOCH_OVERSOLD,
        STOCH_OVERBOUGHT as _STOCH_OVERBOUGHT,
        RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
        SMA_SHORT, SMA_MEDIUM, SMA_LONG,
        FIB_LEVELS, FIB_LOOKBACK_DAYS,
        SUPPORT_LOOKBACK_DAYS, SUPPORT_WINDOW, SUPPORT_MAX_LEVELS, SUPPORT_TOLERANCE_PCT,
        VOLUME_AVG_PERIOD, VOLUME_SPIKE_MULTIPLIER,
        KELTNER_ATR_MULTIPLIER, KELTNER_LOWER_THRESHOLD, KELTNER_NEUTRAL_LOW,
        DIVERGENCE_SWING_WINDOW, DIVERGENCE_MIN_BARS, DIVERGENCE_MAX_BARS,
        VWAP_PERIOD, VWAP_STRONG_ABOVE, VWAP_ABOVE, VWAP_BELOW, VWAP_STRONG_BELOW,
        GAP_LOOKBACK_DAYS, GAP_SIZE_LARGE, GAP_SIZE_MEDIUM, GAP_SIZE_SMALL_NEG, GAP_SIZE_LARGE_NEG,
        PRICE_TOLERANCE,
    )

# Import optimized support/resistance functions
try:
    from ..indicators.support_resistance import (
        find_support_levels as find_support_optimized,
        find_resistance_levels as find_resistance_optimized,
    )
except ImportError:
    from indicators.support_resistance import (
        find_support_levels as find_support_optimized,
        find_resistance_levels as find_resistance_optimized,
    )

logger = logging.getLogger(__name__)


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
    MACD_FAST = _MACD_FAST       # 12 - Fast EMA
    MACD_SLOW = _MACD_SLOW       # 26 - Slow EMA
    MACD_SIGNAL = _MACD_SIGNAL   # 9  - Signal Line

    # Stochastic Default Parameters (from src/constants)
    STOCH_K = _STOCH_K            # 14
    STOCH_D = _STOCH_D            # 3
    STOCH_SMOOTH = _STOCH_SMOOTH  # 3
    STOCH_OVERSOLD = _STOCH_OVERSOLD   # 20
    STOCH_OVERBOUGHT = _STOCH_OVERBOUGHT  # 80

    def __init__(self, config: PullbackScoringConfig):
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
        **kwargs
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
        max_possible = candidate.score_breakdown.max_possible if hasattr(candidate.score_breakdown, 'max_possible') else 26
        normalized_score = (candidate.score / max_possible) * 10 if max_possible > 0 else 0

        # Convert to TradeSignal (based on normalized 0-10 scale)
        if normalized_score >= 3.5:
            signal_type = SignalType.LONG
            if normalized_score >= 7:
                strength = SignalStrength.STRONG
            elif normalized_score >= 5:
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
            nearest_support = min(candidate.support_levels,
                                  key=lambda x: abs(x - entry_price))
            stop_loss = nearest_support * 0.98  # 2% unter Support

            # Target at next resistance or 2:1 R/R
            if candidate.resistance_levels:
                target_price = min(candidate.resistance_levels,
                                   key=lambda x: x if x > entry_price else float('inf'))

            if not target_price or target_price <= entry_price:
                # Fallback: 2:1 Risk/Reward
                risk = entry_price - stop_loss
                target_price = entry_price + (risk * 2)

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
                'rsi': candidate.technicals.rsi_14,
                'trend': candidate.technicals.trend,
                'support_levels': candidate.support_levels,
                'score_breakdown': candidate.score_breakdown.to_dict(),
                'raw_score': candidate.score,
                'max_possible': max_possible
            }
        )

    def analyze_detailed(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        context: Optional[AnalysisContext] = None
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
                macd_result = MACDResult(
                    macd_line=context.macd_line,
                    signal_line=context.macd_signal,
                    histogram=context.macd_histogram,
                    bullish_cross=context.macd_histogram > 0 if context.macd_histogram else False,
                    bearish_cross=context.macd_histogram < 0 if context.macd_histogram else False
                )
            else:
                macd_result = self._calculate_macd(prices)

            # Stochastic
            if context.stoch_k is not None:
                stoch_result = StochasticResult(
                    k=context.stoch_k,
                    d=context.stoch_d,
                    oversold=context.stoch_k < self.STOCH_OVERSOLD,
                    overbought=context.stoch_k > self.STOCH_OVERBOUGHT
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
                trend = 'uptrend'
            elif not above_sma200 and not above_sma20:
                trend = 'downtrend'
            else:
                trend = 'sideways'

            # Support/Resistance (using optimized O(n) algorithm)
            support_levels = find_support_optimized(
                lows=lows,
                lookback=self.config.support.lookback_days,
                window=5,
                max_levels=5,
                volumes=volumes if volumes else None,
                tolerance_pct=1.5
            )
            resistance_levels = find_resistance_optimized(
                highs=highs,
                lookback=60,
                window=5,
                max_levels=5,
                volumes=volumes if volumes else None,
                tolerance_pct=1.5
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
            trend=trend
        )

        # Fibonacci
        lookback = self.config.fibonacci.lookback_days
        fib_levels = self._calculate_fibonacci(
            max(highs[-lookback:]),
            min(lows[-lookback:])
        )

        # Scoring
        breakdown = ScoreBreakdown()

        # 1. RSI Score (0-3 points)
        breakdown.rsi_score, breakdown.rsi_reason = self._score_rsi(rsi)
        breakdown.rsi_value = rsi

        # 1b. RSI Divergence (0-3 points) - NEW
        # Bullish divergence is a strong signal for pullback entry
        divergence_result = calculate_rsi_divergence(
            prices=prices,
            lows=lows,
            highs=highs,
            rsi_period=self.config.rsi.period,
            lookback=60,
            swing_window=3,  # Relaxiert für bessere Swing-Erkennung
            min_divergence_bars=5,
            max_divergence_bars=50  # Längere Formationen erlauben
        )
        div_score_result = self._score_rsi_divergence(divergence_result)
        breakdown.rsi_divergence_score = div_score_result[0]
        breakdown.rsi_divergence_type = divergence_result.divergence_type if divergence_result else None
        breakdown.rsi_divergence_strength = divergence_result.strength if divergence_result else 0
        breakdown.rsi_divergence_formation_days = divergence_result.formation_days if divergence_result else 0
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
        breakdown.fibonacci_score, breakdown.fib_level, breakdown.fib_reason = \
            self._score_fibonacci(current_price, fib_levels)

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
        avg_volume = int(np.mean(volumes[-self.config.volume.average_period:]))
        vol_result = self._score_volume(current_volume, avg_volume)
        breakdown.volume_score = vol_result[0]
        breakdown.volume_reason = vol_result[1]
        breakdown.volume_trend = vol_result[2]
        breakdown.volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        # E.5: Detect potential dividend gap (warning only, no score penalty)
        warnings = []
        if len(prices) >= 2 and avg_volume > 0:
            overnight_gap_pct = (prices[-1] - prices[-2]) / prices[-2] * 100
            vol_ratio = current_volume / avg_volume
            if -3.0 <= overnight_gap_pct <= -1.0 and vol_ratio < 0.8:
                warnings.append(
                    f"Potential dividend gap ({overnight_gap_pct:.1f}%, vol {vol_ratio:.1f}x)"
                )

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
        # Note: spy_prices should be passed via context in production
        # For now, we'll skip if no context provided
        if context and hasattr(context, 'spy_prices') and context.spy_prices:
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

        # 13. Gap Score (0-1 für down-gaps, -0.5 bis 0 für up-gaps) - Validated with 174k+ events
        gap_result = self._score_gap(prices, highs, lows, context)
        breakdown.gap_score = gap_result[0]
        breakdown.gap_type = gap_result[1]
        breakdown.gap_size_pct = gap_result[2]
        breakdown.gap_filled = gap_result[3]
        breakdown.gap_reason = gap_result[4]

        # Resolve weights from config (4-layer: Base -> Regime -> Sector -> Regime x Sector)
        regime = getattr(context, 'regime', 'normal') if context else 'normal'
        sector = getattr(context, 'sector', None) if context else None
        try:
            resolved = self.get_weights(regime=regime, sector=sector)
            w = resolved.weights
        except Exception:
            w = {}

        # Default max weights per component (used when YAML weight matches original)
        _DEFAULTS = {
            'rsi': 3.0, 'rsi_divergence': 3.0, 'support': 2.5, 'fibonacci': 2.0,
            'ma': 2.0, 'trend_strength': 2.0, 'volume': 1.0, 'macd': 2.0,
            'stoch': 2.0, 'keltner': 2.0, 'vwap': 3.0, 'market_context': 2.0,
            'sector': 1.0, 'gap': 1.0,
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

        # Total Score with config-based weight scaling
        breakdown.total_score = (
            _scale('rsi', breakdown.rsi_score) +
            _scale('rsi_divergence', breakdown.rsi_divergence_score) +
            _scale('support', breakdown.support_score) +
            _scale('fibonacci', breakdown.fibonacci_score) +
            _scale('ma', breakdown.ma_score) +
            _scale('trend_strength', breakdown.trend_strength_score) +
            _scale('volume', breakdown.volume_score) +
            _scale('macd', breakdown.macd_score) +
            _scale('stoch', breakdown.stoch_score) +
            _scale('keltner', breakdown.keltner_score) +
            _scale('vwap', breakdown.vwap_score) +
            _scale('market_context', breakdown.market_context_score) +
            _scale('sector', breakdown.sector_score) +
            _scale('gap', breakdown.gap_score)
        )

        # Apply sector_factor as multiplicative adjustment (Iter 4 trained)
        if w and resolved.sector_factor != 1.0:
            breakdown.total_score *= resolved.sector_factor

        # Use resolved max_possible from config, fallback to hardcoded
        if w:
            breakdown.max_possible = resolved.max_possible
        else:
            breakdown.max_possible = STRATEGY_SCORE_CONFIGS['pullback'].max_possible

        # Normalize score to 0-10 scale for fair cross-strategy comparison
        normalized_score = normalize_score(
            breakdown.total_score, 'pullback',
            max_possible=breakdown.max_possible,
        )

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
        lows: List[float]
    ) -> None:
        """Validates all input arrays for consistency and validity."""
        arrays = {'prices': prices, 'volumes': volumes, 'highs': highs, 'lows': lows}
        lengths = {name: len(arr) for name, arr in arrays.items()}
        unique_lengths = set(lengths.values())

        if len(unique_lengths) != 1:
            raise ValueError(
                f"All input arrays must have same length. Got: "
                f"{', '.join(f'{k}={v}' for k, v in lengths.items())}"
            )

        if len(prices) == 0:
            raise ValueError("Input arrays cannot be empty")

        for name, arr in [('prices', prices), ('highs', highs), ('lows', lows)]:
            if any(v is None for v in arr):
                raise ValueError(f"{name} contains None values")

        if any(p <= 0 for p in prices):
            raise ValueError("All prices must be positive (> 0)")

        invalid_bars = [
            (i, h, l) for i, (h, l) in enumerate(zip(highs, lows))
            if h < l
        ]
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
                    f"{symbol}: Close price {p} outside High/Low range "
                    f"[{l}, {h}] at index {i}"
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
            signal_period=self.MACD_SIGNAL
        )

    def _calculate_stochastic(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float]
    ) -> Optional[StochasticResult]:
        """Calculates Stochastic Oscillator. Delegates to shared indicators library."""
        return calculate_stochastic(
            highs=highs, lows=lows, closes=closes,
            k_period=self.STOCH_K, d_period=self.STOCH_D,
            smooth=self.STOCH_SMOOTH,
            oversold=self.STOCH_OVERSOLD, overbought=self.STOCH_OVERBOUGHT
        )

    def _calculate_fibonacci(self, high: float, low: float) -> Dict[str, float]:
        """Fibonacci Retracement Levels"""
        diff = high - low
        return {
            '0.0%': high,
            '23.6%': high - diff * 0.236,
            '38.2%': high - diff * 0.382,
            '50.0%': high - diff * 0.5,
            '61.8%': high - diff * 0.618,
            '78.6%': high - diff * 0.786,
            '100.0%': low
        }
