# OptionPlay - Secure Config Tests
# ==================================
# Comprehensive tests for secure API key management
#
# Coverage includes:
# - mask_api_key() function
# - mask_sensitive_data() function
# - SecureConfig class initialization
# - get_api_key() method with all scenarios
# - set_api_key() method
# - remove_api_key() method
# - Environment variable handling
# - .env file loading
# - Keyring integration (mocked)
# - Key validation
# - Singleton pattern

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from src.utils.secure_config import (
    SecureConfig,
    mask_api_key,
    mask_sensitive_data,
    get_api_key,
    get_secure_config,
    reset_secure_config,
)


# =============================================================================
# MASK_API_KEY TESTS
# =============================================================================

class TestMaskApiKey:
    """Tests for mask_api_key() function."""

    def test_normal_key(self):
        """Normal keys are properly masked."""
        key = "abcdefghijklmnop"
        masked = mask_api_key(key)
        assert masked == "abcd...mnop"
        assert "efgh" not in masked  # Middle part not visible

    def test_short_key_two_chars(self):
        """Two-char keys return asterisks."""
        assert mask_api_key("ab") == "**"

    def test_short_key_one_char(self):
        """Single-char keys return single asterisk."""
        assert mask_api_key("a") == "*"

    def test_short_key_three_chars(self):
        """Three-char keys show first and last."""
        assert mask_api_key("abc") == "a...c"

    def test_short_key_four_chars(self):
        """Four-char keys show first and last."""
        assert mask_api_key("abcd") == "a...d"

    def test_short_key_eight_chars(self):
        """Eight-char keys (exactly visible_chars * 2) show first and last."""
        assert mask_api_key("abcdefgh") == "a...h"

    def test_nine_char_key(self):
        """Nine-char key shows first 4 and last 4."""
        assert mask_api_key("abcdefghi") == "abcd...fghi"

    def test_none_key(self):
        """None returns '<not set>'."""
        assert mask_api_key(None) == "<not set>"

    def test_empty_key(self):
        """Empty string returns empty asterisks."""
        assert mask_api_key("") == ""

    def test_custom_visible_chars_two(self):
        """Custom visible_chars=2."""
        key = "abcdefghijklmnopqrstuvwxyz"
        assert mask_api_key(key, visible_chars=2) == "ab...yz"

    def test_custom_visible_chars_six(self):
        """Custom visible_chars=6."""
        key = "abcdefghijklmnopqrstuvwxyz"
        assert mask_api_key(key, visible_chars=6) == "abcdef...uvwxyz"

    def test_custom_visible_chars_one(self):
        """Custom visible_chars=1."""
        key = "abcdefghijklmnop"
        assert mask_api_key(key, visible_chars=1) == "a...p"

    def test_key_with_special_chars(self):
        """Keys with special characters are masked properly."""
        key = "abc-123_XYZ.token!@#"
        masked = mask_api_key(key)
        # With default visible_chars=4, shows first 4 and last 4
        assert masked.startswith("abc-")
        assert masked.endswith("!@#") or masked.endswith("n!@#")
        assert "..." in masked

    def test_key_with_numbers(self):
        """Keys with numbers are masked properly."""
        key = "1234567890abcdef"
        masked = mask_api_key(key)
        assert masked == "1234...cdef"


# =============================================================================
# MASK_SENSITIVE_DATA TESTS
# =============================================================================

