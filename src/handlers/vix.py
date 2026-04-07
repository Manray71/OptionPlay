"""
VIX Handler Module
==================

Handles VIX-related operations, strategy recommendations, and regime status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Optional

from ..constants import DELTA_LONG_TARGET, DELTA_TARGET
from ..formatters import formatters
from ..indicators.events import EventCalendar, EventType
from ..services.vix_strategy import (
    get_strategy_for_stock,
    get_strategy_for_vix,
)
from ..utils.error_handler import mcp_endpoint
from ..utils.markdown_builder import MarkdownBuilder
from ..utils.validation import validate_symbol
from .base import BaseHandlerMixin

logger = logging.getLogger(__name__)


class VixHandlerMixin(BaseHandlerMixin):
    """
    Mixin for VIX and strategy-related handler methods.
    """

    def _fetch_vix_yahoo(self) -> Optional[float]:
        """
        Fetch VIX from Yahoo Finance as fallback.

        Returns:
            VIX value or None if fetch fails
        """
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
            timeout = self._config.settings.api_connection.yahoo_timeout

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")

            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode())

            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})

            regular_price = meta.get("regularMarketPrice")
            if regular_price:
                return float(regular_price)

            # Fallback: last close from candles
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if closes:
                for c in reversed(closes):
                    if c is not None:
                        return float(c)

            return None

        except Exception as e:
            logger.debug(f"Yahoo VIX fetch error: {e}")
            return None

    @mcp_endpoint(operation="VIX lookup")
    async def get_vix(self, force_refresh: bool = False) -> Optional[float]:
        """
        Get current VIX (with 5-minute cache).

        Uses Marketdata.app as primary source, Yahoo Finance as fallback.

        Args:
            force_refresh: Force refresh even if cached value exists

        Returns:
            VIX value or None
        """
        vix_cache_seconds = self._config.settings.api_connection.vix_cache_seconds

        # Check cache
        if not force_refresh and self._current_vix and self._vix_updated:
            age = (datetime.now() - self._vix_updated).total_seconds()
            if age < vix_cache_seconds:
                return self._current_vix

        vix = None
        source = "unknown"

        # 1. Try Marketdata.app
        try:
            provider = await self._ensure_connected()
            await self._rate_limiter.acquire()
            vix = await provider.get_vix()
            if vix:
                source = "marketdata"
            self._rate_limiter.record_success()
        except Exception as e:
            logger.debug(f"Marketdata.app VIX failed: {e}")

        # 2. Fallback to Yahoo Finance
        if vix is None:
            try:
                vix = await asyncio.to_thread(self._fetch_vix_yahoo)
                if vix:
                    source = "yahoo"
            except Exception as e:
                logger.debug(f"Yahoo VIX failed: {e}")

        # Update cache
        if vix:
            self._current_vix = vix
            self._vix_updated = datetime.now()
            logger.info(f"VIX updated: {vix:.2f} (source: {source})")

        return vix if vix else self._current_vix

    @mcp_endpoint(operation="strategy recommendation")
    async def get_strategy_recommendation(self) -> str:
        """
        Get current strategy recommendation based on VIX.

        Returns:
            Formatted Markdown recommendation
        """
        vix = await self.get_vix()
        recommendation = get_strategy_for_vix(vix)
        return formatters.strategy.format(recommendation, vix)

    @mcp_endpoint(operation="regime status")
    async def get_regime_status(self) -> str:
        """
        Get current VIX regime status.

        Legacy handler — use VixComposedHandler.get_regime_status_v2() instead.
        """
        return "Regime status requires composed handler (VIX v2 active)"

    @mcp_endpoint(operation="strategy for stock", symbol_param="symbol")
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

    @mcp_endpoint(operation="event calendar")
    async def get_event_calendar(self, days: int = 30) -> str:
        """
        Get upcoming market events (FOMC, OPEX, etc.).

        Args:
            days: Number of days to look ahead

        Returns:
            Formatted event calendar
        """
        from datetime import timedelta

        calendar = EventCalendar(include_macro_events=True)
        end_date = date.today() + timedelta(days=days)

        events = [e for e in calendar.events if e.event_date <= end_date]
        events = sorted(events, key=lambda e: e.event_date)

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

    @mcp_endpoint(operation="sector status")
    async def get_sector_status(self) -> str:
        """
        Get current sector momentum analysis for all sectors.

        Uses SectorRSService to calculate relative strength
        with RRG quadrant classification.

        Returns:
            Formatted Markdown sector status table
        """
        from ..services.sector_rs import SectorRSService

        service = SectorRSService()
        statuses = await service.get_all_sector_statuses()

        b = MarkdownBuilder()
        b.h1("Sector RS Analysis").blank()

        if not statuses:
            b.hint("No sector data available.")
            return b.build()

        quadrant_icons = {
            "leading": "[+]",
            "improving": "[^]",
            "weakening": "[v]",
            "lagging": "[-]",
        }

        rows = []
        for s in sorted(statuses, key=lambda x: x.rs_ratio, reverse=True):
            icon = quadrant_icons.get(s.quadrant.value, "[ ]")
            rows.append(
                [
                    s.sector,
                    s.etf_symbol,
                    f"{s.rs_ratio:.1f}",
                    f"{s.rs_momentum:.1f}",
                    f"{icon} {s.quadrant.value.capitalize()}",
                    f"{s.score_modifier:+.1f}",
                ]
            )

        b.table(
            ["Sector", "ETF", "RS Ratio", "Momentum", "Quadrant", "Modifier"],
            rows,
        )
        b.blank()
        b.hint(
            "RS Ratio > 100 = outperforming SPY. Modifier applied additively to signal scores."
        )

        return b.build()
