# OptionPlay - VIX Strategy Selector
# ====================================
# Automatic strategy selection based on VIX

import warnings
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
import logging

from ..constants import (
    VIX_LOW, VIX_NORMAL, VIX_ELEVATED, VIX_HIGH,
    DTE_MIN, DTE_MAX, DTE_TARGET,
    DELTA_TARGET, DELTA_MIN, DELTA_MAX, DELTA_CONSERVATIVE, DELTA_AGGRESSIVE,
    DELTA_LONG_TARGET,
    EARNINGS_MIN_DAYS, EARNINGS_MIN_DAYS_STRICT, EARNINGS_SAFE_DAYS,
    MIN_SCORE_DEFAULT,
)

logger = logging.getLogger(__name__)


# =============================================================================
# VIX TREND ANALYSIS
# =============================================================================

class VixTrend(Enum):
    """VIX trend direction based on 5-day Z-score."""
    RISING_FAST = "rising_fast"    # Z-Score > 1.5: Rising fast
    RISING = "rising"              # Z-Score > 0.75: Rising
    STABLE = "stable"              # Z-Score -0.75 to 0.75: Stable
    FALLING = "falling"            # Z-Score < -0.75: Falling
    FALLING_FAST = "falling_fast"  # Z-Score < -1.5: Falling fast


@dataclass
class VixTrendInfo:
    """VIX trend information."""
    trend: VixTrend
    z_score: float
    current_vix: float
    mean_5d: float
    std_5d: float
    history_available: bool = True

    @property
    def trend_description(self) -> str:
        """Human-readable trend description."""
        descriptions = {
            VixTrend.RISING_FAST: "⚠️ Rising fast",
            VixTrend.RISING: "↑ Rising",
            VixTrend.STABLE: "→ Stable",
            VixTrend.FALLING: "↓ Falling",
            VixTrend.FALLING_FAST: "✓ Falling fast",
        }
        return descriptions.get(self.trend, "Unknown")


class MarketRegime(Enum):
    """
    Market regime based on VIX level.

    5-tier system based on training analysis (2026-01-31):
    - LOW_VOL (<15):     78.9% Win Rate - Normal conditions
    - NORMAL (15-20):    84.0% Win Rate - Sweet Spot
    - DANGER_ZONE (20-25): 78.9% Win Rate - CAUTION! Be careful
    - ELEVATED (25-30):  88.6% Win Rate - Paradoxically good
    - HIGH_VOL (>30):    80.5% Win Rate - Crash mode
    """
    LOW_VOL = "low_vol"           # VIX < 15
    NORMAL = "normal"             # VIX 15-20 (Sweet Spot)
    DANGER_ZONE = "danger_zone"   # VIX 20-25 (CRITICAL!)
    ELEVATED = "elevated"         # VIX 25-30 (OK)
    HIGH_VOL = "high_vol"         # VIX > 30
    UNKNOWN = "unknown"           # No VIX data


@dataclass
class VIXThresholds:
    """
    VIX thresholds for 5-tier regime determination.

    Based on training analysis with 17k+ trades:
    - VIX 20-25: "Danger Zone" with worst performance
    - VIX 25-30: Paradoxically best performance (88.6% WR)

    Values from src/constants/thresholds.py
    """
    low_vol_max: float = VIX_LOW           # < 15 = LOW_VOL
    normal_max: float = VIX_NORMAL         # 15-20 = NORMAL (Sweet Spot)
    danger_zone_max: float = VIX_ELEVATED  # 20-25 = DANGER_ZONE (CRITICAL!)
    elevated_max: float = VIX_HIGH         # 25-30 = ELEVATED (OK)
    # Everything above elevated_max is HIGH_VOL


@dataclass
class StrategyRecommendation:
    """Strategy recommendation based on market conditions"""
    profile_name: str
    regime: MarketRegime
    vix_level: Optional[float]

    # Recommendations
    delta_target: float
    delta_min: float
    delta_max: float
    long_delta_target: float  # Long put delta target (PLAYBOOK §2: -0.05)
    spread_width: Optional[float]  # None = dynamic (delta-based)
    min_score: int
    earnings_buffer_days: int
    dte_min: int
    dte_max: int

    # Reasoning
    reasoning: str
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'profile': self.profile_name,
            'regime': self.regime.value,
            'vix': self.vix_level,
            'recommendations': {
                'delta_target': self.delta_target,
                'long_delta_target': self.long_delta_target,
                'delta_range': [self.delta_min, self.delta_max],
                'spread_width': self.spread_width if self.spread_width is not None else 'dynamic',
                'min_score': self.min_score,
                'earnings_buffer_days': self.earnings_buffer_days,
                'dte_range': [self.dte_min, self.dte_max]
            },
            'reasoning': self.reasoning,
            'warnings': self.warnings
        }


