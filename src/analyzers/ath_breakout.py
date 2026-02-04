# OptionPlay - ATH Breakout Analyzer
# ====================================
# Analyzes breakouts to new all-time highs
#
# Strategy: Buy when stock breaks out of consolidation to new ATH
# - Strong momentum signal
# - Works best with quality stocks in uptrends
# - Risk: False breakouts, overbought conditions

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
import logging
import numpy as np

from .base import BaseAnalyzer
from .context import AnalysisContext

try:
    from ..models.base import TradeSignal, SignalType, SignalStrength
    from ..models.indicators import MACDResult, KeltnerChannelResult
    from ..models.strategy_breakdowns import ATHBreakoutScoreBreakdown
    from ..config.config_loader import ATHBreakoutScoringConfig
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength
    from models.indicators import MACDResult, KeltnerChannelResult
    from models.strategy_breakdowns import ATHBreakoutScoreBreakdown
    from config.config_loader import ATHBreakoutScoringConfig

logger = logging.getLogger(__name__)

# Import S/R analysis
try:
    from ..indicators.support_resistance import get_nearest_sr_levels
except ImportError:
    from indicators.support_resistance import get_nearest_sr_levels

# Import shared indicators
try:
    from ..indicators.momentum import calculate_macd
    from ..indicators.trend import calculate_ema
    from ..indicators.volatility import calculate_atr_simple, calculate_keltner_channel
except ImportError:
    from indicators.momentum import calculate_macd
    from indicators.trend import calculate_ema
    from indicators.volatility import calculate_atr_simple, calculate_keltner_channel

# Import Feature Scoring Mixin (NEW from Feature Engineering)
try:
    from .feature_scoring_mixin import FeatureScoringMixin
except ImportError:
    from analyzers.feature_scoring_mixin import FeatureScoringMixin


@dataclass
class ATHBreakoutConfig:
    """Configuration for ATH Breakout Analyzer (Legacy - for backward compatibility)"""
    # ATH Detection
    ath_lookback_days: int = 252  # 1 year for ATH
    consolidation_days: int = 20  # Minimum consolidation time
    breakout_threshold_pct: float = 1.0  # Min % above old ATH

    # Multi-Day Confirmation (NEW - P1-B)
    confirmation_days: int = 2  # Breakout must hold N days above ATH
    confirmation_threshold_pct: float = 0.5  # Min % above ATH during confirmation

    # Volume Confirmation
    volume_spike_multiplier: float = 1.5  # Volume must be 1.5x average
    volume_avg_period: int = 20

    # Technical Filters
    rsi_max: float = 80.0  # Don't buy if too overbought
    rsi_period: int = 14
    min_uptrend_days: int = 50  # SMA50 must point upward

    # Scoring
    max_score: int = 10
    min_score_for_signal: int = 6


