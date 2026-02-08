# OptionPlay - Strategy Score Breakdowns
# =======================================
# Dataclasses für detaillierte Score-Aufschlüsselung aller Strategien

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


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

    # RSI Divergenz Score (0-3) - NEU
    # Bullische Divergenz: Kurs tieferes Tief, RSI höheres Tief → Verkaufsdruck lässt nach
    # Bärische Divergenz: Kurs höheres Hoch, RSI tieferes Hoch → Kaufdruck lässt nach
    rsi_divergence_score: float = 0
    rsi_divergence_type: Optional[str] = None  # 'bullish', 'bearish', or None
    rsi_divergence_strength: float = 0
    rsi_divergence_formation_days: int = 0
    rsi_divergence_reason: str = ""

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

    # VWAP Score (0-3) - NEW from Feature Engineering
    vwap_score: float = 0
    vwap_value: float = 0
    vwap_distance_pct: float = 0
    vwap_position: str = ""
    vwap_reason: str = ""

    # Market Context Score (-1 to +2) - NEW from Feature Engineering
    market_context_score: float = 0
    spy_trend: str = ""
    market_context_reason: str = ""

    # Sector Score (-1 to +1) - NEW from Feature Engineering
    sector_score: float = 0
    sector: str = ""
    sector_reason: str = ""

    # Gap Score (0-1) - from Feature Engineering
    gap_score: float = 0
    gap_reason: str = ""

    total_score: float = 0
    max_possible: float = 10.0  # v2: 5-component scoring, max 10.0

    def to_dict(self) -> dict[str, Any]:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 3.5,
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
                'rsi_divergence': {
                    'score': self.rsi_divergence_score,
                    'type': self.rsi_divergence_type,
                    'strength': round(self.rsi_divergence_strength, 3),
                    'formation_days': self.rsi_divergence_formation_days,
                    'reason': self.rsi_divergence_reason
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
                },
                'vwap': {
                    'score': self.vwap_score,
                    'value': round(self.vwap_value, 2),
                    'distance_pct': round(self.vwap_distance_pct, 2),
                    'position': self.vwap_position,
                    'reason': self.vwap_reason
                },
                'market_context': {
                    'score': self.market_context_score,
                    'spy_trend': self.spy_trend,
                    'reason': self.market_context_reason
                },
                'sector': {
                    'score': self.sector_score,
                    'name': self.sector,
                    'reason': self.sector_reason
                }
            }
        }


@dataclass
class ATHBreakoutScoreBreakdown:
    """Detaillierte Aufschlüsselung des ATH-Breakout-Scores (v2 — 4-Component)"""
    # Consolidation Quality (0-2.5) — stored in ath_score for compat
    ath_score: float = 0
    ath_old: float = 0
    ath_current: float = 0
    ath_pct_above: float = 0
    ath_had_consolidation: bool = False
    ath_reason: str = ""

    # Volume Score (-1.0 to 2.5)
    volume_score: float = 0
    volume_ratio: float = 0
    volume_trend: str = ""
    volume_reason: str = ""

    # Momentum/Trend Score (-1.0 to 1.5) — stored in trend_score for compat
    trend_score: float = 0
    trend_status: str = ""  # strong_uptrend, uptrend, above_sma200, below_sma200, downtrend
    trend_reason: str = ""

    # RSI info (not a separate scoring component, part of momentum)
    rsi_score: float = 0
    rsi_value: float = 0
    rsi_reason: str = ""

    # Legacy fields (kept for backward compat, default 0)
    rs_score: float = 0
    rs_outperformance: float = 0
    rs_reason: str = ""
    macd_score: float = 0
    macd_signal: Optional[str] = None
    macd_histogram: float = 0
    macd_reason: str = ""
    momentum_score: float = 0
    momentum_roc: float = 0
    momentum_reason: str = ""
    keltner_score: float = 0
    keltner_position: str = ""
    keltner_percent: float = 0
    keltner_reason: str = ""
    vwap_score: float = 0
    vwap_value: float = 0
    vwap_distance_pct: float = 0
    vwap_position: str = ""
    vwap_reason: str = ""
    market_context_score: float = 0
    spy_trend: str = ""
    market_context_reason: str = ""
    sector_score: float = 0
    sector: str = ""
    sector_reason: str = ""
    gap_score: float = 0
    gap_reason: str = ""

    total_score: float = 0
    max_possible: float = 10.0  # v2: 4-component scoring, max ~9.0, normalized to 10 scale

    def to_dict(self) -> dict[str, Any]:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 4.0,
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
            }
        }


