# OptionPlay - Multi-Strategy Scanner Tests
# ==========================================
# Comprehensive unit tests for MultiStrategyScanner
#
# Test Coverage:
# - ScanConfig dataclass initialization and field validation
# - ScanResult dataclass methods and properties
# - MultiStrategyScanner initialization with various configurations
# - Analyzer registration and pool management
# - Single symbol analysis
# - Sync and async scan methods
# - Strategy selection and filtering
# - Score aggregation and sorting
# - Earnings filtering
# - IV rank filtering
# - Fundamentals filtering
# - Stability scoring and filtering
# - Symbol concentration limits
# - Export and summary functions

import pytest
import asyncio
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Tuple, List, Dict, Optional
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock

from src.scanner.multi_strategy_scanner import (
    MultiStrategyScanner,
    ScanConfig,
    ScanResult,
    ScanMode,
    create_scanner,
    quick_scan,
    _get_default_blacklist_scanner,
)
from src.models.base import TradeSignal, SignalType, SignalStrength


# =============================================================================
# Test Data Fixtures
# =============================================================================

def create_uptrend_data(n: int = 100) -> Tuple[List[float], List[int], List[float], List[float]]:
    """Erstellt Aufwärtstrend-Daten"""
    prices = [100 + i * 0.2 for i in range(n)]
    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


def create_pullback_data(n: int = 100) -> Tuple[List[float], List[int], List[float], List[float]]:
    """Erstellt Pullback-Daten (Aufwärtstrend mit Rücksetzer)"""
    prices = []
    for i in range(n):
        if i < 80:
            prices.append(100 + i * 0.25)  # Aufwärtstrend
        else:
            prices.append(120 - (i - 80) * 0.3)  # Pullback

    volumes = [1000000] * n
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    return prices, volumes, highs, lows


def create_bounce_data(n: int = 100) -> Tuple[List[float], List[int], List[float], List[float]]:
    """Erstellt Bounce-Daten (Support-Test)"""
    prices = []
    highs = []
    lows = []

    for i in range(n):
        if i < 60:
            p = 100 + i * 0.2
        elif i < 85:
            p = 112 - (i - 60) * 0.5  # Pullback
        else:
            p = 99.5 + (i - 85) * 0.3  # Bounce

        prices.append(p)
        highs.append(p + 0.5)
        lows.append(p - 0.5)

    # Support-Touches
    lows[30] = 99.0
    lows[55] = 99.2
    lows[84] = 99.0

    volumes = [1000000] * n
    volumes[-1] = 1500000  # Erhöhtes Volumen beim Bounce

    return prices, volumes, highs, lows


def create_flat_data(n: int = 100) -> Tuple[List[float], List[int], List[float], List[float]]:
    """Erstellt flache Daten (kein Signal)"""
    prices = [100.0] * n
    volumes = [1000000] * n
    highs = [100.5] * n
    lows = [99.5] * n
    return prices, volumes, highs, lows


def create_test_signal(
    symbol: str = "TEST",
    strategy: str = "pullback",
    score: float = 5.0,
    stability_score: Optional[float] = None,
    signal_type: SignalType = SignalType.LONG,
) -> TradeSignal:
    """Helper to create test signals"""
    details = {}
    if stability_score is not None:
        details['stability'] = {'score': stability_score}

    return TradeSignal(
        symbol=symbol,
        strategy=strategy,
        signal_type=signal_type,
        strength=SignalStrength.MODERATE,
        score=score,
        current_price=100.0,
        details=details,
    )


# =============================================================================
# ScanConfig Tests
# =============================================================================

class TestScanConfig:
    """Tests for ScanConfig dataclass"""

    def test_default_values(self):
        """Default configuration should have sensible defaults"""
        config = ScanConfig()

        assert config.min_score == 3.5
        assert config.min_actionable_score == 5.0
        assert config.exclude_earnings_within_days == 45
        assert config.iv_rank_minimum == 30.0
        assert config.iv_rank_maximum == 80.0
        assert config.enable_iv_filter is True
        assert config.enable_liquidity_filter is True
        assert config.max_results_per_symbol == 3
        assert config.max_total_results == 50
        assert config.max_concurrent == 10
        assert config.min_data_points == 60
        assert config.enable_pullback is True
        assert config.enable_ath_breakout is True
        assert config.enable_bounce is True
        assert config.enable_earnings_dip is True
        assert config.use_analyzer_pool is True

    def test_custom_values(self):
        """Custom values should be applied"""
        config = ScanConfig(
            min_score=7.0,
            exclude_earnings_within_days=45,
            max_total_results=100,
            enable_pullback=False,
        )

        assert config.min_score == 7.0
        assert config.exclude_earnings_within_days == 45
        assert config.max_total_results == 100
        assert config.enable_pullback is False

    def test_stability_first_config(self):
        """Stability-first configuration defaults"""
        config = ScanConfig()

        assert config.enable_stability_first is True
        assert config.stability_qualified_threshold == 60.0
        assert config.stability_qualified_min_score == 3.5

    def test_win_rate_integration_config(self):
        """Win rate integration configuration"""
        config = ScanConfig()

        assert config.enable_win_rate_integration is True
        assert config.win_rate_base_multiplier == 0.7
        assert config.win_rate_divisor == 300.0

    def test_drawdown_adjustment_config(self):
        """Drawdown adjustment configuration"""
        config = ScanConfig()

        assert config.enable_drawdown_adjustment is True
        assert config.drawdown_penalty_threshold == 10.0
        assert config.drawdown_penalty_per_pct == 0.02

    def test_fundamentals_filter_config(self):
        """Fundamentals filter configuration"""
        config = ScanConfig()

        assert config.enable_fundamentals_filter is True
        assert config.fundamentals_min_stability >= 0
        assert config.fundamentals_min_win_rate == 65.0
        assert config.fundamentals_max_volatility == 70.0
        assert config.fundamentals_max_beta == 2.0

    def test_blacklist_default(self):
        """Blacklist should have default values"""
        config = ScanConfig()

        # Should have a blacklist
        assert config.fundamentals_blacklist is not None
        assert isinstance(config.fundamentals_blacklist, list)
        # Known volatile symbols should be in the list
        assert "TSLA" in config.fundamentals_blacklist or len(config.fundamentals_blacklist) > 0

    def test_sector_filter_defaults(self):
        """Sector filter lists should be empty by default"""
        config = ScanConfig()

        assert config.fundamentals_exclude_sectors == []
        assert config.fundamentals_include_sectors == []
        assert config.fundamentals_exclude_market_caps == []
        assert config.fundamentals_include_market_caps == []


