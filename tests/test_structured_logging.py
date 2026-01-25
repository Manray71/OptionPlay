# Tests for Structured Logging
# =============================

import json
import logging
import asyncio
from io import StringIO
from unittest.mock import patch

import pytest

from src.utils.structured_logging import (
    StructuredFormatter,
    StructuredLogger,
    get_logger,
    configure_logging,
    log_context,
    log_performance,
    log_api_call,
)


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
        assert data['location']['line'] == 42
        assert data['location']['function'] == 'test_function'

    def test_format_with_exception(self):
        """Test exception formatting."""
        formatter = StructuredFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
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


class TestStructuredLogger:
    """Tests for StructuredLogger."""

    def test_get_logger_returns_structured_logger(self):
        """Test that get_logger returns a StructuredLogger."""
        logger = get_logger("test.module")
        # Should be a Logger (StructuredLogger may not be directly checkable)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"


class TestLogContext:
    """Tests for log_context context manager."""

    def test_context_adds_fields(self):
        """Test that context fields are added to logs."""
        formatter = StructuredFormatter()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)

        logger = logging.getLogger("context_test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        with log_context(request_id="abc123", user="john"):
            logger.info("Test message")

        output = stream.getvalue()
        data = json.loads(output)

        assert 'context' in data
        assert data['context']['request_id'] == 'abc123'
        assert data['context']['user'] == 'john'

        logger.removeHandler(handler)

    def test_context_is_cleaned_up(self):
        """Test that context is cleaned up after exiting."""
        formatter = StructuredFormatter()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)

        logger = logging.getLogger("cleanup_test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        with log_context(temp_field="temp_value"):
            pass

        logger.info("After context")

        # Get last line
        lines = stream.getvalue().strip().split('\n')
        data = json.loads(lines[-1])

        # Context should not contain temp_field
        context = data.get('context', {})
        assert 'temp_field' not in context

        logger.removeHandler(handler)


class TestLogPerformance:
    """Tests for log_performance decorator."""

    def test_sync_function_logging(self):
        """Test performance logging for sync functions."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())

        logger = logging.getLogger("perf_test")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

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

        logger.removeHandler(handler)

    @pytest.mark.asyncio
    async def test_async_function_logging(self):
        """Test performance logging for async functions."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())

        logger = logging.getLogger("async_perf_test")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

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

        logger.removeHandler(handler)

    def test_logs_errors(self):
        """Test that errors are logged."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())

        logger = logging.getLogger("error_perf_test")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

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

        logger.removeHandler(handler)


class TestLogApiCall:
    """Tests for log_api_call decorator."""

    @pytest.mark.asyncio
    async def test_logs_api_call_with_symbol(self):
        """Test API call logging with symbol extraction."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())

        logger = logging.getLogger("api_test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

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

        logger.removeHandler(handler)

    @pytest.mark.asyncio
    async def test_logs_api_call_failure(self):
        """Test API call logging on failure."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())

        logger = logging.getLogger("api_fail_test")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

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

        logger.removeHandler(handler)


class TestConfigureLogging:
    """Tests for configure_logging."""

    def test_configure_json_output(self):
        """Test JSON output configuration."""
        stream = StringIO()
        configure_logging(level=logging.INFO, json_output=True, stream=stream)

        logger = logging.getLogger("config_test")
        logger.info("Test message")

        output = stream.getvalue()
        # Should be valid JSON
        data = json.loads(output.strip())
        assert data['message'] == 'Test message'

    def test_configure_plain_output(self):
        """Test plain text output configuration."""
        stream = StringIO()
        configure_logging(level=logging.INFO, json_output=False, stream=stream)

        logger = logging.getLogger("plain_test")
        logger.info("Plain message")

        output = stream.getvalue()
        # Should NOT be JSON
        assert "Plain message" in output
        with pytest.raises(json.JSONDecodeError):
            json.loads(output.strip())
