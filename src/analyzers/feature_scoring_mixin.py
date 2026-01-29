# OptionPlay - Feature Scoring Mixin
# ===================================
# Shared scoring methods for new features from Feature Engineering

from typing import List, Optional, Tuple
import numpy as np

try:
    from ..indicators.volume_profile import (
        calculate_vwap,
        get_sector,
        get_sector_adjustment,
    )
except ImportError:
    from indicators.volume_profile import (
        calculate_vwap,
        get_sector,
        get_sector_adjustment,
    )


class FeatureScoringMixin:
    """
    Mixin class providing shared scoring methods for new features.

    These features were identified through Feature Engineering Training:
    - VWAP Distance: Most important new feature
    - Market Context (SPY Trend): Critical filter
    - Sector: Moderate impact
    """

    def _score_vwap(
        self,
        prices: List[float],
        volumes: List[int]
    ) -> Tuple[float, float, float, str, str]:
        """
        VWAP Score (0-3 Punkte).

        Based on Feature Engineering Training:
        - Above VWAP >3%: 91.9% win rate → 3 points
        - Above VWAP 1-3%: 87.6% win rate → 2 points
        - Near VWAP: 78.3% win rate → 1 point
        - Below VWAP: 51.7-66.1% win rate → 0 points

        Returns:
            (score, vwap_value, distance_pct, position, reason)
        """
        vwap_result = calculate_vwap(prices, volumes, period=20)

        if not vwap_result:
            return 0, 0, 0, "unknown", "Insufficient data for VWAP"

        vwap = vwap_result.vwap
        distance = vwap_result.distance_pct
        position = vwap_result.position

        # Scoring based on training results
        if distance > 3.0:
            score = 3.0
            reason = f"Strong momentum: {distance:.1f}% above VWAP (91.9% win rate)"
        elif distance > 1.0:
            score = 2.0
            reason = f"Above VWAP: {distance:.1f}% (87.6% win rate)"
        elif distance > -1.0:
            score = 1.0
            reason = f"Near VWAP: {distance:.1f}% (78.3% win rate)"
        elif distance > -3.0:
            score = 0.0
            reason = f"Below VWAP: {distance:.1f}% (66.1% win rate)"
        else:
            score = 0.0
            reason = f"Weak: {distance:.1f}% below VWAP (51.7% win rate)"

        return score, vwap, distance, position, reason

    def _score_market_context(
        self,
        spy_prices: Optional[List[float]]
    ) -> Tuple[float, str, str]:
        """
        Market Context Score (0-2 Punkte).

        Based on Feature Engineering Training:
        - Strong uptrend: 76.1% win rate, +$1.03M → 2 points
        - Uptrend: 70.9% win rate → 1 point
        - Sideways: neutral → 0 points
        - Downtrend: 60.1% win rate, -$470k → -0.5 points (penalty)
        - Strong downtrend: 59.3% win rate → -1 point (penalty)

        Returns:
            (score, spy_trend, reason)
        """
        if not spy_prices or len(spy_prices) < 50:
            return 0, "unknown", "No SPY data for market context"

        # Determine SPY trend
        current = spy_prices[-1]
        sma20 = float(np.mean(spy_prices[-20:]))
        sma50 = float(np.mean(spy_prices[-50:]))

        if current > sma20 > sma50:
            trend = "strong_uptrend"
            score = 2.0
            reason = "Strong market uptrend (76.1% win rate)"
        elif current > sma50 and current > sma20:
            trend = "uptrend"
            score = 1.0
            reason = "Market uptrend (70.9% win rate)"
        elif current > sma50:
            trend = "sideways"
            score = 0.0
            reason = "Market sideways"
        elif current < sma20 < sma50:
            trend = "strong_downtrend"
            score = -1.0
            reason = "Strong market downtrend - CAUTION (59.3% win rate)"
        else:
            trend = "downtrend"
            score = -0.5
            reason = "Market downtrend - reduced expectation (60.1% win rate)"

        return score, trend, reason

    def _score_sector(self, symbol: str) -> Tuple[float, str, str]:
        """
        Sector Score (-1 to +1 Punkt).

        Based on Feature Engineering Training:
        - Consumer Staples: +9% win rate → +0.9 points
        - Utilities: +6.8% → +0.7 points
        - Financials: +6.4% → +0.6 points
        - Technology: -10% → -1.0 points
        - Materials: -7.5% → -0.75 points

        Returns:
            (score, sector_name, reason)
        """
        sector = get_sector(symbol)
        adjustment = get_sector_adjustment(symbol)

        if adjustment > 0.5:
            reason = f"{sector}: strong sector (+{adjustment*10:.0f}% win rate)"
        elif adjustment > 0:
            reason = f"{sector}: favorable sector (+{adjustment*10:.0f}% win rate)"
        elif adjustment < -0.5:
            reason = f"{sector}: challenging sector ({adjustment*10:.0f}% win rate)"
        elif adjustment < 0:
            reason = f"{sector}: slightly unfavorable ({adjustment*10:.0f}% win rate)"
        else:
            reason = f"{sector}: neutral sector"

        return adjustment, sector, reason

    def _apply_feature_scores(
        self,
        breakdown,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        context=None
    ) -> None:
        """
        Apply all new feature scores to a breakdown object.

        Modifies breakdown in-place with VWAP, market context, and sector scores.
        """
        # VWAP Score
        vwap_result = self._score_vwap(prices, volumes)
        breakdown.vwap_score = vwap_result[0]
        breakdown.vwap_value = vwap_result[1]
        breakdown.vwap_distance_pct = vwap_result[2]
        breakdown.vwap_position = vwap_result[3]
        breakdown.vwap_reason = vwap_result[4]

        # Market Context Score
        if context and hasattr(context, 'spy_prices') and context.spy_prices:
            market_result = self._score_market_context(context.spy_prices)
            breakdown.market_context_score = market_result[0]
            breakdown.spy_trend = market_result[1]
            breakdown.market_context_reason = market_result[2]
        else:
            breakdown.market_context_score = 0
            breakdown.spy_trend = "unknown"
            breakdown.market_context_reason = "No SPY data available"

        # Sector Score
        sector_result = self._score_sector(symbol)
        breakdown.sector_score = sector_result[0]
        breakdown.sector = sector_result[1]
        breakdown.sector_reason = sector_result[2]
