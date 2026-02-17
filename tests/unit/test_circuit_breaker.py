# Tests für Circuit Breaker
# ==========================

import pytest
import time
import asyncio
from datetime import datetime, timedelta

from src.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitBreakerError,
    CircuitState,
    CircuitBreakerRegistry,
    get_circuit_breaker,
    get_circuit_breaker_registry,
    reset_circuit_breakers,
)


# =============================================================================
# CIRCUIT BREAKER TESTS
# =============================================================================

class TestCircuitBreaker:
    """Tests für CircuitBreaker."""
    
    def setup_method(self):
        """Reset before each test."""
        reset_circuit_breakers()
    
    def test_initial_state_closed(self):
        """Circuit sollte initial CLOSED sein."""
        breaker = CircuitBreaker()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open
    
    def test_stays_closed_under_threshold(self):
        """Circuit bleibt CLOSED bei weniger Fehlern als Threshold."""
        breaker = CircuitBreaker(failure_threshold=5)
        
        for _ in range(4):
            breaker.record_failure()
        
        assert breaker.is_closed
    
    def test_opens_at_threshold(self):
        """Circuit öffnet bei Erreichen des Thresholds."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        for _ in range(3):
            breaker.record_failure()
        
        assert breaker.is_open
    
    def test_rejects_when_open(self):
        """can_execute() gibt False wenn OPEN."""
        breaker = CircuitBreaker(failure_threshold=2)
        
        breaker.record_failure()
        breaker.record_failure()
        
        assert not breaker.can_execute()
    
    def test_transitions_to_half_open(self):
        """Circuit wechselt nach Recovery Timeout zu HALF_OPEN."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.5)
        
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open

        # Simulate recovery timeout elapsed
        breaker._opened_at = datetime.now() - timedelta(seconds=1)

        # State-Abfrage triggered auto-transition
        assert breaker.is_half_open
    
    def test_half_open_to_closed_on_success(self):
        """Circuit schließt bei Erfolgen im HALF_OPEN."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=2
        )
        
        breaker.record_failure()
        breaker.record_failure()
        time.sleep(0.2)
        
        assert breaker.is_half_open
        
        # 2 Erfolge zum Schließen
        breaker.record_success()
        breaker.record_success()
        
        assert breaker.is_closed
    
    def test_half_open_to_open_on_failure(self):
        """Circuit öffnet wieder bei Fehler im HALF_OPEN."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0.1
        )
        
        breaker.record_failure()
        breaker.record_failure()
        time.sleep(0.2)
        
        assert breaker.is_half_open
        
        breaker.record_failure()
        
        assert breaker.is_open
    
    def test_success_resets_failure_count(self):
        """Erfolg setzt Failure-Counter zurück."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        breaker.record_failure()
        breaker.record_failure()
        assert breaker._failure_count == 2
        
        breaker.record_success()
        assert breaker._failure_count == 0
    
    def test_manual_reset(self):
        """reset() setzt Circuit zurück."""
        breaker = CircuitBreaker(failure_threshold=2)
        
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.is_open
        
        breaker.reset()
        assert breaker.is_closed
    
    def test_stats(self):
        """stats() gibt korrekte Statistiken."""
        breaker = CircuitBreaker(
            name="test_breaker",
            failure_threshold=5,
            recovery_timeout=60
        )
        
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        
        stats = breaker.stats()
        
        assert stats["name"] == "test_breaker"
        assert stats["state"] == "closed"
        assert stats["total_calls"] == 3
        assert stats["successful_calls"] == 1
        assert stats["failed_calls"] == 2
        assert stats["failure_threshold"] == 5
        assert stats["recovery_timeout"] == 60
    
    def test_get_retry_after(self):
        """get_retry_after() gibt verbleibende Zeit."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=10)
        
        breaker.record_failure()
        assert breaker.is_open
        
        retry_after = breaker.get_retry_after()
        assert retry_after is not None
        assert 9 <= retry_after <= 10


# =============================================================================
# CONTEXT MANAGER TESTS
# =============================================================================

class TestContextManager:
    """Tests für Context Manager Verwendung."""
    
    def setup_method(self):
        reset_circuit_breakers()
    
    def test_sync_context_manager_success(self):
        """Sync Context Manager bei Erfolg."""
        breaker = CircuitBreaker()
        
        with breaker:
            result = 42
        
        assert breaker._stats.successful_calls == 1
    
    def test_sync_context_manager_failure(self):
        """Sync Context Manager bei Fehler."""
        breaker = CircuitBreaker()
        
        with pytest.raises(ValueError):
            with breaker:
                raise ValueError("test error")
        
        assert breaker._stats.failed_calls == 1
    
    def test_sync_context_manager_rejects_when_open(self):
        """Context Manager wirft Exception wenn OPEN."""
        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure()
        
        with pytest.raises(CircuitBreakerOpen) as exc_info:
            with breaker:
                pass
        
        assert "marketdata_api" not in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_async_context_manager_success(self):
        """Async Context Manager bei Erfolg."""
        breaker = CircuitBreaker()
        
        async with breaker:
            result = await asyncio.sleep(0.01)
        
        assert breaker._stats.successful_calls == 1
    
    @pytest.mark.asyncio
    async def test_async_context_manager_failure(self):
        """Async Context Manager bei Fehler."""
        breaker = CircuitBreaker()
        
        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("async error")
        
        assert breaker._stats.failed_calls == 1


