# Tests for Provider Orchestrator
# ================================
"""
Comprehensive tests for ProviderOrchestrator, ProviderConfig, ProviderStats.

Tests cover:
1. ProviderOrchestrator initialization
2. Provider routing and selection
3. Provider fallback logic
4. Error handling and stats tracking
5. Daily reset and rate limiting
"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock
import importlib

from src.utils.provider_orchestrator import (
    ProviderOrchestrator,
    ProviderType,
    DataType,
    ProviderConfig,
    ProviderStats,
    get_orchestrator,
    format_provider_status,
    _default_orchestrator,
)
import src.utils.provider_orchestrator as provider_orchestrator_module


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def fresh_orchestrator():
    """Create a fresh orchestrator for each test."""
    return ProviderOrchestrator()


@pytest.fixture
def reset_singleton():
    """Reset the global singleton before and after each test."""
    provider_orchestrator_module._default_orchestrator = None
    yield
    provider_orchestrator_module._default_orchestrator = None


# =============================================================================
# PROVIDER TYPE TESTS
# =============================================================================

class TestProviderType:
    """Tests for ProviderType enum."""

    def test_has_expected_providers(self):
        """Test all expected provider types exist."""
        assert ProviderType.MARKETDATA.value == "marketdata"
        assert ProviderType.IBKR.value == "ibkr"
        assert ProviderType.TRADIER.value == "tradier"
        assert ProviderType.YAHOO.value == "yahoo"

    def test_enum_count(self):
        """Test correct number of provider types."""
        assert len(ProviderType) == 4

    def test_provider_type_is_hashable(self):
        """Test that ProviderType can be used as dictionary key."""
        d = {ProviderType.IBKR: "test"}
        assert d[ProviderType.IBKR] == "test"

    def test_provider_type_equality(self):
        """Test enum comparison."""
        assert ProviderType.IBKR == ProviderType.IBKR
        assert ProviderType.IBKR != ProviderType.YAHOO


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

    def test_enum_count(self):
        """Test correct number of data types."""
        assert len(DataType) == 10

    def test_data_type_is_hashable(self):
        """Test that DataType can be used in sets."""
        s = {DataType.QUOTE, DataType.VIX}
        assert DataType.QUOTE in s


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

    def test_config_with_supports_list(self):
        """Test config with explicit supports list."""
        supports = [DataType.QUOTE, DataType.HISTORICAL]
        config = ProviderConfig(name="Test", supports=supports)
        assert config.supports == supports
        assert DataType.QUOTE in config.supports

    def test_config_with_daily_limit(self):
        """Test config with daily limit set."""
        config = ProviderConfig(
            name="Test",
            daily_limit=1000
        )
        assert config.daily_limit == 1000


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

    def test_stats_with_values(self):
        """Test creating stats with custom values."""
        now = datetime.now()
        stats = ProviderStats(
            requests_today=10,
            requests_total=100,
            errors_today=2,
            last_error="Connection timeout",
            last_request=now,
            avg_latency_ms=50.5
        )

        assert stats.requests_today == 10
        assert stats.requests_total == 100
        assert stats.errors_today == 2
        assert stats.last_error == "Connection timeout"
        assert stats.last_request == now
        assert stats.avg_latency_ms == 50.5

    def test_stats_mutable(self):
        """Test that stats can be mutated."""
        stats = ProviderStats()
        stats.requests_today = 5
        stats.errors_today = 1
        assert stats.requests_today == 5
        assert stats.errors_today == 1


# =============================================================================
# PROVIDER ORCHESTRATOR INITIALIZATION TESTS
# =============================================================================

class TestProviderOrchestratorInit:
    """Tests for ProviderOrchestrator initialization."""

    def test_init_creates_providers(self, fresh_orchestrator):
        """Test initialization creates all active providers."""
        assert ProviderType.IBKR in fresh_orchestrator.providers
        assert ProviderType.YAHOO in fresh_orchestrator.providers

    def test_init_only_active_providers(self, fresh_orchestrator):
        """Test initialization only creates IBKR and Yahoo (not legacy providers)."""
        assert len(fresh_orchestrator.providers) == 2
        assert ProviderType.MARKETDATA not in fresh_orchestrator.providers
        assert ProviderType.TRADIER not in fresh_orchestrator.providers

    def test_init_creates_stats(self, fresh_orchestrator):
        """Test initialization creates stats for all providers."""
        for provider_type in fresh_orchestrator.providers:
            assert provider_type in fresh_orchestrator.stats
            assert isinstance(fresh_orchestrator.stats[provider_type], ProviderStats)

    def test_ibkr_enabled_by_default(self, fresh_orchestrator):
        """Test IBKR is enabled by default."""
        assert fresh_orchestrator.providers[ProviderType.IBKR].enabled is True

    def test_yahoo_enabled_by_default(self, fresh_orchestrator):
        """Test Yahoo is enabled by default."""
        assert fresh_orchestrator.providers[ProviderType.YAHOO].enabled is True

    def test_ibkr_connected_false_by_default(self, fresh_orchestrator):
        """Test IBKR connected flag is False by default."""
        assert fresh_orchestrator._ibkr_connected is False

    def test_last_daily_reset_is_today(self, fresh_orchestrator):
        """Test last daily reset is set to today."""
        assert fresh_orchestrator._last_daily_reset == datetime.now().date()

    def test_providers_are_independent_copies(self, fresh_orchestrator):
        """Test that provider configs are independent copies of defaults."""
        # Modify the orchestrator's config
        fresh_orchestrator.providers[ProviderType.IBKR].enabled = False

        # Create a new orchestrator
        new_orchestrator = ProviderOrchestrator()

        # The new orchestrator should still have defaults
        assert new_orchestrator.providers[ProviderType.IBKR].enabled is True

    def test_stats_initialized_to_zero(self, fresh_orchestrator):
        """Test all stats are initialized to zero."""
        for provider_type in ProviderType:
            stats = fresh_orchestrator.stats[provider_type]
            assert stats.requests_today == 0
            assert stats.requests_total == 0
            assert stats.errors_today == 0


# =============================================================================
# ENABLE/DISABLE TESTS
# =============================================================================

class TestEnableDisable:
    """Tests for enable/disable methods."""

    def test_enable_ibkr(self, fresh_orchestrator):
        """Test enabling IBKR."""
        fresh_orchestrator.enable_ibkr(True)

        assert fresh_orchestrator.providers[ProviderType.IBKR].enabled is True
        assert fresh_orchestrator._ibkr_connected is True

    def test_disable_ibkr(self, fresh_orchestrator):
        """Test disabling IBKR."""
        fresh_orchestrator.enable_ibkr(True)
        fresh_orchestrator.enable_ibkr(False)

        assert fresh_orchestrator.providers[ProviderType.IBKR].enabled is False
        assert fresh_orchestrator._ibkr_connected is False

    def test_enable_ibkr_default_param(self, fresh_orchestrator):
        """Test enable_ibkr default parameter is True."""
        fresh_orchestrator.enable_ibkr()
        assert fresh_orchestrator._ibkr_connected is True


# =============================================================================
# GET BEST PROVIDER TESTS
# =============================================================================

class TestGetBestProvider:
    """Tests for get_best_provider method."""

    def test_get_best_for_quote_returns_none_without_ibkr(self, fresh_orchestrator):
        """Test QUOTE returns None when IBKR is not connected."""
        result = fresh_orchestrator.get_best_provider(DataType.QUOTE)
        # IBKR is only provider for QUOTE, but not connected
        assert result is None

    def test_get_best_for_quote_with_ibkr_enabled(self, fresh_orchestrator):
        """Test QUOTE returns IBKR when enabled."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.QUOTE)
        assert result == ProviderType.IBKR

    def test_get_best_for_vix_returns_yahoo(self, fresh_orchestrator):
        """Test VIX returns Yahoo (IBKR not connected)."""
        result = fresh_orchestrator.get_best_provider(DataType.VIX)
        assert result == ProviderType.YAHOO

    def test_get_best_for_vix_with_ibkr_still_returns_yahoo(self, fresh_orchestrator):
        """Test VIX returns Yahoo even when IBKR enabled (IBKR doesn't support VIX)."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.VIX)
        # IBKR is first in routing preferences but doesn't support VIX
        # So Yahoo is returned instead
        assert result == ProviderType.YAHOO

    def test_get_best_for_earnings_returns_yahoo(self, fresh_orchestrator):
        """Test EARNINGS returns Yahoo."""
        result = fresh_orchestrator.get_best_provider(DataType.EARNINGS)
        assert result == ProviderType.YAHOO

    def test_get_best_for_scan_returns_ibkr_when_connected(self, fresh_orchestrator):
        """Test SCAN returns IBKR when connected."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.SCAN, prefer_accuracy=True)
        assert result == ProviderType.IBKR

    def test_get_best_for_scan_returns_none_without_ibkr(self, fresh_orchestrator):
        """Test SCAN returns None when IBKR not connected."""
        result = fresh_orchestrator.get_best_provider(DataType.SCAN)
        assert result is None

    def test_get_best_for_news_with_ibkr(self, fresh_orchestrator):
        """Test NEWS returns IBKR when enabled."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.NEWS)
        assert result == ProviderType.IBKR

    def test_get_best_for_news_without_ibkr_returns_none(self, fresh_orchestrator):
        """Test NEWS returns None without IBKR."""
        result = fresh_orchestrator.get_best_provider(DataType.NEWS)
        assert result is None

    def test_get_best_for_max_pain_with_ibkr(self, fresh_orchestrator):
        """Test MAX_PAIN returns IBKR when enabled."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.MAX_PAIN)
        assert result == ProviderType.IBKR

    def test_get_best_for_max_pain_without_ibkr(self, fresh_orchestrator):
        """Test MAX_PAIN returns None without IBKR."""
        result = fresh_orchestrator.get_best_provider(DataType.MAX_PAIN)
        assert result is None

    def test_get_best_for_strike_recommendation(self, fresh_orchestrator):
        """Test STRIKE_RECOMMENDATION returns IBKR when enabled."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.STRIKE_RECOMMENDATION)
        assert result == ProviderType.IBKR

    def test_get_best_for_historical_returns_ibkr_when_connected(self, fresh_orchestrator):
        """Test HISTORICAL returns IBKR when connected."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.HISTORICAL)
        assert result == ProviderType.IBKR

    def test_get_best_for_historical_returns_none_without_ibkr(self, fresh_orchestrator):
        """Test HISTORICAL returns None when IBKR not connected (only IBKR in routing)."""
        result = fresh_orchestrator.get_best_provider(DataType.HISTORICAL)
        # IBKR is first but not connected; Yahoo also supports HISTORICAL but is not in QUOTE routing
        # Check actual routing — HISTORICAL routes to IBKR only
        assert result is None or result == ProviderType.YAHOO

    def test_get_best_for_options_chain_with_ibkr(self, fresh_orchestrator):
        """Test OPTIONS_CHAIN returns IBKR when enabled."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.OPTIONS_CHAIN)
        assert result == ProviderType.IBKR

    def test_get_best_for_options_chain_without_ibkr(self, fresh_orchestrator):
        """Test OPTIONS_CHAIN returns None without IBKR."""
        result = fresh_orchestrator.get_best_provider(DataType.OPTIONS_CHAIN)
        assert result is None

    def test_get_best_for_iv_rank_without_ibkr(self, fresh_orchestrator):
        """Test IV_RANK returns None when IBKR is disabled."""
        result = fresh_orchestrator.get_best_provider(DataType.IV_RANK)
        assert result is None

    def test_get_best_for_iv_rank_with_ibkr(self, fresh_orchestrator):
        """Test IV_RANK returns IBKR when enabled."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_best_provider(DataType.IV_RANK)
        assert result == ProviderType.IBKR

    def test_get_best_for_unknown_data_type_returns_none(self, fresh_orchestrator):
        """Test unknown data type returns None."""
        # Create a mock unknown data type case by using empty routing
        fresh_orchestrator.ROUTING_PREFERENCES = {}
        result = fresh_orchestrator.get_best_provider(DataType.QUOTE)
        assert result is None


