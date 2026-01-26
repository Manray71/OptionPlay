# OptionPlay - Earnings Dip Analyzer
# ====================================
# Analysiert Kaufgelegenheiten nach Earnings-bedingten Dips
#
# Strategie: Kaufe wenn gute Aktie nach Earnings überreagiert abverkauft wird
# - Contrarian/Mean-Reversion Signal
# - Funktioniert bei Qualitätsaktien mit temporärem Sentiment-Schock
# - Risiko: Dip ist berechtigt (fundamentale Verschlechterung)

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
    from ..config.config_loader import EarningsDipScoringConfig
except ImportError:
    from models.base import TradeSignal, SignalType, SignalStrength
    from models.indicators import MACDResult, StochasticResult, KeltnerChannelResult
    from models.strategy_breakdowns import EarningsDipScoreBreakdown
    from config.config_loader import EarningsDipScoringConfig

logger = logging.getLogger(__name__)


@dataclass
class GapInfo:
    """Informationen über ein Gap Down"""
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
    """Konfiguration für Earnings Dip Analyzer (Legacy - für Rückwärtskompatibilität)"""
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


class EarningsDipAnalyzer(BaseAnalyzer):
    """
    Analysiert Aktien auf Kaufgelegenheiten nach Earnings-Dips.

    Scoring-Kriterien (erweitert):
    - Earnings-Dip (5-15%): 0-3 Punkte
    - Gap-Down bestätigt Earnings-Event: 0-1 Punkt
    - RSI stark oversold (< 30): 0-2 Punkte
    - Preis stabilisiert (keine neuen Lows): 0-2 Punkte
    - Volumen normalisiert: 0-2 Punkte
    - Langfristiger Aufwärtstrend (über SMA200): 0-2 Punkte
    - MACD Recovery Signal: 0-2 Punkte (NEU)
    - Stochastik Recovery: 0-2 Punkte (NEU)
    - Keltner Channel: 0-2 Punkte (NEU)

    Verwendung:
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
        return "Earnings Dip Buy - Kaufe nach übertriebenem Earnings-Abverkauf bei Qualitätsaktien"

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
        Analysiert ein Symbol auf Earnings-Dip-Kaufgelegenheit.
        """
        # Input-Validierung
        self.validate_inputs(prices, volumes, highs, lows, min_length=60)

        current_price = prices[-1]

        # Score Breakdown initialisieren
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
                dip_result[1].get('reason', 'Kein Earnings-Dip erkannt')
            )

        reasons.append(f"Earnings-Dip: -{breakdown.dip_pct:.1f}%")

        if breakdown.dip_pct > 15:
            warnings.append(f"Großer Dip (>{breakdown.dip_pct:.0f}%) - erhöhtes Risiko")

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
                reasons.append(f"Gap {breakdown.gap_fill_pct:.0f}% gefüllt")
        else:
            if self.config.analyze_gap:
                warnings.append("Kein Gap Down erkannt - möglicherweise kein Earnings-Event")

        # 3. RSI Oversold (0-2 Punkte)
        rsi_result = self._score_rsi_oversold(prices)
        breakdown.rsi_score = rsi_result[0]
        breakdown.rsi_value = rsi_result[1]
        breakdown.rsi_reason = f"RSI={breakdown.rsi_value:.1f}"

        if breakdown.rsi_score >= 2:
            reasons.append(f"Stark oversold (RSI {breakdown.rsi_value:.0f})")
        elif breakdown.rsi_score == 1:
            reasons.append(f"Oversold (RSI {breakdown.rsi_value:.0f})")

        # 4. Stabilisierung (0-2 Punkte)
        stab_result = self._score_stabilization(lows)
        breakdown.stabilization_score = stab_result[0]
        breakdown.days_without_new_low = stab_result[1].get('days_without_new_low', 0)
        breakdown.stabilization_reason = f"{breakdown.days_without_new_low} days without new low"

        if breakdown.stabilization_score > 0:
            reasons.append(f"Preis stabilisiert ({breakdown.days_without_new_low} Tage ohne neues Low)")
        else:
            warnings.append("Noch keine Stabilisierung - möglicherweise zu früh")

        # 5. Volumen-Normalisierung (0-2 Punkte) - erweitert
        vol_result = self._score_volume_normalization(volumes)
        breakdown.volume_score = vol_result[0]
        breakdown.volume_ratio = vol_result[1].get('multiplier', 0)
        breakdown.volume_trend = vol_result[1].get('trend', 'unknown')
        breakdown.volume_reason = vol_result[1].get('reason', '')

        if breakdown.volume_score > 0:
            reasons.append("Verkaufsdruck lässt nach")

        # 6. Langfristiger Trend (0-2 Punkte)
        trend_result = self._score_long_term_trend(prices)
        breakdown.trend_score = trend_result[0]
        breakdown.trend_status = trend_result[1].get('trend', 'unknown')
        breakdown.was_in_uptrend = trend_result[1].get('was_in_uptrend', False)
        breakdown.trend_reason = f"Trend: {breakdown.trend_status}"

        if breakdown.trend_score >= 2:
            reasons.append("Langfristiger Aufwärtstrend intakt")
        elif breakdown.trend_score == 0:
            warnings.append("Unter SMA200 - schwächerer langfristiger Trend")

        # 7. MACD Recovery Score (0-2 Punkte) - NEU
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

        # 8. Stochastik Recovery (0-2 Punkte) - NEU
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

        # 9. Keltner Channel (0-2 Punkte) - NEU
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

        # Total Score berechnen
        breakdown.total_score = (
            breakdown.dip_score +
            breakdown.gap_score +
            breakdown.rsi_score +
            breakdown.stabilization_score +
            breakdown.volume_score +
            breakdown.trend_score +
            breakdown.macd_score +
            breakdown.stoch_score +
            breakdown.keltner_score
        )
        breakdown.max_possible = self.scoring_config.max_score

        # Signal-Stärke bestimmen
        if breakdown.total_score >= 13:
            strength = SignalStrength.STRONG
        elif breakdown.total_score >= 9:
            strength = SignalStrength.MODERATE
        elif breakdown.total_score >= 6:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE

        # Entry/Stop/Target berechnen
        entry_price = current_price
        dip_low = dip_result[1].get('dip_low', min(lows[-5:]))
        stop_loss = dip_low * (1 - self.config.stop_below_dip_low_pct / 100)

        # Target: Recovery zu 50% des Dips
        pre_price = dip_result[1].get('pre_earnings_price', prices[-10])
        target_price = current_price + (pre_price - current_price) * (self.config.target_recovery_pct / 100)

        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.LONG if breakdown.total_score >= self.scoring_config.min_score_for_signal else SignalType.NEUTRAL,
            strength=strength,
            score=min(breakdown.total_score, self.scoring_config.max_score),
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            reason=" | ".join(reasons),
            details={
                'score_breakdown': breakdown.to_dict(),
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
        """Erkennt Earnings-Dip"""
        cfg = self.scoring_config.dip_detection
        lookback = cfg.lookback_days

        info = {
            'earnings_date': earnings_date,
            'lookback_days': lookback
        }

        # Pre-Earnings Preis bestimmen
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

        # Dip berechnen
        dip_from_pre = (1 - dip_low / pre_price) * 100
        dip_from_current = (1 - current_price / pre_price) * 100

        info['dip_pct'] = dip_from_current
        info['dip_to_low_pct'] = dip_from_pre

        # Scoring
        if dip_from_current < cfg.min_dip_pct:
            info['reason'] = f"Dip zu klein ({dip_from_current:.1f}% < {cfg.min_dip_pct}%)"
            return 0, info

        if dip_from_current > cfg.max_dip_pct:
            info['reason'] = f"Dip zu groß ({dip_from_current:.1f}% > {cfg.max_dip_pct}%) - zu riskant"
            return 0, info

        # Score basierend auf Dip-Größe
        if cfg.min_dip_pct <= dip_from_current <= cfg.ideal_max_dip_pct:
            return int(cfg.weight_ideal), info  # Idealer Dip (5-10%)
        elif dip_from_current <= 15:
            return int(cfg.weight_moderate), info  # Moderater Dip (10-15%)
        else:
            return int(cfg.weight_large), info  # Großer Dip (15-25%)

    def _detect_gap_down(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float]
    ) -> Tuple[int, GapInfo]:
        """Erkennt Gap Downs"""
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

            # Alternative: Schlusskurs fällt stark
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
        """RSI-Score für starke Oversold-Bedingung"""
        period = 14

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
        """Prüft ob sich der Preis stabilisiert hat"""
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
        """Prüft ob das Panik-Volumen nachlässt - erweitert"""
        if len(volumes) < 10:
            return 0, {'trend': 'unknown', 'reason': 'Insufficient data'}

        early_volume = sum(volumes[-5:-3]) / 2
        current_volume = volumes[-1]
        avg_volume = sum(volumes[-20:-5]) / 15

        multiplier = current_volume / avg_volume if avg_volume > 0 else 0

        info = {
            'early_volume': early_volume,
            'current_volume': current_volume,
            'avg_volume': avg_volume,
            'multiplier': multiplier
        }

        # Volume-Trend der letzten 5 Tage
        recent_volumes = volumes[-5:]
        if len(recent_volumes) >= 3:
            vol_trend = recent_volumes[-1] / recent_volumes[0] if recent_volumes[0] > 0 else 1
            if vol_trend < 0.7:
                info['trend'] = 'normalizing'
            elif vol_trend > 1.3:
                info['trend'] = 'still_elevated'
            else:
                info['trend'] = 'stable'
        else:
            info['trend'] = 'unknown'

        score = 0

        # 1. Volumen normalisiert sich von Spike (1 Punkt)
        if early_volume > avg_volume * 2:
            if current_volume < early_volume * 0.6:
                score += 1
                info['reason'] = "Volume normalizing from spike"

        # 2. Volume-Trend ist abnehmend (1 Punkt)
        if info['trend'] == 'normalizing':
            score += 1
            info['reason'] = info.get('reason', '') + " | Volume declining"

        if not info.get('reason'):
            info['reason'] = "Volume analysis"

        return score, info

    def _score_long_term_trend(self, prices: List[float]) -> Tuple[int, Dict[str, Any]]:
        """Langfristiger Trend-Check"""
        sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else sum(prices) / len(prices)
        sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sum(prices) / len(prices)

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
    # MACD RECOVERY SCORING (NEU)
    # =========================================================================

    def _calculate_macd(
        self,
        prices: List[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Optional[MACDResult]:
        """Berechnet MACD"""
        if len(prices) < slow + signal:
            return None

        ema_fast = self._calculate_ema(prices, fast)
        ema_slow = self._calculate_ema(prices, slow)

        if not ema_fast or not ema_slow:
            return None

        macd_line = [f - s for f, s in zip(ema_fast[-len(ema_slow):], ema_slow)]
        signal_line = self._calculate_ema(macd_line, signal)

        if not signal_line:
            return None

        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        histogram = current_macd - current_signal

        crossover = None
        if len(macd_line) >= 2 and len(signal_line) >= 2:
            prev_macd = macd_line[-2]
            prev_signal = signal_line[-2]

            if prev_macd < prev_signal and current_macd > current_signal:
                crossover = 'bullish'
            elif prev_macd > prev_signal and current_macd < current_signal:
                crossover = 'bearish'

        return MACDResult(
            macd_line=current_macd,
            signal_line=current_signal,
            histogram=histogram,
            crossover=crossover
        )

    def _score_macd_recovery(
        self,
        macd: Optional[MACDResult],
        prices: List[float]
    ) -> Tuple[float, str, str, bool]:
        """MACD Score für Recovery (0-2 Punkte)"""
        if not macd:
            return 0, "No MACD data", "neutral", False

        cfg = self.scoring_config.macd

        # Check if histogram is turning up (Recovery signal)
        turning_up = False
        if len(prices) >= 37:  # Need enough data for MACD history
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
    # STOCHASTIC SCORING (NEU)
    # =========================================================================

    def _calculate_stochastic(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float],
        k_period: int = 14,
        d_period: int = 3
    ) -> Optional[StochasticResult]:
        """Berechnet Stochastic Oscillator"""
        if len(prices) < k_period + d_period:
            return None

        k_values = []
        for i in range(k_period, len(prices) + 1):
            period_highs = highs[i-k_period:i]
            period_lows = lows[i-k_period:i]
            period_close = prices[i-1]

            highest_high = max(period_highs)
            lowest_low = min(period_lows)

            if highest_high == lowest_low:
                k_values.append(50.0)
            else:
                k = ((period_close - lowest_low) / (highest_high - lowest_low)) * 100
                k_values.append(k)

        if len(k_values) < d_period:
            return None

        d_values = []
        for i in range(d_period, len(k_values) + 1):
            d = sum(k_values[i-d_period:i]) / d_period
            d_values.append(d)

        current_k = k_values[-1]
        current_d = d_values[-1] if d_values else current_k

        cfg = self.scoring_config.stochastic
        if current_k < cfg.oversold_threshold:
            zone = 'oversold'
        elif current_k > cfg.overbought_threshold:
            zone = 'overbought'
        else:
            zone = 'neutral'

        crossover = None
        if len(k_values) >= 2 and len(d_values) >= 2:
            prev_k = k_values[-2]
            prev_d = d_values[-2]

            if prev_k < prev_d and current_k > current_d:
                crossover = 'bullish'
            elif prev_k > prev_d and current_k < current_d:
                crossover = 'bearish'

        return StochasticResult(
            k=current_k,
            d=current_d,
            crossover=crossover,
            zone=zone
        )

    def _score_stochastic(self, stoch: Optional[StochasticResult]) -> Tuple[float, str, str]:
        """Stochastic Score (0-2 Punkte)"""
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
    # KELTNER CHANNEL (NEU)
    # =========================================================================

    def _calculate_keltner_channel(
        self,
        prices: List[float],
        highs: List[float],
        lows: List[float]
    ) -> Optional[KeltnerChannelResult]:
        """Berechnet Keltner Channel"""
        cfg = self.scoring_config.keltner
        min_required = max(cfg.ema_period, cfg.atr_period) + 1

        if len(prices) < min_required:
            return None

        ema_values = self._calculate_ema(prices, cfg.ema_period)
        if not ema_values:
            return None
        current_ema = ema_values[-1]

        atr = self._calculate_atr(highs, lows, prices, cfg.atr_period)
        if atr is None or atr <= 0:
            return None

        band_width = atr * cfg.atr_multiplier
        upper = current_ema + band_width
        lower = current_ema - band_width

        current_price = prices[-1]
        channel_range = upper - lower

        if channel_range <= 0:
            return None

        percent_position = (current_price - current_ema) / band_width if band_width > 0 else 0

        if current_price > upper:
            price_position = 'above_upper'
        elif current_price < lower:
            price_position = 'below_lower'
        elif percent_position < -0.5:
            price_position = 'near_lower'
        elif percent_position > 0.5:
            price_position = 'near_upper'
        else:
            price_position = 'in_channel'

        channel_width_pct = (channel_range / current_price) * 100 if current_price > 0 else 0

        return KeltnerChannelResult(
            upper=upper,
            middle=current_ema,
            lower=lower,
            atr=atr,
            price_position=price_position,
            percent_position=percent_position,
            channel_width_pct=channel_width_pct
        )

    def _score_keltner(
        self,
        keltner: KeltnerChannelResult,
        current_price: float
    ) -> Tuple[float, str]:
        """Keltner Channel Score für Earnings Dip (0-2 Punkte)"""
        cfg = self.scoring_config.keltner
        position = keltner.price_position
        pct = keltner.percent_position

        if position == 'below_lower':
            return cfg.weight_below_lower, f"Preis unter Keltner Lower Band ({pct:.2f})"

        if position == 'near_lower':
            return cfg.weight_near_lower, f"Preis nahe Keltner Lower Band ({pct:.2f})"

        if position == 'in_channel' and pct < -0.3:
            return cfg.weight_mean_reversion * 0.5, f"Recovery im unteren Channel ({pct:.2f})"

        if position == 'above_upper':
            return 0, f"Preis über Keltner Upper Band ({pct:.2f})"

        return 0, f"Preis in neutraler Channel-Position ({pct:.2f})"

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _calculate_ema(self, values: List[float], period: int) -> Optional[List[float]]:
        """Berechnet Exponential Moving Average"""
        if len(values) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = [sum(values[:period]) / period]

        for value in values[period:]:
            ema.append((value - ema[-1]) * multiplier + ema[-1])

        return ema

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> Optional[float]:
        """Berechnet Average True Range (ATR)"""
        if len(highs) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(highs)):
            high = highs[i]
            low = lows[i]
            prev_close = closes[i - 1]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        return float(np.mean(true_ranges[-period:]))
