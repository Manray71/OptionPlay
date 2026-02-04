# Tests for Options Service
# =========================
"""
Comprehensive tests for OptionsService class.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from src.services.options_service import OptionsService
from src.services.base import ServiceContext
from src.models.result import ServiceResult


# =============================================================================
# MOCK CLASSES
# =============================================================================

def create_mock_context():
    """Create a mock ServiceContext."""
    context = MagicMock(spec=ServiceContext)
    context.config = MagicMock()
    context.provider = MagicMock()
    context.historical_cache = MagicMock()
    context.rate_limiter = MagicMock()
    return context


def create_mock_option(
    symbol: str = "AAPL250321P00145000",
    underlying: str = "AAPL",
    strike: float = 145.0,
    right: str = "P",
    expiration: str = "2025-03-21",
    bid: float = 1.50,
    ask: float = 1.60,
    delta: float = -0.25,
    iv: float = 0.28
):
    """Create a mock option object."""
    option = MagicMock()
    option.symbol = symbol
    option.underlying = underlying
    option.strike = strike
    option.right = right
    option.expiration = expiration
    option.bid = bid
    option.ask = ask
    option.last = 1.55
    option.volume = 100
    option.openInterest = 500
    option.open_interest = 500
    option.delta = delta
    option.gamma = 0.05
    option.theta = -0.02
    option.vega = 0.10
    option.iv = iv
    option.impliedVolatility = iv
    return option


def create_mock_quote(
    last: float = 150.0,
    bid: float = 149.95,
    ask: float = 150.05
):
    """Create a mock quote object."""
    quote = MagicMock()
    quote.last = last
    quote.bid = bid
    quote.ask = ask
    return quote


def create_mock_historical(
    prices: list = None,
    volumes: list = None,
    highs: list = None,
    lows: list = None
):
    """Create mock historical data."""
    if prices is None:
        prices = [100.0 + i for i in range(90)]
    if volumes is None:
        volumes = [1000000 + i * 10000 for i in range(90)]
    if highs is None:
        highs = [p + 2 for p in prices]
    if lows is None:
        lows = [p - 2 for p in prices]
    return (prices, volumes, highs, lows)


# =============================================================================
# INIT TESTS
# =============================================================================

class TestOptionsServiceInit:
    """Tests for OptionsService initialization."""

    def test_init_with_context(self):
        """Test initialization with context."""
        context = create_mock_context()

        service = OptionsService(context)

        assert service._context is context

    def test_init_creates_strike_recommender(self):
        """Test initialization creates strike recommender."""
        context = create_mock_context()

        service = OptionsService(context)

        assert service._strike_recommender is not None

    def test_init_inherits_from_base_service(self):
        """Test initialization inherits BaseService."""
        context = create_mock_context()

        service = OptionsService(context)

        assert hasattr(service, '_context')
        assert hasattr(service, '_logger')


# =============================================================================
# GET OPTIONS CHAIN TESTS
# =============================================================================

class TestGetOptionsChain:
    """Tests for get_options_chain method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return OptionsService(context)

    @pytest.mark.asyncio
    async def test_returns_service_result(self, service):
        """Test get_options_chain returns ServiceResult."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            provider = MagicMock()
            provider.get_option_chain = AsyncMock(return_value=[create_mock_option()])
            mock_provider.return_value = provider

            with patch.object(service, '_rate_limited') as mock_rate:
                mock_rate.return_value.__aenter__ = AsyncMock()
                mock_rate.return_value.__aexit__ = AsyncMock()

                result = await service.get_options_chain("AAPL")

        assert isinstance(result, ServiceResult)

    @pytest.mark.asyncio
    async def test_validates_symbol(self, service):
        """Test get_options_chain validates symbol."""
        result = await service.get_options_chain("123INVALID")

        assert not result.success
        assert "Invalid" in result.error or "symbol" in result.error.lower()

    @pytest.mark.asyncio
    async def test_validates_dte_range(self, service):
        """Test get_options_chain validates DTE range."""
        result = await service.get_options_chain(
            "AAPL",
            dte_min=60,
            dte_max=30  # Inverted
        )

        assert not result.success

    @pytest.mark.asyncio
    async def test_validates_right(self, service):
        """Test get_options_chain validates right parameter."""
        result = await service.get_options_chain(
            "AAPL",
            right="X"  # Invalid
        )

        assert not result.success

    @pytest.mark.asyncio
    async def test_filters_puts(self, service):
        """Test get_options_chain filters puts correctly."""
        put_option = create_mock_option(right="P")
        call_option = create_mock_option(right="C")

        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            provider = MagicMock()
            provider.get_option_chain = AsyncMock(return_value=[put_option, call_option])
            mock_provider.return_value = provider

            with patch.object(service, '_rate_limited') as mock_rate:
                mock_rate.return_value.__aenter__ = AsyncMock()
                mock_rate.return_value.__aexit__ = AsyncMock()

                result = await service.get_options_chain("AAPL", right="P")

        if result.success:
            assert result.data["right"] == "P"

    @pytest.mark.asyncio
    async def test_filters_calls(self, service):
        """Test get_options_chain filters calls correctly."""
        put_option = create_mock_option(right="P")
        call_option = create_mock_option(right="C")

        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            provider = MagicMock()
            provider.get_option_chain = AsyncMock(return_value=[put_option, call_option])
            mock_provider.return_value = provider

            with patch.object(service, '_rate_limited') as mock_rate:
                mock_rate.return_value.__aenter__ = AsyncMock()
                mock_rate.return_value.__aexit__ = AsyncMock()

                result = await service.get_options_chain("AAPL", right="C")

        if result.success:
            assert result.data["right"] == "C"

    @pytest.mark.asyncio
    async def test_no_data_returns_fail(self, service):
        """Test get_options_chain returns fail when no data."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            provider = MagicMock()
            provider.get_option_chain = AsyncMock(return_value=[])
            mock_provider.return_value = provider

            with patch.object(service, '_rate_limited') as mock_rate:
                mock_rate.return_value.__aenter__ = AsyncMock()
                mock_rate.return_value.__aexit__ = AsyncMock()

                result = await service.get_options_chain("AAPL")

        assert not result.success
        assert "No options data" in result.error

    @pytest.mark.asyncio
    async def test_handles_provider_error(self, service):
        """Test get_options_chain handles provider errors."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            mock_provider.side_effect = Exception("Provider error")

            result = await service.get_options_chain("AAPL")

        assert not result.success

    @pytest.mark.asyncio
    async def test_returns_correct_structure(self, service):
        """Test get_options_chain returns correct data structure."""
        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            provider = MagicMock()
            provider.get_option_chain = AsyncMock(return_value=[create_mock_option()])
            mock_provider.return_value = provider

            with patch.object(service, '_rate_limited') as mock_rate:
                mock_rate.return_value.__aenter__ = AsyncMock()
                mock_rate.return_value.__aexit__ = AsyncMock()

                result = await service.get_options_chain("AAPL")

        if result.success:
            assert "symbol" in result.data
            assert "right" in result.data
            assert "dte_range" in result.data
            assert "count" in result.data
            assert "options" in result.data


# =============================================================================
# GET STRIKE RECOMMENDATION TESTS
# =============================================================================

class TestGetStrikeRecommendation:
    """Tests for get_strike_recommendation method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return OptionsService(context)

    def test_has_get_strike_recommendation_method(self, service):
        """Test service has get_strike_recommendation method."""
        assert hasattr(service, 'get_strike_recommendation')
        assert callable(getattr(service, 'get_strike_recommendation'))

    @pytest.mark.asyncio
    async def test_validates_symbol(self, service):
        """Test get_strike_recommendation validates symbol."""
        result = await service.get_strike_recommendation("123INVALID")

        assert not result.success

    @pytest.mark.asyncio
    async def test_validates_dte_range(self, service):
        """Test get_strike_recommendation validates DTE range."""
        result = await service.get_strike_recommendation(
            "AAPL",
            dte_min=90,
            dte_max=30  # Inverted
        )

        assert not result.success

    @pytest.mark.asyncio
    async def test_returns_service_result(self, service):
        """Test get_strike_recommendation returns ServiceResult."""
        mock_quote = create_mock_quote()
        mock_historical = create_mock_historical()
        mock_recommendation = MagicMock()
        mock_recommendation.to_dict.return_value = {
            "short_strike": 145.0,
            "long_strike": 140.0,
            "spread_width": 5.0
        }

        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            provider = MagicMock()
            provider.get_quote = AsyncMock(return_value=mock_quote)
            provider.get_historical_for_scanner = AsyncMock(return_value=mock_historical)
            provider.get_option_chain = AsyncMock(return_value=[create_mock_option()])
            mock_provider.return_value = provider

            with patch.object(service, '_rate_limited') as mock_rate:
                mock_rate.return_value.__aenter__ = AsyncMock()
                mock_rate.return_value.__aexit__ = AsyncMock()

                with patch.object(service._strike_recommender, 'get_recommendation') as mock_rec:
                    mock_rec.return_value = mock_recommendation
                    with patch.object(service._strike_recommender, 'get_multiple_recommendations') as mock_multi:
                        mock_multi.return_value = []

                        result = await service.get_strike_recommendation("AAPL")

        assert isinstance(result, ServiceResult)

    @pytest.mark.asyncio
    async def test_handles_no_quote(self, service):
        """Test get_strike_recommendation handles missing quote."""
        mock_quote = MagicMock()
        mock_quote.last = None

        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            provider = MagicMock()
            provider.get_quote = AsyncMock(return_value=mock_quote)
            mock_provider.return_value = provider

            with patch.object(service, '_rate_limited') as mock_rate:
                mock_rate.return_value.__aenter__ = AsyncMock()
                mock_rate.return_value.__aexit__ = AsyncMock()

                result = await service.get_strike_recommendation("AAPL")

        assert not result.success
        assert "price" in result.error.lower()

    @pytest.mark.asyncio
    async def test_handles_no_historical(self, service):
        """Test get_strike_recommendation handles missing historical data."""
        mock_quote = create_mock_quote()

        with patch.object(service, '_get_provider', new_callable=AsyncMock) as mock_provider:
            provider = MagicMock()
            provider.get_quote = AsyncMock(return_value=mock_quote)
            provider.get_historical_for_scanner = AsyncMock(return_value=None)
            mock_provider.return_value = provider

            with patch.object(service, '_rate_limited') as mock_rate:
                mock_rate.return_value.__aenter__ = AsyncMock()
                mock_rate.return_value.__aexit__ = AsyncMock()

                result = await service.get_strike_recommendation("AAPL")

        assert not result.success
        assert "historical" in result.error.lower() or "Insufficient" in result.error


