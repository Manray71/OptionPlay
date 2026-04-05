# OptionPlay - Sector Relative Strength with RRG Quadrants
# ========================================================
"""
Replaces SectorCycleService with a cleaner RRG (Relative Rotation Graph) model.

Key changes from sector_cycle_service.py:
- RS Ratio (EMA of sector/benchmark ratio) instead of return difference
- RS Momentum (rate of change of RS Ratio) for quadrant classification
- 4 RRG quadrants: Leading, Weakening, Lagging, Improving
- Additive score modifier (+0.5 to -0.5) instead of multiplicative factor
- Compatibility wrappers for gradual migration

Usage:
    from src.services.sector_rs import SectorRSService

    service = SectorRSService()
    all_rs = await service.get_all_sector_rs()
    modifier = await service.get_score_modifier("AAPL")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================


def _load_sector_rs_config() -> Dict[str, Any]:
    """Load sector_rs config from strategies.yaml (if exists)."""
    try:
        config_path = Path(__file__).resolve().parents[2] / "config" / "strategies.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
                return data.get("sector_rs", {})
    except Exception:
        pass
    return {}


_cfg = _load_sector_rs_config()


# =============================================================================
# CONSTANTS
# =============================================================================

# ETF mapping (GICS Sectors -> SPDR ETFs)
SECTOR_ETF_MAP: Dict[str, str] = {
    "Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}

# Reverse lookup: symbol sector name variants -> canonical name
_SECTOR_ALIASES: Dict[str, str] = {
    "Healthcare": "Health Care",
    "Information Technology": "Technology",
    "Communications": "Communication Services",
}

# Default configuration
DEFAULT_BENCHMARK = _cfg.get("benchmark", "SPY")
DEFAULT_LOOKBACK_DAYS = _cfg.get("lookback_days", 60)
DEFAULT_EMA_FAST = _cfg.get("ema_fast", 10)
DEFAULT_EMA_SLOW = _cfg.get("ema_slow", 30)
DEFAULT_MOMENTUM_LOOKBACK = _cfg.get("momentum_lookback", 5)
DEFAULT_CACHE_TTL_HOURS = _cfg.get("cache_ttl_hours", 8)

# Score modifiers per quadrant (additive, not multiplicative)
_mod_cfg = _cfg.get("score_modifiers", {})
MODIFIER_LEADING = _mod_cfg.get("leading", 0.5)
MODIFIER_IMPROVING = _mod_cfg.get("improving", 0.3)
MODIFIER_WEAKENING = _mod_cfg.get("weakening", -0.3)
MODIFIER_LAGGING = _mod_cfg.get("lagging", -0.5)


# =============================================================================
# DATA MODELS
# =============================================================================


class RSQuadrant(str, Enum):
    """RRG quadrant classification."""

    LEADING = "leading"  # RS > 100, Momentum > 100
    WEAKENING = "weakening"  # RS > 100, Momentum <= 100
    LAGGING = "lagging"  # RS <= 100, Momentum <= 100
    IMPROVING = "improving"  # RS <= 100, Momentum > 100


@dataclass(frozen=True)
class SectorRS:
    """Sector relative strength analysis result."""

    sector: str
    etf_symbol: str
    rs_ratio: float  # > 100 = outperforming benchmark
    rs_momentum: float  # > 100 = improving
    quadrant: RSQuadrant
    score_modifier: float  # Additive modifier for signal scores


# =============================================================================
# COMPUTATION HELPERS (pure functions, no state)
# =============================================================================


def compute_ema(prices: List[float], period: int) -> List[float]:
    """
    Compute Exponential Moving Average.

    Args:
        prices: List of prices (oldest first)
        period: EMA period

    Returns:
        List of EMA values (same length as prices)
    """
    if not prices or period <= 0:
        return []

    k = 2.0 / (period + 1)
    ema = [prices[0]]
    for i in range(1, len(prices)):
        ema.append(prices[i] * k + ema[-1] * (1 - k))
    return ema


def compute_rs_ratio(
    sector_closes: List[float],
    benchmark_closes: List[float],
    ema_period: int = DEFAULT_EMA_SLOW,
) -> float:
    """
    Compute RS Ratio: EMA of (sector / benchmark) * 100.

    Returns value centered around 100:
    - > 100: sector outperforming
    - < 100: sector underperforming
    """
    if (
        not sector_closes
        or not benchmark_closes
        or len(sector_closes) != len(benchmark_closes)
    ):
        return 100.0

    # Raw ratio series
    ratios = []
    for s, b in zip(sector_closes, benchmark_closes):
        if b > 0:
            ratios.append(s / b)
        else:
            ratios.append(1.0)

    if not ratios:
        return 100.0

    # Smooth with EMA
    ema_ratios = compute_ema(ratios, ema_period)

    # Normalize: current EMA / mean of EMA * 100
    if not ema_ratios:
        return 100.0

    # Use the ratio of current to first as relative measure
    # Centered at 100
    current = ema_ratios[-1]
    baseline = ema_ratios[0] if ema_ratios[0] > 0 else 1.0
    return (current / baseline) * 100.0


def compute_rs_momentum(
    sector_closes: List[float],
    benchmark_closes: List[float],
    ema_fast: int = DEFAULT_EMA_FAST,
    ema_slow: int = DEFAULT_EMA_SLOW,
    momentum_lookback: int = DEFAULT_MOMENTUM_LOOKBACK,
) -> float:
    """
    Compute RS Momentum: rate of change of RS Ratio.

    Uses fast EMA / slow EMA of ratio series, then measures
    the recent rate of change.

    Returns value centered around 100:
    - > 100: RS improving (accelerating)
    - < 100: RS deteriorating (decelerating)
    """
    if (
        not sector_closes
        or not benchmark_closes
        or len(sector_closes) != len(benchmark_closes)
        or len(sector_closes) < momentum_lookback + ema_slow
    ):
        return 100.0

    # Raw ratio series
    ratios = []
    for s, b in zip(sector_closes, benchmark_closes):
        if b > 0:
            ratios.append(s / b)
        else:
            ratios.append(1.0)

    # Fast and slow EMAs of the ratio
    ema_fast_vals = compute_ema(ratios, ema_fast)
    ema_slow_vals = compute_ema(ratios, ema_slow)

    if not ema_fast_vals or not ema_slow_vals:
        return 100.0

    # Momentum: fast EMA vs slow EMA, with lookback comparison
    current_spread = ema_fast_vals[-1] / ema_slow_vals[-1] if ema_slow_vals[-1] > 0 else 1.0
    past_spread = (
        ema_fast_vals[-momentum_lookback] / ema_slow_vals[-momentum_lookback]
        if len(ema_fast_vals) > momentum_lookback and ema_slow_vals[-momentum_lookback] > 0
        else 1.0
    )

    if past_spread <= 0:
        return 100.0

    return (current_spread / past_spread) * 100.0


def classify_quadrant(rs_ratio: float, rs_momentum: float) -> RSQuadrant:
    """Classify into RRG quadrant based on RS Ratio and Momentum."""
    if rs_ratio > 100 and rs_momentum > 100:
        return RSQuadrant.LEADING
    elif rs_ratio > 100 and rs_momentum <= 100:
        return RSQuadrant.WEAKENING
    elif rs_ratio <= 100 and rs_momentum > 100:
        return RSQuadrant.IMPROVING
    else:
        return RSQuadrant.LAGGING


def get_quadrant_modifier(quadrant: RSQuadrant) -> float:
    """Get additive score modifier for a quadrant."""
    modifiers = {
        RSQuadrant.LEADING: MODIFIER_LEADING,
        RSQuadrant.IMPROVING: MODIFIER_IMPROVING,
        RSQuadrant.WEAKENING: MODIFIER_WEAKENING,
        RSQuadrant.LAGGING: MODIFIER_LAGGING,
    }
    return modifiers.get(quadrant, 0.0)


def normalize_sector_name(sector: str) -> str:
    """Normalize sector name to canonical form."""
    return _SECTOR_ALIASES.get(sector, sector)


# =============================================================================
# SERVICE CLASS
# =============================================================================


class SectorRSService:
    """
    Service for sector relative strength analysis using RRG quadrants.

    Fetches sector ETF + benchmark data, computes RS Ratio and Momentum,
    classifies into quadrants, and provides additive score modifiers.
    """

    def __init__(
        self,
        provider=None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Args:
            provider: Data provider with async get_historical(symbol, days=N).
                      If None, resolved lazily.
            config: Override config dict (for testing).
        """
        self._provider = provider
        self._config = config or _cfg
        self._cache: Dict[str, SectorRS] = {}
        self._cache_time: float = 0

        # Sector -> symbol mapping (from fundamentals)
        self._symbol_sector_map: Dict[str, str] = {}

    @property
    def _ttl_seconds(self) -> float:
        return self._config.get("cache_ttl_hours", DEFAULT_CACHE_TTL_HOURS) * 3600

    @property
    def _lookback_days(self) -> int:
        return self._config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)

    @property
    def _ema_fast(self) -> int:
        return self._config.get("ema_fast", DEFAULT_EMA_FAST)

    @property
    def _ema_slow(self) -> int:
        return self._config.get("ema_slow", DEFAULT_EMA_SLOW)

    @property
    def _momentum_lookback(self) -> int:
        return self._config.get("momentum_lookback", DEFAULT_MOMENTUM_LOOKBACK)

    @property
    def _benchmark(self) -> str:
        return self._config.get("benchmark", DEFAULT_BENCHMARK)

    def _is_cache_valid(self) -> bool:
        if not self._cache:
            return False
        return (time.time() - self._cache_time) < self._ttl_seconds

    async def _get_provider(self):
        """Lazily resolve the market data provider."""
        if self._provider is not None:
            return self._provider
        try:
            from ..container import get_container

            container = get_container()
            self._provider = await container.ensure_provider()
        except (ImportError, AttributeError):
            logger.warning("Could not resolve market data provider for SectorRS")
        return self._provider

    async def _fetch_closes(self, symbol: str, days: int) -> Optional[List[float]]:
        """Fetch historical closing prices."""
        try:
            provider = await self._get_provider()
            if provider is None:
                return None
            result = await provider.get_historical(symbol, days=days)
            if result and hasattr(result, "closes"):
                return result.closes
            if isinstance(result, list):
                return [r.close for r in result if hasattr(r, "close")]
            return None
        except Exception as e:
            logger.debug(f"Failed to fetch {symbol}: {e}")
            return None

    async def calculate_sector_rs(
        self, sector: str, sector_closes: List[float], benchmark_closes: List[float]
    ) -> SectorRS:
        """
        Calculate RS for a single sector given price data.

        Args:
            sector: Sector name
            sector_closes: Sector ETF closing prices (oldest first)
            benchmark_closes: Benchmark closing prices (oldest first)
        """
        etf = SECTOR_ETF_MAP.get(sector, "???")

        rs_ratio = compute_rs_ratio(
            sector_closes, benchmark_closes, ema_period=self._ema_slow
        )
        rs_momentum = compute_rs_momentum(
            sector_closes,
            benchmark_closes,
            ema_fast=self._ema_fast,
            ema_slow=self._ema_slow,
            momentum_lookback=self._momentum_lookback,
        )
        quadrant = classify_quadrant(rs_ratio, rs_momentum)
        modifier = get_quadrant_modifier(quadrant)

        return SectorRS(
            sector=sector,
            etf_symbol=etf,
            rs_ratio=round(rs_ratio, 2),
            rs_momentum=round(rs_momentum, 2),
            quadrant=quadrant,
            score_modifier=modifier,
        )

    async def get_all_sector_rs(self) -> Dict[str, SectorRS]:
        """
        Fetch and calculate RS for all sectors in parallel.

        Returns cached results if within TTL.
        """
        if self._is_cache_valid():
            return dict(self._cache)

        benchmark = self._benchmark
        fetch_days = self._lookback_days + 10  # buffer

        # Fetch all ETFs + benchmark in parallel
        symbols = list(SECTOR_ETF_MAP.values()) + [benchmark]
        tasks = [self._fetch_closes(sym, fetch_days) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build price map
        price_map: Dict[str, List[float]] = {}
        for sym, res in zip(symbols, results):
            if isinstance(res, list) and len(res) > 0:
                price_map[sym] = res

        benchmark_closes = price_map.get(benchmark)
        if benchmark_closes is None:
            logger.warning(f"No {benchmark} data, returning neutral RS")
            return self._neutral_fallback()

        # Calculate RS for each sector
        sector_results: Dict[str, SectorRS] = {}
        for sector, etf in SECTOR_ETF_MAP.items():
            etf_closes = price_map.get(etf)
            if etf_closes is None or len(etf_closes) != len(benchmark_closes):
                sector_results[sector] = self._neutral_rs(sector)
                continue

            rs = await self.calculate_sector_rs(sector, etf_closes, benchmark_closes)
            sector_results[sector] = rs

        # Update cache
        self._cache = sector_results
        self._cache_time = time.time()

        return dict(sector_results)

    async def get_score_modifier(self, symbol: str) -> float:
        """
        Get additive score modifier for a symbol based on its sector.

        Returns 0.0 if sector unknown or on error.
        """
        try:
            sector = await self._get_symbol_sector(symbol)
            if sector is None:
                return 0.0

            if not self._is_cache_valid():
                await self.get_all_sector_rs()

            rs = self._cache.get(sector)
            if rs is None:
                return 0.0

            return rs.score_modifier
        except Exception as e:
            logger.debug(f"Sector RS modifier error for {symbol}: {e}")
            return 0.0

    async def _get_symbol_sector(self, symbol: str) -> Optional[str]:
        """Look up sector for a symbol from fundamentals cache."""
        if symbol in self._symbol_sector_map:
            return self._symbol_sector_map[symbol]

        try:
            from ..cache import get_fundamentals_manager

            manager = get_fundamentals_manager()
            f = manager.get_fundamentals(symbol)
            if f and f.sector:
                sector = normalize_sector_name(f.sector)
                self._symbol_sector_map[symbol] = sector
                return sector
        except Exception:
            pass

        return None

    # =========================================================================
    # COMPATIBILITY WRAPPERS (for gradual migration from SectorCycleService)
    # =========================================================================

    async def get_all_sector_statuses(self) -> list:
        """
        Compatibility wrapper: returns list of SectorRS objects
        (similar interface to SectorCycleService.get_all_sector_statuses).
        """
        rs_map = await self.get_all_sector_rs()
        return list(rs_map.values())

    async def get_sector_factor(self, sector: str, strategy: Optional[str] = None) -> float:
        """
        Compatibility wrapper: convert additive modifier to multiplicative factor.

        Maps modifier to factor: modifier + 1.0
        (e.g., +0.5 -> 1.5, -0.3 -> 0.7, 0.0 -> 1.0)
        """
        if not self._is_cache_valid():
            await self.get_all_sector_rs()

        canonical = normalize_sector_name(sector)
        rs = self._cache.get(canonical)
        if rs is None:
            return 1.0

        return 1.0 + rs.score_modifier

    # =========================================================================
    # FALLBACKS
    # =========================================================================

    def _neutral_fallback(self) -> Dict[str, SectorRS]:
        """Return neutral RS for all sectors (API error fallback)."""
        result = {sector: self._neutral_rs(sector) for sector in SECTOR_ETF_MAP}
        self._cache = result
        self._cache_time = time.time()
        return result

    def _neutral_rs(self, sector: str) -> SectorRS:
        """Create a neutral SectorRS entry."""
        return SectorRS(
            sector=sector,
            etf_symbol=SECTOR_ETF_MAP.get(sector, "???"),
            rs_ratio=100.0,
            rs_momentum=100.0,
            quadrant=RSQuadrant.LEADING,  # 100/100 is technically leading
            score_modifier=0.0,  # But modifier is 0 (neutral)
        )
