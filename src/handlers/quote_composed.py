"""
Quote Handler (Composition-Based)
==================================

Handles quote, options chain, historical data, and earnings lookups.

This is the composition-based version of QuoteHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .handler_container import BaseHandler, ServerContext
from ..constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS, SPREAD_DTE_MIN, SPREAD_DTE_MAX

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class QuoteHandler(BaseHandler):
    """
    Handler for quote and market data operations.

    Methods:
    - get_quote(): Get current stock quote
    - get_options_chain(): Get options chain with Greeks
    - get_earnings(): Check earnings date for a symbol
    - get_earnings_aggregated(): Multi-source earnings aggregation
    - earnings_prefilter(): Pre-filter watchlist by earnings dates
    - get_historical_data(): Get historical price data
    - get_expirations(): Get available options expiration dates
    - validate_for_trading(): Validate if a symbol is safe for trading
    """

    async def get_quote(self, symbol: str) -> str:
        """Get current stock quote."""
        from ..utils.validation import validate_symbol
        from ..formatters import formatters

        symbol = validate_symbol(symbol)
        quote = await self._get_quote_cached(symbol)
        return formatters.quote.format(symbol, quote)

    async def get_options_chain(
        self,
        symbol: str,
        dte_min: int = 60,
        dte_max: int = 90,
        right: str = "P",
        max_options: int = 15,
    ) -> str:
        """
        Get options chain for a symbol with automatic provider selection.

        Args:
            symbol: Ticker symbol
            dte_min: Minimum days to expiration
            dte_max: Maximum days to expiration
            right: Option type (P for puts, C for calls)
            max_options: Maximum options to display

        Returns:
            Formatted options chain
        """
        from ..utils.validation import validate_symbol, validate_dte_range
        from ..formatters import formatters

        symbol = validate_symbol(symbol)
        dte_min, dte_max = validate_dte_range(dte_min, dte_max)

        quote = await self._get_quote_cached(symbol)
        underlying_price = quote.last if quote else None

        options = await self._get_options_chain_with_fallback(
            symbol, dte_min=dte_min, dte_max=dte_max, right=right
        )

        return formatters.options_chain.format(
            symbol=symbol,
            options=options or [],
            underlying_price=underlying_price,
            right=right,
            dte_min=dte_min,
            dte_max=dte_max,
            max_options=max_options
        )

    def _fetch_yahoo_earnings(self, symbol: str) -> Dict:
        """Fetch earnings date directly from Yahoo Finance API."""
        try:
            url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=calendarEvents"
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')

            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

            calendar = data.get('quoteSummary', {}).get('result', [{}])[0].get('calendarEvents', {})
            earnings = calendar.get('earnings', {})
            earnings_date = None
            earnings_dates = earnings.get('earningsDate', [])

            if earnings_dates:
                timestamp = earnings_dates[0].get('raw')
                if timestamp:
                    earnings_date = datetime.fromtimestamp(timestamp).date()

            if earnings_date:
                days_to = (earnings_date - date.today()).days
                return {
                    'earnings_date': earnings_date.isoformat(),
                    'days_to_earnings': days_to if days_to >= 0 else None,
                    'source': 'yahoo_direct'
                }

            return {'earnings_date': None, 'days_to_earnings': None, 'source': 'yahoo_direct'}
        except Exception as e:
            self._logger.debug(f"Yahoo earnings API error for {symbol}: {e}")
            return {'earnings_date': None, 'days_to_earnings': None, 'source': 'error'}

    async def get_earnings(self, symbol: str, min_days: int = ENTRY_EARNINGS_MIN_DAYS) -> str:
        """
        Check earnings date for a symbol with multi-source fallback.

        Args:
            symbol: Ticker symbol
            min_days: Minimum days until earnings for safety

        Returns:
            Formatted earnings information
        """
        from ..utils.validation import validate_symbol, is_etf
        from ..formatters import formatters
        from ..cache import get_earnings_fetcher

        symbol = validate_symbol(symbol)

        if is_etf(symbol):
            return formatters.earnings.format(
                symbol=symbol, earnings_date=None, days_to_earnings=None,
                min_days=min_days, source="etf", is_etf=True
            )

        earnings_date = None
        days_to_earnings = None
        source_used = "unknown"

        # 1. Try Marketdata.app
        try:
            provider = await self._ensure_connected()
            await self._ctx.rate_limiter.acquire()
            earnings = await provider.get_earnings_date(symbol)
            self._ctx.rate_limiter.record_success()

            if earnings and earnings.earnings_date:
                earnings_date = earnings.earnings_date
                days_to_earnings = earnings.days_to_earnings
                source_used = "marketdata"
        except Exception as e:
            self._logger.debug(f"Marketdata.app earnings failed for {symbol}: {e}")

        # 2. Fallback to Yahoo Finance direct
        if not earnings_date:
            try:
                yahoo_data = await asyncio.to_thread(self._fetch_yahoo_earnings, symbol)
                if yahoo_data.get('earnings_date'):
                    earnings_date = yahoo_data['earnings_date']
                    days_to_earnings = yahoo_data['days_to_earnings']
                    source_used = "yahoo_direct"
            except Exception as e:
                self._logger.debug(f"Yahoo direct earnings failed for {symbol}: {e}")

        # 3. Final fallback: yfinance library
        if not earnings_date:
            try:
                if self._ctx.earnings_fetcher is None:
                    self._ctx.earnings_fetcher = get_earnings_fetcher()

                fetched = await asyncio.to_thread(self._ctx.earnings_fetcher.fetch, symbol)
                if fetched and fetched.earnings_date:
                    earnings_date = fetched.earnings_date
                    days_to_earnings = fetched.days_to_earnings
                    source_used = fetched.source.value
            except Exception as e:
                self._logger.debug(f"yfinance earnings failed for {symbol}: {e}")

        return formatters.earnings.format(
            symbol=symbol, earnings_date=earnings_date,
            days_to_earnings=days_to_earnings, min_days=min_days,
            source=source_used
        )

    async def get_earnings_aggregated(self, symbol: str, min_days: int = ENTRY_EARNINGS_MIN_DAYS) -> str:
        """
        Check earnings date with multi-source aggregation and majority voting.

        Args:
            symbol: Ticker symbol
            min_days: Minimum days until earnings for safety

        Returns:
            Aggregated earnings information with confidence
        """
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder
        from ..cache import get_earnings_fetcher
        from ..utils.earnings_aggregator import (
            EarningsResult, get_earnings_aggregator, create_earnings_result,
        )

        symbol = validate_symbol(symbol)
        results: List[EarningsResult] = []

        async def fetch_marketdata() -> EarningsResult:
            try:
                provider = await self._ensure_connected()
                await self._ctx.rate_limiter.acquire()
                earnings = await provider.get_earnings_date(symbol)
                self._ctx.rate_limiter.record_success()

                if earnings and earnings.earnings_date:
                    return create_earnings_result(
                        source="marketdata",
                        earnings_date=earnings.earnings_date,
                        days_to_earnings=earnings.days_to_earnings,
                    )
                return create_earnings_result(source="marketdata", earnings_date=None, days_to_earnings=None)
            except Exception as e:
                return create_earnings_result(source="marketdata", earnings_date=None, days_to_earnings=None, error=str(e))

        async def fetch_yahoo() -> EarningsResult:
            try:
                yahoo_data = await asyncio.to_thread(self._fetch_yahoo_earnings, symbol)
                return create_earnings_result(
                    source="yahoo_direct",
                    earnings_date=yahoo_data.get("earnings_date"),
                    days_to_earnings=yahoo_data.get("days_to_earnings"),
                )
            except Exception as e:
                return create_earnings_result(source="yahoo_direct", earnings_date=None, days_to_earnings=None, error=str(e))

        async def fetch_yfinance() -> EarningsResult:
            try:
                if self._ctx.earnings_fetcher is None:
                    self._ctx.earnings_fetcher = get_earnings_fetcher()

                fetched = await asyncio.to_thread(self._ctx.earnings_fetcher.fetch, symbol)
                if fetched and fetched.earnings_date:
                    return create_earnings_result(
                        source="yfinance",
                        earnings_date=fetched.earnings_date,
                        days_to_earnings=fetched.days_to_earnings,
                    )
                return create_earnings_result(source="yfinance", earnings_date=None, days_to_earnings=None)
            except Exception as e:
                return create_earnings_result(source="yfinance", earnings_date=None, days_to_earnings=None, error=str(e))

        results = await asyncio.gather(fetch_marketdata(), fetch_yahoo(), fetch_yfinance())

        aggregator = get_earnings_aggregator()
        aggregated = aggregator.aggregate(symbol, list(results))

        b = MarkdownBuilder()
        b.h1(f"Earnings Check: {symbol}").blank()

        if aggregated.consensus_date:
            days = aggregated.days_to_earnings or 0
            if days < 0:
                is_safe = True
                status = "SAFE (past earnings)"
            else:
                is_safe = days >= min_days
                status = "SAFE" if is_safe else "TOO CLOSE"

            b.h2("Consensus Result")
            b.kv_line("Date", aggregated.consensus_date)
            b.kv_line("Days", f"{aggregated.days_to_earnings} (Min: {min_days})")
            b.kv_line("Status", status)
            b.kv_line("Confidence", f"{aggregated.confidence}%")
        else:
            b.status_warning("No earnings date found from any source.")

        return b.build()

    async def earnings_prefilter(
        self,
        min_days: int = 45,
        symbols: Optional[List[str]] = None,
        show_excluded: bool = False,
    ) -> str:
        """
        Pre-filter watchlist by earnings dates.

        Args:
            min_days: Minimum days until earnings
            symbols: Optional specific symbols (default: full watchlist)
            show_excluded: Show excluded symbols with their earnings dates

        Returns:
            Formatted Markdown with safe symbols and cache statistics
        """
        from ..utils.validation import validate_symbols, is_etf
        from ..utils.markdown_builder import MarkdownBuilder
        from ..config import get_watchlist_loader
        from ..cache import get_earnings_fetcher

        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)

        if self._ctx.earnings_fetcher is None:
            self._ctx.earnings_fetcher = get_earnings_fetcher()

        start_time = datetime.now()

        safe_symbols: List[str] = []
        excluded_symbols: List[tuple] = []
        unknown_symbols: List[str] = []
        etf_symbols: List[str] = []
        cache_hits = 0
        api_calls = 0

        for symbol in symbols:
            try:
                if is_etf(symbol):
                    etf_symbols.append(symbol)
                    safe_symbols.append(symbol)
                    continue

                cached = self._ctx.earnings_fetcher.cache.get(symbol)
                if cached:
                    cache_hits += 1
                    earnings_date_str = cached.earnings_date
                    days_to = cached.days_to_earnings
                else:
                    api_calls += 1
                    fetched = await asyncio.to_thread(self._ctx.earnings_fetcher.fetch, symbol)
                    earnings_date_str = fetched.earnings_date if fetched else None
                    days_to = fetched.days_to_earnings if fetched else None

                if days_to is None:
                    unknown_symbols.append(symbol)
                    safe_symbols.append(symbol)
                elif days_to >= min_days:
                    safe_symbols.append(symbol)
                else:
                    excluded_symbols.append((symbol, earnings_date_str, days_to))

            except Exception as e:
                self._logger.debug(f"Earnings check failed for {symbol}: {e}")
                unknown_symbols.append(symbol)
                safe_symbols.append(symbol)

        duration = (datetime.now() - start_time).total_seconds()

        b = MarkdownBuilder()
        b.h1("Earnings Pre-Filter").blank()

        b.h2("Summary")
        b.kv_line("Total Symbols", len(symbols))
        b.kv_line("Min Days to Earnings", min_days)
        safe_count = len(safe_symbols) - len(unknown_symbols) - len(etf_symbols)
        b.kv_line("Safe (>= min_days)", safe_count)
        b.kv_line("ETFs (no earnings)", len(etf_symbols))
        b.kv_line("Excluded (< min_days)", len(excluded_symbols))
        b.kv_line("Unknown (no date)", len(unknown_symbols))
        b.blank()

        b.h2("Cache Statistics")
        b.kv_line("Cache Hits", f"{cache_hits} ({cache_hits*100//len(symbols) if symbols else 0}%)")
        b.kv_line("API Calls", api_calls)
        b.kv_line("Duration", f"{duration:.1f}s")
        b.blank()

        if show_excluded and excluded_symbols:
            b.h2("Excluded Symbols")
            excluded_symbols.sort(key=lambda x: x[2] if x[2] else 999)
            rows = []
            for sym, date_str, days in excluded_symbols[:30]:
                rows.append([sym, date_str or "N/A", str(days) if days else "N/A"])
            b.table(["Symbol", "Earnings Date", "Days"], rows)
            b.blank()

        b.h2("Safe Symbols for Scanning")
        b.kv_line("Count", len(safe_symbols))
        if len(safe_symbols) <= 50:
            b.text(", ".join(sorted(safe_symbols)))
        else:
            b.text(f"First 50: {', '.join(sorted(safe_symbols)[:50])}...")

        return b.build()

    async def get_historical_data(self, symbol: str, days: int = 30) -> str:
        """
        Get historical price data.

        Args:
            symbol: Ticker symbol
            days: Number of days of history

        Returns:
            Formatted historical data
        """
        from ..utils.validation import validate_symbol
        from ..formatters import formatters

        symbol = validate_symbol(symbol)
        provider = await self._ensure_connected()

        await self._ctx.rate_limiter.acquire()
        bars = await provider.get_historical(symbol, days=days)
        self._ctx.rate_limiter.record_success()

        return formatters.historical.format(symbol=symbol, bars=bars or [], days_shown=10)

    async def get_expirations(self, symbol: str) -> str:
        """
        Get available options expiration dates for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            List of available expiration dates
        """
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder

        symbol = validate_symbol(symbol)
        expirations = None

        # Try Tradier first
        if self._ctx.tradier_connected and self._ctx.tradier_provider:
            try:
                expirations = await self._ctx.tradier_provider.get_expirations(symbol)
            except Exception as e:
                self._logger.debug(f"Tradier expirations failed: {e}")

        # Fallback to Marketdata
        if not expirations:
            provider = await self._ensure_connected()
            await self._ctx.rate_limiter.acquire()
            expirations = await provider.get_expirations(symbol)
            self._ctx.rate_limiter.record_success()

        b = MarkdownBuilder()
        b.h1(f"Option Expirations: {symbol}").blank()

        if not expirations:
            b.hint("No expiration dates found.")
            return b.build()

        b.kv_line("Total", len(expirations))
        b.blank()

        rows = []
        for exp in expirations[:20]:
            days_to = (exp - date.today()).days
            rows.append([str(exp), f"{days_to}d"])

        b.table(["Expiration", "DTE"], rows)

        if len(expirations) > 20:
            b.hint(f"... and {len(expirations) - 20} more")

        return b.build()

    async def validate_for_trading(self, symbol: str) -> str:
        """
        Validate if a symbol is safe for trading based on earnings and events.

        Args:
            symbol: Ticker symbol

        Returns:
            Validation result with safety status
        """
        from ..utils.validation import validate_symbol, is_etf
        from ..utils.markdown_builder import MarkdownBuilder
        from ..cache import get_earnings_fetcher
        from ..constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS

        symbol = validate_symbol(symbol)

        if is_etf(symbol):
            b = MarkdownBuilder()
            b.h1(f"Trading Validation: {symbol}").blank()
            b.status_ok("SAFE - ETF (no earnings)")
            return b.build()

        earnings_date = None
        days_to_earnings = None

        try:
            provider = await self._ensure_connected()
            await self._ctx.rate_limiter.acquire()
            earnings = await provider.get_earnings_date(symbol)
            self._ctx.rate_limiter.record_success()

            if earnings:
                earnings_date = earnings.earnings_date
                days_to_earnings = earnings.days_to_earnings
        except Exception as e:
            self._logger.debug(f"Earnings validation failed: {e}")

        if not earnings_date:
            try:
                if self._ctx.earnings_fetcher is None:
                    self._ctx.earnings_fetcher = get_earnings_fetcher()
                fetched = await asyncio.to_thread(self._ctx.earnings_fetcher.fetch, symbol)
                if fetched:
                    earnings_date = fetched.earnings_date
                    days_to_earnings = fetched.days_to_earnings
            except Exception as e:
                self._logger.debug(f"yfinance earnings validation failed: {e}")

        b = MarkdownBuilder()
        b.h1(f"Trading Validation: {symbol}").blank()

        if days_to_earnings is not None:
            is_safe = days_to_earnings >= ENTRY_EARNINGS_MIN_DAYS
            status = "SAFE" if is_safe else "CAUTION"
            icon = "[OK]" if is_safe else "[!]"

            b.h2("Earnings Check")
            b.kv_line("Status", f"{icon} {status}")
            b.kv_line("Next Earnings", earnings_date or "Unknown")
            b.kv_line("Days Until", days_to_earnings)
            b.kv_line("Min Required", f"{ENTRY_EARNINGS_MIN_DAYS} days")
        else:
            b.h2("Earnings Check")
            b.kv_line("Status", "[?] UNKNOWN")
            b.kv_line("Note", "Could not determine earnings date")

        return b.build()

    # --- Shared helper methods ---

    async def _get_options_chain_with_fallback(self, symbol, dte_min=SPREAD_DTE_MIN, dte_max=SPREAD_DTE_MAX, right="P"):
        """Fetch options chain with Tradier-first, IBKR-fallback."""
        options = None
        right_upper = right.upper()

        if self._ctx.tradier_connected and self._ctx.tradier_provider:
            try:
                options = await self._ctx.tradier_provider.get_option_chain(
                    symbol, dte_min=dte_min, dte_max=dte_max, right=right_upper
                )
                if options:
                    return options
            except Exception as e:
                self._logger.debug(f"Tradier options failed: {e}")

        if self._ctx.ibkr_bridge:
            try:
                if await self._ctx.ibkr_bridge.is_available():
                    options = await self._ctx.ibkr_bridge.get_option_chain(
                        symbol, dte_min=dte_min, dte_max=dte_max, right=right_upper
                    )
                    if options:
                        return options
            except Exception as e:
                self._logger.debug(f"IBKR options failed: {e}")

        return options or []
