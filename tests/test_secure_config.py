# OptionPlay - Secure Config Tests
# ==================================
# Tests für sichere API-Key Verwaltung

import os
import pytest
from pathlib import Path
from src.utils.secure_config import (
    SecureConfig,
    mask_api_key,
    mask_sensitive_data,
    get_api_key,
    reset_secure_config,
)


class TestMaskApiKey:
    """Tests für mask_api_key()"""
    
    def test_normal_key(self):
        """Normale Keys werden maskiert"""
        key = "abcdefghijklmnop"
        masked = mask_api_key(key)
        assert masked == "abcd...mnop"
        assert "efgh" not in masked  # Mittelteil nicht sichtbar
    
    def test_short_key(self):
        """Kurze Keys werden anders maskiert"""
        assert mask_api_key("ab") == "**"
        assert mask_api_key("abc") == "a...c"
        assert mask_api_key("abcd") == "a...d"
    
    def test_none_key(self):
        """None gibt '<not set>' zurück"""
        assert mask_api_key(None) == "<not set>"
    
    def test_custom_visible_chars(self):
        """Benutzerdefinierte Anzahl sichtbarer Zeichen"""
        key = "abcdefghijklmnopqrstuvwxyz"
        assert mask_api_key(key, visible_chars=2) == "ab...yz"
        assert mask_api_key(key, visible_chars=6) == "abcdef...uvwxyz"


class TestMaskSensitiveData:
    """Tests für mask_sensitive_data()"""
    
    def test_masks_long_strings(self):
        """Lange alphanumerische Strings werden maskiert"""
        text = "The key is abcdefghijklmnopqrstuvwxyz12345"
        masked = mask_sensitive_data(text)
        assert "abcdefghijklmnopqrstuvwxyz12345" not in masked
    
    def test_masks_bearer_tokens(self):
        """Bearer Tokens werden maskiert"""
        text = "Authorization: Bearer abc123xyz789token"
        masked = mask_sensitive_data(text)
        assert "abc123xyz789token" not in masked


class TestSecureConfig:
    """Tests für SecureConfig Klasse"""
    
    def setup_method(self):
        """Setup vor jedem Test"""
        reset_secure_config()
        # Backup und Clear environment
        self._env_backup = os.environ.get("TEST_API_KEY")
        if "TEST_API_KEY" in os.environ:
            del os.environ["TEST_API_KEY"]
    
    def teardown_method(self):
        """Cleanup nach jedem Test"""
        reset_secure_config()
        if "TEST_API_KEY" in os.environ:
            del os.environ["TEST_API_KEY"]
        if self._env_backup:
            os.environ["TEST_API_KEY"] = self._env_backup
    
    def test_get_from_environment(self):
        """Keys werden aus Environment geladen"""
        os.environ["TEST_API_KEY"] = "test_value_12345"
        config = SecureConfig()
        
        key = config.get_api_key("TEST_API_KEY")
        assert key == "test_value_12345"
    
    def test_caching(self):
        """Keys werden gecached"""
        os.environ["TEST_API_KEY"] = "cached_value"
        config = SecureConfig()
        
        key1 = config.get_api_key("TEST_API_KEY")
        
        # Environment ändern
        os.environ["TEST_API_KEY"] = "changed_value"
        
        # Gecachter Wert bleibt
        key2 = config.get_api_key("TEST_API_KEY")
        assert key2 == "cached_value"
    
    def test_clear_cache(self):
        """Cache kann geleert werden"""
        os.environ["TEST_API_KEY"] = "initial_value"
        config = SecureConfig()
        
        config.get_api_key("TEST_API_KEY")
        os.environ["TEST_API_KEY"] = "new_value"
        config.clear_cache()
        
        key = config.get_api_key("TEST_API_KEY")
        assert key == "new_value"
    
    def test_required_key_missing(self):
        """Fehlender required Key wirft ValueError"""
        config = SecureConfig()
        
        with pytest.raises(ValueError, match="not found"):
            config.get_api_key("NONEXISTENT_KEY", required=True)
    
    def test_optional_key_missing(self):
        """Fehlender optional Key gibt None zurück"""
        config = SecureConfig()
        
        key = config.get_api_key("NONEXISTENT_KEY", required=False)
        assert key is None
    
    def test_set_api_key(self):
        """Keys können gesetzt werden"""
        config = SecureConfig()
        
        config.set_api_key("NEW_KEY", "new_value_123")
        
        assert config.get_api_key("NEW_KEY") == "new_value_123"
        assert os.environ.get("NEW_KEY") == "new_value_123"
        
        # Cleanup
        del os.environ["NEW_KEY"]
    
    def test_available_keys(self):
        """Geladene Keys werden aufgelistet"""
        os.environ["TEST_KEY_1"] = "value1"
        os.environ["TEST_KEY_2"] = "value2"
        config = SecureConfig()
        
        config.get_api_key("TEST_KEY_1")
        config.get_api_key("TEST_KEY_2")
        
        available = config.available_keys
        assert "TEST_KEY_1" in available
        assert "TEST_KEY_2" in available
        
        # Cleanup
        del os.environ["TEST_KEY_1"]
        del os.environ["TEST_KEY_2"]


