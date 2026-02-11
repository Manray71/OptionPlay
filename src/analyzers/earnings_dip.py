# OptionPlay - Earnings Dip Analyzer (Refactored v2)
# ===================================================
# Analyzes buying opportunities after earnings-related dips
#
# Strategy: Buy when quality stock is oversold after earnings overreaction
# - Requires confirmed stabilization (NOT day-0 signal)
# - Fundamental strength check (Stability Score, SMA 200)
# - Overreaction vs. justified drop distinction
# - Mean-reversion / contrarian approach
#
# 5-Component Scoring + Penalties (max ~9.5):
#   1. Drop Magnitude         (0 – 2.0)
#   2. Stabilization           (0 – 2.5)
#   3. Fundamental Strength    (0 – 2.0)
#   4. Overreaction Indicators (0 – 2.0)
#   5. BPS Suitability         (0 – 1.0)
#   6. Penalties               (-3.0 max)
#
# Minimum for signal: 3.5

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Import central constants
from ..constants import (
    RSI_PERIOD,
    SMA_LONG,
    VOLUME_AVG_PERIOD,
)
from ..models.base import SignalStrength, SignalType, TradeSignal
from ..models.strategy_breakdowns import EarningsDipScoreBreakdown
from .base import BaseAnalyzer
from .context import AnalysisContext

# Import Feature Scoring Mixin
from .feature_scoring_mixin import FeatureScoringMixin

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS for Earnings Dip Strategy v2
# =============================================================================

EDIP_MIN_DIP_PCT = 5.0  # Minimum drop to qualify
EDIP_MAX_DIP_PCT = 20.0  # Maximum drop (>20% = likely fundamental)
EDIP_EXTREME_DIP_PCT = 25.0  # Hard disqualify above this
EDIP_LOOKBACK_DAYS = 10  # Max days since earnings to scan
EDIP_MIN_STABILIZATION_DAYS = 1  # Must wait at least 1 day
EDIP_MIN_STABILITY_SCORE = 60.0  # Minimum stability for qualification
from ..constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS as _ENTRY_EARNINGS_MIN_DAYS
from ..constants.trading_rules import (
    ENTRY_VOLUME_MIN,
)

EDIP_MIN_AVG_VOLUME = ENTRY_VOLUME_MIN  # Minimum average volume (from trading_rules)
EDIP_NEXT_EARNINGS_MIN_DAYS = _ENTRY_EARNINGS_MIN_DAYS  # Min days to next earnings for BPS
EDIP_MIN_SCORE = 3.5  # Minimum total score for signal
EDIP_MAX_SCORE = 9.5  # Theoretical maximum

# Scoring: Drop Magnitude Tiers
EDIP_DROP_MINOR_PCT = 7.0
EDIP_DROP_MODERATE_PCT = 10.0
EDIP_DROP_MAJOR_PCT = 15.0
EDIP_DROP_SCORE_SMALL = 0.5
EDIP_DROP_SCORE_MODERATE = 1.0
EDIP_DROP_SCORE_GOOD = 1.5
EDIP_DROP_SCORE_IDEAL = 2.0
EDIP_DROP_SCORE_EXTREME = 1.0

# Scoring: Stabilization
EDIP_STAB_SCORE_GREEN_MULTI = 1.5
EDIP_STAB_SCORE_GREEN_SINGLE = 1.0
EDIP_STAB_SCORE_HIGHER_LOW = 1.0
EDIP_STAB_SCORE_VOL_DECLINE = 0.5
EDIP_STAB_SCORE_HAMMER = 0.5
EDIP_STAB_SCORE_MAX = 2.5

# Scoring: Fundamental Strength
EDIP_STABILITY_VERY_HIGH = 90
EDIP_STABILITY_HIGH = 80
EDIP_STABILITY_MODERATE = 70
EDIP_FUND_SCORE_VERY_HIGH = 1.5
EDIP_FUND_SCORE_HIGH = 1.0
EDIP_FUND_SCORE_MODERATE = 0.5
EDIP_FUND_SCORE_SMA200 = 0.5
EDIP_FUND_SCORE_MAX = 2.0

# Scoring: Overreaction Indicators
EDIP_RSI_EXTREME_OVERSOLD = 30
EDIP_RSI_MODERATE_OVERSOLD = 40
EDIP_OVERREACTION_COMPONENT = 0.5
EDIP_PANIC_VOLUME_MULTIPLIER = 3.0
EDIP_HISTORICAL_MOVE_MULTIPLIER = 2.0
EDIP_OVERREACTION_MAX = 2.0

# Scoring: BPS Suitability
EDIP_BPS_EARNINGS_SCORE = 0.5

