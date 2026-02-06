# OptionPlay - Earnings Dip Analyzer
# ====================================
# Analyzes buying opportunities after earnings-related dips
#
# Strategy: Buy when good stock is oversold after earnings overreaction
# - Contrarian/Mean-Reversion Signal
# - Works with quality stocks experiencing temporary sentiment shock
# - Risk: Dip is justified (fundamental deterioration)

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, date, timedelta
import logging
import numpy as np

from .base import BaseAnalyzer
from .context import AnalysisContext

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..models.indicators import MACDResult, StochasticResult, KeltnerChannelResult
    from ..models.strategy_breakdowns import EarningsDipScoreBreakdown
    from ..config import EarningsDipScoringConfig
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength
    from models.indicators import MACDResult, StochasticResult, KeltnerChannelResult
    from models.strategy_breakdowns import EarningsDipScoreBreakdown
    from config import EarningsDipScoringConfig

logger = logging.getLogger(__name__)

# Import shared indicators
try:
    from ..indicators.momentum import calculate_macd, calculate_stochastic
    from ..indicators.trend import calculate_ema
    from ..indicators.volatility import calculate_atr_simple, calculate_keltner_channel
except ImportError:
    from indicators.momentum import calculate_macd, calculate_stochastic
    from indicators.trend import calculate_ema
    from indicators.volatility import calculate_atr_simple, calculate_keltner_channel

# Import Feature Scoring Mixin (NEW from Feature Engineering)
try:
    from .feature_scoring_mixin import FeatureScoringMixin
except ImportError:
    from analyzers.feature_scoring_mixin import FeatureScoringMixin

# Import central constants
try:
    from ..constants import (
        RSI_PERIOD,
        MACD_FAST, MACD_SLOW, MACD_SIGNAL,
        STOCH_K_PERIOD, STOCH_D_PERIOD, STOCH_SMOOTH,
        SMA_MEDIUM, SMA_LONG,
        VOLUME_AVG_PERIOD, VOLUME_RECENT_WINDOW,
        VOLUME_TREND_LOW, VOLUME_TREND_HIGH,
        VOLUME_SPIKE_MULTIPLIER,
        KELTNER_NEUTRAL_LOW,
        SUPPORT_LOOKBACK_DAYS,
    )
except ImportError:
    from constants import (
        RSI_PERIOD,
        MACD_FAST, MACD_SLOW, MACD_SIGNAL,
        STOCH_K_PERIOD, STOCH_D_PERIOD, STOCH_SMOOTH,
        SMA_MEDIUM, SMA_LONG,
        VOLUME_AVG_PERIOD, VOLUME_RECENT_WINDOW,
        VOLUME_TREND_LOW, VOLUME_TREND_HIGH,
        VOLUME_SPIKE_MULTIPLIER,
        KELTNER_NEUTRAL_LOW,
        SUPPORT_LOOKBACK_DAYS,
    )


@dataclass
class GapInfo:
    """Information about a gap down"""
    detected: bool = False
    gap_day_index: int = -1
    gap_size_pct: float = 0.0
    gap_open: float = 0.0
    prev_close: float = 0.0
    gap_filled: bool = False
    fill_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'detected': self.detected,
            'gap_day_index': self.gap_day_index,
            'gap_size_pct': round(self.gap_size_pct, 2),
            'gap_open': round(self.gap_open, 2) if self.gap_open else 0,
            'prev_close': round(self.prev_close, 2) if self.prev_close else 0,
            'gap_filled': self.gap_filled,
            'fill_pct': round(self.fill_pct, 1)
        }


@dataclass
class EarningsDipConfig:
    """Configuration for Earnings Dip Analyzer (Legacy - for backward compatibility)"""
    # Dip Detection
    min_dip_pct: float = 5.0
    max_dip_pct: float = 25.0
    dip_lookback_days: int = 5

    # Quality Filters
    require_above_sma200: bool = True
    min_market_cap: float = 10e9

    # Recovery Signs
    require_stabilization: bool = True
    stabilization_days: int = 2

    # RSI für Oversold nach Dip
    rsi_oversold_threshold: float = 35.0

    # Gap Analysis
    analyze_gap: bool = True
    min_gap_pct: float = 2.0
    gap_fill_threshold: float = 50.0

    # Risk Management
    stop_below_dip_low_pct: float = 3.0
    target_recovery_pct: float = 50.0

    # Scoring
    max_score: int = 10
    min_score_for_signal: int = 6


