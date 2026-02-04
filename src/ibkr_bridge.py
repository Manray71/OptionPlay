# OptionPlay - IBKR Bridge Client
# ================================
# Connects OptionPlay with the IBKR MCP Server for exclusive features.
#
# Features:
# - News Headlines
# - VIX (Live)
# - Max Pain & OI data
# - IV Rank
# - Strike recommendations
#
# Note: Requires running IBKR MCP Server (TWS must be running)

import asyncio
import json
import logging
import socket

# ib_insync needs nest_asyncio for compatibility with already running event loops
# (e.g., when the MCP server already uses asyncio.run())
import nest_asyncio
nest_asyncio.apply()

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

# MarkdownBuilder import
from .utils.markdown_builder import MarkdownBuilder, format_price, format_volume

logger = logging.getLogger(__name__)


# =============================================================================
# IBKR SYMBOL MAPPING
# =============================================================================
# Some symbols have different names at IBKR than at other brokers/data providers.
# This mapping converts standard symbols to IBKR-compatible symbols.

IBKR_SYMBOL_MAP = {
    # Berkshire Hathaway - space instead of period
    "BRK.B": "BRK B",
    "BRK.A": "BRK A",

    # Brown-Forman - space instead of period
    "BF.B": "BF B",
    "BF.A": "BF A",

    # Symbols not available at IBKR (delisted, merged, ticker change)
    # Set to None to skip them
    "MMC": None,      # Marsh McLennan - possibly ticker change
    "IPG": None,      # Interpublic Group - possibly delisted
    "PARA": None,     # Paramount - delisted/merged
    "K": None,        # Kellanova - possibly ticker change after spin-off
    "PXD": None,      # Pioneer Natural Resources - acquired by Exxon
    "HES": None,      # Hess - acquired by Chevron
    "MRO": None,      # Marathon Oil - possibly ticker change

    # Additional known issues can be added here
}

# Reverse mapping for back-conversion
IBKR_REVERSE_MAP = {v: k for k, v in IBKR_SYMBOL_MAP.items() if v is not None}


def to_ibkr_symbol(symbol: str) -> Optional[str]:
    """
    Converts a standard symbol to an IBKR-compatible symbol.

    Args:
        symbol: Standard ticker symbol

    Returns:
        IBKR symbol or None if the symbol should be skipped
    """
    symbol = symbol.upper().strip()

    # Check if mapping exists
    if symbol in IBKR_SYMBOL_MAP:
        mapped = IBKR_SYMBOL_MAP[symbol]
        if mapped is None:
            logger.debug(f"Symbol {symbol} is being skipped (no IBKR equivalent)")
        return mapped

    return symbol


def from_ibkr_symbol(ibkr_symbol: str) -> str:
    """
    Converts an IBKR symbol back to the standard symbol.

    Args:
        ibkr_symbol: IBKR ticker symbol

    Returns:
        Standard symbol
    """
    if ibkr_symbol in IBKR_REVERSE_MAP:
        return IBKR_REVERSE_MAP[ibkr_symbol]
    return ibkr_symbol


@dataclass
class IBKRNews:
    """News headline from IBKR"""
    symbol: str
    headline: str
    time: Optional[str] = None
    provider: Optional[str] = None


@dataclass
class MaxPainData:
    """Max Pain data"""
    symbol: str
    current_price: float
    max_pain_strike: float
    distance_pct: float
    put_wall: Dict[str, Any]
    call_wall: Dict[str, Any]
    put_call_ratio: float
    expiry: str


@dataclass
class StrikeRecommendation:
    """Strike recommendation from IBKR"""
    symbol: str
    current_price: float
    short_strike: float
    long_strike: float
    spread_width: float
    reason: str
    delta: Optional[float] = None
    credit: Optional[float] = None
    quality: str = "good"
    confidence: float = 50.0
    vix: Optional[float] = None
    vix_regime: Optional[str] = None
    warnings: List[str] = None


