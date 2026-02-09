# OptionPlay - Metrics Collection
# =================================
# Simple metrics collection for observability.
#
# Features:
# - Counter, Gauge, Histogram metrics
# - Thread-safe implementation
# - JSON export for monitoring tools
# - Optional Prometheus-compatible format
#
# Usage:
#     from .metrics import metrics, Counter, Histogram
#
#     # Define metrics
#     api_calls = Counter("api_calls", "Total API calls", ["endpoint"])
#     latency = Histogram("latency_ms", "Request latency")
#
#     # Record metrics
#     api_calls.inc(labels={"endpoint": "quote"})
#     latency.observe(150.5)
#
#     # Export
#     print(metrics.to_json())

from __future__ import annotations

import json
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, cast


@dataclass
class MetricValue:
    """Base class for metric values."""
    name: str
    help_text: str
    labels: Dict[str, str] = field(default_factory=dict)


class Metric(ABC):
    """Abstract base class for metrics."""

    def __init__(self, name: str, help_text: str = "", label_names: Optional[List[str]] = None) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self._lock = threading.Lock()

    @abstractmethod
    def _value(self, labels: Optional[Dict[str, str]] = None) -> Any:
        """Get the current value."""
        pass

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Export as dictionary."""
        pass

    def _label_key(self, labels: Optional[Dict[str, str]] = None) -> Tuple:
        """Create a hashable key from labels."""
        if not labels:
            return ()
        return tuple(sorted(labels.items()))


class Counter(Metric):
    """
    Counter metric - only increases.

    Example:
        requests = Counter("http_requests", "Total HTTP requests", ["method"])
        requests.inc(labels={"method": "GET"})
        requests.inc(5, labels={"method": "POST"})
    """

    def __init__(self, name: str, help_text: str = "", label_names: Optional[List[str]] = None) -> None:
        super().__init__(name, help_text, label_names)
        self._values: Dict[Tuple, float] = defaultdict(float)

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment counter."""
        if amount < 0:
            raise ValueError("Counter can only increase")
        with self._lock:
            key = self._label_key(labels)
            self._values[key] += amount

    def _value(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current value."""
        key = self._label_key(labels)
        return self._values.get(key, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        """Export as dictionary."""
        with self._lock:
            if not self._values:
                return {"name": self.name, "type": "counter", "value": 0}

            if len(self._values) == 1 and () in self._values:
                return {
                    "name": self.name,
                    "type": "counter",
                    "help": self.help_text,
                    "value": self._values[()]
                }

            return {
                "name": self.name,
                "type": "counter",
                "help": self.help_text,
                "values": [
                    {"labels": dict(key), "value": val}
                    for key, val in self._values.items()
                ]
            }


class Gauge(Metric):
    """
    Gauge metric - can increase or decrease.

    Example:
        active_connections = Gauge("active_connections", "Current connections")
        active_connections.set(5)
        active_connections.inc()
        active_connections.dec()
    """

    def __init__(self, name: str, help_text: str = "", label_names: Optional[List[str]] = None) -> None:
        super().__init__(name, help_text, label_names)
        self._values: Dict[Tuple, float] = defaultdict(float)

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set gauge value."""
        with self._lock:
            key = self._label_key(labels)
            self._values[key] = value

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment gauge."""
        with self._lock:
            key = self._label_key(labels)
            self._values[key] += amount

    def dec(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Decrement gauge."""
        with self._lock:
            key = self._label_key(labels)
            self._values[key] -= amount

    def _value(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current value."""
        key = self._label_key(labels)
        return self._values.get(key, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        """Export as dictionary."""
        with self._lock:
            if not self._values:
                return {"name": self.name, "type": "gauge", "value": 0}

            if len(self._values) == 1 and () in self._values:
                return {
                    "name": self.name,
                    "type": "gauge",
                    "help": self.help_text,
                    "value": self._values[()]
                }

            return {
                "name": self.name,
                "type": "gauge",
                "help": self.help_text,
                "values": [
                    {"labels": dict(key), "value": val}
                    for key, val in self._values.items()
                ]
            }


class Histogram(Metric):
    """
    Histogram metric - tracks distribution of values.

    Example:
        latency = Histogram("request_latency_ms", "Request latency",
                           buckets=[10, 50, 100, 500, 1000])
        latency.observe(75.5)
    """

    DEFAULT_BUCKETS = (10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 10000)

    def __init__(
        self,
        name: str,
        help_text: str = "",
        label_names: Optional[List[str]] = None,
        buckets: Optional[Tuple[float, ...]] = None
    ) -> None:
        super().__init__(name, help_text, label_names)
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._counts: Dict[Tuple, Dict[float, int]] = defaultdict(
            lambda: {b: 0 for b in self.buckets}
        )
        self._sums: Dict[Tuple, float] = defaultdict(float)
        self._totals: Dict[Tuple, int] = defaultdict(int)

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record an observation."""
        with self._lock:
            key = self._label_key(labels)
            self._sums[key] += value
            self._totals[key] += 1

            for bucket in self.buckets:
                if value <= bucket:
                    self._counts[key][bucket] += 1

    def _value(self, labels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Get current statistics."""
        key = self._label_key(labels)
        total = self._totals.get(key, 0)
        return {
            "count": total,
            "sum": self._sums.get(key, 0),
            "mean": self._sums.get(key, 0) / total if total > 0 else 0,
            "buckets": dict(self._counts.get(key, {}))
        }

    def to_dict(self) -> Dict[str, Any]:
        """Export as dictionary."""
        with self._lock:
            if not self._totals:
                return {
                    "name": self.name,
                    "type": "histogram",
                    "count": 0,
                    "sum": 0,
                    "mean": 0
                }

            if len(self._totals) == 1 and () in self._totals:
                total = self._totals[()]
                return {
                    "name": self.name,
                    "type": "histogram",
                    "help": self.help_text,
                    "count": total,
                    "sum": self._sums[()],
                    "mean": self._sums[()] / total if total > 0 else 0,
                    "buckets": dict(self._counts[()])
                }

            return {
                "name": self.name,
                "type": "histogram",
                "help": self.help_text,
                "values": [
                    {
                        "labels": dict(key),
                        "count": self._totals[key],
                        "sum": self._sums[key],
                        "mean": self._sums[key] / self._totals[key] if self._totals[key] > 0 else 0,
                        "buckets": dict(self._counts[key])
                    }
                    for key in self._totals.keys()
                ]
            }


class MetricsRegistry:
    """
    Registry for all application metrics.

    Example:
        registry = MetricsRegistry()
        registry.register(Counter("requests", "Total requests"))
        print(registry.to_json())
    """

    def __init__(self) -> None:
        self._metrics: Dict[str, Metric] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

    def register(self, metric: Metric) -> Metric:
        """Register a metric."""
        with self._lock:
            if metric.name in self._metrics:
                return self._metrics[metric.name]
            self._metrics[metric.name] = metric
            return metric

    def get(self, name: str) -> Optional[Metric]:
        """Get a metric by name."""
        return self._metrics.get(name)

    def counter(self, name: str, help_text: str = "", label_names: Optional[List[str]] = None) -> Counter:
        """Create or get a counter."""
        with self._lock:
            if name in self._metrics:
                return cast(Counter, self._metrics[name])  # registered as Counter by prior call
            counter = Counter(name, help_text, label_names)
            self._metrics[name] = counter
            return counter

    def gauge(self, name: str, help_text: str = "", label_names: Optional[List[str]] = None) -> Gauge:
        """Create or get a gauge."""
        with self._lock:
            if name in self._metrics:
                return cast(Gauge, self._metrics[name])  # registered as Gauge by prior call
            gauge = Gauge(name, help_text, label_names)
            self._metrics[name] = gauge
            return gauge

    def histogram(
        self,
        name: str,
        help_text: str = "",
        label_names: Optional[List[str]] = None,
        buckets: Optional[Tuple[float, ...]] = None
    ) -> Histogram:
        """Create or get a histogram."""
        with self._lock:
            if name in self._metrics:
                return cast(Histogram, self._metrics[name])  # registered as Histogram by prior call
            histogram = Histogram(name, help_text, label_names, buckets)
            self._metrics[name] = histogram
            return histogram

    def to_dict(self) -> Dict[str, Any]:
        """Export all metrics as dictionary."""
        with self._lock:
            return {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "uptime_seconds": round(time.time() - self._start_time, 2),
                "metrics": {
                    name: metric.to_dict()
                    for name, metric in self._metrics.items()
                }
            }

    def to_json(self, indent: int = 2) -> str:
        """Export all metrics as JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._metrics.clear()
            self._start_time = time.time()


# Global metrics registry
metrics = MetricsRegistry()

# Pre-defined metrics for OptionPlay
api_requests = metrics.counter("api_requests_total", "Total API requests", ["endpoint", "status"])
api_latency = metrics.histogram("api_latency_ms", "API request latency in milliseconds", ["endpoint"])
active_connections = metrics.gauge("active_connections", "Number of active connections")
cache_hits = metrics.counter("cache_hits_total", "Cache hits", ["cache"])
cache_misses = metrics.counter("cache_misses_total", "Cache misses", ["cache"])
circuit_breaker_state = metrics.gauge("circuit_breaker_state", "Circuit breaker state (0=closed, 1=open, 0.5=half-open)", ["name"])
rate_limit_waits = metrics.counter("rate_limit_waits_total", "Times rate limiter caused waiting")
errors = metrics.counter("errors_total", "Total errors", ["type", "operation"])


__all__ = [
    'Metric',
    'Counter',
    'Gauge',
    'Histogram',
    'MetricsRegistry',
    'metrics',
    'api_requests',
    'api_latency',
    'active_connections',
    'cache_hits',
    'cache_misses',
    'circuit_breaker_state',
    'rate_limit_waits',
    'errors',
]
