# OptionPlay - IBKR Portfolio & Positions
# =========================================
"""
Handles IBKR portfolio retrieval and spread identification.

Provides:
- Full portfolio positions (stocks + options + other)
- Option-only positions
- Spread identification (Bull Put Spreads)
- Formatted Markdown output for all of the above
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

from ..utils.markdown_builder import MarkdownBuilder
from .connection import IBKRConnection

logger = logging.getLogger(__name__)


class IBKRPortfolio:
    """
    Portfolio and position management via IBKR/TWS.

    Requires a shared IBKRConnection instance.

    Usage:
        conn = IBKRConnection()
        portfolio = IBKRPortfolio(conn)
        positions = await portfolio.get_portfolio()
    """

    def __init__(self, connection: IBKRConnection) -> None:
        self._conn = connection

    async def get_portfolio(self) -> List[Dict[str, Any]]:
        """
        Fetches all positions from the IBKR portfolio.

        Returns:
            List of position dictionaries
        """
        if not await self._conn._ensure_connected():
            logger.warning("IBKR not available for portfolio retrieval")
            return []

        try:
            # Fetch portfolio positions (async version)
            raw_positions = await self._conn.ib.reqPositionsAsync()

            positions = []
            for pos in raw_positions:
                contract = pos.contract

                position_data = {
                    "symbol": contract.symbol,
                    "sec_type": contract.secType,
                    "quantity": pos.position,
                    "avg_cost": pos.avgCost,
                    "account": pos.account,
                }

                # Additional fields for options
                if contract.secType == "OPT":
                    position_data.update(
                        {
                            "strike": contract.strike,
                            "right": contract.right,  # 'C' or 'P'
                            "expiry": contract.lastTradeDateOrContractMonth,
                            "multiplier": int(contract.multiplier or 100),
                        }
                    )

                positions.append(position_data)

            logger.info(f"IBKR Portfolio: {len(positions)} positions loaded")
            return positions

        except Exception as e:
            logger.error(f"IBKR Portfolio error: {e}")
            return []

    async def get_portfolio_formatted(self) -> str:
        """
        Fetches portfolio and formats as Markdown.
        """
        positions = await self.get_portfolio()

        b = MarkdownBuilder()
        b.h1("IBKR Portfolio").blank()

        if not positions:
            b.hint("No positions found (IBKR not connected or empty portfolio).")
            return b.build()

        # Group by type
        stocks = [p for p in positions if p["sec_type"] == "STK"]
        options = [p for p in positions if p["sec_type"] == "OPT"]
        other = [p for p in positions if p["sec_type"] not in ["STK", "OPT"]]

        # Stocks
        if stocks:
            b.h2(f"Stocks ({len(stocks)})").blank()
            rows = []
            for p in stocks:
                market_value = p["quantity"] * p["avg_cost"]
                rows.append(
                    [
                        p["symbol"],
                        f"{p['quantity']:,.0f}",
                        f"${p['avg_cost']:.2f}",
                        f"${market_value:,.2f}",
                    ]
                )
            b.table(["Symbol", "Qty", "Avg Cost", "Value"], rows)
            b.blank()

        # Options
        if options:
            b.h2(f"Options ({len(options)})").blank()

            # Group by symbol
            by_symbol: Dict[str, List] = {}
            for p in options:
                sym = p["symbol"]
                if sym not in by_symbol:
                    by_symbol[sym] = []
                by_symbol[sym].append(p)

            for symbol, opts in by_symbol.items():
                b.h3(symbol).blank()
                rows = []
                for p in sorted(opts, key=lambda x: (x["expiry"], x["strike"])):
                    right = "Put" if p["right"] == "P" else "Call"
                    qty_str = f"{p['quantity']:+,.0f}"  # With sign
                    rows.append(
                        [
                            p["expiry"],
                            f"${p['strike']:.0f}",
                            right,
                            qty_str,
                            f"${p['avg_cost']:.2f}",
                        ]
                    )
                b.table(["Expiry", "Strike", "Type", "Qty", "Avg Cost"], rows)
                b.blank()

        # Other
        if other:
            b.h2(f"Other ({len(other)})").blank()
            for p in other:
                b.bullet(f"{p['symbol']} ({p['sec_type']}): {p['quantity']}")
            b.blank()

        # Summary
        b.h2("Summary")
        b.kv_line("Stock Positions", len(stocks))
        b.kv_line("Option Positions", len(options))
        b.kv_line("Other", len(other))

        return b.build()

    async def get_option_positions(self) -> List[Dict[str, Any]]:
        """
        Fetches only option positions from IBKR.

        Returns:
            List of option positions
        """
        all_positions = await self.get_portfolio()
        return [p for p in all_positions if p["sec_type"] == "OPT"]

    async def get_spreads(self) -> List[Dict[str, Any]]:
        """
        Identifies spread positions (Bull Put Spreads, etc.)

        Returns:
            List of identified spreads
        """
        options = await self.get_option_positions()

        if not options:
            return []

        # Group by symbol and expiry
        groups: Dict[str, List] = {}
        for opt in options:
            key = f"{opt['symbol']}_{opt['expiry']}"
            if key not in groups:
                groups[key] = []
            groups[key].append(opt)

        spreads = []
        for key, group in groups.items():
            puts = [o for o in group if o["right"] == "P"]

            # Bull Put Spread: Short Put (higher strike) + Long Put (lower strike)
            short_puts = [p for p in puts if p["quantity"] < 0]
            long_puts = [p for p in puts if p["quantity"] > 0]

            for short in short_puts:
                # Find matching Long Put
                for long in long_puts:
                    if long["strike"] < short["strike"] and abs(long["quantity"]) == abs(
                        short["quantity"]
                    ):
                        # avgCost from IBKR is total cost per contract (not per share)
                        # Net Credit = Short Premium - Long Premium (both totals)
                        net_credit_total = short["avg_cost"] - long["avg_cost"]
                        # Per share = total / 100
                        net_credit_per_share = net_credit_total / 100

                        spread = {
                            "type": "Bull Put Spread",
                            "symbol": short["symbol"],
                            "expiry": short["expiry"],
                            "short_strike": short["strike"],
                            "long_strike": long["strike"],
                            "width": short["strike"] - long["strike"],
                            "contracts": int(abs(short["quantity"])),
                            "short_cost": short["avg_cost"],
                            "long_cost": long["avg_cost"],
                            "net_credit": net_credit_per_share,  # Per share
                            "net_credit_total": net_credit_total
                            * int(abs(short["quantity"])),  # Total
                        }
                        spreads.append(spread)
                        break

        return spreads

    async def get_spreads_formatted(self) -> str:
        """
        Fetches spreads and formats as Markdown.
        """
        spreads = await self.get_spreads()

        b = MarkdownBuilder()
        b.h1("IBKR Spread Positions").blank()

        if not spreads:
            b.hint("No spread positions detected.")
            return b.build()

        rows = []
        total_credit = 0
        total_max_profit = 0
        total_max_loss = 0

        for s in spreads:
            max_profit = s["net_credit"] * s["contracts"] * 100
            max_loss = (s["width"] - s["net_credit"]) * s["contracts"] * 100

            total_credit += s.get("net_credit_total", max_profit)
            total_max_profit += max_profit
            total_max_loss += max_loss

            # Calculate DTE
            try:
                exp_date = datetime.strptime(s["expiry"], "%Y%m%d").date()
                dte = (exp_date - datetime.now().date()).days
                dte_str = f"{dte}d"
            except (ValueError, KeyError, TypeError) as e:
                logger.debug(f"Could not calculate DTE for {s.get('symbol', '?')}: {e}")
                dte_str = "?"

            rows.append(
                [
                    s["symbol"],
                    f"${s['long_strike']:.0f}/${s['short_strike']:.0f}",
                    s["expiry"][:4] + "-" + s["expiry"][4:6] + "-" + s["expiry"][6:],
                    dte_str,
                    str(s["contracts"]),
                    f"${s['net_credit']:.2f}",
                    f"${max_profit:,.0f}",
                    f"${max_loss:,.0f}",
                ]
            )

        b.table(
            ["Symbol", "Strikes", "Expiry", "DTE", "Qty", "Credit", "Max Profit", "Max Loss"], rows
        )

        b.blank()
        b.h2("Summary")
        b.kv_line("Spreads", len(spreads))
        b.kv_line("Total Credit", f"${total_credit:,.0f}")
        b.kv_line("Max Profit", f"${total_max_profit:,.0f}")
        b.kv_line("Max Loss", f"${total_max_loss:,.0f}")

        return b.build()
