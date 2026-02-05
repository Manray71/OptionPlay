# Tests for Structured Logging
# =============================

import json
import logging
import asyncio
import sys
from io import StringIO
from unittest.mock import patch, MagicMock
from datetime import datetime

import pytest

from src.utils.structured_logging import (
    StructuredFormatter,
    StructuredLogger,
    get_logger,
    configure_logging,
    log_context,
    log_performance,
    log_api_call,
    _context,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def clean_logging():
    """Clean up logging state before and after tests."""
    # Store original state
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    # Clean context
    if hasattr(_context, 'data'):
        delattr(_context, 'data')

    yield

    # Restore original state
    root.handlers = original_handlers
    root.setLevel(original_level)

    # Clean context again
    if hasattr(_context, 'data'):
        delattr(_context, 'data')


@pytest.fixture
def json_stream_handler():
    """Create a stream handler with JSON formatter."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())
    handler.setLevel(logging.DEBUG)
    return handler, stream


@pytest.fixture
def test_logger(json_stream_handler):
    """Create a test logger with JSON output."""
    handler, stream = json_stream_handler
    logger = logging.getLogger(f"test_{id(stream)}")
    logger.handlers = []
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield logger, stream
    logger.removeHandler(handler)


# =============================================================================
# STRUCTURED FORMATTER TESTS
# =============================================================================

class TestStructuredFormatter:
    """Tests for StructuredFormatter."""

    def test_format_basic_message(self):
        """Test basic message formatting."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data['level'] == 'INFO'
        assert data['logger'] == 'test'
        assert data['message'] == 'Test message'
        assert 'timestamp' in data
        assert data['timestamp'].endswith('Z')

    def test_format_message_with_args(self):
        """Test message formatting with string interpolation args."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Value is %s and count is %d",
            args=("hello", 42),
            exc_info=None
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data['message'] == 'Value is hello and count is 42'

    def test_format_error_includes_location(self):
        """Test that errors include location info."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Error occurred",
            args=(),
            exc_info=None
        )
        record.funcName = "test_function"

        output = formatter.format(record)
        data = json.loads(output)

        assert 'location' in data
        assert data['location']['file'] == '/path/to/test.py'
        assert data['location']['line'] == 42
        assert data['location']['function'] == 'test_function'

    def test_format_warning_no_location(self):
        """Test that warnings do not include location info."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="/path/to/test.py",
            lineno=42,
            msg="Warning message",
            args=(),
            exc_info=None
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert 'location' not in data

    def test_format_critical_includes_location(self):
        """Test that CRITICAL level includes location info."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.CRITICAL,
            pathname="/path/to/test.py",
            lineno=100,
            msg="Critical error",
            args=(),
            exc_info=None
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert 'location' in data
        assert data['location']['line'] == 100

    def test_format_with_exception(self):
        """Test exception formatting."""
        formatter = StructuredFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error",
            args=(),
            exc_info=exc_info
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert 'exception' in data
        assert data['exception']['type'] == 'ValueError'
        assert data['exception']['message'] == 'Test error'

    def test_format_with_none_exception(self):
        """Test formatting when exc_info is (None, None, None)."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error without exception",
            args=(),
            exc_info=(None, None, None)
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert 'exception' not in data

    def test_masks_sensitive_data(self):
        """Test that sensitive fields are masked."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )
        record.api_key = "super_secret_key_12345"
        record.password = "my_password"
        record.normal_field = "visible"

        output = formatter.format(record)
        data = json.loads(output)

        # Sensitive fields should be masked
        assert data['extra']['api_key'] != "super_secret_key_12345"
        assert '*' in data['extra']['api_key']
        assert '*' in data['extra']['password']

        # Normal fields should be visible
        assert data['extra']['normal_field'] == 'visible'

    def test_masks_all_sensitive_keys(self):
        """Test that all sensitive key variants are masked."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )

        # Set all sensitive key variants
        record.password = "secret123456"
        record.api_key = "key123456789"
        record.apikey = "apikey123456"
        record.token = "token123456789"
        record.secret = "secret123456"
        record.authorization = "auth123456789"
        record.auth = "authvalue123"
        record.credential = "cred123456789"
        record.credentials = "creds12345678"

        output = formatter.format(record)
        data = json.loads(output)

        # All sensitive fields should be masked
        for key in ['password', 'api_key', 'apikey', 'token', 'secret',
                    'authorization', 'auth', 'credential', 'credentials']:
            assert '*' in data['extra'][key], f"Key '{key}' should be masked"

    def test_masks_case_insensitive(self):
        """Test that masking is case insensitive."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )
        record.PASSWORD = "secret12345"
        record.API_KEY = "key12345678"

        output = formatter.format(record)
        data = json.loads(output)

        assert '*' in data['extra']['PASSWORD']
        assert '*' in data['extra']['API_KEY']

    def test_masks_short_sensitive_values(self):
        """Test masking of short sensitive values."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )
        record.password = "abc"  # Short value
        record.token = "ab"  # Very short value

        output = formatter.format(record)
        data = json.loads(output)

        # Short values should be fully masked
        assert data['extra']['password'] == '****'
        assert data['extra']['token'] == '****'

    def test_format_extra_fields(self):
        """Test that extra fields are included."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )
        record.symbol = "AAPL"
        record.price = 150.50
        record.count = 100

        output = formatter.format(record)
        data = json.loads(output)

        assert 'extra' in data
        assert data['extra']['symbol'] == 'AAPL'
        assert data['extra']['price'] == 150.50
        assert data['extra']['count'] == 100

    def test_format_excludes_standard_attributes(self):
        """Test that standard LogRecord attributes are not in extra."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )

        output = formatter.format(record)
        data = json.loads(output)

        # Standard attributes should not appear in extra
        extra = data.get('extra', {})
        assert 'name' not in extra
        assert 'levelname' not in extra
        assert 'pathname' not in extra
        assert 'lineno' not in extra

    def test_format_excludes_private_attributes(self):
        """Test that private attributes (starting with _) are excluded."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )
        record._private_field = "should not appear"
        record.public_field = "should appear"

        output = formatter.format(record)
        data = json.loads(output)

        assert '_private_field' not in data.get('extra', {})
        assert data['extra']['public_field'] == 'should appear'

    def test_format_with_non_serializable_value(self):
        """Test handling of non-JSON-serializable values."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )
        record.complex_obj = {'date': datetime(2024, 1, 15, 10, 30, 0)}

        output = formatter.format(record)
        # Should not raise - uses default=str
        data = json.loads(output)
        assert 'extra' in data

    def test_timestamp_format(self):
        """Test that timestamp is in ISO 8601 format with Z suffix."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None
        )

        output = formatter.format(record)
        data = json.loads(output)

        timestamp = data['timestamp']
        assert timestamp.endswith('Z')
        # Should be parseable as ISO format
        datetime.fromisoformat(timestamp.rstrip('Z'))


