# OptionPlay - Analyzer Pool Tests
# ==================================
# Tests für Object Pooling der Analyzer

import pytest
import threading
import time
from typing import List
from unittest.mock import MagicMock, patch

from src.analyzers.pool import (
    AnalyzerPool,
    PoolConfig,
    PoolStats,
    get_analyzer_pool,
    reset_analyzer_pool,
    configure_default_pool,
)
from src.analyzers.base import BaseAnalyzer
from src.analyzers.bounce import BounceAnalyzer, BounceConfig
from src.analyzers.trend_continuation import TrendContinuationAnalyzer, TrendContinuationConfig
from src.models.base import TradeSignal, SignalType, SignalStrength


class MockAnalyzer(BaseAnalyzer):
    """Mock Analyzer für Tests"""

    def __init__(self, name: str = "mock"):
        self._name = name
        self.analyze_count = 0

    @property
    def strategy_name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Mock analyzer for testing"

    def analyze(self, symbol: str, prices: List[float], volumes: List[int],
                highs: List[float], lows: List[float], **kwargs) -> TradeSignal:
        self.analyze_count += 1
        return TradeSignal(
            symbol=symbol,
            strategy=self.strategy_name,
            signal_type=SignalType.NEUTRAL,
            strength=SignalStrength.NONE,
            score=5.0,
            current_price=prices[-1] if prices else 0,
            reason="Mock analysis"
        )


class TestPoolConfig:
    """Tests für PoolConfig"""

    def test_default_values(self):
        config = PoolConfig()
        assert config.default_pool_size == 5
        assert config.max_pool_size == 20
        assert config.create_on_empty is True

    def test_strategy_pool_size_override(self):
        config = PoolConfig(
            default_pool_size=3,
            strategy_pool_sizes={"bounce": 10, "pullback": 5}
        )

        assert config.get_pool_size("bounce") == 10
        assert config.get_pool_size("pullback") == 5
        assert config.get_pool_size("unknown") == 3  # default


class TestPoolStats:
    """Tests für PoolStats"""

    def test_available_calculation(self):
        stats = PoolStats(strategy="test", pool_size=10, in_use=3)
        assert stats.available == 7

    def test_reuse_rate_empty(self):
        stats = PoolStats(strategy="test")
        assert stats.reuse_rate == 0.0

    def test_reuse_rate_calculation(self):
        stats = PoolStats(
            strategy="test",
            total_checkouts=100,
            total_reuses=75
        )
        assert stats.reuse_rate == 0.75

    def test_to_dict(self):
        stats = PoolStats(
            strategy="bounce",
            pool_size=5,
            in_use=2,
            total_checkouts=50,
            total_creates=10,
            total_reuses=40
        )
        result = stats.to_dict()

        assert result['strategy'] == "bounce"
        assert result['pool_size'] == 5
        assert result['in_use'] == 2
        assert result['available'] == 3
        assert result['reuse_rate'] == 0.8