class EarningsDipAnalyzer(BaseAnalyzer, FeatureScoringMixin):
    """
    Analyzes stocks for buying opportunities after earnings dips.

    Scoring criteria (extended):
    - Earnings dip (5-15%): 0-3 points
    - Gap-down confirms earnings event: 0-1 point
    - RSI strongly oversold (< 30): 0-2 points
    - Price stabilized (no new lows): 0-2 points
    - Volume normalized: 0-2 points
    - Long-term uptrend (above SMA200): 0-2 points
    - MACD Recovery Signal: 0-2 points (NEW)
    - Stochastic Recovery: 0-2 points (NEW)
    - Keltner Channel: 0-2 points (NEW)

    Usage:
        analyzer = EarningsDipAnalyzer()
        signal = analyzer.analyze(
            "AAPL", prices, volumes, highs, lows,
            earnings_date=date(2025, 1, 20)
        )

        if signal.is_actionable:
            print(f"Earnings Dip Signal: {signal.score}/18")
    """

    def __init__(
        self,
        config: Optional[EarningsDipConfig] = None,
        scoring_config: Optional[EarningsDipScoringConfig] = None
    ):
        self.config = config or EarningsDipConfig()
        self.scoring_config = scoring_config or EarningsDipScoringConfig()

    @property
    def strategy_name(self) -> str:
        return "earnings_dip"

    @property
    def description(self) -> str:
        return "Earnings Dip Buy - Buy after exaggerated earnings selloff in quality stocks"

    def analyze(
        self,
        symbol: str,
        prices: List[float],
        volumes: List[int],
        highs: List[float],
        lows: List[float],
        earnings_date: Optional[date] = None,
        pre_earnings_price: Optional[float] = None,
        context: Optional[AnalysisContext] = None,
        **kwargs
    ) -> TradeSignal:
        """
        Analyzes a symbol for earnings dip buying opportunity.
        """
        # Input validation
        self.validate_inputs(prices, volumes, highs, lows, min_length=60)

        current_price = prices[-1]

        # Initialize score breakdown
        breakdown = EarningsDipScoreBreakdown()
        reasons = []
        warnings = []

        # 1. Dip Detection (0-3 Punkte)
        dip_result = self._detect_earnings_dip(
            prices, highs, lows, earnings_date, pre_earnings_price
        )
        breakdown.dip_score = dip_result[0]
        breakdown.dip_pct = dip_result[1].get('dip_pct', 0)
        breakdown.dip_low = dip_result[1].get('dip_low', 0)
        breakdown.pre_earnings_price = dip_result[1].get('pre_earnings_price', 0)
        breakdown.dip_reason = dip_result[1].get('reason', '')

        if breakdown.dip_score == 0:
            return self.create_neutral_signal(
                symbol, current_price,
                dip_result[1].get('reason', 'No earnings dip detected')
            )

        reasons.append(f"Earnings-Dip: -{breakdown.dip_pct:.1f}%")

        if breakdown.dip_pct > 15:
            warnings.append(f"Large dip (>{breakdown.dip_pct:.0f}%) - increased risk")

        # 2. Gap Detection (0-1 Punkt)
        gap_result = self._detect_gap_down(prices, highs, lows)
        gap_info = gap_result[1]
        breakdown.gap_score = gap_result[0]
        breakdown.gap_detected = gap_info.detected
        breakdown.gap_size_pct = gap_info.gap_size_pct
        breakdown.gap_filled = gap_info.gap_filled
        breakdown.gap_fill_pct = gap_info.fill_pct
        breakdown.gap_reason = "Gap detected" if gap_info.detected else "No gap"

        if breakdown.gap_score > 0:
            reasons.append(f"Gap Down -{breakdown.gap_size_pct:.1f}%")
            if breakdown.gap_filled:
                reasons.append(f"Gap {breakdown.gap_fill_pct:.0f}% filled")
        else:
            if self.config.analyze_gap:
                warnings.append("No gap down detected - possibly no earnings event")

        # 3. RSI Oversold (0-2 points)
        rsi_result = self._score_rsi_oversold(prices)
        breakdown.rsi_score = rsi_result[0]
        breakdown.rsi_value = rsi_result[1]
        breakdown.rsi_reason = f"RSI={breakdown.rsi_value:.1f}"

        if breakdown.rsi_score >= 2:
            reasons.append(f"Strongly oversold (RSI {breakdown.rsi_value:.0f})")
        elif breakdown.rsi_score == 1:
            reasons.append(f"Oversold (RSI {breakdown.rsi_value:.0f})")

        # 4. Stabilization (0-2 points)
        stab_result = self._score_stabilization(lows)
        breakdown.stabilization_score = stab_result[0]
        breakdown.days_without_new_low = stab_result[1].get('days_without_new_low', 0)
        breakdown.stabilization_reason = f"{breakdown.days_without_new_low} days without new low"

        if breakdown.stabilization_score > 0:
            reasons.append(f"Price stabilized ({breakdown.days_without_new_low} days without new low)")
        else:
            warnings.append("No stabilization yet - possibly too early")

        # 5. Volume normalization (0-2 points) - extended
        vol_result = self._score_volume_normalization(volumes)
        breakdown.volume_score = vol_result[0]
        breakdown.volume_ratio = vol_result[1].get('multiplier', 0)
        breakdown.volume_trend = vol_result[1].get('trend', 'unknown')
        breakdown.volume_reason = vol_result[1].get('reason', '')

        if breakdown.volume_score > 0:
            reasons.append("Selling pressure declining")

        # 6. Long-term trend (0-2 points)
        trend_result = self._score_long_term_trend(prices)
        breakdown.trend_score = trend_result[0]
        breakdown.trend_status = trend_result[1].get('trend', 'unknown')
        breakdown.was_in_uptrend = trend_result[1].get('was_in_uptrend', False)
        breakdown.trend_reason = f"Trend: {breakdown.trend_status}"

        if breakdown.trend_score >= 2:
            reasons.append("Long-term uptrend intact")
        elif breakdown.trend_score == 0:
            warnings.append("Below SMA200 - weaker long-term trend")

        # 7. MACD Recovery Score (0-2 points) - NEW
        macd_result = self._calculate_macd(prices)
        macd_score_result = self._score_macd_recovery(macd_result, prices)
        breakdown.macd_score = macd_score_result[0]
        breakdown.macd_signal = macd_score_result[2]
        breakdown.macd_histogram = macd_result.histogram if macd_result else 0
        breakdown.macd_turning_up = macd_score_result[3]
        breakdown.macd_reason = macd_score_result[1]

        if breakdown.macd_score >= 2:
            reasons.append("MACD turning bullish")
        elif breakdown.macd_score > 0:
            reasons.append("MACD recovery signs")

        # 8. Stochastic Recovery (0-2 points) - NEW
        stoch_result = self._calculate_stochastic(prices, highs, lows)
        stoch_score_result = self._score_stochastic(stoch_result)
        breakdown.stoch_score = stoch_score_result[0]
        breakdown.stoch_signal = stoch_score_result[2]
        breakdown.stoch_k = stoch_result.k if stoch_result else 0
        breakdown.stoch_d = stoch_result.d if stoch_result else 0
        breakdown.stoch_reason = stoch_score_result[1]

        if breakdown.stoch_score >= 2:
            reasons.append("Stoch oversold + cross")
        elif breakdown.stoch_score > 0:
            reasons.append("Stoch oversold")

        # 9. Keltner Channel (0-2 points) - NEW
        keltner_result = self._calculate_keltner_channel(prices, highs, lows)
        if keltner_result:
            keltner_score_result = self._score_keltner(keltner_result, current_price)
            breakdown.keltner_score = keltner_score_result[0]
            breakdown.keltner_position = keltner_result.price_position
            breakdown.keltner_percent = keltner_result.percent_position
            breakdown.keltner_reason = keltner_score_result[1]

            if breakdown.keltner_score >= 2:
                reasons.append("Below Keltner lower band")
            elif breakdown.keltner_score > 0:
                reasons.append("Near Keltner lower band")

        # NEW: Apply Feature Engineering scores (VWAP, Market Context, Sector)
        self._apply_feature_scores(breakdown, symbol, prices, volumes, context)

        # Resolve weights from config (4-layer: Base → Regime → Sector → Regime×Sector)
        regime = getattr(context, 'regime', 'normal') if context else 'normal'
        sector_ctx = getattr(context, 'sector', None) if context else None
        try:
            resolved = self.get_weights(regime=regime, sector=sector_ctx)
            w = resolved.weights
        except Exception:
            w = {}

        # Default max weights per component (original hardcoded values)
        _DEFAULTS = {
            'dip': 3.0, 'gap': 2.0, 'rsi': 2.0, 'stabilization': 2.0,
            'volume': 2.0, 'trend': 2.0, 'macd': 2.0, 'stoch': 2.0,
            'keltner': 2.0, 'vwap': 3.0, 'market_context': 2.0, 'sector': 1.0,
        }

        def _scale(component: str, raw: float) -> float:
            yaml_max = w.get(component)
            if yaml_max is None:
                return raw
            default_max = _DEFAULTS.get(component, 1.0)
            if default_max <= 0:
                return raw
            return raw * (yaml_max / default_max)

        # Calculate total score with config-based weight scaling
        breakdown.total_score = (
            _scale('dip', breakdown.dip_score) +
            _scale('gap', breakdown.gap_score) +
            _scale('rsi', breakdown.rsi_score) +
            _scale('stabilization', breakdown.stabilization_score) +
            _scale('volume', breakdown.volume_score) +
            _scale('trend', breakdown.trend_score) +
            _scale('macd', breakdown.macd_score) +
            _scale('stoch', breakdown.stoch_score) +
            _scale('keltner', breakdown.keltner_score) +
            _scale('vwap', breakdown.vwap_score) +
            _scale('market_context', breakdown.market_context_score) +
            _scale('sector', breakdown.sector_score)
        )

        # Apply sector_factor as multiplicative adjustment (Iter 4 trained)
        if w and resolved.sector_factor != 1.0:
            breakdown.total_score *= resolved.sector_factor

        breakdown.max_possible = resolved.max_possible if w else 24

        # Normalize score to 0-10 scale for fair cross-strategy comparison
        normalized_score = (breakdown.total_score / breakdown.max_possible) * 10 if breakdown.max_possible > 0 else 0

        # Determine signal strength (based on normalized 0-10 scale)
        if normalized_score >= 7:
            strength = SignalStrength.STRONG
        elif normalized_score >= 5:
            strength = SignalStrength.MODERATE
        elif normalized_score >= 3:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE

        # Calculate Entry/Stop/Target
        entry_price = current_price
        dip_low = dip_result[1].get('dip_low', min(lows[-5:]))
        stop_loss = dip_low * (1 - self.config.stop_below_dip_low_pct / 100)

        # Target: Recovery zu 50% des Dips
        pre_price = dip_result[1].get('pre_earnings_price', prices[-10])
        target_price = current_price + (pre_price - current_price) * (self.config.target_recovery_pct / 100)

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.LONG if normalized_score >= 3.5 else SignalType.NEUTRAL,
            strength=strength,
            score=round(normalized_score, 1),  # Normalized 0-10 score
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=" | ".join(reasons),
            details={
                'score_breakdown': breakdown.to_dict(),
                'raw_score': breakdown.total_score,
                'max_possible': breakdown.max_possible,
                'dip_info': dip_result[1],
                'gap_info': gap_info.to_dict() if gap_info.detected else None,
                'trend_info': trend_result[1],
                'rsi': breakdown.rsi_value,
                'stabilization': stab_result[1]
            },
            warnings=warnings
        )

    def _detect_earnings_dip(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        earnings_date: Optional[date],
        pre_earnings_price: Optional[float]
    ) -> Tuple[int, Dict[str, Any]]:
        """Detects earnings dip"""
        cfg = self.scoring_config.dip_detection
        lookback = cfg.lookback_days

        info = {
            'earnings_date': earnings_date,
            'lookback_days': lookback
        }

        # Determine pre-earnings price
        if pre_earnings_price:
            pre_price = pre_earnings_price
        else:
            if len(prices) >= lookback + 10:
                pre_price = max(prices[-(lookback + 10):-lookback])
            else:
                pre_price = max(prices[:-lookback]) if len(prices) > lookback else prices[0]

        info['pre_earnings_price'] = pre_price

        current_price = prices[-1]
        recent_lows = lows[-lookback:]
        dip_low = min(recent_lows)

        info['current_price'] = current_price
        info['dip_low'] = dip_low

        # Calculate dip
        dip_from_pre = (1 - dip_low / pre_price) * 100
        dip_from_current = (1 - current_price / pre_price) * 100

        info['dip_pct'] = dip_from_current
        info['dip_to_low_pct'] = dip_from_pre

        # Scoring
        if dip_from_current < cfg.min_dip_pct:
            info['reason'] = f"Dip too small ({dip_from_current:.1f}% < {cfg.min_dip_pct}%)"
            return 0, info

        if dip_from_current > cfg.max_dip_pct:
            info['reason'] = f"Dip too large ({dip_from_current:.1f}% > {cfg.max_dip_pct}%) - too risky"
            return 0, info

        # Score based on dip size
        if cfg.min_dip_pct <= dip_from_current <= cfg.ideal_max_dip_pct:
            return int(cfg.weight_ideal), info  # Ideal dip (5-10%)
        elif dip_from_current <= 15:
            return int(cfg.weight_moderate), info  # Moderate dip (10-15%)
        else:
            return int(cfg.weight_large), info  # Large dip (15-25%)

    def _detect_gap_down(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float]
    ) -> Tuple[int, GapInfo]:
        """Detects gap downs"""
        cfg = self.scoring_config.gap_analysis
        lookback = self.config.dip_lookback_days
        min_gap_pct = cfg.min_gap_pct

        gap_info = GapInfo()

        if len(prices) < lookback + 1 or len(highs) < lookback + 1:
            return 0, gap_info

        for i in range(1, lookback + 1):
            idx = -i
            prev_idx = -i - 1

            if abs(prev_idx) > len(lows):
                break

            current_high = highs[idx]
            prev_low = lows[prev_idx]
            prev_close = prices[prev_idx]

            if current_high < prev_low:
                gap_size = prev_low - current_high
                gap_pct = (gap_size / prev_close) * 100

                if gap_pct >= min_gap_pct:
                    gap_info.detected = True
                    gap_info.gap_day_index = i
                    gap_info.gap_size_pct = gap_pct
                    gap_info.gap_open = current_high
                    gap_info.prev_close = prev_close

                    current_price = prices[-1]
                    current_high_today = highs[-1]

                    if current_high_today >= prev_low:
                        gap_info.gap_filled = True
                        gap_info.fill_pct = 100.0
                    elif current_price > current_high:
                        recovery = current_price - current_high
                        gap_info.fill_pct = min(100.0, (recovery / gap_size) * 100)
                        gap_info.gap_filled = gap_info.fill_pct >= cfg.gap_fill_threshold

                    return int(cfg.weight_gap_detected), gap_info

            # Alternative: Closing price falls sharply
            current_close = prices[idx]
            if current_close < prev_low * (1 - min_gap_pct / 100):
                gap_size = prev_low - current_close
                gap_pct = (gap_size / prev_close) * 100

                if gap_pct >= min_gap_pct:
                    gap_info.detected = True
                    gap_info.gap_day_index = i
                    gap_info.gap_size_pct = gap_pct
                    gap_info.gap_open = current_close
                    gap_info.prev_close = prev_close

                    current_price = prices[-1]
                    if current_price >= prev_low:
                        gap_info.gap_filled = True
                        gap_info.fill_pct = 100.0
                    else:
                        recovery = current_price - current_close
                        if gap_size > 0:
                            gap_info.fill_pct = min(100.0, max(0, (recovery / gap_size) * 100))
                        gap_info.gap_filled = gap_info.fill_pct >= cfg.gap_fill_threshold

                    return int(cfg.weight_gap_detected), gap_info

        return 0, gap_info

    def _score_rsi_oversold(self, prices: List[float]) -> Tuple[int, float]:
        """RSI score for strong oversold condition"""
        period = RSI_PERIOD

        if len(prices) < period + 1:
            return 0, 50.0

        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_changes = changes[-period:]

        gains = [c for c in recent_changes if c > 0]
        losses = [-c for c in recent_changes if c < 0]

        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0.0001

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        cfg = self.scoring_config
        if rsi < cfg.rsi_extreme_oversold:
            return 2, rsi
        elif rsi < cfg.rsi_oversold:
            return 1, rsi
        else:
            return 0, rsi

    def _score_stabilization(self, lows: List[float]) -> Tuple[int, Dict[str, Any]]:
        """Checks if the price has stabilized"""
        cfg = self.scoring_config.stabilization

        if len(lows) < 5:
            return 0, {'days_without_new_low': 0}

        recent_lows = lows[-5:]
        min_low = min(recent_lows)
        min_index = recent_lows.index(min_low)
        days_since_low = len(recent_lows) - 1 - min_index

        info = {
            'dip_low': min_low,
            'days_without_new_low': days_since_low,
            'min_index': min_index
        }

        if days_since_low >= cfg.min_days_for_full_score:
            return int(cfg.weight_stable), info
        elif days_since_low >= 1:
            return int(cfg.weight_beginning), info
        else:
            return 0, info

    def _score_volume_normalization(self, volumes: List[int]) -> Tuple[int, Dict[str, Any]]:
        """Checks if panic volume is declining - extended"""
        if len(volumes) < 10:
            return 0, {'trend': 'unknown', 'reason': 'Insufficient data'}

        early_volume = sum(volumes[-VOLUME_RECENT_WINDOW:-3]) / 2
        current_volume = volumes[-1]
        avg_volume = sum(volumes[-VOLUME_AVG_PERIOD:-VOLUME_RECENT_WINDOW]) / (VOLUME_AVG_PERIOD - VOLUME_RECENT_WINDOW)

        multiplier = current_volume / avg_volume if avg_volume > 0 else 0

        info = {
            'early_volume': early_volume,
            'current_volume': current_volume,
            'avg_volume': avg_volume,
            'multiplier': multiplier
        }

        # Volume trend of the last N days
        recent_volumes = volumes[-VOLUME_RECENT_WINDOW:]
        if len(recent_volumes) >= 3:
            vol_trend = recent_volumes[-1] / recent_volumes[0] if recent_volumes[0] > 0 else 1
            if vol_trend < VOLUME_TREND_LOW:
                info['trend'] = 'normalizing'
            elif vol_trend > VOLUME_TREND_HIGH:
                info['trend'] = 'still_elevated'
            else:
                info['trend'] = 'stable'
        else:
            info['trend'] = 'unknown'

        score = 0

        # 1. Volume normalizing from spike (1 point)
        if early_volume > avg_volume * VOLUME_SPIKE_MULTIPLIER:
            if current_volume < early_volume * 0.6:
                score += 1
                info['reason'] = "Volume normalizing from spike"

        # 2. Volume trend is declining (1 point)
        if info['trend'] == 'normalizing':
            score += 1
            info['reason'] = info.get('reason', '') + " | Volume declining"

        if not info.get('reason'):
            info['reason'] = "Volume analysis"

        return score, info

    def _score_long_term_trend(self, prices: List[float]) -> Tuple[int, Dict[str, Any]]:
        """Long-term trend check"""
        sma_200 = sum(prices[-SMA_LONG:]) / SMA_LONG if len(prices) >= SMA_LONG else sum(prices) / len(prices)
        sma_50 = sum(prices[-SMA_MEDIUM:]) / SMA_MEDIUM if len(prices) >= SMA_MEDIUM else sum(prices) / len(prices)

        current = prices[-1]
        pre_dip = prices[-10] if len(prices) >= 10 else prices[0]

        info = {
            'sma_200': sma_200,
            'sma_50': sma_50,
            'current': current,
            'pre_dip': pre_dip
        }

        if pre_dip > sma_200:
            info['was_in_uptrend'] = True

            if current > sma_200:
                info['trend'] = 'still_above_sma200'
                return 2, info
            elif current > sma_200 * 0.95:
                info['trend'] = 'near_sma200'
                return 1, info
            else:
                info['trend'] = 'below_sma200'
                return 0, info
        else:
            info['was_in_uptrend'] = False
            info['trend'] = 'was_not_in_uptrend'
            return 0, info

    # =========================================================================
    # MACD RECOVERY SCORING (NEW)
    # =========================================================================

    def _calculate_macd(
        self,
        prices: List[float],
        fast: int = MACD_FAST,
        slow: int = MACD_SLOW,
        signal: int = MACD_SIGNAL
    ) -> Optional[MACDResult]:
        """Calculates MACD. Delegates to shared indicators library."""
        return calculate_macd(prices, fast_period=fast, slow_period=slow, signal_period=signal)

    def _score_macd_recovery(
        self,
        macd: Optional[MACDResult],
        prices: List[float]
    ) -> Tuple[float, str, str, bool]:
        """MACD Score for Recovery (0-2 points)"""
        if not macd:
            return 0, "No MACD data", "neutral", False

        cfg = self.scoring_config.macd

        # Check if histogram is turning up (Recovery signal)
        turning_up = False
        if len(prices) >= MACD_SLOW + MACD_SIGNAL + 2:  # Need enough data for MACD history
            prev_macd = self._calculate_macd(prices[:-1])
            if prev_macd and macd.histogram > prev_macd.histogram:
                turning_up = True

        if macd.crossover == 'bullish':
            return cfg.weight_bullish_cross, "MACD bullish crossover - recovery signal", "bullish_cross", True

        if turning_up and macd.histogram < 0:
            return cfg.weight_bullish, "MACD histogram turning up - early recovery", "recovering", True

        if macd.histogram > 0:
            return cfg.weight_bullish, "MACD histogram positive", "bullish", turning_up

        return 0, "MACD still bearish", "bearish", False

    # =========================================================================
    # STOCHASTIC SCORING (NEW)
    # =========================================================================

    def _calculate_stochastic(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        k_period: int = STOCH_K_PERIOD,
        d_period: int = STOCH_D_PERIOD
    ) -> Optional[StochasticResult]:
        """Calculates Stochastic Oscillator. Delegates to shared indicators library."""
        cfg = self.scoring_config.stochastic
        return calculate_stochastic(
            highs=highs, lows=lows, closes=prices,
            k_period=k_period, d_period=d_period, smooth=STOCH_SMOOTH,
            oversold=cfg.oversold_threshold, overbought=cfg.overbought_threshold
        )

    def _score_stochastic(self, stoch: Optional[StochasticResult]) -> Tuple[float, str, str]:
        """Stochastic Score (0-2 points)"""
        if not stoch:
            return 0, "No Stochastic data", "neutral"

        cfg = self.scoring_config.stochastic

        if stoch.zone == 'oversold':
            if stoch.crossover == 'bullish':
                return cfg.weight_oversold_cross, "Stoch oversold + bullish cross", "oversold_bullish_cross"
            return cfg.weight_oversold, f"Stoch oversold (K={stoch.k:.0f})", "oversold"

        if stoch.zone == 'overbought':
            return 0, f"Stoch overbought (K={stoch.k:.0f})", "overbought"

        return 0, f"Stoch neutral (K={stoch.k:.0f})", "neutral"

    # =========================================================================
    # KELTNER CHANNEL (NEW)
    # =========================================================================

    def _calculate_keltner_channel(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float]
    ) -> Optional[KeltnerChannelResult]:
        """Calculates Keltner Channel. Delegates to shared indicators library."""
        cfg = self.scoring_config.keltner
        return calculate_keltner_channel(
            prices=prices, highs=highs, lows=lows,
            ema_period=cfg.ema_period, atr_period=cfg.atr_period,
            atr_multiplier=cfg.atr_multiplier
        )

    def _score_keltner(
        self,
        keltner: KeltnerChannelResult,
        current_price: float
    ) -> Tuple[float, str]:
        """Keltner Channel Score for Earnings Dip (0-2 points)"""
        cfg = self.scoring_config.keltner
        position = keltner.price_position
        pct = keltner.percent_position

        if position == 'below_lower':
            return cfg.weight_below_lower, f"Price below Keltner Lower Band ({pct:.2f})"

        if position == 'near_lower':
            return cfg.weight_near_lower, f"Price near Keltner Lower Band ({pct:.2f})"

        if position == 'in_channel' and pct < KELTNER_NEUTRAL_LOW:
            return cfg.weight_mean_reversion * 0.5, f"Recovery in lower channel ({pct:.2f})"

        if position == 'above_upper':
            return 0, f"Price above Keltner Upper Band ({pct:.2f})"

        return 0, f"Price in neutral channel position ({pct:.2f})"

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _calculate_ema(self, values: List[float], period: int) -> Optional[List[float]]:
        """Calculates EMA. Delegates to shared indicators library."""
        if len(values) < period:
            return None
        return calculate_ema(values, period)

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = RSI_PERIOD  # ATR uses same default period as RSI (14)
    ) -> Optional[float]:
        """Calculates ATR (SMA-based). Delegates to shared indicators library."""
        return calculate_atr_simple(highs, lows, closes, period)
