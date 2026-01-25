# OptionPlay - VIX Strategy Selector
# ====================================
# Automatische Strategie-Auswahl basierend auf VIX

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Markt-Regime basierend auf VIX-Level"""
    LOW_VOL = "low_vol"           # VIX < 15
    NORMAL = "normal"             # VIX 15-20
    ELEVATED = "elevated"         # VIX 20-30
    HIGH_VOL = "high_vol"         # VIX > 30
    UNKNOWN = "unknown"           # Keine VIX-Daten


@dataclass
class VIXThresholds:
    """VIX-Schwellenwerte für Regime-Bestimmung"""
    low_vol_max: float = 15.0
    normal_max: float = 20.0
    elevated_max: float = 30.0
    # Alles über elevated_max ist HIGH_VOL


@dataclass
class StrategyRecommendation:
    """Strategie-Empfehlung basierend auf Marktbedingungen"""
    profile_name: str
    regime: MarketRegime
    vix_level: Optional[float]
    
    # Empfehlungen
    delta_target: float
    spread_width: float
    min_score: int
    earnings_buffer_days: int
    
    # Begründung
    reasoning: str
    warnings: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'profile': self.profile_name,
            'regime': self.regime.value,
            'vix': self.vix_level,
            'recommendations': {
                'delta_target': self.delta_target,
                'spread_width': self.spread_width,
                'min_score': self.min_score,
                'earnings_buffer_days': self.earnings_buffer_days
            },
            'reasoning': self.reasoning,
            'warnings': self.warnings
        }


class VIXStrategySelector:
    """
    Wählt automatisch das optimale Strategy-Profil basierend auf VIX.
    
    Logik:
    - VIX < 15:  Conservative - Prämien sind niedrig, konservatives Delta
    - VIX 15-20: Standard - Normale Bedingungen
    - VIX 20-30: Aggressive - Prämien sind attraktiv, mehr Risiko akzeptabel
    - VIX > 30:  High Vol - Crash-Modus, sehr selektiv aber breite Spreads
    """
    
    # Profil-Definitionen (müssen mit strategies.yaml übereinstimmen)
    PROFILES = {
        'conservative': {
            'delta_target': -0.20,
            'spread_width': 2.5,
            'min_score': 6,
            'earnings_buffer_days': 90
        },
        'standard': {
            'delta_target': -0.30,
            'spread_width': 5.0,
            'min_score': 5,
            'earnings_buffer_days': 60
        },
        'aggressive': {
            'delta_target': -0.35,
            'spread_width': 5.0,
            'min_score': 4,
            'earnings_buffer_days': 45
        },
        'high_volatility': {
            'delta_target': -0.20,
            'spread_width': 10.0,
            'min_score': 7,
            'earnings_buffer_days': 90
        }
    }
    
    def __init__(self, thresholds: Optional[VIXThresholds] = None):
        self.thresholds = thresholds or VIXThresholds()
    
    def get_regime(self, vix: Optional[float]) -> MarketRegime:
        """
        Bestimmt das Markt-Regime basierend auf VIX.
        
        Args:
            vix: VIX-Wert (None wenn nicht verfügbar)
            
        Returns:
            MarketRegime basierend auf VIX-Level
        """
        if vix is None:
            return MarketRegime.UNKNOWN
        
        # Validierung: VIX kann nicht negativ sein
        if vix < 0:
            logger.warning(f"Invalid VIX value: {vix} (negative). Returning UNKNOWN.")
            return MarketRegime.UNKNOWN
        
        # Validierung: Extrem hohe Werte könnten auf Datenfehler hinweisen
        if vix > 100:
            logger.warning(
                f"Unusually high VIX value: {vix}. This may indicate a data error. "
                f"Treating as HIGH_VOL regime."
            )
            return MarketRegime.HIGH_VOL
        
        if vix < self.thresholds.low_vol_max:
            return MarketRegime.LOW_VOL
        elif vix < self.thresholds.normal_max:
            return MarketRegime.NORMAL
        elif vix < self.thresholds.elevated_max:
            return MarketRegime.ELEVATED
        else:
            return MarketRegime.HIGH_VOL
    
    def select_profile(self, vix: Optional[float]) -> str:
        """Wählt das optimale Profil basierend auf VIX"""
        regime = self.get_regime(vix)
        
        profile_mapping = {
            MarketRegime.LOW_VOL: 'conservative',
            MarketRegime.NORMAL: 'standard',
            MarketRegime.ELEVATED: 'aggressive',
            MarketRegime.HIGH_VOL: 'high_volatility',
            MarketRegime.UNKNOWN: 'standard'  # Fallback
        }
        
        return profile_mapping[regime]
    
    def get_recommendation(self, vix: Optional[float]) -> StrategyRecommendation:
        """
        Gibt vollständige Strategie-Empfehlung zurück.
        
        Args:
            vix: Aktueller VIX-Wert (None wenn nicht verfügbar)
            
        Returns:
            StrategyRecommendation mit allen Details
        """
        regime = self.get_regime(vix)
        profile_name = self.select_profile(vix)
        profile = self.PROFILES[profile_name]
        
        warnings = []
        
        # Reasoning basierend auf Regime
        if regime == MarketRegime.LOW_VOL:
            reasoning = (
                f"VIX bei {vix:.1f} zeigt niedrige Volatilität. "
                "Optionsprämien sind günstig - konservatives Delta empfohlen. "
                "Engere Spreads da weniger Puffer nötig."
            )
            
        elif regime == MarketRegime.NORMAL:
            reasoning = (
                f"VIX bei {vix:.1f} zeigt normale Marktbedingungen. "
                "Standard-Parameter für Bull-Put-Spreads angemessen."
            )
            
        elif regime == MarketRegime.ELEVATED:
            reasoning = (
                f"VIX bei {vix:.1f} zeigt erhöhte Volatilität. "
                "Optionsprämien sind attraktiv - aggressiveres Delta möglich. "
                "Gute Zeit für Credit Spreads."
            )
            warnings.append("Erhöhte Vorsicht bei Positionsgrößen empfohlen")
            
        elif regime == MarketRegime.HIGH_VOL:
            reasoning = (
                f"VIX bei {vix:.1f} zeigt extreme Volatilität (Crash-Modus). "
                "Sehr hohe Prämien aber auch hohes Gap-Risiko. "
                "Konservatives Delta mit breiten Spreads für mehr Puffer."
            )
            warnings.append("⚠️ Crash-Modus: Reduzierte Positionsgrößen dringend empfohlen")
            warnings.append("⚠️ Nur höchste Qualität (Score >= 7)")
            warnings.append("⚠️ Längere DTE für mehr Erholungszeit")
            
        else:  # UNKNOWN
            reasoning = (
                "Keine VIX-Daten verfügbar. "
                "Verwende Standard-Profil als Fallback."
            )
            warnings.append("VIX nicht verfügbar - manuelle Prüfung empfohlen")
        
        return StrategyRecommendation(
            profile_name=profile_name,
            regime=regime,
            vix_level=vix,
            delta_target=profile['delta_target'],
            spread_width=profile['spread_width'],
            min_score=profile['min_score'],
            earnings_buffer_days=profile['earnings_buffer_days'],
            reasoning=reasoning,
            warnings=warnings
        )
    
    def get_all_profiles(self) -> Dict[str, Dict]:
        """Gibt alle verfügbaren Profile zurück"""
        return self.PROFILES.copy()
    
    def get_regime_description(self, regime: MarketRegime) -> str:
        """Gibt Beschreibung für ein Regime zurück"""
        descriptions = {
            MarketRegime.LOW_VOL: "Niedrige Volatilität (VIX < 15)",
            MarketRegime.NORMAL: "Normale Volatilität (VIX 15-20)",
            MarketRegime.ELEVATED: "Erhöhte Volatilität (VIX 20-30)",
            MarketRegime.HIGH_VOL: "Hohe Volatilität (VIX > 30)",
            MarketRegime.UNKNOWN: "Unbekannt (keine VIX-Daten)"
        }
        return descriptions.get(regime, "Unbekannt")


# =============================================================================
# HELPER FUNKTIONEN
# =============================================================================

def get_strategy_for_vix(vix: Optional[float]) -> StrategyRecommendation:
    """
    Convenience-Funktion für schnelle Strategie-Auswahl.
    
    Beispiel:
        >>> rec = get_strategy_for_vix(22.5)
        >>> print(rec.profile_name)  # 'aggressive'
        >>> print(rec.delta_target)  # -0.35
    """
    selector = VIXStrategySelector()
    return selector.get_recommendation(vix)


def format_recommendation(rec: StrategyRecommendation) -> str:
    """Formatiert Empfehlung als lesbaren String"""
    lines = [
        f"═══════════════════════════════════════════════════════════",
        f"  STRATEGIE-EMPFEHLUNG",
        f"═══════════════════════════════════════════════════════════",
        f"  VIX:          {rec.vix_level:.1f}" if rec.vix_level else "  VIX:          n/a",
        f"  Regime:       {rec.regime.value}",
        f"  Profil:       {rec.profile_name.upper()}",
        f"───────────────────────────────────────────────────────────",
        f"  Delta-Target: {rec.delta_target}",
        f"  Spread-Breite: ${rec.spread_width:.2f}",
        f"  Min-Score:    {rec.min_score}",
        f"  Earnings:     >{rec.earnings_buffer_days} Tage",
        f"───────────────────────────────────────────────────────────",
        f"  {rec.reasoning}",
    ]
    
    if rec.warnings:
        lines.append(f"───────────────────────────────────────────────────────────")
        for warning in rec.warnings:
            lines.append(f"  {warning}")
    
    lines.append(f"═══════════════════════════════════════════════════════════")
    
    return "\n".join(lines)
