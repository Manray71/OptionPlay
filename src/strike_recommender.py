#!/usr/bin/env python3
"""
Strike-Empfehlungsmodul für Bull-Put-Spreads

Analysiert Support-Levels, Delta-Targeting und Spread-Width um optimale
Strike-Kombinationen zu empfehlen.

Kernlogik:
1. Support-Level-Analyse (historische Pivot-Points)
2. Delta-Targeting (Short Put: -0.25 bis -0.35)
3. Spread-Width basierend auf Preisniveau
4. Prämien- und Risk/Reward-Kalkulation
5. Fibonacci-Retracements als zusätzliche Bestätigung

Verwendung:
    from src.strike_recommender import StrikeRecommender
    
    recommender = StrikeRecommender()
    recommendation = recommender.get_recommendation(
        symbol="AAPL",
        current_price=182.50,
        support_levels=[175.0, 170.0, 165.0],
        iv_rank=45,
        options_data=[...],  # Optional: Options-Chain mit Greeks
        fib_levels=[...]     # Optional: Fibonacci-Levels
    )
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum

# ConfigLoader für einheitliche Konfiguration
try:
    from .config_loader import ConfigLoader
    _CONFIG_AVAILABLE = True
except ImportError:
    _CONFIG_AVAILABLE = False

# VIX-basierte Spread-Berechnung
try:
    from .vix_strategy import calculate_spread_width, MarketRegime
    _VIX_SPREAD_AVAILABLE = True
except ImportError:
    _VIX_SPREAD_AVAILABLE = False

logger = logging.getLogger(__name__)


class StrikeQuality(Enum):
    """Bewertung der Strike-Empfehlung"""
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"


@dataclass
class SupportLevel:
    """Support-Level mit Metadaten"""
    price: float
    touches: int = 1
    strength: str = "moderate"  # weak, moderate, strong
    confirmed_by_fib: bool = False
    distance_pct: float = 0.0  # Abstand zum aktuellen Preis in %


@dataclass
class StrikeRecommendation:
    """Empfohlene Strike-Kombination für Bull-Put-Spread"""
    symbol: str
    current_price: float
    
    # Strike-Preise
    short_strike: float
    long_strike: float
    spread_width: float
    
    # Basis für die Empfehlung
    short_strike_reason: str
    support_level_used: Optional[SupportLevel] = None
    
    # Options-Metriken (falls verfügbar)
    estimated_delta: Optional[float] = None
    estimated_credit: Optional[float] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None
    break_even: Optional[float] = None
    
    # Probabilitäten
    prob_profit: Optional[float] = None  # P(OTM bei Verfall)
    risk_reward_ratio: Optional[float] = None
    
    # Bewertung
    quality: StrikeQuality = StrikeQuality.GOOD
    confidence_score: float = 0.0  # 0-100
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Konvertiert zu Dictionary für JSON-Output"""
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "short_strike": self.short_strike,
            "long_strike": self.long_strike,
            "spread_width": self.spread_width,
            "short_strike_reason": self.short_strike_reason,
            "estimated_delta": self.estimated_delta,
            "estimated_credit": self.estimated_credit,
            "max_loss": self.max_loss,
            "max_profit": self.max_profit,
            "break_even": self.break_even,
            "prob_profit": self.prob_profit,
            "risk_reward_ratio": self.risk_reward_ratio,
            "quality": self.quality.value,
            "confidence_score": self.confidence_score,
            "warnings": self.warnings,
            "support_level": {
                "price": self.support_level_used.price,
                "strength": self.support_level_used.strength,
                "touches": self.support_level_used.touches,
                "confirmed_by_fib": self.support_level_used.confirmed_by_fib
            } if self.support_level_used else None
        }