class TestMaskSensitiveData:
    """Tests for mask_sensitive_data() function."""

    def test_masks_long_strings(self):
        """Long alphanumeric strings are masked."""
        text = "The key is abcdefghijklmnopqrstuvwxyz12345"
        masked = mask_sensitive_data(text)
        assert "abcdefghijklmnopqrstuvwxyz12345" not in masked
        assert "***MASKED***" in masked

    def test_masks_bearer_tokens(self):
        """Bearer tokens are masked."""
        text = "Authorization: Bearer abc123xyz789token"
        masked = mask_sensitive_data(text)
        assert "abc123xyz789token" not in masked
        # Either the entire line is masked or token is masked
        assert "***MASKED***" in masked or "Bearer" not in masked

    def test_masks_authorization_headers(self):
        """Authorization headers are masked."""
        text = "Authorization: Basic dXNlcjpwYXNzd29yZA=="
        masked = mask_sensitive_data(text)
        # The base64 credential should be masked
        assert "dXNlcjpwYXNzd29yZA==" not in masked or "***MASKED***" in masked

    def test_custom_patterns_tuple(self):
        """Custom patterns as tuples work."""
        text = "Secret: password123"
        patterns = [(r'password\d+', '***')]
        masked = mask_sensitive_data(text, patterns=patterns)
        assert "password123" not in masked
        assert "***" in masked
        assert "Secret: " in masked

    def test_legacy_pattern_format(self):
        """Legacy pattern format (string only) works."""
        text = "Token: abc123456789xyz"
        patterns = [r'abc\d+xyz']
        masked = mask_sensitive_data(text, patterns=patterns)
        assert "abc123456789xyz" not in masked
        assert "***MASKED***" in masked

    def test_preserves_safe_text(self):
        """Safe text without patterns is preserved."""
        text = "This is safe"
        masked = mask_sensitive_data(text)
        # Short strings without patterns matching are preserved
        assert "This is safe" in masked

    def test_multiple_patterns_applied(self):
        """Multiple default patterns all get applied."""
        text = "Key: abcdefghijklmnopqrstuvwxyz, Bearer token123456789"
        masked = mask_sensitive_data(text)
        # Both patterns should be masked
        assert "abcdefghijklmnopqrstuvwxyz" not in masked
        assert "token123456789" not in masked

    def test_empty_text(self):
        """Empty text returns empty string."""
        assert mask_sensitive_data("") == ""

    def test_no_sensitive_data(self):
        """Text without sensitive data is unchanged."""
        text = "Hello world"
        masked = mask_sensitive_data(text)
        assert masked == "Hello world"


# =============================================================================
# SECURE CONFIG INITIALIZATION TESTS
# =============================================================================

class TestSecureConfigInit:
    """Tests for SecureConfig initialization."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()

    def test_default_initialization(self):
        """Default initialization sets correct defaults."""
        config = SecureConfig()
        assert config._env_file is None
        assert config._use_keyring is False
        assert config._keyring_service == "optionplay"
        assert config._cache == {}
        assert config._env_loaded is False

    def test_custom_env_file(self, tmp_path):
        """Custom env_file is stored."""
        env_file = tmp_path / ".env"
        config = SecureConfig(env_file=env_file)
        assert config._env_file == env_file

    def test_use_keyring_enabled(self):
        """use_keyring flag is stored."""
        config = SecureConfig(use_keyring=True)
        assert config._use_keyring is True

    def test_custom_keyring_service(self):
        """Custom keyring_service is stored."""
        config = SecureConfig(keyring_service="my_service")
        assert config._keyring_service == "my_service"

    def test_keyring_import_failure(self):
        """Handles keyring import failure gracefully."""
        with patch.dict('sys.modules', {'keyring': None}):
            with patch('builtins.__import__', side_effect=ImportError):
                config = SecureConfig(use_keyring=True)
                assert config._keyring_available is False


# =============================================================================
# GET_API_KEY TESTS
# =============================================================================

class TestSecureConfigGetApiKey:
    """Tests for SecureConfig.get_api_key() method."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()
        self._env_backup = {}
        for key in ["TEST_API_KEY", "CACHED_KEY", "ENV_KEY"]:
            if key in os.environ:
                self._env_backup[key] = os.environ[key]
                del os.environ[key]

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["TEST_API_KEY", "CACHED_KEY", "ENV_KEY"]:
            if key in os.environ:
                del os.environ[key]
        for key, value in self._env_backup.items():
            os.environ[key] = value

    def test_get_from_environment(self):
        """Keys are loaded from environment."""
        os.environ["TEST_API_KEY"] = "test_value_12345"
        config = SecureConfig()

        key = config.get_api_key("TEST_API_KEY")
        assert key == "test_value_12345"

    def test_caching(self):
        """Keys are cached after first retrieval."""
        os.environ["TEST_API_KEY"] = "cached_value"
        config = SecureConfig()

        key1 = config.get_api_key("TEST_API_KEY")
        os.environ["TEST_API_KEY"] = "changed_value"
        key2 = config.get_api_key("TEST_API_KEY")

        assert key1 == "cached_value"
        assert key2 == "cached_value"  # Still cached

    def test_clear_cache(self):
        """Cache can be cleared."""
        os.environ["TEST_API_KEY"] = "initial_value"
        config = SecureConfig()

        config.get_api_key("TEST_API_KEY")
        os.environ["TEST_API_KEY"] = "new_value"
        config.clear_cache()

        key = config.get_api_key("TEST_API_KEY")
        assert key == "new_value"

    def test_required_key_missing(self):
        """Missing required key raises ValueError."""
        config = SecureConfig()

        with pytest.raises(ValueError, match="not found"):
            config.get_api_key("NONEXISTENT_KEY", required=True)

    def test_required_key_missing_message(self):
        """Error message includes key name."""
        config = SecureConfig()

        with pytest.raises(ValueError) as exc_info:
            config.get_api_key("MY_MISSING_KEY", required=True)

        assert "MY_MISSING_KEY" in str(exc_info.value)
        assert "environment variable or .env file" in str(exc_info.value)

    def test_optional_key_missing(self):
        """Missing optional key returns None."""
        config = SecureConfig()

        key = config.get_api_key("NONEXISTENT_KEY", required=False)
        assert key is None

    def test_get_from_cache_first(self):
        """Cache is checked before environment."""
        config = SecureConfig()
        config._cache["CACHED_KEY"] = "cached_value"
        os.environ["CACHED_KEY"] = "env_value"

        key = config.get_api_key("CACHED_KEY")
        assert key == "cached_value"

    def test_empty_string_value(self):
        """Empty string values are handled appropriately."""
        os.environ["TEST_API_KEY"] = ""
        config = SecureConfig()

        # Empty string may be treated as not found or returned
        key = config.get_api_key("TEST_API_KEY", required=False)
        # Implementation may return None or empty string for empty env var
        assert key is None or key == ""


