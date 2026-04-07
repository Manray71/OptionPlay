"""
VIX Handler (Composition-Based)
================================

Handles VIX, strategy, regime, event calendar, and sector operations.

This is the composition-based version of VixHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class VixHandler(BaseHandler):
    """
    Handler for VIX-related operations.

    Methods:
    - get_vix(): Get current VIX value
    - get_strategy_recommendation(): Get VIX-based strategy recommendation
    - get_regime_status(): Get current VIX regime and parameters
    - get_strategy_for_stock(): Get strategy recommendation for a specific stock
    - get_event_calendar(): Get upcoming market events
    - get_sector_status(): Get sector momentum analysis
    """

    VIX_CACHE_SECONDS = 300  # 5 minutes

    async def get_vix(self, force_refresh: bool = False) -> Optional[float]:
        """
        Get current VIX value.

        Uses cached value if available and not expired (5 min TTL).

        Args:
            force_refresh: Force API call even if cached

        Returns:
            VIX value or None if unavailable
        """
        # Check cache
        if not force_refresh and self._ctx.current_vix is not None:
            if self._ctx.vix_updated:
                age = (datetime.now() - self._ctx.vix_updated).total_seconds()
                if age < self.VIX_CACHE_SECONDS:
                    return self._ctx.current_vix

        # Try IBKR first
        if self._ctx.ibkr_bridge:
            try:
                vix = await self._ctx.ibkr_bridge.get_vix_value()
                if vix is not None:
                    self._ctx.current_vix = vix
                    self._ctx.vix_updated = datetime.now()
                    return vix
            except Exception as e:
                self._logger.debug(f"IBKR VIX failed: {e}")

        # Try IBKR quote for VIX index
        await self._ensure_connected()
        if self._ctx.ibkr_connected and self._ctx.ibkr_provider:
            try:
                quote = await self._ctx.ibkr_provider.get_quote("VIX")
                if quote and hasattr(quote, "last") and quote.last:
                    self._ctx.current_vix = quote.last
                    self._ctx.vix_updated = datetime.now()
                    return quote.last
            except Exception as e:
                self._logger.debug(f"IBKR VIX quote failed: {e}")

        # Fallback to Yahoo Finance
        if self._ctx.current_vix is None:
            try:
                import asyncio

                vix = await asyncio.to_thread(self._fetch_vix_yahoo)
                if vix:
                    self._ctx.current_vix = vix
                    self._ctx.vix_updated = datetime.now()
                    return vix
            except Exception as e:
                self._logger.debug(f"Yahoo VIX failed: {e}")

        return self._ctx.current_vix

    async def get_strategy_recommendation(self) -> str:
        """
        Get current strategy recommendation based on VIX.

        Returns:
            Formatted Markdown recommendation
        """
        from ..formatters import formatters
        from ..services.vix_strategy import get_strategy_for_vix

        vix = await self.get_vix()
        recommendation = get_strategy_for_vix(vix)
        return formatters.strategy.format(recommendation, vix)

    async def get_regime_status(self) -> str:
        """
        Get current VIX regime status using v2 continuous interpolation.

        Delegates to get_regime_status_v2() since v2 is now active.

        Returns:
            Formatted Markdown regime status
        """
        return await self.get_regime_status_v2()

    async def get_regime_status_v2(self) -> str:
        """
        Get VIX regime status using v2 continuous interpolation model.

        Shows interpolated parameters, term structure overlay, and
        VIX trend information.

        Returns:
            Formatted Markdown regime status
        """
        from ..services.vix_regime import get_regime_params
        from ..utils.markdown_builder import MarkdownBuilder

        vix = await self.get_vix()

        if vix is None:
            return "Could not fetch VIX - unable to determine regime"

        try:
            # Get VIX futures for term structure (if IBKR available)
            vix_futures = None
            try:
                if hasattr(self._ctx, "ibkr_provider") and self._ctx.ibkr_provider:
                    provider = self._ctx.ibkr_provider
                    if hasattr(provider, "get_vix_futures_front"):
                        vix_futures = await provider.get_vix_futures_front()
            except Exception:
                pass

            # Get VIX trend
            vix_trend = None
            try:
                from ..services.vix_strategy import VIXStrategySelector

                selector = VIXStrategySelector()
                trend_info = selector.get_vix_trend(vix)
                if trend_info and trend_info.history_available:
                    vix_trend = trend_info.trend.value
            except Exception:
                pass

            params = get_regime_params(vix, vix_futures, vix_trend)

            b = MarkdownBuilder()
            b.h1("VIX Regime Status (v2)").blank()

            # Current Status
            b.h2("Current Regime")
            b.kv_line("VIX", f"{vix:.2f}")
            b.kv_line("Regime", params.regime_label.value)
            if params.stress_adjusted:
                b.kv_line("Status", "STRESS-ADJUSTED")
            b.blank()

            # Interpolated Parameters
            b.h2("Interpolated Parameters")
            b.kv_line("Min Score", f"{params.min_score:.1f}")
            b.kv_line("Spread Width", f"${params.spread_width:.2f} (floor)")
            b.kv_line("Earnings Buffer", f"{params.earnings_buffer_days}d")
            b.kv_line("Max Positions", str(params.max_positions))
            b.kv_line("Max/Sector", str(params.max_per_sector))
            b.blank()

            # Fixed Parameters (from Playbook)
            b.h2("Fixed Parameters (Playbook)")
            b.kv_line("Delta Target", f"{params.delta_target:.2f}")
            b.kv_line("Delta Range", f"{params.delta_max:.2f} to {params.delta_min:.2f}")
            b.kv_line("DTE Range", f"{params.dte_min}-{params.dte_max}d")
            b.blank()

            # Term Structure
            if vix_futures is not None:
                b.h2("Term Structure")
                spread_pct = ((vix_futures - vix) / vix) * 100
                b.kv_line("VIX Spot", f"{vix:.2f}")
                b.kv_line("VIX Futures (Front)", f"{vix_futures:.2f}")
                b.kv_line("Spread", f"{spread_pct:+.1f}%")
                ts_label = params.term_structure or "neutral"
                b.kv_line("Classification", ts_label.upper())
                b.blank()

            # VIX Trend
            if vix_trend:
                b.h2("VIX Trend")
                b.kv_line("Trend", vix_trend.replace("_", " ").title())
                if params.trend_adjusted:
                    b.kv_line("Adjustment", "Applied")
                b.blank()

            return b.build()

        except Exception as e:
            logger.error(f"Regime status v2 error: {e}")
            return f"Error getting regime status v2: {e}"

    async def get_strategy_for_stock(self, symbol: str) -> str:
        """
        Get strategy recommendation based on stock price and VIX regime.

        Spread width is determined dynamically by delta-based strike selection.
        Use recommend_strikes for specific strike recommendations.

        Args:
            symbol: Ticker symbol

        Returns:
            Formatted Markdown recommendation
        """
        from ..services.vix_strategy import get_strategy_for_stock
        from ..utils.markdown_builder import MarkdownBuilder
        from ..utils.validation import validate_symbol

        symbol = validate_symbol(symbol)

        # Get current quote (cached)
        quote = await self._get_quote_cached(symbol)

        if not quote or not quote.last:
            return f"Cannot get quote for {symbol}"

        stock_price = quote.last
        vix = await self.get_vix()

        recommendation = get_strategy_for_stock(vix, stock_price)

        b = MarkdownBuilder()
        b.h1(f"Strategy for {symbol}").blank()

        b.h2("Market Context")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")
        b.kv_line("Regime", recommendation.regime.value)
        b.kv_line("Stock Price", f"${stock_price:.2f}")
        b.blank()

        b.h2("Base Strategy: Bull-Put-Spread")
        b.kv_line("Short Put Delta", f"{recommendation.delta_target}")
        b.kv_line("Long Put Delta", f"{recommendation.long_delta_target}")
        b.kv_line("Delta-Range", f"[{recommendation.delta_min}, {recommendation.delta_max}]")
        b.kv_line("DTE", f"{recommendation.dte_min}-{recommendation.dte_max} days")
        b.kv_line("Earnings-Buffer", f">{recommendation.earnings_buffer_days} days")
        b.kv_line("Spread Width", "Dynamic (delta-based)")
        b.kv_line("Min-Score", f"{recommendation.min_score}")
        b.blank()

        b.hint(
            "Use `recommend_strikes` for specific strike recommendations with delta-based spread width."
        )
        b.blank()

        b.h2("Reasoning")
        b.text(recommendation.reasoning)

        if recommendation.warnings:
            b.blank()
            b.h2("Warnings")
            for warning in recommendation.warnings:
                b.text(f"* {warning}")

        return b.build()

    async def get_event_calendar(self, days: int = 30) -> str:
        """
        Get upcoming market events (FOMC, OPEX, etc.).

        Args:
            days: Number of days to look ahead

        Returns:
            Formatted event calendar
        """
        from ..indicators.events import EventCalendar, EventType
        from ..utils.markdown_builder import MarkdownBuilder

        calendar = EventCalendar(include_macro_events=True)

        events = calendar.get_upcoming_events(days_ahead=days)

        b = MarkdownBuilder()
        b.h1(f"Market Events (Next {days} Days)").blank()

        if not events:
            b.hint("No major events in this period.")
            return b.build()

        event_icons = {
            EventType.FED_MEETING: "[FED]",
            EventType.CPI: "[CPI]",
            EventType.NFP: "[NFP]",
            EventType.OPEX: "[OPEX]",
            EventType.EARNINGS: "[EARN]",
            EventType.DIVIDEND: "[DIV]",
        }

        rows = []
        for event in events[:20]:
            icon = event_icons.get(event.event_type, "[EVENT]")
            days_until = (event.event_date - date.today()).days
            rows.append(
                [
                    str(event.event_date),
                    f"+{days_until}d" if days_until >= 0 else f"{days_until}d",
                    f"{icon} {event.event_type.value}",
                    event.description or "-",
                ]
            )

        b.table(["Date", "Days", "Event", "Description"], rows)

        return b.build()

    async def get_sector_status(self) -> str:
        """
        Get current sector relative strength analysis for all sectors.

        Uses SectorRSService with RRG quadrant classification.

        Returns:
            Formatted Markdown sector status table
        """
        return await self._get_sector_status_v2()

    async def _get_sector_status_v2(self) -> str:
        """
        Sector RS v2: RRG quadrant-based analysis.

        Returns:
            Formatted Markdown with RS Ratio, Momentum, Quadrant, Modifier
        """
        from ..services.sector_rs import SectorRSService
        from ..utils.markdown_builder import MarkdownBuilder

        service = SectorRSService()
        rs_map = await service.get_all_sector_rs()

        b = MarkdownBuilder()
        b.h1("Sector Relative Strength (RRG)").blank()

        if not rs_map:
            b.hint("No sector data available.")
            return b.build()

        quadrant_icons = {
            "leading": "[+]",
            "improving": "[^]",
            "weakening": "[v]",
            "lagging": "[-]",
        }

        rows = []
        for rs in sorted(rs_map.values(), key=lambda x: x.rs_ratio, reverse=True):
            icon = quadrant_icons.get(rs.quadrant.value, "[ ]")
            modifier_str = f"{rs.score_modifier:+.1f}" if rs.score_modifier != 0 else "0.0"
            rows.append(
                [
                    rs.sector,
                    rs.etf_symbol,
                    f"{rs.rs_ratio:.1f}",
                    f"{rs.rs_momentum:.1f}",
                    f"{icon} {rs.quadrant.value.capitalize()}",
                    modifier_str,
                ]
            )

        b.table(
            ["Sector", "ETF", "RS Ratio", "Momentum", "Quadrant", "Modifier"],
            rows,
        )
        b.blank()
        b.hint(
            "RS > 100 = outperforming SPY. "
            "Quadrants: Leading (+0.5), Improving (+0.3), Weakening (-0.3), Lagging (-0.5). "
            "Modifier added to signal scores when sector_rs enabled."
        )

        return b.build()

    # --- Shared helper methods ---

    def _fetch_vix_yahoo(self) -> Optional[float]:
        """Fetch VIX from Yahoo Finance as fallback."""
        import json
        import urllib.request

        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
            timeout = self._ctx.config.settings.api_connection.yahoo_timeout

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")

            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode())

            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})

            regular_price = meta.get("regularMarketPrice")
            if regular_price:
                return float(regular_price)

            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if closes:
                for c in reversed(closes):
                    if c is not None:
                        return float(c)

            return None
        except Exception as e:
            self._logger.debug(f"Yahoo VIX fetch error: {e}")
            return None

    # _get_quote_cached inherited from BaseHandler