class VIXStrategySelector:
    """
    Automatically selects the optimal strategy profile based on VIX.

    5-tier system (based on training with 17k+ trades):
    - VIX < 15:  Conservative - Low premiums, focus on quality
    - VIX 15-20: Standard - Sweet Spot, best conditions
    - VIX 20-25: DANGER ZONE - Higher requirements, reduced size
    - VIX 25-30: Elevated - Paradoxically good, normal size
    - VIX > 30:  High Vol - Crash mode, very selective
    """

    # Profile definitions
    # BASE STRATEGY: Short Put with Delta -0.20, Long Put Delta -0.05, DTE 60-90 days
    # Spread width is DYNAMIC — derived from delta-selected strikes (not fixed)
    # Earnings buffer: at least 60 days
    PROFILES = {
        'conservative': {
            'delta_target': DELTA_TARGET,
            'delta_range': (DELTA_MAX, DELTA_MIN),  # PLAYBOOK ±0.03
            'min_score': 6,
            'earnings_buffer_days': EARNINGS_MIN_DAYS,
            'dte_min': DTE_MIN,
            'dte_max': DTE_MAX
        },
        'standard': {
            'delta_target': DELTA_TARGET,
            'delta_range': (DELTA_MAX, DELTA_MIN),
            'min_score': 5,
            'earnings_buffer_days': EARNINGS_MIN_DAYS,
            'dte_min': DTE_MIN,
            'dte_max': DTE_MAX
        },
        'danger_zone': {
            # VIX 20-25: "Danger Zone" with only 78.9% Win Rate
            # Stricter requirements, reduced position sizes
            'delta_target': DELTA_TARGET,
            'delta_range': (-0.22, -0.15),  # Narrower delta range (regime override)
            'min_score': 7,                  # Higher quality required!
            'earnings_buffer_days': EARNINGS_MIN_DAYS,
            'dte_min': DTE_MIN,
            'dte_max': DTE_MAX,
            'position_size_factor': 0.75     # 25% reduced size
        },
        'elevated': {
            # VIX 25-30: Paradoxically good (88.6% Win Rate)
            'delta_target': DELTA_TARGET,
            'delta_range': (DELTA_MAX, DELTA_MIN),
            'min_score': 5,
            'earnings_buffer_days': EARNINGS_MIN_DAYS,
            'dte_min': DTE_MIN,
            'dte_max': DTE_MAX
        },
        'high_volatility': {
            'delta_target': DELTA_TARGET,
            'delta_range': (DELTA_MAX, DELTA_MIN),
            'min_score': 6,
            'earnings_buffer_days': EARNINGS_MIN_DAYS,
            'dte_min': DTE_MIN,
            'dte_max': DTE_MAX,
            'position_size_factor': 0.50     # 50% reduced size
        }
    }

    # Trend thresholds for regime adjustment
    TREND_THRESHOLDS = {
        'rising_fast': 1.5,   # Z-Score > 1.5: Rising fast
        'rising': 0.75,       # Z-Score > 0.75: Rising
        'falling': -0.75,     # Z-Score < -0.75: Falling
        'falling_fast': -1.5, # Z-Score < -1.5: Falling fast
    }

    def __init__(self, thresholds: Optional[VIXThresholds] = None) -> None:
        self.thresholds = thresholds or VIXThresholds()
        self._vix_history_cache: Optional[List[float]] = None
        self._cache_timestamp: Optional[float] = None

    def _get_vix_history(self, days: int = 5) -> List[float]:
        """
        Loads VIX history from trades.db.

        Args:
            days: Number of days of history

        Returns:
            List of VIX values (oldest first)
        """
        import time

        # Cache for 5 minutes
        cache_ttl = 300
        now = time.time()

        if (self._vix_history_cache is not None and
            self._cache_timestamp is not None and
            now - self._cache_timestamp < cache_ttl):
            return self._vix_history_cache

        try:
            from ..cache.vix_cache import get_vix_manager
            manager = get_vix_manager()
            history = manager.get_vix_history(days=days)

            # Update cache
            self._vix_history_cache = history
            self._cache_timestamp = now

            return history

        except ImportError:
            logger.debug("VIX cache not available for trend analysis")
            return []
        except Exception as e:
            logger.debug(f"Error loading VIX history: {e}")
            return []

    def get_vix_trend(self, current_vix: Optional[float] = None) -> VixTrendInfo:
        """
        Calculates VIX trend based on 5-day history.

        Uses the last known VIX from DB if current_vix=None.
        The Z-score measures how far the current VIX deviates from the 5-day mean.

        Args:
            current_vix: Current VIX value (optional, uses DB value if None)

        Returns:
            VixTrendInfo with trend details
        """
        history = self._get_vix_history(days=5)

        if len(history) < 3:
            # Not enough history - no trend detectable
            fallback_vix = current_vix if current_vix is not None else 20.0
            return VixTrendInfo(
                trend=VixTrend.STABLE,
                z_score=0.0,
                current_vix=fallback_vix,
                mean_5d=fallback_vix,
                std_5d=0.0,
                history_available=False
            )

        import statistics

        # If no current_vix given, use last value from history
        if current_vix is None:
            current_vix = history[-1]

        # Mean and standard deviation of history
        mean_5d = statistics.mean(history)
        std_5d = statistics.stdev(history) if len(history) > 1 else 1.0

        # Minimum StdDev for Z-score calculation
        # VIX typically moves 1-3 points per day
        if std_5d < 0.5:
            std_5d = 0.5

        z_score = (current_vix - mean_5d) / std_5d

        # Determine trend
        if z_score > self.TREND_THRESHOLDS['rising_fast']:
            trend = VixTrend.RISING_FAST
        elif z_score > self.TREND_THRESHOLDS['rising']:
            trend = VixTrend.RISING
        elif z_score < self.TREND_THRESHOLDS['falling_fast']:
            trend = VixTrend.FALLING_FAST
        elif z_score < self.TREND_THRESHOLDS['falling']:
            trend = VixTrend.FALLING
        else:
            trend = VixTrend.STABLE

        return VixTrendInfo(
            trend=trend,
            z_score=round(z_score, 2),
            current_vix=current_vix,
            mean_5d=round(mean_5d, 2),
            std_5d=round(std_5d, 2),
            history_available=True
        )

    def get_regime(self, vix: Optional[float], use_trend: bool = True) -> MarketRegime:
        """
        Determines the market regime based on VIX (5-tier system).

        With use_trend=True, the regime is adjusted based on VIX trend:
        - Rising VIX -> Tighten regime (e.g., NORMAL -> DANGER_ZONE)
        - Falling VIX -> Relax regime (e.g., DANGER_ZONE -> NORMAL)

        IMPORTANT: Trend adjustment only makes sense for live VIX values!
        For historical/hypothetical values, use use_trend=False.

        Tiers based on training analysis:
        - < 15:   LOW_VOL (78.9% WR)
        - 15-20:  NORMAL - Sweet Spot (84.0% WR)
        - 20-25:  DANGER_ZONE - Critical! (78.9% WR)
        - 25-30:  ELEVATED - Paradoxically good (88.6% WR)
        - > 30:   HIGH_VOL - Crash (80.5% WR)

        Args:
            vix: VIX value (None if not available)
            use_trend: Consider trend (default: True)

        Returns:
            MarketRegime based on VIX level and trend
        """
        # Determine static regime first
        base_regime = self._get_static_regime(vix)

        if base_regime == MarketRegime.UNKNOWN:
            return base_regime

        if not use_trend:
            return base_regime

        # Trend adjustment only makes sense for live VIX
        # Compare if the given VIX is close to the last known VIX
        trend_info = self.get_vix_trend()  # Without argument = uses DB value

        if not trend_info.history_available:
            return base_regime

        # Only apply trend if the given VIX is "current"
        # (i.e., within 2 points of the last known VIX)
        if abs(vix - trend_info.current_vix) > 2.0:
            # VIX is not "current" - probably historical or hypothetical
            logger.debug(
                f"VIX {vix} differs from current {trend_info.current_vix}, "
                "skipping trend adjustment"
            )
            return base_regime

        # Regime adjustment based on trend
        return self._adjust_regime_for_trend(base_regime, trend_info)

    def _get_static_regime(self, vix: Optional[float]) -> MarketRegime:
        """
        Determines static regime without trend consideration.

        Args:
            vix: VIX value

        Returns:
            MarketRegime based only on VIX level
        """
        if vix is None:
            return MarketRegime.UNKNOWN

        # Validation: VIX cannot be negative
        if vix < 0:
            logger.warning(f"Invalid VIX value: {vix} (negative). Returning UNKNOWN.")
            return MarketRegime.UNKNOWN

        # Validation: Extremely high values could indicate data errors
        if vix > 100:
            logger.warning(
                f"Unusually high VIX value: {vix}. This may indicate a data error. "
                f"Treating as HIGH_VOL regime."
            )
            return MarketRegime.HIGH_VOL

        if vix < self.thresholds.low_vol_max:
            return MarketRegime.LOW_VOL
        elif vix < self.thresholds.normal_max:
            return MarketRegime.NORMAL
        elif vix < self.thresholds.danger_zone_max:
            return MarketRegime.DANGER_ZONE
        elif vix < self.thresholds.elevated_max:
            return MarketRegime.ELEVATED
        else:
            return MarketRegime.HIGH_VOL

    def _adjust_regime_for_trend(
        self,
        base_regime: MarketRegime,
        trend_info: VixTrendInfo
    ) -> MarketRegime:
        """
        Adjusts the regime based on VIX trend.

        Logic:
        - RISING_FAST: Tighten regime by 1 level
        - RISING: Tighten regime by 1 level (only at boundaries)
        - FALLING_FAST: Relax regime by 1 level
        - FALLING: Relax regime by 1 level (only at boundaries)

        Args:
            base_regime: Static regime
            trend_info: VIX trend information

        Returns:
            Adjusted MarketRegime
        """
        # Regime order (from relaxed to strict)
        regime_order = [
            MarketRegime.LOW_VOL,
            MarketRegime.NORMAL,
            MarketRegime.DANGER_ZONE,
            MarketRegime.ELEVATED,
            MarketRegime.HIGH_VOL,
        ]

        try:
            current_idx = regime_order.index(base_regime)
        except ValueError:
            return base_regime

        adjusted_idx = current_idx

        # Fast rising VIX: Tighten
        if trend_info.trend == VixTrend.RISING_FAST:
            adjusted_idx = min(current_idx + 1, len(regime_order) - 1)
            logger.debug(
                f"VIX rising fast (z={trend_info.z_score}): "
                f"{base_regime.value} -> {regime_order[adjusted_idx].value}"
            )

        # Rising VIX: Only tighten at boundaries
        elif trend_info.trend == VixTrend.RISING:
            # Only tighten if near threshold
            vix = trend_info.current_vix
            if self._is_near_threshold(vix, upper=True):
                adjusted_idx = min(current_idx + 1, len(regime_order) - 1)
                logger.debug(
                    f"VIX rising near threshold (z={trend_info.z_score}): "
                    f"{base_regime.value} -> {regime_order[adjusted_idx].value}"
                )

        # Fast falling VIX: Relax
        elif trend_info.trend == VixTrend.FALLING_FAST:
            adjusted_idx = max(current_idx - 1, 0)
            logger.debug(
                f"VIX falling fast (z={trend_info.z_score}): "
                f"{base_regime.value} -> {regime_order[adjusted_idx].value}"
            )

        # Falling VIX: Only relax at boundaries
        elif trend_info.trend == VixTrend.FALLING:
            vix = trend_info.current_vix
            if self._is_near_threshold(vix, upper=False):
                adjusted_idx = max(current_idx - 1, 0)
                logger.debug(
                    f"VIX falling near threshold (z={trend_info.z_score}): "
                    f"{base_regime.value} -> {regime_order[adjusted_idx].value}"
                )

        return regime_order[adjusted_idx]

    def _is_near_threshold(self, vix: float, upper: bool = True) -> bool:
        """
        Checks if VIX is near a threshold.

        Args:
            vix: VIX value
            upper: True for upper bound, False for lower

        Returns:
            True if within 1 point of the threshold
        """
        margin = 1.0  # 1 VIX point buffer

        thresholds = [
            self.thresholds.low_vol_max,
            self.thresholds.normal_max,
            self.thresholds.danger_zone_max,
            self.thresholds.elevated_max,
        ]

        for threshold in thresholds:
            if upper and threshold - margin <= vix < threshold:
                return True
            if not upper and threshold <= vix < threshold + margin:
                return True

        return False

    def get_regime_with_trend(self, vix: Optional[float]) -> Tuple[MarketRegime, Optional[VixTrendInfo]]:
        """
        Returns regime and trend info together.

        Args:
            vix: VIX value

        Returns:
            Tuple of (MarketRegime, VixTrendInfo or None)
        """
        if vix is None:
            return MarketRegime.UNKNOWN, None

        trend_info = self.get_vix_trend(vix)
        regime = self.get_regime(vix, use_trend=True)

        return regime, trend_info
    
    def select_profile(self, vix: Optional[float]) -> str:
        """Selects the optimal profile based on VIX (5-tier system)"""
        regime = self.get_regime(vix)

        profile_mapping = {
            MarketRegime.LOW_VOL: 'conservative',
            MarketRegime.NORMAL: 'standard',
            MarketRegime.DANGER_ZONE: 'danger_zone',   # VIX 20-25: CAUTION!
            MarketRegime.ELEVATED: 'elevated',          # VIX 25-30: OK
            MarketRegime.HIGH_VOL: 'high_volatility',
            MarketRegime.UNKNOWN: 'standard'            # Fallback
        }

        return profile_mapping[regime]
    
    def get_recommendation(self, vix: Optional[float]) -> StrategyRecommendation:
        """
        Returns complete strategy recommendation.

        Args:
            vix: Current VIX value (None if not available)

        Returns:
            StrategyRecommendation with all details
        """
        regime = self.get_regime(vix)
        profile_name = self.select_profile(vix)
        profile = self.PROFILES[profile_name]

        warnings = []

        # Reasoning based on regime (5-tier system)
        # Base strategy: Short Put Delta -0.20, DTE 60-90 days
        if regime == MarketRegime.LOW_VOL:
            reasoning = (
                f"VIX at {vix:.1f} shows low volatility. "
                "Short Put with Delta -0.20, DTE 60-90 days. "
                "Premiums are lower - focus on quality."
            )
            warnings.append("Low premiums - focus on quality over quantity")

        elif regime == MarketRegime.NORMAL:
            reasoning = (
                f"VIX at {vix:.1f} - Sweet Spot! Best conditions. "
                "Short Put with Delta -0.20, DTE 60-90 days. "
                "84% Win Rate in this range."
            )

        elif regime == MarketRegime.DANGER_ZONE:
            # VIX 20-25: Critical zone with only 78.9% Win Rate
            reasoning = (
                f"VIX at {vix:.1f} - DANGER ZONE! "
                "Only 78.9% Win Rate in this range. "
                "Higher quality (Score >= 7) and reduced size required."
            )
            warnings.append("DANGER ZONE (VIX 20-25): Win Rate only 78.9%")
            warnings.append("Only trade Score 7+ candidates")
            warnings.append("Reduce position sizes to 75%")
            warnings.append("Avoid Financial Services (6.5% WR Drop)")

        elif regime == MarketRegime.ELEVATED:
            # VIX 25-30: Paradoxically best performance (88.6% WR)
            reasoning = (
                f"VIX at {vix:.1f} - Elevated but OK! "
                "Paradoxically 88.6% Win Rate. "
                "Spread width dynamic (delta-based)."
            )
            warnings.append("VIX 25-30 has historically good performance")

        elif regime == MarketRegime.HIGH_VOL:
            reasoning = (
                f"VIX at {vix:.1f} shows extreme volatility (crash mode). "
                "Short Put with Delta -0.20, DTE 60-90 days. "
                "Spread width dynamic (delta-based)."
            )
            warnings.append("CRASH MODE: Reduce position sizes to 50%")
            warnings.append("Higher quality requirements (Score >= 6)")
            warnings.append("Daily portfolio monitoring required")

        else:  # UNKNOWN
            reasoning = (
                "No VIX data available. "
                "Using standard profile: Delta -0.20, DTE 60-90 days."
            )
            warnings.append("VIX not available - manual market check recommended")

        delta_range = profile.get('delta_range', (profile['delta_target'] - 0.05, profile['delta_target'] + 0.05))

        logger.info(
            f"VIX strategy: vix={vix if vix is not None else 'N/A'}, "
            f"regime={regime.value}, profile={profile_name}, "
            f"delta_target={profile['delta_target']}, long_delta={DELTA_LONG_TARGET}"
        )

        return StrategyRecommendation(
            profile_name=profile_name,
            regime=regime,
            vix_level=vix,
            delta_target=profile['delta_target'],
            delta_min=delta_range[0],
            delta_max=delta_range[1],
            long_delta_target=DELTA_LONG_TARGET,  # -0.05 (PLAYBOOK §2)
            spread_width=None,  # Dynamic: determined by delta-based strike selection
            min_score=profile['min_score'],
            earnings_buffer_days=profile['earnings_buffer_days'],
            dte_min=profile.get('dte_min', 60),
            dte_max=profile.get('dte_max', 90),
            reasoning=reasoning,
            warnings=warnings
        )
    
    def get_all_profiles(self) -> Dict[str, Dict]:
        """Returns all available profiles"""
        return self.PROFILES.copy()

    def get_regime_description(self, regime: MarketRegime) -> str:
        """Returns description for a regime (5-tier system)"""
        descriptions = {
            MarketRegime.LOW_VOL: "Low Volatility (VIX < 15) - 78.9% WR",
            MarketRegime.NORMAL: "Normal Volatility (VIX 15-20) - Sweet Spot 84.0% WR",
            MarketRegime.DANGER_ZONE: "DANGER ZONE (VIX 20-25) - Only 78.9% WR!",
            MarketRegime.ELEVATED: "Elevated Volatility (VIX 25-30) - 88.6% WR",
            MarketRegime.HIGH_VOL: "High Volatility (VIX > 30) - 80.5% WR",
            MarketRegime.UNKNOWN: "Unknown (no VIX data)"
        }
        return descriptions.get(regime, "Unknown")