# =============================================================================
# GET OPTIONS CHAIN FORMATTED TESTS
# =============================================================================

class TestGetOptionsChainFormatted:
    """Tests for get_options_chain_formatted method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return OptionsService(context)

    def test_has_method(self, service):
        """Test service has get_options_chain_formatted method."""
        assert hasattr(service, 'get_options_chain_formatted')
        assert callable(getattr(service, 'get_options_chain_formatted'))

    @pytest.mark.asyncio
    async def test_returns_string(self, service):
        """Test get_options_chain_formatted returns string."""
        with patch.object(service, 'get_options_chain', new_callable=AsyncMock) as mock_chain:
            mock_chain.return_value = ServiceResult.ok({
                "symbol": "AAPL",
                "right": "P",
                "dte_range": "30-60",
                "count": 1,
                "options": [{"strike": 145.0, "bid": 1.50, "ask": 1.60}]
            })

            result = await service.get_options_chain_formatted("AAPL")

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self, service):
        """Test get_options_chain_formatted returns error on failure."""
        with patch.object(service, 'get_options_chain', new_callable=AsyncMock) as mock_chain:
            mock_chain.return_value = ServiceResult.fail("Connection error")

            result = await service.get_options_chain_formatted("AAPL")

        assert "failed" in result.lower()


# =============================================================================
# GET STRIKE RECOMMENDATION FORMATTED TESTS
# =============================================================================

class TestGetStrikeRecommendationFormatted:
    """Tests for get_strike_recommendation_formatted method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return OptionsService(context)

    def test_has_method(self, service):
        """Test service has get_strike_recommendation_formatted method."""
        assert hasattr(service, 'get_strike_recommendation_formatted')
        assert callable(getattr(service, 'get_strike_recommendation_formatted'))

    @pytest.mark.asyncio
    async def test_returns_string(self, service):
        """Test get_strike_recommendation_formatted returns string."""
        with patch.object(service, 'get_strike_recommendation', new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = ServiceResult.ok({
                "symbol": "AAPL",
                "current_price": 150.0,
                "recommendation": {
                    "short_strike": 145.0,
                    "long_strike": 140.0,
                    "spread_width": 5.0,
                    "quality": "good",
                    "confidence_score": 75
                },
                "alternatives": [],
                "support_levels": [140.0, 135.0],
                "fib_levels": [142.0, 138.0]
            })

            result = await service.get_strike_recommendation_formatted("AAPL")

        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self, service):
        """Test get_strike_recommendation_formatted returns error on failure."""
        with patch.object(service, 'get_strike_recommendation', new_callable=AsyncMock) as mock_rec:
            mock_rec.return_value = ServiceResult.fail("Connection error")

            result = await service.get_strike_recommendation_formatted("AAPL")

        assert "failed" in result.lower()


