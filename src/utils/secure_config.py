# OptionPlay - Secure Configuration
# ===================================
# Sichere Verwaltung von API-Keys und sensiblen Daten
#
# Features:
# - Lazy Loading von API-Keys (nur bei Bedarf)
# - Maskierung für Logging
# - Optional: Keyring-Integration für sichere Speicherung
# - Validierung von API-Keys
#
# Verwendung:
#     from utils.secure_config import get_api_key, mask_api_key
#
#     key = get_api_key("MARKETDATA_API_KEY")
#     logger.info(f"Using key: {mask_api_key(key)}")

import os
import logging
from datetime import datetime
from typing import Optional, Dict, Callable
from pathlib import Path
from functools import lru_cache
import re

logger = logging.getLogger(__name__)


# =============================================================================
# API KEY MASKING
# =============================================================================

def mask_api_key(key: Optional[str], visible_chars: int = 4) -> str:
    """
    Maskiert einen API-Key für sicheres Logging.
    
    Args:
        key: Der zu maskierende Key
        visible_chars: Anzahl sichtbarer Zeichen am Anfang und Ende
        
    Returns:
        Maskierter String, z.B. "abc1...xyz9"
        
    Examples:
        >>> mask_api_key("abcdefghijklmnop")
        'abcd...mnop'
        >>> mask_api_key("short")
        's...t'
        >>> mask_api_key(None)
        '<not set>'
    """
    if key is None:
        return "<not set>"
    
    if len(key) <= visible_chars * 2:
        # Sehr kurzer Key - zeige nur ersten und letzten Char
        if len(key) <= 2:
            return "*" * len(key)
        return f"{key[0]}...{key[-1]}"
    
    return f"{key[:visible_chars]}...{key[-visible_chars:]}"


def mask_sensitive_data(text: str, patterns: Optional[list] = None) -> str:
    """
    Maskiert sensible Daten in einem Text.
    
    Nützlich für Log-Sanitization.
    
    Args:
        text: Der zu bereinigende Text
        patterns: Regex-Patterns für sensible Daten (Tupel aus Pattern und Replacement)
        
    Returns:
        Text mit maskierten sensiblen Daten
    """
    if patterns is None:
        patterns = [
            # API Keys (typisches Format) - ersetze komplett
            (r'[A-Za-z0-9_-]{20,}', '***MASKED***'),
            # Bearer Tokens - behalte "Bearer " prefix
            (r'(Bearer\s+)[A-Za-z0-9_.-]+', r'\1***MASKED***'),
            # Authorization Headers - behalte "Authorization: " prefix
            (r'(Authorization:\s*)[^\s]+', r'\1***MASKED***'),
        ]
    
    result = text
    for pattern_tuple in patterns:
        if isinstance(pattern_tuple, tuple):
            pattern, replacement = pattern_tuple
        else:
            # Legacy: nur Pattern, Standard-Replacement
            pattern = pattern_tuple
            replacement = '***MASKED***'
        result = re.sub(pattern, replacement, result)
    
    return result


# =============================================================================
# SECURE CONFIG CLASS
# =============================================================================

