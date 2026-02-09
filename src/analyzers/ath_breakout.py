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

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
import logging
import numpy as np

from .base import BaseAnalyzer
from .context import AnalysisContext

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..models.strategy_breakdowns import ATHBreakoutScoreBreakdown
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength
    from models.strategy_breakdowns import ATHBreakoutScoreBreakdown

logger = logging.getLogger(__name__)

# Import S/R analysis
try:
    from ..indicators.support_resistance import get_nearest_sr_levels
except ImportError:
    from indicators.support_resistance import get_nearest_sr_levels

# Import shared indicators
try:
    from ..indicators.momentum import calculate_macd
except ImportError:
    from indicators.momentum import calculate_macd

# Import Feature Scoring Mixin
try:
    from .feature_scoring_mixin import FeatureScoringMixin
except ImportError:
    from analyzers.feature_scoring_mixin import FeatureScoringMixin

# Import central constants
try:
    from ..constants import (
        RSI_PERIOD,
        MACD_FAST, MACD_SLOW, MACD_SIGNAL,
        SMA_SHORT, SMA_MEDIUM, SMA_LONG,
        VOLUME_AVG_PERIOD,
        SR_LOOKBACK_DAYS_EXTENDED,
        ATH_LOOKBACK_DAYS,
    )
except ImportError:
    from constants import (
        RSI_PERIOD,
        MACD_FAST, MACD_SLOW, MACD_SIGNAL,
        SMA_SHORT, SMA_MEDIUM, SMA_LONG,
        VOLUME_AVG_PERIOD,
        SR_LOOKBACK_DAYS_EXTENDED,
        ATH_LOOKBACK_DAYS,
    )


# =============================================================================
# CONSTANTS for ATH Breakout Strategy v2
# =============================================================================

ATH_CONSOL_LOOKBACK = 60           # Max lookback for consolidation detection
ATH_CONSOL_MIN_DAYS = 20           # Minimum consolidation duration
ATH_CONSOL_MAX_RANGE_PCT = 15.0    # Max range for consolidation (%)
ATH_CONSOL_ATH_TEST_PCT = 1.0     # ATH test = high within 1% of ATH
ATH_VOLUME_DISQUALIFY = 1.0       # Vol < 1.0x avg = disqualify
ATH_RSI_DISQUALIFY = 80.0         # RSI > 80 = disqualify
ATH_MIN_SCORE = 4.0                # Minimum total score for signal
ATH_MAX_SCORE = 9.5                # Theoretical maximum (2.5 + 2.0 + 2.5 + 1.5 + bonus)

# Consolidation Range Tiers
ATH_RANGE_TIGHT_PCT = 8.0
ATH_RANGE_MODERATE_PCT = 12.0
ATH_RANGE_WIDE_PCT = 15.0
ATH_CONSOL_DURATION_MIN = 30
ATH_CONSOL_SCORE_TIGHT_LONG = 2.5
ATH_CONSOL_SCORE_TIGHT_SHORT = 2.0
ATH_CONSOL_SCORE_MOD_LONG = 2.0
ATH_CONSOL_SCORE_MOD_SHORT = 1.5
ATH_CONSOL_SCORE_WIDE = 1.0
ATH_CONSOL_TEST_MIN = 2
ATH_CONSOL_TEST_BONUS = 0.5
ATH_CONSOL_SCORE_MAX = 2.5

# Breakout Strength Tiers
ATH_BREAKOUT_WEAK_PCT = 1.0
ATH_BREAKOUT_MODERATE_PCT = 3.0
ATH_BREAKOUT_STRONG_PCT = 5.0
ATH_BREAKOUT_SCORE_WEAK = 1.0
ATH_BREAKOUT_SCORE_MODERATE = 1.5
ATH_BREAKOUT_SCORE_STRONG = 2.0
ATH_BREAKOUT_SCORE_OVEREXTENDED = 1.5
ATH_BREAKOUT_DAYS_BONUS_MIN = 2
ATH_BREAKOUT_CONFIRMATION_BONUS = 0.5
ATH_BREAKOUT_SCORE_MAX = 2.0

