# OptionPlay - ATH Breakout Analyzer
# ====================================
# Analysiert Ausbrüche auf neue All-Time-Highs
#
# Strategie: Kaufe wenn Aktie aus Konsolidierung auf neues ATH ausbricht
# - Starkes Momentum-Signal
# - Funktioniert am besten bei Qualitätsaktien in Aufwärtstrends
# - Risiko: False Breakouts, überkaufte Bedingungen

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


@dataclass
class ATHBreakoutConfig:
    """Konfiguration für ATH Breakout Analyzer (Legacy - für Rückwärtskompatibilität)"""
    # ATH Detection
    ath_lookback_days: int = 252  # 1 Jahr für ATH
    consolidation_days: int = 20  # Mindest-Konsolidierungszeit
    breakout_threshold_pct: float = 1.0  # Min % über altem ATH

    # Volume Confirmation
    volume_spike_multiplier: float = 1.5  # Volumen muss 1.5x Durchschnitt sein
    volume_avg_period: int = 20

    # Technical Filters
    rsi_max: float = 80.0  # Nicht kaufen wenn zu überkauft
    rsi_period: int = 14
    min_uptrend_days: int = 50  # SMA50 muss aufwärts zeigen

    # Scoring
    max_score: int = 10
    min_score_for_signal: int = 6


