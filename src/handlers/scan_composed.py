"""
Scan Handler (Composition-Based)
=================================

Handles all scanning operations: pullback, bounce, breakout, earnings dip,
multi-strategy, and daily recommendation picks.

This is the composition-based version of ScanHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from ..constants.trading_rules import (
    ENTRY_STABILITY_MIN,
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_STOP_LOSS_MULTIPLIER,
    SPREAD_DTE_MAX,
    SPREAD_DTE_MIN,
)
from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ScanHandler(BaseHandler):
    """
    Handler for scan-related operations.

    Methods:
    - scan_with_strategy(): Scan for pullback candidates
    - scan_pullback_candidates(): Legacy alias for scan_with_strategy
    - scan_bounce(): Scan for support bounce candidates
    - scan_ath_breakout(): Scan for ATH breakout candidates
    - scan_earnings_dip(): Scan for earnings dip candidates
    - scan_trend_continuation(): Scan for trend continuation candidates
    - scan_multi_strategy(): Multi-strategy scan returning best signal per symbol
    - daily_picks(): Generate daily trading recommendations
    """

    async def _execute_scan(
        self,
        mode: "ScanMode",
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

        Args:
            mode: ScanMode determining which strategies to enable
            title: Header title for the output
            emoji: Emoji prefix for the header
            symbols: Optional list of symbols (default: watchlist)
            max_results: Maximum number of results
            min_score: Minimum score threshold
            min_historical_days: Minimum historical data days
            table_columns: Column headers for results table
            row_formatter: Function to format each signal into a table row
            no_results_msg: Message when no candidates found
            list_type: "stable", "risk", or "all"

        Returns:
            Formatted Markdown string with scan results
        """
        from ..cache import get_earnings_fetcher
        from ..config import get_watchlist_loader
        from ..scanner.multi_strategy_scanner import ScanMode
        from ..utils.markdown_builder import MarkdownBuilder, truncate
        from ..utils.validation import validate_symbols

        await self._ensure_connected()

        # Load and validate symbols
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_symbols_by_list_type(list_type)
            list_info = f" ({list_type})" if watchlist_loader.stability_split_enabled else ""
            self._logger.info(f"Scanning {len(symbols)} symbols{list_info}")
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)
            list_info = ""

        # Apply earnings pre-filter if enabled
        original_count = len(symbols)
        excluded_by_earnings = 0
        earnings_cache_hits = 0

        scanner_config = self._ctx.config.settings.scanner

        if scanner_config.auto_earnings_prefilter:
            min_days = scanner_config.earnings_prefilter_min_days
            for_earnings_dip = mode == ScanMode.EARNINGS_DIP
            include_dip_candidates = mode in (ScanMode.ALL, ScanMode.BEST_SIGNAL)
            symbols, excluded_by_earnings, earnings_cache_hits = (
                await self._apply_earnings_prefilter(
                    symbols,
                    min_days,
                    for_earnings_dip=for_earnings_dip,
                    include_dip_candidates=include_dip_candidates,
                )
            )
            if excluded_by_earnings > 0:
                self._logger.info(
                    f"Earnings pre-filter: {excluded_by_earnings}/{original_count} symbols excluded, "
                    f"{earnings_cache_hits} cache hits"
                )

        # Check scan cache first
        cache_key = self._make_scan_cache_key(mode, symbols, min_score, max_results)
        cache_hit = False

        if cache_key in self._ctx.scan_cache:
            cached_result, cached_time = self._ctx.scan_cache[cache_key]
            age = (datetime.now() - cached_time).total_seconds()
            if age < self._ctx.scan_cache_ttl:
                result = cached_result
                cache_hit = True
                self._ctx.scan_cache_hits += 1
                duration = 0.0
                self._logger.info(f"Scan cache HIT: {mode.value} (age: {age:.0f}s)")

        if not cache_hit:
            self._ctx.scan_cache_misses += 1

            enable_pullback = mode in [ScanMode.PULLBACK_ONLY, ScanMode.ALL, ScanMode.BEST_SIGNAL]
            enable_bounce = mode in [ScanMode.BOUNCE_ONLY, ScanMode.ALL, ScanMode.BEST_SIGNAL]
            enable_breakout = mode in [ScanMode.BREAKOUT_ONLY, ScanMode.ALL, ScanMode.BEST_SIGNAL]
            enable_earnings_dip = mode in [
                ScanMode.EARNINGS_DIP,
                ScanMode.ALL,
                ScanMode.BEST_SIGNAL,
            ]
            enable_trend = mode in [ScanMode.TREND_ONLY, ScanMode.ALL, ScanMode.BEST_SIGNAL]

            scanner = self._get_multi_scanner(
                min_score=min_score,
                enable_pullback=enable_pullback,
                enable_bounce=enable_bounce,
                enable_breakout=enable_breakout,
                enable_earnings_dip=enable_earnings_dip,
                enable_trend_continuation=enable_trend,
            )
            scanner.config.max_total_results = max_results

            # Load earnings dates into scanner
            if self._ctx.earnings_fetcher is None:
                self._ctx.earnings_fetcher = get_earnings_fetcher()

            for symbol in symbols:
                cached = self._ctx.earnings_fetcher.cache.get(symbol)
                if cached and cached.earnings_date:
                    try:
                        earnings_date = date.fromisoformat(cached.earnings_date)
                        scanner.set_earnings_date(symbol, earnings_date)
                    except (ValueError, TypeError):
                        pass

            # Determine historical data requirement
            config_days = self._ctx.config.settings.performance.historical_days
            historical_days = (
                max(config_days, min_historical_days) if min_historical_days else config_days
            )

            # Pre-fetch historical data in parallel batches
            prefetch_batch_size = getattr(
                self._ctx.config.settings.performance, "prefetch_batch_size", 20
            )

            prefetch_cache: Dict[str, tuple] = {}

            async def prefetch_batch(batch_symbols: List[str]) -> None:
                tasks = [
                    self._fetch_historical_cached(sym, days=historical_days)
                    for sym in batch_symbols
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for sym, res in zip(batch_symbols, results):
                    if res is not None and not isinstance(res, Exception):
                        prefetch_cache[sym] = res

            for i in range(0, len(symbols), prefetch_batch_size):
                batch = symbols[i : i + prefetch_batch_size]
                await prefetch_batch(batch)

            self._logger.debug(f"Pre-fetched {len(prefetch_cache)}/{len(symbols)} symbols")

            async def data_fetcher(symbol: str) -> Optional[tuple]:
                if symbol in prefetch_cache:
                    return prefetch_cache[symbol]
                return await self._fetch_historical_cached(symbol, days=historical_days)

            # Execute scan
            start_time = datetime.now()
            result = await scanner.scan_async(symbols=symbols, data_fetcher=data_fetcher, mode=mode)
            duration = (datetime.now() - start_time).total_seconds()

            # Cache the result
            self._ctx.scan_cache[cache_key] = (result, datetime.now())

        # Build output
        b = MarkdownBuilder()
        b.h1(f"{emoji} {title}").blank()

        watchlist_loader = get_watchlist_loader()
        if watchlist_loader.stability_split_enabled and list_type != "all":
            list_label = "Stable List" if list_type == "stable" else "Risk List"
            b.kv("List", list_label)

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
                rows = []
                for signal in result.signals[:max_results]:
                    rows.append(
                        [
                            signal.symbol,
                            f"{signal.score:.1f}",
                            f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                            signal.strategy,
                            truncate(signal.reason, 35) if signal.reason else "-",
                        ]
                    )
                b.table(["Symbol", "Score", "Price", "Strategy", "Signal"], rows)
        else:
            b.hint(no_results_msg)

        return b.build()

    def _make_scan_cache_key(
        self, mode: Any, symbols: List[str], min_score: float, max_results: int
    ) -> str:
        """Generate a cache key for scan results."""
        symbols_hash = hash(tuple(sorted(symbols)))
        return f"scan:{mode.value}:{symbols_hash}:{min_score}:{max_results}"

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
        from ..scanner.multi_strategy_scanner import ScanMode
        from ..utils.markdown_builder import truncate

        def format_row(signal: Any) -> list[str]:
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-",
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

    async def scan_pullback_candidates(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """Legacy alias for scan_with_strategy."""
        return await self.scan_with_strategy(symbols, max_results, min_score)

    async def scan_bounce(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Scan for support bounce candidates.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Formatted scan results
        """
        from ..scanner.multi_strategy_scanner import ScanMode
        from ..utils.markdown_builder import truncate

        def format_row(signal: Any) -> list[str]:
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-",
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

    async def scan_ath_breakout(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Scan for ATH breakout candidates.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Formatted scan results
        """
        from ..scanner.multi_strategy_scanner import ScanMode
        from ..utils.markdown_builder import truncate

        def format_row(signal: Any) -> list[str]:
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-",
            ]

        return await self._execute_scan(
            mode=ScanMode.BREAKOUT_ONLY,
            title="ATH Breakout Candidates",
            emoji="[BREAKOUT]",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            min_historical_days=260,
            table_columns=["Symbol", "Score", "Price", "Signal"],
            row_formatter=format_row,
            no_results_msg="No ATH breakout candidates found.",
        )

    async def scan_earnings_dip(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
    ) -> str:
        """
        Scan for earnings dip buy candidates.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Formatted scan results
        """
        from ..scanner.multi_strategy_scanner import ScanMode
        from ..utils.markdown_builder import truncate

        def format_row(signal: Any) -> list[str]:
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-",
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

    async def scan_trend_continuation(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 5.0,
    ) -> str:
        """
        Scan for trend continuation candidates.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold

        Returns:
            Formatted scan results
        """
        from ..scanner.multi_strategy_scanner import ScanMode
        from ..utils.markdown_builder import truncate

        def format_row(signal: Any) -> list[str]:
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                truncate(signal.reason, 40) if signal.reason else "-",
            ]

        return await self._execute_scan(
            mode=ScanMode.TREND_ONLY,
            title="Trend Continuation Candidates",
            emoji="[TREND]",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            min_historical_days=250,
            table_columns=["Symbol", "Score", "Price", "Signal"],
            row_formatter=format_row,
            no_results_msg="No trend continuation candidates found.",
        )

    async def scan_multi_strategy(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 3.5,
        list_type: str = "stable",
    ) -> str:
        """
        Multi-strategy scan returning best signal per symbol.

        Args:
            symbols: List of symbols to scan
            max_results: Maximum results
            min_score: Minimum score threshold
            list_type: "stable" (default), "risk", or "all"

        Returns:
            Formatted scan results with strategy indication
        """
        from ..scanner.multi_strategy_scanner import ScanMode
        from ..utils.markdown_builder import truncate

        strategy_icons = {
            "pullback": "[PB]",
            "bounce": "[BN]",
            "ath_breakout": "[ATH]",
            "earnings_dip": "[ED]",
            "trend_continuation": "[TC]",
        }

        def format_row(signal: Any) -> list[str]:
            icon = strategy_icons.get(signal.strategy, "[?]")
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                f"{icon} {signal.strategy}",
                truncate(signal.reason, 30) if signal.reason else "-",
            ]

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
            min_historical_days=260,
            table_columns=["Symbol", "Score", "Price", "Strategy", "Signal"],
            row_formatter=format_row,
            no_results_msg="No candidates found across any strategy.",
            list_type=list_type,
        )

    async def daily_picks(
        self,
        symbols: Optional[List[str]] = None,
        max_picks: int = 5,
        min_score: float = 3.5,
        min_stability: float = ENTRY_STABILITY_MIN,
        include_strikes: bool = True,
    ) -> str:
        """
        Generate daily trading recommendations (3-5 setups).

        Applies PLAYBOOK filter order:
        1. Blacklist-Check
        2. Stability >= 70 (>= 80 in Danger Zone)
        3. Earnings > 45 days
        4. VIX < 30 (no new trades above 30)
        5. Multi-Strategy Scan
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
        from ..cache import get_earnings_fetcher
        from ..config import get_watchlist_loader
        from ..constants.trading_rules import SIZING_MAX_PER_SECTOR
        from ..services.recommendation_engine import DailyRecommendationEngine
        from ..utils.validation import validate_symbols

        await self._ensure_connected()

        # Load symbols — prefer Tier 1 (high liquidity) if tier data available
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            tier1_symbols = watchlist_loader.get_symbols_by_tier(max_tier=1)
            all_stable = watchlist_loader.get_symbols_by_list_type("stable")
            # Use tier 1 if it has enough symbols, otherwise fall back to stable list
            if len(tier1_symbols) < len(all_stable):
                symbols = tier1_symbols
                self._logger.info(
                    f"Daily picks: scanning {len(symbols)} Tier-1 symbols "
                    f"(of {len(all_stable)} stable)"
                )
            else:
                symbols = all_stable
                self._logger.info(f"Daily picks: scanning {len(symbols)} stable symbols")
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)

        # Apply earnings pre-filter
        scanner_config = self._ctx.config.settings.scanner
        excluded_by_earnings = 0
        if scanner_config.auto_earnings_prefilter:
            min_days = scanner_config.earnings_prefilter_min_days
            symbols, excluded_by_earnings, _ = await self._apply_earnings_prefilter(
                symbols,
                min_days,
                for_earnings_dip=False,
                include_dip_candidates=True,
            )

        # Get current VIX
        vix_level = None
        try:
            vix_level = await self._get_vix()
        except Exception as e:
            self._logger.warning(f"Could not fetch VIX: {e}")

        # Configure recommendation engine
        engine_config = {
            "min_stability_score": min_stability,
            "min_signal_score": min_score,
            "max_picks": max_picks,
            "enable_strike_recommendations": include_strikes,
            "enable_sector_diversification": True,
            "enable_blacklist_filter": True,
            "enable_vix_regime_filter": True,
            "max_per_sector": SIZING_MAX_PER_SECTOR,
        }

        scanner = self._get_multi_scanner(
            min_score=min_score,
            enable_pullback=True,
            enable_bounce=True,
            enable_breakout=True,
            enable_earnings_dip=True,
            enable_trend_continuation=True,
        )

        engine = DailyRecommendationEngine(
            scanner=scanner,
            config=engine_config,
        )

        if vix_level:
            engine.set_vix(vix_level)

        # Pre-fetch historical data
        historical_days = max(self._ctx.config.settings.performance.historical_days, 260)
        prefetch_batch_size = getattr(
            self._ctx.config.settings.performance, "prefetch_batch_size", 20
        )
        prefetch_cache: Dict[str, tuple] = {}

        async def prefetch_batch(batch_symbols: List[str]) -> None:
            tasks = [
                self._fetch_historical_cached(sym, days=historical_days) for sym in batch_symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, res in zip(batch_symbols, results):
                if res is not None and not isinstance(res, Exception):
                    prefetch_cache[sym] = res

        for i in range(0, len(symbols), prefetch_batch_size):
            batch = symbols[i : i + prefetch_batch_size]
            await prefetch_batch(batch)

        async def data_fetcher(symbol: str) -> Optional[tuple]:
            if symbol in prefetch_cache:
                return prefetch_cache[symbol]
            return await self._fetch_historical_cached(symbol, days=historical_days)

        async def options_fetcher(symbol: str) -> list[Any]:
            try:
                return await self._get_options_chain_with_fallback(
                    symbol, dte_min=SPREAD_DTE_MIN, dte_max=SPREAD_DTE_MAX, right="P"
                )
            except Exception as e:
                self._logger.warning(f"Could not fetch options for {symbol}: {e}")
                return []

        # Generate picks
        start_time = datetime.now()
        engine_max_picks = max_picks * 3
        result = await engine.get_daily_picks(
            symbols=symbols,
            data_fetcher=data_fetcher,
            max_picks=engine_max_picks,
            vix=vix_level,
            options_fetcher=options_fetcher if include_strikes else None,
        )

        duration = (datetime.now() - start_time).total_seconds()

        # Shadow Trade Tracker integration
        shadow_results = await self._shadow_log_picks(result)

        # Format output using the mixin's formatter (imported inline)
        from ..services.recommendation_engine import DailyPick
        from ..utils.markdown_builder import MarkdownBuilder, truncate

        b = MarkdownBuilder()
        today_str = date.today().isoformat()
        b.h1(f"Daily Picks -- {today_str}").blank()

        if result.vix_level:
            regime_display = {
                "low_vol": "Normal",
                "normal": "Normal",
                "danger_zone": "Danger Zone",
                "elevated": "Elevated",
                "high_vol": "High Volatility",
                "unknown": "Unknown",
            }
            regime_str = regime_display.get(result.market_regime.value, result.market_regime.value)
            b.kv("Regime", f"{regime_str} (VIX {result.vix_level:.2f})")

        b.kv("Scanned", f"{result.symbols_scanned} symbols | Duration: {duration:.1f}s")

        # Shadow tracker summary
        if shadow_results:
            logged = shadow_results.get("logged", 0)
            rejected = shadow_results.get("rejected", 0)
            skipped = shadow_results.get("skipped", 0)
            total = logged + rejected + skipped
            if total > 0:
                b.kv(
                    "Shadow",
                    f"{logged} logged | {rejected} rejected | {skipped} skipped",
                )

        b.blank()

        if result.warnings:
            for warning in result.warnings:
                b.bullet(warning)
            b.blank()

        if result.picks:
            for pick in result.picks:
                self._format_single_pick_v2(b, pick)
        else:
            b.hint("No candidates found matching criteria.")

        return b.build()

    def _format_single_pick_v2(self, b: Any, pick: Any) -> None:
        """Format a single pick in v2 format with real chain data."""
        from ..constants.trading_rules import SPREAD_MIN_CREDIT_PCT
        from ..utils.markdown_builder import truncate

        strategy_display = {
            "pullback": "Pullback",
            "bounce": "Bounce",
            "ath_breakout": "ATH Breakout",
            "earnings_dip": "Earnings Dip",
        }
        strategy_str = strategy_display.get(pick.strategy, pick.strategy.replace("_", " ").title())

        tier_badge = ""
        if getattr(pick, "liquidity_tier", None) is not None:
            tier_badge = f" [T{pick.liquidity_tier}]"

        eqs_str = ""
        if pick.entry_quality and hasattr(pick.entry_quality, "eqs_total"):
            eqs_str = f" | EQS {pick.entry_quality.eqs_total:.0f}"

        # Enhanced score display
        score_display = f"Score {pick.score:.1f}"
        if pick.enhanced_score is not None:
            score_display = f"Enhanced {pick.enhanced_score:.1f} (base {pick.score:.1f})"

        b.h2(
            f"#{pick.rank} -- {pick.symbol}{tier_badge} | {strategy_str} | {score_display}{eqs_str}"
        )

        # Bonus breakdown line
        if hasattr(pick, "enhanced_score_result") and pick.enhanced_score_result is not None:
            b.text(f"**Bonus:** {pick.enhanced_score_result.bonus_breakdown_str()}")

        b.blank()

        sv = pick.spread_validation
        if sv and sv.tradeable:
            short = sv.short_leg
            long = sv.long_leg
            leg_rows = [
                [
                    f"${short.strike:.0f}",
                    f"{short.delta:.2f}",
                    f"{short.iv * 100:.1f}%" if short.iv else "-",
                    f"{short.open_interest:,}",
                    f"${short.bid:.2f}/${short.ask:.2f}",
                ],
                [
                    f"${long.strike:.0f}",
                    f"{long.delta:.2f}",
                    f"{long.iv * 100:.1f}%" if long.iv else "-",
                    f"{long.open_interest:,}",
                    f"${long.bid:.2f}/${long.ask:.2f}",
                ],
            ]
            b.table(["Strike", "Delta", "IV", "OI", "Bid/Ask"], leg_rows)
            b.blank()

            b.text(
                f"**Spread:** ${sv.spread_width:.0f} breit | **Expiry:** {sv.expiration} ({sv.dte} DTE)"
            )
            credit_check = (
                "OK" if sv.credit_pct and sv.credit_pct >= SPREAD_MIN_CREDIT_PCT else "LOW"
            )
            b.text(
                f"**Credit:** ${sv.credit_bid:.2f} (Bid) -- ${sv.credit_mid:.2f} (Mid) | **Credit/Breite:** {sv.credit_pct:.1f}% {credit_check}"
            )

            max_loss = sv.max_loss_per_contract if sv.max_loss_per_contract else 0
            profit_target_50 = (
                sv.credit_bid * (EXIT_PROFIT_PCT_NORMAL / 100) if sv.credit_bid else 0
            )
            stop_loss_200 = sv.credit_bid * EXIT_STOP_LOSS_MULTIPLIER if sv.credit_bid else 0
            b.text(
                f"**Max Loss:** ${max_loss:.0f}/Kontrakt | **50% Target:** ${profit_target_50:.2f} | **200% Stop:** ${stop_loss_200:.2f}"
            )
            b.blank()
        elif pick.suggested_strikes:
            s = pick.suggested_strikes
            b.text(
                f"**Strikes:** Short ${s.short_strike:.0f} / Long ${s.long_strike:.0f} | Width ${s.spread_width:.0f}"
            )
            if s.estimated_credit:
                b.text(f"**Est. Credit:** ${s.estimated_credit:.2f}")
            if s.expiry:
                dte_str = f" ({s.dte} DTE)" if s.dte is not None else ""
                b.text(f"**Expiry:** {s.expiry}{dte_str}")
            b.blank()

        # Entry Quality line
        eq = pick.entry_quality
        if eq and hasattr(eq, "iv_rank"):
            parts = []
            if eq.iv_rank is not None:
                parts.append(f"IV Rank {eq.iv_rank:.0f}%")
            if eq.iv_percentile is not None:
                parts.append(f"IV Pctl {eq.iv_percentile:.0f}%")
            if eq.rsi is not None:
                rsi_label = ""
                if eq.rsi < 35:
                    rsi_label = " (oversold)"
                elif eq.rsi > 65:
                    rsi_label = " (overbought)"
                parts.append(f"RSI {eq.rsi:.0f}{rsi_label}")
            if eq.pullback_pct is not None:
                parts.append(f"Pullback {eq.pullback_pct:.1f}%")
            if sv and sv.spread_theta:
                parts.append(f"Theta ${sv.spread_theta:.3f}/d")
            if parts:
                b.text(f"**Entry:** {' | '.join(parts)}")
                b.blank()

        # Checklist
        checklist_parts = []
        if pick.stability_score:
            checklist_parts.append(f"Stab({pick.stability_score:.0f})")
        if pick.current_price:
            checklist_parts.append(f"Preis(${pick.current_price:.0f})")
        if sv and sv.dte:
            checklist_parts.append(f"DTE({sv.dte})")
        if sv and sv.credit_pct:
            checklist_parts.append(f"Credit({sv.credit_pct:.1f}%)")
        if pick.sector:
            checklist_parts.append(pick.sector[:12])
        if checklist_parts:
            b.text(f"**Checks:** {' | '.join(checklist_parts)}")

        if pick.reason:
            b.text(f"**Signal:** {truncate(pick.reason, 120)}")

        if pick.warnings:
            for warning in pick.warnings:
                b.bullet(f"Warning: {warning}")

        # Shadow trade status (attached by _shadow_log_picks)
        shadow_status = getattr(pick, "_shadow_status", None)
        if shadow_status:
            b.text(shadow_status)

        b.blank()

    # --- Shadow Trade Tracker ---

    async def _shadow_log_picks(self, result: Any) -> Dict[str, int]:
        """Log daily picks through the tradability gate into shadow tracker.

        For each pick with strike data, runs check_tradability() against the
        live options chain. Tradeable picks are logged as shadow trades,
        non-tradeable ones as rejections. Attaches _shadow_status to each pick
        for display in the output.

        Returns dict with counts: {logged, rejected, skipped}.
        """
        from ..shadow_tracker import ShadowTracker, check_tradability

        counts = {"logged": 0, "rejected": 0, "skipped": 0}

        # Check if shadow tracker is enabled
        try:
            settings = ShadowTracker._load_settings_static()
            if not settings.get("enabled", True):
                return counts
            if not settings.get("auto_log_daily_picks", True):
                return counts
            min_score = settings.get("auto_log_min_score", 8.0)
        except Exception:
            min_score = 8.0

        if not result.picks:
            return counts

        # Get tradier provider for tradability checks
        provider = None
        if self._ctx.tradier_connected and self._ctx.tradier_provider:
            provider = self._ctx.tradier_provider

        try:
            tracker = ShadowTracker()
        except Exception as e:
            self._logger.warning("Shadow tracker init failed: %s", e)
            return counts

        try:
            for pick in result.picks:
                # Need strike data to check tradability
                sv = pick.spread_validation
                ss = pick.suggested_strikes

                # Determine strikes and expiration
                if sv and sv.tradeable and sv.short_leg and sv.long_leg:
                    short_strike = sv.short_leg.strike
                    long_strike = sv.long_leg.strike
                    spread_width = sv.spread_width or (short_strike - long_strike)
                    expiration = sv.expiration
                    dte = sv.dte or 0
                    est_credit = sv.credit_bid or 0.0
                elif ss:
                    short_strike = ss.short_strike
                    long_strike = ss.long_strike
                    spread_width = ss.spread_width
                    expiration = ss.expiry
                    dte = ss.dte or 0
                    est_credit = ss.estimated_credit or 0.0
                else:
                    pick._shadow_status = ""
                    counts["skipped"] += 1
                    continue

                if not expiration:
                    pick._shadow_status = ""
                    counts["skipped"] += 1
                    continue

                # Score filter
                effective_score = pick.enhanced_score or pick.score
                if effective_score < min_score:
                    pick._shadow_status = ""
                    counts["skipped"] += 1
                    continue

                # Tradability check
                if provider:
                    try:
                        tradeable, reason, details = await check_tradability(
                            provider,
                            pick.symbol,
                            expiration,
                            short_strike,
                            long_strike,
                        )
                    except Exception as e:
                        self._logger.debug("Tradability check failed for %s: %s", pick.symbol, e)
                        tradeable, reason, details = False, "no_chain", {"error": str(e)}
                else:
                    # No provider available — skip tradability, log with estimated data
                    tradeable = True
                    reason = "tradeable"
                    details = {}

                # Derive liquidity tier from suggested_strikes quality
                liquidity_tier = None
                if ss and ss.liquidity_quality:
                    tier_map = {"excellent": 1, "good": 1, "fair": 2, "poor": 3}
                    liquidity_tier = tier_map.get(ss.liquidity_quality, 2)

                # Common kwargs
                vix_at_log = result.vix_level
                regime_at_log = result.market_regime.value if result.market_regime else None

                if tradeable:
                    # Build trade context from signal details
                    trade_context_json = None
                    signal = getattr(pick, "_signal", None)
                    if signal:
                        try:
                            trade_ctx = {
                                "signal": {
                                    "score": signal.score,
                                    "strength": signal.strength.value if hasattr(signal.strength, "value") else str(signal.strength),
                                    "reason": signal.reason,
                                    "details": signal.details,
                                },
                                "recommendation": {
                                    "quality": ss.quality if ss and hasattr(ss, "quality") else None,
                                    "risk_reward_ratio": ss.risk_reward_ratio if ss and hasattr(ss, "risk_reward_ratio") else None,
                                    "prob_profit": ss.prob_profit if ss and hasattr(ss, "prob_profit") else None,
                                    "data_source": ss.data_source if ss and hasattr(ss, "data_source") else None,
                                },
                                "scanner": {
                                    "win_rate": pick.historical_win_rate,
                                    "stability": pick.stability_score,
                                    "sector": pick.sector,
                                    "rank": pick.rank,
                                    "speed_score": pick.speed_score,
                                    "reliability_grade": pick.reliability_grade,
                                },
                            }
                            trade_context_json = json.dumps(trade_ctx, default=str)
                        except Exception:
                            pass

                    # Use chain data from tradability check if available
                    trade_id = tracker.log_trade(
                        source="daily_picks",
                        symbol=pick.symbol,
                        strategy=pick.strategy,
                        score=pick.score,
                        enhanced_score=pick.enhanced_score,
                        liquidity_tier=liquidity_tier,
                        short_strike=short_strike,
                        long_strike=long_strike,
                        spread_width=spread_width,
                        est_credit=details.get("net_credit", est_credit),
                        expiration=expiration,
                        dte=dte,
                        short_bid=details.get("short_bid"),
                        short_ask=details.get("short_ask"),
                        short_oi=details.get("short_oi"),
                        long_bid=details.get("long_bid"),
                        long_ask=details.get("long_ask"),
                        long_oi=details.get("long_oi"),
                        price_at_log=pick.current_price,
                        vix_at_log=vix_at_log,
                        regime_at_log=regime_at_log,
                        stability_at_log=pick.stability_score,
                        trade_context=trade_context_json,
                    )
                    if trade_id:
                        credit_str = f"${details.get('net_credit', est_credit):.2f}"
                        oi_short = details.get("short_oi", "?")
                        oi_long = details.get("long_oi", "?")
                        oi_str = f"{oi_short:,} / {oi_long:,}" if isinstance(oi_short, int) else "?"
                        pick._shadow_status = (
                            f"TRADEABLE — Shadow Trade geloggt "
                            f"(Credit {credit_str} | OI: {oi_str})"
                        )
                        counts["logged"] += 1
                    else:
                        # Duplicate
                        pick._shadow_status = "Shadow Trade bereits geloggt (Duplikat)"
                        counts["skipped"] += 1
                else:
                    # Log rejection
                    import json

                    tracker.log_rejection(
                        source="daily_picks",
                        symbol=pick.symbol,
                        strategy=pick.strategy,
                        score=pick.score,
                        liquidity_tier=liquidity_tier,
                        short_strike=short_strike,
                        long_strike=long_strike,
                        rejection_reason=reason,
                        actual_credit=details.get("net_credit"),
                        short_oi=details.get("short_oi"),
                        details=json.dumps(details),
                    )
                    pick._shadow_status = f"NOT TRADEABLE — {reason}"
                    counts["rejected"] += 1

        except Exception as e:
            self._logger.warning("Shadow tracker error: %s", e)
        finally:
            tracker.close()

        return counts

    # --- Shared helper methods (delegating to server context) ---

    async def _fetch_historical_cached(self, symbol: str, days: Optional[int] = None):
        """Fetch historical data with caching.

        Priority: in-memory cache → Tradier.
        """
        from ..cache.historical_cache import CacheStatus

        if days is None:
            days = self._ctx.config.settings.performance.historical_days

        # 1. Check in-memory cache
        if self._ctx.historical_cache:
            cache_result = self._ctx.historical_cache.get(symbol, days)
            if cache_result.status == CacheStatus.HIT:
                return cache_result.data

        # 2. Fetch from Tradier
        await self._ensure_connected()
        if self._ctx.tradier_connected and self._ctx.tradier_provider:
            try:
                data = await self._ctx.tradier_provider.get_historical_for_scanner(
                    symbol, days=days
                )
                if data:
                    if self._ctx.historical_cache:
                        self._ctx.historical_cache.set(symbol, data, days=days)
                    return data
            except (ConnectionError, TimeoutError, ValueError) as e:
                self._logger.debug(f"Tradier historical failed for {symbol}: {e}")

        return None

    async def _apply_earnings_prefilter(
        self,
        symbols,
        min_days,
        for_earnings_dip=False,
        include_dip_candidates=False,
    ):
        """Apply earnings pre-filter to symbols list."""
        from ..cache import get_earnings_fetcher

        if self._ctx.earnings_fetcher is None:
            self._ctx.earnings_fetcher = get_earnings_fetcher()

        safe = []
        excluded = 0
        cache_hits = 0

        for symbol in symbols:
            try:
                cached = self._ctx.earnings_fetcher.cache.get(symbol)
                if cached:
                    cache_hits += 1
                    if cached.days_to_earnings is not None:
                        if cached.days_to_earnings < 0:
                            # Past earnings date = safe (next earnings ~90d away)
                            safe.append(symbol)
                        elif for_earnings_dip:
                            if cached.days_to_earnings <= 10:
                                safe.append(symbol)
                            else:
                                excluded += 1
                        else:
                            if cached.days_to_earnings >= min_days:
                                safe.append(symbol)
                            elif include_dip_candidates and cached.days_to_earnings <= 10:
                                # Keep recent-earnings symbols for dip strategy in multi-mode
                                safe.append(symbol)
                            else:
                                excluded += 1
                    else:
                        safe.append(symbol)
                else:
                    safe.append(symbol)
            except (AttributeError, ValueError) as e:
                logger.debug("Earnings filter error for %s: %s", symbol, e)
                safe.append(symbol)

        return safe, excluded, cache_hits

    def _get_multi_scanner(
        self,
        min_score=3.5,
        enable_pullback=True,
        enable_bounce=True,
        enable_breakout=True,
        enable_earnings_dip=True,
        enable_trend_continuation=True,
        exclude_earnings_within_days=None,
    ):
        """Get a configured MultiStrategyScanner instance."""
        from ..scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig

        config = ScanConfig(
            min_score=min_score,
            enable_pullback=enable_pullback,
            enable_bounce=enable_bounce,
            enable_ath_breakout=enable_breakout,
            enable_earnings_dip=enable_earnings_dip,
            enable_trend_continuation=enable_trend_continuation,
        )
        if exclude_earnings_within_days is not None:
            config.exclude_earnings_within_days = exclude_earnings_within_days
        return MultiStrategyScanner(config=config)

    # _get_vix() inherited from BaseHandler

    async def _get_options_chain_with_fallback(
        self, symbol, dte_min=SPREAD_DTE_MIN, dte_max=SPREAD_DTE_MAX, right="P"
    ):
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