@dataclass
class EarningsDipScoreBreakdown:
    """Detaillierte Aufschlüsselung des Earnings-Dip-Scores (v2 — 5-Component + Penalties)"""
    # Drop Magnitude (0-2.0) — stored in dip_score
    dip_score: float = 0
    dip_pct: float = 0
    dip_low: float = 0
    pre_earnings_price: float = 0
    dip_reason: str = ""

    # Stabilization (0-2.5)
    stabilization_score: float = 0
    days_without_new_low: int = 0
    stabilization_reason: str = ""

    # Overreaction — RSI component (0-0.5)
    rsi_score: float = 0
    rsi_value: float = 0
    rsi_reason: str = ""

    # Overreaction — Volume component (0-0.5)
    volume_score: float = 0
    volume_ratio: float = 0
    volume_trend: str = ""
    volume_reason: str = ""

    # Fundamental/Trend Score (0-2.0) — stored in trend_score for compat
    trend_score: float = 0
    trend_status: str = ""
    was_in_uptrend: bool = False
    trend_reason: str = ""

    # BPS Suitability (0-1.0) — stored in gap_score for compat
    gap_score: float = 0
    gap_detected: bool = False
    gap_size_pct: float = 0
    gap_filled: bool = False
    gap_fill_pct: float = 0
    gap_reason: str = ""

    # Legacy fields (kept for backward compat, default 0)
    macd_score: float = 0
    macd_signal: Optional[str] = None
    macd_histogram: float = 0
    macd_turning_up: bool = False
    macd_reason: str = ""
    stoch_score: float = 0
    stoch_signal: Optional[str] = None
    stoch_k: float = 0
    stoch_d: float = 0
    stoch_reason: str = ""
    keltner_score: float = 0
    keltner_position: str = ""
    keltner_percent: float = 0
    keltner_reason: str = ""
    vwap_score: float = 0
    vwap_value: float = 0
    vwap_distance_pct: float = 0
    vwap_position: str = ""
    vwap_reason: str = ""
    market_context_score: float = 0
    spy_trend: str = ""
    market_context_reason: str = ""
    sector_score: float = 0
    sector: str = ""
    sector_reason: str = ""

    total_score: float = 0
    max_possible: float = 9.5  # v2: 5-component + penalties, max ~9.5

    def to_dict(self) -> dict[str, Any]:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 3.5,
            'components': {
                'dip': {
                    'score': self.dip_score,
                    'dip_pct': round(self.dip_pct, 2),
                    'dip_low': round(self.dip_low, 2),
                    'pre_earnings_price': round(self.pre_earnings_price, 2),
                    'reason': self.dip_reason
                },
                'stabilization': {
                    'score': self.stabilization_score,
                    'days_without_new_low': self.days_without_new_low,
                    'reason': self.stabilization_reason
                },
                'fundamental': {
                    'score': self.trend_score,
                    'was_in_uptrend': self.was_in_uptrend,
                    'reason': self.trend_reason
                },
                'overreaction': {
                    'rsi_score': self.rsi_score,
                    'rsi_value': round(self.rsi_value, 2),
                    'rsi_reason': self.rsi_reason,
                    'volume_score': self.volume_score,
                    'panic_vol_ratio': round(self.volume_ratio, 2),
                    'volume_reason': self.volume_reason,
                },
                'bps_suitability': {
                    'score': self.gap_score,
                    'reason': self.gap_reason,
                },
            }
        }


@dataclass
class TrendContinuationScoreBreakdown:
    """Detaillierte Aufschlüsselung des Trend-Continuation-Scores (v2 — 5-Component)"""
    # SMA Alignment (0-2.5)
    sma_alignment_score: float = 0
    sma_20: float = 0
    sma_50: float = 0
    sma_200: float = 0
    sma_spread_pct: float = 0
    sma_all_rising: bool = False
    sma_reason: str = ""

    # Trend Stability (0-2.0 + 0.5 bonus)
    stability_score: float = 0
    closes_below_sma50: int = 0
    stability_days: int = 60
    golden_cross_days: int = 0
    stability_reason: str = ""

    # Trend Buffer (0-2.0)
    buffer_score: float = 0
    buffer_to_sma50_pct: float = 0
    buffer_to_sma200_pct: float = 0
    buffer_reason: str = ""

    # Momentum Health (0-2.0, penalties possible)
    momentum_score: float = 0
    rsi_value: float = 0
    adx_value: float = 0
    macd_bullish: bool = False
    volume_divergence: bool = False
    momentum_reason: str = ""

    # Volatility Suitability (0-1.5)
    volatility_score: float = 0
    atr_pct: float = 0
    volatility_reason: str = ""

    # Strike Zone Recommendation
    conservative_short_strike: float = 0
    aggressive_short_strike: float = 0

    # VIX Regime
    vix_regime: str = ""
    vix_adjustment: float = 1.0

    total_score: float = 0
    max_possible: float = 10.5  # v2: 5-component scoring

    def to_dict(self) -> dict[str, Any]:
        return {
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'qualified': self.total_score >= 5.0,
            'components': {
                'sma_alignment': {
                    'score': self.sma_alignment_score,
                    'sma_20': round(self.sma_20, 2),
                    'sma_50': round(self.sma_50, 2),
                    'sma_200': round(self.sma_200, 2),
                    'spread_pct': round(self.sma_spread_pct, 2),
                    'all_rising': self.sma_all_rising,
                    'reason': self.sma_reason
                },
                'trend_stability': {
                    'score': self.stability_score,
                    'closes_below_sma50': self.closes_below_sma50,
                    'stability_days': self.stability_days,
                    'golden_cross_days': self.golden_cross_days,
                    'reason': self.stability_reason
                },
                'trend_buffer': {
                    'score': self.buffer_score,
                    'buffer_to_sma50_pct': round(self.buffer_to_sma50_pct, 2),
                    'buffer_to_sma200_pct': round(self.buffer_to_sma200_pct, 2),
                    'reason': self.buffer_reason
                },
                'momentum_health': {
                    'score': self.momentum_score,
                    'rsi': round(self.rsi_value, 2),
                    'adx': round(self.adx_value, 2),
                    'macd_bullish': self.macd_bullish,
                    'volume_divergence': self.volume_divergence,
                    'reason': self.momentum_reason
                },
                'volatility': {
                    'score': self.volatility_score,
                    'atr_pct': round(self.atr_pct, 3),
                    'reason': self.volatility_reason
                },
            },
            'strike_zone': {
                'conservative_short': round(self.conservative_short_strike, 2),
                'aggressive_short': round(self.aggressive_short_strike, 2),
            },
            'vix_regime': self.vix_regime,
            'vix_adjustment': self.vix_adjustment,
        }