# =============================================================================
# DECORATOR TESTS
# =============================================================================

class TestDecorator:
    """Tests für Decorator Verwendung."""
    
    def setup_method(self):
        reset_circuit_breakers()
    
    def test_sync_decorator_success(self):
        """Sync Decorator bei Erfolg."""
        breaker = CircuitBreaker()
        
        @breaker
        def my_function():
            return 42
        
        result = my_function()
        assert result == 42
        assert breaker._stats.successful_calls == 1
    
    def test_sync_decorator_failure(self):
        """Sync Decorator bei Fehler."""
        breaker = CircuitBreaker()
        
        @breaker
        def failing_function():
            raise RuntimeError("oops")
        
        with pytest.raises(RuntimeError):
            failing_function()
        
        assert breaker._stats.failed_calls == 1
    
    @pytest.mark.asyncio
    async def test_async_decorator_success(self):
        """Async Decorator bei Erfolg."""
        breaker = CircuitBreaker()
        
        @breaker
        async def async_function():
            await asyncio.sleep(0.01)
            return 42
        
        result = await async_function()
        assert result == 42
        assert breaker._stats.successful_calls == 1


# =============================================================================
# REGISTRY TESTS
# =============================================================================

class TestRegistry:
    """Tests für CircuitBreakerRegistry."""
    
    def setup_method(self):
        reset_circuit_breakers()
    
    def test_get_or_create(self):
        """get_or_create erstellt neuen Breaker."""
        registry = CircuitBreakerRegistry()
        
        breaker = registry.get_or_create("api")
        assert breaker.name == "api"
    
    def test_get_or_create_returns_same_instance(self):
        """get_or_create gibt selbe Instanz zurück."""
        registry = CircuitBreakerRegistry()
        
        breaker1 = registry.get_or_create("api")
        breaker2 = registry.get_or_create("api")
        
        assert breaker1 is breaker2
    
    def test_all_stats(self):
        """all_stats gibt Stats aller Breaker."""
        registry = CircuitBreakerRegistry()
        
        registry.get_or_create("api1")
        registry.get_or_create("api2")
        
        stats = registry.all_stats()
        
        assert "api1" in stats
        assert "api2" in stats
    
    def test_reset_all(self):
        """reset_all setzt alle Breaker zurück."""
        registry = CircuitBreakerRegistry()
        
        breaker = registry.get_or_create("api", failure_threshold=1)
        breaker.record_failure()
        assert breaker.is_open
        
        registry.reset_all()
        assert breaker.is_closed
    
    def test_get_open_breakers(self):
        """get_open_breakers listet offene Breaker."""
        registry = CircuitBreakerRegistry()
        
        breaker1 = registry.get_or_create("api1", failure_threshold=1)
        breaker2 = registry.get_or_create("api2", failure_threshold=1)
        
        breaker1.record_failure()
        
        open_breakers = registry.get_open_breakers()
        
        assert "api1" in open_breakers
        assert "api2" not in open_breakers


# =============================================================================
# SINGLETON TESTS
# =============================================================================

class TestSingleton:
    """Tests für globale Funktionen."""
    
    def setup_method(self):
        reset_circuit_breakers()
    
    def test_get_circuit_breaker(self):
        """get_circuit_breaker gibt Breaker zurück."""
        breaker = get_circuit_breaker("test_api")
        assert breaker.name == "test_api"
    
    def test_get_circuit_breaker_registry(self):
        """get_circuit_breaker_registry gibt Registry."""
        registry = get_circuit_breaker_registry()
        assert isinstance(registry, CircuitBreakerRegistry)
    
    def test_reset_circuit_breakers(self):
        """reset_circuit_breakers setzt alles zurück."""
        breaker = get_circuit_breaker("api", failure_threshold=1)
        breaker.record_failure()
        
        reset_circuit_breakers()
        
        # Neuer Breaker sollte CLOSED sein
        new_breaker = get_circuit_breaker("api")
        assert new_breaker.is_closed


# =============================================================================
# EXCEPTION TESTS
# =============================================================================

class TestExceptions:
    """Tests für Circuit Breaker Exceptions."""
    
    def test_circuit_breaker_open_exception(self):
        """CircuitBreakerOpen enthält korrekten Namen."""
        exc = CircuitBreakerOpen("my_api", retry_after=30.0)
        
        assert exc.breaker_name == "my_api"
        assert exc.retry_after == 30.0
        assert "my_api" in str(exc)
        assert "OPEN" in str(exc)
        assert "30.0" in str(exc)
    
    def test_circuit_breaker_open_without_retry(self):
        """CircuitBreakerOpen ohne retry_after."""
        exc = CircuitBreakerOpen("my_api")
        
        assert exc.retry_after is None
        assert "retry after" not in str(exc)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
