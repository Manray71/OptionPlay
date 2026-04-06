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

# mypy: warn_unused_ignores=False
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from ..cache.symbol_fundamentals import get_fundamentals_manager
from ..constants.trading_rules import (
    ENTRY_STABILITY_MIN,
    ENTRY_VIX_MAX_NEW_TRADES,
    SIZING_MAX_PER_SECTOR,
    get_regime_rules,
)
from ..models.base import TradeSignal
from ..options.strike_recommender import StrikeRecommender
from ..scanner.multi_strategy_scanner import (
    MultiStrategyScanner,
    ScanConfig,
    ScanMode,
    ScanResult,
)
from ..services.vix_strategy import (
    MarketRegime,
    StrategyRecommendation,
    VIXStrategySelector,
)
from .pick_formatter import format_picks_markdown as _format_picks_markdown
from .pick_formatter import format_single_pick as _format_single_pick
from .recommendation_ranking import RecommendationRankingMixin
from .signal_filter import (
    apply_blacklist_filter,
    apply_sector_diversification,
    apply_stability_filter,
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
    expiry: Optional[str] = None  # e.g. "2026-03-20"
    dte: Optional[int] = None
    dte_warning: Optional[str] = None
    tradeable_status: str = "unknown"  # "READY" / "WARNING" / "NOT_TRADEABLE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "short_strike": self.short_strike,
            "long_strike": self.long_strike,
            "spread_width": self.spread_width,
            "estimated_credit": self.estimated_credit,
            "estimated_delta": self.estimated_delta,
            "prob_profit": self.prob_profit,
            "risk_reward_ratio": self.risk_reward_ratio,
            "quality": self.quality,
            "confidence_score": self.confidence_score,
            "liquidity_quality": self.liquidity_quality,
            "short_oi": self.short_oi,
            "long_oi": self.long_oi,
            "short_spread_pct": self.short_spread_pct,
            "long_spread_pct": self.long_spread_pct,
            "expiry": self.expiry,
            "dte": self.dte,
            "dte_warning": self.dte_warning,
            "tradeable_status": self.tradeable_status,
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
    warnings: list[str] = field(default_factory=list)

    # Liquidity tier (1=high, 2=medium, 3=low)
    liquidity_tier: Optional[int] = None

    # Enhanced scoring (daily_picks re-ranking)
    enhanced_score: Optional[float] = None
    enhanced_score_result: Optional[Any] = None  # EnhancedScoreResult

    # Original signal reference (for shadow trade context logging)
    _signal: Optional[Any] = field(default=None, repr=False)

    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "rank": self.rank,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "score": self.score,
            "stability_score": self.stability_score,
            "speed_score": self.speed_score,
            "reliability_grade": self.reliability_grade,
            "historical_win_rate": self.historical_win_rate,
            "current_price": self.current_price,
            "sector": self.sector,
            "market_cap_category": self.market_cap_category,
            "suggested_strikes": (
                self.suggested_strikes.to_dict() if self.suggested_strikes else None
            ),
            "reason": self.reason,
            "warnings": self.warnings,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.liquidity_tier is not None:
            result["liquidity_tier"] = self.liquidity_tier
        if self.enhanced_score is not None:
            result["enhanced_score"] = self.enhanced_score
        return result


@dataclass
class DailyRecommendationResult:
    """Ergebnis des täglichen Recommendation-Prozesses."""

    picks: list[DailyPick]
    vix_level: Optional[float]
    market_regime: Optional[MarketRegime]
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
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "picks": [p.to_dict() for p in self.picks],
            "vix_level": self.vix_level,
            "market_regime": self.market_regime.value if self.market_regime else None,
            "strategy_recommendation": (
                self.strategy_recommendation.to_dict() if self.strategy_recommendation else None
            ),
            "statistics": {
                "symbols_scanned": self.symbols_scanned,
                "signals_found": self.signals_found,
                "after_stability_filter": self.after_stability_filter,
                "after_sector_diversification": self.after_sector_diversification,
                "after_liquidity_filter": self.after_liquidity_filter,
            },
            "timestamp": self.timestamp.isoformat(),
            "generation_time_seconds": self.generation_time_seconds,
            "warnings": self.warnings,
        }


# =============================================================================
# DAILY RECOMMENDATION ENGINE
# =============================================================================


