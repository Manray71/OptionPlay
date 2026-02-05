"""
Monitor Handler Module
======================

Handles position monitoring for exit signals.
Returns actionable signals (CLOSE / ROLL / ALERT / HOLD) for open positions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..constants.trading_rules import ExitAction
from ..utils.error_handler import endpoint
from ..utils.markdown_builder import MarkdownBuilder
from ..services.position_monitor import (
    PositionMonitor,
    PositionSnapshot,
    PositionSignal,
    MonitorResult,
    get_position_monitor,
    snapshot_from_internal,
    snapshot_from_ibkr,
    estimate_pnl_from_theta,
)
from .base import BaseHandlerMixin

logger = logging.getLogger(__name__)


class MonitorHandlerMixin(BaseHandlerMixin):
    """
    Mixin for position monitoring handler methods.
    """

    @endpoint(operation="position monitoring")
    async def monitor_positions(self) -> str:
        """
        Monitor all open positions and generate exit signals.

        Checks IBKR live positions (preferred) and internal portfolio.
        Returns GO / CLOSE / ROLL / ALERT for each position.

        Returns:
            Formatted Markdown with exit signals
        """
        # Get current VIX
        current_vix = await self.get_vix()

        # Collect position snapshots
        snapshots = await self._collect_position_snapshots()

        if not snapshots:
            b = MarkdownBuilder()
            b.h1("Position Monitor")
            b.blank()
            b.text("Keine offenen Positionen gefunden.")
            b.blank()
            b.text("Quellen geprüft: IBKR Bridge, internes Portfolio")
            return b.build()

        # Run monitor
        monitor = get_position_monitor()
        result = await monitor.check_positions(snapshots, current_vix)

        # Format output
        return self._format_monitor_result(result)

    async def _collect_position_snapshots(self) -> List[PositionSnapshot]:
        """
        Collect position snapshots from all sources.

        Priority: IBKR (live data) > Internal portfolio (theta-estimated).
        IBKR symbols are deduplicated (not counted twice).
        """
        snapshots: List[PositionSnapshot] = []
        ibkr_symbols: set = set()

        # Source 1: IBKR Bridge (preferred — has live data)
        try:
            if hasattr(self, '_ibkr_bridge') and self._ibkr_bridge:
                import asyncio
                spreads = await self._ibkr_bridge.get_spreads()
                if spreads:
                    for spread in spreads:
                        snap = snapshot_from_ibkr(spread)
                        # IBKR may have live current_spread_value
                        # For now it's not in the spread dict, but
                        # the P&L can be estimated from net_credit_total
                        if "net_credit_total" in spread:
                            # Use IBKR's reported data for a rough P&L
                            pass
                        snapshots.append(snap)
                        ibkr_symbols.add(snap.symbol)
        except Exception as e:
            logger.debug(f"IBKR spread collection failed: {e}")

        # Source 2: Internal Portfolio (with theta-estimated P&L)
        try:
            from ..portfolio import get_portfolio_manager
            portfolio = get_portfolio_manager()
            open_positions = portfolio.get_open_positions()

            for pos in open_positions:
                # Skip if already tracked via IBKR
                if pos.symbol in ibkr_symbols:
                    continue

                snap = snapshot_from_internal(pos)
                estimate_pnl_from_theta(snap)
                snapshots.append(snap)
        except Exception as e:
            logger.debug(f"Internal portfolio collection failed: {e}")

        return snapshots

    def _format_monitor_result(self, result: MonitorResult) -> str:
        """Format MonitorResult as Markdown."""
        b = MarkdownBuilder()

        b.h1("Position Monitor")
        b.blank()

        # Summary line
        close_count = len(result.close_signals)
        roll_count = len(result.roll_signals)
        alert_count = len(result.alert_signals)
        hold_count = len(result.hold_signals)

        b.text(
            f"**{result.positions_count} Positionen** | "
            f"{close_count} CLOSE | {roll_count} ROLL | "
            f"{alert_count} ALERT | {hold_count} HOLD"
        )
        b.blank()

        # Regime info
        if result.regime:
            b.kv_line("VIX-Regime", result.regime)
            b.blank()

        # Action items first (CLOSE, ROLL, ALERT)
        action_signals = [
            s for s in result.signals if s.action != ExitAction.HOLD
        ]

        if action_signals:
            b.h2("Aktionen erforderlich")
            b.blank()

            for signal in action_signals:
                icon = self._signal_icon(signal.action)
                pnl_str = self._format_pnl(signal.pnl_pct)
                b.text(
                    f"**{icon} {signal.action.value}** {signal.symbol} "
                    f"(DTE {signal.dte}{pnl_str})"
                )
                b.text(f"  {signal.reason}")
                b.blank()

        # HOLD positions
        if result.hold_signals:
            b.h2("Halten")
            b.blank()

            for signal in result.hold_signals:
                pnl_str = self._format_pnl(signal.pnl_pct)
                b.text(f"OK {signal.symbol} (DTE {signal.dte}{pnl_str})")

            b.blank()

        return b.build()

    @staticmethod
    def _signal_icon(action: ExitAction) -> str:
        """Icon for exit action."""
        icons = {
            ExitAction.CLOSE: "[CLOSE]",
            ExitAction.ROLL: "[ROLL]",
            ExitAction.ALERT: "[ALERT]",
            ExitAction.HOLD: "[HOLD]",
        }
        return icons.get(action, "[?]")

    @staticmethod
    def _format_pnl(pnl_pct: Optional[float]) -> str:
        """Format P&L percentage string."""
        if pnl_pct is None:
            return ""
        return f", P&L {pnl_pct:+.0f}%"
