# Tests for src/utils/metrics.py
# ================================
# Comprehensive unit tests for the metrics collection module.
# Tests cover Counter, Gauge, Histogram, MetricsRegistry, and global metrics.

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from src.utils.metrics import (
    Counter,
    Gauge,
    Histogram,
    Metric,
    MetricValue,
    MetricsRegistry,
    active_connections,
    api_latency,
    api_requests,
    cache_hits,
    cache_misses,
    circuit_breaker_state,
    errors,
    metrics,
    rate_limit_waits,
)


# =============================================================================
# MetricValue Tests
# =============================================================================


class TestMetricValue:
    """Tests for MetricValue dataclass."""

    def test_metric_value_creation(self):
        """Test creating a MetricValue with all fields."""
        mv = MetricValue(name="test_metric", help_text="A test metric", labels={"env": "prod"})
        assert mv.name == "test_metric"
        assert mv.help_text == "A test metric"
        assert mv.labels == {"env": "prod"}

    def test_metric_value_default_labels(self):
        """Test MetricValue with default empty labels."""
        mv = MetricValue(name="test", help_text="test")
        assert mv.labels == {}

    def test_metric_value_empty_labels(self):
        """Test MetricValue with explicitly empty labels."""
        mv = MetricValue(name="test", help_text="test", labels={})
        assert mv.labels == {}


# =============================================================================
# Counter Metric Tests
# =============================================================================


class TestCounter:
    """Comprehensive tests for Counter metric."""

    def test_counter_init(self):
        """Test counter initialization."""
        counter = Counter("test_counter", "A test counter", ["label1", "label2"])
        assert counter.name == "test_counter"
        assert counter.help_text == "A test counter"
        assert counter.label_names == ["label1", "label2"]

    def test_counter_init_no_labels(self):
        """Test counter initialization without labels."""
        counter = Counter("simple_counter")
        assert counter.name == "simple_counter"
        assert counter.help_text == ""
        assert counter.label_names == []

    def test_counter_basic_increment(self):
        """Test basic counter increment by 1."""
        counter = Counter("test")
        counter.inc()
        assert counter._value() == 1.0

    def test_counter_increment_by_amount(self):
        """Test counter increment by specific amount."""
        counter = Counter("test")
        counter.inc(5.5)
        assert counter._value() == 5.5

    def test_counter_multiple_increments(self):
        """Test multiple increments accumulate correctly."""
        counter = Counter("test")
        counter.inc(1)
        counter.inc(2)
        counter.inc(3)
        assert counter._value() == 6.0

    def test_counter_increment_by_zero(self):
        """Test incrementing by zero is allowed."""
        counter = Counter("test")
        counter.inc(0)
        assert counter._value() == 0.0

    def test_counter_negative_increment_raises(self):
        """Test that negative increment raises ValueError."""
        counter = Counter("test")
        with pytest.raises(ValueError, match="Counter can only increase"):
            counter.inc(-1)

    def test_counter_negative_increment_after_positive(self):
        """Test negative increment raises even after positive increments."""
        counter = Counter("test")
        counter.inc(10)
        with pytest.raises(ValueError, match="Counter can only increase"):
            counter.inc(-0.1)

    def test_counter_with_labels(self):
        """Test counter with multiple label combinations."""
        counter = Counter("requests", "HTTP requests", ["method", "status"])
        counter.inc(labels={"method": "GET", "status": "200"})
        counter.inc(labels={"method": "GET", "status": "200"})
        counter.inc(labels={"method": "POST", "status": "201"})
        counter.inc(labels={"method": "GET", "status": "404"})

        assert counter._value(labels={"method": "GET", "status": "200"}) == 2.0
        assert counter._value(labels={"method": "POST", "status": "201"}) == 1.0
        assert counter._value(labels={"method": "GET", "status": "404"}) == 1.0

    def test_counter_missing_label_returns_zero(self):
        """Test that querying non-existent label combination returns 0."""
        counter = Counter("test", "test", ["service"])
        counter.inc(labels={"service": "api"})
        assert counter._value(labels={"service": "db"}) == 0.0

    def test_counter_value_no_labels_returns_zero_when_empty(self):
        """Test _value returns 0 for empty counter."""
        counter = Counter("test")
        assert counter._value() == 0.0

    def test_counter_to_dict_empty(self):
        """Test to_dict for empty counter."""
        counter = Counter("empty_counter", "Empty")
        result = counter.to_dict()
        assert result == {"name": "empty_counter", "type": "counter", "value": 0}

    def test_counter_to_dict_simple_value(self):
        """Test to_dict for counter without labels."""
        counter = Counter("simple", "Simple counter")
        counter.inc(42)
        result = counter.to_dict()
        assert result["name"] == "simple"
        assert result["type"] == "counter"
        assert result["help"] == "Simple counter"
        assert result["value"] == 42.0

    def test_counter_to_dict_with_labels(self):
        """Test to_dict for counter with labels."""
        counter = Counter("labeled", "Labeled counter", ["env"])
        counter.inc(5, labels={"env": "prod"})
        counter.inc(3, labels={"env": "dev"})
        result = counter.to_dict()

        assert result["name"] == "labeled"
        assert result["type"] == "counter"
        assert "values" in result
        assert len(result["values"]) == 2

    def test_counter_label_key_ordering(self):
        """Test that label keys are properly sorted for consistent hashing."""
        counter = Counter("test", "test", ["a", "b", "c"])
        # Different ordering should result in same key
        counter.inc(labels={"c": "3", "a": "1", "b": "2"})
        counter.inc(labels={"a": "1", "b": "2", "c": "3"})
        assert counter._value(labels={"b": "2", "c": "3", "a": "1"}) == 2.0

    def test_counter_float_increment(self):
        """Test counter handles float increments correctly."""
        counter = Counter("test")
        counter.inc(0.1)
        counter.inc(0.2)
        assert abs(counter._value() - 0.3) < 1e-10

    def test_counter_large_increment(self):
        """Test counter handles large increments."""
        counter = Counter("test")
        counter.inc(1_000_000_000)
        counter.inc(500_000_000)
        assert counter._value() == 1_500_000_000


