# OptionPlay - Config Loader Tests
# ==================================

import pytest
import sys
from pathlib import Path

# Add project root to path (not src!)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import (
    ConfigLoader,
    Settings,
    PullbackScoringConfig,
    FilterConfig,
    OptionsConfig,
    RSIConfig,
    PerformanceConfig,
    ApiConnectionConfig,
    CircuitBreakerConfig,
    ScannerConfig,
    find_config_dir,
)


class TestFindConfigDir:
    """Tests for config directory search"""
    
    def test_find_explicit_path(self, tmp_path):
        """Explicit path should be found"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        result = find_config_dir(str(config_dir))
        
        assert result == config_dir
        
    def test_fallback_for_nonexistent(self, tmp_path):
        """Non-existent path should use fallback"""
        result = find_config_dir("/nonexistent/path/12345")
        
        # Should return one of the standard paths or 'config'
        assert result is not None


class TestDefaultSettings:
    """Tests for default settings"""
    
    def test_default_settings_creation(self):
        """Default Settings should be created"""
        settings = Settings()
        
        assert settings is not None
        assert settings.filters is not None
        assert settings.options is not None
        assert settings.pullback_scoring is not None
        
    def test_default_filter_values(self):
        """Filters should have correct defaults"""
        settings = Settings()
        
        assert settings.filters.earnings_exclude_days == 45  # Unified to 45 days (PLAYBOOK §1)
        assert settings.filters.price_minimum == 20.0
        assert settings.filters.price_maximum == 1500.0
        assert settings.filters.volume_minimum == 500000
        assert settings.filters.iv_rank_minimum == 50.0
        assert settings.filters.iv_rank_maximum == 80.0
        
    def test_default_options_values(self):
        """Options should have correct defaults"""
        settings = Settings()

        assert settings.options.dte_minimum == 35   # Tastytrade: 35-50
        assert settings.options.dte_maximum == 50   # Tastytrade: 35-50
        assert settings.options.dte_target == 45    # Tastytrade: 35-50
        assert settings.options.delta_target == -0.20  # PLAYBOOK §2
        assert settings.options.delta_minimum == -0.17  # PLAYBOOK §2: ±0.03
        assert settings.options.delta_maximum == -0.23  # PLAYBOOK §2: ±0.03
        assert settings.options.long_delta_target == -0.05  # PLAYBOOK §2
        assert settings.options.long_delta_maximum == -0.07  # PLAYBOOK §2: ±0.02
        assert settings.options.min_credit_pct == 10.0  # PLAYBOOK §2
        
    def test_default_rsi_values(self):
        """RSI should have correct defaults"""
        settings = Settings()
        
        assert settings.pullback_scoring.rsi.period == 14
        assert settings.pullback_scoring.rsi.extreme_oversold == 30
        assert settings.pullback_scoring.rsi.oversold == 40
        assert settings.pullback_scoring.rsi.neutral == 50


class TestConfigLoader:
    """Tests for ConfigLoader"""
    
    @pytest.fixture
    def config_loader(self, tmp_path):
        """ConfigLoader with temporary directory"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        return ConfigLoader(str(config_dir))
    
    def test_load_all_with_empty_dir(self, config_loader):
        """load_all should work with empty directory"""
        settings = config_loader.load_all()
        
        # Should return defaults
        assert settings is not None
        assert isinstance(settings, Settings)
        
    def test_settings_property(self, config_loader):
        """settings property should return Settings"""
        settings = config_loader.settings
        
        assert settings is not None
        assert isinstance(settings, Settings)


class TestConfigLoaderWithFiles:
    """Tests for ConfigLoader with real files"""
    
    @pytest.fixture
    def config_with_settings(self, tmp_path):
        """ConfigLoader with settings.yaml"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Note: delta_minimum should be less aggressive (closer to 0) than delta_maximum
        # For puts: -0.25 is less aggressive than -0.35 (in absolute terms)
        settings_yaml = """
connection:
  ibkr:
    host: "127.0.0.1"
    port: 7497
    client_id: 1

