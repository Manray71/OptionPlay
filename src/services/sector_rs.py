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
        config_path = Path(__file__).resolve().parents[2] / "config" / "trading.yaml"
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
    # DB (Yahoo Finance) → GICS mapping
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Financial Services": "Financials",
    "Basic Materials": "Materials",
}

# Reverse mapping: GICS canonical → preferred DB (Yahoo Finance) name.
# Built explicitly to avoid silent overwrites when multiple aliases
# map to the same canonical name (dict comprehension keeps only last).
_SECTOR_REVERSE: Dict[str, str] = {}
for _alias, _canonical in _SECTOR_ALIASES.items():
    if _canonical not in _SECTOR_REVERSE:
        _SECTOR_REVERSE[_canonical] = _alias

# Default configuration — Slow window
DEFAULT_BENCHMARK = _cfg.get("benchmark", "SPY")
DEFAULT_LOOKBACK_DAYS = _cfg.get("lookback_days", 120)
DEFAULT_EMA_SLOW = _cfg.get("ema_slow", 50)
DEFAULT_MOMENTUM_LOOKBACK = _cfg.get("momentum_lookback", 14)
DEFAULT_CACHE_TTL_HOURS = _cfg.get("cache_ttl_hours", 8)

# Default configuration — Fast window (E.1)
DEFAULT_FAST_WINDOW = _cfg.get("fast_window", 20)
DEFAULT_FAST_EMA = _cfg.get("fast_ema", 10)
DEFAULT_FAST_MOMENTUM_LOOKBACK = _cfg.get("fast_momentum_lookback", 5)
DEFAULT_FAST_WEIGHT = _cfg.get("fast_weight", 1.5)

# Legacy alias kept for any code that still imports DEFAULT_EMA_FAST
DEFAULT_EMA_FAST = DEFAULT_FAST_EMA

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
    # Slow window (100d context, B)
    rs_ratio: float  # > 100 = outperforming benchmark
    rs_momentum: float  # > 100 = improving
    quadrant: RSQuadrant
    score_modifier: float  # Additive modifier for risk-filter (slow-based)
    # Fast window (20d signal, F) — E.1 additions; defaults preserve backward compat
    rs_ratio_fast: float = 100.0
    rs_momentum_fast: float = 100.0
    quadrant_fast: RSQuadrant = RSQuadrant.LEADING
    dual_label: str = ""  # e.g. "LAG→IMP" when slow=LAG, fast=IMP


@dataclass(frozen=True)
class StockRS:
    """Individual stock relative strength result (dual-window)."""

    symbol: str
    # Slow
    rs_ratio: float
    rs_momentum: float
    quadrant: RSQuadrant
    # Fast
    rs_ratio_fast: float
    rs_momentum_fast: float
    quadrant_fast: RSQuadrant
    # Composite
    dual_label: str
    # Raw scores for AlphaScorer (E.2)
    b_raw: float  # rs_ratio_slow - 100.0
    f_raw: float  # rs_ratio_fast - 100.0


def _compute_dual_label(slow: RSQuadrant, fast: RSQuadrant) -> str:
    """Build a compact dual-quadrant label like 'LAG→IMP'."""
    if slow == fast:
        return slow.value.upper()
    short = {
        "leading": "LEAD",
        "weakening": "WEAK",
        "lagging": "LAG",
        "improving": "IMP",
    }
    return f"{short[slow.value]}→{short[fast.value]}"


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


def _compute_ratio_ema(
    sector_closes: List[float],
    benchmark_closes: List[float],
    ema_period: int,
) -> List[float]:
    """Compute EMA-smoothed sector/benchmark ratio series."""
    if not sector_closes or not benchmark_closes or len(sector_closes) != len(benchmark_closes):
        return []

    ratios = []
    for s, b in zip(sector_closes, benchmark_closes):
        if b > 1e-9:
            ratios.append(s / b)
        else:
            # Benchmark price is zero or negative (bad data) — treat as neutral
            ratios.append(ratios[-1] if ratios else 1.0)

    return compute_ema(ratios, ema_period) if ratios else []