class TestAnalyzerPool:
    """Tests für AnalyzerPool"""

    def setup_method(self):
        """Reset global pool before each test"""
        reset_analyzer_pool()

    def test_register_factory(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        assert "mock" in pool.registered_strategies

    def test_checkout_creates_analyzer(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        analyzer = pool.checkout("mock")

        assert analyzer is not None
        assert isinstance(analyzer, MockAnalyzer)
        assert analyzer.strategy_name == "mock"

    def test_checkin_returns_to_pool(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        analyzer1 = pool.checkout("mock")
        pool.checkin("mock", analyzer1)

        # Sollte dieselbe Instanz zurückbekommen
        analyzer2 = pool.checkout("mock")
        assert analyzer2 is analyzer1

    def test_multiple_checkouts(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        # Mehrere Analyzer auschecken
        analyzer1 = pool.checkout("mock")
        analyzer2 = pool.checkout("mock")

        # Sollten unterschiedliche Instanzen sein
        assert analyzer1 is not analyzer2

    def test_context_manager_acquire(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        with pool.acquire("mock") as analyzer:
            assert analyzer is not None
            assert analyzer.strategy_name == "mock"

        # Nach dem Context sollte der Analyzer im Pool sein
        stats = pool.stats("mock")
        assert stats['in_use'] == 0

    def test_context_manager_exception_safety(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        try:
            with pool.acquire("mock") as analyzer:
                raise ValueError("Test error")
        except ValueError:
            pass

        # Analyzer sollte trotzdem zurückgegeben worden sein
        stats = pool.stats("mock")
        assert stats['in_use'] == 0

    def test_prefill(self):
        pool = AnalyzerPool(PoolConfig(default_pool_size=5))
        pool.register_factory("mock", MockAnalyzer)

        created = pool.prefill("mock", count=3)

        assert created == 3
        stats = pool.stats("mock")
        assert stats['pool_size'] == 3
        assert stats['total_creates'] == 3

    def test_prefill_all(self):
        pool = AnalyzerPool(PoolConfig(default_pool_size=2))
        pool.register_factory("mock1", MockAnalyzer)
        pool.register_factory("mock2", lambda: MockAnalyzer("mock2"))

        result = pool.prefill_all()

        assert result["mock1"] == 2
        assert result["mock2"] == 2

    def test_clear_strategy(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)
        pool.prefill("mock", count=3)

        cleared = pool.clear("mock")

        assert cleared == 3
        stats = pool.stats("mock")
        assert stats['pool_size'] == 0

    def test_clear_all(self):
        pool = AnalyzerPool()
        pool.register_factory("mock1", MockAnalyzer)
        pool.register_factory("mock2", lambda: MockAnalyzer("mock2"))
        pool.prefill_all()

        cleared = pool.clear()

        assert cleared >= 2  # Mindestens die default_pool_size

    def test_stats(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        # Initial stats
        stats = pool.stats("mock")
        assert stats['total_checkouts'] == 0

        # Nach checkout
        analyzer = pool.checkout("mock")
        stats = pool.stats("mock")
        assert stats['total_checkouts'] == 1
        assert stats['in_use'] == 1

        # Nach checkin
        pool.checkin("mock", analyzer)
        stats = pool.stats("mock")
        assert stats['in_use'] == 0

    def test_stats_all(self):
        pool = AnalyzerPool()
        pool.register_factory("mock1", MockAnalyzer)
        pool.register_factory("mock2", lambda: MockAnalyzer("mock2"))

        pool.checkout("mock1")
        pool.checkout("mock2")

        stats = pool.stats()

        assert 'pools' in stats
        assert 'mock1' in stats['pools']
        assert 'mock2' in stats['pools']
        assert stats['total_in_use'] == 2

    def test_checkout_unknown_strategy_raises(self):
        pool = AnalyzerPool()

        with pytest.raises(KeyError):
            pool.checkout("unknown")

    def test_pool_respects_max_size(self):
        config = PoolConfig(default_pool_size=2, max_pool_size=2)
        pool = AnalyzerPool(config)
        pool.register_factory("mock", MockAnalyzer)

        # 3 Analyzer auschecken
        a1 = pool.checkout("mock")
        a2 = pool.checkout("mock")
        a3 = pool.checkout("mock")

        # Alle zurückgeben
        pool.checkin("mock", a1)
        pool.checkin("mock", a2)
        pool.checkin("mock", a3)  # Sollte verworfen werden

        # Pool sollte nur max_size Analyzer verfügbar haben (available)
        stats = pool.stats("mock")
        assert stats['available'] <= 2  # available = pool_size - in_use

    def test_register_analyzer_class(self):
        pool = AnalyzerPool()
        pool.register_analyzer_class("bounce", BounceAnalyzer, BounceConfig())

        with pool.acquire("bounce") as analyzer:
            assert isinstance(analyzer, BounceAnalyzer)


class TestAnalyzerPoolThreadSafety:
    """Thread-Safety Tests für AnalyzerPool"""

    def setup_method(self):
        reset_analyzer_pool()

    def test_concurrent_checkouts(self):
        """Teste parallele Checkouts"""
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)
        pool.prefill("mock", count=10)

        results = []
        errors = []

        def checkout_and_use():
            try:
                with pool.acquire("mock") as analyzer:
                    # Simuliere Arbeit
                    time.sleep(0.01)
                    analyzer.analyze(
                        "TEST",
                        [100.0, 101.0, 102.0] * 20,
                        [1000] * 60,
                        [101.0, 102.0, 103.0] * 20,
                        [99.0, 100.0, 101.0] * 20
                    )
                    results.append(analyzer.analyze_count)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=checkout_and_use) for _ in range(20)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 20

    def test_concurrent_stats_access(self):
        """Teste parallelen Stats-Zugriff"""
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        errors = []

        def access_stats():
            try:
                for _ in range(100):
                    pool.stats()
                    pool.stats("mock")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=access_stats) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0


class TestGlobalAnalyzerPool:
    """Tests für globale Pool-Instanz"""

    def setup_method(self):
        reset_analyzer_pool()

    def test_get_analyzer_pool_singleton(self):
        pool1 = get_analyzer_pool()
        pool2 = get_analyzer_pool()

        assert pool1 is pool2

    def test_reset_analyzer_pool(self):
        pool1 = get_analyzer_pool()
        pool1.register_factory("mock", MockAnalyzer)

        reset_analyzer_pool()

        pool2 = get_analyzer_pool()
        assert "mock" not in pool2.registered_strategies

    def test_configure_default_pool(self):
        pool = configure_default_pool()

        # Sollte Standard-Analyzer registriert haben
        strategies = pool.registered_strategies
        assert "pullback" in strategies or "bounce" in strategies


class TestAnalyzerPoolWithRealAnalyzers:
    """Integration Tests mit echten Analyzern"""

    def setup_method(self):
        reset_analyzer_pool()

    def test_bounce_analyzer_pool(self):
        pool = AnalyzerPool()
        pool.register_factory("bounce", lambda: BounceAnalyzer(BounceConfig()))

        # Test data (120+ for bounce lookback)
        prices = [100.0 + i * 0.1 for i in range(150)]
        volumes = [1000000] * 150
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        with pool.acquire("bounce") as analyzer:
            signal = analyzer.analyze(
                "TEST",
                prices,
                volumes,
                highs,
                lows
            )

            assert signal is not None
            assert signal.strategy == "bounce"

    def test_trend_continuation_analyzer_pool(self):
        pool = AnalyzerPool()
        pool.register_factory("trend_continuation", lambda: TrendContinuationAnalyzer(TrendContinuationConfig()))

        # Test data (250+ for SMA200 + slope lookback)
        prices = [100.0 + i * 0.1 for i in range(300)]
        volumes = [1000000] * 300
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        with pool.acquire("trend_continuation") as analyzer:
            signal = analyzer.analyze(
                "TEST",
                prices,
                volumes,
                highs,
                lows
            )

            assert signal is not None
            assert signal.strategy == "trend_continuation"

    def test_multiple_strategies(self):
        pool = configure_default_pool()

        prices = [100.0 + i * 0.1 for i in range(260)]
        volumes = [1000000] * 260
        highs = [p + 1 for p in prices]
        lows = [p - 1 for p in prices]

        signals = []

        for strategy in pool.registered_strategies:
            try:
                with pool.acquire(strategy) as analyzer:
                    signal = analyzer.analyze(
                        "TEST",
                        prices,
                        volumes,
                        highs,
                        lows
                    )
                    signals.append((strategy, signal))
            except Exception as e:
                # Some analyzers may fail with synthetic data
                pass

        # Mindestens einige sollten funktionieren
        assert len(signals) > 0


class TestAnalyzerPoolReuse:
    """Tests für Wiederverwendungseffizienz"""

    def setup_method(self):
        reset_analyzer_pool()

    def test_reuse_tracking(self):
        pool = AnalyzerPool()
        pool.register_factory("mock", MockAnalyzer)

        # Erster Checkout: create
        a1 = pool.checkout("mock")
        pool.checkin("mock", a1)

        # Zweiter Checkout: reuse
        a2 = pool.checkout("mock")
        pool.checkin("mock", a2)

        stats = pool.stats("mock")
        assert stats['total_creates'] == 1
        assert stats['total_reuses'] == 1
        assert stats['reuse_rate'] == 0.5  # 1 reuse / 2 checkouts

    def test_high_reuse_scenario(self):
        pool = AnalyzerPool(PoolConfig(default_pool_size=5))
        pool.register_factory("mock", MockAnalyzer)
        pool.prefill("mock", count=5)

        # Viele sequentielle Operationen
        for _ in range(100):
            with pool.acquire("mock") as analyzer:
                pass

        stats = pool.stats("mock")

        # Alle nach dem Prefill sollten Reuses sein
        assert stats['total_reuses'] == 100
        assert stats['reuse_rate'] > 0.9  # Hohe Wiederverwendung
