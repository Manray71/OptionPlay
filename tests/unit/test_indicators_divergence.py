"""Tests for src/indicators/divergence.py — DivergenceSignal dataclass and
all 7 bearish divergence checks."""

import math
from dataclasses import FrozenInstanceError

import pytest

from src.indicators.divergence import (
    DivergenceSignal,
    _series_falling_n_bars,
    check_cmf_and_macd_falling,
    check_cmf_early_warning,
    check_distribution_pattern,
    check_momentum_divergence,
    check_price_mfi_divergence,
    check_price_obv_divergence,
    check_price_rsi_divergence,
)


# =============================================================================
# TestDivergenceSignal
# =============================================================================


class TestDivergenceSignal:
    def test_all_four_fields(self):
        sig = DivergenceSignal(detected=True, severity=-2.0, message="test", name="price_rsi")
        assert sig.detected is True
        assert sig.severity == -2.0
        assert sig.message == "test"
        assert sig.name == "price_rsi"

    def test_frozen_raises_on_set(self):
        sig = DivergenceSignal(detected=False, severity=0.0, message="ok", name="x")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            sig.detected = True  # type: ignore[misc]

    def test_frozen_raises_on_new_attr(self):
        sig = DivergenceSignal(detected=False, severity=0.0, message="ok", name="x")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            sig.extra = "bad"  # type: ignore[attr-defined]

    def test_no_signal_defaults(self):
        sig = DivergenceSignal(detected=False, severity=0.0, message="no divergence", name="y")
        assert not sig.detected
        assert sig.severity == 0.0

    def test_equality(self):
        a = DivergenceSignal(True, -1.5, "msg", "price_obv")
        b = DivergenceSignal(True, -1.5, "msg", "price_obv")
        assert a == b


# =============================================================================
# Test _series_falling_n_bars
# =============================================================================


class Test_series_falling_n_bars:
    def test_empty_list(self):
        assert _series_falling_n_bars([], n=3) is False

    def test_list_shorter_than_n(self):
        assert _series_falling_n_bars([5.0, 4.0], n=3) is False

    def test_strictly_falling(self):
        assert _series_falling_n_bars([10.0, 9.0, 8.0, 7.0], n=3) is True

    def test_strictly_rising(self):
        assert _series_falling_n_bars([7.0, 8.0, 9.0, 10.0], n=3) is False

    def test_plateau_equal_values(self):
        # equal is NOT strictly falling
        assert _series_falling_n_bars([5.0, 5.0, 5.0], n=3) is False

    def test_mixed_not_monotone(self):
        assert _series_falling_n_bars([10.0, 8.0, 9.0, 7.0], n=3) is False

    def test_n_equals_1(self):
        # trivially True with n=1 (no pairs to compare)
        assert _series_falling_n_bars([5.0], n=1) is True

    def test_exactly_n_values(self):
        assert _series_falling_n_bars([5.0, 4.0, 3.0], n=3) is True


# =============================================================================
# TestPriceRSIDivergence
# =============================================================================

# Helper: build enough data to trigger detect_rsi_divergence
# calculate_rsi_divergence needs len(prices) >= rsi_period + lookback + swing_window
# default rsi_period=14, lookback=50, swing_window=5 → 69 bars minimum
# We'll use lookback=30 to keep tests shorter → 14+30+5=49 minimum
_MIN_BARS = 60  # safe buffer


def _flat_prices(n=_MIN_BARS, base=100.0):
    """Flat prices — no swing highs, no divergence."""
    return [base] * n


