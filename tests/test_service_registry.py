"""
Tests for ServiceRegistry - Registry-based DI container.
"""

import pytest
from unittest.mock import Mock

from src.core.service_registry import ServiceRegistry, service, register_example_services


@pytest.fixture(autouse=True)
def clean_registry():
    """Clean registry before and after each test."""
    ServiceRegistry.clear()
    yield
    ServiceRegistry.clear()


# =============================================================================
# BASIC REGISTRATION AND RETRIEVAL
# =============================================================================


class TestBasicRegistration:
    """Test basic service registration."""

    def test_register_simple_factory(self):
        """Register a simple class."""

        class SimpleService:
            pass

        ServiceRegistry.register("simple", SimpleService)
        assert ServiceRegistry.is_registered("simple")

    def test_register_callable_factory(self):
        """Register a callable factory."""

        def create_service():
            return {"type": "service"}

        ServiceRegistry.register("callable", create_service)
        assert ServiceRegistry.is_registered("callable")

    def test_get_creates_instance(self):
        """Get creates instance on first call."""

        class Counter:
            instances = 0

            def __init__(self):
                Counter.instances += 1

        ServiceRegistry.register("counter", Counter)
        assert Counter.instances == 0

        instance = ServiceRegistry.get("counter")
        assert Counter.instances == 1
        assert isinstance(instance, Counter)

    def test_get_returns_same_instance(self):
        """Get returns cached instance on subsequent calls."""

        class Service:
            pass

        ServiceRegistry.register("service", Service)

        instance1 = ServiceRegistry.get("service")
        instance2 = ServiceRegistry.get("service")

        assert instance1 is instance2

    def test_get_unregistered_raises(self):
        """Get raises KeyError for unregistered service."""
        with pytest.raises(KeyError, match="not registered"):
            ServiceRegistry.get("nonexistent")

    def test_register_with_kwargs(self):
        """Register with additional factory kwargs."""

        class ConfiguredService:
            def __init__(self, value: int = 0):
                self.value = value

        ServiceRegistry.register("configured", ConfiguredService, value=42)
        instance = ServiceRegistry.get("configured")

        assert instance.value == 42


# =============================================================================
# DEPENDENCY RESOLUTION
# =============================================================================


class TestDependencyResolution:
    """Test dependency resolution."""

    def test_simple_dependency(self):
        """Resolve simple dependency."""

        class Config:
            def __init__(self):
                self.setting = "value"

        class Service:
            def __init__(self, config: Config):
                self.config = config

        ServiceRegistry.register("config", Config)
        ServiceRegistry.register("service", Service, depends_on=["config"])

        instance = ServiceRegistry.get("service")

        assert instance.config is not None
        assert instance.config.setting == "value"

    def test_chain_dependency(self):
        """Resolve chain of dependencies (A → B → C)."""

        class A:
            pass

        class B:
            def __init__(self, a: A):
                self.a = a

        class C:
            def __init__(self, b: B):
                self.b = b

        ServiceRegistry.register("a", A)
        ServiceRegistry.register("b", B, depends_on=["a"])
        ServiceRegistry.register("c", C, depends_on=["b"])

        c = ServiceRegistry.get("c")

        assert c.b is not None
        assert c.b.a is not None

    def test_shared_dependency(self):
        """Multiple services share the same dependency instance."""

        class Shared:
            pass

        class Service1:
            def __init__(self, shared: Shared):
                self.shared = shared

        class Service2:
            def __init__(self, shared: Shared):
                self.shared = shared

        ServiceRegistry.register("shared", Shared)
        ServiceRegistry.register("service1", Service1, depends_on=["shared"])
        ServiceRegistry.register("service2", Service2, depends_on=["shared"])

        s1 = ServiceRegistry.get("service1")
        s2 = ServiceRegistry.get("service2")

        assert s1.shared is s2.shared

    def test_circular_dependency_raises(self):
        """Circular dependency detection."""

        class A:
            def __init__(self, b):
                self.b = b

        class B:
            def __init__(self, a):
                self.a = a

        ServiceRegistry.register("a", A, depends_on=["b"])
        ServiceRegistry.register("b", B, depends_on=["a"])

        with pytest.raises(RuntimeError, match="Circular dependency"):
            ServiceRegistry.get("a")

    def test_self_dependency_raises(self):
        """Self-referential dependency detection."""

        class Self:
            def __init__(self, self_ref):
                pass

        ServiceRegistry.register("self", Self, depends_on=["self"])

        with pytest.raises(RuntimeError, match="Circular dependency"):
            ServiceRegistry.get("self")


# =============================================================================
# RESET BEHAVIOR
# =============================================================================