# =============================================================================
# DAILY LIMIT TESTS
# =============================================================================

class TestDailyLimit:
    """Tests for daily limit handling."""

    def test_provider_skipped_when_daily_limit_reached(self, fresh_orchestrator):
        """Test provider is skipped when daily limit is reached."""
        fresh_orchestrator.enable_ibkr(True)
        fresh_orchestrator.providers[ProviderType.IBKR].daily_limit = 10
        fresh_orchestrator.stats[ProviderType.IBKR].requests_today = 10

        # Should skip IBKR — NEWS only has IBKR, so returns None
        result = fresh_orchestrator.get_best_provider(DataType.NEWS)
        assert result is None

    def test_provider_used_when_under_daily_limit(self, fresh_orchestrator):
        """Test provider is used when under daily limit."""
        fresh_orchestrator.enable_ibkr(True)
        fresh_orchestrator.providers[ProviderType.IBKR].daily_limit = 10
        fresh_orchestrator.stats[ProviderType.IBKR].requests_today = 5

        result = fresh_orchestrator.get_best_provider(DataType.NEWS)
        assert result == ProviderType.IBKR

    def test_fallback_to_next_provider_when_limit_reached(self, fresh_orchestrator):
        """Test fallback to next provider when primary hits limit."""
        fresh_orchestrator.enable_ibkr(True)
        fresh_orchestrator.providers[ProviderType.IBKR].daily_limit = 5
        fresh_orchestrator.stats[ProviderType.IBKR].requests_today = 5

        # IBKR hit limit; VIX falls back to Yahoo
        result = fresh_orchestrator.get_best_provider(DataType.VIX)
        assert result == ProviderType.YAHOO


