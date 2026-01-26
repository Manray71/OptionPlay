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
    delta_min: float
    delta_max: float
    spread_width: float
    min_score: int
    earnings_buffer_days: int
    dte_min: int
    dte_max: int

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
                'delta_range': [self.delta_min, self.delta_max],
                'spread_width': self.spread_width,
                'min_score': self.min_score,
                'earnings_buffer_days': self.earnings_buffer_days,
                'dte_range': [self.dte_min, self.dte_max]
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
    # BASISSTRATEGIE: Short Put mit Delta -0.20, DTE 60-90 Tage
    # Earnings-Buffer: mindestens 60 Tage
    PROFILES = {
        'conservative': {
            'delta_target': -0.20,       # Basis-Delta
            'delta_range': (-0.25, -0.15),
            'spread_width': 5.0,
            'min_score': 6,
            'earnings_buffer_days': 60,  # Minimum 60 Tage
            'dte_min': 60,
            'dte_max': 90
        },
        'standard': {
            'delta_target': -0.20,       # Basis-Delta
            'delta_range': (-0.25, -0.15),
            'spread_width': 5.0,
            'min_score': 5,
            'earnings_buffer_days': 60,  # Minimum 60 Tage
            'dte_min': 60,
            'dte_max': 90
        },
        'aggressive': {
            'delta_target': -0.20,       # Basis-Delta (gleich für alle)
            'delta_range': (-0.25, -0.15),
            'spread_width': 7.5,         # Breiterer Spread bei höherer Vol
            'min_score': 5,
            'earnings_buffer_days': 60,  # Minimum 60 Tage
            'dte_min': 60,
            'dte_max': 90
        },
        'high_volatility': {
            'delta_target': -0.20,       # Basis-Delta (gleich für alle)
            'delta_range': (-0.25, -0.15),
            'spread_width': 10.0,        # Breiterer Spread für mehr Schutz
            'min_score': 6,              # Höhere Qualität bei Crash
            'earnings_buffer_days': 60,  # Minimum 60 Tage
            'dte_min': 60,
            'dte_max': 90
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
        # Basisstrategie: Short Put Delta -0.20, DTE 60-90 Tage
        if regime == MarketRegime.LOW_VOL:
            reasoning = (
                f"VIX bei {vix:.1f} zeigt niedrige Volatilität. "
                "Short Put mit Delta -0.20, DTE 60-90 Tage. "
                "Prämien sind niedriger - auf Qualität setzen."
            )
            warnings.append("Niedrige Prämien - auf Qualität statt Quantität setzen")

        elif regime == MarketRegime.NORMAL:
            reasoning = (
                f"VIX bei {vix:.1f} zeigt normale Marktbedingungen. "
                "Short Put mit Delta -0.20, DTE 60-90 Tage. "
                "Earnings-Puffer von 60 Tagen einhalten."
            )

        elif regime == MarketRegime.ELEVATED:
            reasoning = (
                f"VIX bei {vix:.1f} zeigt erhöhte Volatilität. "
                "Short Put mit Delta -0.20, DTE 60-90 Tage. "
                "Breitere Spreads ($7.50) für Gap-Schutz."
            )
            warnings.append("Erhöhte Vorsicht: Positionsgrößen reduzieren")
            warnings.append("Breitere Spreads nutzen für Gap-Schutz")

        elif regime == MarketRegime.HIGH_VOL:
            reasoning = (
                f"VIX bei {vix:.1f} zeigt extreme Volatilität (Crash-Modus). "
                "Short Put mit Delta -0.20, DTE 60-90 Tage. "
                "Breite Spreads ($10) für maximalen Schutz."
            )
            warnings.append("⚠️ CRASH-MODUS: Positionsgrößen auf 50% reduzieren")
            warnings.append("⚠️ Höhere Qualitätsanforderungen (Score >= 6)")
            warnings.append("⚠️ Tägliche Portfolio-Überwachung erforderlich")

        else:  # UNKNOWN
            reasoning = (
                "Keine VIX-Daten verfügbar. "
                "Verwende Standard-Profil: Delta -0.20, DTE 60-90 Tage."
            )
            warnings.append("⚠️ VIX nicht verfügbar - manuelle Marktprüfung empfohlen")

        delta_range = profile.get('delta_range', (profile['delta_target'] - 0.05, profile['delta_target'] + 0.05))

        return StrategyRecommendation(
            profile_name=profile_name,
            regime=regime,
            vix_level=vix,
            delta_target=profile['delta_target'],
            delta_min=delta_range[0],
            delta_max=delta_range[1],
            spread_width=profile['spread_width'],
            min_score=profile['min_score'],
            earnings_buffer_days=profile['earnings_buffer_days'],
            dte_min=profile.get('dte_min', 60),
            dte_max=profile.get('dte_max', 90),
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
# SPREAD WIDTH CALCULATION
# =============================================================================

def calculate_spread_width(stock_price: float, regime: Optional[MarketRegime] = None) -> float:
    """
    Berechnet die optimale Spread-Breite basierend auf Aktienkurs.

    Faustregel: ca. 2.5-5% des Aktienkurses, gerundet auf Standard-Strikes.
    Bei höherer Volatilität wird der Spread breiter.

    Args:
        stock_price: Aktueller Aktienkurs
        regime: Optional MarketRegime für Volatilitäts-Anpassung

    Returns:
        Empfohlene Spread-Breite in Dollar

    Beispiele:
        >>> calculate_spread_width(50.0)   # -> 2.5
        >>> calculate_spread_width(150.0)  # -> 5.0
        >>> calculate_spread_width(350.0)  # -> 10.0
    """
    # Basis-Spread basierend auf Aktienkurs
    if stock_price < 30:
        base_width = 1.0
    elif stock_price < 50:
        base_width = 2.5
    elif stock_price < 100:
        base_width = 5.0
    elif stock_price < 200:
        base_width = 5.0
    elif stock_price < 500:
        base_width = 10.0
    else:
        base_width = 15.0

    # Volatilitäts-Multiplikator
    vol_multiplier = 1.0
    if regime == MarketRegime.ELEVATED:
        vol_multiplier = 1.5  # 50% breiter bei erhöhter Vol
    elif regime == MarketRegime.HIGH_VOL:
        vol_multiplier = 2.0  # 100% breiter bei Crash

    adjusted_width = base_width * vol_multiplier

    # Auf Standard-Strike-Intervalle runden
    standard_widths = [1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 25.0]

    # Finde nächsten Standard-Wert (aufrunden für Sicherheit)
    for std_width in standard_widths:
        if std_width >= adjusted_width:
            return std_width

    return 25.0  # Maximum


def get_spread_width_table(stock_price: float) -> Dict[str, float]:
    """
    Gibt Spread-Breiten für alle Regime zurück.

    Args:
        stock_price: Aktueller Aktienkurs

    Returns:
        Dict mit Spread-Breite pro Regime
    """
    return {
        'low_vol': calculate_spread_width(stock_price, MarketRegime.LOW_VOL),
        'normal': calculate_spread_width(stock_price, MarketRegime.NORMAL),
        'elevated': calculate_spread_width(stock_price, MarketRegime.ELEVATED),
        'high_vol': calculate_spread_width(stock_price, MarketRegime.HIGH_VOL),
    }


# =============================================================================
# HELPER FUNKTIONEN
# =============================================================================

def get_strategy_for_vix(vix: Optional[float]) -> StrategyRecommendation:
    """
    Convenience-Funktion für schnelle Strategie-Auswahl.

    Beispiel:
        >>> rec = get_strategy_for_vix(22.5)
        >>> print(rec.profile_name)  # 'aggressive'
        >>> print(rec.delta_target)  # -0.20
    """
    selector = VIXStrategySelector()
    return selector.get_recommendation(vix)


def get_strategy_for_stock(
    vix: Optional[float],
    stock_price: float
) -> StrategyRecommendation:
    """
    Strategie-Empfehlung mit dynamischer Spread-Berechnung basierend auf Aktienkurs.

    Args:
        vix: Aktueller VIX-Wert
        stock_price: Aktueller Aktienkurs

    Returns:
        StrategyRecommendation mit angepasster Spread-Breite

    Beispiel:
        >>> rec = get_strategy_for_stock(22.5, 150.0)
        >>> print(rec.spread_width)  # 7.5 (elevated regime, $150 stock)
    """
    selector = VIXStrategySelector()
    regime = selector.get_regime(vix)
    rec = selector.get_recommendation(vix)

    # Spread-Breite basierend auf Aktienkurs berechnen
    dynamic_spread = calculate_spread_width(stock_price, regime)

    # Neues StrategyRecommendation mit dynamischer Spread-Breite
    return StrategyRecommendation(
        profile_name=rec.profile_name,
        regime=rec.regime,
        vix_level=rec.vix_level,
        delta_target=rec.delta_target,
        delta_min=rec.delta_min,
        delta_max=rec.delta_max,
        spread_width=dynamic_spread,
        min_score=rec.min_score,
        earnings_buffer_days=rec.earnings_buffer_days,
        dte_min=rec.dte_min,
        dte_max=rec.dte_max,
        reasoning=rec.reasoning,
        warnings=rec.warnings
    )


def format_recommendation(rec: StrategyRecommendation) -> str:
    """Formatiert Empfehlung als lesbaren String"""
    lines = [
        f"═══════════════════════════════════════════════════════════",
        f"  STRATEGIE-EMPFEHLUNG (Short Put)",
        f"═══════════════════════════════════════════════════════════",
        f"  VIX:          {rec.vix_level:.1f}" if rec.vix_level else "  VIX:          n/a",
        f"  Regime:       {rec.regime.value}",
        f"  Profil:       {rec.profile_name.upper()}",
        f"───────────────────────────────────────────────────────────",
        f"  Delta-Target: {rec.delta_target}",
        f"  Delta-Range:  [{rec.delta_min}, {rec.delta_max}]",
        f"  DTE:          {rec.dte_min}-{rec.dte_max} Tage",
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
