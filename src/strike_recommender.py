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
from typing import List, Dict, Optional, Any
from enum import Enum

try:
    from .constants.trading_rules import (
        SPREAD_SHORT_DELTA_TARGET,
        SPREAD_SHORT_DELTA_MIN,
        SPREAD_SHORT_DELTA_MAX,
        SPREAD_LONG_DELTA_TARGET,
        SPREAD_LONG_DELTA_MIN,
        SPREAD_LONG_DELTA_MAX,
        SPREAD_MIN_CREDIT_PCT,
        ENTRY_OPEN_INTEREST_MIN,
        LIQUIDITY_OI_EXCELLENT,
        LIQUIDITY_SPREAD_PCT_GOOD,
    )
except ImportError:
    from constants.trading_rules import (
        SPREAD_SHORT_DELTA_TARGET,
        SPREAD_SHORT_DELTA_MIN,
        SPREAD_SHORT_DELTA_MAX,
        SPREAD_LONG_DELTA_TARGET,
        SPREAD_LONG_DELTA_MIN,
        SPREAD_LONG_DELTA_MAX,
        SPREAD_MIN_CREDIT_PCT,
        ENTRY_OPEN_INTEREST_MIN,
        LIQUIDITY_OI_EXCELLENT,
        LIQUIDITY_SPREAD_PCT_GOOD,
    )

# ConfigLoader from config package
try:
    from .config import ConfigLoader
    _CONFIG_AVAILABLE = True
except ImportError:
    _CONFIG_AVAILABLE = False

# VIX regime for context
try:
    from .vix_strategy import MarketRegime
except ImportError:
    pass

# Black-Scholes for accurate delta calculation
try:
    from .options.black_scholes import (
        BlackScholes,
        OptionType,
        calculate_delta as bs_calculate_delta,
        calculate_probability_otm,
    )
    _BLACK_SCHOLES_AVAILABLE = True
except ImportError:
    try:
        from src.options.black_scholes import (
            BlackScholes,
            OptionType,
            calculate_delta as bs_calculate_delta,
            calculate_probability_otm,
        )
        _BLACK_SCHOLES_AVAILABLE = True
    except ImportError:
        _BLACK_SCHOLES_AVAILABLE = False

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
    long_delta: Optional[float] = None       # Long Put Delta
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
            "support_level": {
                "price": self.support_level_used.price,
                "strength": self.support_level_used.strength,
                "touches": self.support_level_used.touches,
                "confirmed_by_fib": self.support_level_used.confirmed_by_fib
            } if self.support_level_used else None
        }