# Volume Score Tiers
ATH_VOLUME_EXCEPTIONAL = 2.5
ATH_VOLUME_STRONG = 2.0
ATH_VOLUME_GOOD = 1.5
ATH_VOLUME_ADEQUATE = 1.0
ATH_VOLUME_SCORE_EXCEPTIONAL = 2.5
ATH_VOLUME_SCORE_STRONG = 2.0
ATH_VOLUME_SCORE_GOOD = 1.5
ATH_VOLUME_SCORE_ADEQUATE = 0.5
ATH_VOLUME_SCORE_WEAK = -1.0

# Momentum/Trend Scoring
ATH_MOMENTUM_SMA_PERFECT_BONUS = 0.5
ATH_MOMENTUM_SMA_GOOD_BONUS = 0.25
ATH_MOMENTUM_SMA200_DECLINE = 0.999
ATH_MOMENTUM_SMA200_DECLINE_PENALTY = 0.5
ATH_MOMENTUM_SMA200_LOOKBACK = 20
ATH_MOMENTUM_MACD_BONUS = 0.5
ATH_RSI_HEALTHY_LOW = 50
ATH_RSI_HEALTHY_HIGH = 70
ATH_RSI_HEALTHY_BONUS = 0.5
ATH_RSI_OVERBOUGHT = 75
ATH_RSI_OVERBOUGHT_PENALTY = 0.5
ATH_MOMENTUM_SCORE_MIN = -1.0
ATH_MOMENTUM_SCORE_MAX = 1.5

# Signal Strength
ATH_SIGNAL_STRONG = 7.0
ATH_SIGNAL_MODERATE = 5.5

# Stop Loss
ATH_STOP_RECENT_LOW_DAYS = 10
ATH_STOP_MAX_PCT = 0.95

