# OptionPlay - Error Handler
# ===========================
# Unified error handling for MCP server endpoints
#
# Error Hierarchy:
# - MCPError (base)
#   - DataFetchError (API/network errors)
#     - RateLimitError (rate limit exceeded)
#     - ApiTimeoutError (request timeout)
#     - ApiConnectionError (connection failed)
#   - ConfigurationError (config issues)
#   - ProviderError (data provider issues)
#   - SymbolNotFoundError (invalid symbol)

import asyncio
import functools
import inspect
import logging
from enum import Enum
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar, Optional, Union

from .validation import ValidationError
from .circuit_breaker import CircuitBreakerOpen
from .markdown_builder import MarkdownBuilder

logger = logging.getLogger(__name__)

# Type variable for return type
T = TypeVar('T')


class ErrorCode(Enum):
    """Standard error codes for tracking and monitoring."""
    # General errors (1xxx)
    UNKNOWN = 1000
    VALIDATION_ERROR = 1001
    CONFIGURATION_ERROR = 1002

    # Network/API errors (2xxx)
    CONNECTION_ERROR = 2001
    TIMEOUT_ERROR = 2002
    RATE_LIMIT_ERROR = 2003
    API_ERROR = 2004
    CIRCUIT_BREAKER_OPEN = 2005

    # Data errors (3xxx)
    SYMBOL_NOT_FOUND = 3001
    NO_DATA_AVAILABLE = 3002
    DATA_PARSE_ERROR = 3003
    PROVIDER_ERROR = 3004

    # Business logic errors (4xxx)
    INVALID_OPERATION = 4001
    INSUFFICIENT_DATA = 4002