class StrikeRecommender:
    """
    Strike-Empfehlungs-Engine für Bull-Put-Spreads
    
    Kriterien für Short-Strike-Auswahl:
    1. Unterhalb starker Support-Levels
    2. Delta zwischen -0.25 und -0.35 (Ziel: -0.30)
    3. Mindestens 10% OTM (Puffer für Pullbacks)
    4. Bestätigung durch Fibonacci-Levels bevorzugt
    
    Spread-Width-Regeln:
    - Aktien < $50: $2.50 oder $5 Spread
    - Aktien $50-$150: $5 Spread
    - Aktien $150-$300: $5 oder $10 Spread
    - Aktien > $300: $10 oder $20 Spread
    """
    
    # Konfigurierbare Parameter
    DEFAULT_CONFIG = {
        # Delta-Targeting
        "delta_target": -0.30,
        "delta_min": -0.35,
        "delta_max": -0.20,
        
        # OTM-Anforderungen
        "min_otm_pct": 8.0,    # Mindestens 8% unter Spot
        "target_otm_pct": 12.0, # Ideal: 12% unter Spot
        "max_otm_pct": 25.0,   # Nicht weiter als 25%
        
        # Spread-Widths nach Preisniveau
        "spread_widths": {
            50: [2.5, 5.0],
            150: [5.0],
            300: [5.0, 10.0],
            float('inf'): [10.0, 20.0]
        },
        
        # Support-Level-Bewertung
        "min_touches_strong": 3,
        "min_touches_moderate": 2,
        
        # Prämien-Anforderungen
        "min_credit_pct": 20,  # Mindestens 20% der Spread-Width als Credit
        "target_credit_pct": 30,  # Ideal: 30%
    }
    
    def __init__(self, config: Optional[Dict] = None, use_config_loader: bool = True):
        """
        Initialisiert den Strike-Recommender
        
        Args:
            config: Optionale Konfiguration (überschreibt Defaults)
            use_config_loader: Wenn True, versuche Einstellungen aus ConfigLoader zu laden
        """
        # Starte mit Defaults
        self.config = {**self.DEFAULT_CONFIG}
        
        # Versuche ConfigLoader zu verwenden
        if use_config_loader and _CONFIG_AVAILABLE:
            try:
                loader = ConfigLoader()
                
                # Options-Einstellungen aus settings.yaml laden
                if hasattr(loader, 'settings') and loader.settings:
                    options_cfg = loader.settings.options
                    
                    # Delta-Targets
                    if options_cfg.delta_target:
                        self.config["delta_target"] = options_cfg.delta_target
                    if options_cfg.delta_min:
                        self.config["delta_min"] = options_cfg.delta_min
                    if options_cfg.delta_max:
                        self.config["delta_max"] = options_cfg.delta_max
                    
                    # Spread-Width
                    if options_cfg.default_spread_width:
                        # Konvertiere einzelnen Wert zu Liste
                        default_width = options_cfg.default_spread_width
                        self.config["spread_widths"] = {
                            50: [min(default_width, 2.5), default_width],
                            150: [default_width],
                            300: [default_width, default_width * 2],
                            float('inf'): [default_width * 2, default_width * 4]
                        }
                    
                    # Premium-Anforderungen
                    if options_cfg.min_credit_pct:
                        self.config["min_credit_pct"] = options_cfg.min_credit_pct
                    
                    logger.debug("StrikeRecommender: Konfiguration aus ConfigLoader geladen")
                    
            except Exception as e:
                logger.warning(f"ConfigLoader nicht verfügbar, verwende Defaults: {e}")
        
        # Explizite config überschreibt alles
        if config:
            self.config.update(config)
    
    def get_recommendation(
        self,
        symbol: str,
        current_price: float,
        support_levels: List[float],
        iv_rank: Optional[float] = None,
        options_data: Optional[List[Dict]] = None,
        fib_levels: Optional[List[Dict]] = None,
        dte: int = 45,
        regime: Optional["MarketRegime"] = None
    ) -> StrikeRecommendation:
        """
        Generiert Strike-Empfehlung für einen Bull-Put-Spread

        Args:
            symbol: Ticker-Symbol
            current_price: Aktueller Aktienkurs
            support_levels: Liste von Support-Preisen (sortiert absteigend)
            iv_rank: IV-Rang (0-100), optional
            options_data: Options-Chain mit Greeks, optional
            fib_levels: Fibonacci-Levels, optional
            dte: Days to Expiration
            regime: Optional MarketRegime für VIX-basierte Spread-Berechnung

        Returns:
            StrikeRecommendation mit allen Details
        """
        logger.info(f"Generiere Strike-Empfehlung für {symbol} @ ${current_price}")

        # 1. Support-Levels analysieren und anreichern
        analyzed_supports = self._analyze_support_levels(
            current_price, support_levels, fib_levels
        )

        # 2. Spread-Width basierend auf Preisniveau und VIX-Regime bestimmen
        spread_widths = self._get_spread_widths(current_price, regime)
        preferred_width = spread_widths[0]  # Kleinste empfohlene Width
        
        # 3. Short-Strike finden
        short_strike, reason, support_used = self._find_short_strike(
            current_price, analyzed_supports, options_data
        )
        
        # 4. Long-Strike berechnen
        long_strike = self._calculate_long_strike(short_strike, preferred_width, current_price)
        actual_width = short_strike - long_strike
        
        # 5. Metriken berechnen
        metrics = self._calculate_metrics(
            short_strike, long_strike, actual_width,
            current_price, options_data, iv_rank, dte
        )
        
        # 6. Qualität bewerten
        quality, confidence, warnings = self._evaluate_quality(
            short_strike, long_strike, current_price,
            support_used, metrics, iv_rank
        )
        
        recommendation = StrikeRecommendation(
            symbol=symbol,
            current_price=current_price,
            short_strike=short_strike,
            long_strike=long_strike,
            spread_width=actual_width,
            short_strike_reason=reason,
            support_level_used=support_used,
            estimated_delta=metrics.get("delta"),
            estimated_credit=metrics.get("credit"),
            max_loss=metrics.get("max_loss"),
            max_profit=metrics.get("max_profit"),
            break_even=metrics.get("break_even"),
            prob_profit=metrics.get("prob_profit"),
            risk_reward_ratio=metrics.get("risk_reward"),
            quality=quality,
            confidence_score=confidence,
            warnings=warnings
        )
        
        logger.info(f"Empfehlung: Short {short_strike} / Long {long_strike}, Qualität: {quality.value}")
        return recommendation
    
    def get_multiple_recommendations(
        self,
        symbol: str,
        current_price: float,
        support_levels: List[float],
        options_data: Optional[List[Dict]] = None,
        fib_levels: Optional[List[Dict]] = None,
        num_alternatives: int = 3
    ) -> List[StrikeRecommendation]:
        """
        Generiert mehrere alternative Strike-Empfehlungen
        
        Args:
            symbol: Ticker
            current_price: Aktueller Kurs
            support_levels: Support-Preise
            options_data: Options-Chain
            fib_levels: Fibonacci-Levels
            num_alternatives: Anzahl Alternativen
        
        Returns:
            Liste von Empfehlungen (sortiert nach Qualität)
        """
        recommendations = []
        
        # Verschiedene Spread-Widths probieren
        spread_widths = self._get_spread_widths(current_price)
        
        analyzed_supports = self._analyze_support_levels(
            current_price, support_levels, fib_levels
        )
        
        for width in spread_widths:
            for support in analyzed_supports[:3]:  # Top 3 Supports
                # Short-Strike leicht unter Support
                short_strike = self._round_strike(support.price * 0.98, current_price)
                long_strike = self._calculate_long_strike(short_strike, width, current_price)
                
                if short_strike >= current_price * 0.92:  # Mindestens 8% OTM
                    continue
                
                metrics = self._calculate_metrics(
                    short_strike, long_strike, width,
                    current_price, options_data, None, 45
                )
                
                quality, confidence, warnings = self._evaluate_quality(
                    short_strike, long_strike, current_price,
                    support, metrics, None
                )
                
                rec = StrikeRecommendation(
                    symbol=symbol,
                    current_price=current_price,
                    short_strike=short_strike,
                    long_strike=long_strike,
                    spread_width=width,
                    short_strike_reason=f"Support @ ${support.price:.2f}",
                    support_level_used=support,
                    estimated_delta=metrics.get("delta"),
                    estimated_credit=metrics.get("credit"),
                    max_loss=metrics.get("max_loss"),
                    max_profit=metrics.get("max_profit"),
                    break_even=metrics.get("break_even"),
                    prob_profit=metrics.get("prob_profit"),
                    risk_reward_ratio=metrics.get("risk_reward"),
                    quality=quality,
                    confidence_score=confidence,
                    warnings=warnings
                )
                recommendations.append(rec)
        
        # Nach Confidence sortieren, beste zuerst
        recommendations.sort(key=lambda x: x.confidence_score, reverse=True)
        return recommendations[:num_alternatives]
    
    def _analyze_support_levels(
        self,
        current_price: float,
        support_levels: List[float],
        fib_levels: Optional[List[Dict]] = None
    ) -> List[SupportLevel]:
        """Analysiert und bewertet Support-Levels"""
        analyzed = []
        
        fib_prices = set()
        if fib_levels:
            fib_prices = {fl["level"] for fl in fib_levels}
        
        for price in support_levels:
            if price >= current_price:
                continue
            
            distance_pct = (current_price - price) / current_price * 100
            
            # Stärke basierend auf Touches (würde normalerweise aus Historie berechnet)
            # Hier vereinfacht: näher am Preis = stärker
            if distance_pct < 10:
                strength = "strong"
                touches = 3
            elif distance_pct < 15:
                strength = "moderate"
                touches = 2
            else:
                strength = "weak"
                touches = 1
            
            # Fibonacci-Bestätigung prüfen
            confirmed_by_fib = False
            if fib_prices:
                for fib_price in fib_prices:
                    if abs(price - fib_price) / price < 0.02:  # 2% Toleranz
                        confirmed_by_fib = True
                        break
            
            analyzed.append(SupportLevel(
                price=price,
                touches=touches,
                strength=strength,
                confirmed_by_fib=confirmed_by_fib,
                distance_pct=distance_pct
            ))
        
        # Nach Stärke und Fib-Bestätigung sortieren
        analyzed.sort(
            key=lambda x: (
                x.confirmed_by_fib,
                x.strength == "strong",
                x.strength == "moderate",
                -x.distance_pct  # Nähere zuerst
            ),
            reverse=True
        )
        
        return analyzed
    
    def _get_spread_widths(
        self,
        price: float,
        regime: Optional["MarketRegime"] = None
    ) -> List[float]:
        """
        Bestimmt empfohlene Spread-Widths basierend auf Preisniveau und VIX-Regime.

        Args:
            price: Aktueller Aktienkurs
            regime: Optional MarketRegime für VIX-basierte Anpassung

        Returns:
            Liste empfohlener Spread-Widths
        """
        # Wenn VIX-basierte Berechnung verfügbar, nutze diese
        if _VIX_SPREAD_AVAILABLE and regime is not None:
            dynamic_width = calculate_spread_width(price, regime)
            # Gib auch Alternativen zurück
            return [dynamic_width, dynamic_width * 1.5, dynamic_width * 2.0]

        # Fallback auf statische Konfiguration
        for threshold, widths in sorted(self.config["spread_widths"].items()):
            if price <= threshold:
                return widths
        return [10.0]  # Fallback
    
    def _find_short_strike(
        self,
        current_price: float,
        supports: List[SupportLevel],
        options_data: Optional[List[Dict]]
    ) -> tuple:
        """
        Findet den optimalen Short-Strike
        
        Priorisierung:
        1. Strike mit Delta nahe -0.30 (wenn Options-Daten verfügbar)
        2. Strike unter starkem Support-Level
        3. Strike bei 10-15% OTM
        
        Returns:
            (short_strike, reason, support_used)
        """
        target_delta = self.config["delta_target"]
        target_otm = self.config["target_otm_pct"]
        min_otm = self.config["min_otm_pct"]
        
        # Methode 1: Delta-basiert (wenn Options-Daten vorhanden)
        if options_data:
            best_delta_match = None
            best_delta_diff = float('inf')
            
            for opt in options_data:
                if opt.get("right") != "P":
                    continue
                
                delta = opt.get("delta")
                strike = opt.get("strike")
                
                if delta is None or strike is None:
                    continue
                
                if strike >= current_price:  # Nur OTM Puts
                    continue
                
                delta_diff = abs(delta - target_delta)
                if delta_diff < best_delta_diff:
                    best_delta_diff = delta_diff
                    best_delta_match = opt
            
            if best_delta_match and best_delta_diff < 0.10:
                strike = best_delta_match["strike"]
                return (
                    strike,
                    f"Delta-Targeting: Δ = {best_delta_match['delta']:.2f}",
                    None
                )
        
        # Methode 2: Support-basiert
        if supports:
            best_support = None
            
            for support in supports:
                # Support sollte im gewünschten OTM-Bereich sein
                if min_otm <= support.distance_pct <= target_otm + 5:
                    best_support = support
                    break
            
            if best_support:
                # Strike leicht unter dem Support-Level
                strike = self._round_strike(
                    best_support.price * 0.98,  # 2% unter Support
                    current_price
                )
                
                reason_parts = [f"Support @ ${best_support.price:.2f}"]
                if best_support.confirmed_by_fib:
                    reason_parts.append("Fib-bestätigt")
                if best_support.strength == "strong":
                    reason_parts.append("starker Support")
                
                return (strike, " + ".join(reason_parts), best_support)
        
        # Methode 3: OTM-Prozent-basiert (Fallback)
        strike = self._round_strike(
            current_price * (1 - target_otm / 100),
            current_price
        )
        
        return (strike, f"Standard {target_otm}% OTM", None)
    
    def _calculate_long_strike(
        self,
        short_strike: float,
        spread_width: float,
        current_price: float
    ) -> float:
        """Berechnet den Long-Strike basierend auf Short-Strike und Width"""
        long_strike = short_strike - spread_width
        
        # Auf Standard-Increments runden
        return self._round_strike(long_strike, current_price)
    
    def _round_strike(self, strike: float, reference_price: float) -> float:
        """
        Rundet Strike auf Standard-Increments
        
        - Preise < $50: $0.50 oder $1 Increments
        - Preise $50-$200: $2.50 oder $5 Increments
        - Preise > $200: $5 oder $10 Increments
        """
        if reference_price < 50:
            return round(strike)
        elif reference_price < 200:
            return round(strike / 5) * 5
        else:
            return round(strike / 10) * 10
    
    def _calculate_metrics(
        self,
        short_strike: float,
        long_strike: float,
        spread_width: float,
        current_price: float,
        options_data: Optional[List[Dict]],
        iv_rank: Optional[float],
        dte: int
    ) -> Dict[str, Any]:
        """Berechnet Metriken für den Spread"""
        metrics = {}
        
        # Basis-Metriken (immer berechenbar)
        metrics["spread_width"] = spread_width
        metrics["max_loss"] = spread_width * 100  # pro Contract
        
        # Options-Daten verwenden wenn verfügbar
        short_put = None
        long_put = None
        
        if options_data:
            for opt in options_data:
                if opt.get("right") != "P":
                    continue
                if abs(opt.get("strike", 0) - short_strike) < 0.5:
                    short_put = opt
                if abs(opt.get("strike", 0) - long_strike) < 0.5:
                    long_put = opt
        
        if short_put and long_put:
            # Echte Options-Daten
            short_credit = (short_put.get("bid", 0) or 0)
            long_debit = (long_put.get("ask", 0) or 0)
            net_credit = short_credit - long_debit
            
            if net_credit > 0:
                metrics["credit"] = round(net_credit, 2)
                metrics["max_profit"] = round(net_credit * 100, 2)
                metrics["max_loss"] = round((spread_width - net_credit) * 100, 2)
                metrics["break_even"] = round(short_strike - net_credit, 2)
                metrics["risk_reward"] = round(
                    metrics["max_profit"] / metrics["max_loss"], 2
                ) if metrics["max_loss"] > 0 else 0
            
            if short_put.get("delta"):
                metrics["delta"] = short_put["delta"]
        
        else:
            # Schätzungen ohne echte Options-Daten
            # Vereinfachte Prämien-Schätzung basierend auf OTM% und IV
            otm_pct = (current_price - short_strike) / current_price * 100
            
            # Basis-Credit-Schätzung (sehr vereinfacht)
            if iv_rank and iv_rank > 50:
                credit_factor = 0.35
            else:
                credit_factor = 0.25
            
            estimated_credit = spread_width * credit_factor
            estimated_credit = round(max(estimated_credit, spread_width * 0.20), 2)
            
            metrics["credit"] = estimated_credit
            metrics["max_profit"] = round(estimated_credit * 100, 2)
            metrics["max_loss"] = round((spread_width - estimated_credit) * 100, 2)
            metrics["break_even"] = round(short_strike - estimated_credit, 2)
            
            # Delta-Schätzung basierend auf OTM%
            # Sehr vereinfacht: 10% OTM ≈ -0.25 Delta, 15% OTM ≈ -0.18 Delta
            estimated_delta = -0.50 * (1 - otm_pct / 20)
            estimated_delta = max(min(estimated_delta, -0.15), -0.45)
            metrics["delta"] = round(estimated_delta, 2)
        
        # Gewinn-Wahrscheinlichkeit schätzen
        if "delta" in metrics:
            # P(OTM) ≈ 1 - |Delta|
            metrics["prob_profit"] = round((1 - abs(metrics["delta"])) * 100, 1)
        
        return metrics
    
    def _evaluate_quality(
        self,
        short_strike: float,
        long_strike: float,
        current_price: float,
        support: Optional[SupportLevel],
        metrics: Dict,
        iv_rank: Optional[float]
    ) -> tuple:
        """
        Bewertet die Qualität der Empfehlung
        
        Returns:
            (StrikeQuality, confidence_score, warnings)
        """
        score = 50  # Basis-Score
        warnings = []
        
        # 1. OTM-Abstand prüfen (+/- 20 Punkte)
        otm_pct = (current_price - short_strike) / current_price * 100
        
        if 10 <= otm_pct <= 15:
            score += 20
        elif 8 <= otm_pct < 10 or 15 < otm_pct <= 20:
            score += 10
        elif otm_pct < 8:
            score -= 20
            warnings.append(f"Strike nur {otm_pct:.1f}% OTM - erhöhtes ITM-Risiko")
        elif otm_pct > 25:
            score -= 10
            warnings.append(f"Strike {otm_pct:.1f}% OTM - möglicherweise zu konservativ")
        
        # 2. Support-Qualität (+/- 15 Punkte)
        if support:
            if support.strength == "strong":
                score += 15
            elif support.strength == "moderate":
                score += 10
            
            if support.confirmed_by_fib:
                score += 10
        else:
            score -= 5
            warnings.append("Kein Support-Level verwendet")
        
        # 3. Credit/Width Verhältnis (+/- 10 Punkte)
        credit = metrics.get("credit", 0)
        width = metrics.get("spread_width", 5)
        credit_pct = (credit / width * 100) if width > 0 else 0
        
        if credit_pct >= 30:
            score += 10
        elif credit_pct >= 25:
            score += 5
        elif credit_pct < 20:
            score -= 10
            warnings.append(f"Credit nur {credit_pct:.0f}% der Spread-Width")
        
        # 4. IV-Rang (+/- 10 Punkte)
        if iv_rank is not None:
            if iv_rank > 50:
                score += 10  # Credit Spreads profitieren von hoher IV
            elif iv_rank < 30:
                score -= 5
                warnings.append(f"Niedriger IV-Rang ({iv_rank:.0f}%) - weniger Prämie")
        
        # 5. Risk/Reward (+/- 5 Punkte)
        rr = metrics.get("risk_reward", 0)
        if rr > 0.40:
            score += 5
        elif rr < 0.25:
            score -= 5
            warnings.append(f"Niedriges Risk/Reward ({rr:.2f})")
        
        # Score auf 0-100 begrenzen
        score = max(0, min(100, score))
        
        # Qualitäts-Kategorie bestimmen
        if score >= 75:
            quality = StrikeQuality.EXCELLENT
        elif score >= 60:
            quality = StrikeQuality.GOOD
        elif score >= 45:
            quality = StrikeQuality.ACCEPTABLE
        else:
            quality = StrikeQuality.POOR
        
        return quality, score, warnings