# =============================================================================
# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_strategy_for_vix(vix: Optional[float]) -> StrategyRecommendation:
    """
    Convenience-Funktion für schnelle Strategie-Auswahl.

    Beispiel:
        >>> rec = get_strategy_for_vix(22.5)
        >>> print(rec.profile_name)  # 'aggressive'
        >>> print(rec.delta_target)  # -0.20
    """
    selector = VIXStrategySelector()
    return selector.get_recommendation(vix)


def get_strategy_for_stock(
    vix: Optional[float],
    stock_price: float
) -> StrategyRecommendation:
    """
    Strategy recommendation for a stock based on VIX regime.

    Spread width is no longer calculated here — it is determined
    dynamically by delta-based strike selection in StrikeRecommender.

    Args:
        vix: Current VIX value
        stock_price: Current stock price

    Returns:
        StrategyRecommendation (spread_width=None, delta-based)
    """
    selector = VIXStrategySelector()
    rec = selector.get_recommendation(vix)

    # Spread width is now dynamic (delta-based), not calculated from price
    return rec


def format_recommendation(rec: StrategyRecommendation) -> str:
    """Formats recommendation as readable string"""
    lines = [
        f"═══════════════════════════════════════════════════════════",
        f"  STRATEGY RECOMMENDATION (Short Put)",
        f"═══════════════════════════════════════════════════════════",
        f"  VIX:          {rec.vix_level:.1f}" if rec.vix_level else "  VIX:          n/a",
        f"  Regime:       {rec.regime.value}",
        f"  Profile:      {rec.profile_name.upper()}",
        f"───────────────────────────────────────────────────────────",
        f"  Delta Target: {rec.delta_target}",
        f"  Delta Range:  [{rec.delta_min}, {rec.delta_max}]",
        f"  DTE:          {rec.dte_min}-{rec.dte_max} days",
        f"  Spread Width: ${rec.spread_width:.2f}" if rec.spread_width is not None else "  Spread Width: Dynamic (delta-based)",
        f"  Min Score:    {rec.min_score}",
        f"  Earnings:     >{rec.earnings_buffer_days} days",
        f"───────────────────────────────────────────────────────────",
        f"  {rec.reasoning}",
    ]

    if rec.warnings:
        lines.append(f"───────────────────────────────────────────────────────────")
        for warning in rec.warnings:
            lines.append(f"  {warning}")

    lines.append(f"═══════════════════════════════════════════════════════════")

    return "\n".join(lines)