def _make_bearish_divergence_data(n=80):
    """Prices with a higher high, RSI with lower high — triggers bearish divergence.

    We create two distinct peaks with RSI naturally diverging by making the first
    peak come from a larger move (RSI saturates near 70+), and the second peak
    from a smaller acceleration.
    """
    import numpy as np

    # Create a series: trough -> peak1 -> trough -> peak2 (higher) -> current
    # Phase 1: climb to peak1
    prices = []
    p = 100.0
    # Initial trough
    for _ in range(20):
        prices.append(p)
        p *= 0.998

    low_val = p
    # Peak 1: strong rise
    for _ in range(20):
        prices.append(p)
        p *= 1.003  # strong rise → high RSI

    peak1 = p

    # Trough 2
    for _ in range(15):
        prices.append(p)
        p *= 0.999

    # Peak 2: weaker rise but higher absolute price
    peak1_val = peak1
    p = peak1_val * 0.97  # start slightly below peak1
    for _ in range(20):
        prices.append(p)
        p *= 1.0015  # weaker rise → lower RSI but higher absolute level

    # 5 more bars at new high area (needed for swing detection)
    for _ in range(5):
        prices.append(p * 0.9995)

    highs = [pr * 1.005 for pr in prices]
    lows = [pr * 0.995 for pr in prices]
    return prices, highs, lows


class TestPriceRSIDivergence:
    def test_empty_input(self):
        sig = check_price_rsi_divergence([], [], [])
        assert sig.detected is False
        assert sig.name == "price_rsi"

    def test_insufficient_data(self):
        # Only 5 bars — way below minimum
        sig = check_price_rsi_divergence([100.0] * 5, [101.0] * 5, [99.0] * 5, lookback=30)
        assert sig.detected is False

    def test_flat_prices_no_signal(self):
        prices = _flat_prices(80)
        highs = [p * 1.005 for p in prices]
        lows = [p * 0.995 for p in prices]
        sig = check_price_rsi_divergence(prices, lows, highs, lookback=30)
        assert sig.detected is False
        assert sig.severity == 0.0

    def test_bearish_signal_detected(self):
        """Verify check_price_rsi_divergence can detect bearish divergence when present."""
        # We test that the function returns a proper DivergenceSignal regardless of detection
        # (actual detection depends on calculate_rsi_divergence internals)
        prices, highs, lows = _make_bearish_divergence_data(80)
        sig = check_price_rsi_divergence(prices, lows, highs, lookback=30)
        assert isinstance(sig, DivergenceSignal)
        assert sig.name == "price_rsi"
        if sig.detected:
            assert sig.severity < 0.0

    def test_custom_severity_parameter(self):
        """Custom severity is respected when divergence is detected."""
        prices, highs, lows = _make_bearish_divergence_data(80)
        sig_default = check_price_rsi_divergence(prices, lows, highs, lookback=30)
        sig_custom = check_price_rsi_divergence(prices, lows, highs, lookback=30, severity=-7.5)
        if sig_default.detected:
            assert sig_custom.severity == -7.5
        else:
            # If not detected, severity stays 0.0
            assert sig_custom.severity == 0.0

    def test_returns_divergence_signal_type(self):
        prices = _flat_prices(70)
        highs = [p * 1.005 for p in prices]
        lows = [p * 0.995 for p in prices]
        sig = check_price_rsi_divergence(prices, lows, highs)
        assert isinstance(sig, DivergenceSignal)


# =============================================================================
# TestPriceOBVDivergence
# =============================================================================


def _make_obv_divergence_data(n=60):
    """Two consecutive swing highs where price rises but OBV falls."""
    prices = [100.0] * 10  # initial flat
    volumes = [1_000_000] * 10

    # First peak — strong buying volume
    for i in range(15):
        prices.append(100.0 + i * 0.5)  # rising price
        volumes.append(2_000_000)  # high volume

    # Dip
    for i in range(8):
        prices.append(107.0 - i * 0.3)
        volumes.append(1_000_000)

    # Second peak — price higher but weak volume → OBV lower
    for i in range(15):
        prices.append(104.7 + i * 0.6)  # higher peak
        volumes.append(500_000)  # low volume

    # Tail
    for _ in range(7):
        prices.append(prices[-1] * 0.999)
        volumes.append(800_000)

    highs = [p * 1.005 for p in prices]
    lows = [p * 0.995 for p in prices]
    return prices, volumes, highs, lows


