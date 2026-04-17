# OptionPlay - Scanner Service
# =============================
"""
Service für Multi-Strategy Scanning.

Verantwortlichkeiten:
- Pullback Scanning (Bull-Put-Spreads)
- Support Bounce Scanning
- Multi-Strategy Scanning

Konsolidiert die duplizierten Scanner-Methoden aus mcp_server.py.

Verwendung:
    from src.services import ScannerService
    from src.services.base import create_service_context

    context = create_service_context()
    scanner = ScannerService(context)

    result = await scanner.scan(Strategy.PULLBACK, symbols=["AAPL", "MSFT"])
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from ..cache import CacheStatus
from ..config import get_config, get_scan_config, get_watchlist_loader
from ..constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS
from ..formatters import formatters
from ..models.result import ServiceResult
from ..models.strategy import Strategy
from ..scanner.multi_strategy_scanner import (
    MultiStrategyScanner,
    ScanConfig,
    ScanMode,
    ScanResult,
)
from ..services.vix_strategy import StrategyRecommendation, get_strategy_for_vix
from ..utils.markdown_builder import MarkdownBuilder, truncate
from ..utils.validation import validate_symbols
from .base import BaseService, ServiceContext
from .vix_service import VIXService

logger = logging.getLogger(__name__)


# Mapping von Strategy zu ScanMode
STRATEGY_TO_MODE = {
    Strategy.PULLBACK: ScanMode.PULLBACK_ONLY,
    Strategy.BOUNCE: ScanMode.BOUNCE_ONLY,
}


class ScannerService(BaseService):
    """
    Service für Multi-Strategy Scanning.

    Konsolidiert alle Scanner-Funktionalität in einer Klasse
    mit einheitlicher Schnittstelle.

    Features:
    - Single-Strategy Scans
    - Multi-Strategy Scans
    - VIX-basierte Parameter-Anpassung
    - Historical Data Caching

    Attributes:
        _vix_service: VIX Service für Strategie-Parameter
    """

    def __init__(self, context: ServiceContext, vix_service: Optional[VIXService] = None) -> None:
        """
        Initialisiert den Scanner Service.

        Args:
            context: Shared ServiceContext
            vix_service: Optional VIX Service (wird erstellt wenn nicht übergeben)
        """
        super().__init__(context)
        self._vix_service = vix_service or VIXService(context)

    async def scan(
        self,
        strategy: Strategy,
        symbols: Optional[list[str]] = None,
        max_results: int = 10,
        min_score: Optional[float] = None,
        use_vix_strategy: bool = True,
    ) -> ServiceResult[ScanResult]:
        """
        Führt einen Scan mit der angegebenen Strategie durch.

        Unified Interface für alle Strategien. Ersetzt die duplizierten
        Methoden scan_bounce, etc.

        Args:
            strategy: Die zu verwendende Strategie
            symbols: Symbole zum Scannen (default: Watchlist)
            max_results: Maximale Anzahl Ergebnisse
            min_score: Minimaler Score (default: strategie-spezifisch)
            use_vix_strategy: VIX-basierte Parameter verwenden

        Returns:
            ServiceResult mit ScanResult
        """
        start_time = datetime.now()

        # Ensure connected
        try:
            await self._get_provider()
        except Exception as e:
            return ServiceResult.fail(f"Connection failed: {e}")

        # Get VIX-based recommendation if requested
        recommendation: Optional[StrategyRecommendation] = None
        vix: Optional[float] = None

        if use_vix_strategy and strategy.suitable_for_credit_spreads:
            rec_result = await self._vix_service.get_strategy_recommendation()
            if rec_result.success:
                recommendation = rec_result.data
                vix = self._vix_service.current_vix

        # Load symbols
        symbols = await self._prepare_symbols(symbols)
        if not symbols:
            return ServiceResult.fail("No valid symbols to scan")

        # Determine min_score
        effective_min_score = self._determine_min_score(strategy, min_score, recommendation)

        # Create scanner
        scanner = self._create_scanner(strategy, effective_min_score, recommendation)
        scanner.config.max_total_results = max_results

        # Historical days based on strategy
        historical_days = self._get_historical_days(strategy)

        # Data fetcher with caching
        async def data_fetcher(symbol: str) -> Any:
            return await self._fetch_historical_cached(symbol, historical_days)

        # Execute scan
        try:
            mode = STRATEGY_TO_MODE.get(strategy, ScanMode.ALL)
            result = await scanner.scan_async(
                symbols=symbols,
                data_fetcher=data_fetcher,  # type: ignore[arg-type]  # async callback signature differs from scanner's expected type
                mode=mode,
            )

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            return ServiceResult.ok(data=result, source="scanner", duration_ms=duration_ms)

        except Exception as e:
            self._logger.error(f"Scan failed: {e}")
            return ServiceResult.fail(f"Scan failed: {e}")

    async def scan_multi(
        self,
        symbols: Optional[list[str]] = None,
        max_results: int = 20,
        min_score: float = 5.0,
        strategies: Optional[list[Strategy]] = None,
    ) -> ServiceResult[ScanResult]:
        """
        Multi-Strategy Scan - alle Strategien, bestes Signal pro Symbol.

        Args:
            symbols: Symbole zum Scannen (default: Watchlist)
            max_results: Maximale Anzahl Ergebnisse
            min_score: Minimaler Score
            strategies: Optionale Liste der zu verwendenden Strategien

        Returns:
            ServiceResult mit ScanResult
        """
        start_time = datetime.now()

        # Ensure connected
        try:
            await self._get_provider()
        except Exception as e:
            return ServiceResult.fail(f"Connection failed: {e}")

        # Load symbols
        symbols = await self._prepare_symbols(symbols)
        if not symbols:
            return ServiceResult.fail("No valid symbols to scan")

        # Determine which strategies to use
        enable_pullback = strategies is None or Strategy.PULLBACK in strategies
        enable_bounce = strategies is None or Strategy.BOUNCE in strategies

        # Create multi-strategy scanner
        scanner = self._create_multi_scanner(
            min_score=min_score,
            enable_pullback=enable_pullback,
            enable_bounce=enable_bounce,
        )
        scanner.config.max_total_results = max_results * 2

        historical_days = max(self._config.settings.performance.historical_days, 90)

        # Data fetcher with caching
        async def data_fetcher(symbol: str) -> Any:
            return await self._fetch_historical_cached(symbol, historical_days)

        # Execute scan
        try:
            result = await scanner.scan_async(
                symbols=symbols,
                data_fetcher=data_fetcher,  # type: ignore[arg-type]  # async callback signature differs from scanner's expected type
                mode=ScanMode.BEST_SIGNAL,
            )

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            return ServiceResult.ok(data=result, source="multi_scanner", duration_ms=duration_ms)

        except Exception as e:
            self._logger.error(f"Multi-scan failed: {e}")
            return ServiceResult.fail(f"Multi-scan failed: {e}")

    async def scan_formatted(
        self,
        strategy: Strategy,
        symbols: Optional[list[str]] = None,
        max_results: int = 10,
        min_score: Optional[float] = None,
        use_vix_strategy: bool = True,
    ) -> str:
        """
        Führt Scan durch und gibt formatiertes Markdown zurück.

        Convenience-Methode für MCP-Integration.
        """
        result = await self.scan(
            strategy=strategy,
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
            use_vix_strategy=use_vix_strategy,
        )

        if not result.success:
            return f"❌ Scan failed: {result.error}"

        # Get VIX info for formatting
        vix = self._vix_service.current_vix
        recommendation = None
        if use_vix_strategy and strategy.suitable_for_credit_spreads:
            rec_result = await self._vix_service.get_strategy_recommendation()
            if rec_result.success:
                recommendation = rec_result.data

        return self._format_scan_result(
            result.data,
            strategy,
            vix=vix,
            recommendation=recommendation,
            max_results=max_results,
        )

    async def scan_multi_formatted(
        self,
        symbols: Optional[list[str]] = None,
        max_results: int = 20,
        min_score: float = 5.0,
    ) -> str:
        """
        Multi-Strategy Scan mit formatiertem Markdown-Output.
        """
        result = await self.scan_multi(
            symbols=symbols,
            max_results=max_results,
            min_score=min_score,
        )

        if not result.success:
            return f"❌ Multi-scan failed: {result.error}"

        vix = self._vix_service.current_vix
        return self._format_multi_scan_result(
            result.data,
            vix=vix,
            max_results=max_results,
        )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    async def _prepare_symbols(self, symbols: Optional[list[str]]) -> list[str]:
        """Bereitet Symbolliste vor (Validation, Default-Watchlist)."""
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            return watchlist_loader.get_all_symbols()
        return validate_symbols(symbols, skip_invalid=True)

    def _determine_min_score(
        self,
        strategy: Strategy,
        min_score: Optional[float],
        recommendation: Optional[StrategyRecommendation],
    ) -> float:
        """Bestimmt den effektiven min_score."""
        if min_score is not None:
            return min_score
        if recommendation:
            return recommendation.min_score
        return strategy.default_min_score

    def _get_historical_days(self, strategy: Strategy) -> int:
        """Gibt benötigte historische Tage für Strategie zurück."""
        config_days = self._config.settings.performance.historical_days
        return max(config_days, strategy.min_historical_days)

    def _create_scanner(
        self,
        strategy: Strategy,
        min_score: float,
        recommendation: Optional[StrategyRecommendation],
    ) -> MultiStrategyScanner:
        """Erstellt konfigurierten Scanner für einzelne Strategie."""
        earnings_days = (
            recommendation.earnings_buffer_days if recommendation else ENTRY_EARNINGS_MIN_DAYS
        )

        config = get_scan_config(override_min_score=min_score, override_earnings_days=earnings_days)

        # Nur gewünschte Strategie aktivieren
        config.enable_pullback = strategy == Strategy.PULLBACK
        config.enable_bounce = strategy == Strategy.BOUNCE

        return MultiStrategyScanner(config)

    def _create_multi_scanner(
        self,
        min_score: float,
        enable_pullback: bool,
        enable_bounce: bool,
    ) -> MultiStrategyScanner:
        """Erstellt Scanner mit mehreren Strategien."""
        config = ScanConfig(
            min_score=min_score,
            enable_pullback=enable_pullback,
            enable_bounce=enable_bounce,
        )
        return MultiStrategyScanner(config)

    async def _fetch_historical_cached(self, symbol: str, days: int) -> Optional[tuple[Any, ...]]:
        """Holt Historical Data mit Caching."""
        cache = self._get_historical_cache()

        # Check cache
        cache_result = cache.get(symbol, days)
        if cache_result.status == CacheStatus.HIT:
            self._logger.debug(f"Cache hit for {symbol} ({days}d)")
            return cache_result.data

        # Fetch from API
        try:
            provider = await self._get_provider()
            async with self._rate_limited():
                data = await provider.get_historical_for_scanner(symbol, days=days)

            if data:
                cache.set(symbol, data, days=days)

            result: Optional[tuple[Any, ...]] = data
            return result

        except Exception as e:
            self._logger.warning(f"Failed to fetch historical for {symbol}: {e}")
            return None

    def _format_scan_result(
        self,
        result: ScanResult,
        strategy: Strategy,
        vix: Optional[float],
        recommendation: Optional[StrategyRecommendation],
        max_results: int,
    ) -> str:
        """Formatiert ScanResult als Markdown."""
        b = MarkdownBuilder()
        b.h1(f"{strategy.icon} {strategy.display_name} Scan").blank()

        if vix:
            b.kv("VIX", f"{vix:.2f}")
        b.kv("Scanned", f"{result.symbols_scanned} symbols")
        b.kv("With Signals", result.symbols_with_signals)
        b.kv("Duration", f"{result.scan_duration_seconds:.1f}s")
        b.blank()

        if result.signals:
            b.h2("Top Candidates").blank()
            rows = []
            for signal in result.signals[:max_results]:
                details = signal.details or {}
                rsi = details.get("rsi", 0)
                rows.append(
                    [
                        signal.symbol,
                        f"{signal.score:.1f}",
                        f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                        f"{rsi:.0f}" if rsi else "-",
                        truncate(signal.reason, 40) if signal.reason else "-",
                    ]
                )
            b.table(["Symbol", "Score", "Price", "RSI", "Signal"], rows)
        else:
            b.hint("No candidates found.")

        return b.build()

    def _format_multi_scan_result(
        self,
        result: ScanResult,
        vix: Optional[float],
        max_results: int,
    ) -> str:
        """Formatiert Multi-Strategy ScanResult als Markdown."""
        b = MarkdownBuilder()
        b.h1("📊 Multi-Strategy Scan").blank()

        if vix:
            b.kv("VIX", f"{vix:.2f}")
        b.kv("Scanned", f"{result.symbols_scanned} symbols")
        b.kv("With Signals", result.symbols_with_signals)
        b.kv("Duration", f"{result.scan_duration_seconds:.1f}s")
        b.blank()

        if result.signals:
            # Group by strategy
            by_strategy: dict[str, list[Any]] = {}
            for signal in result.signals:
                strat = signal.strategy
                if strat not in by_strategy:
                    by_strategy[strat] = []
                by_strategy[strat].append(signal)

            b.h2("Strategy Summary").blank()
            rows = []
            for strat, sigs in sorted(by_strategy.items(), key=lambda x: -len(x[1])):
                try:
                    strategy_enum = Strategy.from_string(strat)
                    icon = strategy_enum.icon
                    name = strategy_enum.display_name
                except ValueError:
                    icon = "•"
                    name = strat
                top = ", ".join([s.symbol for s in sigs[:3]])
                rows.append([f"{icon} {name}", str(len(sigs)), top])
            b.table(["Strategy", "Count", "Top Symbols"], rows)
            b.blank()

            b.h2("All Candidates").blank()
            rows = []
            for signal in result.signals[:max_results]:
                try:
                    strategy_enum = Strategy.from_string(signal.strategy)
                    icon = strategy_enum.icon
                    name = strategy_enum.display_name
                except ValueError:
                    icon = "•"
                    name = signal.strategy

                rows.append(
                    [
                        signal.symbol,
                        f"{icon} {name}",
                        f"{signal.score:.1f}",
                        f"${signal.current_price:.2f}" if signal.current_price else "N/A",
                        truncate(signal.reason, 30) if signal.reason else "-",
                    ]
                )
            b.table(["Symbol", "Strategy", "Score", "Price", "Signal"], rows)
        else:
            b.hint("No signals found.")

        return b.build()
