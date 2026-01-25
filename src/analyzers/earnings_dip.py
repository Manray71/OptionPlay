# OptionPlay - Earnings Dip Analyzer
# ====================================
# Analysiert Kaufgelegenheiten nach Earnings-bedingten Dips
#
# Strategie: Kaufe wenn gute Aktie nach Earnings überreagiert abverkauft wird
# - Contrarian/Mean-Reversion Signal
# - Funktioniert bei Qualitätsaktien mit temporärem Sentiment-Schock
# - Risiko: Dip ist berechtigt (fundamentale Verschlechterung)

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, date, timedelta
import logging

from .base import BaseAnalyzer
from .context import AnalysisContext

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength

logger = logging.getLogger(__name__)


@dataclass
class EarningsDipConfig:
    """Konfiguration für Earnings Dip Analyzer"""
    # Dip Detection
    min_dip_pct: float = 5.0  # Mindest-Dip für Signal
    max_dip_pct: float = 25.0  # Max-Dip (darüber = zu riskant)
    dip_lookback_days: int = 5  # Tage nach Earnings zu prüfen
    
    # Quality Filters
    require_above_sma200: bool = True  # Langfristiger Aufwärtstrend
    min_market_cap: float = 10e9  # $10B Min Market Cap (Quality Filter)
    
    # Recovery Signs
    require_stabilization: bool = True  # Preis stabilisiert sich
    stabilization_days: int = 2  # Tage ohne neue Lows
    
    # RSI für Oversold nach Dip
    rsi_oversold_threshold: float = 35.0
    
    # Gap Analysis
    analyze_gap: bool = True
    
    # Risk Management
    stop_below_dip_low_pct: float = 3.0
    target_recovery_pct: float = 50.0  # 50% des Dips zurück
    
    # Scoring
    max_score: int = 10
    min_score_for_signal: int = 6


