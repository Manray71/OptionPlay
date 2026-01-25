# OptionPlay - Signal Aggregator
# ================================
# Kombiniert und rankt Signale aus verschiedenen Strategien

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from collections import defaultdict

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength

logger = logging.getLogger(__name__)


@dataclass
class AggregatedSignal:
    """
    Kombiniertes Signal aus mehreren Strategien für ein Symbol.
    """
    symbol: str
    current_price: float
    
    # Aggregierte Bewertung
    combined_score: float  # Gewichteter Durchschnitt
    signal_count: int  # Anzahl übereinstimmender Signale
    strategies: List[str]  # Namen der Strategien
    
    # Beste Einzelsignale
    best_signal: TradeSignal
    all_signals: List[TradeSignal]
    
    # Konsens
    consensus_type: SignalType
    consensus_strength: SignalStrength
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'current_price': self.current_price,
            'combined_score': round(self.combined_score, 2),
            'signal_count': self.signal_count,
            'strategies': self.strategies,
            'consensus_type': self.consensus_type.value,
            'consensus_strength': self.consensus_strength.value,
            'best_signal': self.best_signal.to_dict()
        }


class SignalAggregator:
    """
    Aggregiert und rankt Signale aus verschiedenen Quellen.
    
    Features:
    - Kombiniert Signale pro Symbol
    - Gewichtet nach Strategie-Priorität
    - Findet Konsens zwischen Strategien
    """
    
    def __init__(self, strategy_weights: Optional[Dict[str, float]] = None):
        """
        Args:
            strategy_weights: Gewichtung pro Strategie (default: alle gleich)
        """
        self._weights = strategy_weights or {}
        self._default_weight = 1.0
    
    def set_weight(self, strategy: str, weight: float) -> None:
        """Setzt Gewichtung für eine Strategie"""
        self._weights[strategy] = weight
    
    def aggregate(
        self,
        signals: List[TradeSignal],
        min_agreement: int = 1
    ) -> List[AggregatedSignal]:
        """
        Aggregiert Signale nach Symbol.
        
        Args:
            signals: Liste aller Signale
            min_agreement: Mindestanzahl übereinstimmender Signale
            
        Returns:
            Liste von AggregatedSignals, sortiert nach combined_score
        """
        # Gruppiere nach Symbol
        by_symbol: Dict[str, List[TradeSignal]] = defaultdict(list)
        for signal in signals:
            by_symbol[signal.symbol].append(signal)
        
        aggregated = []
        
        for symbol, symbol_signals in by_symbol.items():
            if len(symbol_signals) < min_agreement:
                continue
            
            # Nur actionable Signale (LONG oder SHORT)
            actionable = [s for s in symbol_signals if s.signal_type != SignalType.NEUTRAL]
            
            if not actionable:
                continue
            
            # Konsens bestimmen
            long_count = sum(1 for s in actionable if s.signal_type == SignalType.LONG)
            short_count = len(actionable) - long_count
            
            if long_count >= short_count:
                consensus_type = SignalType.LONG
            else:
                consensus_type = SignalType.SHORT
            
            # Nur Signale mit Konsens-Typ
            consensus_signals = [s for s in actionable if s.signal_type == consensus_type]
            
            if not consensus_signals:
                continue
            
            # Gewichteter Score
            total_weight = 0
            weighted_score = 0
            
            for signal in consensus_signals:
                weight = self._weights.get(signal.strategy, self._default_weight)
                weighted_score += signal.score * weight
                total_weight += weight
            
            combined_score = weighted_score / total_weight if total_weight > 0 else 0
            
            # Bestes Signal
            best = max(consensus_signals, key=lambda s: s.score)
            
            # Stärke bestimmen
            if combined_score >= 7 and len(consensus_signals) >= 2:
                strength = SignalStrength.STRONG
            elif combined_score >= 5:
                strength = SignalStrength.MODERATE
            else:
                strength = SignalStrength.WEAK
            
            aggregated.append(AggregatedSignal(
                symbol=symbol,
                current_price=best.current_price,
                combined_score=combined_score,
                signal_count=len(consensus_signals),
                strategies=[s.strategy for s in consensus_signals],
                best_signal=best,
                all_signals=symbol_signals,
                consensus_type=consensus_type,
                consensus_strength=strength
            ))
        
        # Nach Score sortieren
        aggregated.sort(key=lambda x: x.combined_score, reverse=True)
        
        return aggregated
    
    def filter_by_strategy(
        self,
        signals: List[TradeSignal],
        strategy: str
    ) -> List[TradeSignal]:
        """Filtert Signale nach Strategie"""
        return [s for s in signals if s.strategy == strategy]
    
    def get_multi_strategy_hits(
        self,
        signals: List[TradeSignal],
        min_strategies: int = 2
    ) -> List[AggregatedSignal]:
        """
        Findet Symbole mit Signalen aus mehreren Strategien.
        
        Diese sind oft die stärksten Kandidaten.
        """
        return [
            agg for agg in self.aggregate(signals, min_agreement=min_strategies)
            if agg.signal_count >= min_strategies
        ]