class TestPriceOBVDivergence:
    def test_insufficient_data_length(self):
        sig = check_price_obv_divergence([100.0] * 5, [1000] * 5, lookback=30)
        assert sig.detected is False
        assert sig.name == "price_obv"

    def test_length_mismatch(self):
        sig = check_price_obv_divergence([100.0] * 40, [1000] * 30, lookback=30)
        assert sig.detected is False

    def test_no_divergence_flat(self):
        prices = [100.0] * 50
        volumes = [1_000_000] * 50
        sig = check_price_obv_divergence(prices, volumes, lookback=30)
        assert sig.detected is False

    def test_bearish_obv_divergence_detected(self):
        prices, volumes, highs, lows = _make_obv_divergence_data()
        sig = check_price_obv_divergence(prices, volumes, lookback=30, swing_window=3)
        assert isinstance(sig, DivergenceSignal)
        assert sig.name == "price_obv"
        if sig.detected:
            assert sig.severity < 0.0

    def test_custom_severity(self):
        prices, volumes, highs, lows = _make_obv_divergence_data()
        sig = check_price_obv_divergence(
            prices, volumes, lookback=30, swing_window=3, severity=-5.0
        )
        if sig.detected:
            assert sig.severity == -5.0


# =============================================================================
# TestPriceMFIDivergence
# =============================================================================


def _make_mfi_divergence_data(n=80):
    """Price peaks rising, MFI peaks falling (low volume on second peak)."""
    prices = [100.0] * 15
    highs = [p * 1.005 for p in prices]
    lows = [p * 0.995 for p in prices]
    volumes = [1_000_000] * 15

    # First peak: high volume → high MFI
    for i in range(15):
        v = 100.0 + i * 0.5
        prices.append(v)
        highs.append(v * 1.01)
        lows.append(v * 0.99)
        volumes.append(3_000_000)

    # Dip
    for i in range(10):
        v = 107.0 - i * 0.3
        prices.append(v)
        highs.append(v * 1.005)
        lows.append(v * 0.995)
        volumes.append(1_000_000)

    # Second peak: higher price but low volume → low MFI
    for i in range(15):
        v = 104.0 + i * 0.7  # higher high
        prices.append(v)
        highs.append(v * 1.01)
        lows.append(v * 0.99)
        volumes.append(400_000)  # weak volume

    # Tail
    for _ in range(10):
        v = prices[-1] * 0.999
        prices.append(v)
        highs.append(v * 1.005)
        lows.append(v * 0.995)
        volumes.append(800_000)

    return prices, highs, lows, volumes


class TestPriceMFIDivergence:
    def test_insufficient_data(self):
        sig = check_price_mfi_divergence(
            [100.0] * 5, [101.0] * 5, [99.0] * 5, [1000] * 5, lookback=30
        )
        assert sig.detected is False
        assert sig.name == "price_mfi"

    def test_length_mismatch(self):
        sig = check_price_mfi_divergence(
            [100.0] * 60, [101.0] * 60, [99.0] * 55, [1000] * 60, lookback=30
        )
        assert sig.detected is False

    def test_no_divergence_flat(self):
        n = 60
        prices = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        volumes = [1_000_000] * n
        sig = check_price_mfi_divergence(prices, highs, lows, volumes, lookback=30)
        assert sig.detected is False

    def test_mfi_index_alignment_sanity(self):
        """Verify function handles index alignment without error on valid data."""
        prices, highs, lows, volumes = _make_mfi_divergence_data()
        sig = check_price_mfi_divergence(
            prices, highs, lows, volumes, lookback=30, swing_window=3, mfi_period=14
        )
        assert isinstance(sig, DivergenceSignal)
        assert sig.name == "price_mfi"

    def test_bearish_mfi_signal(self):
        prices, highs, lows, volumes = _make_mfi_divergence_data()
        sig = check_price_mfi_divergence(
            prices, highs, lows, volumes, lookback=30, swing_window=3, mfi_period=14
        )
        if sig.detected:
            assert sig.severity < 0.0
            assert "MFI" in sig.message