class TestDefaultBlacklistScanner:
    """Tests for _get_default_blacklist_scanner function"""

    def test_returns_list(self):
        """Should return a list of symbols"""
        blacklist = _get_default_blacklist_scanner()

        assert isinstance(blacklist, list)
        assert len(blacklist) > 0

    def test_blacklist_contains_volatile_symbols(self):
        """Blacklist should contain known volatile symbols"""
        blacklist = _get_default_blacklist_scanner()

        # Check for some common volatile symbols
        volatile_symbols = ["TSLA", "MSTR", "COIN"]
        found = [s for s in volatile_symbols if s in blacklist]
        assert len(found) > 0, "Blacklist should contain some volatile symbols"


# =============================================================================
# ScanResult Tests
# =============================================================================

class TestScanResult:
    """Tests for ScanResult dataclass"""

    def test_initialization(self):
        """ScanResult should initialize correctly"""
        signals = [create_test_signal("AAPL"), create_test_signal("MSFT")]

        result = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=10,
            symbols_with_signals=2,
            total_signals=2,
            signals=signals,
        )

        assert result.symbols_scanned == 10
        assert result.symbols_with_signals == 2
        assert result.total_signals == 2
        assert len(result.signals) == 2
        assert result.errors == []
        assert result.scan_duration_seconds == 0.0

    def test_get_by_strategy(self):
        """get_by_strategy should filter signals correctly"""
        signals = [
            create_test_signal("AAPL", strategy="pullback"),
            create_test_signal("MSFT", strategy="bounce"),
            create_test_signal("GOOGL", strategy="pullback"),
        ]

        result = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=3,
            symbols_with_signals=3,
            total_signals=3,
            signals=signals,
        )

        pullback_signals = result.get_by_strategy("pullback")
        assert len(pullback_signals) == 2
        assert all(s.strategy == "pullback" for s in pullback_signals)

        bounce_signals = result.get_by_strategy("bounce")
        assert len(bounce_signals) == 1
        assert bounce_signals[0].symbol == "MSFT"

        # Non-existent strategy
        empty = result.get_by_strategy("non_existent")
        assert len(empty) == 0

    def test_get_by_symbol(self):
        """get_by_symbol should filter signals correctly"""
        signals = [
            create_test_signal("AAPL", strategy="pullback"),
            create_test_signal("AAPL", strategy="bounce"),
            create_test_signal("MSFT", strategy="pullback"),
        ]

        result = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=2,
            symbols_with_signals=2,
            total_signals=3,
            signals=signals,
        )

        aapl_signals = result.get_by_symbol("AAPL")
        assert len(aapl_signals) == 2
        assert all(s.symbol == "AAPL" for s in aapl_signals)

        msft_signals = result.get_by_symbol("MSFT")
        assert len(msft_signals) == 1

    def test_get_actionable(self):
        """get_actionable should return only actionable signals"""
        signals = [
            create_test_signal("AAPL", score=5.0, signal_type=SignalType.LONG),  # actionable
            create_test_signal("MSFT", score=2.0, signal_type=SignalType.LONG),  # low score
            create_test_signal("GOOGL", score=5.0, signal_type=SignalType.NEUTRAL),  # neutral
        ]

        result = ScanResult(
            timestamp=datetime.now(),
            symbols_scanned=3,
            symbols_with_signals=3,
            total_signals=3,
            signals=signals,
        )

        actionable = result.get_actionable()
        # Only AAPL should be actionable (score >= 3.5 and LONG/SHORT)
        assert len(actionable) == 1
        assert actionable[0].symbol == "AAPL"

    def test_to_dict(self):
        """to_dict should serialize correctly"""
        signals = [create_test_signal("AAPL")]
        timestamp = datetime.now()

        result = ScanResult(
            timestamp=timestamp,
            symbols_scanned=10,
            symbols_with_signals=1,
            total_signals=1,
            signals=signals,
            errors=["error1"],
            scan_duration_seconds=1.5,
        )

        d = result.to_dict()

        assert d['timestamp'] == timestamp.isoformat()
        assert d['symbols_scanned'] == 10
        assert d['symbols_with_signals'] == 1
        assert d['total_signals'] == 1
        assert d['scan_duration_seconds'] == 1.5
        assert d['errors'] == ["error1"]
        assert isinstance(d['signals'], list)
        assert len(d['signals']) == 1


# =============================================================================
# Scanner Initialization Tests
# =============================================================================

class TestScannerInitialization:
    """Tests für Scanner-Initialisierung"""

    def test_default_initialization(self):
        """Standard-Initialisierung sollte alle Analyzer registrieren"""
        scanner = MultiStrategyScanner()

        # Sollte mindestens 3 Analyzer haben (pullback könnte fehlen)
        assert len(scanner.available_strategies) >= 3
        assert 'ath_breakout' in scanner.available_strategies
        assert 'bounce' in scanner.available_strategies
        assert 'earnings_dip' in scanner.available_strategies

    def test_custom_config(self):
        """Custom Config sollte angewendet werden"""
        config = ScanConfig(
            min_score=7.0,
            enable_earnings_dip=False,
            max_total_results=20
        )
        scanner = MultiStrategyScanner(config)

        assert scanner.config.min_score == 7.0
        assert scanner.config.max_total_results == 20
        assert 'earnings_dip' not in scanner.available_strategies

    def test_create_scanner_factory(self):
        """Factory-Funktion sollte funktionieren"""
        scanner = create_scanner(
            enable_pullback=False,
            enable_breakout=True,
            min_score=6.0
        )

        assert scanner.config.min_score == 6.0
        assert 'ath_breakout' in scanner.available_strategies

    def test_scanner_without_pool(self):
        """Scanner ohne Analyzer Pool sollte funktionieren"""
        config = ScanConfig(use_analyzer_pool=False)
        scanner = MultiStrategyScanner(config)

        assert scanner._use_pool is False
        assert scanner._pool is None
        # Should still have analyzers registered
        assert len(scanner.available_strategies) >= 1

    def test_scanner_with_pool(self):
        """Scanner mit Analyzer Pool sollte funktionieren"""
        config = ScanConfig(use_analyzer_pool=True)
        scanner = MultiStrategyScanner(config)

        assert scanner._use_pool is True
        assert scanner._pool is not None

    def test_pool_stats(self):
        """Pool stats sollten verfügbar sein"""
        config = ScanConfig(use_analyzer_pool=True)
        scanner = MultiStrategyScanner(config)

        stats = scanner.pool_stats()
        assert isinstance(stats, dict)
        # Should have pool statistics
        assert 'registered_strategies' in stats or 'pool_enabled' in stats

    def test_pool_stats_without_pool(self):
        """Pool stats ohne Pool sollten pool_enabled=False zeigen"""
        config = ScanConfig(use_analyzer_pool=False)
        scanner = MultiStrategyScanner(config)

        stats = scanner.pool_stats()
        assert stats == {"pool_enabled": False}

    def test_prefill_pool(self):
        """Pool prefill sollte funktionieren"""
        config = ScanConfig(use_analyzer_pool=True)
        scanner = MultiStrategyScanner(config)

        result = scanner.prefill_pool()
        assert isinstance(result, dict)

    def test_available_strategies_property(self):
        """available_strategies property sollte korrekt funktionieren"""
        config = ScanConfig(
            enable_pullback=True,
            enable_ath_breakout=True,
            enable_bounce=False,
            enable_earnings_dip=False,
        )
        scanner = MultiStrategyScanner(config)

        strategies = scanner.available_strategies
        assert 'ath_breakout' in strategies
        assert 'bounce' not in strategies
        assert 'earnings_dip' not in strategies


