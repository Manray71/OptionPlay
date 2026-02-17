"""
OptionPlay MCP Server v4.0.0
=============================

MCP Server for options trading analysis with multi-strategy support.

This is the refactored version using modular handlers.

Stats:
- 53 Tools + 55 Aliases = 108 MCP Endpoints
- 80.19% Test Coverage (6,740 tests)
- Thread-safe singletons with RLock
- Async SQLite via asyncio.to_thread()

Modules:
- handlers.vix: VIX, strategy, regime handlers
- handlers.scan: Scan operations (pullback, bounce, breakout, etc.)
- handlers.quote: Quote, options chain, historical data, earnings
- handlers.analysis: Symbol analysis, ensemble recommendations
- handlers.portfolio: Portfolio management
- handlers.ibkr: IBKR Bridge features
- handlers.report: PDF report generation
- handlers.risk: Position sizing, stop loss, spread analysis

Usage:
    python3 -m src.mcp_server
    python3 -m src.mcp_server --interactive
    python3 -m src.mcp_server --test
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .cache import CacheStatus, EarningsFetcher, get_earnings_fetcher, get_historical_cache
from .config import get_config, get_scan_config, get_watchlist_loader
from .container import ServiceContainer
from .data_providers.local_db import LocalDBProvider, get_local_db_provider

# Local imports
from .data_providers.tradier import TradierEnvironment, TradierProvider
from .formatters import HealthCheckData, formatters

# Composition-based handler architecture (Phase 3.3)
from .handlers.handler_container import (
    HandlerContainer,
    ServerContext,
    create_handler_container_from_server,
)
from .scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig, ScanMode
from .services.vix_strategy import VIXStrategySelector
from .state.server_state import ServerState
from .utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, get_circuit_breaker
from .utils.metrics import metrics
from .utils.provider_orchestrator import ProviderType, get_orchestrator
from .utils.rate_limiter import get_marketdata_limiter
from .utils.request_dedup import get_request_deduplicator
from .utils.secure_config import get_api_key, mask_api_key
from .utils.validation import is_etf

# Handler Mixins removed — now using Composition pattern via HandlerContainer


# IBKR Bridge (optional)
try:
    from .ibkr.bridge import IBKRBridge, get_ibkr_bridge

    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False

logger = logging.getLogger(__name__)


class OptionPlayServer:
    """
    OptionPlay Server for multi-strategy options analysis.

    Uses composition-based handler architecture via HandlerContainer:
    - server.handlers.vix: VIX, strategy, regime operations
    - server.handlers.scan: All scan operations
    - server.handlers.quote: Quote, options, historical, earnings
    - server.handlers.analysis: Symbol analysis, ensemble
    - server.handlers.portfolio: Portfolio management
    - server.handlers.ibkr: IBKR Bridge features
    - server.handlers.report: PDF report generation
    - server.handlers.risk: Position sizing, stop loss
    - server.handlers.validate: Trade validation
    - server.handlers.monitor: Position monitoring

    Usage:
        server = OptionPlayServer()

        # Multi-strategy scan
        result = await server.handlers.scan.scan_multi_strategy()

        # Single symbol analysis
        result = await server.handlers.analysis.analyze_multi_strategy("AAPL")

        # VIX-aware pullback scan
        result = await server.handlers.scan.scan_with_strategy()
    """

    VERSION = "4.0.0"

    def __init__(
        self, api_key: Optional[str] = None, container: Optional[ServiceContainer] = None
    ) -> None:
        """
        Initialize OptionPlay server.

        Args:
            api_key: Marketdata.app API key (optional, reads from env if not provided)
            container: Dependency injection container (optional)

        Raises:
            ValueError: If API key is not provided and not found in environment
        """
        self._container = container

        if container is not None:
            self._config = container.config
            self._rate_limiter = container.rate_limiter
            self._circuit_breaker = container.circuit_breaker
            self._historical_cache = container.historical_cache
            self._provider = None  # Marketdata.app removed — Tradier is sole live provider
        else:
            self._config = get_config()
            perf = self._config.settings.performance
            cb_cfg = self._config.settings.circuit_breaker

            self._provider = None  # Marketdata.app removed — Tradier is sole live provider
            self._rate_limiter = get_marketdata_limiter()
            self._historical_cache = get_historical_cache(
                ttl_seconds=perf.cache_ttl_seconds, max_entries=perf.cache_max_entries
            )

            self._circuit_breaker = get_circuit_breaker(
                name="marketdata_api",
                failure_threshold=cb_cfg.failure_threshold,
                recovery_timeout=cb_cfg.recovery_timeout,
            )

        # Non-container components
        self._scanner: Optional[MultiStrategyScanner] = None
        self._earnings_fetcher: Optional[EarningsFetcher] = None
        self._vix_selector = VIXStrategySelector()

        # Centralized state (STATE-01: replaces scattered variables)
        self.state = ServerState()

        # Cache data stores (metrics tracked via self.state.quote_cache / scan_cache)
        self._quote_cache: Dict[str, tuple] = {}
        self._scan_cache: Dict[str, tuple] = {}
        self._scan_cache_ttl = 1800  # 30 minutes

        # Request deduplicator
        self._deduplicator = get_request_deduplicator()

        # IBKR Bridge (optional)
        self._ibkr_bridge: Optional["IBKRBridge"] = None
        if IBKR_AVAILABLE:
            self._ibkr_bridge = get_ibkr_bridge()

        # Tradier Provider (optional)
        self._tradier_provider: Optional[TradierProvider] = None
        self._tradier_api_key: Optional[str] = None
        self._tradier_connected = False
        self._orchestrator = get_orchestrator()

        try:
            tradier_key = get_api_key("TRADIER_API_KEY", required=False)
            if tradier_key:
                self._tradier_api_key = tradier_key
                logger.info(f"Tradier API key found: {mask_api_key(tradier_key)}")
        except (KeyError, ValueError):
            logger.debug("Tradier API key not configured")

        # Local Database Provider (primary source for historical data)
        self._local_db_provider: Optional[LocalDBProvider] = None
        self._local_db_enabled = self._config.settings.data_sources.local_database.enabled
        if self._local_db_enabled:
            self._local_db_provider = get_local_db_provider()
            if self._local_db_provider.is_available():
                logger.info(f"Local DB provider available: {self._local_db_provider.db_path}")

        # Phase 3.3: Composition-based handler container
        # Initialized lazily via create_handler_container_from_server()
        # when handlers need to be accessed via composition pattern.
        self._handler_container: Optional[HandlerContainer] = None

    @property
    def handlers(self) -> HandlerContainer:
        """
        Access composition-based handlers (Phase 3.3).

        Lazily creates the HandlerContainer on first access,
        bridging from the existing Mixin architecture.

        Usage:
            await server.handlers.vix.get_vix()
            await server.handlers.scan.scan_multi_strategy()
        """
        if self._handler_container is None:
            self._handler_container = create_handler_container_from_server(self)
        return self._handler_container

    @property
    def api_key_masked(self) -> str:
        """Return masked Tradier API key for debugging/logging."""
        return mask_api_key(self._tradier_api_key) if self._tradier_api_key else "N/A"

    # =========================================================================
    # STATE DELEGATION (backward compat for handler mixins)
    # =========================================================================

    @property
    def _connected(self) -> bool:
        return self.state.connection.is_connected

    @_connected.setter
    def _connected(self, value: bool) -> None:
        if value:
            self.state.connection.mark_connected()
        else:
            self.state.connection.mark_disconnected()

    @property
    def _current_vix(self) -> Optional[float]:
        return self.state.vix.current_value

    @_current_vix.setter
    def _current_vix(self, value: Optional[float]) -> None:
        if value is not None:
            self.state.vix.update(value)
        else:
            self.state.vix.current_value = None

    @property
    def _vix_updated(self) -> Optional[datetime]:
        return self.state.vix.updated_at

    @_vix_updated.setter
    def _vix_updated(self, value: Optional[datetime]) -> None:
        self.state.vix.updated_at = value

    @property
    def _quote_cache_hits(self) -> int:
        return self.state.quote_cache.hits

    @_quote_cache_hits.setter
    def _quote_cache_hits(self, value: int) -> None:
        self.state.quote_cache.hits = value

    @property
    def _quote_cache_misses(self) -> int:
        return self.state.quote_cache.misses

    @_quote_cache_misses.setter
    def _quote_cache_misses(self, value: int) -> None:
        self.state.quote_cache.misses = value

    @property
    def _scan_cache_hits(self) -> int:
        return self.state.scan_cache.hits

    @_scan_cache_hits.setter
    def _scan_cache_hits(self, value: int) -> None:
        self.state.scan_cache.hits = value

    @property
    def _scan_cache_misses(self) -> int:
        return self.state.scan_cache.misses

    @_scan_cache_misses.setter
    def _scan_cache_misses(self, value: int) -> None:
        self.state.scan_cache.misses = value

    # =========================================================================
    # ASYNC CONTEXT MANAGER
    # =========================================================================

    async def __aenter__(self) -> "OptionPlayServer":
        """Enter async context - connect to data provider."""
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context - disconnect and cleanup."""
        await self.disconnect()
        return None

    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================

    async def _ensure_tradier_connected(self) -> Optional[TradierProvider]:
        """Establish connection to Tradier API."""
        if not self._tradier_api_key:
            return None

        if self._tradier_provider is None:
            tradier_cfg = self._config.settings.tradier
            env = (
                TradierEnvironment.PRODUCTION
                if tradier_cfg.is_production
                else TradierEnvironment.SANDBOX
            )

            self._tradier_provider = TradierProvider(api_key=self._tradier_api_key, environment=env)

        if not self._tradier_connected:
            try:
                connected = await self._tradier_provider.connect()
                if connected:
                    self._tradier_connected = True
                    self._orchestrator.enable_tradier(True)
                    self.state.connection.mark_connected()
                    logger.info(
                        f"Connected to Tradier ({self._config.settings.tradier.environment})"
                    )
                else:
                    logger.warning("Tradier connection failed")
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"Tradier connection error: {e}")

        return self._tradier_provider if self._tradier_connected else None

    async def _ensure_connected(self) -> Optional[TradierProvider]:
        """Ensure Tradier provider is connected."""
        return await self._ensure_tradier_connected()

    def _get_active_provider_name(self) -> str:
        """Get the name of the currently active provider."""
        if self._tradier_connected:
            return "Tradier"
        return "None"

    def _get_scanner(
        self, min_score: Optional[float] = None, earnings_days: Optional[int] = None
    ) -> MultiStrategyScanner:
        """Get scanner instance with config from YAML (pullback only)."""
        config = get_scan_config(override_min_score=min_score, override_earnings_days=earnings_days)

        config.enable_ath_breakout = False
        config.enable_earnings_dip = False

        return MultiStrategyScanner(config)

    def _get_multi_scanner(
        self,
        min_score: float = 3.5,
        enable_pullback: bool = True,
        enable_bounce: bool = True,
        enable_breakout: bool = True,
        enable_earnings_dip: bool = True,
        enable_trend_continuation: bool = True,
        exclude_earnings_within_days: Optional[int] = None,
    ) -> MultiStrategyScanner:
        """Get scanner instance with all strategies enabled."""
        scanner_cfg = self._config.settings.scanner
        enable_iv = getattr(scanner_cfg, "enable_iv_filter", False)

        if enable_iv and not self._tradier_connected:
            logger.debug("IV filter disabled: no IV data provider connected")
            enable_iv = False

        config = ScanConfig(
            min_score=min_score,
            enable_pullback=enable_pullback,
            enable_bounce=enable_bounce,
            enable_ath_breakout=enable_breakout,
            enable_earnings_dip=enable_earnings_dip,
            enable_trend_continuation=enable_trend_continuation,
            enable_iv_filter=enable_iv,
        )
        if exclude_earnings_within_days is not None:
            config.exclude_earnings_within_days = exclude_earnings_within_days
        return MultiStrategyScanner(config)

    @staticmethod
    def _has_incomplete_ohlcv(data: Tuple) -> bool:
        """Check if data has synthetic/missing OHLCV (close-only from options_prices)."""
        prices, volumes, highs, lows, _opens = data
        if not prices:
            return True

        # Check: All volumes == 0
        all_zero_volume = all(v == 0 for v in volumes)

        # Check: Highs == Close for recent bars (synthetic OHLCV)
        sample = min(20, len(prices))
        identical_highs = all(abs(highs[-i] - prices[-i]) < 0.001 for i in range(1, sample + 1))

        return all_zero_volume or identical_highs

    async def _fetch_historical_cached(
        self, symbol: str, days: Optional[int] = None
    ) -> Optional[Tuple]:
        """Fetch historical data with caching and request deduplication.

        Priority:
        1. In-memory cache (fastest)
        2. Local database (if enabled, data fresh, and has real OHLCV)
        3. Tradier API
        4. Graceful degradation: incomplete local data if API fails
        """
        if days is None:
            days = self._config.settings.performance.historical_days

        # 1. Check in-memory cache first
        cache_result = self._historical_cache.get(symbol, days)

        if cache_result.status == CacheStatus.HIT:
            logger.debug(f"Cache hit for {symbol} ({days}d)")
            return cache_result.data

        # 2. Try local database (much faster than API)
        local_data = None
        if self._local_db_enabled and self._local_db_provider:
            try:
                local_data = await self._local_db_provider.get_historical_for_scanner(
                    symbol, days=days
                )
                if local_data:
                    # Check if data is fresh enough
                    max_age = self._config.settings.data_sources.local_database.max_data_age_days
                    if self._local_db_provider.is_data_fresh(symbol, max_age):
                        if not self._has_incomplete_ohlcv(local_data):
                            # Real OHLCV data — use directly
                            logger.debug(f"LocalDB hit for {symbol} ({days}d, real OHLCV)")
                            self._historical_cache.set(symbol, local_data, days=days)
                            return local_data
                        else:
                            logger.debug(f"LocalDB {symbol}: incomplete OHLCV, enriching via API")
                            # Fall through to API
                    else:
                        logger.debug(f"LocalDB data for {symbol} is stale, using API")
            except Exception as e:
                logger.debug(f"LocalDB failed for {symbol}: {e}")

        # 3. Fetch from Tradier
        async def fetch_historical() -> Optional[Tuple]:
            tradier = await self._ensure_tradier_connected()
            if tradier:
                try:
                    d = await tradier.get_historical_for_scanner(symbol, days=days)
                    if d:
                        logger.debug(f"Historical data for {symbol} from Tradier")
                        return d
                except (ConnectionError, TimeoutError, ValueError) as e:
                    logger.debug(f"Tradier historical failed for {symbol}: {e}")
            return None

        try:
            data = await self._deduplicator.deduplicated_call(
                key=f"historical:{symbol}:{days}", coro_factory=fetch_historical
            )

            if data:
                self._historical_cache.set(symbol, data, days=days)
                # Persist OHLCV to local DB for future scans
                if self._local_db_enabled and self._local_db_provider:
                    try:
                        await self._local_db_provider.save_daily_prices_from_tuple(symbol, data)
                    except Exception as e:
                        logger.debug(f"Failed to persist OHLCV for {symbol}: {e}")
                return data
            elif local_data:
                # API failed — graceful degradation with incomplete local data
                logger.debug(f"API failed for {symbol}, using incomplete local data")
                self._historical_cache.set(symbol, local_data, days=days)
                return local_data

            return None

        except (ConnectionError, TimeoutError, ValueError) as e:
            logger.warning(f"Failed to fetch historical data for {symbol}: {e}")
            # Graceful degradation: return incomplete local data if available
            if local_data:
                logger.debug(f"Using incomplete local data for {symbol} after API error")
                return local_data
            return None

    async def _apply_earnings_prefilter(
        self,
        symbols: List[str],
        min_days: int,
        for_earnings_dip: bool = False,
        include_dip_candidates: bool = False,
    ) -> Tuple[List[str], int, int]:
        """
        Apply earnings pre-filter to symbols.

        KRITISCH: Diese Methode filtert Symbole mit nahenden Earnings heraus.

        BMO/AMC-Handling:
        - AMC (After Market Close) am Tag X: Reaktion erst am Tag X+1 -> Tag X NICHT sicher
        - BMO (Before Market Open) am Tag X: Reaktion bereits eingepreist -> kann sicher sein

        Konservative Defaults:
        - Unknown earnings = NICHT sicher (frueher: erlaubt)
        - BMO am selben Tag = NICHT sicher (konfigurierbar)

        OPTIMIZATION (DEBT-003): Uses batch query instead of N+1 individual queries.
        """
        from datetime import date as date_type

        from .cache import get_earnings_history_manager

        if self._earnings_fetcher is None:
            self._earnings_fetcher = get_earnings_fetcher()

        earnings_history = get_earnings_history_manager()

        # Config for BMO handling
        scanner_config = self._config.settings.scanner
        allow_bmo_same_day = getattr(scanner_config, "earnings_allow_bmo_same_day", False)

        safe_symbols: List[str] = []
        excluded_count = 0
        cache_hits = 0
        today = date_type.today()

        # Separate ETFs (no earnings check needed) from stocks
        etf_symbols = [s for s in symbols if is_etf(s)]
        stock_symbols = [s for s in symbols if not is_etf(s)]

        # ETFs are always safe
        safe_symbols.extend(etf_symbols)

        if not stock_symbols:
            return safe_symbols, excluded_count, cache_hits

        # BATCH QUERY: Get earnings safety for all stocks in ONE query
        batch_results = await earnings_history.is_earnings_day_safe_batch_async(
            stock_symbols, today, min_days, allow_bmo_same_day
        )

        # Collect symbols that need fallback (no DB data)
        symbols_needing_fallback: List[str] = []

        for symbol in stock_symbols:
            symbol_upper = symbol.upper()
            result = batch_results.get(symbol_upper, (False, None, "no_earnings_data"))
            is_safe, days_to, reason = result

            if reason == "no_earnings_data":
                symbols_needing_fallback.append(symbol)
            elif for_earnings_dip:
                # Earnings Dip: Needs recent past earnings
                if days_to is not None and -10 <= days_to <= 0:
                    safe_symbols.append(symbol)
                else:
                    excluded_count += 1
            else:
                # Normal strategies: use BMO/AMC-aware result
                if is_safe:
                    safe_symbols.append(symbol)
                elif include_dip_candidates and days_to is not None and -10 <= days_to <= 0:
                    # In ALL/BEST_SIGNAL mode: keep symbols with recent past earnings
                    # for the earnings_dip strategy. The scanner's per-strategy
                    # _should_skip_for_earnings() will filter them for non-dip strategies.
                    safe_symbols.append(symbol)
                else:
                    logger.debug(f"{symbol}: Excluded - {reason} (days_to={days_to})")
                    excluded_count += 1

        # Handle fallback symbols (no DB data) - use EarningsFetcher
        for symbol in symbols_needing_fallback:
            try:
                cached = self._earnings_fetcher.cache.get(symbol)
                if cached:
                    cache_hits += 1
                    days_to = cached.days_to_earnings
                else:
                    fetched = await asyncio.to_thread(self._earnings_fetcher.fetch, symbol)
                    days_to = fetched.days_to_earnings if fetched else None

                # Fallback logic: conservative for unknown data
                if for_earnings_dip:
                    if days_to is not None and -10 <= days_to <= 0:
                        safe_symbols.append(symbol)
                    else:
                        excluded_count += 1
                else:
                    if days_to is not None and days_to < 0:
                        # Past earnings date = safe (next earnings ~90d away)
                        logger.debug(f"{symbol}: Past earnings ({days_to}d ago) — treating as safe")
                        safe_symbols.append(symbol)
                    elif days_to is not None and days_to >= min_days:
                        safe_symbols.append(symbol)
                    elif include_dip_candidates and days_to is not None and -10 <= days_to <= 0:
                        # Keep recent-earnings symbols for dip strategy in multi-mode
                        safe_symbols.append(symbol)
                    elif days_to is None:
                        logger.debug(f"{symbol}: Excluded - unknown earnings date")
                        excluded_count += 1
                    else:
                        excluded_count += 1

            except (ValueError, KeyError, TypeError) as e:
                logger.debug(f"Earnings check failed for {symbol}: {e}")
                excluded_count += 1

        return safe_symbols, excluded_count, cache_hits

    async def _get_quote_cached(self, symbol: str) -> Optional[Any]:
        """Get quote with caching and request deduplication."""
        symbol = symbol.upper()
        cache_ttl = self._config.settings.performance.cache_ttl_intraday

        if symbol in self._quote_cache:
            quote, timestamp = self._quote_cache[symbol]
            age = (datetime.now() - timestamp).total_seconds()
            if age < cache_ttl:
                self.state.quote_cache.record_hit()
                logger.debug(f"Quote cache HIT: {symbol} (age: {age:.0f}s)")
                return quote

        async def fetch_quote() -> Optional[Any]:
            await self._ensure_connected()
            if self._tradier_connected and self._tradier_provider:
                try:
                    q = await self._tradier_provider.get_quote(symbol)
                    if q and q.last:
                        self._orchestrator.record_request(ProviderType.TRADIER, success=True)
                        return q
                except (ConnectionError, TimeoutError, ValueError) as e:
                    logger.debug(f"Tradier quote failed for {symbol}: {e}")
                    self._orchestrator.record_request(
                        ProviderType.TRADIER, success=False, error=str(e)
                    )
            return None

        quote = await self._deduplicator.deduplicated_call(
            key=f"quote:{symbol}", coro_factory=fetch_quote
        )

        self._quote_cache[symbol] = (quote, datetime.now())
        self.state.quote_cache.record_miss()
        self.state.quote_cache.set_current_entries(len(self._quote_cache))
        logger.debug(f"Quote cache MISS: {symbol}")

        return quote

    def _get_quote_cache_stats(self) -> Dict[str, Any]:
        """Get quote cache statistics from ServerState."""
        stats = self.state.quote_cache
        total = stats.total_requests
        hit_rate = round(stats.hit_rate_pct, 1)
        return {
            "entries": len(self._quote_cache),
            "hits": stats.hits,
            "misses": stats.misses,
            "hit_rate_percent": hit_rate,
        }

    def _get_scan_cache_stats(self) -> Dict[str, Any]:
        """Get scan cache statistics from ServerState."""
        stats = self.state.scan_cache
        hit_rate = round(stats.hit_rate_pct, 1)
        return {
            "entries": len(self._scan_cache),
            "hits": stats.hits,
            "misses": stats.misses,
            "hit_rate_percent": hit_rate,
            "ttl_seconds": self._scan_cache_ttl,
        }

    async def disconnect(self) -> None:
        """Disconnect from all data providers."""
        if self._tradier_provider and self._tradier_connected:
            await self._tradier_provider.disconnect()
            self._tradier_connected = False
            self._orchestrator.enable_tradier(False)
            self.state.connection.mark_disconnected()
            logger.info("Tradier disconnected")

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    async def health_check(self) -> str:
        """Get server status."""
        from .utils.markdown_builder import MarkdownBuilder

        cfg = self._config
        scanner_cfg = cfg.settings.scanner
        loader = get_watchlist_loader()

        ibkr_host = None
        ibkr_port = None
        if IBKR_AVAILABLE and self._ibkr_bridge:
            ibkr_host = self._ibkr_bridge.host
            ibkr_port = self._ibkr_bridge.port

        tradier_available = bool(self._tradier_api_key)
        tradier_environment = None
        if tradier_available:
            tradier_environment = cfg.settings.tradier.environment
            # Trigger lazy connection so health check reflects actual status
            if not self._tradier_connected:
                await self._ensure_tradier_connected()

        # Local DB stats
        local_db_stats = None
        if self._local_db_enabled and self._local_db_provider:
            local_db_stats = self._local_db_provider.stats()

        data = HealthCheckData(
            version=self.VERSION,
            api_key_masked=self.api_key_masked,
            connected=self.state.connection.is_connected,
            current_vix=self.state.vix.current_value,
            vix_updated=self.state.vix.updated_at,
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
            tradier_api_key_masked=(
                mask_api_key(self._tradier_api_key) if self._tradier_api_key else None
            ),
            tradier_environment=tradier_environment,
            local_db_enabled=self._local_db_enabled,
            local_db_stats=local_db_stats,
        )

        return formatters.health_check.format(data)

    async def get_cache_stats(self) -> str:
        """Get detailed cache statistics."""
        from .utils.markdown_builder import MarkdownBuilder

        b = MarkdownBuilder()
        b.h1("Cache Statistics").blank()

        # Historical cache
        hist_stats = self._historical_cache.stats()
        b.h2("Historical Data Cache")
        b.kv_line("Entries", hist_stats.get("entries", 0))
        b.kv_line("Hits", hist_stats.get("hits", 0))
        b.kv_line("Misses", hist_stats.get("misses", 0))
        b.kv_line("Hit Rate", f"{hist_stats.get('hit_rate_percent', 0)}%")
        b.blank()

        # Quote cache
        quote_stats = self._get_quote_cache_stats()
        b.h2("Quote Cache")
        b.kv_line("Entries", quote_stats["entries"])
        b.kv_line("Hits", quote_stats["hits"])
        b.kv_line("Misses", quote_stats["misses"])
        b.kv_line("Hit Rate", f"{quote_stats['hit_rate_percent']}%")
        b.blank()

        # Deduplicator stats
        dedup_stats = self._deduplicator.stats()
        b.h2("Request Deduplication")
        b.kv_line("Total Requests", dedup_stats["total_requests"])
        b.kv_line("Actual API Calls", dedup_stats["actual_calls"])
        b.kv_line("Deduplicated", dedup_stats["deduplicated"])
        b.kv_line("Dedup Rate", f"{dedup_stats['dedup_rate_percent']}%")
        b.blank()

        # Scan cache
        scan_stats = self._get_scan_cache_stats()
        b.h2("Scan Results Cache")
        b.kv_line("Entries", scan_stats["entries"])
        b.kv_line("Hits", scan_stats["hits"])
        b.kv_line("Misses", scan_stats["misses"])
        b.kv_line("Hit Rate", f"{scan_stats['hit_rate_percent']}%")
        b.kv_line("TTL", f"{scan_stats['ttl_seconds']}s")

        return b.build()

    def get_watchlist_info(self) -> str:
        """Get information about the current watchlist."""
        from .config import get_watchlist_loader
        from .utils.markdown_builder import MarkdownBuilder

        loader = get_watchlist_loader()
        all_symbols = loader.get_all_symbols()
        sectors = loader.get_all_sectors()

        b = MarkdownBuilder()
        b.h1("Watchlist Overview").blank()
        b.kv_line("Total Symbols", len(all_symbols))
        b.kv_line("Total Sectors", len(sectors))
        b.blank()

        b.h2("Sectors")
        for sector in sorted(sectors):
            sector_symbols = loader.get_symbols_by_sector(sector)
            b.kv_line(sector, len(sector_symbols))

        return b.build()


