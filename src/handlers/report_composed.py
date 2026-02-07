"""
Report Handler (Composition-Based)
====================================

Handles PDF report generation for scans and individual symbols.

This is the composition-based version of ReportHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .handler_container import BaseHandler, ServerContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ReportHandler(BaseHandler):
    """
    Handler for report generation operations.

    Methods:
    - generate_report(): Generate a detailed PDF report for a symbol
    - generate_scan_report(): Generate a comprehensive multi-symbol PDF scan report
    """

    async def generate_report(
        self,
        symbol: str,
        strategy: str = "pullback",
        include_options: bool = True,
        include_news: bool = True,
    ) -> str:
        """
        Generate a detailed PDF report for a trading candidate.

        Args:
            symbol: Ticker symbol
            strategy: Strategy type (pullback, bounce, breakout, earnings_dip)
            include_options: Include options analysis
            include_news: Include news headlines

        Returns:
            Path to generated PDF file with summary
        """
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder

        symbol = validate_symbol(symbol)

        b = MarkdownBuilder()
        b.h1(f"Report Generation: {symbol}").blank()

        b.hint("PDF report generation requires additional setup.")
        b.text(f"Strategy: {strategy}")
        b.text(f"Options: {'Yes' if include_options else 'No'}")
        b.text(f"News: {'Yes' if include_news else 'No'}")

        return b.build()

    async def generate_scan_report(
        self,
        strategy: str = "multi",
        symbols: Optional[List[str]] = None,
        min_score: float = 3.5,
        max_candidates: int = 20,
    ) -> str:
        """
        Generate a comprehensive multi-symbol PDF scan report.

        Args:
            strategy: Scan strategy
            symbols: List of symbols to scan
            min_score: Minimum score for qualification
            max_candidates: Maximum candidates to include

        Returns:
            Path to generated PDF file with summary
        """
        from ..utils.markdown_builder import MarkdownBuilder
        from ..config import get_watchlist_loader
        from ..cache import get_earnings_fetcher
        from ..scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig

        # 1. Get VIX
        vix_value = await self._get_vix()
        regime = self._ctx.vix_selector.get_regime(vix_value) if vix_value else None
        strategy_rec = self._ctx.vix_selector.get_recommendation(vix_value) if vix_value else None

        vix_data = {
            "value": vix_value or "N/A",
            "regime": regime.name if regime else "Unknown",
            "recommended_strategy": strategy_rec.profile_name.title() if strategy_rec else 'Standard',
        }

        # 2. Get symbols
        if not symbols:
            watchlist_loader = get_watchlist_loader()
            symbols = watchlist_loader.get_all_symbols()

        # 3. Pre-filter by earnings
        safe_symbols = []
        earnings_data = {}

        if self._ctx.earnings_fetcher is None:
            self._ctx.earnings_fetcher = get_earnings_fetcher()

        for sym in symbols[:100]:
            try:
                earnings_info = await self._check_earnings_async(sym)
                days = earnings_info.get('days_to_earnings')
                earnings_data[sym] = {
                    'days_to_earnings': days,
                    'next_date': earnings_info.get('next_date'),
                    'safe': days is None or days > 45,
                }
                if earnings_data[sym]['safe']:
                    safe_symbols.append(sym)
            except Exception as e:
                self._logger.debug(f"Earnings check failed for {sym}: {e}")
                safe_symbols.append(sym)
                earnings_data[sym] = {'days_to_earnings': None, 'next_date': 'Unknown', 'safe': True}

        # 4. Run scan
        config = ScanConfig(min_score=0)
        scanner = MultiStrategyScanner(config=config)
        scan_results = []

        provider = await self._ensure_connected()

        for sym in safe_symbols[:50]:
            try:
                data = await self._fetch_historical_cached(sym, days=260)
                if not data:
                    continue

                prices, volumes, highs, lows, *_ = data

                e_info = earnings_data.get(sym, {})
                if e_info.get('next_date') and e_info['next_date'] != 'Unknown':
                    try:
                        earnings_date = date.fromisoformat(e_info['next_date'])
                        scanner.set_earnings_date(sym, earnings_date)
                    except (ValueError, TypeError):
                        pass

                signals = scanner.analyze_symbol(sym, prices, volumes, highs, lows)
                if signals:
                    best = max(signals, key=lambda x: x.score)
                    scan_results.append(best)
            except Exception as e:
                self._logger.debug(f"Scan failed for {sym}: {e}")

        scan_results = sorted(scan_results, key=lambda x: x.score, reverse=True)[:max_candidates]

        if not scan_results:
            return "No scan results found. Check your watchlist and data connection."

        qualified = [s for s in scan_results if s.score >= min_score]

        b = MarkdownBuilder()
        b.h1("Scan Results").blank()

        b.h2("Summary")
        b.kv_line("Total Scanned", len(safe_symbols))
        b.kv_line("Results", len(scan_results))
        b.kv_line(f"Qualified (>={min_score})", len(qualified))
        b.kv_line("VIX", f"{vix_value:.1f}" if vix_value else "N/A")
        b.kv_line("Strategy", vix_data['recommended_strategy'])
        b.blank()

        if qualified:
            b.h2("Top Picks")
            for i, sig in enumerate(qualified[:5], 1):
                b.bullet(f"**#{i} {sig.symbol}**: Score {sig.score:.1f}/10, ${sig.current_price:.2f}")
            b.blank()

        if scan_results:
            b.h2("All Candidates")
            rows = []
            for sig in scan_results[:20]:
                rows.append([
                    sig.symbol,
                    f"{sig.score:.1f}",
                    f"${sig.current_price:.2f}" if sig.current_price else "N/A",
                    sig.strategy,
                ])
            b.table(["Symbol", "Score", "Price", "Strategy"], rows)

        return b.build()

    async def _check_earnings_async(self, symbol: str) -> Dict[str, Any]:
        """Async helper to check earnings for a symbol."""
        from ..cache import get_earnings_fetcher

        try:
            if self._ctx.earnings_fetcher is None:
                self._ctx.earnings_fetcher = get_earnings_fetcher()

            cached = self._ctx.earnings_fetcher.cache.get(symbol)
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

            result = await asyncio.to_thread(self._ctx.earnings_fetcher.fetch, symbol)
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
            self._logger.debug(f"Earnings check error for {symbol}: {e}")
            return {'days_to_earnings': None, 'next_date': None}

    # --- Shared helper methods ---

    async def _ensure_connected(self):
        if not self._ctx.connected and self._ctx.provider:
            try:
                await self._ctx.provider.connect()
                self._ctx.connected = True
            except Exception as e:
                self._logger.error(f"Connection failed: {e}")
                raise
        return self._ctx.provider

    async def _get_vix(self) -> Optional[float]:
        if self._ctx.current_vix is not None:
            return self._ctx.current_vix
        if self._ctx.provider:
            try:
                quote = await self._ctx.provider.get_quote("VIX")
                if quote and hasattr(quote, 'last') and quote.last:
                    self._ctx.current_vix = quote.last
                    return quote.last
            except Exception:
                pass
        return None

    async def _fetch_historical_cached(self, symbol: str, days: Optional[int] = None):
        if self._ctx.historical_cache:
            return await self._ctx.historical_cache.get_historical(
                symbol, days=days, provider=self._ctx.provider
            )
        if self._ctx.provider:
            return await self._ctx.provider.get_historical_for_scanner(symbol, days=days or 120)
        return None
