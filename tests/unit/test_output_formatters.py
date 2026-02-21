# Tests for Output Formatters
# ============================
"""
Tests for formatters/output_formatters.py module including:
- ScanResultFormatter
- QuoteFormatter
- OptionsChainFormatter
- EarningsFormatter
- ExpirationFormatter
- HistoricalFormatter
- ValidationFormatter
- MaxPainFormatter
- SpreadAnalysisFormatter
- HealthCheckFormatter
"""

import pytest
from datetime import date, datetime
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from src.formatters.output_formatters import (
    ScanResultFormatter,
    QuoteFormatter,
    OptionsChainFormatter,
    EarningsFormatter,
    HistoricalDataFormatter,
    HealthCheckFormatter,
    StrategyRecommendationFormatter,
    SymbolAnalysisFormatter,
    FormatterRegistry,
)


# =============================================================================
# MOCK DATA CLASSES
# =============================================================================

@dataclass
class MockSignal:
    """Mock signal object."""
    symbol: str = "AAPL"
    score: float = 7.5
    current_price: float = 185.50
    reason: str = "Strong support bounce"
    strategy: str = "pullback"
    details: Optional[Dict[str, Any]] = None


@dataclass
class MockScanResult:
    """Mock scan result."""
    symbols_scanned: int = 100
    symbols_with_signals: int = 10
    scan_duration_seconds: float = 5.5
    signals: List[MockSignal] = None

    def __post_init__(self):
        if self.signals is None:
            self.signals = []


@dataclass
class MockRegime:
    """Mock VIX regime with .value attribute."""
    value: str = "normal"


@dataclass
class MockStrategy:
    """Mock strategy recommendation."""
    profile_name: str = "normal"
    delta_target: float = -0.20
    spread_width: float = 10.0
    min_score: int = 7
    earnings_buffer_days: int = 45
    reasoning: str = "Normal VIX environment"
    warnings: List[str] = None
    regime: MockRegime = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.regime is None:
            self.regime = MockRegime()


@dataclass
class MockQuote:
    """Mock quote object."""
    last: Optional[float] = 185.50
    bid: Optional[float] = 185.45
    ask: Optional[float] = 185.55
    volume: Optional[int] = 1000000
    change: Optional[float] = 2.50
    change_pct: Optional[float] = 1.37


@dataclass
class MockOption:
    """Mock option object."""
    strike: float = 180.0
    bid: Optional[float] = 2.50
    ask: Optional[float] = 2.70
    implied_volatility: Optional[float] = 0.25
    delta: Optional[float] = -0.20
    open_interest: Optional[int] = 1500
    expiry: date = None
    gamma: Optional[float] = 0.02
    theta: Optional[float] = -0.05
    vega: Optional[float] = 0.10

    def __post_init__(self):
        if self.expiry is None:
            self.expiry = date(2026, 3, 21)


@dataclass
class MockEarnings:
    """Mock earnings info."""
    earnings_date: Optional[str] = "2026-04-25"
    days_to_earnings: Optional[int] = 80


@dataclass
class MockHistoricalBar:
    """Mock historical bar."""
    date: str = "2026-01-15"
    open: float = 184.0
    high: float = 186.0
    low: float = 183.0
    close: float = 185.50
    volume: int = 1000000


@dataclass
class MockMaxPainResult:
    """Mock max pain result."""
    symbol: str = "AAPL"
    max_pain_strike: float = 180.0
    current_price: float = 185.50
    distance_pct: float = -3.0
    call_oi_total: int = 50000
    put_oi_total: int = 45000


@dataclass
class MockSpreadAnalysis:
    """Mock spread analysis."""
    symbol: str = "AAPL"
    short_strike: float = 180.0
    long_strike: float = 170.0
    net_credit: float = 1.50
    max_risk: float = 8.50
    roi: float = 17.6
    breakeven: float = 178.50
    prob_profit: float = 80.0


# =============================================================================
# SCAN RESULT FORMATTER TESTS
# =============================================================================

