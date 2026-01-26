# OptionPlay - Strategy Score Breakdowns
# =======================================
# Dataclasses für detaillierte Score-Aufschlüsselung aller Strategien

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class BounceScoreBreakdown:
    """Detaillierte Aufschlüsselung des Bounce-Scores"""
    # Support-Test Score (0-3)
    support_score: float = 0
    support_level: Optional[float] = None
    support_distance_pct: float = 0
    support_strength: str = ""  # weak, moderate, strong
    support_touches: int = 0
    support_reason: str = ""

    # RSI Score (0-2)
    rsi_score: float = 0
    rsi_value: float = 0
    rsi_reason: str = ""

    # Candlestick Pattern Score (0-2)
    candlestick_score: float = 0
    candlestick_pattern: Optional[str] = None
    candlestick_bullish: bool = False
    candlestick_reason: str = ""

    # Volume Score (0-2) - erweitert
    volume_score: float = 0
    volume_ratio: float = 0
    volume_trend: str = ""  # decreasing, stable, increasing
    volume_reason: str = ""

    # Trend Score (0-2)
    trend_score: float = 0
    trend_status: str = ""  # uptrend, pullback_in_uptrend, downtrend
    trend_reason: str = ""

    # MACD Score (0-2) - NEU
    macd_score: float = 0
    macd_signal: Optional[str] = None
    macd_histogram: float = 0
    macd_reason: str = ""

    # Stochastik Score (0-2) - NEU
    stoch_score: float = 0
    stoch_signal: Optional[str] = None
    stoch_k: float = 0
    stoch_d: float = 0
    stoch_reason: str = ""

    # Keltner Channel Score (0-2) - NEU
    keltner_score: float = 0
    keltner_position: str = ""
    keltner_percent: float = 0
    keltner_reason: str = ""

    total_score: float = 0
    max_possible: int = 17  # 3+2+2+2+2+2+2+2 = 17

    def to_dict(self) -> Dict:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 6,
            'components': {
                'support': {
                    'score': self.support_score,
                    'level': self.support_level,
                    'distance_pct': round(self.support_distance_pct, 2),
                    'strength': self.support_strength,
                    'touches': self.support_touches,
                    'reason': self.support_reason
                },
                'rsi': {
                    'score': self.rsi_score,
                    'value': round(self.rsi_value, 2),
                    'reason': self.rsi_reason
                },
                'candlestick': {
                    'score': self.candlestick_score,
                    'pattern': self.candlestick_pattern,
                    'bullish': self.candlestick_bullish,
                    'reason': self.candlestick_reason
                },
                'volume': {
                    'score': self.volume_score,
                    'ratio': round(self.volume_ratio, 2),
                    'trend': self.volume_trend,
                    'reason': self.volume_reason
                },
                'trend': {
                    'score': self.trend_score,
                    'status': self.trend_status,
                    'reason': self.trend_reason
                },
                'macd': {
                    'score': self.macd_score,
                    'signal': self.macd_signal,
                    'histogram': round(self.macd_histogram, 4),
                    'reason': self.macd_reason
                },
                'stochastic': {
                    'score': self.stoch_score,
                    'signal': self.stoch_signal,
                    'k': round(self.stoch_k, 2),
                    'd': round(self.stoch_d, 2),
                    'reason': self.stoch_reason
                },
                'keltner': {
                    'score': self.keltner_score,
                    'position': self.keltner_position,
                    'percent': round(self.keltner_percent, 3),
                    'reason': self.keltner_reason
                }
            }
        }


@dataclass
class ATHBreakoutScoreBreakdown:
    """Detaillierte Aufschlüsselung des ATH-Breakout-Scores"""
    # ATH Breakout Score (0-3)
    ath_score: float = 0
    ath_old: float = 0
    ath_current: float = 0
    ath_pct_above: float = 0
    ath_had_consolidation: bool = False
    ath_reason: str = ""

    # Volume Score (0-2)
    volume_score: float = 0
    volume_ratio: float = 0
    volume_trend: str = ""
    volume_reason: str = ""

    # Trend Score (0-2)
    trend_score: float = 0
    trend_status: str = ""  # strong_uptrend, uptrend, weak_uptrend, downtrend
    trend_reason: str = ""

    # RSI Score (0-1) - nicht überkauft
    rsi_score: float = 0
    rsi_value: float = 0
    rsi_reason: str = ""

    # Relative Strength Score (0-2)
    rs_score: float = 0
    rs_outperformance: float = 0
    rs_reason: str = ""

    # MACD Score (0-2) - NEU
    macd_score: float = 0
    macd_signal: Optional[str] = None
    macd_histogram: float = 0
    macd_reason: str = ""

    # Momentum/ADX Score (0-2) - NEU
    momentum_score: float = 0
    momentum_roc: float = 0  # Rate of Change
    momentum_reason: str = ""

    # Keltner Channel Score (0-2) - NEU (Breakout über oberes Band)
    keltner_score: float = 0
    keltner_position: str = ""
    keltner_percent: float = 0
    keltner_reason: str = ""

    total_score: float = 0
    max_possible: int = 16  # 3+2+2+1+2+2+2+2 = 16

    def to_dict(self) -> Dict:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 6,
            'components': {
                'ath_breakout': {
                    'score': self.ath_score,
                    'old_ath': round(self.ath_old, 2),
                    'current_high': round(self.ath_current, 2),
                    'pct_above': round(self.ath_pct_above, 2),
                    'had_consolidation': self.ath_had_consolidation,
                    'reason': self.ath_reason
                },
                'volume': {
                    'score': self.volume_score,
                    'ratio': round(self.volume_ratio, 2),
                    'trend': self.volume_trend,
                    'reason': self.volume_reason
                },
                'trend': {
                    'score': self.trend_score,
                    'status': self.trend_status,
                    'reason': self.trend_reason
                },
                'rsi': {
                    'score': self.rsi_score,
                    'value': round(self.rsi_value, 2),
                    'reason': self.rsi_reason
                },
                'relative_strength': {
                    'score': self.rs_score,
                    'outperformance': round(self.rs_outperformance, 2),
                    'reason': self.rs_reason
                },
                'macd': {
                    'score': self.macd_score,
                    'signal': self.macd_signal,
                    'histogram': round(self.macd_histogram, 4),
                    'reason': self.macd_reason
                },
                'momentum': {
                    'score': self.momentum_score,
                    'roc': round(self.momentum_roc, 2),
                    'reason': self.momentum_reason
                },
                'keltner': {
                    'score': self.keltner_score,
                    'position': self.keltner_position,
                    'percent': round(self.keltner_percent, 3),
                    'reason': self.keltner_reason
                }
            }
        }