# =============================================================================
# CLI & INTERACTIVE MODE
# =============================================================================


async def run_interactive() -> None:
    """Interactive test mode."""
    print("=" * 60)
    print(f"  OPTIONPLAY SERVER v{OptionPlayServer.VERSION} - INTERACTIVE MODE")
    print("=" * 60)

    server = OptionPlayServer()

    # Commands: (handler_attr, method_name, required_args, is_sync)
    commands = {
        "vix": ("vix", "get_strategy_recommendation", [], False),
        "scan": ("scan", "scan_with_strategy", [], False),
        "bounce": ("scan", "scan_bounce", [], False),
        "breakout": ("scan", "scan_ath_breakout", [], False),
        "earningsdip": ("scan", "scan_earnings_dip", [], False),
        "trend": ("scan", "scan_trend_continuation", [], False),
        "multi": ("scan", "scan_multi_strategy", [], False),
        "analyzem": ("analysis", "analyze_multi_strategy", ["symbol"], False),
        "quote": ("quote", "get_quote", ["symbol"], False),
        "options": ("quote", "get_options_chain", ["symbol"], False),
        "earnings": ("quote", "get_earnings", ["symbol"], False),
        "analyze": ("analysis", "analyze_symbol", ["symbol"], False),
        "health": (None, "health_check", [], False),
        "ibkr": ("ibkr", "get_ibkr_status", [], False),
        "pf": ("portfolio", "portfolio_summary", [], True),
    }

    print("\nAvailable commands:")
    for cmd, (_, _, req_args, _) in commands.items():
        args_str = " ".join(f"<{a}>" for a in req_args) if req_args else ""
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

            handler_attr, method_name, required_args, is_sync = commands[cmd]

            if required_args and not args:
                print(f"Missing: {', '.join(required_args)}")
                continue

            # Get method from handler or server directly
            if handler_attr is None:
                method = getattr(server, method_name)
            else:
                handler = getattr(server.handlers, handler_attr)
                method = getattr(handler, method_name)

            if args:
                result = await method(args[0])
            else:
                if is_sync:
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


async def quick_test() -> None:
    """Quick test of functions."""
    print("=" * 60)
    print(f"  OPTIONPLAY v{OptionPlayServer.VERSION} - QUICK TEST")
    print("=" * 60)

    server = OptionPlayServer()

    print("\n1. VIX & Strategy...")
    result = await server.handlers.vix.get_strategy_recommendation()
    print(result)

    print("\n2. Health Check...")
    result = await server.health_check()
    print(result)

    await server.disconnect()
    print("\n[OK] All tests completed!")


def main() -> None:
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
