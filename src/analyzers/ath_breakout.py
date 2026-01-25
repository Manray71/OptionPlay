# OptionPlay - ATH Breakout Analyzer
# ====================================
# Analysiert Ausbrüche auf neue All-Time-Highs
#
# Strategie: Kaufe wenn Aktie aus Konsolidierung auf neues ATH ausbricht
# - Starkes Momentum-Signal
# - Funktioniert am besten bei Qualitätsaktien in Aufwärtstrends
# - Risiko: False Breakouts, überkaufte Bedingungen

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import logging

from .base import BaseAnalyzer
from .context import AnalysisContext

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength

logger = logging.getLogger(__name__)


@dataclass
class ATHBreakoutConfig:
    """Konfiguration für ATH Breakout Analyzer"""
    # ATH Detection
    ath_lookback_days: int = 252  # 1 Jahr für ATH
    consolidation_days: int = 20  # Mindest-Konsolidierungszeit
    breakout_threshold_pct: float = 1.0  # Min % über altem ATH
    
    # Volume Confirmation
    volume_spike_multiplier: float = 1.5  # Volumen muss 1.5x Durchschnitt sein
    volume_avg_period: int = 20
    
    # Technical Filters
    rsi_max: float = 80.0  # Nicht kaufen wenn zu überkauft
    rsi_period: int = 14
    min_uptrend_days: int = 50  # SMA50 muss aufwärts zeigen
    
    # Scoring
    max_score: int = 10
    min_score_for_signal: int = 6