filters:
  earnings:
    exclude_days_before: 90
  price:
    minimum: 25.0
    maximum: 400.0
  volume:
    minimum_daily: 750000
  implied_volatility:
    iv_rank_minimum: 35
    iv_rank_maximum: 75

options_analysis:
  expiration:
    dte_minimum: 35
    dte_maximum: 55
    dte_target: 45
  short_put:
    delta_minimum: -0.25
    delta_maximum: -0.35
    delta_target: -0.28
"""

        (config_dir / "system.yaml").write_text(settings_yaml)
        return ConfigLoader(str(config_dir))
    
    def test_load_custom_filter_settings(self, config_with_settings):
        """Custom filter settings should be loaded"""
        settings = config_with_settings.load_all()
        
        assert settings.filters.earnings_exclude_days == 90
        assert settings.filters.price_minimum == 25.0
        assert settings.filters.price_maximum == 400.0
        assert settings.filters.volume_minimum == 750000
        assert settings.filters.iv_rank_minimum == 35
        assert settings.filters.iv_rank_maximum == 75
        
    def test_load_custom_options_settings(self, config_with_settings):
        """Custom options settings should be loaded"""
        settings = config_with_settings.load_all()
        
        assert settings.options.dte_minimum == 35
        assert settings.options.dte_maximum == 55
        assert settings.options.delta_target == -0.28


class TestWatchlistLoading:
    """Tests for watchlist loading"""
    
    @pytest.fixture
    def config_with_watchlist(self, tmp_path):
        """ConfigLoader with watchlists.yaml"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        watchlist_yaml = """
watchlists:
  default_275:
    name: "Standard Watchlist"
    sectors:
      technology:
        symbols:
          - AAPL
          - MSFT
          - NVDA
      healthcare:
        symbols:
          - UNH
          - JNJ
  tech_focus:
    symbols:
      - AAPL
      - GOOGL
"""
        
        (config_dir / "watchlists.yaml").write_text(watchlist_yaml)
        return ConfigLoader(str(config_dir))
    
    def test_get_watchlist(self, config_with_watchlist):
        """get_watchlist should return symbols"""
        config_with_watchlist.load_all()
        
        watchlist = config_with_watchlist.get_watchlist("default_275")
        
        assert "AAPL" in watchlist
        assert "MSFT" in watchlist
        assert "UNH" in watchlist
        
    def test_get_sector(self, config_with_watchlist):
        """get_sector should return sector symbols"""
        config_with_watchlist.load_all()
        
        tech = config_with_watchlist.get_sector("technology")
        
        assert "AAPL" in tech
        assert "MSFT" in tech
        assert "UNH" not in tech
        
    def test_get_all_sectors(self, config_with_watchlist):
        """get_all_sectors should return all sectors"""
        config_with_watchlist.load_all()
        
        sectors = config_with_watchlist.get_all_sectors()
        
        assert "technology" in sectors
        assert "healthcare" in sectors


class TestStrategyProfiles:
    """Tests for strategy profiles"""
    
    @pytest.fixture
    def config_with_strategies(self, tmp_path):
        """ConfigLoader with strategies.yaml"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        strategies_yaml = """
profiles:
  conservative:
    description: "Low risk profile"
    pullback_scoring:
      min_score_for_candidate: 6
    filters:
      earnings:
        exclude_days_before: 90
      implied_volatility:
        iv_rank_minimum: 20
    options_analysis:
      short_put:
        delta_target: -0.20
      spread:
        preferred_width: 2.5
        
  aggressive:
    description: "High risk profile"
    pullback_scoring:
      min_score_for_candidate: 4
    filters:
      earnings:
        exclude_days_before: 45
    options_analysis:
      short_put:
        delta_target: -0.35