class SecureConfig:
    """
    Sichere Konfigurationsverwaltung.
    
    Features:
    - Lazy Loading von API-Keys
    - Caching mit Invalidierung
    - Keyring-Support (optional)
    - Validierung
    
    Verwendung:
        config = SecureConfig()
        
        # Key wird erst bei Zugriff geladen
        key = config.get_api_key("MARKETDATA_API_KEY")
        
        # Mit Validierung
        key = config.get_api_key("MARKETDATA_API_KEY", validate=True)
    """
    
    # Bekannte API-Key Formate für Validierung
    KEY_PATTERNS = {
        "MARKETDATA_API_KEY": r'^[A-Za-z0-9_-]{20,100}$',
        "TRADIER_API_KEY": r'^[A-Za-z0-9]{20,50}$',
    }
    
    def __init__(
        self,
        env_file: Optional[Path] = None,
        use_keyring: bool = False,
        keyring_service: str = "optionplay"
    ):
        """
        Initialisiert SecureConfig.
        
        Args:
            env_file: Pfad zur .env Datei (optional)
            use_keyring: Keyring für sichere Speicherung nutzen
            keyring_service: Service-Name für Keyring
        """
        self._env_file = env_file
        self._use_keyring = use_keyring
        self._keyring_service = keyring_service
        self._cache: Dict[str, str] = {}
        self._key_load_times: Dict[str, datetime] = {}
        self._env_loaded = False
        
        # Keyring verfügbar?
        self._keyring_available = False
        if use_keyring:
            try:
                import keyring
                self._keyring_available = True
            except ImportError:
                logger.warning(
                    "Keyring requested but not installed. "
                    "Install with: pip install keyring"
                )
    
    def _load_env_file(self) -> None:
        """Lädt .env Datei wenn vorhanden."""
        if self._env_loaded:
            return

        env_file = self._env_file
        if env_file is None:
            # Standard-Pfade versuchen - priorisiere Projekt-Root
            # __file__ ist src/utils/secure_config.py, also parent.parent.parent = Projekt-Root
            project_root = Path(__file__).parent.parent.parent.resolve()
            possible_paths = [
                project_root / ".env",  # Projekt-Root (höchste Priorität)
                Path.cwd() / ".env",
                Path.cwd().parent / ".env",
                Path.home() / ".optionplay" / ".env",  # User config dir
            ]
            for path in possible_paths:
                if path.exists():
                    env_file = path
                    logger.debug(f"Found .env at: {path}")
                    break
        
        if env_file and env_file.exists():
            # Security: reject symlinks to prevent path traversal attacks
            if env_file.is_symlink():
                logger.warning("Rejected symlinked .env file: %s", env_file)
                self._env_loaded = True
                return
            env_file = env_file.resolve()
            try:
                with open(env_file) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip()
                            # Quotes entfernen
                            if value.startswith('"') and value.endswith('"'):
                                value = value[1:-1]
                            elif value.startswith("'") and value.endswith("'"):
                                value = value[1:-1]
                            os.environ.setdefault(key, value)
                logger.debug(f"Loaded env file: {env_file}")
            except Exception as e:
                logger.warning(f"Failed to load env file {env_file}: {e}")
        
        self._env_loaded = True
    
    def _get_from_keyring(self, key_name: str) -> Optional[str]:
        """Holt Key aus Keyring."""
        if not self._keyring_available:
            return None
        
        try:
            import keyring
            return keyring.get_password(self._keyring_service, key_name)
        except Exception as e:
            logger.debug(f"Keyring lookup failed for {key_name}: {e}")
            return None
    
    def _validate_key(self, key_name: str, value: str) -> bool:
        """
        Validiert API-Key Format.
        
        Returns:
            True wenn gültig oder kein Pattern definiert
        """
        pattern = self.KEY_PATTERNS.get(key_name)
        if pattern is None:
            return True
        
        return bool(re.match(pattern, value))
    
    def get_api_key(
        self,
        key_name: str,
        required: bool = True,
        validate: bool = False
    ) -> Optional[str]:
        """
        Holt API-Key mit Lazy Loading.
        
        Reihenfolge:
        1. Cache
        2. Keyring (wenn aktiviert)
        3. Environment Variable
        4. .env Datei
        
        Args:
            key_name: Name des Keys (z.B. "MARKETDATA_API_KEY")
            required: Wenn True, wirft Exception wenn nicht gefunden
            validate: Wenn True, validiert Key-Format
            
        Returns:
            API-Key oder None
            
        Raises:
            ValueError: Wenn required=True und Key nicht gefunden
            ValueError: Wenn validate=True und Key ungültig
        """
        # 1. Cache prüfen
        if key_name in self._cache:
            return self._cache[key_name]
        
        value = None
        source = None
        
        # 2. Keyring versuchen
        if self._use_keyring:
            value = self._get_from_keyring(key_name)
            if value:
                source = "keyring"
        
        # 3. Environment Variable
        if value is None:
            value = os.environ.get(key_name)
            if value:
                source = "environment"
        
        # 4. .env Datei laden und nochmal prüfen
        if value is None:
            self._load_env_file()
            value = os.environ.get(key_name)
            if value:
                source = "env_file"
        
        # Nicht gefunden
        if value is None:
            if required:
                raise ValueError(
                    f"API key '{key_name}' not found. "
                    f"Set it via environment variable or .env file."
                )
            return None
        
        # Validierung
        if validate and not self._validate_key(key_name, value):
            raise ValueError(
                f"API key '{key_name}' has invalid format. "
                f"Got: {mask_api_key(value)}"
            )
        
        # Cachen und zurückgeben
        self._cache[key_name] = value
        self._key_load_times[key_name] = datetime.now()
        logger.debug(f"Loaded {key_name} from {source}: {mask_api_key(value)}")
        logger.info("API key loaded for provider: %s (source: %s)", key_name, source)

        return value
    
    def set_api_key(
        self,
        key_name: str,
        value: str,
        persist: bool = False
    ) -> None:
        """
        Setzt API-Key.
        
        Args:
            key_name: Name des Keys
            value: Wert
            persist: Wenn True, in Keyring speichern (wenn verfügbar)
        """
        self._cache[key_name] = value
        os.environ[key_name] = value
        logger.info("API key set for provider: %s", key_name)

        if persist and self._keyring_available:
            try:
                import keyring
                keyring.set_password(self._keyring_service, key_name, value)
                logger.info(f"Saved {key_name} to keyring")
            except Exception as e:
                logger.warning(f"Failed to save {key_name} to keyring: {e}")
    
    def rotate_key(self, key_name: str) -> Optional[str]:
        """
        Rotiert einen API-Key: invalidiert Cache und lädt neu aus Environment/.env.

        Args:
            key_name: Name des zu rotierenden Keys

        Returns:
            Neuer Key-Wert oder None wenn nicht gefunden
        """
        # Cache und Load-Time invalidieren
        if key_name in self._cache:
            del self._cache[key_name]
        if key_name in self._key_load_times:
            del self._key_load_times[key_name]

        # .env neu laden erzwingen: alten Wert aus os.environ entfernen,
        # damit setdefault() den neuen Wert aus der .env-Datei übernimmt
        if self._env_file is not None or self._env_loaded:
            os.environ.pop(key_name, None)
        self._env_loaded = False

        # Key neu laden
        value = self.get_api_key(key_name, required=False)
        logger.info("API key rotated for provider: %s", key_name)
        return value

    def check_key_age(self, key_name: str, max_age_days: int = 90) -> bool:
        """
        Prüft ob ein Key innerhalb des Alters-Limits liegt.

        Args:
            key_name: Name des Keys
            max_age_days: Maximales Alter in Tagen (default: 90)

        Returns:
            True wenn Key innerhalb des Limits oder nicht geladen,
            False wenn Key älter als max_age_days
        """
        load_time = self._key_load_times.get(key_name)
        if load_time is None:
            return True

        age = datetime.now() - load_time
        age_days = age.days

        if age_days > max_age_days:
            logger.warning(
                "API key for %s was loaded %d days ago (max: %d)",
                key_name, age_days, max_age_days
            )
            return False

        return True

    def clear_cache(self) -> None:
        """Leert den Key-Cache."""
        self._cache.clear()
    
    def remove_api_key(self, key_name: str) -> None:
        """
        Entfernt API-Key aus Cache, Environment und optional Keyring.
        """
        if key_name in self._cache:
            del self._cache[key_name]
        
        if key_name in os.environ:
            del os.environ[key_name]
        
        if self._keyring_available:
            try:
                import keyring
                keyring.delete_password(self._keyring_service, key_name)
            except Exception as e:
                logger.debug(f"Failed to delete {key_name} from keyring: {e}")
    
    @property
    def available_keys(self) -> list:
        """Liste der geladenen Key-Namen (nicht die Werte!)."""
        return list(self._cache.keys())


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_default_config: Optional[SecureConfig] = None