class IBKRBridge:
    """
    Bridge to IBKR MCP Server for exclusive data.

    The IBKR MCP Server runs separately and is supplied with
    market data via TWS/Gateway. This bridge uses the
    tools available there.

    Usage:
        bridge = IBKRBridge()

        if await bridge.is_available():
            news = await bridge.get_news(["AAPL", "MSFT"])
            max_pain = await bridge.get_max_pain(["AAPL"])
    """
    
    # TWS Default Ports
    TWS_PAPER_PORT = 7497
    TWS_LIVE_PORT = 7496
    GATEWAY_PORT = 4001

    def __init__(self, host: str = "127.0.0.1", port: int = 7497):
        self.host = host
        self.port = port
        self._ib = None
        self._connected = False
        self._last_check: Optional[datetime] = None
        self._check_interval = 60  # seconds

    async def is_available(self, force_check: bool = False) -> bool:
        """
        Checks if TWS/Gateway is reachable.

        Caches the result for 60 seconds.
        """
        if not force_check and self._last_check:
            age = (datetime.now() - self._last_check).total_seconds()
            if age < self._check_interval:
                return self._connected
        
        self._last_check = datetime.now()
        
        # Quick Socket Check
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((self.host, self.port))
            sock.close()
            self._connected = result == 0
            
            if self._connected:
                logger.debug(f"TWS reachable at {self.host}:{self.port}")
            else:
                logger.debug(f"TWS not reachable at {self.host}:{self.port}")

            return self._connected

        except Exception as e:
            logger.debug(f"TWS check failed: {e}")
            self._connected = False
            return False

    async def _ensure_connected(self) -> bool:
        """Establishes connection to IBKR."""
        # Check if existing connection is still active
        if self._ib is not None and self._connected:
            if self._ib.isConnected():
                return True
            else:
                logger.warning("IBKR connection lost, reconnecting...")
                self._connected = False
                self._ib = None

        if not await self.is_available():
            return False

        try:
            from ib_insync import IB

            self._ib = IB()
            await self._ib.connectAsync(
                self.host,
                self.port,
                clientId=98,  # Different client than main MCP server
                timeout=10
            )

            if self._ib.isConnected():
                self._connected = True
                logger.info(f"IBKR Bridge verbunden (clientId=98, port={self.port})")
                return True
            else:
                logger.warning("IBKR connectAsync returned but isConnected=False")
                self._connected = False
                return False

        except ImportError:
            logger.warning("ib_insync not installed - IBKR Bridge not available")
            return False
        except Exception as e:
            logger.warning(f"IBKR Bridge connection failed: {type(e).__name__}: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnects."""
        if self._ib:
            self._ib.disconnect()
            self._ib = None
        self._connected = False
    
    # =========================================================================
    # NEWS
    # =========================================================================
    
    async def get_news(
        self,
        symbols: List[str],
        days: int = 5,
        max_per_symbol: int = 5
    ) -> List[IBKRNews]:
        """
        Fetches news headlines for symbols.

        Args:
            symbols: List of ticker symbols
            days: News from the last X days
            max_per_symbol: Max headlines per symbol

        Returns:
            List of IBKRNews
        """
        if not await self._ensure_connected():
            logger.warning("IBKR not available for news retrieval")
            return []
        
        from ib_insync import Stock
        from datetime import timedelta
        
        results = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        for symbol in symbols:
            try:
                stock = Stock(symbol.upper(), "SMART", "USD")
                qualified = self._ib.qualifyContracts(stock)

                if not qualified or not stock.conId:
                    logger.warning(f"News: Could not qualify {symbol} (no conId)")
                    continue

                logger.debug(f"News: Requesting for {symbol} (conId={stock.conId})")

                headlines = await asyncio.wait_for(
                    self._ib.reqHistoricalNewsAsync(
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

        b = MarkdownBuilder()
        b.h1(f"News Headlines ({days} days)").blank()

        if not news:
            b.hint(f"No news found for {', '.join(symbols)} (IBKR not available or no headlines).")
            return b.build()

        # Group by symbol
        by_symbol: Dict[str, List[IBKRNews]] = {}
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
        if not await self._ensure_connected():
            return None
        
        try:
            from ib_insync import Index
            import math
            
            def get_valid(val):
                if val is None:
                    return None
                if isinstance(val, float) and (math.isnan(val) or val <= 0):
                    return None
                return val
            
            vix = Index("VIX", "CBOE")
            self._ib.qualifyContracts(vix)
            
            # With Generic Tick 221 for Mark Price (Pre/Post Market)
            self._ib.reqMktData(vix, "221", False, False)
            await asyncio.sleep(2)  # Wait a bit longer for all data

            ticker = self._ib.ticker(vix)
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
            
            self._ib.cancelMktData(vix)
            
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
    ) -> List[MaxPainData]:
        """
        Calculates Max Pain for symbols.

        Args:
            symbols: List of ticker symbols
            expiry: Expiration YYYYMMDD (optional, otherwise next 30-60 DTE)

        Returns:
            List of MaxPainData
        """
        if not await self._ensure_connected():
            logger.warning("IBKR not available for Max Pain")
            return []
        
        from ib_insync import Stock, Option
        from collections import defaultdict
        import math
        
        results = []
        
        for symbol in symbols:
            try:
                stock = Stock(symbol.upper(), "SMART", "USD")
                self._ib.qualifyContracts(stock)
                
                # Get current price
                self._ib.reqMktData(stock, "", False, False)
                await asyncio.sleep(0.5)
                ticker = self._ib.ticker(stock)
                current_price = ticker.marketPrice() if ticker else None
                self._ib.cancelMktData(stock)

                if not current_price or math.isnan(current_price):
                    continue

                # Get options chain
                chains = await asyncio.wait_for(
                    self._ib.reqSecDefOptParamsAsync(
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
                            self._ib.qualifyContracts(option)
                            self._ib.reqMktData(option, "101", False, False)
                            await asyncio.sleep(0.3)
                            
                            opt_ticker = self._ib.ticker(option)
                            if opt_ticker:
                                oi = opt_ticker.callOpenInterest if right == "C" else opt_ticker.putOpenInterest
                                if oi and not math.isnan(oi):
                                    if right == "C":
                                        oi_data[strike]["call_oi"] = int(oi)
                                    else:
                                        oi_data[strike]["put_oi"] = int(oi)
                            
                            self._ib.cancelMktData(option)
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
    # STATUS
    # =========================================================================
    
    async def get_status(self) -> Dict[str, Any]:
        """Returns bridge status."""
        available = await self.is_available(force_check=True)
        
        return {
            "available": available,
            "host": self.host,
            "port": self.port,
            "connected": self._connected,
            "features": ["news", "vix", "max_pain", "portfolio", "positions"] if available else []
        }
    
    # =========================================================================
    # PORTFOLIO & POSITIONS
    # =========================================================================
    
    async def get_portfolio(self) -> List[Dict[str, Any]]:
        """
        Fetches all positions from the IBKR portfolio.

        Returns:
            List of position dictionaries
        """
        if not await self._ensure_connected():
            logger.warning("IBKR not available for portfolio retrieval")
            return []

        try:
            # Fetch portfolio positions (async version)
            raw_positions = await self._ib.reqPositionsAsync()

            positions = []
            for pos in raw_positions:
                contract = pos.contract

                position_data = {
                    "symbol": contract.symbol,
                    "sec_type": contract.secType,
                    "quantity": pos.position,
                    "avg_cost": pos.avgCost,
                    "account": pos.account,
                }

                # Additional fields for options
                if contract.secType == "OPT":
                    position_data.update({
                        "strike": contract.strike,
                        "right": contract.right,  # 'C' or 'P'
                        "expiry": contract.lastTradeDateOrContractMonth,
                        "multiplier": int(contract.multiplier or 100),
                    })

                positions.append(position_data)

            logger.info(f"IBKR Portfolio: {len(positions)} positions loaded")
            return positions

        except Exception as e:
            logger.error(f"IBKR Portfolio error: {e}")
            return []
    
    async def get_portfolio_formatted(self) -> str:
        """
        Fetches portfolio and formats as Markdown.
        """
        positions = await self.get_portfolio()

        b = MarkdownBuilder()
        b.h1("IBKR Portfolio").blank()

        if not positions:
            b.hint("No positions found (IBKR not connected or empty portfolio).")
            return b.build()

        # Group by type
        stocks = [p for p in positions if p["sec_type"] == "STK"]
        options = [p for p in positions if p["sec_type"] == "OPT"]
        other = [p for p in positions if p["sec_type"] not in ["STK", "OPT"]]

        # Stocks
        if stocks:
            b.h2(f"Stocks ({len(stocks)})").blank()
            rows = []
            for p in stocks:
                market_value = p["quantity"] * p["avg_cost"]
                rows.append([
                    p["symbol"],
                    f"{p['quantity']:,.0f}",
                    f"${p['avg_cost']:.2f}",
                    f"${market_value:,.2f}",
                ])
            b.table(["Symbol", "Qty", "Avg Cost", "Value"], rows)
            b.blank()

        # Options
        if options:
            b.h2(f"Options ({len(options)})").blank()

            # Group by symbol
            by_symbol: Dict[str, List] = {}
            for p in options:
                sym = p["symbol"]
                if sym not in by_symbol:
                    by_symbol[sym] = []
                by_symbol[sym].append(p)

            for symbol, opts in by_symbol.items():
                b.h3(symbol).blank()
                rows = []
                for p in sorted(opts, key=lambda x: (x["expiry"], x["strike"])):
                    right = "Put" if p["right"] == "P" else "Call"
                    qty_str = f"{p['quantity']:+,.0f}"  # With sign
                    rows.append([
                        p["expiry"],
                        f"${p['strike']:.0f}",
                        right,
                        qty_str,
                        f"${p['avg_cost']:.2f}",
                    ])
                b.table(["Expiry", "Strike", "Type", "Qty", "Avg Cost"], rows)
                b.blank()

        # Other
        if other:
            b.h2(f"Other ({len(other)})").blank()
            for p in other:
                b.bullet(f"{p['symbol']} ({p['sec_type']}): {p['quantity']}")
            b.blank()

        # Summary
        b.h2("Summary")
        b.kv_line("Stock Positions", len(stocks))
        b.kv_line("Option Positions", len(options))
        b.kv_line("Other", len(other))
        
        return b.build()
    
    async def get_option_positions(self) -> List[Dict[str, Any]]:
        """
        Fetches only option positions from IBKR.

        Returns:
            List of option positions
        """
        all_positions = await self.get_portfolio()
        return [p for p in all_positions if p["sec_type"] == "OPT"]

    async def get_spreads(self) -> List[Dict[str, Any]]:
        """
        Identifies spread positions (Bull Put Spreads, etc.)

        Returns:
            List of identified spreads
        """
        options = await self.get_option_positions()
        
        if not options:
            return []
        
        # Gruppiere nach Symbol und Expiry
        groups: Dict[str, List] = {}
        for opt in options:
            key = f"{opt['symbol']}_{opt['expiry']}"
            if key not in groups:
                groups[key] = []
            groups[key].append(opt)
        
        spreads = []
        for key, group in groups.items():
            puts = [o for o in group if o["right"] == "P"]
            
            # Bull Put Spread: Short Put (höherer Strike) + Long Put (niedrigerer Strike)
            short_puts = [p for p in puts if p["quantity"] < 0]
            long_puts = [p for p in puts if p["quantity"] > 0]
            
            for short in short_puts:
                # Find matching Long Put
                for long in long_puts:
                    if long["strike"] < short["strike"] and abs(long["quantity"]) == abs(short["quantity"]):
                        # avgCost from IBKR is total cost per contract (not per share)
                        # Net Credit = Short Premium - Long Premium (both totals)
                        net_credit_total = short["avg_cost"] - long["avg_cost"]
                        # Per share = total / 100
                        net_credit_per_share = net_credit_total / 100

                        spread = {
                            "type": "Bull Put Spread",
                            "symbol": short["symbol"],
                            "expiry": short["expiry"],
                            "short_strike": short["strike"],
                            "long_strike": long["strike"],
                            "width": short["strike"] - long["strike"],
                            "contracts": int(abs(short["quantity"])),
                            "short_cost": short["avg_cost"],
                            "long_cost": long["avg_cost"],
                            "net_credit": net_credit_per_share,  # Per share
                            "net_credit_total": net_credit_total * int(abs(short["quantity"])),  # Total
                        }
                        spreads.append(spread)
                        break

        return spreads
    
    async def get_spreads_formatted(self) -> str:
        """
        Fetches spreads and formats as Markdown.
        """
        spreads = await self.get_spreads()

        b = MarkdownBuilder()
        b.h1("IBKR Spread Positions").blank()

        if not spreads:
            b.hint("No spread positions detected.")
            return b.build()
        
        rows = []
        total_credit = 0
        total_max_profit = 0
        total_max_loss = 0
        
        for s in spreads:
            max_profit = s["net_credit"] * s["contracts"] * 100
            max_loss = (s["width"] - s["net_credit"]) * s["contracts"] * 100
            
            total_credit += s.get("net_credit_total", max_profit)
            total_max_profit += max_profit
            total_max_loss += max_loss
            
            # Calculate DTE
            try:
                exp_date = datetime.strptime(s["expiry"], "%Y%m%d").date()
                dte = (exp_date - datetime.now().date()).days
                dte_str = f"{dte}d"
            except (ValueError, KeyError, TypeError) as e:
                logger.debug(f"Could not calculate DTE for {s.get('symbol', '?')}: {e}")
                dte_str = "?"
            
            rows.append([
                s["symbol"],
                f"${s['long_strike']:.0f}/${s['short_strike']:.0f}",
                s["expiry"][:4] + "-" + s["expiry"][4:6] + "-" + s["expiry"][6:],
                dte_str,
                str(s["contracts"]),
                f"${s['net_credit']:.2f}",
                f"${max_profit:,.0f}",
                f"${max_loss:,.0f}",
            ])
        
        b.table(
            ["Symbol", "Strikes", "Expiry", "DTE", "Qty", "Credit", "Max Profit", "Max Loss"],
            rows
        )
        
        b.blank()
        b.h2("Summary")
        b.kv_line("Spreads", len(spreads))
        b.kv_line("Total Credit", f"${total_credit:,.0f}")
        b.kv_line("Max Profit", f"${total_max_profit:,.0f}")
        b.kv_line("Max Loss", f"${total_max_loss:,.0f}")

        return b.build()

    async def get_status_formatted(self) -> str:
        """Status formatted as Markdown."""
        status = await self.get_status()

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
    
    # =========================================================================
    # BATCH QUOTES (Watchlist)
    # =========================================================================
    
    @dataclass
    class QuoteData:
        """Quote data for a symbol."""
        symbol: str
        last: Optional[float] = None
        bid: Optional[float] = None
        ask: Optional[float] = None
        volume: Optional[int] = None
        change: Optional[float] = None
        change_pct: Optional[float] = None
        high: Optional[float] = None
        low: Optional[float] = None
        close: Optional[float] = None
        error: Optional[str] = None

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
        if not await self._ensure_connected():
            logger.warning("IBKR not available for quotes")
            return []
        
        from ib_insync import Stock
        import math
        
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
                    self._ib.qualifyContracts(contract)
                    valid_contracts.append((original_symbol, ibkr_symbol, contract))
                except Exception as e:
                    batch_results.append({
                        "symbol": original_symbol,
                        "error": f"Qualify failed: {e}"
                    })
            
            # Request market data (with generic ticks for pre/post market)
            for original_symbol, ibkr_symbol, contract in valid_contracts:
                try:
                    self._ib.reqMktData(contract, generic_ticks, False, False)
                except Exception as e:
                    logger.debug(f"reqMktData failed for {ibkr_symbol}: {e}")

            # Wait for data (slightly longer for pre/post market data)
            await asyncio.sleep(3 if include_outside_rth else 2)

            # Collect data
            for original_symbol, ibkr_symbol, contract in valid_contracts:
                try:
                    ticker = self._ib.ticker(contract)

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
                    self._ib.cancelMktData(contract)
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
                return "○"  # Closing price
            elif src == "mark":
                return "●"  # Pre/Post Market
            else:
                return ""   # Live - no indicator needed
        
        if gainers:
            b.h2("🟢 Top Gainers").blank()
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
            b.h2("🔴 Top Losers").blank()
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
    ) -> list:
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
        if not await self._ensure_connected():
            logger.warning(f"IBKR not available for options chain ({symbol})")
            return []

        from ib_insync import Stock, Option
        from .data_providers.interface import OptionQuote, DataQuality
        import math

        try:
            ibkr_sym = to_ibkr_symbol(symbol)
            if ibkr_sym is None:
                logger.debug(f"Symbol {symbol} has no IBKR equivalent, skipping")
                return []

            stock = Stock(ibkr_sym, "SMART", "USD")
            self._ib.qualifyContracts(stock)

            # Get current price
            self._ib.reqMktData(stock, "", False, False)
            await asyncio.sleep(0.5)
            ticker = self._ib.ticker(stock)
            current_price = ticker.marketPrice() if ticker else None
            self._ib.cancelMktData(stock)

            if not current_price or math.isnan(current_price):
                logger.warning(f"IBKR: No price for {symbol}, cannot fetch options")
                return []

            # Get options chain definition
            chains = await asyncio.wait_for(
                self._ib.reqSecDefOptParamsAsync(
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

            # Filter strikes to ±20% of current price
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
                    except Exception:
                        continue

                if not contracts:
                    continue

                # Qualify all contracts for this expiry
                all_opts = [c[1] for c in contracts]
                try:
                    self._ib.qualifyContracts(*all_opts)
                except Exception as e:
                    logger.debug(f"IBKR: Qualify failed for {symbol} {expiry_str}: {e}")
                    continue

                # Request market data with Greeks (tick 100=OI, 101=Greeks, 106=IV)
                qualified = [(s, o) for s, o in contracts if o.conId > 0]
                for _, opt in qualified:
                    try:
                        self._ib.reqMktData(opt, "100,101,106", False, False)
                    except Exception as e:
                        logger.debug(f"IBKR reqMktData failed for {symbol}: {e}")

                # Wait for data
                await asyncio.sleep(2)

                # Collect results
                for strike, opt in qualified:
                    try:
                        opt_ticker = self._ib.ticker(opt)
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
                        self._ib.cancelMktData(opt)
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


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_bridge: Optional[IBKRBridge] = None


def get_ibkr_bridge() -> IBKRBridge:
    """Returns global bridge instance."""
    global _default_bridge
    if _default_bridge is None:
        _default_bridge = IBKRBridge()
    return _default_bridge


async def check_ibkr_available() -> bool:
    """Quick check if IBKR is available."""
    bridge = get_ibkr_bridge()
    return await bridge.is_available()
