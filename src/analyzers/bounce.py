# OptionPlay - Bounce Analyzer
# ==============================
# Analyzes bounces from support levels
#
# Strategy: Buy when stock bounces off established support
# - Mean-Reversion Signal
# - Works best with range-bound stocks
# - Risk: Support breaks, trend continues

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
import logging
import numpy as np

from .base import BaseAnalyzer
from .context import AnalysisContext

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..models.indicators import MACDResult, StochasticResult, KeltnerChannelResult, RSIDivergenceResult
    from ..models.strategy_breakdowns import BounceScoreBreakdown
    from ..config.config_loader import BounceScoringConfig
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength
    from models.indicators import MACDResult, StochasticResult, KeltnerChannelResult, RSIDivergenceResult
    from models.strategy_breakdowns import BounceScoreBreakdown
    from config.config_loader import BounceScoringConfig

# Import RSI Divergence calculator
try:
    from ..indicators.momentum import calculate_rsi_divergence
except ImportError:
    from indicators.momentum import calculate_rsi_divergence

# Import optimized support/resistance functions
try:
    from ..indicators.support_resistance import find_support_levels as find_support_optimized
    from ..indicators.support_resistance import get_nearest_sr_levels
except ImportError:
    from indicators.support_resistance import find_support_levels as find_support_optimized
    from indicators.support_resistance import get_nearest_sr_levels

# Import Feature Scoring Mixin (NEW from Feature Engineering)
try:
    from .feature_scoring_mixin import FeatureScoringMixin
except ImportError:
    from analyzers.feature_scoring_mixin import FeatureScoringMixin

logger = logging.getLogger(__name__)


@dataclass
class BounceConfig:
    """Configuration for Bounce Analyzer (Legacy - for backward compatibility)"""
    # Support Detection
    support_lookback_days: int = 60
    support_touches_min: int = 2  # Minimum 2x tested
    support_tolerance_pct: float = 1.5  # Support zone tolerance

    # Bounce Confirmation
    bounce_min_pct: float = 1.0  # Minimum bounce from low
    volume_confirmation: bool = True
    volume_spike_multiplier: float = 1.3

    # RSI for Oversold
    rsi_oversold_threshold: float = 40.0
    rsi_period: int = 14

    # Candlestick Patterns
    require_bullish_candle: bool = True

    # Risk Management
    stop_below_support_pct: float = 2.0
    target_risk_reward: float = 2.0

    # Scoring
    max_score: int = 10
    min_score_for_signal: int = 6


