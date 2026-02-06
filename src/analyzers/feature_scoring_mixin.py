# OptionPlay - Feature Scoring Mixin
# ===================================
# Shared scoring methods for new features from Feature Engineering
# Updated 2026-01-30: Now applies trained weights from ML training

from typing import List, Optional, Tuple, Dict
import numpy as np
import logging

try:
    from ..indicators.volume_profile import (
        calculate_vwap,
        get_sector,
        get_sector_adjustment,
        get_sector_adjustment_with_reason,
    )
    from ..indicators.gap_analysis import analyze_gap
except ImportError:
    from indicators.volume_profile import (
        calculate_vwap,
        get_sector,
        get_sector_adjustment,
        get_sector_adjustment_with_reason,
    )
    from indicators.gap_analysis import analyze_gap

# Import central constants
try:
    from ..constants import (
        VWAP_PERIOD, VWAP_STRONG_ABOVE, VWAP_ABOVE, VWAP_BELOW, VWAP_STRONG_BELOW,
        SMA_SHORT, SMA_MEDIUM,
        GAP_SIZE_LARGE, GAP_SIZE_MEDIUM,
    )
except ImportError:
    from constants import (
        VWAP_PERIOD, VWAP_STRONG_ABOVE, VWAP_ABOVE, VWAP_BELOW, VWAP_STRONG_BELOW,
        SMA_SHORT, SMA_MEDIUM,
        GAP_SIZE_LARGE, GAP_SIZE_MEDIUM,
    )

logger = logging.getLogger(__name__)

# Global cache for feature-engineering thresholds from YAML (loaded once)
_fe_thresholds_cache: Optional[Dict] = None