def compute_rs_ratio(
    sector_closes: List[float],
    benchmark_closes: List[float],
    ema_period: int = DEFAULT_EMA_SLOW,
) -> float:
    """
    Compute RS Ratio: EMA of (sector / benchmark), normalized against mean.

    Standard JdK normalization: current_ema / mean(ema) * 100.
    Returns value centered around 100:
    - > 100: sector outperforming benchmark (above average)
    - < 100: sector underperforming benchmark (below average)
    """
    ema_vals = _compute_ratio_ema(sector_closes, benchmark_closes, ema_period)
    if not ema_vals:
        return 100.0

    mean_ema = sum(ema_vals) / len(ema_vals)
    if mean_ema <= 0:
        return 100.0

    return (ema_vals[-1] / mean_ema) * 100.0


def compute_rs_ratio_series(
    sector_closes: List[float],
    benchmark_closes: List[float],
    ema_period: int = DEFAULT_EMA_SLOW,
) -> List[float]:
    """
    Compute full RS-Ratio time series (for momentum calculation).

    Returns list of RS-Ratio values centered around 100 (oldest first).
    """
    ema_vals = _compute_ratio_ema(sector_closes, benchmark_closes, ema_period)
    if not ema_vals:
        return []

    mean_ema = sum(ema_vals) / len(ema_vals)
    if mean_ema <= 0:
        return []

    return [(e / mean_ema) * 100.0 for e in ema_vals]