# Penalties
EDIP_PENALTY_UNDER_SMA200 = 1.0
EDIP_PENALTY_CONTINUED_DECLINE = 1.5
EDIP_PENALTY_NEW_LOWS_MIN = 2
EDIP_PENALTY_RSI_NOT_EXTREME = 0.5
EDIP_PENALTY_MAX = 3.0

# Signal Strength
EDIP_SIGNAL_STRONG = 6.5
EDIP_SIGNAL_MODERATE = 5.0

# Stabilization Detection
EDIP_STAB_VOLUME_DECLINE_RATIO = 0.7
EDIP_HAMMER_LOWER_WICK_RATIO = 0.6
EDIP_HAMMER_BODY_RATIO = 0.3
EDIP_HAMMER_APPROX_RATIO = 0.7


@dataclass
class EarningsDipConfig:
    """Configuration for Earnings Dip Analyzer v2"""

    # Dip Detection
    min_dip_pct: float = EDIP_MIN_DIP_PCT
    max_dip_pct: float = EDIP_MAX_DIP_PCT
    extreme_dip_pct: float = EDIP_EXTREME_DIP_PCT
    dip_lookback_days: int = EDIP_LOOKBACK_DAYS

    # Stabilization
    min_stabilization_days: int = EDIP_MIN_STABILIZATION_DAYS

    # Fundamental Filters
    min_stability_score: float = EDIP_MIN_STABILITY_SCORE
    require_above_sma200: bool = True
    min_avg_volume: float = EDIP_MIN_AVG_VOLUME

    # BPS Suitability
    next_earnings_min_days: int = EDIP_NEXT_EARNINGS_MIN_DAYS

    # Risk Management
    stop_below_dip_low_pct: float = 3.0
    target_recovery_pct: float = 50.0

    # Scoring
    min_score_for_signal: float = EDIP_MIN_SCORE
    max_score: float = EDIP_MAX_SCORE

    # --- Legacy fields for backward compatibility ---
    max_score_legacy: int = 10
    min_score_for_signal_legacy: int = 6
    rsi_oversold_threshold: float = 35.0
    analyze_gap: bool = True
    min_gap_pct: float = 2.0
    gap_fill_threshold: float = 50.0
    require_stabilization: bool = True
    stabilization_days: int = 2
    min_market_cap: float = 10e9


