"""
Analysis Handler Module
=======================

Handles symbol analysis, ensemble recommendations, and strike recommendations.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from ..cache import get_earnings_fetcher
from ..cache.symbol_fundamentals import get_fundamentals_manager
from ..constants.trading_rules import (
    BLACKLIST_SYMBOLS,
    ENTRY_EARNINGS_MIN_DAYS,
    ENTRY_STABILITY_MIN,
    ENTRY_VOLUME_MIN,
    SPREAD_DTE_MAX,
    SPREAD_DTE_MIN,
    VIX_ELEVATED_MAX,
    VIX_LOW_VOL_MAX,
    VIX_NORMAL_MAX,
    is_blacklisted,
)
from ..indicators.support_resistance import calculate_fibonacci, find_support_levels
from ..options.strike_recommender import StrikeRecommender
from ..services.vix_strategy import get_strategy_for_vix
from ..utils.error_handler import mcp_endpoint
from ..utils.markdown_builder import MarkdownBuilder, truncate
from ..utils.validation import validate_symbol
from .base import BaseHandlerMixin

logger = logging.getLogger(__name__)

# Display / UI formatting constants
DISPLAY_STABILITY_OK = 70  # Stability threshold for "OK" display
SMA_20_PERIOD = 20  # SMA short period
SMA_50_PERIOD = 50  # SMA medium period
SMA_200_PERIOD = 200  # SMA long period
VOLUME_AVG_PERIOD = 20  # Volume average window (days)
DISPLAY_SCORE_STRONG = 7  # Score threshold for "Strong" label
DISPLAY_SCORE_MODERATE = 5  # Score threshold for "Moderate" label
DISPLAY_SCORE_BEST = 6  # Score threshold for best signal
DISPLAY_SCORE_OK = 4  # Score threshold for moderate signal
DISPLAY_REASON_MAX_LEN = 35  # Max length for truncated reason text
FIBONACCI_LOOKBACK = 60  # Lookback period for Fibonacci high/low


class AnalysisHandlerMixin(BaseHandlerMixin):
    """
    Mixin for analysis-related handler methods.
    """

    @mcp_endpoint(operation="symbol analysis", symbol_param="symbol")
    async def analyze_symbol(self, symbol: str) -> str:
        """
        Perform complete analysis for a symbol (Bull-Put-Spread focus).

        Args:
            symbol: Ticker symbol

        Returns:
            Formatted analysis with technical indicators
        """
        symbol = validate_symbol(symbol)

        # Blacklist-Check (PLAYBOOK §1, Filter #1) — vor allen API-Calls
        if is_blacklisted(symbol):
            b = MarkdownBuilder()
            b.h1(f"Analysis: {symbol}").blank()
            b.status_error(f"**BLACKLISTED** — {symbol} darf nicht getradet werden (PLAYBOOK §7)")
            return b.build()

        provider = await self._ensure_connected()

        vix = await self.get_vix()
        recommendation = get_strategy_for_vix(vix)

        quote = await self._get_quote_cached(symbol)

        # Fundamentals (Stability, Sector)
        try:
            fundamentals_mgr = get_fundamentals_manager()
            fundamentals = fundamentals_mgr.get_fundamentals(symbol)
        except (AttributeError, ValueError):
            fundamentals = None

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

        # Fundamentals section (PLAYBOOK §1, Filter #2)
        b.h2("Fundamentals")
        if fundamentals and fundamentals.stability_score is not None:
            stability = fundamentals.stability_score
            if stability >= DISPLAY_STABILITY_OK:
                stability_icon = "[OK]"
            elif stability >= ENTRY_STABILITY_MIN:
                stability_icon = "[~]"  # WARNING: 65-70 range
            else:
                stability_icon = "[X]"
            b.kv_line(
                "Stability",
                f"{stability_icon} {stability:.0f}/100 (min: {ENTRY_STABILITY_MIN:.0f})",
            )
            if fundamentals.sector:
                b.kv_line("Sector", fundamentals.sector)
            if fundamentals.historical_win_rate:
                b.kv_line("Hist. Win Rate", f"{fundamentals.historical_win_rate:.0f}%")
        else:
            b.kv_line("Stability", "[?] UNKNOWN — nicht in symbol_fundamentals")
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
            sma_20 = (
                sum(prices[-SMA_20_PERIOD:]) / SMA_20_PERIOD
                if len(prices) >= SMA_20_PERIOD
                else current_price
            )
            sma_50 = (
                sum(prices[-SMA_50_PERIOD:]) / SMA_50_PERIOD
                if len(prices) >= SMA_50_PERIOD
                else current_price
            )
            sma_200 = (
                sum(prices[-SMA_200_PERIOD:]) / SMA_200_PERIOD
                if len(prices) >= SMA_200_PERIOD
                else current_price
            )

            b.h2("Technical Indicators")
            up_20 = "[UP]" if current_price > sma_20 else "[DN]"
            up_50 = "[UP]" if current_price > sma_50 else "[DN]"
            up_200 = "[UP]" if current_price > sma_200 else "[DN]"
            b.kv_line("SMA 20", f"${sma_20:.2f} {up_20}")
            b.kv_line("SMA 50", f"${sma_50:.2f} {up_50}")
            b.kv_line("SMA 200", f"${sma_200:.2f} {up_200}")

            # Volume (PLAYBOOK §1, Filter #6)
            if volumes and len(volumes) >= VOLUME_AVG_PERIOD:
                avg_vol_20d = sum(volumes[-VOLUME_AVG_PERIOD:]) / VOLUME_AVG_PERIOD
                vol_icon = "[OK]" if avg_vol_20d >= ENTRY_VOLUME_MIN else "[X]"
                b.kv_line(
                    "Avg Volume (20d)", f"{vol_icon} {avg_vol_20d:,.0f} (min: {ENTRY_VOLUME_MIN:,})"
                )
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
            if (
                earnings.days_to_earnings
                and earnings.days_to_earnings > 0
                and earnings.days_to_earnings < ENTRY_EARNINGS_MIN_DAYS
            ):
                b.status_error(f"Earnings in {earnings.days_to_earnings} days - NOT SAFE")
            elif earnings.days_to_earnings:
                b.status_ok(f"Earnings in {earnings.days_to_earnings} days - SAFE")
            else:
                b.hint("No earnings date found")

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

        # Blacklist-Check (PLAYBOOK §1, Filter #1)
        if is_blacklisted(symbol):
            b = MarkdownBuilder()
            b.h1(f"Multi-Strategy Analysis: {symbol}").blank()
            b.status_error(f"**BLACKLISTED** — {symbol} darf nicht getradet werden (PLAYBOOK §7)")
            return b.build()

        provider = await self._ensure_connected()

        historical_days = max(self._config.settings.performance.historical_days, 260)
        data = await self._fetch_historical_cached(symbol, days=historical_days)

        if not data:
            return f"No historical data available for {symbol}"

        prices, volumes, highs, lows, *_ = data

        quote = await self._get_quote_cached(symbol)
        vix = await self.get_vix()

        # Initialize scanner with earnings data
        # For single-symbol analysis: disable earnings filter so user sees all scores
        # (earnings warning is shown separately in the output)
        scanner = self._get_multi_scanner(min_score=0, exclude_earnings_within_days=0)

        # Load earnings date for this symbol into scanner cache
        if self._earnings_fetcher is None:
            self._earnings_fetcher = get_earnings_fetcher()
        cached_earnings = self._earnings_fetcher.cache.get(symbol)
        if cached_earnings and cached_earnings.earnings_date:
            try:
                earnings_date = date.fromisoformat(cached_earnings.earnings_date)
                scanner.set_earnings_date(symbol, earnings_date)
            except (ValueError, TypeError):
                pass

        signals = scanner.analyze_symbol(symbol, prices, volumes, highs, lows)

        strategy_icons = {
            "pullback": "[PB]",
            "bounce": "[BN]",
            "ath_breakout": "[ATH]",
            "earnings_dip": "[ED]",
            "trend_continuation": "[TC]",
        }
        strategy_names = {
            "pullback": "Bull-Put-Spread",
            "bounce": "Support Bounce",
            "ath_breakout": "ATH Breakout",
            "earnings_dip": "Earnings Dip",
            "trend_continuation": "Trend Continuation",
        }

        b = MarkdownBuilder()
        b.h1(f"Multi-Strategy Analysis: {symbol}").blank()

        if quote:
            b.kv_line("Price", f"${quote.last:.2f}" if quote.last else "N/A")
        b.kv_line("VIX", f"{vix:.2f}" if vix else "N/A")

        # Earnings check with warning
        await self._rate_limiter.acquire()
        earnings = await provider.get_earnings_date(symbol)
        self._rate_limiter.record_success()

        if earnings and earnings.earnings_date:
            if earnings.days_to_earnings < ENTRY_EARNINGS_MIN_DAYS:
                b.kv_line(
                    "Earnings",
                    f"[X] {earnings.days_to_earnings}d - DO NOT TRADE (min: {ENTRY_EARNINGS_MIN_DAYS}d)",
                )
            else:
                b.kv_line("Earnings", f"[OK] {earnings.days_to_earnings}d")
        else:
            b.kv_line("Earnings", "N/A")
        b.blank()

        signal_by_strategy = {s.strategy: s for s in signals}

        b.h2("Strategy Scores").blank()
        rows = []
        for strat in ["pullback", "bounce", "ath_breakout", "earnings_dip", "trend_continuation"]:
            icon = strategy_icons.get(strat, "*")
            name = strategy_names.get(strat, strat)

            if strat in signal_by_strategy:
                sig = signal_by_strategy[strat]
                status = (
                    "[OK] Strong"
                    if sig.score >= DISPLAY_SCORE_STRONG
                    else ("[~] Moderate" if sig.score >= DISPLAY_SCORE_MODERATE else "[X] Weak")
                )
                reason = truncate(sig.reason, DISPLAY_REASON_MAX_LEN) if sig.reason else "-"
                rows.append([f"{icon} {name}", f"{sig.score:.1f}/10", status, reason])
            else:
                rows.append([f"{icon} {name}", "N/A", "[X] No signal", "-"])

        b.table(["Strategy", "Score", "Status", "Reason"], rows)
        b.blank()

        if signals:
            best = max(signals, key=lambda x: x.score)
            icon = strategy_icons.get(best.strategy, "*")
            name = strategy_names.get(best.strategy, best.strategy)

            if best.score >= DISPLAY_SCORE_BEST:
                b.status_ok(f"**Best: {icon} {name}** (Score: {best.score:.1f}/10)")
            elif best.score >= DISPLAY_SCORE_OK:
                b.status_warning(f"**Moderate: {icon} {name}** (Score: {best.score:.1f}/10)")
            else:
                b.status_error("**No strong signals.**")

        return b.build()

    @mcp_endpoint(operation="ensemble recommendation", symbol_param="symbol")
    async def get_ensemble_recommendation(self, symbol: str) -> str:
        """
        Get ensemble strategy recommendation for a symbol.

        Uses the trained ensemble selector to recommend the best strategy
        by combining meta-learner predictions, regime-weighted preferences,
        confidence-weighted scoring, and strategy rotation engine.

        Args:
            symbol: Ticker symbol to analyze

        Returns:
            Formatted Markdown ensemble recommendation
        """
        from ..backtesting import (
            EnsembleSelector,
            create_strategy_score,
        )

        symbol = validate_symbol(symbol)

        # Get current VIX for regime context
        vix = await self.get_vix()

        # Run multi-strategy analysis to get scores
        scanner = self._get_scanner()

        historical_days = max(self._config.settings.performance.historical_days, 260)
        data = await self._fetch_historical_cached(symbol, days=historical_days)

        if not data:
            return f"No historical data available for {symbol}"

        prices, volumes, highs, lows, *_ = data
        results = scanner.analyze_symbol(symbol, prices, volumes, highs, lows)

        if not results:
            return f"No analysis results for {symbol}"

        # Convert to StrategyScore format
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

        # Load trained ensemble selector
        try:
            selector = EnsembleSelector.load_trained_model()
        except Exception as e:
            logger.warning(f"Could not load trained ensemble model: {e}")
            selector = EnsembleSelector()

        # Get recommendation
        rec = selector.get_recommendation(symbol, strategy_scores, vix=vix)

        # Format output
        b = MarkdownBuilder()
        b.h1(f"Ensemble Recommendation: {symbol}").blank()

        # Primary Recommendation
        b.h2("Recommended Strategy")
        strategy_icons = {
            "pullback": "[PB]",
            "bounce": "[BN]",
            "ath_breakout": "[ATH]",
            "earnings_dip": "[ED]",
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

        # All Strategy Scores
        b.h2("All Strategies")
        b.text("| Strategy | Score | Confidence | Adjusted |")
        b.text("|----------|-------|------------|----------|")

        for strat, score in sorted(
            rec.strategy_scores.items(), key=lambda x: x[1].adjusted_score, reverse=True
        ):
            marker = " *" if strat == rec.recommended_strategy else ""
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

        return b.build()

    async def get_ensemble_status(self) -> str:
        """
        Get ensemble selector and rotation engine status.

        Returns:
            Formatted Markdown status
        """
        from ..backtesting import EnsembleSelector

        vix = await self.get_vix()

        try:
            selector = EnsembleSelector.load_trained_model()
        except Exception as e:
            logger.warning(f"Could not load ensemble model: {e}")
            return "[!] No trained ensemble model. Run `train_ensemble_v2.py` to train."

        b = MarkdownBuilder()
        b.h1("Ensemble Strategy Status").blank()

        # Current regime
        if vix:
            regime = (
                "low_vol"
                if vix < VIX_LOW_VOL_MAX
                else (
                    "normal"
                    if vix < VIX_NORMAL_MAX
                    else "elevated" if vix < VIX_ELEVATED_MAX else "high_vol"
                )
            )
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
                bar = "#" * int(pref * 20)
                b.text(f"{strat:<15} {pref:>5.1%} {bar}")

            b.blank()

        # Method info
        b.h2("Selector Info")
        b.kv_line("Method", selector.method.value)
        b.kv_line("Rotation Enabled", "Yes" if selector.enable_rotation else "No")
        b.kv_line("Min Score Threshold", f"{selector.min_score_threshold:.1f}")

        return b.build()

    @mcp_endpoint(operation="strike recommendation", symbol_param="symbol")
    async def recommend_strikes(
        self,
        symbol: str,
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
        num_alternatives: int = 3,
    ) -> str:
        """
        Generate optimal strike recommendations for Bull-Put-Spreads.

        Analyzes support levels, Fibonacci retracements, and options chain
        to recommend short/long strike combinations with quality scores.

        Args:
            symbol: Ticker symbol
            dte_min: Minimum days to expiration
            dte_max: Maximum days to expiration
            num_alternatives: Number of alternative recommendations

        Returns:
            Formatted strike recommendations
        """
        symbol = validate_symbol(symbol)

        # Get current quote
        quote = await self._get_quote_cached(symbol)
        if not quote or not quote.last:
            return f"Cannot get quote for {symbol}"

        current_price = quote.last
        vix = await self.get_vix()
        regime = self._vix_selector.get_regime(vix)

        # Get historical data for support levels
        data = await self._fetch_historical_cached(symbol, days=260)
        if not data:
            return f"No historical data for {symbol}"

        prices, volumes, highs, lows, *_ = data

        # Calculate support levels
        support_levels = find_support_levels(lows=lows, lookback=90, window=10, max_levels=5)
        support_levels = [s for s in support_levels if s < current_price]

        # Calculate Fibonacci levels
        recent_high = (
            max(highs[-FIBONACCI_LOOKBACK:]) if len(highs) >= FIBONACCI_LOOKBACK else max(highs)
        )
        recent_low = (
            min(lows[-FIBONACCI_LOOKBACK:]) if len(lows) >= FIBONACCI_LOOKBACK else min(lows)
        )
        fib_levels = calculate_fibonacci(recent_high, recent_low)

        # Get options chain (Tradier -> IBKR fallback, no Marketdata ATM)
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

        # Get recommendation
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

        # Primary recommendation
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

        # Support levels
        if support_levels:
            b.h2("Support Levels")
            for i, level in enumerate(support_levels[:5], 1):
                distance_pct = ((level - current_price) / current_price) * 100
                b.text(f"S{i}: ${level:.2f} ({distance_pct:+.1f}%)")
            b.blank()

        # Liquidity assessment
        if options_data and rec:
            from ..options.liquidity import LiquidityAssessor

            assessor = LiquidityAssessor()
            spread_liq = assessor.assess_spread(rec.short_strike, rec.long_strike, options_data)
            if spread_liq:
                b.h2("Liquidity Assessment")
                quality_upper = spread_liq.overall_quality.upper()
                b.kv_line("Overall Quality", quality_upper)
                b.kv_line("Short Strike OI", f"{spread_liq.short_strike_liquidity.open_interest:,}")
                b.kv_line("Long Strike OI", f"{spread_liq.long_strike_liquidity.open_interest:,}")
                b.kv_line(
                    "Short Bid-Ask Spread", f"{spread_liq.short_strike_liquidity.spread_pct:.1f}%"
                )
                b.kv_line(
                    "Long Bid-Ask Spread", f"{spread_liq.long_strike_liquidity.spread_pct:.1f}%"
                )
                if not spread_liq.is_tradeable:
                    b.blank()
                    b.text("**ILLIQUID - Not recommended for trading**")
                for w in spread_liq.warnings:
                    b.text(f"- {w}")
                b.blank()

        # Fibonacci levels
        b.h2("Fibonacci Retracements")
        for level_name, level_price in sorted(fib_levels.items(), key=lambda x: x[1], reverse=True):
            if level_price < current_price:
                distance_pct = ((level_price - current_price) / current_price) * 100
                b.text(f"{level_name}: ${level_price:.2f} ({distance_pct:+.1f}%)")

        return b.build()