class ATHBreakoutAnalyzer(BaseAnalyzer, FeatureScoringMixin):
    """
    Analyzes stocks for ATH breakouts.

    Scoring criteria (extended):
    - ATH breakout (new high after consolidation): 0-3 points
    - Volume confirmation: 0-2 points
    - Strong uptrend (SMA20 > SMA50 > SMA200): 0-2 points
    - RSI not overbought (< 70): 0-1 point
    - Relative Strength (outperforming SPY): 0-2 points
    - MACD signal: 0-2 points (NEW)
    - Momentum/ROC: 0-2 points (NEW)
    - Keltner Channel (Breakout above Upper): 0-2 points (NEW)

    Usage:
        analyzer = ATHBreakoutAnalyzer()
        signal = analyzer.analyze("AAPL", prices, volumes, highs, lows)

        if signal.is_actionable:
            print(f"Breakout Signal: {signal.score}/16")
    """

    def __init__(
        self,
        config: Optional[ATHBreakoutConfig] = None,
        scoring_config: Optional[ATHBreakoutScoringConfig] = None
    ):
        self.config = config or ATHBreakoutConfig()
        self.scoring_config = scoring_config or ATHBreakoutScoringConfig()

    @property
    def strategy_name(self) -> str:
        return "ath_breakout"

    @property
    def description(self) -> str:
        return "All-Time-High Breakout - Buy on breakout to new ATH with volume confirmation"

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

        Args:
            symbol: Ticker symbol
            prices: Closing prices (oldest first)
            volumes: Daily volume
            highs: Daily highs
            lows: Daily lows
            spy_prices: Optional SPY prices for Relative Strength
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            TradeSignal with breakout rating
        """
        # Input validation
        min_data = max(self.config.ath_lookback_days, 60)
        self.validate_inputs(prices, volumes, highs, lows, min_length=min_data)

        current_price = prices[-1]
        current_high = highs[-1]

        # Initialize score breakdown
        breakdown = ATHBreakoutScoreBreakdown()
        reasons = []
        warnings = []

        # 1. ATH-Breakout Detection (0-3 Punkte) mit Multi-Day Confirmation
        ath_result = self._score_ath_breakout(highs, current_high, prices)
        breakdown.ath_score = ath_result[0]
        breakdown.ath_old = ath_result[1].get('old_ath', 0)
        breakdown.ath_current = ath_result[1].get('current_high', 0)
        breakdown.ath_pct_above = ath_result[1].get('pct_above_old', 0)
        breakdown.ath_had_consolidation = ath_result[1].get('had_consolidation', False)

        # NEW: Confirmation status in breakdown
        confirmation_info = ath_result[1].get('confirmation')
        if confirmation_info:
            breakdown.ath_reason = f"ATH Score: {breakdown.ath_score} ({confirmation_info.get('status', 'unknown')})"
        else:
            breakdown.ath_reason = f"ATH Score: {breakdown.ath_score}"

        if breakdown.ath_score > 0:
            reason_text = f"Neues {ath_result[1]['lookback']}-Tage-Hoch (+{breakdown.ath_pct_above:.1f}%)"

            # Warning for unconfirmed breakout
            if confirmation_info and confirmation_info.get('status') == 'unconfirmed':
                days_req = confirmation_info.get('confirmation_days_required', 2)
                days_above = confirmation_info.get('days_close_above_ath', 0)
                warnings.append(f"⚠️ Unconfirmed breakout - only {days_above}/{days_req} days above ATH")
                reason_text += " (unconfirmed)"

            reasons.append(reason_text)
        else:
            # No breakout = neutral signal
            return self.create_neutral_signal(
                symbol, current_price,
                f"No ATH breakout. Currently {ath_result[1].get('pct_below_ath', 0):.1f}% below ATH"
            )

        # 2. Volume confirmation (0-2 points)
        vol_result = self._score_volume_confirmation(volumes)
        breakdown.volume_score = vol_result[0]
        breakdown.volume_ratio = vol_result[1].get('multiplier', 0)
        breakdown.volume_trend = vol_result[1].get('trend', 'unknown')
        breakdown.volume_reason = vol_result[1].get('reason', '')

        if breakdown.volume_score > 0:
            reasons.append(f"Volume {breakdown.volume_ratio:.1f}x above average")
        else:
            warnings.append("Weak volume confirmation")

        # 3. Trend analysis (0-2 points)
        trend_result = self._score_trend(prices)
        breakdown.trend_score = trend_result[0]
        breakdown.trend_status = trend_result[1].get('trend', 'unknown')
        breakdown.trend_reason = f"Trend: {breakdown.trend_status}"

        if breakdown.trend_score >= 2:
            reasons.append("Strong uptrend (SMA20 > SMA50 > SMA200)")
        elif breakdown.trend_score == 1:
            reasons.append("Moderate uptrend")

        # 4. RSI Check (0-1 Punkt)
        rsi_result = self._score_rsi(prices)
        breakdown.rsi_score = rsi_result[0]
        breakdown.rsi_value = rsi_result[1]
        breakdown.rsi_reason = f"RSI={breakdown.rsi_value:.1f}"

        if breakdown.rsi_score == 0:
            warnings.append(f"RSI overbought ({breakdown.rsi_value:.0f})")

        # 5. Relative Strength (0-2 points)
        if spy_prices and len(spy_prices) >= 20:
            rs_result = self._score_relative_strength(prices, spy_prices)
            breakdown.rs_score = rs_result[0]
            breakdown.rs_outperformance = rs_result[1].get('outperformance', 0)
            breakdown.rs_reason = f"RS: {breakdown.rs_outperformance:.1f}% vs SPY"

            if breakdown.rs_score > 0:
                reasons.append(f"Relative Strength: +{breakdown.rs_outperformance:.1f}% vs SPY")

        # 6. MACD Score (0-2 points) - NEW
        macd_result = self._calculate_macd(prices)
        macd_score_result = self._score_macd(macd_result)
        breakdown.macd_score = macd_score_result[0]
        breakdown.macd_signal = macd_score_result[2]
        breakdown.macd_histogram = macd_result.histogram if macd_result else 0
        breakdown.macd_reason = macd_score_result[1]

        if breakdown.macd_score >= 2:
            reasons.append("MACD bullish cross")
        elif breakdown.macd_score > 0:
            reasons.append("MACD bullish momentum")

        # 7. Momentum/ROC Score (0-2 points) - NEW
        momentum_result = self._score_momentum(prices)
        breakdown.momentum_score = momentum_result[0]
        breakdown.momentum_roc = momentum_result[1]
        breakdown.momentum_reason = momentum_result[2]

        if breakdown.momentum_score >= 2:
            reasons.append(f"Strong momentum (ROC: {breakdown.momentum_roc:.1f}%)")
        elif breakdown.momentum_score > 0:
            reasons.append(f"Positive momentum (ROC: {breakdown.momentum_roc:.1f}%)")

        # 8. Keltner Channel (0-2 points) - NEW (Breakout above upper band)
        keltner_result = self._calculate_keltner_channel(prices, highs, lows)
        if keltner_result:
            keltner_score_result = self._score_keltner_breakout(keltner_result, current_price)
            breakdown.keltner_score = keltner_score_result[0]
            breakdown.keltner_position = keltner_result.price_position
            breakdown.keltner_percent = keltner_result.percent_position
            breakdown.keltner_reason = keltner_score_result[1]

            if breakdown.keltner_score >= 2:
                reasons.append("Breakout above Keltner upper band")
            elif breakdown.keltner_score > 0:
                reasons.append("Near Keltner upper band")

        # NEW: Apply Feature Engineering scores (VWAP, Market Context, Sector, Gap)
        self._apply_feature_scores(breakdown, symbol, prices, volumes, highs, lows, context)

        # Calculate total score
        breakdown.total_score = (
            breakdown.ath_score +
            breakdown.volume_score +
            breakdown.trend_score +
            breakdown.rsi_score +
            breakdown.rs_score +
            breakdown.macd_score +
            breakdown.momentum_score +
            breakdown.keltner_score +
            breakdown.vwap_score +          # Feature Engineering
            breakdown.market_context_score + # Feature Engineering
            breakdown.sector_score +         # Feature Engineering
            breakdown.gap_score             # Validated with 174k+ events
        )
        breakdown.max_possible = 23  # +1 for gap score

        # Normalize score to 0-10 scale for fair cross-strategy comparison
        normalized_score = (breakdown.total_score / breakdown.max_possible) * 10

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
        stop_loss = self._calculate_stop_loss(lows, current_price)
        target_price = self._calculate_target(current_price, stop_loss)

        # Extended S/R analysis with 12-month lookback
        sr_levels = get_nearest_sr_levels(
            current_price=current_price,
            prices=prices,
            highs=highs,
            lows=lows,
            volumes=volumes,
            lookback=252,  # 12 months
            num_levels=3
        )

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
                'ath_info': ath_result[1],
                'trend_info': trend_result[1],
                'rsi': breakdown.rsi_value,
                'sr_levels': sr_levels  # Extended S/R with 12-month lookback
            },
            warnings=warnings
        )

    def _check_breakout_confirmation(
        self,
        prices: List[float],
        highs: List[float],
        ath_price: float,
        confirmation_days: int = 2
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Checks if breakout has been confirmed for N days.

        Single-day breakouts often lead to false positives.
        Price must stay 2-3 days above ATH.

        Args:
            prices: Closing prices (oldest first)
            highs: Daily highs
            ath_price: Old ATH (level to beat)
            confirmation_days: Number of days for confirmation

        Returns:
            Tuple of (is_confirmed, confirmation_score, info)
            - is_confirmed: True if breakout confirmed
            - confirmation_score: 0.0-1.0 (partial credit)
            - info: Confirmation details
        """
        info = {
            'confirmation_days_required': confirmation_days,
            'ath_price': ath_price,
        }

        if len(prices) < confirmation_days + 1:
            info['status'] = 'insufficient_data'
            return False, 0.0, info

        # Check the last N days (excluding today)
        # We check if the closing prices of the last N days were above ATH
        recent_closes = prices[-(confirmation_days + 1):-1]  # N Tage vor heute
        recent_highs = highs[-(confirmation_days + 1):-1]

        days_above_ath = sum(1 for p in recent_closes if p > ath_price)
        days_high_above = sum(1 for h in recent_highs if h > ath_price)

        info['days_close_above_ath'] = days_above_ath
        info['days_high_above_ath'] = days_high_above
        info['recent_closes'] = recent_closes
        info['closes_vs_ath'] = [round(((p / ath_price) - 1) * 100, 2) for p in recent_closes]

        # Confirmation ratio
        confirmation_ratio = days_above_ath / confirmation_days

        # Full confirmation: All N days above ATH
        is_confirmed = days_above_ath >= confirmation_days

        if is_confirmed:
            # Bonus: How far above ATH on average?
            avg_above_pct = sum(((p / ath_price) - 1) * 100 for p in recent_closes) / len(recent_closes)
            info['avg_above_pct'] = avg_above_pct
            info['status'] = 'confirmed'

            # Score: Full score + bonus for strong confirmation
            # 2% above ATH = maximum bonus
            bonus = min(1.0, avg_above_pct / 2.0) if avg_above_pct > 0 else 0
            confirmation_score = 1.0 + (bonus * 0.5)  # Max 1.5
        else:
            info['status'] = 'unconfirmed'
            # Partial credit für teilweise Bestätigung
            confirmation_score = confirmation_ratio * 0.5  # Max 0.5 bei unbestätigt

        return is_confirmed, confirmation_score, info

    def _score_ath_breakout(
        self,
        highs: List[float],
        current_high: float,
        prices: Optional[List[float]] = None
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Checks for ATH breakout with multi-day confirmation.

        New (P1-B): Single-day breakouts are scored lower.
        Confirmed breakouts (2+ days above ATH) receive full score.
        """
        lookback = min(self.config.ath_lookback_days, len(highs) - 1)

        # Old ATH: Maximum of highs BEFORE the consolidation period
        consolidation_start = -self.config.consolidation_days - 1
        if abs(consolidation_start) >= len(highs):
            consolidation_start = -len(highs) + 1

        # Old ATH = Maximum before consolidation
        old_ath = max(highs[-lookback:consolidation_start])

        # Check if new ATH
        threshold = old_ath * (1 + self.config.breakout_threshold_pct / 100)

        info = {
            'lookback': lookback,
            'old_ath': old_ath,
            'current_high': current_high,
            'threshold': threshold,
            'confirmation': None
        }

        if current_high >= threshold:
            # New ATH!
            pct_above = ((current_high / old_ath) - 1) * 100
            info['pct_above_old'] = pct_above

            # Check consolidation (not already at ATH in recent days)
            consolidation_highs = highs[consolidation_start:-1]
            recent_ath = max(consolidation_highs) if consolidation_highs else current_high

            if recent_ath < old_ath * 0.98:  # Was at least 2% below ATH
                info['had_consolidation'] = True
                base_score = 3
            else:
                info['had_consolidation'] = False
                base_score = 2  # ATH but without consolidation

            # NEW (P1-B): Multi-Day Confirmation Check
            if prices and len(prices) >= self.config.confirmation_days + 1:
                is_confirmed, conf_score, conf_info = self._check_breakout_confirmation(
                    prices=prices,
                    highs=highs,
                    ath_price=old_ath,
                    confirmation_days=self.config.confirmation_days
                )
                info['confirmation'] = conf_info

                if not is_confirmed:
                    # Unconfirmed breakout: Reduce score
                    # 3 points -> 1.5-2 points (50% reduction)
                    adjusted_score = int(base_score * 0.5 + conf_score)
                    info['score_adjustment'] = 'reduced_unconfirmed'
                    info['original_score'] = base_score
                    logger.debug(
                        f"ATH Breakout unconfirmed: score {base_score} -> {adjusted_score}"
                    )
                    return adjusted_score, info
                else:
                    # Confirmed breakout: Bonus possible
                    bonus = int(conf_score - 1.0) if conf_score > 1.0 else 0
                    adjusted_score = min(base_score + bonus, 3)  # Max 3 Punkte
                    info['score_adjustment'] = 'confirmed'
                    return adjusted_score, info

            # No price data for confirmation - standard score
            return base_score, info
        else:
            pct_below = ((old_ath / current_high) - 1) * 100
            info['pct_below_ath'] = pct_below
            return 0, info

    def _score_volume_confirmation(
        self,
        volumes: List[int]
    ) -> Tuple[int, Dict[str, Any]]:
        """Checks volume confirmation with trend analysis"""
        avg_period = self.config.volume_avg_period

        if len(volumes) < avg_period + 1:
            return 0, {'trend': 'unknown', 'reason': 'Insufficient data'}

        avg_volume = sum(volumes[-avg_period-1:-1]) / avg_period
        current_volume = volumes[-1]

        multiplier = current_volume / avg_volume if avg_volume > 0 else 0

        info = {
            'current_volume': current_volume,
            'avg_volume': avg_volume,
            'multiplier': multiplier
        }

        # Volume trend of the last 5 days (for breakout should increase)
        recent_volumes = volumes[-5:]
        if len(recent_volumes) >= 3:
            vol_trend = recent_volumes[-1] / recent_volumes[0] if recent_volumes[0] > 0 else 1
            if vol_trend > 1.3:
                info['trend'] = 'increasing'
            elif vol_trend < 0.7:
                info['trend'] = 'decreasing'
            else:
                info['trend'] = 'stable'
        else:
            info['trend'] = 'unknown'

        # Scoring: High volume is important for breakout
        cfg = self.scoring_config
        if multiplier >= cfg.volume_strong_multiplier:
            info['reason'] = "Very strong volume confirms breakout"
            return 2, info
        elif multiplier >= cfg.volume_spike_multiplier:
            info['reason'] = "Good volume confirms breakout"
            return 1, info
        else:
            info['reason'] = "Weak volume - breakout may fail"
            return 0, info

    def _score_trend(self, prices: List[float]) -> Tuple[int, Dict[str, Any]]:
        """Analyzes trend via SMAs"""
        sma_20 = sum(prices[-20:]) / 20
        sma_50 = sum(prices[-50:]) / 50
        sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else sum(prices) / len(prices)

        current = prices[-1]

        info = {
            'sma_20': sma_20,
            'sma_50': sma_50,
            'sma_200': sma_200,
            'price': current
        }

        score = 0

        # Price above all SMAs
        if current > sma_20 > sma_50 > sma_200:
            score = 2
            info['trend'] = 'strong_uptrend'
        elif current > sma_50 > sma_200:
            score = 1
            info['trend'] = 'uptrend'
        elif current > sma_200:
            score = 0
            info['trend'] = 'weak_uptrend'
        else:
            score = 0
            info['trend'] = 'downtrend'

        return score, info

    def _score_rsi(self, prices: List[float]) -> Tuple[int, float]:
        """Calculates RSI and scores (not overbought = good)"""
        period = self.config.rsi_period

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

        # Not overbought = good for breakout
        cfg = self.scoring_config
        if rsi < cfg.rsi_ideal_max:
            return 1, rsi
        else:
            return 0, rsi

    def _score_relative_strength(
        self,
        prices: List[float],
        spy_prices: List[float]
    ) -> Tuple[int, Dict[str, float]]:
        """Compares performance with SPY"""
        cfg = self.scoring_config.relative_strength
        period = cfg.lookback_days

        stock_return = (prices[-1] / prices[-period] - 1) * 100
        spy_return = (spy_prices[-1] / spy_prices[-period] - 1) * 100

        outperformance = stock_return - spy_return

        info = {
            'stock_return': stock_return,
            'spy_return': spy_return,
            'outperformance': outperformance
        }

        if outperformance > cfg.strong_threshold:
            return 2, info
        elif outperformance > cfg.moderate_threshold:
            return 1, info
        else:
            return 0, info

    def _score_momentum(self, prices: List[float]) -> Tuple[float, float, str]:
        """Calculates Momentum/Rate of Change Score"""
        cfg = self.scoring_config.momentum
        period = cfg.roc_period

        if len(prices) < period + 1:
            return 0, 0, "Insufficient data"

        roc = ((prices[-1] / prices[-period]) - 1) * 100

        if roc > cfg.strong_threshold:
            return cfg.weight_strong_momentum, roc, f"Strong momentum: ROC {roc:.1f}%"
        elif roc > cfg.moderate_threshold:
            return cfg.weight_moderate_momentum, roc, f"Moderate momentum: ROC {roc:.1f}%"
        elif roc > 0:
            return 0, roc, f"Weak momentum: ROC {roc:.1f}%"
        else:
            return 0, roc, f"Negative momentum: ROC {roc:.1f}%"

    # =========================================================================
    # MACD SCORING (NEW)
    # =========================================================================

    def _calculate_macd(
        self,
        prices: List[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Optional[MACDResult]:
        """Calculates MACD. Delegates to shared indicators library."""
        return calculate_macd(prices, fast_period=fast, slow_period=slow, signal_period=signal)

    def _score_macd(self, macd: Optional[MACDResult]) -> Tuple[float, str, str]:
        """MACD Score for Breakout (0-2 points)"""
        if not macd:
            return 0, "No MACD data", "neutral"

        cfg = self.scoring_config.macd

        # For breakout: Bullish MACD is confirmation
        if macd.crossover == 'bullish':
            return cfg.weight_bullish_cross, "MACD bullish crossover confirms breakout", "bullish_cross"

        if macd.histogram > 0 and macd.macd_line > 0:
            return cfg.weight_bullish, "MACD positive momentum", "bullish"

        if macd.histogram > 0:
            return cfg.weight_bullish * 0.5, "MACD histogram positive", "bullish_weak"

        return 0, "MACD not confirming breakout", "neutral"

    # =========================================================================
    # KELTNER CHANNEL (NEW - for Breakout)
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

    def _score_keltner_breakout(
        self,
        keltner: KeltnerChannelResult,
        current_price: float
    ) -> Tuple[float, str]:
        """Keltner Channel Score for Breakout (0-2 points) - UPPER Band"""
        cfg = self.scoring_config.keltner
        position = keltner.price_position
        pct = keltner.percent_position

        # For breakout: ABOVE the upper band is bullish
        if position == 'above_upper':
            return cfg.weight_above_upper, f"Breakout above Keltner Upper Band ({pct:.2f})"

        if position == 'near_upper':
            return cfg.weight_near_upper, f"Near Keltner Upper Band ({pct:.2f})"

        if position == 'in_channel' and pct > 0.3:
            return cfg.weight_near_upper * 0.5, f"Upper channel area ({pct:.2f})"

        if position == 'below_lower':
            return 0, f"Below Keltner Lower Band ({pct:.2f}) - not a breakout"

        return 0, f"Neutral channel position ({pct:.2f})"

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
        period: int = 14
    ) -> Optional[float]:
        """Calculates ATR (SMA-based). Delegates to shared indicators library."""
        return calculate_atr_simple(highs, lows, closes, period)

    def _calculate_stop_loss(
        self,
        lows: List[float],
        current_price: float
    ) -> float:
        """Calculates stop-loss below last swing low"""
        # Last 10-day low as support
        recent_low = min(lows[-10:])

        # Stop 1% below support
        stop = recent_low * 0.99

        # Max 5% below current price
        max_stop = current_price * 0.95

        return max(stop, max_stop)

    def _calculate_target(
        self,
        entry: float,
        stop: float
    ) -> float:
        """Calculates target with 2:1 Risk/Reward"""
        risk = entry - stop
        return entry + (risk * 2)
