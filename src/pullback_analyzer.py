# OptionPlay - Pullback Analyzer
# ================================
# Technische Analyse für Pullback-Kandidaten

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import logging

# Import mit Fallback für beide Modi (Package und Standalone)
try:
    from .config_loader import PullbackScoringConfig
except ImportError:
    from config_loader import PullbackScoringConfig

logger = logging.getLogger(__name__)


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class MACDResult:
    """MACD Indicator Result"""
    macd_line: float
    signal_line: float
    histogram: float
    crossover: Optional[str] = None  # 'bullish', 'bearish', or None
    
    def to_dict(self) -> Dict:
        return {
            'macd': round(self.macd_line, 4),
            'signal': round(self.signal_line, 4),
            'histogram': round(self.histogram, 4),
            'crossover': self.crossover
        }


@dataclass
class StochasticResult:
    """Stochastic Oscillator Result"""
    k: float  # %K (fast)
    d: float  # %D (slow)
    crossover: Optional[str] = None  # 'bullish', 'bearish', or None
    zone: Optional[str] = None  # 'oversold', 'overbought', 'neutral'
    
    def to_dict(self) -> Dict:
        return {
            'k': round(self.k, 2),
            'd': round(self.d, 2),
            'crossover': self.crossover,
            'zone': self.zone
        }


@dataclass
class TechnicalIndicators:
    """Alle technischen Indikatoren für ein Symbol"""
    rsi_14: float
    sma_20: float
    sma_50: Optional[float]
    sma_200: float
    macd: Optional[MACDResult]
    stochastic: Optional[StochasticResult]
    
    # Trend-Status
    above_sma20: bool
    above_sma50: Optional[bool]
    above_sma200: bool
    trend: str  # 'uptrend', 'downtrend', 'sideways'
    
    def to_dict(self) -> Dict:
        return {
            'rsi_14': round(self.rsi_14, 2),
            'sma_20': round(self.sma_20, 2),
            'sma_50': round(self.sma_50, 2) if self.sma_50 else None,
            'sma_200': round(self.sma_200, 2),
            'macd': self.macd.to_dict() if self.macd else None,
            'stochastic': self.stochastic.to_dict() if self.stochastic else None,
            'above_sma20': self.above_sma20,
            'above_sma50': self.above_sma50,
            'above_sma200': self.above_sma200,
            'trend': self.trend
        }


@dataclass
class ScoreBreakdown:
    """Detaillierte Aufschlüsselung des Pullback-Scores"""
    rsi_score: float = 0
    rsi_value: float = 0
    rsi_reason: str = ""
    
    support_score: float = 0
    support_level: Optional[float] = None
    support_distance_pct: float = 0
    support_reason: str = ""
    
    fibonacci_score: float = 0
    fib_level: Optional[str] = None
    fib_reason: str = ""
    
    ma_score: float = 0
    price_vs_sma20: str = ""
    price_vs_sma200: str = ""
    ma_reason: str = ""
    
    volume_score: float = 0
    volume_ratio: float = 0
    volume_reason: str = ""
    
    # NEU: MACD und Stochastik (informativ, kein Score-Einfluss)
    macd_signal: Optional[str] = None  # 'bullish', 'bearish', 'neutral'
    stoch_signal: Optional[str] = None  # 'oversold', 'overbought', 'neutral'
    
    total_score: float = 0
    max_possible: int = 10
    
    def to_dict(self) -> Dict:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 5,
            'components': {
                'rsi': {'score': self.rsi_score, 'value': round(self.rsi_value, 2), 'reason': self.rsi_reason},
                'support': {'score': self.support_score, 'level': self.support_level, 'distance_pct': round(self.support_distance_pct, 2), 'reason': self.support_reason},
                'fibonacci': {'score': self.fibonacci_score, 'level': self.fib_level, 'reason': self.fib_reason},
                'moving_averages': {'score': self.ma_score, 'vs_sma20': self.price_vs_sma20, 'vs_sma200': self.price_vs_sma200, 'reason': self.ma_reason},
                'volume': {'score': self.volume_score, 'ratio': round(self.volume_ratio, 2), 'reason': self.volume_reason}
            },
            'signals': {
                'macd': self.macd_signal,
                'stochastic': self.stoch_signal
            }
        }


