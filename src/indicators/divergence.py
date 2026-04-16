"""Bearish divergence checks for swing-high / momentum analysis.

All 7 checks follow the same contract:
  Input: aligned time series (same length, same end-bar)
  Output: DivergenceSignal with detected/severity/message

Designed for Bull-Put-Spread scoring: a detected bearish divergence
adds a negative penalty to the analyzer's score.
"""

from dataclasses import dataclass
from typing import List, Optional

from .momentum import calculate_rsi_divergence


@dataclass(frozen=True)
class DivergenceSignal:
    """Result of a single divergence check.

    Attributes:
        detected: True if the divergence pattern is present
        severity: Score penalty if detected (negative, e.g. -2.0).
                  0.0 if not detected.
        message: Human-readable description ('bearish RSI divergence detected')
        name: Short check identifier ('price_rsi', 'price_obv', etc.)
    """

    detected: bool
    severity: float
    message: str
    name: str


def _series_falling_n_bars(series: List[float], n: int = 3) -> bool:
    """True wenn die letzten n Werte strikt monoton fallend sind.

    series: aelteste zuerst, d.h. series[-1] ist aktueller Wert.
    Returns False wenn len(series) < n.
    """
    if len(series) < n:
        return False
    tail = series[-n:]
    return all(tail[i] > tail[i + 1] for i in range(n - 1))


def check_price_rsi_divergence(
    prices: List[float],
    lows: List[float],
    highs: List[float],
    lookback: int = 30,
    severity: float = -2.0,
) -> DivergenceSignal:
    """Bearish Price/RSI-Divergenz: Higher High in Price, Lower High in RSI."""
    result = calculate_rsi_divergence(
        prices=prices,
        lows=lows,
        highs=highs,
        lookback=lookback,
    )

    if result is None:
        return DivergenceSignal(False, 0.0, "no RSI divergence", "price_rsi")

    if result.divergence_type == "bearish":
        return DivergenceSignal(
            detected=True,
            severity=severity,
            message=(
                f"bearish RSI divergence detected "
                f"(price {result.price_pivot_1:.2f}->{result.price_pivot_2:.2f}, "
                f"RSI {result.rsi_pivot_1:.1f}->{result.rsi_pivot_2:.1f})"
            ),
            name="price_rsi",
        )

    return DivergenceSignal(False, 0.0, "no bearish RSI divergence", "price_rsi")


def check_price_obv_divergence(
    prices: List[float],
    volumes: List[int],
    lookback: int = 30,
    swing_window: int = 5,
    severity: float = -1.5,
) -> DivergenceSignal:
    """Bearish Price/OBV-Divergenz: Price macht Higher High, OBV macht Lower High."""
    from .momentum import calculate_obv_series, find_swing_highs

    if len(prices) < lookback or len(prices) != len(volumes):
        return DivergenceSignal(False, 0.0, "insufficient data", "price_obv")

    obv = calculate_obv_series(prices, volumes)
    if len(obv) != len(prices):
        return DivergenceSignal(False, 0.0, "obv length mismatch", "price_obv")

    swing_highs = find_swing_highs(prices, window=swing_window, lookback=lookback)
    if len(swing_highs) < 2:
        return DivergenceSignal(False, 0.0, "too few swing highs", "price_obv")

    # find_swing_highs returns List[Tuple[int, float]]
    (idx1, p1), (idx2, p2) = swing_highs[-2], swing_highs[-1]
    obv1, obv2 = obv[idx1], obv[idx2]

    if p2 > p1 and obv2 < obv1:
        return DivergenceSignal(
            detected=True,
            severity=severity,
            message=(
                f"bearish OBV divergence "
                f"(price {p1:.2f}->{p2:.2f}, OBV {obv1:.0f}->{obv2:.0f})"
            ),
            name="price_obv",
        )
    return DivergenceSignal(False, 0.0, "no OBV divergence", "price_obv")


