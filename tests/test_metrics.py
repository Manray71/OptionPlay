# Tests for Metrics Module
# ==========================

import json
import threading
import pytest

from src.utils.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    metrics,
)


class TestCounter:
    """Tests for Counter metric."""

    def test_basic_increment(self):
        """Test basic counter increment."""
        counter = Counter("test_counter", "Test counter")
        counter.inc()
        assert counter._value() == 1.0

    def test_increment_by_amount(self):
        """Test incrementing by specific amount."""
        counter = Counter("test_counter2", "Test counter")
        counter.inc(5)
        counter.inc(3)
        assert counter._value() == 8.0

    def test_increment_with_labels(self):
        """Test counter with labels."""
        counter = Counter("test_labeled", "Test", ["method"])
        counter.inc(labels={"method": "GET"})
        counter.inc(labels={"method": "GET"})
        counter.inc(labels={"method": "POST"})

        assert counter._value(labels={"method": "GET"}) == 2.0
        assert counter._value(labels={"method": "POST"}) == 1.0

    def test_negative_increment_raises(self):
        """Test that negative increment raises error."""
        counter = Counter("test_neg", "Test")
        with pytest.raises(ValueError):
            counter.inc(-1)

    def test_to_dict(self):
        """Test dictionary export."""
        counter = Counter("test_export", "Export test")
        counter.inc(5)
        result = counter.to_dict()

        assert result["name"] == "test_export"
        assert result["type"] == "counter"
        assert result["value"] == 5.0


class TestGauge:
    """Tests for Gauge metric."""

    def test_set_value(self):
        """Test setting gauge value."""
        gauge = Gauge("test_gauge", "Test gauge")
        gauge.set(42)
        assert gauge._value() == 42.0

    def test_increment_decrement(self):
        """Test increment and decrement."""
        gauge = Gauge("test_gauge2", "Test")
        gauge.set(10)
        gauge.inc(5)
        gauge.dec(3)
        assert gauge._value() == 12.0

    def test_with_labels(self):
        """Test gauge with labels."""
        gauge = Gauge("connections", "Active connections", ["service"])
        gauge.set(5, labels={"service": "api"})
        gauge.set(3, labels={"service": "db"})

        assert gauge._value(labels={"service": "api"}) == 5.0
        assert gauge._value(labels={"service": "db"}) == 3.0

    def test_to_dict(self):
        """Test dictionary export."""
        gauge = Gauge("test_export2", "Export test")
        gauge.set(100)
        result = gauge.to_dict()

        assert result["name"] == "test_export2"
        assert result["type"] == "gauge"
        assert result["value"] == 100


class TestHistogram:
    """Tests for Histogram metric."""

    def test_observe_single_value(self):
        """Test observing a single value."""
        hist = Histogram("latency", "Latency", buckets=(10, 50, 100))
        hist.observe(25)

        value = hist._value()
        assert value["count"] == 1
        assert value["sum"] == 25
        assert value["mean"] == 25

    def test_observe_multiple_values(self):
        """Test observing multiple values."""
        hist = Histogram("latency2", "Latency", buckets=(10, 50, 100))
        hist.observe(5)
        hist.observe(25)
        hist.observe(75)

        value = hist._value()
        assert value["count"] == 3
        assert value["sum"] == 105
        assert value["mean"] == 35

    def test_bucket_counts(self):
        """Test bucket counting."""
        hist = Histogram("latency3", "Latency", buckets=(10, 50, 100))
        hist.observe(5)   # <= 10, 50, 100
        hist.observe(25)  # <= 50, 100
        hist.observe(75)  # <= 100

        value = hist._value()
        assert value["buckets"][10] == 1
        assert value["buckets"][50] == 2
        assert value["buckets"][100] == 3

    def test_to_dict(self):
        """Test dictionary export."""
        hist = Histogram("test_hist", "Test histogram", buckets=(10, 100))
        hist.observe(50)
        result = hist.to_dict()

        assert result["name"] == "test_hist"
        assert result["type"] == "histogram"
        assert result["count"] == 1


