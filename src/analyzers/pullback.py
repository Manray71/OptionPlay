# OptionPlay - Pullback Analyzer
# ================================
# Technical analysis for pullback candidates

import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import logging

from .base import BaseAnalyzer
from .context import AnalysisContext
from .feature_scoring_mixin import FeatureScoringMixin
from .score_normalization import normalize_score, get_signal_strength, STRATEGY_SCORE_CONFIGS

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..models.indicators import MACDResult, StochasticResult, TechnicalIndicators, KeltnerChannelResult, RSIDivergenceResult
    from ..models.candidates import PullbackCandidate, ScoreBreakdown
    from ..config.config_loader import PullbackScoringConfig
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength
    from models.indicators import MACDResult, StochasticResult, TechnicalIndicators, KeltnerChannelResult, RSIDivergenceResult
    from models.candidates import PullbackCandidate, ScoreBreakdown
    from config.config_loader import PullbackScoringConfig

# Import shared indicators
try:
    from ..indicators.momentum import calculate_rsi, calculate_rsi_divergence, calculate_macd, calculate_stochastic
    from ..indicators.trend import calculate_ema, calculate_sma
    from ..indicators.volatility import calculate_atr_simple, calculate_keltner_channel
except ImportError:
    from indicators.momentum import calculate_rsi, calculate_rsi_divergence, calculate_macd, calculate_stochastic
    from indicators.trend import calculate_ema, calculate_sma
    from indicators.volatility import calculate_atr_simple, calculate_keltner_channel

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
        FIB_LEVELS, FIB_LOOKBACK_DAYS,
        SUPPORT_LOOKBACK_DAYS, SUPPORT_WINDOW, SUPPORT_MAX_LEVELS, SUPPORT_TOLERANCE_PCT,
        VOLUME_AVG_PERIOD, VOLUME_SPIKE_MULTIPLIER,
        KELTNER_ATR_MULTIPLIER, KELTNER_LOWER_THRESHOLD, KELTNER_NEUTRAL_LOW,
        DIVERGENCE_SWING_WINDOW, DIVERGENCE_MIN_BARS, DIVERGENCE_MAX_BARS,
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
        FIB_LEVELS, FIB_LOOKBACK_DAYS,
        SUPPORT_LOOKBACK_DAYS, SUPPORT_WINDOW, SUPPORT_MAX_LEVELS, SUPPORT_TOLERANCE_PCT,
        VOLUME_AVG_PERIOD, VOLUME_SPIKE_MULTIPLIER,
        KELTNER_ATR_MULTIPLIER, KELTNER_LOWER_THRESHOLD, KELTNER_NEUTRAL_LOW,
        DIVERGENCE_SWING_WINDOW, DIVERGENCE_MIN_BARS, DIVERGENCE_MAX_BARS,
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

# Import Gap Analysis (validated with 174k+ events)
try:
    from ..indicators.gap_analysis import analyze_gap
except ImportError:
    from indicators.gap_analysis import analyze_gap

logger = logging.getLogger(__name__)


