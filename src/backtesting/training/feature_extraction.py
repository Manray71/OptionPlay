#!/usr/bin/env python3
"""
Feature Extraction for ML Weight Optimization

Extracted from ml_weight_optimizer.py for modularity.
Contains: TradeFeatures dataclass, FeatureExtractor class
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeFeatures:
    """Extracted features from a trade for ML training"""
    trade_id: str
    symbol: str
    strategy: str
    signal_date: date

    # Score components (features)
    components: Dict[str, float]

    # Target variable
    is_winner: bool
    pnl_percent: float

    # Context
    vix_at_signal: Optional[float]
    regime: Optional[str]
    holding_days: int


class FeatureExtractor:
    """Extract ML features from historical trades"""

    def __init__(self):
        self._regime_boundaries = {
            "low_vol": (0, 15),
            "normal": (15, 20),
            "elevated": (20, 30),
            "high_vol": (30, 100),
        }

    def extract_from_trades(
        self,
        trades: List[Dict[str, Any]],
    ) -> List[TradeFeatures]:
        """
        Extract features from list of trade dicts.

        Args:
            trades: List of trade records from TradeTracker

        Returns:
            List of TradeFeatures for ML training
        """
        features = []

        for trade in trades:
            # Skip incomplete trades
            if trade.get("outcome") not in ("WIN", "LOSS"):
                continue

            # Extract score breakdown
            breakdown = trade.get("score_breakdown", {})
            if isinstance(breakdown, str):
                try:
                    breakdown = json.loads(breakdown)
                except (json.JSONDecodeError, TypeError):
                    breakdown = {}

            if not breakdown:
                continue

            # Normalize component names
            components = {}
            for key, value in breakdown.items():
                # Handle nested dicts
                if isinstance(value, dict):
                    value = value.get("score", value.get("value", 0))
                if isinstance(value, (int, float)):
                    # Normalize key name
                    norm_key = key.lower()
                    if not norm_key.endswith("_score"):
                        norm_key = f"{norm_key}_score"
                    components[norm_key] = float(value)

            if not components:
                continue

            # Determine regime from VIX
            vix = trade.get("vix_at_signal")
            regime = self._get_regime(vix) if vix else None

            # Create features
            features.append(TradeFeatures(
                trade_id=str(trade.get("id", len(features))),
                symbol=trade.get("symbol", "UNKNOWN"),
                strategy=trade.get("strategy", "pullback"),
                signal_date=self._parse_date(trade.get("signal_date")),
                components=components,
                is_winner=trade.get("outcome") == "WIN",
                pnl_percent=float(trade.get("pnl_percent", 0)),
                vix_at_signal=vix,
                regime=regime,
                holding_days=int(trade.get("holding_days", 0)),
            ))

        logger.info(f"Extracted {len(features)} trade features from {len(trades)} trades")
        return features

    def _get_regime(self, vix: float) -> str:
        """Determine regime from VIX value"""
        for regime, (low, high) in self._regime_boundaries.items():
            if low <= vix < high:
                return regime
        return "normal"

    def _parse_date(self, d: Any) -> date:
        """Parse date from various formats"""
        if isinstance(d, date):
            return d
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, str):
            try:
                return date.fromisoformat(d[:10])
            except ValueError:
                logger.debug(f"Could not parse date string: {d!r}, using today")
        return date.today()
