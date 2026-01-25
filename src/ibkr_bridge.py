# OptionPlay - IBKR Bridge Client
# ================================
# Verbindet OptionPlay mit dem IBKR MCP Server für exklusive Features.
#
# Features:
# - News Headlines
# - VIX (Live)
# - Max Pain & OI-Daten
# - IV-Rank
# - Strike-Empfehlungen
#
# Hinweis: Erfordert laufenden IBKR MCP Server (TWS muss laufen)

import asyncio
import json
import logging
import socket

# Fix für nested event loops (ib_insync in async context)
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass
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
# Einige Symbole haben bei IBKR andere Namen als bei anderen Brokern/Datenanbietern.
# Dieses Mapping konvertiert Standard-Symbole zu IBKR-kompatiblen Symbolen.

IBKR_SYMBOL_MAP = {
    # Berkshire Hathaway - Leerzeichen statt Punkt
    "BRK.B": "BRK B",
    "BRK.A": "BRK A",
    
    # Brown-Forman - Leerzeichen statt Punkt
    "BF.B": "BF B",
    "BF.A": "BF A",
    
    # Symbole die bei IBKR nicht verfügbar sind (delisted, merged, ticker change)
    # Setze auf None um sie zu überspringen
    "MMC": None,      # Marsh McLennan - möglicherweise ticker change
    "IPG": None,      # Interpublic Group - möglicherweise delisted
    "PARA": None,     # Paramount - delisted/merged
    "K": None,        # Kellanova - möglicherweise ticker change nach Spin-off
    "PXD": None,      # Pioneer Natural Resources - acquired by Exxon
    "HES": None,      # Hess - acquired by Chevron
    "MRO": None,      # Marathon Oil - möglicherweise ticker change
    
    # Weitere bekannte Probleme können hier ergänzt werden
}

# Reverse Mapping für die Rückkonvertierung
IBKR_REVERSE_MAP = {v: k for k, v in IBKR_SYMBOL_MAP.items() if v is not None}


def to_ibkr_symbol(symbol: str) -> Optional[str]:
    """
    Konvertiert ein Standard-Symbol zu einem IBKR-kompatiblen Symbol.
    
    Args:
        symbol: Standard-Ticker-Symbol
        
    Returns:
        IBKR-Symbol oder None wenn das Symbol übersprungen werden soll
    """
    symbol = symbol.upper().strip()
    
    # Prüfe ob Mapping existiert
    if symbol in IBKR_SYMBOL_MAP:
        mapped = IBKR_SYMBOL_MAP[symbol]
        if mapped is None:
            logger.debug(f"Symbol {symbol} wird übersprungen (kein IBKR-Äquivalent)")
        return mapped
    
    return symbol


def from_ibkr_symbol(ibkr_symbol: str) -> str:
    """
    Konvertiert ein IBKR-Symbol zurück zum Standard-Symbol.
    
    Args:
        ibkr_symbol: IBKR-Ticker-Symbol
        
    Returns:
        Standard-Symbol
    """
    if ibkr_symbol in IBKR_REVERSE_MAP:
        return IBKR_REVERSE_MAP[ibkr_symbol]
    return ibkr_symbol


@dataclass
class IBKRNews:
    """News-Headline von IBKR"""
    symbol: str
    headline: str
    time: Optional[str] = None
    provider: Optional[str] = None


