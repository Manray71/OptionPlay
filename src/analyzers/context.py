# OptionPlay - Analysis Context
# ==============================
# Shared pre-calculated values for analyzers to avoid redundant computations.
#
# Performance Optimizations:
# - Uses NumPy-based indicator calculations (5-10x faster)
# - Calculates all indicators in single pass
# - Only stores final values, not full arrays (memory efficient)
# - Shared across all analyzers for same symbol
#
# Usage:
#     context = AnalysisContext.from_data(prices, volumes, highs, lows)
#     signal = analyzer.analyze(symbol, prices, volumes, highs, lows, context=context)

# mypy: warn_unused_ignores=False
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import logging
import numpy as np

# Import optimized support/resistance functions
# NOTE: Fallback import chains use type: ignore for no-redef (re-importing same names),
# import-untyped (non-package imports), and assignment (None fallbacks for optional deps).
try:
    from ..indicators.support_resistance import (
        find_support_levels as find_support_optimized,
        find_resistance_levels as find_resistance_optimized,
    )
    from ..indicators.optimized import (
        calc_rsi_numpy,
        calc_sma_numpy,
        calc_ema_numpy,
        calc_macd_numpy,
        calc_stochastic_numpy,
        calc_atr_numpy,
        calc_fibonacci_levels,
        find_high_low_numpy,
    )
    from ..indicators.gap_analysis import analyze_gap
    from ..models.indicators import GapResult
    _NUMPY_AVAILABLE = True
except ImportError:
    try:
        from indicators.support_resistance import (  # type: ignore[no-redef,import-untyped]
            find_support_levels as find_support_optimized,
            find_resistance_levels as find_resistance_optimized,
        )
        from indicators.optimized import (  # type: ignore[no-redef,import-untyped]
            calc_rsi_numpy,
            calc_sma_numpy,
            calc_ema_numpy,
            calc_macd_numpy,
            calc_stochastic_numpy,
            calc_atr_numpy,
            calc_fibonacci_levels,
            find_high_low_numpy,
        )
        from indicators.gap_analysis import analyze_gap  # type: ignore[no-redef,import-untyped]
        from models.indicators import GapResult  # type: ignore[no-redef,import-untyped]
        _NUMPY_AVAILABLE = True
    except ImportError:
        _NUMPY_AVAILABLE = False
        analyze_gap = None  # type: ignore[assignment]
        GapResult = None  # type: ignore[assignment,misc]

# Import canonical indicator functions (used in Python fallback path)
# NOTE: Same fallback pattern — no-redef for duplicate imports, assignment for None sentinels.
try:
    from ..indicators.momentum import calculate_rsi, calculate_macd, calculate_stochastic
    from ..indicators.trend import calculate_ema
    from ..indicators.volatility import calculate_atr_simple