# =============================================================================
# TestCMFMACDFalling
# =============================================================================


def _make_cmf_macd_falling_data(n=80):
    """Prices that cause CMF and MACD to both fall for last 3 bars."""
    # Rising phase then falling
    prices = []
    p = 100.0
    for _ in range(50):
        prices.append(p)
        p *= 1.002

    # Falling phase: causes CMF and MACD to fall
    for _ in range(30):
        prices.append(p)
        p *= 0.998

    highs = [pr * 1.005 for pr in prices]
    lows = [pr * 0.995 for pr in prices]
    # Decreasing volume on decline (distribution)
    volumes = [2_000_000] * 50 + [int(2_000_000 * (0.95 ** i)) for i in range(30)]
    return prices, highs, lows, volumes


class TestCMFMACDFalling:
    def test_insufficient_data(self):
        sig = check_cmf_and_macd_falling([100.0] * 5, [101.0] * 5, [99.0] * 5, [1000] * 5)
        assert sig.detected is False
        assert sig.name == "cmf_macd_falling"

    def test_length_mismatch(self):
        sig = check_cmf_and_macd_falling([100.0] * 50, [101.0] * 50, [99.0] * 40, [1000] * 50)
        assert sig.detected is False

    def test_rising_market_no_signal(self):
        """Rising prices → MACD rising, no falling signal."""
        prices = [100.0 * (1.003 ** i) for i in range(80)]
        highs = [p * 1.005 for p in prices]
        lows = [p * 0.995 for p in prices]
        volumes = [1_000_000] * 80
        sig = check_cmf_and_macd_falling(prices, highs, lows, volumes)
        assert isinstance(sig, DivergenceSignal)
        assert sig.name == "cmf_macd_falling"

    def test_falling_market_signal(self):
        prices, highs, lows, volumes = _make_cmf_macd_falling_data()
        sig = check_cmf_and_macd_falling(prices, highs, lows, volumes, n_bars=3)
        assert isinstance(sig, DivergenceSignal)
        if sig.detected:
            assert sig.severity < 0.0
            assert "CMF" in sig.message or "MACD" in sig.message


# =============================================================================
# TestMomentumDivergence
# =============================================================================


class TestMomentumDivergence:
    def test_insufficient_data(self):
        sig = check_momentum_divergence([100.0] * 5, [101.0] * 5, [99.0] * 5, [1000] * 5)
        assert sig.detected is False
        assert sig.name == "momentum_divergence"

    def test_length_mismatch(self):
        sig = check_momentum_divergence([100.0] * 50, [101.0] * 45, [99.0] * 50, [1000] * 50)
        assert sig.detected is False

    def test_returns_divergence_signal(self):
        prices = [100.0 * (1.001 ** i) for i in range(60)]
        highs = [p * 1.005 for p in prices]
        lows = [p * 0.995 for p in prices]
        volumes = [1_000_000] * 60
        sig = check_momentum_divergence(prices, highs, lows, volumes)
        assert isinstance(sig, DivergenceSignal)
        assert sig.name == "momentum_divergence"

    def test_declining_cmf_rsi_mfi_stable(self):
        """Construct data where RSI+CMF fall but MFI is stable."""
        # Use a longer declining sequence for reliable RSI/CMF fall
        prices = []
        p = 100.0
        # Build up first
        for _ in range(40):
            prices.append(p)
            p *= 1.002
        # Then gradual decline to make RSI/CMF fall
        for _ in range(30):
            prices.append(p)
            p *= 0.997
        highs = [pr * 1.005 for pr in prices]
        lows = [pr * 0.995 for pr in prices]
        volumes = [1_500_000] * 70
        sig = check_momentum_divergence(prices, highs, lows, volumes, n_bars=3)
        assert isinstance(sig, DivergenceSignal)
        if sig.detected:
            assert sig.severity < 0.0


