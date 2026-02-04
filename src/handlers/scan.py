"""
Scan Handler Module
===================

Handles all scanning operations: pullback, bounce, breakout, earnings dip, multi-strategy.
Includes Daily Recommendation Engine for top trading candidates.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Callable

from ..scanner.multi_strategy_scanner import ScanMode
from ..services.recommendation_engine import (
    DailyRecommendationEngine,
    DailyPick,
    DailyRecommendationResult,
)
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
        list_type: str = "stable",
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
            list_type: "stable", "risk", or "all" - determines which symbols to scan

        Returns:
            Formatted Markdown string with scan results
        """
        await self._ensure_connected()

        # Load and validate symbols
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            # Use stability-based list selection
            symbols = watchlist_loader.get_symbols_by_list_type(list_type)
            list_info = f" ({list_type})" if watchlist_loader.stability_split_enabled else ""
            logger.info(f"Scanning {len(symbols)} symbols{list_info}")
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)
            list_info = ""

        # Apply earnings pre-filter if enabled
        original_count = len(symbols)
        excluded_by_earnings = 0
        earnings_cache_hits = 0

        scanner_config = self._config.settings.scanner
        # Note: Previously skipped prefilter for ALL/BEST_SIGNAL modes, but earnings
        # filter should ALWAYS be applied to avoid trades around earnings events.
        # The scanner's internal earnings check is a secondary safety layer.

        if scanner_config.auto_earnings_prefilter:
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

        # Show list type info if stability split is active
        watchlist_loader = get_watchlist_loader()
        if watchlist_loader.stability_split_enabled and list_type != "all":
            list_label = "Stable List" if list_type == "stable" else "Risk List"
            b.kv("List", list_label)

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
        list_type: str = "stable",
    ) -> str:
        """
        Multi-strategy scan returning best signal per symbol.

        Runs all strategies (Pullback, Bounce, ATH Breakout, Earnings Dip)
        and returns the highest-scoring signal for each symbol.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold
            list_type: "stable" (default), "risk", or "all"
                       - stable: Only symbols with Stability Score >= 60
                       - risk: Only symbols with Stability Score < 60 or unknown
                       - all: All symbols from watchlist

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

        # Adjust title based on list type
        title_suffix = ""
        if list_type == "risk":
            title_suffix = " (Risk List)"
        elif list_type == "all":
            title_suffix = " (Full Watchlist)"

        return await self._execute_scan(
            mode=ScanMode.BEST_SIGNAL,
            title=f"Multi-Strategy Scan{title_suffix}",
            emoji="[MULTI]",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            min_historical_days=260,  # Need 1 year for ATH detection
            table_columns=["Symbol", "Score", "Price", "Strategy", "Signal"],
            row_formatter=format_row,
            no_results_msg="No candidates found across any strategy.",
            list_type=list_type,
        )

    @mcp_endpoint(operation="daily picks")
    async def daily_picks(
        self,
        symbols: Optional[List[str]] = None,
        max_picks: int = 5,
        min_score: float = 3.5,
        min_stability: float = 70.0,
        include_strikes: bool = True,
    ) -> str:
        """
        Generate daily trading recommendations (3-5 setups).

        Applies PLAYBOOK filter order:
        1. Blacklist-Check
        2. Stability >= 70 (>= 80 in Danger Zone)
        3. Earnings > 60 days
        4. VIX < 30 (no new trades above 30)
        5. Multi-Strategy Scan (Pullback, Bounce, ATH Breakout, Earnings Dip)
        6. Sector Diversification (max 2 per sector)
        7. Combined Ranking (70% Signal Score + 30% Stability)
        8. Strike Recommendations for Bull-Put-Spreads

        Args:
            symbols: List of symbols to scan (uses watchlist if not provided)
            max_picks: Maximum number of recommendations (default: 5)
            min_score: Minimum signal score for ranking (default: 3.5)
            min_stability: Minimum stability score (default: 70.0)
            include_strikes: Include strike recommendations (default: True)

        Returns:
            Formatted Markdown with daily picks and strike recommendations
        """
        await self._ensure_connected()

        # Load symbols
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_symbols_by_list_type("stable")
            logger.info(f"Daily picks: scanning {len(symbols)} stable symbols")
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)

        # Apply earnings pre-filter (same as _execute_scan pipeline)
        scanner_config = self._config.settings.scanner
        excluded_by_earnings = 0
        if scanner_config.auto_earnings_prefilter:
            min_days = scanner_config.earnings_prefilter_min_days
            symbols, excluded_by_earnings, _ = await self._apply_earnings_prefilter(
                symbols, min_days, for_earnings_dip=False
            )
            if excluded_by_earnings > 0:
                logger.info(
                    f"Daily picks earnings pre-filter: {excluded_by_earnings} symbols excluded "
                    f"(earnings within {min_days} days)"
                )

        # Get current VIX via VixHandlerMixin.get_vix()
        vix_level = None
        try:
            vix_level = await self.get_vix()
        except Exception as e:
            logger.warning(f"Could not fetch VIX: {e}")

        # Configure recommendation engine (PLAYBOOK-aligned defaults)
        from ..constants.trading_rules import SIZING_MAX_PER_SECTOR
        engine_config = {
            'min_stability_score': min_stability,
            'min_signal_score': min_score,
            'max_picks': max_picks,
            'enable_strike_recommendations': include_strikes,
            'enable_sector_diversification': True,
            'enable_blacklist_filter': True,
            'enable_vix_regime_filter': True,
            'max_per_sector': SIZING_MAX_PER_SECTOR,  # PLAYBOOK §5: 2
        }

        # Use existing scanner from handler
        scanner = self._get_multi_scanner(
            min_score=min_score,
            enable_pullback=True,
            enable_bounce=True,
            enable_breakout=True,
            enable_earnings_dip=True,
        )

        engine = DailyRecommendationEngine(
            scanner=scanner,
            config=engine_config,
        )

        if vix_level:
            engine.set_vix(vix_level)

        # Determine historical data requirement
        historical_days = max(
            self._config.settings.performance.historical_days,
            260  # Need 1 year for ATH detection
        )

        # Pre-fetch historical data
        prefetch_batch_size = getattr(
            self._config.settings.performance, 'prefetch_batch_size', 20
        )
        prefetch_cache: Dict[str, tuple] = {}

        async def prefetch_batch(batch_symbols: List[str]) -> None:
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

        # Options fetcher for liquidity assessment
        async def options_fetcher(symbol: str):
            """Fetch options chain for liquidity check."""
            try:
                provider = self._get_provider()
                await self._rate_limiter.acquire()
                options = await provider.get_option_chain(
                    symbol, dte_min=60, dte_max=90, right="P"
                )
                self._rate_limiter.record_success()
                return options or []
            except Exception as e:
                logger.warning(f"Could not fetch options for {symbol}: {e}")
                return []

        # Generate picks
        start_time = datetime.now()
        result = await engine.get_daily_picks(
            symbols=symbols,
            data_fetcher=data_fetcher,
            max_picks=max_picks,
            vix=vix_level,
            options_fetcher=options_fetcher if include_strikes else None,
        )
        duration = (datetime.now() - start_time).total_seconds()

        # Format output
        return self._format_daily_picks_output(result, duration, excluded_by_earnings)

    def _format_daily_picks_output(
        self,
        result: DailyRecommendationResult,
        duration: float,
        excluded_by_earnings: int = 0,
    ) -> str:
        """Format daily picks result as Markdown."""
        b = MarkdownBuilder()

        # Header
        b.h1("📊 Daily Picks - Top 20 Candidates").blank()

        # Market Overview
        if result.vix_level:
            regime_display = {
                'low_vol': '🟢 Low Volatility',
                'normal': '🟢 Normal',
                'danger_zone': '🟡 Danger Zone',
                'elevated': '🟠 Elevated',
                'high_vol': '🔴 High Volatility',
                'unknown': '⚪ Unknown',
            }
            regime_str = regime_display.get(result.market_regime.value, result.market_regime.value)
            b.kv("VIX", f"{result.vix_level:.2f}")
            b.kv("Regime", regime_str)
            b.blank()

        # Warnings
        if result.warnings:
            b.h2("⚠️ Warnings").blank()
            for warning in result.warnings:
                b.bullet(warning)
            b.blank()

        # Statistics
        b.kv("Scanned", f"{result.symbols_scanned} symbols")
        if excluded_by_earnings > 0:
            b.kv("Earnings Pre-filter", f"-{excluded_by_earnings} excluded")
        b.kv("Signals Found", result.signals_found)
        b.kv("After Stability Filter", result.after_stability_filter)
        if result.after_liquidity_filter > 0:
            b.kv("After Liquidity Filter", result.after_liquidity_filter)
        b.kv("Duration", f"{duration:.1f}s")
        b.blank()

        # Picks Table
        if result.picks:
            b.h2(f"Top {len(result.picks)} Recommendations").blank()

            # Summary table
            rows = []
            for pick in result.picks:
                grade_badge = f"[{pick.reliability_grade}]" if pick.reliability_grade else ""
                stability_str = f"{pick.stability_score:.0f}" if pick.stability_score else "?"

                # Strategy icon
                strategy_icons = {
                    "pullback": "PB",
                    "bounce": "BN",
                    "ath_breakout": "ATH",
                    "earnings_dip": "ED",
                }
                strategy_str = strategy_icons.get(pick.strategy, pick.strategy[:3].upper())

                speed_str = f"{pick.speed_score:.1f}" if pick.speed_score is not None else "-"

                rows.append([
                    f"{pick.rank}",
                    pick.symbol,
                    f"{pick.score:.1f}",
                    stability_str,
                    speed_str,
                    strategy_str,
                    f"${pick.current_price:.2f}" if pick.current_price else "N/A",
                    pick.sector[:12] if pick.sector else "-",
                    grade_badge,
                ])

            b.table(
                ["#", "Symbol", "Score", "Stab", "Speed", "Type", "Price", "Sector", "Grade"],
                rows
            )
            b.blank()

            # Strike Recommendations Section
            picks_with_strikes = [p for p in result.picks if p.suggested_strikes]
            if picks_with_strikes:
                b.h2("💰 Strike Recommendations").blank()

                strike_rows = []
                for pick in picks_with_strikes[:10]:  # Top 10 with strikes
                    s = pick.suggested_strikes
                    credit_str = f"${s.estimated_credit:.2f}" if s.estimated_credit else "-"
                    pop_str = f"{s.prob_profit:.0f}%" if s.prob_profit else "-"

                    # C/R% (Credit/Risk ratio)
                    cr_str = "-"
                    if s.estimated_credit and s.spread_width and s.spread_width > 0:
                        cr_pct = (s.estimated_credit / s.spread_width) * 100
                        if cr_pct >= 20:
                            cr_badge = "Exzellent"
                        elif cr_pct >= 15:
                            cr_badge = "Gut"
                        elif cr_pct >= 10:
                            cr_badge = "OK"
                        else:
                            cr_badge = "Schlecht"
                        cr_str = f"{cr_pct:.0f}% [{cr_badge}]"

                    # Expiry / DTE columns
                    expiry_str = s.expiry[-5:] if s.expiry else "-"  # "03-20" from "2026-03-20"
                    dte_str = str(s.dte) if s.dte is not None else "-"

                    # Liquidity columns
                    oi_str = f"{s.short_oi:,}" if s.short_oi else "-"
                    sprd_str = f"{s.short_spread_pct:.0f}%" if s.short_spread_pct is not None else "-"

                    # Status column
                    status_badges = {
                        "READY": "READY",
                        "WARNING": "WARN",
                        "NOT_TRADEABLE": "N/T",
                        "unknown": "-",
                    }
                    status_str = status_badges.get(s.tradeable_status, "-")

                    strike_rows.append([
                        pick.symbol,
                        f"${s.short_strike:.0f}",
                        f"${s.long_strike:.0f}",
                        f"${s.spread_width:.0f}",
                        credit_str,
                        cr_str,
                        pop_str,
                        expiry_str,
                        dte_str,
                        oi_str,
                        sprd_str,
                        status_str,
                    ])

                b.table(
                    ["Symbol", "Short", "Long", "Width", "Credit", "C/R%", "P(Profit)", "Expiry", "DTE", "OI", "Sprd%", "Status"],
                    strike_rows
                )
                b.blank()

            # Detailed view for top 5
            b.h2("📋 Top 5 Details").blank()
            for pick in result.picks[:5]:
                self._format_single_pick_detail(b, pick)

        else:
            b.hint("No candidates found matching criteria.")

        return b.build()

    def _format_single_pick_detail(self, b: MarkdownBuilder, pick: DailyPick) -> None:
        """Format a single pick with details."""
        # Header with grade
        grade_str = f" [{pick.reliability_grade}]" if pick.reliability_grade else ""
        b.h3(f"{pick.rank}. {pick.symbol} - {pick.strategy.replace('_', ' ').title()}{grade_str}")

        # Key metrics
        b.kv("Price", f"${pick.current_price:.2f}" if pick.current_price else "N/A")
        b.kv("Score", f"{pick.score:.1f}/10")
        b.kv("Stability", f"{pick.stability_score:.0f}/100" if pick.stability_score else "Unknown")
        b.kv("Speed", f"{pick.speed_score:.1f}/10" if pick.speed_score is not None else "-")

        if pick.historical_win_rate:
            b.kv("Hist. Win Rate", f"{pick.historical_win_rate:.0f}%")

        if pick.sector:
            b.kv("Sector", pick.sector)

        # Strike recommendation
        if pick.suggested_strikes:
            s = pick.suggested_strikes
            b.blank()
            b.text("**Strike Recommendation:**")
            # Expiry + DTE
            if s.expiry:
                dte_str = f" ({s.dte} DTE)" if s.dte is not None else ""
                b.bullet(f"Expiry: {s.expiry}{dte_str}")
            if s.dte_warning:
                b.bullet(f"⚠️ {s.dte_warning}")
            b.bullet(
                f"Short Put: ${s.short_strike:.2f}"
                + (f" (OI: {s.short_oi:,})" if s.short_oi else "")
            )
            b.bullet(
                f"Long Put: ${s.long_strike:.2f}"
                + (f" (OI: {s.long_oi:,})" if s.long_oi else "")
            )
            b.bullet(f"Spread Width: ${s.spread_width:.2f}")
            if s.estimated_credit:
                b.bullet(f"Est. Credit: ${s.estimated_credit:.2f}")
                # C/R% display
                if s.spread_width and s.spread_width > 0:
                    cr_pct = (s.estimated_credit / s.spread_width) * 100
                    b.bullet(f"C/R%: {cr_pct:.0f}%")
                # Fee warning
                credit_per_contract = s.estimated_credit * 100
                if credit_per_contract < 40:
                    fee_pct = (2.60 / credit_per_contract) * 100 if credit_per_contract > 0 else 999
                    b.bullet(
                        f"⚠️ Gebührenwarnung: Credit ${credit_per_contract:.0f} — "
                        f"IBKR-Gebühren ($2.60 RT) = {fee_pct:.1f}% des Ertrags"
                    )
            if s.prob_profit:
                b.bullet(f"P(Profit): {s.prob_profit:.0f}%")
            # Tradeable status
            if s.tradeable_status and s.tradeable_status != "unknown":
                b.bullet(f"Status: {s.tradeable_status}")

        # Reason
        if pick.reason:
            b.blank()
            b.text(f"**Signal:** {truncate(pick.reason, 80)}")

        # Warnings
        if pick.warnings:
            b.blank()
            for warning in pick.warnings:
                b.bullet(f"⚠️ {warning}")

        b.blank()
