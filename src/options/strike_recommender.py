#!/usr/bin/env python3
"""
Strike Recommendation Module for Bull-Put-Spreads

Analyzes support levels and delta targeting to recommend
optimal strike combinations.

Core Logic:
1. Support level analysis (historical pivot points)
2. Delta targeting — Short Put: -0.20, Long Put: -0.05
3. Spread width derived from delta-selected strikes (not fixed)
4. Premium and risk/reward calculation
5. Fibonacci retracements as additional confirmation

Usage:
    from src.strike_recommender import StrikeRecommender

    recommender = StrikeRecommender()
    recommendation = recommender.get_recommendation(
        symbol="AAPL",
        current_price=182.50,
        support_levels=[175.0, 170.0, 165.0],
        iv_rank=45,
        options_data=[...],  # Optional: Options chain with Greeks
        fib_levels=[...]     # Optional: Fibonacci levels
    )
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from ..constants.trading_rules import (
    ENTRY_OPEN_INTEREST_MIN,
    LIQUIDITY_OI_EXCELLENT,
    SPREAD_DTE_TARGET,
    SPREAD_LONG_DELTA_MAX,
    SPREAD_LONG_DELTA_MIN,
    SPREAD_LONG_DELTA_TARGET,
    SPREAD_MIN_CREDIT_PCT,
    SPREAD_SHORT_DELTA_MAX,
    SPREAD_SHORT_DELTA_MIN,
    SPREAD_SHORT_DELTA_TARGET,
)

# ConfigLoader from config package
try:
    from ..config import ConfigLoader

    _CONFIG_AVAILABLE = True
except ImportError:
    _CONFIG_AVAILABLE = False

# VIX regime for context
try:
    from ..services.vix_strategy import MarketRegime
except ImportError:
    MarketRegime = None  # VIX regime features disabled

from .strike_recommender_calc import StrikeMetricsMixin

logger = logging.getLogger(__name__)


class StrikeQuality(Enum):
    """Rating of strike recommendation"""

    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"


@dataclass
class SupportLevel:
    """Support level with metadata"""

    price: float
    touches: int = 1
    strength: str = "moderate"  # weak, moderate, strong
    confirmed_by_fib: bool = False
    distance_pct: float = 0.0  # Distance to current price in %


@dataclass
class StrikeRecommendation:
    """Recommended strike combination for Bull-Put-Spread"""

    symbol: str
    current_price: float

    # Strike prices
    short_strike: float
    long_strike: float
    spread_width: float

    # Basis for the recommendation
    short_strike_reason: str
    support_level_used: Optional[SupportLevel] = None

    # Options metrics (if available)
    estimated_delta: Optional[float] = None  # Short Put Delta
    long_delta: Optional[float] = None  # Long Put Delta
    estimated_credit: Optional[float] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None
    break_even: Optional[float] = None

    # Probabilities
    prob_profit: Optional[float] = None  # P(OTM at expiration)
    risk_reward_ratio: Optional[float] = None

    # Rating
    quality: StrikeQuality = StrikeQuality.GOOD
    confidence_score: float = 0.0  # 0-100
    warnings: List[str] = field(default_factory=list)

    # Data source: "provider", "black_scholes", or "heuristic"
    data_source: str = "provider"

    def to_dict(self) -> Dict:
        """Converts to dictionary for JSON output"""
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "short_strike": self.short_strike,
            "long_strike": self.long_strike,
            "spread_width": self.spread_width,
            "short_strike_reason": self.short_strike_reason,
            "estimated_delta": self.estimated_delta,
            "long_delta": self.long_delta,
            "estimated_credit": self.estimated_credit,
            "max_loss": self.max_loss,
            "max_profit": self.max_profit,
            "break_even": self.break_even,
            "prob_profit": self.prob_profit,
            "risk_reward_ratio": self.risk_reward_ratio,
            "quality": self.quality.value,
            "confidence_score": self.confidence_score,
            "warnings": self.warnings,
            "data_source": self.data_source,
            "support_level": (
                {
                    "price": self.support_level_used.price,
                    "strength": self.support_level_used.strength,
                    "touches": self.support_level_used.touches,
                    "confirmed_by_fib": self.support_level_used.confirmed_by_fib,
                }
                if self.support_level_used
                else None
            ),
        }


class StrikeRecommender(StrikeMetricsMixin):
    """
    Strike recommendation engine for Bull-Put-Spreads

    Criteria for strike selection (PLAYBOOK §2):
    1. Short Put: Delta -0.20 (±0.03) — "Delta ist heilig"
    2. Long Put: Delta -0.05 (±0.02) — protective wing
    3. Spread width is DERIVED from delta-selected strikes (not fixed)
    4. Fallback to price-based width when options data unavailable

    Strike selection priority:
    1. Delta-based (if options data with Greeks available)
    2. Below strong support level
    3. Standard OTM percentage

    Heavy calculation methods (_calculate_metrics, _evaluate_quality)
    are provided by StrikeMetricsMixin from strike_recommender_calc.py.
    """

    # Configurable parameters
    DEFAULT_CONFIG = {
        # Short Put Delta targeting (PLAYBOOK §2: -0.20 ±0.03)
        "delta_target": SPREAD_SHORT_DELTA_TARGET,  # -0.20
        "delta_min": SPREAD_SHORT_DELTA_MIN,  # -0.17
        "delta_max": SPREAD_SHORT_DELTA_MAX,  # -0.23
        # Long Put Delta targeting (PLAYBOOK §2: -0.05 ±0.02)
        "long_delta_target": SPREAD_LONG_DELTA_TARGET,  # -0.05
        "long_delta_min": SPREAD_LONG_DELTA_MIN,  # -0.03
        "long_delta_max": SPREAD_LONG_DELTA_MAX,  # -0.07
        # OTM requirements (quality scoring only — does NOT override delta-based selection)
        # Used as: sanity-check for support-based fallback, quality score factor
        "min_otm_pct": 8.0,  # At least 8% below spot
        "target_otm_pct": 12.0,  # Ideal: 12% below spot
        "max_otm_pct": 25.0,  # Not further than 25%
        # Spread width: NO configured value — derived from delta (PLAYBOOK §2)
        # Fallback uses ~12% of stock price as estimate when no options data
        # Support level rating
        "min_touches_strong": 3,
        "min_touches_moderate": 2,
        # Premium requirements (PLAYBOOK §2: ≥10% Spread-Breite)
        "min_credit_pct": SPREAD_MIN_CREDIT_PCT,  # 10
        "target_credit_pct": 30,  # Ideal: 30%
    }

    def __init__(self, config: Optional[Dict] = None, use_config_loader: bool = True) -> None:
        """
        Initializes the Strike Recommender

        Args:
            config: Optional configuration (overrides defaults)
            use_config_loader: If True, try to load settings from ConfigLoader
        """
        # Start with defaults
        self.config = {**self.DEFAULT_CONFIG}

        # Try to use ConfigLoader
        if use_config_loader and _CONFIG_AVAILABLE:
            try:
                loader = ConfigLoader()

                # Load options settings from settings.yaml
                if hasattr(loader, "settings") and loader.settings:
                    options_cfg = loader.settings.options

                    # Short Put Delta targets
                    if options_cfg.delta_target:
                        self.config["delta_target"] = options_cfg.delta_target
                    if options_cfg.delta_min:
                        self.config["delta_min"] = options_cfg.delta_min
                    if options_cfg.delta_max:
                        self.config["delta_max"] = options_cfg.delta_max

                    # Long Put Delta targets
                    if hasattr(options_cfg, "long_delta_target") and options_cfg.long_delta_target:
                        self.config["long_delta_target"] = options_cfg.long_delta_target
                    if (
                        hasattr(options_cfg, "long_delta_minimum")
                        and options_cfg.long_delta_minimum
                    ):
                        self.config["long_delta_min"] = options_cfg.long_delta_minimum
                    if (
                        hasattr(options_cfg, "long_delta_maximum")
                        and options_cfg.long_delta_maximum
                    ):
                        self.config["long_delta_max"] = options_cfg.long_delta_maximum

                    # Premium requirements
                    if options_cfg.min_credit_pct:
                        self.config["min_credit_pct"] = options_cfg.min_credit_pct

                    logger.info(
                        f"StrikeRecommender config — "
                        f"Short delta: target={self.config['delta_target']}, "
                        f"range=[{self.config['delta_min']}, {self.config['delta_max']}] | "
                        f"Long delta: target={self.config['long_delta_target']}, "
                        f"range=[{self.config['long_delta_min']}, {self.config['long_delta_max']}]"
                    )

            except Exception as e:
                logger.warning(f"ConfigLoader not available, using defaults: {e}")

        # Explicit config overrides everything
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
        dte: int = SPREAD_DTE_TARGET,
        regime: Optional["MarketRegime"] = None,
    ) -> StrikeRecommendation:
        """
        Generates strike recommendation for a Bull-Put-Spread

        Args:
            symbol: Ticker symbol
            current_price: Current stock price
            support_levels: List of support prices (sorted descending)
            iv_rank: IV rank (0-100), optional
            options_data: Options chain with Greeks, optional
            fib_levels: Fibonacci levels, optional
            dte: Days to Expiration
            regime: Optional MarketRegime for VIX-based spread calculation

        Returns:
            StrikeRecommendation with all details
        """
        logger.info(f"Generating strike recommendation for {symbol} @ ${current_price}")

        # 1. Analyze and enrich support levels
        analyzed_supports = self._analyze_support_levels(current_price, support_levels, fib_levels)

        # 2. Find short strike (delta-based if options data available)
        short_strike, reason, support_used = self._find_short_strike(
            current_price, analyzed_supports, options_data
        )

        # If options data available but no liquid short strike found -> NOT TRADEABLE
        if options_data and short_strike is None:
            logger.warning(f"{symbol}: No liquid strikes available — NOT TRADEABLE")
            return StrikeRecommendation(
                symbol=symbol,
                current_price=current_price,
                short_strike=current_price * 0.90,  # placeholder
                long_strike=current_price * 0.80,  # placeholder
                spread_width=current_price * 0.10,
                short_strike_reason=reason,
                support_level_used=None,
                quality=StrikeQuality.POOR,
                confidence_score=0.0,
                warnings=["No liquid strikes available (OI/Bid insufficient)"],
            )

        # 3. Find long strike — delta-based (primary) or width-based (fallback)
        long_strike = None
        long_delta_found = None
        selection_method = "legacy"

        if options_data and short_strike is not None:
            result = self._find_long_strike_by_delta(options_data, short_strike)
            if result:
                long_strike, long_delta_found = result
                selection_method = "delta"
                logger.info(f"Delta-based long strike: ${long_strike} (d={long_delta_found:.3f})")
            else:
                # Options data available but no liquid long strike
                logger.warning(f"{symbol}: No liquid long strike — NOT TRADEABLE")
                return StrikeRecommendation(
                    symbol=symbol,
                    current_price=current_price,
                    short_strike=short_strike,
                    long_strike=short_strike - current_price * 0.10,
                    spread_width=current_price * 0.10,
                    short_strike_reason=reason,
                    support_level_used=support_used,
                    quality=StrikeQuality.POOR,
                    confidence_score=0.0,
                    warnings=["No liquid long strike available"],
                )

        if long_strike is None and not options_data:
            # Fallback: width-based calculation (NO options data available at all)
            selection_method = "fallback"
            logger.warning(
                f"No delta-based long strike found for {symbol} — "
                f"falling back to price-based width estimate. "
                f"Spread width will NOT be delta-derived (PLAYBOOK §2 violation)."
            )
            spread_widths = self._get_spread_widths_fallback(current_price, regime)
            preferred_width = spread_widths[0]
            long_strike = self._calculate_long_strike(short_strike, preferred_width, current_price)
            logger.warning(
                f"Fallback long strike: ${long_strike} (width=${preferred_width}, "
                f"price-based ~12% estimate — NOT delta-derived per PLAYBOOK §2)"
            )

        actual_width = short_strike - long_strike

        # Extract DTE from options data if available
        options_dte = None
        if options_data:
            dte_values = [opt.get("dte") for opt in options_data if opt.get("dte")]
            if dte_values:
                # Use the most common DTE (the expiry most options belong to)
                from collections import Counter

                options_dte = Counter(dte_values).most_common(1)[0][0]
                dte = options_dte

        # 5. Calculate metrics
        metrics = self._calculate_metrics(
            short_strike, long_strike, actual_width, current_price, options_data, iv_rank, dte
        )

        # 6. Evaluate quality
        quality, confidence, warnings = self._evaluate_quality(
            short_strike,
            long_strike,
            current_price,
            support_used,
            metrics,
            iv_rank,
            selection_method=selection_method,
        )

        # Append liquidity warnings from _calculate_metrics
        liquidity_warnings = metrics.get("liquidity_warnings", [])
        if liquidity_warnings:
            warnings.extend(liquidity_warnings)

        recommendation = StrikeRecommendation(
            symbol=symbol,
            current_price=current_price,
            short_strike=short_strike,
            long_strike=long_strike,
            spread_width=actual_width,
            short_strike_reason=reason,
            support_level_used=support_used,
            estimated_delta=metrics.get("delta"),
            long_delta=metrics.get("long_delta"),
            estimated_credit=metrics.get("credit"),
            max_loss=metrics.get("max_loss"),
            max_profit=metrics.get("max_profit"),
            break_even=metrics.get("break_even"),
            prob_profit=metrics.get("prob_profit"),
            risk_reward_ratio=metrics.get("risk_reward"),
            quality=quality,
            confidence_score=confidence,
            warnings=warnings,
            data_source=metrics.get("data_source", "provider"),
        )

        logger.info(
            f"Recommendation: Short {short_strike} / Long {long_strike}, Quality: {quality.value}"
        )
        return recommendation

    def get_multiple_recommendations(
        self,
        symbol: str,
        current_price: float,
        support_levels: List[float],
        options_data: Optional[List[Dict]] = None,
        fib_levels: Optional[List[Dict]] = None,
        num_alternatives: int = 3,
    ) -> List[StrikeRecommendation]:
        """
        Generates multiple alternative strike recommendations.

        When options data with Greeks is available, generates alternatives by
        varying the long put delta target (-0.04, -0.05, -0.06).
        Falls back to width-based alternatives when no options data.

        Args:
            symbol: Ticker
            current_price: Current price
            support_levels: Support prices
            options_data: Options chain
            fib_levels: Fibonacci levels
            num_alternatives: Number of alternatives

        Returns:
            List of recommendations (sorted by quality)
        """
        recommendations = []

        analyzed_supports = self._analyze_support_levels(current_price, support_levels, fib_levels)

        # Find short strike (same for all alternatives)
        short_strike, reason, support_used = self._find_short_strike(
            current_price, analyzed_supports, options_data
        )

        if options_data:
            # Delta-based alternatives: vary long delta target
            long_delta_targets = [
                SPREAD_LONG_DELTA_TARGET + 0.01,
                SPREAD_LONG_DELTA_TARGET,
                SPREAD_LONG_DELTA_TARGET - 0.01,
            ]
            for long_delta_target in long_delta_targets:
                # Temporarily adjust config for this search
                orig_target = self.config["long_delta_target"]
                self.config["long_delta_target"] = long_delta_target

                result = self._find_long_strike_by_delta(options_data, short_strike)
                self.config["long_delta_target"] = orig_target

                if result is None:
                    continue

                long_strike, long_delta = result
                actual_width = short_strike - long_strike

                if actual_width <= 0:
                    continue

                metrics = self._calculate_metrics(
                    short_strike,
                    long_strike,
                    actual_width,
                    current_price,
                    options_data,
                    None,
                    SPREAD_DTE_TARGET,
                )
                metrics["long_delta"] = long_delta

                quality, confidence, warnings = self._evaluate_quality(
                    short_strike, long_strike, current_price, support_used, metrics, None
                )

                rec = StrikeRecommendation(
                    symbol=symbol,
                    current_price=current_price,
                    short_strike=short_strike,
                    long_strike=long_strike,
                    spread_width=actual_width,
                    short_strike_reason=reason,
                    support_level_used=support_used,
                    estimated_delta=metrics.get("delta"),
                    long_delta=long_delta,
                    estimated_credit=metrics.get("credit"),
                    max_loss=metrics.get("max_loss"),
                    max_profit=metrics.get("max_profit"),
                    break_even=metrics.get("break_even"),
                    prob_profit=metrics.get("prob_profit"),
                    risk_reward_ratio=metrics.get("risk_reward"),
                    quality=quality,
                    confidence_score=confidence,
                    warnings=warnings,
                )
                recommendations.append(rec)
        else:
            # Fallback: width-based alternatives
            spread_widths = self._get_spread_widths_fallback(current_price)

            for width in spread_widths:
                long_strike = self._calculate_long_strike(short_strike, width, current_price)

                if short_strike >= current_price * 0.92:
                    continue

                metrics = self._calculate_metrics(
                    short_strike,
                    long_strike,
                    width,
                    current_price,
                    options_data,
                    None,
                    SPREAD_DTE_TARGET,
                )

                quality, confidence, warnings = self._evaluate_quality(
                    short_strike, long_strike, current_price, support_used, metrics, None
                )

                rec = StrikeRecommendation(
                    symbol=symbol,
                    current_price=current_price,
                    short_strike=short_strike,
                    long_strike=long_strike,
                    spread_width=width,
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
                    warnings=warnings,
                )
                recommendations.append(rec)

        # Sort by confidence, best first
        recommendations.sort(key=lambda x: x.confidence_score, reverse=True)
        return recommendations[:num_alternatives]

    # _analyze_support_levels(), _get_spread_widths_fallback(), and
    # _calculate_long_strike() are inherited from StrikeMetricsMixin
    # (see strike_recommender_calc.py)

    def _is_strike_liquid(self, option: Dict) -> bool:
        """
        Check if an option strike has minimum liquidity for trading.

        Uses ENTRY_OPEN_INTEREST_MIN from trading_rules.py (PLAYBOOK §1).
        Tolerates volume=0 when OI is excellent (>= LIQUIDITY_OI_EXCELLENT).

        Args:
            option: Option data dict with open_interest, bid, volume keys

        Returns:
            True if the strike meets minimum liquidity requirements
        """
        oi = option.get("open_interest") or 0
        bid = option.get("bid") or 0

        if oi < ENTRY_OPEN_INTEREST_MIN:
            return False
        if bid <= 0:
            # Accept strikes with valid mid/last (market closed but historically liquid)
            mid = option.get("mid") or option.get("last") or 0
            if mid <= 0:
                return False
        return True

    def _find_short_strike(
        self, current_price: float, supports: List[SupportLevel], options_data: Optional[List[Dict]]
    ) -> tuple:
        """
        Finds the optimal short strike

        Prioritization:
        1. Strike with delta near -0.20 (if options data available)
        2. Strike below strong support level
        3. Strike at 10-15% OTM

        Returns:
            (short_strike, reason, support_used)
        """
        target_delta = self.config["delta_target"]
        delta_min = self.config["delta_min"]  # e.g. -0.18 (less aggressive)
        delta_max = self.config["delta_max"]  # e.g. -0.21 (more aggressive)
        target_otm = self.config["target_otm_pct"]
        min_otm = self.config["min_otm_pct"]

        logger.debug(
            f"Short strike search: target_delta={target_delta}, "
            f"range=[{delta_min}, {delta_max}], "
            f"options_available={len(options_data) if options_data else 0}"
        )

        # Method 1: Delta-based (if options data available)
        if options_data:
            best_delta_match = None
            best_delta_diff = float("inf")

            for opt in options_data:
                if opt.get("right") != "P":
                    continue

                delta = opt.get("delta")
                strike = opt.get("strike")

                if delta is None or strike is None:
                    continue

                if strike >= current_price:  # Only OTM Puts
                    continue

                # Enforce strict delta limits
                # delta_min is less negative (e.g. -0.18), delta_max is more negative (e.g. -0.21)
                if delta > delta_min or delta < delta_max:
                    continue  # Delta outside allowed range

                # Liquidity check: skip illiquid strikes
                if not self._is_strike_liquid(opt):
                    logger.debug(
                        f"Skipping illiquid short strike ${strike}: "
                        f"OI={opt.get('open_interest', 0)}, "
                        f"Bid={opt.get('bid', 0)}"
                    )
                    continue

                delta_diff = abs(delta - target_delta)
                if delta_diff < best_delta_diff:
                    best_delta_diff = delta_diff
                    best_delta_match = opt

            if best_delta_match:
                strike = best_delta_match["strike"]
                return (strike, f"Delta Targeting: d = {best_delta_match['delta']:.2f}", None)

            # Options data available but no liquid strike found in delta range
            logger.warning(
                f"No liquid short strike found in delta range "
                f"[{delta_min}, {delta_max}] with "
                f"OI >= {ENTRY_OPEN_INTEREST_MIN}"
            )
            return (None, "No liquid strikes in delta range", None)

        # Method 2: Support-based (only when no options data)
        if supports:
            best_support = None

            for support in supports:
                # Support should be in desired OTM range
                if min_otm <= support.distance_pct <= target_otm + 5:
                    best_support = support
                    break

            if best_support:
                # Strike slightly below support level
                strike = self._round_strike(
                    best_support.price * 0.98, current_price  # 2% below support
                )

                reason_parts = [f"Support @ ${best_support.price:.2f}"]
                if best_support.confirmed_by_fib:
                    reason_parts.append("Fib-confirmed")
                if best_support.strength == "strong":
                    reason_parts.append("strong support")

                return (strike, " + ".join(reason_parts), best_support)

        # Method 3: OTM percent-based (Fallback)
        strike = self._round_strike(current_price * (1 - target_otm / 100), current_price)

        return (strike, f"Standard {target_otm}% OTM", None)

    def _find_long_strike_by_delta(
        self, options_data: List[Dict], short_strike: float
    ) -> Optional[tuple]:
        """
        Finds the optimal long strike by delta targeting.

        Searches the options chain for the put with delta closest to
        LONG_DELTA_TARGET (-0.05), enforcing the range [-0.07, -0.03].

        Args:
            options_data: Options chain with Greeks
            short_strike: Already-selected short strike (long must be below)

        Returns:
            (long_strike, long_delta) or None if no suitable option found
        """
        target_delta = self.config["long_delta_target"]  # -0.05
        delta_min = self.config["long_delta_min"]  # -0.03 (less negative)
        delta_max = self.config["long_delta_max"]  # -0.07 (more negative)

        logger.debug(
            f"Long strike search: target_delta={target_delta}, "
            f"range=[{delta_min}, {delta_max}], short_strike={short_strike}"
        )

        best_match = None
        best_delta_diff = float("inf")

        for opt in options_data:
            if opt.get("right") != "P":
                continue

            delta = opt.get("delta")
            strike = opt.get("strike")

            if delta is None or strike is None:
                continue

            # Long strike must be below short strike
            if strike >= short_strike:
                continue

            # Enforce strict delta limits
            # delta_min is less negative (e.g. -0.03), delta_max is more negative (e.g. -0.07)
            if delta > delta_min or delta < delta_max:
                continue

            # Liquidity check: skip illiquid strikes
            # For long puts: tolerate volume=0 when OI is excellent
            oi = opt.get("open_interest") or 0
            bid = opt.get("bid") or 0
            if oi < ENTRY_OPEN_INTEREST_MIN:
                logger.debug(
                    f"Skipping illiquid long strike ${strike}: "
                    f"OI={oi} < {ENTRY_OPEN_INTEREST_MIN}"
                )
                continue
            if bid <= 0 and oi < LIQUIDITY_OI_EXCELLENT:
                logger.debug(
                    f"Skipping long strike ${strike}: Bid=0 and "
                    f"OI={oi} < {LIQUIDITY_OI_EXCELLENT}"
                )
                continue

            delta_diff = abs(delta - target_delta)
            if delta_diff < best_delta_diff:
                best_delta_diff = delta_diff
                best_match = opt

        if best_match:
            return (best_match["strike"], best_match["delta"])

        logger.warning(
            f"No liquid long strike found in delta range "
            f"[{delta_min}, {delta_max}] below short strike ${short_strike}"
        )
        return None

    # _calculate_long_strike(), _round_strike(), _analyze_support_levels(),
    # _get_spread_widths_fallback(), _calculate_metrics(), and _evaluate_quality()
    # are all inherited from StrikeMetricsMixin (see strike_recommender_calc.py)


def calculate_strike_recommendation(
    symbol: str,
    current_price: float,
    support_levels: List[float],
    iv_rank: Optional[float] = None,
    options_data: Optional[List[Dict]] = None,
    fib_levels: Optional[List[Dict]] = None,
) -> Dict:
    """
    Convenience function for simple invocation

    Returns:
        Dictionary with strike recommendation
    """
    recommender = StrikeRecommender()
    recommendation = recommender.get_recommendation(
        symbol=symbol,
        current_price=current_price,
        support_levels=support_levels,
        iv_rank=iv_rank,
        options_data=options_data,
        fib_levels=fib_levels,
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
            {"level": 162.5, "fib": 0.618},
        ],
    )

    print(f"Symbol: {rec.symbol}")
    print(f"Current Price: ${rec.current_price}")
    print(f"")
    print(f"=== RECOMMENDATION ===")
    print(f"Short Strike: ${rec.short_strike}")
    print(f"Long Strike:  ${rec.long_strike}")
    print(f"Spread Width: ${rec.spread_width}")
    print(f"Reasoning: {rec.short_strike_reason}")
    print(f"")
    print(f"Estimated Delta: {rec.estimated_delta}")
    print(f"Estimated Credit: ${rec.estimated_credit}")
    print(f"Max Profit: ${rec.max_profit}")
    print(f"Max Loss: ${rec.max_loss}")
    print(f"Break-Even: ${rec.break_even}")
    print(f"P(Profit): {rec.prob_profit}%")
    print(f"")
    print(f"Quality: {rec.quality.value.upper()}")
    print(f"Confidence: {rec.confidence_score}/100")
    if rec.warnings:
        print(f"Warnings: {', '.join(rec.warnings)}")

    # Alternatives
    print(f"\n=== ALTERNATIVES ===")
    alternatives = recommender.get_multiple_recommendations(
        symbol="AAPL",
        current_price=182.50,
        support_levels=[175.0, 170.0, 165.0, 160.0],
        fib_levels=[
            {"level": 173.5, "fib": 0.382},
            {"level": 168.0, "fib": 0.5},
            {"level": 162.5, "fib": 0.618},
        ],
    )

    for i, alt in enumerate(alternatives, 1):
        print(
            f"{i}. {alt.short_strike}/{alt.long_strike} (${alt.spread_width} wide) - "
            f"Conf: {alt.confidence_score}/100 - {alt.quality.value}"
        )
