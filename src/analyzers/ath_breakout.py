# OptionPlay - ATH Breakout Analyzer (Refactored v2)
# ===================================================
# Analyzes breakouts to new all-time highs with consolidation check
#
# Strategy: Buy when stock breaks out of consolidation to new ATH
# - Requires prior consolidation (base building)
# - Requires close confirmation (not just intraday wick)
# - Volume confirmation as gate
# - Momentum/trend context for bonus scoring
#
# 4-Component Scoring (max ~9.0):
#   1. Consolidation Quality  (0 – 2.5)
#   2. Breakout Strength      (0 – 2.0)
#   3. Volume Confirmation    (-1.0 – 2.5)
#   4. Momentum / Trend       (-1.0 – 1.5)
#
# Minimum for signal: 4.0

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..models.base import SignalStrength, SignalType, TradeSignal
from ..models.strategy_breakdowns import ATHBreakoutScoreBreakdown
from .base import BaseAnalyzer
from .context import AnalysisContext
from .score_normalization import clamp_score, normalize_score

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS for ATH Breakout Strategy v2  (loaded from config/analyzer_thresholds.yaml)
# =============================================================================
from ..config.analyzer_thresholds import get_analyzer_thresholds as _get_cfg

# Import central constants
from ..constants import (
    ATH_LOOKBACK_DAYS,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    RSI_PERIOD,
    SMA_LONG,
    SMA_MEDIUM,
    SMA_SHORT,
    SR_LOOKBACK_DAYS_EXTENDED,
    VOLUME_AVG_PERIOD,
)

# Import shared indicators
from ..indicators.momentum import calculate_macd

# Import S/R analysis
from ..indicators.support_resistance import get_nearest_sr_levels

# Import Feature Scoring Mixin
from .feature_scoring_mixin import FeatureScoringMixin

_cfg = _get_cfg()

ATH_CONSOL_LOOKBACK = _cfg.get("ath_breakout.general.consol_lookback", 60)
ATH_CONSOL_MIN_DAYS = _cfg.get("ath_breakout.general.consol_min_days", 20)
ATH_CONSOL_MAX_RANGE_PCT = _cfg.get("ath_breakout.general.consol_max_range_pct", 15.0)
ATH_CONSOL_ATH_TEST_PCT = _cfg.get("ath_breakout.general.consol_ath_test_pct", 1.0)
ATH_VOLUME_DISQUALIFY = _cfg.get("ath_breakout.general.volume_disqualify", 1.0)
ATH_RSI_DISQUALIFY = _cfg.get("ath_breakout.general.rsi_disqualify", 80.0)
ATH_MIN_SCORE = _cfg.get("ath_breakout.general.min_score", 4.0)
ATH_MAX_SCORE = _cfg.get("ath_breakout.general.max_score", 9.5)

# Consolidation Range Tiers
ATH_RANGE_TIGHT_PCT = _cfg.get("ath_breakout.consolidation.range_tight_pct", 8.0)
ATH_RANGE_MODERATE_PCT = _cfg.get("ath_breakout.consolidation.range_moderate_pct", 12.0)
ATH_RANGE_WIDE_PCT = _cfg.get("ath_breakout.consolidation.range_wide_pct", 15.0)
ATH_CONSOL_DURATION_MIN = _cfg.get("ath_breakout.consolidation.duration_min", 30)
ATH_CONSOL_DURATION_VERY_LONG = _cfg.get("ath_breakout.consolidation.duration_very_long", 60)
ATH_CONSOL_SCORE_TIGHT_LONG = _cfg.get("ath_breakout.consolidation.score_tight_long", 2.5)
ATH_CONSOL_SCORE_TIGHT_SHORT = _cfg.get("ath_breakout.consolidation.score_tight_short", 2.0)
ATH_CONSOL_SCORE_MOD_LONG = _cfg.get("ath_breakout.consolidation.score_mod_long", 2.0)
ATH_CONSOL_SCORE_MOD_SHORT = _cfg.get("ath_breakout.consolidation.score_mod_short", 1.5)
ATH_CONSOL_SCORE_WIDE = _cfg.get("ath_breakout.consolidation.score_wide", 1.0)
ATH_CONSOL_TEST_MIN = _cfg.get("ath_breakout.consolidation.test_min", 2)
ATH_CONSOL_TEST_BONUS = _cfg.get("ath_breakout.consolidation.test_bonus", 0.5)
ATH_CONSOL_SCORE_MAX = _cfg.get("ath_breakout.consolidation.score_max", 3.0)

# VCP Volatility Contraction (A1)
ATH_VCP_CONTRACTION_STRONG = _cfg.get("ath_breakout.vcp.contraction_strong", 2.0)
ATH_VCP_CONTRACTION_MODERATE = _cfg.get("ath_breakout.vcp.contraction_moderate", 1.5)
ATH_VCP_CONTRACTION_BONUS_STRONG = _cfg.get("ath_breakout.vcp.contraction_bonus_strong", 0.5)
ATH_VCP_CONTRACTION_BONUS_MODERATE = _cfg.get("ath_breakout.vcp.contraction_bonus_moderate", 0.25)
ATH_VCP_EXPANDING_PENALTY = _cfg.get("ath_breakout.vcp.expanding_penalty", -0.25)
ATH_CONSOL_WINDOW_STEP = _cfg.get("ath_breakout.consolidation.window_step", 5)

# Breakout Strength Tiers
ATH_BREAKOUT_WEAK_PCT = _cfg.get("ath_breakout.breakout.weak_pct", 1.0)
ATH_BREAKOUT_MODERATE_PCT = _cfg.get("ath_breakout.breakout.moderate_pct", 3.0)
ATH_BREAKOUT_STRONG_PCT = _cfg.get("ath_breakout.breakout.strong_pct", 5.0)
ATH_BREAKOUT_SCORE_WEAK = _cfg.get("ath_breakout.breakout.score_weak", 1.0)
ATH_BREAKOUT_SCORE_MODERATE = _cfg.get("ath_breakout.breakout.score_moderate", 1.5)
ATH_BREAKOUT_SCORE_STRONG = _cfg.get("ath_breakout.breakout.score_strong", 2.0)
ATH_BREAKOUT_SCORE_OVEREXTENDED = _cfg.get("ath_breakout.breakout.score_overextended", 1.5)
ATH_BREAKOUT_DAYS_BONUS_MIN = _cfg.get("ath_breakout.breakout.days_bonus_min", 2)
ATH_BREAKOUT_CONFIRMATION_BONUS = _cfg.get("ath_breakout.breakout.confirmation_bonus", 0.5)
ATH_BREAKOUT_SCORE_MAX = _cfg.get("ath_breakout.breakout.score_max", 2.5)