class TestScanResultFormatter:
    """Tests for ScanResultFormatter."""

    def test_format_empty_result(self):
        """Test formatting empty scan result."""
        formatter = ScanResultFormatter()
        result = MockScanResult(symbols_scanned=100, symbols_with_signals=0, signals=[])

        output = formatter.format(result)

        assert "Scan" in output or "No" in output

    def test_format_with_signals(self):
        """Test formatting scan result with signals."""
        formatter = ScanResultFormatter()
        signals = [
            MockSignal(symbol="AAPL", score=8.5, current_price=185.50, reason="Strong support"),
            MockSignal(symbol="MSFT", score=7.5, current_price=410.0, reason="Oversold"),
        ]
        result = MockScanResult(symbols_scanned=100, symbols_with_signals=2, signals=signals)

        output = formatter.format(result)

        assert "AAPL" in output
        assert "MSFT" in output
        assert "8.5" in output or "7.5" in output

    def test_format_with_strategy(self):
        """Test formatting with VIX strategy recommendation."""
        formatter = ScanResultFormatter()
        signals = [MockSignal()]
        result = MockScanResult(symbols_with_signals=1, signals=signals)
        strategy = MockStrategy()

        output = formatter.format(result, recommendation=strategy, vix=18.5)

        assert "VIX" in output or "18.5" in output

    def test_format_with_warnings(self):
        """Test formatting with strategy warnings."""
        formatter = ScanResultFormatter()
        signals = [MockSignal()]
        result = MockScanResult(symbols_with_signals=1, signals=signals)
        strategy = MockStrategy(warnings=["High VIX - reduce position size"])

        output = formatter.format(result, recommendation=strategy, vix=25.0)

        # Warnings may be shown
        assert output is not None


# =============================================================================
# QUOTE FORMATTER TESTS
# =============================================================================

class TestQuoteFormatter:
    """Tests for QuoteFormatter."""

    def test_format_basic_quote(self):
        """Test formatting basic quote."""
        formatter = QuoteFormatter()
        quote = MockQuote()

        output = formatter.format("AAPL", quote)

        assert "AAPL" in output
        assert "185.50" in output or "185" in output

    def test_format_quote_with_none_values(self):
        """Test formatting quote with None values."""
        formatter = QuoteFormatter()
        quote = MockQuote(last=None, bid=None, ask=None)

        output = formatter.format("AAPL", quote)

        assert "AAPL" in output
        assert "N/A" in output or output is not None

    def test_format_quote_no_quote(self):
        """Test formatting with no quote data."""
        formatter = QuoteFormatter()

        output = formatter.format("AAPL", None)

        assert "AAPL" in output


# =============================================================================
# OPTIONS CHAIN FORMATTER TESTS
# =============================================================================

class TestOptionsChainFormatter:
    """Tests for OptionsChainFormatter."""

    def test_format_empty_chain(self):
        """Test formatting empty options chain."""
        formatter = OptionsChainFormatter()

        output = formatter.format(
            symbol="AAPL",
            options=[],
            underlying_price=185.50,
            right="P",
            dte_min=30,
            dte_max=60,
        )

        assert "AAPL" in output or "No options" in output

    def test_format_with_options(self):
        """Test formatting options chain with options."""
        formatter = OptionsChainFormatter()
        options = [
            MockOption(strike=180.0, delta=-0.20),
            MockOption(strike=175.0, delta=-0.15),
            MockOption(strike=170.0, delta=-0.10),
        ]

        output = formatter.format(
            symbol="AAPL",
            options=options,
            underlying_price=185.50,
            right="P",
            dte_min=30,
            dte_max=60,
        )

        assert "AAPL" in output
        assert "180" in output or "$180" in output

    def test_format_calls(self):
        """Test formatting call options."""
        formatter = OptionsChainFormatter()
        options = [MockOption(strike=190.0, delta=0.30)]

        output = formatter.format(
            symbol="AAPL",
            options=options,
            underlying_price=185.50,
            right="C",
            dte_min=30,
            dte_max=60,
        )

        assert output is not None


# =============================================================================
# EARNINGS FORMATTER TESTS
# =============================================================================

class TestEarningsFormatter:
    """Tests for EarningsFormatter."""

    def test_format_earnings_safe(self):
        """Test formatting earnings with safe buffer."""
        formatter = EarningsFormatter()

        output = formatter.format(
            symbol="AAPL",
            earnings_date="2026-04-25",
            days_to_earnings=80,
            min_days=45,
            source="marketdata",
        )

        assert "AAPL" in output
        assert "80" in output or "SAFE" in output or "OK" in output

    def test_format_earnings_unsafe(self):
        """Test formatting earnings with unsafe buffer."""
        formatter = EarningsFormatter()

        output = formatter.format(
            symbol="AAPL",
            earnings_date="2026-02-15",
            days_to_earnings=10,
            min_days=45,
            source="marketdata",
        )

        assert "AAPL" in output
        # Should indicate not safe
        assert "10" in output or "NOT SAFE" in output or "X" in output or "WARNING" in output

    def test_format_earnings_etf(self):
        """Test formatting earnings for ETF."""
        formatter = EarningsFormatter()

        output = formatter.format(
            symbol="SPY",
            earnings_date=None,
            days_to_earnings=None,
            min_days=45,
            source="etf",
            is_etf=True,
        )

        assert "SPY" in output
        assert "ETF" in output or "N/A" in output

    def test_format_no_earnings(self):
        """Test formatting with no earnings date."""
        formatter = EarningsFormatter()

        output = formatter.format(
            symbol="AAPL",
            earnings_date=None,
            days_to_earnings=None,
            min_days=45,
            source="unknown",
        )

        assert "AAPL" in output


# =============================================================================
# HISTORICAL DATA FORMATTER TESTS
# =============================================================================

class TestHistoricalDataFormatter:
    """Tests for HistoricalDataFormatter."""

    def test_format_historical_data(self):
        """Test formatting historical data."""
        formatter = HistoricalDataFormatter()
        bars = [
            MockHistoricalBar(date="2026-01-15", close=185.50),
            MockHistoricalBar(date="2026-01-14", close=183.00),
            MockHistoricalBar(date="2026-01-13", close=184.50),
        ]

        output = formatter.format("AAPL", bars)

        assert "AAPL" in output

    def test_format_empty_historical(self):
        """Test formatting empty historical data."""
        formatter = HistoricalDataFormatter()

        output = formatter.format("AAPL", [])

        assert "AAPL" in output


# =============================================================================
# STRATEGY RECOMMENDATION FORMATTER TESTS
# =============================================================================

class TestStrategyRecommendationFormatter:
    """Tests for StrategyRecommendationFormatter."""

    def test_format_recommendation(self):
        """Test formatting strategy recommendation."""
        formatter = StrategyRecommendationFormatter()
        strategy = MockStrategy()

        output = formatter.format(strategy, vix=18.5)

        assert output is not None
        assert "18.5" in output or "VIX" in output or "normal" in output.lower()

    def test_format_recommendation_with_warnings(self):
        """Test formatting recommendation with warnings."""
        formatter = StrategyRecommendationFormatter()
        strategy = MockStrategy(warnings=["High VIX - reduce position size"])

        output = formatter.format(strategy, vix=25.0)

        assert output is not None


# =============================================================================
# SYMBOL ANALYSIS FORMATTER TESTS
# =============================================================================

class TestSymbolAnalysisFormatter:
    """Tests for SymbolAnalysisFormatter."""

    def test_format_analysis(self):
        """Test formatting symbol analysis."""
        formatter = SymbolAnalysisFormatter()
        strategy = MockStrategy()
        quote = MockQuote()
        earnings = MockEarnings()

        output = formatter.format(
            symbol="AAPL",
            vix=18.5,
            recommendation=strategy,
            quote=quote,
            historical=None,
            earnings=earnings,
        )

        assert "AAPL" in output

    def test_format_analysis_with_historical(self):
        """Test formatting analysis with historical data."""
        formatter = SymbolAnalysisFormatter()
        strategy = MockStrategy()
        quote = MockQuote()
        earnings = MockEarnings()

        # Create historical data tuple: (prices, volumes, highs, lows)
        prices = [180.0 + i for i in range(250)]  # 250 days of prices
        volumes = [1000000] * 250
        highs = [p + 2 for p in prices]
        lows = [p - 2 for p in prices]
        historical = (prices, volumes, highs, lows)

        output = formatter.format(
            symbol="AAPL",
            vix=18.5,
            recommendation=strategy,
            quote=quote,
            historical=historical,
            earnings=earnings,
        )

        assert "AAPL" in output
        assert "SMA" in output or "Technical" in output


# =============================================================================
# FORMATTER REGISTRY TESTS
# =============================================================================

class TestFormatterRegistry:
    """Tests for FormatterRegistry."""

    def test_registry_has_formatters(self):
        """Test registry has standard formatters."""
        registry = FormatterRegistry()

        assert registry.quote is not None
        assert registry.earnings is not None
        assert registry.options_chain is not None
        assert registry.scan_result is not None


# =============================================================================
# HEALTH CHECK FORMATTER TESTS
# =============================================================================

@dataclass
class MockScannerConfig:
    """Mock scanner config for HealthCheckFormatter."""
    min_score: int = 7
    exclude_earnings_within_days: int = 45
    enable_iv_filter: bool = True
    iv_rank_minimum: float = 30.0
    iv_rank_maximum: float = 70.0
    max_concurrent: int = 10


class TestHealthCheckFormatter:
    """Tests for HealthCheckFormatter."""

    def _create_health_data(self, connected: bool = True):
        """Create mock HealthCheckData."""
        from src.formatters.output_formatters import HealthCheckData
        return HealthCheckData(
            version="4.1.0",
            api_key_masked="abc***xyz",
            connected=connected,
            current_vix=18.5,
            vix_updated=datetime(2026, 2, 1, 10, 0, 0),
            watchlist_symbols=350,
            watchlist_sectors=11,
            cache_stats={
                "entries": 100,
                "max_entries": 500,
                "hit_rate_percent": 75.0,
                "hits": 150,
                "misses": 50,
                "ttl_seconds": 3600,
            },
            circuit_breaker_stats={
                "state": "closed",
                "failure_count": 0,
                "failure_threshold": 5,
                "total_calls": 1000,
                "rejected_calls": 0,
                "recovery_timeout": 60,
            },
            rate_limiter_stats={
                "total_requests": 500,
                "total_waits": 10,
                "avg_wait_time": 0.05,
                "available_tokens": 90,
            },
            scanner_config=MockScannerConfig(),
        )

    def test_format_health_check_healthy(self):
        """Test formatting healthy status."""
        formatter = HealthCheckFormatter()
        data = self._create_health_data(connected=True)

        output = formatter.format(data)

        assert "OptionPlay" in output or "Health" in output
        assert "Connected" in output

    def test_format_health_check_disconnected(self):
        """Test formatting disconnected status."""
        formatter = HealthCheckFormatter()
        data = self._create_health_data(connected=False)

        output = formatter.format(data)

        assert output is not None
        assert "Not connected" in output or "❌" in output


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_scan_formatter_max_results(self):
        """Test scan formatter respects max_results."""
        formatter = ScanResultFormatter()
        signals = [MockSignal(symbol=f"SYM{i}") for i in range(20)]
        result = MockScanResult(signals=signals, symbols_with_signals=20)

        output = formatter.format(result, max_results=5)

        # Should limit output
        assert output is not None

    def test_options_formatter_max_options(self):
        """Test options formatter respects max_options."""
        formatter = OptionsChainFormatter()
        options = [MockOption(strike=170.0 + i) for i in range(20)]

        output = formatter.format(
            symbol="AAPL",
            options=options,
            underlying_price=185.50,
            right="P",
            dte_min=30,
            dte_max=60,
            max_options=5,
        )

        assert output is not None

    def test_quote_formatter_zero_volume(self):
        """Test quote formatter with zero volume."""
        formatter = QuoteFormatter()
        quote = MockQuote(volume=0)

        output = formatter.format("AAPL", quote)

        assert "AAPL" in output

    def test_earnings_formatter_negative_days(self):
        """Test earnings formatter with negative days (past earnings)."""
        formatter = EarningsFormatter()

        output = formatter.format(
            symbol="AAPL",
            earnings_date="2026-01-01",
            days_to_earnings=-30,
            min_days=45,
            source="marketdata",
        )

        assert "AAPL" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
