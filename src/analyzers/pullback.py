# OptionPlay - Pullback Analyzer
# ================================
# Technische Analyse für Pullback-Kandidaten

import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import logging

from .base import BaseAnalyzer

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..models.indicators import MACDResult, StochasticResult, TechnicalIndicators
    from ..models.candidates import PullbackCandidate, ScoreBreakdown
    from ..config.config_loader import PullbackScoringConfig
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength
    from models.indicators import MACDResult, StochasticResult, TechnicalIndicators
    from models.candidates import PullbackCandidate, ScoreBreakdown
    from config.config_loader import PullbackScoringConfig

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
        **kwargs
    ) -> TradeSignal:
        """
        Analysiert ein Symbol auf Pullback-Setup.
        
        Returns:
            TradeSignal mit Score und Entry-Empfehlung
        """
        # Vollständige Analyse durchführen
        candidate = self.analyze_detailed(symbol, prices, volumes, highs, lows)
        
        # In TradeSignal konvertieren
        if candidate.is_qualified():
            signal_type = SignalType.LONG
            if candidate.score >= 7:
                strength = SignalStrength.STRONG
            elif candidate.score >= 5:
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
            score=candidate.score,
            current_price=candidate.current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=self._build_reason(candidate),
            details={
                'rsi': candidate.technicals.rsi_14,
                'trend': candidate.technicals.trend,
                'support_levels': candidate.support_levels,
                'score_breakdown': candidate.score_breakdown.to_dict()
            }
        )
    
    def analyze_detailed(
        self, 
        symbol: str, 
        prices: List[float], 
        volumes: List[int], 
        highs: List[float], 
        lows: List[float]
    ) -> PullbackCandidate:
        """
        Vollständige Pullback-Analyse für ein Symbol.
        
        Args:
            symbol: Ticker-Symbol
            prices: Schlusskurse (älteste zuerst)
            volumes: Tagesvolumen
            highs: Tageshochs
            lows: Tagestiefs
            
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
        
        # Technische Indikatoren berechnen
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
        
        # Support/Resistance
        support_levels = self._find_support_levels(lows)
        resistance_levels = self._find_resistance_levels(highs)
        
        # Fibonacci
        lookback = self.config.fibonacci.lookback_days
        fib_levels = self._calculate_fibonacci(
            max(highs[-lookback:]), 
            min(lows[-lookback:])
        )
        
        # Scoring
        breakdown = ScoreBreakdown()
        
        # 1. RSI Score
        breakdown.rsi_score, breakdown.rsi_reason = self._score_rsi(rsi)
        breakdown.rsi_value = rsi
        
        # 2. Support Score
        breakdown.support_score, breakdown.support_reason = self._score_support(
            current_price, support_levels
        )
        if support_levels:
            nearest = min(support_levels, key=lambda x: abs(x - current_price))
            breakdown.support_level = nearest
            breakdown.support_distance_pct = abs(current_price - nearest) / current_price * 100
        
        # 3. Fibonacci Score
        breakdown.fibonacci_score, breakdown.fib_level, breakdown.fib_reason = \
            self._score_fibonacci(current_price, fib_levels)
        
        # 4. Moving Average Score
        breakdown.ma_score, breakdown.ma_reason = self._score_moving_averages(
            current_price, sma_20, sma_200
        )
        breakdown.price_vs_sma20 = "above" if above_sma20 else "below"
        breakdown.price_vs_sma200 = "above" if above_sma200 else "below"
        
        # 5. Volume Score
        avg_volume = int(np.mean(volumes[-self.config.volume.average_period:]))
        breakdown.volume_score, breakdown.volume_reason = self._score_volume(
            current_volume, avg_volume
        )
        breakdown.volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # 6. MACD/Stoch Signals (informativ)
        breakdown.macd_signal = self._get_macd_signal(macd_result)
        breakdown.stoch_signal = self._get_stoch_signal(stoch_result)
        
        # Total Score
        breakdown.total_score = (
            breakdown.rsi_score +
            breakdown.support_score +
            breakdown.fibonacci_score +
            breakdown.ma_score +
            breakdown.volume_score
        )
        breakdown.max_possible = self.config.max_score
        
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
        """Erstellt Begründung aus Score-Breakdown"""
        reasons = []
        
        if candidate.score_breakdown.rsi_score > 0:
            reasons.append(f"RSI oversold ({candidate.technicals.rsi_14:.1f})")
        
        if candidate.score_breakdown.support_score > 0:
            reasons.append("Near support")
        
        if candidate.score_breakdown.ma_score > 0:
            reasons.append("Dip in uptrend")
        
        if candidate.score_breakdown.fibonacci_score > 0:
            reasons.append(f"At Fib {candidate.score_breakdown.fib_level}")
        
        return " + ".join(reasons) if reasons else "Weak setup"
    
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
    
    def _find_support_levels(self, lows: List[float], window: int = 20) -> List[float]:
        """Findet Support-Levels (Swing Lows)"""
        lookback = min(self.config.support.lookback_days, len(lows))
        
        min_required = 2 * window + 1
        if lookback < min_required:
            logger.debug(
                f"Not enough data for support detection: {lookback} < {min_required}"
            )
            return []
        
        supports = []
        start_idx = len(lows) - lookback
        
        for i in range(window, lookback - window):
            abs_idx = start_idx + i
            window_start = abs_idx - window
            window_end = abs_idx + window + 1
            
            local_min = min(lows[window_start:window_end])
            
            if lows[abs_idx] == local_min:
                supports.append(lows[abs_idx])
        
        unique_supports = sorted(set(supports))
        return unique_supports[-3:] if unique_supports else []
    
    def _find_resistance_levels(self, highs: List[float], window: int = 20) -> List[float]:
        """Findet Resistance-Levels (Swing Highs)"""
        lookback = min(60, len(highs))
        
        min_required = 2 * window + 1
        if lookback < min_required:
            return []
        
        resistances = []
        start_idx = len(highs) - lookback
        
        for i in range(window, lookback - window):
            abs_idx = start_idx + i
            window_start = abs_idx - window
            window_end = abs_idx + window + 1
            
            local_max = max(highs[window_start:window_end])
            
            if highs[abs_idx] == local_max:
                resistances.append(highs[abs_idx])
        
        unique_resistances = sorted(set(resistances))
        return unique_resistances[:3] if unique_resistances else []
    
    # =========================================================================
    # SCORING
    # =========================================================================
    
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
    
    def _score_volume(self, current: int, average: int) -> Tuple[float, str]:
        """Volume Score (0-1 Punkt)"""
        if average == 0:
            return 0, "No average volume data"
        
        ratio = current / average
        
        if ratio >= self.config.volume.spike_multiplier:
            return 1, f"Volume spike: {ratio:.1f}x avg"
        else:
            return 0, f"Volume normal: {ratio:.1f}x avg"
    
    # =========================================================================
    # SIGNAL HELPER
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