# Candle Analysis
ATH_CANDLE_MARUBOZU_WICK_MAX = _cfg.get("ath_breakout.candle_analysis.marubozu_wick_max_pct", 5.0)
ATH_CANDLE_WIDE_RANGE_ATR_MULT = _cfg.get("ath_breakout.candle_analysis.wide_range_atr_mult", 1.5)
ATH_CANDLE_CLOSE_HIGH_THRESHOLD = _cfg.get(
    "ath_breakout.candle_analysis.close_near_high_threshold", 0.8
)
ATH_CANDLE_LONG_WICK_THRESHOLD = _cfg.get("ath_breakout.candle_analysis.long_wick_threshold", 0.5)
ATH_CANDLE_MARUBOZU_BONUS = _cfg.get("ath_breakout.candle_analysis.marubozu_bonus", 0.5)
ATH_CANDLE_WIDE_RANGE_BONUS = _cfg.get("ath_breakout.candle_analysis.wide_range_bonus", 0.25)
ATH_CANDLE_CLOSE_HIGH_BONUS = _cfg.get("ath_breakout.candle_analysis.close_high_bonus", 0.25)
ATH_CANDLE_LONG_WICK_PENALTY = _cfg.get("ath_breakout.candle_analysis.long_wick_penalty", -0.5)

# Consolidation Volume Profile (A2)
ATH_CONSOL_VOL_DRYUP_STRONG = _cfg.get("ath_breakout.consol_volume.dryup_strong", 1.5)
ATH_CONSOL_VOL_DRYUP_MODERATE = _cfg.get("ath_breakout.consol_volume.dryup_moderate", 1.2)
ATH_CONSOL_VOL_DISTRIBUTION = _cfg.get("ath_breakout.consol_volume.distribution_threshold", 0.8)
ATH_CONSOL_VOL_DRYUP_STRONG_BONUS = _cfg.get("ath_breakout.consol_volume.dryup_strong_bonus", 0.5)
ATH_CONSOL_VOL_DRYUP_MOD_BONUS = _cfg.get("ath_breakout.consol_volume.dryup_moderate_bonus", 0.25)
ATH_CONSOL_VOL_DISTRIBUTION_PENALTY = _cfg.get(
    "ath_breakout.consol_volume.distribution_penalty", -0.25
)

# Relative Strength vs SPY (A3)
ATH_RS_LOOKBACK = _cfg.get("ath_breakout.relative_strength.lookback_days", 60)
ATH_RS_STRONG = _cfg.get("ath_breakout.relative_strength.strong_outperformance", 20.0)
ATH_RS_MODERATE = _cfg.get("ath_breakout.relative_strength.moderate_outperformance", 10.0)
ATH_RS_UNDERPERFORMANCE = _cfg.get("ath_breakout.relative_strength.underperformance", -10.0)
ATH_RS_STRONG_BONUS = _cfg.get("ath_breakout.relative_strength.strong_bonus", 0.5)
ATH_RS_MODERATE_BONUS = _cfg.get("ath_breakout.relative_strength.moderate_bonus", 0.25)
ATH_RS_UNDERPERFORMANCE_PENALTY = _cfg.get(
    "ath_breakout.relative_strength.underperformance_penalty", -0.5
)

# Gap Analysis (A5)
ATH_GAP_POWER_PCT = _cfg.get("ath_breakout.gap_analysis.power_threshold_pct", 3.0)
ATH_GAP_STANDARD_PCT = _cfg.get("ath_breakout.gap_analysis.standard_threshold_pct", 1.0)
ATH_GAP_POWER_BONUS = _cfg.get("ath_breakout.gap_analysis.power_bonus", 0.5)
ATH_GAP_STANDARD_BONUS = _cfg.get("ath_breakout.gap_analysis.standard_bonus", 0.25)
ATH_GAP_REVERSAL_BONUS = _cfg.get("ath_breakout.gap_analysis.reversal_bonus", 0.25)

# Volume Score Tiers
ATH_VOLUME_EXCEPTIONAL = _cfg.get("ath_breakout.volume.exceptional_ratio", 2.5)
ATH_VOLUME_STRONG = _cfg.get("ath_breakout.volume.strong_ratio", 2.0)
ATH_VOLUME_GOOD = _cfg.get("ath_breakout.volume.good_ratio", 1.5)
ATH_VOLUME_ADEQUATE = _cfg.get("ath_breakout.volume.adequate_ratio", 1.0)
ATH_VOLUME_SCORE_EXCEPTIONAL = _cfg.get("ath_breakout.volume.score_exceptional", 2.5)
ATH_VOLUME_SCORE_STRONG = _cfg.get("ath_breakout.volume.score_strong", 2.0)
ATH_VOLUME_SCORE_GOOD = _cfg.get("ath_breakout.volume.score_good", 1.5)
ATH_VOLUME_SCORE_ADEQUATE = _cfg.get("ath_breakout.volume.score_adequate", 0.5)
ATH_VOLUME_SCORE_WEAK = _cfg.get("ath_breakout.volume.score_weak", -1.0)

# Momentum/Trend Scoring
ATH_MOMENTUM_SMA_PERFECT_BONUS = _cfg.get("ath_breakout.momentum.sma_perfect_bonus", 0.5)
ATH_MOMENTUM_SMA_GOOD_BONUS = _cfg.get("ath_breakout.momentum.sma_good_bonus", 0.25)
ATH_MOMENTUM_SMA200_DECLINE = _cfg.get("ath_breakout.momentum.sma200_decline_mult", 0.999)
ATH_MOMENTUM_SMA200_DECLINE_PENALTY = _cfg.get("ath_breakout.momentum.sma200_decline_penalty", 0.5)
ATH_MOMENTUM_SMA200_LOOKBACK = _cfg.get("ath_breakout.momentum.sma200_lookback", 20)
ATH_MOMENTUM_MACD_BONUS = _cfg.get("ath_breakout.momentum.macd_bonus", 0.5)
ATH_RSI_HEALTHY_LOW = _cfg.get("ath_breakout.momentum.rsi_healthy_low", 50)
ATH_RSI_HEALTHY_HIGH = _cfg.get("ath_breakout.momentum.rsi_healthy_high", 70)
ATH_RSI_HEALTHY_BONUS = _cfg.get("ath_breakout.momentum.rsi_healthy_bonus", 0.5)
ATH_RSI_OVERBOUGHT = _cfg.get("ath_breakout.momentum.rsi_overbought", 75)
ATH_RSI_OVERBOUGHT_PENALTY = _cfg.get("ath_breakout.momentum.rsi_overbought_penalty", 0.5)
ATH_MOMENTUM_SCORE_MIN = _cfg.get("ath_breakout.momentum.score_min", -1.5)
ATH_MOMENTUM_SCORE_MAX = _cfg.get("ath_breakout.momentum.score_max", 2.0)