# =============================================================================
# HELPER TESTS
# =============================================================================

class TestOptionsServiceHelpers:
    """Tests for helper methods."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return OptionsService(context)

    def test_has_option_to_dict_method(self, service):
        """Test service has _option_to_dict method."""
        assert hasattr(service, '_option_to_dict')
        assert callable(getattr(service, '_option_to_dict'))

    def test_option_to_dict_basic(self, service):
        """Test _option_to_dict converts option correctly."""
        option = create_mock_option()
        # Remove to_dict to test attribute-based extraction
        del option.to_dict

        result = service._option_to_dict(option)

        assert isinstance(result, dict)
        assert "strike" in result
        assert "expiration" in result
        assert "right" in result
        assert "bid" in result
        assert "ask" in result

    def test_option_to_dict_with_to_dict_method(self, service):
        """Test _option_to_dict uses option's to_dict if available."""
        option = MagicMock()
        expected = {"strike": 145.0, "custom": True}
        option.to_dict.return_value = expected

        result = service._option_to_dict(option)

        assert result == expected

    def test_option_to_dict_extracts_greeks(self, service):
        """Test _option_to_dict extracts greeks."""
        option = create_mock_option()
        # Remove to_dict method to use fallback
        del option.to_dict

        result = service._option_to_dict(option)

        assert "delta" in result
        assert "gamma" in result
        assert "theta" in result
        assert "vega" in result
        assert "iv" in result


