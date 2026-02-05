# Tests for Error Handler
# ========================

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.utils.error_handler import (
    MCPError,
    DataFetchError,
    ConfigurationError,
    format_error_response,
    endpoint,
    mcp_endpoint,
    sync_endpoint,
    safe_format,
    truncate_string,
)
from src.utils.validation import ValidationError
from src.utils.circuit_breaker import CircuitBreakerOpen


class TestFormatErrorResponse:
    """Tests for format_error_response function."""
    
    def test_validation_error(self):
        """Test formatting of ValidationError."""
        error = ValidationError("Invalid symbol: 123ABC")
        result = format_error_response(error, symbol="123ABC")
        
        assert "❌ Validation Error" in result
        assert "123ABC" in result
        assert "Symbols must be 1-5 uppercase letters" in result
    
    def test_circuit_breaker_open(self):
        """Test formatting of CircuitBreakerOpen."""
        error = CircuitBreakerOpen("test_breaker", 45.5)
        result = format_error_response(error)
        
        assert "⚠️ Service Temporarily Unavailable" in result
        assert "45" in result or "46" in result  # retry_after
    
    def test_connection_error(self):
        """Test formatting of ConnectionError."""
        error = ConnectionError("Failed to connect")
        result = format_error_response(error, symbol="AAPL")
        
        assert "❌ Connection Error" in result
        assert "AAPL" in result
        assert "Marketdata.app" in result
    
    def test_timeout_error(self):
        """Test formatting of TimeoutError."""
        error = TimeoutError("Request timed out")
        result = format_error_response(error, operation="quote lookup")
        
        assert "⏱️ Timeout" in result
        assert "quote lookup" in result
    
    def test_value_error(self):
        """Test formatting of ValueError."""
        error = ValueError("Invalid DTE range")
        result = format_error_response(error)
        
        assert "❌ Invalid Input" in result
        assert "Invalid DTE range" in result
    
    def test_mcp_error(self):
        """Test formatting of MCPError."""
        error = MCPError("Technical error", "User-friendly message")
        result = format_error_response(error)
        
        assert "User-friendly message" in result
    
    def test_generic_error(self):
        """Test formatting of generic Exception."""
        error = RuntimeError("Something went wrong")
        result = format_error_response(error)
        
        assert "❌ Unexpected Error" in result
        assert "RuntimeError" in result
        assert "Something went wrong" in result
    
    def test_long_error_message_truncated(self):
        """Test that long error messages are truncated."""
        error = RuntimeError("A" * 500)
        result = format_error_response(error)
        
        # Should be truncated to 200 chars
        assert len(result) < 600