# Consolidation Search
ATH_CONSOL_WINDOW_STEP = 5


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
        **kwargs
    ):
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
        **kwargs
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
            spy_prices: Optional SPY prices (unused in v2, kept for compat)
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

        if not ath_info['has_ath']:
            return self._make_disqualified_signal(
                symbol, current_price,
                f"No ATH breakout: price is {ath_info.get('pct_below_ath', 0):.1f}% below {ath_info['lookback']}-day high"
            )

        previous_ath = ath_info['previous_ath']

        # Check consolidation
        consol_info = self._detect_consolidation(highs, lows, prices, previous_ath)

        if not consol_info['has_consolidation']:
            return self._make_disqualified_signal(
                symbol, current_price,
                consol_info.get('disqualify_reason', 'No consolidation before breakout')
            )

        breakdown.ath_old = previous_ath
        breakdown.ath_current = current_high
        breakdown.ath_had_consolidation = True

        # =====================================================================
        # STEP 2: Close Confirmation (PFLICHT)
        # =====================================================================
        close_info = self._check_close_confirmation(prices, previous_ath)

        if not close_info['confirmed']:
            return self._make_disqualified_signal(
                symbol, current_price,
                f"Breakout not confirmed: close ${current_price:.2f} is below ATH ${previous_ath:.2f} (intraday fakeout)"
            )

        breakdown.ath_pct_above = close_info['pct_above']

        # =====================================================================
        # STEP 3: Volume Confirmation (PFLICHT — < 1.0x = disqualify)
        # =====================================================================
        volume_info = self._check_volume(volumes)

        if volume_info['ratio'] < self.config.volume_disqualify_threshold:
            return self._make_disqualified_signal(
                symbol, current_price,
                f"Weak volume: {volume_info['ratio']:.2f}x avg (< {self.config.volume_disqualify_threshold}x) — likely false breakout"
            )

        # =====================================================================
        # STEP 4: RSI Check (> 80 = disqualify)
        # =====================================================================
        rsi_value = self._calculate_rsi(prices)

        if rsi_value > self.config.rsi_disqualify:
            return self._make_disqualified_signal(
                symbol, current_price,
                f"RSI overbought at {rsi_value:.0f} (> {self.config.rsi_disqualify:.0f}) — reversal likely"
            )

        # =====================================================================
        # SCORING: 4 Components
        # =====================================================================

        # 1. Consolidation Quality (0 – 2.5)
        consol_score = self._score_consolidation_quality(consol_info)
        breakdown.ath_score = consol_score
        breakdown.ath_reason = (
            f"Base {consol_info['duration']} days, "
            f"{consol_info['range_pct']:.1f}% range"
            + (f", {consol_info['ath_tests']}x tested" if consol_info['ath_tests'] >= 2 else "")
        )

        # 2. Breakout Strength (0 – 2.0)
        breakout_score = self._score_breakout_strength(close_info)

        # 3. Volume Confirmation (-1.0 – 2.5)
        volume_score = self._score_volume(volume_info['ratio'])
        breakdown.volume_score = volume_score
        breakdown.volume_ratio = volume_info['ratio']
        breakdown.volume_reason = volume_info.get('reason', '')

        # 4. Momentum / Trend Context (-1.0 – 1.5)
        momentum_info = self._score_momentum_trend(prices, rsi_value)
        momentum_score = momentum_info['score']
        breakdown.trend_score = momentum_score
        breakdown.trend_status = momentum_info.get('status', '')
        breakdown.trend_reason = momentum_info.get('reason', '')
        breakdown.rsi_value = rsi_value
        breakdown.rsi_reason = f"RSI={rsi_value:.1f}"

        # Total score
        total_score = consol_score + breakout_score + volume_score + momentum_score
        total_score = max(0.0, min(10.0, total_score))
        breakdown.total_score = round(total_score, 1)
        breakdown.max_possible = 10.0

        # =====================================================================
        # BUILD SIGNAL
        # =====================================================================
        signal_text = self._build_signal_text(
            current_price, previous_ath, close_info,
            consol_info, volume_info, momentum_info, rsi_value
        )

        # Signal strength
        if total_score >= ATH_SIGNAL_STRONG:
            strength = SignalStrength.STRONG
        elif total_score >= ATH_SIGNAL_MODERATE:
            strength = SignalStrength.MODERATE
        elif total_score >= ATH_MIN_SCORE:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE

        # Entry/Stop/Target
        entry_price = current_price
        stop_loss = self._calculate_stop_loss(lows, current_price)
        target_price = self._calculate_target(current_price, stop_loss)

        # Extended S/R for context
        sr_levels = get_nearest_sr_levels(
            current_price=current_price,
            prices=prices, highs=highs, lows=lows,
            volumes=volumes,
            lookback=SR_LOOKBACK_DAYS_EXTENDED,
            num_levels=3
        )

        # Warnings
        if rsi_value > ATH_RSI_OVERBOUGHT:
            warnings.append(f"RSI elevated at {rsi_value:.0f} — near overbought")
        if volume_info['ratio'] < ATH_VOLUME_GOOD:
            warnings.append(f"Volume only {volume_info['ratio']:.1f}x avg — elevated false breakout risk")
        if momentum_score < 0:
            warnings.append("Weak momentum context")

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.LONG if total_score >= ATH_MIN_SCORE else SignalType.NEUTRAL,
            strength=strength,
            score=round(total_score, 1),
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=signal_text,
            details={
                'score_breakdown': breakdown.to_dict(),
                'raw_score': total_score,
                'max_possible': 10.0,
                'ath_info': {
                    'previous_ath': previous_ath,
                    'pct_above': close_info['pct_above'],
                    'days_above': close_info['days_above'],
                    'lookback': ath_info['lookback'],
                },
                'consolidation_info': consol_info,
                'volume_info': volume_info,
                'momentum_info': momentum_info,
                'rsi': rsi_value,
                'sr_levels': sr_levels,
                'components': {
                    'consolidation_quality': consol_score,
                    'breakout_strength': breakout_score,
                    'volume': volume_score,
                    'momentum_trend': momentum_score,
                },
            },
            warnings=warnings
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
            return {'has_ath': False, 'previous_ath': 0, 'pct_below_ath': 0, 'lookback': lookback}

        previous_ath = max(highs[-lookback - 1:-1])
        current_high = highs[-1]
        current_close = prices[-1]

        info = {
            'previous_ath': previous_ath,
            'current_high': current_high,
            'lookback': lookback,
        }

        # Check if current bar reaches or exceeds ATH
        if current_high >= previous_ath:
            info['has_ath'] = True
        else:
            pct_below = ((previous_ath - current_high) / previous_ath) * 100
            info['has_ath'] = False
            info['pct_below_ath'] = pct_below

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
                'has_consolidation': False,
                'range_pct': 0,
                'duration': 0,
                'ath_tests': 0,
                'disqualify_reason': 'Insufficient data for consolidation check',
            }

        # Consolidation window: last lookback bars excluding current bar
        end_idx = n - 1  # Exclude breakout bar
        start_idx = max(0, end_idx - lookback)
        consol_highs = highs[start_idx:end_idx]
        consol_lows = lows[start_idx:end_idx]
        consol_closes = prices[start_idx:end_idx]

        if len(consol_highs) < min_days:
            return {
                'has_consolidation': False,
                'range_pct': 0,
                'duration': len(consol_highs),
                'ath_tests': 0,
                'disqualify_reason': f'Consolidation too short: {len(consol_highs)} days (need >= {min_days})',
            }

        # Calculate range
        max_high = max(consol_highs)
        min_low = min(consol_lows)
        range_pct = ((max_high - min_low) / max_high) * 100 if max_high > 0 else 0

        # Find the best (tightest) consolidation window
        # Try different window sizes from min_days to full lookback
        best_range = range_pct
        best_duration = len(consol_highs)

        # Try progressively larger windows starting from min_days
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
                break  # Take the longest valid window

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
                    'has_consolidation': False,
                    'range_pct': round(w_range, 1),
                    'duration': min_days,
                    'ath_tests': 0,
                    'disqualify_reason': f'Range too wide: {w_range:.1f}% (max {max_range}%) — no consolidation',
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

        return {
            'has_consolidation': True,
            'range_pct': round(best_range, 1),
            'duration': best_duration,
            'ath_tests': ath_tests,
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
            'confirmed': confirmed,
            'pct_above': round(pct_above, 2),
            'days_above': days_above,
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
            return {'ratio': 1.0, 'reason': 'Insufficient volume data'}

        avg_volume = sum(volumes[-avg_period - 1:-1]) / avg_period
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

        return {'ratio': round(ratio, 2), 'reason': reason}

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

    def _score_consolidation_quality(self, consol_info: Dict[str, Any]) -> float:
        """
        Score consolidation quality (0 – 2.5).

        Tighter and longer base = higher score.
        ATH tests (2+) = +0.5 bonus.

        Scoring table:
          Range ≤ 8%, Duration 30+ days  → 2.5
          Range ≤ 8%, Duration 20-30     → 2.0
          Range 8-12%, Duration 30+      → 2.0
          Range 8-12%, Duration 20-30    → 1.5
          Range 12-15%, Duration 20+     → 1.0
          ATH tested 2+ times            → +0.5 bonus (max 2.5)
        """
        range_pct = consol_info['range_pct']
        duration = consol_info['duration']
        ath_tests = consol_info['ath_tests']

        # Base score from range + duration
        if range_pct <= ATH_RANGE_TIGHT_PCT:
            if duration >= ATH_CONSOL_DURATION_MIN:
                score = ATH_CONSOL_SCORE_TIGHT_LONG
            else:
                score = ATH_CONSOL_SCORE_TIGHT_SHORT
        elif range_pct <= ATH_RANGE_MODERATE_PCT:
            if duration >= ATH_CONSOL_DURATION_MIN:
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

        return min(ATH_CONSOL_SCORE_MAX, score)

    def _score_breakout_strength(self, close_info: Dict[str, Any]) -> float:
        """
        Score breakout strength (0 – 2.0).

        Based on how far close is above ATH and days confirmed.

        Scoring table:
          Close 0-1% above ATH           → 1.0
          Close 1-3% above ATH           → 1.5
          Close 3-5% above ATH           → 2.0
          Close > 5% above ATH           → 1.5 (potentially overextended)
          2+ days close above ATH         → +0.5 bonus (max 2.0)
        """
        pct_above = close_info['pct_above']
        days_above = close_info['days_above']

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

        return min(ATH_BREAKOUT_SCORE_MAX, score)

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
    ) -> Dict[str, Any]:
        """
        Score momentum and trend context (-1.0 – 1.5).

        Components:
          SMA 20 > SMA 50 > SMA 200 (perfect alignment) → +0.5
          MACD bullish (line > signal)                    → +0.5
          RSI 50-70 (healthy momentum)                    → +0.5

        Penalties:
          RSI > 75 (overbought)   → -0.5
          SMA 200 falling         → -0.5
        """
        score = 0.0
        signals = []

        # SMA alignment check
        sma_20 = sum(prices[-SMA_SHORT:]) / SMA_SHORT if len(prices) >= SMA_SHORT else prices[-1]
        sma_50 = sum(prices[-SMA_MEDIUM:]) / SMA_MEDIUM if len(prices) >= SMA_MEDIUM else prices[-1]
        sma_200 = sum(prices[-SMA_LONG:]) / SMA_LONG if len(prices) >= SMA_LONG else sum(prices) / len(prices)

        current = prices[-1]

        if current > sma_20 > sma_50 > sma_200:
            score += ATH_MOMENTUM_SMA_PERFECT_BONUS
            signals.append("Perfect SMA alignment")
            trend_status = 'strong_uptrend'
        elif current > sma_50 > sma_200:
            score += ATH_MOMENTUM_SMA_GOOD_BONUS
            signals.append("Good SMA alignment")
            trend_status = 'uptrend'
        elif current > sma_200:
            trend_status = 'above_sma200'
        else:
            trend_status = 'below_sma200'

        # SMA 200 direction check
        if len(prices) >= SMA_LONG + ATH_MOMENTUM_SMA200_LOOKBACK:
            sma_200_prev = sum(prices[-(SMA_LONG + ATH_MOMENTUM_SMA200_LOOKBACK):-ATH_MOMENTUM_SMA200_LOOKBACK]) / SMA_LONG
            if sma_200 < sma_200_prev * ATH_MOMENTUM_SMA200_DECLINE:
                score -= ATH_MOMENTUM_SMA200_DECLINE_PENALTY
                signals.append("SMA 200 falling")
                trend_status = 'downtrend'

        # MACD check
        macd_result = calculate_macd(
            prices,
            fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
        )
        if macd_result:
            if macd_result.crossover == 'bullish' or (macd_result.macd_line > macd_result.signal_line):
                score += ATH_MOMENTUM_MACD_BONUS
                signals.append("MACD bullish")

        # RSI scoring
        if ATH_RSI_HEALTHY_LOW <= rsi_value <= ATH_RSI_HEALTHY_HIGH:
            score += ATH_RSI_HEALTHY_BONUS
            signals.append(f"RSI healthy ({rsi_value:.0f})")
        elif rsi_value > ATH_RSI_OVERBOUGHT:
            score -= ATH_RSI_OVERBOUGHT_PENALTY
            signals.append(f"RSI overbought ({rsi_value:.0f})")

        # Clamp
        score = max(ATH_MOMENTUM_SCORE_MIN, min(ATH_MOMENTUM_SCORE_MAX, score))

        reason = ", ".join(signals) if signals else "Neutral momentum"

        return {
            'score': round(score, 2),
            'status': trend_status,
            'reason': reason,
            'sma_20': sma_20,
            'sma_50': sma_50,
            'sma_200': sma_200,
            'rsi': rsi_value,
            'signals': signals,
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
        pct_above = close_info['pct_above']
        days_str = f", day {close_info['days_above']}" if close_info['days_above'] >= 2 else ""
        parts.append(f"ATH Breakout: Close ${current_price:.2f} (+{pct_above:.1f}% over ATH{days_str})")

        # Base info
        base_desc = f"{consol_info['duration']}-day base ({consol_info['range_pct']:.1f}% range"
        if consol_info['ath_tests'] >= 2:
            base_desc += f", {consol_info['ath_tests']}x tested"
        base_desc += ")"
        parts.append(base_desc)

        # Volume
        parts.append(f"Vol {volume_info['ratio']:.1f}x avg")

        # Momentum signals
        if momentum_info.get('signals'):
            parts.append(", ".join(momentum_info['signals']))

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