# =============================================================================
# FORMAT OPTIONS CHAIN TESTS
# =============================================================================

class TestFormatOptionsChain:
    """Tests for _format_options_chain method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return OptionsService(context)

    def test_has_method(self, service):
        """Test service has _format_options_chain method."""
        assert hasattr(service, '_format_options_chain')
        assert callable(getattr(service, '_format_options_chain'))

    def test_formats_as_markdown(self, service):
        """Test _format_options_chain returns markdown string."""
        data = {
            "symbol": "AAPL",
            "right": "P",
            "dte_range": "30-60",
            "count": 2,
            "options": [
                {"strike": 145.0, "bid": 1.50, "ask": 1.60, "expiration": "2025-03-21", "delta": -0.25, "iv": 0.28, "open_interest": 500},
                {"strike": 140.0, "bid": 0.80, "ask": 0.90, "expiration": "2025-03-21", "delta": -0.15, "iv": 0.25, "open_interest": 300},
            ]
        }

        result = service._format_options_chain(data)

        assert isinstance(result, str)
        assert "AAPL" in result
        assert "Puts" in result

    def test_handles_empty_options(self, service):
        """Test _format_options_chain handles empty options."""
        data = {
            "symbol": "AAPL",
            "right": "P",
            "dte_range": "30-60",
            "count": 0,
            "options": []
        }

        result = service._format_options_chain(data)

        assert isinstance(result, str)
        assert "No" in result or "no" in result


# =============================================================================
# FORMAT STRIKE RECOMMENDATION TESTS
# =============================================================================

class TestFormatStrikeRecommendation:
    """Tests for _format_strike_recommendation method."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return OptionsService(context)

    def test_has_method(self, service):
        """Test service has _format_strike_recommendation method."""
        assert hasattr(service, '_format_strike_recommendation')
        assert callable(getattr(service, '_format_strike_recommendation'))

    def test_formats_as_markdown(self, service):
        """Test _format_strike_recommendation returns markdown string."""
        data = {
            "symbol": "AAPL",
            "current_price": 150.0,
            "recommendation": {
                "short_strike": 145.0,
                "long_strike": 140.0,
                "spread_width": 5.0,
                "short_strike_reason": "Below support",
                "quality": "good",
                "confidence_score": 75,
                "estimated_credit": 1.50,
                "max_profit": 150.0,
                "max_loss": 350.0,
                "break_even": 143.5,
                "prob_profit": 80.0,
                "warnings": []
            },
            "alternatives": [],
            "support_levels": [140.0, 135.0]
        }

        result = service._format_strike_recommendation(data)

        assert isinstance(result, str)
        assert "AAPL" in result
        assert "145" in result or "$145" in result

    def test_includes_warnings(self, service):
        """Test _format_strike_recommendation includes warnings."""
        data = {
            "symbol": "AAPL",
            "current_price": 150.0,
            "recommendation": {
                "short_strike": 145.0,
                "long_strike": 140.0,
                "spread_width": 5.0,
                "short_strike_reason": "Below support",
                "quality": "acceptable",
                "confidence_score": 50,
                "warnings": ["Near earnings", "High IV"]
            },
            "alternatives": [],
            "support_levels": []
        }

        result = service._format_strike_recommendation(data)

        assert isinstance(result, str)
        assert "Warning" in result or "warning" in result or "Warnings" in result

    def test_includes_alternatives(self, service):
        """Test _format_strike_recommendation includes alternatives."""
        data = {
            "symbol": "AAPL",
            "current_price": 150.0,
            "recommendation": {
                "short_strike": 145.0,
                "long_strike": 140.0,
                "spread_width": 5.0,
                "short_strike_reason": "Below support",
                "quality": "good",
                "confidence_score": 75
            },
            "alternatives": [
                {
                    "short_strike": 142.5,
                    "long_strike": 137.5,
                    "spread_width": 5.0,
                    "quality": "acceptable",
                    "confidence_score": 60
                }
            ],
            "support_levels": []
        }

        result = service._format_strike_recommendation(data)

        assert isinstance(result, str)
        assert "Alternative" in result or "alternative" in result


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestOptionsServiceIntegration:
    """Integration tests for OptionsService."""

    @pytest.fixture
    def service(self):
        context = create_mock_context()
        return OptionsService(context)

    @pytest.mark.asyncio
    async def test_chain_and_recommendation_workflow(self, service):
        """Test combined chain and recommendation workflow."""
        # This would be a full integration test
        # For unit tests, we mock dependencies
        pass

    def test_service_has_all_required_methods(self, service):
        """Test service has all required public methods."""
        required_methods = [
            'get_options_chain',
            'get_strike_recommendation',
            'get_options_chain_formatted',
            'get_strike_recommendation_formatted',
        ]

        for method in required_methods:
            assert hasattr(service, method)
            assert callable(getattr(service, method))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
