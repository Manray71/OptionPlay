# OptionPlay - Input Validation
# ==============================
# Zentrale Validierungsfunktionen für alle Inputs
#
# Verwendung:
#     from utils.validation import validate_symbol, validate_symbols
#
#     symbol = validate_symbol("AAPL")  # Returns "AAPL"
#     symbol = validate_symbol("aapl")  # Returns "AAPL"
#     symbol = validate_symbol("invalid!!!")  # Raises ValueError

import logging
import re
from typing import List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# =============================================================================
# SYMBOL VALIDATION
# =============================================================================

# Gültige US-Ticker Formate:
# - 1-5 Buchstaben: AAPL, MSFT, A, GOOGL
# - Mit Punkt für Klassen: BRK.A, BRK.B
# - Mit Bindestrich (selten): Einige ETFs
SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

# Erweitert für internationale/spezielle Symbole
SYMBOL_PATTERN_EXTENDED = re.compile(r"^[A-Z]{1,6}([.\-][A-Z]{1,2})?$")

# Bekannte Index-Symbole (ohne Prefix)
INDEX_SYMBOLS = {"VIX", "SPX", "NDX", "DJI", "RUT"}

# ETF-Symbole (haben keine Earnings)
# Beinhaltet: Index-ETFs (SPY, QQQ) und alle 11 Sektor-SPDRs
ETF_SYMBOLS = {
    # Index-ETFs
    "SPY",  # S&P 500 ETF
    "QQQ",  # Nasdaq 100 ETF
    "IWM",  # Russell 2000 ETF
    "DIA",  # Dow Jones ETF
    # Sektor-SPDRs (11 GICS-Sektoren)
    "XLE",  # Energy
    "XLK",  # Technology
    "XLF",  # Financials
    "XLV",  # Health Care
    "XLI",  # Industrials
    "XLY",  # Consumer Discretionary
    "XLP",  # Consumer Staples
    "XLB",  # Materials
    "XLU",  # Utilities
    "XLRE",  # Real Estate
    "XLC",  # Communication Services
    # Themen-ETFs
    "ARKK",  # ARK Innovation ETF
    "SMH",  # VanEck Semiconductor ETF
}


class ValidationError(ValueError):
    """Spezifische Exception für Validierungsfehler"""

    pass


def validate_symbol(symbol: str, allow_index: bool = True, strict: bool = False) -> str:
    """
    Validiert und normalisiert ein Ticker-Symbol.

    Args:
        symbol: Das zu validierende Symbol
        allow_index: Erlaubt Index-Symbole (VIX, SPX, etc.)
        strict: Wenn True, nur Standard US-Ticker erlaubt

    Returns:
        Normalisiertes Symbol (uppercase, getrimmt)

    Raises:
        ValidationError: Bei ungültigem Symbol

    Examples:
        >>> validate_symbol("aapl")
        'AAPL'
        >>> validate_symbol("BRK.B")
        'BRK.B'
        >>> validate_symbol("invalid!!!")
        ValidationError: Invalid symbol format: 'invalid!!!'
    """
    if symbol is None:
        raise ValidationError("Symbol cannot be None")

    if not isinstance(symbol, str):
        raise ValidationError(f"Symbol must be string, got {type(symbol).__name__}")

    # Normalisieren
    normalized = symbol.strip().upper()

    if not normalized:
        raise ValidationError("Symbol cannot be empty")

    # Längenprüfung
    if len(normalized) > 10:
        raise ValidationError(f"Symbol too long: '{symbol}' ({len(normalized)} chars, max 10)")

    # Index-Symbole erlauben
    if allow_index and normalized in INDEX_SYMBOLS:
        return normalized

    # Pattern-Matching
    pattern = SYMBOL_PATTERN if strict else SYMBOL_PATTERN_EXTENDED

    if not pattern.match(normalized):
        raise ValidationError(
            f"Invalid symbol format: '{symbol}'. "
            f"Expected 1-5 letters, optionally with .A/.B suffix (e.g., AAPL, BRK.B)"
        )

    return normalized


