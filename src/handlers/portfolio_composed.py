"""
Portfolio Handler (Composition-Based)
======================================

Handles portfolio management operations: positions, P&L, trades, constraints.

This is the composition-based version of PortfolioHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PortfolioHandler(BaseHandler):
    """
    Handler for portfolio management operations.

    Methods:
    - portfolio_summary(): Get portfolio summary with P&L statistics
    - portfolio_positions(): List portfolio positions
    - portfolio_position(): Get detailed view of a single position
    - portfolio_add(): Add a new Bull Put Spread position
    - portfolio_close(): Close a position
    - portfolio_expire(): Mark position as expired worthless
    - portfolio_expiring(): List positions expiring soon
    - portfolio_trades(): Show trade history
    - portfolio_pnl_symbols(): Show P&L grouped by symbol
    - portfolio_pnl_monthly(): Show monthly P&L report
    - portfolio_check(): Check if a new position can be opened
    - portfolio_constraints(): Show constraint configuration and status
    """

    def portfolio_summary(self) -> str:
        """Get portfolio summary with P&L statistics."""
        from ..portfolio import get_portfolio_manager
        from ..formatters import portfolio_formatter

        portfolio = get_portfolio_manager()
        summary = portfolio.get_summary()
        return portfolio_formatter.format_summary(summary)

    def portfolio_positions(self, status: str = "all") -> str:
        """
        List portfolio positions.

        Args:
            status: Filter by status ("all", "open", "closed")

        Returns:
            Formatted positions table
        """
        from ..portfolio import get_portfolio_manager
        from ..formatters import portfolio_formatter

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

    def portfolio_position(self, position_id: str) -> str:
        """
        Get detailed view of a single position.

        Args:
            position_id: Position ID

        Returns:
            Formatted position details
        """
        from ..portfolio import get_portfolio_manager
        from ..formatters import portfolio_formatter

        portfolio = get_portfolio_manager()
        position = portfolio.get_position(position_id)

        if not position:
            return f"Position not found: {position_id}"

        return portfolio_formatter.format_position_detail(position)

    def portfolio_add(
        self,
        symbol: str,
        short_strike: float,
        long_strike: float,
        expiration: str,
        credit: float,
        contracts: int = 1,
        notes: str = "",
        skip_constraints: bool = False,
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
            skip_constraints: If True, skip constraint checks

        Returns:
            Confirmation message
        """
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder
        from ..portfolio import get_portfolio_manager
        from ..services.portfolio_constraints import get_constraint_checker

        symbol = validate_symbol(symbol)
        portfolio = get_portfolio_manager()

        spread_width = short_strike - long_strike
        max_risk = spread_width * 100 * contracts

        if not skip_constraints:
            open_positions = [
                {"symbol": p.symbol}
                for p in portfolio.get_open_positions()
            ]

            checker = get_constraint_checker()
            result = checker.check_all_constraints(
                symbol=symbol,
                max_risk=max_risk,
                open_positions=open_positions
            )

            b = MarkdownBuilder()

            if not result.allowed:
                b.h1("Position Blocked").blank()
                b.text("The following constraints prevent this trade:").blank()
                for blocker in result.blockers:
                    b.text(f"  {blocker}")
                b.blank()
                b.text("Use `skip_constraints=True` to override (not recommended).")
                return b.build()

            warnings_output = result.warnings if result.warnings else []
        else:
            warnings_output = []

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
            b.kv("Max Risk", f"${max_risk:.2f}")

            if not skip_constraints and warnings_output:
                b.blank()
                b.h2("Warnings")
                for warning in warnings_output:
                    b.text(f"  {warning}")

            return b.build()

        except ValueError as e:
            return f"Error: {e}"

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
        from ..utils.markdown_builder import MarkdownBuilder
        from ..portfolio import get_portfolio_manager

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

    def portfolio_expire(self, position_id: str) -> str:
        """
        Mark position as expired worthless (full profit).

        Args:
            position_id: Position ID

        Returns:
            Confirmation with profit
        """
        from ..utils.markdown_builder import MarkdownBuilder
        from ..portfolio import get_portfolio_manager

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

    def portfolio_expiring(self, days: int = 7) -> str:
        """
        List positions expiring soon.

        Args:
            days: Number of days to look ahead

        Returns:
            Formatted list of expiring positions
        """
        from ..portfolio import get_portfolio_manager
        from ..formatters import portfolio_formatter

        portfolio = get_portfolio_manager()
        positions = portfolio.get_expiring_soon(days)
        return portfolio_formatter.format_expiring_soon(positions)

    def portfolio_trades(self, limit: int = 20) -> str:
        """
        Show trade history.

        Args:
            limit: Maximum number of trades to show

        Returns:
            Formatted trade history
        """
        from ..portfolio import get_portfolio_manager
        from ..formatters import portfolio_formatter

        portfolio = get_portfolio_manager()
        trades = portfolio.get_trades()
        return portfolio_formatter.format_trades(trades, limit)

    def portfolio_pnl_symbols(self) -> str:
        """Show realized P&L grouped by symbol."""
        from ..portfolio import get_portfolio_manager
        from ..formatters import portfolio_formatter

        portfolio = get_portfolio_manager()
        pnl = portfolio.get_pnl_by_symbol()
        return portfolio_formatter.format_pnl_by_symbol(pnl)

    def portfolio_pnl_monthly(self) -> str:
        """Show monthly P&L report."""
        from ..portfolio import get_portfolio_manager
        from ..formatters import portfolio_formatter

        portfolio = get_portfolio_manager()
        pnl = portfolio.get_monthly_pnl()
        return portfolio_formatter.format_monthly_pnl(pnl)

    def portfolio_check(
        self,
        symbol: str,
        max_risk: float = 500.0,
    ) -> str:
        """
        Check if a new position can be opened (constraint check).

        Args:
            symbol: Ticker symbol to check
            max_risk: Maximum risk in USD (default $500)

        Returns:
            Constraint check result
        """
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder
        from ..portfolio import get_portfolio_manager
        from ..services.portfolio_constraints import get_constraint_checker

        symbol = validate_symbol(symbol)
        portfolio = get_portfolio_manager()

        open_positions = [
            {"symbol": p.symbol}
            for p in portfolio.get_open_positions()
        ]

        checker = get_constraint_checker()
        result = checker.check_all_constraints(
            symbol=symbol,
            max_risk=max_risk,
            open_positions=open_positions
        )

        b = MarkdownBuilder()
        b.h1(f"Constraint Check: {symbol}").blank()

        if result.allowed:
            b.text("[v] **ALLOWED** - Position can be opened").blank()
        else:
            b.text("[x] **BLOCKED** - Position cannot be opened").blank()

        b.kv("Current Positions", len(open_positions))
        b.kv("Max Risk", f"${max_risk:.0f}")

        if result.blockers:
            b.blank().h2("Blockers")
            for blocker in result.blockers:
                b.text(f"  {blocker}")

        if result.warnings:
            b.blank().h2("Warnings")
            for warning in result.warnings:
                b.text(f"  {warning}")

        b.blank().h2("Constraint Status")
        status = checker.get_status()
        b.kv("Max Positions", status['constraints']['max_positions'])
        b.kv("Max per Sector", status['constraints']['max_per_sector'])
        b.kv("Daily Risk Used", f"${status['current']['daily_risk_used']:.0f}")
        b.kv("Daily Remaining", f"${status['current']['daily_remaining']:.0f}")

        return b.build()

    def portfolio_constraints(self) -> str:
        """Show current constraint configuration and status."""
        from ..utils.markdown_builder import MarkdownBuilder
        from ..services.portfolio_constraints import get_constraint_checker

        checker = get_constraint_checker()
        status = checker.get_status()

        b = MarkdownBuilder()
        b.h1("Portfolio Constraints").blank()

        b.h2("Configuration")
        for key, value in status['constraints'].items():
            if key == 'symbol_blacklist':
                b.kv("Blacklist", ", ".join(value[:5]) + ("..." if len(value) > 5 else ""))
            elif 'usd' in key or 'size' in key:
                b.kv(key.replace('_', ' ').title(), f"${value:,.0f}")
            elif 'pct' in key or 'correlation' in key:
                b.kv(key.replace('_', ' ').title(), f"{value:.0%}")
            else:
                b.kv(key.replace('_', ' ').title(), value)

        b.blank().h2("Current Status")
        b.kv("Daily Risk Used", f"${status['current']['daily_risk_used']:,.0f}")
        b.kv("Daily Remaining", f"${status['current']['daily_remaining']:,.0f}")
        b.kv("Weekly Risk Used", f"${status['current']['weekly_risk_used']:,.0f}")
        b.kv("Weekly Remaining", f"${status['current']['weekly_remaining']:,.0f}")

        return b.build()
