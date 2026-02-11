# OptionPlay - Signal Filter
# ==========================
"""
Filter-Logik für Trading-Signale nach PLAYBOOK-Regeln.

Extrahiert aus recommendation_engine.py (Phase 3.2).
Enthält reine Filter-Logik: Blacklist, Stability, Sektor-Diversifikation.
"""

# mypy: warn_unused_ignores=False
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ..cache.symbol_fundamentals import SymbolFundamentals
from ..constants.trading_rules import (
    get_adjusted_stability_min,
    is_blacklisted,
)

# Relative imports
from ..models.base import TradeSignal


def check_symbol_stability(
    symbol: str,
    current_vix: Optional[float] = None,
    fundamentals_manager: Any = None,
) -> tuple[bool, float, float]:
    """
    Check if a symbol meets the VIX-adjusted stability requirement.

    Shared logic used by TradeValidator, PositionMonitor, and signal filters.
    Consolidates stability checking (Task 2.4).

    Args:
        symbol: Symbol to check
        current_vix: Current VIX level for regime adjustment
        fundamentals_manager: FundamentalsManager instance

    Returns:
        Tuple of (passes: bool, stability_score: float, required_min: float)
    """
    required_min = get_adjusted_stability_min(current_vix)

    if fundamentals_manager is None:
        return (False, 0.0, required_min)

    try:
        f = fundamentals_manager.get_fundamentals(symbol)
        if f is None or f.stability_score is None:
            return (False, 0.0, required_min)
        return (f.stability_score >= required_min, f.stability_score, required_min)
    except Exception:
        return (False, 0.0, required_min)


def apply_blacklist_filter(
    signals: list[TradeSignal],
) -> list[TradeSignal]:
    """
    Remove blacklisted symbols (PLAYBOOK §1, Check 1).

    Args:
        signals: list[Any] of signals

    Returns:
        Filtered signal list without blacklisted symbols
    """
    filtered = []
    for signal in signals:
        if is_blacklisted(signal.symbol):
            logger.debug(f"Blacklist-filtered: {signal.symbol}")
        else:
            filtered.append(signal)
    return filtered


def apply_stability_filter(
    signals: list[TradeSignal],
    min_stability: float,
    vix: Optional[float] = None,
    fundamentals_manager: Any = None,
) -> list[TradeSignal]:
    """
    Filter signals by minimum stability score (PLAYBOOK §1, Check 2).

    VIX-Regime-aware: at VIX > 20, stability minimum increases to 80.

    Args:
        signals: list[Any] of signals
        min_stability: Base minimum stability score (0-100)
        vix: Current VIX level for regime adjustment
        fundamentals_manager: Optional FundamentalsManager for batch lookup

    Returns:
        Filtered signal list
    """
    # VIX-adjusted stability minimum (PLAYBOOK §3)
    effective_min = max(min_stability, get_adjusted_stability_min(vix))

    # Collect symbols that need fundamentals lookup (batch query instead of N+1)
    symbols_needing_lookup = []
    stability_from_signal: dict[str, float] = {}

    for signal in signals:
        stability = 0.0
        if signal.details and "stability" in signal.details:
            stability = signal.details["stability"].get("score", 0.0)

        if stability > 0.0:
            stability_from_signal[signal.symbol] = stability
        else:
            symbols_needing_lookup.append(signal.symbol)

    # Batch lookup for symbols without stability in signal details
    fundamentals_map: dict[str, float] = {}
    if symbols_needing_lookup and fundamentals_manager:
        batch_result = fundamentals_manager.get_fundamentals_batch(symbols_needing_lookup)
        for symbol, fund in batch_result.items():
            if fund and fund.stability_score:
                fundamentals_map[symbol] = fund.stability_score

    # Apply filter
    filtered = []
    for signal in signals:
        stability = stability_from_signal.get(signal.symbol, 0.0)
        if stability == 0.0:
            stability = fundamentals_map.get(signal.symbol, 0.0)

        if stability >= effective_min:
            filtered.append(signal)
        else:
            logger.debug(
                f"Filtered {signal.symbol}: stability {stability:.0f} < {effective_min:.0f}"
            )

    return filtered


def apply_sector_diversification(
    signals: list[TradeSignal],
    max_per_sector: int,
    fundamentals_manager: Any = None,
) -> list[TradeSignal]:
    """
    Stellt Sektor-Diversifikation sicher.

    Args:
        signals: Liste von Signalen (bereits nach Score sortiert)
        max_per_sector: Maximale Anzahl Signale pro Sektor
        fundamentals_manager: Optional FundamentalsManager for sector lookup

    Returns:
        Diversifizierte Signal-Liste
    """
    if not fundamentals_manager:
        return signals

    # Batch lookup for all sectors (single DB query instead of N+1)
    symbols = [s.symbol for s in signals]
    fundamentals_map = fundamentals_manager.get_fundamentals_batch(symbols)

    sector_counts: dict[str, int] = {}
    diversified = []

    for signal in signals:
        # Sektor ermitteln from batch result
        sector = "Unknown"
        fundamentals = fundamentals_map.get(signal.symbol)
        if fundamentals and fundamentals.sector:
            sector = fundamentals.sector

        # Limit pro Sektor prüfen
        current_count = sector_counts.get(sector, 0)
        if current_count < max_per_sector:
            diversified.append(signal)
            sector_counts[sector] = current_count + 1
        else:
            logger.debug(f"Sector limit reached for {sector}: skipping {signal.symbol}")

    return diversified
