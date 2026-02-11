"""
Options Liquidity Assessment for Bull-Put-Spreads.

Bewertet die Liquidität einzelner Strikes und kompletter Spreads
anhand von Open Interest, Bid-Ask Spread und Volume.

Quality Levels:
- excellent: OI>500, Spread<5%, Volume>200
- good:      OI>100, Spread<10%, Volume>50
- fair:      OI>50,  Spread<15%
- poor:      darunter → ausschließen
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..constants.trading_rules import (
    LIQUIDITY_MIN_QUALITY_DAILY_PICKS,
    LIQUIDITY_OI_EXCELLENT,
    LIQUIDITY_OI_FAIR,
    LIQUIDITY_OI_GOOD,
    LIQUIDITY_SPREAD_PCT_EXCELLENT,
    LIQUIDITY_SPREAD_PCT_FAIR,
    LIQUIDITY_SPREAD_PCT_GOOD,
    LIQUIDITY_VOLUME_EXCELLENT,
    LIQUIDITY_VOLUME_FAIR,
    LIQUIDITY_VOLUME_GOOD,
)

logger = logging.getLogger(__name__)

# Quality ordering for comparisons
_QUALITY_ORDER = {"excellent": 3, "good": 2, "fair": 1, "poor": 0}


@dataclass
class LiquidityInfo:
    """Liquidity assessment for a single option strike."""

    strike: float
    open_interest: int
    daily_volume: int
    bid: float
    ask: float
    mid: float
    spread_pct: float  # bid-ask spread as % of mid
    quality: str  # "excellent", "good", "fair", "poor"


@dataclass
class SpreadLiquidity:
    """Combined liquidity for both legs of a spread."""

    short_strike_liquidity: LiquidityInfo
    long_strike_liquidity: LiquidityInfo
    overall_quality: str  # worst of the two legs
    is_tradeable: bool  # overall_quality >= min quality for daily picks
    warnings: List[str] = field(default_factory=list)


class LiquidityAssessor:
    """Assesses options liquidity for Bull-Put-Spread strikes."""

    def assess_strike(self, option_data: Dict) -> LiquidityInfo:
        """
        Assess liquidity for a single option strike.

        Args:
            option_data: Dict with keys: strike, bid, ask, open_interest, volume

        Returns:
            LiquidityInfo with quality assessment
        """
        strike = option_data.get("strike", 0.0)
        bid = option_data.get("bid") or 0.0
        ask = option_data.get("ask") or 0.0
        oi = option_data.get("open_interest") or 0
        volume = option_data.get("volume") or 0

        mid = (bid + ask) / 2 if (bid + ask) > 0 else 0.0
        spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 999.0

        quality = self._determine_quality(oi, spread_pct, volume)

        return LiquidityInfo(
            strike=strike,
            open_interest=oi,
            daily_volume=volume,
            bid=bid,
            ask=ask,
            mid=mid,
            spread_pct=spread_pct,
            quality=quality,
        )

    def assess_spread(
        self,
        short_strike: float,
        long_strike: float,
        options_data: List[Dict],
    ) -> Optional[SpreadLiquidity]:
        """
        Assess combined liquidity for both legs of a spread.

        Args:
            short_strike: Short put strike price
            long_strike: Long put strike price
            options_data: List of option dicts from the chain

        Returns:
            SpreadLiquidity or None if strikes not found in chain
        """
        short_opt = self._find_option(short_strike, options_data)
        long_opt = self._find_option(long_strike, options_data)

        if short_opt is None or long_opt is None:
            return None

        short_liq = self.assess_strike(short_opt)
        long_liq = self.assess_strike(long_opt)

        # Overall quality is the worst of the two legs
        overall = self._min_quality(short_liq.quality, long_liq.quality)
        min_quality_rank = _QUALITY_ORDER.get(LIQUIDITY_MIN_QUALITY_DAILY_PICKS, 2)
        is_tradeable = _QUALITY_ORDER.get(overall, 0) >= min_quality_rank

        warnings = self._build_warnings(short_liq, long_liq)

        return SpreadLiquidity(
            short_strike_liquidity=short_liq,
            long_strike_liquidity=long_liq,
            overall_quality=overall,
            is_tradeable=is_tradeable,
            warnings=warnings,
        )

    def _determine_quality(self, oi: int, spread_pct: float, volume: int) -> str:
        """Determine liquidity quality level based on thresholds."""
        if (
            oi >= LIQUIDITY_OI_EXCELLENT
            and spread_pct <= LIQUIDITY_SPREAD_PCT_EXCELLENT
            and volume >= LIQUIDITY_VOLUME_EXCELLENT
        ):
            return "excellent"
        if (
            oi >= LIQUIDITY_OI_GOOD
            and spread_pct <= LIQUIDITY_SPREAD_PCT_GOOD
            and volume >= LIQUIDITY_VOLUME_GOOD
        ):
            return "good"
        if oi >= LIQUIDITY_OI_FAIR and spread_pct <= LIQUIDITY_SPREAD_PCT_FAIR:
            return "fair"
        return "poor"

    def _min_quality(self, q1: str, q2: str) -> str:
        """Return the worse of two quality levels."""
        if _QUALITY_ORDER.get(q1, 0) <= _QUALITY_ORDER.get(q2, 0):
            return q1
        return q2

    def _find_option(self, strike: float, options_data: List[Dict]) -> Optional[Dict]:
        """Find option dict matching the given strike price."""
        tolerance = 0.01
        for opt in options_data:
            if abs(opt.get("strike", 0) - strike) < tolerance:
                return opt
        return None

    def _build_warnings(self, short_liq: LiquidityInfo, long_liq: LiquidityInfo) -> List[str]:
        """Build warning messages for liquidity issues."""
        warnings = []
        for label, liq in [("Short", short_liq), ("Long", long_liq)]:
            if liq.open_interest < LIQUIDITY_OI_GOOD:
                warnings.append(
                    f"{label} strike ${liq.strike:.0f}: " f"Low OI ({liq.open_interest})"
                )
            if liq.spread_pct > LIQUIDITY_SPREAD_PCT_GOOD:
                warnings.append(
                    f"{label} strike ${liq.strike:.0f}: "
                    f"Wide bid-ask spread ({liq.spread_pct:.1f}%)"
                )
            if liq.daily_volume < LIQUIDITY_VOLUME_GOOD:
                warnings.append(
                    f"{label} strike ${liq.strike:.0f}: " f"Low volume ({liq.daily_volume})"
                )
        return warnings