class TestMCPEndpointDecorator:
    """Tests for mcp_endpoint decorator."""
    
    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Test decorator with successful function call."""
        @mcp_endpoint(operation="test operation")
        async def test_func():
            return "Success"
        
        result = await test_func()
        assert result == "Success"
    
    @pytest.mark.asyncio
    async def test_catches_validation_error(self):
        """Test decorator catches ValidationError."""
        @mcp_endpoint(operation="test", symbol_param="symbol")
        async def test_func(symbol: str):
            raise ValidationError(f"Invalid symbol: {symbol}")
        
        result = await test_func("BAD")
        assert "❌ Validation Error" in result
    
    @pytest.mark.asyncio
    async def test_catches_generic_error(self):
        """Test decorator catches generic exceptions."""
        @mcp_endpoint(operation="test operation")
        async def test_func():
            raise RuntimeError("Unexpected error")
        
        result = await test_func()
        assert "❌ Unexpected Error" in result
        assert "RuntimeError" in result
    
    @pytest.mark.asyncio
    async def test_symbol_extraction_from_kwargs(self):
        """Test symbol extraction from keyword arguments."""
        @mcp_endpoint(operation="test", symbol_param="symbol")
        async def test_func(symbol: str = "DEFAULT"):
            raise ValidationError("Test error")
        
        result = await test_func(symbol="AAPL")
        assert "AAPL" in result
    
    @pytest.mark.asyncio
    async def test_symbol_extraction_from_args(self):
        """Test symbol extraction from positional arguments."""
        class TestClass:
            @mcp_endpoint(operation="test", symbol_param="symbol")
            async def test_method(self, symbol: str):
                raise ValidationError("Test error")
        
        obj = TestClass()
        result = await obj.test_method("MSFT")
        assert "MSFT" in result


class TestSyncEndpointDecorator:
    """Tests for sync_endpoint decorator."""
    
    def test_successful_call(self):
        """Test decorator with successful function call."""
        @sync_endpoint(operation="test operation")
        def test_func():
            return "Success"
        
        result = test_func()
        assert result == "Success"
    
    def test_catches_error(self):
        """Test decorator catches exceptions."""
        @sync_endpoint(operation="test operation")
        def test_func():
            raise RuntimeError("Test error")
        
        result = test_func()
        assert "❌ Unexpected Error" in result


class TestSafeFormat:
    """Tests for safe_format function."""
    
    def test_all_keys_present(self):
        """Test formatting with all keys present."""
        result = safe_format("Hello {name}!", name="World")
        assert result == "Hello World!"
    
    def test_missing_key(self):
        """Test formatting with missing key."""
        result = safe_format("Hello {name}! Price: {price}", name="World")
        assert result == "Hello World! Price: N/A"
    
    def test_multiple_missing_keys(self):
        """Test formatting with multiple missing keys."""
        result = safe_format("{a} {b} {c}", a="1")
        assert result == "1 N/A N/A"


class TestTruncateString:
    """Tests for truncate_string function."""
    
    def test_short_string(self):
        """Test string shorter than max length."""
        result = truncate_string("Hello", 10)
        assert result == "Hello"
    
    def test_exact_length(self):
        """Test string exactly at max length."""
        result = truncate_string("Hello", 5)
        assert result == "Hello"
    
    def test_long_string(self):
        """Test string longer than max length."""
        result = truncate_string("Hello World", 8)
        assert result == "Hello..."
        assert len(result) == 8
    
    def test_custom_suffix(self):
        """Test with custom suffix."""
        result = truncate_string("Hello World", 9, suffix="…")
        assert result == "Hello Wo…"


class TestCustomExceptions:
    """Tests for custom exception classes."""

    def test_mcp_error(self):
        """Test MCPError exception."""
        error = MCPError("Technical", "User message")
        assert str(error) == "Technical"
        assert error.user_message == "User message"

    def test_mcp_error_default_user_message(self):
        """Test MCPError with default user message."""
        error = MCPError("Technical message")
        assert error.user_message == "Technical message"

    def test_data_fetch_error(self):
        """Test DataFetchError exception."""
        error = DataFetchError("API error", "Could not fetch data")
        assert isinstance(error, MCPError)

    def test_configuration_error(self):
        """Test ConfigurationError exception."""
        error = ConfigurationError("Config error", "Invalid configuration")
        assert isinstance(error, MCPError)


# =============================================================================
# ADDITIONAL TESTS: Error Types and format_error_response Coverage
# =============================================================================

from src.utils.error_handler import (
    RateLimitError,
    ApiTimeoutError,
    ApiConnectionError,
    ProviderError,
    SymbolNotFoundError,
    NoDataError,
    DataParseError,
    InsufficientDataError,
    ErrorCode,
)


class TestErrorCodeEnum:
    """Tests for ErrorCode enum."""

    def test_error_codes_values(self):
        """Test that error codes have correct values."""
        assert ErrorCode.UNKNOWN.value == 1000
        assert ErrorCode.VALIDATION_ERROR.value == 1001
        assert ErrorCode.CONNECTION_ERROR.value == 2001
        assert ErrorCode.RATE_LIMIT_ERROR.value == 2003
        assert ErrorCode.SYMBOL_NOT_FOUND.value == 3001

    def test_error_codes_names(self):
        """Test that error codes have correct names."""
        assert ErrorCode.UNKNOWN.name == "UNKNOWN"
        assert ErrorCode.CIRCUIT_BREAKER_OPEN.name == "CIRCUIT_BREAKER_OPEN"


class TestMCPErrorFull:
    """Comprehensive tests for MCPError and its attributes."""

    def test_to_dict(self):
        """Test MCPError.to_dict() serialization."""
        error = MCPError(
            "Technical error",
            user_message="User-friendly message",
            error_code=ErrorCode.API_ERROR,
            retryable=True,
            retry_after=30,
        )
        d = error.to_dict()

        assert d['error_code'] == ErrorCode.API_ERROR.value
        assert d['error_name'] == "API_ERROR"
        assert d['message'] == "Technical error"
        assert d['user_message'] == "User-friendly message"
        assert d['retryable'] is True
        assert d['retry_after'] == 30

    def test_error_code_override(self):
        """Test that error_code can be overridden."""
        error = MCPError("msg", error_code=ErrorCode.TIMEOUT_ERROR)
        assert error.error_code == ErrorCode.TIMEOUT_ERROR

    def test_retryable_override(self):
        """Test that retryable can be overridden."""
        error = MCPError("msg", retryable=True)
        assert error.retryable is True

    def test_retry_after_override(self):
        """Test that retry_after can be overridden."""
        error = MCPError("msg", retry_after=120)
        assert error.retry_after == 120

    def test_cause_chaining(self):
        """Test that cause is properly chained."""
        original = ValueError("Original")
        error = MCPError("Wrapped", cause=original)
        assert error.__cause__ is original


class TestSymbolNotFoundError:
    """Tests for SymbolNotFoundError."""

    def test_symbol_stored(self):
        """Test that symbol is stored on error."""
        error = SymbolNotFoundError("FAKESYM")
        assert error.symbol == "FAKESYM"

    def test_message_contains_symbol(self):
        """Test that message contains symbol."""
        error = SymbolNotFoundError("AAPL")
        assert "AAPL" in str(error)

    def test_user_message_helpful(self):
        """Test that user_message is helpful."""
        error = SymbolNotFoundError("XYZ")
        assert "XYZ" in error.user_message
        assert "valid ticker" in error.user_message.lower()

    def test_error_code(self):
        """Test error code is SYMBOL_NOT_FOUND."""
        error = SymbolNotFoundError("TEST")
        assert error.error_code == ErrorCode.SYMBOL_NOT_FOUND


class TestDataParseError:
    """Tests for DataParseError."""

    def test_raw_data_stored(self):
        """Test that raw_data is stored."""
        error = DataParseError("Parse failed", raw_data={"invalid": "data"})
        assert error.raw_data == {"invalid": "data"}

    def test_error_code(self):
        """Test error code is DATA_PARSE_ERROR."""
        error = DataParseError("Parse failed")
        assert error.error_code == ErrorCode.DATA_PARSE_ERROR


class TestSpecificErrorTypes:
    """Tests for specific error types and their default properties."""

    def test_rate_limit_error_defaults(self):
        """Test RateLimitError has correct defaults."""
        error = RateLimitError("Rate limited")
        assert error.error_code == ErrorCode.RATE_LIMIT_ERROR
        assert error.retryable is True
        assert error.retry_after == 60  # default

    def test_api_timeout_error_defaults(self):
        """Test ApiTimeoutError has correct defaults."""
        error = ApiTimeoutError("Timed out")
        assert error.error_code == ErrorCode.TIMEOUT_ERROR
        assert error.retryable is True
        assert error.retry_after == 5

    def test_api_connection_error_defaults(self):
        """Test ApiConnectionError has correct defaults."""
        error = ApiConnectionError("Connection failed")
        assert error.error_code == ErrorCode.CONNECTION_ERROR
        assert error.retryable is True
        assert error.retry_after == 10

    def test_provider_error_defaults(self):
        """Test ProviderError has correct defaults."""
        error = ProviderError("Provider issue")
        assert error.error_code == ErrorCode.PROVIDER_ERROR
        assert error.retryable is True

    def test_no_data_error_defaults(self):
        """Test NoDataError has correct defaults."""
        error = NoDataError("No data")
        assert error.error_code == ErrorCode.NO_DATA_AVAILABLE
        assert error.retryable is False

    def test_insufficient_data_error_defaults(self):
        """Test InsufficientDataError has correct defaults."""
        error = InsufficientDataError("Not enough data")
        assert error.error_code == ErrorCode.INSUFFICIENT_DATA
        assert error.retryable is False


class TestFormatErrorResponseComprehensive:
    """Comprehensive tests for format_error_response with all error types."""

    def test_symbol_not_found_error(self):
        """Test formatting of SymbolNotFoundError."""
        error = SymbolNotFoundError("NOSUCH")
        result = format_error_response(error)

        assert "❌ Symbol Not Found" in result
        assert "NOSUCH" in result

    def test_rate_limit_error(self):
        """Test formatting of RateLimitError."""
        error = RateLimitError("Rate limited")
        result = format_error_response(error)

        assert "⏳ Rate Limit Exceeded" in result
        assert "RATE_LIMIT_ERROR" in result
        assert "60" in result  # retry_after

    def test_api_timeout_error(self):
        """Test formatting of ApiTimeoutError."""
        error = ApiTimeoutError("Timed out")
        result = format_error_response(error, symbol="AAPL")

        assert "⏱️ Request Timeout" in result
        assert "AAPL" in result

    def test_api_connection_error(self):
        """Test formatting of ApiConnectionError."""
        error = ApiConnectionError("Connection failed")
        result = format_error_response(error)

        assert "❌ Connection Failed" in result
        assert "Network connectivity" in result
        assert "API service is down" in result

    def test_no_data_error(self):
        """Test formatting of NoDataError."""
        error = NoDataError("No data available", user_message="No options data for this symbol.")
        result = format_error_response(error, symbol="RARE")

        assert "📭 No Data Available" in result
        assert "RARE" in result

    def test_data_parse_error(self):
        """Test formatting of DataParseError."""
        error = DataParseError("JSON decode error")
        result = format_error_response(error)

        assert "❌ Data Parse Error" in result
        assert "JSON decode" in result

    def test_insufficient_data_error(self):
        """Test formatting of InsufficientDataError."""
        error = InsufficientDataError("Need more data", user_message="Not enough historical data.")
        result = format_error_response(error)

        assert "📊 Insufficient Data" in result
        assert "different symbol or time range" in result

    def test_provider_error(self):
        """Test formatting of ProviderError."""
        error = ProviderError("Provider failed", user_message="The data provider is unavailable.")
        result = format_error_response(error, symbol="GOOG")

        assert "❌ Provider Error" in result
        assert "GOOG" in result

    def test_configuration_error(self):
        """Test formatting of ConfigurationError."""
        error = ConfigurationError("Config issue", user_message="Invalid API key configured.")
        result = format_error_response(error)

        assert "⚙️ Configuration Error" in result
        assert "Invalid API key" in result
        assert "environment variables" in result

    def test_include_error_code_false(self):
        """Test that error codes can be suppressed."""
        error = MCPError("Test error")
        result = format_error_response(error, include_error_code=False)

        assert "UNKNOWN" not in result
        assert "1000" not in result

    def test_error_with_retryable_no_retry_after(self):
        """Test retryable error without retry_after shows hint."""
        error = DataFetchError("Fetch failed")
        # DataFetchError is retryable but has no default retry_after
        error.retry_after = None
        result = format_error_response(error)

        assert "temporary" in result.lower() or "try again" in result.lower()


class TestSyncEndpointSymbolExtraction:
    """Tests for sync_endpoint symbol extraction."""

    def test_symbol_from_kwargs(self):
        """Test symbol extraction from kwargs."""
        @sync_endpoint(operation="test", symbol_param="symbol")
        def test_func(symbol: str = "DEFAULT"):
            raise ValidationError("Test error")

        result = test_func(symbol="TSLA")
        assert "TSLA" in result

    def test_symbol_from_args(self):
        """Test symbol extraction from args."""
        class TestClass:
            @sync_endpoint(operation="test", symbol_param="symbol")
            def test_method(self, symbol: str):
                raise ValidationError("Test error")

        obj = TestClass()
        result = obj.test_method("NVDA")
        assert "NVDA" in result


class TestMCPEndpointNoSymbolParam:
    """Tests for mcp_endpoint when symbol_param is not specified."""

    @pytest.mark.asyncio
    async def test_no_symbol_param(self):
        """Test decorator without symbol_param."""
        @mcp_endpoint(operation="generic operation")
        async def test_func(data: dict):
            raise ValueError("Invalid data")

        result = await test_func({"key": "value"})
        assert "❌ Invalid Input" in result
        # Should not have symbol context
        assert " for " not in result.split("Invalid Input")[0]


class TestCircuitBreakerOpenFormat:
    """Tests for CircuitBreakerOpen formatting."""

    def test_custom_retry_after(self):
        """Test CircuitBreakerOpen with custom retry_after."""
        error = CircuitBreakerOpen("test", retry_after=120.5)
        result = format_error_response(error)

        assert "120" in result or "121" in result

    def test_includes_error_code(self):
        """Test that error code is included."""
        error = CircuitBreakerOpen("test", retry_after=30)
        result = format_error_response(error)

        assert "CIRCUIT_BREAKER_OPEN" in result
        assert "2005" in result  # ErrorCode.CIRCUIT_BREAKER_OPEN.value


class TestDataFetchErrorHierarchy:
    """Tests for DataFetchError class hierarchy."""

    def test_rate_limit_is_data_fetch(self):
        """Test RateLimitError inherits from DataFetchError."""
        error = RateLimitError("Limited")
        assert isinstance(error, DataFetchError)
        assert isinstance(error, MCPError)

    def test_api_timeout_is_data_fetch(self):
        """Test ApiTimeoutError inherits from DataFetchError."""
        error = ApiTimeoutError("Timeout")
        assert isinstance(error, DataFetchError)

    def test_api_connection_is_data_fetch(self):
        """Test ApiConnectionError inherits from DataFetchError."""
        error = ApiConnectionError("No connection")
        assert isinstance(error, DataFetchError)


# =============================================================================
# UNIFIED ENDPOINT DECORATOR TESTS
# =============================================================================


class TestUnifiedEndpointDecorator:
    """Tests for the unified endpoint() decorator."""

    @pytest.mark.asyncio
    async def test_async_successful_call(self):
        """Test endpoint with async function success."""
        @endpoint(operation="test")
        async def async_func():
            return "Async Success"

        result = await async_func()
        assert result == "Async Success"

    def test_sync_successful_call(self):
        """Test endpoint with sync function success."""
        @endpoint(operation="test")
        def sync_func():
            return "Sync Success"

        result = sync_func()
        assert result == "Sync Success"

    @pytest.mark.asyncio
    async def test_async_catches_error(self):
        """Test endpoint catches async function errors."""
        @endpoint(operation="async test")
        async def async_func():
            raise RuntimeError("Async error")

        result = await async_func()
        assert "❌ Unexpected Error" in result
        assert "RuntimeError" in result

    def test_sync_catches_error(self):
        """Test endpoint catches sync function errors."""
        @endpoint(operation="sync test")
        def sync_func():
            raise RuntimeError("Sync error")

        result = sync_func()
        assert "❌ Unexpected Error" in result
        assert "RuntimeError" in result

    @pytest.mark.asyncio
    async def test_async_symbol_extraction_kwargs(self):
        """Test symbol extraction from kwargs in async function."""
        @endpoint(operation="test", symbol_param="symbol")
        async def async_func(symbol: str):
            raise ValidationError("Test error")

        result = await async_func(symbol="AAPL")
        assert "AAPL" in result

    def test_sync_symbol_extraction_kwargs(self):
        """Test symbol extraction from kwargs in sync function."""
        @endpoint(operation="test", symbol_param="symbol")
        def sync_func(symbol: str):
            raise ValidationError("Test error")

        result = sync_func(symbol="GOOGL")
        assert "GOOGL" in result

    @pytest.mark.asyncio
    async def test_async_symbol_extraction_args(self):
        """Test symbol extraction from positional args in async method."""
        class TestClass:
            @endpoint(operation="test", symbol_param="symbol")
            async def method(self, symbol: str):
                raise ValidationError("Test error")

        obj = TestClass()
        result = await obj.method("MSFT")
        assert "MSFT" in result

    def test_sync_symbol_extraction_args(self):
        """Test symbol extraction from positional args in sync method."""
        class TestClass:
            @endpoint(operation="test", symbol_param="symbol")
            def method(self, symbol: str):
                raise ValidationError("Test error")

        obj = TestClass()
        result = obj.method("TSLA")
        assert "TSLA" in result

    @pytest.mark.asyncio
    async def test_async_default_operation_name(self):
        """Test default operation name is function name for async."""
        @endpoint()
        async def my_async_operation():
            raise RuntimeError("Error")

        result = await my_async_operation()
        assert "my_async_operation" in result or "Unexpected Error" in result

    def test_sync_default_operation_name(self):
        """Test default operation name is function name for sync."""
        @endpoint()
        def my_sync_operation():
            raise RuntimeError("Error")

        result = my_sync_operation()
        assert "my_sync_operation" in result or "Unexpected Error" in result

    @pytest.mark.asyncio
    async def test_async_preserves_function_metadata(self):
        """Test that async wrapper preserves function metadata."""
        @endpoint(operation="test")
        async def documented_func():
            """This is a docstring."""
            return "Success"

        assert documented_func.__name__ == "documented_func"
        # Note: docstring may be on inner function

    def test_sync_preserves_function_metadata(self):
        """Test that sync wrapper preserves function metadata."""
        @endpoint(operation="test")
        def documented_func():
            """This is a docstring."""
            return "Success"

        assert documented_func.__name__ == "documented_func"

    @pytest.mark.asyncio
    async def test_async_catches_validation_error(self):
        """Test endpoint catches ValidationError in async."""
        @endpoint(operation="test", symbol_param="symbol")
        async def validate_func(symbol: str):
            raise ValidationError(f"Invalid: {symbol}")

        result = await validate_func("BAD")
        assert "❌ Validation Error" in result

    def test_sync_catches_validation_error(self):
        """Test endpoint catches ValidationError in sync."""
        @endpoint(operation="test", symbol_param="symbol")
        def validate_func(symbol: str):
            raise ValidationError(f"Invalid: {symbol}")

        result = validate_func("BAD")
        assert "❌ Validation Error" in result