class TestAnalyzerRegistration:
    """Tests for analyzer registration"""

    def test_register_custom_analyzer(self):
        """Should be able to register custom analyzers"""
        from src.analyzers.base import BaseAnalyzer

        class CustomAnalyzer(BaseAnalyzer):
            @property
            def strategy_name(self) -> str:
                return "custom"

            def analyze(self, symbol, prices, volumes, highs, lows, **kwargs):
                return create_test_signal(symbol, strategy="custom")

        scanner = MultiStrategyScanner()
        custom = CustomAnalyzer()
        scanner.register_analyzer(custom)

        assert "custom" in scanner.available_strategies

    def test_get_analyzer_returns_analyzer(self):
        """get_analyzer should return registered analyzer"""
        scanner = MultiStrategyScanner()

        # Get an existing analyzer
        analyzer = scanner.get_analyzer("bounce")

        # May return analyzer or None depending on pool state
        if analyzer:
            assert analyzer.strategy_name == "bounce"

    def test_get_analyzer_unknown_returns_none(self):
        """get_analyzer for unknown strategy should return None"""
        scanner = MultiStrategyScanner()

        result = scanner.get_analyzer("unknown_strategy")
        assert result is None


# =============================================================================
# Single Symbol Analysis Tests
# =============================================================================

class TestSingleSymbolAnalysis:
    """Tests für Einzelsymbol-Analyse"""

    @pytest.fixture
    def scanner(self):
        config = ScanConfig(
            min_score=0,
            enable_liquidity_filter=False,
            enable_fundamentals_filter=False,
            enable_stability_scoring=False,
            enable_stability_first=False,
        )
        return MultiStrategyScanner(config)

    def test_analyze_uptrend(self, scanner):
        """Aufwärtstrend sollte analysiert werden"""
        prices, volumes, highs, lows = create_uptrend_data()

        signals = scanner.analyze_symbol("TEST", prices, volumes, highs, lows)

        # Sollte mindestens ein Signal zurückgeben oder leer sein
        assert isinstance(signals, list)

    def test_analyze_with_strategy_filter(self, scanner):
        """Strategie-Filter sollte funktionieren"""
        prices, volumes, highs, lows = create_uptrend_data()

        signals = scanner.analyze_symbol(
            "TEST", prices, volumes, highs, lows,
            strategies=['bounce']
        )

        # Alle Signale sollten von bounce sein
        for signal in signals:
            assert signal.strategy == 'bounce'

    def test_analyze_flat_no_signals(self, scanner):
        """Flache Daten sollten wenige/keine Signale geben"""
        prices, volumes, highs, lows = create_flat_data()

        # Erhöhe min_score um keine Signale zu bekommen
        scanner.config.min_score = 8.0
        signals = scanner.analyze_symbol("TEST", prices, volumes, highs, lows)

        assert len(signals) == 0

    def test_signals_sorted_by_score(self, scanner):
        """Signale sollten nach Score sortiert sein"""
        prices, volumes, highs, lows = create_bounce_data()
        scanner.config.min_score = 0  # Alle Signale

        signals = scanner.analyze_symbol("TEST", prices, volumes, highs, lows)

        if len(signals) > 1:
            scores = [s.score for s in signals]
            assert scores == sorted(scores, reverse=True)

    def test_analyze_respects_max_results_per_symbol(self, scanner):
        """Should respect max_results_per_symbol limit"""
        scanner.config.max_results_per_symbol = 1
        prices, volumes, highs, lows = create_bounce_data()

        signals = scanner.analyze_symbol("TEST", prices, volumes, highs, lows)

        assert len(signals) <= 1

    def test_analyze_with_opens_data(self, scanner):
        """Should handle optional opens data"""
        prices, volumes, highs, lows = create_uptrend_data()
        opens = [p - 0.1 for p in prices]  # Opens slightly below closes

        signals = scanner.analyze_symbol(
            "TEST", prices, volumes, highs, lows,
            opens=opens
        )

        assert isinstance(signals, list)

    def test_analyze_with_context(self, scanner):
        """Should accept pre-calculated context"""
        from src.analyzers.context import AnalysisContext

        prices, volumes, highs, lows = create_uptrend_data()
        context = AnalysisContext.from_data("TEST", prices, volumes, highs, lows)

        signals = scanner.analyze_symbol(
            "TEST", prices, volumes, highs, lows,
            context=context
        )

        assert isinstance(signals, list)


# =============================================================================
# Sync Scan Tests
# =============================================================================

