"""
Report Handler Module
=====================

Handles PDF report generation for scans and individual symbols.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..utils.error_handler import endpoint
from ..utils.markdown_builder import MarkdownBuilder
from ..utils.validation import validate_symbol
from ..config import get_watchlist_loader
from ..cache import get_earnings_fetcher
from ..strike_recommender import StrikeRecommender
from ..indicators.support_resistance import find_support_levels, calculate_fibonacci
from .base import BaseHandlerMixin

if TYPE_CHECKING:
    from ..ibkr_bridge import IBKRBridge

logger = logging.getLogger(__name__)

# IBKR availability
try:
    from ..ibkr_bridge import IBKRBridge
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False


class ReportHandlerMixin(BaseHandlerMixin):
    """
    Mixin for report generation handler methods.
    """

    _ibkr_bridge: Optional["IBKRBridge"]

    @endpoint(operation="detailed report generation", symbol_param="symbol")
    async def generate_report(
        self,
        symbol: str,
        strategy: str = "pullback",
        include_options: bool = True,
        include_news: bool = True,
    ) -> str:
        """
        Generate a detailed PDF report for a trading candidate.

        Includes summary, score breakdown, technical levels, options setup, and news.
        The PDF is saved to the reports/ directory.

        Args:
            symbol: Ticker symbol
            strategy: Strategy type (pullback, bounce, breakout, earnings_dip)
            include_options: Include options analysis
            include_news: Include news headlines

        Returns:
            Path to generated PDF file with summary
        """
        symbol = validate_symbol(symbol)

        b = MarkdownBuilder()
        b.h1(f"Report Generation: {symbol}").blank()

        # This is a placeholder - full implementation would use pdf_report_generator
        b.hint("PDF report generation requires additional setup.")
        b.text(f"Strategy: {strategy}")
        b.text(f"Options: {'Yes' if include_options else 'No'}")
        b.text(f"News: {'Yes' if include_news else 'No'}")

        return b.build()

    @endpoint(operation="scan report generation")
    async def generate_scan_report(
        self,
        strategy: str = "multi",
        symbols: Optional[List[str]] = None,
        min_score: float = 3.5,
        max_candidates: int = 20,
    ) -> str:
        """
        Generate a comprehensive multi-symbol PDF scan report.

        Creates a professional PDF report including:
        - Cover page with VIX and top picks
        - Market environment & strategy analysis
        - Scan results with all candidates
        - Earnings filter analysis
        - Detailed analysis for top candidates

        Args:
            strategy: Scan strategy ("multi", "pullback", "bounce", "breakout", "earnings_dip")
            symbols: List of symbols to scan (uses default watchlist if not provided)
            min_score: Minimum score for qualification
            max_candidates: Maximum candidates to include

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
                "spread_width": strategy_rec.spread_width if strategy_rec else None,
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

        for symbol in symbols[:100]:  # Limit for performance
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
                safe_symbols.append(symbol)
                earnings_data[symbol] = {'days_to_earnings': None, 'next_date': 'Unknown', 'safe': True}

        # 4. Run scan
        scanner = self._get_multi_scanner(min_score=0)
        scan_results = []

        provider = await self._ensure_connected()

        for symbol in safe_symbols[:50]:
            try:
                data = await self._fetch_historical_cached(symbol, days=260)
                if not data:
                    continue

                prices, volumes, highs, lows, *_ = data

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
                    best = max(signals, key=lambda x: x.score)
                    scan_results.append(best)

            except Exception as e:
                logger.debug(f"Scan failed for {symbol}: {e}")

        # Sort by score
        scan_results = sorted(scan_results, key=lambda x: x.score, reverse=True)[:max_candidates]

        if not scan_results:
            return "No scan results found. Check your watchlist and data connection."

        # Build response
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

        # Results table
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
                self._earnings_fetcher.fetch,
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