@dataclass
class PullbackCandidate:
    """Vollständige Pullback-Analyse eines Symbols"""
    symbol: str
    current_price: float
    score: float
    score_breakdown: ScoreBreakdown
    
    # Technische Indikatoren
    technicals: TechnicalIndicators
    
    # Support/Resistance
    support_levels: List[float]
    resistance_levels: List[float]
    fib_levels: Dict[str, float]
    
    # Volume
    avg_volume: int
    current_volume: int
    
    # Meta
    timestamp: datetime = field(default_factory=datetime.now)
    data_source: str = "calculated"
    
    # Für Rückwärtskompatibilität
    @property
    def rsi_14(self) -> float:
        return self.technicals.rsi_14
    
    @property
    def sma_20(self) -> float:
        return self.technicals.sma_20
    
    @property
    def sma_200(self) -> float:
        return self.technicals.sma_200
    
    def is_qualified(self, min_score: int = 5) -> bool:
        return self.score >= min_score
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'price': round(self.current_price, 2),
            'score': self.score,
            'qualified': self.is_qualified(),
            'technicals': self.technicals.to_dict(),
            'support_levels': [round(s, 2) for s in self.support_levels],
            'resistance_levels': [round(r, 2) for r in self.resistance_levels],
            'fib_levels': {k: round(v, 2) for k, v in self.fib_levels.items()},
            'volume': {
                'current': self.current_volume,
                'average': self.avg_volume,
                'ratio': round(self.current_volume / self.avg_volume, 2) if self.avg_volume > 0 else 0
            },
            'score_breakdown': self.score_breakdown.to_dict(),
            'timestamp': self.timestamp.isoformat()
        }


# =============================================================================
# ANALYZER CLASS
# =============================================================================

