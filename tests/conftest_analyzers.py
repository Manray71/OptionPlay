# OptionPlay - Shared Analyzer Test Fixtures
# =============================================
# Reusable fixtures and pattern builders for analyzer tests.
#
# Usage: pytest auto-discovers this conftest file. All fixtures
# are available in any test file under tests/.
#
# Pattern builders (make_*) are plain functions — import them
# directly or use the corresponding pytest fixtures.

import math
from typing import Optional

import pytest

from src.analyzers.context import AnalysisContext


# =============================================================================
# SYNTHETIC PRICE PATTERN BUILDERS
# =============================================================================


def make_uptrend(
    n: int = 260,
    base: float = 100.0,
    trend_pct: float = 0.15,
    volatility: float = 0.01,
    seed: int = 42,
) -> dict:
    """
    Generate uptrend OHLCV data.

    Args:
        n: Number of bars
        base: Starting price
        trend_pct: Total price increase as fraction (0.15 = 15%)
        volatility: Daily noise amplitude as fraction of price
        seed: Random seed for reproducibility

    Returns:
        dict with keys: prices, volumes, highs, lows
    """
    import random

    rng = random.Random(seed)
    step = base * trend_pct / n
    prices = []
    highs = []
    lows = []
    volumes = []

    for i in range(n):
        p = base + step * i + rng.gauss(0, base * volatility)
        p = max(p, base * 0.5)  # floor
        h = p * (1 + rng.uniform(0.001, 0.015))
        lo = p * (1 - rng.uniform(0.001, 0.015))
        v = int(1_000_000 + rng.gauss(0, 100_000))
        prices.append(round(p, 2))
        highs.append(round(h, 2))
        lows.append(round(lo, 2))
        volumes.append(max(100_000, v))

    return {"prices": prices, "volumes": volumes, "highs": highs, "lows": lows}


def make_downtrend(
    n: int = 260,
    base: float = 120.0,
    decline_pct: float = 0.20,
    volatility: float = 0.01,
    seed: int = 42,
) -> dict:
    """
    Generate downtrend OHLCV data.

    Args:
        n: Number of bars
        base: Starting price
        decline_pct: Total price decline as fraction
        volatility: Daily noise amplitude
        seed: Random seed

    Returns:
        dict with keys: prices, volumes, highs, lows
    """
    import random

    rng = random.Random(seed)
    step = base * decline_pct / n
    prices = []
    highs = []
    lows = []
    volumes = []

    for i in range(n):
        p = base - step * i + rng.gauss(0, base * volatility)
        p = max(p, base * 0.1)
        h = p * (1 + rng.uniform(0.001, 0.015))
        lo = p * (1 - rng.uniform(0.001, 0.015))
        v = int(1_000_000 + rng.gauss(0, 100_000))
        prices.append(round(p, 2))
        highs.append(round(h, 2))
        lows.append(round(lo, 2))
        volumes.append(max(100_000, v))

    return {"prices": prices, "volumes": volumes, "highs": highs, "lows": lows}


def make_sideways(
    n: int = 260,
    center: float = 100.0,
    band_pct: float = 0.05,
    volatility: float = 0.008,
    seed: int = 42,
) -> dict:
    """
    Generate sideways/consolidation OHLCV data.

    Args:
        n: Number of bars
        center: Center price
        band_pct: Range band as fraction (±5% default)
        volatility: Daily noise
        seed: Random seed

    Returns:
        dict with keys: prices, volumes, highs, lows
    """
    import random

    rng = random.Random(seed)
    prices = []
    highs = []
    lows = []
    volumes = []

    for i in range(n):
        oscillation = center * band_pct * math.sin(2 * math.pi * i / 40)
        p = center + oscillation + rng.gauss(0, center * volatility)
        p = max(p, center * 0.8)
        h = p * (1 + rng.uniform(0.001, 0.012))
        lo = p * (1 - rng.uniform(0.001, 0.012))
        v = int(800_000 + rng.gauss(0, 80_000))
        prices.append(round(p, 2))
        highs.append(round(h, 2))
        lows.append(round(lo, 2))
        volumes.append(max(100_000, v))

    return {"prices": prices, "volumes": volumes, "highs": highs, "lows": lows}