except ImportError:
    try:
        from indicators.momentum import calculate_rsi, calculate_macd, calculate_stochastic  # type: ignore[no-redef,import-untyped]
        from indicators.trend import calculate_ema  # type: ignore[no-redef,import-untyped]
        from indicators.volatility import calculate_atr_simple  # type: ignore[no-redef,import-untyped]
    except ImportError:
        calculate_rsi = None  # type: ignore[assignment]
        calculate_macd = None  # type: ignore[assignment]
        calculate_stochastic = None  # type: ignore[assignment]
        calculate_ema = None  # type: ignore[assignment]
        calculate_atr_simple = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class AnalysisContext:
    """
    Pre-calculated technical indicators and levels for a single symbol.

    Analyzers can use these cached values instead of recalculating them.
    This provides significant performance improvements when multiple
    analyzers process the same symbol.
    """

    # Price data reference
    symbol: str = ""
    current_price: float = 0.0
    current_volume: int = 0

    # RSI values
    rsi_14: Optional[float] = None

    # Moving Averages
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    ema_12: Optional[list[float]] = None
    ema_26: Optional[list[float]] = None

    # MACD
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None

    # Stochastic
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None

    # Support/Resistance
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)

    # Fibonacci levels
    fib_levels: dict[str, float] = field(default_factory=dict)

    # ATR for volatility
    atr_14: Optional[float] = None

    # Volume analysis
    avg_volume_20: Optional[float] = None
    volume_ratio: Optional[float] = None

    # ATH tracking
    all_time_high: Optional[float] = None
    pct_from_ath: Optional[float] = None

    # Trend indicators
    trend: str = "unknown"  # uptrend, downtrend, sideways
    above_sma20: Optional[bool] = None
    above_sma50: Optional[bool] = None
    above_sma200: Optional[bool] = None

    # Gap Analysis (for medium-term strategies like Bull-Put-Spreads)
    gap_result: Optional[Any] = None  # GapResult, uses Any for forward ref
    gap_score: float = 0.0  # -1 to +1, positive = bullish for entry

    # Regime & Sector (Step 7: threading through call stack)
    regime: str = "normal"           # VIX regime (low_vol, normal, elevated, high_vol, danger)
    sector: Optional[str] = None     # Sector name from fundamentals

    # E.5: Dividend-Gap-Handling — set by scanner before analysis
    is_near_ex_dividend: bool = False
    ex_dividend_amount: Optional[float] = None

    # Strategy context (v3: for strategy-differentiated scoring)
    strategy: str = ""               # Current strategy being evaluated (pullback, bounce, etc.)

    @classmethod
    def from_data(
        cls,
        symbol: str,
        prices: list[float],
        volumes: list[int],
        highs: list[float],
        lows: list[float],
        opens: Optional[list[float]] = None,
        calculate_all: bool = True,
        regime: str = "normal",
        sector: Optional[str] = None,
        strategy: str = "",
    ) -> 'AnalysisContext':
        """
        Create context with pre-calculated values from price data.

        Args:
            symbol: Ticker symbol
            prices: Close prices (oldest first)
            volumes: Daily volumes
            highs: Daily highs
            lows: Daily lows
            opens: Open prices (optional, for gap detection)
            calculate_all: If True, calculate all indicators upfront
            regime: VIX regime for config-based scoring
            sector: Sector name for sector-specific weight overrides
            strategy: Strategy name for strategy-differentiated scoring (v3)

        Returns:
            AnalysisContext with populated values
        """
        if len(prices) < 20:
            return cls(symbol=symbol, regime=regime, sector=sector, strategy=strategy)

        # Volume fallback: if latest volume is 0 (weekend/holiday),
        # use last non-zero volume from recent data
        current_volume = volumes[-1] if volumes else 0
        if current_volume == 0 and volumes and len(volumes) >= 2:
            for v in reversed(volumes[:-1]):
                if v > 0:
                    current_volume = v
                    break

        ctx = cls(
            symbol=symbol,
            current_price=prices[-1],
            current_volume=current_volume,
            regime=regime,
            sector=sector,
            strategy=strategy,
        )

        if calculate_all:
            ctx._calculate_indicators(prices, volumes, highs, lows, opens)

        return ctx

    def _calculate_indicators(
        self,
        prices: list[float],
        volumes: list[int],
        highs: list[float],
        lows: list[float],
        opens: Optional[list[float]] = None
    ) -> None:
        """
        Calculate all technical indicators.

        Uses NumPy-based calculations when available (5-10x faster).
        Falls back to pure Python implementations if NumPy module not available.
        """
        if _NUMPY_AVAILABLE:
            self._calculate_indicators_numpy(prices, volumes, highs, lows, opens)
        else:
            self._calculate_indicators_python(prices, volumes, highs, lows, opens)

    def _calculate_indicators_numpy(
        self,
        prices: list[float],
        volumes: list[int],
        highs: list[float],
        lows: list[float],
        opens: Optional[list[float]] = None
    ) -> None:
        """
        Calculate indicators using NumPy (5-10x faster).

        All calculations are vectorized where possible.
        """
        # Store opens for gap calculation
        self._opens = opens

        # Convert to numpy arrays once
        prices_arr = np.asarray(prices, dtype=np.float64)
        highs_arr = np.asarray(highs, dtype=np.float64)
        lows_arr = np.asarray(lows, dtype=np.float64)
        volumes_arr = np.asarray(volumes, dtype=np.float64) if volumes else None

        # RSI (vectorized)
        self.rsi_14 = calc_rsi_numpy(prices_arr, 14)

        # Moving Averages (vectorized)
        self.sma_20 = calc_sma_numpy(prices_arr, 20)
        self.sma_50 = calc_sma_numpy(prices_arr, 50) if len(prices) >= 50 else None
        self.sma_200 = calc_sma_numpy(prices_arr, 200) if len(prices) >= 200 else None

        # EMA - only store last value (memory efficient)
        ema_12_last = calc_ema_numpy(prices_arr, 12, return_last_only=True)
        ema_26_last = calc_ema_numpy(prices_arr, 26, return_last_only=True)

        # For backward compatibility, store as single-element list
        self.ema_12 = [float(ema_12_last)] if ema_12_last is not None else None
        self.ema_26 = [float(ema_26_last)] if ema_26_last is not None else None

        # MACD (vectorized)
        macd_result = calc_macd_numpy(prices_arr)
        if macd_result:
            self.macd_line = macd_result.macd_line
            self.macd_signal = macd_result.signal_line
            self.macd_histogram = macd_result.histogram

        # Stochastic (optimized rolling window)
        if len(highs) >= 14:
            stoch_result = calc_stochastic_numpy(highs_arr, lows_arr, prices_arr)
            if stoch_result:
                self.stoch_k = stoch_result.k
                self.stoch_d = stoch_result.d

        # Support/Resistance (O(n) algorithm)
        self.support_levels = find_support_optimized(
            lows=lows,
            lookback=min(60, len(lows)),
            window=5,
            max_levels=5,
            volumes=volumes if volumes else None,
            tolerance_pct=1.5
        )
        self.resistance_levels = find_resistance_optimized(
            highs=highs,
            lookback=min(60, len(highs)),
            window=5,
            max_levels=5,
            volumes=volumes if volumes else None,
            tolerance_pct=1.5
        )

        # Fibonacci (vectorized high/low finding)
        lookback = min(60, len(highs))
        if lookback > 0:
            high, low = find_high_low_numpy(highs_arr, lows_arr, lookback)
            self.fib_levels = calc_fibonacci_levels(high, low)

        # ATR (vectorized)
        self.atr_14 = calc_atr_numpy(highs_arr, lows_arr, prices_arr, 14)

        # Volume (vectorized) — exclude zero volumes (weekends/holidays)
        if volumes_arr is not None and len(volumes_arr) >= 20:
            recent_vols = volumes_arr[-20:]
            nonzero_vols = recent_vols[recent_vols > 0]
            if len(nonzero_vols) > 0:
                self.avg_volume_20 = float(np.mean(nonzero_vols))
            else:
                self.avg_volume_20 = float(np.mean(recent_vols))
            if self.avg_volume_20 > 0:
                self.volume_ratio = self.current_volume / self.avg_volume_20

        # ATH (vectorized)
        self.all_time_high = float(np.max(highs_arr)) if len(highs_arr) > 0 else None
        if self.all_time_high and self.all_time_high > 0:
            self.pct_from_ath = (self.all_time_high - self.current_price) / self.all_time_high * 100

        # Gap Analysis
        self._calculate_gap(prices, highs, lows)

        # Trend
        self._determine_trend()

    def _calculate_indicators_python(
        self,
        prices: list[float],
        volumes: list[int],
        highs: list[float],
        lows: list[float],
        opens: Optional[list[float]] = None
    ) -> None:
        """
        Calculate indicators using pure Python (fallback).

        Used when NumPy optimized module is not available.
        """
        # Store opens for gap calculation
        self._opens = opens

        # RSI (use canonical implementation)
        if calculate_rsi is not None and len(prices) >= 15:
            self.rsi_14 = calculate_rsi(prices, 14)
        else:
            self.rsi_14 = None

        # Moving Averages
        self.sma_20 = self._calc_sma(prices, 20)
        if len(prices) >= 50:
            self.sma_50 = self._calc_sma(prices, 50)
        if len(prices) >= 200:
            self.sma_200 = self._calc_sma(prices, 200)

        # EMA for MACD
        self.ema_12 = self._calc_ema(prices, 12)
        self.ema_26 = self._calc_ema(prices, 26)

        # MACD
        if self.ema_12 and self.ema_26:
            self._calc_macd()

        # Stochastic
        if len(highs) >= 14 and len(lows) >= 14:
            self._calc_stochastic(highs, lows, prices)

        # Support/Resistance (using optimized O(n) algorithm)
        self.support_levels = find_support_optimized(
            lows=lows,
            lookback=min(60, len(lows)),
            window=5,
            max_levels=5,
            volumes=volumes if volumes else None,
            tolerance_pct=1.5
        )
        self.resistance_levels = find_resistance_optimized(
            highs=highs,
            lookback=min(60, len(highs)),
            window=5,
            max_levels=5,
            volumes=volumes if volumes else None,
            tolerance_pct=1.5
        )

        # Fibonacci (last 60 days)
        lookback = min(60, len(highs))
        if lookback > 0:
            high = max(highs[-lookback:])
            low = min(lows[-lookback:])
            self.fib_levels = self._calc_fibonacci(high, low)

        # ATR
        self.atr_14 = self._calc_atr(highs, lows, prices, 14)

        # Volume — exclude zero volumes (weekends/holidays)
        if len(volumes) >= 20:
            recent_vols = volumes[-20:]
            nonzero_vols = [v for v in recent_vols if v > 0]
            if nonzero_vols:
                self.avg_volume_20 = sum(nonzero_vols) / len(nonzero_vols)
            else:
                self.avg_volume_20 = sum(recent_vols) / 20
            if self.avg_volume_20 > 0:
                self.volume_ratio = self.current_volume / self.avg_volume_20

        # ATH
        self.all_time_high = max(highs) if highs else None
        if self.all_time_high and self.all_time_high > 0:
            self.pct_from_ath = (self.all_time_high - self.current_price) / self.all_time_high * 100

        # Gap Analysis
        self._calculate_gap(prices, highs, lows)

        # Trend
        self._determine_trend()

    def _calc_sma(self, prices: list[float], period: int) -> Optional[float]:
        """Calculate Simple Moving Average."""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def _calc_ema(self, prices: list[float], period: int) -> Optional[list[float]]:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]

        for price in prices[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])

        return ema

    def _calc_macd(self) -> None:
        """Calculate MACD from pre-calculated EMAs."""
        if not self.ema_12 or not self.ema_26:
            return

        # Align lengths
        min_len = min(len(self.ema_12), len(self.ema_26))
        ema_12_aligned = self.ema_12[-min_len:]
        ema_26_aligned = self.ema_26[-min_len:]

        macd_line = [e12 - e26 for e12, e26 in zip(ema_12_aligned, ema_26_aligned)]

        if len(macd_line) >= 9:
            signal_ema = self._calc_ema(macd_line, 9)
            if signal_ema:
                self.macd_line = macd_line[-1]
                self.macd_signal = signal_ema[-1]
                self.macd_histogram = self.macd_line - self.macd_signal

    def _calc_stochastic(
        self,
        highs: list[float],
        lows: list[float],
        prices: list[float],
        k_period: int = 14,
        d_period: int = 3
    ) -> None:
        """
        Calculate Stochastic oscillator with proper %D.

        %K = (Current Close - Lowest Low) / (Highest High - Lowest Low) * 100
        %D = 3-period SMA of %K
        """
        # Need enough data for k_period plus d_period-1 for the SMA
        min_required = k_period + d_period - 1
        if len(prices) < min_required:
            return

        # Calculate multiple %K values for the %D SMA
        k_values = []
        for i in range(d_period):
            offset = d_period - 1 - i
            end_idx = len(prices) - offset
            start_idx = end_idx - k_period

            highest_high = max(highs[start_idx:end_idx])
            lowest_low = min(lows[start_idx:end_idx])
            close = prices[end_idx - 1]

            if highest_high == lowest_low:
                k_values.append(50.0)
            else:
                k_val = (close - lowest_low) / (highest_high - lowest_low) * 100
                k_values.append(k_val)

        # Current %K is the last value
        self.stoch_k = k_values[-1]

        # %D is the 3-period SMA of %K values
        self.stoch_d = sum(k_values) / len(k_values)

    def _calc_fibonacci(self, high: float, low: float) -> dict[str, float]:
        """Calculate Fibonacci retracement levels."""
        diff = high - low
        return {
            '0.0': high,
            '0.236': high - diff * 0.236,
            '0.382': high - diff * 0.382,
            '0.5': high - diff * 0.5,
            '0.618': high - diff * 0.618,
            '0.786': high - diff * 0.786,
            '1.0': low
        }

    def _calc_atr(
        self,
        highs: list[float],
        lows: list[float],
        prices: list[float],
        period: int = 14
    ) -> Optional[float]:
        """Calculate Average True Range."""
        if len(prices) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(prices)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - prices[i-1]),
                abs(lows[i] - prices[i-1])
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        return sum(true_ranges[-period:]) / period

    def _calculate_gap(
        self,
        prices: list[float],
        highs: list[float],
        lows: list[float]
    ) -> None:
        """
        Calculate gap analysis for medium-term trading strategies.

        Gap analysis is validated with 174k+ events across 907 symbols:
        - Down-gaps show +0.43% better 30-day returns
        - Large down-gaps (>3%) show +1.21% outperformance
        - Useful for Bull-Put-Spreads with 30-45 DTE
        """
        if analyze_gap is None or len(prices) < 2:
            self.gap_result = None
            self.gap_score = 0.0
            return

        try:
            # Use real opens if available, otherwise approximate from closes
            if hasattr(self, '_opens') and self._opens and len(self._opens) == len(prices):
                opens = self._opens
            else:
                # Fallback: approximate opens from previous closes
                opens = [prices[0]] + prices[:-1]

            self.gap_result = analyze_gap(
                opens=opens,
                highs=highs,
                lows=lows,
                closes=prices,
                lookback_days=20,
                min_gap_pct=0.5,
            )

            if self.gap_result:
                self.gap_score = self.gap_result.quality_score
            else:
                self.gap_score = 0.0

        except Exception as e:
            logger.debug(f"Gap analysis error: {e}")
            self.gap_result = None
            self.gap_score = 0.0

    def _determine_trend(self) -> None:
        """Determine trend based on moving averages."""
        self.above_sma20 = self.current_price > self.sma_20 if self.sma_20 else None
        self.above_sma50 = self.current_price > self.sma_50 if self.sma_50 else None
        self.above_sma200 = self.current_price > self.sma_200 if self.sma_200 else None

        if self.above_sma200 and self.above_sma20:
            self.trend = 'uptrend'
        elif self.above_sma200 is False and self.above_sma20 is False:
            self.trend = 'downtrend'
        else:
            self.trend = 'sideways'

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for debugging/logging."""
        return {
            'symbol': self.symbol,
            'current_price': self.current_price,
            'rsi_14': self.rsi_14,
            'sma_20': self.sma_20,
            'sma_50': self.sma_50,
            'sma_200': self.sma_200,
            'macd_line': self.macd_line,
            'macd_signal': self.macd_signal,
            'stoch_k': self.stoch_k,
            'support_levels': self.support_levels,
            'resistance_levels': self.resistance_levels,
            'trend': self.trend,
            'volume_ratio': self.volume_ratio,
            'pct_from_ath': self.pct_from_ath,
            'gap_score': self.gap_score,
            'gap_type': self.gap_result.gap_type if self.gap_result else None,
            'regime': self.regime,
            'sector': self.sector,
            'strategy': self.strategy,
        }