# =============================================================================
# Gauge Metric Tests
# =============================================================================


class TestGauge:
    """Comprehensive tests for Gauge metric."""

    def test_gauge_init(self):
        """Test gauge initialization."""
        gauge = Gauge("test_gauge", "A test gauge", ["label1"])
        assert gauge.name == "test_gauge"
        assert gauge.help_text == "A test gauge"
        assert gauge.label_names == ["label1"]

    def test_gauge_init_defaults(self):
        """Test gauge initialization with defaults."""
        gauge = Gauge("simple")
        assert gauge.name == "simple"
        assert gauge.help_text == ""
        assert gauge.label_names == []

    def test_gauge_set_value(self):
        """Test setting gauge value."""
        gauge = Gauge("test")
        gauge.set(42)
        assert gauge._value() == 42.0

    def test_gauge_set_overwrites(self):
        """Test that set overwrites previous value."""
        gauge = Gauge("test")
        gauge.set(10)
        gauge.set(20)
        assert gauge._value() == 20.0

    def test_gauge_set_negative(self):
        """Test gauge can be set to negative value."""
        gauge = Gauge("test")
        gauge.set(-100)
        assert gauge._value() == -100.0

    def test_gauge_set_zero(self):
        """Test gauge can be set to zero."""
        gauge = Gauge("test")
        gauge.set(100)
        gauge.set(0)
        assert gauge._value() == 0.0

    def test_gauge_increment(self):
        """Test gauge increment."""
        gauge = Gauge("test")
        gauge.set(10)
        gauge.inc()
        assert gauge._value() == 11.0

    def test_gauge_increment_by_amount(self):
        """Test gauge increment by specific amount."""
        gauge = Gauge("test")
        gauge.set(10)
        gauge.inc(5)
        assert gauge._value() == 15.0

    def test_gauge_increment_negative(self):
        """Test gauge can increment by negative amount (effectively decrement)."""
        gauge = Gauge("test")
        gauge.set(10)
        gauge.inc(-3)
        assert gauge._value() == 7.0

    def test_gauge_decrement(self):
        """Test gauge decrement."""
        gauge = Gauge("test")
        gauge.set(10)
        gauge.dec()
        assert gauge._value() == 9.0

    def test_gauge_decrement_by_amount(self):
        """Test gauge decrement by specific amount."""
        gauge = Gauge("test")
        gauge.set(10)
        gauge.dec(4)
        assert gauge._value() == 6.0

    def test_gauge_decrement_below_zero(self):
        """Test gauge can decrement below zero."""
        gauge = Gauge("test")
        gauge.set(5)
        gauge.dec(10)
        assert gauge._value() == -5.0

    def test_gauge_operations_chain(self):
        """Test chaining multiple operations."""
        gauge = Gauge("test")
        gauge.set(100)
        gauge.inc(50)
        gauge.dec(30)
        gauge.inc(20)
        gauge.dec(10)
        assert gauge._value() == 130.0

    def test_gauge_with_labels(self):
        """Test gauge with labels."""
        gauge = Gauge("connections", "Active connections", ["service"])
        gauge.set(5, labels={"service": "api"})
        gauge.set(3, labels={"service": "db"})
        gauge.inc(2, labels={"service": "api"})
        gauge.dec(1, labels={"service": "db"})

        assert gauge._value(labels={"service": "api"}) == 7.0
        assert gauge._value(labels={"service": "db"}) == 2.0

    def test_gauge_missing_label_returns_zero(self):
        """Test querying non-existent label returns 0."""
        gauge = Gauge("test", "test", ["env"])
        gauge.set(10, labels={"env": "prod"})
        assert gauge._value(labels={"env": "staging"}) == 0.0

    def test_gauge_to_dict_empty(self):
        """Test to_dict for empty gauge."""
        gauge = Gauge("empty", "Empty gauge")
        result = gauge.to_dict()
        assert result == {"name": "empty", "type": "gauge", "value": 0}

    def test_gauge_to_dict_simple(self):
        """Test to_dict for gauge without labels."""
        gauge = Gauge("simple", "Simple gauge")
        gauge.set(99)
        result = gauge.to_dict()
        assert result["name"] == "simple"
        assert result["type"] == "gauge"
        assert result["help"] == "Simple gauge"
        assert result["value"] == 99

    def test_gauge_to_dict_with_labels(self):
        """Test to_dict for gauge with labels."""
        gauge = Gauge("labeled", "Labeled gauge", ["region"])
        gauge.set(10, labels={"region": "us-east"})
        gauge.set(20, labels={"region": "eu-west"})
        result = gauge.to_dict()

        assert result["name"] == "labeled"
        assert result["type"] == "gauge"
        assert "values" in result
        assert len(result["values"]) == 2

    def test_gauge_float_operations(self):
        """Test gauge handles float operations correctly."""
        gauge = Gauge("test")
        gauge.set(10.5)
        gauge.inc(0.3)
        gauge.dec(0.1)
        assert abs(gauge._value() - 10.7) < 1e-10