def make_gap_down(
    n: int = 260,
    base: float = 110.0,
    gap_pct: float = 0.08,
    gap_at: Optional[int] = None,
    recovery_pct: float = 0.5,
    seed: int = 42,
) -> dict:
    """
    Generate price data with a gap-down event (e.g., earnings dip).

    Args:
        n: Number of bars
        base: Pre-gap price level
        gap_pct: Size of the gap as fraction (8% default)
        gap_at: Bar index for the gap (default: 80% through)
        recovery_pct: How much of the gap is recovered (0.5 = half)
        seed: Random seed

    Returns:
        dict with keys: prices, volumes, highs, lows, gap_index
    """
    import random

    rng = random.Random(seed)
    if gap_at is None:
        gap_at = int(n * 0.8)

    prices = []
    highs = []
    lows = []
    volumes = []

    gap_size = base * gap_pct
    post_gap_base = base - gap_size
    recovery_target = post_gap_base + gap_size * recovery_pct

    for i in range(n):
        if i < gap_at:
            p = base + rng.gauss(0, base * 0.008)
        elif i == gap_at:
            p = post_gap_base + rng.gauss(0, base * 0.005)
        else:
            bars_after = i - gap_at
            recovery_bars = n - gap_at
            progress = min(bars_after / max(recovery_bars, 1), 1.0)
            p = post_gap_base + (recovery_target - post_gap_base) * progress
            p += rng.gauss(0, base * 0.008)

        p = max(p, base * 0.5)
        h = p * (1 + rng.uniform(0.001, 0.015))
        lo = p * (1 - rng.uniform(0.001, 0.015))
        v = int(1_000_000 + rng.gauss(0, 100_000))
        if i == gap_at:
            v = int(v * 3)  # Volume spike on gap day

        prices.append(round(p, 2))
        highs.append(round(h, 2))
        lows.append(round(lo, 2))
        volumes.append(max(100_000, v))

    result = {"prices": prices, "volumes": volumes, "highs": highs, "lows": lows}
    result["gap_index"] = gap_at
    return result


def make_volume_spike(
    base_data: dict,
    at_index: int = -1,
    multiplier: float = 3.0,
) -> dict:
    """
    Add a volume spike to existing OHLCV data.

    Args:
        base_data: dict from make_uptrend/etc with 'volumes' key
        at_index: Bar index for the spike (-1 = last bar)
        multiplier: Volume multiplier

    Returns:
        Same dict with modified volumes (copy)
    """
    result = {k: list(v) if isinstance(v, list) else v for k, v in base_data.items()}
    idx = at_index if at_index >= 0 else len(result["volumes"]) + at_index
    result["volumes"][idx] = int(result["volumes"][idx] * multiplier)
    return result


# =============================================================================
# ANALYSIS CONTEXT BUILDER
# =============================================================================


def make_context(
    symbol: str = "TEST",
    prices: Optional[list] = None,
    volumes: Optional[list] = None,
    highs: Optional[list] = None,
    lows: Optional[list] = None,
    support_levels: Optional[list] = None,
    resistance_levels: Optional[list] = None,
    **kwargs,
) -> AnalysisContext:
    """
    Build an AnalysisContext from price data with sensible defaults.

    Uses AnalysisContext's built-in calculation for indicators when
    given raw OHLCV data. For quick tests that just need a context
    object with specific fields, pass kwargs directly.

    Args:
        symbol: Symbol name
        prices: Close prices (generates uptrend if None)
        volumes: Volume data (generates default if None)
        highs: High prices (derived from prices if None)
        lows: Low prices (derived from prices if None)
        support_levels: Override support levels
        resistance_levels: Override resistance levels
        **kwargs: Additional AnalysisContext fields to override

    Returns:
        AnalysisContext instance
    """
    if prices is None:
        data = make_uptrend()
        prices = data["prices"]
        volumes = volumes or data["volumes"]
        highs = highs or data["highs"]
        lows = lows or data["lows"]

    if highs is None:
        highs = [p * 1.01 for p in prices]
    if lows is None:
        lows = [p * 0.99 for p in prices]
    if volumes is None:
        volumes = [1_000_000] * len(prices)

    ctx = AnalysisContext.from_data(
        symbol=symbol,
        prices=prices,
        volumes=[int(v) for v in volumes],
        highs=highs,
        lows=lows,
        calculate_all=True,
    )

    if support_levels is not None:
        ctx.support_levels = support_levels
    if resistance_levels is not None:
        ctx.resistance_levels = resistance_levels

    for key, val in kwargs.items():
        if hasattr(ctx, key):
            setattr(ctx, key, val)

    return ctx


# =============================================================================
# PYTEST FIXTURES (wrappers around builders)
# =============================================================================


@pytest.fixture
def uptrend_data():
    """260-bar uptrend OHLCV data."""
    return make_uptrend()


@pytest.fixture
def downtrend_data():
    """260-bar downtrend OHLCV data."""
    return make_downtrend()


@pytest.fixture
def sideways_data():
    """260-bar sideways/consolidation OHLCV data."""
    return make_sideways()


@pytest.fixture
def gap_down_data():
    """260-bar data with 8% gap-down at bar 208."""
    return make_gap_down()


@pytest.fixture
def uptrend_context():
    """AnalysisContext with uptrend data."""
    return make_context()


@pytest.fixture
def downtrend_context():
    """AnalysisContext with downtrend data."""
    data = make_downtrend()
    return make_context(prices=data["prices"], volumes=data["volumes"],
                        highs=data["highs"], lows=data["lows"])