def compute_rs_momentum(
    sector_closes: List[float],
    benchmark_closes: List[float],
    ema_fast: int = DEFAULT_EMA_FAST,
    ema_slow: int = DEFAULT_EMA_SLOW,
    momentum_lookback: int = DEFAULT_MOMENTUM_LOOKBACK,
    ema_period: Optional[int] = None,
) -> float:
    """
    Compute RS Momentum: rate of change of the RS-Ratio over momentum_lookback days.

    Measures whether the sector's relative strength is accelerating or decelerating.

    Returns value centered around 100:
    - > 100: RS improving (sector gaining relative strength)
    - < 100: RS deteriorating (sector losing relative strength)

    Args:
        ema_period: If provided, overrides ema_slow (allows dual-window reuse).
    """
    effective_ema = ema_period if ema_period is not None else ema_slow
    rs_series = compute_rs_ratio_series(sector_closes, benchmark_closes, ema_period=effective_ema)

    if len(rs_series) <= momentum_lookback:
        return 100.0

    current_rs = rs_series[-1]
    past_rs = rs_series[-1 - momentum_lookback]

    if past_rs <= 0:
        return 100.0

    return (current_rs / past_rs) * 100.0


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
        return self._config.get("fast_ema", DEFAULT_FAST_EMA)

    @property
    def _ema_slow(self) -> int:
        return self._config.get("ema_slow", DEFAULT_EMA_SLOW)

    @property
    def _momentum_lookback(self) -> int:
        return self._config.get("momentum_lookback", DEFAULT_MOMENTUM_LOOKBACK)

    @property
    def _fast_window(self) -> int:
        return self._config.get("fast_window", DEFAULT_FAST_WINDOW)

    @property
    def _fast_ema(self) -> int:
        return self._config.get("fast_ema", DEFAULT_FAST_EMA)

    @property
    def _fast_momentum_lookback(self) -> int:
        return self._config.get("fast_momentum_lookback", DEFAULT_FAST_MOMENTUM_LOOKBACK)

    @property
    def _fast_weight(self) -> float:
        return self._config.get("fast_weight", DEFAULT_FAST_WEIGHT)

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
        Calculate dual-window RS for a single sector given price data.

        Args:
            sector: Sector name
            sector_closes: Sector ETF closing prices (oldest first)
            benchmark_closes: Benchmark closing prices (oldest first)
        """
        etf = SECTOR_ETF_MAP.get(sector, "???")

        # Slow window (100d context, B)
        rs_ratio = compute_rs_ratio(sector_closes, benchmark_closes, ema_period=self._ema_slow)
        rs_momentum = compute_rs_momentum(
            sector_closes,
            benchmark_closes,
            ema_slow=self._ema_slow,
            momentum_lookback=self._momentum_lookback,
        )
        quadrant = classify_quadrant(rs_ratio, rs_momentum)
        modifier = get_quadrant_modifier(quadrant)

        # Fast window (20d signal, F) — slice from same dataset
        fast_n = self._fast_window + 10  # 30-bar slice (20 + buffer)
        sector_fast = sector_closes[-fast_n:] if len(sector_closes) >= fast_n else sector_closes
        bench_fast = (
            benchmark_closes[-fast_n:] if len(benchmark_closes) >= fast_n else benchmark_closes
        )

        rs_ratio_fast = compute_rs_ratio(sector_fast, bench_fast, ema_period=self._fast_ema)
        rs_momentum_fast = compute_rs_momentum(
            sector_fast,
            bench_fast,
            ema_period=self._fast_ema,
            momentum_lookback=self._fast_momentum_lookback,
        )
        quadrant_fast = classify_quadrant(rs_ratio_fast, rs_momentum_fast)
        dual_label = _compute_dual_label(quadrant, quadrant_fast)

        return SectorRS(
            sector=sector,
            etf_symbol=etf,
            rs_ratio=round(rs_ratio, 2),
            rs_momentum=round(rs_momentum, 2),
            quadrant=quadrant,
            score_modifier=modifier,
            rs_ratio_fast=round(rs_ratio_fast, 2),
            rs_momentum_fast=round(rs_momentum_fast, 2),
            quadrant_fast=quadrant_fast,
            dual_label=dual_label,
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

    async def get_all_sector_rs_with_trail(
        self,
        trail_points: int = 4,
        trail_interval: int = 5,
    ) -> Dict[str, dict]:
        """
        Compute RS for all sectors with trailing tail data.

        Trail is computed by truncating price series at different offsets,
        using existing daily_prices data (no extra DB storage needed).

        Args:
            trail_points: Number of historical snapshots (default 4 = 4 weeks)
            trail_interval: Trading days between snapshots (default 5 = weekly)

        Returns:
            Dict mapping sector name -> {sector, etf, rs_ratio, rs_momentum,
            quadrant, score_modifier, trail: [{rs_ratio, rs_momentum}, ...]}
        """
        benchmark = self._benchmark
        extra_days = trail_points * trail_interval
        fetch_days = self._lookback_days + 10 + extra_days

        # Fetch all ETFs + benchmark in parallel
        symbols = list(SECTOR_ETF_MAP.values()) + [benchmark]
        tasks = [self._fetch_closes(sym, fetch_days) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        price_map: Dict[str, List[float]] = {}
        for sym, res in zip(symbols, results):
            if isinstance(res, list) and len(res) > 0:
                price_map[sym] = res

        benchmark_closes = price_map.get(benchmark)
        if benchmark_closes is None:
            logger.warning(f"No {benchmark} data for trail, returning neutral")
            return {
                sector: {
                    **{
                        k: v
                        for k, v in self._neutral_rs(sector).__dict__.items()
                        if k not in ("quadrant", "quadrant_fast")
                    },
                    "quadrant": self._neutral_rs(sector).quadrant.value,
                    "quadrant_fast": self._neutral_rs(sector).quadrant_fast.value,
                    "trail": [],
                    "trail_fast": [],
                }
                for sector in SECTOR_ETF_MAP
            }

        sector_results: Dict[str, dict] = {}
        offsets = list(range(trail_points * trail_interval, 0, -trail_interval)) + [0]
        fast_n = self._fast_window + 10  # 30-bar slice for fast window

        for sector, etf in SECTOR_ETF_MAP.items():
            etf_closes = price_map.get(etf)
            if etf_closes is None:
                nr = self._neutral_rs(sector)
                sector_results[sector] = {
                    "sector": nr.sector,
                    "etf_symbol": nr.etf_symbol,
                    "rs_ratio": nr.rs_ratio,
                    "rs_momentum": nr.rs_momentum,
                    "quadrant": nr.quadrant.value,
                    "score_modifier": nr.score_modifier,
                    "rs_ratio_fast": nr.rs_ratio_fast,
                    "rs_momentum_fast": nr.rs_momentum_fast,
                    "quadrant_fast": nr.quadrant_fast.value,
                    "dual_label": nr.dual_label,
                    "trail": [],
                    "trail_fast": [],
                }
                continue

            # Align lengths
            min_len = min(len(etf_closes), len(benchmark_closes))
            etf_aligned = etf_closes[-min_len:]
            bench_aligned = benchmark_closes[-min_len:]

            trail = []
            trail_fast = []
            for offset in offsets:
                if offset == 0:
                    sc = etf_aligned
                    bc = bench_aligned
                else:
                    sc = etf_aligned[:-offset]
                    bc = bench_aligned[:-offset]

                if len(sc) < self._ema_slow + self._momentum_lookback:
                    continue

                rs_ratio = compute_rs_ratio(sc, bc, ema_period=self._ema_slow)
                rs_momentum = compute_rs_momentum(
                    sc,
                    bc,
                    ema_slow=self._ema_slow,
                    momentum_lookback=self._momentum_lookback,
                )
                trail.append(
                    {
                        "rs_ratio": round(rs_ratio, 2),
                        "rs_momentum": round(rs_momentum, 2),
                    }
                )

                # Fast trail point — slice from this same truncated series
                sc_fast = sc[-fast_n:] if len(sc) >= fast_n else sc
                bc_fast = bc[-fast_n:] if len(bc) >= fast_n else bc
                rs_ratio_f = compute_rs_ratio(sc_fast, bc_fast, ema_period=self._fast_ema)
                rs_momentum_f = compute_rs_momentum(
                    sc_fast,
                    bc_fast,
                    ema_period=self._fast_ema,
                    momentum_lookback=self._fast_momentum_lookback,
                )
                trail_fast.append(
                    {
                        "rs_ratio": round(rs_ratio_f, 2),
                        "rs_momentum": round(rs_momentum_f, 2),
                    }
                )

            # Current values = last trail point
            current = trail[-1] if trail else {"rs_ratio": 100.0, "rs_momentum": 100.0}
            current_fast = (
                trail_fast[-1] if trail_fast else {"rs_ratio": 100.0, "rs_momentum": 100.0}
            )
            quadrant = classify_quadrant(current["rs_ratio"], current["rs_momentum"])
            quadrant_fast = classify_quadrant(current_fast["rs_ratio"], current_fast["rs_momentum"])

            sector_results[sector] = {
                "sector": sector,
                "etf_symbol": etf,
                "rs_ratio": current["rs_ratio"],
                "rs_momentum": current["rs_momentum"],
                "quadrant": quadrant.value,
                "score_modifier": get_quadrant_modifier(quadrant),
                "rs_ratio_fast": current_fast["rs_ratio"],
                "rs_momentum_fast": current_fast["rs_momentum"],
                "quadrant_fast": quadrant_fast.value,
                "dual_label": _compute_dual_label(quadrant, quadrant_fast),
                "trail": trail[:-1],  # Exclude current (it's in top-level fields)
                "trail_fast": trail_fast[:-1],
            }

        return sector_results

    async def get_all_stock_rs(self, symbols: List[str]) -> Dict[str, StockRS]:
        """
        Compute dual-window RS for all symbols vs SPY. Batch-optimised.

        Fetches SPY once, then all symbol closes in a single parallel gather.
        Result is cached alongside sector RS (same TTL).

        Args:
            symbols: List of ticker symbols (up to ~350 at once).

        Returns:
            Dict mapping symbol -> StockRS with slow + fast fields.
        """
        if not symbols:
            return {}

        benchmark = self._benchmark
        fetch_days = self._lookback_days + 10  # slow window buffer

        # Fetch SPY + all symbols in one parallel batch
        all_syms = [benchmark] + list(symbols)
        tasks = [self._fetch_closes(sym, fetch_days) for sym in all_syms]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        price_map: Dict[str, List[float]] = {}
        for sym, res in zip(all_syms, results):
            if isinstance(res, list) and len(res) > 0:
                price_map[sym] = res

        benchmark_closes = price_map.get(benchmark)
        if benchmark_closes is None:
            logger.warning(f"No {benchmark} data for stock RS batch")
            return {}

        fast_n = self._fast_window + 10

        stock_results: Dict[str, StockRS] = {}
        for sym in symbols:
            sym_closes = price_map.get(sym)
            if sym_closes is None:
                continue

            min_len = min(len(sym_closes), len(benchmark_closes))
            sc = sym_closes[-min_len:]
            bc = benchmark_closes[-min_len:]

            if len(sc) < self._ema_slow + self._momentum_lookback:
                continue

            # Slow RS
            rs_ratio = compute_rs_ratio(sc, bc, ema_period=self._ema_slow)
            rs_momentum = compute_rs_momentum(
                sc, bc, ema_slow=self._ema_slow, momentum_lookback=self._momentum_lookback
            )
            quadrant = classify_quadrant(rs_ratio, rs_momentum)

            # Fast RS (sliced)
            sc_fast = sc[-fast_n:] if len(sc) >= fast_n else sc
            bc_fast = bc[-fast_n:] if len(bc) >= fast_n else bc
            rs_ratio_fast = compute_rs_ratio(sc_fast, bc_fast, ema_period=self._fast_ema)
            rs_momentum_fast = compute_rs_momentum(
                sc_fast,
                bc_fast,
                ema_period=self._fast_ema,
                momentum_lookback=self._fast_momentum_lookback,
            )
            quadrant_fast = classify_quadrant(rs_ratio_fast, rs_momentum_fast)

            stock_results[sym] = StockRS(
                symbol=sym,
                rs_ratio=round(rs_ratio, 4),
                rs_momentum=round(rs_momentum, 4),
                quadrant=quadrant,
                rs_ratio_fast=round(rs_ratio_fast, 4),
                rs_momentum_fast=round(rs_momentum_fast, 4),
                quadrant_fast=quadrant_fast,
                dual_label=_compute_dual_label(quadrant, quadrant_fast),
                b_raw=round(rs_ratio - 100.0, 4),
                f_raw=round(rs_ratio_fast - 100.0, 4),
            )

        return stock_results

    async def get_stock_rs_with_trail(
        self,
        limit: int = 20,
        sector: Optional[str] = None,
        trail_points: int = 4,
        trail_interval: int = 5,
    ) -> List[dict]:
        """
        Compute RS for top liquid individual stocks vs SPY, with trailing tails.

        Args:
            limit: Number of stocks (top by liquidity)
            sector: Optional sector filter (e.g. "Technology")
            trail_points: Historical snapshots (default 4 = 4 weeks)
            trail_interval: Trading days between snapshots (default 5 = weekly)

        Returns:
            List of dicts: {symbol, sector, rs_ratio, rs_momentum, quadrant, trail}
        """
        try:
            from ..cache import get_fundamentals_manager

            manager = get_fundamentals_manager()
            if sector:
                # Filter by sector: get all sector stocks, sort by liquidity
                all_sector = manager.get_symbols_by_sector(sector)
                # Also check aliases (forward: DB→GICS)
                canonical = normalize_sector_name(sector)
                if canonical != sector:
                    all_sector += manager.get_symbols_by_sector(canonical)
                # Also check reverse aliases (GICS→DB)
                reverse = _SECTOR_REVERSE.get(sector)
                if reverse and reverse != sector:
                    all_sector += manager.get_symbols_by_sector(reverse)
                # Filter Tier 1+2, sort by avg_put_oi
                # Fallback: if liquidity classification hasn't run yet (most tiers NULL),
                # include all sector symbols so RRG still works
                tier_qualified = [f for f in all_sector if (f.liquidity_tier or 99) <= 2]
                pool = tier_qualified if len(tier_qualified) >= 3 else all_sector
                top_stocks = sorted(
                    pool,
                    key=lambda f: f.avg_put_oi or 0,
                    reverse=True,
                )[:limit]
            else:
                top_stocks = manager.get_top_liquid_symbols(limit=limit)
        except Exception as e:
            logger.warning(f"Could not get liquid symbols: {e}")
            return []

        if not top_stocks:
            return []

        benchmark = self._benchmark
        extra_days = trail_points * trail_interval
        fetch_days = self._lookback_days + 10 + extra_days

        # Fetch all stock prices + benchmark in parallel
        symbols = [f.symbol for f in top_stocks] + [benchmark]
        tasks = [self._fetch_closes(sym, fetch_days) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        price_map: Dict[str, List[float]] = {}
        for sym, res in zip(symbols, results):
            if isinstance(res, list) and len(res) > 0:
                price_map[sym] = res

        benchmark_closes = price_map.get(benchmark)
        if benchmark_closes is None:
            logger.warning(f"No {benchmark} data for stock RS")
            return []

        # Build sector lookup
        sector_lookup = {f.symbol: f.sector or "Unknown" for f in top_stocks}
        offsets = list(range(trail_points * trail_interval, 0, -trail_interval)) + [0]

        stock_results: List[dict] = []
        for f in top_stocks:
            stock_closes = price_map.get(f.symbol)
            if stock_closes is None:
                continue

            min_len = min(len(stock_closes), len(benchmark_closes))
            stock_aligned = stock_closes[-min_len:]
            bench_aligned = benchmark_closes[-min_len:]

            trail = []
            for offset in offsets:
                sc = stock_aligned[:-offset] if offset > 0 else stock_aligned
                bc = bench_aligned[:-offset] if offset > 0 else bench_aligned

                if len(sc) < self._ema_slow + self._momentum_lookback:
                    continue

                rs_ratio = compute_rs_ratio(sc, bc, ema_period=self._ema_slow)
                rs_momentum = compute_rs_momentum(
                    sc,
                    bc,
                    ema_slow=self._ema_slow,
                    momentum_lookback=self._momentum_lookback,
                )
                trail.append(
                    {
                        "rs_ratio": round(rs_ratio, 2),
                        "rs_momentum": round(rs_momentum, 2),
                    }
                )

            current = trail[-1] if trail else {"rs_ratio": 100.0, "rs_momentum": 100.0}
            quadrant = classify_quadrant(current["rs_ratio"], current["rs_momentum"])

            stock_results.append(
                {
                    "symbol": f.symbol,
                    "sector": sector_lookup.get(f.symbol, "Unknown"),
                    "rs_ratio": current["rs_ratio"],
                    "rs_momentum": current["rs_momentum"],
                    "quadrant": quadrant.value,
                    "trail": trail[:-1],
                }
            )

        return stock_results

    def get_cached_sector_rs(self, sector: str) -> Optional[SectorRS]:
        """
        Get cached SectorRS for a canonical sector name (synchronous).

        Returns None if not cached or cache expired.
        Use this instead of accessing _cache directly.
        """
        if not self._is_cache_valid():
            return None
        return self._cache.get(sector)

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
            rs_ratio_fast=100.0,
            rs_momentum_fast=100.0,
            quadrant_fast=RSQuadrant.LEADING,
            dual_label="LEADING",
        )