# Signal Strength
ATH_SIGNAL_STRONG = _cfg.get("ath_breakout.signal.strong", 7.0)
ATH_SIGNAL_MODERATE = _cfg.get("ath_breakout.signal.moderate", 5.5)

# Stop Loss
ATH_STOP_RECENT_LOW_DAYS = _cfg.get("ath_breakout.stop_loss.recent_low_days", 10)
ATH_STOP_MAX_PCT = _cfg.get("ath_breakout.stop_loss.max_pct", 0.95)


@dataclass
class ATHBreakoutConfig:
    """Configuration for ATH Breakout Analyzer v2"""

    # ATH Detection
    ath_lookback_days: int = ATH_LOOKBACK_DAYS  # 252 days (1 year)

    # Consolidation
    consolidation_lookback: int = ATH_CONSOL_LOOKBACK
    consolidation_min_days: int = ATH_CONSOL_MIN_DAYS
    consolidation_max_range_pct: float = ATH_CONSOL_MAX_RANGE_PCT
    ath_test_tolerance_pct: float = ATH_CONSOL_ATH_TEST_PCT

    # Volume
    volume_avg_period: int = VOLUME_AVG_PERIOD
    volume_disqualify_threshold: float = ATH_VOLUME_DISQUALIFY

    # RSI
    rsi_period: int = RSI_PERIOD
    rsi_disqualify: float = ATH_RSI_DISQUALIFY

    # Risk Management
    stop_below_recent_low_pct: float = 1.0
    target_risk_reward: float = 2.0

    # Scoring
    min_score_for_signal: float = ATH_MIN_SCORE
    max_score: float = ATH_MAX_SCORE

    # Legacy compat fields (ignored by v2, but accepted for backward compat)
    consolidation_days: int = 20
    breakout_threshold_pct: float = 1.0
    confirmation_days: int = 2
    confirmation_threshold_pct: float = 0.5
    volume_spike_multiplier: float = 1.5
    rsi_max: float = 80.0
    min_uptrend_days: int = 50
    max_score_legacy: int = 10
    min_score_for_signal_legacy: int = 6


