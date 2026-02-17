# OptionPlay - MCP Server Integration Tests
# ==========================================
# Tests für das Zusammenspiel der neuen Features im MCP Server

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from src.constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS

# Diese Tests prüfen die Integration der neuen Features:
# - Circuit Breaker
# - Historical Cache
# - Config-basierte Parameter
# - Validation


class TestMCPServerInitialization:
    """Tests für MCP Server Initialisierung mit neuen Features"""
    
    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Mock environment variables"""
        monkeypatch.setenv("MARKETDATA_API_KEY", "test_api_key_12345")
    
    def test_server_initializes_circuit_breaker(self, mock_env):
        """Server sollte Circuit Breaker initialisieren"""
        from src.mcp_server import OptionPlayServer
        from src.utils.circuit_breaker import CircuitBreaker
        
        with patch('src.mcp_server.get_config') as mock_config:
            # Mock config
            mock_settings = Mock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 500
            mock_settings.api_connection.max_retries = 3
            mock_settings.api_connection.retry_base_delay = 2
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 60
            mock_config.return_value.settings = mock_settings
            
            server = OptionPlayServer(api_key="test_key")
            
            assert hasattr(server, '_circuit_breaker')
            assert isinstance(server._circuit_breaker, CircuitBreaker)
    
    def test_server_initializes_cache(self, mock_env):
        """Server sollte Historical Cache initialisieren"""
        from src.mcp_server import OptionPlayServer
        from src.cache.historical_cache import HistoricalCache
        
        with patch('src.mcp_server.get_config') as mock_config:
            mock_settings = Mock()
            mock_settings.performance.cache_ttl_seconds = 600
            mock_settings.performance.cache_max_entries = 1000
            mock_settings.api_connection.max_retries = 3
            mock_settings.api_connection.retry_base_delay = 2
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 60
            mock_config.return_value.settings = mock_settings
            
            server = OptionPlayServer(api_key="test_key")
            
            assert hasattr(server, '_historical_cache')
            assert isinstance(server._historical_cache, HistoricalCache)


class TestCircuitBreakerIntegration:
    """Tests für Circuit Breaker Integration"""
    
    def test_circuit_breaker_blocks_when_open(self):
        """Circuit Breaker sollte Requests blockieren wenn offen"""
        from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
        
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        
        # Öffne den Circuit
        breaker.record_failure()
        breaker.record_failure()
        
        assert breaker.is_open
        assert not breaker.can_execute()
        
        with pytest.raises(CircuitBreakerOpen):
            with breaker:
                pass
    
    def test_circuit_breaker_allows_after_recovery(self):
        """Circuit Breaker sollte Requests nach Recovery erlauben"""
        from src.utils.circuit_breaker import CircuitBreaker
        import time
        
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.5,  # 500ms für schnellen Test
            success_threshold=1
        )
        
        # Öffne den Circuit
        breaker.record_failure()
        assert breaker.is_open
        
        # Simulate recovery timeout elapsed
        breaker._opened_at = datetime.now() - timedelta(seconds=1)

        # Sollte jetzt Half-Open sein
        assert breaker.is_half_open
        assert breaker.can_execute()
        
        # Erfolg sollte schließen
        breaker.record_success()
        assert breaker.is_closed


class TestHistoricalCacheIntegration:
    """Tests für Historical Cache Integration"""
    
    def test_cache_stores_and_retrieves(self):
        """Cache sollte Daten speichern und abrufen"""
        from src.cache.historical_cache import HistoricalCache, CacheStatus
        
        cache = HistoricalCache(ttl_seconds=60)
        
        # Sample data
        data = (
            [100.0, 101.0, 102.0],  # prices
            [1000, 1100, 1200],      # volumes
            [101.0, 102.0, 103.0],   # highs
            [99.0, 100.0, 101.0]     # lows
        )
        
        cache.set("AAPL", data, days=60)
        result = cache.get("AAPL", days=60)
        
        assert result.status == CacheStatus.HIT
        assert result.data == data
    
    def test_cache_accepts_larger_data(self):
        """Cache sollte größere Daten für kleinere Anfragen akzeptieren"""
        from src.cache.historical_cache import HistoricalCache, CacheStatus
        
        cache = HistoricalCache(ttl_seconds=60)
        
        # 260 Tage Daten
        data = (
            [100.0 + i for i in range(260)],
            [1000 + i for i in range(260)],
            [101.0 + i for i in range(260)],
            [99.0 + i for i in range(260)]
        )
        
        cache.set("AAPL", data, days=260)
        
        # Anfrage für 60 Tage sollte 260-Tage-Cache nutzen
        result = cache.get("AAPL", days=60, accept_more_days=True)
        
        assert result.status == CacheStatus.HIT


class TestValidationIntegration:
    """Tests für Validation Integration"""
    
    def test_symbol_validation(self):
        """Symbol-Validierung sollte korrekt funktionieren"""
        from src.utils.validation import validate_symbol, ValidationError
        
        # Gültige Symbole
        assert validate_symbol("AAPL") == "AAPL"
        assert validate_symbol("brk.b") == "BRK.B"
        
        # Ungültige Symbole
        with pytest.raises(ValidationError):
            validate_symbol("INVALID!!!")
        
        with pytest.raises(ValidationError):
            validate_symbol("")
    
    def test_symbols_list_validation(self):
        """Symbollisten-Validierung sollte funktionieren"""
        from src.utils.validation import validate_symbols
        
        symbols = ["AAPL", "aapl", "MSFT", "INVALID!!!"]
        
        # Mit skip_invalid
        result = validate_symbols(symbols, skip_invalid=True)
        assert "AAPL" in result
        assert "MSFT" in result
        assert len(result) == 2  # Dedupliziert und ohne Invalid


class TestConfigIntegration:
    """Tests für Config Integration"""
    
    def test_performance_config_values(self):
        """Performance Config sollte korrekte Werte haben"""
        from src.config import PerformanceConfig
        
        config = PerformanceConfig()
        
        assert config.cache_ttl_seconds > 0
        assert config.historical_days > 0
        assert config.cache_max_entries > 0
    
    def test_circuit_breaker_config_values(self):
        """Circuit Breaker Config sollte korrekte Werte haben"""
        from src.config import CircuitBreakerConfig
        
        config = CircuitBreakerConfig()
        
        assert config.failure_threshold > 0
        assert config.recovery_timeout > 0
        assert config.half_open_max_calls > 0
        assert config.success_threshold > 0


class TestSecureConfigIntegration:
    """Tests für Secure Config Integration"""
    
    def test_api_key_masking(self):
        """API Key sollte korrekt maskiert werden"""
        from src.utils.secure_config import mask_api_key
        
        key = "sk-1234567890abcdefghijklmnop"
        masked = mask_api_key(key)
        
        # Sollte nur Anfang und Ende zeigen
        assert "1234567890" not in masked
        assert masked.startswith("sk-1")
        assert "..." in masked
    
    def test_sensitive_data_masking(self):
        """Sensitive Daten sollten maskiert werden"""
        from src.utils.secure_config import mask_sensitive_data
        
        text = "API Key: abcdefghijklmnopqrstuvwxyz123456"
        masked = mask_sensitive_data(text)
        
        # Langer String sollte maskiert sein
        assert "abcdefghijklmnopqrstuvwxyz123456" not in masked


class TestHealthCheckIntegration:
    """Tests für Health Check mit neuen Features"""
    
    def test_health_check_includes_cache_stats(self):
        """Health Check sollte Cache-Stats enthalten"""
        from src.cache.historical_cache import HistoricalCache
        
        cache = HistoricalCache()
        
        # Einige Operationen
        cache.set("AAPL", ([1.0], [1], [1.0], [1.0]), days=60)
        cache.get("AAPL", days=60)
        cache.get("MSFT", days=60)  # Miss
        
        stats = cache.stats()
        
        assert "entries" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate_percent" in stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
    
    def test_health_check_includes_circuit_breaker_stats(self):
        """Health Check sollte Circuit Breaker Stats enthalten"""
        from src.utils.circuit_breaker import CircuitBreaker
        
        breaker = CircuitBreaker(name="test")
        
        breaker.record_success()
        breaker.record_failure()
        
        stats = breaker.stats()
        
        assert "name" in stats
        assert "state" in stats
        assert "total_calls" in stats
        assert "successful_calls" in stats
        assert "failed_calls" in stats
        assert stats["total_calls"] == 2


class TestEarningsPreFilterIntegration:
    """Tests für automatischen Earnings Pre-Filter in Scans"""

    def test_scanner_config_has_prefilter_options(self):
        """ScannerConfig sollte Pre-Filter Optionen haben"""
        from src.config import ScannerConfig

        config = ScannerConfig()

        assert hasattr(config, 'auto_earnings_prefilter')
        assert hasattr(config, 'earnings_prefilter_min_days')
        assert config.auto_earnings_prefilter is True  # Default: aktiviert
        assert config.earnings_prefilter_min_days == 30  # Default: ENTRY_EARNINGS_MIN_DAYS (was 45)

    def test_prefilter_can_be_disabled(self):
        """Pre-Filter sollte deaktivierbar sein"""
        from src.config import ScannerConfig

        config = ScannerConfig(auto_earnings_prefilter=False)
        assert config.auto_earnings_prefilter is False

    def test_prefilter_min_days_configurable(self):
        """Pre-Filter min_days sollte konfigurierbar sein"""
        from src.config import ScannerConfig

        config = ScannerConfig(earnings_prefilter_min_days=30)
        assert config.earnings_prefilter_min_days == 30

    @pytest.mark.asyncio
    async def test_apply_earnings_prefilter_filters_correctly(self):
        """_apply_earnings_prefilter sollte Symbole korrekt filtern"""
        from unittest.mock import Mock, AsyncMock, patch, MagicMock
        from src.mcp_server import OptionPlayServer

        with patch('src.mcp_server.get_config') as mock_config, \
             patch('src.cache.get_earnings_history_manager') as mock_ehm:
            # Mock config
            mock_settings = Mock()
            mock_settings.performance.cache_ttl_seconds = 300
            mock_settings.performance.cache_max_entries = 500
            mock_settings.api_connection.max_retries = 3
            mock_settings.api_connection.retry_base_delay = 2
            mock_settings.circuit_breaker.failure_threshold = 5
            mock_settings.circuit_breaker.recovery_timeout = 60
            mock_settings.scanner.earnings_allow_bmo_same_day = False
            mock_config.return_value.settings = mock_settings

            # Mock earnings history batch query: all symbols → no_earnings_data
            # so fallback to EarningsFetcher cache is used
            mock_history = MagicMock()
            mock_history.is_earnings_day_safe_batch_async = AsyncMock(return_value={
                "AAPL": (False, None, "no_earnings_data"),
                "MSFT": (False, None, "no_earnings_data"),
                "GOOGL": (False, None, "no_earnings_data"),
            })
            mock_ehm.return_value = mock_history

            server = OptionPlayServer(api_key="test_key")

            # Mock earnings fetcher
            mock_fetcher = MagicMock()
            mock_cache = MagicMock()

            # AAPL: > ENTRY_EARNINGS_MIN_DAYS bis Earnings (safe)
            # MSFT: 30 Tage bis Earnings (excluded bei min_days=ENTRY_EARNINGS_MIN_DAYS)
            # GOOGL: keine Daten (excluded - konservative Logik schließt unbekannte aus)
            def cache_get(symbol):
                if symbol == "AAPL":
                    return Mock(earnings_date="2025-03-15", days_to_earnings=ENTRY_EARNINGS_MIN_DAYS + 15)
                elif symbol == "MSFT":
                    return Mock(earnings_date="2025-02-15", days_to_earnings=30)
                return None  # GOOGL

            mock_cache.get = cache_get
            mock_fetcher.cache = mock_cache
            mock_fetcher.fetch = Mock(return_value=None)  # Fallback für nicht-gecachte

            server._earnings_fetcher = mock_fetcher

            # Test
            safe, excluded, cache_hits = await server._apply_earnings_prefilter(
                ["AAPL", "MSFT", "GOOGL"],
                min_days=45
            )

            assert "AAPL" in safe
            assert "MSFT" not in safe
            assert "GOOGL" not in safe  # Konservative Logik: unknown = excluded
            assert excluded == 2  # MSFT (zu nah) und GOOGL (unknown)
            assert cache_hits == 2  # AAPL und MSFT waren gecacht


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
