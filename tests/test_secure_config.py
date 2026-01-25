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