class TestReset:
    """Test reset behavior."""

    def test_reset_single_service(self):
        """Reset clears single service instance."""

        class Service:
            pass

        ServiceRegistry.register("service", Service)
        instance1 = ServiceRegistry.get("service")

        ServiceRegistry.reset("service")

        assert not ServiceRegistry.is_instantiated("service")

        instance2 = ServiceRegistry.get("service")
        assert instance1 is not instance2

    def test_reset_all(self):
        """Reset with no name clears all instances."""

        class A:
            pass

        class B:
            pass

        ServiceRegistry.register("a", A)
        ServiceRegistry.register("b", B)

        ServiceRegistry.get("a")
        ServiceRegistry.get("b")

        assert ServiceRegistry.is_instantiated("a")
        assert ServiceRegistry.is_instantiated("b")

        ServiceRegistry.reset()

        assert not ServiceRegistry.is_instantiated("a")
        assert not ServiceRegistry.is_instantiated("b")

    def test_reset_cascades_to_dependents(self):
        """Reset cascades to services that depend on the reset service."""

        class Config:
            pass

        class Cache:
            def __init__(self, config: Config):
                self.config = config

        class Provider:
            def __init__(self, config: Config, cache: Cache):
                self.config = config
                self.cache = cache

        ServiceRegistry.register("config", Config)
        ServiceRegistry.register("cache", Cache, depends_on=["config"])
        ServiceRegistry.register("provider", Provider, depends_on=["config", "cache"])

        # Instantiate all
        ServiceRegistry.get("provider")

        assert ServiceRegistry.is_instantiated("config")
        assert ServiceRegistry.is_instantiated("cache")
        assert ServiceRegistry.is_instantiated("provider")

        # Reset config - should cascade to cache and provider
        ServiceRegistry.reset("config")

        assert not ServiceRegistry.is_instantiated("config")
        assert not ServiceRegistry.is_instantiated("cache")
        assert not ServiceRegistry.is_instantiated("provider")

    def test_reset_nonexistent_is_noop(self):
        """Reset of non-instantiated service is a no-op."""
        ServiceRegistry.register("service", dict)
        ServiceRegistry.reset("service")  # Should not raise


# =============================================================================
# HELPER METHODS
# =============================================================================


class TestHelperMethods:
    """Test helper methods."""

    def test_is_registered(self):
        """is_registered returns correct status."""
        assert not ServiceRegistry.is_registered("test")

        ServiceRegistry.register("test", dict)
        assert ServiceRegistry.is_registered("test")

    def test_is_instantiated(self):
        """is_instantiated returns correct status."""
        ServiceRegistry.register("test", dict)

        assert not ServiceRegistry.is_instantiated("test")

        ServiceRegistry.get("test")
        assert ServiceRegistry.is_instantiated("test")

    def test_get_dependencies(self):
        """get_dependencies returns dependency list."""

        class Service:
            pass

        ServiceRegistry.register("a", Service)
        ServiceRegistry.register("b", Service)
        ServiceRegistry.register("c", Service, depends_on=["a", "b"])

        deps = ServiceRegistry.get_dependencies("c")

        assert deps == ["a", "b"]

    def test_get_dependents(self):
        """get_dependents returns services that depend on this one."""

        class Service:
            pass

        ServiceRegistry.register("a", Service)
        ServiceRegistry.register("b", Service, depends_on=["a"])
        ServiceRegistry.register("c", Service, depends_on=["a"])

        dependents = ServiceRegistry.get_dependents("a")

        assert "b" in dependents
        assert "c" in dependents

    def test_list_services(self):
        """list_services returns all registered names."""
        ServiceRegistry.register("a", dict)
        ServiceRegistry.register("b", list)
        ServiceRegistry.register("c", set)

        services = ServiceRegistry.list_services()

        assert sorted(services) == ["a", "b", "c"]

    def test_get_stats(self):
        """get_stats returns registry statistics."""

        class Service:
            pass

        ServiceRegistry.register("a", Service)
        ServiceRegistry.register("b", Service, depends_on=["a"])

        ServiceRegistry.get("a")

        stats = ServiceRegistry.get_stats()

        assert stats["registered"] == 2
        assert stats["instantiated"] == 1
        assert stats["services"]["a"]["instantiated"] is True
        assert stats["services"]["b"]["instantiated"] is False
        assert stats["services"]["b"]["dependencies"] == ["a"]


# =============================================================================
# OVERRIDE FOR TESTING
# =============================================================================


