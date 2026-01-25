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