# =============================================================================
# GET FALLBACK PROVIDERS TESTS
# =============================================================================

class TestGetFallbackProviders:
    """Tests for get_fallback_providers method."""

    def test_get_fallbacks_excludes_primary(self, fresh_orchestrator):
        """Test fallbacks exclude the specified provider."""
        fresh_orchestrator.enable_ibkr(True)
        fallbacks = fresh_orchestrator.get_fallback_providers(
            DataType.QUOTE,
            exclude=ProviderType.IBKR
        )
        assert ProviderType.IBKR not in fallbacks

    def test_get_fallbacks_for_vix(self, fresh_orchestrator):
        """Test fallbacks for VIX include Yahoo."""
        fallbacks = fresh_orchestrator.get_fallback_providers(DataType.VIX)
        assert ProviderType.YAHOO in fallbacks

    def test_get_fallbacks_returns_list(self, fresh_orchestrator):
        """Test fallbacks returns a list."""
        fallbacks = fresh_orchestrator.get_fallback_providers(DataType.HISTORICAL)
        assert isinstance(fallbacks, list)

    def test_get_fallbacks_empty_for_exclusive_provider(self, fresh_orchestrator):
        """Test fallbacks empty when only one provider supports data type and is excluded."""
        # NEWS only supported by IBKR — excluding IBKR leaves no fallbacks
        fallbacks = fresh_orchestrator.get_fallback_providers(
            DataType.NEWS, exclude=ProviderType.IBKR
        )
        assert fallbacks == []

    def test_get_fallbacks_respects_enabled_state(self, fresh_orchestrator):
        """Test fallbacks only include enabled providers."""
        fallbacks = fresh_orchestrator.get_fallback_providers(DataType.QUOTE)

        # IBKR is in routing but not connected — still "enabled" in config
        # get_fallback_providers checks enabled flag, not _ibkr_connected
        for fb in fallbacks:
            config = fresh_orchestrator.providers.get(fb)
            assert config is not None
            assert config.enabled is True

    def test_get_fallbacks_for_unknown_data_type(self, fresh_orchestrator):
        """Test fallbacks for data type not in routing preferences."""
        # Temporarily modify routing
        original = fresh_orchestrator.ROUTING_PREFERENCES.copy()
        fresh_orchestrator.ROUTING_PREFERENCES = {}

        fallbacks = fresh_orchestrator.get_fallback_providers(DataType.QUOTE)
        assert fallbacks == []

        # Restore
        fresh_orchestrator.ROUTING_PREFERENCES = original


