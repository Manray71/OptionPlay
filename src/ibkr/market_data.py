# OptionPlay - IBKR Market Data
# ================================
"""
Handles IBKR market data retrieval: VIX, quotes, options chains, news, max pain.

Provides:
- Live VIX from IBKR
- Batch quotes for watchlist symbols
- Full options chain with Greeks
- News headlines
- Max Pain calculation
- Formatted Markdown output for all of the above
"""

import asyncio
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from ..utils.markdown_builder import MarkdownBuilder, format_price, format_volume
from .connection import IBKRConnection, to_ibkr_symbol, from_ibkr_symbol

logger = logging.getLogger(__name__)


class IBKRMarketData:
    """
    Market data retrieval via IBKR/TWS.

    Requires a shared IBKRConnection instance.

    Usage:
        conn = IBKRConnection()
        market = IBKRMarketData(conn)
        vix = await market.get_vix()
    """

    def __init__(self, connection: IBKRConnection) -> None:
        self._conn = connection

    # =========================================================================
    # NEWS
    # =========================================================================

    async def get_news(
        self,
        symbols: List[str],
        days: int = 5,
        max_per_symbol: int = 5
    ) -> List["IBKRNews"]:
        """
        Fetches news headlines for symbols.

        Args:
            symbols: List of ticker symbols
            days: News from the last X days
            max_per_symbol: Max headlines per symbol

        Returns:
            List of IBKRNews dataclass instances
        """
        if not await self._conn._ensure_connected():
            logger.warning("IBKR not available for news retrieval")
            return []

        from ib_insync import Stock

        # Import dataclass from package
        from . import IBKRNews

        results = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        for symbol in symbols:
            try:
                stock = Stock(symbol.upper(), "SMART", "USD")
                qualified = self._conn.ib.qualifyContracts(stock)

                if not qualified or not stock.conId:
                    logger.warning(f"News: Could not qualify {symbol} (no conId)")
                    continue

                logger.debug(f"News: Requesting for {symbol} (conId={stock.conId})")

                headlines = await asyncio.wait_for(
                    self._conn.ib.reqHistoricalNewsAsync(
                        stock.conId,
                        providerCodes="DJ-N+DJ-RTA+DJ-RTE+BRFG+BRFUPDN",
                        startDateTime=start_date,
                        endDateTime=end_date,
                        totalResults=max_per_symbol
                    ),
                    timeout=15
                )

                if headlines:
                    logger.debug(f"News: {len(headlines)} Headlines für {symbol}")
                    for h in headlines:
                        results.append(IBKRNews(
                            symbol=symbol.upper(),
                            headline=h.headline,
                            time=h.time.isoformat() if h.time else None,
                            provider=h.providerCode
                        ))
                else:
                    logger.debug(f"News: Keine Headlines für {symbol} (API returned empty)")

            except asyncio.TimeoutError:
                logger.warning(f"News timeout for {symbol} (15s)")
            except Exception as e:
                logger.warning(f"News error for {symbol}: {type(e).__name__}: {e}")

        return results

    async def get_news_formatted(
        self,
        symbols: List[str],
        days: int = 5
    ) -> str:
        """
        Fetches news and formats as Markdown.
        """
        news = await self.get_news(symbols, days)

        # Import dataclass from package
        from . import IBKRNews

        b = MarkdownBuilder()
        b.h1(f"News Headlines ({days} days)").blank()

        if not news:
            b.hint(f"No news found for {', '.join(symbols)} (IBKR not available or no headlines).")
            return b.build()

        # Group by symbol
        by_symbol: Dict[str, List] = {}
        for n in news:
            if n.symbol not in by_symbol:
                by_symbol[n.symbol] = []
            by_symbol[n.symbol].append(n)

        for symbol, headlines in by_symbol.items():
            b.h2(symbol).blank()

            for h in headlines:
                time_str = h.time[:10] if h.time else "?"
                provider = f"[{h.provider}]" if h.provider else ""
                b.bullet(f"**{time_str}** {provider} {h.headline}")

            b.blank()

        return b.build()

    # =========================================================================
    # VIX (LIVE)
    # =========================================================================

    async def get_vix(self) -> Optional[Dict[str, Any]]:
        """
        Fetches VIX from IBKR with fallback for closed market.

        Returns:
            Dict with 'value' and 'source' ("live", "mark", "close") or None
        """
        if not await self._conn._ensure_connected():
            return None

        try:
            from ib_insync import Index

            def get_valid(val):
                if val is None:
                    return None
                if isinstance(val, float) and (math.isnan(val) or val <= 0):
                    return None
                return val

            vix = Index("VIX", "CBOE")
            self._conn.ib.qualifyContracts(vix)

            # With Generic Tick 221 for Mark Price (Pre/Post Market)
            self._conn.ib.reqMktData(vix, "221", False, False)
            await asyncio.sleep(2)  # Wait a bit longer for all data

            ticker = self._conn.ib.ticker(vix)
            price = None
            source = None

            if ticker:
                # Price fallback chain: last -> markPrice -> marketPrice -> close
                last = get_valid(ticker.last)
                mark_price = get_valid(ticker.markPrice) if hasattr(ticker, 'markPrice') else None
                close = get_valid(ticker.close)

                if last:
                    price = last
                    source = "live"
                elif mark_price:
                    price = mark_price
                    source = "mark"  # Pre/Post Market
                else:
                    mp = ticker.marketPrice()
                    if mp and not math.isnan(mp) and mp > 0:
                        price = mp
                        source = "live"
                    elif close:
                        price = close
                        source = "close"

            self._conn.ib.cancelMktData(vix)

            if price:
                return {
                    "value": round(price, 2),
                    "source": source
                }

            return None

        except Exception as e:
            logger.debug(f"IBKR VIX error: {e}")
            return None

    async def get_vix_value(self) -> Optional[float]:
        """
        Convenience method: Returns only the VIX value (for compatibility).

        Returns:
            VIX value or None
        """
        result = await self.get_vix()
        return result["value"] if result else None

    # =========================================================================
    # MAX PAIN
    # =========================================================================

    async def get_max_pain(
        self,
        symbols: List[str],
        expiry: Optional[str] = None
    ) -> List["MaxPainData"]:
        """
        Calculates Max Pain for symbols.

        Args:
            symbols: List of ticker symbols
            expiry: Expiration YYYYMMDD (optional, otherwise next 30-60 DTE)

        Returns:
            List of MaxPainData
        """
        if not await self._conn._ensure_connected():
            logger.warning("IBKR not available for Max Pain")
            return []

        from ib_insync import Stock, Option

        # Import dataclass from package
        from . import MaxPainData

        results = []

        for symbol in symbols:
            try:
                stock = Stock(symbol.upper(), "SMART", "USD")
                self._conn.ib.qualifyContracts(stock)

                # Get current price
                self._conn.ib.reqMktData(stock, "", False, False)
                await asyncio.sleep(0.5)
                ticker = self._conn.ib.ticker(stock)
                current_price = ticker.marketPrice() if ticker else None
                self._conn.ib.cancelMktData(stock)

                if not current_price or math.isnan(current_price):
                    continue

                # Get options chain
                chains = await asyncio.wait_for(
                    self._conn.ib.reqSecDefOptParamsAsync(
                        stock.symbol, "", stock.secType, stock.conId
                    ),
                    timeout=15
                )

                if not chains:
                    continue

                chain = next((c for c in chains if c.exchange == "SMART"), chains[0])

                # Determine expiry
                target_expiry = expiry
                if not target_expiry:
                    today = datetime.now().date()
                    for exp in sorted(chain.expirations):
                        try:
                            exp_date = datetime.strptime(exp, "%Y%m%d").date()
                            days = (exp_date - today).days
                            if 30 <= days <= 60:
                                target_expiry = exp
                                break
                        except (ValueError, TypeError) as e:
                            logger.debug(f"Could not parse expiry {exp}: {e}")
                            continue

                if not target_expiry:
                    continue

                # Collect Open Interest
                oi_data = defaultdict(lambda: {"call_oi": 0, "put_oi": 0})

                for strike in chain.strikes:
                    if abs(strike - current_price) / current_price > 0.3:
                        continue

                    for right in ["C", "P"]:
                        try:
                            option = Option(symbol, target_expiry, strike, right, "SMART")
                            self._conn.ib.qualifyContracts(option)
                            self._conn.ib.reqMktData(option, "101", False, False)
                            await asyncio.sleep(0.3)

                            opt_ticker = self._conn.ib.ticker(option)
                            if opt_ticker:
                                oi = opt_ticker.callOpenInterest if right == "C" else opt_ticker.putOpenInterest
                                if oi and not math.isnan(oi):
                                    if right == "C":
                                        oi_data[strike]["call_oi"] = int(oi)
                                    else:
                                        oi_data[strike]["put_oi"] = int(oi)

                            self._conn.ib.cancelMktData(option)
                        except Exception as e:
                            logger.debug(f"IBKR OI data collection error for strike {strike}: {e}")
                            continue

                if not oi_data:
                    continue

                # Calculate Max Pain
                min_pain = float('inf')
                max_pain_strike = None

                for test_strike in oi_data.keys():
                    total_pain = 0
                    for strike, oi in oi_data.items():
                        if test_strike < strike:
                            total_pain += oi["call_oi"] * (strike - test_strike) * 100
                        if test_strike > strike:
                            total_pain += oi["put_oi"] * (test_strike - strike) * 100

                    if total_pain < min_pain:
                        min_pain = total_pain
                        max_pain_strike = test_strike

                # Find Walls
                max_put = max(oi_data.items(), key=lambda x: x[1]["put_oi"])
                max_call = max(oi_data.items(), key=lambda x: x[1]["call_oi"])

                total_puts = sum(d["put_oi"] for d in oi_data.values())
                total_calls = sum(d["call_oi"] for d in oi_data.values())

                results.append(MaxPainData(
                    symbol=symbol.upper(),
                    current_price=round(current_price, 2),
                    max_pain_strike=max_pain_strike,
                    distance_pct=round((current_price - max_pain_strike) / current_price * 100, 1),
                    put_wall={"strike": max_put[0], "oi": max_put[1]["put_oi"]},
                    call_wall={"strike": max_call[0], "oi": max_call[1]["call_oi"]},
                    put_call_ratio=round(total_puts / max(total_calls, 1), 2),
                    expiry=target_expiry
                ))

            except Exception as e:
                logger.warning(f"Max Pain error for {symbol}: {e}")

        return results

    async def get_max_pain_formatted(self, symbols: List[str]) -> str:
        """Max Pain formatted as Markdown."""
        data = await self.get_max_pain(symbols)

        b = MarkdownBuilder()
        b.h1("Max Pain Analysis").blank()

        if not data:
            b.hint("No Max Pain data available (IBKR not connected or error).")
            return b.build()

        # Build table
        rows = []
        for d in data:
            rows.append([
                d.symbol,
                f"${d.current_price:.2f}",
                f"${d.max_pain_strike:.0f}",
                f"{d.distance_pct:+.1f}%",
                f"{d.put_call_ratio:.2f}",
                f"${d.put_wall['strike']:.0f} ({d.put_wall['oi']:,})",
                f"${d.call_wall['strike']:.0f} ({d.call_wall['oi']:,})"
            ])

        b.table(
            ["Symbol", "Price", "Max Pain", "Distance", "P/C Ratio", "Put Wall", "Call Wall"],
            rows
        )
        b.blank()

        b.text("**Interpretation:**")
        b.bullet("Max Pain = Price with least options pain")
        b.bullet("Negative distance = Price above Max Pain (bullish)")
        b.bullet("P/C Ratio > 1 = More puts than calls (bearish sentiment)")

        return b.build()

    # =========================================================================
    # BATCH QUOTES (Watchlist)
    # =========================================================================

    async def get_quotes_batch(
        self,
        symbols: List[str],
        batch_size: int = 50,
        pause_seconds: int = 60,
        callback: Optional[callable] = None,
        include_outside_rth: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Fetches quotes for many symbols in batches.

        When the market is closed, the close price is used as fallback.
        Pre/post-market data is fetched via Mark Price (Generic Tick 221).

        Args:
            symbols: List of ticker symbols
            batch_size: Symbols per batch (default: 50)
            pause_seconds: Pause between batches in seconds (default: 60)
            callback: Optional callback(batch_num, total_batches, results) after each batch
            include_outside_rth: Include pre/post-market data (default: True)

        Returns:
            List of quote dictionaries
        """
        if not await self._conn._ensure_connected():
            logger.warning("IBKR not available for quotes")
            return []

        from ib_insync import Stock

        # Apply symbol mapping and filter invalid symbols
        mapped_symbols = []
        skipped_symbols = []
        symbol_display_map = {}  # IBKR symbol -> Original symbol for display

        for sym in symbols:
            ibkr_sym = to_ibkr_symbol(sym)
            if ibkr_sym is None:
                skipped_symbols.append(sym.upper())
            else:
                mapped_symbols.append(ibkr_sym)
                symbol_display_map[ibkr_sym] = sym.upper()

        if skipped_symbols:
            logger.info(f"Skipping {len(skipped_symbols)} symbols without IBKR equivalent: {', '.join(skipped_symbols[:5])}...")

        all_results = []

        # Add skipped symbols as errors
        for sym in skipped_symbols:
            all_results.append({
                "symbol": sym,
                "error": "No IBKR equivalent (skipped)"
            })

        total_batches = (len(mapped_symbols) + batch_size - 1) // batch_size if mapped_symbols else 0

        # Generic Tick Types for extended data:
        # 221 = Mark Price (Pre/Post Market)
        # 233 = RT Volume (for real-time trades outside RTH)
        generic_ticks = "221,233" if include_outside_rth else ""

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(mapped_symbols))
            batch_symbols = mapped_symbols[start_idx:end_idx]

            logger.info(f"Batch {batch_num + 1}/{total_batches}: {len(batch_symbols)} Symbole ({start_idx+1}-{end_idx})")

            batch_results = []
            contracts = []

            # Create and qualify contracts
            for ibkr_symbol in batch_symbols:
                original_symbol = symbol_display_map.get(ibkr_symbol, ibkr_symbol)
                try:
                    stock = Stock(ibkr_symbol, "SMART", "USD")
                    contracts.append((original_symbol, ibkr_symbol, stock))
                except Exception as e:
                    batch_results.append({
                        "symbol": original_symbol,
                        "error": str(e)
                    })

            # Qualify
            valid_contracts = []
            for original_symbol, ibkr_symbol, contract in contracts:
                try:
                    self._conn.ib.qualifyContracts(contract)
                    valid_contracts.append((original_symbol, ibkr_symbol, contract))
                except Exception as e:
                    batch_results.append({
                        "symbol": original_symbol,
                        "error": f"Qualify failed: {e}"
                    })

            # Request market data (with generic ticks for pre/post market)
            for original_symbol, ibkr_symbol, contract in valid_contracts:
                try:
                    self._conn.ib.reqMktData(contract, generic_ticks, False, False)
                except Exception as e:
                    logger.debug(f"reqMktData failed for {ibkr_symbol}: {e}")

            # Wait for data (slightly longer for pre/post market data)
            await asyncio.sleep(3 if include_outside_rth else 2)

            # Collect data
            for original_symbol, ibkr_symbol, contract in valid_contracts:
                try:
                    ticker = self._conn.ib.ticker(contract)

                    if ticker:
                        # Helper function: extract value if valid (not NaN, not -1, > 0)
                        def get_valid(val):
                            if val is None:
                                return None
                            if isinstance(val, float) and (math.isnan(val) or val <= 0):
                                return None
                            return val

                        last = get_valid(ticker.last)
                        close = get_valid(ticker.close)
                        bid = get_valid(ticker.bid)
                        ask = get_valid(ticker.ask)
                        high = get_valid(ticker.high)
                        low = get_valid(ticker.low)
                        volume = int(ticker.volume) if get_valid(ticker.volume) else None

                        # Mark Price (Pre/Post Market Preis) - Tick 221
                        mark_price = None
                        if hasattr(ticker, 'markPrice'):
                            mark_price = get_valid(ticker.markPrice)

                        # Price fallback chain: last -> markPrice -> marketPrice -> close
                        price = last
                        price_source = "last"

                        if not price and mark_price:
                            price = mark_price
                            price_source = "mark"  # Pre/Post Market

                        if not price:
                            mp = ticker.marketPrice()
                            if mp and not math.isnan(mp) and mp > 0:
                                price = mp
                                price_source = "market"

                        if not price and close:
                            price = close
                            price_source = "close"

                        # Calculate change (against close)
                        change = None
                        change_pct = None
                        if price and close and close > 0:
                            change = price - close
                            change_pct = (change / close) * 100

                        batch_results.append({
                            "symbol": original_symbol,
                            "last": round(price, 2) if price else None,
                            "bid": round(bid, 2) if bid else None,
                            "ask": round(ask, 2) if ask else None,
                            "high": round(high, 2) if high else None,
                            "low": round(low, 2) if low else None,
                            "close": round(close, 2) if close else None,
                            "volume": volume,
                            "change": round(change, 2) if change else None,
                            "change_pct": round(change_pct, 2) if change_pct else None,
                            "price_source": price_source,  # Info where the price comes from
                        })
                    else:
                        batch_results.append({
                            "symbol": original_symbol,
                            "error": "No ticker data"
                        })

                except Exception as e:
                    batch_results.append({
                        "symbol": original_symbol,
                        "error": str(e)
                    })

            # Cancel market data
            for original_symbol, ibkr_symbol, contract in valid_contracts:
                try:
                    self._conn.ib.cancelMktData(contract)
                except Exception as e:
                    logger.debug(f"Error cancelling market data for {original_symbol}: {e}")

            all_results.extend(batch_results)

            # Callback
            if callback:
                callback(batch_num + 1, total_batches, batch_results)

            # Pause between batches (except for the last one)
            if batch_num < total_batches - 1:
                logger.info(f"Pause {pause_seconds}s before next batch...")
                await asyncio.sleep(pause_seconds)

        logger.info(f"Done: {len(all_results)} quotes fetched")
        return all_results

    async def get_quotes_batch_formatted(
        self,
        symbols: List[str],
        batch_size: int = 50,
        pause_seconds: int = 60
    ) -> str:
        """
        Fetches quotes in batches and formats as Markdown.

        Shows price source:
        - filled circle = Live/Pre-Post-Market price
        - empty circle = Closing price (market closed)
        """
        results = await self.get_quotes_batch(symbols, batch_size, pause_seconds)

        b = MarkdownBuilder()
        b.h1(f"IBKR Watchlist Quotes ({len(results)} Symbols)").blank()

        if not results:
            b.hint("No quotes received.")
            return b.build()

        # Sort by Change %
        valid_quotes = [r for r in results if r.get("last") and not r.get("error")]
        error_quotes = [r for r in results if r.get("error")]

        # Price source statistics
        source_counts = {"last": 0, "mark": 0, "market": 0, "close": 0}
        for q in valid_quotes:
            src = q.get("price_source", "last")
            if src in source_counts:
                source_counts[src] += 1

        # Market status hint
        close_pct = (source_counts["close"] / len(valid_quotes) * 100) if valid_quotes else 0
        mark_count = source_counts["mark"]

        if close_pct > 50:
            b.hint(f"Market closed - {source_counts['close']} of {len(valid_quotes)} prices are closing prices")
            b.blank()
        elif mark_count > 0:
            b.hint(f"Pre/Post-Market active - {mark_count} symbols with after-hours prices")
            b.blank()

        # Top Gainers
        gainers = sorted(
            [q for q in valid_quotes if q.get("change_pct") and q["change_pct"] > 0],
            key=lambda x: x["change_pct"],
            reverse=True
        )[:10]

        # Top Losers
        losers = sorted(
            [q for q in valid_quotes if q.get("change_pct") and q["change_pct"] < 0],
            key=lambda x: x["change_pct"]
        )[:10]

        # Helper function for price source indicator
        def price_indicator(q):
            src = q.get("price_source", "last")
            if src == "close":
                return "\u25cb"  # Closing price
            elif src == "mark":
                return "\u25cf"  # Pre/Post Market
            else:
                return ""   # Live - no indicator needed

        if gainers:
            b.h2("\U0001f7e2 Top Gainers").blank()
            rows = []
            for q in gainers:
                indicator = price_indicator(q)
                symbol_display = f"{q['symbol']} {indicator}" if indicator else q["symbol"]
                rows.append([
                    symbol_display,
                    f"${q['last']:.2f}",
                    f"+{q['change_pct']:.2f}%",
                    f"+${q['change']:.2f}",
                    f"{q['volume']:,}" if q.get('volume') else "-"
                ])
            b.table(["Symbol", "Last", "Change %", "Change $", "Volume"], rows)
            b.blank()

        if losers:
            b.h2("\U0001f534 Top Losers").blank()
            rows = []
            for q in losers:
                indicator = price_indicator(q)
                symbol_display = f"{q['symbol']} {indicator}" if indicator else q["symbol"]
                rows.append([
                    symbol_display,
                    f"${q['last']:.2f}",
                    f"{q['change_pct']:.2f}%",
                    f"${q['change']:.2f}",
                    f"{q['volume']:,}" if q.get('volume') else "-"
                ])
            b.table(["Symbol", "Last", "Change %", "Change $", "Volume"], rows)
            b.blank()

        # All Quotes
        b.h2("All Quotes").blank()
        rows = []
        for q in sorted(valid_quotes, key=lambda x: x["symbol"]):
            indicator = price_indicator(q)
            symbol_display = f"{q['symbol']} {indicator}" if indicator else q["symbol"]
            change_str = f"{q['change_pct']:+.2f}%" if q.get('change_pct') else "-"
            rows.append([
                symbol_display,
                f"${q['last']:.2f}",
                f"${q.get('bid', 0):.2f}" if q.get('bid') else "-",
                f"${q.get('ask', 0):.2f}" if q.get('ask') else "-",
                change_str,
                f"{q['volume']:,}" if q.get('volume') else "-"
            ])
        b.table(["Symbol", "Last", "Bid", "Ask", "Change", "Volume"], rows)

        # Errors
        if error_quotes:
            b.blank()
            b.h2(f"Errors ({len(error_quotes)})")
            for q in error_quotes[:10]:
                b.bullet(f"{q['symbol']}: {q['error']}")
            if len(error_quotes) > 10:
                b.hint(f"... and {len(error_quotes) - 10} more")

        # Summary
        b.blank()
        b.h2("Summary")
        b.kv_line("Successful Quotes", len(valid_quotes))
        b.kv_line("Errors", len(error_quotes))
        b.kv_line("Total", len(results))

        # Price source details
        if source_counts["close"] > 0 or source_counts["mark"] > 0:
            b.blank()
            b.text("**Price Sources:**")
            if source_counts["last"] > 0:
                b.bullet(f"Live: {source_counts['last']}")
            if source_counts["mark"] > 0:
                b.bullet(f"Pre/Post-Market: {source_counts['mark']}")
            if source_counts["close"] > 0:
                b.bullet(f"Closing Price: {source_counts['close']}")

        return b.build()

    # =========================================================================
    # OPTIONS CHAIN (for Strike Recommendations)
    # =========================================================================

    async def get_option_chain(
        self,
        symbol: str,
        dte_min: int = 60,
        dte_max: int = 90,
        right: str = "P",
    ) -> List[Any]:
        """
        Fetch full options chain from IBKR/TWS with Greeks.

        Returns OptionQuote objects compatible with the DataProvider interface.
        Used as fallback when Tradier is not available.

        Args:
            symbol: Ticker symbol
            dte_min: Minimum days to expiration
            dte_max: Maximum days to expiration
            right: Option type - "P" for puts, "C" for calls

        Returns:
            List of OptionQuote objects
        """
        if not await self._conn._ensure_connected():
            logger.warning(f"IBKR not available for options chain ({symbol})")
            return []

        from ib_insync import Stock, Option
        from ..data_providers.interface import OptionQuote, DataQuality

        try:
            ibkr_sym = to_ibkr_symbol(symbol)
            if ibkr_sym is None:
                logger.debug(f"Symbol {symbol} has no IBKR equivalent, skipping")
                return []

            stock = Stock(ibkr_sym, "SMART", "USD")
            self._conn.ib.qualifyContracts(stock)

            # Get current price
            self._conn.ib.reqMktData(stock, "", False, False)
            await asyncio.sleep(0.5)
            ticker = self._conn.ib.ticker(stock)
            current_price = ticker.marketPrice() if ticker else None
            self._conn.ib.cancelMktData(stock)

            if not current_price or math.isnan(current_price):
                logger.warning(f"IBKR: No price for {symbol}, cannot fetch options")
                return []

            # Get options chain definition
            chains = await asyncio.wait_for(
                self._conn.ib.reqSecDefOptParamsAsync(
                    stock.symbol, "", stock.secType, stock.conId
                ),
                timeout=15,
            )

            if not chains:
                logger.warning(f"IBKR: No options chain for {symbol}")
                return []

            chain = next((c for c in chains if c.exchange == "SMART"), chains[0])

            # Filter expirations by DTE range
            today = datetime.now().date()
            valid_expiries = []
            for exp in sorted(chain.expirations):
                try:
                    exp_date = datetime.strptime(exp, "%Y%m%d").date()
                    days = (exp_date - today).days
                    if dte_min <= days <= dte_max:
                        valid_expiries.append((exp, exp_date, days))
                except (ValueError, TypeError):
                    continue

            if not valid_expiries:
                logger.debug(f"IBKR: No expirations in DTE range {dte_min}-{dte_max} for {symbol}")
                return []

            # Filter strikes to +/-20% of current price
            max_distance = 0.20
            valid_strikes = [
                s for s in chain.strikes
                if abs(s - current_price) / current_price <= max_distance
            ]

            right_upper = right.upper()
            results = []

            for expiry_str, expiry_date, dte in valid_expiries:
                contracts = []
                for strike in valid_strikes:
                    try:
                        opt = Option(ibkr_sym, expiry_str, strike, right_upper, "SMART")
                        contracts.append((strike, opt))
                    except (TypeError, ValueError) as e:
                        logger.warning("Contract creation failed for %s strike=%s: %s", symbol, strike, e)
                        continue

                if not contracts:
                    continue

                # Qualify all contracts for this expiry
                all_opts = [c[1] for c in contracts]
                try:
                    self._conn.ib.qualifyContracts(*all_opts)
                except Exception as e:
                    logger.debug(f"IBKR: Qualify failed for {symbol} {expiry_str}: {e}")
                    continue

                # Request market data with Greeks (tick 100=OI, 101=Greeks, 106=IV)
                qualified = [(s, o) for s, o in contracts if o.conId > 0]
                for _, opt in qualified:
                    try:
                        self._conn.ib.reqMktData(opt, "100,101,106", False, False)
                    except Exception as e:
                        logger.debug(f"IBKR reqMktData failed for {symbol}: {e}")

                # Wait for data
                await asyncio.sleep(2)

                # Collect results
                for strike, opt in qualified:
                    try:
                        opt_ticker = self._conn.ib.ticker(opt)
                        if not opt_ticker:
                            continue

                        bid = opt_ticker.bid if opt_ticker.bid and not math.isnan(opt_ticker.bid) else None
                        ask = opt_ticker.ask if opt_ticker.ask and not math.isnan(opt_ticker.ask) else None
                        last = opt_ticker.last if opt_ticker.last and not math.isnan(opt_ticker.last) else None

                        # Skip if no pricing at all
                        if bid is None and ask is None and last is None:
                            continue

                        # Greeks from model
                        delta = None
                        gamma = None
                        theta = None
                        vega = None
                        iv = None

                        if opt_ticker.modelGreeks:
                            mg = opt_ticker.modelGreeks
                            delta = mg.delta if mg.delta and not math.isnan(mg.delta) else None
                            gamma = mg.gamma if mg.gamma and not math.isnan(mg.gamma) else None
                            theta = mg.theta if mg.theta and not math.isnan(mg.theta) else None
                            vega = mg.vega if mg.vega and not math.isnan(mg.vega) else None
                            iv = mg.impliedVol if mg.impliedVol and not math.isnan(mg.impliedVol) else None

                        # Open interest
                        oi = None
                        if right_upper == "P":
                            raw_oi = opt_ticker.putOpenInterest
                        else:
                            raw_oi = opt_ticker.callOpenInterest
                        if raw_oi and not math.isnan(raw_oi):
                            oi = int(raw_oi)

                        volume_val = None
                        if opt_ticker.volume and not math.isnan(opt_ticker.volume):
                            volume_val = int(opt_ticker.volume)

                        results.append(OptionQuote(
                            symbol=f"{symbol}{expiry_str}{right_upper}{strike:.0f}",
                            underlying=symbol,
                            underlying_price=current_price,
                            expiry=expiry_date,
                            strike=strike,
                            right=right_upper,
                            bid=bid,
                            ask=ask,
                            last=last,
                            volume=volume_val,
                            open_interest=oi,
                            implied_volatility=iv,
                            delta=delta,
                            gamma=gamma,
                            theta=theta,
                            vega=vega,
                            timestamp=datetime.now(),
                            data_quality=DataQuality.DELAYED_15MIN,
                            source="ibkr",
                        ))
                    except Exception as e:
                        logger.debug(f"IBKR option data error {symbol} {strike}: {e}")

                # Cancel market data for this expiry
                for _, opt in qualified:
                    try:
                        self._conn.ib.cancelMktData(opt)
                    except Exception as e:
                        logger.debug(f"IBKR cancelMktData failed: {e}")

            logger.info(f"IBKR options chain: {len(results)} options for {symbol}")
            return results

        except asyncio.TimeoutError:
            logger.warning(f"IBKR options chain timeout for {symbol}")
            return []
        except Exception as e:
            logger.warning(f"IBKR options chain error for {symbol}: {type(e).__name__}: {e}")
            return []

    # =========================================================================
    # STATUS (formatted)
    # =========================================================================

    async def get_status_formatted(self) -> str:
        """Status formatted as Markdown."""
        status = await self._conn.get_status()

        b = MarkdownBuilder()
        b.h1("IBKR Bridge Status").blank()

        b.kv("Status", "Available" if status["available"] else "Not available")
        b.kv("Host", f"{status['host']}:{status['port']}")
        b.kv("Connected", "Yes" if status["connected"] else "No")

        if status["features"]:
            b.blank()
            b.text("**Available Features:**")
            for f in status["features"]:
                b.bullet(f)
        else:
            b.blank()
            b.hint("TWS/Gateway must be running for IBKR features.")
            b.hint("Start TWS and enable API (Edit > Global Config > API > Settings)")

        return b.build()
