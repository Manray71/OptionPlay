# OptionPlay - Portfolio Formatter
# =================================
# Formats portfolio data for display.

from typing import List, Dict, Optional, Any
from ..utils.markdown_builder import MarkdownBuilder, format_price
from ..portfolio.manager import (
    BullPutSpread, 
    PortfolioSummary, 
    TradeRecord,
    PositionStatus,
)


class PortfolioFormatter:
    """Formats portfolio data as Markdown."""
    
    def format_summary(self, summary: PortfolioSummary) -> str:
        """Format portfolio summary."""
        b = MarkdownBuilder()
        b.h1("Portfolio Summary").blank()
        
        # Overview
        b.h2("Overview")
        b.kv_line("Total Positions", summary.total_positions)
        b.kv_line("Open", summary.open_positions)
        b.kv_line("Closed", summary.closed_positions)
        b.blank()
        
        # P&L
        b.h2("P&L Performance")
        
        # Realized P&L with color indicator
        pnl_icon = "🟢" if summary.total_realized_pnl >= 0 else "🔴"
        b.kv_line("Realized P&L", f"{pnl_icon} ${summary.total_realized_pnl:,.2f}")
        
        if summary.total_unrealized_pnl != 0:
            unrealized_icon = "🟢" if summary.total_unrealized_pnl >= 0 else "🔴"
            b.kv_line("Unrealized P&L", f"{unrealized_icon} ${summary.total_unrealized_pnl:,.2f}")
        
        b.blank()
        
        # Statistics
        b.h2("Statistics")
        win_icon = "✅" if summary.win_rate >= 50 else "⚠️"
        b.kv_line("Win Rate", f"{win_icon} {summary.win_rate:.1f}%")
        b.kv_line("Avg P&L/Trade", f"${summary.avg_profit:,.2f}")
        b.blank()
        
        # Risk
        b.h2("Risk")
        b.kv_line("Capital at Risk", f"${summary.total_capital_at_risk:,.2f}")
        
        if summary.positions_expiring_soon > 0:
            b.kv_line("Expiring Soon", f"⚠️ {summary.positions_expiring_soon} positions (within 7 days)")
        else:
            b.kv_line("Expiring Soon", "None")
        
        return b.build()
    
    def format_positions_table(
        self, 
        positions: List[BullPutSpread],
        title: str = "Positions"
    ) -> str:
        """Format positions as a table."""
        b = MarkdownBuilder()
        b.h1(title).blank()
        
        if not positions:
            b.hint("No positions found.")
            return b.build()
        
        rows = []
        for p in positions:
            status_icon = {
                PositionStatus.OPEN: "🟢",
                PositionStatus.CLOSED: "⚪",
                PositionStatus.EXPIRED: "✅",
                PositionStatus.ASSIGNED: "🔴",
            }.get(p.status, "?")
            
            pnl = p.realized_pnl()
            if pnl is not None:
                pnl_str = f"${pnl:+,.0f}"
            elif p.status == PositionStatus.OPEN:
                pnl_str = f"max ${p.max_profit:,.0f}"
            else:
                pnl_str = "-"
            
            dte = p.days_to_expiration if p.status == PositionStatus.OPEN else "-"
            
            rows.append([
                p.id,
                status_icon,
                p.symbol,
                f"${p.long_leg.strike:.0f}/${p.short_leg.strike:.0f}",
                p.expiration,
                str(dte),
                f"${p.net_credit:.2f}",
                pnl_str,
            ])
        
        b.table(
            ["ID", "St", "Symbol", "Strikes", "Exp", "DTE", "Credit", "P&L"],
            rows
        )
        
        return b.build()
    
    def format_position_detail(self, position: BullPutSpread) -> str:
        """Format detailed position view."""
        b = MarkdownBuilder()
        
        status_text = {
            PositionStatus.OPEN: "🟢 OPEN",
            PositionStatus.CLOSED: "⚪ CLOSED",
            PositionStatus.EXPIRED: "✅ EXPIRED",
            PositionStatus.ASSIGNED: "🔴 ASSIGNED",
        }.get(position.status, position.status.value)
        
        b.h1(f"Position: {position.symbol}").blank()
        b.kv("ID", position.id)
        b.kv("Status", status_text)
        b.blank()
        
        # Structure
        b.h2("Spread Structure")
        b.kv_line("Type", "Bull Put Spread")
        b.kv_line("Short Put", f"${position.short_leg.strike:.2f}")
        b.kv_line("Long Put", f"${position.long_leg.strike:.2f}")
        b.kv_line("Width", f"${position.spread_width:.2f}")
        b.kv_line("Expiration", position.expiration)
        b.kv_line("Contracts", position.contracts)
        b.blank()
        
        # Financials
        b.h2("Financials")
        b.kv_line("Net Credit", f"${position.net_credit:.2f} per contract")
        b.kv_line("Total Credit", f"${position.total_credit:.2f}")
        b.kv_line("Breakeven", f"${position.breakeven:.2f}")
        b.blank()
        
        b.kv_line("Max Profit", f"${position.max_profit:.2f}")
        b.kv_line("Max Loss", f"${position.max_loss:.2f}")
        b.blank()
        
        # P&L
        b.h2("P&L")
        if position.status == PositionStatus.OPEN:
            b.kv_line("Days to Expiration", position.days_to_expiration)
            b.kv_line("Status", "Waiting for expiration or manual close")
        else:
            pnl = position.realized_pnl()
            if pnl is not None:
                pnl_icon = "🟢" if pnl >= 0 else "🔴"
                b.kv_line("Realized P&L", f"{pnl_icon} ${pnl:,.2f}")
            
            if position.close_date:
                b.kv_line("Closed", position.close_date)
            
            if position.close_premium is not None:
                b.kv_line("Close Premium", f"${position.close_premium:.2f}")
        
        # Notes
        if position.notes:
            b.blank()
            b.h2("Notes")
            b.text(position.notes)
        
        # Tags
        if position.tags:
            b.blank()
            b.kv("Tags", ", ".join(position.tags))
        
        return b.build()
    
    def format_trades(self, trades: List[TradeRecord], limit: int = 20) -> str:
        """Format trade history."""
        b = MarkdownBuilder()
        b.h1("Trade History").blank()
        
        if not trades:
            b.hint("No trades recorded.")
            return b.build()
        
        # Sort by timestamp descending
        sorted_trades = sorted(trades, key=lambda t: t.timestamp, reverse=True)
        
        rows = []
        for trade in sorted_trades[:limit]:
            date_str = trade.timestamp[:10]
            action_icon = {
                "open": "📥",
                "close": "📤",
                "expire": "✅",
                "assign": "🔴",
                "adjust": "🔄",
                "roll": "↩️",
            }.get(trade.action.value, "?")
            
            # Extract key detail
            detail = ""
            if "net_credit" in trade.details:
                detail = f"${trade.details['net_credit']:.2f}"
            elif "realized_pnl" in trade.details:
                pnl = trade.details['realized_pnl']
                detail = f"${pnl:+,.0f}"
            
            rows.append([
                date_str,
                action_icon,
                trade.action.value.upper(),
                trade.symbol,
                detail,
            ])
        
        b.table(["Date", "", "Action", "Symbol", "Detail"], rows)
        
        if len(trades) > limit:
            b.blank()
            b.hint(f"Showing {limit} of {len(trades)} trades")
        
        return b.build()
    
    def format_pnl_by_symbol(self, pnl_by_symbol: Dict[str, float]) -> str:
        """Format P&L grouped by symbol."""
        b = MarkdownBuilder()
        b.h1("P&L by Symbol").blank()
        
        if not pnl_by_symbol:
            b.hint("No closed positions.")
            return b.build()
        
        # Sort by P&L descending
        sorted_pnl = sorted(pnl_by_symbol.items(), key=lambda x: x[1], reverse=True)
        
        rows = []
        for symbol, pnl in sorted_pnl:
            icon = "🟢" if pnl >= 0 else "🔴"
            rows.append([symbol, icon, f"${pnl:+,.2f}"])
        
        b.table(["Symbol", "", "P&L"], rows)
        
        total = sum(pnl_by_symbol.values())
        b.blank()
        b.kv("Total", f"${total:+,.2f}")
        
        return b.build()
    
    def format_monthly_pnl(self, monthly_pnl: Dict[str, float]) -> str:
        """Format monthly P&L report."""
        b = MarkdownBuilder()
        b.h1("Monthly P&L").blank()
        
        if not monthly_pnl:
            b.hint("No closed positions.")
            return b.build()
        
        rows = []
        for month, pnl in monthly_pnl.items():
            icon = "🟢" if pnl >= 0 else "🔴"
            rows.append([month, icon, f"${pnl:+,.2f}"])
        
        b.table(["Month", "", "P&L"], rows)
        
        total = sum(monthly_pnl.values())
        avg = total / len(monthly_pnl) if monthly_pnl else 0
        
        b.blank()
        b.kv("Total", f"${total:+,.2f}")
        b.kv("Average/Month", f"${avg:+,.2f}")
        
        return b.build()
    
    def format_expiring_soon(self, positions: List[BullPutSpread]) -> str:
        """Format positions expiring soon."""
        b = MarkdownBuilder()
        b.h1("⚠️ Positions Expiring Soon").blank()
        
        if not positions:
            b.status_ok("No positions expiring within 7 days.")
            return b.build()
        
        # Sort by DTE
        sorted_pos = sorted(positions, key=lambda p: p.days_to_expiration)
        
        rows = []
        for p in sorted_pos:
            dte = p.days_to_expiration
            urgency = "🔴" if dte <= 2 else "🟡" if dte <= 5 else "🟢"
            
            rows.append([
                urgency,
                p.symbol,
                f"${p.long_leg.strike:.0f}/${p.short_leg.strike:.0f}",
                p.expiration,
                f"{dte} days",
                f"${p.max_profit:.0f}",
            ])
        
        b.table(["", "Symbol", "Strikes", "Exp", "DTE", "Max Profit"], rows)
        
        b.blank()
        b.hint("Consider closing or rolling these positions before expiration.")
        
        return b.build()


# Global formatter instance
portfolio_formatter = PortfolioFormatter()