# =============================================================================
# Histogram Metric Tests
# =============================================================================


class TestHistogram:
    """Comprehensive tests for Histogram metric."""

    def test_histogram_init_custom_buckets(self):
        """Test histogram initialization with custom buckets."""
        hist = Histogram("latency", "Latency", buckets=(10, 50, 100, 500))
        assert hist.name == "latency"
        assert hist.buckets == (10, 50, 100, 500)

    def test_histogram_init_default_buckets(self):
        """Test histogram initialization with default buckets."""
        hist = Histogram("latency", "Latency")
        assert hist.buckets == Histogram.DEFAULT_BUCKETS

    def test_histogram_default_buckets_value(self):
        """Test the actual default bucket values."""
        expected = (10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 10000)
        assert Histogram.DEFAULT_BUCKETS == expected

    def test_histogram_observe_single(self):
        """Test observing a single value."""
        hist = Histogram("test", "test", buckets=(10, 50, 100))
        hist.observe(25)

        value = hist._value()
        assert value["count"] == 1
        assert value["sum"] == 25
        assert value["mean"] == 25

    def test_histogram_observe_multiple(self):
        """Test observing multiple values."""
        hist = Histogram("test", "test", buckets=(10, 50, 100))
        hist.observe(10)
        hist.observe(20)
        hist.observe(30)
        hist.observe(40)
        hist.observe(50)

        value = hist._value()
        assert value["count"] == 5
        assert value["sum"] == 150
        assert value["mean"] == 30

    def test_histogram_bucket_counts(self):
        """Test bucket counting logic."""
        hist = Histogram("test", "test", buckets=(10, 50, 100))
        hist.observe(5)   # Falls into 10, 50, 100
        hist.observe(10)  # Falls into 10, 50, 100
        hist.observe(25)  # Falls into 50, 100
        hist.observe(75)  # Falls into 100
        hist.observe(200) # Falls into none (exceeds all)

        value = hist._value()
        assert value["buckets"][10] == 2
        assert value["buckets"][50] == 3
        assert value["buckets"][100] == 4

    def test_histogram_value_exactly_on_bucket_boundary(self):
        """Test value exactly on bucket boundary."""
        hist = Histogram("test", "test", buckets=(10, 50, 100))
        hist.observe(50)  # Should fall into 50 and 100

        value = hist._value()
        assert value["buckets"][10] == 0
        assert value["buckets"][50] == 1
        assert value["buckets"][100] == 1

    def test_histogram_value_above_all_buckets(self):
        """Test value exceeding all bucket boundaries."""
        hist = Histogram("test", "test", buckets=(10, 50, 100))
        hist.observe(1000)

        value = hist._value()
        assert value["count"] == 1
        assert value["sum"] == 1000
        # Value doesn't fall into any bucket (remains at 0)
        # The buckets dict will have 0 values for all buckets since no observation fell into them
        for bucket_limit, count in value["buckets"].items():
            assert count == 0, f"Bucket {bucket_limit} should be 0, got {count}"

    def test_histogram_negative_value(self):
        """Test histogram can observe negative values."""
        hist = Histogram("test", "test", buckets=(0, 10, 100))
        hist.observe(-50)

        value = hist._value()
        assert value["count"] == 1
        assert value["sum"] == -50
        # Negative value falls into all buckets
        assert value["buckets"][0] == 1
        assert value["buckets"][10] == 1
        assert value["buckets"][100] == 1

    def test_histogram_zero_value(self):
        """Test histogram with zero value."""
        hist = Histogram("test", "test", buckets=(0, 10, 100))
        hist.observe(0)

        value = hist._value()
        assert value["count"] == 1
        assert value["sum"] == 0
        assert value["buckets"][0] == 1

    def test_histogram_with_labels(self):
        """Test histogram with labels."""
        hist = Histogram("latency", "Latency", label_names=["endpoint"], buckets=(10, 100))
        hist.observe(5, labels={"endpoint": "/api"})
        hist.observe(50, labels={"endpoint": "/api"})
        hist.observe(200, labels={"endpoint": "/health"})

        api_value = hist._value(labels={"endpoint": "/api"})
        health_value = hist._value(labels={"endpoint": "/health"})

        assert api_value["count"] == 2
        assert api_value["sum"] == 55
        assert health_value["count"] == 1
        assert health_value["sum"] == 200

    def test_histogram_mean_calculation(self):
        """Test mean calculation accuracy."""
        hist = Histogram("test", "test", buckets=(10,))
        hist.observe(10)
        hist.observe(20)
        hist.observe(30)

        value = hist._value()
        assert value["mean"] == 20.0

    def test_histogram_mean_empty(self):
        """Test mean is 0 for empty histogram."""
        hist = Histogram("test", "test", buckets=(10,))
        value = hist._value()
        assert value["mean"] == 0

    def test_histogram_to_dict_empty(self):
        """Test to_dict for empty histogram."""
        hist = Histogram("empty", "Empty histogram", buckets=(10, 100))
        result = hist.to_dict()

        assert result["name"] == "empty"
        assert result["type"] == "histogram"
        assert result["count"] == 0
        assert result["sum"] == 0
        assert result["mean"] == 0

    def test_histogram_to_dict_simple(self):
        """Test to_dict for histogram without labels."""
        hist = Histogram("simple", "Simple histogram", buckets=(10, 100))
        hist.observe(50)
        result = hist.to_dict()

        assert result["name"] == "simple"
        assert result["type"] == "histogram"
        assert result["help"] == "Simple histogram"
        assert result["count"] == 1
        assert result["sum"] == 50
        assert result["mean"] == 50
        assert "buckets" in result

    def test_histogram_to_dict_with_labels(self):
        """Test to_dict for histogram with labels."""
        hist = Histogram("labeled", "Labeled", label_names=["method"], buckets=(10,))
        hist.observe(5, labels={"method": "GET"})
        hist.observe(15, labels={"method": "POST"})
        result = hist.to_dict()

        assert result["name"] == "labeled"
        assert result["type"] == "histogram"
        assert "values" in result
        assert len(result["values"]) == 2

    def test_histogram_float_observations(self):
        """Test histogram handles float observations."""
        hist = Histogram("test", "test", buckets=(10.5, 50.5, 100.5))
        hist.observe(10.25)
        hist.observe(50.25)

        value = hist._value()
        assert value["buckets"][10.5] == 1
        assert value["buckets"][50.5] == 2
        assert value["buckets"][100.5] == 2