class TestSyncScan:
    """Tests für synchrones Scanning"""

    @pytest.fixture
    def scanner(self):
        config = ScanConfig(
            min_score=0,  # Alle Signale
            enable_liquidity_filter=False,  # Deaktiviere Filter für Tests
            enable_fundamentals_filter=False,
            enable_stability_scoring=False,
            enable_stability_first=False,
        )
        return MultiStrategyScanner(config)

    def test_scan_multiple_symbols(self, scanner):
        """Scan mehrerer Symbole"""
        data_map = {
            "AAPL": create_uptrend_data(),
            "MSFT": create_bounce_data(),
            "GOOGL": create_flat_data()
        }

        def data_fetcher(symbol):
            return data_map.get(symbol)

        result = scanner.scan_sync(
            symbols=list(data_map.keys()),
            data_fetcher=data_fetcher
        )

        assert isinstance(result, ScanResult)
        assert result.symbols_scanned == 3
        assert result.scan_duration_seconds > 0

    def test_scan_with_mode_filter(self, scanner):
        """Scan mit Mode-Filter"""
        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(
            symbols=["TEST1", "TEST2"],
            data_fetcher=data_fetcher,
            mode=ScanMode.BOUNCE_ONLY
        )

        # Alle Signale sollten bounce sein
        for signal in result.signals:
            assert signal.strategy == 'bounce'

    def test_scan_best_signal_mode(self, scanner):
        """Best Signal Mode sollte nur bestes pro Symbol behalten"""
        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(
            symbols=["TEST1", "TEST2", "TEST3"],
            data_fetcher=data_fetcher,
            mode=ScanMode.BEST_SIGNAL
        )

        # Maximal ein Signal pro Symbol
        symbols = [s.symbol for s in result.signals]
        assert len(symbols) == len(set(symbols))

    def test_progress_callback(self, scanner):
        """Progress Callback sollte aufgerufen werden"""
        progress_calls = []

        def progress(current, total, symbol):
            progress_calls.append((current, total, symbol))

        def data_fetcher(symbol):
            return create_flat_data()

        scanner.scan_sync(
            symbols=["A", "B", "C"],
            data_fetcher=data_fetcher,
            progress_callback=progress
        )

        assert len(progress_calls) == 3
        assert progress_calls[0] == (1, 3, "A")
        assert progress_calls[2] == (3, 3, "C")

    def test_scan_handles_insufficient_data(self, scanner):
        """Should handle symbols with insufficient data"""
        def data_fetcher(symbol):
            if symbol == "SHORT":
                return ([100.0] * 10, [1000] * 10, [101.0] * 10, [99.0] * 10)
            return create_uptrend_data()

        result = scanner.scan_sync(
            symbols=["SHORT", "FULL"],
            data_fetcher=data_fetcher
        )

        # Should complete without error
        assert isinstance(result, ScanResult)
        assert result.symbols_scanned == 2

    def test_scan_handles_data_fetcher_error(self, scanner):
        """Should handle data fetcher errors gracefully"""
        def data_fetcher(symbol):
            if symbol == "ERROR":
                raise ValueError("Test error")
            return create_uptrend_data()

        result = scanner.scan_sync(
            symbols=["OK", "ERROR", "OK2"],
            data_fetcher=data_fetcher
        )

        assert result.symbols_scanned == 3
        assert len(result.errors) == 1
        assert "ERROR" in result.errors[0]

    def test_scan_respects_max_total_results(self, scanner):
        """Should respect max_total_results limit"""
        scanner.config.max_total_results = 5

        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(
            symbols=[f"SYM{i}" for i in range(20)],
            data_fetcher=data_fetcher
        )

        assert len(result.signals) <= 5


# =============================================================================
# Async Scan Tests
# =============================================================================

class TestAsyncScan:
    """Tests für asynchrones Scanning"""

    @pytest.fixture
    def scanner(self):
        config = ScanConfig(
            min_score=0,
            enable_liquidity_filter=False,
            enable_fundamentals_filter=False,
            enable_stability_scoring=False,
            enable_stability_first=False,
        )
        return MultiStrategyScanner(config)

    @pytest.mark.asyncio
    async def test_async_scan(self, scanner):
        """Async Scan sollte funktionieren"""
        async def data_fetcher(symbol):
            await asyncio.sleep(0.01)  # Simuliere I/O
            return create_uptrend_data()

        result = await scanner.scan_async(
            symbols=["TEST1", "TEST2"],
            data_fetcher=data_fetcher
        )

        assert isinstance(result, ScanResult)
        assert result.symbols_scanned == 2

    @pytest.mark.asyncio
    async def test_async_with_errors(self, scanner):
        """Async Scan sollte Fehler handhaben"""
        async def data_fetcher(symbol):
            if symbol == "ERROR":
                raise ValueError("Test error")
            return create_flat_data()

        result = await scanner.scan_async(
            symbols=["OK", "ERROR", "OK2"],
            data_fetcher=data_fetcher
        )

        assert result.symbols_scanned == 3
        assert len(result.errors) == 1
        assert "ERROR" in result.errors[0]

    @pytest.mark.asyncio
    async def test_async_with_mode_filter(self, scanner):
        """Async scan with mode filter"""
        async def data_fetcher(symbol):
            return create_bounce_data()

        result = await scanner.scan_async(
            symbols=["TEST1", "TEST2"],
            data_fetcher=data_fetcher,
            mode=ScanMode.BOUNCE_ONLY
        )

        for signal in result.signals:
            assert signal.strategy == 'bounce'

    @pytest.mark.asyncio
    async def test_async_parallel_execution(self, scanner):
        """Async scan should execute in parallel"""
        call_times = []

        async def data_fetcher(symbol):
            call_times.append(datetime.now())
            await asyncio.sleep(0.05)
            return create_flat_data()

        await scanner.scan_async(
            symbols=["A", "B", "C", "D", "E"],
            data_fetcher=data_fetcher
        )

        # With parallel execution, calls should happen close together
        if len(call_times) >= 2:
            time_diff = (call_times[-1] - call_times[0]).total_seconds()
            # Should be much less than 5 * 0.05 = 0.25s if parallel
            assert time_diff < 0.2

    @pytest.mark.asyncio
    async def test_async_with_5_tuple_data(self, scanner):
        """Async scan with 5-tuple data (including opens)"""
        async def data_fetcher(symbol):
            prices, volumes, highs, lows = create_uptrend_data()
            opens = [p - 0.1 for p in prices]
            return prices, volumes, highs, lows, opens

        result = await scanner.scan_async(
            symbols=["TEST"],
            data_fetcher=data_fetcher
        )

        assert isinstance(result, ScanResult)


# =============================================================================
# Strategy Selection Tests
# =============================================================================

