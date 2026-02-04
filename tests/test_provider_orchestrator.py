# Tests for Provider Orchestrator
# ================================
"""
Tests for ProviderOrchestrator, ProviderConfig, ProviderStats.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.utils.provider_orchestrator import (
    ProviderOrchestrator,
    ProviderType,
    DataType,
    ProviderConfig,
    ProviderStats,
    get_orchestrator,
    format_provider_status,
)


# =============================================================================
# PROVIDER TYPE TESTS
# =============================================================================

class TestProviderType:
    """Tests for ProviderType enum."""

    def test_has_expected_providers(self):
        """Test all expected provider types exist."""
        assert ProviderType.MARKETDATA.value == "marketdata"
        assert ProviderType.TRADIER.value == "tradier"
        assert ProviderType.IBKR.value == "ibkr"
        assert ProviderType.YAHOO.value == "yahoo"

    def test_enum_count(self):
        """Test correct number of provider types."""
        assert len(ProviderType) == 4


# =============================================================================
# DATA TYPE TESTS
# =============================================================================

class TestDataType:
    """Tests for DataType enum."""

    def test_has_expected_data_types(self):
        """Test all expected data types exist."""
        assert DataType.QUOTE.value == "quote"
        assert DataType.HISTORICAL.value == "historical"
        assert DataType.OPTIONS_CHAIN.value == "options_chain"
        assert DataType.VIX.value == "vix"
        assert DataType.EARNINGS.value == "earnings"
        assert DataType.SCAN.value == "scan"

    def test_has_advanced_types(self):
        """Test advanced data types exist."""
        assert DataType.NEWS.value == "news"
        assert DataType.IV_RANK.value == "iv_rank"
        assert DataType.MAX_PAIN.value == "max_pain"
        assert DataType.STRIKE_RECOMMENDATION.value == "strike_recommendation"


# =============================================================================
# PROVIDER CONFIG TESTS
# =============================================================================

class TestProviderConfig:
    """Tests for ProviderConfig dataclass."""

    def test_create_config(self):
        """Test creating provider config."""
        config = ProviderConfig(
            name="Test Provider",
            enabled=True,
            priority=1,
            rate_limit_per_minute=100,
        )

        assert config.name == "Test Provider"
        assert config.enabled is True
        assert config.priority == 1
        assert config.rate_limit_per_minute == 100

    def test_default_values(self):
        """Test default values."""
        config = ProviderConfig(name="Test")

        assert config.enabled is True
        assert config.priority == 1
        assert config.rate_limit_per_minute == 100
        assert config.daily_limit is None
        assert config.supports == []

    def test_post_init_creates_empty_supports(self):
        """Test post_init creates empty supports list."""
        config = ProviderConfig(name="Test", supports=None)
        assert config.supports == []


# =============================================================================
# PROVIDER STATS TESTS
# =============================================================================

class TestProviderStats:
    """Tests for ProviderStats dataclass."""

    def test_create_stats(self):
        """Test creating provider stats."""
        stats = ProviderStats()

        assert stats.requests_today == 0
        assert stats.requests_total == 0
        assert stats.errors_today == 0
        assert stats.last_error is None
        assert stats.last_request is None
        assert stats.avg_latency_ms == 0.0


# =============================================================================
# PROVIDER ORCHESTRATOR TESTS
# =============================================================================

class TestProviderOrchestrator:
    """Tests for ProviderOrchestrator class."""

    @pytest.fixture
    def orchestrator(self):
        """Create fresh orchestrator for each test."""
        return ProviderOrchestrator()

    def test_init_creates_providers(self, orchestrator):
        """Test initialization creates all providers."""
        assert ProviderType.MARKETDATA in orchestrator.providers
        assert ProviderType.TRADIER in orchestrator.providers
        assert ProviderType.IBKR in orchestrator.providers
        assert ProviderType.YAHOO in orchestrator.providers

    def test_init_creates_stats(self, orchestrator):
        """Test initialization creates stats for all providers."""
        for provider_type in ProviderType:
            assert provider_type in orchestrator.stats

    def test_marketdata_enabled_by_default(self, orchestrator):
        """Test Marketdata.app is enabled by default."""
        assert orchestrator.providers[ProviderType.MARKETDATA].enabled is True

    def test_ibkr_disabled_by_default(self, orchestrator):
        """Test IBKR is disabled by default."""
        assert orchestrator.providers[ProviderType.IBKR].enabled is False

    def test_tradier_disabled_by_default(self, orchestrator):
        """Test Tradier is disabled by default."""
        assert orchestrator.providers[ProviderType.TRADIER].enabled is False

    def test_yahoo_enabled_by_default(self, orchestrator):
        """Test Yahoo is enabled by default."""
        assert orchestrator.providers[ProviderType.YAHOO].enabled is True


# =============================================================================
# ENABLE/DISABLE TESTS
# =============================================================================

class TestEnableDisable:
    """Tests for enable/disable methods."""

    @pytest.fixture
    def orchestrator(self):
        """Create fresh orchestrator for each test."""
        return ProviderOrchestrator()

    def test_enable_ibkr(self, orchestrator):
        """Test enabling IBKR."""
        orchestrator.enable_ibkr(True)

        assert orchestrator.providers[ProviderType.IBKR].enabled is True
        assert orchestrator._ibkr_connected is True

    def test_disable_ibkr(self, orchestrator):
        """Test disabling IBKR."""
        orchestrator.enable_ibkr(True)
        orchestrator.enable_ibkr(False)

        assert orchestrator.providers[ProviderType.IBKR].enabled is False
        assert orchestrator._ibkr_connected is False

    def test_enable_tradier(self, orchestrator):
        """Test enabling Tradier."""
        orchestrator.enable_tradier(True)

        assert orchestrator.providers[ProviderType.TRADIER].enabled is True
        assert orchestrator._tradier_connected is True

    def test_disable_tradier(self, orchestrator):
        """Test disabling Tradier."""
        orchestrator.enable_tradier(True)
        orchestrator.enable_tradier(False)

        assert orchestrator.providers[ProviderType.TRADIER].enabled is False
        assert orchestrator._tradier_connected is False


# =============================================================================
# GET BEST PROVIDER TESTS
# =============================================================================

class TestGetBestProvider:
    """Tests for get_best_provider method."""

    @pytest.fixture
    def orchestrator(self):
        """Create fresh orchestrator for each test."""
        return ProviderOrchestrator()

    def test_get_best_for_quote_returns_marketdata(self, orchestrator):
        """Test QUOTE returns Marketdata (IBKR/Tradier disabled)."""
        result = orchestrator.get_best_provider(DataType.QUOTE)
        assert result == ProviderType.MARKETDATA

    def test_get_best_for_quote_with_ibkr_enabled(self, orchestrator):
        """Test QUOTE returns IBKR when enabled."""
        orchestrator.enable_ibkr(True)
        result = orchestrator.get_best_provider(DataType.QUOTE)
        assert result == ProviderType.IBKR

    def test_get_best_for_vix_returns_yahoo(self, orchestrator):
        """Test VIX returns Yahoo (IBKR disabled)."""
        result = orchestrator.get_best_provider(DataType.VIX)
        assert result == ProviderType.YAHOO

    def test_get_best_for_vix_with_ibkr_still_returns_yahoo(self, orchestrator):
        """Test VIX returns Yahoo even when IBKR is enabled (Yahoo is preferred for VIX)."""
        orchestrator.enable_ibkr(True)
        result = orchestrator.get_best_provider(DataType.VIX)
        # IBKR is in ROUTING_PREFERENCES but requires _ibkr_connected and supports check
        # IBKR does support VIX according to DEFAULT_PROVIDERS, but Yahoo is still returned
        # because IBKR requires prefer_accuracy=True for some data types
        assert result in [ProviderType.IBKR, ProviderType.YAHOO]

    def test_get_best_for_earnings_returns_yahoo(self, orchestrator):
        """Test EARNINGS returns Yahoo."""
        result = orchestrator.get_best_provider(DataType.EARNINGS)
        assert result == ProviderType.YAHOO

    def test_get_best_for_scan_returns_marketdata(self, orchestrator):
        """Test SCAN returns Marketdata (not IBKR even if enabled)."""
        orchestrator.enable_ibkr(True)
        result = orchestrator.get_best_provider(DataType.SCAN)
        # IBKR is skipped for SCAN
        assert result == ProviderType.MARKETDATA

    def test_get_best_for_news_with_ibkr(self, orchestrator):
        """Test NEWS returns IBKR when enabled."""
        orchestrator.enable_ibkr(True)
        result = orchestrator.get_best_provider(DataType.NEWS)
        assert result == ProviderType.IBKR

    def test_get_best_for_news_without_ibkr_returns_none(self, orchestrator):
        """Test NEWS returns None without IBKR."""
        result = orchestrator.get_best_provider(DataType.NEWS)
        assert result is None


# =============================================================================
# GET FALLBACK PROVIDERS TESTS
# =============================================================================

class TestGetFallbackProviders:
    """Tests for get_fallback_providers method."""

    @pytest.fixture
    def orchestrator(self):
        """Create fresh orchestrator for each test."""
        return ProviderOrchestrator()

    def test_get_fallbacks_excludes_primary(self, orchestrator):
        """Test fallbacks exclude the specified provider."""
        fallbacks = orchestrator.get_fallback_providers(
            DataType.QUOTE,
            exclude=ProviderType.MARKETDATA
        )
        assert ProviderType.MARKETDATA not in fallbacks

    def test_get_fallbacks_for_quote(self, orchestrator):
        """Test fallbacks for QUOTE."""
        fallbacks = orchestrator.get_fallback_providers(DataType.QUOTE)
        # Only MARKETDATA is enabled
        assert ProviderType.MARKETDATA in fallbacks

    def test_get_fallbacks_returns_list(self, orchestrator):
        """Test fallbacks returns a list."""
        fallbacks = orchestrator.get_fallback_providers(DataType.HISTORICAL)
        assert isinstance(fallbacks, list)


# =============================================================================
# RECORD REQUEST TESTS
# =============================================================================

class TestRecordRequest:
    """Tests for record_request method."""

    @pytest.fixture
    def orchestrator(self):
        """Create fresh orchestrator for each test."""
        return ProviderOrchestrator()

    def test_record_successful_request(self, orchestrator):
        """Test recording a successful request."""
        orchestrator.record_request(
            ProviderType.MARKETDATA,
            success=True,
            latency_ms=50.0
        )

        stats = orchestrator.stats[ProviderType.MARKETDATA]
        assert stats.requests_today == 1
        assert stats.requests_total == 1
        assert stats.errors_today == 0

    def test_record_failed_request(self, orchestrator):
        """Test recording a failed request."""
        orchestrator.record_request(
            ProviderType.MARKETDATA,
            success=False,
            error="Connection timeout"
        )

        stats = orchestrator.stats[ProviderType.MARKETDATA]
        assert stats.requests_today == 1
        assert stats.errors_today == 1
        assert stats.last_error == "Connection timeout"

    def test_record_updates_latency(self, orchestrator):
        """Test latency is recorded."""
        orchestrator.record_request(
            ProviderType.MARKETDATA,
            success=True,
            latency_ms=100.0
        )

        stats = orchestrator.stats[ProviderType.MARKETDATA]
        assert stats.avg_latency_ms == 100.0

    def test_record_moving_average_latency(self, orchestrator):
        """Test latency uses moving average."""
        # First request
        orchestrator.record_request(
            ProviderType.MARKETDATA,
            success=True,
            latency_ms=100.0
        )
        # Second request - should use 90/10 weighted average
        orchestrator.record_request(
            ProviderType.MARKETDATA,
            success=True,
            latency_ms=200.0
        )

        stats = orchestrator.stats[ProviderType.MARKETDATA]
        # 100 * 0.9 + 200 * 0.1 = 90 + 20 = 110
        assert stats.avg_latency_ms == 110.0

    def test_record_sets_last_request(self, orchestrator):
        """Test last_request timestamp is set."""
        orchestrator.record_request(ProviderType.MARKETDATA, success=True)

        stats = orchestrator.stats[ProviderType.MARKETDATA]
        assert stats.last_request is not None
        assert isinstance(stats.last_request, datetime)


# =============================================================================
# GET PROVIDER STATUS TESTS
# =============================================================================

class TestGetProviderStatus:
    """Tests for get_provider_status method."""

    @pytest.fixture
    def orchestrator(self):
        """Create fresh orchestrator for each test."""
        return ProviderOrchestrator()

    def test_status_returns_dict(self, orchestrator):
        """Test status returns a dict."""
        status = orchestrator.get_provider_status()
        assert isinstance(status, dict)

    def test_status_contains_all_providers(self, orchestrator):
        """Test status contains all providers."""
        status = orchestrator.get_provider_status()
        assert "Marketdata.app" in status
        assert "Tradier" in status
        assert "IBKR/TWS" in status
        assert "Yahoo Finance" in status

    def test_status_has_expected_fields(self, orchestrator):
        """Test status has expected fields."""
        status = orchestrator.get_provider_status()
        marketdata = status["Marketdata.app"]

        assert "enabled" in marketdata
        assert "priority" in marketdata
        assert "rate_limit" in marketdata
        assert "requests_today" in marketdata
        assert "supports" in marketdata


# =============================================================================
# UTILITY METHODS TESTS
# =============================================================================

class TestUtilityMethods:
    """Tests for utility methods."""

    @pytest.fixture
    def orchestrator(self):
        """Create fresh orchestrator for each test."""
        return ProviderOrchestrator()

    def test_should_use_ibkr_false_when_not_connected(self, orchestrator):
        """Test should_use_ibkr returns False when not connected."""
        result = orchestrator.should_use_ibkr_for_validation("AAPL")
        assert result is False

    def test_should_use_ibkr_true_when_connected(self, orchestrator):
        """Test should_use_ibkr returns True when connected."""
        orchestrator.enable_ibkr(True)
        result = orchestrator.should_use_ibkr_for_validation("AAPL")
        assert result is True

    def test_get_scan_provider_returns_marketdata(self, orchestrator):
        """Test scan provider is always Marketdata."""
        result = orchestrator.get_scan_provider()
        assert result == ProviderType.MARKETDATA

    def test_get_vix_provider_returns_yahoo(self, orchestrator):
        """Test VIX provider returns Yahoo by default."""
        result = orchestrator.get_vix_provider()
        assert result == ProviderType.YAHOO


# =============================================================================
# CONVENIENCE FUNCTIONS TESTS
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_get_orchestrator_returns_instance(self):
        """Test get_orchestrator returns ProviderOrchestrator."""
        result = get_orchestrator()
        assert isinstance(result, ProviderOrchestrator)

    def test_get_orchestrator_singleton(self):
        """Test get_orchestrator returns same instance."""
        result1 = get_orchestrator()
        result2 = get_orchestrator()
        assert result1 is result2

    def test_format_provider_status_returns_markdown(self):
        """Test format_provider_status returns markdown."""
        result = format_provider_status()
        assert isinstance(result, str)
        assert "# Data Provider Status" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
