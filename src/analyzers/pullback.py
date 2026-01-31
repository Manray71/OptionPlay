# OptionPlay - Pullback Analyzer
# ================================
# Technische Analyse für Pullback-Kandidaten

import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import logging

from .base import BaseAnalyzer
from .context import AnalysisContext
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

# Import RSI Divergence calculator
try:
    from ..indicators.momentum import calculate_rsi_divergence
except ImportError:
    from indicators.momentum import calculate_rsi_divergence

# Import Volume Profile indicators (NEW from Feature Engineering)
try:
    from ..indicators.volume_profile import (
        calculate_vwap,
        get_sector,
        get_sector_adjustment,
    )
except ImportError:
    from indicators.volume_profile import (
        calculate_vwap,
        get_sector,
        get_sector_adjustment,
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


class PullbackAnalyzer(BaseAnalyzer):
    """
    Analysiert Aktien auf Pullback-Setups.
    
    Indikatoren:
    - RSI (14) - Oversold/Overbought
    - MACD (12, 26, 9) - Trend & Momentum
    - Stochastik (14, 3, 3) - Überkauft/Überverkauft
    - SMAs (20, 50, 200) - Trend
    - Support/Resistance - Swing Highs/Lows
    - Fibonacci Retracements
    """
    
    # MACD Default Parameter
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    
    # Stochastik Default Parameter
    STOCH_K = 14
    STOCH_D = 3
    STOCH_SMOOTH = 3
    STOCH_OVERSOLD = 20
    STOCH_OVERBOUGHT = 80
    
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
        Analysiert ein Symbol auf Pullback-Setup.

        Args:
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            TradeSignal mit Score und Entry-Empfehlung
        """
        # Vollständige Analyse durchführen
        candidate = self.analyze_detailed(symbol, prices, volumes, highs, lows, context=context)

        # Normalize score to 0-10 scale for fair cross-strategy comparison
        max_possible = candidate.score_breakdown.max_possible if hasattr(candidate.score_breakdown, 'max_possible') else 26
        normalized_score = (candidate.score / max_possible) * 10 if max_possible > 0 else 0

        # In TradeSignal konvertieren (based on normalized 0-10 scale)
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
        
        # Entry/Stop/Target berechnen
        entry_price = candidate.current_price
        stop_loss = None
        target_price = None
        
        if candidate.support_levels:
            # Stop unter dem nächsten Support
            nearest_support = min(candidate.support_levels, 
                                  key=lambda x: abs(x - entry_price))
            stop_loss = nearest_support * 0.98  # 2% unter Support
            
            # Target bei nächstem Widerstand oder 2:1 R/R
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
        Vollständige Pullback-Analyse für ein Symbol.

        Args:
            symbol: Ticker-Symbol
            prices: Schlusskurse (älteste zuerst)
            volumes: Tagesvolumen
            highs: Tageshochs
            lows: Tagestiefs
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            PullbackCandidate mit Score, Breakdown und allen Indikatoren

        Raises:
            ValueError: Bei ungültigen oder inkonsistenten Input-Daten
        """
        # Input Validierung
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

            # Trend bestimmen
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

        # 1. RSI Score (0-3 Punkte)
        breakdown.rsi_score, breakdown.rsi_reason = self._score_rsi(rsi)
        breakdown.rsi_value = rsi

        # 1b. RSI Divergenz (0-3 Punkte) - NEU
        # Bullische Divergenz ist starkes Signal für Pullback-Entry
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

        # 2. Support Score mit Stärke-Bewertung (0-2.5 Punkte)
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

        # 3. Fibonacci Score (0-2 Punkte)
        breakdown.fibonacci_score, breakdown.fib_level, breakdown.fib_reason = \
            self._score_fibonacci(current_price, fib_levels)

        # 4. Moving Average Score (0-2 Punkte)
        breakdown.ma_score, breakdown.ma_reason = self._score_moving_averages(
            current_price, sma_20, sma_200
        )
        breakdown.price_vs_sma20 = "above" if above_sma20 else "below"
        breakdown.price_vs_sma200 = "above" if above_sma200 else "below"

        # 5. Trend-Stärke Score (0-2 Punkte) - NEU
        trend_result = self._score_trend_strength(prices, sma_20, sma_50, sma_200)
        breakdown.trend_strength_score = trend_result[0]
        breakdown.trend_alignment = trend_result[1]
        breakdown.sma20_slope = trend_result[2]
        breakdown.trend_reason = trend_result[3]

        # 6. Volume Score mit Trend (0-1 Punkt) - VERBESSERT
        avg_volume = int(np.mean(volumes[-self.config.volume.average_period:]))
        vol_result = self._score_volume(current_volume, avg_volume)
        breakdown.volume_score = vol_result[0]
        breakdown.volume_reason = vol_result[1]
        breakdown.volume_trend = vol_result[2]
        breakdown.volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        # 7. MACD Score (0-2 Punkte) - NEU
        macd_result_score = self._score_macd(macd_result)
        breakdown.macd_score = macd_result_score[0]
        breakdown.macd_reason = macd_result_score[1]
        breakdown.macd_signal = macd_result_score[2]
        breakdown.macd_histogram = macd_result.histogram if macd_result else 0

        # 8. Stochastik Score (0-2 Punkte)
        stoch_result_score = self._score_stochastic(stoch_result)
        breakdown.stoch_score = stoch_result_score[0]
        breakdown.stoch_reason = stoch_result_score[1]
        breakdown.stoch_signal = stoch_result_score[2]
        breakdown.stoch_k = stoch_result.k if stoch_result else 0
        breakdown.stoch_d = stoch_result.d if stoch_result else 0

        # 9. Keltner Channel Score (0-2 Punkte) - NEU
        keltner_result = self._calculate_keltner_channel(prices, highs, lows)
        if keltner_result:
            keltner_score_result = self._score_keltner(keltner_result, current_price)
            breakdown.keltner_score = keltner_score_result[0]
            breakdown.keltner_reason = keltner_score_result[1]
            breakdown.keltner_position = keltner_result.price_position
            breakdown.keltner_percent = keltner_result.percent_position

        # 10. VWAP Score (0-3 Punkte) - NEW from Feature Engineering
        vwap_result = self._score_vwap(prices, volumes)
        breakdown.vwap_score = vwap_result[0]
        breakdown.vwap_value = vwap_result[1]
        breakdown.vwap_distance_pct = vwap_result[2]
        breakdown.vwap_position = vwap_result[3]
        breakdown.vwap_reason = vwap_result[4]

        # 11. Market Context Score (-1 to +2 Punkte) - NEW from Feature Engineering
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

        # 12. Sector Score (-1 to +1 Punkte) - NEW from Feature Engineering
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

        # Total Score (max ~26 Punkte)
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
        """Erstellt Begründung aus Score-Breakdown (erweitert für neue Komponenten)"""
        reasons = []
        bd = candidate.score_breakdown

        # RSI
        if bd.rsi_score > 0:
            reasons.append(f"RSI oversold ({candidate.technicals.rsi_14:.1f})")

        # RSI Divergenz (NEU)
        if bd.rsi_divergence_score >= 2:
            reasons.append(f"RSI Bullische Divergenz (Stärke: {bd.rsi_divergence_strength:.0%})")
        elif bd.rsi_divergence_score > 0:
            reasons.append("RSI Divergenz erkannt")

        # Support mit Stärke
        if bd.support_score > 0:
            if bd.support_strength == "strong":
                reasons.append(f"Near strong support ({bd.support_touches} touches)")
            elif bd.support_strength == "moderate":
                reasons.append("Near moderate support")
            else:
                reasons.append("Near support")

        # Trend-Stärke
        if bd.trend_strength_score > 0:
            if bd.trend_alignment == "strong":
                reasons.append("Strong uptrend")
            else:
                reasons.append("Uptrend")

        # MA-Score (Dip im Aufwärtstrend)
        if bd.ma_score > 0:
            reasons.append("Dip in uptrend")

        # Fibonacci
        if bd.fibonacci_score > 0:
            reasons.append(f"At Fib {bd.fib_level}")

        # MACD (NEU)
        if bd.macd_score >= 2:
            reasons.append("MACD bullish cross")
        elif bd.macd_score > 0:
            reasons.append("MACD bullish")

        # Stochastik (NEU)
        if bd.stoch_score >= 2:
            reasons.append("Stoch oversold + cross")
        elif bd.stoch_score > 0:
            reasons.append("Stoch oversold")

        # Volume
        if bd.volume_score > 0:
            reasons.append("Healthy low volume")

        # Keltner Channel (NEU)
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
        """Validiert alle Input-Arrays auf Konsistenz und Gültigkeit."""
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
    # INDIKATOREN - BERECHNUNG
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
        """Exponential Moving Average"""
        if len(prices) < period:
            return prices
        
        multiplier = 2 / (period + 1)
        ema_values = [np.mean(prices[:period])]
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema_values[-1] * (1 - multiplier))
            ema_values.append(ema)
        
        return ema_values
    
    def _calculate_macd(self, prices: List[float]) -> Optional[MACDResult]:
        """MACD (Moving Average Convergence Divergence)"""
        min_required = self.MACD_SLOW + self.MACD_SIGNAL
        if len(prices) < min_required:
            return None
        
        ema_fast = self._calculate_ema(prices, self.MACD_FAST)
        ema_slow = self._calculate_ema(prices, self.MACD_SLOW)
        
        offset = self.MACD_SLOW - self.MACD_FAST
        
        macd_line = []
        for i in range(len(ema_slow)):
            fast_idx = i + offset
            if fast_idx < len(ema_fast):
                macd_line.append(ema_fast[fast_idx] - ema_slow[i])
        
        if len(macd_line) < self.MACD_SIGNAL:
            return None
        
        signal_line = self._calculate_ema(macd_line, self.MACD_SIGNAL)
        
        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        histogram = current_macd - current_signal
        
        crossover = None
        if len(signal_line) >= 2:
            prev_diff = macd_line[-2] - signal_line[-2]
            curr_diff = current_macd - current_signal
            
            if prev_diff < 0 and curr_diff > 0:
                crossover = 'bullish'
            elif prev_diff > 0 and curr_diff < 0:
                crossover = 'bearish'
        
        return MACDResult(
            macd_line=current_macd,
            signal_line=current_signal,
            histogram=histogram,
            crossover=crossover
        )
    
    def _calculate_stochastic(
        self, 
        highs: List[float], 
        lows: List[float], 
        closes: List[float]
    ) -> Optional[StochasticResult]:
        """Stochastik Oszillator"""
        if len(highs) != len(lows) or len(lows) != len(closes):
            logger.warning(
                f"Stochastic: Input arrays must have same length. "
                f"Got highs={len(highs)}, lows={len(lows)}, closes={len(closes)}"
            )
            return None
        
        min_required = self.STOCH_K + self.STOCH_D + self.STOCH_SMOOTH
        if len(closes) < min_required:
            return None
        
        raw_k = []
        for i in range(self.STOCH_K - 1, len(closes)):
            period_high = max(highs[i - self.STOCH_K + 1:i + 1])
            period_low = min(lows[i - self.STOCH_K + 1:i + 1])
            
            if period_high == period_low:
                raw_k.append(50.0)
            else:
                k = 100 * (closes[i] - period_low) / (period_high - period_low)
                raw_k.append(k)
        
        smooth_k = []
        for i in range(self.STOCH_SMOOTH - 1, len(raw_k)):
            smooth_k.append(np.mean(raw_k[i - self.STOCH_SMOOTH + 1:i + 1]))
        
        d_values = []
        for i in range(self.STOCH_D - 1, len(smooth_k)):
            d_values.append(np.mean(smooth_k[i - self.STOCH_D + 1:i + 1]))
        
        if not smooth_k or not d_values:
            return None
        
        current_k = smooth_k[-1]
        current_d = d_values[-1]
        
        crossover = None
        if len(smooth_k) >= 2 and len(d_values) >= 2:
            prev_diff = smooth_k[-2] - d_values[-2]
            curr_diff = smooth_k[-1] - d_values[-1]
            
            if prev_diff < 0 and curr_diff > 0:
                crossover = 'bullish'
            elif prev_diff > 0 and curr_diff < 0:
                crossover = 'bearish'
        
        if current_k < self.STOCH_OVERSOLD:
            zone = 'oversold'
        elif current_k > self.STOCH_OVERBOUGHT:
            zone = 'overbought'
        else:
            zone = 'neutral'
        
        return StochasticResult(
            k=current_k,
            d=current_d,
            crossover=crossover,
            zone=zone
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
        RSI Divergenz Score (0-3 Punkte).

        Bullische Divergenz ist ein starkes Signal für Pullback-Entry:
        - Kurs macht tieferes Tief
        - RSI macht höheres Tief
        - Verkaufsdruck lässt nach → Bodenbildung wahrscheinlich

        Bärische Divergenz ist ein Warnsignal (kein Punktabzug, aber Warning).
        """
        if not divergence:
            return 0, "Keine RSI-Divergenz erkannt"

        if divergence.divergence_type == 'bullish':
            # Scoring basierend auf Stärke der Divergenz
            strength = divergence.strength

            if strength >= 0.7:
                score = 3.0
                reason = f"Starke bullische Divergenz (Stärke: {strength:.0%}, {divergence.formation_days} Tage)"
            elif strength >= 0.4:
                score = 2.0
                reason = f"Moderate bullische Divergenz (Stärke: {strength:.0%}, {divergence.formation_days} Tage)"
            else:
                score = 1.0
                reason = f"Schwache bullische Divergenz (Stärke: {strength:.0%}, {divergence.formation_days} Tage)"

            return score, reason

        elif divergence.divergence_type == 'bearish':
            # Bärische Divergenz beim Pullback = Warnsignal, aber kein Abzug
            return 0, f"Bärische Divergenz erkannt - Vorsicht! (Stärke: {divergence.strength:.0%})"

        return 0, "Keine signifikante Divergenz"

    def _score_rsi(self, rsi: float) -> Tuple[float, str]:
        """RSI Score (0-3 Punkte)"""
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
        """Support-Nähe Score (0-2 Punkte)"""
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
        """Fibonacci Score (0-2 Punkte)"""
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
        """Moving Average Score (0-2 Punkte)"""
        if price > sma_200 and price < sma_20:
            return 2, "Dip in uptrend (price > SMA200, < SMA20)"
        elif price > sma_200 and price > sma_20:
            return 0, "Strong uptrend, no pullback"
        elif price < sma_200:
            return 0, "Below SMA200, no primary uptrend"
        
        return 0, "MA config doesn't indicate pullback"
    
    def _score_volume(self, current: int, average: int) -> Tuple[float, str, str]:
        """
        Volume Score (0-1 Punkt)

        NEU: Sinkendes Volumen beim Pullback = gesund (keine Panik-Verkäufe)
        """
        if average == 0:
            return 0, "No average volume data", "unknown"

        ratio = current / average
        cfg = self.config.volume

        # NEU: Sinkendes Volumen ist POSITIV bei einem Pullback
        if ratio < cfg.decrease_threshold:
            return cfg.weight_decreasing, f"Low volume pullback: {ratio:.1f}x avg (healthy)", "decreasing"
        elif ratio >= cfg.spike_multiplier:
            # Hohes Volumen bei Pullback = potenziell problematisch (Panik)
            return 0, f"Volume spike: {ratio:.1f}x avg (caution)", "increasing"
        else:
            return 0, f"Volume normal: {ratio:.1f}x avg", "stable"

    def _score_macd(self, macd: Optional[MACDResult]) -> Tuple[float, str, str]:
        """
        MACD Score (0-2 Punkte)

        - Bullish Cross: 2 Punkte (starkes Umkehrsignal)
        - Histogram positiv: 1 Punkt
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
        Stochastik Score (0-2 Punkte)

        - Oversold + Bullish Cross: 2 Punkte (sehr starkes Signal)
        - Nur Oversold: 1 Punkt
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
        Trend-Stärke Score (0-2 Punkte)

        - Starkes Alignment (SMA20 > SMA50 > SMA200): 2 Punkte
        - Moderates Alignment (Preis > SMA200): 1 Punkt
        - Kein Alignment: 0 Punkte

        Returns:
            (score, alignment, sma20_slope, reason)
        """
        cfg = self.config.trend_strength
        current_price = prices[-1]

        # Berechne SMA20-Slope (Steigung)
        slope_lookback = min(cfg.slope_lookback, len(prices) - 1)
        if slope_lookback > 0:
            sma20_recent = sum(prices[-20:]) / 20 if len(prices) >= 20 else current_price
            sma20_older = sum(prices[-20-slope_lookback:-slope_lookback]) / 20 if len(prices) >= 20 + slope_lookback else sma20_recent
            sma20_slope = (sma20_recent - sma20_older) / sma20_older if sma20_older > 0 else 0
        else:
            sma20_slope = 0

        # Prüfe SMA-Alignment
        if sma_50 is not None:
            # Vollständiges Alignment: SMA20 > SMA50 > SMA200
            if sma_20 > sma_50 > sma_200 and current_price > sma_200:
                if sma20_slope >= cfg.min_positive_slope:
                    return cfg.weight_strong_alignment, "strong", sma20_slope, "Strong uptrend (SMA20 > SMA50 > SMA200, rising)"
                else:
                    return cfg.weight_moderate_alignment, "moderate", sma20_slope, "Aligned SMAs but flat/declining slope"
            elif current_price > sma_200 and sma_20 > sma_200:
                return cfg.weight_moderate_alignment, "moderate", sma20_slope, "Above SMA200, partial alignment"
        else:
            # Ohne SMA50: Nur SMA20 vs SMA200 prüfen
            if sma_20 > sma_200 and current_price > sma_200:
                if sma20_slope >= cfg.min_positive_slope:
                    return cfg.weight_strong_alignment, "strong", sma20_slope, "Strong uptrend (SMA20 > SMA200, rising)"
                else:
                    return cfg.weight_moderate_alignment, "moderate", sma20_slope, "Above SMA200 but flat slope"

        # Kein Aufwärtstrend
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
        Erweitertes Support-Scoring mit Stärke-Bewertung.

        Returns:
            (score, reason, strength, touches)
        """
        if not supports:
            return 0, "No support levels found", "none", 0

        cfg = self.config.support
        nearest = min(supports, key=lambda x: abs(x - price))
        distance_pct = abs(price - nearest) / price * 100

        # Schätze Support-Stärke basierend auf Häufigkeit
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

        # Scoring basierend auf Distanz UND Stärke
        base_score = 0
        if distance_pct <= cfg.proximity_percent:
            base_score = cfg.weight_close
        elif distance_pct <= cfg.proximity_percent_wide:
            base_score = cfg.weight_near

        # Bonus für starken Support
        if strength == "strong" and base_score > 0:
            base_score += 0.5  # Bonus für starken Support

        reason = f"Within {distance_pct:.1f}% of {strength} support ${nearest:.2f} ({touches} touches)"
        return base_score, reason, strength, touches

    # =========================================================================
    # SIGNAL HELPER (Legacy - für Rückwärtskompatibilität)
    # =========================================================================

    def _get_macd_signal(self, macd: Optional[MACDResult]) -> Optional[str]:
        """Bestimmt MACD-Signal für Anzeige"""
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
        """Bestimmt Stochastik-Signal für Anzeige"""
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
        """
        Berechnet Keltner Channel.

        Keltner Channel = EMA ± (ATR × Multiplier)
        - Middle: EMA(20)
        - Upper: EMA + ATR(10) × 2
        - Lower: EMA - ATR(10) × 2

        Args:
            prices: Schlusskurse
            highs: Tageshochs
            lows: Tagestiefs

        Returns:
            KeltnerChannelResult oder None bei unzureichenden Daten
        """
        cfg = self.config.keltner
        min_required = max(cfg.ema_period, cfg.atr_period) + 1

        if len(prices) < min_required:
            return None

        # EMA berechnen (Mittellinie)
        ema_values = self._calculate_ema(prices, cfg.ema_period)
        if not ema_values:
            return None
        current_ema = ema_values[-1]

        # ATR berechnen
        atr = self._calculate_atr(highs, lows, prices, cfg.atr_period)
        if atr is None or atr <= 0:
            return None

        # Bänder berechnen
        band_width = atr * cfg.atr_multiplier
        upper = current_ema + band_width
        lower = current_ema - band_width

        # Aktuelle Position des Preises bestimmen
        current_price = prices[-1]
        channel_range = upper - lower

        if channel_range <= 0:
            return None

        # Percent Position: -1 = lower, 0 = middle, +1 = upper
        percent_position = (current_price - current_ema) / band_width if band_width > 0 else 0

        # Position Label
        if current_price > upper:
            price_position = 'above_upper'
        elif current_price < lower:
            price_position = 'below_lower'
        elif percent_position < -0.5:
            price_position = 'near_lower'
        elif percent_position > 0.5:
            price_position = 'near_upper'
        else:
            price_position = 'in_channel'

        # Channel-Breite als % des Preises (Volatilitätsindikator)
        channel_width_pct = (channel_range / current_price) * 100 if current_price > 0 else 0

        return KeltnerChannelResult(
            upper=upper,
            middle=current_ema,
            lower=lower,
            atr=atr,
            price_position=price_position,
            percent_position=percent_position,
            channel_width_pct=channel_width_pct
        )

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[float]:
        """
        Berechnet Average True Range (ATR).

        True Range = max(H-L, |H-Pc|, |L-Pc|)
        ATR = SMA(TR, period)
        """
        if len(highs) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(highs)):
            high = highs[i]
            low = lows[i]
            prev_close = closes[i - 1]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        return float(np.mean(true_ranges[-period:]))

    def _score_keltner(
        self,
        keltner: KeltnerChannelResult,
        current_price: float
    ) -> Tuple[float, str]:
        """
        Keltner Channel Score (0-2 Punkte).

        Scoring-Logik für Pullbacks:
        - Preis unter unterem Band: 2 Punkte (stark oversold, Mean Reversion erwartet)
        - Preis nahe unterem Band: 1 Punkt (pullback in oversold territory)
        - Preis im Channel: 0 Punkte (neutral)
        - Preis über oberem Band: 0 Punkte (überkauft, kein Pullback-Setup)

        Returns:
            (score, reason)
        """
        cfg = self.config.keltner
        position = keltner.price_position
        pct = keltner.percent_position

        if position == 'below_lower':
            return cfg.weight_below_lower, f"Preis unter Keltner Lower Band ({pct:.2f})"

        if position == 'near_lower':
            # Nahe unterem Band = potenzielle Kaufgelegenheit
            return cfg.weight_near_lower, f"Preis nahe Keltner Lower Band ({pct:.2f})"

        if position == 'in_channel' and pct < -0.3:
            # Im Channel, aber im unteren Drittel
            return cfg.weight_mean_reversion * 0.5, f"Pullback im unteren Channel-Bereich ({pct:.2f})"

        if position == 'above_upper':
            # Überkauft = kein Pullback-Signal
            return 0, f"Preis über Keltner Upper Band ({pct:.2f}) - überkauft"

        return 0, f"Preis in neutraler Channel-Position ({pct:.2f})"

    # =========================================================================
    # NEW SCORING METHODS (from Feature Engineering Training)
    # =========================================================================

    def _score_vwap(
        self,
        prices: List[float],
        volumes: List[int]
    ) -> Tuple[float, float, float, str, str]:
        """
        VWAP Score (0-3 Punkte).

        Based on Feature Engineering Training:
        - Above VWAP >3%: 91.9% win rate → 3 points
        - Above VWAP 1-3%: 87.6% win rate → 2 points
        - Near VWAP: 78.3% win rate → 1 point
        - Below VWAP: 51.7-66.1% win rate → 0 points

        Returns:
            (score, vwap_value, distance_pct, position, reason)
        """
        vwap_result = calculate_vwap(prices, volumes, period=20)

        if not vwap_result:
            return 0, 0, 0, "unknown", "Insufficient data for VWAP"

        vwap = vwap_result.vwap
        distance = vwap_result.distance_pct
        position = vwap_result.position

        # Scoring based on training results
        if distance > 3.0:
            score = 3.0
            reason = f"Strong momentum: {distance:.1f}% above VWAP (91.9% win rate)"
        elif distance > 1.0:
            score = 2.0
            reason = f"Above VWAP: {distance:.1f}% (87.6% win rate)"
        elif distance > -1.0:
            score = 1.0
            reason = f"Near VWAP: {distance:.1f}% (78.3% win rate)"
        elif distance > -3.0:
            score = 0.0
            reason = f"Below VWAP: {distance:.1f}% (66.1% win rate)"
        else:
            score = 0.0
            reason = f"Weak: {distance:.1f}% below VWAP (51.7% win rate)"

        return score, vwap, distance, position, reason

    def _score_market_context(
        self,
        spy_prices: Optional[List[float]]
    ) -> Tuple[float, str, str]:
        """
        Market Context Score (0-2 Punkte).

        Based on Feature Engineering Training:
        - Strong uptrend: 76.1% win rate, +$1.03M → 2 points
        - Uptrend: 70.9% win rate → 1 point
        - Sideways: neutral → 0 points
        - Downtrend: 60.1% win rate, -$470k → -0.5 points (penalty)
        - Strong downtrend: 59.3% win rate → -1 point (penalty)

        Returns:
            (score, spy_trend, reason)
        """
        if not spy_prices or len(spy_prices) < 50:
            return 0, "unknown", "No SPY data for market context"

        # Determine SPY trend
        current = spy_prices[-1]
        sma20 = float(np.mean(spy_prices[-20:]))
        sma50 = float(np.mean(spy_prices[-50:]))

        if current > sma20 > sma50:
            trend = "strong_uptrend"
            score = 2.0
            reason = "Strong market uptrend (76.1% win rate)"
        elif current > sma50 and current > sma20:
            trend = "uptrend"
            score = 1.0
            reason = "Market uptrend (70.9% win rate)"
        elif current > sma50:
            trend = "sideways"
            score = 0.0
            reason = "Market sideways"
        elif current < sma20 < sma50:
            trend = "strong_downtrend"
            score = -1.0
            reason = "Strong market downtrend - CAUTION (59.3% win rate)"
        else:
            trend = "downtrend"
            score = -0.5
            reason = "Market downtrend - reduced expectation (60.1% win rate)"

        return score, trend, reason

    def _score_sector(self, symbol: str) -> Tuple[float, str, str]:
        """
        Sector Score (-1 to +1 Punkt).

        Based on Feature Engineering Training:
        - Consumer Staples: +9% win rate → +0.9 points
        - Utilities: +6.8% → +0.7 points
        - Financials: +6.4% → +0.6 points
        - Technology: -10% → -1.0 points
        - Materials: -7.5% → -0.75 points

        Returns:
            (score, sector_name, reason)
        """
        sector = get_sector(symbol)
        adjustment = get_sector_adjustment(symbol)

        if adjustment > 0.5:
            reason = f"{sector}: strong sector (+{adjustment*10:.0f}% win rate)"
        elif adjustment > 0:
            reason = f"{sector}: favorable sector (+{adjustment*10:.0f}% win rate)"
        elif adjustment < -0.5:
            reason = f"{sector}: challenging sector ({adjustment*10:.0f}% win rate)"
        elif adjustment < 0:
            reason = f"{sector}: slightly unfavorable ({adjustment*10:.0f}% win rate)"
        else:
            reason = f"{sector}: neutral sector"

        return adjustment, sector, reason

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
                if abs(gap_size) >= 3.0:
                    reason = f"Large down-gap: {gap_size:.1f}% - strong entry (+1.21% outperformance)"
                elif abs(gap_size) >= 1.0:
                    reason = f"Down-gap: {gap_size:.1f}% - favorable entry (+0.43% 30d)"
                else:
                    reason = f"Small down-gap: {gap_size:.1f}% - mild positive"
            elif gap_type in ('up', 'partial_up'):
                score = min(0, quality_score)  # -0.5 to 0
                if abs(gap_size) >= 3.0:
                    reason = f"Large up-gap: {gap_size:+.1f}% - caution, overbought risk"
                elif abs(gap_size) >= 1.0:
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
                lookback_days=20,
                min_gap_pct=0.5,
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