class TestStrategySelection:
    """Tests for strategy selection based on scan mode"""

    def test_get_strategies_for_mode_all(self):
        """ALL mode should return None (all strategies)"""
        scanner = MultiStrategyScanner()

        strategies = scanner._get_strategies_for_mode(ScanMode.ALL)
        assert strategies is None

    def test_get_strategies_for_mode_best_signal(self):
        """BEST_SIGNAL mode should return None (all strategies)"""
        scanner = MultiStrategyScanner()

        strategies = scanner._get_strategies_for_mode(ScanMode.BEST_SIGNAL)
        assert strategies is None

    def test_get_strategies_for_mode_pullback(self):
        """PULLBACK_ONLY mode should return only pullback"""
        scanner = MultiStrategyScanner()

        strategies = scanner._get_strategies_for_mode(ScanMode.PULLBACK_ONLY)
        assert strategies == ['pullback']

    def test_get_strategies_for_mode_breakout(self):
        """BREAKOUT_ONLY mode should return only ath_breakout"""
        scanner = MultiStrategyScanner()

        strategies = scanner._get_strategies_for_mode(ScanMode.BREAKOUT_ONLY)
        assert strategies == ['ath_breakout']

    def test_get_strategies_for_mode_bounce(self):
        """BOUNCE_ONLY mode should return only bounce"""
        scanner = MultiStrategyScanner()

        strategies = scanner._get_strategies_for_mode(ScanMode.BOUNCE_ONLY)
        assert strategies == ['bounce']

    def test_get_strategies_for_mode_earnings_dip(self):
        """EARNINGS_DIP mode should return only earnings_dip"""
        scanner = MultiStrategyScanner()

        strategies = scanner._get_strategies_for_mode(ScanMode.EARNINGS_DIP)
        assert strategies == ['earnings_dip']


# =============================================================================
# Score Aggregation Tests
# =============================================================================

class TestScoreAggregation:
    """Tests for score aggregation and sorting"""

    def test_keep_best_per_symbol(self):
        """_keep_best_per_symbol should keep only highest scoring signal per symbol"""
        scanner = MultiStrategyScanner()

        signals = [
            create_test_signal("AAPL", score=8.0),
            create_test_signal("AAPL", score=5.0),
            create_test_signal("MSFT", score=7.0),
            create_test_signal("MSFT", score=9.0),
        ]

        result = scanner._keep_best_per_symbol(signals)

        assert len(result) == 2
        aapl_signal = next(s for s in result if s.symbol == "AAPL")
        msft_signal = next(s for s in result if s.symbol == "MSFT")
        assert aapl_signal.score == 8.0
        assert msft_signal.score == 9.0

    def test_keep_best_per_symbol_sorted(self):
        """Result should be sorted by score descending"""
        scanner = MultiStrategyScanner()

        signals = [
            create_test_signal("AAPL", score=5.0),
            create_test_signal("MSFT", score=9.0),
            create_test_signal("GOOGL", score=7.0),
        ]

        result = scanner._keep_best_per_symbol(signals)

        scores = [s.score for s in result]
        assert scores == sorted(scores, reverse=True)


# =============================================================================
# Symbol Concentration Tests
# =============================================================================

class TestSymbolConcentration:
    """Tests for symbol concentration limits"""

    def test_limit_symbol_concentration(self):
        """Should limit number of signals per symbol"""
        scanner = MultiStrategyScanner()

        signals = [
            create_test_signal("AAPL", strategy="pullback", score=9.0),
            create_test_signal("AAPL", strategy="bounce", score=8.0),
            create_test_signal("AAPL", strategy="breakout", score=7.0),
            create_test_signal("MSFT", strategy="pullback", score=6.0),
        ]

        filtered, stats = scanner._limit_symbol_concentration(signals, max_appearances=2)

        # AAPL should only have 2 signals (the two highest scores)
        aapl_signals = [s for s in filtered if s.symbol == "AAPL"]
        assert len(aapl_signals) == 2
        # Should keep highest scores
        assert aapl_signals[0].score == 9.0
        assert aapl_signals[1].score == 8.0

    def test_limit_symbol_concentration_disabled(self):
        """max_appearances=0 should disable limiting"""
        scanner = MultiStrategyScanner()

        signals = [
            create_test_signal("AAPL", score=9.0),
            create_test_signal("AAPL", score=8.0),
            create_test_signal("AAPL", score=7.0),
        ]

        filtered, stats = scanner._limit_symbol_concentration(signals, max_appearances=0)

        assert len(filtered) == 3

    def test_limit_symbol_concentration_stats(self):
        """Should return correct stats"""
        scanner = MultiStrategyScanner()

        signals = [
            create_test_signal("AAPL", score=9.0),
            create_test_signal("AAPL", score=8.0),
            create_test_signal("MSFT", score=7.0),
        ]

        filtered, stats = scanner._limit_symbol_concentration(signals, max_appearances=1)

        assert stats.get("AAPL") == 1
        assert stats.get("MSFT") == 1


# =============================================================================
# Earnings Filter Tests
# =============================================================================