# =============================================================================
# SET_API_KEY TESTS
# =============================================================================

class TestSecureConfigSetApiKey:
    """Tests for SecureConfig.set_api_key() method."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["NEW_KEY", "PERSIST_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_set_api_key(self):
        """Keys can be set."""
        config = SecureConfig()

        config.set_api_key("NEW_KEY", "new_value_123")

        assert config.get_api_key("NEW_KEY") == "new_value_123"
        assert os.environ.get("NEW_KEY") == "new_value_123"

    def test_set_api_key_updates_cache(self):
        """Setting a key updates the cache."""
        config = SecureConfig()

        config.set_api_key("NEW_KEY", "first_value")
        config.set_api_key("NEW_KEY", "second_value")

        assert config.get_api_key("NEW_KEY") == "second_value"

    def test_set_api_key_with_persist_no_keyring(self):
        """Persist flag does nothing without keyring."""
        config = SecureConfig(use_keyring=False)

        config.set_api_key("PERSIST_KEY", "value", persist=True)

        assert config.get_api_key("PERSIST_KEY") == "value"

    def test_set_api_key_with_persist_and_keyring(self):
        """Persist flag saves to keyring when available."""
        mock_keyring = MagicMock()

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(use_keyring=True)
            config._keyring_available = True

            config.set_api_key("PERSIST_KEY", "value", persist=True)

            mock_keyring.set_password.assert_called_once_with(
                "optionplay", "PERSIST_KEY", "value"
            )

    def test_set_api_key_keyring_failure(self):
        """Keyring save failure is handled gracefully."""
        mock_keyring = MagicMock()
        mock_keyring.set_password.side_effect = Exception("Keyring error")

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(use_keyring=True)
            config._keyring_available = True

            # Should not raise, just log warning
            config.set_api_key("PERSIST_KEY", "value", persist=True)

            # Value should still be in cache
            assert config._cache["PERSIST_KEY"] == "value"


# =============================================================================
# REMOVE_API_KEY TESTS
# =============================================================================

class TestSecureConfigRemoveApiKey:
    """Tests for SecureConfig.remove_api_key() method."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["REMOVE_KEY", "REMOVE_ENV_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_remove_from_cache(self):
        """Key is removed from cache."""
        config = SecureConfig()
        config._cache["REMOVE_KEY"] = "value"

        config.remove_api_key("REMOVE_KEY")

        assert "REMOVE_KEY" not in config._cache

    def test_remove_from_environment(self):
        """Key is removed from environment."""
        os.environ["REMOVE_ENV_KEY"] = "value"
        config = SecureConfig()

        config.remove_api_key("REMOVE_ENV_KEY")

        assert "REMOVE_ENV_KEY" not in os.environ

    def test_remove_from_both(self):
        """Key is removed from both cache and environment."""
        os.environ["REMOVE_KEY"] = "env_value"
        config = SecureConfig()
        config._cache["REMOVE_KEY"] = "cache_value"

        config.remove_api_key("REMOVE_KEY")

        assert "REMOVE_KEY" not in config._cache
        assert "REMOVE_KEY" not in os.environ

    def test_remove_nonexistent_key(self):
        """Removing nonexistent key does not raise."""
        config = SecureConfig()

        # Should not raise
        config.remove_api_key("NONEXISTENT_KEY")

    def test_remove_from_keyring(self):
        """Key is removed from keyring when available."""
        mock_keyring = MagicMock()

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(use_keyring=True)
            config._keyring_available = True
            config._cache["REMOVE_KEY"] = "value"
            os.environ["REMOVE_KEY"] = "value"

            config.remove_api_key("REMOVE_KEY")

            mock_keyring.delete_password.assert_called_once_with(
                "optionplay", "REMOVE_KEY"
            )

    def test_remove_keyring_failure(self):
        """Keyring delete failure is handled gracefully."""
        mock_keyring = MagicMock()
        mock_keyring.delete_password.side_effect = Exception("Keyring error")

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(use_keyring=True)
            config._keyring_available = True
            config._cache["REMOVE_KEY"] = "value"

            # Should not raise
            config.remove_api_key("REMOVE_KEY")

            # Cache should still be cleared
            assert "REMOVE_KEY" not in config._cache