class ATHBreakoutAnalyzer(BaseAnalyzer):
    """
    Analysiert Aktien auf ATH-Breakouts.

    Scoring-Kriterien (erweitert):
    - ATH-Breakout (neues Hoch nach Konsolidierung): 0-3 Punkte
    - Volumen-Bestätigung: 0-2 Punkte
    - Starker Aufwärtstrend (SMA20 > SMA50 > SMA200): 0-2 Punkte
    - RSI nicht überkauft (< 70): 0-1 Punkt
    - Relative Stärke (besser als SPY): 0-2 Punkte
    - MACD-Signal: 0-2 Punkte (NEU)
    - Momentum/ROC: 0-2 Punkte (NEU)
    - Keltner Channel (Breakout über Upper): 0-2 Punkte (NEU)

    Verwendung:
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
        return "All-Time-High Breakout - Kaufe bei Ausbruch auf neues ATH mit Volumen-Bestätigung"

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
        Analysiert ein Symbol auf ATH-Breakout.

        Args:
            symbol: Ticker-Symbol
            prices: Schlusskurse (älteste zuerst)
            volumes: Tagesvolumen
            highs: Tageshochs
            lows: Tagestiefs
            spy_prices: Optional SPY-Preise für Relative Strength
            context: Optional pre-calculated AnalysisContext for performance

        Returns:
            TradeSignal mit Breakout-Bewertung
        """
        # Input-Validierung
        min_data = max(self.config.ath_lookback_days, 60)
        self.validate_inputs(prices, volumes, highs, lows, min_length=min_data)

        current_price = prices[-1]
        current_high = highs[-1]

        # Score Breakdown initialisieren
        breakdown = ATHBreakoutScoreBreakdown()
        reasons = []
        warnings = []

        # 1. ATH-Breakout Detection (0-3 Punkte)
        ath_result = self._score_ath_breakout(highs, current_high)
        breakdown.ath_score = ath_result[0]
        breakdown.ath_old = ath_result[1].get('old_ath', 0)
        breakdown.ath_current = ath_result[1].get('current_high', 0)
        breakdown.ath_pct_above = ath_result[1].get('pct_above_old', 0)
        breakdown.ath_had_consolidation = ath_result[1].get('had_consolidation', False)
        breakdown.ath_reason = f"ATH Score: {breakdown.ath_score}"

        if breakdown.ath_score > 0:
            reasons.append(f"Neues {ath_result[1]['lookback']}-Tage-Hoch (+{breakdown.ath_pct_above:.1f}%)")
        else:
            # Kein Breakout = neutrales Signal
            return self.create_neutral_signal(
                symbol, current_price,
                f"Kein ATH-Breakout. Aktuell {ath_result[1].get('pct_below_ath', 0):.1f}% unter ATH"
            )

        # 2. Volumen-Bestätigung (0-2 Punkte)
        vol_result = self._score_volume_confirmation(volumes)
        breakdown.volume_score = vol_result[0]
        breakdown.volume_ratio = vol_result[1].get('multiplier', 0)
        breakdown.volume_trend = vol_result[1].get('trend', 'unknown')
        breakdown.volume_reason = vol_result[1].get('reason', '')

        if breakdown.volume_score > 0:
            reasons.append(f"Volumen {breakdown.volume_ratio:.1f}x über Durchschnitt")
        else:
            warnings.append("Schwache Volumen-Bestätigung")

        # 3. Trend-Analyse (0-2 Punkte)
        trend_result = self._score_trend(prices)
        breakdown.trend_score = trend_result[0]
        breakdown.trend_status = trend_result[1].get('trend', 'unknown')
        breakdown.trend_reason = f"Trend: {breakdown.trend_status}"

        if breakdown.trend_score >= 2:
            reasons.append("Starker Aufwärtstrend (SMA20 > SMA50 > SMA200)")
        elif breakdown.trend_score == 1:
            reasons.append("Moderater Aufwärtstrend")

        # 4. RSI Check (0-1 Punkt)
        rsi_result = self._score_rsi(prices)
        breakdown.rsi_score = rsi_result[0]
        breakdown.rsi_value = rsi_result[1]
        breakdown.rsi_reason = f"RSI={breakdown.rsi_value:.1f}"

        if breakdown.rsi_score == 0:
            warnings.append(f"RSI überkauft ({breakdown.rsi_value:.0f})")

        # 5. Relative Strength (0-2 Punkte)
        if spy_prices and len(spy_prices) >= 20:
            rs_result = self._score_relative_strength(prices, spy_prices)
            breakdown.rs_score = rs_result[0]
            breakdown.rs_outperformance = rs_result[1].get('outperformance', 0)
            breakdown.rs_reason = f"RS: {breakdown.rs_outperformance:.1f}% vs SPY"

            if breakdown.rs_score > 0:
                reasons.append(f"Relative Stärke: +{breakdown.rs_outperformance:.1f}% vs SPY")

        # 6. MACD Score (0-2 Punkte) - NEU
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

        # 7. Momentum/ROC Score (0-2 Punkte) - NEU
        momentum_result = self._score_momentum(prices)
        breakdown.momentum_score = momentum_result[0]
        breakdown.momentum_roc = momentum_result[1]
        breakdown.momentum_reason = momentum_result[2]

        if breakdown.momentum_score >= 2:
            reasons.append(f"Strong momentum (ROC: {breakdown.momentum_roc:.1f}%)")
        elif breakdown.momentum_score > 0:
            reasons.append(f"Positive momentum (ROC: {breakdown.momentum_roc:.1f}%)")

        # 8. Keltner Channel (0-2 Punkte) - NEU (Breakout über oberes Band)
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

        # Total Score berechnen
        breakdown.total_score = (
            breakdown.ath_score +
            breakdown.volume_score +
            breakdown.trend_score +
            breakdown.rsi_score +
            breakdown.rs_score +
            breakdown.macd_score +
            breakdown.momentum_score +
            breakdown.keltner_score
        )
        breakdown.max_possible = self.scoring_config.max_score

        # Signal-Stärke bestimmen
        if breakdown.total_score >= 12:
            strength = SignalStrength.STRONG
        elif breakdown.total_score >= 8:
            strength = SignalStrength.MODERATE
        elif breakdown.total_score >= 5:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NONE

        # Entry/Stop/Target berechnen
        entry_price = current_price
        stop_loss = self._calculate_stop_loss(lows, current_price)
        target_price = self._calculate_target(current_price, stop_loss)

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
                'ath_info': ath_result[1],
                'trend_info': trend_result[1],
                'rsi': breakdown.rsi_value
            },
            warnings=warnings
        )

    def _score_ath_breakout(
        self,
        highs: List[float],
        current_high: float
    ) -> Tuple[int, Dict[str, Any]]:
        """Prüft auf ATH-Breakout"""
        lookback = min(self.config.ath_lookback_days, len(highs) - 1)

        # Altes ATH: Maximum der Highs VOR der Konsolidierungsperiode
        consolidation_start = -self.config.consolidation_days - 1
        if abs(consolidation_start) >= len(highs):
            consolidation_start = -len(highs) + 1

        # Altes ATH = Maximum vor der Konsolidierung
        old_ath = max(highs[-lookback:consolidation_start])

        # Prüfe ob neues ATH
        threshold = old_ath * (1 + self.config.breakout_threshold_pct / 100)

        info = {
            'lookback': lookback,
            'old_ath': old_ath,
            'current_high': current_high,
            'threshold': threshold
        }

        if current_high >= threshold:
            # Neues ATH!
            pct_above = ((current_high / old_ath) - 1) * 100
            info['pct_above_old'] = pct_above

            # Prüfe Konsolidierung (nicht schon die letzten Tage auf ATH)
            consolidation_highs = highs[consolidation_start:-1]
            recent_ath = max(consolidation_highs) if consolidation_highs else current_high

            if recent_ath < old_ath * 0.98:  # War mindestens 2% unter ATH
                info['had_consolidation'] = True
                return 3, info
            else:
                info['had_consolidation'] = False
                return 2, info  # ATH aber ohne Konsolidierung
        else:
            pct_below = ((old_ath / current_high) - 1) * 100
            info['pct_below_ath'] = pct_below
            return 0, info

    def _score_volume_confirmation(
        self,
        volumes: List[int]
    ) -> Tuple[int, Dict[str, Any]]:
        """Prüft Volumen-Bestätigung mit Trend-Analyse"""
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

        # Volume-Trend der letzten 5 Tage (für Breakout sollte steigen)
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

        # Scoring: Für Breakout ist hohes Volumen wichtig
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
        """Analysiert Trend via SMAs"""
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

        # Preis über allen SMAs
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
        """Berechnet RSI und scored (nicht überkauft = gut)"""
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

        # Nicht überkauft = gut für Breakout
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
        """Vergleicht Performance mit SPY"""
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
        """Berechnet Momentum/Rate of Change Score"""
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
    # MACD SCORING (NEU)
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

        # Crossover Detection
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

    def _score_macd(self, macd: Optional[MACDResult]) -> Tuple[float, str, str]:
        """MACD Score für Breakout (0-2 Punkte)"""
        if not macd:
            return 0, "No MACD data", "neutral"

        cfg = self.scoring_config.macd

        # Für Breakout: Bullish MACD ist Bestätigung
        if macd.crossover == 'bullish':
            return cfg.weight_bullish_cross, "MACD bullish crossover confirms breakout", "bullish_cross"

        if macd.histogram > 0 and macd.macd_line > 0:
            return cfg.weight_bullish, "MACD positive momentum", "bullish"

        if macd.histogram > 0:
            return cfg.weight_bullish * 0.5, "MACD histogram positive", "bullish_weak"

        return 0, "MACD not confirming breakout", "neutral"

    # =========================================================================
    # KELTNER CHANNEL (NEU - für Breakout)
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

    def _score_keltner_breakout(
        self,
        keltner: KeltnerChannelResult,
        current_price: float
    ) -> Tuple[float, str]:
        """Keltner Channel Score für Breakout (0-2 Punkte) - UPPER Band"""
        cfg = self.scoring_config.keltner
        position = keltner.price_position
        pct = keltner.percent_position

        # Für Breakout: ÜBER dem oberen Band ist bullisch
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

    def _calculate_stop_loss(
        self,
        lows: List[float],
        current_price: float
    ) -> float:
        """Berechnet Stop-Loss unter letztem Swing-Low"""
        # Letztes 10-Tage-Tief als Support
        recent_low = min(lows[-10:])

        # Stop 1% unter Support
        stop = recent_low * 0.99

        # Max 5% unter aktuellem Preis
        max_stop = current_price * 0.95

        return max(stop, max_stop)

    def _calculate_target(
        self,
        entry: float,
        stop: float
    ) -> float:
        """Berechnet Target mit 2:1 Risk/Reward"""
        risk = entry - stop
        return entry + (risk * 2)