@dataclass
class EarningsDipScoreBreakdown:
    """Detaillierte Aufschlüsselung des Earnings-Dip-Scores"""
    # Dip Score (0-3)
    dip_score: float = 0
    dip_pct: float = 0
    dip_low: float = 0
    pre_earnings_price: float = 0
    dip_reason: str = ""

    # Gap Score (0-1)
    gap_score: float = 0
    gap_detected: bool = False
    gap_size_pct: float = 0
    gap_filled: bool = False
    gap_fill_pct: float = 0
    gap_reason: str = ""

    # RSI Score (0-2)
    rsi_score: float = 0
    rsi_value: float = 0
    rsi_reason: str = ""

    # Stabilization Score (0-2)
    stabilization_score: float = 0
    days_without_new_low: int = 0
    stabilization_reason: str = ""

    # Volume Score (0-2) - erweitert
    volume_score: float = 0
    volume_ratio: float = 0
    volume_trend: str = ""  # normalizing, still_elevated, low
    volume_reason: str = ""

    # Trend Score (0-2)
    trend_score: float = 0
    trend_status: str = ""
    was_in_uptrend: bool = False
    trend_reason: str = ""

    # MACD Score (0-2) - NEU
    macd_score: float = 0
    macd_signal: Optional[str] = None
    macd_histogram: float = 0
    macd_turning_up: bool = False
    macd_reason: str = ""

    # Stochastik Score (0-2) - NEU
    stoch_score: float = 0
    stoch_signal: Optional[str] = None
    stoch_k: float = 0
    stoch_d: float = 0
    stoch_reason: str = ""

    # Keltner Channel Score (0-2) - NEU
    keltner_score: float = 0
    keltner_position: str = ""
    keltner_percent: float = 0
    keltner_reason: str = ""

    total_score: float = 0
    max_possible: int = 18  # 3+1+2+2+2+2+2+2+2 = 18

    def to_dict(self) -> Dict:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 6,
            'components': {
                'dip': {
                    'score': self.dip_score,
                    'dip_pct': round(self.dip_pct, 2),
                    'dip_low': round(self.dip_low, 2),
                    'pre_earnings_price': round(self.pre_earnings_price, 2),
                    'reason': self.dip_reason
                },
                'gap': {
                    'score': self.gap_score,
                    'detected': self.gap_detected,
                    'size_pct': round(self.gap_size_pct, 2),
                    'filled': self.gap_filled,
                    'fill_pct': round(self.gap_fill_pct, 1),
                    'reason': self.gap_reason
                },
                'rsi': {
                    'score': self.rsi_score,
                    'value': round(self.rsi_value, 2),
                    'reason': self.rsi_reason
                },
                'stabilization': {
                    'score': self.stabilization_score,
                    'days_without_new_low': self.days_without_new_low,
                    'reason': self.stabilization_reason
                },
                'volume': {
                    'score': self.volume_score,
                    'ratio': round(self.volume_ratio, 2),
                    'trend': self.volume_trend,
                    'reason': self.volume_reason
                },
                'trend': {
                    'score': self.trend_score,
                    'status': self.trend_status,
                    'was_in_uptrend': self.was_in_uptrend,
                    'reason': self.trend_reason
                },
                'macd': {
                    'score': self.macd_score,
                    'signal': self.macd_signal,
                    'histogram': round(self.macd_histogram, 4),
                    'turning_up': self.macd_turning_up,
                    'reason': self.macd_reason
                },
                'stochastic': {
                    'score': self.stoch_score,
                    'signal': self.stoch_signal,
                    'k': round(self.stoch_k, 2),
                    'd': round(self.stoch_d, 2),
                    'reason': self.stoch_reason
                },
                'keltner': {
                    'score': self.keltner_score,
                    'position': self.keltner_position,
                    'percent': round(self.keltner_percent, 3),
                    'reason': self.keltner_reason
                }
            }
        }
