"""
Alpha-Engine Stufe 1: Berechnet B + 1.5*F Score pro Symbol,
normalisiert auf Percentile-Rank, gibt Top-N Longlist zurueck.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

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


_cfg = _load_sector_rs_config()
_DEFAULT_FAST_WEIGHT = _cfg.get("fast_weight", 1.5)
_DEFAULT_LONGLIST_SIZE = _cfg.get("alpha_longlist_size", 30)


class AlphaScorer:
    """Generates Alpha-Longlist from watchlist symbols."""

    def __init__(
        self,
        sector_rs_service: Optional[SectorRSService] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        cfg = config or _cfg
        self._fast_weight: float = cfg.get("fast_weight", _DEFAULT_FAST_WEIGHT)
        self._default_top_n: int = cfg.get("alpha_longlist_size", _DEFAULT_LONGLIST_SIZE)

        if sector_rs_service is not None:
            self._sector_rs_service = sector_rs_service
        else:
            self._sector_rs_service = SectorRSService()

        self._sector_map: Dict[str, str] = {}

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

    async def generate_longlist(
        self,
        symbols: List[str],
        top_n: Optional[int] = None,
    ) -> List[AlphaCandidate]:
        if not symbols:
            return []

        if top_n is None:
            top_n = self._default_top_n

        self._build_sector_map(symbols)

        stock_rs_map = await self._sector_rs_service.get_all_stock_rs(symbols)

        scores: Dict[str, float] = {}
        stock_data = {}
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