class BounceAnalyzer(BaseAnalyzer, FeatureScoringMixin):
    """
    Analyzes stocks for support bounces.

    Scoring criteria (extended):
    - Support test (price near established support): 0-3 points
    - RSI oversold (< 40): 0-2 points
    - Bullish Candlestick (Hammer, Engulfing): 0-2 points
    - Volume analysis: 0-2 points
    - Trend check (above SMA200): 0-2 points
    - MACD signal: 0-2 points (NEW)
    - Stochastic signal: 0-2 points (NEW)
    - Keltner Channel: 0-2 points (NEW)

    Usage:
        analyzer = BounceAnalyzer()
        signal = analyzer.analyze("AAPL", prices, volumes, highs, lows)

        if signal.is_actionable:
            print(f"Bounce Signal: {signal.score}/17")
    """

    def __init__(
        self,
        config: Optional[BounceConfig] = None,
        scoring_config: Optional[BounceScoringConfig] = None
    ):
        self.config = config or BounceConfig()
        self.scoring_config = scoring_config or BounceScoringConfig()

    @property
    def strategy_name(self) -> str:
        return "bounce"

    @property
    def description(self) -> str:
        return "Support Bounce - Buy on bounce from established support level"

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
        Analyzes a symbol for support bounce.

        Args:
            symbol: Ticker symbol
            prices: Closing prices (oldest first)
            volumes: Daily volume
            highs: Daily highs
            lows: Daily lows
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            TradeSignal with bounce rating
        """
        # Input validation
        min_data = max(self.config.support_lookback_days, 60)
        self.validate_inputs(prices, volumes, highs, lows, min_length=min_data)

        current_price = prices[-1]
        current_low = lows[-1]

        # Initialize score breakdown
        breakdown = BounceScoreBreakdown()
        reasons = []
        warnings = []

        # 1. Support Detection & Test (0-3 points)
        if context and context.support_levels:
            support_levels = context.support_levels
        else:
            support_levels = find_support_optimized(
                lows=lows,
                lookback=self.config.support_lookback_days,
                window=5,
                max_levels=10,
                volumes=volumes if volumes else None,
                tolerance_pct=self.config.support_tolerance_pct
            )

        support_result = self._score_support_test(
            current_low, current_price, support_levels, lows
        )
        breakdown.support_score = support_result[0]
        breakdown.support_level = support_result[1].get('tested_support') or support_result[1].get('nearest_support')
        breakdown.support_distance_pct = support_result[1].get('distance_pct', 0)
        breakdown.support_strength = support_result[1].get('strength', 'weak')
        breakdown.support_touches = support_result[1].get('touches', 0)
        breakdown.support_reason = f"Support-Test Score: {breakdown.support_score}"

        if breakdown.support_score == 0:
            return self.create_neutral_signal(
                symbol, current_price,
                f"No support test. Nearest support at ${support_result[1].get('nearest_support', 'N/A')}"
            )

        if 'tested_support' in support_result[1]:
            reasons.append(f"Support test at ${support_result[1]['tested_support']:.2f}")
        elif 'near_support' in support_result[1]:
            reasons.append(f"Near support at ${support_result[1].get('nearest_support', 0):.2f}")

        # 2. RSI Oversold (0-2 points)
        rsi_result = self._score_rsi_oversold(prices)
        breakdown.rsi_score = rsi_result[0]
        breakdown.rsi_value = rsi_result[1]
        breakdown.rsi_reason = f"RSI={rsi_result[1]:.1f}"

        if breakdown.rsi_score > 0:
            reasons.append(f"RSI oversold ({breakdown.rsi_value:.0f})")
        else:
            warnings.append(f"RSI not oversold ({breakdown.rsi_value:.0f})")

        # 2b. RSI Divergence (0-3 points) - NEW
        # Bullish divergence is a strong signal for bounce
        divergence_result = calculate_rsi_divergence(
            prices=prices,
            lows=lows,
            highs=highs,
            rsi_period=self.config.rsi_period,
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

        if breakdown.rsi_divergence_score >= 2:
            reasons.append(f"RSI Bullish Divergence (strength: {breakdown.rsi_divergence_strength:.0%})")
        elif breakdown.rsi_divergence_type == 'bearish':
            warnings.append("RSI Bearish Divergence - caution!")

        # 3. Candlestick Pattern (0-2 points)
        candle_result = self._score_candlestick_pattern(prices, highs, lows)
        breakdown.candlestick_score = candle_result[0]
        breakdown.candlestick_pattern = candle_result[1].get('pattern')
        breakdown.candlestick_bullish = candle_result[1].get('bullish', False)
        breakdown.candlestick_reason = f"Pattern: {breakdown.candlestick_pattern or 'None'}"

        if breakdown.candlestick_score > 0:
            reasons.append(f"Bullish Pattern: {breakdown.candlestick_pattern}")

        # 4. Volume Analysis (0-2 points) - extended
        vol_result = self._score_volume(volumes)
        breakdown.volume_score = vol_result[0]
        breakdown.volume_ratio = vol_result[1].get('multiplier', 0)
        breakdown.volume_trend = vol_result[1].get('trend', 'unknown')
        breakdown.volume_reason = vol_result[1].get('reason', '')

        if breakdown.volume_score > 0:
            reasons.append("Volume confirms bounce")

        # 5. Trend Check (0-2 points)
        trend_result = self._score_trend(prices)
        breakdown.trend_score = trend_result[0]
        breakdown.trend_status = trend_result[1].get('trend', 'unknown')
        breakdown.trend_reason = f"Trend: {breakdown.trend_status}"

        if breakdown.trend_score >= 2:
            reasons.append("Uptrend intact (above SMA200)")
        elif breakdown.trend_score == 1:
            reasons.append("Neutral trend")
        else:
            warnings.append("Downtrend - increased risk")

        # 6. MACD Score (0-2 points) - NEW
        macd_result = self._calculate_macd(prices)
        macd_score_result = self._score_macd(macd_result)
        breakdown.macd_score = macd_score_result[0]
        breakdown.macd_signal = macd_score_result[2]
        breakdown.macd_histogram = macd_result.histogram if macd_result else 0
        breakdown.macd_reason = macd_score_result[1]

        if breakdown.macd_score >= 2:
            reasons.append("MACD bullish cross")
        elif breakdown.macd_score > 0:
            reasons.append("MACD bullish")

        # 7. Stochastic Score (0-2 points) - NEW
        stoch_result = self._calculate_stochastic(prices, highs, lows)
        stoch_score_result = self._score_stochastic(stoch_result)
        breakdown.stoch_score = stoch_score_result[0]
        breakdown.stoch_signal = stoch_score_result[2]
        breakdown.stoch_k = stoch_result.k if stoch_result else 0
        breakdown.stoch_d = stoch_result.d if stoch_result else 0
        breakdown.stoch_reason = stoch_score_result[1]

        if breakdown.stoch_score >= 2:
            reasons.append("Stoch oversold + cross")
        elif breakdown.stoch_score > 0:
            reasons.append("Stoch oversold")

        # 8. Keltner Channel (0-2 points) - NEW
        keltner_result = self._calculate_keltner_channel(prices, highs, lows)
        if keltner_result:
            keltner_score_result = self._score_keltner(keltner_result, current_price)
            breakdown.keltner_score = keltner_score_result[0]
            breakdown.keltner_position = keltner_result.price_position
            breakdown.keltner_percent = keltner_result.percent_position
            breakdown.keltner_reason = keltner_score_result[1]

            if breakdown.keltner_score >= 2:
                reasons.append("Below Keltner lower band")
            elif breakdown.keltner_score > 0:
                reasons.append("Near Keltner lower band")

        # NEW: Apply Feature Engineering scores (VWAP, Market Context, Sector, Gap)
        self._apply_feature_scores(breakdown, symbol, prices, volumes, highs, lows, context)

        # Calculate total score
        breakdown.total_score = (
            breakdown.support_score +
            breakdown.rsi_score +
            breakdown.rsi_divergence_score +  # NEW: RSI Divergence
            breakdown.candlestick_score +
            breakdown.volume_score +
            breakdown.trend_score +
            breakdown.macd_score +
            breakdown.stoch_score +
            breakdown.keltner_score +
            breakdown.vwap_score +          # Feature Engineering
            breakdown.market_context_score + # Feature Engineering
            breakdown.sector_score +         # Feature Engineering
            breakdown.gap_score             # Validated with 174k+ events
        )
        breakdown.max_possible = 27  # +1 for gap score

        # Normalize score to 0-10 scale for fair cross-strategy comparison
        normalized_score = (breakdown.total_score / breakdown.max_possible) * 10

        # Determine signal strength (based on normalized 0-10 scale)
        if normalized_score >= 7:
            strength = SignalStrength.STRONG
        elif normalized_score >= 5:
            strength = SignalStrength.MODERATE
        elif normalized_score >= 3:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE

        # Calculate Entry/Stop/Target
        entry_price = current_price
        support = support_result[1].get('tested_support', current_low)
        stop_loss = support * (1 - self.config.stop_below_support_pct / 100)
        target_price = self._calculate_target(entry_price, stop_loss)

        # Extended S/R analysis with 12-month lookback
        sr_levels = get_nearest_sr_levels(
            current_price=current_price,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            lookback=252,  # 12 months
            num_levels=3
        )

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.LONG if normalized_score >= 3.5 else SignalType.NEUTRAL,
            strength=strength,
            score=round(normalized_score, 1),  # Normalized 0-10 score
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=" | ".join(reasons),
            details={
                'score_breakdown': breakdown.to_dict(),
                'raw_score': breakdown.total_score,
                'max_possible': breakdown.max_possible,
                'support_levels': support_levels[:3],
                'support_info': support_result[1],
                'trend_info': trend_result[1],
                'rsi': breakdown.rsi_value,
                'candle_info': {'pattern': breakdown.candlestick_pattern, 'bullish': breakdown.candlestick_bullish},
                'sr_levels': sr_levels  # Extended S/R with 12-month lookback
            },
            warnings=warnings
        )

    def _score_support_test(
        self,
        current_low: float,
        current_price: float,
        support_levels: List[float],
        lows: List[float]
    ) -> Tuple[int, Dict[str, Any]]:
        """Checks if current price tests support and evaluates support strength"""
        tolerance = self.config.support_tolerance_pct / 100

        info = {
            'current_low': current_low,
            'current_price': current_price,
            'supports_found': len(support_levels)
        }

        if not support_levels:
            info['nearest_support'] = None
            return 0, info

        # Find nearest support
        nearest_support = min(support_levels, key=lambda s: abs(current_low - s))
        info['nearest_support'] = nearest_support

        # Check if low tested the support
        distance_pct = abs(current_low - nearest_support) / nearest_support
        info['distance_pct'] = distance_pct * 100

        # Calculate support strength (count touches)
        touches = self._count_support_touches(lows, nearest_support, tolerance)
        info['touches'] = touches

        if touches >= 4:
            info['strength'] = 'strong'
        elif touches >= 2:
            info['strength'] = 'moderate'
        else:
            info['strength'] = 'weak'

        if distance_pct <= tolerance:
            # Support getestet
            info['tested_support'] = nearest_support

            # Check if bounce (Close above Low)
            bounce_pct = (current_price - current_low) / current_low * 100
            info['bounce_pct'] = bounce_pct

            if bounce_pct >= self.config.bounce_min_pct:
                # Bonus for strong support
                base_score = 3
                if info['strength'] == 'strong':
                    return base_score, info
                elif info['strength'] == 'moderate':
                    return base_score, info
                else:
                    return 2, info
            else:
                return 2, info  # Support getestet, aber schwacher Bounce

        # Nahe am Support aber nicht getestet
        if distance_pct <= tolerance * 2:
            info['near_support'] = True
            return 1, info

        return 0, info

    def _count_support_touches(
        self,
        lows: List[float],
        support_level: float,
        tolerance: float
    ) -> int:
        """Counts how many times the support level was tested"""
        touches = 0
        lookback = min(len(lows), self.config.support_lookback_days)

        for i in range(-lookback, 0):
            low = lows[i]
            if abs(low - support_level) / support_level <= tolerance:
                touches += 1

        return touches

    def _score_rsi_oversold(self, prices: List[float]) -> Tuple[int, float]:
        """RSI-Score für Oversold-Bedingung"""
        period = self.config.rsi_period

        if len(prices) < period + 1:
            return 0, 50.0

        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_changes = changes[-period:]

        gains = [c for c in recent_changes if c > 0]
        losses = [-c for c in recent_changes if c < 0]

        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.0001

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        if rsi < 30:
            return 2, rsi  # Stark oversold
        elif rsi < self.config.rsi_oversold_threshold:
            return 1, rsi  # Oversold
        else:
            return 0, rsi

    def _score_candlestick_pattern(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float]
    ) -> Tuple[int, Dict[str, Any]]:
        """Detects bullish candlestick patterns"""
        if len(prices) < 3:
            return 0, {'pattern': None}

        # Last candle
        open_price = prices[-2]  # Approximation: vorheriger Close
        close = prices[-1]
        high = highs[-1]
        low = lows[-1]

        body = close - open_price
        upper_wick = high - max(open_price, close)
        lower_wick = min(open_price, close) - low
        body_size = abs(body)

        info = {'pattern': None, 'bullish': False}

        # Hammer Detection
        if body_size > 0:
            if lower_wick >= body_size * 2 and upper_wick < body_size * 0.5:
                info['pattern'] = 'Hammer'
                info['bullish'] = True
                return 2 if body > 0 else 1, info  # Green hammer = better

        # Bullish Engulfing
        if len(prices) >= 3:
            prev_body = prices[-2] - prices[-3]
            if prev_body < 0 and body > 0 and body > abs(prev_body):
                info['pattern'] = 'Bullish Engulfing'
                info['bullish'] = True
                return 2, info

        # Doji am Support
        total_range = high - low
        if total_range > 0 and body_size / total_range < 0.1:
            info['pattern'] = 'Doji'
            info['bullish'] = False  # Neutral, but relevant at support
            return 1, info

        # Bullish Kerze (grün)
        if body > 0:
            info['pattern'] = 'Bullish Candle'
            info['bullish'] = True
            return 1, info

        return 0, info

    def _score_volume(self, volumes: List[int]) -> Tuple[int, Dict[str, Any]]:
        """Extended volume analysis"""
        avg_period = 20

        if len(volumes) < avg_period + 1:
            return 0, {'trend': 'unknown', 'reason': 'Insufficient data'}

        avg_volume = sum(volumes[-avg_period-1:-1]) / avg_period
        current_volume = volumes[-1]

        multiplier = current_volume / avg_volume if avg_volume > 0 else 0

        info = {
            'current_volume': current_volume,
            'avg_volume': avg_volume,
            'multiplier': multiplier
        }

        # Volume trend of the last 5 days
        recent_volumes = volumes[-5:]
        if len(recent_volumes) >= 3:
            vol_trend = recent_volumes[-1] / recent_volumes[0] if recent_volumes[0] > 0 else 1
            if vol_trend < 0.7:
                info['trend'] = 'decreasing'
            elif vol_trend > 1.3:
                info['trend'] = 'increasing'
            else:
                info['trend'] = 'stable'
        else:
            info['trend'] = 'unknown'

        # Scoring
        score = 0

        # 1. Volume spike at bounce = good (1 point)
        if multiplier >= self.config.volume_spike_multiplier:
            score += 1
            info['reason'] = "Volume spike confirms bounce"

        # 2. Declining volume during pullback = healthy (1 point)
        if info['trend'] == 'decreasing':
            score += 1
            info['reason'] = info.get('reason', '') + " | Healthy declining volume"

        if not info.get('reason'):
            info['reason'] = "Normal volume"

        return score, info

    def _score_trend(self, prices: List[float]) -> Tuple[int, Dict[str, Any]]:
        """Trend analysis for bounce context"""
        sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sum(prices) / len(prices)
        sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else sum(prices) / len(prices)

        current = prices[-1]

        info = {
            'sma_50': sma_50,
            'sma_200': sma_200,
            'price': current
        }

        # For bounce, uptrend is important (Mean Reversion)
        if current > sma_200:
            if current > sma_50:
                info['trend'] = 'uptrend'
                return 2, info
            else:
                info['trend'] = 'pullback_in_uptrend'
                return 2, info  # Pullback in uptrend = ideal for bounce
        else:
            info['trend'] = 'downtrend'
            return 0, info  # Downtrend = risky

    # =========================================================================
    # RSI DIVERGENCE SCORING (NEW)
    # =========================================================================

    def _score_rsi_divergence(
        self,
        divergence: Optional[RSIDivergenceResult]
    ) -> Tuple[float, str]:
        """
        RSI Divergence Score (0-3 points).

        Bullish divergence is a strong signal for bounce:
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
            # Bearish divergence in bounce = warning signal, but no deduction
            return 0, f"Bearish divergence detected - caution! (strength: {divergence.strength:.0%})"

        return 0, "No significant divergence"

    # =========================================================================
    # MACD SCORING (NEW)
    # =========================================================================

    def _calculate_macd(
        self,
        prices: List[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Optional[MACDResult]:
        """Calculates MACD"""
        if len(prices) < slow + signal:
            return None

        # EMA berechnen
        ema_fast = self._calculate_ema(prices, fast)
        ema_slow = self._calculate_ema(prices, slow)

        if not ema_fast or not ema_slow:
            return None

        # MACD Line
        macd_line = [f - s for f, s in zip(ema_fast[-len(ema_slow):], ema_slow)]

        # Signal Line (EMA of MACD)
        signal_line = self._calculate_ema(macd_line, signal)
        if not signal_line:
            return None

        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        histogram = current_macd - current_signal

        # Crossover Detection
        crossover = None
        if len(macd_line) >= 2 and len(signal_line) >= 2:
            prev_macd = macd_line[-2]
            prev_signal = signal_line[-2]

            if prev_macd < prev_signal and current_macd > current_signal:
                crossover = 'bullish'
            elif prev_macd > prev_signal and current_macd < current_signal:
                crossover = 'bearish'

        return MACDResult(
            macd_line=current_macd,
            signal_line=current_signal,
            histogram=histogram,
            crossover=crossover
        )

    def _score_macd(self, macd: Optional[MACDResult]) -> Tuple[float, str, str]:
        """MACD Score (0-2 points)"""
        if not macd:
            return 0, "No MACD data", "neutral"

        cfg = self.scoring_config.macd

        if macd.crossover == 'bullish':
            return cfg.weight_bullish_cross, "MACD bullish crossover", "bullish_cross"

        if macd.histogram > 0:
            return cfg.weight_bullish, "MACD histogram positive", "bullish"

        if macd.histogram < 0:
            return 0, "MACD histogram negative", "bearish"

        return 0, "MACD neutral", "neutral"

    # =========================================================================
    # STOCHASTIC SCORING (NEW)
    # =========================================================================

    def _calculate_stochastic(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        k_period: int = 14,
        d_period: int = 3
    ) -> Optional[StochasticResult]:
        """Calculates Stochastic Oscillator"""
        if len(prices) < k_period + d_period:
            return None

        # %K berechnen
        k_values = []
        for i in range(k_period, len(prices) + 1):
            period_highs = highs[i-k_period:i]
            period_lows = lows[i-k_period:i]
            period_close = prices[i-1]

            highest_high = max(period_highs)
            lowest_low = min(period_lows)

            if highest_high == lowest_low:
                k_values.append(50.0)
            else:
                k = ((period_close - lowest_low) / (highest_high - lowest_low)) * 100
                k_values.append(k)

        if len(k_values) < d_period:
            return None

        # %D = SMA of %K
        d_values = []
        for i in range(d_period, len(k_values) + 1):
            d = sum(k_values[i-d_period:i]) / d_period
            d_values.append(d)

        current_k = k_values[-1]
        current_d = d_values[-1] if d_values else current_k

        # Determine zone
        cfg = self.scoring_config.stochastic
        if current_k < cfg.oversold_threshold:
            zone = 'oversold'
        elif current_k > cfg.overbought_threshold:
            zone = 'overbought'
        else:
            zone = 'neutral'

        # Crossover Detection
        crossover = None
        if len(k_values) >= 2 and len(d_values) >= 2:
            prev_k = k_values[-2]
            prev_d = d_values[-2]

            if prev_k < prev_d and current_k > current_d:
                crossover = 'bullish'
            elif prev_k > prev_d and current_k < current_d:
                crossover = 'bearish'

        return StochasticResult(
            k=current_k,
            d=current_d,
            crossover=crossover,
            zone=zone
        )

    def _score_stochastic(self, stoch: Optional[StochasticResult]) -> Tuple[float, str, str]:
        """Stochastic Score (0-2 points)"""
        if not stoch:
            return 0, "No Stochastic data", "neutral"

        cfg = self.scoring_config.stochastic

        if stoch.zone == 'oversold':
            if stoch.crossover == 'bullish':
                return cfg.weight_oversold_cross, "Stoch oversold + bullish cross", "oversold_bullish_cross"
            return cfg.weight_oversold, f"Stoch oversold (K={stoch.k:.0f})", "oversold"

        if stoch.zone == 'overbought':
            return 0, f"Stoch overbought (K={stoch.k:.0f})", "overbought"

        return 0, f"Stoch neutral (K={stoch.k:.0f})", "neutral"

    # =========================================================================
    # KELTNER CHANNEL (NEW)
    # =========================================================================

    def _calculate_keltner_channel(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float]
    ) -> Optional[KeltnerChannelResult]:
        """Calculates Keltner Channel"""
        cfg = self.scoring_config.keltner
        min_required = max(cfg.ema_period, cfg.atr_period) + 1

        if len(prices) < min_required:
            return None

        # Calculate EMA (middle line)
        ema_values = self._calculate_ema(prices, cfg.ema_period)
        if not ema_values:
            return None
        current_ema = ema_values[-1]

        # Calculate ATR
        atr = self._calculate_atr(highs, lows, prices, cfg.atr_period)
        if atr is None or atr <= 0:
            return None

        # Calculate bands
        band_width = atr * cfg.atr_multiplier
        upper = current_ema + band_width
        lower = current_ema - band_width

        # Determine current price position
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

        # Channel width as % of price
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

    def _score_keltner(
        self,
        keltner: KeltnerChannelResult,
        current_price: float
    ) -> Tuple[float, str]:
        """Keltner Channel Score for Bounce (0-2 points)"""
        cfg = self.scoring_config.keltner
        position = keltner.price_position
        pct = keltner.percent_position

        if position == 'below_lower':
            return cfg.weight_below_lower, f"Price below Keltner Lower Band ({pct:.2f})"

        if position == 'near_lower':
            return cfg.weight_near_lower, f"Price near Keltner Lower Band ({pct:.2f})"

        if position == 'in_channel' and pct < -0.3:
            return cfg.weight_mean_reversion * 0.5, f"Bounce in lower channel area ({pct:.2f})"

        if position == 'above_upper':
            return 0, f"Price above Keltner Upper Band ({pct:.2f}) - overbought"

        return 0, f"Price in neutral channel position ({pct:.2f})"

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _calculate_ema(self, values: List[float], period: int) -> Optional[List[float]]:
        """Calculates Exponential Moving Average"""
        if len(values) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = [sum(values[:period]) / period]

        for value in values[period:]:
            ema.append((value - ema[-1]) * multiplier + ema[-1])

        return ema

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[float]:
        """Calculates Average True Range (ATR)"""
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

    def _calculate_target(self, entry: float, stop: float) -> float:
        """Calculates target based on Risk/Reward"""
        risk = entry - stop
        return entry + (risk * self.config.target_risk_reward)
