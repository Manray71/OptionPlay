"""
Scan Handler Module
===================

Handles all scanning operations: pullback, bounce, breakout, earnings dip, multi-strategy.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Callable

from ..scanner.multi_strategy_scanner import ScanMode
from ..utils.error_handler import mcp_endpoint
from ..utils.markdown_builder import MarkdownBuilder, truncate
from ..utils.validation import validate_symbols, is_etf
from ..config import get_watchlist_loader
from ..cache import get_earnings_fetcher
from .base import BaseHandlerMixin

logger = logging.getLogger(__name__)


class ScanHandlerMixin(BaseHandlerMixin):
    """
    Mixin for scan-related handler methods.
    """

    async def _execute_scan(
        self,
        mode: ScanMode,
        title: str,
        emoji: str,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
        min_historical_days: int = 0,
        table_columns: Optional[List[str]] = None,
        row_formatter: Optional[Callable] = None,
        no_results_msg: str = "No candidates found.",
    ) -> str:
        """
        Common scan execution logic for all strategy-specific scans.

        This method encapsulates the shared pattern across scan_bounce,
        scan_ath_breakout, scan_earnings_dip, and scan_multi_strategy.

        Args:
            mode: ScanMode determining which strategies to enable
            title: Header title for the output
            emoji: Emoji prefix for the header
            symbols: Optional list of symbols (default: watchlist)
            max_results: Maximum number of results
            min_score: Minimum score threshold
            min_historical_days: Minimum historical data days (0 = use config default)
            table_columns: Column headers for results table
            row_formatter: Function to format each signal into a table row
            no_results_msg: Message when no candidates found

        Returns:
            Formatted Markdown string with scan results
        """
        await self._ensure_connected()

        # Load and validate symbols
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)

        # Apply earnings pre-filter if enabled
        original_count = len(symbols)
        excluded_by_earnings = 0
        earnings_cache_hits = 0

        scanner_config = self._config.settings.scanner
        skip_prefilter = mode in [ScanMode.ALL, ScanMode.BEST_SIGNAL]

        if scanner_config.auto_earnings_prefilter and not skip_prefilter:
            min_days = scanner_config.earnings_prefilter_min_days
            for_earnings_dip = (mode == ScanMode.EARNINGS_DIP)
            symbols, excluded_by_earnings, earnings_cache_hits = await self._apply_earnings_prefilter(
                symbols, min_days, for_earnings_dip=for_earnings_dip
            )
            if excluded_by_earnings > 0:
                if for_earnings_dip:
                    logger.info(
                        f"Earnings pre-filter (dip mode): {excluded_by_earnings}/{original_count} symbols excluded "
                        f"(no recent past earnings), {earnings_cache_hits} cache hits"
                    )
                else:
                    logger.info(
                        f"Earnings pre-filter: {excluded_by_earnings}/{original_count} symbols excluded "
                        f"(earnings within {min_days} days), {earnings_cache_hits} cache hits"
                    )

        # Check scan cache first
        cache_key = self._make_scan_cache_key(mode, symbols, min_score, max_results)
        cache_hit = False

        if cache_key in self._scan_cache:
            cached_result, cached_time = self._scan_cache[cache_key]
            age = (datetime.now() - cached_time).total_seconds()
            if age < self._scan_cache_ttl:
                result = cached_result
                cache_hit = True
                self._scan_cache_hits += 1
                duration = 0.0
                logger.info(f"Scan cache HIT: {mode.value} (age: {age:.0f}s)")

        if not cache_hit:
            self._scan_cache_misses += 1

            # Configure scanner based on mode
            enable_pullback = mode in [ScanMode.PULLBACK_ONLY, ScanMode.ALL, ScanMode.BEST_SIGNAL]
            enable_bounce = mode in [ScanMode.BOUNCE_ONLY, ScanMode.ALL, ScanMode.BEST_SIGNAL]
            enable_breakout = mode in [ScanMode.BREAKOUT_ONLY, ScanMode.ALL, ScanMode.BEST_SIGNAL]
            enable_earnings_dip = mode in [ScanMode.EARNINGS_DIP, ScanMode.ALL, ScanMode.BEST_SIGNAL]

            scanner = self._get_multi_scanner(
                min_score=min_score,
                enable_pullback=enable_pullback,
                enable_bounce=enable_bounce,
                enable_breakout=enable_breakout,
                enable_earnings_dip=enable_earnings_dip,
            )
            scanner.config.max_total_results = max_results

            # Load earnings dates into scanner
            if self._earnings_fetcher is None:
                self._earnings_fetcher = get_earnings_fetcher()

            for symbol in symbols:
                cached = self._earnings_fetcher.cache.get(symbol)
                if cached and cached.earnings_date:
                    try:
                        earnings_date = date.fromisoformat(cached.earnings_date)
                        scanner.set_earnings_date(symbol, earnings_date)
                    except (ValueError, TypeError):
                        pass

            # Determine historical data requirement
            config_days = self._config.settings.performance.historical_days
            historical_days = max(config_days, min_historical_days) if min_historical_days else config_days

            # Pre-fetch historical data in parallel batches
            prefetch_batch_size = getattr(
                self._config.settings.performance, 'prefetch_batch_size', 20
            )

            prefetch_cache: Dict[str, tuple] = {}

            async def prefetch_batch(batch_symbols: List[str]) -> None:
                """Pre-fetch a batch of symbols in parallel."""
                tasks = [
                    self._fetch_historical_cached(sym, days=historical_days)
                    for sym in batch_symbols
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for sym, result in zip(batch_symbols, results):
                    if result is not None and not isinstance(result, Exception):
                        prefetch_cache[sym] = result

            for i in range(0, len(symbols), prefetch_batch_size):
                batch = symbols[i:i + prefetch_batch_size]
                await prefetch_batch(batch)

            logger.debug(f"Pre-fetched {len(prefetch_cache)}/{len(symbols)} symbols")

            async def data_fetcher(symbol: str):
                if symbol in prefetch_cache:
                    return prefetch_cache[symbol]
                return await self._fetch_historical_cached(symbol, days=historical_days)

            # Execute scan
            start_time = datetime.now()
            result = await scanner.scan_async(
                symbols=symbols,
                data_fetcher=data_fetcher,
                mode=mode
            )
            duration = (datetime.now() - start_time).total_seconds()

            # Cache the result
            self._scan_cache[cache_key] = (result, datetime.now())
            logger.debug(f"Scan cached: {mode.value} ({len(result.signals)} signals)")

        # Build output
        b = MarkdownBuilder()
        b.h1(f"{emoji} {title}").blank()

        # Show pre-filter stats if active
        if excluded_by_earnings > 0:
            b.kv("Watchlist", f"{original_count} symbols")
            b.kv("Pre-filtered", f"-{excluded_by_earnings} (earnings)")
            b.kv("Scanned", f"{len(symbols)} symbols")
        else:
            b.kv("Scanned", f"{len(symbols)} symbols")

        b.kv("With Signals", result.symbols_with_signals)
        if cache_hit:
            b.kv("Source", "cached (30 min TTL)")
        else:
            b.kv("Duration", f"{duration:.1f}s")
        b.blank()

        if result.signals:
            b.h2(f"Top {title.split()[-1] if len(title.split()) > 1 else 'Candidates'}").blank()

            if row_formatter and table_columns:
                rows = [row_formatter(signal) for signal in result.signals[:max_results]]
                b.table(table_columns, rows)
            else:
                # Default formatting
                rows = []
                for signal in result.signals[:max_results]:
                    rows.append([
                        signal.symbol,
                        f"{signal.score:.1f}",
                        f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                        signal.strategy,
                        truncate(signal.reason, 35) if signal.reason else "-"
                    ])
                b.table(["Symbol", "Score", "Price", "Strategy", "Signal"], rows)
        else:
            b.hint(no_results_msg)

        return b.build()

    def _make_scan_cache_key(
        self,
        mode: ScanMode,
        symbols: List[str],
        min_score: float,
        max_results: int
    ) -> str:
        """Generate a cache key for scan results."""
        symbols_hash = hash(tuple(sorted(symbols)))
        return f"scan:{mode.value}:{symbols_hash}:{min_score}:{max_results}"

    @mcp_endpoint(operation="pullback scan")
    async def scan_with_strategy(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Scan for pullback candidates using VIX-based strategy.

        Args:
            symbols: List of symbols to scan (uses watchlist if not provided)
            max_results: Maximum number of results
            min_score: Minimum score threshold

        Returns:
            Formatted Markdown with scan results
        """
        def format_row(signal):
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-"
            ]

        return await self._execute_scan(
            mode=ScanMode.PULLBACK_ONLY,
            title="Pullback Candidates",
            emoji="[PULLBACK]",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            table_columns=["Symbol", "Score", "Price", "Signal"],
            row_formatter=format_row,
            no_results_msg="No pullback candidates found with current criteria.",
        )

    @mcp_endpoint(operation="legacy pullback scan")
    async def scan_pullback_candidates(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Legacy alias for scan_with_strategy.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Scan results
        """
        return await self.scan_with_strategy(symbols, max_results, min_score)

    @mcp_endpoint(operation="support bounce scan")
    async def scan_bounce(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Scan for support bounce candidates.

        Looks for stocks bouncing off established support levels.
        Good for long entries (stock or calls).

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Formatted scan results
        """
        def format_row(signal):
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-"
            ]

        return await self._execute_scan(
            mode=ScanMode.BOUNCE_ONLY,
            title="Support Bounce Candidates",
            emoji="[BOUNCE]",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            table_columns=["Symbol", "Score", "Price", "Signal"],
            row_formatter=format_row,
            no_results_msg="No bounce candidates found.",
        )

    @mcp_endpoint(operation="ATH breakout scan")
    async def scan_ath_breakout(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Scan for ATH breakout candidates.

        Looks for stocks breaking to new all-time highs with volume confirmation.
        Good for momentum trades.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Formatted scan results
        """
        def format_row(signal):
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-"
            ]

        return await self._execute_scan(
            mode=ScanMode.BREAKOUT_ONLY,
            title="ATH Breakout Candidates",
            emoji="[BREAKOUT]",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            min_historical_days=260,  # Need 1 year for ATH detection
            table_columns=["Symbol", "Score", "Price", "Signal"],
            row_formatter=format_row,
            no_results_msg="No ATH breakout candidates found.",
        )

    @mcp_endpoint(operation="earnings dip scan")
    async def scan_earnings_dip(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Scan for earnings dip buy candidates.

        Looks for quality stocks that dropped 5-15% after earnings (potential overreaction).
        Contrarian play.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Formatted scan results
        """
        def format_row(signal):
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-"
            ]

        return await self._execute_scan(
            mode=ScanMode.EARNINGS_DIP,
            title="Earnings Dip Candidates",
            emoji="[EARN_DIP]",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            table_columns=["Symbol", "Score", "Price", "Signal"],
            row_formatter=format_row,
            no_results_msg="No earnings dip candidates found (requires recent earnings within 10 days).",
        )

    @mcp_endpoint(operation="multi-strategy scan")
    async def scan_multi_strategy(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Multi-strategy scan returning best signal per symbol.

        Runs all strategies (Pullback, Bounce, ATH Breakout, Earnings Dip)
        and returns the highest-scoring signal for each symbol.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Formatted scan results with strategy indication
        """
        strategy_icons = {
            "pullback": "[PB]",
            "bounce": "[BN]",
            "ath_breakout": "[ATH]",
            "earnings_dip": "[ED]",
        }

        def format_row(signal):
            icon = strategy_icons.get(signal.strategy, "[?]")
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                f"{icon} {signal.strategy}",
                truncate(signal.reason, 30) if signal.reason else "-"
            ]

        return await self._execute_scan(
            mode=ScanMode.BEST_SIGNAL,
            title="Multi-Strategy Scan",
            emoji="[MULTI]",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            min_historical_days=260,  # Need 1 year for ATH detection
            table_columns=["Symbol", "Score", "Price", "Strategy", "Signal"],
            row_formatter=format_row,
            no_results_msg="No candidates found across any strategy.",
        )
