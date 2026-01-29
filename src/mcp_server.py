"""
OptionPlay MCP Server v3.2.0
=============================

MCP Server for options trading analysis with multi-strategy support.

Improvements v3.2.0:
- Multi-Strategy Scanner (Pullback, Bounce, ATH Breakout, Earnings Dip)
- New tools: scan_bounce, scan_ath_breakout, scan_earnings_dip, scan_multi, analyze_multi
- Single-symbol multi-strategy analysis

Improvements v3.0.0:
- Unified error handling with @mcp_endpoint decorator
- English docstrings throughout
- Better user-friendly error messages
- Improved code structure and maintainability

Improvements v2.5.0:
- Magic numbers moved to config
- PerformanceConfig and ApiConnectionConfig dataclasses
- All constants configurable via settings.yaml
- Historical data cache with configurable TTL

Usage:
    python3 -m src.mcp_server
    python3 -m src.mcp_server --interactive
    python3 -m src.mcp_server --test
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Local imports
from .data_providers.marketdata import MarketDataProvider
from .data_providers.tradier import TradierProvider, TradierEnvironment
from .utils.provider_orchestrator import get_orchestrator, ProviderType, DataType
from .scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig, ScanMode
from .cache import EarningsFetcher, get_earnings_fetcher, EarningsInfo, get_historical_cache, CacheStatus
from .vix_strategy import (
    VIXStrategySelector, get_strategy_for_vix, get_strategy_for_stock,
    calculate_spread_width, get_spread_width_table, format_recommendation, MarketRegime
)
from .utils.rate_limiter import get_marketdata_limiter, AdaptiveRateLimiter
from .utils.validation import validate_symbol, validate_symbols, validate_dte_range, ValidationError, is_etf
from .utils.secure_config import get_api_key, mask_api_key
from .utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, get_circuit_breaker
from .utils.error_handler import mcp_endpoint, sync_endpoint, format_error_response, truncate_string
from .utils.markdown_builder import MarkdownBuilder, format_price, format_volume, truncate
from .utils.metrics import metrics
from .utils.request_dedup import get_request_deduplicator, RequestDeduplicator
from .utils.earnings_aggregator import (
    EarningsAggregator, EarningsResult, EarningsSource, 
    AggregatedEarnings, get_earnings_aggregator, create_earnings_result
)
from .formatters import formatters, HealthCheckData, portfolio_formatter
from .portfolio import (
    PortfolioManager, BullPutSpread, PortfolioSummary,
    get_portfolio_manager, PositionStatus
)
from .config import get_config, get_scan_config, get_watchlist_loader
from .strike_recommender import StrikeRecommender, StrikeRecommendation, StrikeQuality
from .spread_analyzer import SpreadAnalyzer, BullPutSpreadParams, SpreadAnalysis
from .backtesting import (
    BacktestEngine, BacktestConfig, BacktestResult,
    TradeSimulator, PriceSimulator, PerformanceMetrics, calculate_metrics
)
from .indicators.support_resistance import find_support_levels, calculate_fibonacci
from .indicators.events import EventCalendar, get_macro_events, EventType
from .container import ServiceContainer

# IBKR Bridge (optional)
try:
    from .ibkr_bridge import IBKRBridge, get_ibkr_bridge
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False

logger = logging.getLogger(__name__)


class OptionPlayServer:
    """
    OptionPlay Server for multi-strategy options analysis.
    
    Features:
    - Multi-Strategy Scanner (Pullback, Bounce, ATH Breakout, Earnings Dip)
    - Automatic VIX-based strategy selection
    - Rate limiting with adaptive backoff
    - Multi-source earnings check
    - Circuit breaker for API resilience
    
    Usage:
        server = OptionPlayServer()
        
        # Multi-strategy scan
        result = await server.scan_multi_strategy()
        
        # Single symbol multi-strategy analysis
        result = await server.analyze_multi_strategy("AAPL")
        
        # VIX-aware pullback scan
        result = await server.scan_with_strategy()
    """
    
    VERSION = "3.4.0"

    def __init__(
        self,
        api_key: Optional[str] = None,
        container: Optional[ServiceContainer] = None
    ):
        """
        Initialize OptionPlay server.

        Args:
            api_key: Marketdata.app API key (optional, reads from env if not provided)
            container: Dependency injection container (optional, creates default if not provided)

        Raises:
            ValueError: If API key is not provided and not found in environment
        """
        # Use container if provided, otherwise create services directly
        self._container = container

        if container is not None:
            # Use container services
            self._config = container.config
            self._rate_limiter = container.rate_limiter
            self._circuit_breaker = container.circuit_breaker
            self._historical_cache = container.historical_cache
            self._provider = container.provider
            self._api_key = api_key or get_api_key("MARKETDATA_API_KEY", required=True)
        else:
            # Legacy: create services directly (backwards compatible)
            self._config = get_config()
            perf = self._config.settings.performance
            cb_cfg = self._config.settings.circuit_breaker

            # Load API key (with lazy loading and masking)
            self._api_key = api_key
            if not self._api_key:
                try:
                    self._api_key = get_api_key("MARKETDATA_API_KEY", required=True)
                except ValueError as e:
                    raise ValueError(
                        "MARKETDATA_API_KEY required. "
                        "Set environment variable or create .env file."
                    ) from e

            # Initialize components
            self._provider = None
            self._rate_limiter = get_marketdata_limiter()
            self._historical_cache = get_historical_cache(
                ttl_seconds=perf.cache_ttl_seconds,
                max_entries=perf.cache_max_entries
            )

            # Circuit breaker for API connections
            self._circuit_breaker = get_circuit_breaker(
                name="marketdata_api",
                failure_threshold=cb_cfg.failure_threshold,
                recovery_timeout=cb_cfg.recovery_timeout,
            )

        logger.debug(f"API key loaded: {mask_api_key(self._api_key)}")

        # Non-container components (always created directly)
        self._scanner: Optional[MultiStrategyScanner] = None
        self._earnings_fetcher: Optional[EarningsFetcher] = None
        self._vix_selector = VIXStrategySelector()

        # Connection state
        self._connected = False
        self._current_vix: Optional[float] = None
        self._vix_updated: Optional[datetime] = None

        # Quote cache (reduces repeated API calls for same symbol)
        self._quote_cache: Dict[str, tuple] = {}  # symbol -> (quote, timestamp)
        self._quote_cache_hits = 0
        self._quote_cache_misses = 0

        # Scan results cache (reduces repeated scans with same parameters)
        self._scan_cache: Dict[str, tuple] = {}  # cache_key -> (result, timestamp)
        self._scan_cache_ttl = 1800  # 30 minutes (for 1-2x daily usage)
        self._scan_cache_hits = 0
        self._scan_cache_misses = 0

        # Request deduplicator (prevents duplicate concurrent requests)
        self._deduplicator = get_request_deduplicator()

        # IBKR Bridge (optional)
        self._ibkr_bridge: Optional["IBKRBridge"] = None
        if IBKR_AVAILABLE:
            self._ibkr_bridge = get_ibkr_bridge()

        # Tradier Provider (optional - higher priority than Marketdata)
        self._tradier_provider: Optional[TradierProvider] = None
        self._tradier_api_key: Optional[str] = None
        self._tradier_connected = False
        self._orchestrator = get_orchestrator()

        # Check if Tradier is configured and enable it
        try:
            tradier_key = get_api_key("TRADIER_API_KEY", required=False)
            if tradier_key:
                self._tradier_api_key = tradier_key
                logger.info(f"Tradier API key found: {mask_api_key(tradier_key)}")
        except Exception:
            logger.debug("Tradier API key not configured")

    @property
    def api_key_masked(self) -> str:
        """Return masked API key for debugging/logging."""
        return mask_api_key(self._api_key)

    # =========================================================================
    # ASYNC CONTEXT MANAGER
    # =========================================================================

    async def __aenter__(self) -> "OptionPlayServer":
        """
        Enter async context - connect to data provider.

        Usage:
            async with OptionPlayServer() as server:
                result = await server.get_quote("AAPL")

        Returns:
            Connected server instance
        """
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit async context - disconnect and cleanup.

        Args:
            exc_type: Exception type if any
            exc_val: Exception value if any
            exc_tb: Exception traceback if any
        """
        await self.disconnect()
        # Don't suppress exceptions
        return None

    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================

    async def _ensure_tradier_connected(self) -> Optional[TradierProvider]:
        """
        Establish connection to Tradier API.

        Returns:
            Connected TradierProvider instance or None if not configured

        Note:
            Tradier connection failures are logged but don't raise exceptions.
            Falls back to Marketdata.app if Tradier is unavailable.
        """
        if not self._tradier_api_key:
            return None

        if self._tradier_provider is None:
            # Get environment from config
            tradier_cfg = self._config.settings.tradier
            env = TradierEnvironment.PRODUCTION if tradier_cfg.is_production else TradierEnvironment.SANDBOX

            self._tradier_provider = TradierProvider(
                api_key=self._tradier_api_key,
                environment=env
            )

        if not self._tradier_connected:
            try:
                connected = await self._tradier_provider.connect()
                if connected:
                    self._tradier_connected = True
                    self._orchestrator.enable_tradier(True)
                    logger.info(f"Connected to Tradier ({self._config.settings.tradier.environment})")
                else:
                    logger.warning("Tradier connection failed, using Marketdata.app as fallback")
            except Exception as e:
                logger.warning(f"Tradier connection error: {e}, using Marketdata.app as fallback")

        return self._tradier_provider if self._tradier_connected else None

    async def _ensure_connected(self) -> MarketDataProvider:
        """
        Establish connection to Marketdata.app with retry logic and circuit breaker.

        Returns:
            Connected MarketDataProvider instance

        Raises:
            CircuitBreakerOpen: If circuit breaker is open
            ConnectionError: If connection fails after retries
        """
        # Try to connect Tradier first (non-blocking, for orchestrator)
        await self._ensure_tradier_connected()

        # Check circuit breaker
        if not self._circuit_breaker.can_execute():
            retry_after = self._circuit_breaker.get_retry_after()
            raise CircuitBreakerOpen(
                self._circuit_breaker.name,
                retry_after
            )

        if self._provider is None:
            self._provider = MarketDataProvider(self._api_key)

        if not self._connected:
            api_conn = self._config.settings.api_connection
            max_retries = api_conn.max_retries
            base_delay = api_conn.retry_base_delay

            for attempt in range(max_retries):
                try:
                    await self._rate_limiter.acquire()
                    connected = await self._provider.connect()
                    if connected:
                        self._connected = True
                        self._rate_limiter.record_success()
                        self._circuit_breaker.record_success()
                        logger.info("Connected to Marketdata.app")
                        break
                except CircuitBreakerOpen:
                    raise
                except Exception as e:
                    logger.warning(f"Connection attempt {attempt + 1}/{max_retries} failed: {e}")
                    self._circuit_breaker.record_failure(e)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay ** attempt)

            if not self._connected:
                raise ConnectionError(
                    f"Cannot connect to Marketdata.app after {max_retries} attempts"
                )

        return self._provider

    def _get_active_provider_name(self) -> str:
        """Get the name of the currently active provider."""
        if self._tradier_connected:
            return "Tradier"
        return "Marketdata.app"
    
    def _get_scanner(
        self, 
        min_score: Optional[float] = None, 
        earnings_days: Optional[int] = None
    ) -> MultiStrategyScanner:
        """
        Get scanner instance with config from YAML (pullback only).
        
        Args:
            min_score: Override min_score from config (optional)
            earnings_days: Override earnings_days from config (optional)
            
        Returns:
            Configured MultiStrategyScanner instance
        """
        config = get_scan_config(
            override_min_score=min_score,
            override_earnings_days=earnings_days
        )
        
        # For Bull-Put-Spreads: disable ATH breakout and earnings dip strategies
        config.enable_ath_breakout = False
        config.enable_earnings_dip = False
        
        return MultiStrategyScanner(config)
    
    def _get_multi_scanner(
        self,
        min_score: float = 5.0,
        enable_pullback: bool = True,
        enable_bounce: bool = True,
        enable_breakout: bool = True,
        enable_earnings_dip: bool = True,
    ) -> MultiStrategyScanner:
        """
        Get scanner instance with all strategies enabled.
        
        Args:
            min_score: Minimum score threshold
            enable_pullback: Enable pullback strategy
            enable_bounce: Enable support bounce strategy
            enable_breakout: Enable ATH breakout strategy
            enable_earnings_dip: Enable earnings dip strategy
            
        Returns:
            Configured MultiStrategyScanner instance
        """
        # Get IV filter setting from config (default: disabled if no IV data source)
        # IV filter requires IV rank data which may not be available from all providers
        scanner_cfg = self._config.settings.scanner
        enable_iv = getattr(scanner_cfg, 'enable_iv_filter', False)

        # Only enable IV filter if we have a connected provider that supports IV
        if enable_iv and not self._tradier_connected:
            # Tradier provides IV data via ORATS, Marketdata.app may not
            logger.debug("IV filter disabled: no IV data provider connected")
            enable_iv = False

        config = ScanConfig(
            min_score=min_score,
            enable_pullback=enable_pullback,
            enable_bounce=enable_bounce,
            enable_ath_breakout=enable_breakout,
            enable_earnings_dip=enable_earnings_dip,
            enable_iv_filter=enable_iv,
        )
        return MultiStrategyScanner(config)
    
    async def _fetch_historical_cached(
        self,
        symbol: str,
        days: Optional[int] = None
    ) -> Optional[tuple]:
        """
        Fetch historical data with caching and request deduplication.

        Features:
        - TTL-based cache (cache_ttl_seconds, default 15 minutes)
        - Request deduplication for concurrent identical requests

        Args:
            symbol: Ticker symbol
            days: Number of days (default: from config)

        Returns:
            Tuple of (prices, volumes, highs, lows) or None
        """
        if days is None:
            days = self._config.settings.performance.historical_days

        # Check cache first
        cache_result = self._historical_cache.get(symbol, days)

        if cache_result.status == CacheStatus.HIT:
            logger.debug(f"Cache hit for {symbol} ({days}d)")
            return cache_result.data

        # Use deduplication for the actual API call
        async def fetch_historical():
            # Try Tradier first if connected (higher priority for historical data)
            tradier = await self._ensure_tradier_connected()
            if tradier:
                try:
                    d = await tradier.get_historical_for_scanner(symbol, days=days)
                    if d:
                        logger.debug(f"Historical data for {symbol} from Tradier")
                        return d
                except Exception as e:
                    logger.debug(f"Tradier historical failed for {symbol}: {e}")

            # Fallback to Marketdata.app
            provider = await self._ensure_connected()
            await self._rate_limiter.acquire()
            d = await provider.get_historical_for_scanner(symbol, days=days)
            self._rate_limiter.record_success()
            return d

        try:
            data = await self._deduplicator.deduplicated_call(
                key=f"historical:{symbol}:{days}",
                coro_factory=fetch_historical
            )

            if data:
                self._historical_cache.set(symbol, data, days=days)

            return data

        except Exception as e:
            logger.warning(f"Failed to fetch historical data for {symbol}: {e}")
            return None

    async def _apply_earnings_prefilter(
        self,
        symbols: List[str],
        min_days: int,
        for_earnings_dip: bool = False
    ) -> tuple[List[str], int, int]:
        """
        Internal earnings pre-filter that returns filtered symbols without markdown output.
        Uses the 4-week earnings cache to minimize API calls.

        Args:
            symbols: List of symbols to filter
            min_days: Minimum days until earnings (for normal strategies)
            for_earnings_dip: If True, filter for earnings_dip strategy instead
                              (only keep symbols with RECENT PAST earnings)

        Returns:
            Tuple of (safe_symbols, excluded_count, cache_hits)
        """
        if self._earnings_fetcher is None:
            self._earnings_fetcher = get_earnings_fetcher()

        safe_symbols: List[str] = []
        excluded_count = 0
        cache_hits = 0

        for symbol in symbols:
            try:
                # ETFs haben keine Earnings - direkt akzeptieren
                if is_etf(symbol):
                    safe_symbols.append(symbol)
                    logger.debug(f"Including {symbol}: ETF (no earnings)")
                    continue

                # Check cache first
                cached = self._earnings_fetcher.cache.get(symbol)
                if cached:
                    cache_hits += 1
                    days_to = cached.days_to_earnings
                else:
                    # Fetch from API
                    fetched = await asyncio.to_thread(
                        self._earnings_fetcher.fetch,
                        symbol
                    )
                    days_to = fetched.days_to_earnings if fetched else None

                if for_earnings_dip:
                    # Für earnings_dip: Nur Symbole mit KÜRZLICH VERGANGENEN Earnings
                    # days_to muss negativ sein (Earnings vorbei) und nicht älter als 10 Tage
                    if days_to is not None and -10 <= days_to <= 0:
                        safe_symbols.append(symbol)
                    else:
                        excluded_count += 1
                        if days_to is None:
                            logger.debug(f"Excluding {symbol} for earnings_dip: unknown earnings date")
                        elif days_to > 0:
                            logger.debug(f"Excluding {symbol} for earnings_dip: earnings in {days_to} days (not yet occurred)")
                        else:
                            logger.debug(f"Excluding {symbol} for earnings_dip: earnings {abs(days_to)} days ago (too old)")
                else:
                    # Für normale Strategien: Symbole mit bevorstehenden Earnings ausschließen
                    if days_to is not None and days_to >= min_days:
                        safe_symbols.append(symbol)
                    elif days_to is None:
                        # Unbekannte Earnings = akzeptieren (weniger konservativ)
                        # User kann manuell mit /prefilter filtern wenn gewünscht
                        safe_symbols.append(symbol)
                        logger.debug(f"Including {symbol}: unknown earnings date (use /prefilter for stricter filtering)")
                    else:
                        excluded_count += 1

            except Exception as e:
                # Bei Fehlern ebenfalls ausschließen (konservativ)
                logger.debug(f"Earnings check failed for {symbol}: {e}")
                excluded_count += 1

        return safe_symbols, excluded_count, cache_hits

    async def _get_quote_cached(self, symbol: str) -> Optional[Any]:
        """
        Get quote with caching and request deduplication.

        Features:
        - TTL-based cache (cache_ttl_intraday, default 5 minutes)
        - Request deduplication for concurrent identical requests
        - Automatic provider selection (Tradier > Marketdata)

        Args:
            symbol: Ticker symbol

        Returns:
            PriceQuote or None
        """
        symbol = symbol.upper()
        cache_ttl = self._config.settings.performance.cache_ttl_intraday

        # Check cache first
        if symbol in self._quote_cache:
            quote, timestamp = self._quote_cache[symbol]
            age = (datetime.now() - timestamp).total_seconds()
            if age < cache_ttl:
                self._quote_cache_hits += 1
                logger.debug(f"Quote cache HIT: {symbol} (age: {age:.0f}s)")
                return quote

        # Use deduplication for the actual API call
        async def fetch_quote():
            # Prefer Tradier if connected, otherwise use Marketdata
            if self._tradier_connected and self._tradier_provider:
                try:
                    q = await self._tradier_provider.get_quote(symbol)
                    if q and q.last:
                        self._orchestrator.record_request(ProviderType.TRADIER, success=True)
                        return q
                except Exception as e:
                    logger.debug(f"Tradier quote failed for {symbol}, falling back to Marketdata: {e}")
                    self._orchestrator.record_request(ProviderType.TRADIER, success=False, error=str(e))

            # Fallback to Marketdata
            provider = await self._ensure_connected()
            await self._rate_limiter.acquire()
            q = await provider.get_quote(symbol)
            self._rate_limiter.record_success()
            self._orchestrator.record_request(ProviderType.MARKETDATA, success=True)
            return q

        quote = await self._deduplicator.deduplicated_call(
            key=f"quote:{symbol}",
            coro_factory=fetch_quote
        )

        # Cache result (even None to avoid repeated failed lookups)
        self._quote_cache[symbol] = (quote, datetime.now())
        self._quote_cache_misses += 1
        logger.debug(f"Quote cache MISS: {symbol}")

        return quote

    def _get_quote_cache_stats(self) -> Dict[str, Any]:
        """Get quote cache statistics."""
        total = self._quote_cache_hits + self._quote_cache_misses
        hit_rate = (self._quote_cache_hits / total * 100) if total > 0 else 0
        return {
            "entries": len(self._quote_cache),
            "hits": self._quote_cache_hits,
            "misses": self._quote_cache_misses,
            "hit_rate_percent": round(hit_rate, 1),
        }

    def _make_scan_cache_key(
        self,
        mode: ScanMode,
        symbols: List[str],
        min_score: float,
        max_results: int
    ) -> str:
        """Generate a cache key for scan results."""
        # Sort symbols for consistent hashing
        symbols_hash = hash(tuple(sorted(symbols)))
        return f"scan:{mode.value}:{symbols_hash}:{min_score}:{max_results}"

    def _get_scan_cache_stats(self) -> Dict[str, Any]:
        """Get scan cache statistics."""
        total = self._scan_cache_hits + self._scan_cache_misses
        hit_rate = (self._scan_cache_hits / total * 100) if total > 0 else 0
        return {
            "entries": len(self._scan_cache),
            "hits": self._scan_cache_hits,
            "misses": self._scan_cache_misses,
            "hit_rate_percent": round(hit_rate, 1),
            "ttl_seconds": self._scan_cache_ttl,
        }

    async def _execute_scan(
        self,
        mode: ScanMode,
        title: str,
        emoji: str,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 5.0,
        min_historical_days: int = 0,
        table_columns: Optional[List[str]] = None,
        row_formatter: Optional[callable] = None,
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

        # Apply earnings pre-filter if enabled (reduces API calls!)
        original_count = len(symbols)
        excluded_by_earnings = 0
        earnings_cache_hits = 0

        scanner_config = self._config.settings.scanner
        # Für ALL/BEST_SIGNAL Modi: Kein Prefilter, da Scanner beide Earnings-Logiken braucht
        # Für andere Modi: Prefilter entsprechend dem Modus anwenden
        skip_prefilter = mode in [ScanMode.ALL, ScanMode.BEST_SIGNAL]

        if scanner_config.auto_earnings_prefilter and not skip_prefilter:
            min_days = scanner_config.earnings_prefilter_min_days
            # Für EARNINGS_DIP Modus: Nur Symbole mit kürzlich vergangenen Earnings
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

            # Load earnings dates into scanner for per-symbol filtering
            # This is needed for ALL/BEST_SIGNAL modes where prefilter is skipped
            if self._earnings_fetcher is None:
                self._earnings_fetcher = get_earnings_fetcher()

            for symbol in symbols:
                cached = self._earnings_fetcher.cache.get(symbol)
                if cached and cached.earnings_date:
                    from datetime import date as date_type
                    try:
                        earnings_date = date_type.fromisoformat(cached.earnings_date)
                        scanner.set_earnings_date(symbol, earnings_date)
                    except (ValueError, TypeError):
                        pass

            # Determine historical data requirement
            config_days = self._config.settings.performance.historical_days
            historical_days = max(config_days, min_historical_days) if min_historical_days else config_days

            # PERFORMANCE: Pre-fetch historical data in parallel batches
            # This reduces total scan time by ~15-20% by front-loading I/O
            prefetch_batch_size = self._config.settings.performance.get(
                "prefetch_batch_size", 20
            ) if hasattr(self._config.settings.performance, 'get') else 20

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

            # Pre-fetch all symbols in batches
            for i in range(0, len(symbols), prefetch_batch_size):
                batch = symbols[i:i + prefetch_batch_size]
                await prefetch_batch(batch)

            logger.debug(f"Pre-fetched {len(prefetch_cache)}/{len(symbols)} symbols")

            async def data_fetcher(symbol: str):
                # Return from prefetch cache if available, otherwise fetch
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
            b.kv("Source", "cached (2 min TTL)")
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

    async def disconnect(self):
        """Disconnect from all data providers."""
        if self._provider and self._connected:
            await self._provider.disconnect()
            self._connected = False
            logger.info("Marketdata.app disconnected")

        if self._tradier_provider and self._tradier_connected:
            await self._tradier_provider.disconnect()
            self._tradier_connected = False
            self._orchestrator.enable_tradier(False)
            logger.info("Tradier disconnected")
    
    # =========================================================================
    # VIX & STRATEGY
    # =========================================================================
    
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
        Shows current regime, trading parameters, and enabled strategies.

        Returns:
            Formatted Markdown regime status
        """
        from .backtesting.regime_model import RegimeModel, format_regime_status
        from .backtesting.regime_config import get_trained_model_loader

        vix = await self.get_vix()

        if vix is None:
            return "❌ Could not fetch VIX - unable to determine regime"

        try:
            # Try to load trained model
            model = RegimeModel.load_latest()
            model.initialize(vix)
            status = model.get_status()
            params = status.parameters

            b = MarkdownBuilder()
            b.h1("📊 VIX Regime Status").blank()

            # Current Status
            b.h2("Current Regime")
            regime_emoji = {
                "low_vol": "🟢",
                "normal": "🟡",
                "elevated": "🟠",
                "high_vol": "🔴",
            }.get(status.current_regime, "⚪")

            b.kv_line("VIX", f"{vix:.2f}")
            b.kv_line("Regime", f"{regime_emoji} {status.current_regime.upper()}")
            b.kv_line("VIX Range", f"{params.vix_range[0]:.0f} - {params.vix_range[1]:.0f}")
            b.kv_line("Days in Regime", str(status.days_in_regime))

            if status.pending_transition:
                b.kv_line("⚠️ Pending", f"{status.pending_transition} ({status.pending_days} days)")

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
            trained_icon = "✅" if params.is_trained else "⚠️"
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
            from .backtesting.regime_config import get_regime_for_vix, FIXED_REGIMES

            regime_name, config = get_regime_for_vix(vix, FIXED_REGIMES)

            b = MarkdownBuilder()
            b.h1("📊 VIX Regime Status (Default)").blank()

            b.h2("Current Regime")
            regime_emoji = {
                "low_vol": "🟢",
                "normal": "🟡",
                "elevated": "🟠",
                "high_vol": "🔴",
            }.get(regime_name, "⚪")

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

            b.text("⚠️ **Note**: Using default parameters. Run `train_regime_model.py` to train a model.")

            return b.build()

        except Exception as e:
            logger.error(f"Regime status error: {e}")
            return f"❌ Error getting regime status: {e}"

    @mcp_endpoint(operation="ensemble recommendation", symbol_param="symbol")
    async def get_ensemble_recommendation(self, symbol: str) -> str:
        """
        Get ensemble strategy recommendation for a symbol.

        Uses the trained ensemble selector to recommend the best strategy
        by combining:
        - Meta-learner predictions (symbol/regime-specific history)
        - Regime-weighted preferences
        - Confidence-weighted scoring
        - Strategy rotation engine

        Args:
            symbol: Ticker symbol to analyze

        Returns:
            Formatted Markdown ensemble recommendation
        """
        from .backtesting.ensemble_selector import (
            EnsembleSelector,
            StrategyScore,
            create_strategy_score,
        )

        symbol = validate_symbol(symbol)

        # Get current VIX for regime context
        vix = await self.get_vix()

        # Run multi-strategy analysis to get scores
        scanner = await self._get_scanner()
        results = await scanner.analyze_symbol(symbol)

        if not results:
            return f"❌ No analysis results for {symbol}"

        # Convert to StrategyScore format
        strategy_scores = {}
        for result in results:
            breakdown = {}
            if result.score_breakdown:
                for comp, data in result.score_breakdown.items():
                    if isinstance(data, dict):
                        score_val = data.get("score", data.get("value", 0))
                    else:
                        score_val = data
                    breakdown[f"{comp}_score"] = float(score_val) if score_val else 0

            strategy_scores[result.strategy] = create_strategy_score(
                strategy=result.strategy,
                raw_score=result.score,
                breakdown=breakdown,
                confidence=min(1.0, result.score / 10.0) if result.score else 0.5,
            )

        if not strategy_scores:
            return f"❌ No valid strategy scores for {symbol}"

        # Load trained ensemble selector (with symbol preferences from training)
        try:
            selector = EnsembleSelector.load_trained_model()
        except Exception as e:
            logger.warning(f"Could not load trained ensemble model: {e}")
            # Fallback to default selector
            selector = EnsembleSelector()

        # Get recommendation
        rec = selector.get_recommendation(symbol, strategy_scores, vix=vix)

        # Format output
        b = MarkdownBuilder()
        b.h1(f"🎯 Ensemble Recommendation: {symbol}").blank()

        # Primary Recommendation
        b.h2("Recommended Strategy")
        strategy_emoji = {
            "pullback": "📉",
            "bounce": "🔄",
            "ath_breakout": "🚀",
            "earnings_dip": "📊",
        }.get(rec.recommended_strategy, "📈")

        b.kv_line("Strategy", f"{strategy_emoji} **{rec.recommended_strategy.upper()}**")
        b.kv_line("Score", f"{rec.recommended_score:.1f}")
        b.kv_line("Confidence", f"{rec.ensemble_confidence:.0%}")
        b.kv_line("Method", rec.selection_method.value)
        b.blank()

        # Reason
        b.kv_line("Reason", rec.selection_reason)
        b.blank()

        # All Strategy Scores
        b.h2("All Strategies")
        b.text("| Strategy | Score | Confidence | Adjusted |")
        b.text("|----------|-------|------------|----------|")

        for strat, score in sorted(
            rec.strategy_scores.items(),
            key=lambda x: x[1].adjusted_score,
            reverse=True
        ):
            marker = " ⭐" if strat == rec.recommended_strategy else ""
            b.text(
                f"| {strat}{marker} | {score.weighted_score:.1f} | "
                f"{score.confidence:.0%} | {score.adjusted_score:.1f} |"
            )

        b.blank()

        # Context
        b.h2("Context")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")
        b.kv_line("Regime", rec.regime or "unknown")
        b.kv_line("Diversification", f"{rec.diversification_benefit:.0%}")
        b.blank()

        # Alternatives
        if rec.alternative_strategies:
            b.h2("Alternatives")
            b.text(", ".join(rec.alternative_strategies))
            b.blank()

        # Symbol Insights
        insights = selector.get_insights(symbol)
        if insights and insights.get("best_strategy"):
            b.h2("Symbol History")
            b.kv_line("Historical Best", insights["best_strategy"])
            b.kv_line("Confidence", f"{insights.get('confidence', 0):.0%}")

            # Win rates
            win_rates = insights.get("win_rates", {})
            if win_rates:
                best_wr = max(win_rates.values()) if win_rates else 0
                b.kv_line("Best Win Rate", f"{best_wr:.0%}")

        return b.build()

    async def get_ensemble_status(self) -> str:
        """
        Get ensemble selector and rotation engine status.

        Shows current strategy preferences, rotation status,
        and meta-learner insights.

        Returns:
            Formatted Markdown status
        """
        from .backtesting.ensemble_selector import EnsembleSelector

        vix = await self.get_vix()

        try:
            selector = EnsembleSelector.load_trained_model()
        except Exception as e:
            logger.warning(f"Could not load ensemble model: {e}")
            return "⚠️ No trained ensemble model. Run `train_ensemble_v2.py` to train."

        b = MarkdownBuilder()
        b.h1("🎭 Ensemble Strategy Status").blank()

        # Current regime
        if vix:
            regime = "low_vol" if vix < 15 else "normal" if vix < 20 else "elevated" if vix < 30 else "high_vol"
            b.h2("Current Context")
            b.kv_line("VIX", f"{vix:.2f}")
            b.kv_line("Regime", regime.upper())
            b.blank()

        # Rotation Status
        rotation = selector.get_rotation_status()
        if rotation:
            b.h2("Strategy Rotation")
            b.kv_line("Days Since Rotation", str(rotation.get("days_since_rotation", 0)))
            b.kv_line("Total Rotations", str(rotation.get("rotation_count", 0)))

            if rotation.get("last_rotation_reason"):
                b.kv_line("Last Trigger", rotation["last_rotation_reason"])

            b.blank()

            # Current Preferences
            b.h3("Current Preferences")
            prefs = rotation.get("current_preferences", {})
            for strat, pref in sorted(prefs.items(), key=lambda x: -x[1]):
                bar = "█" * int(pref * 20)
                b.text(f"{strat:<15} {pref:>5.1%} {bar}")

            b.blank()

            # Recent Performance
            b.h3("Recent Performance")
            perf = rotation.get("recent_performance", {})
            for strat, rate in sorted(perf.items()):
                if rate is not None:
                    b.text(f"{strat:<15} {rate:>6.1%}")
                else:
                    b.text(f"{strat:<15} {'N/A':>6}")

            b.blank()

        # Method info
        b.h2("Selector Info")
        b.kv_line("Method", selector.method.value)
        b.kv_line("Rotation Enabled", "Yes" if selector.enable_rotation else "No")
        b.kv_line("Min Score Threshold", f"{selector.min_score_threshold:.1f}")

        return b.build()

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
            return f"❌ Cannot get quote for {symbol}"

        stock_price = quote.last
        vix = await self.get_vix()

        recommendation = get_strategy_for_stock(vix, stock_price)

        b = MarkdownBuilder()
        b.h1(f"📊 Strategy for {symbol}").blank()

        b.h2("Market Context")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")
        b.kv_line("Regime", recommendation.regime.value)
        b.kv_line("Stock Price", f"${stock_price:.2f}")
        b.blank()

        b.h2("Basisstrategie: Short Put")
        b.kv_line("Delta-Target", f"{recommendation.delta_target}")
        b.kv_line("Delta-Range", f"[{recommendation.delta_min}, {recommendation.delta_max}]")
        b.kv_line("DTE", f"{recommendation.dte_min}-{recommendation.dte_max} Tage")
        b.kv_line("Earnings-Buffer", f">{recommendation.earnings_buffer_days} Tage")
        b.blank()

        b.h2("Dynamische Spread-Breite")
        b.kv_line("Empfohlene Breite", f"${recommendation.spread_width:.2f}")
        b.kv_line("Min-Score", f"{recommendation.min_score}")
        b.blank()

        # Spread width table
        spread_table = get_spread_width_table(stock_price)
        b.h3("Spread-Breite nach Regime")
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
            b.h2("⚠️ Warnungen")
            for warning in recommendation.warnings:
                b.text(f"• {warning}")

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
            return f"❌ Cannot get quote for {symbol}"

        stock_price = quote.last
        vix = await self.get_vix()
        regime = self._vix_selector.get_regime(vix)

        current_spread = calculate_spread_width(stock_price, regime)
        spread_table = get_spread_width_table(stock_price)

        b = MarkdownBuilder()
        b.h1(f"📐 Spread-Breite: {symbol}").blank()

        b.kv_line("Aktienkurs", f"${stock_price:.2f}")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")
        b.kv_line("Regime", regime.value if regime else "unknown")
        b.blank()

        b.h2("Empfohlene Spread-Breite")
        b.kv_line("Aktuelle Empfehlung", f"${current_spread:.2f}")
        b.blank()

        b.h2("Tabelle nach VIX-Regime")
        rows = [
            ["Low Vol (VIX <15)", f"${spread_table['low_vol']:.2f}"],
            ["Normal (VIX 15-20)", f"${spread_table['normal']:.2f}"],
            ["Elevated (VIX 20-30)", f"${spread_table['elevated']:.2f}"],
            ["High Vol (VIX >30)", f"${spread_table['high_vol']:.2f}"],
        ]
        b.table(["Regime", "Spread-Breite"], rows)

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
        b.h1(f"📅 Market Events (Next {days} Days)").blank()

        if not events:
            b.hint("No major events in this period.")
            return b.build()

        event_icons = {
            EventType.FED_MEETING: "🏦",
            EventType.CPI: "📊",
            EventType.NFP: "📈",
            EventType.OPEX: "📉",
            EventType.EARNINGS: "💰",
            EventType.DIVIDEND: "💵",
        }

        rows = []
        for event in events[:20]:
            icon = event_icons.get(event.event_type, "📌")
            days_until = (event.event_date - date.today()).days
            rows.append([
                str(event.event_date),
                f"+{days_until}d" if days_until >= 0 else f"{days_until}d",
                f"{icon} {event.event_type.value}",
                event.description or "-"
            ])

        b.table(["Date", "Days", "Event", "Description"], rows)

        return b.build()

    @mcp_endpoint(operation="earnings validation", symbol_param="symbol")
    async def validate_for_trading(self, symbol: str) -> str:
        """
        Validate if a symbol is safe for trading based on events.

        Checks earnings, dividends, and other events that could affect the trade.

        Args:
            symbol: Ticker symbol

        Returns:
            Validation result with confidence score
        """
        from datetime import timedelta

        symbol = validate_symbol(symbol)

        # Build event calendar with earnings
        calendar = EventCalendar(include_macro_events=True)

        # Try to get earnings date
        try:
            provider = await self._ensure_connected()
            await self._rate_limiter.acquire()
            earnings = await provider.get_earnings_date(symbol)
            self._rate_limiter.record_success()

            if earnings and earnings.earnings_date:
                earnings_date_obj = datetime.strptime(
                    earnings.earnings_date, "%Y-%m-%d"
                ).date() if isinstance(earnings.earnings_date, str) else earnings.earnings_date
                calendar.add_earnings(symbol, earnings_date_obj, confirmed=True)
        except Exception as e:
            logger.debug(f"Could not fetch earnings for {symbol}: {e}")

        # Validate
        result = calendar.validate_for_sr(symbol)

        b = MarkdownBuilder()
        b.h1(f"🔍 Trading Validation: {symbol}").blank()

        # Overall status
        if result.is_valid:
            if result.confidence_multiplier >= 0.9:
                b.status_ok("**✅ SAFE FOR TRADING**")
            else:
                b.status_warning(f"**⚠️ PROCEED WITH CAUTION** (Confidence: {result.confidence_multiplier:.0%})")
        else:
            b.status_error("**❌ NOT RECOMMENDED**")
        b.blank()

        b.kv_line("Confidence", f"{result.confidence_multiplier:.0%}")
        b.blank()

        # Blocking events
        if result.blocking_events:
            b.h2("🚫 Blocking Events")
            for event in result.blocking_events:
                b.text(f"• {event.event_type.value}: {event.event_date} ({event.days_until} days)")
            b.blank()

        # Warnings
        if result.warning_events:
            b.h2("⚠️ Warning Events")
            for event in result.warning_events:
                b.text(f"• {event.event_type.value}: {event.event_date} ({event.days_until} days)")
            b.blank()

        # Recommendations
        if result.recommendations:
            b.h2("💡 Recommendations")
            for rec in result.recommendations:
                b.text(f"• {rec}")

        return b.build()

    # =========================================================================
    # SCANNING - PULLBACK (ORIGINAL)
    # =========================================================================
    
    @mcp_endpoint(operation="pullback scan")
    async def scan_with_strategy(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        use_vix_strategy: bool = True,
    ) -> str:
        """
        Scan for pullback candidates with VIX-based strategy.
        
        Args:
            symbols: List of symbols (default: watchlist from config)
            max_results: Maximum results to return
            use_vix_strategy: Use VIX-based parameters
            
        Returns:
            Formatted Markdown string with scan results
        """
        provider = await self._ensure_connected()
        
        # Get VIX-based strategy
        vix = await self.get_vix() if use_vix_strategy else None
        recommendation = get_strategy_for_vix(vix)
        
        # Load default watchlist from config
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
            logger.debug(f"Loaded {len(symbols)} symbols from watchlist")
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)
        
        # Scanner with strategy parameters
        scanner = self._get_scanner(
            min_score=recommendation.min_score,
            earnings_days=recommendation.earnings_buffer_days
        )
        scanner.config.max_total_results = max_results
        
        # Data fetcher with cache
        historical_days = self._config.settings.performance.historical_days
        async def data_fetcher(symbol: str):
            return await self._fetch_historical_cached(symbol, days=historical_days)
        
        result = await scanner.scan_async(
            symbols=symbols,
            data_fetcher=data_fetcher,
            mode=ScanMode.PULLBACK_ONLY
        )
        
        # Format output using formatter
        return formatters.scan_result.format(
            result=result,
            recommendation=recommendation if use_vix_strategy else None,
            vix=vix if use_vix_strategy else None,
            max_results=max_results,
            show_details=3,
            title="Pullback Candidates Scan"
        )
    
    @mcp_endpoint(operation="legacy pullback scan")
    async def scan_pullback_candidates(
        self,
        symbols: Optional[List[str]] = None,
        min_score: float = 5.0,
        max_results: int = 10,
    ) -> str:
        """
        Legacy method: Scan without VIX integration.
        
        Use scan_with_strategy() instead for VIX-aware scanning.
        """
        provider = await self._ensure_connected()
        
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)
        
        scanner = self._get_scanner(min_score=min_score)
        scanner.config.max_total_results = max_results
        
        historical_days = self._config.settings.performance.historical_days
        async def data_fetcher(symbol: str):
            return await self._fetch_historical_cached(symbol, days=historical_days)
        
        result = await scanner.scan_async(
            symbols=symbols,
            data_fetcher=data_fetcher,
            mode=ScanMode.PULLBACK_ONLY
        )
        
        return formatters.legacy_scan.format(
            result=result,
            min_score=min_score,
            max_results=max_results
        )
    
    # =========================================================================
    # MULTI-STRATEGY SCANNING (NEW v3.2.0)
    # =========================================================================
    
    @mcp_endpoint(operation="support bounce scan")
    async def scan_bounce(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 5.0,
    ) -> str:
        """
        Scan for Support Bounce candidates.

        Identifies stocks bouncing off established support levels.
        Good for long entries (stock or call options).

        Args:
            symbols: List of symbols (default: watchlist from config)
            max_results: Maximum results to return
            min_score: Minimum bounce score

        Returns:
            Formatted Markdown string with bounce candidates
        """
        def format_bounce_row(signal):
            details = signal.details or {}
            rsi = details.get('rsi', 0)
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                f"{rsi:.0f}" if rsi else "-",
                truncate(signal.reason, 40) if signal.reason else "-"
            ]

        return await self._execute_scan(
            mode=ScanMode.BOUNCE_ONLY,
            title="Support Bounce Scan",
            emoji="🔄",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            table_columns=["Symbol", "Score", "Price", "RSI", "Signal"],
            row_formatter=format_bounce_row,
            no_results_msg="No bounce candidates found.",
        )
    
    @mcp_endpoint(operation="ATH breakout scan")
    async def scan_ath_breakout(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 6.0,
    ) -> str:
        """
        Scan for ATH Breakout candidates.

        Identifies stocks breaking out to new all-time highs with volume confirmation.

        Args:
            symbols: List of symbols (default: watchlist from config)
            max_results: Maximum results to return
            min_score: Minimum breakout score

        Returns:
            Formatted Markdown string with breakout candidates
        """
        def format_breakout_row(signal):
            details = signal.details or {}
            ath_info = details.get('ath_info', {})
            pct_above = ath_info.get('pct_above_old', 0)
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                f"+{pct_above:.1f}%" if pct_above else "-",
                truncate(signal.reason, 35) if signal.reason else "-"
            ]

        return await self._execute_scan(
            mode=ScanMode.BREAKOUT_ONLY,
            title="ATH Breakout Scan",
            emoji="🚀",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            min_historical_days=260,  # Need more history for ATH detection
            table_columns=["Symbol", "Score", "Price", "vs ATH", "Signal"],
            row_formatter=format_breakout_row,
            no_results_msg="No ATH breakout candidates found.",
        )
    
    @mcp_endpoint(operation="earnings dip scan")
    async def scan_earnings_dip(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 10,
        min_score: float = 5.0,
    ) -> str:
        """
        Scan for Earnings Dip Buy candidates.

        Identifies quality stocks that dropped 5-15% after earnings.

        Args:
            symbols: List of symbols (default: watchlist from config)
            max_results: Maximum results to return
            min_score: Minimum earnings dip score

        Returns:
            Formatted Markdown string with earnings dip candidates
        """
        def format_dip_row(signal):
            details = signal.details or {}
            dip_info = details.get('dip_info', {})
            dip_pct = dip_info.get('dip_pct', 0)
            return [
                signal.symbol,
                f"{signal.score:.1f}",
                f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                f"-{dip_pct:.1f}%" if dip_pct else "-",
                truncate(signal.reason, 35) if signal.reason else "-"
            ]

        return await self._execute_scan(
            mode=ScanMode.EARNINGS_DIP,
            title="Earnings Dip Scan",
            emoji="📉",
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            table_columns=["Symbol", "Score", "Price", "Dip", "Signal"],
            row_formatter=format_dip_row,
            no_results_msg="No earnings dip candidates found.",
        )
    
    @mcp_endpoint(operation="multi-strategy scan")
    async def scan_multi_strategy(
        self,
        symbols: Optional[List[str]] = None,
        max_results: int = 20,
        min_score: float = 5.0,
    ) -> str:
        """
        Multi-Strategy Scan - runs all strategies and returns the best signal per symbol.
        
        Args:
            symbols: List of symbols (default: watchlist from config)
            max_results: Maximum results to return
            min_score: Minimum score across any strategy
            
        Returns:
            Formatted Markdown string with multi-strategy results
        """
        provider = await self._ensure_connected()
        
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)
        
        scanner = self._get_multi_scanner(
            min_score=min_score,
            enable_pullback=True,
            enable_bounce=True,
            enable_breakout=True,
            enable_earnings_dip=True,
        )
        scanner.config.max_total_results = max_results * 2

        # Load earnings dates into scanner cache for per-symbol filtering
        if self._earnings_fetcher is None:
            self._earnings_fetcher = get_earnings_fetcher()

        for symbol in symbols:
            cached = self._earnings_fetcher.cache.get(symbol)
            if cached and cached.earnings_date:
                from datetime import date as date_type
                try:
                    earnings_date = date_type.fromisoformat(cached.earnings_date)
                    scanner.set_earnings_date(symbol, earnings_date)
                except (ValueError, TypeError):
                    pass

        historical_days = max(self._config.settings.performance.historical_days, 260)
        async def data_fetcher(symbol: str):
            return await self._fetch_historical_cached(symbol, days=historical_days)

        vix = await self.get_vix()

        start_time = datetime.now()
        result = await scanner.scan_async(
            symbols=symbols,
            data_fetcher=data_fetcher,
            mode=ScanMode.BEST_SIGNAL
        )
        duration = (datetime.now() - start_time).total_seconds()
        
        strategy_icons = {
            'pullback': '📊', 'bounce': '🔄',
            'ath_breakout': '🚀', 'earnings_dip': '📉',
        }
        strategy_names = {
            'pullback': 'Bull-Put-Spread', 'bounce': 'Support Bounce',
            'ath_breakout': 'ATH Breakout', 'earnings_dip': 'Earnings Dip',
        }
        
        b = MarkdownBuilder()
        b.h1("📊 Multi-Strategy Scan").blank()
        b.kv("VIX", f"{vix:.2f}" if vix else "N/A")
        b.kv("Scanned", f"{len(symbols)} symbols")
        b.kv("With Signals", result.symbols_with_signals)
        b.kv("Duration", f"{duration:.1f}s")
        b.blank()
        
        if result.signals:
            by_strategy: Dict[str, List] = {}
            for signal in result.signals:
                if signal.strategy not in by_strategy:
                    by_strategy[signal.strategy] = []
                by_strategy[signal.strategy].append(signal)
            
            b.h2("Strategy Summary").blank()
            rows = []
            for strat, sigs in sorted(by_strategy.items(), key=lambda x: -len(x[1])):
                icon = strategy_icons.get(strat, '•')
                name = strategy_names.get(strat, strat)
                top = ", ".join([s.symbol for s in sigs[:3]])
                rows.append([f"{icon} {name}", str(len(sigs)), top])
            b.table(["Strategy", "Count", "Top Symbols"], rows)
            b.blank()
            
            b.h2("All Candidates").blank()
            rows = []
            for signal in result.signals[:max_results]:
                icon = strategy_icons.get(signal.strategy, '•')
                name = strategy_names.get(signal.strategy, signal.strategy)
                rows.append([
                    signal.symbol,
                    f"{icon} {name}",
                    f"{signal.score:.1f}",
                    f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                    truncate(signal.reason, 30) if signal.reason else "-"
                ])
            b.table(["Symbol", "Strategy", "Score", "Price", "Signal"], rows)
        else:
            b.hint("No signals found.")
        
        return b.build()
    
    @mcp_endpoint(operation="multi-strategy symbol analysis", symbol_param="symbol")
    async def analyze_multi_strategy(self, symbol: str) -> str:
        """
        Analyze a single symbol with all available strategies.
        
        Args:
            symbol: Ticker symbol
            
        Returns:
            Formatted Markdown analysis with all strategy scores
        """
        symbol = validate_symbol(symbol)
        provider = await self._ensure_connected()
        
        historical_days = max(self._config.settings.performance.historical_days, 260)
        data = await self._fetch_historical_cached(symbol, days=historical_days)
        
        if not data:
            return f"❌ No historical data available for {symbol}"
        
        prices, volumes, highs, lows = data

        quote = await self._get_quote_cached(symbol)

        vix = await self.get_vix()

        # Initialize scanner with earnings data
        scanner = self._get_multi_scanner(min_score=0)

        # Load earnings date for this symbol into scanner cache
        if self._earnings_fetcher is None:
            self._earnings_fetcher = get_earnings_fetcher()
        cached_earnings = self._earnings_fetcher.cache.get(symbol)
        if cached_earnings and cached_earnings.earnings_date:
            from datetime import date as date_type
            try:
                earnings_date = date_type.fromisoformat(cached_earnings.earnings_date)
                scanner.set_earnings_date(symbol, earnings_date)
            except (ValueError, TypeError):
                pass

        signals = scanner.analyze_symbol(symbol, prices, volumes, highs, lows)

        strategy_icons = {
            'pullback': '📊', 'bounce': '🔄',
            'ath_breakout': '🚀', 'earnings_dip': '📉',
        }
        strategy_names = {
            'pullback': 'Bull-Put-Spread', 'bounce': 'Support Bounce',
            'ath_breakout': 'ATH Breakout', 'earnings_dip': 'Earnings Dip',
        }

        b = MarkdownBuilder()
        b.h1(f"📊 Multi-Strategy Analysis: {symbol}").blank()

        if quote:
            b.kv_line("Price", f"${quote.last:.2f}" if quote.last else "N/A")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")

        # Earnings check with warning
        await self._rate_limiter.acquire()
        earnings = await provider.get_earnings_date(symbol)
        self._rate_limiter.record_success()

        if earnings and earnings.earnings_date:
            if earnings.days_to_earnings < 45:
                b.kv_line("Earnings", f"❌ {earnings.days_to_earnings}d - DO NOT TRADE")
            elif earnings.days_to_earnings < 60:
                b.kv_line("Earnings", f"⚠️ {earnings.days_to_earnings}d - CAUTION")
            else:
                b.kv_line("Earnings", f"✅ {earnings.days_to_earnings}d")
        else:
            b.kv_line("Earnings", "N/A")
        b.blank()

        signal_by_strategy = {s.strategy: s for s in signals}
        
        b.h2("Strategy Scores").blank()
        rows = []
        for strat in ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']:
            icon = strategy_icons.get(strat, '•')
            name = strategy_names.get(strat, strat)
            
            if strat in signal_by_strategy:
                sig = signal_by_strategy[strat]
                status = "✅ Strong" if sig.score >= 7 else ("🟡 Moderate" if sig.score >= 5 else "❌ Weak")
                reason = truncate(sig.reason, 35) if sig.reason else "-"
                rows.append([f"{icon} {name}", f"{sig.score:.1f}/10", status, reason])
            else:
                rows.append([f"{icon} {name}", "N/A", "❌ No signal", "-"])
        
        b.table(["Strategy", "Score", "Status", "Reason"], rows)
        b.blank()
        
        if signals:
            best = max(signals, key=lambda x: x.score)
            icon = strategy_icons.get(best.strategy, '•')
            name = strategy_names.get(best.strategy, best.strategy)
            
            if best.score >= 6:
                b.status_ok(f"**Best: {icon} {name}** (Score: {best.score:.1f}/10)")
            elif best.score >= 4:
                b.status_warning(f"**Moderate: {icon} {name}** (Score: {best.score:.1f}/10)")
            else:
                b.status_error("**No strong signals.**")
        
        return b.build()
    
    # =========================================================================
    # QUOTES & DATA
    # =========================================================================
    
    @mcp_endpoint(operation="quote lookup", symbol_param="symbol")
    async def get_quote(self, symbol: str) -> str:
        """Get current stock quote."""
        symbol = validate_symbol(symbol)

        quote = await self._get_quote_cached(symbol)

        return formatters.quote.format(symbol, quote)
    
    @mcp_endpoint(operation="options chain lookup", symbol_param="symbol")
    async def get_options_chain(
        self,
        symbol: str,
        dte_min: int = 30,
        dte_max: int = 60,
        right: str = "P",
        max_options: int = 15,
    ) -> str:
        """Get options chain for a symbol with automatic provider selection."""
        symbol = validate_symbol(symbol)
        dte_min, dte_max = validate_dte_range(dte_min, dte_max)

        quote = await self._get_quote_cached(symbol)
        underlying_price = quote.last if quote else None

        options = None

        # Try Tradier first if connected (better Greeks from ORATS)
        if self._tradier_connected and self._tradier_provider:
            try:
                options = await self._tradier_provider.get_option_chain(
                    symbol,
                    dte_min=dte_min,
                    dte_max=dte_max,
                    right=right.upper()
                )
                if options:
                    self._orchestrator.record_request(ProviderType.TRADIER, success=True)
                    logger.debug(f"Options chain from Tradier: {len(options)} options")
            except Exception as e:
                logger.debug(f"Tradier options chain failed for {symbol}, falling back: {e}")
                self._orchestrator.record_request(ProviderType.TRADIER, success=False, error=str(e))

        # Fallback to Marketdata
        if not options:
            provider = await self._ensure_connected()
            await self._rate_limiter.acquire()
            options = await provider.get_option_chain(
                symbol,
                dte_min=dte_min,
                dte_max=dte_max,
                right=right.upper()
            )
            self._rate_limiter.record_success()
            self._orchestrator.record_request(ProviderType.MARKETDATA, success=True)

        return formatters.options_chain.format(
            symbol=symbol,
            options=options or [],
            underlying_price=underlying_price,
            right=right,
            dte_min=dte_min,
            dte_max=dte_max,
            max_options=max_options
        )
    
    # =========================================================================
    # EARNINGS
    # =========================================================================
    
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
            logger.debug(f"Yahoo earnings API error for {symbol}: {e}")
            return {'earnings_date': None, 'days_to_earnings': None, 'source': 'error'}

    @mcp_endpoint(operation="earnings check", symbol_param="symbol")
    async def get_earnings(self, symbol: str, min_days: int = 60) -> str:
        """Check earnings date for a symbol with multi-source fallback."""
        symbol = validate_symbol(symbol)

        # ETFs haben keine Earnings
        if is_etf(symbol):
            return formatters.earnings.format(
                symbol=symbol,
                earnings_date=None,
                days_to_earnings=None,
                min_days=min_days,
                source="etf",
                is_etf=True
            )

        earnings_date = None
        days_to_earnings = None
        source_used = "unknown"

        # 1. Try Marketdata.app
        try:
            provider = await self._ensure_connected()
            await self._rate_limiter.acquire()
            earnings = await provider.get_earnings_date(symbol)
            self._rate_limiter.record_success()
            
            if earnings and earnings.earnings_date:
                earnings_date = earnings.earnings_date
                days_to_earnings = earnings.days_to_earnings
                source_used = "marketdata"
        except Exception as e:
            logger.debug(f"Marketdata.app earnings failed for {symbol}: {e}")
        
        # 2. Fallback to Yahoo Finance direct
        if not earnings_date:
            try:
                yahoo_data = await asyncio.to_thread(
                    self._fetch_yahoo_earnings,
                    symbol
                )
                if yahoo_data.get('earnings_date'):
                    earnings_date = yahoo_data['earnings_date']
                    days_to_earnings = yahoo_data['days_to_earnings']
                    source_used = "yahoo_direct"
            except Exception as e:
                logger.debug(f"Yahoo direct earnings failed for {symbol}: {e}")

        # 3. Final fallback: yfinance library
        if not earnings_date:
            try:
                if self._earnings_fetcher is None:
                    self._earnings_fetcher = get_earnings_fetcher()

                fetched = await asyncio.to_thread(
                    self._earnings_fetcher.fetch,
                    symbol
                )
                if fetched and fetched.earnings_date:
                    earnings_date = fetched.earnings_date
                    days_to_earnings = fetched.days_to_earnings
                    source_used = fetched.source.value
            except Exception as e:
                logger.debug(f"yfinance earnings failed for {symbol}: {e}")
        
        return formatters.earnings.format(
            symbol=symbol,
            earnings_date=earnings_date,
            days_to_earnings=days_to_earnings,
            min_days=min_days,
            source=source_used
        )
    
    @mcp_endpoint(operation="aggregated earnings check", symbol_param="symbol")
    async def get_earnings_aggregated(self, symbol: str, min_days: int = 60) -> str:
        """Check earnings date with multi-source aggregation and majority voting."""
        symbol = validate_symbol(symbol)
        results: List[EarningsResult] = []

        async def fetch_marketdata() -> EarningsResult:
            try:
                provider = await self._ensure_connected()
                await self._rate_limiter.acquire()
                earnings = await provider.get_earnings_date(symbol)
                self._rate_limiter.record_success()

                if earnings and earnings.earnings_date:
                    return create_earnings_result(
                        source="marketdata",
                        earnings_date=earnings.earnings_date,
                        days_to_earnings=earnings.days_to_earnings
                    )
                return create_earnings_result(source="marketdata", earnings_date=None, days_to_earnings=None)
            except Exception as e:
                return create_earnings_result(source="marketdata", earnings_date=None, days_to_earnings=None, error=str(e))

        async def fetch_yahoo() -> EarningsResult:
            try:
                yahoo_data = await asyncio.to_thread(self._fetch_yahoo_earnings, symbol)
                return create_earnings_result(
                    source="yahoo_direct",
                    earnings_date=yahoo_data.get('earnings_date'),
                    days_to_earnings=yahoo_data.get('days_to_earnings')
                )
            except Exception as e:
                return create_earnings_result(source="yahoo_direct", earnings_date=None, days_to_earnings=None, error=str(e))

        async def fetch_yfinance() -> EarningsResult:
            try:
                if self._earnings_fetcher is None:
                    self._earnings_fetcher = get_earnings_fetcher()

                fetched = await asyncio.to_thread(self._earnings_fetcher.fetch, symbol)
                if fetched and fetched.earnings_date:
                    return create_earnings_result(
                        source="yfinance",
                        earnings_date=fetched.earnings_date,
                        days_to_earnings=fetched.days_to_earnings
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
            is_safe = (aggregated.days_to_earnings or 0) >= min_days
            status = "✅ SAFE" if is_safe else "⚠️ TOO CLOSE"
            
            b.h2("Consensus Result")
            b.kv_line("Date", aggregated.consensus_date)
            b.kv_line("Days", f"{aggregated.days_to_earnings} (Min: {min_days})")
            b.kv_line("Status", status)
            b.kv_line("Confidence", f"{aggregated.confidence}%")
        else:
            b.status_warning("No earnings date found from any source.")
        
        return b.build()
    
    # =========================================================================
    # EARNINGS PREFILTER (NEW - WORKFLOW OPTIMIZATION)
    # =========================================================================
    
    @mcp_endpoint(operation="earnings prefilter")
    async def earnings_prefilter(
        self,
        min_days: int = 45,
        symbols: Optional[List[str]] = None,
        show_excluded: bool = False,
    ) -> str:
        """
        Pre-filter watchlist by earnings dates. Returns only symbols with earnings > X days away.
        Uses 4-week cache. This should be the FIRST step before any scan.
        
        Args:
            min_days: Minimum days until earnings (default: 45)
            symbols: Optional specific symbols (default: full watchlist)
            show_excluded: Show excluded symbols with their earnings dates
            
        Returns:
            Formatted Markdown with safe symbols and cache statistics
        """
        # Load symbols
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)
        
        # Initialize earnings fetcher with 4-week cache
        if self._earnings_fetcher is None:
            self._earnings_fetcher = get_earnings_fetcher()

        # Fetch earnings for all symbols (uses cache)
        start_time = datetime.now()

        safe_symbols: List[str] = []
        excluded_symbols: List[tuple] = []  # (symbol, earnings_date, days_to)
        unknown_symbols: List[str] = []
        etf_symbols: List[str] = []
        cache_hits = 0
        api_calls = 0

        for symbol in symbols:
            try:
                # ETFs haben keine Earnings - direkt als safe markieren
                if is_etf(symbol):
                    etf_symbols.append(symbol)
                    safe_symbols.append(symbol)
                    continue

                # Check cache first
                cached = self._earnings_fetcher.cache.get(symbol)
                if cached:
                    cache_hits += 1
                    earnings_date = cached.earnings_date
                    days_to = cached.days_to_earnings
                else:
                    # Fetch from API
                    api_calls += 1
                    fetched = await asyncio.to_thread(
                        self._earnings_fetcher.fetch,
                        symbol
                    )
                    earnings_date = fetched.earnings_date if fetched else None
                    days_to = fetched.days_to_earnings if fetched else None

                # Classify symbol
                if days_to is None:
                    unknown_symbols.append(symbol)
                    safe_symbols.append(symbol)  # Unknown = accept with caution
                elif days_to >= min_days:
                    safe_symbols.append(symbol)
                else:
                    excluded_symbols.append((symbol, earnings_date, days_to))
                    
            except Exception as e:
                logger.debug(f"Earnings check failed for {symbol}: {e}")
                unknown_symbols.append(symbol)
                safe_symbols.append(symbol)  # Error = accept with caution
        
        duration = (datetime.now() - start_time).total_seconds()
        
        # Build output
        b = MarkdownBuilder()
        b.h1("📅 Earnings Pre-Filter").blank()
        
        # Summary
        b.h2("Summary")
        b.kv_line("Total Symbols", len(symbols))
        b.kv_line("Min Days to Earnings", min_days)
        safe_count = len(safe_symbols) - len(unknown_symbols) - len(etf_symbols)
        b.kv_line("Safe (>= min_days)", safe_count)
        b.kv_line("ETFs (no earnings)", len(etf_symbols))
        b.kv_line("Excluded (< min_days)", len(excluded_symbols))
        b.kv_line("Unknown (no date)", len(unknown_symbols))
        b.blank()
        
        # Cache stats
        b.h2("Cache Statistics")
        b.kv_line("Cache Hits", f"{cache_hits} ({cache_hits*100//len(symbols) if symbols else 0}%)")
        b.kv_line("API Calls", api_calls)
        b.kv_line("Duration", f"{duration:.1f}s")
        b.kv_line("Cache TTL", "4 weeks")
        b.blank()
        
        # Excluded symbols (if requested)
        if show_excluded and excluded_symbols:
            b.h2("❌ Excluded Symbols")
            # Sort by days_to_earnings
            excluded_symbols.sort(key=lambda x: x[2] if x[2] else 999)
            rows = []
            for sym, date, days in excluded_symbols[:30]:  # Limit to 30
                rows.append([sym, date or "N/A", str(days) if days else "N/A"])
            b.table(["Symbol", "Earnings Date", "Days"], rows)
            if len(excluded_symbols) > 30:
                b.hint(f"... and {len(excluded_symbols) - 30} more")
            b.blank()
        
        # Safe symbols list (compact)
        b.h2("✅ Safe Symbols for Scanning")
        b.kv_line("Count", len(safe_symbols))
        
        # Group by first letter for readability
        if len(safe_symbols) <= 50:
            b.text(", ".join(sorted(safe_symbols)))
        else:
            b.text(f"First 50: {', '.join(sorted(safe_symbols)[:50])}...")
        b.blank()
        
        # Usage hint
        b.h2("Next Steps")
        b.text("Use the safe symbols list for scanning:")
        b.code(f'optionplay_scan_multi symbols={sorted(safe_symbols)[:20]}...')
        
        return b.build()
    
    # =========================================================================
    # ANALYSIS
    # =========================================================================
    
    @mcp_endpoint(operation="historical data", symbol_param="symbol")
    async def get_historical_data(self, symbol: str, days: int = 30) -> str:
        """Get historical price data."""
        symbol = validate_symbol(symbol)
        provider = await self._ensure_connected()
        
        await self._rate_limiter.acquire()
        bars = await provider.get_historical(symbol, days=days)
        self._rate_limiter.record_success()
        
        return formatters.historical.format(symbol=symbol, bars=bars or [], days_shown=10)
    
    @mcp_endpoint(operation="symbol analysis", symbol_param="symbol")
    async def analyze_symbol(self, symbol: str) -> str:
        """Perform complete analysis for a symbol (Bull-Put-Spread focus)."""
        symbol = validate_symbol(symbol)
        provider = await self._ensure_connected()

        vix = await self.get_vix()
        recommendation = get_strategy_for_vix(vix)

        quote = await self._get_quote_cached(symbol)

        await self._rate_limiter.acquire()
        historical = await provider.get_historical_for_scanner(symbol, days=260)
        self._rate_limiter.record_success()

        await self._rate_limiter.acquire()
        earnings = await provider.get_earnings_date(symbol)
        self._rate_limiter.record_success()
        
        b = MarkdownBuilder()
        b.h1(f"Complete Analysis: {symbol}").blank()
        b.kv("VIX", vix, fmt=".2f")
        b.kv("Strategy", recommendation.profile_name.upper())
        b.blank()
        
        if quote:
            b.h2("Current Price")
            b.kv_line("Last", f"${quote.last:.2f}" if quote.last else "N/A")
            b.blank()
        
        current_price = 0
        sma_200 = 0
        if historical:
            prices, volumes, highs, lows = historical
            current_price = prices[-1]
            sma_20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else current_price
            sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else current_price
            sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else current_price
            
            b.h2("Technical Indicators")
            b.kv_line("SMA 20", f"${sma_20:.2f} ({'↑' if current_price > sma_20 else '↓'})")
            b.kv_line("SMA 50", f"${sma_50:.2f} ({'↑' if current_price > sma_50 else '↓'})")
            b.kv_line("SMA 200", f"${sma_200:.2f} ({'↑' if current_price > sma_200 else '↓'})")
            b.blank()
            
            if current_price > sma_200 and current_price < sma_20:
                trend_status = "✅ **PULLBACK IN UPTREND** - Ideal for Bull-Put-Spread"
            elif current_price > sma_200:
                trend_status = "📈 Uptrend - Wait for pullback"
            else:
                trend_status = "⚠️ Below SMA 200 - Caution"
            
            b.h2("Trend Assessment")
            b.text(trend_status)
            b.blank()
        
        b.h2("Earnings Check")
        if earnings and earnings.earnings_date:
            is_safe = earnings.days_to_earnings >= recommendation.earnings_buffer_days
            # Status with warning for <60 days
            if earnings.days_to_earnings < recommendation.earnings_buffer_days:
                status = "❌ TOO CLOSE - DO NOT TRADE"
            elif earnings.days_to_earnings < 60:
                status = "⚠️ CAUTION - Earnings in <60 days"
            else:
                status = "✅ SAFE"
            b.kv_line("Date", earnings.earnings_date)
            b.kv_line("Days", f"{earnings.days_to_earnings} (Min: {recommendation.earnings_buffer_days})")
            b.kv_line("Status", status)
            if earnings.days_to_earnings < 60 and earnings.days_to_earnings >= recommendation.earnings_buffer_days:
                b.text("⚠️ **Note:** Consider shorter DTE or monitor closely")
        else:
            b.kv_line("Status", "No date available")
        
        return b.build()
    
    @mcp_endpoint(operation="expirations lookup", symbol_param="symbol")
    async def get_expirations(self, symbol: str) -> str:
        """List available options expiration dates."""
        symbol = validate_symbol(symbol)
        provider = await self._ensure_connected()
        
        await self._rate_limiter.acquire()
        expirations = await provider.get_expirations(symbol)
        self._rate_limiter.record_success()
        
        b = MarkdownBuilder()
        b.h1(f"Expiration Dates: {symbol.upper()}").blank()
        
        if not expirations:
            b.hint("No expiration dates found.")
            return b.build()
        
        today = date.today()
        rows = []
        for exp in expirations[:20]:
            dte = (exp - today).days
            exp_type = "Monthly" if 15 <= exp.day <= 21 else "Weekly"
            rows.append([str(exp), str(dte), exp_type])
        
        b.table(["Date", "DTE", "Type"], rows)
        
        return b.build()
    
    # =========================================================================
    # STRIKE RECOMMENDER
    # =========================================================================
    
    @mcp_endpoint(operation="strike recommendation", symbol_param="symbol")
    async def recommend_strikes(
        self,
        symbol: str,
        dte_min: int = 30,
        dte_max: int = 60,
        num_alternatives: int = 3,
    ) -> str:
        """
        Generate optimal strike recommendations for Bull-Put-Spreads.
        
        Analyzes support levels, Fibonacci retracements, and options chain
        to recommend optimal short/long strike combinations.
        
        Args:
            symbol: Ticker symbol
            dte_min: Minimum days to expiration (default: 30)
            dte_max: Maximum days to expiration (default: 60)
            num_alternatives: Number of alternative recommendations (default: 3)
            
        Returns:
            Formatted Markdown with strike recommendations
        """
        symbol = validate_symbol(symbol)
        provider = await self._ensure_connected()

        # 1. Get current quote (cached)
        quote = await self._get_quote_cached(symbol)

        if not quote or not quote.last:
            return f"❌ Cannot get quote for {symbol}"

        current_price = quote.last

        # 2. Get historical data for support analysis
        historical_days = 120  # Need more history for good support levels
        data = await self._fetch_historical_cached(symbol, days=historical_days)
        
        if not data:
            return f"❌ Cannot get historical data for {symbol}"
        
        prices, volumes, highs, lows = data
        
        # 3. Find support levels from swing lows
        support_levels = find_support_levels(
            lows=lows,
            lookback=90,
            window=10,
            max_levels=5
        )
        
        # Filter supports below current price
        support_levels = [s for s in support_levels if s < current_price]
        
        # 4. Calculate Fibonacci retracements
        recent_high = max(highs[-60:]) if len(highs) >= 60 else max(highs)
        recent_low = min(lows[-60:]) if len(lows) >= 60 else min(lows)
        
        fib_levels_dict = calculate_fibonacci(recent_high, recent_low)
        fib_levels = [
            {"level": v, "fib": k}
            for k, v in fib_levels_dict.items()
            if v < current_price  # Only levels below current price
        ]
        
        # 5. Get options chain for accurate Greeks
        await self._rate_limiter.acquire()
        options = await provider.get_option_chain(
            symbol,
            dte_min=dte_min,
            dte_max=dte_max,
            right="P"
        )
        self._rate_limiter.record_success()
        
        # Convert to dict format expected by StrikeRecommender
        options_data = None
        if options:
            options_data = [
                {
                    "strike": opt.strike,
                    "right": "P",
                    "bid": opt.bid,
                    "ask": opt.ask,
                    "delta": opt.delta,
                    "iv": opt.implied_volatility,
                    "dte": (opt.expiry - date.today()).days,
                }
                for opt in options
            ]
        
        # 6. Get VIX regime for dynamic spread calculation
        vix = await self.get_vix()
        regime = self._vix_selector.get_regime(vix) if vix else None

        # 7. Get recommendations
        recommender = StrikeRecommender()

        # Primary recommendation
        primary = recommender.get_recommendation(
            symbol=symbol,
            current_price=current_price,
            support_levels=support_levels,
            options_data=options_data,
            fib_levels=fib_levels,
            dte=dte_min + (dte_max - dte_min) // 2,  # Mid-point DTE
            regime=regime  # VIX-based regime for dynamic spread width
        )
        
        # Alternative recommendations
        alternatives = recommender.get_multiple_recommendations(
            symbol=symbol,
            current_price=current_price,
            support_levels=support_levels,
            options_data=options_data,
            fib_levels=fib_levels,
            num_alternatives=num_alternatives
        )

        # 8. Build output
        b = MarkdownBuilder()
        b.h1(f"🎯 Strike Recommendation: {symbol}").blank()

        # Current price and context
        b.kv_line("Current Price", f"${current_price:.2f}")
        b.kv_line("DTE Range", f"{dte_min}-{dte_max} days")
        if vix and regime:
            b.kv_line("VIX", f"{vix:.1f} ({regime.value})")
        b.blank()
        
        # Support levels found
        if support_levels:
            b.h2("📊 Support Levels")
            support_str = ", ".join([f"${s:.2f}" for s in sorted(support_levels, reverse=True)])
            b.text(support_str)
            b.blank()
        
        # Fibonacci levels
        if fib_levels:
            b.h2("📐 Fibonacci Retracements")
            fib_strs = []
            for fl in sorted(fib_levels, key=lambda x: x["level"], reverse=True)[:4]:
                fib_strs.append(f"{fl['fib']}: ${fl['level']:.2f}")
            b.text(", ".join(fib_strs))
            b.blank()
        
        # Primary recommendation
        b.h2("⭐ Primary Recommendation")
        quality_icons = {
            StrikeQuality.EXCELLENT: "🟢",
            StrikeQuality.GOOD: "🟡",
            StrikeQuality.ACCEPTABLE: "🟠",
            StrikeQuality.POOR: "🔴",
        }
        quality_icon = quality_icons.get(primary.quality, "⚪")
        
        b.kv_line("Short Strike", f"${primary.short_strike:.2f}")
        b.kv_line("Long Strike", f"${primary.long_strike:.2f}")
        b.kv_line("Spread Width", f"${primary.spread_width:.2f}")
        b.kv_line("Reason", primary.short_strike_reason)
        b.blank()
        
        # Metrics
        if primary.estimated_credit:
            b.h3("Expected Metrics")
            b.kv_line("Est. Credit", f"${primary.estimated_credit:.2f}")
            if primary.max_profit:
                b.kv_line("Max Profit", f"${primary.max_profit:.2f}")
            if primary.max_loss:
                b.kv_line("Max Loss", f"${primary.max_loss:.2f}")
            if primary.break_even:
                b.kv_line("Break-Even", f"${primary.break_even:.2f}")
            if primary.prob_profit:
                b.kv_line("P(Profit)", f"{primary.prob_profit:.0f}%")
            if primary.estimated_delta:
                b.kv_line("Short Delta", f"{primary.estimated_delta:.2f}")
            b.blank()
        
        # Quality assessment
        b.h3("Quality Assessment")
        b.kv_line("Quality", f"{quality_icon} {primary.quality.value.upper()}")
        b.kv_line("Confidence", f"{primary.confidence_score:.0f}/100")
        
        if primary.warnings:
            b.blank()
            b.h3("⚠️ Warnings")
            for warning in primary.warnings:
                b.text(f"• {warning}")
        b.blank()
        
        # Alternatives
        if alternatives and len(alternatives) > 1:
            b.h2("🔄 Alternatives")
            rows = []
            for i, alt in enumerate(alternatives[:num_alternatives], 1):
                q_icon = quality_icons.get(alt.quality, "⚪")
                credit_str = f"${alt.estimated_credit:.2f}" if alt.estimated_credit else "N/A"
                rows.append([
                    str(i),
                    f"${alt.short_strike:.0f}/${alt.long_strike:.0f}",
                    f"${alt.spread_width:.0f}",
                    credit_str,
                    f"{q_icon} {alt.confidence_score:.0f}"
                ])
            b.table(["#", "Strikes", "Width", "Credit", "Score"], rows)

        return b.build()

    # =========================================================================
    # DETAILED REPORT
    # =========================================================================

    @mcp_endpoint(operation="detailed report generation", symbol_param="symbol")
    async def generate_report(
        self,
        symbol: str,
        strategy: Optional[str] = None,
        include_options: bool = True,
        include_news: bool = True,
    ) -> str:
        """
        Generate a detailed PDF report for a trading candidate.

        Creates a comprehensive PDF with:
        - Summary header with key findings
        - Full score breakdown for all components
        - Technical levels (Support/Resistance/Fibonacci)
        - Options setup (Strikes, Greeks, P(Profit))
        - News section (via Yahoo Finance)

        Args:
            symbol: Ticker symbol
            strategy: Specific strategy to analyze (pullback, bounce, breakout, earnings_dip)
                     If not specified, uses best matching strategy
            include_options: Include options strike recommendations (default: True)
            include_news: Include recent news (default: True)

        Returns:
            Path to generated PDF file
        """
        symbol = validate_symbol(symbol)

        # 1. Get historical data
        provider = await self._ensure_connected()
        historical_days = max(self._config.settings.performance.historical_days, 260)
        data = await self._fetch_historical_cached(symbol, days=historical_days)

        if not data:
            return f"❌ No historical data available for {symbol}"

        prices, volumes, highs, lows = data

        # 2. Analyze with multi-strategy scanner
        scanner = self._get_multi_scanner(min_score=0)

        # Load earnings date into scanner cache
        if self._earnings_fetcher is None:
            self._earnings_fetcher = get_earnings_fetcher()
        cached_earnings = self._earnings_fetcher.cache.get(symbol)
        earnings_days = None
        if cached_earnings and cached_earnings.earnings_date:
            try:
                earnings_date = date.fromisoformat(cached_earnings.earnings_date)
                scanner.set_earnings_date(symbol, earnings_date)
                earnings_days = (earnings_date - date.today()).days
            except (ValueError, TypeError):
                pass

        signals = scanner.analyze_symbol(symbol, prices, volumes, highs, lows)

        if not signals:
            return f"❌ No signals found for {symbol}"

        # 3. Select best signal (or specific strategy)
        if strategy:
            strategy = strategy.lower().replace('-', '_')
            matching = [s for s in signals if s.strategy == strategy]
            if not matching:
                available = ", ".join(set(s.strategy for s in signals))
                return f"❌ Strategy '{strategy}' not found. Available: {available}"
            candidate = matching[0]
        else:
            candidate = max(signals, key=lambda x: x.score)

        # 4. Get quote for current price
        quote = await self._get_quote_cached(symbol)

        # 5. Build PullbackCandidate-like object for PDF generator
        # Get breakdown from signal details
        breakdown = candidate.details.get('breakdown') if hasattr(candidate, 'details') else None

        # Create a simple candidate object with the data we have
        from dataclasses import dataclass, field
        from typing import Dict, List

        @dataclass
        class ReportCandidate:
            symbol: str
            strategy: str
            score: float
            current_price: float
            score_breakdown: Any = None
            support_levels: List[float] = field(default_factory=list)
            resistance_levels: List[float] = field(default_factory=list)
            fib_levels: Dict[str, float] = field(default_factory=dict)

        # Extract support/resistance from historical data
        support_levels_raw = find_support_levels(lows=lows, lookback=90, window=10, max_levels=5)
        current_price = quote.last if quote else prices[-1]
        support_levels = [s for s in support_levels_raw if s < current_price]
        resistance_levels = [s for s in support_levels_raw if s > current_price]

        # Calculate Fibonacci
        recent_high = max(highs[-60:]) if len(highs) >= 60 else max(highs)
        recent_low = min(lows[-60:]) if len(lows) >= 60 else min(lows)
        fib_levels = calculate_fibonacci(recent_high, recent_low)

        # Build score breakdown from signal details
        score_breakdown = None
        if hasattr(candidate, 'details') and isinstance(candidate.details, dict):
            bd = candidate.details.get('breakdown', {})
            if bd:
                from .models.candidates import ScoreBreakdown
                score_breakdown = ScoreBreakdown(
                    rsi_score=bd.get('rsi', {}).get('score', 0),
                    rsi_value=bd.get('rsi', {}).get('value', 0),
                    rsi_reason=bd.get('rsi', {}).get('reason', ''),
                    support_score=bd.get('support', {}).get('score', 0),
                    support_level=bd.get('support', {}).get('level'),
                    support_distance_pct=bd.get('support', {}).get('distance_pct', 0),
                    support_strength=bd.get('support', {}).get('strength', ''),
                    support_touches=bd.get('support', {}).get('touches', 0),
                    support_reason=bd.get('support', {}).get('reason', ''),
                    fibonacci_score=bd.get('fibonacci', {}).get('score', 0),
                    fib_level=bd.get('fibonacci', {}).get('level'),
                    fib_reason=bd.get('fibonacci', {}).get('reason', ''),
                    ma_score=bd.get('moving_averages', {}).get('score', 0),
                    price_vs_sma20=bd.get('moving_averages', {}).get('vs_sma20', ''),
                    price_vs_sma200=bd.get('moving_averages', {}).get('vs_sma200', ''),
                    ma_reason=bd.get('moving_averages', {}).get('reason', ''),
                    trend_strength_score=bd.get('trend_strength', {}).get('score', 0),
                    trend_alignment=bd.get('trend_strength', {}).get('alignment', ''),
                    sma20_slope=bd.get('trend_strength', {}).get('sma20_slope', 0),
                    trend_reason=bd.get('trend_strength', {}).get('reason', ''),
                    volume_score=bd.get('volume', {}).get('score', 0),
                    volume_ratio=bd.get('volume', {}).get('ratio', 0),
                    volume_trend=bd.get('volume', {}).get('trend', ''),
                    volume_reason=bd.get('volume', {}).get('reason', ''),
                    macd_score=bd.get('macd', {}).get('score', 0),
                    macd_signal=bd.get('macd', {}).get('signal'),
                    macd_histogram=bd.get('macd', {}).get('histogram', 0),
                    macd_reason=bd.get('macd', {}).get('reason', ''),
                    stoch_score=bd.get('stochastic', {}).get('score', 0),
                    stoch_signal=bd.get('stochastic', {}).get('signal'),
                    stoch_k=bd.get('stochastic', {}).get('k', 0),
                    stoch_d=bd.get('stochastic', {}).get('d', 0),
                    stoch_reason=bd.get('stochastic', {}).get('reason', ''),
                    keltner_score=bd.get('keltner', {}).get('score', 0),
                    keltner_position=bd.get('keltner', {}).get('position', ''),
                    keltner_percent=bd.get('keltner', {}).get('percent', 0),
                    keltner_reason=bd.get('keltner', {}).get('reason', ''),
                    total_score=candidate.score,
                )

        report_candidate = ReportCandidate(
            symbol=symbol,
            strategy=candidate.strategy,
            score=candidate.score,
            current_price=current_price,
            score_breakdown=score_breakdown,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            fib_levels=fib_levels,
        )

        # 6. Get options data (if requested)
        options_data = None
        if include_options:
            try:
                # Use StrikeRecommender for options data
                recommender = StrikeRecommender()

                # Get options chain
                await self._rate_limiter.acquire()
                options = await provider.get_option_chain(symbol, dte_min=30, dte_max=60, right="P")
                self._rate_limiter.record_success()

                options_dict = None
                if options:
                    options_dict = [
                        {
                            "strike": opt.strike,
                            "right": "P",
                            "bid": opt.bid,
                            "ask": opt.ask,
                            "delta": opt.delta,
                            "iv": opt.implied_volatility,
                            "dte": (opt.expiry - date.today()).days,
                        }
                        for opt in options
                    ]

                vix = await self.get_vix()
                regime = self._vix_selector.get_regime(vix) if vix else None

                rec = recommender.get_recommendation(
                    symbol=symbol,
                    current_price=current_price,
                    support_levels=support_levels,
                    options_data=options_dict,
                    fib_levels=[{"level": v, "fib": k} for k, v in fib_levels.items() if v < current_price],
                    dte=45,
                    regime=regime,
                )

                if rec:
                    options_data = {
                        'recommendations': [{
                            'short_strike': rec.short_strike,
                            'long_strike': rec.long_strike,
                            'width': rec.spread_width,
                            'credit': rec.estimated_credit or 0,
                            'short_delta': rec.estimated_delta or 0,
                            'short_premium': 0,  # Not available from recommender
                            'long_delta': 0,
                            'long_premium': 0,
                            'probability_of_profit': rec.prob_profit or 0,
                            'dte': 45,
                        }]
                    }
            except Exception as e:
                logger.warning(f"Failed to get options data for {symbol}: {e}")

        # 7. Get news (if requested)
        news = None
        if include_news:
            try:
                from .data_providers.yahoo_news import get_stock_news
                news = get_stock_news(symbol, max_items=5)
            except Exception as e:
                logger.warning(f"Failed to get news for {symbol}: {e}")

        # 8. Prepare historical data for Volume Profile chart
        import pandas as pd

        # Fetch full historical bars (with Open prices) for Volume Profile
        full_bars = await provider.get_historical(symbol, days=130)
        if full_bars and len(full_bars) >= 10:
            # Use actual OHLCV data from bars
            historical_df = pd.DataFrame({
                'Open': [bar.open for bar in full_bars],
                'High': [bar.high for bar in full_bars],
                'Low': [bar.low for bar in full_bars],
                'Close': [bar.close for bar in full_bars],
                'Volume': [bar.volume for bar in full_bars],
            })
        else:
            # Fallback: Create DataFrame with Close as Open approximation
            chart_days = min(130, len(prices))
            historical_df = pd.DataFrame({
                'Open': prices[-chart_days:],
                'High': highs[-chart_days:],
                'Low': lows[-chart_days:],
                'Close': prices[-chart_days:],
                'Volume': volumes[-chart_days:],
            })

        # 9. Generate PDF
        # TODO: Implement new WeasyPrint-based report generator
        # Old ReportLab implementation removed - new Apple-style HTML/PDF system pending

        # Return placeholder message until new system is implemented
        b = MarkdownBuilder()
        b.h1(f"📄 Report: {symbol}").blank()
        b.status_warn("PDF generation temporarily disabled - new report system in development")
        b.blank()
        b.kv_line("Strategy", candidate.strategy.replace('_', ' ').title())
        b.kv_line("Score", f"{candidate.score:.1f}/16")
        if earnings_days:
            b.kv_line("Earnings", f"{earnings_days} days")
        b.blank()
        b.hint("Open the PDF to view the detailed analysis.")

        return b.build()

    # =========================================================================
    # SPREAD ANALYSIS
    # =========================================================================

    @mcp_endpoint(operation="spread analysis", symbol_param="symbol")
    async def analyze_spread(
        self,
        symbol: str,
        short_strike: float,
        long_strike: float,
        net_credit: float,
        dte: int,
        contracts: int = 1,
    ) -> str:
        """
        Analyze a Bull-Put-Spread with comprehensive risk/reward metrics.

        Provides detailed analysis including:
        - Max profit/loss calculation
        - Break-even analysis
        - Risk/Reward ratio
        - Probability estimates
        - P&L scenarios at various prices
        - Exit recommendations (profit targets, stop-loss)

        Args:
            symbol: Ticker symbol
            short_strike: Strike price of short put
            long_strike: Strike price of long put (must be lower than short)
            net_credit: Net credit received per share
            dte: Days to expiration
            contracts: Number of contracts (default: 1)

        Returns:
            Formatted Markdown with spread analysis
        """
        symbol = validate_symbol(symbol)

        # Get current quote (cached)
        quote = await self._get_quote_cached(symbol)

        if not quote or not quote.last:
            return f"❌ Cannot get quote for {symbol}"

        current_price = quote.last

        # Validate spread parameters
        if short_strike <= long_strike:
            return "❌ Short strike must be higher than long strike"

        if short_strike >= current_price:
            return f"❌ Short strike (${short_strike}) should be below current price (${current_price:.2f})"

        if net_credit <= 0:
            return "❌ Net credit must be positive"

        # Create spread parameters
        try:
            params = BullPutSpreadParams(
                symbol=symbol,
                current_price=current_price,
                short_strike=short_strike,
                long_strike=long_strike,
                net_credit=net_credit,
                dte=dte,
                contracts=contracts
            )
        except ValueError as e:
            return f"❌ Invalid parameters: {e}"

        # Analyze spread
        analyzer = SpreadAnalyzer()
        analysis = analyzer.analyze(params)

        # Build output
        b = MarkdownBuilder()
        b.h1(f"📊 Spread Analysis: {symbol}").blank()

        # Spread details
        b.h2("📋 Spread Details")
        b.kv_line("Current Price", f"${current_price:.2f}")
        b.kv_line("Short Strike", f"${short_strike:.2f} ({analysis.distance_to_short_strike:+.1f}% OTM)")
        b.kv_line("Long Strike", f"${long_strike:.2f}")
        b.kv_line("Spread Width", f"${analysis.spread_width:.2f}")
        b.kv_line("Net Credit", f"${net_credit:.2f} x {contracts}")
        b.kv_line("DTE", f"{dte} days")
        b.blank()

        # Profit/Loss metrics
        b.h2("💰 Profit/Loss")
        b.kv_line("Max Profit", f"${analysis.max_profit:,.2f} ({analysis.credit_to_width_ratio:.0f}% of width)")
        b.kv_line("Max Loss", f"${analysis.max_loss:,.2f}")
        b.kv_line("Risk/Reward", f"1:{analysis.risk_reward_ratio:.2f}")
        b.kv_line("Break-Even", f"${analysis.break_even:.2f} ({analysis.distance_to_break_even:+.1f}%)")
        b.blank()

        # Probabilities
        b.h2("📈 Probabilities")
        b.kv_line("P(Profit)", f"{analysis.prob_profit:.0f}%")
        b.kv_line("P(Max Profit)", f"{analysis.prob_max_profit:.0f}%")
        b.kv_line("Expected Value", f"${analysis.expected_value:+.2f}")

        # Risk level with icon
        risk_icons = {
            "low": "🟢",
            "moderate": "🟡",
            "high": "🟠",
            "very_high": "🔴"
        }
        risk_icon = risk_icons.get(analysis.risk_level.value, "⚪")
        b.kv_line("Risk Level", f"{risk_icon} {analysis.risk_level.value.upper()}")
        b.blank()

        # Greeks (if available)
        if analysis.net_theta and analysis.theta_per_day:
            b.h2("📐 Greeks")
            if analysis.net_delta:
                b.kv_line("Net Delta", f"{analysis.net_delta:.3f}")
            b.kv_line("Theta/Day", f"${analysis.theta_per_day:.2f}")
            b.blank()

        # P&L Scenarios
        if analysis.scenarios:
            b.h2("🎯 P&L Scenarios (at Expiration)")
            rows = []
            for scenario in analysis.scenarios:
                status_icons = {
                    "max_profit": "✅",
                    "profit": "🟢",
                    "loss": "🔴",
                    "max_loss": "❌"
                }
                icon = status_icons.get(scenario.status, "")
                rows.append([
                    f"${scenario.price:.2f}",
                    f"${scenario.pnl_total:+,.2f}",
                    f"{scenario.pnl_percent:+.0f}%",
                    f"{icon} {scenario.status}"
                ])
            b.table(["Price", "P&L", "% Max", "Status"], rows)
            b.blank()

        # Warnings
        if analysis.warnings:
            b.h2("⚠️ Warnings")
            for warning in analysis.warnings:
                b.text(f"• {warning}")
            b.blank()

        # Recommendations
        if analysis.recommendations:
            b.h2("💡 Recommendations")
            for rec in analysis.recommendations:
                b.text(f"• {rec}")

        return b.build()

    @mcp_endpoint(operation="monte carlo simulation", symbol_param="symbol")
    async def run_monte_carlo(
        self,
        symbol: str,
        short_strike: float,
        long_strike: float,
        net_credit: float,
        dte: int = 45,
        num_simulations: int = 500,
        volatility: Optional[float] = None,
    ) -> str:
        """
        Run Monte Carlo simulation for a Bull-Put-Spread.

        Simulates multiple price paths to estimate probability of outcomes.

        Args:
            symbol: Ticker symbol
            short_strike: Strike price of short put
            long_strike: Strike price of long put
            net_credit: Net credit received per share
            dte: Days to expiration (default: 45)
            num_simulations: Number of simulations (default: 500, max: 2000)
            volatility: Optional override for volatility (e.g., 0.30 = 30%)

        Returns:
            Formatted Markdown with simulation results
        """
        symbol = validate_symbol(symbol)
        # Get current quote (cached)
        quote = await self._get_quote_cached(symbol)

        if not quote or not quote.last:
            return f"❌ Cannot get quote for {symbol}"

        current_price = quote.last

        # Validate parameters
        if short_strike <= long_strike:
            return "❌ Short strike must be higher than long strike"

        if short_strike >= current_price:
            return f"❌ Short strike (${short_strike}) should be below current price (${current_price:.2f})"

        # Limit simulations
        num_simulations = min(2000, max(100, num_simulations))

        # Estimate volatility from historical data if not provided
        if volatility is None:
            data = await self._fetch_historical_cached(symbol, days=60)
            if data:
                prices, _, _, _ = data
                volatility = PriceSimulator.estimate_volatility(prices)
            else:
                volatility = 0.25  # Default 25%

        # Run simulation
        simulator = TradeSimulator()
        results = simulator.run_monte_carlo(
            symbol=symbol,
            entry_price=current_price,
            short_strike=short_strike,
            long_strike=long_strike,
            net_credit=net_credit,
            dte=dte,
            volatility=volatility,
            num_simulations=num_simulations,
        )

        # Build output
        b = MarkdownBuilder()
        b.h1(f"🎲 Monte Carlo Simulation: {symbol}").blank()

        # Parameters
        b.h2("📋 Parameters")
        b.kv_line("Current Price", f"${current_price:.2f}")
        b.kv_line("Short Strike", f"${short_strike:.2f}")
        b.kv_line("Long Strike", f"${long_strike:.2f}")
        b.kv_line("Net Credit", f"${net_credit:.2f}")
        b.kv_line("DTE", f"{dte} days")
        b.kv_line("Volatility", f"{volatility * 100:.1f}%")
        b.kv_line("Simulations", f"{num_simulations:,}")
        b.blank()

        # Results
        b.h2("📊 Results")
        b.kv_line("Win Rate", f"{results['win_rate']:.1f}%")
        b.kv_line("Avg P&L", f"${results['avg_pnl']:+,.2f}")
        b.kv_line("Median P&L", f"${results['median_pnl']:+,.2f}")
        b.kv_line("Std Dev", f"${results['std_pnl']:,.2f}")
        b.blank()

        b.kv_line("Best Case", f"${results['max_pnl']:+,.2f}")
        b.kv_line("Worst Case", f"${results['min_pnl']:+,.2f}")
        b.kv_line("Avg Hold Days", f"{results['avg_hold_days']:.1f}")
        b.blank()

        # Percentiles
        b.h2("📈 P&L Distribution")
        percentiles = results.get("percentiles", {})
        rows = [
            ["5th", f"${percentiles.get('p5', 0):+,.2f}"],
            ["25th", f"${percentiles.get('p25', 0):+,.2f}"],
            ["50th (Median)", f"${percentiles.get('p50', 0):+,.2f}"],
            ["75th", f"${percentiles.get('p75', 0):+,.2f}"],
            ["95th", f"${percentiles.get('p95', 0):+,.2f}"],
        ]
        b.table(["Percentile", "P&L"], rows)
        b.blank()

        # Outcome Distribution
        b.h2("🎯 Outcome Distribution")
        outcomes = results.get("outcome_distribution", {})
        total = sum(outcomes.values())
        if total > 0:
            outcome_rows = []
            outcome_labels = {
                "profit_target": "✅ Profit Target",
                "expiration": "📅 Expiration",
                "stop_loss": "🛑 Stop Loss",
                "max_loss": "❌ Max Loss",
            }
            for key, label in outcome_labels.items():
                count = outcomes.get(key, 0)
                pct = (count / total) * 100
                outcome_rows.append([label, str(count), f"{pct:.1f}%"])
            b.table(["Outcome", "Count", "%"], outcome_rows)

        return b.build()

    @sync_endpoint(operation="backtest quick")
    def run_quick_backtest(
        self,
        symbols: Optional[List[str]] = None,
        days: int = 180,
        profit_target_pct: float = 50.0,
        stop_loss_pct: float = 200.0,
    ) -> str:
        """
        Run a quick backtest with simulated data.

        Uses simplified assumptions for rapid testing.

        Args:
            symbols: List of symbols (default: ["AAPL", "MSFT", "GOOGL"])
            days: Number of days to simulate (default: 180)
            profit_target_pct: Profit target as % of max profit (default: 50)
            stop_loss_pct: Stop loss as % of credit (default: 200)

        Returns:
            Formatted Markdown with backtest results
        """
        if symbols is None:
            symbols = ["AAPL", "MSFT", "GOOGL"]

        symbols = validate_symbols(symbols, skip_invalid=True)[:5]  # Max 5 symbols

        # Create simulated historical data
        import random
        from datetime import timedelta

        start_date = date.today() - timedelta(days=days)
        end_date = date.today()

        historical_data = {}
        for symbol in symbols:
            base_price = random.uniform(100, 300)
            prices = []
            current = base_price

            current_date = start_date
            while current_date <= end_date:
                if current_date.weekday() < 5:  # Weekdays only
                    # Random walk
                    change = random.gauss(0, 0.015) * current
                    current = max(current + change, base_price * 0.5)
                    prices.append({
                        "date": current_date.isoformat(),
                        "open": current * random.uniform(0.99, 1.01),
                        "high": current * random.uniform(1.0, 1.02),
                        "low": current * random.uniform(0.98, 1.0),
                        "close": current,
                        "volume": random.randint(1000000, 10000000),
                    })
                current_date += timedelta(days=1)

            historical_data[symbol] = prices

        # Create config
        config = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            profit_target_pct=profit_target_pct,
            stop_loss_pct=stop_loss_pct,
            min_pullback_score=5.0,
        )

        # Run backtest
        engine = BacktestEngine(config)
        result = engine.run_sync(
            symbols=symbols,
            historical_data=historical_data,
        )

        # Build output
        b = MarkdownBuilder()
        b.h1("📊 Quick Backtest Results").blank()

        # Config
        b.h2("⚙️ Configuration")
        b.kv_line("Period", f"{start_date} to {end_date}")
        b.kv_line("Symbols", ", ".join(symbols))
        b.kv_line("Initial Capital", f"${config.initial_capital:,.2f}")
        b.kv_line("Profit Target", f"{profit_target_pct}%")
        b.kv_line("Stop Loss", f"{stop_loss_pct}%")
        b.blank()

        # Summary
        b.h2("📈 Performance")
        b.kv_line("Total Trades", str(result.total_trades))
        b.kv_line("Win Rate", f"{result.win_rate:.1f}%")
        b.kv_line("Total P&L", f"${result.total_pnl:+,.2f}")
        return_pct = (result.total_pnl / config.initial_capital) * 100
        b.kv_line("Return", f"{return_pct:+.2f}%")
        b.kv_line("Profit Factor", f"{result.profit_factor:.2f}")
        b.blank()

        b.kv_line("Avg Win", f"${result.avg_win:,.2f}")
        b.kv_line("Avg Loss", f"${result.avg_loss:,.2f}")
        b.kv_line("Avg Hold Days", f"{result.avg_hold_days:.1f}")
        b.blank()

        # Risk
        b.h2("⚠️ Risk Metrics")
        b.kv_line("Max Drawdown", f"${result.max_drawdown:,.2f} ({result.max_drawdown_pct:.1f}%)")
        b.kv_line("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
        b.blank()

        # Outcome Distribution
        if result.outcome_distribution:
            b.h2("🎯 Outcomes")
            for outcome, count in sorted(result.outcome_distribution.items()):
                pct = (count / result.total_trades * 100) if result.total_trades > 0 else 0
                b.kv_line(outcome, f"{count} ({pct:.1f}%)")
            b.blank()

        # Recent trades
        if result.trades:
            b.h2("📋 Recent Trades")
            rows = []
            for trade in result.trades[-10:]:  # Last 10 trades
                outcome_icon = "✅" if trade.is_winner else "❌"
                rows.append([
                    trade.symbol,
                    str(trade.entry_date),
                    f"${trade.realized_pnl:+,.0f}",
                    f"{trade.hold_days}d",
                    f"{outcome_icon} {trade.outcome.value}",
                ])
            b.table(["Symbol", "Entry", "P&L", "Days", "Outcome"], rows)

        b.blank()
        b.text("*Note: This uses simulated data for demonstration purposes.*")

        return b.build()

    @sync_endpoint(operation="watchlist info")
    def get_watchlist_info(self) -> str:
        """Show information about the current watchlist."""
        loader = get_watchlist_loader()
        sectors = loader.get_all_sectors()
        all_symbols = loader.get_all_symbols()
        
        b = MarkdownBuilder()
        b.h1("Watchlist Overview").blank()
        b.kv("Total Symbols", len(all_symbols))
        b.kv("Sectors", len(sectors))
        
        return b.build()
    
    @sync_endpoint(operation="cache stats")
    def get_cache_stats(self) -> str:
        """Show cache statistics."""
        cache_stats = self._historical_cache.stats()
        quote_cache_stats = self._get_quote_cache_stats()

        b = MarkdownBuilder()
        b.h1("Cache Statistics").blank()

        b.h2("Historical Data Cache")
        b.kv_line("Entries", f"{cache_stats['entries']}/{cache_stats['max_entries']}")
        b.kv_line("Hit Rate", f"{cache_stats['hit_rate_percent']}%")
        b.kv_line("TTL", f"{cache_stats['ttl_seconds']}s")
        b.blank()

        b.h2("Quote Cache")
        b.kv_line("Entries", quote_cache_stats['entries'])
        b.kv_line("Hits", quote_cache_stats['hits'])
        b.kv_line("Misses", quote_cache_stats['misses'])
        b.kv_line("Hit Rate", f"{quote_cache_stats['hit_rate_percent']}%")
        b.blank()

        dedup_stats = self._deduplicator.stats()
        b.h2("Request Deduplication")
        b.kv_line("Total Requests", dedup_stats['total_requests'])
        b.kv_line("Actual API Calls", dedup_stats['actual_calls'])
        b.kv_line("Deduplicated", dedup_stats['deduplicated'])
        b.kv_line("Dedup Rate", f"{dedup_stats['dedup_rate_percent']}%")
        b.kv_line("In-Flight", dedup_stats['in_flight'])
        b.blank()

        scan_cache_stats = self._get_scan_cache_stats()
        b.h2("Scan Results Cache")
        b.kv_line("Entries", scan_cache_stats['entries'])
        b.kv_line("Hits", scan_cache_stats['hits'])
        b.kv_line("Misses", scan_cache_stats['misses'])
        b.kv_line("Hit Rate", f"{scan_cache_stats['hit_rate_percent']}%")
        b.kv_line("TTL", f"{scan_cache_stats['ttl_seconds']}s")

        return b.build()
    
    # =========================================================================
    # IBKR BRIDGE FEATURES
    # =========================================================================
    
    @mcp_endpoint(operation="IBKR status check")
    async def get_ibkr_status(self) -> str:
        """Check IBKR Bridge status."""
        b = MarkdownBuilder()
        b.h1("IBKR Bridge Status").blank()
        
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            b.status_error("**Not available** - ib_insync not installed.")
            return b.build()
        
        is_available = await self._ibkr_bridge.is_available(force_check=True)
        b.kv("Status", "✅ Available" if is_available else "❌ Not available")
        b.kv("Host", f"{self._ibkr_bridge.host}:{self._ibkr_bridge.port}")
        
        return b.build()
    
    @mcp_endpoint(operation="news fetch")
    async def get_news(self, symbols: List[str], days: int = 5) -> str:
        """Get news headlines from IBKR for symbols."""
        symbols = validate_symbols(symbols, skip_invalid=True)
        
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "❌ IBKR Bridge not available."
        
        if not await self._ibkr_bridge.is_available():
            return "❌ TWS/Gateway not reachable."
        
        return await self._ibkr_bridge.get_news_formatted(symbols, days)
    
    @mcp_endpoint(operation="max pain calculation")
    async def get_max_pain(self, symbols: List[str]) -> str:
        """Calculate Max Pain for symbols via IBKR."""
        symbols = validate_symbols(symbols, skip_invalid=True)
        
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "❌ IBKR Bridge not available."
        
        if not await self._ibkr_bridge.is_available():
            return "❌ TWS/Gateway not reachable."
        
        return await self._ibkr_bridge.get_max_pain_formatted(symbols)
    
    @mcp_endpoint(operation="IBKR portfolio fetch")
    async def get_ibkr_portfolio(self) -> str:
        """Get portfolio positions from IBKR/TWS."""
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "❌ IBKR Bridge not available."
        
        if not await self._ibkr_bridge.is_available():
            return "❌ TWS/Gateway not reachable."
        
        return await self._ibkr_bridge.get_portfolio_formatted()
    
    @mcp_endpoint(operation="IBKR spreads fetch")
    async def get_ibkr_spreads(self) -> str:
        """Get identified spread positions from IBKR/TWS."""
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "❌ IBKR Bridge not available."
        
        if not await self._ibkr_bridge.is_available():
            return "❌ TWS/Gateway not reachable."
        
        return await self._ibkr_bridge.get_spreads_formatted()
    
    @mcp_endpoint(operation="IBKR VIX fetch")
    async def get_ibkr_vix(self) -> str:
        """Get live VIX from IBKR."""
        b = MarkdownBuilder()
        
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            vix = await self.get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata (IBKR not available)")
            return b.build()
        
        if not await self._ibkr_bridge.is_available():
            vix = await self.get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata (TWS not connected)")
            return b.build()
        
        vix_data = await self._ibkr_bridge.get_vix()
        
        if vix_data:
            b.h1("VIX").blank()
            b.kv("VIX", vix_data["value"], fmt=".2f")
            b.kv("Source", f"IBKR ({vix_data['source']})")
        else:
            vix = await self.get_vix()
            b.h1("VIX").blank()
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Source", "Yahoo/Marketdata")
        
        return b.build()
    
    @mcp_endpoint(operation="IBKR watchlist quotes")
    async def get_ibkr_quotes(
        self,
        symbols: Optional[List[str]] = None,
        batch_size: int = 50,
        pause_seconds: int = 60
    ) -> str:
        """Get quotes for watchlist symbols from IBKR in batches."""
        if not IBKR_AVAILABLE or not self._ibkr_bridge:
            return "❌ IBKR Bridge not available."
        
        if not await self._ibkr_bridge.is_available():
            return "❌ TWS/Gateway not reachable."
        
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()
        else:
            symbols = validate_symbols(symbols, skip_invalid=True)
        
        return await self._ibkr_bridge.get_quotes_batch_formatted(symbols, batch_size, pause_seconds)
    
    # =========================================================================
    # HEALTH CHECK
    # =========================================================================
    
    @mcp_endpoint(operation="health check")
    async def health_check(self) -> str:
        """Get server status."""
        cfg = get_config()
        scanner_cfg = cfg.settings.scanner
        loader = get_watchlist_loader()

        ibkr_host = None
        ibkr_port = None
        if IBKR_AVAILABLE and self._ibkr_bridge:
            ibkr_host = self._ibkr_bridge.host
            ibkr_port = self._ibkr_bridge.port

        # Tradier info
        tradier_available = bool(self._tradier_api_key)
        tradier_environment = None
        if tradier_available:
            tradier_environment = cfg.settings.tradier.environment

        data = HealthCheckData(
            version=self.VERSION,
            api_key_masked=self.api_key_masked,
            connected=self._connected,
            current_vix=self._current_vix,
            vix_updated=self._vix_updated,
            watchlist_symbols=len(loader.get_all_symbols()),
            watchlist_sectors=len(loader.get_all_sectors()),
            cache_stats=self._historical_cache.stats(),
            circuit_breaker_stats=self._circuit_breaker.stats(),
            rate_limiter_stats=self._rate_limiter.stats(),
            scanner_config=scanner_cfg,
            ibkr_available=IBKR_AVAILABLE and self._ibkr_bridge is not None,
            ibkr_host=ibkr_host,
            ibkr_port=ibkr_port,
            metrics_stats=metrics.to_dict(),
            tradier_available=tradier_available,
            tradier_connected=self._tradier_connected,
            tradier_api_key_masked=mask_api_key(self._tradier_api_key) if self._tradier_api_key else None,
            tradier_environment=tradier_environment,
        )

        return formatters.health_check.format(data)
    
    # =========================================================================
    # PORTFOLIO MANAGEMENT
    # =========================================================================
    
    @sync_endpoint(operation="portfolio summary")
    def portfolio_summary(self) -> str:
        """Get portfolio summary with P&L statistics."""
        portfolio = get_portfolio_manager()
        summary = portfolio.get_summary()
        return portfolio_formatter.format_summary(summary)
    
    @sync_endpoint(operation="portfolio positions")
    def portfolio_positions(self, status: str = "all") -> str:
        """List portfolio positions."""
        portfolio = get_portfolio_manager()
        
        if status.lower() == "open":
            positions = portfolio.get_open_positions()
            title = "Open Positions"
        elif status.lower() == "closed":
            positions = portfolio.get_closed_positions()
            title = "Closed Positions"
        else:
            positions = portfolio.get_all_positions()
            title = "All Positions"
        
        return portfolio_formatter.format_positions_table(positions, title)
    
    @sync_endpoint(operation="portfolio position detail")
    def portfolio_position(self, position_id: str) -> str:
        """Get detailed view of a single position."""
        portfolio = get_portfolio_manager()
        position = portfolio.get_position(position_id)
        
        if not position:
            return f"❌ Position not found: {position_id}"
        
        return portfolio_formatter.format_position_detail(position)
    
    @sync_endpoint(operation="add position")
    def portfolio_add(
        self,
        symbol: str,
        short_strike: float,
        long_strike: float,
        expiration: str,
        credit: float,
        contracts: int = 1,
        notes: str = "",
    ) -> str:
        """Add a new Bull Put Spread position."""
        symbol = validate_symbol(symbol)
        portfolio = get_portfolio_manager()
        
        try:
            position = portfolio.add_bull_put_spread(
                symbol=symbol,
                short_strike=short_strike,
                long_strike=long_strike,
                expiration=expiration,
                net_credit=credit,
                contracts=contracts,
                notes=notes,
            )
            
            b = MarkdownBuilder()
            b.h1("✅ Position Added").blank()
            b.kv("ID", position.id)
            b.kv("Symbol", position.symbol)
            b.kv("Strikes", f"${long_strike}/{short_strike}")
            b.kv("Credit", f"${credit:.2f} x {contracts}")
            return b.build()
            
        except ValueError as e:
            return f"❌ Error: {e}"
    
    @sync_endpoint(operation="close position")
    def portfolio_close(self, position_id: str, close_premium: float, notes: str = "") -> str:
        """Close a position by buying back the spread."""
        portfolio = get_portfolio_manager()
        
        try:
            position = portfolio.close_position(position_id, close_premium, notes)
            pnl = position.realized_pnl()
            
            b = MarkdownBuilder()
            b.h1("✅ Position Closed").blank()
            b.kv("Symbol", position.symbol)
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            b.kv("Realized P&L", f"{pnl_icon} ${pnl:+,.2f}")
            return b.build()
            
        except ValueError as e:
            return f"❌ Error: {e}"
    
    @sync_endpoint(operation="expire position")
    def portfolio_expire(self, position_id: str) -> str:
        """Mark position as expired worthless (full profit)."""
        portfolio = get_portfolio_manager()
        
        try:
            position = portfolio.expire_position(position_id)
            
            b = MarkdownBuilder()
            b.h1("✅ Position Expired Worthless").blank()
            b.kv("Symbol", position.symbol)
            b.kv("Profit", f"🟢 ${position.total_credit:,.2f}")
            return b.build()
            
        except ValueError as e:
            return f"❌ Error: {e}"
    
    @sync_endpoint(operation="expiring positions")
    def portfolio_expiring(self, days: int = 7) -> str:
        """List positions expiring soon."""
        portfolio = get_portfolio_manager()
        positions = portfolio.get_expiring_soon(days)
        return portfolio_formatter.format_expiring_soon(positions)
    
    @sync_endpoint(operation="trade history")
    def portfolio_trades(self, limit: int = 20) -> str:
        """Show trade history."""
        portfolio = get_portfolio_manager()
        trades = portfolio.get_trades()
        return portfolio_formatter.format_trades(trades, limit)
    
    @sync_endpoint(operation="P&L by symbol")
    def portfolio_pnl_symbols(self) -> str:
        """Show realized P&L grouped by symbol."""
        portfolio = get_portfolio_manager()
        pnl = portfolio.get_pnl_by_symbol()
        return portfolio_formatter.format_pnl_by_symbol(pnl)
    
    @sync_endpoint(operation="monthly P&L")
    def portfolio_pnl_monthly(self) -> str:
        """Show monthly P&L report."""
        portfolio = get_portfolio_manager()
        pnl = portfolio.get_monthly_pnl()
        return portfolio_formatter.format_monthly_pnl(pnl)

    # =========================================================================
    # POSITION SIZING (Phase 3)
    # =========================================================================

    @mcp_endpoint(operation="position sizing")
    async def calculate_position_size(
        self,
        account_size: float,
        max_loss_per_contract: float,
        win_rate: float = 0.65,
        avg_win: float = 100,
        avg_loss: float = 350,
        signal_score: float = 7.0,
        reliability_grade: Optional[str] = None,
        current_exposure: float = 0,
    ) -> str:
        """
        Calculate optimal position size using Kelly Criterion with VIX and reliability adjustments.

        Uses the Kelly Criterion to determine optimal position sizing, adjusted for:
        - Current VIX level (reduces size in high volatility)
        - Signal reliability grade (A-F, reduces size for lower grades)
        - Signal score (reduces size for lower scores)
        - Portfolio exposure limits

        Args:
            account_size: Total account value in USD
            max_loss_per_contract: Maximum loss per contract in USD
            win_rate: Historical win rate (0.0 - 1.0, default 0.65 = 65%)
            avg_win: Average winning trade in USD (default $100)
            avg_loss: Average losing trade in USD (default $350)
            signal_score: Signal quality score (0-10, default 7.0)
            reliability_grade: Optional reliability grade (A, B, C, D, F)
            current_exposure: Current portfolio exposure in USD (default 0)

        Returns:
            Formatted Markdown with position sizing recommendation
        """
        # Lazy import to avoid circular dependencies
        from .risk.position_sizing import (
            PositionSizer,
            PositionSizerConfig,
            KellyMode,
        )

        # Get current VIX for adjustment
        vix = await self.get_vix() or 20.0

        # Create position sizer with Half-Kelly (conservative)
        config = PositionSizerConfig(kelly_mode=KellyMode.HALF)
        sizer = PositionSizer(
            account_size=account_size,
            current_exposure=current_exposure,
            config=config,
        )

        # Calculate position size
        result = sizer.calculate_position_size(
            max_loss_per_contract=max_loss_per_contract,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            signal_score=signal_score,
            vix_level=vix,
            reliability_grade=reliability_grade,
        )

        # Build output
        b = MarkdownBuilder()
        b.h1("📊 Position Sizing Recommendation").blank()

        # Account context
        b.h2("Account Context")
        b.kv_line("Account Size", f"${account_size:,.0f}")
        b.kv_line("Current Exposure", f"${current_exposure:,.0f}")
        b.kv_line("Max Loss/Contract", f"${max_loss_per_contract:,.0f}")
        b.blank()

        # Market conditions
        b.h2("Market Conditions")
        b.kv_line("VIX", f"{vix:.1f}")
        b.kv_line("VIX Regime", result.vix_regime.value.upper())
        b.kv_line("VIX Adjustment", f"{result.vix_adjustment:.0%}")
        b.blank()

        # Signal quality
        b.h2("Signal Quality")
        b.kv_line("Signal Score", f"{signal_score:.1f}/10")
        if reliability_grade:
            b.kv_line("Reliability Grade", reliability_grade)
        b.kv_line("Kelly Fraction", f"{result.kelly_fraction:.1%}")
        b.blank()

        # Recommendation
        b.h2("⭐ Recommendation")
        b.kv_line("Contracts", str(result.contracts))
        b.kv_line("Capital at Risk", f"${result.capital_at_risk:,.0f}")
        b.kv_line("Risk % of Account", f"{result.capital_at_risk / account_size * 100:.1f}%")
        b.blank()

        # Limiting factor
        limit_icons = {
            "kelly": "📈 Kelly Criterion",
            "max_risk_per_trade": "🛡️ Max Risk Per Trade",
            "portfolio_limit": "📦 Portfolio Limit",
            "vix_adjustment": "📉 VIX Adjustment",
            "reliability": "⚠️ Reliability Grade",
            "score": "📊 Signal Score",
        }
        b.kv_line("Limited By", limit_icons.get(result.limiting_factor, result.limiting_factor))

        if result.contracts == 0:
            b.blank()
            b.h3("⚠️ No Trade Recommended")
            if result.limiting_factor == "insufficient_edge":
                b.text("The win rate and payoff ratio don't provide sufficient edge.")
            elif result.limiting_factor == "portfolio_risk_full":
                b.text("Portfolio exposure limit reached.")
            elif result.limiting_factor == "reliability":
                b.text("Signal reliability too low (Grade D or F).")
            elif result.limiting_factor == "score":
                b.text("Signal score below minimum threshold.")

        return b.build()

    @mcp_endpoint(operation="stop loss recommendation")
    async def recommend_stop_loss(
        self,
        net_credit: float,
        spread_width: float,
    ) -> str:
        """
        Get recommended stop loss level for a credit spread.

        Adjusts stop loss based on current VIX level:
        - Low VIX: Wider stop (100% of credit)
        - High VIX: Tighter stop (50-75% of credit)

        Args:
            net_credit: Net credit received per share
            spread_width: Width of the spread in dollars

        Returns:
            Formatted Markdown with stop loss recommendations
        """
        from .risk.position_sizing import PositionSizer

        vix = await self.get_vix() or 20.0
        sizer = PositionSizer(account_size=100000)  # Account size not needed for stop loss

        result = sizer.calculate_stop_loss(
            net_credit=net_credit,
            spread_width=spread_width,
            vix_level=vix,
        )

        b = MarkdownBuilder()
        b.h1("🛑 Stop Loss Recommendation").blank()

        # Trade context
        b.h2("Trade Details")
        b.kv_line("Net Credit", f"${net_credit:.2f}")
        b.kv_line("Spread Width", f"${spread_width:.2f}")
        b.kv_line("Max Loss", f"${result['max_possible_loss']:.2f}")
        b.blank()

        # VIX context
        b.h2("Market Context")
        b.kv_line("VIX", f"{vix:.1f}")
        b.kv_line("Regime", result['vix_regime'].upper())
        b.blank()

        # Recommendation
        b.h2("⭐ Stop Loss Settings")
        b.kv_line("Stop Loss %", f"{result['stop_loss_pct']:.0f}%")
        b.kv_line("Exit When Spread =", f"${result['stop_price']:.2f}")
        b.kv_line("Max Loss at Stop", f"${result['max_loss']:.2f}")
        b.blank()

        # Explanation
        b.h3("📝 How to Use")
        b.text(f"Close the position if the spread price rises to ${result['stop_price']:.2f}")
        b.text(f"This limits your loss to ${result['max_loss']:.2f} per spread.")

        return b.build()

    # =========================================================================
    # SCAN REPORT
    # =========================================================================

    @mcp_endpoint(operation="scan report generation")
    async def generate_scan_report(
        self,
        strategy: str = "multi",
        symbols: Optional[List[str]] = None,
        min_score: float = 5.0,
        max_candidates: int = 20,
    ) -> str:
        """
        Generate a comprehensive multi-symbol PDF scan report.

        Creates a professional 13-page PDF report including:
        - Cover page with VIX and top picks
        - Table of contents
        - Market environment & strategy analysis
        - Scan results with all candidates
        - Earnings filter analysis
        - Support test analysis
        - Qualified candidates summary
        - Detailed fundamental analysis (top 2)
        - Trade setup with Volume Profile (top 2)
        - Comparison & recommendation
        - Risk management rules

        Args:
            strategy: Scan strategy ("multi", "pullback", "bounce", "breakout", "earnings_dip")
            symbols: List of symbols to scan (uses default watchlist if not provided)
            min_score: Minimum score for qualification (default: 5.0)
            max_candidates: Maximum candidates to include in report (default: 20)

        Returns:
            Path to generated PDF file with summary
        """
        import pandas as pd

        # 1. Get VIX and strategy recommendation
        vix_value = await self.get_vix()
        regime = self._vix_selector.get_regime(vix_value) if vix_value else None
        strategy_rec = self._vix_selector.get_recommendation(vix_value) if vix_value else None

        vix_data = {
            "value": vix_value or "N/A",
            "regime": regime.name if regime else "Unknown",
            "recommended_strategy": strategy_rec.profile_name.title() if strategy_rec else 'Standard',
            "parameters": {
                "delta": strategy_rec.delta_target if strategy_rec else -0.20,
                "spread_width": strategy_rec.spread_width if strategy_rec else 5,
                "min_score": min_score,
                "min_dte": strategy_rec.dte_min if strategy_rec else 60,
                "max_dte": strategy_rec.dte_max if strategy_rec else 90,
            }
        }

        # 2. Get symbols list
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()

        # 3. Pre-filter by earnings
        safe_symbols = []
        earnings_data = {}

        if self._earnings_fetcher is None:
            self._earnings_fetcher = get_earnings_fetcher()

        for symbol in symbols[:100]:  # Limit to 100 for performance
            try:
                earnings_info = await self._check_earnings_async(symbol)
                days = earnings_info.get('days_to_earnings')
                earnings_data[symbol] = {
                    'days_to_earnings': days,
                    'next_date': earnings_info.get('next_date'),
                    'safe': days is None or days > 45,
                }
                if earnings_data[symbol]['safe']:
                    safe_symbols.append(symbol)
            except Exception as e:
                logger.debug(f"Earnings check failed for {symbol}: {e}")
                safe_symbols.append(symbol)  # Include if earnings unknown
                earnings_data[symbol] = {'days_to_earnings': None, 'next_date': 'Unknown', 'safe': True}

        # 4. Run scan
        scanner = self._get_multi_scanner(min_score=0)  # Get all results
        scan_results = []

        provider = await self._ensure_connected()

        for symbol in safe_symbols[:50]:  # Scan top 50 safe symbols
            try:
                data = await self._fetch_historical_cached(symbol, days=260)
                if not data:
                    continue

                prices, volumes, highs, lows = data

                # Set earnings date if known
                e_info = earnings_data.get(symbol, {})
                if e_info.get('next_date') and e_info['next_date'] != 'Unknown':
                    try:
                        earnings_date = date.fromisoformat(e_info['next_date'])
                        scanner.set_earnings_date(symbol, earnings_date)
                    except (ValueError, TypeError):
                        pass

                signals = scanner.analyze_symbol(symbol, prices, volumes, highs, lows)
                if signals:
                    # Take best signal for each symbol
                    best = max(signals, key=lambda x: x.score)
                    scan_results.append(best)

            except Exception as e:
                logger.debug(f"Scan failed for {symbol}: {e}")

        # Sort by score
        scan_results = sorted(scan_results, key=lambda x: x.score, reverse=True)[:max_candidates]

        if not scan_results:
            return "❌ No scan results found. Check your watchlist and data connection."

        # 5. Get fundamentals for top 7 candidates (for scorecards)
        fundamentals = {}
        try:
            from .data_providers.fundamentals import get_fundamentals
            for signal in scan_results[:7]:
                fundamentals[signal.symbol] = get_fundamentals(signal.symbol)
        except Exception as e:
            logger.warning(f"Failed to get fundamentals: {e}")

        # 6. Get options data for top 7 candidates (for scorecards)
        options_data = {}
        recommender = StrikeRecommender()

        for signal in scan_results[:7]:
            try:
                # Get support levels
                data = await self._fetch_historical_cached(signal.symbol, days=260)
                if data:
                    prices, volumes, highs, lows = data
                    support_levels = find_support_levels(lows=lows, lookback=90, window=10, max_levels=5)
                    support_levels = [s for s in support_levels if s < signal.current_price]

                    # Calculate Fibonacci
                    recent_high = max(highs[-60:]) if len(highs) >= 60 else max(highs)
                    recent_low = min(lows[-60:]) if len(lows) >= 60 else min(lows)
                    fib_levels = calculate_fibonacci(recent_high, recent_low)

                    # Get options chain
                    await self._rate_limiter.acquire()
                    options = await provider.get_option_chain(signal.symbol, dte_min=30, dte_max=60, right="P")
                    self._rate_limiter.record_success()

                    options_dict = None
                    if options:
                        options_dict = [
                            {
                                "strike": opt.strike,
                                "right": "P",
                                "bid": opt.bid,
                                "ask": opt.ask,
                                "delta": opt.delta,
                                "iv": opt.implied_volatility,
                                "dte": (opt.expiry - date.today()).days,
                            }
                            for opt in options
                        ]

                    rec = recommender.get_recommendation(
                        symbol=signal.symbol,
                        current_price=signal.current_price,
                        support_levels=support_levels,
                        options_data=options_dict,
                        fib_levels=[{"level": v, "fib": k} for k, v in fib_levels.items() if v < signal.current_price],
                        dte=45,
                        regime=regime,
                    )

                    if rec:
                        options_data[signal.symbol] = {
                            'recommendations': [{
                                'short_strike': rec.short_strike,
                                'long_strike': rec.long_strike,
                                'width': rec.spread_width,
                                'credit': rec.estimated_credit or 0,
                                'short_delta': rec.estimated_delta or 0,
                                'short_premium': 0,
                                'long_delta': 0,
                                'long_premium': 0,
                                'probability_of_profit': rec.prob_profit or 0,
                                'dte': 45,
                            }]
                        }
            except Exception as e:
                logger.debug(f"Options data failed for {signal.symbol}: {e}")

        # 7. Get historical data for Volume Profile (top 7 for scorecards)
        historical_data = {}
        for signal in scan_results[:7]:
            try:
                full_bars = await provider.get_historical(signal.symbol, days=130)
                if full_bars and len(full_bars) >= 10:
                    historical_data[signal.symbol] = pd.DataFrame({
                        'Open': [bar.open for bar in full_bars],
                        'High': [bar.high for bar in full_bars],
                        'Low': [bar.low for bar in full_bars],
                        'Close': [bar.close for bar in full_bars],
                        'Volume': [bar.volume for bar in full_bars],
                    })
            except Exception as e:
                logger.debug(f"Historical data failed for {signal.symbol}: {e}")

        # 8. Generate PDF using new report generator
        pdf_path = None
        try:
            pdf_path = await self._generate_pdf_report(
                vix_value=vix_value,
                vix_data=vix_data,
                scan_results=scan_results,
                earnings_data=earnings_data,
                fundamentals=fundamentals,
                options_data=options_data,
                historical_data=historical_data,
                safe_symbols=safe_symbols,
                min_score=min_score,
            )
        except Exception as e:
            logger.warning(f"PDF generation failed: {e}")
            pdf_path = None

        # 9. Build response
        qualified = [s for s in scan_results if s.score >= min_score]

        b = MarkdownBuilder()
        b.h1("📊 Scan Results").blank()

        if pdf_path:
            b.status_ok(f"PDF Report generated: {pdf_path}")
        else:
            b.status_warn("PDF generation failed - see logs for details")
        b.blank()

        b.h2("Summary")
        b.kv_line("Total Scanned", len(safe_symbols))
        b.kv_line("Results", len(scan_results))
        b.kv_line("Qualified (>={min_score})", len(qualified))
        b.kv_line("VIX", f"{vix_value:.1f}" if vix_value else "N/A")
        b.kv_line("Strategy", vix_data['recommended_strategy'])
        b.blank()

        if qualified:
            b.h2("Top Picks")
            for i, sig in enumerate(qualified[:3], 1):
                b.bullet(f"**#{i} {sig.symbol}**: Score {sig.score:.1f}/16, ${sig.current_price:.2f}")
            b.blank()

        return b.build()

    async def _check_earnings_async(self, symbol: str) -> Dict[str, Any]:
        """Async helper to check earnings for a symbol."""
        try:
            if self._earnings_fetcher is None:
                self._earnings_fetcher = get_earnings_fetcher()

            cached = self._earnings_fetcher.cache.get(symbol)
            if cached and cached.earnings_date:
                try:
                    earnings_date = date.fromisoformat(cached.earnings_date)
                    days = (earnings_date - date.today()).days
                    return {
                        'days_to_earnings': days,
                        'next_date': cached.earnings_date,
                    }
                except (ValueError, TypeError):
                    pass

            # Fetch if not cached
            result = await asyncio.to_thread(
                self._earnings_fetcher.fetch_earnings_date,
                symbol
            )
            if result and result.earnings_date:
                try:
                    earnings_date = date.fromisoformat(result.earnings_date)
                    days = (earnings_date - date.today()).days
                    return {
                        'days_to_earnings': days,
                        'next_date': result.earnings_date,
                    }
                except (ValueError, TypeError):
                    pass

            return {'days_to_earnings': None, 'next_date': None}
        except Exception as e:
            logger.debug(f"Earnings check error for {symbol}: {e}")
            return {'days_to_earnings': None, 'next_date': None}

    async def _generate_pdf_report(
        self,
        vix_value: float,
        vix_data: Dict[str, Any],
        scan_results: List[Any],
        earnings_data: Dict[str, Dict],
        fundamentals: Dict[str, Dict],
        options_data: Dict[str, Dict],
        historical_data: Dict[str, Any],
        safe_symbols: List[str],
        min_score: float,
    ) -> str:
        """
        Generate PDF report from scan data.

        Returns:
            Path to generated PDF file
        """
        from .formatters.pdf_report_generator import (
            PDFReportGenerator,
            CoverPageData,
            ScanResultRow,
            ScorecardData,
            ScoreItem,
            TradeLeg,
            TradeSetup,
            SupportResistanceLevel,
            VolumeProfileBar,
            VolumeProfileData,
            FundamentalsData,
            NewsItem,
            PriceLevel,
            ReportData,
        )
        from .data_providers.yahoo_news import get_stock_news
        from .indicators.volume_profile import calculate_volume_profile_poc, get_sector

        generator = PDFReportGenerator()
        now = datetime.now()

        # Determine market sentiment based on VIX
        if vix_value and vix_value < 15:
            sentiment = "Bullish"
        elif vix_value and vix_value < 20:
            sentiment = "Neutral"
        elif vix_value and vix_value < 30:
            sentiment = "Cautious"
        else:
            sentiment = "Bearish"

        # Build cover page data
        cover = CoverPageData(
            date=now.strftime("%d. %B %Y").replace(
                "January", "Januar"
            ).replace(
                "February", "Februar"
            ).replace(
                "March", "März"
            ).replace(
                "May", "Mai"
            ).replace(
                "June", "Juni"
            ).replace(
                "July", "Juli"
            ).replace(
                "October", "Oktober"
            ).replace(
                "December", "Dezember"
            ),
            time=now.strftime("%H:%M"),
            title="Bull-Put Spread",
            subtitle=f"{len([s for s in scan_results if s.score >= min_score])} Kandidaten gefunden · {min(7, len(scan_results))} detailliert analysiert",
            symbols_after_filter=len(safe_symbols),
            symbols_with_signals=len(scan_results),
            vix_level=vix_value or 0,
            market_sentiment=sentiment,
            dte_range=f"{vix_data['parameters'].get('min_dte', 60)}-{vix_data['parameters'].get('max_dte', 90)} DTE",
            delta_short="0.15-0.25",
            spread_width=f"${vix_data['parameters'].get('spread_width', 5):.0f}",
            min_roi=">30%",
            vix_regime=vix_data.get('regime', 'Normal'),
        )

        # Convert scan results to rows
        results_rows = []
        for i, sig in enumerate(scan_results[:12], 1):
            # Calculate ROI from options data if available
            roi = 0.0
            if sig.symbol in options_data:
                recs = options_data[sig.symbol].get('recommendations', [])
                if recs:
                    credit = recs[0].get('credit', 0)
                    width = recs[0].get('width', 5)
                    if width > 0:
                        roi = (credit / (width - credit)) * 100 if credit < width else 0

            results_rows.append(ScanResultRow(
                rank=i,
                symbol=sig.symbol,
                price=sig.current_price,
                change_pct=getattr(sig, 'change_pct', 0) or 0,
                score=sig.score,
                max_score=16,
                strategy=sig.strategy.replace('_', ' ').title(),
                roi=roi,
                analyzed=i <= 7,
            ))

        # Build scorecards for top 7
        scorecards = []
        for sig in scan_results[:7]:
            try:
                scorecard = await self._build_scorecard_data(
                    signal=sig,
                    fundamentals=fundamentals.get(sig.symbol, {}),
                    options_data=options_data.get(sig.symbol, {}),
                    historical_data=historical_data.get(sig.symbol),
                    earnings_data=earnings_data.get(sig.symbol, {}),
                )
                if scorecard:
                    scorecards.append(scorecard)
            except Exception as e:
                logger.debug(f"Scorecard build failed for {sig.symbol}: {e}")

        # Create report data
        report_data = ReportData(
            cover=cover,
            scan_results=results_rows,
            scorecards=scorecards,
        )

        # Generate PDF
        pdf_path = generator.generate_pdf(report_data)
        return str(pdf_path)

    async def _build_scorecard_data(
        self,
        signal: Any,
        fundamentals: Dict[str, Any],
        options_data: Dict[str, Any],
        historical_data: Any,
        earnings_data: Dict[str, Any],
    ) -> Optional[Any]:
        """Build scorecard data for a single symbol."""
        from .formatters.pdf_report_generator import (
            ScorecardData,
            ScoreItem,
            TradeLeg,
            TradeSetup,
            SupportResistanceLevel,
            VolumeProfileBar,
            VolumeProfileData,
            FundamentalsData,
            NewsItem,
            PriceLevel,
        )
        from .data_providers.yahoo_news import get_stock_news
        from .indicators.volume_profile import get_sector

        symbol = signal.symbol
        now = datetime.now()

        # Get company name via yfinance
        company_name = symbol
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            company_name = info.get('shortName', info.get('longName', symbol))
        except Exception:
            pass

        # Score items from signal breakdown
        score_items = []
        # Extract breakdown from signal.details['score_breakdown'] if available
        details = getattr(signal, 'details', {}) or {}
        breakdown = details.get('score_breakdown', {}) or {}

        # Map breakdown to score items
        # Note: Some values are nested (e.g., keltner.position, macd.signal)
        score_mappings = [
            ('rsi', 'RSI', lambda v: f"{v:.1f}" if v else "N/A"),
            ('rsi_divergence.type', 'RSI Div', lambda v: v.title() if v else "None"),
            ('support_distance', 'Support', lambda v: f"{v:+.1f}%" if v else "N/A"),
            ('fib_level', 'Fib', lambda v: f"{v:.1f}%" if v else "N/A"),
            ('ma50_distance', 'MA 50', lambda v: f"{v:+.1f}%" if v else "N/A"),
            ('trend', 'Trend', lambda v: v.title() if v else "N/A"),
            ('volume_ratio', 'Volume', lambda v: f"{v:.1f}x" if v else "N/A"),
            ('macd.signal', 'MACD', lambda v: v.replace('_', ' ').title() if v else "N/A"),
            ('stochastic.signal', 'Stoch', lambda v: v.replace('_', ' ').title() if v else "N/A"),
            ('vwap.position', 'VWAP', lambda v: v.title() if v else "N/A"),
            ('keltner.position', 'Keltner', lambda v: v.replace('_', ' ').title() if v else "N/A"),
            ('iv_rank', 'IV Rank', lambda v: f"{v:.0f}" if v else "N/A"),
        ]

        for key, label, formatter in score_mappings:
            # Handle nested keys like 'keltner.position'
            if '.' in key:
                parts = key.split('.')
                value = breakdown.get(parts[0], {}).get(parts[1]) if breakdown else None
            else:
                value = breakdown.get(key)
            formatted = formatter(value) if value is not None else "N/A"

            # Determine color based on key (use base key for nested keys)
            base_key = key.split('.')[0] if '.' in key else key
            color = "gray"
            if base_key == 'rsi' and value:
                color = "green" if value < 35 else ("orange" if value < 50 else "gray")
            elif base_key == 'rsi_divergence' and value:
                # Bullish divergence = strong buy signal
                color = "green" if value == 'bullish' else ("red" if value == 'bearish' else "gray")
            elif base_key in ('support_distance', 'ma50_distance') and value:
                color = "green" if value < 0 else "orange"
            elif base_key == 'volume_ratio' and value:
                color = "green" if value > 1.2 else "gray"
            elif base_key == 'trend':
                color = "green" if value == 'up' else ("orange" if value == 'down' else "gray")
            elif base_key == 'macd' and value:
                color = "green" if 'bull' in str(value).lower() else "gray"
            elif base_key == 'stochastic' and value:
                # oversold signals are bullish
                color = "green" if 'oversold' in str(value).lower() else "gray"
            elif base_key == 'vwap' and value:
                # above VWAP = bullish (91.9% win rate per training)
                color = "green" if value == 'above' else ("orange" if value == 'below' else "gray")
            elif base_key == 'iv_rank' and value:
                color = "green" if 30 <= value <= 60 else "orange"
            elif base_key == 'keltner' and value:
                # below_lower/near_lower = bullish for pullback/bounce, above_upper = bullish for breakout
                if 'below' in str(value) or 'near_lower' in str(value):
                    color = "green"  # Oversold - bullish signal
                elif 'above' in str(value) or 'near_upper' in str(value):
                    color = "orange"  # Overbought
                else:
                    color = "gray"  # In channel

            score_items.append(ScoreItem(label=label, value=formatted, color=color))

        # Trade setup from options data
        recs = options_data.get('recommendations', [{}])
        rec = recs[0] if recs else {}

        short_strike = rec.get('short_strike', signal.current_price * 0.95)
        long_strike = rec.get('long_strike', signal.current_price * 0.90)
        credit = rec.get('credit', 1.50)
        width = rec.get('width', 5)
        dte = rec.get('dte', 60)

        expiry = (date.today() + timedelta(days=dte))
        max_risk = (width - credit) * 100 if width > credit else width * 100
        roi = (credit / (width - credit)) * 100 if width > credit else 0
        breakeven = short_strike - credit

        trade_setup = TradeSetup(
            short_leg=TradeLeg(
                leg_type="Short Put",
                strike=short_strike,
                delta=rec.get('short_delta', -0.20),
                premium=rec.get('short_premium', credit + 0.5),
            ),
            long_leg=TradeLeg(
                leg_type="Long Put",
                strike=long_strike,
                delta=rec.get('long_delta', -0.05),
                premium=rec.get('long_premium', 0.5),
            ),
            net_credit=credit,
            max_risk=max_risk,
            roi=roi,
            breakeven=breakeven,
            prob_profit=rec.get('probability_of_profit', 75),
            expiry_date=expiry.strftime("%d. %b %Y"),
            dte=dte,
            earnings_days=earnings_data.get('days_to_earnings'),
        )

        # =================================================================
        # REAL S/R LEVELS from historical data
        # =================================================================
        support_levels = []
        resistance_levels = []
        week_52_high = signal.current_price * 1.15  # Fallback
        week_52_low = signal.current_price * 0.85   # Fallback

        if historical_data is not None and len(historical_data) > 0:
            from .indicators.support_resistance import get_nearest_sr_levels

            closes = historical_data['Close'].tolist()
            highs = historical_data['High'].tolist()
            lows = historical_data['Low'].tolist()
            volumes = historical_data['Volume'].tolist()

            # Calculate real 52W High/Low
            week_52_high = max(highs) if highs else signal.current_price * 1.15
            week_52_low = min(lows) if lows else signal.current_price * 0.85

            # Get real S/R levels
            try:
                sr_data = get_nearest_sr_levels(
                    current_price=signal.current_price,
                    prices=closes,
                    highs=highs,
                    lows=lows,
                    volumes=volumes,
                    lookback=252,  # 12 months
                    num_levels=3
                )

                # Convert supports
                for i, sup in enumerate(sr_data.get('supports', [])[:3], 1):
                    distance_pct = ((sup['price'] - signal.current_price) / signal.current_price) * 100
                    support_levels.append(SupportResistanceLevel(
                        rank=f"S{i}",
                        price=sup['price'],
                        distance_pct=distance_pct,
                        tests=sup.get('touches', 1),
                        strength=min(sup.get('touches', 1) * 25, 100),
                    ))

                # Convert resistances
                for i, res in enumerate(sr_data.get('resistances', [])[:3], 1):
                    distance_pct = ((res['price'] - signal.current_price) / signal.current_price) * 100
                    resistance_levels.append(SupportResistanceLevel(
                        rank=f"R{i}",
                        price=res['price'],
                        distance_pct=distance_pct,
                        tests=res.get('touches', 1),
                        strength=min(res.get('touches', 1) * 25, 100),
                    ))
            except Exception as e:
                logger.debug(f"S/R calculation failed for {symbol}: {e}")

        # Fallback if no real levels found
        if not support_levels:
            support_levels = [
                SupportResistanceLevel(rank="S1", price=signal.current_price * 0.97, distance_pct=-3.0, tests=2, strength=50),
                SupportResistanceLevel(rank="S2", price=signal.current_price * 0.94, distance_pct=-6.0, tests=3, strength=75),
            ]
        if not resistance_levels:
            resistance_levels = [
                SupportResistanceLevel(rank="R1", price=signal.current_price * 1.03, distance_pct=3.0, tests=2, strength=50),
                SupportResistanceLevel(rank="R2", price=signal.current_price * 1.06, distance_pct=6.0, tests=3, strength=75),
            ]

        # =================================================================
        # REAL VOLUME PROFILE with POC, HVN, LVN
        # =================================================================
        vp_bars = []
        poc_price = signal.current_price * 0.98  # Fallback
        value_area_low = signal.current_price * 0.95
        value_area_high = signal.current_price * 1.02
        hvn_support = signal.current_price * 0.96
        lvn_resistance = signal.current_price * 1.05

        if historical_data is not None and len(historical_data) > 0:
            from .indicators.volume_profile import calculate_volume_profile_poc

            closes = historical_data['Close'].tolist()
            volumes = historical_data['Volume'].tolist()
            opens = historical_data['Open'].tolist()

            # Calculate real Volume Profile POC
            try:
                vp_result = calculate_volume_profile_poc(closes, volumes, num_bins=20, period=min(130, len(closes)))
                if vp_result:
                    poc_price = vp_result.poc
                    value_area_low = vp_result.value_area_low
                    value_area_high = vp_result.value_area_high
            except Exception as e:
                logger.debug(f"Volume profile calculation failed: {e}")

            price_min = min(closes)
            price_max = max(closes)
            price_range = price_max - price_min

            if price_range > 0:
                num_bins = 10
                step = price_range / num_bins

                # Track bin volumes for HVN/LVN detection
                bin_data = []
                highs_list = historical_data['High'].tolist()
                lows_list = historical_data['Low'].tolist()

                for i in range(num_bins):
                    bin_price = price_max - (i * step)
                    bin_low = bin_price - step
                    bin_high = bin_price

                    # Count volume in this bin with improved buy/sell classification
                    bin_volume = 0
                    weighted_buy_volume = 0

                    for j in range(len(closes)):
                        close = closes[j]
                        if bin_low <= close <= bin_high:
                            volume = volumes[j]
                            open_p = opens[j]
                            high = highs_list[j]
                            low = lows_list[j]
                            prev_close = closes[j - 1] if j > 0 else close

                            bin_volume += volume

                            # =================================================
                            # IMPROVED BUY/SELL CLASSIFICATION
                            # Combines multiple factors for better accuracy
                            # =================================================

                            # Factor 1: Intraday direction (Close vs Open)
                            intraday_up = close > open_p

                            # Factor 2: Day-over-day direction (Close vs Previous Close)
                            day_over_day_up = close > prev_close

                            # Factor 3: Close position in daily range (0=low, 1=high)
                            daily_range = high - low
                            if daily_range > 0:
                                close_position = (close - low) / daily_range
                            else:
                                close_position = 0.5

                            # Calculate buy confidence (0.0 to 1.0)
                            if intraday_up and day_over_day_up and close_position > 0.6:
                                # Strong buying: up intraday, up vs yesterday, closed near high
                                buy_confidence = 0.85
                            elif intraday_up and day_over_day_up:
                                # Good buying: up on both measures
                                buy_confidence = 0.75
                            elif intraday_up or (day_over_day_up and close_position > 0.5):
                                # Moderate buying: one positive factor
                                buy_confidence = 0.60
                            elif close_position > 0.5:
                                # Weak buying: closed in upper half despite down day
                                buy_confidence = 0.45
                            elif not intraday_up and not day_over_day_up and close_position < 0.4:
                                # Strong selling: down everywhere, closed near low
                                buy_confidence = 0.15
                            else:
                                # Default: slight selling bias
                                buy_confidence = 0.35

                            weighted_buy_volume += volume * buy_confidence

                    total_vol = sum(volumes) or 1
                    vol_pct = (bin_volume / total_vol) * 100

                    buy_pct = (weighted_buy_volume / bin_volume * 100) if bin_volume > 0 else 50
                    sell_pct = 100 - buy_pct

                    # Check if this is POC (real POC from calculation)
                    is_poc = abs(bin_price - poc_price) < step

                    vp_bars.append(VolumeProfileBar(
                        price=bin_price,
                        volume_pct=min(vol_pct * 7, 100),  # Scale for display
                        buy_pct=buy_pct,
                        sell_pct=sell_pct,
                        is_poc=is_poc,
                        is_current=abs(bin_price - signal.current_price) < step,
                    ))
                    bin_data.append((bin_price, vol_pct))

                # Find HVN (High Volume Node) below current price = Support
                # Find LVN (Low Volume Node) above current price = Resistance
                bins_below = [(p, v) for p, v in bin_data if p < signal.current_price]
                bins_above = [(p, v) for p, v in bin_data if p > signal.current_price]

                if bins_below:
                    hvn_support = max(bins_below, key=lambda x: x[1])[0]  # Highest volume below
                if bins_above:
                    lvn_resistance = min(bins_above, key=lambda x: x[1])[0]  # Lowest volume above

        # Fallback empty profile
        if not vp_bars:
            for i in range(8):
                vp_bars.append(VolumeProfileBar(
                    price=signal.current_price * (1.05 - i * 0.02),
                    volume_pct=50,
                    buy_pct=55,
                    sell_pct=45,
                    is_poc=(i == 4),
                    is_current=(i == 3),
                ))

        volume_profile = VolumeProfileData(
            bars=vp_bars,
            poc_price=poc_price,
            value_area=f"${value_area_low:.0f}-${value_area_high:.0f}",
            hvn_support=hvn_support,
            lvn_resistance=lvn_resistance,
            price_step="$2" if signal.current_price < 100 else ("$5" if signal.current_price < 300 else "$10"),
        )

        # =================================================================
        # PRICE LEVELS with real 52W High/Low
        # =================================================================
        pct_to_52w_high = ((week_52_high - signal.current_price) / signal.current_price) * 100
        pct_to_52w_low = ((week_52_low - signal.current_price) / signal.current_price) * 100
        pct_to_short = ((short_strike - signal.current_price) / signal.current_price) * 100
        pct_to_long = ((long_strike - signal.current_price) / signal.current_price) * 100
        pct_to_support = ((support_levels[0].price - signal.current_price) / signal.current_price) * 100 if support_levels else -10.0

        price_levels = [
            PriceLevel(label="52W High", price=week_52_high, pct_from_current=pct_to_52w_high, level_type="resistance"),
            PriceLevel(label="Resistance", price=resistance_levels[0].price if resistance_levels else signal.current_price * 1.05, pct_from_current=resistance_levels[0].distance_pct if resistance_levels else 5.0, level_type="normal"),
            PriceLevel(label="Current", price=signal.current_price, pct_from_current=0.0, level_type="current"),
            PriceLevel(label="Short Strike", price=short_strike, pct_from_current=pct_to_short, level_type="short-strike"),
            PriceLevel(label="Long Strike", price=long_strike, pct_from_current=pct_to_long, level_type="long-strike"),
            PriceLevel(label="Support", price=support_levels[0].price if support_levels else signal.current_price * 0.95, pct_from_current=pct_to_support, level_type="support"),
            PriceLevel(label="52W Low", price=week_52_low, pct_from_current=pct_to_52w_low, level_type="support"),
        ]

        # Fundamentals
        fund_data = FundamentalsData(
            pe_ratio=fundamentals.get('current_price', 0) / max(fundamentals.get('eps', 1), 0.01) if fundamentals.get('eps') else None,
            market_cap=self._format_market_cap(fundamentals.get('market_cap')),
            div_yield=f"{fundamentals.get('dividend_yield', 0) * 100:.2f}%" if fundamentals.get('dividend_yield') else "0.00%",
            iv_rank=breakdown.get('iv_rank', 0) or 0,
            earnings_in_days=earnings_data.get('days_to_earnings'),
            sector=get_sector(symbol),
        )

        # News - IBKR primary, Yahoo fallback
        news_items = []
        raw_news = []
        news_source = "none"

        # Try IBKR first (better quality: Dow Jones, Briefing)
        if IBKR_AVAILABLE and self._ibkr_bridge:
            try:
                ibkr_available = await self._ibkr_bridge.is_available()
                if ibkr_available:
                    ibkr_news = await self._ibkr_bridge.get_news([symbol], days=7, max_per_symbol=3)
                    if ibkr_news:
                        raw_news = [
                            {
                                'title': n.headline,
                                'date': n.time[:10] if n.time else 'Unknown',
                                'publisher': n.provider or 'IBKR'
                            }
                            for n in ibkr_news
                        ]
                        news_source = "ibkr"
                        logger.debug(f"Got {len(raw_news)} news from IBKR for {symbol}")
            except Exception as e:
                logger.debug(f"IBKR news failed for {symbol}: {e}")

        # Fallback to Yahoo if no IBKR news
        if not raw_news:
            try:
                raw_news = get_stock_news(symbol, max_items=3)
                if raw_news:
                    news_source = "yahoo"
                    logger.debug(f"Got {len(raw_news)} news from Yahoo for {symbol}")
            except Exception as e:
                logger.debug(f"Yahoo news failed for {symbol}: {e}")

        # Process news items with sentiment analysis
        for n in raw_news:
            title = n.get('title', '').lower()
            sentiment = "neutral"

            # Positive indicators
            positive_words = ['beat', 'surge', 'jump', 'gain', 'up', 'strong', 'record',
                            'upgrade', 'buy', 'outperform', 'raises', 'growth', 'profit']
            # Negative indicators
            negative_words = ['miss', 'drop', 'fall', 'down', 'weak', 'decline', 'cut',
                            'downgrade', 'sell', 'underperform', 'lowers', 'loss', 'warning']

            if any(w in title for w in positive_words):
                sentiment = "positive"
            elif any(w in title for w in negative_words):
                sentiment = "negative"

            news_items.append(NewsItem(
                text=n.get('title', 'No title')[:80],
                time=n.get('date', 'Unknown'),
                sentiment=sentiment,
            ))

        return ScorecardData(
            symbol=symbol,
            company_name=company_name,
            strategy=signal.strategy.replace('_', ' ').title(),
            date=now.strftime("%d. %b %Y"),
            dte=dte,
            price=signal.current_price,
            price_change=signal.current_price * (breakdown.get('change_pct', 0) / 100) if breakdown.get('change_pct') else 0,
            price_change_pct=breakdown.get('change_pct', 0) or 0,
            score=signal.score,
            max_score=16,
            score_items=score_items,
            trade_setup=trade_setup,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            volume_profile=volume_profile,
            price_levels=price_levels,
            fundamentals=fund_data,
            news=news_items,
        )

    def _format_market_cap(self, value: Optional[float]) -> str:
        """Format market cap to readable string."""
        if not value:
            return "N/A"
        if value >= 1e12:
            return f"${value / 1e12:.2f}T"
        if value >= 1e9:
            return f"${value / 1e9:.1f}B"
        if value >= 1e6:
            return f"${value / 1e6:.0f}M"
        return f"${value:.0f}"


# =============================================================================
# CLI & INTERACTIVE MODE
# =============================================================================

async def run_interactive():
    """Interactive test mode."""
    print("=" * 60)
    print(f"  OPTIONPLAY SERVER v{OptionPlayServer.VERSION} - INTERACTIVE MODE")
    print("=" * 60)
    
    server = OptionPlayServer()
    
    commands = {
        "vix": ("get_strategy_recommendation", []),
        "scan": ("scan_with_strategy", []),
        "bounce": ("scan_bounce", []),
        "breakout": ("scan_ath_breakout", []),
        "earningsdip": ("scan_earnings_dip", []),
        "multi": ("scan_multi_strategy", []),
        "analyzem": ("analyze_multi_strategy", ["symbol"]),
        "quote": ("get_quote", ["symbol"]),
        "options": ("get_options_chain", ["symbol"]),
        "earnings": ("get_earnings", ["symbol"]),
        "analyze": ("analyze_symbol", ["symbol"]),
        "health": ("health_check", []),
        "ibkr": ("get_ibkr_status", []),
        "pf": ("portfolio_summary", []),
    }
    
    print("\nAvailable commands:")
    for cmd, (method, args) in commands.items():
        args_str = " ".join(f"<{a}>" for a in args) if args else ""
        print(f"  {cmd} {args_str}")
    print("  quit - Exit")
    print()
    
    while True:
        try:
            user_input = input("optionplay> ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() == "quit":
                break
            
            parts = user_input.split()
            cmd = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []
            
            if cmd not in commands:
                print(f"Unknown command: {cmd}")
                continue
            
            method_name, required_args = commands[cmd]
            method = getattr(server, method_name)
            
            if required_args and not args:
                print(f"Missing: {', '.join(required_args)}")
                continue
            
            if args:
                result = await method(args[0])
            else:
                if cmd == "pf":
                    result = method()
                else:
                    result = await method()
            
            print()
            print(result)
            print()
            
        except KeyboardInterrupt:
            print("\n")
            break
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    
    await server.disconnect()
    print("Goodbye!")


async def quick_test():
    """Quick test of functions."""
    print("=" * 60)
    print(f"  OPTIONPLAY v{OptionPlayServer.VERSION} - QUICK TEST")
    print("=" * 60)
    
    server = OptionPlayServer()
    
    print("\n1. VIX & Strategy...")
    result = await server.get_strategy_recommendation()
    print(result)
    
    print("\n2. Health Check...")
    result = await server.health_check()
    print(result)
    
    await server.disconnect()
    print("\n✅ All tests completed!")


def main():
    """Entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description=f"OptionPlay Server v{OptionPlayServer.VERSION}")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--test", action="store_true", help="Run quick test")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    
    if args.test:
        asyncio.run(quick_test())
    elif args.interactive:
        asyncio.run(run_interactive())
    else:
        print(f"OptionPlay Server v{OptionPlayServer.VERSION}")
        print("Usage: --interactive, -i  Interactive mode | --test  Quick test")


if __name__ == "__main__":
    main()
