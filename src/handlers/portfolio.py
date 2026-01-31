"""
Portfolio Handler Module
========================

Handles portfolio management operations: positions, P&L, trades.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..utils.error_handler import sync_endpoint
from ..utils.markdown_builder import MarkdownBuilder
from ..utils.validation import validate_symbol
from ..portfolio import get_portfolio_manager
from ..formatters import portfolio_formatter
from .base import BaseHandlerMixin

logger = logging.getLogger(__name__)


class PortfolioHandlerMixin(BaseHandlerMixin):
    """
    Mixin for portfolio management handler methods.
    """

    @sync_endpoint(operation="portfolio summary")
    def portfolio_summary(self) -> str:
        """Get portfolio summary with P&L statistics."""
        portfolio = get_portfolio_manager()
        summary = portfolio.get_summary()
        return portfolio_formatter.format_summary(summary)

    @sync_endpoint(operation="portfolio positions")
    def portfolio_positions(self, status: str = "all") -> str:
        """
        List portfolio positions.

        Args:
            status: Filter by status ("all", "open", "closed")

        Returns:
            Formatted positions table
        """
        portfolio = get_portfolio_manager()

        if status.lower() == "open":
            positions = portfolio.get_open_positions()
            title = "Open Positions"
        elif status.lower() == "closed":
            positions = portfolio.get_closed_positions()
            title = "Closed Positions"
        else:
            positions = portfolio.get_all_positions()
            title = "All Positions"

        return portfolio_formatter.format_positions_table(positions, title)

    @sync_endpoint(operation="portfolio position detail")
    def portfolio_position(self, position_id: str) -> str:
        """
        Get detailed view of a single position.

        Args:
            position_id: Position ID

        Returns:
            Formatted position details
        """
        portfolio = get_portfolio_manager()
        position = portfolio.get_position(position_id)

        if not position:
            return f"Position not found: {position_id}"

        return portfolio_formatter.format_position_detail(position)

    @sync_endpoint(operation="add position")
    def portfolio_add(
        self,
        symbol: str,
        short_strike: float,
        long_strike: float,
        expiration: str,
        credit: float,
        contracts: int = 1,
        notes: str = "",
    ) -> str:
        """
        Add a new Bull Put Spread position.

        Args:
            symbol: Ticker symbol
            short_strike: Short put strike price
            long_strike: Long put strike price
            expiration: Expiration date (YYYY-MM-DD)
            credit: Net credit received per share
            contracts: Number of contracts
            notes: Optional notes

        Returns:
            Confirmation message
        """
        symbol = validate_symbol(symbol)
        portfolio = get_portfolio_manager()

        try:
            position = portfolio.add_bull_put_spread(
                symbol=symbol,
                short_strike=short_strike,
                long_strike=long_strike,
                expiration=expiration,
                net_credit=credit,
                contracts=contracts,
                notes=notes,
            )

            b = MarkdownBuilder()
            b.h1("Position Added").blank()
            b.kv("ID", position.id)
            b.kv("Symbol", position.symbol)
            b.kv("Strikes", f"${long_strike}/{short_strike}")
            b.kv("Credit", f"${credit:.2f} x {contracts}")
            return b.build()

        except ValueError as e:
            return f"Error: {e}"

    @sync_endpoint(operation="close position")
    def portfolio_close(self, position_id: str, close_premium: float, notes: str = "") -> str:
        """
        Close a position by buying back the spread.

        Args:
            position_id: Position ID
            close_premium: Premium paid to close (per share)
            notes: Optional notes

        Returns:
            Confirmation with P&L
        """
        portfolio = get_portfolio_manager()

        try:
            position = portfolio.close_position(position_id, close_premium, notes)
            pnl = position.realized_pnl()

            b = MarkdownBuilder()
            b.h1("Position Closed").blank()
            b.kv("Symbol", position.symbol)
            pnl_icon = "[+]" if pnl >= 0 else "[-]"
            b.kv("Realized P&L", f"{pnl_icon} ${pnl:+,.2f}")
            return b.build()

        except ValueError as e:
            return f"Error: {e}"

    @sync_endpoint(operation="expire position")
    def portfolio_expire(self, position_id: str) -> str:
        """
        Mark position as expired worthless (full profit).

        Args:
            position_id: Position ID

        Returns:
            Confirmation with profit
        """
        portfolio = get_portfolio_manager()

        try:
            position = portfolio.expire_position(position_id)

            b = MarkdownBuilder()
            b.h1("Position Expired Worthless").blank()
            b.kv("Symbol", position.symbol)
            b.kv("Profit", f"[+] ${position.total_credit:,.2f}")
            return b.build()

        except ValueError as e:
            return f"Error: {e}"

    @sync_endpoint(operation="expiring positions")
    def portfolio_expiring(self, days: int = 7) -> str:
        """
        List positions expiring soon.

        Args:
            days: Number of days to look ahead

        Returns:
            Formatted list of expiring positions
        """
        portfolio = get_portfolio_manager()
        positions = portfolio.get_expiring_soon(days)
        return portfolio_formatter.format_expiring_soon(positions)

    @sync_endpoint(operation="trade history")
    def portfolio_trades(self, limit: int = 20) -> str:
        """
        Show trade history.

        Args:
            limit: Maximum number of trades to show

        Returns:
            Formatted trade history
        """
        portfolio = get_portfolio_manager()
        trades = portfolio.get_trades()
        return portfolio_formatter.format_trades(trades, limit)

    @sync_endpoint(operation="P&L by symbol")
    def portfolio_pnl_symbols(self) -> str:
        """
        Show realized P&L grouped by symbol.

        Returns:
            Formatted P&L by symbol
        """
        portfolio = get_portfolio_manager()
        pnl = portfolio.get_pnl_by_symbol()
        return portfolio_formatter.format_pnl_by_symbol(pnl)

    @sync_endpoint(operation="monthly P&L")
    def portfolio_pnl_monthly(self) -> str:
        """
        Show monthly P&L report.

        Returns:
            Formatted monthly P&L
        """
        portfolio = get_portfolio_manager()
        pnl = portfolio.get_monthly_pnl()
        return portfolio_formatter.format_monthly_pnl(pnl)
