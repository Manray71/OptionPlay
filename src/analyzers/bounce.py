# OptionPlay - Bounce Analyzer
# ==============================
# Analysiert Bounces von Support-Levels
#
# Strategie: Kaufe wenn Aktie von etabliertem Support abprallt
# - Mean-Reversion Signal
# - Funktioniert am besten bei Range-gebundenen Aktien
# - Risiko: Support bricht, Trend setzt sich fort

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
import logging

from .base import BaseAnalyzer
from .context import AnalysisContext

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength

logger = logging.getLogger(__name__)


@dataclass
class BounceConfig:
    """Konfiguration für Bounce Analyzer"""
    # Support Detection
    support_lookback_days: int = 60
    support_touches_min: int = 2  # Mindestens 2x getestet
    support_tolerance_pct: float = 1.5  # Support-Zone Toleranz
    
    # Bounce Confirmation
    bounce_min_pct: float = 1.0  # Mindest-Bounce vom Low
    volume_confirmation: bool = True
    volume_spike_multiplier: float = 1.3
    
    # RSI für Oversold
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


class BounceAnalyzer(BaseAnalyzer):
    """
    Analysiert Aktien auf Support-Bounces.
    
    Scoring-Kriterien:
    - Support-Test (Preis nahe etabliertem Support): 3 Punkte
    - RSI oversold (< 40): 2 Punkte
    - Bullish Candlestick (Hammer, Engulfing): 2 Punkte
    - Volumen-Bestätigung beim Bounce: 1 Punkt
    - Aufwärtstrend intakt (über SMA200): 2 Punkte
    
    Verwendung:
        analyzer = BounceAnalyzer()
        signal = analyzer.analyze("AAPL", prices, volumes, highs, lows)
        
        if signal.is_actionable:
            print(f"Bounce Signal: {signal.score}/10")
    """
    
    def __init__(self, config: Optional[BounceConfig] = None):
        self.config = config or BounceConfig()
    
    @property
    def strategy_name(self) -> str:
        return "bounce"
    
    @property
    def description(self) -> str:
        return "Support Bounce - Kaufe bei Abprall von etabliertem Support-Level"
    
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
        Analysiert ein Symbol auf Support-Bounce.

        Args:
            symbol: Ticker-Symbol
            prices: Schlusskurse (älteste zuerst)
            volumes: Tagesvolumen
            highs: Tageshochs
            lows: Tagestiefs
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            TradeSignal mit Bounce-Bewertung
        """
        # Input-Validierung
        min_data = max(self.config.support_lookback_days, 60)
        self.validate_inputs(prices, volumes, highs, lows, min_length=min_data)

        current_price = prices[-1]
        current_low = lows[-1]

        # Score-Komponenten
        score_breakdown = {}
        total_score = 0
        reasons = []
        warnings = []

        # 1. Support Detection & Test (3 Punkte)
        # Use context if available
        if context and context.support_levels:
            support_levels = context.support_levels
        else:
            support_levels = self._find_support_levels(lows)
        support_score, support_info = self._score_support_test(
            current_low, current_price, support_levels
        )
        score_breakdown['support'] = support_score
        total_score += support_score
        
        if support_score == 0:
            # Kein Support-Test = neutrales Signal
            return self.create_neutral_signal(
                symbol, current_price,
                f"Kein Support-Test. Nächster Support bei ${support_info.get('nearest_support', 'N/A')}"
            )
        
        reasons.append(f"Support-Test bei ${support_info['tested_support']:.2f}")
        
        # 2. RSI Oversold (2 Punkte)
        rsi_score, rsi_value = self._score_rsi_oversold(prices)
        score_breakdown['rsi'] = rsi_score
        total_score += rsi_score
        
        if rsi_score > 0:
            reasons.append(f"RSI oversold ({rsi_value:.0f})")
        else:
            warnings.append(f"RSI nicht oversold ({rsi_value:.0f})")
        
        # 3. Bullish Candlestick (2 Punkte)
        candle_score, candle_info = self._score_candlestick_pattern(
            prices, highs, lows
        )
        score_breakdown['candlestick'] = candle_score
        total_score += candle_score
        
        if candle_score > 0:
            reasons.append(f"Bullish Pattern: {candle_info['pattern']}")
        
        # 4. Volumen-Bestätigung (1 Punkt)
        vol_score, vol_info = self._score_volume(volumes)
        score_breakdown['volume'] = vol_score
        total_score += vol_score
        
        if vol_score > 0:
            reasons.append("Erhöhtes Volumen beim Bounce")
        
        # 5. Trend-Check (2 Punkte)
        trend_score, trend_info = self._score_trend(prices)
        score_breakdown['trend'] = trend_score
        total_score += trend_score
        
        if trend_score >= 2:
            reasons.append("Aufwärtstrend intakt (über SMA200)")
        elif trend_score == 1:
            reasons.append("Neutraler Trend")
        else:
            warnings.append("Abwärtstrend - erhöhtes Risiko")
        
        # Signal-Stärke bestimmen
        if total_score >= 8:
            strength = SignalStrength.STRONG
        elif total_score >= 6:
            strength = SignalStrength.MODERATE
        elif total_score >= 4:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE
        
        # Entry/Stop/Target berechnen
        entry_price = current_price
        support = support_info.get('tested_support', current_low)
        stop_loss = support * (1 - self.config.stop_below_support_pct / 100)
        target_price = self._calculate_target(entry_price, stop_loss)
        
        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.LONG if total_score >= self.config.min_score_for_signal else SignalType.NEUTRAL,
            strength=strength,
            score=min(total_score, self.config.max_score),
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=" | ".join(reasons),
            details={
                'score_breakdown': score_breakdown,
                'support_levels': support_levels[:3],  # Top 3
                'support_info': support_info,
                'trend_info': trend_info,
                'rsi': rsi_value,
                'candle_info': candle_info
            },
            warnings=warnings
        )
    
    def _find_support_levels(self, lows: List[float]) -> List[float]:
        """
        Findet Support-Levels durch Swing-Low Detection.
        
        Returns:
            Liste von Support-Levels, sortiert nach Stärke
        """
        lookback = self.config.support_lookback_days
        window = 5  # Swing-Detection Window
        
        if len(lows) < lookback:
            return []
        
        recent_lows = lows[-lookback:]
        swing_lows = []
        
        # Finde Swing-Lows (lokale Minima)
        for i in range(window, len(recent_lows) - window):
            is_swing_low = all(
                recent_lows[i] <= recent_lows[i-j] and 
                recent_lows[i] <= recent_lows[i+j]
                for j in range(1, window + 1)
            )
            if is_swing_low:
                swing_lows.append(recent_lows[i])
        
        if not swing_lows:
            return []
        
        # Clustere ähnliche Levels
        tolerance = self.config.support_tolerance_pct / 100
        clustered = self._cluster_levels(swing_lows, tolerance)
        
        # Sortiere nach Häufigkeit (stärkste zuerst)
        sorted_supports = sorted(clustered.items(), key=lambda x: -x[1])
        
        return [level for level, count in sorted_supports if count >= self.config.support_touches_min]
    
    def _cluster_levels(
        self, 
        levels: List[float], 
        tolerance: float
    ) -> Dict[float, int]:
        """Clustert ähnliche Price-Levels"""
        if not levels:
            return {}
        
        clusters: Dict[float, int] = {}
        
        for level in levels:
            # Finde existierenden Cluster
            found = False
            for cluster_level in list(clusters.keys()):
                if abs(level - cluster_level) / cluster_level <= tolerance:
                    # Füge zu existierendem Cluster hinzu
                    avg_level = (cluster_level * clusters[cluster_level] + level) / (clusters[cluster_level] + 1)
                    count = clusters[cluster_level] + 1
                    del clusters[cluster_level]
                    clusters[avg_level] = count
                    found = True
                    break
            
            if not found:
                clusters[level] = 1
        
        return clusters
    
    def _score_support_test(
        self, 
        current_low: float,
        current_price: float,
        support_levels: List[float]
    ) -> Tuple[int, Dict[str, Any]]:
        """Prüft ob aktueller Preis Support testet"""
        tolerance = self.config.support_tolerance_pct / 100
        
        info = {
            'current_low': current_low,
            'current_price': current_price,
            'supports_found': len(support_levels)
        }
        
        if not support_levels:
            info['nearest_support'] = None
            return 0, info
        
        # Finde nächsten Support
        nearest_support = min(support_levels, key=lambda s: abs(current_low - s))
        info['nearest_support'] = nearest_support
        
        # Prüfe ob Low den Support getestet hat
        distance_pct = abs(current_low - nearest_support) / nearest_support
        
        if distance_pct <= tolerance:
            # Support getestet
            info['tested_support'] = nearest_support
            info['distance_pct'] = distance_pct * 100
            
            # Prüfe ob Bounce (Close über Low)
            bounce_pct = (current_price - current_low) / current_low * 100
            info['bounce_pct'] = bounce_pct
            
            if bounce_pct >= self.config.bounce_min_pct:
                return 3, info  # Volle Punktzahl
            else:
                return 2, info  # Support getestet, aber schwacher Bounce
        
        # Nahe am Support aber nicht getestet
        if distance_pct <= tolerance * 2:
            info['near_support'] = True
            return 1, info
        
        return 0, info
    
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
        """Erkennt bullische Candlestick-Patterns"""
        if len(prices) < 3:
            return 0, {'pattern': None}
        
        # Letzte Kerze
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
                return 2 if body > 0 else 1, info  # Grüner Hammer = besser
        
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
            info['bullish'] = False  # Neutral, aber am Support relevant
            return 1, info
        
        # Bullish Kerze (grün)
        if body > 0:
            info['pattern'] = 'Bullish Candle'
            info['bullish'] = True
            return 1, info
        
        return 0, info
    
    def _score_volume(self, volumes: List[int]) -> Tuple[int, Dict[str, Any]]:
        """Volumen-Analyse"""
        avg_period = 20
        
        if len(volumes) < avg_period + 1:
            return 0, {}
        
        avg_volume = sum(volumes[-avg_period-1:-1]) / avg_period
        current_volume = volumes[-1]
        
        multiplier = current_volume / avg_volume if avg_volume > 0 else 0
        
        info = {
            'current_volume': current_volume,
            'avg_volume': avg_volume,
            'multiplier': multiplier
        }
        
        if multiplier >= self.config.volume_spike_multiplier:
            return 1, info
        
        return 0, info
    
    def _score_trend(self, prices: List[float]) -> Tuple[int, Dict[str, Any]]:
        """Trend-Analyse für Bounce-Kontext"""
        sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sum(prices) / len(prices)
        sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else sum(prices) / len(prices)
        
        current = prices[-1]
        
        info = {
            'sma_50': sma_50,
            'sma_200': sma_200,
            'price': current
        }
        
        # Für Bounce ist Aufwärtstrend wichtig (Mean Reversion)
        if current > sma_200:
            if current > sma_50:
                info['trend'] = 'uptrend'
                return 2, info
            else:
                info['trend'] = 'pullback_in_uptrend'
                return 2, info  # Pullback in Aufwärtstrend = ideal für Bounce
        else:
            info['trend'] = 'downtrend'
            return 0, info  # Downtrend = riskant
    
    def _calculate_target(self, entry: float, stop: float) -> float:
        """Berechnet Target basierend auf Risk/Reward"""
        risk = entry - stop
        return entry + (risk * self.config.target_risk_reward)