class PullbackAnalyzer(BaseAnalyzer, FeatureScoringMixin):
    """
    Analyzes stocks for pullback setups.

    Indicators:
    - RSI (14) - Oversold/Overbought
    - MACD (12, 26, 9) - Trend & Momentum
    - Stochastic (14, 3, 3) - Overbought/Oversold
    - SMAs (20, 50, 200) - Trend
    - Support/Resistance - Swing Highs/Lows
    - Fibonacci Retracements
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

        # Total Score (max ~26 points)
        breakdown.total_score = (
            breakdown.rsi_score +           # 0-3
            breakdown.rsi_divergence_score + # 0-3
            breakdown.support_score +       # 0-2.5
            breakdown.fibonacci_score +     # 0-2
            breakdown.ma_score +            # 0-2
            breakdown.trend_strength_score + # 0-2
            breakdown.volume_score +        # 0-1
            breakdown.macd_score +          # 0-2
            breakdown.stoch_score +         # 0-2
            breakdown.keltner_score +       # 0-2
            breakdown.vwap_score +          # 0-3
            breakdown.market_context_score + # -1 to +2
            breakdown.sector_score +        # -1 to +1
            breakdown.gap_score             # 0 to +1 (NEW - validated)
        )
        breakdown.max_possible = STRATEGY_SCORE_CONFIGS['pullback'].max_possible

        # Normalize score to 0-10 scale for fair cross-strategy comparison
        normalized_score = normalize_score(breakdown.total_score, 'pullback')

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
            current_volume=current_volume
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
        """RSI mit Wilder's Smoothing. Delegates to indicators.momentum."""
        return calculate_rsi(prices, period)
    
    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """Simple Moving Average. Delegates to indicators.trend."""
        return calculate_sma(prices, period)
    
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
    
    # =========================================================================
    # SCORING
    # =========================================================================

    def _score_rsi_divergence(
        self,
        divergence: Optional[RSIDivergenceResult]
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

        if divergence.divergence_type == 'bullish':
            # Scoring based on divergence strength
            strength = divergence.strength

            if strength >= 0.7:
                score = 3.0
                reason = f"Strong bullish divergence (strength: {strength:.0%}, {divergence.formation_days} days)"
            elif strength >= 0.4:
                score = 2.0
                reason = f"Moderate bullish divergence (strength: {strength:.0%}, {divergence.formation_days} days)"
            else:
                score = 1.0
                reason = f"Weak bullish divergence (strength: {strength:.0%}, {divergence.formation_days} days)"

            return score, reason

        elif divergence.divergence_type == 'bearish':
            # Bearish divergence in pullback = warning signal, but no deduction
            return 0, f"Bearish divergence detected - caution! (strength: {divergence.strength:.0%})"

        return 0, "No significant divergence"

    def _score_rsi(self, rsi: float) -> Tuple[float, str]:
        """RSI Score (0-3 points)"""
        cfg = self.config.rsi
        
        if rsi < cfg.extreme_oversold:
            return cfg.weight_extreme, f"RSI {rsi:.1f} < {cfg.extreme_oversold} (extreme oversold)"
        elif rsi < cfg.oversold:
            return cfg.weight_oversold, f"RSI {rsi:.1f} < {cfg.oversold} (oversold)"
        elif rsi < cfg.neutral:
            return cfg.weight_neutral, f"RSI {rsi:.1f} < {cfg.neutral} (neutral-low)"
        else:
            return 0, f"RSI {rsi:.1f} >= {cfg.neutral} (not oversold)"
    
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
            return cfg.weight_near, f"Within {cfg.proximity_percent_wide}% of support ${nearest:.2f}"
        else:
            return 0, f"{distance_pct:.1f}% from nearest support"
    
    def _score_fibonacci(
        self,
        price: float,
        fib_levels: Dict[str, float]
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
        sma_200: float
    ) -> Tuple[float, str]:
        """Moving Average Score (0-2 points)"""
        if price > sma_200 and price < sma_20:
            return 2, "Dip in uptrend (price > SMA200, < SMA20)"
        elif price > sma_200 and price > sma_20:
            return 0, "Strong uptrend, no pullback"
        elif price < sma_200:
            return 0, "Below SMA200, no primary uptrend"
        
        return 0, "MA config doesn't indicate pullback"
    
    def _score_volume(self, current: int, average: int) -> Tuple[float, str, str]:
        """
        Volume Score (0-1 point)

        NEW: Decreasing volume during pullback = healthy (no panic selling)
        """
        if average == 0:
            return 0, "No average volume data", "unknown"

        ratio = current / average
        cfg = self.config.volume

        # NEW: Decreasing volume is POSITIVE during a pullback
        if ratio < cfg.decrease_threshold:
            return cfg.weight_decreasing, f"Low volume pullback: {ratio:.1f}x avg (healthy)", "decreasing"
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

        if macd.crossover == 'bullish':
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

        if stoch.zone == 'oversold':
            if stoch.crossover == 'bullish':
                return cfg.weight_oversold_cross, f"Stoch oversold ({stoch.k:.0f}) + bullish cross", "oversold_bullish_cross"
            return cfg.weight_oversold, f"Stoch oversold ({stoch.k:.0f})", "oversold"
        elif stoch.zone == 'overbought':
            return 0, f"Stoch overbought ({stoch.k:.0f})", "overbought"

        return 0, f"Stoch neutral ({stoch.k:.0f})", "neutral"

    def _score_trend_strength(
        self,
        prices: List[float],
        sma_20: float,
        sma_50: Optional[float],
        sma_200: float
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
            sma20_older = sum(prices[-20-slope_lookback:-slope_lookback]) / 20 if len(prices) >= 20 + slope_lookback else sma20_recent
            sma20_slope = (sma20_recent - sma20_older) / sma20_older if sma20_older > 0 else 0
        else:
            sma20_slope = 0

        # Check SMA alignment
        if sma_50 is not None:
            # Full alignment: SMA20 > SMA50 > SMA200
            if sma_20 > sma_50 > sma_200 and current_price > sma_200:
                if sma20_slope >= cfg.min_positive_slope:
                    return cfg.weight_strong_alignment, "strong", sma20_slope, "Strong uptrend (SMA20 > SMA50 > SMA200, rising)"
                else:
                    return cfg.weight_moderate_alignment, "moderate", sma20_slope, "Aligned SMAs but flat/declining slope"
            elif current_price > sma_200 and sma_20 > sma_200:
                return cfg.weight_moderate_alignment, "moderate", sma20_slope, "Above SMA200, partial alignment"
        else:
            # Without SMA50: Only check SMA20 vs SMA200
            if sma_20 > sma_200 and current_price > sma_200:
                if sma20_slope >= cfg.min_positive_slope:
                    return cfg.weight_strong_alignment, "strong", sma20_slope, "Strong uptrend (SMA20 > SMA200, rising)"
                else:
                    return cfg.weight_moderate_alignment, "moderate", sma20_slope, "Above SMA200 but flat slope"

        # No uptrend
        if current_price < sma_200:
            return 0, "none", sma20_slope, "Below SMA200 - no uptrend"

        return 0, "weak", sma20_slope, "Weak trend structure"

    def _score_support_with_strength(
        self,
        price: float,
        supports: List[float],
        volumes: Optional[List[int]] = None,
        lows: Optional[List[float]] = None
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
            touches = sum(1 for low in lows[-cfg.lookback_days:] if abs(low - nearest) <= tolerance)

            if touches >= cfg.min_touches + 2:
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
            base_score += 0.5  # Bonus for strong support

        reason = f"Within {distance_pct:.1f}% of {strength} support ${nearest:.2f} ({touches} touches)"
        return base_score, reason, strength, touches

    # =========================================================================
    # SIGNAL HELPER (Legacy - for backward compatibility)
    # =========================================================================

    def _get_macd_signal(self, macd: Optional[MACDResult]) -> Optional[str]:
        """Determines MACD signal for display"""
        if not macd:
            return None
        
        if macd.crossover == 'bullish':
            return 'bullish_cross'
        elif macd.crossover == 'bearish':
            return 'bearish_cross'
        elif macd.histogram > 0:
            return 'bullish'
        elif macd.histogram < 0:
            return 'bearish'
        
        return 'neutral'
    
    def _get_stoch_signal(self, stoch: Optional[StochasticResult]) -> Optional[str]:
        """Determines Stochastic signal for display"""
        if not stoch:
            return None

        if stoch.zone == 'oversold':
            if stoch.crossover == 'bullish':
                return 'oversold_bullish_cross'
            return 'oversold'
        elif stoch.zone == 'overbought':
            if stoch.crossover == 'bearish':
                return 'overbought_bearish_cross'
            return 'overbought'

        return 'neutral'

    # =========================================================================
    # KELTNER CHANNEL
    # =========================================================================

    def _calculate_keltner_channel(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float]
    ) -> Optional[KeltnerChannelResult]:
        """Calculates Keltner Channel. Delegates to shared indicators library."""
        cfg = self.config.keltner
        return calculate_keltner_channel(
            prices=prices, highs=highs, lows=lows,
            ema_period=cfg.ema_period, atr_period=cfg.atr_period,
            atr_multiplier=cfg.atr_multiplier
        )

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[float]:
        """Calculates ATR (SMA-based). Delegates to shared indicators library."""
        return calculate_atr_simple(highs, lows, closes, period)

    def _score_keltner(
        self,
        keltner: KeltnerChannelResult,
        current_price: float
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

        if position == 'below_lower':
            return cfg.weight_below_lower, f"Price below Keltner Lower Band ({pct:.2f})"

        if position == 'near_lower':
            # Near lower band = potential buy opportunity
            return cfg.weight_near_lower, f"Price near Keltner Lower Band ({pct:.2f})"

        if position == 'in_channel' and pct < KELTNER_NEUTRAL_LOW:
            # In channel, but in lower third
            return cfg.weight_mean_reversion * 0.5, f"Pullback in lower channel area ({pct:.2f})"

        if position == 'above_upper':
            # Overbought = no pullback signal
            return 0, f"Price above Keltner Upper Band ({pct:.2f}) - overbought"

        return 0, f"Price in neutral channel position ({pct:.2f})"

    # =========================================================================
    # SCORING METHODS from FeatureScoringMixin:
    # _score_vwap, _score_market_context, _score_sector inherited
    # _score_gap is strategy-specific (uses pullback-specific constants)
    # =========================================================================

    def _score_gap(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        context: Optional[AnalysisContext] = None
    ) -> Tuple[float, str, float, bool, str]:
        """
        Gap Score (0-1 für down-gaps, -0.5 bis 0 für up-gaps).

        Validated with 174k+ Gap Events (907 symbols, 5 years):
        - Down-gaps: +0.43% better 30d returns, +1.9pp higher win rate
        - Large down-gaps (>3%): +1.21% outperformance at 5d
        - 30-Day Win Rate: 56.7% (down) vs 54.8% (up)

        Returns:
            (score, gap_type, gap_size_pct, is_filled, reason)
        """
        # Use context if available (already calculated)
        if context and hasattr(context, 'gap_result') and context.gap_result:
            gap = context.gap_result
            gap_type = gap.gap_type
            gap_size = gap.gap_size_pct
            is_filled = gap.is_filled
            quality_score = gap.quality_score

            # Convert quality_score (-1 to +1) to display score
            if gap_type in ('down', 'partial_down'):
                score = max(0, quality_score)  # 0 to 1
                if abs(gap_size) >= GAP_SIZE_LARGE:
                    reason = f"Large down-gap: {gap_size:.1f}% - strong entry (+1.21% outperformance)"
                elif abs(gap_size) >= GAP_SIZE_MEDIUM:
                    reason = f"Down-gap: {gap_size:.1f}% - favorable entry (+0.43% 30d)"
                else:
                    reason = f"Small down-gap: {gap_size:.1f}% - mild positive"
            elif gap_type in ('up', 'partial_up'):
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

            if gap_result and gap_result.gap_type != 'none':
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