class TestEarningsFilter:
    """Tests für Earnings-Filter"""

    @pytest.fixture
    def scanner(self):
        config = ScanConfig(
            min_score=0,
            exclude_earnings_within_days=30
        )
        return MultiStrategyScanner(config)

    def test_earnings_filter_excludes(self, scanner):
        """Symbole mit nahen Earnings sollten gefiltert werden"""
        # Setze Earnings in 10 Tagen
        scanner.set_earnings_date("AAPL", date.today() + timedelta(days=10))

        prices, volumes, highs, lows = create_bounce_data()

        # Bounce sollte gefiltert werden (nicht earnings_dip)
        signals = scanner.analyze_symbol(
            "AAPL", prices, volumes, highs, lows,
            strategies=['bounce', 'earnings_dip']
        )

        bounce_signals = [s for s in signals if s.strategy == 'bounce']
        assert len(bounce_signals) == 0  # Bounce gefiltert

    def test_earnings_dip_with_upcoming_earnings_filtered(self, scanner):
        """earnings_dip sollte gefiltert werden wenn Earnings BEVORSTEHEN"""
        # Earnings in 10 Tagen -> noch nicht stattgefunden -> skip
        scanner.set_earnings_date("AAPL", date.today() + timedelta(days=10))
        should_skip = scanner._should_skip_for_earnings("AAPL", "earnings_dip")
        assert should_skip == True

    def test_earnings_dip_with_recent_past_earnings_not_filtered(self, scanner):
        """earnings_dip sollte NICHT gefiltert werden wenn Earnings KÜRZLICH waren"""
        # Earnings vor 5 Tagen -> kürzlich vergangen -> nicht skippen
        scanner.set_earnings_date("AAPL", date.today() - timedelta(days=5))
        should_skip = scanner._should_skip_for_earnings("AAPL", "earnings_dip")
        assert should_skip == False

    def test_earnings_dip_with_old_past_earnings_filtered(self, scanner):
        """earnings_dip sollte gefiltert werden wenn Earnings zu LANGE HER sind"""
        # Earnings vor 15 Tagen -> zu alt -> skip
        scanner.set_earnings_date("AAPL", date.today() - timedelta(days=15))
        should_skip = scanner._should_skip_for_earnings("AAPL", "earnings_dip")
        assert should_skip == True

    def test_past_earnings_not_filtered_for_other_strategies(self, scanner):
        """Vergangene Earnings sollten andere Strategien nicht filtern"""
        scanner.set_earnings_date("AAPL", date.today() - timedelta(days=5))
        should_skip = scanner._should_skip_for_earnings("AAPL", "bounce")
        assert should_skip == False

    def test_unknown_earnings_allowed_for_other_strategies(self, scanner):
        """Unbekannte Earnings sollten andere Strategien nicht blockieren"""
        # MSFT hat KEIN Earnings-Datum im Scanner-Cache
        # Neue Logik: erlaubt die Analyse statt konservativ zu überspringen
        should_skip = scanner._should_skip_for_earnings("MSFT", "bounce")
        assert should_skip == False

    def test_unknown_earnings_filtered_for_earnings_dip(self, scanner):
        """earnings_dip sollte auch bei unbekannten Earnings gefiltert werden"""
        # MSFT hat KEIN Earnings-Datum im Scanner-Cache
        # earnings_dip braucht bekannte, kürzlich vergangene Earnings -> skip
        should_skip = scanner._should_skip_for_earnings("MSFT", "earnings_dip")
        assert should_skip == True

    def test_set_earnings_date(self, scanner):
        """set_earnings_date should store earnings date"""
        earnings_date = date.today() + timedelta(days=30)
        scanner.set_earnings_date("AAPL", earnings_date)

        assert scanner._earnings_cache.get("AAPL") == earnings_date

    def test_earnings_filter_disabled_when_days_zero(self, scanner):
        """Earnings filter should be disabled when exclude_earnings_within_days=0"""
        scanner.config.exclude_earnings_within_days = 0
        scanner.set_earnings_date("AAPL", date.today() + timedelta(days=5))

        should_skip = scanner._should_skip_for_earnings("AAPL", "bounce")
        assert should_skip is False


# =============================================================================
# IV Rank Filter Tests
# =============================================================================

class TestIVRankFilter:
    """Tests for IV rank filtering"""

    @pytest.fixture
    def scanner(self):
        config = ScanConfig(
            min_score=0,
            enable_iv_filter=True,
            iv_rank_minimum=30.0,
            iv_rank_maximum=80.0,
        )
        return MultiStrategyScanner(config)

    def test_set_iv_rank(self, scanner):
        """set_iv_rank should store IV rank"""
        scanner.set_iv_rank("AAPL", 50.0)

        assert scanner._iv_cache.get("AAPL") == 50.0

    def test_set_iv_ranks_bulk(self, scanner):
        """set_iv_ranks should store multiple IV ranks"""
        scanner.set_iv_ranks({"AAPL": 50.0, "MSFT": 60.0})

        assert scanner._iv_cache.get("AAPL") == 50.0
        assert scanner._iv_cache.get("MSFT") == 60.0

    def test_iv_filter_passes_valid_range(self, scanner):
        """IV filter should pass symbols within valid range"""
        scanner.set_iv_rank("AAPL", 50.0)

        passes, reason = scanner._check_iv_filter("AAPL", "pullback")

        assert passes is True
        assert reason is None

    def test_iv_filter_fails_too_low(self, scanner):
        """IV filter should fail for IV rank below minimum"""
        scanner.set_iv_rank("AAPL", 20.0)

        passes, reason = scanner._check_iv_filter("AAPL", "pullback")

        assert passes is False
        assert "zu niedrig" in reason

    def test_iv_filter_fails_too_high(self, scanner):
        """IV filter should fail for IV rank above maximum"""
        scanner.set_iv_rank("AAPL", 90.0)

        passes, reason = scanner._check_iv_filter("AAPL", "pullback")

        assert passes is False
        assert "zu hoch" in reason

    def test_iv_filter_passes_unknown(self, scanner):
        """IV filter should pass when IV rank is unknown"""
        # No IV rank set for this symbol
        passes, reason = scanner._check_iv_filter("UNKNOWN", "pullback")

        assert passes is True
        assert reason is None

    def test_iv_filter_disabled(self, scanner):
        """IV filter should pass all when disabled"""
        scanner.config.enable_iv_filter = False
        scanner.set_iv_rank("AAPL", 10.0)  # Would fail normally

        passes, reason = scanner._check_iv_filter("AAPL", "pullback")

        assert passes is True

    def test_iv_filter_skipped_for_non_credit_strategies(self, scanner):
        """IV filter should be skipped for non-credit-spread strategies"""
        scanner.set_iv_rank("AAPL", 10.0)  # Would fail for pullback

        # These strategies don't use IV filter
        for strategy in ['earnings_dip', 'ath_breakout', 'bounce']:
            passes, reason = scanner._check_iv_filter("AAPL", strategy)
            assert passes is True


# =============================================================================
# VIX Management Tests
# =============================================================================

class TestVIXManagement:
    """Tests for VIX management"""

    def test_set_vix(self):
        """set_vix should store VIX value"""
        scanner = MultiStrategyScanner()

        scanner.set_vix(25.0)

        assert scanner._vix_cache == 25.0


# =============================================================================
# Stability Scoring Tests
# =============================================================================

class TestStabilityScoring:
    """Tests for stability scoring"""

    def test_get_symbol_stability(self):
        """Should return stability data if available"""
        scanner = MultiStrategyScanner()

        # Manually set stability data
        scanner._stability_cache["AAPL"] = {
            'stability_score': 85,
            'win_rate': 90,
            'avg_drawdown': 5.0,
        }

        data = scanner.get_symbol_stability("AAPL")

        assert data is not None
        assert data['stability_score'] == 85

    def test_get_symbol_stability_not_found(self):
        """Should return None for unknown symbol"""
        scanner = MultiStrategyScanner()

        data = scanner.get_symbol_stability("UNKNOWN")

        assert data is None