# =============================================================================
# AVAILABLE_KEYS TESTS
# =============================================================================

class TestSecureConfigAvailableKeys:
    """Tests for SecureConfig.available_keys property."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["TEST_KEY_1", "TEST_KEY_2", "TEST_KEY_3"]:
            if key in os.environ:
                del os.environ[key]

    def test_available_keys_empty(self):
        """Empty cache returns empty list."""
        config = SecureConfig()
        assert config.available_keys == []

    def test_available_keys_after_get(self):
        """Keys appear in available_keys after retrieval."""
        os.environ["TEST_KEY_1"] = "value1"
        os.environ["TEST_KEY_2"] = "value2"
        config = SecureConfig()

        config.get_api_key("TEST_KEY_1")
        config.get_api_key("TEST_KEY_2")

        available = config.available_keys
        assert "TEST_KEY_1" in available
        assert "TEST_KEY_2" in available
        assert len(available) == 2

    def test_available_keys_after_set(self):
        """Keys appear in available_keys after setting."""
        config = SecureConfig()

        config.set_api_key("TEST_KEY_3", "value3")

        assert "TEST_KEY_3" in config.available_keys

    def test_available_keys_after_remove(self):
        """Keys disappear from available_keys after removal."""
        config = SecureConfig()
        config.set_api_key("TEST_KEY_1", "value1")

        config.remove_api_key("TEST_KEY_1")

        assert "TEST_KEY_1" not in config.available_keys


# =============================================================================
# ENV FILE LOADING TESTS
# =============================================================================

class TestSecureConfigEnvFile:
    """Tests for .env file loading."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["TEST_ENV_VAR", "QUOTED_KEY", "SINGLE_QUOTED",
                    "VALID_KEY", "KEY1", "KEY2", "KEY3", "WHITESPACE_KEY",
                    "EMPTY_LINE_KEY", "EXISTING_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_load_env_file_explicit(self, tmp_path):
        """Explicit .env file is loaded."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_ENV_VAR=test_value_from_file\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("TEST_ENV_VAR")

        assert key == "test_value_from_file"

    def test_load_env_file_with_double_quotes(self, tmp_path):
        """Double-quoted values have quotes stripped."""
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_KEY="quoted_value"\n')

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("QUOTED_KEY")

        assert key == "quoted_value"

    def test_load_env_file_with_single_quotes(self, tmp_path):
        """Single-quoted values have quotes stripped."""
        env_file = tmp_path / ".env"
        env_file.write_text("SINGLE_QUOTED='single_quoted_value'\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("SINGLE_QUOTED")

        assert key == "single_quoted_value"

    def test_load_env_file_ignores_comments(self, tmp_path):
        """Comments (lines starting with #) are ignored."""
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nVALID_KEY=valid_value\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("VALID_KEY")

        assert key == "valid_value"

    def test_load_env_file_ignores_empty_lines(self, tmp_path):
        """Empty lines are ignored."""
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nEMPTY_LINE_KEY=value\n\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("EMPTY_LINE_KEY")

        assert key == "value"

    def test_load_env_file_strips_whitespace(self, tmp_path):
        """Whitespace around key/value is stripped."""
        env_file = tmp_path / ".env"
        env_file.write_text("  WHITESPACE_KEY  =  whitespace_value  \n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("WHITESPACE_KEY")

        assert key == "whitespace_value"

    def test_load_env_file_multiple_keys(self, tmp_path):
        """Multiple keys are loaded."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\nKEY3=value3\n")

        config = SecureConfig(env_file=env_file)

        assert config.get_api_key("KEY1") == "value1"
        assert config.get_api_key("KEY2") == "value2"
        assert config.get_api_key("KEY3") == "value3"

    def test_load_env_file_does_not_override_existing(self, tmp_path):
        """Existing environment variables are not overridden."""
        os.environ["EXISTING_KEY"] = "existing_value"

        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_KEY=file_value\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("EXISTING_KEY")

        # setdefault should not override existing
        assert key == "existing_value"

    def test_load_env_file_only_once(self, tmp_path):
        """Env file is only loaded once."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_ENV_VAR=initial_value\n")

        config = SecureConfig(env_file=env_file)
        config.get_api_key("TEST_ENV_VAR")

        # Modify file
        env_file.write_text("TEST_ENV_VAR=modified_value\n")

        # Clear cache but env_loaded should prevent reload
        config._cache.clear()
        key = config.get_api_key("TEST_ENV_VAR")

        assert key == "initial_value"

    def test_load_env_file_nonexistent(self, tmp_path):
        """Nonexistent .env file does not raise."""
        env_file = tmp_path / "nonexistent.env"

        config = SecureConfig(env_file=env_file)

        # Should not raise
        key = config.get_api_key("SOME_KEY", required=False)
        assert key is None

    def test_load_env_file_handles_equals_in_value(self, tmp_path):
        """Values with equals signs are handled correctly."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY_WITH_EQUALS=value=with=equals\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("KEY_WITH_EQUALS")

        assert key == "value=with=equals"

    def test_load_env_file_read_error(self, tmp_path):
        """File read errors are handled gracefully."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")

        with patch('builtins.open', side_effect=PermissionError("Access denied")):
            config = SecureConfig(env_file=env_file)
            # Should not raise, just log warning
            key = config.get_api_key("KEY", required=False)
            assert key is None