def get_secure_config(
    env_file: Optional[Path] = None,
    use_keyring: bool = False
) -> SecureConfig:
    """
    Gibt globale SecureConfig-Instanz zurück.

    .. deprecated:: 3.5.0
        Use ``ServiceContainer`` instead. Will be removed in v4.0.

    Erstellt bei Bedarf eine neue Instanz.
    """
    try:
        from .deprecation import warn_singleton_usage
        warn_singleton_usage("get_secure_config", "ServiceContainer.secure_config")
    except ImportError:
        pass

    global _default_config

    if _default_config is None:
        _default_config = SecureConfig(
            env_file=env_file,
            use_keyring=use_keyring
        )

    return _default_config


def get_api_key(
    key_name: str,
    required: bool = True,
    validate: bool = False
) -> Optional[str]:
    """
    Convenience-Funktion für API-Key Abruf.
    
    Verwendet die globale SecureConfig-Instanz.
    
    Examples:
        >>> key = get_api_key("MARKETDATA_API_KEY")
        >>> key = get_api_key("OPTIONAL_KEY", required=False)
    """
    return get_secure_config().get_api_key(key_name, required, validate)


def reset_secure_config() -> None:
    """Setzt globale SecureConfig zurück (für Tests)."""
    global _default_config
    if _default_config:
        _default_config.clear_cache()
    _default_config = None