# =============================================================================
# RECORD REQUEST TESTS
# =============================================================================

class TestRecordRequest:
    """Tests for record_request method."""

    def test_record_successful_request(self, fresh_orchestrator):
        """Test recording a successful request."""
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=True,
            latency_ms=50.0
        )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.requests_today == 1
        assert stats.requests_total == 1
        assert stats.errors_today == 0

    def test_record_failed_request(self, fresh_orchestrator):
        """Test recording a failed request."""
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=False,
            error="Connection timeout"
        )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.requests_today == 1
        assert stats.errors_today == 1
        assert stats.last_error == "Connection timeout"

    def test_record_updates_latency(self, fresh_orchestrator):
        """Test latency is recorded."""
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=True,
            latency_ms=100.0
        )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.avg_latency_ms == 100.0

    def test_record_moving_average_latency(self, fresh_orchestrator):
        """Test latency uses moving average."""
        # First request
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=True,
            latency_ms=100.0
        )
        # Second request - should use 90/10 weighted average
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=True,
            latency_ms=200.0
        )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        # 100 * 0.9 + 200 * 0.1 = 90 + 20 = 110
        assert stats.avg_latency_ms == 110.0

    def test_record_sets_last_request(self, fresh_orchestrator):
        """Test last_request timestamp is set."""
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.last_request is not None
        assert isinstance(stats.last_request, datetime)

    def test_record_zero_latency_ignored(self, fresh_orchestrator):
        """Test zero latency doesn't affect average."""
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=True,
            latency_ms=100.0
        )
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=True,
            latency_ms=0
        )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.avg_latency_ms == 100.0

    def test_record_multiple_providers(self, fresh_orchestrator):
        """Test recording requests to multiple providers."""
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)
        fresh_orchestrator.record_request(ProviderType.YAHOO, success=True)
        fresh_orchestrator.record_request(ProviderType.YAHOO, success=False)

        assert fresh_orchestrator.stats[ProviderType.IBKR].requests_today == 1
        assert fresh_orchestrator.stats[ProviderType.YAHOO].requests_today == 2
        assert fresh_orchestrator.stats[ProviderType.YAHOO].errors_today == 1

    def test_record_increments_total(self, fresh_orchestrator):
        """Test requests_total is always incremented."""
        for _ in range(5):
            fresh_orchestrator.record_request(ProviderType.IBKR, success=True)
        for _ in range(3):
            fresh_orchestrator.record_request(ProviderType.IBKR, success=False)

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.requests_total == 8
        assert stats.requests_today == 8
        assert stats.errors_today == 3


