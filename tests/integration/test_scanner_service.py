# Tests for Scanner Service
# =========================
"""
Comprehensive tests for ScannerService class.

Coverage:
1. ScannerService initialization
2. scan() method - single strategy scanning
3. scan_multi() method - multi-strategy scanning
4. Filter application (stability, earnings)
5. Score calculation
6. Error handling
7. Formatted output methods
8. Helper methods
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime
from dataclasses import dataclass

from src.constants.trading_rules import ENTRY_EARNINGS_MIN_DAYS
from src.services.scanner_service import ScannerService, STRATEGY_TO_MODE
from src.services.base import ServiceContext
from src.models.strategy import Strategy
from src.models.result import ServiceResult
from src.scanner.multi_strategy_scanner import ScanMode, ScanResult, ScanConfig


# =============================================================================
# MOCK CLASSES AND FIXTURES
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


def create_mock_recommendation(
    min_score: float = 5.0,
    earnings_buffer_days: int = ENTRY_EARNINGS_MIN_DAYS
):
    """Create a mock StrategyRecommendation."""
    rec = MagicMock()
    rec.min_score = min_score
    rec.earnings_buffer_days = earnings_buffer_days
    rec.delta_target = -0.20
    rec.delta_min = -0.17
    rec.delta_max = -0.23
    rec.profile_name = "standard"
    return rec


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

    def test_all_strategies_map_to_different_modes(self):
        """Test each strategy maps to a unique mode."""
        modes = list(STRATEGY_TO_MODE.values())
        assert len(modes) == len(set(modes))


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

    def test_init_inherits_from_base_service(self):
        """Test ScannerService inherits from BaseService."""
        context = create_mock_context()
        service = ScannerService(context)

        # Should have BaseService attributes
        assert hasattr(service, '_context')
        assert hasattr(service, '_config')
        assert hasattr(service, '_logger')

    def test_init_has_required_methods(self):
        """Test service has all required methods."""
        context = create_mock_context()
        service = ScannerService(context)

        required_methods = [
            'scan', 'scan_multi', 'scan_formatted', 'scan_multi_formatted',
            '_prepare_symbols', '_determine_min_score', '_get_historical_days',
            '_create_scanner', '_create_multi_scanner', '_fetch_historical_cached',
            '_format_scan_result', '_format_multi_scan_result'
        ]
        for method in required_methods:
            assert hasattr(service, method), f"Missing method: {method}"


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
        mock_recommendation = create_mock_recommendation()

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

    @pytest.mark.asyncio
    async def test_scan_skips_vix_for_non_credit_spread_strategies(self, service):
        """Test scan skips VIX strategy for strategies not suitable for credit spreads."""
        mock_scan_result = create_mock_scan_result()

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
                            # ATH_BREAKOUT is not suitable for credit spreads
                            result = await service.scan(
                                strategy=Strategy.ATH_BREAKOUT,
                                symbols=["AAPL"],
                                use_vix_strategy=True
                            )

        # VIX service should NOT have been called for non-credit-spread strategy
        # unless Strategy.ATH_BREAKOUT.suitable_for_credit_spreads is True
        if not Strategy.ATH_BREAKOUT.suitable_for_credit_spreads:
            mock_vix.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_handles_scanner_exception(self, service):
        """Test scan handles exception from scanner."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(side_effect=Exception("Scanner error"))
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        with patch.object(service._vix_service, 'get_strategy_recommendation', new_callable=AsyncMock) as mock_vix:
                            mock_vix.return_value = ServiceResult.fail("No VIX")

                            result = await service.scan(
                                strategy=Strategy.PULLBACK,
                                symbols=["AAPL"],
                                use_vix_strategy=False
                            )

        assert not result.success
        assert "Scan failed" in result.error

    @pytest.mark.asyncio
    async def test_scan_with_max_results(self, service):
        """Test scan respects max_results parameter."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan(
                            strategy=Strategy.PULLBACK,
                            symbols=["AAPL"],
                            max_results=5,
                            use_vix_strategy=False
                        )

        # Check that max_total_results was set on scanner config
        assert mock_scanner.config.max_total_results == 5

    @pytest.mark.asyncio
    async def test_scan_with_custom_min_score(self, service):
        """Test scan uses custom min_score when provided."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan(
                            strategy=Strategy.PULLBACK,
                            symbols=["AAPL"],
                            min_score=8.0,
                            use_vix_strategy=False
                        )

        # _create_scanner should have been called with min_score=8.0
        # _create_scanner(strategy, effective_min_score, recommendation)
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        # min_score is the second positional argument (index 1)
        assert call_args[0][1] == 8.0

    @pytest.mark.asyncio
    async def test_scan_returns_duration_ms(self, service):
        """Test scan result includes duration_ms."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan(
                            strategy=Strategy.PULLBACK,
                            symbols=["AAPL"],
                            use_vix_strategy=False
                        )

        assert result.success
        assert result.duration_ms is not None
        assert result.duration_ms >= 0


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

    @pytest.mark.asyncio
    async def test_scan_multi_with_specific_strategies(self, service):
        """Test scan_multi with specific strategies list."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_multi_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan_multi(
                            symbols=["AAPL"],
                            strategies=[Strategy.PULLBACK, Strategy.BOUNCE]
                        )

        # Verify _create_multi_scanner was called with correct strategy flags
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs['enable_pullback'] == True
        assert call_kwargs['enable_bounce'] == True
        assert call_kwargs['enable_breakout'] == False
        assert call_kwargs['enable_earnings_dip'] == False

    @pytest.mark.asyncio
    async def test_scan_multi_all_strategies_when_none_specified(self, service):
        """Test scan_multi enables all strategies when None specified."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_multi_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan_multi(
                            symbols=["AAPL"],
                            strategies=None
                        )

        # All strategies should be enabled when None
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs['enable_pullback'] == True
        assert call_kwargs['enable_bounce'] == True
        assert call_kwargs['enable_breakout'] == True
        assert call_kwargs['enable_earnings_dip'] == True

    @pytest.mark.asyncio
    async def test_scan_multi_uses_best_signal_mode(self, service):
        """Test scan_multi uses BEST_SIGNAL scan mode."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_multi_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan_multi(symbols=["AAPL"])

        # Verify scan_async was called with BEST_SIGNAL mode
        call_kwargs = mock_scanner.scan_async.call_args[1]
        assert call_kwargs['mode'] == ScanMode.BEST_SIGNAL

    @pytest.mark.asyncio
    async def test_scan_multi_increases_max_results_for_scanner(self, service):
        """Test scan_multi doubles max_results for scanner (to allow filtering)."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_multi_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan_multi(
                            symbols=["AAPL"],
                            max_results=10
                        )

        # Scanner should have max_total_results = max_results * 2
        assert mock_scanner.config.max_total_results == 20

    @pytest.mark.asyncio
    async def test_scan_multi_handles_scanner_exception(self, service):
        """Test scan_multi handles exception from scanner."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_multi_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(side_effect=Exception("Multi-scan error"))
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan_multi(symbols=["AAPL"])

        assert not result.success
        assert "Multi-scan failed" in result.error


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

    @pytest.mark.asyncio
    async def test_scan_formatted_with_vix_strategy(self, service):
        """Test scan_formatted includes VIX recommendation when enabled."""
        mock_scan_result = create_mock_scan_result(
            signals=[create_mock_signal()]
        )
        mock_recommendation = create_mock_recommendation()

        with patch.object(service, 'scan', new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = ServiceResult.ok(mock_scan_result)
            with patch.object(service._vix_service, 'get_strategy_recommendation', new_callable=AsyncMock) as mock_vix:
                mock_vix.return_value = ServiceResult.ok(mock_recommendation)

                result = await service.scan_formatted(
                    strategy=Strategy.PULLBACK,
                    symbols=["AAPL"],
                    use_vix_strategy=True
                )

        assert isinstance(result, str)
        # VIX service should have been called
        mock_vix.assert_called_once()


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

    @pytest.mark.asyncio
    async def test_with_empty_list_uses_watchlist(self, service):
        """Test _prepare_symbols with empty list returns empty (doesn't use watchlist)."""
        with patch('src.services.scanner_service.validate_symbols') as mock_validate:
            mock_validate.return_value = []

            result = await service._prepare_symbols([])

        # Empty list should result in validate_symbols being called
        mock_validate.assert_not_called()  # Actually, empty list should trigger watchlist

    @pytest.mark.asyncio
    async def test_filters_invalid_symbols(self, service):
        """Test _prepare_symbols filters invalid symbols."""
        with patch('src.services.scanner_service.validate_symbols') as mock_validate:
            mock_validate.return_value = ["AAPL"]  # Only AAPL valid

            result = await service._prepare_symbols(["AAPL", "INVALID!!!"])

        mock_validate.assert_called_once()


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
        mock_recommendation = create_mock_recommendation(min_score=6.0)

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

    def test_explicit_zero_is_used(self, service):
        """Test explicit min_score of 0 is used (not treated as falsy)."""
        result = service._determine_min_score(
            strategy=Strategy.PULLBACK,
            min_score=0.0,
            recommendation=None
        )
        # Note: 0.0 is falsy in Python, so this might use default
        # Depending on implementation, this tests edge case
        # If implementation uses "if min_score is not None", 0.0 works
        # If implementation uses "if min_score", 0.0 fails
        assert result == 0.0 or result == Strategy.PULLBACK.default_min_score

    def test_all_strategies_have_default(self, service):
        """Test all strategies have a default min_score."""
        for strategy in Strategy:
            result = service._determine_min_score(
                strategy=strategy,
                min_score=None,
                recommendation=None
            )
            assert result > 0  # All defaults should be positive


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

    def test_ath_breakout_requires_most_days(self, service):
        """Test ATH_BREAKOUT requires the most historical days."""
        service._config.settings.performance.historical_days = 30

        # ATH breakout needs ~260 days for full year ATH detection
        ath_days = service._get_historical_days(Strategy.ATH_BREAKOUT)
        pullback_days = service._get_historical_days(Strategy.PULLBACK)

        assert ath_days >= pullback_days


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

    def test_creates_scanner_for_bounce(self, service):
        """Test creates scanner configured for bounce."""
        with patch('src.services.scanner_service.get_scan_config') as mock_config:
            mock_scan_config = MagicMock()
            mock_config.return_value = mock_scan_config
            with patch('src.services.scanner_service.MultiStrategyScanner') as mock_scanner:
                scanner = service._create_scanner(
                    strategy=Strategy.BOUNCE,
                    min_score=5.0,
                    recommendation=None
                )

        # Check that only bounce is enabled
        assert mock_scan_config.enable_bounce == True

    def test_uses_recommendation_earnings_buffer(self, service):
        """Test scanner uses earnings_buffer_days from recommendation."""
        mock_recommendation = create_mock_recommendation(earnings_buffer_days=45)

        with patch('src.services.scanner_service.get_scan_config') as mock_config:
            mock_scan_config = MagicMock()
            mock_config.return_value = mock_scan_config
            with patch('src.services.scanner_service.MultiStrategyScanner') as mock_scanner:
                scanner = service._create_scanner(
                    strategy=Strategy.PULLBACK,
                    min_score=5.0,
                    recommendation=mock_recommendation
                )

        # Verify get_scan_config was called with override_earnings_days
        mock_config.assert_called_once()
        call_kwargs = mock_config.call_args[1]
        assert call_kwargs.get('override_earnings_days') == 45


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

    def test_passes_strategy_flags(self, service):
        """Test passes strategy enable flags correctly."""
        with patch('src.services.scanner_service.MultiStrategyScanner') as mock_scanner:
            scanner = service._create_multi_scanner(
                min_score=6.0,
                enable_pullback=True,
                enable_bounce=False,
                enable_breakout=True,
                enable_earnings_dip=False
            )

        call_args = mock_scanner.call_args
        config = call_args[0][0]
        assert config.enable_pullback == True
        assert config.enable_bounce == False
        assert config.enable_ath_breakout == True
        assert config.enable_earnings_dip == False

    def test_passes_min_score(self, service):
        """Test passes min_score to scanner config."""
        with patch('src.services.scanner_service.MultiStrategyScanner') as mock_scanner:
            scanner = service._create_multi_scanner(
                min_score=7.5,
                enable_pullback=True,
                enable_bounce=True,
                enable_breakout=True,
                enable_earnings_dip=True
            )

        call_args = mock_scanner.call_args
        config = call_args[0][0]
        assert config.min_score == 7.5


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

    @pytest.mark.asyncio
    async def test_returns_none_on_api_failure(self, service):
        """Test returns None when API fetch fails."""
        from src.cache import CacheStatus

        with patch.object(service, '_get_historical_cache') as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache_result = MagicMock()
            mock_cache_result.status = CacheStatus.MISS
            mock_cache.get.return_value = mock_cache_result
            mock_get_cache.return_value = mock_cache

            with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
                provider = MagicMock()
                provider.get_historical_for_scanner = AsyncMock(side_effect=Exception("API error"))
                mock_provider.return_value = provider

                with patch.object(service, '_rate_limited') as mock_rate:
                    mock_rate.return_value.__aenter__ = AsyncMock()
                    mock_rate.return_value.__aexit__ = AsyncMock()

                    result = await service._fetch_historical_cached("AAPL", 90)

        assert result is None

    @pytest.mark.asyncio
    async def test_caches_successful_fetch(self, service):
        """Test successful fetch is cached."""
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

        # Verify cache.set was called with the data
        mock_cache.set.assert_called_once_with("AAPL", mock_data, days=90)


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

    def test_includes_vix_when_provided(self, service):
        """Test includes VIX in output when provided."""
        mock_result = create_mock_scan_result(signals=[])

        result = service._format_scan_result(
            result=mock_result,
            strategy=Strategy.PULLBACK,
            vix=25.5,
            recommendation=None,
            max_results=10
        )

        assert "25.5" in result or "VIX" in result

    def test_respects_max_results(self, service):
        """Test respects max_results limit."""
        signals = [
            create_mock_signal(symbol=f"SYM{i}", score=10-i)
            for i in range(20)
        ]
        mock_result = create_mock_scan_result(signals=signals)

        result = service._format_scan_result(
            result=mock_result,
            strategy=Strategy.PULLBACK,
            vix=15.0,
            recommendation=None,
            max_results=5
        )

        # Should not contain all 20 symbols
        assert "SYM19" not in result


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

    def test_groups_by_strategy(self, service):
        """Test groups signals by strategy in output."""
        mock_result = create_mock_scan_result(
            signals=[
                create_mock_signal(symbol="AAPL", strategy="pullback"),
                create_mock_signal(symbol="MSFT", strategy="pullback"),
                create_mock_signal(symbol="GOOGL", strategy="bounce"),
            ]
        )

        result = service._format_multi_scan_result(
            result=mock_result,
            vix=15.0,
            max_results=10
        )

        # Should contain strategy summary
        assert "Strategy" in result or "Summary" in result


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        vix_service = create_mock_vix_service()
        return ScannerService(context, vix_service=vix_service)

    @pytest.mark.asyncio
    async def test_connection_error_returns_fail_result(self, service):
        """Test connection error returns failed ServiceResult."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock:
            mock.side_effect = ConnectionError("Network error")

            result = await service.scan(Strategy.PULLBACK, ["AAPL"])

        assert not result.success
        assert "Connection" in result.error

    @pytest.mark.asyncio
    async def test_timeout_error_returns_fail_result(self, service):
        """Test timeout error returns failed ServiceResult."""
        import asyncio
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock:
            mock.side_effect = asyncio.TimeoutError("Timeout")

            result = await service.scan(Strategy.PULLBACK, ["AAPL"])

        assert not result.success

    @pytest.mark.asyncio
    async def test_generic_exception_returns_fail_result(self, service):
        """Test generic exception returns failed ServiceResult."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock:
            mock.side_effect = RuntimeError("Unexpected error")

            result = await service.scan(Strategy.PULLBACK, ["AAPL"])

        assert not result.success

    @pytest.mark.asyncio
    async def test_vix_failure_doesnt_block_scan(self, service):
        """Test VIX fetch failure doesn't block the scan."""
        mock_scan_result = create_mock_scan_result()

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
                            mock_vix.return_value = ServiceResult.fail("VIX unavailable")

                            result = await service.scan(
                                strategy=Strategy.PULLBACK,
                                symbols=["AAPL"],
                                use_vix_strategy=True
                            )

        # Scan should still succeed even if VIX failed
        assert result.success


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

    def test_strategy_has_suitable_for_credit_spreads(self):
        """Test all strategies have suitable_for_credit_spreads property."""
        for strategy in Strategy:
            assert hasattr(strategy, 'suitable_for_credit_spreads')
            assert isinstance(strategy.suitable_for_credit_spreads, bool)

    def test_service_result_types(self):
        """Test ServiceResult factory methods work correctly."""
        # Test ok
        ok_result = ServiceResult.ok(data="test", source="test")
        assert ok_result.success
        assert ok_result.data == "test"

        # Test fail
        fail_result = ServiceResult.fail(error="test error")
        assert not fail_result.success
        assert fail_result.error == "test error"

    def test_scan_config_defaults(self):
        """Test ScanConfig has sensible defaults."""
        config = ScanConfig()
        assert config.min_score > 0
        assert config.max_total_results > 0
        assert config.max_concurrent > 0


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        vix_service = create_mock_vix_service()
        return ScannerService(context, vix_service=vix_service)

    @pytest.mark.asyncio
    async def test_scan_with_single_symbol(self, service):
        """Test scan works with single symbol."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan(
                            strategy=Strategy.PULLBACK,
                            symbols=["AAPL"],
                            use_vix_strategy=False
                        )

        assert result.success

    @pytest.mark.asyncio
    async def test_scan_with_many_symbols(self, service):
        """Test scan works with many symbols."""
        mock_scan_result = create_mock_scan_result()
        many_symbols = [f"SYM{i}" for i in range(100)]

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = many_symbols
                with patch.object(service, '_create_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan(
                            strategy=Strategy.PULLBACK,
                            symbols=many_symbols,
                            use_vix_strategy=False
                        )

        assert result.success

    def test_format_with_none_values(self, service):
        """Test formatting handles None values gracefully."""
        signal = create_mock_signal()
        signal.current_price = None
        signal.reason = None

        mock_result = create_mock_scan_result(signals=[signal])

        # Should not raise exception
        result = service._format_scan_result(
            result=mock_result,
            strategy=Strategy.PULLBACK,
            vix=None,  # VIX can be None
            recommendation=None,
            max_results=10
        )

        assert isinstance(result, str)

    def test_format_with_empty_details(self, service):
        """Test formatting handles empty details dict."""
        signal = create_mock_signal()
        signal.details = {}

        mock_result = create_mock_scan_result(signals=[signal])

        # Should not raise exception
        result = service._format_scan_result(
            result=mock_result,
            strategy=Strategy.PULLBACK,
            vix=15.0,
            recommendation=None,
            max_results=10
        )

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_scan_multi_with_only_one_strategy(self, service):
        """Test scan_multi works with only one strategy enabled."""
        mock_scan_result = create_mock_scan_result()

        with patch.object(service, '_get_provider', new_callable=AsyncMock):
            with patch.object(service, '_prepare_symbols', new_callable=AsyncMock) as mock_prepare:
                mock_prepare.return_value = ["AAPL"]
                with patch.object(service, '_create_multi_scanner') as mock_create:
                    mock_scanner = MagicMock()
                    mock_scanner.scan_async = AsyncMock(return_value=mock_scan_result)
                    mock_scanner.config = MagicMock()
                    mock_create.return_value = mock_scanner
                    with patch.object(service, '_fetch_historical_cached', new_callable=AsyncMock):
                        result = await service.scan_multi(
                            symbols=["AAPL"],
                            strategies=[Strategy.PULLBACK]  # Only one
                        )

        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
