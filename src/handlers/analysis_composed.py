"""
Analysis Handler (Composition-Based)
======================================

Handles symbol analysis, ensemble recommendations, and strike recommendations.

This is the composition-based version of AnalysisHandlerMixin,
providing the same functionality but with cleaner architecture.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .handler_container import BaseHandler, ServerContext
from ..constants.trading_rules import SPREAD_DTE_MIN, SPREAD_DTE_MAX

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Display / UI formatting constants
DISPLAY_STABILITY_OK = 70        # Stability threshold for "OK" display
SMA_20_PERIOD = 20               # SMA short period
SMA_50_PERIOD = 50               # SMA medium period
SMA_200_PERIOD = 200             # SMA long period
VOLUME_AVG_PERIOD = 20           # Volume average window (days)
DISPLAY_SCORE_STRONG = 7         # Score threshold for "Strong" label
DISPLAY_SCORE_MODERATE = 5       # Score threshold for "Moderate" label
DISPLAY_SCORE_BEST = 6           # Score threshold for best signal
DISPLAY_SCORE_OK = 4             # Score threshold for moderate signal
DISPLAY_REASON_MAX_LEN = 35     # Max length for truncated reason text
FIBONACCI_LOOKBACK = 60          # Lookback period for Fibonacci high/low


class AnalysisHandler(BaseHandler):
    """
    Handler for analysis-related operations.

    Methods:
    - analyze_symbol(): Complete analysis for Bull-Put-Spread suitability
    - analyze_multi_strategy(): Multi-strategy analysis for a single symbol
    - get_ensemble_recommendation(): Ensemble strategy recommendation
    - get_ensemble_status(): Ensemble selector and rotation status
    - recommend_strikes(): Optimal strike recommendations
    """

    async def analyze_symbol(self, symbol: str) -> str:
        """
        Perform complete analysis for a symbol (Bull-Put-Spread focus).

        Args:
            symbol: Ticker symbol

        Returns:
            Formatted analysis with technical indicators
        """
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder
        from ..vix_strategy import get_strategy_for_vix
        from ..constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS, ENTRY_VOLUME_MIN, ENTRY_STABILITY_MIN, is_blacklisted
        from ..cache.symbol_fundamentals import get_fundamentals_manager

        symbol = validate_symbol(symbol)

        if is_blacklisted(symbol):
            b = MarkdownBuilder()
            b.h1(f"Analysis: {symbol}").blank()
            b.status_error(f"**BLACKLISTED** -- {symbol} darf nicht getradet werden (PLAYBOOK)")
            return b.build()

        await self._ensure_connected()
        vix = await self._get_vix()
        recommendation = get_strategy_for_vix(vix)

        quote = await self._get_quote_cached(symbol)

        try:
            fundamentals_mgr = get_fundamentals_manager()
            fundamentals = fundamentals_mgr.get_fundamentals(symbol)
        except Exception:
            fundamentals = None

        historical = await self._fetch_historical_cached(symbol, days=260)

        earnings = await self._fetch_earnings_cached(symbol)

        b = MarkdownBuilder()
        b.h1(f"Complete Analysis: {symbol}").blank()
        b.kv("VIX", vix, fmt=".2f")
        b.kv("Strategy", recommendation.profile_name.upper())
        b.blank()

        b.h2("Fundamentals")
        if fundamentals and fundamentals.stability_score is not None:
            stability = fundamentals.stability_score
            if stability >= DISPLAY_STABILITY_OK:
                stability_icon = "[OK]"
            elif stability >= ENTRY_STABILITY_MIN:
                stability_icon = "[~]"  # WARNING: 65-70 range
            else:
                stability_icon = "[X]"
            b.kv_line("Stability", f"{stability_icon} {stability:.0f}/100 (min: {ENTRY_STABILITY_MIN:.0f})")
            if fundamentals.sector:
                b.kv_line("Sector", fundamentals.sector)
            if fundamentals.historical_win_rate:
                b.kv_line("Hist. Win Rate", f"{fundamentals.historical_win_rate:.0f}%")
        else:
            b.kv_line("Stability", "[?] UNKNOWN")
        b.blank()

        if quote:
            b.h2("Current Price")
            b.kv_line("Last", f"${quote.last:.2f}" if quote.last else "N/A")
            b.blank()

        current_price = 0
        sma_200 = 0
        if historical:
            prices, volumes, highs, lows, *_ = historical
            current_price = prices[-1]
            sma_20 = sum(prices[-SMA_20_PERIOD:]) / SMA_20_PERIOD if len(prices) >= SMA_20_PERIOD else current_price
            sma_50 = sum(prices[-SMA_50_PERIOD:]) / SMA_50_PERIOD if len(prices) >= SMA_50_PERIOD else current_price
            sma_200 = sum(prices[-SMA_200_PERIOD:]) / SMA_200_PERIOD if len(prices) >= SMA_200_PERIOD else current_price

            b.h2("Technical Indicators")
            up_20 = "[UP]" if current_price > sma_20 else "[DN]"
            up_50 = "[UP]" if current_price > sma_50 else "[DN]"
            up_200 = "[UP]" if current_price > sma_200 else "[DN]"
            b.kv_line("SMA 20", f"${sma_20:.2f} {up_20}")
            b.kv_line("SMA 50", f"${sma_50:.2f} {up_50}")
            b.kv_line("SMA 200", f"${sma_200:.2f} {up_200}")

            if volumes and len(volumes) >= VOLUME_AVG_PERIOD:
                avg_vol_20d = sum(volumes[-VOLUME_AVG_PERIOD:]) / VOLUME_AVG_PERIOD
                vol_icon = "[OK]" if avg_vol_20d >= ENTRY_VOLUME_MIN else "[X]"
                b.kv_line("Avg Volume (20d)", f"{vol_icon} {avg_vol_20d:,.0f} (min: {ENTRY_VOLUME_MIN:,})")
            b.blank()

            if current_price > sma_200 and current_price < sma_20:
                trend_status = "[OK] **PULLBACK IN UPTREND** - Ideal for Bull-Put-Spread"
            elif current_price > sma_200:
                trend_status = "[INFO] Uptrend - Wait for pullback"
            else:
                trend_status = "[!] Below SMA 200 - Caution"

            b.h2("Trend Assessment")
            b.text(trend_status)
            b.blank()

        if earnings:
            b.h2("Earnings Check")
            if earnings.days_to_earnings and earnings.days_to_earnings < ENTRY_EARNINGS_MIN_DAYS:
                b.status_error(f"Earnings in {earnings.days_to_earnings} days - NOT SAFE")
            elif earnings.days_to_earnings:
                b.status_ok(f"Earnings in {earnings.days_to_earnings} days - SAFE")
            else:
                b.hint("No earnings date found")

        return b.build()

    async def analyze_multi_strategy(self, symbol: str) -> str:
        """
        Analyze a single symbol with all available strategies.

        Args:
            symbol: Ticker symbol

        Returns:
            Formatted Markdown analysis with all strategy scores
        """
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder, truncate
        from ..constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS, is_blacklisted
        from ..cache import get_earnings_fetcher

        symbol = validate_symbol(symbol)

        if is_blacklisted(symbol):
            b = MarkdownBuilder()
            b.h1(f"Multi-Strategy Analysis: {symbol}").blank()
            b.status_error(f"**BLACKLISTED** -- {symbol} darf nicht getradet werden (PLAYBOOK)")
            return b.build()

        await self._ensure_connected()

        historical_days = max(self._ctx.config.settings.performance.historical_days, 260)
        data = await self._fetch_historical_cached(symbol, days=historical_days)

        if not data:
            return f"No historical data available for {symbol}"

        prices, volumes, highs, lows, *_ = data

        quote = await self._get_quote_cached(symbol)
        vix = await self._get_vix()

        # For single-symbol analysis: disable earnings filter so user sees all scores
        # (earnings warning is shown separately in the output)
        scanner = self._get_multi_scanner(min_score=0, exclude_earnings_within_days=0)

        if self._ctx.earnings_fetcher is None:
            self._ctx.earnings_fetcher = get_earnings_fetcher()
        cached_earnings = self._ctx.earnings_fetcher.cache.get(symbol)
        if cached_earnings and cached_earnings.earnings_date:
            try:
                earnings_date = date.fromisoformat(cached_earnings.earnings_date)
                scanner.set_earnings_date(symbol, earnings_date)
            except (ValueError, TypeError):
                pass

        signals = scanner.analyze_symbol(symbol, prices, volumes, highs, lows)

        strategy_icons = {
            'pullback': '[PB]', 'bounce': '[BN]',
            'ath_breakout': '[ATH]', 'earnings_dip': '[ED]',
            'trend_continuation': '[TC]',
        }
        strategy_names = {
            'pullback': 'Bull-Put-Spread', 'bounce': 'Support Bounce',
            'ath_breakout': 'ATH Breakout', 'earnings_dip': 'Earnings Dip',
            'trend_continuation': 'Trend Continuation',
        }

        b = MarkdownBuilder()
        b.h1(f"Multi-Strategy Analysis: {symbol}").blank()

        if quote:
            b.kv_line("Price", f"${quote.last:.2f}" if quote.last else "N/A")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")

        earnings = await self._fetch_earnings_cached(symbol)

        if earnings and earnings.earnings_date:
            if earnings.days_to_earnings < ENTRY_EARNINGS_MIN_DAYS:
                b.kv_line("Earnings", f"[X] {earnings.days_to_earnings}d - DO NOT TRADE (min: {ENTRY_EARNINGS_MIN_DAYS}d)")
            else:
                b.kv_line("Earnings", f"[OK] {earnings.days_to_earnings}d")
        else:
            b.kv_line("Earnings", "N/A")
        b.blank()

        signal_by_strategy = {s.strategy: s for s in signals}

        b.h2("Strategy Scores").blank()
        rows = []
        for strat in ['pullback', 'bounce', 'ath_breakout', 'earnings_dip', 'trend_continuation']:
            icon = strategy_icons.get(strat, '*')
            name = strategy_names.get(strat, strat)

            if strat in signal_by_strategy:
                sig = signal_by_strategy[strat]
                status = "[OK] Strong" if sig.score >= DISPLAY_SCORE_STRONG else ("[~] Moderate" if sig.score >= DISPLAY_SCORE_MODERATE else "[X] Weak")
                reason = truncate(sig.reason, DISPLAY_REASON_MAX_LEN) if sig.reason else "-"
                rows.append([f"{icon} {name}", f"{sig.score:.1f}/10", status, reason])
            else:
                rows.append([f"{icon} {name}", "N/A", "[X] No signal", "-"])

        b.table(["Strategy", "Score", "Status", "Reason"], rows)
        b.blank()

        if signals:
            best = max(signals, key=lambda x: x.score)
            icon = strategy_icons.get(best.strategy, '*')
            name = strategy_names.get(best.strategy, best.strategy)

            if best.score >= DISPLAY_SCORE_BEST:
                b.status_ok(f"**Best: {icon} {name}** (Score: {best.score:.1f}/10)")
            elif best.score >= DISPLAY_SCORE_OK:
                b.status_warning(f"**Moderate: {icon} {name}** (Score: {best.score:.1f}/10)")
            else:
                b.status_error("**No strong signals.**")

        return b.build()

    async def get_ensemble_recommendation(self, symbol: str) -> str:
        """
        Get ensemble strategy recommendation for a symbol.

        Args:
            symbol: Ticker symbol to analyze

        Returns:
            Formatted Markdown ensemble recommendation
        """
        from ..backtesting import EnsembleSelector, create_strategy_score
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder

        symbol = validate_symbol(symbol)
        vix = await self._get_vix()

        scanner = self._get_scanner()
        historical_days = max(self._ctx.config.settings.performance.historical_days, 260)
        data = await self._fetch_historical_cached(symbol, days=historical_days)

        if not data:
            return f"No historical data available for {symbol}"

        prices, volumes, highs, lows, *_ = data
        results = scanner.analyze_symbol(symbol, prices, volumes, highs, lows)

        if not results:
            return f"No analysis results for {symbol}"

        strategy_scores = {}
        for result in results:
            breakdown = {}
            if result.score_breakdown:
                for comp, data_val in result.score_breakdown.items():
                    if isinstance(data_val, dict):
                        score_val = data_val.get("score", data_val.get("value", 0))
                    else:
                        score_val = data_val
                    breakdown[f"{comp}_score"] = float(score_val) if score_val else 0

            strategy_scores[result.strategy] = create_strategy_score(
                strategy=result.strategy,
                raw_score=result.score,
                breakdown=breakdown,
                confidence=min(1.0, result.score / 10.0) if result.score else 0.5,
            )

        if not strategy_scores:
            return f"No valid strategy scores for {symbol}"

        try:
            selector = EnsembleSelector.load_trained_model()
        except Exception as e:
            self._logger.warning(f"Could not load trained ensemble model: {e}")
            selector = EnsembleSelector()

        rec = selector.get_recommendation(symbol, strategy_scores, vix=vix)

        b = MarkdownBuilder()
        b.h1(f"Ensemble Recommendation: {symbol}").blank()

        b.h2("Recommended Strategy")
        strategy_icons = {
            "pullback": "[PB]", "bounce": "[BN]",
            "ath_breakout": "[ATH]", "earnings_dip": "[ED]",
            "trend_continuation": "[TC]",
        }

        icon = strategy_icons.get(rec.recommended_strategy, "[?]")
        b.kv_line("Strategy", f"{icon} **{rec.recommended_strategy.upper()}**")
        b.kv_line("Score", f"{rec.recommended_score:.1f}")
        b.kv_line("Confidence", f"{rec.ensemble_confidence:.0%}")
        b.kv_line("Method", rec.selection_method.value)
        b.blank()
        b.kv_line("Reason", rec.selection_reason)
        b.blank()

        b.h2("All Strategies")
        b.text("| Strategy | Score | Confidence | Adjusted |")
        b.text("|----------|-------|------------|----------|")

        for strat, score in sorted(
            rec.strategy_scores.items(),
            key=lambda x: x[1].adjusted_score,
            reverse=True
        ):
            marker = " *" if strat == rec.recommended_strategy else ""
            b.text(
                f"| {strat}{marker} | {score.weighted_score:.1f} | "
                f"{score.confidence:.0%} | {score.adjusted_score:.1f} |"
            )
        b.blank()

        b.h2("Context")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")
        b.kv_line("Regime", rec.regime or "unknown")
        b.kv_line("Diversification", f"{rec.diversification_benefit:.0%}")

        return b.build()

    async def get_ensemble_status(self) -> str:
        """
        Get ensemble selector and rotation engine status.

        Returns:
            Formatted Markdown status
        """
        from ..backtesting import EnsembleSelector
        from ..utils.markdown_builder import MarkdownBuilder

        vix = await self._get_vix()

        try:
            selector = EnsembleSelector.load_trained_model()
        except Exception as e:
            self._logger.warning(f"Could not load ensemble model: {e}")
            return "[!] No trained ensemble model. Run `train_ensemble_v2.py` to train."

        b = MarkdownBuilder()
        b.h1("Ensemble Strategy Status").blank()

        if vix:
            regime = "low_vol" if vix < 15 else "normal" if vix < 20 else "elevated" if vix < 30 else "high_vol"
            b.h2("Current Context")
            b.kv_line("VIX", f"{vix:.2f}")
            b.kv_line("Regime", regime.upper())
            b.blank()

        rotation = selector.get_rotation_status()
        if rotation:
            b.h2("Strategy Rotation")
            b.kv_line("Days Since Rotation", str(rotation.get("days_since_rotation", 0)))
            b.kv_line("Total Rotations", str(rotation.get("rotation_count", 0)))
            if rotation.get("last_rotation_reason"):
                b.kv_line("Last Trigger", rotation["last_rotation_reason"])
            b.blank()

            b.h3("Current Preferences")
            prefs = rotation.get("current_preferences", {})
            for strat, pref in sorted(prefs.items(), key=lambda x: -x[1]):
                bar = "#" * int(pref * 20)
                b.text(f"{strat:<15} {pref:>5.1%} {bar}")
            b.blank()

        b.h2("Selector Info")
        b.kv_line("Method", selector.method.value)
        b.kv_line("Rotation Enabled", "Yes" if selector.enable_rotation else "No")
        b.kv_line("Min Score Threshold", f"{selector.min_score_threshold:.1f}")

        return b.build()

    async def recommend_strikes(
        self,
        symbol: str,
        dte_min: int = 60,
        dte_max: int = 90,
        num_alternatives: int = 3,
    ) -> str:
        """
        Generate optimal strike recommendations for Bull-Put-Spreads.

        Args:
            symbol: Ticker symbol
            dte_min: Minimum days to expiration
            dte_max: Maximum days to expiration
            num_alternatives: Number of alternative recommendations

        Returns:
            Formatted strike recommendations
        """
        from ..utils.validation import validate_symbol
        from ..utils.markdown_builder import MarkdownBuilder
        from ..strike_recommender import StrikeRecommender
        from ..indicators.support_resistance import find_support_levels, calculate_fibonacci

        symbol = validate_symbol(symbol)

        quote = await self._get_quote_cached(symbol)
        if not quote or not quote.last:
            return f"Cannot get quote for {symbol}"

        current_price = quote.last
        vix = await self._get_vix()
        regime = self._ctx.vix_selector.get_regime(vix)

        data = await self._fetch_historical_cached(symbol, days=260)
        if not data:
            return f"No historical data for {symbol}"

        prices, volumes, highs, lows, *_ = data

        support_levels = find_support_levels(lows=lows, lookback=90, window=10, max_levels=5)
        support_levels = [s for s in support_levels if s < current_price]

        recent_high = max(highs[-FIBONACCI_LOOKBACK:]) if len(highs) >= FIBONACCI_LOOKBACK else max(highs)
        recent_low = min(lows[-FIBONACCI_LOOKBACK:]) if len(lows) >= FIBONACCI_LOOKBACK else min(lows)
        fib_levels = calculate_fibonacci(recent_high, recent_low)

        options = await self._get_options_chain_with_fallback(
            symbol, dte_min=dte_min, dte_max=dte_max, right="P"
        )

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
                    "open_interest": opt.open_interest,
                    "volume": opt.volume,
                }
                for opt in options
            ]

        recommender = StrikeRecommender()
        rec = recommender.get_recommendation(
            symbol=symbol,
            current_price=current_price,
            support_levels=support_levels,
            options_data=options_data,
            fib_levels=[{"level": v, "fib": k} for k, v in fib_levels.items() if v < current_price],
            dte=dte_min,
            regime=regime,
        )

        b = MarkdownBuilder()
        b.h1(f"Strike Recommendations: {symbol}").blank()

        b.h2("Market Context")
        b.kv_line("Current Price", f"${current_price:.2f}")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")
        b.kv_line("Regime", regime.value if regime else "unknown")
        b.blank()

        if not rec:
            b.hint("No suitable strikes found for current criteria.")
            return b.build()

        b.h2("Primary Recommendation")
        b.kv_line("Short Strike", f"${rec.short_strike:.2f}")
        b.kv_line("Long Strike", f"${rec.long_strike:.2f}")
        b.kv_line("Spread Width", f"${rec.spread_width:.2f}")
        b.kv_line("Est. Credit", f"${rec.estimated_credit:.2f}" if rec.estimated_credit else "N/A")
        b.kv_line("Short Delta", f"{rec.estimated_delta:.2f}" if rec.estimated_delta else "N/A")
        b.kv_line("Long Delta", f"{rec.long_delta:.2f}" if rec.long_delta else "N/A")
        b.kv_line("Prob. Profit", f"{rec.prob_profit:.0f}%" if rec.prob_profit else "N/A")
        b.kv_line("Quality", rec.quality.value if rec.quality else "N/A")
        # Show data source for transparency
        source_labels = {
            "provider": "Live (Tradier/ORATS)",
            "black_scholes": "Black-Scholes (geschätzt)",
            "heuristic": "Heuristik (geschätzt)",
        }
        b.kv_line("Datenquelle", source_labels.get(rec.data_source, rec.data_source))
        b.blank()

        if support_levels:
            b.h2("Support Levels")
            for i, level in enumerate(support_levels[:5], 1):
                distance_pct = ((level - current_price) / current_price) * 100
                b.text(f"S{i}: ${level:.2f} ({distance_pct:+.1f}%)")
            b.blank()

        if options_data and rec:
            from ..options.liquidity import LiquidityAssessor
            assessor = LiquidityAssessor()
            spread_liq = assessor.assess_spread(
                rec.short_strike, rec.long_strike, options_data
            )
            if spread_liq:
                b.h2("Liquidity Assessment")
                b.kv_line("Overall Quality", spread_liq.overall_quality.upper())
                b.kv_line("Short Strike OI", f"{spread_liq.short_strike_liquidity.open_interest:,}")
                b.kv_line("Long Strike OI", f"{spread_liq.long_strike_liquidity.open_interest:,}")
                b.kv_line("Short Bid-Ask Spread", f"{spread_liq.short_strike_liquidity.spread_pct:.1f}%")
                b.kv_line("Long Bid-Ask Spread", f"{spread_liq.long_strike_liquidity.spread_pct:.1f}%")
                if not spread_liq.is_tradeable:
                    b.blank()
                    b.text("**ILLIQUID - Not recommended for trading**")
                for w in spread_liq.warnings:
                    b.text(f"- {w}")
                b.blank()

        b.h2("Fibonacci Retracements")
        for level_name, level_price in sorted(fib_levels.items(), key=lambda x: x[1], reverse=True):
            if level_price < current_price:
                distance_pct = ((level_price - current_price) / current_price) * 100
                b.text(f"{level_name}: ${level_price:.2f} ({distance_pct:+.1f}%)")

        return b.build()

    # --- Shared helper methods ---

    # _get_vix() inherited from BaseHandler

    async def _fetch_earnings_cached(self, symbol: str):
        """Fetch earnings info via EarningsFetcher (local DB + yfinance)."""
        import asyncio
        from ..cache import get_earnings_fetcher

        if self._ctx.earnings_fetcher is None:
            self._ctx.earnings_fetcher = get_earnings_fetcher()

        try:
            result = await asyncio.to_thread(self._ctx.earnings_fetcher.fetch, symbol)
            if result and result.earnings_date:
                return result
        except Exception as e:
            self._logger.debug(f"Earnings fetch failed for {symbol}: {e}")
        return None

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
                data = await self._ctx.tradier_provider.get_historical_for_scanner(symbol, days=days)
                if data:
                    if self._ctx.historical_cache:
                        self._ctx.historical_cache.set(symbol, data, days=days)
                    return data
            except (ConnectionError, TimeoutError, ValueError) as e:
                self._logger.debug(f"Tradier historical failed for {symbol}: {e}")

        return None

    def _get_scanner(self, min_score=None, earnings_days=None):
        from ..scanner.multi_strategy_scanner import MultiStrategyScanner, ScanConfig
        config = ScanConfig(min_score=min_score or 3.5)
        return MultiStrategyScanner(config=config)

    def _get_multi_scanner(self, min_score=3.5, enable_pullback=True,
                           enable_bounce=True, enable_breakout=True,
                           enable_earnings_dip=True, enable_trend_continuation=True,
                           exclude_earnings_within_days=None):
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

    async def _get_options_chain_with_fallback(self, symbol, dte_min=SPREAD_DTE_MIN, dte_max=SPREAD_DTE_MAX, right="P"):
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
