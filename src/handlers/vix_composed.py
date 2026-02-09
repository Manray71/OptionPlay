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
                vix = await self._ctx.ibkr_bridge.get_vix()
                if vix is not None:
                    self._ctx.current_vix = vix
                    self._ctx.vix_updated = datetime.now()
                    return vix
            except Exception as e:
                self._logger.debug(f"IBKR VIX failed: {e}")

        # Try Tradier quote for VIX index
        await self._ensure_connected()
        if self._ctx.tradier_connected and self._ctx.tradier_provider:
            try:
                quote = await self._ctx.tradier_provider.get_quote("VIX")
                if quote and hasattr(quote, 'last') and quote.last:
                    self._ctx.current_vix = quote.last
                    self._ctx.vix_updated = datetime.now()
                    return quote.last
            except Exception as e:
                self._logger.debug(f"Tradier VIX quote failed: {e}")

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
        from ..vix_strategy import get_strategy_for_vix
        from ..formatters import formatters

        vix = await self.get_vix()
        recommendation = get_strategy_for_vix(vix)
        return formatters.strategy.format(recommendation, vix)

    async def get_regime_status(self) -> str:
        """
        Get current VIX regime status with trained model recommendations.

        Uses trained regime model if available, otherwise falls back to defaults.

        Returns:
            Formatted Markdown regime status
        """
        from ..backtesting import RegimeModel
        from ..backtesting import get_trained_model_loader
        from ..utils.markdown_builder import MarkdownBuilder

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
            from ..backtesting import get_regime_for_vix, FIXED_REGIMES

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
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder
        from ..vix_strategy import get_strategy_for_stock

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

        b.hint("Use `recommend_strikes` for specific strike recommendations with delta-based spread width.")
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
        from ..utils.markdown_builder import MarkdownBuilder
        from ..indicators.events import EventCalendar, EventType

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
            rows.append([
                str(event.event_date),
                f"+{days_until}d" if days_until >= 0 else f"{days_until}d",
                f"{icon} {event.event_type.value}",
                event.description or "-"
            ])

        b.table(["Date", "Days", "Event", "Description"], rows)

        return b.build()

    async def get_sector_status(self) -> str:
        """
        Get current sector momentum analysis for all sectors.

        Uses SectorCycleService to calculate relative strength,
        breadth, and momentum factors.

        Returns:
            Formatted Markdown sector status table
        """
        from ..services.sector_cycle_service import SectorCycleService
        from ..utils.markdown_builder import MarkdownBuilder

        service = SectorCycleService()
        statuses = await service.get_all_sector_statuses()

        b = MarkdownBuilder()
        b.h1("Sector Momentum Status").blank()

        if not statuses:
            b.hint("No sector data available.")
            return b.build()

        regime_icons = {
            "strong": "[+]",
            "neutral": "[ ]",
            "weak": "[-]",
            "crisis": "[!]",
        }

        rows = []
        for s in sorted(statuses, key=lambda x: x.momentum_factor, reverse=True):
            icon = regime_icons.get(s.regime.value, "[ ]")
            rows.append([
                s.sector,
                s.etf_symbol,
                f"{s.momentum_factor:.3f}",
                f"{icon} {s.regime.value.upper()}",
                f"{s.relative_strength_30d:+.1f}%",
                f"{s.relative_strength_60d:+.1f}%",
                f"{s.breadth_proxy:.2f}",
            ])

        b.table(
            ["Sector", "ETF", "Factor", "Regime", "RS 30d", "RS 60d", "Breadth"],
            rows,
        )
        b.blank()
        b.hint("Factor range: 0.6 (weak) to 1.2 (strong). Applied to signal scores when sector_momentum.enabled=true.")

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
            req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')

            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode())

            result = data.get('chart', {}).get('result', [{}])[0]
            meta = result.get('meta', {})

            regular_price = meta.get('regularMarketPrice')
            if regular_price:
                return float(regular_price)

            closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
            if closes:
                for c in reversed(closes):
                    if c is not None:
                        return float(c)

            return None
        except Exception as e:
            self._logger.debug(f"Yahoo VIX fetch error: {e}")
            return None

    # _get_quote_cached inherited from BaseHandler