class DailyRecommendationEngine(RecommendationRankingMixin):
    """
    Engine für tägliche Trading-Empfehlungen.

    Kombiniert:
    - Multi-Strategy Scanner für Signal-Erkennung
    - VIX Strategy Selector für Markt-Regime-Anpassung
    - Strike Recommender für optimale Spread-Empfehlungen
    - Symbol Fundamentals für Stability und Sektor-Info

    Ranking, speed-scoring and strike-recommendation logic lives in
    RecommendationRankingMixin (recommendation_ranking.py).

    Workflow:
    1. VIX-Level abrufen und Regime bestimmen
    2. Multi-Strategy Scan ausführen
    3. Stability-Filter anwenden (≥70)
    4. Sektor-Diversifikation sicherstellen
    5. Strike-Empfehlungen für Top-Kandidaten generieren
    """

    # Konfiguration (aligned with PLAYBOOK via trading_rules.py)
    # Ranking parameters loaded from config/scoring_weights.yaml → ranking section
    _ranking_cfg = None  # Lazy-loaded to avoid circular import at class definition

    @classmethod
    def _get_ranking_defaults(cls) -> dict:
        if cls._ranking_cfg is None:
            from ..config.scoring_config import get_scoring_resolver

            cls._ranking_cfg = get_scoring_resolver().get_ranking_config()
        return cls._ranking_cfg

    @property
    def DEFAULT_CONFIG(self) -> dict:
        rc = self._get_ranking_defaults()
        return {
            "min_stability_score": ENTRY_STABILITY_MIN,  # PLAYBOOK §1
            "min_signal_score": rc.get("min_signal_score", 3.5),
            "max_picks": 5,  # UMBAUPLAN: 3-5 fertige Setups
            "max_per_sector": SIZING_MAX_PER_SECTOR,  # PLAYBOOK §5: 2
            "enable_strike_recommendations": True,
            "enable_sector_diversification": True,
            "enable_blacklist_filter": True,
            "enable_vix_regime_filter": True,
            "stability_weight": rc.get("stability_weight", 0.3),
            "speed_exponent": rc.get("speed_exponent", 0.3),
        }

    def __init__(
        self,
        scanner: Optional[MultiStrategyScanner] = None,
        vix_selector: Optional[VIXStrategySelector] = None,
        strike_recommender: Optional[StrikeRecommender] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
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
                min_score=self.config["min_signal_score"],
                enable_stability_first=True,
                stability_qualified_threshold=self.config["min_stability_score"],
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
        except (ImportError, AttributeError):
            self._fundamentals_manager = None
            logger.warning("Fundamentals manager not available")

        # Caches
        self._vix_cache: Optional[float] = None
        self._last_result: Optional[DailyRecommendationResult] = None
        self._sector_factors: Dict[str, float] = {}  # sector → momentum factor (0.6-1.2)

    # Map MarketRegime enum values to YAML config regime keys
    _REGIME_TO_CONFIG = {
        "LOW_VOL": "low",
        "NORMAL": "normal",
        "DANGER_ZONE": "danger",
        "ELEVATED": "elevated",
        "HIGH_VOL": "high",
        # None (no VIX data) handled at call site with default "normal"
    }

    def set_vix(self, vix: float) -> None:
        """Setzt den aktuellen VIX-Level."""
        self._vix_cache = vix
        self._scanner.set_vix(vix)

    def get_market_regime(self, vix: Optional[float] = None) -> Optional[MarketRegime]:
        """Bestimmt das aktuelle Markt-Regime."""
        vix_level = vix or self._vix_cache
        if vix_level is None:
            return None

        return self._vix_selector.get_regime(vix_level)

    async def get_daily_picks(
        self,
        symbols: list[str],
        data_fetcher: Callable[..., Any],
        max_picks: int = 3,
        vix: Optional[float] = None,
        options_fetcher: Optional[Callable[..., Any]] = None,
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
        warnings: list[str] = []

        # 1. VIX-Level und Regime bestimmen
        vix_level = vix or self._vix_cache
        if vix_level:
            self.set_vix(vix_level)
            regime = self.get_market_regime(vix_level)
            strategy_rec = self._vix_selector.get_recommendation(vix_level)
            # Pass regime to scanner for config-based scoring weights
            config_regime = self._REGIME_TO_CONFIG.get(regime.value, "normal") if regime else "normal"
            self._scanner.set_regime(config_regime)
        else:
            regime = None
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

        # 2b. Prefetch sector momentum factors (for speed score)
        self._sector_factors = {}
        try:
            from ..config.scoring_config import get_scoring_resolver

            sm_config = get_scoring_resolver().get_sector_momentum_config()
            if sm_config.get("enabled", False):
                from ..services.sector_rs import SectorRSService

                service = SectorRSService()
                statuses = await service.get_all_sector_statuses()
                self._sector_factors = {
                    s.sector: (1.0 + s.score_modifier) for s in statuses
                }
                if self._sector_factors:
                    logger.info(
                        f"Loaded sector momentum factors for {len(self._sector_factors)} sectors"
                    )
        except Exception as e:
            logger.debug(f"Sector momentum prefetch skipped: {e}")

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
        if self.config.get("enable_blacklist_filter", True):
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
            min_stability=self.config["min_stability_score"],
            vix=vix_level,
        )
        after_stability = len(filtered_signals)
        logger.info(f"After stability filter: {after_stability} signals")

        # 4. Sektor-Diversifikation
        if self.config["enable_sector_diversification"]:
            diversified_signals = self._apply_sector_diversification(
                filtered_signals,
                max_per_sector=self.config["max_per_sector"],
            )
        else:
            diversified_signals = filtered_signals
        after_diversification = len(diversified_signals)
        logger.info(f"After sector diversification: {after_diversification} signals")

        # 5. Ranking erstellen (kombiniert Score + Stability)
        ranked_signals = self._rank_signals(diversified_signals)

        # 6. Top N auswählen und DailyPicks erstellen
        # Overfetch: process more candidates to account for quality filtering
        try:
            from .enhanced_scoring import (
                calculate_enhanced_score,
                get_enhanced_scoring_config,
            )

            es_config = get_enhanced_scoring_config()
            overfetch_factor = es_config.overfetch_factor if options_fetcher else 1
            reject_quality = es_config.quality_filter.get("reject_quality", "poor")
        except Exception:
            overfetch_factor = 3 if options_fetcher else 1
            reject_quality = "poor"

        candidate_signals = ranked_signals[: max_picks * overfetch_factor]
        picks: list[DailyPick] = []
        pick_signal_pairs: list[tuple[DailyPick, TradeSignal]] = []
        liquidity_rejected = 0

        for signal in candidate_signals:
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

                # Reject quality below threshold (default: "poor" only)
                if liq_quality and liq_quality == reject_quality:
                    liquidity_rejected += 1
                    logger.info(f"Liquidity-filtered: {signal.symbol} " f"(quality={liq_quality})")
                    continue

            pick_signal_pairs.append((pick, signal))

        # 7. Enhanced scoring and re-ranking (when options data available)
        if options_fetcher:
            try:
                from .enhanced_scoring import calculate_enhanced_score

                for pick, signal in pick_signal_pairs:
                    es_result = calculate_enhanced_score(pick, signal)
                    pick.enhanced_score = es_result.enhanced_score
                    pick.enhanced_score_result = es_result

                # Re-sort by enhanced score (descending)
                pick_signal_pairs.sort(
                    key=lambda ps: ps[0].enhanced_score or 0,
                    reverse=True,
                )
            except Exception as e:
                logger.warning(f"Enhanced scoring failed, using base ranking: {e}")

        # Take top max_picks and re-number ranks
        picks = [ps[0] for ps in pick_signal_pairs[:max_picks]]
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

        logger.info(f"Daily picks generated: {len(picks)} recommendations in {duration:.1f}s")

        return result

    def _apply_blacklist_filter(
        self,
        signals: list[TradeSignal],
    ) -> list[TradeSignal]:
        """Delegates to signal_filter.apply_blacklist_filter (Phase 3.2)."""
        return apply_blacklist_filter(signals)

    def _apply_stability_filter(
        self,
        signals: list[TradeSignal],
        min_stability: float,
        vix: Optional[float] = None,
    ) -> list[TradeSignal]:
        """Delegates to signal_filter.apply_stability_filter (Phase 3.2)."""
        return apply_stability_filter(signals, min_stability, vix, self._fundamentals_manager)

    def _apply_sector_diversification(
        self,
        signals: list[TradeSignal],
        max_per_sector: int,
    ) -> list[TradeSignal]:
        """Delegates to signal_filter.apply_sector_diversification (Phase 3.2)."""
        return apply_sector_diversification(signals, max_per_sector, self._fundamentals_manager)

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

    def _format_single_pick(self, pick: DailyPick) -> list[str]:
        """Delegates to pick_formatter.format_single_pick (Phase 3.2)."""
        return _format_single_pick(pick)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_recommendation_engine(
    min_stability: float = ENTRY_STABILITY_MIN,
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
        "min_stability_score": min_stability,
        "min_signal_score": min_score,
        "max_picks": max_picks,
    }
    return DailyRecommendationEngine(config=config)


async def get_quick_picks(
    symbols: list[str],
    data_fetcher: Callable[..., Any],
    vix: Optional[float] = None,
    max_picks: int = 20,
) -> list[DailyPick]:
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