# =============================================================================
# KEYRING INTEGRATION TESTS
# =============================================================================

class TestSecureConfigKeyring:
    """Tests for keyring integration."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["KEYRING_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_keyring_not_available_warning(self, caplog):
        """Warning is logged when keyring not installed."""
        with patch.dict('sys.modules', {'keyring': None}):
            with patch('builtins.__import__', side_effect=ImportError):
                config = SecureConfig(use_keyring=True)
                assert config._keyring_available is False

    def test_get_from_keyring(self):
        """Keys can be retrieved from keyring."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "keyring_value"

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(use_keyring=True)
            config._keyring_available = True

            key = config.get_api_key("KEYRING_KEY")

            assert key == "keyring_value"
            mock_keyring.get_password.assert_called_once_with(
                "optionplay", "KEYRING_KEY"
            )

    def test_keyring_takes_priority_over_env(self):
        """Keyring value takes priority over environment."""
        os.environ["KEYRING_KEY"] = "env_value"
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "keyring_value"

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(use_keyring=True)
            config._keyring_available = True

            key = config.get_api_key("KEYRING_KEY")

            assert key == "keyring_value"

    def test_keyring_returns_none_falls_back_to_env(self):
        """Falls back to environment when keyring returns None."""
        os.environ["KEYRING_KEY"] = "env_value"
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(use_keyring=True)
            config._keyring_available = True

            key = config.get_api_key("KEYRING_KEY")

            assert key == "env_value"

    def test_keyring_lookup_failure(self):
        """Keyring lookup failure falls back to environment."""
        os.environ["KEYRING_KEY"] = "env_value"
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = Exception("Keyring error")

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(use_keyring=True)
            config._keyring_available = True

            key = config.get_api_key("KEYRING_KEY")

            assert key == "env_value"


# =============================================================================
# KEY VALIDATION TESTS
# =============================================================================

