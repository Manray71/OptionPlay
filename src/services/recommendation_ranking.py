# OptionPlay - Recommendation Ranking Mixin
# ==========================================
"""
Ranking, speed-scoring and strike-recommendation logic extracted from
DailyRecommendationEngine to keep the main module focused on orchestration.

This module provides `RecommendationRankingMixin` which is mixed into
DailyRecommendationEngine.  All instance attributes it references
(``self.config``, ``self._fundamentals_manager``, ``self._strike_recommender``,
``self._sector_factors``) are initialised by DailyRecommendationEngine.__init__.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from ..constants.trading_rules import (
    LIQUIDITY_MIN_QUALITY_DAILY_PICKS,
    SPREAD_DTE_MAX,
    SPREAD_DTE_MIN,
    SPREAD_DTE_TARGET,
)
from ..models.base import TradeSignal
from ..vix_strategy import MarketRegime

if TYPE_CHECKING:
    from ..cache.symbol_fundamentals import SymbolFundamentalsManager
    from ..strike_recommender import StrikeRecommender

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS (loaded from config/scoring_weights.yaml → ranking section)
# =============================================================================
from ..config.scoring_config import get_scoring_resolver as _get_resolver

_ranking_cfg = _get_resolver().get_ranking_config()
_speed_cfg = _ranking_cfg.get("speed", {})

# Speed scoring: DTE component
SPEED_DTE_OPTIMAL = _speed_cfg.get("dte_optimal", 60)
SPEED_DTE_RANGE = _speed_cfg.get("dte_range", 30)
SPEED_DTE_WEIGHT = _speed_cfg.get("dte_weight", 3.0)

# Speed scoring: stability component
SPEED_STABILITY_BASELINE = _speed_cfg.get("stability_baseline", 70)
SPEED_STABILITY_RANGE = _speed_cfg.get("stability_range", 30)
SPEED_STABILITY_WEIGHT = _speed_cfg.get("stability_weight", 2.5)

# Speed scoring: other component weights
SPEED_SECTOR_WEIGHT = _speed_cfg.get("sector_weight", 1.5)
SPEED_PULLBACK_WEIGHT = _speed_cfg.get("pullback_weight", 1.5)
SPEED_MARKET_CONTEXT_WEIGHT = _speed_cfg.get("market_context_weight", 1.5)

# Speed scoring: max possible score
SPEED_SCORE_MAX = _speed_cfg.get("score_max", 10.0)

# Ranking: stability vs signal weight (30% stability, 70% signal)
RANKING_STABILITY_WEIGHT = _ranking_cfg.get("stability_weight", 0.3)

# Speed multiplier minimum (Speed 0 → 0.5x)
SPEED_MULTIPLIER_MIN = _speed_cfg.get("multiplier_min", 0.5)

# Strike support fallback percentages
_strike_cfg = _ranking_cfg.get("strike_support", {})
STRIKE_SUPPORT_PCT_1 = _strike_cfg.get("pct_1", 0.90)
STRIKE_SUPPORT_PCT_2 = _strike_cfg.get("pct_2", 0.85)
STRIKE_SUPPORT_PCT_3 = _strike_cfg.get("pct_3", 0.80)

# Stability warning threshold
RANKING_STABILITY_WARNING = _ranking_cfg.get("stability_warning", 70)


class RecommendationRankingMixin:
    """
    Mixin providing ranking, speed-score and strike-recommendation helpers.

    Expected instance attributes (set by the host class):
        config: dict[str, Any]
        _fundamentals_manager: Optional[SymbolFundamentalsManager]
        _strike_recommender: StrikeRecommender
        _sector_factors: Dict[str, float]
    """

    # Declare mixin attributes (set by DailyRecommendationEngine.__init__)
    config: Dict[str, Any]
    _fundamentals_manager: Optional[SymbolFundamentalsManager]
    _strike_recommender: StrikeRecommender
    _sector_factors: Dict[str, float]

    # Sektor-Speed-Map aus Phase 4 Analyse (avg days_to_playbook_exit)
    _DEFAULT_SECTOR_SPEED: Dict[str, float] = {
        "Utilities": 1.0,
        "Healthcare": 0.9,
        "Real Estate": 0.85,
        "Consumer Defensive": 0.7,
        "Financial Services": 0.6,
        "Industrials": 0.5,
        "Consumer Cyclical": 0.4,
        "Communication Services": 0.3,
        "Energy": 0.2,
        "Technology": 0.1,
        "Basic Materials": 0.0,
    }
    SECTOR_SPEED: Dict[str, float] = {
        **_DEFAULT_SECTOR_SPEED,
        **_ranking_cfg.get("sector_speed", {}),
    }

    # ------------------------------------------------------------------
    # Speed Score
    # ------------------------------------------------------------------

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
        - Höhere Stability = schneller (Bucket: >80->34d vs <50->61d)
        - Defensive Sektoren = schneller (Utilities 32.5d vs Tech 40.5d)
        - Stärkerer Pullback = schneller (r=-0.073)
        - Besserer Marktkontext = schneller (r=-0.081)

        Returns:
            Speed Score 0-10 (höher = schnellerer Exit erwartet)
        """
        score = 0.0

        # 1. DTE-Bonus: Näher an 60 = schneller (Max 3.0)
        dte_factor = max(0.0, 1.0 - (dte - SPEED_DTE_OPTIMAL) / SPEED_DTE_RANGE)
        score += dte_factor * SPEED_DTE_WEIGHT

        # 2. Stability-Bonus: Höher = schneller (Max 2.5)
        stab_factor = max(0.0, (stability_score - SPEED_STABILITY_BASELINE) / SPEED_STABILITY_RANGE)
        score += stab_factor * SPEED_STABILITY_WEIGHT

        # 3. Sektor-Bonus (Max 1.5) x Cycle Factor (0.6-1.2)
        base_sector_speed = self.SECTOR_SPEED.get(sector, 0.5) * SPEED_SECTOR_WEIGHT
        cycle_factor = self._sector_factors.get(sector, 1.0) if self._sector_factors else 1.0
        score += base_sector_speed * cycle_factor

        # 4. Pullback-Score-Bonus (Max 1.5)
        if pullback_score is not None:
            score += min(pullback_score / 10, 1.0) * SPEED_PULLBACK_WEIGHT

        # 5. Market-Context-Bonus (Max 1.5)
        if market_context_score is not None:
            score += min(max(market_context_score, 0) / 10, 1.0) * SPEED_MARKET_CONTEXT_WEIGHT

        return min(score, SPEED_SCORE_MAX)

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _rank_signals(
        self,
        signals: list[TradeSignal],
    ) -> list[TradeSignal]:
        """
        Rankt Signale nach kombiniertem Score mit Speed-Multiplikator.

        Formel:
            base = (1 - weight) * signal_score + weight * (stability / 10)
            speed_normalized = 0.5 + (speed / 10)    # 0->0.5, 5->1.0, 10->1.5
            combined = base * (speed_normalized ** exponent)

        Speed^0.3 Multiplikator-Effekte:
            Speed 0:  0.81x | Speed 5: 1.00x | Speed 10: 1.13x

        Args:
            signals: Liste von Signalen

        Returns:
            Nach kombiniertem Score sortierte Signal-Liste
        """
        weight: float = self.config["stability_weight"]
        speed_exponent: float = self.config.get("speed_exponent", 0.3)

        def get_combined_score(signal: TradeSignal) -> float:
            """Returns combined score with speed multiplier."""
            # Signal-Score (0-10)
            signal_score = signal.score

            # Stability-Score (0-100) -> normalisiert auf 0-10
            stability = 0.0
            sector = None
            pullback_score = None
            market_context_score = None

            if signal.details and "stability" in signal.details:
                stability = signal.details["stability"].get("score", 0.0)

            if self._fundamentals_manager:
                fundamentals = self._fundamentals_manager.get_fundamentals(signal.symbol)
                if fundamentals:
                    if stability == 0.0 and fundamentals.stability_score:
                        stability = fundamentals.stability_score
                    sector = fundamentals.sector

            # Fallback: Sektor aus Signal-Details
            if sector is None and signal.details:
                sector = signal.details.get("sector")

            # Pullback/Market-Context aus Signal-Details extrahieren
            if signal.details:
                scores = signal.details.get("scores", {})
                pullback_score = scores.get("pullback_score")
                market_context_score = scores.get("market_context_score")

            # Base Score: 70% Signal + 30% Stability
            base = (1 - weight) * signal_score + weight * (stability / 10)

            # Speed Score berechnen
            dte = (
                signal.details.get("dte", SPREAD_DTE_TARGET)
                if signal.details
                else SPREAD_DTE_TARGET
            )
            speed = self.compute_speed_score(
                dte=dte,
                stability_score=stability,
                sector=sector,
                pullback_score=pullback_score,
                market_context_score=market_context_score,
            )

            # Speed^exponent Multiplikator (PLAYBOOK)
            # Normalisierung: Speed 0-10 -> 0.5-1.5, dann ^0.3
            speed_normalized = SPEED_MULTIPLIER_MIN + (speed / SPEED_SCORE_MAX)
            combined = base * (speed_normalized**speed_exponent)

            return float(combined)

        # Scores berechnen und sortieren
        signals_with_scores = [(s, get_combined_score(s)) for s in signals]
        signals_with_scores.sort(key=lambda x: x[1], reverse=True)

        return [s for s, _ in signals_with_scores]

    # ------------------------------------------------------------------
    # Strike Recommendation
    # ------------------------------------------------------------------

    async def _generate_strike_recommendation(
        self,
        symbol: str,
        current_price: float,
        signal: TradeSignal,
        regime: MarketRegime,
        options_fetcher: Optional[Callable[..., Any]] = None,
    ):
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
        # Lazy import to avoid circular dependency
        from .recommendation_engine import SuggestedStrikes

        try:
            # Support-Levels aus Signal-Details extrahieren
            support_levels: list[float] = []
            if signal.details:
                # Aus Score-Breakdown
                if "score_breakdown" in signal.details:
                    breakdown = signal.details["score_breakdown"]
                    if isinstance(breakdown, dict):
                        components = breakdown.get("components", {})
                        support_info = components.get("support", {})
                        support_level = support_info.get("level")
                        if support_level:
                            support_levels.append(support_level)

                # Aus technicals
                if "technicals" in signal.details:
                    technicals = signal.details["technicals"]
                    if "support_levels" in technicals:
                        support_levels.extend(technicals["support_levels"])

            # Fallback: Berechne Support als 10% unter aktuellem Preis
            if not support_levels:
                support_levels = [
                    current_price * STRIKE_SUPPORT_PCT_1,
                    current_price * STRIKE_SUPPORT_PCT_2,
                    current_price * STRIKE_SUPPORT_PCT_3,
                ]

            # IV-Rank aus Signal-Details
            iv_rank = None
            if signal.details and "iv_rank" in signal.details:
                iv_rank = signal.details["iv_rank"]

            # Fibonacci-Levels
            fib_levels = None
            if signal.details and "fib_levels" in signal.details:
                fib_levels = signal.details["fib_levels"]

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
                dte_values = [opt.get("dte") for opt in options_data if opt.get("dte")]
                expiry_values = [
                    opt.get("expiration") for opt in options_data if opt.get("expiration")
                ]
                if dte_values:
                    most_common_dte = Counter(dte_values).most_common(1)[0][0]
                    suggested.dte = most_common_dte
                if expiry_values:
                    most_common_expiry = Counter(expiry_values).most_common(1)[0][0]
                    # Handle both date objects and strings
                    if hasattr(most_common_expiry, "isoformat"):
                        suggested.expiry = most_common_expiry.isoformat()
                    else:
                        suggested.expiry = str(most_common_expiry)

                # DTE validation against PLAYBOOK rules
                if suggested.dte is not None:
                    if suggested.dte < SPREAD_DTE_MIN:
                        suggested.dte_warning = f"DTE {suggested.dte} < minimum {SPREAD_DTE_MIN}"
                    elif suggested.dte > SPREAD_DTE_MAX:
                        suggested.dte_warning = f"DTE {suggested.dte} > maximum {SPREAD_DTE_MAX}"

            # Assess liquidity if options data available
            if options_data:
                from ..options.liquidity import LiquidityAssessor

                assessor = LiquidityAssessor()
                spread_liq = assessor.assess_spread(rec.short_strike, rec.long_strike, options_data)
                if spread_liq:
                    suggested.liquidity_quality = spread_liq.overall_quality
                    suggested.short_oi = spread_liq.short_strike_liquidity.open_interest
                    suggested.long_oi = spread_liq.long_strike_liquidity.open_interest
                    suggested.short_spread_pct = spread_liq.short_strike_liquidity.spread_pct
                    suggested.long_spread_pct = spread_liq.long_strike_liquidity.spread_pct

            # Determine tradeable status
            liq_quality = suggested.liquidity_quality
            _quality_order = {"excellent": 3, "good": 2, "fair": 1, "poor": 0}
            min_rank = _quality_order.get(LIQUIDITY_MIN_QUALITY_DAILY_PICKS, 2)
            liq_ok = liq_quality is not None and _quality_order.get(liq_quality, 0) >= min_rank

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

    # ------------------------------------------------------------------
    # Daily Pick creation
    # ------------------------------------------------------------------

    async def _create_daily_pick(
        self,
        rank: int,
        signal: TradeSignal,
        regime: MarketRegime,
        options_fetcher: Optional[Callable[..., Any]] = None,
    ):
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
        # Lazy import to avoid circular dependency
        from .recommendation_engine import DailyPick

        # Stability und Win-Rate aus Signal-Details
        stability_score = 0.0
        historical_wr = None
        if signal.details and "stability" in signal.details:
            stability_score = signal.details["stability"].get("score", 0.0)
            historical_wr = signal.details["stability"].get("historical_win_rate")

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
        if self.config["enable_strike_recommendations"]:
            suggested_strikes = await self._generate_strike_recommendation(
                symbol=signal.symbol,
                current_price=signal.current_price,
                signal=signal,
                regime=regime,
                options_fetcher=options_fetcher,
            )

        # Speed Score berechnen
        dte = signal.details.get("dte", SPREAD_DTE_TARGET) if signal.details else SPREAD_DTE_TARGET
        pullback_score = None
        market_context_score = None
        if signal.details:
            scores = signal.details.get("scores", {})
            pullback_score = scores.get("pullback_score")
            market_context_score = scores.get("market_context_score")

        speed = self.compute_speed_score(
            dte=dte,
            stability_score=stability_score,
            sector=sector,
            pullback_score=pullback_score,
            market_context_score=market_context_score,
        )

        # Warnungen sammeln
        warnings: list[str] = []
        if signal.reliability_warnings:
            warnings.extend(signal.reliability_warnings)
        if stability_score < RANKING_STABILITY_WARNING:
            warnings.append(
                f"\u26a0\ufe0f Stability unter {RANKING_STABILITY_WARNING} ({stability_score:.0f}) - erh\u00f6htes Risiko"
            )
        if regime == MarketRegime.DANGER_ZONE:
            warnings.append(
                "\u26a0\ufe0f VIX in Danger Zone (20-25) - reduzierte Position empfohlen"
            )

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