class TestMetricsRegistry:
    """Tests for MetricsRegistry."""

    def test_register_and_get(self):
        """Test registering and getting metrics."""
        registry = MetricsRegistry()
        counter = Counter("my_counter", "My counter")
        registry.register(counter)

        retrieved = registry.get("my_counter")
        assert retrieved is counter

    def test_counter_factory(self):
        """Test counter factory method."""
        registry = MetricsRegistry()
        counter1 = registry.counter("requests", "Total requests")
        counter2 = registry.counter("requests", "Should return same")

        assert counter1 is counter2

    def test_gauge_factory(self):
        """Test gauge factory method."""
        registry = MetricsRegistry()
        gauge = registry.gauge("connections", "Active connections")

        assert isinstance(gauge, Gauge)
        assert registry.get("connections") is gauge

    def test_histogram_factory(self):
        """Test histogram factory method."""
        registry = MetricsRegistry()
        hist = registry.histogram("latency", "Request latency")

        assert isinstance(hist, Histogram)
        assert registry.get("latency") is hist

    def test_to_dict(self):
        """Test dictionary export."""
        registry = MetricsRegistry()
        registry.counter("counter1", "Counter 1").inc(5)
        registry.gauge("gauge1", "Gauge 1").set(10)

        result = registry.to_dict()

        assert "timestamp" in result
        assert "uptime_seconds" in result
        assert "metrics" in result
        assert "counter1" in result["metrics"]
        assert "gauge1" in result["metrics"]

    def test_to_json(self):
        """Test JSON export."""
        registry = MetricsRegistry()
        registry.counter("test", "Test").inc()

        json_str = registry.to_json()
        parsed = json.loads(json_str)

        assert "metrics" in parsed
        assert "test" in parsed["metrics"]

    def test_reset(self):
        """Test resetting registry."""
        registry = MetricsRegistry()
        registry.counter("test", "Test").inc()
        registry.reset()

        assert registry.get("test") is None


class TestThreadSafety:
    """Tests for thread safety."""

    def test_counter_thread_safety(self):
        """Test counter is thread-safe."""
        counter = Counter("thread_counter", "Thread test")

        def increment():
            for _ in range(1000):
                counter.inc()

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert counter._value() == 10000

    def test_gauge_thread_safety(self):
        """Test gauge is thread-safe."""
        gauge = Gauge("thread_gauge", "Thread test")

        def update():
            for i in range(100):
                gauge.set(i)
                gauge.inc()
                gauge.dec()

        threads = [threading.Thread(target=update) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash, value may vary

    def test_histogram_thread_safety(self):
        """Test histogram is thread-safe."""
        hist = Histogram("thread_hist", "Thread test", buckets=(10, 100, 1000))

        def observe():
            for i in range(100):
                hist.observe(i)

        threads = [threading.Thread(target=observe) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        value = hist._value()
        assert value["count"] == 1000


class TestGlobalMetrics:
    """Tests for global metrics instance."""

    def test_global_metrics_exist(self):
        """Test global metrics are defined."""
        from src.utils.metrics import (
            api_requests,
            api_latency,
            active_connections,
            cache_hits,
            errors,
        )

        assert isinstance(api_requests, Counter)
        assert isinstance(api_latency, Histogram)
        assert isinstance(active_connections, Gauge)
        assert isinstance(cache_hits, Counter)
        assert isinstance(errors, Counter)

    def test_global_registry(self):
        """Test global registry works."""
        # Reset for clean test
        metrics.reset()

        counter = metrics.counter("test_global", "Test")
        counter.inc(10)

        result = metrics.to_dict()
        assert "test_global" in result["metrics"]
        assert result["metrics"]["test_global"]["value"] == 10