def validate_symbols(
    symbols: List[str], allow_index: bool = True, strict: bool = False, skip_invalid: bool = False
) -> List[str]:
    """
    Validiert und normalisiert eine Liste von Symbolen.

    Args:
        symbols: Liste der zu validierenden Symbole
        allow_index: Erlaubt Index-Symbole
        strict: Nur Standard US-Ticker
        skip_invalid: Ungültige überspringen statt Exception

    Returns:
        Liste der validierten Symbole (dedupliziert)

    Raises:
        ValidationError: Bei ungültigem Symbol (wenn skip_invalid=False)
    """
    if not symbols:
        return []

    if not isinstance(symbols, (list, tuple)):
        raise ValidationError(f"Symbols must be list, got {type(symbols).__name__}")

    validated = []
    skipped = []

    for symbol in symbols:
        try:
            validated_symbol = validate_symbol(symbol, allow_index, strict)
            if validated_symbol not in validated:  # Deduplizieren
                validated.append(validated_symbol)
        except ValidationError as e:
            if skip_invalid:
                skipped.append(symbol)
                logger.warning(f"Skipping invalid symbol: {symbol}")
            else:
                raise

    if skipped:
        logger.info(f"Skipped {len(skipped)} invalid symbols: {skipped[:5]}...")

    return validated


# =============================================================================
# PARAMETER VALIDATION
# =============================================================================


def validate_dte(dte: Union[int, str], param_name: str = "DTE") -> int:
    """
    Validiert Days-to-Expiration Parameter.

    Args:
        dte: Tage bis Verfall
        param_name: Name für Fehlermeldung

    Returns:
        Validierter DTE-Wert

    Raises:
        ValidationError: Bei ungültigem Wert
    """
    if not isinstance(dte, int):
        try:
            dte = int(dte)
        except (ValueError, TypeError):
            raise ValidationError(f"{param_name} must be integer, got {type(dte).__name__}")

    if dte < 0:
        raise ValidationError(f"{param_name} cannot be negative: {dte}")

    if dte > 730:  # Max 2 Jahre
        raise ValidationError(f"{param_name} too large: {dte} (max 730 days)")

    return dte


def validate_dte_range(dte_min: Union[int, str], dte_max: Union[int, str]) -> Tuple[int, int]:
    """
    Validiert einen DTE-Bereich.

    Returns:
        Tuple (dte_min, dte_max) validiert

    Raises:
        ValidationError: Bei ungültigem Bereich
    """
    dte_min = validate_dte(dte_min, "dte_min")
    dte_max = validate_dte(dte_max, "dte_max")

    if dte_min > dte_max:
        raise ValidationError(f"dte_min ({dte_min}) cannot be greater than dte_max ({dte_max})")

    return dte_min, dte_max


def validate_delta(delta: Union[int, float], param_name: str = "delta") -> float:
    """
    Validiert Delta-Parameter.

    Args:
        delta: Delta-Wert (-1.0 bis 1.0)
        param_name: Name für Fehlermeldung

    Returns:
        Validierter Delta-Wert
    """
    if not isinstance(delta, (int, float)):
        raise ValidationError(f"{param_name} must be numeric, got {type(delta).__name__}")

    delta = float(delta)

    import math as _math

    if _math.isnan(delta) or _math.isinf(delta):
        raise ValidationError(f"{param_name} must be a finite number, got {delta}")

    if delta < -1.0 or delta > 1.0:
        raise ValidationError(f"{param_name} must be between -1.0 and 1.0, got {delta}")

    return delta


def validate_right(right: str) -> str:
    """
    Validiert Options-Right (Put/Call).

    Args:
        right: "P", "C", "PUT", "CALL", etc.

    Returns:
        Normalisiert: "P" oder "C"
    """
    if not isinstance(right, str):
        raise ValidationError(f"Right must be string, got {type(right).__name__}")

    right = right.strip().upper()

    if right in ("P", "PUT"):
        return "P"
    elif right in ("C", "CALL"):
        return "C"
    else:
        raise ValidationError(f"Invalid right: '{right}'. Expected 'P'/'PUT' or 'C'/'CALL'")