"""
        
        (config_dir / "trading.yaml").write_text(strategies_yaml)
        return ConfigLoader(str(config_dir))
    
    def test_get_strategy(self, config_with_strategies):
        """get_strategy should return profile"""
        config_with_strategies.load_all()
        
        conservative = config_with_strategies.get_strategy("conservative")
        
        assert conservative is not None
        assert conservative['description'] == "Low risk profile"
        
    def test_get_nonexistent_strategy(self, config_with_strategies):
        """get_strategy should return None for unknown profile"""
        config_with_strategies.load_all()
        
        result = config_with_strategies.get_strategy("nonexistent")
        
        assert result is None
        
    def test_apply_strategy(self, config_with_strategies):
        """apply_strategy should modify Settings"""
        config_with_strategies.load_all()

        settings = config_with_strategies.apply_strategy("conservative")

        assert settings.pullback_scoring.min_score_for_candidate == 6
        assert settings.filters.earnings_exclude_days == 90
        assert settings.options.delta_target == -0.20

    def test_regime_profile_affects_scan_config_iv_rank(self, config_with_strategies):
        """apply_strategy should propagate iv_rank_minimum into ScanConfig (OQ-2)"""
        from src.scanner.multi_strategy_scanner import ScanConfig

        config_with_strategies.load_all()
        settings = config_with_strategies.apply_strategy("conservative")

        scan_cfg = ScanConfig(iv_rank_minimum=settings.filters.iv_rank_minimum)
        assert scan_cfg.iv_rank_minimum == 20  # Variante C


class TestEdgeCases:
    """Tests for edge cases"""

    def test_empty_yaml_file(self, tmp_path):
        """Empty YAML file should work"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "system.yaml").write_text("")

        # Empty YAML uses defaults, which should be valid
        loader = ConfigLoader(str(config_dir))
        settings = loader.load_all()

        assert settings is not None

    def test_malformed_yaml(self, tmp_path):
        """Malformed YAML should handle gracefully"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "system.yaml").write_text("this: is: not: valid: yaml: {{")

        loader = ConfigLoader(str(config_dir))

        # Should raise exception or use defaults
        try:
            settings = loader.load_all()
            # If no exception, then defaults
            assert settings is not None
        except Exception:
            # Exception is also acceptable
            pass


# =============================================================================
# TESTS FOR PERFORMANCE, API CONNECTION, CIRCUIT BREAKER CONFIG
# =============================================================================

class TestPerformanceConfig:
    """Tests for PerformanceConfig"""
    
    def test_default_values(self):
        """PerformanceConfig should have correct defaults"""
        config = PerformanceConfig()

        assert config.request_timeout == 30
        assert config.batch_delay == 1.0
        assert config.max_concurrent_requests == 5
        assert config.cache_ttl_seconds == 900  # 15 Minuten für historische Daten
        assert config.cache_ttl_intraday == 300  # 5 Minuten für Live-Quotes
        assert config.cache_ttl_vix == 300  # 5 Minuten für VIX
        assert config.historical_days == 260
        assert config.cache_max_entries == 500
    
    def test_custom_values(self):
        """PerformanceConfig accepts custom values"""
        config = PerformanceConfig(
            request_timeout=60,
            batch_delay=2.0,
            max_concurrent_requests=10,
            cache_ttl_seconds=1800,
            cache_ttl_intraday=600,
            cache_ttl_vix=120,
            historical_days=365,
            cache_max_entries=1000
        )

        assert config.request_timeout == 60
        assert config.batch_delay == 2.0
        assert config.max_concurrent_requests == 10
        assert config.cache_ttl_seconds == 1800
        assert config.cache_ttl_intraday == 600
        assert config.cache_ttl_vix == 120
        assert config.historical_days == 365
        assert config.cache_max_entries == 1000


class TestApiConnectionConfig:
    """Tests for ApiConnectionConfig"""
    
    def test_default_values(self):
        """ApiConnectionConfig should have correct defaults"""
        config = ApiConnectionConfig()
        
        assert config.max_retries == 3
        assert config.retry_base_delay == 2
        assert config.vix_cache_seconds == 300
        assert config.yahoo_timeout == 10
    
    def test_custom_values(self):
        """ApiConnectionConfig accepts custom values"""
        config = ApiConnectionConfig(
            max_retries=5,
            retry_base_delay=3,
            vix_cache_seconds=600,
            yahoo_timeout=30
        )
        
        assert config.max_retries == 5
        assert config.retry_base_delay == 3
        assert config.vix_cache_seconds == 600
        assert config.yahoo_timeout == 30


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig"""
    
    def test_default_values(self):
        """CircuitBreakerConfig should have correct defaults"""
        config = CircuitBreakerConfig()
        
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60.0
        assert config.half_open_max_calls == 3
        assert config.success_threshold == 2
    
    def test_custom_values(self):
        """CircuitBreakerConfig accepts custom values"""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=120.0,
            half_open_max_calls=5,
            success_threshold=3
        )
        
        assert config.failure_threshold == 10
        assert config.recovery_timeout == 120.0
        assert config.half_open_max_calls == 5
        assert config.success_threshold == 3


