# OptionPlay - Structured Logging
# ================================
# JSON-based structured logging for better observability.
#
# Features:
# - JSON output format for log aggregation tools
# - Contextual logging with extra fields
# - Performance timing decorators
# - Sensitive data masking
#
# Usage:
#     from .structured_logging import get_logger, log_context
#
#     logger = get_logger(__name__)
#     logger.info("Processing request", symbol="AAPL", action="quote")
#
#     with log_context(request_id="123"):
#         logger.info("Inside context")

from __future__ import annotations

import json
import logging
import sys
import time
import functools
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Optional, TypeVar
from threading import local

# Thread-local storage for context
_context = local()


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Outputs logs as JSON objects with standard fields:
    - timestamp: ISO 8601 format
    - level: Log level name
    - logger: Logger name
    - message: Log message
    - (extra fields from context or log call)
    """

    SENSITIVE_KEYS = frozenset({
        'password', 'api_key', 'apikey', 'token', 'secret',
        'authorization', 'auth', 'credential', 'credentials'
    })

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Base fields
        log_dict: Dict[str, Any] = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # Add location info for errors
        if record.levelno >= logging.ERROR:
            log_dict['location'] = {
                'file': record.pathname,
                'line': record.lineno,
                'function': record.funcName,
            }

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_dict['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
            }

        # Add thread-local context
        context = getattr(_context, 'data', {})
        if context:
            log_dict['context'] = context.copy()

        # Add extra fields from record (excluding standard attributes)
        standard_attrs = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName',
            'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'pathname', 'process', 'processName', 'relativeCreated',
            'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
            'taskName', 'message',
        }

        extras = {
            k: self._mask_sensitive(k, v)
            for k, v in record.__dict__.items()
            if k not in standard_attrs and not k.startswith('_')
        }

        if extras:
            log_dict['extra'] = extras

        return json.dumps(log_dict, default=str)

    def _mask_sensitive(self, key: str, value: Any) -> Any:
        """Mask sensitive values."""
        if key.lower() in self.SENSITIVE_KEYS:
            if isinstance(value, str) and len(value) > 4:
                return value[:2] + '*' * (len(value) - 4) + value[-2:]
            return '****'
        return value


class StructuredLogger(logging.Logger):
    """
    Logger with structured logging support.

    Allows passing extra fields directly to log methods:
        logger.info("message", symbol="AAPL", price=150.0)
    """

    def _log(
        self,
        level: int,
        msg: object,
        args: tuple,
        exc_info: Any = None,
        extra: Optional[Dict] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        **kwargs: Any
    ) -> None:
        """Override to support keyword arguments as extra fields."""
        if kwargs:
            extra = extra or {}
            extra.update(kwargs)
        super()._log(level, msg, args, exc_info, extra, stack_info, stacklevel + 1)


# Type variable for decorator
F = TypeVar('F', bound=Callable[..., Any])


def get_logger(name: str) -> StructuredLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        StructuredLogger instance
    """
    # Register our custom logger class
    old_class = logging.getLoggerClass()
    logging.setLoggerClass(StructuredLogger)
    logger = logging.getLogger(name)
    logging.setLoggerClass(old_class)
    return logger  # type: ignore


def configure_logging(
    level: int = logging.INFO,
    json_output: bool = True,
    stream: Any = None
) -> None:
    """
    Configure structured logging for the application.

    Args:
        level: Logging level (default: INFO)
        json_output: Use JSON formatter (default: True)
        stream: Output stream (default: stderr)
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Add new handler
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(level)

    if json_output:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))

    root.addHandler(handler)


@contextmanager
def log_context(**kwargs: Any):
    """
    Context manager to add fields to all logs within the context.

    Example:
        with log_context(request_id="abc123", user="john"):
            logger.info("Processing")  # includes request_id and user
    """
    if not hasattr(_context, 'data'):
        _context.data = {}

    old_data = _context.data.copy()
    _context.data.update(kwargs)
    try:
        yield
    finally:
        _context.data = old_data


def log_performance(logger: Optional[logging.Logger] = None):
    """
    Decorator to log function performance.

    Example:
        @log_performance()
        async def fetch_data():
            ...
    """
    def decorator(func: F) -> F:
        nonlocal logger
        if logger is None:
            logger = get_logger(func.__module__)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                logger.debug(
                    f"{func.__name__} completed",
                    extra={
                        'function': func.__name__,
                        'duration_ms': round(elapsed, 2),
                        'status': 'success'
                    }
                )
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(
                    f"{func.__name__} failed",
                    extra={
                        'function': func.__name__,
                        'duration_ms': round(elapsed, 2),
                        'status': 'error',
                        'error': str(e)
                    }
                )
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                logger.debug(
                    f"{func.__name__} completed",
                    extra={
                        'function': func.__name__,
                        'duration_ms': round(elapsed, 2),
                        'status': 'success'
                    }
                )
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(
                    f"{func.__name__} failed",
                    extra={
                        'function': func.__name__,
                        'duration_ms': round(elapsed, 2),
                        'status': 'error',
                        'error': str(e)
                    }
                )
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def log_api_call(
    logger: Optional[logging.Logger] = None,
    include_args: bool = False
):
    """
    Decorator to log API calls with timing and status.

    Example:
        @log_api_call()
        async def get_quote(symbol: str):
            ...
    """
    def decorator(func: F) -> F:
        nonlocal logger
        if logger is None:
            logger = get_logger(func.__module__)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract first positional arg if it looks like a symbol
            symbol = None
            if args and isinstance(args[0], str) and len(args[0]) <= 10:
                symbol = args[0]
            elif 'symbol' in kwargs:
                symbol = kwargs['symbol']

            extra: Dict[str, Any] = {
                'api_call': func.__name__,
            }
            if symbol:
                extra['symbol'] = symbol
            if include_args:
                extra['args'] = str(args[1:]) if args else ''
                extra['kwargs'] = str(kwargs)

            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                extra['duration_ms'] = round(elapsed, 2)
                extra['status'] = 'success'
                logger.info(f"API call {func.__name__}", extra=extra)
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                extra['duration_ms'] = round(elapsed, 2)
                extra['status'] = 'error'
                extra['error_type'] = type(e).__name__
                extra['error'] = str(e)
                logger.warning(f"API call {func.__name__} failed", extra=extra)
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            extra: Dict[str, Any] = {'api_call': func.__name__}

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                extra['duration_ms'] = round(elapsed, 2)
                extra['status'] = 'success'
                logger.info(f"API call {func.__name__}", extra=extra)
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                extra['duration_ms'] = round(elapsed, 2)
                extra['status'] = 'error'
                extra['error'] = str(e)
                logger.warning(f"API call {func.__name__} failed", extra=extra)
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


# Convenience re-exports
__all__ = [
    'StructuredFormatter',
    'StructuredLogger',
    'get_logger',
    'configure_logging',
    'log_context',
    'log_performance',
    'log_api_call',
]
