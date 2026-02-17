# OptionPlay - Options Service
# ==============================
"""
Service für Options-Chain Abfragen und Strike-Empfehlungen.

Verantwortlichkeiten:
- Options-Chain abrufen
- Strike-Empfehlungen generieren
- IV-Rang berechnen
- Options-Daten formatieren

Ersetzt die Options-Logik aus mcp_server.py.

Verwendung:
    from src.services import OptionsService
    from src.services.base import create_service_context

    context = create_service_context()
    options_service = OptionsService(context)

    # Options Chain
    result = await options_service.get_options_chain("AAPL", dte_min=60, dte_max=90)

    # Strike Empfehlung
    result = await options_service.get_strike_recommendation("AAPL")
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..constants.trading_rules import SPREAD_DTE_MAX, SPREAD_DTE_MIN
from ..indicators.support_resistance import calculate_fibonacci, find_support_levels
from ..models.result import ServiceResult
from ..options.strike_recommender import (
    StrikeQuality,
    StrikeRecommendation,
    StrikeRecommender,
)
from ..services.vix_strategy import MarketRegime
from ..utils.markdown_builder import MarkdownBuilder, format_price
from ..utils.validation import ValidationError, validate_dte_range, validate_right, validate_symbol
from .base import BaseService, ServiceContext

logger = logging.getLogger(__name__)


class OptionsService(BaseService):
    """
    Service für Options-Abfragen und Strike-Empfehlungen.

    Features:
    - Options-Chain Abruf mit Greeks
    - Strike-Empfehlungen basierend auf Support-Levels
    - IV-Rang Berechnung
    - Formatierte Markdown-Ausgabe

    Attributes:
        _strike_recommender: StrikeRecommender Instanz
    """

    def __init__(self, context: ServiceContext) -> None:
        """
        Initialisiert den Options Service.

        Args:
            context: Shared ServiceContext
        """
        super().__init__(context)
        self._strike_recommender = StrikeRecommender()

    async def get_options_chain(
        self,
        symbol: str,
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
        right: str = "P",
    ) -> ServiceResult[dict[str, Any]]:
        """
        Holt Options-Chain für ein Symbol.

        Args:
            symbol: Ticker-Symbol
            dte_min: Minimale Days to Expiration
            dte_max: Maximale Days to Expiration
            right: "P" für Puts, "C" für Calls

        Returns:
            ServiceResult mit Options-Chain Daten
        """
        start_time = datetime.now()

        # Validierung
        try:
            symbol = validate_symbol(symbol)
            dte_min, dte_max = validate_dte_range(dte_min, dte_max)
            right = validate_right(right)
        except ValidationError as e:
            return ServiceResult.fail(str(e))

        try:
            provider = await self._get_provider()

            async with self._rate_limited():
                options = await provider.get_option_chain(
                    symbol=symbol, dte_min=dte_min, dte_max=dte_max
                )

            if not options:
                return ServiceResult.fail(f"No options data for {symbol}")

            # Nach Right filtern
            if right == "P":
                options = [o for o in options if getattr(o, "right", "") == "P"]
            elif right == "C":
                options = [o for o in options if getattr(o, "right", "") == "C"]

            # Zu Dicts konvertieren
            options_data = [self._option_to_dict(o) for o in options]

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ServiceResult.ok(
                data={
                    "symbol": symbol,
                    "right": right,
                    "dte_range": f"{dte_min}-{dte_max}",
                    "count": len(options_data),
                    "options": options_data,
                },
                source="api",
                duration_ms=duration_ms,
            )

        except Exception as e:
            self._logger.error(f"Options chain fetch failed for {symbol}: {e}")
            return ServiceResult.fail(f"Options chain fetch failed: {e}")

    async def get_strike_recommendation(
        self,
        symbol: str,
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
        num_alternatives: int = 3,
        regime: Optional[MarketRegime] = None,
    ) -> ServiceResult[dict[str, Any]]:
        """
        Generiert Strike-Empfehlung für Bull-Put-Spread.

        Args:
            symbol: Ticker-Symbol
            dte_min: Minimale DTE
            dte_max: Maximale DTE
            num_alternatives: Anzahl alternativer Empfehlungen
            regime: Optional MarketRegime (für VIX-basierte Anpassung)

        Returns:
            ServiceResult mit Strike-Empfehlungen
        """
        start_time = datetime.now()

        # Validierung
        try:
            symbol = validate_symbol(symbol)
            dte_min, dte_max = validate_dte_range(dte_min, dte_max)
        except ValidationError as e:
            return ServiceResult.fail(str(e))

        try:
            provider = await self._get_provider()

            # Quote für aktuellen Preis
            async with self._rate_limited():
                quote = await provider.get_quote(symbol)

            if not quote or not quote.last:
                return ServiceResult.fail(f"Cannot get current price for {symbol}")

            current_price = quote.last

            # Historical Data für Support-Levels
            async with self._rate_limited():
                historical = await provider.get_historical_for_scanner(symbol, days=90)

            if not historical or not historical[0]:
                return ServiceResult.fail(f"Insufficient historical data for {symbol}")

            prices, volumes, highs, lows, *_ = historical

            # Support-Levels berechnen
            support_levels = find_support_levels(
                lows=lows, lookback=min(60, len(lows)), window=5, max_levels=5
            )

            # Fibonacci-Levels
            lookback = min(90, len(prices))
            fib_high = max(highs[-lookback:]) if highs else max(prices[-lookback:])
            fib_low = min(lows[-lookback:]) if lows else min(prices[-lookback:])
            fib_levels_dict = calculate_fibonacci(high=fib_high, low=fib_low)
            fib_levels: Optional[list[dict[Any, Any]]] = [fib_levels_dict]

            # Optional: Options-Chain für Delta-basierte Empfehlung
            options_data = None
            try:
                async with self._rate_limited():
                    options = await provider.get_option_chain(
                        symbol=symbol, dte_min=dte_min, dte_max=dte_max
                    )
                if options:
                    options_data = [
                        self._option_to_dict(o) for o in options if getattr(o, "right", "") == "P"
                    ]
            except Exception as e:
                self._logger.warning(f"Could not fetch options for strike recommendation: {e}")

            # Empfehlung generieren
            recommendation = self._strike_recommender.get_recommendation(
                symbol=symbol,
                current_price=current_price,
                support_levels=support_levels,
                options_data=options_data,
                fib_levels=fib_levels,
                dte=int((dte_min + dte_max) / 2),
                regime=regime,
            )

            self._logger.info(
                f"Strike recommendation for {symbol}: "
                f"short={recommendation.short_strike} (d={recommendation.estimated_delta}), "
                f"long={recommendation.long_strike} (d={recommendation.long_delta}), "
                f"width={recommendation.spread_width}"
            )

            # Alternativen generieren
            alternatives = []
            if num_alternatives > 1:
                alternatives = self._strike_recommender.get_multiple_recommendations(
                    symbol=symbol,
                    current_price=current_price,
                    support_levels=support_levels,
                    options_data=options_data,
                    fib_levels=fib_levels,
                    num_alternatives=num_alternatives,
                )

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            return ServiceResult.ok(
                data={
                    "symbol": symbol,
                    "current_price": current_price,
                    "recommendation": recommendation.to_dict(),
                    "alternatives": [a.to_dict() for a in alternatives],
                    "support_levels": support_levels,
                    "fib_levels": fib_levels,
                },
                source="calculated",
                duration_ms=duration_ms,
            )

        except Exception as e:
            self._logger.error(f"Strike recommendation failed for {symbol}: {e}")
            return ServiceResult.fail(f"Strike recommendation failed: {e}")

    async def get_options_chain_formatted(
        self,
        symbol: str,
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
        right: str = "P",
    ) -> str:
        """
        Holt Options-Chain und formatiert als Markdown.

        Args:
            symbol: Ticker-Symbol
            dte_min: Minimale DTE
            dte_max: Maximale DTE
            right: "P" oder "C"

        Returns:
            Formatierter Markdown-String
        """
        result = await self.get_options_chain(symbol, dte_min, dte_max, right)

        if not result.success:
            return f"❌ Options chain failed for {symbol}: {result.error}"

        return self._format_options_chain(result.data)

    async def get_strike_recommendation_formatted(
        self,
        symbol: str,
        dte_min: int = SPREAD_DTE_MIN,
        dte_max: int = SPREAD_DTE_MAX,
        num_alternatives: int = 3,
    ) -> str:
        """
        Generiert Strike-Empfehlung und formatiert als Markdown.

        Args:
            symbol: Ticker-Symbol
            dte_min: Minimale DTE
            dte_max: Maximale DTE
            num_alternatives: Anzahl Alternativen

        Returns:
            Formatierter Markdown-String
        """
        result = await self.get_strike_recommendation(symbol, dte_min, dte_max, num_alternatives)

        if not result.success:
            return f"❌ Strike recommendation failed for {symbol}: {result.error}"

        return self._format_strike_recommendation(result.data)

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _option_to_dict(self, option: Any) -> dict[str, Any]:
        """Konvertiert Option-Objekt zu Dictionary."""
        if hasattr(option, "to_dict"):
            result: dict[str, Any] = option.to_dict()
            return result

        return {
            "strike": getattr(option, "strike", None),
            "expiration": str(getattr(option, "expiration", "")),
            "right": getattr(option, "right", None),
            "bid": getattr(option, "bid", None),
            "ask": getattr(option, "ask", None),
            "last": getattr(option, "last", None),
            "volume": getattr(option, "volume", None),
            "open_interest": getattr(option, "openInterest", None)
            or getattr(option, "open_interest", None),
            "delta": getattr(option, "delta", None),
            "gamma": getattr(option, "gamma", None),
            "theta": getattr(option, "theta", None),
            "vega": getattr(option, "vega", None),
            "iv": getattr(option, "iv", None) or getattr(option, "impliedVolatility", None),
        }

    def _format_options_chain(self, data: dict[str, Any]) -> str:
        """Formatiert Options-Chain als Markdown."""
        b = MarkdownBuilder()

        symbol = data.get("symbol", "Unknown")
        right = data.get("right", "P")
        right_name = "Puts" if right == "P" else "Calls"
        count = data.get("count", 0)
        dte_range = data.get("dte_range", "")

        b.h1(f"📊 {symbol} Options Chain ({right_name})").blank()
        b.kv("DTE Range", dte_range)
        b.kv("Options Found", count)
        b.blank()

        options = data.get("options", [])
        if not options:
            b.hint("No options data available.")
            return b.build()

        # Gruppiere nach Expiration
        by_expiry: dict[str, list[dict[str, Any]]] = {}
        for opt in options:
            exp = opt.get("expiration", "Unknown")[:10]  # Nur Datum
            if exp not in by_expiry:
                by_expiry[exp] = []
            by_expiry[exp].append(opt)

        for expiry, opts in sorted(by_expiry.items()):
            b.h2(f"Expiry: {expiry}").blank()

            rows = []
            for opt in sorted(opts, key=lambda x: x.get("strike", 0), reverse=True)[:10]:
                strike = opt.get("strike")
                bid = opt.get("bid")
                ask = opt.get("ask")
                delta = opt.get("delta")
                iv = opt.get("iv")
                oi = opt.get("open_interest")

                rows.append(
                    [
                        format_price(strike) if strike else "-",
                        format_price(bid) if bid else "-",
                        format_price(ask) if ask else "-",
                        f"{delta:.2f}" if delta else "-",
                        f"{iv * 100:.1f}%" if iv else "-",
                        str(oi) if oi else "-",
                    ]
                )

            b.table(["Strike", "Bid", "Ask", "Delta", "IV", "OI"], rows)
            b.blank()

        return b.build()

    def _format_strike_recommendation(self, data: dict[str, Any]) -> str:
        """Formatiert Strike-Empfehlung als Markdown."""
        b = MarkdownBuilder()

        symbol = data.get("symbol", "Unknown")
        current_price = data.get("current_price", 0)
        rec = data.get("recommendation", {})

        b.h1(f"🎯 Strike Recommendation: {symbol}").blank()
        b.kv("Current Price", format_price(current_price))
        b.blank()

        # Hauptempfehlung
        b.h2("Primary Recommendation").blank()

        short_strike = rec.get("short_strike")
        long_strike = rec.get("long_strike")
        spread_width = rec.get("spread_width")
        quality = rec.get("quality", "unknown")
        confidence = rec.get("confidence_score", 0)
        reason = rec.get("short_strike_reason", "")

        quality_emoji = {"excellent": "🟢", "good": "🟡", "acceptable": "🟠", "poor": "🔴"}.get(
            quality, "⚪"
        )

        b.kv("Short Strike", format_price(short_strike) if short_strike else "-")
        b.kv("Long Strike", format_price(long_strike) if long_strike else "-")
        b.kv("Spread Width", format_price(spread_width) if spread_width else "-")

        # Show deltas if available
        short_delta = rec.get("estimated_delta")
        long_delta = rec.get("long_delta")
        if short_delta is not None:
            b.kv("Short Delta", f"{short_delta:.2f}")
        if long_delta is not None:
            b.kv("Long Delta", f"{long_delta:.2f}")

        b.kv("Quality", f"{quality_emoji} {quality.upper()}")
        b.kv("Confidence", f"{confidence}/100")
        b.kv("Reason", reason)
        b.blank()

        # Metrics
        if rec.get("estimated_credit"):
            b.h3("Estimated Metrics").blank()
            b.kv("Est. Credit", format_price(rec.get("estimated_credit")))
            b.kv("Max Profit", f"${rec.get('max_profit', 0):.2f}")
            b.kv("Max Loss", f"${rec.get('max_loss', 0):.2f}")
            b.kv("Break-Even", format_price(rec.get("break_even")))
            if rec.get("prob_profit"):
                b.kv("P(Profit)", f"{rec.get('prob_profit'):.1f}%")
            b.blank()

        # Warnungen
        warnings = rec.get("warnings", [])
        if warnings:
            b.h3("⚠️ Warnings").blank()
            for warning in warnings:
                b.bullet(warning)
            b.blank()

        # Alternativen
        alternatives = data.get("alternatives", [])
        if alternatives:
            b.h2("Alternatives").blank()
            rows = []
            for alt in alternatives:
                alt_quality = alt.get("quality", "?")
                rows.append(
                    [
                        format_price(alt.get("short_strike")),
                        format_price(alt.get("long_strike")),
                        format_price(alt.get("spread_width")),
                        alt_quality.upper()[:4],
                        f"{alt.get('confidence_score', 0)}",
                    ]
                )
            b.table(["Short", "Long", "Width", "Qual", "Conf"], rows)
            b.blank()

        # Support Levels
        support_levels = data.get("support_levels", [])
        if support_levels:
            b.h3("Support Levels Used").blank()
            for level in support_levels[:5]:
                dist_pct = ((current_price - level) / current_price) * 100
                b.bullet(f"{format_price(level)} ({dist_pct:.1f}% below)")

        return b.build()