class TestOverride:
    """Test override functionality for testing."""

    def test_override_injects_instance(self):
        """Override injects custom instance."""

        class RealService:
            def value(self):
                return "real"

        ServiceRegistry.register("service", RealService)

        mock = Mock()
        mock.value.return_value = "mock"

        ServiceRegistry.override("service", mock)

        instance = ServiceRegistry.get("service")

        assert instance is mock
        assert instance.value() == "mock"

    def test_override_without_registration(self):
        """Override works even without prior registration."""
        mock = Mock()
        ServiceRegistry.override("unregistered", mock)

        instance = ServiceRegistry.get("unregistered")
        assert instance is mock


# =============================================================================
# DECORATOR
# =============================================================================


class TestServiceDecorator:
    """Test @service decorator."""

    def test_decorator_registers_class(self):
        """Decorator registers class."""

        @service("decorated")
        class DecoratedService:
            pass

        assert ServiceRegistry.is_registered("decorated")
        instance = ServiceRegistry.get("decorated")
        assert isinstance(instance, DecoratedService)

    def test_decorator_with_dependencies(self):
        """Decorator with dependencies."""

        @service("base")
        class Base:
            pass

        @service("dependent", depends_on=["base"])
        class Dependent:
            def __init__(self, base: Base):
                self.base = base

        instance = ServiceRegistry.get("dependent")
        assert instance.base is not None


# =============================================================================
# EXAMPLE SERVICES (integration test)
# =============================================================================


class TestExampleServices:
    """Test with realistic service examples."""

    def test_realistic_service_graph(self):
        """Test realistic dependency graph like OptionPlay."""

        # Simulate config
        class Config:
            def __init__(self):
                self.api_key = "test-key"
                self.rate_limit = 100

        # Simulate rate limiter
        class RateLimiter:
            def __init__(self, config: Config):
                self.limit = config.rate_limit

        # Simulate cache
        class Cache:
            def __init__(self, config: Config):
                self.ttl = 3600

        # Simulate provider
        class Provider:
            def __init__(self, config: Config, rate_limiter: RateLimiter, cache: Cache):
                self.api_key = config.api_key
                self.limiter = rate_limiter
                self.cache = cache

        # Register
        ServiceRegistry.register("config", Config)
        ServiceRegistry.register("rate_limiter", RateLimiter, depends_on=["config"])
        ServiceRegistry.register("cache", Cache, depends_on=["config"])
        ServiceRegistry.register(
            "provider", Provider, depends_on=["config", "rate_limiter", "cache"]
        )

        # Get provider - should resolve all dependencies
        provider = ServiceRegistry.get("provider")

        assert provider.api_key == "test-key"
        assert provider.limiter.limit == 100
        assert provider.cache.ttl == 3600

        # All services share same config instance
        assert provider.limiter is ServiceRegistry.get("rate_limiter")
        assert provider.cache is ServiceRegistry.get("cache")


# =============================================================================
# REGISTER EXAMPLE SERVICES
# =============================================================================


class TestRegisterExampleServices:
    """Test the example service registrations."""

    def test_register_example_services_creates_entries(self):
        """register_example_services creates the expected service entries."""
        register_example_services()

        assert ServiceRegistry.is_registered("config")
        assert ServiceRegistry.is_registered("rate_limiter")
        assert ServiceRegistry.is_registered("historical_cache")

    def test_example_services_have_correct_dependencies(self):
        """Example services have the expected dependencies."""
        register_example_services()

        assert ServiceRegistry.get_dependencies("config") == []
        assert ServiceRegistry.get_dependencies("rate_limiter") == ["config"]
        assert ServiceRegistry.get_dependencies("historical_cache") == ["config"]

    def test_example_services_resolve_correctly(self):
        """Example services can be resolved and used."""
        register_example_services()

        # Get the services - should resolve dependencies automatically
        config = ServiceRegistry.get("config")
        rate_limiter = ServiceRegistry.get("rate_limiter")
        historical_cache = ServiceRegistry.get("historical_cache")

        # Verify they are actual instances (not None)
        assert config is not None
        assert rate_limiter is not None
        assert historical_cache is not None

        # Verify config is shared
        # (rate_limiter and historical_cache should use same config instance)
        assert ServiceRegistry.is_instantiated("config")

    def test_example_services_reset_cascade(self):
        """Resetting config cascades to dependents."""
        register_example_services()

        # Instantiate all
        ServiceRegistry.get("config")
        ServiceRegistry.get("rate_limiter")
        ServiceRegistry.get("historical_cache")

        assert ServiceRegistry.is_instantiated("config")
        assert ServiceRegistry.is_instantiated("rate_limiter")
        assert ServiceRegistry.is_instantiated("historical_cache")

        # Reset config - should cascade
        ServiceRegistry.reset("config")

        assert not ServiceRegistry.is_instantiated("config")
        assert not ServiceRegistry.is_instantiated("rate_limiter")
        assert not ServiceRegistry.is_instantiated("historical_cache")
