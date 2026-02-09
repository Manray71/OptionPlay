"""
Monitor Handler (Composition-Based)
======================================

Handles position monitoring for exit signals.
Returns actionable signals (CLOSE / ROLL / ALERT / HOLD) for open positions.

This is the composition-based version of MonitorHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MonitorHandler(BaseHandler):
    """
    Handler for position monitoring operations.

    Methods:
    - monitor_positions(): Monitor all open positions for exit signals
    """

    async def monitor_positions(self) -> str:
        """
        Monitor all open positions and generate exit signals.

        Checks IBKR live positions (preferred) and internal portfolio.
        Returns GO / CLOSE / ROLL / ALERT for each position.

        Returns:
            Formatted Markdown with exit signals
        """
        from ..services.position_monitor import get_position_monitor
        from ..utils.markdown_builder import MarkdownBuilder

        current_vix = await self._get_vix()

        snapshots = await self._collect_position_snapshots()

        if not snapshots:
            b = MarkdownBuilder()
            b.h1("Position Monitor")
            b.blank()
            b.text("Keine offenen Positionen gefunden.")
            b.blank()
            b.text("Quellen geprüft: IBKR Bridge, internes Portfolio")
            return b.build()

        monitor = get_position_monitor()
        result = await monitor.check_positions(snapshots, current_vix)

        return self._format_monitor_result(result)

    async def _collect_position_snapshots(self) -> List[Any]:
        """
        Collect position snapshots from all sources.

        Priority: IBKR (live data) > Internal portfolio (theta-estimated).
        """
        from ..services.position_monitor import (
            PositionSnapshot,
            snapshot_from_internal,
            snapshot_from_ibkr,
            estimate_pnl_from_theta,
        )

        snapshots: List[PositionSnapshot] = []
        ibkr_symbols: set = set()

        # Source 1: IBKR Bridge (preferred)
        try:
            if self._ctx.ibkr_bridge:
                spreads = await self._ctx.ibkr_bridge.get_spreads()
                if spreads:
                    for spread in spreads:
                        snap = snapshot_from_ibkr(spread)
                        snapshots.append(snap)
                        ibkr_symbols.add(snap.symbol)
        except Exception as e:
            self._logger.debug(f"IBKR spread collection failed: {e}")

        # Source 2: Internal Portfolio (with theta-estimated P&L)
        try:
            from ..portfolio import get_portfolio_manager
            portfolio = get_portfolio_manager()
            open_positions = portfolio.get_open_positions()

            for pos in open_positions:
                if pos.symbol in ibkr_symbols:
                    continue
                snap = snapshot_from_internal(pos)
                estimate_pnl_from_theta(snap)
                snapshots.append(snap)
        except Exception as e:
            self._logger.debug(f"Internal portfolio collection failed: {e}")

        return snapshots

    def _format_monitor_result(self, result: Any) -> str:
        """Format MonitorResult as Markdown."""
        from ..constants.trading_rules import ExitAction
        from ..utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        b.h1("Position Monitor")
        b.blank()

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

        if result.regime:
            b.kv_line("VIX-Regime", result.regime)
            b.blank()

        # Action items (CLOSE, ROLL, ALERT)
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
    def _signal_icon(action: Any) -> str:
        """Icon for exit action."""
        from ..constants.trading_rules import ExitAction
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

    # --- Shared helper methods ---

    async def _get_vix(self) -> Optional[float]:
        if self._ctx.current_vix is not None:
            return self._ctx.current_vix
        if self._ctx.provider:
            try:
                quote = await self._ctx.provider.get_quote("VIX")
                if quote and hasattr(quote, 'last') and quote.last:
                    self._ctx.current_vix = quote.last
                    return quote.last
            except (ConnectionError, AttributeError, TimeoutError) as e:
                logger.debug("VIX fetch failed: %s", e)
        return None