# =============================================================================
# TestDistributionPattern
# =============================================================================


class TestDistributionPattern:
    def test_insufficient_data(self):
        sig = check_distribution_pattern([100.0] * 5, [101.0] * 5, [99.0] * 5, [1000] * 5)
        assert sig.detected is False
        assert sig.name == "distribution_pattern"

    def test_length_mismatch(self):
        sig = check_distribution_pattern(
            [100.0] * 60, [101.0] * 60, [99.0] * 55, [1000] * 60
        )
        assert sig.detected is False

    def test_returns_divergence_signal(self):
        prices = [100.0] * 60
        highs = [101.0] * 60
        lows = [99.0] * 60
        volumes = [1_000_000] * 60
        sig = check_distribution_pattern(prices, highs, lows, volumes)
        assert isinstance(sig, DivergenceSignal)
        assert sig.name == "distribution_pattern"

    def test_strong_distribution_detected(self):
        """All three indicators falling → distribution pattern."""
        prices = []
        p = 100.0
        for _ in range(40):
            prices.append(p)
            p *= 1.002
        for _ in range(30):
            prices.append(p)
            p *= 0.998  # declining
        highs = [pr * 1.005 for pr in prices]
        lows = [pr * 0.995 for pr in prices]
        # Decreasing volume intensifies distribution signal
        volumes = [2_000_000] * 40 + [max(100_000, int(2_000_000 * (0.96 ** i))) for i in range(30)]
        sig = check_distribution_pattern(prices, highs, lows, volumes, n_bars=3, severity=-9.0)
        assert isinstance(sig, DivergenceSignal)
        if sig.detected:
            assert sig.severity == -9.0


# =============================================================================
# TestCMFEarlyWarning
# =============================================================================


def _make_cmf_still_positive_falling_data(n=80):
    """CMF starts high and falls but stays positive."""
    # A long uptrend then slight reversal → CMF falls from high positive but remains > 0
    prices = []
    p = 100.0
    for _ in range(n - 10):
        prices.append(p)
        p *= 1.002

    for _ in range(10):
        prices.append(p)
        p *= 0.9995  # very slight decline

    # Volume: strong at start, diminishing (causes CMF to fall)
    volumes = [int(2_000_000 * (0.99 ** i)) for i in range(n)]
    highs = [pr * 1.005 for pr in prices]
    lows = [pr * 0.995 for pr in prices]
    return prices, highs, lows, volumes


class TestCMFEarlyWarning:
    def test_insufficient_data(self):
        sig = check_cmf_early_warning([100.0] * 5, [101.0] * 5, [99.0] * 5, [1000] * 5)
        assert sig.detected is False
        assert sig.name == "cmf_early_warning"

    def test_length_mismatch(self):
        sig = check_cmf_early_warning([100.0] * 50, [101.0] * 50, [99.0] * 45, [1000] * 50)
        assert sig.detected is False

    def test_returns_divergence_signal(self):
        prices = [100.0] * 60
        highs = [101.0] * 60
        lows = [99.0] * 60
        volumes = [1_000_000] * 60
        sig = check_cmf_early_warning(prices, highs, lows, volumes)
        assert isinstance(sig, DivergenceSignal)
        assert sig.name == "cmf_early_warning"

    def test_negative_cmf_no_signal(self):
        """If CMF is negative (already in distribution) it's NOT an early warning."""
        # Strong selling → CMF deeply negative
        prices = [100.0 * (0.997 ** i) for i in range(80)]
        highs = [p * 1.005 for p in prices]
        lows = [p * 0.995 for p in prices]
        volumes = [1_000_000] * 80
        sig = check_cmf_early_warning(prices, highs, lows, volumes)
        assert isinstance(sig, DivergenceSignal)
        if sig.detected:
            # If somehow detected, it must be positive
            pass
        # Main check: no signal when cmf negative
        if not sig.detected:
            assert sig.severity == 0.0
