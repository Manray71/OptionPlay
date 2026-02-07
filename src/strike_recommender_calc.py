"""
Strike Recommender - Metrics Calculation & Quality Evaluation

Extracted from strike_recommender.py to keep module size manageable.
Contains the heavy calculation methods as a mixin class:
  - _calculate_metrics(): Black-Scholes / heuristic credit & delta estimation
  - _evaluate_quality(): Quality scoring for strike recommendations

Usage:
    # StrikeRecommender inherits from this mixin — no external usage needed.
    from .strike_recommender_calc import StrikeMetricsMixin
"""

import logging
from typing import Dict, Optional, Any

try:
    from .constants.trading_rules import (
        SPREAD_MIN_CREDIT_PCT,
        LIQUIDITY_SPREAD_PCT_GOOD,
    )
except ImportError:
    from constants.trading_rules import (
        SPREAD_MIN_CREDIT_PCT,
        LIQUIDITY_SPREAD_PCT_GOOD,
    )

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


class StrikeMetricsMixin:
    """
    Mixin providing metrics calculation and quality evaluation for
    Bull-Put-Spread strike recommendations.

    Expects the host class to have:
        - self.config: dict with strike recommender configuration
    """

    def _calculate_metrics(
        self,
        short_strike: float,
        long_strike: float,
        spread_width: float,
        current_price: float,
        options_data: Optional[list],
        iv_rank: Optional[float],
        dte: int,
    ) -> Dict[str, Any]:
        """
        Calculates metrics for the spread.

        Uses Black-Scholes for accurate delta and probability calculation
        when available, otherwise options data or heuristic estimates.
        """
        metrics: Dict[str, Any] = {}

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
            short_credit = short_put.get("bid", 0) or 0
            long_debit = long_put.get("ask", 0) or 0
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
                    except Exception as e:
                        logger.debug(f"Black-Scholes delta calculation failed: {e}")

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
        support: Optional[object],
        metrics: Dict,
        iv_rank: Optional[float],
    ) -> tuple:
        """
        Evaluates the quality of the recommendation.

        Returns:
            (StrikeQuality, confidence_score, warnings)
        """
        # Import here to avoid circular dependency — StrikeQuality lives in
        # the main strike_recommender module which inherits from this mixin.
        try:
            from .strike_recommender import StrikeQuality
        except ImportError:
            from strike_recommender import StrikeQuality  # type: ignore[no-redef]

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
