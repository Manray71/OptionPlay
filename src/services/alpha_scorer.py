"""
Alpha-Engine Stufe 1: Berechnet B + 1.5*F Score pro Symbol,
normalisiert auf Percentile-Rank, gibt Top-N Longlist zurueck.

E.2b.4: Wenn alpha_composite.enabled = true, wird TechnicalComposite
statt RS-only fuer B und F verwendet. Feature-Flag bleibt false bis E.2b.5.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from src.data_providers.local_db import LocalDBProvider
from src.models.alpha import AlphaCandidate
from src.services.sector_rs import RSQuadrant, SectorRSService, normalize_sector_name

logger = logging.getLogger(__name__)


def _load_sector_rs_config() -> Dict[str, Any]:
    try:
        config_path = Path(__file__).resolve().parents[2] / "config" / "trading.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
                return data.get("sector_rs", {})
    except Exception:
        pass
    return {}


def _load_alpha_composite_config() -> Dict[str, Any]:
    try:
        config_path = Path(__file__).resolve().parents[2] / "config" / "trading.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
                return data.get("alpha_composite", {})
    except Exception:
        pass
    return {}


_cfg = _load_sector_rs_config()
_composite_cfg = _load_alpha_composite_config()
_DEFAULT_FAST_WEIGHT = _cfg.get("fast_weight", 1.5)
_DEFAULT_LONGLIST_SIZE = _cfg.get("alpha_longlist_size", 30)
_MIN_BARS_CLASSIC = 135  # 125d window + 10d buffer
_MIN_BARS_FAST = 30  # 20d window + 10d buffer


class AlphaScorer:
    """Generates Alpha-Longlist from watchlist symbols."""

    def __init__(
        self,
        sector_rs_service: Optional[SectorRSService] = None,
        config: Optional[Dict[str, Any]] = None,
        composite_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        cfg = config or _cfg
        self._fast_weight: float = cfg.get("fast_weight", _DEFAULT_FAST_WEIGHT)
        self._default_top_n: int = cfg.get("alpha_longlist_size", _DEFAULT_LONGLIST_SIZE)

        if sector_rs_service is not None:
            self._sector_rs_service = sector_rs_service
        else:
            self._sector_rs_service = SectorRSService(provider=LocalDBProvider())

        self._sector_map: Dict[str, str] = {}

        # E.2b.4: Composite feature flag
        comp_cfg = composite_config if composite_config is not None else _composite_cfg
        self._composite_enabled: bool = comp_cfg.get("enabled", False)
        self._composite = None
        if self._composite_enabled:
            from src.services.technical_composite import TechnicalComposite

            self._composite = TechnicalComposite(comp_cfg)

        # Post-Crash weights (active when _is_post_crash() == True)
        pc_cfg = comp_cfg.get("post_crash", {})
        self._pc_classic_weight: float = float(pc_cfg.get("classic_weight", 0.3))
        self._pc_fast_weight_adj: float = float(pc_cfg.get("fast_weight_adj", 0.7))

    def _build_sector_map(self, symbols: List[str]) -> None:
        """Batch-load sector mapping from fundamentals DB."""
        try:
            from src.cache import get_fundamentals_manager

            manager = get_fundamentals_manager()
            batch = manager.get_fundamentals_batch(symbols)
            for sym, f in batch.items():
                sector = f.sector or "Unknown"
                self._sector_map[sym] = normalize_sector_name(sector)
        except Exception as e:
            logger.debug(f"Could not load fundamentals for sector map: {e}")

    def _get_sector_for_symbol(self, symbol: str) -> str:
        return self._sector_map.get(symbol, "Unknown")

    def _is_post_crash(self, vix: Optional[float] = None) -> bool:
        """Simplified stress check based on VIX. Full stress score in E.2b.5."""
        if vix is not None and vix >= 25:
            return True
        return False

    async def _load_batch_ohlcv(self, symbols: List[str]) -> Dict[str, Optional[Tuple]]:
        """Load OHLCV for all symbols using one DB connection open."""
        try:
            db = LocalDBProvider()
            return await db.get_batch_ohlcv(symbols, limit=260)
        except Exception as e:
            logger.warning(f"Batch OHLCV load failed, composite disabled for this run: {e}")
            return {}

    async def generate_longlist(
        self,
        symbols: List[str],
        top_n: Optional[int] = None,
        vix: Optional[float] = None,
    ) -> List[AlphaCandidate]:
        if not symbols:
            return []

        if top_n is None:
            top_n = self._default_top_n

        self._build_sector_map(symbols)

        stock_rs_map = await self._sector_rs_service.get_all_stock_rs(symbols)

        scores: Dict[str, float] = {}
        stock_data = {}
        composite_data: Dict[str, Tuple] = {}  # {sym: (b_score, f_score)}

        if self._composite_enabled and self._composite is not None:
            is_post_crash = self._is_post_crash(vix=vix)
            all_ohlcv = await self._load_batch_ohlcv(list(stock_rs_map.keys()))

            for sym, rs in stock_rs_map.items():
                ohlcv = all_ohlcv.get(sym)
                classic_quad = rs.quadrant.value.upper()
                fast_quad = rs.quadrant_fast.value.upper()

                if ohlcv is None or len(ohlcv[0]) < _MIN_BARS_FAST:
                    # Not enough data — fall back to RS-only for this symbol
                    logger.debug(
                        f"{sym}: insufficient OHLCV ({len(ohlcv[0]) if ohlcv else 0} bars), "
                        "using RS fallback"
                    )
                    scores[sym] = rs.b_raw + self._fast_weight * rs.f_raw
                    stock_data[sym] = rs
                    continue

                closes, volumes, highs, lows, opens = ohlcv

                b_score = self._composite.compute(
                    symbol=sym,
                    closes=closes[-_MIN_BARS_CLASSIC:],
                    highs=highs[-_MIN_BARS_CLASSIC:],
                    lows=lows[-_MIN_BARS_CLASSIC:],
                    volumes=volumes[-_MIN_BARS_CLASSIC:],
                    opens=opens[-_MIN_BARS_CLASSIC:],
                    timeframe="classic",
                    classic_quadrant=classic_quad,
                    fast_quadrant=fast_quad,
                )
                f_score = self._composite.compute(
                    symbol=sym,
                    closes=closes[-_MIN_BARS_FAST:],
                    highs=highs[-_MIN_BARS_FAST:],
                    lows=lows[-_MIN_BARS_FAST:],
                    volumes=volumes[-_MIN_BARS_FAST:],
                    opens=opens[-_MIN_BARS_FAST:],
                    timeframe="fast",
                    classic_quadrant=classic_quad,
                    fast_quadrant=fast_quad,
                )

                if is_post_crash:
                    alpha_raw = (
                        b_score.total * self._pc_classic_weight
                        + f_score.total * self._pc_fast_weight_adj * 1.5
                    )
                else:
                    alpha_raw = b_score.total + f_score.total * 1.5

                scores[sym] = alpha_raw
                stock_data[sym] = rs
                composite_data[sym] = (b_score, f_score)
        else:
            # RS-only path (original behaviour)
            for sym, rs in stock_rs_map.items():
                raw = rs.b_raw + self._fast_weight * rs.f_raw
                scores[sym] = raw
                stock_data[sym] = rs

        if not scores:
            return []

        percentiles = self._compute_percentile_ranks(scores)

        candidates = []
        for sym, raw in scores.items():
            rs = stock_data[sym]
            b_comp_total: Optional[float] = None
            f_comp_total: Optional[float] = None
            breakout_sigs: Tuple[str, ...] = ()
            pre_bo = False

            if sym in composite_data:
                b_sc, f_sc = composite_data[sym]
                b_comp_total = round(b_sc.total, 4)
                f_comp_total = round(f_sc.total, 4)
                # Combine breakout signals from both windows (fast is primary)
                breakout_sigs = tuple(
                    dict.fromkeys(list(f_sc.breakout_signals) + list(b_sc.breakout_signals))
                )
                pre_bo = f_sc.pre_breakout or b_sc.pre_breakout

            candidates.append(
                AlphaCandidate(
                    symbol=sym,
                    b_raw=rs.b_raw,
                    f_raw=rs.f_raw,
                    alpha_raw=round(raw, 4),
                    alpha_percentile=percentiles[sym],
                    quadrant_slow=rs.quadrant,
                    quadrant_fast=rs.quadrant_fast,
                    dual_label=rs.dual_label,
                    sector=self._get_sector_for_symbol(sym),
                    b_composite=b_comp_total,
                    f_composite=f_comp_total,
                    breakout_signals=breakout_sigs,
                    pre_breakout=pre_bo,
                )
            )

        candidates.sort(key=lambda c: (-c.alpha_percentile, -c.alpha_raw))
        return candidates[:top_n]

    def _compute_percentile_ranks(
        self,
        scores: Dict[str, float],
    ) -> Dict[str, int]:
        if not scores:
            return {}
        sorted_syms = sorted(scores.keys(), key=lambda s: scores[s])
        n = len(sorted_syms)
        return {
            sym: round((rank / (n - 1)) * 100) if n > 1 else 50
            for rank, sym in enumerate(sorted_syms)
        }

    # =========================================================================
    # Sector-Level Alpha Summary (E.2.3)
    # =========================================================================

    async def get_sector_alpha_summary(self) -> List[dict]:
        """Sector-level dual-quadrant + ampel for all 11 GICS sectors."""
        sector_rs = await self._sector_rs_service.get_all_sector_rs()
        summary = []
        for sector, rs in sector_rs.items():
            ampel = self._compute_ampel(rs.quadrant, rs.quadrant_fast)
            summary.append(
                {
                    "sector": sector,
                    "etf": rs.etf_symbol,
                    "quadrant_slow": rs.quadrant.value,
                    "quadrant_fast": rs.quadrant_fast.value,
                    "dual_label": rs.dual_label,
                    "ampel": ampel["color"],
                    "ampel_text": ampel["text"],
                    "score_modifier": rs.score_modifier,
                }
            )
        return summary

    @staticmethod
    def _compute_ampel(slow: RSQuadrant, fast: RSQuadrant) -> dict:
        bullish = {RSQuadrant.IMPROVING, RSQuadrant.LEADING}
        bearish = {RSQuadrant.WEAKENING, RSQuadrant.LAGGING}

        if slow in bullish and fast in bullish:
            return {"color": "green", "text": "Tradeable"}
        elif fast in bullish and slow in bearish:
            return {"color": "yellow", "text": "Vorsicht — 100d noch schwach"}
        elif slow in bearish and fast in bearish:
            return {"color": "red", "text": "Not tradeable"}
        else:
            return {"color": "yellow", "text": "Vorsicht — 20d schwächt sich ab"}


# =============================================================================
# SHARED PIPELINE HELPER (E.3)
# =============================================================================


async def get_alpha_filtered_symbols(
    full_watchlist: List[str],
    config: Optional[Dict[str, Any]] = None,
) -> tuple:
    """
    Returns (filtered_symbols, alpha_map).

    alpha_map: {symbol: AlphaCandidate} for downstream enrichment.
    Falls deaktiviert oder Fehler: (full_watchlist, {}).

    The caller is responsible for passing the broadest available universe
    (default_275 + extended_600 merged, deduplicated).
    """
    cfg = config or {}
    sector_rs_cfg = cfg.get("sector_rs", {})

    if not sector_rs_cfg.get("alpha_engine_enabled", False):
        return full_watchlist, {}

    try:
        scorer = AlphaScorer()
        top_n = sector_rs_cfg.get("alpha_longlist_size", _DEFAULT_LONGLIST_SIZE)
        longlist = await scorer.generate_longlist(full_watchlist, top_n=top_n)
        if longlist:
            logger.info(f"Alpha-Longlist: {len(longlist)} from {len(full_watchlist)} symbols")
            return [c.symbol for c in longlist], {c.symbol: c for c in longlist}
        else:
            logger.warning("Alpha-Longlist empty, falling back to full watchlist")
    except Exception as e:
        logger.error(f"Alpha-Engine error, fallback to full watchlist: {e}")

    return full_watchlist, {}