class MCPError(Exception):
    """Base exception for MCP-specific errors."""

    error_code: ErrorCode = ErrorCode.UNKNOWN
    retryable: bool = False
    retry_after: Optional[int] = None

    def __init__(
        self,
        message: str,
        user_message: Optional[str] = None,
        error_code: Optional[ErrorCode] = None,
        retryable: Optional[bool] = None,
        retry_after: Optional[int] = None,
        cause: Optional[Exception] = None
    ) -> None:
        """
        Initialize MCP error.

        Args:
            message: Technical error message for logging
            user_message: User-friendly message for display (optional)
            error_code: Error code for tracking (optional)
            retryable: Whether the operation can be retried (optional)
            retry_after: Seconds to wait before retry (optional)
            cause: Original exception that caused this error (optional)
        """
        super().__init__(message)
        self.user_message = user_message or message
        if error_code is not None:
            self.error_code = error_code
        if retryable is not None:
            self.retryable = retryable
        if retry_after is not None:
            self.retry_after = retry_after
        self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for logging/serialization."""
        return {
            'error_code': self.error_code.value,
            'error_name': self.error_code.name,
            'message': str(self),
            'user_message': self.user_message,
            'retryable': self.retryable,
            'retry_after': self.retry_after,
        }


class DataFetchError(MCPError):
    """Error fetching data from external API."""
    error_code = ErrorCode.API_ERROR
    retryable = True


class RateLimitError(DataFetchError):
    """API rate limit exceeded."""
    error_code = ErrorCode.RATE_LIMIT_ERROR
    retryable = True
    retry_after = 60  # Default: wait 60 seconds


class ApiTimeoutError(DataFetchError):
    """API request timed out."""
    error_code = ErrorCode.TIMEOUT_ERROR
    retryable = True
    retry_after = 5


class ApiConnectionError(DataFetchError):
    """Failed to connect to API."""
    error_code = ErrorCode.CONNECTION_ERROR
    retryable = True
    retry_after = 10


class ConfigurationError(MCPError):
    """Error in configuration."""
    error_code = ErrorCode.CONFIGURATION_ERROR
    retryable = False


class ProviderError(MCPError):
    """Error from data provider."""
    error_code = ErrorCode.PROVIDER_ERROR
    retryable = True


class SymbolNotFoundError(MCPError):
    """Symbol not found or invalid."""
    error_code = ErrorCode.SYMBOL_NOT_FOUND
    retryable = False

    def __init__(self, symbol: str, **kwargs: Any) -> None:
        message = f"Symbol not found: {symbol}"
        user_message = f"The symbol '{symbol}' was not found. Please verify it's a valid ticker symbol."
        super().__init__(message, user_message=user_message, **kwargs)
        self.symbol = symbol


class NoDataError(MCPError):
    """No data available for the requested operation."""
    error_code = ErrorCode.NO_DATA_AVAILABLE
    retryable = False


class DataParseError(MCPError):
    """Error parsing data from API response."""
    error_code = ErrorCode.DATA_PARSE_ERROR
    retryable = False

    def __init__(self, message: str, raw_data: Any = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.raw_data = raw_data


class InsufficientDataError(MCPError):
    """Insufficient data for the requested operation."""
    error_code = ErrorCode.INSUFFICIENT_DATA
    retryable = False


def format_error_response(
    error: Exception,
    symbol: Optional[str] = None,
    operation: Optional[str] = None,
    include_error_code: bool = True
) -> str:
    """
    Format an exception into a user-friendly Markdown response.

    Args:
        error: The exception that occurred
        symbol: Optional symbol that was being processed
        operation: Optional operation name
        include_error_code: Include error code in response (default: True)

    Returns:
        Formatted Markdown error message
    """
    context = f" for {symbol}" if symbol else ""
    op_context = f" during {operation}" if operation else ""

    b = MarkdownBuilder()

    # Helper to add error code and retry info
    def add_error_metadata(err: MCPError) -> None:
        if include_error_code:
            b.kv("Code", f"{err.error_code.name} ({err.error_code.value})")
        if err.retryable and err.retry_after:
            b.kv("Retry in", f"{err.retry_after} seconds")
        elif err.retryable:
            b.text("_This error may be temporary. Try again._")

    # Handle specific error types (most specific first)
    if isinstance(error, SymbolNotFoundError):
        b.h1(f"❌ Symbol Not Found").blank()
        b.kv("Symbol", error.symbol)
        b.text(error.user_message).blank()
        add_error_metadata(error)
        return b.build()

    if isinstance(error, RateLimitError):
        b.h1("⏳ Rate Limit Exceeded").blank()
        b.text("Too many requests to the API.").blank()
        add_error_metadata(error)
        b.hint("Wait a moment and try again.")
        return b.build()

    if isinstance(error, ApiTimeoutError):
        b.h1(f"⏱️ Request Timeout{context}").blank()
        b.text("The API request took too long.").blank()
        add_error_metadata(error)
        b.kv("Suggestion", "Try again or reduce the scope of your request.")
        return b.build()

    if isinstance(error, ApiConnectionError):
        b.h1(f"❌ Connection Failed{context}").blank()
        b.text("Could not connect to the API.").blank()
        b.text("**Possible causes:**")
        b.bullet("Network connectivity issues")
        b.bullet("API service is down")
        b.bullet("Invalid API key").blank()
        add_error_metadata(error)
        return b.build()

    if isinstance(error, NoDataError):
        b.h1(f"📭 No Data Available{context}").blank()
        b.text(error.user_message).blank()
        add_error_metadata(error)
        return b.build()

    if isinstance(error, DataParseError):
        b.h1(f"❌ Data Parse Error{context}").blank()
        b.text("Failed to parse data from API response.").blank()
        b.kv("Details", str(error)[:200])
        add_error_metadata(error)
        return b.build()

    if isinstance(error, InsufficientDataError):
        b.h1(f"📊 Insufficient Data{context}").blank()
        b.text(error.user_message).blank()
        add_error_metadata(error)
        b.hint("Try with a different symbol or time range.")
        return b.build()

    if isinstance(error, ProviderError):
        b.h1(f"❌ Provider Error{context}").blank()
        b.kv("Details", error.user_message).blank()
        add_error_metadata(error)
        return b.build()

    if isinstance(error, ConfigurationError):
        b.h1("⚙️ Configuration Error").blank()
        b.kv("Issue", error.user_message).blank()
        add_error_metadata(error)
        b.hint("Check your configuration files and environment variables.")
        return b.build()

    if isinstance(error, ValidationError):
        b.h1(f"❌ Validation Error{context}").blank()
        b.kv("Issue", str(error)).blank()
        b.hint("Symbols must be 1-5 uppercase letters (e.g., AAPL, MSFT, GOOGL)")
        return b.build()

    if isinstance(error, CircuitBreakerOpen):
        retry_after = getattr(error, 'retry_after', 60)
        b.h1("⚠️ Service Temporarily Unavailable").blank()
        b.text("The API is temporarily unavailable due to repeated failures.").blank()
        b.kv("Retry in", f"{retry_after:.0f} seconds").blank()
        if include_error_code:
            b.kv("Code", f"CIRCUIT_BREAKER_OPEN ({ErrorCode.CIRCUIT_BREAKER_OPEN.value})")
        b.hint("The circuit breaker will automatically retry after the timeout.")
        return b.build()

    if isinstance(error, ConnectionError):
        b.h1(f"❌ Connection Error{context}").blank()
        b.text("Could not connect to Marketdata.app API.").blank()
        b.text("**Possible causes:**")
        b.bullet("Network connectivity issues")
        b.bullet("API service is down")
        b.bullet("Invalid API key")
        b.blank()
        b.kv("Action", "Check your internet connection and API key configuration.")
        return b.build()

    if isinstance(error, TimeoutError):
        b.h1(f"⏱️ Timeout{context}{op_context}").blank()
        b.text("The request took too long to complete.").blank()
        b.kv("Suggestion", "Try again or reduce the scope of your request.")
        return b.build()

    if isinstance(error, ValueError):
        b.h1(f"❌ Invalid Input{context}").blank()
        b.kv("Error", str(error)).blank()
        b.text("Please check your input parameters.")
        return b.build()

    if isinstance(error, MCPError):
        b.h1(f"❌ Error{context}{op_context}").blank()
        b.kv("Details", error.user_message).blank()
        add_error_metadata(error)
        return b.build()

    # Generic error fallback
    error_type = type(error).__name__
    b.h1(f"❌ Unexpected Error{context}{op_context}").blank()
    b.kv("Type", error_type)
    b.kv("Details", str(error)[:200]).blank()
    if include_error_code:
        b.kv("Code", f"UNKNOWN ({ErrorCode.UNKNOWN.value})")
    b.hint("If this persists, please check the server logs.")
    return b.build()


# =============================================================================
# UNIFIED ENDPOINT DECORATOR
# =============================================================================


def _extract_symbol(
    func: Callable[..., Any],
    symbol_param: Optional[str],
    args: tuple[Any, ...],
    kwargs: dict[str, Any]
) -> Optional[str]:
    """
    Extract symbol parameter from function arguments.

    Args:
        func: The decorated function
        symbol_param: Name of the symbol parameter
        args: Positional arguments
        kwargs: Keyword arguments

    Returns:
        Symbol value or None
    """
    if not symbol_param:
        return None

    # Try kwargs first
    symbol: Any = kwargs.get(symbol_param)
    if symbol is not None:
        return str(symbol)

    # Try positional args (skip self for methods)
    if len(args) > 1:
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        if symbol_param in params:
            idx = params.index(symbol_param)
            if idx < len(args):
                return str(args[idx])

    return None


def endpoint(
    operation: Optional[str] = None,
    symbol_param: Optional[str] = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Unified decorator for MCP endpoints with automatic sync/async detection.

    Automatically detects whether the decorated function is synchronous or
    asynchronous and applies the appropriate wrapper. Catches all exceptions
    and converts them to user-friendly Markdown responses.

    Args:
        operation: Name of the operation (for error messages). Defaults to function name.
        symbol_param: Name of the symbol parameter (for error messages)

    Returns:
        Decorated function with error handling

    Usage::

        @endpoint(operation="quote lookup", symbol_param="symbol")
        async def get_quote(self, symbol: str) -> str:
            ...

        @endpoint(operation="health check")
        def get_health(self) -> str:
            ...

    Note:
        This replaces both mcp_endpoint (async) and sync_endpoint (sync).
        The function type is detected at decoration time using asyncio.iscoroutinefunction().
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        op_name = operation or func.__name__

        if asyncio.iscoroutinefunction(func):
            # Async wrapper
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> str:
                symbol = _extract_symbol(func, symbol_param, args, kwargs)
                try:
                    result: str = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.exception(f"Error in {op_name}: {e}")
                    return format_error_response(e, symbol=symbol, operation=op_name)
            return async_wrapper
        else:
            # Sync wrapper
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> str:
                symbol = _extract_symbol(func, symbol_param, args, kwargs)
                try:
                    result: str = func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.exception(f"Error in {op_name}: {e}")
                    return format_error_response(e, symbol=symbol, operation=op_name)
            return sync_wrapper

    return decorator


# =============================================================================
# LEGACY DECORATORS (deprecated, use endpoint() instead)
# =============================================================================


def mcp_endpoint(
    operation: Optional[str] = None,
    symbol_param: Optional[str] = None
) -> Callable[[Callable[..., Coroutine[Any, Any, str]]], Callable[..., Coroutine[Any, Any, str]]]:
    """
    Decorator for MCP server endpoints with unified error handling.
    
    Catches all exceptions and converts them to user-friendly Markdown responses.
    
    Args:
        operation: Name of the operation (for error messages)
        symbol_param: Name of the symbol parameter (for error messages)
        
    Returns:
        Decorated function
        
    Usage:
        @mcp_endpoint(operation="quote lookup", symbol_param="symbol")
        async def get_quote(self, symbol: str) -> str:
            ...
    """
    def decorator(func: Callable[..., Coroutine[Any, Any, str]]) -> Callable[..., Coroutine[Any, Any, str]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            # Extract symbol from args/kwargs if specified
            symbol = None
            if symbol_param:
                # Try kwargs first
                symbol = kwargs.get(symbol_param)
                # Try positional args (skip self)
                if symbol is None and len(args) > 1:
                    # Get parameter position from function signature
                    import inspect
                    sig = inspect.signature(func)
                    params = list(sig.parameters.keys())
                    if symbol_param in params:
                        idx = params.index(symbol_param)
                        if idx < len(args):
                            symbol = args[idx]
            
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                op_name = operation or func.__name__
                logger.exception(f"Error in {op_name}: {e}")
                return format_error_response(e, symbol=symbol, operation=op_name)
        
        return wrapper
    return decorator


def sync_endpoint(
    operation: Optional[str] = None,
    symbol_param: Optional[str] = None
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """
    Decorator for synchronous endpoints with unified error handling.
    
    Same as mcp_endpoint but for non-async functions.
    """
    def decorator(func: Callable[..., str]) -> Callable[..., str]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            symbol = None
            if symbol_param:
                symbol = kwargs.get(symbol_param)
                if symbol is None and len(args) > 1:
                    import inspect
                    sig = inspect.signature(func)
                    params = list(sig.parameters.keys())
                    if symbol_param in params:
                        idx = params.index(symbol_param)
                        if idx < len(args):
                            symbol = args[idx]
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                op_name = operation or func.__name__
                logger.exception(f"Error in {op_name}: {e}")
                return format_error_response(e, symbol=symbol, operation=op_name)
        
        return wrapper
    return decorator


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def safe_format(template: str, **kwargs: Any) -> str:
    """
    Safely format a template string, replacing missing keys with 'N/A'.
    
    Args:
        template: Format string with {key} placeholders
        **kwargs: Values for placeholders
        
    Returns:
        Formatted string with missing values as 'N/A'
    """
    class SafeDict(dict):  # type: ignore[type-arg]
        def __missing__(self, key: str) -> str:
            return 'N/A'
    
    return template.format_map(SafeDict(**kwargs))


def truncate_string(s: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    Truncate a string to a maximum length.
    
    Args:
        s: String to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated
        
    Returns:
        Truncated string
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix
