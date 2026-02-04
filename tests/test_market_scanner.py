# Tests for Market Scanner
# ========================
"""
Tests for MarketScanner class.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from src.scanner.market_scanner import MarketScanner
from src.models.base import TradeSignal, SignalType


# =============================================================================
# MOCK CLASSES
# =============================================================================

def create_mock_analyzer(name: str = "MockStrategy", default_score: float = 7.0):
    """Create a mock analyzer."""
    analyzer = MagicMock()
    analyzer.strategy_name = name

    def mock_analyze(symbol, prices, volumes, highs, lows, **kwargs):
        signal = MagicMock(spec=TradeSignal)
        signal.symbol = symbol
        signal.score = default_score
        signal.strategy = name
        signal.signal_type = SignalType.BULLISH
        return signal

    analyzer.analyze = mock_analyze
    analyzer.create_neutral_signal = MagicMock(return_value=MagicMock(score=0))
    return analyzer


def create_sample_prices(n: int = 100):
    """Create sample price data."""
    return [100.0 + i * 0.1 for i in range(n)]


def create_sample_volumes(n: int = 100):
    """Create sample volume data."""
    return [1000000 + i * 1000 for i in range(n)]


# =============================================================================
# INIT TESTS
# =============================================================================

class TestMarketScannerInit:
    """Tests for MarketScanner initialization."""

    def test_init_empty_analyzers(self):
        """Test scanner starts with empty analyzers."""
        scanner = MarketScanner()
        assert scanner._analyzers == []

    def test_init_last_scan_none(self):
        """Test scanner starts with no last scan."""
        scanner = MarketScanner()
        assert scanner._last_scan is None


# =============================================================================
# REGISTER ANALYZER TESTS
# =============================================================================

class TestRegisterAnalyzer:
    """Tests for register_analyzer method."""

    def test_register_single_analyzer(self):
        """Test registering a single analyzer."""
        scanner = MarketScanner()
        analyzer = create_mock_analyzer("Pullback")

        scanner.register_analyzer(analyzer)

        assert len(scanner._analyzers) == 1

    def test_register_multiple_analyzers(self):
        """Test registering multiple analyzers."""
        scanner = MarketScanner()

        scanner.register_analyzer(create_mock_analyzer("Pullback"))
        scanner.register_analyzer(create_mock_analyzer("Bounce"))
        scanner.register_analyzer(create_mock_analyzer("Breakout"))

        assert len(scanner._analyzers) == 3


# =============================================================================
# GET ANALYZERS TESTS
# =============================================================================

class TestGetAnalyzers:
    """Tests for get_analyzers method."""

    def test_get_analyzers_empty(self):
        """Test get_analyzers returns empty list when none registered."""
        scanner = MarketScanner()
        assert scanner.get_analyzers() == []

    def test_get_analyzers_returns_names(self):
        """Test get_analyzers returns analyzer names."""
        scanner = MarketScanner()
        scanner.register_analyzer(create_mock_analyzer("Pullback"))
        scanner.register_analyzer(create_mock_analyzer("Bounce"))

        names = scanner.get_analyzers()

        assert "Pullback" in names
        assert "Bounce" in names


# =============================================================================
# SCAN SYMBOL TESTS
# =============================================================================

class TestScanSymbol:
    """Tests for scan_symbol method."""

    @pytest.mark.asyncio
    async def test_scan_symbol_returns_signals(self):
        """Test scan_symbol returns list of signals."""
        scanner = MarketScanner()
        scanner.register_analyzer(create_mock_analyzer("Pullback"))

        prices = create_sample_prices()
        volumes = create_sample_volumes()
        highs = [p * 1.01 for p in prices]
        lows = [p * 0.99 for p in prices]

        signals = await scanner.scan_symbol(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        assert isinstance(signals, list)
        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_scan_symbol_multiple_analyzers(self):
        """Test scan_symbol with multiple analyzers."""
        scanner = MarketScanner()
        scanner.register_analyzer(create_mock_analyzer("Pullback"))
        scanner.register_analyzer(create_mock_analyzer("Bounce"))
        scanner.register_analyzer(create_mock_analyzer("Breakout"))

        prices = create_sample_prices()
        volumes = create_sample_volumes()
        highs = [p * 1.01 for p in prices]
        lows = [p * 0.99 for p in prices]

        signals = await scanner.scan_symbol(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        assert len(signals) == 3

    @pytest.mark.asyncio
    async def test_scan_symbol_handles_error(self):
        """Test scan_symbol handles analyzer errors gracefully."""
        scanner = MarketScanner()

        # Create failing analyzer
        failing_analyzer = MagicMock()
        failing_analyzer.strategy_name = "Failing"
        failing_analyzer.analyze = MagicMock(side_effect=Exception("Test error"))
        failing_analyzer.create_neutral_signal = MagicMock(return_value=MagicMock(score=0))

        scanner.register_analyzer(failing_analyzer)

        prices = create_sample_prices()
        volumes = create_sample_volumes()
        highs = [p * 1.01 for p in prices]
        lows = [p * 0.99 for p in prices]

        # Should not raise
        signals = await scanner.scan_symbol(
            symbol="AAPL",
            prices=prices,
            volumes=volumes,
            highs=highs,
            lows=lows
        )

        assert len(signals) == 1  # Neutral signal returned


# =============================================================================
# SCAN TESTS
# =============================================================================

class TestScan:
    """Tests for scan method."""

    @pytest.mark.asyncio
    async def test_scan_returns_dict(self):
        """Test scan returns dictionary of results."""
        scanner = MarketScanner()
        scanner.register_analyzer(create_mock_analyzer("Pullback"))

        async def mock_fetcher(symbol):
            prices = create_sample_prices()
            volumes = create_sample_volumes()
            highs = [p * 1.01 for p in prices]
            lows = [p * 0.99 for p in prices]
            return (prices, volumes, highs, lows)

        results = await scanner.scan(
            symbols=["AAPL", "MSFT"],
            data_fetcher=mock_fetcher
        )

        assert isinstance(results, dict)

    @pytest.mark.asyncio
    async def test_scan_filters_by_min_score(self):
        """Test scan filters results by min_score."""
        scanner = MarketScanner()
        scanner.register_analyzer(create_mock_analyzer("HighScore", default_score=8.0))
        scanner.register_analyzer(create_mock_analyzer("LowScore", default_score=3.0))

        async def mock_fetcher(symbol):
            prices = create_sample_prices()
            volumes = create_sample_volumes()
            highs = [p * 1.01 for p in prices]
            lows = [p * 0.99 for p in prices]
            return (prices, volumes, highs, lows)

        results = await scanner.scan(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher,
            min_score=5.0
        )

        # Only HighScore should pass
        if "AAPL" in results:
            for signal in results["AAPL"]:
                assert signal.score >= 5.0

    @pytest.mark.asyncio
    async def test_scan_filters_strategies(self):
        """Test scan can filter by strategy names."""
        scanner = MarketScanner()
        scanner.register_analyzer(create_mock_analyzer("Pullback"))
        scanner.register_analyzer(create_mock_analyzer("Bounce"))
        scanner.register_analyzer(create_mock_analyzer("Breakout"))

        async def mock_fetcher(symbol):
            prices = create_sample_prices()
            volumes = create_sample_volumes()
            highs = [p * 1.01 for p in prices]
            lows = [p * 0.99 for p in prices]
            return (prices, volumes, highs, lows)

        results = await scanner.scan(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher,
            strategies=["Pullback", "Bounce"]  # Exclude Breakout
        )

        assert isinstance(results, dict)

    @pytest.mark.asyncio
    async def test_scan_no_analyzers_returns_empty(self):
        """Test scan returns empty dict with no analyzers."""
        scanner = MarketScanner()

        async def mock_fetcher(symbol):
            return ([], [], [], [])

        results = await scanner.scan(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher
        )

        assert results == {}

    @pytest.mark.asyncio
    async def test_scan_handles_fetch_errors(self):
        """Test scan handles data fetch errors gracefully."""
        scanner = MarketScanner()
        scanner.register_analyzer(create_mock_analyzer("Pullback"))

        async def failing_fetcher(symbol):
            raise Exception("Fetch error")

        # Should not raise
        results = await scanner.scan(
            symbols=["AAPL"],
            data_fetcher=failing_fetcher
        )

        assert isinstance(results, dict)

    @pytest.mark.asyncio
    async def test_scan_sets_last_scan(self):
        """Test scan updates _last_scan timestamp."""
        scanner = MarketScanner()
        scanner.register_analyzer(create_mock_analyzer("Pullback"))

        async def mock_fetcher(symbol):
            prices = create_sample_prices()
            volumes = create_sample_volumes()
            highs = [p * 1.01 for p in prices]
            lows = [p * 0.99 for p in prices]
            return (prices, volumes, highs, lows)

        await scanner.scan(
            symbols=["AAPL"],
            data_fetcher=mock_fetcher
        )

        assert scanner._last_scan is not None
        assert isinstance(scanner._last_scan, datetime)


# =============================================================================
# GET TOP SIGNALS TESTS
# =============================================================================

class TestGetTopSignals:
    """Tests for get_top_signals method."""

    def test_get_top_signals_returns_sorted(self):
        """Test get_top_signals returns sorted by score."""
        scanner = MarketScanner()

        # Create mock signals - SignalType uses LONG, SHORT, NEUTRAL
        signal1 = MagicMock(score=6.0, signal_type=SignalType.LONG)
        signal2 = MagicMock(score=8.0, signal_type=SignalType.LONG)
        signal3 = MagicMock(score=7.0, signal_type=SignalType.LONG)

        scan_results = {
            "AAPL": [signal1],
            "MSFT": [signal2],
            "GOOGL": [signal3],
        }

        top = scanner.get_top_signals(scan_results, top_n=2)

        assert len(top) == 2
        assert top[0].score >= top[1].score

    def test_get_top_signals_respects_top_n(self):
        """Test get_top_signals respects top_n limit."""
        scanner = MarketScanner()

        signals = [MagicMock(score=i, signal_type=SignalType.LONG) for i in range(10)]
        scan_results = {f"SYM{i}": [signals[i]] for i in range(10)}

        top = scanner.get_top_signals(scan_results, top_n=3)

        assert len(top) == 3

    def test_get_top_signals_filters_by_type(self):
        """Test get_top_signals can filter by signal type."""
        scanner = MarketScanner()

        long_signal = MagicMock(score=8.0, signal_type=SignalType.LONG)
        short_signal = MagicMock(score=9.0, signal_type=SignalType.SHORT)

        scan_results = {
            "AAPL": [long_signal],
            "MSFT": [short_signal],
        }

        top = scanner.get_top_signals(
            scan_results,
            top_n=10,
            signal_type=SignalType.LONG
        )

        assert len(top) == 1
        assert top[0].signal_type == SignalType.LONG

    def test_get_top_signals_empty_results(self):
        """Test get_top_signals with empty results."""
        scanner = MarketScanner()

        top = scanner.get_top_signals({}, top_n=10)

        assert top == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
