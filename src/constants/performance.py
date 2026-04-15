# OptionPlay - Performance & System Constants
# ============================================
# Cache settings, timeouts, and system parameters.

from dataclasses import dataclass

# =============================================================================
# CACHE SETTINGS
# =============================================================================

# Cache Time-to-Live (seconds)
CACHE_TTL_SECONDS = 900  # 15 minutes for historical data
CACHE_TTL_INTRADAY = 300  # 5 minutes for intraday data
CACHE_TTL_VIX = 300  # 5 minutes for VIX
CACHE_TTL_EARNINGS = 86400  # 24 hours for earnings
CACHE_TTL_FUNDAMENTALS = 3600  # 1 hour for fundamentals

# Cache Size Limits
CACHE_MAX_ENTRIES = 500  # Max entries in LRU cache
CACHE_MAX_MEMORY_MB = 100  # Max memory (approximate)


# =============================================================================
# REQUEST SETTINGS
# =============================================================================

# Timeouts (seconds)
REQUEST_TIMEOUT = 30  # Standard request timeout
REQUEST_TIMEOUT_LONG = 60  # For slow endpoints
YAHOO_TIMEOUT = 10  # Yahoo Finance timeout (often slow)

# Concurrency
MAX_CONCURRENT_REQUESTS = 10  # Max parallel requests
MAX_CONCURRENT_SCANS = 5  # Max parallel symbol scans

# Rate Limiting
BATCH_DELAY = 1.0  # Delay between batches (seconds)
RATE_LIMIT_PER_MINUTE = 100  # Max requests per minute


# =============================================================================
# RETRY SETTINGS
# =============================================================================

MAX_RETRIES = 3  # Max retry attempts on error
RETRY_BASE_DELAY = 2  # Base delay (exponentially increased)
RETRY_MAX_DELAY = 30  # Maximum delay


# =============================================================================
# DATA REQUIREMENTS
# =============================================================================

# Minimum data points for analysis
MIN_DATA_POINTS = 60  # Minimum for technical analysis
MIN_DATA_POINTS_EXTENDED = 200  # For SMA200 calculation

# Historical Data
HISTORICAL_DAYS = 260  # ~1 year trading days
HISTORICAL_DAYS_EXTENDED = 520  # ~2 years


# =============================================================================
# NUMERICAL PRECISION
# =============================================================================

# Price Tolerance for comparisons
PRICE_TOLERANCE = 0.0001  # For float comparisons

# Rounding
SCORE_DECIMAL_PLACES = 1  # Scores to 1 decimal place
PRICE_DECIMAL_PLACES = 2  # Prices to 2 decimal places
PERCENTAGE_DECIMAL_PLACES = 2  # Percentages to 2 decimal places


# =============================================================================
# OUTPUT LIMITS
# =============================================================================

# Scan Results
MAX_RESULTS_PER_SYMBOL = 3  # Max signals per symbol
MAX_TOTAL_RESULTS = 50  # Max total signals
MAX_SYMBOL_APPEARANCES = 2  # Max appearances of a symbol

# Report Generation
MAX_SYMBOLS_IN_REPORT = 20  # Max symbols in PDF report
MAX_CANDIDATES_PER_STRATEGY = 10  # Max candidates per strategy


# =============================================================================
# LOGGING & DEBUGGING
# =============================================================================

# Log Rotation
LOG_MAX_SIZE_MB = 10  # Max log file size
LOG_BACKUP_COUNT = 5  # Number of backup logs

# Debug Settings
DEBUG_SHOW_TIMINGS = False  # Show execution times
DEBUG_VERBOSE_ERRORS = True  # Detailed error messages


# =============================================================================
# CONVENIENCE CLASS
# =============================================================================


@dataclass(frozen=True)
class Performance:
    """
    Grouped performance constants.

    Usage:
        from src.constants import Performance as P
        timeout = P.REQUEST_TIMEOUT
    """

    # Cache
    CACHE_TTL: int = CACHE_TTL_SECONDS
    CACHE_TTL_VIX: int = CACHE_TTL_VIX
    CACHE_MAX_ENTRIES: int = CACHE_MAX_ENTRIES

    # Requests
    TIMEOUT: int = REQUEST_TIMEOUT
    MAX_CONCURRENT: int = MAX_CONCURRENT_REQUESTS
    MAX_RETRIES: int = MAX_RETRIES

    # Data
    MIN_DATA_POINTS: int = MIN_DATA_POINTS
    HISTORICAL_DAYS: int = HISTORICAL_DAYS

    # Output
    MAX_RESULTS: int = MAX_TOTAL_RESULTS
