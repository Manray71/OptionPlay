# OptionPlay - Quote Service
# ===========================
"""
Service für Quote-Abfragen.

Verantwortlichkeiten:
- Einzelne Quotes abrufen
- Batch-Quotes abrufen
- Caching von Quotes
- Formatierung von Quote-Daten

Ersetzt die Quote-Logik aus mcp_server.py.

Verwendung:
    from src.services import QuoteService
    from src.services.base import create_service_context

    context = create_service_context()
    quote_service = QuoteService(context)

    # Einzelnes Quote
    result = await quote_service.get_quote("AAPL")

    # Batch Quotes
    result = await quote_service.get_batch_quotes(["AAPL", "MSFT", "GOOGL"])
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from .base import BaseService, ServiceContext
from ..models.result import ServiceResult
from ..utils.validation import validate_symbol, validate_symbols, ValidationError
from ..utils.markdown_builder import MarkdownBuilder, format_price, format_volume

logger = logging.getLogger(__name__)


class QuoteService(BaseService):
    """
    Service für Quote-Abfragen.

    Features:
    - In-Memory Quote Cache mit TTL
    - Batch-Abfragen für Effizienz
    - Formatierte Markdown-Ausgabe
    - Rate-limited API Calls

    Attributes:
        _quote_cache: In-Memory Cache für Quotes
        _cache_ttl_seconds: Cache TTL in Sekunden
    """

    # Maximum cache size to prevent memory leaks
    MAX_CACHE_SIZE = 500

    def __init__(
        self,
        context: ServiceContext,
        cache_ttl_seconds: int = 60,
        max_cache_size: int = MAX_CACHE_SIZE
    ):
        """
        Initialisiert den Quote Service.

        Args:
            context: Shared ServiceContext
            cache_ttl_seconds: TTL für Quote Cache (default: 60s)
            max_cache_size: Maximum cache entries (LRU eviction, default: 500)
        """
        super().__init__(context)
        # Use OrderedDict for LRU behavior - most recently used at end
        self._quote_cache: OrderedDict[str, tuple[dict[str, Any], datetime]] = OrderedDict()
        self._cache_ttl_seconds = cache_ttl_seconds
        self._max_cache_size = max_cache_size
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_evictions = 0

    async def get_quote(
        self,
        symbol: str,
        use_cache: bool = True
    ) -> ServiceResult[dict[str, Any]]:
        """
        Holt Quote für ein Symbol.

        Args:
            symbol: Ticker-Symbol
            use_cache: Cache verwenden (default: True)

        Returns:
            ServiceResult mit Quote-Daten
        """
        start_time = datetime.now()

        # Validierung
        try:
            symbol = validate_symbol(symbol)
        except ValidationError as e:
            return ServiceResult.fail(str(e))

        # Cache Check
        if use_cache:
            cached = self._get_from_cache(symbol)
            if cached is not None:
                self._cache_hits += 1
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                return ServiceResult.ok(
                    data=cached,
                    source="cache",
                    duration_ms=duration_ms
                )

        self._cache_misses += 1

        # API Call
        try:
            provider = await self._get_provider()
            async with self._rate_limited():
                quote = await provider.get_quote(symbol)

            if quote is None:
                return ServiceResult.fail(f"No quote data for {symbol}")

            # Quote zu Dict konvertieren
            quote_data = self._quote_to_dict(quote, symbol)

            # Cachen
            self._set_cache(symbol, quote_data)

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ServiceResult.ok(
                data=quote_data,
                source="api",
                duration_ms=duration_ms
            )

        except Exception as e:
            self._logger.error(f"Failed to get quote for {symbol}: {e}")
            return ServiceResult.fail(f"Quote fetch failed: {e}")

    async def get_batch_quotes(
        self,
        symbols: list[str],
        use_cache: bool = True,
        max_concurrent: int = 10
    ) -> ServiceResult[dict[str, dict[str, Any]]]:
        """
        Holt Quotes für mehrere Symbole.

        Args:
            symbols: Liste von Ticker-Symbolen
            use_cache: Cache verwenden (default: True)
            max_concurrent: Max parallele Requests

        Returns:
            ServiceResult mit dict[symbol, quote_data]
        """
        start_time = datetime.now()

        # Validierung
        try:
            symbols = validate_symbols(symbols, skip_invalid=True)
        except ValidationError as e:
            return ServiceResult.fail(str(e))

        if not symbols:
            return ServiceResult.fail("No valid symbols provided")

        # Teile in cached und nicht-cached
        results: dict[str, dict[str, Any]] = {}
        to_fetch: list[str] = []

        if use_cache:
            for symbol in symbols:
                cached = self._get_from_cache(symbol)
                if cached is not None:
                    results[symbol] = cached
                    self._cache_hits += 1
                else:
                    to_fetch.append(symbol)
                    self._cache_misses += 1
        else:
            to_fetch = symbols

        # Fetch fehlende Quotes
        if to_fetch:
            try:
                provider = await self._get_provider()

                # Batch in Chunks aufteilen
                for i in range(0, len(to_fetch), max_concurrent):
                    chunk = to_fetch[i:i + max_concurrent]

                    # Parallele Requests
                    tasks = [
                        self._fetch_single_quote(provider, symbol)
                        for symbol in chunk
                    ]
                    chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Ergebnisse verarbeiten
                    for symbol, result in zip(chunk, chunk_results):
                        if isinstance(result, BaseException):
                            self._logger.warning(f"Quote fetch failed for {symbol}: {result}")
                            continue
                        if result is not None:
                            quote_data: dict[str, Any] = result
                            results[symbol] = quote_data
                            self._set_cache(symbol, quote_data)

            except Exception as e:
                self._logger.error(f"Batch quote fetch failed: {e}")
                # Partial results zurückgeben
                if results:
                    duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                    return ServiceResult.ok(
                        data=results,
                        source="partial",
                        duration_ms=duration_ms,
                    )
                return ServiceResult.fail(f"Batch quote fetch failed: {e}")

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceResult.ok(
            data=results,
            source="api" if to_fetch else "cache",
            duration_ms=duration_ms
        )

    async def get_quote_formatted(self, symbol: str) -> str:
        """
        Holt Quote und formatiert als Markdown.

        Args:
            symbol: Ticker-Symbol

        Returns:
            Formatierter Markdown-String
        """
        result = await self.get_quote(symbol)

        if not result.success:
            return f"❌ Quote failed for {symbol}: {result.error}"

        return self._format_quote(result.data)

    async def get_batch_quotes_formatted(self, symbols: list[str]) -> str:
        """
        Holt Batch Quotes und formatiert als Markdown.

        Args:
            symbols: Liste von Ticker-Symbolen

        Returns:
            Formatierter Markdown-String
        """
        result = await self.get_batch_quotes(symbols)

        if not result.success:
            return f"❌ Batch quote failed: {result.error}"

        return self._format_batch_quotes(result.data)

    def get_cache_stats(self) -> dict[str, Any]:
        """Gibt Cache-Statistiken zurück inkl. LRU-Metriken."""
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total * 100) if total > 0 else 0
        usage_pct = (len(self._quote_cache) / self._max_cache_size * 100)

        return {
            "entries": len(self._quote_cache),
            "max_size": self._max_cache_size,
            "usage_pct": round(usage_pct, 1),
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "evictions": self._cache_evictions,
            "hit_rate_pct": round(hit_rate, 2),
            "ttl_seconds": self._cache_ttl_seconds,
        }

    def clear_cache(self) -> int:
        """Leert den Quote Cache."""
        count = len(self._quote_cache)
        self._quote_cache.clear()
        return count

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _get_from_cache(self, symbol: str) -> Optional[dict[str, Any]]:
        """
        Holt Quote aus Cache wenn nicht expired.

        LRU: Moves accessed entry to end (most recently used).
        """
        if symbol not in self._quote_cache:
            return None

        quote_data, timestamp = self._quote_cache[symbol]
        age = (datetime.now() - timestamp).total_seconds()

        if age > self._cache_ttl_seconds:
            del self._quote_cache[symbol]
            return None

        # LRU: Move to end (most recently used)
        self._quote_cache.move_to_end(symbol)
        return quote_data

    def _set_cache(self, symbol: str, quote_data: dict[str, Any]) -> None:
        """
        Setzt Quote im Cache mit LRU eviction.

        When cache is full, evicts least recently used entries.
        """
        # If already in cache, update and move to end
        if symbol in self._quote_cache:
            self._quote_cache[symbol] = (quote_data, datetime.now())
            self._quote_cache.move_to_end(symbol)
            return

        # Evict oldest entries if cache is full
        while len(self._quote_cache) >= self._max_cache_size:
            # Remove oldest (first) item
            oldest_key = next(iter(self._quote_cache))
            del self._quote_cache[oldest_key]
            self._cache_evictions += 1

        # Add new entry at end
        self._quote_cache[symbol] = (quote_data, datetime.now())

    async def _fetch_single_quote(
        self,
        provider: Any,
        symbol: str
    ) -> Optional[dict[str, Any]]:
        """Holt einzelnes Quote mit Rate Limiting."""
        try:
            async with self._rate_limited():
                quote = await provider.get_quote(symbol)
            if quote is None:
                return None
            return self._quote_to_dict(quote, symbol)
        except Exception as e:
            self._logger.warning(f"Quote fetch for {symbol} failed: {e}")
            return None

    def _quote_to_dict(self, quote: Any, symbol: str) -> dict[str, Any]:
        """Konvertiert Quote-Objekt zu Dictionary."""
        # Handle verschiedene Quote-Formate
        if hasattr(quote, 'to_dict'):
            result: dict[str, Any] = quote.to_dict()
            return result

        if hasattr(quote, '__dict__'):
            data: dict[str, Any] = quote.__dict__.copy()
            data['symbol'] = symbol
            return data

        # Fallback für dict-like objects
        if isinstance(quote, dict):
            result = dict(quote)
            result['symbol'] = symbol
            return result

        # Minimal quote
        return {
            'symbol': symbol,
            'last': getattr(quote, 'last', None) or getattr(quote, 'price', None),
            'bid': getattr(quote, 'bid', None),
            'ask': getattr(quote, 'ask', None),
            'volume': getattr(quote, 'volume', None),
            'change': getattr(quote, 'change', None),
            'change_pct': getattr(quote, 'change_pct', None) or getattr(quote, 'changepct', None),
        }

    def _format_quote(self, quote_data: dict[str, Any]) -> str:
        """Formatiert einzelnes Quote als Markdown."""
        b = MarkdownBuilder()

        symbol = quote_data.get('symbol', 'Unknown')
        last = quote_data.get('last')
        bid = quote_data.get('bid')
        ask = quote_data.get('ask')
        volume = quote_data.get('volume')
        change = quote_data.get('change')
        change_pct = quote_data.get('change_pct')

        b.h1(f"📈 {symbol} Quote").blank()

        if last:
            b.kv("Last", format_price(last))

        if bid and ask:
            spread = ask - bid if ask and bid else None
            b.kv("Bid/Ask", f"{format_price(bid)} / {format_price(ask)}")
            if spread:
                b.kv("Spread", format_price(spread))

        if volume:
            b.kv("Volume", format_volume(volume))

        if change is not None and change_pct is not None:
            sign = "+" if change >= 0 else ""
            color_emoji = "🟢" if change >= 0 else "🔴"
            b.kv("Change", f"{color_emoji} {sign}{change:.2f} ({sign}{change_pct:.2f}%)")

        return b.build()

    def _format_batch_quotes(self, quotes: dict[str, dict[str, Any]]) -> str:
        """Formatiert Batch Quotes als Markdown-Tabelle."""
        b = MarkdownBuilder()
        b.h1(f"📊 Batch Quotes ({len(quotes)} symbols)").blank()

        if not quotes:
            b.hint("No quotes retrieved.")
            return b.build()

        # Tabelle erstellen
        rows = []
        for symbol, quote_data in sorted(quotes.items()):
            last = quote_data.get('last')
            change_pct = quote_data.get('change_pct')
            volume = quote_data.get('volume')

            change_str = "-"
            if change_pct is not None:
                sign = "+" if change_pct >= 0 else ""
                change_str = f"{sign}{change_pct:.2f}%"

            rows.append([
                symbol,
                format_price(last) if last else "-",
                change_str,
                format_volume(volume) if volume else "-"
            ])

        b.table(["Symbol", "Last", "Change", "Volume"], rows)

        return b.build()