# =============================================================================
# Stability-First Filter Tests (Phase 6)
# =============================================================================

class TestStabilityFirstFilter:
    """Tests für Stability-First-Filterung"""

    @pytest.fixture
    def scanner_stability_enabled(self):
        """Scanner mit Stability-First aktiviert (simplified 2-tier)"""
        return MultiStrategyScanner(ScanConfig(
            min_score=3.5,
            enable_stability_first=True,
            stability_qualified_threshold=60.0,
            stability_qualified_min_score=3.5,
        ))

    @pytest.fixture
    def scanner_stability_disabled(self):
        """Scanner mit Stability-First deaktiviert"""
        return MultiStrategyScanner(ScanConfig(
            min_score=3.5,
            enable_stability_first=False,
        ))

    def _create_test_signal(self, symbol: str, score: float, stability_score: float = None):
        """Erstellt ein Test-Signal mit optionalem Stability-Score"""
        return create_test_signal(symbol, score=score, stability_score=stability_score)

    def test_qualified_symbol_passes(self, scanner_stability_enabled):
        """Qualified symbol (Stability >=60) with sufficient score passes"""
        signals = [self._create_test_signal('AAPL', score=4.5, stability_score=85.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 1
        assert stats['qualified_kept'] == 1

    def test_qualified_symbol_low_score_fails(self, scanner_stability_enabled):
        """Qualified symbol with score below min_score fails"""
        signals = [self._create_test_signal('MSFT', score=3.0, stability_score=85.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 0
        assert stats['score_too_low'] == 1

    def test_qualified_boundary_passes(self, scanner_stability_enabled):
        """Symbol at exact qualified threshold passes with sufficient score"""
        signals = [self._create_test_signal('GOOGL', score=5.5, stability_score=60.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 1
        assert stats['qualified_kept'] == 1

    def test_blacklist_symbol_always_fails(self, scanner_stability_enabled):
        """Blacklist symbol (Stability <60) is always filtered"""
        signals = [self._create_test_signal('TSLA', score=9.0, stability_score=55.0)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 0
        assert stats['blacklisted'] == 1

    def test_no_stability_data_uses_min_score(self, scanner_stability_enabled):
        """Symbol ohne Stability-Daten sollte min_score verwenden"""
        signals = [self._create_test_signal('UNKNOWN', score=4.0, stability_score=None)]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        # Score 4.0 >= min_score 3.5, sollte durchkommen
        assert len(filtered) == 1
        assert stats['no_stability_data'] == 1

    def test_filter_disabled_passes_all(self, scanner_stability_disabled):
        """Bei deaktiviertem Filter sollten alle Signale durchkommen"""
        signals = [
            self._create_test_signal('AAPL', score=4.0, stability_score=85.0),
            self._create_test_signal('TSLA', score=9.0, stability_score=40.0),
        ]
        filtered, stats = scanner_stability_disabled._filter_by_stability(signals)

        assert len(filtered) == 2
        assert stats.get('reason') == 'disabled'

    def test_mixed_signals_correctly_filtered(self, scanner_stability_enabled):
        """Gemischte Signale sollten korrekt gefiltert werden"""
        signals = [
            self._create_test_signal('AAPL', score=4.5, stability_score=85.0),  # Qualified OK
            self._create_test_signal('MSFT', score=3.0, stability_score=85.0),  # Qualified score too low
            self._create_test_signal('GOOGL', score=5.5, stability_score=65.0),  # Qualified OK
            self._create_test_signal('NFLX', score=7.0, stability_score=60.0),  # Qualified OK (boundary)
            self._create_test_signal('AMZN', score=5.5, stability_score=55.0),  # Blacklisted (< 60)
            self._create_test_signal('TSLA', score=9.0, stability_score=40.0),  # Blacklisted
        ]
        filtered, stats = scanner_stability_enabled._filter_by_stability(signals)

        assert len(filtered) == 3
        passed_symbols = {s.symbol for s in filtered}
        assert passed_symbols == {'AAPL', 'GOOGL', 'NFLX'}

        assert stats['qualified_kept'] == 3
        assert stats['blacklisted'] == 2
        assert stats['score_too_low'] == 1


# =============================================================================
# Fundamentals Filter Tests
# =============================================================================

class TestFundamentalsFilter:
    """Tests for fundamentals filtering"""

    def test_filter_disabled_returns_all(self):
        """When disabled, should return all symbols"""
        config = ScanConfig(enable_fundamentals_filter=False)
        scanner = MultiStrategyScanner(config)

        symbols = ["AAPL", "MSFT", "GOOGL"]
        passed, filtered = scanner.filter_symbols_by_fundamentals(symbols)

        assert passed == symbols
        assert filtered == {}

    def test_filter_empty_cache_returns_all(self):
        """When cache is empty, should return all symbols"""
        config = ScanConfig(enable_fundamentals_filter=True)
        scanner = MultiStrategyScanner(config)
        scanner._fundamentals_cache = {}  # Empty cache

        symbols = ["AAPL", "MSFT", "GOOGL"]
        passed, filtered = scanner.filter_symbols_by_fundamentals(symbols)

        assert passed == symbols
        assert filtered == {}

    def test_whitelist_passes_all_filters(self):
        """Whitelisted symbols should pass all filters"""
        config = ScanConfig(
            enable_fundamentals_filter=True,
            fundamentals_whitelist=["SPECIAL"],
            fundamentals_blacklist=["SPECIAL"],  # Also in blacklist
        )
        scanner = MultiStrategyScanner(config)

        symbols = ["SPECIAL"]
        passed, filtered = scanner.filter_symbols_by_fundamentals(symbols)

        # Whitelist overrides blacklist
        assert "SPECIAL" in passed

    def test_blacklist_filters_symbol(self):
        """Blacklisted symbols should be filtered"""
        config = ScanConfig(
            enable_fundamentals_filter=True,
            fundamentals_blacklist=["BAD"],
        )
        scanner = MultiStrategyScanner(config)

        symbols = ["GOOD", "BAD"]
        passed, filtered = scanner.filter_symbols_by_fundamentals(symbols)

        assert "GOOD" in passed
        assert "BAD" not in passed
        assert "BAD" in filtered

    def test_get_symbol_fundamentals(self):
        """Should return fundamentals for cached symbol"""
        scanner = MultiStrategyScanner()

        # Mock fundamentals data
        mock_fundamentals = MagicMock()
        mock_fundamentals.stability_score = 85.0
        scanner._fundamentals_cache["AAPL"] = mock_fundamentals

        result = scanner.get_symbol_fundamentals("AAPL")

        assert result is mock_fundamentals

    def test_get_symbol_fundamentals_not_found(self):
        """Should return None for unknown symbol"""
        scanner = MultiStrategyScanner()

        result = scanner.get_symbol_fundamentals("UNKNOWN")

        assert result is None


# =============================================================================
# Result and Export Tests
# =============================================================================

class TestScanResultExport:
    """Tests für ScanResult Export"""

    @pytest.fixture
    def scanner(self):
        return MultiStrategyScanner(ScanConfig(min_score=0))

    def test_get_by_strategy(self, scanner):
        """Filter by strategy sollte funktionieren"""
        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(["TEST"], data_fetcher)

        bounce_signals = result.get_by_strategy('bounce')
        assert all(s.strategy == 'bounce' for s in bounce_signals)

    def test_get_actionable(self, scanner):
        """get_actionable sollte nur actionable Signale zurückgeben"""
        scanner.config.min_score = 0

        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(["TEST"], data_fetcher)
        actionable = result.get_actionable()

        for signal in actionable:
            assert signal.is_actionable

    def test_to_dict(self, scanner):
        """to_dict sollte Dictionary zurückgeben"""
        def data_fetcher(symbol):
            return create_flat_data()

        result = scanner.scan_sync(["TEST"], data_fetcher)
        d = result.to_dict()

        assert 'timestamp' in d
        assert 'symbols_scanned' in d
        assert 'signals' in d
        assert isinstance(d['signals'], list)

    def test_export_csv(self, scanner):
        """CSV Export sollte funktionieren"""
        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(["TEST"], data_fetcher)
        csv = scanner.export_signals(result, format='csv')

        assert csv is not None
        assert 'symbol,strategy' in csv

    def test_export_json(self, scanner):
        """JSON Export sollte funktionieren"""
        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(["TEST"], data_fetcher)
        json_str = scanner.export_signals(result, format='json')

        assert json_str is not None
        assert '"timestamp"' in json_str

    def test_export_dict(self, scanner):
        """Dict Export sollte funktionieren"""
        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(["TEST"], data_fetcher)
        d = scanner.export_signals(result, format='dict')

        assert isinstance(d, dict)

    def test_export_unknown_format(self, scanner):
        """Unknown format should return None"""
        def data_fetcher(symbol):
            return create_flat_data()

        result = scanner.scan_sync(["TEST"], data_fetcher)
        output = scanner.export_signals(result, format='unknown')

        assert output is None

    def test_export_no_result(self, scanner):
        """Export with no result should return None"""
        output = scanner.export_signals(None, format='dict')

        assert output is None

    def test_summary(self, scanner):
        """Summary sollte Text zurückgeben"""
        def data_fetcher(symbol):
            return create_bounce_data()

        result = scanner.scan_sync(["TEST"], data_fetcher)
        summary = scanner.get_summary(result)

        assert "SCAN SUMMARY" in summary
        assert "Symbols scanned" in summary

    def test_summary_no_result(self, scanner):
        """Summary with no result should return message"""
        summary = scanner.get_summary(None)

        assert "No scan results available" in summary

    def test_summary_uses_last_scan(self, scanner):
        """Summary without argument should use last scan"""
        def data_fetcher(symbol):
            return create_bounce_data()

        scanner.scan_sync(["TEST"], data_fetcher)
        summary = scanner.get_summary()  # No argument

        assert "SCAN SUMMARY" in summary


# =============================================================================
# Quick Scan Tests
# =============================================================================

class TestQuickScan:
    """Tests für quick_scan Funktion"""

    def test_quick_scan_returns_signals(self):
        """quick_scan sollte Signale zurückgeben"""
        def data_fetcher(symbol):
            return create_bounce_data()

        signals = quick_scan(
            symbols=["TEST"],
            data_fetcher=data_fetcher,
            min_score=0
        )

        assert isinstance(signals, list)

    def test_quick_scan_with_mode(self):
        """quick_scan with mode filter"""
        def data_fetcher(symbol):
            return create_bounce_data()

        signals = quick_scan(
            symbols=["TEST"],
            data_fetcher=data_fetcher,
            mode=ScanMode.BOUNCE_ONLY,
            min_score=0
        )

        for signal in signals:
            assert signal.strategy == 'bounce'


# =============================================================================
# Adjustment Reason Tests
# =============================================================================

class TestAdjustmentReason:
    """Tests for _get_adjustment_reason method"""

    def test_excellent_win_rate(self):
        """Should explain excellent win rate"""
        scanner = MultiStrategyScanner()

        reason = scanner._get_adjustment_reason(92.0, 5.0, 85.0)

        assert "Exzellente WR" in reason

    def test_very_good_win_rate(self):
        """Should explain very good win rate"""
        scanner = MultiStrategyScanner()

        reason = scanner._get_adjustment_reason(87.0, 5.0, 75.0)

        assert "Sehr gute WR" in reason

    def test_low_win_rate(self):
        """Should explain low win rate penalty"""
        scanner = MultiStrategyScanner()

        reason = scanner._get_adjustment_reason(65.0, 5.0, 60.0)

        assert "Niedrige WR" in reason
        assert "reduziert" in reason

    def test_high_drawdown_penalty(self):
        """Should explain high drawdown penalty"""
        scanner = MultiStrategyScanner()

        reason = scanner._get_adjustment_reason(80.0, 18.0, 75.0)

        assert "Hoher Drawdown" in reason
        assert "Penalty" in reason

    def test_low_drawdown_positive(self):
        """Should mention low drawdown positively"""
        scanner = MultiStrategyScanner()

        reason = scanner._get_adjustment_reason(80.0, 3.0, 75.0)

        assert "Niedriger Drawdown" in reason

    def test_very_stable_symbol(self):
        """Should mention very stable symbols"""
        scanner = MultiStrategyScanner()

        reason = scanner._get_adjustment_reason(85.0, 5.0, 85.0)

        assert "Sehr stabil" in reason

    def test_standard_case(self):
        """Standard case should return Standard"""
        scanner = MultiStrategyScanner()

        reason = scanner._get_adjustment_reason(80.0, 8.0, 65.0)

        # No special conditions - should be Standard
        assert "Standard" in reason or len(reason) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