class TestScannerConfig:
    """Tests for ScannerConfig"""
    
    def test_default_values(self):
        """ScannerConfig should have correct defaults"""
        config = ScannerConfig()
        
        assert config.min_score == 5.0
        assert config.min_actionable_score == 6.0
        assert config.exclude_earnings_within_days == 45  # Unified to 45 days
        assert config.iv_rank_minimum == 50.0
        assert config.iv_rank_maximum == 80.0
        assert config.enable_iv_filter == True
        assert config.max_results_per_symbol == 3
        assert config.max_total_results == 50
        assert config.max_concurrent == 10
        assert config.min_data_points == 60
        assert config.enable_pullback == True
        assert config.enable_bounce == True


class TestSettingsWithNewConfigs:
    """Tests for Settings with new config classes"""
    
    def test_settings_has_performance(self):
        """Settings should contain PerformanceConfig"""
        settings = Settings()
        
        assert hasattr(settings, 'performance')
        assert isinstance(settings.performance, PerformanceConfig)
    
    def test_settings_has_api_connection(self):
        """Settings should contain ApiConnectionConfig"""
        settings = Settings()
        
        assert hasattr(settings, 'api_connection')
        assert isinstance(settings.api_connection, ApiConnectionConfig)
    
    def test_settings_has_circuit_breaker(self):
        """Settings should contain CircuitBreakerConfig"""
        settings = Settings()
        
        assert hasattr(settings, 'circuit_breaker')
        assert isinstance(settings.circuit_breaker, CircuitBreakerConfig)
    
    def test_settings_has_scanner(self):
        """Settings should contain ScannerConfig"""
        settings = Settings()
        
        assert hasattr(settings, 'scanner')
        assert isinstance(settings.scanner, ScannerConfig)


class TestConfigLoaderWithNewSections:
    """Tests for ConfigLoader with new YAML sections"""
    
    @pytest.fixture
    def config_with_all_sections(self, tmp_path):
        """ConfigLoader with all new sections"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        settings_yaml = """
performance:
  request_timeout: 45
  batch_delay: 1.5
  max_concurrent_requests: 8
  cache_ttl_seconds: 600
  historical_days: 365
  cache_max_entries: 1000

api_connection:
  max_retries: 5
  retry_base_delay: 3
  vix_cache_seconds: 600
  yahoo_timeout: 15

circuit_breaker:
  failure_threshold: 10
  recovery_timeout: 120
  half_open_max_calls: 5
  success_threshold: 3

scanner:
  enable_iv_filter: false
  max_results_per_symbol: 5
  max_total_results: 100