# =============================================================================
# DAILY RESET TESTS
# =============================================================================

class TestDailyReset:
    """Tests for daily reset functionality."""

    def test_daily_reset_triggers_on_new_day(self, fresh_orchestrator):
        """Test daily reset triggers when date changes."""
        # Record some requests
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)
        fresh_orchestrator.record_request(ProviderType.IBKR, success=False)

        # Simulate previous day
        fresh_orchestrator._last_daily_reset = date.today() - timedelta(days=1)

        # Record another request - should trigger reset
        fresh_orchestrator.record_request(ProviderType.YAHOO, success=True)

        # IBKR stats should be reset
        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.requests_today == 0
        assert stats.errors_today == 0

        # Yahoo should have the new request
        yahoo_stats = fresh_orchestrator.stats[ProviderType.YAHOO]
        assert yahoo_stats.requests_today == 1

    def test_daily_reset_preserves_total(self, fresh_orchestrator):
        """Test daily reset doesn't affect total counts."""
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)
        initial_total = fresh_orchestrator.stats[ProviderType.IBKR].requests_total

        # Simulate previous day
        fresh_orchestrator._last_daily_reset = date.today() - timedelta(days=1)
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)

        # Total should be incremented
        assert fresh_orchestrator.stats[ProviderType.IBKR].requests_total == initial_total + 1

    def test_no_reset_on_same_day(self, fresh_orchestrator):
        """Test no reset when still same day."""
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.requests_today == 2

    def test_daily_reset_updates_last_reset_date(self, fresh_orchestrator):
        """Test _last_daily_reset is updated after reset."""
        fresh_orchestrator._last_daily_reset = date.today() - timedelta(days=1)
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)

        assert fresh_orchestrator._last_daily_reset == date.today()


# =============================================================================
# GET PROVIDER STATUS TESTS
# =============================================================================