class EarningsDipAnalyzer(BaseAnalyzer):
    """
    Analysiert Aktien auf Kaufgelegenheiten nach Earnings-Dips.
    
    Scoring-Kriterien:
    - Earnings-Dip (5-15%): 3 Punkte
    - RSI stark oversold (< 30): 2 Punkte
    - Preis stabilisiert (keine neuen Lows): 2 Punkte
    - Volumen normalisiert: 1 Punkt
    - Langfristiger Aufwärtstrend (über SMA200): 2 Punkte
    
    Verwendung:
        analyzer = EarningsDipAnalyzer()
        signal = analyzer.analyze(
            "AAPL", prices, volumes, highs, lows,
            earnings_date=date(2025, 1, 20)
        )
        
        if signal.is_actionable:
            print(f"Earnings Dip Signal: {signal.score}/10")
    """
    
    def __init__(self, config: Optional[EarningsDipConfig] = None):
        self.config = config or EarningsDipConfig()
    
    @property
    def strategy_name(self) -> str:
        return "earnings_dip"
    
    @property
    def description(self) -> str:
        return "Earnings Dip Buy - Kaufe nach übertriebenem Earnings-Abverkauf bei Qualitätsaktien"
    
    def analyze(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        earnings_date: Optional[date] = None,
        pre_earnings_price: Optional[float] = None,
        context: Optional[AnalysisContext] = None,
        **kwargs
    ) -> TradeSignal:
        """
        Analysiert ein Symbol auf Earnings-Dip-Kaufgelegenheit.
        
        Args:
            symbol: Ticker-Symbol
            prices: Schlusskurse (älteste zuerst)
            volumes: Tagesvolumen
            highs: Tageshochs
            lows: Tagestiefs
            earnings_date: Earnings-Datum (optional, wird geschätzt wenn nicht angegeben)
            pre_earnings_price: Preis vor Earnings (optional)
            
        Returns:
            TradeSignal mit Earnings-Dip-Bewertung
        """
        # Input-Validierung
        self.validate_inputs(prices, volumes, highs, lows, min_length=60)
        
        current_price = prices[-1]
        
        # Score-Komponenten
        score_breakdown = {}
        total_score = 0
        reasons = []
        warnings = []
        
        # 1. Dip Detection (3 Punkte)
        dip_score, dip_info = self._detect_earnings_dip(
            prices, highs, lows, earnings_date, pre_earnings_price
        )
        score_breakdown['dip'] = dip_score
        total_score += dip_score
        
        if dip_score == 0:
            # Kein Earnings-Dip erkannt
            return self.create_neutral_signal(
                symbol, current_price,
                dip_info.get('reason', 'Kein Earnings-Dip erkannt')
            )
        
        dip_pct = dip_info.get('dip_pct', 0)
        reasons.append(f"Earnings-Dip: -{dip_pct:.1f}%")
        
        if dip_pct > 15:
            warnings.append(f"Großer Dip (>{dip_pct:.0f}%) - erhöhtes Risiko")
        
        # 2. RSI Oversold (2 Punkte)
        rsi_score, rsi_value = self._score_rsi_oversold(prices)
        score_breakdown['rsi'] = rsi_score
        total_score += rsi_score
        
        if rsi_score >= 2:
            reasons.append(f"Stark oversold (RSI {rsi_value:.0f})")
        elif rsi_score == 1:
            reasons.append(f"Oversold (RSI {rsi_value:.0f})")
        
        # 3. Stabilisierung (2 Punkte)
        stab_score, stab_info = self._score_stabilization(lows)
        score_breakdown['stabilization'] = stab_score
        total_score += stab_score
        
        if stab_score > 0:
            reasons.append(f"Preis stabilisiert ({stab_info['days_without_new_low']} Tage ohne neues Low)")
        else:
            warnings.append("Noch keine Stabilisierung - möglicherweise zu früh")
        
        # 4. Volumen normalisiert (1 Punkt)
        vol_score, vol_info = self._score_volume_normalization(volumes)
        score_breakdown['volume'] = vol_score
        total_score += vol_score
        
        if vol_score > 0:
            reasons.append("Verkaufsdruck lässt nach")
        
        # 5. Langfristiger Trend (2 Punkte)
        trend_score, trend_info = self._score_long_term_trend(prices)
        score_breakdown['trend'] = trend_score
        total_score += trend_score
        
        if trend_score >= 2:
            reasons.append("Langfristiger Aufwärtstrend intakt")
        elif trend_score == 0:
            warnings.append("Unter SMA200 - schwächerer langfristiger Trend")
        
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
        dip_low = dip_info.get('dip_low', min(lows[-5:]))
        stop_loss = dip_low * (1 - self.config.stop_below_dip_low_pct / 100)
        
        # Target: Recovery zu 50% des Dips
        pre_price = dip_info.get('pre_earnings_price', prices[-10])
        target_price = current_price + (pre_price - current_price) * (self.config.target_recovery_pct / 100)
        
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
                'dip_info': dip_info,
                'trend_info': trend_info,
                'rsi': rsi_value,
                'stabilization': stab_info
            },
            warnings=warnings
        )
    
    def _detect_earnings_dip(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        earnings_date: Optional[date],
        pre_earnings_price: Optional[float]
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Erkennt Earnings-Dip.
        
        Sucht nach starkem Preisrückgang in den letzten Tagen.
        """
        lookback = self.config.dip_lookback_days
        
        info = {
            'earnings_date': earnings_date,
            'lookback_days': lookback
        }
        
        # Pre-Earnings Preis bestimmen
        if pre_earnings_price:
            pre_price = pre_earnings_price
        else:
            # Schätze: Höchster Preis der letzten 10 Tage vor dem Lookback
            if len(prices) >= lookback + 10:
                pre_price = max(prices[-(lookback + 10):-lookback])
            else:
                pre_price = max(prices[:-lookback]) if len(prices) > lookback else prices[0]
        
        info['pre_earnings_price'] = pre_price
        
        # Aktueller Preis und Dip-Low
        current_price = prices[-1]
        recent_lows = lows[-lookback:]
        dip_low = min(recent_lows)
        
        info['current_price'] = current_price
        info['dip_low'] = dip_low
        
        # Dip berechnen
        dip_from_pre = (1 - dip_low / pre_price) * 100
        dip_from_current = (1 - current_price / pre_price) * 100
        
        info['dip_pct'] = dip_from_current
        info['dip_to_low_pct'] = dip_from_pre
        
        # Prüfe ob es ein Gap Down gab (typisch für Earnings)
        has_gap = False
        for i in range(1, min(lookback, len(prices))):
            if prices[-i] < lows[-i-1] * 0.98:  # Gap > 2%
                has_gap = True
                info['gap_detected'] = True
                break
        
        # Scoring
        if dip_from_current < self.config.min_dip_pct:
            info['reason'] = f"Dip zu klein ({dip_from_current:.1f}% < {self.config.min_dip_pct}%)"
            return 0, info
        
        if dip_from_current > self.config.max_dip_pct:
            info['reason'] = f"Dip zu groß ({dip_from_current:.1f}% > {self.config.max_dip_pct}%) - zu riskant"
            return 0, info
        
        # Guter Dip-Bereich
        if self.config.min_dip_pct <= dip_from_current <= 10:
            return 3, info  # Idealer Dip (5-10%)
        elif dip_from_current <= 15:
            return 2, info  # Moderater Dip (10-15%)
        else:
            return 1, info  # Großer Dip (15-25%)
    
    def _score_rsi_oversold(self, prices: List[float]) -> Tuple[int, float]:
        """RSI-Score für starke Oversold-Bedingung"""
        period = 14
        
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
        
        if rsi < 25:
            return 2, rsi  # Extrem oversold
        elif rsi < self.config.rsi_oversold_threshold:
            return 1, rsi  # Oversold
        else:
            return 0, rsi
    
    def _score_stabilization(self, lows: List[float]) -> Tuple[int, Dict[str, Any]]:
        """Prüft ob sich der Preis stabilisiert hat"""
        if len(lows) < 5:
            return 0, {'days_without_new_low': 0}
        
        recent_lows = lows[-5:]
        
        # Finde das Tief
        min_low = min(recent_lows)
        min_index = recent_lows.index(min_low)
        
        # Tage seit dem Tief
        days_since_low = len(recent_lows) - 1 - min_index
        
        info = {
            'dip_low': min_low,
            'days_without_new_low': days_since_low,
            'min_index': min_index
        }
        
        if days_since_low >= self.config.stabilization_days:
            return 2, info  # Stabile Basis
        elif days_since_low >= 1:
            return 1, info  # Beginnende Stabilisierung
        else:
            return 0, info  # Neues Low heute
    
    def _score_volume_normalization(self, volumes: List[int]) -> Tuple[int, Dict[str, Any]]:
        """Prüft ob das Panik-Volumen nachlässt"""
        if len(volumes) < 10:
            return 0, {}
        
        # Vergleiche Volumen: Tag 1-2 nach Dip vs aktuell
        early_volume = sum(volumes[-5:-3]) / 2  # Tage 3-4 zurück
        current_volume = volumes[-1]
        avg_volume = sum(volumes[-20:-5]) / 15  # Normale Durchschnittsvolumen
        
        info = {
            'early_volume': early_volume,
            'current_volume': current_volume,
            'avg_volume': avg_volume
        }
        
        # Volumen sollte sich normalisieren (von Panik-Spike zurück)
        if early_volume > avg_volume * 2:  # Es gab einen Volumen-Spike
            if current_volume < early_volume * 0.6:  # Volumen hat sich beruhigt
                return 1, info
        
        return 0, info
    
    def _score_long_term_trend(self, prices: List[float]) -> Tuple[int, Dict[str, Any]]:
        """Langfristiger Trend-Check"""
        sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else sum(prices) / len(prices)
        sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sum(prices) / len(prices)
        
        current = prices[-1]
        
        # Pre-Dip Preis (vor 10 Tagen) für Trend-Vergleich
        pre_dip = prices[-10] if len(prices) >= 10 else prices[0]
        
        info = {
            'sma_200': sma_200,
            'sma_50': sma_50,
            'current': current,
            'pre_dip': pre_dip
        }
        
        # War die Aktie VOR dem Dip im Aufwärtstrend?
        if pre_dip > sma_200:
            info['was_in_uptrend'] = True
            
            # Ist sie jetzt unter SMA200 gefallen?
            if current > sma_200:
                info['trend'] = 'still_above_sma200'
                return 2, info  # Stark - immer noch über SMA200
            elif current > sma_200 * 0.95:
                info['trend'] = 'near_sma200'
                return 1, info  # Nahe SMA200
            else:
                info['trend'] = 'below_sma200'
                return 0, info
        else:
            info['was_in_uptrend'] = False
            info['trend'] = 'was_not_in_uptrend'
            return 0, info