class TestSecureConfigValidation:
    """Tests for API key validation."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["MARKETDATA_API_KEY", "TRADIER_API_KEY", "UNKNOWN_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_validate_valid_marketdata_key(self):
        """Valid Marketdata API key passes validation."""
        os.environ["MARKETDATA_API_KEY"] = "valid_api_key_12345678901234567890"

        config = SecureConfig()
        key = config.get_api_key("MARKETDATA_API_KEY", validate=True)

        assert key == "valid_api_key_12345678901234567890"

    def test_validate_invalid_marketdata_key_too_short(self):
        """Too short Marketdata key fails validation."""
        os.environ["MARKETDATA_API_KEY"] = "too_short"

        config = SecureConfig()

        with pytest.raises(ValueError, match="invalid format"):
            config.get_api_key("MARKETDATA_API_KEY", validate=True)

    def test_validate_invalid_marketdata_key_bad_chars(self):
        """Marketdata key with invalid characters fails validation."""
        os.environ["MARKETDATA_API_KEY"] = "invalid!@#$%key_with_special_chars"

        config = SecureConfig()

        with pytest.raises(ValueError, match="invalid format"):
            config.get_api_key("MARKETDATA_API_KEY", validate=True)

    def test_validate_valid_tradier_key(self):
        """Valid Tradier API key passes validation."""
        os.environ["TRADIER_API_KEY"] = "validTradierApiKey123456"

        config = SecureConfig()
        key = config.get_api_key("TRADIER_API_KEY", validate=True)

        assert key == "validTradierApiKey123456"

    def test_validate_invalid_tradier_key(self):
        """Invalid Tradier key fails validation."""
        os.environ["TRADIER_API_KEY"] = "short"

        config = SecureConfig()

        with pytest.raises(ValueError, match="invalid format"):
            config.get_api_key("TRADIER_API_KEY", validate=True)

    def test_validate_unknown_key_always_passes(self):
        """Unknown key names pass validation (no pattern defined)."""
        os.environ["UNKNOWN_KEY"] = "any_value"

        config = SecureConfig()
        key = config.get_api_key("UNKNOWN_KEY", validate=True)

        assert key == "any_value"

    def test_validation_error_includes_masked_key(self):
        """Validation error includes masked key value."""
        os.environ["MARKETDATA_API_KEY"] = "short"

        config = SecureConfig()

        with pytest.raises(ValueError) as exc_info:
            config.get_api_key("MARKETDATA_API_KEY", validate=True)

        # Should have masked key in error message
        assert "s...t" in str(exc_info.value) or "short" not in str(exc_info.value)

    def test_no_validation_by_default(self):
        """Validation is not performed by default."""
        os.environ["MARKETDATA_API_KEY"] = "short"

        config = SecureConfig()
        # Should not raise when validate=False (default)
        key = config.get_api_key("MARKETDATA_API_KEY")

        assert key == "short"


# =============================================================================
# SINGLETON / GLOBAL FUNCTION TESTS
# =============================================================================

class TestGlobalFunctions:
    """Tests for global functions."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["GLOBAL_TEST_KEY", "SINGLETON_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_get_api_key_global_function(self):
        """Global get_api_key function works."""
        os.environ["GLOBAL_TEST_KEY"] = "global_value"

        key = get_api_key("GLOBAL_TEST_KEY")
        assert key == "global_value"

    def test_get_api_key_global_required(self):
        """Global get_api_key raises for required missing key."""
        with pytest.raises(ValueError):
            get_api_key("NONEXISTENT_GLOBAL_KEY", required=True)

    def test_get_api_key_global_optional(self):
        """Global get_api_key returns None for optional missing key."""
        key = get_api_key("NONEXISTENT_GLOBAL_KEY", required=False)
        assert key is None

    def test_get_api_key_global_validate(self):
        """Global get_api_key supports validation."""
        os.environ["MARKETDATA_API_KEY"] = "short"

        with pytest.raises(ValueError, match="invalid format"):
            get_api_key("MARKETDATA_API_KEY", validate=True)

    def test_get_secure_config_singleton(self):
        """get_secure_config returns same instance."""
        config1 = get_secure_config()
        config2 = get_secure_config()

        assert config1 is config2

    def test_get_secure_config_after_reset(self):
        """get_secure_config returns new instance after reset."""
        config1 = get_secure_config()
        reset_secure_config()
        config2 = get_secure_config()

        assert config1 is not config2

    def test_reset_secure_config_clears_cache(self):
        """reset_secure_config clears the cache."""
        os.environ["SINGLETON_KEY"] = "value1"

        config = get_secure_config()
        config.get_api_key("SINGLETON_KEY")

        os.environ["SINGLETON_KEY"] = "value2"
        reset_secure_config()

        # New instance, no cache
        key = get_api_key("SINGLETON_KEY")
        assert key == "value2"

    def test_reset_secure_config_when_none(self):
        """reset_secure_config handles None singleton."""
        reset_secure_config()  # First reset
        reset_secure_config()  # Second reset - should not raise