def _get_fe_thresholds() -> Dict:
    """Load feature-engineering thresholds from YAML config (cached)."""
    global _fe_thresholds_cache
    if _fe_thresholds_cache is not None:
        return _fe_thresholds_cache

    try:
        from ..config.scoring_config import get_scoring_resolver
        _fe_thresholds_cache = get_scoring_resolver().get_feature_engineering_config()
    except Exception:
        _fe_thresholds_cache = {}

    return _fe_thresholds_cache


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
        # Read thresholds from YAML config with fallback to constants
        fe = _get_fe_thresholds()
        vwap_cfg = fe.get('vwap', {})
        vwap_period = vwap_cfg.get('period', VWAP_PERIOD)
        strong_above = vwap_cfg.get('strong_above', VWAP_STRONG_ABOVE)
        above = vwap_cfg.get('above', VWAP_ABOVE)
        below = vwap_cfg.get('below', VWAP_BELOW)
        strong_below = vwap_cfg.get('strong_below', VWAP_STRONG_BELOW)

        vwap_result = calculate_vwap(prices, volumes, period=vwap_period)

        if not vwap_result:
            return 0, 0, 0, "unknown", "Insufficient data for VWAP"

        vwap = vwap_result.vwap
        distance = vwap_result.distance_pct
        position = vwap_result.position

        # Scoring based on training results
        if distance > strong_above:
            score = 3.0
            reason = f"Strong momentum: {distance:.1f}% above VWAP (91.9% win rate)"
        elif distance > above:
            score = 2.0
            reason = f"Above VWAP: {distance:.1f}% (87.6% win rate)"
        elif distance > below:
            score = 1.0
            reason = f"Near VWAP: {distance:.1f}% (78.3% win rate)"
        elif distance > strong_below:
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
        # Read thresholds from YAML config with fallback to constants
        fe = _get_fe_thresholds()
        mc_cfg = fe.get('market_context', {})
        sma_short = mc_cfg.get('sma_short', SMA_SHORT)
        sma_medium = mc_cfg.get('sma_medium', SMA_MEDIUM)

        if not spy_prices or len(spy_prices) < sma_medium:
            return 0, "unknown", "No SPY data for market context"

        # Determine SPY trend
        current = spy_prices[-1]
        sma20 = float(np.mean(spy_prices[-sma_short:]))
        sma50 = float(np.mean(spy_prices[-sma_medium:]))

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

    def _score_sector(
        self, symbol: str, vix: float = None
    ) -> Tuple[float, str, str]:
        """
        VIX-dynamic Sector Score.

        Based on Feature Engineering Training (2026-01-31):
        - Consumer Staples: +9% win rate → +0.9 points
        - Utilities: +6.8% → +0.7 points
        - Financials: +6.4% → +0.6 points (but -6.5% at VIX>15!)
        - Technology: -10% → -1.0 points
        - Materials: -7.5% → -0.75 points

        VIX-Dynamic Adjustments:
        - Financial Services: -6.5% WR drop when VIX > 15
        - Defensive sectors improve when VIX rises
        - Tech/Growth sectors worsen when VIX rises

        Args:
            symbol: Stock ticker
            vix: Current VIX level for dynamic adjustment

        Returns:
            (score, sector_name, reason)
        """
        # Use VIX-aware function when VIX is available
        if vix is not None:
            adjustment, sector, reason = get_sector_adjustment_with_reason(symbol, vix)
        else:
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

    def _score_gap(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        context=None
    ) -> Tuple[float, str, float, bool, str]:
        """
        Gap Score (0-1 Punkt für Down-Gaps, -0.5 bis 0 für Up-Gaps).

        Based on Validation with 174k+ Gap Events (907 symbols, 5 years):
        - Down-gaps: +0.43% better 30d returns, +1.9pp higher win rate
        - Large down-gaps (>3%): +1.21% outperformance at 5d
        - 30-Day Win Rate: 56.7% (down) vs 54.8% (up)

        Returns:
            (score, gap_type, gap_size_pct, is_filled, reason)
        """
        # Read thresholds from YAML config with fallback to constants
        fe = _get_fe_thresholds()
        gap_cfg = fe.get('gap', {})
        gap_large = gap_cfg.get('size_large', GAP_SIZE_LARGE)
        gap_medium = gap_cfg.get('size_medium', GAP_SIZE_MEDIUM)

        # Use context if available (already calculated)
        if context and hasattr(context, 'gap_result') and context.gap_result:
            gap = context.gap_result
            gap_type = gap.gap_type
            gap_size = gap.gap_size_pct
            is_filled = gap.is_filled
            quality_score = gap.quality_score

            # Convert quality_score (-1 to +1) to display score
            # Down-gaps get positive points, up-gaps get negative/zero
            if gap_type in ('down', 'partial_down'):
                score = max(0, quality_score)  # 0 to 1
                if abs(gap_size) >= gap_large:
                    reason = f"Large down-gap: {gap_size:.1f}% - strong entry signal (+1.21% outperformance)"
                elif abs(gap_size) >= 1.0:
                    reason = f"Down-gap: {gap_size:.1f}% - favorable entry (+0.43% 30d return)"
                else:
                    reason = f"Small down-gap: {gap_size:.1f}% - mild positive signal"
            elif gap_type in ('up', 'partial_up'):
                score = min(0, quality_score)  # -0.5 to 0
                if abs(gap_size) >= gap_large:
                    reason = f"Large up-gap: {gap_size:+.1f}% - caution, potential overbought"
                elif abs(gap_size) >= gap_medium:
                    reason = f"Up-gap: {gap_size:+.1f}% - short-term momentum"
                else:
                    reason = f"Small up-gap: {gap_size:+.1f}% - neutral"
            else:
                score = 0.0
                reason = "No significant gap"

            return score, gap_type, gap_size, is_filled, reason

        # Calculate directly if context not available
        if len(prices) < 2:
            return 0.0, "none", 0.0, False, "Insufficient data for gap analysis"

        try:
            # Approximate opens from closes (previous close)
            opens = [prices[0]] + prices[:-1]

            gap_result = analyze_gap(
                opens=opens,
                highs=highs,
                lows=lows,
                closes=prices,
                lookback_days=SMA_SHORT,
                min_gap_pct=gap_medium / 2,  # looser threshold for feature scoring
            )

            if gap_result and gap_result.gap_type != 'none':
                return self._score_gap(prices, highs, lows, context=type('Context', (), {'gap_result': gap_result})())
            else:
                return 0.0, "none", 0.0, False, "No significant gap detected"

        except Exception:
            return 0.0, "none", 0.0, False, "Gap analysis error"

    def _apply_feature_scores(
        self,
        breakdown,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float] = None,
        lows: List[float] = None,
        context=None,
        vix: float = None
    ) -> None:
        """
        Apply all new feature scores to a breakdown object.

        Modifies breakdown in-place with VWAP, market context, sector, and gap scores.

        Args:
            breakdown: Score breakdown object to modify
            symbol: Stock ticker
            prices: Price history
            volumes: Volume history
            highs: High prices for gap analysis
            lows: Low prices for gap analysis
            context: Market context with spy_prices, etc.
            vix: Current VIX level for VIX-dynamic sector adjustment
        """
        # Get VIX from context if not provided directly
        if vix is None and context and hasattr(context, 'vix'):
            vix = context.vix

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

        # Sector Score (VIX-dynamic!)
        sector_result = self._score_sector(symbol, vix=vix)
        breakdown.sector_score = sector_result[0]
        breakdown.sector = sector_result[1]
        breakdown.sector_reason = sector_result[2]

        # Gap Score (for medium-term strategies like Bull-Put-Spreads)
        if highs is not None and lows is not None:
            gap_result = self._score_gap(prices, highs, lows, context)
            breakdown.gap_score = gap_result[0]
            breakdown.gap_type = gap_result[1]
            breakdown.gap_size_pct = gap_result[2]
            breakdown.gap_filled = gap_result[3]
            breakdown.gap_reason = gap_result[4]
        else:
            breakdown.gap_score = 0.0
            breakdown.gap_type = "none"
            breakdown.gap_size_pct = 0.0
            breakdown.gap_filled = False
            breakdown.gap_reason = "No high/low data for gap analysis"

