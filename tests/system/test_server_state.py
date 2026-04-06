# OptionPlay - Server State Tests
# =================================
"""
Tests für die neuen State-Management Objekte.

Testet:
- ConnectionState State Machine
- VIXState mit Staleness Detection
- CacheMetrics
- ServerState Composition
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.state import (
    ServerState,
    ConnectionState,
    VIXState,
    CacheMetrics,
    ConnectionStatus,
)


class TestConnectionState:
    """Tests für ConnectionState State Machine."""

    def test_initial_state(self):
        """Initial state should be DISCONNECTED."""
        state = ConnectionState()
        assert state.status == ConnectionStatus.DISCONNECTED
        assert not state.is_connected
        assert state.consecutive_failures == 0
        assert state.last_error is None

    def test_mark_connecting(self):
        """mark_connecting should transition to CONNECTING."""
        state = ConnectionState()
        state.mark_connecting()

        assert state.status == ConnectionStatus.CONNECTING
        assert state.is_connecting
        assert state.last_attempt_at is not None

    def test_mark_connected(self):
        """mark_connected should transition to CONNECTED and reset failures."""
        state = ConnectionState()
        state.consecutive_failures = 3
        state.last_error = "previous error"

        state.mark_connected()

        assert state.status == ConnectionStatus.CONNECTED
        assert state.is_connected
        assert state.consecutive_failures == 0
        assert state.last_error is None
        assert state.last_connected_at is not None

    def test_mark_failed(self):
        """mark_failed should increment failures and store error."""
        state = ConnectionState()

        state.mark_failed("Connection timeout")

        assert state.status == ConnectionStatus.FAILED
        assert state.is_failed
        assert state.consecutive_failures == 1
        assert state.last_error == "Connection timeout"

        # Second failure
        state.mark_failed("Another error")
        assert state.consecutive_failures == 2
        assert state.last_error == "Another error"

    def test_mark_disconnected(self):
        """mark_disconnected should transition to DISCONNECTED."""
        state = ConnectionState()
        state.mark_connected()

        state.mark_disconnected()

        assert state.status == ConnectionStatus.DISCONNECTED
        assert not state.is_connected

    def test_reconnect_increments_total(self):
        """Reconnecting from CONNECTED should increment total_reconnects."""
        state = ConnectionState()
        state.mark_connected()
        assert state.total_reconnects == 0

        # Reconnect
        state.mark_connecting()
        assert state.status == ConnectionStatus.RECONNECTING
        assert state.total_reconnects == 1

    def test_can_attempt_connection(self):
        """can_attempt_connection should be False during connection attempts."""
        state = ConnectionState()

        assert state.can_attempt_connection  # DISCONNECTED
        state.mark_connecting()
        assert not state.can_attempt_connection  # CONNECTING

        state.mark_connected()
        assert state.can_attempt_connection  # CONNECTED

        state.mark_connecting()
        assert not state.can_attempt_connection  # RECONNECTING

    def test_uptime_seconds(self):
        """uptime_seconds should return time since connection."""
        state = ConnectionState()
        assert state.uptime_seconds is None

        state.mark_connected()
        assert state.uptime_seconds is not None
        assert state.uptime_seconds >= 0

    def test_reset(self):
        """reset should clear all state except total_reconnects."""
        state = ConnectionState()
        state.mark_connected()
        state.mark_connecting()  # Becomes RECONNECTING
        state.mark_failed("error")

        state.reset()

        assert state.status == ConnectionStatus.DISCONNECTED
        assert state.consecutive_failures == 0
        assert state.last_error is None
        assert state.last_connected_at is None
        assert state.total_reconnects == 1  # Preserved

    def test_to_dict(self):
        """to_dict should return serializable representation."""
        state = ConnectionState()
        state.mark_connected()

        data = state.to_dict()

        assert isinstance(data, dict)
        assert data["status"] == "connected"
        assert data["is_connected"] is True
        assert "last_connected_at" in data
        assert "uptime_seconds" in data


class TestVIXState:
    """Tests für VIXState mit Staleness Detection."""

    def test_initial_state(self):
        """Initial state should be stale with no value."""
        state = VIXState()
        assert state.current_value is None
        assert state.is_stale
        assert state.regime is None

    def test_update(self):
        """update should set value and auto-detect regime."""
        state = VIXState()

        state.update(18.5)

        assert state.current_value == 18.5
        assert state.updated_at is not None
        assert not state.is_stale

    def test_regime_detection(self):
        """update should auto-detect correct regime from VIX value."""
        state = VIXState()

        # Low vol
        state.update(12.0)
        assert state.regime.value == "LOW_VOL"

        # Standard
        state.update(17.0)
        assert state.regime.value == "NORMAL"

        # Elevated
        state.update(25.0)
        assert state.regime.value == "ELEVATED"

        # High vol
        state.update(35.0)
        assert state.regime.value == "HIGH_VOL"

    def test_staleness(self):
        """is_stale should be True after threshold."""
        state = VIXState(stale_threshold_seconds=1)
        state.update(18.0)

        assert not state.is_stale

        # Simulate time passing
        state.updated_at = datetime.now() - timedelta(seconds=2)
        assert state.is_stale

    def test_change_pct(self):
        """change_pct should calculate percentage change."""
        state = VIXState()

        state.update(20.0)
        assert state.change_pct is None  # No previous

        state.update(22.0)
        assert state.change_pct == pytest.approx(10.0)  # 20 -> 22 = +10%

        state.update(20.0)
        assert state.change_pct == pytest.approx(-9.09, rel=0.01)  # 22 -> 20

    def test_invalidate(self):
        """invalidate should make state stale."""
        state = VIXState()
        state.update(18.0)

        state.invalidate()

        assert state.is_stale
        assert state.current_value == 18.0  # Value preserved

    def test_age_seconds(self):
        """age_seconds should return time since update."""
        state = VIXState()
        assert state.age_seconds is None

        state.update(18.0)
        assert state.age_seconds is not None
        assert state.age_seconds >= 0

    def test_to_dict(self):
        """to_dict should return serializable representation."""
        state = VIXState()
        state.update(18.5)

        data = state.to_dict()

        assert isinstance(data, dict)
        assert data["current_value"] == 18.5
        assert "is_stale" in data
        assert "regime" in data


class TestCacheMetrics:
    """Tests für CacheMetrics."""

    def test_initial_state(self):
        """Initial state should have zero counts."""
        metrics = CacheMetrics(name="test")

        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.hit_rate == 0.0

    def test_record_hit(self):
        """record_hit should increment hits."""
        metrics = CacheMetrics(name="test")

        metrics.record_hit()
        metrics.record_hit()

        assert metrics.hits == 2
        assert metrics.total_requests == 2

    def test_record_miss(self):
        """record_miss should increment misses."""
        metrics = CacheMetrics(name="test")

        metrics.record_miss()

        assert metrics.misses == 1

    def test_hit_rate(self):
        """hit_rate should calculate correct percentage."""
        metrics = CacheMetrics(name="test")

        # 8 hits, 2 misses = 80% hit rate
        for _ in range(8):
            metrics.record_hit()
        for _ in range(2):
            metrics.record_miss()

        assert metrics.hit_rate == pytest.approx(0.8)
        assert metrics.hit_rate_pct == pytest.approx(80.0)
        assert metrics.miss_rate == pytest.approx(0.2)

    def test_fill_rate(self):
        """fill_rate should calculate relative to max_entries."""
        metrics = CacheMetrics(name="test", max_entries=100)

        metrics.set_current_entries(25)
        assert metrics.fill_rate == pytest.approx(0.25)

        metrics.set_current_entries(100)
        assert metrics.fill_rate == pytest.approx(1.0)

        # Cap at 1.0
        metrics.set_current_entries(150)
        assert metrics.fill_rate == pytest.approx(1.0)

    def test_reset(self):
        """reset should clear counters but preserve config."""
        metrics = CacheMetrics(name="test", ttl_seconds=300, max_entries=100)
        metrics.record_hit()
        metrics.record_miss()

        metrics.reset()

        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.ttl_seconds == 300  # Preserved
        assert metrics.max_entries == 100  # Preserved

    def test_to_dict(self):
        """to_dict should return serializable representation."""
        metrics = CacheMetrics(name="test", ttl_seconds=60)
        metrics.record_hit()

        data = metrics.to_dict()

        assert data["name"] == "test"
        assert data["hits"] == 1
        assert "hit_rate_pct" in data


class TestServerState:
    """Tests für ServerState Composition."""

    def test_initial_state(self):
        """Initial state should have correct defaults."""
        state = ServerState()

        assert not state.connection.is_connected
        assert state.vix.is_stale
        assert state.request_count == 0
        assert state.started_at is not None

    def test_uptime(self):
        """uptime should calculate correctly."""
        state = ServerState()

        assert state.uptime_seconds >= 0
        assert isinstance(state.uptime_human, str)

    def test_record_request(self):
        """record_request should increment count and update timestamp."""
        state = ServerState()

        state.record_request()
        state.record_request()

        assert state.request_count == 2
        assert state.last_request_at is not None

    def test_total_cache_requests(self):
        """total_cache_requests should sum all caches."""
        state = ServerState()

        state.quote_cache.record_hit()
        state.quote_cache.record_hit()
        state.scan_cache.record_miss()
        state.historical_cache.record_hit()

        assert state.total_cache_requests == 4

    def test_overall_cache_hit_rate(self):
        """overall_cache_hit_rate should weight by requests."""
        state = ServerState()

        # 3 hits, 1 miss = 75%
        state.quote_cache.record_hit()
        state.quote_cache.record_hit()
        state.scan_cache.record_hit()
        state.historical_cache.record_miss()

        assert state.overall_cache_hit_rate == pytest.approx(0.75)

    def test_reset_caches(self):
        """reset_caches should clear all cache metrics."""
        state = ServerState()
        state.quote_cache.record_hit()
        state.scan_cache.record_miss()

        state.reset_caches()

        assert state.quote_cache.hits == 0
        assert state.scan_cache.misses == 0

    def test_to_dict(self):
        """to_dict should return complete serializable representation."""
        state = ServerState()
        state.connection.mark_connected()
        state.vix.update(18.5)
        state.record_request()

        data = state.to_dict()

        assert isinstance(data, dict)
        assert "connection" in data
        assert "vix" in data
        assert "caches" in data
        assert "uptime_seconds" in data
        assert data["request_count"] == 1

    def test_health_summary(self):
        """health_summary should return compact status."""
        state = ServerState()
        state.connection.mark_connected()
        state.vix.update(18.5)

        summary = state.health_summary()

        assert summary["status"] == "healthy"
        assert summary["connected"] is True
        assert summary["vix"] == 18.5
        assert "cache_hit_rate_pct" in summary


class TestStateIntegration:
    """Integration tests für State Management."""

    def test_connection_lifecycle(self):
        """Full connection lifecycle through state machine."""
        state = ServerState()

        # Connect
        state.connection.mark_connecting()
        assert state.health_summary()["status"] == "degraded"

        state.connection.mark_connected()
        assert state.health_summary()["status"] == "healthy"

        # Reconnect with failure
        state.connection.mark_connecting()
        state.connection.mark_failed("timeout")
        assert state.connection.consecutive_failures == 1

        # Retry and succeed
        state.connection.mark_connecting()
        state.connection.mark_connected()
        assert state.connection.consecutive_failures == 0

        # Disconnect
        state.connection.mark_disconnected()
        assert state.health_summary()["status"] == "degraded"

    def test_cache_metrics_tracking(self):
        """Cache metrics should track across operations."""
        state = ServerState()

        # Simulate some cache operations
        for _ in range(10):
            state.quote_cache.record_hit()

        for _ in range(5):
            state.quote_cache.record_miss()

        for _ in range(8):
            state.historical_cache.record_hit()

        for _ in range(2):
            state.historical_cache.record_miss()

        # Check stats
        assert state.quote_cache.hit_rate_pct == pytest.approx(66.67, rel=0.01)
        assert state.historical_cache.hit_rate_pct == pytest.approx(80.0)
        assert state.total_cache_requests == 25