class ATHBreakoutAnalyzer(BaseAnalyzer):
    """
    Analysiert Aktien auf ATH-Breakouts.
    
    Scoring-Kriterien:
    - ATH-Breakout (neues Hoch nach Konsolidierung): 3 Punkte
    - Volumen-Bestätigung: 2 Punkte
    - Starker Aufwärtstrend (SMA20 > SMA50 > SMA200): 2 Punkte
    - RSI nicht überkauft (< 70): 1 Punkt
    - Relative Stärke (besser als SPY): 2 Punkte
    
    Verwendung:
        analyzer = ATHBreakoutAnalyzer()
        signal = analyzer.analyze("AAPL", prices, volumes, highs, lows)
        
        if signal.is_actionable:
            print(f"Breakout Signal: {signal.score}/10")
    """
    
    def __init__(self, config: Optional[ATHBreakoutConfig] = None):
        self.config = config or ATHBreakoutConfig()
    
    @property
    def strategy_name(self) -> str:
        return "ath_breakout"
    
    @property
    def description(self) -> str:
        return "All-Time-High Breakout - Kaufe bei Ausbruch auf neues ATH mit Volumen-Bestätigung"
    
    def analyze(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        spy_prices: Optional[List[float]] = None,
        context: Optional[AnalysisContext] = None,
        **kwargs
    ) -> TradeSignal:
        """
        Analysiert ein Symbol auf ATH-Breakout.

        Args:
            symbol: Ticker-Symbol
            prices: Schlusskurse (älteste zuerst)
            volumes: Tagesvolumen
            highs: Tageshochs
            lows: Tagestiefs
            spy_prices: Optional SPY-Preise für Relative Strength
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            TradeSignal mit Breakout-Bewertung
        """
        # Input-Validierung
        min_data = max(self.config.ath_lookback_days, 60)
        self.validate_inputs(prices, volumes, highs, lows, min_length=min_data)
        
        current_price = prices[-1]
        current_high = highs[-1]
        
        # Score-Komponenten
        score_breakdown = {}
        total_score = 0
        reasons = []
        warnings = []
        
        # 1. ATH-Breakout Detection (3 Punkte)
        ath_score, ath_info = self._score_ath_breakout(highs, current_high)
        score_breakdown['ath_breakout'] = ath_score
        total_score += ath_score
        
        if ath_score > 0:
            reasons.append(f"Neues {ath_info['lookback']}-Tage-Hoch (+{ath_info['pct_above_old']:.1f}%)")
        else:
            # Kein Breakout = neutrales Signal
            return self.create_neutral_signal(
                symbol, current_price, 
                f"Kein ATH-Breakout. Aktuell {ath_info.get('pct_below_ath', 0):.1f}% unter ATH"
            )
        
        # 2. Volumen-Bestätigung (2 Punkte)
        vol_score, vol_info = self._score_volume_confirmation(volumes)
        score_breakdown['volume'] = vol_score
        total_score += vol_score
        
        if vol_score > 0:
            reasons.append(f"Volumen {vol_info['multiplier']:.1f}x über Durchschnitt")
        else:
            warnings.append("Schwache Volumen-Bestätigung")
        
        # 3. Trend-Analyse (2 Punkte)
        trend_score, trend_info = self._score_trend(prices)
        score_breakdown['trend'] = trend_score
        total_score += trend_score
        
        if trend_score >= 2:
            reasons.append("Starker Aufwärtstrend (SMA20 > SMA50 > SMA200)")
        elif trend_score == 1:
            reasons.append("Moderater Aufwärtstrend")
        
        # 4. RSI Check (1 Punkt)
        rsi_score, rsi_value = self._score_rsi(prices)
        score_breakdown['rsi'] = rsi_score
        total_score += rsi_score
        
        if rsi_score == 0:
            warnings.append(f"RSI überkauft ({rsi_value:.0f})")
        
        # 5. Relative Strength (2 Punkte)
        rs_score = 0
        if spy_prices and len(spy_prices) >= 20:
            rs_score, rs_info = self._score_relative_strength(prices, spy_prices)
            score_breakdown['relative_strength'] = rs_score
            total_score += rs_score
            
            if rs_score > 0:
                reasons.append(f"Relative Stärke: +{rs_info['outperformance']:.1f}% vs SPY")
        
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
        stop_loss = self._calculate_stop_loss(lows, current_price)
        target_price = self._calculate_target(current_price, stop_loss)
        
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
                'ath_info': ath_info,
                'trend_info': trend_info,
                'rsi': rsi_value
            },
            warnings=warnings
        )
    
    def _score_ath_breakout(
        self, 
        highs: List[float], 
        current_high: float
    ) -> tuple[int, Dict[str, Any]]:
        """
        Prüft auf ATH-Breakout.
        
        Returns:
            (score, info_dict)
        """
        lookback = min(self.config.ath_lookback_days, len(highs) - 1)
        
        # Altes ATH: Maximum der Highs VOR der Konsolidierungsperiode
        # Wir schauen auf Highs von vor der letzten consolidation_days + 1 Tag
        consolidation_start = -self.config.consolidation_days - 1
        if abs(consolidation_start) >= len(highs):
            consolidation_start = -len(highs) + 1
        
        # Altes ATH = Maximum vor der Konsolidierung
        old_ath = max(highs[-lookback:consolidation_start])
        
        # Prüfe ob neues ATH
        threshold = old_ath * (1 + self.config.breakout_threshold_pct / 100)
        
        info = {
            'lookback': lookback,
            'old_ath': old_ath,
            'current_high': current_high,
            'threshold': threshold
        }
        
        if current_high >= threshold:
            # Neues ATH!
            pct_above = ((current_high / old_ath) - 1) * 100
            info['pct_above_old'] = pct_above
            
            # Prüfe Konsolidierung (nicht schon die letzten Tage auf ATH)
            consolidation_highs = highs[consolidation_start:-1]
            recent_ath = max(consolidation_highs) if consolidation_highs else current_high
            
            if recent_ath < old_ath * 0.98:  # War mindestens 2% unter ATH
                info['had_consolidation'] = True
                return 3, info
            else:
                info['had_consolidation'] = False
                return 2, info  # ATH aber ohne Konsolidierung
        else:
            pct_below = ((old_ath / current_high) - 1) * 100
            info['pct_below_ath'] = pct_below
            return 0, info
    
    def _score_volume_confirmation(
        self, 
        volumes: List[int]
    ) -> tuple[int, Dict[str, Any]]:
        """Prüft Volumen-Bestätigung"""
        avg_period = self.config.volume_avg_period
        
        avg_volume = sum(volumes[-avg_period-1:-1]) / avg_period
        current_volume = volumes[-1]
        
        multiplier = current_volume / avg_volume if avg_volume > 0 else 0
        
        info = {
            'current_volume': current_volume,
            'avg_volume': avg_volume,
            'multiplier': multiplier
        }
        
        if multiplier >= self.config.volume_spike_multiplier * 1.5:
            return 2, info  # Sehr starkes Volumen
        elif multiplier >= self.config.volume_spike_multiplier:
            return 1, info  # Gutes Volumen
        else:
            return 0, info
    
    def _score_trend(self, prices: List[float]) -> tuple[int, Dict[str, Any]]:
        """Analysiert Trend via SMAs"""
        sma_20 = sum(prices[-20:]) / 20
        sma_50 = sum(prices[-50:]) / 50
        sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else sum(prices) / len(prices)
        
        current = prices[-1]
        
        info = {
            'sma_20': sma_20,
            'sma_50': sma_50,
            'sma_200': sma_200,
            'price': current
        }
        
        score = 0
        
        # Preis über allen SMAs
        if current > sma_20 > sma_50 > sma_200:
            score = 2
            info['trend'] = 'strong_uptrend'
        elif current > sma_50 > sma_200:
            score = 1
            info['trend'] = 'uptrend'
        elif current > sma_200:
            score = 0
            info['trend'] = 'weak_uptrend'
        else:
            score = 0
            info['trend'] = 'downtrend'
        
        return score, info
    
    def _score_rsi(self, prices: List[float]) -> tuple[int, float]:
        """Berechnet RSI und scored"""
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
        
        # Nicht überkauft = gut für Breakout
        if rsi < 70:
            return 1, rsi
        else:
            return 0, rsi
    
    def _score_relative_strength(
        self, 
        prices: List[float], 
        spy_prices: List[float]
    ) -> tuple[int, Dict[str, float]]:
        """Vergleicht Performance mit SPY"""
        period = 20  # 20-Tage Performance
        
        stock_return = (prices[-1] / prices[-period] - 1) * 100
        spy_return = (spy_prices[-1] / spy_prices[-period] - 1) * 100
        
        outperformance = stock_return - spy_return
        
        info = {
            'stock_return': stock_return,
            'spy_return': spy_return,
            'outperformance': outperformance
        }
        
        if outperformance > 5:
            return 2, info
        elif outperformance > 2:
            return 1, info
        else:
            return 0, info
    
    def _calculate_stop_loss(
        self, 
        lows: List[float], 
        current_price: float
    ) -> float:
        """Berechnet Stop-Loss unter letztem Swing-Low"""
        # Letztes 10-Tage-Tief als Support
        recent_low = min(lows[-10:])
        
        # Stop 1% unter Support
        stop = recent_low * 0.99
        
        # Max 5% unter aktuellem Preis
        max_stop = current_price * 0.95
        
        return max(stop, max_stop)
    
    def _calculate_target(
        self, 
        entry: float, 
        stop: float
    ) -> float:
        """Berechnet Target mit 2:1 Risk/Reward"""
        risk = entry - stop
        return entry + (risk * 2)
