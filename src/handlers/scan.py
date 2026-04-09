"""
Scan Handler Module
===================

Handles all scanning operations: pullback, bounce, multi-strategy.
Includes Daily Recommendation Engine for top trading candidates.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from ..cache import get_earnings_fetcher
from ..config import get_watchlist_loader
from ..constants.trading_rules import (
    ENTRY_STABILITY_MIN,
    EXIT_PROFIT_PCT_NORMAL,
    EXIT_STOP_LOSS_MULTIPLIER,
    SPREAD_DTE_MAX,
    SPREAD_DTE_MIN,
)
from ..scanner.multi_strategy_scanner import ScanMode
from ..services.recommendation_engine import (
    DailyPick,
    DailyRecommendationEngine,
    DailyRecommendationResult,
)
from ..utils.error_handler import mcp_endpoint
from ..utils.markdown_builder import MarkdownBuilder, truncate
from ..utils.validation import is_etf, validate_symbols
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
        scan_multi_strategy.

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
            symbols, excluded_by_earnings, earnings_cache_hits = (
                await self._apply_earnings_prefilter(
                    symbols,
                    min_days,
                )
            )
            if excluded_by_earnings > 0:
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

            scanner = self._get_multi_scanner(
                min_score=min_score,
                enable_pullback=enable_pullback,
                enable_bounce=enable_bounce,
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
            historical_days = (
                max(config_days, min_historical_days) if min_historical_days else config_days
            )

            # Pre-fetch historical data in parallel batches
            prefetch_batch_size = getattr(
                self._config.settings.performance, "prefetch_batch_size", 20
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
                batch = symbols[i : i + prefetch_batch_size]
                await prefetch_batch(batch)

            logger.debug(f"Pre-fetched {len(prefetch_cache)}/{len(symbols)} symbols")

            async def data_fetcher(symbol: str) -> Optional[tuple]:
                if symbol in prefetch_cache:
                    return prefetch_cache[symbol]
                return await self._fetch_historical_cached(symbol, days=historical_days)

            # Execute scan
            start_time = datetime.now()
            result = await scanner.scan_async(symbols=symbols, data_fetcher=data_fetcher, mode=mode)
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
        self, mode: ScanMode, symbols: List[str], min_score: float, max_results: int
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

        Runs all strategies (Pullback, Bounce)
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
        5. Multi-Strategy Scan (Pullback, Bounce)
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
                symbols,
                min_days,
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
        from ..constants.trading_rules import SIZING_MAX_PER_SECTOR, SPREAD_MIN_CREDIT_PCT

        engine_config = {
            "min_stability_score": min_stability,
            "min_signal_score": min_score,
            "max_picks": max_picks,
            "enable_strike_recommendations": include_strikes,
            "enable_sector_diversification": True,
            "enable_blacklist_filter": True,
            "enable_vix_regime_filter": True,
            "max_per_sector": SIZING_MAX_PER_SECTOR,  # PLAYBOOK §5: 2
        }

        # Use existing scanner from handler
        scanner = self._get_multi_scanner(
            min_score=min_score,
            enable_pullback=True,
            enable_bounce=True,
        )

        engine = DailyRecommendationEngine(
            scanner=scanner,
            config=engine_config,
        )

        if vix_level:
            engine.set_vix(vix_level)

        # Determine historical data requirement
        historical_days = max(
            self._config.settings.performance.historical_days, 260  # Need 1 year for ATH detection
        )

        # Pre-fetch historical data
        prefetch_batch_size = getattr(self._config.settings.performance, "prefetch_batch_size", 20)
        prefetch_cache: Dict[str, tuple] = {}

        async def prefetch_batch(batch_symbols: List[str]) -> None:
            tasks = [
                self._fetch_historical_cached(sym, days=historical_days) for sym in batch_symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for sym, result in zip(batch_symbols, results):
                if result is not None and not isinstance(result, Exception):
                    prefetch_cache[sym] = result

        for i in range(0, len(symbols), prefetch_batch_size):
            batch = symbols[i : i + prefetch_batch_size]
            await prefetch_batch(batch)

        logger.debug(f"Pre-fetched {len(prefetch_cache)}/{len(symbols)} symbols")

        async def data_fetcher(symbol: str) -> Optional[tuple]:
            if symbol in prefetch_cache:
                return prefetch_cache[symbol]
            return await self._fetch_historical_cached(symbol, days=historical_days)

        # Options fetcher for liquidity assessment via IBKR
        async def options_fetcher(symbol: str) -> list[Any]:
            """Fetch options chain for liquidity check."""
            try:
                return await self._get_options_chain_with_fallback(
                    symbol, dte_min=SPREAD_DTE_MIN, dte_max=SPREAD_DTE_MAX, right="P"
                )
            except Exception as e:
                logger.warning(f"Could not fetch options for {symbol}: {e}")
                return []

        # Generate picks
        start_time = datetime.now()
        # Overfetch: request more picks than needed to account for chain-validation filtering
        engine_max_picks = max_picks * 3
        result = await engine.get_daily_picks(
            symbols=symbols,
            data_fetcher=data_fetcher,
            max_picks=engine_max_picks,
            vix=vix_level,
            options_fetcher=options_fetcher if include_strikes else None,
        )

        # Chain-First Validation (Phase 2): Validate top picks against real options chain
        if include_strikes and result.picks:
            result = await self._apply_chain_validation(result, max_picks)

        duration = (datetime.now() - start_time).total_seconds()

        # Format output
        return self._format_daily_picks_output(result, duration, excluded_by_earnings)

    async def _apply_chain_validation(
        self,
        result: DailyRecommendationResult,
        max_picks: int,
    ) -> DailyRecommendationResult:
        """
        Chain-First Validation: Validate picks against real options chain data.

        For each pick, runs OptionsChainValidator to verify:
        - Expiration in DTE window exists
        - Short/Long puts at correct deltas exist
        - Credit >= 10% spread width
        - Acceptable liquidity (OI, bid-ask)

        Filters out non-tradeable picks and attaches SpreadValidation to each pick.
        """
        try:
            from ..services.options_chain_validator import OptionsChainValidator
        except ImportError:
            logger.warning("OptionsChainValidator not available, skipping chain validation")
            return result

        # Get options provider from server
        options_provider = None
        ibkr_bridge = None

        try:
            if hasattr(self, "_provider") and self._provider:
                options_provider = self._provider
        except Exception as e:
            logger.debug(f"Could not get options provider: {e}")

        try:
            if hasattr(self, "_ibkr") and self._ibkr:
                ibkr_bridge = self._ibkr
        except Exception as e:
            logger.debug(f"Could not get IBKR bridge: {e}")

        if not options_provider:
            logger.info("No options provider available, skipping chain validation")
            return result

        chain_validator = OptionsChainValidator(
            options_provider=options_provider,
            ibkr_bridge=ibkr_bridge,
        )

        validated_picks = []
        chain_rejected = 0

        for pick in result.picks:
            if len(validated_picks) >= max_picks:
                break

            try:
                spread = await chain_validator.validate_spread(pick.symbol)

                if spread.tradeable:
                    pick.spread_validation = spread
                    validated_picks.append(pick)
                    logger.info(
                        f"Chain OK: {pick.symbol} — "
                        f"Credit ${spread.credit_bid:.2f} ({spread.credit_pct:.1f}%) "
                        f"Spread ${spread.spread_width:.0f} "
                        f"[{spread.data_source}]"
                    )
                else:
                    chain_rejected += 1
                    logger.info(f"Chain REJECTED: {pick.symbol} — {spread.reason}")
            except Exception as e:
                logger.warning(f"Chain validation error for {pick.symbol}: {e}")
                # Keep pick without chain data rather than silently dropping
                validated_picks.append(pick)

        # Re-rank after chain filtering
        for i, pick in enumerate(validated_picks, 1):
            pick.rank = i

        if chain_rejected > 0:
            logger.info(
                f"Chain validation: {len(validated_picks)} tradeable, " f"{chain_rejected} rejected"
            )
            if not result.warnings:
                result.warnings = []
            result.warnings.append(
                f"Chain-Validierung: {chain_rejected} Picks nicht handelbar (fehlende Liquidität/Strikes)"
            )

        result.picks = validated_picks
        return result

    def _format_daily_picks_output(
        self,
        result: DailyRecommendationResult,
        duration: float,
        excluded_by_earnings: int = 0,
    ) -> str:
        """Format daily picks result as Markdown (v2 format with real chain data)."""
        b = MarkdownBuilder()
        today_str = date.today().isoformat()

        # Header
        b.h1(f"Daily Picks -- {today_str}").blank()

        # Market Overview (compact single-line)
        if result.vix_level:
            regime_display = {
                "LOW_VOL": "Normal",
                "NORMAL": "Normal",
                "DANGER_ZONE": "Danger Zone",
                "ELEVATED": "Elevated",
                "HIGH_VOL": "High Volatility",
                # None regime handled at call site
            }
            regime_str = regime_display.get(result.market_regime.value, result.market_regime.value) if result.market_regime else "Unknown"
            b.kv("Regime", f"{regime_str} (VIX {result.vix_level:.2f})")

        b.kv("Scanned", f"{result.symbols_scanned} symbols | Duration: {duration:.1f}s")
        b.blank()

        # Warnings (compact)
        if result.warnings:
            for warning in result.warnings:
                b.bullet(warning)
            b.blank()

        # Picks — detailed v2 format
        if result.picks:
            for pick in result.picks:
                self._format_single_pick_v2(b, pick)
        else:
            b.hint("No candidates found matching criteria.")

        return b.build()

    def _format_single_pick_v2(self, b: MarkdownBuilder, pick: DailyPick) -> None:
        """
        Format a single pick in v2 format with real chain data.

        Output matches TASKS_DAILY_PICKS_V2.md Task 4.1 specification.
        """
        from ..constants.trading_rules import SPREAD_MIN_CREDIT_PCT

        # Strategy display
        strategy_display = {
            "pullback": "Pullback",
            "bounce": "Bounce",
        }
        strategy_str = strategy_display.get(pick.strategy, pick.strategy.replace("_", " ").title())

        # EQS display
        eqs_str = ""
        if pick.entry_quality and hasattr(pick.entry_quality, "eqs_total"):
            eqs_str = f" | EQS {pick.entry_quality.eqs_total:.0f}"

        # Header
        b.h2(f"#{pick.rank} -- {pick.symbol} | {strategy_str} | Score {pick.score:.1f}{eqs_str}")
        b.blank()

        # Chain-validated spread data (if available from SpreadValidation)
        sv = pick.spread_validation
        if sv and sv.tradeable:
            # Legs table
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

            # Spread details
            b.text(
                f"**Spread:** ${sv.spread_width:.0f} breit | "
                f"**Expiry:** {sv.expiration} ({sv.dte} DTE)"
            )

            # Credit line
            credit_check = (
                "OK" if sv.credit_pct and sv.credit_pct >= SPREAD_MIN_CREDIT_PCT else "LOW"
            )
            b.text(
                f"**Credit:** ${sv.credit_bid:.2f} (Bid) -- "
                f"${sv.credit_mid:.2f} (Mid) | "
                f"**Credit/Breite:** {sv.credit_pct:.1f}% {credit_check}"
            )

            # Risk targets
            max_loss = sv.max_loss_per_contract if sv.max_loss_per_contract else 0
            profit_target_50 = (
                sv.credit_bid * (EXIT_PROFIT_PCT_NORMAL / 100) if sv.credit_bid else 0
            )
            stop_loss_200 = sv.credit_bid * EXIT_STOP_LOSS_MULTIPLIER if sv.credit_bid else 0
            b.text(
                f"**Max Loss:** ${max_loss:.0f}/Kontrakt | "
                f"**50% Target:** ${profit_target_50:.2f} | "
                f"**200% Stop:** ${stop_loss_200:.2f}"
            )
            b.blank()

        elif pick.suggested_strikes:
            # Fallback: theoretical strikes (no chain data)
            s = pick.suggested_strikes
            b.text(
                f"**Strikes:** Short ${s.short_strike:.0f} / Long ${s.long_strike:.0f} "
                f"| Width ${s.spread_width:.0f}"
            )
            if s.estimated_credit:
                b.text(f"**Est. Credit:** ${s.estimated_credit:.2f}")
            if s.expiry:
                dte_str = f" ({s.dte} DTE)" if s.dte is not None else ""
                b.text(f"**Expiry:** {s.expiry}{dte_str}")
            if s.tradeable_status and s.tradeable_status != "unknown":
                b.text(f"**Status:** {s.tradeable_status}")
            b.blank()

        # Entry Quality line (if EQS available)
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

        # Checklist line
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

        # Signal reason
        if pick.reason:
            b.text(f"**Signal:** {truncate(pick.reason, 120)}")

        # Warnings
        if pick.warnings:
            for warning in pick.warnings:
                b.bullet(f"Warning: {warning}")

        b.blank()

    # Keep old method for backward compatibility
    def _format_single_pick_detail(self, b: MarkdownBuilder, pick: DailyPick) -> None:
        """Format a single pick with details (legacy format, kept for compatibility)."""
        self._format_single_pick_v2(b, pick)