# =============================================================================
# MetricsRegistry Tests
# =============================================================================


class TestMetricsRegistry:
    """Comprehensive tests for MetricsRegistry."""

    def test_registry_init(self):
        """Test registry initialization."""
        registry = MetricsRegistry()
        assert registry._metrics == {}
        assert registry._start_time > 0

    def test_registry_register_metric(self):
        """Test registering a metric."""
        registry = MetricsRegistry()
        counter = Counter("test", "Test counter")
        result = registry.register(counter)

        assert result is counter
        assert registry.get("test") is counter

    def test_registry_register_duplicate_returns_existing(self):
        """Test registering duplicate metric returns existing."""
        registry = MetricsRegistry()
        counter1 = Counter("test", "First")
        counter2 = Counter("test", "Second")

        registry.register(counter1)
        result = registry.register(counter2)

        assert result is counter1
        assert registry.get("test") is counter1

    def test_registry_get_nonexistent(self):
        """Test getting non-existent metric returns None."""
        registry = MetricsRegistry()
        assert registry.get("nonexistent") is None

    def test_registry_counter_factory(self):
        """Test counter factory method."""
        registry = MetricsRegistry()
        counter = registry.counter("requests", "Total requests", ["method"])

        assert isinstance(counter, Counter)
        assert counter.name == "requests"
        assert counter.help_text == "Total requests"
        assert counter.label_names == ["method"]
        assert registry.get("requests") is counter

    def test_registry_counter_factory_returns_existing(self):
        """Test counter factory returns existing metric."""
        registry = MetricsRegistry()
        counter1 = registry.counter("test", "First")
        counter2 = registry.counter("test", "Second")

        assert counter1 is counter2

    def test_registry_gauge_factory(self):
        """Test gauge factory method."""
        registry = MetricsRegistry()
        gauge = registry.gauge("temperature", "Current temperature", ["location"])

        assert isinstance(gauge, Gauge)
        assert gauge.name == "temperature"
        assert registry.get("temperature") is gauge

    def test_registry_gauge_factory_returns_existing(self):
        """Test gauge factory returns existing metric."""
        registry = MetricsRegistry()
        gauge1 = registry.gauge("test", "First")
        gauge2 = registry.gauge("test", "Second")

        assert gauge1 is gauge2

    def test_registry_histogram_factory(self):
        """Test histogram factory method."""
        registry = MetricsRegistry()
        hist = registry.histogram(
            "latency", "Request latency", ["endpoint"], buckets=(10, 100, 1000)
        )

        assert isinstance(hist, Histogram)
        assert hist.name == "latency"
        assert hist.buckets == (10, 100, 1000)
        assert registry.get("latency") is hist

    def test_registry_histogram_factory_returns_existing(self):
        """Test histogram factory returns existing metric."""
        registry = MetricsRegistry()
        hist1 = registry.histogram("test", "First")
        hist2 = registry.histogram("test", "Second")

        assert hist1 is hist2

    def test_registry_histogram_factory_default_buckets(self):
        """Test histogram factory uses default buckets."""
        registry = MetricsRegistry()
        hist = registry.histogram("test", "Test")
        assert hist.buckets == Histogram.DEFAULT_BUCKETS

    def test_registry_to_dict_empty(self):
        """Test to_dict for empty registry."""
        registry = MetricsRegistry()
        result = registry.to_dict()

        assert "timestamp" in result
        assert "uptime_seconds" in result
        assert "metrics" in result
        assert result["metrics"] == {}

    def test_registry_to_dict_with_metrics(self):
        """Test to_dict with registered metrics."""
        registry = MetricsRegistry()
        registry.counter("counter1", "Counter 1").inc(5)
        registry.gauge("gauge1", "Gauge 1").set(10)
        registry.histogram("hist1", "Histogram 1", buckets=(10,)).observe(5)

        result = registry.to_dict()

        assert "counter1" in result["metrics"]
        assert "gauge1" in result["metrics"]
        assert "hist1" in result["metrics"]

    def test_registry_to_dict_timestamp_format(self):
        """Test timestamp is in ISO format with Z suffix."""
        registry = MetricsRegistry()
        result = registry.to_dict()

        assert result["timestamp"].endswith("Z")
        assert "T" in result["timestamp"]

    def test_registry_to_dict_uptime(self):
        """Test uptime calculation."""
        registry = MetricsRegistry()
        time.sleep(0.1)
        result = registry.to_dict()

        assert result["uptime_seconds"] >= 0.1

    def test_registry_to_json(self):
        """Test JSON export."""
        registry = MetricsRegistry()
        registry.counter("test", "Test").inc()

        json_str = registry.to_json()
        parsed = json.loads(json_str)

        assert "metrics" in parsed
        assert "test" in parsed["metrics"]

    def test_registry_to_json_indent(self):
        """Test JSON export with custom indent."""
        registry = MetricsRegistry()
        registry.counter("test", "Test").inc()

        json_str = registry.to_json(indent=4)
        # Check that it's properly indented (has 4 spaces)
        assert "    " in json_str

    def test_registry_reset(self):
        """Test resetting registry."""
        registry = MetricsRegistry()
        registry.counter("test1", "Test 1").inc()
        registry.gauge("test2", "Test 2").set(10)

        registry.reset()

        assert registry.get("test1") is None
        assert registry.get("test2") is None
        assert registry._metrics == {}

    def test_registry_reset_resets_start_time(self):
        """Test reset also resets start time."""
        registry = MetricsRegistry()
        old_start = registry._start_time
        time.sleep(0.1)

        registry.reset()

        assert registry._start_time > old_start


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Tests for thread safety of metrics classes."""

    def test_counter_concurrent_increments(self):
        """Test counter is thread-safe under concurrent increments."""
        counter = Counter("concurrent", "Concurrent counter")
        num_threads = 10
        increments_per_thread = 1000

        def increment():
            for _ in range(increments_per_thread):
                counter.inc()

        threads = [threading.Thread(target=increment) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert counter._value() == num_threads * increments_per_thread

    def test_counter_concurrent_increments_with_labels(self):
        """Test counter with labels is thread-safe."""
        counter = Counter("concurrent", "Concurrent counter", ["label"])
        num_threads = 5

        def increment(label_value):
            for _ in range(100):
                counter.inc(labels={"label": label_value})

        threads = [
            threading.Thread(target=increment, args=(f"val{i}",))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = sum(counter._value(labels={"label": f"val{i}"}) for i in range(num_threads))
        assert total == num_threads * 100

    def test_gauge_concurrent_operations(self):
        """Test gauge is thread-safe under concurrent operations."""
        gauge = Gauge("concurrent", "Concurrent gauge")
        num_threads = 10

        def operate():
            for i in range(100):
                gauge.set(i)
                gauge.inc()
                gauge.dec()

        threads = [threading.Thread(target=operate) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Just verify no exceptions occurred and value is reasonable
        assert isinstance(gauge._value(), float)

    def test_histogram_concurrent_observations(self):
        """Test histogram is thread-safe under concurrent observations."""
        hist = Histogram("concurrent", "Concurrent histogram", buckets=(10, 100, 1000))
        num_threads = 10
        observations_per_thread = 100

        def observe():
            for i in range(observations_per_thread):
                hist.observe(i)

        threads = [threading.Thread(target=observe) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        value = hist._value()
        assert value["count"] == num_threads * observations_per_thread

    def test_registry_concurrent_access(self):
        """Test registry is thread-safe under concurrent access."""
        registry = MetricsRegistry()

        def create_metrics(prefix):
            for i in range(10):
                registry.counter(f"{prefix}_counter_{i}", f"Counter {i}").inc()
                registry.gauge(f"{prefix}_gauge_{i}", f"Gauge {i}").set(i)
                registry.histogram(f"{prefix}_hist_{i}", f"Histogram {i}", buckets=(10,)).observe(i)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_metrics, f"thread{i}") for i in range(5)]
            for future in futures:
                future.result()

        # Should have 5 threads * 10 metrics * 3 types = 150 metrics
        assert len(registry._metrics) == 150

    def test_registry_concurrent_to_dict(self):
        """Test to_dict is thread-safe during concurrent modifications."""
        registry = MetricsRegistry()

        def modify():
            for i in range(50):
                registry.counter(f"counter_{threading.current_thread().name}_{i}", "").inc()

        def read():
            for _ in range(20):
                registry.to_dict()
                time.sleep(0.001)

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=modify))
            threads.append(threading.Thread(target=read))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors


# =============================================================================
# Global Metrics Tests
# =============================================================================


class TestGlobalMetrics:
    """Tests for global metrics instance and pre-defined metrics."""

    def test_global_registry_is_metrics_registry(self):
        """Test global metrics is a MetricsRegistry instance."""
        assert isinstance(metrics, MetricsRegistry)

    def test_api_requests_counter(self):
        """Test api_requests counter is properly configured."""
        assert isinstance(api_requests, Counter)
        assert api_requests.name == "api_requests_total"
        assert api_requests.label_names == ["endpoint", "status"]

    def test_api_latency_histogram(self):
        """Test api_latency histogram is properly configured."""
        assert isinstance(api_latency, Histogram)
        assert api_latency.name == "api_latency_ms"
        assert api_latency.label_names == ["endpoint"]

    def test_active_connections_gauge(self):
        """Test active_connections gauge is properly configured."""
        assert isinstance(active_connections, Gauge)
        assert active_connections.name == "active_connections"

    def test_cache_hits_counter(self):
        """Test cache_hits counter is properly configured."""
        assert isinstance(cache_hits, Counter)
        assert cache_hits.name == "cache_hits_total"
        assert cache_hits.label_names == ["cache"]

    def test_cache_misses_counter(self):
        """Test cache_misses counter is properly configured."""
        assert isinstance(cache_misses, Counter)
        assert cache_misses.name == "cache_misses_total"
        assert cache_misses.label_names == ["cache"]

    def test_circuit_breaker_state_gauge(self):
        """Test circuit_breaker_state gauge is properly configured."""
        assert isinstance(circuit_breaker_state, Gauge)
        assert circuit_breaker_state.name == "circuit_breaker_state"
        assert circuit_breaker_state.label_names == ["name"]

    def test_rate_limit_waits_counter(self):
        """Test rate_limit_waits counter is properly configured."""
        assert isinstance(rate_limit_waits, Counter)
        assert rate_limit_waits.name == "rate_limit_waits_total"

    def test_errors_counter(self):
        """Test errors counter is properly configured."""
        assert isinstance(errors, Counter)
        assert errors.name == "errors_total"
        assert errors.label_names == ["type", "operation"]

    def test_global_metrics_usage(self):
        """Test using global metrics in a realistic scenario."""
        # Reset for clean test
        metrics.reset()

        # Re-register the metrics after reset
        test_counter = metrics.counter("test_api_calls", "Test API calls", ["endpoint"])
        test_latency = metrics.histogram("test_latency", "Test latency", ["endpoint"])
        test_connections = metrics.gauge("test_connections", "Test connections")

        # Simulate API usage
        test_counter.inc(labels={"endpoint": "/quote"})
        test_counter.inc(labels={"endpoint": "/quote"})
        test_counter.inc(labels={"endpoint": "/scan"})
        test_latency.observe(50, labels={"endpoint": "/quote"})
        test_latency.observe(200, labels={"endpoint": "/scan"})
        test_connections.set(5)

        result = metrics.to_dict()

        assert "test_api_calls" in result["metrics"]
        assert "test_latency" in result["metrics"]
        assert "test_connections" in result["metrics"]


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_labels_dict_same_as_none(self):
        """Test empty labels dict is same as None."""
        counter = Counter("test", "test", ["label"])
        counter.inc(labels={})
        counter.inc(labels=None)
        counter.inc()

        assert counter._value(labels={}) == 3.0
        assert counter._value(labels=None) == 3.0
        assert counter._value() == 3.0

    def test_label_key_with_special_characters(self):
        """Test labels with special characters."""
        counter = Counter("test", "test", ["path"])
        counter.inc(labels={"path": "/api/v1/quote?symbol=AAPL"})
        counter.inc(labels={"path": "/api/v1/quote?symbol=AAPL"})

        assert counter._value(labels={"path": "/api/v1/quote?symbol=AAPL"}) == 2.0

    def test_label_with_unicode(self):
        """Test labels with unicode characters."""
        counter = Counter("test", "test", ["name"])
        counter.inc(labels={"name": "test"})

        assert counter._value(labels={"name": "test"}) == 1.0

    def test_metric_with_very_long_name(self):
        """Test metric with very long name."""
        long_name = "a" * 1000
        counter = Counter(long_name, "Test")
        counter.inc()

        assert counter.name == long_name
        assert counter._value() == 1.0

    def test_counter_very_large_number(self):
        """Test counter with very large numbers."""
        counter = Counter("test", "test")
        counter.inc(10**15)
        counter.inc(10**15)

        assert counter._value() == 2 * 10**15

    def test_histogram_very_small_values(self):
        """Test histogram with very small values."""
        hist = Histogram("test", "test", buckets=(0.001, 0.01, 0.1))
        hist.observe(0.0001)
        hist.observe(0.005)
        hist.observe(0.05)

        value = hist._value()
        assert value["buckets"][0.001] == 1
        assert value["buckets"][0.01] == 2
        assert value["buckets"][0.1] == 3

    def test_gauge_rapid_updates(self):
        """Test gauge handles rapid updates correctly."""
        gauge = Gauge("test", "test")

        for i in range(10000):
            gauge.set(i)

        assert gauge._value() == 9999.0

    def test_registry_get_after_reset(self):
        """Test getting metrics after registry reset."""
        registry = MetricsRegistry()
        registry.counter("test", "test").inc()
        registry.reset()

        assert registry.get("test") is None
        # Creating new metric after reset should work
        new_counter = registry.counter("test", "test")
        new_counter.inc()
        assert new_counter._value() == 1.0


# =============================================================================
# Label Key Tests
# =============================================================================


class TestLabelKey:
    """Tests for label key generation and handling."""

    def test_label_key_empty(self):
        """Test label key for empty/None labels."""
        counter = Counter("test", "test")
        assert counter._label_key(None) == ()
        assert counter._label_key({}) == ()

    def test_label_key_single_label(self):
        """Test label key for single label."""
        counter = Counter("test", "test", ["method"])
        key = counter._label_key({"method": "GET"})
        assert key == (("method", "GET"),)

    def test_label_key_multiple_labels_sorted(self):
        """Test label keys are sorted for consistency."""
        counter = Counter("test", "test", ["a", "b", "c"])

        # Different orderings should produce same key
        key1 = counter._label_key({"c": "3", "a": "1", "b": "2"})
        key2 = counter._label_key({"a": "1", "b": "2", "c": "3"})
        key3 = counter._label_key({"b": "2", "c": "3", "a": "1"})

        assert key1 == key2 == key3
        assert key1 == (("a", "1"), ("b", "2"), ("c", "3"))


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Tests for module __all__ exports."""

    def test_all_exports(self):
        """Test all expected items are exported."""
        from src.utils.metrics import (
            Counter,
            Gauge,
            Histogram,
            Metric,
            MetricsRegistry,
            active_connections,
            api_latency,
            api_requests,
            cache_hits,
            cache_misses,
            circuit_breaker_state,
            errors,
            metrics,
            rate_limit_waits,
        )

        # Verify types
        assert Metric is not None
        assert Counter is not None
        assert Gauge is not None
        assert Histogram is not None
        assert MetricsRegistry is not None
        assert isinstance(metrics, MetricsRegistry)
        assert isinstance(api_requests, Counter)
        assert isinstance(api_latency, Histogram)
        assert isinstance(active_connections, Gauge)
        assert isinstance(cache_hits, Counter)
        assert isinstance(cache_misses, Counter)
        assert isinstance(circuit_breaker_state, Gauge)
        assert isinstance(rate_limit_waits, Counter)
        assert isinstance(errors, Counter)

    def test_metric_abstract_base_class(self):
        """Test Metric is abstract base class."""
        # Cannot instantiate abstract class directly
        with pytest.raises(TypeError):
            Metric("test", "test")


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for realistic usage scenarios."""

    def test_api_monitoring_scenario(self):
        """Test realistic API monitoring scenario."""
        registry = MetricsRegistry()

        # Set up metrics
        requests = registry.counter("http_requests", "Total requests", ["method", "endpoint", "status"])
        latency = registry.histogram("http_latency_ms", "Request latency", ["endpoint"], buckets=(50, 100, 250, 500, 1000))
        active = registry.gauge("active_requests", "Active requests")

        # Simulate API traffic
        endpoints = ["/quote", "/scan", "/analyze"]
        methods = ["GET", "POST"]

        for _ in range(100):
            for endpoint in endpoints:
                for method in methods:
                    # Record request
                    active.inc()
                    requests.inc(labels={"method": method, "endpoint": endpoint, "status": "200"})
                    latency.observe(75 + hash(endpoint) % 100, labels={"endpoint": endpoint})
                    active.dec()

        # Verify metrics
        result = registry.to_dict()
        assert "http_requests" in result["metrics"]
        assert "http_latency_ms" in result["metrics"]
        assert "active_requests" in result["metrics"]

        # Check request counts
        req_dict = requests.to_dict()
        assert "values" in req_dict

        # Check latency statistics - histogram with labels uses "values" key
        lat_dict = latency.to_dict()
        assert "values" in lat_dict
        # Each endpoint has observations
        total_observations = sum(v["count"] for v in lat_dict["values"])
        assert total_observations > 0

        # Active requests should be back to 0
        assert active._value() == 0.0

    def test_cache_metrics_scenario(self):
        """Test realistic cache metrics scenario."""
        registry = MetricsRegistry()

        hits = registry.counter("cache_hits", "Cache hits", ["cache_name"])
        misses = registry.counter("cache_misses", "Cache misses", ["cache_name"])
        size = registry.gauge("cache_size", "Cache size", ["cache_name"])

        caches = ["quote", "options", "historical"]

        # Simulate cache operations
        for cache in caches:
            for i in range(50):
                if i % 3 == 0:
                    misses.inc(labels={"cache_name": cache})
                else:
                    hits.inc(labels={"cache_name": cache})
            size.set(1000 + hash(cache) % 500, labels={"cache_name": cache})

        # Calculate hit rates per cache
        for cache in caches:
            hit_count = hits._value(labels={"cache_name": cache})
            miss_count = misses._value(labels={"cache_name": cache})
            hit_rate = hit_count / (hit_count + miss_count) * 100
            assert hit_rate > 60  # Should be about 66%

    def test_json_roundtrip(self):
        """Test JSON export can be parsed and used."""
        registry = MetricsRegistry()

        registry.counter("counter1", "Test counter").inc(10)
        registry.gauge("gauge1", "Test gauge").set(42)
        registry.histogram("hist1", "Test histogram", buckets=(10, 100)).observe(50)

        # Export to JSON
        json_str = registry.to_json()

        # Parse JSON
        data = json.loads(json_str)

        # Verify structure
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "metrics" in data

        # Verify counter
        assert data["metrics"]["counter1"]["value"] == 10
        assert data["metrics"]["counter1"]["type"] == "counter"

        # Verify gauge
        assert data["metrics"]["gauge1"]["value"] == 42
        assert data["metrics"]["gauge1"]["type"] == "gauge"

        # Verify histogram
        assert data["metrics"]["hist1"]["count"] == 1
        assert data["metrics"]["hist1"]["type"] == "histogram"
