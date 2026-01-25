# OptionPlay - Utils Package
# ===========================
# Common utility functions and helpers

from .rate_limiter import (
    RateLimiter,
    AdaptiveRateLimiter,
    RateLimitConfig,
    retry_with_backoff,
    get_limiter,
    get_marketdata_limiter,
    get_tradier_limiter,
    get_yahoo_limiter,
)

from .provider_orchestrator import (
    ProviderOrchestrator,
    ProviderType,
    DataType,
    ProviderConfig,
    ProviderStats,
    get_orchestrator,
    format_provider_status,
)

from .validation import (
    ValidationError,
    ValidationLimits,
    validate_symbol,
    validate_symbols,
    validate_dte,
    validate_dte_range,
    validate_delta,
    validate_right,
    validate_positive_int,
    validate_batch_size,
    validate_max_results,
    validate_min_score,
    validate_num_alternatives,
    validate_min_days,
    validate_pause_seconds,
    safe_validate_symbol,
    is_valid_symbol,
)

from .secure_config import (
    SecureConfig,
    get_secure_config,
    get_api_key,
    mask_api_key,
    mask_sensitive_data,
    reset_secure_config,
)

from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitBreakerError,
    CircuitState,
    CircuitBreakerRegistry,
    get_circuit_breaker,
    get_circuit_breaker_registry,
    reset_circuit_breakers,
)

from .error_handler import (
    ErrorCode,
    MCPError,
    DataFetchError,
    RateLimitError,
    ApiTimeoutError,
    ApiConnectionError,
    ConfigurationError,
    ProviderError,
    SymbolNotFoundError,
    NoDataError,
    format_error_response,
    mcp_endpoint,
    sync_endpoint,
    safe_format,
    truncate_string,
)

from .markdown_builder import (
    MarkdownBuilder,
    MarkdownShortcuts,
    TableAlign,
    TableColumn,
    md,
    format_price,
    format_percent,
    format_volume,
    format_date,
    truncate,
)

from .structured_logging import (
    StructuredFormatter,
    StructuredLogger,
    get_logger,
    configure_logging,
    log_context,
    log_performance,
    log_api_call,
)

__all__ = [
    # Rate Limiter
    'RateLimiter',
    'AdaptiveRateLimiter',
    'RateLimitConfig',
    'retry_with_backoff',
    'get_limiter',
    'get_marketdata_limiter',
    'get_tradier_limiter',
    'get_yahoo_limiter',
    
    # Provider Orchestrator
    'ProviderOrchestrator',
    'ProviderType',
    'DataType',
    'ProviderConfig',
    'ProviderStats',
    'get_orchestrator',
    'format_provider_status',
    
    # Validation
    'ValidationError',
    'ValidationLimits',
    'validate_symbol',
    'validate_symbols',
    'validate_dte',
    'validate_dte_range',
    'validate_delta',
    'validate_right',
    'validate_positive_int',
    'validate_batch_size',
    'validate_max_results',
    'validate_min_score',
    'validate_num_alternatives',
    'validate_min_days',
    'validate_pause_seconds',
    'safe_validate_symbol',
    'is_valid_symbol',
    
    # Secure Config
    'SecureConfig',
    'get_secure_config',
    'get_api_key',
    'mask_api_key',
    'mask_sensitive_data',
    'reset_secure_config',
    
    # Circuit Breaker
    'CircuitBreaker',
    'CircuitBreakerOpen',
    'CircuitBreakerError',
    'CircuitState',
    'CircuitBreakerRegistry',
    'get_circuit_breaker',
    'get_circuit_breaker_registry',
    'reset_circuit_breakers',
    
    # Error Handler
    'ErrorCode',
    'MCPError',
    'DataFetchError',
    'RateLimitError',
    'ApiTimeoutError',
    'ApiConnectionError',
    'ConfigurationError',
    'ProviderError',
    'SymbolNotFoundError',
    'NoDataError',
    'format_error_response',
    'mcp_endpoint',
    'sync_endpoint',
    'safe_format',
    'truncate_string',
    
    # Markdown Builder
    'MarkdownBuilder',
    'MarkdownShortcuts',
    'TableAlign',
    'TableColumn',
    'md',
    'format_price',
    'format_percent',
    'format_volume',
    'format_date',
    'truncate',

    # Structured Logging
    'StructuredFormatter',
    'StructuredLogger',
    'get_logger',
    'configure_logging',
    'log_context',
    'log_performance',
    'log_api_call',
]