class ATHBreakoutAnalyzer(BaseAnalyzer, FeatureScoringMixin):
    """
    Analyzes stocks for ATH breakouts (v2 — Refactored).

    Implements a strict 4-step filter pipeline:
      1. ATH identification + Consolidation check (base required)
      2. Close confirmation (close > previous ATH, not just intraday)
      3. Volume confirmation (vol >= 1.0x avg, < 1.0x = disqualify)
      4. RSI check (> 80 = disqualify)

    4-Component Scoring (max ~9.0):
      - Consolidation Quality:  0 – 2.5
      - Breakout Strength:      0 – 2.0
      - Volume Confirmation:   -1.0 – 2.5
      - Momentum / Trend:      -1.0 – 1.5

    Signal threshold: total_score >= 4.0

    Usage:
        analyzer = ATHBreakoutAnalyzer()
        signal = analyzer.analyze("AAPL", prices, volumes, highs, lows)
        if signal.signal_type == SignalType.LONG:
            print(f"ATH Breakout: {signal.score}/10")
    """

    def __init__(
        self,
        config: Optional[ATHBreakoutConfig] = None,
        scoring_config=None,  # Accepted for backward compat, ignored
        **kwargs,
    ) -> None:
        self.config = config or ATHBreakoutConfig()
        # Accept scoring_config for backward compat but ignore it
        self.scoring_config = scoring_config

    @property
    def strategy_name(self) -> str:
        return "ath_breakout"

    @property
    def description(self) -> str:
        return "ATH Breakout - Buy on confirmed breakout from consolidation to new all-time high"

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
        spy_prices: Optional[List[float]] = None,
        context: Optional[AnalysisContext] = None,
        **kwargs,
    ) -> TradeSignal:
        """
        Analyzes a symbol for ATH breakout.

        Pipeline:
          1. Identify ATH and detect prior consolidation
          2. Check close confirmation (close > previous ATH)
          3. Check volume (< 1.0x avg = disqualify)
          4. Check RSI (> 80 = disqualify)
          5. Score all 4 components
          6. Build signal text

        Args:
            symbol: Ticker symbol
            prices: Closing prices (oldest first)
            volumes: Daily volume
            highs: Daily highs
            lows: Daily lows
            spy_prices: Optional SPY prices for relative strength (A3)
            context: Optional pre-calculated AnalysisContext

        Returns:
            TradeSignal with breakout rating (score 0-10)
        """
        min_data = max(self.config.ath_lookback_days, 60)
        self.validate_inputs(prices, volumes, highs, lows, min_length=min_data)

        current_price = prices[-1]
        current_high = highs[-1]

        # Initialize score breakdown
        breakdown = ATHBreakoutScoreBreakdown()
        warnings = []

        # =====================================================================
        # STEP 1: ATH Identification + Consolidation Check (PFLICHT)
        # =====================================================================
        ath_info = self._identify_ath(highs, prices)

        if not ath_info["has_ath"]:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"No ATH breakout: price is {ath_info.get('pct_below_ath', 0):.1f}% below {ath_info['lookback']}-day high",
            )

        previous_ath = ath_info["previous_ath"]

        # Check consolidation
        consol_info = self._detect_consolidation(highs, lows, prices, previous_ath)

        if not consol_info["has_consolidation"]:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                consol_info.get("disqualify_reason", "No consolidation before breakout"),
            )

        breakdown.ath_old = previous_ath
        breakdown.ath_current = current_high
        breakdown.ath_had_consolidation = True

        # =====================================================================
        # STEP 2: Close Confirmation (PFLICHT)
        # =====================================================================
        close_info = self._check_close_confirmation(prices, previous_ath)

        if not close_info["confirmed"]:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Breakout not confirmed: close ${current_price:.2f} is below ATH ${previous_ath:.2f} (intraday fakeout)",
            )

        breakdown.ath_pct_above = close_info["pct_above"]

        # =====================================================================
        # STEP 3: Volume Confirmation (PFLICHT — < 1.0x = disqualify)
        # =====================================================================
        volume_info = self._check_volume(volumes)

        if volume_info["ratio"] < self.config.volume_disqualify_threshold:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"Weak volume: {volume_info['ratio']:.2f}x avg (< {self.config.volume_disqualify_threshold}x) — likely false breakout",
            )

        # =====================================================================
        # STEP 4: RSI Check (> 80 = disqualify)
        # =====================================================================
        rsi_value = self._calculate_rsi(prices)

        if rsi_value > self.config.rsi_disqualify:
            return self._make_disqualified_signal(
                symbol,
                current_price,
                f"RSI overbought at {rsi_value:.0f} (> {self.config.rsi_disqualify:.0f}) — reversal likely",
            )

        # =====================================================================
        # SCORING: 4 Components
        # =====================================================================

        # 1. Consolidation Quality (0 – 3.0) — includes VCP contraction (A1)
        consol_score = self._score_consolidation_quality(consol_info, highs, lows)
        breakdown.ath_score = consol_score
        breakdown.ath_reason = (
            f"Base {consol_info['duration']} days, "
            f"{consol_info['range_pct']:.1f}% range"
            + (f", {consol_info['ath_tests']}x tested" if consol_info["ath_tests"] >= 2 else "")
        )

        # 2. Breakout Strength (0 – 2.5) — includes candle quality (A4) and gap (A5)
        opens = getattr(context, "_opens", None) if context else None
        breakout_score = self._score_breakout_strength(close_info, prices, highs, lows, opens=opens)

        # 3. Volume Confirmation (-1.0 – 3.0) — includes consol volume profile (A2)
        volume_score = self._score_volume(volume_info["ratio"])
        consol_vol_score = self._score_consol_volume_profile(volumes, consol_info)
        volume_score = volume_score + consol_vol_score
        breakdown.volume_score = volume_score
        breakdown.volume_ratio = volume_info["ratio"]
        breakdown.volume_reason = volume_info.get("reason", "")

        # 4. Momentum / Trend Context (-1.5 – 2.0) — includes RS vs SPY (A3)
        momentum_info = self._score_momentum_trend(prices, rsi_value, spy_prices=spy_prices)
        momentum_score = momentum_info["score"]
        breakdown.trend_score = momentum_score
        breakdown.trend_status = momentum_info.get("status", "")
        breakdown.trend_reason = momentum_info.get("reason", "")
        breakdown.rsi_value = rsi_value
        breakdown.rsi_reason = f"RSI={rsi_value:.1f}"

        # Total score
        total_score = consol_score + breakout_score + volume_score + momentum_score
        total_score = clamp_score(total_score, 10.0)
        breakdown.total_score = round(total_score, 1)
        breakdown.max_possible = 10.0

        # =====================================================================
        # BUILD SIGNAL
        # =====================================================================
        signal_text = self._build_signal_text(
            current_price,
            previous_ath,
            close_info,
            consol_info,
            volume_info,
            momentum_info,
            rsi_value,
        )

        # Signal strength (compared on native scale before normalization)
        if total_score >= ATH_SIGNAL_STRONG:
            strength = SignalStrength.STRONG
        elif total_score >= ATH_SIGNAL_MODERATE:
            strength = SignalStrength.MODERATE
        elif total_score >= ATH_MIN_SCORE:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE

        is_actionable = total_score >= ATH_MIN_SCORE

        # Normalize to 0-10 scale for fair cross-strategy comparison
        normalized_score = normalize_score(total_score, "ath_breakout")

        # Entry/Stop/Target
        entry_price = current_price
        stop_loss = self._calculate_stop_loss(lows, current_price)
        target_price = self._calculate_target(current_price, stop_loss)

        # Extended S/R for context
        sr_levels = get_nearest_sr_levels(
            current_price=current_price,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            lookback=SR_LOOKBACK_DAYS_EXTENDED,
            num_levels=3,
        )

        # Warnings
        if rsi_value > ATH_RSI_OVERBOUGHT:
            warnings.append(f"RSI elevated at {rsi_value:.0f} — near overbought")
        if volume_info["ratio"] < ATH_VOLUME_GOOD:
            warnings.append(
                f"Volume only {volume_info['ratio']:.1f}x avg — elevated false breakout risk"
            )
        if momentum_score < 0:
            warnings.append("Weak momentum context")

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.LONG if is_actionable else SignalType.NEUTRAL,
            strength=strength,
            score=round(normalized_score, 1),
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=signal_text,
            details={
                "score_breakdown": breakdown.to_dict(),
                "raw_score": total_score,
                "max_possible": 10.0,
                "ath_info": {
                    "previous_ath": previous_ath,
                    "pct_above": close_info["pct_above"],
                    "days_above": close_info["days_above"],
                    "lookback": ath_info["lookback"],
                },
                "consolidation_info": consol_info,
                "volume_info": volume_info,
                "momentum_info": momentum_info,
                "rsi": rsi_value,
                "sr_levels": sr_levels,
                "components": {
                    "consolidation_quality": consol_score,
                    "breakout_strength": breakout_score,
                    "volume": volume_score,
                    "momentum_trend": momentum_score,
                },
            },
            warnings=warnings,
        )

    # =========================================================================
    # STEP 1: ATH IDENTIFICATION
    # =========================================================================

    def _identify_ath(
        self,
        highs: List[float],
        prices: List[float],
    ) -> Dict[str, Any]:
        """
        Identify the previous ATH (252-day high) and check if current price
        is at or above it.

        Returns:
            has_ath: bool — True if current high >= previous ATH
            previous_ath: float — the old ATH value
            pct_below_ath: float — how far below ATH (if not breaking out)
            lookback: int
        """
        lookback = min(self.config.ath_lookback_days, len(highs) - 1)

        # Previous ATH = max high in lookback EXCLUDING last bar
        if lookback < 2:
            return {"has_ath": False, "previous_ath": 0, "pct_below_ath": 0, "lookback": lookback}

        previous_ath = max(highs[-lookback - 1 : -1])
        current_high = highs[-1]
        current_close = prices[-1]

        info = {
            "previous_ath": previous_ath,
            "current_high": current_high,
            "lookback": lookback,
        }

        # Check if current bar reaches or exceeds ATH
        if current_high >= previous_ath:
            info["has_ath"] = True
        else:
            pct_below = ((previous_ath - current_high) / previous_ath) * 100
            info["has_ath"] = False
            info["pct_below_ath"] = pct_below

        return info

    # =========================================================================
    # STEP 1b: CONSOLIDATION DETECTION
    # =========================================================================

    def _detect_consolidation(
        self,
        highs: List[float],
        lows: List[float],
        prices: List[float],
        previous_ath: float,
    ) -> Dict[str, Any]:
        """
        Detect consolidation (base building) before the breakout.

        Looks at the 20-60 days before the breakout and checks:
        1. Range = (max_high - min_low) / max_high * 100  → must be ≤ 15%
        2. Duration ≥ 20 days
        3. Count ATH tests (high within 1% of ATH without closing above)

        Returns:
            has_consolidation: bool
            range_pct: float
            duration: int
            ath_tests: int
            disqualify_reason: str (if not valid)
        """
        lookback = self.config.consolidation_lookback
        min_days = self.config.consolidation_min_days
        max_range = self.config.consolidation_max_range_pct
        test_tolerance = self.config.ath_test_tolerance_pct / 100

        # We look at data BEFORE the breakout day (excluding last bar)
        n = len(highs)
        if n < min_days + 1:
            return {
                "has_consolidation": False,
                "range_pct": 0,
                "duration": 0,
                "ath_tests": 0,
                "disqualify_reason": "Insufficient data for consolidation check",
            }

        # Consolidation window: last lookback bars excluding current bar
        end_idx = n - 1  # Exclude breakout bar
        start_idx = max(0, end_idx - lookback)
        consol_highs = highs[start_idx:end_idx]
        consol_lows = lows[start_idx:end_idx]
        consol_closes = prices[start_idx:end_idx]

        if len(consol_highs) < min_days:
            return {
                "has_consolidation": False,
                "range_pct": 0,
                "duration": len(consol_highs),
                "ath_tests": 0,
                "disqualify_reason": f"Consolidation too short: {len(consol_highs)} days (need >= {min_days})",
            }

        # Calculate range
        max_high = max(consol_highs)
        min_low = min(consol_lows)
        range_pct = ((max_high - min_low) / max_high) * 100 if max_high > 0 else 0

        # Find the best (tightest) consolidation window
        # Try different window sizes from min_days to full lookback
        best_range = range_pct
        best_duration = len(consol_highs)

        # Try progressively larger windows starting from min_days.
        # Range is monotonically non-decreasing with window size, so once
        # a window exceeds max_range, all larger windows will too.
        # We want the LONGEST valid window (strongest consolidation signal).
        for window_size in range(min_days, len(consol_highs) + 1, ATH_CONSOL_WINDOW_STEP):
            window_start = len(consol_highs) - window_size
            w_highs = consol_highs[window_start:]
            w_lows = consol_lows[window_start:]
            w_max = max(w_highs)
            w_min = min(w_lows)
            w_range = ((w_max - w_min) / w_max) * 100 if w_max > 0 else 0

            if w_range <= max_range:
                best_range = w_range
                best_duration = window_size
            else:
                break  # Range only grows with window size, stop here

        # If even the shortest window exceeds max_range, check if there's
        # any valid window
        if best_range > max_range:
            # Try the minimum window
            w_start = len(consol_highs) - min_days
            w_highs = consol_highs[w_start:]
            w_lows = consol_lows[w_start:]
            w_max = max(w_highs)
            w_min = min(w_lows)
            w_range = ((w_max - w_min) / w_max) * 100 if w_max > 0 else 0

            if w_range > max_range:
                return {
                    "has_consolidation": False,
                    "range_pct": round(w_range, 1),
                    "duration": min_days,
                    "ath_tests": 0,
                    "disqualify_reason": f"Range too wide: {w_range:.1f}% (max {max_range}%) — no consolidation",
                }
            best_range = w_range
            best_duration = min_days

        # Count ATH tests (high within test_tolerance of ATH, close below ATH)
        ath_tests = 0
        in_test = False
        for i in range(len(consol_highs)):
            h = consol_highs[i]
            c = consol_closes[i]
            if abs(h - previous_ath) / previous_ath <= test_tolerance and c < previous_ath:
                if not in_test:
                    ath_tests += 1
                    in_test = True
            else:
                in_test = False

        # Store window indices for VCP/volume profile analysis (A1, A2)
        consol_end = end_idx
        consol_start = end_idx - best_duration

        return {
            "has_consolidation": True,
            "consol_start": consol_start,
            "consol_end": consol_end,
            "range_pct": round(best_range, 1),
            "duration": best_duration,
            "ath_tests": ath_tests,
        }

    # =========================================================================
    # STEP 2: CLOSE CONFIRMATION
    # =========================================================================

    def _check_close_confirmation(
        self,
        prices: List[float],
        previous_ath: float,
    ) -> Dict[str, Any]:
        """
        Check if the breakout is confirmed by a daily close above ATH.

        Returns:
            confirmed: bool
            pct_above: float — % close is above ATH
            days_above: int — consecutive days with close > ATH
        """
        current_close = prices[-1]
        confirmed = current_close > previous_ath

        # Count consecutive days above ATH (from most recent backwards)
        days_above = 0
        for i in range(len(prices) - 1, -1, -1):
            if prices[i] > previous_ath:
                days_above += 1
            else:
                break

        pct_above = ((current_close - previous_ath) / previous_ath) * 100

        return {
            "confirmed": confirmed,
            "pct_above": round(pct_above, 2),
            "days_above": days_above,
            "previous_ath": previous_ath,
        }

    # =========================================================================
    # STEP 3: VOLUME CHECK
    # =========================================================================

    def _check_volume(self, volumes: List[int]) -> Dict[str, Any]:
        """
        Check breakout volume relative to 20-day average.

        Returns:
            ratio: float (breakout vol / avg vol)
            reason: str
        """
        avg_period = self.config.volume_avg_period

        if len(volumes) < avg_period + 1:
            return {"ratio": 1.0, "reason": "Insufficient volume data"}

        avg_volume = sum(volumes[-avg_period - 1 : -1]) / avg_period
        breakout_volume = volumes[-1]

        # Weekend/holiday fallback: use last non-zero volume
        if breakout_volume == 0 and len(volumes) >= 2:
            for v in reversed(volumes[:-1]):
                if v > 0:
                    breakout_volume = v
                    break

        ratio = breakout_volume / avg_volume if avg_volume > 0 else 0

        if ratio >= 2.0:
            reason = f"Very strong volume: {ratio:.1f}x avg"
        elif ratio >= 1.5:
            reason = f"Strong volume: {ratio:.1f}x avg"
        elif ratio >= 1.0:
            reason = f"Moderate volume: {ratio:.1f}x avg"
        else:
            reason = f"Weak volume: {ratio:.2f}x avg — breakout may fail"

        return {"ratio": round(ratio, 2), "reason": reason}

    # =========================================================================
    # STEP 4: RSI CHECK
    # =========================================================================

    def _calculate_rsi(self, prices: List[float]) -> float:
        """Calculate current RSI value."""
        period = self.config.rsi_period

        if len(prices) < period + 2:
            return 50.0

        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # Wilder's smoothed RSI
        gains = [max(c, 0) for c in changes[:period]]
        losses_list = [max(-c, 0) for c in changes[:period]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses_list) / period if sum(losses_list) > 0 else 0.0001

        for i in range(period, len(changes)):
            c = changes[i]
            avg_gain = (avg_gain * (period - 1) + max(c, 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-c, 0)) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    # =========================================================================
    # SCORING COMPONENTS
    # =========================================================================

    def _score_consolidation_quality(
        self,
        consol_info: Dict[str, Any],
        highs: Optional[List[float]] = None,
        lows: Optional[List[float]] = None,
    ) -> float:
        """
        Score consolidation quality (0 – 3.0).

        Tighter and longer base = higher score.
        ATH tests (2+) = +0.5 bonus.
        VCP contraction (A1) = +0.5/+0.25/-0.25.

        Scoring table:
          Range ≤ 8%, Duration 30+ days  → 2.5
          Range ≤ 8%, Duration 20-30     → 2.0
          Range 8-12%, Duration 60+      → 2.5
          Range 8-12%, Duration 30+      → 2.0
          Range 8-12%, Duration 20-30    → 1.5
          Range 12-15%, Duration 20+     → 1.0
          ATH tested 2+ times            → +0.5 bonus
          VCP contraction                → +0.5/+0.25/-0.25
          Cap: 3.0
        """
        range_pct = consol_info["range_pct"]
        duration = consol_info["duration"]
        ath_tests = consol_info["ath_tests"]

        # Base score from range + duration
        if range_pct <= ATH_RANGE_TIGHT_PCT:
            if duration >= ATH_CONSOL_DURATION_MIN:
                score = ATH_CONSOL_SCORE_TIGHT_LONG
            else:
                score = ATH_CONSOL_SCORE_TIGHT_SHORT
        elif range_pct <= ATH_RANGE_MODERATE_PCT:
            if duration >= ATH_CONSOL_DURATION_VERY_LONG:
                score = ATH_CONSOL_SCORE_TIGHT_LONG  # Very long moderate = same as tight long (2.5)
            elif duration >= ATH_CONSOL_DURATION_MIN:
                score = ATH_CONSOL_SCORE_MOD_LONG
            else:
                score = ATH_CONSOL_SCORE_MOD_SHORT
        elif range_pct <= ATH_RANGE_WIDE_PCT:
            score = ATH_CONSOL_SCORE_WIDE
        else:
            score = 0.0

        # ATH test bonus
        if ath_tests >= ATH_CONSOL_TEST_MIN:
            score += ATH_CONSOL_TEST_BONUS

        # VCP volatility contraction bonus (A1)
        if highs is not None and lows is not None and duration >= ATH_CONSOL_MIN_DAYS:
            vcp_score = self._score_vcp_contraction(consol_info, highs, lows)
            score += vcp_score

        return clamp_score(score, ATH_CONSOL_SCORE_MAX)

    def _score_vcp_contraction(
        self,
        consol_info: Dict[str, Any],
        highs: List[float],
        lows: List[float],
    ) -> float:
        """
        Score VCP-style volatility contraction within the consolidation (A1).

        Splits the consolidation window into two halves and compares
        the range (or ATR proxy) of each half. Decreasing volatility
        indicates institutional accumulation (supply drying up).

        Returns:
          contraction > 2.0x  → +0.5
          contraction > 1.5x  → +0.25
          contraction ≤ 1.0x  → -0.25 (expanding = bearish)
        """
        start = consol_info.get("consol_start")
        end = consol_info.get("consol_end")
        if start is None or end is None:
            return 0.0

        duration = end - start
        if duration < 10:
            return 0.0

        mid = start + duration // 2
        # First half range
        first_highs = highs[start:mid]
        first_lows = lows[start:mid]
        # Second half range (closer to breakout)
        second_highs = highs[mid:end]
        second_lows = lows[mid:end]

        if not first_highs or not second_highs:
            return 0.0

        first_range = max(first_highs) - min(first_lows)
        second_range = max(second_highs) - min(second_lows)

        if second_range <= 0:
            return ATH_VCP_CONTRACTION_BONUS_STRONG  # Perfect contraction

        contraction_ratio = first_range / second_range

        if contraction_ratio >= ATH_VCP_CONTRACTION_STRONG:
            return ATH_VCP_CONTRACTION_BONUS_STRONG
        elif contraction_ratio >= ATH_VCP_CONTRACTION_MODERATE:
            return ATH_VCP_CONTRACTION_BONUS_MODERATE
        elif contraction_ratio <= 1.0:
            return ATH_VCP_EXPANDING_PENALTY
        return 0.0

    def _score_consol_volume_profile(
        self,
        volumes: List[int],
        consol_info: Dict[str, Any],
    ) -> float:
        """
        Score consolidation volume profile (A2).

        Compares pre-consolidation average volume with consolidation volume.
        Decreasing volume during the base = supply drying up (bullish).
        Increasing volume during the base = distribution (bearish).

        Returns:
          dryup ratio > 1.5x  → +0.5
          dryup ratio > 1.2x  → +0.25
          dryup ratio < 0.8x  → -0.25 (distribution)
        """
        start = consol_info.get("consol_start")
        end = consol_info.get("consol_end")
        if start is None or end is None or start < 20:
            return 0.0

        # Pre-consolidation volume (20 days before consolidation)
        pre_start = max(0, start - 20)
        pre_volumes = volumes[pre_start:start]
        consol_volumes = volumes[start:end]

        if not pre_volumes or not consol_volumes:
            return 0.0

        pre_avg = sum(pre_volumes) / len(pre_volumes)
        consol_avg = sum(consol_volumes) / len(consol_volumes)

        if consol_avg <= 0:
            return 0.0

        dryup_ratio = pre_avg / consol_avg

        if dryup_ratio >= ATH_CONSOL_VOL_DRYUP_STRONG:
            return ATH_CONSOL_VOL_DRYUP_STRONG_BONUS
        elif dryup_ratio >= ATH_CONSOL_VOL_DRYUP_MODERATE:
            return ATH_CONSOL_VOL_DRYUP_MOD_BONUS
        elif dryup_ratio < ATH_CONSOL_VOL_DISTRIBUTION:
            return ATH_CONSOL_VOL_DISTRIBUTION_PENALTY
        return 0.0

    def _score_breakout_strength(
        self,
        close_info: Dict[str, Any],
        prices: Optional[List[float]] = None,
        highs: Optional[List[float]] = None,
        lows: Optional[List[float]] = None,
        opens: Optional[List[float]] = None,
    ) -> float:
        """
        Score breakout strength (0 – 2.5).

        Based on how far close is above ATH, days confirmed, candle quality, and gap.

        Scoring table:
          Close 0-1% above ATH           → 1.0
          Close 1-3% above ATH           → 1.5
          Close 3-5% above ATH           → 2.0
          Close > 5% above ATH           → 1.5 (potentially overextended)
          2+ days close above ATH         → +0.5 bonus
          Marubozu (close = high)         → +0.5
          Wide range bar (> 1.5x ATR)     → +0.25
          Close near high (> 80%)         → +0.25
          Long upper wick (> 50% range)   → -0.5
          Power gap above ATH (>3%)       → +0.5
          Standard gap above ATH (1-3%)   → +0.25
          Gap-down reversal close > ATH   → +0.25
          Cap: 2.5
        """
        pct_above = close_info["pct_above"]
        days_above = close_info["days_above"]

        # Base score from % above ATH
        if pct_above <= ATH_BREAKOUT_WEAK_PCT:
            score = ATH_BREAKOUT_SCORE_WEAK
        elif pct_above <= ATH_BREAKOUT_MODERATE_PCT:
            score = ATH_BREAKOUT_SCORE_MODERATE
        elif pct_above <= ATH_BREAKOUT_STRONG_PCT:
            score = ATH_BREAKOUT_SCORE_STRONG
        else:
            score = ATH_BREAKOUT_SCORE_OVEREXTENDED  # Overextended

        # Multi-day confirmation bonus
        if days_above >= ATH_BREAKOUT_DAYS_BONUS_MIN:
            score += ATH_BREAKOUT_CONFIRMATION_BONUS

        # Candle quality analysis (A4)
        if prices is not None and highs is not None and lows is not None and len(prices) >= 2:
            score += self._score_candle_quality(prices, highs, lows)

        # A5: Gap-up analysis
        if opens is not None and len(opens) >= 2 and prices is not None and len(prices) >= 2:
            prev_close = prices[-2]
            open_today = opens[-1]
            prev_ath = close_info.get("previous_ath", 0)

            if prev_close > 0:
                gap_pct = (open_today - prev_close) / prev_close * 100

                if open_today > prev_ath and gap_pct >= ATH_GAP_POWER_PCT:
                    score += ATH_GAP_POWER_BONUS
                elif open_today > prev_ath and gap_pct >= ATH_GAP_STANDARD_PCT:
                    score += ATH_GAP_STANDARD_BONUS
                elif gap_pct < 0 and prices[-1] > prev_ath:
                    # Gap down but closed above ATH — reversal strength
                    score += ATH_GAP_REVERSAL_BONUS

        return clamp_score(score, ATH_BREAKOUT_SCORE_MAX)

    def _score_candle_quality(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
    ) -> float:
        """
        Score breakout candle quality.

        Evaluates the form of the breakout bar:
          - Marubozu (close near high, minimal upper wick): +0.5
          - Wide Range Bar (range > 1.5x ATR): +0.25
          - Close near high (close position > 80%): +0.25
          - Long upper wick (> 50% of range): -0.5
        """
        close = prices[-1]
        high = highs[-1]
        low = lows[-1]
        open_approx = prices[-2]  # Previous close as open approximation

        total_range = high - low
        if total_range <= 0:
            return 0.0

        upper_wick = high - max(close, open_approx)
        close_position = (close - low) / total_range  # 0 = low, 1 = high

        candle_score = 0.0

        # Marubozu: minimal upper wick + bullish
        upper_wick_pct = (upper_wick / total_range) * 100
        if upper_wick_pct < ATH_CANDLE_MARUBOZU_WICK_MAX and close > open_approx:
            candle_score += ATH_CANDLE_MARUBOZU_BONUS
        elif close_position > ATH_CANDLE_CLOSE_HIGH_THRESHOLD:
            # Close near high (only if not already marubozu)
            candle_score += ATH_CANDLE_CLOSE_HIGH_BONUS

        # Wide Range Bar: range > 1.5x ATR(14)
        if len(highs) >= 15 and len(lows) >= 15:
            true_ranges = []
            for i in range(-15, -1):
                tr = highs[i] - lows[i]
                if i > -15:
                    tr = max(tr, abs(highs[i] - prices[i - 1]), abs(lows[i] - prices[i - 1]))
                true_ranges.append(tr)
            atr = sum(true_ranges) / len(true_ranges)
            if atr > 0 and total_range > atr * ATH_CANDLE_WIDE_RANGE_ATR_MULT:
                candle_score += ATH_CANDLE_WIDE_RANGE_BONUS

        # Long upper wick penalty: selling into breakout
        if upper_wick / total_range > ATH_CANDLE_LONG_WICK_THRESHOLD:
            candle_score += ATH_CANDLE_LONG_WICK_PENALTY

        return candle_score

    def _score_volume(self, ratio: float) -> float:
        """
        Score volume confirmation (-1.0 – 2.5).

        Scoring table:
          > 2.5x avg  → 2.5
          > 2.0x avg  → 2.0
          > 1.5x avg  → 1.5
          1.0-1.5x    → 0.5
          < 1.0x      → -1.0 (penalty)
        """
        if ratio >= ATH_VOLUME_EXCEPTIONAL:
            return ATH_VOLUME_SCORE_EXCEPTIONAL
        elif ratio >= ATH_VOLUME_STRONG:
            return ATH_VOLUME_SCORE_STRONG
        elif ratio >= ATH_VOLUME_GOOD:
            return ATH_VOLUME_SCORE_GOOD
        elif ratio >= ATH_VOLUME_ADEQUATE:
            return ATH_VOLUME_SCORE_ADEQUATE
        else:
            return ATH_VOLUME_SCORE_WEAK

    def _score_momentum_trend(
        self,
        prices: List[float],
        rsi_value: float,
        spy_prices: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Score momentum and trend context (-1.5 – 2.0).

        Components:
          SMA 20 > SMA 50 > SMA 200 (perfect alignment) → +0.5
          MACD bullish (line > signal)                    → +0.5
          RSI 50-70 (healthy momentum)                    → +0.5
          Relative Strength vs SPY (A3)                   → +0.5/+0.25/-0.5

        Penalties:
          RSI > 75 (overbought)   → -0.5
          SMA 200 falling         → -0.5
        """
        score = 0.0
        signals = []

        # SMA alignment check
        sma_20 = sum(prices[-SMA_SHORT:]) / SMA_SHORT if len(prices) >= SMA_SHORT else prices[-1]
        sma_50 = sum(prices[-SMA_MEDIUM:]) / SMA_MEDIUM if len(prices) >= SMA_MEDIUM else prices[-1]
        sma_200 = (
            sum(prices[-SMA_LONG:]) / SMA_LONG
            if len(prices) >= SMA_LONG
            else sum(prices) / len(prices)
        )

        current = prices[-1]

        if current > sma_20 > sma_50 > sma_200:
            score += ATH_MOMENTUM_SMA_PERFECT_BONUS
            signals.append("Perfect SMA alignment")
            trend_status = "strong_uptrend"
        elif current > sma_50 > sma_200:
            score += ATH_MOMENTUM_SMA_GOOD_BONUS
            signals.append("Good SMA alignment")
            trend_status = "uptrend"
        elif current > sma_200:
            trend_status = "above_sma200"
        else:
            trend_status = "below_sma200"

        # SMA 200 direction check
        if len(prices) >= SMA_LONG + ATH_MOMENTUM_SMA200_LOOKBACK:
            sma_200_prev = (
                sum(
                    prices[
                        -(SMA_LONG + ATH_MOMENTUM_SMA200_LOOKBACK) : -ATH_MOMENTUM_SMA200_LOOKBACK
                    ]
                )
                / SMA_LONG
            )
            if sma_200 < sma_200_prev * ATH_MOMENTUM_SMA200_DECLINE:
                score -= ATH_MOMENTUM_SMA200_DECLINE_PENALTY
                signals.append("SMA 200 falling")
                trend_status = "downtrend"

        # MACD check
        macd_result = calculate_macd(
            prices, fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
        )
        if macd_result:
            if macd_result.crossover == "bullish" or (
                macd_result.macd_line > macd_result.signal_line
            ):
                score += ATH_MOMENTUM_MACD_BONUS
                signals.append("MACD bullish")

        # RSI scoring
        if ATH_RSI_HEALTHY_LOW <= rsi_value <= ATH_RSI_HEALTHY_HIGH:
            score += ATH_RSI_HEALTHY_BONUS
            signals.append(f"RSI healthy ({rsi_value:.0f})")
        elif rsi_value > ATH_RSI_OVERBOUGHT:
            score -= ATH_RSI_OVERBOUGHT_PENALTY
            signals.append(f"RSI overbought ({rsi_value:.0f})")

        # A3: Relative Strength vs SPY
        rs_vs_spy = None
        if (
            spy_prices is not None
            and len(spy_prices) >= ATH_RS_LOOKBACK
            and len(prices) >= ATH_RS_LOOKBACK
        ):
            stock_perf = (prices[-1] / prices[-ATH_RS_LOOKBACK] - 1) * 100
            spy_perf = (spy_prices[-1] / spy_prices[-ATH_RS_LOOKBACK] - 1) * 100
            rs_vs_spy = stock_perf - spy_perf

            if rs_vs_spy > ATH_RS_STRONG:
                score += ATH_RS_STRONG_BONUS
                signals.append(f"Strong RS vs SPY (+{rs_vs_spy:.1f}%)")
            elif rs_vs_spy > ATH_RS_MODERATE:
                score += ATH_RS_MODERATE_BONUS
                signals.append(f"Moderate RS vs SPY (+{rs_vs_spy:.1f}%)")
            elif rs_vs_spy < ATH_RS_UNDERPERFORMANCE:
                score -= ATH_RS_UNDERPERFORMANCE_PENALTY
                signals.append(f"Laggard breakout (RS {rs_vs_spy:.1f}%)")

        # Clamp
        score = clamp_score(score, ATH_MOMENTUM_SCORE_MAX, ATH_MOMENTUM_SCORE_MIN)

        reason = ", ".join(signals) if signals else "Neutral momentum"

        return {
            "score": round(score, 2),
            "status": trend_status,
            "reason": reason,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "rsi": rsi_value,
            "rs_vs_spy": rs_vs_spy,
            "signals": signals,
        }

    # =========================================================================
    # SIGNAL TEXT
    # =========================================================================

    def _build_signal_text(
        self,
        current_price: float,
        previous_ath: float,
        close_info: Dict[str, Any],
        consol_info: Dict[str, Any],
        volume_info: Dict[str, Any],
        momentum_info: Dict[str, Any],
        rsi_value: float,
    ) -> str:
        """
        Build signal text in the new format:
        "ATH Breakout: Close $X (+Y% over ATH) | Base Z days (W% range, Nx tested) | Vol Mx avg | [Momentum]"
        """
        parts = []

        # Close info
        pct_above = close_info["pct_above"]
        days_str = f", day {close_info['days_above']}" if close_info["days_above"] >= 2 else ""
        parts.append(
            f"ATH Breakout: Close ${current_price:.2f} (+{pct_above:.1f}% over ATH{days_str})"
        )

        # Base info
        base_desc = f"{consol_info['duration']}-day base ({consol_info['range_pct']:.1f}% range"
        if consol_info["ath_tests"] >= 2:
            base_desc += f", {consol_info['ath_tests']}x tested"
        base_desc += ")"
        parts.append(base_desc)

        # Volume
        parts.append(f"Vol {volume_info['ratio']:.1f}x avg")

        # Momentum signals
        if momentum_info.get("signals"):
            parts.append(", ".join(momentum_info["signals"]))

        return " | ".join(parts)

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _make_disqualified_signal(
        self,
        symbol: str,
        current_price: float,
        reason: str,
    ) -> TradeSignal:
        """Create a neutral signal for disqualified candidates."""
        return self.create_neutral_signal(symbol, current_price, reason)

    def _calculate_stop_loss(
        self,
        lows: List[float],
        current_price: float,
    ) -> float:
        """Calculates stop-loss below last swing low."""
        # Last N-day low as support
        recent_low = min(lows[-ATH_STOP_RECENT_LOW_DAYS:])

        # Stop 1% below support
        stop = recent_low * (1 - self.config.stop_below_recent_low_pct / 100)

        # Max stop distance below current price
        max_stop = current_price * ATH_STOP_MAX_PCT

        return max(stop, max_stop)

    def _calculate_target(
        self,
        entry: float,
        stop: float,
    ) -> float:
        """Calculates target with configurable Risk/Reward."""
        risk = entry - stop
        return entry + (risk * self.config.target_risk_reward)
