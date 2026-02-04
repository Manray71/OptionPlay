# Tests for Deprecation Utilities
# ================================
"""
Tests for deprecation warnings and decorator.
"""

import pytest
import warnings
from src.utils.deprecation import (
    warn_singleton_usage,
    deprecated_singleton,
    reset_warnings,
    get_warned_singletons,
    deprecate_getter,
    DEPRECATION_MESSAGES,
)


# =============================================================================
# SETUP/TEARDOWN
# =============================================================================

@pytest.fixture(autouse=True)
def reset_before_each():
    """Reset warnings before each test."""
    reset_warnings()
    yield
    reset_warnings()


# =============================================================================
# WARN SINGLETON USAGE TESTS
# =============================================================================

class TestWarnSingletonUsage:
    """Tests for warn_singleton_usage function."""

    def test_issues_deprecation_warning(self):
        """Test warning is issued."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            warn_singleton_usage("test_func", "container.test", stacklevel=1)

            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "test_func" in str(w[0].message)
            assert "container.test" in str(w[0].message)

    def test_warns_only_once(self):
        """Test warning is only issued once per getter."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            warn_singleton_usage("duplicate_func", "alt", stacklevel=1)
            warn_singleton_usage("duplicate_func", "alt", stacklevel=1)
            warn_singleton_usage("duplicate_func", "alt", stacklevel=1)

            # Only one warning despite 3 calls
            assert len(w) == 1

    def test_tracks_warned_singletons(self):
        """Test warned singletons are tracked."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            warn_singleton_usage("tracked_func", "alt", stacklevel=1)

        warned = get_warned_singletons()
        assert "tracked_func" in warned


# =============================================================================
# RESET WARNINGS TESTS
# =============================================================================

class TestResetWarnings:
    """Tests for reset_warnings function."""

    def test_clears_warned_set(self):
        """Test reset clears the warned singletons set."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            warn_singleton_usage("func_to_clear", "alt", stacklevel=1)

        assert "func_to_clear" in get_warned_singletons()

        reset_warnings()

        assert "func_to_clear" not in get_warned_singletons()


# =============================================================================
# GET WARNED SINGLETONS TESTS
# =============================================================================

class TestGetWarnedSingletons:
    """Tests for get_warned_singletons function."""

    def test_returns_set(self):
        """Test returns a set."""
        result = get_warned_singletons()
        assert isinstance(result, set)

    def test_returns_copy(self):
        """Test returns a copy, not the original."""
        original = get_warned_singletons()
        original.add("test")

        # Should not affect the internal set
        assert "test" not in get_warned_singletons()


# =============================================================================
# DEPRECATED SINGLETON DECORATOR TESTS
# =============================================================================

class TestDeprecatedSingletonDecorator:
    """Tests for deprecated_singleton decorator."""

    def test_decorator_preserves_function(self):
        """Test decorator preserves function behavior."""
        @deprecated_singleton(alternative="container.test")
        def my_func():
            return "result"

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = my_func()

        assert result == "result"

    def test_decorator_issues_warning(self):
        """Test decorator issues deprecation warning."""
        @deprecated_singleton(alternative="container.test")
        def warned_func():
            return True

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            warned_func()

            assert len(w) == 1
            assert "warned_func" in str(w[0].message)

    def test_decorator_with_custom_name(self):
        """Test decorator with custom getter name."""
        @deprecated_singleton(getter_name="custom_name", alternative="alt")
        def actual_name():
            return True

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            actual_name()

            assert "custom_name" in str(w[0].message)

    def test_decorator_warn_level_log(self):
        """Test decorator with log warn level."""
        @deprecated_singleton(alternative="alt", warn_level="log")
        def log_only_func():
            return True

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            log_only_func()

            # Should not issue DeprecationWarning
            deprecation_warnings = [
                warning for warning in w
                if issubclass(warning.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) == 0


# =============================================================================
# DEPRECATE GETTER TESTS
# =============================================================================

class TestDeprecateGetter:
    """Tests for deprecate_getter convenience function."""

    def test_uses_message_from_dict(self):
        """Test uses message from DEPRECATION_MESSAGES."""
        @deprecate_getter("get_config")
        def get_config():
            return {}

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            get_config()

            assert len(w) == 1
            # Should use alternative from DEPRECATION_MESSAGES
            expected_alt = DEPRECATION_MESSAGES["get_config"]
            assert expected_alt in str(w[0].message)

    def test_unknown_getter_uses_default(self):
        """Test unknown getter uses ServiceContainer as alternative."""
        @deprecate_getter("unknown_getter")
        def unknown_getter():
            return {}

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            unknown_getter()

            assert len(w) == 1
            assert "ServiceContainer" in str(w[0].message)


# =============================================================================
# DEPRECATION MESSAGES TESTS
# =============================================================================

class TestDeprecationMessages:
    """Tests for DEPRECATION_MESSAGES constant."""

    def test_has_cache_messages(self):
        """Test cache singletons have messages."""
        assert "get_earnings_cache" in DEPRECATION_MESSAGES
        assert "get_iv_cache" in DEPRECATION_MESSAGES

    def test_has_config_messages(self):
        """Test config singletons have messages."""
        assert "get_config" in DEPRECATION_MESSAGES

    def test_messages_reference_container(self):
        """Test messages reference container properties."""
        for name, alternative in DEPRECATION_MESSAGES.items():
            assert "container" in alternative.lower() or "Server" in alternative


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
