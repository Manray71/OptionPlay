# OptionPlay - Sector Cycle Service
# ===================================
"""
Calculates sector momentum factors for dynamic scoring adjustment.

Uses sector ETFs vs SPY to determine which sectors are in favor/out of favor.
Results are cached with configurable TTL (default 4 hours).

Usage:
    from src.services.sector_cycle_service import SectorCycleService

    service = SectorCycleService()
    statuses = await service.get_all_sector_statuses()
    factor = await service.get_sector_factor("Technology")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import numpy as np

from ..config.scoring_config import get_scoring_resolver

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS (loaded from config/scoring_weights.yaml → sector_cycle section)
# =============================================================================

_sc_cfg = get_scoring_resolver().get_sector_cycle_config()
_sc_weights = _sc_cfg.get("weights", {})
_sc_breadth = _sc_cfg.get("breadth", {})
_sc_regime = _sc_cfg.get("regime", {})
_sc_rs = _sc_cfg.get("rs_scale", {})

# Cache TTL
SECTOR_CACHE_TTL_HOURS = _sc_cfg.get("cache_ttl_hours", 4)

# Factor range (clamping bounds)
SECTOR_FACTOR_MAX = _sc_cfg.get("factor_max", 1.5)
SECTOR_FACTOR_MIN = _sc_cfg.get("factor_min", 0.6)

# Lookback periods (days)
SECTOR_LOOKBACK_SHORT = _sc_cfg.get("lookback_short", 30)
SECTOR_LOOKBACK_LONG = _sc_cfg.get("lookback_long", 60)

# Component weights for momentum factor calculation
SECTOR_WEIGHT_RS_30D = _sc_weights.get("rs_30d", 0.40)
SECTOR_WEIGHT_RS_60D = _sc_weights.get("rs_60d", 0.30)
SECTOR_WEIGHT_BREADTH = _sc_weights.get("breadth", 0.20)
SECTOR_WEIGHT_VOL_PREMIUM = _sc_weights.get("vol_premium", 0.10)

# Breadth proxy defaults
BREADTH_PROXY_NEUTRAL = _sc_breadth.get("proxy_neutral", 0.5)
BREADTH_NORM_FLOOR = _sc_breadth.get("norm_floor", 0.95)
BREADTH_NORM_RANGE = _sc_breadth.get("norm_range", 0.10)

# Regime classification thresholds
SECTOR_REGIME_STRONG = _sc_regime.get("strong", 1.05)
SECTOR_REGIME_NEUTRAL = _sc_regime.get("neutral", 0.90)
SECTOR_REGIME_WEAK = _sc_regime.get("weak", 0.70)

# Relative strength normalization scales
SECTOR_RS_30D_SCALE = _sc_rs.get("d30", 10.0)
SECTOR_RS_60D_SCALE = _sc_rs.get("d60", 15.0)

# Extra days fetched beyond lookback
SECTOR_FETCH_BUFFER_DAYS = _sc_cfg.get("fetch_buffer_days", 10)


# =============================================================================
# Data Models
# =============================================================================


class SectorRegime(str, Enum):
    """Sector momentum regime classification."""

    STRONG = "strong"
    NEUTRAL = "neutral"
    WEAK = "weak"
    CRISIS = "crisis"


@dataclass(frozen=True)
class SectorStatus:
    """Sector momentum analysis result."""

    sector: str
    etf_symbol: str
    relative_strength_30d: float
    relative_strength_60d: float
    breadth_proxy: float
    vol_premium: float
    momentum_factor: float
    regime: SectorRegime


# =============================================================================
# Service
# =============================================================================


class SectorCycleService:
    """
    Service for sector momentum analysis and dynamic scoring factors.

    Fetches all sector ETFs in parallel, calculates momentum factors,
    and caches results for configured TTL.
    """

    def __init__(self, provider=None) -> None:
        """
        Args:
            provider: MarketDataProvider or compatible (must have get_historical).
                      If None, will be resolved lazily.
        """
        self._provider = provider
        self._cache: Dict[str, SectorStatus] = {}
        self._cache_time: float = 0
        self._config = get_scoring_resolver().get_sector_momentum_config()

    @property
    def _ttl_seconds(self) -> float:
        return self._config.get("cache_ttl_hours", SECTOR_CACHE_TTL_HOURS) * 3600

    @property
    def _etf_mapping(self) -> Dict[str, str]:
        return self._config.get(
            "etf_mapping",
            {
                "Technology": "XLK",
                "Healthcare": "XLV",
                "Financials": "XLF",
                "Consumer Discretionary": "XLY",
                "Consumer Staples": "XLP",
                "Energy": "XLE",
                "Industrials": "XLI",
                "Communication Services": "XLC",
                "Utilities": "XLU",
                "Materials": "XLB",
                "Real Estate": "XLRE",
            },
        )

    @property
    def _factor_range(self) -> Dict[str, float]:
        return self._config.get(
            "factor_range", {"min": SECTOR_FACTOR_MIN, "max": SECTOR_FACTOR_MAX}
        )

    @property
    def _lookback_days(self) -> Dict[str, int]:
        return self._config.get(
            "lookback_days", {"short": SECTOR_LOOKBACK_SHORT, "long": SECTOR_LOOKBACK_LONG}
        )

    @property
    def _component_weights(self) -> Dict[str, float]:
        return self._config.get(
            "component_weights",
            {
                "relative_strength_30d": SECTOR_WEIGHT_RS_30D,
                "relative_strength_60d": SECTOR_WEIGHT_RS_60D,
                "breadth": SECTOR_WEIGHT_BREADTH,
                "vol_premium": SECTOR_WEIGHT_VOL_PREMIUM,
            },
        )

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
            logger.warning("Could not resolve market data provider")
        return self._provider

    async def _fetch_historical(self, symbol: str, days: int) -> Optional[List[float]]:
        """Fetch historical closing prices for a symbol."""
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

    def _calculate_return(self, prices: List[float], days: int) -> float:
        """Calculate return over N days."""
        if not prices or len(prices) < days + 1:
            return 0.0
        return (prices[-1] / prices[-(days + 1)] - 1) * 100

    def _calculate_volatility(self, prices: List[float], days: int) -> float:
        """Calculate annualized volatility over N days."""
        if not prices or len(prices) < days + 1:
            return 0.0
        returns = np.diff(np.log(np.array(prices[-days:])))
        if len(returns) == 0:
            return 0.0
        return float(np.std(returns) * np.sqrt(252) * 100)

    def _calculate_breadth_proxy(self, prices: List[float]) -> float:
        """Breadth proxy: price / 50-SMA, normalized to 0-1."""
        if not prices or len(prices) < 50:
            return BREADTH_PROXY_NEUTRAL  # Neutral
        sma50 = float(np.mean(prices[-50:]))
        if sma50 <= 0:
            return BREADTH_PROXY_NEUTRAL
        ratio = prices[-1] / sma50
        # Normalize: 0.95 → 0, 1.05 → 1, clamped
        normalized = (ratio - BREADTH_NORM_FLOOR) / BREADTH_NORM_RANGE
        return max(0.0, min(1.0, normalized))

    def _classify_regime(self, factor: float) -> SectorRegime:
        """Classify sector regime based on momentum factor."""
        if factor >= SECTOR_REGIME_STRONG:
            return SectorRegime.STRONG
        elif factor >= SECTOR_REGIME_NEUTRAL:
            return SectorRegime.NEUTRAL
        elif factor >= SECTOR_REGIME_WEAK:
            return SectorRegime.WEAK
        else:
            return SectorRegime.CRISIS

    async def get_all_sector_statuses(self) -> List[SectorStatus]:
        """
        Fetch and calculate momentum for all sectors in parallel.

        Returns cached results if within TTL.
        """
        if self._is_cache_valid():
            return list(self._cache.values())

        etf_mapping = self._etf_mapping
        lookback = self._lookback_days
        max_days = (
            max(
                lookback.get("short", SECTOR_LOOKBACK_SHORT),
                lookback.get("long", SECTOR_LOOKBACK_LONG),
            )
            + SECTOR_FETCH_BUFFER_DAYS
        )

        # Fetch all ETFs + SPY in parallel
        symbols = list(etf_mapping.values()) + ["SPY"]
        tasks = [self._fetch_historical(sym, max_days) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build price map
        price_map: Dict[str, List[float]] = {}
        for sym, res in zip(symbols, results):
            if isinstance(res, list) and len(res) > 0:
                price_map[sym] = res
            elif isinstance(res, Exception):
                logger.debug(f"Error fetching {sym}: {res}")

        spy_prices = price_map.get("SPY")
        if spy_prices is None:
            logger.warning("No SPY data, returning neutral factors")
            return self._neutral_fallback()

        spy_vol = self._calculate_volatility(
            spy_prices, lookback.get("short", SECTOR_LOOKBACK_SHORT)
        )
        component_weights = self._component_weights
        factor_min = self._factor_range.get("min", SECTOR_FACTOR_MIN)
        factor_max = self._factor_range.get("max", SECTOR_FACTOR_MAX)

        statuses: List[SectorStatus] = []
        for sector, etf in etf_mapping.items():
            etf_prices = price_map.get(etf)
            if etf_prices is None:
                statuses.append(self._neutral_status(sector, etf))
                continue

            # Calculate components
            short_days = lookback.get("short", SECTOR_LOOKBACK_SHORT)
            long_days = lookback.get("long", SECTOR_LOOKBACK_LONG)

            etf_return_short = self._calculate_return(etf_prices, short_days)
            spy_return_short = self._calculate_return(spy_prices, short_days)
            rs_30d = etf_return_short - spy_return_short

            etf_return_long = self._calculate_return(etf_prices, long_days)
            spy_return_long = self._calculate_return(spy_prices, long_days)
            rs_60d = etf_return_long - spy_return_long

            breadth = self._calculate_breadth_proxy(etf_prices)

            etf_vol = self._calculate_volatility(etf_prices, short_days)
            vol_premium = (etf_vol / spy_vol - 1) if spy_vol > 0 else 0.0

            # Weighted combination → raw factor
            # Normalize components to similar scales
            rs_30d_norm = max(-1.0, min(1.0, rs_30d / SECTOR_RS_30D_SCALE))  # ±10% → ±1
            rs_60d_norm = max(-1.0, min(1.0, rs_60d / SECTOR_RS_60D_SCALE))  # ±15% → ±1
            breadth_norm = breadth * 2 - 1  # 0-1 → -1 to 1
            vol_prem_norm = max(-1.0, min(1.0, -vol_premium))  # Negative: high vol is bad

            raw = (
                component_weights.get("relative_strength_30d", SECTOR_WEIGHT_RS_30D) * rs_30d_norm
                + component_weights.get("relative_strength_60d", SECTOR_WEIGHT_RS_60D) * rs_60d_norm
                + component_weights.get("breadth", SECTOR_WEIGHT_BREADTH) * breadth_norm
                + component_weights.get("vol_premium", SECTOR_WEIGHT_VOL_PREMIUM) * vol_prem_norm
            )

            # Scale raw (-1 to 1) to factor range (e.g., 0.6 to 1.2)
            mid = (factor_min + factor_max) / 2
            span = (factor_max - factor_min) / 2
            factor = mid + raw * span
            factor = max(factor_min, min(factor_max, factor))

            status = SectorStatus(
                sector=sector,
                etf_symbol=etf,
                relative_strength_30d=round(rs_30d, 2),
                relative_strength_60d=round(rs_60d, 2),
                breadth_proxy=round(breadth, 3),
                vol_premium=round(vol_premium, 3),
                momentum_factor=round(factor, 3),
                regime=self._classify_regime(factor),
            )
            statuses.append(status)

        # Update cache
        self._cache = {s.sector: s for s in statuses}
        self._cache_time = time.time()

        return statuses

    async def get_sector_factor(self, sector: str, strategy: Optional[str] = None) -> float:
        """
        Get momentum factor for a single sector, optionally strategy-adjusted (v3).

        When strategy is provided, the raw momentum factor is re-clamped
        to the strategy-specific factor_range from scoring_weights.yaml.

        Returns 1.0 (neutral) if sector not found or on error.
        """
        if not self._is_cache_valid():
            await self.get_all_sector_statuses()

        status = self._cache.get(sector)
        if not status:
            return 1.0

        if not strategy:
            return status.momentum_factor

        # v3: Re-clamp to strategy-specific range
        return self._apply_strategy_factor_range(status, strategy)

    def _apply_strategy_factor_range(self, status: SectorStatus, strategy: str) -> float:
        """
        Re-calculate factor with strategy-specific range and component weights (v3).

        Instead of just clamping the existing factor, we recalculate
        from raw components using the strategy's component_weights and
        clamp to the strategy's factor_range.
        """
        resolver = get_scoring_resolver()
        factor_range, comp_weights = resolver.get_sector_factor_config(strategy)

        factor_min = factor_range.get("min", SECTOR_FACTOR_MIN)
        factor_max = factor_range.get("max", SECTOR_FACTOR_MAX)

        # Normalize components (same as get_all_sector_statuses)
        rs_30d_norm = max(-1.0, min(1.0, status.relative_strength_30d / SECTOR_RS_30D_SCALE))
        rs_60d_norm = max(-1.0, min(1.0, status.relative_strength_60d / SECTOR_RS_60D_SCALE))
        breadth_norm = status.breadth_proxy * 2 - 1
        vol_prem_norm = max(-1.0, min(1.0, -status.vol_premium))

        raw = (
            comp_weights.get("relative_strength_30d", SECTOR_WEIGHT_RS_30D) * rs_30d_norm
            + comp_weights.get("relative_strength_60d", SECTOR_WEIGHT_RS_60D) * rs_60d_norm
            + comp_weights.get("breadth", SECTOR_WEIGHT_BREADTH) * breadth_norm
            + comp_weights.get("vol_premium", SECTOR_WEIGHT_VOL_PREMIUM) * vol_prem_norm
        )

        # Scale raw (-1 to 1) to strategy-specific factor range
        mid = (factor_min + factor_max) / 2
        span = (factor_max - factor_min) / 2
        factor = mid + raw * span
        return max(factor_min, min(factor_max, factor))

    async def get_sector_status(self, sector: str) -> Optional[SectorStatus]:
        """Get full status for a single sector."""
        if not self._is_cache_valid():
            await self.get_all_sector_statuses()
        return self._cache.get(sector)

    def _neutral_fallback(self) -> List[SectorStatus]:
        """Return neutral factors for all sectors (API error fallback)."""
        statuses = []
        for sector, etf in self._etf_mapping.items():
            statuses.append(self._neutral_status(sector, etf))
        self._cache = {s.sector: s for s in statuses}
        self._cache_time = time.time()
        return statuses

    def _neutral_status(self, sector: str, etf: str) -> SectorStatus:
        return SectorStatus(
            sector=sector,
            etf_symbol=etf,
            relative_strength_30d=0.0,
            relative_strength_60d=0.0,
            breadth_proxy=0.5,
            vol_premium=0.0,
            momentum_factor=1.0,
            regime=SectorRegime.NEUTRAL,
        )