def validate_positive_int(
    value: Union[int, str], param_name: str, max_value: Optional[int] = None
) -> int:
    """
    Validiert positive Integer-Werte.
    """
    if not isinstance(value, int):
        try:
            value = int(value)
        except (ValueError, TypeError):
            raise ValidationError(f"{param_name} must be integer")

    if value <= 0:
        raise ValidationError(f"{param_name} must be positive, got {value}")

    if max_value and value > max_value:
        raise ValidationError(f"{param_name} too large: {value} (max {max_value})")

    return value


# =============================================================================
# MCP ENDPOINT VALIDATION
# =============================================================================


# Limits for MCP endpoint parameters
class ValidationLimits:
    """Centralized limits for input validation."""

    MAX_SYMBOLS: int = 500
    MAX_BATCH_SIZE: int = 100
    MIN_BATCH_SIZE: int = 1
    MAX_DTE: int = 365
    MIN_DTE: int = 1
    MAX_RESULTS: int = 100
    MIN_RESULTS: int = 1
    MAX_ALTERNATIVES: int = 10
    MIN_ALTERNATIVES: int = 1
    MAX_DAYS: int = 365
    MIN_DAYS: int = 1
    MAX_PAUSE_SECONDS: int = 300
    MIN_PAUSE_SECONDS: int = 1


def validate_batch_size(batch_size: Union[int, str]) -> int:
    """
    Validate batch_size parameter for bulk operations.

    Args:
        batch_size: Number of items per batch

    Returns:
        Validated batch_size

    Raises:
        ValidationError: If batch_size is out of range
    """
    limits = ValidationLimits()

    if not isinstance(batch_size, int):
        try:
            batch_size = int(batch_size)
        except (ValueError, TypeError):
            raise ValidationError(f"batch_size must be integer, got {type(batch_size).__name__}")

    if batch_size < limits.MIN_BATCH_SIZE:
        raise ValidationError(f"batch_size must be >= {limits.MIN_BATCH_SIZE}, got {batch_size}")
    if batch_size > limits.MAX_BATCH_SIZE:
        raise ValidationError(f"batch_size must be <= {limits.MAX_BATCH_SIZE}, got {batch_size}")

    return batch_size


def validate_max_results(max_results: Union[int, str]) -> int:
    """
    Validate max_results parameter for scan/query operations.

    Args:
        max_results: Maximum number of results to return

    Returns:
        Validated max_results

    Raises:
        ValidationError: If max_results is out of range
    """
    limits = ValidationLimits()

    if not isinstance(max_results, int):
        try:
            max_results = int(max_results)
        except (ValueError, TypeError):
            raise ValidationError(f"max_results must be integer, got {type(max_results).__name__}")

    if max_results < limits.MIN_RESULTS:
        raise ValidationError(f"max_results must be >= {limits.MIN_RESULTS}, got {max_results}")
    if max_results > limits.MAX_RESULTS:
        raise ValidationError(f"max_results must be <= {limits.MAX_RESULTS}, got {max_results}")

    return max_results


def validate_min_score(min_score: Union[int, float, str]) -> float:
    """
    Validate min_score parameter for filtering.

    Args:
        min_score: Minimum score threshold (0.0 - 10.0)

    Returns:
        Validated min_score

    Raises:
        ValidationError: If min_score is out of range
    """
    if not isinstance(min_score, (int, float)):
        try:
            min_score = float(min_score)
        except (ValueError, TypeError):
            raise ValidationError(f"min_score must be numeric, got {type(min_score).__name__}")

    min_score = float(min_score)

    import math as _math

    if _math.isnan(min_score) or _math.isinf(min_score):
        raise ValidationError(f"min_score must be a finite number, got {min_score}")

    if min_score < 0.0:
        raise ValidationError(f"min_score cannot be negative, got {min_score}")
    if min_score > 10.0:
        raise ValidationError(f"min_score cannot exceed 10.0, got {min_score}")

    return min_score