def check_price_mfi_divergence(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    lookback: int = 30,
    swing_window: int = 5,
    mfi_period: int = 14,
    severity: float = -1.5,
) -> DivergenceSignal:
    """Bearish Price/MFI-Divergenz: Price macht Higher High, MFI macht Lower High.

    MFI series is shorter than closes by mfi_period: len(mfi) == len(closes) - mfi_period.
    Swing high indices into prices are mapped to the same absolute bar, so we
    subtract mfi_period from the price index to get the MFI index.
    """
    from .momentum import calculate_mfi_series, find_swing_highs

    if len(prices) < lookback + mfi_period or len(prices) != len(highs):
        return DivergenceSignal(False, 0.0, "insufficient data", "price_mfi")
    if len(prices) != len(lows) or len(prices) != len(volumes):
        return DivergenceSignal(False, 0.0, "length mismatch", "price_mfi")

    mfi = calculate_mfi_series(highs, lows, prices, volumes, period=mfi_period)
    if len(mfi) == 0:
        return DivergenceSignal(False, 0.0, "mfi calculation failed", "price_mfi")

    swing_highs = find_swing_highs(prices, window=swing_window, lookback=lookback)
    if len(swing_highs) < 2:
        return DivergenceSignal(False, 0.0, "too few swing highs", "price_mfi")

    (idx1, p1), (idx2, p2) = swing_highs[-2], swing_highs[-1]

    # MFI index alignment: mfi[0] corresponds to prices[mfi_period]
    # So for price index i, mfi index = i - mfi_period
    mfi_idx1 = idx1 - mfi_period
    mfi_idx2 = idx2 - mfi_period

    if mfi_idx1 < 0 or mfi_idx2 < 0 or mfi_idx1 >= len(mfi) or mfi_idx2 >= len(mfi):
        return DivergenceSignal(False, 0.0, "mfi index out of range", "price_mfi")

    mfi1, mfi2 = mfi[mfi_idx1], mfi[mfi_idx2]

    if p2 > p1 and mfi2 < mfi1:
        return DivergenceSignal(
            detected=True,
            severity=severity,
            message=(
                f"bearish MFI divergence "
                f"(price {p1:.2f}->{p2:.2f}, MFI {mfi1:.1f}->{mfi2:.1f})"
            ),
            name="price_mfi",
        )
    return DivergenceSignal(False, 0.0, "no MFI divergence", "price_mfi")


def check_cmf_and_macd_falling(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    n_bars: int = 3,
    severity: float = -1.0,
) -> DivergenceSignal:
    """Bearish Signal: CMF und MACD-Line beide fallen (n_bars strikt monoton).

    calculate_macd_series returns Optional[Dict[str, List[float]]] with 'line' key.
    calculate_cmf_series returns List[float].
    """
    from .momentum import calculate_cmf_series, calculate_macd_series

    if len(prices) < 30 or len(prices) != len(highs):
        return DivergenceSignal(False, 0.0, "insufficient data", "cmf_macd_falling")
    if len(prices) != len(lows) or len(prices) != len(volumes):
        return DivergenceSignal(False, 0.0, "length mismatch", "cmf_macd_falling")

    cmf = calculate_cmf_series(highs, lows, prices, volumes)
    macd_dict = calculate_macd_series(prices)

    if not cmf or macd_dict is None:
        return DivergenceSignal(False, 0.0, "indicator calculation failed", "cmf_macd_falling")

    macd_line = macd_dict.get("line", [])
    if not macd_line:
        return DivergenceSignal(False, 0.0, "macd line empty", "cmf_macd_falling")

    cmf_falling = _series_falling_n_bars(cmf, n=n_bars)
    macd_falling = _series_falling_n_bars(macd_line, n=n_bars)

    if cmf_falling and macd_falling:
        return DivergenceSignal(
            detected=True,
            severity=severity,
            message=(
                f"CMF and MACD both falling {n_bars} bars "
                f"(CMF {cmf[-1]:.3f}, MACD {macd_line[-1]:.3f})"
            ),
            name="cmf_macd_falling",
        )
    return DivergenceSignal(False, 0.0, "no CMF+MACD divergence", "cmf_macd_falling")


def check_momentum_divergence(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    n_bars: int = 3,
    mfi_period: int = 14,
    severity: float = -1.5,
) -> DivergenceSignal:
    """Momentum-Divergenz: MFI stabil (nicht steigend), CMF und RSI fallen.

    Signals distribution pressure building even when price appears stable.
    calculate_rsi_series returns List[float] (same length as prices).
    """
    from .momentum import calculate_cmf_series, calculate_mfi_series, calculate_rsi_series

    if len(prices) < mfi_period + n_bars + 1 or len(prices) != len(highs):
        return DivergenceSignal(False, 0.0, "insufficient data", "momentum_divergence")
    if len(prices) != len(lows) or len(prices) != len(volumes):
        return DivergenceSignal(False, 0.0, "length mismatch", "momentum_divergence")

    mfi = calculate_mfi_series(highs, lows, prices, volumes, period=mfi_period)
    cmf = calculate_cmf_series(highs, lows, prices, volumes)
    rsi = calculate_rsi_series(prices)

    if not mfi or not cmf or not rsi:
        return DivergenceSignal(False, 0.0, "indicator calculation failed", "momentum_divergence")

    # MFI stable: last value NOT higher than n_bars ago (no new buying pressure)
    if len(mfi) < n_bars + 1:
        return DivergenceSignal(False, 0.0, "insufficient mfi data", "momentum_divergence")

    mfi_stable = mfi[-1] <= mfi[-(n_bars + 1)]
    cmf_falling = _series_falling_n_bars(cmf, n=n_bars)
    rsi_falling = _series_falling_n_bars(rsi, n=n_bars)

    if mfi_stable and cmf_falling and rsi_falling:
        return DivergenceSignal(
            detected=True,
            severity=severity,
            message=(
                f"momentum divergence: MFI steady ({mfi[-1]:.1f}), "
                f"CMF falling ({cmf[-1]:.3f}), RSI falling ({rsi[-1]:.1f})"
            ),
            name="momentum_divergence",
        )
    return DivergenceSignal(False, 0.0, "no momentum divergence", "momentum_divergence")


