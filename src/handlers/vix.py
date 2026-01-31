"""
VIX Handler Module
==================

Handles VIX-related operations, strategy recommendations, and regime status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
import urllib.error
from datetime import date, datetime
from typing import Optional

from ..utils.error_handler import mcp_endpoint
from ..utils.markdown_builder import MarkdownBuilder
from ..utils.validation import validate_symbol
from ..vix_strategy import (
    get_strategy_for_vix, get_strategy_for_stock,
    calculate_spread_width, get_spread_width_table
)
from ..formatters import formatters
from ..indicators.events import EventCalendar, EventType
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
            req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')

            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode())

            result = data.get('chart', {}).get('result', [{}])[0]
            meta = result.get('meta', {})

            regular_price = meta.get('regularMarketPrice')
            if regular_price:
                return float(regular_price)

            # Fallback: last close from candles
            closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
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
        Get current VIX regime status with trained model recommendations.

        Uses trained regime model if available, otherwise falls back to defaults.

        Returns:
            Formatted Markdown regime status
        """
        from ..backtesting.regime_model import RegimeModel
        from ..backtesting.regime_config import get_trained_model_loader

        vix = await self.get_vix()

        if vix is None:
            return "Could not fetch VIX - unable to determine regime"

        try:
            # Try to load trained model
            model = RegimeModel.load_latest()
            model.initialize(vix)
            status = model.get_status()
            params = status.parameters

            b = MarkdownBuilder()
            b.h1("VIX Regime Status").blank()

            # Current Status
            b.h2("Current Regime")
            regime_emoji = {
                "low_vol": "[LOW]",
                "normal": "[NORMAL]",
                "elevated": "[ELEVATED]",
                "high_vol": "[HIGH]",
            }.get(status.current_regime, "[?]")

            b.kv_line("VIX", f"{vix:.2f}")
            b.kv_line("Regime", f"{regime_emoji} {status.current_regime.upper()}")
            b.kv_line("VIX Range", f"{params.vix_range[0]:.0f} - {params.vix_range[1]:.0f}")
            b.kv_line("Days in Regime", str(status.days_in_regime))

            if status.pending_transition:
                b.kv_line("Pending", f"{status.pending_transition} ({status.pending_days} days)")

            b.blank()

            # Per-Strategy Min Scores (if trained model available)
            loader = get_trained_model_loader()
            if loader.is_loaded:
                b.h2("Strategy Min Scores (Trained)")
                for strategy in params.strategies_enabled:
                    min_score = model.get_min_score_for_strategy(strategy, params.regime)
                    b.kv_line(f"  {strategy.capitalize()}", f"{min_score:.1f}")
                b.blank()

            # General Trading Parameters
            b.h2("Trading Parameters")
            b.kv_line("Base Min Score", f"{params.min_score:.1f}")
            b.kv_line("Profit Target", f"{params.profit_target_pct:.0f}%")
            b.kv_line("Stop Loss", f"{params.stop_loss_pct:.0f}%")
            b.kv_line("Position Size", f"{params.position_size_pct:.1f}%")
            b.kv_line("Max Positions", str(params.max_concurrent_positions))
            b.blank()

            # Strategies
            b.h2("Enabled Strategies")
            strategies_list = ", ".join(params.strategies_enabled) if params.strategies_enabled else "None"
            b.text(strategies_list)
            b.blank()

            # Model Info
            b.h2("Model Info")
            trained_icon = "[OK]" if params.is_trained else "[!]"
            b.kv_line("Trained Model", f"{trained_icon} {'Yes' if params.is_trained else 'No (using defaults)'}")
            b.kv_line("Confidence", params.confidence_level.upper())

            # Training stats if available
            if loader.is_loaded and loader.summary:
                summary = loader.summary
                b.blank()
                b.h2("Training Stats")
                b.kv_line("Total Trades", f"{summary.get('total_trades', 0):,}")
                b.kv_line("Win Rate", f"{summary.get('win_rate', 0):.1f}%")
                b.kv_line("Total P&L", f"${summary.get('total_pnl', 0):,.0f}")

            return b.build()

        except FileNotFoundError:
            # No trained model available - use defaults
            from ..backtesting.regime_config import get_regime_for_vix, FIXED_REGIMES

            regime_name, config = get_regime_for_vix(vix, FIXED_REGIMES)

            b = MarkdownBuilder()
            b.h1("VIX Regime Status (Default)").blank()

            b.h2("Current Regime")
            regime_emoji = {
                "low_vol": "[LOW]",
                "normal": "[NORMAL]",
                "elevated": "[ELEVATED]",
                "high_vol": "[HIGH]",
            }.get(regime_name, "[?]")

            b.kv_line("VIX", f"{vix:.2f}")
            b.kv_line("Regime", f"{regime_emoji} {regime_name.upper()}")
            b.kv_line("VIX Range", f"{config.vix_lower:.0f} - {config.vix_upper:.0f}")
            b.blank()

            b.h2("Default Parameters")
            b.kv_line("Min Score", f"{config.min_score:.1f}")
            b.kv_line("Profit Target", f"{config.profit_target_pct:.0f}%")
            b.kv_line("Stop Loss", f"{config.stop_loss_pct:.0f}%")
            b.blank()

            b.h2("Enabled Strategies")
            b.text(", ".join(config.strategies_enabled))
            b.blank()

            b.text("**Note**: Using default parameters. Run `train_regime_model.py` to train a model.")

            return b.build()

        except Exception as e:
            logger.error(f"Regime status error: {e}")
            return f"Error getting regime status: {e}"

    @mcp_endpoint(operation="strategy for stock", symbol_param="symbol")
    async def get_strategy_for_stock(self, symbol: str) -> str:
        """
        Get strategy recommendation with dynamic spread width based on stock price.

        Args:
            symbol: Ticker symbol

        Returns:
            Formatted Markdown recommendation with optimal spread width
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

        b.h2("Base Strategy: Short Put")
        b.kv_line("Delta-Target", f"{recommendation.delta_target}")
        b.kv_line("Delta-Range", f"[{recommendation.delta_min}, {recommendation.delta_max}]")
        b.kv_line("DTE", f"{recommendation.dte_min}-{recommendation.dte_max} days")
        b.kv_line("Earnings-Buffer", f">{recommendation.earnings_buffer_days} days")
        b.blank()

        b.h2("Dynamic Spread Width")
        b.kv_line("Recommended Width", f"${recommendation.spread_width:.2f}")
        b.kv_line("Min-Score", f"{recommendation.min_score}")
        b.blank()

        # Spread width table
        spread_table = get_spread_width_table(stock_price)
        b.h3("Spread Width by Regime")
        rows = [
            ["Low Vol (VIX <15)", f"${spread_table['low_vol']:.2f}"],
            ["Normal (VIX 15-20)", f"${spread_table['normal']:.2f}"],
            ["Elevated (VIX 20-30)", f"${spread_table['elevated']:.2f}"],
            ["High Vol (VIX >30)", f"${spread_table['high_vol']:.2f}"],
        ]
        b.table(["Regime", "Spread"], rows)
        b.blank()

        b.h2("Reasoning")
        b.text(recommendation.reasoning)

        if recommendation.warnings:
            b.blank()
            b.h2("Warnings")
            for warning in recommendation.warnings:
                b.text(f"* {warning}")

        return b.build()

    @mcp_endpoint(operation="spread width calculation", symbol_param="symbol")
    async def get_spread_width(self, symbol: str) -> str:
        """
        Calculate optimal spread width for a symbol based on price and VIX.

        Args:
            symbol: Ticker symbol

        Returns:
            Spread width recommendation table
        """
        symbol = validate_symbol(symbol)

        quote = await self._get_quote_cached(symbol)

        if not quote or not quote.last:
            return f"Cannot get quote for {symbol}"

        stock_price = quote.last
        vix = await self.get_vix()
        regime = self._vix_selector.get_regime(vix)

        current_spread = calculate_spread_width(stock_price, regime)
        spread_table = get_spread_width_table(stock_price)

        b = MarkdownBuilder()
        b.h1(f"Spread Width: {symbol}").blank()

        b.kv_line("Stock Price", f"${stock_price:.2f}")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")
        b.kv_line("Regime", regime.value if regime else "unknown")
        b.blank()

        b.h2("Recommended Spread Width")
        b.kv_line("Current Recommendation", f"${current_spread:.2f}")
        b.blank()

        b.h2("Table by VIX Regime")
        rows = [
            ["Low Vol (VIX <15)", f"${spread_table['low_vol']:.2f}"],
            ["Normal (VIX 15-20)", f"${spread_table['normal']:.2f}"],
            ["Elevated (VIX 20-30)", f"${spread_table['elevated']:.2f}"],
            ["High Vol (VIX >30)", f"${spread_table['high_vol']:.2f}"],
        ]
        b.table(["Regime", "Spread Width"], rows)

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
            rows.append([
                str(event.event_date),
                f"+{days_until}d" if days_until >= 0 else f"{days_until}d",
                f"{icon} {event.event_type.value}",
                event.description or "-"
            ])

        b.table(["Date", "Days", "Event", "Description"], rows)

        return b.build()
