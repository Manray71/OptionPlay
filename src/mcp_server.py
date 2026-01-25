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
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Local imports
from .data_providers.marketdata import MarketDataProvider
from .scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig, ScanMode
from .cache import EarningsFetcher, get_earnings_fetcher, EarningsInfo, get_historical_cache, CacheStatus
from .vix_strategy import VIXStrategySelector, get_strategy_for_vix, format_recommendation
from .utils.rate_limiter import get_marketdata_limiter, AdaptiveRateLimiter
from .utils.validation import validate_symbol, validate_symbols, validate_dte_range, ValidationError
from .utils.secure_config import get_api_key, mask_api_key
from .utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, get_circuit_breaker
from .utils.error_handler import mcp_endpoint, sync_endpoint, format_error_response, truncate_string
from .utils.markdown_builder import MarkdownBuilder, format_price, format_volume, truncate
from .utils.metrics import metrics
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
from .indicators.support_resistance import find_support_levels, calculate_fibonacci
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

        # IBKR Bridge (optional)
        self._ibkr_bridge: Optional["IBKRBridge"] = None
        if IBKR_AVAILABLE:
            self._ibkr_bridge = get_ibkr_bridge()
    
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
    
    async def _ensure_connected(self) -> MarketDataProvider:
        """
        Establish connection to Marketdata.app with retry logic and circuit breaker.
        
        Returns:
            Connected MarketDataProvider instance
            
        Raises:
            CircuitBreakerOpen: If circuit breaker is open
            ConnectionError: If connection fails after retries
        """
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
        config = ScanConfig(
            min_score=min_score,
            enable_pullback=enable_pullback,
            enable_bounce=enable_bounce,
            enable_ath_breakout=enable_breakout,
            enable_earnings_dip=enable_earnings_dip,
        )
        return MultiStrategyScanner(config)
    
    async def _fetch_historical_cached(
        self,
        symbol: str,
        days: Optional[int] = None
    ) -> Optional[tuple]:
        """
        Fetch historical data with caching.
        
        Args:
            symbol: Ticker symbol
            days: Number of days (default: from config)
            
        Returns:
            Tuple of (prices, volumes, highs, lows) or None
        """
        if days is None:
            days = self._config.settings.performance.historical_days
        
        # Check cache
        cache_result = self._historical_cache.get(symbol, days)
        
        if cache_result.status == CacheStatus.HIT:
            logger.debug(f"Cache hit for {symbol} ({days}d)")
            return cache_result.data
        
        # Load from API
        try:
            provider = await self._ensure_connected()
            await self._rate_limiter.acquire()
            data = await provider.get_historical_for_scanner(symbol, days=days)
            self._rate_limiter.record_success()
            
            if data:
                self._historical_cache.set(symbol, data, days=days)
            
            return data
            
        except Exception as e:
            logger.warning(f"Failed to fetch historical data for {symbol}: {e}")
            return None

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

        # Determine historical data requirement
        config_days = self._config.settings.performance.historical_days
        historical_days = max(config_days, min_historical_days) if min_historical_days else config_days

        async def data_fetcher(symbol: str):
            return await self._fetch_historical_cached(symbol, days=historical_days)

        # Execute scan
        start_time = datetime.now()
        result = await scanner.scan_async(
            symbols=symbols,
            data_fetcher=data_fetcher,
            mode=mode
        )
        duration = (datetime.now() - start_time).total_seconds()

        # Build output
        b = MarkdownBuilder()
        b.h1(f"{emoji} {title}").blank()
        b.kv("Scanned", f"{len(symbols)} symbols")
        b.kv("With Signals", result.symbols_with_signals)
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
        """Disconnect from data provider."""
        if self._provider and self._connected:
            await self._provider.disconnect()
            self._connected = False
            logger.info("Disconnected")
    
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
        
        await self._rate_limiter.acquire()
        quote = await provider.get_quote(symbol)
        self._rate_limiter.record_success()
        
        vix = await self.get_vix()
        
        scanner = self._get_multi_scanner(min_score=0)
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
        provider = await self._ensure_connected()
        
        await self._rate_limiter.acquire()
        quote = await provider.get_quote(symbol)
        self._rate_limiter.record_success()
        
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
        """Get options chain for a symbol."""
        symbol = validate_symbol(symbol)
        dte_min, dte_max = validate_dte_range(dte_min, dte_max)
        provider = await self._ensure_connected()
        
        await self._rate_limiter.acquire()
        quote = await provider.get_quote(symbol)
        self._rate_limiter.record_success()
        
        underlying_price = quote.last if quote else None
        
        await self._rate_limiter.acquire()
        options = await provider.get_option_chain(
            symbol,
            dte_min=dte_min,
            dte_max=dte_max,
            right=right.upper()
        )
        self._rate_limiter.record_success()
        
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
        cache_hits = 0
        api_calls = 0

        for symbol in symbols:
            try:
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
        b.kv_line("✅ Safe (>= min_days)", len(safe_symbols) - len(unknown_symbols))
        b.kv_line("❌ Excluded (< min_days)", len(excluded_symbols))
        b.kv_line("⚠️ Unknown (no date)", len(unknown_symbols))
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
        
        await self._rate_limiter.acquire()
        quote = await provider.get_quote(symbol)
        self._rate_limiter.record_success()
        
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
            status = "✅ SAFE" if is_safe else "⚠️ TOO CLOSE"
            b.kv_line("Date", earnings.earnings_date)
            b.kv_line("Days", f"{earnings.days_to_earnings} (Min: {recommendation.earnings_buffer_days})")
            b.kv_line("Status", status)
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
        
        # 1. Get current quote
        await self._rate_limiter.acquire()
        quote = await provider.get_quote(symbol)
        self._rate_limiter.record_success()
        
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
                    "iv": opt.iv,
                    "dte": opt.dte,
                }
                for opt in options
            ]
        
        # 6. Get recommendations
        recommender = StrikeRecommender()
        
        # Primary recommendation
        primary = recommender.get_recommendation(
            symbol=symbol,
            current_price=current_price,
            support_levels=support_levels,
            options_data=options_data,
            fib_levels=fib_levels,
            dte=dte_min + (dte_max - dte_min) // 2  # Mid-point DTE
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
        
        # 7. Build output
        b = MarkdownBuilder()
        b.h1(f"🎯 Strike Recommendation: {symbol}").blank()
        
        # Current price and context
        b.kv_line("Current Price", f"${current_price:.2f}")
        b.kv_line("DTE Range", f"{dte_min}-{dte_max} days")
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
        
        b = MarkdownBuilder()
        b.h1("Cache Statistics").blank()
        b.kv_line("Entries", f"{cache_stats['entries']}/{cache_stats['max_entries']}")
        b.kv_line("Hit Rate", f"{cache_stats['hit_rate_percent']}%")
        
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