"""
        
        (config_dir / "system.yaml").write_text(settings_yaml)
        # Partial config may not pass validation, so disable it for this test
        return ConfigLoader(str(config_dir), validate=False)

    def test_load_performance_config(self, config_with_all_sections):
        """PerformanceConfig should be loaded from YAML"""
        settings = config_with_all_sections.load_all()
        
        assert settings.performance.request_timeout == 45
        assert settings.performance.batch_delay == 1.5
        assert settings.performance.max_concurrent_requests == 8
        assert settings.performance.cache_ttl_seconds == 600
        assert settings.performance.historical_days == 365
        assert settings.performance.cache_max_entries == 1000
    
    def test_load_api_connection_config(self, config_with_all_sections):
        """ApiConnectionConfig should be loaded from YAML"""
        settings = config_with_all_sections.load_all()
        
        assert settings.api_connection.max_retries == 5
        assert settings.api_connection.retry_base_delay == 3
        assert settings.api_connection.vix_cache_seconds == 600
        assert settings.api_connection.yahoo_timeout == 15
    
    def test_load_circuit_breaker_config(self, config_with_all_sections):
        """CircuitBreakerConfig should be loaded from YAML"""
        settings = config_with_all_sections.load_all()
        
        assert settings.circuit_breaker.failure_threshold == 10
        assert settings.circuit_breaker.recovery_timeout == 120.0
        assert settings.circuit_breaker.half_open_max_calls == 5
        assert settings.circuit_breaker.success_threshold == 3
    
    def test_load_scanner_config_overrides(self, config_with_all_sections):
        """ScannerConfig should load overrides from YAML"""
        settings = config_with_all_sections.load_all()
        
        assert settings.scanner.enable_iv_filter == False
        assert settings.scanner.max_results_per_symbol == 5
        assert settings.scanner.max_total_results == 100


class TestPartialConfigLoading:
    """Tests for partial config loading (only some sections)"""
    
    @pytest.fixture
    def config_with_partial_sections(self, tmp_path):
        """ConfigLoader with only some sections"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        # Only performance, no other new sections
        settings_yaml = """
performance:
  cache_ttl_seconds: 900
  historical_days: 180
"""
        
        (config_dir / "system.yaml").write_text(settings_yaml)
        # Partial config may not pass validation, so disable it for this test
        return ConfigLoader(str(config_dir), validate=False)

    def test_partial_performance_loads(self, config_with_partial_sections):
        """Partial performance config should load"""
        settings = config_with_partial_sections.load_all()
        
        # Set values
        assert settings.performance.cache_ttl_seconds == 900
        assert settings.performance.historical_days == 180
        
        # Defaults for unset
        assert settings.performance.request_timeout == 30
        assert settings.performance.batch_delay == 1.0
    
    def test_missing_sections_use_defaults(self, config_with_partial_sections):
        """Missing sections should use defaults"""
        settings = config_with_partial_sections.load_all()
        
        # api_connection and circuit_breaker not in YAML -> Defaults
        assert settings.api_connection.max_retries == 3
        assert settings.circuit_breaker.failure_threshold == 5


class TestKeltnerChannelConfig:
    """Tests for KeltnerChannelConfig with upper band weights"""

    def test_default_lower_band_weights(self):
        """Lower band weights should have correct defaults"""
        from src.config import KeltnerChannelConfig

        config = KeltnerChannelConfig()

        assert config.weight_below_lower == 2.0
        assert config.weight_near_lower == 1.0
        assert config.weight_mean_reversion == 1.0

    def test_default_upper_band_weights(self):
        """Upper band weights should have correct defaults for breakout"""
        from src.config import KeltnerChannelConfig

        config = KeltnerChannelConfig()

        assert config.weight_above_upper == 2.0
        assert config.weight_near_upper == 1.0

    def test_custom_upper_band_weights(self):
        """Custom upper band weights should be settable"""
        from src.config import KeltnerChannelConfig

        config = KeltnerChannelConfig(
            weight_above_upper=3.0,
            weight_near_upper=1.5
        )

        assert config.weight_above_upper == 3.0
        assert config.weight_near_upper == 1.5


class TestSupportConfigTouchTolerance:
    """Tests for SupportConfig touch_tolerance_pct field"""

    def test_default_touch_tolerance(self):
        """Touch tolerance should default to 2%"""
        from src.config import SupportConfig

        config = SupportConfig()

        assert config.touch_tolerance_pct == 2.0

    def test_custom_touch_tolerance(self):
        """Custom touch tolerance should be settable"""
        from src.config import SupportConfig

        config = SupportConfig(touch_tolerance_pct=3.0)

        assert config.touch_tolerance_pct == 3.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