def validate_num_alternatives(num_alternatives: Union[int, str]) -> int:
    """
    Validate num_alternatives parameter for strike recommendations.

    Args:
        num_alternatives: Number of alternative recommendations

    Returns:
        Validated num_alternatives

    Raises:
        ValidationError: If num_alternatives is out of range
    """
    limits = ValidationLimits()

    if not isinstance(num_alternatives, int):
        try:
            num_alternatives = int(num_alternatives)
        except (ValueError, TypeError):
            raise ValidationError(
                f"num_alternatives must be integer, got {type(num_alternatives).__name__}"
            )

    if num_alternatives < limits.MIN_ALTERNATIVES:
        raise ValidationError(
            f"num_alternatives must be >= {limits.MIN_ALTERNATIVES}, got {num_alternatives}"
        )
    if num_alternatives > limits.MAX_ALTERNATIVES:
        raise ValidationError(
            f"num_alternatives must be <= {limits.MAX_ALTERNATIVES}, got {num_alternatives}"
        )

    return num_alternatives


def validate_min_days(min_days: Union[int, str]) -> int:
    """
    Validate min_days parameter for earnings checks.

    Args:
        min_days: Minimum days until earnings

    Returns:
        Validated min_days

    Raises:
        ValidationError: If min_days is out of range
    """
    limits = ValidationLimits()

    if not isinstance(min_days, int):
        try:
            min_days = int(min_days)
        except (ValueError, TypeError):
            raise ValidationError(f"min_days must be integer, got {type(min_days).__name__}")

    if min_days < limits.MIN_DAYS:
        raise ValidationError(f"min_days must be >= {limits.MIN_DAYS}, got {min_days}")
    if min_days > limits.MAX_DAYS:
        raise ValidationError(f"min_days must be <= {limits.MAX_DAYS}, got {min_days}")

    return min_days


def validate_pause_seconds(pause_seconds: Union[int, str]) -> int:
    """
    Validate pause_seconds parameter for batch operations.

    Args:
        pause_seconds: Seconds to pause between batches

    Returns:
        Validated pause_seconds

    Raises:
        ValidationError: If pause_seconds is out of range
    """
    limits = ValidationLimits()

    if not isinstance(pause_seconds, int):
        try:
            pause_seconds = int(pause_seconds)
        except (ValueError, TypeError):
            raise ValidationError(
                f"pause_seconds must be integer, got {type(pause_seconds).__name__}"
            )

    if pause_seconds < limits.MIN_PAUSE_SECONDS:
        raise ValidationError(
            f"pause_seconds must be >= {limits.MIN_PAUSE_SECONDS}, got {pause_seconds}"
        )
    if pause_seconds > limits.MAX_PAUSE_SECONDS:
        raise ValidationError(
            f"pause_seconds must be <= {limits.MAX_PAUSE_SECONDS}, got {pause_seconds}"
        )

    return pause_seconds


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def safe_validate_symbol(symbol: str, default: Optional[str] = None) -> Optional[str]:
    """
    Validiert Symbol ohne Exception zu werfen.

    Returns:
        Validiertes Symbol oder default bei Fehler
    """
    try:
        return validate_symbol(symbol)
    except ValidationError:
        return default


def is_valid_symbol(symbol: str) -> bool:
    """
    Prüft ob Symbol gültig ist.

    Returns:
        True wenn gültig, False sonst
    """
    try:
        validate_symbol(symbol)
        return True
    except ValidationError:
        return False


def is_etf(symbol: str) -> bool:
    """
    Prüft ob Symbol ein bekannter ETF ist.

    ETFs haben keine Earnings und sollten vom Earnings-Filter
    übersprungen werden, um unnötige API-Calls zu vermeiden.

    Args:
        symbol: Ticker-Symbol

    Returns:
        True wenn ETF, False sonst

    Examples:
        >>> is_etf("SPY")
        True
        >>> is_etf("AAPL")
        False
    """
    if symbol is None:
        return False
    return symbol.strip().upper() in ETF_SYMBOLS