class PullbackAnalyzer:
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
    
    def _validate_inputs(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float]
    ) -> None:
        """
        Validiert alle Input-Arrays auf Konsistenz und Gültigkeit.
        
        Raises:
            ValueError: Bei ungültigen Inputs
        """
        # Check 1: Alle Arrays müssen gleiche Länge haben
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
        
        # Check 2: Keine None-Werte in numerischen Arrays
        for name, arr in [('prices', prices), ('highs', highs), ('lows', lows)]:
            if any(v is None for v in arr):
                raise ValueError(f"{name} contains None values")
        
        # Check 3: Preise müssen positiv sein
        if any(p <= 0 for p in prices):
            raise ValueError("All prices must be positive (> 0)")
        
        # Check 4: Highs müssen >= Lows sein
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
        
        # Check 5: Close muss zwischen High und Low liegen (mit kleiner Toleranz)
        tolerance = 0.0001  # Für Rundungsfehler
        for i, (p, h, l) in enumerate(zip(prices, highs, lows)):
            if p > h * (1 + tolerance) or p < l * (1 - tolerance):
                logger.warning(
                    f"{symbol}: Close price {p} outside High/Low range "
                    f"[{l}, {h}] at index {i}"
                )
        
        logger.debug(f"Input validation passed for {symbol}: {len(prices)} data points")
    
    def analyze(
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
        # =================================================================
        # INPUT VALIDIERUNG
        # =================================================================
        self._validate_inputs(symbol, prices, volumes, highs, lows)
        
        min_required = self.config.moving_averages.long_period
        if len(prices) < min_required:
            raise ValueError(f"Need {min_required} data points, got {len(prices)}")
        
        current_price = prices[-1]
        current_volume = volumes[-1]
        
        # =================================================================
        # TECHNISCHE INDIKATOREN BERECHNEN
        # =================================================================
        
        # RSI
        rsi = self._calculate_rsi(prices, self.config.rsi.period)
        
        # Moving Averages
        sma_20 = self._calculate_sma(prices, self.config.moving_averages.short_period)
        sma_50 = self._calculate_sma(prices, 50) if len(prices) >= 50 else None
        sma_200 = self._calculate_sma(prices, self.config.moving_averages.long_period)
        
        # MACD
        macd_result = self._calculate_macd(prices)
        
        # Stochastik
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
        
        # =================================================================
        # SUPPORT/RESISTANCE
        # =================================================================
        
        support_levels = self._find_support_levels(lows)
        resistance_levels = self._find_resistance_levels(highs)
        
        # Fibonacci
        lookback = self.config.fibonacci.lookback_days
        fib_levels = self._calculate_fibonacci(
            max(highs[-lookback:]), 
            min(lows[-lookback:])
        )
        
        # =================================================================
        # SCORING
        # =================================================================
        
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
        ema_values = [np.mean(prices[:period])]  # Erster Wert ist SMA
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema_values[-1] * (1 - multiplier))
            ema_values.append(ema)
        
        return ema_values
    
    def _calculate_macd(self, prices: List[float]) -> Optional[MACDResult]:
        """
        MACD (Moving Average Convergence Divergence)
        
        - MACD Line = EMA(12) - EMA(26)
        - Signal Line = EMA(9) of MACD Line
        - Histogram = MACD Line - Signal Line
        
        Die EMA-Berechnung gibt Arrays zurück, die kürzer sind als die Input-Preise:
        - ema_fast hat len(prices) - MACD_FAST + 1 Elemente
        - ema_slow hat len(prices) - MACD_SLOW + 1 Elemente
        
        Beide EMAs repräsentieren Werte ab ihrem jeweiligen Startpunkt.
        Für die MACD-Line müssen wir sie korrekt alignen.
        """
        min_required = self.MACD_SLOW + self.MACD_SIGNAL
        if len(prices) < min_required:
            return None
        
        # EMA berechnen
        # ema_fast[0] entspricht dem EMA ab prices[MACD_FAST-1] (Tag 12)
        # ema_slow[0] entspricht dem EMA ab prices[MACD_SLOW-1] (Tag 26)
        ema_fast = self._calculate_ema(prices, self.MACD_FAST)
        ema_slow = self._calculate_ema(prices, self.MACD_SLOW)
        
        # MACD Line: Differenz der EMAs
        # ema_slow[i] entspricht dem Zeitpunkt prices[MACD_SLOW - 1 + i]
        # Für denselben Zeitpunkt brauchen wir ema_fast[MACD_SLOW - 1 + i - (MACD_FAST - 1)]
        #                                      = ema_fast[i + MACD_SLOW - MACD_FAST]
        offset = self.MACD_SLOW - self.MACD_FAST
        
        macd_line = []
        for i in range(len(ema_slow)):
            fast_idx = i + offset
            if fast_idx < len(ema_fast):
                macd_line.append(ema_fast[fast_idx] - ema_slow[i])
        
        if len(macd_line) < self.MACD_SIGNAL:
            return None
        
        # Signal Line (EMA der MACD Line)
        signal_line = self._calculate_ema(macd_line, self.MACD_SIGNAL)
        
        # Die Signal-Line ist kürzer als die MACD-Line
        # signal_line[i] entspricht macd_line[MACD_SIGNAL - 1 + i]
        # Für Crossover-Erkennung brauchen wir alignierte Werte
        signal_offset = self.MACD_SIGNAL - 1
        
        # Aktuelle Werte (letzte verfügbare)
        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        histogram = current_macd - current_signal
        
        # Crossover erkennen
        # Wir vergleichen die letzten beiden Zeitpunkte wo beide verfügbar sind
        crossover = None
        if len(signal_line) >= 2:
            # signal_line[-2] entspricht macd_line[-2] (durch die Alignment-Logik)
            # signal_line[-1] entspricht macd_line[-1]
            prev_macd = macd_line[-(len(signal_line) - len(signal_line) + 2)]  # = macd_line[-2] relativ zu signal
            prev_macd = macd_line[signal_offset + len(signal_line) - 2]
            curr_macd = macd_line[signal_offset + len(signal_line) - 1]
            
            # Einfacher: Die letzten beiden Signal-Werte mit den korrespondierenden MACD-Werten
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
        """
        Stochastik Oszillator
        
        %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
        %D = SMA(%K, 3)
        
        Smoothed Stochastic verwendet SMA für %K
        
        Args:
            highs: Tageshochs (gleiche Länge wie lows und closes)
            lows: Tagestiefs
            closes: Schlusskurse
            
        Returns:
            StochasticResult oder None bei unzureichenden Daten
        """
        # Input-Validierung (Arrays sollten bereits in analyze() validiert sein,
        # aber wir prüfen nochmal für den Fall eines direkten Aufrufs)
        if len(highs) != len(lows) or len(lows) != len(closes):
            logger.warning(
                f"Stochastic: Input arrays must have same length. "
                f"Got highs={len(highs)}, lows={len(lows)}, closes={len(closes)}"
            )
            return None
        
        min_required = self.STOCH_K + self.STOCH_D + self.STOCH_SMOOTH
        if len(closes) < min_required:
            return None
        
        # Raw %K berechnen
        raw_k = []
        for i in range(self.STOCH_K - 1, len(closes)):
            period_high = max(highs[i - self.STOCH_K + 1:i + 1])
            period_low = min(lows[i - self.STOCH_K + 1:i + 1])
            
            if period_high == period_low:
                raw_k.append(50.0)
            else:
                k = 100 * (closes[i] - period_low) / (period_high - period_low)
                raw_k.append(k)
        
        # Smoothed %K (SMA von Raw %K)
        smooth_k = []
        for i in range(self.STOCH_SMOOTH - 1, len(raw_k)):
            smooth_k.append(np.mean(raw_k[i - self.STOCH_SMOOTH + 1:i + 1]))
        
        # %D (SMA von Smoothed %K)
        d_values = []
        for i in range(self.STOCH_D - 1, len(smooth_k)):
            d_values.append(np.mean(smooth_k[i - self.STOCH_D + 1:i + 1]))
        
        if not smooth_k or not d_values:
            return None
        
        current_k = smooth_k[-1]
        current_d = d_values[-1]
        
        # Crossover erkennen
        crossover = None
        if len(smooth_k) >= 2 and len(d_values) >= 2:
            prev_diff = smooth_k[-2] - d_values[-2]
            curr_diff = smooth_k[-1] - d_values[-1]
            
            if prev_diff < 0 and curr_diff > 0:
                crossover = 'bullish'
            elif prev_diff > 0 and curr_diff < 0:
                crossover = 'bearish'
        
        # Zone bestimmen
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
        """
        Findet Support-Levels (Swing Lows) als lokale Minima.
        
        Ein Swing Low ist ein Tief, das niedriger ist als alle Tiefs
        in einem Fenster von 'window' Tagen auf beiden Seiten.
        
        Args:
            lows: Liste der Tagestiefs (älteste zuerst)
            window: Fenstergröße für lokale Minima-Erkennung
            
        Returns:
            Liste der 3 nächsten Support-Levels (sortiert aufsteigend)
        """
        lookback = min(self.config.support.lookback_days, len(lows))
        
        # Benötigen mindestens 2*window + 1 Datenpunkte für sinnvolle Analyse
        min_required = 2 * window + 1
        if lookback < min_required:
            logger.debug(
                f"Not enough data for support detection: {lookback} < {min_required}. "
                f"Returning empty list."
            )
            return []
        
        supports = []
        
        # Arbeite mit absoluten Indizes für Klarheit
        # Wir analysieren die letzten 'lookback' Werte
        start_idx = len(lows) - lookback
        
        for i in range(window, lookback - window):
            abs_idx = start_idx + i
            
            # Finde das Minimum im Fenster [abs_idx - window, abs_idx + window]
            # +1 für inklusives Ende
            window_start = abs_idx - window
            window_end = abs_idx + window + 1
            
            local_min = min(lows[window_start:window_end])
            
            # Ist der aktuelle Punkt das lokale Minimum?
            if lows[abs_idx] == local_min:
                supports.append(lows[abs_idx])
        
        # Deduplizieren und die 3 höchsten (nächsten zum aktuellen Preis) zurückgeben
        unique_supports = sorted(set(supports))
        return unique_supports[-3:] if unique_supports else []
    
    def _find_resistance_levels(self, highs: List[float], window: int = 20) -> List[float]:
        """
        Findet Resistance-Levels (Swing Highs) als lokale Maxima.
        
        Ein Swing High ist ein Hoch, das höher ist als alle Hochs
        in einem Fenster von 'window' Tagen auf beiden Seiten.
        
        Args:
            highs: Liste der Tageshochs (älteste zuerst)
            window: Fenstergröße für lokale Maxima-Erkennung
            
        Returns:
            Liste der 3 nächsten Resistance-Levels (sortiert absteigend)
        """
        lookback = min(60, len(highs))
        
        # Benötigen mindestens 2*window + 1 Datenpunkte für sinnvolle Analyse
        min_required = 2 * window + 1
        if lookback < min_required:
            logger.debug(
                f"Not enough data for resistance detection: {lookback} < {min_required}. "
                f"Returning empty list."
            )
            return []
        
        resistances = []
        
        # Arbeite mit absoluten Indizes für Klarheit
        start_idx = len(highs) - lookback
        
        for i in range(window, lookback - window):
            abs_idx = start_idx + i
            
            # Finde das Maximum im Fenster [abs_idx - window, abs_idx + window]
            window_start = abs_idx - window
            window_end = abs_idx + window + 1
            
            local_max = max(highs[window_start:window_end])
            
            # Ist der aktuelle Punkt das lokale Maximum?
            if highs[abs_idx] == local_max:
                resistances.append(highs[abs_idx])
        
        # Deduplizieren und die 3 niedrigsten (nächsten zum aktuellen Preis) zurückgeben
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
        
        # Dip im Aufwärtstrend = ideal für Bull-Put-Spread
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