class StrikeRecommender:
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
    """

    # Configurable parameters
    DEFAULT_CONFIG = {
        # Short Put Delta targeting (PLAYBOOK §2: -0.20 ±0.03)
        "delta_target": SPREAD_SHORT_DELTA_TARGET,  # -0.20
        "delta_min": SPREAD_SHORT_DELTA_MIN,         # -0.17
        "delta_max": SPREAD_SHORT_DELTA_MAX,         # -0.23

        # Long Put Delta targeting (PLAYBOOK §2: -0.05 ±0.02)
        "long_delta_target": SPREAD_LONG_DELTA_TARGET,  # -0.05
        "long_delta_min": SPREAD_LONG_DELTA_MIN,         # -0.03
        "long_delta_max": SPREAD_LONG_DELTA_MAX,         # -0.07

        # OTM requirements
        "min_otm_pct": 8.0,    # At least 8% below spot
        "target_otm_pct": 12.0, # Ideal: 12% below spot
        "max_otm_pct": 25.0,   # Not further than 25%

        # Spread width: NO configured value — derived from delta (PLAYBOOK §2)
        # Fallback uses ~12% of stock price as estimate when no options data

        # Support level rating
        "min_touches_strong": 3,
        "min_touches_moderate": 2,

        # Premium requirements (PLAYBOOK §2: ≥10% Spread-Breite)
        "min_credit_pct": SPREAD_MIN_CREDIT_PCT,  # 10
        "target_credit_pct": 30,  # Ideal: 30%
    }
    
    def __init__(self, config: Optional[Dict] = None, use_config_loader: bool = True):
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
                if hasattr(loader, 'settings') and loader.settings:
                    options_cfg = loader.settings.options

                    # Short Put Delta targets
                    if options_cfg.delta_target:
                        self.config["delta_target"] = options_cfg.delta_target
                    if options_cfg.delta_min:
                        self.config["delta_min"] = options_cfg.delta_min
                    if options_cfg.delta_max:
                        self.config["delta_max"] = options_cfg.delta_max

                    # Long Put Delta targets
                    if hasattr(options_cfg, 'long_delta_target') and options_cfg.long_delta_target:
                        self.config["long_delta_target"] = options_cfg.long_delta_target
                    if hasattr(options_cfg, 'long_delta_minimum') and options_cfg.long_delta_minimum:
                        self.config["long_delta_min"] = options_cfg.long_delta_minimum
                    if hasattr(options_cfg, 'long_delta_maximum') and options_cfg.long_delta_maximum:
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
        dte: int = 45,
        regime: Optional["MarketRegime"] = None
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
        analyzed_supports = self._analyze_support_levels(
            current_price, support_levels, fib_levels
        )

        # 2. Find short strike (delta-based if options data available)
        short_strike, reason, support_used = self._find_short_strike(
            current_price, analyzed_supports, options_data
        )

        # If options data available but no liquid short strike found -> NOT TRADEABLE
        if options_data and short_strike is None:
            logger.warning(
                f"{symbol}: No liquid strikes available — NOT TRADEABLE"
            )
            return StrikeRecommendation(
                symbol=symbol,
                current_price=current_price,
                short_strike=current_price * 0.90,  # placeholder
                long_strike=current_price * 0.80,   # placeholder
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
                logger.info(
                    f"Delta-based long strike: ${long_strike} (d={long_delta_found:.3f})"
                )
            else:
                # Options data available but no liquid long strike
                logger.warning(
                    f"{symbol}: No liquid long strike — NOT TRADEABLE"
                )
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
            logger.warning(
                f"No delta-based long strike found for {symbol} — "
                f"falling back to price-based width estimate. "
                f"Spread width will NOT be delta-derived (PLAYBOOK §2 violation)."
            )
            spread_widths = self._get_spread_widths_fallback(current_price, regime)
            preferred_width = spread_widths[0]
            long_strike = self._calculate_long_strike(
                short_strike, preferred_width, current_price
            )
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
            short_strike, long_strike, actual_width,
            current_price, options_data, iv_rank, dte
        )

        # 6. Evaluate quality
        quality, confidence, warnings = self._evaluate_quality(
            short_strike, long_strike, current_price,
            support_used, metrics, iv_rank
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
            warnings=warnings
        )

        logger.info(f"Recommendation: Short {short_strike} / Long {long_strike}, Quality: {quality.value}")
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

        analyzed_supports = self._analyze_support_levels(
            current_price, support_levels, fib_levels
        )

        # Find short strike (same for all alternatives)
        short_strike, reason, support_used = self._find_short_strike(
            current_price, analyzed_supports, options_data
        )

        if options_data:
            # Delta-based alternatives: vary long delta target
            long_delta_targets = [-0.04, -0.05, -0.06]
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
                    short_strike, long_strike, actual_width,
                    current_price, options_data, None, 45
                )
                metrics["long_delta"] = long_delta

                quality, confidence, warnings = self._evaluate_quality(
                    short_strike, long_strike, current_price,
                    support_used, metrics, None
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
                    warnings=warnings
                )
                recommendations.append(rec)
        else:
            # Fallback: width-based alternatives
            spread_widths = self._get_spread_widths_fallback(current_price)

            for width in spread_widths:
                long_strike = self._calculate_long_strike(
                    short_strike, width, current_price
                )

                if short_strike >= current_price * 0.92:
                    continue

                metrics = self._calculate_metrics(
                    short_strike, long_strike, width,
                    current_price, options_data, None, 45
                )

                quality, confidence, warnings = self._evaluate_quality(
                    short_strike, long_strike, current_price,
                    support_used, metrics, None
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
                    warnings=warnings
                )
                recommendations.append(rec)

        # Sort by confidence, best first
        recommendations.sort(key=lambda x: x.confidence_score, reverse=True)
        return recommendations[:num_alternatives]

    def _analyze_support_levels(
        self,
        current_price: float,
        support_levels: List[float],
        fib_levels: Optional[List[Dict]] = None
    ) -> List[SupportLevel]:
        """Analyzes and rates support levels"""
        analyzed = []

        fib_prices = set()
        if fib_levels:
            fib_prices = {fl["level"] for fl in fib_levels}

        for price in support_levels:
            if price >= current_price:
                continue

            distance_pct = (current_price - price) / current_price * 100

            # Strength based on touches (would normally be calculated from history)
            # Simplified here: closer to price = stronger
            if distance_pct < 10:
                strength = "strong"
                touches = 3
            elif distance_pct < 15:
                strength = "moderate"
                touches = 2
            else:
                strength = "weak"
                touches = 1

            # Check Fibonacci confirmation
            confirmed_by_fib = False
            if fib_prices:
                for fib_price in fib_prices:
                    if abs(price - fib_price) / price < 0.02:  # 2% tolerance
                        confirmed_by_fib = True
                        break

            analyzed.append(SupportLevel(
                price=price,
                touches=touches,
                strength=strength,
                confirmed_by_fib=confirmed_by_fib,
                distance_pct=distance_pct
            ))

        # Sort by strength and Fib confirmation
        analyzed.sort(
            key=lambda x: (
                x.confirmed_by_fib,
                x.strength == "strong",
                x.strength == "moderate",
                -x.distance_pct  # Closer first
            ),
            reverse=True
        )

        return analyzed
    
    def _get_spread_widths_fallback(
        self,
        price: float,
        regime: Optional["MarketRegime"] = None
    ) -> List[float]:
        """
        Fallback: Estimates spread width when no options data with Greeks
        is available for delta-based long strike selection.

        Uses ~12% of stock price as a conservative estimate, based on
        typical delta-0.20/0.05 spread widths observed in real markets.

        NOTE: This is a FALLBACK only. The primary method is delta-based
        strike selection (PLAYBOOK §2). This fallback emits a WARNING.

        Args:
            price: Current stock price
            regime: Optional MarketRegime (unused, kept for API compat)

        Returns:
            List of estimated spread widths in dollars
        """
        # Estimate based on typical delta-0.20 to delta-0.05 spread
        # Empirically, this is roughly 10-15% of stock price
        estimated_pct = 12.0
        base_width = price * (estimated_pct / 100.0)

        # Round to $2.50 or $5 increments (depending on price level)
        if price < 100:
            base_width = max(2.5, round(base_width / 2.5) * 2.5)
        else:
            base_width = max(5.0, round(base_width / 5.0) * 5.0)

        logger.warning(
            f"Spread width fallback: estimated ${base_width:.2f} "
            f"({estimated_pct}% of ${price:.2f}). "
            f"Use options data for accurate delta-based width."
        )

        return [base_width]

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
            return False
        return True

    def _find_short_strike(
        self,
        current_price: float,
        supports: List[SupportLevel],
        options_data: Optional[List[Dict]]
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
            best_delta_diff = float('inf')

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
                return (
                    strike,
                    f"Delta Targeting: d = {best_delta_match['delta']:.2f}",
                    None
                )

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
                    best_support.price * 0.98,  # 2% below support
                    current_price
                )

                reason_parts = [f"Support @ ${best_support.price:.2f}"]
                if best_support.confirmed_by_fib:
                    reason_parts.append("Fib-confirmed")
                if best_support.strength == "strong":
                    reason_parts.append("strong support")

                return (strike, " + ".join(reason_parts), best_support)

        # Method 3: OTM percent-based (Fallback)
        strike = self._round_strike(
            current_price * (1 - target_otm / 100),
            current_price
        )

        return (strike, f"Standard {target_otm}% OTM", None)
    
    def _find_long_strike_by_delta(
        self,
        options_data: List[Dict],
        short_strike: float
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
        target_delta = self.config["long_delta_target"]   # -0.05
        delta_min = self.config["long_delta_min"]          # -0.03 (less negative)
        delta_max = self.config["long_delta_max"]          # -0.07 (more negative)

        logger.debug(
            f"Long strike search: target_delta={target_delta}, "
            f"range=[{delta_min}, {delta_max}], short_strike={short_strike}"
        )

        best_match = None
        best_delta_diff = float('inf')

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

    def _calculate_long_strike(
        self,
        short_strike: float,
        spread_width: float,
        current_price: float
    ) -> float:
        """Calculates the long strike based on short strike and width (fallback method)"""
        long_strike = short_strike - spread_width

        # Round to standard increments
        return self._round_strike(long_strike, current_price)

    def _round_strike(self, strike: float, reference_price: float) -> float:
        """
        Rounds strike to standard increments

        - Prices < $50: $0.50 or $1 increments
        - Prices $50-$200: $2.50 or $5 increments
        - Prices > $200: $5 or $10 increments
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
        """
        Calculates metrics for the spread.

        Uses Black-Scholes for accurate delta and probability calculation
        when available, otherwise options data or heuristic estimates.
        """
        metrics = {}

        # Base metrics (always calculable)
        metrics["spread_width"] = spread_width
        metrics["max_loss"] = spread_width * 100  # per contract

        # Estimate volatility from IV rank if no real data
        # IV-Rank 50 = approximately 25% IV typical, IV-Rank 80 = approximately 40% IV
        estimated_iv = 0.20 + (iv_rank or 50) / 100 * 0.30 if iv_rank else 0.25

        # Use options data if available
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
            # Real options data
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
            if long_put.get("delta"):
                metrics["long_delta"] = long_put["delta"]
            # Use IV from options data if available
            if short_put.get("impliedVol"):
                estimated_iv = short_put["impliedVol"]

            # Liquidity warnings based on real data
            liquidity_warnings = []
            for label, put_data in [("Short", short_put), ("Long", long_put)]:
                put_bid = put_data.get("bid") or 0
                put_ask = put_data.get("ask") or 0
                put_mid = (put_bid + put_ask) / 2 if (put_bid + put_ask) > 0 else 0
                if put_bid <= 0:
                    liquidity_warnings.append(
                        f"{label} strike ${put_data.get('strike', 0):.0f}: "
                        f"No bid (Bid=0)"
                    )
                elif put_mid > 0:
                    spread_pct = (put_ask - put_bid) / put_mid * 100
                    if spread_pct > LIQUIDITY_SPREAD_PCT_GOOD:
                        liquidity_warnings.append(
                            f"{label} strike ${put_data.get('strike', 0):.0f}: "
                            f"Wide spread ({spread_pct:.1f}% > "
                            f"{LIQUIDITY_SPREAD_PCT_GOOD}%)"
                        )
            # Credit too low warning
            if net_credit > 0 and spread_width > 0:
                credit_pct = (net_credit / spread_width) * 100
                if credit_pct < SPREAD_MIN_CREDIT_PCT:
                    liquidity_warnings.append(
                        f"Credit ${net_credit:.2f} = {credit_pct:.0f}% of "
                        f"spread (min {SPREAD_MIN_CREDIT_PCT}%)"
                    )
            metrics["liquidity_warnings"] = liquidity_warnings

        else:
            # No real options data - use Black-Scholes or heuristic

            # Method 1: Black-Scholes for accurate credit estimation
            if _BLACK_SCHOLES_AVAILABLE and dte > 0:
                try:
                    time_to_expiry = dte / 365.0

                    short_bs = BlackScholes(
                        spot=current_price,
                        strike=short_strike,
                        time_to_expiry=time_to_expiry,
                        volatility=estimated_iv,
                    )
                    long_bs = BlackScholes(
                        spot=current_price,
                        strike=long_strike,
                        time_to_expiry=time_to_expiry,
                        volatility=estimated_iv,
                    )

                    # Calculate theoretical prices
                    short_put_price = short_bs.put_price()
                    long_put_price = long_bs.put_price()
                    estimated_credit = short_put_price - long_put_price

                    # Calculate accurate delta
                    metrics["delta"] = short_bs.delta(OptionType.PUT)

                    if estimated_credit > 0:
                        metrics["credit"] = round(estimated_credit, 2)
                        metrics["max_profit"] = round(estimated_credit * 100, 2)
                        metrics["max_loss"] = round((spread_width - estimated_credit) * 100, 2)
                        metrics["break_even"] = round(short_strike - estimated_credit, 2)
                        metrics["risk_reward"] = round(
                            metrics["max_profit"] / metrics["max_loss"], 2
                        ) if metrics["max_loss"] > 0 else 0

                except Exception as e:
                    logger.debug(f"Black-Scholes calculation failed: {e}")
                    # Fall through to heuristic

            # Method 2: Heuristic estimation (Fallback)
            if "credit" not in metrics:
                otm_pct = (current_price - short_strike) / current_price * 100

                # Base credit estimation (very simplified)
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

            # Delta via Black-Scholes if available but pricing failed
            if "delta" not in metrics:
                if _BLACK_SCHOLES_AVAILABLE and dte > 0:
                    try:
                        metrics["delta"] = bs_calculate_delta(
                            spot=current_price,
                            strike=short_strike,
                            dte=dte,
                            volatility=estimated_iv,
                            option_type=OptionType.PUT,
                        )
                    except Exception:
                        pass

                # Heuristic fallback for delta
                if "delta" not in metrics:
                    otm_pct = (current_price - short_strike) / current_price * 100
                    estimated_delta = -0.50 * (1 - otm_pct / 20)
                    estimated_delta = max(min(estimated_delta, -0.15), -0.45)
                    metrics["delta"] = round(estimated_delta, 2)

        # Profit probability with Black-Scholes or delta-based
        if _BLACK_SCHOLES_AVAILABLE and dte > 0:
            try:
                metrics["prob_profit"] = round(
                    calculate_probability_otm(
                        spot=current_price,
                        strike=short_strike,
                        dte=dte,
                        volatility=estimated_iv,
                        option_type=OptionType.PUT,
                    ) * 100, 1
                )
            except Exception:
                if "delta" in metrics:
                    metrics["prob_profit"] = round((1 - abs(metrics["delta"])) * 100, 1)
        elif "delta" in metrics:
            # P(OTM) approximately = 1 - |Delta|
            metrics["prob_profit"] = round((1 - abs(metrics["delta"])) * 100, 1)

        # Validierung: Probability muss 0-100% sein
        if "prob_profit" in metrics:
            if metrics["prob_profit"] < 0 or metrics["prob_profit"] > 100:
                logger.error(f"Invalid prob_profit: {metrics['prob_profit']}% for {short_strike}")
                metrics["prob_profit"] = max(0, min(100, metrics["prob_profit"]))

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
        Evaluates the quality of the recommendation

        Returns:
            (StrikeQuality, confidence_score, warnings)
        """
        score = 50  # Base score
        warnings = []

        # 1. Check OTM distance (+/- 20 points)
        otm_pct = (current_price - short_strike) / current_price * 100

        if 10 <= otm_pct <= 15:
            score += 20
        elif 8 <= otm_pct < 10 or 15 < otm_pct <= 20:
            score += 10
        elif otm_pct < 8:
            score -= 20
            warnings.append(f"Strike only {otm_pct:.1f}% OTM - increased ITM risk")
        elif otm_pct > 25:
            score -= 10
            warnings.append(f"Strike {otm_pct:.1f}% OTM - possibly too conservative")

        # 2. Support quality (+/- 15 points)
        if support:
            if support.strength == "strong":
                score += 15
            elif support.strength == "moderate":
                score += 10

            if support.confirmed_by_fib:
                score += 10
        else:
            score -= 5
            warnings.append("No support level used")

        # 3. Credit/Width ratio (+/- 10 points)
        credit = metrics.get("credit", 0)
        width = metrics.get("spread_width", 5)
        credit_pct = (credit / width * 100) if width > 0 else 0

        if credit_pct >= 30:
            score += 10
        elif credit_pct >= 25:
            score += 5
        elif credit_pct < 20:
            score -= 10
            warnings.append(f"Credit only {credit_pct:.0f}% of spread width")

        # 4. IV rank (+/- 10 points)
        if iv_rank is not None:
            if iv_rank > 50:
                score += 10  # Credit spreads benefit from high IV
            elif iv_rank < 30:
                score -= 5
                warnings.append(f"Low IV rank ({iv_rank:.0f}%) - less premium")

        # 5. Risk/Reward (+/- 5 points)
        rr = metrics.get("risk_reward", 0)
        if rr > 0.40:
            score += 5
        elif rr < 0.25:
            score -= 5
            warnings.append(f"Low Risk/Reward ({rr:.2f})")

        # Limit score to 0-100
        score = max(0, min(100, score))

        # Determine quality category
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
            {"level": 162.5, "fib": 0.618}
        ]
    )
    
    for i, alt in enumerate(alternatives, 1):
        print(f"{i}. {alt.short_strike}/{alt.long_strike} (${alt.spread_width} wide) - "
              f"Conf: {alt.confidence_score}/100 - {alt.quality.value}")