@dataclass 
class MaxPainData:
    """Max Pain Daten"""
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
    """Strike-Empfehlung von IBKR"""
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
    Bridge zu IBKR MCP Server für exklusive Daten.
    
    Der IBKR MCP Server läuft separat und wird über TWS/Gateway
    mit Marktdaten versorgt. Diese Bridge nutzt die dort
    verfügbaren Tools.
    
    Verwendung:
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
        self._check_interval = 60  # Sekunden
    
    async def is_available(self, force_check: bool = False) -> bool:
        """
        Prüft ob TWS/Gateway erreichbar ist.
        
        Cached das Ergebnis für 60 Sekunden.
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
                logger.debug(f"TWS erreichbar auf {self.host}:{self.port}")
            else:
                logger.debug(f"TWS nicht erreichbar auf {self.host}:{self.port}")
                
            return self._connected
            
        except Exception as e:
            logger.debug(f"TWS Check fehlgeschlagen: {e}")
            self._connected = False
            return False
    
    async def _ensure_connected(self) -> bool:
        """Stellt Verbindung zu IBKR her."""
        if self._ib is not None and self._connected:
            return True
        
        if not await self.is_available():
            return False
        
        try:
            from ib_insync import IB
            
            self._ib = IB()
            await self._ib.connectAsync(
                self.host, 
                self.port, 
                clientId=98,  # Anderer Client als Haupt-MCP-Server
                timeout=10
            )
            self._connected = True
            logger.info("IBKR Bridge verbunden")
            return True
            
        except ImportError:
            logger.warning("ib_insync nicht installiert - IBKR Bridge nicht verfügbar")
            return False
        except Exception as e:
            logger.warning(f"IBKR Bridge Verbindung fehlgeschlagen: {e}")
            self._connected = False
            return False
    
    async def disconnect(self):
        """Trennt Verbindung."""
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
        Holt News-Headlines für Symbole.
        
        Args:
            symbols: Liste von Ticker-Symbolen
            days: News der letzten X Tage
            max_per_symbol: Max Headlines pro Symbol
            
        Returns:
            Liste von IBKRNews
        """
        if not await self._ensure_connected():
            logger.warning("IBKR nicht verfügbar für News-Abruf")
            return []
        
        from ib_insync import Stock
        from datetime import timedelta
        
        results = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        for symbol in symbols:
            try:
                stock = Stock(symbol.upper(), "SMART", "USD")
                self._ib.qualifyContracts(stock)
                
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
                    for h in headlines:
                        results.append(IBKRNews(
                            symbol=symbol.upper(),
                            headline=h.headline,
                            time=h.time.isoformat() if h.time else None,
                            provider=h.providerCode
                        ))
                        
            except asyncio.TimeoutError:
                logger.warning(f"News Timeout für {symbol}")
            except Exception as e:
                logger.debug(f"News-Fehler für {symbol}: {e}")
        
        return results
    
    async def get_news_formatted(
        self, 
        symbols: List[str], 
        days: int = 5
    ) -> str:
        """
        Holt News und formatiert als Markdown.
        """
        news = await self.get_news(symbols, days)
        
        b = MarkdownBuilder()
        b.h1(f"News Headlines ({days} Tage)").blank()
        
        if not news:
            b.hint(f"Keine News für {', '.join(symbols)} gefunden (IBKR nicht verfügbar oder keine Headlines).")
            return b.build()
        
        # Gruppiere nach Symbol
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
        Holt VIX von IBKR mit Fallback für geschlossenen Markt.
        
        Returns:
            Dict mit 'value' und 'source' ("live", "mark", "close") oder None
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
            
            # Mit Generic Tick 221 für Mark Price (Pre/Post Market)
            self._ib.reqMktData(vix, "221", False, False)
            await asyncio.sleep(2)  # Etwas länger warten für alle Daten
            
            ticker = self._ib.ticker(vix)
            price = None
            source = None
            
            if ticker:
                # Preis-Fallback Kette: last -> markPrice -> marketPrice -> close
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
            logger.debug(f"IBKR VIX Fehler: {e}")
            return None
    
    async def get_vix_value(self) -> Optional[float]:
        """
        Convenience-Methode: Gibt nur den VIX-Wert zurück (für Kompatibilität).
        
        Returns:
            VIX-Wert oder None
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
        Berechnet Max Pain für Symbole.
        
        Args:
            symbols: Liste von Ticker-Symbolen  
            expiry: Verfall YYYYMMDD (optional, sonst nächster 30-60 DTE)
            
        Returns:
            Liste von MaxPainData
        """
        if not await self._ensure_connected():
            logger.warning("IBKR nicht verfügbar für Max Pain")
            return []
        
        from ib_insync import Stock, Option
        from collections import defaultdict
        import math
        
        results = []
        
        for symbol in symbols:
            try:
                stock = Stock(symbol.upper(), "SMART", "USD")
                self._ib.qualifyContracts(stock)
                
                # Aktuellen Preis holen
                self._ib.reqMktData(stock, "", False, False)
                await asyncio.sleep(0.5)
                ticker = self._ib.ticker(stock)
                current_price = ticker.marketPrice() if ticker else None
                self._ib.cancelMktData(stock)
                
                if not current_price or math.isnan(current_price):
                    continue
                
                # Options-Chain holen
                chains = await asyncio.wait_for(
                    self._ib.reqSecDefOptParamsAsync(
                        stock.symbol, "", stock.secType, stock.conId
                    ),
                    timeout=15
                )
                
                if not chains:
                    continue
                
                chain = next((c for c in chains if c.exchange == "SMART"), chains[0])
                
                # Expiry bestimmen
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
                        except:
                            continue
                
                if not target_expiry:
                    continue
                
                # Open Interest sammeln
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
                        except:
                            continue
                
                if not oi_data:
                    continue
                
                # Max Pain berechnen
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
                
                # Walls finden
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
                logger.warning(f"Max Pain Fehler für {symbol}: {e}")
        
        return results
    
    async def get_max_pain_formatted(self, symbols: List[str]) -> str:
        """Max Pain formatiert als Markdown."""
        data = await self.get_max_pain(symbols)
        
        b = MarkdownBuilder()
        b.h1("Max Pain Analyse").blank()
        
        if not data:
            b.hint("Keine Max Pain Daten verfügbar (IBKR nicht verbunden oder Fehler).")
            return b.build()
        
        # Tabelle aufbauen
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
            ["Symbol", "Preis", "Max Pain", "Distanz", "P/C Ratio", "Put Wall", "Call Wall"],
            rows
        )
        b.blank()
        
        b.text("**Interpretation:**")
        b.bullet("Max Pain = Preis mit geringstem Options-Schmerz")
        b.bullet("Distanz negativ = Preis über Max Pain (bullish)")
        b.bullet("P/C Ratio > 1 = Mehr Puts als Calls (bearish sentiment)")
        
        return b.build()
    
    # =========================================================================
    # STATUS
    # =========================================================================
    
    async def get_status(self) -> Dict[str, Any]:
        """Gibt Bridge-Status zurück."""
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
        Holt alle Positionen aus dem IBKR-Portfolio.
        
        Returns:
            Liste von Position-Dictionaries
        """
        if not await self._ensure_connected():
            logger.warning("IBKR nicht verfügbar für Portfolio-Abruf")
            return []
        
        try:
            # Portfolio-Positionen abrufen
            self._ib.reqPositions()
            await asyncio.sleep(1)  # Warte auf Daten
            
            positions = []
            for pos in self._ib.positions():
                contract = pos.contract
                
                position_data = {
                    "symbol": contract.symbol,
                    "sec_type": contract.secType,
                    "quantity": pos.position,
                    "avg_cost": pos.avgCost,
                    "account": pos.account,
                }
                
                # Zusätzliche Felder für Optionen
                if contract.secType == "OPT":
                    position_data.update({
                        "strike": contract.strike,
                        "right": contract.right,  # 'C' oder 'P'
                        "expiry": contract.lastTradeDateOrContractMonth,
                        "multiplier": int(contract.multiplier or 100),
                    })
                
                positions.append(position_data)
            
            logger.info(f"IBKR Portfolio: {len(positions)} Positionen geladen")
            return positions
            
        except Exception as e:
            logger.error(f"IBKR Portfolio-Fehler: {e}")
            return []
    
    async def get_portfolio_formatted(self) -> str:
        """
        Holt Portfolio und formatiert als Markdown.
        """
        positions = await self.get_portfolio()
        
        b = MarkdownBuilder()
        b.h1("IBKR Portfolio").blank()
        
        if not positions:
            b.hint("Keine Positionen gefunden (IBKR nicht verbunden oder leeres Portfolio).")
            return b.build()
        
        # Gruppiere nach Typ
        stocks = [p for p in positions if p["sec_type"] == "STK"]
        options = [p for p in positions if p["sec_type"] == "OPT"]
        other = [p for p in positions if p["sec_type"] not in ["STK", "OPT"]]
        
        # Aktien
        if stocks:
            b.h2(f"Aktien ({len(stocks)})").blank()
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
        
        # Optionen
        if options:
            b.h2(f"Optionen ({len(options)})").blank()
            
            # Gruppiere nach Symbol
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
                    qty_str = f"{p['quantity']:+,.0f}"  # Mit Vorzeichen
                    rows.append([
                        p["expiry"],
                        f"${p['strike']:.0f}",
                        right,
                        qty_str,
                        f"${p['avg_cost']:.2f}",
                    ])
                b.table(["Expiry", "Strike", "Type", "Qty", "Avg Cost"], rows)
                b.blank()
        
        # Andere
        if other:
            b.h2(f"Andere ({len(other)})").blank()
            for p in other:
                b.bullet(f"{p['symbol']} ({p['sec_type']}): {p['quantity']}")
            b.blank()
        
        # Zusammenfassung
        b.h2("Zusammenfassung")
        b.kv_line("Aktien-Positionen", len(stocks))
        b.kv_line("Options-Positionen", len(options))
        b.kv_line("Andere", len(other))
        
        return b.build()
    
    async def get_option_positions(self) -> List[Dict[str, Any]]:
        """
        Holt nur Options-Positionen aus IBKR.
        
        Returns:
            Liste von Options-Positionen
        """
        all_positions = await self.get_portfolio()
        return [p for p in all_positions if p["sec_type"] == "OPT"]
    
    async def get_spreads(self) -> List[Dict[str, Any]]:
        """
        Identifiziert Spread-Positionen (Bull Put Spreads, etc.)
        
        Returns:
            Liste von identifizierten Spreads
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
                # Finde passenden Long Put
                for long in long_puts:
                    if long["strike"] < short["strike"] and abs(long["quantity"]) == abs(short["quantity"]):
                        # avgCost von IBKR ist total cost pro Kontrakt (nicht pro Aktie)
                        # Net Credit = Short Premium - Long Premium (beides totals)
                        net_credit_total = short["avg_cost"] - long["avg_cost"]
                        # Pro Aktie = total / 100
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
                            "net_credit": net_credit_per_share,  # Pro Aktie
                            "net_credit_total": net_credit_total * int(abs(short["quantity"])),  # Gesamt
                        }
                        spreads.append(spread)
                        break
        
        return spreads
    
    async def get_spreads_formatted(self) -> str:
        """
        Holt Spreads und formatiert als Markdown.
        """
        spreads = await self.get_spreads()
        
        b = MarkdownBuilder()
        b.h1("IBKR Spread-Positionen").blank()
        
        if not spreads:
            b.hint("Keine Spread-Positionen erkannt.")
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
            
            # DTE berechnen
            try:
                exp_date = datetime.strptime(s["expiry"], "%Y%m%d").date()
                dte = (exp_date - datetime.now().date()).days
                dte_str = f"{dte}d"
            except:
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
        b.h2("Zusammenfassung")
        b.kv_line("Spreads", len(spreads))
        b.kv_line("Total Credit", f"${total_credit:,.0f}")
        b.kv_line("Max Profit", f"${total_max_profit:,.0f}")
        b.kv_line("Max Loss", f"${total_max_loss:,.0f}")
        
        return b.build()
    
    async def get_status_formatted(self) -> str:
        """Status formatiert als Markdown."""
        status = await self.get_status()
        
        b = MarkdownBuilder()
        b.h1("IBKR Bridge Status").blank()
        
        b.kv("Status", "✅ Verfügbar" if status["available"] else "❌ Nicht verfügbar")
        b.kv("Host", f"{status['host']}:{status['port']}")
        b.kv("Connected", "Ja" if status["connected"] else "Nein")
        
        if status["features"]:
            b.blank()
            b.text("**Verfügbare Features:**")
            for f in status["features"]:
                b.bullet(f)
        else:
            b.blank()
            b.hint("TWS/Gateway muss laufen für IBKR-Features.")
            b.hint("Starte TWS und aktiviere API (Edit > Global Config > API > Settings)")
        
        return b.build()
    
    # =========================================================================
    # BATCH QUOTES (Watchlist)
    # =========================================================================
    
    @dataclass
    class QuoteData:
        """Quote-Daten für ein Symbol."""
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
        Holt Quotes für viele Symbole in Batches.
        
        Wenn der Markt geschlossen ist, wird der Close-Preis als Fallback verwendet.
        Pre-/Post-Market Daten werden über den Mark Price (Generic Tick 221) geholt.
        
        Args:
            symbols: Liste von Ticker-Symbolen
            batch_size: Symbole pro Batch (default: 50)
            pause_seconds: Pause zwischen Batches in Sekunden (default: 60)
            callback: Optional callback(batch_num, total_batches, results) nach jedem Batch
            include_outside_rth: Pre-/Post-Market Daten einbeziehen (default: True)
            
        Returns:
            Liste von Quote-Dictionaries
        """
        if not await self._ensure_connected():
            logger.warning("IBKR nicht verfügbar für Quotes")
            return []
        
        from ib_insync import Stock
        import math
        
        # Symbol-Mapping anwenden und ungültige Symbole filtern
        mapped_symbols = []
        skipped_symbols = []
        symbol_display_map = {}  # IBKR-Symbol -> Original-Symbol für Anzeige
        
        for sym in symbols:
            ibkr_sym = to_ibkr_symbol(sym)
            if ibkr_sym is None:
                skipped_symbols.append(sym.upper())
            else:
                mapped_symbols.append(ibkr_sym)
                symbol_display_map[ibkr_sym] = sym.upper()
        
        if skipped_symbols:
            logger.info(f"Überspringe {len(skipped_symbols)} Symbole ohne IBKR-Äquivalent: {', '.join(skipped_symbols[:5])}...")
        
        all_results = []
        
        # Übersprungene Symbole als Fehler hinzufügen
        for sym in skipped_symbols:
            all_results.append({
                "symbol": sym,
                "error": "Kein IBKR-Äquivalent (übersprungen)"
            })
        
        total_batches = (len(mapped_symbols) + batch_size - 1) // batch_size if mapped_symbols else 0
        
        # Generic Tick Types für erweiterte Daten:
        # 221 = Mark Price (Pre/Post Market)
        # 233 = RT Volume (für Real-time Trades außerhalb RTH)
        generic_ticks = "221,233" if include_outside_rth else ""
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(mapped_symbols))
            batch_symbols = mapped_symbols[start_idx:end_idx]
            
            logger.info(f"Batch {batch_num + 1}/{total_batches}: {len(batch_symbols)} Symbole ({start_idx+1}-{end_idx})")
            
            batch_results = []
            contracts = []
            
            # Contracts erstellen und qualifizieren
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
            
            # Qualifizieren
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
            
            # Market Data anfordern (mit Generic Ticks für Pre/Post Market)
            for original_symbol, ibkr_symbol, contract in valid_contracts:
                try:
                    self._ib.reqMktData(contract, generic_ticks, False, False)
                except Exception as e:
                    logger.debug(f"reqMktData failed for {ibkr_symbol}: {e}")
            
            # Warten auf Daten (etwas länger für Pre/Post Market Daten)
            await asyncio.sleep(3 if include_outside_rth else 2)
            
            # Daten sammeln
            for original_symbol, ibkr_symbol, contract in valid_contracts:
                try:
                    ticker = self._ib.ticker(contract)
                    
                    if ticker:
                        # Hilfsfunktion: Wert extrahieren wenn gültig (nicht NaN, nicht -1, > 0)
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
                        
                        # Preis-Fallback Kette: last -> markPrice -> marketPrice -> close
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
                        
                        # Change berechnen (gegen Close)
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
                            "price_source": price_source,  # Info wo der Preis herkommt
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
            
            # Market Data canceln
            for original_symbol, ibkr_symbol, contract in valid_contracts:
                try:
                    self._ib.cancelMktData(contract)
                except:
                    pass
            
            all_results.extend(batch_results)
            
            # Callback
            if callback:
                callback(batch_num + 1, total_batches, batch_results)
            
            # Pause zwischen Batches (außer beim letzten)
            if batch_num < total_batches - 1:
                logger.info(f"Pause {pause_seconds}s vor nächstem Batch...")
                await asyncio.sleep(pause_seconds)
        
        logger.info(f"Fertig: {len(all_results)} Quotes geholt")
        return all_results
    
    async def get_quotes_batch_formatted(
        self,
        symbols: List[str],
        batch_size: int = 50,
        pause_seconds: int = 60
    ) -> str:
        """
        Holt Quotes in Batches und formatiert als Markdown.
        
        Zeigt Preisquelle an:
        - ● = Live/Pre-Post-Market Preis
        - ○ = Schlusskurs (Markt geschlossen)
        """
        results = await self.get_quotes_batch(symbols, batch_size, pause_seconds)
        
        b = MarkdownBuilder()
        b.h1(f"IBKR Watchlist Quotes ({len(results)} Symbole)").blank()
        
        if not results:
            b.hint("Keine Quotes erhalten.")
            return b.build()
        
        # Sortiere nach Change %
        valid_quotes = [r for r in results if r.get("last") and not r.get("error")]
        error_quotes = [r for r in results if r.get("error")]
        
        # Preisquellen-Statistik
        source_counts = {"last": 0, "mark": 0, "market": 0, "close": 0}
        for q in valid_quotes:
            src = q.get("price_source", "last")
            if src in source_counts:
                source_counts[src] += 1
        
        # Markt-Status Hinweis
        close_pct = (source_counts["close"] / len(valid_quotes) * 100) if valid_quotes else 0
        mark_count = source_counts["mark"]
        
        if close_pct > 50:
            b.hint(f"⏸️ Markt geschlossen - {source_counts['close']} von {len(valid_quotes)} Preise sind Schlusskurse")
            b.blank()
        elif mark_count > 0:
            b.hint(f"🌙 Pre/Post-Market aktiv - {mark_count} Symbole mit außerbörslichen Preisen")
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
        
        # Hilfsfunktion für Preisquelle-Indikator
        def price_indicator(q):
            src = q.get("price_source", "last")
            if src == "close":
                return "○"  # Schlusskurs
            elif src == "mark":
                return "●"  # Pre/Post Market
            else:
                return ""   # Live - kein Indikator nötig
        
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
        
        # Alle Quotes
        b.h2("Alle Quotes").blank()
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
            b.h2(f"⚠️ Fehler ({len(error_quotes)})")
            for q in error_quotes[:10]:
                b.bullet(f"{q['symbol']}: {q['error']}")
            if len(error_quotes) > 10:
                b.hint(f"... und {len(error_quotes) - 10} weitere")
        
        # Zusammenfassung
        b.blank()
        b.h2("Zusammenfassung")
        b.kv_line("Erfolgreiche Quotes", len(valid_quotes))
        b.kv_line("Fehler", len(error_quotes))
        b.kv_line("Gesamt", len(results))
        
        # Preisquellen-Details
        if source_counts["close"] > 0 or source_counts["mark"] > 0:
            b.blank()
            b.text("**Preisquellen:**")
            if source_counts["last"] > 0:
                b.bullet(f"Live: {source_counts['last']}")
            if source_counts["mark"] > 0:
                b.bullet(f"Pre/Post-Market ●: {source_counts['mark']}")
            if source_counts["close"] > 0:
                b.bullet(f"Schlusskurs ○: {source_counts['close']}")
        
        return b.build()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_bridge: Optional[IBKRBridge] = None


def get_ibkr_bridge() -> IBKRBridge:
    """Gibt globale Bridge-Instanz zurück."""
    global _default_bridge
    if _default_bridge is None:
        _default_bridge = IBKRBridge()
    return _default_bridge


async def check_ibkr_available() -> bool:
    """Schnell-Check ob IBKR verfügbar ist."""
    bridge = get_ibkr_bridge()
    return await bridge.is_available()
