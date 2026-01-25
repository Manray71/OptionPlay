# OptionPlay - Output Formatters
# ================================
"""
Spezialisierte Formatter für verschiedene Output-Typen.

Extrahiert die Markdown-Generierung aus dem MCP-Server
in wiederverwendbare, testbare Klassen.

Verwendung:
    from src.formatters import ScanResultFormatter, QuoteFormatter
    
    formatter = ScanResultFormatter()
    output = formatter.format(scan_result, strategy_recommendation, vix)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Protocol

# Import from utils package (not relative)
from src.utils.markdown_builder import (
    MarkdownBuilder, 
    format_price, 
    format_percent, 
    format_volume,
    truncate
)


# =============================================================================
# PROTOCOLS (für Type Hints ohne zirkuläre Imports)
# =============================================================================

class ScanResultProtocol(Protocol):
    """Protocol für ScanResult-ähnliche Objekte."""
    symbols_scanned: int
    symbols_with_signals: int
    scan_duration_seconds: float
    signals: List[Any]


class SignalProtocol(Protocol):
    """Protocol für Signal-ähnliche Objekte."""
    symbol: str
    score: float
    current_price: float
    reason: str
    strategy: str
    details: Optional[Dict[str, Any]]


class StrategyRecommendationProtocol(Protocol):
    """Protocol für StrategyRecommendation."""
    profile_name: str
    delta_target: float
    spread_width: float
    min_score: int
    earnings_buffer_days: int
    reasoning: str
    warnings: List[str]
    regime: Any


class QuoteProtocol(Protocol):
    """Protocol für Quote-ähnliche Objekte."""
    last: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    volume: Optional[int]


class OptionProtocol(Protocol):
    """Protocol für Option-ähnliche Objekte."""
    strike: float
    bid: Optional[float]
    ask: Optional[float]
    implied_volatility: Optional[float]
    delta: Optional[float]
    open_interest: Optional[int]
    expiry: date


class EarningsProtocol(Protocol):
    """Protocol für Earnings-Info."""
    earnings_date: Optional[str]
    days_to_earnings: Optional[int]


# =============================================================================
# BASE FORMATTER
# =============================================================================

class BaseFormatter(ABC):
    """Basis-Klasse für alle Formatter."""
    
    @abstractmethod
    def format(self, *args, **kwargs) -> str:
        """Formatiert das Objekt als Markdown."""
        pass
    
    def _builder(self) -> MarkdownBuilder:
        """Erstellt neuen MarkdownBuilder."""
        return MarkdownBuilder()


# =============================================================================
# SCAN RESULT FORMATTER
# =============================================================================

class ScanResultFormatter(BaseFormatter):
    """
    Formatiert Scan-Ergebnisse als Markdown.
    
    Verwendet von:
    - scan_with_strategy()
    - scan_pullback_candidates()
    """
    
    def format(
        self,
        result: ScanResultProtocol,
        recommendation: Optional[StrategyRecommendationProtocol] = None,
        vix: Optional[float] = None,
        max_results: int = 10,
        show_details: int = 3,
        title: str = "Pullback Candidates Scan"
    ) -> str:
        """
        Formatiert Scan-Ergebnis.
        
        Args:
            result: Scan-Ergebnis
            recommendation: VIX-basierte Strategie-Empfehlung
            vix: Aktueller VIX-Wert
            max_results: Max. Anzahl Ergebnisse in Tabelle
            show_details: Anzahl detaillierter Einträge
            title: Überschrift
        """
        b = self._builder()
        
        # Header
        b.h1(title).blank()
        
        # Strategy info (wenn VIX-basiert)
        if recommendation and vix is not None:
            b.kv("VIX", vix, fmt=".2f")
            b.kv("Strategy", recommendation.profile_name.upper())
            b.kv_inline(
                ("Min Score", recommendation.min_score),
                ("Delta Target", recommendation.delta_target)
            )
            b.blank()
        
        # Scan stats
        b.kv("Scanned", f"{result.symbols_scanned} symbols")
        b.kv("With Signals", result.symbols_with_signals)
        b.kv("Duration", f"{result.scan_duration_seconds:.1f}s")
        b.blank()
        
        if result.signals:
            # Results table
            b.h2("Top Candidates").blank()
            
            rows = []
            for signal in result.signals[:max_results]:
                rows.append([
                    signal.symbol,
                    f"{signal.score:.1f}",
                    format_price(signal.current_price),
                    truncate(signal.reason, 35)
                ])
            
            b.table(["Symbol", "Score", "Price", "Reason"], rows)
            
            # Details for top N
            if show_details > 0:
                b.blank().h2(f"Top {show_details} Details")
                
                for signal in result.signals[:show_details]:
                    b.blank().h3(signal.symbol)
                    b.kv_line("Score", f"{signal.score:.1f}/10")
                    b.kv_line("Price", signal.current_price, fmt="$.2f")
                    
                    if signal.details:
                        if 'rsi' in signal.details:
                            b.kv_line("RSI", signal.details['rsi'], fmt=".1f")
                        if 'pullback_pct' in signal.details:
                            b.kv_line("Pullback", signal.details['pullback_pct'], fmt=".1f%")
                    
                    b.kv_line("Reason", signal.reason)
            
            # Next steps
            if recommendation:
                b.blank().h2("Next Steps")
                b.numbered("Check earnings: `get_earnings <SYMBOL>`")
                b.numbered(f"Options chain: `get_options_chain <SYMBOL>` (DTE 45-60, Delta {recommendation.delta_target})")
                b.numbered(f"Spread width: ${recommendation.spread_width:.2f}")
        else:
            min_score = recommendation.min_score if recommendation else 5
            b.hint(f"No pullback candidates with score >= {min_score} found.")
            if recommendation and recommendation.min_score >= 6:
                b.hint("Tip: With lower VIX, score requirements are increased.")
        
        return b.build()


class LegacyScanResultFormatter(BaseFormatter):
    """Formatter für Legacy-Scan (ohne VIX)."""
    
    def format(
        self,
        result: ScanResultProtocol,
        min_score: float = 5.0,
        max_results: int = 10
    ) -> str:
        b = self._builder()
        
        b.h1("Pullback Candidates Scan").blank()
        b.kv("Scanned", f"{result.symbols_scanned} symbols")
        b.kv("With Signals", result.symbols_with_signals)
        b.kv("Duration", f"{result.scan_duration_seconds:.1f}s")
        b.blank()
        
        if result.signals:
            b.h2("Top Candidates").blank()
            
            rows = []
            for signal in result.signals[:max_results]:
                rows.append([
                    signal.symbol,
                    f"{signal.score:.1f}",
                    signal.strategy,
                    truncate(signal.reason, 40)
                ])
            
            b.table(["Symbol", "Score", "Strategy", "Reason"], rows)
        else:
            b.hint(f"No pullback candidates with score >= {min_score} found.")
        
        return b.build()


# =============================================================================
# QUOTE FORMATTER
# =============================================================================

class QuoteFormatter(BaseFormatter):
    """Formatiert Stock-Quotes."""
    
    def format(
        self,
        symbol: str,
        quote: Optional[QuoteProtocol]
    ) -> str:
        b = self._builder()
        
        b.h1(f"Quote: {symbol.upper()}").blank()
        
        if not quote:
            b.hint("No quote data available.")
            return b.build()
        
        b.kv_line("Last", quote.last, fmt="$.2f")
        b.kv_line("Bid", quote.bid, fmt="$.2f")
        b.kv_line("Ask", quote.ask, fmt="$.2f")
        b.kv_line("Volume", format_volume(quote.volume) if quote.volume else None)
        
        return b.build()


# =============================================================================
# OPTIONS CHAIN FORMATTER
# =============================================================================

class OptionsChainFormatter(BaseFormatter):
    """Formatiert Options-Chains."""
    
    def format(
        self,
        symbol: str,
        options: List[OptionProtocol],
        underlying_price: Optional[float] = None,
        right: str = "P",
        dte_min: int = 30,
        dte_max: int = 60,
        max_options: int = 15
    ) -> str:
        b = self._builder()
        
        option_type = "Put" if right.upper() == "P" else "Call"
        b.h1(f"Options Chain: {symbol.upper()} ({option_type}s)")
        
        if underlying_price:
            b.kv("Underlying", underlying_price, fmt="$.2f")
        b.kv("DTE Range", f"{dte_min}-{dte_max} days")
        b.kv("Found", f"{len(options)} options")
        b.blank()
        
        if not options:
            b.hint(f"No options found for DTE range {dte_min}-{dte_max}.")
            return b.build()
        
        # Group by expiry
        by_expiry: Dict[date, List[OptionProtocol]] = {}
        for opt in options:
            if opt.expiry not in by_expiry:
                by_expiry[opt.expiry] = []
            by_expiry[opt.expiry].append(opt)
        
        options_shown = 0
        for expiry in sorted(by_expiry.keys()):
            if options_shown >= max_options:
                break
            
            dte = (expiry - date.today()).days
            b.h2(f"Expiry: {expiry} ({dte} DTE)").blank()
            
            # Table header
            rows = []
            sorted_opts = sorted(by_expiry[expiry], key=lambda x: x.strike)
            
            # Filter around ATM
            if underlying_price:
                atm_idx = min(
                    range(len(sorted_opts)),
                    key=lambda i: abs(sorted_opts[i].strike - underlying_price)
                )
                start_idx = max(0, atm_idx - 5)
                end_idx = min(len(sorted_opts), atm_idx + 6)
                sorted_opts = sorted_opts[start_idx:end_idx]
            
            for opt in sorted_opts:
                if options_shown >= max_options:
                    break
                
                atm_marker = " ◄" if underlying_price and abs(opt.strike - underlying_price) < 2.5 else ""
                
                rows.append([
                    f"${opt.strike:.0f}{atm_marker}",
                    format_price(opt.bid) if opt.bid else "-",
                    format_price(opt.ask) if opt.ask else "-",
                    f"{opt.implied_volatility*100:.1f}%" if opt.implied_volatility else "-",
                    f"{opt.delta:.2f}" if opt.delta else "-",
                    str(opt.open_interest) if opt.open_interest else "-"
                ])
                options_shown += 1
            
            b.table(["Strike", "Bid", "Ask", "IV", "Delta", "OI"], rows)
            b.blank()
        
        return b.build()


# =============================================================================
# EARNINGS FORMATTER
# =============================================================================

class EarningsFormatter(BaseFormatter):
    """Formatiert Earnings-Info."""
    
    def format(
        self,
        symbol: str,
        earnings_date: Optional[str],
        days_to_earnings: Optional[int],
        min_days: int = 60,
        source: str = "unknown"
    ) -> str:
        b = self._builder()
        
        b.h1(f"Earnings: {symbol}").blank()
        
        if earnings_date:
            is_safe = days_to_earnings >= min_days if days_to_earnings is not None else True
            
            b.kv("Next Earnings", earnings_date)
            b.kv("Days to Earnings", days_to_earnings)
            b.kv(f"Status for {min_days}d trade", "✅ SAFE" if is_safe else "⚠️ TOO CLOSE")
            b.kv("Source", source)
            b.blank()
            
            if not is_safe:
                b.warning_box(
                    f"Earnings in {days_to_earnings} days. "
                    f"Minimum {min_days} days buffer recommended."
                )
        else:
            b.kv("Earnings Date", "Not available")
            b.blank()
            b.note("No earnings date found (Marketdata + Yahoo).")
            b.hint(f"Check manually: https://finance.yahoo.com/quote/{symbol}/analysis")
        
        return b.build()


# =============================================================================
# STRATEGY RECOMMENDATION FORMATTER
# =============================================================================

class StrategyRecommendationFormatter(BaseFormatter):
    """Formatiert VIX-basierte Strategie-Empfehlungen."""
    
    def format(
        self,
        recommendation: StrategyRecommendationProtocol,
        vix: Optional[float]
    ) -> str:
        b = self._builder()
        
        b.h1("Strategy Recommendation").blank()
        
        if vix is not None:
            b.kv("VIX", vix, fmt=".2f")
        else:
            b.kv("VIX", "Not available")
        
        b.kv("Regime", recommendation.regime.value)
        b.kv("Profile", recommendation.profile_name.upper())
        b.blank()
        
        b.h2("Recommended Parameters")
        b.kv_line("Delta Target", recommendation.delta_target)
        b.kv_line("Spread Width", recommendation.spread_width, fmt="$.2f")
        b.kv_line("Min Score", recommendation.min_score)
        b.kv_line("Earnings Buffer", f">{recommendation.earnings_buffer_days} days")
        b.blank()
        
        b.h2("Reasoning")
        b.text(recommendation.reasoning)
        
        if recommendation.warnings:
            b.blank().h2("⚠️ Warnings")
            b.bullets(recommendation.warnings)
        
        return b.build()


# =============================================================================
# HEALTH CHECK FORMATTER
# =============================================================================

@dataclass
class HealthCheckData:
    """Container für Health-Check-Daten."""
    version: str
    api_key_masked: str
    connected: bool
    current_vix: Optional[float]
    vix_updated: Optional[datetime]
    watchlist_symbols: int
    watchlist_sectors: int
    cache_stats: Dict[str, Any]
    circuit_breaker_stats: Dict[str, Any]
    rate_limiter_stats: Dict[str, Any]
    scanner_config: Any
    ibkr_available: bool = False
    ibkr_host: Optional[str] = None
    ibkr_port: Optional[int] = None


class HealthCheckFormatter(BaseFormatter):
    """Formatiert Health-Check-Output."""
    
    def format(self, data: HealthCheckData) -> str:
        b = self._builder()
        
        b.h1("OptionPlay Server Health").blank()
        
        b.kv("Version", data.version)
        b.kv("API Key", data.api_key_masked)
        b.kv("Marketdata.app", "✅ Connected" if data.connected else "❌ Not connected")
        b.blank()
        
        # VIX
        b.h2("VIX")
        if data.current_vix:
            b.kv_line("Current", data.current_vix, fmt=".2f")
        else:
            b.kv_line("Current", "N/A")
        if data.vix_updated:
            b.kv_line("Updated", data.vix_updated.strftime('%H:%M:%S'))
        else:
            b.kv_line("Updated", "N/A")
        b.blank()
        
        # Watchlist
        b.h2("Watchlist (from YAML)")
        b.kv_line("Symbols", data.watchlist_symbols)
        b.kv_line("Sectors", data.watchlist_sectors)
        b.blank()
        
        # Cache
        cs = data.cache_stats
        b.h2("Historical Data Cache")
        b.kv_line("Entries", f"{cs['entries']}/{cs['max_entries']}")
        b.kv_line("Hit Rate", f"{cs['hit_rate_percent']}%")
        b.kv_line("Hits/Misses", f"{cs['hits']}/{cs['misses']}")
        b.kv_line("TTL", f"{cs['ttl_seconds']}s")
        b.blank()
        
        # Circuit Breaker
        cb = data.circuit_breaker_stats
        state_icon = "✅ Closed" if cb['state'] == 'closed' else "❌ OPEN" if cb['state'] == 'open' else "⚠️ Half-Open"
        b.h2("Circuit Breaker")
        b.kv_line("Status", state_icon)
        b.kv_line("Failures", f"{cb['failure_count']}/{cb['failure_threshold']}")
        b.kv_line("Total Calls", f"{cb['total_calls']} (Rejected: {cb['rejected_calls']})")
        b.kv_line("Recovery Timeout", f"{cb['recovery_timeout']}s")
        b.blank()
        
        # Scanner Config
        sc = data.scanner_config
        b.h2("Scanner Config (from YAML)")
        b.kv_line("Min Score", sc.min_score)
        b.kv_line("Earnings Buffer", f"{sc.exclude_earnings_within_days} days")
        b.kv_line("IV Filter", "✅ Active" if sc.enable_iv_filter else "❌ Disabled")
        b.kv_line("IV Rank Range", f"{sc.iv_rank_minimum:.0f}% - {sc.iv_rank_maximum:.0f}%")
        b.kv_line("Max Concurrent", sc.max_concurrent)
        b.blank()
        
        # Rate Limiter
        rl = data.rate_limiter_stats
        b.h2("Rate Limiter (Marketdata.app)")
        b.kv_line("Requests", rl['total_requests'])
        b.kv_line("Waits", rl['total_waits'])
        b.kv_line("Avg Wait", f"{rl['avg_wait_time']:.3f}s")
        b.kv_line("Available Tokens", rl['available_tokens'])
        
        # IBKR Bridge
        b.blank().h2("IBKR Bridge")
        if data.ibkr_available:
            b.kv_line("Status", "✅ Available")
            if data.ibkr_host:
                b.kv_line("Host", f"{data.ibkr_host}:{data.ibkr_port}")
            b.kv_line("Features", "News, Max Pain, Live VIX")
        else:
            b.kv_line("Status", "❌ Not available (ib_insync not installed)")
        
        return b.build()


# =============================================================================
# HISTORICAL DATA FORMATTER
# =============================================================================

class HistoricalDataFormatter(BaseFormatter):
    """Formatiert historische Preisdaten."""
    
    def format(
        self,
        symbol: str,
        bars: List[Any],  # List of HistoricalBar
        days_shown: int = 10
    ) -> str:
        b = self._builder()
        
        b.h1(f"Historical Data: {symbol.upper()}")
        
        if not bars:
            b.blank().hint("No historical data available.")
            return b.build()
        
        b.kv("Period", f"{bars[0].date} to {bars[-1].date} ({len(bars)} days)")
        b.blank()
        
        # Summary
        perf = ((bars[-1].close / bars[0].close) - 1) * 100
        high = max(b_.high for b_ in bars)
        low = min(b_.low for b_ in bars)
        avg_vol = sum(b_.volume for b_ in bars) / len(bars)
        
        b.h2("Summary")
        b.kv_line("Last Close", bars[-1].close, fmt="$.2f")
        b.kv_line("Performance", perf, fmt="+.1f%")
        b.kv_line("High", high, fmt="$.2f")
        b.kv_line("Low", low, fmt="$.2f")
        b.kv_line("Avg Volume", format_volume(int(avg_vol)))
        b.blank()
        
        # Last N days table
        b.h2(f"Last {days_shown} Days").blank()
        
        rows = []
        for bar in bars[-days_shown:]:
            rows.append([
                str(bar.date),
                format_price(bar.open),
                format_price(bar.high),
                format_price(bar.low),
                format_price(bar.close),
                format_volume(bar.volume)
            ])
        
        b.table(["Date", "Open", "High", "Low", "Close", "Volume"], rows)
        
        return b.build()


# =============================================================================
# SYMBOL ANALYSIS FORMATTER
# =============================================================================

class SymbolAnalysisFormatter(BaseFormatter):
    """Formatiert vollständige Symbol-Analysen."""
    
    def format(
        self,
        symbol: str,
        vix: Optional[float],
        recommendation: StrategyRecommendationProtocol,
        quote: Optional[QuoteProtocol],
        historical: Optional[tuple],  # (prices, volumes, highs, lows)
        earnings: Optional[EarningsProtocol],
        pullback_signal: Optional[SignalProtocol] = None
    ) -> str:
        b = self._builder()
        
        b.h1(f"Complete Analysis: {symbol}").blank()
        
        if vix:
            b.kv("VIX", vix, fmt=".2f")
        else:
            b.kv("VIX", "N/A")
        b.kv("Strategy", recommendation.profile_name.upper())
        b.blank()
        
        # Quote
        if quote:
            b.h2("Current Price")
            if quote.last:
                b.kv_line("Last", quote.last, fmt="$.2f")
            else:
                b.kv_line("Last", "N/A")
            if quote.bid:
                b.kv_line("Bid/Ask", f"${quote.bid:.2f} / ${quote.ask:.2f}")
            b.blank()
        
        # Technical analysis
        current_price = 0
        sma_200 = 0
        if historical:
            prices, volumes, highs, lows = historical
            current_price = prices[-1]
            
            sma_20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else current_price
            sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else current_price
            sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else current_price
            
            perf_1m = ((current_price / prices[-22]) - 1) * 100 if len(prices) > 22 else 0
            perf_3m = ((current_price / prices[-66]) - 1) * 100 if len(prices) > 66 else 0
            
            b.h2("Technical Indicators")
            b.kv_line("SMA 20", f"${sma_20:.2f} ({'↑' if current_price > sma_20 else '↓'})")
            b.kv_line("SMA 50", f"${sma_50:.2f} ({'↑' if current_price > sma_50 else '↓'})")
            b.kv_line("SMA 200", f"${sma_200:.2f} ({'↑' if current_price > sma_200 else '↓'})")
            b.blank()
            
            b.h2("Performance")
            b.kv_line("1 Month", perf_1m, fmt="+.1f%")
            b.kv_line("3 Months", perf_3m, fmt="+.1f%")
            b.blank()
            
            # Trend assessment
            b.h2("Trend Assessment")
            if current_price > sma_200 and current_price < sma_20:
                b.status_ok("**PULLBACK IN UPTREND** - Ideal for Bull-Put-Spread")
            elif current_price > sma_200:
                b.text("📈 Uptrend - Wait for pullback")
            elif current_price < sma_200:
                b.status_warning("Below SMA 200 - Caution")
            else:
                b.text("➡️ Sideways")
            b.blank()
            
            # Pullback score
            if pullback_signal:
                b.h2("Pullback Score")
                b.kv_line("Score", f"{pullback_signal.score:.1f}/10 (Min: {recommendation.min_score})")
                qualified = pullback_signal.score >= recommendation.min_score
                b.kv_line("Status", "✅ Qualified" if qualified else "⚠️ Below threshold")
                b.kv_line("Reason", pullback_signal.reason)
                b.blank()
        
        # Earnings
        b.h2("Earnings Check")
        if earnings and earnings.earnings_date:
            is_safe = earnings.days_to_earnings >= recommendation.earnings_buffer_days
            b.kv_line("Date", earnings.earnings_date)
            b.kv_line("Days", f"{earnings.days_to_earnings} (Min: {recommendation.earnings_buffer_days})")
            b.kv_line("Status", "✅ SAFE" if is_safe else "⚠️ TOO CLOSE")
        else:
            b.kv_line("Status", "No date available")
        b.blank()
        
        # Recommendation
        b.h2("Recommendation")
        
        warnings = []
        if earnings and earnings.days_to_earnings and earnings.days_to_earnings < recommendation.earnings_buffer_days:
            warnings.append(f"Earnings in {earnings.days_to_earnings} days (Min: {recommendation.earnings_buffer_days})")
        
        if historical:
            if current_price < sma_200:
                warnings.append("Below SMA 200")
        
        if not warnings:
            b.status_ok("**Suitable for Bull-Put-Spread analysis**")
            b.blank()
            b.hint("Recommended parameters:")
            b.kv_line("Delta", recommendation.delta_target)
            b.kv_line("Spread Width", recommendation.spread_width, fmt="$.2f")
            b.kv_line("DTE", "45-60 days")
        else:
            b.status_warning("**Caution:**")
            b.bullets(warnings)
        
        return b.build()


# =============================================================================
# FACTORY / REGISTRY
# =============================================================================

class FormatterRegistry:
    """
    Registry für alle Formatter.
    
    Verwendung:
        formatters = FormatterRegistry()
        output = formatters.scan_result.format(result, recommendation, vix)
    """
    
    def __init__(self):
        self.scan_result = ScanResultFormatter()
        self.legacy_scan = LegacyScanResultFormatter()
        self.quote = QuoteFormatter()
        self.options_chain = OptionsChainFormatter()
        self.earnings = EarningsFormatter()
        self.strategy = StrategyRecommendationFormatter()
        self.health_check = HealthCheckFormatter()
        self.historical = HistoricalDataFormatter()
        self.symbol_analysis = SymbolAnalysisFormatter()


# Globale Instanz
formatters = FormatterRegistry()
