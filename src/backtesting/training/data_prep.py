# OptionPlay - Training Data Preparation
# =======================================
# Extracted from training/regime_trainer.py (Phase 6e)
#
# Handles VIX data normalization, data segmentation by regime,
# and trade opportunity generation.

import logging
from datetime import date
from typing import Any, Dict, List, Set

from ..models import (
    RegimeConfig,
    get_regime_for_vix,
)

logger = logging.getLogger(__name__)


class DataPrep:
    """Prepares and segments data for regime-based training."""

    def normalize_vix_data(self, vix_data: List[Dict]) -> Dict[date, float]:
        """Convert VIX data to {date: value} dict"""
        result = {}
        for point in vix_data:
            d = point.get("date")
            if isinstance(d, str):
                d = date.fromisoformat(d)
            value = point.get("close") or point.get("value")
            if d and value:
                result[d] = float(value)
        return result

    def segment_data_by_regime(
        self,
        historical_data: Dict[str, List[Dict]],
        vix_by_date: Dict[date, float],
        regimes: Dict[str, RegimeConfig],
        symbols: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Segment historical data by VIX regime.

        Returns dict of:
        {
            regime_name: {
                "dates": List[date],
                "trades": List[Dict],  # Simulated trade opportunities
                "vix_values": List[float],
            }
        }
        """
        segments: Dict[str, Dict] = {
            name: {"dates": [], "trades": [], "vix_values": []}
            for name in regimes.keys()
        }

        # Get all unique dates with both price and VIX data
        all_dates: Set[date] = set()
        for symbol in symbols:
            if symbol not in historical_data:
                continue
            for bar in historical_data[symbol]:
                d = bar.get("date")
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                if d in vix_by_date:
                    all_dates.add(d)

        # Segment dates by regime
        for d in sorted(all_dates):
            vix = vix_by_date.get(d)
            if vix is None:
                continue

            regime_name, _ = get_regime_for_vix(vix, regimes)
            segments[regime_name]["dates"].append(d)
            segments[regime_name]["vix_values"].append(vix)

        # Generate synthetic trade opportunities for each regime
        for regime_name, segment in segments.items():
            segment["trades"] = self.generate_trade_opportunities(
                regime_dates=set(segment["dates"]),
                historical_data=historical_data,
                symbols=symbols,
            )

        return segments

    def generate_trade_opportunities(
        self,
        regime_dates: Set[date],
        historical_data: Dict[str, List[Dict]],
        symbols: List[str],
    ) -> List[Dict]:
        """
        Generate potential trade opportunities within regime dates.

        This is a simplified simulation - actual trades would use
        the full analyzer pipeline.
        """
        opportunities = []

        for symbol in symbols:
            if symbol not in historical_data:
                continue

            bars = historical_data[symbol]
            bars_by_date = {}
            for bar in bars:
                d = bar.get("date")
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                bars_by_date[d] = bar

            for d in sorted(regime_dates):
                if d not in bars_by_date:
                    continue

                bar = bars_by_date[d]
                opportunities.append({
                    "symbol": symbol,
                    "date": d,
                    "price": bar.get("close", 0),
                    "volume": bar.get("volume", 0),
                })

        return opportunities