def check_distribution_pattern(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    n_bars: int = 3,
    mfi_period: int = 14,
    cmf_period: int = 20,
    severity: float = -3.0,
) -> DivergenceSignal:
    """Distribution Pattern: OBV, MFI und CMF alle fallen gleichzeitig.

    The strongest bearish signal — all three volume-based indicators show
    consistent distribution (selling pressure).
    """
    from .momentum import calculate_cmf_series, calculate_mfi_series, calculate_obv_series

    min_len = max(mfi_period + n_bars + 1, cmf_period + n_bars)
    if len(prices) < min_len or len(prices) != len(highs):
        return DivergenceSignal(False, 0.0, "insufficient data", "distribution_pattern")
    if len(prices) != len(lows) or len(prices) != len(volumes):
        return DivergenceSignal(False, 0.0, "length mismatch", "distribution_pattern")

    obv = calculate_obv_series(prices, volumes)
    mfi = calculate_mfi_series(highs, lows, prices, volumes, period=mfi_period)
    cmf = calculate_cmf_series(highs, lows, prices, volumes, period=cmf_period)

    if not obv or not mfi or not cmf:
        return DivergenceSignal(False, 0.0, "indicator calculation failed", "distribution_pattern")

    obv_falling = _series_falling_n_bars(obv, n=n_bars)
    mfi_falling = _series_falling_n_bars(mfi, n=n_bars)
    cmf_falling = _series_falling_n_bars(cmf, n=n_bars)

    if obv_falling and mfi_falling and cmf_falling:
        return DivergenceSignal(
            detected=True,
            severity=severity,
            message=(
                f"distribution pattern: OBV, MFI, CMF all falling {n_bars} bars "
                f"(OBV {obv[-1]:.0f}, MFI {mfi[-1]:.1f}, CMF {cmf[-1]:.3f})"
            ),
            name="distribution_pattern",
        )
    return DivergenceSignal(False, 0.0, "no distribution pattern", "distribution_pattern")


def check_cmf_early_warning(
    prices: List[float],
    highs: List[float],
    lows: List[float],
    volumes: List[int],
    n_bars: int = 3,
    cmf_period: int = 20,
    severity: float = -1.0,
) -> DivergenceSignal:
    """CMF Early Warning: CMF faellt n_bars lang, ist aber noch positiv.

    Early warning sign: money flow turning negative while CMF still above zero
    indicates distribution starting before price shows weakness.
    """
    from .momentum import calculate_cmf_series

    if len(prices) < cmf_period + n_bars or len(prices) != len(highs):
        return DivergenceSignal(False, 0.0, "insufficient data", "cmf_early_warning")
    if len(prices) != len(lows) or len(prices) != len(volumes):
        return DivergenceSignal(False, 0.0, "length mismatch", "cmf_early_warning")

    cmf = calculate_cmf_series(highs, lows, prices, volumes, period=cmf_period)

    if not cmf:
        return DivergenceSignal(False, 0.0, "cmf calculation failed", "cmf_early_warning")

    cmf_falling = _series_falling_n_bars(cmf, n=n_bars)
    cmf_still_positive = cmf[-1] > 0.0

    if cmf_falling and cmf_still_positive:
        return DivergenceSignal(
            detected=True,
            severity=severity,
            message=(
                f"CMF early warning: falling {n_bars} bars but still positive "
                f"(CMF {cmf[-1]:.3f})"
            ),
            name="cmf_early_warning",
        )
    return DivergenceSignal(False, 0.0, "no CMF early warning", "cmf_early_warning")