# =============================================================================
# STRUCTURED LOGGER TESTS
# =============================================================================

class TestStructuredLogger:
    """Tests for StructuredLogger."""

    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a Logger instance."""
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"

    def test_get_logger_preserves_logger_class(self):
        """Test that get_logger restores original logger class."""
        original_class = logging.getLoggerClass()
        get_logger("test.preserve")
        assert logging.getLoggerClass() == original_class

    def test_structured_logger_accepts_kwargs(self, test_logger):
        """Test that StructuredLogger accepts keyword arguments."""
        logger, stream = test_logger

        # Create a StructuredLogger manually
        logging.setLoggerClass(StructuredLogger)
        struct_logger = logging.getLogger(f"struct_test_{id(stream)}")
        logging.setLoggerClass(logging.Logger)

        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())
        struct_logger.addHandler(handler)
        struct_logger.setLevel(logging.INFO)
        struct_logger.propagate = False

        struct_logger.info("Test message", symbol="AAPL", price=150.0)

        output = stream.getvalue()
        data = json.loads(output)

        assert data['extra']['symbol'] == 'AAPL'
        assert data['extra']['price'] == 150.0

    def test_get_logger_same_name_returns_same_logger(self):
        """Test that getting a logger with the same name returns the same instance."""
        logger1 = get_logger("same.name")
        logger2 = get_logger("same.name")
        assert logger1 is logger2

    def test_get_logger_different_names_different_loggers(self):
        """Test that different names return different loggers."""
        logger1 = get_logger("name.one")
        logger2 = get_logger("name.two")
        assert logger1 is not logger2


# =============================================================================
# LOG CONTEXT TESTS
# =============================================================================

class TestLogContext:
    """Tests for log_context context manager."""

    def test_context_adds_fields(self, test_logger, clean_logging):
        """Test that context fields are added to logs."""
        logger, stream = test_logger

        with log_context(request_id="abc123", user="john"):
            logger.info("Test message")

        output = stream.getvalue()
        data = json.loads(output)

        assert 'context' in data
        assert data['context']['request_id'] == 'abc123'
        assert data['context']['user'] == 'john'

    def test_context_is_cleaned_up(self, test_logger, clean_logging):
        """Test that context is cleaned up after exiting."""
        logger, stream = test_logger

        with log_context(temp_field="temp_value"):
            pass

        logger.info("After context")

        output = stream.getvalue()
        data = json.loads(output)

        # Context should not contain temp_field
        context = data.get('context', {})
        assert 'temp_field' not in context

    def test_nested_context(self, test_logger, clean_logging):
        """Test nested context managers."""
        logger, stream = test_logger

        with log_context(outer="value1"):
            with log_context(inner="value2"):
                logger.info("Nested message")

        lines = stream.getvalue().strip().split('\n')
        data = json.loads(lines[-1])

        assert data['context']['outer'] == 'value1'
        assert data['context']['inner'] == 'value2'

    def test_nested_context_cleanup(self, test_logger, clean_logging):
        """Test that nested context restores outer context."""
        logger, stream = test_logger

        with log_context(outer="value1"):
            with log_context(inner="value2"):
                pass
            logger.info("After inner context")

        lines = stream.getvalue().strip().split('\n')
        data = json.loads(lines[-1])

        assert data['context']['outer'] == 'value1'
        assert 'inner' not in data['context']

    def test_context_overwrites_same_key(self, test_logger, clean_logging):
        """Test that inner context can overwrite outer context keys."""
        logger, stream = test_logger

        with log_context(key="outer_value"):
            with log_context(key="inner_value"):
                logger.info("Message")

        output = stream.getvalue()
        data = json.loads(output)

        assert data['context']['key'] == 'inner_value'

    def test_context_initializes_data(self, clean_logging):
        """Test that context initializes _context.data if not present."""
        # Ensure data is not present
        if hasattr(_context, 'data'):
            delattr(_context, 'data')

        with log_context(new_field="value"):
            assert hasattr(_context, 'data')
            assert _context.data['new_field'] == 'value'

    def test_context_exception_cleanup(self, test_logger, clean_logging):
        """Test that context is cleaned up even on exception."""
        logger, stream = test_logger

        try:
            with log_context(error_context="value"):
                raise ValueError("Test error")
        except ValueError:
            pass

        logger.info("After exception")

        output = stream.getvalue()
        data = json.loads(output)

        assert 'error_context' not in data.get('context', {})

    def test_context_empty_after_all_exits(self, clean_logging):
        """Test that context is empty after all context managers exit."""
        with log_context(a="1"):
            with log_context(b="2"):
                pass

        # Context should be empty
        context = getattr(_context, 'data', {})
        assert context == {}


# =============================================================================
# LOG PERFORMANCE DECORATOR TESTS
# =============================================================================

class TestLogPerformance:
    """Tests for log_performance decorator."""

    def test_sync_function_logging(self, test_logger):
        """Test performance logging for sync functions."""
        logger, stream = test_logger

        @log_performance(logger)
        def sample_function():
            return "result"

        result = sample_function()

        assert result == "result"
        output = stream.getvalue()
        data = json.loads(output)

        assert data['extra']['function'] == 'sample_function'
        assert data['extra']['status'] == 'success'
        assert 'duration_ms' in data['extra']
        assert isinstance(data['extra']['duration_ms'], (int, float))

    @pytest.mark.asyncio
    async def test_async_function_logging(self, test_logger):
        """Test performance logging for async functions."""
        logger, stream = test_logger

        @log_performance(logger)
        async def async_sample():
            await asyncio.sleep(0.01)
            return "async_result"

        result = await async_sample()

        assert result == "async_result"
        output = stream.getvalue()
        data = json.loads(output)

        assert data['extra']['function'] == 'async_sample'
        assert data['extra']['status'] == 'success'
        assert data['extra']['duration_ms'] >= 10  # At least 10ms

    def test_logs_errors(self, test_logger):
        """Test that errors are logged."""
        logger, stream = test_logger

        @log_performance(logger)
        def failing_function():
            raise ValueError("Expected error")

        with pytest.raises(ValueError):
            failing_function()

        output = stream.getvalue()
        data = json.loads(output)

        assert data['level'] == 'ERROR'
        assert data['extra']['status'] == 'error'
        assert 'Expected error' in data['extra']['error']

    @pytest.mark.asyncio
    async def test_async_logs_errors(self, test_logger):
        """Test that async errors are logged."""
        logger, stream = test_logger

        @log_performance(logger)
        async def async_failing():
            raise RuntimeError("Async error")

        with pytest.raises(RuntimeError):
            await async_failing()

        output = stream.getvalue()
        data = json.loads(output)

        assert data['level'] == 'ERROR'
        assert data['extra']['status'] == 'error'
        assert 'Async error' in data['extra']['error']

    def test_preserves_function_metadata(self, test_logger):
        """Test that decorator preserves function metadata."""
        logger, stream = test_logger

        @log_performance(logger)
        def documented_function():
            """This is a docstring."""
            return 42

        assert documented_function.__name__ == 'documented_function'
        assert documented_function.__doc__ == 'This is a docstring.'

    def test_without_logger_uses_module_logger(self):
        """Test that decorator creates logger from function module if not provided."""
        @log_performance()
        def module_function():
            return "result"

        # Should not raise
        result = module_function()
        assert result == "result"

    def test_duration_accuracy(self, test_logger):
        """Test that duration measurement is reasonably accurate."""
        logger, stream = test_logger
        import time

        @log_performance(logger)
        def timed_function():
            time.sleep(0.05)  # 50ms
            return "done"

        result = timed_function()

        output = stream.getvalue()
        data = json.loads(output)

        # Should be around 50ms (allow some tolerance)
        assert 45 <= data['extra']['duration_ms'] <= 100


# =============================================================================
# LOG API CALL DECORATOR TESTS
# =============================================================================

class TestLogApiCall:
    """Tests for log_api_call decorator."""

    @pytest.mark.asyncio
    async def test_logs_api_call_with_symbol(self, test_logger):
        """Test API call logging with symbol extraction."""
        logger, stream = test_logger

        @log_api_call(logger)
        async def get_quote(symbol: str):
            return {"price": 150.0}

        result = await get_quote("AAPL")

        assert result == {"price": 150.0}
        output = stream.getvalue()
        data = json.loads(output)

        assert data['extra']['api_call'] == 'get_quote'
        assert data['extra']['symbol'] == 'AAPL'
        assert data['extra']['status'] == 'success'

    @pytest.mark.asyncio
    async def test_logs_api_call_with_symbol_kwarg(self, test_logger):
        """Test API call logging with symbol as keyword argument."""
        logger, stream = test_logger

        @log_api_call(logger)
        async def get_quote(**kwargs):
            return {"price": 150.0}

        result = await get_quote(symbol="MSFT")

        output = stream.getvalue()
        data = json.loads(output)

        assert data['extra']['symbol'] == 'MSFT'

    @pytest.mark.asyncio
    async def test_logs_api_call_failure(self, test_logger):
        """Test API call logging on failure."""
        logger, stream = test_logger

        @log_api_call(logger)
        async def failing_api():
            raise ConnectionError("API unavailable")

        with pytest.raises(ConnectionError):
            await failing_api()

        output = stream.getvalue()
        data = json.loads(output)

        assert data['level'] == 'WARNING'
        assert data['extra']['status'] == 'error'
        assert data['extra']['error_type'] == 'ConnectionError'

    def test_sync_api_call_success(self, test_logger):
        """Test sync API call logging."""
        logger, stream = test_logger

        @log_api_call(logger)
        def sync_api():
            return {"data": "result"}

        result = sync_api()

        assert result == {"data": "result"}
        output = stream.getvalue()
        data = json.loads(output)

        assert data['extra']['api_call'] == 'sync_api'
        assert data['extra']['status'] == 'success'
        assert 'duration_ms' in data['extra']

    def test_sync_api_call_failure(self, test_logger):
        """Test sync API call logging on failure."""
        logger, stream = test_logger

        @log_api_call(logger)
        def sync_failing_api():
            raise TimeoutError("Timed out")

        with pytest.raises(TimeoutError):
            sync_failing_api()

        output = stream.getvalue()
        data = json.loads(output)

        assert data['extra']['status'] == 'error'
        assert 'Timed out' in data['extra']['error']

    @pytest.mark.asyncio
    async def test_include_args_raises_due_to_reserved_key(self, test_logger):
        """Test that include_args=True raises KeyError due to 'args' being reserved.

        Note: This is a known limitation in the current implementation.
        The log_api_call decorator uses 'args' as an extra key which conflicts
        with the reserved 'args' attribute on LogRecord.
        """
        logger, stream = test_logger

        @log_api_call(logger, include_args=True)
        async def api_with_args(symbol: str, count: int):
            return {"symbol": symbol, "count": count}

        # This should raise KeyError because 'args' is a reserved LogRecord attribute
        with pytest.raises(KeyError, match="Attempt to overwrite 'args' in LogRecord"):
            await api_with_args("AAPL", count=10)

    @pytest.mark.asyncio
    async def test_ignores_long_first_arg(self, test_logger):
        """Test that long first arg is not extracted as symbol."""
        logger, stream = test_logger

        @log_api_call(logger)
        async def api_with_long_arg(query: str):
            return {"query": query}

        await api_with_long_arg("this is a very long query string")

        output = stream.getvalue()
        data = json.loads(output)

        # Should not have symbol since first arg is > 10 chars
        assert 'symbol' not in data['extra']

    def test_without_logger_uses_module_logger(self):
        """Test that decorator creates logger from function module if not provided."""
        @log_api_call()
        def api_without_logger():
            return "result"

        # Should not raise
        result = api_without_logger()
        assert result == "result"

    @pytest.mark.asyncio
    async def test_async_no_symbol(self, test_logger):
        """Test async API call without symbol."""
        logger, stream = test_logger

        @log_api_call(logger)
        async def api_no_symbol():
            return {"status": "ok"}

        await api_no_symbol()

        output = stream.getvalue()
        data = json.loads(output)

        assert 'symbol' not in data['extra']
        assert data['extra']['status'] == 'success'


# =============================================================================
# CONFIGURE LOGGING TESTS
# =============================================================================

class TestConfigureLogging:
    """Tests for configure_logging."""

    def test_configure_json_output(self, clean_logging):
        """Test JSON output configuration."""
        stream = StringIO()
        configure_logging(level=logging.INFO, json_output=True, stream=stream)

        logger = logging.getLogger("config_json_test")
        logger.info("Test message")

        output = stream.getvalue()
        # Should be valid JSON
        data = json.loads(output.strip())
        assert data['message'] == 'Test message'

    def test_configure_plain_output(self, clean_logging):
        """Test plain text output configuration."""
        stream = StringIO()
        configure_logging(level=logging.INFO, json_output=False, stream=stream)

        logger = logging.getLogger("config_plain_test")
        logger.info("Plain message")

        output = stream.getvalue()
        # Should NOT be JSON
        assert "Plain message" in output
        with pytest.raises(json.JSONDecodeError):
            json.loads(output.strip())

    def test_configure_removes_existing_handlers(self, clean_logging):
        """Test that configure_logging removes existing handlers."""
        root = logging.getLogger()

        # Add a handler
        dummy_handler = logging.StreamHandler(StringIO())
        root.addHandler(dummy_handler)
        initial_count = len(root.handlers)

        stream = StringIO()
        configure_logging(level=logging.INFO, stream=stream)

        # Should have exactly one handler (the new one)
        assert len(root.handlers) == 1

    def test_configure_sets_level(self, clean_logging):
        """Test that configure_logging sets the log level."""
        stream = StringIO()
        configure_logging(level=logging.WARNING, json_output=True, stream=stream)

        root = logging.getLogger()
        assert root.level == logging.WARNING

        logger = logging.getLogger("level_test")
        logger.info("Should not appear")
        logger.warning("Should appear")

        output = stream.getvalue()
        assert "Should not appear" not in output
        assert "Should appear" in output

    def test_configure_default_stream_stderr(self, clean_logging):
        """Test that default stream is stderr."""
        with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
            configure_logging(level=logging.INFO, json_output=True)

            logger = logging.getLogger("stderr_test")
            logger.info("Test message")

            output = mock_stderr.getvalue()
            assert "Test message" in output

    def test_configure_debug_level(self, clean_logging):
        """Test DEBUG level configuration."""
        stream = StringIO()
        configure_logging(level=logging.DEBUG, json_output=True, stream=stream)

        logger = logging.getLogger("debug_test")
        logger.debug("Debug message")

        output = stream.getvalue()
        data = json.loads(output.strip())
        assert data['level'] == 'DEBUG'
        assert data['message'] == 'Debug message'


# =============================================================================
# LOG LEVEL TESTS
# =============================================================================

class TestLogLevels:
    """Tests for all log levels."""

    def test_all_levels(self, test_logger):
        """Test that all log levels work correctly."""
        logger, stream = test_logger

        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")

        lines = stream.getvalue().strip().split('\n')
        assert len(lines) == 5

        levels = []
        for line in lines:
            data = json.loads(line)
            levels.append(data['level'])

        assert levels == ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

    def test_level_filtering(self, clean_logging):
        """Test that log level filtering works."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())
        handler.setLevel(logging.WARNING)

        logger = logging.getLogger("filter_test")
        logger.handlers = []
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        logger.debug("Debug - filtered")
        logger.info("Info - filtered")
        logger.warning("Warning - shown")
        logger.error("Error - shown")

        lines = stream.getvalue().strip().split('\n')
        assert len(lines) == 2

        levels = [json.loads(line)['level'] for line in lines]
        assert 'DEBUG' not in levels
        assert 'INFO' not in levels
        assert 'WARNING' in levels
        assert 'ERROR' in levels


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests combining multiple features."""

    @pytest.mark.asyncio
    async def test_context_with_decorator(self, test_logger, clean_logging):
        """Test log_context combined with log_api_call decorator."""
        logger, stream = test_logger

        @log_api_call(logger)
        async def api_function(symbol: str):
            return {"price": 100.0}

        with log_context(request_id="req-123"):
            await api_function("AAPL")

        output = stream.getvalue()
        data = json.loads(output)

        assert data['context']['request_id'] == 'req-123'
        assert data['extra']['symbol'] == 'AAPL'

    def test_multiple_extra_fields(self, test_logger):
        """Test logging with multiple extra fields."""
        logger, stream = test_logger

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Complex message",
            args=(),
            exc_info=None
        )
        record.symbol = "AAPL"
        record.price = 150.50
        record.volume = 1000000
        record.tags = ["tech", "large-cap"]

        handler, _ = list(zip(logger.handlers, [stream]))[0]
        handler.emit(record)

        output = stream.getvalue()
        data = json.loads(output)

        assert data['extra']['symbol'] == 'AAPL'
        assert data['extra']['price'] == 150.50
        assert data['extra']['volume'] == 1000000
        assert data['extra']['tags'] == ["tech", "large-cap"]

    def test_error_with_context_and_exception(self, test_logger, clean_logging):
        """Test error logging with context and exception."""
        logger, stream = test_logger

        with log_context(operation="data_fetch"):
            try:
                raise ValueError("Data not found")
            except ValueError:
                logger.exception("Failed to fetch data")

        output = stream.getvalue()
        data = json.loads(output)

        assert data['level'] == 'ERROR'
        assert data['context']['operation'] == 'data_fetch'
        assert 'exception' in data
        assert data['exception']['type'] == 'ValueError'
        assert 'location' in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