class TestGlobalGetApiKey:
    """Tests für die globale get_api_key() Funktion"""

    def setup_method(self):
        reset_secure_config()

    def teardown_method(self):
        reset_secure_config()
        if "GLOBAL_TEST_KEY" in os.environ:
            del os.environ["GLOBAL_TEST_KEY"]

    def test_global_function(self):
        """Globale Funktion nutzt Singleton"""
        os.environ["GLOBAL_TEST_KEY"] = "global_value"

        key = get_api_key("GLOBAL_TEST_KEY")
        assert key == "global_value"


class TestSecureConfigEnvFile:
    """Tests für .env file loading."""

    def setup_method(self):
        reset_secure_config()

    def teardown_method(self):
        reset_secure_config()

    def test_load_env_file_explicit(self, tmp_path):
        """Test: Loading explicit .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_ENV_VAR=test_value_from_file\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("TEST_ENV_VAR")

        assert key == "test_value_from_file"

        # Cleanup
        if "TEST_ENV_VAR" in os.environ:
            del os.environ["TEST_ENV_VAR"]

    def test_load_env_file_with_quotes(self, tmp_path):
        """Test: .env file with quoted values."""
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_KEY="quoted_value"\n')

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("QUOTED_KEY")

        assert key == "quoted_value"

        if "QUOTED_KEY" in os.environ:
            del os.environ["QUOTED_KEY"]

    def test_load_env_file_with_single_quotes(self, tmp_path):
        """Test: .env file with single-quoted values."""
        env_file = tmp_path / ".env"
        env_file.write_text("SINGLE_QUOTED='single_quoted_value'\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("SINGLE_QUOTED")

        assert key == "single_quoted_value"

        if "SINGLE_QUOTED" in os.environ:
            del os.environ["SINGLE_QUOTED"]

    def test_load_env_file_ignores_comments(self, tmp_path):
        """Test: .env file ignores comments."""
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nVALID_KEY=valid_value\n")

        config = SecureConfig(env_file=env_file)
        key = config.get_api_key("VALID_KEY")

        assert key == "valid_value"

        if "VALID_KEY" in os.environ:
            del os.environ["VALID_KEY"]


class TestSecureConfigKeyring:
    """Tests für Keyring integration."""

    def setup_method(self):
        reset_secure_config()

    def teardown_method(self):
        reset_secure_config()

    def test_keyring_not_available_warning(self):
        """Test: Keyring warning when not installed."""
        # Keyring may or may not be installed, but the config should handle it
        config = SecureConfig(use_keyring=True)
        # Should not raise - just warns if keyring not available


class TestSecureConfigValidation:
    """Tests für API key validation."""

    def setup_method(self):
        reset_secure_config()

    def teardown_method(self):
        reset_secure_config()
        for key in ["MARKETDATA_API_KEY", "TRADIER_API_KEY", "UNKNOWN_KEY"]:
            if key in os.environ:
                del os.environ[key]

    def test_validate_valid_marketdata_key(self):
        """Test: Valid Marketdata API key passes validation."""
        os.environ["MARKETDATA_API_KEY"] = "valid_api_key_12345678901234567890"

        config = SecureConfig()
        key = config.get_api_key("MARKETDATA_API_KEY", validate=True)

        assert key == "valid_api_key_12345678901234567890"

    def test_validate_invalid_key_format(self):
        """Test: Invalid key format raises ValueError."""
        os.environ["MARKETDATA_API_KEY"] = "too_short"

        config = SecureConfig()

        with pytest.raises(ValueError, match="invalid format"):
            config.get_api_key("MARKETDATA_API_KEY", validate=True)

    def test_validate_unknown_key_passes(self):
        """Test: Unknown key names pass validation (no pattern defined)."""
        os.environ["UNKNOWN_KEY"] = "any_value"

        config = SecureConfig()
        key = config.get_api_key("UNKNOWN_KEY", validate=True)

        assert key == "any_value"


class TestMaskSensitiveDataExtended:
    """Extended tests for mask_sensitive_data()."""

    def test_custom_patterns(self):
        """Test: Custom patterns for masking."""
        text = "Secret: password123"
        patterns = [(r'password\d+', '***')]

        masked = mask_sensitive_data(text, patterns=patterns)

        assert "password123" not in masked
        assert "***" in masked

    def test_legacy_pattern_format(self):
        """Test: Legacy pattern format (string only)."""
        text = "Token: abc123456789xyz"
        patterns = [r'abc\d+xyz']

        masked = mask_sensitive_data(text, patterns=patterns)

        assert "abc123456789xyz" not in masked

    def test_preserves_safe_text(self):
        """Test: Safe text is preserved."""
        text = "This is safe text without secrets"

        masked = mask_sensitive_data(text)

        # Short strings should be preserved
        assert "This is safe text" in masked
