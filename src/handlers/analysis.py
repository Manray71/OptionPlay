"""
Analysis Handler Module
=======================

Handles symbol analysis, ensemble recommendations, and strike recommendations.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from ..utils.error_handler import mcp_endpoint
from ..utils.markdown_builder import MarkdownBuilder, truncate
from ..utils.validation import validate_symbol
from ..vix_strategy import get_strategy_for_vix
from ..cache import get_earnings_fetcher
from ..strike_recommender import StrikeRecommender
from ..indicators.support_resistance import find_support_levels, calculate_fibonacci
from .base import BaseHandlerMixin

logger = logging.getLogger(__name__)


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
            prices, volumes, highs, lows, *_ = historical
            current_price = prices[-1]
            sma_20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else current_price
            sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else current_price
            sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else current_price

            b.h2("Technical Indicators")
            up_20 = "[UP]" if current_price > sma_20 else "[DN]"
            up_50 = "[UP]" if current_price > sma_50 else "[DN]"
            up_200 = "[UP]" if current_price > sma_200 else "[DN]"
            b.kv_line("SMA 20", f"${sma_20:.2f} {up_20}")
            b.kv_line("SMA 50", f"${sma_50:.2f} {up_50}")
            b.kv_line("SMA 200", f"${sma_200:.2f} {up_200}")
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
            if earnings.days_to_earnings and earnings.days_to_earnings < 45:
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
        provider = await self._ensure_connected()

        historical_days = max(self._config.settings.performance.historical_days, 260)
        data = await self._fetch_historical_cached(symbol, days=historical_days)

        if not data:
            return f"No historical data available for {symbol}"

        prices, volumes, highs, lows, *_ = data

        quote = await self._get_quote_cached(symbol)
        vix = await self.get_vix()

        # Initialize scanner with earnings data
        scanner = self._get_multi_scanner(min_score=0)

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
            'pullback': '[PB]', 'bounce': '[BN]',
            'ath_breakout': '[ATH]', 'earnings_dip': '[ED]',
        }
        strategy_names = {
            'pullback': 'Bull-Put-Spread', 'bounce': 'Support Bounce',
            'ath_breakout': 'ATH Breakout', 'earnings_dip': 'Earnings Dip',
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
            if earnings.days_to_earnings < 45:
                b.kv_line("Earnings", f"[X] {earnings.days_to_earnings}d - DO NOT TRADE")
            elif earnings.days_to_earnings < 60:
                b.kv_line("Earnings", f"[!] {earnings.days_to_earnings}d - CAUTION")
            else:
                b.kv_line("Earnings", f"[OK] {earnings.days_to_earnings}d")
        else:
            b.kv_line("Earnings", "N/A")
        b.blank()

        signal_by_strategy = {s.strategy: s for s in signals}

        b.h2("Strategy Scores").blank()
        rows = []
        for strat in ['pullback', 'bounce', 'ath_breakout', 'earnings_dip']:
            icon = strategy_icons.get(strat, '*')
            name = strategy_names.get(strat, strat)

            if strat in signal_by_strategy:
                sig = signal_by_strategy[strat]
                status = "[OK] Strong" if sig.score >= 7 else ("[~] Moderate" if sig.score >= 5 else "[X] Weak")
                reason = truncate(sig.reason, 35) if sig.reason else "-"
                rows.append([f"{icon} {name}", f"{sig.score:.1f}/10", status, reason])
            else:
                rows.append([f"{icon} {name}", "N/A", "[X] No signal", "-"])

        b.table(["Strategy", "Score", "Status", "Reason"], rows)
        b.blank()

        if signals:
            best = max(signals, key=lambda x: x.score)
            icon = strategy_icons.get(best.strategy, '*')
            name = strategy_names.get(best.strategy, best.strategy)

            if best.score >= 6:
                b.status_ok(f"**Best: {icon} {name}** (Score: {best.score:.1f}/10)")
            elif best.score >= 4:
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
        from ..backtesting.ensemble_selector import (
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
        from ..backtesting.ensemble_selector import EnsembleSelector

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
        dte_min: int = 45,
        dte_max: int = 60,
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
        provider = await self._ensure_connected()

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
        recent_high = max(highs[-60:]) if len(highs) >= 60 else max(highs)
        recent_low = min(lows[-60:]) if len(lows) >= 60 else min(lows)
        fib_levels = calculate_fibonacci(recent_high, recent_low)

        # Get options chain
        await self._rate_limiter.acquire()
        options = await provider.get_option_chain(symbol, dte_min=dte_min, dte_max=dte_max, right="P")
        self._rate_limiter.record_success()

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
        b.kv_line("Est. Delta", f"{rec.estimated_delta:.2f}" if rec.estimated_delta else "N/A")
        b.kv_line("Prob. Profit", f"{rec.prob_profit:.0%}" if rec.prob_profit else "N/A")
        b.kv_line("Quality", rec.quality.value if rec.quality else "N/A")
        b.blank()

        # Support levels
        if support_levels:
            b.h2("Support Levels")
            for i, level in enumerate(support_levels[:5], 1):
                distance_pct = ((level - current_price) / current_price) * 100
                b.text(f"S{i}: ${level:.2f} ({distance_pct:+.1f}%)")
            b.blank()

        # Fibonacci levels
        b.h2("Fibonacci Retracements")
        for level_name, level_price in sorted(fib_levels.items(), key=lambda x: x[1], reverse=True):
            if level_price < current_price:
                distance_pct = ((level_price - current_price) / current_price) * 100
                b.text(f"{level_name}: ${level_price:.2f} ({distance_pct:+.1f}%)")

        return b.build()