class EarningsDipAnalyzer(BaseAnalyzer, FeatureScoringMixin):
    """
    Analyzes stocks for buying opportunities after earnings dips (v2).

    Implements a strict 4-step filter pipeline:
      1. Earnings event + drop detection (5-20%, within 1-10 days)
      2. Stabilization check (min 1 day: green day / higher low / vol decline / hammer)
      3. Fundamental check (Stability ≥ 60, above SMA 200 pre-earnings)
      4. Disqualification gates

    5-Component Scoring + Penalties (max ~9.5):
      - Drop Magnitude:           0 – 2.0
      - Stabilization:            0 – 2.5
      - Fundamental Strength:     0 – 2.0
      - Overreaction Indicators:  0 – 2.0
      - BPS Suitability:          0 – 1.0
      - Penalties:                -3.0 max

    Signal threshold: total_score >= 3.5

    Usage:
        analyzer = EarningsDipAnalyzer()
        signal = analyzer.analyze(
            "AAPL", prices, volumes, highs, lows,
            earnings_date=date(2025, 1, 20),
            pre_earnings_price=185.0,
            stability_score=85.0,
        )
    """

    def __init__(
        self,
        config: Optional[EarningsDipConfig] = None,
        scoring_config=None,  # Legacy — accepted but ignored
        **kwargs,
    ) -> None:
        self.config = config or EarningsDipConfig()
        # Legacy compat: store scoring_config reference
        self.scoring_config = scoring_config

    @property
    def strategy_name(self) -> str:
        return "earnings_dip"

    @property
    def description(self) -> str:
        return "Earnings Dip Buy - Buy after exaggerated earnings selloff in quality stocks"

    # =========================================================================
    # MAIN ANALYZE METHOD
    # =========================================================================

    def analyze(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        earnings_date: Optional[date] = None,
        pre_earnings_price: Optional[float] = None,
        stability_score: Optional[float] = None,
        next_earnings_days: Optional[int] = None,
        historical_avg_earnings_move: Optional[float] = None,
        context: Optional[AnalysisContext] = None,
        **kwargs,
    ) -> TradeSignal:
        """
        Analyzes a symbol for earnings dip buying opportunity.

        Pipeline:
          1. Detect earnings drop (5-20%)
          2. Check stabilization (min 1 day after drop)
          3. Fundamental check (SMA 200, stability)
          4. Score 5 components + penalties
          5. Build signal text

        Args:
            symbol: Ticker symbol
            prices: Closing prices (oldest first)
            volumes: Daily volume
            highs: Daily highs
            lows: Daily lows
            earnings_date: When earnings were reported
            pre_earnings_price: Price before earnings drop
            stability_score: Symbol's stability score (0-100)
            next_earnings_days: Days until next earnings
            historical_avg_earnings_move: Historical avg % move on earnings
            context: Optional AnalysisContext

        Returns:
            TradeSignal with earnings dip rating (score 0-10)
        """
        self.validate_inputs(prices, volumes, highs, lows, min_length=60)

        current_price = prices[-1]
        cfg = self.config

        # Initialize breakdown
        breakdown = EarningsDipScoreBreakdown()
        warnings = []

        # Also accept opens from kwargs for hammer detection
        opens = kwargs.get("opens", None)

        # =====================================================================
        # STEP 1: Earnings Drop Detection (PFLICHT)
        # =====================================================================
        drop_info = self._detect_earnings_drop(
            prices, highs, lows, earnings_date, pre_earnings_price
        )

        if not drop_info["detected"]:
            return self.create_neutral_signal(
                symbol, current_price, drop_info.get("reason", "No earnings dip detected")
            )

        dip_pct = drop_info["dip_pct"]
        dip_low = drop_info["dip_low"]
        drop_day_idx = drop_info["drop_day_idx"]
        pre_price = drop_info["pre_earnings_price"]

        breakdown.dip_pct = dip_pct
        breakdown.dip_low = dip_low
        breakdown.pre_earnings_price = pre_price

        # =====================================================================
        # STEP 2: Stabilization Check (PFLICHT)
        # =====================================================================
        stab_info = self._check_stabilization(prices, highs, lows, volumes, drop_day_idx, opens)

        if not stab_info["stabilized"]:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                stab_info.get("reason", "No stabilization — falling knife"),
                drop_info,
            )

        breakdown.stabilization_score = 0  # scored later
        breakdown.days_without_new_low = stab_info.get("days_since_drop", 0)

        # =====================================================================
        # STEP 3: Fundamental Check (PFLICHT)
        # =====================================================================
        fund_info = self._check_fundamentals(prices, volumes, stability_score)

        if not fund_info["qualified"]:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                fund_info.get("reason", "Fundamental check failed"),
                drop_info,
            )

        # =====================================================================
        # SCORING: 5 Components + Penalties
        # =====================================================================

        # 1. Drop Magnitude (0 – 2.0)
        drop_score = self._score_drop_magnitude(dip_pct)
        breakdown.dip_score = drop_score
        breakdown.dip_reason = f"-{dip_pct:.1f}% earnings drop"

        # 2. Stabilization (0 – 2.5)
        stab_score = self._score_stabilization(stab_info)
        breakdown.stabilization_score = stab_score
        breakdown.stabilization_reason = " + ".join(stab_info.get("details", ["stabilizing"]))

        # 3. Fundamental Strength (0 – 2.0)
        fund_score = self._score_fundamental_strength(stability_score, fund_info)
        breakdown.trend_score = fund_score  # Use trend_score for fundamental
        breakdown.was_in_uptrend = fund_info.get("was_above_sma200", False)
        breakdown.trend_status = "fundamental_check"
        breakdown.trend_reason = fund_info.get("reason", "")

        # 4. Overreaction Indicators (0 – 2.0)
        overreaction_info = self._score_overreaction(
            dip_pct, prices, volumes, drop_day_idx, historical_avg_earnings_move
        )
        overreaction_score = overreaction_info["score"]
        breakdown.rsi_score = overreaction_info.get("rsi_component", 0)
        breakdown.rsi_value = overreaction_info.get("rsi_value", 50.0)
        breakdown.rsi_reason = overreaction_info.get("rsi_reason", "")
        breakdown.volume_score = overreaction_info.get("volume_component", 0)
        breakdown.volume_ratio = overreaction_info.get("panic_vol_ratio", 0)
        breakdown.volume_reason = overreaction_info.get("volume_reason", "")

        # 5. BPS Suitability (0 – 1.0)
        bps_score = self._score_bps_suitability(next_earnings_days)
        breakdown.gap_score = bps_score  # Reuse gap_score for BPS
        breakdown.gap_reason = f"BPS suitability: {bps_score}"

        # 6. Penalties (-3.0 max)
        penalties_info = self._calculate_penalties(prices, lows, drop_day_idx, fund_info)
        penalties = penalties_info["total"]

        # Total score
        total_raw = (
            drop_score + stab_score + fund_score + overreaction_score + bps_score + penalties
        )
        total_score = max(0.0, min(EDIP_MAX_SCORE, total_raw))
        breakdown.total_score = round(total_score, 1)
        breakdown.max_possible = EDIP_MAX_SCORE

        # =====================================================================
        # BUILD SIGNAL
        # =====================================================================

        # Signal text
        signal_text = self._build_signal_text(
            dip_pct, earnings_date, stab_info, stability_score, overreaction_info, fund_info
        )

        # Signal strength
        if total_score >= EDIP_SIGNAL_STRONG:
            strength = SignalStrength.STRONG
        elif total_score >= EDIP_SIGNAL_MODERATE:
            strength = SignalStrength.MODERATE
        elif total_score >= EDIP_MIN_SCORE:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE

        # Entry/Stop/Target
        entry_price = current_price
        stop_loss = dip_low * (1 - cfg.stop_below_dip_low_pct / 100)
        target_price = current_price + (pre_price - current_price) * (cfg.target_recovery_pct / 100)

        # Warnings
        if dip_pct > 15:
            warnings.append(f"Large dip (-{dip_pct:.1f}%) — increased risk")
        if penalties < 0:
            warnings.append(f"Penalties applied ({penalties:.1f})")
        if overreaction_info.get("rsi_value", 50) > 40:
            warnings.append(f"RSI not extreme ({overreaction_info.get('rsi_value', 50):.0f})")

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.LONG if total_score >= EDIP_MIN_SCORE else SignalType.NEUTRAL,
            strength=strength,
            score=round(total_score, 1),
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=signal_text,
            details={
                "score_breakdown": breakdown.to_dict(),
                "raw_score": round(total_raw, 2),
                "max_possible": EDIP_MAX_SCORE,
                "dip_info": drop_info,
                "stabilization": stab_info,
                "fundamental": fund_info,
                "overreaction": overreaction_info,
                "penalties": penalties_info,
                "rsi": overreaction_info.get("rsi_value", 50.0),
            },
            warnings=warnings,
        )

    # =========================================================================
    # STEP 1: EARNINGS DROP DETECTION
    # =========================================================================

    def _detect_earnings_drop(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        earnings_date: Optional[date],
        pre_earnings_price: Optional[float],
    ) -> Dict[str, Any]:
        """
        Detects earnings-related price drop.

        Returns dict with:
            detected: bool
            dip_pct: float (positive value, e.g. 11.3 for -11.3%)
            dip_low: float
            drop_day_idx: int (index in arrays where drop occurred)
            pre_earnings_price: float
            reason: str (if not detected)
        """
        cfg = self.config
        lookback = cfg.dip_lookback_days

        info: Dict[str, Any] = {
            "detected": False,
            "earnings_date": earnings_date,
            "lookback_days": lookback,
        }

        # Determine pre-earnings price
        if pre_earnings_price:
            pre_price = pre_earnings_price
        else:
            if len(prices) >= lookback + 10:
                pre_price = max(prices[-(lookback + 10) : -lookback])
            else:
                pre_price = max(prices[:-lookback]) if len(prices) > lookback else prices[0]

        info["pre_earnings_price"] = pre_price

        current_price = prices[-1]
        info["current_price"] = current_price

        # Find the dip low in the lookback window
        recent_lows = lows[-lookback:]
        dip_low = min(recent_lows)
        drop_day_idx = len(lows) - lookback + recent_lows.index(dip_low)

        info["dip_low"] = dip_low
        info["drop_day_idx"] = drop_day_idx

        # Calculate dip % from pre-earnings price
        dip_pct = (1 - current_price / pre_price) * 100
        dip_to_low_pct = (1 - dip_low / pre_price) * 100

        info["dip_pct"] = dip_pct
        info["dip_to_low_pct"] = dip_to_low_pct

        # Check dip size
        if dip_pct < cfg.min_dip_pct:
            info["reason"] = f"Dip too small ({dip_pct:.1f}% < {cfg.min_dip_pct}%)"
            return info

        if dip_pct > cfg.extreme_dip_pct:
            info["reason"] = (
                f"Dip too extreme ({dip_pct:.1f}% > {cfg.extreme_dip_pct}%) — likely fundamental"
            )
            return info

        info["detected"] = True
        return info

    # =========================================================================
    # STEP 2: STABILIZATION CHECK
    # =========================================================================

    def _check_stabilization(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[int],
        drop_day_idx: int,
        opens: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Checks if the price has stabilized after the earnings drop.

        Stabilization requires at least ONE of:
        - Close > Open (green day after drop)
        - Higher Low (low > drop day low)
        - Volume declining (vol < 0.7x drop day vol)
        - Intraday recovery / Hammer candle

        Returns:
            stabilized: bool
            details: list[str]
            days_since_drop: int
            score: float (for later scoring step)
        """
        info: Dict[str, Any] = {
            "stabilized": False,
            "details": [],
            "days_since_drop": 0,
            "green_days": 0,
            "higher_low": False,
            "volume_declining": False,
            "hammer_detected": False,
        }

        n = len(prices)
        # Days after the drop
        days_after = n - 1 - drop_day_idx

        if days_after < self.config.min_stabilization_days:
            info["reason"] = (
                f"Too early — only {days_after} day(s) after drop, need {self.config.min_stabilization_days}"
            )
            return info

        info["days_since_drop"] = days_after

        drop_low = lows[drop_day_idx]
        drop_volume = volumes[drop_day_idx] if drop_day_idx < len(volumes) else 0

        # Check each stabilization criterion
        green_days = 0
        has_higher_low = False
        vol_declining = False
        has_hammer = False

        for i in range(drop_day_idx + 1, n):
            # Green day check
            if opens is not None and i < len(opens):
                if prices[i] > opens[i]:
                    green_days += 1
            else:
                # Without opens, approximate: close > previous close
                if i > 0 and prices[i] > prices[i - 1]:
                    green_days += 1

            # Higher low check
            if lows[i] > drop_low:
                has_higher_low = True

            # Volume declining check
            if drop_volume > 0 and volumes[i] < drop_volume * EDIP_STAB_VOLUME_DECLINE_RATIO:
                vol_declining = True

            # Hammer detection (intraday recovery)
            if opens is not None and i < len(opens):
                body = abs(prices[i] - opens[i])
                total_range = highs[i] - lows[i]
                lower_wick = min(prices[i], opens[i]) - lows[i]
                if (
                    total_range > 0
                    and lower_wick / total_range > EDIP_HAMMER_LOWER_WICK_RATIO
                    and body / total_range < EDIP_HAMMER_BODY_RATIO
                ):
                    has_hammer = True
            else:
                # Approximate hammer from close vs range
                total_range = highs[i] - lows[i]
                if total_range > 0:
                    close_from_low = prices[i] - lows[i]
                    if close_from_low / total_range > EDIP_HAMMER_APPROX_RATIO:
                        # Close near high with long lower wick
                        has_hammer = True

        info["green_days"] = green_days
        info["higher_low"] = has_higher_low
        info["volume_declining"] = vol_declining
        info["hammer_detected"] = has_hammer

        # Build details list
        if green_days >= 2:
            info["details"].append(f"{green_days} green days")
        elif green_days == 1:
            info["details"].append("1 green day")

        if has_higher_low:
            info["details"].append("higher low formed")

        if vol_declining:
            info["details"].append("vol declining")

        if has_hammer:
            info["details"].append("hammer candle")

        # Stabilization check: at least one criterion met
        info["stabilized"] = green_days >= 1 or has_higher_low or vol_declining or has_hammer

        if not info["stabilized"]:
            info["reason"] = "No stabilization — price continues falling"

        return info

    # =========================================================================
    # STEP 3: FUNDAMENTAL CHECK
    # =========================================================================

    def _check_fundamentals(
        self,
        prices: List[float],
        volumes: List[int],
        stability_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Checks fundamental quality.

        Requirements:
        - Stability Score >= 60 (if provided)
        - Price was above SMA 200 before the dip (pre-dip in uptrend)
        - Average volume >= 500,000

        Returns:
            qualified: bool
            reason: str
            was_above_sma200: bool
            sma200_rising: bool
            stability: float
        """
        cfg = self.config
        info: Dict[str, Any] = {
            "qualified": True,
            "reason": "",
            "was_above_sma200": False,
            "sma200_rising": False,
            "stability": stability_score or 0,
        }

        # Stability check
        if stability_score is not None and stability_score < cfg.min_stability_score:
            info["qualified"] = False
            info["reason"] = (
                f"Stability too low ({stability_score:.0f} < {cfg.min_stability_score})"
            )
            return info

        # SMA 200 check — was price above SMA 200 before the dip?
        if len(prices) >= SMA_LONG:
            sma_200 = sum(prices[-SMA_LONG:]) / SMA_LONG
            # Check pre-dip price (10 bars before end)
            pre_dip_price = prices[-min(10, len(prices))]
            info["sma_200"] = sma_200
            info["was_above_sma200"] = pre_dip_price > sma_200

            # SMA 200 rising?
            if len(prices) >= SMA_LONG + 20:
                sma_200_20d_ago = sum(prices[-(SMA_LONG + 20) : -20]) / SMA_LONG
                info["sma200_rising"] = sma_200 > sma_200_20d_ago

            if cfg.require_above_sma200 and not info["was_above_sma200"]:
                info["qualified"] = False
                info["reason"] = "Price was below SMA 200 before earnings — already in downtrend"
                return info
        else:
            # Not enough data for SMA 200 — skip this check
            info["was_above_sma200"] = True

        # Volume check
        if len(volumes) >= VOLUME_AVG_PERIOD:
            avg_vol = sum(volumes[-VOLUME_AVG_PERIOD:]) / VOLUME_AVG_PERIOD
            info["avg_volume"] = avg_vol
            if avg_vol < cfg.min_avg_volume:
                info["qualified"] = False
                info["reason"] = f"Avg volume too low ({avg_vol:,.0f} < {cfg.min_avg_volume:,.0f})"
                return info

        return info

    # =========================================================================
    # SCORING: 1. Drop Magnitude (0 – 2.0)
    # =========================================================================

    def _score_drop_magnitude(self, dip_pct: float) -> float:
        """
        Score the earnings drop magnitude.

        | Drop Size    | Score |
        |-------------|-------|
        | 5% to 7%   | 0.5   |
        | 7% to 10%  | 1.0   |
        | 10% to 15% | 1.5   |
        | 15% to 20% | 2.0   |
        | > 20%      | 1.0   | (reduced — might be fundamental)
        """
        if dip_pct < EDIP_MIN_DIP_PCT:
            return 0.0
        elif dip_pct < EDIP_DROP_MINOR_PCT:
            return EDIP_DROP_SCORE_SMALL
        elif dip_pct < EDIP_DROP_MODERATE_PCT:
            return EDIP_DROP_SCORE_MODERATE
        elif dip_pct < EDIP_DROP_MAJOR_PCT:
            return EDIP_DROP_SCORE_GOOD
        elif dip_pct <= EDIP_MAX_DIP_PCT:
            return EDIP_DROP_SCORE_IDEAL
        else:
            return EDIP_DROP_SCORE_EXTREME  # Reduced for extreme drops

    # =========================================================================
    # SCORING: 2. Stabilization (0 – 2.5)
    # =========================================================================

    def _score_stabilization(self, stab_info: Dict[str, Any]) -> float:
        """
        Score stabilization quality.

        | Criterion                    | Score |
        |------------------------------|-------|
        | 1 green day                  | 1.0   |
        | 2+ green days                | 1.5   |
        | Higher low formed            | 1.0   |
        | Volume declining (<0.7x)     | 0.5   |
        | Hammer candle after drop     | 0.5   |

        All applicable scores added, max 2.5.
        """
        score = 0.0

        green_days = stab_info.get("green_days", 0)
        if green_days >= 2:
            score += EDIP_STAB_SCORE_GREEN_MULTI
        elif green_days >= 1:
            score += EDIP_STAB_SCORE_GREEN_SINGLE

        if stab_info.get("higher_low", False):
            score += EDIP_STAB_SCORE_HIGHER_LOW

        if stab_info.get("volume_declining", False):
            score += EDIP_STAB_SCORE_VOL_DECLINE

        if stab_info.get("hammer_detected", False):
            score += EDIP_STAB_SCORE_HAMMER

        return min(EDIP_STAB_SCORE_MAX, score)

    # =========================================================================
    # SCORING: 3. Fundamental Strength (0 – 2.0)
    # =========================================================================

    def _score_fundamental_strength(
        self,
        stability_score: Optional[float],
        fund_info: Dict[str, Any],
    ) -> float:
        """
        Score fundamental quality.

        | Criterion                          | Score |
        |-------------------------------------|-------|
        | Stability 70-80                    | 0.5   |
        | Stability 80-90                    | 1.0   |
        | Stability > 90                     | 1.5   |
        | Above SMA 200 + SMA 200 rising     | 0.5   |
        """
        score = 0.0

        if stability_score is not None:
            if stability_score > EDIP_STABILITY_VERY_HIGH:
                score += EDIP_FUND_SCORE_VERY_HIGH
            elif stability_score > EDIP_STABILITY_HIGH:
                score += EDIP_FUND_SCORE_HIGH
            elif stability_score >= EDIP_STABILITY_MODERATE:
                score += EDIP_FUND_SCORE_MODERATE

        if fund_info.get("was_above_sma200", False) and fund_info.get("sma200_rising", False):
            score += EDIP_FUND_SCORE_SMA200

        return min(EDIP_FUND_SCORE_MAX, score)

    # =========================================================================
    # SCORING: 4. Overreaction Indicators (0 – 2.0)
    # =========================================================================

    def _score_overreaction(
        self,
        dip_pct: float,
        prices: List[float],
        volumes: List[int],
        drop_day_idx: int,
        historical_avg_earnings_move: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Score overreaction indicators.

        | Indicator                               | Score |
        |------------------------------------------|-------|
        | RSI after stabilization < 30             | 0.5   |
        | Drop day volume > 3x avg (panic)         | 0.5   |
        | Sector/index stable (not implemented)    | 0.5   |
        | Drop > 2x historical avg earnings move   | 0.5   |

        Returns dict with score and component details.
        """
        info: Dict[str, Any] = {
            "score": 0.0,
            "indicators": [],
            "rsi_component": 0.0,
            "volume_component": 0.0,
            "historical_component": 0.0,
        }

        total = 0.0

        # RSI check
        rsi = self._calculate_rsi(prices)
        info["rsi_value"] = rsi

        if rsi < EDIP_RSI_EXTREME_OVERSOLD:
            total += EDIP_OVERREACTION_COMPONENT
            info["rsi_component"] = EDIP_OVERREACTION_COMPONENT
            info["rsi_reason"] = f"RSI {rsi:.0f} strongly oversold"
            info["indicators"].append(f"RSI {rsi:.0f}")
        elif rsi < EDIP_RSI_MODERATE_OVERSOLD:
            info["rsi_reason"] = f"RSI {rsi:.0f} moderately oversold"
        else:
            info["rsi_reason"] = f"RSI {rsi:.0f} not oversold"

        # Panic volume check
        if len(volumes) >= VOLUME_AVG_PERIOD and drop_day_idx < len(volumes):
            # Calculate average volume excluding the drop day
            vol_window = volumes[max(0, drop_day_idx - VOLUME_AVG_PERIOD) : drop_day_idx]
            if vol_window:
                avg_vol = sum(vol_window) / len(vol_window)
                drop_vol = volumes[drop_day_idx]
                panic_ratio = drop_vol / avg_vol if avg_vol > 0 else 0

                info["panic_vol_ratio"] = panic_ratio
                info["avg_volume"] = avg_vol
                info["drop_volume"] = drop_vol

                if panic_ratio > EDIP_PANIC_VOLUME_MULTIPLIER:
                    total += EDIP_OVERREACTION_COMPONENT
                    info["volume_component"] = EDIP_OVERREACTION_COMPONENT
                    info["volume_reason"] = f"Panic volume {panic_ratio:.1f}x avg"
                    info["indicators"].append(f"Panic vol {panic_ratio:.1f}x")
                else:
                    info["volume_reason"] = f"Volume {panic_ratio:.1f}x avg (not panic level)"
            else:
                info["panic_vol_ratio"] = 0
                info["volume_reason"] = "Insufficient volume data"
        else:
            info["panic_vol_ratio"] = 0
            info["volume_reason"] = "Insufficient volume data"

        # Historical earnings move comparison
        if historical_avg_earnings_move is not None and historical_avg_earnings_move > 0:
            move_ratio = dip_pct / historical_avg_earnings_move
            info["historical_move_ratio"] = move_ratio

            if move_ratio > EDIP_HISTORICAL_MOVE_MULTIPLIER:
                total += EDIP_OVERREACTION_COMPONENT
                info["historical_component"] = EDIP_OVERREACTION_COMPONENT
                info["indicators"].append(f"Drop {move_ratio:.1f}x avg earnings move")

        info["score"] = min(EDIP_OVERREACTION_MAX, total)
        return info

    # =========================================================================
    # SCORING: 5. BPS Suitability (0 – 1.0)
    # =========================================================================

    def _score_bps_suitability(
        self,
        next_earnings_days: Optional[int] = None,
    ) -> float:
        """
        Score Bull-Put-Spread suitability.

        | Criterion                        | Score |
        |-----------------------------------|-------|
        | Next earnings > min_days away     | 0.5   |
        | IV rank after earnings > 30%     | 0.5   | (not checked — needs options data)
        """
        score = 0.0

        if next_earnings_days is not None:
            if next_earnings_days >= self.config.next_earnings_min_days:
                score += EDIP_BPS_EARNINGS_SCORE

        return score

    # =========================================================================
    # SCORING: 6. Penalties (-3.0 max)
    # =========================================================================

    def _calculate_penalties(
        self,
        prices: List[float],
        lows: List[float],
        drop_day_idx: int,
        fund_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Calculate penalty deductions.

        | Condition                                    | Penalty |
        |----------------------------------------------|---------|
        | Under SMA 200 before AND after earnings      | -1.0    |
        | Price falls further after initial drop       | -1.5    |
        | RSI > 40 after drop (not oversold enough)    | -0.5    |
        """
        info: Dict[str, Any] = {
            "total": 0.0,
            "details": [],
        }

        # Penalty: under SMA 200 before AND after
        current_price = prices[-1]
        if len(prices) >= SMA_LONG:
            sma_200 = sum(prices[-SMA_LONG:]) / SMA_LONG
            was_below = not fund_info.get("was_above_sma200", True)
            still_below = current_price < sma_200

            if was_below and still_below:
                info["total"] -= EDIP_PENALTY_UNDER_SMA200
                info["details"].append(
                    f"Under SMA 200 before and after (-{EDIP_PENALTY_UNDER_SMA200})"
                )

        # Penalty: continued decline after drop
        if drop_day_idx < len(lows) - 1:
            drop_low = lows[drop_day_idx]
            # Check if any day after drop made new low
            post_drop_lows = lows[drop_day_idx + 1 :]
            new_lows = sum(1 for l in post_drop_lows if l < drop_low)
            if new_lows >= EDIP_PENALTY_NEW_LOWS_MIN:
                info["total"] -= EDIP_PENALTY_CONTINUED_DECLINE
                info["details"].append(
                    f"Continued decline: {new_lows} new lows after drop (-{EDIP_PENALTY_CONTINUED_DECLINE})"
                )

        # Penalty: RSI not extreme
        rsi = self._calculate_rsi(prices)
        if rsi > EDIP_RSI_MODERATE_OVERSOLD:
            info["total"] -= EDIP_PENALTY_RSI_NOT_EXTREME
            info["details"].append(
                f"RSI {rsi:.0f} not extreme enough (-{EDIP_PENALTY_RSI_NOT_EXTREME})"
            )

        info["total"] = max(-EDIP_PENALTY_MAX, info["total"])
        return info

    # =========================================================================
    # SIGNAL TEXT BUILDER
    # =========================================================================

    def _build_signal_text(
        self,
        dip_pct: float,
        earnings_date: Optional[date],
        stab_info: Dict[str, Any],
        stability_score: Optional[float],
        overreaction_info: Dict[str, Any],
        fund_info: Dict[str, Any],
    ) -> str:
        """
        Build signal text.

        Format: "Earnings Dip: -X% on [date] | Stabilizing: [details] | [Fundamental] | [Overreaction]"
        """
        parts = []

        # Drop info
        if earnings_date:
            date_str = (
                earnings_date.strftime("%b %d")
                if hasattr(earnings_date, "strftime")
                else str(earnings_date)
            )
            parts.append(f"Earnings Dip: -{dip_pct:.1f}% on {date_str}")
        else:
            parts.append(f"Earnings Dip: -{dip_pct:.1f}%")

        # Stabilization details
        stab_details = stab_info.get("details", [])
        if stab_details:
            parts.append(f"Stabilizing: {', '.join(stab_details)}")
        else:
            days = stab_info.get("days_since_drop", 0)
            parts.append(f"Stabilizing: {days} days")

        # Stability score
        if stability_score is not None:
            parts.append(f"Stability {stability_score:.0f}")

        # Overreaction indicators
        indicators = overreaction_info.get("indicators", [])
        if indicators:
            parts.append(", ".join(indicators))
        elif fund_info.get("was_above_sma200", False):
            parts.append("Above SMA 200 pre-earnings")

        return " | ".join(parts)

    # =========================================================================
    # HELPER: RSI CALCULATION
    # =========================================================================

    def _calculate_rsi(self, prices: List[float], period: int = RSI_PERIOD) -> float:
        """
        Calculate RSI using Wilder's smoothing.

        Returns RSI value (0-100).
        """
        if len(prices) < period + 1:
            return 50.0  # Default neutral

        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # Initial averages (SMA)
        gains = [max(0, c) for c in changes[:period]]
        losses = [max(0, -c) for c in changes[:period]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        # Wilder's smoothing for remaining
        for i in range(period, len(changes)):
            change = changes[i]
            gain = max(0, change)
            loss = max(0, -change)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    # =========================================================================
    # HELPER: DISQUALIFIED SIGNAL
    # =========================================================================

    def _make_disqualified_signal(
        self,
        symbol: str,
        price: float,
        reason: str,
        drop_info: Dict[str, Any],
    ) -> TradeSignal:
        """Create a neutral/disqualified signal with context."""
        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.NEUTRAL,
            strength=SignalStrength.NONE,
            score=0.0,
            current_price=price,
            reason=reason,
            details={
                "disqualified": True,
                "dip_info": drop_info,
            },
            warnings=[],
        )


# Keep GapInfo for backward compatibility
@dataclass
class GapInfo:
    """Information about a gap down (legacy — kept for backward compat)"""

    detected: bool = False
    gap_day_index: int = -1
    gap_size_pct: float = 0.0
    gap_open: float = 0.0
    prev_close: float = 0.0
    gap_filled: bool = False
    fill_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected": self.detected,
            "gap_day_index": self.gap_day_index,
            "gap_size_pct": round(self.gap_size_pct, 2),
            "gap_open": round(self.gap_open, 2) if self.gap_open else 0,
            "prev_close": round(self.prev_close, 2) if self.prev_close else 0,
            "gap_filled": self.gap_filled,
            "fill_pct": round(self.fill_pct, 1),
        }