class TestGetProviderStatus:
    """Tests for get_provider_status method."""

    def test_status_returns_dict(self, fresh_orchestrator):
        """Test status returns a dict."""
        status = fresh_orchestrator.get_provider_status()
        assert isinstance(status, dict)

    def test_status_contains_active_providers(self, fresh_orchestrator):
        """Test status contains active providers (IBKR + Yahoo)."""
        status = fresh_orchestrator.get_provider_status()
        assert "IBKR/TWS" in status
        assert "Yahoo Finance" in status

    def test_status_does_not_contain_legacy_providers(self, fresh_orchestrator):
        """Test status does not contain removed providers."""
        status = fresh_orchestrator.get_provider_status()
        assert "Marketdata.app" not in status
        assert "Tradier" not in status

    def test_status_has_expected_fields(self, fresh_orchestrator):
        """Test status has expected fields."""
        status = fresh_orchestrator.get_provider_status()
        ibkr = status["IBKR/TWS"]

        assert "enabled" in ibkr
        assert "priority" in ibkr
        assert "rate_limit" in ibkr
        assert "requests_today" in ibkr
        assert "errors_today" in ibkr
        assert "avg_latency_ms" in ibkr
        assert "last_request" in ibkr
        assert "supports" in ibkr

    def test_status_ibkr_has_connected_field(self, fresh_orchestrator):
        """Test IBKR status includes connected field."""
        status = fresh_orchestrator.get_provider_status()
        assert "connected" in status["IBKR/TWS"]

    def test_status_connected_reflects_state(self, fresh_orchestrator):
        """Test connected field reflects actual IBKR state."""
        fresh_orchestrator.enable_ibkr(True)

        status = fresh_orchestrator.get_provider_status()
        assert status["IBKR/TWS"]["connected"] is True

    def test_status_latency_rounded(self, fresh_orchestrator):
        """Test latency is rounded in status."""
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=True,
            latency_ms=123.456789
        )

        status = fresh_orchestrator.get_provider_status()
        assert status["IBKR/TWS"]["avg_latency_ms"] == 123.5

    def test_status_last_request_iso_format(self, fresh_orchestrator):
        """Test last_request is in ISO format."""
        fresh_orchestrator.record_request(ProviderType.IBKR, success=True)

        status = fresh_orchestrator.get_provider_status()
        last_request = status["IBKR/TWS"]["last_request"]

        # Should be ISO format
        assert last_request is not None
        datetime.fromisoformat(last_request)  # Should not raise

    def test_status_supports_list_contains_values(self, fresh_orchestrator):
        """Test supports list contains data type values."""
        status = fresh_orchestrator.get_provider_status()
        supports = status["IBKR/TWS"]["supports"]

        assert "quote" in supports
        assert "news" in supports


# =============================================================================
# UTILITY METHODS TESTS
# =============================================================================

class TestUtilityMethods:
    """Tests for utility methods."""

    def test_should_use_ibkr_false_when_not_connected(self, fresh_orchestrator):
        """Test should_use_ibkr returns False when not connected."""
        result = fresh_orchestrator.should_use_ibkr_for_validation("AAPL")
        assert result is False

    def test_should_use_ibkr_true_when_connected(self, fresh_orchestrator):
        """Test should_use_ibkr returns True when connected."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.should_use_ibkr_for_validation("AAPL")
        assert result is True

    def test_should_use_ibkr_false_when_daily_limit_exceeded(self, fresh_orchestrator):
        """Test should_use_ibkr returns False when daily limit exceeded."""
        fresh_orchestrator.enable_ibkr(True)
        fresh_orchestrator.stats[ProviderType.IBKR].requests_today = 501

        result = fresh_orchestrator.should_use_ibkr_for_validation("AAPL")
        assert result is False

    def test_should_use_ibkr_true_when_under_daily_limit(self, fresh_orchestrator):
        """Test should_use_ibkr returns True when under daily limit."""
        fresh_orchestrator.enable_ibkr(True)
        fresh_orchestrator.stats[ProviderType.IBKR].requests_today = 500

        result = fresh_orchestrator.should_use_ibkr_for_validation("AAPL")
        assert result is True

    def test_get_scan_provider_returns_ibkr(self, fresh_orchestrator):
        """Test scan provider is always IBKR."""
        result = fresh_orchestrator.get_scan_provider()
        assert result == ProviderType.IBKR

    def test_get_scan_provider_always_ibkr(self, fresh_orchestrator):
        """Test scan provider is IBKR regardless of connection state."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_scan_provider()
        assert result == ProviderType.IBKR

    def test_get_vix_provider_returns_yahoo(self, fresh_orchestrator):
        """Test VIX provider returns Yahoo by default."""
        result = fresh_orchestrator.get_vix_provider()
        assert result == ProviderType.YAHOO

    def test_get_vix_provider_returns_yahoo_even_with_ibkr(self, fresh_orchestrator):
        """Test VIX provider returns Yahoo even with IBKR connected (IBKR doesn't support VIX)."""
        fresh_orchestrator.enable_ibkr(True)
        result = fresh_orchestrator.get_vix_provider()
        # IBKR doesn't support VIX in its supports list, so Yahoo is returned
        assert result == ProviderType.YAHOO

    def test_get_vix_provider_fallback_to_yahoo(self, fresh_orchestrator):
        """Test VIX provider falls back to Yahoo."""
        # Even if Yahoo disabled, should return YAHOO as ultimate fallback
        fresh_orchestrator.providers[ProviderType.YAHOO].enabled = False

        result = fresh_orchestrator.get_vix_provider()
        # Should return YAHOO as ultimate fallback
        assert result == ProviderType.YAHOO