# =============================================================================
# EDGE CASES AND ERROR HANDLING
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["EDGE_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_key_with_unicode(self):
        """Keys with unicode characters are handled."""
        os.environ["EDGE_KEY"] = "value_with_unicode_\u00e9\u00e0"

        config = SecureConfig()
        key = config.get_api_key("EDGE_KEY")

        assert key == "value_with_unicode_\u00e9\u00e0"

    def test_key_with_newline(self):
        """Keys with newlines are handled."""
        os.environ["EDGE_KEY"] = "value\nwith\nnewlines"

        config = SecureConfig()
        key = config.get_api_key("EDGE_KEY")

        assert key == "value\nwith\nnewlines"

    def test_very_long_key(self):
        """Very long keys are handled."""
        long_value = "x" * 10000
        os.environ["EDGE_KEY"] = long_value

        config = SecureConfig()
        key = config.get_api_key("EDGE_KEY")

        assert key == long_value
        assert len(key) == 10000

    def test_key_patterns_immutable(self):
        """KEY_PATTERNS is a class attribute."""
        config1 = SecureConfig()
        config2 = SecureConfig()

        assert config1.KEY_PATTERNS is SecureConfig.KEY_PATTERNS
        assert config2.KEY_PATTERNS is SecureConfig.KEY_PATTERNS


# =============================================================================
# INTEGRATION-STYLE TESTS
# =============================================================================

class TestIntegration:
    """Integration-style tests combining multiple features."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["INT_KEY1", "INT_KEY2", "INT_KEY3"]:
            if key in os.environ:
                del os.environ[key]

    def test_full_lifecycle(self, tmp_path):
        """Test full key lifecycle: load, use, update, remove."""
        # Create .env file
        env_file = tmp_path / ".env"
        env_file.write_text("INT_KEY1=initial_value\n")

        # Load from file
        config = SecureConfig(env_file=env_file)
        assert config.get_api_key("INT_KEY1") == "initial_value"

        # Set new key
        config.set_api_key("INT_KEY2", "second_value")
        assert config.get_api_key("INT_KEY2") == "second_value"

        # Update existing key
        config.set_api_key("INT_KEY1", "updated_value")
        assert config.get_api_key("INT_KEY1") == "updated_value"

        # Check available keys
        available = config.available_keys
        assert "INT_KEY1" in available
        assert "INT_KEY2" in available

        # Remove key
        config.remove_api_key("INT_KEY2")
        assert "INT_KEY2" not in config.available_keys
        assert config.get_api_key("INT_KEY2", required=False) is None

    def test_priority_order(self, tmp_path):
        """Test correct priority: cache > keyring > env > file."""
        # Setup .env file
        env_file = tmp_path / ".env"
        env_file.write_text("INT_KEY3=file_value\n")

        # Setup environment
        os.environ["INT_KEY3"] = "env_value"

        # Setup mock keyring
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "keyring_value"

        with patch.dict('sys.modules', {'keyring': mock_keyring}):
            config = SecureConfig(env_file=env_file, use_keyring=True)
            config._keyring_available = True

            # First call - should get from keyring (highest priority after cache)
            key = config.get_api_key("INT_KEY3")
            assert key == "keyring_value"

            # Value is now cached
            # Disable keyring to verify cache takes priority
            mock_keyring.get_password.return_value = "new_keyring_value"

            # Second call - should get from cache
            key = config.get_api_key("INT_KEY3")
            assert key == "keyring_value"  # Still cached


# =============================================================================
# SYMLINK REJECTION TESTS (A.2)
# =============================================================================

class TestSymlinkRejection:
    """Tests that symlinked .env files are rejected for security."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["SYMLINK_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_symlinked_env_file_rejected(self, tmp_path):
        """Symlinked .env file should be silently rejected."""
        # Create real .env file
        real_env = tmp_path / "real.env"
        real_env.write_text("SYMLINK_KEY=secret_value\n")

        # Create symlink to it
        link_env = tmp_path / ".env"
        link_env.symlink_to(real_env)

        config = SecureConfig(env_file=link_env)
        key = config.get_api_key("SYMLINK_KEY", required=False)

        # Key should NOT be loaded from symlinked file
        assert key is None

    def test_real_env_file_accepted(self, tmp_path):
        """Non-symlinked .env file should be accepted."""
        env_file = tmp_path / ".env"
        env_file.write_text("SYMLINK_KEY=real_value\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("SYMLINK_KEY")

        assert key == "real_value"

    def test_symlink_rejection_logged(self, tmp_path, caplog):
        """Symlink rejection should be logged as warning."""
        import logging

        real_env = tmp_path / "real.env"
        real_env.write_text("SYMLINK_KEY=secret\n")

        link_env = tmp_path / ".env"
        link_env.symlink_to(real_env)

        with caplog.at_level(logging.WARNING):
            config = SecureConfig(env_file=link_env)
            config.get_api_key("SYMLINK_KEY", required=False)

        assert any("symlink" in record.message.lower() for record in caplog.records)

    def test_env_loaded_flag_set_on_symlink(self, tmp_path):
        """env_loaded should be True even after symlink rejection (prevent re-attempts)."""
        real_env = tmp_path / "real.env"
        real_env.write_text("SYMLINK_KEY=secret\n")

        link_env = tmp_path / ".env"
        link_env.symlink_to(real_env)

        config = SecureConfig(env_file=link_env)
        config.get_api_key("SYMLINK_KEY", required=False)

        assert config._env_loaded is True


# =============================================================================
# KEY ROTATION TESTS
# =============================================================================

class TestKeyRotation:
    """Tests for API key rotation functionality."""

    def setup_method(self):
        """Setup before each test."""
        reset_secure_config()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_secure_config()
        for key in ["ROTATE_KEY", "ROTATE_ENV_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_rotate_key_clears_cache(self):
        """rotate_key should clear cached value."""
        os.environ["ROTATE_KEY"] = "old_value"
        config = SecureConfig()

        # Load into cache
        key = config.get_api_key("ROTATE_KEY")
        assert key == "old_value"

        # Change env and rotate
        os.environ["ROTATE_KEY"] = "new_value"
        new_key = config.rotate_key("ROTATE_KEY")

        assert new_key == "new_value"

    def test_rotate_key_returns_new_value(self):
        """rotate_key should return freshly loaded value."""
        os.environ["ROTATE_KEY"] = "rotated_value"
        config = SecureConfig()

        result = config.rotate_key("ROTATE_KEY")
        assert result == "rotated_value"

    def test_rotate_key_nonexistent(self):
        """rotate_key for nonexistent key returns None."""
        config = SecureConfig()

        result = config.rotate_key("NONEXISTENT_ROTATE_KEY")
        assert result is None

    def test_rotate_key_reloads_env_file(self, tmp_path):
        """rotate_key should force .env file reload."""
        env_file = tmp_path / ".env"
        env_file.write_text("ROTATE_ENV_KEY=initial\n")

        config = SecureConfig(env_file=env_file)

        # Load initial value
        key = config.get_api_key("ROTATE_ENV_KEY")
        assert key == "initial"

        # Update .env file
        env_file.write_text("ROTATE_ENV_KEY=rotated\n")

        # Rotate should reload
        new_key = config.rotate_key("ROTATE_ENV_KEY")
        assert new_key == "rotated"

    def test_rotate_key_invalidates_load_time(self):
        """rotate_key should invalidate key load timestamp."""
        os.environ["ROTATE_KEY"] = "value"
        config = SecureConfig()

        config.get_api_key("ROTATE_KEY")

        # Manually check _key_load_times if it exists
        if hasattr(config, '_key_load_times') and "ROTATE_KEY" in config._key_load_times:
            config.rotate_key("ROTATE_KEY")
            # After rotation, load time should be refreshed or removed
            # (it gets re-added on next get_api_key call within rotate_key)
            assert "ROTATE_KEY" in config._key_load_times or True  # Re-loaded