def calculate_strike_recommendation(
    symbol: str,
    current_price: float,
    support_levels: List[float],
    iv_rank: Optional[float] = None,
    options_data: Optional[List[Dict]] = None,
    fib_levels: Optional[List[Dict]] = None
) -> Dict:
    """
    Convenience-Funktion für einfachen Aufruf
    
    Returns:
        Dictionary mit Strike-Empfehlung
    """
    recommender = StrikeRecommender()
    recommendation = recommender.get_recommendation(
        symbol=symbol,
        current_price=current_price,
        support_levels=support_levels,
        iv_rank=iv_rank,
        options_data=options_data,
        fib_levels=fib_levels
    )
    return recommendation.to_dict()


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Strike Recommender Test ===\n")
    
    # Test mit AAPL
    recommender = StrikeRecommender()
    
    rec = recommender.get_recommendation(
        symbol="AAPL",
        current_price=182.50,
        support_levels=[175.0, 170.0, 165.0, 160.0],
        iv_rank=45,
        fib_levels=[
            {"level": 173.5, "fib": 0.382},
            {"level": 168.0, "fib": 0.5},
            {"level": 162.5, "fib": 0.618}
        ]
    )
    
    print(f"Symbol: {rec.symbol}")
    print(f"Aktueller Kurs: ${rec.current_price}")
    print(f"")
    print(f"=== EMPFEHLUNG ===")
    print(f"Short Strike: ${rec.short_strike}")
    print(f"Long Strike:  ${rec.long_strike}")
    print(f"Spread Width: ${rec.spread_width}")
    print(f"Begründung: {rec.short_strike_reason}")
    print(f"")
    print(f"Geschätztes Delta: {rec.estimated_delta}")
    print(f"Geschätzter Credit: ${rec.estimated_credit}")
    print(f"Max Profit: ${rec.max_profit}")
    print(f"Max Loss: ${rec.max_loss}")
    print(f"Break-Even: ${rec.break_even}")
    print(f"P(Profit): {rec.prob_profit}%")
    print(f"")
    print(f"Qualität: {rec.quality.value.upper()}")
    print(f"Confidence: {rec.confidence_score}/100")
    if rec.warnings:
        print(f"Warnungen: {', '.join(rec.warnings)}")
    
    # Alternativen
    print(f"\n=== ALTERNATIVEN ===")
    alternatives = recommender.get_multiple_recommendations(
        symbol="AAPL",
        current_price=182.50,
        support_levels=[175.0, 170.0, 165.0, 160.0],
        fib_levels=[
            {"level": 173.5, "fib": 0.382},
            {"level": 168.0, "fib": 0.5},
            {"level": 162.5, "fib": 0.618}
        ]
    )
    
    for i, alt in enumerate(alternatives, 1):
        print(f"{i}. {alt.short_strike}/{alt.long_strike} (${alt.spread_width} wide) - "
              f"Conf: {alt.confidence_score}/100 - {alt.quality.value}")