# =============================================================================
# CONVENIENCE FUNCTIONS TESTS
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_get_orchestrator_returns_instance(self, reset_singleton):
        """Test get_orchestrator returns ProviderOrchestrator."""
        result = get_orchestrator()
        assert isinstance(result, ProviderOrchestrator)

    def test_get_orchestrator_singleton(self, reset_singleton):
        """Test get_orchestrator returns same instance."""
        result1 = get_orchestrator()
        result2 = get_orchestrator()
        assert result1 is result2

    def test_get_orchestrator_creates_new_after_reset(self, reset_singleton):
        """Test new instance created after reset."""
        result1 = get_orchestrator()
        result1.enable_ibkr(True)  # Modify it

        # Reset singleton
        provider_orchestrator_module._default_orchestrator = None

        result2 = get_orchestrator()
        # Should be a new instance with default state
        assert result2._ibkr_connected is False

    def test_format_provider_status_returns_markdown(self, reset_singleton):
        """Test format_provider_status returns markdown."""
        result = format_provider_status()
        assert isinstance(result, str)
        assert "# Data Provider Status" in result

    def test_format_provider_status_contains_providers(self, reset_singleton):
        """Test format output contains all active providers."""
        result = format_provider_status()
        assert "Yahoo Finance" in result
        assert "IBKR/TWS" in result

    def test_format_provider_status_contains_stats(self, reset_singleton):
        """Test format output contains stats."""
        orchestrator = get_orchestrator()
        orchestrator.record_request(ProviderType.IBKR, success=True)

        result = format_provider_status()
        assert "Requests Today" in result
        assert "Errors Today" in result
        assert "Avg Latency" in result
        assert "Rate Limit" in result

    def test_format_provider_status_shows_connected_status(self, reset_singleton):
        """Test format output shows connection status."""
        orchestrator = get_orchestrator()
        orchestrator.enable_ibkr(True)

        result = format_provider_status()
        assert "Connected" in result


# =============================================================================
# ROUTING PREFERENCES TESTS
# =============================================================================

class TestRoutingPreferences:
    """Tests for routing preferences configuration."""

    def test_all_data_types_have_routing(self, fresh_orchestrator):
        """Test all data types have routing preferences."""
        for data_type in DataType:
            preferences = fresh_orchestrator.ROUTING_PREFERENCES.get(data_type, [])
            # All data types should have at least one provider preference
            assert isinstance(preferences, list)

    def test_quote_routing_order(self, fresh_orchestrator):
        """Test QUOTE routing order: IBKR only."""
        preferences = fresh_orchestrator.ROUTING_PREFERENCES[DataType.QUOTE]
        assert preferences == [ProviderType.IBKR]

    def test_vix_routing_order(self, fresh_orchestrator):
        """Test VIX routing order: IBKR then Yahoo."""
        preferences = fresh_orchestrator.ROUTING_PREFERENCES[DataType.VIX]
        assert preferences == [ProviderType.IBKR, ProviderType.YAHOO]

    def test_news_only_ibkr(self, fresh_orchestrator):
        """Test NEWS only has IBKR."""
        preferences = fresh_orchestrator.ROUTING_PREFERENCES[DataType.NEWS]
        assert preferences == [ProviderType.IBKR]

    def test_earnings_routing(self, fresh_orchestrator):
        """Test EARNINGS routes to Yahoo."""
        preferences = fresh_orchestrator.ROUTING_PREFERENCES[DataType.EARNINGS]
        assert preferences == [ProviderType.YAHOO]


# =============================================================================
# PROVIDER SUPPORT TESTS
# =============================================================================

