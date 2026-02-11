"""
Handler Container - Composition-basierte Handler-Verwaltung
============================================================

Ersetzt die Mixin-basierte Vererbung mit Composition Pattern.

Vorteile:
- Keine komplexe Method Resolution Order (MRO)
- Einfachere Testbarkeit (einzelne Handler können gemockt werden)
- Klarere Abhängigkeiten
- Flexiblere Handler-Konfiguration

Usage:
    container = HandlerContainer(server_context)

    # Handler werden on-demand erstellt (lazy initialization)
    await container.vix.get_strategy_recommendation()
    await container.scan.scan_multi_strategy()
    await container.quote.get_quote("AAPL")

Für Rückwärtskompatibilität delegiert OptionPlayServer alle Aufrufe
an die entsprechenden Handler.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..cache import EarningsFetcher, HistoricalCache
    from ..config import Config
    from ..container import ServiceContainer
    from ..data_providers.tradier import TradierProvider
    from ..scanner.multi_strategy_scanner import MultiStrategyScanner
    from ..state.server_state import ServerState
    from ..utils.circuit_breaker import CircuitBreaker
    from ..utils.rate_limiter import AdaptiveRateLimiter
    from ..utils.request_dedup import RequestDeduplicator
    from ..vix_strategy import VIXStrategySelector

logger = logging.getLogger(__name__)


class ServerContext:
    """
    Shared context providing access to server resources.

    Passed to all handlers so they can access shared state
    without tight coupling to the server class itself.
    """

    def __init__(
        self,
        config: "Config",
        provider: Optional["MarketDataProvider"],
        tradier_provider: Optional["TradierProvider"],
        rate_limiter: "AdaptiveRateLimiter",
        circuit_breaker: "CircuitBreaker",
        historical_cache: "HistoricalCache",
        vix_selector: "VIXStrategySelector",
        deduplicator: "RequestDeduplicator",
        container: Optional["ServiceContainer"] = None,
        server_state: Optional["ServerState"] = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.tradier_provider = tradier_provider
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker
        self.historical_cache = historical_cache
        self.vix_selector = vix_selector
        self.deduplicator = deduplicator
        self.container = container
        self.server_state = server_state

        # Mutable state (shared across handlers)
        self.connected = False
        self.tradier_connected = False
        self.current_vix: Optional[float] = None
        self.vix_updated = None

        # Caches
        self.quote_cache = {}
        self.scan_cache = {}
        self.scan_cache_ttl = 1800

        # Stats
        self.quote_cache_hits = 0
        self.quote_cache_misses = 0
        self.scan_cache_hits = 0
        self.scan_cache_misses = 0

        # Tradier lazy init
        self.tradier_api_key: Optional[str] = None

        # Optional components
        self.earnings_fetcher: Optional["EarningsFetcher"] = None
        self.scanner: Optional["MultiStrategyScanner"] = None
        self.ibkr_bridge = None


class BaseHandler:
    """
    Base class for all handlers.

    Provides access to the shared ServerContext.
    """

    def __init__(self, context: ServerContext) -> None:
        self._ctx = context
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def config(self) -> "Config":
        return self._ctx.config

    @property
    def tradier_provider(self) -> Optional["TradierProvider"]:
        return self._ctx.tradier_provider

    async def _ensure_tradier_connected(self) -> Optional["TradierProvider"]:
        """Establish connection to Tradier API if key is available."""
        if self._ctx.tradier_connected:
            return self._ctx.tradier_provider

        # Lazy-create provider if API key is available but provider not yet created
        if self._ctx.tradier_provider is None and self._ctx.tradier_api_key:
            from ..data_providers.tradier import TradierEnvironment, TradierProvider

            tradier_cfg = self._ctx.config.settings.tradier
            env = (
                TradierEnvironment.PRODUCTION
                if tradier_cfg.is_production
                else TradierEnvironment.SANDBOX
            )
            self._ctx.tradier_provider = TradierProvider(
                api_key=self._ctx.tradier_api_key,
                environment=env,
            )

        if not self._ctx.tradier_provider:
            return None

        try:
            connected = await self._ctx.tradier_provider.connect()
            if connected:
                self._ctx.tradier_connected = True
                self._logger.info("Tradier connected")
            else:
                self._logger.debug("Tradier connection returned False")
        except (ConnectionError, TimeoutError, OSError) as e:
            self._logger.debug(f"Tradier connection failed: {e}")

        return self._ctx.tradier_provider if self._ctx.tradier_connected else None

    async def _ensure_connected(self) -> Optional["TradierProvider"]:
        """Ensure Tradier provider is connected."""
        return await self._ensure_tradier_connected()

    async def _get_quote_cached(self, symbol: str) -> Optional[Any]:
        """Get quote with caching via Tradier."""
        from datetime import datetime

        now = datetime.now()
        if symbol in self._ctx.quote_cache:
            cached_quote, cached_time = self._ctx.quote_cache[symbol]
            if (now - cached_time).total_seconds() < 60:
                self._ctx.quote_cache_hits += 1
                return cached_quote

        self._ctx.quote_cache_misses += 1
        await self._ensure_connected()

        if self._ctx.tradier_connected and self._ctx.tradier_provider:
            try:
                quote = await self._ctx.tradier_provider.get_quote(symbol)
                if quote and quote.last:
                    self._ctx.quote_cache[symbol] = (quote, now)
                    return quote
            except Exception as e:
                self._logger.debug(f"Tradier quote failed for {symbol}: {e}")

        return None

    async def _get_vix(self) -> Optional[float]:
        """Get current VIX value. Chain: cache → IBKR → Tradier → Yahoo Finance."""
        from datetime import datetime

        # 1. Check cache
        if self._ctx.current_vix is not None:
            return self._ctx.current_vix

        # 2. Try IBKR bridge
        if self._ctx.ibkr_bridge:
            try:
                vix = await self._ctx.ibkr_bridge.get_vix_value()
                if vix is not None:
                    self._ctx.current_vix = vix
                    self._ctx.vix_updated = datetime.now()
                    return vix
            except Exception as e:
                self._logger.debug(f"IBKR VIX failed: {e}")

        # 3. Try Tradier quote for VIX index
        await self._ensure_connected()
        if self._ctx.tradier_connected and self._ctx.tradier_provider:
            try:
                quote = await self._ctx.tradier_provider.get_quote("VIX")
                if quote and hasattr(quote, "last") and quote.last:
                    self._ctx.current_vix = quote.last
                    self._ctx.vix_updated = datetime.now()
                    return quote.last
            except Exception as e:
                self._logger.debug(f"Tradier VIX quote failed: {e}")

        # 4. Fall back to Yahoo Finance
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

    def _fetch_vix_yahoo(self) -> Optional[float]:
        """Fetch VIX from Yahoo Finance as fallback."""
        import json
        import urllib.request

        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
            timeout = self._ctx.config.settings.api_connection.yahoo_timeout

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")

            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode())

            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})

            regular_price = meta.get("regularMarketPrice")
            if regular_price:
                return float(regular_price)

            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if closes:
                for c in reversed(closes):
                    if c is not None:
                        return float(c)

            return None
        except Exception as e:
            self._logger.debug(f"Yahoo VIX fetch error: {e}")
            return None


class HandlerContainer:
    """
    Container holding all handler instances.

    Uses lazy initialization - handlers are created on first access.
    This improves startup performance and allows flexible configuration.
    """

    def __init__(self, context: ServerContext) -> None:
        self._context = context

        # Lazy-initialized handlers
        self._vix: Optional[Any] = None
        self._scan: Optional[Any] = None
        self._quote: Optional[Any] = None
        self._analysis: Optional[Any] = None
        self._portfolio: Optional[Any] = None
        self._ibkr: Optional[Any] = None
        self._report: Optional[Any] = None
        self._risk: Optional[Any] = None
        self._validate: Optional[Any] = None
        self._monitor: Optional[Any] = None

    @property
    def vix(self) -> "VixHandler":
        """VIX and strategy handler."""
        if self._vix is None:
            from .vix_composed import VixHandler

            self._vix = VixHandler(self._context)
        return self._vix

    @property
    def scan(self) -> "ScanHandler":
        """Scan operations handler."""
        if self._scan is None:
            from .scan_composed import ScanHandler

            self._scan = ScanHandler(self._context)
        return self._scan

    @property
    def quote(self) -> "QuoteHandler":
        """Quote and market data handler."""
        if self._quote is None:
            from .quote_composed import QuoteHandler

            self._quote = QuoteHandler(self._context)
        return self._quote

    @property
    def analysis(self) -> "AnalysisHandler":
        """Symbol analysis handler."""
        if self._analysis is None:
            from .analysis_composed import AnalysisHandler

            self._analysis = AnalysisHandler(self._context)
        return self._analysis

    @property
    def portfolio(self) -> "PortfolioHandler":
        """Portfolio management handler."""
        if self._portfolio is None:
            from .portfolio_composed import PortfolioHandler

            self._portfolio = PortfolioHandler(self._context)
        return self._portfolio

    @property
    def ibkr(self) -> "IbkrHandler":
        """IBKR Bridge handler."""
        if self._ibkr is None:
            from .ibkr_composed import IbkrHandler

            self._ibkr = IbkrHandler(self._context)
        return self._ibkr

    @property
    def report(self) -> "ReportHandler":
        """Report generation handler."""
        if self._report is None:
            from .report_composed import ReportHandler

            self._report = ReportHandler(self._context)
        return self._report

    @property
    def risk(self) -> "RiskHandler":
        """Risk management handler."""
        if self._risk is None:
            from .risk_composed import RiskHandler

            self._risk = RiskHandler(self._context)
        return self._risk

    @property
    def validate(self) -> "ValidateHandler":
        """Trade validation handler."""
        if self._validate is None:
            from .validate_composed import ValidateHandler

            self._validate = ValidateHandler(self._context)
        return self._validate

    @property
    def monitor(self) -> "MonitorHandler":
        """Position monitoring handler."""
        if self._monitor is None:
            from .monitor_composed import MonitorHandler

            self._monitor = MonitorHandler(self._context)
        return self._monitor


def create_handler_container_from_server(server) -> HandlerContainer:
    """
    Create a HandlerContainer from an existing OptionPlayServer.

    This bridges the old Mixin-based architecture with the new
    Composition-based architecture.

    Args:
        server: OptionPlayServer instance

    Returns:
        HandlerContainer with shared context
    """
    context = ServerContext(
        config=server._config,
        provider=server._provider,
        tradier_provider=getattr(server, "_tradier_provider", None),
        rate_limiter=server._rate_limiter,
        circuit_breaker=server._circuit_breaker,
        historical_cache=server._historical_cache,
        vix_selector=server._vix_selector,
        deduplicator=server._deduplicator,
        container=getattr(server, "_container", None),
        server_state=getattr(server, "state", None),
    )

    # Copy mutable state
    context.connected = server._connected
    context.tradier_connected = getattr(server, "_tradier_connected", False)
    context.tradier_api_key = getattr(server, "_tradier_api_key", None)
    context.current_vix = server._current_vix
    context.vix_updated = server._vix_updated
    context.quote_cache = server._quote_cache
    context.scan_cache = server._scan_cache
    context.earnings_fetcher = server._earnings_fetcher
    context.scanner = getattr(server, "_scanner", None)
    context.ibkr_bridge = getattr(server, "_ibkr_bridge", None)

    return HandlerContainer(context)
