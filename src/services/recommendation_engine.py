# OptionPlay - Daily Recommendation Engine
# =========================================
"""
Daily Recommendation Engine für automatische Trading-Empfehlungen.

Workflow:
1. Multi-Strategy Scan ausführen
2. Stability-Filter anwenden (≥70)
3. VIX-Regime-Check und Strategie-Anpassung
4. Sektor-Diversifikation sicherstellen
5. Strike-Empfehlungen generieren

Usage:
    from src.services.recommendation_engine import DailyRecommendationEngine

    engine = DailyRecommendationEngine(api_key="...")
    picks = await engine.get_daily_picks(max_picks=3)

    for pick in picks:
        print(f"{pick.rank}. {pick.symbol} ({pick.strategy}) - Score: {pick.score}")
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Callable, Tuple
from enum import Enum

# Relative imports
try:
    from ..scanner.multi_strategy_scanner import (
        MultiStrategyScanner,
        ScanConfig,
        ScanResult,
        ScanMode,
    )
    from ..vix_strategy import (
        VIXStrategySelector,
        MarketRegime,
        StrategyRecommendation,
        VIXThresholds,
    )
    from ..strike_recommender import (
        StrikeRecommender,
        StrikeRecommendation,
    )
    from ..models.base import TradeSignal
    from ..cache.symbol_fundamentals import (
        get_fundamentals_manager,
        SymbolFundamentals,
    )
    from ..constants import (
        VIX_LOW, VIX_NORMAL, VIX_ELEVATED, VIX_HIGH,
        STABILITY_PREMIUM, STABILITY_GOOD, STABILITY_OK,
        MIN_SCORE_DEFAULT,
    )
    from ..constants.trading_rules import (
        ENTRY_STABILITY_MIN,
        ENTRY_EARNINGS_MIN_DAYS,
        ENTRY_VIX_MAX_NEW_TRADES,
        BLACKLIST_SYMBOLS,
        is_blacklisted,
        get_adjusted_stability_min,
        SIZING_MAX_PER_SECTOR,
        SPREAD_DTE_MIN,
        SPREAD_DTE_MAX,
        LIQUIDITY_MIN_QUALITY_DAILY_PICKS,
        get_vix_regime,
        get_regime_rules,
    )
    from .signal_filter import (
        apply_blacklist_filter,
        apply_stability_filter,
        apply_sector_diversification,
    )
    from .pick_formatter import (
        format_picks_markdown as _format_picks_markdown,
        format_single_pick as _format_single_pick,
    )
except ImportError:
    from scanner.multi_strategy_scanner import (
        MultiStrategyScanner,
        ScanConfig,
        ScanResult,
        ScanMode,
    )
    from vix_strategy import (
        VIXStrategySelector,
        MarketRegime,
        StrategyRecommendation,
        VIXThresholds,
    )
    from strike_recommender import (
        StrikeRecommender,
        StrikeRecommendation,
    )
    from models.base import TradeSignal
    from cache.symbol_fundamentals import (
        get_fundamentals_manager,
        SymbolFundamentals,
    )
    from constants import (
        VIX_LOW, VIX_NORMAL, VIX_ELEVATED, VIX_HIGH,
        STABILITY_PREMIUM, STABILITY_GOOD, STABILITY_OK,
        MIN_SCORE_DEFAULT,
    )
    from services.signal_filter import (
        apply_blacklist_filter,
        apply_stability_filter,
        apply_sector_diversification,
    )
    from services.pick_formatter import (
        format_picks_markdown as _format_picks_markdown,
        format_single_pick as _format_single_pick,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SuggestedStrikes:
    """Empfohlene Strikes für einen Bull-Put-Spread."""
    short_strike: float
    long_strike: float
    spread_width: float
    estimated_credit: Optional[float] = None
    estimated_delta: Optional[float] = None
    prob_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    quality: str = "good"
    confidence_score: float = 0.0
    # Liquidity fields
    liquidity_quality: Optional[str] = None
    short_oi: Optional[int] = None
    long_oi: Optional[int] = None
    short_spread_pct: Optional[float] = None
    long_spread_pct: Optional[float] = None
    # Expiry / DTE / Tradeable Status
    expiry: Optional[str] = None              # e.g. "2026-03-20"
    dte: Optional[int] = None
    dte_warning: Optional[str] = None
    tradeable_status: str = "unknown"         # "READY" / "WARNING" / "NOT_TRADEABLE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'short_strike': self.short_strike,
            'long_strike': self.long_strike,
            'spread_width': self.spread_width,
            'estimated_credit': self.estimated_credit,
            'estimated_delta': self.estimated_delta,
            'prob_profit': self.prob_profit,
            'risk_reward_ratio': self.risk_reward_ratio,
            'quality': self.quality,
            'confidence_score': self.confidence_score,
            'liquidity_quality': self.liquidity_quality,
            'short_oi': self.short_oi,
            'long_oi': self.long_oi,
            'short_spread_pct': self.short_spread_pct,
            'long_spread_pct': self.long_spread_pct,
            'expiry': self.expiry,
            'dte': self.dte,
            'dte_warning': self.dte_warning,
            'tradeable_status': self.tradeable_status,
        }


@dataclass
class DailyPick:
    """
    Eine tägliche Trading-Empfehlung.

    Kombiniert Signal-Analyse, Stability-Score und Strike-Empfehlung
    in einer übersichtlichen Struktur.
    """
    rank: int  # 1, 2, 3, ...
    symbol: str
    strategy: str  # pullback, ath_breakout, bounce, earnings_dip
    score: float  # Normalized 0-10

    # Symbol-Qualität
    stability_score: float  # 0-100, aus Backtest-Daten
    reliability_grade: Optional[str] = None  # A, B, C, D, F
    historical_win_rate: Optional[float] = None  # %

    # Strike-Empfehlung
    suggested_strikes: Optional[SuggestedStrikes] = None

    # Chain-Validierung (echte Marktdaten, Phase 2)
    spread_validation: Optional[Any] = None  # SpreadValidation from options_chain_validator

    # Entry Quality Score (Phase 3)
    entry_quality: Optional[Any] = None  # EntryQuality from entry_quality_scorer
    ranking_score: Optional[float] = None  # Signal Score × (1 + EQS × 0.3)

    # Speed Score (Kapitaleffizienz-Prediktor, 0-10)
    speed_score: float = 0.0

    # Kontext
    current_price: float = 0.0
    sector: Optional[str] = None
    market_cap_category: Optional[str] = None

    # Begründung und Warnungen
    reason: str = ""
    warnings: List[str] = field(default_factory=list)

    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'rank': self.rank,
            'symbol': self.symbol,
            'strategy': self.strategy,
            'score': self.score,
            'stability_score': self.stability_score,
            'speed_score': self.speed_score,
            'reliability_grade': self.reliability_grade,
            'historical_win_rate': self.historical_win_rate,
            'current_price': self.current_price,
            'sector': self.sector,
            'market_cap_category': self.market_cap_category,
            'suggested_strikes': self.suggested_strikes.to_dict() if self.suggested_strikes else None,
            'reason': self.reason,
            'warnings': self.warnings,
            'timestamp': self.timestamp.isoformat(),
        }


@dataclass
class DailyRecommendationResult:
    """Ergebnis des täglichen Recommendation-Prozesses."""
    picks: List[DailyPick]
    vix_level: Optional[float]
    market_regime: MarketRegime
    strategy_recommendation: Optional[StrategyRecommendation]
    scan_result: Optional[ScanResult]

    # Statistiken
    symbols_scanned: int = 0
    signals_found: int = 0
    after_stability_filter: int = 0
    after_sector_diversification: int = 0
    after_liquidity_filter: int = 0

    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    generation_time_seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'picks': [p.to_dict() for p in self.picks],
            'vix_level': self.vix_level,
            'market_regime': self.market_regime.value,
            'strategy_recommendation': self.strategy_recommendation.to_dict() if self.strategy_recommendation else None,
            'statistics': {
                'symbols_scanned': self.symbols_scanned,
                'signals_found': self.signals_found,
                'after_stability_filter': self.after_stability_filter,
                'after_sector_diversification': self.after_sector_diversification,
                'after_liquidity_filter': self.after_liquidity_filter,
            },
            'timestamp': self.timestamp.isoformat(),
            'generation_time_seconds': self.generation_time_seconds,
            'warnings': self.warnings,
        }


# =============================================================================
# DAILY RECOMMENDATION ENGINE
# =============================================================================

class DailyRecommendationEngine:
    """
    Engine für tägliche Trading-Empfehlungen.

    Kombiniert:
    - Multi-Strategy Scanner für Signal-Erkennung
    - VIX Strategy Selector für Markt-Regime-Anpassung
    - Strike Recommender für optimale Spread-Empfehlungen
    - Symbol Fundamentals für Stability und Sektor-Info

    Workflow:
    1. VIX-Level abrufen und Regime bestimmen
    2. Multi-Strategy Scan ausführen
    3. Stability-Filter anwenden (≥70)
    4. Sektor-Diversifikation sicherstellen
    5. Strike-Empfehlungen für Top-Kandidaten generieren
    """

    # Konfiguration (aligned with PLAYBOOK via trading_rules.py)
    DEFAULT_CONFIG = {
        'min_stability_score': ENTRY_STABILITY_MIN,   # PLAYBOOK §1: 70.0
        'min_signal_score': 3.5,        # Lowered: score is for ranking, not filtering
        'max_picks': 5,                 # UMBAUPLAN: 3-5 fertige Setups
        'max_per_sector': SIZING_MAX_PER_SECTOR,  # PLAYBOOK §5: 2
        'enable_strike_recommendations': True,
        'enable_sector_diversification': True,
        'enable_blacklist_filter': True,
        'enable_vix_regime_filter': True,
        'stability_weight': 0.3,        # 30% Stability, 70% Signal-Score
        'speed_exponent': 0.3,          # Speed^0.3 Multiplikator (PLAYBOOK)
    }

    def __init__(
        self,
        scanner: Optional[MultiStrategyScanner] = None,
        vix_selector: Optional[VIXStrategySelector] = None,
        strike_recommender: Optional[StrikeRecommender] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialisiert die Recommendation Engine.

        Args:
            scanner: Optional vorkonfigurierter Scanner
            vix_selector: Optional VIX Strategy Selector
            strike_recommender: Optional Strike Recommender
            config: Optional Konfiguration
        """
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}

        # Scanner initialisieren
        if scanner:
            self._scanner = scanner
        else:
            scan_config = ScanConfig(
                min_score=self.config['min_signal_score'],
                enable_stability_first=True,
                stability_good_threshold=self.config['min_stability_score'],
                enable_fundamentals_filter=True,
            )
            self._scanner = MultiStrategyScanner(scan_config)

        # VIX Selector
        self._vix_selector = vix_selector or VIXStrategySelector()

        # Strike Recommender
        self._strike_recommender = strike_recommender or StrikeRecommender()

        # Fundamentals Manager
        try:
            self._fundamentals_manager = get_fundamentals_manager()
        except Exception:
            self._fundamentals_manager = None
            logger.warning("Fundamentals manager not available")

        # Caches
        self._vix_cache: Optional[float] = None
        self._last_result: Optional[DailyRecommendationResult] = None

    def set_vix(self, vix: float) -> None:
        """Setzt den aktuellen VIX-Level."""
        self._vix_cache = vix
        self._scanner.set_vix(vix)

    def get_market_regime(self, vix: Optional[float] = None) -> MarketRegime:
        """Bestimmt das aktuelle Markt-Regime."""
        vix_level = vix or self._vix_cache
        if vix_level is None:
            return MarketRegime.UNKNOWN

        return self._vix_selector.get_regime(vix_level)

    async def get_daily_picks(
        self,
        symbols: List[str],
        data_fetcher: Callable,
        max_picks: int = 3,
        vix: Optional[float] = None,
        options_fetcher: Optional[Callable] = None,
    ) -> DailyRecommendationResult:
        """
        Generiert die täglichen Trading-Empfehlungen.

        Args:
            symbols: Liste der zu scannenden Symbole
            data_fetcher: Async-Funktion zum Abrufen der Preisdaten
            max_picks: Maximale Anzahl Empfehlungen
            vix: Optional: Aktueller VIX-Level
            options_fetcher: Optional: Async-Funktion zum Abrufen der Options-Chain

        Returns:
            DailyRecommendationResult mit Picks und Statistiken
        """
        start_time = datetime.now()
        warnings: List[str] = []

        # 1. VIX-Level und Regime bestimmen
        vix_level = vix or self._vix_cache
        if vix_level:
            self.set_vix(vix_level)
            regime = self.get_market_regime(vix_level)
            strategy_rec = self._vix_selector.get_recommendation(vix_level)
        else:
            regime = MarketRegime.UNKNOWN
            strategy_rec = None
            warnings.append("VIX-Level nicht verfügbar - verwende Standard-Strategie")

        # Regime-spezifische Warnungen
        if regime == MarketRegime.DANGER_ZONE:
            warnings.append(
                f"⚠️ DANGER ZONE (VIX {vix_level:.1f}): "
                "Erhöhte Vorsicht geboten, nur Premium-Symbole empfohlen"
            )
        elif regime == MarketRegime.HIGH_VOL:
            warnings.append(
                f"⚠️ HIGH VOLATILITY (VIX {vix_level:.1f}): "
                "Crash-Modus aktiv, sehr selektiv handeln"
            )

        # 2. VIX-Regime pre-check: no new trades if VIX >= 30 (PLAYBOOK §3)
        if vix_level and vix_level >= ENTRY_VIX_MAX_NEW_TRADES:
            regime_rules = get_regime_rules(vix_level)
            warnings.append(
                f"NO-GO: VIX {vix_level:.1f} >= {ENTRY_VIX_MAX_NEW_TRADES} — "
                f"{regime_rules.notes}"
            )
            # Return empty result with warning
            duration = (datetime.now() - start_time).total_seconds()
            return DailyRecommendationResult(
                picks=[],
                vix_level=vix_level,
                market_regime=regime,
                strategy_recommendation=strategy_rec,
                scan_result=None,
                symbols_scanned=len(symbols),
                signals_found=0,
                after_stability_filter=0,
                after_sector_diversification=0,
                generation_time_seconds=duration,
                warnings=warnings,
            )

        # 3. Multi-Strategy Scan ausführen
        logger.info(f"Starting daily scan for {len(symbols)} symbols...")
        scan_result = await self._scanner.scan_async(
            symbols=symbols,
            data_fetcher=data_fetcher,
            mode=ScanMode.BEST_SIGNAL,  # Nur bestes Signal pro Symbol
        )

        signals_found = len(scan_result.signals)
        logger.info(f"Scan complete: {signals_found} signals found")

        # 4. Blacklist-Filter (PLAYBOOK §1, Check 1 — cheapest check first)
        if self.config.get('enable_blacklist_filter', True):
            filtered_signals = self._apply_blacklist_filter(scan_result.signals)
            logger.info(
                f"After blacklist filter: {len(filtered_signals)} signals "
                f"({signals_found - len(filtered_signals)} removed)"
            )
        else:
            filtered_signals = scan_result.signals

        # 5. Stability-Filter with VIX-regime adjustment (PLAYBOOK §1, Check 2 + §3)
        filtered_signals = self._apply_stability_filter(
            filtered_signals,
            min_stability=self.config['min_stability_score'],
            vix=vix_level,
        )
        after_stability = len(filtered_signals)
        logger.info(f"After stability filter: {after_stability} signals")

        # 4. Sektor-Diversifikation
        if self.config['enable_sector_diversification']:
            diversified_signals = self._apply_sector_diversification(
                filtered_signals,
                max_per_sector=self.config['max_per_sector'],
            )
        else:
            diversified_signals = filtered_signals
        after_diversification = len(diversified_signals)
        logger.info(f"After sector diversification: {after_diversification} signals")

        # 5. Ranking erstellen (kombiniert Score + Stability)
        ranked_signals = self._rank_signals(diversified_signals)

        # 6. Top N auswählen und DailyPicks erstellen
        # Overfetch: process more candidates to account for liquidity filtering
        overfetch_factor = 3 if options_fetcher else 1
        candidate_signals = ranked_signals[:max_picks * overfetch_factor]
        picks = []
        liquidity_rejected = 0

        for signal in candidate_signals:
            if len(picks) >= max_picks:
                break

            pick = await self._create_daily_pick(
                rank=len(picks) + 1,
                signal=signal,
                regime=regime,
                options_fetcher=options_fetcher,
            )

            # Liquidity filter: skip picks with poor liquidity or NOT_TRADEABLE
            if options_fetcher and pick.suggested_strikes:
                s = pick.suggested_strikes
                liq_quality = s.liquidity_quality
                status = s.tradeable_status

                # Reject NOT_TRADEABLE
                if status == "NOT_TRADEABLE":
                    liquidity_rejected += 1
                    logger.info(
                        f"Liquidity-filtered: {signal.symbol} "
                        f"(status=NOT_TRADEABLE, "
                        f"quality={liq_quality}, "
                        f"OI_short={s.short_oi}, "
                        f"spread%={s.short_spread_pct})"
                    )
                    continue

                # Reject poor/fair liquidity
                if liq_quality and liq_quality == "poor":
                    liquidity_rejected += 1
                    logger.info(
                        f"Liquidity-filtered: {signal.symbol} "
                        f"(quality={liq_quality})"
                    )
                    continue
                if liq_quality and liq_quality == "fair":
                    liquidity_rejected += 1
                    logger.info(
                        f"Liquidity-filtered: {signal.symbol} "
                        f"(quality={liq_quality}, min=good)"
                    )
                    continue

            picks.append(pick)

        # Re-rank picks after liquidity filtering
        for i, pick in enumerate(picks, 1):
            pick.rank = i

        after_liquidity = after_diversification - liquidity_rejected

        # Ergebnis zusammenstellen
        duration = (datetime.now() - start_time).total_seconds()

        result = DailyRecommendationResult(
            picks=picks,
            vix_level=vix_level,
            market_regime=regime,
            strategy_recommendation=strategy_rec,
            scan_result=scan_result,
            symbols_scanned=scan_result.symbols_scanned,
            signals_found=signals_found,
            after_stability_filter=after_stability,
            after_sector_diversification=after_diversification,
            after_liquidity_filter=after_liquidity,
            generation_time_seconds=duration,
            warnings=warnings,
        )

        self._last_result = result

        logger.info(
            f"Daily picks generated: {len(picks)} recommendations in {duration:.1f}s"
        )

        return result

    def _apply_blacklist_filter(
        self,
        signals: List[TradeSignal],
    ) -> List[TradeSignal]:
        """Delegates to signal_filter.apply_blacklist_filter (Phase 3.2)."""
        return apply_blacklist_filter(signals)

    def _apply_stability_filter(
        self,
        signals: List[TradeSignal],
        min_stability: float,
        vix: Optional[float] = None,
    ) -> List[TradeSignal]:
        """Delegates to signal_filter.apply_stability_filter (Phase 3.2)."""
        return apply_stability_filter(
            signals, min_stability, vix, self._fundamentals_manager
        )

    def _apply_sector_diversification(
        self,
        signals: List[TradeSignal],
        max_per_sector: int,
    ) -> List[TradeSignal]:
        """Delegates to signal_filter.apply_sector_diversification (Phase 3.2)."""
        return apply_sector_diversification(
            signals, max_per_sector, self._fundamentals_manager
        )

    # Sektor-Speed-Map aus Phase 4 Analyse (avg days_to_playbook_exit)
    SECTOR_SPEED = {
        'Utilities': 1.0,
        'Healthcare': 0.9,
        'Real Estate': 0.85,
        'Consumer Defensive': 0.7,
        'Financial Services': 0.6,
        'Industrials': 0.5,
        'Consumer Cyclical': 0.4,
        'Communication Services': 0.3,
        'Energy': 0.2,
        'Technology': 0.1,
        'Basic Materials': 0.0,
    }

    def compute_speed_score(
        self,
        dte: float,
        stability_score: float,
        sector: Optional[str],
        pullback_score: Optional[float] = None,
        market_context_score: Optional[float] = None,
    ) -> float:
        """
        Schätzt wie schnell der PLAYBOOK-Exit erreicht wird.

        Basiert auf Phase 4 Korrelationsanalyse:
        - DTE näher an 60 = schneller (r=+0.259)
        - Höhere Stability = schneller (Bucket: >80→34d vs <50→61d)
        - Defensive Sektoren = schneller (Utilities 32.5d vs Tech 40.5d)
        - Stärkerer Pullback = schneller (r=-0.073)
        - Besserer Marktkontext = schneller (r=-0.081)

        Returns:
            Speed Score 0-10 (höher = schnellerer Exit erwartet)
        """
        score = 0.0

        # 1. DTE-Bonus: Näher an 60 = schneller (Max 3.0)
        dte_factor = max(0.0, 1.0 - (dte - 60) / 30)
        score += dte_factor * 3.0

        # 2. Stability-Bonus: Höher = schneller (Max 2.5)
        stab_factor = max(0.0, (stability_score - 70) / 30)
        score += stab_factor * 2.5

        # 3. Sektor-Bonus (Max 1.5)
        score += self.SECTOR_SPEED.get(sector, 0.5) * 1.5

        # 4. Pullback-Score-Bonus (Max 1.5)
        if pullback_score is not None:
            score += min(pullback_score / 10, 1.0) * 1.5

        # 5. Market-Context-Bonus (Max 1.5)
        if market_context_score is not None:
            score += min(max(market_context_score, 0) / 10, 1.0) * 1.5

        return min(score, 10.0)

    def _rank_signals(
        self,
        signals: List[TradeSignal],
    ) -> List[TradeSignal]:
        """
        Rankt Signale nach kombiniertem Score mit Speed-Multiplikator.

        Formel:
            base = (1 - weight) * signal_score + weight * (stability / 10)
            speed_normalized = 0.5 + (speed / 10)    # 0→0.5, 5→1.0, 10→1.5
            combined = base * (speed_normalized ** exponent)

        Speed^0.3 Multiplikator-Effekte:
            Speed 0:  0.81x | Speed 5: 1.00x | Speed 10: 1.13x

        Args:
            signals: Liste von Signalen

        Returns:
            Nach kombiniertem Score sortierte Signal-Liste
        """
        weight = self.config['stability_weight']
        speed_exponent = self.config.get('speed_exponent', 0.3)

        def get_combined_score(signal: TradeSignal) -> float:
            """Returns combined score with speed multiplier."""
            # Signal-Score (0-10)
            signal_score = signal.score

            # Stability-Score (0-100) -> normalisiert auf 0-10
            stability = 0.0
            sector = None
            pullback_score = None
            market_context_score = None

            if signal.details and 'stability' in signal.details:
                stability = signal.details['stability'].get('score', 0.0)

            if self._fundamentals_manager:
                fundamentals = self._fundamentals_manager.get_fundamentals(signal.symbol)
                if fundamentals:
                    if stability == 0.0 and fundamentals.stability_score:
                        stability = fundamentals.stability_score
                    sector = fundamentals.sector

            # Fallback: Sektor aus Signal-Details
            if sector is None and signal.details:
                sector = signal.details.get('sector')

            # Pullback/Market-Context aus Signal-Details extrahieren
            if signal.details:
                scores = signal.details.get('scores', {})
                pullback_score = scores.get('pullback_score')
                market_context_score = scores.get('market_context_score')

            # Base Score: 70% Signal + 30% Stability
            base = (1 - weight) * signal_score + weight * (stability / 10)

            # Speed Score berechnen
            dte = signal.details.get('dte', 75) if signal.details else 75
            speed = self.compute_speed_score(
                dte=dte,
                stability_score=stability,
                sector=sector,
                pullback_score=pullback_score,
                market_context_score=market_context_score,
            )

            # Speed^exponent Multiplikator (PLAYBOOK)
            # Normalisierung: Speed 0-10 → 0.5-1.5, dann ^0.3
            speed_normalized = 0.5 + (speed / 10.0)
            combined = base * (speed_normalized ** speed_exponent)

            return combined

        # Scores berechnen und sortieren
        signals_with_scores = [(s, get_combined_score(s)) for s in signals]
        signals_with_scores.sort(key=lambda x: x[1], reverse=True)

        return [s for s, _ in signals_with_scores]

    async def _create_daily_pick(
        self,
        rank: int,
        signal: TradeSignal,
        regime: MarketRegime,
        options_fetcher: Optional[Callable] = None,
    ) -> DailyPick:
        """
        Erstellt einen DailyPick aus einem Signal.

        Args:
            rank: Rang (1, 2, 3, ...)
            signal: TradeSignal
            regime: Aktuelles Markt-Regime
            options_fetcher: Optional: Async-Funktion zum Abrufen der Options-Chain

        Returns:
            DailyPick mit Strike-Empfehlung
        """
        # Stability und Win-Rate aus Signal-Details
        stability_score = 0.0
        historical_wr = None
        if signal.details and 'stability' in signal.details:
            stability_score = signal.details['stability'].get('score', 0.0)
            historical_wr = signal.details['stability'].get('historical_win_rate')

        # Sektor und Market Cap aus Fundamentals
        sector = None
        market_cap = None
        if self._fundamentals_manager:
            fundamentals = self._fundamentals_manager.get_fundamentals(signal.symbol)
            if fundamentals:
                sector = fundamentals.sector
                market_cap = fundamentals.market_cap_category
                if stability_score == 0.0 and fundamentals.stability_score:
                    stability_score = fundamentals.stability_score
                if historical_wr is None and fundamentals.historical_win_rate:
                    historical_wr = fundamentals.historical_win_rate

        # Strike-Empfehlung generieren
        suggested_strikes = None
        if self.config['enable_strike_recommendations']:
            suggested_strikes = await self._generate_strike_recommendation(
                symbol=signal.symbol,
                current_price=signal.current_price,
                signal=signal,
                regime=regime,
                options_fetcher=options_fetcher,
            )

        # Speed Score berechnen
        dte = signal.details.get('dte', 75) if signal.details else 75
        pullback_score = None
        market_context_score = None
        if signal.details:
            scores = signal.details.get('scores', {})
            pullback_score = scores.get('pullback_score')
            market_context_score = scores.get('market_context_score')

        speed = self.compute_speed_score(
            dte=dte,
            stability_score=stability_score,
            sector=sector,
            pullback_score=pullback_score,
            market_context_score=market_context_score,
        )

        # Warnungen sammeln
        warnings = []
        if signal.reliability_warnings:
            warnings.extend(signal.reliability_warnings)
        if stability_score < 70:
            warnings.append(
                f"⚠️ Stability unter 70 ({stability_score:.0f}) - erhöhtes Risiko"
            )
        if regime == MarketRegime.DANGER_ZONE:
            warnings.append("⚠️ VIX in Danger Zone (20-25) - reduzierte Position empfohlen")

        return DailyPick(
            rank=rank,
            symbol=signal.symbol,
            strategy=signal.strategy,
            score=signal.score,
            stability_score=stability_score,
            speed_score=speed,
            reliability_grade=signal.reliability_grade,
            historical_win_rate=historical_wr,
            current_price=signal.current_price,
            sector=sector,
            market_cap_category=market_cap,
            suggested_strikes=suggested_strikes,
            reason=signal.reason or "",
            warnings=warnings,
        )

    async def _generate_strike_recommendation(
        self,
        symbol: str,
        current_price: float,
        signal: TradeSignal,
        regime: MarketRegime,
        options_fetcher: Optional[Callable] = None,
    ) -> Optional[SuggestedStrikes]:
        """
        Generiert Strike-Empfehlung für einen Bull-Put-Spread.

        Args:
            symbol: Ticker-Symbol
            current_price: Aktueller Preis
            signal: TradeSignal mit Details
            regime: Markt-Regime für Spread-Anpassung
            options_fetcher: Optional: Async-Funktion zum Abrufen der Options-Chain

        Returns:
            SuggestedStrikes oder None
        """
        try:
            # Support-Levels aus Signal-Details extrahieren
            support_levels = []
            if signal.details:
                # Aus Score-Breakdown
                if 'score_breakdown' in signal.details:
                    breakdown = signal.details['score_breakdown']
                    if isinstance(breakdown, dict):
                        components = breakdown.get('components', {})
                        support_info = components.get('support', {})
                        support_level = support_info.get('level')
                        if support_level:
                            support_levels.append(support_level)

                # Aus technicals
                if 'technicals' in signal.details:
                    technicals = signal.details['technicals']
                    if 'support_levels' in technicals:
                        support_levels.extend(technicals['support_levels'])

            # Fallback: Berechne Support als 10% unter aktuellem Preis
            if not support_levels:
                support_levels = [
                    current_price * 0.90,
                    current_price * 0.85,
                    current_price * 0.80,
                ]

            # IV-Rank aus Signal-Details
            iv_rank = None
            if signal.details and 'iv_rank' in signal.details:
                iv_rank = signal.details['iv_rank']

            # Fibonacci-Levels
            fib_levels = None
            if signal.details and 'fib_levels' in signal.details:
                fib_levels = signal.details['fib_levels']

            # MarketRegime für VIX-basierte Spread-Berechnung
            from ..vix_strategy import MarketRegime as VixRegime
            vix_regime = VixRegime(regime.value) if regime != MarketRegime.UNKNOWN else None

            # Fetch options chain if fetcher available
            options_data = None
            if options_fetcher:
                try:
                    options = await options_fetcher(symbol)
                    if options:
                        from datetime import date
                        options_data = [
                            {
                                "strike": opt.strike,
                                "right": "P",
                                "bid": opt.bid,
                                "ask": opt.ask,
                                "delta": opt.delta,
                                "iv": opt.implied_volatility,
                                "dte": (opt.expiry - date.today()).days,
                                "open_interest": opt.open_interest,
                                "volume": opt.volume,
                            }
                            for opt in options
                        ]
                except Exception as e:
                    logger.warning(f"Could not fetch options for {symbol}: {e}")

            # Strike-Empfehlung generieren
            rec = self._strike_recommender.get_recommendation(
                symbol=symbol,
                current_price=current_price,
                support_levels=support_levels,
                iv_rank=iv_rank,
                options_data=options_data,
                fib_levels=fib_levels,
                regime=vix_regime,
            )

            suggested = SuggestedStrikes(
                short_strike=rec.short_strike,
                long_strike=rec.long_strike,
                spread_width=rec.spread_width,
                estimated_credit=rec.estimated_credit,
                estimated_delta=rec.estimated_delta,
                prob_profit=rec.prob_profit,
                risk_reward_ratio=rec.risk_reward_ratio,
                quality=rec.quality.value,
                confidence_score=rec.confidence_score,
            )

            # Extract expiry/DTE from options data
            if options_data:
                dte_values = [
                    opt.get("dte") for opt in options_data if opt.get("dte")
                ]
                expiry_values = [
                    opt.get("expiration") for opt in options_data
                    if opt.get("expiration")
                ]
                if dte_values:
                    from collections import Counter
                    most_common_dte = Counter(dte_values).most_common(1)[0][0]
                    suggested.dte = most_common_dte
                if expiry_values:
                    from collections import Counter
                    most_common_expiry = Counter(expiry_values).most_common(1)[0][0]
                    # Handle both date objects and strings
                    if hasattr(most_common_expiry, 'isoformat'):
                        suggested.expiry = most_common_expiry.isoformat()
                    else:
                        suggested.expiry = str(most_common_expiry)

                # DTE validation against PLAYBOOK rules
                if suggested.dte is not None:
                    if suggested.dte < SPREAD_DTE_MIN:
                        suggested.dte_warning = (
                            f"DTE {suggested.dte} < minimum {SPREAD_DTE_MIN}"
                        )
                    elif suggested.dte > SPREAD_DTE_MAX:
                        suggested.dte_warning = (
                            f"DTE {suggested.dte} > maximum {SPREAD_DTE_MAX}"
                        )

            # Assess liquidity if options data available
            if options_data:
                from ..options.liquidity import LiquidityAssessor
                assessor = LiquidityAssessor()
                spread_liq = assessor.assess_spread(
                    rec.short_strike, rec.long_strike, options_data
                )
                if spread_liq:
                    suggested.liquidity_quality = spread_liq.overall_quality
                    suggested.short_oi = spread_liq.short_strike_liquidity.open_interest
                    suggested.long_oi = spread_liq.long_strike_liquidity.open_interest
                    suggested.short_spread_pct = spread_liq.short_strike_liquidity.spread_pct
                    suggested.long_spread_pct = spread_liq.long_strike_liquidity.spread_pct

            # Determine tradeable status
            liq_quality = suggested.liquidity_quality
            from ..constants.trading_rules import LIQUIDITY_MIN_QUALITY_DAILY_PICKS
            _quality_order = {"excellent": 3, "good": 2, "fair": 1, "poor": 0}
            min_rank = _quality_order.get(LIQUIDITY_MIN_QUALITY_DAILY_PICKS, 2)
            liq_ok = (
                liq_quality is not None
                and _quality_order.get(liq_quality, 0) >= min_rank
            )

            if rec.quality.value == "poor":
                suggested.tradeable_status = "NOT_TRADEABLE"
            elif liq_ok and not suggested.dte_warning:
                suggested.tradeable_status = "READY"
            elif liq_ok and suggested.dte_warning:
                suggested.tradeable_status = "WARNING"
            elif not liq_ok and liq_quality is not None:
                suggested.tradeable_status = "NOT_TRADEABLE"
            else:
                suggested.tradeable_status = "unknown"

            return suggested

        except Exception as e:
            logger.warning(f"Could not generate strike recommendation for {symbol}: {e}")
            return None

    def get_last_result(self) -> Optional[DailyRecommendationResult]:
        """Gibt das letzte Ergebnis zurück."""
        return self._last_result

    def format_picks_markdown(
        self,
        result: Optional[DailyRecommendationResult] = None,
    ) -> str:
        """Delegates to pick_formatter.format_picks_markdown (Phase 3.2)."""
        result = result or self._last_result
        return _format_picks_markdown(result)

    def _format_single_pick(self, pick: DailyPick) -> List[str]:
        """Delegates to pick_formatter.format_single_pick (Phase 3.2)."""
        return _format_single_pick(pick)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_recommendation_engine(
    min_stability: float = 70.0,
    min_score: float = 5.0,
    max_picks: int = 20,
) -> DailyRecommendationEngine:
    """
    Factory-Funktion für einfache Engine-Erstellung.

    Args:
        min_stability: Mindest-Stability-Score (0-100)
        min_score: Mindest-Signal-Score (0-10)
        max_picks: Max Anzahl Empfehlungen

    Returns:
        Konfigurierte DailyRecommendationEngine
    """
    config = {
        'min_stability_score': min_stability,
        'min_signal_score': min_score,
        'max_picks': max_picks,
    }
    return DailyRecommendationEngine(config=config)


async def get_quick_picks(
    symbols: List[str],
    data_fetcher: Callable,
    vix: Optional[float] = None,
    max_picks: int = 20,
) -> List[DailyPick]:
    """
    Schnelle Empfehlungen ohne Engine-Instanz.

    Args:
        symbols: Liste der Symbole
        data_fetcher: Async-Funktion für Preisdaten
        vix: Optional VIX-Level
        max_picks: Max Anzahl Empfehlungen

    Returns:
        Liste von DailyPicks
    """
    engine = create_recommendation_engine(max_picks=max_picks)
    result = await engine.get_daily_picks(
        symbols=symbols,
        data_fetcher=data_fetcher,
        max_picks=max_picks,
        vix=vix,
    )
    return result.picks
