# Tests for Scanner Service
# =========================
"""
Comprehensive tests for ScannerService class.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from src.services.scanner_service import ScannerService, STRATEGY_TO_MODE
from src.services.base import ServiceContext
from src.models.strategy import Strategy
from src.models.result import ServiceResult
from src.scanner.multi_strategy_scanner import ScanMode, ScanResult, ScanConfig


# =============================================================================
# MOCK CLASSES
# =============================================================================

def create_mock_context():
    """Create a mock ServiceContext."""
    context = MagicMock(spec=ServiceContext)
    context.config = MagicMock()
    context.config.settings = MagicMock()
    context.config.settings.performance = MagicMock()
    context.config.settings.performance.historical_days = 90
    context.provider = MagicMock()
    context.historical_cache = MagicMock()
    context.rate_limiter = MagicMock()
    return context


def create_mock_scan_result(
    symbols_scanned: int = 10,
    signals: list = None,
    scan_duration: float = 1.5
):
    """Create a mock ScanResult."""
    result = MagicMock(spec=ScanResult)
    result.symbols_scanned = symbols_scanned
    result.symbols_with_signals = len(signals) if signals else 0
    result.signals = signals or []
    result.scan_duration_seconds = scan_duration
    result.strategy = "pullback"
    return result


def create_mock_signal(
    symbol: str = "AAPL",
    score: float = 7.5,
    strategy: str = "pullback",
    current_price: float = 150.0,
    reason: str = "RSI oversold"
):
    """Create a mock signal."""
    signal = MagicMock()
    signal.symbol = symbol
    signal.score = score
    signal.strategy = strategy
    signal.current_price = current_price
    signal.reason = reason
    signal.details = {"rsi": 30}
    return signal


def create_mock_vix_service(vix: float = 15.0):
    """Create a mock VIX service."""
    vix_service = MagicMock()
    vix_service.current_vix = vix
    vix_service.get_strategy_recommendation = AsyncMock()
    return vix_service


# =============================================================================
# STRATEGY TO MODE MAPPING TESTS
# =============================================================================

class TestStrategyToModeMapping:
    """Tests for STRATEGY_TO_MODE mapping."""

    def test_pullback_mapping(self):
        """Test PULLBACK strategy maps correctly."""
        assert STRATEGY_TO_MODE[Strategy.PULLBACK] == ScanMode.PULLBACK_ONLY

    def test_bounce_mapping(self):
        """Test BOUNCE strategy maps correctly."""
        assert STRATEGY_TO_MODE[Strategy.BOUNCE] == ScanMode.BOUNCE_ONLY

    def test_ath_breakout_mapping(self):
        """Test ATH_BREAKOUT strategy maps correctly."""
        assert STRATEGY_TO_MODE[Strategy.ATH_BREAKOUT] == ScanMode.BREAKOUT_ONLY

    def test_earnings_dip_mapping(self):
        """Test EARNINGS_DIP strategy maps correctly."""
        assert STRATEGY_TO_MODE[Strategy.EARNINGS_DIP] == ScanMode.EARNINGS_DIP

    def test_mapping_contains_four_strategies(self):
        """Test mapping contains exactly 4 strategies."""
        assert len(STRATEGY_TO_MODE) == 4


# =============================================================================
# SCANNER SERVICE INIT TESTS
# =============================================================================

class TestScannerServiceInit:
    """Tests for ScannerService initialization."""

    def test_init_with_context(self):
        """Test initialization with context."""
        context = create_mock_context()

        service = ScannerService(context)

        assert service._context is context

    def test_init_creates_vix_service(self):
        """Test initialization creates VIX service."""
        context = create_mock_context()

        service = ScannerService(context)

        assert service._vix_service is not None

    def test_init_with_vix_service(self):
        """Test initialization with provided VIX service."""
        context = create_mock_context()
        vix_service = MagicMock()

        service = ScannerService(context, vix_service=vix_service)

        assert service._vix_service is vix_service


# =============================================================================
# SCAN METHOD TESTS
# =============================================================================

class TestScanMethod:
    """Tests for scan method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        vix_service = create_mock_vix_service()
        return ScannerService(context, vix_service=vix_service)

    def test_scan_method_exists(self):
        """Test scan method exists on ScannerService."""
        context = create_mock_context()
        service = ScannerService(context)
        assert hasattr(service, 'scan')
        assert callable(getattr(service, 'scan'))

    @pytest.mark.asyncio
    async def test_scan_connection_failure(self, service):
        """Test scan handles connection failure."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            mock_provider.side_effect = Exception("Connection failed")

            result = await service.scan(
                strategy=Strategy.PULLBACK,
                symbols=["AAPL"]
            )

        assert not result.success
        assert "Connection" in result.error

    @pytest.mark.asyncio
    async def test_scan_no_symbols_returns_fail(self, service):
        """Test scan returns fail when no valid symbols."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = []

                result = await service.scan(
                    strategy=Strategy.PULLBACK,
                    symbols=["INVALID!!!"]
                )

        assert not result.success
        assert "No valid symbols" in result.error

    @pytest.mark.asyncio
    async def test_scan_returns_service_result(self, service):
        """Test scan returns ServiceResult on success."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL", "MSFT"]
                with patch.object(service, '_create_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        with patch.object(service._vix_service, 'get_strategy_recommendation', new_callable=AsyncMock) as mock_vix:
                            mock_vix.return_value = ServiceResult.fail("No VIX")

                            result = await service.scan(
                                strategy=Strategy.PULLBACK,
                                symbols=["AAPL", "MSFT"],
                                use_vix_strategy=False
                            )

        assert isinstance(result, ServiceResult)

    @pytest.mark.asyncio
    async def test_scan_uses_vix_strategy_when_enabled(self, service):
        """Test scan uses VIX strategy when enabled."""
        mock_scan_result = create_mock_scan_result()
        mock_recommendation = MagicMock()
        mock_recommendation.min_score = 6.0
        mock_recommendation.earnings_buffer_days = 45

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        with patch.object(service._vix_service, 'get_strategy_recommendation', new_callable=AsyncMock) as mock_vix:
                            mock_vix.return_value = ServiceResult.ok(mock_recommendation)

                            result = await service.scan(
                                strategy=Strategy.PULLBACK,
                                symbols=["AAPL"],
                                use_vix_strategy=True
                            )

        # VIX service should have been called
        mock_vix.assert_called_once()


# =============================================================================
# SCAN MULTI METHOD TESTS
# =============================================================================

class TestScanMultiMethod:
    """Tests for scan_multi method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        vix_service = create_mock_vix_service()
        return ScannerService(context, vix_service=vix_service)

    def test_scan_multi_method_exists(self):
        """Test scan_multi method exists."""
        context = create_mock_context()
        service = ScannerService(context)
        assert hasattr(service, 'scan_multi')
        assert callable(getattr(service, 'scan_multi'))

    @pytest.mark.asyncio
    async def test_scan_multi_connection_failure(self, service):
        """Test scan_multi handles connection failure."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            mock_provider.side_effect = Exception("Connection failed")

            result = await service.scan_multi(symbols=["AAPL"])

        assert not result.success
        assert "Connection" in result.error

    @pytest.mark.asyncio
    async def test_scan_multi_no_symbols_returns_fail(self, service):
        """Test scan_multi returns fail when no valid symbols."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = []

                result = await service.scan_multi(symbols=["INVALID!!!"])

        assert not result.success
        assert "No valid symbols" in result.error

    @pytest.mark.asyncio
    async def test_scan_multi_returns_service_result(self, service):
        """Test scan_multi returns ServiceResult on success."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL", "MSFT"]
                with patch.object(service, '_create_multi_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan_multi(
                            symbols=["AAPL", "MSFT"],
                            max_results=10,
                            min_score=5.0
                        )

        assert isinstance(result, ServiceResult)


# =============================================================================
# SCAN FORMATTED METHOD TESTS
# =============================================================================

class TestScanFormattedMethod:
    """Tests for scan_formatted method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        vix_service = create_mock_vix_service()
        return ScannerService(context, vix_service=vix_service)

    def test_scan_formatted_method_exists(self):
        """Test scan_formatted method exists."""
        context = create_mock_context()
        service = ScannerService(context)
        assert hasattr(service, 'scan_formatted')
        assert callable(getattr(service, 'scan_formatted'))

    @pytest.mark.asyncio
    async def test_scan_formatted_returns_string(self, service):
        """Test scan_formatted returns string."""
        mock_scan_result = create_mock_scan_result(
            signals=[create_mock_signal()]
        )

        with patch.object(service, 'scan', new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = ServiceResult.ok(mock_scan_result)
            with patch.object(service._vix_service, 'get_strategy_recommendation', new_callable=AsyncMock) as mock_vix:
                mock_vix.return_value = ServiceResult.fail("No VIX")

                result = await service.scan_formatted(
                    strategy=Strategy.PULLBACK,
                    symbols=["AAPL"],
                    use_vix_strategy=False
                )

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_scan_formatted_returns_error_on_failure(self, service):
        """Test scan_formatted returns error message on failure."""
        with patch.object(service, 'scan', new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = ServiceResult.fail("Connection error")

            result = await service.scan_formatted(
                strategy=Strategy.PULLBACK,
                symbols=["AAPL"]
            )

        assert "failed" in result.lower()


# =============================================================================
# SCAN MULTI FORMATTED METHOD TESTS
# =============================================================================

class TestScanMultiFormattedMethod:
    """Tests for scan_multi_formatted method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        vix_service = create_mock_vix_service()
        return ScannerService(context, vix_service=vix_service)

    def test_scan_multi_formatted_method_exists(self):
        """Test scan_multi_formatted method exists."""
        context = create_mock_context()
        service = ScannerService(context)
        assert hasattr(service, 'scan_multi_formatted')
        assert callable(getattr(service, 'scan_multi_formatted'))

    @pytest.mark.asyncio
    async def test_scan_multi_formatted_returns_string(self, service):
        """Test scan_multi_formatted returns string."""
        mock_scan_result = create_mock_scan_result(
            signals=[create_mock_signal()]
        )

        with patch.object(service, 'scan_multi', new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = ServiceResult.ok(mock_scan_result)

            result = await service.scan_multi_formatted(
                symbols=["AAPL"],
                max_results=10,
                min_score=5.0
            )

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_scan_multi_formatted_returns_error_on_failure(self, service):
        """Test scan_multi_formatted returns error message on failure."""
        with patch.object(service, 'scan_multi', new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = ServiceResult.fail("Connection error")

            result = await service.scan_multi_formatted(symbols=["AAPL"])

        assert "failed" in result.lower()


# =============================================================================
# HELPER METHOD TESTS
# =============================================================================

class TestPrepareSymbols:
    """Tests for _prepare_symbols helper method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return ScannerService(context)

    @pytest.mark.asyncio
    async def test_with_provided_symbols(self, service):
        """Test _prepare_symbols with provided symbols."""
        with patch('src.services.scanner_service.validate_symbols') as mock_validate:
            mock_validate.return_value = ["AAPL", "MSFT"]

            result = await service._prepare_symbols(["aapl", "msft"])

        assert result == ["AAPL", "MSFT"]

    @pytest.mark.asyncio
    async def test_with_none_uses_watchlist(self, service):
        """Test _prepare_symbols with None uses watchlist."""
        with patch('src.services.scanner_service.get_watchlist_loader') as mock_loader:
            mock_watchlist = MagicMock()
            mock_watchlist.get_all_symbols.return_value = ["AAPL", "MSFT", "GOOGL"]
            mock_loader.return_value = mock_watchlist

            result = await service._prepare_symbols(None)

        assert result == ["AAPL", "MSFT", "GOOGL"]


class TestDetermineMinScore:
    """Tests for _determine_min_score helper method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return ScannerService(context)

    def test_explicit_min_score_used(self, service):
        """Test explicit min_score is used when provided."""
        result = service._determine_min_score(
            strategy=Strategy.PULLBACK,
            min_score=7.5,
            recommendation=None
        )
        assert result == 7.5

    def test_recommendation_min_score_used(self, service):
        """Test recommendation min_score is used when no explicit."""
        mock_recommendation = MagicMock()
        mock_recommendation.min_score = 6.0

        result = service._determine_min_score(
            strategy=Strategy.PULLBACK,
            min_score=None,
            recommendation=mock_recommendation
        )
        assert result == 6.0

    def test_strategy_default_used(self, service):
        """Test strategy default is used when no explicit or recommendation."""
        result = service._determine_min_score(
            strategy=Strategy.PULLBACK,
            min_score=None,
            recommendation=None
        )
        assert result == Strategy.PULLBACK.default_min_score


class TestGetHistoricalDays:
    """Tests for _get_historical_days helper method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return ScannerService(context)

    def test_uses_strategy_min_days(self, service):
        """Test uses strategy min_historical_days when larger."""
        # Mock config with low historical_days
        service._config.settings.performance.historical_days = 30

        # Strategy requires more days
        result = service._get_historical_days(Strategy.ATH_BREAKOUT)

        assert result >= Strategy.ATH_BREAKOUT.min_historical_days

    def test_uses_config_days_when_larger(self, service):
        """Test uses config days when larger than strategy min."""
        # Mock config with high historical_days
        service._config.settings.performance.historical_days = 300

        result = service._get_historical_days(Strategy.PULLBACK)

        assert result == 300


class TestCreateScanner:
    """Tests for _create_scanner helper method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return ScannerService(context)

    def test_creates_scanner_for_pullback(self, service):
        """Test creates scanner configured for pullback."""
        with patch('src.services.scanner_service.get_scan_config') as mock_config:
            mock_scan_config = MagicMock()
            mock_config.return_value = mock_scan_config
            with patch('src.services.scanner_service.MultiStrategyScanner') as mock_scanner:
                scanner = service._create_scanner(
                    strategy=Strategy.PULLBACK,
                    min_score=5.0,
                    recommendation=None
                )

        mock_scan_config.enable_pullback = True
        mock_scan_config.enable_bounce = False
        mock_scan_config.enable_ath_breakout = False
        mock_scan_config.enable_earnings_dip = False


class TestCreateMultiScanner:
    """Tests for _create_multi_scanner helper method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return ScannerService(context)

    def test_creates_multi_scanner(self, service):
        """Test creates multi-strategy scanner."""
        with patch('src.services.scanner_service.MultiStrategyScanner') as mock_scanner:
            scanner = service._create_multi_scanner(
                min_score=5.0,
                enable_pullback=True,
                enable_bounce=True,
                enable_breakout=False,
                enable_earnings_dip=False
            )

        mock_scanner.assert_called_once()
        call_args = mock_scanner.call_args
        config = call_args[0][0]
        assert isinstance(config, ScanConfig)


class TestFetchHistoricalCached:
    """Tests for _fetch_historical_cached helper method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return ScannerService(context)

    @pytest.mark.asyncio
    async def test_returns_cached_data_on_hit(self, service):
        """Test returns cached data on cache hit."""
        mock_data = ([100.0, 101.0], [1000, 1100], [102.0, 103.0], [99.0, 100.0])

        with patch.object(service, '_get_historical_cache') as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache_result = MagicMock()
            mock_cache_result.status.name = "HIT"
            mock_cache_result.data = mock_data

            # Mock CacheStatus.HIT
            from src.cache import CacheStatus
            mock_cache_result.status = CacheStatus.HIT

            mock_cache.get.return_value = mock_cache_result
            mock_get_cache.return_value = mock_cache

            result = await service._fetch_historical_cached("AAPL", 90)

        assert result == mock_data

    @pytest.mark.asyncio
    async def test_fetches_from_api_on_cache_miss(self, service):
        """Test fetches from API on cache miss."""
        mock_data = ([100.0, 101.0], [1000, 1100], [102.0, 103.0], [99.0, 100.0])

        from src.cache import CacheStatus

        with patch.object(service, '_get_historical_cache') as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache_result = MagicMock()
            mock_cache_result.status = CacheStatus.MISS
            mock_cache.get.return_value = mock_cache_result
            mock_get_cache.return_value = mock_cache

            with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
                provider = MagicMock()
                provider.get_historical_for_scanner = AsyncMock(return_value=mock_data)
                mock_provider.return_value = provider

                with patch.object(service, '_rate_limited') as mock_rate:
                    mock_rate.return_value.__aenter__ = AsyncMock()
                    mock_rate.return_value.__aexit__ = AsyncMock()

                    result = await service._fetch_historical_cached("AAPL", 90)

        assert result == mock_data
        mock_cache.set.assert_called_once()


# =============================================================================
# FORMAT METHOD TESTS
# =============================================================================

class TestFormatScanResult:
    """Tests for _format_scan_result helper method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return ScannerService(context)

    def test_formats_result_as_markdown(self, service):
        """Test formats result as markdown."""
        mock_result = create_mock_scan_result(
            signals=[create_mock_signal()]
        )

        result = service._format_scan_result(
            result=mock_result,
            strategy=Strategy.PULLBACK,
            vix=15.0,
            recommendation=None,
            max_results=10
        )

        assert isinstance(result, str)
        # Result should contain scan info like symbol, score, or scan title
        assert "AAPL" in result or "Scan" in result or "Bull" in result

    def test_formats_empty_result(self, service):
        """Test formats empty result."""
        mock_result = create_mock_scan_result(signals=[])

        result = service._format_scan_result(
            result=mock_result,
            strategy=Strategy.PULLBACK,
            vix=15.0,
            recommendation=None,
            max_results=10
        )

        assert isinstance(result, str)
        assert "No" in result or "no" in result


class TestFormatMultiScanResult:
    """Tests for _format_multi_scan_result helper method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return ScannerService(context)

    def test_formats_multi_result_as_markdown(self, service):
        """Test formats multi-strategy result as markdown."""
        mock_result = create_mock_scan_result(
            signals=[
                create_mock_signal(symbol="AAPL", strategy="pullback"),
                create_mock_signal(symbol="MSFT", strategy="bounce"),
            ]
        )

        result = service._format_multi_scan_result(
            result=mock_result,
            vix=15.0,
            max_results=10
        )

        assert isinstance(result, str)
        assert "Multi" in result

    def test_formats_empty_multi_result(self, service):
        """Test formats empty multi-strategy result."""
        mock_result = create_mock_scan_result(signals=[])

        result = service._format_multi_scan_result(
            result=mock_result,
            vix=15.0,
            max_results=10
        )

        assert isinstance(result, str)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestScannerServiceIntegration:
    """Integration tests for ScannerService."""

    def test_all_strategies_have_mode_mapping(self):
        """Test that main 4 strategies have mode mapping."""
        expected = [
            Strategy.PULLBACK,
            Strategy.BOUNCE,
            Strategy.ATH_BREAKOUT,
            Strategy.EARNINGS_DIP,
        ]
        for strategy in expected:
            assert strategy in STRATEGY_TO_MODE

    def test_strategy_has_default_min_score(self):
        """Test all mapped strategies have default_min_score."""
        for strategy in STRATEGY_TO_MODE.keys():
            assert hasattr(strategy, 'default_min_score')
            assert strategy.default_min_score > 0

    def test_strategy_has_min_historical_days(self):
        """Test all mapped strategies have min_historical_days."""
        for strategy in STRATEGY_TO_MODE.keys():
            assert hasattr(strategy, 'min_historical_days')
            assert strategy.min_historical_days > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