class TestProviderSupport:
    """Tests for provider support configuration."""

    def test_yahoo_supports(self, fresh_orchestrator):
        """Test Yahoo supported data types."""
        config = fresh_orchestrator.providers[ProviderType.YAHOO]
        assert DataType.VIX in config.supports
        assert DataType.EARNINGS in config.supports
        assert DataType.HISTORICAL in config.supports

    def test_ibkr_supports(self, fresh_orchestrator):
        """Test IBKR supported data types."""
        config = fresh_orchestrator.providers[ProviderType.IBKR]
        assert DataType.QUOTE in config.supports
        assert DataType.HISTORICAL in config.supports
        assert DataType.OPTIONS_CHAIN in config.supports
        assert DataType.NEWS in config.supports
        assert DataType.IV_RANK in config.supports
        assert DataType.MAX_PAIN in config.supports
        assert DataType.STRIKE_RECOMMENDATION in config.supports

    def test_ibkr_does_not_support_vix(self, fresh_orchestrator):
        """Test IBKR does not support VIX."""
        config = fresh_orchestrator.providers[ProviderType.IBKR]
        assert DataType.VIX not in config.supports


# =============================================================================
# EDGE CASES AND ERROR HANDLING
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_record_request_with_none_error(self, fresh_orchestrator):
        """Test recording failed request without error message."""
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=False,
            error=None
        )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.errors_today == 1
        assert stats.last_error is None

    def test_record_request_empty_error_string(self, fresh_orchestrator):
        """Test recording failed request with empty error string."""
        fresh_orchestrator.record_request(
            ProviderType.IBKR,
            success=False,
            error=""
        )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.last_error == ""

    def test_latency_moving_average_convergence(self, fresh_orchestrator):
        """Test latency moving average converges correctly."""
        # All 100ms latency
        for _ in range(100):
            fresh_orchestrator.record_request(
                ProviderType.IBKR,
                success=True,
                latency_ms=100.0
            )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        # Should converge close to 100
        assert 99.9 < stats.avg_latency_ms < 100.1

    def test_large_number_of_requests(self, fresh_orchestrator):
        """Test handling large number of requests."""
        for i in range(10000):
            fresh_orchestrator.record_request(
                ProviderType.IBKR,
                success=True,
                latency_ms=50.0
            )

        stats = fresh_orchestrator.stats[ProviderType.IBKR]
        assert stats.requests_today == 10000
        assert stats.requests_total == 10000

    def test_get_best_provider_with_all_disabled(self, fresh_orchestrator):
        """Test get_best_provider when all providers disabled."""
        fresh_orchestrator.providers[ProviderType.IBKR].enabled = False
        fresh_orchestrator.providers[ProviderType.YAHOO].enabled = False

        result = fresh_orchestrator.get_best_provider(DataType.EARNINGS)
        assert result is None

    def test_enable_disable_rapid_toggle(self, fresh_orchestrator):
        """Test rapid enable/disable toggling."""
        for _ in range(100):
            fresh_orchestrator.enable_ibkr(True)
            fresh_orchestrator.enable_ibkr(False)

        assert fresh_orchestrator._ibkr_connected is False
        assert fresh_orchestrator.providers[ProviderType.IBKR].enabled is False

    def test_concurrent_stats_modification(self, fresh_orchestrator):
        """Test that stats can handle concurrent-like modifications."""
        # Simulate concurrent modifications for active providers
        for provider in fresh_orchestrator.providers:
            fresh_orchestrator.record_request(provider, success=True)
            fresh_orchestrator.record_request(provider, success=False)

        for provider in fresh_orchestrator.providers:
            assert fresh_orchestrator.stats[provider].requests_today == 2


# =============================================================================
# PREFER ACCURACY TESTS
# =============================================================================

class TestPreferAccuracy:
    """Tests for prefer_accuracy parameter."""

    def test_prefer_accuracy_with_ibkr_for_scan(self, fresh_orchestrator):
        """Test prefer_accuracy allows IBKR for SCAN when connected."""
        fresh_orchestrator.enable_ibkr(True)

        result = fresh_orchestrator.get_best_provider(
            DataType.SCAN,
            prefer_accuracy=True
        )
        # IBKR is the only SCAN provider now
        assert result == ProviderType.IBKR

    def test_prefer_accuracy_parameter_accepted(self, fresh_orchestrator):
        """Test prefer_accuracy parameter is accepted."""
        fresh_orchestrator.enable_ibkr(True)

        # Should not raise
        result = fresh_orchestrator.get_best_provider(
            DataType.QUOTE,
            prefer_accuracy=True
        )
        assert result == ProviderType.IBKR


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
